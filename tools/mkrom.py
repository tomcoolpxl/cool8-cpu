#!/usr/bin/env python3
"""Assemble the boot ROM into an image `$readmemh` can load.

    python tools/mkrom.py sw/boot.asm -o sim/build/boot.hex

The ROM is 4096 bytes covering $F000-$FFFF and the output is 4096 lines
of two hex digits, one per byte, which is what `cool8_rom.v` reads and
what yosys bakes into EBR.

Two things this checks that the assembler cannot, because they are facts
about the memory map rather than about the source:

  - **Nothing may live at $FE00-$FEFF.** That is the I/O page, it always
    wins the decode, and those 256 bytes of the ROM image can never be
    read back. Code there is silently unreachable — which is exactly the
    kind of fault that survives a bring-up and surfaces months later.
  - **Nothing may live below $F000.** The ROM window starts there. An
    `.org` that reaches lower is a mistake, not a relocation.

The image is generated, not committed: it is derived from sw/boot.asm and
the assembler, and a stale checked-in copy would be a boot ROM that does
not match its own source.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cool8asm                                # noqa: E402
import ioregs                                  # noqa: E402

ROM_BASE = 0xF000
ROM_SIZE = 0x1000

# The hole the I/O page punches in the ROM image, from the one place the
# page is described. It used to be a literal $FE00 here, which would
# have gone on masking the wrong 256 bytes after the page moved -- and
# the check below would then have passed a ROM whose real hole was full
# of code (D67).
IO_BASE = ioregs.IO_BASE
IO_SIZE = ioregs.IO_TOP - ioregs.IO_BASE + 1


def build(source):
    """Return the 4096-byte ROM image, or exit with a diagnosis."""
    try:
        a = cool8asm.assemble(source)
    except cool8asm.AsmError as e:
        sys.exit(f"error: {e}")
    for e in a.errors:
        print(f"error: {e}", file=sys.stderr)
    if a.errors:
        sys.exit(1)

    base, img = a.image()
    end = base + len(img)

    if base < ROM_BASE:
        sys.exit(f"error: the image starts at ${base:04X}, below the ROM "
                 f"window at ${ROM_BASE:04X}")
    if end > ROM_BASE + ROM_SIZE:
        sys.exit(f"error: the image ends at ${end - 1:04X}, above the ROM "
                 f"window at ${ROM_BASE + ROM_SIZE - 1:04X}")

    rom = bytearray(ROM_SIZE)
    rom[base - ROM_BASE:end - ROM_BASE] = img

    hole = rom[IO_BASE - ROM_BASE:IO_BASE - ROM_BASE + IO_SIZE]
    if any(hole):
        first = next(i for i, b in enumerate(hole) if b)
        sys.exit(f"error: ${IO_BASE + first:04X} is in the I/O page, which "
                 f"always wins the decode. Nothing in the ROM image from "
                 f"${IO_BASE:04X} to ${IO_BASE + IO_SIZE - 1:04X} can ever "
                 f"be read.")

    return base, img, rom


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?",
                    default=os.path.join(os.path.dirname(HERE), "sw",
                                         "boot.asm"))
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--bin", help="also write a flat binary")
    args = ap.parse_args()

    base, img, rom = build(args.source)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as fh:
        for b in rom:
            fh.write("%02x\n" % b)
    if args.bin:
        with open(args.bin, "wb") as fh:
            fh.write(rom)

    used = sum(1 for b in rom if b)
    print(f"{os.path.basename(args.source)}: {len(img)} bytes at "
          f"${base:04X}-${base + len(img) - 1:04X}, "
          f"{used} non-zero of {ROM_SIZE} -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
