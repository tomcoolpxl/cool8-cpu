#!/usr/bin/env python3
"""The memory map, derived from the sources rather than written down.

    python tools/memmap.py            print it
    python tools/memmap.py --check    and fail on a byte with two owners

## Why this exists, and why it no longer declares anything

Addresses were written down in eight places and none of them was in
charge. `sim/test_interp.py` carried `VARS = 0x0040` as a private copy,
`sim/build_basic.py` its own `ORG` and `TOP`, `sw/basic.bas` a prose map
in a comment, `sw/lowram.asm` another one -- and `lowram.asm`'s had already gone
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

# The highest byte a bare test driver can put its stack on.
#
# **It is USERTOP, not the top of RAM.** Six harnesses had
# `m.cpu.sp = 0xFFF7` -- the top of RAM when the I/O page was at $FE00 --
# and when the page moved every PUSH began writing return addresses into
# flash registers. [D69] made the same mistake possible again from the
# other side: the image is top-aligned and ends at $FEFF, so a stack
# there writes into the image itself. Everything above USERTOP belongs
# to something.

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
PROG = 0x0200               # stored program up, heap down: one region
CSTK = 0xAE6A               # the CALL stack, 8 frames of 4
SACC = 0xAE6A               # the string accumulator, 256 bytes

# The system storage region ends where the CALL stack begins; its floor
# is computed from the claims below, not chosen (D67).
SYSEND = CSTK - 1
SCREEN = 0x9800             # the text map: 80 cells a row, 32 rows
CSTRIDE = 160               # ...at this pitch, which sw/console.asm and
                            #    the mode presets in cool8_vregs.v agree
                            #    on. It was 256 with 48 cells a row never
                            #    displayed, so the map was 8192 bytes;
                            #    [D30]'s padding, which the map-origin
                            #    register made unnecessary.
SCREEN_END = SCREEN + CSTRIDE * 32 - 1
RAMTOP = SCREEN - 1
TOP = IO_LO                 # the image must end below the I/O page


def image_size():
    """How many bytes sw/main.asm assembles to.

    **Independent of where it is linked** -- COOL8 has no zero page and
    no short absolute form ([D6]), so every absolute operand is two
    bytes whatever the address, and relative branches depend on distance
    rather than position. Measured at $A000, $B000 and $BA58: 17,164
    bytes every time. That is what lets the origin be derived from the
    size without a fixed point to iterate to.

    **Unmeasurable is a return of None, not an exception.** The two
    files this module generates are `.include`d by the image it is
    measuring, so on a tree where one of them is missing the assembler
    raises before anything can write it -- deleting `sw/org.asm` used to
    brick the build with a `FileNotFoundError` from inside the include
    reader, which names the generated file and not the way to get it
    back. `ensure()` seeds a provisional file when the measurement comes
    back None and then measures again.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cool8asm
    try:
        a = cool8asm.assemble(os.path.join(SW, "main.asm"), incdirs=[SW])
    except (OSError, SystemExit):
        return None
    if a.errors:
        return None
    lo, img = a.image()
    return len(img)


def org():
    """Where the image starts: top-aligned under the I/O page.

    `$A000` was written down when the system was compiled BASIC and
    23,528 bytes. It is 17,164 now, and a constant chosen for a size the
    software no longer is leaves the difference stranded between the
    image and $FEFF where nothing can reach it. Derived, the boundary
    follows the image: shrink BASIC and the space appears below it.
    """
    n = image_size()
    return 0xA000 if n is None else (TOP - n)


ORG = org()                 # the system image, derived from its size

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
    """The last byte a program may use: one below the text map.

    **The map, not the lowest claim.** [D69]'s repack put the map,
    system storage and the image all above the user, so what bounds a
    program is the first of those going up -- and that is the screen.
    """
    return SCREEN - 1


def regions():
    """The big picture, with the two floating boundaries filled in.

    A function and not a table because two of its rows depend on the
    claims: the user area ends where the system region begins, and the
    system region begins wherever its lowest claim is.
    """
    floor = region()[0]
    return [
        # The user stops at the map, not at the lowest claim: after
        # [D69] the map, system storage and the image are all above,
        # and the map is the first of them going up.
        (PROG, SCREEN - 1, "user",
         "the stored program up, the heap down -- one region"),
        (floor, SYSEND, "SYSVARS", "system storage, packed, floor computed"),
        (CSTK, CSTK + 0x1F, "CSTK", "the CALL stack, 8 frames of 4"),
        (SACC, SACC + 0xFF, "SACC",
         "the string accumulator; fscmd's page buffer overlays it"),
        (SCREEN, SCREEN_END, "SCREEN",
         "the text map, %d bytes: %d a row, 32 rows" % (CSTRIDE * 32, CSTRIDE)),
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


def ensure():
    """Bring `sw/org.asm` and `sw/sysbot.asm` up to date, and say what moved.

    **Called before anything assembles `sw/main.asm`**, from
    `sim/test_basic.py`'s `build()` -- the one function every suite,
    every tool and every experiment goes through to get an image.

    The two files are inputs to the assembly *and* derived from it, so
    which of them is current when a build starts used to depend on the
    order the `build` job group happened to run in. Change the size of
    BASIC by ten bytes and `poe build` failed on `build-basic` -- the
    image assembled at the old origin while `mkboot` was told to
    relocate to the new one -- and then succeeded on a second run,
    because by then `build-memmap` had written the file. A build that
    passes on the second attempt is a build nobody can read the result
    of, and the failure said nothing about size.

    There is no circularity to break: `image_size()` measures the same
    number wherever the image is linked ([D6] -- no zero page, no short
    absolute form, so every operand is the same width at any address).
    The loop below is belt and braces for the bootstrap case where a
    file is missing entirely and the first measurement is taken with
    the assembler failing; it settles in one pass otherwise.
    """
    global ORG
    moved = []
    for _ in range(3):
        ORG = org()
        changed = []
        for gen in (sysbot_asm, org_asm):
            path, want = gen()
            got = ""
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    got = fh.read()
            if got != want:
                gen(write=True)
                changed.append(os.path.relpath(path, ROOT))
        moved += changed
        if not changed:
            break
    return moved


def org_asm(write=False):
    """`sw/org.asm`: the image's origin, derived from its size.

    Generated for the same reason `sysbot.asm` is -- the number exists
    once, a tool puts it there, and `--check` fails the build when the
    file on disk stops matching. `.org` has to be a literal, and the
    literal depends on how big the file it opens turns out to be, which
    no assembler directive can express.

    The bootstrap is that the size does not depend on the origin, so
    assembling with whatever `org.asm` currently says still measures the
    right number.
    """
    # `org()` and not `TOP - image_size()`, because the measurement is
    # None on a tree where this very file is missing -- the image cannot
    # be assembled without the `.org` it is about to be given. One
    # provisional pass at the fallback origin makes the image
    # assemblable; `ensure()` then measures it and writes the real one.
    o = org()
    n = TOP - o
    head = [
        "; ---------------------------------------------------------------",
        "; org.asm -- GENERATED by tools/memmap.py. Do not edit.",
        ";",
        "; The image is top-aligned under the I/O page: it ends at $%04X" % (TOP - 1),
        "; and starts at $%04X, because it is %d bytes long." % (o, n),
        ";",
        "; This was a written-down $A000, chosen when the system was",
        "; compiled BASIC and 23,528 bytes. A constant picked for a size",
        "; the software no longer is leaves the difference stranded above",
        "; the image, where nothing can reach it. Derived, the boundary",
        "; follows: whatever BASIC stops using appears below it.",
        "; ---------------------------------------------------------------",
        "        .org  $%04X" % o,
        "",
        "",
    ]
    text = chr(10).join(head)
    path = os.path.join(SW, "org.asm")
    if write:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return path, text


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
    written out as a literal for lowram.asm to include. Same arrangement as
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
        "; The user region ends at the text map. After [D69] the map,\n"
        "; system storage and the image are all above it, so $0200 runs\n"
        "; contiguously to USERTOP and the heap comes down from the top\n"
        "; of the same region the program grows up through.\n"
        ";\n"
        f"; Lowest system claim: {low.name} at ${low.addr:04X}, in {low.src}.\n"
        f"; System storage spans ${floor:04X}-${top:04X}, {used} bytes claimed.\n"
        ";\n"
        "; The map's address and pitch are here for the same reason, and\n"
        "; because they have to reach the boot ROM as well as BASIC. They\n"
        "; did not, once: [D70] moved the map from $8000 to $A000 and\n"
        "; sw/boot.asm and sw/monitor.asm kept their own $8000, so the\n"
        "; ROM banner and the whole monitor drew into user RAM while the\n"
        "; display read somewhere else. Every suite passed -- the monitor's\n"
        "; gate reads the serial line, and the cosim compares two models\n"
        "; that were both looking at the right address and seeing nothing.\n"
        "; ---------------------------------------------------------------------\n"
        f"SYSBOT  = ${SCREEN:04X}                 ; the first byte not a program's\n"
        f"USERTOP = ${SCREEN - 1:04X}                 ; the last byte a program may use\n"
        f"SCREEN  = ${SCREEN:04X}                 ; the text map, {CSTRIDE * 32} bytes\n"
        f"CSTRIDE = {CSTRIDE:<21} ; bytes per map row: {CSTRIDE // 2} cells of char+attr\n")
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
    # It read `SYSBOT = irring`, which was true while sw/lowram.asm held
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
    # The generated files have to be the ones on disk, or the assembler
    # is reading a floor, or an origin, that stopped agreeing with the
    # thing it was derived from.
    op, owant = org_asm()
    ogot = open(op, encoding="utf-8").read() if os.path.exists(op) else ""
    if ogot != owant:
        bad.append("sw/org.asm is stale -- run `poe build` (memmap --emit)")

    path, want = sysbot_asm()
    got = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if got != want:
        bad.append("sw/sysbot.asm is stale -- run `poe build` (memmap --emit)")

    # **A hole above the screen is not free space, it is a lost
    # kilobyte.** The packing check treats SYSBOT -- the screen -- as
    # the region's floor and verifies the claims above it are
    # contiguous, which says nothing about the gap between the top of
    # the map and the lowest claim that is not the map. Moving SCREEN
    # down a kilobyte to give BASIC room does exactly that: the user
    # loses 1,024 bytes, nothing claims them, and the image gains
    # nothing because system storage has not moved. Measured, and it
    # passed every check at the time.
    lowest = min((c.addr for c in cs if c.addr > SCREEN_END), default=None)
    if lowest is not None and lowest > SCREEN_END + 1:
        bad.append(f"${SCREEN_END + 1:04X}-${lowest - 1:04X} is a "
                   f"{lowest - SCREEN_END - 1}-byte hole between the top of "
                   f"the text map and the lowest claim above it. Nothing can "
                   f"reach it: the user's region ends at the map and the "
                   f"image stops at the claims. Move the claims down with "
                   f"the map, or the bytes are simply gone.")

    # **And the hardware has to agree, which nothing checked.**
    #
    # The text modes' presets and the reset values in cool8_vregs.v
    # carry the map's address and pitch as literals, and this file
    # carried a comment saying they "agree" -- a hope, not a test. That
    # is the same shape as the I/O page before tools/ioregs.py, and it
    # is what makes moving the screen expensive: five places, three
    # languages, and only the software half is derived.
    #
    # `poe check` reads the Verilog now. It is deliberately a check and
    # not a generator: the RTL is normative for what the silicon does
    # ([D28]), so the right failure is "these disagree", not Python
    # quietly rewriting a mode preset.
    vregs = os.path.join(ROOT, "rtl", "soc", "cool8_vregs.v")
    if os.path.exists(vregs):
        with open(vregs, encoding="utf-8") as fh:
            v = fh.read()
        want_b, want_s = f"16'h{SCREEN:04X}", f"16'd{CSTRIDE}"
        # The text engines are modes 0 and 1; everything else draws from
        # VRAM and has nothing to do with this map.
        for m in (0, 1):
            i = v.find("4'd%d: begin" % m)
            blk = v[i:i + 240] if i >= 0 else ""
            gb = re.search(r"p_base\s*=\s*(16'h[0-9A-Fa-f]{4})", blk)
            gs = re.search(r"p_stride\s*=\s*(16'd\d+)", blk)
            if not gb or not gs:
                bad.append(f"cool8_vregs.v: mode {m}'s preset could not be "
                           f"read, so the check in tools/memmap.py is not "
                           f"checking anything -- fix it before trusting it")
                continue
            if gb.group(1).lower() != want_b.lower() or gs.group(1) != want_s:
                bad.append(f"cool8_vregs.v mode {m} presets the map at "
                           f"{gb.group(1)} stride {gs.group(1)}, and "
                           f"tools/memmap.py says {want_b} stride {want_s}. "
                           f"The display and the console would read "
                           f"different memory.")
        for reg in ("base_r", "maporg_r"):
            mt = re.search(r"%s\s*<=\s*(16'h[0-9A-Fa-f]{4})" % reg, v)
            if mt and mt.group(1).lower() != want_b.lower():
                bad.append(f"cool8_vregs.v resets {reg} to {mt.group(1)}, "
                           f"and the map is at {want_b}. A machine that "
                           f"never writes VID_MODE draws from the wrong "
                           f"address.")

    # **And the Rust machine, which had its own copy too.** The check
    # above read only the Verilog, so moving the map left `rust/` still
    # presetting $A000: the console wrote to one address and the
    # emulator's display read another, and the screen filled with
    # fragments of the right characters in the wrong places. Every
    # suite that reads pixels passed, because the two *models* still
    # agreed with each other -- they were both wrong in the same way
    # only where they were compared.
    rustm = os.path.join(ROOT, "rust", "src", "machine.rs")
    if os.path.exists(rustm):
        with open(rustm, encoding="utf-8") as fh:
            rl = fh.readlines()
        # **Scoped to the presets and the reset values**, because a bare
        # search for $8000 or $A000 also finds the sound engine's bit
        # masks -- a check that cries wolf gets switched off.
        for i, line in enumerate(rl, 1):
            t = line.strip()
            hit = None
            if t.startswith("(0b") and "," in t:          # a mode preset
                hit = re.search(r"0x([0-9A-Fa-f]{4})", t)
            elif t.startswith("base:") or t.startswith("map_org:"):
                hit = re.search(r"0x([0-9A-Fa-f]{4})", t)
            if hit and int(hit.group(1), 16) != SCREEN:
                # modes 2-6 draw from VRAM and preset 0x0000; only the
                # text engines name this map.
                if int(hit.group(1), 16) == 0:
                    continue
                bad.append(f"rust/src/machine.rs:{i} presets ${int(hit.group(1),16):04X} "
                           f"where the map is ${SCREEN:04X}. The console and "
                           f"the emulator's display would read different "
                           f"memory, and every suite that compares the two "
                           f"models would still pass.")

    # **Nobody may keep a private copy of the map's address or pitch.**
    # sw/boot.asm and sw/monitor.asm each held their own `$8000` and
    # "stride 256" through [D70]. Both assembled, both ran, and both
    # drew the ROM banner and the entire monitor into user RAM while the
    # display read $A000 -- for a whole commit, because the monitor's
    # gate reads the serial line and the cosim compares two models that
    # were both looking at the map and both seeing nothing.
    #
    # The equates are generated into sw/sysbot.asm. This refuses a
    # second definition of them anywhere in sw/, which is the only form
    # the mistake can take: a bare literal in an instruction is caught
    # by the machine, but an equate is silently self-consistent.
    own = re.compile(r"^\s*(SCREEN|CSCRN|CSTRIDE)\s*=\s*[\$\d]", re.M)
    for fn in sorted(os.listdir(SW)):
        if not fn.endswith(".asm") or fn == "sysbot.asm":
            continue
        src = open(os.path.join(SW, fn), encoding="utf-8").read()
        for mt in own.finditer(src):
            line = src[:mt.start()].count("\n") + 1
            bad.append(f"sw/{fn}:{line} defines {mt.group(1)} itself. "
                       f"The map's address and pitch are generated into "
                       f"sw/sysbot.asm -- include it and use them.")

    # **The image and system storage must not meet.** The image is
    # top-aligned, so it grows *downward* towards the string
    # accumulator: every byte added to BASIC closes this gap, silently,
    # until the two overlap and the machine stops booting for reasons
    # that look nothing like "the image got bigger".
    gap = ORG - (SACC + 256)
    if gap < 0:
        bad.append(f"the image starts at ${ORG:04X} and system storage runs "
                   f"to ${SACC + 255:04X}: they overlap by {-gap} bytes. "
                   f"BASIC has to shrink, or the map and system storage "
                   f"have to move down.")
    # The threshold was 256 and tripped at 208 on 2026-08-16, which was
    # the point of it: it forced the ask rule 5 requires. The decision
    # was to hold -- BASIC is finished, the demos are verification, and
    # FREE stays 38,400 -- so the line sits at 128 now: today's 208 is
    # accepted, and any future growth past ~80 bytes forces the
    # conversation again before the gap can close silently.
    elif gap < 128:
        bad.append(f"only {gap} bytes between system storage "
                   f"(${SACC + 255:04X}) and the image (${ORG:04X}). That is "
                   f"the growth room BASIC has left; move the map down "
                   f"before adding to it.")

    sysbot = sym("SYSBOT")
    if sysbot is not None and sysbot != SCREEN:
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
        p2, t2 = org_asm(write=True)
        print(f"  wrote {os.path.relpath(p2, ROOT)}: "
              f"{t2.splitlines()[-1].strip()}")
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
