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
[`cool8_text.v`](../rtl/soc/cool8_text.v), which is built and verified
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
[`cool8_text.v`](../rtl/soc/cool8_text.v) already implements and that
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

## Open questions

**One, and it is a fit question rather than an architectural one.**

### Does the video engine as scoped fit the UP5K, and if not, what comes out?

The architecture above is settled. What is not settled is whether all of
it fits alongside the CPU, and the answer will come from `nextpnr`
rather than from arithmetic.

The estimate, using the conversion this project has actually measured —
**1636 LUT4 placed as 1994 logic cells, a factor of 1.22**:

| | LUT4 |
|---|---|
| Fetch engine, pixel shifter, palette, VRAM arbiter, indirect port, raster/IRQ/cursor | 1051 |
| Sprites — 32 descriptors, 8 per line, 8×8 and 16×16, flip, 4 bpp | 450 |
| Blitter — rects, transparency, clip, logic ops, pixel port | *included above* |
| Bresenham line draw | 200 |
| **Total** | **1701** → ~2075 LC |

```
video           2075 LC
existing SoC    1994 LC
audio, PS/2, timer, SPI   ~450 LC
──────────────────────────────────
                4519 LC  =  86 % of 5280
```

86 % is the zone where placement rather than logic becomes the risk:
`nextpnr` moves about 6 % across placer seeds, and 12 MHz still has to
close. Every number above except the 1994 is a hand-count, and this
project's hand-counts have been wrong in both directions — the core came
in at 948 LUT4 against a ~1000 estimate, and at 3080 gate equivalents
against 2750.

**So the question is not resolved by cutting things now.** It is
resolved the way [M3](06-roadmap.md#m3--cpu-rtl) resolved the ASIC area
risk: by measuring early, at the point where the largest uncertain block
first exists. [06-roadmap.md M5](06-roadmap.md#m5--video) now carries
that gate — synthesise and place after the fetch engine, shifter and
palette are wired, before the blitter and sprites are written.

**The cut order, if the gate says so**, in the order already chosen:
programmable viewport and calibration mode (~80), the second indirect
VRAM port (~40), Bresenham lines (~200), the 8 bpp mode (~60), then
sprite descriptors from 32 to 16 (~60).

Not on the table: the memory split, the stride register, the blitter's
rectangle operations, or sprites entirely. Those are what make it a
video *chip* rather than a framebuffer.

---

The question before this one lasted about an hour: co-simulation at M3 exposed that the
flag table did not say whether `MOV Rd,<pp>` set `Z` and `N`, and the
emulator had quietly decided that it did. Closed as
[D25](#d25--mov-rdpp-sets-no-flags) — it does not.

The section below is kept because the reasoning is worth not
re-deriving.

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

The architecture is settled. Anything that reopens it now needs new
evidence of the same kind: real code, measured, not an argument.
