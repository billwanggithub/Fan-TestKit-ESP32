#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct psu_backend {
    const char *name;                          // "riden" / "xy_sk120" / "wz5005"
    int         default_baud;                  // matches CLAUDE.md / spec; 115200 / 115200 / 19200

    esp_err_t (*detect)(void);                 // sets model_id, i_scale, i_max via publish helpers
    esp_err_t (*poll)(void);                   // 5 Hz tick: read v/i set+out + output state
    esp_err_t (*set_voltage)(float v);
    esp_err_t (*set_current)(float i);
    esp_err_t (*set_output)(bool on);
} psu_backend_t;

extern const psu_backend_t psu_backend_riden;
extern const psu_backend_t psu_backend_xy_sk120;
extern const psu_backend_t psu_backend_wz5005;

// ----- shared state, owned by psu_driver.c, exposed to backends -----

uint8_t           psu_driver_priv_get_slave(void);              // current slave addr
SemaphoreHandle_t psu_driver_priv_get_uart_mutex(void);          // for backend-rolled UART txns

void psu_driver_priv_publish_v_set(float v);
void psu_driver_priv_publish_i_set(float i);
void psu_driver_priv_publish_v_out(float v);
void psu_driver_priv_publish_i_out(float i);
void psu_driver_priv_publish_output(bool on);
void psu_driver_priv_publish_model(uint16_t id, const char *name,
                                   float i_scale_div, float i_max);
void psu_driver_priv_note_txn_result(esp_err_t e);

#ifdef __cplusplus
}
#endif
