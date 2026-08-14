# 06 — Roadmap

What exists, what it has been proven on, and what comes next. The
milestone-by-milestone history that used to fill this file lives in
git; a decision that mattered is in
[01-decisions.md](01-decisions.md), a measurement that mattered is in
the document that owns its subject.

## What exists

The whole machine, verified at three levels — the software machine,
RTL co-simulation, and (where the bench allows) real silicon:

- **CPU** — the COOL8 core, cosim-gated against the machine (`rust/`)
  instruction by instruction, mutation-tested, timed by
  `sim/timing.py`.
- **Video** — text, tiles, bitmaps, 32 sprites, 256-entry palette;
  the scanline renderer is held against RTL frames on every pixel of
  every mode.
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

**Not yet exercised on hardware. No longer blocked on parts:**

| needs | for | status |
|---|---|---|
| PS/2 socket + level shifter | the physical keyboard | socket ordered; a 4-channel BSS138 breakout is in hand |
| PMOD-VGA (12-bit R-2R) | a visible picture | ordered |
| RC filter + PMOD-AUDIO | audible sound | amplifier ordered; **two 1 kΩ and two 10 nF outstanding** |

Four passives are the whole remaining shopping list. Each job is a small
one and [05-board.md](05-board.md) describes it — but the audio one is
not wiring, it is the digital-to-analogue conversion itself (§4.2), and
the board that arrives with it is an amplifier that expects an already
reconstructed signal.

Reading the board schematic closed two questions that were open here on
guesswork: **J7 brings out `5V_USB` and all four usable PMOD1 signals**,
so powering the keyboard needs no soldering to the USB connector, and
`S1` is a DIP switch rather than a momentary button, which changes how
the break key is used but not the logic behind it.

## Open, with the next step already named

**Pipelining the fetch — one ten-minute experiment, not a week of work.**

The arithmetic is done and lives in
[D59](01-decisions.md#d59--cpi-is-259-and-pipelining-the-fetch-is-a-bet-rather-than-an-optimisation).
CPI is 2.59, so registering the opcode costs 39 % more cycles and pays
only if the result closes at 12.5625 MHz — the sole rung above 8.375,
because [D32](01-decisions.md) makes `sclk` a division of the pixel
clock. Above that line it is +8 %; below it the machine is **28 %
slower**. Today's design closes at **11.07 mean, 11.23 best** across six
seeds — it was 11.91/12.15 when D59 was written, so the bet has got
*worse*, not better: the gap to 12.5625 is 1.34 MHz now. The experiment
below still costs one afternoon and still answers the question, but
expect it to say no.

**Do not start with the rewrite.** Register the opcode in `S_FETCH` and
change nothing else — no cycle counts, no emulator, no timing table. It
will be functionally wrong and fail co-simulation, and synthesis does
not care:

```bash
python tools/mkbit.py --seeds 6      # read sclk
```

Clears 12.5625 with margin → the rewrite is justified before a line of
it is written. Lands at 12.2 → delete the hack and the question is
closed for good. Either way it costs one afternoon's compute and no
commitment.

**The thing that is not worth trying again** is reshaping the SPRAM read
path: measured, both variants, six seeds each, and the baseline won —
[D60](01-decisions.md#d60--narrowing-the-spram-read-path-earlier-and-replicating-its-select-bought-nothing-and-was-reverted).
At 97 % occupancy the placer's freedom is the constraint, so only
removing logic will move Fmax.

## Chased and closed: the DSP block

**The design uses no DSP and should not.** `cool8_pixport.v` computes
`y × stride` and its header claimed one of the eight `SB_MAC16` blocks;
`00-goals.md` and README repeated it. `tools/mkbit.py` does pass
`synth_ice40 -dsp`, and `ice40_dsp` **checks this multiply and declines
it** -- it maps when the module is synthesised alone and not when the
design is flattened around it.

Rather than force it, the multiply was priced: replaced with a shift and
rebuilt. **5,183 cells with it, 5,175 without — the whole multiply is 8
logic cells.** yosys is already reducing it far below a general 11×16
multiplier, so instantiating an `SB_MAC16` by hand could recover 8 cells
and add a vendor primitive to a module that does not need one.

Closed. The comments in `cool8_pixport.v` and `cool8_snd.v` said
otherwise and now carry the number, so this is not re-opened by the next
reader counting idle DSP blocks. **It earns its place the day a voice
reads a wavetable or a sample**, which is the upgrade `cool8_snd.v`
names and is still a good one.

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
