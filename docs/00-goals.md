# 00 — Goals and constraints

## What we are building

Two things, in this order:

1. **COOL8** — an 8-bit CPU core with a 16-bit address space. Clean
   sheet. Small enough to tape out, pleasant enough to write assembly
   for, regular enough that a C compiler is not a nightmare.
2. **The Cool8 machine** — a complete retro home computer around that
   CPU: RAM, VGA graphics, sound, PS/2 keyboard. Nothing else. No
   joystick ports, no cartridge slot, no disk.

The FPGA implementation is the working machine. The ASIC is the CPU
core alone.

## Hard constraints

### C1 — The CPU must be fabricable on TinyTapeout

Target: a TinyTapeout submission within roughly a year.

This is the single most restrictive constraint and it shapes everything
below it:

- **Pin budget is 8 in / 8 out / 8 bidir, plus `clk` and `rst_n`.**
  That is 24 signals for a bus that naively needs 16 address + 8 data +
  control ≈ 27+. The bus must be multiplexed. See
  [03-microarchitecture.md](03-microarchitecture.md).
- **No usable on-chip RAM.** All memory is external. The CPU core owns
  no RAM, no ROM, no register file larger than a handful of flip-flops.
- **No vendor primitives.** No `SB_SPRAM256KA`, no `SB_RAM40_4K`, no
  `SB_PLL40_*`, no `SB_IO` anywhere inside the core. Those are FPGA hard
  macros with no ASIC equivalent.
- **Area is the currency.** Every flip-flop and every opcode in the
  decoder costs silicon. When two designs are equally good, the smaller
  one wins.

### C2 — The core and the machine are separate

`rtl/core/` contains the CPU and nothing else. It talks to the world
through one synchronous memory interface. Everything else — RAM
controller, video, audio, keyboard, timers — lives in `rtl/soc/` and is
FPGA-only.

The same core RTL was what would have gone to TinyTapeout, wrapped in a
thin pad/multiplexer shim. **That path is shelved and the target is the
FPGA** ([D33](01-decisions.md#d33--the-asic-path-is-shelved-the-target-is-the-fpga)),
which changes what the rule is *for* without changing the rule: a core
that stays portable is a milestone that can be un-shelved, and one that
has been casually sprinkled with `SB_` primitives is a rewrite. Break it
only where a measurement says it buys speed.

### C3 — It must actually be a nice machine

The ASIC goal is not permission to build something miserable. The CPU
has to be genuinely pleasant to hand-write assembly for, and it has to
be a plausible compiler target. If those fight the area budget, we spend
the area — within reason, and we write down why.

## Non-goals

- **Compatibility with anything.** Not 6502, not Z80, not C64, not CP/M.
  No existing binary will ever run on this.
- **Cycle-accurate emulation of any historical chip.** Notably we are
  not reproducing VIC-II bugs. Sprite multiplexing and raster effects
  are supported because we implement them deliberately, not because we
  reproduce someone else's DMA quirks.
- **Pipelining, caches, superscalar anything.** Multicycle, non-pipelined.
- **USB host.** PS/2 keyboard only.
- **Storage.** No SD card and no disk. The 8 MB configuration flash is
  the machine's storage and it can now be written as well as read
  ([D42](01-decisions.md)); a filesystem on top of it is software and is
  not built.
- **An operating system.** A monitor/loader in ROM, that's it.

## Success criteria

The project is done, for a first pass, when:

1. The machine boots from ROM on the iCESugar, puts a text prompt on a
   real VGA monitor, and accepts typing from a real PS/2 keyboard.
2. A program written in COOL8 assembly draws something on screen and
   makes a sound.
3. `yosys`/`nextpnr` reports the whole SoC fitting in the UP5K with
   headroom, and the core alone synthesising cleanly with no FPGA
   primitives.
4. The core passes an instruction-level test suite against a reference
   emulator.
5. A TinyTapeout submission of the core (with the multiplexed bus) has
   been simulated end-to-end against an external-SRAM model.

## Resource budget (iCE40UP5K)

**Everything below is measured, placed and routed**, not estimated. The
M5 gate turned this table from a budget into a report, and it cost a
blitter and three megahertz doing it — see
[D34](01-decisions.md#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter).

| Resource | Available | Used |
|---|---|---|
| LUT4 | — | CPU **695**, video **1972**, flash **277**, keyboard **162**, UART **141**, sound **141**, the rest **249** |
| Logic cells | 5280 | **5022 — 95 %** |
| EBR (block RAM) | 30 × 4 Kbit | Boot ROM 8, font 8, sprite line buffer 5, background line buffer 2, palette 1, sprite descriptors 1, sound voices 1, UART FIFO 1, keyboard FIFO 1 → **28** |
| SPRAM | 4 × 32 KB = 128 KB | 2 blocks = 64 KB CPU RAM; **2 blocks = 64 KB video RAM** ([D28](01-decisions.md)) — **4 of 4** |
| DSP | 8 | **1** — `y × stride` for the pixel port |
| PLL | 1 | **1** — 25.125 MHz for the raster, ÷3 for everything else ([D32](01-decisions.md)) |
| Timing | — | closes at 8.375 MHz; `sclk` Fmax **11.2**, and 11.0-11.5 across placer seeds |

The CPU is 695 LUT4 *in context*; on its own it is **902**, which is the
number [03-microarchitecture.md §5.7](03-microarchitecture.md) quotes and
the one to hold against other cores.

**LUT4 is not the number that decides whether the part is full.** A
logic cell is a LUT4 with its carry and flip-flop, and the measured
conversion on this design is about **1.28 LC per LUT4**. Quote LC when
asking whether something fits.

**EBR and logic cells are not interchangeable.** That is the sentence
M6 turned into a decision: the boot ROM holds 3028 bytes in eight block
RAMs and giving six of them back would buy zero LUTs, so the only way to
spend spare block RAM is on storage that would otherwise be flip-flops.
[D37](01-decisions.md#d37--the-uart-receive-fifo-moves-into-block-ram-reversing-m4s-call)
does exactly that and it is what made M6 fit.

**What is left is 258 logic cells and two block RAMs**, and the machine
is complete against its original scope: CPU, memory, video, sprites,
keyboard, serial, storage it can write, and sound.

Getting there cost the hardware loader, which is a build option now
rather than a fixture ([D40](01-decisions.md)) — 376 logic cells that
paid for the flash write path, without which the machine could load and
could not save.

Two lessons about estimates are worth keeping and they point opposite
ways. Audio was budgeted at ~250 LUT4 for four voices and came in at
**141 for eight** ([D41](01-decisions.md)), because the shape was wrong
rather than the arithmetic. And two of the five "obvious" area savings in
[D39](01-decisions.md) measured *negative* once they were built — a
removal probe measures the ceiling, not the change. Believe the number
when `nextpnr` has printed it, in either direction.

**The machine has now run on real silicon.** It boots, clears RAM, brings
up the monitor and answers over the serial console: `D F000` returns the
boot ROM's first bytes, `2F 60 00 02`, which is the `LDW X,#$0200` the
reset vector points at. Simulation said all of that first and was right —
but the board is where the missing pull-up on `SW[0]` turned up, and no
testbench was ever going to find it ([D40](01-decisions.md)).

**Important:** iCE40 SPRAM cannot be initialised from the bitstream.
At power-on the 64 KB of main RAM contains garbage. The boot ROM lives
in EBR (which *is* bitstream-initialisable) and copies itself down.
See [04-system.md](04-system.md).
