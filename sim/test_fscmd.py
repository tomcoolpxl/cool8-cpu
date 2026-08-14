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
    """A snippet against the real image, with `line` in LBUF and a store."""
    m, syms = H.drive(body, at=DRIVER, sp=memmap.RAMTOP)
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


def stream(code, syms):
    """OPENIN / BGET / EOF / CLOSE, on a real volume ([D82]).

    **The whole point is that nothing is loaded.** `SAVE ... AT` writes
    the bytes and the stream reads them back one at a time out of the
    flash, so this is also the check that the two halves agree about
    where a file's data lives.
    """
    import test_basic as TB

    img = os.path.join(H.BUILD, "stream.img")
    if os.path.exists(img):
        os.remove(img)
    d = disk.Image(img, create=True)
    disk.Volume(d, 0).format("COOL8")
    d.save()

    def typed(*lines):
        M = TB.Machine(code, syms, flash=img)
        M.settle()
        M.cmd("CLS")
        for l in lines:
            M.cmd(l)
        return M

    def rows(M):
        return [r.strip() for r in M.screen() if r.strip()]

    put = ('POKE $3000,65', 'POKE $3001,66', 'POKE $3002,67',
           'SAVE "ABC" AT $3000, 3')

    M = typed(*put, 'OPENIN "ABC"', 'PRINT BGET; BGET; BGET')
    check(any(r == "656667" for r in rows(M)),
          "BGET streams a file back a byte at a time",
          " | ".join(rows(M))[-60:])

    # The stream shuts itself on the last byte, so a file read to its end
    # needs no CLOSE -- and EOF has to agree with that.
    M = typed(*put, 'OPENIN "ABC"', 'PRINT BGET; BGET; BGET', 'PRINT EOF')
    check(any(r == "-1" for r in rows(M)),
          "...and EOF is TRUE once it is spent",
          " | ".join(rows(M))[-60:])

    M = typed(*put, 'OPENIN "ABC"', 'PRINT EOF')
    check(any(r == "0" for r in rows(M)),
          "...and FALSE while bytes remain",
          " | ".join(rows(M))[-60:])

    # Past the end is -1, which no byte can be, so a program may test the
    # value instead of calling EOF for every byte.
    M = typed(*put, 'OPENIN "ABC"', 'PRINT BGET; BGET; BGET; BGET')
    check(any(r.endswith("-1") for r in rows(M)),
          "...and a read past the end is -1, not a wrapped byte",
          " | ".join(rows(M))[-60:])

    M = typed('PRINT BGET', 'PRINT EOF')
    check(rows(M).count("-1") >= 2,
          "with nothing open, BGET and EOF both answer -1",
          " | ".join(rows(M))[-60:])

    M = typed(*put, 'OPENIN "ABC"', 'CLOSE', 'PRINT EOF')
    check(any(r == "-1" for r in rows(M)),
          "CLOSE abandons a stream early",
          " | ".join(rows(M))[-60:])

    M = typed('CLOSE')
    check(not any("?" in r for r in rows(M)),
          "...and CLOSE on nothing is not an error",
          " | ".join(rows(M))[-60:])

    # ---- **A statement after a disk command on the same line.**
    #
    # [D86] made `:` legal and seventeen handlers ended in `cnext`,
    # which skips to the *next line* -- harmless while nothing could
    # follow them, and a silently dropped statement the moment one
    # could. Thirteen of them never moved the program and now end in
    # `JMP stmt`; SAVE..AT and LOAD..AT additionally had to save Y,
    # because fs_save and fs_load walk it over the data.
    M = typed('POKE $3000,96', 'SAVE "F.BIN" AT $3000, 1:PRINT 9')
    check(any(x == "9" for x in rows(M)),
          "a statement after SAVE..AT on one line still runs",
          " | ".join(rows(M))[-40:])

    M = typed('POKE $3000,96', 'SAVE "F.BIN" AT $3000, 1',
              'POKE $3000,0', 'LOAD "F.BIN" AT $3000:PRINT PEEK($3000)')
    check(any(x == "96" for x in rows(M)),
          "...and after LOAD..AT, which had spent Y on the data",
          " | ".join(rows(M))[-40:])

    for cmd in ("CLS", "FREE", "CLOSE", "DRIVE 0", "DIR", "COMPACT"):
        M = typed(cmd + ":PRINT 9")
        check(any(x == "9" for x in rows(M)),
              "...and after %s" % cmd, " | ".join(rows(M))[-40:])

    # ---- GET$: a loop around BGET, and nothing else.
    line = ('POKE $3000,72', 'POKE $3001,73', 'POKE $3002,13',
            'POKE $3003,79', 'POKE $3004,75', 'SAVE "L" AT $3000, 5')
    M = typed(*line, 'OPENIN "L"', 'PRINT GET$', 'PRINT GET$')
    r = rows(M)
    check("HI" in r and "OK" in r, "GET$ reads a line, without its CR",
          " | ".join(r)[-50:])

    # CR ends a line and LF is skipped rather than ending one, so CRLF
    # reads as two lines and not as four with empties between.
    crlf = ('POKE $3000,72', 'POKE $3001,73', 'POKE $3002,13',
            'POKE $3003,10', 'POKE $3004,79', 'POKE $3005,75',
            'SAVE "C" AT $3000, 6')
    M = typed(*crlf, 'OPENIN "C"', 'PRINT GET$', 'PRINT GET$')
    r = rows(M)
    check("HI" in r and "OK" in r, "...and CRLF is two lines, not four",
          " | ".join(r)[-50:])

    # It appends, like every string builtin, because the accumulator may
    # already hold the left of a concatenation.
    M = typed(*line, 'OPENIN "L"', 'PRINT "<" + GET$ + ">"')
    check(any(x == "<HI>" for x in rows(M)),
          "...and it appends, so it composes",
          " | ".join(rows(M))[-40:])

    M = typed(*line, 'OPENIN "L"', 'PRINT GET$', 'PRINT GET$',
              'PRINT LEN(GET$)')
    check(rows(M)[-1] == "0", "...past the end it is the empty string",
          " | ".join(rows(M))[-40:])

    M = typed('OPENIN "NOPE"')
    check(any("NO FILE" in r for r in rows(M)),
          "OPENIN of a missing file says so",
          " | ".join(rows(M))[-60:])

    # **RUN shuts the stream, and nothing below fscmd could do it.**
    # A stream opened in direct mode survived a RUN, so a program
    # inherited one it never opened and leaked the flash on every
    # re-run. The close sits in main.asm because prog.asm and
    # interp.asm are below this module and may not call upward ([D68]).
    M = typed(*put, 'OPENIN "ABC"', '10 PRINT 9', '20 END', 'RUN',
              'PRINT EOF')
    check(rows(M)[-1] == "-1", "RUN shuts an open stream",
          " | ".join(rows(M))[-60:])

    # The last byte shuts it, not the read after. This was written the
    # other way with a comment claiming otherwise, so a program that
    # read exactly its file and stopped held the flash open -- and the
    # comment was the only thing anyone would have checked.
    M = typed(*put, 'OPENIN "ABC"', 'PRINT BGET; BGET; BGET')
    check(M.m.bus.mem[syms["fropen"]] == 0,
          "...and the last byte shuts it, not the read after",
          "FROPEN reads %d" % M.m.bus.mem[syms["fropen"]])


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

    print()
    stream(*H.assemble(os.path.join(H.SW, "main.asm"),
                     name="mainimg", lower=True, write=True))

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
