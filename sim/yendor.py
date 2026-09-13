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
CTRL, KEY_R, KEY_Z, KEY_S, KEY_Y, KEY_N = [0x14], [0x2D], [0x1A], [0x1B], [0x35], [0x31]
S_LIVE, S_PET, S_ANGRY = 1, 2, 4
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
        m = self.byte("mat", y * LW + x)
        if m and v & F_VIS:
            return (3 + self.byte("mtype", m - 1)) * 4, (2 + self.byte("anim")) << 4
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

    # ---------------------------------------------------- the monsters
    def monsters(self):
        """The live monsters: (slot, type, x, y, hp, state)."""
        return [(i, self.byte("mtype", i), self.byte("mx", i), self.byte("my", i), self.byte("mhp", i),
                 self.byte("mstat", i)) for i in range(20) if self.byte("mstat", i)]

    def pet(self):
        return next((m for m in self.monsters() if m[5] & S_PET), None)

    def clear_monsters(self, keep_pet=True):
        """Every monster but the pet taken off the level, and the screen
        drawn again with Ctrl+R."""
        for i, _t, x, y, _hp, st in self.monsters():
            if keep_pet and st & S_PET:
                continue
            self.poke("mstat", 0, i)
            self.poke("mat", 0, y * LW + x)
        self.redraw()

    def put_monster(self, t, x, y, hp=None, state=S_LIVE):
        """A monster of type t poked onto a free slot at (x, y)."""
        i = next(i for i in range(20) if not self.byte("mstat", i))
        lvl = self.byte("m_lvl", t)
        for n, v in (("mtype", t), ("mx", x), ("my", y), ("mlev", lvl), ("mstat", state), ("mmove", 0)):
            self.poke(n, v, i)
        hp = hp if hp is not None else max(1, lvl * 4)
        self.poke("mhp", hp, i)
        self.poke("mhpmax", hp, i)
        self.poke("mat", i + 1, y * LW + x)
        self.redraw()
        return i

    def redraw(self):
        self.m.kbd.feed(CTRL)
        self.m.run_frame(1)
        self.tap(KEY_R)
        self.m.kbd.feed([0xF0, CTRL[0]])
        self.m.run_frame(1)

    def sturdy(self, hp=250):
        """The hero made hard to kill, for a walk the monsters may meet."""
        self.poke("uhp", hp)
        self.poke("uhpmax", hp)

    def messages(self):
        return self.text(0, 0, 40).rstrip() + " | " + self.text(0, 1, 40).rstrip()

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
        taken = {(self.byte("mx", i), self.byte("my", i)) for i in range(20)
                 if self.byte("mstat", i) and not self.byte("mstat", i) & S_PET}
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
                if k in (K_ROCK, K_WALL) or (nx, ny) in taken:
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
        for _ in range(3 * len(keys) + 20):
            if self.hero() == goal or self.byte("dead"):
                break
            if self.text(32, 1, 8) == "--More--":
                self.tap(SPACE)
                continue
            keys = self.path(goal)             # again each step: the monsters move
            if not keys:
                self.tap(KEY_S)
                continue
            self.tap(KP[keys[0]])
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
    print(g.png("yd_start"), "hero at", g.hero(), "depth", g.byte("depth"), "monsters", g.monsters())
    g.sturdy()
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
    if what == "fight":
        # a jackal and a floating eye beside the hero, and at them
        hx, hy = g.hero()
        g.clear_monsters()
        key, (dx, dy) = next((k, s) for k, s in STEP.items() if not (s[0] and s[1])
                             and g.kind(hx + s[0], hy + s[1]) == K_FLOOR and not g.byte("mat", (hy + s[1]) * LW + hx + s[0]))
        g.put_monster(g.c("M_JACKAL"), hx + dx, hy + dy, hp=6)
        for _ in range(12):
            if not g.byte("mat", (hy + dy) * LW + hx + dx):
                break
            if g.text(32, 1, 8) == "--More--":
                g.tap(SPACE)
            g.tap(KP[key])
            print("   ", g.messages())
        print(g.png("yd_fight"), "xp", g.uword("uxp"), "hp", g.byte("uhp"))
    if what == "scene":
        # a staged picture: creatures poked round the hero, and a blow struck
        def stage(types):
            hx, hy = g.hero()
            g.clear_monsters()
            spots = [(hx + dx, hy + dy) for dy in (-2, -1, 0, 1, 2) for dx in (-3, -2, -1, 0, 1, 2, 3)
                     if (dx, dy) != (0, 0) and 0 <= hx + dx < LW and 0 <= hy + dy < LH
                     and g.kind(hx + dx, hy + dy) == K_FLOOR and not g.byte("mat", (hy + dy) * LW + hx + dx)]
            spots.sort(key=lambda p: abs(p[0] - hx) + abs(p[1] - hy))
            for t, (x, y) in zip(types, spots[1::2]):
                g.put_monster(g.c("M_" + t), x, y, hp=60)
                i = y * LW + x
                g.poke("lv", g.byte("lv", i) | F_SEEN | F_VIS, i)
            g.redraw()
        stage(["JACKAL", "NEWT", "FLOATINGEYE", "HILLORC", "GNOMELORD", "GIANTBAT"])
        g.tap(KEY_S)
        g.m.run_frame(5)
        print(g.png("yd_scene1"), g.messages())
        for _ in range(10):
            if g.text(32, 1, 8) != "--More--":
                break
            g.tap(SPACE)
            g.m.run_frame(3)
        g.poke("ulev", 8)
        g.poke("depth", 8)
        g.poke("px", g.byte("dnx"))
        g.poke("py", g.byte("dny"))
        i = g.byte("dny") * LW + g.byte("dnx")
        g.poke("lv", K_DOWN | (g.byte("lv", i) & 224), i)
        g.shifted(DOT)
        g.m.run_frame(20)
        g.sturdy()
        stage(["TROLL", "VAMPIRE", "OWLBEAR", "WRAITH", "SOLDIERANT", "ETTIN"])
        g.tap(KEY_S)
        g.m.run_frame(5)
        print(g.png("yd_scene9"), g.messages())
    if what == "tour":
        # a fight in the first room, a deep level's monsters, and the grave
        hx, hy = g.hero()
        g.clear_monsters()
        key, (dx, dy) = next((k, s) for k, s in STEP.items() if not (s[0] and s[1])
                             and g.kind(hx + s[0], hy + s[1]) == K_FLOOR and not g.byte("mat", (hy + s[1]) * LW + hx + s[0]))
        g.put_monster(g.c("M_HILLORC"), hx + dx, hy + dy, hp=12)
        for _ in range(3):
            if g.text(32, 1, 8) == "--More--":
                g.tap(SPACE)
            g.tap(KP[key])
        print(g.png("yd_tour_fight"), g.messages())
        g.poke("ulev", 8)
        for d in (9,):
            g.poke("depth", d - 1)
            g.poke("px", g.byte("dnx"))
            g.poke("py", g.byte("dny"))
            if g.kind(g.byte("dnx"), g.byte("dny")) != K_DOWN:
                i = g.byte("dny") * LW + g.byte("dnx")
                g.poke("lv", K_DOWN | (g.byte("lv", i) & 224), i)
            g.shifted(DOT)
            g.m.run_frame(20)
            g.sturdy()
            mons = g.monsters()
            if mons:
                # walk to the nearest monster that is not the pet, so it is on the screen
                t = min((m for m in mons if not m[5] & S_PET), key=lambda m: abs(m[2] - g.hero()[0]) + abs(m[3] - g.hero()[1]),
                        default=None)
                if t:
                    for _ in range(40):
                        keys = g.path((t[2], t[3]))
                        if not keys or len(keys) <= 2:
                            break
                        g.tap(KP[keys[0]])
                        if g.text(32, 1, 8) == "--More--":
                            g.tap(SPACE)
            print(g.png("yd_tour_deep"), [(g.c("N_MON"), m) for m in g.monsters()][:3])
        g.poke("uhp", 1)
        for _ in range(200):
            if g.byte("phase") == 2:
                break
            if g.text(32, 1, 8) == "--More--":
                g.tap(SPACE)
            else:
                g.tap(KEY_S)
        g.m.run_frame(10)
        print(g.png("yd_tour_grave"))
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
