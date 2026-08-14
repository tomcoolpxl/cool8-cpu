#!/usr/bin/env python3
"""The default palette, and the only place its colours are written down.

    python tools/palette.py            # (re)write the generated copies
    python tools/palette.py --check    # report drift, write nothing
    python tools/palette.py --show     # print the sixteen banks

## Why this exists

The palette block RAM comes up zeroed from the bitstream -- 256 entries
of black, **including entry 0, which is the border** -- so a machine
that never writes it shows nothing at all. Until [D77] three different
pieces of software wrote one: the boot ROM's sixteen, the flash stub's
thirty-two, and `sw/console.asm`'s one-entry override for mode 3. Three
copies of "what colour is blue", and the machine was black for the
milliseconds between reset and whichever of them ran.

Now the bitstream carries it. `cool8_pal.v` reads `pal.hex` at
elaboration exactly as `cool8_rom.v` reads `boot.hex`, and the EBR is
allocated either way -- only its INIT bits change. **Measured at 76
logic cells cheaper**, reproducibly, at 98 % occupancy where that
matters. `pal.hex` is staged into the run directory by `stage()` below
and is not committed, for the same reason `font.hex` and `boot.hex` are
not: it is derived.

The emulator has to agree or the two models draw different colours, and
every suite that compares them would still pass because they would be
consistent with each other -- the failure [D74] is about. So this emits
`rust/src/pal.rs` too, and `poe check` fails on drift in either.

## 256 entries is sixteen palettes, not one

A tile attribute's low nibble selects a **bank of sixteen** ([D79]), so
the table is sixteen palettes and a bank is the unit worth designing.
Modes 0, 1, 4 and 5 read bank 0; mode 3 reaches only entries 0 and 1;
mode 6 is the only one that sees all 256 at once.

**Bank 0's slot meanings are load-bearing and the rest are free.** A
text cell's attribute is `bg[7:4] fg[3:0]`, so entry 4 of bank 0 must be
the red a program means when it writes 4. Nothing indexes banks 1-15 by
meaning -- a tile or sprite points at a bank and uses whatever is in it
-- so those are chosen for how they look together.

## Where the colours came from

Every bank below is a **published palette**, recorded here with its
author and quantised by one function rather than by hand. The 24-bit
values are the originals; `q444` is the only place a colour is
converted, so "what did we change" has one answer: nothing but the
depth. Fetched from lospec.com rather than recalled -- AAP-16 and
Arne 16 both came back different from memory, which is the reason the
rule about not filling things in from memory exists.

## The format

Twelve bits, `RRRRGGGGBBBB`. The hardware takes an entry as two writes
of `PAL_DATA` -- `0000RRRR` then `GGGGBBBB` -- but that is the port's
shape, not the colour's.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RS = os.path.join(ROOT, "rust", "src", "pal.rs")

LOSPEC = "https://lospec.com/palette-list/%s"

# ---------------------------------------------------------------------
# The sixteen banks: (name, author, source, sixteen 24-bit colours).
#
# Bank 0 is the machine's own and every other is somebody's published
# work. Two of them ship fifteen colours because the hardware they came
# from had fifteen -- the Spectrum's bright black *is* black, and the
# TMS9918's sixteenth entry is transparent -- so black leads both and
# the note says so rather than a silent pad.
# ---------------------------------------------------------------------
BANKS = [
    ("Softened CGA", "COOL8", "the boot ROM's, values eased",
     # CGA's sixteen with the hard 0/A/5/F levels softened. **The slots
     # keep their CGA meanings** because a text attribute names them:
     # 1 blue, 2 green, 4 red, 7 light grey, 15 white.
     ["000000", "1122BB", "11AA44", "22AABB", "BB3322", "AA33AA",
      "BB7722", "BBBBCC", "555566", "5599FF", "66EE77", "77EEEE",
      "FF6666", "EE77EE", "FFDD55", "FFFFFF"]),

    ("PICO-8", "Lexaloffle", LOSPEC % "pico-8",
     ["000000", "1D2B53", "7E2553", "008751", "AB5236", "5F574F",
      "C2C3C7", "FFF1E8", "FF004D", "FFA300", "FFEC27", "00E436",
      "29ADFF", "83769C", "FF77A8", "FFCCAA"]),

    ("DawnBringer 16", "DawnBringer", LOSPEC % "dawnbringer-16",
     ["140C1C", "442434", "30346D", "4E4A4E", "854C30", "346524",
      "D04648", "757161", "597DCE", "D27D2C", "8595A1", "6DAA2C",
      "D2AA99", "6DC2CA", "DAD45E", "DEEED6"]),

    ("Sweetie 16", "GrafxKid", LOSPEC % "sweetie-16",
     ["1A1C2C", "5D275D", "B13E53", "EF7D57", "FFCD75", "A7F070",
      "38B764", "257179", "29366F", "3B5DC9", "41A6F6", "73EFF7",
      "F4F4F4", "94B0C2", "566C86", "333C57"]),

    ("Endesga 16", "Endesga", LOSPEC % "endesga-16",
     ["E4A672", "B86F50", "743F39", "3F2832", "9E2835", "E53B44",
      "FB922B", "FFE762", "63C64D", "327345", "193D3F", "4F6781",
      "AFBFD2", "FFFFFF", "2CE8F4", "0484D1"]),

    ("AAP-16", "Adigun A. Polack", LOSPEC % "aap-16",
     ["070708", "332222", "774433", "CC8855", "993311", "DD7711",
      "FFDD55", "FFFF33", "55AA44", "115522", "44EEBB", "3388DD",
      "5544AA", "555577", "AABBBB", "FFFFFF"]),

    ("Arne 16", "Arne Niklas Jansson", LOSPEC % "arne-16",
     ["000000", "493C2B", "BE2633", "E06F8B", "9D9D9D", "A46422",
      "EB8931", "F7E26B", "FFFFFF", "1B2632", "2F484E", "44891A",
      "A3CE27", "005784", "31A2F2", "B2DCEF"]),

    ("Steam Lords", "Slynyrd", LOSPEC % "steam-lords",
     ["213B25", "3A604A", "4F7754", "A19F7C", "77744F", "775C4F",
      "603B3A", "3B2137", "170E19", "2F213B", "433A60", "4F5277",
      "65738C", "7C94A1", "A0B9BA", "C0D1CC"]),

    ("Island Joy 16", "Kerrie Lake", LOSPEC % "island-joy-16",
     ["FFFFFF", "6DF7C1", "11ADC1", "606C81", "393457", "1E8875",
      "5BB361", "A1E55A", "F7E476", "F99252", "CB4D68", "6A3771",
      "C92464", "F48CB6", "F7B69E", "9B9C82"]),

    ("Bubblegum 16", "PineappleOnPizza", LOSPEC % "bubblegum-16",
     ["16171A", "7F0622", "D62411", "FF8426", "FFD100", "FAFDFF",
      "FF80A4", "FF2674", "94216A", "430067", "234975", "68AED4",
      "BFFF3C", "10D275", "007899", "002859"]),

    # **In the C64's own index order, not lospec's.** lospec sorts its
    # list by tone, so its entry 6 is a brown and its 14 a dark blue --
    # correct colours, useless indices. On a C64 colour 6 *is* blue and
    # 14 *is* light blue, and a program that says 6 means blue. A palette
    # named after a machine has to answer to that machine's numbers or it
    # is only a swatch. Values from c64-wiki, the VICE/CCS64 set.
    ("Commodore 64", "Commodore", "https://www.c64-wiki.com/wiki/Color",
     ["000000", "FFFFFF", "880000", "AAFFEE", "CC44CC", "00CC55",
      "0000AA", "EEEE77", "DD8855", "664400", "FF7777", "333333",
      "777777", "AAFF66", "0088FF", "BBBBBB"]),

    ("NA16", "Nauris", LOSPEC % "na16",
     ["8C8FAE", "584563", "3E2137", "9A6348", "D79B7D", "F5EDBA",
      "C0C741", "647D34", "E4943A", "9D303B", "D26471", "70377F",
      "7EC4C1", "34859D", "17434B", "1F0E1C"]),

    ("ZX Spectrum", "Sinclair", LOSPEC % "zx-spectrum",
     # Fifteen colours: the Spectrum's BRIGHT black is black, so black
     # leads and the published fifteen follow.
     ["000000", "000000", "0000D8", "0000FF", "D80000", "FF0000",
      "D800D8", "FF00FF", "00D800", "00FF00", "00D8D8", "00FFFF",
      "D8D800", "FFFF00", "D8D8D8", "FFFFFF"]),

    ("MSX", "Texas Instruments", LOSPEC % "msx",
     # The TMS9918's first entry is *transparent*, which on a screen
     # with nothing behind it is black. Fifteen visible colours follow.
     ["000000", "000000", "CACACA", "FFFFFF", "B75E51", "D96459",
      "FE877C", "CAC15E", "DDCE85", "3CA042", "40B64A", "73CE7C",
      "5955DF", "7E75F0", "64DAEE", "B565B3"]),

    ("CGA", "IBM", "the hard 0/A/5/F levels bank 0 softens",
     ["000000", "0000AA", "00AA00", "00AAAA", "AA0000", "AA00AA",
      "AA5500", "AAAAAA", "555555", "5555FF", "55FF55", "55FFFF",
      "FF5555", "FF55FF", "FFFF55", "FFFFFF"]),

    ("Greyscale", "COOL8", "a linear ramp, for dithering and masks",
     ["%02X%02X%02X" % (n * 17, n * 17, n * 17) for n in range(16)]),
]


def q444(rgb24):
    """One 24-bit colour to twelve bits, rounded rather than truncated.

    **The only place a colour changes.** `v >> 4` throws away the low
    nibble and darkens everything by up to 6 %; rounding to nearest
    keeps white white and grey grey, and makes a bank authored *as*
    twelve bits round-trip exactly -- which is why bank 0 comes through
    unchanged from what the flash stub used to write.
    """
    v = int(rgb24, 16)
    out = 0
    for sh in (16, 8, 0):
        c = (v >> sh) & 0xFF
        out = (out << 4) | ((c * 15 + 127) // 255)
    return out


def table():
    """All 256 entries: sixteen banks of sixteen, in order."""
    out = []
    for name, _, _, cols in BANKS:
        assert len(cols) == 16, "%s is not sixteen colours" % name
        out += [q444(c) for c in cols]
    assert len(out) == 256
    return out


def hex_text():
    return "".join("%03x\n" % e for e in table())


def rs_text():
    t = table()
    rows = []
    for i in range(0, 256, 8):
        rows.append("    " + " ".join("0x%03X," % e for e in t[i:i + 8]))
    banks = "".join("//   %2d  %s\n" % (i, b[0]) for i, b in enumerate(BANKS))
    return (
        "// pal.rs -- GENERATED by tools/palette.py. Do not edit.\n"
        "//\n"
        "// The same 256 entries the bitstream carries, because the\n"
        "// emulator's display and the hardware's must agree: two models\n"
        "// gated against each other catch a disagreement and cannot\n"
        "// catch a shared assumption ([D74]). `poe check` fails on drift.\n"
        "//\n"
        "// Sixteen banks of sixteen ([D79]):\n"
        + banks +
        "\n"
        "pub const DEFAULT: [u16; 256] = [\n" + "\n".join(rows) + "\n];\n")


def stage(build_dir):
    """Write `pal.hex` where yosys or vvp will resolve it.

    **Not committed, and not in rtl/.** `cool8_pal.v` reads it at
    elaboration from the working directory, exactly as `cool8_rom.v`
    reads `boot.hex` and the pixel stage reads `font.hex` -- so like
    those two it is built into the run directory by whoever is about to
    elaborate. Written here rather than by each of them so the colours
    live in one file.
    """
    with open(os.path.join(build_dir, "pal.hex"), "w", newline=chr(10)) as fh:
        fh.write(hex_text())


def show():
    for i, (name, author, src, cols) in enumerate(BANKS):
        who = (" -- %s" % author) if author else ""
        print("  bank %2d  %-16s%s" % (i, name, who))
        print("           %s" % " ".join("%03x" % q444(c) for c in cols))
        print("           %s" % src)


def main():
    if "--show" in sys.argv:
        show()
        return 0
    want = {RS: rs_text()}
    if "--check" in sys.argv:
        bad = []
        for path, text in want.items():
            got = ""
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    got = fh.read()
            if got != text:
                bad.append("%s is stale -- run python tools/palette.py"
                           % os.path.relpath(path, ROOT))
        for b in bad:
            print("  DRIFT:", b)
        if not bad:
            print("  the palette agrees: %d entries, %d banks of sixteen"
                  % (len(table()), len(BANKS)))
        return 1 if bad else 0
    for path, text in want.items():
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("  wrote", os.path.relpath(path, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
