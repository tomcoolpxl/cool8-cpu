#!/usr/bin/env python3
"""COOL8 assembler.

Two-pass, purpose-built, and it derives its entire mnemonic table from
tools/opcodes.py rather than carrying its own copy. It does that by
disassembling every encoding and normalising the result, so any text the
disassembler can produce is text this assembler accepts, by construction.

    python tools/cool8asm.py sw/lib.asm -o lib.bin --listing lib.lst
    python tools/cool8asm.py sw/lib.asm --pressure

Syntax is documented in docs/02-isa.md section 10 and docs/08-assembler.md.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opcodes  # noqa: E402

REGS8 = ("R0", "R1", "R2", "R3")
REGS16 = ("X", "Y", "SP")
HALVES = ("XL", "XH", "YL", "YH")
ALLREGS = REGS8 + REGS16 + HALVES


class AsmError(Exception):
    def __init__(self, msg, where=None):
        super().__init__(msg)
        self.where = where


# ====================================================================
# Operand normalisation
#
# Both the source line and the disassembler's own output are pushed
# through the same function, so the two can never disagree about what an
# addressing mode looks like.
# ====================================================================

def norm_operand(text):
    """Return (canonical_form, expression_or_None)."""
    t = text.strip()
    u = t.upper()
    if u in ALLREGS:
        return u, None
    if t.startswith("#"):
        return "#N", t[1:]
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        iu = inner.upper()
        if iu in ("X", "Y"):
            return f"[{iu}]", None
        if iu in ("X+", "Y+"):
            return f"[{iu}]", None
        if iu in ("-X", "-Y"):
            return f"[{iu}]", None
        m = re.match(r"^(X|Y|SP)\s*([+-])\s*(.+)$", inner, re.I)
        if m:
            base, sign, rest = m.group(1).upper(), m.group(2), m.group(3)
            if rest.strip().upper() in REGS8:
                if base == "SP":
                    raise AsmError("SP cannot be indexed by a register")
                return f"[{base}+{rest.strip().upper()}]", None
            expr = rest if sign == "+" else f"-({rest})"
            return f"[{base}+N]", expr
        return "[N]", inner
    return "N", t


def norm_line(mnemonic, operand_text):
    """Canonical signature for a whole instruction."""
    ops = []
    if operand_text.strip():
        depth, cur = 0, ""
        for ch in operand_text:
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            if ch == "," and depth == 0:
                ops.append(cur)
                cur = ""
            else:
                cur += ch
        ops.append(cur)
    canon, exprs = [], []
    for o in ops:
        c, e = norm_operand(o)
        canon.append(c)
        if e is not None:
            exprs.append(e)
    return (mnemonic.upper(), tuple(canon)), exprs


def _build_table():
    """Signature -> (opcode, page2_opcode_or_None, operand_kind).

    Built by disassembling every encoding, so the assembler accepts
    exactly the language the disassembler emits.
    """
    table = {}

    def add(op, op2):
        buf = [op] + ([op2] if op2 is not None else []) + [0, 0]
        text, _ = opcodes.disassemble(lambda a: buf[a] if a < len(buf) else 0,
                                      0)
        if text.startswith("."):
            return
        parts = text.split(None, 1)
        mnem = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        sig, _ = norm_line(mnem, rest)
        kind = (opcodes.page2[op2][1] if op2 is not None
                else opcodes.primary[op][1])
        table.setdefault(sig, (op, op2, kind))

    for op in range(256):
        if op != 0x2F:
            add(op, None)
    for op2 in sorted(opcodes.page2):
        add(0x2F, op2)
    return table


TABLE = _build_table()

# Assembler aliases. Every one of these emits an existing orthogonal
# encoding; see docs/02-isa.md section 4.9.1.
ALIASES = {
    # section 4.9.1 idioms: these emit the orthogonal one-byte encodings
    ("SHL", 1): lambda r: ("ADD", f"{r},{r}"),
    ("ROL", 1): lambda r: ("ADC", f"{r},{r}"),
    ("CLR", 1): lambda r: ("SUB", f"{r},{r}"),
    ("TST", 1): lambda r: ("OR", f"{r},{r}"),
    ("SEXC", 1): lambda r: ("SBC", f"{r},{r}"),
    # INC/DEC were dropped as opcodes; these cost the same two bytes
    ("INC", 1): lambda r: ("ADD", f"{r},#1"),
    ("DEC", 1): lambda r: ("SUB", f"{r},#1"),
    # documented condition-code synonyms (section 6)
    ("BHS", 1): lambda t: ("BCS", t),
    ("BLO", 1): lambda t: ("BCC", t),
    ("BZ", 1): lambda t: ("BEQ", t),
    ("BNZ", 1): lambda t: ("BNE", t),
    ("BN", 1): lambda t: ("BMI", t),
    ("BP", 1): lambda t: ("BPL", t),
}


# ====================================================================
# Expressions
# ====================================================================

class Expr:
    def __init__(self, text, where):
        self.text = text
        self.where = where

    def eval(self, syms, pc):
        toks = _tokenize(self.text, self.where)
        val, pos = _parse(toks, 0, syms, pc, self.where)
        if pos != len(toks):
            raise AsmError(f"trailing junk in expression {self.text!r}",
                           self.where)
        return val


_TOKEN_RE = re.compile(r"""
    \s*(?:
      (?P<hex>\$[0-9A-Fa-f]+)
    | (?P<bin>%[01]+)
    | (?P<chr>'(?:\\.|[^'])')
    | (?P<num>\d+)
    | (?P<id>[A-Za-z_.@][A-Za-z0-9_.@]*)
    | (?P<op><<|>>|[-+*/%&|^~()<>])
    )""", re.X)


def _tokenize(text, where):
    toks, i = [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        m = _TOKEN_RE.match(text, i)
        if not m:
            raise AsmError(f"bad character {text[i]!r} in expression", where)
        toks.append(m.group().strip())
        i = m.end()
    return toks


_PREC = [("|",), ("^",), ("&",), ("<<", ">>"), ("+", "-"), ("*", "/", "%")]


def _parse(toks, i, syms, pc, where, level=0):
    if level == len(_PREC):
        return _parse_unary(toks, i, syms, pc, where)
    val, i = _parse(toks, i, syms, pc, where, level + 1)
    while i < len(toks) and toks[i] in _PREC[level]:
        opr = toks[i]
        rhs, i = _parse(toks, i + 1, syms, pc, where, level + 1)
        if opr == "+":
            val += rhs
        elif opr == "-":
            val -= rhs
        elif opr == "*":
            val *= rhs
        elif opr == "/":
            val //= rhs
        elif opr == "%":
            val %= rhs
        elif opr == "&":
            val &= rhs
        elif opr == "|":
            val |= rhs
        elif opr == "^":
            val ^= rhs
        elif opr == "<<":
            val <<= rhs
        else:
            val >>= rhs
    return val, i


def _parse_unary(toks, i, syms, pc, where):
    if i >= len(toks):
        raise AsmError("expression ended early", where)
    t = toks[i]
    if t == "-":
        v, i = _parse_unary(toks, i + 1, syms, pc, where)
        return -v, i
    if t == "~":
        v, i = _parse_unary(toks, i + 1, syms, pc, where)
        return ~v, i
    if t == "<":                                  # low byte
        v, i = _parse_unary(toks, i + 1, syms, pc, where)
        return v & 0xFF, i
    if t == ">":                                  # high byte
        v, i = _parse_unary(toks, i + 1, syms, pc, where)
        return (v >> 8) & 0xFF, i
    if t == "(":
        v, i = _parse(toks, i + 1, syms, pc, where)
        if i >= len(toks) or toks[i] != ")":
            raise AsmError("unbalanced parenthesis", where)
        return v, i + 1
    if t == "*":
        return pc, i + 1
    if t.startswith("$"):
        return int(t[1:], 16), i + 1
    if t.startswith("%"):
        return int(t[1:], 2), i + 1
    if t.startswith("'"):
        body = t[1:-1]
        if body.startswith("\\"):
            body = {"n": "\n", "r": "\r", "t": "\t", "0": "\0",
                    "\\": "\\", "'": "'"}.get(body[1], body[1])
        return ord(body), i + 1
    if t[0].isdigit():
        return int(t, 10), i + 1
    if t in syms:
        return syms[t], i + 1
    raise AsmError(f"undefined symbol {t!r}", where)


# ====================================================================
# Assembler
# ====================================================================

class Item:
    """One emitted thing: an instruction or a lump of data."""

    def __init__(self, addr, kind, source, where):
        self.addr = addr
        self.kind = kind                # 'insn' | 'data'
        self.source = source
        self.where = where
        self.data = b""
        self.op = None
        self.op2 = None
        self.routine = None


class Assembler:
    def __init__(self):
        self.syms = {}
        self.items = []
        self.macros = {}
        self.pc = 0
        self.errors = []
        self.macro_serial = 0
        self.cur_global = ""

    # ------------------------------------------------------ source prep

    def resolve(self, name, path):
        """Where an .include lives: next to the file that asked for it,
        or on the -I path.

        The second is what lets generated assembly include sw/fs.asm.
        The compiler writes its output into a build directory, so a
        sibling lookup would look for fs.asm there and not find it."""
        here = os.path.join(os.path.dirname(path), name)
        if os.path.exists(here):
            return here
        for d in getattr(self, "incdirs", ()):
            cand = os.path.join(d, name)
            if os.path.exists(cand):
                return cand
        return here                     # let open() report it

    def read(self, path, seen=None):
        seen = seen or set()
        real = os.path.abspath(path)
        if real in seen:
            raise AsmError(f"circular include of {path}")
        seen.add(real)
        out = []
        with open(path, encoding="utf-8") as fh:
            for n, raw in enumerate(fh, 1):
                m = re.match(r'\s*\.include\s+"([^"]+)"', raw, re.I)
                if m:
                    out.extend(self.read(self.resolve(m.group(1), path),
                                         seen))
                else:
                    out.append((f"{os.path.basename(path)}:{n}", raw))
        return out

    @staticmethod
    def split(raw):
        """Strip the comment, respecting quotes. Returns (code, comment)."""
        out, q, i = "", None, 0
        while i < len(raw):
            ch = raw[i]
            if q:
                out += ch
                if ch == "\\" and i + 1 < len(raw):
                    out += raw[i + 1]
                    i += 1
                elif ch == q:
                    q = None
            elif ch in "\"'":
                q = ch
                out += ch
            elif ch == ";":
                return out, raw[i:].rstrip()
            else:
                out += ch
            i += 1
        return out, ""

    def expand_macros(self, lines):
        out, i = [], 0
        while i < len(lines):
            where, raw = lines[i]
            code, _ = self.split(raw)
            m = re.match(r"\s*\.macro\s+(\S+)\s*(.*)$", code, re.I)
            if m:
                name = m.group(1).upper()
                params = [p.strip() for p in m.group(2).split(",") if p.strip()]
                body, i = [], i + 1
                while i < len(lines):
                    c2, _ = self.split(lines[i][1])
                    if re.match(r"\s*\.endm\s*$", c2, re.I):
                        break
                    body.append(lines[i])
                    i += 1
                else:
                    raise AsmError(f"macro {name} has no .endm", where)
                self.macros[name] = (params, body)
                i += 1
                continue

            head = re.match(r"\s*(?:([A-Za-z_.@][\w.@]*):)?\s*(\S+)\s*(.*)$",
                            code)
            if head and head.group(2) and head.group(2).upper() in self.macros:
                params, body = self.macros[head.group(2).upper()]
                args = _split_args(head.group(3))
                if len(args) != len(params):
                    raise AsmError(
                        f"macro {head.group(2)} takes {len(params)} "
                        f"argument(s), got {len(args)}", where)
                if head.group(1):
                    out.append((where, f"{head.group(1)}:"))
                self.macro_serial += 1
                sub = dict(zip(params, args))
                for bwhere, braw in body:
                    text = braw
                    for k, v in sub.items():
                        text = re.sub(r"\\" + re.escape(k) + r"\b", v, text)
                    # @name is a macro-local label. It becomes a *local*
                    # label (leading dot) so a macro used inside a routine
                    # cannot accidentally end that routine's label scope.
                    text = re.sub(r"@(\w+)",
                                  lambda mm: f".__m{self.macro_serial}_"
                                             f"{mm.group(1)}", text)
                    out.append((f"{where}>{bwhere}", text))
                i += 1
                continue
            out.append((where, raw))
            i += 1
        return out

    # ------------------------------------------------------------ pass 1

    def pass1(self, lines):
        for where, raw in lines:
            code, comment = self.split(raw)
            if not code.strip():
                continue
            try:
                self._pass1_line(code, comment, where, raw.rstrip())
            except AsmError as e:
                self.errors.append(f"{where}: {e}")

    def _pass1_line(self, code, comment, where, raw):
        m = re.match(r"\s*([A-Za-z_.@][\w.@]*):\s*(.*)$", code)
        if m:
            name = m.group(1)
            if name.startswith("."):
                if not self.cur_global:
                    raise AsmError("local label before any global label",
                                   where)
                name = self.cur_global + name
            else:
                self.cur_global = name
            if name in self.syms:
                raise AsmError(f"duplicate label {name!r}", where)
            self.syms[name] = self.pc
            code = m.group(2)
        if not code.strip():
            if comment or raw.strip():
                it = Item(self.pc, "label", raw, where)
                it.routine = self.cur_global
                self.items.append(it)
            return

        parts = code.split(None, 1)
        head = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""

        m = re.match(r"([A-Za-z_][\w.]*)\s*=\s*(.+)$", code.strip())
        if m and not head.startswith("."):
            self.syms[m.group(1)] = Expr(m.group(2), where).eval(self.syms,
                                                                 self.pc)
            return

        if head.startswith("."):
            self._directive(head.lower(), rest, where, raw)
            return

        self._instruction(head, rest, where, raw)

    def _directive(self, name, rest, where, raw):
        if name == ".org":
            self.pc = Expr(rest, where).eval(self.syms, self.pc) & 0xFFFF
            return
        if name in (".equ", ".set"):
            n, _, e = rest.partition(",")
            self.syms[n.strip()] = Expr(e, where).eval(self.syms, self.pc)
            return
        if name == ".align":
            n = Expr(rest, where).eval(self.syms, self.pc)
            pad = (-self.pc) % n
            self._emit_data(b"\x00" * pad, raw, where)
            return

        it = Item(self.pc, "data", raw, where)
        it.routine = self.cur_global
        if name in (".byte", ".db"):
            it.exprs, it.width = _split_args(rest), 1
            it.size = sum(len(_strbytes(a)) if _isstr(a) else 1
                          for a in it.exprs)
        elif name in (".word", ".dw"):
            it.exprs, it.width = _split_args(rest), 2
            it.size = 2 * len(it.exprs)
        elif name in (".ascii", ".asciz"):
            body = _strbytes(rest.strip())
            if name == ".asciz":
                body += b"\x00"
            it.data, it.size, it.exprs = body, len(body), None
        elif name in (".space", ".res", ".fill"):
            args = _split_args(rest)
            n = Expr(args[0], where).eval(self.syms, self.pc)
            fill = (Expr(args[1], where).eval(self.syms, self.pc)
                    if len(args) > 1 else 0)
            it.data, it.size, it.exprs = bytes([fill & 0xFF]) * n, n, None
        else:
            raise AsmError(f"unknown directive {name!r}", where)
        self.items.append(it)
        self.pc = (self.pc + it.size) & 0xFFFF

    def _emit_data(self, data, raw, where):
        if not data:
            return
        it = Item(self.pc, "data", raw, where)
        it.data, it.size, it.exprs = data, len(data), None
        it.routine = self.cur_global
        self.items.append(it)
        self.pc = (self.pc + it.size) & 0xFFFF

    def _instruction(self, mnem, rest, where, raw):
        key = (mnem.upper(), len(_split_args(rest)) if rest.strip() else 0)
        if key in ALIASES:
            mnem, rest = ALIASES[key](_split_args(rest)[0].strip())

        sig, exprs = norm_line(mnem, rest)
        # local label references resolve against the enclosing global
        exprs = [self._qualify(e) for e in exprs]
        if sig not in TABLE:
            raise AsmError(
                f"no encoding for {mnem.upper()} "
                f"{', '.join(sig[1]) if sig[1] else ''}".rstrip(), where)
        op, op2, kind = TABLE[sig]
        it = Item(self.pc, "insn", raw, where)
        it.op, it.op2, it.kind_operand = op, op2, kind
        it.exprs = [Expr(e, where) for e in exprs]
        it.size = opcodes.length(op, op2)
        it.routine = self.cur_global
        self.items.append(it)
        self.pc = (self.pc + it.size) & 0xFFFF

    def _qualify(self, expr):
        """Rewrite bare local labels (.foo) to Global.foo."""
        if not self.cur_global:
            return expr
        return re.sub(r"(?<![\w.])\.(\w+)",
                      lambda m: f"{self.cur_global}.{m.group(1)}", expr)

    # ------------------------------------------------------------ pass 2

    def pass2(self):
        for it in self.items:
            try:
                if it.kind == "insn":
                    it.data = self._encode(it)
                elif it.kind == "data" and getattr(it, "exprs", None):
                    out = bytearray()
                    for a in it.exprs:
                        if _isstr(a):
                            out += _strbytes(a)
                            continue
                        v = Expr(a, it.where).eval(self.syms, it.addr)
                        if it.width == 1:
                            out.append(v & 0xFF)
                        else:
                            out += bytes([v & 0xFF, (v >> 8) & 0xFF])
                    it.data = bytes(out)
                    if len(it.data) != it.size:
                        raise AsmError("data size changed between passes",
                                       it.where)
            except AsmError as e:
                self.errors.append(f"{it.where}: {e}")

    def _encode(self, it):
        out = bytearray([it.op] if it.op2 is None else [it.op, it.op2])
        kind = it.kind_operand
        n = opcodes.EXTRA[kind]
        if n == 0:
            return bytes(out)
        v = it.exprs[0].eval(self.syms, it.addr)
        if kind == opcodes.REL8:
            d = v - (it.addr + it.size)
            if not -128 <= d <= 127:
                raise AsmError(
                    f"branch out of range: {d:+d} bytes "
                    f"(target ${v:04X} from ${it.addr:04X}); "
                    f"use JMP or move the target closer", it.where)
            out.append(d & 0xFF)
        elif kind in (opcodes.ABS16, opcodes.IMM16):
            out += bytes([v & 0xFF, (v >> 8) & 0xFF])
        elif kind == opcodes.DISP8:
            if not -128 <= v <= 127:
                raise AsmError(f"signed displacement {v} out of range "
                               "(-128..127)", it.where)
            out.append(v & 0xFF)
        elif kind == opcodes.U8:
            if not 0 <= v <= 255:
                raise AsmError(f"unsigned displacement {v} out of range "
                               "(0..255)", it.where)
            out.append(v)
        else:                                        # IMM8, MASK8
            if not -128 <= v <= 255:
                raise AsmError(f"immediate {v} does not fit in a byte",
                               it.where)
            out.append(v & 0xFF)
        return bytes(out)

    # ------------------------------------------------------------ output

    def image(self):
        if not self.items:
            return 0, b""
        placed = [i for i in self.items if i.data]
        if not placed:
            return 0, b""
        lo = min(i.addr for i in placed)
        hi = max(i.addr + len(i.data) for i in placed)
        buf = bytearray(hi - lo)
        for i in placed:
            buf[i.addr - lo:i.addr - lo + len(i.data)] = i.data
        return lo, bytes(buf)

    def listing(self):
        out = ["; addr  bytes        cyc  source", ";" + "-" * 70]
        for it in self.items:
            if it.kind == "label":
                out.append(f"                          {it.source}")
                continue
            raw = " ".join(f"{b:02X}" for b in it.data[:4])
            if len(it.data) > 4:
                raw += ".."
            if it.kind == "insn":
                c = opcodes.cycles(it.op, it.op2)
                cyc = f"{c[0]}/{c[1]}" if isinstance(c, tuple) else str(c)
            else:
                cyc = ""
            out.append(f"{it.addr:04X}  {raw:<12} {cyc:>4}  {it.source}")
        out.append("")
        out.append("; routine                bytes  cycles(min)  insns")
        for name, st in self.routine_stats().items():
            out.append(f"; {name:<22} {st['bytes']:5}  {st['cycles']:11}  "
                       f"{st['insns']:5}")
        return "\n".join(out)

    def symbols(self):
        return "\n".join(f"{v:04X}  {k}" for k, v in
                         sorted(self.syms.items(), key=lambda kv: kv[1]))

    def routine_stats(self):
        stats = {}
        for it in self.items:
            if it.kind == "label" or not it.routine:
                continue
            s = stats.setdefault(it.routine,
                                 {"bytes": 0, "cycles": 0, "insns": 0})
            s["bytes"] += len(it.data)
            if it.kind == "insn":
                s["insns"] += 1
                c = opcodes.cycles(it.op, it.op2)
                s["cycles"] += c[0] if isinstance(c, tuple) else c
        return stats

    # -------------------------------------------------- pressure report

    def pressure(self):
        """Per-routine register usage and spill traffic.

        Spill traffic is the honest, mechanically-derived signal for the
        four-register question: PUSH/POP of a general register, and
        stack-slot stores and reloads, are work the machine only does
        because it ran out of registers.
        """
        rows = {}
        for it in self.items:
            if it.kind != "insn" or not it.routine:
                continue
            r = rows.setdefault(it.routine, {
                "insns": 0, "bytes": 0, "cycles": 0, "spill": 0,
                "used": set(), "ptr": set(), "calls": 0})
            r["insns"] += 1
            r["bytes"] += len(it.data)
            c = opcodes.cycles(it.op, it.op2)
            r["cycles"] += c[0] if isinstance(c, tuple) else c

            op, op2 = it.op, it.op2
            text, _ = opcodes.disassemble(
                lambda a, d=it.data: d[a] if a < len(d) else 0, 0)
            for reg in REGS8:
                if re.search(rf"\b{reg}\b", text):
                    r["used"].add(reg)
            for reg in ("X", "Y"):
                if re.search(rf"\b{reg}L?H?\b", text) or f"[{reg}" in text:
                    r["ptr"].add(reg)
            if op in (0x29, 0x2C, 0x2D):
                r["calls"] += 1
            # spill traffic: GPR push/pop, and stack-slot load/store
            if 0x30 <= op <= 0x37 or 0x3C <= op <= 0x3F:
                r["spill"] += 1
            if 0x60 <= op <= 0x6F and not (op & 1):   # [SP+u8]
                r["spill"] += 1
        return rows


def _split_args(text):
    out, depth, cur, q = [], 0, "", None
    for ch in text:
        if q:
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch
            cur += ch
            continue
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _isstr(a):
    return a.strip().startswith('"')


def _strbytes(a):
    a = a.strip()
    if not a.startswith('"'):
        raise AsmError(f"expected a string, got {a!r}")
    body = a[1:-1]
    return (body.replace("\\n", "\n").replace("\\r", "\r")
                .replace("\\t", "\t").replace("\\0", "\0")
                .replace('\\"', '"').replace("\\\\", "\\")).encode("latin-1")


def assemble(path, incdirs=()):
    a = Assembler()
    a.incdirs = list(incdirs)
    lines = a.read(path)
    lines = a.expand_macros(lines)
    a.pass1(lines)
    a.pass2()
    return a


def main():
    ap = argparse.ArgumentParser(description="COOL8 assembler")
    ap.add_argument("source")
    ap.add_argument("-o", "--output")
    ap.add_argument("--listing")
    ap.add_argument("--symbols")
    ap.add_argument("--pressure", action="store_true")
    ap.add_argument("-I", "--include-dir", action="append", default=[],
                    metavar="DIR",
                    help="where .include looks when the file is not a "
                         "sibling of the one including it")
    args = ap.parse_args()

    try:
        a = assemble(args.source, args.include_dir)
    except AsmError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    for e in a.errors:
        print(f"error: {e}", file=sys.stderr)
    if a.errors:
        sys.exit(1)

    base, img = a.image()
    if args.output:
        with open(args.output, "wb") as fh:
            fh.write(img)
    if args.listing:
        with open(args.listing, "w", encoding="utf-8") as fh:
            fh.write(a.listing() + "\n")
    if args.symbols:
        with open(args.symbols, "w", encoding="utf-8") as fh:
            fh.write(a.symbols() + "\n")

    print(f"{len(img)} bytes at ${base:04X}-${base + len(img) - 1:04X}, "
          f"{len(a.syms)} symbols")

    if args.pressure:
        rows = a.pressure()
        print(f"\n{'routine':<20} {'insn':>5} {'byte':>5} {'cyc':>6} "
              f"{'GPRs':>5} {'ptr':>4} {'spill':>6} {'spill%':>7}")
        print("-" * 68)
        tot_i = tot_s = 0
        for name, r in sorted(rows.items()):
            pct = 100.0 * r["spill"] / r["insns"] if r["insns"] else 0
            tot_i += r["insns"]
            tot_s += r["spill"]
            print(f"{name:<20} {r['insns']:5} {r['bytes']:5} {r['cycles']:6} "
                  f"{len(r['used']):5} {len(r['ptr']):4} {r['spill']:6} "
                  f"{pct:6.1f}%")
        print("-" * 68)
        pct = 100.0 * tot_s / tot_i if tot_i else 0
        print(f"{'TOTAL':<20} {tot_i:5} {'':5} {'':6} {'':5} {'':4} "
              f"{tot_s:6} {pct:6.1f}%")
        spilling = [n for n, r in rows.items() if r["spill"]]
        print(f"\n{len(spilling)}/{len(rows)} routines spill at all"
              + (f": {', '.join(sorted(spilling))}" if spilling else ""))


if __name__ == "__main__":
    main()
