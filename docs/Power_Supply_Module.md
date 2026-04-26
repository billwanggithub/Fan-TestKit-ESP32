# Power Supply Connection Guide

Fan-TestKit's PSU subsystem lives on **UART1**. The same two GPIOs
(GPIO 38 / 39 + GND) talk to whichever PSU is wired — the dashboard
"Family" picker just changes the protocol the firmware speaks.

Selecting a family on the dashboard is **software only**. You still
have to physically wire the PSU before the link comes up.

---

## Supported families

| Family     | Wire protocol               | Factory baud | Slave addr default | Reference |
| ---------- | --------------------------- | ------------ | ------------------ | --------- |
| `riden`    | Modbus-RTU (FC 0x03 / 0x06) | 115200       | 1                  | RD6006 / RD6012 / RD6018 / RD6024 |
| `xy_sk120` | Modbus-RTU (FC 0x03 / 0x06) | 115200       | 1                  | [csvke/XY-SK120-Modbus-RTU-TTL](https://github.com/csvke/XY-SK120-Modbus-RTU-TTL) |
| `wz5005`   | Custom 20-byte sum-checksum | 19200        | 1                  | [kordian-kowalski/wz5005-control](https://github.com/kordian-kowalski/wz5005-control/blob/main/protocol.md) |

---

## Workflow — pick a family, then wire

### 1. Select the family on the dashboard

Open the dashboard at `http://fan-testkit.local/`. In the **Power
Supply** panel:

```text
┌─ Power Supply ───────────────────────────────────┐
│  V set    [slider/number] V                      │
│  I set    [slider/number] A                      │
│  Output   [OFF] [ON]                             │
│  Slave addr [1] [Save]                           │
│  Family    [▼ Riden RD60xx ] [Save] [Reboot]    │
└──────────────────────────────────────────────────┘
```

Dropdown → choose `Riden RD60xx` / `XY-SK120` / `WZ5005` → click
**Save**. The "重開後生效 / reboot to apply" hint appears. Then click
**Reboot**.

The choice is NVS-persisted (namespace `psu_driver`, key `family`).
The dashboard's family/slave/Reboot row stays clickable even when
the link is down — that's the escape hatch when the wrong family is
selected.

CLI alternative (USB-UART console): `psu_family wz5005` (then reboot
manually). `psu_family` with no arg prints the current value.

### 2. Wire the PSU to UART1

Same three signals for every family — the cables are identical, only
the firmware-side protocol changes:

```text
ESP32-S3 board                          PSU comms port
┌──────────────────┐                    ┌──────────────────┐
│ GPIO 38 (TX) ────┼──── data ────►─────┤ RX               │
│ GPIO 39 (RX) ◄───┼──── data ──────────┤ TX               │
│ GND      ────────┼──── ground ────────┤ GND              │
│                  │                    │ +3.3V (DO NOT     │
│                  │                    │   CONNECT)       │
└──────────────────┘                    └──────────────────┘
```

Notes:

- **Common ground is required.** Without it the UART signals float
  and you get garbage or nothing.
- **Don't connect the PSU's TTL VCC line.** The ESP32-S3 powers
  itself from USB; cross-feeding is unsafe.
- **TX/RX cross over.** ESP TX → PSU RX; ESP RX ← PSU TX.
- The PSU still needs its own DC bench input (e.g. RD60xx takes
  6–55 V DC; XY-SK120 takes ~5–32 V DC). UART1 is data only.

### 3. Match the baud rate (front panel ↔ firmware)

The firmware's compiled-in baud is set per-family by Kconfig (see
table above), but **the PSU's actual baud is whatever its front panel
is set to**. They must match.

Easiest path: set the PSU's panel baud to the family's factory
default and leave the firmware Kconfig alone.

| PSU          | How to set the baud |
| ------------ | ------------------- |
| Riden RD60xx | Front-panel menu → "Comm baud" → 115200 |
| XY-SK120     | Front-panel menu → 115200 |
| WZ5005       | `MENU` → item 4 (鲍率/baud) → choose 9600 / 19200 / 38400 / 57600 / 115200 |

If your bench unit is permanently keyed to a different baud, override
the firmware:

```sh
idf.py menuconfig     # → "PSU driver" → "PSU UART1 baud rate" → set
del sdkconfig         # or 'rm -f sdkconfig' — see CLAUDE.md sdkconfig trap
idf.py build flash
```

### 4. Match the slave address

Default is 1 on both sides. If your PSU's panel is set to a different
slave address, match it via the dashboard's **Slave addr** Save button
(NVS-persisted, no reboot needed) or the CLI: `psu_slave <N>`.

Range:

- Riden / XY-SK120: 1..247 (Modbus standard)
- WZ5005: 1..255 (manual extends the range)

The firmware accepts 1..255 in NVS; the Modbus backends clamp
internally.

### 5. WZ5005-only: panel must be in COM mode

The WZ5005 manual section 1.4.2.5 item 3 documents a `COM` / `WIFI`
selector on its system menu. Must be **COM** — WIFI mode disables
the TTL pins entirely. Symptom: every transaction times out, link
stays down even with correct wiring + baud + slave.

```text
WZ5005 menu path:  MENU → item 3 (Communication) → COM
```

---

## Verifying the link

Watch the serial console (`idf.py -p COMxx monitor`) during boot:

```text
I (1234) psu_driver: UART1 ready: family=wz5005 tx=38 rx=39 baud=19200 slave=1
I (1456) psu_wz5005: detected WZ5005 (factory byte 0 = 1)
```

The dashboard PSU panel turns green (`link=up`) and V/I telemetry
populates within ~1 second.

Failure modes:

| Symptom                                                              | Likely cause |
| -------------------------------------------------------------------- | ------------ |
| `link=down` immediately, never recovers                              | Baud mismatch / TX-RX swapped / no GND / wrong slave / WIFI mode (WZ5005) |
| `link=down` after working briefly                                    | Cable intermittent, panel re-keyed mid-session, PSU powered off |
| `link=up` but V/I values obviously wrong                             | Wrong family selected (Modbus framing on a WZ5005, or vice versa) |
| Boot-time `psu_driver` warning `baud N differs from family default M` | Kconfig override active; harmless if intentional, otherwise re-check |

Pre-flight without the PSU: select `wz5005`, reboot, confirm
dashboard shows `PSU offline` within ~1 second. Proves the firmware
is healthy and waiting on hardware.

---

## See also

- `CLAUDE.md` — "PSU driver — multi-family" section: architecture,
  invariants, vtable structure.
- `docs/superpowers/specs/2026-04-26-psu-multi-driver-design.md` —
  protocol details, byte-layout decisions, known unknowns.
- `components/psu_driver/Kconfig.projbuild` — UART pins, baud
  defaults, slave default, family choice.
