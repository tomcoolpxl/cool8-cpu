#!/usr/bin/env python3
"""YENDOR's art: DawnLike's tiles cut into the machine's pattern banks, a
file of them for each theme of the dungeon, and the table that names them.

    python tools/mkyendor.py           write assets/yendor/ -- the .act, the theme files, a preview
    python tools/mkyendor.py --check   everything there is what the sheets make
    python tools/mkyendor.py --font    render the SDS 8x8 font into assets/yendor/sds8x8.png

**The pictures are DawnLike's**, DragonDePlatino's 16 x 16 tileset drawn
for NetHack, on DawnBringer's sixteen-colour palette -- CC-BY 4.0, in
assets/dawnlike/ with its credits. Nothing is redrawn: every cell of the
dungeon is cut from those sheets, and the only change is the one the
machine makes, the palette's 24-bit colours to 12.

**A cell is 16 x 16, four of mode 2's tiles**, and mode 2's tiles have no
transparency. So a creature or an item cannot be laid over the floor on
the screen; it is laid over the floor *here*, and every theme -- a band of
the dungeon's depth, its floor, its walls, its stairs -- is a file of its
own: 32,768 bytes, the four pattern banks the attribute byte reaches.
The game streams the one for the level into VRAM on the stairs.

    bank 0   the font (ASCII 32-126), then the terrain: sixteen wall
             pieces by their neighbours, floor, corridor, the doors, stairs
    bank 1   the items, each on the floor                (later milestones)
    bank 2   the creatures on the floor, frame 0
    bank 3   the same creatures, frame 1 -- DawnLike animates every one

**Colour is a bank of the palette**: DawnBringer's sixteen as they are
for what is in view, the same sixteen dimmed for what is remembered, and
the text in its own inks.

**The font is DawnLike's SDS 8x8**, a TrueType font whose glyphs are
drawn on an 8 x 8 grid: rendered at its own size every pixel is fully on
or off. It is rendered once, by --font, into sds8x8.png, and the build
reads that picture -- so a different FreeType cannot make the check fail.
"""

import io
import os
import sys
import warnings

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL = os.path.join(ROOT, "assets", "dawnlike")
OUT_DIR = os.path.join(ROOT, "assets", "yendor")
OUT = os.path.join(OUT_DIR, "yendor_art.act")
FONT_PNG = os.path.join(OUT_DIR, "sds8x8.png")
PREVIEW = os.path.join(OUT_DIR, "preview.png")

# DawnBringer's 16, as lospec publishes them. DawnLike's sheets carry
# them a unit or two off here and there; a pixel is its nearest.
DB16 = [0x140C1C, 0x442434, 0x30346D, 0x4E4A4E, 0x854C30, 0x346524, 0xD04648, 0x757161,
        0x597DCE, 0xD27D2C, 0x8595A1, 0x6DAA2C, 0xD2AA99, 0x6DC2CA, 0xDAD45E, 0xDEEED6]

# ------------------------------------------------------------ the themes
# A theme is a band of the dungeon: its floor, its walls, its stairs.
# Coordinates are (column, row) in 16-pixel cells of a sheet. A floor or
# a wall set is DawnLike's 7 x 3 autotile block; the floor is its middle,
# the wall pieces are read from the block by the legend in WALL_PIECE.
THEMES = [
    dict(name="halls", file="YTHEME0", depths="1-4",
         floor=(1, 7), wall=(0, 9), up=(0, 1), down=(1, 1)),
    dict(name="caverns", file="YTHEME1", depths="5-8",
         floor=(1, 22), wall=(0, 21), up=(4, 1), down=(5, 1)),
    dict(name="depths", file="YTHEME2", depths="9-12",
         floor=(1, 25), wall=(14, 48), up=(2, 1), down=(3, 1)),
]

# which piece of a wall block for a wall cell whose neighbours north,
# south, west and east are wall: the block's legend, rows 0-2 of
# Objects/Wall.png. A lone run end takes the straight piece.
WALL_PIECE = {
    (0, 0, 0, 0): (3, 0), (0, 0, 0, 1): (1, 0), (0, 0, 1, 0): (1, 0), (0, 0, 1, 1): (1, 0),
    (0, 1, 0, 0): (0, 1), (0, 1, 0, 1): (0, 0), (0, 1, 1, 0): (2, 0), (0, 1, 1, 1): (4, 0),
    (1, 0, 0, 0): (0, 1), (1, 0, 0, 1): (0, 2), (1, 0, 1, 0): (2, 2), (1, 0, 1, 1): (4, 2),
    (1, 1, 0, 0): (0, 1), (1, 1, 0, 1): (3, 1), (1, 1, 1, 0): (5, 1), (1, 1, 1, 1): (4, 1),
}

# doors: closed and open, in a wall running across and in one running down
DOORS = dict(closed_h=("Objects/Door0.png", 0, 0), open_h=("Objects/Door1.png", 0, 0),
             closed_v=("Objects/Door0.png", 1, 0), open_v=("Objects/Door1.png", 1, 0))

# the heroes: frame 0 and frame 1 are the same cell of Player0 and Player1
ROLES = [("VALK", "Valkyrie", 4, 3), ("WIZ", "Wizard", 7, 3), ("ROGUE", "Rogue", 2, 4)]

FONT_FIRST, FONT_LAST = 32, 126


# ---------------------------------------------------------- the pictures
_sheets = {}


def sheet(rel):
    from PIL import Image
    if rel not in _sheets:
        _sheets[rel] = Image.open(os.path.join(DL, rel)).convert("RGBA")
    return _sheets[rel]


def cut(rel, col, row):
    return sheet(rel).crop((col * 16, row * 16, col * 16 + 16, row * 16 + 16))


def over(bg, fg):
    out = bg.copy()
    out.alpha_composite(fg)
    return out


_near = {}


def indices(im):
    """A 16 x 16 picture as DB16 indices; a transparent pixel is 0, the void."""
    out = []
    for y in range(16):
        row = []
        for x in range(16):
            r, g, b, a = im.getpixel((x, y))
            if a < 128:
                row.append(0)
                continue
            v = (r << 16) | (g << 8) | b
            if v not in _near:
                _near[v] = min(range(16), key=lambda i: sum(
                    (((DB16[i] >> s) & 255) - ((v >> s) & 255)) ** 2 for s in (16, 8, 0)))
            row.append(_near[v])
        out.append(row)
    return out


def pack(rows):
    out = []
    for r in rows:
        for i in range(0, len(r), 2):
            out.append((r[i] << 4) | r[i + 1])
    return out


def quarters(px):
    """A 16 x 16 picture as its four 8 x 8 tiles, top left to bottom right."""
    return [pack([r[ox:ox + 8] for r in px[oy:oy + 8]]) for oy in (0, 8) for ox in (0, 8)]


def rgb12(c):
    return (round(((c >> 16) & 255) / 17) << 8) | (round(((c >> 8) & 255) / 17) << 4) | round((c & 255) / 17)


def mix(a, b, t):
    return sum(round(((a >> s) & 255) * (1 - t) + ((b >> s) & 255) * t) << s for s in (16, 8, 0))


# -------------------------------------------------------------- the font
def render_font():
    """SDS 8x8 at its own size, ASCII 32-126 in a row of 8 x 8 cells."""
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(os.path.join(DL, "GUI", "SDS_8x8.ttf"), 8)
    n = FONT_LAST - FONT_FIRST + 1
    im = Image.new("L", (8 * n, 8), 0)
    d = ImageDraw.Draw(im)
    for i in range(n):
        d.text((i * 8, 0), chr(FONT_FIRST + i), fill=255, font=f)
    assert set(im.getdata()) <= {0, 255}, "the font rendered with grey in it"
    im.point(lambda v: 255 if v else 0).convert("1").save(FONT_PNG)


def font_tiles():
    from PIL import Image
    im = Image.open(FONT_PNG).convert("L")
    out = []
    for i in range(FONT_LAST - FONT_FIRST + 1):
        rows = [[15 if im.getpixel((i * 8 + x, y)) else 0 for x in range(8)] for y in range(8)]
        out.append(pack(rows))
    return out


# ------------------------------------------------------- a theme's banks
def terrain_images(t):
    """(name, 16 x 16 indices) for bank 0's terrain, in the game's order."""
    floor = cut("Objects/Floor.png", *t["floor"])
    wx, wy = t["wall"]
    imgs = []
    for mask in range(16):
        key = ((mask >> 3) & 1, (mask >> 2) & 1, (mask >> 1) & 1, mask & 1)
        c, r = WALL_PIECE[key]
        imgs.append(("WALL" if mask == 0 else "", indices(over(floor, cut("Objects/Wall.png", wx + c, wy + r)))))
    imgs.append(("FLOOR", indices(floor)))
    imgs.append(("CORR", indices(floor)))
    for k in ("closed_h", "open_h", "closed_v", "open_v"):
        imgs.append(("DOOR_" + k.upper(), indices(over(floor, cut(*DOORS[k])))))
    imgs.append(("DOORWAY", indices(floor)))
    imgs.append(("UP", indices(over(floor, cut("Objects/Tile.png", *t["up"])))))
    imgs.append(("DOWN", indices(over(floor, cut("Objects/Tile.png", *t["down"])))))
    return imgs


def creature_images(t, frame):
    floor = cut("Objects/Floor.png", *t["floor"])
    return [indices(over(floor, cut("Characters/Player%d.png" % frame, c, r))) for _, _, c, r in ROLES]


def theme_bytes(t, font):
    """The 32,768 bytes of a theme's four pattern banks."""
    bank0 = [b for g in font for b in g]
    bank0 += [0] * (32 * 96 - len(bank0))            # the terrain starts at tile 96
    for _, px in terrain_images(t):
        bank0 += [b for q in quarters(px) for b in q]
    banks = [bank0, []]
    for frame in (0, 1):
        banks.append([b for px in creature_images(t, frame) for q in quarters(px) for b in q])
    out = bytearray()
    for b in banks:
        assert len(b) <= 8192, len(b)
        out += bytes(b) + bytes(8192 - len(b))
    return bytes(out)


# ------------------------------------------------------------- the file
def palette():
    """The banks: 0 DawnBringer's 16, 1 the same remembered -- dimmed
    towards the void -- then the inks of the text, entry 15 of each."""
    db = [rgb12(c) for c in DB16]
    dim = [rgb12(mix(c, 0x140C1C, 0.58)) for c in DB16]
    inks = [0xDEEED6, 0xDAD45E, 0xD04648, 0x6DAA2C, 0x8595A1, 0x6DC2CA]
    banks = [db, dim] + [[db[0]] * 15 + [rgb12(c)] for c in inks]
    return banks


def act(font):
    lines = [
        "; YENDOR's art table, written by tools/mkyendor.py from DawnLike's sheets --",
        "; run it, do not edit this. Tiles, patterns and the palette are DawnLike's,",
        "; by DragonDePlatino, on DawnBringer's palette (CC-BY 4.0).",
        "",
        "; bank 0: tile FONT_FIRST.. is ASCII from 32; a terrain picture is four",
        "; tiles from its T_ number, and T_WALL + 4 * mask is the wall piece whose",
        "; neighbours are walls by mask: 8 north, 4 south, 2 west, 1 east",
        "CONST FONT_FIRST = %d" % FONT_FIRST,
    ]
    n = 96
    for name, _ in terrain_images(THEMES[0]):
        if name:
            lines.append("CONST T_%s = %d" % (name, n))
        n += 4
    lines.append("; banks 2 and 3: the creatures, a picture four tiles, frame 0 and frame 1")
    for i, (key, _, _, _) in enumerate(ROLES):
        lines.append("CONST C_%s = %d" % (key, i * 4))
    lines.append("CONST N_THEMES = %d" % len(THEMES))
    lines.append("; a theme's file on YENDOR's drive, eleven characters each")
    lines.append('BYTE ARRAY theme_names = "%s"' % "".join(t["file"].ljust(8) + "DAT" for t in THEMES))
    pal = palette()
    lines.append("CONST N_PAL = %d" % len(pal))
    lines.append("; the palette: 0 in view, 1 remembered, 2.. the inks of the text")
    lines.append("CARD ARRAY yendor_pal(%d) = [" % (16 * len(pal)))
    for b in pal:
        lines.append("  " + " ".join("$%03X" % c for c in b))
    lines.append("]")
    return "\n".join(lines) + "\n"


def outputs():
    font = font_tiles()
    files = {OUT: act(font).encode("utf-8")}
    for t in THEMES:
        files[os.path.join(OUT_DIR, t["file"] + ".DAT")] = theme_bytes(t, font)
    return files


def preview(files):
    """Each theme's terrain and heroes as the machine would show them, from
    the bytes of its file and the palette -- a room, a door, the stairs."""
    from PIL import Image
    pal = palette()
    S = 2
    room = [
        "###########",
        "#.........#",
        "#..V......+",
        "#....W....#",
        "#.R.....>.#",
        "#####+#####",
    ]
    W, H = len(room[0]), len(room)
    im = Image.new("RGB", ((W * 16 + 8) * S * len(THEMES), (H * 16 + 8) * S), (20, 12, 28))
    rgb = lambda v: (((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17)   # noqa: E731
    for k, t in enumerate(THEMES):
        dat = files[os.path.join(OUT_DIR, t["file"] + ".DAT")]

        def put(tile, pbank, ox, oy, bank=0):
            base = pbank * 8192 + tile * 32
            for y in range(8):
                for x in range(8):
                    v = dat[base + y * 4 + x // 2]
                    ix = (v >> 4) if x % 2 == 0 else v & 15
                    c = rgb(pal[bank][ix])
                    for dy in range(S):
                        for dx in range(S):
                            im.putpixel((ox + x * S + dx, oy + y * S + dy), c)
        names = {}
        n = 96
        for name, _ in terrain_images(t):
            if name:
                names[name] = n
            n += 4
        X0 = k * (W * 16 + 8) * S + 4 * S
        for y, row in enumerate(room):
            for x, ch in enumerate(row):
                pb = 0
                if ch == "#":
                    wall = lambda dx, dy: 1 if 0 <= y + dy < H and 0 <= x + dx < W and room[y + dy][x + dx] in "#+" else 0  # noqa: E731
                    t0 = names["WALL"] + 4 * (8 * wall(0, -1) + 4 * wall(0, 1) + 2 * wall(-1, 0) + wall(1, 0))
                elif ch == "+":
                    t0 = names["DOOR_CLOSED_H"] if y in (0, H - 1) else names["DOOR_CLOSED_V"]
                elif ch == ">":
                    t0 = names["DOWN"]
                elif ch in "VWR":
                    t0, pb = "VWR".index(ch) * 4, 2
                else:
                    t0 = names["FLOOR"]
                for q in range(4):
                    put(t0 + q, pb, X0 + (x * 16 + 8 * (q & 1)) * S, 4 * S + (y * 16 + 8 * (q >> 1)) * S,
                        1 if (ch == "." and x > 7) else 0)
    im.save(PREVIEW)


def main():
    if "--font" in sys.argv:
        os.makedirs(OUT_DIR, exist_ok=True)
        render_font()
        print("  wrote %s" % os.path.relpath(FONT_PNG, ROOT))
        return 0
    files = outputs()
    if "--check" in sys.argv:
        stale = [p for p, b in files.items() if not os.path.exists(p) or open(p, "rb").read() != b]
        if stale:
            print("  stale: %s -- run python tools/mkyendor.py" % ", ".join(os.path.relpath(p, ROOT) for p in stale))
            return 1
        print("ok -- the art table and the %d theme files are current" % len(THEMES))
        return 0
    os.makedirs(OUT_DIR, exist_ok=True)
    for p, b in files.items():
        with open(p, "wb") as fh:
            fh.write(b.replace(b"\r\n", b"\n"))
    preview(files)
    print("  %d themes, %d bytes each; wrote %s" % (len(THEMES), 32768, ", ".join(
        os.path.relpath(p, ROOT) for p in files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
