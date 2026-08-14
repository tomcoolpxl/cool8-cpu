#!/usr/bin/env python3
"""Build the demo disc: every `demos/*.bas` onto drive 13.

    python tools/mkdemos.py [--img PATH] [--png]

**The programs are typed at the machine, not written by this script.**
A BASIC program on disc is *tokenised*, and the only thing that knows the
token table is the machine's own tokeniser -- so this boots the VM, types
each source in, and lets `SAVE` write it. A host-side tokeniser would be
a second implementation of `sw/token.asm` and would drift from it, which
is the trap `AGENTS.md` names first.

That also means the sources in `demos/` are the truth and the disc is
derived, so a demo is reviewed as text and rebuilt rather than edited as
a binary.

Drive 13 is the demo disc; 14 and 15 are the system discs. See
[docs/14-demos.md](../docs/14-demos.md).
"""

import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))
sys.path.insert(0, HERE)

import harness as H                                      # noqa: E402
import cool8disk as disk                                 # noqa: E402
import test_basic as B                                   # noqa: E402

DEMOS = os.path.join(ROOT, "demos")
DRIVE = 13
LABEL = "DEMOS"


def sources():
    return sorted(f for f in os.listdir(DEMOS) if f.endswith(".bas"))


def discname(f):
    """`10print.bas` -> `10PRINT`, which SAVE turns into 10PRINT.BAS."""
    return os.path.splitext(f)[0].upper()[:8]


def build(imgpath, png=False):
    if os.path.exists(imgpath):
        os.remove(imgpath)
    img = disk.Image(imgpath, create=True)
    for d in range(16):
        disk.Volume(img, d).format(LABEL if d == DRIVE else "COOL8")
    img.save()

    code, syms = B.build()
    M = B.Machine(code, syms, flash=imgpath, render=png)
    M.settle()
    M.cmd("CLS")
    M.cmd("DRIVE %d" % DRIVE)

    for f in sources():
        M.cmd("NEW")
        for line in io.open(os.path.join(DEMOS, f),
                            encoding="utf-8").read().splitlines():
            if line.strip():
                M.cmd(line)
        M.cmd('SAVE "%s"' % discname(f))
        print("  typed and saved %-16s as %s" % (f, discname(f)))
    M.m.flash.flush()

    v = disk.Volume(disk.Image(imgpath), DRIVE)
    on = [disk.show_name(e["name"]) for e in v.files()]
    print("  drive %d holds: %s" % (DRIVE, ", ".join(on)))
    return M, syms


def shoot(M, name):
    """One frame of the running program, as a PNG."""
    import test_video as TV
    M.m.run(cycles=250_000_000)
    M.m.run_frame(2)
    rgb = bytearray()
    for v in M.m.fb():
        rgb += bytes((((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17,
                      (v & 15) * 17))
    out = os.path.join(ROOT, "docs", "img", "demo-%s.png" % name)
    TV.write_png(out, 640, 480, rgb)
    print("  wrote", os.path.relpath(out, ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default=os.path.join(H.BUILD, "demos.img"))
    ap.add_argument("--png", action="store_true",
                    help="run the first demo and shoot a frame")
    args = ap.parse_args()

    M, _ = build(args.img, png=args.png)
    if args.png and sources():
        first = discname(sources()[0])
        M.cmd("NEW")
        M.cmd('LOAD "%s"' % first)
        M.m.type("RUN" + chr(13))
        shoot(M, first.lower())
    print("  %s" % os.path.relpath(args.img, ROOT))


if __name__ == "__main__":
    main()
