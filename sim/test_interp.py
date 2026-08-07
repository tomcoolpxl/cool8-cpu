#!/usr/bin/env python3
"""I1 -- the interpreter core, against native code.

    python sim/test_interp.py

`sw/interp.asm` executes the stored program directly. This runs three
programs through it, requires the same answers as the equivalent native
code, and then reports what the interpretation cost.

The answers come first. A fast interpreter that computes the wrong thing
is not a result, and the last two benchmarks in this project both
disagreed on their first run -- once because the native side had `<`
where BASIC means `<=`, once because the interpreted side's variables
were never initialised.
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

CODE = 0x0200
VARS = 0x0040
FAILS = []

T_LET, T_FOR, T_NEXT, T_END = 0x80, 0x81, 0x82, 0x83
E_CON, E_VAR, E_ADD, E_SUB, E_EOX = 0xC0, 0xC1, 0xD0, 0xD1, 0xFF


def con(v):
    return [E_CON, v & 0xFF, (v >> 8) & 0xFF]


def var(i):
    return [E_VAR, i]


def build(name, text):
    path = os.path.join(BUILD, f"ti_{name}.asm")
    with open(path, "w") as fh:
        fh.write(text)
    out = os.path.join(BUILD, f"ti_{name}.bin")
    sym = os.path.join(BUILD, f"ti_{name}.sym")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), path,
                        "-o", out, "--symbols", sym,
                        "-I", os.path.join(ROOT, "sw")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stdout + r.stderr)
    syms = {}
    for line in open(sym):
        p = line.split()
        if len(p) == 2:
            syms[p[1]] = int(p[0], 16)
    with open(out, "rb") as fh:
        return fh.read(), syms


def go(code, prog=None, at=0x3000):
    m = vm.Machine()
    m.bus.mem[CODE:CODE + len(code)] = code
    if prog:
        m.bus.mem[at:at + len(prog)] = bytes(prog)
    m.cpu.pc = CODE
    m.cpu.sp = 0x7FF0
    m.romen = False
    last = -1
    for _ in range(80_000_000):
        if m.cpu.pc == last:
            break
        last = m.cpu.pc
        m.cpu.step()
    else:
        raise SystemExit("never halted")
    return m.cpu.cycles, m


def v(m, i):
    a = VARS + 2 * i
    return m.bus.mem[a] | (m.bus.mem[a + 1] << 8)


HARNESS = """
        .org $0200
        MOV  R0,#$00
        ST   [$0010],R0
        MOV  R0,#$30
        ST   [$0011],R0
        CALL run
        HALT
        .include "interp.asm"
"""


def check(ok, what, detail=""):
    print(f"  {what:<44} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


CASES = [
    # name, program, native equivalent, the variable to compare
    ("A = 7",
     [T_LET, 0] + con(7) + [E_EOX, T_END],
     """
        MOV  R0,#7
        MOV  R1,#0
        ST   [$0040],R0
        ST   [$0041],R1
        HALT
""", 0, 7),

    ("A = K + 3 - K",
     [T_LET, 0] + var(10) + [E_ADD] + con(3) + [E_SUB] + var(10)
     + [E_EOX, T_END],
     """
        MOV  R0,#7
        MOV  R1,#0
        ST   [$0054],R0
        ST   [$0055],R1
        LD   R0,[$0054]
        LD   R1,[$0055]
        MOV  R2,#3
        MOV  R3,#0
        ADD  R0,R2
        ADC  R1,R3
        LD   R2,[$0054]
        LD   R3,[$0055]
        SUB  R0,R2
        SBC  R1,R3
        ST   [$0040],R0
        ST   [$0041],R1
        HALT
""", 0, 3),

    ("FOR K = 1 TO 1000: NEXT K",
     [T_FOR, 10] + con(1) + [E_EOX] + con(1000) + [E_EOX,
      T_NEXT, 10, T_END],
     """
        MOV  R0,#1
        MOV  R1,#0
        ST   [$0054],R0
        ST   [$0055],R1
top:    MOV  R0,#$E8
        MOV  R1,#3
        LD   R2,[$0054]
        LD   R3,[$0055]
        SUB  R0,R2
        SBC  R1,R3
        BGE  .go
        JMP  done
.go:    LD   R0,[$0054]
        LD   R1,[$0055]
        MOV  R2,#1
        MOV  R3,#0
        ADD  R0,R2
        ADC  R1,R3
        ST   [$0054],R0
        ST   [$0055],R1
        JMP  top
done:   HALT
""", 10, 1001),
]


def main():
    print("  I1 -- sw/interp.asm, against native code")
    print()
    code, syms = build("interp", HARNESS)
    size = max(syms.values()) - CODE
    print(f"  interpreter core: about {size:,} bytes")
    print()
    print(f"  {'':<30}{'native':>10}{'interp':>10}{'ratio':>9}   answer")
    for name, prog, nat, idx, want in CASES:
        # the interpreted run needs K seeded where the native one sets it
        pre = ""
        if idx == 0 and "K" in name:
            pre = ("        MOV  R0,#7\n        MOV  R1,#0\n"
                   "        ST   [$0054],R0\n        ST   [$0055],R1\n")
        h = HARNESS.replace("        CALL run", pre + "        CALL run")
        c_i, mi = go(build("i_" + name[:4], h)[0], prog)
        c_n, mn = go(build("n_" + name[:4],
                           f"        .org $0200\n{nat}")[0])
        gi, gn = v(mi, idx), v(mn, idx)
        ok = gi == gn == want
        print(f"  {name:<30}{c_n:>10,}{c_i:>10,}{c_i/c_n:>8.2f}x"
              f"   {gi} vs {gn}  {'ok' if ok else 'MISMATCH'}")
        if not ok:
            FAILS.append(name)
    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
