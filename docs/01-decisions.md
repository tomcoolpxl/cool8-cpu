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

> **The register is kept; the 128×32 map is superseded by
> [D70](#d70--the-user-area-is-one-region-of-40448-bytes).** The map is
> 80×32 at a stride of 160 — 5,120 bytes — because
> [D69](#d69--the-map-is-derived-end-to-end) gave the fetch engine an
> explicit map origin, which lifted the power-of-two stride and the 8 KB
> alignment together. The reasoning below is still why `VID_STRIDE` is a
> register; what it got wrong is treating "a power-of-two stride" and
> "one add per row" as the same requirement. They are not: 160 = 5·32,
> so `r·160` is three adds and a shift, all eight-bit, and X is never
> spilled. See `con_row` in `sw/console.asm`.

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

**The first row of that table is where this went wrong**, and [D70] is
the correction: a 160-byte stride needs a `MUL` only if you ask for the
product directly. Factored as 5·32 it is three adds and a shift, the
partial product fits in a byte for all 32 rows, and X is untouched. The
row count is a free choice — 32 rows at stride 160 keeps the two spare
rows *and* costs 5,120 rather than 8,192.

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

### Should the core's fetch path be pipelined? — priced, still open

The arithmetic this question was waiting on has been done. **CPI is
2.59, so the upside is +8 % and it is collected only if the pipelined
design closes at 12.5625 MHz; below that the machine is 28 % slower.**
What settles it is a ten-minute synthesis probe, not a rewrite —
[D59](#d59--cpi-is-259-and-pipelining-the-fetch-is-a-bet-rather-than-an-optimisation)
describes it.

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

## D54 -- The restart chords are decoded in the keyboard, not in software

The machine had no way back from a wedged program. `SW[0]` reaches
`NMI`, which BASIC now handles, but a game may take that vector; and
**the board has no reset pin at all**, so the only true recovery was
the power switch.

Software cannot fix this by itself, and that is the whole argument. A
chord BASIC watches for is invisible exactly when it is needed: a
program that has disabled interrupts, taken the vectors and stopped
reading the FIFO cannot be asked to restart. Decoding it where the
bytes arrive cannot be masked, intercepted or ignored.

So `cool8_ps2` tracks Shift, Ctrl and Alt across break codes and
raises two outputs: **Ctrl+Shift+Esc restarts `cool8_top`'s power-on
stretch** — indistinguishable from switching the machine off and on,
and it survives anything software can do — and **Ctrl+Esc raises NMI**
and latches a flag at `KBD_MOD` bit 3, so the warm restart is a
request BASIC honours by putting the editor back without losing the
program. A program that takes the NMI vector swallows *that* one,
which is the price of a warm start being a software idea.

The modifiers come out at `$FE44` because the tracking exists anyway:
games get "is Ctrl held" in one read instead of walking `kdbit` three
times, and the editor can grow shortcuts with no state to keep. **They
are not usable for character translation** — they say "now" and the
FIFO says "earlier", so a queued byte must still be translated with
the in-stream shift `sw/kbd.asm` tracks. Recorded here because it is
exactly the mistake the register invites.

**Measured, and it is not cheap.** 5022 logic cells became **5164 of
5280 — 95 % to 97 %**, so the pair cost **142 LC of the 258 that were
left**. The LUT4 delta was only +46; packing is why the estimate made
from it was 2.4x optimistic, and why LC is the number
[00-goals.md](00-goals.md) says to quote. Timing is unchanged at
11.90 MHz against the 8.38 required. `synth_ice40 -abc9` and `-relut`
were both measured on the whole design and returned **exactly the same
5164** — there is no free area in the flags, so anything further has to
come out of the design.

The software side is 68 bytes: BASIC's NMI handler asks which chord it
was and the editor's loop does the warm restart. 26 bytes are left
below the I/O page.

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

## D81 -- One divisor, because a console row is always 16 display lines

**The cursor was on the wrong row in modes 2, 4 and 5, and half height
in all four doubled modes.** Reported from the machine and measured off
the rendered frame: with `CCY` at 29 the text was at display rows
464-479 and the cursor at 232-239, eight lines tall instead of sixteen.

`d1_trow` chose its divisor on the line doubler:

```verilog
d1_trow <= c_vdbl ? {1'b0, vsrc[7:3]} : vsrc[8:4];
```

so a cursor cell was 8 display lines in modes 2, 4, 5 and 6 and 16
elsewhere. **There was nothing to choose.** Every mode's console row is
16 display lines -- 30 rows over 480 in modes 0-4 and 6, 24 over 384 in
mode 5 -- because the doubler stretches source lines to fill the screen
and the console halves its glyph height to match. The *display* pitch of
a row never changes. One divisor:

```verilog
d1_trow <= vsrc[8:4];
```

### The first fix treated the symptom, and cost more everywhere

It scaled `CCY` by a per-mode shift in a new seventh `GEOMTAB` column,
and needed a sixth bit in `CUR_Y` to hold the doubled row -- 29 doubled
is 58. That put a load, a test, a branch and a shift into `con_cursor`,
which runs on **every cursor move**, and widened `cury_r`, `cury_d`,
`cur_y`, `c_cury`, `d1_trow` and `d2_trow`. It bought a correctly placed
cursor that was still half height, because scaling the row number cannot
change the cell's height.

Removing the choice removes all of it: `CUR_Y` is five bits again,
`con_cursor` is four instructions with no arithmetic, `GEOMTAB` is six
columns wide, and the cursor is full height in all seven modes.

### It costs 62 cells, and that is measured rather than argued

| | cells |
|---|---|
| the mux, half-height cursor | 5,121 |
| six-bit `CUR_Y` and a software shift | 5,143 |
| **one divisor, full-height cursor** | **5,183** (98 %, 97 free) |

**Removing a mux made the design bigger**, which is the opposite of what
the netlist says should happen, and reverting only that one line put
5,183 back to 5,121. At 96-98 % occupancy the packing is evidently
sensitive to it in a way the source does not show. Recorded because the
next reader will assume the simpler expression is also the cheaper one,
and here it is not -- and because it is the price of a cursor that is
the right size, which is not negotiable against 62 cells while 97
remain.

### Both models were wrong, identically, and the gates agreed

`render.rs` computed `if vdouble { vrel >> 3 } else { vrel >> 4 }` --
exactly the RTL's mux -- so `sim/cosim.py` and `sim/test_vm.py` compared
two implementations that shared the mistake and found nothing.

**This is [D74]'s note arriving in person**: gating two implementations
against each other catches a disagreement and cannot catch a shared
assumption. A person looking at the screen caught it. `m.fb()` localised
it -- two frames a blink apart differ in exactly the cursor cell, which
isolates it without knowing the invert rule.

### The test asserts the answer, not the table

`sim/test_main.py` walks all seven modes. The obvious check --
`CUR_Y == CCY << CCURSH` -- compares the console with itself, and a
table of zeros passes it in every mode, which was the bug. The invariant
is written out instead and is now simply **`CUR_Y == CCY`**, in every
mode, which is what having nothing to choose means.

It reads `CUR_Y` through `bus.read`, not `bus.mem`: the register lives
in the video block and RAM at that address answers 0 in every mode,
which looks like a broken cursor rather than a broken test.

### Two faults this did not touch

**Mode 6 draws 8-line glyphs**, so its text fills 240 of 480 lines and
its cursor now overhangs it. 30 rows over 480 is 16 display lines, so
the glyph height is what is wrong -- `bglyph` draws `CFROW` source rows
and modes 4 and 6 both say 8, yet mode 4 comes out 16 display lines.
The difference is in the bitmap row arithmetic, not confirmed here.

**Mode 5 has 24 rows and the console does not clamp `CCY`** when the
mode narrows, so a cursor left at row 29 is off its screen entirely.

---

## D80 -- Five keywords, and the seventh significant character

**212 bytes for all five**, and the image went 18,861 to 19,073. [D79]'s
sixteen palettes cost nothing; these cost something, and [D72] is why
that is a sentence rather than a problem -- the ceiling is a slider and
it was slid.

[13-basic.md](13-basic.md) section 12 asked which absences were
decisions and which were gaps. These were the five gaps small enough
that the language looked unfinished without them.

### Each one is a shape the code already had

Not five features -- three existing shapes and one new parser branch.
The exercise was to find which:

| | is | cost |
|---|---|---|
| `STOP` | `ipoll`'s own tail, given a label | **1 byte** |
| `VPOS` | `POS` with the other byte, sharing its tail | 5 |
| `TRUE` / `FALSE` | one tail, two starting bytes | 10 |
| `PI` | a constant beside `KPI2`, loaded and returned | 12 |
| `STRING$` | `sappend` in a loop | ~60 |
| `INPUT` prompt, `? `, and a list | the prompt is new; the list is `h_read`'s walk | ~90 |

**`STOP` is the one worth reading twice.** The break key already had to
stop, remember where, and let `CONT` resume -- that is `ipoll`'s three
instructions after the flag test. `STOP` is the same event by another
name, so it is a label on that tail and the flag test above it inverted
to fall in. Writing it separately would have been a second answer to
"what does stopping mean", and the two would have drifted the first time
`CONT` changed.

**A `STOP` in direct mode stops with nothing to resume**, and no check
says so: `icsv` records a record outside `$0200..PROGEND`, which is
exactly what `h_cont` already rejects as stale.

### NSIG is seven, because a builtin's name is seven

`STRING$` did not fit. `isbuilt` matches an entry by comparing `NLEN`
against its length and then reading that many bytes out of `NBUF` -- so
at `NSIG = 6` the seventh compare read `NLEN` itself, found 7 against
`'$'`, and the entry could never match. Deterministically, silently, and
only for names of exactly the wrong length.

So the buffer grew, and with it the significant characters in a *user*
variable: `ABCDEFG` and `ABCDEFH` are two names now. That is the same
pressure that took it from five to six in [D45], one name later.

**`NENT` is derived now.** It was the literal 12 while `NSIG` was 6 --
one number in two places, agreeing until the day one of them moved,
which is this project's most expensive shape and the day had arrived.

### Page 0 moved by a byte; the map did not move at all

Page 0 was full to the byte, so `NBUF`'s seventh byte pushed the run
above it up one and `SDIG` had to leave. It went to `$0074` and
`memmap.check()` refused: that byte is `FSVARS`, in `fs.asm`, invisible
from `zp.asm`. The free run is `$00A4..$00D9`. **Three files claim page 0
and none of them can see the other two** -- the tool is the only thing
that knows, which is the whole argument for [D67].

Then the image outgrew its slack: 245 bytes between system storage and
`ORG`, against the 256 the check insists on. **Eleven bytes short.**

**The eleven came out of dead system storage, not out of the user's
region.** `CSTKBUF` had been a 32-byte reservation since the call stack
moved into user memory -- `zp.asm` said "dead" beside it in so many
words -- and it was holding the string accumulator 32 bytes higher than
it needed to sit. Deleting it drops `SACCBUF` and `FSPBUF` to `$B26A`
and the gap becomes 277. Nothing else moves.

`FREE` answers **39,424** before this decision and 39,424 after it. The
text map stays at `$9C00`, system storage stays at `$B000-$B389`, and
the bitstream is byte-identical to [D79]'s at 5,121 cells.

### The map origin is not free, and $9C00 is the cheap one

This was found the expensive way -- by moving the map first, which was
the wrong instinct and is now [a standing rule](../AGENTS.md) against
doing it again without asking. The measurement is worth keeping anyway,
because the next time the map genuinely has to move, the obvious choice
is the wrong one.

One full build each. The cell count comes out of synthesis and does not
depend on the placer's seed -- a four-seed sweep moves `pclk` and `sclk`
and leaves `ICESTORM_LC` exactly where it was:

| origin | cells | image growth room | `FREE` |
|---|---|---|---|
| **`$9C00`** -- where it is | **5,121** | 277 | **39,424** |
| `$9800` | 5,201 | 1,269 | 38,400 |
| `$9400` | 5,172 | 2,293 | 37,376 |
| `$9000` | 5,168 | 3,317 | 36,352 |
| `$8C00` | 5,164 | 4,341 | 35,328 |
| `$8800` | 5,157 | 5,365 | 34,304 |

The origin reaches the hardware as four constants in `cool8_vregs.v` --
two mode presets and two register resets -- and nothing else in the
design changes with it. Reverting only those four turned 5,172 back into
5,121, so the whole of the difference is constant folding in the video
address adder.

**`$9C00` is 36 cells cheaper than the best alternative and gives the
most memory**, which makes it the right place on both counts and a
coincidence nobody planned. `$9400` -- the arithmetically obvious "2 KB
down" -- is the *worst* of the five. So if the map ever must move: build
the candidates, do not subtract a round number. And ask first, because
every byte it moves comes off `FREE` one for one.

### What INPUT does now, and what it deliberately does not

`INPUT ["prompt";] var [, var]...`, and it prints `? ` where it printed
nothing at all before -- a program that blocks with no mark on screen
looks hung. A leading `"` is the prompt, which is the C64's rule and one
byte to test, so `INPUT A$` and `INPUT "X"; A$` stay apart with no
lookahead.

**A comma is another prompt on another line, not one line split on
commas.** Splitting is the C64's rule and drags `?REDO FROM START` in
with it -- too few items has to re-ask, too many has to complain, and
both need the accumulator cut up while `snum` reads it whole. A prompt
per item needs no policy at all, because a line that ends is one answer
by construction. It is `h_read`'s walk character for character, which is
the other statement taking a list of scalar targets.

### Two faults the obvious test would have passed

**`PI` printed 3.141 and ate the rest of the expression.** `fload`
writes through Y, so every float builtin brackets its call and leaves
through `frtn`; going straight to `fretf` skipped the restore. `PRINT
PI` was right, and `PRINT PI*2` printed 3.141, and `PRINT PI-4*ATN(1)`
printed 3.141 -- three ways of not noticing. The test that finds it is
`PI` with *something after it*.

**`STRING$`'s count is sixteen bits and its loop ran on eight.**
`STRING$(200,"yz")` correctly said `?STR LEN` while `STRING$(300,"yz")`
quietly returned 88 characters and `STRING$(256,"x")` the empty string.
The high byte is folded in now by clamping to 255, so an impossible
count reaches that same error by that same route rather than by a second
check that could disagree with it.

`PI - 4*ATN(1)` is **-6.1e-05**, one unit in the last place: the
constant is the more accurate of the two, which is the other reason it
is a constant.

---

## D79 — Sixteen banks of sixteen, and they are published palettes

**Done, and free.** [D77] put the palette in the bitstream and left
fourteen of its sixteen banks black. They are filled now, and the
bitstream measured **5,121 logic cells before and after** — a bank is
EBR INIT bits, and those were already being written.

**256 entries was never one palette.** A tile attribute's low nibble
selects a bank of sixteen, so the table is sixteen palettes and the bank
is the unit worth designing. Modes 0, 1, 4 and 5 read bank 0; mode 3
reaches only entries 0 and 1; mode 6 is the only one that sees all 256
at once.

**Bank 0's slots are load-bearing and the rest are free.** A text cell's
attribute is `bg[7:4] fg[3:0]`, so entry 4 of bank 0 must be the red a
program means when it writes 4 — that bank stays softened CGA and its
values are unchanged, byte for byte. Nothing indexes banks 1–15 by
meaning; a tile or sprite points at a bank and takes what is in it. So
those are chosen for how they look together, which is what a *designed*
palette is for and what CGA's semantics prevent bank 0 from being.

| bank | palette | author | source |
|---|---|---|---|
| 0 | Softened CGA | COOL8 | the boot ROM's, values eased |
| 1 | PICO-8 | Lexaloffle | [lospec](https://lospec.com/palette-list/pico-8) |
| 2 | DawnBringer 16 | DawnBringer | [lospec](https://lospec.com/palette-list/dawnbringer-16) |
| 3 | Sweetie 16 | GrafxKid | [lospec](https://lospec.com/palette-list/sweetie-16) |
| 4 | Endesga 16 | Endesga | [lospec](https://lospec.com/palette-list/endesga-16) |
| 5 | AAP-16 | Adigun A. Polack | [lospec](https://lospec.com/palette-list/aap-16) |
| 6 | Arne 16 | Arne Niklas Jansson | [lospec](https://lospec.com/palette-list/arne-16) |
| 7 | Steam Lords | Slynyrd | [lospec](https://lospec.com/palette-list/steam-lords) |
| 8 | Island Joy 16 | Kerrie Lake | [lospec](https://lospec.com/palette-list/island-joy-16) |
| 9 | Bubblegum 16 | PineappleOnPizza | [lospec](https://lospec.com/palette-list/bubblegum-16) |
| 10 | Commodore 64 | Commodore | [lospec](https://lospec.com/palette-list/commodore64) |
| 11 | NA16 | Nauris | [lospec](https://lospec.com/palette-list/na16) |
| 12 | ZX Spectrum | Sinclair | [lospec](https://lospec.com/palette-list/zx-spectrum) |
| 13 | MSX | Texas Instruments | [lospec](https://lospec.com/palette-list/msx) |
| 14 | CGA | IBM | the hard 0/A/5/F levels bank 0 softens |
| 15 | Greyscale | COOL8 | a linear ramp, for dithering and masks |

### Fetched, not remembered

Every one came from lospec.com rather than recall, and that was not
ceremony: **AAP-16 and Arne 16 both came back different from what I
would have written down.** The rule about saying "not confirmed" rather
than filling a value in from memory earns its place on palettes exactly
as it does on BBC BASIC's internals.

Two banks carry fifteen published colours because the hardware they
describe has fifteen — the Spectrum's BRIGHT black *is* black, and the
TMS9918's sixteenth entry is transparent, which over nothing is black.
Both lead with black and say so, rather than being silently padded.

### One quantiser, and it rounds

The 24-bit originals are what `tools/palette.py` holds; `q444` is the
only place a colour is converted, so "what did we change" has one
answer: nothing but the depth. It rounds rather than truncating —
`v >> 4` discards the low nibble and darkens everything by up to 6 %,
where rounding keeps white white. It also makes a bank authored *as*
twelve bits round-trip exactly, which is how bank 0 came through
unchanged and is the check that says the conversion is honest.

`python tools/palette.py --show` prints all sixteen with their authors
and sources.

---

## D78 — PAUSE, POS, NOT and CONT, and where a break can be resumed from

**Done.** Four keywords the C64 and the BBC both have and this machine
did not, found by diffing the generated vocabulary against the C64
manual's 71 keywords and BBC's own token table.

**`PAUSE n` waits n frames**, not milliseconds, because `frames` is what
the machine counts and what `TIMER` reports — so `PAUSE 60` and `TIMER`
measure the same second. It polls `ipoll` rather than spinning: a wait
that cannot be interrupted is a machine that has hung as far as anyone
watching is concerned, and this is the one statement whose whole job is
to take a long time. Measured exact at 0, 5, 30 and 60.

**`POS` reads the console's `CCX`**, not a count of what was printed, so
it is right after anything that moved the cursor — `PRINT TAB(10);POS`
gives 10. `TAB` already knew the number and nothing could ask for it.

**`NOT` is taken at `erel` and not in `prim`, and the level is the whole
decision.** Microsoft's precedence puts it below the relations and above
`AND`/`OR`, so `NOT A = 1` means `NOT (A = 1)`. `erel` is exactly the
relational level with `AND`/`OR` above it in `.more`, so taking `NOT` at
that entry gives the grouping for free; in `prim` it would bind tightest
and mean `(NOT A) = 1`. Recursive, so `NOT NOT x` is x, and since TRUE
is -1 ([D47]) the complement serves logic and bits with one operation.

### CONT, and why the depths travel with the position

`ipoll` is where the break flag becomes `?BREAK`, and **all four of its
callers are loop and branch back-edges**, each one `JMP stmt`
immediately after. So when it fires, `LREC` and `Y` already name the
statement that was about to run — `CONT` resumes exactly there rather
than somewhere in the middle of one. Nothing had to be added to find a
resume point; it was already the only place a break could be noticed.

**The five nesting depths go with it.** `idrct` resets `FDEPTH`,
`DDEPTH`, `EDEPTH`, `CDEPTH` and `FSP` for every direct line — and
`CONT` is a direct line. The FOR, DO, ELSE and CALL stacks still hold
their frames; only the counters saying how many would be zero by the
time `CONT` ran. Without them, continuing out of a loop is
`?NEXT WITHOUT FOR`. Measured: a break at A=6835 inside
`FOR I=1 TO 20000`, then `CONT`, and the program finishes with A=20000.

**It is validated against the program, not only against a flag.** The
ten-byte record lives above the name table, which is itself at
`PROGEND`, so editing the program *moves it* and the bytes read there
are whatever is in the heap. A saved `LREC` outside `$0200..PROGEND`
cannot be a statement of the program that is loaded now — which arrives
at the C64's "editing a line loses CONT" from the other end, and also
covers `NEW` and `RUN`, where `PROGEND` moves to `PROGBOT`. Four ways to
fail and all of them answer `?CONT`, its own error rather than `?CALL`,
which means "no such SUB".

### The bug that made PAUSE do nothing

`PAUSE` snapshots the frame counter in R2 and spins until it changes.
**`ipoll` returns the break flag in R2** — so the compare was against 0,
every iteration looked like a tick, and `PAUSE 30` waited zero frames
while a 4,000-iteration `FOR` took nine. It measured as working code
that returned instantly, which is the shape a timing statement fails in.

  18,570 → 18,861 bytes, 291 for the four.

---

## D77 — The palette is in the bitstream, and that bought 76 logic cells

**Done.** `rtl/soc/cool8_pal.v` reads its 256 entries at elaboration,
exactly as `cool8_rom.v` reads the boot image. Every software copy is
deleted.

**The block RAM came up zeroed** — 256 entries of black, *including
entry 0, which is the border* — so a machine that never wrote the
palette showed nothing at all. Three separate pieces of software wrote
one to avoid that: the boot ROM's sixteen, the flash stub's thirty-two,
and `sw/console.asm`'s one-entry override for mode 3. Three answers to
"what colour is blue", and the screen was black for the interval between
reset and whichever of them ran first.

### It is free, and then some — measured, not assumed

The palette is 256 x 12 bits = 3,072, which is one EBR of 4,096. **That
block is allocated whether or not it has contents**; only its INIT bits
change. So the expectation was zero cost. The measurement was better:

| | logic cells | EBR |
|---|---|---|
| software palettes | 5,197 / 5,280 (98 %) | 28 / 30 |
| **in the bitstream** | **5,121 / 5,280 (96 %)** | 28 / 30 |

**−76 cells**, and reproducible: the baseline was re-run and came back
at exactly 5,197, the new one at exactly 5,121. nextpnr is deterministic
at a fixed seed, so this is not placement noise — it was checked
precisely because 76 cells at 98 % occupancy is the kind of number worth
being wrong about.

### The objection that does not survive contact

"Baking it into the RTL means a resynthesis to change a colour." True,
and **the boot ROM is also in the bitstream** — `cool8_rom.v`
`$readmemh`s `boot.hex`, which yosys embeds. Changing the ROM's palette
table always required exactly the same rebuild. There was never a
flexibility difference to lose.

### One source, two generated copies

`tools/palette.py` owns the colours. It emits `rust/src/pal.rs` — which
is committed and drift-checked, the arrangement `tools/mkrsopc.py` has
for `optab.rs` — and stages `pal.hex` into the run directory for
whoever is about to elaborate, which is what `font.hex` and `boot.hex`
already do and why neither of those is committed either.

**The emulator had to be brought along or nothing would have caught
it.** `machine.rs` initialised `pal: [0; 256]`. Had the hardware shipped
a palette and the emulator not, both models would still have agreed with
*each other* on every golden frame, because software wrote a palette
over the top before any of them were captured — the shared-assumption
failure [D74] is about. `poe check` now refuses drift between the two.

### What was deleted

* The boot ROM's sixteen-entry table and its loop — **32 bytes of ROM
  back**, in the one part of the machine that cannot be reflashed.
* The flash stub's thirty-two entries and their loop.
* **Mode 3's entry-1 override.** One bit per pixel can only name entries
  0 and 1, so mode 3 draws in entry 1 whatever it is; the console used
  to force it to white. It is bank 0's blue now, dim against black and
  chosen rather than inherited. The check that guarded it was rewritten
  rather than deleted: entry 1 must still differ from entry 0, because
  *that* is the fault the override existed for — text that cannot be
  seen at all.

### The banks, which is what 256 entries actually are

In the tile mode the attribute's low nibble selects a **bank of
sixteen**, so the table is sixteen palettes and a bank is the unit worth
designing. Modes 0, 1, 4 and 5 read bank 0; mode 3 reaches only entries
0 and 1; mode 6 is the only one that sees all 256 at once. Bank 0 is
softened CGA — the slot *meanings* are load-bearing, since a text
attribute is `bg[7:4] fg[3:0]` — and bank 1 is PICO-8. **Fourteen banks
are still black**, and they are where a designed sixteen goes.

  boot ROM 3,511 -> 3,479 bytes. Logic cells 5,197 -> 5,121.

---

## D76 — Strings order, and it cost nothing because six copies became one

**Done.** `<`, `<=`, `>`, `>=` compare strings character by character;
the shorter of two otherwise-equal strings is the smaller, so
`"AB" < "ABC"`. `MID$` takes two arguments and runs to the end.

**Before this they silently answered false.** `IF A$ < "B"` on `"ABC"`
printed nothing: the ordering arms called `rhs`, which is the *numeric*
right-hand side, and compared whatever `R0:R1` last held. Not an error,
not a refusal — an answer, and the wrong one. The reference said `=` and
`<>` only, so it was documented; a documented silent wrong answer is
still a silent wrong answer.

### The first implementation was 98 bytes and the right one is zero

`scmp` became a three-way compare — `$FF`, `0`, `1`, which is `fcmp`'s
convention — and then each of `<`, `<=`, `>`, `>=` got an arm that
called it and tested the result. That worked, and it was **six copies of
one idea**: the four new arms plus the two `=` and `<>` already had.

The smaller shape is to notice that **a numeric relation ends in
`SUB R0,R2 / SBC R1,R3` and a branch on the sign**, and that a
three-way compare is exactly a number to feed that. `srhsn` stands in
for `rhs`: if the operands are strings it compares them, sign-extends
the answer into `R0:R1` and zeroes `R2:R3`; otherwise it *is* `rhs`. So
`A$ < B$` becomes `scmp(A$,B$) < 0` and every operator keeps the code it
already had — including `<=` and `>`, which swap their operands, because
swapping `cmp` against zero negates it and that is still correct.

| | image | 4,000 comparisons |
|---|---|---|
| before any ordering | 18,571 | 197 frames |
| four bespoke arms | 18,669 | 197 |
| **one `srhsn`** | **18,571** | **196** |

**Zero net bytes for all six operators**, because unifying them deleted
the duplication that was already there, and no measurable speed
difference. One call site per operator instead of six places for the
next one to be forgotten in.

### What the profile said, and why nothing was micro-optimised

The byte loop is **about 4 % of a string comparison** — 197 frames for
sixteen equal characters against 188 when they differ at the first — so
the expression evaluator is the rest. The first `scmp` pushed and popped
a register *per character* to keep the right-hand length alive; that was
removed, not for the 2 % but because it forced the mismatch path to
unwind the stack by hand on two exits, which is a balance to get wrong
rather than a speed problem. The length is recomputed once, at the end,
from the split already on the stack.

### `MID$` with two arguments

`MID$(A$, 7)` is the rest of the string, which is what both the C64 and
the BBC give and what every published program assumes. The count is not
optional in the parser: it is asked for only when a `,` follows, and
`strim` already clamps, so 255 is the whole rest of anything this
machine can hold. **17 bytes.**

---

## D75 — TAB and SPC are items, not functions

**Done**, and the smallest of the three language additions this
milestone: `PRINT "A"; TAB(10); "B"` and `PRINT "A"; SPC(5); "B"`.

**They are taken in `PRINT`'s item loop, before `eval`.** That is the
whole design decision. Written as *functions* they would have to return
something, and the evaluator has exactly three value shapes — an integer
in R0:R1, a float in FACC, a string in SACC — none of which is "I moved
the cursor and there is nothing to print". Every builtin returns a
value; these do not, so they are not builtins.

The consequence is that they mean nothing outside a `PRINT`, which is
also true on the machines this borrows from. Their `sttab` slots point
at `bad`, so `10 TAB(5)` on its own is `?SYNTAX` rather than a statement
that quietly does nothing.

**`TAB` past the cursor does nothing.** It does not wrap to the next
line and does not emit a newline: a `PRINT` that silently gains a line
break when one field runs long turns a misaligned report into a
scrambled one, and the misalignment is the more useful failure. Measured:
`PRINT "12345678"; TAB(4); "OVER"` gives `12345678OVER`.

`TAB` reads the console's own `CCX` rather than counting what it has
printed, so it is correct after anything else that moved the cursor.

  18,492 → 18,571 bytes, 79 for both.

---

## D74 — The map moved down a kilobyte, and its address lived in five places

**Done, and it is [D72] arriving.** The image reached **-188 bytes** of
room. D72 said the ceiling was a slider and priced the move at "forty
hand-written claims"; it was **64**, done by one script over the `;:`
annotations, and `--check` proved it. `room -188 -> 836`, the user's
memory 40,448 -> 39,424.

**The relocation itself was the easy half.** What took the session was
that the map's address turned out to live in five places, and each was
found by a different failing suite rather than by asking:

| | what it was |
|---|---|
| `tools/memmap.py` | declared - the one that is supposed to be in charge |
| `rtl/soc/cool8_vregs.v` | mode 0 and 1 presets, and the reset values of `base_r` and `maporg_r` |
| `sim/tb/cool8_video_tb.v` | its own preset copy |
| `rust/src/machine.rs` | **the VM's presets** |
| `tools/mkboot.py` | the stub's screen clear and its banner row, twice |

plus `SACCBUF` and `FSPBUF`, which carry no `;:` - deliberately, since
the filesystem's page buffer overlays the accumulator and a claim would
read as two owners - and so were invisible to the script that moved
everything else. `COMPACT` noticed, being the only thing that writes a
page through that buffer.

**The `rust/` one is the instructive failure.** The console wrote to
`$9C00` while the emulator's display read `$A000`, and *every suite that
compares the two models passed* - `cosim`, `test_vm`, `test_video` -
because both models were still consistent with each other. Two
implementations gated against one another catch a disagreement and
cannot catch a shared assumption. The screen filled with fragments of
the right characters in the wrong places, which is what sent five suite
runs looking for a software bug.

`poe check` reads the Verilog **and** the Rust now and refuses
disagreement, and `mkboot` derives the address rather than carrying it.
Both checks were made to fail before being believed. The Rust check is
scoped to the preset table and the reset values: a bare search for
`0xA000`/`0x8000` also finds the sound engine's bit masks, and a check
that cries wolf is a check that gets switched off.

### `m.watch` existed only in AGENTS.md, and now exists

Reaching for "who wrote this address" mid-fault produced an
`AttributeError`. AGENTS.md had documented `m.watch(lo, hi)` / `m.hits`
for as long as anyone could tell, and neither machine had it - **the
identical trap `m.trace` fell into**, written up in
[10-debugging.md](10-debugging.md) and evidently not enough on its own.

It is implemented: a shadow of the watched range diffed on the tick
wrapper the profile and the SP watermark already ride, so it needs no
change to the memory path every other command depends on, and it records
the PC *before* the instruction - the one that did the write, not the
one after. Answering "who wrote the garbage" in one run is what this
entry cost by not having.

---

## D73 — SUB and CALL take parameters, and LOCAL is the same mechanism

**Done.** `SUB name(p[,p])` ... `END SUB`, called `CALL name(a[,a])`,
with `LOCAL name[,name]` inside. Parameters are by value and of any
type; the parameter's own suffix decides, exactly as it does for a
scalar or an array element ([D71]).

**A parameter and a local are one mechanism** - save the variable's
current value on entry, put it back on the way out. That is BBC BASIC's
shape (its FN frame carries a *number of parameters*, read off the
disassembly) and it is nearly free here because every variable already
lives at a fixed address: A-Z resident, or a name-table slot. No new
binding, no scope chain, and **no cost at all to reading a parameter
inside the sub** - it is an ordinary variable at its ordinary address,
so the body runs at exactly the speed it ran at before. Recursion works
because each level saves its own: measured `4 3 2 1` going down and
`2 3 4` coming back, and `5! = 120`.

### The choices, and what each rejected

* **Formals saved, then arguments evaluated and assigned left to
  right.** So an argument naming one of the sub's own parameters sees
  the value already placed: `SUB F(A,B)` called `CALL F(1,A)` gives B
  the 1. Evaluating every argument first - what BBC does - avoids that
  and needs somewhere to hold them, which the single string accumulator
  cannot be: two string arguments would each have to reach the heap
  first, so passing two strings would allocate twice on every call.
* **`?TYPE` per argument**, one compare against `STYPE`, with an integer
  promoting into a float parameter exactly as `A# = 1` does. Nothing
  else converts.
* **32 frames and 256 bytes of saves, in the user's memory** above the
  name table. 416 bytes does not fit the image's slack and is nothing
  against 39,424 - and deep recursion then costs the user's memory,
  which is the honest place for it to cost. BBC puts its stack there
  too, descending from HIMEM.
* **A string parameter clears its descriptor before storing.**
  Otherwise `sstore` reads the *caller's* `maxlen`, decides the value
  fits, and writes into the caller's characters - which `RETURN` then
  restores a descriptor pointing at. Silent corruption of the caller's
  string. Clearing it costs one allocation per string argument per call,
  and nothing reclaims it until `RUN`; that is the price and it is
  written down rather than hidden.

### Four faults it exposed, all older than it

* **`SUB FOO` and the float `FOO#` were one name-table entry.**
  `subname` appended `#`, which is the float suffix, so whichever was
  written last won and `CALL FOO` jumped into the float's bit pattern
  and did nothing at all. `!` now, which carries no bit 7 in `ctab` so
  no identifier can end with it - the property that already makes `(`
  work for arrays. Three sigils, three namespaces.
* **Falling into `END SUB` ended the program.** A SUB returned only
  through `RETURN`; `END SUB` was a marker `h_sub` scanned for when
  stepping over a definition, so reaching one ran `END` and set
  `E_DONE`, with the sub's output already printed.
* **`FUNCTION` was a longer word for `SUB`** - it dispatched to the same
  handler and could not return a value. Retired the way `$A4` and `$C6`
  already are, `toktab.asm`'s own note: "a one-character entry nobody
  can spell holds the byte open", so nothing renumbers and a saved
  program still means what it said. The word is an ordinary variable
  name again.
* **`CLEAR` was missing.** BBC's name, not the C64's `CLR`, because
  `CLS` and `CLG` are BBC's and the three belong together - and because
  `CLR` sits one letter from `CLS` in a way that caused exactly that
  confusion while this was being specified. It is `RUN`'s variable clear
  without the run, split out of `irun` as `vwipe` rather than written
  twice.

### Three register clobbers, and what they have in common

Each cost a debugging round and each is the same shape - a routine
reading a byte into `R0` while `R0:R1` held the value in flight:

* `argpass` read `ERR` into R0 after popping the argument, so **every
  integer parameter arrived as 0** while floats and strings, which
  travel in `FACC` and `SACC`, came through perfectly.
* `argst` read `STYPE` into R0 at entry, one level down, with the same
  symptom after the first was fixed.
* `lstk` uses R0 and R1, and both `lpush` and `lunwind` had put the slot
  offset there - so **every save landed in slot zero** and the last
  value written came back at every level: `4 3 2 1` down, `2 2 2` up.

`FUNCTION` gone, `CLEAR` at `$C7`, `LOCAL` at `$C8`.

  17,859 -> 18,482 bytes, 623 for the whole of it.

---

## D72 — BASIC's size is not a budget to optimise against; the ceiling is a slider

**Decided.** The image had 462 bytes of room to grow and the previous
session's instinct was to hunt for bytes to make space for the next
feature. That is the wrong instinct here and this entry exists to stop
it recurring.

**Nothing about 17,832 bytes is a physical limit.** The machine has 64 KB
of flat RAM and the map is ours: the image is top-aligned under the I/O
page and grows *down* until it meets system storage, so the ceiling is
wherever we put system storage and the text map. Moving them down gives
BASIC more room and costs the user's program space, byte for byte. There
is no third party to negotiate with.

**So features are decided on their merits, not on whether they fit.**
40,448 bytes of user memory is already more than a C64 hands a BASIC
program, and a feature worth 2 KB of image is worth 2 KB of a region
that large. What is *not* acceptable is spending bytes on guards that
buy nothing ([D71] backs out 17 such), or leaving genuinely dead code in
— that is tidiness, not budgeting.

### What moving it actually costs, measured rather than assumed

Moving `SCREEN` from `$A000` to `$9C00` and rebuilding gives the user
1,024 fewer bytes and BASIC **exactly none**:

```
  the user's  39,424 bytes  $0200-$9BFF     (was 40,448)
  room           462 bytes                  (unchanged)
  $B000-$B3FF is a 1024-byte hole nothing claims
```

The map moved; system storage did not. Every claim in the region is a
hand-written address in the module that owns it — `CROWA = $B537` and
about forty more — so the image is still stopped at `$B400` and the
kilobyte is simply gone. **It passed every check at the time**, which is
the part worth fixing rather than remembering.

Two checks were added, and both were made to fail before being believed:

* **A hole between the top of the map and the lowest claim above it.**
  The packing check treats the screen as the region's floor and verifies
  what is above it is contiguous, which says nothing about that gap.
* **The RTL has to agree about where the map is.** `cool8_vregs.v`
  carries the address in the mode 0 and mode 1 presets and in the reset
  values of `base_r` and `maporg_r`, and `tools/memmap.py` carried a
  comment saying they "agree" — a hope, not a test, and the same shape
  as the I/O page before [`tools/ioregs.py`]. `poe check` reads the
  Verilog now. A check and not a generator: the RTL is normative for
  what the silicon does, so the right failure is "these disagree", not
  Python quietly rewriting a mode preset.

### What would make the slider actually cheap

The forty claims are the cost, and they are hand-written addresses only
because nothing generates them. Each already declares its size — 
`CROWA = $B537 ;: 2 the address of row CCY, cached` — so a module could
declare the size alone and let `tools/memmap.py` assign the address and
emit the equates, exactly as it already does for `SYSBOT`, `USERTOP`,
`SCREEN`, `CSTRIDE` and the image's `.org`. Then moving the region is
one constant and a regenerate, and this entry's title becomes true
without qualification.

That is not done. It is the obvious next step if the ceiling is ever
actually reached, and it is written down here so that the next reader
reaches for it instead of reaching for a feature to cut.

---

## D71 — Arrays carry their rank and their element type, and one dimension keeps its own path

**Done.** `DIM` took one bound and every element was two bytes. It now
takes up to three, and the element is an integer, a float or a string
descriptor.

**The typing was already there and nobody had used it.** `arrname`
appends `(` to the scanned name to make the array's key, and the
suffix is in the name before that happens — so `A(`, `A#(` and `A$(`
have always been three different entries in the name table. Nothing had
to be invented to tell them apart; what had to change was an ordering.

**The one thing genuinely in the way was two lines of dispatch.** Both
`prim` and `h_let` tested the suffix *before* testing for `(`, so
`A$(3)` read as the scalar `A$` with a subscript left over for whatever
came next to choke on. Typed arrays were impossible in this parser
however the storage was arranged, and it was three instructions.

### Why it is affordable

The scalar load and store routines take exactly what an element is:
`fstore`/`fload` want three packed bytes at X and take no Y at all,
`sstore`/`sload` want the four-byte descriptor at X, and an integer is
two bytes at X. `aelem` returns X on the element and the type in R2, so
**float and string arrays need no load or store code of their own** —
only a two-compare dispatch at each of the four sites.

### The index arithmetic never multiplies for the width

Widths are 2, 3 and 4, so scaling is a doubling, a doubling twice, or a
doubling and an add. `amul16` is reached only by the Horner step that
flattens the second and third dimensions, so **a one-dimensional array
of any type never multiplies at all**.

### One dimension has its own path, measured into existence

The general form carries a seven-byte frame, a dimension counter and a
Horner step a 1-D array never uses. Measured, that was **147 cycles an
access** more than the untyped version it replaced — 307 frames to 349
on 20,000 iterations of `A(7)=A(7)+1`. Two cheaper fixes were tried
first and are worth recording because they did almost nothing:

* **Peeling the first dimension out of the loop** and **making the
  bounds check non-destructive** (subtract, branch, add the same value
  back, rather than pushing all four registers around a compare). Both
  are strictly better and both stayed. Together they moved the
  measurement by less than a frame: about 36 cycles an access against a
  147-cycle gap.

The gap was the frame and the header, not the loop. A separate rank-1
entry — three bytes of frame, the count read straight out of the
header, no counter, no loop — costs **99 bytes** and brought it to 330
frames. **7.5 % over the untyped version**, which is what an array
knowing its own rank and type costs.

### What was refused, and why the refusals matter

* **Dimensioning twice is `?REDIM`**, the C64's answer. Re-allocating
  silently was the old behaviour and it abandons the block; with no
  garbage collector a `DIM` in a loop eats the heap and reports
  ?OUT OF MEM a long way from the cause.
* **A product that will not fit is `?OUT OF MEM` at `DIM`.**
  `DIM Z(400,400)` is 160,000 elements; a 16-bit count wraps to a block
  *smaller* than the bounds that are then range-checked against it, so
  every write past the wrap lands on the next thing in the heap. One
  divide against `65535 / count`, at `DIM`, where it is free.
* **Subscripts stay range-checked at run time**, per dimension, where
  BBC BASIC checks only at `DIM`. It costs a compare a dimension and
  keeps a bad index an error rather than silent corruption.

### `aelem` keeps its state on the CPU stack, and has to

`A(B(1))` nests — the outer call has parsed nothing when the inner one
runs — so scratch in the storage region would be the outer subscript,
and the outer *type*, overwritten by the inner. `h_dim` cannot nest and
does use scratch: ten bytes overlaid on `lwk`, which is `LINE`'s working
set, on the same argument `sw/prog.asm`'s command scratch makes. The
storage region is packed between the screen below and the CALL stack
above with nowhere to grow, so ten borrowed bytes are ten the user keeps.

### Two faults it exposed, both older than it

* **`esubs` left R2 undefined.** Harmless while nothing branched on it;
  with a type dispatch, a bad subscript could jump into `sload` with X
  on the multiply scratch. The failure path sets R2 to 0 now.
* **`h_leta` carried on after a refused subscript.** `aelem` fails
  before consuming the `)`, so the assignment skipped the wrong byte and
  `eval` reported `?SYNTAX` over the top of the `?INDEX` already set:
  `20 V(9) = 1` named the wrong fault. It checks ERR now.

  17,270 → 17,863 bytes, **593 for the feature**; room to grow 431.

---

## D70 — The user area is one region of 40,448 bytes

**Done.** [D69] deferred this on the grounds that the case for it was "a
program that does not exist yet". The case is not a program, it is the
cap: under two pools a program was limited to 31,350 bytes of text with
10,149 of heap sitting idle beside it, and an array-heavy program hit
10,149 with 31,350 idle. Neither number is reachable by the other, and
nothing the user can do moves the boundary.

**The move.** System storage went from *under* the user area to *above*
it, packed against the text map, and the map moved with it:

| | [D69] | now |
|---|---|---|
| page 0, CPU stack | `$0000-$01FF` | `$0000-$01FF` |
| **the user's** | `$0200-$7C75` **and** `$9400-$BBA4` | **`$0200-$9FFF`, one region** |
| the text map | `$8000-$93FF` | `$A000-$B3FF` |
| system storage, CSTK, SACC | `$7C76-$7FFF` | `$B400-$B789` |
| slack — the image's room to grow | none | `$B78A-$BB98` |
| the image | `$BBA5-$FEFF` | `$BB99-$FEFF` |
| I/O and vectors | `$FF00-$FFFF` | `$FF00-$FFFF` |

```
65,536
  -   512   page 0 and the CPU stack
  - 5,120   the text map
  -   906   system storage 618, CALL stack 32, string accumulator 256
  - 1,039   slack between system storage and the image
  - 17,255  the image
  -   256   the I/O page and the vectors
  =========
   40,448   the user's, in one region
```

**It costs 1,051 bytes and that is the whole price**: 1,039 of slack and
12 the image grew. The regions otherwise trade places and the totals are
conserved, exactly as [D69] predicted — it only estimated the cost low.

**The slack is not waste, it is a shock absorber, and this is the part
[D69] did not see.** The image is top-aligned and its origin is derived,
so it grows *downward*. Under the old layout the heap's ceiling was the
image's origin, so **every byte BASIC gained came straight out of the
user's memory**, silently, on every build. Now it comes out of the slack
first: BASIC can gain 1,039 bytes and `FREE` does not move by one. When
the slack runs out `tools/memmap.py --check` fails the build rather than
quietly eating user memory — and it warns at 256 bytes remaining:

```
only 173 bytes between system storage ($B789) and the image ($B836).
That is the growth room BASIC has left; move the map down before
adding to it.
```

**What made it possible** was [D69]'s map-origin register, which is why
that entry is not superseded so much as spent: with the alignment and
the power-of-two stride both lifted, the map is 5,120 bytes and can sit
at any address, so it could be packed against system storage instead of
sitting in the middle of RAM splitting the user's memory in two. A
128×32 map could not have been moved anywhere useful — 8,192 bytes has
only seven possible homes and every one of them is in the way.

**Forty claims moved and none of them by hand.** The `;:` annotations
are the claims and `tools/memmap.py` derives `SYSBOT`, `USERTOP` and the
image's `ORG` from them, so the repack is a change of constants plus a
regenerate. What it did surface was six numbers written down in a second
place — the stub's screen clear, `mkboot`'s banner row, `prg_free`'s
floor, `test_basic`'s row reader, the video testbench's preset, and
`flash.py`'s relocation target. Every one of them was a place the map
was recomputed rather than read, which is the failure `AGENTS.md` names
and this repository keeps paying for. The last of them shipped: the
suites passed for a full commit while `poe emu` executed the middle of
`sw/console.asm`.

---

## D69 — The map is derived end to end

> **The ceiling arithmetic below is superseded by
> [D70](#d70--the-user-area-is-one-region-of-40448-bytes)**, which did
> the repack this entry deferred. The derivation, the hardware change
> and the two rejected alternatives all stand — D70 is what the
> map-origin register was *for*.

**Decided, and this half of the layout work is finished.**

[D30] chose an 8,192-byte text map to display 80x30, and `$A000` was
written down as the image's origin when BASIC was compiled and 23,528
bytes. Both were right when they were made and neither was true any
more: the image is 17,243 bytes and the padding existed only so a mask
could work.

**Four things were derived rather than declared:**

| | was | is |
|---|---|---|
| the image's origin | `$A000`, a constant | `$FF00 - size`, generated into `sw/org.asm` |
| the system floor | `SYSBOT = irring` | the lowest claim anywhere, generated into `sw/sysbot.asm` |
| the text map's pitch | `<< 8` in five places | `CSTRIDE`, read from the image |
| the heap's floor | `$A000` | the top of the map, from `CSTRIDE * 32` |

**The hardware change that unlocked the last two.** `VID_BASE` carried
the map's address in its high bits and the scroll offset in its low
ones, and `base & ~mask` in `cool8_fetch.v` separated them -- which is
why the map had to be aligned to a power-of-two size, and why the stride
had to be one. The origin is its own register now, latched from the mode
preset and not software-visible, so a scroll moves `VID_BASE` and cannot
move it. **26 logic cells**, and both constraints lift at once: any
stride, any address. The map is 5,120 bytes.

Rejected on the way, with the measurement that rejected it:

* **Wrapping against `base` instead of an origin register.** 32 cells
  and it fitted -- and it wraps within `[base, base+span)`, so the map
  slides with the scroll rather than rotating inside it. Every row of
  the screen reads from the wrong address as soon as anything scrolls,
  at any stride. `sim/test_vm.py` passed throughout, because no golden
  scrolls; the editor broke on the third line typed.
* **Registering `base + span` to save a subtractor.** The obvious
  refinement, and it costs **36 cells more** (5,193 against 5,157):
  sixteen flip-flops and an adder maintaining them every cycle, against
  a subtractor yosys shares with the compare beside it.

**What the machine hands out after this entry, and why there is no
more:**

```
65,536
  -   512   page 0 and the CPU stack
  -   906   system storage 618, CALL stack 32, string accumulator 256
  - 5,120   the text map
  - 17,243  the image
  -   256   the I/O page and the vectors
  =========
   41,499   the user's
```

(That middle line read 1,418 when this entry was written, which made the
block disagree with its own total by 512. The claims are 618 + 32 + 256;
41,499 was right, and is `$0200-$7C75` plus `$9400-$BBA4` measured.)

At this point that was **31,350 of program text and 10,149 of heap**, in
two pools: the program grew up from `$0200`, arrays and strings grew
down from under the image. The two-pool arrangement is what stopped a
`DIM` competing with program text, which it did until the heap got its
own region.

**The remaining question is pools, not bytes, and it is not a memory
question.** Packing system storage above the screen would give one
contiguous region -- slightly *less* in total, because the regions
simply trade places and the totals are conserved by arithmetic. So it
buys flexibility for lopsided programs (35 KB of text, or 10 KB of
arrays) and costs a few hundred bytes and a relocation of forty claims.
Deferred rather than rejected: nothing about it gets easier or harder
later, and the case for it is a program that does not exist yet.

**That case arrived immediately, and [D70] is the repack.** The estimate
above is the one thing here that was wrong — the cost is not "a few
hundred bytes", it is 1,051, and what it buys is not hypothetical
flexibility but the removal of a cap a 32 KB program hits with 10 KB
sitting idle next door.

**What is genuinely still on the table** is the image, at 17,243 bytes
of the 24,037 that are not the user's. It is flat -- 470 labels, the
twenty largest spans are 28 % of it -- so a diet means giving something
up, and [13-basic.md](13-basic.md) section 10 sizes the candidates:
transcendentals 1,020, `COMPACT` 527, float formatting 408. Every byte
cut there moves the origin down and lands in the heap automatically.

---

## D68 — The system is six subsystems, not two languages; [D66]'s port gets a shape

**Done.** [D66] is right that `sw/basic.bas` has to go and wrong about
what it becomes. It plans a routine-by-routine port into one flat
program; this entry says the target is **modules by subsystem, each
entirely in one language, with the command handlers next to their
dispatch**. The porting work is the same work — it now has somewhere to
land.

`sw/basic.bas` is deleted. Nine modules, 17,314 bytes against the old
23,528 — **6,214 saved**, close to the ~5,500 this entry predicted, the
difference being that the compiled globals went too. The board boots
from flash to a keyboard on the new code and 19 suites pass.

Four things this entry got wrong, kept because they are the useful part:

* **The layering was upside down at one joint.** `fscmd` is above
  `interp`, not below: its handlers use `eval`, `cnext` and the `SKIPSP`
  macro, and a `fscmd` assembled first does not parse. Found by moving
  the handlers, not by reasoning about them.
* **"Handlers next to their dispatch" is half a rule.** The handlers
  belong next to what they *implement*; the dispatch belongs at the top.
  While `sttab` sat in `interp.asm` naming every handler, anything that
  wanted the expression evaluator pulled the whole image in — which is
  what forced four suites into private stub blocks.
* **A module boundary is not a test boundary.** Testing each module
  against stand-ins for the ones above it produced suites that agreed
  with each other and not with the machine: `con_putsn` was a recording
  stub, so nothing had ever looked at the screen. One image, `H.fresh()`
  and `H.drive()`, no stubs.
* **The storage floor cannot be an equate.** [D67] computes it and this
  port broke it twice — `SYSBOT = irring`, then `SYSBOT = CONT` — each
  time by adding a module that claimed lower. It is generated now.

### What the measurement changed

[D66] planned against a density ratio of **2.5-3x**, taken from
`sw/demo.bas`, which [11-compiler.md §5a](11-compiler.md) names as the
compiler's worst case. The two routines actually ported came in at
**5.4x** (`putn`, 266 -> 49) and **6.4x** (`number`, 193 -> ~30). At 5x
the 11,008 bytes of compiled editor are worth about **2,200 by hand —
some 8,800 recoverable**, against [D66]'s ~6,000.

`python sim/build_basic.py --waste` says where they go, and it is not
the algorithms:

| | | |
|---|---|---|
| moving data | 3,506 | **63.6 %** |
| arithmetic | 1,199 | 21.7 % |
| control flow | 767 | 13.9 % |

**Two thirds of every compiled routine is shuffling values between stack
slots and registers**, because `tools/cool8bas.py` has no register
allocator. That is the whole of the 5x, and it is why hand-writing wins
so much more than estimated.

**And why the compiler cannot be rescued cheaply**, which had to be
asked before committing to 12 KB of hand assembly: the same tool counts
what a peephole pass could provably remove — 23 store-then-reload pairs
of the same register and slot, and 217 conditional-branch-over-`JMP`
sequences the assembler's relaxation now makes unnecessary. **697 bytes
against 11,008.** A register allocator is a real compiler project and
[D11] shelved that already.

### The diagnosis: no boundaries, cut in half by a language line

`sw/interp.asm` calls **23 routines in `sw/basic.bas`** — `s_list`,
`s_new`, `s_dorun`, `s_savecore`, `s_dodir`, `s_deleterange`, `s_emit`,
`s_getkey` and the rest. So the split is not a layering:

| subsystem | dispatch | implementation |
|---|---|---|
| console — `emit` `putn` `cls` `getkey` | — | basic.bas |
| tokeniser | — | basic.bas |
| program store | — | basic.bas |
| **commands** — LIST NEW SAVE DIR RUN | **interp.asm `sttab`** | **basic.bas** |
| statements, expressions, variables | interp.asm | interp.asm |

**The language boundary runs through the middle of every subsystem.**
That is the real defect, and it is why [D66] reached for "make it one
program" — but a flat merge removes the language line without creating a
single boundary, and the file that results is 18 KB of assembly with no
stated interfaces.

### The shape

| module | holds |
|---|---|
| `console.asm` | the screen in all four modes, cursor, scroll, `emit`/`puts`/`putn`. The KERNAL layer |
| `kbd.asm` | keys and the serial line, into one ring |
| `token.asm` | tokenise **and** detokenise, over one table |
| `prog.asm` | the store: find, insert, delete, renumber, list |
| `edit.asm` | screen-as-document: read a row back, continuation lines, insert and delete |
| `interp.asm` | the language — and `h_list`, `h_new`, `h_save` become real handlers here |
| `fs.asm`, `fscmd.asm` | volumes, and the disk commands |
| `fp.asm`, `fpbas.asm` | floating point, unchanged |
| `main.asm` | boot and the prompt loop |

**Console first**, because all 23 crossings and every routine ported
after it call into the console, and because it is the most mechanical
code in the file — no parsing to get wrong.

### The token table is not frozen, and D65 was wrong to say so

[D65] recorded that `TOKTAB`'s order "fixes every byte after it and
programs on disk hold the old numbering". **There is no installed base.**
Every `.img` in `sim/build/` is generated by the suites; nothing outside
this tree holds a tokenised program. What actually depends on the
numbering is entirely internal, and every bit of it is a hand-written
copy of a position in `TOKTAB`:

- ~25 `K_*` equates in `sw/interp.asm` (`K_PRINT = $80`, `K_GOTO = $A2`,
  `T_LIT = $A4`),
- `CONST T_LIT = $A4` in `sw/basic.bas`,
- and a **private 37-word list in `sim/test_interp.py`**, in a table of
  seventy.

That is the fault [D67] spent a session curing for I/O addresses,
sitting in the file that defines the language. So the token values get
**generated from `TOKTAB`** — `tools/vocab.py` already reads it, along
with `sttab` and `btab` — and the order stops being a constraint anybody
has to remember. A compatibility promise for saved programs is a
decision to take deliberately, later, when there is something to be
compatible with.

### The tokeniser is redesigned, not ported

With the numbering derived, the table can carry **flag bits per token**,
which is what BBC BASIC does and COOL8 does not. Read from the
annotated disassembly rather than a manual, its `TOKENS` entries carry
eight, of which COOL8 wants two:

- **rest of the line is verbatim** — deletes the inline `REM`
  special-case that `tokenise` carries today;
- **a line number follows** — after `GOTO`, `GOSUB`, `THEN`, `LIST`,
  `DELETE`.

The second is not decoration. **`RENUMBER` is broken today**: it
rewrites each line's own number and never looks inside the tokens, so
every `GOTO` in a renumbered program points at the wrong line. Nothing
in the suite catches it. The flag is what makes finding a line-number
reference possible, and a correct RENUMBER is then two passes — build
the old-to-new map, walk the program rewriting references. It is allowed
to be slow and small; almost nobody runs it.

**Two things BBC does that COOL8 should not.** Its keyword table is
sorted so the search can exit early on the first letter; that is a speed
optimisation for a routine that runs once per line typed, and it is not
worth a re-sort. And it packs numeric constants at entry as `tknCONST`
plus three bytes — which COOL8 already does as `T_LIT` plus two, so the
arrangement was inherited correctly and only looked like an invention.

**The float literal falls out of the port.** A hand-written tokeniser
calls `snum`, which already parses fractions and already decides integer
or float, and emits `T_LIT`+2 or a new `T_FLT`+3. [D66] said this and it
is the one part of its plan that needed no revision.

## D67 — One system storage region, derived from the claims, and page 0 stops being special

**Done, and the I/O page moved with it.** All system storage is in one
contiguous region below the screen. One file declares it, every claim
states its size, the region's floor is *computed* from the claims rather
than chosen, and the user area is what is left. Page 0 and the `$FF00`
page hold nothing.

| | before | after |
|---|---|---|
| image | 23,541 bytes, **523 free** | 23,528 bytes, **792 free** |
| ROM contiguous code | `$F000-$FDFF`, 3,584 B | `$F000-$FEFF`, **3,840 B** |
| I/O page | `$FE00-$FEFF` | `$FF00-$FFF7`, 104 B spare |
| system storage | page 0 (full) + `$FF00` (full) | `$7DE9-$7EDF`, packed, 247 B |
| addresses written down | 60 equates + 87 literals + 5 tools | **none** — generated |

**+269 bytes**, of which 256 are the page move and 13 are the workspace
clear that the region made unnecessary. Every suite green: `poe test`
12, `poe check` 6, `poe test-rtl` 12, `sim/cosim.py all`, `sim/synth.py`.

This answers both of [D66]'s "what is not yet known" items, and it had
to, because the port allocates workspace with every routine it moves.

### There are two allocators and one of them is invisible

`DIM x AT $addr` in `sw/basic.bas` emits **no symbol and no size**:
`tools/cool8bas.py` substitutes the literal `$00B0` as the label, so the
editor's claims exist nowhere the symbol table, the assembler or any
check can see them. `tools/memmap.py` recovered them by regex over the
`.bas` source and recorded only the *base* address — never the extent.

So every written statement of the map was wrong, in the same direction:

| said | actually |
|---|---|
| `memmap.py`: `$00A4-$00D9` free, 54 bytes | the editor owns most of it |
| `zp.asm` and [D66]: `$00B1-$00CF` free, **31 bytes** | `DIM cont(31) AS BYTE AT $00B0` owns `$00B0-$00CF`; the 31 bytes do not exist |
| `memmap.py`'s `PAGE0` | **no entry at all** for `$0033-$003F` — `SACC`, `SLEN`, `STYPE`, `DVSR`, `DREM`, `DSGN`, `CSTK`, `CDEPTH`, `SDIG` |
| `memmap.py`'s `REGIONS` | omits `SACC`/`pbuf` at `$7F00-$7FFF` and the whole `$FF00` workspace page |

And the one that bites: **`SFRAC = $00B1` is `cont(1)`.** [D66] moved
`SFRAC` off `$00A4` to escape a collision with the editor's `cols`, and
landed it inside a 32-byte array whose extent nothing could see.
`snumi` writes `SFRAC` for every line number the editor parses;
`cont(1)` is "screen row 1 continues row 0".

**This is the second time the same fault has been fixed by moving the
byte.** That is the argument for the redesign rather than a third move:
the fix that keeps working is the one where a claim cannot be silent.

### Page 0 was never worth defending

[D6] dropped the zero page *and* a direct-page register: every absolute
access is three bytes and the same cycles wherever it points, and
`sw/zp.asm`'s own header has said so all along — "$0040 costs exactly
what $9040 costs". The scarcity was self-inflicted, and it was expensive
twice: it is why [D66] recorded "53 bytes, and that is the whole
budget", and it is why `FORSTK`, `garg`, `lwk`, `frames`, `rseed`, the
keyboard ring and `DIRBUF` were exiled to `$FF00` — a *second* pool,
allocated by hand, in a page the boot ROM's clear does not cover.

The real constraint was never page 0. `sw/interp.asm` states it exactly
while doing the exile: **"page 0 is spoken for, and a `.space` would
ship its zeros in the image."** Only the second clause is architectural.

**Measured, and it is the whole of what was at stake.** `.res` emits
real zero bytes (`tools/cool8asm.py`), and the compiler allocates every
BASIC global that way — `a_lbuf` at `$FAB6`, `a_tbuf` at `$FB37`,
`a_spg` at `$FBD3`, **324 bytes of the image that exist only to reserve
RAM**, carried in flash and copied at boot, against 523 bytes free.

### The design

Workspace needs exactly four properties: outside the user area,
cleared at boot, outside the image, and reachable by a fixed name from
both languages. **One region satisfies all four**, so there is one.

| | |
|---|---|
| `$0000-$00FF` | free. Formerly "page 0" |
| `$0100-$01FF` | the CPU stack, growing down from `$0200` |
| `$0200-$9FFF` | the user area: program up, heap down, **one region** |
| `$A000-$B3FF` | the screen, at `SYSBOT` — the region's lowest claim |
| `$B400-SACC+255` | **system storage** — every claim, contiguous |
| … `ORG-1` | slack: the image's room to grow, checked, never silent |
| `ORG-$FEFF` | the image: code and tables, **no `.res`**. `ORG` is derived |
| `$FF00-$FFF7` | the I/O page, generated from the RTL by `tools/ioregs.py` |
| `$FFF8-$FFFF` | the vectors |

*(The screen inside the system region, and the image's origin derived
rather than written down, are [D69] and
[D70](#d70--the-user-area-is-one-region-of-40448-bytes); when this entry
was written the screen sat at `$8000` splitting the user area, the image
began at a constant `$A000`, and the I/O page was at `$FE00`. The four
rules below are unchanged and are why the move cost a change of
constants rather than an audit.)*

Four rules carry it:

- **One file is the map**, in the language the assembler reads, so it
  cannot drift from what is built. `tools/memmap.py` declares nothing
  and derives everything; the prose maps in `zp.asm`, `basic.bas` and
  [04-system.md](04-system.md) §2 stop restating it. `sw/basic.bas`'s
  `CONST PROG/MEMTOP/USERTOP/SCREEN` become `EXTERN`s of the same
  names, so the numbers exist once.
- **Every claim states its size**, `;: <n> <what>`, and a claim without
  one is not storage. That is the bargain `tools/ioregs.py` already
  makes with `//:` for the I/O page, and it is what makes two owners on
  one byte a build failure instead of a bug found twice.
- **Nothing allocates but the allocator.** No `DIM ... AT`, no `.res`.
  The editor's globals become names in the map file, which removes the
  invisible allocator and returns 324 bytes to the image.
- **`SYSBOT` is computed, not chosen.** It is the lowest claim, so
  adding storage moves the boundary by exactly its size and `FREE`,
  which already derives from `USERTOP`, reports the truth without being
  told. **There is no size to pick and no headroom to guess** — an
  earlier draft of this entry chose 512 bytes, which was a number
  nobody could have defended.

**The move itself is nearly free, and that is [D6] paying off.** The
equates are *names*: `SFRAC = $00B1` becomes `SFRAC = $7Exx` in one
line and no call site changes. What does not move for free is anything
that wrote the address down instead of the name — `PEEK($FF26)` and the
`POKE $FF88` run in `sw/basic.bas` — which is the invisible allocator
one more time, and which the check names.

### What was rejected

**Keeping three pools and just fixing the collision.** Page 0 and the
`$FF00` page are free RAM and cost nothing to use, so "it works" was
available. It is what was done last time, at `$00A4`, and the fault
came back at `$00B1` within one entry. Three pools is three places to
look and one allocator too few.

**Sizing the region.** Rejected on the user's correction that the
32 KB user area was a number picked once and not an architectural
constant: the user area is whatever is left once BASIC and the editor
are resident and initialised. Once that is true there is no trade to
weigh, and a computed floor is strictly better than any chosen one.

**Moving the region to the bottom of RAM**, just above the stack.
`PROG` would float, so a program's base address would change whenever
system storage grew. The top is right, and it is the shape the machine
already has — `$7EE0-$7FFF` has been a protected block above `USERTOP`
all along, for the CALL stack and the string accumulator. This entry
extends it downward and finishes it rather than inventing a region.

**Moving the vectors with the page.** The first sketch put the I/O page
at `$FF00-$FFFF` and moved `RESET`/`NMI`/`IRQ`/`BRK` down to `$FEF8`,
which means changing `rtl/core/` — the portable, ASIC-clean half, and
the one place the structural rule says not to touch casually. Stopping
the page eight bytes short instead leaves the vectors as RAM exactly
where the core reads them, and the whole hardware change becomes
`io_sel` in `cool8_soc.v` and `rom_win` in `cool8_mem.v`. It is also
*worth more*: 256 bytes rather than 248, because the image runs to
`$FEFF` instead of `$FEF7`.

### The move was cheap because the addresses were made derivable first

**The order was the whole trick.** Moving the page looked like a large
job because the base was written down in sixty-odd places; so it was
made derivable *before* it was moved, and then the move was a constant.

`tools/ioregs.py` already read every register's offset out of the
Verilog localparams that decode it. It holds `IO_BASE` as well now and
generates three files from that one source: `sw/io.asm` as
`NAME = IOBASE + $xx`, `sw/io.bas` as `CONST NAME = $xxxx`, and
`docs/04a-registers.md`. `poe check` fails on any of them being stale.
The eighteen `G`-prefixed aliases in `interp.asm` — `GVMODE` for
`VID_MODE` — are gone, so 04a-registers.md's section apologising for
two spellings of one address is empty by construction.

**`CONST` and not `EXTERN` for BASIC, and the difference is 89 bytes.**
Switching `sw/basic.bas`'s eight register names to `EXTERN` grew the
image from 23,541 to 23,630, because a `CONST` folds at compile time
and a link-time symbol cannot. Measured, not predicted, and it is why
BASIC gets a generated file of its own rather than reaching into the
assembly one.

**Then the literals, which are the ones that bite.** An equate naming a
register is checked against the hardware; `POKE $FE1E, 1` is not, and
would go on addressing the old page silently with no symbol to fail on.
There were **87** — 44 in `basic.bas`, 22 in `lib.bas`, 17 in
`demo.asm`, 4 in `interp.asm` — and `ioregs.py --name-literals`
converted them all from the mapping it already had. The check counts
them now and fails at anything but zero.

### What the move broke, and every one was a written-down address

The suites went from 12 green to 6 failing and back. Every cause was
the same shape, and none of them was in the hardware:

- **`nextline` marked the direct-mode record by testing `LREC+1 == $FF`.**
  DIRBUF lived at `$FF88`, so its page *was* the mark. The record moved
  to the storage region and the constant did not: `RUN` printed
  nothing, `MODE 4` never reached the hardware, and the editor still
  worked — which is what made it look like a graphics fault. Four
  sites, all `#>DIRBUF` now.
- **`dorun` set `HEAP` to come down from `$7EDF`** as two `MOV R0,#$DF`
  / `MOV R0,#$7E` halves — the top of the user area before the region
  existed. That aimed the heap at DIRBUF, FORSTK and the keyboard ring.
  It is `#<USERTOP`/`#>USERTOP` now, and `USERTOP` is `SYSBOT - 1`.
- **`CONST IRST = $FF86`** in `basic.bas` became a flash register that
  reads non-zero, so the editor called `doreset()` on every pass of its
  key loop and would not accept a line.
- **Six harnesses set `m.cpu.sp = 0xFFF7`**, the top of RAM under the
  old map and the last byte of the page under the new one. Every `PUSH`
  wrote a return address into a flash register. The machine did not
  crash; it spun, and `sim/test_fs.py` said only "the machine did not
  halt".
- **`_SessVideo` read `0xFE11`, `0xFE22`, `0xFE23`** in
  `tools/cool8rsvm.py`, so `video.ctrl` returned garbage and
  `test_basic.Machine.row()` took the wrong branch — the screen read
  blank whatever was actually on it.
- **`cool8_boot_tb` seeded the RAM byte under `FLS_DATA`** at
  `mem[14'h3F45]`, so autoboot would find an empty directory and fall
  through to the monitor. The seed stayed at `$FE8B`; autoboot read
  uninitialised SPRAM as a directory, believed a garbage length, and
  sat in its copy loop. The failure read "never reached the monitor",
  which points at the boot ROM rather than at a constant in a harness.
- **Eighty-two `16'hFExx` literals across five testbenches**, and three
  decode-edge checks asserting the *old* boundaries.

**Not one of these was a hardware bug**, and `sim/cosim.py all` passed
first time. That is this entry's own argument made twice: an address
written down is a fault waiting for something to move, and the cure is
to generate it rather than to be careful with it.

### Two tool bugs found on the way, both worth keeping

- **The assembler conflated "already included" with "circular."** One
  growing `seen` set meant the second, innocent include of a shared
  header reported `circular include`. It is an ancestor-chain check
  plus include-once now, which is what lets `sw/io.asm` be reached both
  through `zp.asm` and through `fs.asm` — and `sim/test_fs.py`
  assembles the latter on its own, so the header cannot be reached by
  exactly one route.
- **`Assembler.split()` rstrips the comment**, which is right for
  assembling and destroys a file when the two halves are joined back
  up: the first `--name-literals` run turned `interp.asm` into a single
  line. The splitter the rewriter uses is by index now, so the halves
  always reconstruct the line.

### How it was staged, with the tree green at every step

1. **Made observable.** The `;:` annotations, `memmap.py` deriving
   rather than declaring, and the collision check. No behaviour change,
   and the image stayed byte-identical at 23,541 across the annotation
   of `zp.asm`, `fs.asm` and `interp.asm` — which is the check that the
   step really was inert.
2. **Fixed what the check found**: `SFRAC`/`cont`, on its first run.
3. **Made the I/O addresses derivable** — generated `sw/io.asm` and
   `sw/io.bas`, 87 literals converted, aliases dropped. Image unchanged
   at 23,541, so this too was inert.
4. **Moved the page**, and the region with it.

### What is still owed

**The 324 bytes of `.res`.** `a_lbuf` (128), `a_tbuf` (128) and
`a_spg` (32) are still reservations *inside* the image — zeros carried
in flash and copied at boot to reserve RAM. Moving them into the region
is pure profit and needs only `DIM ... AT`, but it is deliberately left
for [D66] stage 2, which is about to hand-write the routines that use
them: doing it now would move buffers that are about to stop existing.
That is 324 of the 792 free bytes, waiting.

**`DIM ... AT` is still the invisible allocator.** `memmap.py` models
it — with its extent, which is the part that was missing — but the
compiler still emits no symbol and no size for it. It goes away with
`basic.bas` rather than being fixed.

## D66 — The editor and the interpreter become one assembly program

**Decided, not yet done.** `sw/basic.bas` is to be ported to assembly
routine by routine until it is empty, and the prompt loop moves into
`sw/interp.asm`. The staging is below; nothing here is a rewrite in one
go, and the suite stays green throughout.

### The number that forced it

`python sim/build_basic.py --by-file`:

| | bytes |
|---|---|
| **`basic.bas`** (the editor) | **12,378 — 52 %** |
| `interp.asm` | 6,615 |
| `fp.asm` | 2,528 |
| `fpbas.asm` | 802 |
| `fs.asm` | 800 |

**The editor is twice the interpreter while doing less**, and the
difference is the language. `sim/test_lib.py` measures the same program
at 704 bytes hand-written and 3,634 compiled — **5.16x** — though that
is `sw/demo.bas`, array- and call-heavy, which
[11-compiler.md §5a](11-compiler.md) names as this compiler's worst
case. The first real editor routine ported came in near it: `putn` plus
its `tenth` helper were ~266 bytes compiled and 49 by hand, and the
image fell 23,909 → 23,703. Call the editor's honest ratio **2.5–3x**,
which against 12,378 bytes is **6–8 KB**.

**This entry answers the question D63 left open** — "what the editor
actually costs" — which had gone unmeasured because `--by-file` globbed
only `sw/*.asm` and silently attributed 13 KB of 24 KB to nothing at
all. It reads `.bas` now, and maps a `SUB` to the `s_` label the
compiler gives it.

### The argument against, which is real

**D52 chose to write the system in its own language**, and that is what
is being given up. The self-hosting demonstration — an OS written in
the BASIC it provides — is the most interesting thing about the shape,
and no byte count buys it back. Against that: it is a demonstration
nobody can see, the machine ships one binary either way, and 6 KB is
the difference between "no room for a decimal point" and room for
several features.

**BASIC source is far easier to change than assembly**, and 12 KB of
working, tested editor is a large surface to hand-translate. That is an
argument about *staging*, not about the destination, and it is why the
plan below never has a broken tree.

### The precedent, and it is unanimous

Neither machine this project borrows from has an editor separate from
its interpreter. **BBC BASIC**: `BUFF` reads a line into `BUFFER`,
`MATCHA` tokenises it *at entry*, `SPTSTN` looks for a line number and
sends it either to `INSRT` to be stored or to `DC` to run now — one
program, one `TOKENS` table. **Microsoft's 6502 BASIC**: `INLIN` reads
into `BUF`, `PTRGET` reads the type sigil off the name, and `INPUT` and
`READ` share one assignment routine, `FIN` for numbers and `STRLIT` for
strings.

COOL8 already has that shape logically and cannot express it, because
the two halves are in different languages. The symptom is duplication
nobody chose:

| job | implementations today |
|---|---|
| text → number | `snum`, `tokenise`'s inline loop, `number()` |
| number → text | `sstr` (to the accumulator), `s_putn` (to the screen) |
| "is this a digit" | `isdigit` in BASIC, `ctab` in the interpreter |

**Five digit loops for two jobs**, in a system whose two halves are
always loaded together and still cannot agree on what a digit is. That
is the architectural case, independent of the byte count.

### What makes it incremental rather than a rewrite

Two mechanisms, one of which had to be built:

- **`EXTERN` is callable now, with arguments.** `tools/cool8bas.py`
  used to resolve an extern to an address only, so a hand-written
  routine could not be reached from BASIC and no compiled `SUB` could
  ever be replaced. `gen_call` takes the extern path today and emits
  the compiler's own convention — arguments pushed right to left,
  caller clears — so the assembly reads `[SP+2]` upward exactly as a
  compiled parameter does. Arity goes unchecked, because the compiler
  cannot know what the assembly wants; that is the cost of the door.
- **The editor's state is already addressable.** A scalar compiles to
  `v_<name>` and an array to `a_<name>`, and both are real symbols:
  `a_lbuf` and `v_cx` can be read and written by a ported routine while
  the rest of the file is still BASIC.

So each routine moves on its own, with the suite green before and
after, and the direction is inward: `basic.bas` stays the top-level
program and shrinks until it holds only includes, at which point the
entry point moves and the file goes.

### The stages, each independently useful

**0 — one of each.** `snum` becomes the only text→number and `sstr`
the only number→text; `number()`, `tokenise`'s loop and `s_putn` call
them. `isdigit` gives way to `ctab`. No user-visible change, ~400–600
bytes, and every later stage is easier because the shared pieces exist.

**1 — `tokenise` (872), and the float literal.** The largest routine in
the editor *and* the sole blocker for `1.5` in source, which needs a
token, a three-byte packed literal, a `prim` arm and a `LIST` renderer
through `fstr`. Doing them together is the point: a hand-written
tokeniser can call `snum`, which already parses fractions.

**2 — line entry and listing.** `storeline` (444), `list` (338),
`deleterange` (180), `insch`, `delchar`.

**3 — screen and keyboard.** `setgeom` (416), `serialkey` (393),
`scroll` (229), `putat` (189), `emit`, `tilefont`.

**4 — the filesystem.** `rewritedir` (636), `docompact` (456),
`loadcore` (314), `dodir` (304), `writelog` (200), `bput` (195),
`parsename` (307). Cold code, so the density win is pure size with no
speed argument either way — and the least-exercised code in the image,
which is the risk.

**5 — the prompt loop, and `basic.bas` is deleted.** `dodirect`,
`runerr`, `main` become the BBC shape: read, tokenise, line number or
not, store or run.

### How it is verified, and this is not optional

**A routine is characterised before it is ported.** Its behaviour goes
into the suite first, so the port is a refactor with a net under it
rather than a rewrite hoping to match. `s_putn` is the cautionary
example: it went in without characterisation, broke `PRINT` for
negatives, and the fault was found by re-running the whole suite and
reading source — the bisect-by-rerun AGENTS.md names — when
`sim/test_basic.py --trace s_putn "PRINT 0 - 7"` shows it directly.
That entry point exists now, and so does `m.trace`, which was
documented on both machines while implemented on neither.

**The size is reported at every stage**, and `--by-sub` is the
burn-down: 88 routines, 11,389 bytes attributed, biggest first.

### The assembler got two things first, and they are done

**Branch relaxation ships.** An out-of-range `BEQ` becomes `BNE` over a
`JMP`, an out-of-range `BRA` becomes a `JMP`, and the inverse condition
comes from `opcodes.COND`'s ordering — the list is in inverse pairs, so
it is the index with the bottom bit flipped, and no second table was
written. Iterated to a fixpoint, because growing one branch moves
everything after it; it terminates because a branch grows once and only
grows.

**The image is byte-identical at 23,703**, which is the check that
matters: nothing already in reach was touched. Every relaxation is
counted and reported, by the CLI and by `sim/harness.py`, because two
silently becoming five would corrupt every size figure this project
quotes.

`sw/disasm.asm`'s `jlo`/`jhs`/`jeq` macros are now unnecessary — they
existed only to invert a test and let a `JMP` carry the distance, which
is what the assembler does by itself.

**`CALLB1` ships**, in `sw/call.asm`, included by `interp.asm` because
that is what uses it and because `sim/test_interp.py` assembles that
file against a stub that never sees the editor. `emitc` is written in
terms of it.

**`tools/cool8asm.py` had no suite of its own** and now does:
`sim/test_cool8asm.py`, in the runner, fifteen checks — the
displacement edges at 125/126 and 127/128, the relaxed encodings byte
for byte, and two VM runs proving a grown branch takes the same path a
near one would, on both arms. A tool eight suites depend on and none
tested was the same shape as the rest of this entry.

### The assembler work, as it was argued

Hand-writing twelve kilobytes is a different job from hand-writing
fifty bytes, and `tools/cool8asm.py` is sized for the second.

**Branch relaxation, and it is the important one.** A conditional
branch reaches ±127 and the assembler makes that a hard error. AGENTS.md
lists it among the traps already hit; `sw/disasm.asm` carries
`jlo`/`jhs`/`jeq` macros that exist for no other reason than to invert
a test and let a `JMP` carry the distance; and one sitting of this
project's work hit it five separate times. Every one of those is a
routine that had to be reshaped around the assembler rather than
written the obvious way, and a port of this size would hit it
constantly, because moving code is the whole activity.

So the assembler should grow the branch itself: an out-of-range `BEQ`
becomes `BNE` over a `JMP`. That needs an iterative sizing pass —
today it is strictly two-pass, and there is a guard that raises if an
item's size changes between them — but the loop converges because
sizes only ever grow.

**It must report every relaxation, and that is not a nicety.** This
project measures itself to the byte, and a silent two-into-five
expansion would quietly corrupt every size measurement it makes. The
count belongs in the assembler's output and each site in the listing.

**A `CALLB` macro, which needs no assembler change at all.** Calling a
compiled routine means pushing arguments right to left, calling, and
clearing the stack; `s_putn`'s first version passed the character in a
register instead and printed the wrong byte — a fault only a negative
number revealed. Macros already exist, so three lines in a shared
include make that convention impossible to get wrong, and every ported
routine that talks to the remaining BASIC will use it.

Structured control-flow macros — `IF`/`ELSE`/`ENDIF`, `WHILE` — are
the obvious third thing and are deliberately *not* in this list. They
depend on relaxation to be usable, and a macro that hides a branch is
worth having only once the branch cannot fail.

**Rewriting the assembler in Rust was considered and rejected**, on the
condition it was offered under: that relaxation would need big changes.
It does not. `tools/cool8asm.py` is 708 lines and relaxation is a
fixpoint loop around the existing pass 1 — size, place, grow whatever
is out of reach, repeat until stable, which terminates because sizes
only grow. Perhaps fifty lines.

And the assembler is not the thing to make faster: **the whole build is
0.35 s and assembling the 24 KB image alone is 0.28 s**. Against that,
a Rust port would have to be fed the mnemonic table from
`tools/opcodes.py`, which is normative and which AGENTS.md forbids
duplicating — so it would need generating and a drift gate, the
`mkrsopc.py` arrangement again — and every suite reaches the assembler
through `sim/harness.py`'s `assemble`/`assemble_text`/`try_assemble`,
which are Python. That is a second implementation and a new build
dependency to solve a problem nobody has.

### Stage 0 has begun, and the first routine cost a page-0 bug

`number()` is `sw/ed.asm`'s `s_number`: 193 bytes of compiled BASIC
became about 30 of assembly, and the image went 23,703 -> 23,546.
**157 bytes for one routine of six lines.**

It shares the interpreter's parser rather than keeping a second one.
`snumi` is `snum` with a single seed changed -- a `.` *ends* the number
instead of starting a fraction, which is what a line number wants --
so the two agree on what a digit is by construction. One predicate,
`SFRAC < 5`, decides "am I counting fraction digits" in both places;
testing `= $FF` instead let the integer-only seed be incremented into
the fraction seed by the first digit, and `10.5` became a float. The
characterisation test written before the port caught that, which is
the entire argument for writing it first.

**Then it broke the editor, and the cause is worth more than the
routine.** `SFRAC` had been given `$00A4` when float `VAL` was built.
`sw/basic.bas` pins state to page 0 with `DIM cols AS BYTE AT $00A4`,
and `tools/memmap.py` could not see that: it read `sw/*.asm` equates
only. So every `snumi` wrote 254 into the editor's column count, the
screen geometry went wild, and control ended up in the boot code --
which wipes user RAM. Nothing in the symptom pointed at page 0.

It was latent for as long as the only callers were `VAL` and `INPUT`,
which do not run while a line is being typed. Porting an *editor*
routine onto the shared parser is what made it reachable.

- `memmap.py` reads `DIM x ... AT $00xx` out of `sw/*.bas` now and
  refuses a byte claimed by two things. It reports this one.
- The pairwise test it first grew was wrong and was backed out: an
  equate may be a token value, and `K_NUM = $A4` is not a claim on
  page 0. Only the `AT` declarations are storage by construction.
- `SFRAC` moved to `$00B1`. The real map is `$00A4-$00B0` editor,
  **`$00B1-$00CF` free (31 bytes)**, `$00D0-$00D8` editor again -- not
  the "54 bytes free" `zp.asm`'s own header claimed, which is now
  corrected.

**The lesson for the remaining 87 routines**: a ported routine runs in
the editor's context, so every byte of interpreter workspace it touches
has to be checked against the editor's, and until now no tool could do
that. `sw/basic.bas` also stores to `$00DC` with a raw literal, inside
the float stack's range, and a `DIM`-only scanner still cannot see it.

### What is not yet known

- **How a string crosses the boundary.** Scalars and arrays are
  addressable; a BASIC *string variable* is a descriptor, and no
  routine taking or returning one has been ported. Stage 2 hits this
  first and should prove it on the smallest such routine before
  anything larger commits to a convention.
- **Page 0.** Hand assembly tends to want more workspace and there is
  no zero-page addressing mode to make it cheap ([D6]). `$00A5-$00D9`
  is free — 53 bytes — and that is the whole budget.

## D65 — Five graphics commands are gone, and the register map is why it was safe

**Done.** `PALETTE`, `SCROLL`, `VPOKE`, `TILE` and `SPRITE` are
removed. `sw/interp.asm` is 120 lines lighter and the image went from
24,050 to **23,816 — 248 bytes free**, up from 14.

Their tokens stay. `TOKTAB`'s order fixes every byte after it and
programs on disk hold the old numbering, so `sttab` points them at
`bad` and the words are `?SYNTAX` where a statement was expected.
[13a-vocabulary.md](13a-vocabulary.md) lists them as removed with the
`POKE` sequence that replaces each, because the generator reads the
same table the interpreter dispatches through.

### Why these five and not `MODE`

All six were called thin register wrappers. Five of them are: each was
a short run of writes to `PAL_IDX`, `VID_SCX`, the VRAM port, or the
sprite descriptor, and **[04a-registers.md](04a-registers.md) now
documents every one of those registers completely** — which is what
made the removal safe rather than reckless. A month ago the same cut
would have deleted the only written record of how to drive the
hardware. [D64]'s generators came first for a reason.

`MODE` was misfiled. It is not a register write but a *preset loader*:
base, stride, depth and the engine select together, and
`POKE VID_MODE, 4` does not do what `MODE 4` does. It stays, and it
was the cheapest of the six anyway — 26 bytes alone, 18 in company.

### Measured, and the method matters more than the number

Every figure came from deleting the command, pointing its table entry
at `bad`, removing whatever that orphaned, and rebuilding. Two earlier
attempts got it wrong in exactly the way the old drop table did:

- **Deleting to the next handler** swallows shared code. `earg` and
  `negp16` sit inside `h_line`'s reach, `retnum` inside `h_gtext`'s,
  `pixxy` inside `h_vpoke`'s. The build refuses, which at least fails
  loudly.
- **Counting references inside `interp.asm` alone** marks everything
  the editor and the boot ROM call as dead. Every command then looks
  removable and nothing links.

The old table's five guesses were all high, in the same direction and
for the same reason as the fixed-point trio that started this note:
`LINE` 400 against 274, `GTEXT` 232 against 168, `SPRITE` 120 against
92, `CLG` 106 against 86.

**Groups are not the sum of their singles.** The six add to 292 and
measure 252; these five add to 266 and measure 234. The cause turned
out to be worth knowing: `sreset` was **already dead** in the
committed tree — no caller anywhere — so every individual measurement
collected it and counted it again. It is gone with the five.

### What it cost

Nothing shipped used any of them: not `sw/demo.bas`, not `sw/lib.bas`,
not the editor. Five cases in `sim/test_run.py` did, and they were
rewritten as `POKE` sequences that drive the same registers, so the
hardware coverage is unchanged — the sprite case still animates a
descriptor once per `VSYNC` and reads the frame back through the
renderer.

The honest cost is verbosity, and it is not evenly spread. A sprite
update is eleven lines where it was one, and with no `:` separator
every `POKE` is its own line. Against that, **a VRAM run got cheaper**:
`VPOKE` reset the address on every call, where setting it once and
letting the port's step carry it is one `POKE` per byte.

### What the 248 bytes are for

The decimal parser. It is the single missing routine behind float
literals, `INPUT A#` and a float-returning `VAL` — three gaps in
[13-basic.md §8](13-basic.md) that all want the same code, and none of
which fitted in 14 bytes.

## D64 — The vocabulary is read out of the tables, and a signature is compulsory

**Done.** `tools/vocab.py` emits
[13a-vocabulary.md](13a-vocabulary.md) from `TOKTAB`, `sttab` and
`btab`. `poe build` regenerates it; `poe check` fails if it is stale,
if any entry has lost its signature, or if a declared return type
disagrees with the tail its handler leaves through. 93 entries — 70
keywords, of which 51 are statements, and 24 builtins. **Zero bytes on
the machine**: the annotations are comments.

### Three sources of truth, and only one of them is a promise

- **Names are read.** `TOKTAB`'s order *is* the token byte and `sttab`
  is the same table in another file, so the tool checks their lengths
  match and pairs them by position. A name cannot drift because nobody
  writes it down twice.
- **Return types are read *and* declared**, and compared. `-> float`
  on a handler that returns through `retnum` is a lie the gate catches;
  the negative test that proved it does bite is in this entry's own
  history — `SGN` was temporarily made to claim `-> float` and the
  check named it.
- **Argument types are declared and believed.** There is no argument
  type anywhere in the interpreter and inferring one would be the
  mistake this project keeps making. Worse, the honest answer is
  usually "it does not check": `!intonly` marks the 23 entries that
  read `R0:R1` without testing `STYPE`, so the list of places a float
  goes silently wrong is generated rather than remembered.

### Why not generate the reference itself

Because the valuable half is not derivable. `2 ^ 3 ^ 2` is 63.96, a
backwards `FOR` runs its body once, `VAL("3.5")` is 3, `LOG(-4)`
returns −4 — none of that exists in the source in any form, and only
`sim/test_run.py` knows it. So the generator emits the *table* and
13-basic.md keeps its hand-written prose, with the gate making sure
the two are talking about the same words.

### What it found on the first run

The header of `sw/toktab.asm` claimed `$A4` was the next free token,
that a 37th keyword would collide with `K_NUM`, and that growing past
it needed a second table. There are **70** keywords, `$A4` is held
open by a one-character `"?"` entry, and the table simply continued.
The same header listed `sw/asm.asm` as one of three readers; [D63]
deleted that file. Both corrected — and both are exactly the drift a
generated inventory exists to prevent, sitting in the file that
defines the language.

## D63 — The inline assembler is gone, `SYS` replaced it, and floats are resident

**Done, and measured at each step.** `python sim/build_basic.py`:

| | image | free |
|---|---|---|
| before | 24,043 | 21 |
| assembler removed | 21,163 | 2,901 |
| `SYS` added | 21,139 | 2,925 |
| float package resident | 23,665 | 399 |
| language binding | 23,876 | 188 |
| `A#`–`Z#` and `^` | 23,975 | 89 |
| comparisons, unary minus | 23,999 | 65 |
| `ABS`, `SGN`, precedence fix | 24,052 | 12 |
| mul level unified (−70) | **23,993** | **71** |

The assembler returned **2,880 bytes and 38 of page 0** — within four
bytes of the 2,886 estimated from the symbol table, which is the closest
an estimate has come all project. `SYS` cost −24: it is *smaller* than
the `h_asm` it replaced.

Resident floating point, everything included, is **2,854 bytes** — it
fits in what the assembler gave back, with 71 to spare. That was the
whole bet of this entry and it came in just under. It was down to 12
bytes before the mul level was unified, which gave 70 back by deleting
a duplicate rather than a feature.

**Floats are real in the language now.** `SIN COS TAN ATN SQR LOG EXP`
and `FLT` are ordinary functions, `PRINT` renders a float, and `+ − * /`
promote — `1 + SQR(2)` and `SQR(2) + 1` are both 2.414, `1 / FLT(4)` is
0.25 where `1 / 4` is still 0. Two integers keep the integer path
untouched, and everything else in the language stays integer: `FOR`,
`POKE`, `PLOT`, subscripts and line numbers read R0:R1 and a float never
puts anything there. `INT` crosses back, flooring.

### It cost almost nothing because strings had already paid

The evaluator has had a type byte since strings needed one: `STYPE` is
0 for a number and non-zero for a string, and a string's value is not in
R0:R1 either — it lives in `SACC`/`SLEN` and `erel`'s `.cat` arm tests
the type and takes the other path. **A float is the same shape with a
third value: `STYPE` 2, and the number in `FACC`.** Nothing new was
invented; `PRINT` grew a branch rather than a printer, and it renders
through `s_putsn` because `fstr` answers exactly the pointer and count
that wants.

### The 8.8 fixed point is gone with it

`FMUL` and `FDIV` were a worse answer to the question real floats
answer, and `INT` was an arithmetic shift right by eight. That is 234
bytes returned and one semantic corrected: **`INT(7)` is 7 now**, where
the shift made it 0. `INT` is the float-to-integer crossing, still
flooring, still for the reason [D62] gives.

### Four bugs, and three were the package meeting a caller it never had

- **`fsav` pushed to the CPU stack.** It is reached by `CALL`, so its
  pushes buried its own return address and `fpair`'s first `POP` took
  that instead of the type. Every expression in the language evaluated
  to 0. It has a five-byte frame stack of its own now.
- **`fp.asm` owns Y, and Y is the token pointer.** `fcp4` and `fswap`
  take a destination in it, `fstr` walks it, `fmul` does `MOVW Y,X`.
  Free while the package was a library called from a driver; not free
  from BASIC. The symptom was not a crash — `PRINT SQR(2)` worked
  because a wrecked Y reads as end-of-line, while `PRINT SQR(2) + 1`
  printed nothing, the `+ 1` lost with the program position. Callers
  save it inline: two instructions against 350 cycles for a multiply.
  **A trampoline was tried first and was worse on both axes**, adding an
  indirect jump *and* bytes.
- **`fpair` did not promote a left-hand integer**, copying its two bytes
  into `FACC` as though they were a float. A wild exponent, and the
  symptom was a hang rather than a wrong number, because `fstr` scales
  by dividing until the value is under 10000.
- **`prim` never cleared `STYPE` for an integer**, and never had to:
  only strings used the type and `sreset` cleared it per statement. With
  floats in the language that leaks forward — the `1` in `SQR(2) + 1`
  inherited type 2. `fsav` clears it, being the one point always
  immediately before the right operand.

### `A#`–`Z#`, `^`, and BM8 as published

Float *variables* were the gap this entry first recorded, and they are
built: `A#`–`Z#`, 26 of them, three bytes each, `#` made a name
character by a bit in `ctab`. `^` followed, as `EXP(y * LOG(x))` — two
transcendentals and the last digit, so `2 ^ 10` prints 1023. That is
the artifact the period Microsoft BASICs had for the same reason and it
is pinned as behaviour; an integer-exponent path would be more bytes
and a second rounding rule to explain.

Together they make **BM8 runnable as published** — the first time the
eighth Rugg/Feldman benchmark could be typed in unmodified here. 0.39 s
against ABC 800's 29 s and a C64's 119 s, and `poe bench` will not
report the time unless the run also prints sin(100) as `-0.50`.
The table and the caveat about what that margin does and does not mean
are in [13-basic.md §9c](13-basic.md).

The operand stack got its overflow check with the frame stack: seven
frames, `?TOO DEEP` past that, rather than four and silence.

### What is still owed

The arithmetic is finished. The language around it is not, and the
gaps are measured and listed in [13-basic.md §8](13-basic.md).

**This entry first said the remaining gaps "error or simply do not
parse". They do not — they are silent.** `STYPE` is read at six sites
in the whole interpreter, and everywhere else a float leaves `R0:R1`
holding whatever was there before and the statement proceeds on it.
`IF X# > 0` branches on stale integers; `PRINT -X#` **drops the sign**,
because `.neg` negates `R0:R1` without asking; `POKE`, `FOR`'s limit,
`STR$` and the ten builtins behind `earg` all do their own version of
the same thing. Only the float *literal* fails loudly, and only because
the tokeniser has no decimal point.

The error was the same shape as this entry's earlier one about the
assembler: a property was asserted from how the code was *meant* to be
organised rather than from running it. Eight programs through the
harness settled it in one pass.

**Comparisons and unary minus are fixed — 24 bytes, and no type check
was added.** `fpair` was already the type check and `fcmp` already
answered `$FF`/0/1, so the float case rewrites the operand pair as
`(sign, 0)` and the six existing integer arms decide as they always
did. `rhs` is the single point all six reach, so the arm is written
once; it now calls `erel` instead of the integer-only
`prim`/`mulrest`/`sumrest`, which is one call rather than three, six
bytes *smaller*, and the reason `IF A# > B# / C#` had been wrong on
the right while correct on the left. Unary minus was a `CMP` and a
`JMP fneg`.

**It cost 0.8–5.3% on BM1–BM7**, worst on BM2, which tests a condition
every iteration of a `GOTO` loop. Recorded because the rule is to
report the number even when it is worse: every comparison now runs
`fsav`/`fpair` whether a float is involved or not.

**Two of the first probes passed by luck and nearly hid the bug.**
`3 > 1/2` and `4 > 10/2` both gave the right answer with the right
side evaluated wrongly, because the wrong evaluation happened to land
on the same side of the boundary. `4 > 10/5` — true, where the broken
path says false — is what exposed it. The tests kept are the
discriminating ones, and each says in a comment what wrong answer it
would give if the fix were reverted.

**Then the same bug turned up a second time, and worse.** The float
arms of `+` and `−` call `mulrest` to bind a higher-precedence
operator before adding — and `mulrest` was the integer-only
continuation too. So `A# = B# + C# * D#` **silently dropped the
multiply**: `FLT(1) + FLT(7) / FLT(2)` gave 8, not 4.5, while the
integer `1 + 6 / 2` was always right. That is not a missing feature,
it is a wrong answer in the most ordinary arithmetic a program can
contain, and it shipped inside an entry that called the arithmetic
finished.

Both bugs are one mistake made twice: **a float-aware arm calling an
integer-only helper.** A third would look the same — `prim`,
`mulrest`, `sumrest` or `mdrhs` reached from something that has
already promoted.

The fix was 17 bytes over budget, and two factorings paid for it:
`fsav / prim / fpair` opened five arms and became `fopnd`; the five
`fop*` wrappers all ended alike and now share a tail at `fretf`, which
also retired two copies of "set the type to 2". `ABS` and `SGN` went
in beside it — `ABS` keeps the type, `SGN` always answers an integer,
which is both the useful form and the one that lets a single path
serve either argument.

**The domain errors are silent, and the library already knows.**
`LOG(-4)` returns −4, `SQR(-9)` returns −9, `X# / FLT(0)` returns the
numerator. `fp.asm` sets carry for every one of them and documents it
in the jump table; `fpbas.asm` never tests it. That makes them the
cheapest gap left — a `BCS` per site, nothing to detect — and they are
open only because 12 bytes remain.

**The `earg` class was considered and dropped.** One choke point, ten
builtins, a few bytes; but `RND`, `CHR$`, `ASC` and `VPEEK` all take
integers naturally and nobody passes them a float. Cheap is not the
same as worth buying.

What stays silent by choice: `POKE`, the `FOR` limit, subscripts,
`STR$`. Pinned at their wrong answers as tripwires.

### The review, and the two it found that mattered

A full read of the package afterwards found the same duplication a
third time and one bug worse than any of them.

**`mulrest` did not know `^` either**, so `0 - 2 ^ 2` was −2. Three
bugs, one cause, three separate discoveries — at which point the answer
is not another patch. **The mul level was written twice**, inline in
`erel` and again as `mulrest`, and the copies had drifted apart on
floats and then on `^`. It is one routine now, called from both places.
That deleted **70 bytes** — the largest reclaim since the assembler —
and it is the only change here that makes a fourth instance impossible
rather than merely absent. It cost 1.3–2% on BM1–BM7: what was inline
in `erel` is a `CALL` now.

**One over-nested expression bricked the session.** `fsav` refuses past
`FSDEEP` and returns *without* pushing, but its callers go on to
`fpair`, which pops unconditionally — so the expression pops one more
frame than it pushed, and `FSP`, a byte, underflows to 251. Nothing
reset it: `idrct` and `irun` clear EDEPTH, FDEPTH, DDEPTH, CDEPTH and
NNAME, and FSP was in neither list. Past that point *every* expression
in the session failed `?COMPLEX` and returned rubbish — after `NEW`,
`PRINT 2 + 2` printed **1538**. Two `ST [FSP],R0`, one in each reset,
bound it to the statement. `sim/test_run.py`'s `fstack()` runs the
poisoning expression and then asks the same machine to add.

**A documented flag was only half true.** `fdiv`'s header promises "C
set on return means division by zero", but the success path ended
`JMP fnorm` and inherited whatever carry the normalise left. The first
caller to believe the contract — `fopdiv`, so that `X# / FLT(0)` errors
like `1 / 0` does — broke on `FLT(1)/FLT(3)`. A flag stated in a header
has to be set on every path or it is not stated. Fixed in `fp.asm`, at
two bytes.

Also corrected: 40 lines of duplicated `ASM` post-mortem in
13-basic.md, a header still calling values "16-bit signed integers
only", an operator table without `^`, and a note claiming `INT` is an
arithmetic shift by 8 — true when §8 was fixed point, false since.

### Floats cost the integer path 1–15%

BM1–BM7 never call `fp.asm` and got slower anyway — BM3 and BM4 by
13–15%, BM1 by 1%. The promotion check runs on every operator whether
a float is present or not. Worth recording because it is the kind of
cost that is easy not to look for: the feature was measured, the code
that did not use the feature was not, and it moved.

### The finding that opens it — and three wrong versions of it first

**`ASM … END ASM` emits code, but its labels never become usable.**
`PRINT FOO` gives 0 and `CALL FOO` gives `?CALL IN 10`, while the
assembled `RET` is demonstrably sitting at `progend`. Full write-up in
[13-basic.md §1](13-basic.md); the leading hypothesis is that the name
table is rebased *after* `aprog` runs, stranding every label the pass
created, and that is unproven.

**This entry first claimed the assembler was never invoked at all.**
That was wrong, and the way it was wrong is worth more than the entry:
a grep of `interp.asm` came back empty and the conclusion was drawn from
it, when the call is in `sw/basic.bas`. Two more followed — that blocks
land at `$7000` (that is `sim/test_asm.py`'s scaffolding, not the
system's), and that labels want BBC's `.name` (that is a *directive*
here; `aline`'s grammar takes `label:`).

Three wrong diagnoses in a row, each confidently held, each from reading
one file and inferring the rest. **The corrective is the project's own
standing rule 4** — the answer came from `--asmdump` printing what the
machine actually did, and every wrong turn came from reasoning about
source instead.

So the honest position: the assembler is 2,886 bytes of code that is
*mostly* working and has one unidentified defect between it and being
usable. That is a materially weaker case for deleting it than "it has
never worked", and this entry is not to be acted on until the defect is
understood — because if it is a one-line ordering fix, the whole
argument below evaporates.

### So the choice is not "keep a feature or lose it"

| | cost |
|---|---|
| **Wire it up** — one scan pass, like `subscan` | ~40–60 bytes |
| **Remove it** — `asm.asm`, `asmtab.asm`, `h_asm`, `h_call`'s label arm | **~2,900 bytes, and 38 of page 0** |

There are 21 bytes free, so *either* needs a cut. Nothing that works
today is lost by removing it, because nothing works today.

Page 0 is the sharper half. [zp.asm](../sw/zp.asm) hands out every byte;
`$00DA-$00FF` is the assembler's. That 38 bytes is why `HIMEM` cannot
exist ([D62](#d62--floating-point-ships-as-a-loadable-library-not-as-part-of-the-system)),
and page 0 is the one resource with no slack anywhere.

### `SYS addr` is what actually has to replace it

Removing `ASM` removes the only way BASIC reaches machine code, because
`CALL <label>` needs the assembler to have defined the label. A loadable
library would have no entry point. **The replacement is one statement:**

```
SYS addr            call machine code, ~25 bytes
```

That is all D62's library ever needed. Assembling on the machine is not
required to *use* machine code — only to write it — and
`tools/cool8asm.py` is a better assembler than the resident one and is
the gate the resident one is measured against. On a machine with a flash
filesystem and a serial console to a host, "type assembly without a PC"
is a thin benefit for 2,900 bytes.

### What the 2,900 buys, and this is the redesign

**Real floating point, resident, in expressions** — not the gated calls
of D62:

| | bytes |
|---|---|
| the package, measured | 2,526 |
| type dispatch on the four operators and six relations | ~300 |
| `SYS` | ~25 |
| **total** | **~2,850** |

against ~2,900 reclaimed. It fits, with nothing to spare and nothing
needed.

**Floats get their own namespace, `A#`–`Z#`**, the way BBC BASIC gives
integers `A%`. Packed three bytes, 78 bytes of RAM, outside page 0 —
[D6](#d6--no-zero-page-addressing-mode) means there is no reason to want
page 0 for them. Integer variables and every integer path are untouched,
so no existing program changes behaviour and no graphics command needs a
coercion. `SIN`, `COS`, `LOG`, `SQR` and `^` become ordinary functions.
BM8 becomes runnable as published.

The alternative spend is the cheap spread — `ABS`, `SGN`, 16.16 fixed
point, `MERGE`, `HIMEM`, better errors — around 1,200 bytes, leaving
1,700 for whatever comes next.

### Against it

- **2,886 bytes of working, gated code get deleted.** `test_asm.py` is a
  real suite proving a real thing. Deleting it to make room is a
  judgement that cannot be undone cheaply.
- **An on-machine assembler is a character feature.** BBC BASIC's is
  famous, and D45 exists because someone thought carefully about how it
  should share the variable namespace. This machine is meant to be a
  pleasant retro computer, not only an efficient one.
- **Fixing it is 40–60 bytes**, which is two orders cheaper than the
  benefit being claimed for the space. If the 21-byte ceiling were
  relieved some other way, "wire it up" is obviously right and this
  entry is obviously wrong.
- Dead tokens stay either way: `ASM` cannot leave `toktab.asm`, whose
  order is fixed by saved programs — though `AS`, `INT`, `BYTE`, `CARD`,
  `EXTERN`, `INCLUDE` and `INLINE` are already dead there, so the
  precedent is established and cheap.

### What would settle it

Two numbers nobody has: **what the editor (`basic.bas`) actually costs**
— it is 13 KB of the image and the only file `--by-file` cannot
attribute, because it has no assembly labels — and whether the sigil
dispatch really is ~300 bytes. Both are measurable, and this entry
should not be acted on before they are.

`python sim/build_basic.py --by-file` is the tool the first of those
wants.

## D62 — Floating point ships as a loadable library, not as part of the system

**Supersedes [D61](#d61--real-floating-point-costs-1074-bytes-measured-and-it-still-does-not-fit)'s
conclusion without contradicting its measurement.** D61 established that
real floats cost about a kilobyte and that the system has 21 bytes. The
error in it was treating "resident" as the only option.

**Floats are not a language feature here. They are a file you load when
you need one**, the way the era actually did it — BBC `*LOAD`ed machine
code, Simons' BASIC on a cartridge, toolkit tapes you merged. Someone
plotting an integral for a school assignment loads the library; everyone
else never pays a byte for it.

**The resident cost is zero**, and that is the entire argument. No drops,
no cuts to `LINE` or `GTEXT`, the image stays where it is. And once the
package is not competing for resident space the transcendentals become
affordable, which is what makes `SIN`, `LOG` and `^` possible at all —
they were unthinkable against 21 bytes and cost nothing in a file.

### What it does not fix

The ergonomics. The API is address-based calls, so `X = X + V*T` is four
of them and a hand-allocated set of addresses. **This makes floats
available, not pleasant**, and the pleasant option for game arithmetic
is still 16.16 fixed point, which is a different job and still
unmeasured.

### The one gap, and the two ways round it

**There is no `HIMEM`.** `LOAD "FP" AT addr` puts raw bytes in memory and
nothing stops the heap growing into them. Adding one is 20–40 bytes and
there are 21, so it is not available.

- **Ship the package inside a BASIC source file as one `ASM … END ASM`
  block.** BASIC's own program storage holds it, so the heap cannot
  reach it and `SAVE`/`LOAD`/`LIST` all work unchanged. It costs ~10 KB
  of assembly *source text* for ~1.7 KB of code and re-assembles on
  every `RUN` — affordable against 40 KB of user RAM, and it needs no
  new feature whatsoever. **This is the supported route.**
- Ship the assembled binary with a documented safe load address, for
  anyone who wants instant start and will not `DIM` into it.

### The jump table is the ABI

Because the package is loaded rather than linked, a caller cannot know
where anything landed. Every entry point is at a fixed offset from the
base, and **entries are appended, never inserted or reordered** — the
same rule and the same reason as `toktab.asm`'s. The table is at the
head of [`sw/fp.asm`](../sw/fp.asm) and lists its own offsets.

### Measured, complete

**2,526 bytes**, 22 entry points, 155 checks. **`python sim/test_fp.py`
prints the whole table below as part of its run — quote it, and if it
disagrees with what is written here then it is right and this is stale.**
The figures were transcribed by hand once and that is exactly how the
Fmax and cell counts in [05-board.md](05-board.md) came to be wrong.

Cycles measured at 8.375 MHz:

| | bytes | cycles | per second |
|---|---|---|---|
| `fmul` | 99 | 350 | 23,900 |
| `fadd` | 137 | 376 | 22,300 |
| `fdiv` | 56 | 1,249 | 6,700 |
| `fstr` | 398 | 2,082 | 4,000 |
| `fsin` | 204 | 4,371 | 1,920 |
| `fcos` | 13 | 4,846 | 1,730 |
| `fexp` | 133 | 4,671 | 1,790 |
| `flog` | 249 | 5,244 | 1,600 |
| `fsqrt` | 115 | 6,389 | 1,310 |
| `fatan` | 296 | 6,744 | 1,240 |
| `ftan` | 64 | 10,509 | 800 |
| `fpow` | 34 | 10,074 | 830 |

plus `fabs` 5, `fneg` 16, `fsgn` 22, `fcmp` 65, `fatan` 296, the pack,
unpack, normalise and int-conversion core from [D61](#d61--real-floating-point-costs-1074-bytes-measured-and-it-still-does-not-fit),
and **71 bytes of workspace that lives inside the package**.

That workspace is worth its own note. It was first written at fixed
page-0 addresses out of 6502 habit, and [zp.asm](../sw/zp.asm) hands out
every byte of page 0 — `FACC` landed in the filesystem's variables and
the temporaries sat on top of **`FORSTK`**. An integral plot is a `FOR`
loop calling these routines, so it would have corrupted itself on the
first iteration. [D6](#d6--no-zero-page-addressing-mode) means there was
never anything to gain: `$0040` costs exactly what `$9040` costs. Inside
the package the workspace also relocates with the code, which is what a
loadable library wants — one base address and nothing else to place.

**Nothing here is a separate series that could have shared one.**
`fcos` is `fsin(x + pi/2)` and costs 13 bytes; `ftan` is the quotient
and costs 64; `fpow` is `exp(y ln x)` and costs 34. Building log and exp
before power, and the quadrant reduction before cosine, is why the tail
of this table is nearly free.

**`fcmp` is in the table because a float library without a comparison is
unusable.** A caller cannot build one out of `fsub` without knowing the
representation, and the moment they do the representation can never
change.

### BM8 is now reachable

`A=K^2 : B=LOG(K) : C=SIN(K)` is 10,074 + 5,244 + 4,371 = **19,689
cycles an iteration, about 2.35 s over a thousand** — extrapolated from
measured single calls, excluding whatever the interpreter costs around
them. Placing that against the published Rugg/Feldman table would need
the table itself verified, which has not been done here.

### The estimates, scored

| | estimated | actual | |
|---|---|---|---|
| arithmetic core | 570 | 676 | 19 % low |
| decimal printer | 250 | 398 | 59 % low |
| transcendentals | 400–700 | 636 | inside |
| trig, sign, compare | — | 745 | not estimated |

Series arithmetic is predictable; formatting and range reduction are
not. `fatan` at 296 bytes is the largest routine in the package after
the printer, and both are large for the same reason — the work is case
analysis, not maths.

## D61 — Real floating point costs 1,074 bytes, measured, and it still does not fit

**Built, run and weighed rather than estimated.** `sw/fp.asm` is a
working 3-byte binary float and `sim/test_fp.py` puts 71 checks through
it on the machine. The number this entry exists for is **1,074 bytes**,
and the system has **21 free**.

### The design that was measured

Not a float that can appear in an expression. That shape was priced at
1.5–2 KB and most of it was not arithmetic: every value slot in the
interpreter widens, and every graphics command needs a coercion at each
argument. **Gating the type removes all of it** — floats live at
addresses, are reached only through calls, and convert out to an integer
or a string. Nothing else in the language learns they exist, so `FOR`,
arrays, `DATA`, `PLOT` and the evaluator are untouched.

Gating also buys the format. Because a float never lives in a variable,
nothing forces the mantissa to a convenient width, so it is 16 bits —
exactly what `mul16` and `udiv16` already work in. A 24-bit mantissa
would need new wide routines.

    byte 0   exponent, excess-128; 0 means zero
    byte 1   bit 7 sign, bits 6-0 the top 7 fraction bits
    byte 2   the low 8 fraction bits

15 stored fraction bits and an implied leading 1 is about 4.8 decimal
digits over roughly 10^±38.

### Where the bytes went

| | bytes |
|---|---|
| add, subtract | 170 |
| int↔float, including the floor | 150 |
| divide | 120 |
| multiply | 99 |
| pack, unpack | 58 |
| normalise | 36 |
| compare | 26 |
| constants | 17 |
| **arithmetic subtotal** | **676** |
| **decimal print** | **398** |
| **total** | **1,074** |

**The printer is 37 % of the package**, and it was estimated at 250
against an actual 398 — 59 % low, where the arithmetic estimate was only
12 % low. That is the lesson worth keeping: the hard part of floating
point is not the floating point.

### And it is fast enough that speed was never the problem

Measured at 8.375 MHz, `python sim/test_fp.py` timings, each figure
including the driver's own load and store:

| op | cycles | per second |
|---|---|---|
| `fmul` | 350 | 23,900 |
| `fadd` | 376 | 22,300 |
| `fsub` | 415 | 20,200 |
| `fdiv` | 1,249 | 6,700 |
| `fstr` | 2,082 | 4,000 |

Divide is three and a half times multiply because it is sixteen
restoring-division steps while multiply gets four hardware 8×8 `MUL`s.
Printing is the slowest operation in the package, which follows from the
scaling loop calling `fmul` or `fdiv` several times before the first
digit exists.

**"Can be slow, must be small" turned out to be the wrong trade to
offer.** Nothing here is slow — a four-operation loop over a thousand
iterations is about 0.18 s of arithmetic. Every constraint that bit was
a size constraint.

### BM1–BM8, and why the comparison is awkward

The Rugg/Feldman benchmarks are the obvious way to place this against
period machines. **BM8's arithmetic is now complete** — `^`, `LOG` and
`SIN` all exist, at about 19,700 cycles an iteration or 2.35 s over a
thousand; see
[D62](#d62--floating-point-ships-as-a-loadable-library-not-as-part-of-the-system).

Two things still stand in the way of a like-for-like run, and neither is
about space:

- **Nothing is callable from BASIC.** The token and dispatch glue was
  costed at ~120 bytes and has not been built.
- **The comparison would be false anyway.** Those times come from
  machines where *all* BASIC arithmetic is floating point. COOL8's is
  integer and this float is a gated type, so BM1–BM7 here would measure
  statement dispatch rather than arithmetic. **Cycles per operation is
  the honest comparison**, and that is the table above.

Add roughly 120 for `btab` entries and dispatch and the delivered cost
is **~1,200 bytes**.

### The verdict

The measured drop list is nowhere near it. The fixed-point trio is 256
and goes for free because floats supersede it, which leaves ~950 to find
from `LINE`, `GTEXT`, `INPUT`, `SPRITE` and `CLG` — whose figures are
still the unverified ones, and whose sum as claimed is ~1,056. **Cutting
literally every drop candidate in the table pays for this and nothing
else**, and leaves a machine with no `LINE`, no `GTEXT`, no `INPUT` and
no `SPRITE`.

So it is built, it works, and it is not affordable **as part of the
system image** — which turned out to be the wrong place to put it. See
[D62](#d62--floating-point-ships-as-a-loadable-library-not-as-part-of-the-system),
which keeps every number in this entry and changes only where the code
lives. The package has since grown transcendentals and stands at 1,710
bytes.

### What it costs beyond bytes

`X = X + V*T` becomes four calls and a hand-allocated set of addresses.
That is an assembler wearing a BASIC hat, and this project's aim is a
*pleasant* retro machine. Even at half the size it would be a wart.

**The cheaper thing remains unmeasured and is the one to try**: 16.16
fixed point in four bytes, ±32,767 at 1/65,536. No exponent, no
normalise, no alignment — add and subtract are plain 32-bit integer
work, multiply and divide are the existing routines widened, and it
needs no new type in the language because it is still an integer
expression. The estimate is 400–600 bytes and the estimate is the point:
this entry is what happens when one goes unchecked.

### Three bugs, all of them flag behaviour

Recorded because each cost a round and each is general:

- **`POP` sets Z.** A routine that computed its answer into the flags
  and *then* restored registers handed the caller the flags of whatever
  came off the stack. It made `ftoi` floor an exact −1.0 to −2, and
  separately ran a loop counter until a data byte happened to hit zero.
  The counter now lives in `X` with `DECW`, which is what `udiv16` does
  and why.
- **A fractional divide is not `udiv16`.** Feeding the dividend in one
  bit at a time computes the *integer* quotient; a float needs
  `D × 2^16 / SB`, so the remainder has to **start** as the dividend.
  The first version returned 1 for 1.0/1.0 — the right answer to the
  wrong question.
- **`CLR` between `SUB` and `SBC`.** The normative flag table in
  [02-isa.md §1.2](02-isa.md#12-flag-effects) says nothing about what
  `CLR` does to carry, so every negate written that way was an
  assumption. They are all complement-and-increment now, as `negp16`
  does it, because `XOR` is documented to leave `C` alone.

## D59 — CPI is 2.59, and pipelining the fetch is a bet rather than an optimisation

**Answers the arithmetic the open question was waiting on**, and the
answer is smaller and riskier than the question assumed. Registering the
opcode was the standing candidate for the next big speed-up. Measured,
the upside is **+8 %** — and it is collected only if the pipelined
design closes at 12.5625 MHz exactly. If it closes anywhere below that,
the machine is **28 % slower** than it is today.

This entry does not decide to abandon it. It prices it, and it names a
ten-minute experiment that settles the bet before any of the expensive
work is done.

### The measurement

`python sim/cpi.py` runs three code shapes on the machine and counts
retired instructions beside cycles. Three shapes, because CPI is a
property of code and not of a CPU:

| | cycles | instructions | CPI |
|---|---|---|---|
| native, six benchmarks | 4,208,529 | 1,324,927 | **3.10–3.64** |
| bytecode, the same six | 28,189,181 | 11,220,922 | **2.50–2.58** |
| the real BASIC interpreter | 1,184,077 | 410,740 | **2.88** |
| **all workloads** | **33,581,787** | **12,956,589** | **2.59** |

The native and bytecode programs come from `sim/bench_lang.py` rather
than being restated — a second copy of a benchmark is a second
benchmark. The interpreter runs the loop `sim/prof_interp.py` profiles,
and it is the one that decides, because that is the resident system.

### The arithmetic

Every instruction passes through `S_FETCH` exactly once, so registering
the opcode costs one cycle per instruction. The page-2 escape (`$2F` —
`MUL`, `XOR`, the bit operations, `ADDW X|Y,#imm16`) passes through
`S_FETCH` *and* `S_FETCH2`, both of which decode off the bus, so those
cost two. The report brackets the penalty `p` at 1.0 and 1.2 and the
conclusion holds at both, which is the only reason it is a conclusion.

    speedup      = (f_new / f_old) x  CPI / (CPI + p)
    f_breakeven  =  f_old x (CPI + p) / CPI

| | CPI | break-even | gain at 12.5625 MHz |
|---|---|---|---|
| interpreter, `p`=1.0 | 2.88 | 11.28 MHz | 1.11x |
| interpreter, `p`=1.2 | 2.88 | 11.86 MHz | 1.06x |
| all workloads, `p`=1.0 | 2.59 | 11.61 MHz | 1.08x |
| all workloads, `p`=1.2 | 2.59 | **12.25 MHz** | **1.03x** |

### The clock is quantised, and that is what makes it a bet

[D32](#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock)
makes `sclk` a division of the pixel clock, and there is one PLL. So the
only rungs are 8.375 and 12.5625 MHz — **there is nothing in between,
and a design that closes at 12.4 runs at 8.375.** The added cycle is
paid either way:

| pipelined design closes at | runs at | CPI | against today |
|---|---|---|---|
| ≥ 12.5625 MHz | 12.5625 | 3.59 | **+8 %** |
| 11.7 – 12.5 MHz | 8.375 | 3.59 | **−28 %** |

That asymmetry, not the size of the upside, is the reason to be careful.
The measured baseline is 11.91 MHz mean and 12.15 best across six seeds
(`python tools/mkbit.py --seeds 6`), so pipelining has to find another
0.4–0.65 MHz beyond where the design already is. Halving an 87 ns cone
plausibly does that. Plausibly is not a number.

Against the +8 %: every entry in [02-isa.md §8](02-isa.md#8-timing-model)
changes, and `tools/opcodes.py`, the emulator and `sim/timing.py` change
with them — and the assembler's listings read `cycles()`, so a stale
table is a wrong listing. `sim/cosim.py` would verify the result on all
511 encodings, so the change is *safe*; it is merely expensive, and its
payoff is conditional on a number nobody has measured.

### The experiment that settles it, and it is cheap

**Do not do the rewrite to find out.** Register the opcode in `S_FETCH`
and change nothing else — no cycle counts, no emulator, no timing table.
The result is functionally wrong and will fail co-simulation, which does
not matter, because synthesis does not care whether a design is correct:

```bash
python tools/mkbit.py --seeds 6      # look at sclk
```

- clears **12.5625 MHz with margin** → the rewrite is justified, and you
  know it before writing a line of it
- lands at **12.2** → the whole exercise is saved, and the hack is
  deleted

Ten minutes of compute against a week of work, on a question that has
been open for four milestones. That this was never done is the finding
here, more than the CPI number is.

### What was wrong with the intuition

The question assumed a 50 % clock gain against a small cycle-count loss.
Both halves were off. The clock gain caps at 50 % only if the pipelined
design reaches the next rung exactly, and the cycle-count loss is not
small: **at CPI 2.59, one added cycle is a 39 % penalty.** A machine
that averages two and a half cycles an instruction has almost nothing
between it and one cycle of overhead. The break-even CPI for any gain at
all at 12.5625 MHz is 2.0, and this machine is at 2.59 — close enough to
the wall that the arithmetic decides it rather than the RTL.

That is the transferable lesson, and it is
[D38](#d38--the-fetch-path-next-state-is-decoded-flat-and-it-bought-area-rather-than-speed)'s
again in a different costume: **the cheap measurement goes first.**
`sim/cpi.py` took minutes and closed a question that had been open for
four milestones and would have cost a week to answer with RTL.

### What this does not close

Nothing here says the critical path is fine. It says *this particular*
attack on it does not pay. The path is still 37 levels and 87 ns, and
D38's untried suggestion — replicating `blk_r`/`byte_r` so each consumer
has a local copy, because the first hop is 4.25 ns of pure routing —
costs no cycles at all and so has no break-even to clear. It was tried;
[D60](#d60--narrowing-the-spram-read-path-earlier-and-replicating-its-select-bought-nothing-and-was-reverted)
is what happened.

## D60 — Narrowing the SPRAM read path earlier, and replicating its select, bought nothing and was reverted

**[D38](#d38--the-fetch-path-next-state-is-decoded-flat-and-it-bought-area-rather-than-speed)
named this as "the cheaper thing to try, and it is untried". It has now
been tried, and it does not help.** Recorded so it is not tried a third
time.

### What was changed

Two things, measured separately because they are separable:

1. **Narrow at each block, then choose the block.** `rdata` was one
   16-bit block mux feeding an 8-bit half mux, so both SPRAM outputs —
   32 bits — had to converge before anything narrowed. Reversed, each
   half mux can sit beside the `SB_SPRAM256KA` that feeds it and only 16
   bits travel. **LUT-neutral: 31 SB_LUT4 either way.**
2. **A local copy of the half select per block**, which is D38's actual
   suggestion, aimed at the 4.25 ns of pure routing its timing report
   found as the critical path's first hop.

### The numbers, six placer seeds each

| | `sclk` mean | min | max | spread | logic cells |
|---|---|---|---|---|---|
| **baseline** | **11.91** | 11.71 | **12.15** | 3.7 % | 5164 — 97 % |
| narrowed early | 11.60 | 11.43 | 12.09 | 5.7 % | 5152 — 97 % |
| + replicated select | 11.73 | 11.40 | 11.94 | 4.6 % | 5184 — 98 % |

**The baseline wins on both the mean and the best seed**, and every
difference is inside the spread. Reverted: `git checkout` on
`rtl/soc/cool8_spram.v`, with the tooling and this entry kept.

Both variants passed `sim/test_spram.py` (90,506 checks) and
`sim/cosim.py all`, so this is a measurement of speed and not a report
of a broken change.

### The trap that nearly made this a false negative

**Two flip-flops with identical inputs are silently deduplicated, and
`(* keep *)` does not stop it.** The first attempt at the replication
wrote `(* keep *) reg byte_r0, byte_r1;`, and `stat` showed the same
three flip-flops as the baseline — the replication had undone itself and
would have been "measured" as no change.

Bisecting the passes: the attribute *works* through `opt -full`, where
both `$dff` survive. It is lost during flip-flop techmapping, between
`map_ffs` and `map_luts`. This is a known and open rough edge —
[yosys #855](https://github.com/YosysHQ/yosys/issues/855) and
[#4272](https://github.com/YosysHQ/yosys/issues/4272) — and the docs and
maintainers both say `keep` is the mechanism, so the failure is silent
and against expectation.

**The robust form is to make the twins non-identical**, because cells
that are not identical cannot be merged at all: hold the complement in
one copy and swap the mux arms. That maps to an `SB_DFFESS` beside the
`SB_DFFESR`, costs one flip-flop and no logic, and survives. If
replication is ever wanted anywhere in this design, that is how, and
**`stat` must be checked for the extra flip-flop rather than assumed.**

### What it says about the critical path

D38's timing report is not wrong — the first hop really is 4.25 ns of
routing — but shortening it does not move Fmax, which means the path is
not won or lost there. The cone is 37 levels deep and the routing is a
symptom of a 97 %-full device, not the cause. **At this occupancy the
placer's freedom is the constraint**, which is also why the seed spread
is 4–6 % and why any change of this size is unmeasurable. Something that
removes logic would help; something that reshapes it will not.
