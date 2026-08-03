#!/usr/bin/env python3
"""The SoC: the I/O page decode, and the machine as a whole.

Three tests, in the order that localises a failure fastest:

  1. `cool8_soc_tb` — the decode, driven by loader frames over a
     bit-banged wire and then by programs the CPU runs. Fast: a short
     baud divider and a filled-in boot ROM, because what is under test
     is which block answered, not how long it took.
  2. `cool8_soc_boot_tb` — the same SoC on the parameters the bitstream
     will carry, from power-on with SPRAM undefined, running the real
     boot image. This is the one that says whether the thing boots.
  3. Synthesis: `cool8_soc` mapped to iCE40 cells, with the latch and
     hierarchy checks that `sim/synth.py` runs over `rtl/core`.

    python sim/test_soc.py
    python sim/test_soc.py --skip-boot     # the slow one

The three test programs are assembled out of `sim/asm/` on every run
rather than checked in as bytes, so the program the CPU executes is the
program in the file next to it.

Set OSS_CAD_SUITE to the toolchain root if the tools are not on PATH.
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cosim                                    # noqa: E402
import cool8asm                                 # noqa: E402
import mkrom                                    # noqa: E402

SOC = [os.path.join(ROOT, "rtl", "soc", f)
       for f in ("cool8_rom.v", "cool8_spram.v", "cool8_mem.v",
                 "cool8_uart.v", "cool8_loader.v", "cool8_soc.v")]
CORE = [os.path.join(ROOT, "rtl", "core", f)
        for f in ("cool8_alu.v", "cool8_agu.v", "cool8_core.v")]
TB = os.path.join(HERE, "tb")
ASM = os.path.join(HERE, "asm")

PROGS = ("led", "echo", "talk", "tx2")


def run(vvp, args, cwd=None):
    r = subprocess.run([cosim._tool("vvp"), vvp] + args, cwd=cwd,
                       capture_output=True, text=True)
    return "\nPASS" in r.stdout, r.stdout + r.stderr


def report(name, ok, out, detail=()):
    print(f"  {name:<44} {'ok' if ok else 'FAIL'}")
    for line in out.splitlines():
        if line.startswith("FAIL") or any(k in line for k in detail):
            print("    " + line)
    return ok


def build_progs():
    """Assemble sim/asm/soc_*.asm into hex images the testbench reads."""
    out = []
    for name in PROGS:
        a = cool8asm.assemble(os.path.join(ASM, f"soc_{name}.asm"))
        base, img = a.image()
        if base != 0x0400:
            sys.exit(f"soc_{name}.asm must be assembled at $0400, not ${base:04X}")
        path = os.path.join(BUILD, f"prog_{name}.hex")
        # Padded to the testbench's array with `xx`, which is how it
        # finds the end of the program — and it keeps $readmemh from
        # warning about a short file on every run.
        with open(path, "w") as fh:
            for b in img:
                fh.write("%02x\n" % b)
            fh.write("xx\n" * (256 - len(img)))
        out.append((name, len(img)))
    print("  test programs: " +
          ", ".join(f"{n} {c} bytes" for n, c in out))


def yosys(script, quiet=True):
    cmd = [cosim._tool("yosys")] + (["-q"] if quiet else []) + ["-p", script]
    r = subprocess.run(cmd, cwd=BUILD, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def synth():
    """Hygiene and area for cool8_soc, the same gate rtl/core gets.

    Runs in sim/build because cool8_rom.v reads its image with $readmemh
    at elaboration and yosys resolves that against its working directory.
    """
    read = "; ".join(
        [f'read_verilog -lib "{cosim.ice40_cells()}"'] +
        [f'read_verilog "{f}"' for f in SOC + CORE])

    rc, out = yosys(f"{read}; hierarchy -check -top cool8_soc; proc; opt; "
                    f"select -assert-none t:$dlatch t:$dlatchsr; check -assert")
    if rc != 0:
        print(out)
        return False, {}

    # Not quiet: `stat` prints to the log, and a combinational loop
    # through the bus is a warning rather than an error — it has to be
    # read out of the transcript or it passes silently and shows up as
    # unroutable much later.
    rc, out = yosys(f"{read}; synth_ice40 -top cool8_soc -flatten; stat",
                    quiet=False)
    if rc != 0 or "found logic loop" in out:
        print(out[-3000:] if rc != 0 else
              "    a combinational loop through the bus")
        return False, {}

    tail = out[out.rindex("=== cool8_soc ==="):]
    c = {}
    for line in tail.splitlines():
        m = re.match(r"\s+(\d+)\s+(SB_\w+)\s*$", line)
        if m:
            c[m.group(2)] = c.get(m.group(2), 0) + int(m.group(1))
    return True, c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-boot", action="store_true",
                    help="skip the cold boot, which is 30 ms of simulated time")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    os.makedirs(BUILD, exist_ok=True)
    build_progs()

    base, img, rom = mkrom.build(os.path.join(ROOT, "sw", "boot.asm"))
    with open(os.path.join(BUILD, "boot.hex"), "w") as fh:
        for b in rom:
            fh.write("%02x\n" % b)

    cells = cosim.ice40_cells()
    ok = True

    vvp = cosim._build("cool8_soc_tb", os.path.join(TB, "cool8_soc_tb.v"),
                       SOC + CORE + [cells], gen="2012")
    good, out = run(vvp, (["+verbose"] if args.verbose else []) +
                    [f"+{n}=prog_{n}.hex" for n in PROGS], cwd=BUILD)
    ok &= report("the I/O page", good, out, ["checks,"])

    if not args.skip_boot:
        vvp = cosim._build("cool8_soc_boot_tb",
                           os.path.join(TB, "cool8_soc_boot_tb.v"),
                           SOC + CORE + [cells], gen="2012")
        good, out = run(vvp, [], cwd=BUILD)
        ok &= report("booting cold, on the shipping parameters", good, out,
                     ["checks,", "clocks"])

    good, c = synth()
    if good:
        print(f"  {'cool8_soc synthesised':<44} ok")
        print(f"    {c.get('SB_LUT4', 0)} LUT4, "
              f"{sum(v for k, v in c.items() if k.startswith('SB_DFF'))} FF, "
              f"{c.get('SB_RAM40_4K', 0)} EBR, "
              f"{c.get('SB_SPRAM256KA', 0)} SPRAM")
    else:
        print(f"  {'cool8_soc synthesised':<44} FAIL")
    ok &= good

    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
