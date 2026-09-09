#!/usr/bin/env python3
"""Build and package UCSD Pascal p-System II.0 for COOL8.

1. Assembles sw/pascal/pascal.asm -> build/PASCAL.BIN
2. Writes system.vol directly into Drive 15 of demos.img (flash offset $790000)
3. Adds PASCAL.BIN and PASCAL.BAS to demos.img
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8disk as disk
import flash
import harness as H


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--img", default=None,
                        help="Path to flash disk image (default: updates both sim/build/demos.img and demos.img)")
    args = parser.parse_args()

    targets = [args.img] if args.img else [
        os.path.join(H.BUILD, "demos.img"),
        os.path.join(ROOT, "demos.img")
    ]

    os.makedirs(H.BUILD, exist_ok=True)
    asm_src = os.path.join(ROOT, "sw", "pascal", "pascal.asm")
    bin_path = os.path.join(H.BUILD, "PASCAL.BIN")
    sym_path = os.path.join(H.BUILD, "pascal.sym")

    print("Assembling sw/pascal/pascal.asm...")
    code, syms = H.assemble(asm_src, name="pascal", write=True)
    print(f"  PASCAL.BIN: {len(code)} bytes")

    # Read system.vol (256 KB)
    vol_path = os.path.join(ROOT, "tools", "ucsd-psystem-vm", "disk-images", "system.vol")
    if not os.path.exists(vol_path):
        raise FileNotFoundError(f"system.vol not found at {vol_path}")
    with open(vol_path, "rb") as f:
        system_vol = f.read()
    print(f"  system.vol: {len(system_vol)} bytes ({len(system_vol) // 512} blocks)")

    # Package into each target disk image
    prg = bytes([0x00, 0x02]) + bytes(code)
    prg_path = os.path.join(H.BUILD, "PASCAL.PRG")
    with open(prg_path, "wb") as f:
        f.write(prg)

    for target in targets:
        if not os.path.exists(target):
            disk.make_image(target)

        im = disk.Image(target)

        # Write system.vol directly to Drive 15 flash sectors ($790000)
        v15_offset = disk.vol_base(disk.PASCAL_VOL)
        im.data[v15_offset:v15_offset + len(system_vol)] = system_vol

        try:
            vol14 = disk.Volume(im, disk.SOFTWARE_VOL)
            try:
                vol14.delete("PASCAL.BIN")
            except BaseException:
                pass
            vol14.add(prg_path, "PASCAL.BIN")
        except BaseException as e:
            print(f"  Note: Volume 14 update for {target}: {e}")

        im.save()
        print(f"  Updated {os.path.relpath(target, ROOT)}: Drive 15 system.vol, Drive 14 PASCAL.BIN")

    bas_src = os.path.join(ROOT, "demos", "pascal.bas")
    if os.path.exists(bas_src):
        import test_basic as B
        import cool8rsvm as vm
        bcode, bsyms = B.build()
        for target in targets:
            m = vm.boot(flash_path=target, render=True)
            for _ in range(90):
                m.run_frame()
            H.settle(m, bsyms)
            H.key(m, bsyms, "DRIVE %d\r" % disk.SOFTWARE_VOL)
            H.key(m, bsyms, "NEW\r")
            for line in open(bas_src, encoding="utf-8").read().splitlines():
                if line.strip():
                    H.line(m, bsyms, line)
            H.key(m, bsyms, 'SAVE "PASCAL"\r')
            m.flash.flush()
            print(f"  Typed and saved PASCAL.BAS onto {os.path.relpath(target, ROOT)} Drive 14")

    print("UCSD Pascal p-System packaging complete.")


if __name__ == "__main__":
    main()
