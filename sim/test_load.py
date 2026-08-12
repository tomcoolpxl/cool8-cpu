#!/usr/bin/env python3
"""The host loader, against the machine and against itself.

Two halves, because the tool has two kinds of thing in it:

  1. **The wire format, against the real RTL.** A session is built with
     `cool8load.frame`, bit-banged into `cool8_soc` by
     `sim/tb/cool8_wire_tb.v`, and the board's replies are parsed back
     with `cool8load.parse_*`. Nothing in between is modelled. This is
     where byte order, checksum span and reply length get to be wrong,
     and it is the half that means a board plugged in for the first time
     has only the physical wire left untested.

  2. **The command loops, against a fake board.** Chunking, retry and
     verify are pure Python and do not need a simulator; what they need
     is a board that misbehaves on demand, which `FakeBoard` is and no
     testbench conveniently is.

    python sim/test_load.py

Set OSS_CAD_SUITE to the toolchain root if the tools are not on PATH.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import toolchain as T                                    # noqa: E402
import cool8asm                                 # noqa: E402
import cool8load as L                           # noqa: E402
import ioregs                                   # noqa: E402

SOC = [os.path.join(ROOT, "rtl", "soc", f)
       for f in ("cool8_rom.v", "cool8_spram.v", "cool8_mem.v",
                 "cool8_uart.v", "cool8_loader.v", "cool8_vga.v",
                 "cool8_vregs.v", "cool8_pal.v", "cool8_fetch.v",
                 "cool8_pixel.v", "cool8_vram.v", "cool8_vport.v",
                 "cool8_pll.v", "cool8_pixport.v", "cool8_sprite.v",
                 "cool8_ps2.v", "cool8_flash.v", "cool8_snd.v",
                 "cool8_video.v", "cool8_soc.v",
                 "cool8_top.v")]
CORE = T.CORE
TB = os.path.join(HERE, "tb", "cool8_wire_tb.v")

PROG_AT = 0x0400

failures = []


def chk(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, expected {want!r}")
        print(f"    FAIL {name}: got {got!r}, expected {want!r}")
    return got == want


def chk_raises(name, fn):
    try:
        fn()
    except L.LoaderError:
        return True
    failures.append(f"{name}: expected a LoaderError, got none")
    print(f"    FAIL {name}: expected a LoaderError, got none")
    return False


# ============================================================ the wire

def session():
    """The frames to send, and what each one must answer.

    Each entry is (label, cmd, length, frame_bytes, check) where `check`
    takes the reply bytes for that frame.
    """
    a = cool8asm.assemble(os.path.join(HERE, "asm", "soc_led.asm"))
    base, prog = a.image()
    assert base == PROG_AT
    wrecked = bytes((b ^ 0xFF) for b in prog)

    e = []

    def add(label, cmd, addr=0, length=0, data=b"", frm=None, check=None):
        e.append((label, cmd, length,
                  frm if frm is not None else L.frame(cmd, addr, length, data),
                  check))

    add("PING", L.CMD_PING,
        check=lambda r: chk("PING replies with the version", r, b"\x01"))
    add("HALT", L.CMD_HALT,
        check=lambda r: chk("HALT is accepted", r, bytes([L.ACK])))

    add("WRITE the program", L.CMD_WRITE, PROG_AT, len(prog), prog,
        check=lambda r: chk("WRITE is accepted", r, bytes([L.ACK])))
    add("READ it back", L.CMD_READ, PROG_AT, len(prog),
        check=lambda r: chk("what came back is what went in",
                            L.parse_read(r, len(prog)), prog))

    # A WRITE whose checksum is wrong is rejected — *after* the payload
    # has already gone into memory, because the loader has no frame
    # buffer and commits bytes as they arrive. docs/07-loader.md says so
    # and this is what pins it: '!' means the data was wrong, not that
    # nothing happened.
    add("WRITE with a broken checksum", L.CMD_WRITE, PROG_AT, len(prog),
        wrecked, frm=L.corrupt(L.frame(L.CMD_WRITE, PROG_AT, len(prog),
                                       wrecked)),
        check=lambda r: chk("a bad checksum is rejected", r, bytes([L.NAK])))
    add("READ after the rejection", L.CMD_READ, PROG_AT, len(prog),
        check=lambda r: chk("the rejected payload landed anyway",
                            L.parse_read(r, len(prog)), wrecked))

    add("WRITE again to recover", L.CMD_WRITE, PROG_AT, len(prog), prog,
        check=lambda r: chk("resending is the recovery", r, bytes([L.ACK])))
    add("READ after recovery", L.CMD_READ, PROG_AT, len(prog),
        check=lambda r: chk("memory is right again",
                            L.parse_read(r, len(prog)), prog))

    add("READ SYSCTRL", L.CMD_READ, ioregs.addr_of("SYS_CTRL"), 1,
        check=lambda r: chk("the I/O page answers a READ",
                            L.parse_read(r, 1), b"\x01"))

    add("GO", L.CMD_GO, PROG_AT,
        check=lambda r: chk("GO is accepted", r, bytes([L.ACK])))
    add("READ the LED", L.CMD_READ, ioregs.addr_of("LED"), 1,
        check=lambda r: chk("the loaded program ran and lit the LED",
                            L.parse_read(r, 1), b"\x06"))

    add("RESET", L.CMD_RESET,
        check=lambda r: chk("RESET is accepted", r, bytes([L.ACK])))
    add("PING after reset", L.CMD_PING,
        check=lambda r: chk("still answering", r, b"\x01"))
    return e


def run_wire(entries):
    """Play the session at the machine and bring back everything it said.

    The script alternates frames with waits, because the loader ignores
    its receiver from the moment it asks for the bus until it has
    finished answering — a frame sent on top of the previous reply is
    dropped without a trace. docs/07-loader.md section 3.
    """
    src = os.path.join(BUILD, "session.hex")
    dst = os.path.join(BUILD, "replies.hex")
    with open(src, "w") as fh:
        for _, cmd, length, frm, _ in entries:
            for b in frm:
                fh.write("0%02x\n" % b)
            fh.write("1%02x\n" % L.reply_len(cmd, length))
        fh.write("xxx\n")
    if os.path.exists(dst):
        os.remove(dst)

    vvp = T.build("cool8_wire_tb", TB, SOC + CORE + [T.cells()],
                       gen="2012")
    r = subprocess.run([T.tool("vvp"), vvp,
                        "+in=session.hex", "+out=replies.hex"],
                       cwd=BUILD, capture_output=True, text=True)
    if "\nPASS" not in r.stdout:
        print(r.stdout + r.stderr)
        sys.exit("the wire testbench did not finish")
    with open(dst) as fh:
        return bytes(int(line, 16) for line in fh if line.strip())


def wire_test():
    e = session()
    blob = b"".join(f for (_, _, _, f, _) in e)
    print(f"  a {len(e)}-frame session, {len(blob)} bytes on the wire")

    replies = run_wire(e)

    pos = 0
    for label, cmd, length, _, check in e:
        n = L.reply_len(cmd, length)
        got = replies[pos:pos + n]
        if len(got) != n:
            failures.append(f"{label}: expected {n} reply bytes, "
                            f"{len(got)} left in the stream")
            print(f"    FAIL {label}: expected {n} reply bytes, "
                  f"{len(got)} left in the stream")
            return
        pos += n
        try:
            check(got)
        except L.LoaderError as ex:
            failures.append(f"{label}: {ex}")
            print(f"    FAIL {label}: {ex}")

    chk("the board said nothing extra", replies[pos:], b"")


# ======================================================= the fake board

class FakeBoard(L.Transport):
    """Enough of the loader to exercise the host's loops.

    Not a second model of the hardware — the RTL is the model, and the
    half above tests against it. This exists to be *unreliable* on
    demand, which is the one thing a testbench cannot conveniently be.
    """

    def __init__(self, nak_once=False, nak_all=False, corrupt_at=None):
        self.mem = bytearray(65536)
        self.buf = bytearray()
        self.replies = bytearray()
        self.nak_once = nak_once            # reject each chunk's first try
        self.nak_all = nak_all              # reject everything, always
        self.seen = set()
        self.corrupt_at = corrupt_at        # mangle this address on write
        self.frames = 0

    def send(self, data):
        self.buf += data
        while True:
            i = self.buf.find(L.MAGIC)
            if i < 0 or len(self.buf) < i + 2 + L.HDR:
                return
            body = self.buf[i + 2:]
            cmd = body[0]
            addr = body[1] | (body[2] << 8)
            n = body[3] | (body[4] << 8)
            need = L.HDR + (n if cmd == L.CMD_WRITE else 0) + 1
            if len(body) < need:
                return
            payload = bytes(body[L.HDR:L.HDR + n]) if cmd == L.CMD_WRITE else b""
            csum = body[need - 1]
            del self.buf[:i + 2 + need]
            self.frames += 1
            self._act(cmd, addr, n, payload, csum)

    def _act(self, cmd, addr, n, payload, csum):
        good = csum == (sum(bytes([cmd, addr & 0xFF, addr >> 8,
                                   n & 0xFF, n >> 8]) + payload) & 0xFF)
        if cmd == L.CMD_WRITE:
            # Committed as it arrives, checksum or not — the real one
            # has no frame buffer either.
            for k, b in enumerate(payload):
                self.mem[(addr + k) & 0xFFFF] = b
            if self.corrupt_at is not None and \
                    addr <= self.corrupt_at < addr + n:
                self.mem[self.corrupt_at] ^= 0xFF
            first = addr not in self.seen
            self.seen.add(addr)
            if self.nak_all or (self.nak_once and first):
                self.replies.append(L.NAK)
            else:
                self.replies.append(L.ACK if good else L.NAK)
        elif cmd == L.CMD_READ:
            if not good:
                self.replies.append(L.NAK)
                return
            data = bytes(self.mem[(addr + k) & 0xFFFF] for k in range(n))
            self.replies += data + bytes([sum(data) & 0xFF])
        elif cmd == L.CMD_PING:
            self.replies.append(0x01)
        else:
            self.replies.append(L.ACK if good else L.NAK)

    def recv(self, n, timeout):
        out = bytes(self.replies[:n])
        del self.replies[:n]
        return out


def unit_test():
    data = bytes((i * 7 + 3) & 0xFF for i in range(600))

    b = FakeBoard()
    ldr = L.Loader(b, chunk=256)
    ldr.write(0x1000, data)
    chk("a 600-byte write is three frames plus the HALT", b.frames, 4)
    chk("...and lands correctly", bytes(b.mem[0x1000:0x1000 + 600]), data)
    chk("...and nothing either side moved",
        (b.mem[0x0FFF], b.mem[0x1258]), (0, 0))

    chk("reading it back chunks too", ldr.read(0x1000, 600), data)

    # A board that rejects the first attempt at every chunk. The retry
    # has to resend the same chunk to the same address, which is the
    # documented recovery and the only one that works.
    b = FakeBoard(nak_once=True)
    ldr = L.Loader(b, chunk=256)
    ldr.write(0x2000, data)
    chk("a retried write still lands", bytes(b.mem[0x2000:0x2000 + 600]), data)
    chk("...having sent each chunk twice", b.frames, 1 + 3 * 2)

    b = FakeBoard(nak_all=True)
    ldr = L.Loader(b, chunk=256, retries=3)
    chk_raises("a board that never accepts gives up",
               lambda: ldr.write(0x3000, data))

    # Verify has to catch a byte the board mangled silently — an ACK is
    # not evidence the memory is right.
    b = FakeBoard(corrupt_at=0x4123)
    ldr = L.Loader(b, chunk=256)
    chk_raises("verify catches a silently mangled byte",
               lambda: ldr.load(0x4000, data, verify=True))

    b = FakeBoard()
    ldr = L.Loader(b, chunk=256)
    ldr.load(0x4000, data, verify=True)
    chk("verify passes on a good board", bytes(b.mem[0x4000:0x4000 + 600]),
        data)
    chk("ping", ldr.ping(), 1)

    # The pure functions, at their edges.
    chk("a frame is header plus payload plus checksum",
        len(L.frame(L.CMD_WRITE, 0x1234, 3, b"\1\2\3")), 2 + 5 + 3 + 1)
    chk("addr and len are little-endian",
        L.frame(L.CMD_READ, 0xBEEF, 0x1234)[2:7],
        bytes([L.CMD_READ, 0xEF, 0xBE, 0x34, 0x12]))
    chk("the checksum spans cmd through the last data byte",
        L.frame(L.CMD_WRITE, 0x00FF, 2, b"\x10\x20")[-1],
        (L.CMD_WRITE + 0xFF + 0x00 + 0x02 + 0x00 + 0x10 + 0x20) & 0xFF)
    chk("READ answers with len+1 bytes", L.reply_len(L.CMD_READ, 7), 8)
    chk("everything else answers with one", L.reply_len(L.CMD_GO, 7), 1)
    chk_raises("a bad read checksum is caught",
               lambda: L.parse_read(b"\x01\x02\x00", 2))
    chk_raises("a NAK is an error", lambda: L.parse_ack(bytes([L.NAK])))
    chk_raises("a short reply is an error", lambda: L.parse_ack(b""))
    chk("hex bytes parse either way",
        (L.hexbytes("07 5a"), L.hexbytes("075a")), (b"\x07\x5a",) * 2)


# ==================================================================

def main():
    os.makedirs(BUILD, exist_ok=True)

    print("  the command loops, against a fake board")
    unit_test()
    n_unit = len(failures)

    print("  the wire format, against the RTL")
    wire_test()

    print(f"\n  {len(failures)} failure(s)"
          f"{'' if not failures else ' — ' + str(n_unit) + ' in the loops'}")
    print("\n" + ("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
