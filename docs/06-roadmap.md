# 06 — Roadmap

Ordered so that each milestone produces something you can actually look
at or listen to. Nothing here is scheduled by date except M8, which has
a real deadline attached to it.

---

## M0 — Specification ✅

- [x] Decide the register model, encoding style, I/O model, audio style
- [x] Complete opcode map
- [x] Verify the board pin budget actually closes
- [x] Review pass over [02-isa.md](02-isa.md) looking for encodings that
      turn out to be unreachable or ambiguous
- [x] Repository skeleton: `rtl/core`, `rtl/soc`, `rtl/pads`, `sim`,
      `tools`, `sw`, `board`

The review pass found four genuine ambiguities, all now closed in the
spec: whether `MOV` sets flags, what reserved page-2 opcodes do, the
reset value of `SP`, and the flag behaviour of the logical, 16-bit and
`POP` instructions. Section 1.2 of the ISA is now a normative flag table
and wins over the prose anywhere they disagree.

## M1 — Reference emulator ✅

The executable specification, written before any RTL.
[`tools/cool8emu.py`](../tools/cool8emu.py).

- [x] Instruction decoder and execution for the full primary page
- [x] Page 2, including the reserved-opcode trap
- [x] Flags, interrupts, reset, bus-grant-free semantics
- [x] Disassembler driven by the shared opcode table
- [x] Trace output: PC, raw bytes, disassembly, registers, flags, cycles
- [x] Loads a flat binary at a given address and runs it
- [x] Self-test suite, mutation-tested

```bash
python tools/cool8emu.py --selftest
python tools/cool8emu.py sw/hello.bin --at 0x0200 --trace
```

**Semantics are decoded from bit fields independently of
`tools/opcodes.py`**, which supplies only length and disassembly. The
two derivations are cross-checked against each other, so a disagreement
is a real signal rather than a shared mistake.

**The suite is mutation-tested.** Seventeen deliberate bugs were
injected — wrong `V` formula, carry taken from the wrong end of a byte,
`SAR` dropping its sign bit, big-endian stack pushes, unsigned `[X+d8]`,
reserved opcodes silently becoming `NOP` — and the suite must fail on
every one. It initially caught 15 of 17; the two escapes (`SAR`
sign-extension untested, and shift cases where bit 0 and bit 7 happened
to agree) were real coverage gaps and are now closed. Re-run that
exercise whenever tests are added.

**Language: Python.** It imports `tools/opcodes.py` directly, so there
is exactly one copy of the opcode table in the project, and its traces
are trivially diffable against RTL. Instruction-level co-simulation does
not need to be fast. If M3's randomised runs turn out to be
throughput-limited, a C model can be added then — but two
implementations that must agree is a cost worth deferring.

## M2 — Assembler ✅

[`tools/cool8asm.py`](../tools/cool8asm.py), documented in
[08-assembler.md](08-assembler.md).

- [x] Two-pass assembler, labels, local labels, expressions,
      `.byte` / `.word` / `.ascii` / `.space` / `.align` / `.include`
- [x] Macros with named parameters and invocation-local labels
- [x] The §4.9.1 aliases emit the orthogonal encodings
- [x] Disassembler sharing the opcode table
- [x] Listing with per-instruction cycle counts, symbol file,
      register-pressure report

```bash
python tools/cool8asm.py sw/lib.asm -o lib.bin --listing lib.lst
python sim/test_corpus.py
```

The assembler has **no mnemonic table of its own**. It builds one at
import by disassembling every encoding in `opcodes.py` and normalising
the result through the same function it normalises source lines with, so
any text the disassembler emits is text the assembler accepts. Adding an
instruction to the table makes it assemblable with no change to the
assembler — which is exactly what happened with `ADDW X,#imm16`.

### The gate: four registers is enough ✅

Question closed by measurement — see
[D21](01-decisions.md#d21--four-general-registers-is-enough-confirmed-question-closed).

26 hand-written routines, 277 instructions: **6 spill instructions,
2.2 %. 23 of 26 routines never touch the stack.** `blit8_or` uses all
four general registers and both pointers with nothing spare and nothing
spilled.

Two things the gate found that the question had not anticipated:

- **The binding constraint is pointers, not general registers.** Four of
  the six spills are pointer pressure. A third pointer is still not
  worth it ([D22](01-decisions.md#d22--no-third-pointer-register)) —
  the primary page has a one-bit pointer field and no room — but it is
  recorded as the first thing to spend future opcode space on.
- **A missing instruction.** There was no `ADDW X,#imm16`, so adding a
  16-bit constant to a pointer took six instructions. Invisible while
  the ISA was only a document; obvious after forty lines of graphics
  code. Added as [D20](01-decisions.md#d20--addw-xyimm16-added-after-the-m2-gate).

The corpus lives in `sw/` and is verified end-to-end by
[`sim/test_corpus.py`](../sim/test_corpus.py) against results computed
in Python. That suite is mutation-tested too.

## M3 — CPU RTL

- [x] `cool8_core` against a simple synchronous RAM model
- [x] Directed test per opcode, generated from the opcode table
- [x] Randomised co-simulation against the M1 emulator, comparing full
      architectural state after every instruction
- [x] Interrupt, reset and bus-grant behaviour
- [x] `MUL` sequencer, checked against 65536 exhaustive operand pairs
- [x] Synthesis check: no FPGA primitives, no inferred RAM, no latches
- [x] LibreLane area run through the TinyTapeout flow

```bash
python sim/cosim.py all          # 511 encodings + random + interrupts + bus
python sim/cosim.py mul          # 65536 exhaustive operand pairs
python sim/synth.py              # hygiene, LUT/FF count, gate estimate
python sim/timing.py             # measured cycles per encoding
```

**Every one of the 511 encodings** is exercised by a generated probe
that sets the whole architectural state, runs one instruction and
converges on a common jump, at zero, one and randomised wait states.
Twelve randomised streams of 4000 instructions run on top of that, and
the full 64 KB memory image is compared as well as the register trace.
A bus grant is proved architecturally invisible by requiring the trace
to be byte-identical to a run without one.

**The gate passed.** `yosys` reports **969 LUT4 and 148 flip-flops**
against the ~1000 LUT estimate, and 3084 gate equivalents against
~2750 — see [03-microarchitecture.md §5.7](03-microarchitecture.md#57-area-estimate).
No latches, no inferred RAM, no vendor primitives, no tri-state.

The RTL turned out **faster than the provisional cycle table**, by one
or two clocks nearly everywhere, because there is no memory address
register and so no separate address state
([D23](01-decisions.md#d23--no-memory-address-register)).
[02-isa.md §8](02-isa.md#8-timing-model) now carries measured numbers,
and `opcodes.py`, the emulator and the RTL agree on all 511.

Two things co-simulation found that reading could not:
[D24](01-decisions.md#d24--ei-and-di-take-effect-immediately-no-delay-slot),
and the one remaining open ISA question, `MOV Rd,<pp>`'s flags.

**Brought forward from M8:** `rtl/pads/tt_um_cool8.v`, the three-phase
bus multiplexer, because LibreLane needs a `tt_um_` top to harden and a
core-only number would not be the number that matters. All 511
encodings also pass through it against a behavioural 74HC573 pair and
an SRAM, with and without wait states. The end-to-end bus-grant *load*
path — an external agent driving the merged strobes — is still M8.

### The area risk is closed

Hardened through TinyTapeout's own LibreLane flow on sky130:
**20,960 µm² of cells at 61.2 % utilisation in a 1×2 — two tiles —
with clean DRC, LVS and antenna.** Register-to-register timing closes at 50 MHz at
every PVT corner, against a design target of about 10 MHz. Full numbers
in [03-microarchitecture.md §5.8](03-microarchitecture.md#58-placed-and-routed--the-real-number).

The single biggest unknown in the schedule is now a measurement, taken
years before the deadline instead of weeks before it, and
[D19](01-decisions.md#d19--area-overruns-are-paid-for-in-tiles-not-isa-cuts)
did not need invoking. The open question that remains is only whether to
buy 4 tiles or 2 (§5.9) — a cost decision, not an
architectural one, and it was settled by running both: 1×2 closes, and
is better than 2×2 on every metric that moved.

Note that OpenLane 2 was renamed **LibreLane** in early 2026 and
TinyTapeout's `tt-gds-action` runs it; the SKY130 shuttles now go
through ChipFoundry and close roughly quarterly rather than once a year,
so "shuttle windows do not move" is less sharp than it was when this
document was written.

## M4 — First light on the FPGA

**In progress.** The clock question is settled by measurement — see
[D26](01-decisions.md#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled).
The system runs at the board's raw 12 MHz with no PLL in the CPU path;
the PLL is reserved for the pixel clock at M5, decoupled through a
dual-clock scanline buffer. §4.1's one-clock-domain rule is withdrawn.

Done so far:

- [x] `rtl/soc/cool8_uart.v` — 8N1, register-programmed divider. At
      12 MHz, 115200 baud is `div = 103` (115385, 0.16 % out)
- [x] `rtl/soc/cool8_loader.v` — frame sniffer and bus master, all seven
      commands, including the two-byte forward path a lone `$C8` needs

Both lint clean under `iverilog -Wall` and `yosys check -assert`, with
no latches. **Neither has been simulated yet.**

Remaining, in the order to do them:

1. [ ] Loader and UART testbench — drive frames in through a UART model
       and check memory. Do this *before* touching hardware: the
       `$C8`-not-followed-by-`$8C` path, the checksum boundary and
       `GO`'s write-vector-then-release-reset sequence are all easy to
       get subtly wrong and miserable to diagnose down a serial cable
2. [ ] `rtl/soc/cool8_spram.v` — 64 KB over 2 × `SB_SPRAM256KA`;
       `addr[15]` picks the block, `addr[14:1]` the word, `addr[0]` the
       byte. One wait state for the registered read
3. [ ] Boot ROM in EBR plus the overlay: reads at `$F000-$FDFF` and
       `$FF00-$FFFF` when `ROMEN`, **writes always to RAM**, `BOOTRAM`
       suppressing the overlay at CPU reset. Minimal ROM contents — the
       overlay is the part that is hard to retrofit, the contents are
       software and belong with the monitor at M6
4. [ ] I/O page decode and `rtl/soc/cool8_soc.v` — `$FE00` `SYSCTRL`,
       `$FE03` `LED`, `$FE70` UART, `$FE80` loader. `$FE00-$FEFF` always
       decodes and always wins
5. [ ] `rtl/soc/cool8_top.v` and `board/icesugar.pcf`
6. [ ] `tools/cool8load.py` — keep the transport separable, per
       [07-loader.md §4](07-loader.md)
7. [ ] Bitstream, then flash and bring up on real hardware
8. [ ] Update the constants D26 invalidates: UART divider §4.6, audio
       reference and table §4.4, timer rate §4.5

**The board is known good and connected:** iCELink DAPLink enumerates as
`F:` for drag-and-drop programming and COM6 for the serial console at
`1D50:602B`. Programming is reversible; the next bitstream overwrites
the last. Never `icesprog -e` — that is a whole-chip erase and it takes
the bitstream with it.

Superseded by D26, kept so the change is legible:

- [ ] ~~PLL: 12 MHz → 25.125 MHz~~
- [ ] SPRAM controller: byte addressing over 16-bit SPRAM, `mem_ready`
      handling
- [ ] Boot ROM in EBR with the overlay logic
- [ ] UART transmit and receive on the iCELink serial pins
- [ ] **Hardware loader** — bus master, frame sniffer, `WRITE`/`READ`/
      `GO`/`HALT`/`RUN`, per [07-loader.md](07-loader.md)
- [ ] `tools/cool8load.py` host side
- [ ] Core + RAM + LED, running a loaded program that blinks the RGB LED

The least glamorous milestone and the one that catches the most bugs.

**Do the loader before anything else on the FPGA.** Until it works,
every software change costs a full bitstream rebuild; after it works,
loading a program is one second and no rebuild, and you get 64 KB memory
read-back as a debugging tool. Everything from here to M7 goes faster
because of it. See [D15](01-decisions.md#d15--the-loader-is-hardware-not-a-rom-monitor).

## M5 — Video

- [ ] VGA timing generator, 640×480@60
- [ ] Memory arbiter, video priority
- [ ] Text mode 0 (80×30), font in EBR
- [ ] Palette registers
- [ ] Boot ROM prints a message

**A real monitor showing real text is the moment this becomes a
computer.**

## M6 — Keyboard and monitor program

- [ ] PS/2 receiver, FIFO, level shifter built
- [ ] SPI flash reader, read-only in hardware (`$FE88`)
- [ ] Monitor in ROM: memory examine/modify, disassemble, go, load a
      program from flash
- [ ] Scancode → ASCII translation in software

**Gate:** type at the machine and it answers.

## M7 — Audio and graphics modes

- [ ] Three tone channels + noise, sigma-delta output, RC filter built
- [ ] Bitmap modes 2, 3 and 4
- [ ] Raster and vblank interrupts
- [ ] A demo that draws something and plays something

At this point the machine is finished as originally scoped.

## M8 — TinyTapeout

The deadline milestone. Shuttle windows do not move.

- [ ] `rtl/pads`: the three-phase bus multiplexer
- [ ] Verilog model of a 74HC573 pair, the strobe-merge gates and an
      async SRAM
- [ ] Bus-grant load path simulated end-to-end: external agent asserts
      `nBUSRQ`, writes SRAM through the merged strobes, releases, CPU
      runs it
- [ ] Full instruction test suite re-run through the multiplexed bus
- [ ] OpenLane synthesis, real cell count, tile count decided
- [ ] Timing closure at the target frequency
- [ ] Submit

**Risk, mostly retired at M3.**
[03-microarchitecture.md §5.7](03-microarchitecture.md#57-area-estimate)
now carries synthesised numbers rather than an estimate: 969 LUT4 and
148 flip-flops on the FPGA, 3084 gate equivalents mapped to two-input
gates against a 2750 guess. That points at a 2×2 tile project. What is
still outstanding is the LibreLane run, which is the only thing that
gives a real placed-and-routed cell count and utilisation — the M3 list
has it.

The three-phase bus multiplexer was also brought forward to M3, so
`rtl/pads` and its instruction-level verification against latch and
SRAM models are already done. What remains here is the bus-*grant* load
path with an external agent, and timing closure.

**Also required:** a physical test board — TT chip, two 74HC573 latches,
one SRAM, a 74HC32 and a 74HC00 to merge the bus strobes, and an RP2040
as loader and debugger. Design it while waiting for silicon.

Put an EEPROM socket and a chip select on it too, even if you never
populate it. It is the only independent way to run code if `BUSRQ`
misbehaves in silicon, and there is no patching silicon.

`cool8load.py` should drive it with the same commands as the FPGA
loader, over a different transport. Keep that layer separable.

---

## Deliberately not scheduled

- Sprites and tile layers — the register map and the two spare SPRAM
  blocks leave room, but they are not in scope until M7 is done
- A filesystem on the SPI flash, and writing to it from the machine
  (see [D16](01-decisions.md#d16--flash-access-is-read-only-in-hardware)
  for the address-floor guard that would make it safe)
- A C compiler backend (LLVM or `vbcc`). The ISA was designed to make
  this possible; actually doing it is a separate project
- A second silicon target with more area

---

## Order-of-work notes

**Write the emulator before the RTL.** It is the cheapest place to
discover that an encoding is ambiguous or that an addressing mode is
useless.

**Write real assembly before the RTL.** M2's gate exists because the
only honest test of "is four registers enough" is a few hundred lines of
code, and the answer is much cheaper to act on before Verilog exists.

**Run OpenLane early.** Area is the one project risk that can invalidate
the architecture, and it is knowable from M3 onwards.
