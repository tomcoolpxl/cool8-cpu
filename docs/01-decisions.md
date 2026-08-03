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

## Resolved former open questions

Recorded so they are not re-opened without new information.

| Question | Resolution |
|---|---|
| Should `LD Rd,[X+Rs]` be promoted to the primary page? | **No.** Stays on page 2 at two bytes. Promoting it would cost `[abs16]` load/store, and there is no evidence yet that array code leans on it hard enough to justify that. Revisit only if M2 assembly says otherwise. |
| Does `CMP Rd,Rd` deserve its four encodings? | **Yes.** Kept for regularity. Every register combination stays legal, the decoder needs no special case and the assembler needs no exception. Four encodings of 256 is cheap. |
| 16-bit counted loops | **Accepted as-is.** `DECW X`/`DECW Y` set `Z` from the full 16-bit result, so `DECW`+`BNE` is a two-instruction 16-bit loop whenever a pointer register is spare. When both pointers are busy, nest the loop or spill the counter. No new instruction. |
| What gets cut if the ASIC overruns? | **Nothing.** See D19. |

## Open questions

**None.** The last one — whether four registers is enough — was closed
by measurement at the M2 gate; see [D21](#d21--four-general-registers-is-enough-confirmed-question-closed).

The architecture is settled. Anything that reopens it now needs new
evidence of the same kind: real code, measured, not an argument.
