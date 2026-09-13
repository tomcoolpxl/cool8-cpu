#!/usr/bin/env python3
"""COOL SWEEPER's art and music: the cells, the frame, the logo, the
cursor, the three themes' palettes and the tunes.

    python tools/mkcoolsw.py           write assets/coolsw/coolsw_art.act and a preview
    python tools/mkcoolsw.py --check   the art file is current

**The picture is this game's own.** Minesweeper's rules are the
common property of every version since 1990; nothing here is taken
from one of them. Every cell, frame piece, icon and the cursor are
drawn by this script, and the only borrowed pixels are the Namco glyphs
Ms. Cool-Man's sheets carry, which COOLTRIS and Arkanoid use too -- here
with a drop shadow, and doubled into a gradient for the logo.

**A cell is 16 x 16, four tiles.** Mode 2's tiles are 8 x 8, so a cell
is a two-by-two block, and the field alternates two shades of each
kind of cell in a checkerboard so the grid reads without lines. The
light and dark squares are separate patterns; the colour of a number
is its palette bank, so the eight numbers cost eight banks and one set
of digit patterns per shade.

**Three themes, the whole palette each**: a meadow for Easy, the sea
for Medium, lava for Hard. A theme is 256 colours written in one go,
so the title shows the theme of the level the cursor is on.

**The tunes are written out note by note** below, eighth by eighth,
one bar a line. The player gives each voice an envelope -- a pluck
that falls to a sustain -- the lead a vibrato and a detuned double on
a voice of its own, and plays drums on the noise channel; so what is
written here is notes, and the shaping is the game's.
"""

import colorsys
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkmscool                                  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "assets", "coolsw")
OUT = os.path.join(ART, "coolsw_art.act")
PREVIEW = os.path.join(ART, "preview.png")


# ------------------------------------------------------------ the colours
def rgb12(c):
    """#RRGGBB to the machine's $0RGB."""
    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
    return (round(r / 17) << 8) | (round(g / 17) << 4) | round(b / 17)


def shade(c, f):
    """#RRGGBB scaled in value by f, towards white when f > 1."""
    r, g, b = ((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if f <= 1:
        v *= f
    else:
        s *= max(0.0, 2 - f)
        v = min(1.0, v * f)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (round(r * 255) << 16) | (round(g * 255) << 8) | round(b * 255)


def mix(a, b, t):
    ch = lambda x, s: (x >> s) & 255                       # noqa: E731
    return sum(round(ch(a, s) * (1 - t) + ch(b, s) * t) << s for s in (16, 8, 0))


# The eight numbers, the colours every coolsweeper since has taught the
# eye: blue, green, red, purple, orange, teal, charcoal, grey.
NUMBERS = [0x1E6FD9, 0x2E9E3E, 0xE0302A, 0x8A2BB8, 0xF08A00, 0x00A0B0, 0x3A3A48, 0x8C8C96]

# The field bank's sixteen: 0 the outline, 1-3 a light covered cell's
# highlight, face and shade, 4-6 a dark one's, 7 and 8 the two grounds
# of an opened cell, 9 its sunken edge, 10-12 a glyph's light, body and
# shadow (the flag's cloth in this bank, a number's in its own), 13 the
# dark of the pole and the mine, 14 the mine's rim, 15 white.
THEMES = [
    dict(name="meadow",
         cover=(0xA8D85A, 0x9ACB4C), ground=(0xEBCBA2, 0xDDBC94),
         bg=0x0E2416, motif=0x1E4228, twinkle=0xFFE36A,
         frame=(0x3A2610, 0xA8712A, 0xE2B252, 0xFFF1B8), panel=0x173020,
         accent=0xFFD84A, logo=(0xFFF7A8, 0xFFE35C, 0xFFC82E, 0xFFA41E, 0xF07A12, 0xCC520A),
         cursor=(0xFFE040, 0xFFFFA0)),
    dict(name="sea",
         cover=(0x86CDEB, 0x74BDE0), ground=(0xF3E8CC, 0xE6D8B6),
         bg=0x07162E, motif=0x12305C, twinkle=0x9FF4FF,
         frame=(0x0E2C48, 0x3984B2, 0x8CD2F2, 0xEAFBFF), panel=0x0C2344,
         accent=0x7FE6FF, logo=(0xE8FFFF, 0xA8F0FF, 0x6AD8FF, 0x3AB0F0, 0x2280D8, 0x1A52B0),
         cursor=(0x60E8FF, 0xE0FFFF)),
    dict(name="lava",
         cover=(0xC77AD8, 0xB86ACA), ground=(0xFCE2D2, 0xF1D0BE),
         bg=0x1E0810, motif=0x481420, twinkle=0xFF8A2A,
         frame=(0x3E0E08, 0xBE4616, 0xFF963E, 0xFFE2A2), panel=0x361018,
         accent=0xFFB040, logo=(0xFFF0B0, 0xFFD060, 0xFFA030, 0xFF6A20, 0xE83A1A, 0xA81A18),
         cursor=(0xFF8030, 0xFFE8A0)),
]

# the banks, and what the game calls them
B_SUR, B_FIELD, B_NUM, B_BOOM, B_WRONG, B_LOGO, B_TEXT, B_HEAD, B_SPR = 0, 1, 2, 10, 11, 12, 13, 14, 15


def theme_palette(t):
    """A theme's 256 colours as $0RGB, bank by bank."""
    pal = [[0x000000] * 16 for _ in range(16)]
    fr = t["frame"]
    pal[B_SUR][:8] = [t["bg"], t["motif"], t["twinkle"], fr[0], fr[1], fr[2], fr[3], t["panel"]]
    ca, cb = t["cover"]
    ga, gb = t["ground"]
    field = [mix(ca, 0x000000, 0.55),
             shade(ca, 1.35), ca, shade(ca, 0.72),
             shade(cb, 1.30), cb, shade(cb, 0.70),
             ga, gb, shade(ga, 0.80),
             0xFF7A6A, 0xE8261E, 0x8E0E0E,
             0x1C1C24, 0x7A7A86, 0xFFFFFF]
    pal[B_FIELD] = field
    for n, c in enumerate(NUMBERS):
        b = list(field)
        b[10], b[11], b[12] = shade(c, 1.45), c, shade(mix(ga, gb, 0.5), 0.72)
        pal[B_NUM + n] = b
    boom = list(field)
    boom[7], boom[8], boom[9] = 0xFF3A24, 0xFF3A24, 0xA0140C
    pal[B_BOOM] = boom
    wrong = list(field)
    wrong[9], wrong[10], wrong[11], wrong[12] = 0xFF2418, 0xD8D8D8, 0xA8A8A8, 0x6C6C6C
    pal[B_WRONG] = wrong
    pal[B_LOGO][:9] = [t["bg"]] + list(t["logo"]) + [mix(t["logo"][5], 0x000000, 0.7), 0x000000]
    # the text: 0 the panel it sits on, 1 the ink, 2 its shadow, 3 the
    # background for the font that sits on it; the HUD's icons after
    hud = [t["panel"], 0xFFFFFF, 0x000000, t["bg"], 0xE8261E, 0x1C1C24, 0x9A9AA6, 0xFFC830]
    pal[B_TEXT][:8] = hud
    pal[B_HEAD][:4] = [t["panel"], t["accent"], 0x000000, t["bg"]]
    cur = t["cursor"]
    pal[B_SPR][:5] = [0x000000, 0x100C08, mix(cur[0], 0x000000, 0.35), cur[0], cur[1]]
    return [rgb12(c) for b in pal for c in b]


# -------------------------------------------------------------- the cells
def grid(rows, key):
    """ASCII art to indices: `key` maps a character to an index, and
    anything not in it is left None -- the ground shows through."""
    return [[key.get(ch) for ch in r] for r in rows]


def covered(parity):
    """A raised cell: a highlight along the top and left, a shade along
    the bottom and right, a gloss in the corner and the outline in the
    four corner pixels where four cells meet."""
    hi, face, sh = (1, 2, 3) if parity == 0 else (4, 5, 6)
    px = [[face] * 16 for _ in range(16)]
    for i in range(16):
        px[0][i] = hi
        px[i][0] = hi
        px[15][i] = sh
        px[i][15] = sh
        px[14][max(1, i)] = sh if 1 <= i <= 14 else px[14][i]
        px[max(1, i)][14] = sh if 1 <= i <= 14 else px[i][14]
    for i in range(2, 6):
        px[2][i] = hi
        px[i][2] = hi
    px[3][3] = hi
    for x, y in ((0, 0), (15, 0), (0, 15), (15, 15)):
        px[y][x] = 0
    return px


def opened(parity):
    """A dug cell: flat ground and a sunken edge along the top and left."""
    g = 7 if parity == 0 else 8
    px = [[g] * 16 for _ in range(16)]
    for i in range(16):
        px[0][i] = 9
        px[i][0] = 9
    return px


# bold digits, eight by eleven, strokes three wide
DIGITS = {
    1: ["...###..", "..####..", ".#####..", "...###..", "...###..", "...###..",
        "...###..", "...###..", "...###..", ".#######", ".#######"],
    2: [".######.", "########", "###..###", ".....###", "....####", "..#####.",
        ".####...", "####....", "###.....", "########", "########"],
    3: [".######.", "########", "###..###", ".....###", "..#####.", "..#####.",
        ".....###", ".....###", "###..###", "########", ".######."],
    4: ["###..###", "###..###", "###..###", "###..###", "########", "########",
        ".....###", ".....###", ".....###", ".....###", ".....###"],
    5: ["########", "########", "###.....", "###.....", "#######.", "########",
        ".....###", ".....###", "###..###", "########", ".######."],
    6: [".######.", "########", "###.....", "###.....", "#######.", "########",
        "###..###", "###..###", "###..###", "########", ".######."],
    7: ["########", "########", ".....###", "....###.", "....###.", "...###..",
        "...###..", "..###...", "..###...", "..###...", "..###..."],
    8: [".######.", "########", "###..###", "###..###", ".######.", ".######.",
        "###..###", "###..###", "###..###", "########", ".######."],
}


def with_digit(parity, n):
    """A dug cell with its number: a light edge along the top of each
    stroke, the body, and a shadow cut into the ground below and right."""
    px = opened(parity)
    rows = DIGITS[n]
    ox, oy = 4, 2
    ink = {(x, y) for y, r in enumerate(rows) for x, ch in enumerate(r) if ch == "#"}
    for x, y in ink:
        px[oy + y + 1][ox + x + 1] = 12
    for x, y in ink:
        px[oy + y][ox + x] = 10 if (x, y - 1) not in ink else 11
    return px


FLAG = [
    "................",
    "................",
    ".........p......",
    ".......rrp......",
    ".....rrRRp......",
    "...rrRRRRp......",
    "..rRRRRRRp......",
    "...dRRRRRp......",
    ".....ddRRp......",
    ".......ddp......",
    ".........p......",
    ".........p......",
    ".......ppppp....",
    ".....ppppppppp..",
    "................",
    "................",
]
MINE = [
    "................",
    "................",
    ".......kk.......",
    "..k..kkkkkk..k..",
    "...kkkkkkkkkk...",
    "...kwwkkkkkkk...",
    "..kkwwkkkkkkkk..",
    ".kkkkkkkkkkkkkk.",
    ".kkkkkkkkkkkkkk.",
    "..kkkkkkkkkkgk..",
    "...kkkkkkkggk...",
    "...kkkkgggkkk...",
    "..k..kkkkkk..k..",
    ".......kk.......",
    "................",
    "................",
]
CROSS = [
    "................",
    "................",
    "..XX........XX..",
    "..XXX......XXX..",
    "...XXX....XXX...",
    "....XXX..XXX....",
    ".....XXXXXX.....",
    "......XXXX......",
    "......XXXX......",
    ".....XXXXXX.....",
    "....XXX..XXX....",
    "...XXX....XXX...",
    "..XXX......XXX..",
    "..XX........XX..",
    "................",
    "................",
]


def overlay(px, art, key):
    out = [r[:] for r in px]
    for y, row in enumerate(grid(art, key)):
        for x, v in enumerate(row):
            if v is not None:
                out[y][x] = v
    return out


FLAG_KEY = {"r": 10, "R": 11, "d": 12, "p": 13}
MINE_KEY = {"k": 13, "g": 14, "w": 15}


def cell_images():
    """Every 16 x 16 image, named, in the order the game numbers them;
    a parity pair is the light square then the dark."""
    out = []
    for p in (0, 1):
        out.append(("COVER", p, covered(p)))
    for p in (0, 1):
        out.append(("OPEN", p, opened(p)))
    for n in range(1, 9):
        for p in (0, 1):
            out.append(("DIGIT", p, with_digit(p, n)))
    for p in (0, 1):
        out.append(("FLAG", p, overlay(covered(p), FLAG, FLAG_KEY)))
    for p in (0, 1):
        out.append(("MINE", p, overlay(opened(p), MINE, MINE_KEY)))
    for p in (0, 1):
        out.append(("WRONG", p, overlay(overlay(covered(p), FLAG, FLAG_KEY), CROSS, {"X": 9})))
    return out


# -------------------------------------------------------- the surround
def frame_piece(kind):
    """An 8 x 8 piece of a bevelled, rounded frame. The profile runs from
    the outside in: dark, shine, light, the body three wide, dark."""
    prof = [3, 6, 5, 4, 4, 4, 3, 3]
    px = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            fx, fy = x + 0.5, y + 0.5
            if kind in ("T", "B", "L", "R"):
                d = {"T": fy, "B": 8 - fy, "L": fx, "R": 8 - fx}[kind]
                k = int(d)
            else:
                cx = 8.0 if "L" in kind else 0.0
                cy = 8.0 if "T" in kind else 0.0
                r = ((fx - cx) ** 2 + (fy - cy) ** 2) ** 0.5
                k = int(8 - r) if r <= 8 else -1
                if r < 0.001:
                    k = 7
            px[y][x] = prof[min(7, k)] if k >= 0 else 0
    return px


FRAME_ORDER = ["TL", "T", "TR", "L", "R", "BL", "B", "BR"]

# the background, 16 x 16: 0 the ground, 1 the motif, 2 the twinkle
BG = [
    "................",
    "....1...........",
    "...121..........",
    "....1...........",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "...........1....",
    "................",
    "................",
    "................",
    "................",
]

# the HUD's icons, 8 x 8 in the text bank: 1 white, 4 red, 5 black,
# 6 grey, 7 gold; 0 the panel
ICONS = {
    "ICON_MINE": ["...6....", ".6.66.6.", "..6166..", "6661666.",
                  "..6666..", ".6.66.6.", "...6....", "........"],
    "ICON_CLOCK": ["..7777..", ".711117.", "71115117", "71115117",
                   "71115557", "71111117", ".711117.", "..7777.."],
    "ICON_FLAG": ["...5444.", "...54444", "...5444.", "...5....",
                  "...5....", "...5....", "..555...", ".55555.."],
}


def glyph_px(g):
    """A packed 8 x 8 glyph to rows of 0 and 1."""
    return [[(g[y * 4 + x // 2] >> (4 if x % 2 == 0 else 0)) & 15 for x in range(8)] for y in range(8)]


def shadowed(g, ground):
    """A glyph with a shadow one pixel down and right, on a ground."""
    px = [[ground] * 8 for _ in range(8)]
    ink = {(x, y) for y in range(8) for x in range(8) if g[y][x]}
    for x, y in ink:
        if x + 1 < 8 and y + 1 < 8:
            px[y + 1][x + 1] = 2
    for x, y in ink:
        px[y][x] = 1
    return px


LOGO = "COOL SWEEPER"


def logo_letter(g):
    """A glyph doubled to 16 x 16: a gradient top to bottom in 1-6, an
    outline in 7 and a shadow in 8, on the ground 0."""
    ink = {(x, y) for y in range(8) for x in range(8) if g[y][x]}
    big = {(2 * x + dx, 2 * y + dy) for x, y in ink for dx in (0, 1) for dy in (0, 1)}
    px = [[0] * 16 for _ in range(16)]
    near = lambda x, y: any((x + a, y + b) in big for a in (-1, 0, 1) for b in (-1, 0, 1))  # noqa: E731
    for y in range(16):
        for x in range(16):
            if (x, y) in big:
                continue
            if near(x, y):
                px[y][x] = 7
            elif (x - 2, y - 2) in big:
                px[y][x] = 8
    for x, y in big:
        px[y][x] = 1 + min(5, y * 6 // 14)
    return px


# the cursor: one corner of four, a sprite of 16 x 16 at the raster's
# own resolution; the game flips it for the other three
CURSOR = [
    "111111111111....",
    "144444444441....",
    "143333333321....",
    "14322222221.....",
    "1432111111......",
    "14321...........",
    "14321...........",
    "14321...........",
    "14321...........",
    "14321...........",
    "1421............",
    "1421............",
    "111.............",
    "................",
    "................",
    "................",
]


def pack(px):
    out = []
    for r in px:
        for i in range(0, len(r), 2):
            out.append((r[i] << 4) | r[i + 1])
    return out


def quarters(px):
    """A 16 x 16 image as its four 8 x 8 tiles: top left, top right,
    bottom left, bottom right."""
    return [pack([r[ox:ox + 8] for r in px[oy:oy + 8]]) for oy in (0, 8) for ox in (0, 8)]


def tiles():
    """Every tile as (name or '', 32 bytes), in the game's numbering."""
    out = []
    names = set()
    for name, p, img in cell_images():
        first = name not in names
        names.add(name)
        for i, q in enumerate(quarters(img)):
            out.append(("T_" + name if first and i == 0 else "", q))
    for i, q in enumerate(quarters(grid(BG, {".": 0, "1": 1, "2": 2}))):
        out.append(("T_BG" if i == 0 else "", q))
    for k in FRAME_ORDER:
        out.append(("T_FR_" + k, pack(frame_piece(k))))
    out.append(("T_SOLID", pack([[7] * 8 for _ in range(8)])))
    for k in ("ICON_MINE", "ICON_CLOCK", "ICON_FLAG"):
        out.append(("T_" + k, pack([[int(ch) if ch != "." else 0 for ch in r] for r in ICONS[k]])))
    _, glyphs = mkmscool.font(mkmscool.load(mkmscool.FONTSHEET))
    order = mkmscool.FONT
    for i, ch in enumerate(order):
        out.append(("T_FONT" if i == 0 else "", pack(shadowed(glyph_px(glyphs[ch]), 0))))
    for i, ch in enumerate(order):
        out.append(("T_BFONT" if i == 0 else "", pack(shadowed(glyph_px(glyphs[ch]), 3))))
    letters = "".join(sorted(set(LOGO) - {" "}, key=LOGO.index))
    for i, ch in enumerate(letters):
        for j, q in enumerate(quarters(logo_letter(glyph_px(glyphs[ch])))):
            out.append(("T_LOGO" if i == 0 and j == 0 else "", q))
    assert len(out) <= 256, len(out)
    return out, order, letters


# -------------------------------------------------------------- the music
# A tune is five tracks of eighths, one bar of eight a line:
#   lead, harmony, bass, arpeggio -- a note is its letter, a # or a b,
#   and its octave (A4 is 440 Hz); `-` holds the note before, `.` lets
#   it go.
#   drums -- k a kick, s a snare, h a closed hat, o an open one, c a
#   crash; `-` nothing.
# Frames an eighth, then whether it goes round again.

TITLE = dict(step=14, loop=True, parts=dict(
    # D major. A: D Bm G A | D F#m G-A D.  B: G A F#m Bm | Em A Bm-G A
    lead="""
        A4 -  D5 -  F#5 - E5 D5 | F#5 - - - D5 - B4 - | G4 - B4 - D5 - E5 F#5 | E5 - - - C#5 - A4 -
        A4 -  D5 -  F#5 - A5 G5 | F#5 - E5 - C#5 - A4 - | B4 - D5 - C#5 - E5 - | D5 - - - - - . .
        B5 - A5 - G5 - D5 -     | E5 - F#5 - G5 - A5 - | A5 - - - F#5 - C#5 - | D5 - F#5 - B5 - A5 -
        G5 - F#5 - E5 - B4 -    | C#5 - E5 - A5 - G5 - | F#5 - D5 - B4 - D5 - | E5 - - - C#5 - B4 C#5
    """,
    harm="""
        F#4 - - - A4 - - - | D4 - - - F#4 - - - | D4 - - - G4 - - - | C#4 - - - E4 - - -
        F#4 - - - A4 - - - | C#4 - - - F#4 - - - | D4 - - - E4 - - - | F#4 - - - - - . .
        D5 - - - G4 - - -  | C#5 - - - E5 - - - | C#5 - - - A4 - - - | F#4 - - - D5 - - -
        B4 - - - G4 - - -  | A4 - - - C#5 - - - | D5 - - - G4 - - - | C#5 - - - A4 - - -
    """,
    bass="""
        D3 . A2 . D3 . A2 . | B2 . F#2 . B2 . F#2 . | G2 . D3 . G2 . D3 . | A2 . E3 . A2 . E3 .
        D3 . A2 . D3 . A2 . | F#2 . C#3 . F#2 . C#3 . | G2 . D3 . A2 . E3 . | D3 . A2 . D3 - - .
        G2 . D3 . G2 . D3 . | A2 . E3 . A2 . E3 . | F#2 . C#3 . F#2 . C#3 . | B2 . F#2 . B2 . F#2 .
        E2 . B2 . E2 . B2 . | A2 . E3 . A2 . C#3 . | B2 . F#2 . G2 . D3 . | A2 . E3 . A2 . G2 .
    """,
    arp="""
        . A4 . F#4 . A4 . F#4 | . F#4 . D4 . F#4 . D4 | . B4 . G4 . B4 . G4 | . C#5 . A4 . E4 . A4
        . A4 . F#4 . A4 . F#4 | . A4 . F#4 . C#5 . A4 | . B4 . G4 . C#5 . A4 | . A4 . F#4 . D4 . .
        G5 B5 D6 B5 G5 B5 D6 B5 | A5 C#6 E6 C#6 A5 C#6 E6 C#6 | F#5 A5 C#6 A5 F#5 A5 C#6 A5 | F#5 B5 D6 B5 F#5 B5 D6 B5
        E5 G5 B5 G5 E5 G5 B5 G5 | E5 A5 C#6 A5 E5 A5 C#6 A5 | F#5 B5 D6 B5 G5 B5 D6 B5 | E5 A5 C#6 E6 C#6 A5 E5 C#5
    """,
    drums="""
        c - h - s - h - | k - h - s - h - | k - h - s - h - | k - h - s - h -
        k - h - s - h - | k - h - s - h - | k - h - s - h - | k - h - s - s s
        k - h k s - h h | k - h k s - h h | k - h k s - h h | k - h k s - h h
        k - h k s - h h | k - h k s - h h | k - h k s - h o | k - s - s s s s
    """))

EASY = dict(step=16, loop=True, parts=dict(
    # G major, unhurried. A: G Em C D | G Em Am-D G.  B: C G Am Em | C G Am D
    lead="""
        D5 - B4 - G4 - B4 D5 | E5 - - - B4 - G4 - | C5 - E5 - G5 - E5 C5 | D5 - - - A4 - F#4 -
        G4 - B4 - D5 - G5 -  | F#5 - E5 - D5 - B4 - | C5 - A4 - D5 - F#5 - | G5 - - - - - . .
        E5 - D5 - C5 - G4 -  | B4 - D5 - G5 - F#5 - | E5 - - - C5 - A4 - | B4 - - - G4 - E4 -
        G4 - C5 - E5 - G5 -  | D5 - - - B4 - D5 - | C5 - E5 - A5 - G5 - | F#5 - - - A5 - F#5 -
    """,
    harm="""
        B3 - - - D4 - - - | G4 - - - E4 - - - | E4 - - - G4 - - - | F#4 - - - D4 - - -
        D4 - - - B3 - - - | A4 - - - G4 - - - | E4 - - - F#4 - - - | B4 - - - - - . .
        G4 - - - E4 - - - | G4 - - - B4 - - - | A4 - - - E4 - - - | G4 - - - B3 - - -
        E4 - - - C5 - - - | B4 - - - G4 - - - | E4 - - - C5 - - - | D5 - - - C5 - - -
    """,
    bass="""
        G2 - - - D3 - - - | E2 - - - B2 - - - | C3 - - - G2 - - - | D3 - - - A2 - - -
        G2 - - - B2 - - - | E2 - - - G2 - - - | A2 - - - D3 - - - | G2 - - - D3 - C3 B2
        C3 - - - G2 - - - | B2 - - - G2 - - - | A2 - - - E2 - - - | E2 - - - G2 - - -
        C3 - - - E3 - - - | B2 - - - D3 - - - | A2 - - - C3 - - - | D3 - - - F#2 - A2 -
    """,
    arp="""
        G3 B3 D4 B3 G3 B3 D4 B3 | E3 G3 B3 G3 E3 G3 B3 G3 | C4 E4 G4 E4 C4 E4 G4 E4 | D4 F#4 A4 F#4 D4 F#4 A4 F#4
        G3 B3 D4 B3 G3 B3 D4 B3 | E3 G3 B3 G3 E3 G3 B3 G3 | A3 C4 E4 C4 D4 F#4 A4 F#4 | G3 B3 D4 G4 D4 B3 G3 .
        C4 E4 G4 E4 C4 E4 G4 E4 | B3 D4 G4 D4 B3 D4 G4 D4 | A3 C4 E4 C4 A3 C4 E4 C4 | G3 B3 E4 B3 G3 B3 E4 B3
        C4 E4 G4 E4 C4 E4 G4 E4 | B3 D4 G4 D4 B3 D4 G4 D4 | A3 C4 E4 C4 A3 C4 E4 C4 | D4 F#4 A4 F#4 D4 F#4 A4 C5
    """,
    drums="""
        k - h - - - h - | k - h - - - h - | k - h - - - h - | k - h - - - h -
        k - h - - - h - | k - h - - - h - | k - h - - - h - | k - h - s - h h
        k - h - s - h - | k - h - s - h - | k - h - s - h - | k - h - s - h -
        k - h - s - h - | k - h - s - h - | k - h - s - h - | k - h - s - h h
    """))

MEDIUM = dict(step=13, loop=True, parts=dict(
    # E minor, uneasy. A: Em C Am B7 | Em C D B.  B: Am Em C B7 | Am Em C B7
    lead="""
        E5 - G5 - F#5 E5 D#5 E5 | G5 - - E5 - - C5 - | A5 - C6 - B5 A5 G5 A5 | F#5 - - - D#5 - B4 -
        E5 - G5 - B5 - A5 G5    | E5 - - G5 - - C6 - | D6 - C6 B5 A5 - F#5 - | B5 - - - D#5 - F#5 -
        C6 - B5 - A5 - E5 -     | G5 - F#5 - E5 - B4 - | C5 - E5 - G5 - C6 - | B5 - - - A5 - F#5 -
        A5 - C6 - E6 - C6 -     | B5 - G5 - E5 - G5 - | E5 - G5 C6 B5 - G5 - | F#5 - D#5 - B4 - D#5 F#5
    """,
    harm="""
        B4 - - - G4 - - - | E4 - - - G4 - - - | E4 - - - C5 - - - | D#4 - - - A4 - - -
        G4 - - - B4 - - - | G4 - - - E4 - - - | F#4 - - - A4 - - - | D#4 - - - F#4 - - -
        E4 - - - C5 - - - | B4 - - - G4 - - - | G4 - - - E4 - - - | D#4 - - - A4 - - -
        C5 - - - A4 - - - | G4 - - - B4 - - - | G4 - - - E4 - - - | A4 - - - F#4 - - -
    """,
    bass="""
        E2 E2 E2 E2 B2 B2 E3 B2 | C3 C3 C3 C3 G2 G2 C3 G2 | A2 A2 A2 A2 E2 E2 A2 E2 | B2 B2 B2 B2 F#2 F#2 B2 F#2
        E2 E2 E2 E2 B2 B2 E3 B2 | C3 C3 C3 C3 G2 G2 C3 G2 | D3 D3 D3 D3 A2 A2 D3 A2 | B2 B2 B2 B2 F#2 F#2 D#3 F#2
        A2 A2 A2 A2 E2 E2 A2 E2 | E2 E2 E2 E2 B2 B2 E3 B2 | C3 C3 C3 C3 G2 G2 C3 G2 | B2 B2 B2 B2 F#2 F#2 B2 F#2
        A2 A2 A2 A2 E2 E2 A2 E2 | E2 E2 E2 E2 B2 B2 E3 B2 | C3 C3 C3 C3 G2 G2 C3 G2 | B2 B2 A2 A2 G2 G2 F#2 F#2
    """,
    arp="""
        . B5 . E6 . G5 . B5 | . G5 . C6 . E6 . C6 | . A5 . E6 . C6 . E6 | . F#5 . B5 . D#6 . A5
        . B5 . E6 . G5 . B5 | . G5 . C6 . E6 . G5 | . A5 . D6 . F#6 . D6 | . B5 . D#6 . F#6 . B5
        . E6 . C6 . A5 . E5 | . G5 . B5 . E6 . B5 | . E6 . C6 . G5 . E5 | . D#6 . B5 . F#5 . A5
        . C6 . E6 . A6 . E6 | . B5 . G5 . E5 . G5 | . G5 . C6 . E6 . C6 | . F#5 . A5 . B5 . D#6
    """,
    drums="""
        c h s h k h s h | k h s h k h s h | k h s h k h s h | k h s h k h s h
        k h s h k h s h | k h s h k h s h | k h s h k h s h | k h s h k s s s
        k h s h k h s h | k h s h k h s h | k h s h k h s h | k h s h k h s o
        k h s h k h s h | k h s h k h s h | k h s h k h s h | k s k s s s s s
    """))

HARD = dict(step=11, loop=True, parts=dict(
    # A minor, headlong. A: Am F G E | Am F Dm-E Am-E.  B: F G Em Am | Dm E F-G E
    lead="""
        A5 - E5 - A5 B5 C6 B5   | A5 - F5 - C5 - F5 - | G5 - D5 - G5 A5 B5 A5 | G#5 - E5 - B4 - G#4 -
        A4 C5 E5 A5 C6 - B5 A5  | C6 - A5 - F5 - A5 C6 | D6 - A5 F5 E5 - G#5 B5 | A5 - - - E5 - G#5 -
        C6 - C6 - A5 - F5 A5    | B5 - B5 - G5 - D5 G5 | E6 - D6 - B5 - G5 - | C6 - B5 - A5 - E5 -
        F5 - A5 - D6 - F6 -     | E6 - - - D6 - B5 G#5 | A5 - C6 - B5 - D6 - | E6 - D6 - B5 - G#5 -
    """,
    harm="""
        E4 - - - A4 - - - | C4 - - - F4 - - - | D4 - - - G4 - - - | E4 - - - G#4 - - -
        E4 - - - A4 - - - | F4 - - - A4 - - - | F4 - - - G#4 - - - | E4 - - - D4 - - -
        A4 - - - C5 - - - | B4 - - - G4 - - - | G4 - - - B4 - - - | E4 - - - A4 - - -
        A4 - - - F4 - - - | G#4 - - - B4 - - - | C5 - - - D5 - - - | G#4 - - - B4 - - -
    """,
    bass="""
        A2 A2 A3 A2 A2 A2 A3 A2 | F2 F2 F3 F2 F2 F2 F3 F2 | G2 G2 G3 G2 G2 G2 G3 G2 | E2 E2 E3 E2 G#2 G#2 B2 G#2
        A2 A2 A3 A2 A2 A2 A3 A2 | F2 F2 F3 F2 F2 F2 F3 F2 | D3 D3 D2 D3 E2 E2 E3 E2 | A2 A2 A3 A2 E2 E2 G#2 B2
        F2 F2 F3 F2 F2 F2 F3 F2 | G2 G2 G3 G2 G2 G2 G3 G2 | E2 E2 E3 E2 E2 E2 E3 E2 | A2 A2 A3 A2 A2 A2 A3 A2
        D3 D3 D2 D3 D3 D3 D2 D3 | E2 E2 E3 E2 E2 E2 E3 E2 | F2 F2 F3 F2 G2 G2 G3 G2 | E2 E2 E3 E2 G#2 G#2 B2 G#2
    """,
    arp="""
        A4 C5 E5 C5 A4 C5 E5 C5 | F4 A4 C5 A4 F4 A4 C5 A4 | G4 B4 D5 B4 G4 B4 D5 B4 | E4 G#4 B4 G#4 E4 G#4 B4 G#4
        A4 C5 E5 C5 A4 C5 E5 C5 | F4 A4 C5 A4 F4 A4 C5 A4 | D4 F4 A4 F4 E4 G#4 B4 G#4 | A4 C5 E5 C5 E4 G#4 B4 G#4
        F4 A4 C5 F5 C5 A4 F4 A4 | G4 B4 D5 G5 D5 B4 G4 B4 | E4 G4 B4 E5 B4 G4 E4 G4 | A4 C5 E5 A5 E5 C5 A4 C5
        D4 F4 A4 D5 A4 F4 D4 F4 | E4 G#4 B4 E5 B4 G#4 E4 G#4 | F4 A4 C5 A4 G4 B4 D5 B4 | E4 G#4 B4 E5 G#5 E5 B4 G#4
    """,
    drums="""
        c h s h k k s h | k h s h k k s h | k h s h k k s h | k h s h k k s h
        k h s h k k s h | k h s h k k s h | k h s h k k s h | k h s h s s s s
        k h s h k k s h | k h s h k k s h | k h s h k k s h | k h s h k k s o
        k h s h k k s h | k h s h k k s h | k h s h k k s h | k s s k s s s s
    """))

WIN = dict(step=6, loop=False, parts=dict(
    lead="C5 E5 G5 C6 - B5 C6 D6 | E6 - - - - - - .",
    harm=".  .  .  E5 - D5 E5 F5 | G5 - - - - - - .",
    bass="C3 - - - - G2 - - | C3 - - - - - - .",
    arp=". . . . . . . . | C6 E6 G6 C7 G6 E6 C6 .",
    drums="k - - k s - - - | c - - - - - - -"))

LOSE = dict(step=10, loop=False, parts=dict(
    lead="E5 - - D#5 - - D5 - | - C#5 - - - - - .",
    harm="C5 - - B4 - - Bb4 - | - A4 - - - - - .",
    bass="A2 - - G#2 - - G2 - | - F#2 - - - - - .",
    arp=". . . . . . . . | . . . . . . . .",
    drums="k - - k - - k - | - s - - - - - -"))

TUNES = [("title", TITLE), ("easy", EASY), ("medium", MEDIUM), ("hard", HARD), ("win", WIN), ("lose", LOSE)]
TRACKS = ["lead", "harm", "bass", "arp", "drums"]
DRUMS = {"-": None, "k": 3, "s": 2, "h": 1, "o": 4, "c": 5}
LOW_MIDI = 24                          # the pitch table starts at C1
HIGH_MIDI = 108


def midi_of(tok):
    """C4 is 60: a letter, a # or a b, and the octave."""
    step = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[tok[0]]
    rest = tok[1:]
    if rest[0] == "#":
        step += 1
        rest = rest[1:]
    elif rest[0] == "b":
        step -= 1
        rest = rest[1:]
    return 12 * (int(rest) + 1) + step


def track_steps(name, text):
    """A track's eighths: a MIDI note, "hold", "off", or for the drums a
    drum number or None. Each bar must be eight."""
    bars = [b.split() for b in text.replace("\n", "|").split("|") if b.strip()]
    for i, b in enumerate(bars):
        assert len(b) == 8, (name, i + 1, b)
    toks = [t for b in bars for t in b]
    if name == "drums":
        return [DRUMS[t] for t in toks]
    out = []
    for t in toks:
        if t == "-":
            out.append("hold")
        elif t == ".":
            out.append("off")
        else:
            m = midi_of(t)
            assert LOW_MIDI <= m < HIGH_MIDI, (name, t)
            out.append(m)
    return out


def tune_stream(t):
    """One tune as the player reads it: frames an eighth, then for each
    eighth a mask -- bit n for track n that has something new -- and the
    bytes it names: a note as MIDI less 23 (0 lets the voice go), a drum
    as its number. $80 ends a tune that goes round; $C0 one that stops."""
    tracks = [track_steps(n, t["parts"][n]) for n in TRACKS]
    n = len(tracks[0])
    assert all(len(tr) == n for tr in tracks), [len(tr) for tr in tracks]
    out = [t["step"]]
    for i in range(n):
        mask, data = 0, []
        for c, tr in enumerate(tracks):
            v = tr[i]
            if c == 4:
                if v is not None:
                    mask |= 1 << c
                    data.append(v)
            elif v == "off":
                mask |= 1 << c
                data.append(0)
            elif v != "hold":
                mask |= 1 << c
                data.append(v - LOW_MIDI + 1)
        out += [mask] + data
    out.append(0x80 if t["loop"] else 0xC0)
    return out, n


def note_incs():
    """The sound engine's phase increment for every note of the table:
    f / 0.4993 Hz (04-system.md section 4.4)."""
    return [round(440.0 * 2 ** ((m - 69) / 12.0) / 0.4993) for m in range(LOW_MIDI, HIGH_MIDI)]


# ------------------------------------------------------------ the file
def act(ts, order, letters, tunes):
    lines = [
        "; COOL SWEEPER's art and music, written by tools/mkcoolsw.py -- run it,",
        "; do not edit this. A tile is 8 x 8 at 4 bpp, high nibble the left",
        "; pixel; a cell's picture is four of them, and T_COVER + 4 is the",
        "; dark square's version of T_COVER.",
        "",
    ]
    for i, (name, _) in enumerate(ts):
        if name:
            lines.append("CONST %s = %d" % (name, i))
    lines.append("CONST N_TILES = %d" % len(ts))
    lines.append("CONST N_FONT = %d" % len(order))
    lines.append("; tile T_FONT + i, and T_BFONT + i, is character i of this")
    lines.append('BYTE ARRAY fontmap = "%s"' % order)
    lines.append("; logo letter i is the four tiles from T_LOGO + 4i")
    lines.append('BYTE ARRAY logomap = "%s"' % letters)
    lines.append("BYTE ARRAY sw_tiles(%d) = [" % (32 * len(ts)))
    for _, b in ts:
        lines.append("  " + " ".join(str(x) for x in b))
    lines.append("]")
    lines.append("")
    lines.append("; the cursor's corner, a 16 x 16 sprite")
    lines.append("BYTE ARRAY cursor_spr(128) = [")
    cur = pack(grid(CURSOR, {".": 0, "1": 1, "2": 2, "3": 3, "4": 4}))
    for i in range(0, 128, 32):
        lines.append("  " + " ".join(str(x) for x in cur[i:i + 32]))
    lines.append("]")
    lines.append("")
    lines.append("; the three themes, 256 colours each: %s" % ", ".join(t["name"] for t in THEMES))
    lines.append("CARD ARRAY theme_pal(%d) = [" % (256 * len(THEMES)))
    for t in THEMES:
        pal = theme_palette(t)
        lines.append("  ; %s" % t["name"])
        for b in range(16):
            lines.append("  " + " ".join("$%03X" % c for c in pal[b * 16:(b + 1) * 16]))
    lines.append("]")
    lines.append("")
    lines.append("; eight steps of a pulse for each theme: the cursor's bright colour")
    lines.append("; (bank 15, entry 3) and the background's twinkle (bank 0, entry 2)")
    tri = [0, 0.25, 0.5, 0.75, 1, 0.75, 0.5, 0.25]
    lines.append("CARD ARRAY glow_ramp(%d) = [" % (8 * len(THEMES)))
    for t in THEMES:
        lines.append("  " + " ".join("$%03X" % rgb12(mix(t["cursor"][0], t["cursor"][1], k)) for k in tri))
    lines.append("]")
    lines.append("CARD ARRAY twinkle_ramp(%d) = [" % (8 * len(THEMES)))
    for t in THEMES:
        lines.append("  " + " ".join("$%03X" % rgb12(mix(t["motif"], t["twinkle"], k)) for k in tri))
    lines.append("]")
    lines.append("")
    lines.append("; a note's increment, from MIDI %d up" % LOW_MIDI)
    incs = note_incs()
    lines.append("CARD ARRAY note_inc(%d) = [" % len(incs))
    for i in range(0, len(incs), 12):
        lines.append("  " + " ".join(str(x) for x in incs[i:i + 12]))
    lines.append("]")
    lines.append("")
    lines.append("; the tunes: title, then one for each level, then the two endings")
    off, blob = [], []
    for (name, t), (stream, n) in zip(TUNES, tunes):
        lines.append(";   %-7s %2d eighths of %2d frames, %4d frames round, %4d bytes"
                     % (name, n, t["step"], n * t["step"], len(stream)))
        lines.append("CONST TUNE_%s = %d" % (name.upper(), len(off)))
        off.append(len(blob))
        blob += stream
    lines.append("CARD ARRAY tune_off(%d) = [%s]" % (len(off), " ".join(str(x) for x in off)))
    lines.append("BYTE ARRAY tune_data(%d) = [" % len(blob))
    for i in range(0, len(blob), 24):
        lines.append("  " + " ".join(str(x) for x in blob[i:i + 24]))
    lines.append("]")
    return "\n".join(lines) + "\n"


def preview(ts):
    """Each theme's cells, frame and cursor at four times over, and a
    little field drawn with them."""
    from PIL import Image
    S = 3
    W, H = 3 * (16 * 14 + 16) * S, (16 * 7 + 24) * S
    im = Image.new("RGB", (W, H), (20, 20, 20))
    rgb = lambda v: (((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17)   # noqa: E731

    def tile(i, bank, pal, ox, oy):
        b = ts[i][1]
        for y in range(8):
            for x in range(8):
                v = b[y * 4 + x // 2]
                ix = (v >> 4) if x % 2 == 0 else (v & 15)
                c = rgb(pal[bank * 16 + ix])
                for dy in range(S):
                    for dx in range(S):
                        im.putpixel((ox + x * S + dx, oy + y * S + dy), c)
    idx = {n: i for i, (n, _) in enumerate(ts) if n}
    field = [
        "CCCC1..1CCCC",
        "CCF21.13CCCC",
        "C2211.1F2CCC",
        "C1..........",
        "C1.12221.1M1",
        "CW.1FFF1.111",
    ]
    for k, t in enumerate(THEMES):
        pal = theme_palette(t)
        X0 = k * (16 * 14 + 16) * S + 8 * S
        for y, row in enumerate(field):
            for x, ch in enumerate(row):
                p = (x + y) & 1
                if ch == "C":
                    base, bank = idx["T_COVER"] + 4 * p, B_FIELD
                elif ch == "F":
                    base, bank = idx["T_FLAG"] + 4 * p, B_FIELD
                elif ch == "M":
                    base, bank = idx["T_MINE"] + 4 * p, B_BOOM
                elif ch == "W":
                    base, bank = idx["T_WRONG"] + 4 * p, B_WRONG
                elif ch == ".":
                    base, bank = idx["T_OPEN"] + 4 * p, B_FIELD
                else:
                    n = int(ch)
                    base, bank = idx["T_DIGIT"] + 8 * (n - 1) + 4 * p, B_NUM + n - 1
                for q in range(4):
                    tile(base + q, bank, pal, X0 + (x * 16 + 8 * (q & 1)) * S, 8 * S + (y * 16 + 8 * (q >> 1)) * S)
        for n in range(8):
            base = idx["T_DIGIT"] + 8 * n
            for q in range(4):
                tile(base + q, B_NUM + n, pal, X0 + (n * 16 + 8 * (q & 1)) * S,
                     (8 + 6 * 16 + 4) * S + 8 * (q >> 1) * S)
    im.save(PREVIEW)


def main():
    ts, order, letters = tiles()
    tunes = [tune_stream(t) for _, t in TUNES]
    text = act(ts, order, letters, tunes)
    if "--check" in sys.argv:
        have = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if have != text:
            print("  %s is stale: run python tools/mkcoolsw.py" % os.path.relpath(OUT, ROOT))
            return 1
        print("ok -- the art file is current")
        return 0
    if not os.path.isdir(ART):
        os.makedirs(ART)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(text)
    preview(ts)
    print("  %d tiles, %d themes, %d tunes in %d bytes" % (len(ts), len(THEMES), len(TUNES),
                                                          sum(len(s) for s, _ in tunes)))
    print("  wrote %s and %s" % (os.path.relpath(OUT, ROOT), os.path.relpath(PREVIEW, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
