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
ORG = memmap.ORG
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

    def __init__(self, code, syms):
        self.m = vm.Machine()
        self.m.bus.mem[ORG:ORG + len(code)] = code
        self.m.cpu.pc = syms["main"]
        self.m.cpu.sp = 0x0200
        self.m.romen = False
        # What every real boot guarantees: the ROM or the flash stub has
        # cleared the screen to spaces. A row padded with NULs instead
        # stores as a bloated record.
        self.m.bus.mem[0x8000:0xA000] = b"\x20\x07" * 0x1000
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
    print(f"  image: {len(code):,} bytes at ${ORG:04X}, "
          f"{memmap.TOP - ORG - len(code):,} free")
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
