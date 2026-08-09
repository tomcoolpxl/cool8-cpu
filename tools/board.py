#!/usr/bin/env python3
"""The real board, driven from the PC over one serial wire.

    python tools/board.py --port COM6 --screen
    python tools/board.py --port COM6 --peek 0x8000 --len 64
    python tools/board.py --port COM6 --type "10 PRINT 6 * 7" --run
    python tools/board.py --port COM6 --selftest

`tools/cool8vm.py`'s `Machine` is the emulator's API and every software
test drives it. This is the same shape for hardware: type at it, read
its memory, read its screen. Import `Board` and it is a harness;
`sim/test_board.py` is the suite built on it.

## Why this can work with the loader turned off

[D40](../docs/01-decisions.md) parameterised the hardware loader out --
`LOADER` defaults to 0 -- so `tools/cool8load.py` cannot reach the
board, and `tools/cool8screen.py` reads the framebuffer through it and
so cannot either. That looked like "the board cannot be inspected
remotely", and it is not true.

**BASIC reads the UART and `$FE71` writes to it.** So the board can be
told to report on itself: type a small program that pokes bytes at the
transmitter, run it, and read them back. Memory, the screen, a variable,
the result of an expression -- all of it comes back over the same wire
that typed the program. Nothing is added to the machine to make this
work; it is the machine's own facilities pointed at the host.

## What has to be respected

**Pacing.** The UART cannot raise an interrupt (`docs/04-system.md` §6),
so BASIC drains its 16-byte FIFO on the vertical blank -- sixteen bytes
per 60th of a second, and about 400 bytes a second sustained. A host
that streams a line at 115200 sends 192 bytes a frame and loses most of
them. So input is fed in small pieces with a gap, and that is not
conservatism, it is the documented limit.

**The screen is the buffer.** The editor is full-screen: a line is
entered by putting it on a row and pressing Return, and typing over a
row that still holds text leaves the tail behind. `cmd()` goes to the
bottom of the screen first, which is what `sim/test_basic.py` does and
for the same reason.
"""

import argparse
import os
import sys
import time

def _config():
    """The board's settings, out of package.json.

    Not written into this file: package.json is where every other name
    and number this project uses already lives, and a USB id buried in
    a Python constant is one more place to look. `COOL8_BOARD_USB`
    overrides it for a different debugger without editing anything.
    """
    import json
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(os.path.dirname(here), "package.json")
    try:
        with open(path) as fh:
            cfg = json.load(fh).get("cool8", {}).get("board", {})
    except Exception:
        cfg = {}
    usb = os.environ.get("COOL8_BOARD_USB") or cfg.get("usb", "")
    try:
        vid, pid = (int(x, 16) for x in usb.split(":"))
    except Exception:
        vid = pid = None
    return int(cfg.get("baud", 115200)), (vid, pid)


BAUD, ICELINK_USB = _config()

# Sixteen bytes is the FIFO; eight with a gap leaves room for the
# interrupt to have run. Measured on the board, not guessed: a full
# line at once loses characters and a line in eights does not.
CHUNK = 8
GAP = 0.035

SCREEN = 0x8000
COLS, ROWS = 80, 30
UART_STAT, UART_DATA = 0xFE70, 0xFE71


def _pieces(data, chunk=CHUNK):
    """Split into FIFO-sized pieces without ever cutting an ESC sequence.

    A sequence is `ESC` then `[` or `O` then bytes up to a final in
    `@`-`~`, which covers `ESC [ A` and `ESC [ 3 ~` alike.
    """
    out, cur, i = [], bytearray(), 0
    while i < len(data):
        n = 1
        if data[i] == 0x1B and i + 1 < len(data):
            n = 2
            while i + n < len(data) and not 0x40 <= data[i + n] <= 0x7E:
                n += 1
            n = min(n + 1, len(data) - i)
        if cur and len(cur) + n > chunk:
            out.append(bytes(cur))
            cur = bytearray()
        cur += data[i:i + n]
        i += n
    if cur:
        out.append(bytes(cur))
    return out


def find_port(prefer=None):
    """The board's serial port, without being told which one.

    The iCELink debugger presents a CDC port alongside its mass-storage
    drive, and **it re-enumerates whenever the FPGA is reconfigured** --
    so a port number written into a command line is right until the
    first time you reprogram, and then it is not. Ask the system.
    """
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    if prefer:
        for p in ports:
            if p.device.upper() == prefer.upper():
                return p.device
    # By USB ID, not by description. The iCELink enumerates as a plain
    # "USB Serial Device" on Windows with nothing in the name to go on,
    # so matching text finds nothing while the board is sitting right
    # there. The ID is the board's, not this machine's.
    for p in ports:
        if (p.vid, p.pid) == ICELINK_USB:
            return p.device
    for p in ports:
        text = " ".join(str(x) for x in (p.description, p.manufacturer,
                                         p.product, p.hwid)).lower()
        if "icelink" in text or "cmsis" in text:
            return p.device
    # A bare USB CDC with nothing else to go on: still better than a
    # guess, and there is usually only one.
    cdc = [p for p in ports if "USB" in (p.hwid or "")]
    if len(cdc) == 1:
        return cdc[0].device
    sys.exit("cannot tell which port the board is on; pass --port. saw: %s"
             % ", ".join("%s (%s)" % (p.device, p.description)
                         for p in ports) or "nothing")


def wait_for_port(prefer=None, timeout=30.0):
    """Wait for the port to come back after a reconfigure."""
    import serial
    started = time.time()
    while time.time() - started < timeout:
        try:
            dev = find_port(prefer)
            s = serial.Serial(dev, BAUD, timeout=0.2)
            s.close()
            return dev
        except SystemExit:
            pass
        except serial.SerialException:
            pass
        time.sleep(0.5)
    sys.exit("the board's serial port did not come back within %gs" % timeout)


class Board:
    """A COOL8 on the other end of a serial port."""

    def __init__(self, port=None, baud=BAUD, verbose=False):
        try:
            import serial
        except ImportError:
            sys.exit("pyserial is needed: pip install pyserial")
        dev = wait_for_port(port, timeout=10.0)
        self.port = dev
        self.ser = serial.Serial(dev, baud, timeout=0.2)
        self.verbose = verbose

    # ------------------------------------------------------------ input

    def send(self, text):
        """Raw bytes at the machine, paced so the FIFO survives.

        **An escape sequence is never split across the gap.** This is
        not tidiness. `serialkey()` treats an `ESC` with nothing behind
        it as a real Escape -- it has to, or a game's loop would hang on
        the one key it most wants to read -- so a chunk boundary falling
        between `ESC` and `[B` turns a cursor-down into an Escape
        followed by the literal text `[B`, which then lands on the
        screen. The board did exactly that and the emulator never could,
        because there the whole burst is always in the ring before
        anything looks at it.
        """
        data = text.encode("latin-1") if isinstance(text, str) else text
        for piece in _pieces(data):
            self.ser.write(piece)
            self.ser.flush()
            time.sleep(GAP)

    def key(self, name):
        """A named key, as the terminal spells it. `serialkey()` folds
        these into the same K_* the PS/2 decoder produces."""
        seq = {"up": "\x1b[A", "down": "\x1b[B", "right": "\x1b[C",
               "left": "\x1b[D", "home": "\x1b[H", "end": "\x1b[F",
               "ret": "\r", "esc": "\x1b"}[name]
        self.send(seq)

    def cmd(self, line):
        """Enter one line, on a blank row.

        Down 29 then Home, exactly as sim/test_basic.py's `cmd` does:
        the bottom of the screen is blank, and typing over a row that
        still holds text would leave its tail behind.
        """
        # Home is 0,0 and DOWN at the bottom scrolls (the C64 law), so
        # Home first, then exactly to the bottom row.
        self.send("\x1b[H")
        self.send("\x1b[B" * 29)
        self.send(line + "\r")
        # The expensive moment is Return: tokenise, store, scroll --
        # and the input ring is 16 bytes with no overflow check, so
        # typing on while the editor is busy silently eats characters.
        # This pause is what the VM harness's settle() does, priced in
        # wall clock. Diagnosed the hard way: sessions died after any
        # ?BREAK, because its print-and-scroll is exactly such a moment.
        time.sleep(0.25)

    def program(self, lines):
        for ln in lines:
            self.cmd(ln)

    # ----------------------------------------------------------- output

    def drain(self, quiet=0.4, limit=8.0):
        """Everything the board says, until it stops saying it."""
        out, last = bytearray(), time.time()
        started = last
        while time.time() - started < limit:
            n = self.ser.in_waiting
            if n:
                out += self.ser.read(n)
                last = time.time()
            elif time.time() - last > quiet:
                break
            else:
                time.sleep(0.02)
        return bytes(out)

    def run(self, expect=0, limit=20.0):
        """RUN, and collect what the program transmits.

        `expect` is how many bytes the program is going to send; waiting
        for exactly that is the difference between a reliable read and
        one that stops in the middle of a slow dump.
        """
        self.drain(quiet=0.15, limit=1.0)               # clear the line
        self.cmd("RUN")
        out, last = bytearray(), time.time()
        started = last
        while time.time() - started < limit:
            n = self.ser.in_waiting
            if n:
                out += self.ser.read(n)
                last = time.time()
                if expect and len(out) >= expect:
                    break
            elif time.time() - last > 1.0 and (out or not expect):
                break
            else:
                time.sleep(0.02)
        return bytes(out)

    # ------------------------------------------------------- inspection

    def peek(self, addr, length, step=1):
        """`length` bytes of the board's memory, read by the board.

        **Every loop here is bottom-tested on purpose.** `DO WHILE` and
        `DO UNTIL` at the top were broken until the `docond` fix, and a
        board carrying an older BASIC still has that -- so a harness
        written with the top form cannot be used to investigate the very
        board it would fail on. `LOOP WHILE` always worked.

        There is no wait on the transmitter either. The FIFO is sixteen
        bytes and the interpreter emits a few thousand statements a
        second against 11,500 bytes a second on the wire, so it drains
        far faster than this fills it. A status poll would double the
        statements per byte to guard against something that cannot
        happen.
        """
        self.cmd("NEW")
        self.program([
            "10 A = $%04X" % addr,
            "20 DO",
            "30 POKE $%04X, PEEK(A)" % UART_DATA,
            "40 A = A + %d" % step,
            "50 LOOP WHILE A < $%04X" % (addr + length * step),
            "60 END",
        ])
        return self.run(expect=length)

    def screen(self):
        """The text screen, as `Machine.text()` gives it.

        Cells are two bytes -- character then attribute -- so the
        character plane is every other byte from $8000.
        """
        raw = self.peek(SCREEN, COLS * ROWS, step=2)
        rows = []
        for r in range(ROWS):
            row = raw[r * COLS:(r + 1) * COLS]
            rows.append("".join(chr(b) if 32 <= b < 127 else " "
                                for b in row).rstrip())
        return rows

    def shows(self, want):
        return any(r.strip() == want for r in self.screen())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", help="default: found automatically")
    ap.add_argument("--baud", type=int, default=BAUD)
    ap.add_argument("--screen", action="store_true")
    ap.add_argument("--peek", type=lambda s: int(s, 0))
    ap.add_argument("--len", type=int, default=64)
    ap.add_argument("--type", action="append", default=[])
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--ports", action="store_true",
                    help="list the serial ports and stop")
    args = ap.parse_args()

    if args.ports:
        from serial.tools import list_ports
        for p in list_ports.comports():
            print("  %-8s %s" % (p.device, p.description))
        return 0

    b = Board(args.port, args.baud)
    print("  board on %s" % b.port)

    if args.type:
        b.program(args.type)
    if args.run:
        print(b.run().decode("latin-1", "replace"))
    if args.peek is not None:
        data = b.peek(args.peek, args.len)
        for i in range(0, len(data), 16):
            chunk = data[i:i + 16]
            print("%04X  %-48s %s" % (
                args.peek + i, " ".join("%02X" % c for c in chunk),
                "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)))
    if args.screen:
        for i, row in enumerate(b.screen()):
            if row.strip():
                print("%2d | %s" % (i, row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
