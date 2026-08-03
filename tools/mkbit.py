#!/usr/bin/env python3
"""Build the bitstream: yosys, nextpnr, icepack.

    python tools/mkbit.py

Writes build/cool8.bin, plus the boot ROM image it is built around and
the intermediate netlists, and reports what the device ended up holding
and what frequency it closed at.

Programming is separate and deliberate: copy build/cool8.bin onto the
iCELink drive, or `icesprog build/cool8.bin`. **Never `icesprog -e`** —
that is a whole-chip erase and it takes the bitstream with it.

The boot ROM is assembled here rather than checked in, for the same
reason sim/test_boot.py does it: a stale hex file is a boot ROM that
does not match its own source. yosys runs with build/ as its working
directory because cool8_rom.v reads that name at elaboration.

Set OSS_CAD_SUITE to the toolchain root if the tools are not on PATH.
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "build")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))

import cosim                                    # noqa: E402
import mkrom                                    # noqa: E402

SRC = [os.path.join(ROOT, "rtl", "core", f)
       for f in ("cool8_alu.v", "cool8_agu.v", "cool8_core.v")] + \
      [os.path.join(ROOT, "rtl", "soc", f)
       for f in ("cool8_rom.v", "cool8_spram.v", "cool8_mem.v",
                 "cool8_uart.v", "cool8_loader.v", "cool8_soc.v",
                 "cool8_top.v")]

PCF = os.path.join(ROOT, "board", "icesugar.pcf")


def step(name, argv, cwd=BUILD):
    print(f"  {name} ...", end="", flush=True)
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    if r.returncode != 0:
        print(" FAILED")
        print(out[-4000:])
        sys.exit(1)
    print(" ok")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", type=float, default=12.0,
                    help="the constraint to close against, in MHz")
    args = ap.parse_args()

    os.makedirs(BUILD, exist_ok=True)

    base, img, rom = mkrom.build(os.path.join(ROOT, "sw", "boot.asm"))
    with open(os.path.join(BUILD, "boot.hex"), "w") as fh:
        for b in rom:
            fh.write("%02x\n" % b)
    print(f"  boot ROM: {len(img)} bytes at ${base:04X}")

    read = "; ".join(f'read_verilog "{f}"' for f in SRC)
    step("yosys  ", [cosim._tool("yosys"), "-q", "-p",
                     f"{read}; synth_ice40 -top cool8_top -json cool8.json"])

    pnr = step("nextpnr", [cosim._tool("nextpnr-ice40"),
                           "--up5k", "--package", "sg48",
                           "--pcf", PCF, "--json", "cool8.json",
                           "--asc", "cool8.asc", "--freq", str(args.freq)])

    step("icepack", [cosim._tool("icepack"), "cool8.asc", "cool8.bin"])

    for line in pnr.splitlines():
        m = re.search(r"(SB_LUT4|SB_DFF\w*|SB_CARRY|SB_RAM40_4K|"
                      r"SB_SPRAM256KA|ICESTORM_LC|ICESTORM_RAM|"
                      r"ICESTORM_SPRAM|SB_IO):\s+(\d+)/\s*(\d+)\s+(\d+)%",
                      line)
        if m:
            print(f"    {m.group(1):<16} {m.group(2):>5} / {m.group(3):<5} "
                  f"{m.group(4):>3}%")
    # nextpnr reports twice, after placement and after routing. Only the
    # second is the answer, and it is a constraint check rather than a
    # number to admire: nextpnr fails the run if it is not met, so
    # reaching here at all means the design closed at --freq.
    fmax = [l for l in pnr.splitlines() if "Max frequency for clock" in l]
    if fmax:
        print("    " + fmax[-1].split("Info: ")[-1].strip())

    size = os.path.getsize(os.path.join(BUILD, "cool8.bin"))
    print(f"\n  build/cool8.bin, {size} bytes")
    print("  copy it onto the iCELink drive to program the board")
    return 0


if __name__ == "__main__":
    sys.exit(main())
