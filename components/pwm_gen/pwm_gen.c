#include "pwm_gen.h"

#include <math.h>
#include <string.h>

#include "driver/mcpwm_prelude.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// MCPWM 的 timer counter 是 16-bit（MCPWM_LL_MAX_COUNT_VALUE = 0x10000），所以
// period_ticks 必須 ∈ [2, 65535]。一個固定 resolution_hz 覆蓋不了 1 Hz ~ 1 MHz
// 六個 decade，於是用 3-band 動態 resolution：每次 pwm_gen_set() 依 freq
// 挑「能在 16-bit counter 內塞下 period」的最高 resolution。同 band 內走
// TEZ latch glitch-free 更新，跨 band 需要 teardown→recreate timer（oper /
// cmpr / gen 物件保留並重新 connect）、會有 ~tens of µs 的 output 斷點。
//
//   Band  resolution_hz  freq range       period_ticks    duty bits
//   HI    10 MHz         153 Hz – 1 MHz   10 – 65359      3.3 – 16
//   MID   160 kHz        3 Hz – 152 Hz    1052 – 53333    10 – 16
//   LO    1 kHz          1 Hz – 2 Hz      500 – 1000      9 – 10
#define PWM_FREQ_MIN_HZ 1u
#define PWM_FREQ_MAX_HZ 1000000u

typedef struct {
    uint32_t resolution_hz;
    uint32_t freq_min;   // inclusive lower bound; freq < freq_min falls to next band
} pwm_band_t;

// Ordered by descending resolution. First entry with freq >= freq_min wins.
static const pwm_band_t s_bands[] = {
    { 10000000u, 153u },   // HI
    {   160000u,   3u },   // MID
    {     1000u,   1u },   // LO
};

static const char *TAG = "pwm_gen";

static struct {
    bool                      initialised;
    gpio_num_t                pwm_gpio;
    gpio_num_t                trigger_gpio;
    mcpwm_timer_handle_t      timer;
    mcpwm_oper_handle_t       oper;
    mcpwm_cmpr_handle_t       cmpr;
    mcpwm_gen_handle_t        gen;
    uint32_t                  freq_hz;
    float                     duty_pct;
    uint32_t                  period_ticks;
    uint32_t                  resolution_hz;
} s_pwm;

static const pwm_band_t *pick_band(uint32_t freq_hz)
{
    for (size_t i = 0; i < sizeof(s_bands) / sizeof(s_bands[0]); ++i) {
        if (freq_hz >= s_bands[i].freq_min) return &s_bands[i];
    }
    return NULL;
}

static inline uint32_t freq_to_period_ticks(uint32_t resolution_hz, uint32_t freq_hz)
{
    if (freq_hz == 0) return 0;
    return resolution_hz / freq_hz;
}

uint8_t pwm_gen_duty_resolution_bits(uint32_t freq_hz)
{
    const pwm_band_t *band = pick_band(freq_hz);
    if (!band) return 0;
    uint32_t period = freq_to_period_ticks(band->resolution_hz, freq_hz);
    if (period < 2) return 0;
    uint8_t bits = 0;
    while ((1u << bits) <= period) bits++;
    return bits ? (uint8_t)(bits - 1) : 0;
}

esp_err_t pwm_gen_init(const pwm_gen_config_t *cfg)
{
    if (!cfg) return ESP_ERR_INVALID_ARG;
    if (s_pwm.initialised) return ESP_ERR_INVALID_STATE;

    memset(&s_pwm, 0, sizeof(s_pwm));
    s_pwm.pwm_gpio     = cfg->pwm_gpio;
    s_pwm.trigger_gpio = cfg->trigger_gpio;

    // Start at a safe known state: 1 kHz, 0% duty. Falls into the HI band.
    const uint32_t init_freq = 1000;
    const pwm_band_t *band = pick_band(init_freq);
    s_pwm.resolution_hz = band->resolution_hz;
    s_pwm.period_ticks  = freq_to_period_ticks(band->resolution_hz, init_freq);
    s_pwm.freq_hz       = init_freq;
    s_pwm.duty_pct      = 0.0f;

    mcpwm_timer_config_t timer_cfg = {
        .group_id      = 0,
        .clk_src       = MCPWM_TIMER_CLK_SRC_DEFAULT,
        .resolution_hz = s_pwm.resolution_hz,
        .count_mode    = MCPWM_TIMER_COUNT_MODE_UP,
        .period_ticks  = s_pwm.period_ticks,
    };
    ESP_ERROR_CHECK(mcpwm_new_timer(&timer_cfg, &s_pwm.timer));

    mcpwm_operator_config_t oper_cfg = { .group_id = 0 };
    ESP_ERROR_CHECK(mcpwm_new_operator(&oper_cfg, &s_pwm.oper));
    ESP_ERROR_CHECK(mcpwm_operator_connect_timer(s_pwm.oper, s_pwm.timer));

    mcpwm_comparator_config_t cmpr_cfg = { .flags.update_cmp_on_tez = true };
    ESP_ERROR_CHECK(mcpwm_new_comparator(s_pwm.oper, &cmpr_cfg, &s_pwm.cmpr));
    ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(s_pwm.cmpr, 0));

    mcpwm_generator_config_t gen_cfg = { .gen_gpio_num = s_pwm.pwm_gpio };
    ESP_ERROR_CHECK(mcpwm_new_generator(s_pwm.oper, &gen_cfg, &s_pwm.gen));

    // High on timer empty, low when compare hits → standard PWM.
    ESP_ERROR_CHECK(mcpwm_generator_set_action_on_timer_event(
        s_pwm.gen, MCPWM_GEN_TIMER_EVENT_ACTION(
            MCPWM_TIMER_DIRECTION_UP, MCPWM_TIMER_EVENT_EMPTY, MCPWM_GEN_ACTION_HIGH)));
    ESP_ERROR_CHECK(mcpwm_generator_set_action_on_compare_event(
        s_pwm.gen, MCPWM_GEN_COMPARE_EVENT_ACTION(
            MCPWM_TIMER_DIRECTION_UP, s_pwm.cmpr, MCPWM_GEN_ACTION_LOW)));

    // Trigger GPIO: plain push-pull, idle low.
    gpio_config_t io_cfg = {
        .pin_bit_mask = 1ULL << s_pwm.trigger_gpio,
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&io_cfg));
    gpio_set_level(s_pwm.trigger_gpio, 0);

    ESP_ERROR_CHECK(mcpwm_timer_enable(s_pwm.timer));
    ESP_ERROR_CHECK(mcpwm_timer_start_stop(s_pwm.timer, MCPWM_TIMER_START_NO_STOP));

    s_pwm.initialised = true;
    ESP_LOGI(TAG, "init ok: pwm_gpio=%d trigger_gpio=%d freq=%lu duty=%.1f%% res=%lu",
             s_pwm.pwm_gpio, s_pwm.trigger_gpio,
             (unsigned long)s_pwm.freq_hz, s_pwm.duty_pct,
             (unsigned long)s_pwm.resolution_hz);
    return ESP_OK;
}

// Tear down the current timer and bring up a new one with a different
// resolution_hz / period_ticks combination. Operator / comparator / generator
// objects are retained and reconnected — their action config (high on TEZ,
// low on compare) is preserved. Call site already validated band and period.
static esp_err_t reconfigure_for_band(const pwm_band_t *band,
                                      uint32_t new_period,
                                      uint32_t new_compare)
{
    esp_err_t err;

    err = mcpwm_timer_start_stop(s_pwm.timer, MCPWM_TIMER_STOP_EMPTY);
    if (err != ESP_OK) { ESP_LOGE(TAG, "timer stop: %s", esp_err_to_name(err)); return err; }

    err = mcpwm_timer_disable(s_pwm.timer);
    if (err != ESP_OK) { ESP_LOGE(TAG, "timer disable: %s", esp_err_to_name(err)); return err; }

    err = mcpwm_del_timer(s_pwm.timer);
    if (err != ESP_OK) { ESP_LOGE(TAG, "timer del: %s", esp_err_to_name(err)); return err; }
    s_pwm.timer = NULL;

    mcpwm_timer_config_t timer_cfg = {
        .group_id      = 0,
        .clk_src       = MCPWM_TIMER_CLK_SRC_DEFAULT,
        .resolution_hz = band->resolution_hz,
        .count_mode    = MCPWM_TIMER_COUNT_MODE_UP,
        .period_ticks  = new_period,
    };
    err = mcpwm_new_timer(&timer_cfg, &s_pwm.timer);
    if (err != ESP_OK) { ESP_LOGE(TAG, "timer new: %s", esp_err_to_name(err)); return err; }

    err = mcpwm_operator_connect_timer(s_pwm.oper, s_pwm.timer);
    if (err != ESP_OK) { ESP_LOGE(TAG, "oper connect: %s", esp_err_to_name(err)); return err; }

    err = mcpwm_comparator_set_compare_value(s_pwm.cmpr, new_compare);
    if (err != ESP_OK) { ESP_LOGE(TAG, "cmpr set: %s", esp_err_to_name(err)); return err; }

    err = mcpwm_timer_enable(s_pwm.timer);
    if (err != ESP_OK) { ESP_LOGE(TAG, "timer enable: %s", esp_err_to_name(err)); return err; }

    err = mcpwm_timer_start_stop(s_pwm.timer, MCPWM_TIMER_START_NO_STOP);
    if (err != ESP_OK) { ESP_LOGE(TAG, "timer start: %s", esp_err_to_name(err)); return err; }

    return ESP_OK;
}

esp_err_t pwm_gen_set(uint32_t freq_hz, float duty_pct)
{
    if (!s_pwm.initialised) return ESP_ERR_INVALID_STATE;
    if (freq_hz < PWM_FREQ_MIN_HZ || freq_hz > PWM_FREQ_MAX_HZ) return ESP_ERR_INVALID_ARG;
    if (duty_pct < 0.0f || duty_pct > 100.0f) return ESP_ERR_INVALID_ARG;

    const pwm_band_t *band = pick_band(freq_hz);
    if (!band) return ESP_ERR_INVALID_ARG;

    uint32_t period = freq_to_period_ticks(band->resolution_hz, freq_hz);
    if (period < 2 || period > 65535) return ESP_ERR_INVALID_ARG;

    uint32_t compare = (uint32_t)lroundf((duty_pct / 100.0f) * (float)period);
    if (compare > period) compare = period;

    if (band->resolution_hz == s_pwm.resolution_hz) {
        // Same band → glitch-free TEZ-latched update.
        esp_err_t err = mcpwm_timer_set_period(s_pwm.timer, period);
        if (err != ESP_OK) return err;
        err = mcpwm_comparator_set_compare_value(s_pwm.cmpr, compare);
        if (err != ESP_OK) return err;
    } else {
        // Band crossing → teardown-reconfigure-restart (brief output glitch).
        esp_err_t err = reconfigure_for_band(band, period, compare);
        if (err != ESP_OK) return err;
    }

    s_pwm.period_ticks  = period;
    s_pwm.freq_hz       = freq_hz;
    s_pwm.duty_pct      = duty_pct;
    s_pwm.resolution_hz = band->resolution_hz;

    // Trigger pulse: a software "settings changed" edge for scope latching.
    // 1 Hz gives 1000 µs; 1 MHz gives 200 µs — both cleanly observable.
    int64_t pulse_us = 2 + 1000000 / (int64_t)freq_hz;
    if (pulse_us > 1000) pulse_us = 1000;
    if (pulse_us <  200) pulse_us =  200;
    gpio_set_level(s_pwm.trigger_gpio, 1);
    esp_rom_delay_us((uint32_t)pulse_us);
    gpio_set_level(s_pwm.trigger_gpio, 0);

    return ESP_OK;
}

void pwm_gen_get(uint32_t *freq_hz, float *duty_pct)
{
    if (freq_hz)  *freq_hz  = s_pwm.freq_hz;
    if (duty_pct) *duty_pct = s_pwm.duty_pct;
}
