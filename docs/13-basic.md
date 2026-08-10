# 13. COOL8 BASIC — the language reference

The interpreter runs the editor's stored form directly: what you typed
is what executes, tokenised. Values are **16-bit signed integers** only
— see §8 for the fraction that fits anyway. One statement per line;
there is no `:` separator. The implementation is
[`sw/interp.asm`](../sw/interp.asm), and the register-level truth for
everything the graphics and sound commands touch is
[04-system.md](04-system.md).

## 1. Statements

| | |
|---|---|
| `A = expr` | assignment. `LET` does not exist, and neither does `CONST` any more — an interpreter folds nothing, so it was an assignment in costume and its bytes went to better use |
| `IF e THEN … ELSE …` / `ELSEIF` | single-line only. The `THEN` arm is any one statement, including another `IF` |
| `FOR v = a TO b [STEP s]` … `NEXT [v]` | `STEP` may be negative; eight levels deep; `NEXT i` closes inner loops the BBC way |
| `DO [WHILE e \| UNTIL e]` … `LOOP [WHILE e \| UNTIL e]` | either end, both tested every iteration; `EXIT DO` from anywhere |
| `GOTO n` / `ON e GOTO n1, n2, …` | `ON` takes literal line numbers, not expressions; a value out of range falls through |
| `CALL name(…)` / `SUB name` … `RETURN` | SUBs found once at RUN; no parameters, no locals |
| `PRINT a; b$; c` | `;` butts items together, `,` inserts one space, a trailing separator holds the newline. Negative numbers print signed |
| `INPUT v` | digits and a leading `-`, echoed as typed, ended by Return; numeric scalars only |
| `DATA n, n, …` / `READ v, v` / `RESTORE` | numbers only (with `-`), scalar targets only; reading past the end is `?OUT OF DATA` |
| `POKE a, b` / `PEEK(a)` | main RAM and the I/O page |
| `DIM v(n)` | one-dimensional arrays on the heap |
| `ASM` … `END ASM` | the whole assembler of [08-assembler.md](08-assembler.md), labels as variables |
| `REM …` / `' …` | a comment: the rest of the line, whatever is in it. Both are stored with the text verbatim after a marker, so `LIST` gives back exactly what was typed and nothing inside is tokenised |
| `END` | a clean stop |

Numbers are decimal or `$` hex (`$FE10`). Variables `A`–`Z` are
resident and free to find; longer names cost a lookup. `A$`–`Z$` are
strings.

## 2. Operators

`* / MOD` bind tightest, then `+ - << >> AND OR XOR`, then one
relation: `= <> < <= > >=`. TRUE is **-1**, so `AND`/`OR`/`XOR` serve
logic and bits with one implementation ([D47](01-decisions.md)).
`IF A > 0 AND B > 0` works exactly as it reads. Strings compare with
`=` and `<>` only.

### What the arithmetic does at the edges

Everything is 16-bit two's complement, −32768 to 32767. Measured on the
machine, not inferred:

| | | |
|---|---|---|
| `-7 / 2` | **−3** | division truncates **towards zero** |
| `-7 MOD 2` | **−1** | the remainder takes the sign of the **dividend**… |
| `7 MOD -2` | **1** | …and ignores the sign of the divisor |
| `-8 >> 1` | **32764** | **`>>` is a *logical* shift — it fills with zero** |
| `30000 + 30000` | **−5536** | overflow wraps silently. There is no check |
| `300 * 300` | **24464** | so does the product: 16×16 keeps the low 16 |
| `-32768 / -1` | **−32768** | the one division that overflows, and it wraps too |
| `1 / 0` | `?DIV BY 0` | `/` and `MOD` both error, as `FDIV` does |

**`>>` is the trap.** Values are signed everywhere else in this
language, so `-8 >> 1` giving 32764 rather than −4 is the one place the
signedness quietly stops applying — `SHR`/`ROR` at
[`sw/interp.asm`](../sw/interp.asm) shifts a zero into the top. Use `/ 2`
where you meant an arithmetic shift; the divide is slower but it is
signed. `INT` *is* an arithmetic shift, by 8 — see §8.

**Overflow is silent by design**, not by omission: a check costs bytes
on every operation and the size ceiling in §12 is the reason there is
none.

## 3. Functions

`LEN LEFT$ RIGHT$ MID$ CHR$ ASC STR$ VAL INSTR` — strings, BBC-shaped:
one accumulator, four-byte descriptors, no garbage collection.

| | |
|---|---|
| `RND(n)` | 0..n-1 from a 16-bit xorshift; `RND(0)` is the raw word |
| `TIMER` | frames since power-on, 60 per second, wraps at 65536 (~18 min). No parentheses |
| `INKEY` | the next typed key, or 0 if none is waiting. No parentheses. Ordinary keys are ASCII (`Z` is 90, Esc is 27, Return 13); named keys are `K_UP` 256, `K_DOWN` 257, `K_LEFT` 258, `K_RIGHT` 259, `K_HOME` 260, `K_END` 261, `K_DEL` 262, `K_INS` 263 |
| `KEY(sc)` | -1 while the key with raw Set 2 scancode `sc` is **held right now** — as many keys at once as you like, which is what a game needs and `INKEY`'s queue cannot say. §6 has the codes |
| `VPEEK(a)` | one byte of video RAM |
| `FMUL(a,b) FDIV(a,b) INT(a)` | 8.8 fixed point, §8. `INT` floors |

## 4. The screen modes

`MODE n` selects one of seven presets. They are presets over **one**
fetch engine — the command loads the base, stride, depth and engine
registers, keeps the display on, and touches nothing else: not the
palette, not VRAM contents, not the sprites.

| n | Kind | Pixels | Colours | Coordinates | Surface | Where |
|---|---|---|---|---|---|---|
| 0 | text | 80×30 cells, 8×16 glyphs | 16 fg + 16 bg per cell | col 0-79, row 0-29 | 8 KB | main RAM `$8000` |
| 1 | text | 40×30 cells, wide glyphs | same | col 0-39 | 8 KB | main RAM `$8000` |
| 2 | tiles | 40×30 tiles of 8×8 (320×240) | 16 per tile, from a bank | tile 0-39, 0-29 | 4 KB map + patterns | VRAM `$0000` |
| 3 | bitmap | 640×480 | 2 (palette 0 and 1) | x 0-639, y 0-479 | 38,400 B, stride 80 | VRAM `$0000` |
| 4 | bitmap | 320×240, doubled to full screen | 16 (palette 0-15) | x 0-319, y 0-239 | 38,400 B, stride 160 | VRAM `$0000` |
| 5 | bitmap | 256×192, doubled, bordered | 16 | x 0-255, y 0-191 | 24,576 B, stride 128 | VRAM `$0000` |
| 6 | bitmap | 256×240, doubled, side borders | 256 (the whole palette) | x 0-255, y 0-239 | 61,440 B, stride 256 | VRAM `$0000` |

Which to pick:

- **Mode 4 is the general graphics mode** — 16 colours, square-ish
  pixels, and 25 KB of VRAM left over for sprite patterns and
  off-screen work. The demos in this chapter use it.
- **Mode 2 is what a game should use.** Nothing is redrawn: scrolling
  is a register write, animation is `TILE` writes at the edges.
  Map + 256 tiles + sprite patterns is ~20 KB, leaving 44 KB free.
- **Mode 5 is the one that double-buffers** — two 24 KB buffers fit.
  Mode 4 cannot (76,800 bytes does not fit 64 KB); when you want a
  double-buffered mode 4, the answer is usually mode 2.
- **Mode 3** is monochrome 640×480 — text-dense screens, plots.
- **Mode 6** gives every palette entry at once and fills VRAM doing it
  (4 KB left — about 32 sprite patterns and nothing else).
- Modes 0/1 are the text screens; the editor lives in 0. `PRINT` works
  there. A program may `MODE 0` and print, but the editor's screen is
  also the one you come back to — drawing over it is drawing over your
  listing.

**When a program ends, errs, or is broken, NOTHING is restored.**
Mode, palette, scroll, sprites and sound all stay exactly as the
program left them — the C64's deal — and the editor simply carries on
in whatever mode it wakes up in, because it works in all of them
(§9b). A sound left playing keeps playing until something silences it;
`MODE 0` typed direct brings the text screen back. Graphics no longer
need a holding loop to stay visible, though `DO`/`VSYNC`/`LOOP`
remains the animation idiom.

The bitmap surfaces all start at VRAM `$0000`. Everything above the
surface is yours; the boot stub parks two fonts at the top — the
`GTEXT` 8×8 at `$FC00`, and the 8×16 the mode 3 console blits at
`$F600`, the text modes' own face at full height (mode 3's cells are
16 undoubled lines, and 30 such rows are the whole screen). In mode 4
that leaves `$9600`–`$F5FF` (24 KB) free for patterns and buffers.
Scribbling over `$F600`–`$FEFF` costs `GTEXT` and the mode 3 console
their glyphs until the next boot, and the editor's scrolled bitmap
window repaints before it would reach them.

## 5. Graphics commands

All are thin wrappers over the auto-increment hardware ports — fast
enough to draw with, honest enough that `VPOKE` can do anything they
cannot. Pixel coordinates are the **logical** grid of the current mode
(the table above), except sprites, which live on the raster.

| | |
|---|---|
| `PLOT x, y, c` | one pixel. `c` is masked to the mode's depth (`AND 15` in mode 4) |
| `HLINE x, y, n, c` | `n` pixels rightward from (x,y), one store each — the fast fill |
| `LINE x0, y0, x1, y1, c` | Bresenham, any slope, endpoints included |
| `CLG c` | the whole surface to colour `c`, ~30 ms. Do it once, not per frame |
| `SCROLL x, y` | the fine-scroll registers, 0-7 within a tile/cell; whole-tile motion is `VID_BASE`, see [04-system.md §5.5](04-system.md) |
| `PALETTE i, v` | entry `i` (0-255) = `$0RGB`, 4 bits per gun: `$0F00` is red, `$0FFF` white. Entries 0-15 are what 4-bpp modes and text use; 16-31 are bank 1. Boot seeds 0-15 with the editor's sixteen and 16-31 with the Pico-8 sixteen |
| `TILE x, y, t, a` | one mode-2 map entry: tile index `t` (0-255) at tile column `x`, row `y`. `a`: bits 7:6 V/H flip, 5:4 pattern bank, 3:0 palette bank |
| `VPOKE a, b` | one byte of VRAM — the master key that makes everything without a command possible |
| `GTEXT x, y, s$, c` | 8×8-cell text in any bitmap mode: set pixels paint `c`, clear pixels paint 0 (opaque). The face is the editor's own Spleen, resampled to 8×8, ASCII 32-127, seeded by boot at VRAM `$FC00` — 8 bytes a glyph, so `$FC00 + (ASC(ch)-32)*8`, and `VPOKE` can restyle it |
| `VSYNC` | hold until the next frame starts — **the pacing primitive**. A loop doing `VSYNC` once per pass runs at exactly 60 Hz |

Mode-2 patterns: a tile is 32 bytes (8 rows × 4 bytes, 4 bpp, high
nibble left). The map occupies VRAM `$0000`-`$0FFF`; put patterns
above it and reach them with pattern bank bits or `PAT_BASE`. Writing
one is a `FOR` loop of `VPOKE`s, exactly as it is an assembly
programmer's job.

Not provided, and why: `POINT` (the pixel port is write-only — `VPEEK`
the byte instead), palette cycling and sprite collision as commands
(`PALETTE`+`VSYNC` cycles; your own coordinates bounding-box test),
`CIRCLE`/`PAINT` (the C128 trap), text in *tile* mode (`GTEXT` covers
the bitmap modes; tiles want a font as patterns).

## 6. Sprites

```
SPRITE n, x, y, img, a
```

Writes descriptor `n` (0-31) whole, and opens the global sprite gate —
which the editor closes again when the program ends, so a crash never
leaves sprites over your listing.

- `x`, `y` — **raster coordinates**, not logical ones: over a 320×240
  mode a sprite positions twice as finely as the background, and
  reaches the borders. 0-1023, wrapping; park a sprite at `x = 700` to
  hide it.
- `img` — the pattern's VRAM address in 32-byte units (`address / 32`).
  A pattern is 4 bpp, high nibble left: 32 bytes for 8×8, 128 for
  16×16. Colour 0 is transparent; 1-15 index the sprite palette bank
  (bank 0 unless `SPR_CTRL[7:4]` says otherwise — all sprites share
  one bank).
- `a` — the attribute byte: bit 7 size (0 = 8×8, 1 = 16×16), bit 6
  **enable**, bit 5 V-flip, bit 4 H-flip, bit 3 behind (the sprite
  shows only where the background is colour 0). So 64 is the plain
  "on" value.

Eight sprites per scanline; descriptor 0 is in front of descriptor 31.
Patterns are yours to `VPOKE`. A complete floating sprite:

```
10 MODE 4
20 CLG 1
30 FOR J = 0 TO 31
40 VPOKE 64000 + J, $EE
50 NEXT J
60 X = 0
70 DO
80 VSYNC
90 SPRITE 0, X, 120, 2000, 64
92 X = X + 1
93 IF X > 319 THEN X = 0
95 LOOP
```

(64000/32 = 2000; `$EE` is two pixels of colour 14 per byte.)

## 7. Sound and the keyboard

```
SOUND v, pitch, vol, noise
PITCH v, p
```

- `v` — voice 0-7. All eight are identical: a square wave, or a noise
  source when `noise` is nonzero.
- `pitch` — the phase increment: **f ≈ pitch / 2 Hz**. So A4 (440 Hz)
  is 881, and one octave is a doubling. Middle C ≈ 523.
- `vol` — 0-15; 0 is silence and how a note is stopped.
- `PITCH` rewrites the pitch alone — slides and vibrato without
  restating the volume.

There are no envelopes and no queues, on purpose: a `VSYNC` loop
writing `SOUND v, p, vol, 0` with a falling `vol` *is* an envelope,
with any shape you like ([D41](01-decisions.md)).

`KEY(sc)` scancodes a game actually reaches for — the full Set 2 table
is [04-system.md §4.3](04-system.md):

| key | code | key | code |
|---|---|---|---|
| cursor up | `$75` | space | `$29` |
| cursor down | `$72` | left shift | `$12` |
| cursor left | `$6B` | Esc | `$76` |
| cursor right | `$74` | Enter | `$5A` |
| `Z` | `$1A` | `X` | `$22` |

```
10 DO
20 IF KEY($6B) THEN X = X - 1
30 IF KEY($74) THEN X = X + 1
40 VSYNC
50 LOOP
```

The keyboard and the serial console produce the same key codes;
`INKEY` cannot tell which wire a key arrived on. **Ctrl+Pause** (on
the keyboard and in the emulator window) and serial **Ctrl-C** both
stop a running program with `?BREAK IN line`. A program left running
holds its unread keys in the queue and the editor will type them when
it returns; drain `INKEY` before `END` if you care.

## 8. 8.8 fixed point

A value cell is 16 bits, so the fraction that fits it is 8.8: ±127 and
change, in 1/256 steps — sub-pixel positions and speeds. Spell 2.5 as
`640` (2×256 + 128).

| | |
|---|---|
| `a + b`, `a - b` | already correct — fixed add is integer add |
| `FMUL(a, b)` | (a×b) >> 8, signed |
| `FDIV(a, b)` | (a<<8) / b, signed; division by zero errors |
| `INT(a)` | drops the fraction, **flooring**: an arithmetic shift right by 8 |

**`INT` rounds towards minus infinity, not towards zero.** `INT(-384)` —
that is −1.5 — is **−2**, not −1. It is the high byte with the sign
extended into the low ([`sw/interp.asm`](../sw/interp.asm) `iint`),
which is a floor, and it is BBC BASIC's `INT`.

**Flooring is the right rounding here, and the reason is motion.** Every
value gets a cell of equal width, so a constant velocity gives constant
pixel steps. Truncation towards zero would give the origin a
double-width cell and stall an object crossing it for a frame. If you
genuinely want truncation — and `IF` is a statement here, not an
expression:

```
IF X < 0 THEN T = -INT(-X) ELSE T = INT(X)
```

> **This function was called `FIX` until it was renamed, and the name was
> the bug.** `FIX` means truncate-towards-zero wherever a dialect carries
> both names, so the reference described the function the name promised
> rather than the one the machine implements, and the two disagreed for
> every negative argument. The behaviour was always right and did not
> change; only the spelling did. Programs saved before the rename call a
> name that no longer resolves.

`X = X + V` with `V = FDIV(3, 2)` moves one-and-a-half pixels a frame
when `PLOT INT(X), y, c` draws it. That is what floats are for in a
game, at a fiftieth of their cost.

## 9. The boot, direct mode, one vocabulary, storage

- Power-on is mode 0, the editor. The boot stub — run-once code the
  init then wipes along with all user RAM — seeds both palette banks
  and the `GTEXT` font and paints the boot screen, free count
  included (a build-time constant: a fresh machine is empty by
  definition). None of it costs a resident byte, and none of it
  survives to be executed or LISTed over.
- **A line with no number executes on the spot** — direct mode, the
  C64's shape with the BBC's manners. Variables persist between
  direct statements *and across runs* (`PRINT A` after a break is the
  whole point), a direct `GOTO n` resumes the stored program, and a
  direct `MODE` takes effect and stays.
- **Commands are ordinary statements** — one vocabulary: `LIST NEW
  FREE CLS SAVE LOAD DIR ERA COMPACT DRIVE DELETE RENUMBER` all run
  in a program or typed direct. A program can `SAVE` itself; `LOAD`
  inside a program **chains** — the new program continues from its
  first line with variables kept. The one direct-only statement is
  `RUN` (a program restarting itself would stack a frame per
  restart). No other guard exists: `DELETE` from a running program is
  legal and self-inflicted.
- `LOAD`'s three forms: `LOAD "N"` replaces (or chains, in a
  program); `LOAD "N", n` merges the file's lines from `n` up;
  `LOAD "N" AT addr` is raw bytes to memory — the BBC's `*LOAD`
  inside the language, with `SAVE "N" AT addr, len` as its partner
  for sprite sheets, tile sets, fonts and machine code.
- `SAVE`/`LOAD`/`DIR` are the SPI-flash filesystem: named files on
  fake-disk volumes, surviving power-off. The format and geometry are
  [04-system.md §8](04-system.md#8-mass-storage-the-filesystem).

## 9b. The editor: every mode, the C64's law

The editor works in **all seven modes** — 80 columns in modes 0 and
3, 40 in 1, 2 and 4, 32 in 5 and 6. The cell map at `$8000` is the
truth in every one; what changes is the mirror (nothing in text
modes, one map write per cell in tiles, a glyph blit in bitmaps), so
`PRINT` output is visible wherever the machine happens to be.

The keys follow the C64's KERNAL, verified against its disassembly:

- **DOWN** and **RIGHT** past the edges scroll at the bottom; the
  cursor never wraps to the top.
- **UP** stops at row 0. **LEFT** at column 0 wraps to the previous
  row's end. **Home** is 0,0.
- **Logical lines are 80 characters everywhere** — one row at 80
  columns, two at 40, three at 32, linked as on the C64. Return
  reads the whole logical line; `DEL`, backspace (across the row
  seam) and `INS` (opens a gap) edit it as a unit.
- The cursor blinks character-against-reverse at the C64's rate —
  the hardware's style 3 in text modes, a soft inverted glyph in
  tiles and bitmaps, drawn only while the editor waits.

Deviations from the C64, on purpose: forward-`DEL` and an `End` key
exist (it had neither), there is no quote mode (PETSCII-specific),
and insert mode is one keypress per gap rather than a sticky count.

## 9c. Speed: the Rugg/Feldman benchmarks

BM1–BM7 (Kilobaud, June 1977 — the set *Personal Computer World* ran
on everything for a decade), typed at the editor and RUN. `poe bench`
measures them; `sim/bench_bm.py` carries the listings and the
adaptations. Measured in cycles, so the seconds are arithmetic at
D32's 8.375 MHz, and the body only: each is run again with the loop
removed and the difference taken, which is what a stopwatch between
the `S` and the `E` measured too.

| | BM1 | BM2 | BM3 | BM4 | BM5 | BM6 | BM7 |
|---|---|---|---|---|---|---|---|
| COOL8 @ 8.375 MHz | 0.05 | 0.26 | 0.54 | 0.50 | 0.70 | 1.06 | 1.77 |
| the same work @ 2 MHz | 0.21 | 1.11 | 2.28 | 2.09 | 2.94 | 4.45 | 7.40 |
| the same work @ 1 MHz | 0.41 | 2.21 | 4.56 | 4.18 | 5.87 | 8.90 | 14.80 |
| Apple II Integer BASIC, 1 MHz | 1.3 | 3.1 | 7.2 | 7.2 | 8.8 | 18.5 | 28.0 |
| BBC BASIC, 2 MHz | 0.8 | 3.1 | 8.1 | 8.7 | 9.0 | 13.9 | 21.1 |
| Applesoft, 1 MHz | 1.3 | 8.5 | 16.0 | 17.8 | 19.1 | 28.6 | 44.8 |
| Commodore 64, 1 MHz | 1.2 | 9.3 | 17.6 | 19.5 | 21.0 | 29.5 | 47.5 |

**Read the Integer BASIC row first.** Applesoft, Commodore's MS BASIC
and BBC BASIC evaluate in floating point, which is most of what
BM3–BM7 measure, so beating them says little about this interpreter.
Wozniak's Integer BASIC is the only other integer implementation in
the published set, and clock for clock this is **1.4× to 3.1×** faster
than it.

**BM8 is not run and no number is quoted for it.** It is `K^2`, `LOG`
and `SIN` — a float-library benchmark, and §8 is the whole of the
arithmetic here.

**BM4 is faster than BM3, and everywhere else it is slower.** On the
Apple, the BBC and the 64 the constants in `K/2*3+4-5` cost *more*
than the variables in `K/K*K+K-K`, because those interpreters re-parse
a decimal literal from ASCII on every pass. This one stores a literal
as `T_LIT` and two binary bytes when the line is typed (§1), so a
constant is cheaper than a variable rather than dearer — the
inversion in that column is the tokeniser's decision, showing up as a
measurement.

## 10. Sizes and the ceiling

`python sim/build_basic.py` is the measurement, and it prints the free
count rather than leaving it to arithmetic:

```
  basic.bin   24,043 bytes  $A000-$FDEA
  BOOT.BIN    26,805 bytes  (2762 of relocating stub)
  free            21 bytes  to $FDFF
```

**Twenty-one bytes, of 24,064.** The ceiling is not looming, it is
here: the resident system fills 99.91 % of the space between `$A000`
and the I/O page at `$FE00`. The all-modes editor spent most of what
the space hunt won (workspace exodus to the `$FF00` page, the halved
classification table, the boot screen exiled to the stub, C64-terse
messages, the peephole and direct-push compiler passes, `CONST`
removed).

**Nothing further fits.** A `btab` entry alone is six bytes — a length,
the name, a handler word — before the handler exists, so even `ABS`,
which is a sign test and a negate, is most of what is left, and `SGN`
beside it does not fit at all. **Any new feature now costs an old one**,
and the drop candidates in order of bytes returned against pain are
`LINE` (~400), the fixed-point trio (~446), `GTEXT` (~232), `INPUT`
(~198), `SPRITE` (~120), `CLG` (~106). Past those, spilling system data
into high user RAM is the sanctioned escape.

The `INT` rename cost **+5 bytes** (24,038 → 24,043): a `CMP`/`BNE`/`JMP`
in `prim` against the six-byte `btab` entry it replaced, and the inverted
branch is two of those five. This entry read 24,024 before it was
measured again, so treat any number here as stale unless
`sim/build_basic.py` just printed it.
