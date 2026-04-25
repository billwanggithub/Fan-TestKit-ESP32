#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define GPIO_IO_PIN_COUNT 16

typedef enum {
    GPIO_IO_MODE_INPUT_PULLDOWN = 0,
    GPIO_IO_MODE_INPUT_PULLUP   = 1,
    GPIO_IO_MODE_INPUT_FLOATING = 2,
    GPIO_IO_MODE_OUTPUT         = 3,
} gpio_io_mode_t;

typedef struct {
    gpio_io_mode_t mode;
    bool           level;     // input: last sampled; output: driven
    bool           pulsing;   // true while a one-shot pulse is in flight
} gpio_io_state_t;

esp_err_t gpio_io_init(void);

esp_err_t gpio_io_set_mode (uint8_t idx, gpio_io_mode_t mode);
esp_err_t gpio_io_set_level(uint8_t idx, bool level);
esp_err_t gpio_io_pulse    (uint8_t idx, uint32_t width_ms);

void      gpio_io_get_state(uint8_t idx, gpio_io_state_t *out);
void      gpio_io_get_all  (gpio_io_state_t out[GPIO_IO_PIN_COUNT]);

esp_err_t gpio_io_set_power(bool on);
bool      gpio_io_get_power(void);

uint32_t  gpio_io_get_pulse_width_ms(void);
esp_err_t gpio_io_set_pulse_width_ms(uint32_t width_ms);

#ifdef __cplusplus
}
#endif
