#!/usr/bin/env python3
"""The machine against the hardware, pixel for pixel and sample for
sample.

The machine (rust/, RUST_PORT.md) is only worth writing an operating
system against if it agrees with the gates. This is the check that says
so, and it is not a self-check: every expected value here came out of a
Verilog simulation of the RTL.

  video   `sim/test_video.py` dumps two frames as the DUT's own pixels
          leave it — build/text.hex (mode 0) and build/tiles.hex (mode
          2). The stimulus that produced them is replayed here through
          the machine's registers and VRAM, rendered by its own
          scanline renderer, and all 307,200 pixels must match.

  sound   `sim/test_snd.py` dumps 4096 level bytes from the running
          engine — a five-note chord at unrelated pitches, a silent
          voice, a stopped voice and noise. The machine's sound engine
          must produce the identical stream.

  machine the ROM boots, the monitor answers, and `D F000` returns the
          bytes the board returned over its serial port.

    python sim/test_vm.py
    python sim/test_vm.py --regen        # re-run the RTL suites first

**Why replay the stimulus rather than share it.** The frames could have
been produced by asking the machine to render whatever the testbench
happened to set up, which would make this a test of the renderer against
itself. Writing the setup out twice — once in Verilog, once here — means
a misunderstanding of what the registers mean has to be made twice,
identically, to go unnoticed.

Set OSS_CAD_SUITE to the toolchain root if the frames need regenerating.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")
SHARED = os.path.join(HERE, "build")


def golden(name):
    """An RTL dump, wherever the suite that made it put it.

    `sim/test_video.py` and `sim/test_snd.py` produce these, and under
    the runner every job has its own COOL8_BUILD — so the dumps land in
    a sibling directory, not in this job's. Look in this job's build
    first, then the shared one, then any job's.
    """
    import glob
    for cand in ([os.path.join(BUILD, name), os.path.join(SHARED, name)]
                 + sorted(glob.glob(os.path.join(SHARED, "jobs", "*", name)))):
        if os.path.exists(cand):
            return cand
    return None

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8rsvm as vm                           # noqa: E402
import mkfont                                    # noqa: E402

H_VIS, V_VIS = 640, 480
COLS, ROWS = 80, 30


# ====================================================== the stimulus
#
# A transcription of sim/tb/cool8_video_tb.v's setup tasks. The names
# match so the two can be read side by side.

def put_pal(m):
    """The sixteen CGA colours, then a ramp so the deeper modes have
    something to be wrong about."""
    cga = [(0, 0, 0), (0, 0, 0xA), (0, 0xA, 0), (0, 0xA, 0xA),
           (0xA, 0, 0), (0xA, 0, 0xA), (0xA, 5, 0), (0xA, 0xA, 0xA),
           (5, 5, 5), (5, 5, 0xF), (5, 0xF, 5), (5, 0xF, 0xF),
           (0xF, 5, 5), (0xF, 5, 0xF), (0xF, 0xF, 5), (0xF, 0xF, 0xF)]
    for e, (r, g, b) in enumerate(cga):
        m.io_write(0x1E, e)
        m.io_write(0x1F, r)
        m.io_write(0x1F, (g << 4) | b)
    for k in range(16, 256):
        r, g, b = k & 0xF, (k >> 4) & 0xF, ((k >> 2) & 0xF) ^ 0x9
        m.io_write(0x1E, k)
        m.io_write(0x1F, r)
        m.io_write(0x1F, (g << 4) | b)


def set_mode(m, mode):
    m.io_write(0x10, 0x80 | mode)


def set_scroll(m, sx, sy):
    m.io_write(0x16, sx & 0xFF)
    m.io_write(0x17, (sx >> 8) & 3)
    m.io_write(0x18, sy & 0xFF)
    m.io_write(0x19, (sy >> 8) & 3)


def no_sprites(m):
    for i in range(32):
        m.io_write(0x2A, i << 3)
        for _ in range(8):
            m.io_write(0x2B, 0x00)
    m.io_write(0x2C, 0x00)


def build_screen():
    """The same screen cool8_text_tb built: a box, four strings, two
    colour bars, the whole 256-glyph set, and a shade ramp."""
    scr = [0x0720] * (COLS * ROWS)

    scr[0] = 0x0FC9
    scr[COLS - 1] = 0x0FBB
    scr[4 * COLS] = 0x0FC8
    scr[4 * COLS + COLS - 1] = 0x0FBC
    for k in range(1, COLS - 1):
        scr[k] = 0x0FCD
        scr[4 * COLS + k] = 0x0FCD
    for k in range(1, 4):
        scr[k * COLS] = 0x0FBA
        scr[k * COLS + COLS - 1] = 0x0FBA

    def put_str(row, col, s, attr):
        for n, ch in enumerate(s):
            if col + n < COLS:
                scr[row * COLS + col + n] = (attr << 8) | ord(ch)

    put_str(1, 3, "COOL8", 0x0E)
    put_str(1, 9, "text mode 0 - 80x30 cells of 8x16", 0x0B)
    put_str(2, 3, "the font is real, the raster is real,", 0x07)
    put_str(3, 3, "and this frame came out of a simulator", 0x08)

    for k in range(16):
        for j in range(4):
            scr[6 * COLS + 3 + k * 4 + j] = (k << 8) | 0xDB
    for k in range(16):
        for j in range(4):
            scr[7 * COLS + 3 + k * 4 + j] = (k << 12) | 0x20

    for k in range(256):
        scr[(10 + k // 16) * COLS + 3 + (k % 16) * 3] = 0x0A00 | k

    for k in range(64):
        shade = {0: 0xB0, 1: 0xB1, 2: 0xB2}.get(k & 3, 0xDB)
        scr[27 * COLS + 8 + k] = (((k >> 2) & 0xF) << 8) | 0xDB
        scr[28 * COLS + 8 + k] = (((k >> 2) & 0xF) << 8) | shade
    return scr


def load_text_map(m, scr):
    """80 cells of char and attribute a row, which is the stride the
    mode 0 preset loads.

    **The pitch is asked of the machine, not written down.** This said
    `j * 256`, D30's 128-cell map, and it was a fourth copy of a number
    that also lived in cool8_vregs.v, cool8_video_tb.v and
    sw/console.asm — so when the map stopped being 256 bytes a row this
    filled one layout and the display read another, 59,980 pixels
    apart.
    """
    stride = m.bus.read(0xFF14) | (m.bus.read(0xFF15) << 8)
    base = m.bus.read(0xFF12) | (m.bus.read(0xFF13) << 8)
    for i in range(0x10000):
        m.bus.mem[i] = 0x00
    for j in range(ROWS):
        for k in range(COLS):
            c = scr[j * COLS + k]
            m.bus.mem[base + j * stride + k * 2] = c & 0xFF
            m.bus.mem[base + j * stride + k * 2 + 1] = c >> 8


class Vram:
    """VRAM built locally, then pushed in one go.

    The engine sees words; this collects them and hands the machine a
    whole 64 KB at once, because a round trip per word would be 32,768
    of them.
    """

    def __init__(self):
        self.buf = bytearray(0x10000)

    def put(self, wa, d):
        self.buf[(wa * 2) & 0xFFFF] = d & 0xFF
        self.buf[(wa * 2 + 1) & 0xFFFF] = (d >> 8) & 0xFF

    def flush(self, m):
        m.video.vram[0:0x10000] = self.buf


def load_tiles(m, v):
    """A map of 64 columns at stride 128 with every attribute
    combination, and patterns that are not symmetric so a flip that does
    nothing is visible."""
    m.io_write(0x20, 0x00)
    m.io_write(0x21, 0x40)                  # patterns at $4000
    for j in range(32):
        for k in range(64):
            # {j[3:0]^k[3:0], k[5:0]+j[5:0], 2'b00} is twelve bits wide,
            # so it zero-extends before the XOR with {k[7:0], j[7:0]}.
            w = ((((j ^ k) & 0xF) << 8) | ((((k + j) & 0x3F)) << 2))
            v.put((j * 128 + k * 2) >> 1,
                  (w ^ (((k & 0xFF) << 8) | (j & 0xFF))) & 0xFFFF)
    for k in range(4096):
        v.put(0x2000 + k,
                 (((k & 0xF) << 12) | ((((k >> 4) & 0xFF) ^ 0x6D) << 4) |
                  ((k >> 4) & 0xF)) & 0xFFFF)


# ============================================================ the checks

def read_hex(path):
    with open(path) as fh:
        return [int(line, 16) for line in fh if line.strip()]


def frame_check(name, dump, setup):
    path = golden(dump)
    if path is None:
        print(f"  {name:<28} build/{dump} missing{'':<12} MISSING")
        return None
    want = read_hex(path)
    if len(want) != H_VIS * V_VIS:
        print(f"  {name:<28} {len(want)} pixels, want {H_VIS * V_VIS}"
              f"{'':<6} FAIL")
        return False

    m = vm.Machine(font=font_bytes(), render=True)
    v = Vram()
    setup(m, v)
    v.flush(m)

    # The renderer draws as the raster runs, so the frame has to be
    # scanned out before it can be read. The CPU is halted for it: RAM
    # holds the text map and nothing should be executing over it. Two
    # frames, because the first may be joined part-way.
    m.cpu.halted = True
    m.run_frame(2)
    got = m.fb()

    bad = 0
    first = None
    for i, (g, w) in enumerate(zip(got, want)):
        if g != w:
            if first is None:
                first = (i % H_VIS, i // H_VIS, g, w)
            bad += 1
    detail = f"{len(want)} pixels, {bad} wrong"
    print(f"  {name:<28} {detail:<28} {'ok' if bad == 0 else 'FAIL'}")
    if first:
        x, y, g, w = first
        print(f"    first at ({x},{y}): got {g:03x} want {w:03x}")
    return bad == 0


def font_bytes():
    """The machine's font, for the renderer — text mode needs glyphs."""
    font, _, _ = mkfont.build(os.path.join(ROOT, 'assets', 'font',
                                           'spleen-8x16.bdf'))
    return font


def fill_vram_bitmap(m, v):
    """What the bitmap phases leave behind, and the tile phase inherits.

    Pattern banks 1..3 are never written by the tile setup, so what a
    cell with attribute bits $10..$30 draws is this fill. Leaving it out
    gave a frame that was wrong in three quarters of its tiles — which
    is the emulator being right about a VRAM that was not the same one.
    """
    for k in range(32768):
        # {k[7:0] ^ 8'h5A, k[15:8] + 8'h37} — the XOR is the *high* byte.
        v.put(k, (((k & 0xFF) ^ 0x5A) << 8) |
                       (((k >> 8) + 0x37) & 0xFF))


def setup_text(m, v):
    put_pal(m)
    no_sprites(m)
    set_mode(m, 0)
    load_text_map(m, build_screen())


def setup_cursor(m, v):
    """Phase 3 of cool8_video_tb: the text screen, scrolled, with the
    hardware cursor mid-screen.

    **The cursor was the one part of the pixel path this gate never
    rendered**, so when [D81] found `d1_trow` choosing its divisor on the
    line doubler, `render.rs` was making the identical mistake and the
    two models agreed all the way to the screen. Cosim compares
    instructions and this compares pixels; neither could see a cell
    nothing drew.

    Rate 3 is the solid cursor, which is the only one a frame comparison
    can predict without modelling the blink counter.
    """
    put_pal(m)
    no_sprites(m)
    set_mode(m, 0)
    load_text_map(m, build_screen())
    set_scroll(m, 0, 5)
    m.io_write(0x22, 40)                    # CUR_X
    m.io_write(0x23, 12)                    # CUR_Y
    m.io_write(0x24, 0b11001)               # CUR_CTRL: rate 3, on


def put_spr(m, i, en, big, hf, vf, bh, x, y, pat, bank):
    m.io_write(0x2A, i << 3)
    m.io_write(0x2B, y & 0xFF)
    m.io_write(0x2B, (big << 7) | (en << 6) | ((y >> 8) & 1))
    m.io_write(0x2B, x & 0xFF)
    m.io_write(0x2B, (x >> 8) & 3)
    m.io_write(0x2B, (pat >> 5) & 0xFF)
    m.io_write(0x2B, (pat >> 13) & 7)
    m.io_write(0x2B, (vf << 7) | (hf << 6) | (bh << 5))
    m.io_write(0x2B, bank)                  # per-sprite, and never used


def load_sprite_patterns(m, v):
    """Every pattern asymmetric in both directions, so a flip taken from
    the wrong bit shows up as a wrong pixel rather than a symmetry."""
    for k in range(2048):
        v.put(0x3000 + k,
                 ((((k & 0xF) + 1) & 0xF) << 12) |
                 (((((k >> 4) & 0xF) ^ 6) & 0xF) << 8) |
                 (((((k >> 8) & 0xF) + 3) & 0xF) << 4) |
                 ((((k >> 2) & 0xF) ^ 0xA) & 0xF))


def setup_tiles(m, v):
    put_pal(m)
    no_sprites(m)
    fill_vram_bitmap(m, v)
    m.io_write(0x1A, 0x2B)                  # the border the bitmap phases set
    set_mode(m, 2)
    load_tiles(m, v)
    set_scroll(m, 0, 0)


def setup_sprites(m, v):
    """Phase 13: eleven sprites over a 4 bpp bitmap.

    The background is whatever the earlier phases left in VRAM — the
    bitmap fill with the tile map and the tile patterns written over
    parts of it — so all of that history is replayed before the sprites
    go on top. Eight overlap in pairs so priority shows, both sizes are
    present, every flip is used, two are behind the background, and
    three hang off the left, right and bottom edges.
    """
    put_pal(m)
    no_sprites(m)
    fill_vram_bitmap(m, v)
    m.io_write(0x1A, 0x2B)
    set_mode(m, 2)
    load_tiles(m, v)
    load_sprite_patterns(m, v)

    set_mode(m, 4)
    m.io_write(0x12, 0x00)
    m.io_write(0x13, 0x00)                  # base $0000
    set_scroll(m, 0, 0)
    # Bank $5, so the shared bank is carried rather than passing by being
    # zero. Every descriptor sets a different per-sprite bank and none of
    # them shows.
    m.io_write(0x2C, 0x51)

    put_spr(m, 0,  1, 1, 0, 0, 0, 40,   60,  0x6000, 0x1)
    put_spr(m, 1,  1, 1, 1, 0, 0, 48,   60,  0x6080, 0x2)
    put_spr(m, 2,  1, 1, 0, 1, 0, 100,  60,  0x6100, 0x3)
    put_spr(m, 3,  1, 1, 1, 1, 1, 108,  60,  0x6180, 0x4)
    put_spr(m, 4,  1, 0, 0, 0, 0, 200,  62,  0x6200, 0x5)
    put_spr(m, 5,  1, 0, 1, 0, 0, 204,  62,  0x6220, 0x6)
    put_spr(m, 6,  1, 0, 0, 1, 1, 300,  64,  0x6240, 0x7)
    put_spr(m, 7,  1, 1, 0, 0, 0, 400,  58,  0x6260, 0x8)
    put_spr(m, 8,  1, 1, 0, 0, 0, 1016, 200, 0x6300, 0x9)
    put_spr(m, 9,  1, 1, 0, 0, 0, 632,  200, 0x6380, 0xA)
    put_spr(m, 10, 1, 1, 0, 0, 0, 300,  472, 0x6400, 0xB)


def sound_check():
    path = golden("snd.hex")
    if path is None:
        print(f"  {'the sound engine':<28} build/snd.hex missing"
              f"{'':<11} MISSING")
        return None
    want = read_hex(path)

    m = vm.Machine()
    m.cpu.halted = True                     # the engine, not a program

    def set_voice(v, inc, en, noise, vol):
        m.io_write(0x50, v << 3)
        m.io_writes(0x51, [inc & 0xFF, inc >> 8])
        m.io_write(0x50, (v << 3) | 4)
        m.io_writes(0x51, [vol, (noise << 7) | (en << 6)])

    set_voice(0, 881,   1, 0, 15)
    set_voice(1, 1109,  1, 0, 10)
    set_voice(2, 1319,  1, 0, 7)
    set_voice(3, 37,    1, 0, 3)
    set_voice(4, 20000, 1, 0, 4)
    set_voice(5, 500,   0, 0, 15)
    set_voice(6, 0,     1, 0, 9)
    set_voice(7, 3000,  1, 1, 12)

    # The engine makes a sample every 256 system clocks, so run the
    # machine until it has produced as many as the RTL dumped.
    m.samples()                             # drop anything from setup
    got = []
    while len(got) < len(want):
        m.run(cycles=256 * (len(want) - len(got)))
        got += list(m.samples())
    got = got[:len(want)]
    bad = sum(1 for g, w in zip(got, want) if g != w)
    ok = bad == 0
    detail = f"{len(want)} samples, {bad} wrong"
    print(f"  {'the sound engine':<28} {detail:<28} "
          f"{'ok' if ok else 'FAIL'}")
    if not ok:
        for i, (g, w) in enumerate(zip(got, want)):
            if g != w:
                print(f"    first at sample {i}: got {g:02x} want {w:02x}")
                break
    return ok


def machine_check():
    """The boot path, and the answer the board itself gave."""
    m = vm.boot()
    txt = vm.converse(m, "D F000\\r", frames=20)
    ok = "COOL8" in txt and "2F 60 00 02" in txt.upper()
    detail = "boots, prompts, dumps the ROM"
    print(f"  {'the whole machine':<28} {detail:<28} "
          f"{'ok' if ok else 'FAIL'}")
    if not ok:
        print("    " + repr(txt[-200:]))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regen", action="store_true",
                    help="re-run the RTL suites that write the golden files")
    args = ap.parse_args()

    if args.regen:
        for suite in ("test_video.py", "test_snd.py"):
            print(f"  regenerating with sim/{suite} ...")
            subprocess.run([sys.executable, os.path.join(HERE, suite)],
                           check=False)

    results = [
        machine_check(),
        frame_check("mode 0 text, 80x30",
                    "text.hex", setup_text),
        frame_check("mode 2 tiles, 40x30",
                    "tiles.hex", setup_tiles),
        frame_check("11 sprites over a bitmap",
                    "sprites.hex", setup_sprites),
        frame_check("text with the hardware cursor",
                    "cursor.hex", setup_cursor),
        sound_check(),
    ]

    ran = [r for r in results if r is not None]
    ok = bool(ran) and all(ran)
    if len(ran) != len(results):
        print("\n  (run sim/test_vm.py --regen to produce the missing "
              "golden files)")
    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
