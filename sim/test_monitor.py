#!/usr/bin/env python3
"""M6's gate: type at the machine and it answers.

Runs sim/tb/cool8_mon_tb.v, which boots the whole SoC cold on the
parameters the bitstream carries -- the real boot image out of
sw/boot.asm, SPRAM undefined, the default 115200 divider -- and then
talks to it. Characters go in on the serial line and on the PS/2 clock,
and every phase names a string the monitor has to produce.

Nothing is poked and nothing is forced, so a keystroke here takes the
same path it takes on the bench: scancode on an open-drain wire, the
receiver's parity check, the FIFO, the CPU's own load through the I/O
page, the translation table in ROM, the echo, the shared transmitter.

What the phases answer:

  banner       the ROM ran, the console came up, and the monitor is
               executing in the ROM window
  unknown      a command it does not have is refused, not ignored
  D            dump $F000, which is `2F 60 ...` because that is the
               first instruction the machine executes
  ?            the help, which is here because '?' is the one command
               that is not a letter and folding case with a single
               BCLR #$20 turns it into $1F
  E then D     a byte written and read back -- the machine can be told
               something and remembers it
  U            unassemble $F000 to `LDW  X,#$0200`
  L then D     four bytes copied off a flash on the other end of the SPI
               pins and read back. The only phase that exercises the
               stall on FLS_DATA, because the copy loop has no status
               poll in it and the SPI is eight times slower than the CPU
               asking
  keyboard     $1C echoes as `a`, and as `A` with shift held, which
               exercises the make/break/prefix handling as well as the
               table

    python sim/test_monitor.py
    python sim/test_monitor.py -v      # echo everything the machine says

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
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cosim                                    # noqa: E402
import mkrom                                    # noqa: E402
import mkfont                                   # noqa: E402

TB = os.path.join(HERE, "tb", "cool8_mon_tb.v")
SOC = [os.path.join(ROOT, "rtl", "soc", f)
       for f in ("cool8_rom.v", "cool8_spram.v", "cool8_mem.v",
                 "cool8_uart.v", "cool8_loader.v", "cool8_vga.v",
                 "cool8_vregs.v", "cool8_pal.v", "cool8_fetch.v",
                 "cool8_pixel.v", "cool8_vram.v", "cool8_vport.v",
                 "cool8_pll.v", "cool8_pixport.v", "cool8_sprite.v",
                 "cool8_ps2.v", "cool8_flash.v", "cool8_snd.v",
                 "cool8_video.v", "cool8_soc.v")]
CORE = [os.path.join(ROOT, "rtl", "core", f)
        for f in ("cool8_alu.v", "cool8_agu.v", "cool8_core.v")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vcd")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    os.makedirs(BUILD, exist_ok=True)

    # The ROM and the font are built here rather than checked in, for the
    # same reason test_boot.py builds them: a stale image is a boot ROM
    # that does not match its own source, and this is the one test where
    # that would look like a broken monitor.
    base, img, rom = mkrom.build(os.path.join(ROOT, "sw", "boot.asm"))
    with open(os.path.join(BUILD, "boot.hex"), "w") as fh:
        for b in rom:
            fh.write("%02x\n" % b)
    font, _, _ = mkfont.build(os.path.join(ROOT, "assets", "font",
                                           "spleen-8x16.bdf"))
    with open(os.path.join(BUILD, "font.hex"), "w") as fh:
        for b in font:
            fh.write("%02x\n" % b)
    print(f"  boot.asm with the monitor: {len(img)} bytes, "
          f"{sum(1 for b in rom if b)} non-zero of {len(rom)}")

    vvp = cosim._build("cool8_mon_tb", TB, SOC + CORE + [cosim.ice40_cells()],
                       gen="2012")
    cmd = [cosim._tool("vvp"), os.path.abspath(vvp)]
    if args.vcd:
        cmd.append(f"+vcd={args.vcd}")
    if args.verbose:
        cmd.append("+verbose")

    r = subprocess.run(cmd, cwd=BUILD, capture_output=True, text=True)
    ok = "\nPASS" in r.stdout

    summary = ""
    for line in r.stdout.splitlines():
        if "checks," in line:
            summary = line.strip()
    print(f"  typing at the machine        {summary:<28} "
          f"{'ok' if ok else 'FAIL'}")
    if not ok:
        for line in r.stdout.splitlines():
            if line.startswith("FAIL"):
                print("    " + line)
        if args.verbose:
            print(r.stdout[-6000:])

    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
