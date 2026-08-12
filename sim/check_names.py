#!/usr/bin/env python3
"""Every global name in the compiler's sources, declared once.

    python sim/check_names.py

COOL8 BASIC is case-insensitive, so `CONST NLAB` in one file and
`DIM nlab` in another are one name -- and the DIM wins, silently. That
has cost two debugging sessions already: `NSYM`/`nsym` made the symbol
table look full the moment it was empty, and `NLAB`/`nlab` turned the
emitter's table length into a variable and hung it.

Nothing in the language catches this, so this does. Only top-level
declarations count; a DIM inside a SUB is a frame slot and may repeat as
often as it likes.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# basic.bas is gone: the editor is sw/*.asm now ([D68]). What is left is
# the compiler, which is still written in BASIC and still needs this.
FILES = ["chars.bas", "lex.bas", "emit.bas", "comp.bas"]
DECL = re.compile(r"^\s*(CONST|DIM)\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
OPEN = re.compile(r"^\s*(INLINE\s+)?(SUB|FUNCTION)\s", re.I)
SHUT = re.compile(r"^\s*END\s+(SUB|FUNCTION)\s*$", re.I)


def globals_in(path, name):
    """Top-level CONST and DIM, with the SUB bodies skipped."""
    out, depth = [], 0
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        if OPEN.match(line):
            depth += 1
            continue
        if SHUT.match(line):
            depth = max(0, depth - 1)
            continue
        if depth:
            continue
        m = DECL.match(line)
        if m:
            out.append((m.group(2).lower(), m.group(1).upper(), name, n))
    return out


def main():
    seen, bad = {}, []
    for f in FILES:
        path = os.path.join(ROOT, "sw", f)
        if not os.path.exists(path):
            continue
        for low, kind, fn, n in globals_in(path, f):
            if low in seen:
                pk, pf, pn = seen[low]
                bad.append(f"  {low}: {pk} in {pf}:{pn}, {kind} in {fn}:{n}")
            else:
                seen[low] = (kind, fn, n)
    for b in bad:
        print(b)
    print(f"  {len(seen)} global names, {len(bad)} collisions")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
