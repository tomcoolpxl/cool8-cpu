#!/usr/bin/env python3
"""Generate demos/synth.bas -- the c64-synth sequencer, screen as memory.

    python tools/mksynth.py

**The port of tomcoolpxl/c64-synth, its trick kept whole: the screen is
the sequencer's memory.** The original reads its notes off a virtual
C64 display; COOL8 does it natively, because modes 0/1 are text in main
RAM -- the play loop PEEKs the bytes PRINT painted, cell = $9800 +
row*160 + col*2, char then attribute.

**Melody, tuning, tempo: the original's.** DEFAULT_TRACKS verbatim;
A=1..Z=26 are notes, everything else rests; pitch is the synth's SID
arithmetic (40 * 1.0595^(note+mask) * 985248/2^24 Hz, masks 82/70/46,
the slightly-sharp 1.0595 kept deliberately) as ~2*Hz DATA. The 160 ms
step is 9.6 frames at 60 Hz; **9 frames -- 150 ms, slightly faster --
by decision.**

**Seven voices, keys 1-8 toggling each live, the row's digit lit or
dimmed to show it.** Muted voices skip their triggers and envelopes and
are silenced at the flip:

  v0 LEAD   the track, held at 10, released one step per four frames
  v1 ARP    plucked at 9, fast decay on rests
  v2 BASS   squares at 10; **a rest is the snare** -- the same voice
            flips to noise, the original's bass_snare move
  v3 DRUM   a new, visible, editable row: K kick (low square), S snare
            (noise), H hat (short high noise)
  v4 ECHO   the lead row read two steps late, quiet, fading -- a pure
            delay, deliberately not a detune (vetoed: no robots)
  v5 ECHO   the arp row one step late, quieter
  v6 DRONE  the bass root an octave down, soft and sustained
  v7        spare; its toggle lights, nothing sounds

The echo and drone reads run on a different frame (F=1) than the step
work (F=0 after wrap), so the heaviest frame stays inside the 60 Hz
budget -- the suite's 9-frames-per-step gate is the proof, not this
comment.

**The whole screen is C64 colours**: bank 0's sixteen slots are
repainted with the machine's own Commodore 64 palette (tools/palette.py
bank 10, quantised the same way), the border is light blue through
VID_BORDER, and every attribute is light-blue-on-blue -- the boot
screen every C64 owner remembers. Attribute bytes are C64-indexed:
paper 6, ink 14 ($6E), playhead inverted ($E6), a live voice's digit
white ($61), a muted one dark grey ($6B).
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import palette                                             # noqa: E402

# src/Config.js DEFAULT_TRACKS, verbatim -- 32 steps, cols 7..38
TRACKS = [
    "Q   :   :   R   Q   :   :   M O ",
    "T VT:RQMO T XVTQ:M YXVTQ:M QRQO ",
    "AM AMA MHT HTH TJV JVJ VFR FRF R",
]
MASKS = [82, 70, 46, 94]     # the shipped three, plus the flute's
                             # octave one above the lead
# the percussion the bass row already implied, made visible: the
# original snared on every bass rest, so the drum row IS those rests.
# K and H decode too, for the editor to type.
DRUMS = None                 # derived from TRACKS[2] in main()
FLUTE = {5: "V", 6: "T", 13: "X", 14: "V", 21: "Y", 22: "V",
         26: "Q", 27: "R"}   # step -> note, out of that bar's arp tones

PAL_CLOCK = 985248           # the synth's PAL SID arithmetic
SID_MAX = 16777216
SEMITONE = 1.0595            # deliberately the original's, not 2**(1/12)

BODY = """1 GOTO 100
10 VSYNC
11 F=F+1:IF F=9 THEN F=0:GOSUB 30
12 IF F=1 THEN GOSUB 50
13 IF F=2 THEN GOSUB 70
14 IF D=1 AND V>0 AND M(0)=1 THEN G=G+1:IF G>3 THEN G=0:V=V-1:SOUND 0,P,V,0
15 IF E=1 AND W>0 AND M(1)=1 THEN W=W-3:IF W<0 THEN W=0
16 IF E=1 AND W>0 AND M(1)=1 THEN SOUND 1,Q,W,0
17 IF E=1 AND W=0 AND M(1)=1 THEN SOUND 1,Q,0,0:E=0
18 IF Y>0 AND M(3)=1 THEN Y=Y-3:IF Y<0 THEN Y=0
19 IF Y>0 AND M(3)=1 THEN SOUND 3,J,Y,O
20 IF U>0 AND M(5)=1 THEN U=U-1:SOUND 5,K,U,0
21 T=INKEY:IF T=0 THEN GOTO 10
22 IF T>48 AND T<57 THEN T=T-49:GOSUB 60:GOTO 10
23 IF T>255 THEN GOSUB 80:GOTO 10
24 IF T=32 THEN GOSUB 91:GOTO 10
25 IF T>64 AND T<91 THEN POKE R,T:GOTO 10
26 IF T>96 AND T<123 THEN POKE R,T-32:GOTO 10
27 IF T<>27 THEN GOTO 10
28 FOR I=0 TO 7:SOUND I,100,0,0:NEXT I
29 MODE 0:CURSOR 1:END
30 S=S+1:IF S>31 THEN S=0
31 C=39406+S+S
34 N=PEEK(C)-64:IF N>0 AND M(0)=1 THEN P=Z(N-1):V=10:D=0:SOUND 0,P,V,0
35 IF N<1 THEN D=1
36 N=PEEK(C+160)-64:IF N>0 AND M(1)=1 THEN Q=Z(N+25):W=7:E=0:SOUND 1,Q,7,0
37 IF N<1 THEN E=1:W=7
38 N=PEEK(C+320)-64:IF N>0 AND M(2)=1 THEN SOUND 2,Z(N+51),9,0
39 IF N<1 AND M(2)=1 THEN SOUND 2,100,0,0
45 RETURN
50 N=PEEK(C+800)-64:IF N>0 AND M(5)=1 THEN K=Z(N+77):U=6:SOUND 5,K,6,0
51 N=PEEK(C+640)-64:IF N>0 AND M(4)=1 THEN SOUND 4,Z(N+25),4,0
52 N=PEEK(C+960)-64:IF N>0 AND M(6)=1 THEN SOUND 6,Z(N+25),6,0
53 IF N<1 AND M(6)=1 THEN SOUND 6,100,0,0
54 N=PEEK(C+1120)-64:IF N>0 AND M(7)=1 THEN SOUND 7,Z(N+25),8,0
55 IF N<1 AND M(7)=1 THEN SOUND 7,100,0,0
56 N=PEEK(C+480)-64:IF N=19 AND M(3)=1 THEN Y=11:J=2500:O=1:SOUND 3,2500,11,1
57 IF N=11 AND M(3)=1 THEN Y=11:J=120:O=0:SOUND 3,120,11,0
58 IF N=8 AND M(3)=1 THEN Y=6:J=9000:O=1:SOUND 3,9000,6,1
59 RETURN
60 IF M(T)=1 THEN M(T)=0:POKE 39393+T*160,107:SOUND T,100,0,0:RETURN
61 M(T)=1:POKE 39393+T*160,97:RETURN
70 N=39407+A+A:T=39407+S+S
71 POKE N,110:POKE T,230:POKE N+160,110:POKE T+160,230
72 POKE N+320,110:POKE T+320,230:POKE N+480,110:POKE T+480,230
73 POKE N+640,110:POKE T+640,230:POKE N+800,110:POKE T+800,230
74 POKE N+960,110:POKE T+960,230:POKE N+1120,110:POKE T+1120,230
75 A=S:POKE R+1,22:RETURN
80 POKE R+1,110
81 B=(R-38912)/160:X=(R-38912-B*160)/2
82 IF T=258 THEN X=X-1
83 IF T=259 THEN X=X+1
84 IF T=256 THEN B=B-1
85 IF T=257 THEN B=B+1
86 IF X<7 THEN X=7
87 IF X>38 THEN X=38
88 IF B<3 THEN B=3
89 IF B>10 THEN B=10
90 R=38912+B*160+X+X:POKE R+1,22:RETURN
91 B=(R-38912)/160:X=(R-38912-B*160)/2:X=X-7
92 IF X-X/4*4=0 THEN POKE R,58:RETURN
93 POKE R,32:RETURN
100 MODE 1
101 CLS:CURSOR 0
102 POKE $FF1A,14
104 DIM Z(103):DIM M(7)
105 FOR I=0 TO 103:READ N:Z(I)=N:NEXT I
106 FOR I=0 TO 15
107 READ N:POKE $FF1E,I:POKE $FF1F,N/256:POKE $FF1F,N-N/256*256
108 NEXT I
110 PRINT "  COOL8 SYNTH  1-8 VOICES  ESC QUITS"
111 PRINT
112 PRINT "       %s"
113 PRINT "1 LEAD %s"
114 PRINT "2 ARP  %s"
115 PRINT "3 BASS %s"
116 PRINT "4 DRUM %s"
117 PRINT "5 PAD  %s"
118 PRINT "6 FLUTE%s"
119 PRINT "7 PLUCK%s"
120 PRINT "8 HORN %s"
121 PRINT
122 PRINT "       TYPE IN THE GRID - IT PLAYS IT"
125 FOR R=0 TO 29
126 FOR I=0 TO 39:POKE 38913+R*160+I+I,110:NEXT I
127 NEXT R
133 FOR I=0 TO 7:M(I)=1:POKE 39393+I*160,97:NEXT I
134 C=39406:S=31:A=31:F=0:D=1:E=1:V=0:W=0:Y=0:U=0
135 R=39406:POKE R+1,22
136 GOTO 10
"""


def pitch(note, mask):
    """COOL8 SOUND pitch for letter `note` (1..26) under `mask`"""
    f = 40.0 * (SEMITONE ** (note + mask)) * PAL_CLOCK / SID_MAX
    return int(round(2.0 * f))


def main():
    assert all(len(t) == 32 for t in TRACKS), "a track is not 32 steps"
    drums = "".join("S" if c == " " else " " for c in TRACKS[2])
    # the pad holds each bar's root -- the bass line's own bar-start
    # notes, played soft in the arp's octave
    pad = "".join(TRACKS[2][i] if i % 8 == 0 else " " for i in range(32))
    flute = "".join(FLUTE.get(i, " ") for i in range(32))
    lead = TRACKS[0]
    assert all(lead[i] in " :" for i in FLUTE), "flute clashes the lead"
    # the drone is gone -- awful, by verdict. In its row: the PLUCK,
    # three anticipations on a clean mid square -- the coming bar's
    # root, one step before each chord change, cut by the next beat
    # mark. J into bar 3, F into bar 4, A leading home.
    pluck = {15: TRACKS[2][16], 23: TRACKS[2][24], 31: TRACKS[2][0]}
    drone = "".join(pluck.get(i, " ") for i in range(32))
    for i in pluck:
        assert TRACKS[0][i] in " :" and FLUTE.get(i) is None, i
    horn = "".join(chr((ord(TRACKS[2][i - 4]) - 65 + 7) % 26 + 65)
                   if i % 8 == 4 else " " for i in range(32))

    def beats(t):
        # the original's own convention: a bar mark on every fourth
        # column unless a note sits there
        return "".join(":" if i % 4 == 0 and c == " " else c
                       for i, c in enumerate(t))

    drums, pad, flute = beats(drums), beats(pad), beats(flute)
    drone, horn = beats(drone), beats(horn)
    assert len(drums) == 32 and len(pad) == 32 and len(flute) == 32
    assert len(drone) == 32 and len(horn) == 32
    assert drums.count("S") == 8, "the bass rests moved: %r" % drums
    pitches = []
    for mask in MASKS:
        for note in range(1, 27):
            p = pitch(note, mask)
            assert 0 < p < 65536
            pitches.append(p)

    # the machine's own C64 palette, quantised the way the banks are
    name, _, _, hexes = palette.BANKS[10]
    assert name == "Commodore 64" and len(hexes) == 16
    # q444 takes the 24-bit hex string and returns the packed 12-bit
    # value -- exactly the number PAL_DATA wants, high byte first
    c64 = [palette.q444(h) for h in hexes]

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

    # DATA is numbers only on this machine, so the track strings ride
    # in their PRINT statements -- stated once, painted once, and from
    # then on the screen copy is the only one the player reads
    src = (BODY % (("+---" * 8,) + tuple(TRACKS)
                   + (drums, pad, flute, drone, horn))
           + "\n".join(data(pitches, 200) + data(c64, 240)) + "\n")
    path = os.path.join(ROOT, "demos", "synth.bas")
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    lines = [l for l in src.split("\n") if l.strip()]
    ns = [int(l.split()[0]) for l in lines]
    assert ns == sorted(ns), "line numbers not ascending"
    over = [n for n, l in zip(ns, lines) if len(l) > 79]
    assert not over, "lines over 79 chars: %s" % over
    print("  synth.bas: %d lines" % len(lines))
    for nm, t in [("drums", drums), ("pad", pad), ("flute", flute),
                  ("drone", drone), ("horn", horn)]:
        print("  %-5s %r" % (nm, t))
    print("  -> %s" % path)


if __name__ == "__main__":
    main()
