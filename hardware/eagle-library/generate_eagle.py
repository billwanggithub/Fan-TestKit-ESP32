"""
Generate an EAGLE .lbr (XML library) for the YD-ESP32-S3-COREBOARD V1.4.

Why EAGLE: Altium Designer has a first-class EAGLE importer
(File -> Import Wizard -> "EAGLE Files (*.SCH, *.BRD, *.LBR)"), but does
NOT ship a KiCad importer in most installations. So EAGLE .lbr is the
most-portable handoff format from this Python generator into Altium.

The .lbr also imports cleanly into:
  - EAGLE itself (any version 6+)
  - Fusion 360 Electronics
  - Autodesk EAGLE-format-aware tools

Source PDFs (single source of truth, mirrored from the EasyEDA / KiCad libs):
  ../../docs/YD-ESP32-S3-SCH-V1.4.pdf  (pinout)
  ../../docs/ESP32-S3-Metric.pdf       (mechanics)

Output:
  YD-ESP32-S3.lbr  -> EAGLE library: 1 symbol, 1 footprint (package), 1 device

Import into Altium Designer:
  File -> Import Wizard...
  Select "EAGLE Files (*.SCH, *.BRD, *.LBR)" -> Next
  Add YD-ESP32-S3.lbr -> Next -> finish
  Altium produces YD-ESP32-S3.SchLib + YD-ESP32-S3.PcbLib in the output
  folder you choose. The Device that links the two is preserved.
"""
import os
from xml.dom.minidom import getDOMImplementation

# ---------- Pinout (matches kicad-library / easyeda-library) ----------
# Pin direction codes for EAGLE: in, out, io, oc, hiz, pas, pwr, sup, nc
J1 = [
    ("3V3",   "pwr"),  # 1
    ("3V3",   "pwr"),  # 2
    ("EN",    "in"),   # 3  CHIP_PU
    ("GPIO4", "io"),   # 4
    ("GPIO5", "io"),   # 5
    ("GPIO6", "io"),   # 6
    ("GPIO7", "io"),   # 7
    ("GPIO15","io"),   # 8
    ("GPIO16","io"),   # 9
    ("GPIO17","io"),   # 10
    ("GPIO18","io"),   # 11
    ("GPIO8", "io"),   # 12
    ("GPIO3", "io"),   # 13   strapping (USB-JTAG select)
    ("GPIO46","io"),   # 14   strapping
    ("GPIO9", "io"),   # 15
    ("GPIO10","io"),   # 16
    ("GPIO11","io"),   # 17
    ("GPIO12","io"),   # 18
    ("GPIO13","io"),   # 19
    ("GPIO14","io"),   # 20
    ("5V",    "pwr"),  # 21   via D3 + IN-OUT 0R
    ("GND",   "pwr"),  # 22
]
J2 = [
    ("GND",   "pwr"),  # 1
    ("U0TXD", "io"),   # 2   GPIO43
    ("U0RXD", "io"),   # 3   GPIO44
    ("GPIO1", "io"),   # 4
    ("GPIO2", "io"),   # 5
    ("GPIO42","io"),   # 6
    ("GPIO41","io"),   # 7
    ("GPIO40","io"),   # 8
    ("GPIO39","io"),   # 9
    ("GPIO38","io"),   # 10
    ("GPIO37","io"),   # 11
    ("GPIO36","io"),   # 12
    ("GPIO35","io"),   # 13
    ("GPIO0", "io"),   # 14  strapping (BOOT)
    ("GPIO45","io"),   # 15  strapping
    ("GPIO48","io"),   # 16  WS2812 onboard RGB LED
    ("GPIO47","io"),   # 17
    ("GPIO21","io"),   # 18
    ("GPIO20","io"),   # 19  USB D+
    ("GPIO19","io"),   # 20  USB D-
    ("GND",   "pwr"),  # 21
    ("GND",   "pwr"),  # 22
]

# ---------- Mechanics (from Metric PDF) ----------
PCB_W_MM     = 27.94
PCB_H_MM     = 63.39
HDR_PITCH_MM = 2.54
HDR_ROW_MM   = 25.40
PIN_SPAN_MM  = 53.34
PAD_DIA_MM   = 1.8
HOLE_DIA_MM  = 1.0

# ============================================================================
# EAGLE coordinate convention:
#   - All coordinates in millimetres in the .lbr (EAGLE accepts mm directly).
#   - Y axis: positive = UP (mathematical, opposite of KiCad).
#   - Symbol grid: 0.1" = 2.54 mm. Pin length keyword "middle" = 5.08 mm.
#
# EAGLE layers used here (defaults from EAGLE's standard layer set):
#   Layer 1   = Top copper (used for SMD pads only; THT pads cover all copper)
#   Layer 16  = Bottom copper
#   Layer 17  = Pads (THT pad copper)         <- not a layer for elements,
#                                                THT <pad> creates copper on
#                                                all copper layers automatically
#   Layer 20  = Dimension (board outline)
#   Layer 21  = tPlace (top silkscreen)
#   Layer 25  = tNames (reference text on top silk)
#   Layer 27  = tValues (value text on top silk)
#   Layer 39  = tKeepout (top keepout)
#   Layer 51  = tDocu (documentation, similar to KiCad F.Fab)
#   Layer 94  = Symbols (schematic symbol body)
#   Layer 95  = Names (schematic ref text)
#   Layer 96  = Values (schematic value text)
# ============================================================================

# ---------- Schematic symbol layout ----------
SYM_PIN_PITCH = 2.54
SYM_PIN_LEN   = 5.08          # EAGLE "middle" pin length
SYM_BODY_W    = 30.48         # 12 grid units
SYM_ROWS      = 22

# Place the body so pin grid lands on EAGLE's mandatory 2.54 mm symbol grid.
SYM_LEFT  = -SYM_BODY_W / 2
SYM_RIGHT =  SYM_BODY_W / 2
# Pins span Y = +27.94 (top, pin 1) down to -25.40 (bottom, pin 22)
# In EAGLE Y+ = UP, so pin 1 is at the most-POSITIVE Y.
SYM_PIN1_Y =  (PIN_SPAN_MM / 2)
SYM_TOP    =  SYM_PIN1_Y + SYM_PIN_PITCH       # body top a bit above pin 1
SYM_BOT    = -SYM_PIN1_Y - SYM_PIN_PITCH       # body bottom a bit below pin 22

# Snap to 2.54 mm grid (EAGLE refuses off-grid pins in symbols)
def snap(v, grid=SYM_PIN_PITCH):
    return round(v / grid) * grid
SYM_TOP = snap(SYM_TOP)
SYM_BOT = snap(SYM_BOT)


# ============================================================================
# Build the XML tree
# ============================================================================
impl = getDOMImplementation()
doctype = impl.createDocumentType(
    "eagle",
    "",
    "eagle.dtd",
)
doc = impl.createDocument(None, "eagle", doctype)
root = doc.documentElement
root.setAttribute("version", "9.6.2")

def el(parent, tag, **attrs):
    e = doc.createElement(tag)
    for k, v in attrs.items():
        # XML attribute names can't contain '-' easily in Python kwargs,
        # so use '_' and translate.
        e.setAttribute(k.replace("__", "-"), str(v))
    parent.appendChild(e)
    return e

def fmt(v):
    """EAGLE prefers 4-decimal mm values."""
    return f"{v:.4f}"

# Drawing wrapper (mandatory in .lbr files)
drawing = el(root, "drawing")
el(drawing, "settings", alwaysvectorfont="no", verticaltext="up")
el(drawing, "grid",
   distance="0.1", unitdist="inch", unit="inch",
   style="lines", multiple="1", display="no", altdistance="0.01",
   altunitdist="inch", altunit="inch")

# ---------- Layer definitions ----------
layers_el = el(drawing, "layers")
LAYERS = [
    (1,  "Top",        4, 1, "yes", "yes", "yes"),
    (16, "Bottom",     1, 1, "yes", "yes", "yes"),
    (17, "Pads",       2, 1, "yes", "yes", "yes"),
    (18, "Vias",       2, 1, "yes", "yes", "yes"),
    (19, "Unrouted",   6, 1, "yes", "yes", "yes"),
    (20, "Dimension", 15, 1, "yes", "yes", "yes"),
    (21, "tPlace",     7, 1, "yes", "yes", "yes"),
    (22, "bPlace",     7, 1, "yes", "yes", "yes"),
    (25, "tNames",     7, 1, "yes", "yes", "yes"),
    (26, "bNames",     7, 1, "yes", "yes", "yes"),
    (27, "tValues",    7, 1, "yes", "yes", "yes"),
    (28, "bValues",    7, 1, "yes", "yes", "yes"),
    (29, "tStop",      7, 3, "yes", "yes", "yes"),
    (30, "bStop",      7, 6, "yes", "yes", "yes"),
    (39, "tKeepout",   4, 11, "yes", "yes", "yes"),
    (40, "bKeepout",   1, 11, "yes", "yes", "yes"),
    (41, "tRestrict",  4, 10, "yes", "yes", "yes"),
    (42, "bRestrict",  1, 10, "yes", "yes", "yes"),
    (43, "vRestrict",  2, 10, "yes", "yes", "yes"),
    (44, "Drills",     7, 1, "yes", "yes", "yes"),
    (45, "Holes",      7, 1, "yes", "yes", "yes"),
    (51, "tDocu",      7, 1, "yes", "yes", "yes"),
    (52, "bDocu",      7, 1, "yes", "yes", "yes"),
    (94, "Symbols",    4, 1, "yes", "yes", "yes"),
    (95, "Names",      7, 1, "yes", "yes", "yes"),
    (96, "Values",     7, 1, "yes", "yes", "yes"),
    (97, "Info",       7, 1, "yes", "yes", "yes"),
    (98, "Guide",      6, 1, "yes", "yes", "yes"),
]
for n, name, color, fill, vis, act, used in LAYERS:
    el(layers_el, "layer",
       number=n, name=name, color=color, fill=fill,
       visible=vis, active=act)

# ---------- Library ----------
library = el(drawing, "library")
el(library, "description").appendChild(doc.createTextNode(
    "YD-ESP32-S3-COREBOARD V1.4 ESP32-S3-WROOM-1 (N16R8) dev board.&#13;"
    "44-pin breakout: 2x 22-pin headers on 25.40 mm row spacing, "
    "2.54 mm pitch.&#13;"
    "USB1=CH343P UART0 console; USB2=native USB (HID/CDC); "
    "WS2812 RGB on GPIO48."
))

# ============================================================================
# PACKAGE  (PCB footprint)
# ============================================================================
packages = el(library, "packages")
package = el(packages, "package", name="YD-ESP32-S3-COREBOARD")
el(package, "description").appendChild(doc.createTextNode(
    "YD-ESP32-S3-COREBOARD V1.4 land pattern.&#13;"
    "2x22 THT, 25.40 mm row spacing, 2.54 mm pitch, 1.0 mm drill, "
    "1.8 mm pad."
))

# Footprint origin = component centre.
J1_X   = -HDR_ROW_MM / 2
J2_X   = +HDR_ROW_MM / 2
PIN1_Y =  PIN_SPAN_MM / 2     # EAGLE Y+ = up, so pin 1 (top) is +ve Y

def pad_thru(parent, num, x, y, p1=False):
    """Through-hole pad. Pin 1 of each header is square."""
    shape = "square" if p1 else "round"
    el(parent, "pad",
       name=str(num), x=fmt(x), y=fmt(y),
       drill=fmt(HOLE_DIA_MM), diameter=fmt(PAD_DIA_MM),
       shape=shape, rot="R0", thermals="no")

# 44 pads
for i in range(22):
    y = PIN1_Y - i * HDR_PITCH_MM
    pad_thru(package, i + 1, J1_X, y, p1=(i == 0))
for i in range(22):
    y = PIN1_Y - i * HDR_PITCH_MM
    pad_thru(package, i + 1 + 22, J2_X, y, p1=(i == 0))

# ---------- Outlines ----------
half_w = PCB_W_MM / 2
half_h = PCB_H_MM / 2

def line(parent, layer, x1, y1, x2, y2, width=0.127):
    el(parent, "wire",
       x1=fmt(x1), y1=fmt(y1), x2=fmt(x2), y2=fmt(y2),
       width=fmt(width), layer=layer)

# Layer 21 tPlace = silkscreen body outline (slightly inset)
inset = 0.5
for x1, y1, x2, y2 in [
    (-half_w + inset, -half_h + inset,  half_w - inset, -half_h + inset),
    ( half_w - inset, -half_h + inset,  half_w - inset,  half_h - inset),
    ( half_w - inset,  half_h - inset, -half_w + inset,  half_h - inset),
    (-half_w + inset,  half_h - inset, -half_w + inset, -half_h + inset),
]:
    line(package, 21, x1, y1, x2, y2, width=0.127)

# Layer 51 tDocu = full PCB outline (documentation only, doesn't gate DRC)
for x1, y1, x2, y2 in [
    (-half_w, -half_h,  half_w, -half_h),
    ( half_w, -half_h,  half_w,  half_h),
    ( half_w,  half_h, -half_w,  half_h),
    (-half_w,  half_h, -half_w, -half_h),
]:
    line(package, 51, x1, y1, x2, y2, width=0.10)

# Layer 39 tKeepout = component-area keepout under the carrier-side board
el(package, "rectangle",
   x1=fmt(-half_w), y1=fmt(-half_h),
   x2=fmt( half_w), y2=fmt( half_h),
   layer="39")

# Pin 1 silkscreen marker: short tick to the LEFT of J1 pin 1
line(package, 21,
     J1_X - PAD_DIA_MM,  PIN1_Y - PAD_DIA_MM/2,
     J1_X - PAD_DIA_MM,  PIN1_Y + PAD_DIA_MM/2, width=0.20)

# Reference and value text placeholders
el(package, "text",
   x=fmt(0), y=fmt(half_h + 1.5),
   size=fmt(1.2), layer="25", align="center"
).appendChild(doc.createTextNode(">NAME"))
el(package, "text",
   x=fmt(0), y=fmt(-half_h - 1.5),
   size=fmt(1.0), layer="27", align="center"
).appendChild(doc.createTextNode(">VALUE"))

# ============================================================================
# SYMBOL  (schematic)
# ============================================================================
symbols = el(library, "symbols")
symbol = el(symbols, "symbol", name="YD-ESP32-S3-COREBOARD")
el(symbol, "description").appendChild(doc.createTextNode(
    "YD-ESP32-S3-COREBOARD V1.4 schematic symbol (44 pins, J1=1..22, "
    "J2=23..44)."
))

# Body rectangle on layer 94 (Symbols)
el(symbol, "wire",
   x1=fmt(SYM_LEFT),  y1=fmt(SYM_TOP),
   x2=fmt(SYM_RIGHT), y2=fmt(SYM_TOP),
   width="0.254", layer="94")
el(symbol, "wire",
   x1=fmt(SYM_RIGHT), y1=fmt(SYM_TOP),
   x2=fmt(SYM_RIGHT), y2=fmt(SYM_BOT),
   width="0.254", layer="94")
el(symbol, "wire",
   x1=fmt(SYM_RIGHT), y1=fmt(SYM_BOT),
   x2=fmt(SYM_LEFT),  y2=fmt(SYM_BOT),
   width="0.254", layer="94")
el(symbol, "wire",
   x1=fmt(SYM_LEFT),  y1=fmt(SYM_BOT),
   x2=fmt(SYM_LEFT),  y2=fmt(SYM_TOP),
   width="0.254", layer="94")

# Reference and value placeholders
el(symbol, "text",
   x=fmt(SYM_LEFT), y=fmt(SYM_TOP + 1),
   size="1.778", layer="95"
).appendChild(doc.createTextNode(">NAME"))
el(symbol, "text",
   x=fmt(SYM_RIGHT), y=fmt(SYM_TOP + 1),
   size="1.778", layer="96", align="bottom-right"
).appendChild(doc.createTextNode(">VALUE"))

# Pins
def add_pin(parent, name, x, y, rot, direction):
    """
    EAGLE pin attributes:
      x, y        : pin's connection point (electrical end, where wires attach)
      length      : keyword: point | short | middle | long
                    (point=0, short=2.54, middle=5.08, long=7.62)
      direction   : in | out | io | oc | hiz | pas | pwr | sup | nc
      visible     : off | pad | pin | both
      rot         : R0 | R90 | R180 | R270
                    Pin extends FROM (x,y) IN the direction of rotation.
                    R0  = pin extends to the right of (x,y); body is on LEFT
                    R180= pin extends to the left  of (x,y); body is on RIGHT
                    For a left-side pin (body on the right), use R0.
                    For a right-side pin (body on the left), use R180.
    """
    el(parent, "pin",
       name=name, x=fmt(x), y=fmt(y),
       length="middle", direction=direction,
       visible="both", rot=rot)

# Left side (J1, symbol pins 1..22). Connection point sits to the LEFT of body.
for i, (name, dirn) in enumerate(J1):
    y = SYM_PIN1_Y - i * SYM_PIN_PITCH       # top -> bottom
    x = SYM_LEFT - SYM_PIN_LEN
    add_pin(symbol, name, x, y, "R0", dirn)

# Right side (J2, symbol pins 23..44).
for i, (name, dirn) in enumerate(J2):
    y = SYM_PIN1_Y - i * SYM_PIN_PITCH
    x = SYM_RIGHT + SYM_PIN_LEN
    add_pin(symbol, name, x, y, "R180", dirn)

# ============================================================================
# DEVICESET / DEVICE (links symbol -> footprint)
# ============================================================================
devicesets = el(library, "devicesets")
deviceset = el(devicesets, "deviceset",
               name="YD-ESP32-S3-COREBOARD", prefix="U", uservalue="no")
el(deviceset, "description").appendChild(doc.createTextNode(
    "YD-ESP32-S3-COREBOARD V1.4 dev board (ESP32-S3-WROOM-1 N16R8)."
))

gates = el(deviceset, "gates")
el(gates, "gate", name="G$1", symbol="YD-ESP32-S3-COREBOARD",
   x="0", y="0")

devices = el(deviceset, "devices")
device = el(devices, "device", name="", package="YD-ESP32-S3-COREBOARD")
connects = el(device, "connects")

# Map every symbol pin -> footprint pad (1:1 by number for our case).
# Pin name on the symbol  ↔ pad name on the package.
# EAGLE matches symbol-pin -> package-pad by NAME, so we need each symbol
# pin to have a unique name. Since we can have repeated nets ("3V3", "GND",
# "5V"), we add a numeric suffix on the symbol pin... BUT this would change
# the displayed pin name on the schematic. Instead, we use the standard
# EAGLE trick: rename the symbol pins to unique tokens like "P1", "P2"...
# and rely on the .lbr <connects> mapping to surface the friendly net
# names elsewhere. That doesn't match what we want either.
#
# The clean fix: number symbol pins 1..44 internally and put the friendly
# net name in the pin's display name field. EAGLE's <pin name="..."> IS
# the displayed name. To allow duplicates, we suffix duplicates with a
# zero-width counter. Easier: name pins "P1".."P44" and override display
# via the device's <connects> using pad="N". The displayed pin name is
# the symbol-pin name though, so users would see P1..P44, not GPIO names.
#
# Actual EAGLE solution: pin names in a SYMBOL must be unique within the
# symbol, but two pins CAN have the same DISPLAYED name if you use a
# trailing "@N" suffix — EAGLE shows everything before the "@".  This is
# the documented EAGLE convention used by Texas Instruments libraries
# for parts with multiple GND/VCC pins.

def display_to_unique(names):
    """Append @1, @2, ... only to repeated names. First instance unsuffixed."""
    seen = {}
    out = []
    for n in names:
        c = seen.get(n, 0) + 1
        seen[n] = c
        out.append(f"{n}@{c}" if c > 1 or names.count(n) > 1 else n)
    # Recompute: EAGLE wants @N on EVERY duplicated name, including the first.
    # The conditional above already does that via names.count(n) > 1.
    return out

all_names = [n for n, _ in J1] + [n for n, _ in J2]
unique_names = display_to_unique(all_names)

# Patch pin names in the symbol element to use the @-suffixed unique names.
# (We added them with the bare name above; rewrite now.)
# Find all <pin> elements under <symbol> in document order — that order
# corresponds to J1[0..21] then J2[0..21], which is the same order as
# all_names / unique_names.
sym_pins = symbol.getElementsByTagName("pin")
assert len(sym_pins) == 44, len(sym_pins)
for pin_el, uname in zip(sym_pins, unique_names):
    pin_el.setAttribute("name", uname)

# <connects>: gate G$1, pin <symbol pin name>, pad <package pad number>
for idx, uname in enumerate(unique_names, start=1):
    el(connects, "connect", gate="G$1", pin=uname, pad=str(idx))

# Technologies (mandatory empty)
el(device, "technologies").appendChild(
    doc.createElement("technology")
).setAttribute("name", "")

# ============================================================================
# Write
# ============================================================================
HERE = os.path.dirname(os.path.abspath(__file__))
out_path = os.path.join(HERE, "YD-ESP32-S3.lbr")

# minidom indents reasonably; we want EAGLE-style 1-space indents.
xml_text = doc.toprettyxml(indent=" ", encoding="utf-8")
with open(out_path, "wb") as f:
    f.write(xml_text)

print(f"Wrote {out_path}")
print(f"  symbol pins:    {len(sym_pins)}")
print(f"  package pads:   44")
print(f"  PCB outline:    {PCB_W_MM} x {PCB_H_MM} mm")
print(f"  Header row spacing: {HDR_ROW_MM} mm")
print(f"  Pin pitch / span:   {HDR_PITCH_MM} / {PIN_SPAN_MM} mm")
print(f"  Pad / hole:         {PAD_DIA_MM} / {HOLE_DIA_MM} mm")
