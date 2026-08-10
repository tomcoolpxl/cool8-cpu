#!/usr/bin/env python3
"""Where the interpreter's clocks go.

    python sim/prof_interp.py

Runs the expression benchmark under `sim/dbg.py`'s profiler and reports
per routine. This exists because guessing did not work: flattening the
evaluator from three nested calls per operand to one was the obvious fix
and moved the benchmark by 1.6 %.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import cool8rsvm as vm                                   # noqa: E402
import dbg
import test_interp as T

code, syms = T.build("interp", T.HARNESS)
K, num, name, line, program = T.K, T.num, T.name, T.line, T.program
prog = program(
    line(10, [K["FOR"]], name("K"), "=", num(1), [K["TO"]], num(1000)),
    line(20, name("A"), "=", name("K"), "+", num(3), "-", name("K")),
    line(30, [K["NEXT"]]),
    line(40, [K["END"]]))
m = vm.Machine()
m.bus.mem[T.CODE:T.CODE + len(code)] = code
at = syms["prog"]
m.bus.mem[at:at + len(prog)] = bytes(prog)
end = at + len(prog)
m.cpu.pc = T.CODE
m.cpu.sp = 0x7FF0
m.romen = False
m.bus.mem[0x0016] = end & 0xFF
m.bus.mem[0x0017] = end >> 8
p = dbg.Profile(syms, T.CODE, at)
p.run(m)
print("  FOR K = 1 TO 1000: A = K + 3 - K: NEXT")
print()
print(p.report())
