# COOL8

An 8-bit home computer on a single iCE40UP5K FPGA.

**The CPU is an original design** — not a 6502, not a Z80, not a clone or
a derivative of either. So is the video chip. Both were specified,
implemented and verified in this repository, and nothing here is
compatible with any existing machine by intent.

![Text mode 0: a box in CP437 line-drawing characters, the full 256-glyph
character set, and all sixteen palette colours](docs/img/text-mode-0.png)

*Mode 0, 80×30. Rendered from the simulator through the real raster and
the real font ROM; `python sim/test_video.py` regenerates it.*

---

## What it is

| | |
|---|---|
| **CPU** | COOL8 — 8-bit, 16-bit address space, 511 encodings, four general registers and two 16-bit pointers. 902 LUT4 |
| **Memory** | 64 KB RAM, plus a separate 64 KB of video RAM |
| **Video** | 640×480 VGA. Text, tiles and bitmaps from one engine; 32 sprites, 8 per scanline; 256-colour palette from 4096 |
| **Sound** | Planned |
| **Input** | PS/2 keyboard, and a serial console that works as its peer |
| **Storage** | 8 MB SPI flash, read-only today |
| **Board** | iCESugar v1.5 — Lattice iCE40UP5K, 5280 logic cells |

It boots to a monitor in ROM: examine and change memory, disassemble, run
a program, load one from flash. Programs are loaded over USB serial
without rebuilding the bitstream.

## Running it without a board

These run against the simulator; no hardware is required.

```bash
python tools/cool8emu.py --selftest    # the ISA, executable
python sim/test_video.py               # every mode, every pixel -> build/*.png
python sim/test_monitor.py             # boot the machine and type at it
```

`sim/test_monitor.py` starts the whole SoC cold with RAM undefined, then
drives it over a bit-banged serial line and clocks PS/2 scancodes in on
an open-drain wire.

## Build the bitstream

Needs [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build) on
`PATH`.

```bash
python tools/mkbit.py
```

Writes `build/cool8.bin`. Copy it onto the iCELink drive to program the
board.

## Load a program

```bash
python tools/cool8load.py --port COM3 --go 0x0200 myprog.bin
```

The loader is a state machine in the FPGA rather than a program in ROM,
so it works with no software on the machine and with the CPU halted. A
bus grant leaves all architectural state untouched, so it can also read
all 64 KB back while a program runs.

```bash
python tools/cool8screen.py --port COM3   # the machine's text screen, on your PC
```

---

## The parts

```
   12 MHz ──▶ cool8_pll ......... one PLL: 25.125 MHz for the raster,
    (pin 35)                        and a third of that, 8.375 MHz,
                  │                 for everything else
              cool8_top ......... pins, power-on reset, the LED
                  │
              cool8_soc ......... the bus, and the I/O page at $FE00
                  │               that is decoded ahead of everything
                  ├── cool8_core ...... the CPU
                  ├── cool8_mem ....... the memory map and the ROM overlay
                  │     ├── cool8_spram .... 64 KB over 2 x SB_SPRAM256KA
                  │     └── cool8_rom ...... 4 KB boot ROM in EBR
                  ├── cool8_uart ...... 8N1, divider in a register
                  ├── cool8_loader .... bus master on the end of the wire
                  ├── cool8_ps2 ....... keyboard, raw Set 2 scancodes
                  ├── cool8_flash ..... the config flash as mass storage
                  └── cool8_video ..... $FE10-$FE3F, and the VGA pins
                        ├── cool8_vga ..... the 640x480 raster
                        ├── cool8_vregs ... the mode, and the presets
                        ├── cool8_fetch ... text, tile and bitmap, one engine
                        ├── cool8_pixel ... the shifter, cursor, line buffers
                        ├── cool8_pal ..... 256 x 12-bit, dual clock
                        ├── cool8_sprite .. 32 descriptors, 8 to a line
                        ├── cool8_vram .... 64 KB, four-way arbiter
                        ├── cool8_vport ... the CPU's window onto it
                        └── cool8_pixport . plot by coordinate

              Text reads main RAM; everything else reads video RAM, so
              nothing the video engine does can stall the CPU.
```

**What the part holds**, placed and routed:

```
ICESTORM_LC      5030 / 5280   95 %
ICESTORM_RAM       27 / 30     90 %
ICESTORM_SPRAM      4 / 4     100 %
ICESTORM_DSP        1 / 8      12 %
sclk closes at 11.0-11.5 MHz against a constraint of 8.375
```

## The CPU

Original design, documented in [docs/02-isa.md](docs/02-isa.md).

One byte encodes a register-to-register ALU operation across any of the
four registers, or a load or store through either pointer. Two bytes
encode an immediate, a displacement or a branch. Opcode `$2F` escapes to
a second 256-entry page for the rarer instructions.

```asm
        LDW  X,#src             ; 16-bit pointers, so a copy loop
        LDW  Y,#dst             ; leaves two registers free
        MOV  R2,#64
.loop:  LD   R0,[X]
        ST   [Y],R0
        INCW X
        INCW Y
        SUB  R2,#1
        BNE  .loop
```

Sixteen branch conditions including signed and unsigned comparisons, a
full 16-bit stack pointer, `[SP+u8]` addressing for stack frames, and an
8×8 multiply landing in `X`, so the product can be dereferenced directly.

Register-to-register operations take 2 clocks, a load through a pointer
2, a call 6. The counts are measured from the RTL by `sim/timing.py`.

`cool8_core` is comparable in size to a compact 6502 core, with roughly
twice the architectural state — the two 16-bit pointers — and about half
a Z80. It uses no block RAM, no DSP and no vendor primitives; the
register file is flip-flops, and `sim/synth.py` checks this on every run.

## The video chip

Also an original design. One fetch engine drives all three display modes;
they differ only in what an item is and where it is read from.

| Mode | | Format |
|---|---|---|
| 0 | 80×30 text, 8×16 glyphs | character + attribute |
| 1 | 40×30 text, 16×16 | same glyphs, doubled |
| 2 | 40×30 tiles of 8×8 → 320×240 | 4 bpp patterns, flip and palette bank per cell |
| 3 | 640×480 bitmap | 1 bpp |
| 4 | 320×240 bitmap | 4 bpp |
| 5 | 256×192 bitmap, bordered | 4 bpp, double-buffered |
| 6 | 256×240 bitmap | 8 bpp |

Sprites use a separate line buffer merged at the pixel stage, so they are
independent of the background mode and work over text as readily as over
a bitmap. 32 descriptors, 8 per scanline, 8×8 and 16×16, 4 bpp.

Scrolling moves the origin rather than the memory. The text map is 32
rows with 30 displayed and the row pointer wraps in hardware, so
scrolling a terminal is one register write plus clearing one row.

`PIX_X`/`PIX_Y`/`PIX_DATA` plot a pixel by coordinate, with `y × stride`
computed in one of the FPGA's multipliers.

## Sound

Planned. Nothing is built yet.

---

## How it is checked

The reference emulator was written before the RTL, from the ISA
document, and the RTL is checked against it instruction by instruction.
Both emit one line of full architectural state per retired instruction;
`sim/cosim.py` diffs them and compares the whole 64 KB memory image, so a
store to a wrong address is caught as well as a wrong result.

```bash
python sim/cosim.py all       # 511 encodings, random streams, interrupts,
                              #   wait states, bus grants, the ASIC bus
python sim/mutate.py          # break the RTL on purpose; require a failure
```

The video engine is checked the same way: a golden model of the display
against all 307,200 pixels of a frame, for every mode.

The full battery is sixteen suites. `sim/cosim.py all` is the gate for
any RTL change.

## Documents

`docs/` is the source of truth. It records the reasoning behind each
decision, including the alternatives that were rejected.

| | |
|---|---|
| [00-goals.md](docs/00-goals.md) | Scope, constraints, the resource budget |
| [01-decisions.md](docs/01-decisions.md) | Every architectural call and its argument |
| [02-isa.md](docs/02-isa.md) | The instruction set |
| [03-microarchitecture.md](docs/03-microarchitecture.md) | Datapath, control, bus, timing |
| [04-system.md](docs/04-system.md) | Memory map, video, keyboard, flash, boot |
| [05-board.md](docs/05-board.md) | Pinout, PMODs, external circuits, BOM |
| [06-roadmap.md](docs/06-roadmap.md) | Milestones and their gates |
| [07-loader.md](docs/07-loader.md) | Loader wire protocol |
| [08-assembler.md](docs/08-assembler.md) | Assembler reference |

Two files are normative in code rather than prose:
[`tools/opcodes.py`](tools/opcodes.py) is the only encoding table in the
project, and [`tools/cool8emu.py`](tools/cool8emu.py) is the executable
specification.

## Hardware

| | |
|---|---|
| Board | iCESugar v1.5 (~€25) |
| Display | MuseLab 12-bit VGA PMOD |
| Keyboard | PS/2, through a level shifter — a few passives |
| Programming | Drag and drop onto the iCELink drive |

The 8 MB configuration flash doubles as mass storage — the FPGA releases
its pins to user logic once configured. The SPI master issues read
opcodes only, so software cannot corrupt the bitstream it boots from.

## Status

The machine boots, puts text on screen, accepts typing, loads from flash
and runs the monitor. Audio is not built. The VGA and PS/2 connectors are
still to be made, so the image above is rendered from simulation rather
than captured from a screen.

## Licence

MIT. See [LICENSE](LICENSE).

The font is [Spleen](https://github.com/fcambus/spleen) 8×16, BSD
2-clause, vendored in [`assets/font/`](assets/font).
