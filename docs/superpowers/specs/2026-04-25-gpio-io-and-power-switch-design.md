# GPIO IO + Power Switch — Design

**Date:** 2026-04-25
**Status:** Approved (brainstorming → spec → plan)
**Scope:** Add a software-controllable power-switch GPIO and 16 user-configurable
GPIO pins (two groups of 8) reachable from the Web dashboard, USB HID, USB CDC,
and the UART CLI.

---

## 1. Goal

Give the Fan-TestKit board:

1. **One power-switch GPIO output** that the dashboard can flip on/off, with
   active-high / active-low polarity selectable at build time (so it can drive
   either common-cathode FETs or low-trigger 5 V relay modules).

2. **Two groups of 8 user GPIOs** (16 total). Each pin can be flipped between
   input and output at runtime. Group A defaults to input (pull-down); Group B
   defaults to output (low). Outputs support both level toggle and a one-shot
   pulse of configurable width.

All controls are reachable through every existing transport (Web WebSocket /
USB HID / USB CDC / UART CLI), funneled through the existing `control_task`
queue — preserving the project's "single logical handler, multiple transport
frontends" invariant.

---

## 2. Pin allocation

Picked from the YD-ESP32-S3-COREBOARD V1.4 schematic
(`docs/YD-ESP32-S3-SCH-V1.4.pdf`), avoiding strapping pins, USB pins, the
WS2812 RGB LED, and PSRAM-internal pins (35–37).

```
power_switch                 GPIO21        (J2-17)

group A — input default      GPIO7         (J1-7)
                             GPIO15        (J1-8)
                             GPIO16        (J1-9)
                             GPIO17        (J1-10)
                             GPIO18        (J1-11)
                             GPIO8         (J1-12)
                             GPIO9         (J1-15)
                             GPIO10        (J1-16)

group B — output default     GPIO11        (J1-17)
                             GPIO12        (J1-18)
                             GPIO13        (J1-19)
                             GPIO14        (J1-20)
                             GPIO1         (J2-3)
                             GPIO2         (J2-4)
                             GPIO42        (J2-5)
                             GPIO41        (J2-6)
```

Rationale:
- Group A occupies a continuous segment on J1 (pins 7..16 inclusive of the
  first run), so a single IDC ribbon picks all 8 inputs at once.
- Group B occupies the second J1 run plus the first 4 free J2 pins, again
  ribbon-friendly.
- Power-switch is intentionally on J2 (separated from the 16 GPIO pins) so a
  fan-supply relay wiring run cannot brush the data GPIOs.

All allocations are exposed in `main/Kconfig.projbuild` as defaults so a
hardware revision can re-pin without code changes.

---

## 3. Architecture

### 3.1 Component layout

A new component `components/gpio_io/` owns:

- the 16-pin state table (mode + value + pulsing flag)
- the power-switch state
- the input poll task (20 Hz)
- the per-pin one-shot pulse timers (esp_timer)
- the public API the rest of the system consumes

It depends only on `app_api` (for `ctrl_cmd_t`) and the IDF `esp_driver_gpio`
component. It does **not** depend on `main`.

### 3.2 Single-handler invariant

Every transport translates its frame into a `ctrl_cmd_t`, posts it to
`ctrl_cmd_queue`, and `control_task` is the only caller of
`gpio_io_set_mode` / `gpio_io_set_level` / `gpio_io_pulse` /
`gpio_io_set_power`.

```
WS JSON   ──┐
HID OUT   ──┤
CDC SLIP  ──┼──► control_task ──► gpio_io_*  ──► hardware
CLI       ──┘                          │
                                       ▼
                            esp_timer (per-pin pulse)
                            poll_task @ 20 Hz (sample inputs)
                                       │
                                       ▼
                            atomic 16-byte state table
                                       ▲
                                       │
                            telemetry_task (existing) reads snapshot
```

### 3.3 State table

```c
typedef enum {
    GPIO_IO_MODE_INPUT_PULLDOWN = 0,
    GPIO_IO_MODE_INPUT_PULLUP,
    GPIO_IO_MODE_INPUT_FLOATING,
    GPIO_IO_MODE_OUTPUT,
} gpio_io_mode_t;
```

Per pin, packed into one `_Atomic uint8_t`:
- bits 0–1: mode (4 values)
- bit  2:   level (sampled for input, driven for output)
- bit  3:   pulsing (true while a pulse is in flight)
- bits 4–7: reserved

16 atomics + 1 `_Atomic uint8_t s_power` for the power switch. Relaxed
ordering — telemetry tolerates one-sample staleness, exactly as
`latest_rpm` does today.

The atomic packing means `gpio_io_get_all()` produces a coherent 16-byte
snapshot suitable for the WS telemetry frame without any locking.

### 3.4 Pulse implementation

One `esp_timer_handle_t` per output-eligible pin (16 timers, one-shot).

`gpio_io_pulse(idx, width_ms)`:
1. Reject if pin is currently `pulsing=true` or not in `OUTPUT` mode →
   returns `ESP_ERR_INVALID_STATE`.
2. Read current driven level `L` from state.
3. Drive the pin to `!L` (idle-inverted: idle high pulses low, idle low
   pulses high).
4. Mark `pulsing=true`.
5. `esp_timer_start_once(width_ms * 1000 µs)`.
6. Timer callback drives the pin back to `L`, clears `pulsing`.

Width range clamped to **[1 ms, 10000 ms]**; values outside the range get
clamped silently (CLI / WS will log a warn if the request was clipped).

### 3.5 Input polling

A dedicated `gpio_io_poll_task` (priority 2) runs at 20 Hz:

```c
for (int i = 0; i < 16; i++) {
    if (mode_of(i) is INPUT_*)
        update_atomic_level(i, gpio_get_level(pin_of(i)));
}
```

20 Hz matches the existing telemetry cadence; each new telemetry frame
carries a coherent input-state snapshot taken ≤ 50 ms ago. No edge
interrupts, no debounce — fan-testkit GPIO use is "static probe pin"
not "tachometer-class fast edges".

---

## 4. APIs

### 4.1 `components/gpio_io/include/gpio_io.h`

```c
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

typedef enum {
    GPIO_IO_MODE_INPUT_PULLDOWN = 0,
    GPIO_IO_MODE_INPUT_PULLUP,
    GPIO_IO_MODE_INPUT_FLOATING,
    GPIO_IO_MODE_OUTPUT,
} gpio_io_mode_t;

typedef struct {
    gpio_io_mode_t mode;
    bool           level;     // for input: last sampled; for output: driven
    bool           pulsing;   // true while a pulse is in flight
} gpio_io_state_t;

#define GPIO_IO_PIN_COUNT 16

esp_err_t gpio_io_init(void);

esp_err_t gpio_io_set_mode (uint8_t idx, gpio_io_mode_t mode);
esp_err_t gpio_io_set_level(uint8_t idx, bool level);
esp_err_t gpio_io_pulse    (uint8_t idx, uint32_t width_ms);
void      gpio_io_get_state(uint8_t idx, gpio_io_state_t *out);
void      gpio_io_get_all  (gpio_io_state_t out[GPIO_IO_PIN_COUNT]);

esp_err_t gpio_io_set_power(bool on);
bool      gpio_io_get_power(void);

uint32_t  gpio_io_get_pulse_width_ms(void);
esp_err_t gpio_io_set_pulse_width_ms(uint32_t width_ms);   // also persists to NVS
```

### 4.2 `app_api.h` extensions

```c
typedef enum {
    /* existing */
    CTRL_CMD_SET_PWM,
    CTRL_CMD_SET_RPM_PARAMS,
    CTRL_CMD_SET_RPM_TIMEOUT,
    CTRL_CMD_OTA_BEGIN,
    CTRL_CMD_OTA_CHUNK,
    CTRL_CMD_OTA_END,
    /* new */
    CTRL_CMD_GPIO_SET_MODE,    // {idx, mode}
    CTRL_CMD_GPIO_SET_LEVEL,   // {idx, level}
    CTRL_CMD_GPIO_PULSE,       // {idx, width_ms}
    CTRL_CMD_POWER_SET,        // {on}
    CTRL_CMD_PULSE_WIDTH_SET,  // {width_ms}
} ctrl_cmd_kind_t;

typedef struct {
    ctrl_cmd_kind_t kind;
    union {
        struct { uint32_t freq_hz; float duty_pct; }    set_pwm;
        struct { uint8_t  pole; uint16_t mavg; }        set_rpm_params;
        struct { uint32_t timeout_us; }                 set_rpm_timeout;
        struct { uint8_t  idx; uint8_t mode; }          gpio_set_mode;
        struct { uint8_t  idx; uint8_t level; }         gpio_set_level;
        struct { uint8_t  idx; uint32_t width_ms; }     gpio_pulse;
        struct { uint8_t  on; }                         power_set;
        struct { uint32_t width_ms; }                   pulse_width_set;
    };
} ctrl_cmd_t;
```

### 4.3 control_task switch additions

```c
case CTRL_CMD_GPIO_SET_MODE:    gpio_io_set_mode (cmd.gpio_set_mode.idx,
                                                  cmd.gpio_set_mode.mode); break;
case CTRL_CMD_GPIO_SET_LEVEL:   gpio_io_set_level(cmd.gpio_set_level.idx,
                                                  cmd.gpio_set_level.level); break;
case CTRL_CMD_GPIO_PULSE:       gpio_io_pulse    (cmd.gpio_pulse.idx,
                                                  cmd.gpio_pulse.width_ms); break;
case CTRL_CMD_POWER_SET:        gpio_io_set_power(cmd.power_set.on);   break;
case CTRL_CMD_PULSE_WIDTH_SET:  gpio_io_set_pulse_width_ms(
                                          cmd.pulse_width_set.width_ms); break;
```

### 4.4 Boot via queue

`app_main` posts the boot defaults through the queue, mirroring the existing
PWM boot-default pattern:

```c
ctrl_cmd_t boot_pwr   = { .kind = CTRL_CMD_POWER_SET,       .power_set = {.on = 0} };
control_task_post(&boot_pwr,  pdMS_TO_TICKS(100));
```

(GPIO mode defaults are applied inside `gpio_io_init()` itself — there are
16 pins each with a Kconfig-set mode, queueing 16 boot commands is noise.
The power-switch path is queued because there is exactly one and it preserves
the single-path-from-boot invariant for the user-visible toggle.)

---

## 5. Web dashboard

### 5.1 New panels

Two new panels inserted between the existing **Frequency** panel and the
existing **OTA** panel.

#### 5.1.1 Power panel

```
┌──────────────────────────────────────────────────┐
│ Power Switch                            [ ⏻ OFF ]│
└──────────────────────────────────────────────────┘
```

Big toggle, red background when ON. Single click → `set_power`. UI shows the
echoed-back state from telemetry (no client-side cache).

#### 5.1.2 GPIO panel

```
┌──────────────────────────────────────────────────┐
│ GPIO                                             │
│                                                  │
│  Group A (J1-7..J1-16)                           │
│  ┌──────────────────────────────────────────┐    │
│  │ A1 GPIO7   [IN ▾ pulldown ] value: 0     │    │
│  │ A2 GPIO15  [IN ▾ pulldown ] value: 0     │    │
│  │ A3 GPIO16  [IN ▾ pulldown ] value: 0     │    │
│  │ A4 GPIO17  [IN ▾ pulldown ] value: 1     │    │
│  │ A5 GPIO18  [IN ▾ pulldown ] value: 0     │    │
│  │ A6 GPIO8   [IN ▾ pulldown ] value: 0     │    │
│  │ A7 GPIO9   [IN ▾ pulldown ] value: 0     │    │
│  │ A8 GPIO10  [OUT▾]    [tog 0] [Pulse]     │    │ ← user changed to OUT
│  └──────────────────────────────────────────┘    │
│                                                  │
│  Group B (J1-17..J2-6)                           │
│  ┌──────────────────────────────────────────┐    │
│  │ B1 GPIO11  [OUT▾]    [tog 0] [Pulse]     │    │
│  │ B2 GPIO12  [OUT▾]    [tog 1] [Pulse]     │    │
│  │ ...                                      │    │
│  │ B8 GPIO41  [OUT▾]    [tog 0] [Pulsing…]  │    │ ← greyed during pulse
│  └──────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

Per row:
- Pin label `A1..A8` / `B1..B8` (fixed, doesn't change with mode)
- Static GPIO number readout (pulled from `device_info` JSON, same pattern as
  the Help panel's pin readouts)
- Mode `<select>` with 4 options (`input + pull-down`, `input + pull-up`,
  `input floating`, `output`)
- Tail (mode-dependent):
  - input → `value: 0|1`
  - output → toggle `<input type="checkbox" role="switch">` plus a `Pulse`
    button
- Pulse-in-progress: row's toggle and Pulse button get `disabled`, label shows
  `Pulsing…` for the duration of `pulse_width_ms`.

### 5.2 Settings-panel addition

A third section in the existing Settings `<details>`:

```
┌──────────────────────────────────────────────────┐
│ Settings                                         │
│   ▸ RPM (existing)                               │
│   ▸ Step sizes (existing)                        │
│   ▾ GPIO output                                  │
│       Pulse width [100] ms      [Apply]          │
└──────────────────────────────────────────────────┘
```

Range 1–10000 ms; out-of-range values rejected with an inline warning before
sending the WS message.

### 5.3 i18n

Every new label gets `data-i18n="..."` keys following the existing pattern.
Translation strings added to `app.js`'s i18n table for `en` / `zh-Hant` /
`zh-Hans`.

### 5.4 No client-side cache

Following the existing CLAUDE.md invariant ("Dashboard mirrors the same
invariant ... no `lastSent` cache"), GPIO panels read their current value from
DOM state at commit time and rely on the next telemetry frame to confirm.
Pulse-in-progress UI lockout uses the `pulsing` flag straight from telemetry.

---

## 6. WebSocket protocol

### 6.1 Client → device

```json
{"type":"set_gpio_mode",   "idx":3,  "mode":"input_pulldown"}
{"type":"set_gpio_mode",   "idx":3,  "mode":"input_pullup"}
{"type":"set_gpio_mode",   "idx":3,  "mode":"input_floating"}
{"type":"set_gpio_mode",   "idx":3,  "mode":"output"}
{"type":"set_gpio_level",  "idx":11, "level":1}
{"type":"pulse_gpio",      "idx":11}                       // omitted width_ms → frontend substitutes the current global pulse_width_ms before posting CTRL_CMD_GPIO_PULSE
{"type":"pulse_gpio",      "idx":11, "width_ms":250}       // explicit override for this pulse only
{"type":"set_power",       "on":true}
{"type":"set_pulse_width", "width_ms":250}
```

`idx` is `0..15` (Group A = 0..7, Group B = 8..15).

### 6.2 Device → client (status frame)

The existing `{type:"status", freq, duty, rpm, ts}` frame gains three fields:

```json
{
  "type":"status",
  "freq":1000, "duty":50.0, "rpm":3200.5, "ts":12345,
  "power": 0,
  "pulse_width_ms": 100,
  "gpio":[
    {"m":"i_pd","v":0,"p":0},  /* index 0 = A1 */
    {"m":"i_pd","v":0,"p":0},
    ...
    {"m":"o","v":0,"p":1}      /* index 15 = B8 (pulsing) */
  ]
}
```

Mode short codes: `i_pd`, `i_pu`, `i_fl`, `o`. With 16 entries and short
codes, the gpio array is < 350 bytes — at 20 Hz that's ~7 KB/s, negligible
on Wi-Fi.

### 6.3 ack / error

Single-shot replies on each command, same pattern as the existing
`factory_reset` ack:

```json
{"type":"ack", "op":"set_gpio_mode",  "idx":3}
{"type":"err", "op":"pulse_gpio",     "idx":11, "msg":"already pulsing"}
```

---

## 7. USB protocols

### 7.1 HID

A new HID OUT report id `0x04` carries GPIO/power ops with a 4-byte
data payload. The HID report descriptor grows by ~10 bytes (one new
report-id collection: usage-page, usage, report-count, report-size,
logical min/max, input/output marker). The exact post-edit byte count
will be measured against `sizeof(usb_hid_report_descriptor)` and the
`_Static_assert(sizeof(usb_hid_report_descriptor) == N)` updated in
both `usb_composite/usb_descriptors.c` and the `HID_REPORT_DESC_SIZE`
macro in `usb_composite.c:49` (same lockstep pattern as the 0x03
factory-reset descriptor edit). The compile error on mismatch is the
guard against drift.

```
Report ID 0x04 OUT, 4 data bytes:
  byte 0: op
    0x01 = set mode    bytes [1]=idx (0..15), [2]=mode (0..3)
    0x02 = set level   bytes [1]=idx,         [2]=level (0|1)
    0x03 = pulse       bytes [1]=idx,         [2]=width_lo, [3]=width_hi
    0x04 = power       bytes [1]=on (0|1)
```

HID IN status frame (50 Hz, RPM-only) is **unchanged** — GPIO state is large
enough that pushing it via HID IN would force a descriptor renegotiation and
add latency for no benefit. Hosts that need GPIO state read it through CDC
or WebSocket.

### 7.2 CDC SLIP

New op codes added to `usb_protocol.h`:

```c
#define USB_CDC_OP_GPIO_SET_MODE     0x30   /* payload: idx, mode             */
#define USB_CDC_OP_GPIO_SET_LEVEL    0x31   /* payload: idx, level            */
#define USB_CDC_OP_GPIO_PULSE        0x32   /* payload: idx, width_lo, width_hi */
#define USB_CDC_OP_POWER             0x33   /* payload: on                    */
#define USB_CDC_OP_PULSE_WIDTH_SET   0x34   /* payload: width_lo, width_hi    */
```

The existing `0x10` status query response payload gains a 17-byte tail:

```
[ existing status bytes ]
[ 16 × packed gpio state byte ]   /* same layout as the atomic state */
[ 1  × power byte ]
```

Old hosts that parse only the existing prefix continue working as long as
they read by length, not greedily. Hosts that want GPIO state add a
length-aware parser branch.

Magic-byte guards are not needed for these ops — they manipulate
test-bench GPIOs, not safety-critical state like factory-reset.

---

## 8. CLI

Four new commands in `app_main.c`, registered through the existing
`esp_console_cmd_register` pattern:

```
gpio_mode  <idx 0..15> <mode>     # mode = i_pd | i_pu | i_fl | o
gpio_set   <idx 0..15> <0|1>      # output level
gpio_pulse <idx 0..15> [width_ms] # uses global width if width_ms omitted
power      <0|1>                  # power switch on/off
```

The existing `status` command grows two extra lines:

```
power on/off
gpio  A1=i_pd:0 A2=i_pd:0 ... B8=o:0 (pulse_width=100ms)
```

---

## 9. Persistence (NVS)

Namespace `"gpio_io"` (separate from `net_dashboard`'s wifi-cred namespace).

| key             | type    | persisted |
|-----------------|---------|-----------|
| pulse_width_ms  | u32     | yes       |
| (nothing else)  |         |           |

Explicitly **not persisted**:

- power-switch state — boots OFF every time. Safety: a previously-ON value
  could energise an unexpectedly-attached load on the next power cycle.
- per-pin mode and level — boot back to Kconfig defaults. The dashboard
  shows them immediately on connect, user re-applies if they want a
  different layout.

---

## 10. Kconfig

In `main/Kconfig.projbuild`, under the existing `Fan-TestKit App` menu:

```
config APP_POWER_SWITCH_GPIO
    int "Power-switch GPIO"
    default 21

config APP_POWER_SWITCH_ACTIVE_LOW
    bool "Power-switch is active-low (low-trigger relay module)"
    default y

config APP_GPIO_GROUP_A_PIN_0   int "Group A pin 0 GPIO"   default 7
config APP_GPIO_GROUP_A_PIN_1   int "Group A pin 1 GPIO"   default 15
config APP_GPIO_GROUP_A_PIN_2   int "Group A pin 2 GPIO"   default 16
config APP_GPIO_GROUP_A_PIN_3   int "Group A pin 3 GPIO"   default 17
config APP_GPIO_GROUP_A_PIN_4   int "Group A pin 4 GPIO"   default 18
config APP_GPIO_GROUP_A_PIN_5   int "Group A pin 5 GPIO"   default 8
config APP_GPIO_GROUP_A_PIN_6   int "Group A pin 6 GPIO"   default 9
config APP_GPIO_GROUP_A_PIN_7   int "Group A pin 7 GPIO"   default 10

config APP_GPIO_GROUP_B_PIN_0   int "Group B pin 0 GPIO"   default 11
config APP_GPIO_GROUP_B_PIN_1   int "Group B pin 1 GPIO"   default 12
config APP_GPIO_GROUP_B_PIN_2   int "Group B pin 2 GPIO"   default 13
config APP_GPIO_GROUP_B_PIN_3   int "Group B pin 3 GPIO"   default 14
config APP_GPIO_GROUP_B_PIN_4   int "Group B pin 4 GPIO"   default 1
config APP_GPIO_GROUP_B_PIN_5   int "Group B pin 5 GPIO"   default 2
config APP_GPIO_GROUP_B_PIN_6   int "Group B pin 6 GPIO"   default 42
config APP_GPIO_GROUP_B_PIN_7   int "Group B pin 7 GPIO"   default 41

config APP_DEFAULT_PULSE_WIDTH_MS
    int "Default GPIO pulse width (ms) on first boot before NVS is set"
    default 100
```

Defaults are summarised in `gpio_io_init()`:
- Group A boots `INPUT_PULLDOWN`
- Group B boots `OUTPUT` driving 0
- Power switch boots OFF (taking active-low into account)

---

## 11. Component dependencies

```
components/gpio_io/CMakeLists.txt:
    REQUIRES app_api esp_driver_gpio esp_timer nvs_flash

main/CMakeLists.txt → REQUIRES gains gpio_io
components/usb_composite/CMakeLists.txt → no change (already REQUIRES app_api)
components/net_dashboard/CMakeLists.txt → no change (REQUIRES app_api already)
```

`gpio_io` is **upstream** of every transport — it does not REQUIRE any
transport component. Direction is identical to `pwm_gen`'s position in the
graph.

---

## 12. Testing

### 12.1 Unit / smoke

1. **Build clean** — `del sdkconfig && idf.py fullclean && idf.py build`
   (CLAUDE.md sdkconfig trap — Kconfig defaults won't take effect otherwise).
2. **CLI smoke** on USB1 console:
   ```
   gpio_mode 0 o          # change A1 to output
   gpio_set 0 1           # drive A1 high
   ```
   Verify GPIO7 reads 3.3 V on a multimeter.
3. **Pulse timing** — `gpio_pulse 8 100` with toggle=0 → scope GPIO11, expect
   100 ms ± 2 ms high pulse.
4. **Power switch** — `power 1`, multimeter on GPIO21, expect 0 V (because
   `APP_POWER_SWITCH_ACTIVE_LOW=y` by default → ON drives low).
5. **Active-high path** — flip `APP_POWER_SWITCH_ACTIVE_LOW=n`, rebuild,
   `power 1` → 3.3 V.

### 12.2 Web smoke

6. Open dashboard, verify GPIO panel shows 16 rows, Group A all `IN
   pulldown value:0`, Group B all `OUT toggle 0`.
7. Toggle B1 in dashboard → multimeter on GPIO11 → 3.3 V.
8. Click Pulse on B1 with idle=0 → scope shows 100 ms high pulse, row
   greys out for 100 ms with `Pulsing…` label.
9. Wire jumper from a known 3.3 V to GPIO7 → A1 row should show
   `value: 1` within ≤ 50 ms.
10. Settings → GPIO output → change pulse width to 250 ms → click Pulse
    on B2 → scope confirms 250 ms.
11. Power-switch big toggle → multimeter on GPIO21 reflects the polarity
    set in Kconfig.

### 12.3 USB smoke

12. PC tool sends HID report id `0x04`, op `0x02`, idx 8, level 1 → B1
    drives high. Status query (CDC `0x10`) returns the 17-byte GPIO tail
    showing B1 mode=output, level=1.
13. CDC `0x33` op with payload `0x01` → power switch ON.

### 12.4 Regression

14. PWM still works at 1 kHz / 50 % (visual scope on GPIO4).
15. RPM panel still reads jumper-tach signal.
16. Factory-reset still completes (WS button + 3 s BOOT hold).
17. OTA still flashes a new image and reboots.

### 12.5 NVS persistence

18. Change pulse width to 250 ms → `esp_restart` → reconnect dashboard,
    Settings should still show 250 ms.
19. Toggle power ON → `esp_restart` → power should be **OFF** on reboot
    (intentional non-persistence).

### 12.6 Edge cases

20. `gpio_pulse 99` → CLI error, no crash.
21. Send `set_gpio_level` to a pin currently in input mode → no-op,
    `{type:"err",op:"set_gpio_level","msg":"not output mode"}` reply.
22. Send `pulse_gpio` to an already-pulsing pin → `{type:"err"}` reply
    with `"already pulsing"`.
23. Mode change on a pulsing pin → mode-change rejected with
    `{type:"err",msg:"pulsing in progress"}`.

---

## 13. Risks

- **GPIO1 / GPIO2** are JTAG TDO/TDI on some chip variants; they are *not*
  on this chip's USB-JTAG path (USB-JTAG uses GPIO19/20). They're free and
  used elsewhere in YD-ESP32-S3 example projects without issue, but if a
  future debug session needs JTAG over GPIO1/2 those are the first pins
  to reassign.

- **Group B boots driving low**. Any external device wired to a Group B pin
  during board boot will see a 0 V immediately. Documented in the help panel
  so users hooking up sensitive logic don't get surprised.

- **Active-low power switch boot**. With `APP_POWER_SWITCH_ACTIVE_LOW=y`, OFF
  means the GPIO drives high (3.3 V). For a brief moment between reset and
  `gpio_io_init()`, the pin floats — a pull-down on the board / FET input is
  recommended. Documented in `docs/first-time-setup.md`.

- **Pulse stalls**. If `esp_timer_start_once` ever fails (out of timers /
  memory), `gpio_io_pulse` must restore the pin to its idle level and
  clear `pulsing` synchronously **before** returning the error. The pin
  is never left mid-pulse on the failure path; the caller sees an
  `ESP_ERR_*` return code and the next telemetry frame shows
  `pulsing=false`.

---

## 14. Out of scope

- Edge-triggered input notifications (e.g. push-on-change) — current 20 Hz
  polling is enough for fan-testkit's "static jumper / probe" use.
- Per-pin alias names / labels persisted to NVS — Group A/B numeric IDs
  plus the GPIO number from device_info are sufficient.
- I²C / SPI / one-wire over the same pins — outside the GPIO IO scope.
- Per-pin pull configuration on output mode — output drives are by
  definition not pulled; pull config only applies in input modes.

---

## 15. Open questions

None — all design questions answered during brainstorming
(2026-04-25 session).
