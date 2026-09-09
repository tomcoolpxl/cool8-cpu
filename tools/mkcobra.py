#!/usr/bin/env python3
"""The Cobra's tables, from demos/cobra.bas into demos/cobra.act.

    python tools/mkcobra.py            rewrite the generated block
    python tools/mkcobra.py --check    fail if it is stale

**Two demos, one model.** `demos/cobra.bas` carries the Cobra Mk III as
`DATA` -- 28 vertices, 38 edges, a 72-entry sine table and 72 frames'
worth of visible-edge lists, 2,264 numbers that `tools/mk3d.py`
transcribed from the published BBC Elite source. The CoolAction! port
has no `READ`, so the same numbers are initialised arrays -- and they
are copied out of the BASIC by this script rather than by hand,
because 2,264 numbers typed twice would be wrong in one place and the
ship would be subtly bent in a way only the framebuffer comparison in
`sim/test_action.py` could see.

The port's *logic* is hand-written in `demos/cobra.act`; only the block
between the two marker lines is generated, and `poe check` fails if
the block does not match what the BASIC's `DATA` says today. The
BASIC's line numbers are the map: 200-249 vertices, 250-299 edges,
300-349 sines, 350 up the frames, which is `mk3d.py`'s layout.
"""

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAS = os.path.join(ROOT, "demos", "cobra.bas")
ACT = os.path.join(ROOT, "demos", "cobra.act")
BEGIN = "; ---- generated from demos/cobra.bas by tools/mkcobra.py: do not edit ----"
END = "; ---- end of the generated block ----"


def data(lo, hi):
    """Every DATA value on lines lo..hi of the BASIC, in order."""
    out = []
    for line in io.open(BAS, encoding="utf-8"):
        m = re.match(r"(\d+)\s+DATA\s+(.*)$", line.strip())
        if m and lo <= int(m.group(1)) <= hi:
            out += [int(v) for v in m.group(2).split(",")]
    return out


def tables():
    verts = data(200, 249)
    edges = data(250, 299)
    sines = data(300, 349)
    frames = data(350, 9999)
    assert len(verts) == 28 * 3, len(verts)
    assert len(edges) == 38 * 2, len(edges)
    assert len(sines) == 72, len(sines)
    # the frame stream is 72 of: a count, then that many edge indices
    i, n, total = 0, 0, 0
    while i < len(frames):
        cnt = frames[i]
        assert 0 < cnt <= 38 and all(0 <= e < 38 for e in frames[i + 1:i + 1 + cnt])
        i += 1 + cnt
        n += 1
        total += cnt
    assert n == 72 and i == len(frames), (n, i, len(frames))
    return verts, edges, sines, frames, total


def rows(vals, per=16):
    return "\n".join("  " + " ".join(str(v) for v in vals[i:i + per])
                     for i in range(0, len(vals), per))


def block():
    verts, edges, sines, frames, total = tables()
    o = [BEGIN]
    o.append("; 28 vertices: x, screen y, z -- tilted 20 degrees about X by")
    o.append("; tools/mk3d.py, so y is already a screen row and only x moves")
    o.append("INT ARRAY vx(28) = [")
    o.append(rows(verts[0::3]) + "]")
    o.append("INT ARRAY vy(28) = [")
    o.append(rows(verts[1::3]) + "]")
    o.append("INT ARRAY vz(28) = [")
    o.append(rows(verts[2::3]) + "]")
    o.append("; 38 edges, as two vertex indices")
    o.append("BYTE ARRAY ea(38) = [")
    o.append(rows(edges[0::2]) + "]")
    o.append("BYTE ARRAY eb(38) = [")
    o.append(rows(edges[1::2]) + "]")
    o.append("; 72 of sin, scaled to 127, one per 5 degrees")
    o.append("INT ARRAY sn(72) = [")
    o.append(rows(sines) + "]")
    o.append("; the visible edges of each of the 72 frames: a count, then")
    o.append("; that many edge indices -- %d edges in all, the culling done" % total)
    o.append("; on the host from the projected polygons (14-demos.md)")
    o.append("BYTE ARRAY fr(%d) = [" % len(frames))
    o.append(rows(frames, 24) + "]")
    o.append("CONST NLINES = %d" % total)
    o.append(END)
    return "\n".join(o) + "\n"


def splice(text, new):
    a, b = text.index(BEGIN), text.index(END) + len(END) + 1
    return text[:a] + new + text[b:]


def main():
    want = block()
    have = io.open(ACT, encoding="utf-8").read() if os.path.exists(ACT) else ""
    if BEGIN not in have or END not in have:
        sys.exit("%s has no generated block to fill" % os.path.relpath(ACT, ROOT))
    if "--check" in sys.argv:
        if splice(have, want) != have:
            print("  demos/cobra.act's tables are stale against demos/cobra.bas: "
                  "run python tools/mkcobra.py")
            return 1
        print("ok -- demos/cobra.act carries demos/cobra.bas's tables")
        return 0
    io.open(ACT, "w", encoding="utf-8", newline="\n").write(splice(have, want))
    print("wrote the tables into %s" % os.path.relpath(ACT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
