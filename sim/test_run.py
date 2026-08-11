#!/usr/bin/env python3
"""I5 -- RUN, typed at the editor over the UART.

    python sim/test_run.py

Everything else in this milestone's battery pokes the interpreter's
state and calls `irun` directly. This does not: it boots the machine,
types a program at it a character at a time, types `RUN`, and reads the
answer off the screen through the machine's own `VID_BASE`.

That is the only test that can catch the wiring -- `dorun` telling the
interpreter where the program, the heap, the accumulator and the CALL
stack are, and the assembly pass running before the first statement.
`sim/test_interp.py` supplies all of that from a harness and so cannot.

It reuses `sim/test_basic.py`'s `Machine` verbatim, because that harness
reads the screen through the machine's own registers rather than
assuming where it is -- the rule docs/10-debugging.md was written about.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import test_basic as B                                     # noqa: E402

ROOT = H.ROOT

FAILS = H.FAILS


def run(code, syms, lines, budget=200_000_000):
    """Type a program, RUN it, and hand back the screen."""
    M = B.Machine(code, syms)
    M.settle()
    for ln in lines:
        M.cmd(ln)
    M.cmd("RUN")
    M.settle(budget)
    return M


def shows(M, text):
    return any(r.strip() == text for r in M.screen())


CASES = [
    # The whole point: the stored program is what runs. Nothing was
    # compiled, nothing was copied.
    ("PRINT of an expression",
     ["10 PRINT 2 + 3 * 4", "20 END"], "14"),

    ("a variable survives between lines",
     ["10 A = 6", "20 A = A * 7", "30 PRINT A", "40 END"], "42"),

    # [D45] puts assembler labels in the same table as SUB names, so
    # `CALL name` on a plain label runs the machine code at it. That is
    # the only way a BASIC program executes an ASM block -- h_asm itself
    # just steps over one -- and it is what a loadable library is
    # reached through, so it is worth a case of its own. A stores at
    # VARS, which sw/zp.asm puts at $0040.
    # `ASM` is no longer a keyword ([D63]) -- $9E is SYS now -- so a
    # program that says ASM is assigning to a variable of that name.
    # Nothing errors, which is the right outcome for a word that never
    # did anything.
    ("ASM is an ordinary name now",
     ["10 ASM = 5", "20 PRINT ASM", "30 END"], "5"),

    # ---- floating point, resident ([D63]). A float is STYPE 2 with the
    # ---- value in FACC, the same shape strings have always had, so
    # ---- PRINT renders it through the string path.
    ("SQR of a perfect square", ["10 PRINT SQR(9)", "20 END"], "3"),
    ("SQR of one that is not", ["10 PRINT SQR(2)", "20 END"], "1.414"),
    ("LOG", ["10 PRINT LOG(1)", "20 END"], "0"),
    ("EXP", ["10 PRINT EXP(0)", "20 END"], "1"),
    ("SIN of zero", ["10 PRINT SIN(0)", "20 END"], "0"),
    ("COS of zero", ["10 PRINT COS(0)", "20 END"], "1"),
    ("FLT promotes an integer", ["10 PRINT FLT(7)", "20 END"], "7"),
    # The argument may itself be a float, which is what fargf's type
    # test is for -- without it this would convert FACC's bit pattern.
    ("a float argument is not converted twice",
     ["10 PRINT SQR(SQR(16))", "20 END"], "2"),

    # ---- the operators promote. Either side being a float makes the
    # ---- whole thing float; two integers still take the integer path,
    # ---- which is what every other test in this file depends on.
    ("float on the left of +", ["10 PRINT SQR(2) + 1", "20 END"], "2.414"),
    ("float on the right of +", ["10 PRINT 1 + SQR(2)", "20 END"], "2.414"),
    ("float minus float",
     ["10 PRINT SQR(9) - SQR(4)", "20 END"], "1"),
    ("float times integer", ["10 PRINT SQR(9) * 3", "20 END"], "9"),
    ("integer divided by float, which integer division would floor",
     ["10 PRINT 1 / FLT(4)", "20 END"], "0.25"),
    # 0.9999, not 1, and that is the format being honest rather than a
    # fault: a third does not fit 16 significand bits, the divide
    # truncates, and multiplying back cannot recover what was dropped.
    # Every small float does this; expecting 1 here would be expecting
    # 4.8 digits to behave like infinite ones.
    ("a whole expression of them, and it does not round-trip",
     ["10 PRINT FLT(1) / FLT(3) * FLT(3)", "20 END"], "0.9999"),

    # ---- A#-Z#. The suffix is the type, so A, A# and A$ are three
    # ---- variables, and a float needs no storage of its own: the name
    # ---- table entry's value and aux are four contiguous bytes and a
    # ---- packed float is three.
    ("a float variable holds a float",
     ["10 X# = SQR(2)", "20 PRINT X#", "30 END"], "1.414"),
    ("an integer right-hand side is promoted",
     ["10 X# = 1", "20 PRINT X#", "30 END"], "1"),
    ("a float variable in an expression",
     ["10 X# = FLT(1) / FLT(4)", "20 PRINT X# + 1", "30 END"], "1.25"),
    ("A and A# are different variables",
     ["10 A = 7", "20 A# = SQR(9)", "30 PRINT A", "40 END"], "7"),
    ("and the float one kept its own value",
     ["10 A = 7", "20 A# = SQR(9)", "30 PRINT A#", "40 END"], "3"),
    ("a float survives into the next statement",
     ["10 X# = FLT(1) / FLT(3)", "20 Y# = X# * FLT(3)", "30 PRINT Y#",
      "40 END"], "0.9999"),
    ("INT crosses a float variable back",
     ["10 X# = FLT(7) / FLT(2)", "20 PRINT INT(X#)", "30 END"], "3"),

    # 1023, not 1024. `^` is exp(y * ln x), and a 15-bit fraction cannot
    # make that round trip exactly -- the same last-digit artifact the
    # period Microsoft BASICs had. Pinned so a change in fexp/flog shows up.
    ("the power operator, and two integers still promote",
     ["10 PRINT 2 ^ 10", "20 END"], "1023"),

    # ---- Comparisons. All six operators, both orders, and both sides
    # ---- of each boundary -- `rhs` folds a float pair to (sign, 0) and
    # ---- the integer arms decide, so a sign error would flip a whole
    # ---- operator rather than one case.
    ("a float compares greater",
     ["10 X# = FLT(1) / FLT(2)", "20 IF X# > 0 THEN PRINT 7",
      "30 END"], "7"),
    ("and is not greater when it is not",
     ["10 X# = FLT(1) / FLT(2)", "20 IF X# > 1 THEN PRINT 7",
      "30 PRINT 9", "40 END"], "9"),
    ("an integer on the left promotes too",
     ["10 X# = FLT(1) / FLT(2)", "20 IF 1 > X# THEN PRINT 7",
      "30 END"], "7"),
    ("less-than",
     ["10 IF SQR(2) < 2 THEN PRINT 7", "20 END"], "7"),
    ("equality on a value that is exact",
     ["10 X# = FLT(4) / FLT(2)", "20 IF X# = 2 THEN PRINT 7",
      "30 END"], "7"),
    ("inequality",
     ["10 IF SQR(2) <> 1 THEN PRINT 7", "20 END"], "7"),
    ("<= at the boundary, where equal must still pass",
     ["10 X# = FLT(4) / FLT(2)", "20 IF X# <= 2 THEN PRINT 7",
      "30 END"], "7"),
    (">= at the boundary",
     ["10 X# = FLT(4) / FLT(2)", "20 IF X# >= 2 THEN PRINT 7",
      "30 END"], "7"),
    ("a negative float compares below zero",
     ["10 X# = FLT(0) - FLT(3)", "20 IF X# < 0 THEN PRINT 7",
      "30 END"], "7"),
    ("two floats against each other, not just against integers",
     ["10 X# = SQR(2)", "20 Y# = SQR(3)", "30 IF Y# > X# THEN PRINT 7",
      "40 END"], "7"),
    ("a float loop condition runs to completion",
     ["10 X# = FLT(0)", "20 X# = X# + FLT(1)",
      "30 IF X# < FLT(4) THEN GOTO 20", "40 PRINT INT(X#)",
      "50 END"], "4"),
    # 4 > 10/2 is false. If the right were evaluated as its last operand
    # alone it would be 4 > 2, which is true -- so this case tells the
    # two apart where 3 > 1/2 does not.
    # A float *expression* on the right, which needs rhs to go through
    # erel. Each pair is chosen so that evaluating the right as its last
    # operand alone gives the opposite answer -- `3 > 1/2` would pass
    # either way and proves nothing.
    ("a float expression on the right, false side",   # 4 > 5
     ["10 IF FLT(4) > FLT(10) / FLT(2) THEN PRINT 7",
      "20 PRINT 9", "30 END"], "9"),
    ("a float expression on the right, true side",    # 4 > 2
     ["10 IF FLT(4) > FLT(10) / FLT(5) THEN PRINT 7",
      "20 END"], "7"),
    ("a sum on the right",                            # 4 > 11
     ["10 IF FLT(4) > FLT(10) + FLT(1) THEN PRINT 7",
      "20 PRINT 9", "30 END"], "9"),
    ("a float expression on the left",                # 2 < 4
     ["10 IF FLT(10) / FLT(5) < FLT(4) THEN PRINT 7",
      "20 END"], "7"),
    ("an expression on both sides at once",           # 2.5 > 1.5
     ["10 IF FLT(10) / FLT(4) > FLT(3) / FLT(2) THEN PRINT 7",
      "20 END"], "7"),
    # Strings still take the string path -- STYPE 1, not "non-zero".
    ("a string comparison is untouched by the float arm",
     ['10 IF "AB" = "AB" THEN PRINT 7', "20 END"], "7"),
    ("and an unequal one",
     ['10 IF "AB" = "AC" THEN PRINT 7', "20 PRINT 9", "30 END"], "9"),

    # ---- Unary minus.
    ("unary minus on a float keeps the sign",
     ["10 X# = SQR(2)", "20 PRINT -X#", "30 END"], "-1.414"),
    ("unary minus twice returns it",
     ["10 X# = SQR(2)", "20 PRINT -(-X#)", "30 END"], "1.414"),
    ("unary minus on an integer is unchanged",
     ["10 A = 5", "20 PRINT -A", "30 END"], "-5"),
    ("negating zero does not invent a sign",
     ["10 X# = FLT(0)", "20 PRINT -X#", "30 END"], "0"),

    ("binary minus promotes, as every operator does",
     ["10 PRINT 0 - SQR(2)", "20 END"], "-1.414"),

    # ---- The silent class that remains. Each reads R0:R1, which a
    # ---- float does not write, so it acts on whatever the integer
    # ---- registers last held and says nothing. Pinned at the wrong
    # ---- answer deliberately: these are tripwires, and a failure here
    # ---- most likely means someone closed the gap. See D63.

    # Should be 65, or an error. POKE reads a stale register instead.
    ("POKE of a float stores a stale integer",
     ["10 X# = FLT(65)", "20 POKE 700, X#",
      "30 PRINT PEEK(700)", "40 END"], "2"),

    # Should run three times. The limit reads as 1, so the body runs once.
    ("FOR to a float limit runs once",
     ["10 X# = FLT(3)", "20 FOR I = 1 TO X#",
      "30 PRINT I", "40 NEXT", "50 END"], "1"),

    # No float arrays: DIM accepts the name and makes an ordinary
    # two-byte-per-element integer array called "A#(".
    ("DIM of a float array is accepted and is not one",
     ["10 DIM A#(4)", "20 PRINT 5", "30 END"], "5"),

    # The one that fails loudly, and the only one that does: there is no
    # decimal point in the tokeniser, so `1.5` is `1` and then rubbish.
    ("a float literal is a syntax error",
     ["10 PRINT 1.5", "20 END"], "?SYNTAX IN 10"),

    # ---- ABS and SGN. ABS keeps the type, SGN always answers an
    # ---- integer, so the pair is checked on both argument types and
    # ---- on zero, where a sign byte could invent one.
    ("ABS of a negative integer stays an integer",
     ["10 PRINT ABS(0 - 5)", "20 END"], "5"),
    ("ABS of a positive integer is unchanged",
     ["10 PRINT ABS(5)", "20 END"], "5"),
    ("ABS of zero",
     ["10 PRINT ABS(0)", "20 END"], "0"),
    ("ABS of a negative float keeps the fraction",
     ["10 X# = FLT(0) - FLT(7)", "20 X# = X# / FLT(2)",
      "30 PRINT ABS(X#)", "40 END"], "3.5"),

    # ---- Precedence across a promotion. `mulrest` is the continuation
    # ---- the + and - arms call to bind `b * c` before adding it, and
    # ---- while it was integer-only the multiply was silently dropped:
    # ---- FLT(1) + FLT(7)/FLT(2) gave 8, not 4.5. The integer pair is
    # ---- here so a regression cannot hide by breaking both.
    ("a divide binds tighter than a minus, in floats",
     ["10 PRINT FLT(0) - FLT(7) / FLT(2)", "20 END"], "-3.5"),
    ("and tighter than a plus",
     ["10 PRINT FLT(1) + FLT(7) / FLT(2)", "20 END"], "4.5"),
    ("a multiply binds tighter than a plus, in floats",
     ["10 PRINT FLT(1) + FLT(3) * FLT(2)", "20 END"], "7"),
    ("the same in integers, which never broke",
     ["10 PRINT 1 + 6 / 2", "20 END"], "4"),
    ("a float multiply after a minus",
     ["10 PRINT FLT(10) - FLT(3) * FLT(2)", "20 END"], "4"),
    ("ABS of a float stays a float, so it still divides",
     ["10 X# = FLT(0) - FLT(7)", "20 PRINT ABS(X#) / FLT(2)",
      "30 END"], "3.5"),
    ("SGN of a negative integer",
     ["10 PRINT SGN(0 - 9)", "20 END"], "-1"),
    ("SGN of a positive integer",
     ["10 PRINT SGN(9)", "20 END"], "1"),
    ("SGN of zero is zero, not a sign",
     ["10 PRINT SGN(0)", "20 END"], "0"),
    ("SGN of a negative float",
     ["10 X# = FLT(0) - SQR(2)", "20 PRINT SGN(X#)", "30 END"], "-1"),
    ("SGN of a positive float",
     ["10 PRINT SGN(SQR(2))", "20 END"], "1"),
    ("SGN of float zero",
     ["10 X# = FLT(0)", "20 PRINT SGN(X#)", "30 END"], "0"),
    # SGN answers an integer even for a float, which is the point: it
    # has to be usable where a float is not.
    ("SGN of a float is an integer, so POKE accepts it",
     ["10 X# = FLT(0) - SQR(2)", "20 POKE 700, SGN(X#) + 66",
      "30 PRINT PEEK(700)", "40 END"], "65"),

    # ---- Nesting. MAXEXPR is 24 but the float frame stack is 7 deep,
    # ---- so the frame stack is what a deep expression hits first.
    ("nesting within the frame stack is fine",
     ["10 PRINT 1+(1+(1+(1+(1+1))))", "20 END"], "6"),
    # Eight pending operators against seven frames. It refuses -- and
    # prints rubbish on the way, because PRINT has already been handed
    # a value by the time `stmt` looks at ERR. Ugly, and acceptable:
    # the error is loud, the line is abandoned, and the *session*
    # survives, which is what fstack() below actually guards.
    ("past the frame stack it refuses",
     ["10 PRINT 1+(1+(1+(1+(1+(1+(1+(1+1)))))))", "20 END"],
     "?COMPLEX IN 10"),

    # ---- Getting a fraction out of two integer literals. **Declaring
    # ---- the destination is not enough** -- the right-hand side is a
    # ---- complete expression, evaluated before the assignment sees
    # ---- it, so `X# = 1 / 4` divides in integers and promotes the 0.
    # ---- One *operand* has to be a float when the operator runs.
    ("declaring the target float does not make the divide one",
     ["10 X# = 1 / 4", "20 PRINT X#", "30 END"], "0"),
    ("promoting either operand does",
     ["10 X# = 1 / FLT(4)", "20 PRINT X#", "30 END"], "0.25"),
    ("either one, not just the right",
     ["10 PRINT FLT(1) / 4", "20 END"], "0.25"),
    # Once a float is in a variable it carries its own type, so the
    # FLT() is needed once rather than at every use.
    ("a float variable promotes the divide by itself",
     ["10 X# = 1", "20 PRINT X# / 4", "30 END"], "0.25"),
    ("and accumulates without another FLT",
     ["10 X# = 1", "20 X# = X# / 4", "30 PRINT X#", "40 END"], "0.25"),

    # ---- AND/OR bind looser than the relationals -- BBC's order, and
    # ---- Microsoft's (OPTAB: relationals 100, AND 80, OR 70). So the
    # ---- common idiom needs no parentheses. The whole truth table,
    # ---- because a precedence error here shows up in only one corner.
    ("AND of two true relations",
     ["10 A = 1", "20 B = 1", "30 IF A > 0 AND B > 0 THEN PRINT 7",
      "40 PRINT 9", "50 END"], "7"),
    ("AND with the right false",
     ["10 A = 1", "20 B = 0", "30 IF A > 0 AND B > 0 THEN PRINT 7",
      "40 PRINT 9", "50 END"], "9"),
    ("AND with the left false",
     ["10 A = 0", "20 B = 1", "30 IF A > 0 AND B > 0 THEN PRINT 7",
      "40 PRINT 9", "50 END"], "9"),
    ("OR with one true",
     ["10 A = 1", "20 B = 0", "30 IF A > 0 OR B > 0 THEN PRINT 7",
      "40 PRINT 9", "50 END"], "7"),
    ("OR with neither",
     ["10 A = 0", "20 B = 0", "30 IF A > 0 OR B > 0 THEN PRINT 7",
      "40 PRINT 9", "50 END"], "9"),

    # ---- Power, and its precedence. Verified against Microsoft's own
    # ---- 6502 source: OPTAB gives `^` 127, negation 125, `*` 123, and
    # ---- FRMEVL compares the pending precedence with BCS -- greater
    # ---- *or equal* applies the pending operator, so equal binds left.
    # ---- COOL8 matches on both counts.
    # (2^3)^2 = 64, not 2^(3^2) = 512. 63.96 rather than 64 is exp/log,
    # compounding across two of them, which is the honest argument
    # against chaining `^` at all.
    ("`^` is left-associative, as in MS BASIC, and the error compounds",
     ["10 PRINT 2 ^ 3 ^ 2", "20 END"], "63.96"),
    ("a power binds tighter than a binary minus",   # 0 - 4, via exp/log
     ["10 PRINT 0 - 2 ^ 2", "20 END"], "-3.999"),
    # -x^2 is -(x^2): the exponent belongs to the x and the sign to the
    # result, which is what the notation means and what MS BASIC does.
    ("a power binds tighter than a leading minus",
     ["10 A = 2", "20 PRINT -A ^ 2", "30 END"], "-3.999"),
    ("but a leading minus still binds tighter than a multiply",
     ["10 A = 2", "20 PRINT -A * 3", "30 END"], "-6"),
    ("and the right operand of a multiply takes its power first",
     ["10 PRINT 2 * 3 ^ 2", "20 END"], "17.99"),
    ("a parenthesised negative base is still the other thing",
     ["10 A = 2", "20 PRINT (0 - A) ^ 2", "30 END"], "-2"),
    # A negative base cannot go through exp(y ln x): flog refuses and
    # hands back its argument, so (-2)^2 is -2 rather than 4. Silent,
    # and now much harder to reach by accident -- it took a written
    # parenthesis above, where -A^2 used to land on it.
    ("a negative base returns the base, silently",
     ["10 X# = FLT(0) - FLT(2)", "20 PRINT X# ^ FLT(2)", "30 END"], "-2"),

    # ---- Range and division.
    ("INT of a float past 16 bits saturates rather than wrapping",
     ["10 X# = FLT(30000) * FLT(30000)", "20 PRINT INT(X#)",
      "30 END"], "32767"),
    ("a big float prints in exponent form, at four digits",
     ["10 PRINT FLT(30000) * FLT(30000)", "20 END"], "8.999E+08"),
    ("integer divide by zero errors",
     ["10 PRINT 1 / 0", "20 END"], "?DIV BY 0 IN 10"),
    ("MOD by zero errors the same way",
     ["10 PRINT 5 MOD 0", "20 END"], "?DIV BY 0 IN 10"),
    ("and a float divide by zero now errors too, not silently",
     ["10 PRINT FLT(1) / FLT(0)", "20 END"], "?DIV BY 0 IN 10"),

    # ---- Statements and strings at their edges.
    # The body runs once even though the limit is already passed: the
    # test is at NEXT, which is what MS BASIC does too.
    ("a backwards FOR still runs its body once",
     ["10 FOR I = 5 TO 1", "20 PRINT 8", "30 NEXT", "40 END"], "8"),
    ("MID$ past the end is empty, not an error",
     ['10 PRINT MID$("ABC", 5, 1)', "20 PRINT 8", "30 END"], "8"),
    ("LEFT$ past the end clamps",
     ['10 PRINT LEFT$("AB", 10)', "20 END"], "AB"),
    ("a subscript past DIM errors",
     ["10 DIM A(3)", "20 A(5) = 1", "30 PRINT 8", "40 END"],
     "?INDEX IN 20"),
    ("an unassigned float reads as zero",
     ["10 PRINT Q#", "20 END"], "0"),
    # `rhs` evaluates a whole erel, so a chain folds right to left:
    # 1 < (2 < 3). Not meaningful in any BASIC of the era; pinned so
    # the associativity is at least written down.
    ("a chained relational folds right to left",
     ["10 IF 1 < 2 < 3 THEN PRINT 7", "20 PRINT 9", "30 END"], "9"),

    # ---- Text and floats, in both directions. Neither works, and the
    # ---- reasons are not the same one.
    ("VAL of an integer string is fine",
     ['10 PRINT VAL("3")', "20 END"], "3"),
    ("VAL of a negative integer string",
     ['10 PRINT VAL("-7")', "20 END"], "-7"),
    ("VAL of nonsense is zero, not an error",
     ['10 PRINT VAL("ABC")', "20 END"], "0"),
    # **VAL stops at the point.** No error, no float -- "3.5" is 3, and
    # assigning it to a float variable promotes the 3. There is no
    # decimal parser anywhere in the machine, which is the same missing
    # piece as the float literal and INPUT of a float.
    ("VAL truncates at the decimal point, silently",
     ['10 PRINT VAL("3.5")', "20 END"], "3"),
    ("and assigning that to a float promotes the truncation",
     ['10 X# = VAL("3.5")', "20 PRINT X#", "30 END"], "3"),
    # ---- STR$ of a float works, and shares PRINT's renderer, so the
    # ---- two can never disagree about a value. It appends rather than
    # ---- assigns, which is what concatenation needs.
    ("STR$ of a float renders it",
     ["10 X# = FLT(7) / FLT(2)", "20 PRINT STR$(X#)", "30 END"], "3.5"),
    ("and concatenates, rather than replacing the accumulator",
     ["10 X# = FLT(7) / FLT(2)", '20 PRINT "N=" + STR$(X#) + "!"',
      "30 END"], "N=3.5!"),
    ("STR$ of a negative float keeps the sign",
     ["10 X# = FLT(0) - FLT(7) / FLT(2)", "20 PRINT STR$(X#)",
      "30 END"], "-3.5"),
    ("STR$ agrees with PRINT on the same value",
     ["10 X# = SQR(2)", "20 PRINT STR$(X#)", "30 END"], "1.414"),
    ("STR$ of an integer is unchanged",
     ['10 PRINT STR$(42) + "!"', "20 END"], "42!"),
    ("LEN of a rendered float, so the length is right too",
     ["10 X# = FLT(7) / FLT(2)", "20 PRINT LEN(STR$(X#))", "30 END"], "3"),

    # ---- Domain errors, and the surprising part: fp.asm *detects*
    # ---- every one and sets carry -- the jump table promises "fsqrt C
    # ---- set if negative", "flog C set if not positive" -- and the
    # ---- bindings in fpbas.asm never test it. The library knows and
    # ---- the language throws the knowledge away, returning the
    # ---- argument. Only fdiv's is wired up, because leaving that one
    # ---- silent made floats disagree with integers about `/ 0`.
    # ---- Pinned: if one starts erroring, a binding grew a check.
    ("LOG of a negative returns the argument, silently",
     ["10 X# = FLT(0) - FLT(4)", "20 PRINT LOG(X#)", "30 END"], "-4"),
    ("SQR of a negative does the same",
     ["10 X# = FLT(0) - FLT(9)", "20 PRINT SQR(X#)", "30 END"], "-9"),
    # Both integers must still be integers -- 7/2 is 3, not 3.5.
    ("two integers keep the integer path", ["10 PRINT 7 / 2", "20 END"],
     "3"),

    # Two arithmetic edges that are surprising, documented in
    # docs/13-basic.md sections 2 and 8, and would regress silently.
    #
    # `>>` is a *logical* shift in a language whose values are signed
    # everywhere else: SHR/ROR shifts a zero into the top, so -8 >> 1 is
    # 32764 and not -4. Anyone "fixing" that to an arithmetic shift
    # changes the language, and this is where they find out.
    ("`>>` is logical, not arithmetic",
     ["10 PRINT -8 >> 1", "20 END"], "32764"),

    # INT is the float-to-integer crossing now, not 8.8's shift ([D63]).
    # An integer comes back unchanged -- INT(7) is 7, where the old shift
    # made it 0 -- and a float floors, which is BBC BASIC's rule and the
    # right one for motion: equal-width cells give a constant velocity
    # constant pixel steps.
    ("INT leaves an integer alone", ["10 PRINT INT(7)", "20 END"], "7"),
    ("INT of a positive float", ["10 PRINT INT(SQR(2))", "20 END"], "1"),
    ("INT floors a negative float towards minus infinity",
     ["10 PRINT INT(0 - SQR(2))", "20 END"], "-2"),

    # Comments. The tokeniser copies both forms verbatim to the end of
    # the line (sw/basic.bas tokenise), so what is stored begins with a
    # character below $80 -- which is exactly what `stmt` routes to
    # h_let. A comment that reaches the interpreter must be *skipped*,
    # not parsed as an assignment, and the punctuation cases are the
    # ones that decide it: `=` makes the line look like an assignment
    # and `-` and `*` like an expression, so a handler that merely
    # tolerates `REM HELLO` still stops on `REM A = B`.
    ("an empty REM is skipped",
     ["10 REM", "20 PRINT 1", "30 END"], "1"),

    ("REM with words is skipped",
     ["10 REM HELLO WORLD", "20 PRINT 1", "30 END"], "1"),

    ("REM full of asterisks is skipped",
     ["10 REM ********", "20 PRINT 1", "30 END"], "1"),

    ("REM containing = is skipped, not assigned",
     ["10 REM A = B", "20 PRINT 1", "30 END"], "1"),

    ("REM containing dashes is skipped",
     ["10 REM ---- SECTION ----", "20 PRINT 1", "30 END"], "1"),

    ("an apostrophe comment is skipped",
     ["10 ' A = B ****", "20 PRINT 1", "30 END"], "1"),

    ("a comment between statements does not break the walk",
     ["10 A = 6", "20 REM SIX", "30 A = A * 7", "40 ' SEVEN",
      "50 PRINT A", "60 END"], "42"),

    # The comment is stored as a token plus verbatim text, so LIST has
    # to put the keyword back and the text through untouched. A program
    # listing itself is the round trip end to end: typed, tokenised,
    # stored, detokenised.
    ("LIST gives a REM back exactly as it was typed",
     ["10 REM SIX * SEVEN = 42", "20 LIST", "30 END"],
     "10 REM SIX * SEVEN = 42"),

    ("FOR and NEXT",
     ["10 FOR I = 1 TO 5", "20 S = S + I", "30 NEXT I",
      "40 PRINT S", "50 END"], "15"),

    ("DO and LOOP UNTIL",
     ["10 DO", "20 N = N + 3", "30 LOOP UNTIL N = 12",
      "40 PRINT N", "50 END"], "12"),

    ("IF and ELSE",
     ["10 K = 5", "20 IF K > 3 THEN PRINT 111 ELSE PRINT 222",
      "30 END"], "111"),

    # DO WHILE and DO UNTIL test at the *top*, which means the second
    # iteration re-enters where the first one started. That re-entry
    # went through `stmt`, which dispatched the `WHILE` sitting after
    # the `DO` as though it were a statement -- and `sttab[$8A]` is
    # `bad`. So the loop ran exactly once and then said ?SYNTAX ERROR,
    # and nothing here caught it because every case used the bottom
    # form. Both ends, both keywords, and a nest, from now on.
    ("DO WHILE, which is tested on re-entry and not just once",
     ["10 A = 0", "20 DO WHILE A < 10", "30 A = A + 1", "40 LOOP",
      "50 PRINT A", "60 END"], "10"),

    ("DO UNTIL, the same at the top",
     ["10 A = 0", "20 DO UNTIL A = 10", "30 A = A + 1", "40 LOOP",
      "50 PRINT A", "60 END"], "10"),

    ("LOOP WHILE, the form that always worked",
     ["10 A = 0", "20 DO", "30 A = A + 1", "40 LOOP WHILE A < 10",
      "50 PRINT A", "60 END"], "10"),

    ("LOOP UNTIL",
     ["10 A = 0", "20 DO", "30 A = A + 1", "40 LOOP UNTIL A = 10",
      "50 PRINT A", "60 END"], "10"),

    ("a DO WHILE nested inside another",
     ["10 A = 0", "20 DO WHILE A < 2", "30 B = 0", "40 DO WHILE B < 5",
      "50 B = B + 1", "60 LOOP", "70 A = A + 1", "80 LOOP",
      "90 PRINT A * 5", "95 END"], "10"),

    # The language round-out.
    ("PRINT separators butt items and a trailing one holds the newline",
     ['10 PRINT 1; 2; "X"', "20 PRINT 3;", "30 PRINT 4", "40 END"], "34"),

    ("FOR counts down when STEP is negative",
     ["10 S = 0", "20 FOR I = 10 TO 1 STEP -2", "30 S = S + I",
      "40 NEXT I", "50 PRINT S", "60 END"], "30"),

    ("shifts, both directions, at the compiler's precedence",
     ["10 PRINT (5 << 4) + (256 >> 6)", "20 END"], "84"),

    ("DATA is read, RESTORE rewinds, minus signs survive",
     ["10 DATA 7, -3, 100", "20 READ A, B", "30 RESTORE", "40 READ C",
      "50 PRINT A + B + C", "60 END"], "11"),

    ("ON picks the nth target",
     ["10 ON 2 GOTO 40, 60", "20 PRINT 0", "30 END",
      "40 PRINT 40", "50 END", "60 PRINT 99", "70 END"], "99"),

    ("TILE writes the map entry where the mode 2 engine looks",
     ["10 TILE 3, 2, 65, 7", "20 PRINT VPEEK(262); VPEEK(263)",
      "30 END"], "657"),

    # CLG's fill is read back beside the glyph, and GTEXT's glyph comes
    # from a font row the program itself poked -- the stub seeds the
    # real font only on a flash boot, which this harness is not.
    ("CLG fills and GTEXT draws through the seeded font",
     ["10 MODE 4", "20 CLG 3", "30 VPOKE $FC08, $FF", "40 PITCH 0, 500",
      "50 GTEXT 0, 0, \"!\", 9", "60 PRINT VPEEK(0); VPEEK(200)",
      "70 END"], "15351"),

    # Graphics and sound. Every check that can be is made by the
    # machine itself: VPEEK reads back what PLOT and LINE drew through
    # the pixel port, so the whole path -- parse, eval, port, VRAM --
    # is in the assertion. The screen the editor prints on is mode 0 in
    # main RAM, so drawing in mode 4 never disturbs the row the answer
    # lands on -- and dorun's restore is itself under test here, since
    # reading that row back needs VID_BASE pointed at $8000 again.
    ("VPOKE and VPEEK round-trip the VRAM port",
     ["10 VPOKE $1234, 77", "20 PRINT VPEEK($1234)", "30 END"], "77"),

    ("RND stays in range and is not stuck",
     ["10 A = 0", "20 B = 1", "30 FOR I = 1 TO 20", "40 C = RND(10)",
      "50 IF C > 9 THEN B = 0", "60 IF C < 0 THEN B = 0",
      "70 A = A + C", "80 NEXT I", "90 IF A = 0 THEN B = 0",
      "95 PRINT B", "99 END"], "1"),

    ("TIMER advances across two VSYNCs",
     ["10 A = TIMER", "20 VSYNC", "30 VSYNC", "40 B = TIMER - A",
      "50 IF B >= 2 THEN PRINT 1", "60 END"], "1"),

    ("MODE 4 and PLOT put a pixel where VPEEK finds it",
     ["10 MODE 4", "20 PLOT 10, 3, 15", "30 A = VPEEK(3 * 160 + 5)",
      "40 IF A <> 0 THEN PRINT 1", "50 END"], "1"),

    ("SCROLL, PALETTE, SPRITE, SOUND, HLINE and LINE all execute",
     ["10 MODE 4", "20 SCROLL 0, 0", "30 PALETTE 17, $0F00",
      "40 SPRITE 0, 100, 50, 4, 64", "50 SOUND 0, 881, 0, 0",
      "60 HLINE 0, 0, 8, 3", "70 LINE 0, 0, 7, 7, 5",
      "80 A = VPEEK(3 * 160 + 1)", "90 IF A <> 0 THEN PRINT 1",
      "99 END"], "1"),

    # A shallow line, both directions. Slope 1 is the one case a broken
    # Bresenham gets right -- the e2-recomputed-mid-step bug walked every
    # line at slope 1 and never met the endpoint -- so the checks are an
    # endpoint off that diagonal and a clean pixel on it.
    ("LINE at a shallow slope terminates and meets its endpoint",
     ["10 MODE 4", "20 LINE 0, 0, 319, 100, 7",
      "30 A = VPEEK(100 * 160 + 159)", "40 B = VPEEK(150 * 160 + 75)",
      "50 LINE 0, 100, 319, 0, 7", "60 C = VPEEK(159)",
      "70 IF A <> 0 AND B = 0 AND C <> 0 THEN PRINT 1", "80 END"], "1"),

    ("a string, which needs the accumulator and the heap",
     ['10 A$ = "HELLO"', '20 B$ = A$ + " THERE"', "30 PRINT B$",
      "40 END"], "HELLO THERE"),

    ("the string functions",
     ['10 A$ = "ABCDEF"', '20 PRINT MID$(A$,3,2)', "30 END"], "CD"),

    ("an array",
     ["10 DIM V(4)", "20 V(2) = 99", "30 PRINT V(2)", "40 END"], "99"),

    ("a SUB, called and returned from",
     ["10 CALL SHOW", "20 GOTO 99", "30 SUB SHOW", "40 PRINT 7",
      "50 RETURN", "60 END SUB", "99 END"], "7"),

    ("division and MOD",
     ["10 PRINT 100 / 7", "20 END"], "14"),
]

# A fault has to name the line it happened on, which is what LREC is
# still holding when the interpreter stops.
ERRORS = [
    ("an undefined SUB names the line",
     ["10 A = 1", "20 CALL NOPE", "30 END"], "?CALL IN 20"),

    ("a subscript past the end names the line",
     ["10 DIM V(2)", "20 V(9) = 1", "30 END"], "?INDEX IN 20"),

    ("division by zero names the line",
     ["10 A = 1 / 0", "20 END"], "?DIV BY 0 IN 10"),
]


def breaks_out(code, syms):
    """Ctrl-C stops a program that would otherwise never stop.

    Nothing polls a device to make this work: the vertical blank
    interrupt takes the byte and sets a flag, and the interpreter reads
    that flag at its loop back-edges. That is the C64's arrangement --
    its jiffy IRQ sets the RUN/STOP flag and BASIC polls it -- and it is
    the only shape that can stop a *running* program, which by
    definition is not reading the keyboard.
    """
    M = B.Machine(code, syms)
    M.settle()
    for ln in ["10 A = A + 1", "20 GOTO 10", "30 END"]:
        M.cmd(ln)
    # `cmd` settles after typing, and a program that never ends
    # never settles -- so RUN goes straight to the machine and the
    # ticks are counted here. `M.m.type` feeds; `M.type` waits.
    M.type("\x1b[B" * 29, chunk=3)
    M.type("\x1b[H", chunk=3)
    M.m.type("RUN\r")
    # **One server-side run, not a Python tick loop.** This was
    # `for _ in range(1_500_000): M.m.tick()`: a round trip per
    # instruction across the machine's process boundary, which is the
    # one thing AGENTS.md says that boundary cannot afford. On its own
    # it was 90s of this suite's 101s, and it bought nothing the run
    # below does not -- nothing was being watched, the program was just
    # being let spin.
    #
    # **Six million cycles, not three.** The loop it replaced ran about
    # 1.5 M instructions, which is some 4.5 M cycles, and a rewrite
    # that leaves a test running the machine for *less* time than
    # before is a rewrite that quietly narrows what the test can catch.
    # This runs longer than the loop did and still costs milliseconds,
    # because the cost was never the machine -- it was the round trips.
    M.m.run(cycles=6_000_000)
    M.m.uart.feed(b"")
    M.settle(40_000_000)
    return M


def keyboard(code, syms):
    """INKEY and KEY, driven from the PS/2 port rather than the UART.

    Two questions and two answers, and the reason there are two of each:

    `INKEY` is the queue -- what was typed, each key once, in order.
    That is the C64's GET, and it cannot answer a game's question. A held
    key arrives once and then not again until auto-repeat, and only ever
    one key at a time, so left-and-fire is not expressible in it. `KEY(c)`
    reads the bitmap sw/kbd.asm keeps instead: is that key down *now*,
    asked of as many keys as you like.

    ## Why these programs never end

    A held key still produces its character, and that character sits in
    the ring until something reads it. So when a program ends and the
    editor comes back, the editor reads it -- and types it over the row
    the program just printed on. The first version of this test looked
    like KEY() returning FALSE and was nothing of the kind: the answer
    had been printed and then overwritten by the `a` of the held A key.

    That is worth knowing rather than working around. It is what the
    hardware does, it is what the C64 does with its own buffer, and a
    game that ends while the player is still holding a key will see
    exactly this. A program that does not want it can drain INKEY before
    it ends. These loop forever and are stopped with Ctrl-C, so the
    editor never gets a turn and the screen holds what was printed.
    """
    out = {}

    # ---- KEY: nothing, one key, then two at once
    M = B.Machine(code, syms)
    M.settle()
    for ln in ["10 DO", '20 IF KEY($1C) AND KEY($29) THEN PRINT "BOTH"',
               "30 LOOP"]:
        M.cmd(ln)
    M.m.type("RUN\r")
    M.m.run(cycles=4_000_000)
    out["none"] = M.m.shows("BOTH")
    M.m.scancode([0x1C])                        # A down, and stays down
    M.m.run(cycles=4_000_000)
    out["one"] = M.m.shows("BOTH")
    M.m.scancode([0x29])                        # space down as well
    M.m.run(cycles=4_000_000)
    out["both"] = M.m.shows("BOTH")
    kd = syms["kdown"]
    M.m.scancode([0xF0, 0x29])                  # space back up
    M.m.run(cycles=2_000_000)
    out["released"] = bytes(M.m.bus.mem[kd:kd + 16])

    # ---- INKEY: a character, a named key, and a lone Escape
    M = B.Machine(code, syms)
    M.settle()
    for ln in ["10 DO", "20 A = INKEY", "30 IF A <> 0 THEN PRINT A",
               "40 LOOP"]:
        M.cmd(ln)
    M.m.type("RUN\r")
    M.m.run(cycles=4_000_000)
    out["quiet"] = M.m.shows("90")
    M.m.key("Z")
    M.m.run(cycles=4_000_000)
    out["char"] = M.m.shows("90")               # ASCII Z
    M.m.key(["K_UP"])
    M.m.run(cycles=4_000_000)
    out["named"] = M.m.shows("256")             # K_UP
    M.m.type("\x1b")
    M.m.run(cycles=4_000_000)
    out["esc"] = M.m.shows("27")
    return out


def sprites(code, syms):
    """SPRITE, animated the way a game animates it: the pattern VPOKEd
    into VRAM, the descriptor rewritten once per VSYNC, one pixel per
    frame. The frame comes from the machine's own scanline renderer
    (rust/src/render.rs, derived from the RTL) over the session `fb`
    command -- the same renderer the window shows, so what this checks
    is the path a person actually sees, timing included.
    """
    out = {}
    M = B.Machine(code, syms, render=True)
    M.settle()
    # This harness boots no flash image, so the boot stub's palette
    # never ran and every entry is black -- the program states its own
    # colour, which puts PALETTE's visible effect under test as well.
    # Sprites live in raster space, undoubled: descriptor (x, 120) is
    # screen (x, 120) and eight pixels are eight pixels, whatever the
    # playfield mode is doing.
    for ln in ["10 MODE 4", "20 CLG 0", "25 PALETTE 14, $0FFF",
               "30 FOR J = 0 TO 31", "40 VPOKE 64000 + J, $EE",
               "50 NEXT J", "60 X = 20",
               "70 DO", "80 VSYNC", "90 SPRITE 0, X, 120, 2000, 64",
               "94 X = X + 1", "97 LOOP"]:
        M.cmd(ln)
    M.m.type("RUN\r")
    M.m.run(cycles=8_000_000)

    def find(frame):
        row = frame[124 * 640:125 * 640]
        bg = row[0]
        xs = [x for x, v in enumerate(row) if v != bg]
        return (xs[0], xs[-1]) if xs else None

    out["first"] = find(M.m.fb())
    M.m.run(cycles=4_000_000)
    out["later"] = find(M.m.fb())
    return out


def syscall(code, syms):
    """`SYS addr` runs machine code, which is D63's whole replacement.

    Removing the on-machine assembler took away the only route from
    BASIC to machine code. This is the route that replaced it, and it is
    what a loadable library is reached through -- so it is the one case
    that has to work or D62's float package is unreachable from a
    program. The blob is assembled on the host, which is now the only
    assembler there is.
    """
    blob, _ = H.assemble_text(
        "        .org $6000\n"
        "        MOV  R0,#7\n"
        "        ST   [$0040],R0\n"        # A, at VARS
        "        CLR  R0\n"
        "        ST   [$0041],R0\n"
        "        RET\n", "sysblob")
    M = B.Machine(code, syms)
    M.settle()
    M.m.bus.mem[0x6000:0x6000 + len(blob)] = blob
    for ln in ["10 SYS $6000", "20 PRINT A", "30 END"]:
        M.cmd(ln)
    M.cmd("RUN")
    M.settle()
    return M


def asmdump():
    """`python sim/test_run.py --asmdump` -- what an ASM block produced.

    Nothing in this tree had ever *executed* an ASM block: the only
    existing case proves one is stepped over. So when `CALL FOO` says
    `?CALL IN 10` there is no working example to diff against, and the
    question is the plainest one there is -- did the assembler run, and
    where did it put the bytes. sim/test_asm.py says $7000.
    """
    code, syms = B.build()
    for label, prog in (
            # `FOO:` is cool8asm.py's syntax. **The on-machine assembler
            # takes BBC BASIC's `.FOO`** -- asm.asm's header says so and
            # `aisid` tests for '.'. A colon label is simply not a label
            # here, which is why the first attempt at this saw a block
            # assemble and no name appear.
            ("colon label, which is not one", ["10 PRINT FOO", "20 END",
             "900 ASM", "910 FOO:    RET", "990 END ASM"]),
            ("dot label", ["10 PRINT FOO", "20 END",
             "900 ASM", "910 .FOO", "920         RET", "990 END ASM"]),
            ("dot label, called", ["10 CALL FOO", "20 PRINT A", "30 END",
             "900 ASM", "910 .FOO", "920         MOV  R0,#7",
             "930         ST   [$0040],R0", "940         CLR  R0",
             "950         ST   [$0041],R0", "960         RET",
             "990 END ASM"])):
        M = run(code, syms, prog)
        print(f"  ---- {label}")
        for r in M.screen():
            if r.strip():
                print("      " + r.strip())

        # **Not $7000.** sw/basic.bas seeds the assembler's output
        # pointer from `progend` ($00DC) and reads back where it stopped
        # ($00DA), so a block's code lands straight after the program.
        # $7000 is sim/test_asm.py's own arrangement for testing the
        # assembler in isolation, and reading the system's behaviour out
        # of a test's scaffolding is how this went wrong the first time.
        def w(a):
            return M.m.bus.mem[a] | (M.m.bus.mem[a + 1] << 8)

        pend, aout, atop = w(0x0016), w(0x00DC), w(0x00DA)
        print(f"      progend ${pend:04X}   asm out ${aout:04X}"
              f"   asm end ${atop:04X}   nametab ${w(0x0027):04X}")
        for base in (pend & ~0xF, (pend & ~0xF) + 16):
            print("      $%04X  %s" % (
                base, bytes(M.m.bus.mem[base:base + 16]).hex(" ")))
        print()
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--asmdump":
        return asmdump()

    print("  I5 -- RUN, typed at the editor")
    print()
    code, syms = B.build()
    print(f"  basic.bin: {len(code):,} bytes")
    print()
    for what, lines, want in CASES:
        M = run(code, syms, lines)
        check(shows(M, want), what,
              "screen:\n      " + "\n      ".join(
                  r for r in M.screen() if r.strip()))
    print()
    for what, lines, want in ERRORS:
        M = run(code, syms, lines)
        check(shows(M, want), what,
              "screen:\n      " + "\n      ".join(
                  r for r in M.screen() if r.strip()))
    print()
    M = syscall(code, syms)
    check(shows(M, "7"), "SYS runs machine code at an address",
          " | ".join(r.strip() for r in M.screen() if r.strip()))

    print()
    M = breaks_out(code, syms)
    check(shows(M, "?BREAK IN 10") or shows(M, "?BREAK IN 20"),
          "Ctrl-C stops a program that never would",
          " | ".join(r.strip() for r in M.screen() if r.strip()))

    print()
    k = keyboard(code, syms)
    check(not k["none"], "KEY() is false with nothing held")
    check(not k["one"], "and still false with only one of the two down")
    check(k["both"], "TWO keys held at once -- what a queue cannot say")
    check(k["released"] == bytes([0, 0, 0, 0x10] + [0] * 12),
          "and releasing one leaves the other held",
          k["released"].hex(" "))
    check(not k["quiet"], "INKEY is 0 when nothing was typed")
    check(k["char"], "a key on the PS/2 port reaches a running program")
    check(k["named"], "and a cursor key arrives as K_UP, not as a keypad 8")
    check(k["esc"], "a lone Escape returns 27 rather than blocking")

    print()
    s = sprites(code, syms)
    check(s["first"] is not None, "an animated SPRITE is on the frame")
    if s["first"]:
        w = s["first"][1] - s["first"][0] + 1
        check(w == 8, "eight sprite pixels wide, raster space", "span %d" % w)
        check(s["later"] is not None and s["later"][0] > s["first"][0],
              "and VSYNC carries it rightward",
              "%s -> %s" % (s["first"], s["later"]))
        if s["later"]:
            d = s["later"][0] - s["first"][0]
            check(25 <= d <= 33, "at one pixel per frame -- VSYNC pacing",
                  "%d px in ~29 frames" % d)

    # INPUT blocks mid-run, so the harness types the answer while the
    # program is waiting -- which is the whole point of the command.
    M = B.Machine(code, syms)
    M.settle()
    for ln in ["10 INPUT A", "20 PRINT A + 1", "30 END"]:
        M.cmd(ln)
    M.m.type("RUN\r")
    M.m.run(cycles=3_000_000)
    M.m.type("41\r")
    M.m.run(cycles=8_000_000)
    check(shows(M, "42"), "INPUT takes a number typed at a waiting program",
          " | ".join(r.strip() for r in M.screen() if r.strip())[:100])

    print()
    fstack(code, syms)

    return H.report()


def fstack(code, syms):
    """Does overrunning the float frame stack poison the machine?

    `fsav` refuses past FSDEEP and returns *without pushing*, but every
    caller goes on to `fpair`, which pops unconditionally. So a too-deep
    expression pops one more frame than it pushed and FSP -- a byte --
    underflows. Nothing resets it: `idrct` clears EDEPTH, FDEPTH,
    DDEPTH, CDEPTH and NNAME, and FSP is not in that list. The question
    is whether one bad expression costs a line or the whole session.
    """
    M = B.Machine(code, syms)
    M.settle()
    for ln in ["10 PRINT 1+(1+(1+(1+(1+(1+(1+(1+1)))))))", "20 END"]:
        M.cmd(ln)
    M.m.type("RUN\r")
    M.m.run(cycles=8_000_000)
    check(shows(M, "?COMPLEX IN 10"), "a too-deep expression is refused",
          " | ".join(r.strip() for r in M.screen() if r.strip())[:160])

    # ...and now the same machine is asked to do trivial arithmetic.
    M.cmd("NEW")
    for ln in ["10 PRINT 2 + 2", "20 END"]:
        M.cmd(ln)
    M.m.type("RUN\r")
    M.m.run(cycles=8_000_000)
    check(shows(M, "4"),
          "and the machine can still add afterwards -- FSP recovered",
          " | ".join(r.strip() for r in M.screen() if r.strip())[:200])


if __name__ == "__main__":
    sys.exit(main())
