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

**GOSUB/RETURN is GOSUB/RETURN again, and BM5 is the published
listing.** It was CALL/SUB for as long as this BASIC had no GOSUB: a SUB
is found once at RUN rather than searched for per call, which is BBC
BASIC's arrangement and faster than Microsoft's line-number scan. That
adaptation was fair while it was forced, and it stopped being forced
when GOSUB arrived.

**So this number is not comparable with the one this table used to
print, and that is the point of changing it.** `GOSUB 9000` resolves
its target through `prg_find` on every call, exactly as the Microsoft
BASICs in the table do -- and 9000 is a *high* line number, which is
what the published listing says and what those machines paid for.
Against CALL, which resolved once at RUN, this measures the thing BM5
was written to measure. Every other machine's BM5 stands; only COOL8's
moved.

**LET is gone**, so `510 LET A=...` is `510 A=...`. No semantic change:
LET was always optional and costs a token nobody needs.

**`IF K<1000 THEN 500` is written `THEN GOTO 500`.** The bare line
number is Microsoft shorthand this language never had.

**BM8 is run, and it is measured differently from the other seven.**
It is `A=K^2`, `LOG(K)`, `SIN(K)`, a hundred times -- the published
listing counts to 100, not 1000, which is why BM8 times are not ten
times BM7's anywhere in the table. It is a floating-point library
benchmark and this machine's BASIC is 16-bit integer, so it runs on
`sw/fp.asm` ([D62](../docs/01-decisions.md)).

**The loop is machine code, not BASIC, and that is not a shortcut.**
The plan was an `ASM` block calling the library, which is exactly what
`CALL <label>` and [D45] exist for -- but `ASM` blocks are never
assembled ([13-basic.md](../docs/13-basic.md) §1): the assembler is
written and byte-gated in isolation and nothing in the interpreter ever
starts it. So there is no way to type this benchmark at the editor.

What that costs the comparison is less than it sounds. On the machines
in the BM8 table the interpreter is a rounding error beside their FP
library -- a 6502 `SIN` is milliseconds, the parse around it
microseconds -- so timing the library doing the same 300 operations is
close to what their stopwatch caught. **The real caveat is precision:**
a 16-bit significand, about 4.8 digits, against the ~9 of the 40-bit
floats those BASICs carried. A shorter mantissa is a faster mantissa,
and that is most of the margin.

`A`, `B` and `C` are float slots rather than BASIC variables, because a
variable here is two bytes and holds an integer. The run is checked
against K=100 before any time is printed: a call that silently does
nothing costs no cycles and reports a wonderful figure, which is how
`sim/test_lib.py` measured nothing for a year.

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

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from test_fp import dec as fpdec                         # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import test_basic as B                                     # noqa: E402
import cool8rsvm as emu                                     # noqa: E402

SYS_HZ = 8_375_000.0

# The listings, as published, with the three adaptations the header
# names. Line numbers are the originals so a reader can diff them
# against Kilobaud.
HEAD = ['300 PRINT "S"']
TAIL = ['700 PRINT "E"', "800 END"]
SUBDEF = ["9000 RETURN"]      # the published BM5's target line

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
      "520 GOSUB 9000", "600 IF K < 1000 THEN GOTO 500"],
     ["400 K = 0"], True),

    ("BM6", "...and an inner FOR loop",
     ["400 K = 0", "430 DIM M(5)", "500 K = K + 1",
      "510 A = K / 2 * 3 + 4 - 5", "520 GOSUB 9000",
      "530 FOR L = 1 TO 5", "540 NEXT L",
      "600 IF K < 1000 THEN GOTO 500"],
     ["400 K = 0", "430 DIM M(5)"], True),

    ("BM7", "...writing to an array",
     ["400 K = 0", "430 DIM M(5)", "500 K = K + 1",
      "510 A = K / 2 * 3 + 4 - 5", "520 GOSUB 9000",
      "530 FOR L = 1 TO 5", "535 M(L) = A", "540 NEXT L",
      "600 IF K < 1000 THEN GOTO 500"],
     ["400 K = 0", "430 DIM M(5)"], True),

    # **BM8, as published, in BASIC.** It counts to 100 and not 1000,
    # which is why no machine's BM8 is ten times its BM7. The three
    # results are float variables because they are floats -- `A#` is
    # BASIC's own float now ([D63]), and `^`, `LOG` and `SIN` are
    # ordinary functions rather than a library reached by address.
    ("BM8", "K^2, LOG(K), SIN(K) -- 100 times",
     ["400 K = 0", "500 K = K + 1", "530 A# = K ^ 2",
      "540 B# = LOG(K)", "550 C# = SIN(K)",
      "600 IF K < 100 THEN GOTO 500"],
     ["400 K = 0"]),
]

# Published times, in seconds. en.wikipedia.org/wiki/Rugg/Feldman_benchmarks
# Integer BASIC first: it is the only other integer interpreter here and
# so the only like-for-like row.
REF = [
    # Integer BASICs -- the only rows that compare like for like.
    ("Apple II  Integer BASIC", "6502", 1.0, True,
     [1.3, 3.1, 7.2, 7.2, 8.8, 18.5, 28.0]),
    ("Luxor ABC 80  integer", "Z80", 3.0, True,
     [0.3, 1.1, 3.5, 3.5, 3.6, 5.8, 9.3]),
    # Floating point, which is most of what BM3-BM7 then measures.
    ("Acorn Atom  System BASIC", "6502", 1.0, False,
     [0.5, 5.1, 9.5, 10.8, 13.9, 19.1, 31.1]),
    ("BBC Micro  BBC BASIC", "6502", 2.0, False,
     [0.8, 3.1, 8.1, 8.7, 9.0, 13.9, 21.1]),
    ("Apple II  Applesoft", "6502", 1.0, False,
     [1.3, 8.5, 16.0, 17.8, 19.1, 28.6, 44.8]),
    ("Commodore 64  MS BASIC", "6510", 1.0, False,
     [1.2, 9.3, 17.6, 19.5, 21.0, 29.5, 47.5]),
    ("ABC 800  BASIC II single", "Z80", 3.0, False,
     [0.9, 1.8, 6.0, 5.9, 6.3, 11.6, 19.6]),
    ("Luxor ABC 80  float", "Z80", 3.0, False,
     [1.1, 2.3, 11.1, 12.1, 12.6, 17.7, 23.9]),
    ("IBM PC  BASICA", "8088", 4.77, False,
     [1.5, 5.2, 12.1, 12.6, 13.6, 23.5, 37.4]),
    ("Apple III  Business BASIC", "6502B", 2.0, False,
     [1.7, 7.2, 13.5, 14.5, 16.0, 27.0, 42.5]),
    ("VIC-20  MS BASIC", "6502", 1.108, False,
     [1.4, 8.3, 15.5, 17.1, 18.3, 27.2, 42.7]),
    ("Spectravideo SV-328  MS", "Z80", 3.6, False,
     [1.6, 5.4, 17.9, 19.6, 20.6, 30.7, 42.2]),
    ("ZX80  Sinclair", "Z80", 3.25, False,
     [1.5, 4.7, 9.2, 9.0, 12.7, 25.9, 39.2]),
    ("ZX Spectrum  Sinclair", "Z80", 3.58, False,
     [4.4, 8.2, 20.0, 19.2, 23.1, 53.4, 77.6]),
    ("TDL ZPU  Zapple", "Z80", 4.0, False,
     [1.7, 9.5, 20.6, 21.7, 23.7, 36.7, 52.4]),
    ("Altair 8800  Altair 4.0", "8080", 2.0, False,
     [1.7, 10.2, 21.0, 22.5, 24.3, 36.7, 52.4]),
]

# BM8's published times, same source. A shorter list than BM1-BM7's,
# and **Apple II Integer BASIC is not in it at all** -- Wozniak's
# interpreter has no LOG, no SIN and no floating point, so the one other
# integer BASIC in the set simply cannot run this benchmark.
REF8 = [
    ("ABC 800  BASIC II single", "Z80", 3.0, 29.0),
    ("BBC Micro  BBC BASIC", "6502", 2.0, 49.9),
    ("Apple II  Applesoft", "6502", 1.0, 55.5),
    ("Altair 8800  Altair 4.0", "8080", 2.0, 67.8),
    ("Acorn Electron  BBC BASIC", "6502A", 2.0, 72.53),
    ("Acorn Atom  System BASIC", "6502", 1.0, 92.0),
    ("VIC-20  MS BASIC", "6502", 1.0, 99.0),
    ("Commodore 64  MS BASIC", "6510", 1.0, 119.3),
    ("Luxor ABC 80  ABC BASIC", "Z80", 3.0, 136.0),
    ("ZX Spectrum  Sinclair", "Z80", 3.58, 239.1),
    ("TI-99/4A  TI BASIC", "9900", 3.0, 382.0),
]

# **The TRS-80 is missing on purpose.** It belongs in this table -- a
# 1.77 MHz Z80 running Level II BASIC is exactly the machine these
# benchmarks were aimed at, and Rugg and Feldman wrote a book of TRS-80
# programs. No BM1-BM7 times for it could be found in a source worth
# citing, and a number recalled rather than read is worse than a gap.
#
# **So are the 8086 and the NEC V20**, for the same reason. The 8088
# row is the IBM PC and is real; the V20 was a pin-compatible 8088
# replacement and an 8086 has the wider bus, so both would land near
# that row -- but "would land near" is an argument, not a measurement,
# and this table only carries measurements.


def run_cycles(code, syms, lines, blob=None):
    """Type a program, RUN it, and return the cycles RUN cost.

    `blob` is (address, bytes) put in memory before the program runs --
    how BM8 gets the float library there, standing in for the
    `LOAD "FP" AT` a person would type.
    """
    M = B.Machine(code, syms)
    M.settle()
    if blob is not None:
        at, data = blob
        M.m.bus.mem[at:at + len(data)] = data
    for ln in lines:
        M.cmd(ln)
    before = M.m.cpu.cycles
    M.cmd("RUN")
    M.settle(400_000_000)
    return M.m.cpu.cycles - before, M


# =====================================================================# **The numbers before floating point went in**, for BM1-BM7, measured
# the same way on the same machine. [D63] put fsav/fpair into `erel`'s
# hot path -- every `+ - * /` now saves its left operand and asks what
# type the pair is -- and that is not free. Keeping the old column is
# the only way to see what it cost, and standing rule 2 says report the
# number including when it got worse.
OLD = [0.049, 0.264, 0.545, 0.499, 0.701, 1.062, 1.767]


def main():
    print("  Rugg/Feldman BM1-BM8, in COOL8 BASIC on the machine")
    print()
    code, syms = B.build()

    mine = []
    for entry in BMS:
        name, about, body, baseline = entry[0], entry[1], entry[2], entry[3]
        sub = SUBDEF if len(entry) > 4 else []
        full, _ = run_cycles(code, syms, HEAD + body + TAIL + sub)
        # The same program with the loop taken out: the editor, the
        # parse, both PRINTs and the way back to the prompt, which the
        # stopwatch between S and E never counted either.
        base, _ = run_cycles(code, syms, HEAD + baseline + TAIL + sub)
        cyc = full - base
        secs = cyc / SYS_HZ
        mine.append(secs)
        print(f"  {name}  {about:<38} {cyc:>10,} cycles  {secs:7.3f} s")

    # **BM8 has to prove it computed something.** A loop whose body
    # quietly fails costs almost nothing and reports a wonderful time;
    # sim/test_lib.py measured nothing for a year exactly that way. So
    # it is run once more with the last value printed.
    chk = BMS[-1]
    _, M8 = run_cycles(code, syms,
                       HEAD + chk[2] + ["650 PRINT C#"] + TAIL)
    if not any("-0.50" in r for r in M8.screen()):
        for r in M8.screen():
            if r.strip():
                print("      " + r.strip())
        raise SystemExit("BM8 did not compute sin(100); no time reported")

    seven, bm8 = mine[:7], mine[7]

    print()
    print("  Against the machines these were written for, BM1-BM7")
    print("  (published seconds; COOL8 measured, and the same work")
    print("  scaled to 2 MHz -- no COOL8 was built or clocked there):")
    print()
    rows = [("COOL8 @ 8.375 MHz", "COOL8", 8.375, True, seven),
            ("COOL8 @ 2 MHz", "COOL8", 2.0, True,
             [s * 8.375 / 2.0 for s in seven]),
            ("COOL8 (OLD) @ 8.375 MHz", "COOL8", 8.375, True, OLD),
            ("COOL8 (OLD) @ 2 MHz", "COOL8", 2.0, True,
             [s * 8.375 / 2.0 for s in OLD])] + list(REF)
    rows.sort(key=lambda r: r[4][6])

    print(f"  {'':<26}{'CPU':>6}{'MHz':>6}" +
          "".join(f"{n:>8}" for n in ("BM1", "BM2", "BM3", "BM4",
                                      "BM5", "BM6", "BM7")))
    for name, cpu, mhz, integer, times in rows:
        mark = " *" if integer else "  "
        print(f"  {name:<26}{cpu:>6}{mhz:6.2f}" +
              "".join(f"{t:8.1f}" for t in times) + mark)
    print("    * integer BASIC: the only rows that compare like for like.")
    print("      OLD is this interpreter before floats went in, so the")
    print("      pair of COOL8 rows prices what the type check costs.")

    cost = [(n - o) / o * 100 for n, o in zip(seven, OLD)]
    print()
    print("  What floating point cost the integer path, per benchmark:")
    print("    " + "  ".join(f"{n} {c:+.0f}%" for n, c in zip(
        ("BM1", "BM2", "BM3", "BM4", "BM5", "BM6", "BM7"), cost)))

    print()
    print("  BM8 -- K^2, LOG(K), SIN(K), 100 times, in BASIC:")
    print()
    r8 = sorted(REF8 + [("COOL8 @ 8.375 MHz", "COOL8", 8.375, bm8),
                        ("COOL8 @ 2 MHz", "COOL8", 2.0, bm8 * 8.375 / 2.0)],
                key=lambda r: r[3])
    print(f"  {'':<28}{'CPU':>7}{'MHz':>6}{'BM8':>10}")
    for name, cpu, mhz, t in r8:
        print(f"  {name:<28}{cpu:>7}{mhz:6.2f}{t:10.2f}")
    print()
    print("  **Apple II Integer BASIC is absent from this one**, and that")
    print("  is the point of it: Wozniak's interpreter has no LOG, no SIN")
    print("  and no float at all, so the only other integer BASIC in the")
    print("  set cannot run BM8. This one can because [D63] made floats")
    print("  resident -- A#, ^, LOG and SIN are the language's own now.")
    print()
    print("  The margin is mostly precision: a 16-bit significand, about")
    print("  4.8 digits, against the ~9 of the 40-bit floats those BASICs")
    print("  carried. A shorter mantissa is a faster mantissa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
