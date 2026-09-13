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
# The colour PROM, in its own order (PROMcolors: BB GGG RRR through the
# board's resistors), with entry 10 -- 219700, which nothing on the
# board draws -- given to the tractor beam's 00B8DE, a colour of the
# character PROM's that the sheet's beam frames use. Index 0 here is
# black and transparent; PROM entry k is index k + 1, so one sixteen is
# both the sprite bank and the bitmap's bank 0.
PROM = [0xDEDEDE, 0xFF0000, 0xFFFF00, 0xFF9700, 0xFFB800, 0xFF00DE, 0x00FFDE, 0xB8B8DE,
        0xDE4700, 0x00FF00, 0x00B8DE, 0x0068DE, 0x9700DE, 0x0000DE, 0x009797]
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
    ncommon = len(pats.pats)
    imgs, fblob, foffs = formation(s)
    dat = Dat()
    blob = []
    for q in pats.pats:
        blob += double(q)
    dat.add("SPR", blob)
    return dict(pats=pats, common=common, ncommon=ncommon, fimgs=imgs, fblob=fblob, foffs=foffs,
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
