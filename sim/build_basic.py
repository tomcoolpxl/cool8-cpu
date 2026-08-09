#!/usr/bin/env python3
"""Build the system image and the bootable file, and report the sizes.

    python sim/build_basic.py          (or: npm run build)

`sim/test_basic.py` builds `basic.bin` as a side effect of testing it,
which is fine for a test and no use at all when what you want is the
artifact. This produces both of them and prints what they cost, because
the size at every milestone is the number this project is judged on --
the system has to stay inside `$A000-$FDFF` and nothing warns you as it
fills.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import mkboot                                              # noqa: E402
import test_basic as B                                     # noqa: E402

TOP = 0xFE00            # the I/O page: the system ends below this
ORG = 0xA000


def main():
    code, _ = B.build()
    boot = mkboot.build(code, dest=ORG, build_dir=BUILD)
    with open(os.path.join(BUILD, "BOOT.BIN"), "wb") as fh:
        fh.write(boot)

    end = ORG + len(code)
    free = TOP - end
    print(f"  basic.bin  {len(code):>7,} bytes  ${ORG:04X}-${end - 1:04X}")
    print(f"  BOOT.BIN   {len(boot):>7,} bytes  "
          f"({len(boot) - len(code)} of relocating stub)")
    print(f"  free       {free:>7,} bytes  to ${TOP - 1:04X}")
    if free < 0:
        print("  the system does not fit below the I/O page")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
