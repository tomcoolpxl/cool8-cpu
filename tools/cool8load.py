#!/usr/bin/env python3
"""The host end of the hardware loader — docs/07-loader.md.

    python tools/cool8load.py --port COM6 --ping
    python tools/cool8load.py --port COM6 --load game.bin --at 0x4000 --go 0x4000
    python tools/cool8load.py --port COM6 --dump 0x0000 --len 256
    python tools/cool8load.py --port COM6 --halt
    python tools/cool8load.py --port COM6 --write 0xFE03 --bytes 01
    python tools/cool8load.py --port COM6 --run

Three layers, kept apart on purpose:

  `frame` / `parse_*`   the wire format, and nothing else. Pure
                        functions over bytes, so they can be checked
                        against the real RTL without a serial port
                        existing — sim/test_load.py does exactly that.
  `Transport`           bytes in, bytes out. `SerialTransport` is the
                        one that talks to the board.
  `Loader`              the commands, chunking and retry, built on the
                        two above and blind to which transport it has.

That seam is the point. There is no UART and no loader block on the
TinyTapeout part — the equivalent is a microcontroller asserting
`nBUSRQ` and driving the merged bus strobes — and the commands map onto
it one for one, so the same `Loader` drives either target through a
different `Transport`. See docs/07-loader.md section 4.

The serial transport needs pyserial (`pip install pyserial`); it is
imported only when used, so everything else here works without it.
"""

import argparse
import os
import sys
import time

MAGIC = b"\xC8\x8C"

CMD_WRITE = 0x01
CMD_READ = 0x02
CMD_GO = 0x03
CMD_HALT = 0x04
CMD_RUN = 0x05
CMD_RESET = 0x06
CMD_PING = 0x07

ACK = 0x4B          # 'K'
NAK = 0x21          # '!'

# A frame is $C8 $8C cmd addr16 len16 [data] csum, everything
# little-endian, checksum over cmd through the last data byte.
HDR = 5

DEFAULT_BAUD = 115200
DEFAULT_CHUNK = 256


class LoaderError(Exception):
    pass


# ----------------------------------------------------------------- wire

def frame(cmd, addr=0, length=0, data=b""):
    """One frame, ready to put on the wire."""
    body = bytes([cmd, addr & 0xFF, (addr >> 8) & 0xFF,
                  length & 0xFF, (length >> 8) & 0xFF]) + bytes(data)
    return MAGIC + body + bytes([sum(body) & 0xFF])


def corrupt(f):
    """The same frame with a wrong checksum — for testing a NAK path."""
    return f[:-1] + bytes([(f[-1] + 1) & 0xFF])


def reply_len(cmd, length):
    """How many bytes a command answers with.

    Every command replies with exactly one byte except READ, which
    streams its data and then a checksum over it, with no leading 'K'.
    """
    return length + 1 if cmd == CMD_READ else 1


def parse_ack(reply, what="command"):
    if len(reply) != 1:
        raise LoaderError(f"{what}: expected 1 byte back, got {len(reply)}")
    if reply[0] == NAK:
        raise LoaderError(f"{what}: the board rejected it (checksum or "
                          f"unknown command)")
    if reply[0] != ACK:
        raise LoaderError(f"{what}: expected $4B, got ${reply[0]:02X}")
    return True


def parse_read(reply, length):
    """Data bytes out of a READ reply, checking the trailing checksum."""
    if len(reply) != length + 1:
        raise LoaderError(f"read: expected {length + 1} bytes back, "
                          f"got {len(reply)}")
    data, csum = reply[:length], reply[length]
    if sum(data) & 0xFF != csum:
        raise LoaderError(f"read: checksum ${csum:02X} does not match the "
                          f"${sum(data) & 0xFF:02X} of the data")
    return bytes(data)


# ------------------------------------------------------------ transport

class Transport:
    """Bytes in, bytes out. Subclass this to drive something else."""

    def send(self, data):
        raise NotImplementedError

    def recv(self, n, timeout):
        """Up to n bytes, giving up after timeout seconds."""
        raise NotImplementedError

    def flush_input(self):
        """Throw away anything already waiting to be read."""

    def close(self):
        pass


class SerialTransport(Transport):
    def __init__(self, port, baud=DEFAULT_BAUD):
        try:
            import serial
        except ImportError:
            raise LoaderError(
                "the serial transport needs pyserial: pip install pyserial")
        self.port = serial.Serial(port, baud, timeout=0.05)

    def send(self, data):
        self.port.write(data)
        self.port.flush()

    def recv(self, n, timeout):
        end = time.monotonic() + timeout
        out = bytearray()
        while len(out) < n and time.monotonic() < end:
            chunk = self.port.read(n - len(out))
            if chunk:
                out += chunk
        return bytes(out)

    def flush_input(self):
        self.port.reset_input_buffer()

    def close(self):
        self.port.close()


class RecordingTransport(Transport):
    """Keeps everything sent and replays a fixed reply stream.

    What sim/test_load.py drives the RTL with: the session is built
    here, handed to a testbench, and the board's real replies come back
    through the same object.
    """

    def __init__(self, replies=b""):
        self.sent = bytearray()
        self.replies = bytes(replies)
        self.pos = 0

    def send(self, data):
        self.sent += data

    def recv(self, n, timeout):
        out = self.replies[self.pos:self.pos + n]
        self.pos += len(out)
        return out


# --------------------------------------------------------------- loader

class Loader:
    def __init__(self, transport, chunk=DEFAULT_CHUNK, retries=3,
                 timeout=2.0, verbose=False):
        self.t = transport
        self.chunk = chunk
        self.retries = retries
        self.timeout = timeout
        self.verbose = verbose

    def _say(self, msg):
        if self.verbose:
            print("  " + msg)

    def _exchange(self, cmd, addr=0, length=0, data=b""):
        self.t.send(frame(cmd, addr, length, data))
        return self.t.recv(reply_len(cmd, length), self.timeout)

    # -- the commands

    def ping(self):
        """Ask the loader for its version.

        Drops anything already buffered first, since the port may have
        been sitting open while a program talked into it. That is not a
        cure for a *running* talkative program — the byte read back could
        still be the program's rather than the loader's, and nothing in
        the protocol can tell them apart. `HALT` first if that matters.
        """
        self.t.flush_input()
        r = self._exchange(CMD_PING)
        if len(r) != 1:
            raise LoaderError("ping: no answer — wrong port, wrong baud "
                              "rate, or the board is not running")
        return r[0]

    def halt(self):
        parse_ack(self._exchange(CMD_HALT), "halt")

    def run(self):
        parse_ack(self._exchange(CMD_RUN), "run")

    def reset(self):
        parse_ack(self._exchange(CMD_RESET), "reset")

    def go(self, addr):
        parse_ack(self._exchange(CMD_GO, addr), "go")

    def write(self, addr, data, halt_first=True):
        """Write memory, in chunks, retrying a chunk the board rejects.

        HALT first by default. The bus grant lasts one frame, so between
        chunks the CPU runs again — into whatever half of the new
        program has landed so far. docs/07-loader.md section 2.

        A rejected WRITE has already modified memory: the loader has no
        frame buffer and commits bytes as they arrive, so '!' means the
        data was wrong, not that nothing happened. Resending the same
        chunk is the whole recovery, and it is what this does.
        """
        if halt_first:
            self.halt()
        data = bytes(data)
        for off in range(0, len(data), self.chunk):
            piece = data[off:off + self.chunk]
            here = addr + off
            for attempt in range(self.retries):
                try:
                    parse_ack(self._exchange(CMD_WRITE, here, len(piece),
                                             piece),
                              f"write ${here:04X}")
                    break
                except LoaderError as e:
                    self._say(f"retry {attempt + 1}: {e}")
                    if attempt == self.retries - 1:
                        raise
            self._say(f"wrote {len(piece)} bytes at ${here:04X}")

    def read(self, addr, length):
        """Read memory, in chunks, checking each chunk's checksum.

        Chunked for the same reason a write is: a corrupted reply costs
        one chunk rather than the whole dump. Note that the loader
        advances the address between bytes, so this is *not* the way to
        pop a FIFO register repeatedly — see docs/07-loader.md section 2.
        """
        out = bytearray()
        while len(out) < length:
            n = min(self.chunk, length - len(out))
            here = addr + len(out)
            for attempt in range(self.retries):
                try:
                    out += parse_read(self._exchange(CMD_READ, here, n), n)
                    break
                except LoaderError as e:
                    self._say(f"retry {attempt + 1}: {e}")
                    if attempt == self.retries - 1:
                        raise
        return bytes(out)

    def load(self, addr, data, verify=False):
        self.write(addr, data)
        if verify:
            back = self.read(addr, len(data))
            if back != data:
                bad = next(i for i in range(len(data)) if back[i] != data[i])
                raise LoaderError(
                    f"verify failed at ${addr + bad:04X}: wrote "
                    f"${data[bad]:02X}, read back ${back[bad]:02X}")
            self._say(f"verified {len(data)} bytes")


# ------------------------------------------------------------------ cli

def anyint(s):
    return int(s, 0)


def hexbytes(s):
    t = s.replace(",", " ").replace("$", "").replace("0x", "")
    if " " in t.strip():
        return bytes(int(p, 16) for p in t.split())
    t = t.strip()
    if len(t) % 2:
        raise argparse.ArgumentTypeError("--bytes needs whole bytes")
    return bytes.fromhex(t)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Talk to the COOL8 hardware loader.",
        epilog="Actions run in the order listed above, so --load --go "
               "does the right thing in one invocation.")
    ap.add_argument("--port", help="serial port, e.g. COM6 or /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--chunk", type=anyint, default=DEFAULT_CHUNK,
                    help="bytes per WRITE or READ frame")
    ap.add_argument("-v", "--verbose", action="store_true")

    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--halt", action="store_true")
    ap.add_argument("--load", metavar="FILE", help="a flat binary")
    ap.add_argument("--at", type=anyint, help="where --load puts it")
    ap.add_argument("--verify", action="store_true",
                    help="read --load back and compare")
    ap.add_argument("--write", type=anyint, metavar="ADDR")
    ap.add_argument("--bytes", type=hexbytes, help="hex, for --write")
    ap.add_argument("--dump", type=anyint, metavar="ADDR")
    ap.add_argument("--len", type=anyint, default=256, help="for --dump")
    ap.add_argument("--out", metavar="FILE", help="write --dump here")
    ap.add_argument("--go", type=anyint, metavar="ADDR")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args(argv)

    if args.load and args.at is None:
        ap.error("--load needs --at")
    if args.write is not None and not args.bytes:
        ap.error("--write needs --bytes")
    if not args.port:
        ap.error("--port is required")

    try:
        t = SerialTransport(args.port, args.baud)
    except LoaderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    ldr = Loader(t, chunk=args.chunk, timeout=args.timeout,
                 verbose=args.verbose)
    try:
        if args.ping:
            print(f"loader version {ldr.ping()}")
        if args.halt:
            ldr.halt()
            print("halted")
        if args.load:
            with open(args.load, "rb") as fh:
                img = fh.read()
            ldr.load(args.at, img, verify=args.verify)
            print(f"loaded {len(img)} bytes at ${args.at:04X}")
        if args.write is not None:
            ldr.write(args.write, args.bytes)
            print(f"wrote {len(args.bytes)} bytes at ${args.write:04X}")
        if args.dump is not None:
            data = ldr.read(args.dump, args.len)
            if args.out:
                with open(args.out, "wb") as fh:
                    fh.write(data)
                print(f"dumped {len(data)} bytes to {args.out}")
            else:
                hexdump(args.dump, data)
        if args.go is not None:
            ldr.go(args.go)
            print(f"running at ${args.go:04X}")
        if args.run:
            ldr.run()
            print("released")
        if args.reset:
            ldr.reset()
            print("reset")
    except LoaderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        t.close()
    return 0


def hexdump(base, data, width=16):
    for off in range(0, len(data), width):
        row = data[off:off + width]
        hx = " ".join(f"{b:02X}" for b in row).ljust(width * 3 - 1)
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        print(f"{base + off:04X}  {hx}  {txt}")


if __name__ == "__main__":
    sys.exit(main())
