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

import toolchain as T                           # noqa: E402
import mkrom                                    # noqa: E402
import mkfont                                   # noqa: E402

SRC = [os.path.join(ROOT, "rtl", "core", f)
       for f in ("cool8_alu.v", "cool8_agu.v", "cool8_core.v")] + \
      [os.path.join(ROOT, "rtl", "soc", f)
       for f in ("cool8_rom.v", "cool8_spram.v", "cool8_mem.v",
                 "cool8_uart.v", "cool8_loader.v", "cool8_vga.v",
                 "cool8_vregs.v", "cool8_pal.v", "cool8_fetch.v",
                 "cool8_pixel.v", "cool8_vram.v", "cool8_vport.v",
                 "cool8_pll.v", "cool8_pixport.v", "cool8_sprite.v",
                 "cool8_ps2.v", "cool8_flash.v", "cool8_snd.v",
                 "cool8_video.v", "cool8_soc.v",
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


def fmax(pnr):
    """{clock name: MHz} from nextpnr's *final* report.

    nextpnr reports twice, after placement and after routing, and only
    the second is the answer. Taking the last line rather than the last
    *pass* is how you end up quoting the placement estimate for whichever
    clock happens to print last, so the whole block is re-collected and
    later entries overwrite earlier ones by name.
    """
    out = {}
    for line in pnr.splitlines():
        m = re.search(r"Max frequency for clock\s+'([^']+)':\s+"
                      r"([\d.]+)\s*MHz", line)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def cells(pnr):
    """The device utilisation table, as printed lines."""
    out = []
    for line in pnr.splitlines():
        m = re.search(r"(SB_LUT4|SB_DFF\w*|SB_CARRY|SB_RAM40_4K|"
                      r"SB_SPRAM256KA|ICESTORM_LC|ICESTORM_RAM|"
                      r"ICESTORM_SPRAM|SB_IO):\s+(\d+)/\s*(\d+)\s+(\d+)%",
                      line)
        if m:
            out.append(f"    {m.group(1):<16} {m.group(2):>5} / "
                       f"{m.group(3):<5} {m.group(4):>3}%")
    return out


def clock_of(fm, want):
    """Fmax for the clock whose name contains `want`, or None.

    nextpnr decorates names — `sclk_$glb_clk`, `clk$SB_IO_IN` — so an
    exact match finds nothing and a substring is what works.
    """
    for k, v in fm.items():
        if want in k:
            return v
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", type=float, default=8.375,
                    help="the constraint to close against, in MHz")
    ap.add_argument("--seed", type=int, default=None,
                    help="nextpnr placer seed")
    ap.add_argument("--seeds", type=int, default=0, metavar="N",
                    help="sweep seeds 1..N and report Fmax per clock, "
                         "instead of building. Placement is the only "
                         "seeded step, so yosys runs once. Use this "
                         "rather than one run: D32 and D38 both measured "
                         "a ~6%% spread, and D38 is the cautionary tale "
                         "of a single-seed result that was noise.")
    args = ap.parse_args()

    os.makedirs(BUILD, exist_ok=True)

    font, _, _ = mkfont.build(os.path.join(ROOT, "assets", "font",
                                           "spleen-8x16.bdf"))
    import palette
    palette.stage(BUILD)

    with open(os.path.join(BUILD, "font.hex"), "w") as fh:
        for b in font:
            fh.write("%02x\n" % b)

    base, img, rom = mkrom.build(os.path.join(ROOT, "sw", "boot.asm"))
    with open(os.path.join(BUILD, "boot.hex"), "w") as fh:
        for b in rom:
            fh.write("%02x\n" % b)
    print(f"  boot ROM: {len(img)} bytes at ${base:04X}")

    read = "; ".join(f'read_verilog "{f}"' for f in SRC)
    step("yosys  ", [T.tool("yosys"), "-q", "-p",
                     f"{read}; synth_ice40 -dsp -top cool8_top -json cool8.json"])

    def nextpnr(seed=None):
        argv = [T.tool("nextpnr-ice40"), "--up5k", "--package", "sg48",
                "--pcf", PCF, "--json", "cool8.json",
                "--asc", "cool8.asc", "--freq", str(args.freq)]
        if seed is not None:
            argv += ["--seed", str(seed)]
        return step("nextpnr" if seed is None else f"seed {seed:<2}", argv)

    if args.seeds:
        rows, util = [], []
        for s in range(1, args.seeds + 1):
            pnr = nextpnr(s)
            rows.append((s, fmax(pnr)))
            util = util or cells(pnr)     # placement-invariant, take one
        print()
        for line in util:
            print(line)
        names = sorted({k for _, fm in rows for k in fm})
        print()
        print(f"  {'seed':>4}  " + "  ".join(f"{n:>22}" for n in names))
        for s, fm in rows:
            print(f"  {s:>4}  " + "  ".join(
                f"{fm.get(n, float('nan')):>18.2f} MHz" for n in names))
        print()
        for n in names:
            v = [fm[n] for _, fm in rows if n in fm]
            if not v:
                continue
            mean = sum(v) / len(v)
            print(f"    {n:<24} mean {mean:6.2f}  min {min(v):6.2f}  "
                  f"max {max(v):6.2f}  spread "
                  f"{(max(v) - min(v)) / mean * 100:4.1f}%")
        print()
        return 0

    pnr = nextpnr(args.seed)

    step("icepack", [T.tool("icepack"), "cool8.asc", "cool8.bin"])

    for line in cells(pnr):
        print(line)
    # A constraint check rather than a number to admire: nextpnr fails the
    # run if --freq is not met, so reaching here means the design closed.
    # One seed is not a measurement of Fmax, though — use --seeds for that.
    for n, v in sorted(fmax(pnr).items()):
        print(f"    Fmax {n:<24} {v:7.2f} MHz")

    size = os.path.getsize(os.path.join(BUILD, "cool8.bin"))
    print(f"\n  build/cool8.bin, {size} bytes")
    print("  copy it onto the iCELink drive to program the board")
    return 0


if __name__ == "__main__":
    sys.exit(main())
