# YD-ESP32-S3-COREBOARD V1.4 — EasyEDA library

EasyEDA Standard schematic symbol + PCB footprint for the
**YD-ESP32-S3-COREBOARD V1.4** (ESP32-S3-WROOM-1, N16R8 — 16 MB flash, 8 MB
octal PSRAM). Use this when designing a carrier / breakout PCB that the
coreboard plugs into via its two 22-pin headers.

Generated from the source PDFs in [docs/](../../docs):

- [YD-ESP32-S3-SCH-V1.4.pdf](../../docs/YD-ESP32-S3-SCH-V1.4.pdf) — pinout
- [ESP32-S3-Metric.pdf](../../docs/ESP32-S3-Metric.pdf) — PCB mechanics

Re-run [generate_lib.py](generate_lib.py) after editing if the source
schematic ever changes.

## Files

| File                                   | What                                                                                |
| -------------------------------------- | ----------------------------------------------------------------------------------- |
| `YD-ESP32-S3-COREBOARD.symbol.json`    | EasyEDA Standard schematic symbol (44 pins)                                         |
| `YD-ESP32-S3-COREBOARD.footprint.json` | EasyEDA Standard PCB footprint (2× 22-pin THT headers, board outline, silkscreen)   |
| `generate_lib.py`                      | Source generator — single point of truth for pin map + dimensions                   |

## Import into EasyEDA Standard

EasyEDA Pro uses a different file format — these JSONs target **EasyEDA
Standard** (the free web editor at [easyeda.com](https://easyeda.com)).

1. Open EasyEDA Standard, sign in.
2. **File → Import → EasyEDA Source…** → pick
   `YD-ESP32-S3-COREBOARD.symbol.json`. The symbol opens in the editor.
   **File → Save** into your personal library.
3. Repeat for `YD-ESP32-S3-COREBOARD.footprint.json`.
4. Create a **Device** linking the two: in your library, right-click the
   symbol → **New → Device** → assign the footprint you just imported.
   Verify pad-number ↔ pin-number mapping (1..22 = J1, 23..44 = J2 — see
   table below).

## Pin map

The symbol numbers pins **1..22 for J1** (left header) and **23..44 for J2**
(right header). The footprint pads use the same numbering. The silkscreen on
the physical board labels them **J1 1..22** and **J2 1..22** independently —
remember to add 22 when looking up a J2 pin on the symbol.

### J1 (left header)

| Sym# | Board# | Net   | Notes                                    |
|------|--------|-------|------------------------------------------|
| 1    | J1.1   | 3V3   | LDO output (CJ6107A33GW)                 |
| 2    | J1.2   | 3V3   | tied to J1.1                             |
| 3    | J1.3   | EN    | ESP32-S3 CHIP_PU                         |
| 4    | J1.4   | GPIO4 |                                          |
| 5    | J1.5   | GPIO5 |                                          |
| 6    | J1.6   | GPIO6 |                                          |
| 7    | J1.7   | GPIO7 |                                          |
| 8    | J1.8   | GPIO15|                                          |
| 9    | J1.9   | GPIO16|                                          |
| 10   | J1.10  | GPIO17|                                          |
| 11   | J1.11  | GPIO18|                                          |
| 12   | J1.12  | GPIO8 |                                          |
| 13   | J1.13  | GPIO3 | strapping (USB-JTAG select at reset)     |
| 14   | J1.14  | GPIO46| strapping                                |
| 15   | J1.15  | GPIO9 |                                          |
| 16   | J1.16  | GPIO10|                                          |
| 17   | J1.17  | GPIO11|                                          |
| 18   | J1.18  | GPIO12|                                          |
| 19   | J1.19  | GPIO13|                                          |
| 20   | J1.20  | GPIO14|                                          |
| 21   | J1.21  | 5V    | via D3 schottky + IN-OUT 0Ω (back-feed)  |
| 22   | J1.22  | GND   |                                          |

### J2 (right header)

| Sym# | Board# | Net    | Notes                                   |
|------|--------|--------|-----------------------------------------|
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

GPIO19/20 also surface on USB2 via the on-board USB-OTG / USB-JTAG 0Ω
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

Hole 1.0 mm fits both 0.6 mm round header pins and standard 0.64 mm square
header pins with clearance for hand-soldering. Pin 1 of each header is a
square pad (industry convention).

## Verifying the import

After importing, sanity-check by:

1. Opening the footprint in EasyEDA's PCB editor and measuring the centre
   distance between any J1 pad and the same-row J2 pad — must be **25.40 mm**.
2. Measuring J1.1 → J1.22 — must be **53.34 mm**.
3. In the schematic, confirming pin 23 (J2.1) is labelled `3V3`, pin 25 (J2.3)
   is `U0TXD`, pin 39 (J2.17) is `GPIO48`.

## Limitations

- No 3D model. Add one in EasyEDA after import if you want it for assembly
  visualisation.
- USB-C connector keep-out / cutout is not included — the carrier PCB usually
  has a notch under the USB-C end of the coreboard so the connector overhangs
  the carrier. Add a milled slot in your carrier design referencing the
  Metric PDF.
- Coreboard mounting holes: the YD-ESP32-S3-COREBOARD V1.4 has no through-hole
  mounts — it's held by the headers alone. If your application needs vibration
  resistance, add stand-offs that clamp the PCB edges on the carrier.
