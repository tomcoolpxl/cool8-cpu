#!/usr/bin/env python3
"""M10 -- the language benchmark, run before the compiler exists.

    python sim/bench_lang.py

Six benchmarks, written once as a tiny IR, emitted two ways, and
measured on the real instruction set by tools/cool8emu.py.

  native    leaf-aware accumulator code generation, OS_PLAN section 4.1
  bytecode  a stack machine with a token dispatch loop, FastBasic's model

**Both emitters run the same program and must produce the same answer.**
That is the cross-check: two independent back ends agreeing on 1899
primes is what says this measures code generation rather than a bug in
one of them.

## Why this runs before the compiler

OS_PLAN's whole shape rests on native code being worth its size, and the
evidence for that was one hand-written addition. This project has been
wrong that way before: D43 was a limit asserted in a comment for two
milestones and it was off by 60 %. So the gate runs first -- if native
is not at least 3x bytecode on real programs, the execution decision
reopens before a line of compiler is written.

## What is deliberately not modelled

The standard BM3 and BM4 divide. Division is a runtime CALL in both
models, so it would dilute the comparison equally while needing a
routine nothing else here wants; BM3 multiplies instead. Multiply is the
more interesting case anyway -- it is the boundary where a one-pass
compiler stops inlining and calls the runtime. BM8 is trigonometric and
belongs to the float library, which is a separate question.

Neither emitter optimises. There is no peephole pass, no register
allocation across statements and no constant folding: every statement
loads what it needs and stores what it made. That is what a one-pass
compiler emits and it is the thing being measured.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8emu as emu                                   # noqa: E402

# ---- where things live in the emitted programs
CODE = 0x0200
VARS = 0x1000            # 16-bit variables, two bytes each
ARR = 0x2000             # the sieve's flags and BM7's array
BC = 0x6000              # the bytecode stream, for the byte model

VN = {}                  # name -> address


def var(n):
    if n not in VN:
        VN[n] = VARS + 2 * len(VN)
    return VN[n]


# =====================================================================
# The benchmarks, as a tiny IR
#
# leaf  = ('v', name) | ('i', n)
# stmt  = ('set', name, leaf)
#       | ('bin', name, op, leafL, leafR)      name = L op R
#       | ('lbl', name)
#       | ('br', cond, leafL, leafR, label)    branch if L cond R
#       | ('jmp', label)
#       | ('call', label) | ('ret',)
#       | ('ldx', name, base, leaf, w)         name = mem[base + leaf*w]
#       | ('stx', base, leaf, w, leafV)        mem[base + leaf*w] = V
#       | ('halt',)
# =====================================================================

def bm_loop():
    """BM1 -- FOR K = 1 TO 1000: NEXT K.  Pure loop control."""
    return [('set', 'k', ('i', 1)),
            ('lbl', 'L'),
            ('bin', 'k', '+', ('v', 'k'), ('i', 1)),
            ('br', 'lo', ('v', 'k'), ('i', 1001), 'L'),
            ('halt',)], 'k', 1001


def bm_incr():
    """BM2 -- K = K + 1 until 1000.  Assignment, compare, branch."""
    return [('set', 'k', ('i', 0)),
            ('lbl', 'L'),
            ('bin', 'k', '+', ('v', 'k'), ('i', 1)),
            ('br', 'lo', ('v', 'k'), ('i', 1000), 'L'),
            ('halt',)], 'k', 1000


def bm_arith():
    """BM3-like -- A = K*2 + 3 - K inside the loop.

    The standard BM3 divides; division is a runtime CALL in all three
    models and would dilute the comparison equally while adding a
    routine none of this needs. Multiply is kept, because multiply IS
    the interesting case: it is the boundary where a one-pass compiler
    stops inlining and calls the runtime.
    """
    return [('set', 'k', ('i', 0)),
            ('lbl', 'L'),
            ('bin', 'k', '+', ('v', 'k'), ('i', 1)),
            ('bin', 'a', '*', ('v', 'k'), ('i', 2)),
            ('bin', 'a', '+', ('v', 'a'), ('i', 3)),
            ('bin', 'a', '-', ('v', 'a'), ('v', 'k')),
            ('br', 'lo', ('v', 'k'), ('i', 1000), 'L'),
            ('halt',)], 'a', (1000 * 2 + 3 - 1000)


def bm_calls():
    """BM6-like -- an inner FOR of 5 and a call, per outer iteration."""
    return [('set', 'k', ('i', 0)),
            ('lbl', 'L'),
            ('bin', 'k', '+', ('v', 'k'), ('i', 1)),
            ('set', 'l', ('i', 0)),
            ('lbl', 'I'),
            ('bin', 'l', '+', ('v', 'l'), ('i', 1)),
            ('call', 'SUB1'),
            ('br', 'lo', ('v', 'l'), ('i', 5), 'I'),
            ('br', 'lo', ('v', 'k'), ('i', 1000), 'L'),
            ('halt',),
            ('lbl', 'SUB1'),
            ('ret',)], 'k', 1000


def bm_array():
    """BM7-like -- M(L) = A, a word array indexed in the inner loop."""
    return [('set', 'k', ('i', 0)),
            ('lbl', 'L'),
            ('bin', 'k', '+', ('v', 'k'), ('i', 1)),
            ('set', 'l', ('i', 0)),
            ('lbl', 'I'),
            ('bin', 'l', '+', ('v', 'l'), ('i', 1)),
            ('stx', ARR, ('v', 'l'), 2, ('v', 'k')),
            ('br', 'lo', ('v', 'l'), ('i', 5), 'I'),
            ('br', 'lo', ('v', 'k'), ('i', 1000), 'L'),
            ('ldx', 'a', ARR, ('i', 5), 2),
            ('halt',)], 'a', 1000


def bm_sieve():
    """The Byte sieve, 8190. The answer is 1899 primes."""
    SIZE = 8190
    return [('set', 'c', ('i', 0)),
            # for i = 0 to SIZE: flags(i) = 1
            ('set', 'i', ('i', 0)),
            ('lbl', 'F'),
            ('stx', ARR, ('v', 'i'), 1, ('i', 1)),
            ('bin', 'i', '+', ('v', 'i'), ('i', 1)),
            ('br', 'lo', ('v', 'i'), ('i', SIZE + 1), 'F'),
            # for i = 0 to SIZE
            ('set', 'i', ('i', 0)),
            ('lbl', 'M'),
            ('ldx', 't', ARR, ('v', 'i'), 1),
            ('br', 'eq', ('v', 't'), ('i', 0), 'N'),
            ('bin', 'p', '+', ('v', 'i'), ('v', 'i')),
            ('bin', 'p', '+', ('v', 'p'), ('i', 3)),        # prime
            ('bin', 'j', '+', ('v', 'i'), ('v', 'p')),      # k = i + prime
            ('lbl', 'K'),
            ('br', 'hs', ('v', 'j'), ('i', SIZE + 1), 'E'),
            ('stx', ARR, ('v', 'j'), 1, ('i', 0)),
            ('bin', 'j', '+', ('v', 'j'), ('v', 'p')),
            ('jmp', 'K'),
            ('lbl', 'E'),
            ('bin', 'c', '+', ('v', 'c'), ('i', 1)),
            ('lbl', 'N'),
            ('bin', 'i', '+', ('v', 'i'), ('i', 1)),
            ('br', 'lo', ('v', 'i'), ('i', SIZE + 1), 'M'),
            ('halt',)], 'c', 1899


BENCH = [("loop   BM1  FOR K=1 TO 1000", bm_loop),
         ("incr   BM2  K=K+1 x1000", bm_incr),
         ("arith  BM3  A=K*2+3-K", bm_arith),
         ("calls  BM6  nested loop + CALL", bm_calls),
         ("array  BM7  M(L)=A", bm_array),
         ("sieve       Byte sieve 8190", bm_sieve)]

# branch condition -> the COOL8 mnemonic that follows a 16-bit SUB/SBC
BR = {'lo': 'BLO', 'hs': 'BHS', 'eq': 'BEQ', 'ne': 'BNE'}
INV = {'lo': 'hs', 'hs': 'lo', 'eq': 'ne', 'ne': 'eq'}


# =====================================================================
# 1. native -- leaf-aware accumulator, OS_PLAN section 4.1
# =====================================================================

class Native:
    """R0:R1 is the accumulator, R2:R3 the second operand.

    No optimiser, no peepholes, no register allocation across
    statements: every statement loads what it needs and stores what it
    made. That is what a one-pass compiler emits and it is the thing
    being measured.
    """

    def __init__(self, long=False):
        self.o = []
        self.stmts = 0
        self.long = long
        self.n = 0

    def leaf(self, lf, r):                  # r is 0 (R0:R1) or 2 (R2:R3)
        k, v = lf
        if k == 'i':
            self.o.append(f"        MOV  R{r},#{v & 0xFF}")
            self.o.append(f"        MOV  R{r+1},#{(v >> 8) & 0xFF}")
        else:
            a = var(v)
            self.o.append(f"        LD   R{r},[${a:04X}]")
            self.o.append(f"        LD   R{r+1},[${a+1:04X}]")

    def emit(self, s):
        op = s[0]
        if op == 'lbl':
            self.o.append(f"{s[1]}:")
            return
        self.stmts += 1
        if op == 'set':
            self.leaf(s[2], 0)
            a = var(s[1])
            self.o.append(f"        ST   [${a:04X}],R0")
            self.o.append(f"        ST   [${a+1:04X}],R1")
        elif op == 'bin':
            _, dst, o2, lf, rf = s
            self.leaf(lf, 0)
            self.leaf(rf, 2)
            if o2 == '+':
                self.o.append("        ADD  R0,R2")
                self.o.append("        ADC  R1,R3")
            elif o2 == '-':
                self.o.append("        SUB  R0,R2")
                self.o.append("        SBC  R1,R3")
            else:
                self.o.append("        CALL mul16")   # runtime, as planned
            a = var(dst)
            self.o.append(f"        ST   [${a:04X}],R0")
            self.o.append(f"        ST   [${a+1:04X}],R1")
        elif op == 'br':
            _, c, lf, rf, lab = s
            self.leaf(lf, 0)
            self.leaf(rf, 2)
            self.o.append("        SUB  R0,R2")
            self.o.append("        SBC  R1,R3")
            if c in ('eq', 'ne'):
                self.o.append("        OR   R0,R1")
            if self.long:
                # Bcc reaches +-127 bytes. Past that a one-pass compiler
                # inverts the condition and jumps: 3 more bytes, and 2
                # more clocks when the branch is taken.
                sk = f".sk{self.n}"
                self.n += 1
                self.o.append(f"        {BR[INV[c]]}  {sk}")
                self.o.append(f"        JMP  {lab}")
                self.o.append(f"{sk}:")
            else:
                self.o.append(f"        {BR[c]}  {lab}")
        elif op == 'jmp':
            self.o.append(f"        JMP  {s[1]}")
        elif op == 'call':
            self.o.append(f"        CALL {s[1]}")
        elif op == 'ret':
            self.o.append("        RET")
        elif op == 'ldx':
            _, dst, base, idx, w = s
            self.addr(base, idx, w)
            self.o.append("        LD   R0,[X]")
            if w == 2:
                self.o.append("        INCW X")
                self.o.append("        LD   R1,[X]")
            else:
                self.o.append("        CLR  R1")
            a = var(dst)
            self.o.append(f"        ST   [${a:04X}],R0")
            self.o.append(f"        ST   [${a+1:04X}],R1")
        elif op == 'stx':
            _, base, idx, w, valf = s
            self.addr(base, idx, w)
            self.leaf(valf, 0)
            self.o.append("        ST   [X],R0")
            if w == 2:
                self.o.append("        INCW X")
                self.o.append("        ST   [X],R1")
        elif op == 'halt':
            self.o.append("        HALT")

    def addr(self, base, idx, w):
        """X = base + idx*w, the general form a compiler emits."""
        self.leaf(idx, 0)
        if w == 2:
            self.o.append("        ADD  R0,R0")
            self.o.append("        ADC  R1,R1")
        self.o.append(f"        LDW  X,#${base:04X}")
        self.o.append("        ADDW X,R0")
        self.o.append("        MOV  R2,XH")
        self.o.append("        ADD  R2,R1")
        self.o.append("        MOV  XH,R2")

    def build(self, prog):
        self.o.append(f"        .org ${CODE:04X}")
        for s in prog:
            self.emit(s)
        self.o += MUL16
        return "\n".join(self.o) + "\n"


# A 16x16 -> 16 multiply out of the hardware 8x8.  R0:R1 * R2:R3 -> R0:R1.
#
#   result = alo*blo + ((alo*bhi + ahi*blo) << 8), keeping 16 bits.
#
# MUL leaves Rd and Rs alone and lands the product in X, so only blo
# needs saving -- the second partial product needs it back after the
# first has overwritten R2.
MUL16 = [
    "mul16:  PUSH R2",
    "        MUL  R0,R2",           # X = alo*blo
    "        MOVW Y,X",
    "        MUL  R0,R3",           # X = alo*bhi, low byte shifts into YH
    "        MOV  R2,XL",
    "        MOV  R0,YH",
    "        ADD  R0,R2",
    "        MOV  YH,R0",
    "        POP  R2",              # blo back
    "        MUL  R1,R2",           # X = ahi*blo
    "        MOV  R2,XL",
    "        MOV  R0,YH",
    "        ADD  R0,R2",
    "        MOV  YH,R0",
    "        MOV  R0,YL",
    "        MOV  R1,YH",
    "        RET",
]


# =====================================================================
# The harness
# =====================================================================

ASM = os.path.join(ROOT, "tools", "cool8asm.py")
os.makedirs(BUILD, exist_ok=True)


def assemble(src, stem, quiet=False):
    a = os.path.join(BUILD, stem + ".asm")
    b = os.path.join(BUILD, stem + ".bin")
    open(a, "w").write(src)
    r = subprocess.run([sys.executable, ASM, a, "-o", b],
                       capture_output=True, text=True)
    if r.returncode != 0:
        if not quiet:
            print(r.stdout + r.stderr)
        raise SystemExit("assembly failed: " + stem)
    return b, os.path.getsize(b)


class Mem(emu.Bus):
    def __init__(self):
        self.mem = bytearray(0x10000)

    def read(self, a):
        return self.mem[a & 0xFFFF]

    def write(self, a, v):
        self.mem[a & 0xFFFF] = v & 0xFF


def run(binpath, extra=None, limit=200_000_000):
    bus = Mem()
    d = open(binpath, "rb").read()
    bus.mem[CODE:CODE + len(d)] = d
    if extra:
        off, blob = extra
        bus.mem[off:off + len(blob)] = blob
    c = emu.Cool8(bus)
    c.reset()
    c.pc = CODE
    c.sp = 0xFFF7
    n = 0
    while n < limit and not c.halted:
        c.step()
        n += 1
    if not c.halted:
        raise SystemExit("did not halt: " + binpath)
    return c.cycles, bus


def answer(bus, name):
    a = var(name)
    return bus.mem[a] | (bus.mem[a + 1] << 8)




OPS = ['PUSHI', 'PUSHV', 'STOREV', 'ADD', 'SUB', 'MUL', 'JMP', 'BLO',
       'BHS', 'BEQ', 'BNE', 'LDXB', 'LDXW', 'STXB', 'STXW', 'CALL',
       'RET', 'HALT']
OPN = {n: i for i, n in enumerate(OPS)}
HASARG = {'PUSHI', 'PUSHV', 'STOREV', 'JMP', 'BLO', 'BHS', 'BEQ', 'BNE',
          'LDXB', 'LDXW', 'STXB', 'STXW', 'CALL'}


def push(lf):
    return [('PUSHI', lf[1] & 0xFFFF)] if lf[0] == 'i' \
        else [('PUSHV', var(lf[1]))]


def bc_compile(prog):
    """The IR to a byte stream, in two passes for the labels."""
    seq = []
    for s in prog:
        op = s[0]
        if op == 'lbl':
            seq.append(('label', s[1]))
        elif op == 'set':
            seq += push(s[2]) + [('STOREV', var(s[1]))]
        elif op == 'bin':
            _, dst, o, l, r = s
            seq += push(l) + push(r)
            seq.append(({'+': 'ADD', '-': 'SUB', '*': 'MUL'}[o], None))
            seq.append(('STOREV', var(dst)))
        elif op == 'br':
            _, c, l, r, lab = s
            seq += push(l) + push(r)
            seq.append(({'lo': 'BLO', 'hs': 'BHS', 'eq': 'BEQ',
                         'ne': 'BNE'}[c], ('ref', lab)))
        elif op == 'jmp':
            seq.append(('JMP', ('ref', s[1])))
        elif op == 'call':
            seq.append(('CALL', ('ref', s[1])))
        elif op == 'ret':
            seq.append(('RET', None))
        elif op == 'ldx':
            _, dst, base, idx, w = s
            seq += push(idx)
            seq.append(('LDXB' if w == 1 else 'LDXW', base))
            seq.append(('STOREV', var(dst)))
        elif op == 'stx':
            _, base, idx, w, val = s
            seq += push(idx) + push(val)
            seq.append(('STXB' if w == 1 else 'STXW', base))
        elif op == 'halt':
            seq.append(('HALT', None))

    addr, at = {}, 0
    for e in seq:
        if e[0] == 'label':
            addr[e[1]] = BC + at
        else:
            at += 1 + (2 if e[0] in HASARG else 0)

    out = bytearray()
    for e in seq:
        if e[0] == 'label':
            continue
        out.append(OPN[e[0]])
        if e[0] in HASARG:
            a = e[1]
            if isinstance(a, tuple):
                a = addr[a[1]]
            out += bytes((a & 0xFF, (a >> 8) & 0xFF))
    return bytes(out)


ARG = ["        LD   R2,[Y]", "        INCW Y",
       "        LD   R3,[Y]", "        INCW Y"]
IDX = ["        ADDW X,R0", "        MOV  R0,XH",
       "        ADD  R0,R1", "        MOV  XH,R0"]


def vm_source():
    o = [f"        .org ${CODE:04X}",
         f"        LDW  Y,#${BC:04X}",
         "disp:   LD   R0,[Y]",
         "        INCW Y",
         "        SHL  R0",
         "        LDW  X,#tab",
         "        LD   R1,[X+R0]",
         "        ADD  R0,#1",
         "        LD   R2,[X+R0]",
         "        MOV  XL,R1",
         "        MOV  XH,R2",
         "        JMP  [X]"]

    def h(name, body):
        o.append(f"h_{name}:")
        o.extend(body)

    h('PUSHI', ARG + ["        PUSH R3", "        PUSH R2",
                      "        JMP  disp"])
    h('PUSHV', ARG + ["        MOV  XL,R2", "        MOV  XH,R3",
                      "        LD   R0,[X]", "        INCW X",
                      "        LD   R1,[X]", "        PUSH R1",
                      "        PUSH R0", "        JMP  disp"])
    h('STOREV', ARG + ["        MOV  XL,R2", "        MOV  XH,R3",
                       "        POP  R0", "        POP  R1",
                       "        ST   [X],R0", "        INCW X",
                       "        ST   [X],R1", "        JMP  disp"])
    for nm, a, b in (('ADD', 'ADD', 'ADC'), ('SUB', 'SUB', 'SBC')):
        h(nm, ["        POP  R2", "        POP  R3",
               "        POP  R0", "        POP  R1",
               f"        {a}  R0,R2", f"        {b}  R1,R3",
               "        PUSH R1", "        PUSH R0", "        JMP  disp"])
    # mul16 uses Y as scratch, and in this model Y is the interpreter's
    # program counter -- so the IP has to be saved across every runtime
    # call. Six clocks, and it is a real cost of holding the IP in a
    # register the runtime also wants. Native code has Y free.
    h('MUL', ["        POP  R2", "        POP  R3",
              "        POP  R0", "        POP  R1",
              "        PUSHW Y", "        CALL mul16", "        POPW Y",
              "        PUSH R1", "        PUSH R0",
              "        JMP  disp"])
    h('JMP', ARG + ["        MOV  YL,R2", "        MOV  YH,R3",
                    "        JMP  disp"])
    for nm, inv in (('BLO', 'BHS'), ('BHS', 'BLO'),
                    ('BEQ', 'BNE'), ('BNE', 'BEQ')):
        body = ARG + ["        MOV  XL,R2", "        MOV  XH,R3",
                      "        POP  R2", "        POP  R3",
                      "        POP  R0", "        POP  R1",
                      "        SUB  R0,R2", "        SBC  R1,R3"]
        if nm in ('BEQ', 'BNE'):
            body.append("        OR   R0,R1")
        body += [f"        {inv}  n{nm}", "        MOVW Y,X",
                 f"n{nm}:   JMP  disp"]
        h(nm, body)
    h('LDXB', ARG + ["        POP  R0", "        POP  R1",
                     "        MOV  XL,R2", "        MOV  XH,R3"] + IDX +
      ["        LD   R0,[X]", "        CLR  R1",
       "        PUSH R1", "        PUSH R0", "        JMP  disp"])
    h('LDXW', ARG + ["        POP  R0", "        POP  R1",
                     "        ADD  R0,R0", "        ADC  R1,R1",
                     "        MOV  XL,R2", "        MOV  XH,R3"] + IDX +
      ["        LD   R0,[X]", "        INCW X", "        LD   R1,[X]",
       "        PUSH R1", "        PUSH R0", "        JMP  disp"])
    h('STXB', ARG + ["        MOV  XL,R2", "        MOV  XH,R3",
                     "        POP  R2", "        POP  R3",
                     "        POP  R0", "        POP  R1"] + IDX +
      ["        ST   [X],R2", "        JMP  disp"])
    h('STXW', ARG + ["        MOV  XL,R2", "        MOV  XH,R3",
                     "        POP  R2", "        POP  R3",
                     "        POP  R0", "        POP  R1",
                     "        ADD  R0,R0", "        ADC  R1,R1"] + IDX +
      ["        ST   [X],R2", "        INCW X", "        ST   [X],R3",
       "        JMP  disp"])
    h('CALL', ARG + ["        PUSHW Y", "        MOV  YL,R2",
                     "        MOV  YH,R3", "        JMP  disp"])
    h('RET', ["        POPW Y", "        JMP  disp"])
    h('HALT', ["        HALT"])

    o.append("tab:")
    for n in OPS:
        o.append(f"        .word h_{n}")
    o += MUL16
    return "\n".join(o) + "\n"



def emit_native(prog):
    """Native code, retrying with long branches if any is out of reach.

    A Bcc reaches +-127 bytes and the sieve's loops do not fit. A
    one-pass compiler that cannot see forward has to solve this; the
    cheapest correct answer is to invert the test and jump, which costs
    3 bytes and 2 clocks on the taken path.
    """
    n = Native()
    try:
        return n, assemble(n.build(prog), "bl_nat", quiet=True)
    except SystemExit:
        n = Native(long=True)
        return n, assemble(n.build(prog), "bl_nat")


def main():
    import math
    HZ = 8_375_000
    vm, vmsize = assemble(vm_source(), "bl_vm")

    print("  M10 -- native code against stack bytecode, on cool8emu")
    print()
    print(f"  {'benchmark':<30} {'native':>11} {'bytecode':>11} "
          f"{'ratio':>7}  answers")

    tn = tb = tns = tbs = ts = 0
    ratios = []
    rows = []
    for label, fn in BENCH:
        prog, resvar, want = fn()
        n, (nbin, nsize) = emit_native(prog)
        ncyc, nbus = run(nbin)
        ngot = answer(nbus, resvar)

        stream = bc_compile(prog)
        bcyc, bbus = run(vm, extra=(BC, stream))
        bgot = answer(bbus, resvar)

        ok = "ok" if (ngot == want and bgot == want) else              f"MISMATCH nat={ngot} bc={bgot} want={want}"
        r = bcyc / ncyc
        ratios.append(r)
        tn += ncyc
        tb += bcyc
        tns += nsize
        tbs += len(stream)
        ts += n.stmts
        rows.append((label, n.stmts, nsize, len(stream)))
        print(f"  {label:<30} {ncyc:11,} {bcyc:11,} {r:6.2f}x  "
              f"{ngot:<6} {ok}")

    print()
    print(f"  {'TOTAL':<30} {tn:11,} {tb:11,} {tb/tn:6.2f}x")
    print(f"  {'wall clock at 8.375 MHz':<30} {tn/HZ*1000:10.0f}ms "
          f"{tb/HZ*1000:10.0f}ms")
    print()

    print("  Size -- the other half of the trade")
    print()
    print(f"  {'benchmark':<30} {'stmts':>6} {'native':>8} {'B/stmt':>7} "
          f"{'bytecode':>9} {'B/stmt':>7}")
    for label, st, ns, bs in rows:
        print(f"  {label:<30} {st:6} {ns:8,} {ns/st:7.1f} "
              f"{bs:9,} {bs/st:7.1f}")
    print(f"  {'TOTAL':<30} {ts:6} {tns:8,} {tns/ts:7.1f} "
          f"{tbs:9,} {tbs/ts:7.1f}")
    print()
    print(f"  native code is {tns/tbs:.2f}x the size of bytecode")
    print(f"  32 KB of native code holds about {32768/(tns/ts):,.0f} "
          f"statements")
    print(f"  the bytecode interpreter itself is {vmsize:,} bytes")
    print()

    gm = math.prod(ratios) ** (1 / len(ratios))
    worst = min(ratios)
    print(f"  geometric mean {gm:.2f}x, worst case {worst:.2f}x")
    print()
    print(f"  GATE: native >= 3x bytecode on real programs -- "
          f"{'PASS' if worst >= 3.0 else 'FAIL'}")
    return 0 if worst >= 3.0 else 1


if __name__ == "__main__":
    sys.exit(main())
