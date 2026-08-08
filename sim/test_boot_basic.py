#!/usr/bin/env python3
"""M16 -- the board, from reset: flash, to BASIC, to a keyboard.

    python sim/test_boot_basic.py

Every other test of BASIC pokes the image into `$A000` and clears ROMEN
by hand. That is a convenience, and it means no test has ever run the
sequence a board actually runs. This one does:

  reset          with ROMEN on and nothing in RAM
  autoboot       the ROM finds BOOT.BIN on drive 0 and loads it to $0200
  the stub       moves the image to $A000, drops the overlay, jumps
  BASIC          starts, installs its interrupt, and draws its banner
  the keyboard   a program is typed at the PS/2 port and RUN

Nothing is placed by the harness. If `tools/mkboot.py` gets the length
wrong, if ROMEN is dropped in the wrong order, if BASIC's vector never
gets installed, or if the keyboard interrupt is not enabled, this fails
and the others still pass -- which is the point of it.

**Why the stub exists.** Autoboot loads to `$0200` because that is where
a small program goes; BASIC links at `$A000` because program text grows
up from `$0200` and the screen is at `$8000`. Rather than teach a 4 KB
ROM with 36 bytes free to read a load address -- in the one part of the
machine that cannot be reflashed -- the file carries its own relocation.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8vm as vm                                       # noqa: E402
import cool8disk as disk                                   # noqa: E402
import mkboot                                              # noqa: E402
import test_basic as B                                     # noqa: E402

IMG = os.path.join(BUILD, "bootbasic.img")
FAILS = []


def check(ok, what, detail=""):
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


def image(boot):
    """A formatted volume 0 with BOOT.BIN on it, built by the PC tool."""
    if os.path.exists(IMG):
        os.remove(IMG)
    img = disk.Image(IMG, create=True)
    v = disk.Volume(img, 0)
    v.format("SYSTEM")
    p = os.path.join(BUILD, "BOOT.BIN")
    with open(p, "wb") as fh:
        fh.write(boot)
    v.add(p, "BOOT.BIN")
    img.save()


def settle(m, syms, budget=40_000_000):
    """Wait for the editor to go idle, as sim/test_basic.py does.

    Same three conditions: nothing in either FIFO, nothing in the ring,
    and the CPU sitting at rawkey's "nothing waiting" branch.
    """
    idle = syms["s_rawkey.rk0"]
    head, tail = syms["irhead"], syms["irtail"]
    for _ in range(budget):
        if (not m.uart.rx and not m.kbd.q
                and m.bus.mem[head] == m.bus.mem[tail]
                and m.cpu.pc == idle):
            return True
        m.tick()
    return False


def key(m, syms, text):
    for ch in text:
        m.key([ch])
        if not settle(m, syms):
            raise SystemExit("the machine never went idle after %r" % ch)


def main():
    print("  M16 -- reset to BASIC to a keypress, on a flash image")
    print()

    code, syms = B.build()
    boot = mkboot.build(code, dest=0xA000, build_dir=BUILD)
    print(f"  basic.bin {len(code):,} bytes, "
          f"BOOT.BIN {len(boot):,} with its stub")
    print()
    image(boot)

    m = vm.boot(flash_path=IMG)
    check(m.romen, "the machine comes out of reset with ROMEN on")

    # 40 frames is what sim/test_autoboot.py allows for the ROM to clear
    # RAM, walk the directory and load the file; the copy and BASIC's
    # own start-up are on top of that.
    for _ in range(90):
        m.run_frame()

    check(not m.romen,
          "and the stub dropped the overlay before jumping",
          "SYSCTRL=$%02X" % m.bus.read(0xFE00))
    check(bytes(m.bus.mem[0xA000:0xA000 + 64]) == code[:64],
          "the image was relocated to $A000, byte for byte")
    check(bytes(m.bus.mem[0xA000 + len(code) - 64:0xA000 + len(code)])
          == code[-64:],
          "including its last bytes, which live under the ROM window",
          "ends at $%04X" % (0xA000 + len(code) - 1))

    vec = m.bus.mem[0xFFFC] | (m.bus.mem[0xFFFD] << 8)
    check(vec == syms["iisr"],
          "BASIC installed its own interrupt vector",
          "$%04X, wanted $%04X" % (vec, syms["iisr"]))
    check(m.kbd.irq_en, "and enabled the keyboard's interrupt")
    check(m.shows("COOL8 BASIC 1.0"),
          "it booted to its banner with nothing attached",
          " | ".join(r.strip() for r in m.text() if r.strip())[:120])

    # ---- and it takes a program from the keyboard, not the cable
    if not settle(m, syms):
        raise SystemExit("BASIC never went idle")
    key(m, syms, '10 PRINT 6 * 7\r20 END\r')
    check(any("PRINT 6 * 7" in r for r in m.text()),
          "a program typed at the PS/2 port reaches the editor")

    key(m, syms, "RUN\r")
    check(m.shows("42"),
          "and RUN, typed the same way, prints its answer",
          " | ".join(r.strip() for r in m.text() if r.strip())[:120])

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
