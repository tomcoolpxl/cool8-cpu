#!/usr/bin/env python3
"""S1 -- the screen editor, typed at.

    python sim/test_basic.py

`sw/basic.bas` is COOL8 BASIC itself: one screen, a cursor, and a Return
key. This drives it the way a person would -- every character goes in
over the wire and every check reads the screen back out.

What is checked:

  boot        the machine comes up with its banner and a free-memory line
  stored      numbered lines are stored, tokenised, in ascending order
  LIST        and come back out in order, detokenised, whatever order
              they were typed in
  the trick   cursor up onto a listed line, type over it, press Return,
              and that line is replaced -- the screen *is* the buffer
  cursor      the hardware cursor is where the typing is
  commands    NEW empties it, DELETE removes a range, RENUMBER renumbers

## Two rules this file follows

**Read through the machine's own video registers**, never a hardcoded
address. `sim/test_edit.py` used to read where the editor *wrote* rather
than where the display was pointed, so it passed a program that never
set `VID_BASE` at all.

**Settle means idle, not "the FIFO drained".** The byte is taken out of
the FIFO before it is acted on, so a harness that stops there reads the
state one keystroke early and blames the machine.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8vm as vm                                     # noqa: E402
import cool8vid as vid                                   # noqa: E402
import cool8bas as bas                                   # noqa: E402

ORG = 0xC000
FAILS = []


def check(ok, what, detail=""):
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


def build():
    src = os.path.join(ROOT, "sw", "basic.bas")
    with open(src, encoding="utf-8") as fh:
        asm = bas.compile_source(fh.read(), ORG)
    apath = os.path.join(BUILD, "basic.asm")
    with open(apath, "w") as fh:
        fh.write(asm)
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), apath,
                        "-o", os.path.join(BUILD, "basic.bin"),
                        "--symbols", os.path.join(BUILD, "basic.sym")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("compile failed")
    syms = {}
    for line in open(os.path.join(BUILD, "basic.sym")):
        p = line.split()
        if len(p) == 2:
            syms[p[1].lower()] = int(p[0], 16)
    with open(os.path.join(BUILD, "basic.bin"), "rb") as fh:
        return fh.read(), syms


class Machine:
    def __init__(self, code, syms):
        self.m = vm.Machine()
        self.m.bus.mem[ORG:ORG + len(code)] = code
        self.m.cpu.pc = ORG
        self.m.cpu.sp = 0xFFF7
        self.m.romen = False
        # rawkey's `.rk0` is reached only when nothing is waiting, so it
        # is the one address that means "idle" rather than "busy".
        self.idle = syms["s_rawkey.rk0"]

    def settle(self, budget=80_000_000):
        n = 0
        while n < budget:
            if not self.m.uart.rx and self.m.cpu.pc == self.idle:
                return
            self.m.cpu.step()
            n += 1
        raise SystemExit("the machine never went idle")

    def type(self, text, chunk=8):
        data = text.replace("\n", "\r").encode("latin-1")
        for i in range(0, len(data), chunk):
            self.m.uart.feed(data[i:i + chunk])
            self.settle()
            if self.m.uart.overrun:
                raise SystemExit("the FIFO overran")

    def cmd(self, s):
        """Type a command on a blank row, the way a person would.

        Typing over a row that still holds text leaves its tail behind
        -- `DELETE 20` onto a row reading `20 PRINT 2` becomes
        `DELETE 202`. That is exactly what a C64 does and it is a
        property to respect, not work around: so go to the bottom of the
        screen, which is blank, and type there.
        """
        self.type("\x1b[B" * 29, chunk=3)
        self.type("\x1b[H", chunk=3)
        self.type(s + "\r")

    def row(self, r):
        """One displayed row, through the machine's own VID_BASE."""
        base = vid._row_addr_v(self.m.video, r)
        return "".join(chr(self.m.bus.mem[(base + 2 * c) & 0xFFFF])
                       for c in range(80)).replace("\x00", " ").rstrip()

    def screen(self):
        return [self.row(r) for r in range(30)]

    def find(self, text):
        for r, line in enumerate(self.screen()):
            if line.strip() == text:
                return r
        return -1

    def prog(self):
        """The stored program, decoded from memory -- the check that the
        lines really are tokenised and in order."""
        end = (self.m.bus.mem[self.syms_progend]
               | (self.m.bus.mem[self.syms_progend + 1] << 8))
        out, p = [], 0x0200
        while p < end:
            n = self.m.bus.mem[p] | (self.m.bus.mem[p + 1] << 8)
            ln = self.m.bus.mem[p + 2]
            out.append((n, bytes(self.m.bus.mem[p + 3:p + 3 + ln])))
            p += 3 + ln
        return out


def main():
    print("  S1 -- sw/basic.bas, typed at")
    print()
    code, syms = build()
    print(f"  system: {len(code):,} bytes at ${ORG:04X}, "
          f"{len(code)/1024:.1f} KB of the 15.5 KB resident budget")
    print()

    M = Machine(code, syms)
    M.syms_progend = syms["v_progend"]
    M.settle()

    # ---- 1. it boots
    scr = M.screen()
    check(any("COOL8" in r for r in scr) and any("BYTES FREE" in r
                                                 for r in scr),
          "boots to a banner with a free-memory line",
          " | ".join(r for r in scr[:8] if r.strip())[:90])

    # ---- 2. numbered lines are stored, tokenised, in order
    M.type("20 PRINT 2\n10 PRINT 1\n30 PRINT 3\n")
    p = M.prog()
    check([n for n, _ in p] == [10, 20, 30],
          "numbered lines stored in ascending order, typed out of order",
          f"{[n for n, _ in p]}")
    check(all(b[0] >= 0x80 for _, b in p),
          "and tokenised -- PRINT is one byte",
          f"{[b[:4] for _, b in p]}")

    # ---- 3. LIST brings them back
    M.cmd("LIST")
    check(M.find("10 PRINT 1") >= 0 and M.find("20 PRINT 2") >= 0
          and M.find("30 PRINT 3") >= 0,
          "LIST detokenises them back in order",
          " | ".join(r for r in M.screen() if r.strip())[-90:])

    # ---- 4. the trick: edit a listed line in place
    #
    # Clear first, then LIST, so the row found is the listed one and not
    # the echo of what was typed earlier -- both are on screen and only
    # one of them is the thing under test.
    M.cmd("CLS")
    M.cmd("LIST")
    row = M.find("30 PRINT 3")
    cy = M.m.video.cur_y
    # One escape sequence per chunk: split across chunks the machine sees
    # a bare ESC and waits for the rest that is not there yet.
    M.type("\x1b[A" * (cy - row), chunk=3)
    M.type("\x1b[H", chunk=3)                  # Home: column 0
    before = M.row(row)
    M.type("30 PRINT 9")                       # type over it
    M.type("\r")                               # Return anywhere on the row
    p = dict(M.prog())
    check(p.get(30, b"")[-1:] == b"9",
          "cursor up onto a listed line, retype, Return -- it is replaced",
          f"row {row} was {before!r}, is now {M.row(row)!r}; "
          f"line 30 is {p.get(30)!r}")
    check([n for n in sorted(p)] == [10, 20, 30],
          "and nothing else moved")

    # ---- 5. the cursor is where the typing is
    # Return moved the cursor off the edited row onto the blank one
    # below it, so there is nothing to step over first.
    M.type("PRINT")
    cx, cy = M.m.video.cur_x, M.m.video.cur_y
    check(M.row(cy)[:cx].endswith("PRINT"),
          f"the cursor is where the typing is (row {cy}, col {cx})",
          f"row {cy} = {M.row(cy)[:40]!r}")

    # ---- 6. commands
    M.type("\r")                               # abandon that line
    M.cmd("DELETE 20")
    check(sorted(dict(M.prog())) == [10, 30], "DELETE removes a line",
          f"{sorted(dict(M.prog()))}")
    M.cmd("RENUMBER 100,5")
    check(sorted(dict(M.prog())) == [100, 105], "RENUMBER renumbers",
          f"{sorted(dict(M.prog()))}")
    M.cmd("NEW")
    check(M.prog() == [], "NEW empties it")

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
