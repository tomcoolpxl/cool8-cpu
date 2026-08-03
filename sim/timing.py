#!/usr/bin/env python3
"""Measure what every encoding actually costs, in clocks.

docs/02-isa.md section 8 says its cycle counts are targets rather than
measurements and will be replaced once the RTL exists. This is that
replacement: it runs the directed probe program, which executes every
encoding exactly once at a known address, and reads the cycle delta
across each instruction under test out of the testbench's cycle log.

    python sim/timing.py            # report, and diff against the table
    python sim/timing.py --emit     # list every encoding's measured cost

Both branch outcomes are covered because the probe program contains
`BRA` and `BNV` — always taken and never taken — as ordinary encodings,
and every conditional branch measures at one or the other depending on
the flags its own probe happened to set.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

import opcodes                                  # noqa: E402
import progen                                   # noqa: E402
import cosim                                    # noqa: E402

BUILD = cosim.BUILD


def measure():
    """Returns {(op, op2): clocks} for every encoding."""
    mem, _ = progen.directed()
    hexf = os.path.join(BUILD, "timing.hex")
    progen.write_hex(mem, hexf)
    cycf = os.path.join(BUILD, "timing.cyc")
    vvp = cosim.build_sim()
    cosim.run_sim(vvp, [f"+hex={hexf}", f"+cyc={cycf}", "+ws=0",
                        "+maxcycles=4000000"])

    # Each line is the PC and the clock at which one instruction retired.
    log = []
    for line in open(cycf):
        pc, cyc = line.split()
        log.append((int(pc, 16), int(cyc)))

    where = progen.PROBE_ADDR
    starts = {}
    for k in range(len(log) - 1):
        starts.setdefault(log[k][0], []).append(log[k + 1][1] - log[k][1])

    out = {}
    for key, addr in where.items():
        if addr in starts:
            out[key] = starts[addr][0]
    return out


CLASS = [
    ("NOP, CLC, SEC, EI, DI",     [(0x20, None), (0x26, None), (0x24, None)]),
    ("ALU Rd,Rs",                 [(0x91, None), (0xB5, None)]),
    ("ALU Rd,#imm8",              [(0x04, None), (0x1C, None)]),
    ("INCW / DECW X|Y",           [(0x38, None), (0x3A, None)]),
    ("LD / ST Rd,[X|Y]",          [(0x40, None), (0x48, None)]),
    ("PUSH / POP Rd",             [(0x30, None), (0x34, None)]),
    ("LD / ST Rd,[X+d8]",         [(0x50, None), (0x58, None)]),
    ("LD / ST Rd,[SP+u8]",        [(0x60, None), (0x68, None)]),
    ("LD / ST Rd,[abs16]",        [(0x61, None), (0x69, None)]),
    ("PUSHW / POPW",              [(0x3C, None), (0x3E, None)]),
    ("Bcc taken",                 [(0x70, None)]),
    ("Bcc not taken",             [(0x71, None)]),
    ("JMP abs16",                 [(0x28, None)]),
    ("JMP [X|Y]",                 [(0x2A, None)]),
    ("CALL abs16",                [(0x29, None)]),
    ("CALL [X|Y]",                [(0x2C, None)]),
    ("RET",                       [(0x22, None)]),
    ("RETI",                      [(0x23, None)]),
    ("BRK / reserved page-2 trap", [(0x2E, None), (0x2F, 0x2E)]),
    ("XOR Rd,Rs (page 2)",        [(0x2F, 0x00)]),
    ("unary Rd (page 2)",         [(0x2F, 0x14), (0x2F, 0x20)]),
    ("bit ops Rd,#mask (page 2)", [(0x2F, 0x30), (0x2F, 0x38)]),
    ("MOV Rd,<pp> / MOV <pp>,Rs", [(0x2F, 0x40), (0x2F, 0x50)]),
    ("LDW X,#imm16",              [(0x2F, 0x60)]),
    ("LDW X,[abs16] / STW",       [(0x2F, 0x62), (0x2F, 0x64)]),
    ("MOVW",                      [(0x2F, 0x66)]),
    ("ADDW SP,#d8 / LEA",         [(0x2F, 0x6C), (0x2F, 0x6D)]),
    ("ADDW X|Y,#imm16",           [(0x2F, 0x2C)]),
    ("ADDW / SUBW X|Y,Rd",        [(0x2F, 0x70), (0x2F, 0x78)]),
    ("LD / ST [X|Y + Rs]",        [(0x2F, 0x80), (0x2F, 0xA0)]),
    ("auto-increment / decrement", [(0x2F, 0xC0), (0x2F, 0xD0)]),
    ("PUSH F / POP F / CLV",      [(0x2F, 0xE0), (0x2F, 0xE1), (0x2F, 0xE2)]),
    ("MUL Rd,Rs",                 [(0x2F, 0xF0)]),
]


def name(key):
    if key[0] == 0x2F:
        e = opcodes.page2.get(key[1])
        return e[0] if e else f"reserved ${key[1]:02X}"
    return opcodes.primary[key[0]][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true")
    args = ap.parse_args()

    got = measure()
    missing = [k for k in got if got[k] <= 0]
    print(f"measured {len(got)} encodings"
          + (f", {len(missing)} implausible" if missing else ""))
    print()
    print(f"  {'class':<30} {'measured':>8} {'section 8':>10}")
    for label, keys in CLASS:
        vals = sorted({got[k] for k in keys if k in got})
        want = opcodes.cycles(keys[0][0], keys[0][1])
        if isinstance(want, tuple):
            want = want[1] if "taken" in label and "not" not in label \
                else want[0]
        m = "/".join(str(v) for v in vals) if vals else "?"
        flag = "" if vals and len(vals) == 1 and vals[0] == want else "  <-"
        print(f"  {label:<30} {m:>8} {want:>10}{flag}")

    if args.emit:
        print("\n# measured, clocks, one wait-state-free memory access "
              "per clock")
        for k in sorted(got, key=lambda k: (k[0], k[1] if k[1] else -1)):
            print(f"#   {name(k):<24} {got[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
