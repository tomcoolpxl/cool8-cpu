#!/usr/bin/env python3
"""Generate demos/synth.bas -- the c64-synth sequencer, screen as memory.

    python tools/mksynth.py

**The port of tomcoolpxl/c64-synth, and the trick is kept whole: the
screen is the sequencer's memory.** The original reads its notes off
the virtual C64 display -- "what you see is literally what you hear" --
and COOL8 can do it more honestly still, because modes 0/1 are text in
*main* RAM: the play loop PEEKs the same bytes PRINT put there. Mode 1
is the 40-column screen, same map as mode 0, cell = $9800 + row*160 +
col*2, char then attribute.

**The melody, tempo and tuning are the original's, verbatim.**
DEFAULT_TRACKS below are copied exactly; a char is a note by A=1..Z=26,
anything else is a rest, and the `:` marks are rests that draw the
beat. Pitch is the synth's own SID-faithful table -- f(i) = 40 *
1.0595^i * 985248 / 2^24 Hz, per-track octave masks 82/70/46 -- with
its slightly-sharp 1.0595 semitone reproduced deliberately, and COOL8's
register being ~2*Hz the DATA is round(2*f). Tempo: the original steps
every 160 ms (8 PAL frames); this machine is 60 Hz, and the chosen
mapping is **9 frames = 150 ms, slightly faster by decision**.

**Three instruments onto square-and-noise (D41: envelopes are
software).** The lead (triangle there) is a square held while notes
run and released on rests; the arpeggio (square there too) is plucked
with a fast per-frame decay on rests; the bass keeps the original's
best trick -- on a rest **the same voice becomes the snare**, one
noise burst decayed by the frame loop, exactly as bass_snare mode
flips oscillator to noise buffer. Eight voices exist; three play;
rows 4-8 are drawn empty, ready to be filled.
"""
import io
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# src/Config.js DEFAULT_TRACKS, verbatim -- 32 steps, cols 7..38
TRACKS = [
    "Q   :   :   R   Q   :   :   M O ",
    "T VT:RQMO T XVTQ:M YXVTQ:M QRQO ",
    "AM AMA MHT HTH TJV JVJ VFR FRF R",
]
MASKS = [82, 70, 46]         # per-track octave offsets, as shipped

PAL_CLOCK = 985248           # the synth's PAL SID arithmetic
SID_MAX = 16777216
SEMITONE = 1.0595            # deliberately the original's, not 2**(1/12)


def pitch(note, mask):
    """COOL8 SOUND pitch for letter `note` (1..26) under `mask`"""
    f = 40.0 * (SEMITONE ** (note + mask)) * PAL_CLOCK / SID_MAX
    return int(round(2.0 * f))


def main():
    assert all(len(t) == 32 for t in TRACKS), "a track is not 32 steps"
    pitches = []
    for mask in MASKS:
        for note in range(1, 27):
            p = pitch(note, mask)
            assert 0 < p < 65536
            pitches.append(p)
    used = sorted(set(c for t in TRACKS for c in t if c.isalpha()))
    print("  notes used: %s" % "".join(used))

    # Rows: 0 title, 1 blank, 2 ruler, 3-10 eight tracks (3 live),
    # 12 credit. The play loop:
    #   - one step every 9 VSYNCs; the playhead is the attribute byte
    #     of the current column on the three live rows ($19 normal,
    #     $91 lit -- bg/fg swapped)
    #   - lead v0: note holds at 10, rest releases one step every
    #     four frames -- the original's ~0.3 s time-constant tail,
    #     and softer than the arp's pluck the way a triangle is
    #   - arp  v1: note plucks at 9, rest decays 3/frame
    #   - bass v2: note squares at 10; **a rest is the snare** -- the
    #     voice flips to noise at 13 and the frame loop decays it
    body = """1 GOTO 100
10 VSYNC
11 F=F+1:IF F=9 THEN F=0:GOSUB 30
12 IF D=1 AND V>0 THEN G=G+1:IF G>3 THEN G=0:V=V-1:SOUND 0,P,V,0
13 IF E=1 AND W>0 THEN W=W-3:IF W<0 THEN W=0
14 IF E=1 AND W>0 THEN SOUND 1,Q,W,0
15 IF E=1 AND W=0 THEN SOUND 1,Q,0,0:E=0
16 IF B=1 AND X>0 THEN X=X-2:IF X<0 THEN X=0
17 IF B=1 AND X>0 THEN SOUND 2,3000,X,1
18 IF B=1 AND X=0 THEN SOUND 2,3000,0,1:B=0
19 T=INKEY:IF T=0 THEN GOTO 10
20 SOUND 0,0,0,0:SOUND 1,0,0,0:SOUND 2,0,0,0
21 MODE 0
22 CURSOR 1
23 END
30 T=39407+S+S:POKE T,25:POKE T+160,25:POKE T+320,25
31 S=S+1:IF S>31 THEN S=0
32 T=39407+S+S:POKE T,145:POKE T+160,145:POKE T+320,145
33 C=39406+S+S
34 N=PEEK(C)-64:IF N>0 AND N<27 THEN P=Z(N-1):V=10:D=0:G=0:SOUND 0,P,10,0
35 IF N<1 OR N>26 THEN D=1
36 N=PEEK(C+160)-64:IF N>0 AND N<27 THEN Q=Z(N+25):W=9:E=0:SOUND 1,Q,9,0
37 IF N<1 OR N>26 THEN E=1:W=9
38 N=PEEK(C+320)-64:IF N>0 AND N<27 THEN SOUND 2,Z(N+51),10,0:B=0
39 IF N<1 OR N>26 THEN B=1:X=13
40 RETURN
100 MODE 1
101 CLS:CURSOR 0
102 POKE $FF1E,1:POKE $FF1F,3:POKE $FF1F,39
103 POKE $FF1E,9:POKE $FF1F,6:POKE $FF1F,91
104 DIM Z(77)
105 FOR I=0 TO 77:READ N:Z(I)=N:NEXT I
110 PRINT "  COOL8 SYNTH"
111 PRINT
112 PRINT "       %s"
113 PRINT "1 LEAD %s"
114 PRINT "2 ARP  %s"
115 PRINT "3 BASS %s"
116 PRINT "4"
117 PRINT "5"
118 PRINT "6"
119 PRINT "7"
120 PRINT "8"
121 PRINT
122 PRINT "       THE SCREEN IS THE SEQUENCER"
130 FOR I=0 TO 31
131 POKE 39407+I+I,25:POKE 39567+I+I,25:POKE 39727+I+I,25
132 NEXT I
133 S=31:F=0:D=1:E=1:B=1:V=0:W=0:X=0
134 GOTO 10
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

    # DATA is numbers only on this machine, so the track strings ride
    # in their PRINT statements -- stated once, painted once, and from
    # then on the screen copy is the only one the player reads
    src = (body % (("+---" * 8,) + tuple(TRACKS))
           + "\n".join(data(pitches, 200)) + "\n")
    path = os.path.join(ROOT, "demos", "synth.bas")
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    lines = [l for l in src.split("\n") if l.strip()]
    ns = [int(l.split()[0]) for l in lines]
    assert ns == sorted(ns), "line numbers not ascending"
    over = [n for n, l in zip(ns, lines) if len(l) > 79]
    assert not over, "lines over 79 chars: %s" % over
    lo = min(p for p in pitches)
    hi = max(p for p in pitches)
    print("  synth.bas: %d lines; 78 pitches %d-%d; 3 voices; 150 ms a step"
          % (len(lines), lo, hi))
    print("  -> %s" % path)


if __name__ == "__main__":
    main()
