#!/usr/bin/env python3
"""I2 -- the interpreter, executing the editor's own stored programs.

    python sim/test_interp.py

`sw/interp.asm` walks the form the editor writes -- `lineno | len |
tokens` -- with the editor's own token bytes. Each case here is built
the way `sw/basic.bas` would store it, run, and checked against the
answer a person would expect.

I1 got this wrong in a way worth recording: it invented a private token
space where `$80` meant LET, and `$80` is `PRINT` in the editor's
`TOKTAB`. It worked only because the test poked its own bytes into
memory and never met a real program.

Numeric literals are stored as token `$A4` and two binary bytes rather
than as ASCII digits. The editor's tokeniser does not do that yet -- I2
adds it -- but the interpreter is written against it, because otherwise
every iteration of a loop re-parses decimal.
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
PROG = 0x3000
VARS = 0x0040
FAILS = []

# the editor's tokens, TOKTAB order
K = {n: 0x80 + i for i, n in enumerate(
    "PRINT SUB FUNCTION DIM CONST FOR NEXT TO DO LOOP WHILE UNTIL EXIT "
    "IF THEN ELSE ELSEIF END RETURN CALL AS INT BYTE PEEK POKE AND OR "
    "XOR CARD AT ASM EXTERN INCLUDE INLINE GOTO WEND".split())}
K["NUM"] = 0xA4


def num(v):
    return [K["NUM"], v & 0xFF, (v >> 8) & 0xFF]


def name(s):
    return [ord(c) for c in s]


def line(n, *parts):
    """One stored record: lineno, len, tokens."""
    toks = []
    for p in parts:
        toks += p if isinstance(p, list) else [ord(p)] if isinstance(p, str) \
            and len(p) == 1 else name(p)
    return [n & 0xFF, n >> 8, len(toks)] + toks + [0]


def program(*lines):
    out = []
    for ln in lines:
        out += ln
    return out


def build(name_, text):
    path = os.path.join(BUILD, f"ti_{name_}.asm")
    with open(path, "w") as fh:
        fh.write(text)
    out = os.path.join(BUILD, f"ti_{name_}.bin")
    sym = os.path.join(BUILD, f"ti_{name_}.sym")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), path,
                        "-o", out, "--symbols", sym,
                        "-I", os.path.join(ROOT, "sw")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stdout + r.stderr)
    syms = {}
    for ln in open(sym):
        p = ln.split()
        if len(p) == 2:
            syms[p[1]] = int(p[0], 16)
    with open(out, "rb") as fh:
        return fh.read(), syms


# The interpreter needs three of the editor's routines. In the real
# system they are basic.bas's; here they are stubs that record what was
# asked for, so PRINT can be checked without a screen.
HARNESS = """
        .org $0200
        MOV  R0,#<prog
        ST   [$0014],R0
        MOV  R0,#>prog
        ST   [$0015],R0
        ; $0016 (PEND) is written by the harness before the run
        CALL irun
        HALT

; ---- stubs standing in for sw/basic.bas
s_putn: LD   R0,[SP+2]          ; remember the last number printed
        ST   [printed],R0
        LD   R0,[SP+3]
        ST   [printed+1],R0
        LD   R0,[nprint]
        ADD  R0,#1
        ST   [nprint],R0
        RET
s_newline:
        RET
s_findline:
        LDW  X,#prog
.fl:    LD   R0,[X]             ; this record's line number
        INCW X
        LD   R1,[X]
        INCW X
        LD   R2,[SP+2]
        LD   R3,[SP+3]
        SUB  R0,R2
        SBC  R1,R3
        OR   R0,R1
        BEQ  .hit
        LD   R0,[X]             ; skip its tokens and the zero
        INCW X
        ADDW X,R0
        INCW X
        BRA  .fl
.hit:   DECW X
        DECW X
        MOV  R0,XL
        MOV  R1,XH
        RET

printed:  .word 0
nprint:   .byte 0
        .include "interp.asm"
prog:
"""


def check(ok, what, detail=""):
    print(f"  {what:<46} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


CASES = [
    ("A = 7",
     program(line(10, name("A"), "=", num(7)), line(20, [K["END"]])),
     {0: 7}),

    ("A = 2 + 3 * 4",
     program(line(10, name("A"), "=", num(2), "+", num(3), "*", num(4)),
             line(20, [K["END"]])),
     {0: 14}),

    ("A = (2 + 3) * 4",
     program(line(10, name("A"), "=", "(", num(2), "+", num(3), ")", "*",
                  num(4)),
             line(20, [K["END"]])),
     {0: 20}),

    ("A = 0 - 5 + 100",
     program(line(10, name("A"), "=", "-", num(5), "+", num(100)),
             line(20, [K["END"]])),
     {0: 95}),

    ("K = 3 : A = K * K",
     program(line(10, name("K"), "=", num(3)),
             line(20, name("A"), "=", name("K"), "*", name("K")),
             line(30, [K["END"]])),
     {0: 9, 10: 3}),

    ("IF 1 = 1 THEN A = 5",
     program(line(10, [K["IF"]], num(1), "=", num(1), [K["THEN"]],
                  name("A"), "=", num(5)),
             line(20, [K["END"]])),
     {0: 5}),

    ("IF 1 = 2 THEN A = 5  (not taken)",
     program(line(10, name("A"), "=", num(9)),
             line(20, [K["IF"]], num(1), "=", num(2), [K["THEN"]],
                  name("A"), "=", num(5)),
             line(30, [K["END"]])),
     {0: 9}),

    ("A < B comparisons",
     program(line(10, name("A"), "=", num(3), "<", num(9)),
             line(20, name("B"), "=", num(9), "<", num(3)),
             line(30, name("C"), "=", num(4), ">=", num(4)),
             line(40, [K["END"]])),
     {0: 1, 1: 0, 2: 1}),

    ("FOR K = 1 TO 10: NEXT K",
     program(line(10, [K["FOR"]], name("K"), "=", num(1), [K["TO"]],
                  num(10)),
             line(20, [K["NEXT"]], name("K")),
             line(30, [K["END"]])),
     {10: 11}),

    ("FOR K = 1 TO 5: S = S + K: NEXT",
     program(line(10, [K["FOR"]], name("K"), "=", num(1), [K["TO"]],
                  num(5)),
             line(20, name("S"), "=", name("S"), "+", name("K")),
             line(30, [K["NEXT"]]),
             line(40, [K["END"]])),
     {18: 15, 10: 6}),

    ("POKE and PEEK",
     program(line(10, [K["POKE"]], num(0x2000), ",", num(65)),
             line(20, name("A"), "=", [K["PEEK"]], "(", num(0x2000), ")"),
             line(30, [K["END"]])),
     {0: 65}),
]


def main():
    print("  I2 -- sw/interp.asm, on the editor's stored form")
    print()
    code, syms = build("interp", HARNESS)
    print(f"  interpreter: {syms['prog'] - syms['irun']:,} bytes")
    print()
    for name_, prog, want in CASES:
        m = vm.Machine()
        m.bus.mem[CODE:CODE + len(code)] = code
        at = syms["prog"]
        m.bus.mem[at:at + len(prog)] = bytes(prog)
        # progend is one past the last record
        end = at + len(prog)
        m.cpu.pc = CODE
        m.cpu.sp = 0x7FF0
        m.romen = False
        # patch the progend the harness loaded
        m.bus.mem[0x0016] = end & 0xFF
        m.bus.mem[0x0017] = end >> 8
        last = -1
        for _ in range(20_000_000):
            if m.cpu.pc == last:
                break
            last = m.cpu.pc
            m.cpu.step()
        else:
            check(False, name_, "never halted")
            continue
        got = {i: m.bus.mem[VARS + 2 * i] | (m.bus.mem[VARS + 2 * i + 1] << 8)
               for i in want}
        ok = got == want
        check(ok, name_, f"got {got}, wanted {want}" if not ok else "")
    # ---- the open question: what does an expression cost in a loop?
    #
    # I1 reported 6.09x for a single statement, which is fixed overhead
    # against almost nothing. This is the same expression a thousand
    # times, which is the number that decides the design.
    bench = program(
        line(10, [K["FOR"]], name("K"), "=", num(1), [K["TO"]], num(1000)),
        line(20, name("A"), "=", name("K"), "+", num(3), "-", name("K")),
        line(30, [K["NEXT"]]),
        line(40, [K["END"]]))
    m = vm.Machine()
    m.bus.mem[CODE:CODE + len(code)] = code
    at = syms["prog"]
    m.bus.mem[at:at + len(bench)] = bytes(bench)
    end = at + len(bench)
    m.cpu.pc = CODE
    m.cpu.sp = 0x7FF0
    m.romen = False
    m.bus.mem[0x0016] = end & 0xFF
    m.bus.mem[0x0017] = end >> 8
    last = -1
    for _ in range(80_000_000):
        if m.cpu.pc == last:
            break
        last = m.cpu.pc
        m.cpu.step()
    got = m.bus.mem[VARS + 20] | (m.bus.mem[VARS + 21] << 8)
    # the native equivalent, as the compiler emits it
    nat, _ = build("bnat", """
        .org $0200
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
        LD   R0,[$0054]
        LD   R1,[$0055]
        MOV  R2,#1
        MOV  R3,#0
        ADD  R0,R2
        ADC  R1,R3
        ST   [$0054],R0
        ST   [$0055],R1
        JMP  top
done:   HALT
""")
    mn = vm.Machine()
    mn.bus.mem[CODE:CODE + len(nat)] = nat
    mn.cpu.pc = CODE
    mn.cpu.sp = 0x7FF0
    mn.romen = False
    last = -1
    for _ in range(80_000_000):
        if mn.cpu.pc == last:
            break
        last = mn.cpu.pc
        mn.cpu.step()
    kn = mn.bus.mem[0x0054] | (mn.bus.mem[0x0055] << 8)
    print()
    check(got == kn == 1001,
          f"1000 x  A = K + 3 - K   (K ends {got}, native {kn})")
    print(f"    native {mn.cpu.cycles:,} clocks, interpreted "
          f"{m.cpu.cycles:,} -- {m.cpu.cycles/mn.cpu.cycles:.2f}x")

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
