# YD-ESP32-S3-COREBOARD V1.4 — EAGLE library (for Altium import)

EAGLE `.lbr` library for the **YD-ESP32-S3-COREBOARD V1.4**
(ESP32-S3-WROOM-1, N16R8 — 16 MB flash, 8 MB octal PSRAM).

This format exists primarily as **the import path into Altium Designer**.
Altium ships an EAGLE importer in every installation
(File → Import Wizard → "EAGLE Files (\*.SCH, \*.BRD, \*.LBR)"), but
does NOT ship a KiCad importer in most installations. So `.lbr` is the
most-portable handoff format from this Python generator into Altium.

The same single source of truth lives at:

- [../easyeda-library/](../easyeda-library/) — for EasyEDA Standard
- [../kicad-library/](../kicad-library/) — for KiCad 6+ (also imports into
  Altium *if* your installation has the KiCad importer plugin)
- this folder — for Altium and EAGLE

Generated from the source PDFs in [docs/](../../docs):

- [YD-ESP32-S3-SCH-V1.4.pdf](../../docs/YD-ESP32-S3-SCH-V1.4.pdf) — pinout
- [ESP32-S3-Metric.pdf](../../docs/ESP32-S3-Metric.pdf) — PCB mechanics

Re-run [generate_eagle.py](generate_eagle.py) after editing if the source
schematic ever changes.

## Files

| File                  | What                                                              |
| --------------------- | ----------------------------------------------------------------- |
| `YD-ESP32-S3.lbr`     | EAGLE library: 1 symbol + 1 footprint + 1 device (linkage)        |
| `generate_eagle.py`   | Source generator                                                  |

## Import into Altium Designer

1. **File → Import Wizard…** → Next.
2. **Select Type of Files to Import** → pick **"EAGLE Files
   (\*.SCH, \*.BRD, \*.LBR)"** → Next.
3. **Add** `YD-ESP32-S3.lbr` to the import list → Next.
4. Choose the output folder (anywhere — Altium will produce `.SchLib`
   and `.PcbLib` files there) → Next → Finish.
5. Altium opens the converted libraries automatically. You'll get:
   - `YD-ESP32-S3.SchLib` — schematic library, 1 component named
     `YD-ESP32-S3-COREBOARD`, prefix `U`, 44 pins
   - `YD-ESP32-S3.PcbLib` — PCB library, 1 footprint named
     `YD-ESP32-S3-COREBOARD`, 44 THT pads
   - The Device-level link is preserved: opening the SchLib component,
     you'll see its **Footprint** field already points at the
     PcbLib footprint.
6. Optional: **File → New → Project → Integrated Library** if you want
   to bundle the two into a single `.IntLib` per your team's policy.

### After-import sanity check

- In **PcbLib editor**: distance between any pad on the J1 column and the
  same-row pad on the J2 column = **25.40 mm** centre-to-centre.
- Pad 1 → pad 22 (J1 column) = **53.34 mm**.
- Pad 1 of each header (pads 1 and 23 in our numbering) is **square**;
  all other pads are **round**.
- All pads are through-hole, **1.80 mm** diameter, **1.00 mm** drill, on
  **Multi-Layer**.
- In **SchLib editor**: 44 pins. Power pins (`3V3`, `5V`, `GND`) marked
  as electrical type **Power**, `EN` as **Input**, GPIOs as **I/O**.
  Duplicate net names (`3V3`, `GND`) display as plain `3V3` / `GND` even
  though the underlying pin name carries an `@N` suffix — this is the
  standard EAGLE convention for repeating power pins, and Altium
  preserves it on import.

## Pin map

The symbol numbers pins **1..22 for J1** (left header) and **23..44 for J2**
(right header). The footprint pads use the same numbering. The silkscreen
on the physical board labels them **J1 1..22** and **J2 1..22**
independently — remember to add 22 when looking up a J2 pin on the symbol.

### J1 (left header)

| Sym# | Board# | Net    | Notes                                    |
| ---- | ------ | ------ | ---------------------------------------- |
| 1    | J1.1   | 3V3    | LDO output (CJ6107A33GW)                 |
| 2    | J1.2   | 3V3    | tied to J1.1                             |
| 3    | J1.3   | EN     | ESP32-S3 CHIP_PU                         |
| 4    | J1.4   | GPIO4  |                                          |
| 5    | J1.5   | GPIO5  |                                          |
| 6    | J1.6   | GPIO6  |                                          |
| 7    | J1.7   | GPIO7  |                                          |
| 8    | J1.8   | GPIO15 |                                          |
| 9    | J1.9   | GPIO16 |                                          |
| 10   | J1.10  | GPIO17 |                                          |
| 11   | J1.11  | GPIO18 |                                          |
| 12   | J1.12  | GPIO8  |                                          |
| 13   | J1.13  | GPIO3  | strapping (USB-JTAG select at reset)     |
| 14   | J1.14  | GPIO46 | strapping                                |
| 15   | J1.15  | GPIO9  |                                          |
| 16   | J1.16  | GPIO10 |                                          |
| 17   | J1.17  | GPIO11 |                                          |
| 18   | J1.18  | GPIO12 |                                          |
| 19   | J1.19  | GPIO13 |                                          |
| 20   | J1.20  | GPIO14 |                                          |
| 21   | J1.21  | 5V     | via D3 schottky + IN-OUT 0Ω (back-feed)  |
| 22   | J1.22  | GND    |                                          |

### J2 (right header)

| Sym# | Board# | Net    | Notes                                   |
| ---- | ------ | ------ | --------------------------------------- |
| 23   | J2.1   | GND    |                                         |
| 24   | J2.2   | U0TXD  | GPIO43 — CH343P UART0 TX (USB1 console) |
| 25   | J2.3   | U0RXD  | GPIO44 — CH343P UART0 RX (USB1 console) |
| 26   | J2.4   | GPIO1  |                                         |
| 27   | J2.5   | GPIO2  |                                         |
| 28   | J2.6   | GPIO42 |                                         |
| 29   | J2.7   | GPIO41 |                                         |
| 30   | J2.8   | GPIO40 |                                         |
| 31   | J2.9   | GPIO39 |                                         |
| 32   | J2.10  | GPIO38 |                                         |
| 33   | J2.11  | GPIO37 |                                         |
| 34   | J2.12  | GPIO36 |                                         |
| 35   | J2.13  | GPIO35 |                                         |
| 36   | J2.14  | GPIO0  | strapping (BOOT)                        |
| 37   | J2.15  | GPIO45 | strapping                               |
| 38   | J2.16  | GPIO48 | onboard WS2812 RGB LED data             |
| 39   | J2.17  | GPIO47 |                                         |
| 40   | J2.18  | GPIO21 |                                         |
| 41   | J2.19  | GPIO20 | USB D+ (USB2 — TinyUSB / USB-JTAG)      |
| 42   | J2.20  | GPIO19 | USB D- (USB2)                           |
| 43   | J2.21  | GND    | tied to J2.22                           |
| 44   | J2.22  | GND    |                                         |

GPIO19/20 also surface on USB2 via the on-board USB-OTG / USB-JTAG 0 Ω
jumper — if your carrier uses these GPIOs as plain IO, leave the USB2
jumper in USB-JTAG position so they're free.

## Mechanics

| Parameter                           | Value            |
| ----------------------------------- | ---------------- |
| PCB outline (W × H, incl. USB tabs) | 27.94 × 63.39 mm |
| Header row spacing (J1 ↔ J2 centre) | 25.40 mm (1.0″)  |
| Header pin pitch                    | 2.54 mm (0.1″)   |
| Pins per header                     | 22               |
| Pin span (pin1 ↔ pin22 centres)     | 53.34 mm         |
| Edge-to-pin1 margin (top)           | 1.91 mm          |
| Pad / hole                          | 1.8 / 1.0 mm     |

Hole 1.0 mm fits both 0.6 mm round header pins and standard 0.64 mm
square header pins with clearance for hand-soldering. Pin 1 of each
header is a square pad (industry convention).

## EAGLE layers used in the footprint

| EAGLE layer | What                                | Altium equivalent after import |
| ----------- | ----------------------------------- | ------------------------------ |
| 17 Pads     | THT pad copper (all layers via THT) | Multi-Layer                    |
| 21 tPlace   | Top silkscreen body outline + pin-1 | Top Overlay                    |
| 25 tNames   | Reference designator (>NAME)        | Top Overlay                    |
| 27 tValues  | Value text (>VALUE)                 | Top Overlay (or Mech)          |
| 39 tKeepout | Component keepout zone              | Keep-Out (or Mech 1)           |
| 51 tDocu    | Full PCB outline (documentation)    | Mechanical 13                  |

The Dimension layer (board outline / Edge.Cuts) is intentionally NOT used
— the component is meant to drop into a carrier PCB which owns its own
outline. The PCB outline is documented on layer 51 (tDocu) for visual
reference only.

## Limitations

- No 3D model. Add a STEP file in Altium after import if you want one
  for assembly visualisation.
- USB-C connector keep-out / cutout is not included — the carrier PCB
  usually has a milled slot at the USB-C end so the connectors overhang
  the carrier. Add the slot in your carrier design referencing the
  Metric PDF.
- Coreboard mounting holes: the YD-ESP32-S3-COREBOARD V1.4 has no
  through-hole mounts — it's held by the headers alone. If your
  application needs vibration resistance, add stand-offs that clamp the
  PCB edges on the carrier.

## Note on `@N` suffixed pin names

EAGLE requires every pin name within a symbol to be unique, but real
parts often have multiple pins with the same net name (e.g. four GND
pins). The standard convention — used by official Texas Instruments,
Analog Devices, and ST EAGLE libraries — is to suffix duplicates with
`@1`, `@2`, etc. EAGLE displays everything before the `@` on the
schematic, so the user sees `GND` four times. Our library uses this
convention for `3V3` (×2) and `GND` (×4). Altium's EAGLE importer
preserves the suffixes on the underlying pin names but the displayed
name in the SchLib remains the visible part — no manual cleanup
needed.
