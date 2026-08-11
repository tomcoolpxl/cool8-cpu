#!/usr/bin/env python3
"""The memory map, in one place, machine-readable.

    python tools/memmap.py            print it
    python tools/memmap.py --check    and verify sw/zp.asm agrees

## Why this exists

Addresses were written down in eight places and none of them was in
charge. `sim/test_interp.py` carried `VARS = 0x0040` as a private copy,
`sim/build_basic.py` its own `ORG` and `TOP`, `sw/basic.bas` a prose map
in a comment, `sw/zp.asm` another one -- and `zp.asm`'s had already gone
stale, still listing `FORSTK` in page 0 after it moved out.

That is the failure this project keeps paying for and has a cure for:
[`tools/opcodes.py`](opcodes.py) is the one machine-readable source for
the encoding, everything imports it, and `poe check` fails on drift.
**This is the same arrangement for addresses.** Import it; do not retype
a number out of it.

## What is normative where

The *hardware* map -- what decodes where -- belongs to
[docs/04-system.md](../docs/04-system.md) and this file follows it. The
*software* allocation of page 0 belongs to [sw/zp.asm](../sw/zp.asm),
which is where the assembler reads it from, and `--check` verifies this
file against those equates rather than the other way round. So: docs for
the silicon, zp.asm for the assembly, and this for anything in Python
that would otherwise write a number down twice.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------
# What the hardware decodes. docs/04-system.md section 3 is normative.
# ---------------------------------------------------------------------
RAM_LO, RAM_HI = 0x0000, 0xFDFF     # plain SPRAM, no aliasing
IO_LO, IO_HI = 0xFE00, 0xFEFF       # always decoded, always wins
TOPRAM_LO, TOPRAM_HI = 0xFF00, 0xFFFF

# The boot ROM overlays these on *reads* while ROMEN=1, and drops out
# once the flash stub clears it.
ROM_LO, ROM_HI = 0xF000, 0xFDFF

VECTORS = {"RESET": 0xFFF8, "NMI": 0xFFFA, "IRQ": 0xFFFC, "BRK": 0xFFFE}

# **Nothing decodes into page 0.** It is worth stating because it is the
# question that gets asked every time something wants cheap storage
# there, and the answer has to be checked against the whole machine and
# not just BASIC: the ROM, the monitor and the disassembler define no
# page-0 storage at all, and the I/O page is $FE00 and above.

# ---------------------------------------------------------------------
# Page 0, as sw/zp.asm allocates it. `--check` reads that file and
# compares, so this table cannot quietly drift from the equates the
# assembler actually uses.
# ---------------------------------------------------------------------
PAGE0 = [
    (0x0000, 0x0011, "DOSTK", "DO/LOOP's own stack, four frames"),
    (0x0012, 0x0013, "BENT", "the builtin table entry being tried"),
    (0x0014, 0x0022, "LREC", "the interpreter: record, progend, error"),
    (0x0023, 0x0026, "MTMP", "multiply scratch"),
    (0x0027, 0x0032, "NTAB", "long names: table, heap floor, scan buffer"),
    (0x0040, 0x0073, "VARS", "A-Z, two bytes each"),
    (0x0074, 0x00A1, "FSVARS", "sw/fs.asm's workspace"),
    (0x00A2, 0x00A3, "FDEPTH", "FOR depth, then expression depth"),
    (0x00A4, 0x00A4, "SFRAC",
     "VAL's fraction digits, $FF until a point is met"),
    (0x00A4, 0x00D9, None, "free -- 54 bytes, FORSTK's when it left"),
    (0x00DA, 0x00FE, "FSTK", "floating point's operand stack; was the "
                             "on-machine assembler until D63"),
    (0x00FF, 0x00FF, None, "free"),
    (0x0100, 0x01FF, None, "the CPU stack, growing down from $0200"),
]

# ---------------------------------------------------------------------
# What BASIC lays out below itself. sw/basic.bas is where these are set.
# ---------------------------------------------------------------------
# Named individually as well as in the table, because importing a name
# is the point -- `from memmap import VARS, ORG, TOP`.
DOSTK, BENT, LREC, MTMP, NTAB = 0x0000, 0x0012, 0x0014, 0x0023, 0x0027
VARS, FSVARS = 0x0040, 0x0074
FDEPTH, EDEPTH = 0x00A2, 0x00A3
FSTK, FSP, FLTY = 0x00DA, 0x00FD, 0x00FE
CPUSTK = 0x0100

PROG = 0x0200               # stored program, growing up from here
USERTOP = 0x7EDF            # the heap grows down to meet the names
CSTK = 0x7EE0               # the CALL stack, 8 frames of 4
SCREEN = 0x8000             # 128x32 cells at stride 256, 80x30 shown
SCREEN_END = 0x9FFF
ORG = 0xA000                # the system image
TOP = 0xFE00                # and it must end below this

REGIONS = [
    (PROG, USERTOP, "user", "the stored program up, the heap down"),
    (CSTK, 0x7EFF, "CSTK", "the CALL stack, 8 frames of 4"),
    (SCREEN, SCREEN_END, "SCREEN", "the text map, stride 256 in every mode"),
    (ORG, TOP - 1, "SYSTEM", "BASIC: editor, interpreter, floats"),
    (IO_LO, IO_HI, "IO", "the I/O page"),
    (TOPRAM_LO, TOPRAM_HI, "vectors", "RAM, or boot ROM on reads"),
]


def equates():
    """{name: (address, file)} for every absolute equate in sw/.

    **Not just zp.asm.** The first version read that file alone and the
    check caught its own blind spot on the first run: `FSVARS` is
    declared in `sw/fs.asm`. Anything may claim an address, so the audit
    has to look everywhere -- which is also what makes the collision
    test below worth having.
    """
    import glob
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "sw", "*.asm"))):
        src = open(path, encoding="utf-8").read()
        for n, v in re.findall(r"^([A-Za-z_]\w*)\s*=\s*\$([0-9A-Fa-f]{1,4})",
                               src, re.M):
            out.setdefault(n, (int(v, 16), os.path.basename(path)))
    return out


def check():
    """PAGE0 against what the sources actually say. Returns problems."""
    eq, bad = equates(), []
    for lo, _hi, name, _why in PAGE0:
        if name is None:
            continue
        if name not in eq:
            bad.append(f"{name} is in memmap.py and in no source")
        elif eq[name][0] != lo:
            bad.append(f"{name}: memmap ${lo:04X}, "
                       f"{eq[name][1]} ${eq[name][0]:04X}")

    # **Two names on one byte of page 0 is the bug this cannot miss.**
    # Page 0 is fully spoken for and the pressure to reuse it is
    # constant; the float package was first written into the middle of
    # FORSTK because nobody could see the whole map at once.
    owners = {}
    for lo, hi, name, _why in PAGE0:
        if name is None:
            continue
        for a in range(lo, hi + 1):
            owners[a] = name
    for n, (a, f) in sorted(eq.items()):
        if a < 0x0100 and a in owners and owners[a] != n:
            here = next(r for r in PAGE0
                        if r[2] == owners[a] and r[0] <= a <= r[1])
            if not (here[0] <= a <= here[1]):
                bad.append(f"{n} (${a:04X}, {f}) lands in {owners[a]}")
    # The float stack has to end before the two bytes that manage it.
    deep = eq.get("FSDEEP")
    if deep is not None and eq.get("FSTK") is not None:
        end = eq["FSTK"] + deep * 5
        if end > eq.get("FSP", 0):
            bad.append(f"FSTK's {deep} frames reach ${end:04X}, past FSP "
                       f"at ${eq.get('FSP', 0):04X}")
    return bad


def main():
    print()
    print("  Page 0")
    for lo, hi, name, why in PAGE0:
        tag = name or ""
        print(f"    ${lo:04X}-${hi:04X}  {tag:<8} {why}")
    print()
    print("  The rest")
    for lo, hi, name, why in REGIONS:
        print(f"    ${lo:04X}-${hi:04X}  {name:<8} {why}")
    print()
    print(f"    ROM overlay ${ROM_LO:04X}-${ROM_HI:04X} and "
          f"${TOPRAM_LO:04X}-${TOPRAM_HI:04X}, on reads while ROMEN")
    print("    " + "  ".join(f"{k} ${v:04X}" for k, v in VECTORS.items()))
    print()
    if "--check" in sys.argv:
        bad = check()
        for b in bad:
            print("  DRIFT:", b)
        print("  memmap.py and sw/zp.asm agree" if not bad else "")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
