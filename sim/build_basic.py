#!/usr/bin/env python3
"""Build the system image and the bootable file, and report the sizes.

    python sim/build_basic.py          (or: poe build)

`sim/test_basic.py` builds `basic.bin` as a side effect of testing it,
which is fine for a test and no use at all when what you want is the
artifact. This produces both of them and prints what they cost, because
the size at every milestone is the number this project is judged on --
the system has to stay inside `$A000-$FDFF` and nothing warns you as it
fills.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import mkboot                                              # noqa: E402
import test_basic as B                                     # noqa: E402

from memmap import ORG, TOP                                # noqa: E402


def main():
    code, syms = B.build()
    boot = mkboot.build(code, dest=ORG, build_dir=BUILD)
    with open(os.path.join(BUILD, "BOOT.BIN"), "wb") as fh:
        fh.write(boot)

    end = ORG + len(code)
    free = TOP - end
    print(f"  basic.bin  {len(code):>7,} bytes  ${ORG:04X}-${end - 1:04X}")
    print(f"  BOOT.BIN   {len(boot):>7,} bytes  "
          f"({len(boot) - len(code)} of relocating stub)")
    print(f"  free       {free:>7,} bytes  to ${TOP - 1:04X}")
    if "--by-file" in sys.argv:
        by_file(syms)
    if "--by-command" in sys.argv:
        by_command(syms)
    if free < 0:
        print("  the system does not fit below the I/O page")
        return 1
    return 0


def by_command(syms):
    """What each keyword's handler costs, from the symbol table.

        python sim/build_basic.py --by-command

    **The drop table in docs/13-basic.md section 10 was five guesses**,
    and the one figure ever checked was 1.7x too high because shared
    code had been counted against the feature that happened to call it.
    This measures instead: `tools/vocab.py` knows which handler each
    keyword dispatches to, and the symbol table knows where every label
    landed, so a handler's own span is the distance to whatever label
    comes next.

    **Read it as a floor.** The span covers the handler and nothing
    else, which is right for shared code -- `earg`, `retnum` and
    `udiv16` stay behind because the rest of the language still calls
    them -- but it stops at the first private helper the handler owns,
    so a command with subroutines of its own is worth more than this
    says. `LINE` measures 32 here and reclaims 274 when actually
    deleted.

    **The real figure needs a deletion**, and the measured ones are in
    docs/13-basic.md section 10: remove the handler, point its table
    entry at `bad`, then remove whatever that orphaned -- iteratively,
    counting references across *every* file in sw/, because the editor
    and the boot ROM call into the interpreter too. Stopping at the
    next handler instead is what the old guesses effectively did, and
    it is wrong: `earg` and `negp16` sit inside h_line's reach,
    `retnum` inside h_gtext's, `pixxy` inside h_vpoke's, and all three
    are shared.
    """
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import vocab                                            # noqa: E402

    stmts, fns = vocab.vocabulary()
    marks = sorted((a, n) for n, a in syms.items())
    addr = {n: a for n, a in ((n, a) for a, n in marks)}

    def span(label, stop_at=None):
        a = syms.get(label.lower())
        if a is None:
            return None
        for b, n in marks:
            if b > a and (stop_at is None or n in stop_at):
                return b - a
        return None

    handlers = {e["handler"] for e in stmts + fns} - {"bad"}
    hset = {h.lower() for h in handlers}

    rows = []
    for e in stmts + fns:
        h = e["handler"]
        if h == "bad":
            continue
        own, blk = span(h), span(h, hset)
        if own is None:
            continue
        rows.append((own, blk or own, e["name"], h))

    # One handler can serve several keywords (h_sub is SUB and FUNCTION,
    # h_else is ELSE, ELSEIF and DATA), so fold them or the total lies.
    seen, folded = set(), []
    for own, blk, name, h in sorted(rows, reverse=True):
        if h in seen:
            continue
        seen.add(h)
        also = [n for o, b, n, hh in rows if hh == h and n != name]
        folded.append((own, blk, name + ("+" + "+".join(also) if also else ""),
                       h))

    print()
    print("  What each command's handler costs, biggest first:")
    print()
    print(f"    {'command':<18} {'own':>6}")
    for own, blk, name, h in folded[:22]:
        print(f"    {name:<18} {own:>6,}")
    print()
    print(f"    {'measured total':<18} {sum(o for o, _, _, _ in folded):>6,}")
    print()
    print("    The handler alone, so this is a floor: private helpers")
    print("    are not counted, and neither is shared code -- removing a")
    print("    command reclaims neither earg nor retnum nor udiv16. The")
    print("    measured figures, from actually deleting each one, are in")
    print("    docs/13-basic.md section 10.")


def by_file(syms):
    """What each source file contributes, from the symbol table.

        python sim/build_basic.py --by-file

    **This exists because the drop table in docs/13-basic.md section 10
    was guesswork.** Five of its six figures had never been checked and
    the one that was came back 1.7x too high, because shared code was
    being counted against whichever feature happened to call it. A file's
    labels all land in one contiguous run, so the distance from its first
    to its last is what removing the file would actually return -- and
    nothing shared with the rest of the system is inside that span.

    It is an upper bound, not a promise: a file's callers still have to
    go, and page-0 and token-table entries are not counted here.
    """
    import glob
    import re

    # **Sum the gaps, do not measure the span.** A file's labels are not
    # necessarily contiguous -- monitor.asm has three of them spread
    # across a range that encloses two other files, so its span read as
    # 8,616 bytes when its own code is a fraction of that. Sorting every
    # label by address and giving each gap to the file that owns the
    # label opening it is right however the files interleave.
    # **Only labels inside the image count.** Page-0 equates and the
    # I/O page are in the symbol table too, and letting them in made
    # every gap from $0000 upward land on some file -- which is how a
    # first version reported 41 KB for a file that is not in the build
    # at all. A file whose name matches a symbol it does not own is the
    # same trap, so a file needs several labels in range to be believed.
    top = max(v for v in syms.values() if v < TOP)
    owner, count = {}, {}
    for path in sorted(glob.glob(os.path.join(ROOT, "sw", "*.asm"))):
        base = os.path.basename(path)
        for n in re.findall(r"^([A-Za-z_][A-Za-z0-9_]*):",
                            open(path, encoding="utf-8").read(), re.M):
            a = syms.get(n.lower())
            if a is not None and ORG <= a <= top:
                owner.setdefault(a, base)
                count[base] = count.get(base, 0) + 1
    owner = {a: f for a, f in owner.items() if count[f] >= 4}
    marks = sorted(owner)
    total = {}
    for i, a in enumerate(marks[:-1]):
        total[owner[a]] = total.get(owner[a], 0) + (marks[i + 1] - a)
    rows = sorted(((v, k) for k, v in total.items()), reverse=True)
    print()
    print("  What each source file costs the image:")
    print()
    for v, k in rows:
        print(f"    {k:<16} {v:>6,} bytes")
    print(f"    {'attributed':<16} {sum(total.values()):>6,} bytes")
    print()
    print("    Each gap between consecutive labels goes to the file that")
    print("    opened it, so interleaving does not distort a total. It is")
    print("    still an upper bound on removal: the callers have to go")
    print("    too, and page-0 and token-table entries are not counted.")


if __name__ == "__main__":
    sys.exit(main())
