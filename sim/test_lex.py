#!/usr/bin/env python3
"""S4a -- the compiler's front end, against the cross-compiler's.

    python sim/test_lex.py

`sw/lex.bas` hands the parser one token at a time out of the stored
program. `tools/cool8bas.py`'s `lex()` does the same job from text. If
they disagree about what a token is, the two compilers cannot agree
about anything downstream -- so this compares the whole stream, token
for token, kind and value.

## What is being compared, and what is not

The machine reads the *tokenised* form, so it never sees indentation and
never has to match a keyword against a table -- keywords arrived as
single bytes when the line was typed. The reference reads text. The two
therefore differ in what they do, which is the point: they have to agree
on the answer anyway.

Line numbers are not compared. The machine's lines are numbered by the
user and the reference's by position in the file; neither reaches the
code generator.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8vm as vm                                     # noqa: E402
import cool8bas as bas                                   # noqa: E402

ORG = 0x0200
PROG = 0x4000           # the stored program the driver lexes
OUT = 0x6000            # where the driver writes what it found
FAILS = []

T_EOF, T_NL, T_NUM, T_NAME, T_STR, T_OP = range(6)

# The program under test. Every construct the lexer has to get right:
# hex and decimal, names with digits and underscores, the two-character
# operators, a string, a comment, a REM, a blank line, and keywords
# butted against punctuation.
SOURCE = """K_1 = $1F
DIM buf_2(15) AS BYTE
x9 = 100
IF x9 <> $ff THEN
  x9 = x9 << 2
  buf_2(0) = x9 >> 1
END IF
' a comment on its own
REM another one
DO WHILE x9 >= 10

  x9 = x9 - 1
LOOP
PRINT "hi there"
CALL sub_a(x9, 3)
"""


def check(ok, what, detail=""):
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


def keyword_bytes():
    """The keyword -> token byte map, read out of sw/toktab.asm.

    Read rather than restated: the table is the machine's, and a copy
    here would only ever agree with itself. It used to be inline in
    sw/basic.bas and moved to its own file when sw/asm.asm needed it as
    well -- the assembler has to turn keyword bytes back into words,
    because the editor tokenises the inside of an ASM block.
    """
    src = open(os.path.join(ROOT, "sw", "toktab.asm"), encoding="utf-8")
    text = src.read()
    body = text.split("TOKTAB:", 1)[1]
    out, tok = {}, 0x80
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith(".byte"):
            if line.startswith(";") or not line:
                continue
            break
        parts = [p.strip() for p in line[5:].split(",")]
        if parts[0] == "0":
            break
        word = "".join(p.strip('"') for p in parts[1:])
        out[word.lower()] = tok
        tok += 1
    return out


def tokenise(line, kw):
    """One typed line to its stored bytes -- the machine's tokenise()."""
    out, i, q = bytearray(), 0, False
    while i < len(line):
        c = line[i]
        if c == '"':
            q = not q
            out.append(ord(c))
            i += 1
        elif q:
            out.append(ord(c))
            i += 1
        elif c == "'":
            out += line[i:].encode("latin-1")
            break
        elif c.isalpha() or c == "_":
            j = i
            while j < len(line) and (line[j].isalnum() or line[j] == "_"):
                j += 1
            word = line[i:j]
            if word.lower() == "rem":
                out += line[i:].encode("latin-1")
                break
            t = kw.get(word.lower())
            if t:
                out.append(t)
            else:
                out += word.encode("latin-1")
            i = j
        else:
            out.append(ord(c))
            i += 1
    return bytes(out)


def store(lines, kw):
    """The lines as the machine holds them: lineno, len, tokens."""
    out = bytearray()
    for n, line in enumerate(lines, 1):
        body = tokenise(line, kw)
        out += bytes((n * 10 & 255, (n * 10) >> 8, len(body))) + body
    return bytes(out)


def reference(src):
    """cool8bas's lexer, reduced to (kind, value) with lines dropped."""
    out = []
    for kind, text, _ in bas.lex(src):
        if kind == "eof":
            out.append(("eof", None))
        elif kind == "nl":
            out.append(("nl", None))
        elif kind == "num":
            out.append(("num", text))
        elif kind == "name":
            out.append(("name", text.lower()))
        elif kind == "str":
            out.append(("str", text))
        elif kind == "op":
            out.append(("op", text))
        else:
            out.append(("kw", kind))
    return out


DRIVER = """
INCLUDE "chars.bas"
INCLUDE "lex.bas"

DIM op AS CARD
DIM n AS BYTE

progend = $4000 + {size}
CALL lexstart($4000)
op = $6000
DO
  n = nexttok()
  POKE op, n
  op = op + 1
  IF n = T_NUM THEN
    POKE op, tnum AND 255
    POKE op + 1, tnum >> 8
    op = op + 2
  ELSE
    POKE op, tsl
    op = op + 1
    n = 0
    DO WHILE n < tsl
      POKE op, tsb(n)
      op = op + 1
      n = n + 1
    LOOP
  END IF
LOOP WHILE tk <> T_EOF
POKE $7F00, op AND 255
POKE $7F01, op >> 8
END
"""


def main():
    print("  S4a -- sw/lex.bas, against cool8bas.py's lex()")
    print()

    kw = keyword_bytes()
    bytok = {v: k for k, v in kw.items()}
    lines = SOURCE.splitlines()
    stored = store(lines, kw)

    asm = bas.compile_source(DRIVER.replace("{size}", str(len(stored))), ORG)
    apath = os.path.join(BUILD, "lex_drv.asm")
    with open(apath, "w") as fh:
        fh.write(asm)
    out = os.path.join(BUILD, "lex_drv.bin")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), apath,
                        "-o", out, "-I", os.path.join(ROOT, "sw")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("the driver would not compile")
    code = open(out, "rb").read()
    print(f"  driver + lexer: {len(code):,} bytes, "
          f"{len(stored):,} bytes of stored program")

    m = vm.Machine()
    m.bus.mem[ORG:ORG + len(code)] = code
    m.bus.mem[PROG:PROG + len(stored)] = stored
    m.cpu.pc = ORG
    m.cpu.sp = 0xFFF7
    m.romen = False
    # m.run, not a stepping loop: the machine advances the raster and
    # the interrupt flags and a bare loop does not (AGENTS.md).
    if m.run(budget=20_000_000) != "halt":
        raise SystemExit("the driver never halted")

    # Decode what the machine wrote.
    end = m.bus.mem[0x7F00] | (m.bus.mem[0x7F01] << 8)
    got, p = [], OUT
    while p < end:
        k = m.bus.mem[p]
        p += 1
        if k == T_NUM:
            got.append(("num", m.bus.mem[p] | (m.bus.mem[p + 1] << 8)))
            p += 2
        else:
            ln = m.bus.mem[p]
            p += 1
            text = bytes(m.bus.mem[p:p + ln]).decode("latin-1")
            p += ln
            if k == T_EOF:
                got.append(("eof", None))
            elif k == T_NL:
                got.append(("nl", None))
            elif k == T_NAME:
                got.append(("name", text.lower()))
            elif k == T_STR:
                got.append(("str", text))
            elif k == T_OP:
                got.append(("op", text))
            else:
                got.append(("kw", bytok.get(k, f"?{k:02X}")))

    want = reference(SOURCE)

    check(len(got) == len(want),
          f"the machine read {len(got)} tokens, the reference {len(want)}",
          f"{len(got)} against {len(want)}")

    n = min(len(got), len(want))
    bad = [i for i in range(n) if got[i] != want[i]]
    check(not bad and len(got) == len(want),
          "and every one of them is the same token",
          f"first differs at {bad[0]}: {got[bad[0]]} against "
          f"{want[bad[0]]}" if bad else
          f"got {got[n:]} extra" if len(got) > n else
          f"missing {want[n:]}")

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
