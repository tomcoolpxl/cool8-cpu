#!/usr/bin/env python3
"""COOL8 BASIC — a one-pass native-code compiler.

    python tools/cool8bas.py prog.bas -o prog.bin
    python tools/cool8bas.py prog.bas -S            # keep the assembly

Structured BASIC with no line numbers, compiled straight to COOL8
machine code. There is no intermediate representation, no optimiser and
no second pass: the parser emits instructions as it recognises them,
which is what makes compiling fast enough that `RUN` feels interpreted.

## The code generation model

**Leaf-aware accumulator**, as OS_PLAN section 4.1 specifies. The value
being computed lives in `R0:R1`. When the right-hand operand of a binary
operator is a *leaf* — a constant, a variable, a parameter — it loads
straight into `R2:R3` and the operation is two instructions. Only a
nested right-hand side spills, and it spills to a compiler-allocated
temporary rather than to the hardware stack.

Real expressions are mostly leaf-shaped, which is why this is worth
doing and why `sim/bench_lang.py` measured the shape it did.

## Two things the ISA forces

**Sixteen-bit comparison has no `Z` for the whole value.** `SUB`/`SBC`
leaves `Z` reflecting the high byte alone, so `BGT` and `BLE` would be
wrong whenever the low bytes differ and the high bytes match. `a > b` is
therefore compiled as `b < a` and `a <= b` as `b >= a`, leaving only
`BLT`, `BGE` and — with an `OR` to fold the two bytes — `BEQ`/`BNE`.

**A branch reaches ±127 bytes.** A one-pass compiler cannot see how far
forward a block will run, so every forward conditional branch is emitted
inverted with a `JMP` behind it. Backward branches, whose distance is
known, use the short form when it fits. This costs 3 bytes and 2 clocks
on the taken path and is not optional.

## What is not here yet

Integer only — `INT` is 16-bit signed and is the only type. No strings,
no floats, no `LONG`, no locals inside `SUB` (parameters yes, and they
are on the stack, so recursion works). Those are M14's runtime library
and the types that come with it.
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ORG = 0x0200

KEYWORDS = {
    'const', 'dim', 'sub', 'end', 'if', 'then', 'else', 'elseif',
    'for', 'to', 'next', 'do', 'loop', 'while', 'until', 'exit',
    'wend', 'call', 'as', 'int', 'byte', 'return', 'goto', 'poke',
    'rem', 'at', 'asm', 'function', 'peek', 'extern',
    'print', 'include', 'and', 'or', 'xor', 'inline',
}

# `a > b` is compiled as `b < a`, and `a <= b` as `b >= a`.
SWAP = {'>': '<', '<=': '>='}
# The inverse of each surviving relation, for a jump-if-false.
NOT = {'<': '>=', '>=': '<', '=': '<>', '<>': '='}
BRANCH = {'<': 'BLT', '>=': 'BGE', '=': 'BEQ', '<>': 'BNE'}
# BYTE is unsigned, so its comparisons are the carry ones.
BYTE_BRANCH = {'<': 'BLO', '>=': 'BHS', '=': 'BEQ', '<>': 'BNE'}


SHIFTABLE = {'<<', '>>'}

# A safety cap on what INLINE will expand, so a mistake is a compile
# error rather than a program three times its size.
INLINE_MAX = 200


def mk_bin(op, a, b):
    """Build a binary node, folding it if both sides are known.

    Not an optimisation — the difference between `SIZE + 1` being an
    add and being a number. Without it the sieve recomputes its limit
    every time round the loop, and worse: the result is not a leaf, so
    the comparison spills through a temporary as well. That was 35 %.
    """
    if a[0] == 'num' and b[0] == 'num':
        v = {'+': a[1] + b[1], '-': a[1] - b[1], '*': a[1] * b[1],
             'and': a[1] & b[1], 'or': a[1] | b[1], 'xor': a[1] ^ b[1],
             '<<': a[1] << b[1], '>>': (a[1] & 0xFFFF) >> b[1]}[op]
        return ('num', v & 0xFFFF)
    return ('bin', op, a, b)


class Err(Exception):
    def __init__(self, msg, line):
        super().__init__(f"line {line}: {msg}")
        self.line = line


# ============================================================= the lexer

TOKEN = re.compile(r"""
    (?P<ws>[ \t]+)
  | (?P<comment>'[^\n]*|\bREM\b[^\n]*)
  | (?P<nl>\n)
  | (?P<str>"[^"
]*")
  | (?P<num>\$[0-9A-Fa-f]+|\d+)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><<|>>|<>|<=|>=|[-+*/()=<>,;])
""", re.X | re.I)


ASM_OPEN = re.compile(r"[ \t]*ASM[ \t]*\n", re.I)
ASM_CLOSE = re.compile(r"[ \t]*END[ \t]+ASM[ \t]*(\n|$)", re.I)


def lex(src):
    """ASM blocks are taken out whole. The assembler already knows how to
    read them, and there is nothing the tokeniser can usefully do to
    assembly source except damage it."""
    out, line, i = [], 1, 0
    while i < len(src):
        m = ASM_OPEN.match(src, i)
        if m and (not out or out[-1][0] == 'nl'):
            body, j, line = [], m.end(), line + 1
            while True:
                c = ASM_CLOSE.match(src, j)
                if c:
                    j = c.end()
                    line += 1
                    break
                k = src.find("\n", j)
                if k < 0:
                    raise Err("ASM without END ASM", line)
                body.append(src[j:k])
                j, line = k + 1, line + 1
            out.append(('asm', body, line))
            out.append(('nl', '\n', line))
            i = j
            continue
        m = TOKEN.match(src, i)
        if not m:
            raise Err(f"cannot read {src[i]!r}", line)
        i = m.end()
        kind = m.lastgroup
        text = m.group()
        if kind in ('ws', 'comment'):
            continue
        if kind == 'nl':
            if out and out[-1][0] != 'nl':
                out.append(('nl', '\n', line))
            line += 1
            continue
        if kind == 'str':
            out.append(('str', text[1:-1], line))
        elif kind == 'num':
            v = int(text[1:], 16) if text[0] == '$' else int(text)
            out.append(('num', v, line))
        elif kind == 'name':
            low = text.lower()
            out.append((low if low in KEYWORDS else 'name', text, line))
        else:
            out.append(('op', text, line))
    out.append(('nl', '\n', line))
    out.append(('eof', '', line))
    return out


# ============================================================ the symbols

class Sym:
    def __init__(self, kind, label=None, size=2, count=1, index=None,
                 value=None, nargs=0, returns=False,
                 body=None, params=None, inlinable=False):
        self.kind = kind        # 'var' | 'array' | 'const' | 'sub' | 'param'
        self.label = label
        self.size = size
        self.count = count
        self.index = index      # for a parameter: which one
        self.value = value
        self.nargs = nargs
        self.returns = returns      # a FUNCTION, so a call has a value
        self.body = body            # (start, stop) token range, for inlining
        self.params = params or []  # [(name, width)]
        self.inlinable = inlinable


# =========================================================== the compiler

class Compiler:
    def __init__(self):
        self.t = []
        self.p = 0
        self.out = []
        self.data = []
        self.glob = {}
        self.local = None       # the SUB being compiled, or None
        self.n = 0
        self.loops = []         # (continue_label, exit_label)
        self.temps = 0
        self.max_temp = 0
        self.subs_seen = set()
        self.uses_mul = False
        self.frame = 0          # bytes of locals in the SUB being built
        self.max_frame = 0      # its high-water mark, inlining included
        self.inlining = set()   # SUBs being expanded, to stop recursion
        self.inline_ret = None  # where a RETURN inside an expansion goes
        self.searchpath = [os.getcwd(), os.path.join(ROOT, "sw")]

    # ---------------------------------------------------------- plumbing

    def tok(self, k=0):
        return self.t[self.p + k]

    def at(self, kind, text=None):
        t = self.tok()
        return t[0] == kind and (text is None or
                                 str(t[1]).lower() == text)

    def take(self, kind=None, text=None):
        t = self.tok()
        if kind and not self.at(kind, text):
            raise Err(f"expected {text or kind}, found {t[1]!r}", t[2])
        self.p += 1
        return t

    def eat_nl(self):
        while self.at('nl'):
            self.p += 1

    def label(self, stem='L'):
        self.n += 1
        return f".{stem}{self.n}"

    def e(self, s):
        self.out.append("        " + s)

    def lab(self, s):
        self.out.append(s + ":")

    # ------------------------------------------------------ the symbols

    def lookup(self, name):
        low = name.lower()
        if self.local:
            s = self.local.get(low)
            if s is not None:
                return s
        return self.glob.get(low)

    def redefine_check(self, name):
        """Names are case-insensitive, so CONST PATBASE and SUB PatBase
        are the same name. Silently letting one replace the other turns
        a typo into a crash three hundred lines later."""
        s = self.glob.get(name.lower())
        if s is not None and s.kind == 'sub':
            raise Err(f"{name} is already a SUB or FUNCTION -- names are "
                      f"not case sensitive", self.tok()[2])

    def define_var(self, name):
        low = name.lower()
        s = self.glob.get(low)
        if s is None:
            s = Sym('var', label=f"v_{low}")
            self.glob[low] = s
            self.data.append(f"v_{low}: .res 2")
        return s

    def temp(self):
        """A spill slot in the frame, reused by depth.

        **These have to be per-invocation, not global.** A global slot
        works right up until an argument expression contains a call, and
        the callee reuses slot 0 while the caller still has an argument
        parked in it. That is how eight sprites become one.
        """
        k = self.temps
        self.temps += 1
        self.max_temp = max(self.max_temp, self.temps)
        return k

    # ---------------------------------------------------- loading leaves

    def width(self, e):
        """1 for a byte, 2 for an int.

        A literal takes whichever width it is used at, so `x + 1` on
        bytes stays a byte. Everything else is what it was declared.
        """
        k = e[0]
        if k == 'num':
            return 1 if 0 <= e[1] <= 255 else 2
        if k in ('var', 'local', 'param'):
            return e[2]
        if k == 'index':
            return e[1].size
        if k == 'peek':
            return 1
        if k == 'bin':
            if e[1] in ('+', '-', 'and', 'or', 'xor', '<<', '>>'):
                return max(self.width(e[2]), self.width(e[3]))
            return 2                    # a multiply can always overflow
        if k == 'neg':
            return 2
        return 2                        # calls, strings, externs

    def is_leaf(self, e):
        return e[0] in ('num', 'var', 'param', 'const', 'extern', 'local',
                        'strlit')

    def load(self, e, r, w=2):
        """A leaf into R{r}, or R{r}:R{r+1} when `w` is 2.

        A byte-wide source read at word width is zero-extended with a
        `CLR`, which is one instruction; a word-wide source read at byte
        width simply drops its high half, which is none.
        """
        k = e[0]
        if k in ('num', 'const'):
            v = e[1] & 0xFFFF
            self.e(f"MOV  R{r},#{v & 0xFF}")
            if w == 2:
                self.e(f"MOV  R{r+1},#{v >> 8}")
        elif k in ('extern', 'strlit'):
            self.e(f"MOV  R{r},#<{e[1]}")
            self.e(f"MOV  R{r+1},#>{e[1]}")
        elif k == 'var':
            self.e(f"LD   R{r},[{e[1]}]")
            if w == 2:
                if e[2] == 1:
                    self.e(f"CLR  R{r+1}")
                else:
                    self.e(f"LD   R{r+1},[{e[1]}+1]")
        elif k == 'local':
            self.e(f"LD   R{r},[SP+{e[1]}]")
            if w == 2:
                if e[2] == 1:
                    self.e(f"CLR  R{r+1}")
                else:
                    self.e(f"LD   R{r+1},[SP+{e[1]+1}]")
        elif k == 'param':
            # [SP+u8] is 3 clocks against 4 for [abs16], so a parameter
            # is cheaper to read than a global. That is the opposite of
            # the 6502, and it is why recursion was kept.
            off = 2 + 2 * e[1]
            self.e(f"LD   R{r},[SP+@{off}]")
            if w == 2:
                if e[2] == 1:
                    self.e(f"CLR  R{r+1}")
                else:
                    self.e(f"LD   R{r+1},[SP+@{off+1}]")
        else:
            raise Err(f"not a leaf: {k}", 0)

    def load_temp(self, k, r, bias=0, width=2):
        """`bias` is how far SP has already moved.

        Spill slots are addressed off SP, so anything that pushes while
        a slot is still live has to say so. Pushing arguments is the
        only place that happens, and getting it wrong reads the
        neighbouring argument instead.
        """
        self.e(f"LD   R{r},[SP+~{k}_{bias}]")
        if width == 2:
            self.e(f"LD   R{r+1},[SP+~{k}b_{bias}]")

    def store_temp(self, k, bias=0, width=2):
        self.e(f"ST   [SP+~{k}_{bias}],R0")
        if width == 2:
            self.e(f"ST   [SP+~{k}b_{bias}],R1")

    # ------------------------------------------------------- expressions

    def gen(self, e, w=None):
        """Leave the value of `e` in R0, or R0:R1 when it is two wide.

        Byte arithmetic is not a shortcut -- it is half the instructions.
        `ADD R0,R2` against `ADD R0,R2 / ADC R1,R3`, one `MOV` for a
        constant instead of two, one load and one store per variable.
        On a machine whose sprites and colours are all bytes, that is
        most of the work in an inner loop.
        """
        if w is None:
            w = self.width(e)
        k = e[0]
        if self.is_leaf(e):
            self.load(e, 0, w)
        elif k == 'bin' and e[1] in SHIFTABLE:
            _, op, a, b = e
            if b[0] != 'num':
                raise Err("a shift has to be by a constant in this "
                          "version", 0)
            # The operand keeps its own width. Narrowing first would
            # load the low byte and then shift it away, which is what
            # `a >> 8` became the moment BYTE existed.
            wa = max(self.width(a), w)
            self.gen(a, wa)
            self.shift(op, b[1] & 15, wa)
        elif k == 'bin':
            _, op, a, b = e
            if self.is_leaf(b):
                self.gen(a, w)
                self.load(b, 2, w)
            else:
                # Right first, into a temp, so the operand order of a
                # non-commutative operator survives.
                self.gen(b, w)
                tk = self.temp()
                self.store_temp(tk, width=w)
                self.gen(a, w)
                self.load_temp(tk, 2, width=w)
                self.temps -= 1
            self.binop(op, w)
        elif k == 'neg':
            self.gen(('bin', '-', ('num', 0), e[1]), w)
        elif k == 'index':
            self.addr(e[1], e[2])
            self.e("LD   R0,[X]")
            if e[1].size == 2:
                self.e("INCW X")
                self.e("LD   R1,[X]")
            elif w == 2:
                self.e("CLR  R1")
        elif k == 'peek' and w == 1:
            if e[1][0] == 'num':
                self.e(f"LD   R0,[${e[1][1] & 0xFFFF:04X}]")
            else:
                self.gen(e[1])
                self.e("MOV  XL,R0")
                self.e("MOV  XH,R1")
                self.e("LD   R0,[X]")
        elif k == 'peek':
            if e[1][0] == 'num':
                # A known address is one instruction. Every I/O register
                # in the machine is a known address, so this is the
                # difference between a language that can drive hardware
                # and one that talks about it.
                self.e(f"LD   R0,[${e[1][1] & 0xFFFF:04X}]")
                self.e("CLR  R1")
            else:
                self.gen(e[1])
                self.e("MOV  XL,R0")
                self.e("MOV  XH,R1")
                self.e("LD   R0,[X]")
                self.e("CLR  R1")
        elif k == 'call':
            self.gen_call(e[1], e[2], want=True)
        else:
            raise Err(f"cannot evaluate {k}", 0)

    def shift(self, op, n, w=2):
        """R0:R1 shifted by a constant.

        Eight of them is a byte move, which is why `x >> 8` for the high
        byte costs two instructions instead of eight pairs -- and why the
        library stopped needing a SUB to take one apart.
        """
        if w == 1:
            for _ in range(min(n, 8)):
                self.e("ADD  R0,R0" if op == '<<' else "SHR  R0")
            return
        if n >= 8:
            if op == '<<':
                self.e("MOV  R1,R0")
                self.e("CLR  R0")
            else:
                self.e("MOV  R0,R1")
                self.e("CLR  R1")
            n -= 8
        for _ in range(n):
            if op == '<<':
                self.e("ADD  R0,R0")
                self.e("ADC  R1,R1")
            else:
                self.e("SHR  R1")
                self.e("ROR  R0")

    def binop(self, op, w=2):
        if op == '+':
            self.e("ADD  R0,R2")
            if w == 2:
                self.e("ADC  R1,R3")
        elif op == '-':
            self.e("SUB  R0,R2")
            if w == 2:
                self.e("SBC  R1,R3")
        elif op in ('and', 'or', 'xor'):
            m = {'and': 'AND', 'or': 'OR ', 'xor': 'XOR'}[op]
            self.e(f"{m}  R0,R2")
            if w == 2:
                self.e(f"{m}  R1,R3")
        elif op == '*':
            self.uses_mul = True
            self.e("CALL mul16")
        else:
            raise Err(f"operator {op} is not in this version", 0)

    def addr(self, sym, idx):
        """X = base + index*size.

        Two things the general form does not need to know, and this one
        does:

        **A constant index is a constant address.** `note(0)` becomes one
        `LDW X,#label` instead of six instructions and a multiply by two.

        **A small array cannot carry into the high byte.** The general
        sequence adds the index's high byte to `XH` afterwards, and for
        an array whose last element is inside 255 bytes that add is
        always of zero. Dropping it is 8 clocks off every subscript, and
        an inner loop touches subscripts more than anything else.
        """
        span = sym.size * (sym.count + 1)
        if idx[0] == 'num':
            off = (idx[1] & 0xFFFF) * sym.size
            self.e(f"LDW  X,#{sym.label}+{off}")
            return
        self.gen(idx, 2)
        if sym.size == 2:
            self.e("ADD  R0,R0")
            self.e("ADC  R1,R1")
        self.e(f"LDW  X,#{sym.label}")
        self.e("ADDW X,R0")
        if span > 256:
            self.e("MOV  R2,XH")
            self.e("ADD  R2,R1")
            self.e("MOV  XH,R2")

    # ------------------------------------------------------- conditions

    def gen_cond(self, e, label, jump_if_false=True):
        """Evaluate a comparison and branch."""
        if e[0] != 'cmp':
            raise Err("a condition has to be a comparison", 0)
        _, op, a, b = e
        if op in SWAP:
            op, a, b = SWAP[op], b, a
        if jump_if_false:
            op = NOT[op]
        # A comparison of two bytes is unsigned and needs no high half:
        # one subtract, and the carry says it all.
        w = max(self.width(a), self.width(b))
        if self.is_leaf(b):
            self.gen(a, w)
            self.load(b, 2, w)
        else:
            self.gen(b, w)
            tk = self.temp()
            self.store_temp(tk, width=w)
            self.gen(a, w)
            self.load_temp(tk, 2, width=w)
            self.temps -= 1
        self.e("SUB  R0,R2")
        if w == 2:
            self.e("SBC  R1,R3")
            if op in ('=', '<>'):
                self.e("OR   R0,R1")
            self.branch(BRANCH[op], label)
        else:
            self.branch(BYTE_BRANCH[op], label)

    def branch(self, mnem, label):
        """Forward branches go long, because one pass cannot see ahead."""
        skip = self.label('x')
        inv = {'BLT': 'BGE', 'BGE': 'BLT', 'BEQ': 'BNE', 'BNE': 'BEQ',
               'BLO': 'BHS', 'BHS': 'BLO'}
        self.e(f"{inv[mnem]}  {skip}")
        self.e(f"JMP  {label}")
        self.lab(skip)

    # ------------------------------------------------------------ calls

    def gen_named(self, name, args):
        """Call a library routine by name, with a message worth reading
        if the library was not included."""
        if name.lower() not in self.glob:
            raise Err(f"PRINT needs {name} -- add "
                      f'INCLUDE "lib.bas"', self.tok()[2])
        self.gen_call(name, args)

    def include(self, path):
        """Splice another source in where the INCLUDE was.

        One pass, so this is a genuine textual splice rather than a
        module system: the library's SUBs are compiled as if they had
        been typed here.
        """
        for d in self.searchpath:
            full = os.path.join(d, path)
            if os.path.exists(full):
                break
        else:
            raise Err(f"cannot find {path}", self.tok()[2])
        with open(full, encoding="utf-8") as fh:
            sub = lex(fh.read())
        sub = [x for x in sub if x[0] != 'eof']
        self.t[self.p:self.p] = sub
        self.scan_subs()

    def assigns_to(self, s, pname):
        """Does the body assign to this parameter?

        A leaf argument can be substituted straight into the body -- no
        slot, no store, no load -- but only if the body treats it as
        read-only. Otherwise the substitution would try to assign to a
        constant.
        """
        a, b = s.body
        for q in range(a, b - 1):
            if (self.t[q][0] == 'name'
                    and str(self.t[q][1]).lower() == pname
                    and self.t[q + 1][0] == 'op'
                    and self.t[q + 1][1] == '='):
                return True
        return False

    def inline_call(self, s, args):
        """Expand a SUB at the call site.

        The saving is the calling convention, which on this machine is
        about ninety clocks for four arguments: a store and a load per
        argument, two pushes each, the CALL, the RET and the frame
        adjustment at both ends -- around a body that may be fifty. A
        leaf argument costs nothing at all here, because the body simply
        refers to it where it stands.
        """
        binds = {}
        save_frame = self.frame
        for (pname, pw), a in zip(s.params, args):
            if self.is_leaf(a) and not self.assigns_to(s, pname):
                binds[pname] = ('subst', a)
                continue
            self.gen(a, pw)
            slot = self.frame
            self.frame += pw
            self.max_frame = max(self.max_frame, self.frame)
            self.e(f"ST   [SP+{slot}],R0")
            if pw == 2:
                self.e(f"ST   [SP+{slot+1}],R1")
            binds[pname] = Sym('local', index=slot, size=pw)

        end = self.label('inl')
        save = (self.p, self.local, self.inline_ret)
        self.local = binds
        self.inline_ret = end
        self.inlining.add(s.label)
        self.p = s.body[0]
        self.block(enders=('end',))
        self.inlining.discard(s.label)
        self.p, self.local, self.inline_ret = save
        self.lab(end)
        self.max_frame = max(self.max_frame, self.frame)
        self.frame = save_frame

    def gen_call(self, name, args, want=False):
        s = self.glob.get(name.lower())
        if s is None or s.kind != 'sub':
            raise Err(f"{name} is not a SUB", 0)
        if len(args) != s.nargs:
            raise Err(f"{name} takes {s.nargs} argument(s), "
                      f"{len(args)} given", 0)
        if s.inlinable and s.label not in self.inlining:
            self.inline_call(s, args)
            return
        # Every argument is evaluated into a temp BEFORE anything is
        # pushed. Pushing as we go would move SP while a later argument
        # was still reading a parameter through [SP+u8].
        slots = []
        for a in args:
            self.gen(a, 2)              # arguments go on the stack as words
            tk = self.temp()
            self.store_temp(tk)
            slots.append(tk)
        for j, t in enumerate(reversed(slots)):      # right to left
            self.load_temp(t, 0, bias=2 * j)
            self.e("PUSH R1")
            self.e("PUSH R0")
        self.temps -= len(slots)
        self.e(f"CALL {s.label}")
        if args:
            self.e(f"ADDW SP,#{2 * len(args)}")

    # ------------------------------------------------------- statements

    def parse(self, src):
        self.t = lex(src)
        self.p = 0
        self.scan_subs()
        self.e("JMP  main")
        self.lab("main")
        first = len(self.out)
        self.e("ADDW SP,#-@F")
        self.frame = 0
        self.max_frame = 0
        self.temps = 0
        self.max_temp = 0
        self.block(top=True)
        self.e("HALT")
        self.patch(first)
        self.subs()
        return self.assemble()

    def scan_subs(self):
        """One look ahead for SUB names, so a call can precede its
        definition. It is the only thing this compiler reads twice.

        It also records each body's token range and parameter list, which
        is what lets a short one be expanded at the call site instead of
        called.
        """
        i = 0
        while i < len(self.t):
            marked = (self.t[i][0] == 'inline'
                      and self.t[i + 1][0] in ('sub', 'function'))
            head = i + 1 if marked else i
            if self.t[head][0] in ('sub', 'function') and                     self.t[head + 1][0] == 'name':
                name = self.t[head + 1][1]
                params, j = [], head + 2
                if self.t[j][0] == 'op' and self.t[j][1] == '(':
                    j += 1
                    while not (self.t[j][0] == 'op' and self.t[j][1] == ')'):
                        if self.t[j][0] == 'name':
                            pw = 2
                            if self.t[j + 1][0] == 'as' and                                     self.t[j + 2][0] == 'byte':
                                pw = 1
                            params.append((self.t[j][1].lower(), pw))
                        while not (self.t[j][0] == 'op'
                                   and self.t[j][1] in (',', ')')):
                            j += 1
                        if self.t[j][1] == ',':
                            j += 1
                    j += 1
                if self.t[j][0] == 'as':        # FUNCTION f(...) AS INT
                    j += 2
                # find the matching END SUB / END FUNCTION
                k, depth = j, 1
                while k < len(self.t) - 1 and depth:
                    if self.t[k][0] in ('sub', 'function'):
                        depth += 1
                    elif self.t[k][0] == 'end' and                             self.t[k + 1][0] in ('sub', 'function'):
                        depth -= 1
                        if not depth:
                            break
                        k += 1
                    k += 1
                body = (j, k)
                span = k - j
                has_asm = any(self.t[q][0] == 'asm' for q in range(j, k))
                self.glob[name.lower()] = Sym(
                    'sub', label=f"s_{name.lower()}", nargs=len(params),
                    returns=self.t[head][0] == 'function',
                    body=body, params=params,
                    # Expansion is asked for, not guessed at. A
                    # threshold cannot know that a routine called twice
                    # should be expanded and one called two hundred
                    # times should not -- and guessing wrong tripled the
                    # editor and put its code on top of its buffer.
                    #
                    # An assembly body reads its arguments off the stack
                    # at fixed offsets, so it only works when it really
                    # was called, whatever the author asked for.
                    inlinable=marked and not has_asm
                    and span <= INLINE_MAX)
            i += 1

    def block(self, top=False, enders=()):
        while True:
            self.eat_nl()
            t = self.tok()
            if t[0] == 'eof':
                if enders:
                    raise Err(f"expected {enders[0].upper()}", t[2])
                return None
            if t[0] in enders:
                return t[0]
            if t[0] == 'inline':
                self.take('inline')
                continue
            if t[0] in ('sub', 'function'):
                if not top:
                    raise Err("a SUB cannot be inside anything", t[2])
                self.skip_sub()
                continue
            self.statement()

    def skip_sub(self):
        """SUBs are compiled separately, after the main body."""
        start = self.p
        depth = 0
        while True:
            t = self.tok()
            if t[0] == 'eof':
                raise Err("SUB without END SUB", t[2])
            if t[0] in ('sub', 'function'):
                depth += 1
            elif t[0] == 'end' and self.tok(1)[0] in ('sub', 'function'):
                depth -= 1
                self.p += 2
                if depth == 0:
                    break
                continue
            self.p += 1
        self.subs_seen.add((start, self.p))

    def subs(self):
        for start, stop in sorted(self.subs_seen):
            save = self.p
            self.p = start
            kind = self.take()[0]
            name = self.take('name')[1]
            s = self.glob[name.lower()]
            params = {}
            if self.at('op', '('):
                self.take('op', '(')
                i = 0
                while not self.at('op', ')'):
                    pn = self.take('name')[1]
                    pw = 2
                    if self.at('as'):
                        self.take('as')
                        if self.at('byte'):
                            self.take('byte')
                            pw = 1
                        else:
                            self.take('int')
                    params[pn.lower()] = Sym('param', index=i, size=pw)
                    i += 1
                    if self.at('op', ','):
                        self.take('op', ',')
                self.take('op', ')')
            if self.at('as'):           # FUNCTION f(...) AS INT
                self.take('as')
                self.take('int')
            self.lab(s.label)
            first = len(self.out)
            self.e("ADDW SP,#-@F")
            self.local = params
            self.frame = 0
            self.max_frame = 0
            self.temps = 0
            self.max_temp = 0
            self.block(enders=('end',))
            self.take('end')
            self.take()                 # SUB or FUNCTION
            self.e("ADDW SP,#@F")
            self.e("RET")
            self.patch(first)
            self.local = None
            self.p = save

    def statement(self):
        t = self.tok()
        k = t[0]

        if k == 'asm':
            # Verbatim. This is how the language reaches the machine:
            # data tables, and calls into sw/fs.asm and the runtime.
            for line in self.take('asm')[1]:
                self.out.append(line)
            return
        if k == 'poke':
            self.take('poke')
            addr = self.expr()
            self.take('op', ',')
            val = self.expr()
            if addr[0] == 'num':
                self.gen(val, 1)        # a POKE writes one byte
                self.e(f"ST   [${addr[1] & 0xFFFF:04X}],R0")
                return
            if self.is_leaf(val):
                self.gen(addr)
                self.e("MOV  XL,R0")
                self.e("MOV  XH,R1")
                self.load(val, 0)
            else:
                self.gen(val)
                tv = self.temp()
                self.store_temp(tv)
                self.gen(addr)
                self.e("MOV  XL,R0")
                self.e("MOV  XH,R1")
                self.load_temp(tv, 0)
                self.temps -= 1
            self.e("ST   [X],R0")
            return
        if k == 'return':
            self.take('return')
            if not self.at('nl'):
                # A FUNCTION hands back a full word, whatever the
                # expression's own width is. `RETURN buf(i)` on a byte
                # array left the high half of R0:R1 holding whatever was
                # there, and the caller stored both -- so every character
                # the editor read came back with rubbish above it.
                self.gen(self.expr(), 2)
            if self.inline_ret is not None:
                self.e(f"JMP  {self.inline_ret}")
                return
            if self.local is not None:
                self.e("ADDW SP,#@F")   # release the frame; R0:R1 stands
            self.e("RET")
            return
        if k == 'include':
            self.take('include')
            path = self.take('str')[1]
            self.include(path)
            return
        if k == 'print':
            self.take('print')
            nl = True
            while not self.at('nl'):
                e = self.expr()
                if e[0] == 'strlit':
                    self.gen_named('Puts', [e])
                else:
                    self.gen_named('Putn', [e])
                nl = True
                if self.at('op', ','):
                    self.take('op', ',')
                    continue
                if self.at('op', ';'):
                    self.take('op', ';')
                    nl = False
                    continue
                break
            if nl:
                self.gen_named('Newline', [])
            return
        if k == 'extern':
            # A name the assembly side owns -- a table, a routine's data.
            # Its value is its address.
            self.take('extern')
            name = self.take('name')[1]
            self.glob[name.lower()] = Sym('extern', label=name)
            return
        if k == 'const':
            self.take('const')
            name = self.take('name')[1]
            self.take('op', '=')
            v = self.const_expr()
            self.redefine_check(name)
            self.glob[name.lower()] = Sym('const', value=v)
            return
        if k == 'dim':
            self.take('dim')
            name = self.take('name')[1]
            low = name.lower()
            array = self.at('op', '(')
            n = 0
            if array:
                self.take('op', '(')
                n = self.const_expr()
                self.take('op', ')')

            w = 2
            if self.at('as'):
                self.take('as')
                if self.at('byte'):
                    self.take('byte')
                    w = 1
                else:
                    self.take('int')

            if not array:
                # A scalar. Inside a SUB it is a local, in the frame;
                # outside, a global.
                if self.local is not None:
                    self.local[low] = Sym('local', index=self.frame, size=w)
                    self.frame += w
                    self.max_frame = max(self.max_frame, self.frame)
                    return
                self.redefine_check(name)
                self.glob[low] = Sym('var', label=f"v_{low}", size=w)
                self.data.append(f"v_{low}: .res {w}")
                return

            self.redefine_check(name)
            if self.at('at'):
                # An array laid over an address rather than allocated:
                # the screen, the I/O page, a buffer somewhere chosen.
                self.take('at')
                a = self.const_expr()
                self.glob[low] = Sym('array', label=f"${a:04X}",
                                     size=w, count=n)
                return
            self.glob[low] = Sym('array', label=f"a_{low}", size=w, count=n)
            self.data.append(f"a_{low}: .res {w * (n + 1)}")
            return
        if k == 'if':
            return self.do_if()
        if k == 'for':
            return self.do_for()
        if k == 'do':
            return self.do_do()
        if k == 'while':
            return self.do_while()
        if k == 'exit':
            self.take('exit')
            self.take('do')
            if not self.loops:
                raise Err("EXIT DO outside a loop", t[2])
            self.e(f"JMP  {self.loops[-1][1]}")
            return
        if k == 'end':
            self.take('end')
            self.e("HALT")
            return
        if k == 'call':
            self.take('call')
            return self.statement()
        if k == 'name':
            name = self.take('name')[1]
            s = self.lookup(name)
            if isinstance(s, tuple):
                raise Err(f"{name} is an argument here and cannot be "
                          f"assigned", t[2])
            if s and s.kind == 'sub':
                args = self.call_args()
                self.gen_call(name, args)
                return
            if self.at('op', '('):          # an array element
                if s is None or s.kind != 'array':
                    raise Err(f"{name} is not an array", t[2])
                self.take('op', '(')
                idx = self.expr()
                self.take('op', ')')
                self.take('op', '=')
                val = self.expr()
                if self.is_leaf(val):
                    # The address first, then the value straight into
                    # R0:R1. A leaf cannot disturb X, so the spill that
                    # the general case needs is pure waste here -- and
                    # array stores are exactly where inner loops live.
                    self.addr(s, idx)
                    self.load(val, 0, s.size)
                else:
                    # Anything else can want X itself, so the value is
                    # computed first and parked.
                    self.gen(val, s.size)
                    tv = self.temp()
                    self.store_temp(tv, width=s.size)
                    self.addr(s, idx)
                    self.load_temp(tv, 0, width=s.size)
                    self.temps -= 1
                self.e("ST   [X],R0")
                if s.size == 2:
                    self.e("INCW X")
                    self.e("ST   [X],R1")
                return
            self.take('op', '=')
            v = self.expr()
            if s is None:
                s = self.define_var(name)
            if s.kind in ('local', 'param', 'var'):
                self.gen(v, s.size)
                self.store_var(s)
                return
            raise Err(f"cannot assign to {name}", t[2])
        raise Err(f"cannot start a statement with {t[1]!r}", t[2])

    def call_args(self):
        args = []
        if self.at('op', '('):
            self.take('op', '(')
            while not self.at('op', ')'):
                args.append(self.expr())
                if self.at('op', ','):
                    self.take('op', ',')
            self.take('op', ')')
        elif not self.at('nl'):
            args.append(self.expr())
            while self.at('op', ','):
                self.take('op', ',')
                args.append(self.expr())
        return args

    # -------------------------------------------------- control structures

    def do_if(self):
        self.take('if')
        cond = self.expr()
        self.take('then')
        endl = self.label('endif')
        if not self.at('nl'):                       # single line IF
            nxt = self.label('fi')
            self.gen_cond(cond, nxt)
            self.statement()
            self.lab(nxt)
            return
        nxt = self.label('fi')
        self.gen_cond(cond, nxt)
        end = self.block(enders=('else', 'elseif', 'end'))
        if end == 'else':
            self.take('else')
            self.e(f"JMP  {endl}")
            self.lab(nxt)
            self.block(enders=('end',))
            self.take('end')
            self.take('if')
            self.lab(endl)
            return
        if end == 'elseif':
            self.take('elseif')
            self.e(f"JMP  {endl}")
            self.lab(nxt)
            self.p -= 1
            self.t[self.p] = ('if', 'IF', self.tok()[2])
            self.do_if()
            self.lab(endl)
            return
        self.take('end')
        self.take('if')
        self.lab(nxt)

    def do_for(self):
        self.take('for')
        name = self.take('name')[1]
        self.take('op', '=')
        start = self.expr()
        self.take('to')
        limit = self.expr()

        s = self.lookup(name) or self.define_var(name)
        # The limit is evaluated once, as every BASIC since Dartmouth
        # has done, into a hidden temporary.
        lim = f"f_{self.n}_lim"
        self.n += 1
        self.data.append(f"{lim}: .res {s.size}")
        self.gen(limit, s.size)
        self.e(f"ST   [{lim}],R0")
        if s.size == 2:
            self.e(f"ST   [{lim}+1],R1")
        self.gen(start, s.size)
        self.store_var(s)

        top = self.label('for')
        done = self.label('nxt')
        self.lab(top)
        # Tested at the top, so FOR i = 1 TO 0 runs zero times.
        self.gen_cond(('cmp', '<=', self.ref(s),
                       ('var', lim, s.size)), done)
        self.loops.append((top, done))
        self.block(enders=('next',))
        self.take('next')
        if self.at('name'):
            self.take('name')
        self.loops.pop()
        self.gen(('bin', '+', self.ref(s), ('num', 1)), s.size)
        self.store_var(s)
        self.e(f"JMP  {top}")
        self.lab(done)

    def patch(self, first):
        """Fill in the frame size, now that the body has been read.

        A one-pass compiler cannot know how many locals a SUB has until
        it has finished reading it, so offsets go out as markers and are
        resolved here. `@F` is the frame size; `@n` is a parameter at
        offset n above it.
        """
        loc = max(self.frame, self.max_frame)
        total = loc + 2 * self.max_temp
        for i in range(first, len(self.out)):
            line = self.out[i]
            if "@" not in line and "~" not in line:
                continue
            line = line.replace("#-@F", f"#-{total}")
            line = line.replace("#@F", f"#{total}")
            line = re.sub(
                r"~(\d+)b_(\d+)",
                lambda m: str(loc + 2 * int(m.group(1)) + 1
                              + int(m.group(2))), line)
            line = re.sub(
                r"~(\d+)_(\d+)",
                lambda m: str(loc + 2 * int(m.group(1))
                              + int(m.group(2))), line)
            line = re.sub(r"@(\d+)",
                          lambda m: str(int(m.group(1)) + total), line)
            if total == 0 and ("ADDW SP,#0" in line
                               or "ADDW SP,#-0" in line):
                line = "        ; no frame"
            self.out[i] = line

    def ref(self, s):
        if isinstance(s, tuple):        # a substituted argument
            return s[1]
        if s.kind == 'param':
            return ('param', s.index, s.size)
        if s.kind == 'local':
            return ('local', s.index, s.size)
        return ('var', s.label, s.size)

    def store_var(self, s):
        if s.kind == 'local':
            self.e(f"ST   [SP+{s.index}],R0")
            if s.size == 2:
                self.e(f"ST   [SP+{s.index+1}],R1")
            return
        if s.kind == 'param':
            off = 2 + 2 * s.index
            self.e(f"ST   [SP+@{off}],R0")
            if s.size == 2:
                self.e(f"ST   [SP+@{off+1}],R1")
        else:
            self.e(f"ST   [{s.label}],R0")
            if s.size == 2:
                self.e(f"ST   [{s.label}+1],R1")

    def do_do(self):
        self.take('do')
        top = self.label('do')
        done = self.label('od')
        self.lab(top)
        if self.at('while'):
            self.take('while')
            self.gen_cond(self.expr(), done)
        elif self.at('until'):
            self.take('until')
            self.gen_cond(self.expr(), done, jump_if_false=False)
        self.loops.append((top, done))
        self.block(enders=('loop',))
        self.take('loop')
        self.loops.pop()
        if self.at('while'):
            self.take('while')
            self.gen_cond(self.expr(), top, jump_if_false=False)
        elif self.at('until'):
            self.take('until')
            self.gen_cond(self.expr(), top)
        else:
            self.e(f"JMP  {top}")
        self.lab(done)

    def do_while(self):
        self.take('while')
        top = self.label('wh')
        done = self.label('wend')
        self.lab(top)
        self.gen_cond(self.expr(), done)
        self.loops.append((top, done))
        self.block(enders=('wend',))
        self.take('wend')
        self.loops.pop()
        self.e(f"JMP  {top}")
        self.lab(done)

    # ------------------------------------------------------ expressions

    def const_expr(self):
        e = self.expr()
        if e[0] == 'num':
            return e[1]
        if e[0] == 'const':
            return e[1]
        raise Err("a constant is needed here", self.tok()[2])

    def expr(self):
        a = self.bitwise()
        if self.at('op') and self.tok()[1] in ('<', '>', '<=', '>=',
                                               '=', '<>'):
            op = self.take('op')[1]
            return ('cmp', op, a, self.bitwise())
        return a

    def bitwise(self):
        a = self.arith()
        while self.tok()[0] in ('and', 'or', 'xor'):
            op = self.take()[0]
            a = mk_bin(op, a, self.arith())
        return a

    def arith(self):
        a = self.term()
        while self.at('op') and self.tok()[1] in ('+', '-'):
            op = self.take('op')[1]
            a = mk_bin(op, a, self.term())
        return a

    def term(self):
        a = self.unary()
        while self.at('op') and self.tok()[1] in ('*', '<<', '>>'):
            op = self.take('op')[1]
            a = mk_bin(op, a, self.unary())
        return a

    def unary(self):
        if self.at('op', '-'):
            self.take('op')
            e = self.unary()
            if e[0] == 'num':
                return ('num', (-e[1]) & 0xFFFF)
            return ('neg', e)
        return self.primary()

    def primary(self):
        t = self.tok()
        if t[0] == 'str':
            self.take('str')
            lab = f"str_{self.n}"
            self.n += 1
            body = ", ".join(str(ord(c)) for c in t[1]) or "0"
            self.data.append(f'{lab}: .byte {body}, 0')
            return ('strlit', lab)
        if t[0] == 'peek':
            self.take('peek')
            self.take('op', '(')
            e = self.expr()
            self.take('op', ')')
            return ('peek', e)
        if t[0] == 'num':
            self.take('num')
            return ('num', t[1])
        if t[0] == 'op' and t[1] == '(':
            self.take('op')
            e = self.expr()
            self.take('op', ')')
            return e
        if t[0] == 'name':
            name = self.take('name')[1]
            s = self.lookup(name)
            if s is None:
                raise Err(f"{name} has no value yet", t[2])
            if isinstance(s, tuple):        # a substituted argument
                return s[1]
            if s.kind == 'const':
                return ('num', s.value)
            if s.kind == 'array':
                self.take('op', '(')
                idx = self.expr()
                self.take('op', ')')
                return ('index', s, idx)
            if s.kind == 'sub':
                return ('call', name, self.call_args())
            if s.kind == 'extern':
                return ('extern', s.label)
            return self.ref(s)
        raise Err(f"expected a value, found {t[1]!r}", t[2])

    # ---------------------------------------------------------- output

    def assemble(self):
        o = [f"        .org ${ORG:04X}"] + self.out
        if self.uses_mul:
            o += MUL16
        o.append("")
        o += self.data
        return "\n".join(o) + "\n"


# A 16x16 -> 16 multiply out of the hardware 8x8, as the runtime will
# hold it. MUL leaves its operands alone and lands the product in X.
MUL16 = [
    "mul16:  PUSH R2",
    "        MUL  R0,R2",
    "        MOVW Y,X",
    "        MUL  R0,R3",
    "        MOV  R2,XL",
    "        MOV  R0,YH",
    "        ADD  R0,R2",
    "        MOV  YH,R0",
    "        POP  R2",
    "        MUL  R1,R2",
    "        MOV  R2,XL",
    "        MOV  R0,YH",
    "        ADD  R0,R2",
    "        MOV  YH,R0",
    "        MOV  R0,YL",
    "        MOV  R1,YH",
    "        RET",
]


def compile_source(src):
    return Compiler().parse(src)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("-o", "--output")
    ap.add_argument("-S", "--asm", action="store_true",
                    help="write the assembly and stop")
    a = ap.parse_args()

    with open(a.source) as fh:
        src = fh.read()
    try:
        asm = compile_source(src)
    except Err as e:
        sys.exit(f"{a.source}: {e}")

    stem = os.path.splitext(a.output or a.source)[0]
    apath = stem + ".asm"
    with open(apath, "w") as fh:
        fh.write(asm)
    if a.asm:
        print(apath)
        return 0
    out = a.output or (stem + ".bin")
    r = subprocess.run([sys.executable,
                        os.path.join(HERE, "cool8asm.py"), apath, "-o", out],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
