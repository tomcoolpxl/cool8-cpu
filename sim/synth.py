#!/usr/bin/env python3
"""The M3 synthesis gate.

Three things, in the order the roadmap asks for them:

  1. Hygiene. No latches, no inferred RAM, no vendor primitives and no
     tri-state anywhere in rtl/core. A latch here would mean a case
     statement somewhere is missing a default, and it would come back as
     a hold-time failure on silicon long after it was cheap to find.

  2. FPGA gate. yosys targeting the iCE40UP5K reports LUT4 and flip-flop
     counts. docs/03-microarchitecture.md estimated roughly 1000 LUTs
     and about 137 flip-flops.

  3. ASIC proxy. Mapping to two-input gates gives a technology-neutral
     count to hold against the ~2750-gate estimate in section 5.7,
     without waiting for a full LibreLane run.

    python sim/synth.py
"""

import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORE = os.path.join(ROOT, "rtl", "core")
RTL = [os.path.join(CORE, f)
       for f in ("cool8_alu.v", "cool8_agu.v", "cool8_core.v")]

sys.path.insert(0, HERE)
import toolchain as T                                             # noqa: E402


def yosys(script):
    # cosim._tool also puts the suite's own directories on PATH, which
    # the toolchain's executables need to load their libraries. Finding
    # the binary is not the same as being able to run it.
    exe = T.tool("yosys")
    r = subprocess.run([exe, "-p", script], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        sys.exit("yosys failed")
    return r.stdout + r.stderr


READ = "read_verilog " + " ".join(f'"{f}"' for f in RTL)


def _last_stat(text, module):
    """The final `stat` block for a module — yosys prints one per pass."""
    blocks = re.findall(r"=== %s ===(.*?)(?=\n=== |\nEnd of script|\Z)"
                        % re.escape(module), text, re.S)
    if not blocks:
        sys.exit(f"no stat block for {module} in yosys output")
    return blocks[-1]


def counts(text):
    """Cell-type counts from the last `stat` block."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s+(\d+)\s+(\S+)\s*$", line)
        if m:
            out[m.group(2)] = out.get(m.group(2), 0) + int(m.group(1))
    return out


def hygiene():
    print("hygiene")
    ok = True

    # proc/opt without any technology mapping: a latch here is a real
    # incomplete assignment, not a mapping artefact.
    t = yosys(f"{READ}; hierarchy -check -top cool8_core; proc; opt; "
              f"check -assert; stat")
    c = counts(t)
    latches = sum(v for k, v in c.items() if "dlatch" in k or "sr" == k)
    print(f"  latches                        : {latches}  "
          f"{'ok' if latches == 0 else 'FAIL'}")
    ok &= latches == 0

    # After memory_map nothing may remain that is not ordinary logic.
    t = yosys(f"{READ}; hierarchy -check -top cool8_core; proc; memory_map; "
              f"opt -full; flatten; opt -full; stat")
    c = counts(t)
    mems = sum(v for k, v in c.items() if k.startswith("$mem"))
    print(f"  memories after memory_map      : {mems}  "
          f"{'ok' if mems == 0 else 'FAIL'}")
    ok &= mems == 0

    # Vendor primitives and tri-state, textually — the core must build
    # for both the FPGA and the ASIC from the same source.
    bad = []
    for f in RTL:
        # Comments talk about tri-state and initial blocks precisely
        # because there aren't any; scan the code only.
        src = re.sub(r"//[^\n]*", "", open(f, encoding="utf-8").read())
        for pat, why in ((r"\bSB_\w+", "iCE40 primitive"),
                         (r"\bsky130_\w+", "sky130 cell"),
                         (r"\btri\b", "tri-state"),
                         (r"\binitial\b", "initial block"),
                         (r"posedge\s+\w*rst", "asynchronous reset")):
            for m in re.finditer(pat, src):
                bad.append(f"{os.path.basename(f)}: {why} ({m.group(0)})")
    print(f"  vendor primitives / tri-state  : {len(bad)}  "
          f"{'ok' if not bad else 'FAIL'}")
    for b in bad:
        print("    " + b)
    ok &= not bad

    # 'z' anywhere in the core would mean a tri-state driver.
    zs = sum(len(re.findall(r"'[bhd]?[0-9a-fA-F_]*[zZ]",
                            open(f, encoding="utf-8").read())) for f in RTL)
    print(f"  high-impedance literals        : {zs}  "
          f"{'ok' if zs == 0 else 'FAIL'}")
    ok &= zs == 0
    return ok


def fpga():
    print("\nFPGA — iCE40UP5K")
    t = yosys(f"{READ}; synth_ice40 -top cool8_core -noflatten; stat")
    per = {}
    for mod in ("cool8_alu", "cool8_agu", "cool8_core"):
        m = re.search(r"=== %s ===(.*?)(?====|\Z)" % re.escape(mod), t, re.S)
        if m:
            per[mod] = counts(m.group(1))

    t2 = yosys(f"{READ}; synth_ice40 -top cool8_core -flatten; stat")
    c = counts(_last_stat(t2, "cool8_core"))
    luts = c.get("SB_LUT4", 0)
    ffs = sum(v for k, v in c.items() if k.startswith("SB_DFF"))
    carry = c.get("SB_CARRY", 0)
    rams = sum(v for k, v in c.items() if "RAM" in k)

    for mod in ("cool8_alu", "cool8_agu"):
        if mod in per:
            print(f"  {mod:<12} {per[mod].get('SB_LUT4', 0):>5} LUT4")
    print(f"  {'cool8_core':<12} {luts:>5} LUT4   {ffs} FF   "
          f"{carry} carry")
    print(f"  inferred block RAM             : {rams}  "
          f"{'ok' if rams == 0 else 'FAIL'}")
    print(f"  against the ~1000 LUT estimate : "
          f"{'inside' if luts <= 1300 else 'OVER — investigate'}")
    return rams == 0, luts, ffs


def asic_proxy():
    print("\nASIC proxy — mapped to two-input gates")
    t = yosys(f"{READ}; hierarchy -check -top cool8_core; synth -top "
              f"cool8_core -flatten; abc -g AND,NAND,OR,NOR,XOR,XNOR; "
              f"opt_clean; stat")
    c = counts(_last_stat(t, "cool8_core"))
    gates = sum(v for k, v in c.items()
                if k.startswith("$_") and not k.startswith("$_DFF")
                and not k.startswith("$_SDFF"))
    ffs = sum(v for k, v in c.items()
              if k.startswith("$_DFF") or k.startswith("$_SDFF"))
    # A flip-flop is worth roughly six two-input gates in a standard cell
    # library; that is the convention docs/03 section 5.7 was written in.
    equiv = gates + ffs * 6
    print(f"  combinational two-input gates  : {gates}")
    print(f"  flip-flops                     : {ffs}")
    print(f"  gate equivalents (FF = 6)      : {equiv}")
    print(f"  section 5.7 estimated          : 2750")
    return equiv, ffs


def main():
    ok = hygiene()
    ram_ok, luts, ffs = fpga()
    equiv, affs = asic_proxy()
    ok &= ram_ok
    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
