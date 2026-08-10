#!/usr/bin/env python3
"""A cool8vm.Machine stand-in backed by the Rust fast machine.

`machine()` returns the Rust-backed batch machine when `rust/` is built
(or cargo can build it), and the reference `cool8vm.Machine` otherwise;
`COOL8_PYVM=1` forces the reference, which is how to rule the fast
machine out when a failure needs a second opinion.

The surface is exactly the slice the batch suites use and no more:
`bus.mem` to poke and read, `cpu.pc`/`cpu.sp` to set, `romen`,
`run(budget=...)` returning "halt" or "budget", and `cpu.cycles` /
`cpu.instructions` afterwards. Anything finer — a tick loop, `watch`,
`trace`, the keyboard, the screen — belongs on the reference machine:
use `cool8vm.Machine` directly for those cases and say why.

**This is not a second machine model.** rust/src/machine.rs is held to
cool8vm.py per retired instruction by sim/rustsim.py (RUST_PORT.md),
and the server-side run loop is Machine.run's own, so a test moved here
keeps its stopping behaviour exactly. What it buys is speed: the
machine steps at ~66 M instr/s against CPython's ~0.5 M.

One `cool8rs +serve` process is shared by every RustMachine in the
process, so a suite of a hundred cases pays one spawn, not a hundred.
Each run is a fresh machine on the far side — which is also the shape
every batch suite already has, one Machine per case — so `run()` can be
called once per RustMachine; a second call raises rather than silently
resuming with stale registers.
"""

import atexit
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
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
        if os.environ.get("COOL8_PYVM"):
            _available = False
        elif os.path.exists(EXE):
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
        self.sp = 0xFFF8
        self.cycles = 0
        self.instructions = 0


class _Bus:
    def __init__(self):
        self.mem = bytearray(0x10000)


class RustMachine:
    backend = "rust"

    def __init__(self):
        self.bus = _Bus()
        self.cpu = _Cpu()
        self.romen = True
        self._ran = False

    def run(self, until=None, cycles=None, budget=200_000_000):
        if until is not None or cycles is not None:
            raise NotImplementedError(
                "the batch machine runs to a halt or a budget; a test "
                "that needs until/cycles belongs on cool8vm.Machine")
        if self._ran:
            raise RuntimeError(
                "one run per RustMachine — registers do not round-trip, "
                "so a resume would be a different machine. Make a new one")
        self._ran = True

        os.makedirs(BUILD, exist_ok=True)
        _serial[0] += 1
        base = os.path.join(BUILD, "rsvm_%d_%d" % (os.getpid(), _serial[0]))
        mem_in, mem_out = base + ".in", base + ".out"
        with open(mem_in, "wb") as f:
            f.write(self.bus.mem)

        s = _srv()
        s.stdin.write("run\t%s\t%s\t%d\t%d\t%d\t%d\n"
                      % (mem_in, mem_out, self.cpu.pc, self.cpu.sp,
                         1 if self.romen else 0, budget))
        s.stdin.flush()
        resp = s.stdout.readline().split()
        if not resp or resp[0] != "ok":
            raise RuntimeError("cool8rs server: %r" % (resp,))
        reason = resp[1]
        self.cpu.instructions = int(resp[2])
        self.cpu.cycles = int(resp[3])
        with open(mem_out, "rb") as f:
            self.bus.mem[:] = f.read()
        os.remove(mem_in)
        os.remove(mem_out)
        return reason


def machine():
    """The fast machine if it is usable, the reference machine if not."""
    if available():
        return RustMachine()
    sys.path.insert(0, HERE)
    import cool8vm
    return cool8vm.Machine()
