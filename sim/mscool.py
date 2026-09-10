"""Ms. Cool-Man on the session VM: the driver the gate and the eye use.

`Game` compiles demos/mscoolman.act behind its private art, loads it
on a rendering session machine, and plays it: an autopilot pokes her
`want` every frame, so a test can walk her to a pill, at a blue ghost
or into a red one, and read back what the program holds -- positions,
states, the score, the maze -- by the compiler's symbol table. The
gate in test_action.py is built on it; run this file to look:

    python sim/mscool.py [title|pill|death|clear|fruit]

writes the frames to sim/build/ms_*.png. The art is not in the
repository (assets/misscool/ is ignored), so both say so and stop
when it is absent rather than fail.
"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness as H          # noqa: E402

SOURCE = "demos/mscoolman.act"
STEP = {0: (1, 0), 1: (-1, 0), 2: (0, -1), 3: (0, 1)}
K_WALL, K_PATH, K_DOT, K_PILL, K_DOOR, K_HOUSE = range(6)
HER, BLINKY, PINKY, INKY, SUE, FRUIT = range(6)
G_HOME, G_LEAVE, G_OUT, G_FRIGHT, G_EYES, G_ENTER = range(6)


def sources():
    """The files that compile the game, or None without the art."""
    return H.act_sources(SOURCE)


class Game:
    def __init__(self, render=True):
        src = sources()
        if src is None:
            raise SystemExit("Ms. Cool-Man: the art is not here (assets/misscool/)")
        prg, syms = H.try_build_act(src, "mscoolman")
        if prg is None:
            raise SystemExit("compile failed:\n" + syms)
        self.prg, self.syms = prg, syms
        self.m = H.session(render=render)
        H.load_act(self.m, prg)

    # ------------------------------------------------------- the program
    def word(self, n, i=0):
        a = self.syms["v_" + n] + 2 * i
        v = self.m.bus.mem[a] | (self.m.bus.mem[a + 1] << 8)
        return v - 65536 if v >= 32768 else v

    def byte(self, n, i=0):
        return self.m.bus.mem[self.syms["v_" + n] + i]

    def poke(self, n, v, i=0):
        self.m.bus.mem[self.syms["v_" + n] + i] = v & 0xFF

    def pokew(self, n, v, i=0):
        a = self.syms["v_" + n] + 2 * i
        self.m.bus.mem[a] = v & 0xFF
        self.m.bus.mem[a + 1] = (v >> 8) & 0xFF

    def kind(self):
        a = self.syms["v_kind"]
        return bytes(self.m.bus.mem[a:a + 868])

    def set_kind(self, kind):
        a = self.syms["v_kind"]
        self.m.bus.mem[a:a + 868] = bytes(kind)

    def her(self):
        return self.word("cx"), self.word("cy")

    def ghosts(self):
        """(x, y, state) for Blinky, Pinky, Inky, Sue."""
        return [(self.word("cx", g), self.word("cy", g), self.byte("gstate", g))
                for g in range(1, 5)]

    def cell(self, col, row):
        """A map cell: (tile, attribute)."""
        a = row * 128 + col * 2
        v = self.m.video.vram[a:a + 2]
        return v[0], v[1]

    # ----------------------------------------------------------- playing
    def start(self):
        """Through the title and READY! into play."""
        self.m.run_frame(30)
        self.m.kbd.feed([0x29])
        self.m.run_frame(2)
        self.m.kbd.feed([0xF0, 0x29])
        self.m.run_frame(260)              # READY! with the jingle: 256 frames

    def route(self, tx, ty):
        """The first direction of a shortest walk from her tile to (tx, ty);
        None when she is there or it cannot be reached."""
        kind = self.kind()

        def ok(x, y):
            if x < 0 or x > 27:
                return True
            return 0 <= y <= 30 and kind[y * 28 + x] not in (K_WALL, K_DOOR, K_HOUSE)
        x, y = self.her()
        sx, sy = x >> 3, y >> 3
        if (sx, sy) == (tx, ty):
            return None
        prev = {(sx, sy): None}
        q = deque([(sx, sy)])
        while q:
            c = q.popleft()
            if c == (tx, ty):
                break
            for d, (dx, dy) in STEP.items():
                if not ok(c[0] + dx, c[1] + dy):
                    continue
                n = ((c[0] + dx) % 28, c[1] + dy)
                if n not in prev:
                    prev[n] = (c, d)
                    q.append(n)
        if (tx, ty) not in prev:
            return None
        c = (tx, ty)
        while prev[c][0] != (sx, sy):
            c = prev[c][0]
        return prev[c][1]

    def goto(self, tx, ty, limit=1200):
        """Walk her to the centre of a tile, poking `want` every frame.
        True on arrival; False when it cannot be reached or she stops
        moving (caught) or the limit runs out."""
        last, still = None, 0
        for t in range(limit):
            x, y = self.her()
            if (x >> 3, y >> 3) == (tx, ty) and (x & 7) == 4 and (y & 7) == 4:
                return True
            d = self.route(tx, ty)
            if d is not None:
                self.poke("want", d)
            self.m.run_frame(1)
            still = still + 1 if (x, y) == last else 0
            last = (x, y)
            if still > 8:
                return False
        return False

    def chase(self, state, limit=600):
        """Walk at the first ghost in a state until something happens:
        it is no longer in that state, the game pauses, or she stops."""
        last, still = None, 0
        for _ in range(limit):
            gs = [(gx, gy) for gx, gy, s in self.ghosts() if s == state]
            if not gs:
                return True
            gx, gy = gs[0]
            d = self.route(max(0, min(27, gx >> 3)), gy >> 3)
            if d is not None:
                self.poke("want", d)
            self.m.run_frame(1)
            if self.byte("pause_all"):
                return True
            x, y = self.her()
            still = still + 1 if (x, y) == last else 0
            last = (x, y)
            if still > 8:
                return False
        return False

    def eat(self, frames):
        """Toward the nearest dot, for so many frames; the frames the
        sprite engine overran are counted and the flag cleared each time."""
        import ioregs
        ctrl = ioregs.addr_of("SPR_CTRL")
        self.m.bus.write(ctrl, (15 << 4) | 3)
        over = 0
        kind = self.kind()
        lives = self.byte("lives")
        for t in range(frames):
            x, y = self.her()
            best = None
            for i, k in enumerate(kind):
                if k in (K_DOT, K_PILL):
                    d = abs((i % 28) - (x >> 3)) + abs((i // 28) - (y >> 3))
                    if best is None or d < best[0]:
                        best = (d, i % 28, i // 28)
            if best is None:
                break
            d = self.route(best[1], best[2])
            if d is not None:
                self.poke("want", d)
            self.m.run_frame(1)
            kind = self.kind()
            if self.m.bus.read(ctrl) & 2:
                over += 1
                self.m.bus.write(ctrl, (15 << 4) | 3)
            if self.byte("lives") != lives:
                break
        return over

    def clear_but_one(self):
        """Every dot but the nearest, then walk her onto it: the level
        ends. Returns True once the next level's READY! is on, with
        three frames of it left -- or False when she never got there."""
        kind = bytearray(self.kind())
        x, y = self.her()
        best = None
        for i in range(868):
            if kind[i] in (K_DOT, K_PILL):
                d = abs((i % 28) - (x >> 3)) + abs((i // 28) - (y >> 3))
                if best is None or d < best[0]:
                    best = (d, i)
        for i in range(868):
            if kind[i] in (K_DOT, K_PILL) and i != best[1]:
                kind[i] = K_PATH
        self.set_kind(kind)
        self.pokew("dots_left", 1)
        level = self.byte("level")
        tx, ty = best[1] % 28, best[1] // 28
        for t in range(600):
            if self.byte("level") != level:
                # Level() ran; Ready() holds 121 frames
                self.m.run_frame(118)
                return True
            d = self.route(tx, ty)
            if d is not None:
                self.poke("want", d)
            self.m.run_frame(1)
        return False

    # ------------------------------------------------------------ looking
    def png(self, name):
        import test_video as TV
        fb = self.m.fb()
        out = bytearray()
        for v in fb:
            out += bytes((((v >> 8) & 0xF) * 17, ((v >> 4) & 0xF) * 17, (v & 0xF) * 17))
        path = os.path.join(H.BUILD, name + ".png")
        TV.write_png(path, 640, 480, out)
        return path


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "title"
    g = Game()
    print("PRG %d bytes" % len(g.prg))
    if what == "title":
        g.m.run_frame(30)
        print(g.png("ms_title"))
        g.start()
        print(g.png("ms_ready"))
    else:
        g.start()
    if what == "pill":
        g.goto(1, 2)
        g.m.run_frame(5)
        print("fright", g.word("fright_left"), g.ghosts(), g.png("ms_fright"))
        g.chase(G_FRIGHT)
        g.m.run_frame(10)
        print("ghosts", g.ghosts(), "score", g.word("score"), g.png("ms_eaten"))
        for _ in range(600):
            g.m.run_frame(5)
            if all(s in (G_HOME, G_LEAVE, G_OUT) for _, _, s in g.ghosts()):
                break
        print("after", g.ghosts(), g.png("ms_home"))
    elif what == "death":
        g.chase(G_OUT)
        g.m.run_frame(75)
        print(g.png("ms_dying"))
        g.m.run_frame(150)
        print(g.png("ms_after_death"), "lives", g.byte("lives"), g.ghosts())
    elif what == "clear":
        g.clear_but_one()
        g.m.run_frame(60)
        print("level", g.byte("level"), "maze", g.byte("maze"), g.png("ms_level2"))
        g.clear_but_one()
        g.m.run_frame(60)
        print("level", g.byte("level"), "maze", g.byte("maze"), g.png("ms_level3"))
        g.goto(1, 4)
        g.m.run_frame(5)
        print(g.png("ms_level3_pill"), g.ghosts())
    elif what == "fruit":
        g.pokew("dots_left", g.word("dots_start") - 69)
        over = g.eat(60)
        print("fruit", g.word("fruit_left"), (g.word("cx", FRUIT), g.word("cy", FRUIT)),
              "overrun frames", over, g.png("ms_fruit"))
    print("frames", g.m.frames, "sp", hex(g.m.cpu.sp))


if __name__ == "__main__":
    main()
