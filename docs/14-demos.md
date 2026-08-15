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
| 2–12, 14, 15 | `COOL8` | the user's, formatted and empty |
| **13** | **`DEMOS`** | **the demo disc — what this document is about** |

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
by accident on the first afternoon.

## 2. The sources are the truth, the disc is derived

`demos/*.bas` is what gets reviewed. `tools/mkdemos.py` formats the
volumes, **types each source at the machine**, and lets `SAVE` write it.

**It types rather than tokenises, and that is the whole design.** A
program on disc is tokenised, and the only thing that knows the token
table is `sw/token.asm`. A host-side tokeniser would be a second
implementation of it and would drift the first time a keyword was added —
which is the trap [AGENTS.md](../AGENTS.md) names first and this project
has paid for a dozen times. Typing costs a few seconds a demo and cannot
be wrong.

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

## 5. Adding one

1. Write `demos/name.bas`. Keep it BASIC, keep it under 80 characters a
   line (the editor's logical line), and say in a `REM` what it is and
   where it came from.
2. `poe demos` — every demo is typed in, saved, run and shot.
3. Look at the picture. `docs/img/demo-<name>.png`.
4. Add a section here saying what it demonstrates about *this* machine,
   not just what it draws.
