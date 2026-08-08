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
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
