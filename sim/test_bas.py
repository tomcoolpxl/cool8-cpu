#!/usr/bin/env python3
"""M12 -- the compiler, against the code M10 wrote by hand.

    python sim/test_bas.py

`tools/cool8bas.py` compiles the six benchmarks from `sw/bench/*.bas`.
Each has to produce the right answer and to run within **15 %** of the
same benchmark hand-compiled in `sim/bench_lang.py`.

## Why that is the gate

A code generator is easy to write and hard to write *well*, and the
failure mode is silent: it compiles, it runs, it is 40 % slower than it
should be and nobody notices for a year. M10 established what good looks
like by writing the code out by hand. This is the check that the
compiler reaches it.

The comparison is not quite like for like and the differences are named
in the table: `FOR` is tested at the top, where the hand-written loop
tested at the bottom, and the compiler emits every forward conditional
branch long because one pass cannot see how far a block will run.
Both are correctness requirements, not sloppiness -- and both are why
the tolerance is 15 % and not zero.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
BENCH = os.path.join(ROOT, "sw", "bench")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

import cool8emu as emu                                   # noqa: E402
import cool8bas as bas                                   # noqa: E402

TOLERANCE = 0.15

# name, source, the variable holding the answer, the answer, and the
# clocks the same benchmark took hand-compiled in sim/bench_lang.py
CASES = [
    ("loop   BM1  FOR k = 1 TO 1000", "loop.bas", "k", 1001, 47_015),
    ("incr   BM2  k = k + 1 x1000", "incr.bas", "k", 1000, 47_015),
    ("arith  BM3  a = k*2+3-k", "arith.bas", "a", 1003, 200_015),
    ("calls  BM6  nested loop + SUB", "calls.bas", "k", 1000, 340_015),
    ("array  BM7  m(l) = k", "array.bas", "a", 1000, 505_055),
    ("sieve       Byte sieve 8190", "sieve.bas", "c", 1899, 3_069_408),
]


class Mem(emu.Bus):
    def __init__(self):
        self.mem = bytearray(0x10000)

    def read(self, a):
        return self.mem[a & 0xFFFF]

    def write(self, a, v):
        self.mem[a & 0xFFFF] = v & 0xFF


def build(src):
    """Compile, assemble, and hand back the image and the symbol map."""
    stem = os.path.join(BUILD, "bas_" + os.path.basename(src)[:-4])
    with open(os.path.join(BENCH, src)) as fh:
        asm = bas.compile_source(fh.read())
    with open(stem + ".asm", "w") as fh:
        fh.write(asm)
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"),
                        stem + ".asm", "-o", stem + ".bin",
                        "--symbols", stem + ".sym"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("assembly failed: " + src)
    syms = {}
    for line in open(stem + ".sym"):
        parts = line.split()
        if len(parts) == 2:
            syms[parts[1].lower()] = int(parts[0], 16)
    with open(stem + ".bin", "rb") as fh:
        return fh.read(), syms, stem


def run(code, limit=200_000_000):
    bus = Mem()
    bus.mem[bas.ORG:bas.ORG + len(code)] = code
    c = emu.Cool8(bus)
    c.reset()
    c.pc = bas.ORG
    c.sp = 0xFFF7
    n = 0
    while n < limit and not c.halted:
        c.step()
        n += 1
    if not c.halted:
        raise SystemExit("the program did not halt")
    return c.cycles, bus


# Programs that are not benchmarks: they check the compiler is a
# language rather than a benchmark-shaped thing. Answers only.
CORRECT = [
    ("recursion through stack parameters", "rec.bas",
     {"total": 55}),
    ("IF / ELSEIF / ELSE", "ifelse.bas", {"a": 334}),
    ("precedence, parentheses, unary minus", "prec.bas",
     {"a": 14, "b": 20, "c": 3, "d": 90, "e": 20}),
    # The outer loop runs three times: the inner one exits at a=21 on
    # the first pass and immediately on the next two, so a is 23.
    ("EXIT DO leaves the inner loop only", "exitdo.bas",
     {"a": 23, "b": 3}),
    ("several parameters, called twice", "args.bas", {"r": 579}),
]


def correctness():
    print("  Correctness, beyond the benchmarks")
    print()
    bad = []
    for label, src, want in CORRECT:
        code, syms, _ = build(src)
        _, bus = run(code)
        got = {}
        for name in want:
            a = syms.get("v_" + name)
            got[name] = (bus.mem[a] | (bus.mem[a + 1] << 8)) if a else None
        ok = got == want
        print(f"  {label:<44} {'ok' if ok else 'FAIL'}")
        if not ok:
            print(f"    got {got}, want {want}")
            bad.append(label)
    print()
    return bad


def main():
    bad = correctness()
    print("  M12 -- tools/cool8bas.py against M10's hand-written code")
    print()
    print(f"  {'benchmark':<32} {'compiled':>11} {'by hand':>11} "
          f"{'ratio':>7} {'bytes':>6}  answer")

    fails = list(bad)
    tc = th = 0
    for label, src, resvar, want, hand in CASES:
        code, syms, stem = build(src)
        # the compiler names a global `v_<name>`; find where it landed
        addr = syms.get("v_" + resvar)
        if addr is None:
            print(f"  {label:<32} no symbol v_{resvar} in the map")
            fails.append(label)
            continue
        cyc, bus = run(code)
        got = bus.mem[addr] | (bus.mem[addr + 1] << 8)
        r = cyc / hand
        ok = got == want and r <= 1 + TOLERANCE
        tc += cyc
        th += hand
        note = "ok" if ok else (
            f"WRONG got {got} want {want}" if got != want
            else f"{(r-1)*100:.0f} % over budget")
        print(f"  {label:<32} {cyc:11,} {hand:11,} {r:6.2f}x "
              f"{len(code):6,}  {got:<6} {note}")
        if not ok:
            fails.append(label)

    print()
    print(f"  {'TOTAL':<32} {tc:11,} {th:11,} {tc/th:6.2f}x")
    print()
    print(f"  GATE: within {TOLERANCE:.0%} of hand-written code -- "
          f"{'PASS' if not fails else 'FAIL'}")
    for f in fails:
        print(f"    over: {f}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
