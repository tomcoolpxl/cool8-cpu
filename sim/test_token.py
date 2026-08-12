#!/usr/bin/env python3
"""The tokeniser, driven inside the real system.

    python sim/test_token.py

`sw/token.asm` turns typed text into the stored form and back.

**No driver and no stubs.** This used to assemble the tokeniser in front
of a hand-written entry sequence and a block of stand-ins for everything
`sw/interp.asm` dragged in -- and then split that block on a comment
line to take half of it, because the tokeniser calls `snum` and `fstore`
which sit above it. There is one image now ([D68]): `H.fresh()` loads
it and `H.call()` pokes four bytes of `CALL tok_line / HALT`, so the
routine under test is the one that ships.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import vocab                                             # noqa: E402

FAILS = H.FAILS

K = {n: t for t, n in vocab.keywords()}
T_LIT = K["?"]
K_FLT = K["!"]


def t(text):
    """Put `text` in LBUF, run tok_line, hand back the token bytes."""
    m, syms = H.fresh()
    lbuf = syms["lbuf"]
    for i, ch in enumerate(text):
        m.bus.mem[lbuf + i] = ord(ch)
    m.bus.mem[syms["llen"]] = len(text)
    H.call(m, syms, "tok_line")
    n = m.bus.mem[syms["tlen"]]
    return list(m.bus.mem[syms["tbuf"]:syms["tbuf"] + n])

def main():
    print("  the tokeniser, sw/token.asm")
    print()
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
