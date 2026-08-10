#!/usr/bin/env python3
"""The machine in a window, on the Rust machine — screen, keyboard,
speaker, at full speed with the scanline renderer.

    python tools/cool8rsrun.py            # boot to BASIC off a disk image
    python tools/cool8rsrun.py --monitor  # just the boot ROM
    (or: npm run emu:rust)

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", action="store_true",
                    help="boot ROM only: no flash image, no BASIC")
    ap.add_argument("--flash", help="use this flash image instead of "
                                    "building one with BASIC on it")
    args = ap.parse_args()

    if not shutil.which("cargo"):
        sys.exit("cargo not found: the window needs a Rust toolchain")

    os.makedirs(BUILD, exist_ok=True)
    import cool8vm as vm
    rom, font = vm.build_rom()
    rom_p = os.path.join(BUILD, "emu_rom.bin")
    font_p = os.path.join(BUILD, "emu_font.bin")
    with open(rom_p, "wb") as f:
        f.write(rom)
    with open(font_p, "wb") as f:
        f.write(font)

    # The machine's own layout for right-click paste, derived from
    # sw/keymap.asm through the machine's tables — never a second copy.
    chars, _ = vm._kbd_tables()
    km_p = os.path.join(BUILD, "emu_keymap.txt")
    with open(km_p, "w", newline="\n") as f:
        for ch, (code, shifted) in sorted(chars.items()):
            f.write("%02x %02x %d\n" % (ord(ch), code, 1 if shifted else 0))

    cmd = [EXE, "+emu", f"+rom={rom_p}", f"+font={font_p}",
           f"+keymap={km_p}"]
    if args.flash:
        cmd.append(f"+flash={os.path.abspath(args.flash)}")
    elif not args.monitor:
        import rustsim
        cmd.append(f"+flash={rustsim._basic_image()}")

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
