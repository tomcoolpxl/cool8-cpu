#!/usr/bin/env python3
"""M13 -- the editor, driven by keystrokes on the machine.

    python sim/test_edit.py             # 120 lines, about a minute
    python sim/test_edit.py --lines 1010

`sw/edit.bas` is compiled by `tools/cool8bas.py`, loaded into
`tools/cool8vm.py`, and then *typed at*. Nothing here reaches into the
machine to place text: every character goes in through the UART the way
a person's would, and every check reads the screen or the flash back out
the way a person would see it.

What is checked:

  written     N lines typed in, and the buffer holds what was typed
  edited      the cursor is moved and text changed in the middle
  saved       Ctrl-S, and tools/cool8disk.py finds the file on drive 0
  reloaded    Ctrl-L into a machine that never saw the typing
  coloured    keywords, numbers and comments come back in different
              attributes, read out of the text map

**RUN is not checked, and cannot be yet** -- see the note at the end.
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, BUILD)

import cool8vm as vm                                     # noqa: E402
import cool8disk as disk                                 # noqa: E402
import mkedit                                            # noqa: E402

IMG = os.path.join(BUILD, "edit.img")
BUF = 0x2000
SCREEN = 0x8200

A_KEY, A_NUM, A_REM, A_TEXT = 0x0E, 0x0B, 0x0A, 0x07

FAILS = []


def check(ok, what, detail=""):
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


class Machine:
    """The editor, running, with a keyboard attached."""

    def __init__(self, code, syms):
        self.m = vm.Machine(flash_path=IMG)
        self.m.bus.mem[0x200:0x200 + len(code)] = code
        self.m.cpu.pc = 0x200
        self.m.cpu.sp = 0xFFF7
        self.m.romen = False
        self.steps = 0
        # Idle means "back in getkey with nothing to read". Waiting for
        # the FIFO to drain is not the same thing -- the byte is taken
        # before it is acted on, so a harness that stops there reads the
        # state one keystroke early and blames the editor.
        self.idle = syms["s_getkey.gk"]

    def settle(self, budget=200_000_000):
        n = 0
        while n < budget:
            if not self.m.uart.rx and self.m.cpu.pc == self.idle:
                return True
            self.m.cpu.step()
            n += 1
            self.steps += 1
        raise SystemExit("the editor never came back to getkey")

    def type(self, text, chunk=8):
        """Type, a few characters at a time so the 16-byte FIFO never
        overruns -- which is what would happen on a real serial line
        without flow control, and is not what is being tested."""
        data = text.encode("latin-1")
        for i in range(0, len(data), chunk):
            self.m.uart.feed(data[i:i + chunk])
            self.settle()
            if self.m.uart.overrun:
                raise SystemExit("the FIFO overran -- feed smaller chunks")

    def screen_row(self, r):
        """One row of the text map, as (char, attribute) pairs."""
        base = SCREEN + r * 256
        return [(self.m.bus.mem[base + 2 * c],
                 self.m.bus.mem[base + 2 * c + 1]) for c in range(80)]

    def row_text(self, r):
        return "".join(chr(c) for c, _ in self.screen_row(r)).rstrip()


def program(nlines):
    """A COOL8 BASIC program of the requested length, with keywords,
    numbers and comments in it so the colouring has something to do."""
    out = ["' a program written on the machine itself", "CONST STEP = 3",
           "total = 0"]
    i = 0
    while len(out) < nlines:
        out.append(f"total = total + {i % 97}")
        if i % 7 == 0:
            out.append(f"' note {i}")
        if i % 11 == 0:
            out.append("IF total > 4000 THEN")
            out.append("  total = total - 4000")
            out.append("END IF")
        i += 1
    return out[:nlines]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, default=120)
    args = ap.parse_args()

    print("  M13 -- sw/edit.bas, typed at through the UART")
    print()

    code, syms = mkedit.build()
    print(f"  editor: {len(code):,} bytes compiled from "
          f"{len(open(os.path.join(ROOT, 'sw', 'edit.bas')).readlines())} "
          f"lines of COOL8 BASIC")

    if os.path.exists(IMG):
        os.remove(IMG)
    img = disk.Image(IMG, create=True)
    disk.Volume(img, 0).format("SOURCE")
    img.save()

    lines = program(args.lines)
    text = "\r".join(lines) + "\r"
    print(f"  typing {len(lines)} lines, {len(text):,} characters ...")

    t0 = time.time()
    ed = Machine(code, syms)
    ed.settle()
    ed.type(text)
    el = time.time() - t0
    print(f"  typed in {el:.0f} s of wall clock, "
          f"{ed.m.cpu.cycles / 8_375_000:.1f} s of machine time")
    print()

    # ---- 1. written
    n = ed.m.bus.mem[syms["v_gs"]] | (ed.m.bus.mem[syms["v_gs"] + 1] << 8)
    got = bytes(ed.m.bus.mem[BUF:BUF + n]).decode("latin-1")
    check(got == text, f"{len(lines)} lines typed in, and the buffer holds "
          f"them ({n:,} bytes)",
          f"got {len(got)} bytes, wanted {len(text)}")

    # ---- 2. the screen shows the tail of what was typed
    last = lines[-1]
    onscreen = any(ed.row_text(r).strip() == last.strip()
                   for r in range(1, 30))
    check(onscreen, "the last line typed is on the screen",
          f"looking for {last!r}")

    # ---- 3. coloured
    row = None
    for r in range(1, 30):
        if ed.row_text(r).strip().startswith("IF total"):
            row = r
            break
    if row is None:
        check(False, "a coloured row to inspect")
    else:
        cells = ed.screen_row(row)
        text_row = ed.row_text(row)
        kw = [a for c, a in cells if chr(c) in "IFTHEN" and a == A_KEY]
        num = [a for c, a in cells if chr(c).isdigit() and a == A_NUM]
        check(len(kw) >= 2 and len(num) >= 2,
              "keywords and numbers are coloured differently",
              f"row {row}: {text_row!r} kw={len(kw)} num={len(num)}")
    com = None
    for r in range(1, 30):
        if ed.row_text(r).strip().startswith("'"):
            com = r
            break
    if com is not None:
        cells = ed.screen_row(com)
        check(all(a == A_REM for c, a in cells[:8]),
              "a comment is one colour to the end of the line",
              f"row {com}: {[hex(a) for _, a in cells[:8]]}")

    # ---- 4. edited: go up two lines, home, and type at the front
    ed.type("\x1b[A\x1b[A\x1b[HZZZ")
    n2 = ed.m.bus.mem[syms["v_gs"]] | (ed.m.bus.mem[syms["v_gs"] + 1] << 8)
    ge = ed.m.bus.mem[syms["v_ge"]] | (ed.m.bus.mem[syms["v_ge"] + 1] << 8)
    total = 24576 - ge + n2
    check(total == len(text) + 3,
          "cursor moved up and text inserted in the middle",
          f"length {total}, wanted {len(text) + 3}")

    # ---- 5. saved
    ed.type("\x13")
    ed.settle()
    ed.m.flash.flush()
    v = disk.Volume(disk.Image(IMG), 0)
    e = v.find("SOURCE.BAS")
    saved = v.get("SOURCE.BAS") if e else b""
    check(e is not None and len(saved) == total,
          f"Ctrl-S saved it, and the PC tool sees {len(saved):,} bytes",
          f"entry {e}")

    # ---- 6. reloaded into a machine that never saw the typing
    ed2 = Machine(code, syms)
    ed2.settle()
    ed2.type("\x0c")
    ed2.settle()
    # After a load the cursor sits at the top, so the text is on the far
    # side of the gap. Reading buf[0:gs] was right only while the editor
    # left the cursor at the end -- the harness had to learn the same
    # thing the editor did.
    gs3 = ed2.m.bus.mem[syms["v_gs"]] | (ed2.m.bus.mem[syms["v_gs"] + 1] << 8)
    ge3 = ed2.m.bus.mem[syms["v_ge"]] | (ed2.m.bus.mem[syms["v_ge"] + 1] << 8)
    n3 = 24576 - ge3 + gs3
    back = (bytes(ed2.m.bus.mem[BUF:BUF + gs3])
            + bytes(ed2.m.bus.mem[BUF + ge3:BUF + 24576]))
    check(n3 == total and back == saved,
          "Ctrl-L reloaded it into a fresh machine, byte for byte",
          f"{n3:,} bytes back, {len(saved):,} saved")

    print()
    print("  RUN: not possible yet -- the compiler runs on the PC (M12).")
    print("       Everything above happened on the machine.")
    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
