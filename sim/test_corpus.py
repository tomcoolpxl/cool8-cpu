#!/usr/bin/env python3
"""Run the M2 gate corpus through the reference emulator.

The register-pressure numbers only mean something if the code they
describe actually works. This assembles sw/lib.asm, sw/gfx.asm and
sw/frames.asm, then calls every routine with real inputs and checks the
results against Python.

    python sim/test_corpus.py
"""

import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8asm  # noqa: E402
import cool8emu  # noqa: E402

SENTINEL = 0xFFFF
STACK = 0x8000
fails = []


def check(name, ok, detail=""):
    if not ok:
        fails.append(f"{name}: {detail}")


def load(*sources):
    """Assemble several files into one address space."""
    bus = cool8emu.Bus()
    syms = {}
    for src in sources:
        a = cool8asm.assemble(os.path.join(ROOT, src))
        if a.errors:
            for e in a.errors:
                print(f"error: {e}", file=sys.stderr)
            sys.exit(1)
        base, img = a.image()
        bus.load(base, img)
        syms.update(a.syms)
    return bus, syms


def call(bus, addr, max_instr=3_000_000, **state):
    cpu = cool8emu.Cool8(bus)
    cpu.sp = STACK
    for k, v in state.items():
        if k.startswith("r") and len(k) == 2:
            cpu.r[int(k[1])] = v
        else:
            setattr(cpu, k, v)
    cpu._push16(SENTINEL)
    cpu.pc = addr
    n = 0
    while cpu.pc != SENTINEL and n < max_instr:
        cpu.step()
        n += 1
    if n >= max_instr:
        raise RuntimeError(f"routine at ${addr:04X} never returned")
    return cpu


def main():
    bus, S = load("sw/lib.asm", "sw/gfx.asm", "sw/frames.asm")
    rnd = random.Random(20260802)

    # ---------------------------------------------------------- blocks
    src = bytes(rnd.randrange(256) for _ in range(64))
    bus.load(0x2000, src)
    call(bus, S["memcpy"], x=0x2000, y=0x2100, r0=64)
    check("memcpy", bytes(bus.mem[0x2100:0x2140]) == src)

    call(bus, S["memset"], y=0x2200, r0=0xAB, r1=32)
    check("memset", bytes(bus.mem[0x2200:0x2220]) == b"\xAB" * 32)

    c = call(bus, S["memcmp"], x=0x2000, y=0x2100, r0=64)
    check("memcmp equal", c.r[0] == 0, c.r[0])
    bus.write(0x2110, src[0x10] ^ 0xFF)
    c = call(bus, S["memcmp"], x=0x2000, y=0x2100, r0=64)
    check("memcmp differing", c.r[0] != 0, c.r[0])
    bus.write(0x2110, src[0x10])

    # --------------------------------------------------------- strings
    bus.load(0x2300, b"hello, world\x00")
    c = call(bus, S["strlen"], x=0x2300)
    check("strlen", c.r[0] == 12, c.r[0])
    check("strlen leaves X on the NUL", c.x == 0x230C, hex(c.x))

    call(bus, S["strcpy"], x=0x2300, y=0x2400)
    check("strcpy", bytes(bus.mem[0x2400:0x240D]) == b"hello, world\x00")

    c = call(bus, S["strcmp"], x=0x2300, y=0x2400)
    check("strcmp equal", c.r[0] == 0, c.r[0])
    bus.load(0x2500, b"hello, worlZ\x00")
    c = call(bus, S["strcmp"], x=0x2300, y=0x2500)
    check("strcmp greater", c.r[0] == (ord("d") - ord("Z")), c.r[0])
    c = call(bus, S["strcmp"], x=0x2500, y=0x2300)
    check("strcmp less", c.r[0] == (ord("Z") - ord("d")) & 0xFF, c.r[0])

    # ---------------------------------------------------- 16-bit maths
    def put16(a, v):
        bus.write16(a, v & 0xFFFF)

    def get16(a):
        return bus.read16(a)

    for a, b in ((0x1234, 0x1111), (0xFFFF, 0x0001), (0x00FF, 0x0001)):
        put16(0x2600, a)
        put16(0x2610, b)
        call(bus, S["add16"], x=0x2600, y=0x2610)
        check(f"add16 {a:04X}+{b:04X}", get16(0x2600) == (a + b) & 0xFFFF,
              f"{get16(0x2600):04X}")
        put16(0x2600, a)
        call(bus, S["sub16"], x=0x2600, y=0x2610)
        check(f"sub16 {a:04X}-{b:04X}", get16(0x2600) == (a - b) & 0xFFFF,
              f"{get16(0x2600):04X}")
        put16(0x2600, a)
        call(bus, S["shl16"], x=0x2600)
        check(f"shl16 {a:04X}", get16(0x2600) == (a << 1) & 0xFFFF,
              f"{get16(0x2600):04X}")

    for a, b in ((5, 5), (5, 6), (6, 5), (0x0100, 0x00FF), (0xFFFF, 0)):
        put16(0x2600, a)
        put16(0x2610, b)
        c = call(bus, S["cmp16"], x=0x2600, y=0x2610)
        check(f"cmp16 {a:04X} vs {b:04X} Z", c.Z == (a == b))
        check(f"cmp16 {a:04X} vs {b:04X} C", c.C == (a >= b))

    bad = 0
    for _ in range(300):
        a, b = rnd.randrange(0x10000), rnd.randrange(0x10000)
        c = call(bus, S["mul16"], r0=a & 0xFF, r1=a >> 8,
                 r2=b & 0xFF, r3=b >> 8)
        got = c.r[0] | (c.r[1] << 8)
        if got != (a * b) & 0xFFFF:
            bad += 1
    check("mul16 (300 random pairs)", bad == 0, f"{bad} wrong")

    bad = 0
    for _ in range(400):
        a, b = rnd.randrange(256), rnd.randrange(1, 256)
        c = call(bus, S["div8"], r0=a, r1=b)
        if c.r[0] != a // b or c.r[1] != a % b:
            bad += 1
    check("div8 (400 random pairs)", bad == 0, f"{bad} wrong")

    # ---------------------------------------------------------- sorting
    bad = 0
    for n in (1, 2, 3, 8, 32, 64):
        data = [rnd.randrange(256) for _ in range(n)]
        bus.load(0x2700, bytes(data))
        call(bus, S["sort8"], x=0x2700, r0=n)
        if list(bus.mem[0x2700:0x2700 + n]) != sorted(data):
            bad += 1
    check("sort8 (6 array sizes)", bad == 0, f"{bad} wrong")

    # ------------------------------------------------------- formatting
    for v in (0x00, 0x0F, 0x42, 0xAB, 0xFF):
        call(bus, S["hex8"], r0=v, y=0x2800)
        got = bytes(bus.mem[0x2800:0x2802]).decode()
        check(f"hex8 ${v:02X}", got == f"{v:02X}", got)
    for v in (0, 7, 42, 99, 100, 255):
        call(bus, S["dec8"], r0=v, y=0x2810)
        got = bytes(bus.mem[0x2810:0x2813]).decode()
        check(f"dec8 {v}", got == f"{v:03d}", got)

    # ----------------------------------------------------------- macros
    c = call(bus, S["ptr_bump"], x=0x1000)
    check("addx16 macro", c.x == 0x1000 + 1000, hex(c.x))
    bus.load(S["scratch"], b"\xFF" * 32)
    call(bus, S["clear_buf"])
    check("memclr macro",
          bytes(bus.mem[S["scratch"]:S["scratch"] + 32]) == b"\x00" * 32)

    # --------------------------------------------------------- graphics
    SCREEN, STRIDE = 0xA000, 40
    for x, y in ((0, 0), (7, 0), (8, 1), (255, 199), (100, 50)):
        c = call(bus, S["pixel_addr"], r0=x, r1=y)
        want = SCREEN + y * STRIDE + (x >> 3)
        check(f"pixel_addr ({x},{y}) address", c.x == want,
              f"{c.x:04X} != {want:04X}")
        check(f"pixel_addr ({x},{y}) mask", c.r[2] == 0x80 >> (x & 7),
              f"{c.r[2]:02X}")

    for a in range(SCREEN, SCREEN + 0x2000):
        bus.mem[a] = 0
    call(bus, S["setpixel"], r0=9, r1=2)
    check("setpixel", bus.read(SCREEN + 2 * STRIDE + 1) == 0x40,
          f"{bus.read(SCREEN + 2 * STRIDE + 1):02X}")

    call(bus, S["hline"], y=0xB000, r0=10, r1=0xFF)
    check("hline", bytes(bus.mem[0xB000:0xB00A]) == b"\xFF" * 10)

    for a in range(0xB100, 0xB400):
        bus.mem[a] = 0
    call(bus, S["vline"], x=0xB100, r0=4, r1=0x01)
    check("vline", all(bus.read(0xB100 + i * STRIDE) == 0x01
                       for i in range(4)))

    sprite = bytes([0x81, 0x42, 0x24, 0x18, 0x18, 0x24, 0x42, 0x81])
    bus.load(0x2900, sprite)
    for a in range(0xB500, 0xB700):
        bus.mem[a] = 0
    call(bus, S["blit8"], x=0x2900, y=0xB500)
    check("blit8", all(bus.read(0xB500 + i * STRIDE) == sprite[i]
                       for i in range(8)))

    for i in range(8):
        bus.write(0xB600 + i * STRIDE, 0x18)
    call(bus, S["blit8_or"], x=0x2900, y=0xB600)
    check("blit8_or", all(bus.read(0xB600 + i * STRIDE) == (sprite[i] | 0x18)
                          for i in range(8)))

    mask = bytes([0x00, 0x81, 0xFF, 0x18, 0x18, 0xFF, 0x81, 0x00])
    bus.load(0x2A00, mask)
    bus.write16(S["maskptr"], 0x2A00)
    for i in range(8):
        bus.write(0xB700 + i * STRIDE, 0xF0)
    call(bus, S["blit8_mask"], x=0x2900, y=0xB700)
    check("blit8_mask",
          all(bus.read(0xB700 + i * STRIDE) == ((0xF0 & mask[i]) | sprite[i])
              for i in range(8)),
          [f"{bus.read(0xB700 + i * STRIDE):02X}" for i in range(8)])

    for i in range(200 * STRIDE):
        bus.mem[SCREEN + i] = i & 0xFF
    call(bus, S["scroll_up"])
    moved = 24 * STRIDE * 8
    check("scroll_up",
          all(bus.read(SCREEN + i) == ((i + STRIDE * 8) & 0xFF)
              for i in range(0, moved, 37)))

    call(bus, S["clear_screen"], r0=0x5A)
    check("clear_screen",
          all(bus.read(SCREEN + i) == 0x5A
              for i in range(0, 25 * STRIDE * 8, 41)))

    # ------------------------------------------------- compiler frames
    def cdecl(name, *args):
        cpu = cool8emu.Cool8(bus)
        cpu.sp = STACK
        for a in reversed(args):
            cpu._push(a & 0xFF)
        cpu._push16(SENTINEL)
        cpu.pc = S[name]
        n = 0
        while cpu.pc != SENTINEL and n < 500_000:
            cpu.step()
            n += 1
        return cpu.r[0]

    check("sum3(1,2,3)", cdecl("sum3", 1, 2, 3) == 6, cdecl("sum3", 1, 2, 3))
    check("sum3(100,100,55)", cdecl("sum3", 100, 100, 55) == 255)
    for x in (0, 3, 5, 16):
        want = ((x * x) & 0xFF) + x
        want = (want + 3) & 0xFF
        check(f"poly({x})", cdecl("poly", x) == want,
              f"{cdecl('poly', x)} != {want}")
    for n in (1, 4, 10):
        p = ((n * n) & 0xFF) + n
        p = (p + 3) & 0xFF
        want = (n + p + 1) & 0xFF
        check(f"outer({n})", cdecl("outer", n) == want,
              f"{cdecl('outer', n)} != {want}")

    arr = bytes(rnd.randrange(256) for _ in range(20))
    bus.load(0x2B00, arr)
    got = cdecl("sum_array", 0x00, 0x2B, 20)
    check("sum_array", got == sum(arr) & 0xFF, f"{got} != {sum(arr) & 0xFF}")

    check("depth4 chain", cdecl("depth4", 0) == 10, cdecl("depth4", 0))

    print(f"corpus: {len(fails)} failure(s)")
    for f in fails:
        print("  FAIL", f)
    return not fails


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
