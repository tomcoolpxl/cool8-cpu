#!/usr/bin/env python3
"""A statement-dispatched interpreter, measured against native code.

    python sim/bench_interp.py

`sim/bench_dispatch.py` measured how control gets from one operation to
the next. This measures the thing that actually decides the design:
whether dispatching once per *statement* -- the BBC BASIC shape -- is
fast enough to give up compiling for.

The benchmark is BM1, `FOR K = 1 TO n: NEXT K`, which is pure loop
control and the same one `sim/bench_lang.py` measures for native code.
An empty loop is the worst case for an interpreter, because there is no
real work for the dispatch to be amortised over.

Three versions of the identical loop:

  native      what the compiler emits today
  interp      a token interpreter: statement dispatch through a table,
              a resident variable table so a name IS an address, and
              FOR/NEXT keeping its state on a small loop stack
  interp+     the same, with NEXT's common path -- increment, compare,
              branch back -- reached without going round the dispatch

The variables are resident and single-letter, as BBC BASIC's A%-Z% were:
`K` is not looked up, it is index 10 of a table at a known address.
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

N = 1000
CODE = 0x0200


SYM = {}


def build(name, text):
    path = os.path.join(BUILD, f"in_{name}.asm")
    with open(path, "w") as fh:
        fh.write(text)
    out = os.path.join(BUILD, f"in_{name}.bin")
    sym = os.path.join(BUILD, f"in_{name}.sym")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), path,
                        "-o", out, "--symbols", sym],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stdout + r.stderr)
    want = "k" if name == "native" else "vars"
    for line in open(sym):
        p = line.split()
        if len(p) == 2 and p[1] == want:
            SYM[name] = int(p[0], 16) + (0 if want == "k" else 20)
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


# --------------------------------------------------------------- native
#
# FOR K = 1 TO N: NEXT K, as the compiler emits it: the limit in a slot,
# the counter a global, tested at the top.

NATIVE = f"""
        .org ${CODE:04X}
        MOV  R0,#{N & 255}
        MOV  R1,#{N >> 8}
        ST   [lim],R0
        ST   [lim+1],R1
        MOV  R0,#1
        MOV  R1,#0
        ST   [k],R0
        ST   [k+1],R1
top:    LD   R0,[lim]
        LD   R1,[lim+1]
        LD   R2,[k]
        LD   R3,[k+1]
        SUB  R0,R2              ; limit - k; carry on while k <= limit
        SBC  R1,R3
        BGE  .go
        JMP  done
.go:    LD   R0,[k]
        LD   R1,[k+1]
        MOV  R2,#1
        MOV  R3,#0
        ADD  R0,R2
        ADC  R1,R3
        ST   [k],R0
        ST   [k+1],R1
        JMP  top
done:   HALT
k:      .word 0
lim:    .word 0
"""

# ---------------------------------------------------------- interpreter
#
# Tokens.  $80 FOR, $81 NEXT, $82 END.  A FOR carries its variable
# index and two 16-bit constants; a NEXT carries its variable index.
#
#   FOR K = 1 TO N   ->  $80 0A 01 00 <N>
#   NEXT K           ->  $81 0A
#   END              ->  $82

INTERP_HEAD = f"""
        .org ${CODE:04X}
        LDW  Y,#prog
disp:   LD   R0,[Y]
        INCW Y
        SUB  R0,#$80
        SHL  R0
        LDW  X,#sttab
        LD   R1,[X+R0]
        ADD  R0,#1
        LD   R2,[X+R0]
        MOV  XL,R1
        MOV  XH,R2
        JMP  [X]

sttab:  .word h_for
        .word h_next
        .word h_end

h_end:  HALT

; ---- FOR v = a TO b
;
; The variable index is doubled into the resident table, the start is
; stored, and the limit and the address of the statement after the FOR
; go on the loop stack. Nothing is searched for: `K` is index 10.
h_for:  LD   R0,[Y]             ; variable index
        INCW Y
        SHL  R0
        ST   [lv],R0
        LDW  X,#vars
        ADDW X,R0
        LD   R0,[Y]             ; start, low
        INCW Y
        ST   [X],R0
        LD   R0,[Y]             ; start, high
        INCW Y
        INCW X
        ST   [X],R0
        LD   R0,[Y]             ; limit
        INCW Y
        ST   [ll],R0
        LD   R0,[Y]
        INCW Y
        ST   [lh],R0
        MOV  R0,YL              ; where the body starts
        ST   [lb],R0
        MOV  R0,YH
        ST   [lb+1],R0
        JMP  disp

; ---- NEXT v
;
; The loop stack is one deep here, which is all this benchmark needs and
; costs the same per iteration as a real one: the state is read from
; fixed addresses either way.
h_next: INCW Y                  ; skip the variable index
nx:     LDW  X,#vars
        LD   R0,[lv]
        ADDW X,R0
        LD   R2,[X]
        INCW X
        LD   R3,[X]
        MOV  R0,#1
        ADD  R2,R0
        MOV  R0,#0
        ADC  R3,R0
        ST   [X],R3
        DECW X
        ST   [X],R2             ; v = v + 1
        LD   R0,[ll]
        LD   R1,[lh]
        SUB  R0,R2              ; limit - v
        SBC  R1,R3
        BLT  .out
"""

INTERP_TAIL_SLOW = """
        LD   R0,[lb]            ; back to the body
        MOV  YL,R0
        LD   R0,[lb+1]
        MOV  YH,R0
        JMP  disp
.out:   JMP  disp

lv:     .byte 0
ll:     .byte 0
lh:     .byte 0
lb:     .word 0
vars:   .fill 52, 0
prog:
"""

# The one shortcut worth having: an empty loop body means the token
# after the body start is the NEXT itself, so the common path can go
# straight back to `nx` instead of round the dispatch. A real
# interpreter does this by noticing the body is one statement long.
INTERP_TAIL_FAST = """
        LD   R0,[lb]
        MOV  YL,R0
        LD   R0,[lb+1]
        MOV  YH,R0
        LD   R0,[Y]             ; is the body just this NEXT again?
        CMP  R0,#$81
        BEQ  .again
        JMP  disp
.again: INCW Y
        INCW Y
        JMP  nx
.out:   JMP  disp

lv:     .byte 0
ll:     .byte 0
lh:     .byte 0
lb:     .word 0
vars:   .fill 52, 0
prog:
"""

PROG = f"""        .byte $80, 10, 1, 0, {N & 255}, {N >> 8}
        .byte $81, 10
        .byte $82
"""


def main():
    print("  BM1 -- FOR K = 1 TO 1000: NEXT K")
    print()
    out = []

    # Every version must leave K at the same value. A loop that is fast
    # and wrong is not a result.
    def kof(m, sym):
        a = SYM[sym]
        return m.bus.mem[a] | (m.bus.mem[a + 1] << 8)

    c, m = run(build("native", NATIVE))
    kn = kof(m, "native")
    out.append(("native", c))

    c, m = run(build("interp", INTERP_HEAD + INTERP_TAIL_SLOW + PROG))
    k1 = kof(m, "interp")
    out.append(("interpreted", c))

    c, m = run(build("interp2", INTERP_HEAD + INTERP_TAIL_FAST + PROG))
    k2 = kof(m, "interp2")
    out.append(("interpreted, tight NEXT", c))

    ok = kn == k1 == k2 == N + 1
    print(f"  K after the loop: native {kn}, interpreted {k1}, "
          f"tight {k2}   {'ok' if ok else 'MISMATCH'}")
    if not ok:
        return 1
    print()

    base = out[0][1]
    print(f"  {'':<26}{'clocks':>12}{'per iteration':>15}{'vs native':>12}")
    for name, cycles in out:
        print(f"  {name:<26}{cycles:>12,}{cycles/N:>15.1f}"
              f"{cycles/base:>11.2f}x")
    print()
    print(f"  at 8.375 MHz, {N} iterations:")
    for name, cycles in out:
        print(f"    {name:<26}{1000*cycles/8_375_000:>8.2f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
