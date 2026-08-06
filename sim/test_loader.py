#!/usr/bin/env python3
"""The SoC serial path: cool8_uart and cool8_loader, simulated.

Runs sim/tb/cool8_loader_tb.v, which bit-bangs real 8N1 frames into the
UART, arbitrates the memory bus with a real cool8_core, and checks what
ends up in memory and what comes back down the wire.

The matrix is the two things that can shift the handshakes underneath the
loader without changing a line of it:

  - the baud divider, because the sniffer's state machine and the memory
    handshake run at the system clock while bytes arrive at the line
    rate. div=103 is the real 115200 at 12 MHz (D26); the smaller ones
    squeeze the gap between bytes and would expose anything that assumes
    the memory is idle when the next byte lands.
  - memory wait states, because the SPRAM at M4 item 2 has one.

    python sim/test_loader.py
    python sim/test_loader.py --div 103 --ws 1 --vcd waves.vcd

Set OSS_CAD_SUITE to the toolchain root if iverilog is not on PATH.
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")

sys.path.insert(0, HERE)

TB = os.path.join(HERE, "tb", "cool8_loader_tb.v")
RTL = ([os.path.join(ROOT, "rtl", "soc", f)
        for f in ("cool8_uart.v", "cool8_loader.v")] +
       [os.path.join(ROOT, "rtl", "core", f)
        for f in ("cool8_alu.v", "cool8_agu.v", "cool8_core.v")])

# div, wait states. 15 and 31 are not real baud rates; they are there to
# run the same frames with the bytes arriving four and two times closer
# together than the hardware will ever deliver them.
MATRIX = [(15, 0), (15, 3), (31, 1), (103, 0), (103, 1), (103, 3)]


# One toolchain locator, in cosim. This file had its own copy, and when
# cosim's learned to put the suite's bin directory on PATH so `vvp` can
# find libvvp-1.dll, this copy did not — six phases failed with no output
# and looked like a broken loader.
from cosim import _tool                                  # noqa: E402


def build():
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, "cool8_loader_tb.vvp")
    newest = max(os.path.getmtime(f) for f in RTL + [TB])
    if os.path.exists(out) and os.path.getmtime(out) > newest:
        return out
    subprocess.run([_tool("iverilog"), "-g2005", "-Wall", "-Wno-timescale",
                    "-o", out, TB] + RTL, check=True)
    return out


def run(vvp, div, ws, vcd=None, verbose=False):
    args = [_tool("vvp"), vvp, f"+div={div}", f"+ws={ws}"]
    if vcd:
        args.append(f"+vcd={vcd}")
    if verbose:
        args.append("+verbose")
    r = subprocess.run(args, capture_output=True, text=True)
    ok = "\nPASS" in r.stdout
    return ok, r.stdout + r.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--div", type=int, help="one divider instead of the matrix")
    ap.add_argument("--ws", type=int, default=0)
    ap.add_argument("--vcd")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    vvp = build()
    cases = [(args.div, args.ws)] if args.div else MATRIX
    bad = 0
    for div, ws in cases:
        ok, out = run(vvp, div, ws, args.vcd, args.verbose)
        checks = ""
        for line in out.splitlines():
            if "checks," in line:
                checks = line
        print(f"  div={div:<4} ws={ws}   {checks:<26} "
              f"{'ok' if ok else 'FAIL'}")
        if not ok or args.verbose:
            for line in out.splitlines():
                if line.startswith("FAIL") or (args.verbose and
                                               line.startswith("  ok")):
                    print("    " + line)
        bad += not ok

    print("\n" + ("PASS" if bad == 0 else f"FAIL — {bad} of {len(cases)}"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
