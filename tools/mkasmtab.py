#!/usr/bin/env python3
"""Generate sw/asmtab.asm, the on-machine assembler's mnemonic table.

    python tools/mkasmtab.py            # write sw/asmtab.asm
    python tools/mkasmtab.py --check    # fail if it would differ

`tools/opcodes.py` is the single source of truth for the encoding
(AGENTS.md), and `sw/disasm.asm` cannot be shared: it lives only in the
4 KB boot ROM at $F72E, reachable from the monitor's `U` command and
from nowhere else, and BASIC runs with ROMEN clear over the top of it.
So the machine-side assembler needs its own table -- but a *derived*
one, not a second authored copy. This is what derives it.

## What comes out

One entry per spelling: three key bytes and one payload.

    .byte 'A','D','C', (AF_ALU<<4)|1

**The key is (first, second, last).** Measured over every mnemonic and
alias: 61 real ones collide nowhere, and adding the 13 aliases collides
exactly once, `SEC` against `SEXC`. `SEXC` is cut -- it is `SBC Rd,Rd`
spelled out, and writing it that way costs nothing. Three bytes beats
five: `ADD`/`ADDW`, `MOV`/`MOVW`, `PUSH`/`PUSHW`, `LD`/`LDW`, `ST`/`STW`
and `RET`/`RETI` all separate on the last character.

**The payload is a family and a base**, four bits each. The family says
which arithmetic rule builds the opcode -- the encodings are arithmetic
rather than a table (docs/11-compiler.md section 3), so thirteen rules
cover all 491 encodings. The base is the field that rule adds: the ALU
operation, the condition code, the page-2 group.

## The check that matters

Emitting a table proves nothing. `verify()` below implements every
family rule in Python and requires it to reproduce **every one of the
491 encodings in cool8asm.TABLE**, which is itself built by
disassembling all of them. So the rules are proved here, cheaply, and
`sw/asm.asm` only has to mirror arithmetic that is already known good.
Anything the rules cannot reach is named in CUT, and CUT is checked
against the table too -- an encoding that is neither implemented nor
deliberately cut fails.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import cool8asm as A                                      # noqa: E402
import opcodes                                            # noqa: E402

OUT = os.path.join(ROOT, "sw", "asmtab.asm")

# ---- the families, mirrored by sw/asm.asm ---------------------------
AF_NONE = 0     # no operands; base indexes amnone
AF_ALU = 1      # Rd,#N | Rd,Rs                     base = ALU op 0-7
AF_ALUDUP = 2   # Rd -> ALU Rd,Rd                   base = ALU op
AF_ALUIM1 = 3   # Rd -> ALU Rd,#1                   base = ALU op
AF_BR = 4       # N                                 base = cc 0-15
AF_UNARY = 5    # Rd, page 2                        base = group
AF_BIT = 6      # Rd,#N, page 2                     base = group
AF_LDST = 7     # the six addressing modes          base = 0 LD, 1 ST
AF_W16 = 8      # the 16-bit ops                    base = subcode
AF_STK = 9      # PUSH/POP                          base = 0/1
AF_JMP = 10     # JMP/CALL: N | [X] | [Y]           base = 0/1
AF_MUL = 11     # Rd,Rs page 2
AF_XOR = 12     # Rd,#N | Rd,Rs, page 2

FAMNAME = {v: k for k, v in globals().items() if k.startswith("AF_")}

ALU = ["MOV", "ADD", "ADC", "SUB", "SBC", "AND", "OR", "CMP"]
CC = ["BRA", "BNV", "BEQ", "BNE", "BCS", "BCC", "BMI", "BPL",
      "BVS", "BVC", "BHI", "BLS", "BGE", "BLT", "BGT", "BLE"]
# Page 2 puts these at $14 + i*4 + dd and $30 + i*4 + dd, so both stay
# affine and the order below is load-bearing. The ROL slot between ROR
# and BSET is deliberately empty (opcodes.py:121-123).
UNARY = ["NOT", "NEG", "SWAP", "SHR", "SAR", "ROR"]
BIT = ["BSET", "BCLR", "BTST"]

# No-operand instructions, and their bytes. CLV is the only page-2 one,
# and BRK sits at $2E rather than with the rest.
NONE = [("NOP", None, 0x20), ("HALT", None, 0x21), ("RET", None, 0x22),
        ("RETI", None, 0x23), ("EI", None, 0x24), ("DI", None, 0x25),
        ("CLC", None, 0x26), ("SEC", None, 0x27), ("BRK", None, 0x2E),
        ("CLV", 0x2F, 0xE2)]

# Condition-code synonyms: a different spelling of the same cc, so they
# need no rewriting at all -- only the right base.
CC_ALIAS = {"BHS": "BCS", "BLO": "BCC", "BZ": "BEQ",
            "BNZ": "BNE", "BN": "BMI", "BP": "BPL"}
# Idioms that rewrite their operands. Four duplicate the register and
# two append an immediate 1; that is why AF_ALUDUP and AF_ALUIM1 exist
# rather than a general rewrite mechanism.
DUP_ALIAS = {"CLR": "SUB", "TST": "OR", "SHL": "ADD", "ROL": "ADC"}
IM1_ALIAS = {"INC": "ADD", "DEC": "SUB"}

# Deliberately not reachable, and why. sim/test_asm.py requires every
# signature in cool8asm.TABLE to be either encodable or named here.
CUT = {
    ("PUSH", ("N",)): "PUSH F -- the flags register, nothing needs it",
    ("POP", ("N",)): "POP F -- likewise",
    ("BNV", ("N",)): "never branches; disasm.asm renders it ???",
}


# ---- the family rules, in Python, so they can be proved -------------

def rule(fam, base, ops):
    """(prefix, opcode) for one signature, or None if the family does
    not accept these operands. Mirrored instruction for instruction by
    sw/asm.asm; every line here is one add there."""
    def rn(o):
        return int(o[1]) if len(o) == 2 and o[0] == "R" else None

    if fam == AF_NONE:
        pre, op = NONE[base][1], NONE[base][2]
        return (pre, op) if ops == () else None

    if fam in (AF_ALU, AF_XOR):
        if len(ops) != 2:
            return None
        d = rn(ops[0])
        if d is None:
            # MOV pp,Rd -- the only form whose first operand is not a
            # register, and page 2 $50 is its half of the pair.
            if fam == AF_ALU and base == 0 and ops[0] in PP:
                s = rn(ops[1])
                return (0x2F, 0x50 | (s << 2) | PP[ops[0]]) \
                    if s is not None else None
            return None
        if fam == AF_XOR:
            # XOR is the eighth ALU operation and had no room in the
            # one-byte blocks, so both its forms are on page 2:
            # $00-$0F register, $10-$13 immediate.
            if ops[1] == "#N":
                return (0x2F, 0x10 + d)
            s = rn(ops[1])
            return (0x2F, 0x00 | (d << 2) | s) if s is not None else None
        if ops[1] == "#N":                  # $00-$1F, 8 ops x 4 regs
            return (None, 0x00 | (base << 2) | d)
        s = rn(ops[1])
        if s is not None:                   # $80-$FF
            return (None, 0x80 | (base << 4) | (d << 2) | s)
        # MOV Rd,pp is page 2 $40, MOV pp,Rd is $50
        if base == 0 and ops[1] in PP:
            return (0x2F, 0x40 | (d << 2) | PP[ops[1]])
        return None

    if fam == AF_ALUDUP:                    # CLR r -> SUB r,r
        d = rn(ops[0]) if len(ops) == 1 else None
        return (None, 0x80 | (base << 4) | (d << 2) | d) if d is not None \
            else None

    if fam == AF_ALUIM1:                    # INC r -> ADD r,#1
        d = rn(ops[0]) if len(ops) == 1 else None
        return (None, 0x00 | (base << 2) | d) if d is not None else None

    if fam == AF_BR:
        return (None, 0x70 | base) if ops == ("N",) else None

    if fam == AF_UNARY:                     # p2 $14-$2B, 4 regs each
        d = rn(ops[0]) if len(ops) == 1 else None
        return (0x2F, 0x14 + base * 4 + d) if d is not None else None

    if fam == AF_BIT:                       # p2 $30-$3B
        if len(ops) != 2 or ops[1] != "#N":
            return None
        d = rn(ops[0])
        return (0x2F, 0x30 + base * 4 + d) if d is not None else None

    if fam == AF_MUL:
        if len(ops) != 2:
            return None
        d, s = rn(ops[0]), rn(ops[1])
        return (0x2F, 0xF0 | (d << 2) | s) if None not in (d, s) else None

    if fam == AF_STK:                       # $30-$37, PUSH=0 POP=1
        d = rn(ops[0]) if len(ops) == 1 else None
        return (None, 0x30 + base * 4 + d) if d is not None else None

    if fam == AF_JMP:                       # $28/$29 abs, $2A-$2D [X|Y]
        if len(ops) != 1:
            return None
        if ops[0] == "N":
            return (None, 0x28 + base)
        if ops[0] in ("[X]", "[Y]"):
            return (None, 0x2A + base * 2 + (ops[0] == "[Y]"))
        return None

    if fam == AF_LDST:
        return ldst(base, ops)

    if fam == AF_W16:
        return w16(base, ops)

    return None


PP = {"XL": 0, "XH": 1, "YL": 2, "YH": 3}


def ldst(st, ops):
    """LD/ST in six addressing modes, three of them on page 2.

    $40/$50 are [X|Y] and [X|Y+d8]; $60 is [SP+u8] and [abs16]; page 2
    carries the register-indexed and auto-increment forms."""
    a, b = (ops[0], ops[1]) if st == 0 else (ops[1], ops[0])
    if len(ops) != 2 or len(a) != 2 or a[0] != "R":
        return None
    d = int(a[1])
    if b in ("[X]", "[Y]"):
        return (None, 0x40 + st * 8 + d * 2 + (b == "[Y]"))
    if b in ("[X+N]", "[Y+N]"):
        return (None, 0x50 + st * 8 + d * 2 + (b == "[Y+N]"))
    if b == "[SP+N]":
        return (None, 0x60 + st * 8 + d * 2)
    if b == "[N]":
        return (None, 0x60 + st * 8 + d * 2 + 1)
    if len(b) == 6 and b[1] in "XY" and b[3] == "R":    # [X+R0]
        return (0x2F, 0x80 + st * 32 + (b[1] == "Y") * 16
                + d * 4 + int(b[4]))
    # $C0 is post-increment and $D0 pre-decrement; within each, bit 3
    # is LD/ST and bit 0 picks the pointer -- the same shape as $40/$50.
    if b in ("[X+]", "[Y+]"):
        return (0x2F, 0xC0 + st * 8 + d * 2 + (b == "[Y+]"))
    if b in ("[-X]", "[-Y]"):
        return (0x2F, 0xD0 + st * 8 + d * 2 + (b == "[-Y]"))
    return None


# The 16-bit block is the one corner that is not affine, so it is a
# small table of (mnemonic, operand shapes) -> page-2 opcode rather
# than arithmetic. Fifteen entries; disasm.asm bakes the operand text
# into w16_ops for the same reason, going the other way.
W16 = {
    ("LDW", ("X", "#N")): (0x2F, 0x60), ("LDW", ("Y", "#N")): (0x2F, 0x61),
    ("LDW", ("X", "[N]")): (0x2F, 0x62), ("LDW", ("Y", "[N]")): (0x2F, 0x63),
    ("STW", ("[N]", "X")): (0x2F, 0x64), ("STW", ("[N]", "Y")): (0x2F, 0x65),
    ("MOVW", ("X", "Y")): (0x2F, 0x66), ("MOVW", ("Y", "X")): (0x2F, 0x67),
    ("MOVW", ("SP", "X")): (0x2F, 0x68), ("MOVW", ("SP", "Y")): (0x2F, 0x69),
    ("MOVW", ("X", "SP")): (0x2F, 0x6A), ("MOVW", ("Y", "SP")): (0x2F, 0x6B),
    ("ADDW", ("SP", "#N")): (0x2F, 0x6C),
    ("LEA", ("X", "[SP+N]")): (0x2F, 0x6D),
    ("LEA", ("Y", "[SP+N]")): (0x2F, 0x6E),
    ("INCW", ("X",)): (None, 0x38), ("INCW", ("Y",)): (None, 0x39),
    ("DECW", ("X",)): (None, 0x3A), ("DECW", ("Y",)): (None, 0x3B),
    ("PUSHW", ("X",)): (None, 0x3C), ("PUSHW", ("Y",)): (None, 0x3D),
    ("POPW", ("X",)): (None, 0x3E), ("POPW", ("Y",)): (None, 0x3F),
    ("ADDW", ("X", "#N")): (0x2F, 0x2C), ("ADDW", ("Y", "#N")): (0x2F, 0x2D),
}
W16NAME = ["LDW", "STW", "MOVW", "ADDW", "SUBW", "LEA",
           "INCW", "DECW", "PUSHW", "POPW"]


def w16(base, ops):
    name = W16NAME[base]
    hit = W16.get((name, ops))
    if hit:
        return hit
    if name == "ADDW" and len(ops) == 2 and ops[0] in ("X", "Y") \
            and len(ops[1]) == 2 and ops[1][0] == "R":
        return (0x2F, 0x70 + (ops[0] == "Y") * 4 + int(ops[1][1]))
    if name == "SUBW" and len(ops) == 2 and ops[0] in ("X", "Y") \
            and len(ops[1]) == 2 and ops[1][0] == "R":
        return (0x2F, 0x78 + (ops[0] == "Y") * 4 + int(ops[1][1]))
    return None


# ---- the spellings ---------------------------------------------------

def spellings():
    """[(name, family, base)], in the order they are emitted."""
    out = []
    for i, m in enumerate(ALU):
        out.append((m, AF_ALU, i))
    out.append(("XOR", AF_XOR, 0))
    for i, m in enumerate(CC):
        out.append((m, AF_BR, i))
    for a, real in CC_ALIAS.items():
        out.append((a, AF_BR, CC.index(real)))
    for a, real in DUP_ALIAS.items():
        out.append((a, AF_ALUDUP, ALU.index(real)))
    for a, real in IM1_ALIAS.items():
        out.append((a, AF_ALUIM1, ALU.index(real)))
    for i, m in enumerate(UNARY):
        out.append((m, AF_UNARY, i))
    for i, m in enumerate(BIT):
        out.append((m, AF_BIT, i))
    for i, (m, _, _) in enumerate(NONE):
        out.append((m, AF_NONE, i))
    out.append(("LD", AF_LDST, 0))
    out.append(("ST", AF_LDST, 1))
    for i, m in enumerate(W16NAME):
        out.append((m, AF_W16, i))
    out.append(("PUSH", AF_STK, 0))
    out.append(("POP", AF_STK, 1))
    out.append(("JMP", AF_JMP, 0))
    out.append(("CALL", AF_JMP, 1))
    out.append(("MUL", AF_MUL, 0))
    return out


def key(name):
    return (name[0], name[1] if len(name) > 1 else " ", name[-1])


def verify():
    """Every encoding in cool8asm.TABLE, reproduced by the rules."""
    fams = {n: (f, b) for n, f, b in spellings()}
    bad, cut_hit = [], set()
    for (mnem, ops), (op, op2, _) in sorted(A.TABLE.items()):
        if (mnem, ops) in CUT:
            cut_hit.add((mnem, ops))
            continue
        if mnem not in fams:
            bad.append(f"{mnem} {','.join(ops)}: no family")
            continue
        f, b = fams[mnem]
        got = rule(f, b, ops)
        want = (op2 is not None and 0x2F or None, op2 if op2 is not None
                else op)
        if got != want:
            bad.append(f"{mnem} {','.join(ops):22} {FAMNAME[f]:9} "
                       f"got {got}, want {want}")
    stale = set(CUT) - cut_hit
    for s in sorted(stale):
        bad.append(f"CUT names {s}, which is not an encoding")
    # keys must stay unique
    seen = {}
    for n, _, _ in spellings():
        k = key(n)
        if k in seen:
            bad.append(f"key {''.join(k)} collides: {seen[k]} and {n}")
        seen[k] = n
    return bad


def render():
    lines = [
        "; ---------------------------------------------------------------------",
        "; asmtab.asm -- the on-machine assembler's mnemonic table.",
        ";",
        "; GENERATED by tools/mkasmtab.py from tools/opcodes.py. Do not edit:",
        "; sim/test_asm.py regenerates this and fails if it differs, which is",
        "; what keeps one source of truth for the encoding (AGENTS.md).",
        ";",
        "; Three key bytes -- first, second and last character of the mnemonic",
        "; -- then a family in the high nibble and its base field in the low.",
        "; The family names below are mirrored by the encoders in sw/asm.asm.",
        "; ---------------------------------------------------------------------",
        "",
    ]
    for n, v in sorted(FAMNAME.items()):
        lines.append(f"{v:<10}= {n}")
    lines += ["", f"AMENT   = 4                     ; bytes per entry",
              f"AMCOUNT = {len(spellings())}", "", "amtab:"]
    for n, f, b in spellings():
        k = key(n)
        ch = ",".join(f"'{c}'" if c != " " else "$20" for c in k)
        lines.append(f"        .byte {ch},({FAMNAME[f]}<<4)|{b}"
                     f"        ; {n}")
    lines += ["        .byte 0", "",
              "; No-operand instructions: prefix ($00 for page 1) and opcode.",
              "amnone:"]
    for n, pre, op in NONE:
        lines.append(f"        .byte ${pre or 0:02X},${op:02X}"
                     f"                 ; {n}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="fail if sw/asmtab.asm is not what would be written")
    args = ap.parse_args()

    bad = verify()
    if bad:
        print(f"the family rules do not reproduce the encoding "
              f"({len(bad)} problems):")
        for b in bad[:40]:
            print("   ", b)
        return 1
    n = len(A.TABLE) - len(CUT)
    print(f"  {len(spellings())} spellings, {len(FAMNAME)} families, "
          f"reproducing {n} of {len(A.TABLE)} encodings "
          f"({len(CUT)} deliberately cut)")

    text = render()
    if args.check:
        have = open(OUT).read() if os.path.exists(OUT) else None
        if have != text:
            print(f"  {OUT} is stale -- rerun tools/mkasmtab.py")
            return 1
        print(f"  {OUT} is current")
        return 0
    with open(OUT, "w") as fh:
        fh.write(text)
    print(f"  wrote {OUT}, {len(text.splitlines())} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
