#!/usr/bin/env python3
"""COOLTRIS's art: the block, the ghost, the frame, the weave, the font,
the palettes and the tune.

    python tools/mkcooltris.py           write assets/cooltris/cooltris_art.act and a preview
    python tools/mkcooltris.py --check   the art file is current

**The picture is this port's own.** COOLTRIS is a falling-block game in
the manner of the 1989 NES one, and its *numbers* follow that game's
published ones -- gravity by level, the 40/100/300/1200 scoring, the
16-then-6 frame key repeat (tetris.wiki) -- but none of its pixels. Every
tile here is drawn by this script: one bevelled block, a hollow ghost of
it, eight frame pieces, a background weave, and the glyphs, which are the
Namco font the Ms. Cool-Man sheets carry, as Arkanoid uses them.

**A block's colour is its palette bank**, so the seven shapes cost one
pattern and seven banks of four colours, and a shape keeps its colour all
game. The surround -- frame, weave, panels, headings -- is one bank
written again at every level, so the twentieth screen looks nothing like
the first while the pieces stay where the eye left them.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkmscool                                  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "assets", "cooltris")
OUT = os.path.join(ART, "cooltris_art.act")
PREVIEW = os.path.join(ART, "preview.png")

# ------------------------------------------------------------- the tiles
# Each is 8 x 8 of palette indices. In a piece's bank: 0 the outline, 1
# the light face, 2 the body, 3 the shade. In the surround's: 0 the
# ground, 1 the weave, 2 the frame's dark, 3 its body, 4 its light, 5 its
# shine.
BLOCK = ["00000000",
         "01111112",
         "01222232",
         "01223332",
         "01233332",
         "01333332",
         "02222222",
         "00000000"]
GHOST = ["00000000",
         "02222220",
         "02000020",
         "02000020",
         "02000020",
         "02000020",
         "02222220",
         "00000000"]
WEAVE = ["11000000",
         "10000000",
         "00000000",
         "00000100",
         "00001100",
         "00000000",
         "00000000",
         "00000000"]
# the well's frame and the panels': a bevel with the light on the outside
FRAME = {
    "TL": ["44444444", "43333333", "43222222", "43222222", "43222222", "43222222", "43222222", "43222222"],
    "T":  ["44444444", "33333333", "22222222", "22222222", "22222222", "22222222", "22222222", "22222222"],
    "TR": ["44444444", "33333334", "22222234", "22222234", "22222234", "22222234", "22222234", "22222234"],
    "L":  ["43222222", "43222222", "43222222", "43222222", "43222222", "43222222", "43222222", "43222222"],
    "R":  ["22222234", "22222234", "22222234", "22222234", "22222234", "22222234", "22222234", "22222234"],
    "BL": ["43222222", "43222222", "43222222", "43222222", "43222222", "43222222", "43333333", "44444444"],
    "B":  ["22222222", "22222222", "22222222", "22222222", "22222222", "22222222", "33333333", "44444444"],
    "BR": ["22222234", "22222234", "22222234", "22222234", "22222234", "22222234", "33333344", "44444444"],
}
FRAME_ORDER = ["TL", "T", "TR", "L", "R", "BL", "B", "BR"]

# ---------------------------------------------------------- the colours
# The seven shapes, each a light face, a body and a shade. Named for
# their letters, in the order the game deals them.
PIECES = [
    ("I", 0x8FF, 0x0CC, 0x066),
    ("O", 0xFE8, 0xEC0, 0x850),
    ("T", 0xE9F, 0xA3D, 0x527),
    ("S", 0xAF8, 0x5C2, 0x271),
    ("Z", 0xF98, 0xD33, 0x711),
    ("J", 0x9BF, 0x36C, 0x136),
    ("L", 0xFC8, 0xE80, 0x740),
]


def hsv(h, s, v):
    """A colour on the machine's $0RGB from hue 0-359, and 0-1 either way."""
    import colorsys
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, s, v)
    return (round(r * 15) << 8) | (round(g * 15) << 4) | round(b * 15)


def surround(level):
    """A level's sixteen: the ground, the weave, the frame's four and the
    headings. Twenty hues around the wheel, each level a step of 63
    degrees so that no two levels running look alike."""
    h = 20 + level * 63
    return [
        hsv(h, 0.85, 0.10),            # 0 the ground
        hsv(h, 0.70, 0.22),            # 1 the weave
        hsv(h + 12, 0.85, 0.30),       # 2 the frame's dark
        hsv(h + 12, 0.70, 0.55),       # 3 its body
        hsv(h + 12, 0.35, 0.85),       # 4 its light
        hsv(h + 12, 0.10, 1.00),       # 5 its shine
        0xFFF,                         # 6 a figure
        hsv(h + 180, 0.30, 0.95),      # 7 a heading, the hue's opposite
        hsv(h + 180, 0.60, 0.60),      # 8 a heading, dimmed
        hsv(h, 0.55, 0.42),            # 9 a panel's face
        hsv(h, 0.85, 0.16),            # 10 a panel's ground
        0x000, 0x000, 0x000, 0x000, 0x000,
    ]


# --------------------------------------------------------------- the tune
# Mine, on three voices: a minor riff over a walking bass, four bars round
# and round. Notes are name + octave, `-` a rest, and each step is an
# eighth at 140 beats a minute -- 13 frames of the machine's 60.
STEP = 13
LEAD = ("A4 C5 E5 C5 D5 F5 E5 D5 C5 E5 A5 E5 D5 C5 B4 A4 "
        "A4 C5 E5 G5 F5 E5 D5 C5 B4 D5 G5 D5 C5 B4 A4 -")
BASS = ("A2 -  A2 -  D3 -  D3 -  C3 -  C3 -  E2 -  E2 -  "
        "A2 -  A2 -  F2 -  F2 -  G2 -  G2 -  E2 -  E2 -")
HARM = ("-  E4 -  A4 -  A4 -  F4 -  G4 -  C5 -  G4 -  E4 "
        "-  E4 -  C5 -  C5 -  A4 -  B4 -  G4 -  G4 -  E4")
VOLS = (10, 12, 6)                     # lead, bass, harmony


def inc(note):
    """A note name to the voice's phase increment: its pitch over the
    engine's 0.4993 Hz a step."""
    if note == "-":
        return 0
    step = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[note[0]]
    midi = 12 * (int(note[-1]) + 1) + step
    return round(440.0 * 2 ** ((midi - 69) / 12.0) / 0.4993)


def tune_stream():
    """The stream, wait byte first, as the player reads it."""
    voices = [LEAD.split(), BASS.split(), HARM.split()]
    n = len(voices[0])
    assert all(len(v) == n for v in voices), [len(v) for v in voices]
    out, last = [0], [None, None, None]
    for i in range(n):
        mask, data = 0, []
        for c, v in enumerate(voices):
            if v[i] != last[c]:
                mask |= 1 << c
                f = inc(v[i])
                data += [f & 255, f >> 8, 0 if f == 0 else VOLS[c]]
                last[c] = v[i]
        out += [mask] + data + [STEP - 1]
    out += [0x80]
    return out, n * STEP


def tiles():
    """Every tile as (name, 32 bytes at 4 bpp), in the order the game
    numbers them: the weave, the block, the ghost, the frame's eight, a
    solid, then the font."""
    def pack(rows):
        out = []
        for r in rows:
            for i in range(0, 8, 2):
                out.append((int(r[i]) << 4) | int(r[i + 1]))
        return out
    out = [("BG", pack(WEAVE)), ("BLOCK", pack(BLOCK)), ("GHOST", pack(GHOST))]
    out += [("FR_" + k, pack(FRAME[k])) for k in FRAME_ORDER]
    out.append(("SOLID", pack(["33333333"] * 8)))
    _, glyphs = mkmscool.font(mkmscool.load(mkmscool.FONTSHEET))
    order = mkmscool.FONT
    out += [("FONT", glyphs[order[0]])] + [("", glyphs[ch]) for ch in order[1:]]
    return out, order


def act(ts, order, stream, frames):
    lines = [
        "; COOLTRIS's art, written by tools/mkcooltris.py -- run it, do not",
        "; edit this. A tile is 8 x 8 at 4 bpp, high nibble the left pixel.",
        ";",
        "; The block's colour is its bank: 0 the outline, 1 the light face,",
        "; 2 the body, 3 the shade, so the seven shapes are seven banks of",
        "; four. The surround's bank is written again at every level.",
        "",
    ]
    n = 0
    for name, _ in ts:
        if name:
            lines.append("CONST T_%s = %d" % (name, n))
        n += 1
    lines.append("CONST N_FONT = %d" % len(order))
    lines.append("CONST N_TILES = %d" % len(ts))
    lines.append('; tile T_FONT + i is character i of this')
    lines.append('BYTE ARRAY fontmap = "%s"' % order)
    lines.append("BYTE ARRAY cool_tiles(%d) = [" % (32 * len(ts)))
    for _, b in ts:
        lines.append("  " + " ".join(str(x) for x in b))
    lines.append("]")
    lines.append("")
    lines.append("; the seven shapes' banks, four colours each: I O T S Z J L")
    lines.append("CARD ARRAY piece_pal(%d) = [" % (7 * 4))
    for name, light, body, shade in PIECES:
        lines.append("  $000 $%03X $%03X $%03X   ; %s" % (light, body, shade, name))
    lines.append("]")
    lines.append("")
    lines.append("; the surround, sixteen a level, twenty levels")
    lines.append("CARD ARRAY lvl_pal(%d) = [" % (20 * 16))
    for lv in range(20):
        lines.append("  " + " ".join("$%03X" % c for c in surround(lv)))
    lines.append("]")
    lines.append("")
    lines.append("; the tune: %d steps, %d frames round, on voices 0-2" % (len(LEAD.split()), frames))
    lines.append("CONST TUNE_FRAMES = %d" % frames)
    lines.append("BYTE ARRAY tune_data(%d) = [" % len(stream))
    for i in range(0, len(stream), 24):
        lines.append("  " + " ".join(str(x) for x in stream[i:i + 24]))
    lines.append("]")
    return "\n".join(lines) + "\n"


def preview(ts, order):
    """The tiles at four times over, then the twenty levels' surrounds."""
    from PIL import Image
    im = Image.new("RGB", (8 * 36 + 8, 36 * 3 + 20 * 10 + 16), (24, 24, 24))

    def rgb(v):
        return (((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17)

    def draw(bytes_, pal, ox, oy, scale=4):
        for y in range(8):
            for x in range(8):
                b = bytes_[y * 4 + x // 2]
                ix = (b >> 4) if x % 2 == 0 else (b & 15)
                c = rgb(pal[ix]) if ix < len(pal) else (0, 0, 0)
                for dy in range(scale):
                    for dx in range(scale):
                        im.putpixel((ox + x * scale + dx, oy + y * scale + dy), c)
    sur = surround(0)
    for i, (name, b) in enumerate(ts[:11]):
        draw(b, sur, 8 + (i % 8) * 36, 8 + (i // 8) * 36)
    for i, (_, light, body, shade) in enumerate(PIECES):
        draw(ts[1][1], [0x000, light, body, shade], 8 + i * 36, 8 + 2 * 36)
    for lv in range(20):
        for i, c in enumerate(surround(lv)[:11]):
            for y in range(8):
                for x in range(8):
                    im.putpixel((8 + i * 10 + x, 36 * 3 + 8 + lv * 10 + y), rgb(c))
    im.save(PREVIEW)


def main():
    ts, order = tiles()
    stream, frames = tune_stream()
    text = act(ts, order, stream, frames)
    if "--check" in sys.argv:
        have = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if have != text:
            print("  %s is stale: run python tools/mkcooltris.py" % os.path.relpath(OUT, ROOT))
            return 1
        print("ok -- the art file is current")
        return 0
    if not os.path.isdir(ART):
        os.makedirs(ART)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(text)
    preview(ts, order)
    print("  %d tiles (%d of them glyphs), 7 piece banks, 20 level surrounds" % (len(ts), len(order)))
    print("  the tune: %d steps, %d frames round, %d bytes" % (len(LEAD.split()), frames, len(stream)))
    print("  wrote %s and %s" % (os.path.relpath(OUT, ROOT), os.path.relpath(PREVIEW, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
