#!/usr/bin/env python3
"""The video engine.

    python sim/test_video.py

Two things, and the second is the point of the first:

  1. `cool8_vga_tb` runs a golden raster model beside `cool8_vga` and
     compares every output on every one of 840,000 pixel clocks, then
     checks the tallies docs/04-system.md section 5.1 states — 640x480
     visible in 800x525, 96 pixel clocks of hsync a line, two lines of
     vsync a frame.
  2. It renders one frame to `build/frame.png`, which is the only way to
     *look* at what the video engine produces until a VGA PMOD exists,
     and stays the reference the hardware has to match afterwards.

The PNG is written by hand out of zlib rather than by a library: it is
about twenty lines and it keeps the suite runnable on a checkout with
nothing installed.

Set OSS_CAD_SUITE to the toolchain root if the tools are not on PATH.
"""

import os
import argparse
import struct
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")

sys.path.insert(0, HERE)

sys.path.insert(0, os.path.join(ROOT, "tools"))

import cosim                                    # noqa: E402
import mkfont                                   # noqa: E402

VGA = os.path.join(ROOT, "rtl", "soc", "cool8_vga.v")
TEXT = [os.path.join(ROOT, "rtl", "soc", f)
        for f in ("cool8_vga.v", "cool8_rom.v", "cool8_text.v")]
TB = os.path.join(HERE, "tb", "cool8_vga_tb.v")
TEXT_TB = os.path.join(HERE, "tb", "cool8_text_tb.v")
BDF = os.path.join(ROOT, "assets", "font", "spleen-8x16.bdf")

H_VIS, V_VIS = 640, 480


def write_png(path, width, height, rgb):
    """A minimal truecolour PNG. rgb is a flat list of (r, g, b) bytes."""
    raw = bytearray()
    for row in range(height):
        raw.append(0)                            # filter type 0, none
        off = row * width * 3
        raw += rgb[off:off + width * 3]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                            8, 2, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        fh.write(chunk(b"IEND", b""))


def render(src, dst):
    """Turn the testbench's 12-bit pixel dump into a PNG."""
    with open(src) as fh:
        px = [int(line, 16) for line in fh if line.strip()]
    if len(px) != H_VIS * V_VIS:
        return None, (f"the frame holds {len(px)} pixels, "
                      f"not {H_VIS * V_VIS}")
    out = bytearray()
    for v in px:
        # 4 bits per channel, scaled to 8 by replication so $F is $FF.
        out += bytes((((v >> 8) & 0xF) * 17,
                      ((v >> 4) & 0xF) * 17,
                      (v & 0xF) * 17))
    write_png(dst, H_VIS, V_VIS, out)
    return len(px), None


DOCS_IMG = os.path.join(ROOT, "docs", "img")

# What README.md shows. These have to be committed for GitHub to render
# them, which makes them the one generated thing in the project that
# lives in the repo — so they are checked against what the suite
# actually produces rather than trusted.
PUBLISHED = {
    "frame.png": "raster-test-pattern.png",
    "text.png": "text-mode-0.png",
}


def check_published(refresh):
    out = []
    for built, shown in PUBLISHED.items():
        src = os.path.join(BUILD, built)
        dst = os.path.join(DOCS_IMG, shown)
        if not os.path.exists(src):
            continue
        new = open(src, "rb").read()
        old = open(dst, "rb").read() if os.path.exists(dst) else None
        if new == old:
            continue
        if refresh:
            os.makedirs(DOCS_IMG, exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(new)
            out.append(f"refreshed docs/img/{shown}")
        else:
            out.append(f"docs/img/{shown} is not what this run produced "
                       f"— rerun with --refresh")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="update the images README.md shows")
    args = ap.parse_args()

    os.makedirs(BUILD, exist_ok=True)
    ok = True

    vvp = cosim._build("cool8_vga_tb", TB, [VGA])
    r = subprocess.run([cosim._tool("vvp"), vvp, "+frame=frame.hex"],
                       cwd=BUILD, capture_output=True, text=True)
    out = r.stdout + r.stderr
    good = "\nPASS" in out
    print(f"  {'the raster, every pixel of two frames':<44} "
          f"{'ok' if good else 'FAIL'}")
    for line in out.splitlines():
        if line.startswith("FAIL") or "checks" in line or "visible in" in line:
            print("    " + line)
    ok &= good

    png = os.path.join(BUILD, "frame.png")
    n, err = render(os.path.join(BUILD, "frame.hex"), png)
    if err:
        print(f"  {'a frame, rendered':<44} FAIL")
        print("    " + err)
        ok = False
    else:
        print(f"  {'a frame, rendered':<44} ok")
        print(f"    {n} pixels -> {os.path.relpath(png, ROOT)}")

    # ---- the font, and a screen of text through it
    img, present, fb = mkfont.build(BDF)
    with open(os.path.join(BUILD, "font.hex"), "w") as fh:
        for b in img:
            fh.write("%02x\n" % b)
    blank = sum(1 for i in range(256) if not any(img[i * 16:(i + 1) * 16]))
    print(f"  {'the font':<44} ok")
    print(f"    {present}/256 CP437 glyphs from a {fb[0]}x{fb[1]} box, "
          f"{blank} blank")

    vvp = cosim._build("cool8_text_tb", TEXT_TB, TEXT)
    r = subprocess.run([cosim._tool("vvp"), vvp, "+frame=text.hex"],
                       cwd=BUILD, capture_output=True, text=True)
    out = r.stdout + r.stderr
    good = "\nPASS" in out
    print(f"  {'text mode 0, through the raster':<44} "
          f"{'ok' if good else 'FAIL'}")
    for line in out.splitlines():
        if line.startswith("FAIL") or "captured" in line:
            print("    " + line)
    ok &= good

    if good:
        png = os.path.join(BUILD, "text.png")
        n, err = render(os.path.join(BUILD, "text.hex"), png)
        if err:
            print(f"  {'a screen, rendered':<44} FAIL")
            print("    " + err)
            ok = False
        else:
            print(f"  {'a screen, rendered':<44} ok")
            print(f"    {n} pixels -> {os.path.relpath(png, ROOT)}")

    notes = check_published(args.refresh)
    stale = any("not what this run" in n for n in notes)
    print(f"  {'the images README.md shows':<44} "
          f"{'FAIL' if stale else 'ok'}")
    for n in notes:
        print("    " + n)
    ok &= not stale

    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
