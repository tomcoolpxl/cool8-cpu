#!/usr/bin/env python3
"""The video memory and its arbiter, against a word array.

Runs sim/tb/cool8_vram_tb.v, which drives all four requesters of
rtl/soc/cool8_vram.v and holds all 32K words against its own reference
with a per-nibble written mask: directed cases for the handshake, the
nibble write masks, the block seam and every address bit; then the
arbitration order walked down one requester at a time; then back-to-back
throughput; then a long concurrent stream with all four asking at once.

Three properties are worth naming, because each is load-bearing
somewhere else:

  * A grant every cycle with no turnaround bubble. This is what
    separates the block from cool8_spram, and docs/04-system.md
    section 5.10's bandwidth budget assumes it.
  * Per-nibble writes. A 4 bpp pixel is one nibble, which is why the
    pixel port needs no read-modify-write in the mode most drawing
    happens in.
  * The blitter is not starved by strict priority. The random stream
    asserts it gets more than half the cycles, which is the arithmetic
    D28 and section 5.10 rest on.

    python sim/test_vram.py
    python sim/test_vram.py --seeds 20 --n 100000

Set OSS_CAD_SUITE to the toolchain root if iverilog is not on PATH.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

sys.path.insert(0, HERE)

import cosim                                    # noqa: E402

TB = os.path.join(HERE, "tb", "cool8_vram_tb.v")
RTL = [os.path.join(ROOT, "rtl", "soc", "cool8_vram.v")]


def build():
    return cosim._build("cool8_vram_tb", TB, RTL + [cosim.ice40_cells()],
                        gen="2012")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--n", type=int, default=20000,
                    help="randomised concurrent cycles per seed")
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
        summary = grants = ""
        for line in r.stdout.splitlines():
            if "checks," in line:
                summary = line
            if "grants:" in line:
                grants = line.strip()
        print(f"  seed {seed:<3} {summary:<26} {grants:<44} "
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
