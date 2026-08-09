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
| `A = expr` | assignment. `LET` does not exist |
| `CONST name = expr` | an assignment in costume — nothing is folded and nothing is protected, which the source says honestly |
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
| `FMUL(a,b) FDIV(a,b) FIX(a)` | 8.8 fixed point, §8 |

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

**When a program ends, errs, or is broken, the editor puts mode 0
back** — base, scroll, sprites-off and sound-silence included. The
palette is deliberately left as the program set it: a changed palette
is a look, not a fault. So graphics that should stay visible must end
in a loop:

```
80 DO
90 VSYNC
95 LOOP
```

The bitmap surfaces all start at VRAM `$0000`. Everything above the
surface is yours; the boot stub parks the `GTEXT` font at `$FC00`. In
mode 4 that leaves `$9600`–`$FBFF` (25.5 KB) free for patterns and
buffers.

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
| `FIX(a)` | the integer part, sign preserved |

`X = X + V` with `V = FDIV(3, 2)` moves one-and-a-half pixels a frame
when `PLOT FIX(X), y, c` draws it. That is what floats are for in a
game, at a fiftieth of their cost.

## 9. The boot, the editor, storage

- Power-on is mode 0, the editor. The boot stub — run-once code the
  init then wipes along with all user RAM — seeds both palette banks
  and the `GTEXT` font and paints the boot screen, free count
  included (a build-time constant: a fresh machine is empty by
  definition). None of it costs a resident byte, and none of it
  survives to be executed or LISTed over.
- Editor commands (typed without a line number): `RUN LIST NEW FREE
  CLS SAVE "name" LOAD "name" DIR ERA "name" COMPACT DRIVE n
  DELETE a-b RENUMBER`. There is no immediate mode — a statement
  without a line number is a syntax error by design.
- `SAVE`/`LOAD`/`DIR` are the SPI-flash filesystem: the program's
  tokenised form, named, surviving power-off.

## 10. Sizes and the ceiling

The resident system is **22,856 bytes of the 24,064** below the I/O
page — 1,208 free, after a space hunt in three acts: every workspace
buffer (the input ring, the key bitmap, `FOR` frames, argument
scratch, the filesystem's page buffer) moved out of the image into the
otherwise-idle `$FF00` page and the string accumulator; a
classification table halved because its token half was 128 zeros; and
the boot screen — text, painting and free count — moved wholesale into
the run-once stub, with the error messages tersed to C64 brevity and
the editor's table unified into the interpreter's. If the ceiling
looms again, the drop candidates in order of bytes returned against
pain: `LINE` (~400), the fixed-point trio (~446), `GTEXT` (~232),
`INPUT` (~198), `CLG` (~106), `SPRITE` (~120).
