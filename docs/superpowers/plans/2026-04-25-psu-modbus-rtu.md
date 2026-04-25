# PSU Modbus-RTU Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add UART1-attached Riden RD60xx programmable DC supply control via a hand-rolled Modbus-RTU master, exposed through the existing CLI / WebSocket / HID / CDC frontends.

**Architecture:** New `psu_modbus` component owns UART1 + Modbus-RTU master + 5 Hz telemetry poll. `control_task` gains 4 new `ctrl_cmd_kind_t` values; frontends are extended in lock-step. Telemetry rides the existing 20 Hz WS status frame. Hand-rolled (no `esp-modbus` dependency) — only 5 registers and 2 function codes (0x03/0x06).

**Tech Stack:** ESP-IDF v6.0 (`esp_driver_uart`, `nvs_flash`, FreeRTOS), C99, Modbus-RTU @ 19200-8N1, cJSON for the WS frontend, TinyUSB HID/CDC.

**Spec:** `docs/superpowers/specs/2026-04-25-psu-modbus-rtu-design.md`

---

## File structure

| File | Status | Responsibility |
|------|--------|----------------|
| `components/psu_modbus/CMakeLists.txt` | NEW | Component manifest |
| `components/psu_modbus/include/psu_modbus.h` | NEW | Public API + telemetry struct |
| `components/psu_modbus/psu_modbus.c` | NEW | UART init, Modbus master, `psu_task`, NVS, atomic publish |
| `components/app_api/include/app_api.h` | EDIT | 4 new `ctrl_cmd_kind_t` values + union members |
| `main/Kconfig.projbuild` | EDIT | `APP_PSU_UART_TX_GPIO`, `_RX_GPIO`, `_BAUD`, `_SLAVE_DEFAULT` |
| `main/app_main.c` | EDIT | `psu_modbus_init/start`, 5 CLI commands, status line |
| `main/control_task.c` | EDIT | 4 new switch cases |
| `components/net_dashboard/ws_handler.c` | EDIT | 4 new WS msg types + `psu` block in status JSON |
| `components/net_dashboard/net_dashboard.c` | EDIT | `psu_*` fields in `device_info` JSON |
| `components/net_dashboard/CMakeLists.txt` | EDIT | `REQUIRES psu_modbus` |
| `components/net_dashboard/web/index.html` | EDIT | New collapsible Power Supply panel |
| `components/net_dashboard/web/app.css` | EDIT | Panel styling |
| `components/net_dashboard/web/app.js` | EDIT | PSU panel logic + i18n strings |
| `components/usb_composite/include/usb_protocol.h` | EDIT | HID 0x05 ops + CDC 0x40..0x44 + magic |
| `components/usb_composite/usb_descriptors.c` | EDIT | New TLC for 0x05 + assert size 83 |
| `components/usb_composite/usb_composite.c` | EDIT | `HID_REPORT_DESC_SIZE` macro update |
| `components/usb_composite/usb_hid_task.c` | EDIT | Parse 0x05 → post `ctrl_cmd_t` |
| `components/usb_composite/usb_cdc_task.c` | EDIT | Parse 0x40..0x43, push 0x44 telemetry @ 5 Hz |
| `components/usb_composite/CMakeLists.txt` | EDIT | `REQUIRES psu_modbus` |
| `CLAUDE.md` | EDIT | Document UART1 pin reservation + invariant note |

---

> **Project test note:** This codebase is firmware for an ESP32-S3. No host-side test harness exists (gpio_io and net_dashboard shipped without one). "Verification" steps are **build + manual hardware test** rather than unit tests. Each task ends with a build verification (`idf.py build`) and a commit; manual hardware verification of the full flow is reserved for the integration task at the end.
>
> Activate ESP-IDF v6.0 in your shell first — easiest route is the desktop shortcut **"ESP-IDF 6.0 PWM Project"** or the `esp6 pwm` PowerShell alias (defined in `D:\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`). All `idf.py` invocations in this plan assume that shell.

---

### Task 1: Add Kconfig entries for PSU UART pins, baud, and default slave address

**Files:**
- Modify: `main/Kconfig.projbuild` (append before `endmenu`)

- [ ] **Step 1: Append the PSU section to the existing app menu**

Open `main/Kconfig.projbuild`. Find the line `endmenu` at the end. Insert these lines **above** that final `endmenu`:

```kconfig
    config APP_PSU_UART_TX_GPIO
        int "PSU UART1 TX GPIO"
        default 38

    config APP_PSU_UART_RX_GPIO
        int "PSU UART1 RX GPIO"
        default 39

    config APP_PSU_UART_BAUD
        int "PSU UART1 baud rate"
        default 19200

    config APP_PSU_SLAVE_DEFAULT
        int "PSU Modbus slave address default (used on first boot before NVS)"
        default 1
        range 1 247
```

- [ ] **Step 2: Force a sdkconfig rebuild so the new symbols are picked up**

`sdkconfig.defaults` does not currently mention these symbols, so the existing `sdkconfig` lacks them. The Kconfig defaults will be picked up by the next configure step. Run from the project root:

```bash
idf.py reconfigure
```

Expected: `-- Configuring done` and a refreshed `sdkconfig` containing `CONFIG_APP_PSU_UART_TX_GPIO=38`. Verify:

```bash
grep -E "CONFIG_APP_PSU_(UART|SLAVE)" sdkconfig
```

Expected output: 4 lines, one per new symbol, with the defaults above.

- [ ] **Step 3: Build to confirm Kconfig changes don't break the existing build**

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 4: Commit**

```bash
git add main/Kconfig.projbuild sdkconfig
git commit -m "feat(psu): add Kconfig entries for UART pins, baud, and default slave addr"
```

---

### Task 2: Add new ctrl_cmd kinds to app_api.h

**Files:**
- Modify: `components/app_api/include/app_api.h`

- [ ] **Step 1: Extend the enum**

Open `components/app_api/include/app_api.h`. Replace the existing enum block:

```c
typedef enum {
    CTRL_CMD_SET_PWM,
    CTRL_CMD_SET_RPM_PARAMS,
    CTRL_CMD_SET_RPM_TIMEOUT,
    CTRL_CMD_OTA_BEGIN,
    CTRL_CMD_OTA_CHUNK,
    CTRL_CMD_OTA_END,
    CTRL_CMD_GPIO_SET_MODE,
    CTRL_CMD_GPIO_SET_LEVEL,
    CTRL_CMD_GPIO_PULSE,
    CTRL_CMD_POWER_SET,
    CTRL_CMD_PULSE_WIDTH_SET,
} ctrl_cmd_kind_t;
```

with:

```c
typedef enum {
    CTRL_CMD_SET_PWM,
    CTRL_CMD_SET_RPM_PARAMS,
    CTRL_CMD_SET_RPM_TIMEOUT,
    CTRL_CMD_OTA_BEGIN,
    CTRL_CMD_OTA_CHUNK,
    CTRL_CMD_OTA_END,
    CTRL_CMD_GPIO_SET_MODE,
    CTRL_CMD_GPIO_SET_LEVEL,
    CTRL_CMD_GPIO_PULSE,
    CTRL_CMD_POWER_SET,
    CTRL_CMD_PULSE_WIDTH_SET,
    CTRL_CMD_PSU_SET_VOLTAGE,
    CTRL_CMD_PSU_SET_CURRENT,
    CTRL_CMD_PSU_SET_OUTPUT,
    CTRL_CMD_PSU_SET_SLAVE,
} ctrl_cmd_kind_t;
```

- [ ] **Step 2: Extend the union**

In the same header, find the `ctrl_cmd_t` struct's union and add 4 new members at the end (just before the closing `};` of the union):

```c
        struct { float    v;     }                     psu_set_voltage;
        struct { float    i;     }                     psu_set_current;
        struct { uint8_t  on;    }                     psu_set_output;
        struct { uint8_t  addr;  }                     psu_set_slave;
```

The full union now reads:

```c
    union {
        struct { uint32_t freq_hz; float duty_pct; }   set_pwm;
        struct { uint8_t pole; uint16_t mavg; }        set_rpm_params;
        struct { uint32_t timeout_us; }                set_rpm_timeout;
        struct { uint8_t  idx; uint8_t  mode; }        gpio_set_mode;
        struct { uint8_t  idx; uint8_t  level; }       gpio_set_level;
        struct { uint8_t  idx; uint32_t width_ms; }    gpio_pulse;
        struct { uint8_t  on; }                        power_set;
        struct { uint32_t width_ms; }                  pulse_width_set;
        struct { float    v;     }                     psu_set_voltage;
        struct { float    i;     }                     psu_set_current;
        struct { uint8_t  on;    }                     psu_set_output;
        struct { uint8_t  addr;  }                     psu_set_slave;
    };
```

- [ ] **Step 3: Build to confirm header still compiles cleanly**

`control_task.c` does not yet handle the new kinds, so the switch will fall through to the default — harmless for now; the compiler will not warn (the enum has no `default:` clause and no `-Wswitch-enum`).

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 4: Commit**

```bash
git add components/app_api/include/app_api.h
git commit -m "feat(app_api): add CTRL_CMD_PSU_* kinds for power-supply control"
```

---

### Task 3: Skeleton psu_modbus component (header + empty .c + CMakeLists)

**Files:**
- Create: `components/psu_modbus/CMakeLists.txt`
- Create: `components/psu_modbus/include/psu_modbus.h`
- Create: `components/psu_modbus/psu_modbus.c`

- [ ] **Step 1: Create CMakeLists.txt**

```cmake
idf_component_register(
    SRCS        "psu_modbus.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "."
    REQUIRES    app_api
                esp_driver_uart
                nvs_flash
                log
)
```

- [ ] **Step 2: Create the public header**

`components/psu_modbus/include/psu_modbus.h`:

```c
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float    v_set;
    float    i_set;
    float    v_out;
    float    i_out;
    bool     output_on;
    bool     link_ok;
    uint16_t model_id;       // raw register 0x00; 0 if not yet detected
    float    i_scale_div;    // 100.0 or 1000.0; valid only when model_id != 0
} psu_modbus_telemetry_t;

esp_err_t psu_modbus_init(void);    // brings up UART, loads slave addr from NVS
esp_err_t psu_modbus_start(void);   // creates psu_task, fires model-detect read

esp_err_t psu_modbus_set_voltage(float v);
esp_err_t psu_modbus_set_current(float i);
esp_err_t psu_modbus_set_output(bool on);

uint8_t   psu_modbus_get_slave_addr(void);
esp_err_t psu_modbus_set_slave_addr(uint8_t addr);   // 1..247

void psu_modbus_get_telemetry(psu_modbus_telemetry_t *out);

// Convenience for device_info JSON.
const char *psu_modbus_get_model_name(void);   // "RD6006" | "RD6012" | "RD6018" | "unknown"

#ifdef __cplusplus
}
#endif
```

- [ ] **Step 3: Create a stub .c that compiles but does nothing**

`components/psu_modbus/psu_modbus.c`:

```c
#include "psu_modbus.h"

#include <stdatomic.h>
#include <string.h>

#include "esp_log.h"

static const char *TAG = "psu_modbus";

esp_err_t psu_modbus_init(void)            { ESP_LOGI(TAG, "init (stub)");  return ESP_OK; }
esp_err_t psu_modbus_start(void)           { ESP_LOGI(TAG, "start (stub)"); return ESP_OK; }
esp_err_t psu_modbus_set_voltage(float v)  { (void)v; return ESP_OK; }
esp_err_t psu_modbus_set_current(float i)  { (void)i; return ESP_OK; }
esp_err_t psu_modbus_set_output(bool on)   { (void)on; return ESP_OK; }
uint8_t   psu_modbus_get_slave_addr(void)  { return 1; }
esp_err_t psu_modbus_set_slave_addr(uint8_t a) { (void)a; return ESP_OK; }

void psu_modbus_get_telemetry(psu_modbus_telemetry_t *out)
{
    if (!out) return;
    memset(out, 0, sizeof(*out));
}

const char *psu_modbus_get_model_name(void) { return "unknown"; }
```

- [ ] **Step 4: Build to confirm the new component is picked up**

```bash
idf.py build
```

Expected: `Project build complete.` Verify the component was discovered:

```bash
grep "psu_modbus" build/project_description.json | head -5
```

Expected: at least one match referencing `components/psu_modbus`.

- [ ] **Step 5: Commit**

```bash
git add components/psu_modbus/
git commit -m "feat(psu_modbus): stub component skeleton (header + no-op impl)"
```

---

### Task 4: Implement Modbus-RTU CRC-16 and frame helpers (still inside psu_modbus.c)

**Files:**
- Modify: `components/psu_modbus/psu_modbus.c`

- [ ] **Step 1: Replace the stub file with the framing primitives**

Open `components/psu_modbus/psu_modbus.c` and replace its contents with:

```c
#include "psu_modbus.h"

#include <stdatomic.h>
#include <string.h>

#include "esp_log.h"

static const char *TAG = "psu_modbus";

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
    return crc;   // already in low-byte-first wire order when written as LE
}

// Build "Read Holding Registers" (FC 0x03) request:
//   [slave][0x03][hi(addr)][lo(addr)][hi(n)][lo(n)][lo(crc)][hi(crc)]
// Returns total frame length (always 8).
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

// ---- Public API stubs (filled in next tasks) -------------------------------

esp_err_t psu_modbus_init(void)            { ESP_LOGI(TAG, "init (stub)");  return ESP_OK; }
esp_err_t psu_modbus_start(void)           { ESP_LOGI(TAG, "start (stub)"); return ESP_OK; }
esp_err_t psu_modbus_set_voltage(float v)  { (void)v; return ESP_OK; }
esp_err_t psu_modbus_set_current(float i)  { (void)i; return ESP_OK; }
esp_err_t psu_modbus_set_output(bool on)   { (void)on; return ESP_OK; }
uint8_t   psu_modbus_get_slave_addr(void)  { return 1; }
esp_err_t psu_modbus_set_slave_addr(uint8_t a) { (void)a; return ESP_OK; }

void psu_modbus_get_telemetry(psu_modbus_telemetry_t *out)
{
    if (!out) return;
    memset(out, 0, sizeof(*out));
}

const char *psu_modbus_get_model_name(void) { return "unknown"; }
```

- [ ] **Step 2: ~~CRC-16 sanity check~~ — SKIPPED (see post-mortem)**

> **History:** the original plan added a `__attribute__((constructor))`
> self-check that compared `modbus_crc16({01 03 00 08 00 05})` against
> `0x0944` and called `__builtin_trap()` on mismatch. The compared-against
> constant turned out to be wrong (taken from a stray spec note rather
> than actually computed), so on real hardware the trap fired every cold
> boot and the chip never reached `app_main`. The check was reverted in
> commit `32e3706`. **Do not add it back** unless you have:
>
> 1. A canonical CRC vector verified against either an authoritative
>    reference implementation or live RD60xx wire traffic.
> 2. Some way to surface the failure other than a silent trap —
>    constructors run before `ESP_LOG` is up, so a debug-hostile silent
>    halt is the only signal you'll get.
>
> CRC correctness is verified end-to-end at runtime instead: a bad
> implementation makes every transaction time out, `link_ok` flips to
> false within ~1 s, the dashboard shows "PSU offline". Skip this step
> entirely.

- [ ] **Step 3: Build to verify the helpers compile (no trap to run yet)**

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 4: Commit**

```bash
git add components/psu_modbus/psu_modbus.c
git commit -m "feat(psu_modbus): Modbus-RTU CRC-16 + FC 0x03/0x06 frame helpers"
```

---

### Task 5: UART1 init + NVS-backed slave-address load/save

**Files:**
- Modify: `components/psu_modbus/psu_modbus.c`

- [ ] **Step 1: Add UART driver, NVS includes, and shared module state**

Insert near the top of `psu_modbus.c` (below the existing `#include "esp_log.h"`):

```c
#include "driver/uart.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#define PSU_UART_PORT     UART_NUM_1
#define PSU_RX_BUF_SIZE   256
#define PSU_TX_BUF_SIZE   256

#define NVS_NAMESPACE     "psu_modbus"
#define NVS_KEY_SLAVE     "slave_addr"

static _Atomic uint8_t s_slave_addr;
```

- [ ] **Step 2: Implement NVS load/save helpers**

Insert above the existing `psu_modbus_init` stub:

```c
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
```

- [ ] **Step 3: Replace the `psu_modbus_init` stub with real UART init**

Replace the existing one-line `psu_modbus_init` with:

```c
esp_err_t psu_modbus_init(void)
{
    load_slave_addr_from_nvs();

    const uart_config_t cfg = {
        .baud_rate = CONFIG_APP_PSU_UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
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
```

- [ ] **Step 4: Replace the `psu_modbus_get_slave_addr` and `_set_slave_addr` stubs**

```c
uint8_t psu_modbus_get_slave_addr(void)
{
    return atomic_load_explicit(&s_slave_addr, memory_order_relaxed);
}

esp_err_t psu_modbus_set_slave_addr(uint8_t addr)
{
    if (addr < 1 || addr > 247) return ESP_ERR_INVALID_ARG;
    atomic_store_explicit(&s_slave_addr, addr, memory_order_relaxed);
    save_slave_addr_to_nvs(addr);
    ESP_LOGI(TAG, "slave addr set to %u (NVS)", addr);
    return ESP_OK;
}
```

- [ ] **Step 5: Build**

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 6: Commit**

```bash
git add components/psu_modbus/psu_modbus.c
git commit -m "feat(psu_modbus): UART1 init + NVS-backed slave address"
```

---

### Task 6: Modbus transaction primitive (TX + RX with timeout + CRC verify)

**Files:**
- Modify: `components/psu_modbus/psu_modbus.c`

- [ ] **Step 1: Add the transaction primitive above `psu_modbus_init`**

```c
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define PSU_TXN_TIMEOUT_MS   100
#define PSU_INTERFRAME_MS    2     // 3.5-char gap @ 19200 ≈ 1.8 ms

// Result codes folded into esp_err_t:
//   ESP_OK            : valid response, CRC ok
//   ESP_ERR_TIMEOUT   : no/short response within timeout
//   ESP_ERR_INVALID_CRC : full-length response but CRC mismatch
//   ESP_ERR_INVALID_RESPONSE : Modbus exception (fc | 0x80) or wrong slave/fc
//
// `expect_len` is the total expected response length (header + data + CRC).
// Caller is responsible for sizing `resp` >= `expect_len`.
static esp_err_t psu_txn(const uint8_t *req, size_t req_len,
                         uint8_t *resp, size_t expect_len)
{
    uart_flush_input(PSU_UART_PORT);

    int written = uart_write_bytes(PSU_UART_PORT, (const char *)req, req_len);
    if (written != (int)req_len) return ESP_ERR_INVALID_STATE;
    esp_err_t e = uart_wait_tx_done(PSU_UART_PORT, pdMS_TO_TICKS(50));
    if (e != ESP_OK) return e;

    int got = uart_read_bytes(PSU_UART_PORT, resp, expect_len,
                              pdMS_TO_TICKS(PSU_TXN_TIMEOUT_MS));
    // Inter-frame gap before the next transaction.
    vTaskDelay(pdMS_TO_TICKS(PSU_INTERFRAME_MS));

    if (got <= 0)               return ESP_ERR_TIMEOUT;
    if ((size_t)got < expect_len) {
        // Could be exception response: 5 bytes [slave][fc|0x80][exc][crc][crc]
        if (got >= 5 && (resp[1] & 0x80)) {
            if (verify_crc(resp, 5)) {
                ESP_LOGW(TAG, "modbus exception: fc=0x%02X exc=0x%02X",
                         resp[1] & 0x7F, resp[2]);
                return ESP_ERR_INVALID_RESPONSE;
            }
        }
        return ESP_ERR_TIMEOUT;
    }
    if (!verify_crc(resp, expect_len)) return ESP_ERR_INVALID_CRC;
    if (resp[0] != req[0])             return ESP_ERR_INVALID_RESPONSE;   // wrong slave echo
    if ((resp[1] & 0x7F) != (req[1] & 0x7F)) return ESP_ERR_INVALID_RESPONSE;
    if (resp[1] & 0x80)                return ESP_ERR_INVALID_RESPONSE;   // exception
    return ESP_OK;
}

static esp_err_t psu_read_holding(uint16_t addr, uint16_t n, uint16_t *out_regs)
{
    uint8_t slave = atomic_load_explicit(&s_slave_addr, memory_order_relaxed);
    uint8_t req[8];
    build_read_holding(req, slave, addr, n);

    // FC 0x03 response: [slave][0x03][bytecount][N×2 bytes][crc][crc]
    size_t expect = 5 + n * 2;
    uint8_t resp[64];
    if (expect > sizeof(resp)) return ESP_ERR_INVALID_SIZE;
    esp_err_t e = psu_txn(req, sizeof(req), resp, expect);
    if (e != ESP_OK) return e;
    if (resp[2] != n * 2) return ESP_ERR_INVALID_RESPONSE;
    for (uint16_t i = 0; i < n; i++) {
        out_regs[i] = ((uint16_t)resp[3 + i * 2] << 8) | resp[4 + i * 2];
    }
    return ESP_OK;
}

static esp_err_t psu_write_single(uint16_t addr, uint16_t val)
{
    uint8_t slave = atomic_load_explicit(&s_slave_addr, memory_order_relaxed);
    uint8_t req[8];
    build_write_single(req, slave, addr, val);

    // FC 0x06 echoes the request: 8 bytes total.
    uint8_t resp[8];
    return psu_txn(req, sizeof(req), resp, sizeof(resp));
}
```

- [ ] **Step 2: Build to confirm the new code compiles**

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 3: Commit**

```bash
git add components/psu_modbus/psu_modbus.c
git commit -m "feat(psu_modbus): RTU transaction primitive + read_holding / write_single"
```

---

### Task 7: psu_task with poll loop, atomic publish, link-health

**Files:**
- Modify: `components/psu_modbus/psu_modbus.c`

- [ ] **Step 1: Add register addresses, model table, and module state**

Insert below the `#define NVS_KEY_SLAVE` line:

```c
// ---- Riden RD60xx register map -------------------------------------------
#define REG_MODEL    0x0000
#define REG_V_SET    0x0008
#define REG_I_SET    0x0009
#define REG_V_OUT    0x000A
#define REG_I_OUT    0x000B
#define REG_OUTPUT   0x0012

#define POLL_PERIOD_MS       200    // 5 Hz
#define LINK_FAIL_THRESHOLD  5

// Atomic publish — bit-punned floats and bools.
static _Atomic uint32_t s_v_set_bits, s_i_set_bits, s_v_out_bits, s_i_out_bits;
static _Atomic uint8_t  s_output_on;
static _Atomic uint8_t  s_link_ok;
static _Atomic uint16_t s_model_id;
static _Atomic uint32_t s_i_scale_bits;   // float bit-punned, 100.0 or 1000.0

static const struct { uint16_t id; const char *name; float i_scale; } RD_MODELS[] = {
    { 60062, "RD6006",  1000.0f },
    { 60065, "RD6006P", 1000.0f },
    { 60121, "RD6012",   100.0f },
    { 60125, "RD6012P",  100.0f },
    { 60181, "RD6018",   100.0f },
    { 60241, "RD6024",   100.0f },
};
#define RD_MODELS_N (sizeof(RD_MODELS) / sizeof(RD_MODELS[0]))

static TaskHandle_t s_psu_task;

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
```

- [ ] **Step 2: Add model-detection routine and link-health helper**

```c
static void detect_model(void)
{
    uint16_t model = 0;
    if (psu_read_holding(REG_MODEL, 1, &model) != ESP_OK) {
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

static void note_txn_result(esp_err_t e)
{
    static int fails = 0;
    if (e == ESP_OK) {
        if (fails >= LINK_FAIL_THRESHOLD) {
            ESP_LOGI(TAG, "link recovered");
        }
        fails = 0;
        atomic_store_explicit(&s_link_ok, 1, memory_order_relaxed);
    } else {
        if (fails < LINK_FAIL_THRESHOLD) fails++;
        if (fails == LINK_FAIL_THRESHOLD) {
            ESP_LOGW(TAG, "link lost: %s", esp_err_to_name(e));
            atomic_store_explicit(&s_link_ok, 0, memory_order_relaxed);
        }
    }
}
```

- [ ] **Step 3: Add the polling task**

```c
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

        // Read [V_SET, I_SET, V_OUT, I_OUT] in one transaction (4 contiguous regs).
        uint16_t r[4] = {0};
        esp_err_t e = psu_read_holding(REG_V_SET, 4, r);
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
        e = psu_read_holding(REG_OUTPUT, 1, &o);
        note_txn_result(e);
        if (e == ESP_OK) {
            atomic_store_explicit(&s_output_on, o ? 1 : 0, memory_order_relaxed);
        }

        vTaskDelayUntil(&last, period);
    }
}
```

- [ ] **Step 4: Wire `psu_modbus_start`**

Replace the existing `psu_modbus_start` stub with:

```c
esp_err_t psu_modbus_start(void)
{
    if (s_psu_task) return ESP_ERR_INVALID_STATE;
    BaseType_t ok = xTaskCreate(psu_task_fn, "psu_modbus", 4096, NULL, 4, &s_psu_task);
    return ok == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
```

- [ ] **Step 5: Wire `psu_modbus_get_telemetry` and `psu_modbus_get_model_name`**

Replace those two stubs with:

```c
void psu_modbus_get_telemetry(psu_modbus_telemetry_t *out)
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

const char *psu_modbus_get_model_name(void)
{
    uint16_t id = atomic_load_explicit(&s_model_id, memory_order_relaxed);
    for (size_t i = 0; i < RD_MODELS_N; i++) {
        if (RD_MODELS[i].id == id) return RD_MODELS[i].name;
    }
    return "unknown";
}
```

- [ ] **Step 6: Build**

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 7: Commit**

```bash
git add components/psu_modbus/psu_modbus.c
git commit -m "feat(psu_modbus): polling task with model detection + link-health tracking"
```

---

### Task 8: Setpoint write functions (V / I / Output)

**Files:**
- Modify: `components/psu_modbus/psu_modbus.c`

- [ ] **Step 1: Replace the three setpoint stubs**

Replace `psu_modbus_set_voltage`, `_set_current`, `_set_output` with:

```c
esp_err_t psu_modbus_set_voltage(float v)
{
    if (v < 0.0f)  v = 0.0f;
    if (v > 60.0f) v = 60.0f;
    uint16_t raw = (uint16_t)(v * 100.0f + 0.5f);
    esp_err_t e = psu_write_single(REG_V_SET, raw);
    note_txn_result(e);
    if (e == ESP_OK) {
        store_f(&s_v_set_bits, raw / 100.0f);
    } else {
        ESP_LOGW(TAG, "set_voltage(%.2f V) failed: %s", (double)v, esp_err_to_name(e));
    }
    return e;
}

esp_err_t psu_modbus_set_current(float i)
{
    if (i < 0.0f) i = 0.0f;
    float i_div = load_f(&s_i_scale_bits);
    if (i_div < 1.0f) i_div = 1000.0f;   // before model detect
    float i_max = (i_div >= 999.0f) ? 6.0f : 24.0f;   // RD6006: 6 A; RD6012/18/24: ≤24 A
    if (i > i_max) i = i_max;
    uint16_t raw = (uint16_t)(i * i_div + 0.5f);
    esp_err_t e = psu_write_single(REG_I_SET, raw);
    note_txn_result(e);
    if (e == ESP_OK) {
        store_f(&s_i_set_bits, raw / i_div);
    } else {
        ESP_LOGW(TAG, "set_current(%.3f A) failed: %s", (double)i, esp_err_to_name(e));
    }
    return e;
}

esp_err_t psu_modbus_set_output(bool on)
{
    esp_err_t e = psu_write_single(REG_OUTPUT, on ? 1 : 0);
    note_txn_result(e);
    if (e == ESP_OK) {
        atomic_store_explicit(&s_output_on, on ? 1 : 0, memory_order_relaxed);
    } else {
        ESP_LOGW(TAG, "set_output(%d) failed: %s", on ? 1 : 0, esp_err_to_name(e));
    }
    return e;
}
```

> **Concurrency note:** Setpoint writes are called from `control_task` (priority 6). Polling reads happen on `psu_task` (priority 4). Both share UART1. Modbus is half-duplex and our `psu_txn` uses `uart_flush_input` + `uart_write_bytes` + a synchronous `uart_read_bytes` — concurrent calls would interleave bytes on the wire. To prevent that, add a mutex.
>
> **Spec deviation (intentional):** Spec §4.7 describes a transaction queue with same-kind setpoint coalescing. The simpler implementation here calls `psu_write_single` directly under the UART mutex. At 19200 baud one round trip is ~30 ms; the dashboard's slider commit rate is ≤5/s, so the wire never saturates and coalescing is unnecessary. If a future frontend ever spams setpoints faster than the wire, revisit this and add a queue. Documented here so the next reader knows the deviation is deliberate, not a bug.

- [ ] **Step 2: Add the UART mutex**

Near the top of the file, next to the other module state:

```c
#include "freertos/semphr.h"

static SemaphoreHandle_t s_uart_mutex;
```

In `psu_modbus_init`, before returning `ESP_OK`, create the mutex:

```c
    s_uart_mutex = xSemaphoreCreateMutex();
    if (!s_uart_mutex) return ESP_ERR_NO_MEM;
```

Wrap the body of `psu_txn` in mutex-take/give:

```c
static esp_err_t psu_txn(const uint8_t *req, size_t req_len,
                         uint8_t *resp, size_t expect_len)
{
    if (xSemaphoreTake(s_uart_mutex, pdMS_TO_TICKS(PSU_TXN_TIMEOUT_MS + 50)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }

    uart_flush_input(PSU_UART_PORT);
    int written = uart_write_bytes(PSU_UART_PORT, (const char *)req, req_len);
    esp_err_t result;
    if (written != (int)req_len) {
        result = ESP_ERR_INVALID_STATE;
        goto out;
    }
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
    xSemaphoreGive(s_uart_mutex);
    return result;
}
```

- [ ] **Step 3: Build**

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 4: Commit**

```bash
git add components/psu_modbus/psu_modbus.c
git commit -m "feat(psu_modbus): setpoint writes (V/I/output) + UART mutex"
```

---

### Task 9: Wire psu_modbus init/start into app_main + control_task switch cases

**Files:**
- Modify: `main/app_main.c`
- Modify: `main/control_task.c`

- [ ] **Step 1: Add include and init/start calls in `app_main.c`**

In `main/app_main.c`, near the other component includes, add:

```c
#include "psu_modbus.h"
```

In `app_main()`, add the init call **after** `gpio_io_init()` and before `ota_core_init()`:

```c
    ESP_ERROR_CHECK(psu_modbus_init());
```

Add the start call **after** `control_task_start()` and **before** the boot PWM setpoint block:

```c
    ESP_ERROR_CHECK(psu_modbus_start());
```

- [ ] **Step 2: Add the 4 switch cases in `control_task.c`**

In `main/control_task.c`, add `#include "psu_modbus.h"` next to the other component includes (`gpio_io.h`, `pwm_gen.h`, `rpm_cap.h`).

In the switch in `control_task()`, add four new cases right before the `CTRL_CMD_OTA_BEGIN` group:

```c
        case CTRL_CMD_PSU_SET_VOLTAGE: {
            esp_err_t e = psu_modbus_set_voltage(cmd.psu_set_voltage.v);
            if (e != ESP_OK) {
                ESP_LOGW(TAG, "psu_set_voltage(%.2f) failed: %s",
                         (double)cmd.psu_set_voltage.v, esp_err_to_name(e));
            }
        } break;
        case CTRL_CMD_PSU_SET_CURRENT: {
            esp_err_t e = psu_modbus_set_current(cmd.psu_set_current.i);
            if (e != ESP_OK) {
                ESP_LOGW(TAG, "psu_set_current(%.3f) failed: %s",
                         (double)cmd.psu_set_current.i, esp_err_to_name(e));
            }
        } break;
        case CTRL_CMD_PSU_SET_OUTPUT: {
            esp_err_t e = psu_modbus_set_output(cmd.psu_set_output.on != 0);
            if (e != ESP_OK) {
                ESP_LOGW(TAG, "psu_set_output(%u) failed: %s",
                         cmd.psu_set_output.on, esp_err_to_name(e));
            }
        } break;
        case CTRL_CMD_PSU_SET_SLAVE: {
            esp_err_t e = psu_modbus_set_slave_addr(cmd.psu_set_slave.addr);
            if (e != ESP_OK) {
                ESP_LOGW(TAG, "psu_set_slave(%u) failed: %s",
                         cmd.psu_set_slave.addr, esp_err_to_name(e));
            }
        } break;
```

- [ ] **Step 3: Update `main/CMakeLists.txt`** so `main` finds the `psu_modbus` headers

Open `main/CMakeLists.txt` and add `psu_modbus` to the `REQUIRES` list. (The other peer components — `gpio_io`, `pwm_gen`, `rpm_cap` — are already there; mirror that exactly.)

- [ ] **Step 4: Build**

```bash
idf.py build
```

Expected: `Project build complete.` Build will fail with a "no such header `psu_modbus.h`" if the REQUIRES update was missed — fix and rebuild.

- [ ] **Step 5: Commit**

```bash
git add main/app_main.c main/control_task.c main/CMakeLists.txt
git commit -m "feat(psu): wire psu_modbus into app_main + control_task"
```

---

### Task 10: Add CLI commands (psu_v / psu_i / psu_out / psu_slave / psu_status) + status line

**Files:**
- Modify: `main/app_main.c`

- [ ] **Step 1: Add CLI argtables and handlers**

In `main/app_main.c`, after the existing `cmd_power` handler, add:

```c
// ---- CLI: psu_v <volts> ----------------------------------------------------
static struct { struct arg_dbl *v; struct arg_end *end; } s_psu_v_args;
static int cmd_psu_v(int argc, char **argv)
{
    int n = arg_parse(argc, argv, (void **)&s_psu_v_args);
    if (n != 0) { arg_print_errors(stderr, s_psu_v_args.end, argv[0]); return 1; }
    ctrl_cmd_t c = {
        .kind = CTRL_CMD_PSU_SET_VOLTAGE,
        .psu_set_voltage = { .v = (float)s_psu_v_args.v->dval[0] },
    };
    return control_task_post(&c, pdMS_TO_TICKS(100)) == ESP_OK ? 0 : 1;
}

// ---- CLI: psu_i <amps> -----------------------------------------------------
static struct { struct arg_dbl *i; struct arg_end *end; } s_psu_i_args;
static int cmd_psu_i(int argc, char **argv)
{
    int n = arg_parse(argc, argv, (void **)&s_psu_i_args);
    if (n != 0) { arg_print_errors(stderr, s_psu_i_args.end, argv[0]); return 1; }
    ctrl_cmd_t c = {
        .kind = CTRL_CMD_PSU_SET_CURRENT,
        .psu_set_current = { .i = (float)s_psu_i_args.i->dval[0] },
    };
    return control_task_post(&c, pdMS_TO_TICKS(100)) == ESP_OK ? 0 : 1;
}

// ---- CLI: psu_out <0|1> ----------------------------------------------------
static struct { struct arg_int *on; struct arg_end *end; } s_psu_out_args;
static int cmd_psu_out(int argc, char **argv)
{
    int n = arg_parse(argc, argv, (void **)&s_psu_out_args);
    if (n != 0) { arg_print_errors(stderr, s_psu_out_args.end, argv[0]); return 1; }
    ctrl_cmd_t c = {
        .kind = CTRL_CMD_PSU_SET_OUTPUT,
        .psu_set_output = { .on = (uint8_t)(s_psu_out_args.on->ival[0] ? 1 : 0) },
    };
    return control_task_post(&c, pdMS_TO_TICKS(100)) == ESP_OK ? 0 : 1;
}

// ---- CLI: psu_slave <addr> -------------------------------------------------
static struct { struct arg_int *addr; struct arg_end *end; } s_psu_slave_args;
static int cmd_psu_slave(int argc, char **argv)
{
    int n = arg_parse(argc, argv, (void **)&s_psu_slave_args);
    if (n != 0) { arg_print_errors(stderr, s_psu_slave_args.end, argv[0]); return 1; }
    int v = s_psu_slave_args.addr->ival[0];
    if (v < 1 || v > 247) { printf("addr must be 1..247\n"); return 1; }
    ctrl_cmd_t c = {
        .kind = CTRL_CMD_PSU_SET_SLAVE,
        .psu_set_slave = { .addr = (uint8_t)v },
    };
    return control_task_post(&c, pdMS_TO_TICKS(100)) == ESP_OK ? 0 : 1;
}

// ---- CLI: psu_status -------------------------------------------------------
static int cmd_psu_status(int argc, char **argv)
{
    (void)argc; (void)argv;
    psu_modbus_telemetry_t t;
    psu_modbus_get_telemetry(&t);
    printf("psu  %s  %s  v_set=%.2f V  i_set=%.3f A  v_out=%.2f V  i_out=%.3f A  output=%s  slave=%u\n",
           psu_modbus_get_model_name(),
           t.link_ok ? "link=up" : "link=down",
           (double)t.v_set, (double)t.i_set,
           (double)t.v_out, (double)t.i_out,
           t.output_on ? "ON" : "OFF",
           psu_modbus_get_slave_addr());
    return 0;
}
```

Add `#include "psu_modbus.h"` near the other component includes if it isn't already there.

- [ ] **Step 2: Register the commands in `register_commands()`**

After the existing `pw_cmd` registration block:

```c
    s_psu_v_args.v   = arg_dbl1(NULL, NULL, "<volts>", "voltage in volts (0..60)");
    s_psu_v_args.end = arg_end(1);
    const esp_console_cmd_t psu_v_cmd = { .command = "psu_v", .help = "set PSU output voltage",
        .hint = NULL, .func = cmd_psu_v, .argtable = &s_psu_v_args };
    ESP_ERROR_CHECK(esp_console_cmd_register(&psu_v_cmd));

    s_psu_i_args.i   = arg_dbl1(NULL, NULL, "<amps>", "current limit in amps");
    s_psu_i_args.end = arg_end(1);
    const esp_console_cmd_t psu_i_cmd = { .command = "psu_i", .help = "set PSU current limit",
        .hint = NULL, .func = cmd_psu_i, .argtable = &s_psu_i_args };
    ESP_ERROR_CHECK(esp_console_cmd_register(&psu_i_cmd));

    s_psu_out_args.on  = arg_int1(NULL, NULL, "<on>", "1 = ON, 0 = OFF");
    s_psu_out_args.end = arg_end(1);
    const esp_console_cmd_t psu_out_cmd = { .command = "psu_out", .help = "PSU output enable",
        .hint = NULL, .func = cmd_psu_out, .argtable = &s_psu_out_args };
    ESP_ERROR_CHECK(esp_console_cmd_register(&psu_out_cmd));

    s_psu_slave_args.addr = arg_int1(NULL, NULL, "<addr>", "Modbus slave address 1..247");
    s_psu_slave_args.end  = arg_end(1);
    const esp_console_cmd_t psu_slave_cmd = { .command = "psu_slave", .help = "set Modbus slave addr (NVS)",
        .hint = NULL, .func = cmd_psu_slave, .argtable = &s_psu_slave_args };
    ESP_ERROR_CHECK(esp_console_cmd_register(&psu_slave_cmd));

    const esp_console_cmd_t psu_status_cmd = { .command = "psu_status",
        .help = "print PSU snapshot (v_set/i_set/v_out/i_out/link/model)",
        .hint = NULL, .func = cmd_psu_status };
    ESP_ERROR_CHECK(esp_console_cmd_register(&psu_status_cmd));
```

- [ ] **Step 3: Append a one-line PSU summary to the existing `cmd_status`**

In `cmd_status` (which already prints PWM, RPM, power, gpio), add **before the final `return 0;`**:

```c
    psu_modbus_telemetry_t pt;
    psu_modbus_get_telemetry(&pt);
    printf("psu  %s  %s  v=%.2f/%.2f V  i=%.3f/%.3f A  out=%s\n",
           psu_modbus_get_model_name(),
           pt.link_ok ? "up" : "down",
           (double)pt.v_set, (double)pt.v_out,
           (double)pt.i_set, (double)pt.i_out,
           pt.output_on ? "ON" : "OFF");
```

- [ ] **Step 4: Build**

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 5: Commit**

```bash
git add main/app_main.c
git commit -m "feat(cli): add psu_v/psu_i/psu_out/psu_slave/psu_status commands"
```

---

### Task 11: WebSocket frontend — accept set_psu_*, push psu block in status JSON

**Files:**
- Modify: `components/net_dashboard/ws_handler.c`
- Modify: `components/net_dashboard/CMakeLists.txt`

- [ ] **Step 1: Add `psu_modbus` to net_dashboard REQUIRES**

In `components/net_dashboard/CMakeLists.txt`, add `psu_modbus` to the `REQUIRES` list (anywhere; mirror `gpio_io` placement).

- [ ] **Step 2: Add include and four new `else if` branches in `handle_json`**

In `components/net_dashboard/ws_handler.c`, near the other includes, add:

```c
#include "psu_modbus.h"
```

In `handle_json`, after the existing `else if` chain (just before its closing `}`), add:

```c
    } else if (strcmp(type_j->valuestring, "set_psu_voltage") == 0) {
        const cJSON *v = cJSON_GetObjectItem(root, "v");
        if (!cJSON_IsNumber(v)) return;
        ctrl_cmd_t c = {
            .kind = CTRL_CMD_PSU_SET_VOLTAGE,
            .psu_set_voltage = { .v = (float)v->valuedouble },
        };
        control_task_post(&c, 0);
    } else if (strcmp(type_j->valuestring, "set_psu_current") == 0) {
        const cJSON *i = cJSON_GetObjectItem(root, "i");
        if (!cJSON_IsNumber(i)) return;
        ctrl_cmd_t c = {
            .kind = CTRL_CMD_PSU_SET_CURRENT,
            .psu_set_current = { .i = (float)i->valuedouble },
        };
        control_task_post(&c, 0);
    } else if (strcmp(type_j->valuestring, "set_psu_output") == 0) {
        const cJSON *on = cJSON_GetObjectItem(root, "on");
        if (!cJSON_IsBool(on) && !cJSON_IsNumber(on)) return;
        bool b = cJSON_IsBool(on) ? cJSON_IsTrue(on) : (on->valuedouble != 0);
        ctrl_cmd_t c = {
            .kind = CTRL_CMD_PSU_SET_OUTPUT,
            .psu_set_output = { .on = b ? 1 : 0 },
        };
        control_task_post(&c, 0);
    } else if (strcmp(type_j->valuestring, "set_psu_slave") == 0) {
        const cJSON *a = cJSON_GetObjectItem(root, "addr");
        if (!cJSON_IsNumber(a)) return;
        int v = (int)a->valuedouble;
        if (v < 1 || v > 247) return;
        ctrl_cmd_t c = {
            .kind = CTRL_CMD_PSU_SET_SLAVE,
            .psu_set_slave = { .addr = (uint8_t)v },
        };
        control_task_post(&c, 0);
```

- [ ] **Step 3: Add the `psu` block to the 20 Hz status JSON**

Find the function that builds the status JSON (look for a `cJSON_CreateObject` call followed by `gpio` or `power` insertions — same pattern). Add a `psu` sub-object alongside the existing `gpio`/`power`/etc. blocks. Example (insert next to where `gpio` is added):

```c
    {
        psu_modbus_telemetry_t pt;
        psu_modbus_get_telemetry(&pt);
        cJSON *psu = cJSON_AddObjectToObject(root, "psu");
        cJSON_AddNumberToObject(psu, "v_set",  pt.v_set);
        cJSON_AddNumberToObject(psu, "i_set",  pt.i_set);
        cJSON_AddNumberToObject(psu, "v_out",  pt.v_out);
        cJSON_AddNumberToObject(psu, "i_out",  pt.i_out);
        cJSON_AddBoolToObject  (psu, "output", pt.output_on);
        cJSON_AddBoolToObject  (psu, "link",   pt.link_ok);
        cJSON_AddStringToObject(psu, "model",  psu_modbus_get_model_name());
        cJSON_AddNumberToObject(psu, "slave",  psu_modbus_get_slave_addr());
    }
```

If the status JSON is built in a different file, search for `"gpio"` to locate it:

```bash
grep -rn '"gpio"' components/net_dashboard/
```

and apply the same pattern there.

- [ ] **Step 4: Build**

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 5: Commit**

```bash
git add components/net_dashboard/CMakeLists.txt components/net_dashboard/ws_handler.c
git commit -m "feat(ws): accept set_psu_* + include psu block in 20 Hz status"
```

---

### Task 12: device_info HTTP — expose psu_* metadata fields

**Files:**
- Modify: `components/net_dashboard/net_dashboard.c` (or whichever file builds `device_info`)

- [ ] **Step 1: Locate the device_info JSON builder**

```bash
grep -rn "psu_uart\|power_switch\|group_a" components/net_dashboard/
```

- [ ] **Step 2: Add psu_* fields next to the existing pin-number fields**

```c
    cJSON_AddNumberToObject(root, "psu_uart_tx_pin", CONFIG_APP_PSU_UART_TX_GPIO);
    cJSON_AddNumberToObject(root, "psu_uart_rx_pin", CONFIG_APP_PSU_UART_RX_GPIO);
    cJSON_AddNumberToObject(root, "psu_baud",        CONFIG_APP_PSU_UART_BAUD);
    cJSON_AddStringToObject(root, "psu_model_name",  psu_modbus_get_model_name());

    {
        psu_modbus_telemetry_t pt;
        psu_modbus_get_telemetry(&pt);
        // Slider clamps. Empty/unknown model → conservative defaults (RD6006 6 A).
        float i_max = (pt.i_scale_div >= 999.0f || pt.i_scale_div < 1.0f) ? 6.0f : 24.0f;
        cJSON_AddNumberToObject(root, "psu_v_max", 60.0);
        cJSON_AddNumberToObject(root, "psu_i_max", i_max);
    }
```

Add `#include "psu_modbus.h"` and `#include "sdkconfig.h"` to that file if missing.

- [ ] **Step 3: Build**

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 4: Commit**

```bash
git add components/net_dashboard/net_dashboard.c
git commit -m "feat(device_info): expose psu_uart pins, baud, model name, V/I max"
```

---

### Task 13: Dashboard HTML — collapsible Power Supply panel skeleton

**Files:**
- Modify: `components/net_dashboard/web/index.html`

- [ ] **Step 1: Insert the panel above the GPIO panel**

Search for the GPIO panel container in `index.html` (look for an id or class containing `gpio` / `group-a`). Insert the following HTML **immediately above** it:

```html
<details id="psu-panel" class="panel" open>
  <summary>
    <span data-i18n="psu_title">Power Supply</span>
    <span class="psu-meta"><span id="psu-model">—</span> · slave <span id="psu-slave">—</span></span>
    <span id="psu-link" class="psu-link" data-state="down" title="link"></span>
  </summary>
  <div class="psu-body">
    <div class="psu-row">
      <label data-i18n="psu_v_set">V set</label>
      <input type="range" id="psu-v-slider" min="0" max="60" step="0.01" value="0" />
      <input type="number" id="psu-v-input" min="0" max="60" step="0.01" value="0" />
      <span class="psu-unit">V</span>
      <span class="psu-meas"><span data-i18n="psu_measured">measured</span> <span id="psu-v-out">0.00</span> V</span>
    </div>
    <div class="psu-row">
      <label data-i18n="psu_i_set">I set</label>
      <input type="range" id="psu-i-slider" min="0" max="6" step="0.001" value="0" />
      <input type="number" id="psu-i-input" min="0" max="6" step="0.001" value="0" />
      <span class="psu-unit">A</span>
      <span class="psu-meas"><span data-i18n="psu_measured">measured</span> <span id="psu-i-out">0.000</span> A</span>
    </div>
    <div class="psu-row">
      <label data-i18n="psu_output">Output</label>
      <button id="psu-out-off" class="psu-btn">OFF</button>
      <button id="psu-out-on"  class="psu-btn">ON</button>
    </div>
    <div class="psu-row psu-settings">
      <label data-i18n="psu_slave_lbl">Slave addr</label>
      <input type="number" id="psu-slave-input" min="1" max="247" value="1" />
      <button id="psu-slave-save" data-i18n="psu_save">Save</button>
    </div>
  </div>
</details>
```

- [ ] **Step 2: Build to confirm the embedded files refresh**

```bash
idf.py build
```

Expected: `Project build complete.` (HTML is `EMBED_TXTFILES`'d so it triggers a relink.)

- [ ] **Step 3: Commit**

```bash
git add components/net_dashboard/web/index.html
git commit -m "feat(dashboard): power supply panel skeleton (HTML)"
```

---

### Task 14: Dashboard CSS — Power Supply panel styling

**Files:**
- Modify: `components/net_dashboard/web/app.css`

- [ ] **Step 1: Append PSU styles to app.css**

Append at the end of the file:

```css
/* ---- Power Supply panel ------------------------------------------------- */
#psu-panel .psu-meta {
  font-size: 0.85em;
  opacity: 0.7;
  margin-left: 0.5em;
}
#psu-panel .psu-link {
  display: inline-block;
  width: 0.7em;
  height: 0.7em;
  border-radius: 50%;
  margin-left: 0.5em;
  vertical-align: middle;
}
#psu-panel .psu-link[data-state="up"]   { background: #2cbf3a; }
#psu-panel .psu-link[data-state="down"] { background: #c33; }
#psu-panel .psu-body {
  display: flex;
  flex-direction: column;
  gap: 0.5em;
  padding: 0.5em 0;
}
#psu-panel .psu-row {
  display: grid;
  grid-template-columns: 5em 1fr 6em 1.5em 1fr;
  align-items: center;
  gap: 0.5em;
}
#psu-panel .psu-row.psu-settings {
  grid-template-columns: 5em 6em auto 1fr;
}
#psu-panel .psu-meas {
  font-variant-numeric: tabular-nums;
  opacity: 0.85;
}
#psu-panel .psu-btn {
  padding: 0.3em 0.8em;
  cursor: pointer;
}
#psu-panel.psu-offline .psu-body {
  opacity: 0.4;
  pointer-events: none;
}
```

- [ ] **Step 2: Build**

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 3: Commit**

```bash
git add components/net_dashboard/web/app.css
git commit -m "style(dashboard): PSU panel layout + link indicator + offline grey-out"
```

---

### Task 15: Dashboard JS — PSU panel logic, telemetry binding, i18n

**Files:**
- Modify: `components/net_dashboard/web/app.js`

- [ ] **Step 1: Add i18n strings**

Locate the existing translation tables (search for `i18n` or for an existing key like `gpio_title`). Add these keys to all three language tables:

```js
// English
psu_title:    "Power Supply",
psu_v_set:    "V set",
psu_i_set:    "I set",
psu_output:   "Output",
psu_measured: "measured",
psu_slave_lbl:"Slave addr",
psu_save:     "Save",
psu_offline:  "PSU offline",
```

```js
// 繁體中文
psu_title:    "電源供應器",
psu_v_set:    "電壓設定",
psu_i_set:    "電流設定",
psu_output:   "輸出",
psu_measured: "實測",
psu_slave_lbl:"從機位址",
psu_save:     "儲存",
psu_offline:  "PSU 離線",
```

```js
// 简体中文
psu_title:    "电源供应器",
psu_v_set:    "电压设定",
psu_i_set:    "电流设定",
psu_output:   "输出",
psu_measured: "实测",
psu_slave_lbl:"从机地址",
psu_save:     "保存",
psu_offline:  "PSU 离线",
```

- [ ] **Step 2: Add the PSU panel module after the existing GPIO panel module**

```js
// ---- Power Supply panel --------------------------------------------------
const psuPanel = (() => {
  const panelEl     = document.getElementById('psu-panel');
  const modelEl     = document.getElementById('psu-model');
  const slaveEl     = document.getElementById('psu-slave');
  const linkEl      = document.getElementById('psu-link');
  const vSlider     = document.getElementById('psu-v-slider');
  const vInput      = document.getElementById('psu-v-input');
  const vOutEl      = document.getElementById('psu-v-out');
  const iSlider     = document.getElementById('psu-i-slider');
  const iInput      = document.getElementById('psu-i-input');
  const iOutEl      = document.getElementById('psu-i-out');
  const outOffBtn   = document.getElementById('psu-out-off');
  const outOnBtn    = document.getElementById('psu-out-on');
  const slaveInput  = document.getElementById('psu-slave-input');
  const slaveBtn    = document.getElementById('psu-slave-save');

  // Mirror PWM panel pattern: no lastSent cache; commit on release reads
  // values straight from the inputs.
  const send = (msg) => ws && ws.readyState === 1 && ws.send(JSON.stringify(msg));

  const commitV = () => send({ type: 'set_psu_voltage', v: parseFloat(vInput.value) });
  const commitI = () => send({ type: 'set_psu_current', i: parseFloat(iInput.value) });

  // Slider drag → update number input live (no send); commit on `change`.
  vSlider.addEventListener('input',  () => { vInput.value = vSlider.value; });
  vSlider.addEventListener('change', commitV);
  vInput.addEventListener('change',  () => { vSlider.value = vInput.value; commitV(); });

  iSlider.addEventListener('input',  () => { iInput.value = iSlider.value; });
  iSlider.addEventListener('change', commitI);
  iInput.addEventListener('change',  () => { iSlider.value = iInput.value; commitI(); });

  outOffBtn.addEventListener('click', () => send({ type: 'set_psu_output', on: false }));
  outOnBtn .addEventListener('click', () => send({ type: 'set_psu_output', on: true  }));

  slaveBtn.addEventListener('click', () => {
    const a = parseInt(slaveInput.value, 10);
    if (!(a >= 1 && a <= 247)) return;
    send({ type: 'set_psu_slave', addr: a });
  });

  // Track focus so we don't yank a slider out from under the user.
  let userInteractingV = false, userInteractingI = false;
  [vSlider, vInput].forEach(el => {
    el.addEventListener('focus', () => userInteractingV = true);
    el.addEventListener('blur',  () => userInteractingV = false);
  });
  [iSlider, iInput].forEach(el => {
    el.addEventListener('focus', () => userInteractingI = true);
    el.addEventListener('blur',  () => userInteractingI = false);
  });

  return {
    setRanges(info) {
      if (typeof info.psu_v_max === 'number') {
        vSlider.max = info.psu_v_max; vInput.max = info.psu_v_max;
      }
      if (typeof info.psu_i_max === 'number') {
        iSlider.max = info.psu_i_max; iInput.max = info.psu_i_max;
      }
      if (info.psu_model_name) modelEl.textContent = info.psu_model_name;
    },
    setFromDevice(psu) {
      if (!psu) return;
      modelEl.textContent = psu.model || '—';
      slaveEl.textContent = (psu.slave != null) ? psu.slave : '—';
      linkEl.dataset.state = psu.link ? 'up' : 'down';
      panelEl.classList.toggle('psu-offline', !psu.link);
      if (!userInteractingV) {
        vSlider.value = psu.v_set;
        vInput.value  = psu.v_set;
      }
      if (!userInteractingI) {
        iSlider.value = psu.i_set;
        iInput.value  = psu.i_set;
      }
      vOutEl.textContent = (+psu.v_out).toFixed(2);
      iOutEl.textContent = (+psu.i_out).toFixed(3);
      // Output button highlight.
      outOnBtn .classList.toggle('active',  psu.output);
      outOffBtn.classList.toggle('active', !psu.output);
    }
  };
})();
```

- [ ] **Step 3: Hook PSU panel into the device_info fetch and the WS status handler**

Find the existing code that calls `gpioPanel.setRanges(info)` (after `fetch('/device_info')`) and add the matching PSU call:

```js
psuPanel.setRanges(info);
```

Find the existing WS message handler that updates the GPIO/power panels from the status frame; add:

```js
psuPanel.setFromDevice(msg.psu);
```

- [ ] **Step 4: Build & flash to a board to test (manual hardware step)**

Activate ESP-IDF (e.g. via the **"ESP-IDF 6.0 PWM Project"** desktop shortcut or `esp6 pwm`). Then:

```bash
idf.py build flash monitor
```

Open the dashboard. Confirm the Power Supply panel renders with sliders, an offline grey-out (no PSU yet attached), and link indicator red.

- [ ] **Step 5: Commit**

```bash
git add components/net_dashboard/web/app.js
git commit -m "feat(dashboard): PSU panel logic + telemetry binding + i18n"
```

---

### Task 16: HID frontend — report 0x05 and parse → control_task

**Files:**
- Modify: `components/usb_composite/include/usb_protocol.h`
- Modify: `components/usb_composite/usb_descriptors.c`
- Modify: `components/usb_composite/usb_composite.c`
- Modify: `components/usb_composite/usb_hid_task.c`
- Modify: `components/usb_composite/CMakeLists.txt`

- [ ] **Step 1: Add `psu_modbus` to usb_composite REQUIRES**

In `components/usb_composite/CMakeLists.txt`, add `psu_modbus` to the `REQUIRES` list. (Will use the `app_api` ctrl_cmd struct to post; `psu_modbus.h` is only needed if a frontend wants to read state. Add it for future-proofing.)

- [ ] **Step 2: Define op codes in `usb_protocol.h`**

Append after the existing GPIO HID/CDC defines:

```c
// ---- PSU power supply (HID) ------------------------------------------------

#define USB_HID_REPORT_PSU            0x05   // OUT, 8 B (op, payload[5], _, _)

// op codes inside report 0x05 byte 0
#define USB_HID_PSU_OP_SET_VOLTAGE    0x10   // bytes 1..4 = float LE
#define USB_HID_PSU_OP_SET_CURRENT    0x11   // bytes 1..4 = float LE
#define USB_HID_PSU_OP_SET_OUTPUT     0x12   // byte  1    = 0|1
#define USB_HID_PSU_OP_SET_SLAVE      0x13   // byte  1 = addr, byte 5 = magic 0xA5

#define USB_HID_PSU_SLAVE_MAGIC       0xA5

// ---- PSU power supply (CDC SLIP) ------------------------------------------

#define USB_CDC_OP_PSU_SET_VOLTAGE    0x40   // float LE (4 B)
#define USB_CDC_OP_PSU_SET_CURRENT    0x41   // float LE (4 B)
#define USB_CDC_OP_PSU_SET_OUTPUT     0x42   // u8 (0|1)
#define USB_CDC_OP_PSU_SET_SLAVE      0x43   // u8 addr, u8 magic 0xA5
#define USB_CDC_OP_PSU_TELEMETRY      0x44   // D→H @ 5 Hz: 4×float + u8 flags = 17 B

#define USB_CDC_PSU_SLAVE_MAGIC       0xA5
```

- [ ] **Step 3: Add the new TLC and update the static_assert in `usb_descriptors.c`**

In `components/usb_composite/usb_descriptors.c`, add the new enum value:

```c
enum { REPORT_ID_SET_PWM = 0x01, REPORT_ID_SET_RPM = 0x02, REPORT_ID_FACTORY_RESET = 0x03,
       REPORT_ID_GPIO    = 0x04, REPORT_ID_PSU     = 0x05,
       REPORT_ID_STATUS  = 0x10, REPORT_ID_ACK     = 0x11 };
```

Insert this descriptor block **after** the GPIO 0x04 block and **before** the IN status 0x10 block:

```c
    // 0x05 OUT PSU: 8 bytes
    0x85, REPORT_ID_PSU,
    0x09, 0x06,
    0x75, 0x08, 0x95, 8,
    0x91, 0x02,
```

Update the static_assert from 73 → 83:

```c
_Static_assert(sizeof(usb_hid_report_descriptor) == 83,
               "HID_REPORT_DESC_SIZE in usb_composite.c must match this size");
```

- [ ] **Step 4: Update `HID_REPORT_DESC_SIZE` macro in `usb_composite.c`**

Find the `#define HID_REPORT_DESC_SIZE 73` line in `usb_composite.c` and change to `83`. (Keep the comment about the descriptor count.)

- [ ] **Step 5: Add report 0x05 dispatch in `usb_hid_task.c`**

Locate the existing OUT-report dispatch (the function that switches on `report_id` for 0x01/0x02/0x03/0x04). Add a case for 0x05:

```c
case USB_HID_REPORT_PSU: {
    if (len < 1) break;
    uint8_t op = buf[0];
    ctrl_cmd_t cmd = {0};
    bool ok = false;
    switch (op) {
    case USB_HID_PSU_OP_SET_VOLTAGE:
        if (len < 5) break;
        memcpy(&cmd.psu_set_voltage.v, &buf[1], 4);
        cmd.kind = CTRL_CMD_PSU_SET_VOLTAGE;
        ok = true;
        break;
    case USB_HID_PSU_OP_SET_CURRENT:
        if (len < 5) break;
        memcpy(&cmd.psu_set_current.i, &buf[1], 4);
        cmd.kind = CTRL_CMD_PSU_SET_CURRENT;
        ok = true;
        break;
    case USB_HID_PSU_OP_SET_OUTPUT:
        if (len < 2) break;
        cmd.kind = CTRL_CMD_PSU_SET_OUTPUT;
        cmd.psu_set_output.on = buf[1] ? 1 : 0;
        ok = true;
        break;
    case USB_HID_PSU_OP_SET_SLAVE:
        if (len < 6) break;
        if (buf[5] != USB_HID_PSU_SLAVE_MAGIC) break;
        if (buf[1] < 1 || buf[1] > 247)        break;
        cmd.kind = CTRL_CMD_PSU_SET_SLAVE;
        cmd.psu_set_slave.addr = buf[1];
        ok = true;
        break;
    default: break;
    }
    if (ok) control_task_post(&cmd, 0);
} break;
```

Add `#include "usb_protocol.h"` and `#include "app_api.h"` if they aren't already there. (They are, in the GPIO 0x04 dispatch.)

- [ ] **Step 6: Build**

```bash
idf.py build
```

Expected: `Project build complete.` If you get `_Static_assert failed`, the descriptor size doesn't match — count bytes in the new block (10 bytes) and fix.

- [ ] **Step 7: Commit**

```bash
git add components/usb_composite/include/usb_protocol.h \
        components/usb_composite/usb_descriptors.c \
        components/usb_composite/usb_composite.c \
        components/usb_composite/usb_hid_task.c \
        components/usb_composite/CMakeLists.txt
git commit -m "feat(usb_hid): add report 0x05 for PSU + descriptor grow 73→83"
```

---

### Task 17: CDC frontend — accept 0x40..0x43 + push 0x44 telemetry @ 5 Hz

**Files:**
- Modify: `components/usb_composite/usb_cdc_task.c`

- [ ] **Step 1: Locate the SLIP op dispatch**

Search for an existing case like `USB_CDC_OP_GPIO_SET_MODE` in `usb_cdc_task.c`. The new ops slot into the same switch statement.

- [ ] **Step 2: Add four host→device cases**

```c
case USB_CDC_OP_PSU_SET_VOLTAGE: {
    if (payload_len < 4) break;
    ctrl_cmd_t c = { .kind = CTRL_CMD_PSU_SET_VOLTAGE };
    memcpy(&c.psu_set_voltage.v, payload, 4);
    control_task_post(&c, 0);
} break;
case USB_CDC_OP_PSU_SET_CURRENT: {
    if (payload_len < 4) break;
    ctrl_cmd_t c = { .kind = CTRL_CMD_PSU_SET_CURRENT };
    memcpy(&c.psu_set_current.i, payload, 4);
    control_task_post(&c, 0);
} break;
case USB_CDC_OP_PSU_SET_OUTPUT: {
    if (payload_len < 1) break;
    ctrl_cmd_t c = {
        .kind = CTRL_CMD_PSU_SET_OUTPUT,
        .psu_set_output = { .on = payload[0] ? 1 : 0 },
    };
    control_task_post(&c, 0);
} break;
case USB_CDC_OP_PSU_SET_SLAVE: {
    if (payload_len < 2) break;
    if (payload[1] != USB_CDC_PSU_SLAVE_MAGIC) break;
    if (payload[0] < 1 || payload[0] > 247)    break;
    ctrl_cmd_t c = {
        .kind = CTRL_CMD_PSU_SET_SLAVE,
        .psu_set_slave = { .addr = payload[0] },
    };
    control_task_post(&c, 0);
} break;
```

- [ ] **Step 3: Add a 5 Hz telemetry push (op 0x44)**

Locate the CDC TX task (search for the existing log mirror or a `vTaskDelay` with periodic behaviour). Add a separate periodic push, or piggyback on an existing periodic block. Inside the 5 Hz tick:

```c
{
    psu_modbus_telemetry_t pt;
    psu_modbus_get_telemetry(&pt);

    uint8_t buf[1 /*op*/ + 4*4 /*floats*/ + 1 /*flags*/];
    buf[0] = USB_CDC_OP_PSU_TELEMETRY;
    memcpy(&buf[1],  &pt.v_set, 4);
    memcpy(&buf[5],  &pt.i_set, 4);
    memcpy(&buf[9],  &pt.v_out, 4);
    memcpy(&buf[13], &pt.i_out, 4);
    buf[17] = (pt.output_on ? 0x01 : 0) | (pt.link_ok ? 0x02 : 0);

    // Use the existing slip_send helper. (Search for slip_send / cdc_slip_send.)
    cdc_slip_send(buf, sizeof(buf));
}
```

If a 5 Hz tick doesn't already exist in `usb_cdc_task.c`, add one — a simple `vTaskDelay(pdMS_TO_TICKS(200))` loop is acceptable; place it next to the existing TX-side processing so we don't fan out new tasks.

Add `#include "psu_modbus.h"` to the file.

- [ ] **Step 4: Build**

```bash
idf.py build
```

Expected: `Project build complete.`

- [ ] **Step 5: Commit**

```bash
git add components/usb_composite/usb_cdc_task.c
git commit -m "feat(usb_cdc): handle PSU SLIP ops 0x40..0x43 + push 0x44 telemetry @ 5 Hz"
```

---

### Task 18: Update CLAUDE.md with UART1 pin reservation + invariant note

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add UART1 to the "Pins reserved by hardware" sentence**

Search for the line `Pins reserved by hardware: **19, 20** (USB).` In the same paragraph, add a follow-up sentence:

```text
UART1 (PSU Modbus) defaults to GPIO 38 (TX) / 39 (RX) at 19200-8N1; both
are Kconfig-overridable.
```

- [ ] **Step 2: Add a PSU section after the GPIO/power_switch section**

After the "Factory reset / reprovision" section, append:

````markdown
## PSU Modbus-RTU master (5th controllable subsystem)

Hand-rolled RTU master targeting the Riden RD60xx family (RD6006 / RD6012 /
RD6018). UART1 @ 19200-8N1 on GPIO 38/39 (Kconfig overridable). One
peripheral driver, four frontends — same single-handler invariant as PWM,
RPM, GPIO, and the relay power switch:

```text
Wi-Fi WS  set_psu_voltage / current / output / slave  ──┐
USB HID 0x05 + ops 0x10..0x13                            ├──► control_task ──► psu_modbus_set_*()
USB CDC ops 0x40..0x43                                   │
CLI psu_v / psu_i / psu_out / psu_slave                  ──┘
```

Telemetry (V_SET/I_SET/V_OUT/I_OUT/output) polled at 5 Hz, published as
atomic bit-punned floats. Surfaces in the 20 Hz WS status frame as a
`psu` block, in CDC op `0x44` at 5 Hz, and via `psu_status` CLI.

Slave address is NVS-persisted in namespace `psu_modbus`, key
`slave_addr`. Setting it does **not** issue a Modbus write — the supply's
own slave address is set from the supply's front panel; firmware just
matches it.

Hand-rolled (not `esp-modbus`) because we use 2 function codes and 5
registers — adding another component-manager pin alongside
`esp_tinyusb` / `mdns` / `cjson` would exceed the LoC saved.
````

- [ ] **Step 2: Build sanity (CLAUDE.md doesn't affect the build)**

```bash
git diff --stat CLAUDE.md
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): document UART1 PSU Modbus reservation + invariant"
```

---

### Task 19: Hardware-in-the-loop integration verification

**Files:** none (manual hardware test)

> **Pre-flight:** activate ESP-IDF v6.0 (desktop shortcut **"ESP-IDF 6.0 PWM Project"** or `esp6 pwm`). The Riden supply must be powered on, its TTL daughterboard must be connected to ESP32 UART1 (TX→RX cross-wire, GND shared), and the supply's front-panel comm setting must be Modbus 19200 8N1, slave address matching what the firmware has in NVS (default 1).

- [ ] **Step 1: Flash and boot**

```bash
idf.py -p COM24 flash monitor
```

Expected boot log lines (in order):

```text
psu_modbus: UART1 ready: tx=38 rx=39 baud=19200 slave=1
psu_modbus: detected model 60062 (RD6006, I scale = ÷1000)
```

If model detection logs `model detect failed` instead, check wiring and slave address.

- [ ] **Step 2: CLI smoke test**

In the monitor REPL:

```text
psu_v 5.0
psu_i 1.0
psu_out 1
psu_status
psu_out 0
```

Expected: supply display matches each command within ~200 ms; `psu_status` prints `link=up` and the new setpoints.

- [ ] **Step 3: Dashboard test**

Open `http://fan-testkit.local/`. Verify:

1. Power Supply panel renders with link indicator green.
2. Drag V slider → supply tracks within ~200 ms; `measured` field updates.
3. Drag I slider → same.
4. Click ON → supply output enables, button highlights.
5. Click OFF → output disables.

- [ ] **Step 4: Link-loss recovery test**

Unplug the UART cable from the supply. Within ~1 s:

- Monitor logs `psu_modbus: link lost: ESP_ERR_TIMEOUT` (once).
- Dashboard panel greys out, link indicator red.

Re-plug. Within ~1 s:

- Monitor logs `psu_modbus: link recovered`.
- Dashboard panel restores, link indicator green.

- [ ] **Step 5: Slave-address persistence**

```text
psu_slave 5
```

Power-cycle the board. After reboot, `psu_status` should still report `slave=5`. Restore with `psu_slave 1`.

- [ ] **Step 6: Boot-with-PSU-disconnected test**

Power off the supply (or unplug UART). Reboot the board. Verify:

- Boot log shows `model detect failed (PSU offline at boot?); falling back to RD6006 scale`.
- Firmware stays up; PWM/RPM/GPIO all work normally.
- Dashboard shows PSU panel offline.
- Power on the supply → within ~2 s, model detection completes on the next poll, panel goes online.

- [ ] **Step 7: No commit needed** — this task is a verification gate, not a code change. If any step fails, revisit the relevant code task and fix.

---

## Out-of-scope follow-ups (do NOT include in v1)

- OVP/OCP read & write (registers 0x82/0x83/0x60/0x61).
- CV/CC mode bit, internal temperature, energy counters.
- Battery / charge mode registers.
- RS-485 transceiver (DE pin GPIO).
- Multi-PSU chaining.
- ESP-Modbus migration if requirements expand significantly.
