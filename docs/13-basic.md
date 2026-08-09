# 13. COOL8 BASIC — the language reference

The interpreter runs the editor's stored form directly: what you typed
is what executes, tokenised. 16-bit integers only — see §7 for the
fraction that fits anyway. One statement per line; there is no `:`
separator. The implementation is [`sw/interp.asm`](../sw/interp.asm),
and the register-level truth for everything the graphics and sound
commands touch is [04-system.md](04-system.md).

## 1. Statements

| | |
|---|---|
| `A = expr` | assignment. `LET` does not exist |
| `CONST name = expr` | an assignment in costume — nothing is folded and nothing is protected, which the source says honestly |
| `IF e THEN … ELSE …` / `ELSEIF` | single-line only |
| `FOR v = a TO b [STEP s]` … `NEXT [v]` | `STEP` may be negative; eight levels deep; `NEXT i` closes inner loops the BBC way |
| `DO [WHILE e \| UNTIL e]` … `LOOP [WHILE e \| UNTIL e]` | either end, both tested every iteration; `EXIT DO` from anywhere |
| `GOTO n` / `ON e GOTO n1, n2, …` | `ON` takes literal line numbers, not expressions; out of range falls through |
| `CALL name(…)` / `SUB name` … `RETURN` | SUBs found once at RUN; no parameters, no locals |
| `PRINT a; b$; c` | `;` butts, `,` is one space, a trailing separator holds the newline. Negative numbers print signed |
| `INPUT v` | digits and a leading `-`, echoed, ended by Return; numeric scalars only |
| `DATA n, n, …` / `READ v, v` / `RESTORE` | numbers only (with `-`), scalar targets only; `DATA` may share a line with nothing; reading past the end is `?OUT OF DATA ERROR` |
| `POKE a, b` / `PEEK(a)` | main RAM and the I/O page |
| `ASM` … `END ASM` | the whole assembler of [08-assembler.md](08-assembler.md), labels as variables |
| `END` | a clean stop |

## 2. Operators

`* / MOD` bind tightest, then `+ - << >> AND OR XOR`, then one
relation: `= <> < <= > >=`. TRUE is **-1**, so `AND`/`OR`/`XOR` serve
logic and bits with one implementation ([D47](01-decisions.md)).
Strings compare with `=` and `<>` only.

## 3. Functions

`LEN LEFT$ RIGHT$ MID$ CHR$ ASC STR$ VAL INSTR` — strings, BBC-shaped:
one accumulator, four-byte descriptors, no garbage collection.

| | |
|---|---|
| `RND(n)` | 0..n-1; `RND(0)` is the raw 16-bit xorshift word |
| `TIMER` | frames since power-on, wraps at 65536 (~18 min). No parentheses |
| `INKEY` | the next typed key or 0; named keys are `K_UP`(256)…`K_INS`(263), Esc is 27. No parentheses |
| `KEY(sc)` | -1 while raw Set 2 scancode `sc` is held — as many at once as you like. The codes: [04-system.md §4.3](04-system.md) |
| `VPEEK(a)` | one byte of VRAM |
| `FMUL FDIV FIX` | §7 |

## 4. Graphics

All thin wrappers over the auto-increment ports; the modes, formats and
strides are [04-system.md §5.3](04-system.md).

| | |
|---|---|
| `MODE n` | preset 0–6, display kept on. **The editor gets mode 0 back** whenever a program ends, errs, or is broken — with the base, scroll and sound also reset. The palette is deliberately left as the program set it |
| `PLOT x, y, c` | one pixel, current depth, hardware-masked |
| `HLINE x, y, n, c` | n pixels rightward, one store each |
| `LINE x0, y0, x1, y1, c` | Bresenham through the pixel port |
| `CLG c` | the whole surface, via the VRAM port, ~30 ms |
| `SCROLL x, y` | the fine-scroll registers — the whole command |
| `PALETTE i, v` | entry i = `$0RGB`. Bank 0 is the editor's sixteen, bank 1 the Pico-8 sixteen, both seeded at boot |
| `TILE x, y, t, a` | one mode-2 map entry |
| `SPRITE n, x, y, img, a` | descriptor n whole. `img` in 32-byte units; `a`: bit 7 size, 6 enable, 5 V-flip, 4 H-flip, 3 behind. Patterns are yours to `VPOKE`, exactly as they are an assembly programmer's |
| `VPOKE a, b` | one byte of VRAM — the master key that makes everything without a command possible |
| `GTEXT x, y, s$, c` | 8×8 opaque text in any bitmap mode, from the font the boot stub seeds at VRAM `$FC00` |
| `VSYNC` | hold until the next frame — the pacing primitive |

Not provided, and why: `POINT` (the pixel port is write-only),
palette cycling and sprite collision as commands (palette and
descriptors are write-only; `PALETTE`+`VSYNC` cycles, and your own
coordinates bounding-box test), `CIRCLE`/`PAINT` (the C128 trap),
text in *tile* mode (pattern-RAM font loading — `GTEXT` covers
bitmap modes).

## 5. Sound

| | |
|---|---|
| `SOUND v, pitch, vol, noise` | voice 0–7; `pitch` is the phase increment, **f ≈ pitch / 2 Hz** (A4 = 881); vol 0–15, 0 is silence; `noise` picks the LFSR |
| `PITCH v, p` | pitch alone — slides and vibrato without restating volume |

No envelopes and no queues, on purpose: a `VSYNC` loop writing volume
is an envelope with any shape you like ([D41](01-decisions.md)).

## 6. The screen, the keyboard, the boot

- Power-on is mode 0, the editor. The boot stub — run-once code in
  reclaimed RAM — seeds both palette banks and the `GTEXT` font, and
  plays the three-note chime. None of it costs a resident byte.
- The keyboard and the serial console produce the same key codes;
  `INKEY` cannot tell which wire a key arrived on. Ctrl+Pause and
  serial Ctrl-C both stop a running program.
- A program left running holds its keys in the queue; the editor will
  type them when it returns. Drain `INKEY` before `END` if you care.

## 7. 8.8 fixed point

A value cell is 16 bits, so the fraction that fits it is 8.8:
±127 and change, in 1/256 steps — sub-pixel positions and speeds.
Spell 2.5 as `640` (2×256+128), or keep values in `F`-suffixed
variables by convention.

| | |
|---|---|
| `a + b`, `a - b` | already correct — fixed add is integer add |
| `FMUL(a, b)` | (a×b)>>8, signed |
| `FDIV(a, b)` | (a<<8)/b, signed; division by zero errors |
| `FIX(a)` | the integer part, sign preserved |

`X = X + V` with `V = FDIV(3, 2)` moves one-and-a-half pixels a frame
when `PLOT FIX(X), y, c` draws it. That is what floats are for in a
game, at a fiftieth of their cost.

## 8. Sizes and the ceiling

The resident system is **24,057 bytes of the 24,064** below the I/O
page. The next feature displaces an old one; the drop candidates, in
order of bytes returned against pain: `LINE` (407), the fixed-point
trio (446), `GTEXT` (232), `INPUT` (198), `CLG` (106), `SPRITE` (113).
Everything else earns its bytes several times over.
