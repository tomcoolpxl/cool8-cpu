# 06 — Roadmap

What exists, what it has been proven on, and what comes next. The
milestone-by-milestone history that used to fill this file lives in
git; a decision that mattered is in
[01-decisions.md](01-decisions.md), a measurement that mattered is in
the document that owns its subject.

## What exists

The whole machine, verified at three levels — emulator, RTL
co-simulation, and (where the bench allows) real silicon:

- **CPU** — the COOL8 core, cosim-gated against `tools/cool8emu.py`
  instruction by instruction, mutation-tested, timed by
  `sim/timing.py`.
- **Video** — text, tiles, bitmaps, 32 sprites, 256-entry palette;
  the renderer in `tools/cool8vid.py` is held against RTL frames on
  every pixel of every mode.
- **Sound** — 8 voices, 1-bit sigma-delta, model checked against the
  running engine.
- **Keyboard** — PS/2 decoder shared between the boot ROM's monitor
  and BASIC, key-down bitmap, `INKEY`/`KEY()`.
- **Storage** — SPI flash read *and* write from the machine: the
  filesystem behind `SAVE`/`LOAD`/`DIR`/`ERA`/`COMPACT`, plus raw
  `SAVE`/`LOAD ... AT`, and autoboot from volume 0.
- **BASIC** — the resident system: interpreter, full-screen C64-law
  editor working in all seven modes at 80/40/32 columns, direct mode,
  one unified statement vocabulary, inline assembler.
- **Boot** — ROM autoboot loads `BOOT.BIN`; a relocating stub carries
  the system image, paints the boot screen, seeds palettes and the
  GTEXT font, and is wiped by init along with all user RAM.

## Hardware status

Everything reachable over the board's one wire is verified on the
chip: boot to BASIC from flash, every BASIC command (self-graded over
serial), break and recovery, the whole flash filesystem cycle from
both sides of the chip. None of it worked until the deep-power-down
wake-up of [05-board.md](05-board.md) Trap 0 was added.

**Not yet exercised on hardware, blocked on bench parts, not code:**

| needs | for |
|---|---|
| PS/2 level shifter | the physical keyboard |
| VGA PMOD (12-bit R-2R) | a visible picture |
| RC filter + jack | audible sound |

That is the whole remaining hardware list. Each is a small solder job
described in [05-board.md](05-board.md).

## Shelved: TinyTapeout

The target is the FPGA
([D33](01-decisions.md#d33--the-asic-path-is-shelved-the-target-is-the-fpga)).
The discipline stays where it is free: `rtl/core` remains Verilog-2001
with no vendor primitives, no inferred RAM and no clock gating, and
`sim/synth.py` keeps checking it — a still-portable core is a
milestone that can be un-shelved.

## Deliberately not scheduled

- A second background layer, 16 sprites per scanline, sprite scaling
  and collision — the register and descriptor bits are reserved and
  [04-system.md §5.11](04-system.md) prices each one.
- A C compiler backend (LLVM or `vbcc`). The ISA was designed to make
  it possible; doing it is a separate project.
- A second silicon target with more area.

## Order-of-work notes, kept because they keep being right

**Write the emulator before the RTL** — the cheapest place to discover
an ambiguous encoding. **Write real assembly before the RTL** — the
only honest test of "is four registers enough" is a few hundred lines
of code. **Profile before optimising, and believe the profile** — this
file's ancestors record a 256-byte lookup table bought on a 10 %
estimate that returned 2 %.
