# Architecture — Deep Reference

## Invariant 1: Single logical handler, multiple transport frontends

Both **setpoint control** and **firmware update** have exactly one
implementation with two transport frontends:

```
Wi-Fi WebSocket ──┐                             ┌── /ota POST ──┐
                  ├──► control_task (setpoints) │                ├──► ota_writer_task
USB HID reports ──┘                             └── CDC frames ──┘     (esp_ota_*)
```

Frontends translate protocol only. Core logic is written once. A third
transport (e.g. Ethernet) should plug in as a new frontend feeding the same
`ctrl_cmd_queue` / `ota_core_*` APIs — never duplicate the business logic.

### Boot defaults go through the queue too

`app_main` posts `CTRL_CMD_SET_PWM(10000, 0)` after `control_task_start()`
so the boot default takes the same `pwm_gen_set → publish_pwm` path every
later command uses. Hardware, the published atomics in control_task, and
downstream consumers (telemetry @ 20 Hz, HID status frames) all reflect
the same value from boot.

**Don't seed the atomics directly from `pwm_gen_get()`** — that bypasses
the single path and lets the hardware drift from the published state.
Symptom if violated: the dashboard's first telemetry frame carries
`freq=0`, the JS picks it up, and a duty-only commit before any freq
change ships `{freq:0, duty:X}` → `pwm_gen_set` rejects with
`ESP_ERR_INVALID_ARG`.

### Dashboard mirrors the same invariant

`app.js` has no `lastSent` cache for freq/duty — each panel's `onCommit`
reads the *other* axis from that panel's `getValue()` at commit time, and
`setFromDevice` keeps `panel.current` locked to telemetry. **Don't
reintroduce a parallel cache** ("just to avoid one extra read") — it
WILL desync.

### IP announcement also single-path

ntfy.sh push is fire-and-forget after every IP_EVENT_STA_GOT_IP, going
through `ip_announcer_priv_enqueue_push` from the event handler. The
push worker on a dedicated FreeRTOS task (priority 2, separate from
control_task because HTTPS retries can hold the task ~15 s) drains the
queue and updates the telemetry block atomically.

### Boot-order constraint for IP_EVENT / WIFI_EVENT registrants

Any component that registers on `IP_EVENT` / `WIFI_EVENT` (currently
`ip_announcer`, `net_dashboard`'s `provisioning`) must run *after*
`esp_event_loop_create_default()`. We do this once in `app_main`
(right before `ip_announcer_init()`), not inside provisioning.

`esp_event_handler_register` returns `ESP_ERR_INVALID_STATE` when the
default loop doesn't exist — and that path is fatal in our code, so a
mis-ordered init will abort instead of silently dropping the cold-boot
push. See HANDOFF.md 2026-04-29 for the post-mortem.

## Invariant 2: Components never depend on `main`

ESP-IDF's `main` component cannot be a `REQUIRES` dependency. Shared
types like `ctrl_cmd_t` live in `components/app_api/include/app_api.h`.
When adding a new cross-component API, put the header in `app_api/`
(or a new dedicated component) — don't let any component
`REQUIRES main`.

## Task topology rationale

```
priority 6  control_task                 owns PWM setpoints, drains ctrl_cmd_queue
priority 5  rpm_converter_task           freq_fifo → period→RPM → rpm_fifo
priority 4  rpm_averager_task            sliding avg → atomic latest_rpm + history
priority 3  httpd (ESP-IDF)              HTTP + WebSocket
priority 3  usb_hid_task                 HID OUT parse; IN @ 50 Hz from latest_rpm
priority 2  usb_cdc_tx/rx                CDC log mirror + SLIP OTA frames
priority 2  telemetry_task               20 Hz WebSocket status push
priority 2  ota_writer_task              single esp_ota_* writer (mutex-guarded)
```

### Lock-free SPSC ring buffers

`freq_fifo`, `rpm_fifo` connect ISR→task and task→task. **Don't replace
with `xQueue` without measuring** — the capture ISR runs at up to MHz
rates.

### Atomic float for `latest_rpm`

Bit-punned through `uint32_t`, relaxed ordering. One-sample staleness
is acceptable; **don't add a mutex**.

### RPM timeout sentinel

When no edge arrives within `rpm_timeout_us`, the timeout callback
pushes a period value with `0x80000000` OR'd in. The converter task
recognises this sentinel bit and emits `0.0 RPM`. Default timeout is
1 second. Preserve this mechanism when editing `rpm_cap.c`.

## Wire protocols (host tool contracts)

- **HID report IDs** and **CDC SLIP frame ops** are defined in
  `components/usb_composite/include/usb_protocol.h`. These are the
  contract with the PC host tool (separate project, out of this repo's
  scope). Changing payload shapes is a breaking change.
- **WebSocket JSON** contract: `{type: "set_pwm" | "set_rpm" |
  "factory_reset"}` for client→device, `{type: "status" | "ack" |
  "ota_progress"}` for device→client. Documented inline in
  `components/net_dashboard/ws_handler.c`.
