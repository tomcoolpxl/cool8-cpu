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

    # The machine's own layout for right-click paste, derived from
    # sw/keymap.asm through the machine's tables — never a second copy.
    chars, _ = cool8kbd.kbd_tables()
    km_p = os.path.join(BUILD, "emu_keymap.txt")
    with open(km_p, "w", newline="\n") as f:
        for ch, (code, shifted) in sorted(chars.items()):
            f.write("%02x %02x %d\n" % (ord(ch), code, 1 if shifted else 0))

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

    env = dict(os.environ)
    # SDL2's cmake_minimum_required predates what cmake 4 will still
    # speak to; this is cmake's own documented floor for exactly that.
    env.setdefault("CMAKE_POLICY_VERSION_MINIMUM", "3.5")
    r = subprocess.run(["cargo", "build", "--release", "--features", "gui"],
                       cwd=os.path.join(ROOT, "rust"),
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        return 1

    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
