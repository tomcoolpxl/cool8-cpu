#!/usr/bin/env python3
"""Where a statement interpreter actually loses: three prototypes.

    python sim/bench_interp2.py

`sim/bench_interp.py` measured loop control and got 1.5x native. That is
the case statement dispatch flatters, because one dispatch covers a
whole iteration. These are the three that it does not:

  expression   `A = K + 3 - K`. Loop control dispatches once per
               iteration; an expression has to walk operands and
               operators one at a time, which is where most interpreters
               give back what they saved.
  subscript    `M(L) = A`. An address computation the compiler folds
               into two instructions and an interpreter has to do at
               run time, every time.
  call         `GOSUB` and `RETURN` against `CALL` and `RET`. The
               machine has a call instruction; an interpreter has to
               push its own return position and find the target.

Multiply is deliberately absent from the expression. It is a runtime
call in both models, so it would dilute the comparison equally while
telling us nothing -- the same reason `sim/bench_lang.py` leaves out
division.

Every pair is checked for the same answer before any timing is believed.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8vm as vm                                     # noqa: E402

N = 1000
CODE = 0x0200
SYM = {}


def build(name, text):
    path = os.path.join(BUILD, f"i2_{name}.asm")
    with open(path, "w") as fh:
        fh.write(text)
    out = os.path.join(BUILD, f"i2_{name}.bin")
    sym = os.path.join(BUILD, f"i2_{name}.sym")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), path,
                        "-o", out, "--symbols", sym],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stdout + r.stderr)
    SYM[name] = {}
    for line in open(sym):
        p = line.split()
        if len(p) == 2:
            SYM[name][p[1]] = int(p[0], 16)
    with open(out, "rb") as fh:
        return fh.read()


def run(code):
    m = vm.Machine()
    m.bus.mem[CODE:CODE + len(code)] = code
    m.cpu.pc = CODE
    m.cpu.sp = 0x7FF0
    m.romen = False
    if m.run(budget=80_000_000) != "halt":
        raise SystemExit("never halted")
    return m.cpu.cycles, m


def word(m, name, sym, off=0):
    a = SYM[name][sym] + off
    return m.bus.mem[a] | (m.bus.mem[a + 1] << 8)


# The loop that drives each benchmark N times, so what is measured is
# the statement and not the harness. Both sides use the identical
# counter, so it cancels.
DRIVE_HEAD = f"""
        .org ${CODE:04X}
        MOV  R0,#{N & 255}
        MOV  R1,#{N >> 8}
        ST   [n],R0
        ST   [n+1],R1
outer:  LD   R0,[n]
        LD   R1,[n+1]
        MOV  R2,R0
        OR   R2,R1
        BNE  .go
        HALT
.go:    SUB  R0,#1
        ST   [n],R0
        BCS  .ok
        LD   R1,[n+1]
        SUB  R1,#1
        ST   [n+1],R1
.ok:
"""
DRIVE_TAIL = """
        JMP  outer
n:      .word 0
"""

# ===================================================== 1. an expression
#
#   A = K + 3 - K
#
# native: the compiler's leaf-aware accumulator code.

EXPR_NATIVE = DRIVE_HEAD + """
        LD   R0,[vk]
        LD   R1,[vk+1]
        MOV  R2,#3
        MOV  R3,#0
        ADD  R0,R2
        ADC  R1,R3
        LD   R2,[vk]
        LD   R3,[vk+1]
        SUB  R0,R2
        SBC  R1,R3
        ST   [va],R0
        ST   [va+1],R1
""" + DRIVE_TAIL + """
vk:     .word 7
va:     .word 0
"""

# interpreted: LET dispatches once, then a term/operator walk.
#
#   $84 <var> <expr> $FF        LET
#   $C0 lo hi                   a constant
#   $C1 idx                     a variable
#   $D0 / $D1                   + / -
EXPR_INTERP = DRIVE_HEAD + """
        LDW  Y,#prog
        JMP  disp
disp:   LD   R0,[Y]
        INCW Y
        SUB  R0,#$84
        SHL  R0
        LDW  X,#sttab
        LD   R1,[X+R0]
        ADD  R0,#1
        LD   R2,[X+R0]
        MOV  XL,R1
        MOV  XH,R2
        JMP  [X]
sttab:  .word h_let
        .word h_end
h_end:
""" + DRIVE_TAIL + """
h_let:  LD   R0,[Y]             ; the target variable
        INCW Y
        SHL  R0
        ST   [tv],R0
        CALL term               ; first operand into R2:R3
        ST   [ac],R2
        ST   [ac+1],R3
.more:  LD   R0,[Y]
        CMP  R0,#$D0
        BEQ  .add
        CMP  R0,#$D1
        BEQ  .sub
        LDW  X,#vars            ; end of expression: store
        LD   R0,[tv]
        ADDW X,R0
        LD   R0,[ac]
        ST   [X],R0
        INCW X
        LD   R0,[ac+1]
        ST   [X],R0
        INCW Y                  ; step over the $FF
        JMP  disp
.add:   INCW Y
        CALL term
        LD   R0,[ac]
        LD   R1,[ac+1]
        ADD  R0,R2
        ADC  R1,R3
        ST   [ac],R0
        ST   [ac+1],R1
        JMP  .more
.sub:   INCW Y
        CALL term
        LD   R0,[ac]
        LD   R1,[ac+1]
        SUB  R0,R2
        SBC  R1,R3
        ST   [ac],R0
        ST   [ac+1],R1
        JMP  .more

; one operand into R2:R3
term:   LD   R0,[Y]
        INCW Y
        CMP  R0,#$C0
        BEQ  .con
        LD   R0,[Y]             ; a variable
        INCW Y
        SHL  R0
        LDW  X,#vars
        ADDW X,R0
        LD   R2,[X]
        INCW X
        LD   R3,[X]
        RET
.con:   LD   R2,[Y]
        INCW Y
        LD   R3,[Y]
        INCW Y
        RET

tv:     .byte 0
ac:     .word 0
vars:   .fill 52, 0
prog:   .byte $84, 0, $C1, 10, $D0, $C0, 3, 0, $D1, $C1, 10, $FF
        .byte $85
"""

# ====================================================== 2. a subscript
#
#   M(L) = A     with L = 5, A = 7
#
# native: base + L*2 folded into the address computation.

SUB_NATIVE = DRIVE_HEAD + """
        LD   R0,[vl]
        LD   R1,[vl+1]
        ADD  R0,R0
        ADC  R1,R1
        LDW  X,#arr
        ADDW X,R0
        LD   R0,[va]
        ST   [X],R0
        INCW X
        LD   R0,[va+1]
        ST   [X],R0
""" + DRIVE_TAIL + """
vl:     .word 5
va:     .word 7
arr:    .fill 64, 0
"""

SUB_INTERP = DRIVE_HEAD + """
        LDW  Y,#prog
disp:   LD   R0,[Y]
        INCW Y
        SUB  R0,#$86
        SHL  R0
        LDW  X,#sttab
        LD   R1,[X+R0]
        ADD  R0,#1
        LD   R2,[X+R0]
        MOV  XL,R1
        MOV  XH,R2
        JMP  [X]
sttab:  .word h_sto
        .word h_end
h_end:
""" + DRIVE_TAIL + """
; $86 <arr> <subscript var> <value var>
h_sto:  INCW Y                  ; which array -- one here
        LD   R0,[Y]             ; the subscript variable
        INCW Y
        SHL  R0
        LDW  X,#vars
        ADDW X,R0
        LD   R2,[X]
        INCW X
        LD   R3,[X]
        ADD  R2,R2              ; times the element width
        ADC  R3,R3
        LDW  X,#arr
        ADDW X,R2
        MOV  R0,XH              ; the high half of the subscript
        ADD  R0,R3
        MOV  XH,R0
        LD   R0,[Y]             ; the value variable
        INCW Y
        SHL  R0
        ST   [tv],R0
        MOVW  Y,X               ; keep the element address
        LDW  X,#vars
        LD   R0,[tv]
        ADDW X,R0
        LD   R2,[X]
        INCW X
        LD   R3,[X]
        MOVW  X,Y
        ST   [X],R2
        INCW X
        ST   [X],R3
        LDW  Y,#prog
        INCW Y
        INCW Y
        INCW Y
        INCW Y
        JMP  disp
tv:     .byte 0
; the same starting values the native version holds in its globals:
; variable 0 is A = 7, variable 11 is L = 5
vars:   .word 7
        .fill 20, 0
        .word 5
        .fill 28, 0
arr:    .fill 64, 0
prog:   .byte $86, 0, 11, 0
        .byte $87
"""

# ========================================================== 3. a call
#
# native: CALL and RET, which the machine does in hardware.

CALL_NATIVE = DRIVE_HEAD + """
        CALL sub
""" + DRIVE_TAIL + """
sub:    LD   R0,[vc]
        ADD  R0,#1
        ST   [vc],R0
        RET
vc:     .word 0
"""

# interpreted: GOSUB pushes the token position on its own stack and
# jumps to a target already resolved to an address -- so this measures
# the call, not a line search.
CALL_INTERP = DRIVE_HEAD + """
        LDW  Y,#prog
disp:   LD   R0,[Y]
        INCW Y
        SUB  R0,#$88
        SHL  R0
        LDW  X,#sttab
        LD   R1,[X+R0]
        ADD  R0,#1
        LD   R2,[X+R0]
        MOV  XL,R1
        MOV  XH,R2
        JMP  [X]
sttab:  .word h_gos
        .word h_ret
        .word h_inc
        .word h_end
h_end:
""" + DRIVE_TAIL + """
h_gos:  LD   R0,[Y]             ; target, already an address
        INCW Y
        LD   R1,[Y]
        INCW Y
        MOV  R2,YL              ; remember where to come back to
        ST   [rs],R2
        MOV  R2,YH
        ST   [rs+1],R2
        MOV  YL,R0
        MOV  YH,R1
        JMP  disp
h_ret:  LD   R0,[rs]
        MOV  YL,R0
        LD   R0,[rs+1]
        MOV  YH,R0
        JMP  disp
h_inc:  LD   R0,[vc]
        ADD  R0,#1
        ST   [vc],R0
        JMP  disp
rs:     .word 0
vc:     .word 0
prog:   .byte $88
        .word body
        .byte $8B
body:   .byte $8A, $89
"""


def case(title, nat, itp, check):
    cn, mn = run(build(title + "_n", nat))
    ci, mi = run(build(title + "_i", itp))
    a, b = check(mn, mi, title)
    ok = a == b
    print(f"  {title:<12}{cn:>10,}{ci:>12,}{ci/cn:>10.2f}x     "
          f"{a} vs {b}  {'ok' if ok else 'MISMATCH'}")
    return ok


def main():
    print("  Where a statement interpreter loses, against native code")
    print()
    print(f"  {'':<12}{'native':>10}{'interpreted':>12}{'ratio':>10}"
          f"     answers")
    good = True
    good &= case("expression", EXPR_NATIVE, EXPR_INTERP,
                 lambda mn, mi, t: (word(mn, t + "_n", "va"),
                                    word(mi, t + "_i", "vars")))
    good &= case("subscript", SUB_NATIVE, SUB_INTERP,
                 lambda mn, mi, t: (word(mn, t + "_n", "arr", 10),
                                    word(mi, t + "_i", "arr", 10)))
    good &= case("call", CALL_NATIVE, CALL_INTERP,
                 lambda mn, mi, t: (word(mn, t + "_n", "vc"),
                                    word(mi, t + "_i", "vc")))
    print()
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
