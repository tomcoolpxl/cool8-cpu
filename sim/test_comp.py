#!/usr/bin/env python3
"""S4c -- symbols, expressions and control flow, on the machine.

    python sim/test_comp.py

`sw/comp.bas` compiles DIM, CONST and assignment, with the arithmetic
between them, straight to bytes. `tools/cool8bas.py` compiles the same
program on the PC. The bytes have to match, and so do the addresses the
variables land at -- getting the code right and the data layout wrong
would be a compiler that produces correct instructions about the wrong
memory.

## Why the addresses are checked separately

The cross-compiler writes its variables as a `.res` block after the
code and lets the assembler place them; the machine has no assembler, so
it places them itself -- every mention chains through emit.bas until the
end of the program and is patched then. Those are different mechanisms
that have to reach the same answer, so the answer is checked.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8vm as vm                                     # noqa: E402
import cool8bas as bas                                   # noqa: E402
from test_lex import keyword_bytes, store                # noqa: E402

ORG = 0x0200            # where the compiler itself runs
# Well clear of the driver. The compiler's own variables are laid out
# after its code, and it is 16 KB of code with 2 KB of tables -- at
# $4000 the source was being overwritten by the symbol pool that was
# meant to describe it, and the failure moved every time the driver
# changed size.
SRC = 0x8000            # the stored program it compiles
OUT = 0xA000            # and where it puts the result
FAILS = []

# The program under test. Chosen for what the generator has to decide:
# byte and word widths side by side, a literal adapting to each, a
# constant folded away, both shift directions including the >= 8 case
# that becomes a byte move, and a right operand that is a leaf at every
# width.
SOURCE = """CONST LIMIT = 100 + 23
DIM w AS INT
DIM b AS BYTE
DIM u AS CARD
DIM i AS INT
DIM tab(9) AS INT
DIM buf(255) AS BYTE
DIM big(200) AS INT
DIM scr(4095) AS BYTE AT $C000
w = 1000
b = 7
u = $ABCD
w = w + LIMIT
b = b + 1
b = b AND 15
w = w - b
u = u XOR $00FF
w = w << 1
w = w >> 8
b = b << 2
w = (w + 1) - LIMIT
w = 0 - w
' right operands that are not leaves, so the frame has to exist
w = (w + 1) - (b + 2)
u = (u XOR $0F0F) AND (u + 1)
b = (b + 1) - (b AND 3)
w = w - ((b + 1) + (b + 2))
IF (w + 1) > (b + 2) THEN
  w = w + 1
END IF
IF w > 10 THEN
  w = w - 1
END IF
IF b = 0 THEN
  b = 1
ELSE
  b = b - 1
END IF
IF w < 0 THEN
  w = 0
ELSEIF w > 999 THEN
  w = 999
ELSE
  w = w + 1
END IF
IF u >= $8000 THEN u = 0
DO WHILE w <> 0
  w = w - 1
  IF w = 5 THEN
    EXIT DO
  END IF
LOOP
DO
  b = b + 1
LOOP UNTIL b >= 200
FOR i = 1 TO 10
  w = w + i
NEXT i
FOR b = 0 TO LIMIT
  u = u + 1
NEXT
' the hardware: a known address is one instruction, a computed one is X
POKE $FE10, $80
POKE $FE12, 0
b = PEEK($FE22)
w = PEEK($FE23) + 1
POKE w, b
POKE w + 1, b + 2
POKE $FE24, PEEK($FE24) AND 15
u = PEEK(u + 1)
w = w + PEEK($FE70)
' arrays: a constant index is a constant address; a small one cannot
' carry into the high byte, a big one can
tab(0) = 1
tab(3) = w
buf(7) = b
buf(i) = b + 1
tab(i) = w + 1
big(i) = w
big(0) = 0
scr(0) = 65
scr(i + 1) = b
w = tab(0) + tab(i)
b = buf(3) - buf(i)
w = big(i) + big(2)
b = scr(i) XOR scr(0)
FOR i = 0 TO 9
  tab(i) = tab(i) + 1
NEXT
END
"""


def check(ok, what, detail=""):
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


DRIVER = """
INCLUDE "chars.bas"
INCLUDE "lex.bas"
INCLUDE "emit.bas"
INCLUDE "comp.bas"

progend = $8000 + {size}
CALL compile($8000, $A000)
POKE $7F00, cp AND 255
POKE $7F01, cp >> 8
POKE $7F02, cerr
POKE $7F03, nsym
POKE $7F04, tk
POKE $7F05, tsl
POKE $7F06, spend AND 255
' symbol 0 is the CONST, which is never placed; symbol 1 is w
POKE $7F07, labv(2) AND 255
POKE $7F08, labv(2) >> 8
POKE $7F09, ctmax
POKE $7F0A, ctmps
POKE $7F0B, tsb(0)
POKE $7F0C, nn
END
"""


def reference():
    """cool8bas on the same program: the bytes, and where v_* landed."""
    asm = bas.compile_source(SOURCE, OUT)
    apath = os.path.join(BUILD, "comp_ref.asm")
    with open(apath, "w") as fh:
        fh.write(asm)
    out = os.path.join(BUILD, "comp_ref.bin")
    sym = os.path.join(BUILD, "comp_ref.sym")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), apath,
                        "-o", out, "--symbols", sym,
                        "-I", os.path.join(ROOT, "sw")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("the reference would not assemble")
    addrs, hidden = {}, 0
    for line in open(sym):
        p = line.split()
        # a_* is an array, v_* a scalar; both are storage and both are
        # in the same block, so the first of either ends the code
        if len(p) == 2 and (p[1].startswith("v_") or p[1].startswith("a_")):
            addrs[p[1][2:]] = int(p[0], 16)
        # FOR evaluates its limit once, into a slot of its own
        elif len(p) == 2 and p[1].endswith("_lim"):
            hidden += 1
    return open(out, "rb").read(), addrs, hidden


def build_driver(size):
    asm = bas.compile_source(DRIVER.replace("{size}", str(size)), ORG)
    apath = os.path.join(BUILD, "comp_drv.asm")
    with open(apath, "w") as fh:
        fh.write(asm)
    out = os.path.join(BUILD, "comp_drv.bin")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), apath,
                        "-o", out, "-I", os.path.join(ROOT, "sw")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("the compiler would not compile")
    return open(out, "rb").read()


def main():
    print("  S4c -- sw/comp.bas, against cool8bas.py")
    print()

    want, waddr, hidden = reference()
    kw = keyword_bytes()
    stored = store(SOURCE.splitlines(), kw)

    code = build_driver(len(stored))
    print(f"  compiler: {len(code):,} bytes, compiling "
          f"{len(SOURCE.splitlines())} lines")

    m = vm.Machine()
    m.bus.mem[ORG:ORG + len(code)] = code
    m.bus.mem[SRC:SRC + len(stored)] = stored
    m.cpu.pc = ORG
    m.cpu.sp = 0xFFF7
    m.romen = False
    n, last = 0, -1
    while n < 250_000_000:
        if m.cpu.pc == last:
            break
        last = m.cpu.pc
        m.cpu.step()
        n += 1
    else:
        raise SystemExit("the compiler never finished")

    end = m.bus.mem[0x7F00] | (m.bus.mem[0x7F01] << 8)
    err = m.bus.mem[0x7F02]
    nsym = m.bus.mem[0x7F03]

    if not check(err == 0, "the machine compiled it without complaint",
                 f"error {err}, {nsym} symbols, "
                 f"{end - OUT} bytes emitted, tk=${m.bus.mem[0x7F04]:02X} "
                 f"tsl={m.bus.mem[0x7F05]} spend={m.bus.mem[0x7F06]} "
                 f"ctmax={m.bus.mem[0x7F09]} ctmps={m.bus.mem[0x7F0A]} "
                 f"tsb0={m.bus.mem[0x7F0B]!r} nn={m.bus.mem[0x7F0C]}"):
        print()
        print(f"FAIL -- {len(FAILS)}")
        return 1

    # The code stops where the first variable begins.
    codelen = min(waddr.values()) - OUT
    got = bytes(m.bus.mem[OUT:OUT + codelen])

    check(end - OUT == len(want),
          f"code and data together are {end - OUT} bytes, "
          f"the reference {len(want)}",
          f"{end - OUT} against {len(want)}")

    bad = [i for i in range(min(len(got), codelen))
           if got[i] != want[i]]
    check(not bad, f"and the {codelen} bytes of code are identical",
          f"{len(bad)} differ, first at +{bad[0]:04X}: "
          f"{got[bad[0]]:02X} against {want[bad[0]]:02X}" if bad else "")

    first = m.bus.mem[0x7F07] | (m.bus.mem[0x7F08] << 8)
    check(first == min(waddr.values()),
          f"the first variable is at ${first:04X}, as the assembler put it",
          f"${first:04X} against ${min(waddr.values()):04X}")

    # An AT array is laid over an address and gets no storage, so it
    # has no symbol on the reference side -- but the machine still
    # names it.
    consts = sum(1 for ln in SOURCE.splitlines()
                 if ln.strip().upper().startswith("CONST "))
    ats = sum(1 for ln in SOURCE.splitlines() if " AT " in ln.upper())
    want_n = len(waddr) + consts + hidden + ats
    check(nsym == want_n,
          f"{nsym} symbols: {len(waddr)} with storage, {consts} const, "
          f"{hidden} FOR limits, {ats} laid over an address",
          f"{nsym} against {want_n}")

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
