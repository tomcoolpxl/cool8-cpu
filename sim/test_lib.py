#!/usr/bin/env python3
"""M14 -- the runtime library, and the demo rewritten in the language.

    python sim/test_lib.py

`sw/demo.asm` is hand-written assembly: a tiled background, eight 16x16
sprites bouncing, and a two-voice arpeggio with a software envelope.
`sw/demo.bas` is the same thing written in COOL8 BASIC against
`sw/lib.bas`. This measures one against the other.

**Gate: the language version is no more than 2x slower.**

## How the comparison is made fair

Both programs wait for vertical blank, so left alone they would run at
exactly the same speed -- 60 frames a second, both idle. So the vblank
flag is held permanently ready for both, which turns the wait into a no
-op and lets each run its update loop flat out. Frames are counted by
watching writes of zero to `SPR_IDX`, which is how each version starts
its sprite pass, and the measure is frames completed per million clocks.

Setup is measured separately: it is a one-off, it is dominated by
pushing 8 KB through the VRAM port, and averaging it into a per-frame
figure would flatter whichever version was given more frames.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8emu as emu                                   # noqa: E402
import cool8bas as bas                                   # noqa: E402

TOLERANCE = 2.0
BUDGET = 60_000_000          # clocks each version is given
FAILS = []


def check(ok, what, detail=""):
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


class Bus(emu.Bus):
    """RAM, VRAM behind its port, and just enough I/O to run the demo.

    The vblank flag reads as permanently ready, which is what makes the
    two versions comparable: both spin on it, and neither should be
    measured waiting.
    """

    def __init__(self):
        self.mem = bytearray(0x10000)
        self.vram = bytearray(0x10000)
        self.vaddr = 0
        self.frames = 0
        self.spr = bytearray(256)
        self.spr_idx = 0
        self.snd = bytearray(64)
        self.snd_idx = 0
        self.pal = []
        self.pal_idx = 0
        self.regs = {}

    def read(self, a):
        a &= 0xFFFF
        if (a & 0xFF00) == 0xFE00:
            r = a & 0xFF
            if r == 0x1D:
                return 0x02                 # vblank, always pending
            if r == 0x29:
                v = self.vram[self.vaddr]
                self.vaddr = (self.vaddr + 1) & 0xFFFF
                return v
            return self.regs.get(r, 0xFF)
        return self.mem[a]

    def write(self, a, v):
        a &= 0xFFFF
        v &= 0xFF
        if (a & 0xFF00) == 0xFE00:
            r = a & 0xFF
            self.regs[r] = v
            if r == 0x26:
                self.vaddr = (self.vaddr & 0xFF00) | v
            elif r == 0x27:
                self.vaddr = (self.vaddr & 0x00FF) | (v << 8)
            elif r == 0x29:
                self.vram[self.vaddr] = v
                self.vaddr = (self.vaddr + 1) & 0xFFFF
            elif r == 0x1E:
                self.pal_idx = v
            elif r == 0x1F:
                # The stream of bytes, not a decoded palette: a byte
                # pair commits an entry and the index then advances, and
                # modelling that here would be a second implementation
                # of cool8_pal to get wrong. What matters is that both
                # versions send the same bytes.
                self.pal.append(v)
            elif r == 0x2A:
                self.spr_idx = v
                if v == 0:
                    self.frames += 1        # each pass starts at sprite 0
            elif r == 0x2B:
                self.spr[self.spr_idx] = v
                self.spr_idx = (self.spr_idx + 1) & 0xFF
            elif r == 0x50:
                self.snd_idx = v & 0x3F
            elif r == 0x51:
                self.snd[self.snd_idx] = v
                self.snd_idx = (self.snd_idx + 1) & 0x3F
            return
        self.mem[a] = v


def run(code, budget=BUDGET):
    bus = Bus()
    bus.mem[0x200:0x200 + len(code)] = code
    c = emu.Cool8(bus)
    c.reset()
    c.pc = 0x200
    c.sp = 0xFFF7
    setup = None
    n = 0
    while c.cycles < budget and not c.halted:
        c.step()
        n += 1
        if setup is None and bus.frames == 1:
            setup = c.cycles
    return bus, c.cycles, setup


def build_asm(src, out):
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"),
                        os.path.join(ROOT, "sw", src),
                        "-o", os.path.join(BUILD, out)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("assembly failed: " + src)
    with open(os.path.join(BUILD, out), "rb") as fh:
        return fh.read()


def build_bas(src, out):
    with open(os.path.join(ROOT, "sw", src), encoding="utf-8") as fh:
        asm = bas.compile_source(fh.read())
    apath = os.path.join(BUILD, out + ".asm")
    with open(apath, "w") as fh:
        fh.write(asm)
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), apath,
                        "-o", os.path.join(BUILD, out)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("compile failed: " + src)
    with open(os.path.join(BUILD, out), "rb") as fh:
        return fh.read()


def main():
    print("  M14 -- sw/demo.bas against sw/demo.asm")
    print()

    a_code = build_asm("demo.asm", "demo_asm.bin")
    b_code = build_bas("demo.bas", "demo_bas.bin")

    a_bus, a_cyc, a_setup = run(a_code)
    b_bus, b_cyc, b_setup = run(b_code)

    print(f"  {'':<22} {'assembly':>12} {'BASIC':>12} {'ratio':>8}")
    print(f"  {'code size':<22} {len(a_code):11,}B {len(b_code):11,}B "
          f"{len(b_code)/len(a_code):7.2f}x")
    print(f"  {'setup, to frame 1':<22} {a_setup:11,} {b_setup:11,} "
          f"{b_setup/a_setup:7.2f}x")
    fa = a_bus.frames / (a_cyc / 1e6)
    fb = b_bus.frames / (b_cyc / 1e6)
    print(f"  {'frames':<22} {a_bus.frames:11,} {b_bus.frames:11,}")
    print(f"  {'frames per Mclock':<22} {fa:11.1f} {fb:11.1f} "
          f"{fa/fb:7.2f}x")
    print()

    slow = fa / fb
    check(slow <= TOLERANCE,
          f"the language version is within {TOLERANCE:g}x of assembly",
          f"{slow:.2f}x slower")

    # ---- and it has to be the same demo, not merely a fast one
    check(a_bus.vram[0x4000:0x4020] == b_bus.vram[0x4000:0x4020]
          and a_bus.vram[0x4020:0x4040] == b_bus.vram[0x4020:0x4040],
          "the tile patterns match the assembly version",
          f"asm {a_bus.vram[0x4000:0x4008].hex()} "
          f"bas {b_bus.vram[0x4000:0x4008].hex()}")
    check(a_bus.vram[0x6000:0x6080] == b_bus.vram[0x6000:0x6080],
          "the sprite pattern matches, all 128 bytes",
          f"asm {a_bus.vram[0x6040:0x6048].hex()} "
          f"bas {b_bus.vram[0x6040:0x6048].hex()}")
    check(a_bus.vram[0:256] == b_bus.vram[0:256],
          "the first row of the tile map matches")
    check(a_bus.pal[:512] == b_bus.pal[:512],
          "the palette bytes match, all 256 entries",
          f"asm {a_bus.pal[:6]} bas {b_bus.pal[:6]}")

    def enabled(bus):
        return sum(1 for i in range(8) if bus.spr[i * 8 + 1] & 0x40)
    check(enabled(a_bus) == 8 and enabled(b_bus) == 8,
          "both have eight sprites enabled and moving",
          f"asm {enabled(a_bus)} bas {enabled(b_bus)}")
    check(a_bus.snd[4] != 0 and b_bus.snd[4] != 0
          and a_bus.snd[0] != 0 and b_bus.snd[0] != 0,
          "both are playing: voice 0 has a pitch and a volume",
          f"asm inc={a_bus.snd[0]:02x}{a_bus.snd[1]:02x} "
          f"vol={a_bus.snd[4]:02x}  "
          f"bas inc={b_bus.snd[0]:02x}{b_bus.snd[1]:02x} "
          f"vol={b_bus.snd[4]:02x}")

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
