#!/usr/bin/env python3
"""Build the demo disc: every `demos/*.bas` onto drive 13.

    python tools/mkdemos.py [--img PATH] [--png NAME]

**The machine is booted, not poked.** `BOOT.BIN` goes on drive 0 and the
ROM autoboots it, which is `poe emu` without a window -- because the boot
stub is what uploads the fonts into VRAM and a text demo drawn on a
machine that never booted is a blue screen with nothing on it. That is
not a hypothetical: the first version of this script poked the image in
and jumped to `main`, and the first text demo rendered blank.

**The programs are typed at the machine, not written by this script.** A
program on disc is tokenised, and the only thing that knows the token
table is `sw/token.asm`; a host-side tokeniser would be a second
implementation of it and would drift the first time a keyword was added.
So the sources in `demos/` are the truth and the disc is derived.

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
import cool8rsvm as vm                                   # noqa: E402
import memmap                                            # noqa: E402
import mkboot                                            # noqa: E402
import test_basic as B                                   # noqa: E402

DEMOS = os.path.join(ROOT, "demos")
DRIVE = disk.DEMO_VOL     # the layout is cool8disk's, not written twice


def sources():
    return sorted(f for f in os.listdir(DEMOS) if f.endswith(".bas"))


def discname(f):
    return os.path.splitext(f)[0].upper()[:8]


def volume(imgpath, code):
    """Drive 0 bootable, drive 13 the demo disc, the rest the user's."""
    # **Write what `build` returned, do not add the BOOT.BIN lying in the
    # build directory.** `mkboot.build` returns the bytes and writes no
    # file; only tools/flash.py writes BOOT.BIN. Adding that path instead
    # boots whatever the last `poe disk` left there, so a source change
    # is typed at hours-old firmware and the machine looks buggy rather
    # than stale -- which is the trap flash.py names in its own comment,
    # and it cost a session here before this line existed.
    boot = mkboot.build(code, dest=memmap.ORG, build_dir=H.BUILD)
    bootpath = os.path.join(H.BUILD, "BOOT.BIN")
    with open(bootpath, "wb") as fh:
        fh.write(boot)
    disk.make_image(imgpath, bootbin=bootpath)   # the layout is shared
    return len(boot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default=os.path.join(H.BUILD, "demos.img"))
    ap.add_argument("--png", metavar="NAME", nargs="?", const="",
                    help="run this demo (default the first) and shoot it")
    args = ap.parse_args()

    code, syms = B.build()
    n = volume(args.img, code)
    print("  16 volumes; drive 0 bootable (BOOT.BIN {:,}), drive {} is "
          "DEMOS".format(n, DRIVE))

    m = vm.boot(flash_path=args.img, render=True)
    for _ in range(90):
        m.run_frame()
    H.settle(m, syms)
    H.key(m, syms, "DRIVE %d\r" % DRIVE)

    for f in sources():
        H.key(m, syms, "NEW\r")
        for line in io.open(os.path.join(DEMOS, f),
                            encoding="utf-8").read().splitlines():
            if line.strip():
                H.key(m, syms, line + "\r")
        H.key(m, syms, 'SAVE "%s"\r' % discname(f))
        print("  typed and saved %-16s as %s" % (f, discname(f)))
    m.flash.flush()

    v = disk.Volume(disk.Image(args.img), DRIVE)
    print("  drive %d holds: %s"
          % (DRIVE, ", ".join(disk.show_name(e["name"]) for e in v.files())))

    # **Every demo gets shot, not just the first.** A picture is the
    # only review a demo really gets, and one that is never rendered is
    # one nobody looks at until a user does.
    for want in ([args.png] if args.png else
                 [discname(f) for f in sources()]):
        # **Stop whatever is still running.** A demo ends in `GOTO` or
        # `LOOP` and never comes back, so the machine is not idle and
        # `H.key` would wait for a prompt that is never coming. The
        # break key is what a person would press.
        m.press_break()
        m.run(cycles=20_000_000)
        H.settle(m, syms)
        H.key(m, syms, "MODE 0\r")      # back to text to be typed at
        H.key(m, syms, "NEW\r")
        H.key(m, syms, 'LOAD "%s"\r' % want)
        # **`H.key` settles after every keystroke, and a demo does not
        # settle** -- it ends in `GOTO` or `LOOP`, so the Return that
        # starts it never returns to the prompt. Type RUN, then press
        # Return without waiting for idle and give it a fixed slice.
        H.key(m, syms, "RUN")
        m.key(["\r"])
        m.run(cycles=900_000_000)   # bench.bas runs for ~50 s of
        #   machine time before it has a report to show
        m.run_frame(2)
        import test_video as TV
        rgb = bytearray()
        for p in m.fb():
            rgb += bytes((((p >> 8) & 15) * 17, ((p >> 4) & 15) * 17,
                          (p & 15) * 17))
        out = os.path.join(ROOT, "docs", "img",
                           "demo-%s.png" % want.lower())
        TV.write_png(out, 640, 480, rgb)
        print("  %d colours on screen -> %s"
              % (len(set(m.fb())), os.path.relpath(out, ROOT)))
    print("  %s" % os.path.relpath(args.img, ROOT))


if __name__ == "__main__":
    main()
