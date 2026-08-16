#!/usr/bin/env python3
"""Generate demos/cobra.bas -- Elite's Cobra Mk III, hidden lines gone.

    python tools/mk3d.py

**The model is the published one.** 28 vertices, 38 edges, 13 faces and
the edge-to-face table, transcribed from the annotated BBC Elite source
at bbcelite.com (the SHIP_COBRA_MK_3 blueprint); the transcription is
asserted against the counts the source states.

**The tilt is baked, the spin is runtime.** The host rotates the model
20 degrees about X once; BASIC spins it about the view's vertical axis,
which never touches y, so each vertex's screen Y is one constant and
only screen X varies. Everything is integer, and the largest
|qx*cos + qz*sin| is asserted inside 16-bit signed.

**Visibility is decided by the projected polygon, not the published
normal.** Elite's normals are hand-rounded integers -- (0,62,31) is
near its face's plane, not on it -- so a normal-based cull flips a few
degrees away from where the *drawn* geometry turns edge-on, and edges
vanished while their faces were still visibly open. Here each face's
boundary loop is walked out of the edge table (spurs like the laser
line pruned), its winding calibrated once against the published normal
far from the silhouette, and then every frame's visibility is the
**signed area of the face under the exact integer projection the
machine draws**, kept visible through a small grace margin. Measured
across the revolution: 24.6 edges a frame mean against the normal
cull's 23.6, worst 33 against 32 -- accuracy priced at about one LINE
a frame.

**One mode.** The see-through wireframe is gone by decision -- the
hidden-line ship is simply better -- so the draw loop erases the
two-flips-old frame's edges in black (its list precomputed like every
other) and draws the new set; two CLGs at start cover pages that have
never been drawn. Mode 5 double buffer throughout, D92's split: DBASE
names the glass, BASE the pencil, flipped in two POKEs after VSYNC.
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
# face normals as published -- used only to calibrate winding, far from
# the silhouette, where a few degrees of hand-rounding cannot matter
FACES = [
    (0, 62, 31), (-18, 55, 16), (18, 55, 16), (-16, 52, 14),
    (16, 52, 14), (-14, 47, 0), (14, 47, 0), (-61, 102, 0),
    (61, 102, 0), (0, 0, -80), (-7, -42, 9), (0, -30, 6), (7, -42, 9),
]
# each edge's two faces; the rear-panel details (23-30, 32-37) live in
# face 9's plane and appear and vanish with the stern as one unit
EDGE_FACES = [
    (0, 11), (4, 12), (3, 10), (7, 10), (8, 12), (8, 9), (6, 9),
    (5, 9), (7, 9), (1, 5), (2, 6), (3, 7), (4, 8), (0, 1), (0, 2),
    (9, 10), (9, 11), (9, 12), (10, 11), (11, 12), (1, 3), (2, 4),
    (0, 11), (9, 9), (9, 9), (9, 9), (9, 9), (9, 9), (9, 9), (9, 9),
    (9, 9), (5, 6), (9, 9), (9, 9), (9, 9), (9, 9), (9, 9), (9, 9),
]

F = 72                       # frames in a revolution: 5 degrees a step
TILT = math.radians(20)
SCALE = 1.10                 # the largest that keeps the products 16-bit
MARGIN = 150                 # px^2 of grace before a closing face hides


def main():
    assert len(VERTS) == 28 and len(EDGES) == 38, "not the published ship"
    assert len(FACES) == 13 and len(EDGE_FACES) == 38
    assert all(0 <= a < 28 and 0 <= b < 28 for a, b in EDGES)
    assert all(0 <= a < 13 and 0 <= b < 13 for a, b in EDGE_FACES)

    ct, st = math.cos(TILT), math.sin(TILT)

    def tilt(v):
        x, y, z = v
        return (x, y * ct - z * st, y * st + z * ct)

    qx, qy, qz = [], [], []
    for v in VERTS:
        x, y, z = tilt(v)
        qx.append(int(round(x * SCALE)))
        qy.append(int(round(y * SCALE)))
        qz.append(int(round(z * SCALE)))

    worst = max(abs(qx[v]) + abs(qz[v]) for v in range(28)) * 127
    assert worst < 32000, "products overflow 16-bit: %d" % worst

    sy = [96 - qy[v] for v in range(28)]
    assert all(4 <= y <= 188 for y in sy), "screen y out of mode 5"
    sn = [int(round(127 * math.sin(2 * math.pi * i / F)))
          for i in range(F)]

    def project(f):
        """integer screen coordinates, exactly as line 133 computes"""
        c, s = sn[(f + F // 4) % F], sn[f]
        return [(128 + int((qx[v] * c + qz[v] * s) / 256), sy[v])
                for v in range(28)]

    for f in range(F):
        for (x, _) in project(f):
            assert 4 <= x <= 251, "screen x out of range: %d" % x

    # ---- each face's boundary loop, walked from the edge table. The
    # laser line (20-21) hangs off faces 0 and 11 as a spur -- an edge
    # with a degree-1 endpoint -- and spurs bound no area, so they are
    # pruned before the walk.
    loops = []
    for face in range(13):
        es = [list(EDGES[e]) for e in range(38)
              if EDGE_FACES[e] != (9, 9) and face in EDGE_FACES[e]]
        while True:
            deg = {}
            for a, b in es:
                deg[a] = deg.get(a, 0) + 1
                deg[b] = deg.get(b, 0) + 1
            drop = [e for e in es if deg[e[0]] == 1 or deg[e[1]] == 1]
            if not drop:
                break
            es = [e for e in es if e not in drop]
        assert len(es) >= 3, "face %d has no loop" % face
        adj = {}
        for a, b in es:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
        assert all(len(v) == 2 for v in adj.values()), \
            "face %d boundary is not one cycle" % face
        start = es[0][0]
        loop, prev = [start], None
        while True:
            nxt = [n for n in adj[loop[-1]] if n != prev]
            prev = loop[-1]
            loop.append(nxt[0])
            if loop[-1] == start:
                break
        loops.append(loop[:-1])

    def area(face, pts):
        a, lp = 0, loops[face]
        for i in range(len(lp)):
            x0, y0 = pts[lp[i]]
            x1, y1 = pts[lp[(i + 1) % len(lp)]]
            a += x0 * y1 - x1 * y0
        return a

    # winding calibration: at each face's farthest-from-silhouette
    # frame the published normal is unambiguous, and the signed area's
    # sign there fixes the loop's orientation for good
    nrm = [tilt(n) for n in FACES]
    cal = []
    for face in range(13):
        best, bf = 0.0, 0
        for f in range(F):
            th = 2 * math.pi * f / F
            vz = -nrm[face][0] * math.sin(th) + nrm[face][2] * math.cos(th)
            if abs(vz) > abs(best):
                best, bf = vz, f
        a = area(face, project(bf))
        assert a != 0, "face %d degenerate at calibration" % face
        cal.append(-1 if (best < 0) == (a < 0) else 1)

    vis = []
    for f in range(F):
        pts = project(f)
        fv = [cal[k] * area(k, pts) < MARGIN for k in range(13)]
        vis.append([e for e in range(38)
                    if fv[EDGE_FACES[e][0]] or fv[EDGE_FACES[e][1]]])
    counts = [len(v) for v in vis]
    assert all(8 <= n < 38 for n in counts), "culling degenerate: %s" % (
        sorted(set(counts)))
    # no edge may flicker: visible, gone for one frame, visible again
    for e in range(38):
        v = [e in vis[f] for f in range(F)]
        assert not any(v[f - 1] and v[(f + 1) % F] and not v[f]
                       for f in range(F)), "edge %d flickers" % e
    slots = sum(counts)

    body = """1 GOTO 100
10 A=A+1:IF A>71 THEN A=0
11 VSYNC
12 POKE $FF30,P:P=96-P:POKE $FF13,P
13 IF R>0 THEN R=R-1:CLG 0:GOTO 16
14 Y=A-2:IF Y<0 THEN Y=Y+72
15 D=O(Y)+Q(Y)-1:FOR K=O(Y) TO D:LINE H(K),J(K),L(K),M(K),0:NEXT K
16 D=O(A)+Q(A)-1:FOR K=O(A) TO D:LINE H(K),J(K),L(K),M(K),10:NEXT K
17 IF INKEY=0 THEN GOTO 10
18 MODE 0
19 CURSOR 1
20 END
100 PRINT "COBRA MK III"
101 PRINT "COMPUTING 72 FRAMES..."
102 DIM U(2015):DIM W(27):DIM E(37):DIM G(37):DIM S(71)
103 DIM X(27):DIM Z(27)
104 DIM H(%d):DIM J(%d):DIM L(%d):DIM M(%d)
105 DIM O(71):DIM Q(71)
110 FOR V=0 TO 27
111 READ N:X(V)=N
112 READ N:W(V)=N
113 READ N:Z(V)=N
114 NEXT V
115 FOR K=0 TO 37
116 READ N:E(K)=N
117 READ N:G(K)=N
118 NEXT K
120 FOR V=0 TO 71
121 READ N:S(V)=N
122 NEXT V
130 FOR F=0 TO 71
131 T=F+18:IF T>71 THEN T=T-72
132 C=S(T):D=S(F):B=F*28
133 FOR V=0 TO 27:U(B+V)=128+(X(V)*C+Z(V)*D)/256:NEXT V
134 NEXT F
135 PRINT "CULLING..."
140 B=0
141 FOR F=0 TO 71
142 READ N:Q(F)=N:O(F)=B:C=F*28
143 FOR K=1 TO N
144 READ T
145 H(B)=U(C+E(T)):J(B)=W(E(T)):L(B)=U(C+G(T)):M(B)=W(G(T))
146 B=B+1
147 NEXT K
148 NEXT F
150 MODE 5
151 CURSOR 0
152 CLG 0
153 POKE $FF30,0:POKE $FF11,$7A
154 A=71:P=0:R=2
155 GOTO 10
""" % (slots - 1, slots - 1, slots - 1, slots - 1)

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
    seen = []
    for f in range(F):
        seen += [counts[f]] + vis[f]
    src = body + "\n".join(
        data(model, 200) + data(edges, 250) + data(sn, 300)
        + data(seen, 350)) + "\n"
    path = os.path.join(ROOT, "demos", "cobra.bas")
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    lines = [l for l in src.split("\n") if l.strip()]
    ns = [int(l.split()[0]) for l in lines]
    assert ns == sorted(ns), "line numbers not ascending"
    over = [n for n, l in zip(ns, lines) if len(l) > 79]
    assert not over, "lines over 79 chars: %s" % over
    print("  cobra.bas: %d lines, 28 vertices, 38 edges, %d frames"
          % (len(lines), F))
    print("  visible edges a frame: %d-%d, mean %.1f; %d slots, %s bytes"
          % (min(counts), max(counts), slots / float(F), slots,
             "{:,}".format(slots * 8)))
    print("  cull: projected signed area, %d px^2 grace, 0 flickers"
          % MARGIN)
    print("  -> %s" % path)


if __name__ == "__main__":
    main()
