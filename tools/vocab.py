#!/usr/bin/env python3
"""The BASIC vocabulary, taken from the tables that implement it.

    python tools/vocab.py            check the sources agree
    python tools/vocab.py --emit     rewrite docs/13a-vocabulary.md
    python tools/vocab.py --list     print what it found

**The names are read, the meanings are declared, and the return types
are checked against the code.** That split is the whole design, and it
exists because this project has repeatedly written documentation from
how the interpreter is *organised* rather than from what it does --
`?TYPE` errors that were never raised, an `INT` described as a shift
eight years after it stopped being one, a `toktab` header insisting a
37th keyword would collide when there are seventy.

So:

  * A **name** can never drift, because it is taken from `TOKTAB` and
    `btab` -- the same bytes the machine matches against.
  * A **signature** cannot be inferred and is not guessed at. There is
    no argument-type declaration anywhere in the interpreter, and the
    honest reason is that most handlers do not check: they read R0:R1
    and act on whatever is there. So each table entry carries a `;:`
    line, and **an entry without one fails the check.** That is the
    point -- a new keyword cannot be added silently.
  * A **return type** is declared *and* verified: the handler's tail
    says which of `retnum`, `fretf`/`frtn` or `sappend` it leaves
    through, and a `-> float` that returns through `retnum` is a lie
    the gate catches.

What it deliberately does not do is describe behaviour. `2^3^2` is
63.96, a backwards `FOR` runs its body once, `VAL("3.5")` is 3 -- none
of that is in the source in any form, and only `sim/test_run.py` knows
it. This emits the table; the prose in docs/13-basic.md stays written
by hand, and the check keeps the two talking about the same words.

## The `;:` line

Anywhere in an entry's own line, or on a comment line directly after
it and before the next entry:

    .word h_poke            ; $98 POKE
                            ;: POKE addr:int, value:int !intonly

    .byte 3,"S","I","N"
    .word i_sin             ;: SIN(x:float) -> float   radians

`-> type` is the return, checked. `!flag` is a note; `!intonly` marks
an entry that reads R0:R1 without testing STYPE, so a float reaching
it is silently wrong rather than an error -- the list of those is
worth having generated rather than remembered.
"""

import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOKTAB = os.path.join(ROOT, "sw", "toktab.asm")
INTERP = os.path.join(ROOT, "sw", "interp.asm")
# `sttab` binds a token to a handler, and the handlers are spread over
# every module -- PRINT is the interpreter's, LIST is prog.asm's, SAVE is
# fscmd.asm's. So the table lives in sw/main.asm, the one file whose job
# is to depend on all of them ([D68]); it was in interp.asm while
# interp.asm named every handler itself.
STTAB = os.path.join(ROOT, "sw", "main.asm")
FPBAS = os.path.join(ROOT, "sw", "fpbas.asm")
DOC = os.path.join(ROOT, "docs", "13a-vocabulary.md")
TOKASM = os.path.join(ROOT, "sw", "tokens.asm")

# `?` is not a keyword: it is a one-character entry holding $A4 open for
# the numeric-literal marker, so the generated equate is called what the
# byte actually means rather than what the placeholder spells.
RENAME = {"?": "NUM", "!": "FLT"}

TOKFLG = os.path.join(ROOT, "sw", "tokflag.asm")

# ---------------------------------------------------------------------
# What each keyword does to the tokeniser and to RENUMBER.
#
# BBC BASIC's TOKENS entries carry eight flag bits; COOL8 wants two, and
# they are declared here rather than read out of anything because they
# are a *decision* per keyword -- the same standing MODULES has in
# sim/build_basic.py. A keyword with no entry gets zero.
#
# F_VERB  the rest of the line is copied verbatim. REM only. It deletes
#         the special case `tokenise` used to carry inline.
# F_LINE  line numbers follow, possibly comma-separated. Nothing in the
#         tokeniser reads this -- a number already tokenises to T_LIT
#         and two bytes, which is BBC's arrangement -- but RENUMBER
#         does, and without it RENUMBER cannot find a reference to
#         rewrite. It has been silently corrupting every GOTO in a
#         renumbered program ([D68]).
# ---------------------------------------------------------------------
F_VERB, F_LINE = 0x01, 0x02

FLAGS = {
    "REM": F_VERB,
    "GOTO": F_LINE,             # GOTO n, and ON x GOTO n,n,n
    "THEN": F_LINE,             # IF c THEN n
    "LIST": F_LINE,             # LIST a,b
    "DELETE": F_LINE,           # DELETE a,b
}

FIRST = 0x80                    # TOKTAB's first entry is this token

# How a handler says what it returns. The tail it leaves through is the
# type; `sappend` sets STYPE itself, which is why it counts as one.
TAILS = [
    ("float", ("fretf", "frtn", "fptl")),
    ("string", ("sappend",)),
    ("int", ("retnum",)),
]

SIG = re.compile(r";:\s*(.+?)\s*$")
RET = re.compile(r"->\s*([A-Za-z]+)")
FLAG = re.compile(r"!([A-Za-z]+)")


def _lines(path):
    return io.open(path, encoding="utf-8").read().split("\n")


def keywords():
    """(token, name) for every TOKTAB entry, in table order."""
    out, on = [], False
    for l in _lines(TOKTAB):
        if l.startswith("TOKTAB:"):
            on = True
            continue
        if not on:
            continue
        m = re.match(r'\s*\.byte\s+(\d+)\s*,?\s*(.*)$', l)
        if not m:
            continue
        n = int(m.group(1))
        if n == 0:                              # the terminator
            break
        chars = re.findall(r'"(.)"', m.group(2))
        if len(chars) != n:
            raise SystemExit(
                "toktab: entry says %d characters, has %d: %s" %
                (n, len(chars), l.strip()))
        out.append((FIRST + len(out), "".join(chars)))
    return out


def _table(path, start, stop_blank=True):
    """The lines of one table, from its label to a blank line or .byte 0."""
    src, out, on = _lines(path), [], False
    for l in src:
        if re.match(r"^%s:" % re.escape(start), l):
            on = True
            continue
        if not on:
            continue
        if stop_blank and not l.strip():
            break
        if re.match(r"\s*\.byte\s+0\s*$", l):
            break
        out.append(l)
    return out


def _entries(lines, kind):
    """Split a table's lines into entries, each carrying its `;:` text.

    An entry owns its own line and every comment line after it, up to
    the next entry -- so a signature may sit inline or underneath.
    """
    out, cur = [], None
    for l in lines:
        m = re.match(r"\s*\.word\s+([A-Za-z_][A-Za-z0-9_]*)", l)
        if kind == "btab":
            b = re.match(r'\s*\.byte\s+\d+\s*,\s*(".*)$', l)
            if b:
                cur = {"name": "".join(re.findall(r'"(.)"', b.group(1))),
                       "handler": None, "sig": None}
                out.append(cur)
                continue
        if m:
            if kind == "sttab":
                cur = {"name": None, "handler": m.group(1), "sig": None}
                out.append(cur)
            elif cur is not None:
                cur["handler"] = m.group(1)
        if cur is not None:
            s = SIG.search(l)
            if s:
                cur["sig"] = s.group(1) if cur["sig"] is None else cur["sig"]
    return out


def _handler_return(name):
    """Which tail the handler leaves through, or None if it is not clear."""
    for path in (INTERP, FPBAS):
        src = _lines(path)
        for i, l in enumerate(src):
            if not re.match(r"^%s:" % re.escape(name), l):
                continue
            body = []
            for l2 in src[i:]:
                if body and re.match(r"^[A-Za-z_][A-Za-z0-9_]*:", l2):
                    break
                body.append(l2.split(";")[0])
            blob = "\n".join(body)
            for kind, marks in TAILS:
                if any(re.search(r"\b%s\b" % m, blob) for m in marks):
                    return kind
            return None
    return None


def tokens_asm():
    """`sw/tokens.asm` -- `K_<NAME> = $xx` for every keyword.

    **The token numbering was hand-copied into three places** and
    [D65] called it frozen on the strength of a compatibility promise
    this project has never made: ~25 `K_*` equates in `sw/interp.asm`, a
    `CONST T_LIT` in `sw/basic.bas`, and a private 37-word list in
    `sim/test_interp.py` -- in a table of seventy ([D68]).

    Generating them is the same arrangement `tools/ioregs.py` has for
    the I/O page, and it has the same effect: the order stops being
    something anyone has to remember, and `TOKTAB` can be reordered or
    given a flags byte by rebuilding.

    **It found four dead equates on the first run**, which is what a
    generated inventory is for: `K_FUNC`, `K_RET`, `K_GOTOT` and
    `K_CONST` had definitions and no users -- and `K_CONST` was `$84`,
    which has been `RUN` since `CONST` was removed, so anything that had
    used it would have matched the wrong keyword.
    """
    ks = keywords()
    o = []
    o.append("; ------------------------------------------------------"
             "---------------")
    o.append("; tokens.asm -- the keyword token values, generated by"
             " tools/vocab.py.")
    o.append(";")
    o.append("; **Do not edit.** The values are TOKTAB's own order: the"
             " first entry")
    o.append("; is $%02X and each one after it is the next byte."
             " `poe check` fails if" % FIRST)
    o.append("; this file is stale, so the table can be reordered by"
             " rebuilding.")
    o.append("; ------------------------------------------------------"
             "---------------")
    o.append("")
    for tok, name in ks:
        n = RENAME.get(name, name)
        n = re.sub(r"[^A-Za-z0-9_]", "_", n)
        o.append("K_%-8s = $%02X" % (n, tok))
    o.append("")
    o.append("NTOK    = %d                    ; keywords, $%02X-$%02X"
             % (len(ks), FIRST, FIRST + len(ks) - 1))
    o.append("T_LIT   = K_NUM                 ; the stored-number marker,"
             " as tokenise writes it")
    return "\n".join(o)


def tokflag_asm():
    """`sw/tokflag.asm` -- one flags byte per keyword, in TOKTAB order.

    A table parallel to `TOKTAB` rather than a field inside it, for two
    reasons. `sw/basic.bas`'s `lookup` and `puttok` still walk `TOKTAB`
    in its `length, chars...` shape and must keep working until
    `main.asm` takes the entry point; and the flags are wanted by the
    tokeniser and by RENUMBER, not by the detokeniser, so putting them
    in the walked table would make every `LIST` step over a byte it
    never reads.
    """
    ks = keywords()
    o = []
    o.append("; ------------------------------------------------------"
             "---------------")
    o.append("; tokflag.asm -- what each keyword does to the tokeniser"
             " and to")
    o.append("; RENUMBER, generated by tools/vocab.py. One byte per"
             " keyword, in")
    o.append("; TOKTAB order, so token $%02X+n is TOKFLG+n." % FIRST)
    o.append(";")
    o.append("; **Do not edit.** The flags are declared in vocab.py"
             " because they are a")
    o.append("; decision per keyword; this file is how the machine sees"
             " them.")
    o.append("; ------------------------------------------------------"
             "---------------")
    o.append("")
    o.append("F_VERB  = $%02X                   ; rest of the line is"
             " verbatim: REM" % F_VERB)
    o.append("F_LINE  = $%02X                   ; line numbers follow:"
             " GOTO, THEN, LIST" % F_LINE)
    o.append("")
    o.append("TOKFLG:")
    for tok, name in ks:
        f = FLAGS.get(name, 0)
        tag = " ".join(n for n, b in (("F_VERB", F_VERB), ("F_LINE", F_LINE))
                       if f & b) or "0"
        o.append("        .byte %-16s ; $%02X %s" % (tag, tok, name))
    return "\n".join(o)


def vocabulary():
    kw = keywords()
    st = _entries(_table(STTAB, "sttab"), "sttab")
    if len(st) != len(kw):
        raise SystemExit(
            "sttab has %d entries and TOKTAB %d -- they are one table "
            "in two files and must be the same length" % (len(st), len(kw)))
    stmts = []
    for (tok, name), e in zip(kw, st):
        e["name"], e["token"] = name, tok
        stmts.append(e)
    fns = _entries(_table(INTERP, "btab", stop_blank=False), "btab")
    return stmts, fns


def check():
    bad = []
    stmts, fns = vocabulary()

    for e in stmts:
        if e["handler"] == "bad":               # a clause word: TO, THEN
            continue
        if not e["sig"]:
            bad.append("$%02X %-9s has no ;: signature (%s)" %
                       (e["token"], e["name"], e["handler"]))
    for e in fns:
        if not e["sig"]:
            bad.append("%-9s has no ;: signature (%s)" %
                       (e["name"], e["handler"]))

    # A declared return type has to match the tail the handler uses.
    for e in stmts + fns:
        if not e["sig"]:
            continue
        m = RET.search(e["sig"])
        if not m:
            continue
        want = m.group(1)
        if want not in ("int", "float", "string"):
            continue                            # `same`: ABS returns
                                                # whichever type it got,
                                                # so no tail is wrong
        got = _handler_return(e["handler"])
        if got and got != want:
            bad.append("%-9s declares -> %s but returns through the %s "
                       "tail" % (e["name"], want, got))

    # Only worth comparing the emitted doc once every entry has a
    # signature -- otherwise the diff is noise on top of the real fault.
    if bad:
        pass
    elif not os.path.exists(DOC):
        bad.append("docs/13a-vocabulary.md is missing: "
                   "run python tools/vocab.py --emit")
    elif io.open(DOC, encoding="utf-8").read() != markdown():
        bad.append("docs/13a-vocabulary.md is stale: "
                   "run python tools/vocab.py --emit")

    for path, want in ((TOKASM, tokens_asm()), (TOKFLG, tokflag_asm())):
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        if not os.path.exists(path):
            bad.append("%s is missing: run python tools/vocab.py --emit" % rel)
        elif io.open(path, encoding="utf-8").read() != want + "\n":
            bad.append("%s is stale: run python tools/vocab.py --emit" % rel)
    if False:
        bad.append("sw/tokens.asm is missing: "
                   "run python tools/vocab.py --emit")
    elif io.open(TOKASM, encoding="utf-8").read() != tokens_asm() + "\n":
        bad.append("sw/tokens.asm is stale: "
                   "run python tools/vocab.py --emit")

    for b in bad:
        print("  " + b)
    n = len(stmts) + len(fns)
    print("%s -- %d table entries, %d problems" %
          ("FAIL" if bad else "ok", n, len(bad)))
    return 1 if bad else 0


def _row(sig):
    """Split a signature into (call, note) for the table."""
    sig = sig or "?"                            # check() reports the
                                                # missing one; do not
                                                # crash rendering it
    note = " ".join("`!%s`" % f for f in FLAG.findall(sig))
    call = FLAG.sub("", sig).strip()
    rest = ""
    if "  " in call:                            # two spaces begin a remark
        call, rest = call.split("  ", 1)
    tail = " ".join(x for x in (rest.strip(), note) if x)
    # `|` is a cell separator: `DO [WHILE c | UNTIL c]` and `int|float`
    # both have to survive being put in a table.
    esc = lambda s: s.replace("|", "\\|")
    return esc(call.strip()), esc(tail)


def markdown():
    stmts, fns = vocabulary()
    o = []
    o.append("# 13a. The vocabulary")
    o.append("")
    o.append("**Generated by `tools/vocab.py` from the tables that "
             "implement the language — do not edit.** `poe check` fails "
             "if this file and the sources disagree, and if any entry "
             "has lost its signature.")
    o.append("")
    o.append("Names come from `TOKTAB` and `btab`, the bytes the "
             "matcher compares against. Return types are declared next "
             "to each entry and verified against the tail its handler "
             "leaves through. **Argument types are declarations, not "
             "proofs** — most handlers read `R0:R1` without testing "
             "`STYPE`, which is what `!intonly` marks: a float reaching "
             "one is silently wrong rather than an error. Behaviour at "
             "the edges is in [13-basic.md](13-basic.md), measured "
             "rather than derived.")
    o.append("")

    o.append("## Statements")
    o.append("")
    o.append("| token | | |")
    o.append("|---|---|---|")
    for e in stmts:
        if e["handler"] == "bad":
            continue
        call, note = _row(e["sig"])
        o.append("| `$%02X` | `%s` | %s |" % (e["token"], call, note))
    o.append("")

    dead = [e for e in stmts if e["handler"] == "bad"]
    o.append("## Tokenised, but not statements")
    o.append("")
    o.append("These hold a token but `sttab` sends them to `bad`, so "
             "meeting one where a statement was expected is `?SYNTAX`. "
             "Three reasons, all marked below: a **clause** the "
             "tokeniser matches inside something else (`TO` in a `FOR`, "
             "`THEN` in an `IF`); a **function** reached from `prim` "
             "rather than dispatched; or a command that was "
             "**removed**, whose token stays because the order of "
             "`TOKTAB` fixes every byte after it and programs on disk "
             "hold the old numbering.")
    o.append("")
    o.append("| token | | |")
    o.append("|---|---|---|")
    for e in dead:
        if e["sig"]:
            call, note = _row(e["sig"])
            o.append("| `$%02X` | `%s` | %s |" % (e["token"], call, note))
        else:
            o.append("| `$%02X` | `%s` | |" % (e["token"], e["name"]))
    o.append("")

    o.append("## Functions")
    o.append("")
    o.append("Matched by name, not tokenised — they have no token byte.")
    o.append("")
    o.append("| | |")
    o.append("|---|---|")
    for e in fns:
        call, note = _row(e["sig"])
        o.append("| `%s` | %s |" % (call, note))
    o.append("")

    unsafe = [e for e in stmts + fns
              if e["sig"] and "intonly" in FLAG.findall(e["sig"])]
    o.append("## The `!intonly` list")
    o.append("")
    o.append("%d of them. Each reads `R0:R1` and never tests `STYPE`, "
             "so handing one a float does not raise an error — it acts "
             "on whatever the integer registers last held. This list is "
             "generated so it cannot quietly grow." % len(unsafe))
    o.append("")
    o.append(", ".join("`%s`" % e["name"] for e in unsafe) + ".")
    o.append("")
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--emit", action="store_true",
                    help="rewrite docs/13a-vocabulary.md")
    ap.add_argument("--check", action="store_true",
                    help="verify the sources and the emitted doc agree")
    ap.add_argument("--list", action="store_true",
                    help="print the parsed tables")
    a = ap.parse_args()

    if a.list:
        stmts, fns = vocabulary()
        for e in stmts:
            print("$%02X %-10s %-10s %s" %
                  (e["token"], e["name"], e["handler"], e["sig"] or "-"))
        for e in fns:
            print("    %-10s %-10s %s" %
                  (e["name"], e["handler"], e["sig"] or "-"))
        return 0
    if a.emit:
        io.open(DOC, "w", encoding="utf-8", newline="\n").write(markdown())
        io.open(TOKASM, "w", encoding="utf-8", newline="\n").write(
            tokens_asm() + "\n")
        io.open(TOKFLG, "w", encoding="utf-8", newline="\n").write(
            tokflag_asm() + "\n")
        print("wrote %s, %s and %s" % (os.path.relpath(DOC, ROOT),
                                       os.path.relpath(TOKASM, ROOT),
                                       os.path.relpath(TOKFLG, ROOT)))
        return 0
    return check()


if __name__ == "__main__":
    sys.exit(main())
