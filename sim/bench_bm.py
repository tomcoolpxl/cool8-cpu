#!/usr/bin/env python3
"""The Rugg/Feldman benchmarks, in COOL8 BASIC, on the machine.

    python sim/bench_bm.py

BM1-BM7 as published (Kilobaud, June 1977; the set Personal Computer
World then ran on everything for a decade), typed at the editor and
RUN, timed in cycles and put beside the machines they were written to
compare.

## What is measured, and against what

The historical numbers are a stopwatch between the `S` and the `E` the
program prints. So is this: every benchmark is run twice, once whole
and once with the loop removed, and the difference is the body. That
subtracts the editor, the parse, the two PRINTs and the return to the
prompt, and leaves what the interpreter spent on the benchmark.

Cycles are exact -- the machine counts them -- so the second figure is
arithmetic rather than measurement, at the 8.375 MHz D32 gives the
system clock.

## The adaptations, and why each one is fair

**GOSUB/RETURN becomes CALL/SUB.** COOL8 has no GOSUB; a SUB is found
once at RUN rather than searched for per call, which is BBC BASIC's
arrangement and faster than Microsoft's line-number scan. BM5 exists
to price a subroutine call, and it still does -- but against a machine
that resolves the target earlier than the ones in the table.

**LET is gone**, so `510 LET A=...` is `510 A=...`. No semantic change:
LET was always optional and costs a token nobody needs.

**`IF K<1000 THEN 500` is written `THEN GOTO 500`.** The bare line
number is Microsoft shorthand this language never had.

**BM8 is not run.** It is `A=K^2`, `LOG` and `SIN`: a floating-point
library benchmark, and this machine has 16-bit integers and 8.8 fixed
point ([13-basic.md](../docs/13-basic.md)). There is no honest way to
report a number for it, so there is none.

## The comparison is not like for like, and the table says so

**COOL8 BASIC is integer-only.** Applesoft, Commodore's MS BASIC and
BBC BASIC all evaluate in floating point, and that is most of what
BM3-BM7 measure. The fair comparator in the published set is **Apple
II Integer BASIC** -- Wozniak's, also integer, also no FP at all --
and it is the one to read first. The float BASICs are shown because
they are what these benchmarks are famous for, not because beating
them proves much.

The clock is the other half. COOL8 runs at 8.375 MHz against 1 MHz for
the Apple and the 64 and 2 MHz for the BBC, so the table carries the
measured time *and* the same work scaled to 1 and 2 MHz -- what this
interpreter would do on their clock. Scaling is linear because nothing
here waits on a device: no disk, no wait states, and the display fetch
steals no CPU cycle (D28).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import test_basic as B                                     # noqa: E402

SYS_HZ = 8_375_000.0

# The listings, as published, with the three adaptations the header
# names. Line numbers are the originals so a reader can diff them
# against Kilobaud.
HEAD = ['300 PRINT "S"']
TAIL = ['700 PRINT "E"', "800 END"]
SUBDEF = ["820 SUB NUL", "830 RETURN", "840 END SUB"]

BMS = [
    ("BM1", "an empty FOR loop",
     ["400 FOR K = 1 TO 1000", "500 NEXT K"],
     []),

    ("BM2", "the loop written with GOTO",
     ["400 K = 0", "500 K = K + 1", "600 IF K < 1000 THEN GOTO 500"],
     ["400 K = 0"]),

    ("BM3", "...and arithmetic in it",
     ["400 K = 0", "500 K = K + 1", "510 A = K / K * K + K - K",
      "600 IF K < 1000 THEN GOTO 500"],
     ["400 K = 0"]),

    ("BM4", "...with constants, so the divide is real",
     ["400 K = 0", "500 K = K + 1", "510 A = K / 2 * 3 + 4 - 5",
      "600 IF K < 1000 THEN GOTO 500"],
     ["400 K = 0"]),

    ("BM5", "...and a subroutine call",
     ["400 K = 0", "500 K = K + 1", "510 A = K / 2 * 3 + 4 - 5",
      "520 CALL NUL", "600 IF K < 1000 THEN GOTO 500"],
     ["400 K = 0"], True),

    ("BM6", "...and an inner FOR loop",
     ["400 K = 0", "430 DIM M(5)", "500 K = K + 1",
      "510 A = K / 2 * 3 + 4 - 5", "520 CALL NUL",
      "530 FOR L = 1 TO 5", "540 NEXT L",
      "600 IF K < 1000 THEN GOTO 500"],
     ["400 K = 0", "430 DIM M(5)"], True),

    ("BM7", "...writing to an array",
     ["400 K = 0", "430 DIM M(5)", "500 K = K + 1",
      "510 A = K / 2 * 3 + 4 - 5", "520 CALL NUL",
      "530 FOR L = 1 TO 5", "535 M(L) = A", "540 NEXT L",
      "600 IF K < 1000 THEN GOTO 500"],
     ["400 K = 0", "430 DIM M(5)"], True),
]

# Published times, in seconds. en.wikipedia.org/wiki/Rugg/Feldman_benchmarks
# Integer BASIC first: it is the only other integer interpreter here and
# so the only like-for-like row.
REF = [
    ("Apple II  Integer BASIC", "6502", 1.0,
     [1.3, 3.1, 7.2, 7.2, 8.8, 18.5, 28.0]),
    ("Acorn Atom  System BASIC", "6502", 1.0,
     [0.5, 5.1, 9.5, 10.8, 13.9, 19.1, 31.1]),
    ("BBC Micro  BBC BASIC", "6502", 2.0,
     [0.8, 3.1, 8.1, 8.7, 9.0, 13.9, 21.1]),
    ("Apple II  Applesoft", "6502", 1.0,
     [1.3, 8.5, 16.0, 17.8, 19.1, 28.6, 44.8]),
    ("Commodore 64  MS BASIC", "6510", 1.0,
     [1.2, 9.3, 17.6, 19.5, 21.0, 29.5, 47.5]),
    ("ZX Spectrum  Sinclair", "Z80", 3.58,
     [4.4, 8.2, 20.0, 19.2, 23.1, 53.4, 77.6]),
    ("Altair 8800  Altair 4.0", "8080", 2.0,
     [1.7, 10.2, 21.0, 22.5, 24.3, 36.7, 52.4]),
]


def run_cycles(code, syms, lines):
    """Type a program, RUN it, and return the cycles RUN cost."""
    M = B.Machine(code, syms)
    M.settle()
    for ln in lines:
        M.cmd(ln)
    before = M.m.cpu.cycles
    M.cmd("RUN")
    M.settle(400_000_000)
    return M.m.cpu.cycles - before


def main():
    print("  Rugg/Feldman BM1-BM7, in COOL8 BASIC on the machine")
    print()
    code, syms = B.build()

    mine = []
    for entry in BMS:
        name, about, body, baseline = entry[0], entry[1], entry[2], entry[3]
        sub = SUBDEF if len(entry) > 4 else []
        full = run_cycles(code, syms, HEAD + body + TAIL + sub)
        # The same program with the loop taken out: the editor, the
        # parse, both PRINTs and the way back to the prompt, which the
        # stopwatch between S and E never counted either.
        base = run_cycles(code, syms, HEAD + baseline + TAIL + sub)
        cyc = full - base
        secs = cyc / SYS_HZ
        mine.append(secs)
        print(f"  {name}  {about:<38} {cyc:>10,} cycles  {secs:7.3f} s")

    print()
    print("  Measured at 8.375 MHz, and the same work at their clocks:")
    print()
    print("    " + "".join(f"{n:>9}" for n in ("BM1", "BM2", "BM3", "BM4",
                                               "BM5", "BM6", "BM7")))
    for mhz in (8.375, 2.0, 1.0):
        row = "".join(f"{s * 8.375 / mhz:9.2f}" for s in mine)
        print(f"  {mhz:5.3f} MHz {row}")

    print()
    print("  The machines these were written for (published seconds):")
    print()
    print(f"  {'':<26}{'MHz':>5}" +
          "".join(f"{n:>8}" for n in ("BM1", "BM2", "BM3", "BM4",
                                      "BM5", "BM6", "BM7")))
    for name, cpu, mhz, times in REF:
        print(f"  {name:<26}{mhz:5.2f}" +
              "".join(f"{t:8.1f}" for t in times))

    # The headline, against the only other integer BASIC in the set,
    # with the clock taken out of it.
    ref = dict((r[0], r) for r in REF)["Apple II  Integer BASIC"]
    at1 = [s * 8.375 for s in mine]
    print()
    print("  Against Apple II Integer BASIC, both at 1 MHz "
          "(the like-for-like row):")
    print("    " + "  ".join(
        f"{n}: {r / m:4.1f}x" for n, r, m in
        zip(("BM1", "BM2", "BM3", "BM4", "BM5", "BM6", "BM7"),
            ref[3], at1)))
    print()
    print("  BM8 is not run: it is K^2, LOG and SIN, and this machine has")
    print("  16-bit integers and 8.8 fixed point. There is no honest")
    print("  number for it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
