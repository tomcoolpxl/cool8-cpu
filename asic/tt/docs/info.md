<!--
Rendered on the Tiny Tapeout project page and in the shuttle datasheet.
-->

## How it works

COOL8 is a clean-sheet 8-bit CPU: four fully orthogonal general
registers, two 16-bit pointer registers, a 16-bit stack pointer, and an
instruction set where every ALU operation accepts any register as source
and destination in one or two bytes. It is not a 6502 clone and not a
Z80 clone; it takes the 6502's implementation discipline and a
regularised version of the Z80's register model, and drops the
historical baggage of both.

The design is multicycle and non-pipelined, with a single memory port.
There is exactly one 8-bit ALU and exactly one 16-bit adder, time-shared
between instruction fetch, branch targets, displaced addressing, stack
pushes and pointer increments. The 8x8 multiply borrows that hardware
rather than adding any: it uses X itself as the accumulator, so it costs
control logic and no architectural state.

An 8-bit CPU bus needs 16 address plus 8 data plus strobes, which does
not fit in Tiny Tapeout's 24 usable pins. Address and data therefore
share the eight bidirectional pins in three phases, with two external
74HC573 latches reconstructing the full 16-bit address — the 8085 idea
taken one step further. Every memory access costs three clocks.

## How to test

The chip needs the rest of a computer around it: two 74HC573 latches on
`ALE_L` and `ALE_H` to hold `A[7:0]` and `A[15:8]`, an SRAM on the
reconstructed address bus, and `nRD` / `nWR` to its `nOE` and `nWE`.

At reset the CPU reads a 16-bit little-endian vector from `$FFF8` and
starts executing there.

Pull `nBUSRQ` low and the CPU finishes the instruction in flight, goes
completely off the bus and raises `BUSAK`. An external microcontroller
can then drive the address latches and the SRAM itself to load a
program, release `nBUSRQ`, and the CPU carries on with every register
exactly as it was. That is how software gets in, and it doubles as a
debugger: halt, read all of memory, resume, and the program cannot tell.

Because the CPU deasserts its own strobes whenever `BUSAK` is high, the
two sources never contend and are simply merged on the board — a 74HC32
to OR the two `ALE` lines and a 74HC00 to AND `nRD` and `nWR`.

`READY` held low inserts wait states. `nIRQ` is level-sensitive and
maskable, `nNMI` is edge-sensitive and is not.

## External hardware

- 2 x 74HC573 transparent latches
- 1 x 62256 (32 KB) or 628128 (128 KB) asynchronous SRAM
- 1 x 74HC32 to merge the two ALE strobes
- 1 x 74HC00 to merge nRD and nWR; spare gates do address decode
- 1 x RP2040 as loader and debugger, driving nBUSRQ
- 1 x 28C64 EEPROM, optional — an independent way to boot if the bus
  grant misbehaves in silicon
