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

- [x] Loader and UART testbench —
      [`sim/tb/cool8_loader_tb.v`](../sim/tb/cool8_loader_tb.v), driven by
      [`sim/test_loader.py`](../sim/test_loader.py)

All three lint clean under `iverilog -Wall` and `yosys check -assert`
with no latches; the UART is **141 LUT4 and 72 flip-flops**, the loader
**250 LUT4 and 139**.

```bash
python sim/test_loader.py            # 357 checks × 6 divider/wait-state pairs
```

Nothing on the paths that matter is stubbed. The host end bit-bangs real
8N1 at the divider the UART is programmed with, so a disagreement about
what a bit time is corrupts a byte rather than drifting quietly. The bus
is arbitrated by `cool8_core`'s own `busak` against a CPU that is
genuinely executing — spinning in a `BRA -2` at `$0000` — so the loader
only gets memory when the CPU has really let go of it, and the testbench
fails if the core drives a strobe while granted. `GO` is checked by
loading a program over the wire and requiring it to run.

**The `$C8` path was wrong, exactly where this list guessed it would
be.** `S_FWD2` forwarded the held byte unconditionally *and* re-entered
`S_MAGIC` when that byte was another `$C8`, so the byte was both passed
to the CPU and consumed as magic: `$C8 $C8 $8C` forwarded two `$C8`s
where the host sent one as data, and `$C8 $C8 $5A` forwarded four bytes
for three. A program's own serial output would have been corrupted at
about one byte in 65536, which is exactly the kind of fault that is
invisible in a bring-up and unbearable to find later. The rule is now
stated properly in [07-loader.md §1](07-loader.md#1-framing).

Two documented behaviours also turned out not to match the RTL, and the
documents were wrong rather than the code: `GO` does not need to hold the
CPU in reset while it writes the vector, because the bus grant already
keeps it away; and `LDR_CTRL` bit 0, the sniffer enable, is not
implemented at all.

**Mutation-tested, as M1 and M2 were.** Thirty-two deliberate bugs — a
big-endian `GO` vector, a checksum over the payload but not the header, a
byte-swapped `len16`, `ACK` and `NAK` exchanged, `RUN` not releasing the
bus, `mem_ready` ignored, the UART sampling on the bit edge instead of
the middle, transmitting one bit short — and the suite caught all 32.

- [x] `rtl/soc/cool8_spram.v` — 64 KB over 2 × `SB_SPRAM256KA`, in
      **31 LUT4 and 3 flip-flops** on top of the two blocks. One wait
      state on a read, none on a write; the mapping and the reasoning are
      in [03-microarchitecture.md §6.2](03-microarchitecture.md#62-spram-and-the-memory-interface)

```bash
python sim/test_spram.py             # the controller against a byte array
python sim/cosim.py spram            # the CPU running out of it
```

Two tests, because they answer different questions. The unit testbench
drives the controller as a bus master with its own 64 KB reference and a
written/not-written bitmap — SPRAM comes up undefined and an unwritten
byte reads `x`, which is the truth — and covers the handshake, both byte
lanes of a word, the block seam, every address bit as a walking one,
accesses with no gap between them, and 30 000 randomised accesses per
seed followed by a read-back sweep in address order. It localises a
fault. The co-simulation runs **all 511 encodings and three random
streams through the real `SB_SPRAM256KA` models**, comparing the
instruction trace and the whole 64 KB image against the emulator, with
the image loaded a byte at a time through the controller's own port
because that is the only way this memory can be loaded. It says whether
a fault matters.

The dump the co-simulation compares reads the SPRAM arrays directly
using the documented mapping rather than through the controller, so a
controller that consistently reads back its own wrong mapping still
fails.

**Mutation-tested**: 19 deliberate bugs — swapped byte lanes, `MASKWREN`
writing the whole word, a shifted word address, the block select taken
from `addr[14]`, no wait state on a read, a wait state on a write, a read
relaunched on its data cycle, the byte not mirrored into both halves —
and the unit testbench catches 18.

The one that escapes is **equivalent, not missed**: leaving `CHIPSELECT`
asserted through the read's data cycle re-reads the same word, because
the address is stable, so `DATAOUT` does not change. It costs power and
nothing else, and no test at the port can tell the two apart.

Running the same mutants past both testbenches also priced them against
each other, which is the reason to keep both: **two are caught only by
the unit testbench** — the ones that stop the block and half selects
being captured on the launch cycle. The CPU holds its address while
stalled, so it can never expose them, and only a testbench that
deliberately scribbles a different address onto the bus mid-stall does.

The simulation build needs `-g2012`, not because anything in `rtl/` is
SystemVerilog but because yosys's `cells_sim.v` uses default port values.
The models are not vendored: they have to match the yosys that maps the
design, and a stale copy of a memory primitive is a bug that looks like
an RTL bug.

- [x] Boot ROM in EBR plus the overlay — `rtl/soc/cool8_rom.v` and
      `rtl/soc/cool8_mem.v`, with the image built out of
      [`sw/boot.asm`](../sw/boot.asm) by
      [`tools/mkrom.py`](../tools/mkrom.py)

```bash
python sim/test_boot.py              # the ROM, the overlay, and a cold boot
```

**8 EBR blocks, 2 SPRAM, 53 LUT4 and 6 flip-flops** for the whole memory
map. `ROMEN` reloads from `~bootram` on every CPU reset rather than from
a constant, which is the entire mechanism behind the loader's `GO`: set
BOOTRAM, pulse reset, and the machine wakes with the ROM out of the map
and its reset vector taken from the RAM the loader just wrote. Clear it
and reset and it boots normally.

Four tests, ordered so a failure localises:

1. The ROM image read back through the port **against the netlist
   `synth_ice40` produces**, not just against the RTL. The RTL run proves
   `$readmemh` parses the file; only the mapped `SB_RAM40_4K` blocks with
   their `INIT_0..INIT_F` prove the image will be in the *bitstream*. A
   boot ROM that is right in simulation and empty on the board is not a
   hypothetical failure, and it is a miserable one to diagnose through a
   blank screen.
2. The overlay's four rules against patterns rather than real code, so
   which memory answered is readable from the data byte alone.
3. **The machine booting**, from power-on, with SPRAM undefined exactly
   as the part is — so the CPU cannot get anywhere at all unless its
   reset vector really came out of the ROM. It clears 60 KB, installs the
   vectors *through* its own read window, and halts. Reset to HALT is
   **365,036 clocks, 30 ms at 12 MHz**.
4. The loader's path: BOOTRAM set, a program and a vector poked into RAM,
   CPU reset pulsed, and a check that not one byte was fetched from the
   ROM window.

**Mutation-tested**: 17 deliberate bugs — the ROM window a nibble low or
covering the I/O page, writes suppressed under the overlay, the read mux
backwards, BOOTRAM inverted or ignored, the ROM given 11 address bits —
and 14 are caught. The three that are not are the same family as the one
`cool8_spram.v` has: each drops a qualification that only ever avoids
re-deriving a value nothing reads before it is re-derived, so no test at
the port can see them.

One of the escapes was real and is now closed. The testbench filled ROM
and RAM with `addr[7:0] ^ constant`, which made aliasing of the *high*
address bits invisible — a ROM wired to 11 bits passed, because the two
addresses that collided had the same low byte. Both patterns now depend
on the whole address.

Contents deliberately stop there. Bringing up video, copying a monitor
down and dropping the overlay need hardware and software that do not
exist until M5 and M6; what is here is what the overlay needs in order to
be provably working. `tools/mkrom.py` refuses to build an image with
anything at `$FE00-$FEFF`, since the I/O page wins that decode and code
there would be silently unreachable.

- [x] I/O page decode and the machine assembled —
      [`rtl/soc/cool8_soc.v`](../rtl/soc/cool8_soc.v)

```bash
python sim/test_soc.py               # the I/O page, and the whole machine
```

**1636 LUT4 and 544 flip-flops** for the entire SoC — 31 % of the
UP5K — with 8 EBR, all of them the boot ROM, and 2 SPRAM. The page is
decoded on the **bus**, ahead of `cool8_mem` and whoever the master is,
which is what makes `$FE00-$FEFF` win against 64 KB of SPRAM underneath
it and a boot ROM over the top with no exception anywhere in the map.
Registers: `$FE00` `SYSCTRL`, `$FE02` `SYSSTAT`, `$FE03` `LED`,
`$FE70-$FE73` UART, `$FE80-$FE81` loader. `$FE01` `CPUDIV` is not
implemented and reads `$FF` — D26 removed the thing it was for.

Decoding on the bus rather than on the CPU's port also means **the
loader reaches the I/O page**, so a `WRITE` frame to `$FE03` lights the
LED with no CPU, no program and no working boot ROM. That is the first
useful thing to do to a board that has just come up, and it is worth
having before there is anything else to look at.

**The obvious design does not synthesise, and the tools say so quietly.**
The I/O page has nothing to wait for — the registers are flip-flops and a
read is a mux — so the first version answered in the cycle it was
addressed. That makes the read data a combinational function of the
address, and §4 of the microarchitecture reads the opcode straight off
`mem_rdata` during a fetch, so the address is a combinational function of
the read data: a loop through the bus. `yosys` reports it as a *warning*
and maps the design anyway, and `check -assert` does not see it at all,
so it would have arrived as an unroutable placement or worse. The fix
puts every access in the machine on one shape — launch, then data — and
all three memories are now read on every launch with the answer picked
afterwards. Full reasoning in
[03-microarchitecture.md §6.3](03-microarchitecture.md#63-the-io-page-and-why-it-costs-a-wait-state).

**Two talkers, one wire.** The transmitter is shared between the loader's
replies and the program's own output, and the first arrangement — the
CPU takes the wire whenever it has a byte queued, the loader is shown a
busy line — let a program transmitting flat out **starve the loader
completely**. It refills its holding register in about fifteen clocks and
a byte takes a thousand, so the loader never saw an idle cycle to commit
on. A host that cannot interrupt a running program is a host reaching for
the reset button, which is the one thing the loader exists to avoid. The
loader now has absolute priority through a `tx_want` line, and a program
is delayed by at most one byte —
[D27](01-decisions.md#d27--the-loader-outranks-the-cpu-on-the-shared-transmitter).

Four tests, ordered so a failure localises:

1. Every register read back **through the loader's `READ` command**
   rather than by peeking at the RTL, so a register that exists but is
   not decoded fails. Unlisted addresses read `$FF` and swallow writes.
2. The page winning: a distinguishable byte deposited into the SPRAM
   under each register, and a check that the register answered and that a
   write to the page did not reach the RAM. And the other direction —
   writes to `$1200`, `$1203`, `$1270`, `$1272`, whose low bytes alias
   live registers. Every program load writes `$0400`, which aliases
   `SYSCTRL`; a decode that forgot the high byte would corrupt the
   machine every time software arrived and would look like a loader
   fault.
3. The serial path end to end: the 16-byte receive FIFO in order, full
   exactly at sixteen, an overrun that loses the *newest* byte and is
   acknowledged by writing bit 2, the divider register really driving the
   UART at three different rates, and the transmit share under
   contention.
4. **Programs the CPU actually runs**, assembled out of
   [`sim/asm/`](../sim/asm) on every run and loaded over the wire —
   because everything above reaches the page from the loader's port and
   the core's is a different master with a different address source. One
   writes the LED and halts; one echoes the serial port, so a byte makes
   the whole round trip through sniffer, FIFO, the CPU's own load and
   store, and the shared transmitter; one transmits flat out while a
   frame arrives; one overfills the transmitter to pin which byte is lost.

Then the same SoC again on the parameters the bitstream will carry —
default divider, default build id, the real boot image, SPRAM undefined —
booting cold to a blue LED in **365,036 clocks, 30 ms**. That test is the
answer to "will this work on the board", and it is the last thing to run
before item 3 below.

**Mutation-tested**: 25 deliberate bugs — the page twice as wide or at
the wrong base, an I/O write also reaching RAM and a RAM write also
reaching I/O, the read mux backwards, the read left combinational, a FIFO
that cannot tell full from empty or drops its oldest byte, the overrun
flag unacknowledgeable, `tx_want` missing the reply state — and all 25
are caught.

Three of them escaped the first pass and all three were real gaps rather
than equivalent mutants, which is the useful part. A write that reached
*every* register in the page survived because nothing wrote a RAM address
whose low byte aliased a live one. `SYSCTRL` being written by any I/O
write survived because the overlay only ever got checked at moments when
`ROMEN` happened to be right anyway. And which byte a full transmitter
drops was not pinned by anything, because no program wrote `UART_DATA`
without looking first. All three now have a test.

Loading over a **running** program also turned out to need `HALT` first:
the grant is per frame, so between one `WRITE` and the next the CPU
resumes into whatever half of the new program has landed. The testbench
found it by doing exactly that, and
[07-loader.md §2](07-loader.md#01-write) now says so as a requirement
rather than a suggestion.

- [x] `rtl/soc/cool8_top.v`, [`board/icesugar.pcf`](../board/icesugar.pcf)
      and [`tools/mkbit.py`](../tools/mkbit.py) — **there is a bitstream**

```bash
python tools/mkbit.py                # yosys, nextpnr, icepack
```

**1994 logic cells of 5280 — 37 % — 8 EBR, 2 SPRAM, 6 pins, and it
closes at 12 MHz.** The full numbers and the critical path are in
[05-board.md §6](05-board.md#6-toolchain). This is the first time the
assembled machine has been placed and routed; D26's 16.9 MHz was the
core and two SPRAM alone, without the boot ROM's block mux or the I/O
page's, and `nextpnr`'s result moves about 6 % across placer seeds. It
is the number M5's video engine has to leave intact.

`cool8_top` is deliberately thin — a power-on reset, an LED inversion,
and the machine. Two facts in it are guesses that the hardware will
settle, both with unmistakable symptoms and both listed in
[05-board.md §3.1](05-board.md#31-the-two-facts-a-first-bitstream-is-guessing-at):
the LED's polarity, and which of pins 4 and 6 the FPGA transmits on.
`cool8_top_tb` checks everything that is not a guess — that the reset
counter releases and took the right number of clocks to do it, that each
colour is its own pin and inverted, and that a frame at the default
115200 divider is answered.

**No reset button, on purpose.** One with the polarity guessed wrong
holds the machine in reset forever and looks exactly like a dead board.
It goes on once there is a board known to work.

- [x] [`tools/cool8load.py`](../tools/cool8load.py), the host side

```bash
python sim/test_load.py              # against the RTL, and against itself
```

Three layers, because the transport has to come out: `frame` and the
`parse_*` functions are the wire format and nothing else, `Transport` is
bytes in and bytes out, and `Loader` is the commands, chunking and retry
built on both. The ASIC's microcontroller bridge is one new `Transport`
subclass and no other change —
[07-loader.md §4](07-loader.md#4-on-the-asic). pyserial is imported only
by the transport that needs it, so nothing else in the tool depends on
it being installed.

Tested in two halves, because the tool has two kinds of thing in it.
**The wire format goes against the real RTL**: a session is built with
`frame`, bit-banged at `cool8_soc` by
[`cool8_wire_tb.v`](../sim/tb/cool8_wire_tb.v), and the board's actual
replies are parsed back with `parse_read` and `parse_ack`, with nothing
modelled in between. That covers the things that are wrong in practice —
byte order, what the checksum spans, how many bytes a command answers
with — and it means a board plugged in for the first time has only the
physical wire left untested. **The command loops go against a fake
board** that can be unreliable on demand: chunking, resending a rejected
chunk, and `--verify` catching a byte an ACK said nothing about.

Two behaviours are now pinned that were only prose before. A `WRITE`
whose checksum fails **has already modified memory** — the loader has no
frame buffer and commits bytes as they arrive — so the test writes
garbage, reads it back to prove it landed, and then recovers by
resending. And:

**The host must wait for a reply before sending the next frame.** The
loader stops looking at its receiver from the moment it asks for the bus
until it has finished answering, so a frame sent on top of a reply is
discarded — not executed, not forwarded to the CPU, not reported. The
first version of the wire testbench replayed a whole session
back-to-back and four commands vanished without a symptom. Nothing is
wrong with the hardware; the transmitter is busy and the frame has
nowhere to go. It is a rule, it is easy to break by pipelining, and it
is now in [07-loader.md §3](07-loader.md#3-host-side) along with its two
consequences — chunk a large `READ`, and a running program's serial
input is lost for the duration of any frame being answered.

Remaining, in the order to do them:

1. [ ] Flash it and bring it up on real hardware
2. [ ] Update the remaining constants D26 invalidates: audio reference
       and table §4.4, timer rate §4.5. The UART divider (§4.6) and
       `CPUDIV` (§4.1, §6.1) are done, since the SoC implements them

**The board is known good and connected:** iCELink DAPLink enumerates as
`F:` for drag-and-drop programming and COM6 for the serial console at
`1D50:602B`. Programming is reversible; the next bitstream overwrites
the last. Never `icesprog -e` — that is a whole-chip erase and it takes
the bitstream with it.

Superseded by D26, kept so the change is legible:

- [ ] ~~PLL: 12 MHz → 25.125 MHz~~
- [x] ~~SPRAM controller: byte addressing over 16-bit SPRAM,
      `mem_ready` handling~~ — done, above
- [x] ~~Boot ROM in EBR with the overlay logic~~ — done, above
- [x] ~~**Hardware loader** — bus master, frame sniffer, `WRITE`/`READ`/
      `GO`/`HALT`/`RUN`~~ — done, above
- [ ] UART transmit and receive on the iCELink serial *pins* — the UART
      itself is done and simulated; what is left is the `.pcf`
- [ ] `tools/cool8load.py` host side
- [ ] Core + RAM + LED, running a loaded program that lights the RGB LED
      — **it does, in simulation**, in `cool8_soc_tb`. What remains is
      the same thing on the board

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
