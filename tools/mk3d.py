#!/usr/bin/env python3
"""Generate demos/cobra.bas -- Elite's Cobra Mk III on the double buffer.

    python tools/mk3d.py

**The model is the published one.** 28 vertices and 38 edges transcribed
from the annotated BBC Elite source at bbcelite.com (the SHIP_COBRA_MK_3
blueprint); nothing here invents geometry, and the transcription is
asserted against the counts the source states.

**The tilt is baked, the spin is runtime, and the order is what makes
it cheap.** The host rotates the model 20 degrees about X once. BASIC
then spins it about the *view's* vertical axis: p' = RotY(theta) * q,
and RotY never touches y -- so each vertex's screen Y is one constant
and only screen X varies with the angle. The startup loop computes
72 frames x 28 vertices of screen X into one array, about a second of
integer arithmetic, and the draw loop is LINE statements and nothing
else. Everything is integer: coordinates are scaled so the largest
|qx*cos + qz*sin| stays inside 16-bit signed with margin, asserted
below rather than hoped.

**Mode 5 is the double-buffer mode** (04-system.md section 5.4) and the
demo is the first user of it: pages at $0000 and $6000, and because
$6000's low byte is zero the whole flip is one POKE of VID_BASE_H. The
display latches the base at frame start (cool8_fetch.v samples once);
the pixel port reads it live (D91's neighbour, cool8_pixport.v) -- so
after VSYNC the demo points the base at the page just hidden, clears
and draws it, and the viewer only ever sees finished frames.
"""
import io
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# SHIP_COBRA_MK_3, bbcelite.com -- vertex coordinates as published
VERTS = [
    (32, 0, 76), (-32, 0, 76), (0, 26, 24), (-120, -3, -8),
    (120, -3, -8), (-88, 16, -40), (88, 16, -40), (128, -8, -40),
    (-128, -8, -40), (0, 26, -40), (-32, -24, -40), (32, -24, -40),
    (-36, 8, -40), (-8, 12, -40), (8, 12, -40), (36, 8, -40),
    (36, -12, -40), (8, -16, -40), (-8, -16, -40), (-36, -12, -40),
    (0, 0, 76), (0, 0, 90), (-80, -6, -40), (-80, 6, -40),
    (-88, 0, -40), (80, 6, -40), (88, 0, -40), (80, -6, -40),
]
EDGES = [
    (0, 1), (0, 4), (1, 3), (3, 8), (4, 7), (6, 7), (6, 9), (5, 9),
    (5, 8), (2, 5), (2, 6), (3, 5), (4, 6), (1, 2), (0, 2), (8, 10),
    (10, 11), (7, 11), (1, 10), (0, 11), (1, 5), (0, 6), (20, 21),
    (12, 13), (18, 19), (14, 15), (16, 17), (15, 16), (14, 17),
    (13, 18), (12, 19), (2, 9), (22, 24), (23, 24), (22, 23),
    (25, 26), (26, 27), (25, 27),
]

F = 72                       # frames in a revolution: 5 degrees a step
TILT = math.radians(20)
SCALE = 1.10                 # the largest that keeps the products 16-bit


def main():
    assert len(VERTS) == 28 and len(EDGES) == 38, "not the published ship"
    assert all(0 <= a < 28 and 0 <= b < 28 for a, b in EDGES)

    ct, st = math.cos(TILT), math.sin(TILT)
    qx, qy, qz = [], [], []
    for (x, y, z) in VERTS:
        yt = y * ct - z * st         # RotX(20) once, on the host
        zt = y * st + z * ct
        qx.append(int(round(x * SCALE)))
        qy.append(int(round(yt * SCALE)))
        qz.append(int(round(zt * SCALE)))

    # the products BASIC will form: |qx*c + qz*s| must fit 16-bit signed
    worst = max(abs(qx[v]) + abs(qz[v]) for v in range(28)) * 127
    assert worst < 32000, "products overflow 16-bit: %d" % worst

    sy = [96 - qy[v] for v in range(28)]          # screen y, constant
    assert all(4 <= y <= 188 for y in sy), "screen y out of mode 5"
    # screen x across the whole revolution, checked the way BASIC will
    # compute it -- integer sine table, integer truncating division
    sn = [int(round(127 * math.sin(2 * math.pi * i / F)))
          for i in range(F)]
    for f in range(F):
        c, s = sn[(f + F // 4) % F], sn[f]
        for v in range(28):
            x = 128 + int((qx[v] * c + qz[v] * s) / 256)
            assert 4 <= x <= 251, "screen x out of range: %d" % x

    body = """1 GOTO 100
10 A=A+1:IF A>71 THEN A=0
11 VSYNC
12 P=96-P:POKE $FF13,P
13 CLG 0
14 B=A*28
15 FOR K=0 TO 37:LINE U(B+E(K)),W(E(K)),U(B+G(K)),W(G(K)),10:NEXT K
16 IF INKEY=0 THEN GOTO 10
17 POKE $FF13,0
18 MODE 0
19 CURSOR 1
20 END
100 PRINT "COBRA MK III"
101 PRINT "COMPUTING 72 FRAMES..."
102 DIM U(2015):DIM W(27):DIM E(37):DIM G(37):DIM S(71)
103 DIM X(27):DIM Z(27)
104 FOR V=0 TO 27
105 READ N:X(V)=N
106 READ N:W(V)=N
107 READ N:Z(V)=N
108 NEXT V
110 FOR K=0 TO 37
111 READ N:E(K)=N
112 READ N:G(K)=N
113 NEXT K
120 FOR V=0 TO 71
121 READ N:S(V)=N
122 NEXT V
130 FOR F=0 TO 71
131 T=F+18:IF T>71 THEN T=T-72
132 C=S(T):D=S(F):B=F*28
133 FOR V=0 TO 27:U(B+V)=128+(X(V)*C+Z(V)*D)/256:NEXT V
134 NEXT F
140 MODE 5
141 CURSOR 0
142 CLG 0
143 A=71:P=0
144 GOTO 10
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

    model = []
    for v in range(28):
        model += [qx[v], sy[v], qz[v]]
    edges = [n for e in EDGES for n in e]
    src = body + "\n".join(
        data(model, 200) + data(edges, 250) + data(sn, 300)) + "\n"
    path = os.path.join(ROOT, "demos", "cobra.bas")
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    lines = [l for l in src.split("\n") if l.strip()]
    ns = [int(l.split()[0]) for l in lines]
    assert ns == sorted(ns), "line numbers not ascending"
    over = [n for n, l in zip(ns, lines) if len(l) > 79]
    assert not over, "lines over 79 chars: %s" % over
    print("  cobra.bas: %d lines, 28 vertices, 38 edges, %d frames"
          % (len(lines), F))
    print("  worst product %d of 32767; screen x,y asserted in range"
          % worst)
    print("  -> %s" % path)


if __name__ == "__main__":
    main()
