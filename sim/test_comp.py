#!/usr/bin/env python3
"""S4b -- symbols and expressions, compiled on the machine.

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
SRC = 0x4000            # the stored program it compiles
OUT = 0x6000            # and where it puts the result
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

progend = $4000 + {size}
CALL compile($4000, $6000)
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
    addrs = {}
    for line in open(sym):
        p = line.split()
        if len(p) == 2 and p[1].startswith("v_"):
            addrs[p[1][2:]] = int(p[0], 16)
    return open(out, "rb").read(), addrs


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
    print("  S4b -- sw/comp.bas, against cool8bas.py")
    print()

    want, waddr = reference()
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
    while n < 40_000_000:
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
                 f"tsl={m.bus.mem[0x7F05]} spend={m.bus.mem[0x7F06]}"):
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

    check(nsym == len(waddr) + 1,
          f"{nsym} symbols, the reference {len(waddr)} variables "
          f"and a constant",
          f"{nsym} against {len(waddr) + 1}")

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
