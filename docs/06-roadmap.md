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

**The gate passed.** `yosys` reports **948 LUT4 and 148 flip-flops**
against the ~1000 LUT estimate, and 3080 gate equivalents against
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

## M4 — First light on the FPGA ✅

**Done — the machine runs on the board.** The clock question is settled by measurement — see
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
   vectors *through* its own read window, and hands over. At M4 it ended
   on a HALT there, because there was nothing to hand over to; since M6
   the stopping point is the jump into the monitor, which this testbench
   cannot run — it has no I/O page, so the console reads uninitialised
   SPRAM. Reset to the handover is **366,091 clocks, 43.7 ms at
   8.375 MHz**.
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
[05-board.md §3.1](05-board.md#31-the-two-facts-a-first-bitstream-guessed-at):
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

- [x] **Flashed, and it works.**

Programmed by copying `build/cool8.bin` onto the iCELink drive. The
first bitstream came up and answered, and everything below was read off
the real board rather than out of a simulator:

| Asked | Answered |
|---|---|
| `--ping` | `loader version 1` |
| `$FE02` `SYSSTAT` | `04` — the build that was just flashed |
| `$FE72/73` `UART_DIV` | `67 00` — 103, and 115200 baud works |
| `$FE01` `CPUDIV` | `FF` — unimplemented, as documented |
| `$FE03` `LED` | `01` — **the boot ROM ran** |
| `$0000`, `$EFF0` | all zero — 60 KB cleared |
| `$FFF8` with `ROMEN=0` | `00 F0 4B F0 …` — the vectors, in RAM |
| `$F000` with `ROMEN=0` | `77 1C BA F4 …` — live uninitialised SPRAM |
| `$F000` with `ROMEN=1` | `2F 60 00 02` — `LDW X,#$0200` |

Those last three are the overlay proving itself on silicon: the vectors
were written *through* the ROM's own read window into the RAM
underneath, the RAM above `$EFFF` is the garbage the part really does
come up with, and the ROM is where it should be. Nothing but hardware
can demonstrate the middle one.

Then loaded programs. `soc_led.bin` written, verified byte for byte,
`GO`, and `$FE03` reads `06` — a CPU executing code that arrived over a
wire. Then `soc_echo.bin`, and the machine held a conversation:

```
sending : Hello from COOL8 on real silicon!
echoed  : Hello from COOL8 on real silicon!
```

Every byte of that went in as edges on pin 4, through the sniffer, the
receive FIFO, the CPU's own `LD` and `ST` through the I/O page, the
shared transmitter, and back out on pin 6. Two more things fell out of
the same session, both of which had only ever been true in simulation:
`$C8 $5A` came back as two bytes and not four — the `S_FWD2` bug
simulation found at the top of this milestone — and a `PING` sent while
the echo program was running flat out was answered, which is
[D27](01-decisions.md#d27--the-loader-outranks-the-cpu-on-the-shared-transmitter)
holding on real timing.

Finally `RESET`: the machine rebooted from ROM, cleared RAM again — the
loaded program at `$0400` reads back as zeros — and lit the LED.

**One guess of the two was settled and one was not.** Pins 4 and 6 are
the right way round, or nothing would have answered. LED *polarity*
cannot be read back: the register says `01` either way, and only an eye
on the board can say whether that is blue or yellow. See §3.1 of
[05-board.md](05-board.md).

- [x] The constants D26 invalidated

Audio (§4.4), the timer (§4.5), the sigma-delta rate, the block diagram
and the video bandwidth sum (§5.3) — the last two were not on the list
and were wrong in the same way, which is reason enough. The UART divider
(§4.6) and `CPUDIV` (§4.1, §6.1) were done when the SoC implemented them.

Two of them are worth reading, because they went opposite ways for a
stated reason. **Audio keeps its reference and changes its divider**:
12 MHz ÷ 32 = 375 kHz rather than ÷64, because §4.4 is a table of notes
that have to stay in tune and 375 kHz lands them within 0.05 % while
keeping the bass floor at 45.8 Hz. **The timer keeps its divider and
lets its rate follow**: nothing has to land on a frequency, so ÷256 and
46.875 kHz, which halves the tick and doubles the reach of a 16-bit
reload to 1.40 s.

And §5.3's bandwidth arithmetic was doubly wrong — it divided by
25.125 MHz, and it counted per pixel rather than per scanline, which is
the unit a scanline buffer works in. Done properly it is 10.5 % in the
worst mode and 1.3 % in text, against the 12.5 % it used to claim: the
conclusion was right by accident and is now right on purpose.

**M4 is done.**

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

**In progress, and being built without a monitor.** The VGA PMOD is not
bought yet, which changes how this is developed and not what is built —
see §Working without the display below.

The architecture is settled — [D28](01-decisions.md) through
[D31](01-decisions.md) and [04-system.md §5](04-system.md). **What is
not settled is whether all of it fits**, and the order below exists to
answer that with a synthesis report rather than an estimate.

- [x] VGA timing generator, 640×480@60 —
      [`rtl/soc/cool8_vga.v`](../rtl/soc/cool8_vga.v)
- [x] Text mode 0 (80×30), font in EBR, dual-clock line buffer and the
      palette — `cool8_text.v`, since replaced by the general engine
      below and deleted
- [x] VRAM controller over the two spare SPRAM blocks, and the four-way
      arbiter — [`rtl/soc/cool8_vram.v`](../rtl/soc/cool8_vram.v), in
      **93 LUT4 and 5 flip-flops** on top of the two blocks

```bash
python sim/test_vram.py              # all four requesters against a word array
```

The block is sixteen bits wide rather than eight, because nothing here
has the core's 8-bit bus to answer to, and the bandwidth budget in
[04-system.md §5.10](04-system.md) is counted in these accesses. Three
properties are load-bearing and each has a test:

1. **A grant every cycle, with no turnaround bubble.** `DATAOUT` is
   registered but SPRAM will take a new address the very next cycle;
   `cool8_spram` spends that cycle as a wait state only because the
   core's protocol makes it, and nothing here does. 64 back-to-back
   reads must take 64 cycles.
2. **Per-nibble writes.** `MASKWREN` has one bit per nibble and a 4 bpp
   pixel *is* a nibble, so plotting one is a native masked write with no
   read-modify-write in the mode most drawing happens in. Each of the
   four nibbles is written alone and the other three checked untouched.
3. **Strict priority does not starve the blitter.** Under a load harsher
   than §5.10's worst case — an 8 bpp display, sprites, *and* a CPU port
   asking on 8 % of cycles — the blitter measures **51.3 %** of grants.
   The test asserts 45 %, which is nine sigma below that mean and two
   orders of magnitude above what a broken arbiter gives.

Only five flip-flops: four `rvalid` and the captured block select. The
block select is taken on the grant cycle rather than re-read on the data
cycle, keeping it off the read data path that
[D26](01-decisions.md#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled)
measured as the critical one in the machine.

**Mutation-tested**, as every block since M1 has been: 19 deliberate
bugs — every one of the four priority terms broken in turn, a requester
granted without asking, the address mux permuted, the block select taken
from `addr[14]` or re-read combinationally, the read mux backwards,
`rvalid` unqualified by write or asserted a cycle early, nibble masks
forced to `4'hF`, the write-data and mask muxes swapped, `WREN` ungated
by the grant, the word address shifted, both blocks chip-selected at
once, and `active` missing the blitter — and **all 19 are caught.**

Two of them were caught only because the scoreboard runs continuously
rather than per phase: a read that returns another requester's data
produces a plausible value, not an obviously wrong one, and nothing but
a reference model notices.

- [x] `VRAM_ADDR`/`VRAM_DATA` indirect port and the `$FEC0-$FEFF` alias —
      [`rtl/soc/cool8_vport.v`](../rtl/soc/cool8_vport.v), in **170 LUT4
      and 59 flip-flops**

```bash
python sim/test_vport.py             # the port against a real cool8_vram
```

**The prefetch is not an optimisation, it is the only way a read works.**
The I/O page has one timing shape and cannot negotiate — launch in one
cycle, answer in the next ([§6.3](03-microarchitecture.md)) — and a VRAM
read has to win the arbiter and then wait a cycle for `DATAOUT`. So the
byte at the current address is kept in a register, fetched ahead. A read
of `VRAM_DATA` hands over the register, advances and re-arms. It is the
same arrangement every VDP with a data port has used, and the reason
those chips all want a dummy read after setting the address.

**A prefetch is issued after a read and after an address write, never
after a write of data.** Writing is the bulk direction — loading a tile
set, clearing a buffer — and fetching after each one would double the
port's VRAM traffic to serve a read that is not coming. The cost is one
stall on the first read after a burst, and `under_contention` is the
test for it.

`o_stall` covers the rest: the core tolerates arbitrary wait states and
`sim/cosim.py` already proves it against randomised ones, so a slow
fetch is correct rather than merely usual.

**One step code follows `VID_STRIDE`** instead of the fixed table of
awkward row pitches VERA needs, because the register holding the current
mode's row pitch already exists. The other seven are 0, 1, 2, 4, 8, 16
and 256, and bit 3 turns any of them round.

**No cached word.** A 16-bit fetch straddles two byte addresses and
holding it would serve two sequential reads from one access — but the
blitter writes the same memory, and a cache with no invalidation from
the other three requesters returns a stale byte after any blit that
touched it. One fetch per read; the bandwidth is there.

**Mutation-tested: 26 deliberate bugs, 25 caught.** The alias a nibble
too narrow, too wide, or absent; every step code and the decrement bit;
an advance dropped on reads or on writes; a register read treated as a
data access; the write mask fixed, inverted or whole-word; a posted
write using the advanced address; the prefetch half taken from the wrong
bit or picked backwards; both stall conditions removed; a stalled read
not carried across the gap; `ADDR_H` written into the low half.

The one escape was included expecting it to: issuing a prefetch after a
write as well is functionally identical and merely wasteful, so no test
at the port can see it. It is a performance mutant, not a missed bug.

**Two of the caught bugs are the hazard this block was rewritten for.**
A fetch issued against one address, with the address moved before the
data returned, must not let that byte land as valid — `pf_stale` is what
stops it, and the window is only a cycle or two wide, so
`stale_prefetch` walks an address write across it at six offsets, twice,
once with the memory busy.

**And two testbench faults, both of which read as RTL bugs.** Registering
`o_stall` and sampling it after `@(posedge clk)` reads the value from one
edge earlier, because a task resumes before the non-blocking update
lands — every read appeared to return its predecessor's byte. Moving the
handshake to the negative edge then broke it the other way: dropping
`io_rd` at the negedge takes the launch pulse away before the posedge
samples it, and no read happened at all. The rule is that **the strobe is
driven from the positive edge and the handshake is read at the
negative** one, and it is now stated at the top of the testbench.
- [x] The fetch engine: all three engines, the stride register, scroll,
      and the memory select off the mode decode —
      [`cool8_fetch.v`](../rtl/soc/cool8_fetch.v)
- [x] Pixel shifter, 1/2/4/8 bpp, attribute decode, hardware cursor —
      [`cool8_pixel.v`](../rtl/soc/cool8_pixel.v)
- [x] 256-entry palette in EBR behind `PAL_IDX`/`PAL_DATA` —
      [`cool8_pal.v`](../rtl/soc/cool8_pal.v)
- [x] `VID_*` wired to the I/O page —
      [`cool8_vregs.v`](../rtl/soc/cool8_vregs.v),
      [`cool8_video.v`](../rtl/soc/cool8_video.v)
- [x] Raster and vblank interrupts, ORed into the core's `irq`

```bash
python sim/test_video.py             # every mode, every visible pixel
```

**`cool8_text.v` is gone.** The general engine replaced it, and the
proof is that `docs/img/text-mode-0.png` — the committed screen the old
block produced — comes back **byte-identical** from the new one. That is
the strongest form the check could take: same font, same palette, same
CP437 screen, a different fetch path and a different shifter.

**The testbench carries its own answer.** `golden()` in
[`cool8_video_tb.v`](../sim/tb/cool8_video_tb.v) computes the colour of
every visible pixel from the register values, the memory image and the
font, using the arithmetic [04-system.md §5](04-system.md) states — and
it is written the long way round on purpose. It multiplies where the RTL
accumulates, it flips a tile by renumbering its pixels where the RTL
reverses nibbles and swaps words, and it walks all 32 sprite descriptors
in order where the RTL renders eight of them backwards. Two derivations
that agree are evidence; one derivation checked against itself is not.

Sixteen frames, **five million pixel comparisons**: all four depths,
both text widths, tiles with every attribute combination, fine scroll in
both directions, all three cursor styles, a bordered mode, and main RAM
made deliberately grudging so the text fetch has to wait for the CPU.

Three bugs it found that no count would have:

- **The line number arrived one edge late.** `line_y` was captured on
  the same clock as the pulse that announces it, so every consumer saw
  the *previous* line's number for the cycle it acted on — and the
  display changed bank one scanline late. The symptom was that the first
  line of every character row was drawn from the row above it, and it is
  invisible in anything but a picture. Capturing the value one edge ahead
  of the pulse is the fix.
- **Vertical blanking has to prime two rows, not one.** Without a scroll
  the first row boundary is line 0 and one primed row is enough; with a
  fine vertical scroll of five it moves to line 11, and nothing between
  vblank and line 11 would have fetched the row the raster wants there.
- **A tile's attribute has to be fetched by "the next pixel is in a
  different tile", not by "this is pixel seven".** The two are the same
  everywhere except at the end of a line, and that is the one place it
  matters — with a fine scroll the first tile of every line was drawn in
  the palette bank of the last tile of the line before.

### 🚩 The gate: does it fit? — **answered, and it cost the blitter**

```bash
python sim/test_soc.py               # LUT4 for the whole SoC
python tools/mkbit.py                # placed LC, and whether it closes
```

**No, not as scoped.** The gate did its job twice — once on area and
once on timing — and both answers changed the plan. The reasoning is
[D34](01-decisions.md#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter)
and [D32](01-decisions.md#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock);
the numbers are here.

| | estimated LUT4 | measured |
|---|---|---|
| VRAM + arbiter + indirect port | 130 | 263 |
| fetch engine, shifter, palette, registers | 1051 | 1386 |
| blitter | ~350 | 1306 |
| sprite engine | 450 | 402 |
| pixel port | *in the blitter's line* | 199 |

**Every estimate for this subsystem came in at about half**, and the
first row was recorded when it happened and the rest carried forward
anyway. That is the process mistake worth naming: an estimate already
proven 2× low is evidence about the estimator, not about the one block.

With the blitter in, the machine did not fit the part at all — 5438
logic cells against 5280, `nextpnr` failing rather than warning. The
blitter came out; the sprite engine stayed, because [§5.3](04-system.md)
already argues a tile map redraws nothing and needs no accelerator. What
survived of it is `PIX_X`/`PIX_Y`/`PIX_DATA`, at 199 LUT4 and one of the
eight DSP blocks the design had never used — the address arithmetic,
which is the part an 8-bit CPU is actually bad at.

**And the clock.** The part has one PLL and its reference is the pad the
12 MHz arrives on, so the system clock has to be a division of 25.125.
Half of it does not close: 11.0–11.6 MHz across six placer seeds against
the 12.5625 needed. A third of it does, with margin. **8.375 MHz.**

```
ICESTORM_LC       5076 / 5280   96 %
ICESTORM_RAM        29 / 30     96 %
ICESTORM_SPRAM       4 / 4     100 %
ICESTORM_DSP         1 / 8      12 %
sclk closes at 10.81 MHz against a constraint of 8.375
```

- [ ] ~~Blitter: `FILL_RECT`, `COPY_RECT`, `COPY_RECT_TRANSPARENT`,
      clipping, logic ops~~ — **cut, D34**. The `PIX_*` port is built
- [ ] ~~`DRAW_LINE`~~ — **cut first**, under this section's own decision
      table. About six cycles a pixel in software through `PIX_DATA`
- [x] Sprite engine: 32 descriptors in EBR, 8 per scanline, 8×8 and
      16×16, flip, priority, and the overrun flag —
      [`cool8_sprite.v`](../rtl/soc/cool8_sprite.v), **402 LUT4 and 7 EBR**

Two things in it are not what [§5.6](04-system.md) originally described,
and both are arithmetic rather than preference. **The descriptor is
packed so the per-line scan reads one 16-bit word instead of four
bytes** — a scanline is 266 system clocks and 32 descriptors at four
reads each would be 128 of them before a pattern was fetched. And
**sprites render in reverse descriptor order**, because first-writer-
wins needs the line buffer read back and an iCE40 block RAM's read port
belongs to the raster; last-writer-wins backwards gives the same picture
with no reads at all.

**Nothing clears the sprite line buffer** — clearing 640 entries would
take 640 of the 266 clocks a line has — so **every sprite is rendered
for two lines past its bottom edge, writing zeros** over its own span.
Two lines because the banks alternate and both have to be wiped, and
*before* the real sprites of the line, or a low-numbered sprite's clear
lands on a high-numbered sprite's pixels.

The generation bit that was there first — bit 1 of the line number,
carried in every entry — is not sufficient on its own, and the testbench
is what said so: it separates a line from the one two lines earlier and
not from the one four lines earlier, so every sprite's last row came
back four lines underneath it in a band that repeated down the screen.

- [ ] Boot ROM prints a message

### Working without the display

None of the missing hardware blocks the work, which is worth stating
because it looks like it should.

**The keyboard was never the problem.** Keystrokes typed at a terminal
go down the USB serial that already exists, through the sniffer, into
`UART_DATA`. PS/2 is a *second* input path, added when the level shifter
is built. M6 built both, and the monitor reads them as peers — so the
level shifter is a convenience now rather than a dependency, and
`sim/test_monitor.py` drives the PS/2 side from a device model rather
than waiting for one.

**The video engine is verified by looking at it.** `sim/test_video.py`
renders a frame to `build/frame.png` — a real 640×480 image with a
one-pixel border and a 45° diagonal in it, so a raster that is off by one
anywhere shears or shifts visibly rather than merely failing a count.
That image stays useful after the PMOD arrives, as the thing the
hardware has to match.

**The screen already exists as memory.** Mode 0 is 4800 bytes and a bus
grant is architecturally invisible, so
[`tools/cool8screen.py`](../tools/cool8screen.py) reads the framebuffer
out from under a running program and draws it in a terminal, at about
two frames a second over 115200. It is the same memory the video engine
will read, decoded the same way — which makes it the thing that has to
agree with the hardware, written first. Verified against the board:
a screen written at `$8000`, read back, and `$80A4` holding
`43 0F 4F 0F 4F 0F 4C 0F 38 0F` — "COOL8" in white on black.

It paints **without halting**, deliberately. `Loader.write` halts first
because loading a program over a running one has to; painting a
framebuffer does not, and freezing the CPU to look at its output would
defeat the only reason the tool exists. Getting that wrong is how the
`RESET`-does-not-release-`HALT` behaviour in
[07-loader.md §2](07-loader.md#06-reset) got found.

**And a monitor is cheap when it is wanted.** The PMOD-VGA is three
resistor ladders and a connector; a breadboard, nine resistors and a cut
VGA cable is a couple of euro, and one resistor per channel gives eight
colours and proves the timing.

**A real monitor showing real text is the moment this becomes a
computer.**

## M6 — Keyboard and monitor program ✅

- [x] PS/2 receiver, FIFO, transmit path —
      [`rtl/soc/cool8_ps2.v`](../rtl/soc/cool8_ps2.v), **160 LUT4,
      91 flip-flops and 1 EBR**
- [x] SPI flash reader, read-only in hardware (`$FE88`) —
      [`rtl/soc/cool8_flash.v`](../rtl/soc/cool8_flash.v), **180 LUT4
      and 79 flip-flops**
- [x] Monitor in ROM: memory examine/modify, disassemble, go, load a
      program from flash — [`sw/monitor.asm`](../sw/monitor.asm) and
      [`sw/disasm.asm`](../sw/disasm.asm)
- [x] Scancode → ASCII translation in software
- [ ] Level shifter built — hardware, and the last thing between this
      and a keyboard on the desk. [05-board.md §4.1](05-board.md)

```bash
python sim/test_ps2.py               # the keyboard port, against a keyboard
python sim/test_flash.py             # the SPI reader, against a flash
python sim/test_monitor.py           # the gate
python sim/mutate.py                 # both blocks, broken on purpose
```

**Gate: type at the machine and it answers — and it does.**
`sim/test_monitor.py` boots the whole SoC cold on the parameters the
bitstream carries, with SPRAM undefined and nothing poked, and then
talks to it: over the serial line, and by clocking Set 2 scancodes in on
an open-drain PS/2 wire. Every phase names a string the monitor has to
produce.

A keystroke in that test takes the path it takes on the bench — eleven
bits on the wire, the parity check, the FIFO, the CPU's own load through
the I/O page, the translation table in ROM, the echo, the shared
transmitter. Pressing `A` gives `a`, and `A` with shift held, which
covers make and break and the prefix handling as well as the table.

### The two blocks, and what testing them found

**Both are mutation-tested**, as every block since M1 has been, and this
milestone has a harness for it rather than a procedure:
[`sim/mutate.py`](../sim/mutate.py). **41 of 42 deliberate bugs are
caught** — data sampled on the wrong clock edge, no line filtering,
parity accepted when even, the watchdog disabled, a full FIFO written
anyway, the read register never settled, transmit parity even, the most
significant bit sent first, no inhibit before the request to send, a
missing acknowledge ignored, a device that never answers waited on for
ever; and on the flash, a different opcode, the address byte-swapped, a
seven-bit shift, MISO never sampled, the address not advancing, chip
select not held, reads that never stall.

The one survivor is **equivalent, not missed**, and the harness carries
the argument: `rx_n` is cleared on both paths out of a transmission
anyway, once by `T_ACK` and once by the watchdog. `mutate.py` fails if a
mutation listed as equivalent is ever caught, so the argument cannot go
stale quietly.

Four of the mutations survived the first run and every one was a real
gap. **Three of them share a shape**: the test polled a status bit
before reading, and the poll is what hid the bug. The sharpest was the
FIFO's read register — the block RAM answers a cycle late, and *every*
test in the file checked `KBD_STAT` first, which is exactly the wait
that makes the staleness invisible. The phase that catches it now takes
one blind read and sweeps it across the window the byte arrives in,
asserting not what the read returned but that **the byte was neither
lost nor duplicated**. A stale read is the failure that matters because
it pops as well as lies.

**The flash's device model found a real bug before any mutation did.**
It decodes the opcode off the wire and only knows `$03` — which is how
[D16](01-decisions.md#d16--flash-access-is-read-only-in-hardware)'s
promise gets checked rather than asserted — and it refused an `$EA`.
Closing the stream shared a cycle with a shift in progress, and the
shifter's assignments to `sr`, `n` and `spi_sck` sit further down the
same `always` block, so half the close was overwritten and the next open
built its command out of the wreckage. Closing is its own branch now.

### What it cost, and what paid for it

**340 LUT4 for the two blocks, against 403 logic cells free after M5.**
That would not have fitted. The PS/2 receiver was the only one of the
two this project had ever put a number against — ~120 LUT4 in
[00-goals.md](00-goals.md) — and it came in at 160, which is 1.3× rather
than the 2× the video subsystem managed three times. The flash reader
had no estimate at all.

What paid for the gap was the boot ROM's own waste, spent the only way
it can be:
[D37](01-decisions.md#d37--the-uart-receive-fifo-moves-into-block-ram-reversing-m4s-call)
moved the UART's sixteen-byte receive FIFO out of flip-flops and into a
block RAM, which is **109 LUT4 and 123 flip-flops back for one EBR** —
reversing a decision M4 made correctly on premises that have both since
inverted.

```
ICESTORM_LC       5076 / 5280   96 %
ICESTORM_RAM        29 / 30     96 %
ICESTORM_SPRAM       4 / 4     100 %
sclk closes at 10.81 MHz against a constraint of 8.375
```

*(That is the M6 figure. M7 changed it — see below.)*

**204 logic cells and one block RAM are left**, and M7's audio was
budgeted at ~250 LUT4 by a process this project has now watched come in
at twice its estimate four times. That is the next thing the gate will
be about, and the levers are known: the boot ROM is still holding 3028
bytes in eight EBR, the sprite engine's descriptor count is a
parameter, and `PIX_*` is 199 LUT4 that
[D34](01-decisions.md#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter)
already argued is optional.

## M7 — Sound, storage, and the board ✅

- [x] Eight voices, squares and noise, sigma-delta output —
      [`rtl/soc/cool8_snd.v`](../rtl/soc/cool8_snd.v), **141 LUT4, 131
      flip-flops and 1 EBR**
      ([D41](01-decisions.md#d41--the-sound-engine-is-one-datapath-walked-eight-times-not-four-dividers))
- [x] The machine can write its own flash, above a hardware floor at
      `$100000` ([D42](01-decisions.md#d42--the-machine-can-write-its-own-flash-above-a-hardware-floor))
- [x] The `SW[0]` break button, with the pull-up the board turned out to
      need ([D40](01-decisions.md#d40--the-hardware-loader-is-a-build-option-and-it-is-off))
- [x] Eight 16x16 sprites on a line, which had never actually worked
      ([D43](01-decisions.md#d43--the-sprite-engine-renders-eight-16x16-sprites-and-did-not-before))
- [ ] The timer at `$FE60`, still the last unbuilt register block
- [ ] A demo that draws something and plays something
- [ ] RC low-pass and coupling capacitor on `P1_3`, and the VGA and PS/2
      connectors — hardware, and the last thing between this and a
      machine on a desk

### 🚩 The fit gate, and how it was answered

**It did not fit.** The sound engine took the design to 5320 logic cells
against 5280, and then to 5301 after the obvious trims — the first time
in the project `nextpnr` refused outright.

What paid for it was **the hardware loader, 376 cells**
([D40](01-decisions.md#d40--the-hardware-loader-is-a-build-option-and-it-is-off)),
which is a build option now rather than a fixture. Its justification had
expired: it existed because at M4 there was no ROM, no monitor and no
flash reader, and all three exist.

The other lever the M6 list named — sprite descriptors 32 → 16 — **saves
nothing**, measured at +4 LUT4. The cost is the per-line machinery and
the line buffer, not the descriptor count. Sprites *per line* is the one
that pays, and it was not needed.

**Where it landed:**

```
ICESTORM_LC     5022 / 5280   95 %
ICESTORM_RAM      28 / 30     93 %
ICESTORM_SPRAM     4 / 4     100 %
ICESTORM_DSP       1 / 8      12 %
sclk closes at 11.20 MHz against a constraint of 8.375
```

258 cells and two block RAMs left.

### The machine ran

**It boots on real silicon.** Power-on reset, PLL lock, 60 KB of SPRAM
cleared, the monitor answering on the serial console: `?` lists the
commands and `D F000` returns `2F 60 00 02`, the `LDW X,#$0200` the reset
vector points at.

Everything simulation predicted was right, and the board still found one
thing no testbench could have: `SW[0]` had no pull-up, floated,
oscillated, and produced a machine taking NMIs continuously. Every
simulation of a floating pin is a decision about what to drive it with.

Not yet exercised on hardware: video (no VGA PMOD), the keyboard (no
level shifter), sound (no RC filter), and the flash write path — which
should be tried at a high address with the bitstream backed up.

## M8 — TinyTapeout — **shelved**

**The target is the FPGA.** M8 is out of the plan and the reasoning is
[D33](01-decisions.md#d33--the-asic-path-is-shelved-the-target-is-the-fpga):
what shelving it buys is permission rather than direction — cycle counts
may change without a tapeout implication, and the bus protocol is fair
game — and the thing it was invoked for, the 37-level critical path in
D32, is logic depth that would be the same on either target.

**The discipline stays where it is free.** `rtl/core` remains
Verilog-2001 with no vendor primitives, no inferred RAM and no clock
gating, and `sim/synth.py` keeps checking it. A core that is still
portable is a milestone that can be un-shelved; a core casually
sprinkled with `SB_` primitives is a rewrite.

**The risk this milestone carried is already retired.** M3 hardened the
core through TinyTapeout's own LibreLane flow on sky130: 20,960 µm² at
61.2 % utilisation in two tiles, clean DRC, LVS and antenna, closing at
50 MHz at every PVT corner. `rtl/pads/tt_um_cool8.v` and its
instruction-level verification against latch and SRAM models exist and
pass. What was never done is the bus-*grant* load path with an external
agent, and the physical test board.

## Deliberately not scheduled

- A second background layer, 16 sprites per scanline, sprite scaling
  and collision — the register and descriptor bits are reserved and
  [04-system.md §5.11](04-system.md) prices each one
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
