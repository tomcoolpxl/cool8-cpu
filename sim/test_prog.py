#!/usr/bin/env python3
"""The program store, driven directly.

    python sim/test_prog.py

`sw/prog.asm` holds the stored program: find a line, insert one, delete
a range, list it, renumber it. Fourth module of the [D68] port.

**This is where a bug corrupts the user's program rather than printing
something wrong**, so it is characterised harder than the others: every
insert case is checked by reading the whole store back and decoding it,
not by looking at one byte.

`RENUM` gets its own section because it has never worked: the compiled
version rewrote each line's own number and never looked inside the
tokens, so every `GOTO` in a renumbered program pointed at the wrong
line and nothing in the suite noticed.
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
T_LIT = K["?"]
PROGBOT = 0x0200


def build(body):
    stubs = TI.HARNESS.split("; ---- stubs standing in for sw/basic.bas")[1]
    return H.assemble_text(
        "        .org $4000\nmain:\n" + body +
        '\n        .include "prog.asm"\n; ---- stubs\n' + stubs,
        "progdrv", lower=True)


def machine(code, syms):
    m = H.session()
    m.bus.mem[0x200:0x200 + len(code)] = code
    m.cpu.pc = 0x200
    m.cpu.sp = memmap.RAMTOP
    m.romen = False
    # The store lives at $0200, which is where the driver is loaded, so
    # the driver is assembled to run from there and then moves the
    # program base out of its own way. Simpler: put the driver high.
    return m


def run(body, lines=(), budget=20_000_000):
    """Assemble a driver, seed the store with `lines`, run it.

    Each line is (number, [token bytes]).
    """
    code, syms = build(body)
    m = H.session()
    base = 0x4000                       # the driver, out of the store
    m.bus.mem[base:base + len(code)] = code
    m.cpu.pc = base
    m.cpu.sp = memmap.RAMTOP
    m.romen = False
    p = PROGBOT
    for n, toks in lines:
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


def store(m, syms):
    """The program, decoded: [(number, [tokens]), ...]."""
    end = m.bus.mem[syms["progend"]] | (m.bus.mem[syms["progend"] + 1] << 8)
    out, p = [], PROGBOT
    while p < end:
        n = m.bus.mem[p] | (m.bus.mem[p + 1] << 8)
        ln = m.bus.mem[p + 2]
        out.append((n, list(m.bus.mem[p + 3:p + 3 + ln])))
        p += 4 + ln
    return out


def lit(n):
    return [T_LIT, n & 0xFF, n >> 8]


def main():
    print("  the program store, sw/prog.asm")
    print()

    # ---- insert, in order, from any order of arrival.
    def put(n, toks):
        body = "        MOV  R3,#%d\n" % len(toks)
        body += "        LDW  X,#tb\n        LDW  Y,#%d\n" % 0
        # Fill TBUF from a table in the driver, then store.
        b = "".join("        MOV  R0,#$%02X\n        CALL tok_byte\n" % t
                    for t in toks)
        return ("        CLR  R0\n        ST   [TLEN],R0\n" + b +
                "        MOV  R0,#$%02X\n        MOV  R1,#$%02X\n"
                "        CALL prg_store\n        HALT\n" % (n & 0xFF, n >> 8))

    m, syms = run(put(20, [K["PRINT"]]),
                  [(10, [K["PRINT"]]), (30, [K["PRINT"]])])
    check([n for n, _ in store(m, syms)] == [10, 20, 30],
          "a line is inserted in order, not appended",
          "%s" % [n for n, _ in store(m, syms)])

    m, syms = run(put(10, [K["END"]]), [(10, [K["PRINT"]]), (20, [K["NEW"]])])
    got = store(m, syms)
    check(got == [(10, [K["END"]]), (20, [K["NEW"]])],
          "an existing line is replaced, and the one after it survives",
          "%s" % got)

    # A longer replacement moves the tail up; a shorter one moves it
    # down. The direction the copy walks has to follow or it eats itself.
    m, syms = run(put(10, [K["PRINT"], K["END"], K["NEW"]]),
                  [(10, [K["PRINT"]]), (20, [K["NEW"]])])
    got = store(m, syms)
    check(got == [(10, [K["PRINT"], K["END"], K["NEW"]]), (20, [K["NEW"]])],
          "a longer line grows the hole and the tail moves up", "%s" % got)

    m, syms = run(put(10, [K["END"]]),
                  [(10, [K["PRINT"], K["END"], K["NEW"]]), (20, [K["NEW"]])])
    got = store(m, syms)
    check(got == [(10, [K["END"]]), (20, [K["NEW"]])],
          "a shorter line shrinks it and the tail moves down", "%s" % got)

    # An empty TBUF is how typing a bare line number deletes a line.
    m, syms = run(put(20, []), [(10, [K["PRINT"]]), (20, [K["NEW"]]),
                                (30, [K["END"]])])
    check([n for n, _ in store(m, syms)] == [10, 30],
          "an empty line deletes the record",
          "%s" % [n for n, _ in store(m, syms)])

    # ---- delete a range.
    m, syms = run("""
        MOV  R0,#20
        CLR  R1
        MOV  R2,#40
        CLR  R3
        CALL prg_del
        HALT
""", [(10, [K["PRINT"]]), (20, [K["NEW"]]), (30, [K["END"]]),
      (50, [K["CLS"]])])
    check([n for n, _ in store(m, syms)] == [10, 50],
          "a range is deleted, inclusive at both ends",
          "%s" % [n for n, _ in store(m, syms)])

    # ---- RENUM, which is the point of the token flags.
    #
    # Two lines and a GOTO between them. The compiled RENUMBER left the
    # GOTO pointing at 30, which after renumbering is nothing at all.
    prog = [(10, [K["PRINT"]]),
            (30, [K["GOTO"]] + lit(50)),
            (50, [K["END"]])]
    m, syms = run("""
        MOV  R0,#100
        CLR  R1
        MOV  R2,#10
        CALL prg_renum
        HALT
""", prog)
    got = store(m, syms)
    check([n for n, _ in got] == [100, 110, 120],
          "RENUM renumbers the lines themselves",
          "%s" % [n for n, _ in got])
    check(got[1][1] == [K["GOTO"]] + lit(120),
          "...and rewrites the GOTO to follow the line it meant",
          "%s" % got[1][1])

    # A reference to a line that does not exist is left alone rather
    # than aimed somewhere arbitrary.
    m, syms = run("""
        MOV  R0,#100
        CLR  R1
        MOV  R2,#10
        CALL prg_renum
        HALT
""", [(10, [K["GOTO"]] + lit(999)), (20, [K["END"]])])
    got = store(m, syms)
    check(got[0][1] == [K["GOTO"]] + lit(999),
          "a GOTO into nowhere is left alone, not pointed at a real line",
          "%s" % got[0][1])

    # A literal that is NOT a line number must not be touched: the flag
    # is what tells them apart, and without it RENUM would rewrite every
    # constant in the program.
    m, syms = run("""
        MOV  R0,#100
        CLR  R1
        MOV  R2,#10
        CALL prg_renum
        HALT
""", [(10, [K["POKE"]] + lit(10)), (20, [K["END"]])])
    got = store(m, syms)
    check(got[0][1] == [K["POKE"]] + lit(10),
          "a constant that is not a line number is untouched by RENUM",
          "%s" % got[0][1])

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
