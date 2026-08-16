#!/usr/bin/env python3
"""Regenerate demos/wave.bas -- the palette and the program are one design.

    python tools/mkwave.py

**Why 253 colours.** Entry 0 is the border, so it stays black; the
head needs a white, which is entry 255; entry 254 is parked at black so
a stray index shows background rather than a colour. 1..253 is the
ramp. And 253 is the *right* count, not just what was left: a sweep
paints 478 lines (239 down, 239 up) and gcd(478, 253) = 1 -- 11*23
against 2*239 -- so the row-to-colour alignment precesses through every
phase and every row shows every colour over time. 254 would share a
factor 2 with 478 and lock half the alignments out permanently.

**The colour is a free-running counter, by specification.** Every
painted line takes the next palette entry, wrapping 253 -> 1; lines and
colours step in lockstep, nothing skipped. The consequence, accepted
with eyes open: the 240 rows hold a 478-value window folded into 253,
so not all 253 are on screen at an instant -- the pattern drifts
instead, which is the point. `sim/test_run.py`'s lockstep case is the
gate on all of it.

**The ramp is one turn of the hue circle at full saturation**, and the
counter's wrap means it must close -- entry 253 is entry 1's neighbour.
253 colours a click or two apart is more movement than the circle
supplies (90 clicks: six edges of fifteen), and the rest is spent as
deviation from the ideal circle. Which deviation was the shadow-band
lesson: nearest-by-distance takes inward neighbours as readily as
outward, and a red dropped 15->14 costs 0.299 of perceived luminance
where a green costs 0.587, so rows came out darker than their
neighbours at the 253/90 beat. Charging LW clicks of hue error per
click of brightness error buys them off; LW=4 is the measured knee
(LW=0 banded, luminance-only wandered 2.71 clicks off the circle and
desaturated).
"""
import io
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

N = 253                    # ramp entries 1..253; 0 border, 255 white
W = (0.299, 0.587, 0.114)  # what the eye weighs each channel at
LW = 4.0                   # a click of brightness error costs 4 of hue


def hexagon(t):
    """t in 0..6 -> the hue circle at full saturation, channels 0..1"""
    k, f = int(t) % 6, t - int(t)
    return [(1, f, 0), (1 - f, 1, 0), (0, 1, f),
            (0, 1 - f, 1), (f, 0, 1), (1, 0, 1 - f)][k]


def hug(maxstep=2, span=2, vmax=15.0):
    """walk the hue circle; take the best unused colour a step away"""
    used, out, prev, dev = set(), [], None, []
    for i in range(N):
        ideal = [x * vmax for x in hexagon(i * 6.0 / N)]
        base = [int(round(x)) for x in ideal]
        best = None
        for dr in range(-span, span + 1):
            for dg in range(-span, span + 1):
                for db in range(-span, span + 1):
                    c = (base[0] + dr, base[1] + dg, base[2] + db)
                    if not all(0 <= x <= 15 for x in c) or c in used:
                        continue
                    step = 0 if prev is None else sum(
                        abs(a - b) for a, b in zip(c, prev))
                    if prev is not None and not 1 <= step <= maxstep:
                        continue
                    ex = abs(sum(w * (x - y)
                                 for w, x, y in zip(W, c, ideal)))
                    d = math.sqrt(sum((a - b) ** 2
                                      for a, b in zip(c, ideal)))
                    if best is None or (LW * ex + d, step) < best[0]:
                        best = ((LW * ex + d, step), c, d)
        if best is None:
            raise SystemExit("  dead end at entry %d" % i)
        used.add(best[1])
        out.append(best[1])
        dev.append(best[2])
        prev = best[1]
    return out, dev


# **Draw order is the flicker fix.** The head was drawn last, after up
# to four fill spans (~2.7 ms), and vblank is ~1.4 ms: at the top of
# the screen the raster reached the head's row before the white was
# down, so it flickered there and was steady at the bottom, where the
# raster arrives 13 ms later. The two spans that matter -- recolouring
# the row the head left (line 13) and drawing the new head (14) -- go
# first and fit inside vblank; the passed-through rows follow.
#
# **Colour order is the spec.** Every vacated row takes the next E, in
# the order the head crossed them: O first, then the rows between O and
# Y. The counter never advances without a line painted, and no line is
# painted without advancing the counter -- which is what makes the
# lockstep testable from the framebuffer alone.
BODY = """1 GOTO 100
10 A=A+3:IF A>719 THEN A=A-720
11 Y=S(A)
12 VSYNC
13 IF O<>Y THEN R=O:GOSUB 50
14 LINE 0,Y,255,Y,255
15 IF O<Y-1 THEN FOR I=O+1 TO Y-1:R=I:GOSUB 50:NEXT I
16 IF O>Y+1 THEN FOR I=1 TO O-Y-1:R=O-I:GOSUB 50:NEXT I
17 O=Y
18 IF INKEY=0 THEN GOTO 10
19 MODE 0
20 CURSOR 1
21 END
50 LINE 0,R,255,R,E
51 E=E+1:IF E>253 THEN E=1
52 RETURN
100 MODE 6
101 CURSOR 0
102 DIM S(719)
103 FOR I=0 TO 180
104 READ V
105 S(I)=V
106 NEXT I
107 FOR I=1 TO 179
108 S(360-I)=S(I)
109 S(360+I)=239-S(I)
110 S(720-I)=239-S(I)
111 NEXT I
112 S(360)=120:S(540)=0
120 FOR I=1 TO 253
121 READ V
122 POKE $FF1E,I
123 POKE $FF1F,V/256
124 POKE $FF1F,V-V/256*256
125 NEXT I
126 POKE $FF1E,0:POKE $FF1F,0:POKE $FF1F,0
127 POKE $FF1E,254:POKE $FF1F,0:POKE $FF1F,0
128 POKE $FF1E,255:POKE $FF1F,15:POKE $FF1F,255
129 CLG 0
130 A=0:O=120:E=1
131 GOTO 10
"""


def data(vals, start):
    lines, n, i = [], start, 0
    while i < len(vals):
        chunk = vals[i:i + 14]
        while len(("%d DATA " % n) + ",".join(map(str, chunk))) > 79:
            chunk = chunk[:-1]
        lines.append("%d DATA %s" % (n, ",".join(map(str, chunk))))
        i += len(chunk)
        n += 1
    return lines


def main():
    out, dev = hug()

    # the checks that matter, asserted rather than eyeballed
    assert len(out) == N, "wrong length"
    assert len(set(out)) == N, "duplicate colours: %s" % sorted(
        c for c in set(out) if out.count(c) > 1)
    assert (0, 0, 0) not in out, "a ramp entry is black"
    assert (15, 15, 15) not in out, "a ramp entry is white"
    steps = [sum(abs(a - b) for a, b in zip(out[i], out[(i + 1) % N]))
             for i in range(N)]       # cyclic: includes the 253->1 wrap
    lum = [sum(w * x for w, x in zip(W, c)) for c in out]
    ripple = []
    for i in range(N):
        near = [lum[(i + j) % N] for j in (-2, -1, 0, 1, 2)]
        ripple.append(lum[i] - sum(near) / 5.0)

    print("  %d entries, distinct %d, duplicates 0 (asserted)"
          % (N, len(set(out))))
    print("  steps incl. the wrap: 1-unit %d, 2-unit %d, more %d"
          % (steps.count(1), steps.count(2),
             sum(1 for s in steps if s > 2)))
    print("  the loop closes 253 -> 1 at %d click(s)" % steps[-1])
    print("  deviation from the ideal circle: mean %.2f max %.2f"
          % (sum(dev) / len(dev), max(dev)))
    print("  rows darker than their neighbours by >0.35: %d"
          % sum(1 for r in ripple if r < -0.35))
    print("  gcd(478 paints a sweep, %d) = %d" % (N, math.gcd(478, N)))

    q = [int(round(120 + 119 * math.sin(2 * math.pi * i / 720)))
         for i in range(181)]
    packed = [c[0] * 256 + c[1] * 16 + c[2] for c in out]
    assert len(set(packed)) == N, "packing collided"
    src = BODY + "\n".join(data(q, 200) + data(packed, 300)) + "\n"
    path = os.path.join(ROOT, "demos", "wave.bas")
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    lines = [l for l in src.split("\n") if l.strip()]
    ns = [int(l.split()[0]) for l in lines]
    assert ns == sorted(ns), "line numbers not ascending"
    over = [n for n, l in zip(ns, lines) if len(l) > 79]
    assert not over, "lines over 79 chars: %s" % over
    print("  wave.bas: %d lines -> %s" % (len(lines), path))


if __name__ == "__main__":
    main()
