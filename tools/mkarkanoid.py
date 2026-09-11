#!/usr/bin/env python3
"""Arkanoid's art, rounds and music, out of the ripped arcade sheets.

    python tools/mkarkanoid.py             write assets/arkanoid/arkanoid_art.act and a preview
    python tools/mkarkanoid.py --check     the art file is current
    python tools/mkarkanoid.py --boxes S   every shape the finder sees on sheet S, band by band

**The art is the original's**, as Ms. Cool-Man's is (tools/mkmscool.py):
`assets/arkanoid/` holds sheets ripped from the arcade Arkanoid (Taito,
1986) -- The Spriters Resource's arcade sheets for the fields, the
blocks, the power-ups, the enemies, DOH and the intro mothership, and
its fuller "Arkanoid (World, older)" Vaus sheet -- and the VGM rips of
the board's own music (VGMPF's Arkanoid (ARC) pack, the YM2149 register
log at 1.5 MHz). This generator turns them into
`assets/arkanoid/arkanoid_art.act`, which demos/arkanoid.parts names as
the part the game compiles behind.

**The rounds are the arcade's**, read off StrategyWiki's walkthrough
(`Arkanoid/Walkthrough`), whose 32 round pictures are the arcade's own
224 x 256 frames. Each brick cell was read by its face: 13 columns of
16 pixels from x 8, rows of 8 from y 24 (the playfield's top, under the
frame at 16-23), a cell a brick when its right and bottom edges are the
black line every brick has and 40 of the 65 pixels inside are one brick
colour. That reads round 1 as silver, red, yellow, blue, magenta,
green, which is round 1. One cell needed a second look: round 5's
top-left antenna tip reads empty because a cone and its shadow sit on
it in that frame, and it is put back -- the invader is symmetric, and
the cone's pixels are measured over that cell (x 54-64, y 29-38).

**The enemies follow the round.** Where a frame caught an enemy, its
colours say which: cones on rounds 5, 9, 13, 17, pyramids never caught,
molecules on 3, 7, 11, 15, 19, 23, 27, cubes on 16, 28, 32 -- the round's
background and its enemy are the same choice, (round - 1) mod 4: blue
and cones, green and pyramids, circuit and molecules, grey and cubes.

**The font is the arcade's, where the arcade shows it.** The title
screen and the play screen's top line show 25 glyphs; 23 of them are the
Namco font Ms. Cool-Man already has, pixel for pixel, with the digits
one row higher than Namco's so that they sit on the letters' line. E and
L are not: Taito's are a pixel wider, to the left. So the observed
glyphs are used as observed, and only the ones no screenshot shows fall
back to the Namco font -- listed by `--fonts`, never silently.
"""

import gzip
import io
import os
import struct
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "assets", "arkanoid")
OUT = os.path.join(ART, "arkanoid_art.act")
PREVIEW = os.path.join(ART, "preview.png")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkmscool  # noqa: E402  the Namco font, and q4

q4 = mkmscool.q4

# The sheets: file, and the colours that are the sheet's own background
# rather than art (a transparent pixel is background everywhere).
SHEETS = {
    "fields": ("arcade_fields.png", ()),
    "blocks": ("arcade_blocks.png", ()),
    "powerups": ("arcade_powerups.png", ((255, 255, 255),)),
    "enemies": ("arcade_enemies.png", ((171, 160, 0), (91, 85, 0), (146, 39, 143))),
    "vaus": ("arcade_vaus_world.png", ((132, 156, 149),)),
    "doh": ("arcade_doh.png", ()),
    "ship": ("arcade_ship.png", ()),
}


class Sheet:
    def __init__(self, name):
        from PIL import Image
        fn, bg = SHEETS[name]
        path = os.path.join(ART, fn)
        if not os.path.exists(path):
            sys.exit("%s is missing: the ripped sheets (see the docstring)" % os.path.relpath(path, ROOT))
        im = Image.open(path).convert("RGBA")
        self.name = name
        self.w, self.h = im.size
        self.px = im.load()
        self.bg = set(bg)

    def at(self, x, y):
        """The pixel's colour, or None where the sheet is background."""
        c = self.px[x, y]
        return None if c[3] == 0 or c[:3] in self.bg else c[:3]

    def components(self, box=None):
        """Every 8-connected shape inside box (x0, y0, x1, y1): (x, y, w, h, pixels)."""
        x0, y0, x1, y1 = box or (0, 0, self.w, self.h)
        seen = set()
        out = []
        for y in range(y0, y1):
            for x in range(x0, x1):
                if (x, y) in seen or self.at(x, y) is None:
                    continue
                stack = [(x, y)]
                seen.add((x, y))
                bx0 = bx1 = x
                by0 = by1 = y
                n = 0
                while stack:
                    a, b = stack.pop()
                    n += 1
                    bx0, bx1, by0, by1 = min(bx0, a), max(bx1, a), min(by0, b), max(by1, b)
                    for da in (-1, 0, 1):
                        for db in (-1, 0, 1):
                            c, d = a + da, b + db
                            if x0 <= c < x1 and y0 <= d < y1 and (c, d) not in seen and self.at(c, d) is not None:
                                seen.add((c, d))
                                stack.append((c, d))
                out.append((bx0, by0, bx1 - bx0 + 1, by1 - by0 + 1, n))
        return out


def bands(comps):
    """Shapes grouped into horizontal bands whose rows overlap."""
    out = []
    for c in sorted(comps, key=lambda c: (c[1], c[0])):
        if out and c[1] <= out[-1][1]:
            out[-1][1] = max(out[-1][1], c[1] + c[3] - 1)
            out[-1][2].append(c)
        else:
            out.append([c[1], c[1] + c[3] - 1, [c]])
    return out


def show_boxes(name):
    s = Sheet(name)
    for y0, y1, cs in bands(s.components()):
        print("y %3d-%3d: %s" % (y0, y1, "  ".join("%d,%d %dx%d" % c[:4] for c in sorted(cs))))


# ------------------------------------------------------------------ rounds
# The 32 layouts, 13 columns, row 0 at y 24 (tile row 1 on this machine):
# W white O orange C cyan G green R red B blue M magenta Y yellow
# S silver X gold, '.' no brick. Read off StrategyWiki's arcade frames
# as the docstring says; round 5's row 2 carries the one correction.
ROUNDS = [
    "..../..../..../..../SSSSSSSSSSSSS/RRRRRRRRRRRRR/YYYYYYYYYYYYY/BBBBBBBBBBBBB/MMMMMMMMMMMMM/GGGGGGGGGGGGG",
    "..../..../W............/WO.........../WOC........../WOCG........./WOCGR......../WOCGRB......./WOCGRBM....../"
    "WOCGRBMY...../WOCGRBMYW..../WOCGRBMYWO.../WOCGRBMYWOC../WOCGRBMYWOCG./SSSSSSSSSSSSR",
    "..../..../..../GGGGGGGGGGGGG/..../WWWXXXXXXXXXX/..../RRRRRRRRRRRRR/..../XXXXXXXXXXWWW/..../MMMMMMMMMMMMM/..../"
    "BBBXXXXXXXXXX/..../CCCCCCCCCCCCC/..../XXXXXXXXXXCCC",
    "..../..../..../..../.OCGSB.YWOCG./.CGSBM.WOCGS./.GSBMY.OCGSB./.SBMYW.CGSBM./.BMYWO.GSBMY./.MYWOC.SBMYW./"
    ".YWOCG.BMYWO./.WOCGS.MYWOC./.OCGSB.YWOCG./.CGSBM.WOCGS./.GSBMY.OCGSB./.SBMYW.CGSBM./.BMYWO.GSBMY./.MYWOC.SBMYW.",
    "..../..../...Y.....Y.../...Y.....Y.../....Y...Y..../....Y...Y..../...SSSSSSS.../...SSSSSSS.../..SSRSSSRSS../"
    "..SSRSSSRSS../.SSSSSSSSSSS./.SSSSSSSSSSS./.SSSSSSSSSSS./.S.SSSSSSS.S./.S.S.....S.S./.S.S.....S.S./"
    "....SS.SS..../....SS.SS....",
    "..../..../..../..../B.R.G.C.G.R.B/B.R.G.C.G.R.B/B.R.G.C.G.R.B/B.R.G.C.G.R.B/B.R.G.C.G.R.B/B.XOXOXOXOX.B/"
    "B.R.G.C.G.R.B/B.R.G.C.G.R.B/B.R.G.C.G.R.B/B.R.G.C.G.R.B/O.O.X.O.X.O.O/B.R.G.C.G.R.B",
    "..../..../..../..../.....YYM...../....YYMMB..../...YYMMBBR.../...YMMBBRR.../..YMMBBRRGG../..MMBBRRGGC../"
    "..MBBRRGGCC../..BBRRGGCCO../..BRRGGCCOO../..RRGGCCOOW../...GGCCOOW.../...GCCOOWW.../....COOWW..../.....OWW.....",
    "..../..../..../..../...X.X.X.X.../.X.........X./.XX.X...X.XX./......W....../.X...XOX...X./...X..C..X.../"
    "......G....../...X..R..X.../.X...XBX...X./......M....../.XX.X...X.XX./.X.........X./...X.X.X.X...",
    "..../..../.X.X.....X.X./.XGX.....XGX./.XCX.....XCX./.XXX.....XXX./..../....MWWWY..../....MOOOY..../"
    "....MCCCY..../....MGGGY..../....MRRRY..../....MBBBY....",
    ".X.........../..../.X.........../.X.........../.X.........../.X.....B...../.X....BCB..../.X...BCWCB.../"
    ".X..BCWCWCB../.X.BCWCSCWCB./.X..BCWCWCB../.X...BCWCB.../.X....BCB..../.X.....B...../.X.........../"
    ".X.........../.X.........../.XXXXXXXXXXXX",
    "..../..../..../..../.SSSSSSSSSSS./.S.........S./.S.SSSSSSS.S./.S.S.....S.S./.S.S.SSS.S.S./.S.S.S.S.S.S./"
    ".S.S.SSS.S.S./.S.S.....S.S./.S.SSSSSSS.S./.S.........S./.SSSSSSSSSSS.",
    "..../..../..../..../XXXXXXXXXXXXX/....X.....XM./.XW.X.....X../.X..X..X..X../.X..XG.X..X../.X..X..X..X../"
    ".X.OX..X.BX../.X..X..X..X../.X..X..X..X../.X..X.RX..X../.X..X..X..X../.XC....X...../.X.....X....Y/.XXXXXXXXXXXX",
    "..../..../..../..../.YYY.WWW.YYY./.MMM.OOO.MMM./.BBB.CCC.BBB./.RRR.GGG.RRR./.GGG.RRR.GGG./.CCC.BBB.CCC./"
    ".OOO.MMM.OOO./.WWW.YYY.WWW.",
    "..../..../..../..../BBBBBBBBBBBBB/X...........X/BBBBBBBBBBBBB/..../OSSSSSSSSSSSO/X...........X/WWWWWWWWWWWWW/"
    "..../CSSSSSSSSSSSC/X...........X/RRRRRRRRRRRRR/..../RRRRRRRRRRRRR/X...........X",
    "..../..../..../..../..../..../CWXCCCCCCCXWC/CWYXCCCCCXGWC/CWYYXCCCXGGWC/CWYYYXWXGGGWC/CWYYYYWGGGGWC/"
    "CWYYYYWGGGGWC/CWYYYYWGGGGWC/CSYYYYWGGGGSC/CCSYYYWGGGSCC/CCCSYYWGGSCCC/CCCCSYWGSCCCC/CCCCCSWSCCCCC",
    "..../..../..../..../......X....../....WW.WW..../..WW..X..WW../WW..OO.OO..WW/..OO..X..OO../OO..YY.YY..OO/"
    "..YY..X..YY../YY..GG.GG..YY/..GG..X..GG../GG..RR.RR..GG/..RR..X..RR../RR..BB.BB..RR/..BB.....BB../BB.........BB",
    "..../..../..../..../......S....../...BBBSGGG.../..BBBWWWGGG../..BBWWWWWGG../.BBBWWWWWGGG./.BBBWWWWWGGG./"
    ".BBBWWWWWGGG./.S..S.S.S..S./......S....../......S....../......S....../....X.X....../....XXX....../.....X.......",
    "..../..../..../..../O.XYYYYYYYX.O/O.XXYYYYYXX.O/O.X.XYYYX.X.O/O.X.MXYXC.X.O/O.X.M.S.C.X.O/O.X.M.G.C.X.O/"
    "O.X.M.G.C.X.O/O.X.M.G.C.X.O/O.X.M.G.C.X.O/OXXXM.G.CXXXO",
    "..../..../..../..../..XXXXXXXXX../..GRBMXMBRG../..GRBMXMBRG../..GRBMXMBRG../..GRBMYMBRG../..GRBMXMBRG../"
    "..GRBMXMBRG../..GRBMXMBRG../..XXXXXXXXX..",
    "..../..../..../..../XWXOXCXGXRXBX/XMXSXSXSXSXYX/..../XMX.X.X.X.X.X/X.XMX.X.X.X.X/X.X.XMX.X.X.X/X.X.X.XMX.X.X/"
    "X.X.X.X.XMX.X/...........M./..X.X.X.XMX../..X.X.XMX.X../..X.XMX.X.X../...MX.X.X..../.M....X......",
    "..../..../..../..../.XOOOOOOOOOX./.X.........X./.X.XXXXXXX.X./.X.X.....X.X./.X.X.....X.X./.X.X.RRR.X.X./"
    ".X.X.GGG.X.X./.X.X.BBB.X.X./.X.X.WWW.X.X./.X.X.....X.X./.X.XCCCCCX.X./.X.........X./.X.........X./.XXXXXXXXXXX.",
    "..../..../..../..../YYYYYYYYYYYYY/YYYYYYYYYYYYY/..../RRX.XRRRX.XRR/RRX.XRRRX.XRR/RRX.XRRRX.XRR/RRX.XRRRX.XRR/"
    "..../WWWWWWWWWWWWW/WWWWWWWWWWWWW",
    "..../..../..../..../CCCCCCCCCCCCC/..../..SSS.SSS.SSS/..SGS.SGS.SGS/..SSS.SSS.SSS/..../.SSS.SSS.SSS./"
    ".SRS.SRS.SRS./.SSS.SSS.SSS./..../SSS.SSS.SSS../SBS.SBS.SBS../SSS.SSS.SSS..",
    "..../..../..../..../..../..../..../.....WWW...../.....WWW...../.....WWW...../....WWWWW..../....WBWBW..../"
    "...WBBWBBW.../...BBBBBBB.../..BBBBBBBBB../..BBBBBBBBB../.BBBBBBBBBBB./BBBBBBBBBBBBB",
    "..../..../..../..../RRRRRRRRRRRRR/GGGGGGGGGGGGG/BBBBBBBBBBBBB/XXXXXSSSXXXXX/XRRRX...XBBBX/XRRRX...XBBBX/"
    "X...........X/X...........X/X...XGGGX...X/X...XGGGX...X/XSSSXXXXXSSSX",
    "..../..../..../..../..XSSSX....../.X.....X...../X..CCC..X..../X.GGGGG.X..../X.BBBBB.X..../X..MMM..X..../"
    ".X.....X...../..XXXXX......",
    "..../..../..../..../..../..../..../..../..../..../..../SSSSSSSSSSSSS/YYYYYYYYYYYYY/SSSSSSSSSSSSS/..../"
    "SSSSSSSSSSSSS/RRRRRRRRRRRRR/SSSSSSSSSSSSS",
    "..../..../..../BBBBBBBBBBBBB/BXXXXMXMXXXXB/BX.........XB/BXM.......MXB/BXMM.....MMXB/BXMMM...MMMXB/"
    ".BXMMM.MMMXB./..BXMMMMMXB../...BXMMMXB.../....BXMXB..../.....BMB...../......B......",
    "..../..../..../..../YYYYYX.XYYYYY/MMMMMX.XMMMMM/XXWXXX.XXXWXX/BBBBBX.XBBBBB/RRRRRX.XRRRRR/GGGGGX.XGGGGG/"
    "SSWSSX.XSSWSS/CCCCCX.XCCCCC/OOOOOX.XOOOOO/WWWWWX.XWWWWW",
    "..../..../..../..../YM.........../YMBR........./YMBRGC......./YMBRGCOW...../YMBRGCOWYM.../SMBRGCOWYMBR./"
    ".XSRGCOWYMBRG/...XSCOWYMBRG/.....XSWYMBRG/.......XSMBRG/.........XSRG/...........XS",
    "..../..../..../..../G.R.B.M.Y.W.O/S.S.S.S.S.S.S/.B.R.G.C.O.W./.S.S.S.S.S.S./C.G.R.B.M.Y.W/S.S.S.S.S.S.S/"
    ".M.B.R.G.C.O./.S.S.S.S.S.S./O.C.G.R.B.M.Y/S.S.S.S.S.S.S/.Y.M.B.R.G.C./.S.S.S.S.S.S./W.O.C.G.R.B.M/S.S.S.S.S.S.S",
    "..../..../..../..../..X.X.X.X.X../..X.X.X.X.X../..X.X.X.XGG../..X.X.X.X.X../..X.X.XRRRR../..X.X.X.X.X../"
    "..X.XBBBBBB../..X.X.X.X.X../..XMMMMMMMM../..X.X.X.X.X../..YYYYYYYYY../..SSSSSSSSS..",
]
BRICKS = "WOCGRBMYSX"                        # the order the tiles and points follow
POINTS = [50, 60, 70, 80, 90, 100, 110, 120]  # silver is 50 x round, gold nothing
MAXROWS = 18


def rounds():
    """The layouts as 18 rows of 13, '....' short for an empty row."""
    out = []
    for n, r in enumerate(ROUNDS, 1):
        rows = [("." * 13 if row == "...." else row) for row in r.split("/")]
        assert all(len(row) == 13 and set(row) <= set(BRICKS + ".") for row in rows), n
        assert len(rows) <= MAXROWS, (n, len(rows))
        rows += ["." * 13] * (MAXROWS - len(rows))
        out.append(rows)
    assert len(out) == 32
    # the ones everybody knows, as a check on the reading
    assert out[0][4:10] == ["S" * 13, "R" * 13, "Y" * 13, "B" * 13, "M" * 13, "G" * 13]
    assert out[1][14] == "SSSSSSSSSSSSR"
    return out


# ------------------------------------------------------------------- font
# What the arcade's own frames show, 7 rows a glyph on its 8 x 8 cell:
# StrategyWiki's title screen (Arkanoid_title.png, "1UP  HIGH SCORE",
# "00  17550", "(c) 1986 TAITO CORP JAPAN", "ALL RIGHTS RESERVED",
# "CREDIT 0") and every play frame's top line. The same glyph where it
# repeats is the same pixels; one copy of each is kept.
SEEN = {
    "0": "...###../..#..##./.##...##/.##...##/.##...##/..##..#./...###..",
    "1": "....##../...###../....##../....##../....##../....##../..######",
    "5": ".######./.##...../.######./......##/......##/.##...##/..#####.",
    "6": "...####./..##..../.##...../.######./.##...##/.##...##/..#####.",
    "7": ".#######/.##...##/.....##./....##../...##.../...##.../...##...",
    "8": "..####../.##...#./.###..#./..####../.#..####/.#....##/..#####.",
    "9": "..#####./.##...##/.##...##/..######/......##/.....##./..####..",
    "A": "...###../..##.##./.##...##/.##...##/.#######/.##...##/.##...##",
    "C": "...####./..##..##/.##...../.##...../.##...../..##..##/...####.",
    "D": ".#####../.##..##./.##...##/.##...##/.##...##/.##..##./.#####..",
    "E": ".#######/.##...../.##...../.######./.##...../.##...../.#######",
    "G": "...#####/..##..../.##...../.##..###/.##...##/..##..##/...#####",
    "H": ".##...##/.##...##/.##...##/.#######/.##...##/.##...##/.##...##",
    "I": "..######/....##../....##../....##../....##../....##../..######",
    "J": "......##/......##/......##/......##/......##/.##...##/..#####.",
    "L": ".##...../.##...../.##...../.##...../.##...../.##...../.#######",
    "N": ".##...##/.###..##/.####.##/.#######/.##.####/.##..###/.##...##",
    "O": "..#####./.##...##/.##...##/.##...##/.##...##/.##...##/..#####.",
    "P": ".######./.##...##/.##...##/.##...##/.######./.##...../.##.....",
    "R": ".######./.##...##/.##...##/.##..###/.#####../.##.###./.##..###",
    "S": "..####../.##..##./.##...../..#####./......##/.##...##/..#####.",
    "T": "..######/....##../....##../....##../....##../....##../....##..",
    "U": ".##...##/.##...##/.##...##/.##...##/.##...##/.##...##/..#####.",
    "V": ".##...##/.##...##/.##...##/.###.###/..#####./...###../....#...",
}
# the copyright sign fills its cell
COPYRIGHT = "..####../.#....#./#..##..#/#.#....#/#.#....#/#..##..#/.#....#./..####.."
DIFFERS = set("EL")                    # Taito's, not Namco's: a pixel wider
FONT = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-.!/ "


def rows_of(g):
    return [r for r in g.split("/")]


def namco_rows(ch, glyphs):
    """A Namco glyph as 8 strings, from mkmscool's 4 bpp bytes."""
    g = glyphs[ch]
    out = []
    for y in range(8):
        s = ""
        for b in g[y * 4:(y + 1) * 4]:
            s += ("#" if b >> 4 else ".") + ("#" if b & 15 else ".")
        out.append(s)
    return out


QUOTE = (10, 2)                         # '"' on the Pac-Man sheet's font panel


def font():
    """The glyphs, as 8 bytes of 1 bpp each (bit 7 the left pixel), and
    the list of those that fell back to the Namco font."""
    _, ng = mkmscool.font(mkmscool.load(mkmscool.FONTSHEET), {'"': QUOTE})
    q = namco_rows('"', ng)
    assert any("#" in r for r in q[:3]) and not any("#" in r for r in q[4:]), "the quote is not a quote: %s" % q
    out = {'"': [int(r.replace("#", "1").replace(".", "0"), 2) for r in q]}
    fallback = ['"']
    for ch in FONT:
        nr = namco_rows(ch, ng)
        # Namco's digits sit a row low; the arcade's sit on the letters' line
        if ch.isdigit():
            nr = nr[1:] + ["........"]
        if ch in SEEN:
            sr = rows_of(SEEN[ch]) + ["........"]
            if ch in DIFFERS:
                assert sr != nr, ch
            else:
                assert sr == nr, "%s: the arcade's glyph is not Namco's\n%s\n%s" % (ch, sr, nr)
            rows = sr
        else:
            rows = nr
            if ch != " ":
                fallback.append(ch)
        out[ch] = [int(r.replace("#", "1").replace(".", "0"), 2) for r in rows]
    out["@"] = [int(r.replace("#", "1").replace(".", "0"), 2) for r in rows_of(COPYRIGHT)]
    return out, fallback


# ----------------------------------------------------------------- fields
# The fields sheet: five 224 x 240 panels at x = 232k, the playfield with
# its frame exactly as the arcade draws it from y 16 (blue, green,
# circuit, grey, and DOH's red), the life icons under each at y 240; and
# under the first four at y 256 the same panels dark -- the colours a
# block's shadow turns the background to. Four backgrounds for rounds
# 1-32 in turn, (round - 1) mod 4; the red one for DOH.
COLS, ROWS = 28, 30


def cell(s, x0, y0):
    return tuple(s.px[x0 + x, y0 + y][:3] for y in range(8) for x in range(8))


def fields():
    s = Sheet("fields")
    out = []
    for k in range(5):
        x0 = 232 * k
        norm = [[cell(s, x0 + tx * 8, ty * 8) for tx in range(COLS)] for ty in range(ROWS)]
        dark = [[cell(s, x0 + tx * 8, 256 + ty * 8) for tx in range(COLS)] for ty in range(ROWS)] if k < 4 else None
        out.append({"k": k, "norm": norm, "dark": dark})
    return out


def period(grid, cells):
    """The smallest (pw, ph) the grid repeats by over the given cells."""
    cs = set(cells)
    for ph in range(1, 17):
        for pw in range(1, 17):
            if all(grid[ty][tx] == grid[ty + ph][tx] for tx, ty in cells if (tx, ty + ph) in cs) and \
               all(grid[ty][tx] == grid[ty][tx + pw] for tx, ty in cells if (tx + pw, ty) in cs):
                return pw, ph
    return None


def field_report(fl):
    """How each panel is built: frame, the frame's shadow, the pattern."""
    inner = [(tx, ty) for ty in range(2, ROWS) for tx in range(2, COLS - 1)]
    for f in fl:
        k, norm, dark = f["k"], f["norm"], f["dark"]
        cols = Counter(q4(c) for row in norm for t in row for c in t)
        if dark:
            cols.update(q4(c) for row in dark for t in row for c in t)
        p = period(norm, inner)
        pd = period(dark, inner) if dark else None
        shadow = None
        if dark:
            # the frame's own shadow: row 1 and column 1 are the dark panel's
            row1 = all(norm[1][tx] == dark[1][tx] for tx in range(1, COLS - 1))
            col1 = all(norm[ty][1] == dark[ty][1] for ty in range(1, ROWS))
            shadow = (row1, col1)
        if p is None:
            # where the pattern breaks: the cells that differ from their
            # neighbour a period away, for the period that fits best
            best = None
            for ph in range(1, 9):
                for pw in range(1, 9):
                    bad = [(tx, ty) for tx, ty in inner
                           if (tx + pw < COLS - 1 and norm[ty][tx] != norm[ty][tx + pw]) or
                              (ty + ph < ROWS and norm[ty][tx] != norm[ty + ph][tx])]
                    if best is None or len(bad) < len(best[2]):
                        best = (pw, ph, bad)
            print("    field %d: period %s breaks at %s" % (k, best[:2], best[2][:24]))
        if dark:
            # how far the frame's shadow reaches: pixel columns of column 2
            # and pixel rows of row 2 that are the dark panel's
            xs = [x for x in range(8) if all(norm[ty][2][y * 8 + x] == dark[ty][2][y * 8 + x]
                                              for ty in range(3, ROWS) for y in range(8))]
            ys = [y for y in range(8) if all(norm[2][tx][y * 8 + x] == dark[2][tx][y * 8 + x]
                                              for tx in range(3, COLS - 1) for x in range(8))]
            print("    field %d: the frame's shadow takes pixel columns %s of column 2, rows %s of row 2" % (k, xs, ys))
        uniq = len({t for row in norm for t in row} | ({t for row in dark for t in row} if dark else set()))
        print("  field %d: %2d colours %s, %3d tiles, pattern %s dark %s, frame shadow row/col 1 %s" %
              (k, len(cols), " ".join("%03X" % c for c in sorted(cols)),
               uniq, p, pd, shadow))


# ----------------------------------------------------------------- blocks
# The blocks sheet: the eight colours at 16 x 8, four to a row from the
# top-left, white orange cyan green / red blue magenta yellow; then
# silver and gold, each at rest and in five frames of the shine a hit
# sends across it (the sixth and seventh cells of those rows are empty).
def bricks():
    s = Sheet("blocks")
    out = {}
    for i, ch in enumerate("WOCGRBMY"):
        x0, y0 = (i % 4) * 16, (i // 4) * 8
        out[ch] = [(cell(s, x0, y0), cell(s, x0 + 8, y0))]
    for r, ch in ((2, "S"), (3, "X")):
        out[ch] = [(cell(s, f * 16, r * 8), cell(s, f * 16 + 8, r * 8)) for f in range(6)]
        # the shine goes and comes back: its first frame is the brick at rest
        assert out[ch][0] != out[ch][3]
    for ch, frames in out.items():
        for a, b in frames:
            assert all(s is not None for s in a + b), ch
    return out


# ------------------------------------------------------------------ Vaus
# The fuller Vaus sheet, "Arkanoid (World, older)": every box below is
# what `--boxes vaus` finds, in sheet pixels (x, y, w, h).
V_ESCAPE = [(8, 49, 18, 5), (34, 46, 16, 8), (58, 45, 13, 9), (79, 45, 11, 9), (98, 44, 12, 10),
            (118, 46, 9, 8), (135, 47, 11, 7), (154, 48, 13, 6), (175, 50, 14, 4), (197, 48, 12, 6),
            (217, 47, 9, 7), (234, 47, 7, 7), (249, 49, 6, 5), (263, 51, 5, 3), (276, 52, 4, 2)]
V_FLASH = [(8, 81, 1, 1), (17, 81, 7, 1), (32, 80, 15, 3), (55, 79, 23, 5), (86, 78, 31, 7),
           (125, 79, 23, 5), (156, 80, 15, 3), (179, 81, 7, 1), (194, 81, 1, 1)]
V_APPEAR = [(8 + 40 * i, 109, 32, 8) for i in range(8)]        # the outline filling in
V_NORMAL = [(8 + 40 * i, 141, 32, 8) for i in range(6)]        # the end lights turning
V_LASER = [(8 + 40 * i, 177, 32, 8) for i in range(6)]
V_BIG = [(8 + 56 * i, 213, 48, 8) for i in range(6)]
V_HIT = [(8 + 40 * i, 253, 32, 8) for i in range(3)]           # whole, cracked, crackling
V_DEBRIS = [(144, 245, 32, 24), (192, 245, 37, 24), (245, 245, 41, 24), (302, 245, 44, 24)]
V_GROW = [(16 - i, 405 + 16 * i, 32 + 2 * i, 8) for i in range(9)]   # normal to enlarged
V_ARM = [(80, 405, 32, 8), (83, 421, 26, 8), (85, 437, 22, 8), (88, 453, 16, 8), (84, 469, 24, 8),
         (82, 485, 28, 8), (81, 501, 30, 8), (80, 517, 32, 8), (80, 533, 32, 8)]  # normal to laser
V_SHADOW = (308, 145, 32, 8)       # the normal Vaus's shadow, drawn alone
V_BALL = (367, 341, 5, 4)
V_BALL_SHADOW = (371, 345, 5, 4)
V_BEAMS = (392, 325, 16, 8)        # the laser's two beams, 13 pixels apart


def grab(s, box):
    """A box as rows of colours, None for background."""
    x0, y0, w, h = box
    return [[s.at(x0 + x, y0 + y) for x in range(w)] for y in range(h)]


def vaus():
    s = Sheet("vaus")
    out = {}
    for name, boxes in (("escape", V_ESCAPE), ("flash", V_FLASH), ("appear", V_APPEAR),
                        ("normal", V_NORMAL), ("laser", V_LASER), ("big", V_BIG), ("hit", V_HIT),
                        ("debris", V_DEBRIS), ("grow", V_GROW), ("arm", V_ARM)):
        out[name] = [grab(s, b) for b in boxes]
    # the sheet's own rule, "move sprite four pixels down and to the right
    # and color all black": its shadow drawn alone is the normal Vaus's
    # shape, and so the game derives every shadow from its frame
    shadow = grab(s, V_SHADOW)
    shape = [[c is not None for c in row] for row in out["normal"][0]]
    assert [[c is not None for c in row] for row in shadow] == shape, "the shadow is not the Vaus's shape"
    assert all(c in (None, (0, 0, 0)) for row in shadow for c in row), "the shadow is not black"
    out["ball"] = grab(s, V_BALL)
    ball_shadow = grab(s, V_BALL_SHADOW)
    assert [[c is not None for c in r] for r in ball_shadow] == [[c is not None for c in r] for r in out["ball"]]
    out["beams"] = grab(s, V_BEAMS)
    return out


# ------------------------------------------------------ capsules, enemies
# The power-ups sheet: seven rows of the capsule at 16 x 8, eight frames
# of its letter turning; the sheet's white is its background, so white
# inside a capsule is told from white outside by where it can be reached
# from the cell's edge.
CAPSULE_ROWS = "SCLEDBP"     # the rows as the sheet has them, by their letters


def capsules():
    s = Sheet("powerups")
    out = {}
    for r, ch in enumerate(CAPSULE_ROWS):
        frames = []
        for f in range(8):
            x0, y0 = f * 16, r * 8
            raw = [[s.px[x0 + x, y0 + y] for x in range(16)] for y in range(8)]
            white = lambda c: c[3] == 0 or c[:3] == (255, 255, 255)
            outside = set()
            stack = [(x, y) for y in range(8) for x in range(16)
                     if (x in (0, 15) or y in (0, 7)) and white(raw[y][x])]
            outside.update(stack)
            while stack:
                x, y = stack.pop()
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    a, b = x + dx, y + dy
                    if 0 <= a < 16 and 0 <= b < 8 and (a, b) not in outside and white(raw[b][a]):
                        outside.add((a, b))
                        stack.append((a, b))
            frames.append([[None if (x, y) in outside else raw[y][x][:3] for x in range(16)] for y in range(8)])
        out[ch] = frames
    return out


# The enemies sheet, 16 x 16 on a grid from the top-left: the cone's
# eight frames; the pyramid's eleven over two rows; the molecule's
# twenty-four over three; the cube's ten over two; the burst an enemy
# goes up in, six; and the sparkle one appears from, six. The sheet's
# checkerboard and the sparkle row's purple are background.
ENEMY_ROWS = {"cone": [(0, 8)], "pyramid": [(1, 6), (2, 5)], "molecule": [(3, 8), (4, 8), (5, 8)],
              "cube": [(6, 5), (7, 5)], "burst": [(8, 6)], "sparkle": [(9, 6)]}


def enemies():
    s = Sheet("enemies")
    out = {}
    for name, rows in ENEMY_ROWS.items():
        out[name] = [grab(s, (f * 16, r * 16, 16, 16)) for r, n in rows for f in range(n)]
    return out


# ------------------------------------------------------------ DOH, ship
# DOH: 64 x 96 cells from y 144, four to a row -- NORMAL (the mouth
# opening), HIT, three rows dying, and the death over the last three
# rows, ten frames. The piece at the top-left is the red wall he sits
# in on round 33.
def doh():
    s = Sheet("doh")
    frames = []
    for r in range(8):
        for c in range(4 if r < 7 else 2):
            frames.append(grab(s, (64 * c, 144 + 96 * r, 64, 96)))
    wall = grab(s, (0, 0, 88, 135))
    return {"normal": frames[0:4], "hit": frames[4:8], "dying": frames[8:20], "death": frames[20:30],
            "wall": wall}


# The mothership: the ARKANOID logo, then twenty frames of 192 x 88,
# two to a row, as the intro shows it -- lit, hit, and the Vaus's rings
# rising out of it.
def ship():
    s = Sheet("ship")
    logo = grab(s, (0, 0, 193, 42))
    frames = [grab(s, (1 + 200 * c, 54 + 100 * r, 191, 83)) for r in range(10) for c in range(2)]
    return {"logo": logo, "frames": frames}


def bbox(im):
    ys = [y for y, row in enumerate(im) if any(c is not None for c in row)]
    xs = [x for x in range(len(im[0])) if any(row[x] is not None for row in im)]
    return (xs[0], ys[0], xs[-1] - xs[0] + 1, ys[-1] - ys[0] + 1) if xs else None


def cells_of(im, ox=0, oy=0, w=None, h=None):
    """The 8 x 8 cells of im from (ox, oy), row-major, None-padded."""
    H, W = len(im), len(im[0])
    w = w or W - ox
    h = h or H - oy
    out = []
    for ty in range(0, h, 8):
        for tx in range(0, w, 8):
            out.append(tuple(im[oy + y][ox + x] if oy + y < H and ox + x < W else None
                             for y in range(ty, ty + 8) for x in range(tx, tx + 8)))
    return out


def recolour_map(a, b):
    """The colour-for-colour mapping that turns cell a into cell b, or None."""
    m = {}
    for ca, cb in zip(a, b):
        if m.setdefault(ca, cb) != cb:
            return None
    return m


# ----------------------------------------------------------------- report
def colours(*images):
    cnt = Counter()
    for im in images:
        for row in im:
            for c in row:
                if c is not None:
                    cnt[q4(c)] += 1
    return cnt


def cells8(im):
    """An image cut into 8 x 8 cells, None-padded: the set of distinct ones."""
    h, w = len(im), len(im[0])
    out = set()
    for ty in range(0, h, 8):
        for tx in range(0, w, 8):
            out.add(tuple(im[y][x] if y < h and x < w else None for y in range(ty, ty + 8) for x in range(tx, tx + 8)))
    return out


def report():
    rs = rounds()
    fnt, fallback = font()
    print("  32 rounds; font %d glyphs, %d as the arcade shows them, Namco's for %s" %
          (len(fnt), len([c for c in FONT if c in SEEN]), "".join(fallback)))
    fl = fields()
    field_report(fl)
    bk = bricks()
    bc = colours(*[[list(t)] for fr in bk.values() for a, b in fr for t in (a, b)])
    print("  bricks: %d colours %s" % (len(bc), " ".join("%03X" % c for c in sorted(bc))))
    v = vaus()
    for name in ("escape", "flash", "appear", "normal", "laser", "big", "hit", "debris", "grow", "arm"):
        vc = colours(*v[name])
        print("  vaus %-7s %2d frames, %2d colours %s" % (name, len(v[name]), len(vc), " ".join("%03X" % c for c in sorted(vc))))
    print("  ball %s, beams %s" % (sorted("%03X" % c for c in colours(v["ball"])), sorted("%03X" % c for c in colours(v["beams"]))))
    cp = capsules()
    for ch, frames in cp.items():
        cc = colours(*frames)
        print("  capsule %s: %2d colours %s" % (ch, len(cc), " ".join("%03X" % c for c in sorted(cc))))
    en = enemies()
    for name, frames in en.items():
        ec = colours(*frames)
        print("  %-8s %2d frames, %2d colours %s" % (name, len(frames), len(ec), " ".join("%03X" % c for c in sorted(ec))))
    d = doh()
    for name in ("normal", "hit", "dying", "death"):
        dc = colours(*d[name])
        n = len(set().union(*[cells8(f) for f in d[name]]))
        print("  doh %-7s %2d frames, %3d distinct cells, %2d colours %s" % (name, len(d[name]), n, len(dc), " ".join("%03X" % c for c in sorted(dc))))
    alld = set().union(*[cells8(f) for k in ("normal", "hit", "dying", "death") for f in d[k]])
    print("  doh all: %d distinct cells; wall %d cells, %d colours" % (len(alld), len(cells8(d["wall"])), len(colours(d["wall"]))))
    # aligned on each frame's own box, and told as recolours of the
    # normal frames where the pixels allow it
    allf = [(k, i, f) for k in ("normal", "hit", "dying", "death") for i, f in enumerate(d[k])]
    boxes = [(k, i, bbox(f)) for k, i, f in allf]
    print("  doh boxes: " + " ".join("%s%d:%d,%d,%dx%d" % ((k[0], i) + b) for k, i, b in boxes))
    base = []
    for k, i, f in allf[:4]:
        bx = bbox(f)
        base.append(cells_of(f, bx[0], bx[1], 64, 96))
    tiles = set(c for b in base for c in b)
    maps = Counter()
    for k, i, f in allf[4:]:
        bx = bbox(f)
        cs = cells_of(f, bx[0], bx[1], 64, 96)
        new = 0
        for j, c in enumerate(cs):
            found = None
            for b in base:
                m = recolour_map(b[j], c)
                if m is not None:
                    found = frozenset((q4(a) if a else None, q4(v) if v else None) for a, v in m.items() if a != v)
                    break
            if found is None:
                new += 1
                tiles.add(c)
            elif found:
                maps[found] += 1
        print("    doh %s%-2d %2d cells need their own tile" % (k[0], i, new))
    nbase = len(set(c for b in base for c in b))
    # partial recolourings that agree where they overlap are one palette
    merged = []
    for m in sorted(maps, key=len, reverse=True):
        d_ = dict(m)
        for g in merged:
            if all(g.get(a, v) == v for a, v in d_.items()):
                g.update(d_)
                break
        else:
            merged.append(d_)
    print("  doh: %d base tiles from the normal frames, %d in all; %d recolourings, %d palettes merged: %s" %
          (nbase, len(tiles), len(maps), len(merged),
           "; ".join(" ".join("%03X>%03X" % (a, v) for a, v in sorted(g.items(), key=lambda e: e[0] or 0) if a is not None and v is not None) for g in merged)))
    sh = ship()
    sc = colours(*sh["frames"])
    alls = set().union(*[cells8(f) for f in sh["frames"]])
    print("  ship: %d frames, %d distinct cells (frame 0 alone %d), %d colours %s" %
          (len(sh["frames"]), len(alls), len(cells8(sh["frames"][0])), len(sc), " ".join("%03X" % c for c in sorted(sc))))
    print("  logo: %d cells, %d colours %s" % (len(cells8(sh["logo"])), len(colours(sh["logo"])),
                                               " ".join("%03X" % c for c in sorted(colours(sh["logo"])))))
    a = sh["frames"][0]
    H, W = len(a), len(a[0])
    print("    ship frame  0: %2d colours %s" % (len(colours(a)), " ".join("%03X" % c for c in sorted(colours(a)))))
    for i in range(1, 20):
        b = sh["frames"][i]
        same_shape = all((a[y][x] is None) == (b[y][x] is None) for y in range(H) for x in range(W))
        diff = [(x, y) for y in range(H) for x in range(W) if a[y][x] != b[y][x]]
        m = recolour_map([c for row in a for c in row], [c for row in b for c in row])
        box = (min(x for x, _ in diff), min(y for _, y in diff), max(x for x, _ in diff), max(y for _, y in diff)) if diff else None
        print("    ship frame %2d: shape %s, %5d pixels differ %s, %s" %
              (i, "same" if same_shape else "differs", len(diff), box,
               "a recolour of frame 0 (%d colours move)" % sum(1 for p, v in m.items() if p != v) if m else "not a recolour"))


# ================================================================ the build
# Tile numbers in pattern bank 0 (VID_PAT, 32 bytes a tile) and the
# palette banks the game gives them.
T_FIELD = 0          # the round's background: its tiles, up to 68
T_BRICK = 68         # 40: the ten at rest, then silver's and gold's shine
T_FONT = 120         # the glyphs in FONT's order, then (c) and the quote
T_VAUS = 168         # the Vaus drawn into the background: two sets of 24
T_LIFE = 216
VROWS = (26, 27, 28, 29)   # the rows the Vaus, its shadow and its debris touch


def pack4(ix):
    """Palette indices, row-major, as 4 bpp bytes: the left pixel high."""
    return [(ix[i] << 4) | ix[i + 1] for i in range(0, len(ix), 2)]


def build_field(f):
    """A background as tiles, a palette, and the model the game builds
    its map from: the frame's cells, a pattern repeating every pw x ph
    cells (normal and dark), and the cells the pattern does not predict."""
    norm = f["norm"]
    dark = f["dark"] or norm
    tiles, index = [], {}

    def ti(t):
        if t not in index:
            index[t] = len(tiles)
            tiles.append(t)
        return index[t]
    N = [[ti(norm[ty][tx]) for tx in range(COLS)] for ty in range(ROWS)]
    D = [[ti(dark[ty][tx]) for tx in range(COLS)] for ty in range(ROWS)]
    cols = sorted({q4(c) for t in tiles for c in t})
    assert len(cols) <= 16, (f["k"], len(cols))
    pix = {c: i for i, c in enumerate(cols)}
    enc = [pack4([pix[q4(c)] for c in t]) for t in tiles]
    fcells = [(tx, 0) for tx in range(COLS)] + [(0, ty) for ty in range(1, ROWS)] + \
             [(COLS - 1, ty) for ty in range(1, ROWS)]
    assert all(N[ty][tx] == D[ty][tx] for tx, ty in fcells), "the frame darkens"
    inner = [(tx, ty) for ty in range(1, ROWS) for tx in range(1, COLS - 1)]
    best = None
    for ph in range(1, 9):
        for pw in range(1, 9):
            votes = {}
            for tx, ty in inner:
                votes.setdefault((tx % pw, ty % ph), Counter())[(N[ty][tx], D[ty][tx])] += 1
            pat = {r: c.most_common(1)[0][0] for r, c in votes.items()}
            exc = [(tx, ty) for tx, ty in inner if pat[(tx % pw, ty % ph)] != (N[ty][tx], D[ty][tx])]
            if best is None or len(exc) < len(best[3]):
                best = (pw, ph, pat, exc)
    pw, ph, pat, exc = best
    out = {"k": f["k"], "cols": cols, "pal": cols + [0] * (16 - len(cols)), "tiles": enc, "N": N, "D": D,
           "frame": [N[ty][tx] for tx, ty in fcells], "pw": pw, "ph": ph,
           "pn": [pat[(x, y)][0] for y in range(ph) for x in range(pw)],
           "pd": [pat[(x, y)][1] for y in range(ph) for x in range(pw)],
           "exc": [(tx, ty, N[ty][tx], D[ty][tx]) for tx, ty in exc]}
    # the model rebuilt as the game will, and held to the sheet
    mn, md = field_maps(out)
    assert mn == N and md == D, "the field model does not rebuild field %d" % f["k"]
    return out


def field_maps(b):
    """The normal and dark maps the game builds from a field's model."""
    mn = [[0] * COLS for _ in range(ROWS)]
    md = [[0] * COLS for _ in range(ROWS)]
    fr = iter(b["frame"])
    for tx in range(COLS):
        mn[0][tx] = md[0][tx] = next(fr)
    for ty in range(1, ROWS):
        mn[ty][0] = md[ty][0] = next(fr)
    for ty in range(1, ROWS):
        mn[ty][COLS - 1] = md[ty][COLS - 1] = next(fr)
    for ty in range(1, ROWS):
        for tx in range(1, COLS - 1):
            i = (ty % b["ph"]) * b["pw"] + tx % b["pw"]
            mn[ty][tx], md[ty][tx] = b["pn"][i], b["pd"][i]
    for tx, ty, n, d in b["exc"]:
        mn[ty][tx], md[ty][tx] = n, d
    return mn, md


def build_bricks(bk):
    cells = []
    for ch in BRICKS:
        cells += list(bk[ch][0])
    for ch in "SX":
        for f in range(1, 6):
            cells += list(bk[ch][f])
    cols = sorted({q4(c) for t in cells for c in t})
    assert len(cols) <= 16, len(cols)
    pix = {c: i for i, c in enumerate(cols)}
    return {"pal": cols + [0] * (16 - len(cols)), "tiles": [pack4([pix[q4(c)] for c in t]) for t in cells]}


# The sprites' one palette bank (04-system.md section 5.6): six colours
# every sprite shares, four slots the round's enemy fills, two the
# falling capsule's, and DOH's shot's two greys.
SPR_FIXED = [0x000, 0xFFF, 0xFF0, 0x0FF, 0xF00, 0x0F0]     # indices 1-6
ENEMY_SLOT, CAP_SLOT, GREY_SLOT = 7, 11, 13
ENEMY_TYPES = ("cone", "pyramid", "molecule", "cube")

# DOH's shot is on no sheet; round 33's frame on StrategyWiki shows it
# three times on its way down, edge on, turning, and face on -- a = 174,
# b = 255, c = 112 grey, read off that frame pixel by pixel.
DOH_SHOT = [
    ["a", "a", "a", "a", "a", "a", "a"],
    ["...bbbbb", "..bbbbba", ".bbbbba.", "bbbbba..", "aaaaa..."],
    ["...ac...", "..aaac..", ".aaaaac.", "aaaaaaac", ".aaaaac.", "..aaac..", "...ac..."],
]
SHOT_RGB = {"a": (174, 174, 174), "b": (255, 255, 255), "c": (112, 112, 112)}


class Cells:
    """A deduplicated list of 4 bpp 8 x 8 cells."""
    def __init__(self):
        self.cells, self.index = [], {}

    def add(self, cell):
        cell = tuple(cell)
        if cell not in self.index:
            self.index[cell] = len(self.cells)
            self.cells.append(cell)
        return self.index[cell]

    def image(self, im, cmap, ox=0, oy=0):
        """im's 8 x 8 cells from (ox, oy), row-major, as indices."""
        h, w = len(im), len(im[0])
        out = []
        for ty in range(oy, h, 8):
            for tx in range(ox, w, 8):
                ix = []
                for y in range(ty, ty + 8):
                    for x in range(tx, tx + 8):
                        c = im[y][x] if 0 <= y < h and 0 <= x < w else None
                        ix.append(0 if c is None else cmap[q4(c)])
                out.append(self.add(pack4(ix)))
        return out


def spr_map(extra, first):
    m = {c: i + 1 for i, c in enumerate(SPR_FIXED)}
    for i, c in enumerate(extra):
        m[c] = first + i
    return m


def build_sprites(cp, en, v):
    sc = Cells()
    out = {"enemy_pal": [], "cap_pal": []}
    fixed = set(SPR_FIXED)
    for name in ENEMY_TYPES:
        extra = sorted(set(colours(*en[name])) - fixed)
        assert len(extra) <= 4, (name, extra)
        out["enemy_pal"].append(extra + [0] * (4 - len(extra)))
        m = spr_map(extra, ENEMY_SLOT)
        out[name] = [sc.image(f, m) for f in en[name]]
    out["burst"] = [sc.image(f, spr_map([], 0)) for f in en["burst"]]
    for ch in CAPSULE_ROWS:
        extra = sorted(set(colours(*cp[ch])) - fixed, key=lambda c: sum((c >> s) & 15 for s in (0, 4, 8)))
        assert len(extra) <= 2, (ch, extra)
        out["cap_pal"].append(extra + [0] * (2 - len(extra)))
        m = spr_map(extra, CAP_SLOT)
        out["cap_" + ch] = [sc.image(f, m) for f in cp[ch]]
    m = spr_map([0xAAA, 0x777], GREY_SLOT)
    out["ball"] = sc.image(v["ball"], m)
    out["ball_shadow"] = sc.image([[(0, 0, 0) if c else None for c in row] for row in v["ball"]], m)
    beams = v["beams"]
    out["beam"] = sc.image([row[0:3] for row in beams], m)
    assert [row[13:16] for row in beams] == [row[0:3] for row in beams], "the two beams differ"
    out["shot"] = [sc.image([[SHOT_RGB.get(ch) for ch in row] for row in ph], m) for ph in DOH_SHOT]
    out["pal"] = [0] + SPR_FIXED + [0] * 4 + [0] * 2 + [0xAAA, 0x777, 0]
    out["cells"] = sc.cells
    return out


# The Vaus is drawn into the background, not by the sprite engine: it
# never leaves its row, its shadow is part of the picture that way, and
# it leaves the engine's eight a line to the balls, the capsules and
# the enemies that cross it. Its colours hold the same nine indices in
# every background's Vaus bank, 1-9; index 0 in its cells is see-through.
VAUS_COLS = [0x000, 0x009, 0x08F, 0x0FF, 0x666, 0x888, 0xB20, 0xF50, 0xFFF]


def with_shadow(im):
    """The frame over its own shadow: its shape, four right and four
    down, in black -- the sheet's rule, which vaus() checks."""
    h, w = len(im), len(im[0])
    out = [[None] * (w + 4) for _ in range(h + 4)]
    for y in range(h):
        for x in range(w):
            if im[y][x] is not None:
                out[y + 4][x + 4] = (0, 0, 0)
    for y in range(h):
        for x in range(w):
            if im[y][x] is not None:
                out[y][x] = im[y][x]
    return out


def pad_rows(im, top, total):
    w = len(im[0])
    return [[None] * w for _ in range(top)] + im + [[None] * w for _ in range(total - top - len(im))]


def build_vaus(v, flds):
    vc = Cells()
    m = {c: i + 1 for i, c in enumerate(VAUS_COLS)}
    frames = {}

    def put(name, ims, ox_of, oy=0):
        out = []
        for im in ims:
            s = with_shadow(im)
            cells = vc.image(s, m)
            wc, hc = (len(s[0]) + 7) // 8, (len(s) + 7) // 8
            out.append((wc, hc, ox_of(im), oy, cells))
        frames[name] = out
    put("normal", v["normal"], lambda im: 0)
    put("laser", v["laser"], lambda im: 0)
    put("appear", v["appear"], lambda im: 0)
    put("hit", v["hit"], lambda im: 0)
    put("big", v["big"], lambda im: -8)
    put("grow", v["grow"], lambda im: (32 - len(im[0])) // 2)
    put("arm", v["arm"], lambda im: (32 - len(im[0])) // 2)
    put("flash", [pad_rows(im, 4 - len(im) // 2 - (0 if len(im) % 2 else 0), 8) for im in v["flash"]],
        lambda im: 16 - len(im[0]) // 2)
    put("debris", v["debris"], lambda im: 16 - len(im[0]) // 2, -8)
    # each background's Vaus bank: its colours in the rows the Vaus
    # touches, around the nine the Vaus keeps at 1-9
    banks = []
    for b in flds:
        region = sorted({b["cols"][ix >> 4 if k == 0 else ix & 15]
                         for ty in VROWS for tx in range(COLS)
                         for t in (b["tiles"][b["N"][ty][tx]],) for byte in t
                         for k, ix in ((0, byte), (1, byte))} - set(VAUS_COLS))
        banks.append(region)
    return {"cells": vc.cells, "frames": frames, "banks": banks}


def report_build():
    fl = fields()
    flds = [build_field(f) for f in fl]
    for b in flds:
        print("  field %d: %2d tiles, %2d colours, pattern %dx%d, %2d cells off it" %
              (b["k"], len(b["tiles"]), len(b["cols"]), b["pw"], b["ph"], len(b["exc"])))
    bk = build_bricks(bricks())
    print("  bricks: %d tiles" % len(bk["tiles"]))
    v = vaus()
    sp = build_sprites(capsules(), enemies(), v)
    print("  sprites: %d cells (%d bytes, %d doubled in VRAM)" % (len(sp["cells"]), 32 * len(sp["cells"]), 128 * len(sp["cells"])))
    vb = build_vaus(v, flds)
    nf = sum(len(f) for f in vb["frames"].values())
    print("  vaus: %d cells in %d frames (%d bytes); the colours each background adds around its nine: %s" %
          (len(vb["cells"]), nf, 32 * len(vb["cells"]), " | ".join(" ".join("%03X" % c for c in r) for r in vb["banks"])))
    savings(fl, v)


def flips(t, w=8):
    """A cell's four orientations, as the tile attribute's flip bits give them."""
    rows = [t[i:i + w] for i in range(0, len(t), w)]
    h = tuple(c for r in rows for c in reversed(r))
    vv = tuple(c for r in reversed(rows) for c in r)
    hv = tuple(c for r in reversed(rows) for c in reversed(r))
    return (t, h, vv, hv)


def canon(t):
    return min(flips(t), key=lambda x: tuple(str(c) for c in x))


def savings(fl, v):
    """What each way of storing less would save, measured."""
    # a brick's shadow as a palette: is dark a colour-for-colour
    # recolouring of normal across the whole background?
    for f in fl[:4]:
        m = {}
        ok = True
        for ty in range(ROWS):
            for tx in range(COLS):
                for a, b in zip(f["norm"][ty][tx], f["dark"][ty][tx]):
                    if m.setdefault(q4(a), q4(b)) != q4(b):
                        ok = False
        nt = len({t for row in f["norm"] for t in row})
        ntf = len({canon(t) for row in f["norm"] for t in row})
        print("    field %d: dark %s; %d normal tiles, %d with flips" %
              (f["k"], "is one recolouring: " + " ".join("%03X>%03X" % e for e in sorted(m.items())) if ok else "is not a recolouring",
               nt, ntf))
    d = doh()
    base = []
    for f in d["normal"]:
        bx = bbox(f)
        base += cells_of(f, bx[0], bx[1], 64, 96)
    print("    doh normal: %d cells, %d with flips; frames 0 and 3 alone %d" %
          (len(set(base)), len({canon(c) for c in base}), len(set(base[:96] + base[288:]))))
    sh = ship()
    s0 = cells_of(sh["frames"][0])
    lg = cells_of(sh["logo"])
    print("    ship frame 0: %d cells, %d with flips; logo %d, %d with flips" %
          (len(set(s0)), len({canon(c) for c in s0}), len(set(lg)), len({canon(c) for c in lg})))
    en = enemies()
    for name in ENEMY_TYPES + ("burst",):
        cs = [c for f in en[name] for c in cells_of(f)]
        print("    %-8s %3d cells, %3d distinct, %3d with flips" % (name, len(cs), len(set(cs)), len({canon(c) for c in cs})))
    cp = capsules()
    cs = [c for ch in CAPSULE_ROWS for f in cp[ch] for c in cells_of(f)]
    print("    capsules %3d cells, %3d distinct, %3d with flips" % (len(cs), len(set(cs)), len({canon(c) for c in cs})))
    vcs = []
    for name in ("normal", "laser", "appear", "hit", "big", "grow", "arm", "flash", "debris"):
        for im in v[name]:
            vcs += cells_of(im)
    print("    vaus without shadows: %d cells, %d distinct, %d with flips" % (len(vcs), len(set(vcs)), len({canon(c) for c in vcs})))
    # and what a run-length code would make of the bytes themselves
    import zlib

    def packbits(data):
        out, i = 0, 0
        while i < len(data):
            j = i
            while j < len(data) and j - i < 128 and data[j] == data[i]:
                j += 1
            if j - i >= 3:
                out += 2
                i = j
            else:
                k = i
                while k < len(data) and k - i < 128 and not (k + 2 < len(data) and data[k] == data[k + 1] == data[k + 2]):
                    k += 1
                out += 1 + (k - i)
                i = k
        return out

    def tilebytes(cells):
        cols = sorted({q4(c) for t in cells for c in t if c is not None})
        pix = {c: i % 15 + 1 for i, c in enumerate(cols)}     # a stand-in index: only the bytes' shape counts here
        return bytes(b for t in cells for b in pack4([0 if c is None else pix[q4(c)] for c in t]))
    blocks = {
        "fields": b"".join(tilebytes(list({t for row in f["norm"] for t in row} |
                                          ({t for row in f["dark"] for t in row} if f["dark"] and f["k"] == 0 else set())))
                           for f in fl),
        "doh": tilebytes(list(set(base))),
        "ship": tilebytes(list(set(s0))),
        "logo": tilebytes(list(set(lg))),
        "enemies": tilebytes(list({c for name in ENEMY_TYPES + ("burst",) for f in en[name] for c in cells_of(f)})),
        "capsules": tilebytes(list(set(cs))),
        "vaus": tilebytes(list(set(vcs))),
    }
    tot = [0, 0, 0]
    for name, data in blocks.items():
        r, z = packbits(data), len(zlib.compress(data, 9))
        tot[0] += len(data)
        tot[1] += r
        tot[2] += z
        print("    %-9s %6d bytes, run-length %6d, zlib %6d" % (name, len(data), r, z))
    print("    all       %6d bytes, run-length %6d, zlib %6d" % tuple(tot))


# ------------------------------------------------------------------ music
# The board's own music: VGMPF's Arkanoid (ARC) pack is the YM2149's
# register log, 44,100 ticks a second, written by the sound driver once
# a 60 Hz frame. Each track is replayed here frame by frame -- the three
# tone channels' periods and levels, the envelope worked out where a
# channel asks for it -- and what reaches the game is the frames where a
# channel changes: its pitch as this machine's phase increment and its
# level on the machine's linear 4-bit scale. None of the five uses the
# noise generator.
TRACKS = [("STORY", "01 - Story.vgz"), ("START", "02 - Round Start.vgz"), ("DOH", "04 - Doh Round.vgz"),
          ("OVER", "05 - Game Over.vgz"), ("ENDING", "06 - Ending.vgz")]
# The AY's sixteen levels are logarithmic, about 3 dB apart; the machine's
# are linear. round(15 x amplitude) from the datasheet's table, a quiet
# note kept at 1 rather than lost.
AY_LIN = [0, 1, 1, 1, 1, 1, 1, 2, 3, 4, 5, 7, 9, 10, 13, 15]
ENGINE_HZ = 8375000 / 256 / 65536       # one step of a voice's increment, in Hz (04-system.md section 4.4)


def vgm_writes(path):
    d = gzip.open(path).read()
    assert d[:4] == b"Vgm ", path
    clock = struct.unpack_from("<I", d, 0x74)[0]
    i = 0x34 + struct.unpack_from("<I", d, 0x34)[0]
    t, out = 0, []
    while True:
        c = d[i]
        if c == 0x66:
            break
        if c == 0xA0:
            out.append((t, d[i + 1], d[i + 2]))
            i += 3
        elif c == 0x61:
            t += struct.unpack_from("<H", d, i + 1)[0]
            i += 3
        elif c == 0x62:
            t += 735
            i += 1
        elif c == 0x63:
            t += 882
            i += 1
        elif 0x70 <= c <= 0x7F:
            t += (c & 15) + 1
            i += 1
        else:
            raise ValueError("%s: VGM command $%02X" % (path, c))
    return clock, out, t


def env_level(shape, dt, ep, clock):
    """The AY envelope's level dt seconds after its shape was written."""
    step = 16 * (ep or 1) / clock
    s = int(dt / step)
    cont, att, alt, hold = (shape >> 3) & 1, (shape >> 2) & 1, (shape >> 1) & 1, shape & 1
    cycle, pos = divmod(s, 16)
    if cycle == 0:
        return pos if att else 15 - pos
    if not cont:
        return 0
    if hold:
        return (15 if att else 0) ^ (15 if alt else 0)
    up = att ^ (alt and cycle & 1)
    return pos if up else 15 - pos


def track(path):
    """A track as events: (frame, [(channel, increment, level)])."""
    clock, ws, total = vgm_writes(path)
    t0 = ws[0][0]
    n = (total - t0) // 735 + 1
    regs = [0] * 16
    env_t = t0
    wi = 0
    prev = [None] * 3
    events = []
    for f in range(n):
        while wi < len(ws) and ws[wi][0] < t0 + f * 735 + 367:
            _, r, val = ws[wi]
            regs[r] = val
            if r == 13:
                env_t = ws[wi][0]
            wi += 1
        now = t0 + f * 735
        ch = []
        for c in range(3):
            tp = (regs[2 * c] | (regs[2 * c + 1] & 15) << 8) or 1
            amp = regs[8 + c]
            level = env_level(regs[13] & 15, (now - env_t) / 44100, regs[11] | regs[12] << 8, clock) \
                if amp & 16 else amp & 15
            vol = AY_LIN[level] if not (regs[7] >> c) & 1 else 0
            inc = min(65535, round(clock / (16 * tp) / ENGINE_HZ)) if vol else 0
            st = (inc, vol)
            if st != prev[c]:
                ch.append((c, inc, vol))
                prev[c] = st
        if ch:
            events.append((f, ch))
    return events, n


def pack_track(events, n):
    """wait, mask, then increment and level for each channel in the mask;
    a wait of 255 with nothing in the mask is a filler, and the stream
    ends on mask $80 after the track's last frame."""
    out, last = [], 0
    for f, ch in events:
        wait = f - last
        while wait > 255:
            out += [255, 0]
            wait -= 255
        out += [wait, sum(1 << c for c, _, _ in ch)]
        for c, inc, vol in ch:
            out += [inc & 255, inc >> 8, vol]
        last = f
    wait = n - last
    while wait > 255:
        out += [255, 0]
        wait -= 255
    return out + [wait, 0x80]


def music():
    out = []
    for name, fn in TRACKS:
        ev, n = track(os.path.join(ART, "vgm", fn))
        out.append((name, pack_track(ev, n), n, len(ev)))
    return out


# ============================================================ the output
# Two files. **ARKANOID.DAT** is everything the video hardware reads --
# tiles and sprite patterns, already in the form VRAM holds them -- and
# the game streams it from the flash straight into VRAM, at the flash's
# own 34 clocks a byte, when a phase needs it (04-system.md section 5.4:
# a tile set from SPI flash is a load loop, not a DMA engine). The PRG
# carries only what the CPU itself reads while it plays: the rounds, the
# field models, the Vaus's cells it draws into the background, palettes
# and tables. **arkanoid_art.act** is that, and the offsets of every
# block in the data file.
DAT = os.path.join(ART, "ARKANOID.DAT")
KIND = {ch: i + 1 for i, ch in enumerate(BRICKS)}     # W 1 ... S 9, X 10 (gold)


class Dat:
    def __init__(self):
        self.data = bytearray()
        self.blocks = []

    def add(self, name, data):
        self.blocks.append((name, len(self.data), len(data)))
        self.data += bytes(data)


def double(cell):
    """A logical 8 x 8 cell as the 16 x 16 raster sprite pattern that
    shows it over a doubled mode: every pixel twice, every row twice."""
    out = []
    for y in range(8):
        px = []
        for b in cell[y * 4:(y + 1) * 4]:
            px += [b >> 4, b >> 4, b & 15, b & 15]
        row = [(px[i] << 4) | px[i + 1] for i in range(0, 16, 2)]
        out += row + row
    return out


def pack_round(rows):
    """A round as its first row, its row count, and seven bytes a row --
    thirteen kinds a nibble each, 0 no brick."""
    used = [i for i, r in enumerate(rows) if r != "." * 13]
    f, l = used[0], used[-1]
    out = [f, l - f + 1]
    for r in rows[f:l + 1]:
        nib = [0 if c == "." else KIND[c] for c in r] + [0]
        out += [(nib[i] << 4) | nib[i + 1] for i in range(0, 14, 2)]
    return out


# The blocks sheet's pieces under the backgrounds (--zoom blocks 0 128 96
# 64): at x 56 a 32 x 8 strip six times down, the four cells of a gate
# in the top of the frame from shut to open -- its bars going from the
# middle outward, which is what the round frames on StrategyWiki that
# caught an enemy coming in show; and at x 32 three columns of five
# cells, the right wall's exit in its three frames of crackle, a pipe
# end above and below.
def gates_exit(fl):
    s = Sheet("blocks")
    gate = [[cell(s, 56 + 8 * c, 128 + 8 * k) for c in range(4)] for k in range(6)]
    ex = [[cell(s, 32 + 8 * k, 128 + 8 * r) for r in range(5)] for k in range(3)]
    q = lambda t: tuple(q4(c) for c in t)  # noqa: E731
    g0 = [q(t) for t in gate[0]]
    row0 = [q(fl[0]["norm"][0][tx]) for tx in range(COLS)]
    pos = [tx for tx in range(COLS - 3) if row0[tx:tx + 4] == g0]
    near = sorted((sum(a != b for t, u in zip(row0[tx:tx + 4], g0) for a, b in zip(t, u)), tx) for tx in range(COLS - 3))[:4]
    return gate, ex, pos, near


# ------------------------------------------------------------ DOH's round
# Round 33 on StrategyWiki (Arkanoid_Stage_33.png) puts DOH's 62 x 96
# face at x 82, y 56 of the arcade's screen -- y 40 here, a tile row --
# on black, with the wall's tubes round him on the red field. So the
# round's background is one picture: the red panel, the wall pasted with
# its hole at DOH's place and the hole black; and DOH is cells 10-17 x
# 5-16 over it, his picture two pixels in from their left.
DOH_X, DOH_Y = 82, 40
DOH_TX, DOH_TY, DOH_W, DOH_H = 10, 5, 8, 12


def doh_round(fl):
    """The round's background picture (rows of colours), DOH's frames
    composed over it, and where the wall went."""
    d = doh()
    wall = d["wall"]
    # the hole is the sheet's transparency inside the wall: what cannot be
    # reached through transparency from the piece's own edge
    H, W = len(wall), len(wall[0])
    out = set()
    stack = [(x, y) for y in range(H) for x in range(W) if (x in (0, W - 1) or y in (0, H - 1)) and wall[y][x] is None]
    out.update(stack)
    while stack:
        x, y = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = x + dx, y + dy
            if 0 <= a < W and 0 <= b < H and (a, b) not in out and wall[b][a] is None:
                out.add((a, b))
                stack.append((a, b))
    hole = [(x, y) for y in range(H) for x in range(W) if wall[y][x] is None and (x, y) not in out]
    for x, y in hole:
        wall[y][x] = (255, 255, 255)
    hx0, hy0 = min(x for x, _ in hole), min(y for _, y in hole)
    hx1, hy1 = max(x for x, _ in hole), max(y for _, y in hole)
    wx, wy = DOH_X - hx0, DOH_Y - hy0
    pic = [[fl[4]["norm"][y // 8][x // 8][(y % 8) * 8 + x % 8] for x in range(224)] for y in range(240)]
    for y, row in enumerate(wall):
        for x, c in enumerate(row):
            if c is not None and 0 <= wx + x < 224 and 0 <= wy + y < 240:
                pic[wy + y][wx + x] = (0, 0, 0) if c == (255, 255, 255) else c
    # DOH's pixels marked apart from the background's, so that a palette
    # that recolours him leaves the wall behind him alone
    frames = {}
    for k in ("normal", "hit", "dying", "death"):
        out = []
        for f in d[k]:
            bx = bbox(f)
            im = [[("b", c) for c in row] for row in pic]
            for y in range(bx[3]):
                for x in range(bx[2]):
                    c = f[bx[1] + y][bx[0] + x]
                    if c is not None:
                        im[DOH_Y + y][DOH_X + x] = ("d", c)
            out.append(cells_of(im, DOH_TX * 8, DOH_TY * 8, DOH_W * 8, DOH_H * 8))
        frames[k] = out
    return pic, frames, (wx, wy, hx1 - hx0 + 1, hy1 - hy0 + 1)


def doh_recolour(base, fr):
    """The one change of DOH's colours that turns frame `base` into `fr`,
    his background untouched -- {old: new} -- or None, with the pixels
    that stop it."""
    m, bad = {}, 0
    for bt, ft in zip(base, fr):
        for (bk, bc), (fk, fc) in zip(bt, ft):
            if bk != fk or (bk == "b" and bc != fc) or m.setdefault(q4(bc), q4(fc)) != q4(fc):
                bad += 1
    return ({a: v for a, v in m.items() if a != v} if not bad else None), bad


def doh_build(fl):
    """DOH's round as tiles. The background: one picture, its own tiles
    and map. DOH: his four normal frames' cells over it, in a palette
    whose first entries are his colours and whose last are the
    background's inside his cells, kept apart even where a colour is the
    same, so that the frames the sheet shows him hit and dying -- each
    one of his normal frames with one of his colours changed -- are that
    frame and a palette write. His last two death frames, the wireframe,
    are tiles of their own."""
    pic, frames, where = doh_round(fl)
    bgc = cells_of(pic)
    bt, bi = [], {}
    bmap = []
    for c in bgc:
        if c not in bi:
            bi[c] = len(bt)
            bt.append(c)
        bmap.append(bi[c])
    bcols = sorted({q4(c) for t in bt for c in t})
    assert len(bcols) <= 16, ("DOH's background", len(bcols))
    bpix = {c: i for i, c in enumerate(bcols)}
    normal = frames["normal"]
    dcols = sorted({q4(c) for fr in normal for t in fr for k, c in t if k == "d"})
    ecols = sorted({q4(c) for fr in normal for t in fr for k, c in t if k == "b"})
    assert len(dcols) + len(ecols) <= 16, ("DOH's palette", dcols, ecols)
    dpix = {("d", c): i for i, c in enumerate(dcols)}
    dpix.update({("b", c): len(dcols) + i for i, c in enumerate(ecols)})
    tiles, index = [], {}

    def ti(t):
        if t not in index:
            index[t] = len(tiles)
            tiles.append(t)
        return index[t]
    maps = [[ti(c) for c in fr] for fr in normal]
    # hit and dying: a normal frame and one colour of his changed
    looks = []
    for k in ("hit", "dying"):
        for i, fr in enumerate(frames[k]):
            best = None
            for b in range(4):
                m, bad = doh_recolour(normal[b], fr)
                if best is None or bad < best[2]:
                    best = (b, m, bad)
            looks.append((k, i) + best)
    # the wireframe: tiles of its own, in the death palette
    wire = frames["death"][8:10]
    wcols = sorted({q4(c) for fr in wire for t in fr for _, c in t})
    assert len(wcols) <= 16, ("the wireframe", wcols)
    wt, wi = [], {}
    wmaps = []
    for fr in wire:
        row = []
        for c in fr:
            if c not in wi:
                wi[c] = len(wt)
                wt.append(c)
            row.append(wi[c])
        wmaps.append(row)
    return {"pic": pic, "where": where,
            "bg_pal": bcols + [0] * (16 - len(bcols)), "bg_tiles": [pack4([bpix[q4(c)] for c in t]) for t in bt],
            "bg_map": bmap,
            "pal": dcols + ecols + [0] * (16 - len(dcols) - len(ecols)), "ndoh": len(dcols),
            "tiles": [pack4([dpix[(k, q4(c))] for k, c in t]) for t in tiles], "maps": maps,
            "looks": looks,
            "wire_pal": wcols + [0] * (16 - len(wcols)),
            "wire_tiles": [pack4([wcols.index(q4(c)) for _, c in t]) for t in wt], "wire_maps": wmaps}


# -------------------------------------------------------------- the intro
# The mothership over the story, as the intro shows it: frame 0 whole;
# the frames that light it, and the green rings the Vaus rises out of
# it in, as the cells they change; the red flashes it is hit in as
# palettes, each a recolouring of the lit frame (--ship lists which
# frame is what). Black behind it, where the sheet is transparent. The
# ARKANOID logo is its own tiles in its own palette; the Vaus flying
# away is sprites, fifteen frames on the Vaus sheet.
SHIP_W, SHIP_H = 24, 11


def intro_build(v):
    sh = ship()
    fr = sh["frames"]

    def black(im, w, h):
        """Transparent and past the edge both black, to w x h."""
        rows = [[c if c is not None else (0, 0, 0) for c in row] + [(0, 0, 0)] * (w - len(row)) for row in im]
        return rows + [[(0, 0, 0)] * w for _ in range(h - len(rows))]

    def pad(im, w, h):
        """Past the edge transparent too, to w x h: the space behind the
        ship stays its own colour, index 0, which no flash changes -- the
        flashes redden the ship's black and not the black around it."""
        return [row + [None] * (w - len(row)) for row in im] + [[None] * w for _ in range(h - len(im))]
    cs = [cells_of(pad(f, SHIP_W * 8, SHIP_H * 8), 0, 0, SHIP_W * 8, SHIP_H * 8) for f in fr]
    tiles, index = [], {}

    def ti(t):
        if t not in index:
            index[t] = len(tiles)
            tiles.append(t)
        return index[t]
    base = [ti(c) for c in cs[0]]
    deltas, pals = {}, {}
    for i in range(1, 20):
        for b in (2, 11):
            if b < i:
                m = {}
                if all(m.setdefault(a and q4(a), c and q4(c)) == (c and q4(c))
                       for ta, tc in zip(cs[b], cs[i]) for a, c in zip(ta, tc)) and m.get(None) is None:
                    pals[i] = (b, {a: c for a, c in m.items() if a is not None})
                    break
        else:
            deltas[i] = [(j, ti(c)) for j, c in enumerate(cs[i]) if c != cs[0][j]]
    cols = sorted({q4(c) for t in tiles for c in t if c is not None})
    if len(cols) > 15:
        # which frames brought which colours: the diagnosis when the
        # ship's bank overflows
        c0 = {q4(c) for j in base for c in tiles[j] if c is not None}
        for i in range(1, 20):
            if i in pals:
                print("    frame %2d: a palette over frame %d" % (i, pals[i][0]))
            else:
                new = {q4(c) for _, j in deltas[i] for c in tiles[j] if c is not None} - c0
                print("    frame %2d: %2d cells, new colours %s" % (i, len(deltas[i]), " ".join("%03X" % c for c in sorted(new))))
    assert len(cols) <= 15, ("the ship", cols)
    # index 0 the space behind it, black; its own colours from 1
    pix = {c: i + 1 for i, c in enumerate(cols)}
    pix[None] = 0
    ship_pal = [0x000] + cols + [0] * (15 - len(cols))
    flashes = {i: [0x000] + [m.get(c, c) for c in cols] + [0] * (15 - len(cols)) for i, (b, m) in pals.items()}
    logo = black(sh["logo"], 200, 48)
    lcs = cells_of(logo, 0, 0, 200, 48)
    lt, li = [], {}
    lmap = []
    for c in lcs:
        if c not in li:
            li[c] = len(lt)
            lt.append(c)
        lmap.append(li[c])
    lcols = sorted({q4(c) for t in lt for c in t})
    assert len(lcols) <= 16, ("the logo", lcols)
    # the Vaus flying away: sprites in a palette of their own
    esc = Cells()
    ecols = sorted(set(colours(*v["escape"])))
    assert len(ecols) <= 15, ecols
    em = {c: i + 1 for i, c in enumerate(ecols)}
    efr = []
    for im in v["escape"]:
        w, h = len(im[0]), len(im)
        efr.append(((w + 7) // 8, (h + 7) // 8, w, h, esc.image(im, em)))
    return {"tiles": [pack4([pix[None] if c is None else pix[q4(c)] for c in t]) for t in tiles],
            "pal": ship_pal, "base": base,
            "deltas": deltas, "flashes": flashes, "pals": pals,
            "logo_tiles": [pack4([lcols.index(q4(c)) for c in t]) for t in lt],
            "logo_pal": lcols + [0] * (16 - len(lcols)), "logo_map": lmap,
            "esc_cells": esc.cells, "esc_frames": efr, "esc_pal": [0] + ecols + [0] * (15 - len(ecols))}


def show_scenes():
    """--scenes: what the DOH round and the intro come to."""
    fl = fields()
    db = doh_build(fl)
    print("  DOH: wall at %s; background %d tiles; DOH %d tiles (%d of his colours); wireframe %d tiles" %
          (db["where"], len(db["bg_tiles"]), len(db["tiles"]), db["ndoh"], len(db["wire_tiles"])))
    for k, i, b, m, bad in db["looks"]:
        print("    %s %2d: normal %d with %s%s" % (k, i, b, m, "" if not bad else "  -- %d pixels are not a recolouring" % bad))
    ib = intro_build(vaus())
    print("  ship: %d tiles; flashes %s; deltas %s; logo %d tiles; escape %d sprite cells" %
          (len(ib["tiles"]), sorted(ib["flashes"]), {i: len(d) for i, d in ib["deltas"].items()},
           len(ib["logo_tiles"]), len(ib["esc_cells"])))


def vaus_banks(b):
    """A background's two Vaus banks: its colours in the rows the Vaus
    touches, left of column `split` and from it, around the Vaus's nine
    at 1-9 -- one bank does not hold them all for the blue background."""
    def region(t0, t1):
        cs = set()
        for ty in VROWS:
            for tx in range(t0, t1):
                for byte in b["tiles"][b["N"][ty][tx]]:
                    cs.add(b["cols"][byte >> 4])
                    cs.add(b["cols"][byte & 15])
        return sorted(cs - set(VAUS_COLS))
    for split in range(1, COLS):
        ra, rb = region(0, split), region(split, COLS)
        if len(ra) <= 7 and len(rb) <= 7:
            break
    else:
        raise AssertionError("field %d: no split of its Vaus rows fits two banks" % b["k"])

    def bank(extra):
        pal = [extra[0] if extra else 0] + VAUS_COLS + extra[1:] + [0] * (7 - len(extra[1:]) - (0 if extra else 0))
        pal = pal[:16] + [0] * (16 - len(pal[:16]))
        where = {c: i for i, c in enumerate(pal) if i == 0 and extra or 1 <= i <= 9 or (i >= 10 and c in extra)}
        remap = [where.get(c, 0) for c in b["pal"]]
        return pal, remap
    (pa, ma), (pb, mb) = bank(ra), bank(rb)
    return split, pa, ma, pb, mb


def build():
    """Every piece of the output, in the order the two files hold them."""
    rs = rounds()
    fnt, fallback = font()
    fl = fields()
    flds = [build_field(f) for f in fl]
    bk = build_bricks(bricks())
    v = vaus()
    cp, en = capsules(), enemies()
    dat = Dat()
    o = {"flds": flds, "bk": bk, "v": v, "dat": dat, "rounds": [pack_round(r) for r in rs],
         "fallback": fallback}
    # the fields' tiles, one block each
    for b in flds:
        dat.add("FIELD%d" % b["k"], [x for t in b["tiles"] for x in t])
        assert len(b["tiles"]) <= T_BRICK - T_FIELD, (b["k"], len(b["tiles"]))
    dat.add("BRICKS", [x for t in bk["tiles"] for x in t])
    # the font: ink is index 1, whatever bank the text is in
    order = FONT + '@"'
    ftiles = []
    for ch in order:
        g = fnt[ch]
        ix = [(g[y] >> (7 - x)) & 1 for y in range(8) for x in range(8)]
        ftiles += pack4(ix)
    dat.add("FONT", ftiles)
    o["fontmap"] = order
    # sprites: the capsules, the burst, the ball, its shadow, the beam and
    # DOH's shot in one block that stays; each enemy's in a block of its
    # own that a round streams over the last one
    fixed = set(SPR_FIXED)
    common = Cells()
    o["cap_pal"], o["cap"] = [], {}
    for ch in CAPSULE_ROWS:
        extra = sorted(set(colours(*cp[ch])) - fixed, key=lambda c: sum((c >> s) & 15 for s in (0, 4, 8)))
        assert len(extra) <= 2, (ch, extra)
        o["cap_pal"].append(extra + [0] * (2 - len(extra)))
        m = spr_map(extra, CAP_SLOT)
        o["cap"][ch] = [common.image(f, m) for f in cp[ch]]
    m = spr_map([0xAAA, 0x777], GREY_SLOT)
    o["burst"] = [common.image(f, m) for f in en["burst"]]
    o["ball"] = common.image(v["ball"], m)[0]
    o["ball_shadow"] = common.image([[(0, 0, 0) if c else None for c in row] for row in v["ball"]], m)[0]
    assert [row[13:16] for row in v["beams"]] == [row[0:3] for row in v["beams"]], "the two beams differ"
    o["beam"] = common.image([row[0:3] for row in v["beams"]], m)[0]
    o["shot"] = [common.image([[SHOT_RGB.get(ch) for ch in row] for row in ph], m)[0] for ph in DOH_SHOT]
    dat.add("SPRITES", [x for c in common.cells for x in double(c)])
    o["n_common"] = len(common.cells)
    o["enemy_pal"], o["enemy"], o["n_enemy"] = [], {}, {}
    for name in ENEMY_TYPES:
        extra = sorted(set(colours(*en[name])) - fixed)
        assert len(extra) <= 4, (name, extra)
        o["enemy_pal"].append(extra + [0] * (4 - len(extra)))
        ec = Cells()
        m = spr_map(extra, ENEMY_SLOT)
        o["enemy"][name] = [ec.image(f, m) for f in en[name]]
        o["n_enemy"][name] = len(ec.cells)
        dat.add("ENEMY_" + name.upper(), [x for c in ec.cells for x in double(c)])
    o["spr_pal"] = [0] + SPR_FIXED + [0] * 6 + [0xAAA, 0x777, 0]
    # the Vaus: its cells stay in the PRG, where the CPU reads them to
    # draw it into the background; its shadow is drawn from its own
    # cells at run time, so none are stored for it
    vc = Cells()
    vm = {c: i + 1 for i, c in enumerate(VAUS_COLS)}
    frames = []
    groups = []

    def put(name, ims, ox_of, oy=0):
        groups.append((name, len(frames), len(ims)))
        for im in ims:
            frames.append(((len(im[0]) + 7) // 8, (len(im) + 7) // 8, ox_of(im), oy, vc.image(im, vm)))
    put("normal", v["normal"], lambda im: 0)
    put("laser", v["laser"], lambda im: 0)
    put("big", v["big"], lambda im: -8)
    put("appear", v["appear"], lambda im: 0)
    put("hit", v["hit"], lambda im: 0)
    put("grow", v["grow"], lambda im: (32 - len(im[0])) // 2)
    put("arm", v["arm"], lambda im: (32 - len(im[0])) // 2)
    put("flash", [pad_rows(im, 4 - len(im) // 2, 8) for im in v["flash"]], lambda im: 16 - len(im[0]) // 2)
    put("debris", v["debris"], lambda im: 16 - len(im[0]) // 2, -8)
    o["vaus_cells"], o["vaus_frames"], o["vaus_groups"] = vc.cells, frames, groups
    o["vaus_banks"] = [vaus_banks(b) for b in flds]
    # the gates in the top of the frame, and the exit in its right side
    gate, ex, pos, near = gates_exit(fl)
    assert len(pos) == 2, "the gates' closed frame is not in the frame's top row: %s" % near
    o["gates"] = pos
    for b in flds:
        pix = {c: i for i, c in enumerate(b["cols"])}
        assert all(q4(c) in pix for f in gate for t in f for c in t), "a gate colour is not in field %d" % b["k"]
        dat.add("GATE%d" % b["k"], [x for f in gate for t in f for x in pack4([pix[q4(c)] for c in t])])
    vi = {c: i + 1 for i, c in enumerate(VAUS_COLS)}
    assert all(q4(c) in vi for f in ex for t in f for c in t), "an exit colour is not the Vaus's"
    dat.add("EXIT", [x for f in ex for t in f for x in pack4([vi[q4(c)] for c in t])])
    # a life, as the arcade shows it under the field: the small Vaus
    # beside the first panel at y 240, two cells
    s = Sheet("fields")
    icon = [[s.at(8 + x, 240 + y) for x in range(16)] for y in range(8)]
    hc = sorted(set(colours(icon)))
    assert len(hc) <= 15, hc
    hm = {c: i + 1 for i, c in enumerate(hc)}
    dat.add("HUD", [x for t in (0, 8) for x in pack4([0 if icon[y][t + xx] is None else hm[q4(icon[y][t + xx])]
                                                       for y in range(8) for xx in range(8)])])
    o["hud_pal"] = [0] + hc + [0] * (15 - len(hc))
    o["music"] = music()
    # DOH's round: its background, DOH, and his wireframe, each a block
    db = doh_build(fl)
    o["doh"] = db
    # a file on a drive is at most 65,535 bytes -- its catalogue entry's
    # length is two bytes (tools/cool8disk.py) -- and all of this is more:
    # the rounds' blocks are ARKANOID.DAT, the intro's and DOH's are a
    # second file, ARKSCENE.DAT, and bit 7 of a block's high offset byte
    # says which
    dat = o["dat2"] = Dat()
    dat.add("DOHBG", [x for t in db["bg_tiles"] for x in t])
    dat.add("DOH", [x for t in db["tiles"] for x in t])
    dat.add("WIRE", [x for t in db["wire_tiles"] for x in t])
    for name, n in (("DOHBG", len(db["bg_tiles"])), ("DOH", len(db["tiles"])), ("WIRE", len(db["wire_tiles"]))):
        assert n <= 256, (name, n)
    # its own Vaus banks, as a sixth background: its tiles are not panel
    # 4's, so neither is the numbering the Vaus's rows come in
    dohf = {"k": 5, "tiles": db["bg_tiles"], "pal": db["bg_pal"],
            "cols": sorted({q4(c) for row in db["pic"] for c in row}),
            "N": [[db["bg_map"][ty * COLS + tx] for tx in range(COLS)] for ty in range(ROWS)]}
    o["vaus_banks"].append(vaus_banks(dohf))
    # the intro: the logo's tiles, then the ship's, one run over pattern
    # banks 1 and 2; and the Vaus flying off, sprites doubled
    ib = intro_build(v)
    o["intro"] = ib
    assert len(ib["logo_tiles"]) + len(ib["tiles"]) <= 512, "the intro does not fit two pattern banks"
    dat.add("INTRO", [x for t in ib["logo_tiles"] + ib["tiles"] for x in t])
    dat.add("ESCAPE", [x for c in ib["esc_cells"] for x in double(c)])
    return o


def act(o):
    L = []
    w = L.append
    w("; Arkanoid's art, rounds and tables, generated by tools/mkarkanoid.py from")
    w("; the ripped arcade sheets in assets/arkanoid/. Generated: do not edit.")
    w("; The tiles and sprite patterns are in ARKANOID.DAT beside it, whose")
    w("; blocks these offsets name; the game streams them into VRAM.")
    w("")
    for f, d in enumerate((o["dat"], o["dat2"])):
        w("; %s" % ("ARKANOID.DAT, the rounds'" if f == 0 else "ARKSCENE.DAT, the intro's and DOH's: bit 7 of DH_ says so"))
        for name, off, n in d.blocks:
            # an offset in the file is 24 bits; a CONST is a word
            w("CONST D_%s = %d" % (name, off & 0xFFFF))
            w("CONST DH_%s = %d" % (name, (off >> 16) | (f << 7)))
            w("CONST N_%s = %d" % (name, n))
    w("")
    w("; the 32 rounds: first row, row count, then 7 bytes a row, a nibble a")
    w("; brick: 0 none, 1-8 white orange cyan green red blue magenta yellow,")
    w("; 9 silver, 10 gold")
    offs, blob = [], []
    for r in o["rounds"]:
        offs.append(len(blob))
        blob += r
    w("CARD ARRAY rnd_off(32) = [%s]" % " ".join(str(x) for x in offs))
    w("BYTE ARRAY rnd_data(%d) = [" % len(blob))
    for i in range(0, len(blob), 32):
        w("  " + " ".join("$%02X" % b for b in blob[i:i + 32]))
    w("]")
    w("")
    w("; the five backgrounds: blue, green, circuit, grey (rounds 1-32 in turn)")
    w("; and DOH's red. Each: its palette, its frame's cells (row 0, then")
    w("; column 0 and column 27 from row 1), a pattern of pw x ph cells normal")
    w("; and dark, and the cells the pattern does not predict (x y normal dark)")
    flds = o["flds"]
    w("CARD ARRAY fld_pal(80) = [%s]" % " ".join("$%03X" % c for b in flds for c in b["pal"]))
    w("BYTE ARRAY fld_n(5) = [%s]" % " ".join(str(len(b["tiles"])) for b in flds))
    w("BYTE ARRAY fld_frame(%d) = [" % (5 * 86))
    for b in flds:
        w("  " + " ".join(str(x) for x in b["frame"]))
    w("]")
    w("BYTE ARRAY fld_pw(5) = [%s]" % " ".join(str(b["pw"]) for b in flds))
    w("BYTE ARRAY fld_ph(5) = [%s]" % " ".join(str(b["ph"]) for b in flds))
    w("BYTE ARRAY fld_pn(320) = [")
    for b in flds:
        w("  " + " ".join(str(x) for x in b["pn"] + [0] * (64 - len(b["pn"]))))
    w("]")
    w("BYTE ARRAY fld_pd(320) = [")
    for b in flds:
        w("  " + " ".join(str(x) for x in b["pd"] + [0] * (64 - len(b["pd"]))))
    w("]")
    eo, eb = [], []
    for b in flds:
        eo.append(len(eb))
        for e in b["exc"]:
            eb += list(e)
    eo.append(len(eb))
    w("CARD ARRAY fld_exc_off(6) = [%s]" % " ".join(str(x) for x in eo))
    w("BYTE ARRAY fld_exc(%d) = [" % len(eb))
    for i in range(0, len(eb), 32):
        w("  " + " ".join(str(x) for x in eb[i:i + 32]))
    w("]")
    w("")
    w("CARD ARRAY brk_pal(16) = [%s]" % " ".join("$%03X" % c for c in o["bk"]["pal"]))
    w("")
    w("; the font's order: tile T_FONT + i is character i of this string")
    w('BYTE ARRAY fontmap = "%s"' % o["fontmap"].replace('"', "'"))
    w("")
    w("; sprites: one palette bank for all of them. The capsule's two slots")
    w("; (11, 12) and the round's enemy's four (7-10) are filled when they")
    w("; change; cells are numbered in their block, a pattern of 128 bytes")
    w("CARD ARRAY spr_pal(16) = [%s]" % " ".join("$%03X" % c for c in o["spr_pal"]))
    w("CARD ARRAY cap_pal(14) = [%s]" % " ".join("$%03X" % c for p in o["cap_pal"] for c in p))
    w("CARD ARRAY enemy_pal(16) = [%s]" % " ".join("$%03X" % c for p in o["enemy_pal"] for c in p))
    w("; a capsule frame is its left and right cells; letters in CAPSULE order")
    w('BYTE ARRAY cap_order = "%s"' % CAPSULE_ROWS)
    w("BYTE ARRAY cap_cells(112) = [")
    for ch in CAPSULE_ROWS:
        w("  " + " ".join(str(x) for f in o["cap"][ch] for x in f))
    w("]")
    w("BYTE ARRAY burst_cells(24) = [%s]" % " ".join(str(x) for f in o["burst"] for x in f))
    w("CONST SC_BALL = %d" % o["ball"])
    w("CONST SC_SHADOW = %d" % o["ball_shadow"])
    w("CONST SC_BEAM = %d" % o["beam"])
    w("BYTE ARRAY shot_cells(3) = [%s]" % " ".join(str(x) for x in o["shot"]))
    w("CONST N_COMMON = %d" % o["n_common"])
    for i, name in enumerate(ENEMY_TYPES):
        fr = o["enemy"][name]
        w("CONST EN_%s_FRAMES = %d" % (name.upper(), len(fr)))
        w("BYTE ARRAY en_%s(%d) = [%s]" % (name, 4 * len(fr), " ".join(str(x) for f in fr for x in f)))
    w("")
    w("; the Vaus, drawn into the background: 4 bpp cells, 0 see-through and")
    w("; its nine colours at 1-9 in every background's Vaus banks; a frame is")
    w("; width and height in cells, x and y offsets in pixels, then its cells")
    for name, first, n in o["vaus_groups"]:
        w("CONST VF_%s = %d" % (name.upper(), first))
        w("CONST VN_%s = %d" % (name.upper(), n))
    fo, fb = [], []
    for wc, hc, ox, oy, cells in o["vaus_frames"]:
        fo.append(len(fb))
        fb += [wc, hc, ox & 255, oy & 255] + cells
    w("CARD ARRAY vf_off(%d) = [%s]" % (len(fo), " ".join(str(x) for x in fo)))
    w("BYTE ARRAY vf_data(%d) = [" % len(fb))
    for i in range(0, len(fb), 32):
        w("  " + " ".join(str(x) for x in fb[i:i + 32]))
    w("]")
    w("BYTE ARRAY vaus_cells(%d) = [" % (32 * len(o["vaus_cells"])))
    for c in o["vaus_cells"]:
        w("  " + " ".join("$%02X" % b for b in c))
    w("]")
    w("; each background's Vaus banks: left of its split column, and from it;")
    w("; and the maps from its field colours to them")
    nb = len(o["vaus_banks"])
    w("; the sixth is DOH's round's")
    w("BYTE ARRAY vb_split(%d) = [%s]" % (nb, " ".join(str(vb[0]) for vb in o["vaus_banks"])))
    w("CARD ARRAY vb_pal(%d) = [%s]" % (32 * nb, " ".join("$%03X" % c for vb in o["vaus_banks"] for c in vb[1] + vb[3])))
    w("BYTE ARRAY vb_map(%d) = [%s]" % (32 * nb, " ".join(str(c) for vb in o["vaus_banks"] for c in vb[2] + vb[4])))
    w("")
    ib = o["intro"]
    nl = len(ib["logo_tiles"])
    w("; the intro: the logo's tiles then the ship's, one run of tile numbers")
    w("; over pattern banks 1 and 2 (a number's bit 8 picks the bank); the")
    w("; ship's frame 0 as a map; each frame that changes cells as its (cell,")
    w("; tile) pairs, from ship_doff; the frames that only recolour as a")
    w("; palette over the frame they recolour; the Vaus flying off as")
    w("; sprites: width and height in cells, then in pixels, then its cells")
    w("CONST SHIP_W = %d" % SHIP_W)
    w("CONST SHIP_H = %d" % SHIP_H)
    w("CONST LOGO_W = 25")
    w("CONST LOGO_H = 6")
    w("CARD ARRAY logo_pal(16) = [%s]" % " ".join("$%03X" % c for c in ib["logo_pal"]))
    w("CARD ARRAY ship_pal(16) = [%s]" % " ".join("$%03X" % c for c in ib["pal"]))
    w("BYTE ARRAY logo_map(%d) = [%s]" % (len(ib["logo_map"]), " ".join(str(t) for t in ib["logo_map"])))
    w("CARD ARRAY ship_map(%d) = [" % len(ib["base"]))
    for r in range(SHIP_H):
        w("  " + " ".join(str(nl + t) for t in ib["base"][r * SHIP_W:(r + 1) * SHIP_W]))
    w("]")
    doff, dl = [0] * 20, []
    for i in range(20):
        if i in ib["deltas"]:
            doff[i] = len(dl) + 1             # 0 is a frame with none
            dl.append(len(ib["deltas"][i]))
            for j, t in ib["deltas"][i]:
                dl += [j, nl + t]
    w("CARD ARRAY ship_doff(20) = [%s]" % " ".join(str(x) for x in doff))
    w("CARD ARRAY ship_dl(%d) = [" % len(dl))
    for i in range(0, len(dl), 24):
        w("  " + " ".join(str(x) for x in dl[i:i + 24]))
    w("]")
    fl_ = sorted(ib["flashes"])
    w("; frames that are a palette: which, over which frame, and the palette")
    w("CONST SHIP_NFLASH = %d" % len(fl_))
    w("BYTE ARRAY ship_ff(%d) = [%s]" % (len(fl_), " ".join(str(i) for i in fl_)))
    w("BYTE ARRAY ship_fb(%d) = [%s]" % (len(fl_), " ".join(str(ib["pals"][i][0]) for i in fl_)))
    w("CARD ARRAY ship_flash(%d) = [" % (16 * len(fl_)))
    for i in fl_:
        w("  " + " ".join("$%03X" % c for c in ib["flashes"][i]))
    w("]")
    w("CARD ARRAY esc_pal(16) = [%s]" % " ".join("$%03X" % c for c in ib["esc_pal"]))
    eo, ed = [], []
    for wc, hc, pw_, ph_, cells in ib["esc_frames"]:
        eo.append(len(ed))
        ed += [wc, hc, pw_, ph_] + cells
    w("CONST ESC_FRAMES = %d" % len(eo))
    w("CARD ARRAY esc_off(%d) = [%s]" % (len(eo), " ".join(str(x) for x in eo)))
    w("BYTE ARRAY esc_data(%d) = [%s]" % (len(ed), " ".join(str(x) for x in ed)))
    w("")
    w("; the gates' first columns in the frame's top row")
    w("CONST GATE_L = %d" % o["gates"][0])
    w("CONST GATE_R = %d" % o["gates"][1])
    w("")
    w("; a life's icon beside the field, two tiles in its own bank")
    w("CARD ARRAY hud_pal(16) = [%s]" % " ".join("$%03X" % c for c in o["hud_pal"]))
    w("")
    db = o["doh"]
    w("; DOH's round: its background's tiles (pattern bank 1) and map, DOH's")
    w("; four normal frames (pattern bank 2) as maps of his cells, columns")
    w("; DOH_TX.. and rows DOH_TY.., his last two death frames, the")
    w("; wireframe (pattern bank 3); and the frames the sheet shows him hit")
    w("; and dying, each a normal frame with his colour DOH_RED changed")
    w("CONST DOH_TX = %d" % DOH_TX)
    w("CONST DOH_TY = %d" % DOH_TY)
    w("CONST DOH_W = %d" % DOH_W)
    w("CONST DOH_H = %d" % DOH_H)
    w("CONST DOH_RED = %d" % db["pal"].index(0xA00))
    w("CARD ARRAY doh_bgpal(16) = [%s]" % " ".join("$%03X" % c for c in db["bg_pal"]))
    w("CARD ARRAY doh_pal(16) = [%s]" % " ".join("$%03X" % c for c in db["pal"]))
    w("CARD ARRAY wire_pal(16) = [%s]" % " ".join("$%03X" % c for c in db["wire_pal"]))
    w("BYTE ARRAY doh_bgmap(840) = [")
    for r in range(ROWS):
        w("  " + " ".join(str(x) for x in db["bg_map"][r * COLS:(r + 1) * COLS]))
    w("]")
    w("BYTE ARRAY doh_maps(%d) = [" % (96 * 4))
    for fr in db["maps"]:
        w("  " + " ".join(str(x) for x in fr))
    w("]")
    w("BYTE ARRAY wire_maps(%d) = [" % (96 * 2))
    for fr in db["wire_maps"]:
        w("  " + " ".join(str(x) for x in fr))
    w("]")
    w("; hit 0-3, then dying 0-11: the normal frame, and what DOH_RED becomes")
    w("; (the sheet's dying frame 8 is 2 pixels off normal 0 in purple; it is")
    w("; drawn as that)")
    looks = []
    for n, (k, i, b, m, bad) in enumerate(db["looks"]):
        if m is None:
            # the purple its three neighbours in the row wear
            m = db["looks"][n + 1][3]
        looks.append((b, m[0xA00]))
    w("BYTE ARRAY look_base(16) = [%s]" % " ".join(str(b) for b, _ in looks))
    w("CARD ARRAY look_col(16) = [%s]" % " ".join("$%03X" % c for _, c in looks))
    w("")
    w("; the board's music, a frame at a time on voices 0-2: wait (frames),")
    w("; mask (the channels that change; $80 the end), then increment low,")
    w("; increment high and level for each channel in the mask")
    for name, data, n, ne in o["music"]:
        w("CONST MUS_%s_FRAMES = %d" % (name, n))
        w("BYTE ARRAY mus_%s(%d) = [" % (name.lower(), len(data)))
        for i in range(0, len(data), 32):
            w("  " + " ".join(str(x) for x in data[i:i + 32]))
        w("]")
    return "\n".join(L) + "\n"


def sizes(o):
    """What the PRG carries, by the arrays the .act declares."""
    total = 0
    for line in act(o).splitlines():
        if " ARRAY " in line and "(" in line:
            n = int(line.split("(")[1].split(")")[0])
            total += n * (2 if line.startswith("CARD") else 1)
        elif " ARRAY " in line and '"' in line:
            total += len(line.split('"')[1]) + 1
    return total


def zoom(args):
    """--zoom SHEET x y w h [scale]: that part of a sheet, enlarged on an
    8-pixel grid, into sim/build/zoom_SHEET.png -- how the sheets' pieces
    were looked at before their boxes were written down."""
    from PIL import Image
    name, x, y, w, h = args[0], int(args[1]), int(args[2]), int(args[3]), int(args[4])
    sc = int(args[5]) if len(args) > 5 else 8
    fn, _ = SHEETS[name]
    src = Image.open(os.path.join(ART, fn)).convert("RGB").crop((x, y, x + w, y + h))
    big = src.resize((w * sc, h * sc), Image.NEAREST)
    px = big.load()
    for gx in range(0, w * sc, 8 * sc):
        for gy in range(0, h * sc, 2):
            px[gx, gy] = (255, 0, 255)
    for gy in range(0, h * sc, 8 * sc):
        for gx in range(0, w * sc, 2):
            px[gx, gy] = (255, 0, 255)
    out = os.path.join(ROOT, "sim", "build", "zoom_%s.png" % name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    big.save(out)
    print(out)


def main():
    if "--boxes" in sys.argv:
        show_boxes(sys.argv[sys.argv.index("--boxes") + 1])
        return 0
    if "--zoom" in sys.argv:
        zoom(sys.argv[sys.argv.index("--zoom") + 1:])
        return 0
    if "--report" in sys.argv:
        report()
        report_build()
        return 0
    if "--ship" in sys.argv:
        sh = ship()
        fr = sh["frames"]
        base = cells_of(fr[0])
        print("  ship frame 0: %d cells, %d distinct; logo %d distinct" %
              (len(base), len(set(base)), len(set(cells_of(sh["logo"])))))
        for i in range(1, 20):
            cs = cells_of(fr[i])
            for b in range(i):
                bc = cells_of(fr[b])
                ms = [recolour_map(bc[j], cs[j]) for j in range(len(cs))]
                if all(m is not None for m in ms):
                    merged = {}
                    ok = all(merged.setdefault(a, v) == v for m in ms for a, v in m.items())
                    print("    frame %2d: a recolour of frame %d%s" % (i, b, "" if ok else " cell by cell only"))
                    break
            else:
                diff = [j for j in range(len(cs)) if cs[j] != base[j]]
                new = {cs[j] for j in diff} - set(base)
                print("    frame %2d: %3d cells differ from frame 0, %3d new cells" % (i, len(diff), len(new)))
        return 0
    if "--scenes" in sys.argv:
        show_scenes()
        return 0
    o = build()
    text = act(o)
    dat2 = os.path.join(ART, "ARKSCENE.DAT")
    files = [(DAT, bytes(o["dat"].data), o["dat"]), (dat2, bytes(o["dat2"].data), o["dat2"])]
    for path, data, _ in files:
        assert len(data) <= 65535, "%s is %d bytes: a file on a drive is at most 65,535" % (path, len(data))
    if "--check" in sys.argv:
        have = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        stale = [os.path.relpath(OUT, ROOT)] if have != text else []
        for path, data, _ in files:
            if (open(path, "rb").read() if os.path.exists(path) else b"") != data:
                stale.append(os.path.relpath(path, ROOT))
        if stale:
            print("  %s stale: run python tools/mkarkanoid.py" % ", ".join(stale))
            return 1
        print("ok -- the art file and the two data files are current")
        return 0
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(text)
    for path, data, _ in files:
        open(path, "wb").write(data)
    preview(o)
    print("  the PRG's share of the art %d bytes" % sizes(o))
    for path, data, d in files:
        print("  %s %d bytes in %d blocks" % (os.path.basename(path), len(data), len(d.blocks)))
        for name, off, n in d.blocks:
            print("    %-16s %6d bytes at %6d" % (name, n, off))
    print("  %d glyphs, Namco's for %s; vaus %d cells in %d frames; splits %s" %
          (len(o["fontmap"]), "".join(o["fallback"]), len(o["vaus_cells"]), len(o["vaus_frames"]),
           [vb[0] for vb in o["vaus_banks"]]))
    for name, d, n, ne in o["music"]:
        print("  music %-6s %4d frames (%5.2f s), %3d events, %4d bytes" % (name, n, n / 60, ne, len(d)))
    print("  wrote %s, %s and %s" % (os.path.relpath(OUT, ROOT), os.path.relpath(DAT, ROOT), os.path.relpath(PREVIEW, ROOT)))
    return 0


# --------------------------------------------------------------- preview
def rgb(v):
    return (((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17)


def unpack_round(o, n):
    blob = o["rounds"][n]
    f, cnt = blob[0], blob[1]
    grid = [[0] * 13 for _ in range(MAXROWS)]
    for r in range(cnt):
        for c in range(13):
            b = blob[2 + r * 7 + c // 2]
            grid[f + r][c] = (b >> 4) if c % 2 == 0 else (b & 15)
    return grid


def field_picture(o, n):
    """Round n (0-31) as the game builds it, from the generated data
    alone: the background's model, the bricks, and every brick's shadow
    one cell right and one down. Returns rows of $0RGB."""
    b = o["flds"][n % 4]
    mn, md = field_maps(b)
    grid = unpack_round(o, n)
    brick = lambda tx, ty: grid[ty - 1][(tx - 1) // 2] if 1 <= tx <= 26 and 1 <= ty <= MAXROWS else 0  # noqa: E731
    img = [[0] * 224 for _ in range(240)]
    for ty in range(ROWS):
        for tx in range(COLS):
            k = brick(tx, ty)
            if k:
                pal = o["bk"]["pal"]
                t = o["bk"]["tiles"][2 * (k - 1) + ((tx - 1) & 1)]
            else:
                pal = b["pal"]
                t = b["tiles"][md[ty][tx] if brick(tx - 1, ty - 1) else mn[ty][tx]]
            for y in range(8):
                for x in range(8):
                    byte = t[y * 4 + x // 2]
                    img[ty * 8 + y][tx * 8 + x] = pal[(byte >> 4) if x % 2 == 0 else (byte & 15)]
    return img


def preview(o):
    from PIL import Image
    W, H = 8 * 232, 4 * 248 + 200
    im = Image.new("RGB", (W, H), (32, 32, 32))
    px = im.load()
    for n in range(32):
        pic = field_picture(o, n)
        ox, oy = (n % 8) * 232, (n // 8) * 248
        for y in range(240):
            for x in range(224):
                px[ox + x, oy + y] = rgb(pic[y][x])
    # the sprites, undoubled, in the palette each wears
    y0 = 4 * 248 + 8
    dat = o["dat"].data
    blocks = {name: (off, n) for name, off, n in o["dat"].blocks}

    def cell(block, i, pal, x0, yy):
        off = blocks[block][0] + i * 128
        for y in range(8):
            for x in range(8):
                byte = dat[off + (y * 2) * 8 + x]
                v = byte >> 4
                if v:
                    px[x0 + x, yy + y] = rgb(pal[v])
    x = 4
    for k, ch in enumerate(CAPSULE_ROWS):
        pal = list(o["spr_pal"])
        pal[11:13] = o["cap_pal"][k]
        for f, (l, r) in enumerate(o["cap"][ch]):
            cell("SPRITES", l, pal, x + f * 18, y0 + k * 10)
            cell("SPRITES", r, pal, x + f * 18 + 8, y0 + k * 10)
    x = 160
    for k, name in enumerate(ENEMY_TYPES):
        pal = list(o["spr_pal"])
        pal[7:11] = o["enemy_pal"][k]
        for f, cs in enumerate(o["enemy"][name]):
            for q, c in enumerate(cs):
                cell("ENEMY_" + name.upper(), c, pal, x + f * 18 + (q % 2) * 8, y0 + k * 18 + (q // 2) * 8)
    for f, cs in enumerate(o["burst"]):
        for q, c in enumerate(cs):
            cell("SPRITES", c, o["spr_pal"], 4 + f * 18 + (q % 2) * 8, y0 + 80 + (q // 2) * 8)
    cell("SPRITES", o["ball_shadow"], o["spr_pal"], 124, y0 + 84)
    cell("SPRITES", o["ball"], o["spr_pal"], 120, y0 + 80)
    cell("SPRITES", o["beam"], o["spr_pal"], 136, y0 + 80)
    for i, c in enumerate(o["shot"]):
        cell("SPRITES", c, o["spr_pal"], 150 + i * 10, y0 + 80)
    # the Vaus frames over round 1's bottom rows, shadow first, as the game draws them
    b = o["flds"][0]
    split, pa, ma, pb, mb = o["vaus_banks"][0]
    for i, (wc, hc, ox, oy, cs) in enumerate(o["vaus_frames"]):
        fx, fy = 900 + (i % 12) * 72, y0 + (i // 12) * 36 + 10
        for pass_ in (0, 1):
            for j, c in enumerate(cs):
                cc = o["vaus_cells"][c]
                for y in range(8):
                    for x in range(8):
                        byte = cc[y * 4 + x // 2]
                        v = (byte >> 4) if x % 2 == 0 else (byte & 15)
                        if v:
                            X = fx + ox + (j % wc) * 8 + x + (4 if pass_ == 0 else 0)
                            Y = fy + oy + (j // wc) * 8 + y + (4 if pass_ == 0 else 0)
                            px[X, Y] = (0, 0, 0) if pass_ == 0 else rgb(pa[v])
    # the font, white
    order = o["fontmap"]
    off = blocks["FONT"][0]
    for i in range(len(order)):
        for y in range(8):
            for x in range(8):
                byte = dat[off + i * 32 + y * 4 + x // 2]
                if (byte >> 4) if x % 2 == 0 else (byte & 15):
                    px[4 + i * 9 + x, H - 12 + y] = (255, 255, 255)
    im.save(PREVIEW)


if __name__ == "__main__":
    sys.exit(main())
