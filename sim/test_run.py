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

    ("8.8 fixed point: FMUL, FDIV and FIX agree",
     ["10 PRINT FMUL(640, 384); FDIV(768, 512); FIX(1000)",
      "20 END"], "9603843"),

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


def sprites(code, syms):
    """SPRITE, animated the way a game animates it: the pattern VPOKEd
    into VRAM, the descriptor rewritten once per VSYNC, one pixel per
    frame. The frame is rendered through cool8vid -- the renderer the
    window uses and the one test_video holds against the RTL -- so what
    this checks is the path a person actually sees, timing included.
    """
    import cool8vid as vid
    out = {}
    M = B.Machine(code, syms)
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

    out["first"] = find(vid.render_np(M.m).reshape(-1).tolist())
    M.m.run(cycles=4_000_000)
    out["later"] = find(vid.render_np(M.m).reshape(-1).tolist())
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
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
