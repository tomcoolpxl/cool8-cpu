#!/usr/bin/env python3
"""Turn a BDF font into the 4 KB image the font EBR is initialised with.

    python tools/mkfont.py assets/font/spleen-8x16.bdf -o sim/build/font.hex

256 glyphs of 8x16, one byte per row, glyph *n* at offset *n* x 16 — the
layout `cool8_font.v` reads and `synth_ice40` bakes into eight
`SB_RAM40_4K`. Bit 7 of each byte is the leftmost pixel.

The character set is **CP437**, mapped through Python's own codec rather
than through a table written out here, so the mapping is the one everyone
else means by CP437 and there is nothing to get wrong. Codes `$00-$1F`
are CP437's decorative glyphs (smilies, card suits, arrows); a font that
does not carry them leaves those cells blank, which is what a terminal
font like Spleen does and is not worth faking.

Any BDF of the right cell size works — this parses the bounding boxes
rather than assuming them — so swapping the font is one argument.
"""

import argparse
import os
import sys

CELL_W = 8
CELL_H = 16
GLYPHS = 256


def parse_bdf(path):
    """{codepoint: [row bitmasks, top first]} plus the font bounding box."""
    glyphs = {}
    fb = None
    enc = bbx = None
    rows = None

    with open(path, encoding="latin-1") as fh:
        for line in fh:
            w = line.split()
            if not w:
                continue
            k = w[0]
            if k == "FONTBOUNDINGBOX":
                fb = tuple(int(v) for v in w[1:5])
            elif k == "ENCODING":
                enc = int(w[1])
            elif k == "BBX":
                bbx = tuple(int(v) for v in w[1:5])
            elif k == "BITMAP":
                rows = []
            elif k == "ENDCHAR":
                if enc is not None and enc >= 0 and bbx and rows is not None:
                    glyphs[enc] = (bbx, rows)
                enc = bbx = None
                rows = None
            elif rows is not None:
                rows.append(w[0])

    if fb is None:
        sys.exit(f"{path}: no FONTBOUNDINGBOX")
    return glyphs, fb


def compose(bbx, rows, fb):
    """Place one glyph's bitmap into a CELL_W x CELL_H cell.

    BDF puts the glyph origin on the baseline and gives every bounding
    box as an offset from it, so a glyph smaller than the cell has to be
    positioned rather than just copied — which is most of them, and
    getting it wrong shifts descenders by a row.
    """
    bw, bh, bxoff, byoff = bbx
    fbw, fbh, fbxoff, fbyoff = fb
    cell = [0] * CELL_H
    stride = (bw + 7) // 8

    for r, hexrow in enumerate(rows[:bh]):
        bits = int(hexrow, 16) if hexrow else 0
        bits <<= (stride * 8 - len(hexrow) * 4)     # left-justify short rows
        y = fbyoff + fbh - byoff - bh + r           # row inside the cell
        if not (0 <= y < CELL_H):
            continue
        acc = 0
        for c in range(bw):
            if bits & (1 << (stride * 8 - 1 - c)):
                x = bxoff + c - fbxoff
                if 0 <= x < CELL_W:
                    acc |= 1 << (CELL_W - 1 - x)
        cell[y] |= acc
    return cell


def build(path):
    glyphs, fb = parse_bdf(path)
    img = bytearray(GLYPHS * CELL_H)
    present = 0
    for code in range(GLYPHS):
        try:
            u = ord(bytes([code]).decode("cp437"))
        except UnicodeDecodeError:
            continue
        g = glyphs.get(u)
        if g is None:
            continue
        present += 1
        cell = compose(g[0], g[1], fb)
        img[code * CELL_H:(code + 1) * CELL_H] = bytes(cell)
    return bytes(img), present, fb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bdf")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    img, present, fb = build(args.bdf)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        for b in img:
            fh.write("%02x\n" % b)
    print(f"  {os.path.basename(args.bdf)}: bounding box {fb[0]}x{fb[1]}, "
          f"{present}/256 CP437 glyphs, {len(img)} bytes -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
