#include "psu_modbus_rtu.h"
#include "psu_backend.h"

#include <string.h>
#include "driver/uart.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

static const char *TAG = "psu_modbus_rtu";

#define PSU_UART_PORT        UART_NUM_1
#define PSU_TXN_TIMEOUT_MS   100
#define PSU_INTERFRAME_MS    2

// ---- Modbus-RTU CRC-16 (poly 0xA001, init 0xFFFF) -------------------------
static uint16_t modbus_crc16(const uint8_t *buf, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= buf[i];
        for (int b = 0; b < 8; b++) {
            if (crc & 1) crc = (crc >> 1) ^ 0xA001;
            else         crc >>= 1;
        }
    }
    return crc;
}

// Build "Read Holding Registers" (FC 0x03) request:
//   [slave][0x03][hi(addr)][lo(addr)][hi(n)][lo(n)][lo(crc)][hi(crc)]
static size_t build_read_holding(uint8_t *out, uint8_t slave, uint16_t addr, uint16_t n)
{
    out[0] = slave;
    out[1] = 0x03;
    out[2] = (addr >> 8) & 0xFF;
    out[3] = addr & 0xFF;
    out[4] = (n >> 8) & 0xFF;
    out[5] = n & 0xFF;
    uint16_t crc = modbus_crc16(out, 6);
    out[6] = crc & 0xFF;
    out[7] = (crc >> 8) & 0xFF;
    return 8;
}

// Build "Write Single Register" (FC 0x06) request:
//   [slave][0x06][hi(addr)][lo(addr)][hi(val)][lo(val)][lo(crc)][hi(crc)]
static size_t build_write_single(uint8_t *out, uint8_t slave, uint16_t addr, uint16_t val)
{
    out[0] = slave;
    out[1] = 0x06;
    out[2] = (addr >> 8) & 0xFF;
    out[3] = addr & 0xFF;
    out[4] = (val >> 8) & 0xFF;
    out[5] = val & 0xFF;
    uint16_t crc = modbus_crc16(out, 6);
    out[6] = crc & 0xFF;
    out[7] = (crc >> 8) & 0xFF;
    return 8;
}

// Verify the trailing 2-byte CRC of a frame of length `len`.
static bool verify_crc(const uint8_t *buf, size_t len)
{
    if (len < 4) return false;
    uint16_t want = modbus_crc16(buf, len - 2);
    uint16_t got  = (uint16_t)buf[len - 2] | ((uint16_t)buf[len - 1] << 8);
    return want == got;
}

esp_err_t psu_modbus_rtu_txn(const uint8_t *req, size_t req_len,
                             uint8_t *resp, size_t expect_len)
{
    SemaphoreHandle_t mtx = psu_driver_priv_get_uart_mutex();
    if (xSemaphoreTake(mtx, pdMS_TO_TICKS(PSU_TXN_TIMEOUT_MS + 50)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }

    esp_err_t result;
    uart_flush_input(PSU_UART_PORT);
    int written = uart_write_bytes(PSU_UART_PORT, (const char *)req, req_len);
    if (written != (int)req_len) { result = ESP_ERR_INVALID_STATE; goto out; }
    esp_err_t e = uart_wait_tx_done(PSU_UART_PORT, pdMS_TO_TICKS(50));
    if (e != ESP_OK) { result = e; goto out; }

    int got = uart_read_bytes(PSU_UART_PORT, resp, expect_len,
                              pdMS_TO_TICKS(PSU_TXN_TIMEOUT_MS));
    vTaskDelay(pdMS_TO_TICKS(PSU_INTERFRAME_MS));

    if (got <= 0) { result = ESP_ERR_TIMEOUT; goto out; }
    if ((size_t)got < expect_len) {
        if (got >= 5 && (resp[1] & 0x80)) {
            if (verify_crc(resp, 5)) {
                ESP_LOGW(TAG, "modbus exception: fc=0x%02X exc=0x%02X",
                         resp[1] & 0x7F, resp[2]);
                result = ESP_ERR_INVALID_RESPONSE;
                goto out;
            }
        }
        result = ESP_ERR_TIMEOUT;
        goto out;
    }
    if (!verify_crc(resp, expect_len))            { result = ESP_ERR_INVALID_CRC;      goto out; }
    if (resp[0] != req[0])                        { result = ESP_ERR_INVALID_RESPONSE; goto out; }
    if ((resp[1] & 0x7F) != (req[1] & 0x7F))      { result = ESP_ERR_INVALID_RESPONSE; goto out; }
    if (resp[1] & 0x80)                           { result = ESP_ERR_INVALID_RESPONSE; goto out; }
    result = ESP_OK;

out:
    xSemaphoreGive(mtx);
    return result;
}

esp_err_t psu_modbus_rtu_read_holding(uint8_t slave, uint16_t addr,
                                      uint16_t n, uint16_t *out_regs)
{
    uint8_t req[8];
    build_read_holding(req, slave, addr, n);

    // FC 0x03 response: [slave][0x03][bytecount][N×2 bytes][crc][crc]
    size_t expect = 5 + n * 2;
    uint8_t resp[64];
    if (expect > sizeof(resp)) return ESP_ERR_INVALID_SIZE;
    esp_err_t e = psu_modbus_rtu_txn(req, sizeof(req), resp, expect);
    if (e != ESP_OK) return e;
    if (resp[2] != n * 2) return ESP_ERR_INVALID_RESPONSE;
    for (uint16_t i = 0; i < n; i++) {
        out_regs[i] = ((uint16_t)resp[3 + i * 2] << 8) | resp[4 + i * 2];
    }
    return ESP_OK;
}

esp_err_t psu_modbus_rtu_write_single(uint8_t slave, uint16_t addr,
                                      uint16_t val)
{
    uint8_t req[8];
    build_write_single(req, slave, addr, val);

    // FC 0x06 echoes the request: 8 bytes total.
    uint8_t resp[8];
    return psu_modbus_rtu_txn(req, sizeof(req), resp, sizeof(resp));
}
