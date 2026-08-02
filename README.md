# COOL8

A clean-sheet 8-bit CPU and retro home-computer, built first on an
iCE40UP5K FPGA (iCESugar v1.5) and designed from day one to be
fabricable as an ASIC.

Not a 6502 clone, not a Z80 clone. It takes the 6502's implementation
discipline and a regularised, reduced version of the Z80's register and
addressing model, and drops the historical baggage of both.

## Status

Design phase. No RTL yet. The documents below are the specification
being written before any Verilog is committed.

| Area | State |
|---|---|
| ISA | v0.1 complete. 256/256 primary opcodes, normative flag table |
| Reference emulator | **Working.** Full ISA, self-tested, mutation-tested |
| Microarchitecture | Bus, FSM and ASIC pin profile specified |
| System (video/audio/keyboard) | Specified |
| Board bring-up | Pin budget verified against the board's own pinout |
| Assembler | Next (M2) |
| RTL | Not started |

```bash
python tools/cool8emu.py --selftest          # 0 failures
python tools/cool8emu.py sw/hello.bin --at 0x0200 --trace
```

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
| [tools/opcodes.py](tools/opcodes.py) | Machine-readable opcode table, disassembler, coverage check |
| [tools/cool8emu.py](tools/cool8emu.py) | Reference emulator — the executable specification |

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

TinyTapeout, within roughly a year. This is a hard constraint on the
design, not an afterthought — see
[docs/03-microarchitecture.md](docs/03-microarchitecture.md) for the
multiplexed bus profile that makes an 8-bit CPU fit in TinyTapeout's
8 in / 8 out / 8 bidir pin budget.

## Licence

See [LICENSE](LICENSE).
