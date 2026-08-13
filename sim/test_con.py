#!/usr/bin/env python3
"""The console module, driven directly.

    python sim/test_con.py

`sw/console.asm` is the first module of the [D68] port and nothing calls it
yet -- `sw/basic.bas` still owns the screen until `main.asm` takes the
entry point. So it gets a suite of its own now rather than at the
switch-over, for the reason ASM_MOVE_PLAN.md gives: writing thousands of
bytes of assembly on the strength of it *assembling* is how a port goes
wrong quietly.

This is `sim/test_fs.py`'s arrangement -- a driver assembled in front of
the module, run on a bare machine, and the result read back -- because
that is how a module with no callers gets exercised.

**The screen is read through the machine**, never at an address this
file computes: `m.row()` goes via the machine's own `VID_BASE`, which is
what catches a console that scrolled by moving the origin to somewhere
the display is not (docs/10-debugging.md section 3).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import memmap                                            # noqa: E402

FAILS = H.FAILS

# Mode 0, display enabled: the byte a program writes to VID_MODE.
M_TEXT80 = 0x80


def build(name, body):
    """A driver with sw/console.asm behind it.

    A leading global label because local labels are scoped to the last
    global one, so a driver whose first label is `.loop` has nowhere to
    hang it -- the same reason sim/test_fs.py opens with `main:`.
    """
    return H.assemble_text(
        "        .org $0200\nmain:\n" + body +
        '\n        .include "console.asm"\n', name, lower=True)


def run(code, mode=M_TEXT80, steps=20_000_000):
    """A machine with peripherals, the driver at $0200.

    The mode register is set from here rather than by the driver so a
    case can ask for a screen without repeating four instructions, and
    so `con_geom` is genuinely reading the hardware.
    """
    m = H.session()
    m.bus.mem[0x200:0x200 + len(code)] = code
    m.cpu.pc = 0x200
    m.cpu.sp = memmap.RAMTOP
    m.romen = False
    m.io_write(0x10, mode)                  # VID_MODE
    # **The preset carries the base and the stride.** Writing
    # VID_MODE loads VID_CTRL, VID_BASE, VID_STRIDE and the vertical
    # extent; these four writes then put them back to $8000 and 256
    # by hand, which was a private copy of the layout and stopped
    # being true the moment [D69] moved the map. Deleted, not
    # updated: the numbers belong to the machine.
    if m.run(budget=steps) != "halt":
        print("  the driver did not halt: pc $%04X" % m.cpu.pc)
        raise SystemExit("the driver did not halt")
    return m


def peek(m, syms, name):
    return m.bus.mem[syms[name.lower()]]


def main():
    print("  the console module, sw/console.asm")
    print()

    # ---- 1. geometry comes out of the hardware, not out of a guess.
    code, syms = build("con_geom", """
        CALL con_init
        HALT
""")
    m = run(code)
    check(peek(m, syms, "CCOLS") == 80 and peek(m, syms, "CROWS") == 30,
          "mode 0 reads back as 80x30",
          "cols=%d rows=%d" % (peek(m, syms, "CCOLS"),
                               peek(m, syms, "CROWS")))
    check(peek(m, syms, "CKIND") == 0, "...and as a text screen")
    check(peek(m, syms, "CRPL") == 1,
          "...where a logical line is one row of 80")

    m2 = run(code, mode=0x85)               # mode 5: 32x24, 4 bpp bitmap
    check(peek(m2, syms, "CCOLS") == 32 and peek(m2, syms, "CROWS") == 24,
          "mode 5 reads back as 32x24",
          "cols=%d rows=%d" % (peek(m2, syms, "CCOLS"),
                               peek(m2, syms, "CROWS")))
    check(peek(m2, syms, "CKIND") == 2, "...as a bitmap screen")
    check(peek(m2, syms, "CRPL") == 3,
          "...where a logical line spans three rows, so it is still 96")

    # An undecoded mode must not index off the end of the table: seven
    # entries, and the hardware nibble goes to fifteen.
    m3 = run(code, mode=0x8F)
    check(peek(m3, syms, "CCOLS") == 80 and peek(m3, syms, "CKIND") == 0,
          "an undecoded mode falls back to plain text, not off the table",
          "cols=%d kind=%d" % (peek(m3, syms, "CCOLS"),
                               peek(m3, syms, "CKIND")))

    # ---- 2. characters land where the display is looking.
    code, syms = build("con_emit", """
        CALL con_init
        LDW  X,#msg
        CALL con_puts
        HALT
msg:    .asciz "HELLO"
""")
    m = run(code)
    check(m.row(0).startswith("HELLO"),
          "con_puts puts a string on row 0", repr(m.row(0)[:16]))
    check(peek(m, syms, "CCX") == 5,
          "...and the cursor is past it", "cx=%d" % peek(m, syms, "CCX"))

    # ---- 3. cls really clears all 32 map rows, not just the visible 30.
    #
    # Rows 30 and 31 are what the scroll wraps through, so leaving them
    # dirty means a scroll drags old text up from under the screen. The
    # check is to dirty a row that is off-screen, clear, scroll to it,
    # and look.
    code, syms = build("con_wrap", """
        CALL con_init
        MOV  R0,#30             ; a row nobody can see
        MOV  R1,#0
        MOV  R2,#$58            ; 'X'
        MOV  R3,#$07
        CALL con_put
        CALL con_cls
        MOV  R3,#30
.s:     PUSH R3
        CALL con_scroll
        POP  R3
        SUB  R3,#1
        BNE  .s
        HALT
""")
    m = run(code)
    dirty = [r for r in range(30) if m.row(r).strip()]
    check(not dirty, "cls clears the two rows the scroll wraps through",
          "rows still holding text: %s" % dirty)

    # ---- 4. scrolling moves the origin, and the display follows it.
    code, syms = build("con_scroll1", """
        CALL con_init
        LDW  X,#top
        CALL con_puts
        CALL con_scroll
        HALT
top:    .asciz "TOP"
""")
    m = run(code)
    check(peek(m, syms, "CTOP") == 1,
          "one scroll advances the origin by one row",
          "ctop=%d" % peek(m, syms, "CTOP"))
    check(m.row(29).strip() == "",
          "...the row scrolled in is blank", repr(m.row(29)[:16]))
    # The text that was on row 0 is now on row -1, which is to say off
    # the top -- and reading through VID_BASE is the only way to see
    # that the origin really moved rather than the memory.
    check("TOP" not in m.row(0),
          "...and what was on row 0 has gone up off the screen",
          repr(m.row(0)[:16]))

    # ---- 5. the line-wrap link, which is what lets the editor read a
    # ---- wrapped line back as one line.
    code, syms = build("con_wrapln", """
        CALL con_init
        MOV  R3,#80             ; exactly one full row at 80 columns
.p:     PUSH R3
        MOV  R0,#$41            ; 'A'
        CALL con_emit
        POP  R3
        SUB  R3,#1
        BNE  .p
        HALT
""")
    m = run(code)
    check(peek(m, syms, "CCY") == 1 and peek(m, syms, "CCX") == 0,
          "eighty characters at 80 columns land the cursor on row 1",
          "cy=%d cx=%d" % (peek(m, syms, "CCY"), peek(m, syms, "CCX")))
    # CRPL is 1 in mode 0, so the eighty-first character starts a NEW
    # logical line rather than linking: the link table must stay clear.
    cont = m.bus.mem[syms["cont"] + 1]
    check(cont == 0,
          "...as a new logical line, not a continuation, at 80 columns",
          "cont[1]=%d" % cont)

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
