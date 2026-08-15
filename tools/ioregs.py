#!/usr/bin/env python3
"""The I/O register map, taken from the hardware that decodes it.

    python tools/ioregs.py            check the RTL and the software agree
    python tools/ioregs.py --emit     rewrite docs/04a-registers.md
    python tools/ioregs.py --list     print what it found

**The RTL is normative here, and that is the whole point.** A keyword
that drifts from its documentation is a bad reference; a register
address that drifts from the hardware is a program poking the wrong
peripheral, on the board, where no simulation need notice. `tools/
opcodes.py` already treats one table as the truth and checks the rest
against it; this is the same arrangement for `$FE00-$FEFF`.

## Where the addresses come from

Every peripheral declares its own offsets as Verilog localparams, and
**the value is already the page offset** -- `A_IDX = 8'h50` in
`cool8_snd.v` is `$FE50`, no base to add and no wiring to infer. So the
addresses are read, not declared, and cannot be got wrong here.

What a `//:` comment supplies is the *name* software should use for it
and one line on what it does:

    localparam [7:0] A_IDX  = 8'h50;    //: SND_IDX   voice select

**A register without one fails the check.** New hardware cannot appear
without saying what it is, which is the same bargain `tools/vocab.py`
makes for keywords.

## What is checked

  * Every RTL register carries a `//:` line.
  * No two registers claim one address.
  * **Every `$FExx` equate in `sw/` lands on an address the hardware
    actually decodes.** An equate naming a register that does not exist
    is the failure this file is really here to catch.
  * No one software name is used for two different addresses.

Aliases are reported rather than refused: `$FE10` is `VID_MODE` in the
boot ROM and `GVMODE` in the interpreter, and twelve registers are like
that. Two spellings of one address is untidy; a spelling that points
at the wrong address is a bug, and only the second is worth failing a
build over. The generated table lists both so the untidiness is at
least visible.
"""

import argparse
import glob
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RTL = os.path.join(ROOT, "rtl", "soc", "*.v")
DOC = os.path.join(ROOT, "docs", "04a-registers.md")
ASM = os.path.join(ROOT, "sw", "io.asm")
BAS = os.path.join(ROOT, "sw", "io.bas")

# **The page base lives here and nowhere else.** It used to be the
# literal `0xFE00` here, `8'hFE` twice in the RTL, `0xFE00` twice in
# `rust/`, and sixty hand-written `$FExx` equates across `sw/` -- which
# is what made moving the page look like a large job instead of a
# one-line one ([D67]). The equates are generated from this now, so the
# software side of a move is regenerating a file.
IO_BASE = 0xFF00
IO_TOP = 0xFFF7                     # the last address the page decodes

# **The page moved from $FE00 to $FF00, and the vectors did not move.**
# The image ceiling was $FDFF *because* I/O started at $FE00, and
# $FF00-$FFF7 was a stranded 248-byte RAM island above it -- outside the
# boot ROM's $0000-$EFFF clear, which is exactly why it needed a hand
# allocation of its own. Putting the page at the top and stopping it
# short of $FFF8 makes RAM contiguous to $FEFF, hands the image 256
# bytes, hands the ROM 256 contiguous bytes, and leaves RESET/NMI/IRQ/BRK
# where the CPU core reads them -- so `rtl/core/` is untouched, which is
# the whole reason for the eight-byte notch ([D67]).

PARAM = re.compile(r"(A_[A-Z0-9_]+)\s*=\s*8'h([0-9A-Fa-f]{2})")
NOTE = re.compile(r"//:\s*(\S+)\s*(.*?)\s*$")
# A software equate naming a register, in either dialect and in either
# form: the literal `$FExx` that predates the generated file, and the
# `IOBASE + $xx` the generated file emits. Both are recognised so the
# check keeps biting during the transition and after it. Lines that
# merely POKE a literal are not declarations and are counted separately.
EQU = re.compile(r"^\s*(?:CONST\s+|\.equ\s+)?([A-Za-z_][A-Za-z0-9_]*)"
                 r"\s*,?\s*=\s*,?\s*(?:\$%02X([0-9A-Fa-f]{2})"
                 r"|IOBASE\s*\+\s*\$([0-9A-Fa-f]{1,2}))\b"
                 % (IO_BASE >> 8))
USES = re.compile(r"\b(POKE|PEEK|VPOKE|VPEEK)\b")


def registers():
    """{offset: {param, addr, name, note, module}} from the RTL."""
    out = {}
    for path in sorted(glob.glob(RTL)):
        mod = os.path.basename(path)
        for line in io.open(path, encoding="utf-8"):
            m = PARAM.search(line)
            if not m:
                continue
            n = NOTE.search(line)
            off = int(m.group(2), 16)
            out[off] = {"param": m.group(1), "addr": IO_BASE + off,
                        "name": n.group(1) if n else None,
                        "note": n.group(2) if n else "",
                        "module": mod,
                        "dup": off in out}
    return out


def addr_of(name):
    """The address of a register, by the name the hardware gave it.

    For Python that has to know one -- a harness reading `SYSCTRL` back,
    a test typing a `POKE` at the machine. Those were literals
    (`m.bus.read(0xFE00)`), which is the same fault as a literal in
    assembly and fails the same silent way when the page moves (D67).
    """
    for r in registers().values():
        if r["name"] == name:
            return r["addr"]
    raise KeyError("no register named %r; see python tools/ioregs.py --list"
                   % name)


def software():
    """{offset: {name: [files]}} for every $FExx equate in sw/."""
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "sw", "*.asm")) +
                       glob.glob(os.path.join(ROOT, "sw", "*.bas"))):
        base = os.path.basename(path)
        for line in io.open(path, encoding="utf-8"):
            if USES.search(line):
                continue
            m = EQU.match(line)
            if not m:
                continue
            off = int(m.group(2) or m.group(3), 16) & 0xFF
            out.setdefault(off, {}).setdefault(m.group(1), []).append(base)
    return out


def literals():
    """Bare `$FExx` uses in sw/ that are not equates: `POKE $FE1E, 1`,
    `LD R0,[$FE11]`.

    **These are what makes moving the page dangerous, and the check used
    to skip them on purpose** -- `software()` ignores any line with a
    POKE or PEEK on it, because such a line is a use and not a
    declaration. That was right for the question it was asked ("does
    software name an address nothing decodes") and wrong for this one: a
    literal is exactly the thing that keeps pointing at the old address
    after the base changes, silently, with no symbol to fail on.

    Returns {file: [(line, address)]} so the remaining work is countable
    rather than estimated ([D67]).
    """
    out = {}
    # Only addresses the page actually decodes. The page stops eight
    # bytes short of the top, so `$FFFC` in `POKE $FFFC, iisr AND 255`
    # is the IRQ vector in RAM and not a register at all -- matching the
    # whole high page would report every vector install as a fault.
    # Not `#$FFF0`, which is the immediate -16 in `ADDW X,#$FFF0` and no
    # kind of address. Only a bare `$FFxx` -- `[$FF11]` in assembly, a
    # POKE or PEEK argument in BASIC -- is a reference to the page.
    lit = re.compile(r"(?<!#)\$([0-9A-Fa-f]{4})\b")
    for path in sorted(glob.glob(os.path.join(ROOT, "sw", "*.asm")) +
                       glob.glob(os.path.join(ROOT, "sw", "*.bas"))):
        base = os.path.basename(path)
        if base in ("io.asm", "io.bas"):
            continue
        for n, line in enumerate(io.open(path, encoding="utf-8"), 1):
            code = line.split(";")[0].split("'")[0]
            if EQU.match(code):
                continue
            for m in lit.finditer(code):
                a = int(m.group(1), 16)
                if IO_BASE <= a <= IO_TOP:
                    out.setdefault(base, []).append((n, a))
    return out


def _code(line, path):
    """(code, comment) for a source line, quotes respected.

    The assembler's own splitter for `.asm`, because a `;` inside a
    character literal is not a comment and getting that wrong here would
    rewrite the wrong half of the line. BASIC's comment is `'`, which is
    never a quote character in that language, so the only thing to skip
    past is a `"` string.
    """
    # **The assembler's splitter rstrips the comment**, which is right
    # for assembling and destroys a file when the two halves are joined
    # back up: every commented line loses its newline and the file
    # becomes one line. Found the hard way, on interp.asm. So the split
    # here is by index, and the two halves always reconstruct the line.
    if path.endswith(".asm"):
        import cool8asm
        code, _ = cool8asm.Assembler.split(line)
        return line[:len(code)], line[len(code):]
    q = False
    for i, ch in enumerate(line):
        if ch == '"':
            q = not q
        elif ch == "'" and not q:
            return line[:i], line[i:]
    return line, ""


def name_literals(write=False):
    """Rewrite every bare `$FExx` use in sw/ to its generated name.

    The conversion lives next to the detector because the mapping is
    already here: `registers()` knows which name the hardware gave each
    offset, so there is nothing to decide per site and nothing to get
    wrong by hand across eighty-seven of them. Comments are left alone
    -- several of them are *about* the page and would read as nonsense
    with a register name spliced in.

    Returns {file: [(line, addr, name)]}, and with `write` also saves.
    """
    regs = {r["addr"]: (r["name"] or r["param"]) for r in registers().values()}
    # Only addresses the page actually decodes. The page stops eight
    # bytes short of the top, so `$FFFC` in `POKE $FFFC, iisr AND 255`
    # is the IRQ vector in RAM and not a register at all -- matching the
    # whole high page would report every vector install as a fault.
    # Not `#$FFF0`, which is the immediate -16 in `ADDW X,#$FFF0` and no
    # kind of address. Only a bare `$FFxx` -- `[$FF11]` in assembly, a
    # POKE or PEEK argument in BASIC -- is a reference to the page.
    lit = re.compile(r"(?<!#)\$([0-9A-Fa-f]{4})\b")
    done, missing = {}, []
    for path in sorted(glob.glob(os.path.join(ROOT, "sw", "*.asm")) +
                       glob.glob(os.path.join(ROOT, "sw", "*.bas"))):
        base = os.path.basename(path)
        if base in ("io.asm", "io.bas"):
            continue
        out, hit = [], []
        for n, line in enumerate(io.open(path, encoding="utf-8",
                                         newline="").readlines(), 1):
            code, comment = _code(line, base)
            if EQU.match(code):
                out.append(line)
                continue

            def sub(m, _n=n, _h=hit):
                a = int(m.group(1), 16)
                if not (IO_BASE <= a <= IO_TOP):
                    return m.group(0)
                if a not in regs:
                    missing.append((base, _n, a))
                    return m.group(0)
                _h.append((_n, a, regs[a]))
                return regs[a]

            out.append(lit.sub(sub, code) + comment)
        if hit:
            done[base] = hit
            if write:
                io.open(path, "w", encoding="utf-8",
                        newline="").write("".join(out))
    for base, n, a in missing:
        print("  %s:%d $%04X is decoded by no peripheral -- left alone"
              % (base, n, a))
    return done


def check():
    bad = []
    regs, sw = registers(), software()

    # Two localparams on one address: the tool cannot tell which is
    # meant and neither can the bus.
    seen = {}
    for path in sorted(glob.glob(RTL)):
        for line in io.open(path, encoding="utf-8"):
            m = PARAM.search(line)
            if not m:
                continue
            off = int(m.group(2), 16)
            key = (os.path.basename(path), m.group(1))
            if off in seen and seen[off] != key:
                bad.append("$%04X is claimed by %s %s and %s %s" %
                           (IO_BASE + off, seen[off][0], seen[off][1], key[0], key[1]))
            seen[off] = key

    for off in sorted(regs):
        if not regs[off]["name"]:
            bad.append("$%04X %-10s in %s has no //: name" %
                       (IO_BASE + off, regs[off]["param"],
                        regs[off]["module"]))

    # The one that matters: software naming an address nothing decodes.
    for off in sorted(sw):
        if off not in regs:
            who = sorted({f for v in sw[off].values() for f in v})
            bad.append("$%04X is named by %s but no peripheral decodes "
                       "it" % (IO_BASE + off, ", ".join(sorted(sw[off])) +
                               " (" + ", ".join(who) + ")"))

    # One name, two addresses -- a real defect, unlike two names for one.
    where = {}
    for off, names in sw.items():
        for n in names:
            where.setdefault(n, set()).add(off)
    for n, offs in sorted(where.items()):
        if len(offs) > 1:
            bad.append("%s is used for %s" %
                       (n, " and ".join("$%04X" % (IO_BASE + o) for o in sorted(offs))))

    # **The documents write addresses down, so the documents get checked
    # too.** A BASIC program has no symbolic names -- a user reading
    # docs/13-basic.md types the number -- so those numbers are the one
    # place a literal is unavoidable, and therefore the one place drift
    # is invisible. It happened: [D67] moved the page to $FF00 and every
    # `POKE $FE1E` in the BASIC reference stayed behind, pointing a user
    # at a page nothing answers at. Fourteen of them.
    for rel in ("docs/13-basic.md",):
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        text = io.open(path, encoding="utf-8").read()
        live = {r["addr"] for r in regs.values()}
        # **Keyed on `POKE`, not on the address range.** Ranged on the
        # I/O page it would pass a stale address for free: the whole
        # failure mode is a number left behind at the *old* page, which
        # is below the new one and so never looked at. This caught
        # nothing until it stopped asking where the address is and
        # started asking what the document tells a user to do with it.
        for m in re.finditer(r"POKE\s+\$(F[0-9A-F]{3})", text):
            a = int(m.group(1), 16)
            if a not in live:
                bad.append("%s says POKE $%04X, and no peripheral decodes "
                           "that" % (rel, a))

    if not bad:
        for path, want in ((DOC, markdown()), (ASM, assembly() + "\n"),
                           (BAS, basic() + "\n")):
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            if not os.path.exists(path):
                bad.append("%s is missing: "
                           "run python tools/ioregs.py --emit" % rel)
            elif io.open(path, encoding="utf-8").read() != want:
                bad.append("%s is stale: "
                           "run python tools/ioregs.py --emit" % rel)

    # **A bare literal is what survives a move.** An equate that names a
    # register is checked against the hardware above; a `POKE $FE1E, 1`
    # is not, and would go on addressing the old page after the base
    # changed, silently, with no symbol to fail on. There were 87 when
    # this check was written -- 44 in basic.bas, 22 in lib.bas, 17 in
    # demo.asm, 4 in interp.asm -- and `--name-literals` converted them
    # all, so the gate is now at zero and stays there ([D67]).
    for f, hits in sorted(literals().items()):
        for n, a in hits:
            bad.append("%s:%d uses $%04X directly -- run "
                       "python tools/ioregs.py --name-literals" % (f, n, a))

    for b in bad:
        print("  " + b)
    print("%s -- %d registers, %d named in software, %d problems" %
          ("FAIL" if bad else "ok", len(regs), len(software()), len(bad)))
    return 1 if bad else 0


def assembly():
    """`sw/io.asm` -- every register as `NAME = IOBASE + $xx`.

    **The software side of the I/O page, generated from the hardware
    that decodes it.** Before this the addresses were sixty hand-written
    `$FExx` equates spread over four `.asm` files and `basic.bas`, each
    file carrying its own subset under its own spelling, and moving the
    page meant editing all of them and hoping. Now the offsets come from
    the RTL, the base comes from `IO_BASE` above, and a move is this
    file regenerated ([D67]).

    Canonical names only. The interpreter's `G`-prefixed shorthand --
    `GVMODE` for `VID_MODE`, eighteen of them -- is gone rather than
    emitted alongside: two spellings of one address is an untidiness
    [04a-registers.md](../docs/04a-registers.md) used to have a section
    apologising for, and generating both would have made the generator
    read its own output to find out what to generate.
    """
    regs = registers()
    o = []
    o.append("; ------------------------------------------------------"
             "---------------")
    o.append("; io.asm -- the I/O page, generated by tools/ioregs.py.")
    o.append(";")
    o.append("; **Do not edit.** The offsets are read out of the Verilog"
             " localparams")
    o.append("; that decode them (rtl/soc/*.v), the base is IO_BASE in"
             " the generator,")
    o.append("; and `poe check` fails if this file is stale.")
    o.append(";")
    o.append("; Every address is IOBASE + offset rather than a literal,"
             " so the page")
    o.append("; can move by changing one constant on each side -- which"
             " is the whole")
    o.append("; point: it used to be sixty literals across five files"
             " ([D67]).")
    o.append("; ------------------------------------------------------"
             "---------------")
    o.append("")
    o.append("IOBASE  = $%04X" % IO_BASE)
    o.append("")

    bymod = {}
    for off, r in regs.items():
        bymod.setdefault(r["module"], []).append(off)
    for mod in sorted(bymod):
        o.append("; ---- %s" % mod)
        for off in sorted(bymod[mod]):
            r = regs[off]
            name = r["name"] or r["param"]
            o.append("%-11s = IOBASE + $%02X       ; %s" %
                     (name, off, r["note"]))
        o.append("")
    return "\n".join(o)


def basic():
    """`sw/io.bas` -- the same registers as COOL8 BASIC `CONST`s.

    **CONSTs rather than EXTERNs, and the difference is 89 bytes.** A
    `CONST` folds at compile time, so `POKE VID_MODE, x` assembles a
    literal address; an `EXTERN` is a link-time symbol `tools/cool8bas.py`
    cannot fold, and switching `sw/basic.bas`'s eight register names to
    EXTERN grew the image from 23,541 to 23,630 -- measured, not
    predicted. So BASIC gets its own generated file rather than reaching
    into the assembly one, and the address is still written down once.
    """
    regs = registers()
    o = []
    o.append("' ----------------------------------------------------"
             "-----------------")
    o.append("' io.bas -- the I/O page for COOL8 BASIC, generated by"
             " tools/ioregs.py.")
    o.append("'")
    o.append("' **Do not edit.** Same source as sw/io.asm: the Verilog"
             " localparams in")
    o.append("' rtl/soc/*.v that decode these addresses. `poe check`"
             " fails if stale.")
    o.append("'")
    o.append("' CONST and not EXTERN on purpose -- a CONST folds and an"
             " EXTERN does")
    o.append("' not, which was worth 89 bytes of image ([D67]).")
    o.append("' ----------------------------------------------------"
             "-----------------")
    o.append("")
    for off in sorted(regs):
        r = regs[off]
        o.append("CONST %-12s = $%04X       ' %s" %
                 (r["name"] or r["param"], r["addr"], r["note"]))
    return "\n".join(o)


def markdown():
    regs, sw = registers(), software()
    o = []
    o.append("# 04a. The I/O registers")
    o.append("")
    o.append("**Generated by `tools/ioregs.py` from the Verilog that "
             "decodes them — do not edit.** `poe build` regenerates it "
             "and `poe check` fails if it is stale, if a peripheral has "
             "gained a register without a name, or if anything in `sw/` "
             "names an address no hardware answers at.")
    o.append("")
    o.append("`$%04X-$%04X` is decoded on the bus ahead of memory, so "
             "these addresses are never RAM. Each peripheral's Verilog "
             "gives its offsets as localparams whose value *is* the page "
             "offset — `A_IDX = 8'h50` is `$%04X` — so the addresses "
             "here are read from the hardware rather than restated."
             % (IO_BASE, IO_TOP, IO_BASE + 0x50))
    o.append("")
    o.append("The page stops at `$%04X`, eight bytes short of the top: "
             "`$FFF8-$FFFF` stay RAM because the CPU fetches its reset "
             "and interrupt vectors from there, and leaving them alone "
             "is what let the page move without touching `rtl/core/` "
             "([D67](01-decisions.md))." % IO_TOP)
    o.append("")
    o.append("What the registers *do* at the bit level is "
             "[04-system.md](04-system.md), written by hand.")
    o.append("")

    bymod = {}
    for off, r in regs.items():
        bymod.setdefault(r["module"], []).append(off)

    for mod in sorted(bymod):
        o.append("## `%s`" % mod)
        o.append("")
        o.append("| | | |")
        o.append("|---|---|---|")
        for off in sorted(bymod[mod]):
            r = regs[off]
            names = sorted(sw.get(off, {}))
            canon = r["name"] or "?"
            extra = [n for n in names if n != canon]
            label = "`%s`" % canon
            if extra:
                label += " *(also %s)*" % ", ".join("`%s`" % e for e in extra)
            elif not names:
                label += " —"
            o.append("| `$%04X` | %s | %s |" % (r["addr"], label, r["note"]))
        o.append("")

    unreached = [off for off in sorted(regs) if off not in sw]
    o.append("## Registers no software name reaches")
    o.append("")
    o.append("%d of %d. The hardware decodes them and nothing in `sw/` "
             "has an equate for one, so reaching them means a bare "
             "`POKE $FExx`. Not a fault — several are read-only status "
             "or set once by the boot ROM — but the list is generated "
             "so it is a decision rather than an oversight."
             % (len(unreached), len(regs)))
    o.append("")
    o.append(", ".join("`$%04X` %s" % (regs[o_]["addr"], regs[o_]["name"])
                       for o_ in unreached) + ".")
    o.append("")

    aliased = [off for off in sorted(regs)
               if len([n for n in sw.get(off, {})]) > 1]
    o.append("## Registers with more than one software name")
    o.append("")
    o.append("%d of them, and all the same split: the interpreter uses "
             "its own `G`-prefixed shorthand while the boot ROM, the "
             "demo and the library use the longer name. Two spellings "
             "of one address is untidy but harmless, so the check "
             "reports rather than refuses; a spelling pointing at the "
             "*wrong* address is what it fails on." % len(aliased))
    o.append("")
    o.append("| | |")
    o.append("|---|---|")
    for off in aliased:
        o.append("| `$%04X` | %s |" %
                 (regs[off]["addr"],
                  " · ".join("`%s`" % n for n in sorted(sw[off]))))
    o.append("")
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--emit", action="store_true",
                    help="rewrite docs/04a-registers.md")
    ap.add_argument("--check", action="store_true",
                    help="verify the RTL and the software agree")
    ap.add_argument("--list", action="store_true",
                    help="print the parsed registers")
    ap.add_argument("--name-literals", action="store_true",
                    help="rewrite bare $FExx uses in sw/ to their names")
    a = ap.parse_args()

    if a.name_literals:
        done = name_literals(write=True)
        for base, hits in sorted(done.items()):
            print("  %-12s %3d" % (base, len(hits)))
        print("  %d converted" % sum(len(v) for v in done.values()))
        return 0

    if a.list:
        regs, sw = registers(), software()
        for off in sorted(regs):
            r = regs[off]
            print("$%04X %-11s %-12s %-18s %s" %
                  (r["addr"], r["param"], r["name"] or "-",
                   ",".join(sorted(sw.get(off, {}))) or "-", r["note"]))
        return 0
    if a.emit:
        io.open(DOC, "w", encoding="utf-8", newline="\n").write(markdown())
        io.open(ASM, "w", encoding="utf-8", newline="\n").write(
            assembly() + "\n")
        io.open(BAS, "w", encoding="utf-8", newline="\n").write(
            basic() + "\n")
        print("wrote %s, %s and %s" % (os.path.relpath(DOC, ROOT),
                                       os.path.relpath(ASM, ROOT),
                                       os.path.relpath(BAS, ROOT)))
        return 0
    return check()


if __name__ == "__main__":
    sys.exit(main())
