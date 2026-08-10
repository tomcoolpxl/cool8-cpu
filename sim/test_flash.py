#!/usr/bin/env python3
"""The SPI flash reader, against a flash.

Runs sim/tb/cool8_flash_tb.v, which puts rtl/soc/cool8_flash.v opposite a
behavioural W25Q that decodes the opcode off the wire and only knows one.
Anything other than $03 fails the run rather than quietly returning
zeros, so D16's promise — this hardware has no program or erase path —
is checked by a device that would refuse one, not asserted in a comment.

The master implements mode 0 from the host's side and the model
implements it from the device's, so they agree only if both are right.

What the phases answer:

  decode        $FE88-$FE8D, which of them is the data port, and neither
                neighbour
  registers     the 24-bit address reads back
  a short read  sixteen bytes streamed against the model's own memory,
                with chip select held low the whole way
  the address   FLS_ADDR follows the stream, so a monitor can show
                progress, and a write to it while open is ignored so it
                never disagrees with the part
  close/reopen  a second session issues a fresh command instead of
                carrying on
  the boundary  $00FFFF to $010000, the one place a 24-bit counter made
                of three 8-bit registers goes wrong
  stalling      reads really do stall, because a byte is sixteen system
                clocks and the CPU can ask for one in two — and a read
                with no stream open does not hang

    python sim/test_flash.py
    python sim/test_flash.py --vcd fls.vcd -v

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

TB = os.path.join(HERE, "tb", "cool8_flash_tb.v")
RTL = [os.path.join(ROOT, "rtl", "soc", "cool8_flash.v")]


def build():
    return T.build("cool8_flash_tb", TB, RTL + [T.cells()],
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
    print(f"  the flash reader on a wire    {summary:<42} "
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
