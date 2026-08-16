# 03 — Microarchitecture

Multicycle, non-pipelined, single memory port. Deliberately transparent:
you should be able to read a waveform and see the instruction happening.

---

## 1. The core / system split

This is the most important structural rule in the project.

```
                    ┌─────────────────────────────┐
   rtl/core/        │        cool8_core           │  ← stays portable
                    │  registers, ALU, AGU, FSM   │
                    └──────────────┬──────────────┘
                                   │ cool8 memory interface
                                   │ (16-bit addr, 8-bit data)
             ┌─────────────────────┴─────────────────────┐
             │                                           │
  ┌──────────┴──────────┐                   ┌────────────┴────────────┐
  │  rtl/soc/  (FPGA)   │                   │  rtl/pads/  (ASIC)      │
  │  SPRAM controller   │                   │  3-phase multiplexer    │
  │  video, audio, PS/2 │                   │  onto 24 TT pins        │
  └─────────────────────┘                   └─────────────────────────┘
```

`cool8_core` contains **no** vendor primitives, no inferred RAM, no
tri-state, no initial blocks with content, no clock gating and no
asynchronous reset. Its register file is flip-flops, not a memory macro,
because 32 bits of storage is cheaper as flops than as any RAM you could
instantiate.

If a change to the core would break either target, it is the wrong
change.

---

## 2. Core interface

```verilog
module cool8_core (
    input  wire        clk,
    input  wire        rst_n,

    // Memory interface — one access at a time
    output wire [15:0] mem_addr,
    output wire [7:0]  mem_wdata,
    input  wire [7:0]  mem_rdata,
    output wire        mem_read,
    output wire        mem_write,
    input  wire        mem_ready,

    // Interrupts (active high, synchronised outside the core)
    input  wire        irq,
    input  wire        nmi,

    // Bus arbitration — an external agent takes the memory bus
    input  wire        busrq,
    output wire        busak,

    // Status / debug
    output wire        o_fetch,      // this access is an opcode fetch
    output wire        o_halted,
    output wire        o_iack,
    output wire        o_retire      // an instruction completes this cycle
);
```

### 2.1 Bus protocol

Synchronous, single outstanding access, ready-gated.

- The core asserts `mem_read` **or** `mem_write` together with a stable
  `mem_addr` (and `mem_wdata` on a write).
- The transfer completes on the rising clock edge where `mem_ready` is
  high. On a read, `mem_rdata` must be valid in that same cycle.
- While `mem_ready` is low, the core holds everything and stalls.

One protocol covers all three cases that matter:

| Situation | How it appears |
|---|---|
| FPGA, uncontended SPRAM | Read: `mem_ready` low for one cycle (registered read), then high. Write: high immediately — see §6.2 |
| FPGA, the I/O page | The same. It has nothing to wait for and waits anyway — see §6.3 |
| FPGA, video stealing a cycle | `mem_ready` low for one extra cycle |
| ASIC, 3-phase multiplexed bus | `mem_ready` low for two cycles, high on the third |

The core does not know or care which. That is the point.
### 2.2 Bus request and grant

`busrq` lets something other than the CPU own memory. It is the only
way a COOL8 system loads software, on either target, and so it is a
**core** feature rather than SoC glue — see
[D17](01-decisions.md#d17--bus-request-belongs-in-the-core).

```
1.  External agent asserts busrq.
2.  The core finishes the instruction in flight. No instruction is
    restartable-in-the-middle, so there is never partial state to save.
3.  The core stops fetching, deasserts mem_read and mem_write
    (tri-states AD[7:0] on the ASIC), and asserts busak.
4.  The agent owns memory for as long as it holds busrq.
5.  busrq deasserts; the core deasserts busak and resumes at the next
    instruction, with every register exactly as it was.
```

A bus grant is **not** a reset and **not** an interrupt. Nothing is
pushed, no vector is taken, `PC` does not move. Architectural state is
untouched — which is what makes it usable as a debugger: halt, read all
of memory, resume, and the program cannot tell.

`busrq` is sampled at the same point as interrupts — an instruction
boundary — and takes priority over both. Worst-case grant latency is the
longest instruction, which is `MUL` at 11 clocks. `MUL` touches no
memory, so on the ASIC it is still 11: the three-phase bus stretches
only the instructions that access memory, and the worst of those is
`CALL abs16` at 6 clocks with 5 accesses, so 6 + 5×2 = 16.

---

## 3. Datapath

```
                  ┌──────────────────────────────────────────┐
                  │              8-bit data path             │
                  │                                          │
   mem_rdata ────▶│  IR  TMP  TMPH       R0 R1 R2 R3         │
                  │   │   └────┬───┘        │  │  │  │        │
                  │   │        └────┬───────┴──┴──┴──┘        │
                  │   │             ▼                        │
                  │   │        ┌─────────┐                   │
                  │   │        │ 8-bit   │──▶ flags C Z N V  │
                  │   │        │  ALU    │                   │
                  │   │        └────┬────┘                   │
                  │   │             └──────▶ writeback ──────┼──▶ mem_wdata
                  └───┼──────────────────────────────────────┘
                      │
                  ┌───▼──────────────────────────────────────┐
                  │            16-bit address path           │
                  │                                          │
                  │   PC     SP     X      Y    {TMPH,TMP}   │
                  │    │      │     │      │       │         │
                  │    └──────┴──┬──┴──────┴───────┘         │
                  │              ▼                           │
                  │       ┌─────────────┐                    │
                  │       │  16-bit AGU │───┬──▶ A operand   │
                  │       │   adder     │───┴──▶ sum         │
                  │       └─────────────┘                    │
                  └──────────────────────────────────────────┘
                                     │
                                     └──▶ mem_addr  (2:1, no MAR)
```

### 3.1 Storage

| Element | Bits | Notes |
|---|---|---|
| `R0`–`R3` | 32 | Flip-flops, 2 read ports + 1 write port |
| `X`, `Y` | 32 | |
| `SP` | 16 | |
| `PC` | 16 | |
| `F` | 5 | C, Z, N, V, I |
| `IR` | 8 | Opcode, or the page-2 second byte |
| `p2` | 1 | `IR` holds a page-2 opcode |
| `TMP`, `TMPH` | 16 | Immediate / displacement / 16-bit operand |
| FSM state + step counter | 7 | |
| `vec_sel`, `in_int`, `iack`, `halted`, NMI edge | 6 | |
| **Total** | **139** | 148 as synthesised, see §5.7 |

The interface gains `o_retire`, which pulses as an instruction
completes. It is not architectural — it exists so the co-simulation
harness can sample state at exactly the points the emulator does.

Two read ports on a 4-entry file is four 4:1 muxes — trivial.

There is **no memory address register**. `mem_addr` is driven straight
from the AGU, which removes 16 flip-flops and, more importantly, a whole
pipeline stage from every memory access: an effective address is
computed in the same cycle the access is made rather than the cycle
before. That is where most of the difference between the measured cycle
counts and the earlier targets comes from. See
[D23](01-decisions.md#d23--no-memory-address-register).

`IR2` is gone for the same reason: after a `$2F` escape the primary
opcode is known to be `$2F` and carries no further information, so the
second byte overwrites `IR` and a single `p2` bit records that it did.
`TMPH` is new, and holds the high byte of a 16-bit operand.

### 3.2 The single 16-bit adder

There is exactly **one** 16-bit adder in the core. It is time-shared:

| Operation | A input | B input |
|---|---|---|
| Instruction fetch | `PC` | `+1` |
| Branch target | `PC` | `sext(TMP)` |
| `[X+d8]`, `[Y+d8]` | `X` / `Y` | `sext(TMP)` |
| `[SP+u8]` | `SP` | `zext(TMP)` |
| `[X+Rs]` | `X` / `Y` | `zext(Rs)` |
| `PUSH` / `POP` | `SP` | `±1` |
| `INCW` / `DECW` | `X` / `Y` | `±1` |
| `ADDW SP,#d8` | `SP` | `sext(TMP)` |

Sharing costs a couple of input muxes and saves roughly 40 % of the
core's combinational area versus separate increment/add paths. On the
FPGA the muxes are free (they fold into the LUT inputs); on the ASIC
the saving is real.

The 8-bit ALU is separate and is never used for address arithmetic.

### 3.3 Multiply

`MUL Rd,Rs` ([02-isa.md §5.7](02-isa.md#57-multiply)) is a shift-add
sequencer that borrows hardware rather than adding any:

| Role | Reused element |
|---|---|
| 16-bit product accumulator | `X` — which is also the destination |
| Shifted multiplier | `TMP` |
| Multiplicand | read from the register file each step |
| The adder | the existing 8-bit ALU |

Eight iterations of *conditionally add the multiplicand to the high half
of `X`, then shift `X` and `TMP` right by one*. The only genuinely new
state is a 3-bit step counter, so the cost is control logic and muxes —
roughly 150 gates, and **no new flip-flops of architectural state**.

The FSM gains one state, `MULT`, which loops until the counter expires.
It is the only state in the machine that repeats, and it touches no
memory, so it does not complicate the interrupt or bus-grant model:
`MUL` is still a single instruction that completes before either is
sampled.

---

## 4. Control FSM

Twelve states and a 3-bit step counter. Not every instruction visits
every state, and most visit two or three.

| State | Action |
|---|---|
| `RESET` | Select the reset vector. |
| `VEC` | Read a vector, low byte then high, into `PC`. |
| `FETCH` | Read at `PC`. `PC ← PC+1`. Latch the opcode into `IR`. |
| `FETCH2` | The page-2 second opcode byte. `IR ← it`, `p2 ← 1`. |
| `OPND` | One or two operand bytes into `TMP` and `TMPH`. |
| `EXEC` | ALU or AGU operation, flag update, writeback. |
| `MEM` | One or two data accesses. |
| `PUSH` | Two or three byte push: `PUSHW`, `CALL`, interrupt entry. |
| `POP` | Two or three byte pop: `POPW`, `RET`, `RETI`. |
| `MULT` | One shift-add step; loops eight times. |
| `HALT` | Stopped, waiting for an interrupt or reset. |
| `BUSAK` | Off the bus, waiting for `busrq` to release. |

There is no `ADDR` state. Because `mem_addr` comes straight from the
AGU (§3.1), the effective address is computed in the cycle the access
happens rather than the cycle before it.

### 4.1 Sequences by instruction class

```
ALU Rd,Rs           FETCH → EXEC                             2
ALU Rd,#imm8        FETCH → OPND → EXEC                      3
INCW X              FETCH → EXEC                (AGU)        2
LD Rd,[X]           FETCH → MEM                              2
ST [X],Rd           FETCH → MEM                              2
LD Rd,[X+d8]        FETCH → OPND → MEM                       3
LD Rd,[SP+u8]       FETCH → OPND → MEM                       3
LD Rd,[abs16]       FETCH → OPND ×2 → MEM                    4
PUSH Rd             FETCH → MEM                              2
POP Rd              FETCH → MEM                              2
Bcc (not taken)     FETCH → OPND                             2
Bcc (taken)         FETCH → OPND → EXEC                      3
JMP abs16           FETCH → OPND ×2      (PC ← {rdata,TMP})  3
CALL abs16          FETCH → OPND ×2 → PUSH ×2 → EXEC         6
RET                 FETCH → POP ×2                           3
RETI                FETCH → POP ×3                           4
MUL Rd,Rs           FETCH → FETCH2 → EXEC → MULT ×8         11
interrupt entry     PUSH ×3 → VEC ×2                         5
page 2              FETCH → FETCH2 → …as above…             +1
```

Interrupts and `busrq` are sampled at instruction boundaries only.
Because no instruction is restartable-in-the-middle — there are no block
operations, by design — latency is bounded by the longest instruction
and no mid-instruction state ever needs saving.

Priority at the boundary: `busrq` > `nmi` > `irq`.

An instruction that changes `I` does so in the cycle it retires, and the
boundary check reads the **new** value: reading the old one would let an
interrupt in immediately after `DI` and keep one out immediately after
`EI`. See [D24](01-decisions.md#d24--ei-and-di-take-effect-immediately-no-delay-slot).

---

## 5. ASIC target: the TinyTapeout bus profile

### 5.1 The problem

TinyTapeout gives every project exactly:

- `ui_in[7:0]` — 8 dedicated inputs
- `uo_out[7:0]` — 8 dedicated outputs
- `uio_in[7:0]` / `uio_out[7:0]` / `uio_oe[7:0]` — 8 bidirectional,
  presented to the design as three separate buses with a **per-bit**
  output enable
- `clk`, `rst_n` (active low), `ena`

Note the bidirectional convention: the wrapper does not hand you a
single inout bus. `AD[7:0]` below is `uio_out` driven when
`uio_oe = $FF` and sampled from `uio_in` when `uio_oe = $00`. Tri-stating
during a bus grant means clearing `uio_oe`.

That is 24 usable signals. A naive 8-bit CPU bus needs 16 address +
8 data + read + write + at least one strobe = 27 minimum, with nothing
left for interrupts. It does not fit.

### 5.2 The solution: three-phase multiplexing

The address and data share the eight bidirectional pins, in three
phases, with two external transparent latches reconstructing the full
16-bit address. This is the 8085/8051 idea taken one step further.

```
uio[7:0]     AD[7:0]     bidir   A[7:0] │ A[15:8] │ D[7:0]
                                 tri-stated while BUSAK is high
uo_out[0]    ALE_L       out     address-low latch strobe
uo_out[1]    ALE_H       out     address-high latch strobe
uo_out[2]    nRD         out     read strobe, active low
uo_out[3]    nWR         out     write strobe, active low
uo_out[4]    SYNC        out     high when this access is an opcode fetch
uo_out[5]    HALTED      out
uo_out[6]    IACK        out     interrupt acknowledge
uo_out[7]    BUSAK       out     bus granted, CPU is off the bus
ui_in[0]     nIRQ        in
ui_in[1]     nNMI        in
ui_in[2]     READY       in      hold low to insert wait states
ui_in[3]     nBUSRQ      in      external agent requests the bus
ui_in[4:7]   —           in      spare
```

20 of the 24 pins are spent. The four spare inputs are deliberate
headroom: a pin decision on a taped-out chip cannot be revised.

### 5.3 Merging a granted bus

A subtlety that only shows up when you try to build the test board.
During a bus grant the CPU tri-states `AD[7:0]`, so the external agent
can drive address and data — but `ALE_L`, `ALE_H`, `nRD` and `nWR` are
CPU *outputs*. The agent has no way to strobe the address latches or
the SRAM.

This is resolved on the board, not in the chip. Because the CPU
deasserts its strobes whenever `BUSAK` is high, the two sources never
contend and can simply be merged:

```
latch LE   =  CPU_ALE_L  OR  MCU_ALE_L        active high  → 74HC32
              CPU_ALE_H  OR  MCU_ALE_H
SRAM nOE   =  CPU_nRD   AND  MCU_nRD          active low   → 74HC00 as AND
SRAM nWE   =  CPU_nWR   AND  MCU_nWR
```

Two 14-pin packages, six gates of the eight available, roughly €0.60,
and about 10 ns of added propagation delay — irrelevant at a few MHz.

An earlier draft did this inside the chip instead, multiplexing the
strobes from four spare input pins while `BUSAK` was high. It worked,
but it spent four irreplaceable die pins and four muxes to save two
logic packages on a board that already has three chips on it. Board
parts are free; pins after tapeout are not. Merging a granted bus with
external glue is also simply how bus arbitration was normally done.

**Two alternatives considered and rejected:**

- *Tri-state the latches.* The 74HC573 has an `/OE` pin; tie it to
  `BUSAK` and the MCU drives the SRAM address bus directly. No extra
  packages, one inverter — but the MCU then needs 16 address + 8 data +
  2 control = 26 GPIO, which is exactly a Pico's entire budget with
  nothing left over.
- *No bus grant at all.* Boot from a parallel EEPROM containing a serial
  loader; garbage SRAM stops mattering because the CPU does not fetch
  from it at reset. This costs nothing and is kept as the **fallback**
  (§5.5) — but it gives no debugger, and re-burning a ROM to change
  software is a worse loop than a bus grant.

### 5.4 Bus cycle

```
              T1          T2          T3
           ┌───────┐   ┌───────┐   ┌───────┐
clk     ───┘       └───┘       └───┘       └───

AD      ══╡A[7:0]╞═════╡A[15:8]╞════╡ D[7:0] ╞══

ALE_L   ──┘‾‾‾‾‾‾‾└──────────────────────────────
ALE_H   ────────────┘‾‾‾‾‾‾‾└────────────────────
nRD     ‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾└──────────┘‾‾‾‾‾
```

Read data is sampled on the rising edge of `nRD`. On a write, `AD` is
driven by the CPU throughout T3 and `nWR` strobes instead.

**Every memory access costs three clock cycles on the ASIC**, against
one on the FPGA. An `ADD R0,R1` is 4 clocks instead of 2; a
`LD R0,[X+d8]` is about 11 instead of 5. At 10 MHz that puts the chip
in the same performance class as a 1 MHz 6502 — entirely appropriate,
and not the limiting factor when you are talking to a 55 ns SRAM.

### 5.5 External glue

| Part | Purpose |
|---|---|
| 2 × 74HC573 | Transparent latches for `A[7:0]` and `A[15:8]` |
| 1 × 62256 (32 KB) or 628128 (128 KB) SRAM | Main memory |
| 1 × 74HC32 | OR-merge the two `ALE` strobes (§5.3) |
| 1 × 74HC00 | AND-merge `nRD`/`nWR`; spare gates do address decode |
| 1 × RP2040 / Pico | Loader and debugger: drives `nBUSRQ`, `AD[7:0]` and its own strobes |
| 1 × 28C64 EEPROM *(optional)* | Boot ROM fallback — see below |

That is a complete, working single-board computer around a TinyTapeout
die. It is also close to how you would have built one in 1982, which is
the aesthetic.

**The EEPROM is cheap insurance.** A socket and a chip-select from the
spare `74HC00` gates cost nothing at design time, and they give the
board a second, completely independent way to run code: the CPU boots
from ROM, and a serial loader in that ROM pulls programs into SRAM. If
`BUSRQ` turns out to have a bug in silicon — and you cannot patch
silicon — that is the difference between a dead chip and a working one.

Design it in. Populate it only if you need it.

### 5.6 Optional: two-phase page mode

`A[15:8]` only needs re-emitting when it actually changes. A comparator
plus a "same page" fast path would cut most sequential fetches from
three cycles to two. Costs 8 flip-flops and an 8-bit comparator.

**Not in v1.** Get it correct first. Noted here so the pin assignment
does not preclude it — `ALE_H` simply stops toggling on the fast path.

### 5.7 Area estimate

Rough, pending synthesis:

The estimate this section carried before the RTL existed was ~2750
gates, made up of ~1100 for state, ~300 for the ALU, ~450 for the AGU,
~600 for decode and the FSM, ~150 for multiply and ~150 for the pad
wrapper.

**Synthesised**, by [`sim/synth.py`](../sim/synth.py):

| Measure | Result |
|---|---|
| iCE40UP5K, `cool8_core` | **902 LUT4, 140 FF, 24 carry** |
| — of which `cool8_alu` | 78 LUT4 |
| — of which `cool8_agu` | 128 LUT4 |
| Mapped to two-input gates | 2080 combinational + 140 FF |
| Gate equivalents at 6 GE per flip-flop | **2920** |

It was 948 LUT4 and 148 FF until [D38](01-decisions.md) gave `S_FETCH`
its own flat next-state decode, which was attempted as a speed fix and
kept as an area one.

Measured on yosys 0.67. It was 969 LUT4 and 3084 GE when this was
first written, on an older yosys; the RTL has not changed and the
mapper has. Worth knowing before reading a 2 % move as a regression —
and worth re-running `sim/synth.py` rather than trusting this line
after a toolchain update.

948 LUTs against a ~1000 estimate is close enough to be luck. The gate
count is 12 % over the estimate, which for a figure written before any
code existed is well inside the noise and does not change the
conclusion: at a TinyTapeout tile of roughly 1000 gates this is a
**2×2 project**, since the shuttle sells 1×1, 1×2, 2×2, 3×2, 4×2, 6×2
and 8×2 and there is no three-tile option.

### 5.8 Placed and routed — the real number

Run at M3 through TinyTapeout's own flow (LibreLane, sky130, `ttsky26c`),
on `tt_um_cool8`: the core **and** the bus multiplexer, not just the core.

| Measure | Result |
|---|---|
| Standard cells | **3009**, of which 158 sequential |
| Cell area | **21,706 µm²** |
| Die area, as a 1×2 | 36,349 µm² |
| **Utilisation** | **61.2 %** |
| Setup, worst corner (`ss` 100 °C 1.60 V) | −2.13 ns |
| — of which register to register | **0** |
| Setup, typical and fast corners | +4.74 ns, +5.27 ns |
| Hold, worst corner | +0.11 ns, no violations |
| DRC / LVS / antenna / routing DRC | 0 / 0 / 0 / 0 |
| Power | 1.48 mW |

**The architecture is not at risk on area.** 3009 cells against a guess
of "750 cells" — the guess was in the wrong unit more than the wrong
ballpark; the gate-equivalent estimate of 2750 against 21,706 µm² of
real cells is the comparison that holds up, and it is close. At 29.9 %
utilisation this fits in two tiles, not four. See §5.9.

**The timing violations are all at the pins, not inside the CPU.**
Register-to-register setup slack is positive at every corner: the
control FSM, the ALU and the shared 16-bit adder all close at 50 MHz in
slow silicon at 100 °C. Every one of the 27 violating paths ends at an
output pad or starts at an input pad, against TinyTapeout's default
assumption about what is on the other side of them. What is actually on
the other side here is two 74HC573 latches and a 55 ns SRAM clocked at
around 10 MHz, where the budget is 100 ns rather than the few
nanoseconds the default reserves.

So the honest statement is: **the CPU closes at 50 MHz; the chip's I/O
timing is constrained by a boundary assumption that does not describe
this board.** Setting `CLOCK_PERIOD` in `src/config.json` to the real
target would clear the remaining violations and, incidentally, remove
the 246 timing-repair buffers and 688 slow-corner slew violations that
chasing a 20 ns constraint bought.

Dropping the memory address register (§3.1, [D23](01-decisions.md#d23--no-memory-address-register))
lengthened the path from the pointer registers through the AGU adder to
the address pins, which is exactly where these paths are. It cost
nothing that matters at the target frequency, and it is worth
remembering that it is the path to watch if the frequency target ever
moves.

### 5.9 Tile count

A 1×1 tile is 161 × 111.52 µm, about 17,955 µm². There is no 3-tile
option — the shuttle sells 1×1, 1×2, 2×2, 3×2, 4×2, 6×2 and 8×2 — so
the earlier estimate of "around 3 tiles" had to resolve one way or the
other. **Both were run.**

| | 2×2 | 1×2 |
|---|---|---|
| Die area | 75,603 µm² | 36,349 µm² |
| Cell area | 21,706 µm² | 20,960 µm² |
| Utilisation | 29.9 % | 61.2 % |
| Setup slack, worst corner | −2.128 ns | −2.023 ns |
| Routing wirelength | 82,341 µm | 78,117 µm |
| Routing DRC / magic DRC / LVS / antenna | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Max slew violations | 688 | 623 |
| Power | 1.479 mW | 1.478 mW |

**1×2 closes, and is better on every metric that moved.** Global
placement did not struggle at 61 %, and routing reached zero DRC errors
as it did at 2×2. Timing improved rather than degraded: the only
violating paths are register-to-pad (§5.8), and halving the die
shortened them.

The apparent drop in cell count from 3009 to 2420 is tap cells and
fill, which scale with die area rather than with logic. Real cell area
barely moved.

So the honest answer is **2 tiles, not 3 and not 4**. The caveat worth
recording: 61 % is TinyTapeout's default target density, so it closed
with the design as it stands and not much room beyond it. Anything that
grows the core later — the two-phase page mode in §5.6, for instance —
should be re-run before assuming 1×2 still holds.

[D19](01-decisions.md#d19--area-overruns-are-paid-for-in-tiles-not-isa-cuts)
— area overruns are paid for in tiles, not ISA cuts — turned out not to
need invoking.

---

## 6. FPGA implementation notes

### 6.1 Clocking

**The system runs at the board's raw 12 MHz, with no PLL in the CPU
path** —
[D26](01-decisions.md#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled),
settled by measurement. The PLL is reserved for the pixel clock at M5
and the two domains are decoupled through a dual-clock scanline buffer,
so the one-clock-domain rule this section used to state is withdrawn.

`CPUDIV` at `$FE01` went with it. It existed to brake a 25.125 MHz core
down to something an 8-bit machine plausibly ran at
([D13](01-decisions.md#d13--clock-fast-with-a-programmable-brake)); at
12 MHz there is nothing to brake, and it is not implemented. If a reason
to run slower appears, it is a clock **enable** into the core and never
a gated clock.

### 6.2 SPRAM and the memory interface

`SB_SPRAM256KA` is 16K × 16, single port, with four nibble write
enables (`MASKWREN`), and its read output is registered — data appears
the cycle *after* the address. Byte access uses two of the four mask
bits and address bit 0 to select the half-word.

`rtl/soc/cool8_spram.v` handles all of that and presents the core's flat
16-bit byte-addressed interface, in **31 LUT4 and 3 flip-flops** on top
of the two blocks:

| Field | Use |
|---|---|
| `addr[15]` | which block — `CHIPSELECT` |
| `addr[14:1]` | the word inside it — `ADDRESS` |
| `addr[0]` | which half — two of the four `MASKWREN` bits, and the read mux |

**A read costs one wait state and a write costs none.** The registered
output is why a read waits; a write commits on the same rising edge the
core completes its transfer on, so making it wait would spend a cycle to
buy nothing. `mem_ready` is low only during a read's address cycle —
high when idle and high through a write — and the asymmetry is invisible
above the bus. Video contention (M5) will pull it low for the cycles it
takes.

The block and half selects are captured on the launch cycle rather than
re-read on the data cycle. The bus protocol above does say a master
holds its address stable while stalled, so this is not strictly
required; it costs two flip-flops and keeps both selects off the read
data path, which [D26](01-decisions.md#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled)
measured as the critical path in the whole system.

**SPRAM cannot be initialised from the bitstream.** All 64 KB is garbage
at power-on. See [04-system.md](04-system.md) for the boot sequence.

`rtl/soc/cool8_mem.v` wraps that block together with `cool8_rom.v` — the
4 KB boot ROM, **8 `SB_RAM40_4K`**, which is initialisable and is the
only memory with anything in it at power-on — and applies the overlay:
reads at `$F000-$FDFF` and `$FF00-$FFFF` come from ROM while `ROMEN`,
writes always go to RAM, and `$FE00-$FEFF` is a hole in the window
because the I/O page wins that decode. The whole map is **53 LUT4 and 6
flip-flops** on top of the two SPRAM and eight EBR blocks.

Both memories are read on every launch and the answer is picked
afterwards, from a select captured on the launch cycle. Suppressing the
SPRAM read under the overlay would save a little power for the 30 ms the
ROM is mapped and would cost a second copy of the ready logic to keep in
step with the first, which is the kind of trade that only looks good in
the abstract. The ROM's read is registered for the same reason: matching
`cool8_spram`'s latency exactly makes the overlay a data mux rather than
a second timing model.

### 6.3 The I/O page, and why it costs a wait state

`rtl/soc/cool8_soc.v` assembles the machine — core, memory, UART,
loader, keyboard, flash and the video subsystem — and decodes
`$FE00-$FEFF` on the **bus**, ahead of `cool8_mem` and whoever the
master is. **4019 LUT4 and 1632 flip-flops** for the whole SoC, with 28
EBR, 4 SPRAM and **no DSP** — see 00-goals.md, the design intends one —
**5199 logic cells of the 5280 the part has, 98 %**, `sclk` Fmax
**11.51 MHz** (one seed, 2026-08-16, after [D91]; the six-seed mean of
2026-08-14 was 11.07, range 10.77-11.23, at 5183 cells). The LUT4
figure had drifted again before D91 was measured — 3754 was recorded
here while the same synthesis said 3972 — so D91's own cost is the
before/after pair in its entry (+47 LUT4, +1 FF), not the delta
against this paragraph's previous number.

**Both numbers moved and neither was noticed until the documents were
audited**: 5164 and 11.91 were the figures here for long enough to
cover D77 through D81. The cell count is the honest cost of features;
the Fmax fall of 0.84 MHz is the one to watch, because
[D59](01-decisions.md#d59--cpi-is-259-and-pipelining-the-fetch-is-a-bet-rather-than-an-optimisation)
needs 12.5625 MHz for pipelining the fetch to pay and the gap is now
1.34 MHz rather than 0.5. It still closes comfortably at the 8.375 MHz
`sclk` actually runs at. It was 1636 LUT4 and 8 EBR before
M5.

That is with the hardware loader out
([D40](01-decisions.md#d40--the-hardware-loader-is-a-build-option-and-it-is-off))
and the sound engine and the flash write path in.

The 16-byte receive FIFO is a block RAM, and it was flip-flops until M6.
Refusing the inference cost a measured 109 LUT4 and 123 flip-flops and
saved one EBR, which was right when the design was at 37 % of the logic
and the font was about to claim eight blocks; after M5 it is the wrong
way round, and
[D37](01-decisions.md#d37--the-uart-receive-fifo-moves-into-block-ram-reversing-m4s-call)
has the measurement.

The inference itself is still not what happens. Left alone yosys retimes
the read capture into the block's own output register, and no test here
reaches a netlist. So the read register is written out and the contract
is stated: **the head byte is correct whenever `rx_avail` is set**,
enforced by a `settle` flag that suppresses availability for the one
cycle after either pointer moves. `cool8_ps2.v` carries the same
arrangement, and `sim/test_ps2.py` sweeps a blind read across the
arrival window to prove it — a phase added because the mutation that
deletes `settle` survived everything else in that file.

The first version answered an I/O read in the cycle it was addressed,
since there is nothing to wait for: the registers are flip-flops and the
read is a mux. That does not synthesise. Selecting the read data on the
address makes `rdata` a combinational function of `addr`, and §4's
decoder reads the opcode straight off `mem_rdata` during a fetch, so
`addr` is a combinational function of `rdata` — the two close a loop
through the bus that `yosys` reports and that no timing analysis can
cross. It is a loop the memory could never create, because SPRAM and EBR
both answer out of a register.

M5 added three things to that arrangement, and each of them is a rule
the first version broke.

**A read's side effect has to happen once, and "the memory launched" is
no longer enough to say so.** Three things can make the memory launch
more than once for a single access now: the display fetch stealing a
cycle, the data cycle of the access it stole, and `cool8_spram`
relaunching every other cycle while the VRAM port holds `ready` low. So
"this access has started" is latched rather than re-derived, and cleared
when the access completes. Without it a stalled read of `UART_DATA` pops
the FIFO twice and the byte in between is simply gone.

**A write held across a stolen cycle reaches the page twice.** Half the
registers on the page have side effects — a palette index advanced
twice, a VRAM address advanced twice — so `io_we` is gated by the
arbiter's state as well.

That gate is necessary and it was not sufficient. A stolen cycle is not
the only thing that can hold a write up: a block *on the page* can stall
one too, and then the strobe stays high through a stall the page itself
asked for. Only one such block exists — `cool8_vport`, when a second
`VRAM_DATA` write arrives while one is posted — and its own `~wr_pend`
guard happened to cover its own register, so nothing was ever observed to
break. That is coverage, not construction, and the audio engine and the
timer are both still to come.

So the write is now two signals. **`io_wreq` is what the master is asking
for**; the port that decides whether to stall sees that one. **`io_we` is
what the page may act on**, which is `io_wreq` qualified by every stall,
and every register with a side effect sees that one. They cannot be the
same signal: `cool8_vport`'s write stall is a function of the write being
offered, so feeding the qualified strobe back into it would make `io_we`
depend on itself.

**And nothing the core drives may take part in arbitrating the memory.**
The obvious version let a master's write win, since a write is a single
cycle and never waits; that put `bus_write` into the grant, `bus_write`
comes combinationally off the byte the core is fetching, and the arbiter
was suddenly inside the machine's longest path. It cost about two
megahertz. The grant is now a function of flip-flops only, and a write
that loses simply waits a cycle — the master is holding its address
anyway.

So the I/O page answers the way the memories do: read on the launch
cycle, answer on the next. **All three — RAM, boot ROM and I/O — are read on
every launch and the answer is picked afterwards**, from selects
captured on that cycle, and `mem_ready` has exactly one source. The
launch itself is `cool8_spram`'s, exported through `cool8_mem`, so there
is one definition of when an access starts rather than three that have
to agree. A read's side effects — popping the receive FIFO — hang off
the same signal, which is what stops a two-cycle read popping twice.

Writes need none of this: a write completes in the cycle it is asserted
everywhere in the machine, so the strobe is already one cycle wide.
Reads go down to the SPRAM unconditionally, including at I/O addresses,
because reading a shadowed byte costs nothing and gating them would mean
a second copy of the timing. Writes are gated, because those do cost
something.

### 6.4 Verification plan

1. **Reference emulator first.** A C or Python model of the ISA, written
   from [02-isa.md](02-isa.md), before any RTL. It is the specification
   made executable and it is what the RTL gets checked against.
2. **Per-instruction directed tests.** Every opcode, every register
   combination, every flag effect. With 4 registers and a regular
   encoding this is generatable rather than hand-written.
3. **Randomised co-simulation.** Random instruction streams, RTL against
   emulator, comparing architectural state after every instruction.
4. **Formal, if it is cheap.** The decoder and flag logic are small
   enough that `yosys`+`sby` bounded model checking is worth trying.
5. **Bus-level test.** The pad wrapper against a Verilog model of a
   74HC573 pair and an async SRAM, proving the ASIC path works before
   anything is submitted.
