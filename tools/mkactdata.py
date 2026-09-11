#!/usr/bin/env python3
"""The demos' tables, from their BASIC `DATA` into their CoolAction! ports.

    python tools/mkactdata.py            rewrite every generated block
    python tools/mkactdata.py --check    fail if any is stale
    python tools/mkactdata.py plasma     one demo

**Two demos, one table, and the numbers are copied by machine.** A
CoolAction! port of a BASIC demo has no `READ`, so what the BASIC
carries as `DATA` -- a sine table, a palette, a tune -- is an
initialised array in the `.act`. Typed twice, thousands of numbers
would be wrong in one place and the picture subtly bent in a way only
the framebuffer comparison in `sim/test_action.py` could see; so each
port has a marked block that this script fills from the BASIC's own
`DATA` lines, and `poe check` fails if the block does not match what
the BASIC says today. The port's *logic* is hand-written around it.

The BASIC's line numbers are the map: each block below names the range
of `DATA` lines it reads and how to lay the values out -- flat, every
k-th value from an offset (a table of triples split into three
arrays), or consecutive pairs joined into one word, which is what a
palette written high byte then low byte to `PAL_DATA` is.
"""

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMOS = os.path.join(ROOT, "demos")
BEGIN = "; ---- generated from demos/%s.bas by tools/mkactdata.py: do not edit ----"
END = "; ---- end of the generated block ----"


def data(bas, lo, hi):
    """Every DATA value on lines lo..hi of the BASIC, in order."""
    out = []
    for line in io.open(bas, encoding="utf-8"):
        m = re.match(r"(\d+)\s+DATA\s+(.*)$", line.strip())
        if m and lo <= int(m.group(1)) <= hi:
            out += [int(v) for v in m.group(2).split(",")]
    return out


def stride(k, i):
    return lambda v: v[i::k]


def pairs(v):
    assert len(v) % 2 == 0
    return [(v[j] << 8) | v[j + 1] for j in range(0, len(v), 2)]


def flat(v):
    return v


def rows(vals, per):
    fmt = ("$%03X" if any(v > 255 for v in vals) and all(v >= 0 for v in vals)
           else "%d")
    return "\n".join("  " + " ".join(fmt % v for v in vals[i:i + per])
                     for i in range(0, len(vals), per))


# (act name, type, first DATA line, last DATA line, layout, expected
#  count or None, one line on what it is). COBRA is not here: its
# CoolAction! program left the BASIC's frames behind (D105), and its
# model comes from tools/mk3d.py, which writes both.
BLOCKS = {
    "plasma": [
        ("ax", "BYTE", 200, 299, flat, 256, "the x interference table, two sine voices"),
        ("gy", "BYTE", 300, 399, flat, 240, "the y one; a pixel is ax(x) + gy(y), 1..46"),
        ("pal", "CARD", 400, 499, pairs, 47, "the 47-entry cyclic rainbow, $0RGB"),
    ],
    "wave": [
        ("sq", "BYTE", 200, 299, flat, 181, "a quarter sine, rows 0..239; mirrored three ways at start"),
        ("pal", "CARD", 300, 399, flat, 253, "entries 1..253: one turn of the hue circle, $0RGB, a word each"),
    ],
    "synth": [
        ("zt", "CARD", 200, 239, flat, 104, "pitch increments: the c64-synth's SID arithmetic, precomputed"),
        ("pal", "CARD", 240, 259, flat, 16, "the Commodore 64 palette, $0RGB"),
    ],
    "intro": [
        ("zt", "CARD", 200, 239, flat, 78, "pitch increments, SYNTH's"),
        ("wob", "BYTE", 240, 259, flat, 64, "the bob: 64 of sine for VID_SCY"),
        ("trk", "BYTE", 260, 299, flat, 96, "three tracks of 32 steps: lead, arpeggio, bass"),
        ("msg1", "BYTE", 300, 309, flat, 40, "the banner, row 8"),
        ("atr1", "BYTE", 310, 319, flat, 40, "its attributes, a static rainbow"),
        ("msg2", "BYTE", 320, 329, flat, 40, "the banner, row 20"),
    ],
    "maze": [
        ("pal", "CARD", 160, 199, pairs, 16, "the Commodore 64 palette, $0RGB"),
        ("tile", "BYTE", 290, 329, flat, 32, "C64 screen code 77 at 4 bpp: paper 6, ink 14"),
    ],
}


def block(demo):
    bas = os.path.join(DEMOS, demo + ".bas")
    o = [BEGIN % demo]
    consts = []
    for name, ctype, lo, hi, lay, n, what in BLOCKS[demo]:
        vals = lay(data(bas, lo, hi))
        if n is not None:
            assert len(vals) == n, (demo, name, len(vals), n)
        if ctype == "BYTE":
            assert all(0 <= v <= 255 for v in vals), (demo, name)
        if what:
            o.append("; " + what)
        o.append("%s ARRAY %s(%d) = [" % (ctype, name, len(vals)))
        o.append(rows(vals, 24 if ctype == "BYTE" else 12) + "]")
    o += consts
    o.append(END)
    return "\n".join(o) + "\n"


def splice(text, demo, new):
    a = text.index(BEGIN % demo)
    b = text.index(END, a) + len(END) + 1
    return text[:a] + new + text[b:]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    bad = 0
    for demo in (args or sorted(BLOCKS)):
        act = os.path.join(DEMOS, demo + ".act")
        if not os.path.exists(act):
            print("  demos/%s.act does not exist yet" % demo)
            bad += 1
            continue
        have = io.open(act, encoding="utf-8").read()
        if (BEGIN % demo) not in have or END not in have:
            print("  demos/%s.act has no generated block to fill" % demo)
            bad += 1
            continue
        want = splice(have, demo, block(demo))
        if check:
            if want != have:
                print("  demos/%s.act's tables are stale against demos/%s.bas: "
                      "run python tools/mkactdata.py" % (demo, demo))
                bad += 1
        elif want != have:
            io.open(act, "w", encoding="utf-8", newline="\n").write(want)
            print("  wrote the tables into demos/%s.act" % demo)
    if check:
        n = len(args or BLOCKS)
        print("%s -- %d of %d ports carry their BASIC's DATA" % ("FAIL" if bad else "ok", n - bad, n))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
