"""Blockade on the session VM: the driver the gate and the eye use.

`Game` compiles demos/blockade.act behind its generated characters,
loads the PRG on a rendering session machine, and plays: it taps keys
through the keyboard's scancodes and reads what the program holds by
the compiler's symbol table. Run it to look:

    python sim/blockade.py [title|two|cpu|keys]

title shows the start; two plays a scripted round of two players; cpu
plays the computer against a left player who never turns; keys presses
the keys every way a person can and says which turned the head -- the
gate holds its answers. Frames go to sim/build/blk_*.png.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness as H          # noqa: E402

SOURCE = "demos/blockade.act"
ART = os.path.join(H.ROOT, "assets", "blockade", "blockade_art.act")
# make codes, up right down left: W D S A, and the cursor keys, E0-prefixed
LEFT_KEYS = [[0x1D], [0x23], [0x1B], [0x1C]]
RIGHT_KEYS = [[0xE0, 0x75], [0xE0, 0x74], [0xE0, 0x72], [0xE0, 0x6B]]
SPACE, C, ESC = [0x29], [0x21], [0x76]
FX, FY = 4, 1                                    # the field's corner on the map


def sources():
    """The files that compile the game, or None without the art."""
    if not os.path.exists(ART):
        return None
    return H.act_sources(SOURCE)


class Game:
    def __init__(self, render=True, tag="blockade"):
        src = sources()
        if src is None:
            raise SystemExit("Blockade: the art is not here (assets/blockade/)")
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

    def uword(self, n, i=0):
        a = self.addr(n) + 2 * i
        return self.m.bus.mem[a] | (self.m.bus.mem[a + 1] << 8)

    def poke(self, n, v, i=0):
        self.m.bus.mem[self.addr(n) + i] = v & 0xFF

    def cell(self, x, y):
        """A field cell's tile, (x, y) on the arcade's 32 x 28."""
        return self.m.video.vram[(FY + y) * 128 + (FX + x) * 2]

    def tap(self, codes):
        self.m.kbd.feed(codes)
        self.m.run_frame(2)
        self.m.kbd.feed(codes[:-1] + [0xF0, codes[-1]])
        self.m.run_frame(1)

    def heads(self):
        return [(self.byte("px", p), self.byte("py", p), self.byte("pdir", p)) for p in range(2)]

    def playing(self, cap=600):
        """Frames until a round's loop of play runs."""
        l0 = self.uword("loops")
        for t in range(cap):
            self.m.run_frame(1)
            if self.uword("loops") != l0:
                return t + 1
        raise SystemExit("the loop of play never ran")

    def place(self, p, x, y, d):
        """A head put at (x, y) going way d, between two frames: where the
        next step goes from. What the map shows is not moved."""
        for n, v in (("px", x), ("py", y), ("pdir", d), ("pnext", d)):
            self.poke(n, v, p)
        self.poke("tn", 0, p)

    def steps_until(self, n, cap=2000):
        """Frames until the round has taken n steps, or crashed."""
        for t in range(cap):
            if self.uword("steps") >= n or self.byte("boom_t"):
                return t
            self.m.run_frame(1)
        return cap

    def png(self, name):
        path = os.path.join(H.BUILD, name + ".png")
        H.shot(self.m, path)
        return path


def open_field(g):
    """The field's inside free again as far as the game can tell; the map
    still shows what was drawn."""
    a = g.addr("occ")
    for y in range(1, 27):
        for x in range(1, 31):
            g.m.bus.mem[a + y * 32 + x] = 0


def after_step(g):
    """Frames to the end of the next step."""
    s = g.uword("steps")
    for t in range(64):
        g.m.run_frame(1)
        if g.uword("steps") != s:
            return t + 1
    raise SystemExit("no step came")


def keys(g):
    """Every way a person presses a key, from a round running: the left
    player put going right in open field and the right going left, then
    a press, and what the heads do at the steps after. For each: what,
    whether it did it, and what it did."""
    out = []

    def case():
        open_field(g)
        g.place(0, 8, 12, 1)
        g.place(1, 24, 20, 3)
        after_step(g)

    def up_after(k, burst=False):
        """Up pressed k frames into a step, held a frame -- or made and
        broken in one burst, a tap shorter than a frame."""
        case()
        g.m.run_frame(k)
        w = LEFT_KEYS[0]
        if burst:
            g.m.kbd.feed(w + [0xF0] + w)
        else:
            g.m.kbd.feed(w)
            g.m.run_frame(1)
            g.m.kbd.feed([0xF0] + w)
        after_step(g)
        return g.byte("pdir", 0)

    rate = g.byte("rate")
    ways = [up_after(k) for k in range(rate)]
    out.append(("a press at each frame of a step turns the head at the next",
                all(w == 0 for w in ways), "a step every %d frames: %s" % (rate, ways)))
    w = up_after(rate // 2, burst=True)
    out.append(("a tap shorter than a frame turns it", w == 0, "way %d" % w))
    case()                             # up, then left, from going right
    g.m.run_frame(1)
    g.tap(LEFT_KEYS[0])
    g.tap(LEFT_KEYS[3])
    after_step(g)
    w1 = g.byte("pdir", 0)
    after_step(g)
    w2 = g.byte("pdir", 0)
    out.append(("a turn and a turn again in one step both happen", (w1, w2) == (0, 3), "ways %d, %d" % (w1, w2)))
    case()
    g.m.kbd.feed(LEFT_KEYS[0] + RIGHT_KEYS[2])
    g.m.run_frame(1)
    g.m.kbd.feed([0xF0] + LEFT_KEYS[0] + [0xE0, 0xF0, RIGHT_KEYS[2][1]])
    after_step(g)
    both = (g.byte("pdir", 0), g.byte("pdir", 1))
    out.append(("both players pressing in one frame both turn", both == (0, 2), "ways %s" % (both,)))
    case()
    g.tap(LEFT_KEYS[3])
    after_step(g)
    w = g.byte("pdir", 0)
    out.append(("a press back on itself is ignored", w == 1, "way %d" % w))
    g.poke("players", 1)
    case()
    g.tap(RIGHT_KEYS[0])
    after_step(g)
    w = g.byte("pdir", 0)
    g.poke("players", 2)
    out.append(("alone against the computer, the cursor keys steer too", w == 0, "way %d" % w))
    return out


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "title"
    g = Game(tag="blk_" + what)
    print("PRG %d bytes" % (len(g.prg) - 2))
    g.m.run_frame(30)
    print(g.png("blk_title"), "heads", g.heads())
    if what == "title":
        return
    if what == "keys":
        g.tap(SPACE)
        g.playing()
        for name, ok, detail in keys(g):
            print("  %-60s %s  %s" % (name, "ok" if ok else "NO", detail))
        return
    g.tap(SPACE if what == "two" else C)
    g.m.run_frame(64)                  # the moment before they go
    if what == "two":
        # the left player turns right after four steps, the right player
        # left after six; then down and up into each other's way
        g.steps_until(4)
        g.tap(LEFT_KEYS[1])
        g.steps_until(6)
        g.tap(RIGHT_KEYS[3])
        g.steps_until(12)
        print(g.png("blk_two_turns"), "heads", g.heads(), "turn cell", g.cell(5, 9))
        g.tap(LEFT_KEYS[2])
        g.tap(RIGHT_KEYS[0])
    n = g.steps_until(10_000)
    print(g.png("blk_" + what + "_crash"), "after %d frames" % n, "heads", g.heads(),
          "steps", g.uword("steps"), "loops", g.uword("loops"))
    g.m.run_frame(95)
    print("scores", g.byte("score", 0), g.byte("score", 1), g.png("blk_" + what + "_next"))


if __name__ == "__main__":
    main()
