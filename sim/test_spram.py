#!/usr/bin/env python3
"""The SPRAM controller against a byte array.

Runs sim/tb/cool8_spram_tb.v, which drives rtl/soc/cool8_spram.v as a bus
master and holds all 64 KB against its own reference copy: directed cases
for the handshake, the byte lanes, the block seam and every address bit,
then a long randomised stream, then a read-back sweep in address order.

The instruction-level counterpart — the CPU actually running out of it —
is `python sim/cosim.py spram`. This one localises a failure; that one
says whether it matters.

    python sim/test_spram.py
    python sim/test_spram.py --seeds 20 --n 100000

Set OSS_CAD_SUITE to the toolchain root if iverilog is not on PATH.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")

sys.path.insert(0, HERE)

import cosim                                  # noqa: E402

TB = os.path.join(HERE, "tb", "cool8_spram_tb.v")
RTL = [os.path.join(ROOT, "rtl", "soc", "cool8_spram.v")]


def build():
    return cosim._build("cool8_spram_tb", TB, RTL + [cosim.ice40_cells()],
                        gen="2012")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--n", type=int, default=30000,
                    help="randomised accesses per seed")
    ap.add_argument("--vcd")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    vvp = build()
    bad = 0
    for seed in range(1, args.seeds + 1):
        cmd = [cosim._tool("vvp"), vvp, f"+n={args.n}", f"+seed={seed}"]
        if args.vcd and seed == 1:
            cmd.append(f"+vcd={args.vcd}")
        if args.verbose:
            cmd.append("+verbose")
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok = "\nPASS" in r.stdout
        summary = swept = ""
        for line in r.stdout.splitlines():
            if "checks," in line:
                summary = line
            if "swept" in line:
                swept = line.strip()
        print(f"  seed {seed:<3} {summary:<26} {swept:<28} "
              f"{'ok' if ok else 'FAIL'}")
        if not ok:
            for line in r.stdout.splitlines():
                if line.startswith("FAIL"):
                    print("    " + line)
        bad += not ok

    print("\n" + ("PASS" if bad == 0 else f"FAIL — {bad} of {args.seeds}"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
