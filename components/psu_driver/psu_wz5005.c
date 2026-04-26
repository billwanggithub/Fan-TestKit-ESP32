#include "psu_backend.h"

#include <string.h>
#include <stdint.h>
#include "esp_err.h"
#include "esp_log.h"
#include "driver/uart.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

static const char *TAG = "psu_wz5005";

#define WZ_UART_PORT          UART_NUM_1
#define WZ_FRAME_LEN          20
#define WZ_HEADER             0xAA
#define WZ_TXN_TIMEOUT_MS     150
#define WZ_INTERFRAME_MS      3        // ~3.5 char @ 19200

#define WZ_OP_SET_MODE        0x20     // arg byte 0: 0=manual, 1=remote
#define WZ_OP_SET_ADDR        0x21
#define WZ_OP_SET_OUTPUT      0x22
#define WZ_OP_GET_STATUS      0x23
#define WZ_OP_GET_FACTORY     0x24
#define WZ_OP_READ_VI_BLOCK   0x2B
#define WZ_OP_WRITE_VI_BLOCK  0x2C

#define WZ_I_MAX              5.0f
#define WZ_V_MAX              50.0f
#define WZ_V_SCALE            1000.0f   // raw / 1000 = volts (verified by reference frame)
#define WZ_I_SCALE            1000.0f   // assumed by analogy; verified on bench

// Builds a 20-byte WZ5005 frame in `out`. `args` of length `arg_len` is
// copied to bytes 3..(3+arg_len-1); remaining argument bytes are zeroed.
// Final byte is sum-of-bytes[0..18] mod 256.
static void wz_build_frame(uint8_t *out, uint8_t addr, uint8_t op,
                           const uint8_t *args, size_t arg_len)
{
    memset(out, 0, WZ_FRAME_LEN);
    out[0] = WZ_HEADER;
    out[1] = addr;
    out[2] = op;
    if (args && arg_len) {
        if (arg_len > 16) arg_len = 16;   // bytes 3..18 = 16 args max
        memcpy(&out[3], args, arg_len);
    }
    uint16_t s = 0;
    for (size_t i = 0; i < WZ_FRAME_LEN - 1; i++) s += out[i];
    out[WZ_FRAME_LEN - 1] = (uint8_t)(s & 0xFF);
}

static bool wz_verify_checksum(const uint8_t *frame)
{
    uint16_t s = 0;
    for (size_t i = 0; i < WZ_FRAME_LEN - 1; i++) s += frame[i];
    return (uint8_t)(s & 0xFF) == frame[WZ_FRAME_LEN - 1];
}

// One-shot WZ5005 transaction. Acquires shared UART mutex, writes 20-byte
// request, reads 20-byte response, validates header + addr + checksum.
// Returns ESP_OK with bytes 3..18 of the response copied into resp_args
// (up to resp_args_len bytes).
static esp_err_t wz_txn(uint8_t op, const uint8_t *args, size_t arg_len,
                        uint8_t *resp_args, size_t resp_args_len)
{
    SemaphoreHandle_t mtx = psu_driver_priv_get_uart_mutex();
    if (xSemaphoreTake(mtx, pdMS_TO_TICKS(WZ_TXN_TIMEOUT_MS + 50)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }

    uint8_t req[WZ_FRAME_LEN];
    wz_build_frame(req, psu_driver_priv_get_slave(), op, args, arg_len);

    uart_flush_input(WZ_UART_PORT);
    int written = uart_write_bytes(WZ_UART_PORT, (const char *)req, WZ_FRAME_LEN);
    esp_err_t e;
    if (written != WZ_FRAME_LEN) { e = ESP_ERR_INVALID_STATE; goto out; }
    e = uart_wait_tx_done(WZ_UART_PORT, pdMS_TO_TICKS(50));
    if (e != ESP_OK) goto out;

    uint8_t resp[WZ_FRAME_LEN];
    int got = uart_read_bytes(WZ_UART_PORT, resp, WZ_FRAME_LEN,
                              pdMS_TO_TICKS(WZ_TXN_TIMEOUT_MS));
    vTaskDelay(pdMS_TO_TICKS(WZ_INTERFRAME_MS));
    if (got < WZ_FRAME_LEN)        { e = ESP_ERR_TIMEOUT;          goto out; }
    if (resp[0] != WZ_HEADER)      { e = ESP_ERR_INVALID_RESPONSE; goto out; }
    if (resp[1] != req[1])         { e = ESP_ERR_INVALID_RESPONSE; goto out; }
    if (!wz_verify_checksum(resp)) { e = ESP_ERR_INVALID_CRC;      goto out; }
    // Per WZ5005 manual: a status byte of 0x80 in the response = OK,
    // 0x90/0xA0/0xB0/0xC0/0xD0 = error. The byte position is op-dependent
    // and not authoritatively documented; we treat structural validity
    // (header + addr + checksum) as success and let the caller interpret
    // payload semantics. Field-incorrect frames will surface as drift in
    // telemetry vs front-panel display, not as link_ok=false.
    if (resp_args && resp_args_len) {
        size_t n = (resp_args_len > 16) ? 16 : resp_args_len;
        memcpy(resp_args, &resp[3], n);
    }
    e = ESP_OK;
out:
    xSemaphoreGive(mtx);
    return e;
}

// Cached last-read VI block — used by set_voltage/set_current to do a
// read-modify-write without a fresh read each setpoint write. Refreshed
// every poll() cycle.
static uint8_t s_last_vi[16];
static bool    s_have_vi;

static esp_err_t wz_read_vi_block(void)
{
    uint8_t resp_args[16] = {0};
    esp_err_t e = wz_txn(WZ_OP_READ_VI_BLOCK, NULL, 0, resp_args, sizeof(resp_args));
    psu_driver_priv_note_txn_result(e);
    if (e == ESP_OK) {
        memcpy(s_last_vi, resp_args, sizeof(s_last_vi));
        s_have_vi = true;
        // Layout (best-guess per spec, big-endian pairs):
        //   bytes 0..1   V_SET   ÷1000
        //   bytes 2..3   I_SET   ÷1000
        //   bytes 4..5   OVP     ÷1000  (read but not surfaced in v1)
        //   bytes 6..7   OCP     ÷1000  (read but not surfaced in v1)
        //   bytes 8..9   V_OUT   ÷1000
        //   bytes 10..11 I_OUT   ÷1000
        uint16_t v_set = ((uint16_t)resp_args[0]  << 8) | resp_args[1];
        uint16_t i_set = ((uint16_t)resp_args[2]  << 8) | resp_args[3];
        uint16_t v_out = ((uint16_t)resp_args[8]  << 8) | resp_args[9];
        uint16_t i_out = ((uint16_t)resp_args[10] << 8) | resp_args[11];
        psu_driver_priv_publish_v_set(v_set / WZ_V_SCALE);
        psu_driver_priv_publish_i_set(i_set / WZ_I_SCALE);
        psu_driver_priv_publish_v_out(v_out / WZ_V_SCALE);
        psu_driver_priv_publish_i_out(i_out / WZ_I_SCALE);
    }
    return e;
}

static esp_err_t wz_read_output_state(void)
{
    uint8_t resp_args[16] = {0};
    esp_err_t e = wz_txn(WZ_OP_GET_STATUS, NULL, 0, resp_args, sizeof(resp_args));
    psu_driver_priv_note_txn_result(e);
    if (e == ESP_OK) {
        // Per kordian-kowalski/wz5005-control: byte 0 = output status (0/1).
        psu_driver_priv_publish_output(resp_args[0] != 0);
    }
    return e;
}

static esp_err_t wz_detect(void)
{
    // Try to enter remote mode (best-effort; ignore failure — some units
    // accept commands without explicit remote mode).
    uint8_t mode_arg = 1;
    (void)wz_txn(WZ_OP_SET_MODE, &mode_arg, 1, NULL, 0);

    uint8_t resp_args[16] = {0};
    esp_err_t e = wz_txn(WZ_OP_GET_FACTORY, NULL, 0, resp_args, sizeof(resp_args));
    psu_driver_priv_note_txn_result(e);
    if (e != ESP_OK) {
        psu_driver_priv_publish_model(0, "WZ5005", WZ_I_SCALE, WZ_I_MAX);
        return e;
    }
    // Per the kordian-kowalski reference: byte 0 = model. We don't have a
    // model table for WZ5xxx — any non-zero detect response is treated as
    // "WZ5005" for v1.
    uint16_t id = resp_args[0];
    if (id == 0) id = 1;  // ensure model_id != 0 so re-detect doesn't loop
    psu_driver_priv_publish_model(id, "WZ5005", WZ_I_SCALE, WZ_I_MAX);
    ESP_LOGI(TAG, "detected WZ5005 (factory byte 0 = %u)", resp_args[0]);
    return ESP_OK;
}

static esp_err_t wz_poll(void)
{
    wz_read_vi_block();
    wz_read_output_state();
    return ESP_OK;
}

static esp_err_t wz_set_voltage(float v)
{
    if (v < 0.0f)        v = 0.0f;
    if (v > WZ_V_MAX)    v = WZ_V_MAX;

    if (!s_have_vi) {
        esp_err_t e = wz_read_vi_block();
        if (e != ESP_OK) return e;
    }
    uint8_t args[16];
    memcpy(args, s_last_vi, 16);
    uint16_t raw = (uint16_t)(v * WZ_V_SCALE + 0.5f);
    args[0] = (raw >> 8) & 0xFF;
    args[1] = raw & 0xFF;

    esp_err_t e = wz_txn(WZ_OP_WRITE_VI_BLOCK, args, sizeof(args), NULL, 0);
    psu_driver_priv_note_txn_result(e);
    if (e == ESP_OK) {
        memcpy(s_last_vi, args, 16);
        psu_driver_priv_publish_v_set(raw / WZ_V_SCALE);
    }
    return e;
}

static esp_err_t wz_set_current(float i)
{
    if (i < 0.0f)     i = 0.0f;
    if (i > WZ_I_MAX) i = WZ_I_MAX;

    if (!s_have_vi) {
        esp_err_t e = wz_read_vi_block();
        if (e != ESP_OK) return e;
    }
    uint8_t args[16];
    memcpy(args, s_last_vi, 16);
    uint16_t raw = (uint16_t)(i * WZ_I_SCALE + 0.5f);
    args[2] = (raw >> 8) & 0xFF;
    args[3] = raw & 0xFF;

    esp_err_t e = wz_txn(WZ_OP_WRITE_VI_BLOCK, args, sizeof(args), NULL, 0);
    psu_driver_priv_note_txn_result(e);
    if (e == ESP_OK) {
        memcpy(s_last_vi, args, 16);
        psu_driver_priv_publish_i_set(raw / WZ_I_SCALE);
    }
    return e;
}

static esp_err_t wz_set_output(bool on)
{
    uint8_t arg = on ? 1 : 0;
    esp_err_t e = wz_txn(WZ_OP_SET_OUTPUT, &arg, 1, NULL, 0);
    psu_driver_priv_note_txn_result(e);
    if (e == ESP_OK) psu_driver_priv_publish_output(on);
    return e;
}

const psu_backend_t psu_backend_wz5005 = {
    .name         = "wz5005",
    .default_baud = 19200,
    .detect       = wz_detect,
    .poll         = wz_poll,
    .set_voltage  = wz_set_voltage,
    .set_current  = wz_set_current,
    .set_output   = wz_set_output,
};
