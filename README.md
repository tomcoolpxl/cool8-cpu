# COOL8

A clean-sheet 8-bit CPU, and the whole computer around it: memory,
video, sound, keyboard and a hardware loader, on one iCE40UP5K FPGA
(iCESugar v1.5). The CPU is also designed from day one to be fabricable
on its own as an ASIC.

It takes the 6502's implementation discipline and a regularised, reduced version of the Z80's register and addressing model, and drops the historical baggage of both.

![Text mode 0: a box in CP437 line-drawing characters, the full 256-glyph
character set, and all sixteen palette colours](docs/img/text-mode-0.png)

*Text mode 0, captured off the RGB pins. Not a photograph — there is no
VGA PMOD yet, so this is a whole frame taken out of the simulator through
the real raster and the real font ROM, which is also how the video engine
is developed. `python sim/test_video.py` regenerates it.*

## The machine

```
   12 MHz ──▶ cool8_top ......... pins, power-on reset, the LED
                  │
              cool8_soc ......... the bus, and the I/O page at $FE00
                  │               that is decoded ahead of everything
                  ├── cool8_core ...... the CPU
                  ├── cool8_mem ....... the memory map and the ROM overlay
                  │     ├── cool8_spram .... 64 KB over 2 x SB_SPRAM256KA
                  │     └── cool8_rom ...... 4 KB boot ROM in EBR
                  ├── cool8_uart ...... 8N1, divider in a register
                  └── cool8_loader .... bus master on the end of the wire

              cool8_vga ......... the 640x480 raster        ─┐ built and
              cool8_text ........ 80x30 text, font, palette ─┘ verified,
                                                               not yet wired

              video RAM ......... 64 KB over the other 2 x SB_SPRAM256KA,
                                  its own address space. Text reads main
                                  RAM; everything else reads this, so the
                                  blitter never stalls the CPU
```

Sizes are measured, not estimated — every one is recorded in
[docs/](docs/) with the run that produced it.

| Block | What it is | Size | State |
|---|---|---|---|
| `cool8_core` | The CPU. 511 encodings, 4+2 registers | 948 LUT4, 148 FF | **On the board** |
| `cool8_spram` | 64 KB byte-addressed over 16-bit SPRAM | 31 LUT4, 2 SPRAM | **On the board** |
| `cool8_rom` | 4 KB boot ROM, and the font | 8 EBR | **On the board** |
| `cool8_mem` | Memory map, ROM overlay, `BOOTRAM` | 53 LUT4 | **On the board** |
| `cool8_uart` | Serial, to the iCELink USB bridge | 141 LUT4, 72 FF | **On the board** |
| `cool8_loader` | Loads and debugs RAM with the CPU held off | 250 LUT4, 139 FF | **On the board** |
| `cool8_soc` | Everything above, assembled: the bus, the I/O page, the shared UART | **1636 LUT4 all in** | **On the board** |
| `cool8_vga` | 640×480 @ 60, both syncs | 51 LUT4, 46 FF | Verified, not wired |
| `cool8_text` | Text mode 0, CP437 font, palette | 266 LUT4, 9 EBR | Verified, not wired |
| VRAM + arbiter | 64 KB of dedicated video RAM, four requesters | — | **Next** |
| video fetch | Text, tile and bitmap over one parameterised engine | — | **Next** |
| blitter | Rects, transparency, clipping, logic ops, lines | — | Specified (M5) |
| sprites | 32 descriptors, 8 per scanline, 4 bpp | — | Specified (M5) |
| audio | 3 tone + 1 noise, sigma-delta out | — | Specified (M7) |
| PS/2 | Keyboard, 16-byte FIFO | — | Specified (M6) |
| timer, SPI flash | Periodic interrupt; flash as storage | — | Specified (M6) |

**Placed and routed, the whole bitstream is 1994 of the UP5K's 5280
logic cells, and it closes at 12 MHz** — CPU, 64 KB of RAM, boot ROM,
serial and loader, running on real hardware. A logic cell is a LUT4 with
its carry and flip-flop, so that number is larger than the LUT4 count
above and is the one that decides whether the part is full.

## Status

| Area | State |
|---|---|
| ISA | v0.1 complete. 256/256 primary opcodes, normative flag table |
| Reference emulator | **Working.** Full ISA, self-tested, mutation-tested |
| Assembler, corpus | **Working.** Macros, listings; 26 routines verified |
| **CPU RTL** | **Working.** 511/511 encodings co-simulated against the emulator |
| **SoC** | **Running on real hardware.** Boots cold, answers, runs loaded programs, echoes serial |
| **Video** | Raster verified pixel by pixel; text mode 0 draws a real CP437 font in 16 colours |
| Audio, keyboard | Specified, not built |
| ASIC pad wrapper | Three-phase bus, verified against latch and SRAM models |
| **Silicon** | **Hardened.** Fits in two TinyTapeout tiles, clean DRC/LVS |
| Open design questions | **One.** Whether the video engine as scoped fits the UP5K — a fit question, settled by M5's synthesis gate, not by argument. 31 decisions logged |
| Next | VRAM, the arbiter and the fetch engine — then measure before building the blitter and sprites (M5) |

The CPU is checked against the reference emulator instruction by
instruction: every one of the 511 encodings produces the same
architectural state and the same 64 KB of memory as the model, including
through the multiplexed ASIC bus.

```bash
python tools/opcodes.py --check              # opcode map coverage
python tools/cool8emu.py --selftest          # ISA semantics
python sim/test_corpus.py                    # 26 routines, end to end
python tools/cool8asm.py sw/gfx.asm --pressure

python sim/cosim.py all                      # RTL against the emulator
python sim/cosim.py mul                      # 65536 exhaustive products
python sim/synth.py                          # area and synthesis hygiene
python sim/timing.py                         # measured cycles per encoding

python sim/test_loader.py                    # UART and loader, over a wire
python sim/test_spram.py                     # the SPRAM controller
python sim/test_boot.py                      # boot ROM and the overlay
python sim/test_soc.py                       # the I/O page, and a cold boot
python sim/test_load.py                      # the host loader
python sim/test_video.py                     # raster, font, text -> build/*.png

python tools/mkbit.py                        # build/cool8.bin
```

The RTL work needs [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build)
on `PATH`, or `OSS_CAD_SUITE` pointing at its root.

## Documents

| Doc | Contents |
|---|---|
| [docs/00-goals.md](docs/00-goals.md) | What we're building, hard constraints, non-goals |
| [docs/01-decisions.md](docs/01-decisions.md) | Decision log — every architectural call and why |
| [docs/02-isa.md](docs/02-isa.md) | Instruction set architecture, complete opcode map |
| [docs/03-microarchitecture.md](docs/03-microarchitecture.md) | Datapath, bus protocol, TinyTapeout pin profile |
| [docs/04-system.md](docs/04-system.md) | Memory map, video, audio, keyboard, boot |
| [docs/05-board.md](docs/05-board.md) | iCESugar v1.5 pinout, PMODs, external circuits, BOM |
| [docs/06-roadmap.md](docs/06-roadmap.md) | Milestones |
| [docs/07-loader.md](docs/07-loader.md) | Loader wire protocol |
| [docs/08-assembler.md](docs/08-assembler.md) | Assembler reference |
| [tools/opcodes.py](tools/opcodes.py) | Machine-readable opcode table, disassembler, coverage check |
| [tools/cool8emu.py](tools/cool8emu.py) | Reference emulator — the executable specification |
| [tools/cool8asm.py](tools/cool8asm.py) | Assembler and disassembler |
| [tools/cool8load.py](tools/cool8load.py) | Host end of the loader — load, dump, halt, run |
| [tools/cool8screen.py](tools/cool8screen.py) | The machine's text screen, in a terminal on the PC |
| [tools/mkbit.py](tools/mkbit.py) | The bitstream: yosys, nextpnr, icepack |
| [rtl/core/](rtl/core/) | The CPU: `cool8_core.v`, `cool8_alu.v`, `cool8_agu.v` |
| [rtl/soc/](rtl/soc/) | The machine: memory, boot ROM, UART, loader, I/O page, raster, text mode |
| [rtl/pads/](rtl/pads/) | `tt_um_cool8.v` — the TinyTapeout three-phase bus |
| [sim/](sim/) | Co-simulation, program generators, synthesis and timing gates |
| [sw/](sw/) | Software corpus: library, graphics, compiler-style frames |
| [assets/font/](assets/font/) | Spleen 8x16, BSD 2-clause, converted to the font EBR image |

## The shape of it in one screen

```
        R0 R1 R2 R3     four 8-bit general registers, fully orthogonal
        X  Y            two 16-bit pointer registers
        SP              16-bit stack pointer
        PC              16-bit program counter
        F               C Z N V I

        MOV  ADD  ADC  SUB  SBC  AND  OR  CMP
             ^ these eight, on any register, from any register or an
               immediate, in one or two bytes

        LD Rd,[X]          ST [Y],Rd          1 byte
        LD Rd,[X+d8]       ST [Y+d8],Rd       2 bytes
        LD Rd,[SP+d8]      ST [SP+d8],Rd      2 bytes
        LD Rd,[abs16]      ST [abs16],Rd      3 bytes

        Bcc rel8           16 ARM-style conditions
```

A byte copy loop:

```asm
        ; X = source, Y = destination, R0 = length
loop:   LD   R1,[X]        ; 1
        ST   [Y],R1        ; 1
        INCW X             ; 1
        INCW Y             ; 1
        SUB  R0,#1         ; 2
        BNE  loop          ; 2      -> 8 bytes, R2 and R3 still free
```

## Hardware

**FPGA board:** iCESugar v1.5 — Lattice iCE40UP5K-SG48, 5280 LUT4,
~120 Kbit EBR, 4 × 256 Kbit SPRAM, 1 PLL, 12 MHz clock. Nothing else is
needed to run what exists today.

| | | |
|---|---|---|
| **Loading** | Hardware loader over the board's own USB serial — `cat` a binary at the machine, no bitstream rebuild | **Working** |
| **Video** | MuseLab PMOD-VGA (12-bit 4:4:4) → VGA monitor | Not bought. The engine is developed and verified without it — see below |
| **Keyboard** | PS/2, level-shifted to 3.3 V | Not built. Typing at the serial port already reaches the machine |
| **Audio** | 3 tone + 1 noise, 1-bit sigma-delta through an RC filter | Not built (M7) |
| **Storage** | The board's own 8 MB SPI flash, read-only in hardware | Not built (M6) |

### Working without the display

The missing hardware does not block the work, which is worth stating
because it looks like it should.

- **The screen is memory.** Mode 0 is 4800 bytes and a bus grant is
  architecturally invisible, so `tools/cool8screen.py` reads the
  framebuffer out from under a running program and draws it in a
  terminal, over the serial port, at about two frames a second.
- **The video engine is verified by looking at it.**
  `python sim/test_video.py` renders whole frames off the RGB pins to
  `build/*.png` — the raster, and a screen of real text — which stays
  the reference the hardware has to match afterwards. The two copies in
  [docs/img/](docs/img/) are the current output.

  ![The raster test pattern: a one-pixel border pinned at all four edges
  and a 45-degree diagonal](docs/img/raster-test-pattern.png)

  *The raster on its own. The border pins all four edges of the 640×480
  window and the diagonal shears if a line is the wrong length, so a
  timing error is visible rather than merely detectable — which is the
  point of rendering it at all.*
- **A monitor is cheap when it is wanted.** The PMOD-VGA is three
  resistor ladders and a connector; one resistor per channel gives eight
  colours and proves the timing.

## ASIC target

TinyTapeout. This is a hard constraint on the design, not an
afterthought — see
[docs/03-microarchitecture.md](docs/03-microarchitecture.md) for the
multiplexed bus profile that makes an 8-bit CPU fit in TinyTapeout's
8 in / 8 out / 8 bidir pin budget.

**It fits.** Hardened through TinyTapeout's LibreLane flow on sky130 at
M3, years ahead of any deadline, because area was the one risk that
could have invalidated the architecture:

| | |
|---|---|
| Standard cells | 2420, of which 158 sequential |
| Cell area | 20,960 µm² — 61 % of a 1x2 tile |
| Register-to-register timing | closes at 50 MHz at every PVT corner |
| DRC / LVS / antenna | clean |
| Power | 1.48 mW |

The design target is around 10 MHz, which puts the chip in the same
performance class as a 1 MHz 6502 — appropriate, and not the limiting
factor when you are talking to a 55 ns SRAM.

## Licence

See [LICENSE](LICENSE).
