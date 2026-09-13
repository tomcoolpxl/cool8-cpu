"""GALAGA on the session VM: the driver the gate and the eye use.

`Game` compiles demos/galaga.act behind its generated art, makes a flash
image with GALAGA.DAT on drive 11 -- where the demos disc puts it, and
where the game looks -- loads the PRG on a rendering session machine with
that flash, and plays: it holds and taps keys through the keyboard's
scancodes, and reads what the program holds by the compiler's symbol
table. Run it to look:

    python sim/galaga.py [MODE]

MODE is play, which writes frames to sim/build/gal_*.png, or profile,
which measures the work in every frame -- the clocks that are not
WaitVBlank's -- and says where the busiest frame's went.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness as H          # noqa: E402

SOURCE = "demos/galaga.act"
DAT = os.path.join(H.ROOT, "assets", "galaga", "GALAGA.DAT")
FRAME = 139_583              # clocks in a frame (docs/14-demos.md)
# make and break codes: the cursor keys are E0-prefixed
LEFT, RIGHT, SPACE, ESC = [0xE0, 0x6B], [0xE0, 0x74], [0x29], [0x76]


def sources():
    """The files that compile the game, or None without the art."""
    if not os.path.exists(DAT):
        return None
    return H.act_sources(SOURCE)


def flash_image(name="galaga"):
    """A formatted flash with the data file on drive 11."""
    import cool8disk as disk
    img = os.path.join(H.BUILD, name + ".img")
    disk.make_image(img)
    im = disk.Image(img)
    vol = disk.Volume(im, disk.ACTION_VOL)
    vol.add(DAT, os.path.basename(DAT))
    im.save()
    return img


class Game:
    def __init__(self, render=True, tag="galaga"):
        """`tag` names the build and the flash image in sim/build, so that
        runs side by side do not write over each other's."""
        src = sources()
        if src is None:
            raise SystemExit("GALAGA: the art is not here (assets/galaga/)")
        prg, syms = H.try_build_act(src, tag)
        if prg is None:
            raise SystemExit("compile failed:\n" + syms)
        self.prg, self.syms = prg, syms
        self.m = H.session(render=render, flash_path=flash_image(tag))
        self.org, self.end = H.load_act(self.m, prg)

    # ------------------------------------------------------- the program
    def addr(self, n):
        return self.syms["v_" + n]

    def c(self, n):
        return self.syms["c_" + n]

    def byte(self, n, i=0):
        return self.m.bus.mem[self.addr(n) + i]

    def word(self, n, i=0):
        v = self.uword(n, i)
        return v - 65536 if v >= 32768 else v

    def uword(self, n, i=0):
        a = self.addr(n) + 2 * i
        return self.m.bus.mem[a] | (self.m.bus.mem[a + 1] << 8)

    def poke(self, n, v, i=0):
        self.m.bus.mem[self.addr(n) + i] = v & 0xFF

    def pokew(self, n, v, i=0):
        a = self.addr(n) + 2 * i
        self.m.bus.mem[a] = v & 0xFF
        self.m.bus.mem[a + 1] = (v >> 8) & 0xFF

    # ----------------------------------------------------------- playing
    def hold(self, codes, frames):
        """A key held for so many frames, then let go."""
        self.m.kbd.feed(codes)
        self.m.run_frame(frames)
        self.m.kbd.feed(codes[:-1] + [0xF0, codes[-1]])
        self.m.run_frame(1)

    def tap(self, codes):
        self.hold(codes, 2)

    def until(self, pred, cap=600):
        for t in range(cap):
            if pred():
                return t
            self.m.run_frame(1)
        return None

    def frame_work(self, frames):
        """The clocks each of so many frames spent on something other than
        waiting for the next, and the profile of the busiest."""
        import dbg
        worst, costs = None, []
        for _ in range(frames):
            p = dbg.Profile(self.syms, self.org, self.end)
            p.start(self.m)
            self.m.run_frame(1)
            p.collect(self.m)
            work = p.total - p.of("WaitVBlank")
            costs.append(work)
            if worst is None or work > worst[0]:
                worst = (work, p)
        return costs, worst

    # ----------------------------------------------------------- the bitmap
    def pixel(self, x, y):
        """A pixel of the mode 4 bitmap: 160 bytes a row, two to a byte,
        the left one in the high nibble."""
        b = self.m.video.vram[y * 160 + (x >> 1)]
        return b >> 4 if x % 2 == 0 else b & 15

    def at_rest(self):
        """Run on to the loop's next WaitVBlank, where the frame's drawing is
        done: a frame boundary lands wherever the program is, mid-list
        included."""
        a = self.syms["WaitVBlank"]
        self.m.breakpoints.add(a)
        try:
            why = self.m.run(budget=2_000_000)
        finally:
            self.m.breakpoints.discard(a)
        assert why == "breakpoint", why

    def bitmap_diff(self):
        """The field's pixels that are not what the program's own state says
        should be there -- each character at rest drawn where its slot says
        it is drawn, each star it says is lit -- as (x, y, have, want); an
        empty list is a bitmap no list left a pixel behind in."""
        import mkgalaga as A
        if not hasattr(self, "_fimgs"):
            s = A.Sheet("sprites")
            self._fimgs = [A.grid_cell(s, c, A.ROWS[n]) for n, c in A.FORMATION]
        fx = self.c("FX")
        want = {}
        for i in range(self.c("NSLOT")):
            if self.byte("sl_on", i):
                img = self._fimgs[self.byte("sl_fr", i)]
                x0, y0 = fx + self.byte("sl_x", i), self.byte("sl_y", i)
                for y in range(16):
                    for x in range(16):
                        if img[y][x]:
                            want[(x0 + x, y0 + y)] = img[y][x]
        for i in range(self.c("NSTAR")):
            if self.byte("st_on", i):
                p = (fx + self.byte("st_x", i), self.byte("st_y", i))
                assert p not in want, "star %d lit on a character's pixel %s" % (i, p)
                want[p] = self.byte("st_c", i)
        out = []
        for y in range(240):
            for x in range(fx, fx + self.c("FW")):
                have = self.pixel(x, y)
                if have != want.get((x, y), 0):
                    out.append((x, y, have, want.get((x, y), 0)))
        return out

    def png(self, name):
        path = os.path.join(H.BUILD, name + ".png")
        H.shot(self.m, path)
        return path


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "play"
    g = Game(tag="gal_" + what)
    print("PRG %d bytes, %04X-%04X" % (len(g.prg) - 2, g.org, g.end))
    g.m.run_frame(30)
    print(g.png("gal_start"), "loops", g.uword("loops"))
    if what == "play":
        for i in range(4):
            g.m.run_frame(60)
            print(g.png("gal_play%d" % i), "loops", g.uword("loops"), "frames", g.m.frames)
    elif what == "bitmap":
        for i in range(12):
            g.m.run_frame(37)
            g.at_rest()
            d = g.bitmap_diff()
            print("after %4d frames: %d pixels differ %s" % (g.m.frames, len(d), d[:6]))
    elif what == "profile":
        costs, (work, p) = g.frame_work(240)
        print("work per frame over %d frames: mean %d, max %d clocks (%.0f%% of a frame)"
              % (len(costs), sum(costs) // len(costs), max(costs), 100 * max(costs) / FRAME))
        print("the frames, in thousands of clocks:")
        for i in range(0, len(costs), 24):
            print("  " + " ".join("%3d" % (c // 1000) for c in costs[i:i + 24]))
        print("the busiest frame:")
        print(p.report(top=12))


if __name__ == "__main__":
    main()
