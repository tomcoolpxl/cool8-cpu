#!/usr/bin/env python3
"""The picture drive: photographs as mode 6 shows them, 256 of 4,096 colours.

    python tools/mkpics.py --fetch     download the originals below that are missing, then convert
    python tools/mkpics.py             write assets/pictures/<name>.pic from every original present
    python tools/mkpics.py --check     every .pic is what this writes from its original
    python tools/mkpics.py --preview   and decode each to sim/build/pics/<name>.png, for the eye

demos/slides.act shows every `.PIC` on the picture drive
(`cool8disk.PICTURE_VOL`), and tools/mkdemos.py puts there the ones
this has written, in the order `SOURCES` gives.

**A picture file is the hardware's own bytes**
([D103](../docs/01-decisions.md)): an eight-byte header, the 256
palette entries in the order and the form `PAL_DATA` takes them, then
the pixels in the order mode 6 lays them out in VRAM. The viewer
streams it off the flash into the two ports and decodes nothing.

    +0       3   "PIC"
    +3       1   1         the format's version
    +4       1   6         the VID_MODE preset the pixels are laid out for
    +5       1   border    the palette index VID_BORDER takes -- black
    +6       2   0         reserved
    +8     512   palette   256 entries, each 0000RRRR then GGGGBBBB
    +520 61440   pixels    240 rows of 256, the top row first

61,960 bytes: 243 of a volume's 1,760 data pages, so a drive holds seven.

**The quantiser is libimagequant, told the palette's depth.** The
palette is twelve bits. A quantiser that chooses in 24 and is rounded
afterwards has placed its 256 colours for some other machine: two of
them can round onto one entry, and its dithering was worked out
against colours this screen cannot show. `min_posterization = 4`
makes it choose among the 4,096 the palette holds and dither against
exactly those -- libimagequant documents the setting for RGB444
displays, which is what this is. Black goes in as a fixed colour so
the border, the 64 physical pixels either side of mode 6's 512, is
black whatever the picture; it costs at most one of the 256.

**The frame is the screen's.** Mode 6 is 256 x 240 logical pixels,
each 2 x 2 on the 640 x 480 raster, so a pixel is square and the
picture is 16:15. An original is cropped to that about its centre and
scaled with Lanczos: a USC-SIPI square loses 16 of its 512 rows at the
top and 16 at the bottom, a Kodak 3:2 frame about a seventh of its
width at each side.

**The originals are not in the repository.** USC-SIPI says it does
not hold the copyright on most of its images and cannot say who does;
Kodak's set is reported released for unrestricted use. `--fetch` gets
them from the addresses below and refuses one whose hash has moved,
and `.gitignore` keeps them, and what this makes of them, out of git.
The Lena image is absent on purpose: its subject asked for it to be
retired, and USC-SIPI has removed it.
"""

import argparse
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "assets", "pictures")
PREVIEW = os.path.join(ROOT, "sim", "build", "pics")

W, H = 256, 240                     # mode 6's logical screen
HEADER = 8
SIZE = HEADER + 2 * 256 + W * H     # 61,960
VERSION, MODE = 1, 6

# The originals, in the order the viewer shows them: the name on the
# disc, the file, where it came from, its SHA-256, and what it is.
SOURCES = [
    ("MANDRILL", "4.2.03.tiff",
     "https://sipi.usc.edu/database/download.php?vol=misc&img=4.2.03",
     "3f590b52279fb59b81906f1e928ae713a5357b1afc1a2017a103adb563fb4494",
     "Mandrill, USC-SIPI 4.2.03, 512 x 512"),
    ("PEPPERS", "4.2.07.tiff",
     "https://sipi.usc.edu/database/download.php?vol=misc&img=4.2.07",
     "676c21edcc56b517ebd54764d6026d2befe7e15014ec3f0c9e6f2ce1d9ad74bf",
     "Peppers, USC-SIPI 4.2.07, 512 x 512"),
    ("PARROTS", "kodim23.png",
     "https://r0k.us/graphics/kodak/kodak/kodim23.png",
     "e3111a2fd4da24af15d6459ef9eacfe54106b38e27b4a21821b75c3f5d2d5baf",
     "Parrots, Kodak Photo CD kodim23, 768 x 512"),
    ("PAINTED", "kodim15.png",
     "https://r0k.us/graphics/kodak/kodak/kodim15.png",
     "7538cbb80cb9103606c48b806eae57d56c885c7f90b9b3be70a41160f9cbb683",
     "Painted face, Kodak Photo CD kodim15, 768 x 512"),
]


def pic_path(name):
    return os.path.join(DIR, name.lower() + ".pic")


# ------------------------------------------------------------ the format

def pack(pal, pixels, border):
    """A picture file from 256 palette entries as $0RGB, 61,440 index
    bytes, and the index the border takes."""
    if len(pal) != 256 or len(pixels) != W * H or not 0 <= border < 256:
        raise ValueError("a picture is 256 entries, %d pixels and a border index" % (W * H))
    out = bytearray(b"PIC" + bytes((VERSION, MODE, border, 0, 0)))
    for c in pal:
        out += bytes(((c >> 8) & 0x0F, c & 0xFF))
    out += bytes(pixels)
    return bytes(out)


def unpack(blob):
    """`(palette, pixels, border)` from a picture file."""
    if len(blob) < SIZE or blob[:3] != b"PIC" or blob[3] != VERSION or blob[4] != MODE:
        raise ValueError("not a version-%d mode-%d picture" % (VERSION, MODE))
    pal = [(blob[HEADER + 2 * i] << 8) | blob[HEADER + 2 * i + 1] for i in range(256)]
    return pal, bytes(blob[HEADER + 512:SIZE]), blob[5]


# ------------------------------------------------------- the conversion

def frame(path):
    """The original cropped to 16:15 about its centre, scaled to 256 x 240."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    if w * H > h * W:                  # wider than the screen: the sides go
        cw = h * W / H
        box = ((w - cw) / 2, 0, (w + cw) / 2, h)
    else:                              # taller: the top and bottom go
        ch = w * H / W
        box = (0, (h - ch) / 2, w, (h + ch) / 2)
    return im.resize((W, H), Image.Resampling.LANCZOS, box=box)


def rgb444(c):
    """A libimagequant colour as $0RGB. Posterised to four bits, a level
    is its nibble twice -- $00, $11 ... $FF -- so the low nibble carries
    nothing to lose."""
    for v in (c.r, c.g, c.b):
        if v % 17:
            raise SystemExit("libimagequant gave a level of %d, which is not four-bit" % v)
    return (c.r // 17) << 8 | (c.g // 17) << 4 | (c.b // 17)


def quantise(rgb):
    """`(palette, pixels, border)` for a 256 x 240 picture: 256 different
    colours of the palette's 4,096 and every pixel's index.

    **One pass is not enough, and the screen said so.** libimagequant
    places its colours at full precision and posterises them after, so
    two that settle close together round onto one 12-bit colour: the
    first cut's painted face had 256 entries and 163 different colours
    on the glass. So the distinct ones go back in as fixed colours and it
    runs again, placing only the slots the duplicates freed, until all
    256 differ or a pass frees none -- libimagequant's own search each
    time, never a second quantiser beside it."""
    try:
        import libimagequant as liq
    except ImportError:
        raise SystemExit('libimagequant is not installed: pip install -e ".[pictures]"')
    raw = rgb.convert("RGBA").tobytes()
    fixed = [0]                        # black: the border's, whatever the picture
    for _ in range(16):
        attr = liq.Attr()
        attr.max_colors = 256
        attr.min_posterization = 4     # the palette's own depth: four bits a channel
        attr.speed = 1                 # the slowest search, the best palette
        img = attr.create_rgba(raw, W, H, 0)
        for c in fixed:
            img.add_fixed_color(liq.Color(((c >> 8) & 15) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17, 255))
        res = img.quantize(attr)
        pal = [rgb444(c) for c in res.get_palette()]
        distinct = list(dict.fromkeys(pal))
        if len(distinct) == len(pal) or len(distinct) == len(fixed):
            break
        fixed = distinct
    res.dithering_level = 1.0
    pixels = res.remap_image(img)
    pal = [rgb444(c) for c in res.get_palette()]
    border = pal.index(0)
    pal += [0] * (256 - len(pal))
    return pal, pixels, border


def convert(src):
    """`(picture file, colours on the screen, border)` from an original --
    colours counted as the glass shows them, so two entries holding one
    colour count once. libimagequant's own quality figures are not
    reported: a first pass rates its palette before the rounding to four
    bits, and with fixed colours in play the figures of two runs do not
    compare, so they said less than the count does."""
    pal, pixels, border = quantise(frame(src))
    return pack(pal, pixels, border), len({pal[i] for i in set(pixels)}), border


# ----------------------------------------------------------- the files

def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def present():
    """`[(disc name, path)]` for every picture this has written, in the
    order the viewer shows them -- what tools/mkdemos.py puts on the
    picture drive."""
    return [(name + ".PIC", pic_path(name)) for name, *_ in SOURCES
            if os.path.exists(pic_path(name))]


def fetch():
    import urllib.request
    os.makedirs(DIR, exist_ok=True)
    for name, fn, url, want, what in SOURCES:
        path = os.path.join(DIR, fn)
        if os.path.exists(path) and sha256(path) == want:
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "cool8-mkpics"})
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
        got = hashlib.sha256(blob).hexdigest()
        if got != want:
            sys.exit("%s: %d bytes from %s hash to %s, not %s -- the original has moved"
                     % (fn, len(blob), url, got, want))
        with open(path, "wb") as fh:
            fh.write(blob)
        print("  fetched %-12s %9s bytes  %s" % (fn, "{:,}".format(len(blob)), what))


def originals():
    """The sources that are here, each held to its hash."""
    out = []
    for name, fn, url, want, what in SOURCES:
        path = os.path.join(DIR, fn)
        if not os.path.exists(path):
            continue
        if sha256(path) != want:
            sys.exit("%s is not the original %s names (SHA-256 differs)" % (path, url))
        out.append((name, path, what))
    return out


def write(preview):
    here = originals()
    if not here:
        print("  no originals in %s: python tools/mkpics.py --fetch"
              % os.path.relpath(DIR, ROOT))
        return 0
    import zlib
    for name, path, what in here:
        blob, used, border = convert(path)
        with open(pic_path(name), "wb") as fh:
            fh.write(blob)
        # what a decoder on the machine could at best buy back: deflate
        # at its hardest is the ceiling an LZ the machine could run
        # would stay under (D103)
        print("  %-12s %s bytes, %3d colours on the screen, border %3d, deflate saves %d%%  <- %s"
              % (name + ".PIC", "{:,}".format(len(blob)), used, border,
                 100 - 100 * len(zlib.compress(blob, 9)) // len(blob), what))
        if preview:
            show(name, blob)
    return 0


def check():
    here = originals()
    if not here:
        print("  no originals in %s, so nothing to hold a picture to"
              % os.path.relpath(DIR, ROOT))
        return 0
    stale = 0
    for name, path, what in here:
        out = pic_path(name)
        have = open(out, "rb").read() if os.path.exists(out) else None
        if have != convert(path)[0]:
            stale += 1
            print("  %s is not what %s makes: python tools/mkpics.py"
                  % (os.path.relpath(out, ROOT), os.path.basename(path)))
    print("  %d of %d pictures current" % (len(here) - stale, len(here)))
    return 1 if stale else 0


def show(name, blob):
    """A picture file decoded as the palette shows it, 256 x 240."""
    sys.path.insert(0, os.path.join(ROOT, "sim"))
    import test_video as TV
    pal, pixels, _ = unpack(blob)
    rgb = bytearray()
    for i in pixels:
        c = pal[i]
        rgb += bytes((((c >> 8) & 15) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17))
    os.makedirs(PREVIEW, exist_ok=True)
    path = os.path.join(PREVIEW, name.lower() + ".png")
    TV.write_png(path, W, H, rgb)
    print("    %s" % os.path.relpath(path, ROOT))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fetch", action="store_true",
                    help="download the originals that are missing, then convert")
    ap.add_argument("--check", action="store_true",
                    help="every .pic is what this writes from its original")
    ap.add_argument("--preview", action="store_true",
                    help="decode each picture to sim/build/pics/ as well")
    a = ap.parse_args()
    if a.check:
        return check()
    if a.fetch:
        fetch()
    return write(a.preview)


if __name__ == "__main__":
    sys.exit(main())
