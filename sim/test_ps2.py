#!/usr/bin/env python3
"""The keyboard port, against a keyboard.

Runs sim/tb/cool8_ps2_tb.v, which puts rtl/soc/cool8_ps2.v on an
open-drain wire with a device model on the other end. The model owns the
clock and implements the protocol from the specification rather than from
the block, in both directions — and the two directions sample on
opposite clock levels, which is the single most common way a PS/2
transmit path is wrong.

What the phases answer:

  decode        $FE40-$FE43, and not the addresses either side
  one scancode  a byte arrives and reads back
  a break       $1C $F0 $1C in order, because a scancode stream is only
                meaningful in sequence
  parity        a bad frame is dropped rather than queued, and flagged
  watchdog      a frame cut off after five bits must not leave every
                later frame six bits out of step forever
  glitch        a clock pulse shorter than the filter is not a bit
  the FIFO      sixteen fit, the seventeenth is the one lost, and the
                sixteen that fitted come back in order
  interrupts    enable, assert on arrival, drop when drained
  transmit      $ED to the device with odd parity and a stop bit, the
                device's acknowledge, and the $FA it answers with
  no keyboard   a transmit into an empty socket gives up instead of
                wedging tx_busy for ever

    python sim/test_ps2.py
    python sim/test_ps2.py --vcd ps2.vcd -v

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

TB = os.path.join(HERE, "tb", "cool8_ps2_tb.v")
RTL = [os.path.join(ROOT, "rtl", "soc", "cool8_ps2.v")]


def build():
    return T.build("cool8_ps2_tb", TB, RTL + [T.cells()],
                        gen="2012")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vcd")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    vvp = build()
    cmd = [T.tool("vvp"), vvp]
    if args.vcd:
        cmd.append(f"+vcd={args.vcd}")
    if args.verbose:
        cmd.append("+verbose")

    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = "\nPASS" in r.stdout

    summary = ""
    for line in r.stdout.splitlines():
        if "checks," in line:
            summary = line.strip()
    print(f"  the keyboard port on a wire   {summary:<28} "
          f"{'ok' if ok else 'FAIL'}")
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
