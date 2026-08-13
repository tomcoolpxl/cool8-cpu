#!/usr/bin/env python3
"""The Machine API, served by cool8rs — THE machine, since the Python
reference retired (D55/D57 in docs/01-decisions.md).

Two shapes:

- `machine()` — the batch machine: CPU and RAM per call over one
  shared `+serve` process. `bus.mem`, the register file (round-trips,
  so poke → run → inspect → run again works), `romen`, `breakpoints`,
  `run(until=…, cycles=…, budget=…)` with the classic reasons —
  "until", "breakpoint", "cycles", "halt", "budget". Peripheral state
  does not survive between runs; `until` takes PCs, never a predicate.
- `Machine()` / `boot()` — the session machine: one persistent machine
  with peripherals, flash and all, one `+serve` process each. Adds
  `type`/`key`/`scancode`/`said`, the screen (`row`/`text`/`shows`),
  `settle`, `run_frame`, `fb()` (with `render=True`), the cycle
  profiler and the SP low-water mark — every per-instruction look
  answered server-side, because the boundary stays at machine-API
  granularity and a pipe cannot afford a round trip per tick.

The machine steps at ~66 M instr/s. There is no Python fallback: a
clone without cargo cannot run the suites, and says so.
"""

import atexit
import os
import shutil
import subprocess
import sys

# The I/O page base, from the one place it is written down: a client that
# kept its own copy would poke the old page after a move and report the
# hardware as broken (D67).
import ioregs as _ioregs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)        # cool8kbd, mkrom, mkfont live beside us
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(ROOT, "sim", "build")
EXE = os.path.join(ROOT, "rust", "target", "release",
                   "cool8rs.exe" if os.name == "nt" else "cool8rs")

_available = None
_server = None
_serial = [0]


def available():
    """Is the fast machine usable here? Builds it once if cargo is."""
    global _available
    if _available is None:
        if os.path.exists(EXE):
            _available = True
        elif shutil.which("cargo"):
            r = subprocess.run(["cargo", "build", "--release"],
                               cwd=os.path.join(ROOT, "rust"),
                               capture_output=True)
            _available = r.returncode == 0 and os.path.exists(EXE)
        else:
            _available = False
    return _available


def _quit_server():
    global _server
    if _server is not None and _server.poll() is None:
        try:
            _server.stdin.write("quit\n")
            _server.stdin.flush()
        except OSError:
            pass
        _server.wait(timeout=5)
    _server = None


def _srv():
    global _server
    if _server is None or _server.poll() is not None:
        _server = subprocess.Popen([EXE, "+serve"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, text=True)
        atexit.register(_quit_server)
    return _server


class _Cpu:
    def __init__(self):
        self.pc = 0
        # The top of contiguous RAM, below the I/O page — not $FFF8,
        # which the page now covers (D67).
        self.sp = _ioregs.IO_BASE - 1
        self.r = [0, 0, 0, 0]
        self.x = 0
        self.y = 0
        self.f = 0
        self.halted = False
        self.cycles = 0
        self.instructions = 0

    # The flags, unpacked from F the way the emulator packed them —
    # C, Z, N, V, I from bit 0 up — so a harness can keep asking c.Z.
    def _flag(bit):                                        # noqa: N805
        def get(self):
            return bool(self.f & (1 << bit))

        def set_(self, v):
            self.f = (self.f & ~(1 << bit)) | (bool(v) << bit)
        return property(get, set_)

    C, Z, N, V, I = _flag(0), _flag(1), _flag(2), _flag(3), _flag(4)
    del _flag


class _Bus:
    def __init__(self):
        self.mem = bytearray(0x10000)

    # emu.Bus's little conveniences, kept so harnesses read unchanged.
    def read(self, a):
        return self.mem[a & 0xFFFF]

    def write(self, a, v):
        self.mem[a & 0xFFFF] = v & 0xFF

    def load(self, base, blob):
        self.mem[base:base + len(blob)] = blob

    def read16(self, a):
        return self.mem[a & 0xFFFF] | (self.mem[(a + 1) & 0xFFFF] << 8)

    def write16(self, a, v):
        self.mem[a & 0xFFFF] = v & 0xFF
        self.mem[(a + 1) & 0xFFFF] = (v >> 8) & 0xFF


class _Trace:
    """`trace` and `trace_report`, shared by both machines.

    The API docs/10-debugging.md and AGENTS.md describe. It lived in
    neither class for long enough that sim/test_fp.py's --trace mode
    was calling a method that did not exist and nobody noticed, which
    is what a documented tool with no implementation costs.
    """

    def trace(self, n=32, syms=None, into=True):
        """What the machine executes next, one instruction at a time.

        **A breakpoint says where it stopped; this says what it did.**
        Decoded *forward* from the live PC through `opcodes.disassemble`
        -- the normative decoder -- so the boundaries are the ones the
        CPU used. Decoding backwards from a symptom is the mistake
        written up at the top of sim/dbg.py.

        `into=False` steps over a CALL, running to the address after it,
        so one routine's shape is not buried under its callees.

        Returns (pc, label or None, text) rows for `trace_report`.

        **A round trip per instruction**, which is why this takes an `n`
        and is not how anything watches a whole run -- `settle` and the
        profiler are server-side commands for exactly that reason. Tens
        or hundreds of instructions is what it is for.
        """
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import opcodes                                      # noqa: E402

        at = {}
        for name, a in (syms or {}).items():
            at.setdefault(a, name)
        rows = []
        for _ in range(n):
            pc = self.cpu.pc
            try:
                text, ln = opcodes.disassemble(
                    lambda i: self.bus.mem[i & 0xFFFF], pc)
            except Exception:
                text, ln = None, 0
            rows.append((pc, at.get(pc), text or "?"))
            if self.cpu.halted:
                break
            if not into and text and text.split()[0] == "CALL" and ln > 0:
                self.run(until=pc + ln)
            else:
                self.tick()
        return rows

    @staticmethod
    def trace_report(rows):
        """`trace`'s rows as text, labels in the margin."""
        out = []
        for pc, label, text in rows:
            out.append("  %-14s $%04X  %s" % (label or "", pc, text))
        return "\n".join(out)


class RustMachine(_Trace):
    """See the module header. The registers round-trip, so poke → run →
    inspect → run again works exactly as it does on vm.Machine; what
    does NOT survive between runs is peripheral state (video, UART,
    keyboard, flash), because every run is a fresh machine around the
    carried CPU and memory. Batch workloads touch none of it; one that
    starts to belongs on the machine-mode script harness instead."""

    backend = "rust"

    def __init__(self):
        self.bus = _Bus()
        self.cpu = _Cpu()
        self.romen = True
        self.breakpoints = set()

    @staticmethod
    def _pcs(spec):
        if spec is None:
            return "-"
        if isinstance(spec, int):
            spec = (spec,)
        if callable(spec):
            raise NotImplementedError(
                "the batch machine takes PCs, not predicates; a test "
                "that needs one drives the machine differently")
        return ",".join(str(p) for p in spec) or "-"

    def tick(self):
        """One instruction.

        **The batch machine has no peripherals and so no interrupts**,
        which is what lets an instruction be exactly its own cycle
        count: nothing can arrive part-way and change the boundary.
        `opcodes.cycles()` is normative and `poe check` gates it
        against the RTL, so this is the same instruction the CPU sees.

        A whole `run` round trip each time -- a memory file written and
        read -- so this is for a trace of tens of instructions, never
        for watching a workload.
        """
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import opcodes                                      # noqa: E402
        pc = self.cpu.pc
        # **The breakpoints have to go for the duration.** `run` stops
        # *at* a breakpoint, and a trace begins standing on one, so
        # leaving them set makes every step halt before it executes and
        # the PC never moves -- which reads as a hung machine.
        bps, self.breakpoints = self.breakpoints, set()
        try:
            self.run(cycles=opcodes.cycles(self.bus.mem[pc],
                                           self.bus.mem[(pc + 1) & 0xFFFF]))
        finally:
            self.breakpoints = bps

    def run(self, until=None, cycles=None, budget=200_000_000):
        os.makedirs(BUILD, exist_ok=True)
        _serial[0] += 1
        base = os.path.join(BUILD, "rsvm_%d_%d" % (os.getpid(), _serial[0]))
        mem_in, mem_out = base + ".in", base + ".out"
        with open(mem_in, "wb") as f:
            f.write(self.bus.mem)

        c = self.cpu
        regs = ",".join(str(v) for v in (
            c.pc, c.sp, c.r[0], c.r[1], c.r[2], c.r[3], c.x, c.y, c.f,
            c.cycles, c.instructions, 1 if c.halted else 0))
        s = _srv()
        s.stdin.write("run\t%s\t%s\t%d\t%d\t%s\t%s\t%s\t%s\n"
                      % (mem_in, mem_out, budget, 1 if self.romen else 0,
                         regs, self._pcs(until), self._pcs(self.breakpoints),
                         "-" if cycles is None else int(cycles)))
        s.stdin.flush()
        resp = s.stdout.readline().split()
        if not resp or resp[0] != "ok":
            raise RuntimeError("cool8rs server: %r" % (resp,))
        reason = resp[1]
        v = [int(x) for x in resp[2].split(",")]
        (c.pc, c.sp, c.r[0], c.r[1], c.r[2], c.r[3], c.x, c.y, c.f,
         c.cycles, c.instructions) = v[:11]
        c.halted = bool(v[11])
        with open(mem_out, "rb") as f:
            self.bus.mem[:] = f.read()
        os.remove(mem_in)
        os.remove(mem_out)
        return reason


def machine():
    """The batch machine. cool8rs is the machine now — there is no
    Python fallback; a clone without cargo cannot run the suites."""
    _require()
    return RustMachine()


def _require():
    if not available():
        raise SystemExit(
            "cool8rs is not built and cargo was not found. The machine "
            "is rust/ (RUST_PORT.md); install a Rust toolchain "
            "(https://rustup.rs) or build rust/ elsewhere.")


# ---------------------------------------------------------------- sessions
#
# The batch machine above carries CPU and RAM per call and nothing else.
# The session machine holds ONE persistent cool8rs machine — UART, PS/2,
# video, flash and all — which is what the interactive suites need:
# type, settle, read the screen, type again. One `+serve` process per
# SessionMachine, so two sessions can never trample each other's state.
#
# The surface is the one the suites already knew; the
# boundary stays at machine-API granularity (RUST_PORT.md's rule), which
# is why `settle` — a per-instruction poll — is a server-side command
# and not a tick loop over the pipe.

# The session's register mirror is the same shape; reads are current
# because registers only change during stepping commands, which pull.
_SessCpu = _Cpu


class _SessMem:
    """m.bus.mem, over the wire. Suites read and write slices during
    setup and assertion, never in hot loops, so a round trip per access
    is the right trade."""
    def __init__(self, sess):
        self._s = sess

    def _rd(self, a, n):
        h = self._s._cmd("rd\t%d\t%d" % (a, n))[0]
        return b"" if h == "-" else bytes.fromhex(h)

    def __getitem__(self, k):
        if isinstance(k, slice):
            start, stop = k.start or 0, k.stop if k.stop is not None \
                else 0x10000
            return bytearray(self._rd(start, max(0, stop - start)))
        return self._rd(k, 1)[0]

    def __setitem__(self, k, v):
        if isinstance(k, slice):
            start = k.start or 0
            self._s._cmd("wr\t%d\t%s" % (start, bytes(v).hex() or "-"))
        else:
            self._s._cmd("wr\t%d\t%s" % (k, bytes([v]).hex()))


class _SessBus:
    def __init__(self, sess):
        self.mem = _SessMem(sess)
        self._s = sess

    def read(self, a):
        return int(self._s._cmd("busrd\t%d" % a)[0])

    def write(self, a, v):
        self._s._cmd("buswr\t%d\t%s" % (a, bytes([v & 0xFF]).hex()))


class _SessUart:
    def __init__(self, sess):
        self._s = sess

    def feed(self, data):
        self._s._cmd("type\t%s" % (bytes(data).hex() or "-"))

    def take(self):
        h = self._s._cmd("said")[0]
        return b"" if h == "-" else bytes.fromhex(h)

    @property
    def rx(self):
        """The FIFO's fill as an int — the suites only test truthiness."""
        return self._s._stat()[0]

    @property
    def overrun(self):
        return self._s._stat()[2] != 0


class _SessKbd:
    def __init__(self, sess):
        self._s = sess

    def feed(self, codes):
        self._s._cmd("scan\t%s" % (bytes(codes).hex() or "-"))

    @property
    def q(self):
        return self._s._stat()[1]

    @property
    def overrun(self):
        return self._s._stat()[3] != 0

    @property
    def irq_en(self):
        return self._s._stat()[4] != 0


class _SessVram:
    def __init__(self, sess):
        self._s = sess

    def __getitem__(self, k):
        if isinstance(k, slice):
            start, stop = k.start or 0, k.stop if k.stop is not None \
                else 0x10000
            h = self._s._cmd("vrd\t%d\t%d" % (start, max(0, stop - start)))[0]
            return bytearray(b"" if h == "-" else bytes.fromhex(h))
        return int(self._s._cmd("vrd\t%d\t1" % k)[0], 16)

    def __setitem__(self, k, v):
        if isinstance(k, slice):
            start = k.start or 0
            self._s._cmd("vwr\t%d\t%s" % (start, bytes(v).hex() or "-"))
        else:
            self._s._cmd("vwr\t%d\t%s" % (k, bytes([v]).hex()))


class _SessVideo:
    """The video registers the suites read, through the bus — these
    reads have no side effects on the register file."""
    def __init__(self, sess):
        self._s = sess
        self.vram = _SessVram(sess)

    @property
    def ctrl(self):
        return self._s.bus.read(_ioregs.addr_of("VID_CTRL"))

    @property
    def cur_x(self):
        return self._s.bus.read(_ioregs.addr_of("CUR_X"))

    @property
    def cur_y(self):
        return self._s.bus.read(_ioregs.addr_of("CUR_Y"))


class _SessFlash:
    def __init__(self, sess):
        self._s = sess

    def flush(self):
        self._s._cmd("flush")


class SessionMachine(_Trace):
    """The persistent machine with peripherals attached.

    What does NOT cross: predicates (`run(until=callable)` raises) and
    per-write watches — observation that needs every instruction is a
    server-side command (`settle`, the profiler, `sp_min`), and a test
    needing a new one extends the protocol rather than looping here.
    """

    backend = "rust-session"

    def __init__(self, rom=None, font=None, flash_path=None, render=False):
        # The font is render-only; text()/row() read RAM. It matters
        # only when the renderer is attached.
        os.makedirs(BUILD, exist_ok=True)
        self._proc = subprocess.Popen([EXE, "+serve"], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, text=True)
        atexit.register(self._quit)
        _serial[0] += 1
        stem = os.path.join(BUILD, "rsvm_%d_%d" % (os.getpid(), _serial[0]))
        rom_arg = font_arg = "-"
        if rom is not None:
            rom_arg = stem + "_rom.bin"
            with open(rom_arg, "wb") as f:
                f.write(bytes(rom))
        if render:
            font_arg = "0"
            if font is not None:
                font_arg = stem + "_font.bin"
                with open(font_arg, "wb") as f:
                    f.write(bytes(font))
        self._cmd("new\t%s\t%s\t%s" % (rom_arg, flash_path or "-", font_arg))
        for p in (rom_arg, font_arg):
            if p not in ("-", "0"):
                os.remove(p)
        self.bus = _SessBus(self)
        self.uart = _SessUart(self)
        self.kbd = _SessKbd(self)
        self.flash = _SessFlash(self)
        self.video = _SessVideo(self)
        self.cpu = _SessCpu()
        self._romen = True
        self.breakpoints = set()
        self._pull()

    def _quit(self):
        if self._proc.poll() is None:
            try:
                self._proc.stdin.write("quit\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
            except OSError:
                pass

    def _cmd(self, line):
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()
        resp = self._proc.stdout.readline().split()
        if not resp or resp[0] != "ok":
            raise RuntimeError("cool8rs session: %r" % (resp,))
        return resp[1:]

    def _stat(self):
        return [int(v) for v in self._cmd("stat")]

    def _push(self):
        c = self.cpu
        regs = ",".join(str(v) for v in (
            c.pc, c.sp, c.r[0], c.r[1], c.r[2], c.r[3], c.x, c.y, c.f,
            c.cycles, c.instructions, 1 if c.halted else 0))
        self._cmd("sregs\t%s\t%d" % (regs, 1 if self._romen else 0))

    def _pull(self, csv=None, romen=None):
        if csv is None:
            csv, romen = self._cmd("gregs")[:2]
        v = [int(x) for x in csv.split(",")]
        c = self.cpu
        (c.pc, c.sp, c.r[0], c.r[1], c.r[2], c.r[3], c.x, c.y, c.f,
         c.cycles, c.instructions) = v[:11]
        c.halted = bool(v[11])
        if romen is not None:
            self._romen = bool(int(romen))

    @property
    def romen(self):
        """ROMEN is machine state — SYSCTRL bit 0 — and the machine
        changes it (the flash stub drops the overlay before jumping),
        so it round-trips with the registers rather than being a
        client-side belief. Setting it pushes immediately."""
        return self._romen

    @romen.setter
    def romen(self, v):
        self._romen = bool(v)
        self._push()

    @staticmethod
    def _pcs(spec):
        if spec is None:
            return "-"
        if isinstance(spec, int):
            spec = (spec,)
        if callable(spec):
            raise NotImplementedError(
                "the session machine takes PCs, not predicates; a test "
                "that needs one drives the machine differently")
        return ",".join(str(p) for p in spec) or "-"

    # ------------------------------------------------------------ running

    def run(self, until=None, cycles=None, budget=200_000_000):
        self._push()
        r = self._cmd("srun\t%d\t%s\t%s\t%s"
                      % (budget, self._pcs(until),
                         self._pcs(self.breakpoints),
                         "-" if cycles is None else int(cycles)))
        self._pull(r[1], r[2])
        return r[0]

    def tick(self):
        self._push()
        r = self._cmd("ticks\t1")
        self._pull(r[0], r[1])

    def run_frame(self, n=1):
        self._push()
        r = self._cmd("frames\t%d" % n)
        self._pull(r[0], r[1])

    def settle(self, idle_pc, irhead, irtail, budget=80_000_000):
        """Run until the machine is idle: UART FIFO empty, PS/2 FIFO
        empty, the input ring drained, PC at the idle label. The same
        loop the suites hand-rolled, server-side because it polls
        per instruction."""
        self._push()
        r = self._cmd("settle\t%d\t%d\t%d\t%d"
                      % (idle_pc, irhead, irtail, budget))
        self._pull(r[1], r[2])
        return r[0] == "settled"

    def press_break(self):
        self._cmd("nmi")

    # ---------------------------------------------------- typing, reading

    def type(self, text):
        if isinstance(text, str):
            text = text.replace("\n", "\r").encode("latin-1")
        self.uart.feed(text)

    def said(self):
        return self.uart.take()

    def key(self, text):
        import cool8kbd
        self.kbd.feed(cool8kbd.encode_keys(text))

    def scancode(self, codes):
        self.kbd.feed(bytes(codes))

    def _text_bytes(self):
        return bytes.fromhex(self._cmd("text")[0])

    def row(self, r, cols=80):
        raw = self._text_bytes()[r * 80:r * 80 + cols]
        return "".join(chr(b) for b in raw).replace("\x00", " ").rstrip()

    def text(self, rows=30, cols=80):
        raw = self._text_bytes()
        return ["".join(chr(b) for b in raw[r * 80:r * 80 + cols])
                .replace("\x00", " ").rstrip() for r in range(rows)]

    def shows(self, want):
        return any(r.strip() == want for r in self.text())

    def fb(self):
        """The rendered frame: 640x480 of 12-bit palette colours, as a
        flat list. Needs `render=True` at construction."""
        raw = bytes.fromhex(self._cmd("fb")[0])
        return [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]

    @property
    def frames(self):
        return self._stat()[5]

    def palette(self):
        """The committed palette entries, 256 of $0RGB."""
        raw = bytes.fromhex(self._cmd("pald")[0])
        return [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]

    def sprites(self):
        """The 256 sprite descriptor bytes."""
        return bytes.fromhex(self._cmd("sprd")[0])

    def sound(self):
        """The programmed voice array, 8 bytes a voice in the register
        layout: inc lo/hi, phase lo/hi, volume, noise/enable bits."""
        return bytes.fromhex(self._cmd("sndd")[0])

    def samples(self):
        """The level stream since the last call, at the engine's own
        32.7 kHz."""
        h = self._cmd("snds")[0]
        return b"" if h == "-" else bytes.fromhex(h)

    def io_write(self, reg, val):
        """One write to the I/O page, by register offset — `IO_BASE |
        reg`, through the bus, so the auto-incrementing data ports
        behave as they do for software."""
        self.bus.write(_ioregs.IO_BASE | (reg & 0xFF), val)

    def io_writes(self, reg, values):
        """A run of writes to one I/O register, in a single round trip
        — the idiom PAL_DATA, SPR_DATA and SND_DATA are built for."""
        self._cmd("buswr\t%d\t%s"
                  % (_ioregs.IO_BASE | (reg & 0xFF),
                     bytes(values).hex() or "-"))

    # ------------------------------------------------- observation, cheap
    #
    # Per-instruction looks a pipe cannot afford, answered server-side.

    def profile_start(self):
        self._cmd("profon")

    def profile_cycles(self):
        """{pc: cycles} since profile_start."""
        out = {}
        for tok in self._cmd("profdump"):
            pc, c = tok.split(":")
            out[int(pc)] = int(c)
        return out

    def watch(self, lo, hi):
        """Record every write into [lo, hi], with the PC that did it.

        `self.hits` is then a list of `(pc, addr, value)`. AGENTS.md has
        documented this since before it existed; it exists now, because
        the question "who wrote the garbage" came up during [D74] and
        the answer was an AttributeError.
        """
        self._cmd("watch	%d	%d" % (lo, hi))

    @property
    def hits(self):
        out = []
        for t in self._cmd("hits"):
            pc, a, v = t.split(":")
            out.append((int(pc), int(a), int(v)))
        return out

    def sp_min(self):
        """The stack's low-water mark since sp_clear (or forever)."""
        return int(self._cmd("spmin")[0])

    def sp_clear(self):
        self._cmd("spclr")


def Machine(rom=None, font=None, flash_path=None, render=False):
    """A machine with peripherals — the session machine, always.
    `render=True` attaches the scanline renderer so `fb()` answers."""
    _require()
    return SessionMachine(rom=rom, font=font, flash_path=flash_path,
                          render=render)


def build_rom():
    """The real boot ROM and the font, built by the ordinary tools."""
    import mkrom
    import mkfont
    base, img, rom = mkrom.build(os.path.join(ROOT, "sw", "boot.asm"))
    font, _, _ = mkfont.build(os.path.join(ROOT, "assets", "font",
                                           "spleen-8x16.bdf"))
    return bytearray(rom), bytearray(font)


def boot(flash_path=None, render=False):
    """A machine with the real ROM in it, sitting at its reset vector."""
    _require()
    rom, font = build_rom()
    return SessionMachine(rom=rom, font=font, flash_path=flash_path,
                          render=render)


def converse(m, text='', frames=8):
    """Type at the machine, and collect what it says back."""
    if text:
        m.uart.feed(text.replace('\\r', '\r').encode('latin-1'))
    m.run_frame(frames)
    return m.uart.take().decode('latin-1')
