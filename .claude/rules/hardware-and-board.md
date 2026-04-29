# Hardware & Board Reference

**Board:** YD-ESP32-S3-COREBOARD V1.4 — ESP32-S3-WROOM-1, 16 MB flash, 8 MB
octal PSRAM (N16R8 variant). Schematic at `docs/YD-ESP32-S3-SCH-V1.4.pdf`.
Full design spec at `C:\Users\billw\.claude\plans\read-the-project-plan-pure-eagle.md`.

## USB ports

Two USB-C with distinct roles:

- **USB1** — CH343P USB-UART bridge on UART0. Serial console + `idf.py flash`
  auto-reset. Always available for logs regardless of other config.
- **USB2** — native USB D-/D+ on GPIO19/GPIO20. Routes to either the
  USB-JTAG peripheral or TinyUSB via a `USB-JTAG` / `USB-OTG` 0 Ω jumper.
  **TinyUSB composite (HID + CDC) requires the `USB-OTG` jumper to be
  bridged.** Users often hit this on first run.

## GPIO reservations

- Reserved by hardware: **19, 20** (USB).
- Strapping pins to avoid for critical outputs: **0** (BOOT), **3** (USB-JTAG
  select), **45**, **46**.
- Onboard WS2812 RGB LED: **GPIO48**.
- UART1 (PSU bus): **GPIO38** (TX) / **GPIO39** (RX); 8N1; baud is
  family-dependent (Riden 115200, XY-SK120 115200, WZ5005 19200) and
  Kconfig-overridable. See `docs/Power_Supply_Module.md`.

## CH343 DTR/RTS auto-program trap — chip stuck in download mode

**Symptom:** after a successful flash, the serial monitor shows
`rst:0x1 (POWERON),boot:0x0 (DOWNLOAD(USB/UART0)) waiting for download`
on every reset instead of running the app. BOOT button is not pressed,
flash hashes verify, but the app never runs.

**Root cause:** the YD-ESP32-S3 has an "Auto program" transistor circuit on
the CH343's DTR/RTS lines (schematic page 1, Q1/Q2). Truth table:

```
DTR  RTS  -->  EN   IO0
 1    1         1    1     <- run mode (idle)
 1    0         0    1     <- reset asserted
 0    1         1    0     <- download mode (GPIO0 low at boot)
```

Some CH343 driver + pySerial combinations leave RTS asserted (RTS=1
while DTR drops to 0 at port close), which pulls GPIO0 low so the chip
boots into download mode on the next reset. `idf.py monitor` re-triggers
this every time it opens the port, so the chip never escapes.

**Fix** — when opening a serial tool to interact with the REPL:

- Use a terminal that lets you **explicitly hold DTR=1 and RTS=1** on
  port open (串口調試助手 / SerialTool works — check both DTR and RTS
  boxes before 打開). PuTTY by default does not toggle these and works.
- Or: `idf.py -p COMn monitor --no-reset` skips the reset-on-open
  sequence.
- Or: physical power cycle (unplug USB, wait 2 s, replug) — boots
  cleanly because no host has the port open yet.

Do **not** try to solve this by removing R5/R7/Q1/Q2 — esptool's auto
program sequence on flash depends on them. Only monitor-open is the
problem.
