#!/usr/bin/env python3
"""The machine's text screen, in a terminal on the PC.

    python tools/cool8screen.py --port COM6 --demo
    python tools/cool8screen.py --port COM6

**This needs a `LOADER(1)` bitstream.** It reads the framebuffer
through the hardware loader, and `LOADER` defaults to 0 (D40), so on a
shipping board it reaches nothing at all. `tools/board.py --screen`
is the reader for that board: it asks BASIC to POKE the framebuffer at
the UART, which needs no loader.

**The framebuffer is just RAM**, and a bus grant is architecturally
invisible, so the loader can read the screen out from under a running
program without it noticing. That means a screen exists before the video
engine does: this reads the 4800 bytes of mode 0 over the serial port and
draws them, so software can be written and watched with no VGA hardware
at all — see docs/04-system.md section 5.2 for the cell format.

It is not a substitute for the video engine and it does not pretend to
be. It is the same memory the video engine will read, decoded the same
way, which makes it the thing that has to agree with the hardware when
the hardware arrives.

    --base 0x80   the framebuffer's high byte, as VID_BASE holds it
    --demo        fill the screen with a pattern first, to prove the path
    --once        one frame and exit, instead of refreshing

At 115200 a full 80x30 screen is 4800 bytes, about 0.42 s, so this
refreshes at roughly two frames a second. The UART divider is a register
(`$FE72`), so a faster rate scales that directly if the CDC bridge and
the host agree on one.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cool8load as L                           # noqa: E402

COLS, ROWS = 80, 30

# The 16 palette entries as the boot ROM will set them: the usual
# CGA-ish order, so a `07` attribute is grey on black and looks like a
# console rather than like a bug.
PALETTE = [
    (0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170),
    (170, 0, 0), (170, 0, 170), (170, 85, 0), (170, 170, 170),
    (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255),
    (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255),
]


def cell_char(code):
    """Code page 437-ish, minus the parts a terminal will fight over."""
    if code == 0:
        return " "
    if 32 <= code < 127:
        return chr(code)
    return "·"                              # a dot for anything else


def render(cells, colour=True):
    out = []
    for row in range(ROWS):
        line = []
        last = None
        for col in range(COLS):
            ch, attr = cells[row * COLS + col]
            fg, bg = attr & 0x0F, (attr >> 4) & 0x0F
            if colour and (fg, bg) != last:
                fr, fgg, fb = PALETTE[fg]
                br, bgg, bb = PALETTE[bg]
                line.append(f"\033[38;2;{fr};{fgg};{fb}m"
                            f"\033[48;2;{br};{bgg};{bb}m")
                last = (fg, bg)
            line.append(cell_char(ch))
        line.append("\033[0m" if colour else "")
        out.append("".join(line))
    return "\n".join(out)


def read_screen(ldr, base):
    raw = ldr.read(base, COLS * ROWS * 2)
    return [(raw[i], raw[i + 1]) for i in range(0, len(raw), 2)]


def demo_image():
    """Something recognisable, so a blank screen means blank and not broken."""
    cells = [(0, 0x07)] * (COLS * ROWS)
    cells = list(cells)

    def put(row, col, text, attr):
        for k, c in enumerate(text):
            if col + k < COLS:
                cells[row * COLS + col + k] = (ord(c), attr)

    put(1, 2, "COOL8", 0x0F)
    put(1, 8, "text mode 0, 80 x 30, read over the serial port", 0x07)
    put(3, 2, "The framebuffer is RAM. The video engine is not here yet.", 0x0B)
    put(4, 2, "This is the same memory it will read, decoded the same way.",
        0x0B)
    for i in range(16):
        put(6 + i // 8, 2 + (i % 8) * 9, f" attr {i:X}  ", (i << 4) | 0x0F)
    put(9, 2, "-" * 60, 0x08)
    for row in range(11, ROWS - 1):
        put(row, 2, "".join(chr(33 + ((row * 7 + c) % 94)) for c in range(60)),
            0x02 + (row % 6))
    return cells


def flatten(cells):
    out = bytearray()
    for ch, attr in cells:
        out += bytes((ch, attr))
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=L.DEFAULT_BAUD)
    ap.add_argument("--base", type=lambda s: int(s, 0), default=0x80,
                    help="framebuffer high byte, as VID_BASE holds it")
    ap.add_argument("--demo", action="store_true",
                    help="write a pattern into the framebuffer first")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-colour", action="store_true")
    args = ap.parse_args()

    base = args.base << 8
    t = L.SerialTransport(args.port, args.baud)
    ldr = L.Loader(t, chunk=256)
    try:
        if args.demo:
            # Emphatically without halting. A bus grant is invisible, so
            # a screen can be written and read under a running program —
            # and freezing the CPU to look at its output would defeat the
            # only reason this tool exists. `Loader.write` halts by
            # default because loading a *program* over a running one has
            # to; painting a framebuffer does not.
            ldr.write(base, flatten(demo_image()), halt_first=False)
            print(f"wrote a {COLS}x{ROWS} screen at ${base:04X}")

        os.system("")                            # let Windows do ANSI
        while True:
            frame = render(read_screen(ldr, base), colour=not args.no_colour)
            sys.stdout.write("\033[H\033[2J" + frame + "\n")
            sys.stdout.flush()
            if args.once:
                break
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    except L.LoaderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        t.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
