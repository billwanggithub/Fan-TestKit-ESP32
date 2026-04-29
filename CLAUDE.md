# CLAUDE.md

ESP32-S3 firmware for the Fan-TestKit bench (PWM gen, RPM cap, USB
composite HID/CDC, Wi-Fi dashboard, multi-family PSU control). Detailed
rules are split into [.claude/rules/](.claude/rules/) — load them on
demand based on the task.

## Critical rules (non-negotiable)

- **Single handler, multiple transport frontends.** Setpoint control,
  OTA, factory reset, PSU control all have one core handler with
  WS/HID/CDC/CLI frontends that translate protocol only. Never
  duplicate business logic in a frontend. Boot defaults go through the
  same queue (`CTRL_CMD_SET_PWM` from `app_main`); don't seed atomics
  from `pwm_gen_get()`. Dashboard `app.js` has no `lastSent` cache —
  don't reintroduce one.
- **Components never `REQUIRES main`.** Shared types live in
  `components/app_api/include/app_api.h`.
- **Boot order:** `esp_event_loop_create_default()` must run before any
  component that registers on `IP_EVENT` / `WIFI_EVENT` (currently
  `ip_announcer`, `net_dashboard` provisioning). Mis-ordered init
  aborts on `ESP_ERR_INVALID_STATE`.
- **Lock-free SPSC ring buffers** (`freq_fifo`, `rpm_fifo`) — don't
  swap for `xQueue` without measuring; capture ISR runs at MHz rates.
- **Atomic float `latest_rpm`** (bit-punned `uint32_t`, relaxed) —
  don't add a mutex. RPM timeout sentinel is `period | 0x80000000`.
- **PWM duty is NOT NVS-persisted.** Boot always starts at duty=0.
  Hard safety invariant — a fan reboot under power must not restart
  at the previous duty.
- **PWM same-band updates use TEZ latching** (`update_cmp_on_tez`).
  Don't `mcpwm_timer_stop`/restart in the update path — that's where
  glitches come from.
- **PWM band-cross requires shadow-register flush.** `reconfigure_for_band`
  must software-sync timer to phase=0 right after `mcpwm_new_timer`.
  See [.claude/rules/pwm-mcpwm.md](.claude/rules/pwm-mcpwm.md) for the
  register sequence and three abandoned attempts that did NOT work.
- **HID descriptor size invariant.** `_Static_assert(sizeof(...) == N)`
  in `usb_descriptors.c` + `HID_REPORT_DESC_SIZE` macro in
  `usb_composite.c:49` — both must move together when adding reports.
- **PSU CRC has NO boot-time self-check.** Earlier `__attribute__((constructor))`
  trapped before `app_main` on every cold boot. Don't reintroduce.

## Emergency quick-fix

- **Build picks up old config?** `del sdkconfig && idf.py fullclean &&
  idf.py build`. `fullclean` keeps `sdkconfig`; `sdkconfig.defaults`
  changes are silently ignored if the symbol already exists in
  `sdkconfig`.
- **Chip stuck in `waiting for download` after flash?** CH343 DTR/RTS
  trap. Use `idf.py monitor --no-reset`, or a terminal that holds
  DTR=1+RTS=1 on open (PuTTY works), or power-cycle USB. See
  [.claude/rules/hardware-and-board.md](.claude/rules/hardware-and-board.md).
- **`encrypted-flash` fails on a new board?** Don't run it. Secure Boot
  and Flash Enc are currently `n` in `sdkconfig.defaults` (temp
  workaround); use plain `idf.py flash`.
- **TinyUSB doesn't enumerate?** Check the USB-OTG / USB-JTAG 0Ω jumper
  on the board — composite HID+CDC needs `USB-OTG`.
- **Build error `driver/uart.h: no such file`?** v6.0 split the
  `driver` umbrella. Add `esp_driver_uart` (or peripheral-specific
  REQUIRES) to the component's CMakeLists.

## Key file locations

- `components/app_api/include/app_api.h` — shared types
  (`ctrl_cmd_t`, queue handles); cross-component API headers.
- `components/usb_composite/include/usb_protocol.h` — HID report IDs
  and CDC SLIP frame ops (host-tool contract; payload changes are
  breaking).
- `components/net_dashboard/ws_handler.c` — WebSocket JSON contract
  inline.
- `components/net_dashboard/include/net_dashboard.h` —
  `net_dashboard_factory_reset()` (4-transport convergence point).
- `components/pwm_gen/pwm_gen.c` — 2-band table + `reconfigure_for_band`.
- `components/rpm_cap/rpm_cap.c` — capture ISR + timeout sentinel.
- `components/psu_driver/` — multi-family vtable (`riden`, `xy_sk120`,
  `wz5005`).
- `main/idf_component.yml` — pinned component-manager deps.
- `sdkconfig.defaults` — pinned Kconfig (target, partition table,
  Secure Boot off).
- `docs/YD-ESP32-S3-SCH-V1.4.pdf` — board schematic; consult before
  allocating GPIOs.
- `HANDOFF.md` — IDF v5.5.1 → v6.0 migration notes + Secure Boot
  re-enable bisect plan.

## Hardware quick-ref

**Board:** YD-ESP32-S3-COREBOARD V1.4 (ESP32-S3-WROOM-1, N16R8: 16 MB
flash, 8 MB octal PSRAM). Two USB-C: **USB1** = CH343P UART0 console
(always on); **USB2** = native USB on GPIO19/20, needs **USB-OTG**
jumper for TinyUSB composite.

**GPIO reservations:** 19, 20 (USB). Strapping pins to avoid for
critical outputs: 0 (BOOT), 3 (USB-JTAG select), 45, 46. WS2812 RGB on
GPIO48. PSU UART1: GPIO38 (TX) / GPIO39 (RX), 8N1, baud per family.

Full details + CH343 trap → [.claude/rules/hardware-and-board.md](.claude/rules/hardware-and-board.md).

## Build & flash (Windows)

ESP-IDF v6.0 at `C:\esp\v6.0\esp-idf`. Activate via desktop shortcut
**"ESP-IDF 6.0 PWM Project"**, the `esp6 pwm` PowerShell alias, or
`C:\esp\v6.0\esp-idf\export.ps1`.

```bash
idf.py build
idf.py -p COM24 flash monitor
```

Don't `export` the v5.5.1 install inside a v6.0 shell (Python venv
collision). Full toolchain notes, sdkconfig trap, security posture,
v6.0 driver split, component-manager pins →
[.claude/rules/build-and-toolchain.md](.claude/rules/build-and-toolchain.md).

## Task topology (FreeRTOS)

```text
priority 6  control_task         owns PWM setpoints, drains ctrl_cmd_queue
priority 5  rpm_converter_task   freq_fifo → period→RPM → rpm_fifo
priority 4  rpm_averager_task    sliding avg → atomic latest_rpm + history
priority 3  httpd                HTTP + WebSocket
priority 3  usb_hid_task         HID OUT parse; IN @ 50 Hz from latest_rpm
priority 2  usb_cdc_tx/rx        CDC log mirror + SLIP OTA frames
priority 2  telemetry_task       20 Hz WebSocket status push
priority 2  ota_writer_task      single esp_ota_* writer (mutex-guarded)
priority 4  psu_task             5 Hz UART poll, atomic V/I publish
priority 2  ip_announcer worker  fire-and-forget ntfy.sh push (HTTPS, may stall ~15 s)
```

Architectural rationale + full invariants →
[.claude/rules/architecture-deep.md](.claude/rules/architecture-deep.md).

## Reference docs

| Topic | File |
| --- | --- |
| Hardware, USB jumpers, CH343 trap | [.claude/rules/hardware-and-board.md](.claude/rules/hardware-and-board.md) |
| ESP-IDF v6.0, sdkconfig, security, deps | [.claude/rules/build-and-toolchain.md](.claude/rules/build-and-toolchain.md) |
| Single-handler invariant, task rationale | [.claude/rules/architecture-deep.md](.claude/rules/architecture-deep.md) |
| PWM 2-band, MCPWM v6.0 quirks, shadow flush | [.claude/rules/pwm-mcpwm.md](.claude/rules/pwm-mcpwm.md) |
| Factory reset, PSU multi-family, NVS keys | [.claude/rules/subsystems.md](.claude/rules/subsystems.md) |
| PSU wiring + register maps | [docs/Power_Supply_Module.md](docs/Power_Supply_Module.md) |
| Captive-portal provisioning design | [docs/superpowers/specs/2026-04-22-softap-captive-portal-design.md](docs/superpowers/specs/2026-04-22-softap-captive-portal-design.md) |
| Release-mode eFuse hardening | [docs/release-hardening.md](docs/release-hardening.md) |
| Migration notes (v5.5.1 → v6.0) | [HANDOFF.md](HANDOFF.md) |

## Communication preferences

All responses and commit-message bodies: **晶晶體** (Traditional Chinese +
English code-switching). Code, command names, and technical keywords stay
in English. Commit-message titles can be English-first for git log
readability.

Flowcharts in docs and comments use **ASCII tree format** (`├─` `└─` `│`),
not Mermaid.
