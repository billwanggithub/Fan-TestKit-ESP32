#include "psu_driver.h"
#include "psu_backend.h"
#include "psu_modbus_rtu.h"

#include <stdatomic.h>
#include <string.h>

#include "esp_log.h"
#include "driver/uart.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

static const char *TAG = "psu_driver";

#define PSU_UART_PORT     UART_NUM_1
#define PSU_RX_BUF_SIZE   256
#define PSU_TX_BUF_SIZE   256

#define NVS_NAMESPACE     "psu_driver"
#define NVS_KEY_SLAVE     "slave_addr"

// ---- Riden RD60xx register map -------------------------------------------
#define REG_MODEL    0x0000
#define REG_V_SET    0x0008
#define REG_I_SET    0x0009
#define REG_V_OUT    0x000A
#define REG_I_OUT    0x000B
#define REG_OUTPUT   0x0012

#define POLL_PERIOD_MS       200    // 5 Hz
#define LINK_FAIL_THRESHOLD  5

static _Atomic uint8_t s_slave_addr;

// Atomic publish — bit-punned floats and bools.
static _Atomic uint32_t s_v_set_bits, s_i_set_bits, s_v_out_bits, s_i_out_bits;
static _Atomic uint8_t  s_output_on;
static _Atomic uint8_t  s_link_ok;
static _Atomic uint16_t s_model_id;
static _Atomic uint32_t s_i_scale_bits;   // float bit-punned, 100.0 or 1000.0

static const struct {
    uint16_t    id;
    const char *name;
    float       i_scale;   // raw_register / i_scale = amps
    float       i_max;     // device current ceiling for slider/clamp
} RD_MODELS[] = {
    { 60062, "RD6006",  1000.0f,  6.0f },
    { 60065, "RD6006P", 1000.0f,  6.0f },
    { 60121, "RD6012",   100.0f, 12.0f },
    { 60125, "RD6012P",  100.0f, 12.0f },
    { 60181, "RD6018",   100.0f, 18.0f },
    { 60241, "RD6024",   100.0f, 24.0f },
};
#define RD_MODELS_N (sizeof(RD_MODELS) / sizeof(RD_MODELS[0]))

static TaskHandle_t s_psu_task;
static SemaphoreHandle_t s_uart_mutex;

SemaphoreHandle_t psu_driver_priv_get_uart_mutex(void)
{
    return s_uart_mutex;
}

static inline void store_f(_Atomic uint32_t *slot, float v)
{
    uint32_t bits;
    memcpy(&bits, &v, sizeof(bits));
    atomic_store_explicit(slot, bits, memory_order_relaxed);
}

static inline float load_f(_Atomic uint32_t *slot)
{
    uint32_t bits = atomic_load_explicit(slot, memory_order_relaxed);
    float v;
    memcpy(&v, &bits, sizeof(v));
    return v;
}

// ---- NVS helpers -----------------------------------------------------------

static void load_slave_addr_from_nvs(void)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) != ESP_OK) {
        atomic_store_explicit(&s_slave_addr,
                              (uint8_t)CONFIG_APP_PSU_SLAVE_DEFAULT,
                              memory_order_relaxed);
        return;
    }
    uint8_t v = (uint8_t)CONFIG_APP_PSU_SLAVE_DEFAULT;
    (void)nvs_get_u8(h, NVS_KEY_SLAVE, &v);
    if (v < 1 || v > 247) v = (uint8_t)CONFIG_APP_PSU_SLAVE_DEFAULT;
    atomic_store_explicit(&s_slave_addr, v, memory_order_relaxed);
    nvs_close(h);
    ESP_LOGI(TAG, "slave addr from NVS: %u", v);
}

static void save_slave_addr_to_nvs(uint8_t v)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) != ESP_OK) return;
    nvs_set_u8(h, NVS_KEY_SLAVE, v);
    nvs_commit(h);
    nvs_close(h);
}

// ---- Polling task helpers --------------------------------------------------

static void detect_model(void)
{
    uint16_t model = 0;
    uint8_t slave = atomic_load_explicit(&s_slave_addr, memory_order_relaxed);
    if (psu_modbus_rtu_read_holding(slave, REG_MODEL, 1, &model) != ESP_OK) {
        ESP_LOGW(TAG, "model detect failed (PSU offline at boot?); falling back to RD6006 scale");
        atomic_store_explicit(&s_model_id, 0, memory_order_relaxed);
        store_f(&s_i_scale_bits, 1000.0f);
        return;
    }
    float scale = 1000.0f;
    const char *name = "unknown";
    for (size_t i = 0; i < RD_MODELS_N; i++) {
        if (RD_MODELS[i].id == model) {
            scale = RD_MODELS[i].i_scale;
            name  = RD_MODELS[i].name;
            break;
        }
    }
    atomic_store_explicit(&s_model_id, model, memory_order_relaxed);
    store_f(&s_i_scale_bits, scale);
    ESP_LOGI(TAG, "detected model %u (%s, I scale = ÷%.0f)",
             model, name, (double)scale);
}

// Called from both psu_task (polling) and control_task (setpoint writes), so
// the failure counter must be atomic. memory_order_relaxed is fine — the only
// invariant we need is that the counter monotonically increases on failure
// and resets to zero on success. The transition log lines may double-fire
// across concurrent writers in a tight race; that's fine, it's just a log.
static _Atomic int s_link_fails;

static void note_txn_result(esp_err_t e)
{
    if (e == ESP_OK) {
        int prev = atomic_exchange_explicit(&s_link_fails, 0, memory_order_relaxed);
        if (prev >= LINK_FAIL_THRESHOLD) {
            ESP_LOGI(TAG, "link recovered");
        }
        atomic_store_explicit(&s_link_ok, 1, memory_order_relaxed);
    } else {
        // CAS-bounded increment: cap the counter at LINK_FAIL_THRESHOLD so it
        // can't wrap. This also makes the "==threshold" edge fire exactly once.
        int cur = atomic_load_explicit(&s_link_fails, memory_order_relaxed);
        while (cur < LINK_FAIL_THRESHOLD) {
            if (atomic_compare_exchange_weak_explicit(&s_link_fails, &cur, cur + 1,
                    memory_order_relaxed, memory_order_relaxed)) {
                if (cur + 1 == LINK_FAIL_THRESHOLD) {
                    ESP_LOGW(TAG, "link lost: %s", esp_err_to_name(e));
                    atomic_store_explicit(&s_link_ok, 0, memory_order_relaxed);
                }
                break;
            }
            // cur was reloaded by the CAS; loop and retry.
        }
    }
}

static void psu_task_fn(void *arg)
{
    (void)arg;
    detect_model();

    const TickType_t period = pdMS_TO_TICKS(POLL_PERIOD_MS);
    TickType_t last = xTaskGetTickCount();
    while (true) {
        // Re-detect once if we missed at boot AND link is now up — best-effort.
        if (atomic_load_explicit(&s_model_id, memory_order_relaxed) == 0 &&
            atomic_load_explicit(&s_link_ok,  memory_order_relaxed) == 1) {
            detect_model();
        }

        uint8_t slave = atomic_load_explicit(&s_slave_addr, memory_order_relaxed);

        // Read [V_SET, I_SET, V_OUT, I_OUT] in one transaction (4 contiguous regs).
        uint16_t r[4] = {0};
        esp_err_t e = psu_modbus_rtu_read_holding(slave, REG_V_SET, 4, r);
        note_txn_result(e);
        if (e == ESP_OK) {
            float i_div = load_f(&s_i_scale_bits);
            store_f(&s_v_set_bits, r[0] / 100.0f);
            store_f(&s_i_set_bits, r[1] / i_div);
            store_f(&s_v_out_bits, r[2] / 100.0f);
            store_f(&s_i_out_bits, r[3] / i_div);
        }

        // Read OUTPUT separately (non-contiguous with the V/I block).
        uint16_t o = 0;
        e = psu_modbus_rtu_read_holding(slave, REG_OUTPUT, 1, &o);
        note_txn_result(e);
        if (e == ESP_OK) {
            atomic_store_explicit(&s_output_on, o ? 1 : 0, memory_order_relaxed);
        }

        vTaskDelayUntil(&last, period);
    }
}

// ---- Public API (Tasks 5-8) -----------------------------------------------

esp_err_t psu_driver_init(void)
{
    // Create the mutex *first* so any subsequent error path that returns
    // before the task starts can still be safely re-entered.
    s_uart_mutex = xSemaphoreCreateMutex();
    if (!s_uart_mutex) return ESP_ERR_NO_MEM;

    load_slave_addr_from_nvs();

    const uart_config_t cfg = {
        .baud_rate  = CONFIG_APP_PSU_UART_BAUD,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    esp_err_t e = uart_driver_install(PSU_UART_PORT, PSU_RX_BUF_SIZE,
                                      PSU_TX_BUF_SIZE, 0, NULL, 0);
    if (e != ESP_OK) { ESP_LOGE(TAG, "driver_install: %s", esp_err_to_name(e)); return e; }
    e = uart_param_config(PSU_UART_PORT, &cfg);
    if (e != ESP_OK) { ESP_LOGE(TAG, "param_config: %s", esp_err_to_name(e));  return e; }
    e = uart_set_pin(PSU_UART_PORT,
                     CONFIG_APP_PSU_UART_TX_GPIO,
                     CONFIG_APP_PSU_UART_RX_GPIO,
                     UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (e != ESP_OK) { ESP_LOGE(TAG, "set_pin: %s", esp_err_to_name(e));       return e; }

    ESP_LOGI(TAG, "UART1 ready: tx=%d rx=%d baud=%d slave=%u",
             CONFIG_APP_PSU_UART_TX_GPIO, CONFIG_APP_PSU_UART_RX_GPIO,
             CONFIG_APP_PSU_UART_BAUD,
             atomic_load_explicit(&s_slave_addr, memory_order_relaxed));

    return ESP_OK;
}
esp_err_t psu_driver_start(void)
{
    if (s_psu_task) return ESP_ERR_INVALID_STATE;
    BaseType_t ok = xTaskCreate(psu_task_fn, "psu_driver", 4096, NULL, 4, &s_psu_task);
    return ok == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
esp_err_t psu_driver_set_voltage(float v)
{
    if (v < 0.0f)  v = 0.0f;
    if (v > 60.0f) v = 60.0f;
    uint16_t raw = (uint16_t)(v * 100.0f + 0.5f);
    uint8_t slave = atomic_load_explicit(&s_slave_addr, memory_order_relaxed);
    esp_err_t e = psu_modbus_rtu_write_single(slave, REG_V_SET, raw);
    note_txn_result(e);
    if (e == ESP_OK) {
        store_f(&s_v_set_bits, raw / 100.0f);
    } else {
        ESP_LOGW(TAG, "set_voltage(%.2f V) failed: %s", (double)v, esp_err_to_name(e));
    }
    return e;
}

esp_err_t psu_driver_set_current(float i)
{
    if (i < 0.0f) i = 0.0f;
    float i_div = load_f(&s_i_scale_bits);
    if (i_div < 1.0f) i_div = 1000.0f;   // before model detect
    float i_max = psu_driver_get_i_max();
    if (i > i_max) i = i_max;
    uint16_t raw = (uint16_t)(i * i_div + 0.5f);
    uint8_t slave = atomic_load_explicit(&s_slave_addr, memory_order_relaxed);
    esp_err_t e = psu_modbus_rtu_write_single(slave, REG_I_SET, raw);
    note_txn_result(e);
    if (e == ESP_OK) {
        store_f(&s_i_set_bits, raw / i_div);
    } else {
        ESP_LOGW(TAG, "set_current(%.3f A) failed: %s", (double)i, esp_err_to_name(e));
    }
    return e;
}

esp_err_t psu_driver_set_output(bool on)
{
    uint8_t slave = atomic_load_explicit(&s_slave_addr, memory_order_relaxed);
    esp_err_t e = psu_modbus_rtu_write_single(slave, REG_OUTPUT, on ? 1 : 0);
    note_txn_result(e);
    if (e == ESP_OK) {
        atomic_store_explicit(&s_output_on, on ? 1 : 0, memory_order_relaxed);
    } else {
        ESP_LOGW(TAG, "set_output(%d) failed: %s", on ? 1 : 0, esp_err_to_name(e));
    }
    return e;
}
uint8_t psu_driver_get_slave_addr(void)
{
    return atomic_load_explicit(&s_slave_addr, memory_order_relaxed);
}

esp_err_t psu_driver_set_slave_addr(uint8_t addr)
{
    if (addr < 1 || addr > 247) return ESP_ERR_INVALID_ARG;
    atomic_store_explicit(&s_slave_addr, addr, memory_order_relaxed);
    save_slave_addr_to_nvs(addr);
    ESP_LOGI(TAG, "slave addr set to %u (NVS)", addr);
    return ESP_OK;
}

void psu_driver_get_telemetry(psu_driver_telemetry_t *out)
{
    if (!out) return;
    out->v_set       = load_f(&s_v_set_bits);
    out->i_set       = load_f(&s_i_set_bits);
    out->v_out       = load_f(&s_v_out_bits);
    out->i_out       = load_f(&s_i_out_bits);
    out->output_on   = atomic_load_explicit(&s_output_on, memory_order_relaxed) != 0;
    out->link_ok     = atomic_load_explicit(&s_link_ok,   memory_order_relaxed) != 0;
    out->model_id    = atomic_load_explicit(&s_model_id,  memory_order_relaxed);
    out->i_scale_div = load_f(&s_i_scale_bits);
}

const char *psu_driver_get_model_name(void)
{
    uint16_t id = atomic_load_explicit(&s_model_id, memory_order_relaxed);
    for (size_t i = 0; i < RD_MODELS_N; i++) {
        if (RD_MODELS[i].id == id) return RD_MODELS[i].name;
    }
    return "unknown";
}

float psu_driver_get_i_max(void)
{
    uint16_t id = atomic_load_explicit(&s_model_id, memory_order_relaxed);
    for (size_t i = 0; i < RD_MODELS_N; i++) {
        if (RD_MODELS[i].id == id) return RD_MODELS[i].i_max;
    }
    // Conservative default: RD6006 ceiling. Used pre-detect or unknown model.
    return 6.0f;
}

// CRC correctness is verified end-to-end: a bad implementation produces
// frames the supply rejects, every transaction times out, and link_ok stays
// false — the dashboard immediately shows "PSU offline". A boot-time
// __builtin_trap was tried earlier but the constant we compared against
// turned out to be wrong, bricking boot; the on-the-wire feedback loop is
// the real test anyway.
