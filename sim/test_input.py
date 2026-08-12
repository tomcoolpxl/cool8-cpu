#!/usr/bin/env python3
"""The input module, driven directly.

    python sim/test_input.py

`sw/input.asm` is the second module of the [D68] port and nothing calls
it yet. Same arrangement as `sim/test_con.py`: a driver assembled in
front of the module, run on a machine, the answer read back.

**The ring is filled from here rather than by the interrupt**, which is
the point of a unit test for this layer: `in_key` decodes what is in the
ring, and whether the bytes arrived from a PS/2 port or an ANSI terminal
is exactly what it is supposed to stop mattering. The interrupt path
itself is covered where it belongs, in `sim/test_basic.py`, which types
at a booted machine.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import memmap                                            # noqa: E402

FAILS = H.FAILS

OUT = 0x4000                    # where the driver leaves R0:R1

# The named keys, as sw/basic.bas has always numbered them: above the
# byte range so a decoded cursor key cannot be confused with a
# character, and contiguous so the decoder can use an offset.
K_UP, K_DOWN, K_LEFT, K_RIGHT = 256, 257, 258, 259
K_HOME, K_END, K_DEL, K_INS = 260, 261, 262, 263

DRIVER = """
        CALL in_key
        ST   [$%04X],R0
        ST   [$%04X],R1
        HALT
""" % (OUT, OUT + 1)


def build():
    return H.assemble_text(
        "        .org $0200\nmain:\n" + DRIVER +
        '\n        .include "input.asm"\n', "in_key", lower=True)


def decode(code, syms, ring):
    """Put `ring` in the interrupt's ring and run one `in_key`."""
    m = H.session()
    m.bus.mem[0x200:0x200 + len(code)] = code
    m.cpu.pc = 0x200
    m.cpu.sp = memmap.RAMTOP
    m.romen = False
    base = syms["irring"]
    for i, b in enumerate(ring):
        m.bus.mem[base + i] = b
    m.bus.mem[syms["irtail"]] = 0
    m.bus.mem[syms["irhead"]] = len(ring) & 15
    if m.run(budget=5_000_000) != "halt":
        raise SystemExit("the driver did not halt at $%04X" % m.cpu.pc)
    return m.bus.mem[OUT] | (m.bus.mem[OUT + 1] << 8)


def main():
    print("  the input module, sw/input.asm")
    print()
    code, syms = build()

    check(decode(code, syms, []) == 0,
          "an empty ring is no key")
    check(decode(code, syms, [ord("A")]) == 65,
          "a plain character passes through")

    # sw/kbd.asm hands the named keys over as $80+n off the PS/2 port.
    check(decode(code, syms, [0x80]) == K_UP,
          "a PS/2 named code becomes K_UP, not the byte $80")
    check(decode(code, syms, [0x87]) == K_INS,
          "...and the last of them is K_INS")

    # The same keys off the serial line, as ANSI. That the two wires
    # produce the identical code is the whole job of this module.
    esc = [0x1B, ord("[")]
    check(decode(code, syms, esc + [ord("A")]) == K_UP,
          "ESC [ A off the serial line is the same K_UP")
    check(decode(code, syms, esc + [ord("D")]) == K_LEFT,
          "ESC [ D is left, not right -- the pair the table transposes")
    check(decode(code, syms, esc + [ord("C")]) == K_RIGHT,
          "...and ESC [ C is right")
    check(decode(code, syms, esc + [ord("H")]) == K_HOME,
          "ESC [ H is home")
    check(decode(code, syms, [0x1B, ord("O"), ord("F")]) == K_END,
          "ESC O F is end -- some terminals send O where others send [")

    # The two that carry a trailing '~', which has to be swallowed or it
    # arrives as a stray character on the next call.
    check(decode(code, syms, esc + [ord("3"), ord("~")]) == K_DEL,
          "ESC [ 3 ~ is delete")
    check(decode(code, syms, esc + [ord("2"), ord("~")]) == K_INS,
          "ESC [ 2 ~ is insert")

    # **A lone Escape is Escape.** Blocking for the rest of a sequence
    # that is never coming would hang a game's loop on the one key it is
    # most likely to test for.
    check(decode(code, syms, [0x1B]) == 27,
          "a lone Escape is Escape and does not block")
    check(decode(code, syms, esc + [ord("Z")]) == 27,
          "an unknown final byte falls back to Escape rather than hanging")

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
