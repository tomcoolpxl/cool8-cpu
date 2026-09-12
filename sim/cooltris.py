"""COOLTRIS on the session VM: the driver the gate and the eye use.

`Game` compiles demos/cooltris.act behind its generated art, loads the
PRG on a rendering session machine, and plays: it taps keys through the
keyboard's scancodes and reads what the program holds by the compiler's
symbol table. Run it to look:

    python sim/cooltris.py [title|play|rows|level]

title shows the front; play drops a few pieces; rows fills the well but
for one column and clears four at once; level pokes the count up so the
surround changes. Frames go to sim/build/cool_*.png.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness as H          # noqa: E402

SOURCE = "demos/cooltris.act"
ART = os.path.join(H.ROOT, "assets", "cooltris", "cooltris_art.act")
# make codes: the cursor keys are E0-prefixed
LEFT, RIGHT, DOWN, UP = [0xE0, 0x6B], [0xE0, 0x74], [0xE0, 0x72], [0xE0, 0x75]
Z, X, C_HOLD, M_DROP = [0x1A], [0x22], [0x21], [0x3A]
P, SPACE, ESC = [0x4D], [0x29], [0x76]
WX, WY = 15, 5                                   # the well's corner on the map
GLYPHS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-.!/ "   # the font's order


def sources():
    """The files that compile the game, or None without the art."""
    if not os.path.exists(ART):
        return None
    return H.act_sources(SOURCE)


class Game:
    def __init__(self, render=True, tag="cooltris"):
        src = sources()
        if src is None:
            raise SystemExit("COOLTRIS: the art is not here (assets/cooltris/)")
        prg, syms = H.try_build_act(src, tag)
        if prg is None:
            raise SystemExit("compile failed:\n" + syms)
        self.prg, self.syms = prg, syms
        self.m = H.session(render=render)
        self.org, self.end = H.load_act(self.m, prg)

    def c(self, n):
        return self.syms["c_" + n]

    def addr(self, n):
        return self.syms["v_" + n]

    def byte(self, n, i=0):
        return self.m.bus.mem[self.addr(n) + i]

    def word(self, n, i=0):
        a = self.addr(n) + 2 * i
        v = self.m.bus.mem[a] | (self.m.bus.mem[a + 1] << 8)
        return v - 65536 if v >= 32768 else v

    def uword(self, n, i=0):
        a = self.addr(n) + 2 * i
        return self.m.bus.mem[a] | (self.m.bus.mem[a + 1] << 8)

    def poke(self, n, v, i=0):
        self.m.bus.mem[self.addr(n) + i] = v & 0xFF

    def pokew(self, n, v, i=0):
        """A two-byte one: cx, cy and gy are INTs."""
        a = self.addr(n) + 2 * i
        self.m.bus.mem[a] = v & 0xFF
        self.m.bus.mem[a + 1] = (v >> 8) & 0xFF

    def cell(self, col, row):
        """A map cell: (tile, attribute)."""
        a = row * 128 + col * 2
        v = self.m.video.vram[a:a + 2]
        return v[0], v[1]

    def well(self, x, y):
        """What the game holds in the well's cell, 0 empty."""
        return self.byte("well", y * 10 + x)

    def score(self):
        """The seven digits as a number."""
        return sum(self.byte("dig", i) * 10 ** i for i in range(7))

    def piece(self):
        return (self.byte("cur"), self.byte("rot"), self.word("cx"), self.word("cy"), self.word("gy"))

    def tap(self, codes, frames=2):
        self.m.kbd.feed(codes)
        self.m.run_frame(frames)
        self.m.kbd.feed(codes[:-1] + [0xF0, codes[-1]])
        self.m.run_frame(1)

    def hold(self, codes, frames):
        self.m.kbd.feed(codes)
        self.m.run_frame(frames)
        self.m.kbd.feed(codes[:-1] + [0xF0, codes[-1]])
        self.m.run_frame(1)

    def playing(self, cap=600):
        """Frames until the loop of play runs."""
        l0 = self.uword("loops")
        for t in range(cap):
            self.m.run_frame(1)
            if self.uword("loops") != l0:
                return t + 1
        raise SystemExit("the loop of play never ran")

    def start(self):
        """Through the title into a game."""
        self.m.run_frame(30)
        self.tap(SPACE)
        return self.playing()

    def landed(self, cap=2000):
        """Frames until the piece now falling locks: any entry delay left
        over from the piece before is waited out first."""
        for _ in range(cap):
            if self.byte("are_t") == 0:
                break
            self.m.run_frame(1)
        for t in range(cap):
            self.m.run_frame(1)
            if self.byte("are_t"):
                return t + 1
        return cap

    def fresh(self, cap=600):
        """Frames until a piece has just come in, at the top of the well."""
        for t in range(cap):
            self.m.run_frame(1)
            if self.byte("are_t") == 0 and self.word("cy") <= 0:
                return t + 1
        raise SystemExit("no piece came in")

    def fill(self, rows, gap=9):
        """The well's bottom `rows` rows filled but for one column, as if
        played there: the game's own array, and the screen redrawn by the
        next thing that draws it."""
        for y in range(20 - rows, 20):
            for x in range(10):
                self.m.bus.mem[self.addr("well") + y * 10 + x] = 0 if x == gap else 1 + (x % 7)

    def png(self, name):
        path = os.path.join(H.BUILD, name + ".png")
        H.shot(self.m, path)
        return path


def four_rows(g, lo=0, hi=0, lv=0):
    """Four rows at once: the counts poked so that the clear lands the
    game on the level wanted, the well filled but for its last column,
    and the piece just come in made an I stood on end over that column."""
    g.poke("lines_lo", lo)
    g.poke("lines_hi", hi)
    g.poke("level", lv)
    g.fill(4)
    g.fresh()
    g.poke("cur", 0)
    g.poke("rot", 1)
    g.pokew("cx", 7)
    g.pokew("cy", 0)
    g.pokew("gy", 0)                   # the ghost too, or the old one is erased
    g.hold(DOWN, 90)
    g.m.run_frame(90)


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "title"
    g = Game(tag="cool_" + what)
    print("PRG %d bytes" % (len(g.prg) - 2))
    g.m.run_frame(40)
    print(g.png("cool_title"))
    if what == "title":
        return
    g.tap(SPACE)
    g.playing()
    if what == "level":
        # the level is only repainted when a clear raises it, so raise it
        four_rows(g, lo=86, lv=8)
        print(g.png("cool_level10"), "level", g.byte("level") + 1)
        four_rows(g, lo=96, hi=1, lv=18)
        print(g.png("cool_level20"), "level", g.byte("level") + 1)
        return
    if what == "name":
        # the well filled but for one column, so the next shape will not
        # fit, and a score past the ten thousand it starts with: the game
        # ends and asks for three letters
        for y in range(20):
            for x in range(1, 10):
                g.m.bus.mem[g.addr("well") + y * 10 + x] = 1
        for i, d in enumerate([0, 0, 0, 5, 3, 0, 0]):
            g.poke("dig", d, i)
        over = 0
        want = g.c("T_FONT") + GLYPHS.index("G")   # the words, not the filling
        for t in range(400):
            g.m.run_frame(1)
            if g.cell(16, 14)[0] == want:
                over = t
                break
        g.m.run_frame(10)
        show = lambda: "%s cell %s" % ("".join(chr(g.byte("topname", i)) for i in range(3)), g.cell(33, 21))
        print("  game over after %d frames: %s" % (over, show()))
        for keys, said in ((UP, "up"), (UP, "up"), (RIGHT, "right"), (SPACE, "space")):
            g.tap(keys)
            g.m.run_frame(5)
            print("  after %-6s %s" % (said, show()))
        print(g.png("cool_name"), "score", g.score(), "best", sum(g.byte("top", i) * 10 ** i for i in range(7)))
        return
    if what == "rows":
        four_rows(g)
        print(g.png("cool_rows"), "score", g.score(), "rows", g.byte("lines_lo"), "level", g.byte("level") + 1)
        return
    for i in range(4):
        g.m.kbd.feed(DOWN)             # held down until it lands
        n = g.landed()
        g.m.kbd.feed([0xE0, 0xF0, 0x72])
        print("  piece %d soft dropped and landed after %d frames: %s" % (i, n, g.piece()))
        g.fresh()
    print(g.png("cool_play"), "score", g.score(), "rows", g.byte("lines_lo"),
          "loops", g.uword("loops"))


if __name__ == "__main__":
    main()
