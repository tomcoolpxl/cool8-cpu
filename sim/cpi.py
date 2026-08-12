#!/usr/bin/env python3
"""Cycles per instruction, and whether pipelining the fetch would pay.

    python sim/cpi.py

## The question this exists to answer

[docs/01-decisions.md] "Open questions" has one live item: should the
core's fetch path be pipelined? The machine closes at 11.2 MHz and runs
at 8.375, and the gap is one cone — SPRAM read data, through the block
and byte selects, the boot ROM's mux and the I/O page's, the instruction
decode, and into the next state. 37 levels of logic, 87 ns. It is
[D23](docs/01-decisions.md) showing up: the core has no memory address
register, so its decoder reads the opcode straight off the bus during
`S_FETCH` and the byte and the decision it drives share a cycle.

Registering the opcode breaks that cone in two and should roughly halve
it. **It costs one cycle per `S_FETCH`.** Whether the machine comes out
ahead is arithmetic, and the decisions file says in as many words that
nobody has done it. This is that arithmetic.

## The model, stated so it can be disagreed with

    speedup = (f_new / f_old) x (CPI / (CPI + p))

`p` is the added cycles per instruction. Every instruction passes
through `S_FETCH` exactly once, so `p = 1` — except the page-2 escape
(`$2F`), which passes through `S_FETCH` and then `S_FETCH2`, both of
which decode off the bus. Those cost 2. Page-2 carries `MUL`, `XOR`, the
bit operations and `ADDW X|Y,#imm16`, so it is real but not dominant;
the report brackets the answer at `p = 1.0` and `p = 1.2` and the
conclusion has to survive both or it is not a conclusion.

Rearranged, the useful form is the **break-even clock**: the frequency a
pipelined design must actually close at before it is worth having.

    f_breakeven = f_old x (CPI + p) / CPI

That is the number to hold against what `nextpnr` reports after the
change, and it is why this is worth measuring before writing any RTL —
if break-even lands above what halving an 87 ns cone can plausibly buy,
the question is closed for free.

## What is measured

Three code shapes, because CPI is a property of code and not of the CPU:

  native     compiler-style straight-line code, `sim/bench_lang.py`
  bytecode   a stack machine with a token dispatch loop, same source
  interp     the real resident BASIC interpreter running a real program

The first two are reused from `sim/bench_lang.py` rather than restated —
a second copy of the benchmark definitions is a second benchmark. The
third is the machine as a person actually uses it, and it is the one
that decides, because that is where the clocks really go.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                        # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import cool8rsvm as emu                                    # noqa: E402
import memmap                                            # noqa: E402
import bench_lang as B                                     # noqa: E402

HZ = 8_375_000
FMAX_TODAY = 11.2e6          # docs/05-board.md section 6, measured
HALF_PIXEL = 12.5625e6       # the next rung, docs/01-decisions.md


def run_counted(binpath, extra=None, limit=200_000_000):
    """Run to HALT and return (cycles, instructions).

    Same setup as bench_lang.run, which returns only cycles; this needs
    the retire count beside it and must not perturb that gate to get it.
    """
    m = emu.machine()
    d = open(binpath, "rb").read()
    m.bus.mem[B.CODE:B.CODE + len(d)] = d
    if extra:
        off, blob = extra
        m.bus.mem[off:off + len(blob)] = blob
    m.cpu.pc = B.CODE
    m.cpu.sp = memmap.RAMTOP
    m.romen = False
    if m.run(budget=limit) != "halt":
        raise SystemExit("did not halt: " + binpath)
    return m.cpu.cycles, m.cpu.instructions


def interp_workload():
    """The real interpreter, running the loop prof_interp.py profiles."""
    import test_interp as T
    code, syms = T.build("interp", T.HARNESS)
    K, num, name, line, program = T.K, T.num, T.name, T.line, T.program
    prog = program(
        line(10, [K["FOR"]], name("K"), "=", num(1), [K["TO"]], num(1000)),
        line(20, name("A"), "=", name("K"), "+", num(3), "-", name("K")),
        line(30, [K["NEXT"]]),
        line(40, [K["END"]]))
    m = emu.Machine()
    m.bus.mem[T.CODE:T.CODE + len(code)] = code
    at = syms["prog"]
    m.bus.mem[at:at + len(prog)] = bytes(prog)
    end = at + len(prog)
    m.cpu.pc = T.CODE
    m.cpu.sp = 0x7FF0
    m.romen = False
    m.bus.mem[0x0016] = end & 0xFF
    m.bus.mem[0x0017] = end >> 8
    if m.run(budget=200_000_000) != "halt":
        raise SystemExit("interpreter did not halt")
    return m.cpu.cycles, m.cpu.instructions


def main():
    rows = []

    vm, _ = B.assemble(B.vm_source(), "cpi_vm", quiet=True)
    for label, fn in B.BENCH:
        prog, _, _ = fn()
        _, (nbin, _) = B.emit_native(prog)
        rows.append(("native   " + label.split()[0],) + run_counted(nbin))
        stream = B.bc_compile(prog)
        rows.append(("bytecode " + label.split()[0],)
                    + run_counted(vm, extra=(B.BC, stream)))

    rows.append(("interp   FOR/arith x1000",) + interp_workload())

    print()
    print("  Cycles per instruction, measured on the machine")
    print()
    print(f"  {'workload':<28} {'cycles':>13} {'instructions':>14} "
          f"{'CPI':>6}")
    tc = ti = 0
    for label, cyc, ins in rows:
        tc += cyc
        ti += ins
        print(f"  {label:<28} {cyc:13,} {ins:14,} {cyc / ins:6.2f}")
    overall = tc / ti
    print(f"  {'':<28} {'':>13} {'':>14} {'':>6}")
    print(f"  {'ALL WORKLOADS':<28} {tc:13,} {ti:14,} {overall:6.2f}")
    print()

    interp_cpi = rows[-1][1] / rows[-1][2]
    print("  What it costs to add a cycle to every fetch")
    print()
    print(f"  {'':<20} {'CPI':>6} {'+1 cyc':>9} {'break-even':>12} "
          f"{'at 12.5625':>12}")
    for name, cpi in (("interpreter", interp_cpi),
                      ("all workloads", overall)):
        for p in (1.0, 1.2):
            be = HZ * (cpi + p) / cpi
            gain = (HALF_PIXEL / HZ) * (cpi / (cpi + p))
            tag = f"{name} p={p}"
            print(f"  {tag:<20} {cpi:6.2f} {cpi + p:9.2f} "
                  f"{be / 1e6:9.2f} MHz {gain:11.2f}x")
    print()
    print(f"  today: runs at {HZ / 1e6:.3f} MHz, closes at "
          f"{FMAX_TODAY / 1e6:.1f} MHz unpipelined")
    print(f"  target: {HALF_PIXEL / 1e6:.4f} MHz, half the pixel clock")
    print()

    # The seed spread is the instrument's own error bar. docs/01-decisions.md
    # D32 and D38 both measured it at ~6 % of Fmax across six placer seeds,
    # and D38 is the cautionary tale of a single-seed result that was noise.
    worst_be = max(HZ * (c + 1.2) / c for c in (interp_cpi, overall))
    margin = HALF_PIXEL - worst_be
    spread = 0.06 * FMAX_TODAY

    print("  The margin, against the noise it must be measured in")
    print()
    print(f"    break-even, worst case          "
          f"{worst_be / 1e6:7.2f} MHz")
    print(f"    target, half the pixel clock    "
          f"{HALF_PIXEL / 1e6:7.4f} MHz")
    print(f"    margin                          "
          f"{margin / 1e6:7.2f} MHz")
    print(f"    placer seed spread, 6% of Fmax  "
          f"{spread / 1e6:7.2f} MHz")
    print()
    if margin <= 0:
        print("  Break-even is ABOVE the target. Pipelining makes the "
              "machine slower.")
    elif margin < spread:
        print(f"  **The margin is smaller than the seed spread.** Even a "
              f"pipelined design")
        print(f"  that closed at {HALF_PIXEL / 1e6:.4f} MHz would return "
              f"{(HALF_PIXEL / HZ) * (overall / (overall + 1)):.2f}x on all "
              f"workloads, and")
        print("  could not be distinguished from noise without many seeds. "
              "It costs a")
        print("  rewrite of every cycle count in docs/02-isa.md section 8, "
              "tools/opcodes.py,")
        print("  the emulator and sim/timing.py.  -> NOT WORTH IT")
    else:
        print("  -> WORTH TRYING")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
