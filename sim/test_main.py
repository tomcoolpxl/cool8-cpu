#!/usr/bin/env python3
"""The whole system, on the new modules.

    python sim/test_main.py

`sw/main.asm` is the eighth and last module of the [D68] port, and the
switch-over: the entry point, the prompt loop and the interrupt
handlers, with every module underneath it and `sw/basic.bas` out of the
picture entirely.

**This is the first time the system runs on the new code**, and it is
the one step that could not be verified module by module. The other
seven suites drive a module in isolation with a driver in front of it;
this one boots the machine and types at it, which is the only thing that
proves the modules fit together.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import cool8rsvm as vm                                   # noqa: E402
import memmap                                            # noqa: E402
import vocab                                             # noqa: E402

FAILS = H.FAILS
# Read through `memmap` rather than bound here: the origin is derived
# and test_basic.build() may move it, so a copy taken at import is the
# address the image was linked at last time.
K = {n: t for t, n in vocab.keywords()}


def build():
    return H.assemble(os.path.join(H.SW, "main.asm"), name="mainimg",
                      lower=True, write=True)


class Machine:
    """The same arrangement sim/test_basic.py uses, on the new image.

    `in_raw.rk0` is the "nothing waiting" branch and so the one address
    that means idle rather than busy -- `s_rawkey.rk0` was its name
    while the editor was compiled BASIC.
    """

    def __init__(self, code, syms, render=False):
        # The font is render-only, and render=True *without* it draws a
        # blank frame in every mode -- which is how a pixel check comes
        # back unable to tell a working mode from a black screen.
        self.m = (vm.Machine(font=H.font(), render=True) if render
                  else vm.Machine())
        self.m.bus.mem[memmap.ORG:memmap.ORG + len(code)] = code
        self.m.cpu.pc = syms["main"]
        self.m.cpu.sp = 0x0200
        self.m.romen = False
        # What every real boot guarantees: the ROM or the flash stub has
        # cleared the map to spaces. A row padded with NULs stores as an
        # eighty-character record. **Wherever the image put the map** --
        # [D69] moved it above the user's region, and clearing $8000
        # cleared program space while the real map stayed zero.


        scrn, cs = syms["cscrn"], syms["cstride"]
        self.m.bus.mem[scrn:scrn + cs * 32] = b" " * (cs * 16)
        self.idle = syms["in_raw.rk0"]
        self.irhead = syms["irhead"]
        self.irtail = syms["irtail"]
        self.syms = syms

    def settle(self, budget=80_000_000):
        if not self.m.settle(self.idle, self.irhead, self.irtail, budget):
            raise SystemExit("the machine never went idle")

    def type(self, text, chunk=8):
        data = text.replace("\n", "\r").encode("latin-1")
        for i in range(0, len(data), chunk):
            self.m.uart.feed(data[i:i + chunk])
            self.settle()

    def cmd(self, s):
        """Type on a blank row, the way sim/test_basic.py does: Home,
        then down to the bottom, which is where nothing has been
        printed."""
        self.type("\x1b[H", chunk=3)
        self.type("\x1b[B" * 29, chunk=3)
        self.type(s + "\r")

    def row(self, r):
        return self.m.row(r)

    def screen(self):
        return [self.row(r) for r in range(32)]

    def shows(self, text):
        return any(r.strip() == text for r in self.screen())

    def lit(self):
        """Pixels that are not the background. Needs render=True."""
        return H.screen(self.m)


    def prog(self):
        end = (self.m.bus.mem[self.syms["progend"]]
               | (self.m.bus.mem[self.syms["progend"] + 1] << 8))
        out, p = [], 0x0200
        while p < end:
            n = self.m.bus.mem[p] | (self.m.bus.mem[p + 1] << 8)
            ln = self.m.bus.mem[p + 2]
            out.append((n, bytes(self.m.bus.mem[p + 3:p + 3 + ln])))
            p += 4 + ln
        return out


def main():
    print("  the whole system on the new modules, sw/main.asm")
    print()
    code, syms = build()
    print(f"  image: {len(code):,} bytes at ${memmap.ORG:04X}, "
          f"{memmap.TOP - memmap.ORG - len(code):,} free")
    print()

    M = Machine(code, syms)
    M.settle()
    check(M.m.cpu.pc == syms["in_raw.rk0"],
          "it boots and reaches the key loop", "pc=$%04X" % M.m.cpu.pc)

    M.type("HELLO\r")
    check(any("HELLO" in r for r in M.screen()),
          "a typed line appears on the screen",
          " | ".join(r.strip() for r in M.screen() if r.strip())[:100])

    M = Machine(code, syms)
    M.settle()
    M.type("20 PRINT 2\r10 PRINT 1\r30 PRINT 3\r")
    p = M.prog()
    check([n for n, _ in p] == [10, 20, 30],
          "numbered lines are stored in order, typed out of order",
          "%s" % [n for n, _ in p])
    check(all(b[0] >= 0x80 for _, b in p),
          "...and tokenised: PRINT is one byte", "%s" % [b[:3] for _, b in p])

    M.cmd("RUN")
    check(M.shows("1") and M.shows("2") and M.shows("3"),
          "RUN executes the stored program",
          " | ".join(r.strip() for r in M.screen() if r.strip())[:100])

    # Strings and arrays, which are the two things that need the heap.
    # sim/test_run.py reports both as garbage on the screen; these say
    # whether that is the system or that suite's reader, and they are
    # worth keeping either way -- nothing else here allocates.
    M = Machine(code, syms)
    M.settle()
    M.type('10 A$="HI"\r20 PRINT A$\r')
    M.cmd("RUN")
    check(M.shows("HI"), "a string variable survives a RUN",
          " | ".join(r.strip() for r in M.screen() if r.strip())[:100])

    # DIM on its own first: if a program with a DIM in it prints
    # nothing at all, the subscript checks below are asking the wrong
    # question.
    M = Machine(code, syms)
    M.settle()
    M.type("10 DIM A(3)\r20 PRINT 9\r")
    M.cmd("RUN")
    check(M.shows("9"), "a program with a DIM in it still runs",
          " | ".join(r.strip() for r in M.screen() if r.strip())[:90])

    M = Machine(code, syms)
    M.settle()
    M.type("10 DIM A(3)\r20 A(1) = 5\r30 PRINT A(1)\r")
    M.cmd("RUN")
    check(M.shows("5"), "DIM, a subscripted store, and reading it back",
          "stored %s\n    screen %s"
          % (M.prog(),
             " | ".join(r.strip() for r in M.screen() if r.strip())[:80]))

    # **Every mode, not the two that happen to be exercised.**
    #
    # `con_geom` is table-driven over GEOMTAB and the console keeps a
    # mirror per kind -- text, tiles, bitmap -- so a mode that is never
    # typed at is a branch that is never taken. Modes 0 and 1 were the
    # only ones any suite reached.
    for mode in range(7):
        M = Machine(code, syms, render=True)
        M.settle()
        M.cmd("MODE %d" % mode)
        M.cmd('PRINT "COOL8"')
        # **Whether it is visible is asked in sim/test_boot_basic.py**,
        # and it has to be: this suite pokes the image in and jumps to
        # `main`, so the boot stub never runs -- and the stub is what
        # seeds the palette and uploads the fonts into VRAM. A "can it
        # be seen" check here would be measuring what the harness left
        # out. What is this suite's to check is that the console
        # followed the mode, which is below.

        # ...and the console has to have been *told*, which is a
        # different thing and was the bug: characters reached the cell
        # map through whatever mirror was already set, so the text was
        # there and no glyph was ever drawn. Nothing rendered in modes
        # 2-5 and the map looked fine.
        #
        # GEOMTAB is read out of the image rather than copied here, so
        # this compares the console against its own table and cannot
        # drift when a mode is added.
        w = syms["geomw"]
        ent = syms["geomtab"] + w * (mode if mode < 7 else 0)
        want = list(M.m.bus.mem[ent:ent + w])
        # The tile mode is the one entry the table does not finish:
        # `con_tilefont` sets the cell height and the stride itself,
        # because the blitter expands four bits per pixel into a pattern
        # slot and the stride is the slot's, not the screen's. The table
        # carries zeros there rather than a number that would read as if
        # it meant something.
        if want[2] == 1:
            want[3], want[4] = 4, 8
        got = [M.m.bus.mem[syms[n]] for n in
               ("ccols", "crows", "ckind", "cbpc", "cfrow", "crpl",
                "ccursh")]
        check(got == want, "...and the console followed: MODE %d geometry"
              % mode, "console %s, GEOMTAB says %s" % (got, want))

        # **CCY is not CUR_Y.** The hardware counts a cursor row in 8
        # display lines wherever the doubler is on and 16 where it is
        # not, so the doubled modes need CCY doubled on the way out --
        # without it the cursor sat at CCY*8 while the text was at
        # CCY*16, half way up the screen with the text at the bottom.
        #
        # Read back through the register, which is the only thing that
        # can see the other half of the fault: CUR_Y was five bits, and
        # row 29 doubled is 58, which wrapped to 26. Both models
        # truncated identically, so cosim and test_vm agreed with each
        # other and were both wrong -- the shared assumption D74 says
        # gating two models against each other cannot catch.
        # `bus.read`, not `bus.mem` -- CUR_Y is a register in the video
        # block and RAM at that address is not it. Reading the wrong one
        # answers 0 in every mode, which looks like a broken cursor
        # rather than a broken test.
        # **Expected here, not read from CCURSH.** Checking CUR_Y against
        # `CCY << CCURSH` compares the console with itself: a table of
        # zeros -- which is what the bug was -- satisfies it in every
        # mode. These are the doubled modes, measured off the rendered
        # frame, and a wrong table now fails rather than agrees.
        ccy = M.m.bus.mem[syms["ccy"]]
        cury = M.m.bus.read(syms["cur_y"])
        want_cury = ccy * (2 if mode in (2, 4, 5) else 1)
        check(cury == want_cury,
              "...and MODE %d puts the cursor on the text's row" % mode,
              "CCY %d wants CUR_Y %d, reads %d" % (ccy, want_cury, cury))

    M = Machine(code, syms)
    M.settle()
    M.cmd("PRINT 6 * 7")
    check(M.shows("42"), "a direct line runs on the spot",
          " | ".join(r.strip() for r in M.screen() if r.strip())[:100])

    # The float literal, which the compiled tokeniser could not express.
    M = Machine(code, syms)
    M.settle()
    M.cmd("PRINT 1.5")
    check(M.shows("1.5"), "PRINT 1.5 -- the float literal, in source",
          " | ".join(r.strip() for r in M.screen() if r.strip())[:100])

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
