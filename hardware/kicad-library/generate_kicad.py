"""
Generate KiCad 6+ schematic-symbol library and PCB footprint for the
YD-ESP32-S3-COREBOARD V1.4. Re-uses the pinout/mechanics source-of-truth
from ../easyeda-library/generate_lib.py (J1 / J2 lists are duplicated here
to keep this script standalone — keep them in sync if either pinout edits).

Source PDFs:
  ../../docs/YD-ESP32-S3-SCH-V1.4.pdf  (pinout)
  ../../docs/ESP32-S3-Metric.pdf       (mechanics)

Outputs:
  YD-ESP32-S3.kicad_sym                              -> schematic library
  YD-ESP32-S3.pretty/YD-ESP32-S3-COREBOARD.kicad_mod -> footprint
  sym-lib-table  /  fp-lib-table                     -> personal-library
                                                        registration snippets

Import into Altium:
  File -> Import Wizard -> "KiCad Files (*.kicad_pcb, *.kicad_sym, ...)"
  Point at YD-ESP32-S3.kicad_sym for the symbol; point at the .pretty
  folder for the footprint. Altium converts both into .SchLib / .PcbLib.

Import into KiCad (alt path):
  Preferences -> Manage Symbol Libraries / Footprint Libraries -> Add
  existing project library. Snippets in sym-lib-table / fp-lib-table
  show the exact lines to paste.
"""
import os

# ---------- Pinout (from schematic) ----------
# Pin types follow KiCad 6 vocabulary:
#   power_in, power_out, input, output, bidirectional, passive, no_connect
J1 = [
    ("3V3",   "power_in"),       # 1
    ("3V3",   "power_in"),       # 2
    ("EN",    "input"),          # 3  CHIP_PU
    ("GPIO4", "bidirectional"),  # 4
    ("GPIO5", "bidirectional"),  # 5
    ("GPIO6", "bidirectional"),  # 6
    ("GPIO7", "bidirectional"),  # 7
    ("GPIO15","bidirectional"),  # 8
    ("GPIO16","bidirectional"),  # 9
    ("GPIO17","bidirectional"),  # 10
    ("GPIO18","bidirectional"),  # 11
    ("GPIO8", "bidirectional"),  # 12
    ("GPIO3", "bidirectional"),  # 13   strapping (USB-JTAG select)
    ("GPIO46","bidirectional"),  # 14   strapping
    ("GPIO9", "bidirectional"),  # 15
    ("GPIO10","bidirectional"),  # 16
    ("GPIO11","bidirectional"),  # 17
    ("GPIO12","bidirectional"),  # 18
    ("GPIO13","bidirectional"),  # 19
    ("GPIO14","bidirectional"),  # 20
    ("5V",    "power_in"),       # 21   via D3 schottky + IN-OUT 0R jumper
    ("GND",   "power_in"),       # 22
]

J2 = [
    ("GND",   "power_in"),       # 1
    ("U0TXD", "bidirectional"),  # 2   GPIO43
    ("U0RXD", "bidirectional"),  # 3   GPIO44
    ("GPIO1", "bidirectional"),  # 4
    ("GPIO2", "bidirectional"),  # 5
    ("GPIO42","bidirectional"),  # 6
    ("GPIO41","bidirectional"),  # 7
    ("GPIO40","bidirectional"),  # 8
    ("GPIO39","bidirectional"),  # 9
    ("GPIO38","bidirectional"),  # 10
    ("GPIO37","bidirectional"),  # 11
    ("GPIO36","bidirectional"),  # 12
    ("GPIO35","bidirectional"),  # 13
    ("GPIO0", "bidirectional"),  # 14  strapping (BOOT)
    ("GPIO45","bidirectional"),  # 15  strapping
    ("GPIO48","bidirectional"),  # 16  WS2812 onboard RGB LED
    ("GPIO47","bidirectional"),  # 17
    ("GPIO21","bidirectional"),  # 18
    ("GPIO20","bidirectional"),  # 19  USB D+
    ("GPIO19","bidirectional"),  # 20  USB D-
    ("GND",   "power_in"),       # 21
    ("GND",   "power_in"),       # 22
]

# ---------- Mechanics (from Metric PDF) ----------
PCB_W_MM       = 27.94          # outline width
PCB_H_MM       = 63.39          # outline height incl. USB-C tabs
HDR_PITCH_MM   = 2.54           # 0.1"
HDR_ROW_MM     = 25.40          # J1 col -> J2 col centre-to-centre (1.0")
PIN_SPAN_MM    = 53.34          # pin1 -> pin22 centres == 21 * 2.54

PAD_DIA_MM     = 1.8
HOLE_DIA_MM    = 1.0

# ============================================================================
# SCHEMATIC SYMBOL  (KiCad 6 .kicad_sym)
# ============================================================================
# KiCad symbol coords: mm, Y axis inverted (Y+ = down on canvas).
# Pin pitch on the symbol = 2.54 mm (matches KiCad's default 50-mil grid).
# Pin length = 5.08 mm (2 grid units).
# Body width = 30.48 mm (12 grid units) — leaves room for "GPIO48" labels.

SYM_PIN_PITCH = 2.54
SYM_PIN_LEN   = 5.08
SYM_BODY_W    = 30.48
SYM_ROWS      = 22
SYM_BODY_H    = (SYM_ROWS + 1) * SYM_PIN_PITCH    # +1 for top header strip

# Symbol body centred on origin in X; pins span Y = -27.94 .. +25.40
SYM_LEFT  = -SYM_BODY_W / 2
SYM_RIGHT =  SYM_BODY_W / 2
SYM_TOP   = -((SYM_ROWS + 1) * SYM_PIN_PITCH) / 2
SYM_BOT   =  ((SYM_ROWS + 1) * SYM_PIN_PITCH) / 2


def sym_pin(name, num, ptype, x, y, length, orientation_deg):
    """Emit one (pin ...) S-expression line."""
    # KiCad pin orientation: 0 = pin extends to the +X direction (right);
    # 180 = -X (left); 90 = +Y (up); 270 = -Y (down).
    # For a symbol body, a pin on the LEFT side has orientation 0 (its body
    # connects on its right). A RIGHT-side pin has orientation 180.
    return (
        f'    (pin {ptype} line\n'
        f'      (at {x:.2f} {y:.2f} {orientation_deg})\n'
        f'      (length {length:.2f})\n'
        f'      (name "{name}" (effects (font (size 1.27 1.27))))\n'
        f'      (number "{num}" (effects (font (size 1.27 1.27))))\n'
        f'    )'
    )


def build_symbol():
    """Return the full .kicad_sym text for one symbol."""
    pins = []
    # Left pins (J1, symbol pins 1..22). Pin 1 is at the top.
    for i, (name, ptype) in enumerate(J1):
        # Y from top (row 0) to bottom (row 21).  In KiCad Y+ = down.
        y = SYM_TOP + (i + 1) * SYM_PIN_PITCH
        # Left pin's tip is to the LEFT of the body, body root at SYM_LEFT.
        # Pin endpoint coordinate = body_left - length, but KiCad places the
        # pin AT (x, y) being the pin's connection point (the tip). The pin
        # then extends "length" in the orientation direction. For a left-side
        # pin (orientation 0 means extending right *into* the body)... actually
        # no — orientation = 180 means the pin graphic extends from its
        # connection point *toward* -X direction... wait. KiCad convention is:
        # the (at x y rot) is where the connection (electrical end) is.
        # rotation 0: the pin body extends to the LEFT of the connection point
        #             (so the connection point is on the RIGHT of the pin
        #             graphic). Use this for pins on the LEFT side of the body
        #             when you want the connection sticking out leftward.
        # Actually KiCad's spec: rotation 0 = pin points right; the body of
        # the symbol must therefore be on the LEFT of the pin's connection
        # point. For pins on the left side of a symbol body, rotation = 180.
        # Connection point sits at (SYM_LEFT - SYM_PIN_LEN, y).
        x = SYM_LEFT - SYM_PIN_LEN
        pins.append(sym_pin(name, i + 1, ptype, x, y, SYM_PIN_LEN, 0))
    # Right pins (J2, symbol pins 23..44).
    for i, (name, ptype) in enumerate(J2):
        y = SYM_TOP + (i + 1) * SYM_PIN_PITCH
        x = SYM_RIGHT + SYM_PIN_LEN
        pins.append(sym_pin(name, i + 1 + 22, ptype, x, y, SYM_PIN_LEN, 180))

    pins_block = "\n".join(pins)

    rect = (
        f'    (rectangle\n'
        f'      (start {SYM_LEFT:.2f} {SYM_TOP:.2f})\n'
        f'      (end   {SYM_RIGHT:.2f} {SYM_BOT:.2f})\n'
        f'      (stroke (width 0.254) (type default))\n'
        f'      (fill (type background))\n'
        f'    )'
    )

    return f'''(kicad_symbol_lib
  (version 20211014)
  (generator generate_kicad_py)
  (symbol "YD-ESP32-S3-COREBOARD"
    (in_bom yes)
    (on_board yes)
    (property "Reference" "U" (id 0)
      (at {SYM_LEFT:.2f} {SYM_TOP - 2.54:.2f} 0)
      (effects (font (size 1.27 1.27)) (justify left))
    )
    (property "Value" "YD-ESP32-S3-COREBOARD" (id 1)
      (at {SYM_RIGHT:.2f} {SYM_TOP - 2.54:.2f} 0)
      (effects (font (size 1.27 1.27)) (justify right))
    )
    (property "Footprint" "YD-ESP32-S3:YD-ESP32-S3-COREBOARD" (id 2)
      (at 0 0 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "https://www.vcc-gnd.com/" (id 3)
      (at 0 0 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Manufacturer" "vcc-gnd.com (YD studio)" (id 4)
      (at 0 0 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "MPN" "YD-ESP32-S3-COREBOARD V1.4" (id 5)
      (at 0 0 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "ki_keywords" "ESP32-S3 WROOM N16R8 dev board YD-ESP32-S3 NodeMCU" (id 6)
      (at 0 0 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "ki_description" "ESP32-S3-WROOM-1 (N16R8) dev board with 22+22 2.54 mm headers, USB1=CH343P UART0, USB2=native USB (HID/CDC), WS2812 on GPIO48" (id 7)
      (at 0 0 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (symbol "YD-ESP32-S3-COREBOARD_0_1"
{rect}
    )
    (symbol "YD-ESP32-S3-COREBOARD_1_1"
{pins_block}
    )
  )
)
'''


# ============================================================================
# PCB FOOTPRINT  (KiCad 6 .kicad_mod)
# ============================================================================
# Footprint coords: mm. Pads on layer "*.Cu" (THT through-hole = all copper).
# Silkscreen on F.SilkS, courtyard on F.CrtYd, fabrication on F.Fab.

# Footprint origin = component centre. Pin (1,1) of J1 is at:
J1_X = -HDR_ROW_MM / 2      # left column
J2_X = +HDR_ROW_MM / 2      # right column
PIN1_Y = -PIN_SPAN_MM / 2   # pin 1 is at the TOP (most-negative Y in KiCad)


def fp_pad(num, x, y, p1=False):
    """Through-hole pad. Pin 1 is rectangular per industry convention."""
    shape = "rect" if p1 else "circle"
    return (
        f'  (pad "{num}" thru_hole {shape}\n'
        f'    (at {x:.4f} {y:.4f})\n'
        f'    (size {PAD_DIA_MM:.2f} {PAD_DIA_MM:.2f})\n'
        f'    (drill {HOLE_DIA_MM:.2f})\n'
        f'    (layers "*.Cu" "*.Mask")\n'
        f'  )'
    )


def fp_line(x1, y1, x2, y2, layer, width=0.12):
    return (
        f'  (fp_line (start {x1:.4f} {y1:.4f}) (end {x2:.4f} {y2:.4f})\n'
        f'    (stroke (width {width}) (type solid)) (layer "{layer}")\n'
        f'  )'
    )


def fp_rect(x1, y1, x2, y2, layer, width=0.12):
    return "\n".join([
        fp_line(x1, y1, x2, y1, layer, width),
        fp_line(x2, y1, x2, y2, layer, width),
        fp_line(x2, y2, x1, y2, layer, width),
        fp_line(x1, y2, x1, y1, layer, width),
    ])


def fp_text(kind, text, x, y, layer, size=1.0, thickness=0.15):
    return (
        f'  (fp_text {kind} "{text}" (at {x:.2f} {y:.2f}) (layer "{layer}")\n'
        f'    (effects (font (size {size} {size}) (thickness {thickness})))\n'
        f'  )'
    )


def build_footprint():
    half_w = PCB_W_MM / 2
    half_h = PCB_H_MM / 2

    pads = []
    # J1: footprint pads 1..22
    for i in range(22):
        y = PIN1_Y + i * HDR_PITCH_MM
        pads.append(fp_pad(i + 1, J1_X, y, p1=(i == 0)))
    # J2: footprint pads 23..44
    for i in range(22):
        y = PIN1_Y + i * HDR_PITCH_MM
        pads.append(fp_pad(i + 1 + 22, J2_X, y, p1=(i == 0)))
    pads_block = "\n".join(pads)

    # Outline on Edge.Cuts (board outline) — useful when the footprint lives
    # standalone but is OPTIONAL when used on a carrier (the carrier owns its
    # own Edge.Cuts). We put it on F.Fab instead so it documents the keep-out
    # without forcing a board-cut wherever the footprint drops in.
    fab_outline = fp_rect(-half_w, -half_h, half_w, half_h, "F.Fab", width=0.10)
    silk_outline = fp_rect(-half_w, -half_h, half_w, half_h, "F.SilkS", width=0.12)

    # Courtyard slightly larger than the PCB outline.
    cy = 0.5
    courtyard = fp_rect(-half_w - cy, -half_h - cy,
                        half_w + cy,  half_h + cy, "F.CrtYd", width=0.05)

    # Pin-1 silk indicator: a small triangle/arrow next to J1 pin 1.
    p1_marker = fp_line(J1_X - PAD_DIA_MM, PIN1_Y - PAD_DIA_MM,
                        J1_X - PAD_DIA_MM, PIN1_Y + PAD_DIA_MM,
                        "F.SilkS", width=0.20)

    # Reference and value text. Value goes on F.Fab so it survives DRC; the
    # silkscreen reference is the user-visible designator.
    ref_text = fp_text("reference", "REF**",
                       0, -half_h - 1.5, "F.SilkS", size=1.0)
    val_text = fp_text("value", "YD-ESP32-S3-COREBOARD",
                       0, half_h + 1.5, "F.Fab", size=1.0)
    user_text = fp_text("user", "${REFERENCE}",
                        0, 0, "F.Fab", size=1.0)

    return f'''(footprint "YD-ESP32-S3-COREBOARD"
  (version 20221018)
  (generator generate_kicad_py)
  (layer "F.Cu")
  (descr "YD-ESP32-S3-COREBOARD V1.4 dev board, 2x22 2.54 mm female-header land pattern. Row spacing 25.40 mm, pin span 53.34 mm. PCB outline 27.94 x 63.39 mm.")
  (tags "ESP32-S3 WROOM N16R8 YD-ESP32-S3 NodeMCU header 2.54mm")
  (attr through_hole)
{ref_text}
{val_text}
{user_text}
{pads_block}
{fab_outline}
{silk_outline}
{courtyard}
{p1_marker}
)
'''


# ============================================================================
# Personal-library registration snippets (KiCad project tables)
# ============================================================================
SYM_LIB_TABLE = '''(sym_lib_table
  (lib (name "YD-ESP32-S3")(type "KiCad")(uri "${KIPRJMOD}/hardware/kicad-library/YD-ESP32-S3.kicad_sym")(options "")(descr "YD-ESP32-S3-COREBOARD V1.4 ESP32-S3 dev board"))
)
'''

FP_LIB_TABLE = '''(fp_lib_table
  (lib (name "YD-ESP32-S3")(type "KiCad")(uri "${KIPRJMOD}/hardware/kicad-library/YD-ESP32-S3.pretty")(options "")(descr "YD-ESP32-S3-COREBOARD V1.4 ESP32-S3 dev board"))
)
'''

# ============================================================================
# Write outputs
# ============================================================================
HERE = os.path.dirname(os.path.abspath(__file__))

sym_path = os.path.join(HERE, "YD-ESP32-S3.kicad_sym")
fp_dir   = os.path.join(HERE, "YD-ESP32-S3.pretty")
fp_path  = os.path.join(fp_dir, "YD-ESP32-S3-COREBOARD.kicad_mod")
sym_table_path = os.path.join(HERE, "sym-lib-table")
fp_table_path  = os.path.join(HERE, "fp-lib-table")

os.makedirs(fp_dir, exist_ok=True)

with open(sym_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(build_symbol())
with open(fp_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(build_footprint())
with open(sym_table_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(SYM_LIB_TABLE)
with open(fp_table_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(FP_LIB_TABLE)

print(f"Wrote KiCad library:")
print(f"  symbol:    {sym_path}")
print(f"  footprint: {fp_path}")
print(f"  sym table: {sym_table_path}")
print(f"  fp  table: {fp_table_path}")
print()
print(f"  PCB outline: {PCB_W_MM} x {PCB_H_MM} mm")
print(f"  Header row spacing: {HDR_ROW_MM} mm  (centre-to-centre)")
print(f"  Pin pitch: {HDR_PITCH_MM} mm,  pin span: {PIN_SPAN_MM} mm  (22 pins)")
print(f"  Pad/hole: {PAD_DIA_MM} / {HOLE_DIA_MM} mm")
