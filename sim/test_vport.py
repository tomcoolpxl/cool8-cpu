#!/usr/bin/env python3
"""The indirect VRAM port, against a real cool8_vram.

Runs sim/tb/cool8_vport_tb.v, which drives rtl/soc/cool8_vport.v the way
the I/O page will — a one-cycle launch pulse for a read, a write held
until it is taken, mem_ready gated by o_stall — with the real memory
underneath and a synthetic display fetch contending for it.

The contention is the point. Everything interesting about this block is
what happens when the prefetched byte is not back in time, and it is
always back in time unless something else is using the memory.

What the phases answer:

  decode           $FE26-$FE29, and the $FEC0-$FEFF alias, without
                   claiming a neighbour
  basics           runs of writes and reads, both byte lanes, an
                   odd-aligned run, and that reading a register is not a
                   data access
  steps            all eight step codes in both directions, the stride
                   code following VID_STRIDE, and a wrapping address
  the_alias        a 64-byte run through $FEC0 pulling 64 consecutive
                   VRAM bytes — which is what makes VRAM visible to the
                   loader and to tools/cool8screen.py at all
  stale_prefetch   the address moved while a fetch was out for it. The
                   window is a cycle or two wide, so the address write is
                   walked across it at six offsets, twice, once with the
                   memory busy
  under_contention the first read after a write burst, which by design
                   has nothing prefetched and must stall
  random_stream    mixed runs at random addresses and steps, with the
                   display load changing underneath

    python sim/test_vport.py
    python sim/test_vport.py --seeds 10 --n 20000

Set OSS_CAD_SUITE to the toolchain root if iverilog is not on PATH.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

sys.path.insert(0, HERE)

import toolchain as T                                    # noqa: E402

TB = os.path.join(HERE, "tb", "cool8_vport_tb.v")
RTL = [os.path.join(ROOT, "rtl", "soc", f)
       for f in ("cool8_vport.v", "cool8_vram.v")]


def build():
    return T.build("cool8_vport_tb", TB, RTL + [T.cells()],
                        gen="2012")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--n", type=int, default=4000,
                    help="randomised port operations per seed")
    ap.add_argument("--vcd")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    vvp = build()
    bad = 0
    for seed in range(1, args.seeds + 1):
        cmd = [T.tool("vvp"), vvp, f"+n={args.n}", f"+seed={seed}"]
        if args.vcd and seed == 1:
            cmd.append(f"+vcd={args.vcd}")
        if args.verbose:
            cmd.append("+verbose")
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok = "\nPASS" in r.stdout
        summary = stalled = ""
        for line in r.stdout.splitlines():
            if "checks," in line:
                summary = line
            if "stalled" in line:
                stalled = line.strip()
        print(f"  seed {seed:<3} {summary:<28} {stalled:<24} "
              f"{'ok' if ok else 'FAIL'}")
        if not ok:
            for line in r.stdout.splitlines()[:40]:
                if line.startswith("FAIL"):
                    print("    " + line)
        bad += not ok

    print("\n" + ("PASS" if bad == 0 else f"FAIL — {bad} of {args.seeds}"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
