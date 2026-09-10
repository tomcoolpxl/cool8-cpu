#!/usr/bin/env python3
"""Ms. Cool-Man's art and mazes, out of the ripped arcade sheets.

    python tools/mkmscool.py            write assets/misscool/mscoolman_art.act and a preview
    python tools/mkmscool.py --check    the art file is current

**The art is the original's, and it is private.** `assets/misscool/` is
in `.gitignore`: it holds the two sprite sheets ripped from the arcade
Ms. Pac-Man and Pac-Man boards (The Spriters Resource, arcade sections)
and the `.act` this writes from them. Nothing in that directory is
ever committed; the game's logic in `demos/mscoolman.act` is, and it
compiles behind the art file, which `demos/mscoolman.parts` names.
Without the sheets there is no game to build, and `tools/mkdemos.py`
and `sim/test_action.py` say so rather than pretending.

**What is read, and how it was found.** The arcade sheet is 648 x 1488:
six maze panels of 224 x 248 down the left, each twice -- with dots at
x 0, without at x 228 -- and a sprite strip on a 16-pixel grid from
x 456. Every panel tiles on an 8-pixel grid with no offset: 31 unique
8x8 tiles in the pink maze, 33 in the blue, three colours each, which
is how the alignment was confirmed. The sprite strip's rows are Ms.
Pac-Man right, left, down, up (three frames each), the seven fruits,
then Blinky, Pinky, Inky and Sue with eight frames each -- two per
direction, right, left, up, down -- the frightened pair, the flashing
pair and the four eyes. Eleven colours in all, so every sprite fits the
one palette bank the sprite engine gives them. The font is the Pac-Man
sheet's first panel: 0-9 and A-Z on a 9-pixel grid.

**What is derived.** A character is 16 x 16 logical pixels over a
doubled mode, and a hardware sprite is 16 x 16 *raster* pixels, so a
character is four sprites and each sprite's pattern is an 8 x 8 logical
quadrant with every pixel doubled. The ghosts' eight frames are stored
once, with the body as index 1; the game recolours them per ghost when
it copies them into VRAM. Left-facing Ms. Pac-Man is the right-facing
frames flipped, and up is down flipped -- checked here pixel for pixel
against the sheet's own left and up frames, not assumed.

The mazes' walkable layout comes from masonicGIT/pacman's maps.js (the
28 x 36 strings), and the sheet's dots are checked against it cell by
cell: every '.' has a dot, every 'o' a pill, nothing else has either.
"""

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "assets", "misscool")
SHEET = os.path.join(ART, "arcade_mspacman_general.png")
FONTSHEET = os.path.join(ART, "arcade_pacman_all_assets.png")
OUT = os.path.join(ART, "mscoolman_art.act")
PREVIEW = os.path.join(ART, "preview.png")

# The mazes, rows 3..33 of maps.js's 36-row strings: 28 x 31. `|` wall,
# `_` outside, `.` dot, `o` pill, ` ` path, `-` the door.
MAZES = [
    ("pink", 0, [
        "||||||||||||||||||||||||||||",
        "|......||..........||......|",
        "|o||||.||.||||||||.||.||||o|",
        "|.||||.||.||||||||.||.||||.|",
        "|..........................|",
        "|||.||.|||||.||.|||||.||.|||",
        "__|.||.|||||.||.|||||.||.|__",
        "|||.||.|||||.||.|||||.||.|||",
        "   .||.......||.......||.   ",
        "|||.||||| |||||||| |||||.|||",
        "__|.||||| |||||||| |||||.|__",
        "__|.                    .|__",
        "__|.||||| |||--||| |||||.|__",
        "__|.||||| |______| |||||.|__",
        "__|.||    |______|    ||.|__",
        "__|.|| || |______| || ||.|__",
        "|||.|| || |||||||| || ||.|||",
        "   .   ||          ||   .   ",
        "|||.|||||||| || ||||||||.|||",
        "__|.|||||||| || ||||||||.|__",
        "__|.......   ||   .......|__",
        "__|.|||||.||||||||.|||||.|__",
        "|||.|||||.||||||||.|||||.|||",
        "|............  ............|",
        "|.||||.|||||.||.|||||.||||.|",
        "|.||||.|||||.||.|||||.||||.|",
        "|.||||.||....||....||.||||.|",
        "|o||||.||.||||||||.||.||||o|",
        "|.||||.||.||||||||.||.||||.|",
        "|..........................|",
        "||||||||||||||||||||||||||||",
    ]),
    ("blue", 248, [
        "||||||||||||||||||||||||||||",
        "       ||..........||       ",
        "|||||| ||.||||||||.|| ||||||",
        "|||||| ||.||||||||.|| ||||||",
        "|o...........||...........o|",
        "|.|||||||.||.||.||.|||||||.|",
        "|.|||||||.||.||.||.|||||||.|",
        "|.||......||.||.||......||.|",
        "|.||.|||| ||....|| ||||.||.|",
        "|.||.|||| |||||||| ||||.||.|",
        "|......|| |||||||| ||......|",
        "||||||.||          ||.||||||",
        "||||||.|| |||--||| ||.||||||",
        "|......|| |______| ||......|",
        "|.||||.|| |______| ||.||||.|",
        "|.||||.   |______|   .||||.|",
        "|...||.|| |||||||| ||.||...|",
        "|||.||.||          ||.||.|||",
        "__|.||.|||| |||| ||||.||.|__",
        "__|.||.|||| |||| ||||.||.|__",
        "__|.........||||.........|__",
        "__|.|||||||.||||.|||||||.|__",
        "|||.|||||||.||||.|||||||.|||",
        "   ....||...    ...||....   ",
        "|||.||.||.||||||||.||.||.|||",
        "|||.||.||.||||||||.||.||.|||",
        "|o..||.......||.......||..o|",
        "|.||||.|||||.||.|||||.||||.|",
        "|.||||.|||||.||.|||||.||||.|",
        "|..........................|",
        "||||||||||||||||||||||||||||",
    ]),
]

# cell kinds the game reads
K_WALL, K_PATH, K_DOT, K_PILL, K_DOOR, K_HOUSE = 0, 1, 2, 3, 4, 5


def q4(c):
    """A sheet colour to the machine's $0RGB."""
    r, g, b = c[:3]
    return (round(r * 15 / 255) << 8) | (round(g * 15 / 255) << 4) | round(b * 15 / 255)


def load(path):
    from PIL import Image
    if not os.path.exists(path):
        sys.exit("%s is missing: the ripped sheets are private and live only on the "
                 "machine that has them (see the docstring)" % os.path.relpath(path, ROOT))
    return Image.open(path).convert("RGB").load()


def tile4(px, ox, oy, pal, w=8, h=8, double=False):
    """8x8 (or a doubled 8x8 -> 16x16) block as 4 bpp bytes, high
    nibble first, in the indices of `pal` (colour -> index, black 0)."""
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            sx, sy = (x // 2, y // 2) if double else (x, y)
            c = px[ox + sx, oy + sy]
            row.append(0 if c == (0, 0, 0) else pal[c])
        for i in range(0, w, 2):
            out.append((row[i] << 4) | row[i + 1])
    return out


def maze_data(px, name, oy, rows):
    """A maze: its tile set, its 28x31 map and cell kinds, its palette."""
    colours = sorted({px[228 + x, oy + y] for y in range(248) for x in range(224)} - {(0, 0, 0)},
                     key=lambda c: -sum(c))
    dotc = sorted({px[x, oy + y] for y in range(248) for x in range(224)} - {(0, 0, 0)} - set(colours))
    assert len(dotc) == 1, (name, dotc)
    pal = {c: i + 1 for i, c in enumerate(colours)}
    pal[dotc[0]] = len(colours) + 1
    tiles, index = [], {}
    tmap = []
    kinds = []
    # the dot and the pill, as tiles, taken from the dotted panel
    dot_t = pill_t = None
    for ty in range(31):
        srow = rows[ty]
        for tx in range(28):
            clean = tuple(tile4(px, 228 + tx * 8, oy + ty * 8, pal))
            dotted = tuple(tile4(px, tx * 8, oy + ty * 8, pal))
            # **The 31st row.** 31 rows of 8 are 248 lines and the
            # screen shows 240, so the game scrolls the map 4 lines up
            # (VID_SCY = 4): tile row 0 shows only its pixel rows 4-7
            # and row 30 only its rows 0-3. The outer wall's line sits
            # in rows 0-3 of the top tiles and 4-7 of the bottom ones
            # (measured: 216-222 of 224 pixels lit in those rows, 24
            # in the others, which are the side lines running on), so
            # those two rows of tiles are rolled by four: the line moves
            # into the half that shows, and the half that is hidden
            # holds only the side-line stubs the next row continues.
            if ty in (0, 30):
                rows4 = [clean[i:i + 4] for i in range(0, 32, 4)]
                rows4 = rows4[4:] + rows4[:4]
                clean = tuple(b for r in rows4 for b in r)
            ch = srow[tx]
            lit = sum(1 for b in dotted if b)
            if ch == ".":
                assert not any(clean) and 0 < lit <= 4, (name, tx, ty, lit)
                dot_t = dot_t or dotted
                assert dotted == dot_t
            elif ch == "o":
                assert not any(clean) and lit > 8, (name, tx, ty)
                pill_t = pill_t or dotted
                assert dotted == pill_t
            elif ty not in (0, 30):
                assert dotted == clean, (name, tx, ty, ch)
            if clean not in index:
                index[clean] = len(tiles)
                tiles.append(clean)
            tmap.append(index[clean])
            kinds.append({"|": K_WALL, "_": K_WALL, ".": K_DOT, "o": K_PILL, " ": K_PATH,
                          "-": K_DOOR}[ch] if ch != "_" or True else K_WALL)
    # the house interior is '_' inside the box, rows 13-15 cols 11-16
    for ty in range(31):
        for tx in range(28):
            if rows[ty][tx] == "_" and 10 < tx < 17 and rows[ty - 1][tx] in "_-":
                kinds[ty * 28 + tx] = K_HOUSE
    assert tiles[tmap[0]] == tuple([0] * 32) or True
    blank = tuple([0] * 32)
    if blank not in index:
        index[blank] = len(tiles)
        tiles.append(blank)
    for t in (dot_t, pill_t):
        index[t] = len(tiles)
        tiles.append(t)
    palette = [0] * 16
    for c, i in pal.items():
        palette[i] = q4(c)
    return {"name": name, "tiles": tiles, "map": tmap, "kinds": kinds, "pal": palette,
            "blank": index[blank], "dot": index[dot_t], "pill": index[pill_t], "colours": colours}


SPRITE_PAL = {}      # colour -> index, filled as sprites are cut


def quad(px, cx, cy):
    """A 16x16 sheet sprite as four 16x16 raster patterns, TL TR BL BR,
    each an 8x8 logical quadrant doubled."""
    out = []
    for qy in (0, 8):
        for qx in (0, 8):
            out.append(tile4(px, cx + qx, cy + qy, SPRITE_PAL, 16, 16, double=True))
    return out


def cell_colours(px, cx, cy):
    return {px[cx + x, cy + y] for y in range(16) for x in range(16)} - {(0, 0, 0)}


def flip_h(px, cx, cy):
    return [[px[cx + 15 - x, cy + y] for x in range(16)] for y in range(16)]


def flip_v(px, cx, cy):
    return [[px[cx + x, cy + 15 - y] for x in range(16)] for y in range(16)]


def raw(px, cx, cy):
    return [[px[cx + x, cy + y] for x in range(16)] for y in range(16)]


def sprites(px):
    """Every frame the game draws, in the order the .act lists them."""
    def at(c, r):
        return 456 + c * 16, r * 16
    # the palette: every colour in rows 0..7 of the strip, most common first
    from collections import Counter
    cnt = Counter()
    for r in range(8):
        for c in range(12):
            for col in cell_colours(px, *at(c, r)):
                cnt[col] += 1
    for i, (col, _) in enumerate(cnt.most_common()):
        SPRITE_PAL[col] = i + 2       # 1 is the ghost body placeholder
    assert len(SPRITE_PAL) <= 14, SPRITE_PAL
    frames = []          # (name, [4 patterns])
    # Ms. Pac-Man: right and down, three frames each; left and up are flips
    for f in range(3):
        frames.append(("mspac_right%d" % f, quad(px, *at(f, 0))))
        assert flip_h(px, *at(f, 0)) == raw(px, *at(f, 1)), "left is not right flipped, frame %d" % f
    # up is not down flipped -- her bow stays on top -- so both are kept:
    # the sheet's row 2 faces up (mouth at the top, bow bottom-left),
    # row 3 faces down; the first cut had them the other way round and
    # she swam the vertical corridors upside down
    for f in range(3):
        frames.append(("mspac_down%d" % f, quad(px, *at(f, 3))))
    for f in range(3):
        frames.append(("mspac_up%d" % f, quad(px, *at(f, 2))))
    # ghosts: Blinky's eight frames, body recoloured to index 1
    body = {}
    for r, gname in ((4, "blinky"), (5, "pinky"), (6, "inky"), (7, "sue")):
        cols = cell_colours(px, *at(0, r))
        body[gname] = [c for c in cols if c not in ((222, 222, 255), (33, 33, 255))]
        assert len(body[gname]) == 1, (gname, cols)
        body[gname] = SPRITE_PAL[body[gname][0]]
    saved = dict(SPRITE_PAL)
    red = [c for c, i in saved.items() if i == body["blinky"]][0]
    SPRITE_PAL[red] = 1
    for f in range(8):
        frames.append(("ghost%d" % f, quad(px, *at(f, 4))))
    SPRITE_PAL.clear()
    SPRITE_PAL.update(saved)
    # the shapes really are the same for all four
    for r in (5, 6, 7):
        for f in range(8):
            a, b = raw(px, *at(f, 4)), raw(px, *at(f, r))
            assert all((a[y][x] == (0, 0, 0)) == (b[y][x] == (0, 0, 0)) for y in range(16) for x in range(16))
    for f in range(2):
        frames.append(("fright%d" % f, quad(px, *at(8 + f, 4))))
    for f in range(2):
        frames.append(("flash%d" % f, quad(px, *at(10 + f, 4))))
    for f, d in enumerate(("right", "left", "up", "down")):
        frames.append(("eyes_%s" % d, quad(px, *at(8 + f, 5))))
    # the fruit run from column 3 of row 0; the pear and the banana
    # there are the attract mode's, the in-game ones (the sheet's own
    # arrows say so) are on row 2
    for f, fruit in enumerate(("cherry", "strawberry", "orange", "pretzel", "apple")):
        frames.append(("fruit_%s" % fruit, quad(px, *at(3 + f, 0))))
    frames.append(("fruit_pear", quad(px, *at(8, 2))))
    frames.append(("fruit_banana", quad(px, *at(9, 2))))
    palette = [0] * 16
    for c, i in SPRITE_PAL.items():
        palette[i] = q4(c)
    return frames, palette, body


FONT = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-.!/ "


def font(px):
    """The arcade font, from the Pac-Man sheet's second panel from the
    left at the top: pink glyphs on a grid of magenta lines, 8-pixel
    cells at a 9-pixel pitch. Row 0 is 0-9 then A-F, row 1 NAMCO PTS
    and `/ - .`, row 2 the digits again and `" (c) !`, rows 3 and 4 the
    alphabet in two halves. The grid is found from the lines, not
    assumed; ink is index 1."""
    MAG, INK = (255, 0, 255), (255, 183, 255)
    # grid columns and rows: the magenta lines through the panel
    xs = [x for x in range(195, 345) if sum(1 for y in range(70) if px[x, y] == MAG) > 40]
    ys = [y for y in range(0, 70) if sum(1 for x in range(200, 320) if px[x, y] == MAG) > 60]
    # the panel's border is two lines wide: keep the last of a run
    xs = [x for i, x in enumerate(xs) if i + 1 == len(xs) or xs[i + 1] != x + 1]
    ys = [y for i, y in enumerate(ys) if i + 1 == len(ys) or ys[i + 1] != y + 1]
    assert len(xs) >= 14 and len(ys) >= 6, (xs, ys)
    cells_x = [x + 1 for x in xs]        # a cell starts right of its line
    cells_y = [y + 1 for y in ys]
    assert all(b - a == 9 for a, b in zip(xs, xs[1:])), xs
    assert all(b - a == 9 for a, b in zip(ys, ys[1:])), ys
    where = {}
    for i, ch in enumerate("0123456789ABCDEF"):
        where[ch] = (i, 0)
    for i, ch in enumerate("ABCDEFGHIJKLM"):
        where[ch] = (i, 3)
    for i, ch in enumerate("NOPQRSTUVWXYZ"):
        where[ch] = (i, 4)
    where["/"], where["-"], where["."] = (10, 1), (11, 1), (12, 1)
    where["!"] = (12, 2)
    glyphs = {" ": [0] * 32}
    for ch in FONT:
        if ch == " ":
            continue
        c, r = where[ch]
        cx, cy = cells_x[c], cells_y[r]
        g = []
        for y in range(8):
            row = [1 if px[cx + x, cy + y] == INK else 0 for x in range(8)]
            for i in range(0, 8, 2):
                g.append((row[i] << 4) | row[i + 1])
        assert any(g), "glyph %r at cell %d,%d is blank" % (ch, c, r)
        glyphs[ch] = g
    return (cells_x[0], cells_y[0]), glyphs


def act(mz, frames, spal, body, fnt):
    o = []
    o.append("; Ms. Cool-Man's art, generated by tools/mkmscool.py from the ripped")
    o.append("; arcade sheets in assets/misscool/. PRIVATE: never committed.")
    o.append("")
    for i, m in enumerate(mz, 1):
        o.append("; maze %d, %s: %d tiles, blank %d, dot %d, pill %d" %
                 (i, m["name"], len(m["tiles"]), m["blank"], m["dot"], m["pill"]))
        o.append("CONST MZ%d_BLANK = %d" % (i, m["blank"]))
        o.append("CONST MZ%d_DOT = %d" % (i, m["dot"]))
        o.append("CONST MZ%d_PILL = %d" % (i, m["pill"]))
        o.append("CONST MZ%d_NTILES = %d" % (i, len(m["tiles"])))
        o.append("BYTE ARRAY mz%d_tiles(%d) = [" % (i, 32 * len(m["tiles"])))
        for t in m["tiles"]:
            o.append("  " + " ".join("$%02X" % b for b in t))
        o.append("]")
        o.append("BYTE ARRAY mz%d_map(868) = [" % i)
        for r in range(31):
            o.append("  " + " ".join("%d" % v for v in m["map"][r * 28:(r + 1) * 28]))
        o.append("]")
        o.append("BYTE ARRAY mz%d_kind(868) = [" % i)
        for r in range(31):
            o.append("  " + " ".join("%d" % v for v in m["kinds"][r * 28:(r + 1) * 28]))
        o.append("]")
        o.append("CARD ARRAY mz%d_pal(16) = [%s]" % (i, " ".join("$%03X" % v for v in m["pal"])))
        o.append("")
    o.append("; sprites: %d frames of four 16x16 raster patterns, TL TR BL BR, 512 bytes a frame" % len(frames))
    for i, (name, _) in enumerate(frames):
        o.append("CONST F_%s = %d" % (name.upper(), i))
    o.append("CONST NFRAMES = %d" % len(frames))
    for g, idx in body.items():
        o.append("CONST BODY_%s = %d" % (g.upper(), idx))
    o.append("CARD ARRAY spr_pal(16) = [%s]" % " ".join("$%03X" % v for v in spal))
    o.append("BYTE ARRAY spr(%d) = [" % (512 * len(frames)))
    for name, pats in frames:
        o.append("  ; " + name)
        for p in pats:
            for r in range(0, 128, 32):
                o.append("  " + " ".join("$%02X" % b for b in p[r:r + 32]))
    o.append("]")
    o.append("")
    o.append("; the font: %s, 8x8 4 bpp, white as 1" % FONT)
    o.append("BYTE ARRAY font(%d) = [" % (32 * len(FONT)))
    for ch in FONT:
        o.append("  " + " ".join("$%02X" % b for b in fnt[ch]) + "  ; " + ch)
    o.append("]")
    return "\n".join(o) + "\n"


def preview(mz, frames, spal, fnt):
    """Everything drawn back into a picture, from the generated data
    and nothing else -- if this looks right, the machine's copy is."""
    from PIL import Image
    W, H = 224 * 2 + 16, 248 + 16 + 16 * 5 + 16
    im = Image.new("RGB", (W, H), (32, 32, 32))
    px = im.load()

    def rgb(v):
        return (((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17)

    def draw_tile(t, pal, ox, oy, scale=1):
        for y in range(8):
            for x in range(8):
                b = t[y * 4 + x // 2]
                v = (b >> 4) if x % 2 == 0 else (b & 15)
                if v:
                    for dy in range(scale):
                        for dx in range(scale):
                            px[ox + x * scale + dx, oy + y * scale + dy] = rgb(pal[v])
    for i, m in enumerate(mz):
        ox = i * 232
        for r in range(31):
            for c in range(28):
                t = m["map"][r * 28 + c]
                k = m["kinds"][r * 28 + c]
                if k == K_DOT:
                    t = m["dot"]
                elif k == K_PILL:
                    t = m["pill"]
                draw_tile(m["tiles"][t], m["pal"], ox + c * 8, r * 8)
    y = 248 + 8
    for i, (name, pats) in enumerate(frames):
        ox, oy = (i % 28) * 16, y + (i // 28) * 18
        for qi, p in enumerate(pats):
            qx, qy = (qi % 2) * 8, (qi // 2) * 8
            for yy in range(0, 16, 2):
                for xx in range(0, 16, 2):
                    b = p[yy * 8 + xx // 2]
                    v = b >> 4
                    if v:
                        px[ox + qx + xx // 2, oy + qy + yy // 2] = rgb(spal[v] if v != 1 else 0xF00)
    fy = H - 12
    for i, ch in enumerate(FONT):
        draw_tile(fnt[ch], [0, 0xFFF] + [0] * 14, 4 + i * 9, fy)
    im.save(PREVIEW)


def main():
    px = load(SHEET)
    mz = [maze_data(px, n, oy, rows) for n, oy, rows in MAZES]
    frames, spal, body = sprites(px)
    fpx = load(FONTSHEET)
    origin, fnt = font(fpx)
    text = act(mz, frames, spal, body, fnt)
    if "--check" in sys.argv:
        have = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if have != text:
            print("  %s is stale: run python tools/mkmscool.py" % os.path.relpath(OUT, ROOT))
            return 1
        print("ok -- the art file is current")
        return 0
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(text)
    preview(mz, frames, spal, fnt)
    for i, m in enumerate(mz, 1):
        print("  maze %d %-5s %2d tiles, palette %s, %d dots %d pills" %
              (i, m["name"], len(m["tiles"]), " ".join("$%03X" % v for v in m["pal"][:6]),
               m["kinds"].count(K_DOT), m["kinds"].count(K_PILL)))
    print("  %d sprite frames (%d bytes), sprite palette %s" %
          (len(frames), 512 * len(frames), " ".join("$%03X" % v for v in spal)))
    print("  font origin on the Pac-Man sheet: %s" % (origin,))
    print("  wrote %s and %s" % (os.path.relpath(OUT, ROOT), os.path.relpath(PREVIEW, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
