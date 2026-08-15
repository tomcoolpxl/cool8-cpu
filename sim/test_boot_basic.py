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

import harness as H
import memmap                                      # noqa: E402
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
    """The shipping disk layout, built by the PC tool.

    **`disk.make_image`, not a private layout here.** Which volume is
    what is `tools/cool8disk.py`'s, shared with `tools/flash.py` and
    `tools/mkdemos.py`; a copy in this file is a fourth answer to the
    question and would not have caught volume 1 being unformatted.
    """
    p = os.path.join(BUILD, "BOOT.BIN")
    with open(p, "wb") as fh:
        fh.write(boot)
    disk.make_image(IMG, bootbin=p)


settle = H.settle          # the shared pair, sim/harness.py
key = H.key


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
        # One bit per pixel can only name palette entries 0 and 1, so
        # mode 3 writes its text in entry 1 whatever that is. The
        # console used to force it to white; the bitstream carries the
        # palette now ([D77]) and entry 1 is bank 0's blue, which is a
        # choice rather than an accident. **What still has to hold is
        # that it is not black** -- entry 1 equal to entry 0 is text
        # that cannot be seen, which is the fault the override existed
        # for and the one worth keeping a check on.
        if mode == 3:
            pal = m.palette()
            check(pal[1] != pal[0] and pal[1] != 0,
                  "...and MODE 3's text colour is visible against entry 0",
                  "entry 1 is $%03X, entry 15 is $%03X" % (pal[1], pal[15]))
        key(m, syms, "CLS\r")

    # Back to a text mode, where the cursor is the hardware's again.
    #
    # **This is a standing check, not a reproduction.** Coming back from
    # a graphics mode blinks a cursor in the wrong spot until a key
    # moves it, and this is not that bug: measured at idle straight
    # after the switch, CUR_X/CUR_Y already agree with CCX/CCY, with or
    # without con_geom placing them. So the stale-register explanation
    # is ruled out and the real one is still open -- most likely the
    # inverted cell the soft cursor last drew, which nothing erases on
    # the way out of a graphics mode. Kept because the agreement is
    # worth holding on to while that is chased.
    key(m, syms, "MODE 4\r")
    for _ in range(4):
        key(m, syms, 'PRINT "X"\r')
    key(m, syms, "MODE 0\r")
    cx, cy = m.bus.mem[syms["ccx"]], m.bus.mem[syms["ccy"]]
    check((m.bus.read(ioregs.addr_of("CUR_X")),
           m.bus.read(ioregs.addr_of("CUR_Y"))) == (cx, cy),
          "coming back to a text mode places the cursor, not just its style",
          "hardware ($%02X,$%02X), console ($%02X,$%02X)"
          % (m.bus.read(ioregs.addr_of("CUR_X")),
             m.bus.read(ioregs.addr_of("CUR_Y")), cx, cy))


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
    boot = mkboot.build(code, dest=memmap.ORG, build_dir=BUILD)
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
    check(bytes(m.bus.mem[memmap.ORG:memmap.ORG + 64]) == code[:64],
          "the image was relocated to $A000, byte for byte")
    check(bytes(m.bus.mem[memmap.ORG + len(code) - 64:memmap.ORG + len(code)])
          == code[-64:],
          "including its last bytes, which live under the ROM window",
          "ends at $%04X" % (memmap.ORG + len(code) - 1))

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

    # **Two programs, two languages, one number.** The boot banner's
    # byte count is computed by tools/mkboot.py from the claims in
    # tools/memmap.py; `FREE` is computed by prg_free on the machine
    # from the SYSBOT the assembler got. Nothing made them agree, and
    # they did not: prg_free subtracted USERTOP, which is the last byte
    # a program may use rather than the first byte it may not, so FREE
    # answered one less than the screen it was printed under.
    # **Parsed signed, and this check is why.** It read the number with
    # `.isdigit()`, which is False for "-25088" -- so when [D70] pushed
    # the free count past 32767 and `num_put` printed it signed, the
    # machine said `-25088 BYTES FREE` under a banner reading `40448`
    # and this check dropped the bad row on the floor before comparing.
    # Both assertions passed. A filter that discards exactly the shape
    # of the failure is not a filter, it is a blind spot.
    settle(m, syms)
    key(m, syms, "FREE\r")
    said = [r.strip() for r in m.text() if "BYTES FREE" in r]
    nums = set()
    for r in said:
        w = r.split()[0]
        nums.add(int(w) if w.lstrip("-").isdigit() else w)
    check(len(said) >= 2 and len(nums) == 1,
          "FREE answers the same number the boot banner printed",
          "rows %s" % said)
    check(nums == {mkboot.FREE},
          "...and that number is the one the claims say",
          "machine %s, tools/mkboot.py %d" % (sorted(nums, key=str), mkboot.FREE))

    # **A program long enough to scroll the screen.** `ed_read` rebuilds
    # the logical line by reading back the cells the console painted, and
    # a cell the console has never touched holds $00, not $20. It trimmed
    # trailing blanks by testing for $20 alone, so the first line typed
    # onto a row with unpainted cells took the whole 80-column row into
    # the record -- 74 bytes for `PRINT 1` instead of 5. Nothing showed:
    # LIST was right, RUN was right, and only READ failed, because the
    # padding sits inside the record's own length and `dnext` lands in
    # it. It reached the disc through SAVE, so a typed-in program was
    # silently damaged for good. Forty identical lines is the smallest
    # case that scrolls; every record must be 9 bytes.
    settle(m, syms)
    key(m, syms, "NEW\r")
    for i in range(1, 41):
        key(m, syms, "%d PRINT 1\r" % (i * 10))
    end = m.bus.mem[syms["progend"]] | (m.bus.mem[syms["progend"] + 1] << 8)
    bad, p = [], 0x0200
    while p < end - 3:
        n = m.bus.mem[p + 2]
        if n != 5:
            bad.append((m.bus.mem[p] | (m.bus.mem[p + 1] << 8), n))
        if n == 0:
            break
        p += 4 + n
    check(end - 0x0200 == 40 * 9 and not bad,
          "forty typed lines store forty records, none padded by the screen",
          "%d bytes, wanted %d; padded %s" % (end - 0x0200, 40 * 9, bad[:4]))

    # **A cold machine comes up on drive 1, and drive 1 is there.** The
    # ROM walks volume 0 for BOOT.BIN and cannot be told otherwise, so
    # coming up on 0 put every unqualified SAVE beside the file the
    # machine boots from. FSDRV was never initialised at all -- it
    # inherited the zero from the RAM wipe -- and `fsc_init` sets it now.
    # The address is asked of the claims, never written down here.
    fsdrv = next(c.addr for c in memmap.asm_claims() if c.name == "FSDRV")
    check(m.bus.mem[fsdrv] == disk.USER_VOL,
          "a cold machine comes up on drive %d, not the boot volume"
          % disk.USER_VOL,
          "FSDRV = %d" % m.bus.mem[fsdrv])

    # ...and the disk it starts on is formatted. `poe disk` built volume
    # 0 alone until the default moved, which boots to a machine whose
    # every DIR and SAVE fails on a disk that looks fine.
    v = disk.Volume(disk.Image(IMG), disk.USER_VOL)
    ok = True
    try:
        v.files()
    except Exception:
        ok = False
    check(ok, "...and that drive is formatted, so DIR and SAVE work")

    settle(m, syms)
    key(m, syms, 'SAVE "DEFDRV"\r')
    m.flash.flush()            # the write is the machine's until it is asked
    names = [disk.show_name(e["name"])
             for e in disk.Volume(disk.Image(IMG), disk.USER_VOL).files()]
    check(any(n.startswith("DEFDRV") for n in names),   # SAVE adds .BAS
          "an unqualified SAVE lands on the user's drive, not the ROM's",
          "drive %d holds %s" % (disk.USER_VOL, names))

    # **COLOR is the pen, and it is one byte: bg high, fg low.** It
    # has PALETTE's token, which had been `bad` since PALETTE was
    # removed -- a spelling the machine only ever answered ?SYNTAX
    # to. The paper is optional because changing ink is the common
    # case, so `COLOR 1` must keep the nibble it was not asked about.
    settle(m, syms)
    cattr = syms["cattr"]
    key(m, syms, "COLOR 14,6\r")
    both = m.bus.mem[cattr]
    key(m, syms, "COLOR 1\r")
    inkonly = m.bus.mem[cattr]
    key(m, syms, "COLOR 31,255\r")
    masked = m.bus.mem[cattr]
    check(both == 0x6E, "COLOR fg,bg is one byte, paper high ink low",
          "got $%02X, wanted $6E" % both)
    check(inkonly == 0x61, "...and COLOR fg alone keeps the paper",
          "got $%02X, wanted $61" % inkonly)
    # 31 AND 15 is 15, not 1 -- masking keeps the low nibble, it
    # does not clamp. Both ends land on 15, so the byte is $FF.
    check(masked == 0xFF, "...and both are masked to 0-15",
          "got $%02X, wanted $FF" % masked)
    key(m, syms, "COLOR 7,0\r")

    print()
    modes(syms)

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
