#!/usr/bin/env python3
"""How much does one interpreted operation cost on COOL8?

    python sim/bench_dispatch.py

`sim/bench_lang.py` answered "compile or interpret" and got 6.7x for
native code. This asks the question underneath it: if we interpret,
*how* should the interpreter get from one operation to the next? On an
8-bit machine that choice is most of the speed.

Four mechanisms, each measured by running the same do-nothing operation
a hundred thousand times and dividing. Nothing is estimated.

  token table    a byte per operation, indexing a table of handler
                 addresses. What bench_lang's VM does, and what most
                 8-bit BASICs do.
  direct thread  two bytes per operation, holding the handler's address
                 itself. No table lookup at all.
  subroutine     three bytes per operation: `CALL handler`. The CPU's
                 own instruction fetch is the dispatch.
  native         the operation inline, no dispatch. The floor.

The interesting one on this instruction set is the third. There is no
`LDW X,[X]`, so loading a handler address out of a table costs several
instructions -- but `CALL abs16` is a single instruction that does
exactly that job in hardware.
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

# Small enough that the straight-line cases (three bytes an operation
# for subroutine threading, nine for native) still fit the address
# space. At 20000 the CALL sequence alone was 60 KB and ran off the end.
N = 3000                # operations per run
CODE = 0x0200
DATA = 0x6000


def build(name, text):
    path = os.path.join(BUILD, f"disp_{name}.asm")
    with open(path, "w") as fh:
        fh.write(text)
    out = os.path.join(BUILD, f"disp_{name}.bin")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), path,
                        "-o", out], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stdout + r.stderr)
    with open(out, "rb") as fh:
        return fh.read()


def run(code):
    m = vm.Machine()
    m.bus.mem[CODE:CODE + len(code)] = code
    m.cpu.pc = CODE
    m.cpu.sp = 0x7FF0
    m.romen = False
    if m.run(budget=60_000_000) != "halt":
        raise SystemExit("never halted")
    return m.cpu.cycles


# The operation being dispatched to is the same in every case: add one
# to a counter. What differs is only how control reaches it.

TOKEN = f"""
        .org ${CODE:04X}
        LDW  Y,#stream
loop:   LD   R0,[Y]
        INCW Y
        TST  R0
        BEQ  done
        SUB  R0,#1
        SHL  R0
        LDW  X,#tab
        LD   R1,[X+R0]
        ADD  R0,#1
        LD   R2,[X+R0]
        MOV  XL,R1
        MOV  XH,R2
        JMP  [X]
done:   HALT
h_op:   LD   R3,[count]
        ADD  R3,#1
        ST   [count],R3
        JMP  loop
tab:    .word h_op
count:  .byte 0
stream: .fill {N}, 1
        .byte 0
"""

DIRECT = f"""
        .org ${CODE:04X}
        LDW  Y,#stream
loop:   LD   R0,[Y]
        INCW Y
        LD   R1,[Y]
        INCW Y
        MOV  XL,R0
        MOV  XH,R1
        JMP  [X]
done:   HALT
h_op:   LD   R3,[count]
        ADD  R3,#1
        ST   [count],R3
        JMP  loop
count:  .byte 0
stream: .fill {2 * N + 2}, 0
"""

SUBR = f"""
        .org ${CODE:04X}
        JMP  start
h_op:   LD   R3,[count]
        ADD  R3,#1
        ST   [count],R3
        RET
count:  .byte 0
start:
"""

# Straight-line, like the threaded cases: a loop would add its own
# control cost and this is meant to be the floor.
NATIVE_HEAD = f"""
        .org ${CODE:04X}
        JMP  start
count:  .byte 0
start:
"""
NATIVE_OP = """        LD   R3,[count]
        ADD  R3,#1
        ST   [count],R3
"""


def token_stream():
    """The direct-threaded stream needs the handler's real address, so
    it is filled in after assembling once to find out where it is."""
    return None


def main():
    print("  How one interpreted operation reaches the next, on COOL8")
    print()
    results = []

    # ---- token table
    code = build("token", TOKEN)
    c = run(code)
    results.append(("token table", c, 1))

    # ---- direct threading: patch the stream with h_op's address
    src = DIRECT
    path = os.path.join(BUILD, "disp_direct.asm")
    with open(path, "w") as fh:
        fh.write(src)
    out = os.path.join(BUILD, "disp_direct.bin")
    sym = os.path.join(BUILD, "disp_direct.sym")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), path,
                        "-o", out, "--symbols", sym],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stdout + r.stderr)
    syms = {p[1]: int(p[0], 16) for p in
            (l.split() for l in open(sym)) if len(p) == 2}
    code = bytearray(open(out, "rb").read())
    at = syms["stream"] - CODE
    hop = syms["h_op"]
    for i in range(N):
        code[at + 2 * i] = hop & 0xFF
        code[at + 2 * i + 1] = hop >> 8
    # the terminator: an address that halts
    code[at + 2 * N] = syms["done"] & 0xFF
    code[at + 2 * N + 1] = syms["done"] >> 8
    results.append(("direct thread", run(bytes(code)), 2))

    # ---- subroutine threading: N calls, then a halt
    src = SUBR + "\n".join(["        CALL h_op"] * N) + "\n        HALT\n"
    results.append(("subroutine", run(build("subr", src)), 3))

    # ---- native
    src = NATIVE_HEAD + NATIVE_OP * N + "        HALT\n"
    results.append(("native inline", run(build("native", src)), 9))

    base = [c for n, c, _ in results if n == "native inline"][0]
    print(f"  {'mechanism':<16}{'clocks/op':>11}{'overhead':>10}"
          f"{'bytes/op':>10}{'vs native':>11}")
    for name, cycles, size in results:
        per = cycles / N
        print(f"  {name:<16}{per:>11.1f}{per - base/N:>10.1f}"
              f"{size:>10}{per/(base/N):>10.2f}x")
    print()
    print("  The operation itself is a three-instruction increment, so")
    print("  'overhead' is what the dispatch costs on top of the work.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
