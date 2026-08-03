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

- [ ] `cool8_core` against a simple synchronous RAM model
- [ ] Directed test per opcode, generated from the opcode table
- [ ] Randomised co-simulation against the M1 emulator, comparing full
      architectural state after every instruction
- [ ] Interrupt, reset and bus-grant behaviour
- [ ] `MUL` sequencer, checked against 65536 exhaustive operand pairs
- [ ] Synthesis check: no FPGA primitives, no inferred RAM, no latches

**Gate:** `yosys` reports the core's LUT and FF count. If it is wildly
outside the ~1000 LUT estimate, find out why before continuing.

**Also at M3, not M8: run OpenLane.** Area is the one risk that could
invalidate the architecture, it is knowable from here onward, and
[D19](01-decisions.md#d19--area-overruns-are-paid-for-in-tiles-not-isa-cuts)
says the answer is to buy tiles — a decision much easier to make years
early than weeks before a shuttle deadline.

## M4 — First light on the FPGA

- [ ] PLL: 12 MHz → 25.125 MHz
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

**Risk:** the area estimate in
[03-microarchitecture.md §5.7](03-microarchitecture.md#57-area-estimate)
is unverified. Run OpenLane on the core as soon as M3 passes — do not
wait for M8. If the core is too large, the cuts come out of the
addressing modes and page 2, not the orthogonal ALU.

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
