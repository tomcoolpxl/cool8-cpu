"""COOL SWEEPER on the session VM: the driver the gate and the eye use.

`Game` compiles demos/coolsw.act behind its generated art, loads the
PRG on a rendering session machine, and plays: it taps keys through the
keyboard's scancodes and reads what the program holds by the compiler's
symbol table. Run it to look:

    python sim/coolsw.py [title|play|win|boom|pause] [level]

title shows the front; play digs the middle and flags what the numbers
prove; win clears the field; boom digs a mine; pause pauses. Frames go
to sim/build/sw_*.png.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness as H          # noqa: E402

SOURCE = "demos/coolsw.act"
ART = os.path.join(H.ROOT, "assets", "coolsw", "coolsw_art.act")
# make codes: the cursor keys are E0-prefixed
LEFT, RIGHT, DOWN, UP = [0xE0, 0x6B], [0xE0, 0x74], [0xE0, 0x72], [0xE0, 0x75]
SPACE, ENTER, F, P, ESC = [0x29], [0x5A], [0x2B], [0x4D], [0x76]
GLYPHS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-.!/ "   # the font's order
LEVELS = [(9, 9, 10), (14, 11, 25), (18, 12, 45)]
F_MINE, F_OPEN, F_FLAG, F_MARK = 16, 32, 64, 128


def sources():
    """The files that compile the game, or None without the art."""
    if not os.path.exists(ART):
        return None
    return H.act_sources(SOURCE)


class Game:
    def __init__(self, render=True, tag="coolsw"):
        src = sources()
        if src is None:
            raise SystemExit("COOL SWEEPER: the art is not here (assets/coolsw/)")
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
        a = self.addr(n) + 2 * i
        self.m.bus.mem[a] = v & 0xFF
        self.m.bus.mem[a + 1] = (v >> 8) & 0xFF

    def cell(self, col, row):
        """A map tile: (tile, attribute)."""
        a = row * 128 + col * 2
        v = self.m.video.vram[a:a + 2]
        return v[0], v[1]

    def text(self, col, row, n):
        """What a row of the map says, in the font's glyphs; `?` for a
        tile that is not one."""
        out = ""
        for i in range(n):
            t, _ = self.cell(col + i, row)
            for base in (self.c("T_FONT"), self.c("T_BFONT")):
                if base <= t < base + len(GLYPHS):
                    out += GLYPHS[t - base]
                    break
            else:
                out += "?"
        return out

    # -------------------------------------------------------- the field
    def size(self):
        return self.byte("bw"), self.byte("bh"), self.byte("nm")

    def field(self):
        bw, bh, _ = self.size()
        return [self.byte("f", i) for i in range(bw * bh)]

    def pic(self, x, y):
        """The picture a field cell shows: (first tile, bank)."""
        return self.cell(self.byte("ox") + 2 * x, self.byte("oy") + 2 * y)

    def want(self, v, x, y):
        """The picture a cell's byte should show, by the art's numbering."""
        c = self.c
        p = 4 * ((x + y) & 1)
        if v & F_OPEN:
            if v & F_MINE:
                return c("T_MINE") + p, c("B_BOOM") if v & F_MARK else c("B_FIELD")
            n = v & 15
            if n:
                return c("T_DIGIT") + 8 * (n - 1) + p, c("B_NUM") + n - 1
            return c("T_OPEN") + p, c("B_FIELD")
        if v & F_FLAG:
            if v & F_MARK:
                return c("T_WRONG") + p, c("B_WRONG")
            return c("T_FLAG") + p, c("B_FIELD")
        return c("T_COVER") + p, c("B_FIELD")

    def score(self):
        return sum(self.byte("dig", i) * 10 ** i for i in range(6))

    # -------------------------------------------------------- the keys
    def tap(self, codes, frames=2):
        self.m.kbd.feed(codes)
        self.m.run_frame(frames)
        self.m.kbd.feed(codes[:-1] + [0xF0, codes[-1]])
        self.m.run_frame(1)

    def until(self, pred, cap=600):
        for t in range(cap):
            if pred():
                return t
            self.m.run_frame(1)
        return None

    def start(self, level=0):
        """Through the front into a game of that level: down until the
        cursor is on it, whichever level the last game left it on."""
        self.until(lambda: self.byte("phase") == 0, 600)
        self.m.run_frame(20)
        for _ in range(3):
            if self.byte("sel") == level:
                break
            self.tap(DOWN)
            self.m.run_frame(3)
        self.tap(SPACE)
        l0 = self.uword("loops")
        t = self.until(lambda: self.uword("loops") != l0, 600)
        if t is None:
            raise SystemExit("the loop of play never ran")
        return t

    def goto(self, x, y):
        """The cursor to a cell, by the keys."""
        for _ in range(40):
            cx, cy = self.byte("ccx"), self.byte("ccy")
            if (cx, cy) == (x, y):
                return True
            if cx < x:
                self.tap(RIGHT)
            elif cx > x:
                self.tap(LEFT)
            elif cy < y:
                self.tap(DOWN)
            else:
                self.tap(UP)
        return False

    def dig(self, x, y, settle=40):
        self.goto(x, y)
        self.tap(SPACE)
        self.m.run_frame(settle)

    def flag(self, x, y):
        self.goto(x, y)
        self.tap(ENTER)
        self.m.run_frame(2)

    def png(self, name):
        path = os.path.join(H.BUILD, name + ".png")
        H.shot(self.m, path)
        return path


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "title"
    level = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    g = Game(tag="sw_" + what)
    print("PRG %d bytes" % (len(g.prg) - 2))
    g.m.run_frame(30)
    for _ in range(level):
        g.tap(DOWN)
        g.m.run_frame(3)
    g.m.run_frame(20)
    print(g.png("sw_title%d" % level))
    if what == "title":
        return
    g.tap(SPACE)
    g.m.run_frame(40)
    print(g.png("sw_start%d" % level))
    bw, bh, nm = g.size()
    g.dig(bw // 2, bh // 2, 60)
    print(g.png("sw_dug%d" % level), "score", g.score(), "opened", g.byte("opened"))
    if what == "play":
        # flag every mine that touches an opened number, as a player would
        f = g.field()
        for i, v in enumerate(f):
            x, y = i % bw, i // bw
            if v & F_MINE and any(
                    0 <= x + dx < bw and 0 <= y + dy < bh and f[(y + dy) * bw + x + dx] & F_OPEN
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                g.flag(x, y)
        g.m.run_frame(30)
        print(g.png("sw_play%d" % level), "flags", g.byte("flags"))
    elif what == "win":
        f = g.field()
        for i, v in enumerate(f):
            if not v & (F_MINE | F_OPEN):
                g.poke("f", v | F_OPEN, i)
                g.poke("opened", g.byte("opened") + 1)
        last = next(i for i, v in enumerate(f) if not v & (F_MINE | F_OPEN))
        g.poke("f", f[last], last)
        g.poke("opened", g.byte("opened") - 1)
        g.tap(P)                       # the pause redraws the field the pokes opened
        g.m.run_frame(4)
        g.tap(P)
        g.m.run_frame(4)
        g.dig(last % bw, last // bw, 5)
        g.m.run_frame(200)
        print(g.png("sw_win%d" % level), "score", g.score())
        g.m.run_frame(200)
        print(g.png("sw_win%db" % level), "score", g.score(), "phase", g.byte("phase"))
    elif what == "boom":
        f = g.field()
        mine = next(i for i, v in enumerate(f) if v & F_MINE)
        g.dig(mine % bw, mine // bw, 12)
        print(g.png("sw_boom%da" % level))
        g.m.run_frame(160)
        print(g.png("sw_boom%d" % level), "score", g.score())
        g.m.run_frame(200)
        print(g.png("sw_boom%db" % level), "score", g.score(), "phase", g.byte("phase"))
    elif what == "pause":
        g.tap(P)
        g.m.run_frame(10)
        print(g.png("sw_pause%d" % level))


if __name__ == "__main__":
    main()
