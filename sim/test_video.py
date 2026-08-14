#!/usr/bin/env python3
"""The video engine.

    python sim/test_video.py

Three things, and the third is the point of the first two:

  1. `cool8_vga_tb` runs a golden raster model beside `cool8_vga` and
     compares every output on every one of 840,000 pixel clocks, then
     checks the tallies docs/04-system.md section 5.1 states — 640x480
     visible in 800x525, 96 pixel clocks of hsync a line, two lines of
     vsync a frame.
  2. `cool8_video_tb` runs the whole subsystem through every mode and
     compares every visible pixel against arithmetic taken from section
     5 rather than from the RTL. Thirteen frames, four million checks.
  3. It renders frames to `build/*.png`, which is the only way to *look*
     at what the video engine produces until a VGA PMOD exists, and
     stays the reference the hardware has to match afterwards.

The PNG is written by hand out of zlib rather than by a library: it is
about twenty lines and it keeps the suite runnable on a checkout with
nothing installed.

Set OSS_CAD_SUITE to the toolchain root if the tools are not on PATH.
"""

import os
import argparse
import re
import struct
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")

sys.path.insert(0, HERE)

sys.path.insert(0, os.path.join(ROOT, "tools"))

import toolchain as T                                    # noqa: E402
import mkfont                                   # noqa: E402

VGA = os.path.join(ROOT, "rtl", "soc", "cool8_vga.v")
VIDEO = [os.path.join(ROOT, "rtl", "soc", f)
         for f in ("cool8_video.v", "cool8_vga.v", "cool8_vregs.v",
                   "cool8_pal.v", "cool8_fetch.v", "cool8_pixel.v",
                   "cool8_rom.v", "cool8_vram.v", "cool8_vport.v",
                   "cool8_pixport.v", "cool8_sprite.v")]
TB = os.path.join(HERE, "tb", "cool8_vga_tb.v")
VIDEO_TB = os.path.join(HERE, "tb", "cool8_video_tb.v")
BDF = os.path.join(ROOT, "assets", "font", "spleen-8x16.bdf")

H_VIS, V_VIS = 640, 480

# cool8_video_tb's phases, and the three that also dump a frame.
#
# Phases 3 and 13 are dumped for sim/test_vm.py rather than for a
# picture. 13 is the only frame with sprites in it; **3 is the only one
# with a cursor**, and without it the emulator's cursor path was the one
# part of the video model nothing checked -- which is exactly where
# [D81] found both models wrong in the same way, agreeing with each
# other and with nothing else. A gate cannot catch a shared assumption
# about a thing it never renders.
N_PHASES = 16
FRAME_DUMPS = {0: "text.hex", 3: "cursor.hex", 11: "tiles.hex",
               13: "sprites.hex"}


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

    vvp = T.build("cool8_vga_tb", TB, [VGA])
    r = subprocess.run([T.tool("vvp"), vvp, "+frame=frame.hex"],
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
    import palette
    palette.stage(BUILD)

    with open(os.path.join(BUILD, "font.hex"), "w") as fh:
        for b in img:
            fh.write("%02x\n" % b)
    blank = sum(1 for i in range(256) if not any(img[i * 16:(i + 1) * 16]))
    print(f"  {'the font':<44} ok")
    print(f"    {present}/256 CP437 glyphs from a {fb[0]}x{fb[1]} box, "
          f"{blank} blank")

    vvp = T.build("cool8_video_tb", VIDEO_TB,
                       VIDEO + [T.cells()], gen="2012")

    # One process per phase, all at once.
    #
    # The phases are independent pictures and each costs three frames of
    # raster — two to settle a mode change and one to compare. Run
    # end to end that is twenty million pixel-clock edges in an
    # interpreted simulator and it took the best part of half an hour.
    # `+from`/`+to` now skip the *frames* of a phase nobody is looking at,
    # not just the comparison, so a single phase costs one phase.
    #
    # The set-up still runs for every phase in every process, because
    # later phases build on registers and memory earlier ones wrote. It is
    # a few thousand register writes and it does not show.
    #
    # Phases 0 and 11 also dump their frame, which is where text.png and
    # tiles.png come from — so the pictures cost nothing extra now, where
    # tiles.png used to need a second full sweep of all sixteen.
    jobs = []
    for ph in range(N_PHASES):
        argv = [T.tool("vvp"), vvp, f"+from={ph}", f"+to={ph}"]
        if ph in FRAME_DUMPS:
            argv += [f"+frame={FRAME_DUMPS[ph]}", f"+which={ph}"]
        jobs.append((ph, subprocess.Popen(argv, cwd=BUILD,
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT,
                                          text=True)))

    good, lines, checks, fails = True, [], 0, 0
    for ph, proc in jobs:
        out = proc.communicate()[0]
        if "\nPASS" not in out:
            good = False
        for line in out.splitlines():
            line = line.rstrip()
            # Each process prints its own running total; sum them rather
            # than printing sixteen of them.
            tot = re.match(r"\s+(\d+) checks, (\d+) failures", line)
            if tot:
                checks += int(tot.group(1))
                fails += int(tot.group(2))
            elif line.startswith("FAIL"):
                lines.append(line)
            elif "pixels," in line:
                lines.append(line)

    print(f"  {'every mode, against a model of section 5':<44} "
          f"{'ok' if good else 'FAIL'}")
    for line in lines:
        print("    " + line)
    print(f"      {checks} checks, {fails} failures")
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

    # The tile engine, as a picture. Not published: the tile data this
    # testbench uses is every attribute combination against patterns
    # chosen to be asymmetric, which is what a flip taken from the wrong
    # bit shows up in and is not what anyone would call a screen.
    #
    # Phase 11 dumped it during the sweep above. This used to be a second
    # run of all sixteen phases to reach one of them.
    if good:
        png = os.path.join(BUILD, "tiles.png")
        n, err = render(os.path.join(BUILD, "tiles.hex"), png)
        if not err:
            print(f"  {'the tile engine, rendered':<44} ok")
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
