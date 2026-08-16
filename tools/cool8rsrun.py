#!/usr/bin/env python3
"""The machine in a window, on the Rust machine — screen, keyboard,
speaker, at full speed with the scanline renderer.

    python tools/cool8rsrun.py            # boot to BASIC off a disk image
    python tools/cool8rsrun.py --monitor  # just the boot ROM
    (or: poe emu)

This is the launcher, not the emulator: it builds the assets the
runner needs — the boot ROM, the font, and a flash image with BASIC on
volume 0 — with the same tools everything else uses, builds cool8rs
with its window and speaker (`--features gui`), and hands over.
tools/cool8run.py remains the Python front end; RUST_PORT.md says what
differs (per-scanline rendering, mostly).
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(ROOT, "sim", "build")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))

EXE = os.path.join(ROOT, "rust", "target", "release",
                   "cool8rs.exe" if os.name == "nt" else "cool8rs")


def basic_image():
    """The disk on the shelf: `build/cool8.img`, whatever is in it.

    **This runs what is there and builds nothing.** `poe disk` builds
    the image and `poe emu` boots it — two commands, because a launcher
    that decides for itself when to rebuild needs a rule about when a
    source counts as newer, and that rule is exactly the thing that
    quietly boots a stale image one day. One disk builder either way:
    `tools/flash.py` makes this image for the board too.
    """
    import flash
    if not os.path.exists(flash.DISK):
        sys.exit("no %s -- run `poe disk` to build it (or pass --flash)"
                 % os.path.relpath(flash.DISK, ROOT))
    return flash.DISK


def version():
    """`1.0.0 (f21d7c0)`, or just the version where git cannot answer."""
    v = "?"
    try:
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("version"):
                    v = line.split("=")[1].strip().strip('"')
                    break
    except OSError:
        pass
    try:
        sha = subprocess.run(["git", "describe", "--always", "--dirty"],
                             cwd=ROOT, capture_output=True, text=True)
        if sha.returncode == 0 and sha.stdout.strip():
            return "%s (%s)" % (v, sha.stdout.strip())
    except OSError:
        pass
    return v


def banner(cmd, code, rom, font):
    """What is about to run, and out of which files.

    **This used to open with "44 branches relaxed in main.asm"** -- the
    assembler's size note, printed by the library build path, which is
    neither what this command is about nor something a person launching
    a machine can act on. What they cannot see and do need is which
    firmware is in the window and which disc it is holding: those come
    from four different places (sw/, the ROM built here, the flash image
    on disk, the catalogue read out of it) and any of them can be from a
    different afternoon than the others.
    """
    import memmap
    import cool8disk as disk

    def arg(k):
        return next((c[len(k) + 2:] for c in cmd if c.startswith("+%s=" % k)),
                    None)

    def rel(q):
        return os.path.relpath(q, ROOT) if q else None

    print("  COOL8 %s -- the Rust machine in a window, SDL2 and a "
          "scanline renderer" % version())
    print("    exe       %s" % rel(EXE))
    print("    firmware  BASIC %s bytes at $%04X, assembled from sw/"
          % (format(len(code), ","), memmap.ORG))
    print("    boot ROM  %s, %s bytes -- uploads %s (%s) into VRAM"
          % (rel(arg("rom")), format(len(rom), ","), rel(arg("font")),
             format(len(font), ",")))

    flash = arg("flash")
    if not flash:
        print("    disc      none: --monitor, so the ROM and no BASIC")
        return
    print("    disc      %s" % rel(flash))
    if not os.path.exists(flash):
        print("              MISSING -- run `poe disk`, or pass --flash")
        return

    # **Volume 0 first, and by hand.** `catalogue` answers what the demo
    # menu needs, which is programs a person can LOAD, so it does not
    # mention BOOT.BIN -- and printing "drive 0 empty" about the volume
    # holding the firmware the ROM is about to jump into is worse than
    # saying nothing. It is the one file on the image that decides what
    # the machine *is*.
    try:
        boot = disk.Volume(disk.Image(flash), disk.BOOT_VOL).files()
        if boot:
            print("              drive %-2d %-6s %s, %s bytes -- what the "
                  "ROM autoboots"
                  % (disk.BOOT_VOL, "SYSTEM", disk.show_name(boot[0]["name"]),
                     format(boot[0]["length"], ",")))
    except Exception:
        pass

    rows = disk.catalogue(flash)
    by = {}
    for drive, label, name in rows:
        by.setdefault((drive, label), []).append(name)
    for (drive, label), names in sorted(by.items()):
        print("              drive %-2d %-6s %s"
              % (drive, label, ", ".join(names)))

    used = {d for d, _ in by} | {disk.BOOT_VOL}
    free = [d for d in range(disk.N_VOLS) if d not in used]
    if free:
        print("              %d more formatted and empty; DRIVE %d is where "
              "a cold machine comes up" % (len(free), disk.USER_VOL))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", action="store_true",
                    help="boot ROM only: no flash image, no BASIC")
    ap.add_argument("--flash", help="boot this flash image instead of "
                                    "build/cool8.img")
    args = ap.parse_args()

    if not shutil.which("cargo"):
        sys.exit("cargo not found: the window needs a Rust toolchain")

    os.makedirs(BUILD, exist_ok=True)
    import cool8rsvm as vm
    import cool8kbd
    rom, font = vm.build_rom()
    rom_p = os.path.join(BUILD, "emu_rom.bin")
    font_p = os.path.join(BUILD, "emu_font.bin")
    with open(rom_p, "wb") as f:
        f.write(rom)
    with open(font_p, "wb") as f:
        f.write(font)

    import test_basic as B
    code, syms = B.build()

    # The machine's own layout for right-click paste, derived from
    # sw/keymap.asm through the machine's tables — never a second copy.
    chars, _ = cool8kbd.kbd_tables()
    km_p = os.path.join(BUILD, "emu_keymap.txt")
    with open(km_p, "w", newline="\n") as f:
        for ch, (sc, shifted) in sorted(chars.items()):
            f.write("%02x %02x %d\n" % (ord(ch), sc, 1 if shifted else 0))

    cmd = [EXE, "+emu", f"+rom={rom_p}", f"+font={font_p}",
           f"+keymap={km_p}"]
    if args.flash:
        cmd.append(f"+flash={os.path.abspath(args.flash)}")
    elif not args.monitor:
        cmd.append(f"+flash={basic_image()}")

    # **The disc catalogue, read here and handed over as a file.** Same
    # arrangement as the keymap above and for the same reason: the
    # emulator is never taught a machine format. `tools/cool8disk.py`
    # owns the directory layout, so a walk written again in Rust would
    # be a second implementation of it and would drift the first time an
    # entry gained a field.
    flash_arg = next((c[7:] for c in cmd if c.startswith("+flash=")), None)
    if flash_arg and os.path.exists(flash_arg):
        import cool8disk as disk
        rows = disk.catalogue(flash_arg)
        cat_p = os.path.join(BUILD, "emu_discs.txt")
        with open(cat_p, "w", newline="\n") as f:
            for drive, label, name in rows:
                f.write("%d\t%s\t%s\n" % (drive, label, name))
        cmd.append(f"+discs={cat_p}")

    # **The idle symbols, so the window can wait on the machine.** The
    # play button restarts and then types, and it must not type into a
    # machine that is still uploading fonts. `Machine::is_idle` is the
    # same predicate `settle` uses for the suites; these are the three
    # addresses it asks about, derived from the image being run rather
    # than written down anywhere.
    try:
        # **The symbols come from a fresh build; the machine runs the
        # BOOT.BIN already on the image.** Those are two different
        # firmwares the moment anything in sw/ changes, and the image is
        # top-aligned, so a sixteen-byte change moves every symbol.
        # `+idle` then names a PC this machine never sits at, `is_idle`
        # is never true, and the play button waits forever for a machine
        # that booted seconds ago -- which reads as "the demos do not
        # work" and is nothing of the kind. Silent, and the second time
        # this shape has cost a session (flash.py's own comment is about
        # the first). Compared by length: a firmware change moves it, and
        # reading the file back through the volume to compare bytes is
        # more machinery than the question needs.
        stale = None
        if flash_arg and os.path.exists(flash_arg):
            import cool8disk as disk
            import mkboot
            import memmap
            fresh = len(mkboot.build(code, dest=memmap.ORG, build_dir=BUILD))
            got = disk.Volume(disk.Image(flash_arg), disk.BOOT_VOL).files()
            have = got[0]["length"] if got else 0
            if have != fresh:
                stale = (have, fresh)

        if stale:
            print("  **%s carries different firmware than sw/ builds now**"
                  % os.path.basename(flash_arg))
            print("     on the image %s bytes, built here %s bytes"
                  % (format(stale[0], ","), format(stale[1], ",")))
            print("     the machine will boot and can be typed at, but the")
            print("     play button cannot: its idle test would name a")
            print("     symbol from the wrong build. Rebuild the disc:")
            print("       python -m poethepoet demos")
        else:
            cmd.append("+idle=%d,%d,%d" % (syms["in_raw.rk0"],
                                           syms["irhead"], syms["irtail"]))
    except Exception as e:                  # a monitor-only run has none
        print("  no idle symbols (%s); the demo menu will not launch" % e)

    env = dict(os.environ)
    # SDL2's cmake_minimum_required predates what cmake 4 will still
    # speak to; this is cmake's own documented floor for exactly that.
    env.setdefault("CMAKE_POLICY_VERSION_MINIMUM", "3.5")
    # **Say that it is building.** `--features gui` drags in SDL2, and
    # SDL2 is vendored, so coming from the default (parity) build this
    # compiles C for minutes with `capture_output` swallowing every line
    # cargo prints. A silent terminal for that long is indistinguishable
    # from a hang, and it got reported as "the emulator window does not
    # appear" -- which sends you looking at SDL, at the window manager,
    # at the flash image, at anything but a compile that had not
    # finished. The build stays captured (its output is noise when it
    # succeeds); only the fact of it is announced.
    banner(cmd, code, rom, font)
    print("  building cool8rs --features gui "
          "(SDL2 is vendored; first build after a plain one takes "
          "longer)...", flush=True)
    r = subprocess.run(["cargo", "build", "--release", "--features", "gui"],
                       cwd=os.path.join(ROOT, "rust"),
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        return 1

    print("  window up: %s" % os.path.basename(EXE), flush=True)
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
