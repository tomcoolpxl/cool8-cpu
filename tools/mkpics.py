#!/usr/bin/env python3
"""The picture drive: photographs in mode 6, more than 256 colours of 4,096.

    python tools/mkpics.py --fetch     download the originals below that are missing, then convert
    python tools/mkpics.py             write assets/pictures/<name>.pic and .rpl from every original present
    python tools/mkpics.py --check     every picture is what this writes from its original
    python tools/mkpics.py --preview   and decode each to sim/build/pics/<name>.png, for the eye

demos/slides.act shows every `.PIC` on the picture drive
(`cool8disk.PICTURE_VOL`), and tools/mkdemos.py puts there the files
this has written, in the order `SOURCES` gives.

**A picture file is the hardware's own bytes**
([D103](../docs/01-decisions.md)): an eight-byte header, the 256
palette entries in the order and the form `PAL_DATA` takes them, then
the pixels in the order mode 6 lays them out in VRAM.

    +0       3   "PIC"
    +3       1   version   1: one palette; 2: it changes between rows
    +4       1   6         the VID_MODE preset the pixels are laid out for
    +5       1   border    the palette index VID_BORDER takes -- black
    +6       2   0         reserved
    +8     512   palette   256 entries, each 0000RRRR then GGGGBBBB; row 0's in version 2
    +520 61440   pixels    240 rows of 256, the top row first

61,960 bytes: 243 of a volume's 1,760 data pages.

**Version 2's palette changes between rows** ([D104](../docs/01-decisions.md)).
Row r's pixels are indices into row r's palette, which is row r-1's
with some entries rewritten, and NAME.RPL beside the picture lists them
in the order the viewer writes them:

    +0       3   "RPL"
    +3       1   1         the list's version
    +4       1   240       rows
    +5       1   HOT       slots a record opens with
    +6       1   FREE      the most slots a record's second part has
    +7       1   0         reserved
    +8    a record a row, r = 0..239:
            HOT slots (entry, 0000RRRR, GGGGBBBB) that row r changes,
              written in the blanking before it -- entries row r-1 used,
              so they cannot move while it is drawn; a slot not needed
              rewrites the border's black, which changes nothing
            a count, then that many slots row r+1 changes, written while
              row r is drawn -- entries row r does not use, so nothing on
              the screen moves when they do

**The quantiser is libimagequant, told the palette's depth.** The
palette is twelve bits. A quantiser that chooses in 24 and is rounded
afterwards has placed its colours for some other machine, and its
dithering was worked out against colours this screen cannot show.
`min_posterization = 4` makes it choose among the 4,096 the palette
holds -- libimagequant documents the setting for RGB444 displays.
Black is a fixed colour so the border, the 64 physical pixels either
side of mode 6's 512, is black whatever the picture. It sets row 0's
palette; the rows below are this file's planner, because no standard
tool plans a palette that changes by line for this machine's budget
(png2amiga's Amiga modes were the nearest, D104).

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
MODE = 6

# D104's budget, in palette entries a row, from the viewer's own clocks
# against the RTL's timing (04-system.md section 5.9): HOT must commit in
# the 70 clocks between VID_RASTER naming a row's first line and the
# palette read for its first picture pixel; FREE fits the rest of the
# row's two lines, 532 clocks, at 30 an entry.
HOT = 2
FREE = 14
LOOKAHEAD = 8                       # the rows below a change is chosen for
RPL_HEADER = 8

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


def rpl_path(name):
    return os.path.join(DIR, name.lower() + ".rpl")


# ------------------------------------------------------------ the format

def pack(pal, pixels, border, version=1):
    """A picture file from 256 palette entries as $0RGB -- row 0's, in
    version 2 -- 61,440 index bytes, and the index the border takes."""
    if len(pal) != 256 or len(pixels) != W * H or not 0 <= border < 256:
        raise ValueError("a picture is 256 entries, %d pixels and a border index" % (W * H))
    out = bytearray(b"PIC" + bytes((version, MODE, border, 0, 0)))
    for c in pal:
        out += bytes(((c >> 8) & 0x0F, c & 0xFF))
    out += bytes(pixels)
    return bytes(out)


def unpack(blob):
    """`(palette, pixels, border)` from a picture file of either version;
    in version 2 the palette is row 0's."""
    if len(blob) < SIZE or blob[:3] != b"PIC" or blob[3] not in (1, 2) or blob[4] != MODE:
        raise ValueError("not a mode-%d picture this knows" % MODE)
    pal = [(blob[HEADER + 2 * i] << 8) | blob[HEADER + 2 * i + 1] for i in range(256)]
    return pal, bytes(blob[HEADER + 512:SIZE]), blob[5]


def pack_rpl(changes, border):
    """NAME.RPL from `changes`, a `(hot, free)` pair of `[(entry, $0RGB)]`
    lists a row, each the entries that row's palette changes."""
    out = bytearray(b"RPL" + bytes((1, H, HOT, FREE, 0)))
    for r in range(H):
        hot = changes[r][0]
        if len(hot) > HOT or (r + 1 < H and len(changes[r + 1][1]) > FREE):
            raise ValueError("row %d changes more than the budget" % r)
        for e, c in hot + [(border, 0)] * (HOT - len(hot)):
            out += bytes((e, (c >> 8) & 0x0F, c & 0xFF))
        nxt = changes[r + 1][1] if r + 1 < H else []
        out.append(len(nxt))
        for e, c in nxt:
            out += bytes((e, (c >> 8) & 0x0F, c & 0xFF))
    return bytes(out)


def unpack_rpl(blob):
    """`changes` back from NAME.RPL, as `pack_rpl` takes them -- the
    spare slots included, since the viewer writes those too."""
    if blob[:3] != b"RPL" or blob[3] != 1:
        raise ValueError("not a version-1 change list")
    rows, hot_n = blob[4], blob[5]
    changes = [([], []) for _ in range(rows)]
    i = RPL_HEADER
    for r in range(rows):
        for _ in range(hot_n):
            changes[r][0].append((blob[i], blob[i + 1] << 8 | blob[i + 2]))
            i += 3
        n = blob[i]
        i += 1
        for _ in range(n):
            changes[r + 1][1].append((blob[i], blob[i + 1] << 8 | blob[i + 2]))
            i += 3
    return changes


def display(pal, pixels, changes=None):
    """What the screen shows: a (240, 256, 3) array of 8-bit RGB, each
    row through its own palette when there are `changes`."""
    import numpy as np
    p = np.array(pal, dtype=np.int64)
    idx = np.frombuffer(bytes(pixels), dtype=np.uint8).reshape(H, W)
    out = np.zeros((H, W, 3), dtype=np.uint8)
    for r in range(H):
        if changes:
            for e, c in changes[r][0] + changes[r][1]:
                p[e] = c
        row = p[idx[r]]
        out[r] = np.stack([(row >> 8) & 15, (row >> 4) & 15, row & 15], axis=1) * 17
    return out


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
    """`(palette, pixels, border)` for a picture of any size: 256
    different colours of the palette's 4,096 and every pixel's index.

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
    w, h = rgb.size
    raw = rgb.convert("RGBA").tobytes()
    fixed = [0]                        # black: the border's, whatever the picture
    for _ in range(16):
        attr = liq.Attr()
        attr.max_colors = 256
        attr.min_posterization = 4     # the palette's own depth: four bits a channel
        attr.speed = 1                 # the slowest search, the best palette
        img = attr.create_rgba(raw, w, h, 0)
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


def oklab(rgb):
    """sRGB in 0..1, shape (..., 3), to OKLab (Bjorn Ottosson's): a
    space where a distance is about how different two colours look."""
    import numpy as np
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    lms = lin @ np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                          [0.2119034982, 0.6806995451, 0.1073969566],
                          [0.0883024619, 0.2817188376, 0.6299787005]]).T
    return np.cbrt(lms) @ np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                                    [1.9779984951, -2.4285922050, 0.4505937099],
                                    [0.0259040371, 0.7827717662, -0.8086757660]]).T


_GRID = []


def grid():
    """The palette's 4,096 colours in OKLab, indexed by $0RGB."""
    import numpy as np
    if not _GRID:
        c = np.arange(4096)
        rgb = np.stack([(c >> 8) & 15, (c >> 4) & 15, c & 15], axis=1) / 15.0
        _GRID.append(oklab(rgb).astype(np.float32))
    return _GRID[0]


def choose(lab, bins, r, pal, pl, used_prev, border):
    """`(hot, free)`: the entries row r's palette changes from the row
    above's, each `(entry, $0RGB)`.

    Chosen for the LOOKAHEAD rows from r down, nearer ones counting more:
    the colours those rows are missing most -- the 4,096's, where their
    pixels fall and carry the most error -- into the entries they need
    least, which is what it would cost their pixels to fall back on their
    second-nearest entry. One at a time, while a change gains more than it
    costs: at most FREE into entries row r-1 did not use, at most HOT into
    entries it did. The border's black is never touched."""
    import numpy as np
    g = grid()
    band = lab[r:r + LOOKAHEAD].reshape(-1, 3)
    bb = bins[r:r + LOOKAHEAD].reshape(-1)
    w = np.repeat((0.8 ** np.arange(len(band) // W)).astype(np.float32), W)
    d = np.sqrt(((band[:, None, :] - pl[None, :, :]) ** 2).sum(axis=2))
    mass = np.bincount(bb, weights=w * d.min(axis=1), minlength=4096)
    mass[list(set(pal))] = 0
    cand = np.argsort(-mass, kind="stable")[:64]
    cand = cand[mass[cand] > 0]
    if not cand.size:
        return [], []
    dc = np.sqrt(((band[:, None, :] - g[cand][None, :, :]) ** 2).sum(axis=2))
    free_ok = np.array([e not in used_prev for e in range(256)])
    hot_ok = ~free_ok
    free_ok[border] = hot_ok[border] = False
    alive = np.ones(cand.size, dtype=bool)
    hot, free = [], []
    while len(hot) < HOT or len(free) < FREE:
        part = np.partition(d, 1, axis=1)
        d1, d2 = part[:, 0], part[:, 1]
        loss = np.bincount(d.argmin(axis=1), weights=w * (d2 - d1), minlength=256)
        gain = (w[:, None] * np.maximum(0.0, d1[:, None] - dc)).sum(axis=0)
        gain[~alive] = -1.0
        k = int(gain.argmax())
        ok = free_ok if len(free) < FREE else np.zeros(256, dtype=bool)
        if len(hot) < HOT:
            ok = ok | hot_ok
        if not ok.any():
            break
        e = int(np.where(ok, loss, np.inf).argmin())
        if gain[k] - loss[e] <= 1e-3:
            break
        (hot if hot_ok[e] else free).append((e, int(cand[k])))
        d[:, e] = dc[:, k]
        alive[k] = False
        free_ok[e] = hot_ok[e] = False
    return hot, free


def plan(rgb, pal0, border):
    """`(pixels, changes)`: a 256 x 240 picture through a palette that
    changes between rows, starting from `pal0`.

    Row by row down the picture: `choose` makes the row's palette out of
    the one above, then the row is dithered against it -- Floyd-Steinberg
    in OKLab, carrying its error into the row below, which is dithered
    against a palette a few entries different."""
    import numpy as np
    g = grid()
    src = np.asarray(rgb, dtype=np.uint8)
    lab = oklab(src / 255.0).astype(np.float32)
    lv = (src.astype(np.int64) * 15 + 127) // 255      # the nearest four-bit level
    bins = lv[..., 0] << 8 | lv[..., 1] << 4 | lv[..., 2]
    pal = list(pal0)
    pl = g[np.array(pal)].copy()
    pixels = bytearray(W * H)
    changes = []
    err = np.zeros((W + 2, 3), dtype=np.float32)
    used_prev = set()
    for r in range(H):
        hot, free = choose(lab, bins, r, pal, pl, used_prev, border) if r else ([], [])
        for e, c in hot + free:
            pal[e] = c
            pl[e] = g[c]
        changes.append((hot, free))
        nxt = np.zeros((W + 2, 3), dtype=np.float32)
        base = r * W
        for x in range(W):
            want = lab[r, x] + err[x + 1]
            i = int(((pl - want) ** 2).sum(axis=1).argmin())
            pixels[base + x] = i
            q = want - pl[i]
            err[x + 2] += q * (7 / 16)
            nxt[x] += q * (3 / 16)
            nxt[x + 1] += q * (5 / 16)
            nxt[x + 2] += q * (1 / 16)
        err = nxt
        used_prev = set(pixels[base:base + W])
    return pixels, changes


def fidelity(shown, rgb):
    """How far a picture as the screen shows it is from its original: the
    mean OKLab distance after a 3 x 3 box blur of both -- the blur standing
    for the eye, which averages dithering away. Lower is closer."""
    import numpy as np
    from PIL import Image, ImageFilter
    a = np.asarray(Image.fromarray(shown).filter(ImageFilter.BoxBlur(1)), dtype=np.float64) / 255
    b = np.asarray(rgb.filter(ImageFilter.BoxBlur(1)), dtype=np.float64) / 255
    return float(np.sqrt(((oklab(a) - oklab(b)) ** 2).sum(axis=2)).mean())


def convert(src):
    """`(picture, change list, report)` from an original: the version-2
    picture, its NAME.RPL, and a line saying what the screen will show
    against the single palette of version 1."""
    import numpy as np
    rgb = frame(src)
    pal0, _, border = quantise(rgb.crop((0, 0, W, 3 * LOOKAHEAD)))
    pixels, changes = plan(rgb, pal0, border)
    shown = display(pal0, pixels, changes)
    flat_pal, flat_pix, _ = quantise(rgb)
    flat = display(flat_pal, flat_pix)
    n = sum(len(h) + len(f) for h, f in changes)
    colours = len(np.unique(shown.reshape(-1, 3), axis=0))
    report = ("%4d colours on the screen, %4d changes, off by %.4f (one palette: %d colours, %.4f)"
              % (colours, n, fidelity(shown, rgb),
                 len(np.unique(flat.reshape(-1, 3), axis=0)), fidelity(flat, rgb)))
    return pack(pal0, pixels, border, version=2), pack_rpl(changes, border), report


# ----------------------------------------------------------- the files

def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def present():
    """`[(disc name, path)]` for every file this has written, in the
    order the viewer shows them -- a picture, then its change list --
    which is what tools/mkdemos.py puts on the picture drive."""
    out = []
    for name, *_ in SOURCES:
        if os.path.exists(pic_path(name)):
            out.append((name + ".PIC", pic_path(name)))
            if os.path.exists(rpl_path(name)):
                out.append((name + ".RPL", rpl_path(name)))
    return out


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
    for name, path, what in here:
        pic, rpl, report = convert(path)
        with open(pic_path(name), "wb") as fh:
            fh.write(pic)
        with open(rpl_path(name), "wb") as fh:
            fh.write(rpl)
        print("  %-12s %s + %s bytes  %s\n               <- %s"
              % (name + ".PIC", "{:,}".format(len(pic)), "{:,}".format(len(rpl)), report, what))
        if preview:
            show(name, pic, rpl)
    return 0


def check():
    here = originals()
    if not here:
        print("  no originals in %s, so nothing to hold a picture to"
              % os.path.relpath(DIR, ROOT))
        return 0
    stale = 0
    for name, path, what in here:
        pic, rpl, _ = convert(path)
        for out, want in ((pic_path(name), pic), (rpl_path(name), rpl)):
            have = open(out, "rb").read() if os.path.exists(out) else None
            if have != want:
                stale += 1
                print("  %s is not what %s makes: python tools/mkpics.py"
                      % (os.path.relpath(out, ROOT), os.path.basename(path)))
    print("  %d of %d files current" % (2 * len(here) - stale, 2 * len(here)))
    return 1 if stale else 0


def show(name, pic, rpl=None):
    """A picture decoded as the screen shows it, 256 x 240."""
    sys.path.insert(0, os.path.join(ROOT, "sim"))
    import test_video as TV
    pal, pixels, _ = unpack(pic)
    shown = display(pal, pixels, unpack_rpl(rpl) if rpl else None)
    os.makedirs(PREVIEW, exist_ok=True)
    path = os.path.join(PREVIEW, name.lower() + ".png")
    TV.write_png(path, W, H, shown.tobytes())
    print("    %s" % os.path.relpath(path, ROOT))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fetch", action="store_true",
                    help="download the originals that are missing, then convert")
    ap.add_argument("--check", action="store_true",
                    help="every picture is what this writes from its original")
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
