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
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")
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

; sw/interp.asm is here because sw/asm.asm now calls into it: a label is
; a BASIC variable ([D45](docs/01-decisions.md)), so nlook and nfind are
; the symbol table. That is also how the built system is put together --
; basic.bas includes both -- so the harness is closer to the real thing
; than it was, at the price of the three editor stubs interp.asm wants.
s_putn:   RET
s_newline:RET
s_putsn:  RET
s_findline:
        LDW  X,#prog
        MOV  R0,XL
        MOV  R1,XH
        RET


; INKEY and KEY reach outside the interpreter: the ring belongs to the
; editor and the key-down bitmap to sw/kbd.asm, and neither is here
; when interp.asm is assembled on its own. Stubbed rather than pulled
; in, because this file tests the interpreter and not the keyboard --
; sim/test_run.py drives the real ones on the whole system.
; INPUT and PRINT separators reach the editor's console; standalone,
; a getkey answers Return at once so INPUT terminates, and emit
; swallows the byte -- the caller pops its own arguments.
s_emit: RET
s_getkey:
        MOV  R0,#$0D
        CLR  R1
        RET
s_serialkey:
        CLR  R0
        CLR  R1
        RET
kdbit:  CLR  R0                 ; a zero mask: KEY() is always false
        LDW  X,#kdstub
        RET
kdstub: .byte 0
; The former editor commands are tokens now, and their handlers call
; the editor's compiled cores. Standalone, each core is a RET and the
; shared buffers are bytes -- the same stubs sim/test_interp.py
; carries, because this file tests the assembler and not the editor.
s_parsename:
        CLR  R0
        CLR  R1
        RET
s_list:
s_deleterange:
s_renumber:
s_new:
s_dofree:
s_cls:
s_dodir:
s_docompact:
s_drivecore:
s_eracore:
s_savecore:
s_savedata:
s_loadcore:
s_loaddata:
s_dorun:
        RET
a_lbuf: .space 4
v_llen: .byte 0
v_ip:   .byte 0
v_fok:  .byte 0
v_progend: .word 0
        .include "zp.asm"
        .include "interp.asm"
        .include "toktab.asm"
        .include "asm.asm"
prog:
"""


def run(code, syms, prog, budget=2_000_000):
    m = vm.Machine()
    m.bus.mem[CODE:CODE + len(code)] = code
    at = syms["prog"]
    m.bus.mem[at:at + len(prog)] = bytes(prog)
    # PEND is one past the last record. nextline compares LREC against
    # it, so leaving it at zero makes the program look empty and the
    # assembler emits nothing at all -- silently.
    end = at + len(prog)
    m.bus.mem[0x0016], m.bus.mem[0x0017] = end & 0xFF, end >> 8
    m.cpu.pc, m.cpu.sp, m.romen = CODE, 0x7FF0, False
    m.run(budget=budget)
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


# ---------------------------------------------------------------------
# The gate proper: assemble on the machine, assemble the same text with
# tools/cool8asm.py, and require the bytes to be identical.
#
# `sim/test_emit.py` is the model. No partial credit: the first byte
# that differs is the answer, because an assembler that is nearly right
# is an assembler that writes a program which nearly runs.
# ---------------------------------------------------------------------
ORG = 0x7000                    # where an ASM block's code is laid down

DRIVER = """
        .org $0200
start:  CLR  R0
        ST   [$0018],R0         ; ERR
        ST   [$0029],R0         ; NNAME: no names defined yet
        ST   [$00E0],R0         ; ACH
        ST   [$00E3],R0         ; AKLEN
        MOV  R0,#$00            ; NTAB = $6000, above the program
        ST   [$0027],R0
        MOV  R0,#$60
        ST   [$0028],R0
        MOV  R0,#<$7000         ; ACBASE: where the block is laid down
        ST   [$00DC],R0
        MOV  R0,#>$7000
        ST   [$00DD],R0
        MOV  R0,#<prog
        MOV  R1,#>prog
        CALL aprog
        HALT

s_putn:   RET
s_newline:RET
s_putsn:  RET
s_findline:
        LDW  X,#prog
        MOV  R0,XL
        MOV  R1,XH
        RET


; INKEY and KEY reach outside the interpreter: the ring belongs to the
; editor and the key-down bitmap to sw/kbd.asm, and neither is here
; when interp.asm is assembled on its own. Stubbed rather than pulled
; in, because this file tests the interpreter and not the keyboard --
; sim/test_run.py drives the real ones on the whole system.
; INPUT and PRINT separators reach the editor's console; standalone,
; a getkey answers Return at once so INPUT terminates, and emit
; swallows the byte -- the caller pops its own arguments.
s_emit: RET
s_getkey:
        MOV  R0,#$0D
        CLR  R1
        RET
s_serialkey:
        CLR  R0
        CLR  R1
        RET
kdbit:  CLR  R0                 ; a zero mask: KEY() is always false
        LDW  X,#kdstub
        RET
kdstub: .byte 0
; The former editor commands are tokens now, and their handlers call
; the editor's compiled cores. Standalone, each core is a RET and the
; shared buffers are bytes -- the same stubs sim/test_interp.py
; carries, because this file tests the assembler and not the editor.
s_parsename:
        CLR  R0
        CLR  R1
        RET
s_list:
s_deleterange:
s_renumber:
s_new:
s_dofree:
s_cls:
s_dodir:
s_docompact:
s_drivecore:
s_eracore:
s_savecore:
s_savedata:
s_loadcore:
s_loaddata:
s_dorun:
        RET
a_lbuf: .space 4
v_llen: .byte 0
v_ip:   .byte 0
v_fok:  .byte 0
v_progend: .word 0
        .include "zp.asm"
        .include "interp.asm"
        .include "toktab.asm"
        .include "asm.asm"
prog:
"""


def asmprog(lines):
    """A stored BASIC program that is one ASM block."""
    recs, n = [], 10
    for text in ["ASM"] + list(lines) + ["END ASM"]:
        toks = tokenise(text)
        recs.append([n & 0xFF, n >> 8, len(toks)] + toks + [0])
        n += 10
    return [b for r in recs for b in r]


def reference(lines):
    """The same text through tools/cool8asm.py."""
    path = os.path.join(BUILD, "ta_ref.asm")
    with open(path, "w") as fh:
        fh.write(f"        .org ${ORG:04X}\n" + "\n".join(lines) + "\n")
    out = os.path.join(BUILD, "ta_ref.bin")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), path,
                        "-o", out, "-I", os.path.join(ROOT, "sw")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr).strip()
    with open(out, "rb") as fh:
        return fh.read(), None


def machine(code, syms, lines, budget=2_000_000):
    """The same text through sw/asm.asm. Returns (bytes, ERR)."""
    m = run(code, syms, asmprog(lines), budget)
    end = m.bus.mem[0x00DA] | (m.bus.mem[0x00DB] << 8)     # ACP
    return bytes(m.bus.mem[ORG:end]), m.bus.mem[0x0018]


def hexs(b):
    return " ".join(f"{x:02X}" for x in b)


def identical(code, syms, what, lines):
    want, err = reference(lines)
    if want is None:
        return check(False, what, f"cool8asm.py rejected it: {err}")
    got, e = machine(code, syms, lines)
    if e:
        return check(False, what, f"the machine stopped with ERR={e}")
    return check(got == want, what,
                 f"got    {hexs(got)}\n         wanted {hexs(want)}")


# One line per case, and each is its own program so a failure names the
# encoding rather than an offset into a blob.
ONELINE = [
    "        NOP", "        HALT", "        RET", "        RETI",
    "        EI", "        DI", "        CLC", "        SEC",
    "        BRK", "        CLV",
    "        MOV  R0,R1", "        MOV  R3,#$7F", "        ADD  R2,R2",
    "        ADC  R1,#1", "        SUB  R0,R3", "        SBC  R2,#$10",
    "        AND  R1,R2", "        OR   R0,#$0F", "        CMP  R3,R0",
    "        XOR  R2,R3", "        XOR  R1,#$AA",
    "        CLR  R2", "        TST  R3", "        SHL  R1",
    "        ROL  R0", "        INC  R3", "        DEC  R0",
    "        NOT  R1", "        NEG  R2", "        SWAP R3",
    "        SHR  R0", "        SAR  R1", "        ROR  R2",
    "        BSET R0,#1", "        BCLR R1,#2", "        BTST R2,#$80",
    "        PUSH R0", "        POP  R3", "        MUL  R1,R2",
    "        MOV  R0,XL", "        MOV  R1,YH", "        MOV  XH,R2",
    "        MOV  YL,R3",
    "        LD   R0,[X]", "        LD   R1,[Y]", "        ST   [X],R2",
    "        ST   [Y],R3",
    "        LD   R0,[X+5]", "        LD   R1,[Y-3]",
    "        ST   [X+$10],R2", "        ST   [Y+1],R3",
    "        LD   R2,[SP+4]", "        ST   [SP+8],R1",
    "        LD   R0,[$FE70]", "        ST   [$8000],R3",
    "        LD   R1,[X+R2]", "        ST   [Y+R0],R3",
    "        LD   R0,[X+]", "        ST   [Y+],R1",
    "        LD   R2,[-X]", "        ST   [-Y],R0",
    "        LDW  X,#$1234", "        LDW  Y,#$8000",
    "        LDW  X,[$0200]", "        LDW  Y,[$0202]",
    "        STW  [$0204],X", "        STW  [$0206],Y",
    "        MOVW X,Y", "        MOVW Y,X", "        MOVW SP,X",
    "        MOVW SP,Y", "        MOVW X,SP", "        MOVW Y,SP",
    "        ADDW SP,#8", "        ADDW SP,#-8",
    "        LEA  X,[SP+2]", "        LEA  Y,[SP+9]",
    "        ADDW X,#$100", "        ADDW Y,#4",
    "        ADDW X,R1", "        ADDW Y,R3",
    "        SUBW X,R0", "        SUBW Y,R2",
    "        INCW X", "        DECW Y", "        PUSHW X", "        POPW Y",
    "        JMP  [X]", "        JMP  [Y]", "        CALL [X]",
    "        CALL [Y]",
    "        .byte 1,2,3", "        .db $FF,$00",
    "        .word $1234,$5678", "        .dw 1,2",
]

# Cases that need more than one line: labels, branches, both passes.
MULTI = [
    ("a backward branch",
     ["loop:   ADD  R1,R0", "        BNE  loop"]),
    ("a forward branch, which is what pass 1 is for",
     ["        BEQ  done", "        NOP", "done:   HALT"]),
    ("JMP and CALL to a label",
     ["start1: NOP", "        JMP  start1", "        CALL start1"]),
    ("label arithmetic, which chaining could not do",
     ["base1:  .word 0", "        LDW  X,#base1+2", "        LD R0,[base1+1]"]),
    ("'*' is where we are",
     ["        LDW  X,#*", "        NOP", "        LDW  Y,#*"]),
    ("byte select, as sim/test_interp.py's own driver uses it",
     ["targ1:  .word 0", "        MOV  R0,#<targ1", "        MOV  R1,#>targ1"]),
    # The collisions the untokeniser exists for. Every one of these is a
    # TOKTAB word, so the editor stored a token byte and agetc had to
    # give the letters back.
    ("a label spelled LOOP, which the tokeniser destroyed",
     ["loop:   NOP", "        BRA  loop"]),
    ("a label spelled NEXT",
     ["next:   NOP", "        JMP  next"]),
    ("a label spelled END",
     ["end:    NOP", "        CALL end"]),
    ("SUB, AND, OR and XOR as mnemonics",
     ["        SUB  R0,#1", "        AND  R1,R0", "        OR   R2,R3",
      "        XOR  R0,R1"]),
    ("CALL, which is a keyword byte too",
     ["there:  NOP", "        CALL there"]),
    # cool8asm.py scopes a local label to the enclosing global one; the
    # machine's namespace is flat, because qualifying costs ~40 bytes
    # and gated sources use unique local names anyway. Both resolve
    # consistently inside their own world, so the bytes agree -- but
    # the reference needs the global label to exist at all.
    ("a local label keeps its dot",
     ["outer1: BRA  .skip", "        NOP", ".skip:  HALT"]),
    ("six significant characters keep .done1 and .done2 apart",
     ["outer2: BEQ  .done1", "        BNE  .done2", ".done1: NOP",
      ".done2: HALT"]),
    ("both spellings of a literal reach the same $A4",
     ["        MOV  R2,#255", "        MOV  R3,#$FF"]),
    ("a comment is not code",
     ["        NOP             ; this is ignored", "        HALT"]),
    ("an ASM block can be more than a few lines",
     ["        LDW  X,#$8000", "        MOV  R0,#$41", "fill1:  ST   [X+],R0",
      "        MOV  R1,XH", "        CMP  R1,#$A0", "        BNE  fill1",
      "        RET"]),
]

# Things that must be refused rather than assembled to something wrong.
NEGATIVE = [
    ("an undefined symbol", ["        JMP  nowhere"]),
    ("an immediate that does not fit a byte", ["        MOV  R0,#$1234"]),
    ("a branch beyond +127", ["        BRA  far"] + ["        NOP"] * 130
     + ["far:    HALT"]),
    ("a mnemonic that does not exist", ["        FROB R0,R1"]),
    ("an operand shape with no encoding", ["        MOV  [X],R0"]),
    (".org, which a block does not get to choose", ["        .org $200"]),
    (".macro, which is several hundred bytes of nothing",
     ["        .macro foo", "        NOP", "        .endm"]),
]


# ---------------------------------------------------------------------
# Every encoding, not a sample of them.
#
# A hand-written case list proves the cases someone thought of. This
# walks `cool8asm.TABLE` -- itself built by disassembling all 491
# encodings -- and requires each one to be either assembled identically
# or named in `mkasmtab.CUT`. An encoding added to opcodes.py that is
# neither implemented nor deliberately cut fails here.
# ---------------------------------------------------------------------
def concrete(form):
    """A canonical operand form as something a person could type."""
    return {"#N": "#1", "[N]": "[$1234]", "N": "*",
            "[X+N]": "[X+1]", "[Y+N]": "[Y+1]",
            "[SP+N]": "[SP+1]"}.get(form, form)


def signatures():
    import cool8asm as A
    import mkasmtab as M
    out = []
    for sig in sorted(A.TABLE):
        if sig in M.CUT:
            continue
        mnem, ops = sig
        text = "        " + mnem
        if ops:
            text += " " * (6 - len(mnem)) + ",".join(concrete(o) for o in ops)
        out.append(text)
    return out, len(A.TABLE), len(M.CUT)


def table_walk(code, syms):
    import opcodes
    lines, total, cut = signatures()
    want, err = reference(lines)
    if want is None:
        return check(False, "every signature in cool8asm.TABLE",
                     f"cool8asm.py rejected its own table: {err}")
    got, e = machine(code, syms, lines, budget=60_000_000)
    if e:
        return check(False, "every signature in cool8asm.TABLE",
                     f"the machine stopped with ERR={e} after "
                     f"{len(got)} of {len(want)} bytes")
    if got == want:
        return check(True, f"all {len(lines)} signatures, {total} encodings "
                           f"less {cut} cut")
    # Name the instruction rather than the offset: segment the reference
    # by its own instruction lengths, the way sim/dbg.py's diff does.
    at, i = 0, 0
    while i < len(want) and i < len(got):
        op = want[i]
        op2 = want[i + 1] if op == 0x2F and i + 1 < len(want) else None
        n = opcodes.length(op, op2)
        if got[i:i + n] != want[i:i + n]:
            return check(False, "every signature in cool8asm.TABLE",
                         f"{lines[at].strip()}\n"
                         f"         got    {hexs(got[i:i + n])}\n"
                         f"         wanted {hexs(want[i:i + n])}")
        i += n
        at += 1
    return check(False, "every signature in cool8asm.TABLE",
                 f"lengths differ: {len(got)} against {len(want)}")


def main():
    print("  I3 -- sw/asm.asm, the assembler on the machine")
    print()
    code, syms = T.build("asm", HARNESS)
    print(f"  untokeniser and scanner: "
          f"{syms['prog'] - syms['agetc']:,} bytes")
    print()
    for src, want in CASES:
        m = run(code, syms, block(src))
        got = untokenised(m)
        check(got == want, f"agetc: {src.strip()[:38]}",
              f"got {got!r}\n         wanted {want!r}")

    print()
    print("  byte-identical to tools/cool8asm.py")
    print()
    dcode, dsyms = T.build("asmdrv", DRIVER)
    print(f"  sw/asm.asm: {dsyms['prog'] - dsyms['agetc']:,} bytes"
          f" of code, {dsyms['agetc'] - dsyms['amtab']:,} of table")
    print()
    for src in ONELINE:
        identical(dcode, dsyms, src.strip(), [src])
    print()
    for what, lines in MULTI:
        identical(dcode, dsyms, what, lines)

    print()
    print("  refused, rather than assembled to something wrong")
    print()
    for what, lines in NEGATIVE:
        got, e = machine(dcode, dsyms, lines)
        check(e != 0, what, f"ERR was 0 and it emitted {hexs(got)}")

    print()
    print("  the whole instruction set, walked")
    print()
    table_walk(dcode, dsyms)

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
