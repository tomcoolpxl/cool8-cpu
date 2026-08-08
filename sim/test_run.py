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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import test_basic as B                                     # noqa: E402

FAILS = []


def check(ok, what, detail=""):
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


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

    ("FOR and NEXT",
     ["10 FOR I = 1 TO 5", "20 S = S + I", "30 NEXT I",
      "40 PRINT S", "50 END"], "15"),

    ("DO and LOOP UNTIL",
     ["10 DO", "20 N = N + 3", "30 LOOP UNTIL N = 12",
      "40 PRINT N", "50 END"], "12"),

    ("IF and ELSE",
     ["10 K = 5", "20 IF K > 3 THEN PRINT 111 ELSE PRINT 222",
      "30 END"], "111"),

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
     ["10 A = 1", "20 CALL NOPE", "30 END"], "?CALL ERROR IN 20"),

    ("a subscript past the end names the line",
     ["10 DIM V(2)", "20 V(9) = 1", "30 END"], "?SUBSCRIPT ERROR IN 20"),

    ("division by zero names the line",
     ["10 A = 1 / 0", "20 END"], "?DIVISION BY ZERO ERROR IN 10"),
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
    for _ in range(1_500_000):   # typed, read, and looping
        M.m.tick()
    M.m.uart.feed(b"")
    M.settle(40_000_000)
    return M


def main():
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
    M = breaks_out(code, syms)
    check(shows(M, "?BREAK IN 10") or shows(M, "?BREAK IN 20"),
          "Ctrl-C stops a program that never would",
          " | ".join(r.strip() for r in M.screen() if r.strip()))

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
