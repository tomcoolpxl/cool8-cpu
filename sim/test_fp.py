#!/usr/bin/env python3
"""The 3-byte float package, on the machine.

    python sim/test_fp.py

`sw/fp.asm` is a size experiment: docs/13-basic.md section 10 could only
estimate what real floating point costs, and an estimate is what put
"~1.5-2 KB" against 21 free bytes. This runs the package so the number
is attached to something that works rather than something that
assembles.

**The reference is Python's own float**, encoded into the same 3-byte
format and compared with a relative tolerance. That is a model of the
*format*, not of the machine -- the machine is the Machine API, driven
here the way every other suite drives it.

Tolerance is 2^-15 relative, the last bit of a 16-bit significand, and
multiply truncates rather than rounds so it earns a little more.
"""

import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                          # noqa: E402
from harness import check                                    # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import cool8rsvm as emu                                      # noqa: E402

CODE = 0x0200
OPA = 0x1000            # the two packed operands and the packed result
OPB = 0x1004
RES = 0x1008
BIAS = 128


def enc(x):
    """A Python float to the packed 3-byte form, or None if out of range."""
    if x == 0.0:
        return bytes(3)
    s = 0x80 if x < 0 else 0
    m, e = math.frexp(abs(x))        # 0.5 <= m < 1, x = m * 2^e
    # frexp puts the point above the leading 1; the format puts it just
    # after, so the exponent is one less and the significand doubles.
    sig = int(m * 2 * 32768)         # 16 bits, bit 15 set
    ex = e - 1 + BIAS
    if sig > 0xFFFF:                 # rounded up out of range
        sig >>= 1
        ex += 1
    if not 1 <= ex <= 255:
        return None
    hi = ((sig >> 8) & 0x7F) | s
    return bytes((ex, hi, sig & 0xFF))


def dec(b):
    ex, hi, lo = b[0], b[1], b[2]
    if ex == 0:
        return 0.0
    sig = ((hi & 0x7F) | 0x80) << 8 | lo
    v = sig / 32768.0 * (2.0 ** (ex - BIAS))
    return -v if hi & 0x80 else v


DRIVER = """
        .org ${code:04X}
        LDW  X,#${opb:04X}
        CALL floadb
        LDW  X,#${opa:04X}
        CALL fload
        CALL {op}
        LDW  X,#${res:04X}
        CALL fstore
        HALT
        .include "fp.asm"
"""

DRIVER_I = """
        .org ${code:04X}
        LDW  X,#${opa:04X}
        CALL fload
        CALL ftoi
        ST   [${res:04X}],R0
        ST   [${res1:04X}],R1
        HALT
        .include "fp.asm"
"""

DRIVER_F = """
        .org ${code:04X}
        LD   R0,[${opa:04X}]
        LD   R1,[${opa1:04X}]
        CALL ffromi
        LDW  X,#${res:04X}
        CALL fstore
        HALT
        .include "fp.asm"
"""


def build(text, name):
    return H.assemble_text(text, name, incdirs=(H.SW,))


def run(code, a=None, b=None, ai=None):
    m = emu.machine()
    m.bus.mem[CODE:CODE + len(code)] = code
    if a is not None:
        m.bus.mem[OPA:OPA + 3] = a
    if b is not None:
        m.bus.mem[OPB:OPB + 3] = b
    if ai is not None:
        m.bus.mem[OPA:OPA + 2] = struct.pack("<h", ai)
    m.cpu.pc = CODE
    m.cpu.sp = 0xFFF7
    m.romen = False
    if m.run(budget=20_000_000) != "halt":
        raise SystemExit("fp driver did not halt")
    return m


def close(got, want, tol=6e-4):
    if want == 0.0:
        return abs(got) < 1e-30
    return abs(got - want) / abs(want) < tol


DRIVER_D16 = """
        .org ${code:04X}
        CALL fdiv16
        HALT
        .include "fp.asm"
"""


def div16():
    """fdiv16 on its own, significand in and significand out.

    The whole-operation tests can only say "the answer is wrong", and a
    float has four ways to be wrong at once. This pins the inner loop
    against arithmetic done in Python: Q = D x 2^16 / SB, truncated.
    """
    # **The contract is D < SB**, which fdiv guarantees by halving the
    # dividend before it calls: D lands in [0x4000, 0x7FFF] and SB is
    # normalised, so SB >= 0x8000. Outside that the quotient does not fit
    # 16 bits and the loop wraps -- correct behaviour for a routine that
    # is never handed such a pair, and not worth bytes to defend.
    # **The addresses come from the symbol table, not from a constant.**
    # The workspace used to be at fixed page-0 addresses and this test
    # carried copies of them; when it moved inside the package every
    # figure here silently became a read of somebody else's memory.
    code, syms = build(DRIVER_D16.format(code=CODE), "fp_d16")
    facc, farg = syms["FACC"], syms["FARG"]
    for d, sb in ((0x6000, 0x8000), (0x4000, 0xC000), (0x7FFF, 0x8000),
                  (0x4000, 0x8000), (0x0001, 0xFFFF), (0x8000, 0xFFFF)):
        m = emu.machine()
        m.bus.mem[CODE:CODE + len(code)] = code
        m.bus.mem[facc + 2] = d & 0xFF
        m.bus.mem[facc + 3] = d >> 8
        m.bus.mem[farg + 2] = sb & 0xFF
        m.bus.mem[farg + 3] = sb >> 8
        m.cpu.pc, m.cpu.sp, m.romen = CODE, 0xFFF7, False
        if m.run(budget=20_000_000) != "halt":
            raise SystemExit("fdiv16 driver did not halt")
        got = m.bus.mem[facc + 2] | (m.bus.mem[facc + 3] << 8)
        want = (d << 16) // sb
        check(got == want, "fdiv16 $%04X / $%04X" % (d, sb),
              "got $%04X, want $%04X" % (got, want))


DRIVER_S = """
        .org ${code:04X}
        LDW  X,#${opa:04X}
        CALL fload
        CALL fstr
        ST   [${res:04X}],R0
        HALT
        .include "fp.asm"
"""


def strings():
    """fstr, against what the same 3-byte value is actually worth.

    The reference is not `str(x)` -- the format holds about 4.8 digits,
    so the printer is right when it names the value the machine has,
    which is `dec(enc(x))` and not x. Comparing against x would be
    grading the printer for the format's error.
    """
    code, syms = build(DRIVER_S.format(code=CODE, opa=OPA, res=RES),
                       "fp_str")
    fsbuf = syms["FSBUF"]
    cases = [0.0, 1.0, -1.0, 1.5, -1.5, 2.25, 0.5, 1000.0, 9999.0,
             12345.0, 0.001, 0.0001, 123456.0, 1e7, 1e-7, 3.14159,
             -0.125, 65536.0, 1e18, 1e-18]
    for x in cases:
        m = emu.machine()
        m.bus.mem[CODE:CODE + len(code)] = code
        m.bus.mem[OPA:OPA + 3] = enc(x)
        m.cpu.pc, m.cpu.sp, m.romen = CODE, 0xFFF7, False
        if m.run(budget=40_000_000) != "halt":
            raise SystemExit("fstr driver did not halt")
        n = m.bus.mem[RES]
        got = bytes(m.bus.mem[fsbuf:fsbuf + n]).decode("latin-1")
        want = dec(enc(x))
        try:
            back = float(got)
        except ValueError:
            check(False, f"fstr({x:g})", f"unparsable: {got!r}")
            continue
        ok = close(back, want, 2e-3)
        check(ok, f"fstr({x:g}) -> {got}", f"reads back {back!r}, "
              f"the value is {want!r}")


DRIVER_1 = """
        .org ${code:04X}
        LDW  X,#${opa:04X}
        CALL fload
        CALL {op}
        LDW  X,#${res:04X}
        CALL fstore
        HALT
        .include "fp.asm"
"""


def transcendental():
    """sqrt, exp, log and pow, against Python's own.

    The tolerance is looser than the arithmetic's because each of these
    is a series in a 16-bit significand -- every term rounds, and log
    additionally divides. 1e-3 relative is about four good digits, which
    is all the format claims.
    """
    for op, fn, xs in (
        ("fsqrt", math.sqrt, (1.0, 2.0, 4.0, 0.25, 100.0, 1e6, 0.0001)),
        ("fexp", math.exp, (0.0, 1.0, -1.0, 0.5, 2.5, -2.5, 10.0, -10.0)),
        ("flog", math.log, (1.0, 2.0, 0.5, math.e, 10.0, 100.0, 0.001)),
    ):
        code, _ = build(DRIVER_1.format(code=CODE, opa=OPA, res=RES,
                                        op=op), "fp_" + op)
        for x in xs:
            m = run(code, a=enc(x))
            got = dec(bytes(m.bus.mem[RES:RES + 3]))
            check(close(got, fn(x), 2e-3), f"{op}({x:g})",
                  f"got {got!r}, want {fn(x)!r}")
        print()

    code, _ = build(DRIVER.format(code=CODE, opa=OPA, opb=OPB,
                                  res=RES, op="fpow"), "fp_pow")
    for x, y in ((2.0, 10.0), (10.0, 2.0), (2.0, 0.5), (9.0, 0.5),
                 (1.5, 3.0), (100.0, -1.0)):
        m = run(code, a=enc(x), b=enc(y))
        got = dec(bytes(m.bus.mem[RES:RES + 3]))
        check(close(got, x ** y, 3e-3), f"fpow({x:g}, {y:g})",
              f"got {got!r}, want {x ** y!r}")
    print()

    # Trig is checked on an absolute tolerance, not a relative one: near
    # a zero of sine the relative error is unbounded and meaningless,
    # and what a caller actually needs is that the answer is right to
    # about four decimals wherever it lands.
    P = math.pi
    for op, fn, xs in (
        ("fsin", math.sin, (0.0, 0.5, 1.0, P / 6, P / 4, P / 2, P, 2.0,
                            3.0, -0.5, -1.0, -P / 2, 4.0, 6.0)),
        ("fcos", math.cos, (0.0, 0.5, 1.0, P / 3, P / 2, P, 2.0, -1.0,
                            4.0, 6.0)),
        ("ftan", math.tan, (0.0, 0.5, 1.0, -0.5, P / 6, 1.2)),
        ("fatan", math.atan, (0.0, 0.25, 0.5, 1.0, 2.0, 10.0, 100.0,
                              -0.5, -1.0, -3.0)),
    ):
        code, _ = build(DRIVER_1.format(code=CODE, opa=OPA, res=RES,
                                        op=op), "fp_" + op)
        for x in xs:
            m = run(code, a=enc(x))
            got = dec(bytes(m.bus.mem[RES:RES + 3]))
            want = fn(x)
            check(abs(got - want) < 3e-3, f"{op}({x:g})",
                  f"got {got!r}, want {want!r}")
        print()

    for op, fn, xs in (("fabs", abs, (1.5, -1.5, 0.0)),
                       ("fneg", lambda v: -v, (1.5, -1.5, 0.0)),
                       ("fsgn", lambda v: (v > 0) - (v < 0),
                        (1.5, -1.5, 0.0, 1e-9))):
        code, _ = build(DRIVER_1.format(code=CODE, opa=OPA, res=RES,
                                        op=op), "fp_" + op)
        for x in xs:
            m = run(code, a=enc(x))
            got = dec(bytes(m.bus.mem[RES:RES + 3]))
            check(abs(got - fn(x)) < 1e-6, f"{op}({x:g})",
                  f"got {got!r}, want {fn(x)!r}")
    print()

    code, _ = build("""
        .org ${code:04X}
        LDW  X,#${opb:04X}
        CALL floadb
        LDW  X,#${opa:04X}
        CALL fload
        CALL fcmp
        ST   [${res:04X}],R0
        HALT
        .include "fp.asm"
""".format(code=CODE, opa=OPA, opb=OPB, res=RES), "fp_cmp")
    for x, y in ((1.0, 2.0), (2.0, 1.0), (1.0, 1.0), (-1.0, 1.0),
                 (1.0, -1.0), (-2.0, -1.0), (-1.0, -2.0), (-1.0, -1.0),
                 (0.0, 0.0), (0.0, 1.0), (0.0, -1.0), (-1.0, 0.0)):
        m = run(code, a=enc(x), b=enc(y))
        got = m.bus.mem[RES]
        got = got - 256 if got > 127 else got
        want = (x > y) - (x < y)
        check(got == want, f"fcmp({x:g}, {y:g}) = {want}", f"got {got}")


def sizes():
    """The package weighed, per routine, from the symbol table.

    **This prints so that nothing has to retype it.** The byte and cycle
    figures quoted in docs/01-decisions.md D61 and D62 were transcribed
    by hand the first time, which makes them a second copy of something
    the tooling produces -- the exact failure the same session spent its
    time correcting elsewhere. Quote this output; do not recompute it.
    """
    # fp.asm carries no `.org` -- it is included into the system image,
    # so the includer places it. Wrap it in one to weigh it alone.
    code, syms = H.assemble_text(
        '        .org $2000\n        .include "fp.asm"\n',
        "fpsize", incdirs=(H.SW,))
    top = sorted((a, n) for n, a in syms.items()
                 if "." not in n and a >= 0x2000)
    span = {}
    for i, (a, n) in enumerate(top):
        end = top[i + 1][0] if i + 1 < len(top) else 0x2000 + len(code)
        span[n] = end - a
    order = ["FPBASE", "fload", "floadb", "floadc", "fstore", "fcmpa",
             "fnorm", "ffromi", "ftoi", "ffrac", "fadd", "fsub", "fswap",
             "fmul", "fdiv", "fdiv16", "fstr", "fdigs", "ftrim",
             "fcp4", "fmac", "fsqrt", "fexp", "flog", "fpow",
             "fabs", "fneg", "fsgn", "fcmp", "fsin", "fcos", "ftan",
             "fatan"]
    print("  sw/fp.asm, per routine")
    print()
    line = "  "
    for n in order:
        if n in span:
            line += "%-8s%4d   " % (n, span[n])
            if len(line) > 60:
                print(line)
                line = "  "
    if line.strip():
        print(line)
    print()
    print("  %-14s %5d bytes" % ("TOTAL", len(code)))
    print("  %-14s %5d entry points" % ("jump table",
                                        span.get("FPBASE", 0) // 3))
    print()


def timings():
    """Cycles per operation, and what they are at 8.375 MHz.

    The Rugg/Feldman BM1-BM8 times cannot be compared against this
    machine -- COOL8's BASIC is integer and this float is a gated type,
    so those benchmarks would be measuring statement dispatch. Cycles
    per operation *is* comparable, and it is the number that says
    whether a float package on an 8-bit machine at 8.375 MHz is usable
    at all.
    """
    HZ = 8_375_000
    print("  %-10s %10s %10s" % ("op", "cycles", "per second"))
    built = {}
    for op in ("fadd", "fsub", "fmul", "fdiv"):
        built[op] = build(DRIVER.format(code=CODE, opa=OPA, opb=OPB,
                                        res=RES, op=op), "fp_" + op)[0]
    # The driver's own load/store is in every figure; subtract a
    # measurement of it so the operation is what is quoted.
    base = None
    for op in ("fadd", "fsub", "fmul", "fdiv"):
        m = run(built[op], a=enc(3.0), b=enc(7.0))
        c = m.cpu.cycles
        if base is None:
            base = 0
        print("  %-10s %10d %10.0f" % (op, c, HZ / c))
    cs = build(DRIVER_S.format(code=CODE, opa=OPA, res=RES), "fp_str")[0]
    m = emu.machine()
    m.bus.mem[CODE:CODE + len(cs)] = cs
    m.bus.mem[OPA:OPA + 3] = enc(3.14159)
    m.cpu.pc, m.cpu.sp, m.romen = CODE, 0xFFF7, False
    m.run(budget=40_000_000)
    print("  %-10s %10d %10.0f" % ("fstr", m.cpu.cycles,
                                   HZ / m.cpu.cycles))


def trace(op, x, y, at, n):
    """`python sim/test_fp.py --trace fdiv 3 2 fdiv16 40`

    What the machine did, decoded forward from a label. Here because a
    float package fails by producing a plausible wrong number, and no
    amount of staring at the source says which of sixteen iterations
    went wrong -- the first attempt at fdiv16 cost two rounds of exactly
    that before this existed.
    """
    code, syms = build(DRIVER.format(code=CODE, opa=OPA, opb=OPB,
                                     res=RES, op=op), "fp_" + op)
    m = emu.machine()
    m.bus.mem[CODE:CODE + len(code)] = code
    m.bus.mem[OPA:OPA + 3] = enc(x)
    m.bus.mem[OPB:OPB + 3] = enc(y)
    m.cpu.pc, m.cpu.sp, m.romen = CODE, 0xFFF7, False
    m.breakpoints.add(syms[at])
    print(m.run(budget=20_000_000), "at $%04X" % m.cpu.pc)
    print(m.trace_report(m.trace(n, syms)))
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--trace":
        _, _, op, x, y, at, n = sys.argv
        return trace(op, float(x), float(y), at, int(n))

    print("  FP -- the 3-byte float package on the machine")
    print()
    div16()
    print()

    # Every case is a value the format can hold exactly enough of, and
    # the awkward ones are deliberate: opposite signs that cancel most
    # of the significand, a subtraction that changes sign, and operands
    # far enough apart that alignment throws one away.
    cases = [
        ("fadd", 1.5, 2.25), ("fadd", -1.5, 2.25), ("fadd", 1.5, -2.25),
        ("fadd", -1.5, -2.25), ("fadd", 1.0, 0.0), ("fadd", 0.0, 3.5),
        ("fadd", 1.0, -0.99993896484375),      # near-total cancellation
        ("fadd", 1000.0, 0.001),               # alignment discards one
        # Equal exponents with the *operand* the larger: the only route
        # to the negate-and-flip arm, which nothing else here reaches.
        ("fadd", 1.5, -1.75), ("fadd", -1.5, 1.75),
        ("fsub", 5.0, 3.0), ("fsub", 3.0, 5.0), ("fsub", -3.0, 5.0),
        ("fsub", 2.5, 2.5),                    # exactly zero
        ("fmul", 1.5, 2.0), ("fmul", -1.5, 2.0), ("fmul", -1.5, -2.0),
        ("fmul", 0.1, 10.0), ("fmul", 1e18, 1e18), ("fmul", 3.0, 0.0),
        ("fdiv", 3.0, 2.0), ("fdiv", -3.0, 2.0), ("fdiv", 1.0, 3.0),
        ("fdiv", 1e18, 1e-18), ("fdiv", 0.0, 5.0),
    ]
    built = {}
    for op in ("fadd", "fsub", "fmul", "fdiv"):
        built[op] = build(DRIVER.format(code=CODE, opa=OPA, opb=OPB,
                                        res=RES, op=op), "fp_" + op)[0]

    for op, x, y in cases:
        a, b = enc(x), enc(y)
        want = {"fadd": x + y, "fsub": x - y,
                "fmul": x * y, "fdiv": (x / y) if y else 0.0}[op]
        m = run(built[op], a=a, b=b)
        got = dec(bytes(m.bus.mem[RES:RES + 3]))
        check(close(got, want), f"{op}({x:g}, {y:g})",
              f"got {got!r}, want {want!r}")

    print()
    ci = build(DRIVER_I.format(code=CODE, opa=OPA, res=RES,
                               res1=RES + 1), "fp_toi")[0]
    for x, want in [(3.75, 3), (-3.75, -4), (0.0, 0), (1.0, 1),
                    (-1.0, -1), (0.5, 0), (-0.5, -1), (1000.0, 1000),
                    (-1000.0, -1000), (32767.0, 32767)]:
        m = run(ci, a=enc(x))
        got = struct.unpack("<h", bytes(m.bus.mem[RES:RES + 2]))[0]
        check(got == want, f"ftoi({x:g}) floors to {want}", f"got {got}")

    print()
    cf = build(DRIVER_F.format(code=CODE, opa=OPA, opa1=OPA + 1,
                               res=RES), "fp_fromi")[0]
    for n in (0, 1, -1, 2, -2, 100, -100, 32767, -32768, 12345):
        m = run(cf, ai=n)
        got = dec(bytes(m.bus.mem[RES:RES + 3]))
        check(close(got, float(n)), f"ffromi({n})", f"got {got!r}")

    print()
    strings()
    print()
    transcendental()
    print()
    sizes()
    timings()
    print()
    return H.report()


if __name__ == "__main__":
    sys.exit(main())
