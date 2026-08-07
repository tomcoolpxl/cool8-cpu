#!/usr/bin/env python3
"""S4 -- the self-hosted compiler, against the cross-compiler.

    python sim/test_comp.py
    python sim/test_comp.py arrays        # just the one case

`sw/comp.bas` compiles a stored program straight to bytes, on the
machine. `tools/cool8bas.py` compiles the same program on the PC. The
bytes have to match, and so do the addresses the variables land at:
correct instructions about the wrong memory is not a working compiler.

## Why a suite and not one program

Both were tried. A single 126-line program covering everything gave one
bit -- pass or fail -- and took minutes, because the compiler walks the
token stream three times per pass and its symbol lookup is a linear
scan, so cost grows faster than length. Split into cases it runs in a
fraction of the time and a failure names the feature that broke.

`sim/dbg.py` supplies the rest: the first structural fault rather than
its tenth symptom, disassembly from real instruction boundaries, the
line of the program under test that the compiler had reached, and a
decoded dump of the compiler's own variables.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8bas as bas                                   # noqa: E402
import dbg                                               # noqa: E402
from test_lex import keyword_bytes, store                # noqa: E402

ORG = 0x0200            # where the compiler itself runs
SRC = 0x8000            # the stored program it compiles
OUT = 0xA000            # and where it puts the result
FAILS = []

DRIVER = """
INCLUDE "chars.bas"
INCLUDE "lex.bas"
INCLUDE "emit.bas"
INCLUDE "comp.bas"

' The length of the program comes from memory, so one built compiler
' serves every case. Baking in a size would have the lexer run off the
' end of the shorter ones.
DIM plen AS CARD
plen = PEEK($7F11)
plen = plen << 8
plen = plen + PEEK($7F10)
progend = $8000 + plen
CALL compile($8000, $A000)
POKE $7F00, cp AND 255
POKE $7F01, cp >> 8
END
"""

# One program per part of the generator, so a failure names the part.
CASES = [

    ("scalars", """CONST LIMIT = 100 + 23
DIM w AS INT
DIM b AS BYTE
DIM u AS CARD
w = 1000
b = 7
u = $ABCD
w = w + LIMIT
b = b AND 15
w = w - b
u = u XOR $00FF
w = w << 1
w = w >> 8
b = b << 2
w = (w + 1) - LIMIT
w = 0 - w
END
"""),

    ("temporaries", """DIM w AS INT
DIM b AS BYTE
DIM u AS CARD
w = (w + 1) - (b + 2)
u = (u XOR $0F0F) AND (u + 1)
b = (b + 1) - (b AND 3)
w = w - ((b + 1) + (b + 2))
IF (w + 1) > (b + 2) THEN
  w = w + 1
END IF
END
"""),

    ("branches", """DIM w AS INT
DIM b AS BYTE
DIM u AS CARD
IF w > 10 THEN
  w = w - 1
END IF
IF b = 0 THEN
  b = 1
ELSE
  b = b - 1
END IF
IF w < 0 THEN
  w = 0
ELSEIF w > 999 THEN
  w = 999
ELSE
  w = w + 1
END IF
IF u >= $8000 THEN u = 0
END
"""),

    ("loops", """CONST LIMIT = 123
DIM w AS INT
DIM b AS BYTE
DIM u AS CARD
DIM i AS INT
DO WHILE w <> 0
  w = w - 1
  IF w = 5 THEN
    EXIT DO
  END IF
LOOP
DO
  b = b + 1
LOOP UNTIL b >= 200
FOR i = 1 TO 10
  w = w + i
NEXT i
FOR b = 0 TO LIMIT
  u = u + 1
NEXT
END
"""),

    ("hardware", """DIM w AS INT
DIM b AS BYTE
DIM u AS CARD
POKE $FE10, $80
b = PEEK($FE22)
w = PEEK($FE23) + 1
POKE w, b
POKE w + 1, b + 2
POKE $FE24, PEEK($FE24) AND 15
u = PEEK(u + 1)
w = w + PEEK($FE70)
END
"""),

    ("arrays", """DIM w AS INT
DIM b AS BYTE
DIM i AS INT
DIM tab(9) AS INT
DIM buf(255) AS BYTE
DIM big(200) AS INT
DIM scr(4095) AS BYTE AT $C000
tab(0) = 1
tab(3) = w
buf(7) = b
buf(i) = b + 1
tab(i) = w + 1
big(i) = w
big(0) = 0
scr(0) = 65
scr(i + 1) = b
w = tab(0) + tab(i)
b = buf(3) - buf(i)
w = big(i) + big(2)
b = scr(i) XOR scr(0)
END
"""),

    ("subs", """DIM w AS INT
DIM b AS BYTE
DIM i AS INT
DIM tab(9) AS INT
CALL setrow(3, 65)
w = total(9) + 1
CALL setrow(i + 1, b + 2)
w = total(i) - total(0)
b = clamp(w, 200)
END

SUB setrow(r AS INT, c AS BYTE)
  DIM k AS INT
  k = 0
  DO WHILE k < 10
    tab(k) = r + c
    k = k + 1
  LOOP
END SUB

FUNCTION total(n AS INT) AS INT
  DIM s AS INT
  DIM j AS INT
  s = 0
  j = 0
  DO WHILE j <= n
    s = s + tab(j)
    j = j + 1
  LOOP
  RETURN s
END FUNCTION

FUNCTION clamp(v AS INT, hi AS BYTE) AS BYTE
  IF v > hi THEN
    RETURN hi
  END IF
  IF v < 0 THEN
    RETURN 0
  END IF
  RETURN v
END FUNCTION
"""),
]


def check(ok, what, detail=""):
    print(f"  {what:<44} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print(detail)
    return ok


def reference(source, name):
    """cool8bas on the same program: the bytes, and where storage went."""
    asm = bas.compile_source(source, OUT)
    apath = os.path.join(BUILD, f"ref_{name}.asm")
    with open(apath, "w") as fh:
        fh.write(asm)
    out = os.path.join(BUILD, f"ref_{name}.bin")
    sym = os.path.join(BUILD, f"ref_{name}.sym")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), apath,
                        "-o", out, "--symbols", sym,
                        "-I", os.path.join(ROOT, "sw")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stdout + r.stderr)
    addrs = {}
    for line in open(sym):
        p = line.split()
        if len(p) == 2 and (p[1].startswith("v_") or p[1].startswith("a_")
                            or p[1].endswith("_lim")):
            addrs[p[1]] = int(p[0], 16)
    with open(out, "rb") as fh:
        return fh.read(), addrs


def run_case(name, source, img, kw):
    want, waddr = reference(source, name)
    stored = store(source.splitlines(), kw)
    r = dbg.Run(img, src=SRC, stored=stored, out=OUT)
    r.m.bus.mem[0x7F10] = len(stored) & 0xFF
    r.m.bus.mem[0x7F11] = len(stored) >> 8
    try:
        r.go()
    except dbg.Fault as f:
        return check(False, name, str(f) + "\n    " + r.state())

    cerr = img.sym.get("v_cerr")
    err = r.m.bus.mem[cerr] if cerr else 0
    if err:
        return check(False, name,
                     f"    the compiler refused it: error {err}\n"
                     f"    {r.state()}")

    end = r.word(0x7F00)
    got = bytes(r.m.bus.mem[OUT:end])
    codelen = (min(waddr.values()) - OUT) if waddr else len(want)
    d = dbg.diff(got, want, OUT, codelen, codelen)
    if d is None and len(got) != len(want):
        d = (f"    code matches; data is {len(got) - codelen} bytes "
             f"against {len(want) - codelen}")
    return check(d is None, f"{name} ({codelen} bytes of code)", d or "")


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    print("  S4 -- sw/comp.bas, against cool8bas.py")
    print()

    kw = keyword_bytes()
    img = dbg.Image(DRIVER, ORG, "comp_drv")
    print(f"  compiler: {len(img.code):,} bytes "
          f"({len(img.code)/1024:.1f} KB)")
    print()

    for name, source in CASES:
        if only and name != only:
            continue
        run_case(name, source, img, kw)

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
