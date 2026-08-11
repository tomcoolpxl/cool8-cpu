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

PARAM = re.compile(r"(A_[A-Z0-9_]+)\s*=\s*8'h([0-9A-Fa-f]{2})")
NOTE = re.compile(r"//:\s*(\S+)\s*(.*?)\s*$")
# A software equate: NAME = $FExx, in either dialect. Lines that merely
# POKE a literal are not declarations and are counted separately.
EQU = re.compile(r"^\s*(?:CONST\s+|\.equ\s+)?([A-Za-z_][A-Za-z0-9_]*)"
                 r"\s*,?\s*=\s*,?\s*\$(FE[0-9A-Fa-f]{2})\b")
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
            out[off] = {"param": m.group(1), "addr": 0xFE00 + off,
                        "name": n.group(1) if n else None,
                        "note": n.group(2) if n else "",
                        "module": mod,
                        "dup": off in out}
    return out


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
            off = int(m.group(2), 16) & 0xFF
            out.setdefault(off, {}).setdefault(m.group(1), []).append(base)
    return out


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
                bad.append("$FE%02X is claimed by %s %s and %s %s" %
                           (off, seen[off][0], seen[off][1], key[0], key[1]))
            seen[off] = key

    for off in sorted(regs):
        if not regs[off]["name"]:
            bad.append("$FE%02X %-10s in %s has no //: name" %
                       (off, regs[off]["param"], regs[off]["module"]))

    # The one that matters: software naming an address nothing decodes.
    for off in sorted(sw):
        if off not in regs:
            who = sorted({f for v in sw[off].values() for f in v})
            bad.append("$FE%02X is named by %s but no peripheral decodes "
                       "it" % (off, ", ".join(sorted(sw[off])) +
                               " (" + ", ".join(who) + ")"))

    # One name, two addresses -- a real defect, unlike two names for one.
    where = {}
    for off, names in sw.items():
        for n in names:
            where.setdefault(n, set()).add(off)
    for n, offs in sorted(where.items()):
        if len(offs) > 1:
            bad.append("%s is used for %s" %
                       (n, " and ".join("$FE%02X" % o for o in sorted(offs))))

    if not bad:
        if not os.path.exists(DOC):
            bad.append("docs/04a-registers.md is missing: "
                       "run python tools/ioregs.py --emit")
        elif io.open(DOC, encoding="utf-8").read() != markdown():
            bad.append("docs/04a-registers.md is stale: "
                       "run python tools/ioregs.py --emit")

    for b in bad:
        print("  " + b)
    print("%s -- %d registers, %d named in software, %d problems" %
          ("FAIL" if bad else "ok", len(regs), len(software()), len(bad)))
    return 1 if bad else 0


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
    o.append("`$FE00-$FEFF` is decoded on the bus ahead of memory, so "
             "these addresses are never RAM. Each peripheral's Verilog "
             "gives its offsets as localparams whose value *is* the page "
             "offset — `A_IDX = 8'h50` is `$FE50` — so the addresses "
             "here are read from the hardware rather than restated.")
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
    a = ap.parse_args()

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
        print("wrote %s" % os.path.relpath(DOC, ROOT))
        return 0
    return check()


if __name__ == "__main__":
    sys.exit(main())
