#!/usr/bin/env python3
"""I2 -- the interpreter, executing the editor's own stored programs.

    python sim/test_interp.py

`sw/interp.asm` walks the form the editor writes -- `lineno | len |
tokens` -- with the editor's own token bytes. Each case here is built
the way `sw/basic.bas` would store it, run, and checked against the
answer a person would expect.

I1 got this wrong in a way worth recording: it invented a private token
space where `$80` meant LET, and `$80` is `PRINT` in the editor's
`TOKTAB`. It worked only because the test poked its own bytes into
memory and never met a real program.

Numeric literals are stored as token `$A4` and two binary bytes rather
than as ASCII digits. The editor's tokeniser does not do that yet -- I2
adds it -- but the interpreter is written against it, because otherwise
every iteration of a loop re-parses decimal.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import cool8rsvm as vm                                   # noqa: E402
import cool8rsvm                                         # noqa: E402

ROOT, BUILD = H.ROOT, H.BUILD

CODE = 0x0200
PROG = 0x3000
from memmap import VARS                                    # noqa: E402
FAILS = H.FAILS

# The tokens, read out of sw/toktab.asm rather than listed here.
#
# **This was a hand-written 37-word string, in a table of seventy** --
# the numbering copied into a third place, and already wrong: it said
# `ASM` at $9E, which has been `SYS` since [D63] removed the on-machine
# assembler. Positionally the values still lined up, so nothing failed
# and nobody noticed, which is what a private copy of a generated table
# buys you ([D68]).
import vocab                                             # noqa: E402

K = {n: t for t, n in vocab.keywords()}
K["NUM"] = K.pop("?")


def num(v):
    return [K["NUM"], v & 0xFF, (v >> 8) & 0xFF]


def name(s):
    return [ord(c) for c in s]


def line(n, *parts):
    """One stored record: lineno, len, tokens."""
    toks = []
    for p in parts:
        toks += p if isinstance(p, list) else [ord(p)] if isinstance(p, str) \
            and len(p) == 1 else name(p)
    return [n & 0xFF, n >> 8, len(toks)] + toks + [0]


SP = [0x20]

# `spaced` writes the same record the *editor* would. Every case above
# packs its tokens edge to edge, which no typed line ever is:
# sw/basic.bas:1536-1541 drops one space after the line number and
# tokenise() copies the rest verbatim, so `10 A = 7` is stored as
# A ' ' = ' ' $A4 07 00. Before skipsp that assigned VARS+190 = $00FE and
# said nothing.


def spaced(n, *parts):
    """One record with a space between every token, as typed."""
    out = []
    for p in parts:
        out += [p, SP]
    return line(n, *out[:-1])


def program(*lines):
    out = []
    for ln in lines:
        out += ln
    return out


def build(name_, text):
    return H.assemble_text(text, f"ti_{name_}")


# The interpreter needs three of the editor's routines. In the real
# system they are basic.bas's; here they are stubs that record what was
# asked for, so PRINT can be checked without a screen.
HARNESS = """
        .org $0200
        MOV  R0,#<prog
        ST   [$0014],R0
        MOV  R0,#>prog
        ST   [$0015],R0
        ; $0016 (PEND) is written by the harness before the run.
        ; NTAB and HEAP are the caller's job, the same way: the name
        ; table goes above the program and the heap comes down from
        ; MEMTOP. Fixed addresses here, as sim/test_emit.py does.
        MOV  R0,#$00
        ST   [$0027],R0         ; NTAB = $6000
        MOV  R0,#$60
        ST   [$0028],R0
        ; HEAP = $7F00, not MEMTOP. On the machine the stack is page 1
        ; (sw/boot.asm sets SP to $0200) so the heap may come all the way
        ; down from $7FFF; this harness runs the deep stack at $7FF0 that
        ; docs/10-debugging.md prescribes, and an array allocated at the
        ; top zeroed straight over it. That is the harness-against-machine
        ; mismatch the stored-form contract already names.
        MOV  R0,#$00
        ST   [$002A],R0
        MOV  R0,#$7F
        ST   [$002B],R0
        MOV  R0,#$00            ; SACC = $5F00, below the name table
        ST   [$0033],R0
        MOV  R0,#$5F
        ST   [$0034],R0
        MOV  R0,#$00            ; CSTK = $5E00, the CALL stack
        ST   [$003C],R0
        MOV  R0,#$5E
        ST   [$003D],R0
        CALL irun
        HALT

; ---- stubs standing in for sw/basic.bas
s_putn: LD   R0,[SP+2]          ; remember the last number printed
        ST   [printed],R0
        LD   R0,[SP+3]
        ST   [printed+1],R0
        LD   R0,[nprint]
        ADD  R0,#1
        ST   [nprint],R0
        RET
s_newline:
        RET
; A heap string is length-counted, so this is puts' sibling: address
; then length. It records what was printed so a case can assert on it
; without a screen, the same way s_putn does.
s_putsn:
        LD   R0,[SP+2]
        MOV  XL,R0
        LD   R0,[SP+3]
        MOV  XH,R0
        LD   R1,[SP+4]
        ST   [printlen],R1
        LDW  Y,#printed
        TST  R1
        BEQ  .pd
.pc:    LD   R0,[X]
        INCW X
        ST   [Y+],R0
        SUB  R1,#1
        BNE  .pc
.pd:    RET
s_findline:
        LDW  X,#prog
.fl:    LD   R0,[X]             ; this record's line number
        INCW X
        LD   R1,[X]
        INCW X
        LD   R2,[SP+2]
        LD   R3,[SP+3]
        SUB  R0,R2
        SBC  R1,R3
        OR   R0,R1
        BEQ  .hit
        LD   R0,[X]             ; skip its tokens and the zero
        INCW X
        ADDW X,R0
        INCW X
        BRA  .fl
.hit:   DECW X
        DECW X
        MOV  R0,XL
        MOV  R1,XH
        RET

printed:  .space 40
printlen: .byte 0
nprint:   .byte 0

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
; shared buffers are bytes: this file tests the interpreter, and
; sim/test_basic.py drives the real ones on the whole system.
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
; Floating point is part of the interpreter now ([D63]): `erel` calls
; fsav/fpair on every + - * /, and h_print calls fprint. interp.asm no
; longer assembles without them.
        .include "fp.asm"
        .include "fpbas.asm"
prog:
"""


CASES = [
    ("A = 7",
     program(line(10, name("A"), "=", num(7)), line(20, [K["END"]])),
     {0: 7}),

    ("A = 2 + 3 * 4",
     program(line(10, name("A"), "=", num(2), "+", num(3), "*", num(4)),
             line(20, [K["END"]])),
     {0: 14}),

    ("A = (2 + 3) * 4",
     program(line(10, name("A"), "=", "(", num(2), "+", num(3), ")", "*",
                  num(4)),
             line(20, [K["END"]])),
     {0: 20}),

    ("A = 0 - 5 + 100",
     program(line(10, name("A"), "=", "-", num(5), "+", num(100)),
             line(20, [K["END"]])),
     {0: 95}),

    ("K = 3 : A = K * K",
     program(line(10, name("K"), "=", num(3)),
             line(20, name("A"), "=", name("K"), "*", name("K")),
             line(30, [K["END"]])),
     {0: 9, 10: 3}),

    ("IF 1 = 1 THEN A = 5",
     program(line(10, [K["IF"]], num(1), "=", num(1), [K["THEN"]],
                  name("A"), "=", num(5)),
             line(20, [K["END"]])),
     {0: 5}),

    ("IF 1 = 2 THEN A = 5  (not taken)",
     program(line(10, name("A"), "=", num(9)),
             line(20, [K["IF"]], num(1), "=", num(2), [K["THEN"]],
                  name("A"), "=", num(5)),
             line(30, [K["END"]])),
     {0: 9}),

    ("A < B comparisons",
     program(line(10, name("A"), "=", num(3), "<", num(9)),
             line(20, name("B"), "=", num(9), "<", num(3)),
             line(30, name("C"), "=", num(4), ">=", num(4)),
             line(40, [K["END"]])),
     {0: 0xFFFF, 1: 0, 2: 0xFFFF}),

    ("FOR K = 1 TO 10: NEXT K",
     program(line(10, [K["FOR"]], name("K"), "=", num(1), [K["TO"]],
                  num(10)),
             line(20, [K["NEXT"]], name("K")),
             line(30, [K["END"]])),
     {10: 11}),

    ("FOR K = 1 TO 5: S = S + K: NEXT",
     program(line(10, [K["FOR"]], name("K"), "=", num(1), [K["TO"]],
                  num(5)),
             line(20, name("S"), "=", name("S"), "+", name("K")),
             line(30, [K["NEXT"]]),
             line(40, [K["END"]])),
     {18: 15, 10: 6}),

    ("POKE and PEEK",
     program(line(10, [K["POKE"]], num(0x2000), ",", num(65)),
             line(20, name("A"), "=", [K["PEEK"]], "(", num(0x2000), ")"),
             line(30, [K["END"]])),
     {0: 65}),

    # Nesting. Before FOR had a stack this did not fail -- it silently
    # ran the wrong program, because the inner loop overwrote the outer
    # one's variable, limit, body and line, and the outer NEXT then
    # counted I toward J's limit. S is the one that shows it: 3 x 4
    # additions of 1.
    ("nested FOR: 3 x 4 iterations",
     program(line(10, [K["FOR"]], name("I"), "=", num(1), [K["TO"]],
                  num(3)),
             line(20, [K["FOR"]], name("J"), "=", num(1), [K["TO"]],
                  num(4)),
             line(30, name("S"), "=", name("S"), "+", num(1)),
             line(40, [K["NEXT"]], name("J")),
             line(50, [K["NEXT"]], name("I")),
             line(60, [K["END"]])),
     {18: 12, 8: 4, 9: 5}),

    # Three deep, and the innermost body runs 2 x 3 x 4 times.
    ("three levels of FOR",
     program(line(10, [K["FOR"]], name("I"), "=", num(1), [K["TO"]],
                  num(2)),
             line(20, [K["FOR"]], name("J"), "=", num(1), [K["TO"]],
                  num(3)),
             line(30, [K["FOR"]], name("L"), "=", num(1), [K["TO"]],
                  num(4)),
             line(40, name("S"), "=", name("S"), "+", num(1)),
             line(50, [K["NEXT"]], name("L")),
             line(60, [K["NEXT"]], name("J")),
             line(70, [K["NEXT"]], name("I")),
             line(80, [K["END"]])),
     {18: 24}),

    # The outer variable is still the outer variable after the inner
    # loop has been and gone -- the cache really is restored, not just
    # left holding whatever the inner loop finished with. A is read
    # inside the loop and so is 5; I is read after NEXT has incremented
    # past the limit and so is 6, the same way K ends 11 above.
    ("the outer variable survives the inner loop",
     program(line(10, [K["FOR"]], name("I"), "=", num(5), [K["TO"]],
                  num(5)),
             line(20, [K["FOR"]], name("J"), "=", num(1), [K["TO"]],
                  num(9)),
             line(30, [K["NEXT"]], name("J")),
             line(40, name("A"), "=", name("I")),
             line(50, [K["NEXT"]], name("I")),
             line(60, [K["END"]])),
     {0: 5, 8: 6}),

    # ---- the same statements, written the way the editor stores them.
    #
    # Every case above is packed edge to edge and no typed line is. The
    # interpreter read a space as a variable index, so `A = 7` assigned
    # $00FE -- ASYMS, the assembler's symbol table pointer -- and left
    # ERR at zero. Spaces are kept in the stored form on purpose: it is
    # what makes LIST give back the indentation that was typed, and it
    # is BBC BASIC's arrangement and 6502 Microsoft BASIC's alike.
    ("spaced: A = 7",
     program(spaced(10, name("A"), "=", num(7)),
             line(20, [K["END"]])),
     {0: 7}),

    ("spaced: A = 2 + 3 * 4, precedence intact",
     program(spaced(10, name("A"), "=", num(2), "+", num(3), "*", num(4)),
             line(20, [K["END"]])),
     {0: 14}),

    ("spaced: IF 1 < 2 THEN A = 5",
     program(spaced(10, [K["IF"]], num(1), "<", num(2), [K["THEN"]],
                    name("A"), "=", num(5)),
             line(20, [K["END"]])),
     {0: 5}),

    # POKE's comma and PEEK's parentheses each had a blind INCW Y.
    ("spaced: POKE $2000,65 : A = PEEK($2000)",
     program(spaced(10, [K["POKE"]], num(0x2000), ",", num(65)),
             spaced(20, name("A"), "=", [K["PEEK"]], "(", num(0x2000), ")"),
             line(30, [K["END"]])),
     {0: 65}),

    # A false IF has to step over the literal in the arm it is skipping.
    # $A4 carries two binary bytes and the high byte of anything under
    # 256 is zero, so a byte-at-a-time scan stopped inside the number
    # and resumed three bytes into the middle of the record. The ELSE
    # arm is what makes it visible: reaching it at all means the skip
    # landed where it meant to.
    ("a false IF skips over the literal in its own arm",
     program(spaced(10, name("A"), "=", num(9)),
             spaced(20, [K["IF"]], num(1), "=", num(2), [K["THEN"]],
                    name("A"), "=", num(5), [K["ELSE"]],
                    name("B"), "=", num(77)),
             line(30, [K["END"]])),
     {0: 9, 1: 77}),

    # **There is no ASM block any more.** [D63] took the on-machine
    # assembler out of the image and gave token $9E to `SYS`, so what
    # used to be `ASM` is now a statement that calls machine code at an
    # address. The case that lived here proved a block was stepped over;
    # there is nothing to step over. `SYS` is exercised end to end in
    # sim/test_run.py, which can poke a routine into memory for it to
    # call -- this suite drives the interpreter without one.

    # ---- long names. A-Z stay resident and stay the fast path; a name
    # of two characters or more goes in the table, and `count` and `n`
    # have to be able to sit in the same expression.
    ("long name: COUNT = 7 : A = COUNT",
     program(spaced(10, name("COUNT"), "=", num(7)),
             spaced(20, name("A"), "=", name("COUNT")),
             line(30, [K["END"]])),
     {0: 7}),

    ("long names are case-insensitive: Count and COUNT are one",
     program(spaced(10, name("Count"), "=", num(9)),
             spaced(20, name("A"), "=", name("cOuNt")),
             line(30, [K["END"]])),
     {0: 9}),

    # Six significant characters, so these are two names and not one.
    # Five would have merged them, which is why NSIG is six: the
    # assembler's labels are BASIC variables now and .done1/.done2 have
    # to stay apart.
    ("six significant characters: DONE10 and DONE11 differ",
     program(spaced(10, name("DONE10"), "=", num(3)),
             spaced(20, name("DONE11"), "=", num(4)),
             spaced(30, name("A"), "=", name("DONE10")),
             spaced(40, name("B"), "=", name("DONE11")),
             line(50, [K["END"]])),
     {0: 3, 1: 4}),

    ("an unset long name reads zero, as A-Z do",
     program(spaced(10, name("A"), "=", name("NEVERSET"), "+", num(5)),
             line(20, [K["END"]])),
     {0: 5}),

    ("FOR over a long name still nests and still counts",
     program(spaced(10, [K["FOR"]], name("IDX"), "=", num(1), [K["TO"]],
                    num(4)),
             spaced(20, name("TOTAL"), "=", name("TOTAL"), "+",
                    name("IDX")),
             spaced(30, [K["NEXT"]], name("IDX")),
             spaced(40, name("A"), "=", name("TOTAL")),
             line(50, [K["END"]])),
     {0: 10}),

    # All six relationals, because only four of them were ever run. The
    # `<=` and `>` arms popped the caller's return address -- `rhs` has
    # already balanced its own pushes -- and `<=` branched past the
    # subtraction it had just set up. Neither showed, because no case
    # used either operator.
    ("all six relationals, including <= and >",
     program(spaced(10, name("A"), "=", num(1), "<", num(2)),
             spaced(20, name("B"), "=", num(2), "<=", num(2)),
             spaced(30, name("C"), "=", num(3), ">", num(2)),
             spaced(40, name("D"), "=", num(2), ">=", num(3)),
             spaced(50, name("E"), "=", num(1), "<>", num(2)),
             spaced(60, name("F"), "=", num(1), "=", num(1)),
             line(70, [K["END"]])),
     {0: 0xFFFF, 1: 0xFFFF, 2: 0xFFFF, 3: 0, 4: 0xFFFF, 5: 0xFFFF}),

    ("the other way round, so a true test is not just always true",
     program(spaced(10, name("A"), "=", num(3), "<", num(2)),
             spaced(20, name("B"), "=", num(3), "<=", num(2)),
             spaced(30, name("C"), "=", num(1), ">", num(2)),
             spaced(40, name("D"), "=", num(4), ">=", num(3)),
             line(50, [K["END"]])),
     {0: 0, 1: 0, 2: 0, 3: 0xFFFF}),

    # AND, OR and XOR are bitwise, and because TRUE is -1 they are the
    # logical operators too -- the same instruction serves both. That is
    # BBC BASIC's reason for -1 and the whole point of copying it.
    ("AND, OR and XOR as bit operations",
     program(spaced(10, name("A"), "=", num(0x0F0F), [K["AND"]],
                    num(0x00FF)),
             spaced(20, name("B"), "=", num(0x0F00), [K["OR"]],
                    num(0x00F0)),
             spaced(30, name("C"), "=", num(0xFF00), [K["XOR"]],
                    num(0x0FF0)),
             line(40, [K["END"]])),
     {0: 0x000F, 1: 0x0FF0, 2: 0xF0F0}),

    ("the same operators as logic, which only works because TRUE is -1",
     program(spaced(10, name("A"), "=", num(1), "<", num(2), [K["AND"]],
                    num(3), "<", num(4)),
             spaced(20, name("B"), "=", num(1), "<", num(2), [K["AND"]],
                    num(4), "<", num(3)),
             spaced(30, name("C"), "=", num(9), "<", num(2), [K["OR"]],
                    num(3), "<", num(4)),
             line(40, [K["END"]])),
     {0: 0xFFFF, 1: 0, 2: 0xFFFF}),

    ("IF takes a compound condition without parentheses",
     program(spaced(10, name("K"), "=", num(5)),
             spaced(20, [K["IF"]], name("K"), ">", num(1), [K["AND"]],
                    name("K"), "<", num(9), [K["THEN"]], name("A"), "=",
                    num(7)),
             line(30, [K["END"]])),
     {0: 7}),

    # ---- strings. The `$` is the type, so `A` and `A$` are different
    # names and nothing needs a type field.
    ("A$ = \"HI\" : B$ = A$",
     program(spaced(10, name("A$"), "=", name('"HI"')),
             spaced(20, name("B$"), "=", name("A$")),
             spaced(30, [K["PRINT"]], name("B$")),
             line(40, [K["END"]])),
     {}, "HI"),

    ("concatenation, which the accumulator gets for nothing",
     program(spaced(10, name("A$"), "=", name('"AB"')),
             spaced(20, name("B$"), "=", name('"CD"')),
             spaced(30, name("C$"), "=", name("A$"), "+", name("B$"),
                    "+", name('"EF"')),
             spaced(40, [K["PRINT"]], name("C$")),
             line(50, [K["END"]])),
     {}, "ABCDEF"),

    ("a string variable and an integer of the same letter coexist",
     program(spaced(10, name("A"), "=", num(42)),
             spaced(20, name("A$"), "=", name('"X"')),
             spaced(30, [K["PRINT"]], name("A$")),
             line(40, [K["END"]])),
     {0: 42}, "X"),

    ("reassignment that fits reuses the space it already has",
     program(spaced(10, name("A$"), "=", name('"LONGER"')),
             spaced(20, name("A$"), "=", name('"AB"')),
             spaced(30, [K["PRINT"]], name("A$")),
             line(40, [K["END"]])),
     {}, "AB"),

    ("an empty string is a string",
     program(spaced(10, name("A$"), "=", name('""')),
             spaced(20, [K["PRINT"]], name("A$"), "+", name('"Z"')),
             line(30, [K["END"]])),
     {}, "Z"),

    ("LEN, and it does not disturb what it measures",
     program(spaced(10, name("A$"), "=", name('"HELLO"')),
             spaced(20, name("A"), "=", name("LEN"), "(", name("A$"), ")"),
             spaced(30, name("B"), "=", name("LEN"), "(", name("A$"), "+",
                    name('"XY"'), ")"),
             spaced(40, name("C$"), "=", name("A$"), "+", name('"!"')),
             spaced(50, [K["PRINT"]], name("C$")),
             line(60, [K["END"]])),
     {0: 5, 1: 7}, "HELLO!"),

    # Comparing in place is the other half of what the accumulator
    # buys: neither side was ever copied to the heap.
    ("string equality, which allocates nothing",
     program(spaced(10, name("A$"), "=", name('"YES"')),
             spaced(20, name("A"), "=", name("A$"), "=", name('"YES"')),
             spaced(30, name("B"), "=", name("A$"), "=", name('"NO"')),
             spaced(40, name("C"), "=", name("A$"), "<>", name('"NO"')),
             spaced(50, name("D"), "=", name("A$"), "<>", name('"YES"')),
             line(60, [K["END"]])),
     {0: 0xFFFF, 1: 0, 2: 0xFFFF, 3: 0}),

    ("a different length is never equal",
     program(spaced(10, name("A$"), "=", name('"AB"')),
             spaced(20, name("A"), "=", name("A$"), "=", name('"ABC"')),
             line(30, [K["END"]])),
     {0: 0}),

    ("IF on a string, which is what the comparison is for",
     program(spaced(10, name("A$"), "=", name('"Y"')),
             spaced(20, [K["IF"]], name("A$"), "=", name('"Y"'),
                    [K["THEN"]], name("A"), "=", num(1)),
             spaced(30, [K["IF"]], name("A$"), "=", name('"N"'),
                    [K["THEN"]], name("B"), "=", num(1)),
             line(40, [K["END"]])),
     {0: 1, 1: 0}),

    ("STR$ and VAL round-trip",
     program(spaced(10, [K["PRINT"]], name("STR$"), "(", num(1234), ")"),
             spaced(20, name("A"), "=", name("VAL"), "(", name('"567"'),
                    ")"),
             line(30, [K["END"]])),
     {0: 567}, "1234"),

    ("STR$ of zero and of a negative",
     program(spaced(10, name("A$"), "=", name("STR$"), "(", num(0), ")",
                    "+", name('","'), "+", name("STR$"), "(", "-",
                    num(42), ")"),
             spaced(20, [K["PRINT"]], name("A$")),
             line(30, [K["END"]])),
     {}, "0,-42"),

    # ---- VAL of a fraction. The digits go into the same 16-bit
    # ---- accumulator the integer path uses, counting those after the
    # ---- point, and one divide by 10^n at the end turns it into a
    # ---- float. Asserted on what PRINT rendered, because the value
    # ---- lands in FACC and not in a variable.
    ("VAL of a fraction is a float",
     program(spaced(10, [K["PRINT"]], name("VAL"), "(", name('"3.5"'), ")"),
             line(20, [K["END"]])),
     {}, "3.5"),

    ("VAL of a negative fraction keeps the sign",
     program(spaced(10, [K["PRINT"]], name("VAL"), "(", name('"-3.5"'),
                    ")"),
             line(20, [K["END"]])),
     {}, "-3.5"),

    ("a bare point still has an integer part of zero",
     program(spaced(10, [K["PRINT"]], name("VAL"), "(", name('".5"'), ")"),
             line(20, [K["END"]])),
     {}, "0.5"),

    ("a trailing point is the whole number",
     program(spaced(10, [K["PRINT"]], name("VAL"), "(", name('"3."'), ")"),
             line(20, [K["END"]])),
     {}, "3"),

    ("a quarter, which the format holds exactly",
     program(spaced(10, [K["PRINT"]], name("VAL"), "(", name('"0.25"'),
                    ")"),
             line(20, [K["END"]])),
     {}, "0.25"),

    # Four fraction digits is the cap: it is what 4.8 decimal digits can
    # carry, and it is what keeps 10^n inside sixteen bits.
    #
    # **Multiplied back out, not printed.** `fstr` renders about four
    # significant digits -- SQR(2) is 1.414 -- so printing this would
    # show 1.234 whether the parser kept four fraction digits or five,
    # and the assertion would be about the printer. Scaling by 10000
    # and crossing to an integer asks the parser directly.
    # Into a variable, not printed: INT gives an integer, and an
    # integer PRINT goes through the s_putn stub while the string one
    # goes through s_putsn -- so `printed` stays empty and the case
    # would fail while the value was right.
    ("digits past the fourth are consumed and ignored",
     program(spaced(10, name("A"), "=", [K["INT"]], "(", name("VAL"),
                    "(", name('"1.2345678"'), ")", "*", name("FLT"),
                    "(", num(10000), ")", ")"),
             line(20, [K["END"]])),
     {0: 12344}),        # not 12340, which is what four digits would be;
                         # the missing one is the 15-bit fraction and
                         # INT flooring the product, not a lost digit

    ("a second point ends the number, as any other non-digit does",
     program(spaced(10, [K["PRINT"]], name("VAL"), "(", name('"3.5.7"'),
                    ")"),
             line(20, [K["END"]])),
     {}, "3.5"),

    ("VAL takes a sign and stops at the first character that is not a digit",
     program(spaced(10, name("A"), "=", name("VAL"), "(", name('"-12"'),
                    ")"),
             spaced(20, name("B"), "=", name("VAL"), "(", name('"12AB"'),
                    ")"),
             spaced(30, name("C"), "=", name("VAL"), "(", name('"X"'),
                    ")"),
             line(40, [K["END"]])),
     {0: 0xFFF4, 1: 12, 2: 0}),

    ("VAL of STR$ is where it started",
     program(spaced(10, name("A"), "=", name("VAL"), "(", name("STR$"),
                    "(", num(9999), ")", ")"),
             line(20, [K["END"]])),
     {0: 9999}),

    ("INSTR finds, counting from one, or answers zero",
     program(spaced(10, name("A$"), "=", name('"HELLO WORLD"')),
             spaced(20, name("A"), "=", name("INSTR"), "(", name("A$"),
                    ",", name('"WORLD"'), ")"),
             spaced(30, name("B"), "=", name("INSTR"), "(", name("A$"),
                    ",", name('"H"'), ")"),
             spaced(40, name("C"), "=", name("INSTR"), "(", name("A$"),
                    ",", name('"ZZ"'), ")"),
             spaced(50, name("D"), "=", name("INSTR"), "(", name("A$"),
                    ",", name('"D"'), ")"),
             line(60, [K["END"]])),
     {0: 7, 1: 1, 2: 0, 3: 11}),

    ("INSTR leaves the accumulator alone, so it composes",
     program(spaced(10, name("A$"), "=", name('"ABCDE"')),
             spaced(20, name("B$"), "=", name("MID$"), "(", name("A$"),
                    ",", name("INSTR"), "(", name("A$"), ",",
                    name('"C"'), ")", ",", num(2), ")"),
             spaced(30, [K["PRINT"]], name("B$")),
             line(40, [K["END"]])),
     {}, "CD"),

    # ---- CALL and RETURN. The SUBs are found once at RUN, so a call
    # is the same lookup a variable is rather than a search.
    ("CALL a SUB and come back to the statement after it",
     program(spaced(10, name("A"), "=", num(1)),
             spaced(20, [K["CALL"]], name("BUMP")),
             spaced(30, name("B"), "=", num(9)),
             spaced(40, [K["GOTO"]], num(99)),
             spaced(50, [K["SUB"]], name("BUMP")),
             spaced(60, name("A"), "=", name("A"), "+", num(41)),
             spaced(70, [K["RETURN"]]),
             spaced(80, [K["END"]], [K["SUB"]]),
             line(99, [K["END"]])),
     {0: 42, 1: 9}),

    # A SUB defined *before* the code that calls it must be stepped over
    # rather than fallen into, and it spans records now.
    ("a SUB in the way is stepped over, not fallen into",
     program(spaced(10, [K["SUB"]], name("SETB")),
             spaced(20, name("B"), "=", num(7)),
             spaced(30, [K["RETURN"]]),
             spaced(40, [K["END"]], [K["SUB"]]),
             spaced(50, name("A"), "=", num(1)),
             spaced(60, [K["CALL"]], name("SETB")),
             line(70, [K["END"]])),
     {0: 1, 1: 7}),

    ("calls nest",
     program(spaced(10, [K["CALL"]], name("OUTER")),
             spaced(20, [K["GOTO"]], num(99)),
             spaced(30, [K["SUB"]], name("OUTER")),
             spaced(40, name("A"), "=", name("A"), "+", num(1)),
             spaced(50, [K["CALL"]], name("INNER")),
             spaced(60, name("A"), "=", name("A"), "+", num(10)),
             spaced(70, [K["RETURN"]]),
             spaced(80, [K["END"]], [K["SUB"]]),
             spaced(85, [K["SUB"]], name("INNER")),
             spaced(90, name("A"), "=", name("A"), "+", num(100)),
             spaced(95, [K["RETURN"]]),
             spaced(96, [K["END"]], [K["SUB"]]),
             line(99, [K["END"]])),
     {0: 111}),

    ("a SUB called from inside a loop",
     program(spaced(10, [K["FOR"]], name("I"), "=", num(1), [K["TO"]],
                    num(3)),
             spaced(20, [K["CALL"]], name("ADDIT")),
             spaced(30, [K["NEXT"]], name("I")),
             spaced(40, [K["GOTO"]], num(99)),
             spaced(50, [K["SUB"]], name("ADDIT")),
             spaced(60, name("S"), "=", name("S"), "+", num(5)),
             spaced(70, [K["RETURN"]]),
             spaced(80, [K["END"]], [K["SUB"]]),
             line(99, [K["END"]])),
     {18: 15}),

    # ---- the string functions. Each one's argument has already
    # appended itself to the accumulator, so they are a length change
    # and at most a move within it -- nothing allocates.
    ("LEFT$, RIGHT$ and MID$",
     program(spaced(10, name("A$"), "=", name('"ABCDEF"')),
             spaced(20, name("B$"), "=", name("LEFT$"), "(", name("A$"),
                    ",", num(3), ")"),
             spaced(30, [K["PRINT"]], name("B$")),
             line(40, [K["END"]])),
     {}, "ABC"),

    ("RIGHT$ takes them off the other end",
     program(spaced(10, name("A$"), "=", name('"ABCDEF"')),
             spaced(20, [K["PRINT"]], name("RIGHT$"), "(", name("A$"),
                    ",", num(2), ")"),
             line(30, [K["END"]])),
     {}, "EF"),

    ("MID$ counts from one, as every BASIC does",
     program(spaced(10, name("A$"), "=", name('"ABCDEF"')),
             spaced(20, [K["PRINT"]], name("MID$"), "(", name("A$"), ",",
                    num(3), ",", num(2), ")"),
             line(30, [K["END"]])),
     {}, "CD"),

    ("asking for more than there is gives what there is",
     program(spaced(10, name("A$"), "=", name('"AB"')),
             spaced(20, [K["PRINT"]], name("LEFT$"), "(", name("A$"),
                    ",", num(99), ")"),
             line(30, [K["END"]])),
     {}, "AB"),

    ("CHR$ and ASC are inverses",
     program(spaced(10, name("A"), "=", name("ASC"), "(",
                    name('"A"'), ")"),
             spaced(20, [K["PRINT"]], name("CHR$"), "(", num(66), ")"),
             line(30, [K["END"]])),
     {0: 65}, "B"),

    ("a function inside a concatenation, which is where the accumulator earns it",
     program(spaced(10, name("A$"), "=", name('"HELLO"')),
             spaced(20, name("B$"), "=", name("LEFT$"), "(", name("A$"),
                    ",", num(2), ")", "+", name('"-"'), "+",
                    name("RIGHT$"), "(", name("A$"), ",", num(2), ")"),
             spaced(30, [K["PRINT"]], name("B$")),
             line(40, [K["END"]])),
     {}, "HE-LO"),

    ("LEN of a function result",
     program(spaced(10, name("A$"), "=", name('"ABCDEF"')),
             spaced(20, name("A"), "=", name("LEN"), "(", name("MID$"),
                    "(", name("A$"), ",", num(2), ",", num(3), ")", ")"),
             line(30, [K["END"]])),
     {0: 3}),

    # ---- DO/LOOP, with the test at either end or both.
    ("DO ... LOOP UNTIL, which always runs once",
     program(spaced(10, [K["DO"]]),
             spaced(20, name("S"), "=", name("S"), "+", num(1)),
             spaced(30, [K["LOOP"]], [K["UNTIL"]], name("S"), "=", num(5)),
             spaced(40, name("A"), "=", name("S")),
             line(50, [K["END"]])),
     {0: 5}),

    ("DO WHILE tests at the top, so a false one runs the body never",
     program(spaced(10, name("S"), "=", num(9)),
             spaced(20, [K["DO"]], [K["WHILE"]], num(0)),
             spaced(30, name("S"), "=", num(1)),
             spaced(40, [K["LOOP"]]),
             spaced(50, name("A"), "=", name("S")),
             line(60, [K["END"]])),
     {0: 9}),

    ("LOOP WHILE tests at the bottom",
     program(spaced(10, [K["DO"]]),
             spaced(20, name("S"), "=", name("S"), "+", num(2)),
             spaced(30, [K["LOOP"]], [K["WHILE"]], name("S"), "<", num(7)),
             spaced(40, name("A"), "=", name("S")),
             line(50, [K["END"]])),
     {0: 8}),

    ("EXIT leaves from the middle and lands past the LOOP",
     program(spaced(10, [K["DO"]]),
             spaced(20, name("S"), "=", name("S"), "+", num(1)),
             spaced(30, [K["IF"]], name("S"), "=", num(3), [K["THEN"]],
                    [K["EXIT"]]),
             spaced(40, [K["LOOP"]]),
             spaced(50, name("A"), "=", name("S")),
             line(60, [K["END"]])),
     {0: 3}),

    ("a nested DO, and EXIT counts the nesting on its way out",
     program(spaced(10, [K["DO"]]),
             spaced(20, name("I"), "=", name("I"), "+", num(1)),
             spaced(30, [K["DO"]]),
             spaced(40, name("J"), "=", name("J"), "+", num(1)),
             spaced(50, [K["LOOP"]], [K["UNTIL"]], name("J"),
                    name("MOD"), num(3), "=", num(0)),
             spaced(60, [K["LOOP"]], [K["UNTIL"]], name("I"), "=", num(2)),
             spaced(70, name("A"), "=", name("I")),
             spaced(80, name("B"), "=", name("J")),
             line(90, [K["END"]])),
     {0: 2, 1: 6}),

    # ELSEIF reached while running means the arm above it succeeded, so
    # it behaves as ELSE does; reached by a *false* IF it is a fresh
    # condition on the same line.
    ("ELSEIF picks the arm that matches",
     program(spaced(10, name("K"), "=", num(2)),
             spaced(20, [K["IF"]], name("K"), "=", num(1), [K["THEN"]],
                    name("A"), "=", num(11), [K["ELSEIF"]], name("K"),
                    "=", num(2), [K["THEN"]], name("A"), "=", num(22),
                    [K["ELSE"]], name("A"), "=", num(33)),
             line(30, [K["END"]])),
     {0: 22}),

    ("ELSEIF falls through to ELSE when no arm matches",
     program(spaced(10, name("K"), "=", num(7)),
             spaced(20, [K["IF"]], name("K"), "=", num(1), [K["THEN"]],
                    name("A"), "=", num(11), [K["ELSEIF"]], name("K"),
                    "=", num(2), [K["THEN"]], name("A"), "=", num(22),
                    [K["ELSE"]], name("A"), "=", num(33)),
             line(30, [K["END"]])),
     {0: 33}),

    ("the first arm still wins, and skips the rest of the line",
     program(spaced(10, name("K"), "=", num(1)),
             spaced(20, [K["IF"]], name("K"), "=", num(1), [K["THEN"]],
                    name("A"), "=", num(11), [K["ELSEIF"]], name("K"),
                    "=", num(1), [K["THEN"]], name("A"), "=", num(22)),
             line(30, [K["END"]])),
     {0: 11}),

    # ---- division. One restoring pass gives the quotient and the
    # remainder both, so MOD is the same routine read a different way.
    ("integer division and MOD, one routine between them",
     program(spaced(10, name("A"), "=", num(7), "/", num(2)),
             spaced(20, name("B"), "=", num(100), "/", num(10)),
             spaced(30, name("C"), "=", num(7), name("MOD"), num(2)),
             spaced(40, name("D"), "=", num(100), name("MOD"), num(7)),
             spaced(50, name("E"), "=", num(1), "/", num(2)),
             line(60, [K["END"]])),
     {0: 3, 1: 10, 2: 1, 3: 2, 4: 0}),

    # Truncating toward zero, with the remainder taking the dividend's
    # sign -- BBC BASIC's rule for DIV and MOD, and C's later.
    ("negative operands truncate toward zero",
     program(spaced(10, name("A"), "=", "-", num(7), "/", num(2)),
             spaced(20, name("B"), "=", "-", num(7), name("MOD"), num(2)),
             spaced(30, name("C"), "=", num(7), "/", "-", num(2)),
             spaced(40, name("D"), "=", "-", num(8), "/", num(2)),
             line(50, [K["END"]])),
     {0: 0xFFFD, 1: 0xFFFF, 2: 0xFFFD, 3: 0xFFFC}),

    ("division binds tighter than addition",
     program(spaced(10, name("A"), "=", num(1), "+", num(9), "/", num(3)),
             spaced(20, name("B"), "=", num(20), "/", num(4), "/", num(5)),
             line(30, [K["END"]])),
     {0: 4, 1: 1}),

    # ---- DIM and arrays. DIM A(10) is eleven elements, 0 to 10, which
    # is BBC BASIC's rule and Microsoft's and what every published
    # program assumes.
    ("DIM A(10) : A(3) = 7 : B = A(3)",
     program(spaced(10, [K["DIM"]], name("A"), "(", num(10), ")"),
             spaced(20, name("A"), "(", num(3), ")", "=", num(7)),
             spaced(30, name("B"), "=", name("A"), "(", num(3), ")"),
             line(40, [K["END"]])),
     {1: 7}),

    # A(3) and A must be different variables. BBC has one namespace and
    # refuses the collision; A-Z are resident here, so an array called A
    # goes in the name table under the name `A(`.
    ("the array A and the scalar A are not the same variable",
     program(spaced(10, [K["DIM"]], name("A"), "(", num(4), ")"),
             spaced(20, name("A"), "=", num(99)),
             spaced(30, name("A"), "(", num(1), ")", "=", num(5)),
             spaced(40, name("B"), "=", name("A")),
             spaced(50, name("C"), "=", name("A"), "(", num(1), ")"),
             line(60, [K["END"]])),
     {0: 99, 1: 99, 2: 5}),

    ("an undimensioned element reads zero",
     program(spaced(10, [K["DIM"]], name("SIEVE"), "(", num(20), ")"),
             spaced(20, name("A"), "=", name("SIEVE"), "(", num(9), ")",
                    "+", num(1)),
             line(30, [K["END"]])),
     {0: 1}),

    ("the last element, A(10), is in range",
     program(spaced(10, [K["DIM"]], name("A"), "(", num(10), ")"),
             spaced(20, name("A"), "(", num(10), ")", "=", num(42)),
             spaced(30, name("B"), "=", name("A"), "(", num(10), ")"),
             line(40, [K["END"]])),
     {1: 42}),

    ("a whole array summed in a loop",
     program(spaced(10, [K["DIM"]], name("V"), "(", num(5), ")"),
             spaced(20, [K["FOR"]], name("I"), "=", num(0), [K["TO"]],
                    num(5)),
             spaced(30, name("V"), "(", name("I"), ")", "=", name("I"),
                    "*", num(2)),
             spaced(40, [K["NEXT"]], name("I")),
             spaced(50, [K["FOR"]], name("I"), "=", num(0), [K["TO"]],
                    num(5)),
             spaced(60, name("S"), "=", name("S"), "+", name("V"), "(",
                    name("I"), ")"),
             spaced(70, [K["NEXT"]], name("I")),
             spaced(80, name("A"), "=", name("S")),
             line(90, [K["END"]])),
     {0: 30}),

    ("spaced: FOR I = 1 TO 3, three iterations",
     program(spaced(10, [K["FOR"]], name("I"), "=", num(1), [K["TO"]],
                    num(3)),
             spaced(20, name("S"), "=", name("S"), "+", num(1)),
             spaced(30, [K["NEXT"]], name("I")),
             line(40, [K["END"]])),
     {18: 3, 8: 4}),
]


def trace(pattern, n=400):
    """`python sim/test_interp.py --trace "past the fourth" [n]`

    Run the one case whose name contains `pattern` and print what the
    machine executed, `n` instructions from the first statement. A case
    that prints nothing has either faulted or never reached PRINT, and
    a breakpoint cannot tell those apart -- the trace decodes forward
    from the live PC, so the boundaries are the ones the CPU used.
    """
    code, syms = build("interp", HARNESS)
    hit = [c for c in CASES if pattern.lower() in c[0].lower()]
    if not hit:
        raise SystemExit("no case matching %r" % pattern)
    name_, prog = hit[0][0], hit[0][1]
    m = cool8rsvm.machine()
    m.bus.mem[CODE:CODE + len(code)] = code
    at = syms["prog"]
    m.bus.mem[at:at + len(prog)] = bytes(prog)
    end = at + len(prog)
    m.cpu.pc, m.cpu.sp, m.romen = CODE, 0x7FF0, False
    m.bus.mem[0x0016] = end & 0xFF
    m.bus.mem[0x0017] = end >> 8
    print("  " + name_)
    print()
    why = m.run(budget=20_000_000)
    err = m.bus.mem[0x0018]              # ERR, sw/zp.asm
    ln = m.bus.mem[syms["printlen"]]
    got = bytes(m.bus.mem[syms["printed"]:syms["printed"] + ln])
    print("  run:     %s" % why)
    print("  ERR:     $%02X" % err)
    print("  printed: %r" % got.decode("latin-1"))
    print()
    print("  Nothing printed with ERR clear means PRINT was never")
    print("  reached; a non-zero ERR names the fault -- see E_* in")
    print("  sw/zp.asm. For instruction-level detail use sim/dbg.py,")
    print("  which owns disassembly for the batch machine.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--trace":
        return trace(sys.argv[2],
                     int(sys.argv[3]) if len(sys.argv) > 3 else 400)
    print("  I2 -- sw/interp.asm, on the editor's stored form")
    print()
    code, syms = build("interp", HARNESS)
    print(f"  interpreter: {syms['prog'] - syms['irun']:,} bytes")
    # **There is no second machine to fall back to.** This line used to
    # offer "python", from when a reference emulator existed; [D57]
    # retired it and H.machine() now refuses rather than pretending.
    print("  machine: the VM (rust/), which is the default for any "
          "software test")
    print()
    for case in CASES:
        name_, prog, want = case[0], case[1], case[2]
        wantstr = case[3] if len(case) > 3 else None
        m = cool8rsvm.machine()
        m.bus.mem[CODE:CODE + len(code)] = code
        at = syms["prog"]
        m.bus.mem[at:at + len(prog)] = bytes(prog)
        # progend is one past the last record
        end = at + len(prog)
        m.cpu.pc = CODE
        m.cpu.sp = 0x7FF0
        m.romen = False
        # patch the progend the harness loaded
        m.bus.mem[0x0016] = end & 0xFF
        m.bus.mem[0x0017] = end >> 8
        # m.run, not a stepping loop: the machine advances the raster
        # and the interrupt flags and a bare loop does not (AGENTS.md).
        if m.run(budget=20_000_000) != "halt":
            check(False, name_, "never halted")
            continue
        got = {i: m.bus.mem[VARS + 2 * i] | (m.bus.mem[VARS + 2 * i + 1] << 8)
               for i in want}
        ok = got == want
        detail = "" if ok else f"got {got}, wanted {want}"
        if wantstr is not None:
            n = m.bus.mem[syms["printlen"]]
            at2 = syms["printed"]
            gots = bytes(m.bus.mem[at2:at2 + n]).decode("latin-1")
            if gots != wantstr:
                ok = False
                detail = f"printed {gots!r}, wanted {wantstr!r}"
        check(ok, name_, detail)
    # ---- the errors the FOR stack raises
    #
    # A bounded stack is only worth having if going over it says so. The
    # BBC Micro's "Too many FORs" is the model: the alternative is
    # wrapping and running the wrong program, which is what the
    # one-level version did.
    def run_err(prog):
        m = cool8rsvm.machine()
        m.bus.mem[CODE:CODE + len(code)] = code
        at = syms["prog"]
        m.bus.mem[at:at + len(prog)] = bytes(prog)
        m.cpu.pc, m.cpu.sp, m.romen = CODE, 0x7FF0, False
        m.bus.mem[0x0016] = (at + len(prog)) & 0xFF
        m.bus.mem[0x0017] = (at + len(prog)) >> 8
        m.run(budget=5_000_000)
        return m.bus.mem[0x0018]        # ERR

    # MAXFOR is 8, so the ninth is one too many.
    nest = [line(10 + i, [K["FOR"]], name(chr(65 + i)), "=", num(1),
                 [K["TO"]], num(2)) for i in range(9)]
    err = run_err(program(*nest, line(200, [K["END"]])))
    check(err == 2, "a tenth nested FOR stops with ?TOO MANY FORS",
          f"ERR was {err}, wanted 2")

    err = run_err(program(line(10, [K["NEXT"]]), line(20, [K["END"]])))
    check(err == 3, "NEXT with no FOR stops with ?NEXT WITHOUT FOR",
          f"ERR was {err}, wanted 3")

    # DO has a bounded stack of its own and says so when it fills,
    # which is the BBC Micro's rule rather than BBC BASIC (86)'s.
    nest = [line(10 + i, [K["DO"]]) for i in range(5)]
    err = run_err(program(*nest, line(200, [K["END"]])))
    check(err == 16, "a fifth nested DO stops with ?TOO MANY DOS",
          f"ERR was {err}, wanted 16")

    err = run_err(program(line(10, [K["LOOP"]]), line(20, [K["END"]])))
    check(err == 16, "LOOP with no DO stops rather than jumping nowhere",
          f"ERR was {err}, wanted 16")

    err = run_err(program(line(10, [K["EXIT"]]), line(20, [K["END"]])))
    check(err == 16, "EXIT with no DO likewise",
          f"ERR was {err}, wanted 16")

    err = run_err(program(spaced(10, name("A"), "=", num(1), "/", num(0)),
                          line(20, [K["END"]])))
    check(err == 15, "division by zero stops with ?DIVISION BY ZERO",
          f"ERR was {err}, wanted 15")

    err = run_err(program(spaced(10, [K["CALL"]], name("NOPE")),
                          line(20, [K["END"]])))
    check(err == 17, "CALL of a SUB that is not there stops",
          f"ERR was {err}, wanted 17")

    err = run_err(program(line(10, [K["RETURN"]]), line(20, [K["END"]])))
    check(err == 17, "RETURN without CALL stops",
          f"ERR was {err}, wanted 17")

    # ---- subscripts are checked, which BBC BASIC II does not do.
    #
    # It checks only at DIM, that the bound fits in fourteen bits, and
    # does no range test when indexing. That is affordable when the
    # running program is a separate compiled copy; here the stored
    # program *is* the program, so an unchecked subscript writes over
    # the source of the statement executing it.
    err = run_err(program(spaced(10, [K["DIM"]], name("A"), "(", num(4),
                                 ")"),
                          spaced(20, name("A"), "(", num(5), ")", "=",
                                 num(1)),
                          line(30, [K["END"]])))
    check(err == 7, "one past the end stops with ?SUBSCRIPT",
          f"ERR was {err}, wanted 7")

    err = run_err(program(spaced(10, [K["DIM"]], name("A"), "(", num(4),
                                 ")"),
                          spaced(20, name("B"), "=", name("A"), "(",
                                 num(0), "-", num(1), ")"),
                          line(30, [K["END"]])))
    check(err == 7, "a negative subscript stops with ?SUBSCRIPT",
          f"ERR was {err}, wanted 7")

    err = run_err(program(spaced(10, name("B"), "=", name("Q"), "(",
                                 num(0), ")"),
                          line(20, [K["END"]])))
    check(err == 7, "an array never DIMmed stops with ?SUBSCRIPT",
          f"ERR was {err}, wanted 7")

    # The heap comes down toward the name table and they must meet at
    # an error rather than through each other.
    err = run_err(program(spaced(10, [K["DIM"]], name("BIG"), "(",
                                 num(20000), ")"),
                          line(20, [K["END"]])))
    check(err == 5, "a DIM that will not fit stops with ?OUT OF MEMORY",
          f"ERR was {err}, wanted 5")

    # Eight deep is legal and must still run to a clean stop.
    nest8 = [line(10 + i, [K["FOR"]], name(chr(65 + i)), "=", num(1),
                  [K["TO"]], num(1)) for i in range(8)]
    nest8 += [line(100 + i, [K["NEXT"]], name(chr(72 - i)))
              for i in range(8)]
    err = run_err(program(*nest8, line(200, [K["END"]])))
    check(err == 255, "eight deep is legal and ends cleanly",
          f"ERR was {err}, wanted 255")

    # ---- the stack, which is 256 bytes on the machine and not here
    #
    # interp.asm's header says a parenthesis costs six bytes of stack,
    # so depth 20 is 120 and safe. That is a claim about a hazard that
    # has already cost a day on this project, and the harness runs with
    # SP at $7FF0 where the machine runs it at $0200 -- so the harness
    # cannot fail the way the machine would. Measure it instead.
    #
    # Two depths, because the interesting number is the slope: the
    # difference divides out everything that is not per-level.
    def depth_cost(d):
        prog = program(line(10, name("A"), "=",
                            "(" * d, num(7), ")" * d),
                       line(20, [K["END"]]))
        # The high-water mark needs a look at SP after every
        # instruction — the machine's own low-water mark (sp_min,
        # server-side), because that look cannot cross the session
        # pipe one tick at a time.
        m = vm.Machine()
        m.bus.mem[CODE:CODE + len(code)] = code
        at = syms["prog"]
        m.bus.mem[at:at + len(prog)] = bytes(prog)
        m.cpu.pc, m.cpu.sp, m.romen = CODE, 0x7FF0, False
        m.bus.mem[0x0016] = (at + len(prog)) & 0xFF
        m.bus.mem[0x0017] = (at + len(prog)) >> 8
        m.sp_clear()
        m.run(budget=2_000_000)
        low = min(m.sp_min(), 0x7FF0)
        a = m.bus.mem[VARS] | (m.bus.mem[VARS + 1] << 8)
        return 0x7FF0 - low, a

    MAXEXPR = 24                        # must track sw/interp.asm
    d5, a5 = depth_cost(5)
    d20, a20 = depth_cost(20)
    check(a5 == 7 and a20 == 7, "a deeply parenthesised expression still "
          "gives the right answer", f"got {a5} and {a20}, wanted 7")
    per = (d20 - d5) / 15.0
    print(f"    a parenthesis costs {per:.1f} bytes of stack "
          f"({d5} at depth 5, {d20} at depth 20)")

    # The evaluator refuses past MAXEXPR, so the worst case is bounded
    # by the counter rather than by what fits in a 127-byte line. The
    # editor is 78 bytes down when it calls RUN; the two together have
    # to fit in the 256-byte stack, and page 0 below it holds the
    # interpreter's state, the variables and the filesystem's workspace.
    worst = d20 + per * (MAXEXPR - 20)
    check(worst + 78 < 256, "the deepest expression the evaluator allows "
          "still fits under the editor",
          f"{MAXEXPR} levels reach {worst:.0f} bytes and the editor is "
          f"already 78 down, of 256")

    # And past it, it says so rather than running off the stack.
    over = program(line(10, name("A"), "=",
                        "(" * (MAXEXPR + 6), num(7), ")" * (MAXEXPR + 6)),
                   line(20, [K["END"]]))
    err = run_err(over)
    check(err == 4, "past that it stops with ?FORMULA TOO COMPLEX",
          f"ERR was {err}, wanted 4")

    # ---- the open question: what does an expression cost in a loop?
    #
    # I1 reported 6.09x for a single statement, which is fixed overhead
    # against almost nothing. This is the same expression a thousand
    # times, which is the number that decides the design.
    bench = program(
        line(10, [K["FOR"]], name("K"), "=", num(1), [K["TO"]], num(1000)),
        line(20, name("A"), "=", name("K"), "+", num(3), "-", name("K")),
        line(30, [K["NEXT"]]),
        line(40, [K["END"]]))
    m = cool8rsvm.machine()
    m.bus.mem[CODE:CODE + len(code)] = code
    at = syms["prog"]
    m.bus.mem[at:at + len(bench)] = bytes(bench)
    end = at + len(bench)
    m.cpu.pc = CODE
    m.cpu.sp = 0x7FF0
    m.romen = False
    m.bus.mem[0x0016] = end & 0xFF
    m.bus.mem[0x0017] = end >> 8
    m.run(budget=80_000_000)
    got = m.bus.mem[VARS + 20] | (m.bus.mem[VARS + 21] << 8)
    # the native equivalent, as the compiler emits it
    nat, _ = build("bnat", """
        .org $0200
        MOV  R0,#1
        MOV  R1,#0
        ST   [$0054],R0
        ST   [$0055],R1
top:    MOV  R0,#$E8
        MOV  R1,#3
        LD   R2,[$0054]
        LD   R3,[$0055]
        SUB  R0,R2
        SBC  R1,R3
        BGE  .go
        JMP  done
.go:    LD   R0,[$0054]
        LD   R1,[$0055]
        MOV  R2,#3
        MOV  R3,#0
        ADD  R0,R2
        ADC  R1,R3
        LD   R2,[$0054]
        LD   R3,[$0055]
        SUB  R0,R2
        SBC  R1,R3
        ST   [$0040],R0
        ST   [$0041],R1
        LD   R0,[$0054]
        LD   R1,[$0055]
        MOV  R2,#1
        MOV  R3,#0
        ADD  R0,R2
        ADC  R1,R3
        ST   [$0054],R0
        ST   [$0055],R1
        JMP  top
done:   HALT
""")
    mn = cool8rsvm.machine()
    mn.bus.mem[CODE:CODE + len(nat)] = nat
    mn.cpu.pc = CODE
    mn.cpu.sp = 0x7FF0
    mn.romen = False
    mn.run(budget=80_000_000)
    kn = mn.bus.mem[0x0054] | (mn.bus.mem[0x0055] << 8)
    print()
    check(got == kn == 1001,
          f"1000 x  A = K + 3 - K   (K ends {got}, native {kn})")
    print(f"    native {mn.cpu.cycles:,} clocks, interpreted "
          f"{m.cpu.cycles:,} -- {m.cpu.cycles/mn.cpu.cycles:.2f}x")

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
