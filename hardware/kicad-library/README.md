# YD-ESP32-S3-COREBOARD V1.4 — KiCad library (also imports into Altium)

KiCad 6+ schematic-symbol library and PCB footprint for the
**YD-ESP32-S3-COREBOARD V1.4** (ESP32-S3-WROOM-1, N16R8 — 16 MB flash, 8 MB
octal PSRAM).

KiCad's S-expression text format is also Altium Designer's preferred
import path for vendor-neutral libraries: Altium has a built-in
**File → Import Wizard → KiCad Files** that converts `.kicad_sym` →
`.SchLib` and `.pretty/*.kicad_mod` → `.PcbLib`. So the same files in this
folder work in both ecosystems.

Generated from the source PDFs in [docs/](../../docs):

- [YD-ESP32-S3-SCH-V1.4.pdf](../../docs/YD-ESP32-S3-SCH-V1.4.pdf) — pinout
- [ESP32-S3-Metric.pdf](../../docs/ESP32-S3-Metric.pdf) — PCB mechanics

The pin map, mechanical dimensions, and pad geometry mirror the
[../easyeda-library/](../easyeda-library/README.md) tree — same
single-source-of-truth data, different output format.
Re-run [generate_kicad.py](generate_kicad.py) after editing if the source
schematic ever changes.

## Files

| File                                              | What                                                            |
| ------------------------------------------------- | --------------------------------------------------------------- |
| `YD-ESP32-S3.kicad_sym`                           | Schematic symbol library (one symbol, 44 pins)                  |
| `YD-ESP32-S3.pretty/YD-ESP32-S3-COREBOARD.kicad_mod` | PCB footprint (2× 22-pin THT, board outline, silk, courtyard)   |
| `sym-lib-table` / `fp-lib-table`                  | KiCad personal-library registration snippets (paste into yours) |
| `generate_kicad.py`                               | Source generator — single point of truth                        |

## Import into Altium Designer

1. **File → Import Wizard…**
2. Select **"KiCad Files"** in the file-format list, click Next.
3. **For the symbol library:** point the wizard at
   `YD-ESP32-S3.kicad_sym`. Altium converts it to a `.SchLib`. Save the
   resulting `.SchLib` into your IntLib project (or any personal library
   path).
4. **For the footprint library:** run the wizard a second time, select
   "KiCad Files" again, and this time point it at the entire
   `YD-ESP32-S3.pretty/` **folder**. Altium reads every `.kicad_mod`
   inside and produces a `.PcbLib`.
5. Open the resulting `.SchLib`, find the `YD-ESP32-S3-COREBOARD` symbol,
   and verify in the **SCH Library** panel that the **Footprint** field
   points at `YD-ESP32-S3-COREBOARD` in the new `.PcbLib`. (The KiCad
   symbol's `Footprint` property is `YD-ESP32-S3:YD-ESP32-S3-COREBOARD` —
   Altium drops the namespace prefix on import; you may need to retype it
   as just the footprint name plus a Library reference.)
6. Optional: bundle into an `.IntLib` if your team policy uses integrated
   libraries (Project → Add New Project → Integrated Library).

### Sanity-check after Altium import

- Open the footprint in PcbLib editor: distance between any pad on the
  J1 column and the same-row pad on the J2 column = **25.40 mm** centre
  to centre.
- Distance from pad 1 to pad 22 (J1) = **53.34 mm**.
- Pad 1 of each header is rectangular; pads 2..22 are circular.
- All pads are through-hole, 1.80 mm diameter, 1.00 mm drill, on
  `Multi-Layer` (Altium's equivalent of KiCad's `*.Cu *.Mask`).

## Import into KiCad (alternate path)

For an existing KiCad project:

1. Edit the project's `sym-lib-table` and `fp-lib-table` (in the project
   directory) and append the lines from this folder's `sym-lib-table`
   and `fp-lib-table`. The snippets use `${KIPRJMOD}` so they
   auto-resolve relative to your project file.
2. Or via GUI: **Preferences → Manage Symbol Libraries → Project Specific
   Libraries → "+"** and browse to `YD-ESP32-S3.kicad_sym`. Same path
   for footprints under **Manage Footprint Libraries**.

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

## Layers used in the footprint

| KiCad layer | What                                | Altium equivalent after import |
| ----------- | ----------------------------------- | ------------------------------ |
| `*.Cu`      | THT pad copper (all layers)         | Multi-Layer                    |
| `*.Mask`    | Solder mask aperture                | Top/Bottom Solder              |
| `F.SilkS`   | Top silkscreen outline + pin-1 mark | Top Overlay                    |
| `F.Fab`     | Component outline + value text      | Mechanical 13 (Fab)            |
| `F.CrtYd`   | Courtyard / keepout                 | Mechanical 1 (or Keep-Out)     |

The Edge.Cuts (board outline) layer is intentionally NOT used — the
component is meant to drop into a carrier PCB which owns its own outline.
The PCB outline is documented on `F.Fab` and `F.SilkS` for visual
reference only.

## Limitations

- No 3D model. Add an STEP file in KiCad/Altium after import if you want
  one for assembly visualisation.
- USB-C connector keep-out / cutout is not included — the carrier PCB
  usually has a milled slot at the USB-C end so the connectors overhang
  the carrier. Add the slot in your carrier design referencing the
  Metric PDF.
- Coreboard mounting holes: the YD-ESP32-S3-COREBOARD V1.4 has no
  through-hole mounts — it's held by the headers alone. If your
  application needs vibration resistance, add stand-offs that clamp the
  PCB edges on the carrier.
