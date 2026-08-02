# 03 — Microarchitecture

Multicycle, non-pipelined, single memory port. Deliberately transparent:
you should be able to read a waveform and see the instruction happening.

---

## 1. The core / system split

This is the most important structural rule in the project.

```
                    ┌─────────────────────────────┐
   rtl/core/        │        cool8_core           │  ← goes to the ASIC
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
    output wire        o_iack
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
| FPGA, uncontended SPRAM | `mem_ready` low for one cycle (registered read), then high |
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

`busrq` is sampled at the same point as interrupts (in `FETCH`), and
takes priority over both. Worst-case grant latency is the longest
instruction, roughly 7 cycles on the FPGA and ~21 on the ASIC.

---

## 3. Datapath

```
                  ┌──────────────────────────────────────────┐
                  │              8-bit data path             │
                  │                                          │
   mem_rdata ────▶│  IR  IR2  TMP        R0 R1 R2 R3         │
                  │   │        │          │  │  │  │         │
                  │   │        └────┬─────┴──┴──┴──┘         │
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
                  │   PC     SP     X      Y      MAR        │
                  │    │      │     │      │       │         │
                  │    └──────┴──┬──┴──────┘       │         │
                  │              ▼                 │         │
                  │       ┌─────────────┐          │         │
                  │       │  16-bit AGU │──────────┘         │
                  │       │   adder     │                    │
                  │       └─────────────┘                    │
                  └──────────────────────────────────────────┘
                                     │
                                     └──▶ mem_addr
```

### 3.1 Storage

| Element | Bits | Notes |
|---|---|---|
| `R0`–`R3` | 32 | Flip-flops, 2 read ports + 1 write port |
| `X`, `Y` | 32 | |
| `SP` | 16 | |
| `PC` | 16 | |
| `F` | 5 | C, Z, N, V, I |
| `IR` | 8 | Instruction register |
| `IR2` | 8 | Page-2 second opcode byte |
| `TMP` | 8 | Immediate / displacement / high address byte |
| `MAR` | 16 | Memory address register |
| FSM state | ~4 | |
| **Total** | **~137** | |

Two read ports on a 4-entry file is four 4:1 muxes — trivial.

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

---

## 4. Control FSM

Six states. Not every instruction visits every state.

| State | Action |
|---|---|
| `FETCH` | `MAR ← PC`, read. `PC ← PC+1`. Latch `mem_rdata` into `IR`. |
| `FETCH2` | Read the second instruction byte into `TMP` (or `IR2` for page 2). `PC ← PC+1`. |
| `FETCH3` | Read the third byte (high address). `PC ← PC+1`. |
| `ADDR` | AGU computes the effective address into `MAR`. |
| `MEM` | Data read or write at `MAR`. |
| `EXEC` | ALU operation, flag update, register writeback. |

### 4.1 Sequences by instruction class

```
ALU Rd,Rs           FETCH → EXEC
ALU Rd,#imm8        FETCH → FETCH2 → EXEC
INCW X              FETCH → EXEC                (AGU, not ALU)
LD Rd,[X]           FETCH → ADDR → MEM
ST [X],Rd           FETCH → ADDR → MEM
LD Rd,[X+d8]        FETCH → FETCH2 → ADDR → MEM
LD Rd,[SP+u8]       FETCH → FETCH2 → ADDR → MEM
LD Rd,[abs16]       FETCH → FETCH2 → FETCH3 → ADDR → MEM
PUSH Rd             FETCH → ADDR → MEM
POP Rd              FETCH → ADDR → MEM
Bcc (not taken)     FETCH → FETCH2
Bcc (taken)         FETCH → FETCH2 → ADDR
JMP abs16           FETCH → FETCH2 → FETCH3 → ADDR
CALL abs16          FETCH → FETCH2 → FETCH3 → MEM → MEM → ADDR
RET                 FETCH → MEM → MEM → ADDR
page 2              FETCH → FETCH2(→IR2) → …as above…
```

Interrupts and `busrq` are sampled in `FETCH` only. Because no
instruction is restartable-in-the-middle — there are no block
operations, by design — latency is bounded by the longest instruction
and no mid-instruction state ever needs saving.

Priority at the `FETCH` sample point: `busrq` > `nmi` > `irq`.

---

## 5. ASIC target: the TinyTapeout bus profile

### 5.1 The problem

TinyTapeout gives every project exactly:

- `ui_in[7:0]` — 8 dedicated inputs
- `uo_out[7:0]` — 8 dedicated outputs
- `uio[7:0]` — 8 bidirectional
- `clk`, `rst_n`, `ena`

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
ui_in[4]     ext_ALE_L   in  ┐
ui_in[5]     ext_ALE_H   in  ├   strobe pass-through, see below
ui_in[6]     ext_nRD     in  │
ui_in[7]     ext_nWR     in  ┘
```

Every one of the 24 pins is now spent.

### 5.3 Strobe pass-through during bus grant

There is a subtlety that only shows up once you try to build the test
board. During a bus grant the CPU tri-states `AD[7:0]`, so the external
agent can drive the address and data lines — but `ALE_L`, `ALE_H`,
`nRD` and `nWR` are CPU *outputs*. The agent has no way to strobe the
address latches or the SRAM, so it cannot actually do anything with the
bus it was just granted.

The fix costs four multiplexers and the four remaining input pins:

```
while BUSAK is low   uo_out[3:0] ← the core's own strobes
while BUSAK is high  uo_out[3:0] ← ui_in[7:4]
```

The external agent drives `AD[7:0]` and its own strobes into
`ui_in[7:4]`, and the chip passes them straight through to the latches
and the SRAM. The whole bus is now controllable from outside with **no
extra buffers, no tri-state-able latches and no arbitration logic** on
the board.

The test board becomes: TT chip, two 74HC573s, one SRAM, one RP2040
wired to the chip's pins. That's it.

**If pins are ever needed for something else**, `SYNC`, `HALTED` and
`IACK` are the droppable ones — they are debug conveniences, not
functional requirements. The pass-through is functional.

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
| 1 × 74HC00 or GAL | Address decode, if you want I/O |

That is a complete, working single-board computer around a
TinyTapeout die. It is also exactly how you would have built one in
1982, which is the aesthetic.

### 5.6 Optional: two-phase page mode

`A[15:8]` only needs re-emitting when it actually changes. A comparator
plus a "same page" fast path would cut most sequential fetches from
three cycles to two. Costs 8 flip-flops and an 8-bit comparator.

**Not in v1.** Get it correct first. Noted here so the pin assignment
does not preclude it — `ALE_H` simply stops toggling on the fast path.

### 5.7 Area estimate

Rough, pending synthesis:

| Block | Estimate |
|---|---|
| Architectural + microarchitectural state (~137 FF) | ~1100 gates |
| 8-bit ALU with flag logic | ~300 gates |
| 16-bit AGU adder + input muxes | ~450 gates |
| Instruction decoder + FSM | ~600 gates |
| Bus multiplexer / pad wrapper | ~150 gates |
| **Total** | **~2600 gates ≈ 700 cells** |

A TinyTapeout 1×1 tile is on the order of 1000 standard cells, and
multi-tile projects are supported. The core should land in the 2–4 tile
range. **This must be confirmed with real synthesis before committing to
a shuttle**, and it is the single biggest unknown in the schedule.

---

## 6. FPGA implementation notes

### 6.1 Clocking

One clock domain for the entire SoC. The PLL turns the board's 12 MHz
into approximately 25.125 MHz, which is the VGA pixel clock for
640×480@60 (nominal 25.175 MHz, 0.2 % low, comfortably inside every
monitor's tolerance).

The CPU runs from the same clock through a clock **enable**, never a
gated clock. An I/O register sets the divider so the effective CPU rate
can be dialled from full speed down to roughly 1 MHz — see
[D13](01-decisions.md#d13--clock-fast-with-a-programmable-brake).

### 6.2 SPRAM and the memory interface

`SB_SPRAM256KA` is 16K × 16, single port, with four nibble write
enables (`MASKWREN`), and its read output is registered — data appears
the cycle *after* the address. Byte access uses two of the four mask
bits and address bit 0 to select the half-word.

The SPRAM controller in `rtl/soc/` handles all of that and presents the
core's flat 16-bit byte-addressed interface. `mem_ready` goes low for
the registered-read latency and for any cycle the video engine has
taken.

**SPRAM cannot be initialised from the bitstream.** All 64 KB is garbage
at power-on. See [04-system.md](04-system.md) for the boot sequence.

### 6.3 Verification plan

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
