# Subsystems Reference

Detailed reference for the four major non-PWM subsystems: factory reset,
PSU driver, NVS-persisted tunables, USB descriptors. All four follow the
"single handler, multiple frontends" invariant from
[architecture-deep.md](architecture-deep.md).

## Factory reset / reprovision (4 transports, 1 core)

Every reset entry point lands on `net_dashboard_factory_reset()`
(`components/net_dashboard/include/net_dashboard.h`), which wipes
stored Wi-Fi credentials via `prov_clear_credentials()` (calls
`esp_wifi_restore()`) and calls `esp_restart()`. Next boot the device
sees no credentials → SoftAP `Fan-TestKit-setup` opens for captive-portal
provisioning.

```
Web UI confirm      ──┐
USB HID 0x03 + 0xA5 ──┤
USB CDC 0x20 + 0xA5 ──┼──► net_dashboard_factory_reset()
BOOT long-press ≥3s ──┘       ├── prov_clear_credentials()
                              └── esp_restart()
```

### Design notes

- **Magic-byte guard on USB paths** (`USB_HID_FACTORY_RESET_MAGIC =
  0xA5`, `USB_CDC_FACTORY_RESET_MAGIC = 0xA5`) so a stray zeroed
  report can't wipe credentials. Web UI uses a JS `confirm()` dialog;
  BOOT uses a 3-second hold (50 ms poll cadence in
  `boot_button_task`, GPIO0 with internal pull-up).
- **200 ms restart delay** in `factory_reset_task` lets each
  transport's ack frame (WS `{type:"ack",op:"factory_reset"}`, CDC op
  `0x21`, HID report `0x03` silent) flush before the reset interrupts
  the connection.
- **Idempotent** — second call inside the 200 ms window is a no-op
  via a static volatile flag. BOOT long-press triggers spawn exactly
  one reset even if the input glitches.
- **GPIO0 runtime reuse**: GPIO0 is a strapping pin but only sampled
  at reset for BOOT/DOWNLOAD selection. After boot it's a normal
  input that any app can read.
- **Cross-component coupling**: `usb_composite` REQUIRES
  `net_dashboard` so HID/CDC callbacks can reach the reset API.
  Direction is acceptable — `net_dashboard` is the "network state"
  component and factory reset *is* a network-state concern
  (credentials).

## HID descriptor size invariant

Each new report id grows `usb_hid_report_descriptor` (53 → 63 with `0x03`,
→ 73 with GPIO `0x04`, → 83 with PSU `0x05`, → 93 with settings-save
`0x06`). The `_Static_assert(sizeof(...) == N)` in
`usb_composite/usb_descriptors.c` and the `HID_REPORT_DESC_SIZE` macro
in `usb_composite.c:49` keep the two in sync — any future descriptor
edit triggers a compile error on mismatch.

## PSU driver — multi-family (5th controllable subsystem)

`components/psu_driver/` owns UART1 and dispatches to one of three PSU
backends at boot, picked by the NVS key `psu_driver/family` (default
from Kconfig `APP_PSU_DEFAULT_FAMILY_*`):

- **`riden`** — Riden RD60xx (Modbus-RTU, factory baud 115200, register
  map in `psu_riden.c`).
- **`xy_sk120`** — XY-SK120 (Modbus-RTU, factory baud 115200, register
  map in `psu_xy_sk120.c`).
- **`wz5005`** — WZ5005 (custom 20-byte sum-checksum protocol, factory
  baud 19200, op codes in `psu_wz5005.c`).

`APP_PSU_UART_BAUD` defaults track the family's factory baud; bench
operators with re-keyed panels override per-build via
`idf.py menuconfig` → "PSU driver". The two Modbus-RTU backends share
`psu_modbus_rtu.c` (CRC-16, FC 0x03/0x06 helpers); WZ5005 is fully
standalone. One UART mutex shared by all backends.

Switching family at runtime: dashboard PSU panel → Family dropdown →
Save → Reboot button (or `psu_family <name>` CLI + manual reboot).
The change is NVS-persisted but boot-effective (re-init UART for new
baud is risky vs simple reboot).

### Same single-handler invariant as PWM/RPM/GPIO/relay

```text
Wi-Fi WS  set_psu_voltage / current / output / slave  ──┐
USB HID 0x05 + ops 0x10..0x13                            ├──► control_task ──► psu_driver_set_*()
USB CDC ops 0x40..0x43                                   │                          │
CLI psu_v / psu_i / psu_out / psu_slave / psu_family     ──┘                          ▼
                                                                          backend vtable
                                                                          (riden / xy_sk120 / wz5005)
```

Telemetry (V_SET / I_SET / V_OUT / I_OUT / output) polled at 5 Hz,
published as atomic bit-punned floats. Surfaces in the 20 Hz WS status
frame as a `psu` block, in CDC op `0x44` at 5 Hz, and via `psu_status`
CLI.

### Slave address + family persistence

NVS-persisted in namespace `psu_driver`, keys `slave_addr` and `family`.
Setting either does **not** issue a write to the supply — the supply's
own slave address (and panel-keyed baud, per family) is set from the
front panel; firmware just matches it. Slave range is 1..255 (Modbus
families clamp to 1..247 inside the backend; WZ5005 uses the full
1..255).

### Why hand-rolled (not `esp-modbus`)

We use 2 function codes (0x03 read holding, 0x06 write single) for the
Modbus families, and a wholly different 20-byte custom frame for WZ5005.
Adding another component-manager pin alongside `esp_tinyusb` / `mdns` /
`cjson` would exceed the LoC saved.

### CRC-16 — no boot-time self-check

Poly `0xA001`, init `0xFFFF`, shift-right-after-XOR. There is
deliberately **no boot-time self-check**: an earlier
`__attribute__((constructor))` compared against `0x0944` and trapped on
mismatch, but that constant was wrong — every cold boot trapped before
`app_main` ran, putting the chip in a reset loop. CRC correctness is
verified end-to-end instead: a bad implementation produces frames the
supply rejects, every transaction times out, and `link_ok` stays false →
the dashboard immediately shows "PSU offline".

**Don't reintroduce the boot-time check** unless you have a verified
canonical CRC vector AND log output before the trap (constructors run
before `ESP_LOG` is up, so a silent trap is the only failure mode —
debug-hostile by construction). Same posture applies to WZ5005's
sum-mod-256 checksum.

### UART mutex + inter-frame gap

UART access is funnelled through a single mutex (`s_uart_mutex` in
`psu_driver.c`, exposed to backends via `psu_driver_priv_get_uart_mutex`)
so setpoint writes from `control_task` (priority 6) and the polling
loop on `psu_task` (priority 4) cannot interleave bytes on the wire.
Inter-frame gap is 2 ms for Modbus families (3.5-char @ 19200 ≈ 1.8 ms);
WZ5005 uses 3 ms.

### Link health

5 consecutive timeouts/CRC failures flips `link_ok` to false; first
success flips it back. Only state transitions log — avoids spam when
the cable is unplugged.

## NVS-persisted runtime tunables

Four namespaces hold user-tunable state that should survive reboot:

- `psu_driver`: keys `slave_addr` (u8), `family` (str). See PSU section
  above.
- `rpm_cap`: keys `pole` (u8), `mavg` (u16), `timeout_us` (u32) — set
  via `rpm_cap_save_params_to_nvs()` / `rpm_cap_save_timeout_to_nvs()`.
- `pwm_gen`: key `freq_hz` (u32) — set via
  `pwm_gen_save_current_freq_to_nvs()`. **Duty is deliberately NOT
  persisted** — boot always starts at duty=0 regardless of saved
  state. This is a hard safety invariant: a fan reboot under power
  must not silently restart at the previous duty.
- `ui_settings`: keys `duty_step` (blob: float, 4 B), `freq_step` (u16)
  — set via `ui_settings_save_steps()`. Owned by the
  `components/ui_settings/` component, which is also referenced by
  `net_dashboard` so the WS status frame can serve current step values
  to all browser clients (no per-browser localStorage; the device is
  the source of truth).
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

### Save command flow

All Save commands flow through `control_task` (CTRL_CMD_SAVE_RPM_PARAMS /
SAVE_RPM_TIMEOUT / SAVE_PWM_FREQ / SAVE_UI_STEPS) and are reachable via
all four transports:

- WebSocket: `{"type":"save_rpm_params"}`, `{"type":"save_rpm_timeout"}`,
  `{"type":"save_pwm_freq"}`, `{"type":"save_ui_steps","duty_step":...,
  "freq_step":...}`
- HID: report id `0x06` (USB_HID_REPORT_SETTINGS_SAVE) with op codes
  `0x01..0x04` covering all four settings in a single 8-byte payload.
- CDC SLIP: ops `0x50..0x53`. `save_pwm_freq`'s u32 payload is
  advisory; the device authoritatively saves its live freq via
  `pwm_gen_get` to avoid transport-level race conditions.
- CLI: `save_rpm_params`, `save_rpm_timeout`, `save_pwm_freq`,
  `save_ui_steps <duty> <freq>`.

### NVS save error handling policy

Every save fn propagates both `nvs_set_*` and `nvs_commit` errors via the
`(es == ESP_OK) ? nvs_commit(h) : ESP_OK` short-circuit. Pre-existing
`psu_driver` retains the older silent-commit pattern for now;
acknowledged tech debt.
