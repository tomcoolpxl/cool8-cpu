#!/usr/bin/env python3
"""The disk commands, driven directly.

    python sim/test_fscmd.py

`sw/fscmd.asm` is the language's side of the filesystem: parse a name,
call the right `sw/fs.asm` primitive, say what went wrong. Seventh
module of the [D68] port.

**This is the least-exercised code in the image and the only code whose
bugs corrupt a volume**, which is why it gets a suite before the
switch-over rather than after it. `sim/test_fs.py` proves the format
against `tools/cool8disk.py`; this proves the layer above it -- that a
name typed at the editor becomes the right eleven-byte field, and that
SAVE followed by LOAD gives a program back byte for byte.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402
import test_interp as TI                                 # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import memmap                                            # noqa: E402
import cool8disk as disk                                 # noqa: E402

FAILS = H.FAILS

IMG = os.path.join(H.BUILD, "fscmd.img")
PROGBOT = 0x0200
DRIVER = 0x4000


def build(body):
    stubs = TI.HARNESS.split("; ---- stubs standing in for sw/basic.bas")[1]
    return H.assemble_text(
        "        .org $4000\nmain:\n" + body +
        "\ned_direct: RET\n"
        '        .include "fscmd.asm"\n; ---- stubs\n' + stubs,
        "fscmddrv", lower=True)


def volume():
    """A formatted volume with one file already on it."""
    if os.path.exists(IMG):
        os.remove(IMG)
    img = disk.Image(IMG, create=True)
    v = disk.Volume(img, 0)
    v.format("COOL8")
    img.save()
    return v


def run(body, line=None, prog=(), budget=60_000_000):
    """Assemble a driver, put `line` in LBUF, seed the store, run it."""
    code, syms = build(body)
    m = H.session()
    m.bus.mem[DRIVER:DRIVER + len(code)] = code
    m.cpu.pc = DRIVER
    m.cpu.sp = memmap.RAMTOP
    m.romen = False
    if line is not None:
        for i, ch in enumerate(line):
            m.bus.mem[syms["lbuf"] + i] = ord(ch)
        m.bus.mem[syms["llen"]] = len(line)
        m.bus.mem[syms["edip"]] = 0
    p = PROGBOT
    for n, toks in prog:
        m.bus.mem[p] = n & 0xFF
        m.bus.mem[p + 1] = n >> 8
        m.bus.mem[p + 2] = len(toks)
        for i, t in enumerate(toks):
            m.bus.mem[p + 3 + i] = t
        m.bus.mem[p + 3 + len(toks)] = 0
        p += 4 + len(toks)
    m.bus.mem[syms["progend"]] = p & 0xFF
    m.bus.mem[syms["progend"] + 1] = p >> 8
    if m.run(budget=budget) != "halt":
        raise SystemExit("the driver did not halt at $%04X" % m.cpu.pc)
    return m, syms


def name(m, syms):
    return "".join(chr(c) for c in
                   m.bus.mem[syms["fsname"]:syms["fsname"] + 11])


def main():
    print("  the disk commands, sw/fscmd.asm")
    print()

    # ---- parsing a name into the 8.3 field the directory holds.
    #
    # Every form the editor accepts, and the padding matters: the field
    # is compared byte for byte against what is on the volume, so a name
    # that pads differently simply never matches.
    for typed, want in (("HELLO", "HELLO   BAS"),
                        ('"HELLO"', "HELLO   BAS"),
                        ("HELLO.TXT", "HELLO   TXT"),
                        ('"MY FILE.TX"', "MY FILE TX "),
                        ("hello", "HELLO   BAS"),
                        ("A", "A       BAS")):
        m, syms = run("        CALL fsc_name\n        HALT\n", line=typed)
        check(name(m, syms) == want,
              "%-12s parses as %r" % (typed, want), repr(name(m, syms)))

    # An extension typed without a name is not a name.
    m, syms = run("        CALL fsc_name\n        HALT\n", line="")
    check(name(m, syms) == " " * 11,
          "an empty line is no name at all", repr(name(m, syms)))

    # A comma ends an unquoted name -- LOAD "N",100 has to split there.
    m, syms = run("        CALL fsc_name\n        HALT\n", line="AB,100")
    check(name(m, syms) == "AB      BAS",
          "a comma ends an unquoted name", repr(name(m, syms)))
    check(m.bus.mem[syms["edip"]] == 2,
          "...and the scan stops on it, so the number is still there",
          "edip=%d" % m.bus.mem[syms["edip"]])

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
