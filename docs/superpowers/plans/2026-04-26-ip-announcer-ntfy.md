# IP Announcer (ntfy.sh push) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an opt-in `ip_announcer` component that pushes the device's IP to the user's phone via ntfy.sh after every Wi-Fi association, surfacing the topic + ntfy deep-link in the captive-portal `/success` page so the user can subscribe with one tap.

**Architecture:**
- New self-contained `components/ip_announcer/` owning NVS settings, IP-event hook, and a dedicated push task. Pattern matches `ui_settings` (NVS-backed atomic state) + `psu_driver` (worker task drains a queue).
- Single-handler invariant: one push handler in `ip_announcer.c`; four transports (WS / HID / CDC / CLI) translate protocol only.
- 3-tier topic resolution at first boot: NVS → Kconfig `APP_IP_ANNOUNCER_TOPIC_DEFAULT` → random `fan-testkit-<32 chars>` fallback. Result persisted to NVS so subsequent boots take fast path.
- Placeholder safety guard refuses pushes for topics matching `CHANGE-ME-*` / `fan-testkit-CHANGE*` or shorter than 16 chars; surfaced as red banner in dashboard.
- Captive-portal `/success` HTML extended with new ntfy section, including `ntfy://ntfy.sh/<topic>?subscribe=1` deep-link.

**Tech Stack:** ESP-IDF v6.0, `esp_http_client` + `esp_crt_bundle` (Mozilla bundle includes `*.ntfy.sh`), `esp_random`, NVS, FreeRTOS queue + task, cJSON for WS, esp_console for CLI, TinyUSB HID/CDC.

**Branch:** Spec calls for `feature/ip-announcer` cut from current `feature/psu-modbus-rtu`. Before starting Phase 1, run:

```bash
git checkout -b feature/ip-announcer
```

**Phasing:** Five phases, each ending with a working build that can be flashed and tested.

1. **Phase 1** — Component skeleton + NVS layer + topic resolution. Boot test: log shows resolved topic.
2. **Phase 2** — Real HTTPS push via esp_http_client. Manual test: ntfy app receives notification.
3. **Phase 3** — Wi-Fi event hook + dedupe + safety guard. Cold-boot test: notification arrives once per IP change.
4. **Phase 4** — All 4 transports (WS / HID / CDC / CLI) + dashboard panel + WS telemetry frame extension.
5. **Phase 5** — Captive-portal `/success` integration + i18n + Help section + README/CLAUDE.md updates.

---

## Files Touched (overview)

### Phase 1 — Component skeleton + NVS + topic resolution
- Create: `components/ip_announcer/CMakeLists.txt`
- Create: `components/ip_announcer/Kconfig`
- Create: `components/ip_announcer/include/ip_announcer.h`
- Create: `components/ip_announcer/ip_announcer.c`
- Modify: `main/CMakeLists.txt` — add `ip_announcer` to REQUIRES
- Modify: `main/app_main.c` — call `ip_announcer_init()` before `net_dashboard_start()`
- Modify: `.gitignore` — add `sdkconfig.defaults.local`

### Phase 2 — HTTPS push
- Create: `components/ip_announcer/ip_announcer_push.c`
- Modify: `components/ip_announcer/CMakeLists.txt` — add `ip_announcer_push.c` source + `esp_http_client esp-tls` REQUIRES
- Modify: `components/ip_announcer/ip_announcer.c` — wire push task + queue

### Phase 3 — IP event hook + dedupe + safety guard
- Modify: `components/ip_announcer/ip_announcer.c` — register `IP_EVENT_STA_GOT_IP` handler, dedupe, safety guard

### Phase 4 — Transports + dashboard
- Modify: `components/usb_composite/include/usb_protocol.h` — `USB_HID_REPORT_ANNOUNCER` + `USB_CDC_OP_ANNOUNCER_*`
- Modify: `components/usb_composite/usb_descriptors.c` — descriptor + 1 report id; bump `_Static_assert` 93 → 103
- Modify: `components/usb_composite/usb_composite.c` — `HID_REPORT_DESC_SIZE` 93 → 103
- Modify: `components/usb_composite/usb_hid_task.c` — handle report 0x07
- Modify: `components/usb_composite/usb_cdc_task.c` — handle ops 0x60/0x61, emit 0x62/0x63
- Modify: `components/app_api/include/app_api.h` — 3 new ctrl_cmd kinds
- Modify: `main/control_task.c` — handle 3 new cmd kinds
- Modify: `components/net_dashboard/CMakeLists.txt` — add `ip_announcer` to REQUIRES
- Modify: `components/net_dashboard/ws_handler.c` — `set_announcer` / `test_announcer` handlers + `announcer` block in 20 Hz status frame
- Modify: `components/net_dashboard/web/index.html` — Settings panel
- Modify: `components/net_dashboard/web/app.js` — i18n keys, WS handler, UI bindings, status-line update
- Modify: `main/app_main.c` — register 3 new CLI commands

### Phase 5 — Captive portal + docs
- Modify: `components/net_dashboard/CMakeLists.txt` — already in Phase 4, no further change
- Modify: `components/net_dashboard/captive_portal.c` — extend `repl[][]` from 2 to 5 tokens, pull topic via `ip_announcer_get_settings`
- Modify: `components/net_dashboard/web/success.html` — new ntfy section with `{{NTFY_TOPIC}}` / `{{NTFY_DEEPLINK}}` / `{{NTFY_WEBLINK}}` tokens
- Modify: `components/net_dashboard/web/app.js` — Help section i18n strings (added in Phase 4 too; if missed there, add here)
- Modify: `components/net_dashboard/web/index.html` — Help footer `<details>` block
- Modify: `README.md` — feature note
- Modify: `CLAUDE.md` — `ip_announcer` namespace in NVS-tunables section

---

## Wire-Protocol Additions (locked before code is written)

These are the contract values used throughout the plan.

### WebSocket ops (client → device)

```json
{"type":"set_announcer","enable":true,"topic":"...","server":"ntfy.sh","priority":3}
{"type":"test_announcer"}
```

Each generates `{"type":"ack","op":"set_announcer"|"test_announcer","ok":true|false}`.

### WebSocket status frame extension (device → client)

The 20 Hz status frame gains an `announcer` block:

```json
"announcer":{"enable":true,"topic":"fan-testkit-...","server":"ntfy.sh","priority":3,
             "status":"ok","last_pushed_ip":"192.168.49.123","last_http_code":200,
             "last_err":""}
```

`status` values: `"never" | "ok" | "failed" | "disabled"`.

### HID report ID and op codes

```text
USB_HID_REPORT_ANNOUNCER       0x07   OUT, 8 B (op + payload)

  USB_HID_ANN_OP_ENABLE_TOGGLE 0x01   payload byte 1: 0|1
  USB_HID_ANN_OP_TEST_PUSH     0x02   no payload
```

Topic / server / priority do not flow through HID — too long for an 8-byte payload, and rarely changed compared to enable+test.

### CDC SLIP ops

```text
USB_CDC_OP_ANNOUNCER_SET       0x60   H→D  u8 enable, u8 priority, str topic\0 str server\0
USB_CDC_OP_ANNOUNCER_TEST      0x61   H→D  empty payload
USB_CDC_OP_ANNOUNCER_TELEMETRY 0x62   D→H  5 Hz: u8 enable, u8 priority, u8 status_enum,
                                                u16 last_http_code, str last_pushed_ip\0
                                                str topic\0 str server\0 str last_err\0
USB_CDC_OP_ANNOUNCER_RESULT    0x63   D→H  fired on each push final outcome:
                                                u8 ok, u16 http_code, str ip\0 str err\0
```

### CLI commands

```text
announcer_set <topic> [server] [priority]    priority defaults to 3
announcer_enable <0|1>
announcer_test
announcer_status
```

### control_task command kinds

```c
CTRL_CMD_ANNOUNCER_SET,         // payload: bool enable, u8 priority, char topic[65], char server[97]
CTRL_CMD_ANNOUNCER_TEST,        // no payload
CTRL_CMD_ANNOUNCER_ENABLE,      // payload: u8 enable
```

### NVS keys (namespace `ip_announcer`)

| Key       | Type | Notes                                              |
|-----------|------|----------------------------------------------------|
| `enable`  | u8   | 0 = disabled, 1 = enabled. Default 0.              |
| `topic`   | str  | 8..64 chars `[a-zA-Z0-9_-]+`. Resolved on first boot. |
| `server`  | str  | hostname-only, default `"ntfy.sh"`.                |
| `priority`| u8   | 1..5, default 3.                                   |
| `last_ip` | str  | last successfully-pushed IP, default `""`.         |

---

## Phase 1 — Component skeleton + NVS + topic resolution

### Task 1.1: Create the component skeleton

**Files:**
- Create: `components/ip_announcer/CMakeLists.txt`
- Create: `components/ip_announcer/Kconfig`
- Create: `components/ip_announcer/include/ip_announcer.h`
- Create: `components/ip_announcer/ip_announcer.c`

- [ ] **Step 1: Create `components/ip_announcer/CMakeLists.txt`**

```cmake
idf_component_register(
    SRCS         "ip_announcer.c"
    INCLUDE_DIRS "include"
    REQUIRES     log
                 nvs_flash
                 esp_event
                 esp_netif
                 app_api
)
```

(`esp_http_client` and `esp-tls` REQUIRES are added in Phase 2 when `ip_announcer_push.c` is introduced.)

- [ ] **Step 2: Create `components/ip_announcer/Kconfig`**

```kconfig
menu "IP Announcer (ntfy)"

config APP_IP_ANNOUNCER_TOPIC_DEFAULT
    string "Default ntfy topic (empty = auto-generate random)"
    default ""
    help
        Topic name pushed to ntfy.sh on every IP_EVENT_STA_GOT_IP.
        WARNING: this is your channel's de-facto password — anyone
        who reads this string from your repo can subscribe and see
        every IP this device pushes. Either:
          - Leave empty: each board generates a private random topic
            on first boot. Recommended for shared / public builds.
          - Set in sdkconfig.defaults.local (gitignored): all boards
            from your private build share one topic. Convenient for
            multi-board ownership; do NOT commit this file.
        Topics that look like a placeholder ("CHANGE-ME-*", or fewer
        than 16 chars after trimming) refuse to push at runtime and
        the dashboard surfaces a red warning.

config APP_IP_ANNOUNCER_SERVER_DEFAULT
    string "Default ntfy server hostname"
    default "ntfy.sh"
    help
        Hostname only, no scheme, no path. Override at runtime via
        the dashboard / CLI for self-hosted ntfy instances.

endmenu
```

- [ ] **Step 3: Create `components/ip_announcer/include/ip_announcer.h`**

```c
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

// Settings shape — public so transports / dashboard can populate it.
typedef struct {
    bool        enable;
    char        topic[65];     // 64-char + NUL
    char        server[97];    // hostname-only
    uint8_t     priority;      // 1..5
} ip_announcer_settings_t;

// Telemetry shape — published in 20 Hz WS status frame and HID/CDC mirrors.
typedef enum {
    IP_ANN_STATUS_NEVER = 0,
    IP_ANN_STATUS_OK,
    IP_ANN_STATUS_FAILED,
    IP_ANN_STATUS_DISABLED,
} ip_announcer_status_t;

typedef struct {
    ip_announcer_status_t status;
    int                   last_http_code;       // 0 if never tried
    char                  last_pushed_ip[16];   // dotted-quad, "" if never
    char                  last_err[48];         // human-readable, "" on success
    int64_t               last_attempt_ms;      // esp_timer_get_time / 1000
} ip_announcer_telemetry_t;

// Lifecycle (called from app_main BEFORE net_dashboard_start).
esp_err_t ip_announcer_init(void);

// Settings getters/setters. set persists to NVS.
esp_err_t ip_announcer_get_settings(ip_announcer_settings_t *out);
esp_err_t ip_announcer_set_settings(const ip_announcer_settings_t *in);

// Toggle enable only (used by HID 0x07 op 0x01).
esp_err_t ip_announcer_set_enable(bool enable);

// Read-only telemetry snapshot.
void ip_announcer_get_telemetry(ip_announcer_telemetry_t *out);

// Trigger an immediate push of the current STA IP. Async — returns
// ESP_OK after enqueueing. Implemented in Phase 2.
esp_err_t ip_announcer_test_push(void);

#ifdef __cplusplus
}
#endif
```

- [ ] **Step 4: Create `components/ip_announcer/ip_announcer.c` (initial skeleton — NVS load + topic resolution + getters/setters; push fn stubs)**

```c
#include "ip_announcer.h"

#include <string.h>
#include <stdatomic.h>

#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "nvs.h"
#include "sdkconfig.h"

static const char *TAG = "ip_announcer";

#define NVS_NAMESPACE       "ip_announcer"
#define NVS_KEY_ENABLE      "enable"
#define NVS_KEY_TOPIC       "topic"
#define NVS_KEY_SERVER      "server"
#define NVS_KEY_PRIORITY    "priority"
#define NVS_KEY_LAST_IP     "last_ip"

#define DEFAULT_PRIORITY    3

// Mutex protecting s_settings + s_telemetry.
static SemaphoreHandle_t s_lock;
static ip_announcer_settings_t  s_settings;
static ip_announcer_telemetry_t s_telemetry;

static void generate_random_topic(char *out, size_t out_size)
{
    static const char alphabet[] =
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789";  // 62 chars
    char tok[33];
    for (int i = 0; i < 32; i++) {
        tok[i] = alphabet[esp_random() % 62];
    }
    tok[32] = '\0';
    snprintf(out, out_size, "fan-testkit-%s", tok);
}

static esp_err_t persist_settings_unlocked(const ip_announcer_settings_t *s)
{
    nvs_handle_t h;
    esp_err_t e = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (e != ESP_OK) return e;
    esp_err_t e1 = nvs_set_u8 (h, NVS_KEY_ENABLE,   s->enable ? 1 : 0);
    esp_err_t e2 = nvs_set_str(h, NVS_KEY_TOPIC,    s->topic);
    esp_err_t e3 = nvs_set_str(h, NVS_KEY_SERVER,   s->server);
    esp_err_t e4 = nvs_set_u8 (h, NVS_KEY_PRIORITY, s->priority);
    esp_err_t ec = (e1 == ESP_OK && e2 == ESP_OK && e3 == ESP_OK && e4 == ESP_OK)
                   ? nvs_commit(h) : ESP_OK;
    nvs_close(h);
    if (e1 != ESP_OK) return e1;
    if (e2 != ESP_OK) return e2;
    if (e3 != ESP_OK) return e3;
    if (e4 != ESP_OK) return e4;
    return ec;
}

esp_err_t ip_announcer_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    if (!s_lock) return ESP_ERR_NO_MEM;

    memset(&s_settings,  0, sizeof(s_settings));
    memset(&s_telemetry, 0, sizeof(s_telemetry));
    s_settings.priority  = DEFAULT_PRIORITY;
    s_telemetry.status   = IP_ANN_STATUS_NEVER;

    nvs_handle_t h;
    esp_err_t e = nvs_open(NVS_NAMESPACE, NVS_READONLY, &h);
    bool nvs_has_topic = false;
    if (e == ESP_OK) {
        uint8_t en = 0;
        if (nvs_get_u8(h, NVS_KEY_ENABLE, &en) == ESP_OK) {
            s_settings.enable = (en != 0);
        }
        size_t sz = sizeof(s_settings.topic);
        if (nvs_get_str(h, NVS_KEY_TOPIC, s_settings.topic, &sz) == ESP_OK
            && s_settings.topic[0] != '\0') {
            nvs_has_topic = true;
        }
        sz = sizeof(s_settings.server);
        nvs_get_str(h, NVS_KEY_SERVER, s_settings.server, &sz);
        uint8_t pr = DEFAULT_PRIORITY;
        if (nvs_get_u8(h, NVS_KEY_PRIORITY, &pr) == ESP_OK) {
            if (pr < 1) pr = 1;
            if (pr > 5) pr = 5;
            s_settings.priority = pr;
        }
        sz = sizeof(s_telemetry.last_pushed_ip);
        nvs_get_str(h, NVS_KEY_LAST_IP, s_telemetry.last_pushed_ip, &sz);
        nvs_close(h);
    }

    // 3-tier topic resolution.
    if (!nvs_has_topic) {
        const char *kcfg = CONFIG_APP_IP_ANNOUNCER_TOPIC_DEFAULT;
        if (kcfg && kcfg[0] != '\0') {
            strncpy(s_settings.topic, kcfg, sizeof(s_settings.topic) - 1);
            s_settings.topic[sizeof(s_settings.topic) - 1] = '\0';
            ESP_LOGI(TAG, "topic from Kconfig: %s", s_settings.topic);
        } else {
            generate_random_topic(s_settings.topic, sizeof(s_settings.topic));
            ESP_LOGI(TAG, "topic random-generated: %s", s_settings.topic);
        }
    } else {
        ESP_LOGI(TAG, "topic from NVS: %s", s_settings.topic);
    }

    // Server fallback to Kconfig if not in NVS.
    if (s_settings.server[0] == '\0') {
        const char *kcfg = CONFIG_APP_IP_ANNOUNCER_SERVER_DEFAULT;
        const char *src = (kcfg && kcfg[0] != '\0') ? kcfg : "ntfy.sh";
        strncpy(s_settings.server, src, sizeof(s_settings.server) - 1);
        s_settings.server[sizeof(s_settings.server) - 1] = '\0';
    }

    // Persist resolved topic + server back so subsequent boots take
    // the fast path.
    esp_err_t pe = persist_settings_unlocked(&s_settings);
    if (pe != ESP_OK) {
        ESP_LOGW(TAG, "persist on init failed: %s", esp_err_to_name(pe));
    }

    ESP_LOGI(TAG, "init: enable=%d topic=%s server=%s priority=%u",
             s_settings.enable, s_settings.topic, s_settings.server,
             s_settings.priority);
    return ESP_OK;
}

esp_err_t ip_announcer_get_settings(ip_announcer_settings_t *out)
{
    if (!out) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    *out = s_settings;
    xSemaphoreGive(s_lock);
    return ESP_OK;
}

esp_err_t ip_announcer_set_settings(const ip_announcer_settings_t *in)
{
    if (!in) return ESP_ERR_INVALID_ARG;
    if (in->topic[0] == '\0' || strlen(in->topic) < 8 || strlen(in->topic) > 64) {
        return ESP_ERR_INVALID_ARG;
    }
    if (in->server[0] == '\0') return ESP_ERR_INVALID_ARG;
    uint8_t pr = in->priority;
    if (pr < 1) pr = 1;
    if (pr > 5) pr = 5;

    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_settings.enable   = in->enable;
    strncpy(s_settings.topic,  in->topic,  sizeof(s_settings.topic) - 1);
    s_settings.topic[sizeof(s_settings.topic) - 1] = '\0';
    strncpy(s_settings.server, in->server, sizeof(s_settings.server) - 1);
    s_settings.server[sizeof(s_settings.server) - 1] = '\0';
    s_settings.priority = pr;
    esp_err_t e = persist_settings_unlocked(&s_settings);
    xSemaphoreGive(s_lock);
    return e;
}

esp_err_t ip_announcer_set_enable(bool enable)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_settings.enable = enable;
    esp_err_t e = persist_settings_unlocked(&s_settings);
    xSemaphoreGive(s_lock);
    return e;
}

void ip_announcer_get_telemetry(ip_announcer_telemetry_t *out)
{
    if (!out) return;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    *out = s_telemetry;
    xSemaphoreGive(s_lock);
}

// Push fn — wired in Phase 2.
esp_err_t ip_announcer_test_push(void)
{
    ESP_LOGW(TAG, "test_push: not yet wired (Phase 2)");
    return ESP_OK;
}
```

- [ ] **Step 5: Add `ip_announcer` to `main/CMakeLists.txt` REQUIRES**

Open `main/CMakeLists.txt`, find the `REQUIRES` clause (it lists components like `app_api`, `gpio_io`, `pwm_gen`, etc.), and add `ip_announcer`.

- [ ] **Step 6: Wire `ip_announcer_init()` in `app_main`**

Edit `main/app_main.c`. Find the existing `ESP_ERROR_CHECK(ui_settings_init());` line. Add the new init call **immediately after `ui_settings_init` and before `usb_composite_start` / `net_dashboard_start`**:

```c
ESP_ERROR_CHECK(ui_settings_init());

// IP Announcer must init BEFORE net_dashboard so its IP_EVENT
// handler is registered before provisioning fires the first
// IP_EVENT_STA_GOT_IP.
ESP_ERROR_CHECK(ip_announcer_init());
```

Add the include near the top of the file alongside the other component headers:

```c
#include "ip_announcer.h"
```

- [ ] **Step 7: Add `sdkconfig.defaults.local` to `.gitignore`**

Open `.gitignore` and append:

```text
# Per-developer Kconfig overrides (private ntfy topic etc.)
sdkconfig.defaults.local
```

- [ ] **Step 8: Build and verify**

Run:

```bash
idf.py build
```

Expected: clean build. No new warnings. Binary size grows by ~3 KB (component skeleton, no HTTP yet).

- [ ] **Step 9: Flash + boot, verify topic resolution**

Run:

```bash
idf.py -p COM24 flash monitor
```

Expected log lines on first boot (NVS empty):

```text
I (xxx) ip_announcer: topic random-generated: fan-testkit-<32 random chars>
I (xxx) ip_announcer: init: enable=0 topic=fan-testkit-... server=ntfy.sh priority=3
```

Power-cycle. Expected on second boot:

```text
I (xxx) ip_announcer: topic from NVS: fan-testkit-<same as before>
I (xxx) ip_announcer: init: enable=0 topic=fan-testkit-... server=ntfy.sh priority=3
```

The topic must be identical across both boots — proves NVS persistence.

- [ ] **Step 10: Verify Kconfig override path**

Create `sdkconfig.defaults.local` (do not commit):

```text
CONFIG_APP_IP_ANNOUNCER_TOPIC_DEFAULT="fan-testkit-test-kconfig-override-123456"
```

Erase NVS to force re-resolution:

```bash
idf.py -p COM24 erase-flash
del sdkconfig
idf.py build
idf.py -p COM24 flash monitor
```

Expected log:

```text
I (xxx) ip_announcer: topic from Kconfig: fan-testkit-test-kconfig-override-123456
```

Then delete `sdkconfig.defaults.local` and `del sdkconfig` again to revert for subsequent tasks.

- [ ] **Step 11: Commit**

```bash
git add components/ip_announcer/ main/CMakeLists.txt main/app_main.c .gitignore
git commit -m "feat(ip_announcer): component skeleton + NVS layer + topic resolution

Phase 1 of ntfy.sh push integration. Wires the new component into
the build, registers ip_announcer_init() before net_dashboard_start()
so the IP_EVENT hook (Phase 3) lands before provisioning fires.
Topic resolution chain: NVS → Kconfig APP_IP_ANNOUNCER_TOPIC_DEFAULT
→ random fan-testkit-<32 chars> fallback. Resolved topic persisted
back to NVS so subsequent boots take the fast path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — HTTPS push to ntfy.sh

### Task 2.1: Add the push worker module

**Files:**
- Create: `components/ip_announcer/ip_announcer_push.c`
- Modify: `components/ip_announcer/CMakeLists.txt`
- Modify: `components/ip_announcer/ip_announcer.c` — start push task in init, expose `ip_announcer_test_push`, expose `ip_announcer_priv_enqueue_push(const char *ip)` for Phase 3.

- [ ] **Step 1: Add `esp_http_client esp-tls` to REQUIRES + new source**

Edit `components/ip_announcer/CMakeLists.txt`:

```cmake
idf_component_register(
    SRCS         "ip_announcer.c"
                 "ip_announcer_push.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "."
    REQUIRES     log
                 nvs_flash
                 esp_event
                 esp_netif
                 esp_http_client
                 esp-tls
                 app_api
)
```

- [ ] **Step 2: Create the private header `components/ip_announcer/ip_announcer_priv.h`**

```c
#pragma once

#include "ip_announcer.h"

#ifdef __cplusplus
extern "C" {
#endif

// Worker-side API used by ip_announcer.c to drive ip_announcer_push.c.

esp_err_t ip_announcer_push_init(void);

// Called from ip_announcer.c. Snapshots settings + IP, enqueues push job.
// Updates the telemetry block on completion via the helper below.
esp_err_t ip_announcer_priv_enqueue_push(const char *ip);

// Updaters used by push worker — defined in ip_announcer.c.
void ip_announcer_priv_set_telemetry(const ip_announcer_telemetry_t *t);
void ip_announcer_priv_get_settings(ip_announcer_settings_t *out);

#ifdef __cplusplus
}
#endif
```

- [ ] **Step 3: Create `components/ip_announcer/ip_announcer_push.c`**

```c
#include "ip_announcer_priv.h"

#include <string.h>
#include <stdio.h>

#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

static const char *TAG = "ip_ann_push";

#define PUSH_QUEUE_DEPTH    4
#define PUSH_RETRIES        3
#define PUSH_RETRY_GAP_MS   5000
#define PUSH_HTTP_TIMEOUT_MS 5000

typedef struct {
    char ip[16];
} push_job_t;

static QueueHandle_t s_push_q;
static TaskHandle_t  s_push_task;

static bool topic_is_safe(const char *topic)
{
    if (!topic) return false;
    size_t n = strlen(topic);
    if (n < 16) return false;
    if (strncasecmp(topic, "CHANGE-ME-", 10) == 0) return false;
    if (strncasecmp(topic, "fan-testkit-CHANGE", 18) == 0) return false;
    return true;
}

static int do_push_once(const ip_announcer_settings_t *s, const char *ip,
                        char *err_out, size_t err_out_size)
{
    char url[160];
    snprintf(url, sizeof(url), "https://%s/%s", s->server, s->topic);

    char body[160];
    int body_n = snprintf(body, sizeof(body),
                          "IP: %s\nhttp://%s/\n", ip, ip);

    char click[64];
    snprintf(click, sizeof(click), "http://%s/", ip);

    char prio_s[2] = { (char)('0' + s->priority), '\0' };

    esp_http_client_config_t cfg = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = PUSH_HTTP_TIMEOUT_MS,
        .crt_bundle_attach = esp_crt_bundle_attach,
    };
    esp_http_client_handle_t cli = esp_http_client_init(&cfg);
    if (!cli) {
        snprintf(err_out, err_out_size, "esp_http_client_init failed");
        return -1;
    }

    esp_http_client_set_header(cli, "Title",    "Fan-TestKit online");
    esp_http_client_set_header(cli, "Tags",     "green_circle");
    esp_http_client_set_header(cli, "Priority", prio_s);
    esp_http_client_set_header(cli, "Click",    click);
    esp_http_client_set_post_field(cli, body, body_n);

    esp_err_t e = esp_http_client_perform(cli);
    int http_code = -1;
    if (e == ESP_OK) {
        http_code = esp_http_client_get_status_code(cli);
        if (http_code < 200 || http_code >= 300) {
            snprintf(err_out, err_out_size, "HTTP %d", http_code);
        } else {
            err_out[0] = '\0';
        }
    } else {
        snprintf(err_out, err_out_size, "%s", esp_err_to_name(e));
    }
    esp_http_client_cleanup(cli);
    return http_code;
}

static void push_task(void *arg)
{
    (void)arg;
    push_job_t job;
    while (true) {
        if (xQueueReceive(s_push_q, &job, portMAX_DELAY) != pdTRUE) continue;

        ip_announcer_settings_t s;
        ip_announcer_priv_get_settings(&s);

        ip_announcer_telemetry_t t = {0};
        t.last_attempt_ms = esp_timer_get_time() / 1000;
        snprintf(t.last_pushed_ip, sizeof(t.last_pushed_ip), "%s", job.ip);

        if (!s.enable) {
            t.status = IP_ANN_STATUS_DISABLED;
            snprintf(t.last_err, sizeof(t.last_err), "%s", "announcer disabled");
            ip_announcer_priv_set_telemetry(&t);
            continue;
        }
        if (!topic_is_safe(s.topic)) {
            t.status = IP_ANN_STATUS_FAILED;
            snprintf(t.last_err, sizeof(t.last_err), "%s",
                     "topic looks like a placeholder; change it before enabling push");
            ip_announcer_priv_set_telemetry(&t);
            ESP_LOGW(TAG, "refusing push: %s", t.last_err);
            continue;
        }

        int http_code = -1;
        for (int attempt = 0; attempt < PUSH_RETRIES; attempt++) {
            http_code = do_push_once(&s, job.ip, t.last_err, sizeof(t.last_err));
            t.last_http_code = http_code;
            if (http_code >= 200 && http_code < 300) {
                t.status = IP_ANN_STATUS_OK;
                t.last_err[0] = '\0';
                ESP_LOGI(TAG, "push ok: %s -> ntfy %s/%s (HTTP %d)",
                         job.ip, s.server, s.topic, http_code);
                break;
            }
            // 4xx → no retry, save resources.
            if (http_code >= 400 && http_code < 500) {
                t.status = IP_ANN_STATUS_FAILED;
                ESP_LOGW(TAG, "push 4xx no-retry: %s", t.last_err);
                break;
            }
            ESP_LOGW(TAG, "push attempt %d failed: %s",
                     attempt + 1, t.last_err);
            if (attempt < PUSH_RETRIES - 1) {
                vTaskDelay(pdMS_TO_TICKS(PUSH_RETRY_GAP_MS));
            }
        }
        if (t.status != IP_ANN_STATUS_OK) {
            t.status = IP_ANN_STATUS_FAILED;
            ESP_LOGW(TAG, "push final failure: %s", t.last_err);
        }
        ip_announcer_priv_set_telemetry(&t);
    }
}

esp_err_t ip_announcer_push_init(void)
{
    s_push_q = xQueueCreate(PUSH_QUEUE_DEPTH, sizeof(push_job_t));
    if (!s_push_q) return ESP_ERR_NO_MEM;
    BaseType_t ok = xTaskCreate(push_task, "ip_ann_push", 6144, NULL, 2,
                                &s_push_task);
    return ok == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}

esp_err_t ip_announcer_priv_enqueue_push(const char *ip)
{
    if (!ip || !s_push_q) return ESP_ERR_INVALID_STATE;
    push_job_t job;
    snprintf(job.ip, sizeof(job.ip), "%s", ip);
    return xQueueSend(s_push_q, &job, 0) == pdTRUE ? ESP_OK : ESP_ERR_TIMEOUT;
}
```

- [ ] **Step 4: Update `ip_announcer.c` — start push task in init, expose `priv` helpers, wire `test_push`**

Add includes near the top (alongside existing includes):

```c
#include "ip_announcer_priv.h"
#include "esp_netif.h"
```

At the **end** of `ip_announcer_init()` (just before the final `return ESP_OK;`), add:

```c
    e = ip_announcer_push_init();
    if (e != ESP_OK) {
        ESP_LOGE(TAG, "push init failed: %s", esp_err_to_name(e));
        return e;
    }
```

Replace the stub `ip_announcer_test_push` with:

```c
esp_err_t ip_announcer_test_push(void)
{
    esp_netif_t *sta = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (!sta) return ESP_ERR_INVALID_STATE;
    esp_netif_ip_info_t info = {0};
    if (esp_netif_get_ip_info(sta, &info) != ESP_OK) return ESP_ERR_INVALID_STATE;
    if (info.ip.addr == 0) return ESP_ERR_INVALID_STATE;
    char ip[16];
    snprintf(ip, sizeof(ip), IPSTR, IP2STR(&info.ip));
    return ip_announcer_priv_enqueue_push(ip);
}
```

Add the priv helpers at the end of the file:

```c
void ip_announcer_priv_get_settings(ip_announcer_settings_t *out)
{
    if (!out) return;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    *out = s_settings;
    xSemaphoreGive(s_lock);
}

void ip_announcer_priv_set_telemetry(const ip_announcer_telemetry_t *t)
{
    if (!t) return;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_telemetry = *t;
    // Persist last_ip on success so dedupe survives reboot.
    if (t->status == IP_ANN_STATUS_OK && t->last_pushed_ip[0]) {
        nvs_handle_t h;
        if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) == ESP_OK) {
            nvs_set_str(h, NVS_KEY_LAST_IP, t->last_pushed_ip);
            nvs_commit(h);
            nvs_close(h);
        }
    }
    xSemaphoreGive(s_lock);
}
```

- [ ] **Step 5: Build**

```bash
idf.py build
```

Expected: clean. The binary grows by ~80 KB (HTTP client + crt_bundle).

- [ ] **Step 6: Flash + manual smoke test**

Pre-conditions: register a topic on the ntfy.sh Android app (e.g. install ntfy from Play Store, tap "+", subscribe to your auto-generated `fan-testkit-...` topic).

Plug board, flash, and on the **fan-testkit** REPL run a temporary test from monitor:

```bash
idf.py -p COM24 flash monitor
```

The board is up, but `enable=0` so no automatic push happens yet. We need to flip enable + trigger a test. Phase 2 doesn't have CLI yet (Phase 4); for this smoke test, use a temporary CLI command. **Skip if you don't want a throwaway CLI** — the next phases will exercise it.

Alternative smoke test (no CLI needed): edit `ip_announcer_init` temporarily to do `s_settings.enable = true;` after the NVS load, **and** add `ip_announcer_test_push();` at the very end of `ip_announcer_init`. Build, flash, watch the monitor for:

```text
I (xxx) ip_ann_push: push ok: 192.168.x.y -> ntfy ntfy.sh/fan-testkit-... (HTTP 200)
```

And the ntfy app receives the notification with title `Fan-TestKit online`, body `IP: 192.168.x.y / http://192.168.x.y/`, and a tappable click target.

**Revert the temporary edits** before continuing.

- [ ] **Step 7: Commit**

```bash
git add components/ip_announcer/
git commit -m "feat(ip_announcer): HTTPS push worker with retry + safety guard

Phase 2. Adds a dedicated FreeRTOS push task (priority 2, stack 6 KB)
draining a 4-deep queue. Push uses esp_http_client + esp_crt_bundle
(Mozilla bundle covers *.ntfy.sh). Retries 3× with 5 s gap on 5xx /
network errors; 4xx is no-retry. Topic safety guard refuses pushes
on placeholder topics (CHANGE-ME-* or len < 16).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — IP event hook + dedupe

### Task 3.1: Hook IP_EVENT_STA_GOT_IP and dedupe by last_ip

**Files:**
- Modify: `components/ip_announcer/ip_announcer.c`

- [ ] **Step 1: Register the IP event handler in `ip_announcer_init`**

Add the event handler at the end of `ip_announcer_init` (after `ip_announcer_push_init()`):

```c
    extern void ip_announcer_on_ip_event(void *arg, esp_event_base_t base,
                                         int32_t id, void *data);
    esp_err_t reg_e = esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                 ip_announcer_on_ip_event, NULL);
    if (reg_e == ESP_ERR_INVALID_STATE) {
        // Default loop already created by provisioning. Some IDF versions
        // surface this; ignore — handler still registers via the existing loop.
        ESP_LOGD(TAG, "esp_event_handler_register: default loop already exists");
    } else if (reg_e != ESP_OK) {
        ESP_LOGE(TAG, "event handler register failed: %s",
                 esp_err_to_name(reg_e));
        return reg_e;
    }
```

Add the missing include at the top of `ip_announcer.c`:

```c
#include "esp_event.h"
#include "esp_netif_ip_addr.h"
```

- [ ] **Step 2: Implement the event handler in `ip_announcer.c`**

Add this function above `ip_announcer_init`:

```c
void ip_announcer_on_ip_event(void *arg, esp_event_base_t base,
                              int32_t id, void *data)
{
    (void)arg;
    if (base != IP_EVENT || id != IP_EVENT_STA_GOT_IP) return;

    ip_event_got_ip_t *evt = (ip_event_got_ip_t *)data;
    char ip[16];
    snprintf(ip, sizeof(ip), IPSTR, IP2STR(&evt->ip_info.ip));

    xSemaphoreTake(s_lock, portMAX_DELAY);
    bool enable = s_settings.enable;
    bool same   = (strcmp(ip, s_telemetry.last_pushed_ip) == 0)
                  && (s_telemetry.status == IP_ANN_STATUS_OK);
    xSemaphoreGive(s_lock);

    if (!enable) {
        ESP_LOGI(TAG, "IP %s — push disabled", ip);
        return;
    }
    if (same) {
        ESP_LOGI(TAG, "IP %s — already pushed; skipping (dedupe)", ip);
        return;
    }
    ESP_LOGI(TAG, "IP %s — enqueueing push", ip);
    esp_err_t e = ip_announcer_priv_enqueue_push(ip);
    if (e != ESP_OK) {
        ESP_LOGW(TAG, "enqueue failed: %s", esp_err_to_name(e));
    }
}
```

- [ ] **Step 3: Build**

```bash
idf.py build
```

Expected: clean.

- [ ] **Step 4: Manual integration test**

1. Erase NVS to ensure topic regenerates and `enable=0`:

```bash
idf.py -p COM24 erase-flash
idf.py -p COM24 flash monitor
```

2. Wait for provisioning, complete it via the captive portal. Expected log after WIFI_STA gets IP:

```text
I (xxx) prov: got ip: 192.168.x.y
I (xxx) ip_announcer: IP 192.168.x.y — push disabled
```

(No notification arrives because `enable=0` — that's correct.)

3. Use `nvs_set` from `idf.py monitor` debug shell, OR temporarily edit `ip_announcer_init` to force `s_settings.enable = true` again, rebuild, flash. Expected:

```text
I (xxx) ip_announcer: IP 192.168.x.y — enqueueing push
I (xxx) ip_ann_push: push ok: 192.168.x.y -> ntfy ntfy.sh/fan-testkit-... (HTTP 200)
```

4. Reboot without changing IP. Expected dedupe:

```text
I (xxx) ip_announcer: IP 192.168.x.y — already pushed; skipping (dedupe)
```

(The `last_ip` was persisted to NVS in Phase 2 task 2.1 step 4.)

5. Reconnect to a different SSID (or change router subnet) so DHCP issues a different IP. Expected: a new push fires.

6. Revert any temporary `s_settings.enable = true` edit.

- [ ] **Step 5: Commit**

```bash
git add components/ip_announcer/ip_announcer.c
git commit -m "feat(ip_announcer): hook IP_EVENT_STA_GOT_IP with last-IP dedupe

Phase 3. Registers IP_EVENT_STA_GOT_IP handler and routes new IPs
through the push queue. Skips push when enable=0 or when the new
IP matches the last successfully-pushed IP (DHCP renew case). The
last_ip is persisted in NVS (Phase 2) so dedupe survives reboot.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Transports + dashboard panel

### Task 4.1: Wire-protocol header constants + control_task command kinds

**Files:**
- Modify: `components/usb_composite/include/usb_protocol.h`
- Modify: `components/app_api/include/app_api.h`

- [ ] **Step 1: Add HID + CDC ops to `usb_protocol.h`**

Append to `components/usb_composite/include/usb_protocol.h` just before the trailing `#ifdef __cplusplus` block:

```c
// ---- IP Announcer (HID) ----------------------------------------------------

#define USB_HID_REPORT_ANNOUNCER       0x07   // OUT, 8 B (op + payload)

#define USB_HID_ANN_OP_ENABLE_TOGGLE   0x01   // payload byte 1: 0|1
#define USB_HID_ANN_OP_TEST_PUSH       0x02   // no payload

typedef struct __attribute__((packed)) {
    uint8_t  op;          // 0x01 enable, 0x02 test
    uint8_t  enable;      // valid only for 0x01
    uint8_t  pad[6];
} usb_hid_announcer_t;

_Static_assert(sizeof(usb_hid_announcer_t) == 8,
               "usb_hid_announcer_t must match HID report 0x07 size");

// ---- IP Announcer (CDC SLIP) ------------------------------------------------

#define USB_CDC_OP_ANNOUNCER_SET       0x60   // H→D u8 enable, u8 priority,
                                              //     str topic\0 str server\0
#define USB_CDC_OP_ANNOUNCER_TEST      0x61   // H→D empty
#define USB_CDC_OP_ANNOUNCER_TELEMETRY 0x62   // D→H 5 Hz status mirror
#define USB_CDC_OP_ANNOUNCER_RESULT    0x63   // D→H push final outcome event
```

- [ ] **Step 2: Add 3 ctrl_cmd kinds to `app_api.h`**

Edit `components/app_api/include/app_api.h`:

In the `ctrl_cmd_kind_t` enum, add (right after `CTRL_CMD_PSU_SET_SLAVE`):

```c
    CTRL_CMD_ANNOUNCER_SET,
    CTRL_CMD_ANNOUNCER_TEST,
    CTRL_CMD_ANNOUNCER_ENABLE,
```

In the union inside `ctrl_cmd_t`, add the three new payload variants:

```c
        struct { uint8_t enable; }                    announcer_enable;
        struct {
            uint8_t enable;
            uint8_t priority;
            char    topic[65];
            char    server[97];
        }                                              announcer_set;
```

`CTRL_CMD_ANNOUNCER_TEST` carries no payload.

- [ ] **Step 3: Build (header-only check)**

```bash
idf.py build
```

Expected: clean. New constants compile.

- [ ] **Step 4: Commit**

```bash
git add components/usb_composite/include/usb_protocol.h components/app_api/include/app_api.h
git commit -m "feat(announcer): wire-protocol constants + ctrl_cmd kinds

Adds HID report 0x07 (announcer) with op codes 0x01 enable / 0x02
test, and CDC ops 0x60..0x63. control_task gains 3 new command
kinds matching the announcer surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4.2: control_task handles announcer commands

**Files:**
- Modify: `main/control_task.c`

- [ ] **Step 1: Add the three case branches**

Edit `main/control_task.c`. Add the include at the top (alongside other component includes):

```c
#include "ip_announcer.h"
```

Add three new case statements inside the switch in `control_task` (insert before the closing `}` of the switch, after the existing `CTRL_CMD_PSU_SET_SLAVE` case):

```c
        case CTRL_CMD_ANNOUNCER_SET: {
            ip_announcer_settings_t s = {
                .enable   = (cmd.announcer_set.enable != 0),
                .priority = cmd.announcer_set.priority,
            };
            strncpy(s.topic,  cmd.announcer_set.topic,  sizeof(s.topic) - 1);
            s.topic[sizeof(s.topic) - 1] = '\0';
            strncpy(s.server, cmd.announcer_set.server, sizeof(s.server) - 1);
            s.server[sizeof(s.server) - 1] = '\0';
            esp_err_t e = ip_announcer_set_settings(&s);
            if (e != ESP_OK) {
                ESP_LOGW(TAG, "announcer_set failed: %s", esp_err_to_name(e));
            }
        } break;
        case CTRL_CMD_ANNOUNCER_TEST: {
            esp_err_t e = ip_announcer_test_push();
            if (e != ESP_OK) {
                ESP_LOGW(TAG, "announcer_test failed: %s", esp_err_to_name(e));
            }
        } break;
        case CTRL_CMD_ANNOUNCER_ENABLE: {
            esp_err_t e = ip_announcer_set_enable(cmd.announcer_enable.enable != 0);
            if (e != ESP_OK) {
                ESP_LOGW(TAG, "announcer_enable failed: %s", esp_err_to_name(e));
            }
        } break;
```

- [ ] **Step 2: Add `ip_announcer` to main's REQUIRES if not already**

Open `main/CMakeLists.txt`. Confirm `ip_announcer` is in the REQUIRES (added in Phase 1). If missing, add it.

- [ ] **Step 3: Build**

```bash
idf.py build
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add main/control_task.c main/CMakeLists.txt
git commit -m "feat(announcer): control_task dispatches announcer cmds

Three new case branches for CTRL_CMD_ANNOUNCER_SET / TEST / ENABLE,
landing on ip_announcer_set_settings / test_push / set_enable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4.3: WebSocket handlers + status frame extension

**Files:**
- Modify: `components/net_dashboard/CMakeLists.txt` — add `ip_announcer` REQUIRES
- Modify: `components/net_dashboard/ws_handler.c`

- [ ] **Step 1: Add `ip_announcer` to net_dashboard REQUIRES**

Edit `components/net_dashboard/CMakeLists.txt`. Find the existing `REQUIRES` clause and add `ip_announcer`.

- [ ] **Step 2: Add the include at the top of `ws_handler.c`**

```c
#include "ip_announcer.h"
```

- [ ] **Step 3: Add `set_announcer` and `test_announcer` to `handle_json`**

Insert two new `else if` branches in `handle_json` (after the existing `set_psu_family` branch and before `reboot`):

```c
    } else if (strcmp(type_j->valuestring, "set_announcer") == 0) {
        const cJSON *en = cJSON_GetObjectItem(root, "enable");
        const cJSON *tp = cJSON_GetObjectItem(root, "topic");
        const cJSON *sv = cJSON_GetObjectItem(root, "server");
        const cJSON *pr = cJSON_GetObjectItem(root, "priority");
        if (!cJSON_IsString(tp) || !cJSON_IsString(sv) || !cJSON_IsNumber(pr)) {
            ws_send_json_to(fd, "{\"type\":\"ack\",\"op\":\"set_announcer\",\"ok\":false}");
            return;
        }
        ctrl_cmd_t c = {
            .kind = CTRL_CMD_ANNOUNCER_SET,
            .announcer_set = {
                .enable   = cJSON_IsBool(en) ? (cJSON_IsTrue(en) ? 1 : 0)
                                              : (en && cJSON_IsNumber(en)
                                                 && en->valuedouble != 0 ? 1 : 0),
                .priority = (uint8_t)pr->valuedouble,
            },
        };
        strncpy(c.announcer_set.topic, tp->valuestring,
                sizeof(c.announcer_set.topic) - 1);
        c.announcer_set.topic[sizeof(c.announcer_set.topic) - 1] = '\0';
        strncpy(c.announcer_set.server, sv->valuestring,
                sizeof(c.announcer_set.server) - 1);
        c.announcer_set.server[sizeof(c.announcer_set.server) - 1] = '\0';
        control_task_post(&c, 0);
        ws_send_json_to(fd, "{\"type\":\"ack\",\"op\":\"set_announcer\",\"ok\":true}");
    } else if (strcmp(type_j->valuestring, "test_announcer") == 0) {
        ctrl_cmd_t c = { .kind = CTRL_CMD_ANNOUNCER_TEST };
        control_task_post(&c, 0);
        ws_send_json_to(fd, "{\"type\":\"ack\",\"op\":\"test_announcer\",\"ok\":true}");
```

- [ ] **Step 4: Add the `announcer` block to the 20 Hz status frame**

In `telemetry_task` (in the same file), find the section that appends the `ui` block. Add an `announcer` block right after the `ui` block (still inside the if-`n < sizeof(payload)` chain, before the closing `}`):

```c
        // After existing ",ui:{...}" block, before the closing "}"...
        ip_announcer_settings_t  ann_s;
        ip_announcer_telemetry_t ann_t;
        ip_announcer_get_settings(&ann_s);
        ip_announcer_get_telemetry(&ann_t);
        static const char *status_str[] = { "never", "ok", "failed", "disabled" };
        if (n < (int)sizeof(payload)) {
            n += snprintf(payload + n, sizeof(payload) - n,
                ",\"announcer\":{\"enable\":%s,\"topic\":\"%s\",\"server\":\"%s\","
                "\"priority\":%u,\"status\":\"%s\","
                "\"last_pushed_ip\":\"%s\",\"last_http_code\":%d,\"last_err\":\"%s\"}",
                ann_s.enable ? "true" : "false",
                ann_s.topic,
                ann_s.server,
                (unsigned)ann_s.priority,
                status_str[ann_t.status],
                ann_t.last_pushed_ip,
                ann_t.last_http_code,
                ann_t.last_err);
        }
```

Make sure this is **inserted before** the line `n += snprintf(payload + n, sizeof(payload) - n, "}");` that closes the outer object.

- [ ] **Step 5: Build**

```bash
idf.py build
```

Expected: clean.

- [ ] **Step 6: Smoke test via existing dashboard**

Flash, open the dashboard, open browser DevTools → Network → WS. Inspect the 20 Hz status frame. Expected to find the new `announcer` block with placeholder defaults (`enable:false`, `status:"never"`, etc.).

- [ ] **Step 7: Commit**

```bash
git add components/net_dashboard/CMakeLists.txt components/net_dashboard/ws_handler.c
git commit -m "feat(announcer): WebSocket set_announcer/test_announcer + status block

Browser-side surface for the announcer. Status frame now carries the
announcer block at 20 Hz so the panel UI updates the same way other
panels do.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4.4: USB HID handle report 0x07

**Files:**
- Modify: `components/usb_composite/usb_descriptors.c`
- Modify: `components/usb_composite/usb_composite.c`
- Modify: `components/usb_composite/usb_hid_task.c`

- [ ] **Step 1: Add the 0x07 report to the HID descriptor**

Edit `components/usb_composite/usb_descriptors.c`.

In the `enum { REPORT_ID_SET_PWM = 0x01, ... };` list, add `REPORT_ID_ANNOUNCER = 0x07,` after `REPORT_ID_SETTINGS_SAVE = 0x06`.

In the `usb_hid_report_descriptor[]` array, insert this block right after the `// 0x06 OUT settings_save: 8 bytes` entry (and before the `0x10 IN status` entry):

```c
    // 0x07 OUT announcer: 8 bytes
    0x85, REPORT_ID_ANNOUNCER,
    0x09, 0x08,
    0x75, 0x08, 0x95, 8,
    0x91, 0x02,
```

Update the `_Static_assert` at the bottom from `93` to `103`:

```c
_Static_assert(sizeof(usb_hid_report_descriptor) == 103,
               "HID_REPORT_DESC_SIZE in usb_composite.c must match this size");
```

- [ ] **Step 2: Bump `HID_REPORT_DESC_SIZE` in `usb_composite.c`**

Edit `components/usb_composite/usb_composite.c:49`:

```c
#define HID_REPORT_DESC_SIZE 103  // usb_descriptors.c:usb_hid_report_descriptor 實際大小。
                                  // 若 report descriptor 修改必須同步 (usb_descriptors.c 的
                                  // _Static_assert 會把兩者綁住，漂移會 compile-fail)。
```

- [ ] **Step 3: Handle report 0x07 in `usb_hid_task.c`**

Edit `components/usb_composite/usb_hid_task.c`. Find the function that dispatches inbound HID reports based on `report_id` (it's a switch or chain of `if (report_id == ...)`). Add the include at the top:

```c
#include "ip_announcer.h"
```

Add a new case alongside the existing 0x06 (settings_save) handler:

```c
        case USB_HID_REPORT_ANNOUNCER: {
            const usb_hid_announcer_t *p = (const usb_hid_announcer_t *)payload;
            if (p->op == USB_HID_ANN_OP_ENABLE_TOGGLE) {
                ctrl_cmd_t c = {
                    .kind = CTRL_CMD_ANNOUNCER_ENABLE,
                    .announcer_enable = { .enable = (p->enable != 0) ? 1 : 0 },
                };
                control_task_post(&c, 0);
            } else if (p->op == USB_HID_ANN_OP_TEST_PUSH) {
                ctrl_cmd_t c = { .kind = CTRL_CMD_ANNOUNCER_TEST };
                control_task_post(&c, 0);
            }
        } break;
```

(Adjust the case-statement boilerplate to match what is already there. If the dispatch is `if/else if`, write `else if (report_id == USB_HID_REPORT_ANNOUNCER) { ... }` with the same body.)

- [ ] **Step 4: Build**

```bash
idf.py build
```

Expected: clean. The descriptor `_Static_assert` doubles as a hardcoded check that descriptor size is 103 bytes.

- [ ] **Step 5: USB enumeration smoke test**

Flash. On a host machine, replug USB2 (with USB-OTG jumper bridged) and confirm:

- The composite device still enumerates (HID + CDC).
- `lsusb -v` (Linux/Mac) or USBView (Windows) shows the HID report descriptor at 103 bytes.
- Existing PC host tool (PWM, RPM, GPIO, PSU) still works — confirm no regression.

- [ ] **Step 6: Commit**

```bash
git add components/usb_composite/
git commit -m "feat(announcer): HID report 0x07 (enable + test)

HID descriptor grows 93 -> 103 bytes for the new announcer report.
Two op codes: 0x01 toggle enable, 0x02 trigger test push. Topic /
server / priority deliberately not in HID payload — those are long
strings owned by dashboard / CLI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4.5: USB CDC SLIP ops

**Files:**
- Modify: `components/usb_composite/usb_cdc_task.c`

- [ ] **Step 1: Add include**

```c
#include "ip_announcer.h"
```

- [ ] **Step 2: Handle 0x60 / 0x61 in the inbound SLIP-frame dispatch**

Find the section that switches/branches on `op` for inbound CDC frames. Add:

```c
        case USB_CDC_OP_ANNOUNCER_SET: {
            // payload: u8 enable, u8 priority, str topic\0 str server\0
            if (payload_len < 4) break;
            const uint8_t *p = payload;
            uint8_t en  = p[0];
            uint8_t pri = p[1];
            const char *topic  = (const char *)(p + 2);
            size_t topic_n = strnlen(topic, payload_len - 2);
            if (topic_n + 2 + 1 >= payload_len) break;
            const char *server = topic + topic_n + 1;

            ctrl_cmd_t c = {
                .kind = CTRL_CMD_ANNOUNCER_SET,
                .announcer_set = { .enable = en, .priority = pri },
            };
            strncpy(c.announcer_set.topic, topic,
                    sizeof(c.announcer_set.topic) - 1);
            c.announcer_set.topic[sizeof(c.announcer_set.topic) - 1] = '\0';
            strncpy(c.announcer_set.server, server,
                    sizeof(c.announcer_set.server) - 1);
            c.announcer_set.server[sizeof(c.announcer_set.server) - 1] = '\0';
            control_task_post(&c, 0);
        } break;
        case USB_CDC_OP_ANNOUNCER_TEST: {
            ctrl_cmd_t c = { .kind = CTRL_CMD_ANNOUNCER_TEST };
            control_task_post(&c, 0);
        } break;
```

- [ ] **Step 3: Emit 0x62 (telemetry mirror at 5 Hz)**

Find the existing 5 Hz CDC telemetry tick (already used by `USB_CDC_OP_PSU_TELEMETRY = 0x44`). Add an `announcer` snapshot emission alongside it:

```c
    // Inside the 5 Hz CDC telemetry tick (where PSU 0x44 is emitted):
    {
        ip_announcer_settings_t  ann_s;
        ip_announcer_telemetry_t ann_t;
        ip_announcer_get_settings(&ann_s);
        ip_announcer_get_telemetry(&ann_t);

        uint8_t buf[256];
        size_t n = 0;
        buf[n++] = USB_CDC_OP_ANNOUNCER_TELEMETRY;
        buf[n++] = ann_s.enable ? 1 : 0;
        buf[n++] = ann_s.priority;
        buf[n++] = (uint8_t)ann_t.status;
        // u16 last_http_code (LE)
        buf[n++] = (uint8_t)(ann_t.last_http_code & 0xff);
        buf[n++] = (uint8_t)((ann_t.last_http_code >> 8) & 0xff);
        // C-strings: last_pushed_ip, topic, server, last_err
        size_t l = strlen(ann_t.last_pushed_ip) + 1;
        if (n + l > sizeof(buf)) goto skip_announcer_tx;
        memcpy(buf + n, ann_t.last_pushed_ip, l); n += l;

        l = strlen(ann_s.topic) + 1;
        if (n + l > sizeof(buf)) goto skip_announcer_tx;
        memcpy(buf + n, ann_s.topic, l); n += l;

        l = strlen(ann_s.server) + 1;
        if (n + l > sizeof(buf)) goto skip_announcer_tx;
        memcpy(buf + n, ann_s.server, l); n += l;

        l = strlen(ann_t.last_err) + 1;
        if (n + l > sizeof(buf)) goto skip_announcer_tx;
        memcpy(buf + n, ann_t.last_err, l); n += l;

        cdc_slip_send(buf, n);  // existing helper used by other 0x44 emit
        skip_announcer_tx: ;
    }
```

(Adjust `cdc_slip_send` to whatever helper this file uses to send a SLIP-framed payload — match the calling convention of the existing PSU 0x44 emission. If the helper has a different name, use that.)

- [ ] **Step 4: Build**

```bash
idf.py build
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add components/usb_composite/usb_cdc_task.c
git commit -m "feat(announcer): CDC SLIP ops 0x60/0x61 + 5 Hz telemetry mirror 0x62

Host-tool surface for the announcer over CDC. Inbound 0x60 carries
enable+priority+topic+server (NUL-delimited strings); 0x61 fires a
test push. Outbound 0x62 mirrors the announcer block at 5 Hz next
to the existing PSU 0x44 emit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4.6: CLI commands

**Files:**
- Modify: `main/app_main.c`

- [ ] **Step 1: Add the include**

Already present from Phase 4.2. Verify `#include "ip_announcer.h"` is at the top.

- [ ] **Step 2: Define the four CLI command handlers**

Insert near the other `cmd_*` handlers (e.g. after `cmd_psu_family`):

```c
// ---- CLI: announcer_set <topic> [server] [priority] ------------------------
static struct {
    struct arg_str *topic;
    struct arg_str *server;
    struct arg_int *priority;
    struct arg_end *end;
} s_ann_set_args;

static int cmd_announcer_set(int argc, char **argv)
{
    int n = arg_parse(argc, argv, (void **)&s_ann_set_args);
    if (n != 0) { arg_print_errors(stderr, s_ann_set_args.end, argv[0]); return 1; }
    ip_announcer_settings_t cur;
    ip_announcer_get_settings(&cur);
    ctrl_cmd_t c = {
        .kind = CTRL_CMD_ANNOUNCER_SET,
        .announcer_set = {
            .enable   = cur.enable ? 1 : 0,
            .priority = (s_ann_set_args.priority->count > 0)
                        ? (uint8_t)s_ann_set_args.priority->ival[0]
                        : cur.priority,
        },
    };
    strncpy(c.announcer_set.topic, s_ann_set_args.topic->sval[0],
            sizeof(c.announcer_set.topic) - 1);
    c.announcer_set.topic[sizeof(c.announcer_set.topic) - 1] = '\0';
    const char *srv = (s_ann_set_args.server->count > 0)
                      ? s_ann_set_args.server->sval[0]
                      : cur.server;
    strncpy(c.announcer_set.server, srv,
            sizeof(c.announcer_set.server) - 1);
    c.announcer_set.server[sizeof(c.announcer_set.server) - 1] = '\0';
    return control_task_post(&c, pdMS_TO_TICKS(100)) == ESP_OK ? 0 : 1;
}

// ---- CLI: announcer_enable <0|1> -------------------------------------------
static struct {
    struct arg_int *en;
    struct arg_end *end;
} s_ann_enable_args;

static int cmd_announcer_enable(int argc, char **argv)
{
    int n = arg_parse(argc, argv, (void **)&s_ann_enable_args);
    if (n != 0) { arg_print_errors(stderr, s_ann_enable_args.end, argv[0]); return 1; }
    ctrl_cmd_t c = {
        .kind = CTRL_CMD_ANNOUNCER_ENABLE,
        .announcer_enable = { .enable = (s_ann_enable_args.en->ival[0] ? 1 : 0) },
    };
    return control_task_post(&c, pdMS_TO_TICKS(100)) == ESP_OK ? 0 : 1;
}

// ---- CLI: announcer_test ---------------------------------------------------
static int cmd_announcer_test(int argc, char **argv)
{
    (void)argc; (void)argv;
    ctrl_cmd_t c = { .kind = CTRL_CMD_ANNOUNCER_TEST };
    return control_task_post(&c, pdMS_TO_TICKS(100)) == ESP_OK ? 0 : 1;
}

// ---- CLI: announcer_status -------------------------------------------------
static int cmd_announcer_status(int argc, char **argv)
{
    (void)argc; (void)argv;
    ip_announcer_settings_t  s;
    ip_announcer_telemetry_t t;
    ip_announcer_get_settings(&s);
    ip_announcer_get_telemetry(&t);
    static const char *status_str[] = { "never", "ok", "failed", "disabled" };
    printf("announcer  enable=%d  topic=%s  server=%s  priority=%u\n",
           s.enable, s.topic, s.server, (unsigned)s.priority);
    printf("           last_status=%s  last_ip=%s  http=%d  err=\"%s\"\n",
           status_str[t.status], t.last_pushed_ip, t.last_http_code, t.last_err);
    return 0;
}
```

- [ ] **Step 3: Register the four commands inside `register_commands`**

After the existing PSU command registrations:

```c
    s_ann_set_args.topic    = arg_str1(NULL, NULL, "<topic>",     "ntfy topic name (8..64 chars)");
    s_ann_set_args.server   = arg_str0(NULL, NULL, "[server]",    "hostname only, default ntfy.sh");
    s_ann_set_args.priority = arg_int0(NULL, NULL, "[priority]",  "1..5, default 3");
    s_ann_set_args.end      = arg_end(3);
    const esp_console_cmd_t ann_set_cmd = {
        .command = "announcer_set",
        .help    = "set ntfy topic / server / priority",
        .hint    = NULL,
        .func    = cmd_announcer_set,
        .argtable = &s_ann_set_args,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&ann_set_cmd));

    s_ann_enable_args.en  = arg_int1(NULL, NULL, "<en>", "1 = enabled, 0 = disabled");
    s_ann_enable_args.end = arg_end(1);
    const esp_console_cmd_t ann_en_cmd = {
        .command = "announcer_enable",
        .help    = "enable / disable IP push notifications",
        .hint    = NULL,
        .func    = cmd_announcer_enable,
        .argtable = &s_ann_enable_args,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&ann_en_cmd));

    const esp_console_cmd_t ann_test_cmd = {
        .command = "announcer_test",
        .help    = "trigger an immediate test push",
        .hint    = NULL,
        .func    = cmd_announcer_test,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&ann_test_cmd));

    const esp_console_cmd_t ann_status_cmd = {
        .command = "announcer_status",
        .help    = "print announcer state + last push result",
        .hint    = NULL,
        .func    = cmd_announcer_status,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&ann_status_cmd));
```

- [ ] **Step 4: Build + flash + manual test**

```bash
idf.py build
idf.py -p COM24 flash monitor
```

In the monitor REPL:

```
fan-testkit> announcer_status
announcer  enable=0  topic=fan-testkit-...  server=ntfy.sh  priority=3
           last_status=never  last_ip=  http=0  err=""

fan-testkit> announcer_enable 1
fan-testkit> announcer_test
```

Expected: ntfy app receives a notification; subsequent `announcer_status` shows `last_status=ok`, `last_ip=192.168.x.y`, `http=200`.

- [ ] **Step 5: Commit**

```bash
git add main/app_main.c
git commit -m "feat(announcer): CLI announcer_set/enable/test/status

Four new commands for the announcer surface. announcer_set takes
optional [server] and [priority] args defaulting to current values,
so simple usage stays one-arg ('announcer_set my-topic-name').

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4.7: Dashboard panel + i18n + status binding

**Files:**
- Modify: `components/net_dashboard/web/index.html`
- Modify: `components/net_dashboard/web/app.js`

- [ ] **Step 1: Add the Settings panel HTML**

Edit `components/net_dashboard/web/index.html`. Find the existing Step Sizes panel (search for `id="ui-steps"` or similar). Insert this new panel **after** the Step Sizes panel and before the Help footer:

```html
<section class="card" id="announcer">
  <h2 data-i18n="announcer_h">IP Announcer (ntfy.sh)</h2>

  <div id="announcer-banner" class="banner banner-error" hidden>
    <span data-i18n="announcer_banner_placeholder">
      Topic looks like a placeholder — change it before enabling push.
    </span>
  </div>

  <label>
    <input type="checkbox" id="announcer-enable" />
    <span data-i18n="announcer_enable">Enable IP push notifications</span>
  </label>

  <div class="row">
    <label data-i18n="announcer_topic">Topic:</label>
    <input type="text" id="announcer-topic" maxlength="64" />
    <button type="button" id="announcer-randomize" data-i18n="announcer_random">🎲 Random</button>
  </div>

  <div class="row">
    <label data-i18n="announcer_server">Server:</label>
    <input type="text" id="announcer-server" maxlength="96" value="ntfy.sh" />
  </div>

  <div class="row">
    <label data-i18n="announcer_priority">Priority:</label>
    <select id="announcer-priority">
      <option value="1">1 — Min</option>
      <option value="2">2 — Low</option>
      <option value="3" selected>3 — Default</option>
      <option value="4">4 — High</option>
      <option value="5">5 — Max</option>
    </select>
  </div>

  <p class="status" id="announcer-status" data-i18n="announcer_status_never">
    Never pushed.
  </p>

  <div class="row">
    <button type="button" id="announcer-test" data-i18n="announcer_test">Send test now</button>
    <button type="button" id="announcer-save" data-i18n="announcer_save">Save</button>
  </div>

  <p class="hint">
    <span data-i18n="announcer_subscribe_h">📲 Subscribe on phone:</span>
    <a id="announcer-deeplink" href="#" data-i18n="announcer_open_in_app">Open in ntfy app</a>
  </p>
</section>
```

- [ ] **Step 2: Add i18n strings to `app.js`**

Edit `components/net_dashboard/web/app.js`. Find the existing translation tables (`en`, `zh-tw`, `zh-cn`). Add these keys to each:

```js
// Add to the en table:
announcer_h: 'IP Announcer (ntfy.sh)',
announcer_enable: 'Enable IP push notifications',
announcer_topic: 'Topic:',
announcer_server: 'Server:',
announcer_priority: 'Priority:',
announcer_test: 'Send test now',
announcer_save: 'Save',
announcer_random: '🎲 Random',
announcer_status_never: 'Never pushed.',
announcer_status_ok: 'Pushed {ip} ({age})',
announcer_status_failed: 'Failed: {err}',
announcer_status_disabled: 'Disabled.',
announcer_subscribe_h: '📲 Subscribe on phone:',
announcer_open_in_app: 'Open in ntfy app',
announcer_banner_placeholder: 'Topic looks like a placeholder — change it before enabling push.',
announcer_help_h: 'IP Announcer (ntfy.sh push notifications)',
announcer_help_p: 'When enabled, the device pushes its IP to ntfy.sh on every Wi-Fi connection. Install the ntfy app on your phone, subscribe to your topic, and tap the notification to open the dashboard. The topic name acts as a password — anyone with it can read your IP. Use a long, random topic.',
```

```js
// Add to the zh-tw table:
announcer_h: 'IP 通知 (ntfy.sh)',
announcer_enable: '啟用 IP 推播',
announcer_topic: 'Topic:',
announcer_server: '伺服器:',
announcer_priority: '優先順序:',
announcer_test: '立即測試',
announcer_save: '儲存',
announcer_random: '🎲 隨機',
announcer_status_never: '尚未推送過。',
announcer_status_ok: '已推送 {ip} ({age})',
announcer_status_failed: '失敗：{err}',
announcer_status_disabled: '已停用。',
announcer_subscribe_h: '📲 在手機上訂閱：',
announcer_open_in_app: '在 ntfy app 開啟',
announcer_banner_placeholder: 'Topic 看起來像 placeholder — 啟用推播前請先修改。',
announcer_help_h: 'IP 通知 (ntfy.sh 推播)',
announcer_help_p: '啟用後，每次 Wi-Fi 連線會把 IP 推送到 ntfy.sh。手機裝 ntfy app、訂閱你的 topic、點通知就能直接開 dashboard。Topic 等同密碼 — 任何知道它的人都能看到你推送的 IP，請用夠長夠隨機的字串。',
```

```js
// Add to the zh-cn table:
announcer_h: 'IP 通知 (ntfy.sh)',
announcer_enable: '启用 IP 推送',
announcer_topic: 'Topic:',
announcer_server: '服务器:',
announcer_priority: '优先级:',
announcer_test: '立即测试',
announcer_save: '保存',
announcer_random: '🎲 随机',
announcer_status_never: '尚未推送过。',
announcer_status_ok: '已推送 {ip} ({age})',
announcer_status_failed: '失败：{err}',
announcer_status_disabled: '已停用。',
announcer_subscribe_h: '📲 在手机上订阅：',
announcer_open_in_app: '在 ntfy app 打开',
announcer_banner_placeholder: 'Topic 看起来像占位符 — 启用推送前请先修改。',
announcer_help_h: 'IP 通知 (ntfy.sh 推送)',
announcer_help_p: '启用后，每次 Wi-Fi 连接会把 IP 推送到 ntfy.sh。手机装 ntfy app、订阅你的 topic、点通知就能直接打开 dashboard。Topic 等同密码 — 任何知道它的人都能看到你推送的 IP，请用够长够随机的字符串。',
```

- [ ] **Step 3: Wire panel JS — Save / Test / Random / status binding**

In `app.js`, locate the existing WebSocket message handler (search for the `case 'status':` arm or similar). Inside it, after the existing `setFromDevice` calls, add:

```js
// announcer block from status frame
if (msg.announcer) {
  applyAnnouncerStatus(msg.announcer);
}
```

Define `applyAnnouncerStatus` near the other `setFromDevice`-style helpers:

```js
function announcerTopicLooksSafe(topic) {
  if (!topic) return false;
  if (topic.length < 16) return false;
  const lower = topic.toLowerCase();
  if (lower.startsWith('change-me-')) return false;
  if (lower.startsWith('fan-testkit-change')) return false;
  return true;
}

function applyAnnouncerStatus(a) {
  // Only repopulate inputs when the user is NOT actively editing them.
  const topicInput = document.getElementById('announcer-topic');
  const serverInput = document.getElementById('announcer-server');
  const priorityInput = document.getElementById('announcer-priority');
  const enableInput = document.getElementById('announcer-enable');
  if (document.activeElement !== topicInput) topicInput.value = a.topic || '';
  if (document.activeElement !== serverInput) serverInput.value = a.server || 'ntfy.sh';
  if (document.activeElement !== priorityInput) priorityInput.value = String(a.priority || 3);
  enableInput.checked = !!a.enable;

  const banner = document.getElementById('announcer-banner');
  banner.hidden = announcerTopicLooksSafe(a.topic);

  const statusEl = document.getElementById('announcer-status');
  const t = window.__I18N || {};
  if (a.status === 'ok') {
    statusEl.textContent = (t.announcer_status_ok || 'Pushed {ip}')
      .replace('{ip}', a.last_pushed_ip || '?')
      .replace('{age}', '');
    statusEl.style.color = 'green';
  } else if (a.status === 'failed') {
    statusEl.textContent = (t.announcer_status_failed || 'Failed: {err}')
      .replace('{err}', a.last_err || '?');
    statusEl.style.color = 'red';
  } else if (a.status === 'disabled') {
    statusEl.textContent = t.announcer_status_disabled || 'Disabled.';
    statusEl.style.color = '';
  } else {
    statusEl.textContent = t.announcer_status_never || 'Never pushed.';
    statusEl.style.color = '';
  }

  const dl = document.getElementById('announcer-deeplink');
  const topic = encodeURIComponent(a.topic || '');
  const server = encodeURIComponent(a.server || 'ntfy.sh');
  dl.href = `ntfy://${a.server || 'ntfy.sh'}/${a.topic || ''}?subscribe=1`;

  // Disable Test button when topic is unsafe.
  document.getElementById('announcer-test').disabled =
    !announcerTopicLooksSafe(a.topic);
}
```

In the DOM-ready / panel-init section, wire the buttons:

```js
document.getElementById('announcer-randomize').addEventListener('click', () => {
  const alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  let tok = '';
  const arr = new Uint32Array(32);
  crypto.getRandomValues(arr);
  for (let i = 0; i < 32; i++) tok += alphabet[arr[i] % alphabet.length];
  document.getElementById('announcer-topic').value = `fan-testkit-${tok}`;
});

document.getElementById('announcer-save').addEventListener('click', () => {
  ws.send(JSON.stringify({
    type: 'set_announcer',
    enable: document.getElementById('announcer-enable').checked,
    topic: document.getElementById('announcer-topic').value.trim(),
    server: document.getElementById('announcer-server').value.trim() || 'ntfy.sh',
    priority: parseInt(document.getElementById('announcer-priority').value, 10) || 3,
  }));
});

document.getElementById('announcer-test').addEventListener('click', () => {
  ws.send(JSON.stringify({ type: 'test_announcer' }));
});
```

(`ws` here is whatever WebSocket variable name `app.js` already uses for the dashboard connection.)

- [ ] **Step 4: Add basic CSS for the new banner if not already present**

Edit `components/net_dashboard/web/app.css`. If `.banner-error` is not defined, add:

```css
.banner {
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  margin-bottom: 0.75rem;
}
.banner-error {
  background: #fde7e7;
  color: #a02020;
  border: 1px solid #f3b2b2;
}
```

- [ ] **Step 5: Build + flash**

```bash
idf.py build
idf.py -p COM24 flash monitor
```

- [ ] **Step 6: Browser smoke test (golden path)**

Open the dashboard in Chrome / Firefox.

1. Confirm the new "IP Announcer (ntfy.sh)" panel appears.
2. Confirm topic / server / priority show device-side values pulled from the 20 Hz status frame.
3. Confirm the deeplink href is `ntfy://ntfy.sh/<topic>?subscribe=1`.
4. Click Random — topic field updates to a fresh `fan-testkit-...` string.
5. Tick Enable, click Save. Check status line updates to "Disabled" → eventually "Pushed ..." after the next IP_EVENT (or after a Test press).
6. Click Send test now — phone receives the ntfy notification within ~5 s.
7. Set topic to `CHANGE-ME-test` and Save → confirm the red banner appears, Test button becomes disabled.

- [ ] **Step 7: Commit**

```bash
git add components/net_dashboard/web/
git commit -m "feat(announcer): dashboard Settings panel + i18n + status binding

Browser-side UI for the announcer. Save / Random / Test buttons,
status line bound to 20 Hz status frame, deeplink to ntfy app for
subscription, red banner on placeholder topics, Test button auto-
disabled when topic is unsafe.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5 — Captive portal + docs

### Task 5.1: Captive-portal `/success` page renders ntfy section

**Files:**
- Modify: `components/net_dashboard/captive_portal.c`
- Modify: `components/net_dashboard/web/success.html`

- [ ] **Step 1: Add 3 new replacement tokens in `success_get`**

Edit `components/net_dashboard/captive_portal.c`. Add the include at the top:

```c
#include "ip_announcer.h"
```

In `success_get` (around line 134), replace the existing 2-token replacement table with the 5-token version:

```c
    ip_announcer_settings_t ann_s;
    ip_announcer_get_settings(&ann_s);
    char deeplink[200];
    char weblink[200];
    snprintf(deeplink, sizeof(deeplink), "ntfy://%s/%s?subscribe=1",
             ann_s.server, ann_s.topic);
    snprintf(weblink,  sizeof(weblink),  "https://%s/%s",
             ann_s.server, ann_s.topic);

    const char *repl[][2] = {
        { "{{IP}}",            ip_buf      },
        { "{{MDNS}}",          "fan-testkit.local" },
        { "{{NTFY_TOPIC}}",    ann_s.topic },
        { "{{NTFY_DEEPLINK}}", deeplink    },
        { "{{NTFY_WEBLINK}}",  weblink     },
    };
    for (size_t r = 0; r < sizeof(repl)/sizeof(repl[0]); r++) {
        const char *tok = repl[r][0];
        const char *val = repl[r][1];
        size_t tok_len = strlen(tok);
        size_t val_len = strlen(val);
        char *p;
        while ((p = strstr(rendered, tok)) != NULL) {
            size_t tail = strlen(p + tok_len);
            if ((p - rendered) + val_len + tail + 1 > sizeof(rendered)) break;
            memmove(p + val_len, p + tok_len, tail + 1);
            memcpy(p, val, val_len);
        }
    }
```

Bump the `rendered` buffer size if needed. Currently it's 2048 bytes; adding ~400 bytes of ntfy section + 3 long deeplink tokens stays comfortably within. If a build-time warning fires, raise to 3072.

- [ ] **Step 2: Add the ntfy section to `success.html`**

Edit `components/net_dashboard/web/success.html`. Find the existing IP / mDNS section. Insert this block after it:

```html
<section class="ntfy">
  <h3>📲 Get IP notifications on this phone</h3>
  <p>Install the <strong>ntfy</strong> app
     (<a href="https://play.google.com/store/apps/details?id=io.heckel.ntfy">Play Store</a>
      / <a href="https://apps.apple.com/app/ntfy/id1625396347">App Store</a>),
     then tap below to subscribe to this device's topic:</p>
  <p><a class="btn" href="{{NTFY_DEEPLINK}}">Open in ntfy app</a></p>
  <p><small>Topic: <code>{{NTFY_TOPIC}}</code><br>
     Web view: <a href="{{NTFY_WEBLINK}}">{{NTFY_WEBLINK}}</a><br>
     (Subscribe in the app, then enable IP push from the dashboard
      Settings &rarr; IP Announcer.)</small></p>
</section>
```

- [ ] **Step 3: Build + flash**

```bash
idf.py build
idf.py -p COM24 flash monitor
```

- [ ] **Step 4: Re-provisioning smoke test**

Erase NVS to force the captive portal flow:

```bash
idf.py -p COM24 erase-flash
idf.py -p COM24 flash monitor
```

On a phone, connect to `Fan-TestKit-setup` AP. Captive portal opens. Provision with valid creds. After the device gets an IP, the success page should render with:

- IP address (already worked)
- mDNS hostname (already worked)
- **New** ntfy section with topic + deeplink + weblink
- Tapping "Open in ntfy app" on the Android phone opens the ntfy app's subscribe screen with the topic prefilled (assuming ntfy app is already installed)

- [ ] **Step 5: Commit**

```bash
git add components/net_dashboard/captive_portal.c components/net_dashboard/web/success.html
git commit -m "feat(announcer): captive-portal success page shows ntfy topic + deeplink

Phase 5. Right after a fresh provisioning succeeds, the success page
now offers a one-tap subscribe link via ntfy:// deeplink so the user
can subscribe to their device's topic in the ntfy app without typing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 5.2: Help footer + README + CLAUDE.md

**Files:**
- Modify: `components/net_dashboard/web/index.html`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a Help `<details>` block for the announcer**

Edit `components/net_dashboard/web/index.html`. Find the existing Help footer (search for `<details>` blocks at the bottom of the page). Add another `<details>` entry before the closing footer:

```html
<details>
  <summary data-i18n="announcer_help_h">IP Announcer (ntfy.sh push notifications)</summary>
  <p data-i18n="announcer_help_p">
    When enabled, the device pushes its IP to ntfy.sh on every Wi-Fi
    connection. Install the ntfy app on your phone, subscribe to your
    topic, and tap the notification to open the dashboard. The topic
    name acts as a password — anyone with it can read your IP. Use a
    long, random topic.
  </p>
</details>
```

(The i18n keys `announcer_help_h` / `announcer_help_p` were added in Phase 4.7 — verify they exist in all three language tables.)

- [ ] **Step 2: Update `README.md`**

Open `README.md`. Find the existing feature list. Add a bullet describing IP Announcer:

```markdown
- **IP Announcer (ntfy.sh push)** — opt-in feature that pushes the
  device's IP to your phone via ntfy.sh after every Wi-Fi connection.
  Solves the "Android Chrome can't resolve `fan-testkit.local` on a
  phone hotspot with randomised subnet" problem. Install the ntfy
  Android / iOS app, subscribe to your auto-generated topic (shown on
  the captive-portal success page), enable from Settings → IP
  Announcer in the dashboard. Topic resolution: NVS → Kconfig
  `APP_IP_ANNOUNCER_TOPIC_DEFAULT` (set in `sdkconfig.defaults.local`
  for personal multi-board builds) → random `fan-testkit-<32 chars>`
  fallback. Topics matching `CHANGE-ME-*` or shorter than 16 chars
  are refused at runtime to prevent placeholder leaks.
```

- [ ] **Step 3: Update `CLAUDE.md`**

Open `CLAUDE.md`. Find the "NVS-persisted runtime tunables" section. Add a fourth bullet to the namespace list:

```markdown
- `ip_announcer`: keys `enable` (u8), `topic` (str), `server` (str),
  `priority` (u8), `last_ip` (str). Owned by the
  `components/ip_announcer/` component, which is also referenced by
  `net_dashboard` (status frame) and `captive_portal` (deeplink on
  /success). Topic is resolved at first boot from NVS → Kconfig
  `APP_IP_ANNOUNCER_TOPIC_DEFAULT` → random fallback, then persisted
  back to NVS so subsequent boots skip the resolution. Placeholder
  guard: topics matching `CHANGE-ME-*` / `fan-testkit-CHANGE*` or
  shorter than 16 chars are refused at push-enqueue time, with a
  red banner in the dashboard.
```

Also append a paragraph to the "Architecture — two invariants" section's first invariant, expanding the IP-announcement transport diagram:

```markdown
The same posture extends to **IP announcement**: ntfy.sh push is
fire-and-forget after every IP_EVENT_STA_GOT_IP, going through
`ip_announcer_priv_enqueue_push` from the event handler. The push
worker on a dedicated FreeRTOS task (priority 2, separate from
control_task because HTTPS retries can hold the task ~15 s) drains
the queue and updates the telemetry block atomically.
```

- [ ] **Step 4: Build + flash**

```bash
idf.py build
idf.py -p COM24 flash monitor
```

Sanity check: confirm dashboard Help footer now shows the new entry, and that all three languages render correctly when toggled.

- [ ] **Step 5: Commit**

```bash
git add components/net_dashboard/web/index.html README.md CLAUDE.md
git commit -m "docs(announcer): Help footer entry, README feature note, CLAUDE.md NVS tunables

Round out Phase 5. Help footer surfaces the privacy posture (topic
acts as a password). README explains the use case and Kconfig
override path. CLAUDE.md lists the new ip_announcer NVS namespace
and extends the single-handler invariant section with the IP
announcement transport.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Final acceptance checklist

After Phase 5 commit, run through the spec's "Manual verification before merge" list:

- [ ] **End-to-end Android Pixel hotspot test**

Setup:
- Erase NVS to force fresh provisioning.
- Build with empty `APP_IP_ANNOUNCER_TOPIC_DEFAULT` (random fallback).
- Phone has ntfy app installed.

Steps:
1. Power-cycle the board.
2. Connect phone to `Fan-TestKit-setup` SoftAP.
3. Captive portal opens; provision with the phone's hotspot creds (or any home Wi-Fi).
4. After /success renders, tap "Open in ntfy app" → subscribe.
5. In the dashboard (open via the IP shown on /success), navigate to Settings → IP Announcer, tick Enable, click Save.
6. Power-cycle the board so it reconnects via DHCP.
7. **Phone receives an ntfy notification within ~5 s of the board's `IP_EVENT_STA_GOT_IP`.**
8. Tap the notification → Chrome (or default browser) opens the dashboard.

- [ ] **Self-host smoke test**

Set `server` to a private hostname (e.g. `ntfy.example.lan`) via dashboard. Save. Click Test. Confirm the device hits the new server (you can verify via captured DNS query or Wireshark on the LAN).

- [ ] **Topic safety guard test**

Set topic to `CHANGE-ME-test` via dashboard. Confirm:
- Red banner shows.
- Test button is disabled.
- `announcer_test` from CLI returns non-zero with placeholder error.
- Even with `enable=1`, no push is sent on next IP_EVENT.

- [ ] **Rate-limit test**

Trigger `announcer_test` 6 times within 60 seconds. The 6th should return HTTP 429. Confirm `announcer_status` shows `last_status=failed`, `http=429`. Confirm device does NOT crash, does NOT retry the 429.

- [ ] **Cold-boot regression sweep**

After the announcer is enabled and the topic is set, every cold boot should result in exactly one notification on the phone (or zero if dedupe matches the previous IP).

---

## Self-Review Notes

**Spec coverage check:**
- Component layout, public API, NVS layout, first-boot resolution, Kconfig file, safety guard → Phase 1.
- HTTPS push, retry policy, error handling table → Phase 2.
- IP_EVENT hook, dedupe semantics → Phase 3.
- WS / HID / CDC / CLI surfaces, dashboard UI panel, status frame `announcer` block → Phase 4.
- Captive-portal `/success` integration, Help section, README + CLAUDE.md updates → Phase 5.
- All non-goals respected: no encryption, no live telemetry pushing, no control channel, no BLE, no fallback channel.

**Type consistency:**
- `ip_announcer_settings_t` / `ip_announcer_telemetry_t` / `ip_announcer_status_t` — defined in Task 1.1 step 3, consumed identically in 4.3, 4.4, 4.5, 4.7, 5.1.
- `CTRL_CMD_ANNOUNCER_SET / TEST / ENABLE` — defined in 4.1, dispatched in 4.2, posted from 4.3 (WS), 4.4 (HID), 4.5 (CDC), 4.6 (CLI).
- HID descriptor size 93 → 103 — bumped in `usb_descriptors.c` `_Static_assert` AND `usb_composite.c` `HID_REPORT_DESC_SIZE` macro in lockstep (Task 4.4 steps 1-2).
- `ip_announcer_priv_*` symbols — declared in `ip_announcer_priv.h` (Task 2.1 step 2), defined in `ip_announcer.c` (Task 2.1 step 4), consumed in `ip_announcer_push.c` (Task 2.1 step 3).

**No placeholders:** every step has either complete code, exact bash commands, or acceptance criteria. The one "match the helper convention" hand-wave in Task 4.5 step 3 is unavoidable until the implementer reads the file (the helper name is local to that file and not visible from the outside).
