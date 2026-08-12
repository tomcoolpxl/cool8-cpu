#!/usr/bin/env python3
"""The screen editor, driven directly.

    python sim/test_edit.py

`sw/edit.asm` is the C64's arrangement generalised: the screen *is* the
document, a logical line may span several rows, and Return reads the
line back off the display rather than out of a buffer somebody kept.
Sixth module of the [D68] port.

**So every case here types into the cell map through the console and
reads the answer back out of it**, which is the only way to test a
module whose state is the screen.
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
PROGBOT = 0x0200


def build(body):
    stubs = TI.HARNESS.split("; ---- stubs standing in for sw/basic.bas")[1]
    return H.assemble_text(
        "        .org $4000\nmain:\n" + body +
        # `ed_direct` is main.asm's, and main.asm is the last module of
        # the port. Until it exists, running a line with no number is a
        # no-op here -- which is exactly what this suite wants, since
        # what it is testing is that the *decision* went that way.
        "\ned_direct: RET\n"
        '        .include "edit.asm"\n; ---- stubs\n' + stubs,
        "editdrv", lower=True)


def run(body, screen=(), cx=0, cy=0, mode=0x80, budget=20_000_000):
    """Paint `screen` into the cell map, put the cursor at (cy, cx), run.

    Each entry of `screen` is (row, text). The console is initialised
    first, so the geometry comes from the hardware the way it does on a
    real boot.
    """
    code, syms = build(body)
    m = H.session()
    m.bus.mem[0x4000:0x4000 + len(code)] = code
    m.cpu.pc = 0x4000
    m.cpu.sp = memmap.RAMTOP
    m.romen = False
    m.io_write(0x10, mode)                  # VID_MODE
    m.io_write(0x12, 0x00)
    m.io_write(0x13, 0x80)
    m.io_write(0x14, 0x00)
    m.io_write(0x15, 0x01)
    m.bus.mem[syms["progend"]] = PROGBOT & 0xFF
    m.bus.mem[syms["progend"] + 1] = PROGBOT >> 8
    if m.run(budget=budget) != "halt":
        raise SystemExit("the driver did not halt at $%04X" % m.cpu.pc)
    return m, syms


def lbuf(m, syms):
    n = m.bus.mem[syms["llen"]]
    return "".join(chr(c) for c in
                   m.bus.mem[syms["lbuf"]:syms["lbuf"] + n])


def paint(text, row=0, cx=0, cy=0, extra=""):
    """A driver that inits the console, types `text`, parks the cursor."""
    out = "        CALL con_init\n"
    for ch in text:
        out += "        MOV  R0,#$%02X\n        CALL con_emit\n" % ord(ch)
    out += "        MOV  R0,#%d\n        ST   [CCY],R0\n" % cy
    out += "        MOV  R0,#%d\n        ST   [CCX],R0\n" % cx
    return out + extra + "        HALT\n"


def main():
    print("  the screen editor, sw/edit.asm")
    print()

    # ---- reading a line back off the screen.
    m, syms = run(paint("PRINT 1", cy=0, cx=0,
                        extra="        CLR  R0\n        CALL ed_read\n"))
    check(lbuf(m, syms) == "PRINT 1",
          "a row reads back as the line that was typed on it",
          repr(lbuf(m, syms)))

    # Trailing blanks are trimmed: the rest of the row is spaces, and a
    # line that kept them would store eighty bytes for seven characters.
    check(m.bus.mem[syms["llen"]] == 7,
          "...with the trailing blanks trimmed",
          "llen=%d" % m.bus.mem[syms["llen"]])

    # ---- a wrapped line is ONE logical line.
    #
    # Eighty-five characters at 80 columns spill onto row 1, linked, and
    # Return must read all eighty-five back -- not the first row, and not
    # the second.
    # **Mode 1, 40 columns.** At 80 columns CRPL is 1, so the
    # eighty-first character starts a NEW logical line rather than
    # linking -- a line is eighty characters in every mode, and the
    # narrow ones reach that across two or three rows. So the wrap can
    # only be tested where wrapping happens.
    long = "A" * 45
    m, syms = run(paint(long, cy=1, cx=0,
                        extra="        MOV  R0,#1\n        CALL ed_read\n"),
                  mode=0x81)
    check(m.bus.mem[syms["llen"]] == 45,
          "at 40 columns a wrapped line reads back whole, from either row",
          "llen=%d" % m.bus.mem[syms["llen"]])
    check(lbuf(m, syms) == long, "...and it is the right forty-five")

    # ---- delete and insert, which go read / edit / write.
    m, syms = run(paint("ABCD", cy=0, cx=1,
                        extra="        CALL ed_del\n"
                              "        CLR  R0\n        CALL ed_read\n"))
    check(lbuf(m, syms) == "ACD",
          "delete takes the character under the cursor", repr(lbuf(m, syms)))

    m, syms = run(paint("ABCD", cy=0, cx=1,
                        extra="        CALL ed_ins\n"
                              "        CLR  R0\n        CALL ed_read\n"))
    check(lbuf(m, syms) == "A BCD",
          "insert opens a gap and pushes the tail right",
          repr(lbuf(m, syms)))

    # Backspace at column 0 of a row that does NOT continue the one above
    # must do nothing, or Return would join two unrelated lines.
    m, syms = run(paint("AB", cy=0, cx=0,
                        extra="        CALL ed_bs\n"
                              "        CLR  R0\n        CALL ed_read\n"))
    check(lbuf(m, syms) == "AB",
          "backspace at the very start of a line does nothing",
          repr(lbuf(m, syms)))

    # ---- Return: a numbered line is stored.
    m, syms = run(paint("10 PRINT", cy=0, cx=0,
                        extra="        CLR  R0\n        CALL ed_enter\n"))
    end = m.bus.mem[syms["progend"]] | (m.bus.mem[syms["progend"] + 1] << 8)
    check(end > PROGBOT, "Return on a numbered line stores it",
          "progend=$%04X" % end)
    if end > PROGBOT:
        n = m.bus.mem[PROGBOT] | (m.bus.mem[PROGBOT + 1] << 8)
        ln = m.bus.mem[PROGBOT + 2]
        toks = list(m.bus.mem[PROGBOT + 3:PROGBOT + 3 + ln])
        check(n == 10, "...under the number that was typed", "n=%d" % n)
        check(toks == [K["PRINT"]],
              "...tokenised, with the separating space dropped",
              "%s" % toks)

    # A line with no number is not stored: it runs. `ed_direct` is
    # stubbed here, so the check is that nothing reached the store.
    m, syms = run(paint("PRINT", cy=0, cx=0,
                        extra="        CLR  R0\n        CALL ed_enter\n"))
    end = m.bus.mem[syms["progend"]] | (m.bus.mem[syms["progend"] + 1] << 8)
    check(end == PROGBOT,
          "a line with no number is run, not stored", "progend=$%04X" % end)

    # A blank line does neither.
    m, syms = run("        CALL con_init\n        CLR  R0\n"
                  "        CALL ed_enter\n        HALT\n")
    end = m.bus.mem[syms["progend"]] | (m.bus.mem[syms["progend"] + 1] << 8)
    check(end == PROGBOT, "a blank line does nothing at all")

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
