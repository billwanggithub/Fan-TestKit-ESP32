#include "gpio_io.h"

#include "esp_log.h"

static const char *TAG = "gpio_io";

esp_err_t gpio_io_init(void)            { ESP_LOGI(TAG, "gpio_io stub init"); return ESP_OK; }

esp_err_t gpio_io_set_mode (uint8_t idx, gpio_io_mode_t mode)  { (void)idx; (void)mode;  return ESP_ERR_NOT_SUPPORTED; }
esp_err_t gpio_io_set_level(uint8_t idx, bool level)           { (void)idx; (void)level; return ESP_ERR_NOT_SUPPORTED; }
esp_err_t gpio_io_pulse    (uint8_t idx, uint32_t width_ms)    { (void)idx; (void)width_ms; return ESP_ERR_NOT_SUPPORTED; }

void gpio_io_get_state(uint8_t idx, gpio_io_state_t *out) { (void)idx; if (out) *out = (gpio_io_state_t){0}; }
void gpio_io_get_all  (gpio_io_state_t out[GPIO_IO_PIN_COUNT])
{
    if (!out) return;
    for (int i = 0; i < GPIO_IO_PIN_COUNT; i++) out[i] = (gpio_io_state_t){0};
}

esp_err_t gpio_io_set_power(bool on)         { (void)on;  return ESP_ERR_NOT_SUPPORTED; }
bool      gpio_io_get_power(void)            { return false; }

uint32_t  gpio_io_get_pulse_width_ms(void)              { return 100; }
esp_err_t gpio_io_set_pulse_width_ms(uint32_t width_ms) { (void)width_ms; return ESP_ERR_NOT_SUPPORTED; }
