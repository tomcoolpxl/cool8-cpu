#!/usr/bin/env python3
"""Build the system image and the bootable file, and report the sizes.

    python sim/build_basic.py          (or: poe build)

`sim/test_basic.py` builds `basic.bin` as a side effect of testing it,
which is fine for a test and no use at all when what you want is the
artifact. This produces both of them and prints what they cost, because
the size at every milestone is the number this project is judged on --
the image grows *down* from `$FEFF` into a finite gap above system
storage, and nothing else warns you as it closes.

It also brings `sw/org.asm` and `sw/sysbot.asm` up to date, because
`test_basic.build()` does: they are inputs to the assembly and derived
from it, so a build that assumed some other job had written them first
failed whenever the size of BASIC changed and passed on the next run.
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

import memmap                                              # noqa: E402

# **`memmap.ORG` at the point of use, never a local copy.** It is
# derived from the size of the image, and `test_basic.build()` brings
# the generated `.org` up to date as part of building -- so a name bound
# at import time is the origin from *before* that happened. On a tree
# with sw/org.asm missing, this file bound the $A000 fallback, built a
# correct image at $BB8F, and then told the stub to relocate to $A000.
def ORG():
    return memmap.ORG


def TOP():
    return memmap.TOP


def main():
    code, syms = B.build()
    boot = mkboot.build(code, dest=ORG(), build_dir=BUILD)
    with open(os.path.join(BUILD, "BOOT.BIN"), "wb") as fh:
        fh.write(boot)

    end = ORG() + len(code)
    # **The image is top-aligned, so "free to $FEFF" is always zero.**
    # It was the right number when the origin was the constant $A000 and
    # the image grew up towards the I/O page; since [D69] derived the
    # origin the image grows *down*, and the number that can run out is
    # the gap below it -- BASIC's room to grow before it reaches system
    # storage. `memmap --check` fails the build on the same quantity.
    room = ORG() - (memmap.SACC + 256)
    print(f"  basic.bin  {len(code):>7,} bytes  ${ORG():04X}-${end - 1:04X}")
    print(f"  BOOT.BIN   {len(boot):>7,} bytes  "
          f"({len(boot) - len(code)} of relocating stub)")
    print(f"  room       {room:>7,} bytes  to grow down into, before "
          f"system storage at ${memmap.SACC + 255:04X}")
    print(f"  the user's {memmap.usertop() - memmap.PROG + 1:>7,} bytes  "
          f"${memmap.PROG:04X}-${memmap.usertop():04X}, one region")
    free = TOP() - end
    if "--by-file" in sys.argv:
        by_file(syms)
    if "--by-command" in sys.argv:
        by_command(syms)
    if "--by-sub" in sys.argv:
        by_sub(syms)
    if "--by-module" in sys.argv:
        by_module(syms)
    if "--waste" in sys.argv:
        by_waste(syms)
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


def by_sub(syms):
    """What each compiled editor routine costs.

        python sim/build_basic.py --by-sub

    **basic.bas is 52 % of the image**, and it is compiled BASIC where
    interp.asm is hand assembly -- `sim/test_lib.py` measures the same
    program at 704 bytes written by hand and 3,634 compiled, 5.16x. So
    the question "should the editor be assembly" is worth thousands of
    bytes, and it is answered one routine at a time rather than by
    rewriting 12 KB on a ratio measured from a graphics demo.

    This is where to aim. A compiled SUB becomes `s_<name>` with its
    labels as `s_<name>.<something>`, so a routine's span runs to the
    next dot-free symbol and takes its own locals with it.
    """
    marks = sorted((a, n) for n, a in syms.items() if ORG() <= a < TOP())
    tops = [(a, n) for a, n in marks if "." not in n]
    rows = []
    for i, (a, n) in enumerate(tops):
        if not n.startswith("s_"):
            continue
        end = tops[i + 1][0] if i + 1 < len(tops) else None
        if end:
            rows.append((end - a, n))
    rows.sort(reverse=True)
    print()
    print("  What each compiled editor routine costs:")
    print()
    for size, n in rows[:24]:
        print(f"    {n[2:]:<20} {size:>6,}")
    print()
    print(f"    {'these':<20} {sum(r[0] for r in rows[:24]):>6,}")
    print(f"    {'all ' + str(len(rows)):<20} {sum(r[0] for r in rows):>6,}")
    print()
    print("    Hand-write one and compare: that is the editor's own")
    print("    density ratio, where 5.16x is demo.bas's and demo.bas is")
    print("    array- and call-heavy, which docs/11-compiler.md section")
    print("    5a names as this compiler's worst case.")


# Which module each compiled routine belongs to, per ASM_MOVE_PLAN.md.
# Hand-written because it is a *decision* about where code should live,
# not a fact derivable from the source -- that is exactly what the plan
# is. Everything else about the burn-down is measured.
MODULES = {
    "con": ("setgeom scroll bput putat tilefont emit newline tput curdrw "
            "brepaint cls clearrow putsn puts putn rowaddr dnrow getat "
            "showcur"),
    "kbd": "serialkey getkey waitraw rawkey",
    "token": ("tokenise lookup puttok ishex puttnum isident isalpha hexof "
              "upper isdigit number"),
    "prog": ("storeline list deleterange renumber findline memmove lineno "
             "nextline linelen freebytes new"),
    "edit": ("writelog delchar insch readrow enter lend shiftlbuf backspace "
             "lpos curleft lstart doreset gotoend"),
    "fscmd": ("rewritedir docompact loadcore parsename dodir nextsrc "
              "fetchline savecore loaddata skipsp entpage savedata entpages "
              "wrpage rdpage fssave fsload drivecore fsfind dofree erasesect "
              "eracore fsreadent fserase fsmount"),
    "main": "dodirect runerr dorun errmsg",
}


def by_module(syms):
    """The ASM_MOVE_PLAN.md burn-down, measured.

        python sim/build_basic.py --by-module

    **A hand-maintained burn-down is a table that drifts**, and this
    project has been bitten by every one it has written down -- the drop
    table in 13-basic.md was five guesses, `lowram.asm`'s free-space figure
    was wrong three times running. So the plan states the *grouping*,
    which is a decision, and this measures the *bytes*, which are not.

    A routine that has moved to assembly simply stops being an `s_`
    symbol with a compiled body, so "remaining" falls on its own as the
    port proceeds. Nothing has to be ticked off by hand.
    """
    marks = sorted((a, n) for n, a in syms.items() if ORG() <= a < TOP())
    tops = [(a, n) for a, n in marks if "." not in n]
    size = {}
    for i, (a, n) in enumerate(tops):
        if n.startswith("s_") and i + 1 < len(tops):
            size[n[2:]] = tops[i + 1][0] - a

    owner = {r: m for m, rs in MODULES.items() for r in rs.split()}
    unplaced = sorted(set(size) - set(owner))

    print()
    print("  ASM_MOVE_PLAN.md, measured:")
    print()
    print(f"    {'module':<8} {'routines':>8} {'bytes':>8}")
    total = 0
    for m in MODULES:
        rs = [r for r in MODULES[m].split() if r in size]
        b = sum(size[r] for r in rs)
        total += b
        print(f"    {m:<8} {len(rs):>8} {b:>8,}")
    print(f"    {'total':<8} {len(size):>8} {total:>8,}")
    if unplaced:
        # A routine nobody assigned is the plan going stale against the
        # source, which is the one thing this report cannot measure away.
        print()
        print("    not in any module -- add it to MODULES:")
        print("      " + ", ".join(unplaced))
    print()
    print("    A routine that has moved to assembly stops being an `s_`")
    print("    symbol with a compiled body, so this falls on its own.")


def by_waste(_syms):
    """Where the compiled editor's bytes actually go.

        python sim/build_basic.py --waste

    **[D66] planned a 12 KB hand-port against a density ratio of 2.5-3x
    that was never measured on this code** -- it came from `sw/demo.bas`,
    which docs/11-compiler.md names as the compiler's worst case. The two
    routines actually ported came in at 5.4x (`putn`) and 6.4x
    (`number`), which is a different decision: 11,008 bytes at 5x is
    ~8,800 recoverable, not ~6,000.

    So this asks the prior question -- *why* is it 5x -- by classifying
    what the compiler emitted. The answer is not subtle and it is not
    the algorithms: over half of every compiled routine is moving values
    between stack slots and registers, because there is no register
    allocator. That is a fact about the compiler, and some of it is
    removable without hand-writing anything.

    Two of the patterns are provably dead rather than merely suspicious:

      * `ST [SP+k],Rn` immediately followed by `LD Rn,[SP+k]` -- the
        same register and the same slot, so the load cannot change
        anything.
      * a conditional branch over a `JMP`. The compiler emits this
        because a branch reaches only +/-127; the assembler grows
        branches itself now ([D66]'s own first deliverable), so the
        compiler can emit the branch and let the assembler decide.

    Read the totals as an upper bound on a peephole pass, not as a
    promise: removing an instruction moves every branch after it, and
    the assembler's relaxation has to be re-run to know the real figure.
    """
    import re

    path = os.path.join(BUILD, "basic.asm")
    if not os.path.exists(path):
        print("\n  no generated assembly at", path)
        return

    ins, cur = [], None
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^([A-Za-z_]\w*):", line)
        if m:
            cur = m.group(1)
        mi = re.match(r"^\s+([A-Z][A-Z0-9]*)\s+(.*?)(?:\s*;.*)?$", line.rstrip())
        if mi and cur and cur.startswith("s_"):
            ins.append((mi.group(1), mi.group(2).strip()))

    kinds = {"LD": "move", "ST": "move", "MOV": "move", "PUSH": "move",
             "POP": "move", "LDW": "move", "STW": "move", "MOVW": "move",
             "CLR": "move",
             "ADD": "arith", "SUB": "arith", "ADC": "arith", "SBC": "arith",
             "MUL": "arith", "AND": "arith", "OR": "arith", "XOR": "arith",
             "CMP": "arith", "TST": "arith", "ADDW": "arith",
             "JMP": "flow", "CALL": "flow", "RET": "flow"}
    tally = {}
    for op, _ in ins:
        k = kinds.get(op, "flow" if op.startswith("B") else "other")
        tally[k] = tally.get(k, 0) + 1
    n = len(ins)

    print()
    print("  What the compiled editor spends its instructions on:")
    print()
    for k in ("move", "arith", "flow", "other"):
        v = tally.get(k, 0)
        print(f"    {k:<8} {v:>6,}  {100.0 * v / n:5.1f}%")
    print(f"    {'total':<8} {n:>6,}")

    dead = redundant = 0
    for (o1, a1), (o2, a2) in zip(ins, ins[1:]):
        m1 = re.match(r"^\[SP\+(\d+)\],(R\d)$", a1)
        m2 = re.match(r"^(R\d),\[SP\+(\d+)\]$", a2)
        if (o1 == "ST" and o2 == "LD" and m1 and m2
                and m1.group(1) == m2.group(2) and m1.group(2) == m2.group(1)):
            dead += 1
        if (o1.startswith("B") and o1 != "BRA" and o2 == "JMP"
                and a1.startswith(".")):
            redundant += 1

    print()
    print("  Provably removable, without touching a line of BASIC:")
    print()
    print(f"    store then reload the same register and slot   "
          f"{dead:>5,}  ~{dead * 2:,} bytes")
    print(f"    conditional branch over a JMP, which the        "
          f"{redundant:>5,}  ~{redundant * 3:,} bytes")
    print( "      assembler now relaxes by itself")
    print()
    print(f"    {'':<46} ~{dead * 2 + redundant * 3:,} bytes")
    print()
    print("    An upper bound: removing an instruction moves every")
    print("    branch after it, so the real figure needs a rebuild.")


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
    top = max(v for v in syms.values() if v < TOP())
    owner, count = {}, {}
    # **The .bas sources count too, and leaving them out hid the
    # largest file in the image.** basic.bas is the editor, compiled
    # into the same address space, and it was simply absent from this
    # report -- 13 KB of 24 KB unattributed, which read as "gaps". A
    # compiled SUB or FUNCTION becomes a label of the same name, which
    # is how interp.asm reaches s_putn, so the same span arithmetic
    # works on both once the names are found.
    for path in sorted(glob.glob(os.path.join(ROOT, "sw", "*.asm")) +
                       glob.glob(os.path.join(ROOT, "sw", "*.bas"))):
        base = os.path.basename(path)
        src = open(path, encoding="utf-8").read()
        names = re.findall(r"^([A-Za-z_][A-Za-z0-9_]*):", src, re.M)
        # The compiler prefixes a compiled SUB with `s_`, which is how
        # interp.asm reaches `s_putn` for a name written `SUB putn`.
        names += ["s_" + n for n in
                  re.findall(r"^\s*(?:SUB|FUNCTION)\s+([A-Za-z_]\w*)",
                             src, re.M | re.I)]
        for n in names:
            a = syms.get(n.lower())
            if a is not None and ORG() <= a <= top:
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
