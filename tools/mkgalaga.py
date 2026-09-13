#!/usr/bin/env python3
"""GALAGA's art, out of the ripped arcade sheets.

    python tools/mkgalaga.py               write assets/galaga/galaga_art.act, GALAGA.DAT and a preview
    python tools/mkgalaga.py --check       the art file and the data file are current
    python tools/mkgalaga.py --boxes S     every shape the finder sees on sheet S, band by band
    python tools/mkgalaga.py --colours S   every colour on sheet S and how often

**The art is the arcade's own**, as Ms. Cool-Man's and Arkanoid's are:
`assets/galaga/` holds The Spriters Resource's two arcade Galaga (Namco,
1981) sheets as copied into two GitHub projects -- "General Sprites" in
its expanded version (BlazorGuy/BlazorGalaga, ripped by 125scratch,
xdonthave1xx and Goemar) and its older one (rokcoder-qb64/galaga,
resources/26482.png), the same art repacked with the fighter's full
rotation (resources/Galaga.png), and "Screens and Text" (assets/text.png,
ripped by 125scratch) -- fetched with the owner's consent. Their colours
are the arcade's colour PROM (computerarcheology.com's PROMcolors page:
fifteen colours and black), which is one sprite bank here exactly.
"""

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "assets", "galaga")
OUT = os.path.join(ART, "galaga_art.act")
DAT = os.path.join(ART, "GALAGA.DAT")
PREVIEW = os.path.join(ART, "preview.png")

# The sheets: file, and the colours that are the sheet's own background
# rather than art (a transparent pixel is background everywhere).
SHEETS = {
    "sprites": ("arcade_general_sprites.png", ()),
    "old": ("arcade_general_sprites_old.png", ((0, 0, 0),)),
    "rot": ("arcade_rotations.png", ((0, 0, 0),)),
    "text": ("arcade_screens_text.png", ((0, 0, 0),)),
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


def show_colours(name):
    s = Sheet(name)
    n = {}
    for y in range(s.h):
        for x in range(s.w):
            c = s.at(x, y)
            if c is not None:
                n[c] = n.get(c, 0) + 1
    for c, k in sorted(n.items(), key=lambda t: -t[1]):
        print("  %02X%02X%02X %6d" % (c + (k,)))


# ---------------------------------------------------------------- palette
# The colour PROM (computerarcheology's PROMcolors: BB GGG RRR through
# the board's resistors) has fifteen colours and black, and entry 10 --
# 219700 -- is drawn by nothing; the tractor beam's 00B8DE, a colour of
# the character PROM's that the sheet's beam frames use, takes its place.
# Index 0 is black and transparent, and the order is this program's: the
# first eight are the colours anything drawn into the bitmap low on the
# field uses -- the stars, the bombs, the explosions, the beam, the score
# -- and the last eight are the ones a level's backdrop may take over
# below its raster split, so the split rewrites one run of eight entries.
PROM = [0xDEDEDE, 0xFF0000, 0xFFFF00, 0x00FFDE, 0x00B8DE, 0x0068DE, 0xFF9700,
        0xFFB800, 0xFF00DE, 0xB8B8DE, 0xDE4700, 0x00FF00, 0x9700DE, 0x0000DE, 0x009797]
SAFE = 8                                # indices 0-7 survive the split
# sheet colours that are not the PROM's, and the entry each is drawn with
ALIAS = {0xFFFFFF: 0xDEDEDE, 0xB800DE: 0x9700DE}


def q4(v):
    """A 24-bit colour as the machine's 12 bits."""
    r, g, b = v >> 16, (v >> 8) & 255, v & 255
    return (round(r * 15 / 255) << 8) | (round(g * 15 / 255) << 4) | round(b * 15 / 255)


PAL = [0x000] + [q4(c) for c in PROM]
INDEX = {c: i + 1 for i, c in enumerate(PROM)}


def index_of(c):
    v = (c[0] << 16) | (c[1] << 8) | c[2]
    v = ALIAS.get(v, v)
    if v not in INDEX:
        raise SystemExit("colour %06X is not the arcade's" % v)
    return INDEX[v]


# ---------------------------------------------------------------- sprites
# "General Sprites" is a grid of 16 x 16 cells at 18-pixel pitch from
# (1, 1). The left eight columns: a row a character, its seven rotation
# frames in columns 0-6 -- column 6 facing up, column 0 facing left,
# fifteen degrees apart -- and, for the four that sit in the formation,
# the wing flap in column 7. The other three quarter-turns are flips of
# these, which is how the arcade draws them too (sprite RAM has flip X
# and flip Y and nothing else).
ROWS = {
    "fighter": 0, "captured": 1, "boss": 2, "boss_hit": 3, "goei": 4, "zako": 5,
    "scorpion": 6, "bosconian": 7, "galaxian": 8, "dragonfly": 9, "enterprise": 11,
}
FLAPS = ("boss", "boss_hit", "goei", "zako")
COMMON = ("fighter", "captured", "boss", "boss_hit", "goei", "zako")


def grid_cell(s, col, row):
    """A cell as 16 rows of 16 palette indices."""
    x0, y0 = 1 + 18 * col, 1 + 18 * row
    out = []
    for y in range(16):
        r = []
        for x in range(16):
            c = s.at(x0 + x, y0 + y)
            r.append(0 if c is None else index_of(c))
        out.append(tuple(r))
    return tuple(out)


def frames_of(s, name):
    """The character's frames: seven rotations, then the flap if it has one."""
    n = 8 if name in FLAPS else 7
    return [grid_cell(s, c, ROWS[name]) for c in range(n)]


def fliph(img):
    return tuple(tuple(reversed(r)) for r in img)


def flipv(img):
    return tuple(reversed(img))


def quadrant(img, qx, qy):
    return tuple(tuple(img[qy * 8 + y][qx * 8:qx * 8 + 8]) for y in range(8))


def double(q):
    """An 8 x 8 quadrant as the 16 x 16 raster pattern that shows it over a
    doubled mode: every pixel twice, every row twice, 4 bpp, 128 bytes."""
    out = []
    for r in q:
        row = [(v << 4) | v for v in r]
        out += row + row
    return out


class Patterns:
    """Quadrant patterns, one per shape under the four flips.
    `find` answers (pattern number, flags) with the flags in descriptor
    byte 6's bits -- 7 V, 6 H -- that turn the stored one into the asked
    one, or None for a quadrant with nothing in it."""

    def __init__(self):
        self.pats = []
        self.seen = {}

    def find(self, q):
        if not any(any(r) for r in q):
            return None
        for flags, t in ((0, q), (0x40, fliph(q)), (0x80, flipv(q)), (0xC0, flipv(fliph(q)))):
            if t in self.seen:
                return self.seen[t], flags
        n = len(self.pats)
        self.pats.append(q)
        self.seen[q] = n
        return n, 0


def cut(img, x0, y0):
    return tuple(tuple(img[y0 + y][x0:x0 + 8]) for y in range(8))


def halves(img):
    """Where a frame is its own mirror, the four sprites that show it from
    two stored halves: [(x, y, 8 x 8 picture)] with x, y its logical offset
    in the 16 x 16 box. Galaga's upright frames are fifteen pixels wide and
    symmetric about their middle column, so the mirror does not fall on the
    quadrants' boundary: the halves overlap by that column instead, a
    sprite's position being free to the raster pixel."""
    for a in (8, 7):                                   # mirror x -> 2a - x
        spare = 0 if a == 8 else 15
        if all(img[y][spare] == 0 for y in range(16)) and \
                all(img[y][x] == img[y][2 * a - x] for y in range(16) for x in range(16) if 0 <= 2 * a - x < 16):
            x0 = a - 7                                  # the left half: columns x0 .. a
            return [(x0, 0, cut(img, x0, 0)), (a, 0, fliph(cut(img, x0, 0))),
                    (x0, 8, cut(img, x0, 8)), (a, 8, fliph(cut(img, x0, 8)))]
    for a in (8, 7):                                   # mirror y -> 2a - y
        spare = 0 if a == 8 else 15
        if all(img[spare][x] == 0 for x in range(16)) and \
                all(img[y][x] == img[2 * a - y][x] for y in range(16) for x in range(16) if 0 <= 2 * a - y < 16):
            y0 = a - 7
            return [(0, y0, cut(img, 0, y0)), (8, y0, cut(img, 8, y0)),
                    (0, a, flipv(cut(img, 0, y0))), (8, a, flipv(cut(img, 8, y0)))]
    return [(qx * 8, qy * 8, quadrant(img, qx, qy)) for qy in (0, 1) for qx in (0, 1)]


def sprite_set(s, names, pats):
    """Every frame of `names` as four sprites: (pattern and flags, or None
    for nothing to show; x, y logical offset in the frame's 16 x 16 box)."""
    out = []
    for name in names:
        for f in frames_of(s, name):
            out.append((name, [(pats.find(p), x, y) for x, y, p in halves(f)]))
    return out


# ------------------------------------------------------------- formation
# The formation lives in the bitmap, not in sprites: forty characters in
# rows of ten cannot be sprites under eight a line, and they move a pixel
# at a time. A resting character is one of these frames, and moving it a
# pixel, or flapping, is a list of the pixels that change -- so the cost
# is the outline, not the square.
FORMATION = [("zako", 6), ("zako", 7), ("goei", 6), ("goei", 7), ("boss", 6), ("boss", 7),
             ("boss_hit", 6), ("boss_hit", 7), ("captured", 6)]
EMPTY = tuple((0,) * 16 for _ in range(16))


def delta(old, new, dx, dy):
    """The runs that turn `old` at (-dx, -dy) into `new` at (0, 0), both
    16 x 16, as bytes: y + 2, x + 1, n, then the n colours; 0 ends it, so
    the load that fetches a run's row is its own test. A pixel is written
    only where the picture changes, and a gap of up to two pixels inside a
    run is written too when `new` owns those pixels, since a run costs
    more to start than a pixel costs to store. Drawn from nothing, every
    pixel written is the character's own, so the same list with its
    colours ignored erases it."""
    want = {}
    for y in range(-1, 17):
        for x in range(-1, 17):
            n = new[y][x] if 0 <= x < 16 and 0 <= y < 16 else 0
            ox, oy = x + dx, y + dy
            o = old[oy][ox] if 0 <= ox < 16 and 0 <= oy < 16 else 0
            if n != o:
                want[(x, y)] = n
    out = []
    for y in range(-1, 17):
        xs = sorted(x for (x, yy) in want if yy == y)
        runs = []
        for x in xs:
            if runs:
                gap = range(runs[-1][1] + 1, x)
                if len(gap) <= 2 and all(0 <= g < 16 and 0 <= y < 16 and new[y][g] for g in gap):
                    runs[-1][1] = x
                    continue
            runs.append([x, x])
        for a, b in runs:
            vals = [want.get((x, y), new[y][x] if 0 <= x < 16 and 0 <= y < 16 else 0) for x in range(a, b + 1)]
            out += [y + 2, a + 1, len(vals)] + vals
    return out + [0]


def runs_of(stream):
    """A delta's runs back out of its bytes: (y, x, colours), the field's
    offsets from the top-left."""
    i = 0
    while stream[i] != 0:
        yy, xx, n = stream[i], stream[i + 1], stream[i + 2]
        yield yy - 2, xx - 1, list(stream[i + 3:i + 3 + n])
        i += 3 + n


# a character's moves in the bitmap, in fm_off's order: drawn from nothing,
# a pixel right, left, down, up, and flapped where it stands
MOVES = [None, (1, 0), (-1, 0), (0, 1), (0, -1), "flap"]


def mask(img):
    """Two bytes a row, bit 15 the left pixel: where the character is."""
    out = []
    for r in img:
        v = 0
        for x, p in enumerate(r):
            if p:
                v |= 0x8000 >> x
        out += [v >> 8, v & 255]
    return out


def formation(s):
    imgs = [grid_cell(s, c, ROWS[n]) for n, c in FORMATION]
    partner = {}
    for i, (n, c) in enumerate(FORMATION):
        for j, (m, d) in enumerate(FORMATION):
            if n == m and c != d:
                partner[i] = j
    blob, offs = [], []
    for i, img in enumerate(imgs):
        for mv in MOVES:
            if mv is None:
                d = delta(EMPTY, img, 0, 0)
            elif mv == "flap":
                d = delta(img, imgs[partner[i]], 0, 0) if i in partner else [0]
            else:
                d = delta(img, img, mv[0], mv[1])
            offs.append(len(blob))
            blob += d
    return imgs, blob, offs


# ------------------------------------------------------------------ font
# "Screens and Text" carries the font in the arcade's four text colours,
# on a 9-pixel grid; the white set is rows 443 and 452 from x 453.
FONT = ["0123456789ABCDEFGHIJKLMNO", "PQRSTUVWXYZ#-%.!@"]    # '#' the block, '@' the (c)


def font(t):
    out = {}
    for r, chars in enumerate(FONT):
        for k, ch in enumerate(chars):
            g = []
            for y in range(8):
                v = 0
                for x in range(8):
                    if t.at(453 + 9 * k + x, 443 + 9 * r + y) is not None:
                        v |= 0x80 >> x
                g.append(v)
            out[ch] = g
    out[" "] = [0] * 8
    return out


GLYPHS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-%.!@# "


# -------------------------------------------------------------- backdrops
# A level's horizon: a band along the bottom of the field, cut from the
# published art in assets/galaga/backdrops/ (README.md there credits it)
# at one pixel to one -- after an exact integer reduction where the art
# was drawn large -- and put into sixteen colours whose first eight are
# the palette's own, so the stars, the bombs, the explosions and the beam
# look the same over it, and whose last eight are the band's: the game's
# raster split writes them a row above the band and puts the arcade's
# back at the vertical blank. **The one change made to the art's pixels**,
# by the owner's leave: the band's first FADE rows are dithered into black
# on a 4 x 4 Bayer matrix, a sixteenth more of each row kept than the row
# above, so the horizon rises out of the sky rather than starting on a
# line.
BAND_Y, BAND_H, FADE = 176, 64, 16
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
BACKDROPS = [
    # file, reduction, and the band's top-left in the reduced picture
    ("chikyuu_16_edge_0.png", 1, 16, 154),
    ("green_nebula_arne16_-_512x512_0.png", 1, 70, 158),
    ("rocky-far-mountains_0.png", 5, 16, 40),
    ("planet-only-alt2-alpha.png", 2, -16, 26),
]


def rgb_of(v):
    return ((v >> 8) & 15, (v >> 4) & 15, v & 15)


def backdrop(entry):
    """(sixteen 12-bit colours, BAND_H rows of 224 indices) for a level."""
    from PIL import Image
    fn, red, x0, y0 = entry
    im = Image.open(os.path.join(ART, "backdrops", fn)).convert("RGBA")
    if red > 1:
        assert im.width % red == 0 and im.height % red == 0, fn
        im = im.resize((im.width // red, im.height // red), Image.NEAREST)
    px = im.load()
    band = []
    counts = {}
    for y in range(BAND_H):
        row = []
        for x in range(224):
            # beyond the picture's edge is black space
            inside = 0 <= x0 + x < im.width and 0 <= y0 + y < im.height
            r, g, b, a = px[x0 + x, y0 + y] if inside else (0, 0, 0, 0)
            v = 0 if a < 128 else q4((r << 16) | (g << 8) | b)
            row.append(v)
            counts[v] = counts.get(v, 0) + 1
        band.append(row)
    fixed = PAL[:SAFE]
    free = [[rgb_of(v), n] for v, n in counts.items() if v not in fixed]
    # the closest two, weighted, merged until eight are left
    while len(free) > 16 - SAFE:
        best = None
        for i in range(len(free)):
            for j in range(i + 1, len(free)):
                (a, na), (b, nb) = free[i], free[j]
                d = sum((p - q) ** 2 for p, q in zip(a, b)) * na * nb / (na + nb)
                if best is None or d < best[0]:
                    best = (d, i, j)
        _, i, j = best
        (a, na), (b, nb) = free[i], free[j]
        free[i] = [tuple((p * na + q * nb) / (na + nb) for p, q in zip(a, b)), na + nb]
        del free[j]
    pal = list(fixed) + [(round(c[0]) << 8) | (round(c[1]) << 4) | round(c[2]) for c, _ in free]
    pal += [0] * (16 - len(pal))
    rgbs = [rgb_of(v) for v in pal]
    cache = {}
    out = []
    for row in band:
        o = []
        for v in row:
            if v not in cache:
                c = rgb_of(v)
                cache[v] = min(range(16), key=lambda k: (sum((p - q) ** 2 for p, q in zip(c, rgbs[k])), k))
            o.append(cache[v])
        out.append(o)
    for y in range(FADE):
        for x in range(224):
            if BAYER[y % 4][x % 4] >= y * 16 // FADE:
                out[y][x] = 0
    return pal, out


def pack_band(rows):
    """The band as the bitmap holds it: two pixels a byte, the left high."""
    out = []
    for r in rows:
        out += [(r[x] << 4) | r[x + 1] for x in range(0, 224, 2)]
    return out


# ------------------------------------------------------------- bitmap art
# The other pictures drawn into the bitmap: each is one list from nothing,
# its top-left the box's, in fm_delta's format -- so putting back what
# was under exactly the pixels it wrote clears it. Every colour in them
# is one of the first SAFE, which is what lets them cross the backdrop.
# The explosions are the arcade's double-size sprites, 32 x 32, found on
# the sheet as the shapes along its top: the fighter's four from x 147,
# an enemy's five from x 300; a box is centred on its shape.
PLAYER_BOOM = [(147, 175, 3, 30), (180, 208, 3, 32), (213, 244, 1, 32), (248, 276, 3, 32)]
ENEMY_BOOM = [(300, 306, 12, 19), (333, 344, 10, 22), (365, 380, 9, 24), (394, 420, 3, 30), (426, 456, 1, 32)]
BOMB = (313, 140, 3, 8)                 # the enemy's shot: white, a red body
# the panel's pictures, which stay above the band: a fighter in hand, and
# the stage badges for 1, 5, 10, 20, 30 and 50 stages
PANEL = [("LIFE", (290, 173, 13, 14)), ("B1", (307, 176, 7, 12)), ("B5", (317, 174, 7, 14)),
         ("B10", (328, 174, 13, 14)), ("B20", (345, 172, 15, 16)), ("B30", (363, 172, 15, 16)),
         ("B50", (381, 172, 15, 16))]
SHOT = (313, 122)                       # the fighter's: a blue head, a white eye, a red trail


def box_image(s, x0, y0, w, h):
    return tuple(tuple(0 if not (0 <= x0 + x < s.w and 0 <= y0 + y < s.h) or s.at(x0 + x, y0 + y) is None
                       else index_of(s.at(x0 + x, y0 + y)) for x in range(w)) for y in range(h))


def centred(s, shape, size=32):
    a, b, y0, y1 = shape
    return box_image(s, (a + b + 1) // 2 - size // 2, (y0 + y1 + 1) // 2 - size // 2, size, size)


def draw_list(img):
    w, h = len(img[0]), len(img)
    out = []
    for y in range(h):
        x = 0
        while x < w:
            if img[y][x]:
                a = x
                while x < w and img[y][x]:
                    x += 1
                out += [y + 2, a + 1, x - a] + list(img[y][a:x])
            else:
                x += 1
    return out + [0]


def bitmap_art(s):
    """[(name, picture)] and the lists' blob and offsets."""
    arts = [("PBOOM%d" % i, centred(s, b)) for i, b in enumerate(PLAYER_BOOM)]
    arts += [("EBOOM%d" % i, centred(s, b)) for i, b in enumerate(ENEMY_BOOM)]
    arts.append(("BOMB", box_image(s, *BOMB)))
    low = len(arts)
    arts += [(name, box_image(s, *box)) for name, box in PANEL]
    blob, offs = [], []
    for k, (name, img) in enumerate(arts):
        assert k >= low or all(v < SAFE for r in img for v in r), "%s uses a colour the backdrop takes" % name
        offs.append(len(blob))
        blob += draw_list(img)
    return arts, blob, offs


# ---------------------------------------------------------------- flights
# The arcade's flight paths, starts, stage waves and home slots, from
# tools/galaga_paths.py -- the disassembly's own bytes. The path tables sit
# in the sub CPU's ROM at their own addresses and point at one another;
# here they are one blob, packed region by region, every pointer rewritten
# to an offset into it.
STAGES, RANK = 16, 3                    # rank A: MAME's default difficulty


def flights():
    import random
    import galaga_paths as P
    tabs = sorted(P.PATH_TABLES, key=lambda t: t[1])
    regions = []                        # [start, end, [items]]
    for name, addr, items in tabs:
        size = sum(2 if isinstance(i, str) else 1 for i in items)
        if regions and regions[-1][1] == addr:
            regions[-1][1] += size
            regions[-1][2] += items
        elif not (regions and regions[-1][0] <= addr < regions[-1][1]):
            regions.append([addr, addr + size, list(items)])
    base, off = {}, 0
    for r in regions:
        base[r[0]] = off
        off += r[1] - r[0]

    def reloc(addr):
        for r in regions:
            if r[0] <= addr < r[1]:
                return base[r[0]] + addr - r[0]
        raise SystemExit("a path points at $%04X, outside every table" % addr)

    blob = []
    for r in regions:
        for it in r[2]:
            if isinstance(it, str):
                w = reloc(P.LABEL_ADDR[it])
                blob += [w & 255, w >> 8]
            else:
                blob.append(it)
    # the blob is the ROM's bytes where the ROM has them
    for r in regions:
        for a in range(r[0], r[1]):
            b = blob[base[r[0]] + a - r[0]]
            if not any(isinstance(it, str) for it in r[2]):
                assert b == P.SUB_ROM[a]
    starts = [reloc(P.LABEL_ADDR[lab]) for lab, _ in P.DB_2A3C]
    sels = [sel for _, sel in P.DB_2A3C]
    # object id -> formation row and column, and the game's slot
    obj_row, obj_col, obj_slot = [], [], []
    for obj in range(0, 0x60, 2):
        r, c = (P.HPOS[obj] - 0x14) // 2, P.HPOS[obj + 1] // 2
        obj_row.append(r)
        obj_col.append(c)
        if r == 0:
            slot = c - 3
        elif r == 1:
            slot = 4 + c - 3
        elif r in (2, 3):
            slot = 255 if c in (0, 9) else 8 + (r - 2) * 8 + c - 1
        else:
            slot = 24 + (r - 4) * 10 + c
        obj_slot.append(slot)
    waves, woffs, kinds, parms = [], [], [], []
    for st in range(1, STAGES + 1):
        kind, _, _ = P.stage_row(st, RANK)
        _, _, table = P.build_wave_table(st, RANK, random.Random(st))
        woffs.append(len(waves))
        waves += table
        kinds.append(1 if kind == "challenge" else 0)
        parms += P.stage_parms(st, RANK)[:10]
    return dict(blob=blob, starts=starts, sels=sels, start_bytes=list(P.DB_2A6C), obj_row=obj_row,
                obj_col=obj_col, obj_slot=obj_slot, waves=waves, woffs=woffs, kinds=kinds, parms=parms,
                origins=list(P.DB_FMTN_HPOS_ORIG), atk_yllw=reloc(P.LABEL_ADDR["db_flv_atk_yllw"]),
                atk_red=reloc(P.LABEL_ADDR["db_flv_atk_red"]), atk_boss=reloc(P.LABEL_ADDR["db_flv_0411"]),
                atk_capture=reloc(P.LABEL_ADDR["db_0454"]), rogue=reloc(P.LABEL_ADDR["db_fltv_rogefgter"]))


# ------------------------------------------------------------------ sound
# The arcade's sounds, as its sound CPU plays them: tools/galaga_sound.py
# runs a tick-exact model of the driver over the ROM's own note streams
# (checked against the sound ROM's CRC) and puts each sound on 60 Hz
# frames. Here each is a stream of changes on the voices it owns: a byte
# whose bits 0-2 say which voices' increments change and bits 4-6 which
# volumes (bit 7 the end), the new increments then the new volumes, then
# the frames until the next change -- an envelope's step being one byte.
# The game mixes them the driver's way -- the sounds in its fixed order, a
# later one's voice winning -- with the tunes on voices 0-2 and the
# effects on 3-5. Not carried: the coin (08) and the first-place name
# entry (0C, and its tail 16); the other places' tune (10) is.
TUNES = (0x07, 0x09, 0x0A, 0x0B, 0x0D, 0x0E, 0x10, 0x11, 0x14)
DROPPED = (0x08, 0x0C, 0x16)
SND_ORDER = (0x00, 0x13, 0x0F, 0x03, 0x02, 0x04, 0x01, 0x12, 0x05, 0x06, 0x09, 0x07,
             0x11, 0x0D, 0x0E, 0x14, 0x15, 0x0A, 0x0B, 0x10)


def sounds():
    import galaga_sound as S
    blob, offs, v0, nv = [], [], [], []
    for sid in range(len(S.SND_PARMS)):
        _, n, first = S.SND_PARMS[sid]
        offs.append(len(blob))
        v0.append(first)
        nv.append(n)
        if sid in DROPPED:
            blob += [0x80]
            continue
        r = S.render(sid, chain=False)
        frames = len(r[0])
        inc = [None] * 3
        vol = [None] * 3
        recs = []
        for f in range(frames):
            mask, incs, vols = 0, [], []
            for v in range(first, first + n):
                _, hz, vl = r[v][f]
                i = 0 if hz is None else min(65535, round(S.target_increment(hz)))
                vl = 0 if hz is None else vl
                if i != inc[v]:
                    inc[v] = i
                    mask |= 1 << v
                    incs += [i & 255, i >> 8]
                if vl != vol[v]:
                    vol[v] = vl
                    mask |= 16 << v
                    vols.append(vl)
            if mask:
                recs.append((f, mask, incs + vols))
        for k, (f, mask, data) in enumerate(recs):
            gap = (recs[k + 1][0] if k + 1 < len(recs) else frames) - f
            while gap > 255:                   # a long hold: empty records carry it
                blob += [mask, *data, 255]
                gap -= 255
                mask, data = 0, []
            blob += [mask, *data, gap]
        blob += [0x80]                         # the end: its voices fall silent
    return dict(blob=blob, offs=offs, v0=v0, nv=nv, loop=[1 if sid in S.LOOP_IDS or sid == 0 else 0
                                                        for sid in range(len(S.SND_PARMS))])


# ------------------------------------------------------------------ build
class Dat:
    def __init__(self):
        self.data = bytearray()
        self.blocks = []

    def add(self, name, data):
        self.blocks.append((name, len(self.data), len(data)))
        self.data += bytes(data)


def build():
    s, t = Sheet("sprites"), Sheet("text")
    pats = Patterns()
    common = sprite_set(s, COMMON, pats)
    shot = pats.find(box_image(s, SHOT[0] - 2, SHOT[1], 8, 8))
    assert shot[1] == 0
    ncommon = len(pats.pats)
    arts, ablob, aoffs = bitmap_art(s)
    imgs, fblob, foffs = formation(s)
    dat = Dat()
    blob = []
    for q in pats.pats:
        blob += double(q)
    dat.add("SPR", blob)
    bds = [backdrop(b) for b in BACKDROPS]
    for k, (_, rows) in enumerate(bds):
        dat.add("BD%d" % k, pack_band(rows))
    return dict(snd=sounds(), fl=flights(), pats=pats, common=common, ncommon=ncommon, fimgs=imgs, fblob=fblob, foffs=foffs, bds=bds,
                shot=shot[0], arts=arts, ablob=ablob, aoffs=aoffs,
                font=font(t), dat=dat, sheet=s)


def arr(w, decl, vals, per=16, fmt="%d"):
    w(decl + " = [")
    for i in range(0, len(vals), per):
        w("  " + " ".join(fmt % v for v in vals[i:i + per]))
    w("]")


def act(o):
    L = []
    w = L.append
    w("; GALAGA's art, generated by tools/mkgalaga.py from the ripped arcade")
    w("; sheets in assets/galaga/. Generated: do not edit. The sprite patterns")
    w("; are in GALAGA.DAT beside it, whose blocks these offsets name; the")
    w("; game streams them into VRAM.")
    w("")
    for name, off, n in o["dat"].blocks:
        w("CONST D_%s = %d" % (name, off & 0xFFFF))
        w("CONST DH_%s = %d" % (name, off >> 16))
        w("CONST N_%s = %d" % (name, n))
    w("")
    w("; the colour PROM, black first: the sprite bank and the bitmap's bank 0")
    arr(w, "CARD ARRAY gal_pal(16)", PAL, fmt="$%03X")
    w("")
    w("; the levels' backdrops: a band of %d rows from row %d, in GALAGA.DAT's" % (BAND_H, BAND_Y))
    w("; BD blocks, and its palette -- the first %d the arcade's, the rest the band's" % SAFE)
    spr_end = 0x9600 + len(o["pats"].pats) * 128
    assert spr_end + BAND_H * 112 <= 0x10000, "the band's copy does not fit VRAM above the sprites"
    w("; the band's copy is kept in VRAM right above the sprite patterns")
    w("CONST BD_VRAM = $%04X" % spr_end)
    w("CONST BAND_Y = %d" % BAND_Y)
    w("CONST BAND_H = %d" % BAND_H)
    w("CONST SAFE = %d" % SAFE)
    w("; for each level its own eight, as PAL_DATA takes them -- the high byte first")
    bp = []
    for pal, _ in o["bds"]:
        for v in pal[SAFE:]:
            bp += [v >> 8, v & 255]
    arr(w, "BYTE ARRAY bd_pal(%d)" % len(bp), bp, fmt="$%02X")
    w("")
    names = []
    for n, _ in o["common"]:
        if n not in names:
            names.append(n)
    w("; the sprite frames: each character's first frame, then four sprites a")
    w("; frame -- the pattern (255 none), descriptor byte 6's flips for it, and")
    w("; its logical x and y in the frame's 16 x 16 box")
    first = 0
    for n in names:
        w("CONST F_%s = %d" % (n.upper(), first))
        first += sum(1 for m, _ in o["common"] if m == n)
    w("CONST SPR_PATS = %d" % len(o["pats"].pats))
    qp, qf, qx, qy = [], [], [], []
    for _, quads in o["common"]:
        for pf, x, y in quads:
            qp.append(255 if pf is None else pf[0])
            qf.append(0 if pf is None else pf[1])
            qx.append(x)
            qy.append(y)
    arr(w, "BYTE ARRAY spr_qp(%d)" % len(qp), qp)
    arr(w, "BYTE ARRAY spr_qf(%d)" % len(qf), qf, fmt="$%02X")
    arr(w, "BYTE ARRAY spr_qx(%d)" % len(qx), qx)
    arr(w, "BYTE ARRAY spr_qy(%d)" % len(qy), qy)
    w("")
    w("; the formation's frames, in the bitmap: for each, %d offsets into" % len(MOVES))
    w("; fm_delta -- drawn from nothing (which, colours ignored, also erases")
    w("; it), moved a pixel right, left, down, up, and flapped (an empty list")
    w("; if not); a list is runs of y + 2, x + 1, n and n colours, and 0 ends it")
    for i, (n, c) in enumerate(FORMATION):
        w("CONST FM_%s%d = %d" % (n.upper(), c, i))
    arr(w, "CARD ARRAY fm_off(%d)" % len(o["foffs"]), o["foffs"], per=len(MOVES))
    arr(w, "BYTE ARRAY fm_delta(%d)" % len(o["fblob"]), o["fblob"], per=24)
    fm = []
    for img in o["fimgs"]:
        fm += mask(img)
    w("; where each frame is, two bytes a row, bit 15 the left pixel")
    arr(w, "BYTE ARRAY fm_mask(%d)" % len(fm), fm, fmt="$%02X")
    w("")
    fl = o["fl"]
    w("; the flights, the arcade's (tools/galaga_paths.py): the path tables in one")
    w("; blob, every pointer an offset into it; each of the 24 entry paths' offset")
    w("; and its start set in fl_start, three bytes -- Y, X, the angle's high")
    w("; byte -- a set, the mirrored start the three after")
    arr(w, "BYTE ARRAY fl_rom(%d)" % len(fl["blob"]), fl["blob"], per=24, fmt="$%02X")
    arr(w, "CARD ARRAY fl_path(24)", fl["starts"])
    arr(w, "BYTE ARRAY fl_sel(24)", fl["sels"])
    arr(w, "BYTE ARRAY fl_start(%d)" % len(fl["start_bytes"]), fl["start_bytes"], fmt="$%02X")
    for k in ("atk_yllw", "atk_red", "atk_boss", "atk_capture", "rogue"):
        w("CONST FL_%s = %d" % (k.upper(), fl[k]))
    w("; the formation's origins as the arcade holds them: ten columns' sprite X,")
    w("; six rows' raw bytes (Y as Yint >> 1)")
    arr(w, "BYTE ARRAY fm_orig(16)", fl["origins"], fmt="$%02X")
    w("; an object id's (/2) formation row and column, and the game's slot (255 none)")
    arr(w, "BYTE ARRAY obj_row(48)", fl["obj_row"])
    arr(w, "BYTE ARRAY obj_col(48)", fl["obj_col"])
    arr(w, "BYTE ARRAY obj_slot(48)", fl["obj_slot"])
    w("; each stage's waves as the arcade's launcher reads them: $7E a wave's end,")
    w("; $7F the last, else a path token and an object id; the stage's kind (1 a")
    w("; challenging stage) and its ten parameter nibbles")
    w("CONST STAGES = %d" % STAGES)
    arr(w, "BYTE ARRAY st_waves(%d)" % len(fl["waves"]), fl["waves"], per=24, fmt="$%02X")
    arr(w, "CARD ARRAY st_woff(%d)" % STAGES, fl["woffs"])
    arr(w, "BYTE ARRAY st_kind(%d)" % STAGES, fl["kinds"])
    arr(w, "BYTE ARRAY st_parm(%d)" % len(fl["parms"]), fl["parms"], per=10)
    w("")
    sd = o["snd"]
    w("; the arcade's sounds, rendered by tools/galaga_sound.py: for each, its")
    w("; stream's offset, first voice, voices, and whether it loops; a stream is")
    w("; records of a mask -- bits 0-2 the voices whose increments follow, 4-6")
    w("; those whose volumes follow them, 7 the end -- then the frames to the next")
    w("CONST NSND = %d" % len(sd["offs"]))
    arr(w, "BYTE ARRAY snd_data(%d)" % len(sd["blob"]), sd["blob"], per=24)
    arr(w, "CARD ARRAY snd_start(%d)" % len(sd["offs"]), sd["offs"])
    arr(w, "BYTE ARRAY snd_v0(%d)" % len(sd["v0"]), sd["v0"])
    arr(w, "BYTE ARRAY snd_nv(%d)" % len(sd["nv"]), sd["nv"])
    arr(w, "BYTE ARRAY snd_loops(%d)" % len(sd["loop"]), sd["loop"])
    w("; the driver's order, a later sound's voice winning, and each's group:")
    w("; 0 the effects, on voices 3-5, 1 the tunes, on 0-2")
    arr(w, "BYTE ARRAY snd_order(%d)" % len(SND_ORDER), SND_ORDER, fmt="$%02X")
    arr(w, "BYTE ARRAY snd_tune(%d)" % len(sd["offs"]), [1 if i in TUNES else 0 for i in range(len(sd["offs"]))])
    w("")
    w("; the fighter's shot: one sprite, its 3 x 8 in columns 2-4")
    w("CONST P_SHOT = %d" % o["shot"])
    w("")
    w("; the other pictures the bitmap holds, each one list in fm_delta's format")
    w("; from its box's top-left: art_off(k), k being")
    for k, (name, img) in enumerate(o["arts"]):
        w("CONST A_%s = %d" % (name, k))
    w("CONST N_EBOOM = %d" % len(ENEMY_BOOM))
    w("CONST N_PBOOM = %d" % len(PLAYER_BOOM))
    arr(w, "CARD ARRAY art_off(%d)" % len(o["aoffs"]), o["aoffs"])
    arr(w, "BYTE ARRAY art_delta(%d)" % len(o["ablob"]), o["ablob"], per=24)
    w("")
    w("; the font, 8 rows of 1 bpp, in this order: %s" % GLYPHS)
    g = []
    for ch in GLYPHS:
        g += o["font"][ch]
    arr(w, "BYTE ARRAY glyphs(%d)" % len(g), g, per=8, fmt="$%02X")
    return "\n".join(L) + "\n"


def replay(canvas, x0, y0, stream):
    for yy, xx, vals in runs_of(stream):
        for k, v in enumerate(vals):
            canvas[(x0 + xx + k, y0 + yy)] = v


def frame_image(o, quads):
    """A sprite frame put back together from its four sprites, as a dict."""
    pats = o["pats"].pats
    img = {}
    for pf, x, y in quads:
        if pf is None:
            continue
        p = pats[pf[0]]
        if pf[1] & 0x40:
            p = fliph(p)
        if pf[1] & 0x80:
            p = flipv(p)
        for b in range(8):
            for a in range(8):
                if p[b][a]:
                    img[(x + a, y + b)] = p[b][a]
    return img


def preview(o):
    from PIL import Image
    S = 3
    im = Image.new("RGB", (340 * S, 180 * S), (24, 24, 40))
    px = im.load()

    def rgb(i):
        v = PAL[i]
        return (((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17)

    def put(x, y, i):
        if i:
            for a in range(S):
                for b in range(S):
                    px[x * S + a, y * S + b] = rgb(i)

    for k, (_, quads) in enumerate(o["common"]):
        ox, oy = 2 + (k % 16) * 20, 2 + (k // 16) * 20
        for (x, y), v in frame_image(o, quads).items():
            put(ox + x, oy + y, v)
    for k in range(len(FORMATION)):
        canvas = {}
        x0, y0 = 2 + k * 20, 70
        offs = o["foffs"][k * len(MOVES):]
        replay(canvas, x0, y0, o["fblob"][offs[0]:])
        replay(canvas, x0 + 1, y0, o["fblob"][offs[1]:])
        replay(canvas, x0 + 1, y0 + 1, o["fblob"][offs[3]:])
        replay(canvas, x0 + 1, y0 + 1, o["fblob"][offs[5]:])
        for (x, y), v in canvas.items():
            put(x, y, v)
    for k, ch in enumerate(GLYPHS):
        for y in range(8):
            for x in range(8):
                if o["font"][ch][y] & (0x80 >> x):
                    put(2 + (k % 32) * 9 + x, 100 + (k // 32) * 10 + y, 1)
    for i in range(16):
        for y in range(8):
            for x in range(8):
                put(2 + i * 9 + x, 130 + y, i)
    im.save(PREVIEW)
    bands_preview(o)


def bands_preview(o):
    """The four backdrops as the band shows them, one under another."""
    from PIL import Image
    S = 3
    im = Image.new("RGB", (224 * S, (BAND_H + 4) * S * len(o["bds"])), (24, 24, 40))
    px = im.load()
    for k, (pal, rows) in enumerate(o["bds"]):
        for y, row in enumerate(rows):
            for x, v in enumerate(row):
                c = rgb_of(pal[v])
                for a in range(S):
                    for b in range(S):
                        px[x * S + a, (k * (BAND_H + 4) + y) * S + b] = (c[0] * 17, c[1] * 17, c[2] * 17)
    im.save(os.path.join(ART, "preview_backdrops.png"))


def check(o, s):
    """The generated data says what the sheet says: every sprite frame put
    back together is the sheet's cell, and every delta, replayed over the
    picture before it, gives the picture after, writing no pixel that is
    neither picture's -- so a neighbour or a star beside it is never hit."""
    k = 0
    for name in COMMON:
        for f in frames_of(s, name):
            got = frame_image(o, o["common"][k][1])
            want = {(x, y): f[y][x] for y in range(16) for x in range(16) if f[y][x]}
            assert got == want, "%s frame %d does not come back" % (name, k)
            k += 1

    def own(im, x0, y0):
        return {(x0 + x, y0 + y) for y in range(16) for x in range(16) if im[y][x]}

    for i, img in enumerate(o["fimgs"]):
        offs = o["foffs"][i * len(MOVES):]
        for m, mv in enumerate(MOVES):
            new = img
            if mv == "flap":
                if o["fblob"][offs[m]] == 0:
                    continue
                new = [f for j, f in enumerate(o["fimgs"]) if j != i and FORMATION[j][0] == FORMATION[i][0]][0]
                old, dx, dy = img, 0, 0
            elif mv is None:
                old, dx, dy = EMPTY, 0, 0
            else:
                old, (dx, dy) = img, mv
            canvas = {(x - dx, y - dy): old[y][x] for y in range(16) for x in range(16)}
            touched = {}
            replay(touched, 0, 0, o["fblob"][offs[m]:])
            allowed = own(old, -dx, -dy) | own(new, 0, 0)
            for p in touched:
                assert p in allowed, "frame %d move %d writes %s, which is neither picture's" % (i, m, p)
            canvas.update(touched)
            for (x, y), v in canvas.items():
                want = new[y][x] if 0 <= x < 16 and 0 <= y < 16 else 0
                assert v == want, "frame %d move %d: pixel %d,%d is %d, not %d" % (i, m, x, y, v, want)


def main():
    if "--boxes" in sys.argv:
        show_boxes(sys.argv[sys.argv.index("--boxes") + 1])
        return 0
    if "--colours" in sys.argv:
        show_colours(sys.argv[sys.argv.index("--colours") + 1])
        return 0
    o = build()
    check(o, o["sheet"])
    text = act(o)
    data = bytes(o["dat"].data)
    assert len(data) <= 65535, "GALAGA.DAT is %d bytes: a file on a drive is at most 65,535" % len(data)
    if "--check" in sys.argv:
        have = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        stale = [os.path.relpath(OUT, ROOT)] if have != text else []
        if (open(DAT, "rb").read() if os.path.exists(DAT) else b"") != data:
            stale.append(os.path.relpath(DAT, ROOT))
        if stale:
            print("  %s stale: run python tools/mkgalaga.py" % ", ".join(stale))
            return 1
        print("ok -- the art file and the data file are current")
        return 0
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(text)
    open(DAT, "wb").write(data)
    preview(o)
    n = len(o["common"])
    print("  %d common frames in %d sprite patterns, %d bytes of VRAM" % (n, o["ncommon"], o["ncommon"] * 128))
    offs = o["foffs"] + [len(o["fblob"])]
    print("  formation: %d frames, %d bytes of deltas" % (len(FORMATION), len(o["fblob"])))
    for k, (nm, c) in enumerate(FORMATION):
        b = k * len(MOVES)
        print("    %-9s %d: %s" % (nm, c, "  ".join("%s %3d" % (lbl, offs[b + m + 1] - offs[b + m])
                                                for m, lbl in enumerate(("draw", "right", "left", "down", "up", "flap")))))
    print("  wrote %s, %s and %s" % tuple(os.path.relpath(p, ROOT) for p in (OUT, DAT, PREVIEW)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
