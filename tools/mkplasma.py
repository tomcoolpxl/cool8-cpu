#!/usr/bin/env python3
"""Generate demos/plasma.bas -- paint once, animate only the palette.

    python tools/mkplasma.py

**The pixels never move.** Mode 6 is painted once with a fixed
interference pattern and the animation is palette rotation: the colour
under every pixel slides along a cyclic rainbow while VRAM stays
byte-for-byte still. WAVE proved the palette machinery; this is that
lesson run backwards.

**The pattern is separable, and that is what makes it paintable.**
colour(x, y) = A(x) + G(y), two integer interference tables (two sine
voices each, host-computed, emitted as DATA), summing to 1..47 -- so
the paint loop is one statement a pixel through PIX_DATA's
auto-increment, about 25 s of visible top-down fill that is its own
progress bar. Painting a non-separable field at this interpreter's
speed would be minutes; the separable form is the whole trick.

**47 colours, and why not 240.** Rotating a palette costs two PAL_DATA
pokes an entry, and a 240-entry rotation is a third of a second -- 3
fps. 47 entries stream in ~90 ms through PAL_DATA's auto-increment
(one PAL_IDX write, then pairs), which paced by VSYNC gives the slow
oily flow plasma wants. The wrap costs nothing: the palette arrays are
emitted doubled, H(O+I) with O in 0..46, so the inner loop has no IF
-- an IF that skips its NEXT is the classic trap here.
"""
import io
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

N = 47                       # cyclic ramp entries 1..47; 0 stays border


def hexagon(t):
    k, f = int(t) % 6, t - int(t)
    return [(1, f, 0), (1 - f, 1, 0), (0, 1, f),
            (0, 1 - f, 1), (f, 0, 1), (1, 0, 1 - f)][k]


BODY = """1 GOTO 100
10 VSYNC
11 GOSUB 30
12 T=INKEY:IF T=0 THEN GOTO 10
13 MODE 0
14 CURSOR 1:END
30 POKE $FF1E,1
31 FOR I=0 TO 46:POKE $FF1F,H(O+I):POKE $FF1F,L(O+I):NEXT I
32 O=O+1:IF O>46 THEN O=0
33 RETURN
100 MODE 6
101 CURSOR 0
102 DIM A(255):DIM G(239):DIM H(93):DIM L(93)
103 FOR I=0 TO 255:READ N:A(I)=N:NEXT I
104 FOR I=0 TO 239:READ N:G(I)=N:NEXT I
105 FOR I=0 TO 46
106 READ N:H(I)=N:H(I+47)=N
107 READ N:L(I)=N:L(I+47)=N
108 NEXT I
109 O=0:GOSUB 30
110 CLG 0
120 FOR Y=0 TO 239
121 POKE $FF36,Y:POKE $FF34,0:POKE $FF35,0
122 D=G(Y)
123 FOR I=0 TO 255:POKE $FF38,A(I)+D:NEXT I
124 NEXT Y
125 GOTO 10
"""


def main():
    ax = []
    for x in range(256):
        v = (math.sin(2 * math.pi * 2 * x / 256)
             + math.sin(2 * math.pi * 3 * x / 256 + 1.3))
        ax.append(int(round((v + 2) / 4 * 23)) + 1)          # 1..24
    gy = []
    for y in range(240):
        v = (math.sin(2 * math.pi * 2 * y / 240 + 0.7)
             + math.sin(2 * math.pi * 5 * y / 240))
        gy.append(int(round((v + 2) / 4 * 23)))              # 0..23
    assert min(ax) >= 1 and max(ax) <= 24
    assert min(gy) >= 0 and max(gy) <= 23
    sums = {a + g for a in ax for g in gy}
    assert min(sums) >= 1 and max(sums) <= N, sorted(sums)[:3]

    pal = []
    for i in range(N):
        r, g, b = hexagon(i * 6.0 / N)
        pal.append((int(round(r * 15)),
                    int(round(g * 15)), int(round(b * 15))))
    hi = [c[0] for c in pal]                  # PAL_DATA high byte: R
    lo = [c[1] * 16 + c[2] for c in pal]      # low byte: G*16+B

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

    pal_pairs = [v for i in range(N) for v in (hi[i], lo[i])]
    src = (BODY + "\n".join(data(ax, 200) + data(gy, 300)
                            + data(pal_pairs, 400)) + "\n")
    path = os.path.join(ROOT, "demos", "plasma.bas")
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    lines = [l for l in src.split("\n") if l.strip()]
    ns = [int(l.split()[0]) for l in lines]
    assert ns == sorted(ns), "line numbers not ascending"
    over = [n for n, l in zip(ns, lines) if len(l) > 79]
    assert not over, "lines over 79 chars: %s" % over
    print("  plasma.bas: %d lines; field 1..%d over a %d-entry cyclic"
          " ramp" % (len(lines), max(sums), N))
    print("  -> %s" % path)


if __name__ == "__main__":
    main()
