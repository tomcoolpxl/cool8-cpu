#!/usr/bin/env python3
"""M15 -- autoboot, and the monitor's raw flash write.

    python sim/test_autoboot.py

Two new things in the boot ROM, both checked on `tools/cool8vm.py` with
a real flash image built by `tools/cool8disk.py`:

  autoboot   the ROM looks on drive 0 for BOOT.BIN, loads it to $0200
             and runs it -- so a board with an OS on its flash comes up
             in the OS with nothing attached
  no BOOT    and a volume without one falls through to the monitor,
             which is what a blank board does and what you want while
             developing
  W          the monitor programs memory into flash, and the PC tool
             reads back what it wrote
  the floor  a W below $100000 is refused in gates, sets the flag, and
             changes nothing

**The image is built by the PC tool, not by hand.** If the ROM's idea of
a directory entry and `cool8disk.py`'s ever drift apart, autoboot stops
finding the file -- which is the same two-implementations check
`sim/test_fs.py` makes, one layer down.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8vm as vm                                     # noqa: E402
import cool8disk as disk                                 # noqa: E402

IMG = os.path.join(BUILD, "autoboot.img")
FAILS = []


def check(ok, what, detail=""):
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


def fresh_image(with_boot=None):
    if os.path.exists(IMG):
        os.remove(IMG)
    img = disk.Image(IMG, create=True)
    v = disk.Volume(img, 0)
    v.format("SYSTEM")
    if with_boot is not None:
        p = os.path.join(BUILD, "bootimg.bin")
        with open(p, "wb") as fh:
            fh.write(with_boot)
        v.add(p, "BOOT.BIN")
    img.save()


def boot(frames=40):
    m = vm.boot(flash_path=IMG)
    for _ in range(frames):
        m.run_frame()
    return m


def main():
    print("  M15 -- autoboot and the W command")
    print()

    # A program that writes a signature and stops, so "it ran" is a fact
    # rather than an inference.
    prog = bytes([
        0x00, 0xAB,                     # MOV R0,#$AB
        0x69, 0x00, 0x30,               # ST [$3000],R0
        0x00, 0xCD,                     # MOV R0,#$CD
        0x69, 0x01, 0x30,               # ST [$3001],R0
        0x21,                           # HALT
    ])

    # ---- 1. a volume with BOOT.BIN on it
    fresh_image(prog)
    m = boot()
    ran = m.bus.mem[0x3000] == 0xAB and m.bus.mem[0x3001] == 0xCD
    check(ran, "BOOT.BIN was found, loaded to $0200 and run",
          f"$3000={m.bus.mem[0x3000]:02X} $3001={m.bus.mem[0x3001]:02X} "
          f"pc=${m.cpu.pc:04X}")
    check(bytes(m.bus.mem[0x200:0x200 + len(prog)]) == prog,
          "and the image in memory is the file, byte for byte")

    # ---- 2. a volume without one
    fresh_image(None)
    m = boot()
    out = m.uart.take().decode("latin-1")
    check("COOL8 monitor" in out,
          "with no BOOT.BIN it falls through to the monitor",
          repr(out[:60]))
    check(m.bus.mem[0x3000] == 0x00,
          "and nothing was run")

    # ---- 3. the RAM is still clear where the boot sequence promises
    clear = all(m.bus.mem[a] == 0 for a in range(0xEF60, 0xEF70))
    check(clear, "autoboot tidied its scratch away",
          f"{[hex(m.bus.mem[a]) for a in range(0xEF60, 0xEF66)]}")

    # ---- 4. W writes to flash, and the PC tool reads it back
    fresh_image(None)
    m = vm.boot(flash_path=IMG)
    # Boot first. The ROM clears $0000-$EFFF, so anything put in RAM
    # before the machine has run is gone by the time the monitor asks.
    vm.converse(m, "", frames=20)
    payload = b"written by the monitor"
    m.bus.mem[0x4000:0x4000 + len(payload)] = payload
    out = vm.converse(m, f"W 4000 {len(payload):X} 7F00\\r", frames=90)
    m.flash.flush()
    raw = disk.Image(IMG).data
    at = 0x7F0000
    check("ok" in out and bytes(raw[at:at + len(payload)]) == payload,
          f"W programmed {len(payload)} bytes at $7F0000",
          f"reply {out.strip()[-30:]!r} got {bytes(raw[at:at+8])!r}")

    # ---- 5. and the floor still refuses
    before = bytes(disk.Image(IMG).data[:32])
    m = vm.boot(flash_path=IMG)
    vm.converse(m, "", frames=20)
    m.bus.mem[0x4000] = 0x5A
    out = vm.converse(m, "W 4000 1 0000\\r", frames=60)
    m.flash.flush()
    after = bytes(disk.Image(IMG).data[:32])
    check("refused" in out and before == after,
          "a W below $100000 is refused, and nothing changes",
          f"reply {out.strip()[-40:]!r}")

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
