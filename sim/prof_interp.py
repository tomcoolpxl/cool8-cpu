#!/usr/bin/env python3
"""Where the interpreter's clocks go.

    python sim/prof_interp.py

Runs two programs under `sim/dbg.py`'s profiler and reports per
routine. This exists because guessing did not work: flattening the
evaluator from three nested calls per operand to one was the obvious
fix and moved the benchmark by 1.6 %.

**The second case is about `isbuilt`.** Builtins carry no token -- they
are matched by name, in a linear walk of `btab`, *every time the
expression is evaluated*. A-Z and A$-Z$ are resident and skip it, but
every builtin call and every long variable name pays, and a long name
pays the full table because it misses. So the order of `btab` is a
runtime cost, and this says how much of one before anyone reorders it.
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
def profile(title, prog):
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
    print("  " + title)
    print()
    print(p.report())
    print()


profile("FOR K = 1 TO 1000: A = K + 3 - K: NEXT",
        program(
            line(10, [K["FOR"]], name("K"), "=", num(1),
                 [K["TO"]], num(1000)),
            line(20, name("A"), "=", name("K"), "+", num(3),
                 "-", name("K")),
            line(30, [K["NEXT"]]),
            line(40, [K["END"]])))

# RND is twelfth in btab, so a hit walks eleven entries first; the loop
# variable K is resident and costs nothing. Whatever `isbuilt` takes
# here is what reordering the table could return.
profile("FOR K = 1 TO 200: A = RND(10): NEXT   -- RND is 12th in btab",
        program(
            line(10, [K["FOR"]], name("K"), "=", num(1),
                 [K["TO"]], num(200)),
            line(20, name("A"), "=", name("RND"), "(", num(10), ")"),
            line(30, [K["NEXT"]]),
            line(40, [K["END"]])))
