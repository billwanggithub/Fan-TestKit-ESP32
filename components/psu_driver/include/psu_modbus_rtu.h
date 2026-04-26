#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

// Wraps a single Modbus-RTU request/response transaction on UART1.
// Acquires the shared psu_driver UART mutex, flushes RX, writes req,
// reads up to expect_len bytes, verifies CRC.
//
// Returns:
//   ESP_OK                    : valid response, CRC ok
//   ESP_ERR_TIMEOUT           : no/short response
//   ESP_ERR_INVALID_CRC       : full-length response but CRC mismatch
//   ESP_ERR_INVALID_RESPONSE  : Modbus exception (fc | 0x80) or wrong slave/fc
esp_err_t psu_modbus_rtu_txn(const uint8_t *req, size_t req_len,
                             uint8_t *resp, size_t expect_len);

// FC 0x03 (read holding) — issues a transaction and copies n big-endian
// register words into out_regs.
esp_err_t psu_modbus_rtu_read_holding(uint8_t slave, uint16_t addr,
                                      uint16_t n, uint16_t *out_regs);

// FC 0x06 (write single) — issues a transaction and verifies the echo.
esp_err_t psu_modbus_rtu_write_single(uint8_t slave, uint16_t addr,
                                      uint16_t val);

#ifdef __cplusplus
}
#endif
