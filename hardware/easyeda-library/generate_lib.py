"""
Generate EasyEDA Standard schematic-symbol + PCB-footprint JSON files for the
YD-ESP32-S3-COREBOARD V1.4 (NodeMCU-ESP32-S3 / ESP32-S3-WROOM-1, N16R8 variant).

Source of truth:
  - Pinout: docs/YD-ESP32-S3-SCH-V1.4.pdf (J1, J2 22-pin headers)
  - Mechanics: docs/ESP32-S3-Metric.pdf (PCB outline 27.94 x 63.39 mm,
    header row spacing 25.40 mm, pin pitch 2.54 mm, pin span 53.34 mm,
    edge-to-pin1 margin 1.91 mm, USB-C tabs add ~6.24 mm to outline length)

Run: `python generate_lib.py`

Output:
  - YD-ESP32-S3-COREBOARD.symbol.json    -> EasyEDA Standard schematic symbol
  - YD-ESP32-S3-COREBOARD.footprint.json -> EasyEDA Standard PCB footprint

Import in EasyEDA Standard via:
  File -> Import -> EasyEDA Source...   (one file at a time)
Then save each into your personal library; link them together as a Device
(Symbol + Footprint).
"""
import json

# ---------- Pinout (from schematic) ----------
# J1 (left header, top -> bottom = pin 1 -> 22)
J1 = [
    ("3V3",   "P"),  # 1
    ("3V3",   "P"),  # 2
    ("EN",    "I"),  # 3  CHIP_PU
    ("GPIO4", "B"),  # 4
    ("GPIO5", "B"),  # 5
    ("GPIO6", "B"),  # 6
    ("GPIO7", "B"),  # 7
    ("GPIO15","B"),  # 8
    ("GPIO16","B"),  # 9
    ("GPIO17","B"),  # 10
    ("GPIO18","B"),  # 11
    ("GPIO8", "B"),  # 12
    ("GPIO3", "B"),  # 13   strapping (USB-JTAG select)
    ("GPIO46","B"),  # 14   strapping
    ("GPIO9", "B"),  # 15
    ("GPIO10","B"),  # 16
    ("GPIO11","B"),  # 17
    ("GPIO12","B"),  # 18
    ("GPIO13","B"),  # 19
    ("GPIO14","B"),  # 20
    ("5V",    "P"),  # 21   via D3 schottky + IN-OUT 0R jumper
    ("GND",   "P"),  # 22
]

# J2 (right header, top -> bottom = pin 1 -> 22)
J2 = [
    ("GND",   "P"),  # 1
    ("U0TXD", "B"),  # 2   GPIO43
    ("U0RXD", "B"),  # 3   GPIO44
    ("GPIO1", "B"),  # 4
    ("GPIO2", "B"),  # 5
    ("GPIO42","B"),  # 6
    ("GPIO41","B"),  # 7
    ("GPIO40","B"),  # 8
    ("GPIO39","B"),  # 9
    ("GPIO38","B"),  # 10
    ("GPIO37","B"),  # 11
    ("GPIO36","B"),  # 12
    ("GPIO35","B"),  # 13
    ("GPIO0", "B"),  # 14  strapping (BOOT)
    ("GPIO45","B"),  # 15  strapping
    ("GPIO48","B"),  # 16  WS2812 onboard RGB LED
    ("GPIO47","B"),  # 17
    ("GPIO21","B"),  # 18
    ("GPIO20","B"),  # 19  USB D+
    ("GPIO19","B"),  # 20  USB D-
    ("GND",   "P"),  # 21
    ("GND",   "P"),  # 22
]

# ============================================================================
# SCHEMATIC SYMBOL  (EasyEDA Standard JSON shape language)
# ============================================================================
# Coordinates are in pixels at 10 px = 100 mil = 2.54 mm grid (EasyEDA default).
# Pin pitch = 10 px. Pin length = 20 px (2 grid units, the EasyEDA default).
# Symbol body width = 50 grid units = 500 px.

PIN_PITCH = 10
PIN_LEN   = 20
BODY_W    = 60 * PIN_PITCH        # 600 px wide body
ROWS      = 22

# Top-left of the symbol body (in EasyEDA canvas px).
ORIGIN_X = 200
ORIGIN_Y = 100

BODY_LEFT  = ORIGIN_X
BODY_RIGHT = ORIGIN_X + BODY_W
BODY_TOP   = ORIGIN_Y
BODY_BOT   = ORIGIN_Y + (ROWS + 1) * PIN_PITCH   # +1 for top header label spacing

shapes = []

# ---- body rectangle ----
shapes.append(
    f"R~{BODY_LEFT}~{BODY_TOP}~~~{BODY_W}~{(ROWS + 1) * PIN_PITCH}~"
    f"#880000~1~0~none~rgba(255,255,194,1)~gge1~0"
)

# ---- title text in body header ----
shapes.append(
    f"T~L~{BODY_LEFT + 10}~{BODY_TOP + 12}~0~#000000~7pt~0~~~~~~"
    f"YD-ESP32-S3-COREBOARD~start~Title~gge_title~0"
)

# ---- helper: build one pin shape command ----
# Pin command grammar (EasyEDA Standard, simplified):
#   PIN~display~electric~spice~x~y~rotation~id~~M dx dy~
#       drawing~clock~
#       Pname~Px~Py~rotP~colorP~font~size~~~visible~
#       Nnumber~Nx~Ny~rotN~colorN~font~size~~~visible~
#       dot~clock_path
#
# We use rotation 0 for left-side pins (extending left) and 180 for right-side.
gid = 100

def pin_left(idx0, name, ptype):
    """Left-side pin (J1). idx0 is 0..21."""
    global gid
    y = BODY_TOP + (idx0 + 1) * PIN_PITCH + 5    # +5 for header offset within body
    x_pin_end  = BODY_LEFT - PIN_LEN
    x_pin_root = BODY_LEFT
    pin_num = idx0 + 1
    gid += 1
    g = f"gge{gid}"
    cmd = (
        f"P~show~{ptype}~~{x_pin_end}~{y}~0~{g}~~"
        f"M{x_pin_end},{y} h{PIN_LEN}~"
        f"#880000~0~"
        f"~{x_pin_root + 6}~{y}~0~#000000~Arial~7pt~end~~~1~"
        f"^^{name}^^{x_pin_root + 6}~{y - 4}~0~#000000~Arial~7pt~start~~~1~"
        f"^^{pin_num}^^{x_pin_end + 4}~{y - 4}~0~#000000~Arial~5pt~start~~~1~"
        f"0~"
    )
    return cmd

def pin_right(idx0, name, ptype):
    """Right-side pin (J2). idx0 is 0..21."""
    global gid
    y = BODY_TOP + (idx0 + 1) * PIN_PITCH + 5
    x_pin_root = BODY_RIGHT
    x_pin_end  = BODY_RIGHT + PIN_LEN
    pin_num = idx0 + 1 + 22       # J2 pins numbered 23..44 in symbol-pin order
    gid += 1
    g = f"gge{gid}"
    cmd = (
        f"P~show~{ptype}~~{x_pin_end}~{y}~180~{g}~~"
        f"M{x_pin_end},{y} h-{PIN_LEN}~"
        f"#880000~0~"
        f"~{x_pin_root - 6}~{y}~180~#000000~Arial~7pt~start~~~1~"
        f"^^{name}^^{x_pin_root - 6}~{y - 4}~0~#000000~Arial~7pt~end~~~1~"
        f"^^{pin_num}^^{x_pin_end - 4}~{y - 4}~0~#000000~Arial~5pt~end~~~1~"
        f"0~"
    )
    return cmd

# Use simpler reliable EasyEDA Pin syntax.
# A pin in EasyEDA Standard can be written as a pieces of nested commands;
# since hand-rolling raw shape strings is error-prone, we instead emit a
# minimal symbol whose pins are drawn as line + text + named pin.
# EasyEDA Pro accepts a cleaner nested pin description; for Standard we use
# the official "P" command with the documented field order:
#   P ~ display ~ electric ~ spice ~ x ~ y ~ rot ~ id ~ ~
#       Mxxx,yyy h±L ~ color ~ 0 ~
#       ^^pinDot^^xx~yy~rot~color~~~~~visible ~
#       ^^pinPath^^Mxx,yy h±dx ~ color ~ 0 ~
#       ^^pinName^^name~xx~yy~rot~color~Arial~7pt~start ~ ~ ~ visible ~
#       ^^pinNum^^num~xx~yy~rot~color~Arial~5pt~start ~ ~ ~ visible
#
# We adopt the working syntax used by symbols exported from EasyEDA itself.

def pin(idx0_global, name, ptype, side):
    """Emit one pin. side: 'L' or 'R'. idx0_global = 0..43."""
    global gid
    if side == "L":
        idx0 = idx0_global
        y = BODY_TOP + (idx0 + 1) * PIN_PITCH + 5
        x_root = BODY_LEFT
        x_end  = BODY_LEFT - PIN_LEN
        rot = 0
        path = f"M{x_root},{y} h-{PIN_LEN}"
        name_x = x_root + 4
        name_anchor = "start"
        num_x = x_end + 2
    else:
        idx0 = idx0_global - 22
        y = BODY_TOP + (idx0 + 1) * PIN_PITCH + 5
        x_root = BODY_RIGHT
        x_end  = BODY_RIGHT + PIN_LEN
        rot = 180
        path = f"M{x_root},{y} h{PIN_LEN}"
        name_x = x_root - 4
        name_anchor = "end"
        num_x = x_end - 2
    pin_num = idx0_global + 1   # 1..44
    gid += 1
    g_pin = f"gge{gid}"; gid += 1
    g_dot = f"gge{gid}"; gid += 1
    g_path= f"gge{gid}"; gid += 1
    g_nm  = f"gge{gid}"; gid += 1
    g_no  = f"gge{gid}"
    return (
        f"P~show~{ptype}~~{x_end}~{y}~{rot}~{g_pin}~~"
        f"^^0^^{x_end}~{y}~{rot}~#880000~~~~~0~{g_dot}~"
        f"^^1^^{path}~#880000~0~{g_path}~"
        f"^^2^^{name}~{name_x}~{y - 4}~0~#000000~Arial~7pt~{name_anchor}~~~1~{g_nm}~"
        f"^^3^^{pin_num}~{num_x}~{y - 4}~0~#000000~Arial~5pt~{'start' if side=='L' else 'end'}~~~1~{g_no}"
    )

# ---- emit all 44 pins ----
for i, (n, t) in enumerate(J1):
    shapes.append(pin(i, n, t, "L"))
for i, (n, t) in enumerate(J2):
    shapes.append(pin(22 + i, n, t, "R"))

# ---- prefab/refdes/value text in body ----
shapes.append(
    f"T~L~{BODY_LEFT + 10}~{BODY_TOP - 10}~0~#0066CC~7pt~0~~~~~~"
    f"U?~start~Prefix~ggeRefDes~0"
)
shapes.append(
    f"T~L~{BODY_RIGHT - 10}~{BODY_TOP - 10}~0~#0066CC~7pt~0~~~~~~"
    f"YD-ESP32-S3-COREBOARD~end~Name~ggeName~0"
)

symbol = {
    "head": {
        "docType": "2",
        "editorVersion": "6.5.46",
        "c_para": {
            "pre": "U?",
            "name": "YD-ESP32-S3-COREBOARD",
            "package": "YD-ESP32-S3-COREBOARD",
            "Manufacturer": "vcc-gnd.com (YD studio)",
            "Manufacturer Part": "YD-ESP32-S3-COREBOARD V1.4",
            "Description":
                "ESP32-S3-WROOM-1 (N16R8) dev board, 22+22 2.54 mm headers, "
                "USB1=CH343P UART0, USB2=native USB (HID/CDC), WS2812 on GPIO48",
        },
        "x": "0",
        "y": "0",
        "uuid": "yd-esp32-s3-coreboard-symbol",
        "puuid": "",
        "importFlag": 0,
        "transformList": "",
    },
    "canvas":
        "CA~1000~1000~#FFFFFF~yes~#CCCCCC~5~1000~1000~line~5~pixel~5~0~0",
    "shape": shapes,
    "BBox": {
        "x": BODY_LEFT - PIN_LEN - 80,
        "y": BODY_TOP - 30,
        "width": BODY_W + 2 * PIN_LEN + 160,
        "height": (ROWS + 1) * PIN_PITCH + 60,
    },
    "colors": {},
}

# ============================================================================
# PCB FOOTPRINT  (EasyEDA Standard JSON)
# ============================================================================
# Coordinate units: pixels, where 10 px == 100 mil == 2.54 mm  (EasyEDA default
# canvas grid).  All physical dimensions therefore scale by 10 px / 2.54 mm.
PX_PER_MM = 10.0 / 2.54

def mm(v): return v * PX_PER_MM

# Mechanical (Metric PDF):
PCB_W_MM    = 27.94
PCB_H_MM    = 63.39      # incl. USB-C tabs
HDR_PITCH_MM= 2.54
HDR_ROW_MM  = 25.40      # centerline-to-centerline of J1 and J2 columns
PIN_SPAN_MM = 53.34      # pin1 .. pin22 centers
EDGE_TO_P1_MM = 1.91     # top edge of PCB-without-USB-tabs to pin 1 center

# We place footprint centered on (0,0).
center_x = 0.0
center_y = 0.0

# Pin (1,1) of J1 lives at:
j1_x = center_x - mm(HDR_ROW_MM / 2)        # left column
j2_x = center_x + mm(HDR_ROW_MM / 2)        # right column
# Pin1 y position (top): we anchor the pin grid to the symmetric center of the
# 21 * 2.54 = 53.34 mm pin span.
pin1_y = center_y - mm(PIN_SPAN_MM / 2)

# Pad geometry: 2.54 mm header => standard 1.6 mm hole, 2.8 mm pad diameter.
HOLE_MM = 1.0    # 1.0 mm hole works for 0.6 mm round header pin AND THM screw
PAD_MM  = 1.8

shapes_fp = []

def pad(num, x, y, layer=11, shape="OVAL"):
    """layer 11 = multi-layer (THT)."""
    return (
        f"PAD~{shape}~{x:.4f}~{y:.4f}~"
        f"{mm(PAD_MM):.4f}~{mm(PAD_MM):.4f}~{layer}~{num}~"
        f"{mm(HOLE_MM):.4f}~~0~"
        f"gge_pad{num}~0~~~~~~0~~~~"
        f"M {x:.4f} {y - mm(PAD_MM)/2:.4f} L {x + mm(PAD_MM)/2:.4f} {y:.4f} "
        f"L {x:.4f} {y + mm(PAD_MM)/2:.4f} L {x - mm(PAD_MM)/2:.4f} {y:.4f} Z~"
        f"Y"
    )

# Pin 1 of every header is square (rectangle) per industry convention.
def pad_p1(num, x, y):
    s = mm(PAD_MM)
    return (
        f"PAD~RECT~{x:.4f}~{y:.4f}~"
        f"{s:.4f}~{s:.4f}~11~{num}~"
        f"{mm(HOLE_MM):.4f}~~0~"
        f"gge_pad{num}~0~~~~~~0~~~~"
        f"M {x - s/2:.4f} {y - s/2:.4f} L {x + s/2:.4f} {y - s/2:.4f} "
        f"L {x + s/2:.4f} {y + s/2:.4f} L {x - s/2:.4f} {y + s/2:.4f} Z~"
        f"Y"
    )

# J1 pads: numbered 1..22 in board, but to keep them aligned with the symbol
# we'll number them 1..22 (J1) and 23..44 (J2). The Device link sheet must
# 1:1 map symbol pin -> footprint pad number.
for i in range(22):
    y = pin1_y + mm(i * HDR_PITCH_MM)
    if i == 0:
        shapes_fp.append(pad_p1(i + 1, j1_x, y))
    else:
        shapes_fp.append(pad(i + 1, j1_x, y))
for i in range(22):
    y = pin1_y + mm(i * HDR_PITCH_MM)
    if i == 0:
        shapes_fp.append(pad_p1(i + 1 + 22, j2_x, y))
    else:
        shapes_fp.append(pad(i + 1 + 22, j2_x, y))

# Board outline rectangle on layer 10 (BoardOutLine).
half_w = mm(PCB_W_MM / 2)
half_h = mm(PCB_H_MM / 2)
shapes_fp.append(
    f"TRACK~0.4~10~"
    f"{-half_w:.4f} {-half_h:.4f} "
    f"{ half_w:.4f} {-half_h:.4f} "
    f"{ half_w:.4f} { half_h:.4f} "
    f"{-half_w:.4f} { half_h:.4f} "
    f"{-half_w:.4f} {-half_h:.4f}~"
    f"gge_outline~0"
)

# Top silkscreen — outline of the carrier well (slightly inside the board edge).
inset = mm(0.5)
shapes_fp.append(
    f"TRACK~0.254~3~"
    f"{-half_w + inset:.4f} {-half_h + inset:.4f} "
    f"{ half_w - inset:.4f} {-half_h + inset:.4f} "
    f"{ half_w - inset:.4f} { half_h - inset:.4f} "
    f"{-half_w + inset:.4f} { half_h - inset:.4f} "
    f"{-half_w + inset:.4f} {-half_h + inset:.4f}~"
    f"gge_silk~0"
)

# Pin-1 silk indicator: small arrow + "1" near J1 pin 1.
p1_y = pin1_y
shapes_fp.append(
    f"TEXT~L~{j1_x - mm(3):.4f}~{p1_y - mm(1):.4f}~0.3~0~0~3~0.6~1~"
    f"M0,0~start~~gge_p1text~0~1~Arial~"
)

# Reference designator (top silk) and value (bottom silk).
shapes_fp.append(
    f"TEXT~P~{0:.4f}~{-half_h - mm(2):.4f}~0.3~0~0~3~1.2~U?~"
    f"M0,0~middle~~ggeRefDes_fp~0~1~Arial~"
)
shapes_fp.append(
    f"TEXT~N~{0:.4f}~{ half_h + mm(2):.4f}~0.3~0~0~10~1.0~"
    f"YD-ESP32-S3-COREBOARD~M0,0~middle~~ggeName_fp~0~1~Arial~"
)

footprint = {
    "head": {
        "docType": "4",
        "editorVersion": "6.5.46",
        "c_para": {
            "pre": "U?",
            "package": "YD-ESP32-S3-COREBOARD",
            "link": "",
            "3DModel": "",
        },
        "x": "0",
        "y": "0",
        "uuid": "yd-esp32-s3-coreboard-footprint",
        "puuid": "",
        "importFlag": 0,
        "transformList": "",
    },
    "canvas":
        "CA~1000~1000~#000000~yes~#555555~5~1000~1000~line~5~mm~5~0~0~0~Both",
    "shape": shapes_fp,
    "layers": [
        "1~TopLayer~#FF0000~true~true~true~1",
        "2~BottomLayer~#0000FF~true~true~true~1",
        "3~TopSilkLayer~#FFCC00~true~true~true~1",
        "4~BottomSilkLayer~#66CC00~true~true~true~1",
        "5~TopPasteMaskLayer~#808080~true~false~true~1",
        "6~BottomPasteMaskLayer~#808080~true~false~true~1",
        "7~TopSolderMaskLayer~#800080~true~false~true~0.4",
        "8~BottomSolderMaskLayer~#800080~true~false~true~0.4",
        "9~Ratlines~#6464FF~true~true~true~1",
        "10~BoardOutLine~#FF00FF~true~true~true~1",
        "11~Multi-Layer~#A0A0A4~true~true~true~1",
        "12~Document~#FFFFFF~true~true~true~1",
        "13~TopAssembly~#888888~true~true~true~1",
        "14~BottomAssembly~#888888~true~true~true~1",
        "15~Mechanical~#808080~true~true~true~1",
    ],
    "BBox": {
        "x": -half_w - 20,
        "y": -half_h - 20,
        "width": 2 * half_w + 40,
        "height": 2 * half_h + 40,
    },
    "objects": [],
    "colors": {},
}

# ============================================================================
# Write outputs
# ============================================================================
import os
HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "YD-ESP32-S3-COREBOARD.symbol.json"), "w") as f:
    json.dump(symbol, f, indent=2)
with open(os.path.join(HERE, "YD-ESP32-S3-COREBOARD.footprint.json"), "w") as f:
    json.dump(footprint, f, indent=2)

# Pinout reference table for the README.
print("Wrote symbol + footprint JSON.")
print(f"  PCB outline: {PCB_W_MM} x {PCB_H_MM} mm")
print(f"  Header row spacing: {HDR_ROW_MM} mm  (centre-to-centre)")
print(f"  Pin pitch: {HDR_PITCH_MM} mm,  pin span: {PIN_SPAN_MM} mm  (22 pins)")
print(f"  Pad/hole: {PAD_MM} / {HOLE_MM} mm")
