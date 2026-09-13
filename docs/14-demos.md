# 14. The demo disc

A COOL8 ships with sixteen volumes. This document owns what is on them,
what a demo is allowed to assume, and how to add one.

```bash
python tools/mkdemos.py --png
```

## 1. The drives

Sixteen volumes, numbered **0 to 15**, 448 KB each, in one 8 MB flash
image ([`tools/cool8disk.py`](../tools/cool8disk.py)). `DRIVE n` selects
one and everything after it — `DIR`, `SAVE`, `LOAD`, `ERA` — works on
that volume until the next `DRIVE`.

| drive | label | holds |
|---|---|---|
| **0** | `SYSTEM` | **the ROM's**: `BOOT.BIN`, and nothing a user should write |
| **1** | `COOL8` | **where a cold machine comes up** — the user's, empty |
| 2–8 | `COOL8` | the user's, formatted and empty |
| **9** | `MOTT` | **MOTT's**: its program and its theme files, too big for the CoolAction disc; its loader is on 11 ([D108](01-decisions.md)) |
| **10** | **`PICTURES`** | **the picture drive**: the `.PIC` files SLIDES shows, a screen of mode 6 each, and beside each the `.RPL` that changes its palette row by row -- §4, `SLIDES` |
| **11** | **`ACTION`** | **the CoolAction! disc**: every `demos/*.act`, compiled, as a bare `.BIN` — the Demos menu's twin; MOTT's is only its loader |
| **12** | `BAPPLE` | Bad Apple's stream, capped to this one drive — §4 |
| **13** | **`DEMOS`** | **the demo disc**: everything written in BASIC, games included |
| **14** | `SOFTWARE` | the machine-code systems — the four Infocom games and the p-System's loader — each a `.BIN` behind a `.BAS` stub |
| 15 | `PASCAL` | the p-System's own volume: not a menu, reached through `PASCAL` on 14 |

**Three of those are menus, and a menu is a drive.** The emulators —
the web page and the window — read the catalogue `tools/cool8disk.py`
writes, group it by the volume an entry came from, and title each
group from `cool8disk.MENUS`: **Demos** (13), **Software** (14),
**CoolAction** (11). Nothing in either emulator names a program or
knows the disc format; `catalogue()` gained a `kind` per entry so the
launcher knows which of two things to type — `LOAD` and `RUN` for a
`.BAS`, `SYS "NAME.BIN"` for a `.BIN` — and that is the whole of what
they were taught ([D99](01-decisions.md#d99--three-menus-and-a-menu-is-a-drive)).

**The split is by language, not by genre.** If it is written in BASIC
it is a Demo, and TAIPAN and the two COOLTRIS being games does not
move them. Software is what the machine runs natively — the Z-Machine
and the p-System — reached through a small BASIC stub that sets the
drive and `SYS`es into the interpreter; the stub is the menu entry and
the `.BIN` beside it is not listed twice. CoolAction is the compiled
`.BIN` demos, no stub at all. RAINBOW and the other ports therefore
exist twice under one name, on 13 in BASIC and on 11 compiled, and
that is the point: the two menus are how the interpreter and the
compiler get compared on the same picture. COBRA is on both as well,
but as two programs: the compiled one tumbles, every frame computed
([D105](01-decisions.md)).

| menu | drive | programs |
|---|---|---|
| **Demos** | 13 | MAZE, RAINBOW, WAVE, PLASMA, INTRO, BOING, TRIANGLES, MANDEL, COBRA, SYNTH, BENCH, MINIBNCH, BAPPLE, TAIPAN, COOLTRS1, COOLTRS2 |
| **Software** | 14 | HHGG, ZORK1, PLANET, LGOP, PASCAL |
| **CoolAction** | 11 | RAINBOW, TRIANGLE, MAZE, PLASMA, WAVE, MANDEL, SYNTH, INTRO, PRIMES — the compiled twins, §4 — COBRA, which shares only its ship and its name with the BASIC's, COBRA2, its camera and sky, and MSCOOLMN, ARKANOID, BLOCKADE, COOLTRIS, COOLSW, GALAGA, MOTT, KEYTEST and SLIDES, which have no BASIC |

**Volume 0 is not the user's, and that is the ROM's decision.**
`sw/boot.asm` walks volume 0's directory for `BOOT.BIN`; it is the 4 KB
part a board cannot reflash, so no software may move it. BASIC therefore
comes up on **drive 1** (`fsc_init` in [`sw/fscmd.asm`](../sw/fscmd.asm)),
and an unqualified `SAVE` can never land beside the file the machine
boots from. `FSDRV` was never initialised at all before that — it
inherited the zero the cold-start RAM wipe leaves, which is how volume 0
became the default by accident.

**The layout lives in [`tools/cool8disk.py`](../tools/cool8disk.py)** —
`BOOT_VOL`, `USER_VOL`, `DEMO_VOL` and `make_image` — because three
builders need it (`flash.py`, `mkdemos.py`, `sim/test_boot_basic.py`)
and a layout copied into each is a layout that drifts. `poe disk`
formatted volume 0 alone until the default moved, which would have
booted to a machine whose every `DIR` and `SAVE` failed on a disk that
looked fine.

13 for the demos so a demo disc is somewhere a user will not overwrite
by accident on the first afternoon. `CLAIMED` in the same file is the
set of volumes something owns — 0, 1, 10, 11, 13, 14, 15 — and Bad Apple's
planner may not put a chunk on one of them (§4, `BAPPLE`).

## 2. The sources are the truth, the disc is derived

`demos/*.bas` is what gets reviewed. `tools/mkdemos.py` formats the
volumes, **types each source at the machine**, and lets `SAVE` write it.

**The machine tokenises, and that is the whole design.** A program on
disc is tokenised, and the only thing that knows the token table is
`sw/token.asm`. A host-side tokeniser would be a second implementation
of it and would drift the first time a keyword was added — which is the
trap [AGENTS.md](../AGENTS.md) names first and this project has paid for
a dozen times.

**It no longer types, and that is not a retreat from the above.**
`H.line` writes the text where `ed_read` would have left it and enters
`ed_inject` — `ed_enter` without the screen scrape — so every keyword,
number and quote is still turned into tokens by the machine's own
tokeniser. Nothing on the host knows what `PRINT` is worth.

What it skips is the *keyboard*, which was the cost: a round trip a
character, because the PS/2 queue is sixteen deep and a key is two
scancodes, so a line cannot be delivered in one go and the harness
settles after each. **Ninety seconds to put five demos on a disc,
nearly all of it waiting.** One round trip a line instead: measured
**19.6× on a six-line program**, and the stored program came back
byte-for-byte identical, floats included — which is the gate
`sim/test_run.py` keeps rather than a claim made here.

**A host-side tokeniser was approved and then not written, and the
reason is a number.** The case for one was that a disc could be built
with no VM at all -- worth arguing about when typing five demos cost
ninety seconds. `H.line` made that **2.5 seconds**, and the premise
went with it. What it would still cost has not changed: `snum`'s number
packing, the quoted-text and REM passthrough and the record layout,
reimplemented, with two versions that must agree forever. The rules are
not obvious ones -- a line over eighty characters does not store, `READ`
takes scalar targets only, a five-digit float literal does not survive
the parser, and [D88] floors on the way into an integer -- and every one
is somewhere a second implementation drifts silently. **Reopen it only
if the 2.5 s becomes the problem**, which is a different argument from
the one that was approved.

**The keyboard is still proven, deliberately.** Typing every character
was the only thing exercising the real driver end to end — the PS/2
ISR, `sw/keymap.asm`, the editor's per-key handling — and it did so as
a *side effect* of building a disc. A side effect can vanish without
anyone noticing, so it is a named case in `sim/test_run.py` now.

So a demo is edited as text, rebuilt, and never patched as a binary.

## 3. What a demo may assume

**Nothing that needs the toolchain.** Demos are built and run on the VM
(`python tools/mkdemos.py --png` renders a frame), because a question
about software is a question for the fast machine — the RTL is for
questions about the hardware.

**BASIC only.** A demo that needs machine code should ship it as a PRG
and reach it with `SYS "NAME.BIN"` ([D87]), so the BASIC stays readable.

**The palette is in the bitstream** ([D77], [D79]) — sixteen banks of
sixteen, published palettes, live from reset. A demo does not seed a
palette and must not assume it may scribble on one without saying so.

## 4. The demos

### `MAZE` — after the C64 one-liner

```
10 PRINT CHR$(205.5+RND(1)); : GOTO 10
```

is the most famous BASIC program written, and has a
[book](https://mitpress.mit.edu/9780262526746/10-print-chr205-5rnd1-goto-10/)
about it. It works because PETSCII 205 and 206 are the two diagonals,
and `RND` picks between them.

![MAZE](img/demo-maze.png)

**Forty columns, because the cell has to be square.** Mode 0's 80×30
cells are 8 wide by 16 high, so a diagonal drawn in one is not at 45°
and the maze comes out sheared. Forty columns makes the cell 16×16.

**It is tile mode, and that is not a preference.** The text version was
written first, in mode 1, drawing CP437's `/` and `\` at 47 and 92 with
`47 + 45*RND(2)` standing in for `205.5 + RND(1)`. It was wrong on the
screen: **those glyphs have side bearing.** They stop short of the cell
edge, so every join in the maze is broken and the picture is a field of
dashes. The text font is 4 KB of EBR read by the hardware — ROM, not
redefinable — so there is no fixing it in mode 1. Mode 2 is the same
40×30 geometry with the pattern in RAM, which is the whole difference.

**The tile is C64 screen code 77, pixel for pixel.** Transcribed from
the character ROM rather than drawn by hand, and drawing it by hand got
it wrong twice: the real glyph is two and three pixels wide, not one,
and it reaches both corners. Code 78 is its exact horizontal mirror —
checked, not assumed — so **attribute bit 6 draws the other diagonal and
one 32-byte tile serves both**, which is why the `DATA` is four lines
and not eight.

**The scroll is the hardware's, and nothing moves in memory.** The tile
map is a ring 32 rows tall with 30 shown (§5.5), so `VID_SCY` steps the
eight pixels inside a tile and one stride onto `VID_BASE` steps the row
— wrapped back into the ring with a compare and subtract, because
software wraps the base and the hardware only wraps its own row pointer
within it. The demo draws the row it is *about to need* and then scrolls
onto it. **A fine scroll makes the window touch 31 rows, not 30**, so of
a 32-row ring exactly one row is off screen and only that one is safe to
draw into: the fill is 32, and 31 would build every new row in the
part-shown row along the bottom edge, in view.

`MODE 2` leaves `VID_BASE` at 0 and `VID_STRIDE` at 128 — asked, not
assumed, and the demo reads the stride rather than writing 128 down.

**It is paced on `VID_IRQ`'s vblank flag** — write 1 to clear, then wait
for it, which is one frame unambiguously. `VID_RASTER` cannot do this:
it is bits 7:0 of a line count that runs past 255, so the same value
comes round twice a frame and BASIC cannot tell which. **The coarse step
goes with fine step 0**, because `VID_BASE` and the tile row offset are
both sampled at frame start; pair the base with step 7 instead and one
frame shows a row and seven pixels at once and the next comes back,
which reads as a shudder.

**The palette is the C64's, copied.** Bank 0 is overwritten entry for
entry from a `DATA` table of RGB444 pairs, so 6 is `#0000AA` and 14 is
`#0088FF` — the same numbers a C64 program means when it says 6 and 14
([`tools/palette.py`](../tools/palette.py) bank 10 is the same set, kept
in the C64's own index order for the same reason). The tile is drawn in
those two indices directly: paper 6, ink 14.

### `RAINBOW` — a bouncing line with a fifteen-line trail

![RAINBOW](img/demo-rainbow.png)

Two endpoints bounce independently around mode 4's 320×240, and a ring
buffer of fifteen holds the older lines so the trail can be erased
oldest-first. The colour is the ring slot, so the trail walks the whole
palette as it goes.

**It is a demonstration of `VSYNC` more than of `LINE`.** The loop draws
one line, erases one line and waits for the frame — so it runs at
exactly 60 Hz because the hardware says when, not because the work
happens to take that long.

**`PALETTE` was a statement once and is not any more**;
[13-basic.md](13-basic.md) lists what went and what replaces it. This demo was
written before it went, and porting it was the whole of the change:
`PALETTE i, v` is `PAL_IDX` then `PAL_DATA` twice, **high byte first**,
which is what the `DATA` pairs are. Everything else it uses — `CLG`,
`LINE`, `VSYNC`, `DO`/`LOOP`, `DIM` and arrays — still works unchanged.

### `BENCH` — the Rugg/Feldman benchmarks

![BENCH](img/demo-bench.png)

BM1–BM8 as published (Kilobaud, June 1977; BM8 is John Coll's, *Personal
Computer World*, February 1978), then a table against the machines they
were written for. **The listings inside the timing are unchanged** — the
repeat loop is outside them, and `IF K<1000 THEN GOTO 500` is the one
edit, which this BASIC requires.

**It reports an index, not seconds: COOL8 at 1 MHz is 100**, and lower
is faster. Seconds invite a comparison the clocks do not support — this
machine runs at 8.375 MHz against a table of 1–2 MHz ones — so the
baseline is COOL8 scaled to 1 MHz and every column is a ratio against
it, in whole numbers. `CPU` and `MHZ` are their own columns, because the
clock is most of the answer and burying it in the name hides that.

**BM5–BM7 used to be the weak columns, and the benchmark is what found
out why.** Against a C64 they sat at 141, 149 and 164 while the pure
arithmetic loops were at 360 and 436 — the three that call a subroutine
scoring worst is not a coincidence, it is a signature. The cause was
`prg_find`'s memo having one slot: the inner loop is `GOSUB 2` then
`GOTO <head>`, two targets at opposite ends of the program, so they
evicted each other every pass and every jump walked from `PROGBOT`
again. A second slot ([`sw/prog.asm`](../sw/prog.asm)) cost 48 bytes and
bought **2.6× on BM5, 2.3× on BM6, 1.8× on BM7**; the C64 columns are
now 360, 346 and 299, in line with the rest. **BM1–BM4 came back
byte-identical**, which is the control that says nothing else moved.

**One significant figure on these, because the demo is timed in
frames.** Three runs are averaged against a 16.7 ms tick, and two
consecutive builds of the same binary gave BM5 as 360 and 386 — about
7 % apart. The isolated measurement below is the tighter one, and the
`poe bench` table in [13-basic.md](13-basic.md) is tighter still because
it counts cycles rather than frames.

Isolated, the loop is 104 frames against 31 for the same loop with the
`GOSUB` removed; after the second slot it is 39. The call itself was
never expensive — 8 frames — and the other 65 were the eviction.

**`4.1875` does not survive the parser** — five significant digits
against a float that carries about four, and the whole row came out
negative. The 2 MHz row is `8.375/2`, which is the clock the machine
actually runs at and four digits.

**Ten of the figures come from one table** and are comparable with each
other. The **IBM PC** (8088 at 4.77 MHz) is *MikroDatorn*'s 1982 run of
the same benchmarks, noted on screen as a different source — its VIC-20
row matches the other table exactly, which is the reason for trusting it
beside them. MSX, Amstrad/Schneider CPC and TRS-80 are in neither and
are left out rather than filled in from a third stopwatch.

**What it took to write says more about the BASIC than the times do:**

- **Variable names are one letter.** `SL` and `SM` are both `S`; `RP` is
  `R`, which was the repeat count, so the loop overwrote its own bound.
- **The suffix picks the type and none means integer** (§`DIM`). `DIM
  T(8)` truncated every measurement to whole seconds; it is `T#(8)`.
  `V/10` is integer division for the same reason — `V*0.1` is not.
- **`READ` will not take a float from `DATA`**, so the published figures
  are stored as tenths.
- **A 24-bit frame count does not fit the float** — four significant
  digits — so the timer differences the two low bytes, each exact, which
  still spans eighteen minutes.
- **BM1 finishes in under one frame.** A thousand `FOR` iterations is
  ~12 ms against a 16.7 ms tick, so each benchmark runs three times and
  is averaged.
- **A source line over 80 characters is not a stored line.** The header
  row was 87 with `1040 PRINT "` on the front, so the editor never kept
  it and the table printed with no column names — silently, because a
  line that does not store cannot fail at run time. Both header rows are
  split now.
- **`4.1875` does not survive the parser** — five significant digits
  against about four — and the row it scaled came out *negative*. The
  2 MHz row is `8.375/2`.

### `MANDEL` — the set, in fixed point

![MANDEL](img/demo-mandel.png)

Mode 6, the only mode that sees all 256 palette entries at once, with a
gradient built as four ramps and entry 0 forced black for the interior.

**It is integer arithmetic, and that is the whole reason it finishes.**
A float operation on this machine costs about five times an integer one
(BM3 in `BENCH` is integer — that is easy to misread), so the iteration
runs in **Q6 fixed point**: 64 units to 1.0, which is the largest scale
whose products still fit a signed 16-bit word. `zx*zy` peaks at 16,384;
at Q7 it would reach 65,536 and overflow.

Two details that are not optional:

- **`A*B/32`, not `2*A*B/64`.** Same value; the doubled form peaks at
  32,768 and overflows a signed word by exactly one.
- **The escape is tested *before* squaring.** A value that has just
  escaped can be four times the bound, and squaring it overflows — so
  the test is `|zx|>2 or |zy|>2` and the squares are skipped on the way
  out. That is a square escape boundary rather than a circular one,
  which is the standard fixed-point trade.

**Mariani-Silver does the rest.** The set is connected, so a rectangle
whose border is one colour is that colour throughout: fill it and
compute nothing inside. Filling is one `POKE` a pixel against sixty-four
iterations of arithmetic, so *not* computing a region is worth hundreds
of times its area. The stack is four arrays and an index rather than
recursion — no `CALL` frame per rectangle, no 32-deep limit — and the
contour bands in the picture are those rectangles.

**The symmetric pixel is written at the same time**, not in a second
pass: the value is already in hand, so the mirror costs four more
`POKE`s and saves reading 30,720 bytes back.

**The flat band on the left was the left edge, not the zoom, and it
took two goes to say so.** Every column with x < −2 escapes on the
*first* iteration — `A` is `X` after one pass, and the test fires at
`A < −128` — so it comes out one colour, and a run of such columns is a
flat vertical band. The first attempt narrowed the *step* (2 units to
1.5), which took the band from 25% to 8.6% and looked like progress:
thinner columns, so fewer of them outside the set. But the left edge
stayed at −2.25, a quarter-unit left of the set's leftmost point, so
eleven columns of 128 still escaped at once. **Narrowing a view does
not move its edge.**

The edge is −2.00 now and the step is `I*5/4`, which is 2.47 across by
2.34 down: **no column escapes on the first iteration**, and the set
fills 91% of the width instead of 76%. Both axes use the same Q6 step,
so the pixels stay square. The colour count went 50 to 53 — finer
sampling finds more escape counts.

**Why it is not 256 colours.** The distinct colour count is bounded by
the iteration cap, not by the palette: 64 iterations can produce at most
64 values. Raising the cap to 128 gained one — this view simply does not
contain many high escape counts. More colour needs a zoom or continuous
colouring, not a bigger number.

### `WAVE` — a sine sweep with a gradient trail

![WAVE](img/demo-wave.png)

A full-width horizontal line sweeps a sine over mode 6's 256x240, 4 s
a lap, and **every row it vacates takes the next of 253 palette
entries, wrapping** -- lines and colours step in lockstep, nothing
skipped. Entry 0 is the black border, 255 the white head, 254 parked
at black so a stray index shows background, 1..253 the ramp. The trail
is the whole screen, and it drifts: `python tools/mkwave.py`
regenerates the program and the palette as one design, and
`sim/test_run.py`'s `wave_lockstep` case is the gate on all of it.

**Why 253 is the right modulus and not just what was left.** A sweep
paints 478 lines -- 239 down, 239 up -- and gcd(478, 253) = 1, 11*23
against 2*239. So the row-to-colour alignment precesses through every
one of the 253 phases, every row shows every colour over about
seventeen minutes, and nothing is structurally skipped. 254 would
share a factor 2 with 478 and lock half the alignments out forever.

**Not all 253 are on screen at an instant, and that is arithmetic, not
a fault.** A row's colour is its *last* paint, and the last paints on
screen span a 478-value window folded into 253: measured, **127 to
~200 distinct at any moment**, every entry back within a sweep. The
alternative was tried and is written down here: locking colour to row
gives 240 distinct always -- and a picture in which nothing moves.
Those are the same variable; the cycling was chosen with eyes open.

**Draw order is the flicker fix, and vblank is the budget.** The head
was once drawn last, after up to four fill spans (~2.7 ms), and vblank
is ~1.4 ms: at the top of the screen the raster reached the head's row
before the white was down, so the head flickered there and was steady
at the bottom, where the raster arrives 13 ms later. The two spans
that matter -- recolouring the vacated row, then the new head -- now
go first and fit inside vblank; the fill rows follow while the raster
scans. The residue is a one-frame mosaic near the head, and it is the
next lesson.

**`fb()` is the composed frame, not the VRAM.** The scanline renderer
shows the frame as the raster scanned it, which is its whole point --
and near the head the two disagree by design, because the fills land a
few ms into the scan, after the raster has passed the top rows. The
lockstep gate read `fb()` first and reported that mosaic as a sync
break: three pairs in sixty samples, always within two rows of the
head, stale values with no pattern. They were true of the display and
false of the program. **The program's contract is checked in VRAM** --
a mode-6 byte *is* the palette index -- where away from the head the
screen must be two arithmetic chains, +1 per row below descent, -1
under ascent; the head is checked on `fb()`, where there must be
exactly one white row. Sampling is `run(until=h_vsync.vw)`, the
interpreter parked in the VSYNC wait, where the iteration's painting
is complete by definition -- a frame boundary catches the demo
mid-redraw, and a fixed cycle offset is the same mistake with a magic
number.

**Two different black gaps, and only one was a bug.** The sine mirror
was `240-S`, so the table spanned rows 1-239 and **row 0 was never
painted at all** -- a permanent black line along the top, by
construction. It is `239-S` now and 0-239 is covered. The other was
fill exposure -- a vacated row showing background until its turn --
and it died when the vacate moved inside vblank: the gate measures 0
black rows inside the picture and one white head on every sample.

**The ramp is one turn of the hue circle, and it must close.** The
counter wraps, so entry 253 is entry 1's neighbour in time and on
screen; the loop closes at 2 clicks. 253 distinct colours a click or
two apart is more movement than a hue circle supplies -- **six edges
of fifteen, 90 clicks** -- and the rest is spent as deviation from the
ideal circle. Which deviation was the shadow-band lesson:
nearest-by-distance takes inward neighbours as readily as outward, and
a red dropped 15->14 costs 0.299 of perceived luminance where a green
costs 0.587, so rows came out darker than their neighbours at the
253/90 beat, reading as grey rules down the screen. Charging **4
clicks of hue error per click of brightness error** -- the measured
knee; luminance-only wanders 2.71 clicks off the circle and
desaturates -- prices them out: mean deviation 1.23 of a click, max
2.43, steps 112 single and 141 double with none above two, duplicates
asserted at zero. The blue quarter stays the darkest part, luminance
1.6 against the yellows' 13.4: that is what a saturated spectrum is,
and flattening it costs the saturation that makes it a rainbow.

**A horizontal span really is cheaper than a vertical one, and the
reason is in the hardware.** `PIX_DATA` auto-increments X (§5.7), so a
horizontal run is one store a pixel while a vertical one has to rewrite
X and Y for every pixel — three. Measured from BASIC, twenty spans of
192 pixels: **27 frames horizontal against 88 vertical, 3.3×**. `HLINE`
was a keyword once and this is what replaced it.

**And it does not matter, because hand-poking is the wrong primitive.**
The first version drew its spans that way — 512 `POKE`s a frame — and
ran at **four iterations a second**. The profile says why: `h_poke` was
**3.9 %** of the clocks and `prim`/`stmt`/`erel`/`eval` were **64 %**.
BASIC was not storing pixels, it was *parsing statements about* storing
pixels, and the direction of the span is noise beside that. `LINE` is
Bresenham in machine code, one statement for the whole span: the same
512 pixels a frame, **60 Hz, `VSYNC`-paced**. The lesson generalises —
in this BASIC the cost of a loop is the statements in it, so the win is
never a cheaper store, it is a primitive that stores without being
asked again.

**Palette entry 0 is the border.** Starting the ramp at 0 turned the
whole overscan electric blue, which is not a bug in the demo so much as
a fact about the video path worth writing down: entry 0 is the
background *and* the frame around it.

**This demo overwrites all 256 palette entries**, which §3 says a demo
may not do quietly.

**The tables are `DATA`, computed by `tools/mkwave.py`.** 181 sine
values for the first quarter, mirrored three ways at run time —
`S(360-i)`, `239-S(360+i)`, `239-S(720-i)` — which is integer work and
therefore safe, and 253 packed palette words. `DATA` rather than a
`SIN` loop because **a float assigned to an integer variable floored
nothing before D88 existed** ([13-basic.md §8](13-basic.md)):
`S(I) = 120 + 110*SIN(...)` stored -6654 where 230 belongs, silently,
while `PRINT` of the same expression was correct. This demo shipped
once with a sine table that was not a sine and looked plausible enough
on screen that only counting the rows caught it. Note also that `READ`
takes scalar targets only, so it is `READ V` then `S(I) = V`;
`READ S(I)` is `?INDEX`.

### `COBRA` — Elite's ship, hidden lines removed, on the double buffer

![COBRA](img/demo-cobra.png)

**The model is the published one.** 28 vertices, 38 edges, 13 faces and
the edge-to-face table of the Cobra Mk III, transcribed by
`tools/mk3d.py` from the annotated BBC Elite source at
[bbcelite.com](https://elite.bbcelite.com/6502sp/main/variable/ship_cobra_mk_3.html).
The generator asserts the counts against what the source states and
emits `DATA`; no importer, no conversion step on the machine.

**The tilt is baked, the spin is runtime, and the order is the trick.**
The host rotates the ship 20° about X once; BASIC spins it about the
*view's* vertical axis — `RotY` after the tilt — and a Y rotation never
touches y, so each vertex's screen Y is one constant and only screen X
moves. Startup fills 72 frames × 28 vertices of screen X and unpacks
each frame's visible edges into flat endpoint arrays, all integer, the
worst product asserted at 23,495 of a signed 16-bit's 32,767.

**There was a see-through wireframe mode, and it was eliminated by
decision** — the hidden-line ship is simply better, and one mode is
one code path. Its lessons stayed: the profile that shaped this loop
(`python sim/test_run.py --profile cobra`) measured the wireframe's
frame at **31.5 % `CLG`, ~15 % nested-subscript machinery, ~13 %
drawing**, which is why this demo erases by redrawing the
two-flips-old frame's edges in black instead of clearing 24,576 bytes,
and why every `LINE` argument is a single-subscript array read. Two
`CLG`s at start cover pages never yet drawn.

**Visibility is decided by the projected polygon, not the published
normal.** Elite's normals are hand-rounded integers — `(0,62,31)` is
near its face's plane, not on it — so a normal-based cull flipped a few
degrees away from where the *drawn* geometry turns edge-on, and edges
vanished while their faces were still visibly open. The generator
walks each face's boundary loop out of the edge table (spurs like the
laser line pruned), calibrates its winding once against the published
normal far from the silhouette, and then decides every frame by the
**signed area of the face under the exact integer projection the
machine draws**, with a 150 px² grace margin so a closing face holds
through the transition. The revolution is asserted flicker-free — no
edge visible, gone one frame, visible again. Cost, measured: 24.6
edges a frame mean against the normal cull's 23.6, worst 33 against
32 — **accuracy priced at about one `LINE` a frame**, which was the
constraint set for it: all of this runs in the generator, and the
machine only ever `READ`s shorter or equal lists.

**First user of mode 5's double buffer, and it shipped wrong twice** —
worth keeping because both claims sounded right. The first cut flipped
`VID_BASE` alone and called the viewer safe; false — the fetch
re-latches the base every frame start and a drawn frame takes several,
so the display followed the page under construction and the `CLG` was
a visible black frame between ships. [D92](01-decisions.md) split the
glass from the pencil: `VID_DBASE_H` names the page the display scans,
`VID_BASE` steers only the drawing. The second cut flipped both with
two `POKE`s after `VSYNC`, and that was a frame wrong: the fetch takes
`DBASE` at the frame start, on the pulse that ticks the counter
`VSYNC` waits for, so a `DBASE` written after `VSYNC` reached the glass
a frame late — and `BASE`, moved to the old page in the same line, had
the erase begin on the page being shown. Measured on the glass, **at 9
flips of 9 the first frame after the flip was the old page mid-erase**:
on one, 452 of the new page's 621 pixels were missing, and all 348 lit
pixels it does not hold were the page before's. One display frame in
four or five showed the outgoing pose with lines already erased, where
the new one belonged. The flip is now `POKE $FF30,P:VSYNC`, then
`POKE $FF13` to the other page — the order [D105](01-decisions.md)
amended D92 to after the compiled COBRA found the same fault.

**Measured: 4.5 display frames a drawn frame (4–5), ~13 fps, and every
frame on the glass is a finished page.** `sim/test_run.py`'s
`cobra_flips` holds it on the rendered frame, not on the registers. It
finds each flip exactly — parked in the `VSYNC` wait the page is done,
and the next `stmt` is `VSYNC` returning, just past the frame start
that latched the display base — and requires the first two frames
scanned after the flip, and the last before the next one, to be the
finished page pixel for pixel, 396–647 pixels a ship. **The probe it
replaced read `VID_DBASE_H` and `VID_BASE_H` every frame and passed
with the flip in the wrong order**: the registers read a page apart
either way, and a register is not the glass. Registers are still read
through `bus.read()` — `bus.mem[]` is the RAM *under* the I/O page, the
mistake `cool8_soc_tb`'s "the page wins" section exists to catch.
**The recorded next lever is the interpreter's, not the demo's**: name
lookup (`nentry`, `nlook.*`, `varidx`, `aelem`) is ~36 % of a frame,
and a `nlook` memo in `prg_find`'s two-slot shape is the candidate.

**The compiled COBRA is a different program** since
[D105](01-decisions.md): the same ship, tumbling on three axes, every
frame computed at 60 Hz -- its section is with the CoolAction menu's.

### `SYNTH` — the screen is the sequencer

![SYNTH](img/demo-synth.png)

**A port of [tomcoolpxl/c64-synth](https://tomcoolpxl.github.io/c64-synth/),
its trick kept whole: the sequencer has no note array — it reads the
characters on the screen.** The original PEEKs its virtual C64 display
("what you see is literally what you hear"); COOL8 does it natively,
because modes 0/1 are text in *main* RAM — the play loop `PEEK`s the
very bytes `PRINT` painted, through the map at `VID_BASE`. Mode 1 is
the 40-column screen; a char is a note by A=1..Z=26, anything else a
rest, `:` a rest that draws the beat.

**Melody, tuning and instruments are the original's.** The three
DEFAULT_TRACKS ride verbatim in their `PRINT` statements (`DATA` is
numbers-only here — the first cut tried `READ A$` and learned it at
`?SYNTAX`); pitch is the synth's own SID arithmetic, f = 40 · 1.0595^
(note+mask) · 985248/2²⁴ Hz with masks 82/70/46, its slightly-sharp
1.0595 semitone reproduced deliberately, precomputed to `DATA` as
COOL8's ~2·Hz register values. Tempo: the original's 160 ms step is
9.6 frames at 60 Hz; **9 frames — 150 ms, slightly faster — by
decision.**

**Seven voices, an editor, and one percussion line** — keys 1–8
toggle voices live (the digit lights or dims), **arrows move a cursor
in the grid, letters and space type straight into the memory the
sequencer plays**, Esc quits. There were briefly two percussion lines:
the bass row's invisible rest-snare (the original's `bass_snare` flip)
plus a new drum row — so the flip is gone and **the drum row IS that
percussion made visible**, derived by the generator from the bass
track's own rests, one S per bar off-beat. K (kick) and H (hat) decode
too, waiting to be typed. The pad, row 5, holds each bar's root —
also derived, the bass line's own bar-start notes, soft and sustained.
**All eight voices are visible, editable rows now.** The bass was
checked against the source: its instant cut on rests matches the
original's zeroed oscillator, the snare split off correctly, and the
one thing out of reach is the sawtooth itself -- square is the only
tone this chip has. What was off was balance, now the original's own
ratios (lead .35 / bass .3 / arp .2 mapped to 10/9/7). The drone is
gone -- awful, by verdict -- and its row holds the **pluck**: three
anticipations on a clean mid square — the coming bar's root one step
before each chord change, cut by the next beat mark. J into bar 3, F
into bar 4, A leading home. Row 8 is the **horn**: brassy mid-register stabs of each bar
root's fifth on the bar mid-beats, derived by lettering seven
semitones up the bass line. **Space types the bar mark**: on a beat
column (every fourth, the original's own convention) it writes `:`,
elsewhere a plain rest, and every generated row carries its beat marks
the same way. One bug worth its ink: the first F=1 ran before any
step had set `C`, so the fx voices PEEKed the program's own token
bytes as notes and one indexed the pitch table out of range --
surfacing as `?SYNTAX` over the `?INDEX`, the interplay
`sw/interp.asm` documents. `C` is initialised now; the old version had
merely been lucky about which bytes its offsets hit.

Row 6 is the **flute** — fleeting high two-note sparkles placed in
the lead's rest gaps, each drawn from that bar's own arpeggio tones,
played an octave above the lead at low volume with a fast fade, which
is what makes a square wave stop being a buzzer. The bass drone keeps
voice 7; 8 is spare. Typing accepts lowercase and upcases it — the
first field report was "i cannot type letters", because the gate had
only ever typed a *shifted* C while a real keypress arrives unshifted.

**The whole screen is C64 colours**: all sixteen of bank 0's slots
repainted with the machine's own Commodore 64 palette, border light
blue via `VID_BORDER`, light-blue-on-blue attributes, the playhead an
inverted column moved pairwise, the cursor a white cell.

**The step is staged across three frames, and the gate is why.** All
the work on one frame overran 16.7 ms and the tempo gate caught it —
one frame per step showed the playhead restored but not yet lit. Now
F=0 reads the melodic rows, F=1 the echoes, drone and drums, F=2 moves
the playhead; every frame stays inside the budget it must share with
eleven envelope statements.

**Gate-enforced** (`synth_screen`): mode 1; rows 3–5, columns 7–38
hold the c64-synth tracks byte for byte; exactly one lit column per
frame; the playhead steps every 9 frames and walks the 32 columns in
order — which is also the proof the whole loop runs, `SOUND`s
included, since any BASIC error stops it. The gate reads through
`VID_BASE`, having first been written with a computed screen address
and caught by the scroll — the exact mistake the rule exists for.

### `PLASMA` — paint once, animate only the palette

![PLASMA](img/demo-plasma.png)

**The pixels never move.** Mode 6 is painted once with a fixed
interference field and the animation is palette rotation — the colour
under every pixel slides along a 47-entry cyclic rainbow while VRAM
stays byte-for-byte still. It is WAVE's palette lesson run backwards,
and the suite holds it literally: the VRAM byte at a sampled point
must not change between frames while the rendered colour of the same
pixel must.

**The field is separable — colour(x,y) = A(x)+G(y) — and that is what
makes it paintable.** Two integer interference tables (two sine voices
each, host-computed, `DATA`), summing to 1..46, so the paint loop is
one statement a pixel through `PIX_DATA`'s auto-increment: ~25 s of
visible top-down fill that is its own progress bar, MANDEL-class and
in bounds. A non-separable field at this interpreter's speed would be
minutes. The gate checks the painted VRAM against the stored `DATA`'s
own sums.

**47 colours, and why not 240**: rotating a palette costs two
`PAL_DATA` pokes an entry, so a 240-entry rotation is a third of a
second — 3 fps. 47 stream in ~90 ms through the port's auto-increment,
which paced by `VSYNC` is the slow oily flow plasma wants. The wrap
costs nothing: the palette arrays are emitted doubled, `H(O+I)`, so
the inner loop carries no `IF` — an `IF` that skips its `NEXT` being
the classic trap. Regenerated by `python tools/mkplasma.py`; any key
exits.

### `INTRO` — the scroller, hardware doing the work

![INTRO](img/demo-intro.png)

**The motion costs four POKEs a frame.** Mode 1 stores 80 columns and
shows 40, so the display is a window on a wider banner: fine scroll
walks the 8 logical pixels of a cell (`VID_SCRL_X` — [D93], the drift
this demo caught: §5.5 documented text fine-X while the silicon passed
text through unmoved), and the coarse step is a two-byte `VID_BASE`
slide. Every row is written 40-column periodic — halves identical,
gate-checked byte for byte — so when the window has slid 40 cells the
base snaps home invisibly: an infinite scroll with zero redrawing. The
whole screen bobs on `VID_SCRL_Y`'s sine, the border flashes white on
every snare, and the message letters carry a static rainbow of
attributes.

**It shuddered once every eight frames, and the port is what found
it.** The banner stepped left two pixels a frame, then on the frame
where the fine step wrapped to 0 it jumped a whole cell to the right
and came back the frame after — "some of the text is shifted", seen
on the glass and not by any gate. Measured on the renderer by writing
the demo's register pair by hand at the frame boundary and reading a
glyph's x back: −2, −2, … +14, −18, −2. The cause is in
[04-system.md §5.5](04-system.md): text fine scroll is live while
`VID_BASE` is latched at vblank, so a fine step and a base written
together after the frame wait land a frame apart, and the tile idiom
of "coarse step with fine step 0" is exactly wrong for text. The base
is now written a frame ahead, in the BASIC and in `intro.act` alike,
and the pair gate holds the two to the same registers on the same
frame.

**The music is SYNTH's top three voices, verbatim** — lead, arpeggio,
bass-with-snare, same pitch tables and envelopes, 9 frames a step —
with the tracks carried as arrays: this screen belongs to the
scroller, and SYNTH keeps the screen-as-sequencer trick where it means
something.

**The gate is D93's end-to-end proof**: rows periodic, SCX walking
exactly the eight fine positions, even-byte base steps, SCY moving,
and — the line that failed until the fetch, the renderer, the
testbench model and the harness all agreed — **the rendered glyphs
actually sliding across frames**. The way there found the harness bug
worth the trip: suite machines rendered text with no font, so glyphs
had never lit in `fb()` and a cursor toggle looked like a display
kill. Every rendering machine loads the real font now.

### `BOING` — the Amiga's ball, and not one pixel redrawn

![BOING](img/demo-boing.png)

The 1984 Boing demo, in BASIC, at 60 Hz. A 96-pixel checkered ball on a
256-pixel screen, a shadow behind it, and a purple room — and the loop
that runs it is **four `POKE`s a frame**.

**Nothing is redrawn, because nothing can be.** A ball this size is
about 7,000 pixels; the interpreter manages ~12,000 statements a second
(`MINIBNCH`), so any per-frame blit from BASIC is a slideshow before it
starts. So the ball, its shadow and the room are painted **once** into a
416×288 canvas — 1.6 s, all of it horizontal `LINE` spans — and the
display's 256×192 window is then walked over that canvas:

| axis | register | step |
|---|---|---|
| x | `VID_SCX` | a bitmap gets the full ten bits of fine scroll for nothing (§5.5), so one logical pixel |
| y | `VID_BASE` | one row is one pixel, and a row is what the base must move in |

Mode 5 rather than mode 4 for the room it leaves: the viewport is
256×192, so 416×288 of VRAM buys **160 pixels of travel across and 96
down**, and the ball is placed so it touches all four edges at the ends
of both. The `sim/test_run.py` gate is exact about the claim — every
byte of VRAM must be **identical** before and after the flight while the
ball crosses the glass.

**The room stands still because the window steps a whole cell.** The
window carries the room with it, so the grid has to be invariant under
the step: it repeats every 8 pixels and the window moves in eights. The
price is an 8-pixel quantum, and it is bought back in the *timing* —
the flight is integrated in sixteenths of a pixel and snapped to eight
only at the `POKE`, so gravity is where the eye reads it: the ball hangs
at the top of the arc and flies at the floor. The gate holds the grid by
its lattice phase rather than its position, because the ball occludes
part of every row it crosses.

**The spin is the palette, which is how the original did it too.** Eight
entries carry the checks — the index encodes the meridian mod 4 and the
band's parity — and rotating them walks the pattern round the ball in
four phases for 24 `POKE`s. The meridians themselves are cosine-spaced,
so they crowd at the edge the way a sphere's do, and the rotation reads
as a sphere turning rather than a flag waving.

**One trap worth the writing down: a subroutine's loop counter is a
global.** The palette routine counted `FOR P = 0 TO 7` while `P` was the
ball's x position, and every third frame the ball was quietly reset to
the left wall — which looks exactly like a physics bug and is not one.
`LOCAL` exists only inside a `SUB` ([13-basic.md §1](13-basic.md)); a
`GOSUB` shares the whole namespace, and in this BASIC that namespace is
26 letters.

### `TRIANGLES` — the BBC Micro's filled triangles, without the primitive

![TRIANGLES](img/demo-triangle.png)

```
MODE 2:REPEAT:GCOL 0,RND(16)-1
MOVE RND(1280),RND(1024):MOVE RND(1280),RND(1024)
PLOT 85,RND(1280),RND(1024):UNTIL FALSE
```

is the demo every BBC Micro and every Agon runs first. `PLOT 85` is a
filled triangle in the OS; this machine has no such primitive, so the
fill *is* the program — sort the three points by Y, walk two edges down
the shape, and join them with one horizontal `LINE` a row. Mode 4, so
the 16 colours the original asks for, over the whole 320×240.

**Horizontal is the entire performance argument.** A flat `LINE` sets
the pixel port once and lets it step X itself — 22 cycles a pixel
against Bresenham's 209 ([D89](01-decisions.md), and
[13-basic.md §5](13-basic.md)) — so the shape is chosen to be drawn in
spans, and the only thing that happens per *pixel* is machine code. The
edges step in sixteenths of a pixel, which buys one divide an edge
instead of one a row.

**`>>` is a logical shift here** ([13-basic.md §2](13-basic.md)), so an
accumulator that ever went negative would come back as 32000-odd and
`LINE` would write far outside the 38,400-byte surface — over the
`GTEXT` font, among other things. It cannot, because it interpolates
between two on-screen points; `sim/test_run.py`'s `triangles_fill`
holds every byte of VRAM above the surface against what it was before
`RUN` rather than taking the argument's word for it.

**Measured: 11.2 triangles a second, 5.4 display frames each.** The
profile says where that goes — `python sim/test_run.py --profile
triangles`: `hrun` (the span itself) **14.3 %**, `varidx` 11.1 %, and
the rest spread across `prim`, `eval`, `erel` and `stmt`. It is
statement-bound, not pixel-bound, which is the same finding `WAVE`
records from the other end: in this BASIC the cost of a loop is the
statements in it.

**So the row was written out twice to save a `NEXT`, and it measured
slower — 10.7 against 11.2.** Unrolling only pays if the duplicate is
free, and the second row's `I+1` has to be evaluated in two arguments
where `NEXT`'s own increment is one add nobody parses. Four statements
a row is the floor here: the `LINE`, the two edge steps, and the
`NEXT`.

Colours are 1–15, not 0–15: entry 0 is the paper, and a triangle
painted in it is a triangle nobody sees. The disc name is `TRIANGLE` —
eight characters is the filesystem's limit and the source keeps the
plural.

### `MINIBNCH` — ten thousand adds, timed by the machine's own clock

![MINIBNCH](img/demo-minibnch.png)

Ten passes of a thousand `S=S+J`, with a dot a pass, and the time it
took. The listing inside the timing is exactly what was typed at the
machine; everything else is the clock around it, and the marker dots
stay *inside* the measurement because they are part of the program
being timed.

**`TIMER` is the clock and one tick is 16.7 ms.** It is the vblank
count at 59.97 Hz, so a run of a hundred frames is measured to about a
percent — six times finer than the tenth of a second asked of it, with
no calibration and nothing to drift. It wraps at 65,536 frames and the
subtraction wraps with it, so only a run past nine minutes would need
the third byte at `$FF2F`.

**Measured: 99–100 frames, about 1.66 s — 0.166 s for a thousand
adds**, which
is about 12,000 interpreted statements a second (each pass is the add
and the `NEXT`). That is the number to reach for when asking whether
something belongs in BASIC or in a `SYS` routine, and it is why
`TRIANGLES` above is statement-bound.

**The answer is `-23788` and it is right.** `S` is an integer, so
500500 comes back as its low sixteen bits; `S#` would hold the value
but only to about five digits, and would take five times as long to
get there. The demo prints the wrapped figure and says so.

`sim/test_run.py`'s `minibnch_clock` reads `TMR_L`/`TMR_M` itself on
either side of the run and holds the printed frame count against its
own — a demo that reports a time is worth exactly what its clock is
worth. It is also what found the console bug in
[13-basic.md §5](13-basic.md)'s `MODE` row: this was the first text
demo to open with `MODE 0 : CLS`, and it printed into the middle of the
screen.

### `BAPPLE` — Bad Apple, streamed from the dedicated drives

![BAPPLE](img/demo-bapple-shadow.png)

**What ships is the first 344 frames, on drive 12 alone** — seven
chunks, the opening of the film, and the stub `BAPPLE` on the demo
disc that plays them. **The whole film was built and plays frame-exact
end to end**: 3,481 frames extracted at 15 fps, 224 of black-and-credits
tail trimmed by a coverage threshold (the credits are two static text
cards under 2% lit; the film's last real frame lands to black at
217.1 s), leaving 3,257 frames -> 5,259,513 bytes in 82 chunks. Verified
by parking the VM at the VSYNC wait every four hardware frames for the
*whole film* and requiring both VRAM pages to equal the reference
decoder's state, park after park -- every frame from 0 to the last
matched exactly.

**Why it is capped, and where the cap lives.** The full stream is
5,259,513 bytes against 454,656 usable a volume — 11.57 volumes — so
the full build took twelve drives, 12 downward, and its lowest was
**drive 1, `USER_VOL`**, where a cold machine comes up: the whole-film
plan always collided with the user's own disc. An earlier session cut
the disc to drive 12 alone, but the cut lived only in
`demos/bapple/manifest.json`, which `.gitignore` excludes, while
`tools/mkbadapple.py` went on saying `range(12, 0, -1)` and this
section went on describing the twelve-drive film — so a rebuild from
the mp4 would have walked straight back over drives 1 to 11 without a
word. Now the generator's default drive list is `[BAPPLE_VOL]`,
`--drives 12,8,7` asks for more, `plan()` refuses any drive in
`cool8disk.CLAIMED`, and `tools/mkdemos.py` asserts the same thing on
every chunk it places, so a manifest from before the cap fails the
build rather than the user. Rebuild the shipping cut with
`python tools/mkbadapple.py badapple.mp4` — the stream stops when the
drive is full, which is the 344 frames — or `--frames N` for fewer;
the longest cut the free drives allow is `--drives 12,8,7,6,5,4,3,2` -- drive 10 is the
picture drive now ([D103](01-decisions.md)) and drive 9 MOTT's ([D108](01-decisions.md)), both claimed, and the planner
says so if it is asked for, as it says when the stream outgrows the
drives it was given -- and it is not in
the tree because the full build's directory is kept beside the cut,
unused, with a `README.md` saying which half is live. The mp4 stays
out of the repository.

**Fitting was a planner problem, not an encoder problem.** The encoder
absorbs unchanged same-value bytes into runs and only pays a skip
token for stretches of eight or more, which brought the stream to
5.31 MB against 5.41 MB of raw drive capacity -- but a planner that
only cut 64 KB chunks wasted each drive's unreachable tail, 720 KB of
packing loss, and reported the stream as not fitting. Chunks are now
cut against the file-size cap and the drive's remaining space at once
(the last chunk on a drive fills it), and the planner predicts the
256-byte page alignment `Volume.add` gives every file start.

**Why this port is easy where every other 8-bit port was hard**: flash
is 8 MB and `FLS_DATA` auto-advances, so streaming is native and plain
delta-RLE at 256×192/15 fps (~2–4 MB) needs none of the heroics — the
C64's 170 KB vector quantisation, the BBC's floppy choreography — that
define the genre. The fight everywhere else is storage; ours was only
decode speed, and 8.375 MHz settles it.

**The stream**: frames become mode 5 byte planes (two pixels a byte),
delta-encoded against the frame *two* back — pages alternate under the
D92 double buffer, so a page's previous content is two frames old.
Tokens: `$00` end-of-frame (flip `VID_DBASE_H`), `$01–$7F` a run of
the next byte through `VRAM_DATA`'s auto-increment, `$80–$FF` a skip
of token−127. Frames 0 and 1 ship full, so nothing needs clearing.

**The decoder is 68 bytes of machine code** at $9000, assembled by the
generator through the harness with register addresses stamped from
`tools/ioregs.py`, POKEd from `DATA` by the stub, one frame per `SYS`
from a four-`VSYNC` loop — BASIC keeps the tempo and the exit key.

**Dedicated drives, in the order `--drives` gives them**: the catalogue
caps a file at 65,535 bytes, so the stream ships as `BA###.DAT` chunks
split at frame boundaries. Volume files are contiguous from a fixed offset, so the
planner *predicts* each chunk's absolute flash address into the stub's
table, and `mkdemos` asserts the prediction when it places them — a
chunk landing anywhere else would stream garbage from a right-looking
drive. Between chunks the stub closes `FLS_CTRL`, re-points the
address, reopens.

**Two build-order traps, both now held by assertions.** First, the
chunks used to be written into the image file while the disc-building
machine was already running; the `flush()` after `SAVE "BAPPLE"` put
the machine's pre-chunk flash back over the file, leaving erased $FF
where the stream had just been placed -- every placement assertion had
passed, on an intermediate state. `mkdemos` now places the chunks
*before* the machine boots and re-reads every chunk from the finished
file. Second, the stub was typed over the previous demo without a
`NEW`: every line number the stub does not use survived, and WAVE's
colour-ramp DATA lines 205-249 sat between the decoder DATA (200-204)
and the chunk table (250+), so `READ` served palette bytes as flash
addresses. The program LISTed clean line for line -- only dumping the
READ stream itself showed the ramp. The fix is one `NEW`; the gate now
types a decoy demo first to keep the scenario alive.

**Gate-enforced** (`bapple_decodes`): a fresh synthetic clip is
encoded, placed, and played -- the stub typed over a decoy program, as
the disc build types it; both VRAM pages must then equal a consecutive
reference frame pair with the right parity — the token walk, the flash
auto-advance, the VRAM auto-increment, the skip carry and the page
alternation in one comparison. **The flip is held on the glass**:
twenty-two consecutive display frames must each be a whole frame of
the clip, in order, four apiece. BAPPLE never had COBRA's flip fault —
the decoder writes `VID_DBASE_H` as its last store, before the stub's
four `VSYNC`s, the order [D105](01-decisions.md) amended D92 to, so a
page has left the glass before it is decoded into — but the gate used
to read the register, and now it reads the frame. Sound is a later,
separate step, by decision.

### `TAIPAN` — the 1982 China Sea trading game in 40-column Mode 1

![TAIPAN](img/demo-taipan.png)

A port of Art Canfil & Ronald J. Berg's classic 1982 adventure game *Taipan!*,
ported to COOL8 BASIC in **Mode 1 (40×30 text mode, 16 foreground/background colors per cell)**.

**All mechanics are preserved**:
- Trading 6 goods (Opium, Silk, Tea, Arms, Pepper, Rice) across 10 historical ports.
- Debt, loans, and compound interest with Elder Brother Wu in Hong Kong.
- Hong Kong godown (warehouse) cargo storage.
- Random market shifts, events, extortion, Li Yuen's pirate fleet, sea battles, typhoons, and ship upgrades.
- Historical price tracking per port and per commodity.

**Language and platform specifics**:
- Runs in native 40×30 text mode (`MODE 1`) with per-character foreground and background colors (`COLOR fg, bg`).
- Uses 24-bit floating-point numbers (`M#`, `D#`, `Q#`, `AP#`, `GP#`, `HI#`, `LO#`) to represent currency and prices beyond 16-bit bounds.
- Custom sound effects through the 8-voice audio subsystem (`SOUND`).
- ASCII ship graphic rendered in Mode 1 during pirate encounters.

### `COOLTRIS 1` — 1-player arcade Tetris in 40-column Mode 1 with CP437 character graphics

![COOLTRIS 1](img/demo-cooltris.png)

Classic 1-player arcade Tetris implemented in COOL8 BASIC using **Mode 1 (40×30 text mode)** and CP437 character graphics (`demos/cooltris.bas` / `demos/cooltris1.bas`).

**Game mechanics & features**:
- Standard 10×20 playing matrix with authentic double-line box border (CP437 201, 205, 187, 186, 200, 188).
- Complete 7 tetromino set (I, J, L, O, S, T, Z) with standard color palette, 4 rotation states each, and double-width solid block characters (`██` CP437 219).
- Modern 7-Bag randomizer ensuring uniform piece distribution without droughts.
- Ghost piece / drop shadow preview (`░░` CP437 176) showing real-time landing position.
- SRS wall kicks for clockwise (`W`, `K`, `X`, `Up Arrow`) and counter-clockwise (`Z`, `J`) rotation against board boundaries and stack obstructions.
- Soft drop (`S`, `Down Arrow`) and hard instant drop (`Space`).
- Real-time NEXT piece preview window in sidebar with single-line box border.
- Sidebar showing 6-digit score, level, lines cleared, and persistent session high score on separate lines.
- Anti-hover hardware timer synchronization (`TIMER`) ensuring gravity drops strictly in real-time regardless of input frequency.
- Clean square-wave sound effects (`SOUND voice, pitch, vol, 0`) for movement, rotation, soft drop, locking, single/double/triple/Tetris line clears, level ups, pause, and game over.
- Game over curtain animation (`▓▓` CP437 178) with high-score tracking, replay prompt (`N TO PLAY`), and pause (`P`).

### `COOLTRIS 2` — Arcade Tile Engine Tetris in Mode 2 with Custom 4 bpp Graphics and 7 Palettes

Classic arcade Tetris re-engineered for **Mode 2 (40×30 Tile Mode, 320×240 doubled)** with custom 4 bpp tile patterns, multi-bank color palettes, and direct VRAM streaming (`demos/cooltris2.bas`).

**Architecture and tile engine specifics**:
- Runs in native 40×30 tile mode (`MODE 2`), leveraging the OS auto-font at VRAM `$1000..$1BFF` (Tiles 0..95) alongside 17 custom-designed 4 bpp arcade tiles at VRAM `$1C00..$1E1F` (Tiles 96..112).
- **Custom 4 bpp Arcade Tile Set**:
  - Tiles 96 & 97: 3D beveled block halves (left/right specular highlight and core shadow) creating 16×8 arcade tetromino minos.
  - Tiles 98 & 99: Fine 1-pixel ghost landing outline tiles.
  - Tiles 100–105: Ornate gold double-rail border set (horizontal, vertical, corners).
  - Tiles 106–111: Sleek silver single-rail box borders for NEXT preview, Keys, and Stats windows.
  - Tile 112: Textured arcade curtain dissolve effect for game over sequence.
- **7-Bank Color Palette**:
  - Each piece uses an authentic 4-color shading ramp (highlight, base, midtone, shadow) mapped across 7 independent 16-color palette banks (`$FF1E..$FF1F`).
  - Pieces retain crisp 3D depth and distinct arcade identity (Cyan I, Blue J, Orange L, Yellow O, Green S, Magenta T, Red Z).
- **Direct VRAM Streaming**:
  - Uses fast hardware auto-incrementing VRAM address registers (`$FF26..$FF29`) to stream tile index and attribute bytes in ~0.15–0.48 ms per frame (< 3% of the 60 Hz frame budget).
- **Audio & Timing**:
  - Crisp noise-free multi-voice square wave sound effects (`noise = 0`), anti-hover hardware timer synchronization (`TIMER`), pause (`P`), game over restart (`N`), and clean exit (`Q`).

### The CoolAction menu — eight of the demos, compiled, and programs of its own

The same demos in CoolAction! ([15-action.md](15-action.md)), on
drive 11 as bare `.BIN`s: RAINBOW, TRIANGLES, MAZE, PLASMA, WAVE,
MANDEL, SYNTH and INTRO, each a `demos/name.act` beside its
`demos/name.bas`; COBRA, which was the ninth and is now a program of
its own, and COBRA2, its camera and sky, the next two sections; and
KEYTEST, MSCOOLMN, ARKANOID, BLOCKADE, COOLTRIS, COOLSW, GALAGA, MOTT and SLIDES, which have no BASIC and follow them. **The picture is the contract, not the code.** A port
may do the work any way the language allows -- and mostly does it the
BASIC's way, because the BASIC's way was measured -- but
`sim/test_action.py` runs every pair to the same point and requires
what the machine holds to be identical: VRAM, palette, the text map,
the programmed voices, the registers. Every one of the nine -- COBRA
then among them -- matched on its first run against its original, which is what the library's
`Line` being `LINE` pixel for pixel and `Rnd` being `RND` from the
same seed bought.

**Where each pair is parked, and what must agree:**

| port | parked at | identical |
|---|---|---|
| RAINBOW | the 40th frame wait | 38,400 bytes of mode 4, 16 palette entries |
| TRIANGLES | the 281st `RND` -- forty triangles in | 38,400 bytes of mode 4 |
| MAZE | the 1,341st `RND` -- the map and twelve scroll steps | the map and the tile, the palette, `VID_BASE`, `VID_SCY` |
| PLASMA | the 5th frame wait -- painted, four rotations in | 61,440 bytes of mode 6, 47 palette entries |
| WAVE | the 120th frame wait | 61,440 bytes, all 256 palette entries |
| MANDEL | the key wait at the end -- the whole set | 61,440 bytes, all 256 palette entries |
| SYNTH | the 120th frame wait -- thirteen steps of the tune | the 5,120-byte text map, eight voices' pitch, volume and bits, the palette, the border; then the editor typed at |
| INTRO | the 120th frame wait | the text map, the voices, `VID_BASE`, `VID_SCX`, `VID_SCY`, the border |

A frame wait is a routine entry on both sides -- `h_vsync` in the
interpreter, `WaitVBlank` in the library -- and so is an `RND`, so the
two machines are at the same point of the same algorithm whatever the
clock says. Where the demo has no frame wait, the count of random
numbers *is* the clock.

**What a port changes.** `READ`/`DATA` becomes an initialised array;
`tools/mkactdata.py` copies every BASIC's `DATA` into a marked block
of its `.act` -- PLASMA's tables and rainbow, WAVE's sine and
253-entry ramp, SYNTH's and INTRO's tunes, MAZE's palette and tile --
and `poe check` fails if a block is stale,
so a change to a model or a palette in the BASIC fails there rather
than in the framebuffer. `DIM` is a declaration, `0-Q` is `-q`, a
`POKE` to a register is the register's generated name, a `POKE` to the
text map is the machine's own base plus the BASIC's offset, `INKEY` is
`ReadKey()` on the interpreter's own keyboard tables, and `RND` is
`Rnd()`, the interpreter's xorshift from its seed -- which is why
TRIANGLES and MAZE, pictures made of nothing but random numbers, match.
MANDEL's coordinates are `BYTE` where the BASIC has integers, because
a screen coordinate is 0-255 by construction; the arithmetic that must not be narrowed -- MANDEL's Q6
iteration, WAVE's `o < y - 1` at the top of the screen, TRIANGLES' edge
accumulators -- is `INT`, and every divide truncates towards zero as
the BASIC's does.

**What the pairs measure.** COBRA, while it was a port, measured the
two ends: its start-up -- 2,016 projections and 1,772 table gathers --
was **36× faster** compiled (1.4 M clocks against 50.5 M), and a
frame's drawing 2.4× (239 K against 578 K), because `Line` and `LINE`
are the same algorithm and the compiled one, at 97 clocks a pixel, had
only just overtaken the interpreter's 101-181; neither held 60 Hz. **MANDEL is 35×**: the whole set in 60.5 M clocks
against 2,126 M -- 7 s against 4 min 14 s of machine time -- with the
same Mariani-Silver rectangles and the same Q6 iteration, which is the
arithmetic-and-array-traffic case the sieve profile predicted. Those
are the figures after the compiler's optimiser
([15-action.md §4a](15-action.md)); before it they were 18.7×, 2.0×
and 7.1×, and reading these ports' hot loops is what found the
patterns. PLASMA's 25 s of visible top-down paint is a fraction of a
second. RAINBOW, WAVE, SYNTH and INTRO sit in the frame wait either
way and gain nothing a viewer can see. The full table is in
[15-action.md §5](15-action.md).

**`PRIMES` is on the same menu**, because it is `demos/primes.act` and
the disc is derived from `demos/`: it counts the primes to a thousand
and says so on the serial port, which the page does not show. A
demonstration that a compiled program reaches the hardware, not a
picture.

**Two things the ports made visible.** `CLG` clears 240 rows of the
stride in every mode (`h_clg`), which in mode 5 is 30,720 bytes from
`VID_BASE` -- 6,144 past the page -- so the COBRA port's second
clearing frame wiped the top 48 rows of the page then on show; it
lasted one frame, the library's `Clg` does exactly the same, and the
two framebuffers agreed. And a voice's phase accumulator, bytes 2 and 3 of its eight,
can never be compared between two machines: the engine advances it
every 256 clocks from the moment the pitch lands, and two programs
that write the same pitch in the same frame write it at different
clocks. The gate compares pitch, volume and the mode bits, which is
what the program wrote.

### `COBRA`, compiled — the tumble, every frame computed

![COBRA, compiled](img/demo-act-cobra.png)

**The same ship, a different program** ([D105](01-decisions.md)).
`demos/cobra.act` tumbles the Cobra Mk III on three axes and computes
every frame between two vertical blanks -- the rotation from three
angles, the 28 vertices through it and into perspective, the 13 faces
culled, the visible edges erased and drawn -- in 55,958 of the frame's
139,583 clocks, so it holds 60 Hz with 60 % to spare. The BASIC's
COBRA replays 72 precomputed frames about one axis at about 13 a
second, and the compiled port of it drew 30.

**A mode no preset names**: 256 × 240 at 4 bits a pixel -- mode 6's
timing, `VID_CTRL = $3A`, a stride of 128 -- which is 30,720 bytes a
page, so both pages of a double buffer fit VRAM. At 4 bits the pixel
port plots in one store and steps X or Y itself, and a line is 14
clocks a pixel. **The page is flipped before the frame wait, not
after**: the fetch takes `DBASE` on the pulse that ticks the frame
counter, so a flip after the wait lags a frame and the glass shows the
page being redrawn -- which the first cut did, D92's order still said,
and the BASIC COBRA did at every flip until its gate compared the
glass.

**Assembly where the profile put the clocks**, compiled CoolAction!
everywhere else:

| a frame | clocks | |
|---|---|---|
| the lines, the last frame's erased and this one's drawn | 30,457 | assembly: a store and an error step a pixel |
| 28 vertices onto the screen | 13,658 | assembly: the unsigned `MUL` with 128 carried in, the surplus off as two constants |
| 13 faces and the edge list | 8,618 | the faces in assembly, the same multiply-add; the list compiled |
| the rotation | 1,856 | compiled: fifteen products from a 1,024-step sine table |

**The faces are culled by their normals**, each its own triangle's,
with 256 of hysteresis: the BASIC's area on the screen flickered at
this speed, because near edge-on a thin face's area is the rounding of
its corners. `tools/mk3d.py` writes the model and the tables and
checks the camera against the machine's own integer arithmetic over
every pose, down to the picture closing -- no drawn edge but the
laser ends in nothing. `test_cobra` holds the program to it: a pass in
each of 600 vblanks, every vertex where the generator's arithmetic puts
it, every face's decision from the program's own matrix, the list
exactly the visible edges and the page exactly the list's lines, pixel
for pixel, and erasing by redrawing the same as a clear. The PRG is
5,583 bytes, 2 KB of it sine.

### `COBRA2` — the camera circles, the ship flies, the sky stays put

![COBRA 2](img/demo-act-cobra2.png)

**COBRA read the other way round** ([D106](01-decisions.md)).
`demos/cobra2.act` is a copy of the compiled COBRA, which it leaves
alone: the ship does not turn, a camera circles it at a sixth of COBRA's
rates, and the ship flies straight along its length. The ship's frame
is then the world's, so the rotation COBRA computes is the camera's,
and everything fixed in the world goes through it -- the corners, 24
stars and 10 specks of dust.

**Elite's sky, placed in the world, and the ship flying through it.** A
star is a direction and swings across the screen exactly as far as the
camera turns. A speck is a point fixed in the world; the ship has a
place in the world and flies eight model units a frame along its nose,
the camera following, and a speck's place from the ship goes through
the perspective as a corner does -- so specks stream past the hull, and
those in front of it and behind it part company as the camera goes
round. As Elite does with its stardust, what leaves the screen is
recycled: a star across the opposite edge, a speck somewhere in view
ahead of the ship, each put back into the world through the matrix's
transpose. The ship moving and not the dust is the owner's call: it is
the shape a second ship will need.

**Behind the ship, the sky is hidden.** The ship is lines, so a star
behind it would show through its body. Its outline -- the edges where a
face turned to the camera meets one turned away -- is crossed twice by
any row, and a point between the two crossings of its row is not drawn:
a star always, a speck when it is behind the ship's centre. It stays in
the sky and comes out again past the ship's edge.

**Measured**: 90,065 of the frame's 139,583 clocks, 60 Hz over 1,800
frames -- the sky 36,456 (in assembly: the ship's own three rows once a
point, a table and a `MUL` for the perspective, and the outline test),
its dots 2,166, recycling 1,620; the transform skips the stern's panel
vertices while the stern is turned away. `test_cobra2` holds it to every claim COBRA is held to
and, on top, to `tools/mk3d.py`'s models of the sky: every star and
speck where the models put it, in its colour, and none drawn inside the
ship's outline; each page the dots with
the lines over them, pixel for pixel; over 120 frames the ship flying
its four units a frame, each star on the screen keeping its direction
and each speck its place in the world; and what is recycled mostly back
on the screen the next frame. Faces keep hysteresis on the way out only: at half COBRA's rates, the first cut's,
two-sided hysteresis left a one-frame gap between two faces trading an
edge. The PRG is 11,647 bytes.

### `KEYTEST` — what the keyboard sends

`demos/keytest.act`: every byte the PS/2 FIFO delivers, on the screen
as hex as it arrives and echoed to the serial port -- the raw Set 2
stream, a make code, `$F0` then the code for a release, `$E0` before
an extended key -- and under it what the library makes of the same
bytes: the keys `KeyHeld` says are down and the last one `KeyHit`
saw. Esc twice resets the machine. Written the day the space bar did nothing in
Ms. Cool-Man ([D101](01-decisions.md#d101--a-program-that-reads-the-keyboard-owns-it)):
the window typed a character as make-then-break in one burst, and
this shows that in one line, where a real press is a make, a pause,
then the break. The program to run first when a keyboard, a front end
or a board is in doubt; the serial log is the record.

### `MSCOOLMN` — Ms. Cool-Man: the arcade's first two mazes, in mode 2

`demos/mscoolman.act`, 56 KB of PRG from `$1400` under the loader of
[D102](01-decisions.md#d102--the-loader-a-program-owns-the-machine-and-never-comes-back),
the whole of Ms. Pac-Man with the arcade's rules: the four mazes on
the arcade's schedule -- pink for levels 1 and 2, light blue for 3 to
5, orange for 6 to 9, navy for 10 to 13, then the third and fourth
shapes again in magenta-and-yellow and in salmon, four levels each and
in turn for ever -- the four ghosts with their own targets, the pills,
the fruit, the house, the tunnels, the score beside the maze, the
ghost's score where it was eaten, and the three intermissions. A hobby port for the machine's owner, with no users; **its art
is the arcade's own pixels**, in the repository by that owner's
decision. `tools/mkmscool.py` rips the two mazes, her nine frames, the
ghosts', the fruit and the font from the sheet images in
`assets/misscool/` (The Spriters Resource's arcade Ms. Pac-Man and
Pac-Man sheets) and writes `assets/misscool/mscoolman_art.act` beside
them; `demos/mscoolman.parts` names that file as the part the game
compiles behind, `sim/harness.py`'s `act_sources()` reads the
manifest, and `poe check` holds the generated file to the sheets.
Without the part, `poe demos` leaves the game off the disc and says
so, and the gate skips, loudly.

**Mode 2, because the arcade board is a tile map with sprites.** The
maze is 28 × 31 tiles of 8 × 8 in the map at VRAM 0, a dot is a tile
and eating one is one map write; the screen holds 30 rows, so
`VID_SCY` is 4 and the generator rolls the outer walls four pixel
rows into the visible halves of their tiles -- the top wall shows in
lines 0-3, the bottom in 236-239, all 31 rows on 240 lines. The score,
high score, level, lives and level fruit sit beside the maze in
columns 28-39, where the arcade's 224-wide picture leaves 96 pixels
of a 320-wide screen: the arcade's HUD rows above and below the maze
are what the height does not allow, and the side is where it goes.
The font is the arcade's, the maze tiles and palette are the sheet's
(38 to 40 tiles a shape, five colours each; the fifth and sixth
mazes are the third and fourth shapes under other palettes, which the
generator proves by finding the nibble permutation and emits as
palettes alone), the lives and the fruit beside the maze are her
sprite and the fruit sprites undoubled into tiles, and a cell's kind
-- wall, path, dot, pill, door -- follows from its tile, the outside
having a black tile of its own so that it is not a path.

**A character is four hardware sprites.** Sixteen logical pixels over
a doubled mode is 32 raster lines, and a sprite is 16 × 16 raster, so
each of her, the four ghosts and the fruit is a 2 × 2 block -- 24 of
the 32 descriptors, all from palette bank 15, the one bank the engine
gives sprites (`SPR_CTRL[7:4]`). Her left-facing frames are the
right-facing ones H-flipped with the quadrants swapped; the ghosts'
eight frames are stored once with the body as colour index 1 and
written to VRAM four times at load with index 1 replaced by each
ghost's colour -- 16 KB of VRAM for 2 KB of program. The engine draws
eight sprites a line and trails every sprite two lines to clear its
span ([04-system.md §5.6](04-system.md)), so the seam between a
character's halves, where its top sprites' trailing lines meet its
bottom sprites' first, is where three characters abreast at exactly
one height cost more than a line has and the lowest-numbered loses
a line. The five movers therefore take the low descriptor numbers in
turn, a frame each, so a loss flickers between them instead of
sticking to one; Inky and Sue bob out of step with Pinky in the
house. Measured with `sim/mscool.py`'s autopilot eating its way round
the pink maze with `SPR_CTRL`'s overrun flag cleared every frame:
32 of 390 frames overran before a death, 75 before the rotation;
at level 3 with all four ghosts loose the gate's 240-frame stretch
has measured anywhere from 68 to 165, depending on where they are --
the count is printed, not gated, because a ghost train in a corridor
is the game and not a fault.

**The rules are the Pac-Man Dossier's**, which Ms. Pac-Man keeps:
speeds as sixteenths of a pixel a frame from the percentages of
1.25 px (her 80 %, ghosts 75 %, frightened 90 and 50, the tunnel 40,
by level band), the scatter/chase timetable (7, 20, 7, 20, 5, 20, 5
seconds at level 1, the sixth chase endless from level 2), Blinky at
her tile, Pinky four tiles ahead with the upward overflow (four left
as well), Inky's vector doubled from Blinky, Sue's eight-tile coward
radius, up-left-down-right on a tie, no reversing except when the
mode flips, the house counters (Inky at 30 dots, Sue at 60 more;
after a death 7, 17, 32; four seconds without a dot lets the next
out), Cruise Elroy at 20 and 10 dots, the fright lengths by level
with the flashing, 200-400-800-1600 for the ghosts on one pill, a
frame of freeze a dot and three for a pill, the eaten ghost's eyes
home through the door and out again. Ms. Pac-Man's own: the ghosts
wander at random through the first two scatters so no pattern works
twice, and the fruit walks in through a tunnel after 70 dots and
again after 170, wanders, and leaves by a tunnel -- cherry,
strawberry, orange, pretzel, apple, pear, banana by level, 100 to
5,000. The opening jingle plays under READY! at a game's start, as
the arcade's does: melody and bass on two voices from the VGMusic
transcription of the level intro (mspacman.mid, Oedipus, 106 bpm),
its pitches as the engine's 0.5 Hz steps and its lengths in frames.
**The intermissions** come after levels 2, 5, 9 and every fourth
after, on a black screen under the clapperboard from the sheet
clapping its number: "They Meet" and "The Chase" move as the
reference implementation whose maps these are (masonicGIT/pacman,
`src/cutscenes.js`) moves them, frame for frame at the arcade's own
pixel positions -- Pac-Man and Inky along one lane, she and Pinky
along another, the ghosts quickening at the middle; both in from the
sides, the ramp over the ghosts as they bump heads, the climb, and
the heart; then the four runs of the chase at two and a half and
three pixels a frame and the seven-pixel dart. "Junior" has no
reference to follow and is choreographed from its description: the
parents at the left, the stork over the top, the bundle dropped,
falling, bouncing twice, and Junior in it. Pac-Man's own frames are
on the sheet (left is right mirrored, down is up turned over), and so
are the heart, the stork, the bundle and Junior. "They Meet" plays
its tune, the VGMusic transcription (mspacman2.mid) on two voices;
**the tunes of "The Chase" and "Junior" have no transcription to be
found and are not made up**, so those two acts play to their sounds.
Not there: a second player, and the level-by-level fright and speed
tables past level 5 are the Dossier's for Pac-Man.

**The gate** (`sim/test_action.py`, on `sim/mscool.py`) runs the game
three ways: on the bare machine for the rules; `SYS`'d from a booted
BASIC with its interrupt handler running; and booted from the demos
disc by the real ROM, the launcher's `DRIVE 11` and `SYS "MSCOOLMN.BIN"`
typed at the keyboard, the space bar as a make-and-break burst, an
arrow key held -- the path a person takes, and the one that found
[D101](01-decisions.md#d101--a-program-that-reads-the-keyboard-owns-it)
twice. On the bare machine: the art file is what the generator writes; the compiled bytes agree with
`tools/cool8asm.py`'s; the title frame is mode 2 scrolled four lines
with the pink maze's own tile in the corner and her name in yellow;
READY!; 224 dots, three lives; she walks left along row 23 and each
dot is ten and a blank cell; Blinky and Pinky loose, Inky waiting;
the pill is fifty and six seconds of blue and the loose ghosts turn;
a blue ghost eaten is 200, eyes, the door, the house, out again; a
red one is a life and everyone back at the start with one icon fewer
beside the maze; the level cleared is the pink maze again, and again
is the blue one with 244 dots, its palette, its tiles and the orange
beside it; the fruit walks in after 70 dots; the sprite engine's
overrun flag over 240 frames of play; then the level poked to 2, 5, 9
and 13 in turn and cleared, and after each the clapperboard with its
digit, the first act's tune playing and the others' not, the next
level's READY!, and levels 6, 10 and 14 in the orange, the navy and
the magenta maze with their dot counts, palettes and tiles. An autopilot in `sim/mscool.py`
pokes her wanted direction each frame along a shortest path, and the
same file run by hand writes the frames as PNG: `python sim/mscool.py
pill` (or `title`, `death`, `clear`, `fruit`) -- which is how every
picture above was checked, and how the two bugs of the first frame
were found: every cell in row 0 because `row << 7` on a `BYTE` is a
byte, and the fruit one column off the sheet.

### `ARKANOID` — the arcade Arkanoid, all 33 rounds, in mode 2

`demos/arkanoid.act`, the whole of Taito's 1986 arcade Arkanoid under
the loader of [D102](01-decisions.md): the 32 rounds in the arcade's
layouts on their four backgrounds, the Vaus, the ball, the seven
capsules and what each does, the laser, the three balls, the enemies
through the gates in the frame's top, the exit a B opens, DOH on round
33, the intro's story over the mothership, and the board's own music. A
hobby port for the machine's owner, with no users; **its art is the
arcade's own pixels**, as Ms. Cool-Man's is. `tools/mkarkanoid.py` reads
The Spriters Resource's arcade sheets in `assets/arkanoid/` (the fields,
the blocks, the power-ups, the enemies, DOH, the intro's mothership and
the owner's fuller "Arkanoid (World, older)" Vaus sheet) and writes
three files there: `arkanoid_art.act`, which `demos/arkanoid.parts`
names as the part the game compiles behind, and **two data files the
game reads from its own drive** -- ARKANOID.DAT and ARKSCENE.DAT, 92 KB
of tiles and sprite patterns that do not fit the program and are
streamed from the flash into VRAM when a phase needs them
([D107](01-decisions.md)). `demos/arkanoid.disc` names them, and
`tools/mkdemos.py` puts them on drive 11 beside ARKANOID.PRG. `poe
check` holds all three to the sheets.

**The rounds are read off the arcade**, from StrategyWiki's walkthrough,
whose 32 pictures are the arcade's own 224 x 256 frames: each brick cell
by its face, 40 of its 65 inner pixels one brick colour and its right
and bottom edges the black every brick has. Round 1 reads silver, red,
yellow, blue, magenta, green. One cell is put back by hand: round 5's
top-left antenna, under a cone and its shadow in that frame. The same
frames that caught an enemy say which comes when: cones on the blue
rounds, pyramids on the green, molecules on the circuit, cubes on the
grey -- the background and the enemy are one choice, (round - 1) mod 4.
Round 3's gold was held against the arcade's frame again when it was
asked after: its eight rows -- green; three white and ten gold; red; ten
gold and three white; magenta; three blue and ten gold; cyan; ten gold
and three cyan -- are that frame's, cell for cell, and gold cannot be
broken there or anywhere, by ball or by laser, nor is it counted towards
clearing the round
([StrategyWiki](https://strategywiki.org/wiki/Arkanoid/Gameplay)). The
way through is the three-brick gap at one end of each gold row.

**Mode 2, the field at one pixel to one.** The arcade's field is 224 x
240 under its score line and mode 2 is 320 x 240, so the field is
columns 0-27 exactly and the score, the round and the lives go beside
it. A background is a model the generator proves against the sheet --
its frame, a pattern of cells, and the cells the pattern does not
predict. A brick is two tiles; its shadow, one cell right and one down,
is the background's dark tile, as the arcade's own tile map does it. The
gates open in the frame's top row a strip of six frames at a time; the
exit is three frames of crackle in the right wall.

**The Vaus is composed into the background** ([D107](01-decisions.md)):
the background under it, its shadow in black, the Vaus, into tiles --
all 60 of its frames, the lights turning, the enlarging and arming
morphs, its appearing and its breaking up -- so it costs no sprite and
its shadow is the arcade's. Everything else is sprites from one bank,
the capsule's two colours and the round's enemy's four filled in when
they change.

**The rules as far as they are known.** Points by colour, 50 to 120,
silver 50 times the round and two hits (one more every eight rounds),
gold never; 1,000 for a capsule, 100 for an enemy, 10,000 for the exit,
1,000 a hit on DOH, who takes sixteen; an extra Vaus at 20,000, 60,000
and every 60,000. The capsules as the arcade's instruction card names
them -- orange S slows the ball, green C catches it, blue E enlarges,
aqua D splits it in three, red L arms the laser, pink B opens the exit,
grey P is a Vaus more -- one at a time, none while three balls fly, B
and P half as likely as the rest, never the power already held. **Chosen,
because the arcade's numbers are not published**: eight ball speeds from
1.5 to 3.5 pixels a frame, a step faster every eight hits and at the
first touch of the ceiling; six angles off the Vaus, 30, 45 and 60
degrees either way by where the ball lands; a capsule a brick in five;
an enemy through the gate on the Vaus's side every six seconds, three at
most, wandering down; DOH opening his mouth every two and a half seconds
for three shots aimed where the Vaus was. **The sound effects are made
on the voices** -- the rip has the board's music and nothing else --
and are this port's. **The music is the board's**: the story, the round
start, DOH's round, game over and the ending, replayed from the YM2149's
register log a 60 Hz frame at a time, the three channels' periods as
phase increments and their levels on the machine's linear scale, the
envelopes worked out where a channel asks for one.

**The Vaus's collisions, and what the first cut got wrong.** An enemy
that meets the Vaus bursts, for 100, as one the ball or a beam hits
does, and does the Vaus no harm: StrategyWiki's
[gameplay page](https://strategywiki.org/wiki/Arkanoid/Gameplay) has the
Vaus crash into enemies harmlessly, and has the ball leave it steeply
off its middle, at 45 degrees off its red bands and shallowly off its
very ends, as the six angles above do. The ball bounces off the Vaus
anywhere in its body on the way down, not only across its top: the
first cut bounced only a ball that crossed the top in a frame, so a
Vaus that came under the ball a frame late -- the ball's bottom one to
eight pixels past its top -- let it through (`python sim/arkanoid.py
late`). The body is the frame on the screen, as wide as its pixels on
the rows a ball lands on, which the generator measures from the sheet
(`vf_l`, `vf_r`): the first cut took the form's, and a morph plays while
the form already says where it goes, so for the 18 frames of shrinking
up to 8 pixels of the Vaus each side let a ball through (`vaus`). And an
enemy never heads up into the frame's top: one heading in eight is up,
nothing stopped it, and a sprite's y is nine bits, so an enemy that
rose past the field wrapped to the screen's bottom -- at y -26 and -34
under and beside the Vaus -- where nothing met it (`up`).

**Out through the exit.** The gap a B opens is taken by driving the Vaus
into it: the ten thousand lands and the Vaus goes on right, out through
the gap, before the round turns. The first cut ended the round the
moment the Vaus reached the gap and left it standing there for some
seventy frames before it vanished where it stood
(`python sim/arkanoid.py exit`, which shoots every eighth frame across
the change).

**DOH** sits in the wall's hole on his red round, cells 10-17 x 5-16,
drawn from four normal frames with his mouth opening; hit, he flashes
cyan, and beaten he turns purple in the sheet's twelve dying frames --
each a normal frame with one colour changed, a palette write -- then
his wireframe comes down through him a cell row at a time, where the
sheet's eight frames of it pixel by pixel would be 660 tiles. **Not
there**: the ending's words, of which no frame was found; the board's
extra-life jingle, which the rip does not have.

**The intro and the title are the arcade's pictures**: the ARKANOID
logo over the title screen's words, and the story typed over the
mothership, which is lit, hit in four red flashes -- palettes over its
lit frame -- and gives up the Vaus in rings, the Vaus flying off in the
sheet's fifteen frames. The story's words are the game's (the NES
version's FAQ quotes them; StrategyWiki's frame shows the last three
lines); the other lines' breaks and the timing are this port's, and the
font here has no comma. The glyphs themselves are the arcade's where a
frame shows them: 25 on the title and the play screen, 23 of them the
Namco font Ms. Cool-Man has and E and L a pixel wider; the rest are
Namco's, and `tools/mkarkanoid.py` lists which.

**The gate** (`sim/test_action.py`, on `sim/arkanoid.py`) runs the game
with its two data files on drive 11 of a flash image of its own: the
generator's three files current; the compiled bytes the same as
`tools/cool8asm.py`'s; mode 2 and the logo on the title; round 1's
silver and green bricks where the arcade has them and a shadow cell the
dark tile; ROUND over the field and the round-start tune on voice 0; the
Vaus as cells of the background in its banks, its shadow in the row
under; 600 frames of the autopilot with a frame of play in every
vblank; each capsule caught and its power; an enemy through a gate; out
through the exit into round 2 with 10,000, the Vaus going on out through
the gap rather than stopping dead; a ball lost and a life gone;
the stack where it should be; the Vaus's collisions -- an enemy onto it
bursting where they meet and not beside it, a ball bouncing off a Vaus
that came under it late, down to its last row, the ball's body the drawn
one within a pixel for each form and every frame of both morphs both
ways, an enemy made to head up stopping at the field's top; then the
path a person takes -- the real
ROM booting the demos disc, `DRIVE 11` and `SYS "ARKANOID.BIN"` typed at
the keyboard, the game finding its two data files on the drive it came
from, the logo up, space, and round 1 -- with the disc first held to
this build and these data files; then round 33, DOH's face in pattern
bank 2, the sixteenth hit, and the black he sat in. `python sim/arkanoid.py
play` (or `powers`, `enemies`, `doh`, `intro`, `profile`) plays it with
an autopilot and writes the frames as PNG; `touch`, `late`, `vaus` and
`up` are the collision experiments the gate holds, and print what they
find.

### `BLOCKADE` — Gremlin's 1976 arcade Blockade, the first snake game, in mode 2

`demos/blockade.act`, under the loader of [D102](01-decisions.md):
Gremlin's Blockade (October 1976), Lane Hauck's two-player game and the
start of the snake kind
([Wikipedia](https://en.wikipedia.org/wiki/Blockade_(video_game))). Two
arrows each lay a wall behind them; whoever runs into a wall -- the
border, their own or the other's -- gives the other a point, and the
first to six wins (the operator could set three to six, and the 6 in
the top border is that setting). **Its characters are the arcade's own
pixels**: `tools/mkblockade.py` reads StrategyWiki's 256 x 224
screenshot of the arcade's screen in `assets/blockade/` -- two colours,
black and $0F0, on an 8-pixel grid from (0, 0), ten distinct cells there
against 13 or more at any other offset -- and writes
`assets/blockade/blockade_art.act`, which `demos/blockade.parts` names;
`poe check` holds it to the picture.

**The trails are the border's pieces.** The screenshot's trails are
drawn with the border's own straights and corners, a turn being the
corner that joins the side the head came in by and the side it left by;
the generator checks that at all five turns in the picture, and the game
draws every trail that way. **Mode 2, one to one**: the arcade's screen
is a 32 x 28 map of 8 x 8 characters (MAME's `blockade.cpp`), so the
field is columns 4-35 and rows 1-28 of mode 2's 40 x 30. The heads start
where the arcade's do, read off its frames: the left player going down
from (5, 5), the right going up from (26, 22). The left player's head is
a solid arrow and the right's an outlined one; the screenshot has each
pointing one way, and the other three are that head mirrored or turned a
quarter -- derived, not seen.

**The sound is the arcade's in kind, not in pitch.** The
[Golden Age Arcade Historian](http://allincolorforaquarter.blogspot.com/2015/09/the-ultimate-so-far-history-of-gremlin_25.html)
has Hauck's tone circuit sounding a different pitch for each player and
direction, and Bob Pecoraro's explosion as white noise from a
reverse-biased diode shaped by an envelope into a boom; MAME's driver
has a 555 at 93,681.5 Hz into a preloadable counter, and a sample for
the boom. So every step sounds the two players' notes one after the
other -- counts of 120-129 and 128-137 over that 93,681.5 Hz, a semitone
apart, by the way each goes -- and a crash is a second of low noise
falling away. **Chosen**, because the arcade's are not known: those
counts and that envelope; a step every eight frames at a round's start,
a frame fewer every 24 steps down to four; a press turning the head at the
next step, two kept waiting, and never back on itself.

**Two players, or one against the computer.** The left player steers
with W A S D and the right with the cursor keys, and a player alone
against the computer with either -- the owner's choice over the home
version's W A S Z and P L ; ., which played wrong to fingers that know
W A S D. A press waits for the step that turns the head, and two can
wait, so a quick turn and turn again both happen; the first cut kept
only the last press, and a U-turn lost its second key. Space starts two
players and C one against the computer, which steers the right player: straight on, a quarter left or a quarter right, whichever
has the most free cells behind it by a flood fill of up to 64, straight
when it is as good, and now and then a turn that is as good.

**The gate** (`sim/test_action.py`, on `sim/blockade.py`): the
generator's file current; the compiled bytes the same as
`tools/cool8asm.py`'s; mode 2; the border's corners and sides and the 6;
the heads where the arcade starts them; a turn drawn with the corner
joining the ways in and out; a frame of play in every vblank; a crash a
point to the other player; two heads into one cell a point to neither;
the computer turning off a wall and outliving a player who never turns;
six points ending the game; every press turning the head -- at each
frame of a step, a tap shorter than a frame, a turn and a turn again in
one step, both players in one frame, a press back on itself ignored, the
cursor keys for a player alone; the stack. `python sim/blockade.py two` (or
`title`, `cpu`) plays it and writes the frames as PNG.

### `COOLTRIS` — seven shapes into a well, in twenty levels of colour

`demos/cooltris.act`, under the loader of [D102](01-decisions.md), and
nothing to do with the two BASIC COOLTRS demos above: a falling-block
game in the manner of the 1989 NES one, written from its *published
numbers* and none of its pixels. **The numbers**
([tetris.wiki](https://tetris.wiki/Tetris_(NES)),
[its scoring page](https://tetris.wiki/Scoring)): 48 frames a row at the
first level down through 8, 6, 5, 4, 3 to 2 at the twentieth, ten rows a
level, 40/100/300/1200 times the level for one to four rows at once, a
point a cell for a soft drop, and a key that repeats after 16 frames and
then every 6. **The picture** is `tools/mkcooltris.py`'s own: one
bevelled block, a hollow ghost of it, eight frame pieces, a background
weave, and the Namco glyphs Ms. Cool-Man's sheets carry, which Arkanoid
also borrows. `poe check` holds the art file to the generator.

**A block's colour is its palette bank**, so the seven shapes cost one
pattern and seven banks of four, and a shape keeps its colour all game.
The surround -- frame, weave, panels, headings -- is bank 0, written
again at every level from twenty schemes a hue-step of 63 degrees apart,
with the two text banks rebuilt from it, so the twentieth screen is a
different colour from the first while the pieces stay where the eye left
them. The well is ten by twenty cells of 8 x 8 in mode 2's 40 x 30, the
same shape the board's is, with the score, rows and level down one side
and the next piece and the best down the other.

**Kinder than the board**, all of it asked for: the shapes come from a
bag of seven shuffled, so there is no long wait for a long one; a hollow
ghost shows where the piece will land; the space bar drops it there at
once for two points a cell; and C parks a shape beside the next one,
once between one shape and the next. No wall kicks, and a piece still
locks the moment it lands. The levels go on past the twentieth -- two
frames a row to the twenty-ninth and one after that, as the board's own
do -- with the twenty colour schemes coming round again, and play goes
on until the well fills. When it does, the score stays on the screen
under GAME OVER until the space bar or four seconds, so that the game
just played can be read. A new best takes three letters, up and down for
the letter and right for the next place. **Chosen**: the entry delay of
12 frames and the line-clear flash of three steps.

**The turns are the board's own.** They are the Nintendo rotation
system's grids, read off the diagram on
[tetris.wiki](https://tetris.wiki/Nintendo_Rotation_System) cell by cell
and held to it by the gate: the I, the S and the Z have two forms, the O
one, and the T, the J and the L four. Two goes at the table by hand got
it wrong first -- the J's fourth turn was a T, one cell out, and the I,
S and Z had four forms of which the third and fourth sat a row below the
first and second, so turning one twice walked it down the well. Taking
the published grids whole ended both.

**Two more found in the making**, both held by the gate now. The J's
fourth turn was a T, so the gate holds every shape to being the same
shape at each of its four turns. And the name a new best asks for took the
down key still latched from the soft drop -- which asks whether down is
*held* and so never takes its latch -- turning the first letter back as
fast as it was typed; the name entry lets go of its keys as it starts. **Ten tunes, one for every level as it comes up**, all this port's own
and every one written out note by note in `tools/mkcooltris.py`. Each is
thirty-two eighths on voices 0-2: a melody, a bass walking on the even
steps two notes to a chord, and a third or a fifth between them on the
odd ones. The first is the one the port started with, in A minor; the
nine after it keep its shape in their own keys and moods -- D minor
longing, E phrygian dark, C major bright, A dorian hopeful, D minor
driving, E minor marching, F lydian floating, A harmonic minor dramatic,
D dorian restless -- and the step shortens from 13 frames to 9, so the
later ones are brisker. A level plays tune (level mod ten), so the
twentieth screen sounds like the tenth. The effects are on voices 3 to 5.
On the front they play one after another, each twice before the next,
with C to skip on and the number under PRESS SPACE; behind the words,
blocks rain down the well, one to a column, each at its own pace and in
its own colour.
(A first attempt had the generator compose nine of them from keys,
scales and motifs; they were thrown out for being worth less than the
one written by hand.)

Keys: the cursor keys or A S D move it and soft drop it; the space bar,
up or X turns it clockwise and Z the other way; M drops it to the ghost;
C parks it; P pauses; Esc ends it. The space bar starts a game, and a
new best takes three letters.

**Measured**: 12,812 bytes of PRG; a soft-dropped piece reaches the
floor in 30 to 39 frames; four rows at once on the first level score
1,200, and 1,229 with the drop counted.

**The gate** (`sim/test_action.py`, on `sim/cooltris.py`): the art file
current; the compiled bytes the same as `tools/cool8asm.py`'s; mode 2;
the well framed and the seven shapes on the front each in its own bank;
a piece falling with its ghost below it in its own colour; a soft drop
worth a point a cell and the piece locking into the well; M dropping it
to the ghost at once for two points a cell; C parking a shape, refusing
a second time and giving it back; every level bringing its own tune; four rows at
once for twelve hundred; ten rows a level, the surround painted afresh
and the shapes' colours kept; twenty levels with the last at two frames
a row; the bag holding each shape once; a full well ending the game; the
stack. `python sim/cooltris.py play` (or `title`, `rows`, `level`) plays
it and writes the frames as PNG.

### `COOLSW` — COOL SWEEPER, three fields in three themes, and its own music

`demos/coolsw.act`, under the loader of [D102](01-decisions.md): a field
of covered cells, some of them mines; a dug cell shows how many of its
eight neighbours are mines, a dug mine ends the game, and every cell that
is not a mine opened clears the field. The rules are the common property
of every coolsweeper since 1990, with the modern kindness that **the
first cell dug and the eight round it are never mines** -- the mines are
placed on the first dig, not before -- so the first dig always opens
ground to reason from. The picture and the music are this game's own:
`tools/mkcoolsw.py` draws every cell, frame piece, icon and the cursor,
doubles the Namco glyphs Ms. Cool-Man's sheets carry into the logo, sets
out the palettes and writes out the tunes, all into
`assets/coolsw/coolsw_art.act`, which `demos/coolsw.parts` names.
`poe check` holds the art file to the generator. On the screen the game
is COOL SWEEPER; on the disc, where a name has eight characters, COOLSW.

**A cell is 16 x 16, four tiles**, chosen over one 8 x 8 tile a cell so
that a number has room to be a bold digit with a bevel and a shadow
rather than a glyph. What it costs is the field size: mode 2's 40 x 30
tiles hold 18 x 12 such cells with a frame and a score bar, so **the
levels are sized to the screen, not to the 1990 game** -- 9 x 9 with 10
mines, 14 x 11 with 25, 18 x 12 with 45, where Windows had 9 x 9, 16 x 16
and 30 x 16. (One tile a cell would have fitted those exactly; both, by
level, would have drawn every picture twice.) The field is a
checkerboard of two shades of each kind of cell, so the grid reads
without lines; the light and dark squares are separate patterns, and a
number's colour is its palette bank -- eight banks for the eight, in the
colours coolsweepers have always used. 234 tiles in all.

**Each level has a theme, and a theme is the whole palette**: a meadow
for Easy, the sea for Medium, lava for Hard, 256 colours each written in
one go. Everything on the screen draws through banks, so a theme change
repaints the lot with no tile touched, and **the front shows the theme
of the level the cursor is on** as it moves. Three entries cycle: the
twinkle in the background, the cursor's glow, and a band of light up the
logo's letters on the front.

**The cursor is four sprites**, one 16 x 16 corner flipped four ways,
round the cell at the raster's own resolution. It glides -- half the
distance a frame -- and breathes a pixel or three outwards; the same
four brackets mark the level on the front. **The first dig opens its
ground as a ripple**, one ring of cells a frame from the one dug, with a
rising note a ring. **A mine shakes the ground** -- the tile layer's fine
scroll for half a second, the cursor hidden -- then every other mine
shows itself one after another, the one that went off on red, and every
flag that was wrong is crossed.

**The score**: 10 times the level for a cell dug, 5 for each further
cell a dig opens; at the end 25 times the level for every mine the
player flagged. Clearing the field is worth 1000 times the level and 20
for every second under par -- 60, 150 and 300 -- so a fast clear of Hard
is the best score there is. A blown-up field keeps what it earned. The
reckoning is a panel over the field: what the field was worth, the
bonuses line by line, and the score counting up to its total in about a
second and a half. Each level keeps a best with three letters, up and
down for the letter and right for the next, and the front lists them.
The clock starts at the first dig.

**The music is written out note by note in `tools/mkcoolsw.py`**, an
eighth at a time and a bar a line, and the game gives it its shape: a
title theme (D major, sixteen bars, a verse and a soaring second half
with sparkling arpeggios), a tune for each level -- G major and
unhurried for Easy, E minor and uneasy for Medium with a driving
repeated bass and water drops on top, A minor and headlong for Hard
with a galloping octave bass -- and two endings, a fanfare for a
cleared field and a sinking chromatic wail for a mine. Each is five
tracks on voices 0-4: a lead, a sustained harmony, a bass, an arpeggio
and drums. **The player makes the square waves sound played**: every
note falls from a peak to a sustain frame by frame and faster once let
go -- a pluck for the arpeggio, a slow bloom for the lead -- the lead
gets a vibrato once it has sounded for ten frames and a double on voice
5 four steps quieter and a few cents sharp, so the two beat; the drums
are a kick falling in pitch, and a snare, hats and a crash on the noise
channel. **The music quickens by a quarter** when an eighth of the
field's safe cells or fewer are left to open. The effects take voices
6 (a tone) and 7 (noise).

Keys: the cursor keys move, and go round from one edge to the other;
the space bar digs, and on a number whose mines are all flagged opens
the cells round it; Enter or F flags and unflags; P pauses and hides the
field; Esc leaves a game for the front, and on the front restarts the
machine.

**Measured**: 25,021 bytes of PRG, of which 7,488 are the tiles, 1,536
the three palettes and 2,352 the six tunes. On the largest field a frame
of play costs 4,956 clocks at rest with the music playing, of the
139,583 a frame has. The busiest thing the game does is the first dig,
and the first version of it cost **138,395 clocks in one frame** -- the
gate's frame-by-frame profile put 77 % of that in `PlaceMines`, which
asked every one of the 216 cells about its nine. Having each of the 45
mines add one round itself instead took that frame to **23,099**, and
the program 46 bytes smaller.

**The gate** (`sim/test_action.py`, on `sim/coolsw.py`): the art file
current; the compiled bytes the same as `tools/cool8asm.py`'s; mode 2
with the sprites on bank 15; the front with its logo, its three levels
and the cursor on the first, in the meadow's colours; the front's tune
playing the lead as the generator wrote it, note for note from the
pitches voice 0 is given, with its envelope's peak and its double, and
drums on the noise; down picking each level in its own theme and going
round; nine by nine framed and all covered with the score and level
above; the cursor keys moving the cursor round the edges with the
corners following; the first dig never a mine nor next to one, every
count right, exactly the cells the rules open opened, and every cell's
picture its byte; ten points for the dig and five a cell opened, the
clock running; a flag counted, refusing a dig and taken off; a number
with its mines flagged opening round it; the pause hiding the field;
the tune quickening near the end; the last safe cell clearing the field
and flagging every mine, and the score the rules give; a best taking
three letters and the front showing it; the second level blown up --
the shake, every mine shown, the wrong flag crossed, the ending's tune;
Esc leaving for the front; the third level eighteen by twelve in lava's
colours; every frame of play and of the first dig fitting in its frame
on the largest field; the stack. `python sim/coolsw.py play` (or
`title`, `win`, `boom`, `pause`, with a level of 0, 1 or 2 after it)
plays it and writes the frames as PNG.

### `GALAGA` — the arcade Galaga, sixteen stages in four levels, in mode 4

`demos/galaga.act`, Namco's 1981 arcade Galaga under the loader of
[D102](01-decisions.md): stages 1 to 16 as the arcade's rank A plays
them -- the entry waves on the arcade's own paths, the formation's sway
and breathing, the dives, the boss's escorts, the bombs, three
challenging stages with their own creatures and their tally -- in four
levels of four stages, each level with a backdrop across the field's
foot and a tune of its own, and after stage 16 round the four again.
A hobby port for the machine's owner, with no users. **The sprites, the
font and the sounds are the arcade's**; the backdrops and the levels'
tunes are not, and are said to be not.

**Where it comes from.** `tools/mkgalaga.py` reads the four sheets in
`assets/galaga/` -- BlazorGalaga's copies of The Spriters Resource's
arcade rips: the general sprites, an older cut of them, the rotations,
the screens' text -- and writes `galaga_art.act` (`demos/galaga.parts`)
and **GALAGA.DAT**, which the game reads from its own drive
(`demos/galaga.disc`): the sprite patterns it streams into VRAM, the
challenging stages' creatures, the four backdrops' bands, and the
stages' waves and the levels' tunes it loads when it wants them. The
flights, the attack and the stage tables come from the hackbar/galaga
disassembly through two reference models, `tools/galaga_paths.py` and
`tools/galaga_dives.py`; the sounds from `tools/galaga_sound.py`, a model
of the sound CPU's driver over the sound ROM's own streams. `poe check`
holds the generated files to all of it. The backdrops are OpenGameArt's,
cropped and quantised and faded into the black by a dither
(`assets/galaga/README.md` has each one's author and licence, and the
title screen names them): the Earth for stages 1-4, a nebula for 5-8, a
red ridge for 9-12 and a gold planet for 13-16.

**Mode 4, and the formation in the bitmap** ([D113](01-decisions.md)).
Forty characters in rows of ten are more sprites than a line has, so a
character at rest is drawn into the 320 x 240 bitmap, and moving it a
pixel writes only the pixels that change, from lists the generator
makes for every frame and every move. What flies is sprites: the
fighter, two rockets, six flyers of four descriptors each, and the
bombs. Explosions and score pop-ups are pictures drawn into the bitmap
and put back. The backdrop's band, the bottom 64 rows, has its own
eight colours by a raster split, and a copy of it in VRAM to put back
from. The field is the arcade's 224 columns in the middle of the 320,
its 256 rows pressed into 240 below the formation's lowest reach.

**The motion is the arcade's** ([D114](01-decisions.md)): a port of the
sub CPU's path interpreter, its 16-bit coordinates, its ten-bit angle
and its linear turns, flying the ROM's own path bytes; and **so is the
attack** ([D115](01-decisions.md)): the three sortie timers and their
reloads by the enemies left and the stage's time, the first character
at rest sent in id order, every other boss sortie a capture, the
escorts from under the boss launched a frame apart, a bomb at each of a
flyer's chances its mask allows aimed where the fighter is, continuous
bombing when few are left, the arcade's hit windows, the restart's
counts. Points as the arcade gives them: 50 and 100 a bee, 80 and 160 a
butterfly, a boss two hits for 150 at rest or 400, 800 or 1,600 by its
escorts in the air; a fighter more at 20,000, 70,000 and every 70,000.
The challenging stages (3, 7, 11 and 15) fly bees, butterflies, then the
arcade's dragonflies and scorpions -- streamed over the butterfly's
patterns for the stage -- pay 1,000 or 1,500 for a whole wave of eight,
a hundred a hit after, and 10,000 for all forty. After GAME OVER come the
arcade's results, as its screens' sheet lays them out: the rockets
fired, the hits, and the hit-miss ratio to a tenth of a percent.

**What differs, and why.** Six flyers where the arcade has twelve: a
wave waits for a slot, and stage 1's dives begin at frame 1,327 rather
than 895. The sprites are 32: six flyers and two bombs spend them, and a
bomb or a dive with none left is not made -- on stage 16 some forty in a
minute. **The capture is the arcade's** ([D116](01-decisions.md)): the
boss's tractor beam, the sheet's own, grows a row at a time over the
backdrop, holds, and takes a fighter under it up, spinning, turning red;
FIGHTER CAPTURED; and the red fighter goes home with its boss into the
place above it, dives with it, and is worth 500 there and 1,000 in the
air. **Not there yet**: the rescue and the dual fighter (a boss shot on
its way home with a captured fighter takes the fighter with it), the
bonus bee's transformations (their creatures' patterns have no room in
VRAM), the name entry, and a second player.

**The sound** is the arcade's effects and jingles, each rendered frame by
frame from the driver's model and mixed in the driver's order -- tunes
on voices 0-2, effects on 3-5, the fighter's explosion as noise on 6 --
and each level's tune is this port's own, in a key and tempo of its
own, with drums on voice 7 beneath the arcade's sounds.

**The gate** (`sim/test_action.py`, on `sim/galaga.py`) runs it with
GALAGA.DAT on drive 11 of a flash image of its own: the generated files
current; the compiled bytes the same as `tools/cool8asm.py`'s; the title
in mode 4 and the sprites on bank 15; stage 1's forty flying in, each
held to the reference machine frame by frame, all home; the formation
breathing and flapping without a pixel of the bitmap other than the
program's state says; a volley scored, its explosions leaving nothing,
20,000 bringing a fighter; the start theme's notes frame for frame; the
level's tune and drums; the raster split's lines; every frame's work
inside its frame; challenging stage 11's creature, tally and payment;
**stage 1's attack held to `tools/galaga_dives.py` frame by frame for
3,000 frames** -- every flyer and every bomb, down to continuous bombing
-- and stage 16's the same wherever the sprites allow; a crash, the
explosion over the backdrop put back, and a fighter after READY; a
capture -- the beam in its blues, the fighter taken, FIGHTER CAPTURED,
the red fighter in its place, the bitmap exact once the beam is gone; P
pausing and going on; the last fighter lost and the results; then
the path a person takes -- the real ROM booting the demos disc, `DRIVE
11` and `SYS "GALAGA.BIN"`, the title up, space, and stage 1. `python
sim/galaga.py play` (or `levels`, `attack`, `challenge n`, `death`,
`results`, `capture`, `profile [stage frames]`) plays it and writes the frames as PNG;
`flights`, `dives stage frames [x [every]]`, `bitmap`, `shoot`, `split`
and `sound` are the comparisons the gate makes; `sizes` says where the
program's bytes are.

Keys: the cursor keys or Z and X move, space fires, P pauses, Esc
gives the game up.

### `MOTT` — a descent after NetHack, in DawnLike's tiles

`demos/mott.act`, on its own drive: **MOTT.PRG, its theme files, its
names, its help page and its strings are on drive 9**, and only the loader, `MOTT.BIN`, is on
drive 11 -- it names drive 9 -- so the game is on the CoolAction menu and
drive 11, which had 45,568 bytes free, carries 1 KB of it
([D108](01-decisions.md)). The Amulet of Mott lies twelve levels down;
fetch it and climb back to the sun. The game is Rogue's and NetHack's,
and **it is being built in milestones**. **The name is TTOM backwards**, as
Rogue's Yendor is Rodney: the game was YENDOR until the owner renamed
it MOTT, and with it the Amulet, the Wizard, the drive's label and every
file.

**The tiles are DawnLike**, DragonDePlatino's 16 x 16 tileset drawn for
NetHack, on DawnBringer's sixteen colours -- CC-BY 4.0, the sheets in
[`assets/dawnlike/`](../assets/dawnlike/README.md) with their credits
(the title screen carried them too until the owner took them off). Chosen by the owner over Kenney's
Micro Roguelike and ink_slime's 8 x 8 sheet (both CC0, both small enough
to show a whole level at once) and NetHack's own tiles (under the
NetHack General Public License, and in more colours than a bank has):
DawnLike's palette *is* one bank of sixteen, which is what mode 2
gives a tile. The text is DawnLike's own SDS 8x8 font, which has lower
case, where the Namco glyphs the other games borrow have none.

**A cell is 16 x 16, four tiles**, so the screen shows twenty cells by
thirteen of a level forty by twenty-four -- rows 0 and 1 for messages,
2 to 27 the window, 28 and 29 the status -- and the window follows the
hero, jumping to recentre four cells from its sides and three from its
top and bottom. **Mode 2's tiles have no transparency**, and every one
of DawnBringer's sixteen is used somewhere in DawnLike's creatures and
items (measured over the sheets), so no colour can stand for "floor
here". A creature or an item is therefore drawn onto the floor by
`tools/mkmott.py`, and **each band of the dungeon is a theme of its
own**: its floor, its walls, its stairs, and every creature and item on
that floor -- a file of 32,768 bytes, the four pattern banks an
attribute reaches, streamed from drive 9 into VRAM on the stairs in
about eight frames. Bank 0 is the font and the terrain, sixteen wall
pieces chosen by which neighbours are walls; bank 1 the items; banks 2
and 3 the creatures in DawnLike's two animation frames, so a creature
animates by its cell's attribute naming the other bank. The floors
change with depth, as the owner chose: brick halls for levels 1-4,
caverns of brown earth for 5-8, blue crystal stone for 9-12.

**What is in view is in palette bank 0, what is remembered in bank 1**,
the same sixteen dimmed towards the void, so the map fades as the hero
leaves it and no picture is stored twice. **Levels persist**: the
current one is in memory, and each other one is parked in its own slot
of VRAM above the pattern banks, `$9000` up, 1,536 bytes a slot, and
comes back exactly as it was left.

**The level is Rogue's**: nine cells of a three by three grid, most of
them a room and up to two only a turn in a corridor; one cell joined to
a neighbour not yet joined until all nine are; a turn joined to a second
neighbour if it has only one, and where its two corridors leave it the
same way and lie over each other, the stub they leave filled back to
rock, so no corridor ends in nothing; then four to six loops more, as
NetHack's `makecorridors()` digs four or more besides the ones that join
every room; a corridor leaves a room by a door in its wall, half of them an
empty doorway, a third shut, the rest open. Lit rooms are seen whole
from inside or from a doorway -- nine in ten on levels 1-4, seven in
ten on 5-8, half on 9-12 -- and anywhere else the hero sees the eight
cells round. Walking into a shut door opens it (NetHack's autoopen), and
a door is never entered or left diagonally; an empty doorway is no bar.

**The creatures are NetHack's, in DawnLike's pictures.** 45 monsters
from the newt to the vampire lord, the six forms of the two pets, four
of the people later milestones need -- shopkeeper, Oracle, watchman,
priest -- the fountain's water nymph and water demon, and the Wizard of
Mott: 60, and with the three heroes and Platino, all 64 of the pictures
a creature bank holds. A monster's level,
speed, armour class, frequency, difficulty and up to three attacks are
NetHack 3.6's own, read out of `src/monst.c`, so the ladder of danger is
the one players know; which DawnLike cell is which creature is named by
tommyettinger's [DawnLikeAtlas](https://github.com/tommyettinger/DawnLikeAtlas)
(`image_names.tsv`), which is also how the first milestone's heroes were
found to be the wrong race's -- they are the human valkyrie, wizard and,
for the Rogue, bandit now.

**The rules are NetHack's where the game has the thing they govern:**

- **A level's monsters**: one in three rooms, never the room the hero
  comes down into; and a monster arriving out of sight one turn in
  seventy. The kind is NetHack's choice by difficulty -- no harder than
  half of depth and hero's level together, no easier than a sixth of the
  depth -- weighted by frequency; jackals, rats and ants come in small
  groups and hill orcs and killer bees in large ones, halved while the
  hero is below level 3.
- **A blow**: the hero hits when 1 + the role's bonus + the target's
  armour class + the hero's level + the weapon's enchantment beats a d20,
  for the weapon's die, its enchantment and strength's bonus (Valkyrie a
  long sword +1 and +2 for strength, Wizard a quarterstaff +1, Rogue a
  short sword and +2 to hit for dexterity); a monster hits when 10 + the
  hero's armour class + its level beats a d20 plus the attack's place,
  for its dice. Monster against monster is its level and the defender's
  armour class.
- **Speed** is movement points: each turn a monster adds its speed and
  acts once for every twelve, the hero's.
- **Experience** is monst.c's creature worth -- the square of the level,
  more for armour, speed and special attacks, fifty past level eight --
  on NetHack's ladder, 20, 40, 80 ... to level 12 at 20,000; a level is a
  d8 and a d2 of hit points, the Valkyrie one more, and power.
- **Mending** is a hit point every 42/(level+2)+1 turns below level ten.
- **The pet** -- the Valkyrie's and Wizard's a kitten, the Rogue's a
  little dog -- fights hostiles beside it that are not two levels above
  it, and follows as NetHack's `dog_move()` does: towards the hero when
  three or more away, or two and the hero in a corridor or a doorway, and
  about the hero otherwise; and when it cannot see the hero, towards the
  newest of the hero's last 32 steps beside it (`settrack()` and
  `gettrack()`), so it comes round corners and through doors after the
  hero instead of pressing against the wall between. Measured along ten
  levels walked stairs to stairs (`python sim/mott.py follow 1 10`): it
  used to step only where it was nearer in a straight line, and was beside
  the hero on 18 of 282 steps, as far as 18 behind, and beside the stairs
  down on none of the ten; now beside on 123 of 244, never more than 4
  behind, and beside the stairs within three turns' wait on eight. It
  comes down the stairs if it is beside the hero, changes places when the hero walks into it, and grows as
  NetHack's `grow_up()` has it: hit points on each kill, a level at eight
  a level, a housecat or dog at level 4 and a large cat or dog at 6. A
  monster the pet bites bites back.
- **The Wizard's force bolt**: `Z` and a direction, five power, 2d12 to
  the first monster in the line within eight cells.

**Where it is not NetHack, and why.** A monster sees the hero when the
hero sees it, which is the view the game already computes, rather than a
line of sight of its own. None is generated asleep. Special attacks are
the ones these creatures have, cut down: poison is an extra d6 one time
in eight, without NetHack's strength loss or instant death; a
homunculus's bite sleeps the hero for up to ten turns; a wraith's or a
vampire's touch drains a level one time in three; the floating eye's
passive gaze freezes the hero for d(level+1, 10) turns, not NetHack's
d(level+1, 70), which was decided when the game had no saves and would
end most games that strike one; the acid blob splashes and the yellow mold stings. A
leprechaun steals nothing until there is gold. The message area is two
lines with `--More--` when a turn has more to say.

**The things are NetHack's too.** 48 kinds from NetHack 3.6's
`src/objects.c`, cut to what 64 pictures and the program's memory hold:
seven weapons (dagger to two-handed sword, each with its small-monster
die), nine pieces of armour over six slots (leather armour to plate mail,
a small shield, an orcish helm, leather gloves, low boots and a leather
cloak, each with its armour class), eight potions (healing, extra
healing, gain level, gain energy, sleeping, sickness, fruit juice,
water), eight scrolls (identify, enchant weapon, enchant armor, remove
curse, teleportation, magic mapping, light, fire), six wands (light,
create monster, striking, digging, magic missile, sleep), six rings
(protection, regeneration, free action, poison resistance, increase
damage, teleportation), the amulet of life saving, the Amulet of Mott
and its cheap plastic imitation, and gold. Their generation
probabilities and base costs are objects.c's -- the costs waiting for the
shops -- and a level is filled as NetHack's `makelevel()` fills it: gold
one room in three, a thing one room in three with a one in five chance
of another after each, and a thing one kill in six.

**What cannot be seen is not known.** Each game shuffles which
appearance each potion, scroll, wand and ring wears, among NetHack's own
descriptions for them -- ruby, pink, orange, emerald, sky blue, milky and
bubbly potions (water is always clear); scrolls labeled ZELGO MER, JUYED
AWK YACC, NR 9, PRATYAVAYAH, DAIYEN FOOELS, VERR YED HORRE, KERNOD WEL and
ELAM EBOW; glass, balsa, maple, oak, ebony and iron wands; wooden,
granite, black onyx, moonstone, jade and ruby rings -- and DawnLike, which
was drawn for NetHack, has a picture of each of those names, so the
picture is the appearance's. A kind becomes known when using it shows
what it is, or when a scroll of identify says so; a thing is blessed,
uncursed or cursed as `mksobj()` makes it, and that and its enchantment
are known when worn, tried or identified. A name is NetHack's `doname()`,
"a blessed +1 quarterstaff (wielded)", "a scroll labeled ZELGO MER",
"an iron wand (0:5)", with NetHack's `implicit_uncursed` leaving
"uncursed" off a kind that is known, which is what keeps a line inside
forty columns.

**What they do**, as NetHack's `peffects()`, `seffects()` and `zap.c`
have it for these kinds: healing and extra healing mend and raise the
most when they run over; gain level raises a level, and cursed lifts the
hero through the ceiling; sleeping sleeps unless a ring of free action is
worn; identify names one thing, and blessed sometimes everything;
enchant weapon and enchant armor add one, and evaporate what is pushed
past +5 or +3; remove curse uncurses what is in use, or everything if
blessed; teleportation moves the hero on the level, or down one if
cursed; magic mapping shows the level; a wand of digging bores through
walls and rock, or down to the next level; magic missile and sleep reach
every monster in eight cells, striking the first. A cursed weapon welds
itself to the hand and cursed armour or rings will not come off; the
armour class is ten less what is worn and its enchantment and the rings
of protection. The amulet of life saving takes a death and crumbles; a
leprechaun's touch halves the purse and takes it elsewhere. Daggers are
thrown by `f`, the Rogue up to three at once, and come down where they
stop. Each hero starts with NetHack's `u_init.c` things, identified: the
Valkyrie a +1 long sword, a dagger and a +3 small shield; the Wizard a
blessed +1 quarterstaff, a cloak, an attack wand, two different rings,
two potions and two scrolls; the Rogue a short sword, six to fifteen
daggers, +1 leather armour and a potion of sickness.

**Traps and secret doors, as NetHack's `mklev.c` and `trap.c` make
them.** One door in eight is a secret door, drawn as the wall it sits in,
and one cell in 35 of the corridors dug after every room is joined is a
secret passage, drawn as rock; `s` searches the eight cells round the
hero, finding a secret door or passage one time in seven and a hidden trap
one in eight, luck pushing the odds as `rnl()` does, and magic mapping
finds the passages but not the doors. **A room with stairs is never
shut in by secret doors alone**: if every door it has is secret, one is
made a plain shut door, so a hero arriving can always see a way out;
the other rooms can be closets, as NetHack's can. Measured on 600 levels
the game made itself (`python sim/mott.py reach 0 600`, which calls
`MakeLevel` and `MakeCave` on the running machine and walks each): before,
282 corridors that ended in nothing and, on 74 of the 450 room levels,
a stairs-up room from which fewer than 60 cells, and not the stairs
down, could be reached without a search, because a spanning walk and one to three loops
leave most rooms one door, and one door in eight is secret; after, no
dead end, no room of stairs without a door or corridor to be seen, and
every cell of every level reached once the secrets are found. On 121 of
the 450 the stairs down are still behind a secret somewhere, always at
the end of a corridor that runs into a wall -- where to search. Every room of a level gets a trap
while a die of 8 less a sixth of the depth comes up 0, eleven of
NetHack's kinds by `mktrap()`'s choice, each with DawnLike's picture of
it and hidden until it goes off or is found: an arrow trap (thitu() at
level 8, a d6), a dart trap (a d3, poisoned one time in six), a falling
rock trap (2d6, 2 under a hard helmet), a squeaky board (every monster on
the level wakes), a bear trap (2d4, and four to seven turns held -- a
diagonal pull always loosens it, a straight one one time in five), a
sleeping gas trap (from depth 2, up to 25 turns asleep), a pit and from
depth 5 a spiked pit (two to seven turns climbing out), a trap door
(down one level, one more each time a d4 comes up 1, never from the
bottom), a teleportation trap and from depth 5 a level teleporter, which
throws the hero up to three levels past the current one and is gone
after. A trap already seen is escaped one time in five, and an arrow,
dart or rock trap runs out one time in fifteen. Poison is NetHack's
`poisoned()`: a ring of poison resistance shrugs it off; otherwise one
time in thirty for a missile, or eight for the spikes, it kills outright,
and some of the rest take hit points. The gravestone says which: "killed
by a little dart", "fell into a pit of iron spikes", "poisoned by a fall
onto poison spikes".

**Fountains**, one room in ten. `q` standing on one asks "Drink from the
fountain?", and a drink is `drinkfountain()`'s d30: the cool draught
nine times in 30, tepid water, foul water, contaminated water (a d10, a
d4 with poison resistance), an endless stream of two to six snakes, a
water demon, a curse on one thing in five in the pack, the stalking
image, a sight of every monster on the level, a water nymph, bad breath
that sends every monster running, the quenched thirst -- and one time in
three the fountain dries up. The water nymph and the water demon are
monst.c's too, and fill the creature banks' last two pictures; the nymph
is generated as NetHack generates her, and steals a thing from the pack
and teleports away with it, carried until she dies.

**Altars and prayer.** One room in twenty has an altar -- NetHack's is
one in sixty, and a twelve-level dungeon would show one a game -- lawful,
neutral or chaotic, and a thing dropped on it shows its curse: "There is
a black flash as a cursed dagger hits the altar." `#pray` is NetHack's
`dopray()`, down to its numbers: the heroes' alignments (the human
Valkyrie and Wizard neutral, the Rogue chaotic) and gods (Tyr, Odin,
Loki; Ptah, Thoth, Anhur; Issek, Mog, Kos), the alignment record from 10
and a point a hostile's kill, luck, the prayer timeout from 300 and down
a turn at a time. A prayer in major trouble -- hit points at 5 or a
fifth or sixth of the most -- is heard with the timeout under 200, in
minor trouble -- something cursed worn or wielded -- under 100, and
otherwise only at 0; three turns of prayer in which, if the god is
pleased, no monster's blow lands ("starts to attack you, but pulls
back"); then `pleased()` mending the hit points, uncursing what is
worn, and with the record high and nothing wrong a golden glow, a blessed
weapon or every curse lifted -- and the timeout set again by `rnz(350)`.
Too soon costs three luck and angers the god; an angry god's
`angrygods()` ranges from displeasure through a lost level, a black glow
cursing things and a water demon, to the lightning bolt, "killed by the
wrath of Odin". Attacking a peaceful creature asks first and costs a
point of alignment; killing one costs six, and luck.

**Elbereth.** `E` writes in the dust with a fingertip -- a line typed at
the keyboard, up to sixteen letters, added to what is there or wiping it
out first -- and walking onto an engraving reads it. As NetHack 3.6's
`onscary()` has it, a hostile beside a hero standing on exactly
"Elbereth", in any case, runs instead of striking, unless it is human --
the soldier, the shopkeeper and the town's people -- or peaceful. The
dust wears as NetHack's does: a monster standing on it rubs out a
letter a move, the hero's melee three and a throw two, and time one now
and then, each letter turning into the one below it on NetHack's rubout
table.

**Shops, as `mkroom.c`, `shknam.c` and `shk.c` run them.** From depth 2,
while a die of the depth comes up under 3, a room with one door and no
stairs becomes a shop: a general store, used armor dealership,
second-hand bookstore, liquor emporium, antique weapons outlet, jewelers
or quality apparel and accessories by `shknam.c`'s odds, lit, stocked on
every cell but the row along the door's wall, with a keeper by one of
the eight first names of its kind -- Asidonhopo, Kalecik, Lahinch -- on
the post inside the door and 1,030 to 4,000 gold. The keeper greets the
hero at the door ("Hello, Valkyrie!  Welcome to Asidonhopo's general
store!"), quotes a thing picked up ("For you, esteemed lady; only 8
zorkmids for this axe.") at `get_cost()`'s price -- objects.c's cost, ten
more a point of enchantment, a third more for one thing in four whose
kind is unknown -- and lists it unpaid in the pack; stands on the post
while the hero owes and steps aside when not; buys what the hero drops,
if it is the shop's kind of thing, for half ("Asidonhopo offers 4 gold
pieces for your axe.  Sell it?"), and bills a potion drunk or a scroll
read before it is paid for, and a fifth of a wand's cost a zap. `p` pays, a thing at a time while the gold lasts.
Leaving owing -- out of the door, by teleport or down a hole -- is
robbery: "You stole 8 zorkmids worth of merchandise.", the keeper angry
and after the hero, and appeased by the stolen sum paid back, or a
thousand gold two times in three.

**`?` shows the keys**, a page of `MHELP.DAT` over the map, and the
title no longer carries the art's credit, at the owner's word -- it
stays with the sheets in `assets/dawnlike/` and here.

**The dungeon's branches, as NetHack's `dungeon.def` lays them out, cut
to size.** A game is seventeen levels, and each has its own VRAM slot:
the dungeon's twelve by depth; the Gnomish Mines, three levels opening
from a second stairs down on level 2 or 3; and Sokoban, two levels up
from a second stairs up on the level above the Oracle, who sits on level
5, 6 or 7. A level knows its number and its depth apart -- the mines'
are one to three below where they open, Sokoban's one and two above
where it starts -- and every way off a level (stairs, a branch's stairs,
a trap door, a hole, a level teleporter, digging, a cursed scroll or
potion) asks which level is under or over this one. The status line's
`Dlvl` is the depth, as NetHack's is.

**The mines are caves, made as `mkmap.c` makes them**: two cells in five
floor at random, one pass that keeps a cell with three or four floor
neighbours and settles the rest, one that makes rock of a cell with
exactly five, two more that make rock of a cell with fewer than three;
every cave then joined to the first by a corridor dug across and down,
and the rock round the floor walled. The passes and the joining's flood
fill are assembly, over the cell maps' fixed addresses: 45 frames for a
level, where CoolAction! took 74 and 717 bytes more. Four gnomes, a
gnome lord, a dwarf and a hill orc live in each, with things and gold,
and more of both at the bottom, which has no way down. The caves are
dark, so the hero sees the cells round it -- NetHack lights most of its
mines' levels, which needs a line of sight the game does not have.

**The mines' second level is a town**, the game's own after NetHack's
Minetown: a lit square inside a wall with a temple, a general store,
three houses, two fountains, three watchmen and three gnomes, all at
peace. Its store is a shop like any other, with its keeper. **The temple**
has an altar of an alignment chosen when the level is made and an aligned
priest by it; walking in, as NetHack's `intemple()` has it, "The priest
of Odin intones: Pilgrim, you enter a sacred place!" and then a hero of
the altar's alignment in good standing experiences a sense of peace --
"a" for the pious, "an unusual" below piety -- and anyone else a
forbidding feeling. `#chat` with the priest is `priest_talk()`: with no
gold, poverty preached; otherwise a contribution asked for and a number
typed, and a gift under 200 a level thanked ("Cheapskate." if it was
mean), under 400 a blessing, under 600 protection -- two to four points
off the armour class the first time, one more after -- and anything more
gratitude.

**Delphi, on the Oracle's level**, the game's own after `oracle.des`: a
lit court, a ring of wall with a gap each side, and the Oracle's chamber
inside it with four fountains round her; four forest centaurs at peace in
the court, and three monsters that are not. `#chat` with her is
`doconsult()`: "Wilt thou settle for a minor consultation?" for fifty
zorkmids, a rumour -- sixteen true ones, written for the game in the
voice of NetHack's, since NetHack's own rumours and oracles are its
authors' text -- and five experience the first time; declined, "Then
dost thou desire a major one?" for 500 and fifty a level, one of four
pages of oracularity over the map -- or, for less than the price, the one
she gives when she scornfully takes all the hero's money -- and a tenth of
the price in experience the first time (a twenty-fifth after a minor
one).

**Sokoban, two small puzzles** drawn for the game and proven solvable
by `tools/mkmott.py`, which searches every map it writes and refuses one
it cannot solve. Boulders are NetHack's `moverock()`: pushed a cell ahead
of the hero, never aslant in Sokoban ("The boulder won't roll diagonally
on this floor."), never into a wall, a shut door, another boulder or a
monster; into a hole it falls and plugs it, into a pit it fills it. The
levels are known from the start, their holes seen; a step into a hole
is not escaped -- "Air currents pull you down into a hole!" -- and lands
on the level below; the hero cannot squeeze diagonally between boulders
and walls; nothing teleports and nothing digs. The top of the second
holds an amulet of life saving and gold.

**The Amulet and the climb back, as NetHack runs its endgame's pieces.**
Level 12 holds the Amulet of Mott in a room away from the stairs, and
the Wizard of Mott -- monst.c's Wizard of Yendor, level 30, armour class
-8, more than a hero of the twelve levels can hope to kill -- asleep
beside it. Carrying it, the Wizard wakes one turn in forty, as
`amulet()` has it ("You get the feeling that something is watching
you."); his blow is `AD_SAMU`, and one in twenty steals the Amulet and
takes him elsewhere with it, and only killing him gets it back. Once it
has been lifted, every 50 to 250 turns `intervene()`: a vague
nervousness, a black glow cursing things, every monster on the level
woken, a nasty -- an ettin, a troll, an owlbear, a vampire lord -- beside
the hero, or the Wizard back ("So thou thought thou couldst elude me,
fool."); and a successful prayer's timeout grows by another `rnz(1000)`.
Climbing the dungeon's stairs with it above level 9, one time in four, "A
mysterious force momentarily surrounds you..." and the hero goes down
instead -- up to three levels for the lawful, two for the neutral, one
for the chaotic -- or somewhere else on the level. Up the stairs of level
1 with it, the hero climbs out into the sunlight and the game is won:
the hero's picture where the grave would be, INTO THE SUN, and how long
it took.

**Platino**, DawnLike's author's own creature, whom his licence asks be
hidden well in any game that uses the tiles, is the last of the
creatures: harmless, never generated, and he pops up only beside a hero
who writes his name in the dust.

**Music by depth, and sounds.** Ten tunes written for the game -- the
title's march, the halls' walking A minor, the caverns' slow Phrygian,
the depths' pulse in C minor, the mines' digging song, the town's lilt,
Sokoban's staccato puzzle, Delphi's arpeggios, and a death and a victory
that do not loop -- are in `MMUSIC.DAT` on drive 9, 786 bytes, as events
of three voices: a lead, a bass and a harmony, each note fading to half.
`tools/mkmott.py` writes them from note names. The player reads a step
from the flash when it is due, in the frame loop, which never runs while
another stream is open. **The music is not played all the time**: the
title's plays on, but a part of the dungeon's plays twice through when
the hero comes into it -- the halls, the caverns, the depths, the Mines,
the town, Sokoban, Delphi -- and then the dungeon is quiet; another level
of the same part does not start it again.

**What is heard instead, and not all the time either.** On a fourth
voice, a sound is a pitch swept and faded, or swelled and faded, noise
or tone, repeated with its pitch a little off each time: a blow landing
or missing, a kill, the hero hurt, a level gained, a door, gold, a trap,
the stairs, a wand or a spell, a prayer's end, a fountain, a boulder.
A monster's blow sounds as its kind -- a bite, a claw's scratch, a
weapon's clang, a sting, the thud of a butt, a kick or a squeeze. In the
quiet, one of the part's two noises comes 20 to 37 seconds apart: in the
halls footsteps or a drip, in the caverns a drip or the wind, in the
depths a rumble or the wind, in the Mines a pick or a drip, in the town
footsteps or a creak, in Sokoban a creak or a drip, at Delphi bubbling or
the wind -- counted by dice of their own, so how long a player waits
never changes the game's. And NetHack's own: a fight out of sight is
heard, `noises()`, "You hear some noises in the distance.", once in ten
turns unless it has come nearer or gone further; and `dosounds()`, a
fountain on the level one turn in 400 ("You hear bubbling water."), a
tended shop the hero is not in one in 200 ("You hear the chime of a cash
register."), a temple one in 200 ("You hear someone praising" its god),
and the Oracle out of sight one in 400 ("You hear convulsive ravings."),
each with a sound of its own.

**Where milestone 5 is not NetHack.** The Mines are three levels, not
eight, with a town and no Mines' End luckstone; Sokoban two levels, not
four, with a prize, not a zoo, and no luck penalty for its rules broken;
the maps are the game's, not NetHack's; the rumours and oracularities are
the game's; the town's watch does not guard the fountains or the shop.
`#chat` is the second long command.

**Where milestone 4 is not NetHack.** Monsters walk round traps rather
than into them, which spares every trap its monster half. No Keystone
Kops: the robbed keeper is the punishment. No credit, itemized billing,
selling to a keeper without gold, or shopkeepers leaving their level.
**The shop's loopholes are kept on purpose**, found in a review after
milestone 6 and left in by the owner for players to discover: a wand or
a thrown weapon never angers a peaceful -- a keeper put to sleep can be
walked past with the goods, or killed from across the room; an angry
keeper is paid only inside the shop; paying stops at the first thing the
gold does not cover; the keeper's gold is lost when he dies; the post
inside the door is sold and bought on; the one-in-four surcharge is shop
stock's alone and gone once bought; an unpaid thing's price follows what
is known and the keeper's mood; and digging through the shop's wall or
floor costs nothing but the robbery. The fountain has no wish, no Excalibur and no pools; an altar cannot be
converted, as there are no corpses to sacrifice; an angry god's minion is
the water demon, the one demon the game has. `#pray` is the one long
command so far.

**Memory, measured at the end of milestone 3, and the room made after
it.** The PRG was 45,525 bytes from `$1400`, its last byte at `$C5D4`,
leaving 14,635 below `$FF00`; `tools/cool8asm.py --pressure` put 33,804
of it in routines -- the largest `Read` 1,452, `MakeLevel` 1,274 and
`Name` 1,050 -- and milestones 4 to 6 were estimated at more than that.
The owner chose three ways to make room, and all three are in
([D109](01-decisions.md#d109--room-for-mott-dead-routines-dropped-low-ram-for-the-payload-names-on-the-disc)): **the compiler drops the routines nothing reaches**, the
library's `Line`, `Clg` and pixel runs among them, 2,113 bytes; **the
level's three cell maps**, 2,880 bytes, are bound to `$0800`-`$133F`,
below the program, in RAM the loader leaves to it and nothing loads
into; and **the names** of the creatures, the kinds and the
appearances, 1,323 bytes, are 24-byte records in `MNAMES.DAT` on drive
9, read from the flash when a message needs one -- 1,198 saved net of
the routine that reads them. The PRG is now **39,334 bytes**, its last
byte at `$ADA5`, with **20,826 free** below `$FF00`: 31,770 in routines,
4,175 in the messages' own strings, the rest tables and working arrays.
The special levels' maps go on the disc the same way when milestone 5
makes them.

**Memory at the end of milestone 4.** Milestone 4 took the PRG from
39,334 bytes to 55,270, 4,890 short of the top of RAM with two
milestones to come, and it came back down by three more measures
([D110](01-decisions.md#d110--strings-off-the-image-and-routines-that-release-their-own-parameters)), after the game's `--pressure` report and the
suites' own clocks: **the messages left the image** -- the compiler's
`#"text"`, a string that is a number in the program and a record in
`MOTT.STR` on drive 9, which a message asks for when it prints; 250 of
them, 7,404 bytes of file -- **routines pop their own parameters** where
that saves bytes -- a routine called from enough places spends five
bytes an exit where every call site spent three -- 4,459 bytes of this
PRG; and **a level's state beyond its cells is one run of memory**, so
parking and unparking a level is two copies instead of sixty, 1,373
bytes. The PRG is **49,438 bytes**, its last byte at `$D51D`, with
**10,722 free** below `$FF00` for milestones 5 and 6: 44,653 in
routines, 957 in the short strings still in the image.

**Memory at the end of milestone 5.** The branches, the caves, the
special levels, the Oracle, the temple and Sokoban added 5,635 bytes to
the PRG -- 6,332 before the cave's loops became assembly -- so it is
**55,073 bytes**, its last byte at `$EB20`, with **5,087 free** below
`$FF00` for milestone 6. The maps are not in it: `MLEVELS.DAT` on drive 9
holds the four special levels, 1,100 bytes each, cells, rooms, stairs and
up to twenty features, and `MPAGES.DAT` the Oracle's pages beside the
keys ([D111](01-decisions.md#d111--motts-special-levels-drawn-in-the-tool-proven-and-read-from-the-disc)).

**Memory at the end of milestone 6.** The Amulet's run, Platino and the
victory took 1,192 bytes, the music and the sounds 1,209, the quiet and
what is heard in it 1,347, the corridors that end nowhere and the rooms
of stairs shut in put right 516, the pet following the hero's steps 313:
**59,650 bytes**, its last byte at `$FD01`, **510 free** below `$FF00`.

**Saving, as NetHack does it.** `S` asks "Really save?", parks the level
the hero is on in its slot -- without the shop's reckoning, since the
hero has not left -- and writes `MOTT.SAV` on drive 9: its eight sectors
erased, the stamp of the build, the game's whole run of globals from
`save_from` to `save_end`, and every level made from its VRAM slot,
"Saving... level 3 of 9" as each goes; then its state, last; then "Be
seeing you..." and the title. The title reads the file's head and, for a
save this build wrote and nobody has played on from, offers "C: continue
your saved game"; `C` reads it all back, clears the state byte -- NetHack
deletes a save when it is restored -- and enters the level where the hero
stood with "Hello Valkyrie, welcome back to MOTT!". Each byte is kept
inverted, so the zeros of a level are never programmed: the machine
writes one byte a request, which on the board is a flash write cycle
each, and a save of a dozen levels is some thousands of them. The file,
its layout and the room made for it are
[D112](01-decisions.md#d112--motts-saves-a-sector-aligned-file-rewritten-in-place-and-the-room-made-for-it);
the board's write path is untested, and the gate runs it on the machine
model.

**Memory with saving.** Saving took 1,350 bytes and the program 840 past
`$FF00`; the message helpers gave back 1,392, the scratch buffers moved
to low RAM 182, and the compiler's shorter shapes 531: **58,895 bytes**,
its last byte at `$FA0E`, **1,265 free** below `$FF00`.

**The grave**: when the hit points run out, "You die...", then DawnLike's
gravestone and who died, what killed them, on which level, at which
experience level, after how many turns and with how much gold.

**The plan**, decided with the owner before any code:

| milestone | what it brings |
|---|---|
| **1 — done** | the themes from drive 9; the title with the three heroes and the credits; Rogue's level; seeing and remembering; doors; stairs; persistence |
| **2 — done** | monsters and combat by NetHack's numbers, the three roles, experience, the pet, the force bolt, the grave |
| **3 — done** | the things by NetHack's numbers: the pack, wielding, wearing, gold; potions, scrolls, wands and rings under appearances shuffled each game; blessed, uncursed, cursed; what each does |
| **4 — done** | shops and their keeper; altars and prayer; fountains; traps and secret doors; Elbereth in the dust; `?` |
| **5 — done** | the special levels: the Oracle, a small Sokoban up from below it, and a cave branch after the Gnomish Mines with a town |
| **6 — done** | the Amulet on level 12 and the climb back; music by depth and the effects; the Platino sprite hidden, as DawnLike's author asks |
| **7 — done** | saving, asked for after 6: `S` saves and ends the game, the title's `C` continues it, and the save is used once played on |

Chosen with the owner and not in it: hunger (so food is not a clock).

Keys: the cursor keys, the keypad or `h j k l y u b n` move, and two
cursor keys held together go diagonally; a key held repeats after ten
frames, every third after that; moving into a monster attacks it and
into the pet changes places; `>` and `<` take the stairs, and Enter the
stairs the hero stands on; `.` rests a turn, `s` or keypad 5 searches
one; `S` saves the game and ends it, and the title's `C` continues it. NetHack's letters for the rest: `i` the pack, `,` picks up, `d`
drops, `w` wields, `W` wears, `T` takes off, `P` puts on, `R` removes,
`q` drinks (from a fountain too), `r` reads, `z` zaps, `t` throws, `f`
fires daggers, `:` looks here, `\` lists the discoveries, `Z` casts, `p`
pays, `E` engraves, `#` takes a long command (`#pray`, `#chat`), `?` shows the
keys; a thing asked for is chosen by its
letter from the pack shown over the map, a direction by a movement key,
and `>` or `<` for down and up. Gold walked over is picked up. Ctrl+R
draws the screen again; Esc asks whether to quit, and on the title
restarts the machine.

**Measured**: milestone 1, 13,742 bytes of PRG, the art table included;
milestone 2, 26,289; milestone 3, 45,525, and 39,334 after the room
was made; milestone 4, 49,438; milestone 5, 55,073; milestone 6,
59,650; with saving, **58,895**. On drive 9 three theme files of 32,768 bytes, `MNAMES.DAT` of
12,000 (250 names at 48 bytes), `MPAGES.DAT` of 5,520 (six pages),
`MLEVELS.DAT` of 4,400 (four levels), `MMUSIC.DAT` of 786 (ten tunes),
`MOTT.STR` of 9,829 (325 strings) and `MOTT.SAV` of 32,768, erased on a
sector; the loader of 1,044 on drive 11.

**The gate** (`sim/test_action.py`, on `sim/mott.py`): the art table
and theme files what the sheets make; the compiled bytes the same as
`tools/cool8asm.py`'s; the program at `$1400` with its cell maps at
`$0800`, outside the PRG; the creature table monst.c's numbers, and the
creatures' and things' names in `MNAMES.DAT` and not in the PRG;
MTHEME0.DAT in the pattern banks byte for byte; the title saying MOTT and
no credits, and the palette's
banks; the hero chosen. The dungeon, with its monsters cleared: level 1's
monsters all of difficulty 1 and the kitten beside the Valkyrie; one
stair up under the hero, one down, every floor and corridor reachable,
seven to nine rooms each walled but for its doors; every cell in the
window the picture its byte says -- terrain in view or remembered, the
hero, a monster in view; a lit room seen whole; a wall refusing a step
without taking a turn; a shut door opened by walking into it, stood in,
and not left diagonally; the walk to the stairs down with the window
following and what was left behind dimmed; level 2 made under the
stairs and level 1 back exactly as it was left, its monsters too; the
way out refused without the Amulet; the caverns' theme at depth 5 and
the depths' at 9; every monster a deep level makes of NetHack's
difficulty for it; no stairs down on level 12; Esc asking and y leaving
for the title. The creatures: moving into a newt attacks it and its
kill is worth monst.c's experience; a sewer rat's bite taking hit
points; twenty points making level 2 with its hit points; the pet
killing a newt beside it and growing; changing places with the pet; the
pet coming down the stairs; a floating eye's gaze freezing the hero for
turns and then letting go; mending; the status lines; the grave naming
the soldier ant and the level, and Enter back to the title; the Wizard's
force bolt taking five power and 2d12 from the jackal in its line. The
things: objects.c's class, number, slot, probability and cost for every
kind; the Wizard's things known and the appearances shuffled; `i`
listing the pack under its classes; the Valkyrie's things and armour
class 6; gold walked over into the purse and the status line; `:` and
`,` and `d`, the floor showing the thing's picture; ring mail worn and
taken off, cursed boots that will not come off; a cursed axe welded to
the hand; a ring of protection in the armour class; an unknown potion of
healing drunk and known; sleeping yawned off with free action; identify,
enchant weapon, enchant armor and magic mapping read; a wand of sleep
stopping a gnome lord and a wand with no charges; daggers fired and
landing; an amulet of life saving taking a death; the discoveries; a
thing left on a level there on coming back; the
stack. Milestone 4: a level's parked state one run of memory that fits
its slot; the traps' names and depths, the gods and the keepers' names on
disc; `?` from `MHELP.DAT`; an arrow trap shooting, seen and drawn; a
bear trap holding the hero four to seven diagonal pulls; `s` finding a
secret door and a hidden pit; a fountain asked for and drunk; a cursed
dagger's black flash on an altar; `#pray` typed, asked, and Odin mending a
hero in trouble, then a second prayer too soon costing three luck and the
god's anger; `E` writing Elbereth and a jackal beside it running without
a bite; a shop poked round the hero's room: Asidonhopo's welcome, an axe
quoted at 8 and unpaid, `p` paying for it, the keeper buying it back for
4, and the hero out of the door owing having stolen 8 zorkmids' worth
with the keeper angry; a water nymph stealing a potion and carrying it;
Milestone 5: the mines' and the Oracle's levels in their ranges; the
branch's second stairs down on the mines' level; a mines level a cave of
more than 150 floor cells, every one joined to the stairs up, none on the
edge, all walled, with its gnomes, dwarf and orc, and the depth and theme
the mines'; the town's temple, altar, priest, general store, watchmen and
gnomes at peace; into the temple with the priest's words and an unusual
sense of peace; `#chat` with the priest and 500 given at level 1 for
protection off the armour class; the mines' bottom without stairs down,
and three climbs back to the branch's stairs; Sokoban up from level 4,
its boulders where the map puts them, its holes seen, its map known; a
boulder refused aslant; a step into a hole down to level 4 and back; both
puzzles solved through the keyboard, push by push, as `sokoban_solve()`
finds them, the stairs up reached and the prize taken; Delphi with the
Oracle, four fountains and four centaurs at peace; a minor consultation
for fifty, a rumour and five experience, and a major one for 550 with a
page over the map; the stack. Milestone 6: the title's tune playing, the
halls' twice through and then quiet, and not again on the next level of
the halls; a noise of the halls' when its count comes round, and the next
20 seconds or more off; a jackal's bite sounding as a bite; the pet's
fight out of sight heard as noises in the distance; a fountain on the
level heard, bubbling; the depths' tune and the stairs' sound; level 12's Amulet with the
Wizard asleep beside it; the Amulet taken and the Wizard's malice set; his
blow stealing it and his carrying it off, and killed, his dropping it; an
intervention when the count runs out and the next set; the mysterious
force sending the hero down on the stairs; Platino written for and
appearing; up the stairs of level 1 with the Amulet into the sunlight,
the game won and the victory's tune; a cursed ring dropped when it is
not worn, and worn, neither dropped nor taken off; 160 levels made by the
game's own routines, every cell reached with the secrets found, no
corridor a dead end, and no room of stairs without a door or corridor to
be seen; a Wizard's kitten keeping up along three levels walked stairs to
stairs, never more than six behind and beside the stairs down to come
along on two of them; `S` asking, writing the game and going back to the
title, which offers it; `MOTT.SAV` on a sector, its state written last, the
largest save inside it; the program loaded afresh with its low RAM and
parked levels wiped, and `C` bringing back the level, the hero, the pack,
the monsters, the things, the parked levels and what is known; the save
then used, and offered no more; and from the demos disc, MOTT.PRG, its themes, names, pages, levels, music, strings and save file on drive 9,
only the loader on 11, and `SYS "MOTT.BIN"` from BASIC finding its
program and its theme there. `python sim/mott.py walk` (or `title`,
`stairs`, `deep`, `fight`, `scene`, `tour`, `shop`, `branches`) plays it and writes the
frames as PNG; `reach 0 n` makes n levels and says what a walk over each finds, and
`follow role n` walks n levels stairs to stairs and says how the pet kept up.

### `SLIDES` — the old test pictures, as fully as mode 6 can show them

`demos/slides.act`, on drive 11, reading drive 10: every `.PIC` there in
catalogue order, the space bar for the next, round again after the last,
Esc to reset the machine. The pictures are image processing's old test
set -- the USC-SIPI Mandrill and Peppers, Kodak's parrots (`kodim23`) and
painted face (`kodim15`) -- which `python tools/mkpics.py --fetch`
downloads and converts. **They are not in the repository**, and neither
is a screenshot of them ([D103](01-decisions.md);
[`assets/pictures/README.md`](../assets/pictures/README.md) says why,
and why Lena is not among them).

**Mode 6 is the machine at its most colourful**: 256 × 240, a byte a
pixel, all 256 palette entries on the screen at once, each any of 4,096.
Each picture brings its own 256 -- the machine's frame shows 256, 254,
254 and 252 different colours for the four, the black border included
-- chosen by libimagequant among the
4,096 the palette holds, dithered against exactly those, and cropped to
the screen's 16:15 about the centre.

**The file is the hardware's own bytes**: `PIC`, a version, the mode,
the border's palette index and two reserved, then 512 bytes of palette
in the form `PAL_DATA` takes, then 61,440 pixels as VRAM holds them --
61,960 bytes. `tools/mkpics.py`'s docstring is the layout; `pack` and
`unpack` there are its one implementation on the host. **Version 2 adds
a second file**, `NAME.RPL`: row by row, the entries to rewrite -- two
slots written in the blanking before a row, then up to fourteen for the
row after, written while the row is drawn
([D104](01-decisions.md)). A picture and its list are under 74 KB, so
the drive holds six.

**Showing one is two streams and two vertical blanks.** The header and
the palette come into memory, 33,832 clocks through `FlashRead`; at the
next frame the palette goes black -- 3,603 clocks, inside the blank's
11,970, so the old picture goes all at once; the pixels stream from
`FLS_DATA` to `VRAM_DATA` in an `ASM` loop; at the next frame the new
palette goes in, 5,669 clocks, so the new picture arrives whole.
Measured on the machine, from `Show` to the next key poll: 2,370,373
clocks, 283 ms -- 2,089,180 of them the stream, **34 clocks a byte,
which is the flash's own rate and not the loop's**, and 237,804 three
frame waits. The loop itself is 14 clocks a byte, and `FLS_DATA` holds
every read off until the shifter has the next byte
([04-system.md §4.8](04-system.md)).

**This paragraph said 149 ms, and the machine was wrong.** It then
handed `FLS_DATA` over at once, so the stream measured 14 clocks a byte;
the documents said the flash delivered one in 16; and the RTL's shifter
takes 34, which `sim/tb/cool8_flash_tb.v` now measures and the machine
now models. SLIDES was the first program fast enough for the
difference to show: every earlier reader of the flash was a compiled
loop slower than the wire.

**The compiled version was measured first, and failed its own gate.** A
`FOR` over the palette took 53 clocks a byte -- 27,201 for the 512, more
than twice the blank -- and the gate reported the top 57 lines of a
frame drawn under a palette half written. The pixel `WHILE` took 37
clocks a byte, 92 % of a picture's time. Both loops are assembly now,
and they took SLIDES from 4,791 bytes to 4,711; turning the cursor off
put it at 4,719.

**The cursor was on over the first version's pictures, and no gate saw
it.** The text cursor is its own overlay, drawn in every mode, and BASIC
leaves it on through `SYS` and the loader, so it blinked in the middle
of the Mandrill -- where the owner saw it. The gate's bare machine has
the cursor off from reset, so it could not: it now turns the cursor on
in mid-screen first, as BASIC leaves it, and looks at the frame again
half a blink later.

**The screen found the waste in the palette.** The first conversion
counted palette indices -- 254, 252, 255 and 201 -- while the frame
showed 242, 227, 232 and 163 different colours: libimagequant places
its colours at full precision and posterises after, so neighbours
round onto one 12-bit colour, and the painted face threw away 93 of
its 256. `mkpics.py` now gives the distinct ones back to it as fixed
colours and lets it place the freed slots again, until all differ or a
pass frees none.

**And more than 256 colours: the palette changes between rows**
([D104](01-decisions.md)). The four pictures are version 2: every row
is drawn in a palette of its own, up to sixteen entries from the row
above's -- two rewritten in the blanking before the row, to entries the
row above used, and up to fourteen while the row above is drawn, to
entries it does not use. `Raster()` does it every frame, locked to
`VID_RASTER`, after `Commit` has put row 0's palette back in the blank.
**The machine's frame shows 822, 523, 628 and 446 different colours**
for the Mandrill, the Peppers, the parrots and the painted face, where
one palette showed 256, 254, 254 and 252, and each sits 22 to 48 %
closer to its original once both are blurred as the eye blurs
dithering. SLIDES is 3,773 bytes with it.

**Finding it cost a compiler bug.** Every version-2 picture was refused
at first: `LoadRpl` builds its change list's name with `rpl_name(i + 1)
= pic_stem(k * 8 + i)`, and a store into a byte array at a computed
byte index popped its value over its index, so the stem went 82 bytes
past the array and the catalogue was searched for a blank name. The
compiler is fixed ([15-action.md §3](15-action.md)), `test_features`
holds the shape, and every other program on the disc compiled
byte-for-byte the same with the fix -- none had used it.

**Gate-enforced** (`test_slides` in `sim/test_action.py`). On a flash
image of its own -- two made-up pictures, with a text file, a `.PIC`
too short to be one, a `.PIC` of an unknown version, a version-2 `.PIC`
with no change list, and a made-up version-2 picture whose rows each
bring three entries and recolour two: the first picture's pixels in
VRAM from `VID_BASE`, its 256 entries committed and its border; every
raster pixel of a frame the picture's or the border's; the palette black
and back each inside a blank; a space skipping the bad file to the
second; the next skipping the list-less picture to the made-up raster
one, its frame every row through its own palette, pixel for pixel, and
**the machine's log of every palette write held to
[04-system.md §5.9](04-system.md)** -- of 2,906 writes in two frames,
none lands under a pixel showing its entry, and the blanking writes land
33 to 61 clocks after `VID_RASTER` names their line, where 70 is the
last that beats its first pixel; round again to the first; and an empty
drive saying so on the text screen. Then, once `poe demos` has put the
real pictures on the disc, the path a person takes: the ROM booting it,
`DRIVE 11`, `SYS "SLIDES.BIN"`, all four in turn -- each exact against
its own rows' palettes, its log clean -- and round again. `python
sim/test_action.py --slides` writes each picture as the machine shows
it to `sim/build/slides_<name>.png`.

**Adding a picture** is an entry in `SOURCES` -- the file, where it came
from, its SHA-256 -- then `--fetch` and `poe demos`. SLIDES reads the
catalogue, not a list of names, so any version-1 `.PIC` on drive 10 is
a slide.

### `HHGG`, `ZORK1`, `PLANET`, `LGOP` — Infocom Text Adventure Suite (Native Z3 Interpreter)

Infocom's celebrated interactive fiction text adventure games, running natively on COOL8's pure assembly Z-Machine Version 3 (Z3) interpreter on Drive 13 (`DEMOS`) and Drive 14 (`ADVENTUR`):

1. **`HHGG` (Drive 13)**: *The Hitchhiker's Guide to the Galaxy* (1984) by Douglas Adams and Steve Meretzky. Styled with the authentic Amiga dark blue background, crisp white letters, inverted status bar, and matching blue border (`CATTR = $1F`, status `$F1`, border `$01`).
2. **`ZORK1` (Drive 14)**: *Zork I: The Great Underground Empire* (1980) by Marc Blank and Dave Lebling. Styled with classic amber phosphor letters on a deep black background (`CATTR = $0E`, status `$E0`, border `$00`).
3. **`PLANET` (Drive 14)**: *Planetfall* (1983) by Steve Meretzky. Styled in standard crisp monochrome text on black (`CATTR = $07`, status `$70`, border `$00`).
4. **`LGOP` (Drive 14)**: *Leather Goddesses of Phobos* (1986) by Steve Meretzky. Styled with a dark gray background and very light gray foreground text (`CATTR = $87`, status `$78`, border `$08`).

**Architecture and execution**:
- Launched via `SYS "<NAME>.BIN"` from their respective `.BAS` loader programs on Drive 13/14.
- **Interpreter footprint**: 7.5 KB at `$0200..$1F73`.
- **Story file storage**: Stored as `.DAT` chunks on Drives 13 and 14 (up to 128 KB per story).
- **Demand-paging memory**: 16-page LRU cache (512 bytes/page = 8 KB RAM window) backed by SPI Flash paging.
- **Visuals & I/O**:
  - Full 80×30 text mode (`MODE 0`) with automatic word wrapping.
  - Real-time inverse video status bar on Row 0 showing room location, score, and move counter.
  - Interrupt-driven keyboard input with line editing, word tokenization, and 16-bit binary search across Infocom vocabulary dictionaries.

### UCSD Pascal p-System II.0 (`PASCAL`)

![UCSD Pascal](img/demo-pascal.png)

A complete, native port of the UCSD Pascal p-System II.0 virtual machine (P-Machine), running the authentic 1979 operating system, compiler, filer, and editor directly on COOL8.

- **Interpreter footprint**: 8.6 KB native machine code at `$0200..$247A`.
- **Operating system volume**: Packaged as standard UCSD disk volume on Drive 15 (`SYSTEM.PASCAL`, `SYSTEM.FILER`, `SYSTEM.COMPILER`, `SYSTEM.EDITOR`, `SYSTEM.MISCINFO`, `SYSTEM.SYNTAX`, and example programs `HELLO`, `SIEVE`, `HANOI`, `MANDEL`, `GUESS`, `FACT`).
- **Interactive Console & Terminal**: Emulates VT-52 terminal protocol with cursor home (`$19`), erase-to-end-of-screen (`$0B`), erase-to-end-of-line (`$1D`), cursor-up (`$1F`), and gotoxy (`$1E`), driving the native 80×32 text hardware directly.
- **Execution**:
  - Launched from BASIC via `RUN "PASCAL"` (or `SYS "PASCAL.BIN"`).
  - Boots through Segment 4 (`INITIALIZE`), loads `SYSTEM.MISCINFO`, mounts volumes, and drops into the root command line prompt:
    `Command: E(dit, R(un, F(ile, C(omp, L(ink, X(ecute, A(ssem, D(ebug,? [II.0]`
  - Supports interactive command menu navigation and execution of native Pascal tools.

## 5. Adding one

1. Write `demos/name.bas`. Keep it BASIC, keep it under 80 characters a
   line (the editor's logical line), and say in a `REM` what it is and
   where it came from.
2. `poe demos` — every demo is typed in, saved, run and shot.
3. Look at the picture. `docs/img/demo-<name>.png`.
4. Add a section here saying what it demonstrates about *this* machine,
   not just what it draws.

**A CoolAction! one** is `demos/name.act`, and `poe demos` compiles it
behind the library at `$1400` as `NAME.PRG` on drive 11, with
`NAME.BIN` beside it -- the loader of
[D102](01-decisions.md#d102--the-loader-a-program-owns-the-machine-and-never-comes-back),
which `SYS "NAME.BIN"` runs and which then owns the machine and
streams the program in over whatever BASIC was. Up to 60 KB, no
return: a program that finishes resets the machine. Nothing else to
do. Its gate is in `sim/test_action.py`, not here: a port of a BASIC
demo is held to the BASIC one's framebuffer, and a new one to whatever
it claims. A stub is not wanted and not listed. Data the repository
must not hold -- Ms. Cool-Man's ripped art -- goes in a file a
`demos/name.parts` manifest names (one path a line, `#` comments),
compiled between the library and the program; a missing part leaves
the program off the disc with a message rather than a compile error.

**A Software one** — a machine-code system — is a `.BIN` on drive 14
and a `demos/name.bas` stub that sets `DRIVE 14` and `SYS`es it; add
the stub's name to `SOFTWARE` in `tools/mkdemos.py`, which is the one
list that says a `.bas` in `demos/` is a stub and not a demo.
