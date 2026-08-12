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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import cool8rsvm as vm                                     # noqa: E402
import cool8disk as disk                                   # noqa: E402
import mkboot                                              # noqa: E402
import ioregs                                              # noqa: E402
import test_basic as B                                     # noqa: E402

BUILD = H.BUILD

IMG = os.path.join(BUILD, "bootbasic.img")
FAILS = H.FAILS


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
    """Wait for the editor to go idle — m.settle, the machine's own
    idle test (same conditions sim/test_basic.py names: both FIFOs
    empty, the ring drained, the CPU at rawkey's idle branch)."""
    return m.settle(syms["in_raw.rk0"], syms["irhead"], syms["irtail"],
                    budget)


def key(m, syms, text):
    for ch in text:
        m.key([ch])
        if not settle(m, syms):
            raise SystemExit("the machine never went idle after %r" % ch)


def modes(syms):
    """Every video mode, typed at the keyboard, counted in **pixels**.

    **This is the only check in the tree that asks what a person sees.**
    `m.row()` and the cell map at $8000 both answer from main RAM, and
    `rust/src/render.rs` reads main RAM only for the text engine -- the
    tile and bitmap engines fetch from VRAM, which `bglyph` fills
    through VRAM_DATA. So a mode can have the right characters in the
    map, the right geometry in the console and the right colour in the
    palette, and still show nothing at all. It did: modes 2 to 6 were
    reported working three times off checks that never looked at a
    pixel.

    `vm.boot(render=True)` is `poe emu` without the window -- the real
    ROM, the real font, the real scanline renderer, the flash image the
    board would run.
    """
    m = vm.boot(flash_path=IMG, render=True)
    for _ in range(90):
        m.run_frame()
    if not settle(m, syms):
        raise SystemExit("BASIC never went idle")
    base = lit(m)
    for mode in range(7):
        key(m, syms, "MODE %d\r" % mode)
        blank = lit(m)
        key(m, syms, 'PRINT "COOL8COOL8"\r')
        after = lit(m)
        # The text has to add pixels the empty screen did not have.
        # Comparing against the same mode's own blank screen is what
        # keeps a mode that paints a border from passing on the border.
        # The console's own view of the screen, so a failure says which
        # number is wrong rather than only that nothing appeared.
        w = lambda n: m.bus.mem[syms[n]] | (m.bus.mem[syms[n] + 1] << 8)
        b = lambda n: m.bus.mem[syms[n]]
        check(after > blank + 200,
              "MODE %d shows what is typed at it" % mode,
              "%d lit before, %d after (idle %d) | CBASE $%04X CSTR $%04X "
              "CGS8 $%04X CBPC %d CFROW %d CKIND %d | VID_BASE $%02X%02X "
              "STRIDE $%02X%02X"
              % (blank, after, base, w("cbase"), w("cstr"), w("cgs8"),
                 b("cbpc"), b("cfrow"), b("ckind"),
                 m.bus.read(0xFF13), m.bus.read(0xFF12),
                 m.bus.read(0xFF15), m.bus.read(0xFF14)))
        key(m, syms, "CLS\r")


def lit(m, frames=2):
    """Pixels that differ from the background, after scanning out.

    Two frames because the first may be joined part-way -- the reason
    sim/test_vm.py takes two.
    """
    m.run_frame(frames)
    fb = m.fb()
    bg = max(set(fb), key=fb.count)
    return sum(1 for v in fb if v != bg)


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
          "SYSCTRL=$%02X" % m.bus.read(ioregs.addr_of("SYS_CTRL")))
    check(bytes(m.bus.mem[0xA000:0xA000 + 64]) == code[:64],
          "the image was relocated to $A000, byte for byte")
    check(bytes(m.bus.mem[0xA000 + len(code) - 64:0xA000 + len(code)])
          == code[-64:],
          "including its last bytes, which live under the ROM window",
          "ends at $%04X" % (0xA000 + len(code) - 1))

    # Where the CPU actually is, because "the vector is still the ROM's"
    # has two causes -- BASIC did not install it, or BASIC has not got
    # there yet -- and they need different fixes.
    near = min(((abs(m.cpu.pc - a), n) for n, a in syms.items()
                if a <= m.cpu.pc), default=(0, "?"))
    print("  after 90 frames: pc $%04X, nearest symbol %s"
          % (m.cpu.pc, near[1]))
    for i, r in enumerate(m.text()[:10]):
        if r.strip():
            print("    row %-2d %r" % (i, r.strip()))
    vec = m.bus.mem[0xFFFC] | (m.bus.mem[0xFFFD] << 8)
    check(vec == syms["iisr"],
          "BASIC installed its own interrupt vector",
          "$%04X, wanted $%04X" % (vec, syms["iisr"]))
    check(m.kbd.irq_en, "and enabled the keyboard's interrupt")
    check(m.shows("COOLBASIC " + mkboot.VERSION),
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

    # ---- the restart chords (D54)
    #
    # Raw scancodes, because that is what the chords are: the keyboard
    # decodes them before anything software could, and `m.key()` would
    # go through sw/keymap.asm and produce characters instead.
    #
    # First the machine is put in the state a program leaves behind --
    # mode 4, a bitmap the editor cannot be read on -- because that is
    # what a restart is for.
    print()
    key(m, syms, "MODE 4\r")
    check(m.bus.read(ioregs.addr_of("VID_MODE")) & 0x0F == 4, "a program leaves mode 4 behind",
          "VID_MODE=$%02X" % m.bus.read(ioregs.addr_of("VID_MODE")))

    m.scancode([0x14, 0x76, 0xF0, 0x76, 0xF0, 0x14])       # Ctrl+Esc
    settle(m, syms)
    check(m.bus.read(ioregs.addr_of("VID_MODE")) & 0x0F == 0,
          "Ctrl+Esc puts the editor back in mode 0",
          "VID_MODE=$%02X" % m.bus.read(ioregs.addr_of("VID_MODE")))
    check(not any(r.strip() for r in m.text()),
          "...and the screen it left behind is cleared",
          " | ".join(r.strip() for r in m.text() if r.strip())[:120])
    key(m, syms, "LIST\r")
    check(any("PRINT 6 * 7" in r for r in m.text()),
          "...and the warm restart kept the program",
          " | ".join(r.strip() for r in m.text() if r.strip())[:120])

    # Cold: the keyboard resets the machine itself, so this is the whole
    # boot path again -- ROM, autoboot, the stub -- and the program is
    # gone because BASIC's init wipes user RAM on the way up.
    m.scancode([0x14, 0x12, 0x76, 0xF0, 0x76, 0xF0, 0x12, 0xF0, 0x14])
    for _ in range(90):
        m.run_frame()
    check(m.shows("COOLBASIC " + mkboot.VERSION),
          "Ctrl+Shift+Esc reboots the machine from flash",
          " | ".join(r.strip() for r in m.text() if r.strip())[:120])
    settle(m, syms)
    key(m, syms, "LIST\r")
    check(not any("PRINT 6 * 7" in r for r in m.text()),
          "...and the cold restart took the program with it",
          " | ".join(r.strip() for r in m.text() if r.strip())[:120])

    print()
    modes(syms)

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
