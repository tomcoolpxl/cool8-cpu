# COOL8

An 8-bit home computer on a single iCE40UP5K FPGA.

Everything in it is an original design, built in this repository: the
CPU is a completely new design, not a 6502 or a Z80 or a derivative of either, the video and audio chips are custom as well, and the BASIC in ROM was written for this hardware. Power the board on and it boots from SPI flash into a full-screen BASIC editor.

![The BASIC editor after boot: the banner, the machine's vitals, and a
ten-line graphics program typed in](docs/img/readme-editor.png)

*The editor, with a program typed in. This is the emulator booting the
same flash image the board boots — the picture regenerates from source.*

`RUN` that program and:

![Mode 4: sixteen palette lines, a diagonal, and GTEXT lettering on
blue](docs/img/readme-mode4.png)

## The machine

| | |
|---|---|
| **CPU** | COOL8 — 8-bit, 16-bit address space, 511 encodings, four registers and two 16-bit pointers. 902 LUT4, no vendor primitives |
| **Memory** | 64 KB RAM, plus a separate 64 KB of video RAM |
| **Video** | 640×480 VGA. Text, tiles and bitmaps from one engine; 32 sprites, 8 per scanline; 256-colour palette from 4096 |
| **Sound** | 8 voices — squares and noise, 4-bit volume, 1-bit sigma-delta out |
| **Input** | PS/2 keyboard and a serial console as equals: `INKEY` reads a queue, `KEY(c)` reads which keys are down right now |
| **Storage** | 8 MB SPI flash — the bitstream, the system, and a filesystem for `SAVE`/`LOAD`/`DIR` |
| **Software** | BASIC with a full-screen editor, graphics, sound, an inline assembler and 8.8 fixed point — 24 KB, resident in the top of RAM |
| **Board** | iCESugar v1.5 — Lattice iCE40UP5K, 5280 logic cells |

## Run it — no board required

The whole machine exists in software: the CPU model is checked
instruction-for-instruction against the Verilog, the renderer is
compared against frames dumped from the gates on all 307,200 pixels of
every mode, and the sound model against samples of the running engine.
What the window shows is what the silicon does.

You need Python 3.12+ and Node 18+, then:

```bash
pip install pygame-ce numpy
```

```bash
npm run disk
```

```bash
npm run emu -- --flash build/cool8.img
```

`disk` builds `build/cool8.img`, a flash image with BASIC installed;
`emu` boots it in a window. In the window:

- **Typing** arrives exactly as typed, on any keyboard layout; held keys
  repeat.
- **Ctrl+Pause** is Break — it stops a running program, same as on the
  board.
- **Right mouse button** pastes the clipboard into the machine.
- **F12** writes the screen to a PNG; `--wav out.wav` records the sound.

Something to type at it:

```js
10 MODE 4
20 CLG 1
30 GTEXT 96, 24, "COOL8 BASIC", 10
40 FOR I = 0 TO 15
50 HLINE 60, 56 + I * 9, 200, I
60 NEXT I
70 LINE 0, 239, 319, 0, 7
80 DO
90 VSYNC
95 LOOP
RUN
```

The language — every statement, operator, graphics and sound command,
`ASM` for inline machine code, and the size ledger the whole thing is
accountable to — is documented in [docs/13-basic.md](docs/13-basic.md).

## What's inside

![Block diagram: the COOL8 CPU connected to memory, video, UART, PS/2,
sound and SPI flash, each wired to its connector](docs/img/readme-soc.svg)

*Generated from the RTL by `npm run diagram` — yosys elaborates the SoC
and the diagram states what is actually connected, not what a drawing
claims.*

Text mode reads main RAM; tiles, bitmaps and sprites read the separate
video RAM through a four-way arbiter — so nothing the video engine
fetches can stall the CPU. The full module tree and every design
decision are in [docs/03-microarchitecture.md](docs/03-microarchitecture.md)
and [docs/01-decisions.md](docs/01-decisions.md).

What the part holds, placed and routed:

```
ICESTORM_LC      5022 / 5280   95 %
ICESTORM_RAM       28 / 30     93 %
ICESTORM_SPRAM      4 / 4     100 %
ICESTORM_DSP        1 / 8      12 %
```

## Putting it on a board

Hardware work needs the
[OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build):
put its `bin` on `PATH` or set `OSS_CAD_SUITE` to its root, then let
the environment check tell you where you stand:

```bash
npm run doctor
```

Build the bitstream, then program the board — bitstream and system
image both, written over USB and verified by reading them back:

```bash
npm run bit
```

```bash
npm run flash
```

The board boots into the same BASIC as the emulator. With only the USB
cable connected, the serial console (115200 8N1 on the iCELink's CDC
port) is the keyboard and `npm run board:screen` reads the screen back;
every BASIC command has been verified on the chip through that wire.
The VGA, PS/2 and audio connectors are wired in the gates but await
their physical counterparts — the pinout and the bench notes live in
[docs/05-board.md](docs/05-board.md), the plan in
[docs/06-roadmap.md](docs/06-roadmap.md).

## Tests

```bash
npm test
```

runs the software suites in parallel — interpreter, editor, assembler,
compiler, filesystem, and a cold boot from a flash image. The other
phases:

```bash
npm run test:rtl
```

```bash
npm run test:board
```

`test:rtl` simulates the Verilog, including `cosim` — the emulator
executed in lockstep against the RTL, which is the gate for any RTL
change. `test:board` talks to the real board. The full command
vocabulary is [docs/12-tasks.md](docs/12-tasks.md); `npm run list`
prints it.

## Documentation

| | |
|---|---|
| [00-goals.md](docs/00-goals.md) | what this project is and is not |
| [01-decisions.md](docs/01-decisions.md) | every design decision, numbered, with its reasoning |
| [02-isa.md](docs/02-isa.md) | the CPU: registers, encodings, every instruction |
| [03-microarchitecture.md](docs/03-microarchitecture.md) | how the core and the video chip are built |
| [04-system.md](docs/04-system.md) | the memory map and the I/O page |
| [05-board.md](docs/05-board.md) | the iCESugar: pins, flash, traps found on real hardware |
| [06-roadmap.md](docs/06-roadmap.md) | what works, what's next |
| [08-assembler.md](docs/08-assembler.md) | the assembler, host-side and on-machine |
| [10-debugging.md](docs/10-debugging.md) | how to investigate this machine |
| [11-compiler.md](docs/11-compiler.md) | the self-hosted compiler |
| [12-tasks.md](docs/12-tasks.md) | the commands |
| [13-basic.md](docs/13-basic.md) | the BASIC language reference |

## License

[MIT](LICENSE).
