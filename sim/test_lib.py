#!/usr/bin/env python3
"""M14 -- the runtime library, and the demo rewritten in the language.

    python sim/test_lib.py

`sw/demo.asm` is hand-written assembly: a tiled background, eight 16x16
sprites bouncing, and a two-voice arpeggio with a software envelope.
`sw/demo.bas` is the same thing written in COOL8 BASIC against
`sw/lib.bas`. This measures one against the other.

**Gate: the language version is no more than 2x slower.**

## How the comparison is made fair

Both programs wait for vertical blank, so on a real machine they run at
exactly the same speed: 60 frames a second, each spending the rest of
the frame spinning on `VID_IRQ`. **Frames completed is therefore not a
measurement** -- it is 429 either way in a 60 Mclock budget, and a gate
built on it can never fail. (It was one, for a while, and passed at
1.00x for the same reason a stopped clock is right: this file used to
run on a hand-written bus that held the vblank flag permanently ready
so both versions ran flat out.)

What is measured instead is **work per frame**: the clocks each version
spends *not* spinning. The machine's profiler charges every cycle to
the PC that spent it, so the spin loop's own cycles subtract out and
what is left is the update -- sprite movement, the music, the envelope.
That is the number the gate is about, and it is the one a demo with a
sixteenth voice would move.

Setup is measured separately: it is a one-off, it is dominated by
pushing 8 KB through the VRAM port, and averaging it into a per-frame
figure would flatter whichever version was given more frames.

## What the comparison reads

The machine's own state, through the session dumps -- VRAM, the
committed palette entries, the sprite descriptor table and the
programmed sound voices (`m.palette()`, `m.sprites()`, `m.sound()`).
This file used to carry a hand-written bus that modelled just enough
of the I/O page to fake those, which meant the gate compared two
programs against a *third* implementation of the hardware, written
here and nowhere else. It now compares them on the machine both would
run on.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8rsvm as vm                                   # noqa: E402
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


def start(code):
    """The program loaded at $0200, ready to run."""
    m = vm.Machine()
    m.bus.mem[0x200:0x200 + len(code)] = code
    m.cpu.pc, m.cpu.sp, m.romen = 0x200, 0xFFF7, False
    return m


def measure_setup(code, syms, budget=BUDGET):
    """The clocks before the first sprite pass.

    Setup ends when the descriptor table stops being all zero, which is
    the first thing the update loop does. Stepped in fine slices and
    asked, rather than hooked: a 5000-clock slice is 4 % of a frame, so
    the boundary is exact to far better than the number it feeds.
    """
    m = start(code)
    while m.cpu.cycles < budget:
        m.run(cycles=5_000)
        if any(m.sprites()):
            return m.cpu.cycles
    return None


def wait_range(syms, name):
    """[lo, hi) of the vblank wait routine, from the symbol map: its own
    address up to the next symbol above it.

    A local label inside the routine (`wait_vbl.w`, `s_waitvbl.wv` --
    the spin itself) is part of it, not the end of it, so those are
    skipped when looking for the next symbol.
    """
    lo = syms[name]
    above = [a for n, a in syms.items()
             if a > lo and not n.startswith(name + ".")]
    return lo, min(above) if above else lo + 16


def run(code, syms, waitsym, budget=BUDGET):
    """One program for a fixed clock budget, with the spin discounted.

    Returns the machine, the clocks spent, the frames reached, and the
    clocks spent *outside* the vblank wait -- the work.
    """
    m = start(code)
    m.profile_start()
    m.run(cycles=budget)
    lo, hi = wait_range(syms, waitsym)
    spin = sum(c for pc, c in m.profile_cycles().items() if lo <= pc < hi)
    return m, m.cpu.cycles, m.frames, m.cpu.cycles - spin


def _symbols(path):
    syms = {}
    for line in open(path):
        p = line.split()
        if len(p) == 2:
            syms[p[1].lower()] = int(p[0], 16)
    return syms


def _assemble(apath, out):
    sym = os.path.join(BUILD, out + ".sym")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), apath,
                        "-o", os.path.join(BUILD, out), "--symbols", sym],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("assembly failed: " + apath)
    with open(os.path.join(BUILD, out), "rb") as fh:
        return fh.read(), _symbols(sym)


def build_asm(src, out):
    return _assemble(os.path.join(ROOT, "sw", src), out)


def build_bas(src, out):
    with open(os.path.join(ROOT, "sw", src), encoding="utf-8") as fh:
        asm = bas.compile_source(fh.read())
    apath = os.path.join(BUILD, out + ".asm")
    with open(apath, "w") as fh:
        fh.write(asm)
    return _assemble(apath, out)


def main():
    print("  M14 -- sw/demo.bas against sw/demo.asm")
    print()

    a_code, a_syms = build_asm("demo.asm", "demo_asm.bin")
    b_code, b_syms = build_bas("demo.bas", "demo_bas.bin")

    # The vblank wait, so its clocks can be taken out: `wait_vbl` in the
    # assembly, and lib.bas's `waitvbl` compiled to `s_waitvbl` with the
    # spin itself at the local label `.wv` inside it.
    a_wait, b_wait = "wait_vbl", "s_waitvbl"

    a_setup = measure_setup(a_code, a_syms)
    b_setup = measure_setup(b_code, b_syms)
    a, a_cyc, a_frames, a_work = run(a_code, a_syms, a_wait)
    b, b_cyc, b_frames, b_work = run(b_code, b_syms, b_wait)

    a_vram, b_vram = a.video.vram, b.video.vram
    a_pal, b_pal = a.palette(), b.palette()
    a_spr, b_spr = a.sprites(), b.sprites()
    a_snd, b_snd = a.sound(), b.sound()

    wa = a_work / max(a_frames, 1)
    wb = b_work / max(b_frames, 1)

    print(f"  {'':<22} {'assembly':>12} {'BASIC':>12} {'ratio':>8}")
    print(f"  {'code size':<22} {len(a_code):11,}B {len(b_code):11,}B "
          f"{len(b_code)/len(a_code):7.2f}x")
    print(f"  {'setup, to frame 1':<22} {a_setup:11,} {b_setup:11,} "
          f"{b_setup/a_setup:7.2f}x")
    # Equal by construction: both wait for vblank, so both reach the
    # same number of frames in the same budget. Printed as the control
    # it is -- if these ever differ, one version stopped waiting.
    print(f"  {'frames (both locked)':<22} {a_frames:11,} {b_frames:11,}")
    print(f"  {'work per frame':<22} {wa:11,.0f} {wb:11,.0f} "
          f"{wb/wa:7.2f}x")
    print(f"  {'of a frame''s 139,650':<22} {100*wa/139650:10.1f}% "
          f"{100*wb/139650:10.1f}%")
    print()

    check(a_frames == b_frames,
          "both are frame-locked, so work per frame is the comparison",
          f"asm {a_frames} frames, bas {b_frames}")

    slow = wb / wa
    check(slow <= TOLERANCE,
          f"the language version is within {TOLERANCE:g}x of assembly",
          f"{slow:.2f}x slower: {wb:,.0f} clocks a frame against "
          f"{wa:,.0f}")
    check(wb < 139650,
          "and it still fits inside a frame",
          f"{wb:,.0f} clocks of the 139,650 a frame has")

    # ---- and it has to be the same demo, not merely a fast one
    check(a_vram[0x4000:0x4040] == b_vram[0x4000:0x4040],
          "the tile patterns match the assembly version",
          f"asm {a_vram[0x4000:0x4008].hex()} "
          f"bas {b_vram[0x4000:0x4008].hex()}")
    check(a_vram[0x6000:0x6080] == b_vram[0x6000:0x6080],
          "the sprite pattern matches, all 128 bytes",
          f"asm {a_vram[0x6040:0x6048].hex()} "
          f"bas {b_vram[0x6040:0x6048].hex()}")
    check(a_vram[0:256] == b_vram[0:256],
          "the first row of the tile map matches")
    # The committed entries, not the byte stream that made them: what
    # matters is that both programs put the same colours in the
    # palette, whatever order they wrote the halves in.
    check(a_pal == b_pal,
          "the palette matches, all 256 entries",
          f"asm {[hex(v) for v in a_pal[:3]]} "
          f"bas {[hex(v) for v in b_pal[:3]]}")

    def enabled(spr):
        return sum(1 for i in range(8) if spr[i * 8 + 1] & 0x40)
    check(enabled(a_spr) == 8 and enabled(b_spr) == 8,
          "both have eight sprites enabled and moving",
          f"asm {enabled(a_spr)} bas {enabled(b_spr)}")
    # Every descriptor field except the position, which is where the
    # two versions are legitimately out of step: they have run a
    # different number of frames by the budget's end.
    same = all(a_spr[i * 8 + 4:i * 8 + 8] == b_spr[i * 8 + 4:i * 8 + 8]
               for i in range(8))
    check(same, "and the same pattern, flip and priority in all eight",
          f"asm {a_spr[4:8].hex()} bas {b_spr[4:8].hex()}")
    check(a_snd[4] != 0 and b_snd[4] != 0
          and (a_snd[0] or a_snd[1]) and (b_snd[0] or b_snd[1]),
          "both are playing: voice 0 has a pitch and a volume",
          f"asm inc={a_snd[1]:02x}{a_snd[0]:02x} vol={a_snd[4]:02x}  "
          f"bas inc={b_snd[1]:02x}{b_snd[0]:02x} vol={b_snd[4]:02x}")
    check(a_snd[5] & 0x40 and b_snd[5] & 0x40,
          "and voice 0 is enabled in both",
          f"asm ctrl={a_snd[5]:02x} bas ctrl={b_snd[5]:02x}")

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
