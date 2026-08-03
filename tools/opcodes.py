#!/usr/bin/env python3
"""COOL8 opcode table — the single source of truth for the encoding.

Expands the encoding rules in docs/02-isa.md into a flat 256-entry
primary table and a sparse page-2 table, and self-checks that the
primary page is exactly covered with no collisions and no gaps.

The emulator, disassembler and assembler all import this rather than
each carrying their own copy of the map.

Mnemonics carry explicit operand placeholders so the table alone is
enough to render an instruction:

    {i}  8-bit immediate, unsigned      #$2A
    {m}  8-bit bit-mask immediate       #$01
    {d}  8-bit displacement, signed     +5 / -3
    {u}  8-bit displacement, unsigned   4
    {a}  16-bit absolute address        $1234
    {w}  16-bit immediate               $1234
    {t}  branch target, resolved        $04A0

Run directly to print the table and the coverage check:
    python tools/opcodes.py
    python tools/opcodes.py --check
"""

import sys

REGS = ["R0", "R1", "R2", "R3"]
ALU = ["MOV", "ADD", "ADC", "SUB", "SBC", "AND", "OR", "CMP"]
COND = ["BRA", "BNV", "BEQ", "BNE", "BCS", "BCC", "BMI", "BPL",
        "BVS", "BVC", "BHI", "BLS", "BGE", "BLT", "BGT", "BLE"]
PTR = ["X", "Y"]
HALVES = ["XL", "XH", "YL", "YH"]

# Operand kinds and how many bytes follow the opcode
NONE, IMM8, MASK8, DISP8, U8, REL8, ABS16, IMM16 = range(8)
EXTRA = {NONE: 0, IMM8: 1, MASK8: 1, DISP8: 1, U8: 1,
         REL8: 1, ABS16: 2, IMM16: 2}

primary = [None] * 256
page2 = {}


def put(table, op, mnemonic, operand=NONE):
    if isinstance(table, list):
        assert table[op] is None, f"collision at ${op:02X}: {mnemonic}"
        table[op] = (mnemonic, operand)
    else:
        assert op not in table, f"page2 collision at ${op:02X}: {mnemonic}"
        table[op] = (mnemonic, operand)


# --- $00-$1F : 000 ooo dd  ALU Rd,#imm8 -------------------------------
for ooo, name in enumerate(ALU):
    for dd, r in enumerate(REGS):
        put(primary, (ooo << 2) | dd, f"{name} {r},#{{i}}", IMM8)

# --- $20-$2F : control and flow ---------------------------------------
for op, (m, o) in {
    0x20: ("NOP", NONE),        0x21: ("HALT", NONE),
    0x22: ("RET", NONE),        0x23: ("RETI", NONE),
    0x24: ("EI", NONE),         0x25: ("DI", NONE),
    0x26: ("CLC", NONE),        0x27: ("SEC", NONE),
    0x28: ("JMP {a}", ABS16),   0x29: ("CALL {a}", ABS16),
    0x2A: ("JMP [X]", NONE),    0x2B: ("JMP [Y]", NONE),
    0x2C: ("CALL [X]", NONE),   0x2D: ("CALL [Y]", NONE),
    0x2E: ("BRK", NONE),        0x2F: ("<page2>", NONE),
}.items():
    put(primary, op, m, o)

# --- $30-$37 : PUSH/POP Rd --------------------------------------------
for t, name in enumerate(["PUSH", "POP"]):
    for dd, r in enumerate(REGS):
        put(primary, 0x30 | (t << 2) | dd, f"{name} {r}")

# --- $38-$3F : 16-bit pointer quick ops -------------------------------
for i, name in enumerate(["INCW X", "INCW Y", "DECW X", "DECW Y",
                          "PUSHW X", "PUSHW Y", "POPW X", "POPW Y"]):
    put(primary, 0x38 + i, name)

# --- $40-$5F : pointer indirect, with and without displacement --------
for base, disp in ((0x40, False), (0x50, True)):
    for t in (0, 1):
        for dd, r in enumerate(REGS):
            for b, p in enumerate(PTR):
                ea = f"[{p}{{d}}]" if disp else f"[{p}]"
                m = f"LD {r},{ea}" if t == 0 else f"ST {ea},{r}"
                put(primary, base | (t << 3) | (dd << 1) | b,
                    m, DISP8 if disp else NONE)

# --- $60-$6F : stack relative and absolute ----------------------------
for t in (0, 1):
    for dd, r in enumerate(REGS):
        for b in (0, 1):
            ea, kind = ("[SP+{u}]", U8) if b == 0 else ("[{a}]", ABS16)
            m = f"LD {r},{ea}" if t == 0 else f"ST {ea},{r}"
            put(primary, 0x60 | (t << 3) | (dd << 1) | b, m, kind)

# --- $70-$7F : Bcc rel8 -----------------------------------------------
for c, name in enumerate(COND):
    put(primary, 0x70 | c, f"{name} {{t}}", REL8)

# --- $80-$FF : 1 ooo dd ss  ALU Rd,Rs ---------------------------------
for ooo, name in enumerate(ALU):
    for dd, d in enumerate(REGS):
        for ss, s in enumerate(REGS):
            put(primary, 0x80 | (ooo << 4) | (dd << 2) | ss,
                f"{name} {d},{s}")

# ======================================================================
# page 2 ($2F prefix)
# ======================================================================

# $00-$0F  XOR Rd,Rs
for dd, d in enumerate(REGS):
    for ss, s in enumerate(REGS):
        put(page2, (dd << 2) | ss, f"XOR {d},{s}")

# $10-$3B  unary and bit operations, 4 opcodes each.
# The ROL slot is deliberately empty: ROL/SHL already exist as one-byte
# ADC Rd,Rd / ADD Rd,Rd, so a two-byte duplicate would be strictly worse.
# $2C-$2D were later reclaimed for ADDW X|Y,#imm16 (see below).
for i, name in enumerate(["XOR", "NOT", "NEG", "SWAP", "SHR", "SAR",
                          "ROR", None, "BSET", "BCLR", "BTST"]):
    if name is None:
        continue
    for dd, d in enumerate(REGS):
        if name == "XOR":
            put(page2, 0x10 + i * 4 + dd, f"XOR {d},#{{i}}", IMM8)
        elif name in ("BSET", "BCLR", "BTST"):
            put(page2, 0x10 + i * 4 + dd, f"{name} {d},#{{m}}", MASK8)
        else:
            put(page2, 0x10 + i * 4 + dd, f"{name} {d}")

# $2C-$2D  16-bit immediate added to a pointer.
# Found by writing real code: adding a 16-bit constant to X otherwise
# takes six instructions. See docs/01-decisions.md D20.
put(page2, 0x2C, "ADDW X,#{w}", IMM16)
put(page2, 0x2D, "ADDW Y,#{w}", IMM16)

# $40-$5F  pointer half-register moves
for dd, d in enumerate(REGS):
    for pp, p in enumerate(HALVES):
        put(page2, 0x40 | (dd << 2) | pp, f"MOV {d},{p}")
        put(page2, 0x50 | (dd << 2) | pp, f"MOV {p},{d}")

# $60-$6E  16-bit operations
for op, (m, o) in {
    0x60: ("LDW X,#{w}", IMM16),     0x61: ("LDW Y,#{w}", IMM16),
    0x62: ("LDW X,[{a}]", ABS16),    0x63: ("LDW Y,[{a}]", ABS16),
    0x64: ("STW [{a}],X", ABS16),    0x65: ("STW [{a}],Y", ABS16),
    0x66: ("MOVW X,Y", NONE),        0x67: ("MOVW Y,X", NONE),
    0x68: ("MOVW SP,X", NONE),       0x69: ("MOVW SP,Y", NONE),
    0x6A: ("MOVW X,SP", NONE),       0x6B: ("MOVW Y,SP", NONE),
    0x6C: ("ADDW SP,#{d}", DISP8),
    0x6D: ("LEA X,[SP+{u}]", U8),    0x6E: ("LEA Y,[SP+{u}]", U8),
}.items():
    put(page2, op, m, o)

# $70-$7F  16-bit add/sub of an 8-bit register
for i, name in enumerate(["ADDW X", "ADDW Y", "SUBW X", "SUBW Y"]):
    for dd, d in enumerate(REGS):
        put(page2, 0x70 + i * 4 + dd, f"{name},{d}")

# $80-$BF  register-indexed addressing
for i, (m, p) in enumerate([("LD", "X"), ("LD", "Y"),
                            ("ST", "X"), ("ST", "Y")]):
    for dd, d in enumerate(REGS):
        for ss, s in enumerate(REGS):
            ea = f"[{p}+{s}]"
            put(page2, 0x80 + i * 16 + (dd << 2) + ss,
                f"{m} {d},{ea}" if m == "LD" else f"{m} {ea},{d}")

# $C0-$DF  auto-increment and auto-decrement
for base, pre in ((0xC0, False), (0xD0, True)):
    for t in (0, 1):
        for dd, r in enumerate(REGS):
            for b, p in enumerate(PTR):
                ea = f"[-{p}]" if pre else f"[{p}+]"
                put(page2, base | (t << 3) | (dd << 1) | b,
                    f"LD {r},{ea}" if t == 0 else f"ST {ea},{r}")

# $E0-$E2  system
for op, m in {0xE0: "PUSH F", 0xE1: "POP F", 0xE2: "CLV"}.items():
    put(page2, op, m)

# $F0-$FF  multiply, X <- Rd * Rs, unsigned
for dd, d in enumerate(REGS):
    for ss, s in enumerate(REGS):
        put(page2, 0xF0 | (dd << 2) | ss, f"MUL {d},{s}")


# ---------------------------------------------------------------- API

def cycles(op, op2=None):
    """Cycle cost per docs/02-isa.md section 8, FPGA timing (1-cycle
    memory). Returns an int, or (not_taken, taken) for conditional
    branches. The emulator cross-checks its own accounting against this.
    """
    if op == 0x2F:                                    # page 2: escape + op
        if op2 is None or op2 not in page2:
            return 7                                  # reserved -> BRK trap
        if op2 < 0x10:
            return 3                                  # XOR Rd,Rs
        if op2 in (0x2C, 0x2D):
            return 6                                  # ADDW X|Y,#imm16
        if op2 < 0x40:
            g = (op2 - 0x10) >> 2
            return 4 if g in (0, 8, 9, 10) else 3     # imm/bit forms cost 1
        if op2 < 0x60:
            return 3                                  # half-register moves
        if op2 < 0x70:
            return {0x60: 6, 0x61: 6, 0x62: 8, 0x63: 8, 0x64: 8, 0x65: 8,
                    0x66: 3, 0x67: 3, 0x68: 3, 0x69: 3, 0x6A: 3, 0x6B: 3,
                    0x6C: 5, 0x6D: 5, 0x6E: 5}[op2]
        if op2 < 0x80:
            return 4                                  # ADDW/SUBW X|Y,Rd
        if op2 < 0xC0:
            return 5                                  # [X|Y + Rs]
        if op2 < 0xE0:
            return 5                                  # auto inc / dec
        if op2 < 0xE3:
            return 4 if op2 < 0xE2 else 3             # PUSH F/POP F, CLV
        return 13                                     # MUL: escape + 12
    if op < 0x20:
        return 3                                      # ALU Rd,#imm8
    if op < 0x30:
        return {0x20: 2, 0x21: 2, 0x22: 5, 0x23: 6, 0x24: 2, 0x25: 2,
                0x26: 2, 0x27: 2, 0x28: 4, 0x29: 7, 0x2A: 2, 0x2B: 2,
                0x2C: 5, 0x2D: 5, 0x2E: 7}[op]
    if op < 0x38:
        return 3                                      # PUSH/POP Rd
    if op < 0x40:
        return 2 if (op & 7) < 4 else 4               # INCW/DECW vs PUSHW
    if op < 0x50:
        return 3                                      # LD/ST [X|Y]
    if op < 0x70:
        return 5                                      # displaced / absolute
    if op < 0x80:
        return (3, 4)                                 # Bcc not taken, taken
    return 2                                          # ALU Rd,Rs


def length(op, op2=None):
    """Total instruction length in bytes, including any $2F prefix."""
    if op == 0x2F:
        e = page2.get(op2)
        return 2 + (EXTRA[e[1]] if e else 0)
    return 1 + EXTRA[primary[op][1]]


def disassemble(read, addr):
    """Render one instruction. `read(a)` returns the byte at address a.

    Returns (text, length).
    """
    op = read(addr)
    if op == 0x2F:
        op2 = read((addr + 1) & 0xFFFF)
        entry = page2.get(op2)
        if entry is None:
            return f".byte $2F,${op2:02X}   ; reserved -> BRK", 2
        mnem, kind = entry
        pos = addr + 2
    else:
        mnem, kind = primary[op]
        pos = addr + 1

    n = EXTRA[kind]
    lo = read(pos & 0xFFFF) if n >= 1 else 0
    hi = read((pos + 1) & 0xFFFF) if n >= 2 else 0
    total = (pos - addr) + n

    if kind == IMM8 or kind == MASK8:
        text = mnem.replace("{i}", f"${lo:02X}").replace("{m}", f"${lo:02X}")
    elif kind == DISP8:
        s = lo - 256 if lo > 127 else lo
        text = mnem.replace("{d}", f"{s:+d}")
    elif kind == U8:
        text = mnem.replace("{u}", str(lo))
    elif kind == REL8:
        s = lo - 256 if lo > 127 else lo
        text = mnem.replace("{t}", f"${(addr + total + s) & 0xFFFF:04X}")
    elif kind in (ABS16, IMM16):
        v = lo | (hi << 8)
        text = mnem.replace("{a}", f"${v:04X}").replace("{w}", f"${v:04X}")
    else:
        text = mnem
    return text, total


# ---------------------------------------------------------------- check

def check():
    holes = [i for i, e in enumerate(primary) if e is None]
    print(f"primary page : {256 - len(holes)}/256 encodings assigned")
    if holes:
        print("  UNASSIGNED :", " ".join(f"${h:02X}" for h in holes))
    print(f"page 2       : {len(page2)}/256 assigned, "
          f"{256 - len(page2)} reserved")

    # spot-check the worked examples in docs/02-isa.md
    expect = [
        (0x42, "LD R1,[X]"), (0x4B, "ST [Y],R1"),
        (0x38, "INCW X"),    (0x39, "INCW Y"),
        (0x0C, "SUB R0,#{i}"), (0x73, "BNE {t}"),
        (0x50, "LD R0,[X{d}]"), (0x52, "LD R1,[X{d}]"),
        (0x91, "ADD R0,R1"), (0x58, "ST [X{d}],R0"),
        (0x81, "MOV R0,R1"), (0xB5, "SUB R1,R1"),
        (0x68, "ST [SP+{u}],R0"), (0x60, "LD R0,[SP+{u}]"),
        (0x44, "LD R2,[X]"), (0x96, "ADD R1,R2"),
        (0x92, "ADD R0,R2"), (0xA7, "ADC R1,R3"),
        (0x22, "RET"),       (0x72, "BEQ {t}"),
    ]
    bad = [(o, w, primary[o][0]) for o, w in expect if primary[o][0] != w]
    for o, want, got in bad:
        print(f"  MISMATCH ${o:02X}: doc says {want!r}, table says {got!r}")
    print(f"doc examples : {len(expect) - len(bad)}/{len(expect)} match")

    p2 = [(0x38, "BTST R0,#{m}"), (0xF4, "MUL R1,R0"), (0x6C, "ADDW SP,#{d}")]
    p2bad = [(o, w) for o, w in p2 if page2[o][0] != w]
    for o, w in p2bad:
        print(f"  MISMATCH page2 ${o:02X}: expected {w!r}, got {page2[o][0]!r}")
    print(f"page-2 spots : {len(p2) - len(p2bad)}/{len(p2)} match")
    return not holes and not bad and not p2bad


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    for i in range(0, 256, 4):
        print("  ".join(f"${i+j:02X} {primary[i+j][0]:<18}" for j in range(4)))
    print()
    check()
