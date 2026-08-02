# 06 — Roadmap

Ordered so that each milestone produces something you can actually look
at or listen to. Nothing here is scheduled by date except M8, which has
a real deadline attached to it.

---

## M0 — Specification (current)

- [x] Decide the register model, encoding style, I/O model, audio style
- [x] Complete opcode map
- [x] Verify the board pin budget actually closes
- [ ] Review pass over [02-isa.md](02-isa.md) looking for encodings that
      turn out to be unreachable or ambiguous
- [ ] Repository skeleton: `rtl/core`, `rtl/soc`, `rtl/pads`, `sim`,
      `tools`, `sw`, `board`

## M1 — Reference emulator

The executable specification, written before any RTL.

- [ ] Instruction decoder and execution for the full primary page
- [ ] Page 2
- [ ] Flags, interrupts, reset
- [ ] Trace output: PC, opcode, disassembly, register and flag state
      after each instruction
- [ ] Loads a flat binary at a given address and runs it

**Language: Python.** It imports `tools/opcodes.py` directly, so there
is exactly one copy of the opcode table in the project, and its traces
are trivially diffable against RTL. Instruction-level co-simulation does
not need to be fast. If M3's randomised runs turn out to be
throughput-limited, a C model can be added then — but two
implementations that must agree is a cost worth deferring.

## M2 — Assembler

- [ ] Two-pass assembler for the syntax in
      [02-isa.md §10](02-isa.md#10-assembler-syntax-conventions)
- [ ] Labels, local labels, expressions, `.byte` / `.word` / `.ascii`
- [ ] The §4.9.1 aliases (`SHL`, `ROL`, `CLR`, `TST`) emit the
      orthogonal encodings
- [ ] Disassembler, sharing the opcode table with the assembler

**Gate:** write a few hundred lines of real assembly — string routines,
16-bit arithmetic, a sort — and see whether four registers hold up.
This is the checkpoint for open question 1 in
[01-decisions.md](01-decisions.md#open-questions). Changing the register
model after RTL exists is expensive; changing it here is free.

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
