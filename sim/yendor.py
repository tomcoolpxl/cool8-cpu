"""YENDOR on the session VM: the driver the gate and the eye use.

`Game` compiles demos/yendor.act behind its art table, makes a flash
image with the theme files on YENDOR's drive, loads the PRG on a
rendering session machine and plays: it taps keys through the keyboard's
scancodes and reads what the program holds by the compiler's symbol
table. Run it to look:

    python sim/yendor.py [title|walk|stairs|deep] [role]

title shows the front; walk begins a game and walks the first level;
stairs goes down and back up; deep pokes the way to each theme. Frames
go to sim/build/yd_*.png.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness as H          # noqa: E402

SOURCE = "demos/yendor.act"
ART = os.path.join(H.ROOT, "assets", "yendor")
DATS = [os.path.join(ART, "YTHEME%d.DAT" % i) for i in range(3)]
# make codes: the cursor keys are E0-prefixed
LEFT, RIGHT, DOWN, UP = [0xE0, 0x6B], [0xE0, 0x74], [0xE0, 0x72], [0xE0, 0x75]
KP = {1: [0x69], 2: [0x72], 3: [0x7A], 4: [0x6B], 5: [0x73], 6: [0x74], 7: [0x6C], 8: [0x75], 9: [0x7D]}
ENTER, SPACE, ESC, DOT, COMMA, LSHIFT = [0x5A], [0x29], [0x76], [0x49], [0x41], [0x12]
LW, LH = 40, 24
K_ROCK, K_WALL, K_FLOOR, K_CORR, K_DOORC, K_DOORO, K_DOORWAY, K_UP, K_DOWN = range(9)
F_LIT, F_SEEN, F_VIS = 32, 64, 128
# the direction a keypad key steps, as (dx, dy)
STEP = {8: (0, -1), 9: (1, -1), 6: (1, 0), 3: (1, 1), 2: (0, 1), 1: (-1, 1), 4: (-1, 0), 7: (-1, -1)}


def sources():
    """The files that compile the game, or None without the art."""
    if not os.path.exists(os.path.join(ART, "yendor_art.act")) or not all(os.path.exists(p) for p in DATS):
        return None
    return H.act_sources(SOURCE)


def flash_image(name="yendor"):
    """A formatted flash with the theme files on YENDOR's drive."""
    import cool8disk as disk
    img = os.path.join(H.BUILD, name + ".img")
    disk.make_image(img)
    im = disk.Image(img)
    vol = disk.Volume(im, disk.YENDOR_VOL)
    for p in DATS:
        vol.add(p, os.path.basename(p))
    im.save()
    return img


class Game:
    def __init__(self, render=True, tag="yendor"):
        src = sources()
        if src is None:
            raise SystemExit("YENDOR: the art is not here -- python tools/mkyendor.py")
        prg, syms = H.try_build_act(src, tag)
        if prg is None:
            raise SystemExit("compile failed:\n" + syms)
        self.prg, self.syms = prg, syms
        self.m = H.session(render=render, flash_path=flash_image(tag))
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

    def tile(self, col, row):
        """A map tile: (tile, attribute)."""
        a = row * 128 + col * 2
        v = self.m.video.vram[a:a + 2]
        return v[0], v[1]

    def text(self, col, row, n):
        """What a row of the screen says, in the font's glyphs."""
        out = ""
        for i in range(n):
            t, a = self.tile(col + i, row)
            out += chr(t + 32) if (a >> 4) == 0 and t < 95 else "?"
        return out

    # ------------------------------------------------------- the level
    def level(self):
        return [self.byte("lv", i) for i in range(LW * LH)]

    def kind(self, x, y):
        return self.byte("lv", y * LW + x) & 31

    def hero(self):
        return self.byte("px"), self.byte("py")

    def cell_pic(self, x, y):
        """The picture on the screen at a level cell, or None off the window."""
        vx, vy = self.byte("vx"), self.byte("vy")
        if not (vx <= x < vx + 20 and vy <= y < vy + 13):
            return None
        return self.tile((x - vx) * 2, 2 + (y - vy) * 2)

    def want_pic(self, x, y):
        """The picture a level cell should show, by the art's numbering:
        the hero's frame in bank 2 or 3, black for never seen, the terrain
        in palette bank 0 when in view and 1 when remembered."""
        c = self.c
        if (x, y) == self.hero():
            return self.byte("role") * 4, (2 + self.byte("anim")) << 4
        v = self.byte("lv", y * LW + x)
        if not v & F_SEEN:
            return 0, 0
        bank = 0 if v & F_VIS else 1
        k = v & 31

        def wall(ax, ay):
            if not (0 <= ax < LW and 0 <= ay < LH):
                return 0
            return 1 if self.kind(ax, ay) in (K_WALL, K_DOORC, K_DOORO, K_DOORWAY) else 0
        if k == K_WALL:
            t = c("T_WALL") + 4 * (8 * wall(x, y - 1) + 4 * wall(x, y + 1) + 2 * wall(x - 1, y) + wall(x + 1, y))
        elif k in (K_DOORC, K_DOORO):
            across = (x > 0 and self.kind(x - 1, y) == K_WALL) or (x + 1 < LW and self.kind(x + 1, y) == K_WALL)
            t = c("T_DOOR_%s_%s" % ("CLOSED" if k == K_DOORC else "OPEN", "H" if across else "V"))
        else:
            t = c({K_FLOOR: "T_FLOOR", K_CORR: "T_CORR", K_DOORWAY: "T_DOORWAY",
                   K_UP: "T_UP", K_DOWN: "T_DOWN"}[k])
        return t, bank

    def wrong_pics(self):
        """The cells in the window whose picture is not what they hold."""
        vx, vy = self.byte("vx"), self.byte("vy")
        return [(x, y) for y in range(vy, vy + 13) for x in range(vx, vx + 20)
                if self.cell_pic(x, y) != self.want_pic(x, y)]

    # -------------------------------------------------------- the keys
    def tap(self, codes, frames=2):
        self.m.kbd.feed(codes)
        self.m.run_frame(frames)
        self.m.kbd.feed(codes[:-1] + [0xF0, codes[-1]])
        self.m.run_frame(1)

    def shifted(self, codes, frames=2):
        """A key with the left shift held round it: > is shift and full stop."""
        self.m.kbd.feed(LSHIFT)
        self.m.run_frame(1)
        self.tap(codes, frames)
        self.m.kbd.feed([0xF0, LSHIFT[0]])
        self.m.run_frame(1)

    def until(self, pred, cap=600):
        for t in range(cap):
            if pred():
                return t
            self.m.run_frame(1)
        return None

    def start(self, role=0):
        """Through the title into a game as that hero."""
        self.until(lambda: self.byte("phase") == 0 and self.byte("theme") == 0, 300)
        self.m.run_frame(10)
        for _ in range(3):
            if self.byte("role") == role:
                break
            self.tap(DOWN)
            self.m.run_frame(2)
        self.tap(ENTER)
        l0 = self.uword("loops")
        if self.until(lambda: self.uword("loops") != l0, 600) is None:
            raise SystemExit("the loop of play never ran")

    def path(self, goal):
        """The keypad presses that walk the hero to a cell, by a search over
        what the level holds -- doors shut are walked into and open."""
        from collections import deque
        lv = self.level()
        start = self.hero()
        prev = {start: None}
        q = deque([start])
        door = (K_DOORC, K_DOORO)
        while q:
            x, y = q.popleft()
            if (x, y) == goal:
                break
            for key, (dx, dy) in STEP.items():
                nx, ny = x + dx, y + dy
                if not (0 <= nx < LW and 0 <= ny < LH) or (nx, ny) in prev:
                    continue
                k, here = lv[ny * LW + nx] & 31, lv[y * LW + x] & 31
                if k in (K_ROCK, K_WALL):
                    continue
                if dx and dy and (k in door or here in door):
                    continue
                prev[(nx, ny)] = ((x, y), key)
                q.append((nx, ny))
        if goal not in prev:
            return None
        keys, at = [], goal
        while prev[at]:
            at, key = prev[at]
            keys.append(key)
        return keys[::-1]

    def walk_to(self, goal):
        keys = self.path(goal)
        if keys is None:
            return False
        for key in keys:
            before = self.hero()
            self.tap(KP[key])
            if self.hero() == before:          # a door opened instead: step again
                self.tap(KP[key])
        return self.hero() == goal

    def png(self, name):
        path = os.path.join(H.BUILD, name + ".png")
        H.shot(self.m, path)
        return path


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "title"
    role = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    g = Game(tag="yd_" + what)
    print("PRG %d bytes" % (len(g.prg) - 2))
    g.m.run_frame(60)
    print(g.png("yd_title"))
    if what == "title":
        return
    g.start(role)
    g.m.run_frame(10)
    print(g.png("yd_start"), "hero at", g.hero(), "depth", g.byte("depth"))
    if what in ("walk", "stairs"):
        dn = (g.byte("dnx"), g.byte("dny"))
        ok = g.walk_to(dn)
        print(g.png("yd_walked"), "walked to the stairs down" if ok else "no way to the stairs", dn, "turns", g.uword("turns"))
        if what == "stairs" and ok:
            g.shifted(DOT)
            g.m.run_frame(20)
            print(g.png("yd_level2"), "depth", g.byte("depth"), "hero", g.hero())
            g.shifted(COMMA)
            g.m.run_frame(20)
            print(g.png("yd_back1"), "depth", g.byte("depth"), "hero", g.hero())
    if what == "deep":
        for d in (5, 9):
            g.poke("depth", d - 1)
            dn = (g.byte("dnx"), g.byte("dny"))
            g.poke("px", dn[0])
            g.poke("py", dn[1])
            g.shifted(DOT)
            g.m.run_frame(30)
            print(g.png("yd_depth%d" % d), "depth", g.byte("depth"), "theme", g.byte("theme"))


if __name__ == "__main__":
    main()
