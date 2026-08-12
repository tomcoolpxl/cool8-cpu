#!/usr/bin/env python3
"""The memory map, derived from the sources rather than written down.

    python tools/memmap.py            print it
    python tools/memmap.py --check    and fail on a byte with two owners

## Why this exists, and why it no longer declares anything

Addresses were written down in eight places and none of them was in
charge. `sim/test_interp.py` carried `VARS = 0x0040` as a private copy,
`sim/build_basic.py` its own `ORG` and `TOP`, `sw/basic.bas` a prose map
in a comment, `sw/zp.asm` another one -- and `zp.asm`'s had already gone
stale, still listing `FORSTK` in page 0 after it moved out.

**The first cure was a hand-written table here, and it drifted too.**
It claimed `$00A4-$00D9` was 54 free bytes when the editor owned most of
it, had no entry at all for `$0033-$003F` -- nine names, thirteen bytes
-- and knew nothing of the string accumulator at `$7F00` or the whole
`$FF00` workspace page. A second copy of the map is still a second copy
of the map, however good its intentions ([D67](../docs/01-decisions.md)).

So this file **declares only what the silicon decodes** and derives
everything else from the sources the assembler reads. What it cannot
derive, it does not claim.

## How a claim is declared

An equate is a *constant* unless it says otherwise, because most of them
are: `K_NUM = $A4` is a token value and not an address at all, and an
earlier check that assumed otherwise had to be backed out. Storage says
so, and states its size:

    FORSTK  = $FF3E                 ;: 72 MAXFOR frames of FORFR

`;:` is the same bargain [`ioregs.py`](ioregs.py) makes with `//:` for
the I/O page: **new storage cannot appear without saying what it is**,
and two claims on one byte are a build failure rather than a bug found
twice. `SFRAC` was moved off `$00A4` to escape the editor's `cols` and
landed inside `cont(31)` at `$00B0`, which nothing could see; that is
the fault this format exists to make impossible.

## The second allocator, which is invisible

`DIM x AT $addr` in BASIC emits **no symbol and no size** --
`tools/cool8bas.py` substitutes the literal `$00B0` as the label -- so
the editor's claims reach neither the symbol table nor the assembler.
They are read out of the `.bas` source here, *with their extent*, which
is what the earlier version got wrong: it recorded the base address
alone, so a 32-byte array looked like one byte and the 31 after it read
as free.

[D67] removes this allocator rather than modelling it better. Until
then, modelling it is what keeps the check honest.
"""

import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SW = os.path.join(ROOT, "sw")

# ---------------------------------------------------------------------
# What the hardware decodes. docs/04-system.md section 2 is normative
# and this follows it. **This is the only hand-written map left here**,
# because it is the only one that is not derivable from software: no
# source file can tell you where the address decoder answers.
# ---------------------------------------------------------------------
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ioregs as _ioregs                                    # noqa: E402

# **The page base is `tools/ioregs.py`'s**, which is also what the
# generated equates and the RTL comments derive from. Written down here
# again is how it came to be in eight places (D67).
IO_LO, IO_HI = _ioregs.IO_BASE, _ioregs.IO_TOP

# RAM is everything below the page, plus the eight vector bytes above it.
# The page stops short of $FFF8 precisely so the vectors stay RAM and
# `rtl/core/` needs no change; see D67.
RAM_LO, RAM_HI = 0x0000, IO_LO - 1
TOPRAM_LO, TOPRAM_HI = IO_HI + 1, 0xFFFF

# The highest byte a bare test driver can put its stack on. Six harnesses
# had `m.cpu.sp = 0xFFF7` -- the top of RAM when the I/O page was at
# $FE00 -- and when the page moved to $FF00 every PUSH began writing
# return addresses into flash registers. The machine did not crash; it
# spun, and the suite said only "the machine did not halt". Import this
# rather than writing the number a seventh time (D67).
RAMTOP = IO_LO - 1

# The boot ROM overlays $F000-$FFFF on *reads* while ROMEN=1, less the
# I/O page, and drops out once the flash stub clears it. With the page at
# the top the ROM's code space is contiguous from $F000 to the page.
ROM_LO, ROM_HI = 0xF000, IO_LO - 1

VECTORS = {"RESET": 0xFFF8, "NMI": 0xFFFA, "IRQ": 0xFFFC, "BRK": 0xFFFE}

# **Nothing decodes into page 0**, and it has no addressing advantage
# either -- [D6] dropped the zero page and the direct-page register
# both, so $0040 costs exactly what $9040 costs. It is ordinary RAM.
# [D67] is why that sentence matters: page 0 was defended as scarce for
# years, at the cost of a second hand-allocated pool at $FF00.

# ---------------------------------------------------------------------
# What BASIC lays out below itself. These are still declared, and [D67]
# step 3 moves them into the map file the assembler reads, where
# `sw/basic.bas`'s own CONST copies of them will become EXTERNs.
# ---------------------------------------------------------------------
PROG = 0x0200               # stored program, growing up from here
CSTK = 0x7EE0               # the CALL stack, 8 frames of 4
SACC = 0x7F00               # the string accumulator, 256 bytes

# The system storage region ends where the CALL stack begins; its floor
# is computed from the claims below, not chosen (D67).
SYSEND = CSTK - 1
SCREEN = 0x8000             # 128x32 cells at stride 256, 80x30 shown
SCREEN_END = 0x9FFF
ORG = 0xA000                # the system image
TOP = IO_LO                 # and it must end below the I/O page

VARS = 0x0040               # imported by sim/test_interp.py

def region():
    """(floor, top, used) for the system storage region.

    **The floor is the lowest claim, not a round number.** That is what
    makes "the user area is whatever is left" true rather than a slogan:
    add a claim and the floor drops by exactly its size, and `check()`
    refuses any gap between the floor and the claims above it, so the
    region cannot quietly acquire slack that nobody is using and nobody
    can spend (D67).
    """
    cs = [c for c in claims() if PROG <= c.addr <= SYSEND]
    if not cs:
        return SYSEND + 1, SYSEND, 0
    return min(c.addr for c in cs), SYSEND, sum(c.size for c in cs)


def usertop():
    """The last byte a program may use: one below the region's floor."""
    return region()[0] - 1


def regions():
    """The big picture, with the two floating boundaries filled in.

    A function and not a table because two of its rows depend on the
    claims: the user area ends where the system region begins, and the
    system region begins wherever its lowest claim is.
    """
    floor = region()[0]
    return [
        (PROG, floor - 1, "user", "the stored program up, the heap down"),
        (floor, SYSEND, "SYSVARS", "system storage, packed, floor computed"),
        (CSTK, CSTK + 0x1F, "CSTK", "the CALL stack, 8 frames of 4"),
        (SACC, SACC + 0xFF, "SACC",
         "the string accumulator; pbuf overlays it"),
        (SCREEN, SCREEN_END, "SCREEN",
         "the text map, stride 256 in every mode"),
        (ORG, TOP - 1, "IMAGE", "BASIC: editor, interpreter, floats"),
        (IO_LO, IO_HI, "IO", "the I/O page, generated by tools/ioregs.py"),
        (TOPRAM_LO, TOPRAM_HI, "vectors", "RAM; the CPU reads these"),
    ]


# ---------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------

class Claim:
    """One run of bytes with an owner, from wherever it was declared."""

    def __init__(self, addr, size, name, note, src):
        self.addr, self.size = addr, size
        self.name, self.note, self.src = name, note, src

    @property
    def end(self):
        return self.addr + self.size - 1

    def overlaps(self, other):
        return self.addr <= other.end and other.addr <= self.end

    def __repr__(self):
        return f"<{self.name} ${self.addr:04X}+{self.size}>"


_CLAIM = re.compile(
    r"^([A-Za-z_]\w*)\s*=\s*\$([0-9A-Fa-f]{1,4})\s*;:\s*(\d+)\s*(.*)$", re.M)

# `DIM name(n) AS TYPE AT $addr` -- the invisible allocator. The bound
# and the type are what give it an extent, and the extent is the whole
# point: `cont(31) AS BYTE` is 32 bytes, not one.
_DIM = re.compile(
    r"^\s*DIM\s+([A-Za-z_]\w*)\s*(?:\(\s*(\d+)\s*\))?"
    r"(?:\s+AS\s+(BYTE|INT|CARD))?\s+AT\s+\$([0-9A-Fa-f]{1,4})",
    re.M | re.I)

_WIDTH = {"byte": 1, "int": 2, "card": 2, None: 2}


def asm_claims():
    """Every `;:` storage claim in sw/*.asm **and sw/*.bas**.

    The `.bas` files are scanned too because `sw/basic.bas` declares
    storage inside its trailing `ASM` block in exactly the assembly
    syntax -- `irring = $FF00 ;: 16` -- and a scanner that looked only at
    `.asm` could not see the editor's interrupt workspace at all. That
    was eight more claims invisible to the map, on top of the `DIM ... AT`
    ones, and they only surfaced when the I/O page moved on top of them.
    """
    out = []
    for path in sorted(glob.glob(os.path.join(SW, "*.asm")) +
                       glob.glob(os.path.join(SW, "*.bas"))):
        base = os.path.basename(path)
        src = open(path, encoding="utf-8").read()
        for name, addr, size, note in _CLAIM.findall(src):
            out.append(Claim(int(addr, 16), int(size), name,
                             note.strip(), base))
    return out


def bas_claims():
    """Every `DIM ... AT` in sw/*.bas, **with its extent**.

    The extent is the part the old check did not have, and the part that
    hid `SFRAC` inside `cont`. A bound of `n` is `n + 1` elements, which
    is what `tools/cool8bas.py` reserves.
    """
    out = []
    for path in sorted(glob.glob(os.path.join(SW, "*.bas"))):
        base = os.path.basename(path)
        src = open(path, encoding="utf-8").read()
        for name, bound, kind, addr in _DIM.findall(src):
            w = _WIDTH[kind.lower() if kind else None]
            n = (int(bound) + 1) if bound else 1
            out.append(Claim(int(addr, 16), w * n, name,
                             "DIM ... AT, no symbol emitted", base))
    return out


def claims():
    return sorted(asm_claims() + bas_claims(), key=lambda c: (c.addr, c.name))


def sysbot_asm(write=False):
    """`sw/sysbot.asm`: the floor of system storage, as a number.

    **The floor cannot be an equate over a symbol.** `SYSBOT = irring`
    was one, and it was wrong the moment sw/console.asm claimed below
    `irring`; `SYSBOT = CONT` was the same mistake one module along,
    because sw/main.asm claims below *that*. An equate can only name a
    symbol the assembler has already seen, and the lowest claim in the
    machine belongs to whichever module happens to hold it -- which is
    not knowable from inside any one of them, and changes.

    So it is derived here, where every claim is visible at once, and
    written out as a literal for zp.asm to include. Same arrangement as
    the I/O page and the token numbering: the number exists once, a tool
    puts it there, and `--check` fails the build if the file on disk
    stops matching what the claims say ([D67]).
    """
    floor, top, used = region()
    low = min((c for c in claims() if c.addr >= 0x0200), key=lambda c: c.addr)
    text = (
        "; ---------------------------------------------------------------------\n"
        "; sysbot.asm -- GENERATED by tools/memmap.py. Do not edit.\n"
        ";\n"
        "; The floor of system storage is the lowest claim anywhere in sw/,\n"
        "; which no single module can name: an equate may only refer to a\n"
        "; symbol already seen, and the module holding the lowest claim is not\n"
        "; the first one read. Written as a number for that reason, and\n"
        "; checked against the claims by `poe check`.\n"
        ";\n"
        f"; Lowest claim: {low.name} at ${low.addr:04X}, in {low.src}.\n"
        f"; The region spans ${floor:04X}-${top:04X}, {used} bytes claimed.\n"
        "; ---------------------------------------------------------------------\n"
        f"SYSBOT  = ${floor:04X}                 ; the lowest claim in sw/\n"
        f"USERTOP = ${floor - 1:04X}                 ; the last byte a program may use\n")
    path = os.path.join(SW, "sysbot.asm")
    if write:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return path, text


_SYMS = None


def sym(name):
    """One symbol's value, asked of the assembler.

    `SYSBOT` is an equate over another symbol -- `SYSBOT = CONT` -- so
    no regular expression over the source can tell you what it is, and a
    regular expression over the source is exactly what let it point at
    the wrong claim for as long as it did. The assembler is the only
    thing that knows, so it is what gets asked.

    Returns None if the system does not assemble, because a broken build
    has louder problems than the map and this check should not be the
    one to report them.
    """
    global _SYMS
    if _SYMS is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import cool8asm
        try:
            a = cool8asm.assemble(os.path.join(SW, "main.asm"), incdirs=[SW])
            _SYMS = {} if a.errors else {k.upper(): v for k, v in a.syms.items()}
        except Exception:
            _SYMS = {}
    return _SYMS.get(name.upper())


def collisions(cs=None):
    """Every pair of claims sharing a byte. This is the check."""
    cs = cs if cs is not None else claims()
    bad = []
    for i, a in enumerate(cs):
        for b in cs[i + 1:]:
            if b.addr > a.end:
                break
            if a.overlaps(b):
                bad.append((a, b))
    return bad


def check():
    """Problems, as text. Empty means the map holds."""
    cs = claims()
    bad = [f"${a.addr:04X}+{a.size} {a.name} ({a.src}) overlaps "
           f"${b.addr:04X}+{b.size} {b.name} ({b.src})"
           for a, b in collisions(cs)]

    # A claim that lands in the I/O page is a register, not storage; one
    # past the top of RAM is a typo. Neither can be caught by looking at
    # the claim alone, which is why the hardware map stays declared here.
    for c in cs:
        if IO_LO <= c.addr <= IO_HI or IO_LO <= c.end <= IO_HI:
            bad.append(f"{c.name} (${c.addr:04X}+{c.size}, {c.src}) "
                       f"lands in the I/O page")
        elif ORG <= c.addr < TOP:
            bad.append(f"{c.name} (${c.addr:04X}+{c.size}, {c.src}) "
                       f"is storage inside the image -- see [D67]")

    # **The region must be packed.** A gap between the floor and the
    # claims is user RAM that has been taken away and given to nobody,
    # and it is invisible: `FREE` would report the smaller number and no
    # one would know which byte to blame. Overlaps are caught above; this
    # catches the other direction.
    floor, top, used = region()
    span = top - floor + 1
    if used and span != used:
        bad.append(f"the system region spans {span} bytes and claims "
                   f"{used}: {span - used} unused, move the floor to "
                   f"${top - used + 1:04X}")

    # **SYSBOT has to be the lowest claim, and once was not.**
    #
    # It read `SYSBOT = irring`, which was true while sw/zp.asm held
    # every claim in the region. sw/console.asm then claimed $7DAF-$7DE8
    # -- CONT, the mirror, the cursor, the whole geometry -- underneath
    # it, and USERTOP went on pointing 58 bytes too high. `DIM A(3)`
    # took ten bytes off the heap and wrote the array over CCY, CTOP,
    # CCOLS, CROWS and CKIND; the console then printed nothing at all,
    # with no error and nothing on screen to look at. It cost a session.
    #
    # Nothing above catches it: every claim is legal, none overlaps, and
    # the region is packed. The floor being *reachable by the heap* is a
    # different question, and this is it.
    # The generated file has to be the one on disk, or the assembler is
    # reading a floor that the claims stopped agreeing with.
    path, want = sysbot_asm()
    got = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if got != want:
        bad.append("sw/sysbot.asm is stale -- run `poe build` (memmap --emit)")

    sysbot = sym("SYSBOT")
    if sysbot is not None and sysbot != floor:
        low = min((c for c in cs if c.addr >= 0x0200), key=lambda c: c.addr)
        bad.append(f"SYSBOT is ${sysbot:04X} but the lowest claim is "
                   f"${floor:04X} ({low.name}, {low.src}): "
                   f"{sysbot - floor} bytes of system storage sit below "
                   f"USERTOP and the heap will allocate over them")

    # ...and BASIC has to agree with the assembly about every address it
    # reaches by number.
    #
    # **A CONST is the second copy, and the second copy is what rots.**
    # `CONST IRST = $FF86` went on naming the old workspace page after
    # the I/O page moved on top of it, so the editor read a flash
    # register, found it non-zero, and called doreset() on every pass of
    # its key loop -- no error, no crash, just an editor that would not
    # accept a line. Nothing could have caught that except this: a CONST
    # whose name matches a storage claim must have the claim's address.
    #
    # They stay CONSTs rather than becoming EXTERNs because a CONST
    # folds and an EXTERN does not, which was measured at 89 bytes (D67).
    # So the number is genuinely written twice and this is what keeps the
    # copy honest.
    byname = {c.name.lower(): c for c in cs}
    byname["usertop"] = Claim(usertop(), 1, "USERTOP",
                              "the region's floor, less one", "computed")
    src = os.path.join(SW, "basic.bas")
    if os.path.exists(src):
        for n, v in re.findall(
                r"^\s*CONST\s+([A-Za-z_]\w*)\s*=\s*\$([0-9A-Fa-f]{1,4})",
                open(src, encoding="utf-8").read(), re.M | re.I):
            c = byname.get(n.lower())
            if c is not None and int(v, 16) != c.addr:
                bad.append(f"sw/basic.bas has CONST {n} = ${int(v, 16):04X} "
                           f"and {c.src} puts {c.name} at ${c.addr:04X}")
    return bad


def rows():
    """The map as (lo, hi, name, note) including the gaps, so free RAM
    is visible rather than inferred. Gaps are what the port needs to
    know and what no earlier version of this file could answer."""
    out, at = [], 0x0000
    for c in claims():
        if c.addr > at:
            out.append((at, c.addr - 1, None, "free"))
        out.append((c.addr, c.end, c.name, f"{c.note} [{c.src}]"))
        at = max(at, c.end + 1)
    if at <= 0xFFFF:
        out.append((at, 0xFFFF, None, "free"))
    return out


def free_runs(lo=0x0000, hi=0xFFFF, least=1):
    """Unclaimed runs inside a range -- the question "where is there
    room", which is why this module exists at all."""
    return [(a, b) for a, b, name, _ in rows()
            if name is None and a >= lo and b <= hi and b - a + 1 >= least]


def main():
    cs = claims()
    print()
    print("  Claimed storage, derived from sw/*.asm `;:` and sw/*.bas `AT`")
    print()
    for lo, hi, name, why in rows():
        if hi < 0x0200 or (0x7E00 <= hi <= 0x8000) or lo >= 0xFF00:
            tag = name or ""
            n = hi - lo + 1
            print(f"    ${lo:04X}-${hi:04X} {n:>4}  {tag:<9} {why}")
    print()
    print("  Regions the hardware and the boot decide")
    for lo, hi, name, why in regions():
        print(f"    ${lo:04X}-${hi:04X}  {name:<8} {why}")
    print()
    print(f"    ROM overlay ${ROM_LO:04X}-${ROM_HI:04X} and "
          f"${TOPRAM_LO:04X}-${TOPRAM_HI:04X}, on reads while ROMEN")
    print("    " + "  ".join(f"{k} ${v:04X}" for k, v in VECTORS.items()))
    print()
    print(f"  {len(cs)} claims, {sum(c.size for c in cs)} bytes")
    for lo, hi in free_runs(0x0000, 0x01FF, least=8):
        print(f"    free in page 0     ${lo:04X}-${hi:04X}  {hi - lo + 1}")
    for lo, hi in free_runs(0xFF00, 0xFFF7, least=8):
        print(f"    free at $FF00      ${lo:04X}-${hi:04X}  {hi - lo + 1}")
    print()
    if "--emit" in sys.argv:
        path, text = sysbot_asm(write=True)
        print(f"  wrote {os.path.relpath(path, ROOT)}: "
              f"{text.splitlines()[-2].strip()}")
        print()
    if "--check" in sys.argv:
        bad = check()
        for b in bad:
            print("  DRIFT:", b)
        print("  the map holds: no byte has two owners" if not bad else "")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
