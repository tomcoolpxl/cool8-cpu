#!/usr/bin/env python3
"""COOL8 opcode table — the single source of truth for the encoding.

Expands the encoding rules in docs/02-isa.md into a flat 256-entry
primary table and a sparse page-2 table, and self-checks that the
primary page is exactly covered with no collisions and no gaps.

The assembler, disassembler and reference emulator all import this
rather than each carrying their own copy of the map.

Run directly to print the table and the coverage check:
    python tools/opcodes.py
    python tools/opcodes.py --check
"""

import sys

REGS = ["R0", "R1", "R2", "R3"]
ALU = ["MOV", "ADD", "ADC", "SUB", "SBC", "AND", "OR", "CMP"]
COND = ["BRA", "BNV", "BEQ", "BNE", "BCS", "BCC", "BMI", "BPL",
        "BVS", "BVC", "BHI", "BLS", "BGE", "BLT", "BGT", "BLE"]

# operand kinds, and how many bytes follow the opcode
NONE, IMM8, DISP8, REL8, ABS16, IMM16 = range(6)
EXTRA = {NONE: 0, IMM8: 1, DISP8: 1, REL8: 1, ABS16: 2, IMM16: 2}

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
        put(primary, (ooo << 2) | dd, f"{name} {r},#", IMM8)

# --- $20-$2F : control and flow ---------------------------------------
for op, (m, o) in {
    0x20: ("NOP", NONE),      0x21: ("HALT", NONE),
    0x22: ("RET", NONE),      0x23: ("RETI", NONE),
    0x24: ("EI", NONE),       0x25: ("DI", NONE),
    0x26: ("CLC", NONE),      0x27: ("SEC", NONE),
    0x28: ("JMP ", ABS16),    0x29: ("CALL ", ABS16),
    0x2A: ("JMP [X]", NONE),  0x2B: ("JMP [Y]", NONE),
    0x2C: ("CALL [X]", NONE), 0x2D: ("CALL [Y]", NONE),
    0x2E: ("BRK", NONE),      0x2F: ("<page2>", NONE),
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
            for b, p in enumerate(["X", "Y"]):
                ea = f"[{p}+d]" if disp else f"[{p}]"
                m = f"LD {r},{ea}" if t == 0 else f"ST {ea},{r}"
                put(primary, base | (t << 3) | (dd << 1) | b,
                    m, DISP8 if disp else NONE)

# --- $60-$6F : stack relative and absolute ----------------------------
for t in (0, 1):
    for dd, r in enumerate(REGS):
        for b in (0, 1):
            ea, kind = ("[SP+u]", DISP8) if b == 0 else ("[a16]", ABS16)
            m = f"LD {r},{ea}" if t == 0 else f"ST {ea},{r}"
            put(primary, 0x60 | (t << 3) | (dd << 1) | b, m, kind)

# --- $70-$7F : Bcc rel8 -----------------------------------------------
for c, name in enumerate(COND):
    put(primary, 0x70 | c, f"{name} ", REL8)

# --- $80-$FF : 1 ooo dd ss  ALU Rd,Rs ---------------------------------
for ooo, name in enumerate(ALU):
    for dd, d in enumerate(REGS):
        for ss, s in enumerate(REGS):
            put(primary, 0x80 | (ooo << 4) | (dd << 2) | ss,
                f"{name} {d},{s}")

# --- page 2 ($2F prefix) ----------------------------------------------
for dd, d in enumerate(REGS):
    for ss, s in enumerate(REGS):
        put(page2, (dd << 2) | ss, f"XOR {d},{s}")
for i, name in enumerate(["XOR", "NOT", "NEG", "SWAP", "SHR", "SAR",
                          "ROR", "ROL", "BSET", "BCLR", "BTST"]):
    for dd, d in enumerate(REGS):
        imm = IMM8 if name in ("XOR", "BSET", "BCLR", "BTST") else NONE
        sep = ",#" if imm else ""
        put(page2, 0x10 + i * 4 + dd, f"{name} {d}{sep}", imm)
for dd, d in enumerate(REGS):
    for pp, p in enumerate(["XL", "XH", "YL", "YH"]):
        put(page2, 0x40 | (dd << 2) | pp, f"MOV {d},{p}")
        put(page2, 0x50 | (dd << 2) | pp, f"MOV {p},{d}")
for op, (m, o) in {
    0x60: ("LDW X,#", IMM16),   0x61: ("LDW Y,#", IMM16),
    0x62: ("LDW X,", ABS16),    0x63: ("LDW Y,", ABS16),
    0x64: ("STW ,X", ABS16),    0x65: ("STW ,Y", ABS16),
    0x66: ("MOVW X,Y", NONE),   0x67: ("MOVW Y,X", NONE),
    0x68: ("MOVW SP,X", NONE),  0x69: ("MOVW SP,Y", NONE),
    0x6A: ("MOVW X,SP", NONE),  0x6B: ("MOVW Y,SP", NONE),
    0x6C: ("ADDW SP,#", IMM8),  0x6D: ("LEA X,[SP+u]", DISP8),
    0x6E: ("LEA Y,[SP+u]", DISP8),
}.items():
    put(page2, op, m, o)
for i, name in enumerate(["ADDW X", "ADDW Y", "SUBW X", "SUBW Y"]):
    for dd, d in enumerate(REGS):
        put(page2, 0x70 + i * 4 + dd, f"{name},{d}")
for i, (m, p) in enumerate([("LD", "X"), ("LD", "Y"),
                            ("ST", "X"), ("ST", "Y")]):
    for dd, d in enumerate(REGS):
        for ss, s in enumerate(REGS):
            ea = f"[{p}+{s}]"
            put(page2, 0x80 + i * 16 + (dd << 2) + ss,
                f"{m} {d},{ea}" if m == "LD" else f"{m} {ea},{d}")
for base, form in ((0xC0, "+"), (0xD0, "-")):
    for t in (0, 1):
        for dd, r in enumerate(REGS):
            for b, p in enumerate(["X", "Y"]):
                ea = f"[{p}+]" if form == "+" else f"[-{p}]"
                put(page2, base | (t << 3) | (dd << 1) | b,
                    f"LD {r},{ea}" if t == 0 else f"ST {ea},{r}")
for op, m in {0xE0: "PUSH F", 0xE1: "POP F", 0xE2: "CLV"}.items():
    put(page2, op, m)


def length(op, op2=None):
    """Total instruction length in bytes."""
    if op == 0x2F:
        return 2 + EXTRA[page2[op2][1]]
    return 1 + EXTRA[primary[op][1]]


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
        (0x0C, "SUB R0,#"),  (0x73, "BNE "),
        (0x50, "LD R0,[X+d]"), (0x52, "LD R1,[X+d]"),
        (0x91, "ADD R0,R1"), (0x58, "ST [X+d],R0"),
        (0x81, "MOV R0,R1"), (0xB5, "SUB R1,R1"),
        (0x68, "ST [SP+u],R0"), (0x60, "LD R0,[SP+u]"),
        (0x44, "LD R2,[X]"), (0x96, "ADD R1,R2"),
        (0x92, "ADD R0,R2"), (0xA7, "ADC R1,R3"),
        (0x22, "RET"),       (0x72, "BEQ "),
    ]
    bad = [(o, w, primary[o][0]) for o, w in expect if primary[o][0] != w]
    for o, want, got in bad:
        print(f"  MISMATCH ${o:02X}: doc says {want!r}, table says {got!r}")
    print(f"doc examples : {len(expect) - len(bad)}/{len(expect)} match")
    return not holes and not bad


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    for i in range(0, 256, 4):
        print("  ".join(f"${i+j:02X} {primary[i+j][0]:<14}" for j in range(4)))
    print()
    check()
