#!/usr/bin/env python3
"""The sound engine, on a scope and on a meter.

Runs sim/tb/cool8_snd_tb.v against rtl/soc/cool8_snd.v. The pin carries
no samples — it carries a 1-bit sigma-delta stream whose *duty cycle* is
the analogue value — so everything here is measured the way the RC filter
on the pin measures it.

  the DC level    silence sits at half scale, a square averages to half
                  scale, one voice held low sits at 47 %, held high at
                  52 %, and eight of them held low at 26 %
  the modulator   every 256-clock window emits exactly as many carries as
                  the level it was fed, so the DAC loses nothing
  the stream      4096 samples of a five-note chord plus noise, written
                  to build/snd.hex for sim/test_vm.py to gate the
                  emulator's sound model against

    python sim/test_snd.py
    python sim/test_snd.py --vcd snd.vcd -v

Set OSS_CAD_SUITE to the toolchain root if iverilog is not on PATH.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")

sys.path.insert(0, HERE)

import toolchain as T                                    # noqa: E402

TB = os.path.join(HERE, "tb", "cool8_snd_tb.v")
RTL = [os.path.join(ROOT, "rtl", "soc", "cool8_snd.v")]

STREAM = "snd.hex"


def build():
    return T.build("cool8_snd_tb", TB, RTL, gen="2012")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vcd")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--no-stream", action="store_true",
                    help="skip the sample dump the emulator gate needs")
    args = ap.parse_args()

    vvp = build()
    cmd = [T.tool("vvp"), vvp]
    if args.vcd:
        cmd.append(f"+vcd={args.vcd}")
    if not args.no_stream:
        cmd.append(f"+dump={STREAM}")

    r = subprocess.run(cmd, capture_output=True, text=True, cwd=BUILD)
    ok = "\nPASS" in r.stdout

    summary = ""
    for line in r.stdout.splitlines():
        if "checks," in line:
            summary = line.strip()
    print(f"  eight voices on one pin       {summary:<28} "
          f"{'ok' if ok else 'FAIL'}")
    if args.verbose:
        for line in r.stdout.splitlines():
            if line.startswith("  "):
                print("  " + line)
    if not ok:
        for line in r.stdout.splitlines():
            if line.startswith("FAIL"):
                print("    " + line)
        if args.verbose:
            print(r.stdout[-4000:])

    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
