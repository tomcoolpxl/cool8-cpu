#!/usr/bin/env python3
"""sw/asm.asm -- COOL8 assembly, assembled on the machine.

    python sim/test_asm.py

The gate is byte-identity with `tools/cool8asm.py` for the same source,
the same shape as `sim/test_emit.py`. Before that can mean anything the
front end has to be right, because the editor tokenises the inside of an
`ASM` block: `SUB` arrives as $81, `AND` as $99, a label spelled `LOOP`
as $89, `.byte` as '.' followed by $96, and every number as $A4 and two
binary bytes.

`agetc` undoes all of that. This checks it does, by comparing the
characters it hands back against the text that was tokenised -- which is
the only way to know the assembler is reading the program the user
typed rather than a plausible-looking corruption of it.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

import cool8vm as vm                                      # noqa: E402
import test_interp as T                                   # noqa: E402

CODE = 0x0200
OUT = 0x7000
FAILS = []

# Page 0, mirroring sw/asm.asm.
ACH, AKLEN, AVAL = 0x00E0, 0x00E3, 0x00E5


def check(ok, what, detail=""):
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


# ---------------------------------------------------------------------
# The tokeniser, as sw/basic.bas implements it.
#
# This is a model and models drift, which is why it is only used to
# *build* input here and never to decide whether the machine is right.
# The keyword list is read out of sw/toktab.asm rather than restated, so
# the one thing that could drift silently cannot.
# ---------------------------------------------------------------------
def toktab():
    text = open(os.path.join(ROOT, "sw", "toktab.asm"),
                encoding="utf-8").read()
    body = text.split("TOKTAB:", 1)[1]
    words, tok = {}, 0x80
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith(".byte"):
            continue
        parts = [p.strip() for p in line[5:].split(",")]
        if parts[0] == "0":
            break
        words["".join(p.strip('"') for p in parts[1:])] = tok
        tok += 1
    return words


WORDS = toktab()


def tokenise(text):
    """Text -> the bytes sw/basic.bas would store for it."""
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c.isalpha() or c == "_":
            j = i
            while j < len(text) and (text[j].isalnum() or text[j] == "_"):
                j += 1
            word = text[i:j].upper()
            if word in WORDS:
                out.append(WORDS[word])
            else:
                out += [ord(ch) for ch in text[i:j]]
            i = j
        elif c.isdigit():
            j = i
            while j < len(text) and text[j].isdigit():
                j += 1
            out += T.num(int(text[i:j]))
            i = j
        elif c == "$":
            j = i + 1
            while j < len(text) and text[j] in "0123456789abcdefABCDEF":
                j += 1
            out += T.num(int(text[i + 1:j] or "0", 16))
            i = j
        else:
            out.append(ord(c))
            i += 1
    return out


def block(*lines):
    """A stored program of one ASM line per source line."""
    recs = []
    for n, text in enumerate(lines):
        toks = tokenise(text)
        recs.append([(10 + n * 10) & 0xFF, (10 + n * 10) >> 8, len(toks)]
                    + toks + [0])
    return [b for r in recs for b in r]


HARNESS = """
        .org $0200
start:  CLR  R0
        ST   [$00E3],R0         ; AKLEN: no expansion in progress
        ST   [$00E0],R0         ; ACH:   nothing pushed back
        MOV  R0,#<(prog+3)      ; past lineno and len
        MOV  YL,R0
        MOV  R0,#>(prog+3)
        MOV  YH,R0
        LDW  X,#$7000
.lp:    PUSHW X
        CALL agetc
        POPW X
        ST   [X],R0
        INCW X
        CMP  R0,#0
        BEQ  .done
        CMP  R0,#1              ; a number: record its value too
        BNE  .lp
        LD   R0,[$00E5]
        ST   [X],R0
        INCW X
        LD   R0,[$00E6]
        ST   [X],R0
        INCW X
        BRA  .lp
.done:  HALT

        .include "zp.asm"
        .include "toktab.asm"
        .include "asm.asm"
prog:
"""


def run(code, syms, prog, budget=2_000_000):
    m = vm.Machine()
    m.bus.mem[CODE:CODE + len(code)] = code
    at = syms["prog"]
    m.bus.mem[at:at + len(prog)] = bytes(prog)
    m.cpu.pc, m.cpu.sp, m.romen = CODE, 0x7FF0, False
    last = -1
    for _ in range(budget):
        if m.cpu.pc == last:
            break
        last = m.cpu.pc
        m.cpu.step()
    return m


def untokenised(m):
    """Read back what agetc handed out, as text."""
    out, i = [], OUT
    while True:
        c = m.bus.mem[i]
        i += 1
        if c == 0:
            return "".join(out)
        if c == 1:
            v = m.bus.mem[i] | (m.bus.mem[i + 1] << 8)
            i += 2
            out.append(f"<{v}>")
        else:
            out.append(chr(c))


# Each case is the source line, and what agetc should hand back. A
# number comes back as one marker, so it is written <value> -- which is
# the point: the assembler never parses a digit.
CASES = [
    ("        NOP", "        NOP"),
    # the five collisions named in the plan, and they are not the only
    # ones -- every TOKTAB word is a keyword byte wherever it appears
    ("        SUB  R0,#1", "        SUB  R0,#<1>"),
    ("        AND  R1,R0", "        AND  R1,R0"),
    ("        OR   R0,R1", "        OR   R0,R1"),
    ("        XOR  R2,R3", "        XOR  R2,R3"),
    ("        CALL putc", "        CALL putc"),
    # a label spelled like a keyword: destroyed by the tokeniser, and
    # only recoverable because this works in characters
    ("loop:   ADD  R1,R0", "LOOP:   ADD  R1,R0"),
    ("next:   INCW X", "NEXT:   INCW X"),
    ("end:    HALT", "END:    HALT"),
    # .byte arrives as '.' and the BYTE token, and is unreachable
    # without the untokeniser
    ("        .byte 5", "        .BYTE <5>"),
    # hex and decimal are the same $A4 by the time we see them
    ("        MOV  R3,#$FF", "        MOV  R3,#<255>"),
    ("        MOV  R2,#255", "        MOV  R2,#<255>"),
    # a local label keeps its dot
    ("        BRA  .skip", "        BRA  .skip"),
    # a 16-bit literal, and an operand that is a whole expression
    ("        LD   R0,[$FE70]", "        LD   R0,[<65136>]"),
]


def main():
    print("  I3 -- sw/asm.asm, the assembler on the machine")
    print()
    code, syms = T.build("asm", HARNESS)
    print(f"  front end so far: {syms['prog'] - syms['agetc']:,} bytes")
    print()
    for src, want in CASES:
        m = run(code, syms, block(src))
        got = untokenised(m)
        check(got == want, f"agetc: {src.strip()[:38]}",
              f"got {got!r}\n         wanted {want!r}")
    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
