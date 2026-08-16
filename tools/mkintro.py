#!/usr/bin/env python3
"""Generate demos/intro.bas -- the scroller intro, hardware doing the work.

    python tools/mkintro.py

**The motion is registers, not redrawing.** Mode 1 stores 80 columns
and shows 40, so the display is a window onto a wider banner: per frame
the fine scroll takes the low four bits (`VID_SCRL_X` in text -- D93,
the drift this demo caught: section 5.5 documented it while the pixel
stage passed text through unscrolled) and the coarse cell is a
`VID_BASE_L` byte-pair slide. Every stored row is 40-column periodic --
its two halves identical -- so when the window has slid 40 cells the
base snaps home invisibly: an infinite scroll with zero drawing. The
whole screen bobs on `VID_SCRL_Y`'s fine-vertical sine for free, and
the border flashes white on every snare.

**The music is the SYNTH demo's top three voices, verbatim** -- lead,
arpeggio, and the bass whose rests are the snare -- same pitch tables,
same envelopes, same 9-frames-a-step tempo, with the tracks carried as
arrays (the intro's screen belongs to the scroller; SYNTH keeps the
screen-as-sequencer trick where it means something).

Frame budget: scroll 3 statements, wobble 2, border 1, envelopes 7 --
the step lands whole on its frame, and the suite's cadence gate is the
proof, as it was for SYNTH.
"""
import io
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TRACKS = [
    "Q   :   :   R   Q   :   :   M O ",
    "T VT:RQMO T XVTQ:M YXVTQ:M QRQO ",
    "AM AMA MHT HTH TJV JVJ VFR FRF R",
]
MASKS = [82, 70, 46]
PAL_CLOCK, SID_MAX, SEMITONE = 985248, 16777216, 1.0595

MSG1 = "COOL8 MEGADEMO * THE SCREEN IS ALIVE *  "
MSG2 = "WAVE COBRA SYNTH PLASMA MAZE RAINBOW *  "
# fg colours cycled across the message cells, CGA bank brights
RAINBOW = [12, 14, 10, 11, 9, 13, 15, 11]

BODY = """1 GOTO 100
10 VSYNC
11 T=T+1:IF T>319 THEN T=0
12 D=T/8:POKE $FF16,T-D*8:POKE $FF12,D+D
13 K=K+1:IF K>63 THEN K=0
14 POKE $FF18,W(K)
15 POKE $FF1A,14
16 F=F+1:IF F=9 THEN F=0:GOSUB 30
17 IF O=1 AND V>0 THEN G=G+1:IF G>3 THEN G=0:V=V-1:SOUND 0,P,V,0
18 IF E=1 AND H>0 THEN H=H-3:IF H<0 THEN H=0
19 IF E=1 AND H>0 THEN SOUND 1,Q,H,0
20 IF E=1 AND H=0 THEN SOUND 1,Q,0,0:E=0
21 IF B=1 AND X>0 THEN X=X-2:IF X<0 THEN X=0
22 IF B=1 AND X>0 THEN SOUND 2,3000,X,1
23 IF B=1 AND X=0 THEN SOUND 2,3000,0,1:B=0
24 I=INKEY:IF I=0 THEN GOTO 10
25 SOUND 0,0,0,0:SOUND 1,0,0,0:SOUND 2,0,0,0
26 POKE $FF16,0:POKE $FF18,0
27 MODE 0
28 CURSOR 1:END
30 A=A+1:IF A>31 THEN A=0
31 N=R(A):IF N>0 THEN P=Z(N-1):V=10:O=0:SOUND 0,P,V,0
32 IF N<1 THEN O=1
33 N=R(A+32):IF N>0 THEN Q=Z(N+25):H=7:E=0:SOUND 1,Q,7,0
34 IF N<1 THEN E=1:H=7
35 N=R(A+64):IF N>0 THEN SOUND 2,Z(N+51),9,0:B=0
36 IF N<1 THEN B=1:X=13:POKE $FF1A,1
37 RETURN
100 MODE 1
101 CLS:CURSOR 0
102 DIM Z(77):DIM W(63):DIM R(95)
103 FOR I=0 TO 77:READ N:Z(I)=N:NEXT I
104 FOR I=0 TO 63:READ N:W(I)=N:NEXT I
105 FOR I=0 TO 95:READ N:R(I)=N:NEXT I
110 FOR I=0 TO 79
111 POKE 39552+I+I,61:POKE 40832+I+I,61
112 NEXT I
120 FOR I=0 TO 39
121 READ N:POKE 40192+I+I,N:POKE 40272+I+I,N
122 NEXT I
123 FOR I=0 TO 39
124 READ N:POKE 40193+I+I,N:POKE 40273+I+I,N
125 NEXT I
130 FOR I=0 TO 39
131 READ N:POKE 42112+I+I,N:POKE 42192+I+I,N
132 NEXT I
140 T=0:K=0:F=0:A=31:O=1:E=1:B=1:V=0:H=0:X=0
141 GOTO 10
"""


def pitch(note, mask):
    f = 40.0 * (SEMITONE ** (note + mask)) * PAL_CLOCK / SID_MAX
    return int(round(2.0 * f))


def main():
    assert len(MSG1) == 40 and len(MSG2) == 40, (len(MSG1), len(MSG2))
    pitches = [pitch(n, m) for m in MASKS for n in range(1, 27)]
    assert all(0 < p < 65536 for p in pitches)
    wob = [int(round(7.5 + 7.5 * math.sin(2 * math.pi * k / 64)))
           for k in range(64)]
    assert all(0 <= w <= 15 for w in wob)
    tracks = []
    for t in TRACKS:
        assert len(t) == 32
        tracks += [(ord(c) - 64) if c.isalpha() else 0 for c in t]
    msg1 = [ord(c) for c in MSG1]
    attr1 = [RAINBOW[i % len(RAINBOW)] for i in range(40)]
    msg2 = [ord(c) for c in MSG2]

    # the map addresses BODY pokes, derived here so a map move is one
    # edit: rows 4 and 12 are the rules, row 8 the message (chars then
    # attrs), row 20 the credits
    base = 0x9800
    assert base + 4 * 160 == 39552
    assert base + 12 * 160 == 40832
    assert base + 8 * 160 == 40192 and base + 8 * 160 + 80 == 40272
    assert base + 8 * 160 + 1 == 40193
    assert base + 20 * 160 == 42112

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

    src = (BODY + "\n".join(
        data(pitches, 200) + data(wob, 240) + data(tracks, 260)
        + data(msg1, 300) + data(attr1, 310) + data(msg2, 320)) + "\n")
    path = os.path.join(ROOT, "demos", "intro.bas")
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    lines = [l for l in src.split("\n") if l.strip()]
    ns = [int(l.split()[0]) for l in lines]
    assert ns == sorted(ns), "line numbers not ascending"
    over = [n for n, l in zip(ns, lines) if len(l) > 79]
    assert not over, "lines over 79 chars: %s" % over
    print("  intro.bas: %d lines; message %r" % (len(lines), MSG1))
    print("  -> %s" % path)


if __name__ == "__main__":
    main()
