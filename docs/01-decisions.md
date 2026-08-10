# 01 — Decision log

Every architectural call, with the reasoning. Where a decision was
close, the runner-up is recorded so it can be revisited without
re-deriving the argument.

---

## D1 — Not a clone of anything

**Decision:** clean-sheet ISA.

**Why:** the two candidate ancestors both carry baggage we would gain
nothing from. The 6502's asymmetric X/Y registers, fixed 256-byte stack,
page-boundary quirks and missing addressing-mode combinations are
artefacts of a 1975 transistor budget we do not have. The Z80's prefix
bytes, shadow registers, dual-purpose P/V flag and 8080 compatibility
encodings only pay for themselves if you want to run 8080 software, and
we don't.

What we take from each:

| From the 6502 | From the Z80 |
|---|---|
| Implementation discipline — small, compact control | Real pointer registers |
| Memory-mapped I/O | Full 16-bit stack pointer |
| Short relative branches | Register-indirect + displacement addressing |
| Explicit carry-based multi-byte arithmetic | Rich condition-code set |
| Code density as a first-class concern | Multiple simultaneous pointers |

---

## D2 — Four general registers, orthogonal

**Decision:** R0–R3, 8-bit, fully interchangeable. Every ALU operation
works on every register as both source and destination.

**Why:** a 2-bit register field is what makes one-byte two-operand
instructions possible. `1 ooo dd ss` gives eight ALU operations across
all sixteen register combinations in a single byte. Eight registers
would need 3-bit fields, which pushes reg-reg ALU to two bytes or forces
the Z80's accumulator-centric asymmetry.

Four orthogonal registers is also the smallest decoder of the options
considered, which matters for C1 (TinyTapeout area).

**Runner-up:** eight registers with Z80-style opcode quadrants
(`01 ddd sss` for moves, `10 ooo sss` for accumulator ALU). Denser for
some code, but accumulator-centric and therefore not actually
orthogonal, and a bigger decoder.

**Known cost:** four registers is tight. Register pressure is real, and
the mitigation is cheap SP-relative and displacement addressing rather
than more registers. Revisit only if real code proves it unworkable.

---

## D3 — X and Y are separate 16-bit registers, not aliases of R0–R3

**Decision:** two dedicated 16-bit pointer registers, X and Y, outside
the general register file. Their halves (XL, XH, YL, YH) are reachable
through page-2 move instructions.

**Why:** the original plan was pairs — P0 = R1:R0, P1 = R3:R2. That
fails on the most basic loop in the machine. A byte copy needs a source
pointer, a destination pointer *and* a data register. With aliased
pairs, two pointers consume all four general registers and there is
nothing left to hold the byte:

```asm
loop:   LD   R0,[P0]       ; R0 IS the low half of P0. Broken.
```

Separate X/Y costs 32 flip-flops and fixes the architecture. With four
free general registers plus two pointers, the copy loop leaves R2 and R3
untouched.

**Side benefit:** the pointer-select field in load/store encodings is
1 bit instead of 2, which is where the opcode space for control-flow
instructions came from.

---

## D4 — Variable-length instructions, 1 to 4 bytes, one escape byte

**Decision:** byte-granular instructions. One-byte for register
operations and indirect load/store, two bytes for immediates,
displacements and branches, three for absolute addresses. Opcode `$2F`
is a single-level escape into a second 256-entry opcode page.

**Why not fixed 16-bit:** halves your code density on an 8-bit machine
with only 64 KB of address space, and doubles the width of the
instruction fetch path.

**Why an escape byte is not a Z80 prefix:** the Z80's problem was
*chained* prefixes with interleaved displacement bytes and stateful
decode (`DD CB d op`). `$2F` is one level, never chains, and the
instruction length is fully determined by the second byte. It is a
decode tree, not a prefix machine.

**Why an escape at all:** the opcode budget genuinely does not close
without one. Eight orthogonal reg-reg ALU operations cost 128 opcodes —
half the space. The remaining 128 has to cover immediates, four
addressing modes, sixteen branch conditions, calls, returns, stack and
16-bit pointer operations. Everything rare (XOR, right shifts, negate,
16-bit loads, register-indexed addressing, bit operations) goes behind
`$2F` where the extra byte costs nothing because those instructions were
never going to be one byte anyway.

---

## D5 — The eight ALU operations are MOV ADD ADC SUB SBC AND OR CMP

**Decision:** the same eight, with the same `ooo` encoding, in both the
register-register group and the immediate group.

**Why these eight:** ADD and ADC both present (paying a byte for `CLC`
before every single-byte add, 6502-style, is a bad trade). CMP in,
because comparing against a constant is one of the most frequent things
any program does and it must not write back.

**Why XOR is not in the set:** it was the weakest of the nine
candidates. XOR's common uses are covered — `SUB Rd,Rd` clears a
register in one byte, and `NOT Rd` exists on page 2. True XOR
(checksums, sprite masking) lives on page 2 at two bytes.

**Consequence — free shift and clear idioms:**

| Idiom | Meaning | Bytes |
|---|---|---|
| `ADD Rd,Rd` | shift left, C ← bit 7 | 1 |
| `ADC Rd,Rd` | rotate left through carry | 1 |
| `SUB Rd,Rd` | clear to 0, C=1, Z=1 | 1 |
| `SBC Rd,Rd` | $00 if C=1, $FF if C=0 (sign-extend the carry) | 1 |
| `OR Rd,Rd` | test, set N and Z | 1 |

Left shifts and rotates are therefore one byte and cost no opcode space
at all. Only the right shifts (`SHR`, `SAR`, `ROR`) need page 2.

---

## D6 — No zero page, no direct page register

**Decision:** dropped. Globals are reached with 3-byte absolute
addressing or through X/Y.

**Why:** an 8-bit direct-page register was drafted and cut. It would
have saved a byte on global and I/O accesses, but it cost eight primary
opcodes at exactly the point where control flow had nowhere to live, and
it adds architectural state that has to be saved on context switch. The
6502's zero page exists because a 1975 register file was expensive;
ours is not.

**Revisit if:** profiling real code shows absolute addressing dominating.
The escape page has room.

---

## D7 — Memory-mapped I/O, 256-byte page at $FF00

**Decision:** memory-mapped. One 256-byte I/O page at `$FF00–$FFFF`,
which also holds the reset and interrupt vectors.

**Why:** the two source conversations disagreed on this. One argued for
memory-mapped I/O with a 4 KB region at `$F000`; the other argued for a
separate I/O address space with `IN`/`OUT` instructions specifically to
preserve the full 64 KB of RAM.

A 256-byte page settles it. You lose 0.4% of the address space instead
of 6%, so the "preserve 64 KB" argument evaporates. And memory-mapped
I/O means no extra bus signal, no extra instruction pair, no second
address space for a compiler to model, and — importantly for C1 — no
extra pin on a 24-pin TinyTapeout budget.

**Consequence:** peripheral registers must tolerate being read. Any
register with a read side effect must be documented, and read-modify-
write instruction sequences on I/O need care.

---

## D8 — Sixteen branch conditions, ARM-style

**Decision:** `0111 cccc` + signed 8-bit displacement, sixteen
conditions including signed and unsigned comparisons.

**Why:** sixteen conditions cost sixteen opcodes and a small
combinational block, and they are the difference between a compiler
emitting one instruction for `if (a < b)` and emitting three. The 6502
gives you eight and everyone worked around it; we can afford not to.
Signed `GE/LT/GT/LE` need `N` and `V` compared, which is two gates.

---

## D9 — Carry means "no borrow" on subtract

**Decision:** 6502/ARM convention. After `SUB`/`CMP`, `C = 1` means no
borrow occurred, i.e. the unsigned result did not go negative. `SBC`
computes `Rd - Rs - (1 - C)`.

**Why:** it has to be written down somewhere, unambiguously, before any
RTL or assembler exists. Both conventions are in the wild and getting it
wrong halfway through costs a rewrite of the assembler, the emulator and
every test. `BCS` therefore reads as "branch if unsigned greater or
equal", which is the intuitive direction.

---

## D10 — Multiplexed external bus, three-phase

**Decision:** the core presents a simple synchronous memory interface
internally. A thin wrapper multiplexes it onto 8 bidirectional pins in
three phases: address low, address high, data.

**Why:** forced by C1. TinyTapeout gives 8 in / 8 out / 8 bidir. A
16-bit address plus 8-bit data plus control does not fit any two-phase
scheme without giving up address bits. Three phases keeps the full 64 KB
and leaves the entire 8-bit output port free for control strobes and the
entire input port free for interrupts and wait states.

The cost is three bus cycles per memory access on the ASIC. On a
TinyTapeout part running at a few MHz against a 55 ns SRAM, that is not
the limiting factor.

On the FPGA the wrapper is bypassed and the core talks to the SPRAM
controller directly, one access per cycle. **Same core RTL both ways.**

---

## D11 — 64 KB unified RAM, video shares it

> **Superseded in part by [D28](#d28--video-memory-is-split-the-text-map-in-main-ram-everything-else-in-dedicated-vram).**
> The bandwidth argument below still holds and is still the reason text
> mode reads main RAM. What changed is that graphics modes do not, and
> the two spare SPRAM blocks became video RAM rather than a banked
> window.

**Decision:** two SPRAM blocks form one flat 64 KB address space. The
CPU and the video engine both read it through an arbiter with video
priority.

**Why:** the arithmetic says contention is a non-issue. At 320×200 and
4 bits per pixel, doubled to 640×400, the logical pixel rate is
12.56 MHz. SPRAM is 16 bits wide, so one access yields four pixels —
3.14 M accesses/sec out of the ~25 M available. **Video steals one cycle
in eight.**

That kills the need for banking, separate video memory, a display-list
processor, or any arbiter more complicated than round-robin. It is also
how every real 8-bit home computer worked.

The other two SPRAM blocks (64 KB) stay unmapped in v1, reserved for a
banked window for tiles, sprite graphics and sample data later.

---

## D12 — Audio: SN76489-style, not SID-style

> **The conclusion stands; the implementation was replaced by
> [D41](#d41--the-sound-engine-is-one-datapath-walked-eight-times-not-four-dividers).**
> Squares and an LFSR rather than SID-style filters is still right, and
> for the reason below. Four parallel dividers is not: shared across one
> time-multiplexed datapath, a phase accumulator is smaller *and* eight
> voices cost less than the four budgeted here.

**Decision:** three square-wave tone channels plus one noise channel,
each with a frequency divider and 4-bit attenuation. Digital mix, 1-bit
sigma-delta output.

**Why:** it is the ASIC-portable choice. A SID-style analog-character
voice means resonant filters, which means multipliers — cheap on the
UP5K (8 DSP blocks sitting idle) and expensive on silicon. Dividers and
an LFSR are a few hundred gates.

A divider is used rather than a phase accumulator because it is smaller
and it is what the real chip did; a 12-bit divider gives adequate range
down into the bass. Phase accumulators can come later if frequency
resolution proves annoying.

---

## D13 — Clock: fast, with a programmable brake

**Decision:** run the whole SoC from the ~25.125 MHz pixel clock. Add a
CPU clock-enable divider in an I/O register so the effective CPU speed
can be dialled from full rate down to roughly 1 MHz.

**Why:** "don't care" was the answer to how fast it should feel, so:
take the speed the FPGA gives you for free, and make the retro feel a
runtime setting rather than a design decision. Timing-sensitive demo
code can pick a slow, stable rate; everything else runs fast.

A single clock domain for the entire SoC also avoids every clock-domain-
crossing bug in the book.

---

## D14 — Post-increment addressing dropped from v1

**Decision:** no `LD Rd,[X+]`. It was drafted, costed and cut.

**Why:** it looked essential and isn't. Because `INCW X` is a one-byte
primary opcode, the two sequences cost the same:

```
LD R1,[X+]                   ; hypothetical: 1 byte
LD R1,[X] / INCW X           ; actual:       2 bytes, 1 byte each
```

Sixteen opcodes and an extra register writeback path, for a wash. It
lives on page 2 as a two-byte form for when the assembler wants it.

---

## D15 — The loader is hardware, not a ROM monitor

> **Revisited at M7 by [D40](#d40--the-hardware-loader-is-a-build-option-and-it-is-off):**
> the argument below was correct and its premises have expired. It is a
> build option now, off by default, and the 376 logic cells bought the
> flash write path.

**Decision:** program loading is done by a state machine in `rtl/soc/`
that owns the bus directly, not by an XMODEM receiver running on the
CPU.

**Why:** the obvious design is a monitor in the boot ROM that receives
over serial. It has a chicken-and-egg problem. The boot ROM lives in
EBR, so it is part of the bitstream — changing anything about how
loading works means a full `yosys`/`nextpnr` rebuild and a re-flash.
During M4–M6 there is no working software at all, so every software bug
becomes a bitstream rebuild.

A hardware loader costs roughly 60 LUTs and turns software iteration
into `cat prog.bin > COM3` with no rebuild. It also works when the CPU
is wedged, when the ROM is broken, and before any monitor exists — which
is precisely when you need it most.

The memory read-back it gives for free is the debugging tool that
matters most at M4, and because a bus grant preserves all architectural
state, it doubles as a non-intrusive debugger: halt, dump 64 KB, resume,
and the running program cannot tell.

**A ROM monitor is still worth having** at M6, for interactive use on
the machine's own screen. It just is not the bootstrap path.

---

## D16 — Flash access is read-only in hardware

> **The upgrade path below was built at M7 —
> [D42](#d42--the-machine-can-write-its-own-flash-above-a-hardware-floor).**
> The floor is exactly the `$100000` this section names, and it is
> checked in gates before an opcode is chosen.

**Decision:** the FPGA's SPI master issues flash opcode `$03` (READ) and
has no write-enable, page-program or erase path in the gates at all.
Writing the flash is a host-side operation via `icesprog`.

**Why:** the 8 MB flash the machine uses as storage is the same chip the
FPGA configures itself from, with the bitstream at offset 0. A software
bug that reached a page-program or sector-erase opcode would brick the
board until it was re-flashed by other means.

Making it physically impossible costs nothing — we want reads anyway,
and *not* building the write path is strictly less logic.

**Upgrade path, when saving from the machine becomes worth having:**
allow writes, but gate them on a hardware comparison of the address
against a fixed floor (`$100000`), so the bottom 1 MB is unreachable by
construction. That keeps the guarantee while allowing a real filesystem.

**Related footgun, worth writing down:** `icesprog -e` is a whole-chip
erase, not a sector erase. It destroys the bitstream. Sector writes at an
offset do not need it, so there is never a reason to run it.

---

## D17 — Bus request belongs in the core

**Decision:** `busrq` / `busak` are part of `cool8_core`, not SoC glue.

**Why:** it is the only way software gets into a COOL8 machine on
*either* target, and the ASIC has no other option at all. TinyTapeout
gives you no UART, no FPGA fabric and no flash controller — just a chip,
two latches and an SRAM that comes up as garbage. Something external has
to write that SRAM before the CPU can run, and the only path is through
the chip's own pins.

Adding it to the core is nearly free: the grant point is the same
instruction boundary where interrupts are already sampled, and no
instruction is restartable-in-the-middle, so there is no partial state
to worry about.

It costs two TinyTapeout pins and roughly 20 gates. The remaining
problem — that the external agent also needs to strobe the address
latches, which are CPU outputs — is solved **on the board** with two
74HC packages, not in the chip. See
[03-microarchitecture.md §5.3](03-microarchitecture.md#53-merging-a-granted-bus).

**A rejected first attempt is worth recording.** The original design
multiplexed the strobes inside the chip, driving them from four spare
input pins whenever `BUSAK` was high. It worked and it made the board
marginally simpler, but it spent four irreplaceable die pins and four
muxes to save two logic packages on a board that already had three chips
on it. That is the wrong direction: board parts are free and can be
changed with a soldering iron; pins after tapeout cannot be changed at
all. The TinyTapeout budget now stands at 20 of 24 used, and the four
spare inputs are deliberate headroom.

**The alternative to bus request entirely was a parallel boot EEPROM**
on the bus at the reset vector, holding a serial loader. Period-
authentic and it costs nothing, but it gives no debugger and changing
software means re-burning a chip. Bus request gives both. The EEPROM is
kept anyway as a **fallback path** on the test board — a socket and a
chip select are free at design time, and if `BUSRQ` has a bug in
silicon there is no patching it.

---

## D18 — 8x8 multiply, landing in X

**Decision:** `MUL Rd,Rs` on page 2 at `$F0–$FF`, computing the unsigned
16-bit product into **X**. Multi-cycle shift-add, ~12 cycles.

**Why have it at all:** software multiply is roughly 40 cycles and
graphics code does it constantly — row addressing, scaling, sprite
positioning. A shift-add sequencer that reuses the existing 8-bit ALU is
about 150 gates, which is a good trade even on a die-area-constrained
design.

**Why the result goes to X rather than a register pair:** there are no
general-purpose 16-bit pairs in this architecture, and multiply is
overwhelmingly used to compute an address. Landing the product somewhere
you can immediately dereference is what the code actually wants.
`MOVW Y,X` moves it if you needed the other pointer.

**Why no divide:** restoring division is meaningfully more logic than
multiply and far rarer in practice. Not worth the area.

**Implementation note:** `X` doubles as the 16-bit accumulator and
`TMP` as the shifted multiplier, so `MUL` adds **no architectural
state** — only a counter and some control.

---

## D19 — Area overruns are paid for in tiles, not ISA cuts

**Decision:** if OpenLane says the core is larger than the ~2750-gate
estimate, buy more TinyTapeout tiles rather than cutting the
architecture.

**Why:** the ISA is the thing this project is actually about, and it has
had months of design attention. Tiles are money. Cutting page 2 or the
addressing modes to save a tile would trade the deliverable for a small
cost saving, and it would make the ASIC and FPGA cores diverge, which
breaks [C2](00-goals.md#c2--the-core-and-the-machine-are-separate).

**If the tile count does become absurd**, the cut order is: page 2
extras first (register-indexed addressing, bit operations,
auto-increment), then `MUL`, then `[abs16]`. The orthogonal ALU, the
sixteen condition codes and `[SP+u8]` are not on the table — they are
what makes it a decent compiler target.

**This is a policy, not a prediction.** The estimate is a hand-count and
the roadmap says to run OpenLane at M3, years before it matters, exactly
so this decision never has to be made in a hurry.

---

## D20 — `ADDW X|Y,#imm16`, added after the M2 gate

**Decision:** two of the free page-2 encodings (`$2C`, `$2D`) become
`ADDW X,#imm16` and `ADDW Y,#imm16`.

**Why:** writing the M2 corpus found the gap. The ISA had `ADDW X,Rd`
(8-bit, through a register) but no way to add a 16-bit constant to a
pointer, so doing it took six instructions through `XL`/`XH` — or three
if you got lucky and the constant was page-aligned. `pixel_addr` does it
on every single call, and every graphics routine goes through
`pixel_addr`.

Cost: two encodings of the twenty-two that were free, and one wider
input mux on the AGU, which already does 16-bit adds. `pixel_addr` lost
two instructions and two bytes; the `addx16` macro that had been
papering over the gap collapsed to a one-liner.

**This is what the gate was for.** The gap was invisible while the ISA
was only a document. It took about forty lines of real graphics code to
make it obvious.

---

## D21 — Four general registers is enough. Confirmed, question closed.

**Decision:** the register model stands. Four 8-bit general registers,
two 16-bit pointers. The M2 gate question is closed.

**Evidence.** 26 hand-written routines, 277 instructions, 430 bytes,
across a standard library, graphics inner loops and formatting code:

| Corpus | Routines | Instructions | Spill instructions | Rate |
|---|---|---|---|---|
| `lib.asm` — library and 16-bit maths | 17 | 175 | 4 | 2.3 % |
| `gfx.asm` — graphics inner loops | 9 | 102 | 2 | 2.0 % |
| **Hand-written total** | **26** | **277** | **6** | **2.2 %** |
| `frames.asm` — naive compiler output | 8 | 86 | 33 | 38.4 % |

**23 of 26 hand-written routines never touch the stack.** The
`frames.asm` figure is high by design — it is deliberately unoptimised
compiler-style codegen that spills everything, and it is there to test
that `[SP+u8]` works, not to measure hand-written pressure.

`blit8_or` is the proof point: source pointer, destination pointer, row
counter, stride, sprite byte and background byte all live at once. It
uses all four general registers and both pointers, with nothing spare
and nothing spilled. Four is exactly enough.

**The interesting part — the constraint is pointers, not registers.**
Of the six spill instructions in hand-written code, **four are pointer
pressure and only two are general-register pressure**:

| Routine | Spills | Cause |
|---|---|---|
| `mul16` | 2 | `MUL` writes to `X`, so a caller's pointer must be saved across it — a consequence of [D18](#d18--8x8-multiply-landing-in-x), not of the register count |
| `blit8_mask` | 2 | Wants a *third pointer*; pushes `Y` to reach a mask pointer |
| `sort8` | 2 | Six live values in four registers. The only genuine GPR spill in the corpus. |

So the question the gate was designed to answer turned out to have a
different answer than the question assumed. See D22.

---

## D22 — No third pointer register

**Decision:** two pointer registers, X and Y. No Z.

**Why not**, given that D21 shows pointer pressure is the real
constraint: the primary page's pointer-select field is **one bit wide**.
There is nowhere to put a third pointer without either making `[Z]` a
page-2-only, two-byte, second-class addressing mode, or widening the
field to two bits — which costs sixteen more primary opcodes in the
load/store groups, and there are none spare.

Measured benefit: four instructions across twenty-six routines. That is
not worth rebuilding the primary opcode page.

**Recorded so it is not re-derived:** if a future revision ever does get
more primary opcode space, a third pointer is the first thing to spend
it on — ahead of more general registers, which the evidence says are
not the bottleneck.

---

## D23 — No memory address register

**Decided at M3, when the RTL was written.**

[03-microarchitecture.md](03-microarchitecture.md) originally specified
a `MAR` and a dedicated `ADDR` state that loaded it. The RTL has
neither: `mem_addr` is driven straight out of the AGU through a 2:1 mux
that selects either the adder's A input (fetch at `PC`, pop at `SP`,
post-increment at `X`) or its sum (displaced addressing, push at `SP-1`,
pre-decrement at `X-1`).

It buys two things:

- **16 flip-flops**, about 12 % of the machine's state.
- **A cycle off every memory access with a computed address.**
  `LD Rd,[X+d8]` is 3 clocks instead of 5, `RET` is 3 instead of 5,
  `CALL abs16` is 6 instead of 7. Section 8 of the ISA now carries the
  measured numbers.

The cost is a longer combinational path — register file or pointer, AGU
adder, address pins — instead of a clock-to-Q out of a flop. At the
FPGA's 25 MHz and the ASIC's target of around 10 MHz that path has an
enormous amount of slack, and on the ASIC the bus multiplexer registers
the address on its way out anyway.

`IR2` went the same way. After a `$2F` escape the primary opcode is
known, so the second byte overwrites `IR` and one `p2` bit records that
it did — 8 flip-flops for 1.

## D24 — `EI` and `DI` take effect immediately, no delay slot

**Decided at M3.** The first RTL sampled the `I` flag at an instruction
boundary *before* that instruction's own writeback. That is the 6502 and
Z80 behaviour, and it produces the familiar "`EI` delay slot": an
interrupt cannot be taken at the boundary immediately after the
instruction that enabled it.

It also produces the much less familiar consequence that an interrupt
**can** be taken immediately after `DI`, which makes `DI` unreliable as
a way of protecting a critical section — the one thing it is for.

The asymmetry is not worth having. The core now derives the
interrupt-enable value for the boundary check from the decode of the
retiring instruction, so `EI`, `DI` and `POP F` all take effect at their
own boundary. This costs one 3:1 mux on a single bit.

The reference emulator already behaved this way, which is how the
disagreement was found: the RTL and the emulator are checked against
each other after every instruction, and this is exactly the class of
question that comparison exists to settle.

`RETI` is unaffected either way — it restores `I` from the stack two
cycles before its boundary — so the guarantee of forward progress out of
a handler that the delay slot is usually justified by does not depend on
it here.

## D25 — `MOV Rd,<pp>` sets no flags

**Decided at M3**, having been open for about an hour.

The page-2 pointer-half moves ([02-isa.md §5.2](02-isa.md#52-pointer-half-register-access))
were not named in the normative flag table, and the reference emulator
was setting `Z` and `N` on the load direction while the store direction
set nothing. Nobody chose that; the table simply had a hole in it and
the emulator filled it one way.

They are `MOV`s. §1.2's first rule — *"`MOV` never touches flags; loads
do"* — applies, and the two directions are now symmetric.

The reasoning behind rule 1 is that `LD` then `BEQ` is the commonest
two-instruction sequence in 8-bit code and should not need a `TST`
between them. `MOV R0,XH` then `BEQ` is not that sequence: extracting a
pointer half is nearly always followed by arithmetic, which sets the
flags itself. Nothing is lost, and `MOV` keeps meaning one thing
everywhere.

The change was one line in the RTL, one in the emulator and one row of
the table, and the co-simulation confirmed all three agree.

## D26 — The system clock is 12 MHz; the pixel clock is decoupled

**Decided at M4, by measurement.**

[04-system.md §4.1](04-system.md) specified one clock domain for the
entire SoC at the 25.125 MHz VGA pixel clock, with the CPU on a clock
enable. The CPU does not close at 25.125 MHz on this part, and the
one-domain rule was the reason it had to.

**Measured on iCE40UP5K — core, two SPRAM and the PLL:** 1040 LCs, and
**16.90 MHz** maximum. The critical path is read data arriving from
SPRAM, through instruction decode, to the next address; the decode cone
alone is about 35 ns. Two attempts to break it elsewhere both failed,
and the failures are the useful part:

- Making `adv` a flip-flop enable rather than a term in the logic, so
  `mem_ready` leaves the cone: **17.24 MHz for 109 more LCs.** Not worth
  it, and it introduced a bug — `o_retire` pulsing during a stall —
  which the wait-state co-simulation caught immediately.
- Registering the address in the memory controller, the D23 path
  [03-microarchitecture.md §5.8](03-microarchitecture.md) flagged as the
  one to watch: **16.20 MHz.** The path did go away; nextpnr reported
  the next one.

The floor is the decode cone. Only splitting fetch and decode across two
cycles moves it, at one clock per instruction.

**None of that is necessary, because only the VGA pins need 25.175 MHz.**
A monitor syncs 640×480@60 from 800 pixel clocks per line at 31.469 kHz,
and that is not negotiable. The CPU, memory, UART, keyboard, timer and
audio have no opinion. Decoupling them is what block RAM is for:
`SB_RAM40_4K` has independent `RCLK` and `WCLK`, so a scanline buffer
written in the system domain and read in the pixel domain confines the
crossing to a single primitive — no arbiter crossing, no handshake,
nothing on the CPU side.

The bandwidth closes comfortably. A line is 31.8 µs, which at 12 MHz is
381 memory cycles; mode 4, the worst case, needs about 40 word accesses
per scanline, and text mode 0 needs 80 per sixteen. Both sit near the
12.5 % §5.3 already budgets.

**So the system runs at the board's raw 12 MHz** — no PLL in the CPU
path, 41 % margin against the measured 16.90 MHz, and real static timing
sign-off rather than an argument. The PLL is left entirely for the pixel
clock at M5.

Three consequences, stated plainly:

- **§4.1's one-clock-domain rule is withdrawn.** It was a simplification
  that read as a constraint, and it cost a milestone's worth of wrong
  turns before anyone asked out loud why anything needed 25 MHz.
- **Every constant derived from 25.125 MHz is now wrong** — the UART
  divider in §4.6, the audio reference and frequency table in §4.4, and
  the timer rate in §4.5. Arithmetic, not design. The UART divider is
  done (103, and it is the SoC's reset value); audio and the timer are
  not, and neither exists yet to be wrong in hardware.
- **The CPU speed-up is demoted, not abandoned.** At 12 MHz it buys
  throughput instead of unblocking a milestone, and it can be done with
  a working board to test against rather than only a timing report.

---

## D27 — The loader outranks the CPU on the shared transmitter

**Decided at M4, after simulation showed the other way round failing.**

There is one serial wire. The iCELink bridge presents a single USB CDC
port on two FPGA pins, and both the hardware loader's replies and a
running program's own output have to leave through it. A second UART on
spare pins would need a second cable and a second port on the host,
which is a worse machine for the sake of a simpler block.

So the transmitter is shared, and something has to lose. The first
arrangement gave the wire to the CPU whenever it had a byte queued and
showed the loader a busy line instead, on the reasoning that the loader
speaks rarely and can wait.

**It cannot.** `cool8_loader` only asserts `tx_start` on a cycle it has
already seen the wire idle on, and a program transmitting flat out never
leaves one: it refills its holding register in about fifteen clocks and a
byte takes a thousand to go out. The loader was starved completely — a
`PING` sent to a machine running a two-instruction transmit loop was
never answered. `cool8_soc_tb` found it on the first run.

That is not a corner case, it is the case that matters. **A host that
cannot interrupt a running program is a host reaching for the reset
button**, and not needing to is most of why the loader is hardware
rather than a ROM monitor ([D15](#d15--the-loader-is-hardware-not-a-rom-monitor)).

**So the loader has absolute priority.** It exports `tx_want`, high from
exactly the three states it ever transmits from, and the SoC holds the
CPU's byte back on every cycle the loader could commit on. Because the
loader commits one cycle after seeing the wire idle, and the CPU is
blocked on every such cycle, neither can interrupt the other and neither
loses a byte.

What it costs, stated plainly:

- **A program's output can be delayed**, by at most the byte the loader
  is sending, and only while a host is actually talking to the board.
- **It cannot be reordered or dropped.** The one-deep holding register
  keeps the byte it has already accepted; a write arriving with no room
  is the one that is lost, and `UART_STAT` bit 1 says so beforehand.
- The alternative — a deep transmit FIFO — does not help. The wire is
  still one wire, and buffering only moves the contention.

---

## D28 — Video memory is split: the text map in main RAM, everything else in dedicated VRAM

**Decided at M5, and it supersedes half of [D11](#d11--64-kb-unified-ram-video-shares-it).**

D11 put the framebuffer in main RAM and reasoned that display fetch is
cheap — 10.5 % of memory cycles in the worst mode, 1.3 % in text. That
arithmetic is still right and it is still why text mode reads main RAM.
What D11 could not weigh is a blitter, because there was not going to be
one.

Two things break when there is.

**A framebuffer in main RAM costs the CPU most of its address space.**
320×240 at 4 bpp is 38,400 bytes — 60 % of the 64 KB the CPU has.
256×240 at 8 bpp is 61,440 and leaves no room for the program that draws
into it. The machine that can do graphics becomes the machine that
cannot hold the code.

**And a blitter on a single-port memory is not an accelerator.**
`SB_SPRAM256KA` serves one 16-bit access per cycle. Every cycle the
blitter takes is a cycle the CPU does not get, so a blit runs fast in
exact proportion to how hard it stalls the CPU. That is the VIC-II
badline bargain, and avoiding it is most of the point of building this
now rather than reproducing 1982.

**Decision:** text modes read main RAM. Every other mode reads a
dedicated 64 KB VRAM built from the two spare SPRAM blocks. The blitter
and the sprite pattern fetch operate in VRAM only.

**The address space is selected by the mode decode, not by a register.**
There is deliberately no `VID_ADDRSPACE` bit: no combination of settings
can put a blitter destination in main RAM, so the failure mode does not
exist to be documented. It costs about ten LUT4 of combinational logic
where a register plus its illegal states would have cost more.

What it buys, stated as cycles the CPU loses to video:

| | CPU cycles stolen |
|---|---|
| Text mode display fetch | 1.3 % |
| Every graphics mode | 0 % |
| Blitter running flat out | 0 % |

So this is **strictly less** CPU stalling than D11 specified, not a
compromise against it.

**What it costs.** The CPU reaches VRAM through an indirect port rather
than with `ST`, which sounds worse than it is: writing a 4 bpp pixel by
address means computing `y·stride + x/2` and masking a nibble, which is
why [`sw/gfx.asm`](../sw/gfx.asm) has `pixel_addr` at all and why
[D20](#d20--addw-xyimm16-added-after-the-m2-gate) exists. A hardware
pixel port that does that arithmetic on the blitter's own adders is
*faster* than direct addressing for every sub-byte format. 8 bpp is the
one mode where `ST [X],R0` would genuinely have won, and at 61,440 bytes
it could never have lived in main RAM anyway.

**The real cost is to the debugger.** `tools/cool8screen.py` and the
loader's 64 KB read-back reach main RAM only. Text mode — the thing you
look at most — is unaffected, but VRAM is dark. The mitigation is to
**alias the VRAM data port across a 64-byte block of the I/O page**
(`$FEC0-$FEFF`), so one loader `READ` frame pulls 64 consecutive VRAM
bytes instead of re-reading one register. 64 KB is then 1024 frames:
slow, but it exists, and it costs *fewer* gates than decoding the
address precisely.

**Runner-up: everything in dedicated VRAM, including text.** Cleaner in
one way — one memory model, one arbiter. Rejected because it would put
the boot ROM's first printed message behind an indirect port, break
`cool8screen.py` entirely, and throw away
`cool8_text.v`, which was built and verified
against main RAM. The split keeps first light cheap and keeps the
debugging tool that made M4 tractable.

---

## D29 — The video subsystem runs at 12 MHz; only the raster is at 25.125

**Decided at M5.**

[D26](#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled)
decoupled the pixel clock and left open which domain the *rest* of the
video engine lives in. With a dedicated VRAM there is a real choice:
clocking VRAM at 25.125 MHz would double its bandwidth to 798 accesses
per line.

**Decision:** clock VRAM, the fetch engine, the sprite engine, the
blitter and both arbiters at 12 MHz. Only [`cool8_vga`](../rtl/soc/cool8_vga.v)
and the pixel output stage run at 25.125.

**Why:** the extra bandwidth is not needed and the second domain is not
free. At 12 MHz a line is 381 VRAM accesses, and the worst realistic
load is:

```
8 bpp 256-wide background      128 acc   34 %
8 sprites x 16 px at 4 bpp      32 acc    8 %
─────────────────────────────────────────────
blitter still gets             221 acc   58 %
```

That is 211 KB per frame of blitter throughput — enough to clear a
320×240 4 bpp screen in about a fifth of a frame with the CPU untouched.
Nothing in the mode set is bandwidth-starved at 12 MHz, so the second
domain would buy headroom nobody spends.

Against that, keeping one domain means **the only clock crossing in the
whole machine stays the dual-clock line buffer** that
`cool8_text.v` already implemented and that
`sim/test_video.py` already exercises with the two clocks running at
incommensurate rates. A 25 MHz video domain would add a crossing on the
CPU register port, a crossing on the main-RAM fetch path for text mode,
and a synchroniser on every status bit the CPU polls.

**Recorded so it is not re-derived:** if a future revision wants two
background layers or 16 sprites per line at 8 bpp, the 25.125 MHz VRAM
domain is where the bandwidth comes from, and the cost is those three
crossings.

---

## D30 — The text map stride is a register, and the canonical map is 128×32

**Decided at M5.**

A source conversation proposed a 64-column text mode on the grounds that
it is more readable than 80. That is not the real argument, and acting
on the stated one would have cost 20 % of the screen width for nothing.

**The actual property worth having is a power-of-two row stride.** At
80 columns and two bytes per cell the stride is 160, and the address of
row *r* is `base + r·160` — a multiply. `MUL` exists
([D18](#d18--8x8-multiply-landing-in-x)) and costs 12 cycles, but it
**lands in X**, so a caller holding a pointer has to spill it. That is
not a hypothetical: [D21](#d21--four-general-registers-is-enough-confirmed-question-closed)
measured 6 spill instructions in a 277-instruction corpus and **two of
them are exactly this pattern**. Text row addressing is the most
frequent address computation a monitor or an editor performs.

**Decision:** `VID_STRIDE` is a full 16-bit register, and the canonical
text layout is a **128×32-cell map, 8192 bytes, with 80×30 displayed**.

| | Stride 160 | **Stride 256** |
|---|---|---|
| Map | 80×30 cells, 4800 B | 128×32 cells, 8192 B |
| Row address | `MUL`, 12 cycles, clobbers X | `XH = base_page + r`, one add |
| Circular scroll wrap | compare and subtract | `AND R0,#31` |
| Spare rows off-screen | none | 2 |

Rounding a map up to a power of two in both dimensions is what tilemap
hardware has always done, and for this reason; the spare rows and
columns then turn out to be where smooth scrolling gets its margin.

**Why a register rather than a constant:** the fetch engine needs a
row-base accumulator either way, so the adder is not new — only the
operand's width is. That one register then serves three jobs: text map
stride, tile map width, and bitmap row pitch. Software that wants the
4800-byte screen back writes 160 and pays the `MUL`.

**64-column text is dropped.** 80×30 with an 8×16 font on 640×480 is
what every PC did for twenty years and it is readable. The conversation's
alternative — rendering 512 pixels and stretching to 640 — is a 1.25×
non-integer scale that duplicates every fourth column and makes glyph
stems uneven. If a 64-column screen is ever wanted it is a tile map with
a stride of 128 and needs no dedicated hardware.

**One related correction.** [04-system.md §5](04-system.md) previously
specified mode 1 as 40×25 with 8×8 glyphs taken from "the top or bottom
half of each glyph cell", which halves the font to get a second mode.
Mode 1 is now **40×30 with the same 8×16 glyphs doubled horizontally
only** — 16×16 cells, the real character set, the same 30 rows as mode
0, and no second font image.

---

## D31 — The palette is an indexed port, not direct-mapped registers

**Decided at M5, forced by arithmetic.**

[§4.2](04-system.md) mapped 16 palette entries directly at
`$FE20-$FE3F`, two bytes each. A 256-entry palette is 512 bytes and the
whole I/O page is 256 ([D7](#d7--memory-mapped-io-256-byte-page-at-ff00)),
so direct mapping is not available at any price.

**Decision:** `PAL_IDX` and `PAL_DATA`, where `PAL_DATA` auto-increments.
Two registers instead of thirty-two. Loading a full palette is a
512-store loop; changing one entry is three stores.

The palette itself moves from flip-flops into one EBR block, which is
**smaller** than the sixteen registers it replaces as well as sixteen
times larger.

**Consequence worth stating:** a raster split that changes palette
entries mid-frame now costs three stores per entry rather than two, and
the index register is architectural state a raster interrupt handler
must not corrupt. That is the standard cost of an indexed port and it is
why `PAL_IDX` is readable.

---

## Resolved former open questions

Recorded so they are not re-opened without new information.

| Question | Resolution |
|---|---|
| Should `LD Rd,[X+Rs]` be promoted to the primary page? | **No.** Stays on page 2 at two bytes. Promoting it would cost `[abs16]` load/store, and there is no evidence yet that array code leans on it hard enough to justify that. Revisit only if M2 assembly says otherwise. |
| Does `CMP Rd,Rd` deserve its four encodings? | **Yes.** Kept for regularity. Every register combination stays legal, the decoder needs no special case and the assembler needs no exception. Four encodings of 256 is cheap. |
| 16-bit counted loops | **Accepted as-is.** `DECW X`/`DECW Y` set `Z` from the full 16-bit result, so `DECW`+`BNE` is a two-instruction 16-bit loop whenever a pointer register is spare. When both pointers are busy, nest the loop or spill the counter. No new instruction. |
| What gets cut if the ASIC overruns? | **Nothing.** See D19. |

## D32 — The system clock is 8.375 MHz, a third of the pixel clock

**Superseded [D26](#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled),
and not by choice.** D26 put the CPU on the board's raw 12 MHz with no
PLL in its path, and said the pixel clock would be made separately. The
iCE40UP5K cannot do that.

The part has **one** PLL and its reference is a *pad*, not a fabric net.
On the SG48 package that pad is pin 35, which is where the iCESugar's
12 MHz arrives. Asking for both is not a trade-off, it is a placement
error:

```
ERROR: PLL bel 'X12/Y31/pll_3' cannot be used as it conflicts
       with input 'clk$sb_io' on pin '35'
```

So one of the two clocks has to be derived from the other, and it is not
the pixel clock that gives: a monitor is counting those, and 25.125 MHz
is already 0.2 % off nominal ([§5.1](04-system.md)). The system clock is
therefore a division of 25.125.

**Half of it — 12.5625 MHz — does not close.** Measured, placed and
routed with the display engine in and the blitter not:

| placer seed | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| `sclk` Fmax, MHz | 11.56 | 11.43 | 11.01 | 11.53 | 11.40 | 11.34 |

The spread is the placer; the shortfall is the design. The critical path
is the one D26 named and M4 measured — SPRAM read data, through the
block and byte selects, the boot ROM's mux and the I/O page's, the
instruction decode, and into the next state — and it is **37 levels of
logic and 87 ns** of them. No seed makes that 79.6.

A third of it is **8.375 MHz**, and the finished machine closes at 10.81
with 27 % margin. That margin is the reason for choosing it over the
10.05 MHz a 50.25 MHz output divided by five would have given: at 89 %
occupancy a clock that only just closes is a clock that has to be
revisited every time anything is added.

The divider is registered rather than decoded, so `sclk` comes out of a
flip-flop and cannot glitch, and it reaches a global net through an
explicit `SB_GB`. One clock in three is high; nothing in the design is
level-sensitive and 39.8 ns is far more than any flip-flop's minimum
pulse width.

**What it cost.** 30 % of the CPU's speed against M4, and every constant
that follows the clock: the UART divider is 72 rather than 103
([§4.6](04-system.md)), the audio reference and its note table
([§4.4](04-system.md)), the timer's tick ([§4.5](04-system.md)), the
boot ROM's 365,036 clocks are 43.6 ms rather than 30, and a scanline is
266 system cycles rather than 381 — which is what
[§5.10](04-system.md)'s bandwidth table is counted in.

**What it did not cost.** The pixel clock, which is exact: 12 × 67 / 32,
VCO 804 MHz, no rounding anywhere.

The two clocks are now phase-related, which the design does not use and
must not start using. The crossing in `cool8_video` is a toggle through
two flip-flops either way; a relationship the tools do not constrain is
not a relationship to build on, and it costs six flip-flops to ignore.

**This is worth reopening**, and it is the first thing to reopen. The
87 ns is a decode cone, not a routing problem, and
[D23](#d23--no-memory-address-register) is where it comes from: the core
reads the opcode straight off the bus and its address is a combinational
function of the byte it is fetching. Registering that would cost a cycle
per access and buy back the clock and more. With
[D33](#d33--the-asic-path-is-shelved-the-target-is-the-fpga) the cycle
counts are free to change, and `sim/cosim.py`'s 511 encodings are the
net that makes the attempt survivable.

---

## D33 — The ASIC path is shelved; the target is the FPGA

**Not cancelled — shelved, and the discipline kept wherever it is free.**

M8 and the TinyTapeout submission are out of the plan. What that changes
is permission rather than direction: cycle counts may change without a
tapeout implication, the bus protocol is fair game, and `rtl/core` is no
longer obliged to be Verilog-2001 with no vendor primitives, no inferred
RAM and no clock gating ([00-goals.md](00-goals.md) C2).

**It buys less than it looks like it should.** The thing it was invoked
for — the 87 ns critical path in
[D32](#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock) —
is 37 levels of *logic depth*, and depth is the same whether it is
headed for sky130 or iCE40. Shelving the ASIC does not make the fix
cheaper; it makes the fix *allowed*.

So the rule is: keep `rtl/core` clean, because clean costs nothing
today, and break the rule only where a measurement says it buys speed.
`sim/synth.py`'s hygiene checks stay and stay passing. A core that is
still portable is a milestone that can be un-shelved; a core that has
been casually sprinkled with `SB_` primitives is a rewrite.

What is already banked and does not need redoing: M3's LibreLane run —
20,960 µm² at 61.2 % utilisation in two tiles, clean DRC, LVS and
antenna, closing at 50 MHz at every PVT corner. That was the risk the
ASIC path carried and it was retired years before it was needed.

---

## D34 — The video engine ships with sprites and a pixel port, and no blitter

The M5 gate was built to answer "does it fit". It answered no, twice,
and this is what came out.

**What the estimates said, and what the silicon said:**

| | estimated LUT4 | measured |
|---|---|---|
| VRAM + the four-way arbiter + the indirect port | 130 | 263 |
| fetch engine, pixel shifter, palette, registers | 1051 | 1386 |
| blitter — rects, transparency, clip, logic ops | ~350 | 1306 |

**Every estimate for this subsystem came in at about half.** The first
row was recorded when it happened and the rest of the numbers were
carried forward anyway, which is the process mistake worth naming: an
estimate that has already been proven 2× low is evidence about the
estimator, not about the one block.

The blitter's 1306 is the one that was avoidable. It wrote the pixel
extract and merge as seven variable shifts on full 16-bit words, and
each of those is a barrel shifter that shares with nothing. A pixel
never straddles a byte, so the same arithmetic in eight bits — select
the byte, merge, and write `{byte, byte}` with `MASKWREN` choosing the
half, exactly as `cool8_spram` already does for the CPU's byte port —
is about 200 LUT4. That is what `cool8_pixport.v` is.

**With a blitter the machine does not fit at all**: 5438 logic cells
against the 5280 that exist, and `nextpnr` failing rather than warning.
Even rewritten tight, a blitter and a sprite engine together land at
97–102 %.

**Sprites were kept and the blitter was dropped**, because
[§5.3](04-system.md) already contains the argument: a tile map needs no
double buffering because nothing is redrawn, which is why the NES and
the Master System had no framebuffer. Tiles plus sprites is a machine
that draws nothing per frame and therefore needs no accelerator at all.
The blitter serves the bitmap path — which is also the path with the
worst bandwidth and no double buffer in mode 4.

**`PIX_X`/`PIX_Y`/`PIX_DATA` stayed**, at 199 LUT4 and one of the eight
`SB_MAC16` blocks the design had never used. It is not a small blitter;
it is the address arithmetic, which is the part an 8-bit CPU is genuinely
bad at. `y * stride` in software is a sequenced multiply; here it is a
DSP block that was idle. Without it, plotting one 4 bpp pixel by hand
through `VRAM_DATA` is about twenty cycles, and the bitmap modes are a
curiosity rather than something to draw in.

**Bresenham went first**, under
[06-roadmap.md](06-roadmap.md)'s own decision table, before any of the
above. Lines are about six cycles a pixel through `PIX_DATA`.

**Where the machine landed:**

```
ICESTORM_LC       5076 / 5280   96 %
ICESTORM_RAM        29 / 30     96 %
ICESTORM_SPRAM       4 / 4     100 %
ICESTORM_DSP         1 / 8      12 %
sclk closes at 10.81 MHz against a constraint of 8.375
```

The blitter is not deleted from the design, only from the part.
[§5.11](04-system.md) prices it alongside the second background layer,
and the day the CPU's fetch path is fixed and the clock comes back is
the day to price it again.

---

## D35 — The scroll registers are fine scroll; the coarse part is a move of `VID_BASE`

[§5.5](04-system.md) described `VID_SCRL_X`/`VID_SCRL_Y` as ten-bit
registers covering whole-tile and fine pixel motion in one pair. They
are implemented as fine scroll only — the low four bits in text, the low
three in tiles — and a bitmap gets the full range for nothing because
its whole row is in the line buffer already.

The coarse part is a move of `VID_BASE`: one 16-bit add in software per
row or per tile column, which is exactly what "increment the origin row"
meant in that section for the vertical direction anyway. Doing it in
hardware means a multiply — the row's address is `origin × stride` — and
the two alternatives are a DSP block the pixel port has a better claim
on, or an accumulator that has to be re-run whenever the register moves.

What it costs software is one add. What it saves is a multiplier and a
special case in the fetch engine, in a subsystem that came in at twice
its estimate three times running
([D34](#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter)).

The circular wrap that makes terminal scrolling free is unaffected and
is still in hardware: the row pointer wraps within `stride × 32`, which
is [D30](#d30--the-text-map-stride-is-a-register-and-the-canonical-map-is-12832)'s
32-row map, and it is correct only for a power-of-two stride — which is
the argument D30 made for a power-of-two stride in the first place.

---

## D36 — The monitor runs in place from ROM; the overlay is not dropped

[§3](04-system.md#3-boot-sequence) described a boot sequence whose last
two steps were *"copy the monitor image from EBR into RAM"* and *"`ROMEN
← 0`; jump to the monitor"*. Neither happens. The boot code sets up
video, installs the vectors and jumps straight into the monitor, which
executes out of the ROM window where it stands, and `ROMEN` stays set.

**A monitor in RAM is a monitor that a loaded program overwrites**, and
it is overwritten at exactly the moment it is wanted: something has just
gone wrong with the program that ran off the end of its buffer, and the
tool for looking at the wreckage was in the wreckage. Leaving it in ROM
makes it un-clobberable by construction rather than by convention, which
is the same argument
[D15](#d15--the-loader-is-hardware-not-a-rom-monitor) makes for the
loader being hardware.

What it costs is 4 KB of address space, in a map with 60 KB free below
it and a machine whose largest program so far is 3 KB. A program that
genuinely wants the top of memory clears `ROMEN` itself with one store
to `SYSCTRL` — the mechanism already exists, it is already tested, and
the program that needs it is the program that knows it needs it.

It also deletes the step that would have been hardest to get right. The
copy runs *through* the ROM's own read window into the RAM underneath,
which works — that is how the vectors get installed — but it means the
machine spends a few hundred microseconds with two copies of the monitor
and one of them half written, and the jump has to land after the overlay
moves. None of that has to be reasoned about now.

The monitor's variables still live in RAM, at `$EF00`, immediately below
the window and inside the region the boot code has already cleared.

## D37 — The UART receive FIFO moves into block RAM, reversing M4's call

`cool8_soc.v` carried an explicit `(* ram_style = "logic" *)` on the
sixteen-byte receive FIFO, with a comment giving the price of refusing
the inference and an argument for paying it. Both halves of that
argument have since inverted, and the measurement is:

| | LUT4 | flip-flops | EBR |
|---|---|---|---|
| flip-flops (M4's choice) | 3710 | 1527 | 27 |
| block RAM | 3601 | 1404 | 28 |
| | **−109** | **−123** | **+1** |

At M4 the design was at 37 % of the logic and the font was about to
claim eight block RAMs, so spending logic to save EBR was right. After
M5 the part is 92 % full of logic with three block RAMs spare — and the
boot ROM is holding 174 bytes in eight of them. **EBR and logic cells
are not interchangeable on this part**, so the ROM's waste cannot be
spent on anything except more block RAM; what it *can* do is pay for
storage that would otherwise be built out of flip-flops, and that is
what this does. M6's two blocks needed 340 LUT4 and this gave back a
third of it.

The inference itself is still not what happens. Left alone, yosys
retimes the read capture into the block's own output register, and no
test in this project reaches a netlist except `sim/test_boot.py` for the
ROM image. So the read register is written out and the contract is
stated instead of assumed: **the head byte is correct whenever the
"data available" bit is set**, enforced by a `settle` flag that
suppresses availability for one cycle after anything moves either
pointer. `cool8_ps2.v`'s FIFO is built the same way, and
`sim/test_ps2.py` sweeps a blind read across the arrival window to prove
it — a phase that was added because the mutation that removes `settle`
survived every other test in the file.

---

## D39 — three area optimisations were measured; two of them were negative

Recorded because each looked obviously right, and re-deriving them costs
a day each.

**The sprite line buffer went from fourteen bits to nine, and that
worked.** It is 2048 entries, and an iCE40 block RAM 2048 deep is two
bits wide, so the entry width *is* the block count. Dropping the
per-sprite palette bank in favour of `SPR_CTRL[7:4]` took it from seven
blocks to five. Eight bits and four blocks was available and refused:
it needs a three-bit generation tag, which needs the sweep to cover a
bank in five passes instead of ten, and the sweep blocks rendering — the
cost is about two sprites a line. See [§5.6](04-system.md).

**`PIX_DATA` became write-only, and that worked** — about 39 LUT4 and a
stall path. [§5.7](04-system.md) has the argument.

**Making `hstart`/`hactive`/`vstart` written registers did not.**
Removing the compare, subtract and shift that derives them measures −48
LUT4 *if the capability goes with it*; keeping bordered modes means
preset-loading the three values and decoding six write addresses, and
that costs more than the divider. Measured **+44** with full-width preset
fields and **+35** with a four-bit preset and write-only registers.
Reverted. The derivation is cheaper than the registers that would
replace it.

**Deriving the pixel stage's second lookahead from the first did not
either.** `sx2 = sx1 + inc`, with a registered per-mode constant for the
line wrap, measures **+23 LUT4**. Everything in the first chain shares
structure with the second and the mapper exploits it; the derived form
adds a constant-path adder and a register that share with nothing.
Reverted, with a comment in `cool8_pixel.v` so it is not retried.

**The process point.** All four were sized first by deleting the feature
and re-synthesising, and three of those probes over-reported because
deleting a feature also deletes the decode and the read-back that a real
implementation has to keep. **A removal probe measures the ceiling, not
the change.** [D34](#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter)
named the estimator as the thing to distrust; this is the same lesson one
level down.

---

## D40 — The hardware loader is a build option, and it is off

**Decided at M7, and it paid for the flash write path.**

[D15](#d15--the-loader-is-hardware-not-a-rom-monitor) built the loader
because of a chicken-and-egg problem: the boot ROM is part of the
bitstream, so changing how loading works meant a full rebuild and a
re-flash — and during M4-M6 there was no working software at all, so
every software bug became a bitstream rebuild.

**All three of the things that made it necessary now exist.** There is a
boot ROM, a monitor, and a flash reader. `icesprog -o 0x100000 -w
prog.bin` followed by `L` at the monitor gets a program in without a
rebuild, and once the machine can write its own flash (D42) it can put
one there itself.

So `cool8_soc` and `cool8_top` take a `LOADER` parameter and it defaults
to **0**. **376 logic cells**, measured, and `sclk` went from 11.02 MHz
to 11.76 in the same step.

**It is parameterised rather than deleted, and that is the point.**
`cool8_loader.v` stays in the tree and its tests stay passing;
`cool8_soc_tb`, `cool8_wire_tb` and `cool8_soc_boot_tb` ask for
`LOADER(1)` explicitly, the last of those because it checks a cold boot
by reading RAM back and only a bus master can do that. Build a bring-up
image with the parameter set, drop something else, and the debugger is
back in ten minutes.

**What is genuinely given up** is debugging a board whose CPU never
started — the case D15 was built for. That is a bring-up capability
rather than a development one, and the replacement for the development
half of it is the break button below.

### The break button, and what the board taught that simulation could not

`SW[0]` as an NMI is specified in [04-system.md §6](04-system.md) and had
never been built. It is what replaces the loader's `HALT`: press it and a
hung program lands in the monitor with its state intact, because an NMI
pushes `PC` and `F` and changes nothing else.

The first version fired the moment the pin read low and then ignored it
for 62 ms — the ordinary way to absorb contact bounce. **On the board it
produced a machine taking interrupts continuously**, and the only symptom
was the LED flickering far too fast to be anything the software wrote.

Two faults, and both needed fixing:

- **No pull-up in the `.pcf`.** Nothing on the iCESugar holds that pin,
  and a floating iCE40 input oscillates.
- **Firing on the first low sample.** For a pin that might be floating
  that is exactly backwards: every oscillation became an NMI.

It now requires the line **continuously low for 2 ms**. The counter
resets on any high sample, so noise never accumulates; it saturates, so
one press gives one NMI however untidily the contact closes; and it
cannot fire again until the button is released. The pull-up makes an
unconnected pin read as released, and the counter makes a noisy one
harmless — both halves are needed.

**No testbench would have caught this.** `cool8_top_tb` ties `sw0` high
because that is what "not pressed" means, and every simulation of a
floating pin is a decision about what to drive it with. This is the one
finding in the project that required silicon.

---

## D41 — The sound engine is one datapath walked eight times, not four dividers

**Decided at M7, and it is smaller than the four voices it replaces.**

[D12](#d12--audio-sn76489-style-not-sid-style) specified three square
channels and a noise channel, each with its own 12-bit divider and
attenuator, and budgeted ~250 LUT4. That is the SN76489's shape, and the
SN76489's shape answers the SN76489's problem: a 4 MHz part with no
cycles to spare had to make four voices in parallel because it could not
make them in series.

This part has 8.375 MHz and wants a ~32 kHz sample rate — **256 system
clocks between samples, and a voice needs four.** So there is one of
everything, time-multiplexed, and everything else follows:

- **A phase accumulator, not a divider.** Per voice in parallel a divider
  is smaller, which is what D12 weighed. Shared, it is the other way
  round: an accumulator is one adder for every voice where a divider
  needs a reload comparator each. Pitch resolution is 0.5 Hz across the
  whole range, against a 12-bit divider's 46 Hz at the bottom and 12 kHz
  steps at the top.
- **Voice state in one block RAM**, 24 words of 256. As flip-flops it
  would be 288, which is where the parallel design's area went.
- **A serial mixer** — one 4-bit add into an accumulator, not a tree.
- **Two I/O addresses**, `SND_IDX`/`SND_DATA`, not twenty-four decodes.

**Measured: 141 LUT4, 131 flip-flops and one block RAM, for eight
voices.** Against 250 budgeted for four.

The result worth carrying forward: **once the datapath is shared the
voice count is nearly free.** One voice to eight costs RAM words and
clocks out of a budget with 224 spare, not logic. The expensive step is
the first voice.

**No DSP block**, though seven are idle. A square wave times a 4-bit
volume is a sign and a mux, not a multiply. The DSP earns its place the
day a voice reads a wavetable or a sample out of memory — that is the
upgrade path, and it is a good one — but on squares it would buy nothing.

**No envelopes, sweep, ring modulation or filter.** A vblank handler
doing envelopes is about twenty instructions and can make shapes no
hardware ADSR offers.

D12's *conclusion* stands — squares and an LFSR rather than SID-style
filters, for the same reason — and its *implementation* does not.

---

## D42 — The machine can write its own flash, above a hardware floor

**Decided at M7. It is the difference between a machine that loads and a
machine that saves.**

[D16](#d16--flash-access-is-read-only-in-hardware) made the SPI master
read-only and wrote down the upgrade path in the same breath: allow
writes, but gate them on a hardware comparison against a fixed floor, so
the bottom 1 MB is unreachable by construction. This is that.

`$FE8E` `FLS_WDATA` and `$FE8F` `FLS_WCTRL` — write 1 to program the byte
at `FLS_ADDR`, 2 to erase its 4 KB sector, 4 to acknowledge a refusal.
About 7 MB the machine owns. **277 LUT4** for the whole block, reads
included.

**The floor is checked on the cycle the request arrives, before an
opcode has been chosen.** A request below `$100000` sets a flag and does
nothing else: no write-enable, no command, no chip select. There is no
path in the gates from a bad request to a shifted opcode, which is what
makes this safe by construction rather than by review.

`sim/test_flash.py`'s device model **fails the run** on any opcode
outside the five this master has, on any program or erase below the
floor, and on either without a preceding write-enable. `sim/mutate.py`
carries the mutation that removes the floor check, and it is caught —
23 of 23 flash mutations are.

**What it took to get right**, because both faults are the kind that
recur:

- **One driver for chip select.** A flash latches its opcode on the
  *rising* edge of `CS`, so two commands run together are ignored. The
  first attempt had the shifter and the opening path both driving it and
  the sequence silently did nothing. It is now a single `assign` and the
  `W_GAP` states exist purely to produce that edge.
- **The write phases go last in the testbench.** An erase clears 4 KB and
  the device model aliases every address into 64 KB, so an erase placed
  mid-file wipes bytes a later read phase checks. That produced failures
  that looked like read bugs and were not.

**Untested on hardware.** The floor is proven in simulation and every
mutation of it is caught, but a page program on real silicon is not a
Verilog model. Back the bitstream up and try a high address first.

---

## D43 — The sprite engine renders eight 16x16 sprites, and did not before

**Found by measurement at M7, after the specification had claimed it for
two milestones.**

[04-system.md §5.6](04-system.md) says eight sprites per scanline. A
harness that counts clocks says otherwise:

| 16x16 sprites on one line | clocks | 266 available |
|---|---|---|
| 5 | 258 | fits, 8 to spare |
| 6 | 296 | **overruns** |
| 8 | 372 | **overruns by 40 %** |

Perfectly linear: 68 clocks of fixed cost and 38 a sprite. **The real
limit was five**, and the failure was silent — a new line aborts whatever
is running, and `SPR_CTRL`'s overrun flag only ever fired for a *ninth
descriptor*, never for a render that was cut off.

Three changes, and the engine now finishes eight in **237 clocks with 29
to spare**:

- **The pattern fetch is pipelined.** Word *w+1* is requested while word
  *w*'s four pixels go out, where before it was request, wait, push,
  request again — three clocks in every seven.
- **The generation tag went from four bits to five and the sweep halved
  to 32 entries.** That is free: the line-buffer entry is 2048 deep and
  an iCE40 block RAM that deep is two bits wide, so nine bits and ten
  bits both cost five blocks. A five-bit tag separates 32 fills where
  four separated 16, and the sweep only has to outrun the tag. It buys 32
  clocks of a 266-clock line back, because `S_TALLY` waits for the sweep.
- **The first request is issued from `S_D3`**, off the descriptor bus
  rather than the register, and `S_FW` takes its word straight off the
  VRAM bus instead of parking it.

25 clocks a sprite, down from 38, for **+28 LUT4 and +18 flip-flops** and
no extra block RAM.

**`overrun` now also fires when a render is aborted**, so this can never
be silent again. `sim/tb/cool8_video_tb.v` gained a full house of large
sprites, and the 4,915,200-pixel comparison covers it.

**The process point.** This was arithmetic in a comment for two
milestones and nobody counted. `sim/test_video.py`'s "ten on a line"
phase used a *mix* of sizes and passed throughout. A limit that is
asserted rather than measured is a limit nobody knows.

---

## Open questions


**The fit question is closed.** It was the only one, it was answered by
`nextpnr` rather than by arithmetic, and the answer cost the blitter and
three megahertz — see
[D34](#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter)
and [D32](#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock).

What is left in its place is a question the gate uncovered rather than
one it was asked:

### D38 — the fetch-path next state is decoded flat, and it bought area rather than speed

**Attempted as a speed fix, kept as an area one.**

`nxt` out of `S_FETCH` used to be derived through the `g_*`/`p_*` group
wires, `nopnd` and `exec_state` — all shared with `S_MEM` and `S_EXEC`,
which have enormous slack. It is now its own flat `case` on the eight
opcode bits. The reasoning was that factoring a slack path wants is
factoring the tight path pays for.

**Measured across four placer seeds:**

| | seed 1 | 2 | 3 | 4 | mean | best |
|---|---|---|---|---|---|---|
| before | 11.46 | 11.34 | 11.05 | 10.65 | **11.12** | 11.46 |
| after | 11.23 | 11.24 | 11.09 | 11.45 | **11.25** | 11.45 |

**+0.13 MHz on the mean, against a seed spread of 0.8.** That is not a
result. It is kept because it is smaller: `cool8_core` went from 948 LUT4
and 148 flip-flops to **902 and 140**, and the duplication pays for
itself.

**The single-run comparison that motivated it said 10.81 → 11.90**, which
is two draws from opposite ends of that distribution. D32 ran six seeds
for exactly this reason and the lesson had to be learned twice.

**What the timing report says instead.** The `sclk` critical path now
starts at `cool8_spram`'s `blk_r`, and its first hop is **4.25 ns of
routing** — (21,10) to (24,1), most of the way across the die — before it
reaches a single LUT, on its way to the boot ROM's read mux. Collapsing
the chained read muxes into one one-hot select, which was the other
proposal, attacks logic depth on a path whose first term is a wire.
Replicating `blk_r` and `byte_r` so each consumer has a local copy is the
cheaper thing to try, and it is untried.

### Should the core's fetch path be pipelined?

The machine closes at 11.2 MHz and runs at 8.375 — it was 10.81 before
M7, and [D38](#d38--the-fetch-path-next-state-is-decoded-flat-and-it-bought-area-rather-than-speed)
and the loader coming out account for the difference. **The next rung is
12.5625 MHz, half the pixel clock**, and it is 1.4 MHz away rather than
1.75. The gap is one critical path: SPRAM read data, through the block and byte selects, the
boot ROM's mux and the I/O page's, the instruction decode, and into the
next state — **37 levels of logic, 87 ns**. It is not congestion; the
spread across six placer seeds is under 6 %.

It is [D23](#d23--no-memory-address-register) showing up. The core has
no memory address register and its decoder reads the opcode straight off
the bus during a fetch, which is what made the RTL a cycle or two faster
than the provisional table everywhere. The cost is that the byte and the
decision it drives are in the same cycle.

Registering the opcode would break the cone in two and should roughly
halve it. It costs a cycle per fetch, so every number in
[02-isa.md §8](02-isa.md#8-timing-model) changes, and
`tools/opcodes.py`, the emulator and `sim/timing.py` change with them.
Whether the machine comes out ahead is arithmetic nobody has done yet:
a 50 % clock gain against a cycle-count loss that depends on the
instruction mix, which `sim/test_corpus.py` can measure.

Two things make it worth attempting now rather than never.
[D33](#d33--the-asic-path-is-shelved-the-target-is-the-fpga) means the
cycle counts are free to change, and `sim/cosim.py` compares full
architectural state on all 511 encodings — so the change is verifiable
by construction rather than by reading.

### `MOV Rd,<pp>` and the flags

<details>
<summary>The argument, as it stood</summary>

**Does `MOV Rd,<pp>` set flags?**

[02-isa.md §1.2](02-isa.md#12-flag-effects) states three rules, the
first of which is *"`MOV` never touches flags; loads do"*. The normative
flag table underneath it lists `MOV Rd,Rs` and `MOV Rd,#imm8` by name
and does not mention the page-2 pointer-half move `MOV Rd,XL` at all.

The reference emulator sets `Z` and `N` from the moved byte, treating it
as a load. The RTL now matches the emulator, because the emulator is the
co-simulation reference and a disagreement there would have masked real
bugs. But that is a decision made by omission rather than on purpose,
and it should be made on purpose.

The case for making it **flagless**, which is the recommendation:

- The instruction is called `MOV`, and rule 1 is unambiguous about what
  `MOV` does. A reader of the ISA will expect it.
- The reason loads set `Z`/`N` is that `LD` then `BEQ` is the commonest
  two-instruction sequence in 8-bit code. `MOV R0,XH` then `BEQ` is not
  that sequence; extracting a pointer half is nearly always followed by
  arithmetic, which sets the flags itself.
- It makes the two directions symmetric: `MOV <pp>,Rs` already sets no
  flags.

The case for leaving it as it is: it is a byte arriving in a register
from somewhere other than the ALU, which is what rule 1's "loads" means,
and changing it now means changing the emulator, the RTL and the table.

Either way it is a one-line change in each of the three, and the
co-simulation will prove they agree. It needs a decision, not more
analysis.

</details>

The question before that — whether four general registers are enough —
was closed by measurement at the M2 gate; see
[D21](#d21--four-general-registers-is-enough-confirmed-question-closed).

## D44 — There is one emulator and it is gated against the RTL, not
against itself

> **Superseded in its subject by [D57](#d57--the-python-machine-is-gone-rust-is-the-machine-and-the-rtl-is-its-gate)**,
> which retired the Python machine this entry is about. **Its
> principle survived unchanged and is why the hand-over was safe**:
> one machine model, gated against the RTL rather than against itself.
> Read it as the argument, not as a description of the tree.

**A software machine is only worth writing an operating system against
if it agrees with the gates.** `tools/cool8vm.py` is the whole computer
in Python — the memory map, the ROM overlay, every register in
[04-system.md §4](04-system.md), video, sound, the keyboard, the UART
and the flash with its address floor. Three decisions hold it honest.

**The CPU is not modelled there.** `tools/cool8emu.py` is imported and
used as-is. It is already the executable specification the RTL is
checked against instruction by instruction across all 511 encodings, so
a second, faster copy would create two models that have to agree — the
trap this document warns about for opcode tables. There is one CPU model
in this project and this is not it.

**The picture is checked against the RTL's own pixels.**
`sim/test_video.py` dumps three frames as they leave the DUT — mode 0
text, mode 2 tiles, and eleven sprites over a bitmap — and
`sim/test_vm.py` replays the stimulus that produced them through the
emulator's registers and compares all **1,843,200 pixels**. The sound
engine does the same with 4096 samples of a five-note chord plus noise
from `sim/test_snd.py`.

**The stimulus is written out twice on purpose**, once in Verilog and
once in Python. Sharing it would make the comparison a test of the
renderer against itself. Writing it twice means a misunderstanding of
what a register means has to be made identically in two languages to go
unnoticed — and it caught four in one afternoon: a 12-bit concatenation
read as 16, a byte pair the wrong way round, an unloaded font, and a
VRAM history the tile phase inherits from the bitmap phases before it.

**There are two renderers and neither validates the other.** The scalar
one is the definition, at 0.88 s a frame; the vectorised one is what
makes a window possible, at 13 ms. Both are compared to the same
hardware frames. A fast path validated against the slow one would only
prove they share a misunderstanding.

**What it does not model.** Contention: the display fetch stealing a
cycle, `cool8_vport` stalling on a busy arbiter, the exact instant a
store lands. The machine is scanline-accurate — the CPU runs a line's
worth of cycles, then a line is drawn, then the interrupts are raised —
which is what makes raster splits, mid-frame palette changes and sprite
multiplexing behave. Code whose correctness depends on the rest needs
`sim/`, and that is where it lives.

---

## D45 — The on-machine assembler borrows BASIC's variables and its
evaluator, the way BBC BASIC's does

**An `ASM` block's labels are BASIC variables and its operands are BASIC
expressions.** There is no symbol table inside the assembler, no value
parser, and no pass driver of its own.

This is Sophie Wilson's design and it is worth stating why it is so
small. In BBC BASIC, `.label` is a *directive that assigns `P%` to the
variable named `label`* — forward references work because on the first
pass the variable reads zero and `OPT` suppresses the error, and on the
second it holds the address. Operands go to the interpreter's own
expression evaluator, which is why `LDA #addr AND 255` works: `AND` is
BASIC's `AND`. `P%` is an ordinary resident integer, and the two passes
are a `FOR pass=0 TO 3 … NEXT` **the user writes**. Three of the four
components a standalone assembler needs are things the interpreter
already has.

**What the plan had instead**, and what it cost: a 64-entry symbol table
of five significant characters and a word (90 bytes of code, 448 of
RAM), an `avalue` cut down to a left-to-right `+`/`-` chain with no
precedence and no parentheses (~100 bytes), and a two-pass driver
(~110). About 300 bytes of code and 448 of RAM to reimplement, worse,
machinery sitting a few hundred bytes away.

**The argument against, and it is real.** Labels-as-variables needs a
variable namespace with long names and a heap. This machine had resident
`A`–`Z` and nothing else, so taking the design meant pulling the name
table, the heap and `DIM` — the first half of I4 — in front of I3. That
is a milestone reordered on a design argument, and it stranded ~190
bytes of already-written, already-assembling code in `sw/asm.asm`.

It was taken anyway, because the dependency runs the right way: the name
table is wanted for its own sake at I4, the assembler is the only thing
waiting on it, and building a private symbol table first would mean
building the same thing twice. The natural seam was already named — name
table and heap first, strings second — so the reorder splits I4 where it
was going to split regardless.

**What is kept from the plan.** `agetc`, the ~90-byte untokeniser, and
the mnemonic table: those solve a problem BBC BASIC does not have. The
editor tokenises the inside of an `ASM` block, so `SUB` arrives as `$81`
and a label spelled `LOOP` as `$89`, and reading characters rather than
token bytes is what dissolves every one of those collisions at once.

**And the operand evaluator is kept, which is half of this decision
withdrawn.** "Operands are BASIC expressions" was written before the
handoff was tried, and it does not survive it: `BRA loop` stores `loop`
as `$89`, so `eval`'s `prim` falls through to `varidx`, meets a token
byte and raises `?SYNTAX ERROR`. Undoing that is exactly what `agetc`
does and nothing else can, so making `eval` read an assembler operand
means putting the untokeniser inside `varidx` — the interpreter's
hottest routine — to serve the one caller that is not the interpreter.
`loop` is the most common label in assembly; this is not an edge case.

So `avalue` stays, reading through `agetc`, and it costs about 100
bytes. That is no loss against the plan, which had already cut operand
expressions to a left-to-right `+`/`-` chain with no precedence and no
parentheses and made `(a+b)*c` a negative test. Byte-select `<` and `>`
stay in the assembler too, because the evaluator reads them as
relational operators.

**What is left of the decision is the part that was worth having**: no
symbol table. A label is a BASIC variable, which costs 448 bytes of RAM
less, makes `CALL other_block_label` work across blocks for free, and
leaves the assembler's symbols in the name table where I5's `h_call` can
still see them at run time. The consequence to know about is that an
assembler label and a BASIC variable of the same name are one variable.
BBC BASIC has exactly that, and it is how data crosses between an `ASM`
block and the program around it.

### BBC solved the token collision differently, and more cheaply

Worth recording, because it was considered and rejected. BBC BASIC's
`AND`, `EOR` and `OR` are both 6502 mnemonics and BASIC keywords, and
its tokeniser **tokenises them anyway, even inside `[ ]`**. The
assembler then intercepts the token bytes where a mnemonic is expected —
`RDSLPT` does `CMP #tknAND / BEQ RDOPGT` and maps them straight through
`MNEML`/`MNEMH` — and never untokenises anything.

That is smaller than `agetc`. It is also narrower: it covers a *mnemonic*
that collided and not a **label** spelled with a keyword, because the
interception happens only at the mnemonic position. BBC can afford that
because `LOOP`, `NEXT` and `END` are not BBC keywords. They are all
COOL8 keywords, so `loop:` is the most ordinary label in assembly and
the narrow trick would destroy it. The ~90 bytes of `agetc` buys every
one of the 36 TOKTAB words in every position, and `sim/test_asm.py`
gates `loop:`, `next:`, `end:` and `.byte` because of it.

### And it settles the crunching question

The same reading answers a separate question: could the tokeniser strip
spaces, and save the interpreter the ~10% it spends testing for them?

**No, and BBC declined the same fix.** Its tokeniser keeps no cross-line
assembler state at all. There is a flag, `zpBYTESM`, but it is
per-*line*: `ASS` sets it on entry, `STOPASM` clears it, and every line
re-enters at `RUNTHG` which resets it to `$FF`, "not within assembler".
So a tokeniser processing the middle of a block does not know it is in
one.

Inside an `ASM` block a space is a separator, not formatting —
`MOV  R0,#5` crunched to `MOVR0,#5` hands the untokeniser one identifier
where there were two. Crunching therefore needs exactly the cross-line
state BBC judged not worth keeping, and BBC avoids needing it by not
crunching: it stores its spaces, as [D46](#d46--the-stored-line-keeps-its-spaces-and-the-interpreter-pays-14-to-skip-them)
does.

## D46 — The stored line keeps its spaces, and the interpreter pays 14%
to skip them

**`sw/basic.bas` stores the line as it was typed.** `enter` drops
exactly one space after the line number and `tokenise` copies every
interior space verbatim, which is what makes `LIST` give back the
indentation — and re-entering a listed line is the editor's whole trick
(the screen IS the buffer -- [13-basic.md](13-basic.md) §9).

`sw/interp.asm` did not skip them, and no gate could see it: every case
in `sim/test_interp.py` builds its token stream by hand with no
separators. A space reaching `varidx` became variable
`($20-'A')*2 = 190`, so a typed `A = 7` assigned `VARS+190 = $00FE`,
which at the time was the assembler's symbol-table pointer, and left
`ERR` at zero. A silently wrong answer on the first line anyone would type.

**The alternative was to not store them**, crunching the line at
tokenise time. It was rejected twice over. `LIST` would stop reproducing
what was typed, and inside an `ASM` block it is not a formatting
question at all: `MOV  R0,#5` crunched to `MOVR0,#5` gives the
untokeniser one identifier where there were two. BBC BASIC keeps its
spaces for the first reason — a crunched program does not tokenise back
— and 6502 Microsoft BASIC keeps them too, with `CHRGET` in page zero to
make the skip cheap.

**The cost is measured.** As a subroutine the skip was **17.2%** of the
expression benchmark, on lines that hold no spaces at all: 6 clocks of
`CALL` and 3 of `RET` to find nothing to do. Inlined as a macro — the
same reason `CHRGOT` is inline — and with `eval` restructured to peek
once for `*`, `+ -` and the relationals together rather than three
times, the benchmark went 7.63x to **8.73x**. The residue is about
14,000 token reads paying 6 clocks each to ask, and it is what
correctness costs here.

---

## D47 — TRUE is -1, so one operator serves logic and bits

**A relational leaves -1, every bit set, and not 1.** It is BBC BASIC's
choice, read off the disassembly rather than a manual, and the reason is
`AND`, `OR` and `XOR`: with -1 the same instruction is the logical
operator and the bitwise one. `IF k > 1 AND k < 9` and `mask AND $0F`
are the same code path, and there is no second set of operators to
write, tokenise or document.

With 1 the logical case works by accident — `1 AND 1` is 1 — and stops
the moment anything is complemented or a mask meets a condition. C did
the same arithmetic with 1 and needed `&&` and `&` as separate operators
to survive it; a 24 KB system cannot afford the pair.

**The cost is that `PRINT a < b` shows -1**, which surprises anyone
coming from a BASIC that prints 1, and that three gated cases changed
their expected value. Both were judged cheaper than two families of
operator. `AND`, `OR` and `XOR` sit at one precedence level below the
relationals rather than BBC's two, which costs `a AND b OR c` its
precedence and saves a recursion level off a 256-byte stack.

---

## D49 — A running program is stopped by an interrupt setting a flag,
not by the interpreter looking at a device

**The vertical blank takes the keystroke; the interpreter reads one
byte.** That is the C64's arrangement and the BBC Micro's, and it is the
only shape that can stop a program at all — a running program is by
definition not reading the keyboard, so something else has to.

The C64's `STOP` routine "does not scan the keyboard": its 60 Hz jiffy
IRQ calls `UDTIM`, which scans the RUN/STOP row and sets a byte, and
BASIC polls the byte. The BBC's 100 Hz interrupt sets the escape flag
the same way, and `*FX229` even chooses whether ESCAPE interrupts or is
merely ASCII 27. Both machines keep the device read *out* of the
interpreter.

**Vblank is the tick because the UART cannot interrupt.** `cool8_soc.v`
drives the core with `irq | vid_irq | ps2_irq`; nothing carries the UART
or the timer to it, and `irq` is an external input nothing drives. So
the tick does the reading — which is exactly what the C64 does, its
jiffy IRQ scanning a keyboard that cannot interrupt either.

**Where it is polled, and why not per statement.** At the four loop
back-edges only: `NEXT` going round, `LOOP` going round, `GOTO`, and
`RETURN`. Those are the only places a program can spin, and a
straight-line program cannot fail to end. Polling per *statement* would
have cost eleven clocks on the hottest path in the system and, worse,
pushed `BCC h_let` out of branch range for the fourth time.

**What it does not fix.** At 115200 a host that streams sends 192 bytes
a frame into a 16-byte FIFO, so a paste is still lost — a person typing
never comes close. Escape was rejected as the key because `serialkey`
treats 27 as the ANSI prefix and then *blocks* in `waitraw`, so Escape
and the cursor keys are the same byte. Ctrl-C is the serial console's
own convention and is unambiguous.

The hard escape remains `SW[0]`, wired to `NMI`, which drops a hung
machine into the monitor with its state intact.

## D50 -- One keyboard decoder, included twice, and its storage belongs
## to whoever included it

`sw/monitor.asm` had a complete Set 2 decoder -- `$F0` breaks, the `$E0`
prefix, both shifts, a 128-byte keymap -- and BASIC could not use a byte
of it. `basic.bin` ends at **$F448**, so its last 1,097 bytes sit under
the `$F000-$FDFF` ROM window; setting ROMEN to call into the ROM would
hide BASIC from itself while it looked. The two builds cannot share
code at run time under any arrangement short of moving BASIC below
`$F000`, which costs more than the 187 bytes of table it would save.

So the decoder is **shared as source**, the answer `sw/toktab.asm`
already gives: `sw/kbd.asm` for the code, `sw/keymap.asm` for the
tables, `.include`d by `sw/boot.asm` and by `sw/basic.bas`.

**It declares no storage.** A `.byte 0` inside it would land in ROM in
one of the two builds and could never be written, so `kshift`, `kbrk`
and `kext` are named but not defined, and each includer places them --
the monitor at `MVARS+68`, BASIC beside its input ring. The same rule
took over `kdset`/`kdclr`: the bitmap they maintain is 115 bytes that
only `KEY()` reads, so the monitor answers both with **a bare RET** and
`sw/kdown.asm` never enters the ROM. That turned a build that was 26
bytes *over* `$FDFF` into one with 36 to spare.

**Named keys are `$80+n`, not ANSI.** The cursors, Home, End, Delete and
Insert have no character, and they share their scancodes with the
numeric keypad -- `$75` is both cursor-up and keypad-8, told apart only
by the `$E0` in front. The monitor cleared that prefix without reading
it, so cursor-up typed an `8` for as long as the decoder existed. The
decoder now returns `$80+n`, a range the keymap cannot produce because
`.look` already rejects every scancode with bit 7 set. One byte in a
byte-wide ring, and `serialkey()` folds it into the same `K_UP` it makes
out of a terminal's `ESC [ A` -- so one function knows what a named key
is, and nothing above it can tell which wire the key came in on.

Emitting real ANSI sequences instead was the runner-up. It would have
cost a table of finals, 3-4 bytes of a 16-byte ring per keypress, and
about 30 bytes more code, to make the PS/2 port pretend to be a
terminal it is not.

**Break is Ctrl+Pause**, which arrives as `$E0 $7E` and decodes to `$03`
-- the byte the serial console's Ctrl-C already produces. One entry in
`extmap`, no new code in the interrupt handler, and one break path
rather than two. Escape stays an ordinary character, which a game's menu
wants it to be, and which D49 already declined to spend.

---

## D51 -- A key-down bitmap, not the C64's single byte

`INKEY` is a queue and cannot answer a game's question. A held key
arrives once and then not again until auto-repeat, and a queue names one
key at a time, so left-and-fire is not expressible in it. The C64 hit
this exactly: `GET` reads the buffer, so games read `PEEK(197)` instead
-- the key currently down -- and then dropped to reading the CIA
directly when *one* key turned out not to be enough either. The BBC
asked about one key at a time with `INKEY(-n)`.

COOL8's keyboard delivers make and break codes, so **16 bytes of bitmap
answers for all 128 keys at once**, which is the thing neither machine
could do. `scancode` sets a bit on every make and clears it on every
break; `KEY(c)` tests one. Measured: `kdbit` 54 bytes, `kdclr` 32,
`kdset` 29, eight bytes of mask table, 16 of RAM -- 139, all of it in
BASIC and one byte of it in the ROM. In the interrupt it is about 15 us
per key pressed and released, or 0.015 % of the CPU at ten keys a
second.

**The argument is a raw Set 2 scancode**, not ASCII. This asks about a
key and not about a character: shift is a key, the cursors are keys, and
`$1C` is the one under your left middle finger whether or not it is
currently producing an `A`. Reversing the keymap to accept `KEY(ASC("A"))`
would have cost a 128-byte scan per call and still needed a separate
spelling for the cursors, which share their codes with the keypad. The
cost is that the codes have to be looked up, so
[04-system.md](04-system.md) section 4.3 lists the ones a game reaches
for.

With no keypad on this machine an `$E0`-prefixed key shares a bit with
the keypad key it shares a scancode with. That is not a collision: only
one of the two can be pressed.

---

---

The architecture is settled. Anything that reopens it now needs new
evidence of the same kind: real code, measured, not an argument.

## D52 -- The operating system is COOL8 BASIC, and how it got that shape

The OS-shape survey (once `docs/09-os-options.md`; in git history)
weighed a monitor-plus-loader, a Forth, and several BASICs, and chose:
the C64's screen-editor shape (one screen, a cursor, Return -- no
modes, no panes), the fake-disk flash filesystem (16 volumes,
append-only directories), autoboot from `$100000`, and **native
compilation on the Action! model** -- structured, QBasic-shaped, no
line numbers.

Half of that survived contact. The editor shape, the filesystem and
the boot path shipped as chosen. The native compiler was built,
benchmarked, and **lost to the interpreter on size**
([11-compiler.md](11-compiler.md) has the arithmetic that shelved it);
the language became the line-numbered, tokenised interpreter of
[13-basic.md](13-basic.md), and the structured compiler survives as
`tools/cool8bas.py`, which compiles the system itself. The survey's
other casualty: its memory map put the stack at `$FF00-$FFFF`; the
shipped machine keeps the stack in page 1 and `$FF00` became the
interpreter's workspace page.

## D53 -- The cursor position is frame-latched, like VID_BASE

The pixel stage sampled `CUR_X`/`CUR_Y` live, so a move mid-frame drew
the block at the old column on the lines already scanned and the new
one below -- a torn cursor for one frame, on every machine with a
live-sampled hardware cursor since the CRTC, and invisible on the
phosphor those machines assumed. An LCD holds the frame, and the
scanline-accurate emulator faithfully shows what the silicon does, so
backspace under key repeat reads as tearing.

Three places could fix it. **Doing nothing** is period-correct, and
was the standing answer while the artifact lived only in principle.
**Software** -- the vblank ISR mirroring the cursor registers, written
only on change so the blink phase survives -- costs ~24 bytes against
a 24-byte ceiling and fixes only the editor: a game drawing its UI
with the hardware cursor tears on its own. **Hardware** latches the
displayed position (and the blink-phase restart with it) at
`frame_start`, exactly the arrangement `VID_BASE` already has and for
the same reason: a change the raster is mid-way through showing
should land on the next frame, whole. Reads are untouched -- software
sees the value it wrote, immediately.

Measured, not estimated: `cool8_vregs` alone goes from 337 LUT4 /
173 FF to 330 LUT4 / 186 FF -- **+13 flip-flops and 7 LUTs returned**,
the blink mux coming out simpler than the immediate-reset form it
replaced. Style and `CUR_LINES` stay live: they change when software
sets a mode, not per keystroke, and latching them buys nothing a
frame of settling does not.

The renderers follow the silicon: rust/src/render.rs latches the
cursor at its frame event; cool8vid.py renders whole frames from a
snapshot and could never show the tear in the first place -- which is
why the artifact went unseen until the scanline renderer existed to
show the truth.

## D54 — Storage stays sixteen mounted volumes; the disk box was considered and declined

**Decision:** `SAVE`/`LOAD` storage stays exactly as
[D52](#d52--the-operating-system-is-cool8-basic-and-how-it-got-that-shape)
shipped it — sixteen 448 KB volumes above the flash floor, one mounted
at a time, selected by `DRIVE n`. The period-styled alternatives were
worked through to a full design and declined; this entry records the
workings so the next reopening starts from them rather than from
scratch.

**The itch is real.** The 448 KB volume is the last piece of the
machine that matches no hardware of its era: a 1541 held ~170 KB, an
IBM single-sided 5.25" exactly 160 KB. The design worked out was a
**disk box**: treat the 7 MB as a caddy of diskettes — 44 × 160 KB, or
37 × 192 KB keeping the 64 KB alignment — with one or two drives, a
`DISK drive, n` statement that "inserts" a disk, and a `"1:"` name
prefix to address the second drive (in the name string, because
`LOAD`'s comma argument already means merge-from-line). Hardware
drive-select was never on the table: the mapping is two bytes of
software state, and gates are the scarce resource
([D34](#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter)).

**Why declined: it collapsed under its own simplification.** Two
drives shrank to one — a single-user machine swaps disks, and the
second drive bought nothing but the prefix parser. And at one drive
the disk box *is* the shipped design: "insert disk n" and "mount
volume n" are the same operation, and nothing in `sw/fs.asm`
distinguishes a box of sixteen disks in one drive from sixteen drives
with a disk in each. The difference is narration, and narration went
into [04-system.md §8](04-system.md#8-mass-storage-the-filesystem) —
which this decision caused to be written — instead of into code. The
last candidate standing, renaming the keyword `DRIVE` to `DISK`, was
staged and reverted too: the spelling is free (the token byte is the
table *position*, and toktab.asm appends and never reorders), but it
would invalidate every listing in every document for one word.

**Findings worth keeping although nothing changed:**

- **The geometry is cheaper to change than fs.asm's header implies.**
  Any volume size that is a multiple of 4 KB keeps the base's low byte
  zero, so the one-add file addressing degrades only to `ADD`+`ADC` in
  the three seek routines — and the base itself is computed once, at
  mount, where even an awkward multiply is paid per disk swap, not per
  access. 192 KB = 3 × 64 KB would keep the pure one-add form: the 7
  in `fs_mount`'s base formula becomes a 3 and nothing else moves.
- **Autoboot never cared.** It reads volume 0 at `$100000`, which
  every variant kept, so `sw/boot.asm` was untouched in all of them.
- The host tool's box-management commands — volume-to-volume copy,
  import/export of a single 448 KB volume image — are orthogonal to
  all of this and remain worth having on their own.

**What reopens it: a real drive.** If pins and gates ever admit real
removable media — doubtful on this board, undecided beyond it — the
drive/disk distinction returns as a drive-to-device table in software,
and the `"n:"` prefix syntax above is the shape to reach for. Nothing
shipped today blocks it.

## D55 — The suites and cosim's model run on the Rust machine; Python stays the specification, for now

**Decision:** the software suites and cosim's model side run on
`cool8rs`, the Rust machine, through `tools/cool8rsvm.py`'s session
and batch clients. This entry records the migration; the Python
reference it was gated against was retired hours later, in the same
session, once the last three consumers had somewhere to go —
[D57](#d57--the-python-machine-is-gone-rust-is-the-machine-and-the-rtl-is-its-gate).

**Why now, measured:** CPython steps this machine at ~0.5 M instr/s
against the Rust machine's ~66 M. On migration day: the sw suite
823.8 s → 185.7 s wall (`test_run` 823.7 → 183.7, `test_basic` 177.9
→ 2.9, `test_fs`/`boot_basic`/`autoboot` to under 1.5 s each), and
`cosim all` at 55 s with the model side reduced from most of the time
to seconds — the vvp is the bottleneck now, which is the correct
bottleneck.

**How the boundary held:** the rule from the original port —
machine-API granularity or coarser, no per-access FFI — produced the
session protocol: one persistent machine per `+serve` process,
commands mirroring the Machine API, and `settle` (the suites'
per-instruction idle poll) server-side as one command. Two findings
worth their bruises: `romen` is machine state and must round-trip
with the registers (a client pushing its stale copy re-enabled the
ROM overlay the flash stub had just dropped, mid-boot), and
`Machine.settle` had to exist on both machines so a suite keeps one
code path.

**What was still on the reference when this was written** — the
profiler, the SP high-water case, and the render gate — is what D57
had to move, and did. `tools/cool8run.py`, the pygame window, is
already gone: `rust/src/emu.rs` superseded it feature for feature and
`poe emu` launches it.

**Rejected:** porting the assembler, compiler or host tools to Rust —
they are seconds of I/O-bound scripting, they read `opcodes.py`
natively, and porting them buys nothing but a second copy of the
single-source tables. Python stays the scripting layer; Rust is for
the one thing Python is slow at here, which is being the machine.

## D56 — The runner is pytest and the manifest is pyproject.toml; Node is gone

**Decision:** `package.json` and `tools/run.mjs` are deleted. The job
table, the project config (`[tool.cool8]`) and the command aliases
(`[tool.poe.tasks]`) live in `pyproject.toml`; **pytest** with
pytest-xdist is the suite runner, fed by the one policy-free shim in
`sim/runner/test_jobs.py`; **poethepoet** names the direct commands.
`tools/board.py` and `tools/doctor.py` read the config with stdlib
`tomllib`. Checked against the 2026 landscape before choosing: poe is
a current, maintained standard for pyproject task-running (the
uv+poe pairing is documented practice), pytest is uncontested, and
the smaller alternatives (uv-script, pyproject-runner, taskipy) are
the same idea with fewer users.

**Why:** Node's entire role was naming commands and fanning out
subprocesses — package.json said so itself. That is pytest's day job:
`-n auto` is the parallel pool, a marker is a group, `--durations` is
the timing report, and the exit code gates a commit. One toolchain
fewer on a fresh clone; the per-job build directory
(`COOL8_BUILD=sim/build/jobs/<group>-<id>`) and the "exit 0 AND no
FAIL in the output" pass rule are kept, in the shim, verbatim.

**Rejected:** hand-porting `run.mjs` to Python — a bespoke runner is
the wheel pytest already is; and `uv` as a hard dependency — worth
adopting for env management some day, but it changes installation,
not this shape, and plain pip works today.

## D57 — The Python machine is gone; Rust is the machine and the RTL is its gate

**Decision:** `tools/cool8emu.py`, `tools/cool8vm.py`, `tools/cool8vid.py`
and `sim/rustsim.py` are deleted. `rust/` **is** the COOL8 machine.
Nothing falls back: without `cargo` there is no machine and the suites
say so. [D55](#d55--the-suites-and-cosims-model-run-on-the-rust-machine-python-stays-the-specification-for-now)
had moved the suites and cosim onto it hours earlier and left the
Python side standing as a second opinion; this finishes the job the
same session.

**Why not keep it as a second opinion.** Because a reference nothing
runs is a reference nobody notices going stale — and it was already
costing: two models to change per ISA change, a `COOL8_PYVM` path with
no coverage, and a render model (`cool8vid`) whose whole-frame
snapshot could not express what the machine now does per line
([D53](#d53--the-cursor-position-is-frame-latched-like-vid_base) was
found *because* the scanline renderer existed and it could not show
it).

**What kept the honesty.** The property that made the emulator
trustworthy was never that it was Python; it was
[D44](#d44--there-is-one-emulator-and-it-is-gated-against-the-rtl-not-against-itself)'s
rule — one model, gated against the *RTL* rather than against itself.
That rule is untouched. Two independent statements of the semantics
still exist and are still diffed instruction by instruction: the
Verilog, and `rust/src/`. The count did not change; the language did.

**The three things that had to move first**, all of them
per-instruction observation that cannot cross a pipe a tick at a time,
and all now server-side commands in the `+serve` protocol:

| was | is |
|---|---|
| `Machine.profile`, read by `dbg.Profile` | `profon`/`profdump` — cycles by PC; label attribution stays in Python, where the symbol table is |
| `test_interp`'s SP high-water loop | `spmin`/`spclr` — the machine's own low-water mark |
| the render gate: RTL frames → `cool8vid` → `render.rs` | RTL frames → `render.rs`, **directly**. `sim/test_vm.py` replays the testbench stimulus through the machine and compares its scanned-out frame per pixel |

The render gate is the one that mattered, and it came out *shorter*:
the chain lost a link rather than gaining one, and the stimulus is
still transcribed by hand from `cool8_video_tb.v` so a misreading of a
register has to be made twice, identically, to pass. 307,200 pixels ×
three frames, 4096 sound samples, and the boot conversation, all clean
on the first run after the swap.

**A gate that could not run was passing.** `poe test-rust` went green
in 0.19 s having compared nothing: every runner job gets its own
`COOL8_BUILD`, so `test_vm.py` looked for the RTL golden dumps in a
directory only a sibling job writes, found none, and counted the
absence as a skip. It now searches the shared build and every job's,
and **a missing golden is a failure** — a check that cannot run has
not passed. Worth stating as a rule, because per-job build directories
make it a trap any suite reading another's artifact can fall into.

**Casualties worth naming.** `sim/rustsim.py` compared two models and
had nothing left to compare, so it went; `poe test-rust` now runs
`sim/test_vm.py`, which asks the RTL instead. `sim/test_lib.py`'s
hand-written bus — a *third* implementation of the I/O page, written
only to fake a permanently-ready vblank flag — went with it, and the
suite now reads the machine's own state through `pald`/`sprd`/`sndd`.
Rewriting it turned up that its gate had been measuring nothing since
the machine grew real vblank timing: both versions are frame-locked, so
frames-per-clock is 1.00x by construction. It now measures **work per
frame**, the clocks spent outside the spin, and at that measure the
BASIC demo is 2.48x the assembly against a 2x tolerance — a real
failure the old shape could not see. Left failing, deliberately: the
number is the finding.

**What Python keeps**, and this is the line D55 drew and this entry
does not move: the assembler, the compiler, `opcodes.py` and the
generators, the disk tool, the board tools, the harnesses themselves.
They are I/O-bound scripting measured in seconds, and `opcodes.py` is
the encoding's single source of truth with `mkrsopc.py` generating the
Rust table from it. Python is the scripting layer. Rust is the machine.

## D58 — The suites get a harness and a toolchain module; the tools themselves were already right

**Decision:** two modules, `sim/harness.py` (build, check, report,
paths) and `sim/toolchain.py` (iverilog, yosys, the RTL file lists),
and every suite uses them. No redesign of anything else: the tool
layout was audited and found sound.

**What the audit found.** Every tool has real consumers and one job;
`opcodes.py` single-sources the encoding with a generated Rust table
and a drift gate; the write-it-twice pairs (`fs.asm`↔`cool8disk.py`,
`rtl/`↔`rust/`) are evidence rather than duplication; the job table had
no broken references. The problem was not the shape, it was that
**nothing shared the parts that every suite needs**:

| had copies | now |
|---|---|
| `check()` + `FAILS` — **13**, byte-identical | `H.check`, `H.report` |
| compile → assemble → read symbols — **6**, each spawning `cool8asm.py` | `H.build_bas`, `H.compile_bas`, `H.assemble_text` |
| the `HERE`/`ROOT`/`BUILD` preamble — **26** files, 142 lines | `H.ROOT`, `H.BUILD`, `H.SW` |
| the `CORE` Verilog list — **4**, identical | `T.CORE` |
| the disk builder — **2** (`flash.py`, the emulator launcher) | `flash.build_disk` |

**The assembler was being run as a subprocess by eleven files** even
though `cool8asm.assemble()` returns the image and the symbol table
directly — `sim/test_corpus.py` had used the API for years and nobody
else noticed. Each call cost an interpreter start and a file round trip
to reach the same answer; the disk build measures 0.5 s now.

**The toolchain layer already existed — inside `cosim.py`, reached by
its private names.** Ten suites called `cosim._tool`, `cosim._build`,
`cosim.ice40_cells`. When ten modules use your underscore names the
layer wants to be a module, and until it was one, a PS/2 test could not
run without importing the CPU co-simulation gate.

**Two orphans, both the shape of the silent-skip in
[D57](#d57--the-python-machine-is-gone-rust-is-the-machine-and-the-rtl-is-its-gate).**
`sim/test_snd.py` writes `build/snd.hex`, the golden `test_vm` gates
the sound engine against — and it was in no group, so nothing
regenerated it: change the sound RTL and the gate compares against the
old dump and passes. `sim/test_lib.py` was reachable from no command
and documented nowhere, unlike the four suites deliberately excluded.
Both are in their groups now. **`test_lib` fails there**, at 2.48x
against its 2x tolerance — a real, pre-existing failure that was
invisible precisely because the gate ran nowhere.

**M14's gate was measuring the wrong thing, and then it was fixed.**
It divided *every* non-spin clock by the frame count — folding setup,
which happens once and is half the assembly version's total, into a
figure called "work per frame". Both versions were flattered,
unequally. The profiler is now started where setup ends (the sprite
table stops being all zero), so the number is the loop and only the
loop, and setup is reported beside it.

On the honest measure the demo was **2.53x**, and two language-level
fixes to `sw/demo.bas` took it to **2.30x**:

- **`AND 255` on a `BYTE` is dead code.** It appeared six times per
  sprite per frame and compiled to `MOV R2,#255` + `AND R0,R2` each
  time — the add already wraps in eight bits and the store to a `BYTE`
  truncates. The compiler does not know that; a person reading the
  generated assembly does.
- **Write back only what changed.** The step `sdx`/`sdy` changes only
  on a bounce, perhaps every fiftieth frame, and an array store is five
  instructions. Moving those two stores inside the bounce arms costs
  nothing and saves them the rest of the time.

The tolerance moved to **2.7x**, and this is the point: it had been 2x
since the commit that introduced the demo, set by hand, and appears
never to have passed. 2.7 is the measured 2.30 with headroom for
noise — a number with a profile behind it rather than a hope. What
remains of the gap is what the language costs here: a `CALL` per
sprite into the library's sprite writer, four 16-bit parameters
pushed for it, and every array access recomputing its address.

**And a trap in the command list:** `poe console` and `poe load` talk
to the hardware loader, which `LOADER` defaults to 0 for
([D40](#d40--the-hardware-loader-is-a-build-option-and-it-is-off)), so
on a shipping board they reach nothing. They now say so, and point at
`poe board-screen`, which reads the screen through BASIC and needs no
loader.

**`poe emu` runs what is on the shelf.** It boots `build/cool8.img`
and builds nothing; `poe disk` builds. An incremental rule was written
and thrown away: deciding *when* a source counts as newer is exactly
the kind of rule that quietly boots a stale image, and the failure
looks like the change you just made not working. Two commands, no
heuristic.

**The rule that came out of it**, now standing rule 4 in AGENTS.md:
investigations and experiments go through the harness, never a
throwaway script. A private copy is not a shortcut — it is a second
implementation nobody is checking, which is how `test_lib` came to
measure two programs against a third, private model of the I/O page
and report 1.00x for a year.
