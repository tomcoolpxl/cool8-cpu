#!/usr/bin/env python3
"""Blockade's characters, out of a screenshot of the arcade's own screen.

    python tools/mkblockade.py            write assets/blockade/blockade_art.act and a preview
    python tools/mkblockade.py --check    the art file is current
    python tools/mkblockade.py --cells    every distinct 8x8 cell of the screenshot, and the grid

**The art is the original's.** Gremlin's Blockade (1976) draws its
screen from a map of 8 x 8 characters, 256 x 224 of it seen (MAME's
src/mame/sega/blockade.cpp). `assets/blockade/Blockade_gameplay.png` is
StrategyWiki's screenshot of it at that size, downloaded by the owner's
decision; every cell the game draws is cut from it.

**What is read, and how it was found.** The screenshot is two colours,
black and $0F0, on an 8-pixel grid from (0, 0): 10 distinct cells
there, 13 or more at any other offset (`--cells`). They are the blank;
the border's two straight pieces and its four corners; a 6 in the top
border's middle, the points a game is played to; player 1's head, a
solid arrow pointing down; and player 2's, an outlined one pointing
left. The trails are drawn with the border's own pieces -- a turn is
the corner joining the two sides the trail leaves it by -- which is
checked at every turn in the picture, not assumed.

**What is derived.** The picture has each head pointing one way; the
other three ways are that head mirrored or turned a quarter, which no
frame shows, so they are not checked.

Two more screenshots of the arcade, the Arcade Museum's, were read in
the browser for the digits and heads this one lacks, and not kept:
JPEGs of the same pieces blurred, the same 6 and the same two heads,
and in one a word too blurred to read.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkmscool                                  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "assets", "blockade")
SHOT = os.path.join(ART, "Blockade_gameplay.png")
OUT = os.path.join(ART, "blockade_art.act")
PREVIEW = os.path.join(ART, "preview.png")
W, H = 256, 224

# where each piece is in the screenshot, by its cell's (column, row)
PIECES = [
    ("BLANK", (1, 1)),
    ("VERT", (0, 1)),                  # the side borders; a trail going up or down
    ("HORZ", (1, 0)),                  # the top and bottom; a trail going across
    ("RD", (0, 0)),                    # the corners, by the two sides they join
    ("LD", (31, 0)),
    ("UR", (0, 27)),
    ("UL", (31, 27)),
    ("SIX", (16, 0)),                  # the points a game is played to
    ("HEAD1", (5, 21)),                # player 1's head, going down
    ("HEAD2", (17, 16)),               # player 2's, going left
]
# every turn the picture's trails make, and the corner it is drawn with
TURNS = {(22, 16): "LD", (26, 20): "LD", (21, 18): "RD", (22, 18): "UL", (21, 20): "UR"}


def grid(px, ox=0, oy=0):
    """Every distinct 8 x 8 cell on the grid from (ox, oy): its pixels as
    a tuple of rows, and the cells where it is."""
    seen = {}
    for cy in range((H - oy) // 8):
        for cx in range((W - ox) // 8):
            c = tuple(tuple(px[ox + cx * 8 + x, oy + cy * 8 + y] for x in range(8)) for y in range(8))
            seen.setdefault(c, []).append((cx, cy))
    return seen


def show_cells(px):
    """The grid's alignment -- the offset with the fewest distinct cells
    is the one the characters sit on -- then each distinct cell there,
    a letter a colour."""
    counts = sorted((len(grid(px, ox, oy)), ox, oy) for oy in range(8) for ox in range(8))
    print("  distinct cells by grid offset, fewest first: %s" %
          ", ".join("(%d, %d) %d" % (ox, oy, n) for n, ox, oy in counts[:6]))
    seen = grid(px)
    cols = sorted({p for c in seen for row in c for p in row}, key=sum)
    key = {c: (".#+*o@"[i] if i < 6 else "?") for i, c in enumerate(cols)}
    print("  colours: %s" % ", ".join("%s %s $%03X" % (key[c], c, mkmscool.q4(c)) for c in cols))
    for n, (c, where) in enumerate(sorted(seen.items(), key=lambda kv: -len(kv[1]))):
        print("  cell %d: %d times, first at %s" % (n, len(where), where[:6]))
        for row in c:
            print("      " + "".join(key[p] for p in row))


def cut(px, cx, cy):
    """A cell as eight rows of 0 (black) and 1 (the screen's colour)."""
    return tuple(tuple(0 if px[cx * 8 + x, cy * 8 + y] == (0, 0, 0) else 1 for x in range(8))
                 for y in range(8))


def flip_h(c):
    return tuple(tuple(reversed(r)) for r in c)


def flip_v(c):
    return tuple(reversed(c))


def turn(c):
    """A quarter turn clockwise: the bottom row becomes the left column."""
    return tuple(tuple(c[7 - x][y] for x in range(8)) for y in range(8))


def heads(down=None, left=None):
    """A head's four ways -- up, right, down, left, the game's order --
    from the one the picture has."""
    if down is not None:
        left = turn(down)
        return [flip_v(down), flip_h(left), down, left]
    up = turn(left)
    return [up, flip_h(left), flip_v(up), left]


def rip(px):
    """The pieces, checked against the picture, then the heads' four
    ways: (name, cell) in tile order, and the screen's colour."""
    seen = grid(px)
    colours = {p for c in seen for row in c for p in row} - {(0, 0, 0)}
    assert len(colours) == 1, "the screenshot is not two colours: %s" % sorted(colours)
    assert len(seen) == len(PIECES), "%d distinct cells on the grid, not %d" % (len(seen), len(PIECES))
    cells = {name: cut(px, *at) for name, at in PIECES}
    assert len(set(cells.values())) == len(PIECES), "two pieces are the same cell"
    for at, name in TURNS.items():
        assert cut(px, *at) == cells[name], "the turn at %s is not drawn with the %s corner" % (at, name)
    tiles = [(name, cells[name]) for name, _ in PIECES if not name.startswith("HEAD")]
    tiles += [("HEAD1_" + "URDL"[d], c) for d, c in enumerate(heads(down=cells["HEAD1"]))]
    tiles += [("HEAD2_" + "URDL"[d], c) for d, c in enumerate(heads(left=cells["HEAD2"]))]
    assert tiles[10][1] == cells["HEAD1"] and tiles[15][1] == cells["HEAD2"]
    return tiles, mkmscool.q4(colours.pop())


def tilebytes(c):
    """A cell as 4 bpp tile bytes, high nibble first: 0 black, 1 the colour."""
    return [(r[i] << 4) | r[i + 1] for r in c for i in range(0, 8, 2)]


def act(tiles, colour):
    lines = [
        "; BLOCKADE's characters, written by tools/mkblockade.py from",
        "; assets/blockade/Blockade_gameplay.png -- run it, do not edit this.",
        ";",
        "; A tile is 8 x 8 at 4 bpp, 0 black and 1 the screen's colour. The",
        "; heads are four each, up, right, down, left; the one the picture shows",
        "; (player 1 down, player 2 left) is ripped, the other three turned.",
        "",
    ]
    for i, (name, _) in enumerate(tiles):
        if not name.startswith("HEAD") or name.endswith("_U"):
            lines.append("CONST T_%s = %d" % (name.split("_")[0], i))
    lines.append("CONST N_TILES = %d" % len(tiles))
    lines.append("CARD ARRAY blk_pal(2) = [0 %d]" % colour)
    lines.append("BYTE ARRAY blk_tiles(%d) = [" % (32 * len(tiles)))
    for _, c in tiles:
        lines.append("  " + " ".join(str(b) for b in tilebytes(c)))
    lines.append("]")
    return "\n".join(lines) + "\n"


def preview(tiles, colour):
    """The tiles four times over, in their order, on grey."""
    from PIL import Image
    ink = tuple(((colour >> s) & 15) * 17 for s in (8, 4, 0))
    im = Image.new("RGB", (8 * 36 + 4, 2 * 36 + 4), (48, 48, 48))
    for i, (_, c) in enumerate(tiles):
        ox, oy = 4 + (i % 8) * 36, 4 + (i // 8) * 36
        for y in range(32):
            for x in range(32):
                im.putpixel((ox + x, oy + y), ink if c[y // 4][x // 4] else (0, 0, 0))
    im.save(PREVIEW)


def main():
    px = mkmscool.load(SHOT)
    if "--cells" in sys.argv:
        show_cells(px)
        return 0
    tiles, colour = rip(px)
    text = act(tiles, colour)
    if "--check" in sys.argv:
        have = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if have != text:
            print("  %s is stale: run python tools/mkblockade.py" % os.path.relpath(OUT, ROOT))
            return 1
        print("ok -- the art file is current")
        return 0
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(text)
    preview(tiles, colour)
    print("  %d tiles, the screen's colour $%03X; %d turns checked against the corners"
          % (len(tiles), colour, len(TURNS)))
    print("  wrote %s and %s" % (os.path.relpath(OUT, ROOT), os.path.relpath(PREVIEW, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
