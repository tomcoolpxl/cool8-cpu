# COOL8

A clean-sheet 8-bit CPU and retro home-computer, built first on an
iCE40UP5K FPGA (iCESugar v1.5) and designed from day one to be
fabricable as an ASIC.

Not a 6502 clone, not a Z80 clone. It takes the 6502's implementation
discipline and a regularised, reduced version of the Z80's register and
addressing model, and drops the historical baggage of both.

## Status

The CPU exists in Verilog and is checked against the reference emulator
instruction by instruction. Every one of the 511 encodings runs on the
RTL and produces the same architectural state and the same 64 KB of
memory as the model — including through the multiplexed ASIC bus.

| Area | State |
|---|---|
| ISA | v0.1 complete. 256/256 primary opcodes, normative flag table |
| Reference emulator | **Working.** Full ISA, self-tested, mutation-tested |
| Assembler | **Working.** Macros, listings, register-pressure report |
| Software corpus | 26 routines, verified against Python in the emulator |
| **CPU RTL** | **Working.** 511/511 encodings co-simulated against the emulator |
| Timing | **Measured**, not estimated. 969 LUT4, 148 FF on iCE40 |
| ASIC pad wrapper | Three-phase bus, verified against latch and SRAM models |
| **Silicon** | **Hardened.** Fits in two TinyTapeout tiles, clean DRC/LVS |
| **SoC** | **Simulated.** Memory, boot ROM, UART, loader and I/O page; boots cold to a lit LED |
| **Bitstream** | **Running on the board.** 1994 of 5280 logic cells, closes at 12 MHz |
| System (video/audio/keyboard) | Specified |
| Board bring-up | **Done.** Boots, answers, runs loaded programs, echoes serial |
| Open design questions | **None.** All 27 decisions logged; the last two closed at M4 |
| Next | Video — a real monitor showing real text (M5) |

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
| [rtl/core/](rtl/core/) | The CPU: `cool8_core.v`, `cool8_alu.v`, `cool8_agu.v` |
| [rtl/pads/](rtl/pads/) | `tt_um_cool8.v` — the TinyTapeout three-phase bus |
| [sim/](sim/) | Co-simulation, program generators, synthesis and timing gates |
| [sw/](sw/) | Software corpus: library, graphics, compiler-style frames |

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

- **FPGA board:** iCESugar v1.5 (Lattice iCE40UP5K-SG48, 5280 LUT4,
  ~120 Kbit EBR, 4 × 256 Kbit SPRAM, 1 PLL, 12 MHz clock)
- **Video:** MuseLab PMOD-VGA (12-bit 4:4:4) → VGA monitor
- **Keyboard:** PS/2, level-shifted to 3.3 V
- **Audio:** 4-channel SN76489-style tone/noise generator, 1-bit
  sigma-delta out through an RC filter
- **Loading:** hardware loader over the board's USB serial — `cat` a
  binary at the machine, no bitstream rebuild. 8 MB SPI flash as storage.

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
