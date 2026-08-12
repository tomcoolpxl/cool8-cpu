#!/usr/bin/env python3
"""The tokeniser module, driven directly.

    python sim/test_token.py

`sw/token.asm` turns typed text into the stored form and back. It is the
third module of the [D68] port and nothing calls it yet.

**It needs the interpreter behind it**, which the other module suites do
not: the number parser is `snum` and the float packer is `fstore`, both
of which live below the tokeniser in the design and above it in the
tree -- the call upward `sw/token.asm`'s header admits to and
ASM_MOVE_PLAN.md carries as owed. So this reuses `sim/test_interp.py`'s
harness verbatim rather than growing a second set of stubs for the same
twenty-three editor routines.

That reuse is the point of the arrangement: the stub block is one
string in one file, and a suite that needed its own copy would be the
private-copy trap AGENTS.md names.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402
import test_interp as TI                                 # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import memmap                                            # noqa: E402
import vocab                                             # noqa: E402

FAILS = H.FAILS

K = {n: t for t, n in vocab.keywords()}
T_LIT = K["?"]
K_FLT = K["!"]


def build():
    """A driver, the tokeniser, and the interpreter it leans on.

    `TI.HARNESS` opens with `.org $0200` and its own entry code, so the
    driver goes in front of it and the includes come along behind.
    """
    body = """
        .org $0200
main:   CALL tok_line
        HALT
        .include "token.asm"
"""
    # TI.HARNESS carries the stubs and the interpreter includes; drop
    # its own .org and entry sequence, which this driver replaces.
    stubs = TI.HARNESS.split("; ---- stubs standing in for sw/basic.bas")[1]
    return H.assemble_text(
        body + "\n; ---- stubs\n" + stubs, "tokenise", lower=True)


def tokenise(code, syms, text):
    """Put `text` in LBUF, run tok_line, hand back the token bytes."""
    m = H.session()
    m.bus.mem[0x200:0x200 + len(code)] = code
    m.cpu.pc = 0x200
    m.cpu.sp = memmap.RAMTOP
    m.romen = False
    lbuf = syms["lbuf"]
    for i, ch in enumerate(text):
        m.bus.mem[lbuf + i] = ord(ch)
    m.bus.mem[syms["llen"]] = len(text)
    if m.run(budget=20_000_000) != "halt":
        raise SystemExit("tok_line did not halt at $%04X" % m.cpu.pc)
    n = m.bus.mem[syms["tlen"]]
    return list(m.bus.mem[syms["tbuf"]:syms["tbuf"] + n])


def main():
    print("  the tokeniser, sw/token.asm")
    print()
    code, syms = build()

    def t(text):
        return tokenise(code, syms, text)

    check(t("PRINT") == [K["PRINT"]],
          "a keyword becomes one byte", "%s" % t("PRINT"))
    check(t("print") == [K["PRINT"]],
          "...and it is folded, so lower case is the same keyword")
    check(t("A") == [ord("A")],
          "a name that is not a keyword is copied")

    # The trap the compiled tokeniser carried a comment about: scanning
    # only letters split `x_end` into `x_` and `end`, and END is a
    # keyword, so the tail of a name became a token.
    check(t("X_END") == [ord(c) for c in "X_END"],
          "an identifier is scanned whole, so X_END does not end in a token",
          "%s" % t("X_END"))
    check(t("A$") == [ord("A"), ord("$")],
          "a trailing $ is part of the name, not the start of a hex literal")
    check(t("A#") == [ord("A"), ord("#")],
          "...and so is a trailing #, which is what keeps A and A# apart")

    # Numbers: the marker and two binary bytes, which is what stops an
    # interpreted FOR re-parsing decimal on every iteration.
    check(t("1000") == [T_LIT, 0xE8, 0x03],
          "a number is the marker and its value, low byte first",
          "%s" % t("1000"))
    check(t("$FE70") == [T_LIT, 0x70, 0xFE],
          "a bare $ is a hex literal", "%s" % t("$FE70"))

    # **The float literal**, which is the gap docs/13-basic.md section 8
    # calls the last loud one: PRINT 1.5 was ?SYNTAX because the
    # tokeniser had no decimal point.
    got = t("1.5")
    check(len(got) == 4 and got[0] == K_FLT,
          "1.5 is the float marker and three packed bytes", "%s" % got)
    check(t(".5")[0] == K_FLT,
          "...and a number may open with its point", "%s" % t(".5"))
    # `3.` is a float, not an integer -- the point switches `snum` into
    # counting mode whether or not a digit follows it, so `VAL("3.")` has
    # always answered a float too. Asserted here as the *inherited* rule
    # rather than a choice this module made: sharing the parser is what
    # makes a typed constant and a typed answer agree by construction,
    # which is the whole of [D66]'s "one text to number".
    check(t("3.")[0] == K_FLT,
          "a trailing point makes a float, as VAL('3.') does", "%s" % t("3."))

    # Quoted text and comments are copied whole.
    check(t('PRINT "FOR"') ==
          [K["PRINT"], ord(" ")] + [ord(c) for c in '"FOR"'],
          "a keyword inside quotes stays text", "%s" % t('PRINT "FOR"'))
    check(t("'FOR") == [ord(c) for c in "'FOR"],
          "a comment is copied verbatim, keyword and all")

    # REM takes the rest of the line, and it does so through the
    # generated flag rather than a case in the tokeniser.
    got = t("REM FOR")
    check(got == [K["REM"]] + [ord(c) for c in " FOR"],
          "REM is one token and the rest is verbatim -- via F_VERB",
          "%s" % got)

    check(t("") == [], "an empty line tokenises to nothing")
    check(t("10 PRINT 1") ==
          [T_LIT, 10, 0, ord(" "), K["PRINT"], ord(" "), T_LIT, 1, 0],
          "a whole line, spaces kept as the stored form requires",
          "%s" % t("10 PRINT 1"))

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
