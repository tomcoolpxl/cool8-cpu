"""MOTT on the session VM: the driver the gate and the eye use.

`Game` compiles demos/mott.act behind its art table, makes a flash
image with the theme files on MOTT's drive, loads the PRG on a
rendering session machine and plays: it taps keys through the keyboard's
scancodes and reads what the program holds by the compiler's symbol
table. Run it to look:

    python sim/mott.py [title|walk|stairs|deep] [role]

title shows the front; walk begins a game and walks the first level;
stairs goes down and back up; deep pokes the way to each theme. Frames
go to sim/build/yd_*.png.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness as H          # noqa: E402

SOURCE = "demos/mott.act"
ART = os.path.join(H.ROOT, "assets", "mott")
DATS = [os.path.join(ART, "MTHEME%d.DAT" % i) for i in range(3)]
NAMES = os.path.join(ART, "MNAMES.DAT")
HELP = os.path.join(ART, "MPAGES.DAT")
LEVELS = os.path.join(ART, "MLEVELS.DAT")
MUSIC = os.path.join(ART, "MMUSIC.DAT")
# make codes: the cursor keys are E0-prefixed
LEFT, RIGHT, DOWN, UP = [0xE0, 0x6B], [0xE0, 0x74], [0xE0, 0x72], [0xE0, 0x75]
KP = {1: [0x69], 2: [0x72], 3: [0x7A], 4: [0x6B], 5: [0x73], 6: [0x74], 7: [0x6C], 8: [0x75], 9: [0x7D]}
ENTER, SPACE, ESC, DOT, COMMA, LSHIFT = [0x5A], [0x29], [0x76], [0x49], [0x41], [0x12]
CTRL, KEY_R, KEY_Z, KEY_S, KEY_Y, KEY_N = [0x14], [0x2D], [0x1A], [0x1B], [0x35], [0x31]
S_LIVE, S_PET, S_ANGRY = 1, 2, 4
# the pack's letters a to r, as the keys that type them; the command keys
LETTERS = [0x1C, 0x32, 0x21, 0x23, 0x24, 0x2B, 0x34, 0x33, 0x43, 0x3B, 0x42, 0x4B, 0x3A, 0x31, 0x44, 0x4D, 0x15, 0x2D]
KEY_I, KEY_D, KEY_W, KEY_T, KEY_P, KEY_Q, KEY_F, KEY_BSLASH = [0x43], [0x23], [0x1D], [0x2C], [0x4D], [0x15], [0x2B], [0x5D]
KEY_3, KEY_SLASH, KEY_E = [0x26], [0x4A], [0x24]
# the letters as Set 2 make codes, for typing a line
SCAN = dict(zip("abcdefghijklmnopqrstuvwxyz",
                [0x1C, 0x32, 0x21, 0x23, 0x24, 0x2B, 0x34, 0x33, 0x43, 0x3B, 0x42, 0x4B, 0x3A, 0x31, 0x44, 0x4D,
                 0x15, 0x2D, 0x1B, 0x2C, 0x3C, 0x2A, 0x1D, 0x22, 0x35, 0x1A]))
OF_BLESS, OF_CURSE, OF_BKNOWN, OF_EKNOWN = 1, 2, 4, 8
LW, LH = 40, 24
K_ROCK, K_WALL, K_FLOOR, K_CORR, K_DOORC, K_DOORO, K_DOORWAY, K_UP, K_DOWN = range(9)
K_SDOOR, K_SCORR, K_FOUNTAIN, K_ALTAR = 9, 10, 11, 12       # 12-14 an altar, lawful to chaotic
F_TRAP, F_LIT, F_SEEN, F_VIS = 16, 32, 64, 128
TF_SEEN, TF_ONCE = 1, 2
OF_UNPAID, OF_DEAR, OF_NOCHG = 16, 32, 64
S_HOSTILE, S_PEACE = 8, 16
# the direction a keypad key steps, as (dx, dy)
STEP = {8: (0, -1), 9: (1, -1), 6: (1, 0), 3: (1, 1), 2: (0, 1), 1: (-1, 1), 4: (-1, 0), 7: (-1, -1)}


def sources():
    """The files that compile the game, or None without the art."""
    if not os.path.exists(os.path.join(ART, "mott_art.act")) or not all(os.path.exists(p) for p in DATS + [NAMES, HELP, LEVELS, MUSIC]):
        return None
    return H.act_sources(SOURCE)


def flash_image(name="mott"):
    """A formatted flash with the theme files on MOTT's drive, and the
    strings the build of that name wrote."""
    import cool8disk as disk
    img = os.path.join(H.BUILD, name + ".img")
    disk.make_image(img)
    im = disk.Image(img)
    vol = disk.Volume(im, disk.MOTT_VOL)
    for p in DATS + [NAMES, HELP, LEVELS, MUSIC]:
        vol.add(p, os.path.basename(p))
    if H.act_strings(name):
        vol.add(H.act_strings(name), "MOTT.STR")
    im.save()
    return img


class Game:
    def __init__(self, render=True, tag="mott"):
        src = sources()
        if src is None:
            raise SystemExit("MOTT: the art is not here -- python tools/mkmott.py")
        # where the loader runs it: the cell maps are bound below
        # PAYLOAD_ORG, where a program at $0200 would be
        prg, syms = H.try_build_act(src, tag, org=H.PAYLOAD_ORG)
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

    def word(self, n, i=0):
        v = self.uword(n, i)
        return v - 65536 if v >= 32768 else v

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
        return self.byte("lv", y * LW + x) & 15

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
        o = self.byte("oat", y * LW + x)
        if o:
            t = self.byte("ot", o - 1)
            return (self.byte("o_pic", t) + self.byte("ap", t)) * 4, 16 | bank
        if v & F_TRAP:
            tr = self.trap_at(x, y)
            if tr is not None and tr[3] & TF_SEEN:
                return c("T_TRAP") + 4 * tr[0], bank
        k = v & 15
        if k == K_SCORR:
            return 0, 0

        def wall(ax, ay):
            if not (0 <= ax < LW and 0 <= ay < LH):
                return 0
            return 1 if self.kind(ax, ay) in (K_WALL, K_DOORC, K_DOORO, K_DOORWAY, K_SDOOR) else 0
        if k in (K_WALL, K_SDOOR):
            t = c("T_WALL") + 4 * (8 * wall(x, y - 1) + 4 * wall(x, y + 1) + 2 * wall(x - 1, y) + wall(x + 1, y))
        elif k in (K_DOORC, K_DOORO):
            across = (x > 0 and self.kind(x - 1, y) == K_WALL) or (x + 1 < LW and self.kind(x + 1, y) == K_WALL)
            t = c("T_DOOR_%s_%s" % ("CLOSED" if k == K_DOORC else "OPEN", "H" if across else "V"))
        else:
            t = c({K_FLOOR: "T_FLOOR", K_CORR: "T_CORR", K_DOORWAY: "T_DOORWAY", K_UP: "T_UP",
                   K_DOWN: "T_DOWN", K_FOUNTAIN: "T_FOUNTAIN"}.get(k, "T_ALTAR"))
        return t, bank

    def traps(self):
        """The level's traps: (slot, kind, x, y, flags)."""
        return [(i, self.byte("tt", i), self.byte("tx", i), self.byte("ty", i), self.byte("tf", i))
                for i in range(8) if self.byte("tt", i) != 255]

    def trap_at(self, x, y):
        """(kind, x, y, flags) of the trap at a cell, or None."""
        return next(((k, tx, ty, f) for _i, k, tx, ty, f in self.traps() if (tx, ty) == (x, y)), None)

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
        for n, v in (("mtype", t), ("mx", x), ("my", y), ("mlev", lvl), ("mstat", state), ("mmove", 0),
                     ("msl", 0), ("mflee", 0)):
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

    # ------------------------------------------------------ the things
    def pack(self):
        """The pack: (letter, kind, quantity, flags, enchantment)."""
        return [(k, self.byte("it", k), self.byte("iq", k), self.byte("ifl", k), self.byte("ie", k))
                for k in range(18) if self.byte("it", k) != 255]

    def give(self, t, q=1, f=0, e=0):
        """A thing poked into the first free letter of the pack."""
        k = next(k for k in range(18) if self.byte("it", k) == 255)
        for n, v in (("it", t), ("iq", q), ("ifl", f), ("ie", e)):
            self.poke(n, v, k)
        return k

    def objs(self):
        """The things on the floor: (slot, kind, x, y, quantity, flags, enchantment)."""
        return [(i, self.byte("ot", i), self.byte("ox", i), self.byte("oy", i), self.byte("oq", i),
                 self.byte("of", i), self.byte("oe", i)) for i in range(32) if self.byte("ot", i) != 255]

    def put_obj(self, t, x, y, q=1, f=0, e=0):
        i = next(i for i in range(32) if self.byte("ot", i) == 255)
        for n, v in (("ot", t), ("ox", x), ("oy", y), ("oq", q), ("of", f), ("oe", e)):
            self.poke(n, v, i)
        self.poke("oat", i + 1, y * LW + x)
        self.redraw()
        return i

    def clear_objs(self):
        for i in range(32):
            self.poke("ot", 255, i)
        for c in range(LW * LH):
            self.poke("oat", 0, c)
        self.redraw()

    def command(self, key, letter=None, shift=False, direction=None):
        """A command key, the letter it asks for, and a direction if it
        asks for one; a --More-- in between is answered."""
        (self.shifted if shift else self.tap)(key)
        self.m.run_frame(4)
        if letter is not None:
            self.tap([LETTERS[letter]])
            self.m.run_frame(6)
        if direction is not None:
            self.tap(direction if isinstance(direction, list) else KP[direction])
            self.m.run_frame(6)
        for _ in range(8):
            if self.text(32, 1, 8) != "--More--":
                break
            self.tap(SPACE)
            self.m.run_frame(3)

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
        rocks = {(self.byte("ox", i), self.byte("oy", i)) for i in range(32)
                 if self.byte("ot", i) == self.c("O_BOULDER")}
        sokoban = self.byte("lvl") >= self.c("L_SOKO1")
        door = (K_DOORC, K_DOORO)
        while q:
            x, y = q.popleft()
            if (x, y) == goal:
                break
            for key, (dx, dy) in STEP.items():
                nx, ny = x + dx, y + dy
                if not (0 <= nx < LW and 0 <= ny < LH) or (nx, ny) in prev:
                    continue
                k, here = lv[ny * LW + nx] & 15, lv[y * LW + x] & 15
                if k in (K_ROCK, K_WALL, K_SDOOR, K_SCORR) or lv[ny * LW + nx] & F_TRAP or (nx, ny) in taken:
                    continue
                if (nx, ny) in rocks or (dx and dy and sokoban):
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
        l0 = self.uword("loops")                # the last step's turn finished and drawn, not caught half way
        self.until(lambda: self.uword("loops") != l0, 120)
        return self.hero() == goal

    def png(self, name):
        path = os.path.join(H.BUILD, name + ".png")
        H.shot(self.m, path)
        return path

    # ------------------------------------------------------ milestone 4
    def word_poke(self, n, v, i=0):
        v &= 0xFFFF
        self.poke(n, v & 255, 2 * i)
        self.poke(n, v >> 8, 2 * i + 1)

    def clear_traps(self):
        for i in range(8):
            self.poke("tt", 255, i)
        for c in range(LW * LH):
            self.poke("lv", self.byte("lv", c) & ~F_TRAP & 255, c)

    def put_trap(self, k, x, y, seen=False):
        i = next(i for i in range(8) if self.byte("tt", i) == 255)
        for n, v in (("tt", k), ("tx", x), ("ty", y), ("tf", TF_SEEN if seen else 0)):
            self.poke(n, v, i)
        c = y * LW + x
        self.poke("lv", self.byte("lv", c) | F_TRAP, c)
        return i

    def set_kind(self, x, y, k):
        c = y * LW + x
        self.poke("lv", (self.byte("lv", c) & 0xF0) | k, c)

    def type_text(self, s):
        """Letters typed as the keyboard sends them, shift for capitals."""
        for ch in s:
            code = [SCAN[ch.lower()]]
            (self.shifted if ch.isupper() else self.tap)(code)

    # ------------------------------------------------------ milestone 5
    def stairs(self, key, at):
        """The hero put on a cell and the stairs there taken: > or <."""
        self.poke("px", at[0])
        self.poke("py", at[1])
        f0 = self.m.frames
        self.shifted(key)
        l0 = self.uword("loops")
        self.until(lambda: self.uword("loops") > l0 + 2, 3000)
        self.m.run_frame(4)
        self.sturdy()
        return self.m.frames - f0

    def down_to(self, target):
        """Down the dungeon's stairs, a level at a time, to a level number."""
        while self.byte("lvl") < target:
            self.stairs(DOT, (self.byte("dnx"), self.byte("dny")))

    def play(self, keys=(), frames=6, cap=40):
        """Frames run, --More-- answered, and every message line seen kept."""
        seen = []
        for _ in range(cap):
            m = self.messages()
            if m not in seen:
                seen.append(m)
            if self.text(32, 1, 8) == "--More--":
                self.tap(SPACE)
                continue
            self.m.run_frame(frames)
            if self.messages() == m and self.text(32, 1, 8) != "--More--":
                break
        return " / ".join(seen)


PASSABLE = {K_FLOOR, K_CORR, K_DOORC, K_DOORO, K_DOORWAY, K_UP, K_DOWN, K_FOUNTAIN, 12, 13, 14}


def reach(lv, start, secrets):
    """The cells a hero at start can walk to -- a shut door opens, a door
    is never passed diagonally -- with the secret doors and passages found
    or not."""
    from collections import deque
    ok = PASSABLE | ({K_SDOOR, K_SCORR} if secrets else set())
    door = {K_DOORC, K_DOORO, K_SDOOR}
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in STEP.values():
            nx, ny = x + dx, y + dy
            if not (0 <= nx < LW and 0 <= ny < LH) or (nx, ny) in seen:
                continue
            k = lv[ny * LW + nx] & 15
            if k not in ok:
                continue
            if dx and dy and (k in door or lv[y * LW + x] & 15 in door):
                continue
            seen.add((nx, ny))
            q.append((nx, ny))
    return seen


def survey(g, n, say=True):
    """n levels made by the game's own MakeLevel and MakeCave, called on
    the running machine, and each searched from its stairs up: a cell no
    walk reaches even with every secret found is a level that cannot be
    finished; a corridor with one way on is a dead end; a room of stairs
    with no door nor corridor to be seen from them is a hero shut in on
    arriving. The stairs down behind a secret, somewhere, is NetHack's."""
    bad, behind, shut, secrets, ups, dead, shops, chances = [], 0, 0, 0, set(), 0, 0, 0.0
    syms = {k.lower(): v for k, v in g.syms.items()}
    for i in range(n):
        cave = i % 4 == 3
        d = 1 + i % 11
        if cave:
            g.poke("lvl", g.c("L_MINES") + i % 3)
            g.poke("depth", 3 + i % 3)
            H.call(g.m, syms, "MakeCave", at=0xFEE0)
        else:
            g.poke("lvl", d)
            g.poke("depth", d)
            H.call(g.m, syms, "MakeLevel", at=0xFEE0)
        lv = g.level()
        up, dn = (g.byte("upx"), g.byte("upy")), (g.byte("dnx"), g.byte("dny"))
        if not (0 <= up[0] < LW and 0 <= up[1] < LH) or lv[up[1] * LW + up[0]] & 15 != K_UP:
            bad.append((i, "cave" if cave else d, "no stairs up where upx, upy say", up))
            continue
        cells = {(x, y) for y in range(LH) for x in range(LW) if lv[y * LW + x] & 15 in PASSABLE | {K_SDOOR, K_SCORR}}
        found = reach(lv, up, True)
        lost = cells - found
        if lost:
            bad.append((i, "cave" if cave else d, "unreachable even with the secrets found", sorted(lost)[:6], len(lost)))
        secrets += sum(1 for v in lv if v & 15 in (K_SDOOR, K_SCORR))
        ups.add(up)
        if not cave and d > 1:
            chances += min(1.0, 3.0 / d)       # mklev's rn2(depth) < 3
            shops += g.byte("shroom") != 255
        has_dn = lv[dn[1] * LW + dn[0]] & 15 == K_DOWN
        if has_dn and dn not in reach(lv, up, False):
            behind += 1
        if cave:
            continue
        for (x, y) in found:
            if lv[y * LW + x] & 15 == K_CORR:
                ways = sum(1 for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0))
                           if 0 <= x + dx < LW and 0 <= y + dy < LH
                           and lv[(y + dy) * LW + x + dx] & 15 in PASSABLE | {K_SDOOR, K_SCORR})
                dead += ways <= 1
        for s in [up] + ([dn] if has_dn else []):
            if not any(lv[y * LW + x] & 15 in (K_CORR, K_DOORO, K_DOORC, K_DOORWAY) for (x, y) in reach(lv, s, False)):
                shut += 1
    st = dict(levels=n, bad=bad, dead=dead, shut=shut, behind=behind, secrets=secrets, ups=len(ups), shops=shops,
              chances=chances)
    if say:
        print("%(shops)d shops where the dice allowed %(chances).0f; "
              "%(levels)d levels: %(ups)d places for the stairs up, %(secrets)d secret doors and passages; "
              "%(behind)d with the stairs down behind a secret; %(dead)d dead ends; %(shut)d rooms of stairs shut in; "
              "%(n_bad)d that cannot be finished" % dict(st, n_bad=len(bad)))
        for b in bad[:20]:
            print("   ", b)
    return st


def follow(g, levels, say=True):
    """The hero walked to the stairs down of level after level, nothing
    else on them, and how far behind the pet is at each step: how often it
    is beside the hero, how far it falls, and how often it is beside the
    stairs when the hero gets there, to come along."""
    dists, beside_at_stairs, lost, waits = [], 0, 0, 0
    for n in range(levels):
        g.clear_monsters()
        pet = g.pet()
        if pet is None:
            hx, hy = g.hero()
            spot = next((hx + s[0], hy + s[1]) for s in STEP.values() if g.kind(hx + s[0], hy + s[1]) == K_FLOOR
                        and not g.byte("mat", (hy + s[1]) * LW + hx + s[0]))
            g.put_monster(g.c("M_KITTEN"), spot[0], spot[1], hp=30, state=S_LIVE | S_PET)
            lost += 1
        for i in range(LW * LH):                 # the secrets open and the traps gone, so the walk is the pet's test
            k = g.byte("lv", i) & 15
            if k in (K_SDOOR, K_SCORR):
                g.poke("lv", (g.byte("lv", i) & 0xF0) | (K_DOORC if k == K_SDOOR else K_CORR), i)
        g.clear_traps()
        goal = (g.byte("dnx"), g.byte("dny"))
        for _ in range(300):
            if g.hero() == goal:
                break
            if g.text(32, 1, 8) == "--More--":
                g.tap(SPACE)
                continue
            keys = g.path(goal)
            if not keys:
                g.tap(KEY_S)
                continue
            g.clear_monsters()
            g.sturdy()
            g.tap(KP[keys[0]])
            p = g.pet()
            if p:
                dists.append(max(abs(p[2] - g.hero()[0]), abs(p[3] - g.hero()[1])))
        waited = 0
        for waited in range(4):                  # a player waits a turn or three for the pet before going down
            p = g.pet()
            near = p and max(abs(p[2] - goal[0]), abs(p[3] - goal[1])) <= 1
            if near or waited == 3:
                break
            g.tap(KEY_S)
            g.play(frames=2, cap=4)
        beside_at_stairs += bool(near)
        waits += waited if near else 0
        if say:
            print("  level %d: %d steps, pet %s" % (g.byte("lvl"), len(dists),
                                                  "beside the stairs after %d turns waited" % waited if near else "not at the stairs"))
        g.stairs(DOT, goal)
    st = dict(steps=len(dists), beside=sum(1 for d in dists if d <= 1), within3=sum(1 for d in dists if d <= 3),
              worst=max(dists) if dists else 0, at_stairs=beside_at_stairs, levels=levels, lost=lost, waits=waits)
    if say:
        print("%(steps)d steps: pet beside the hero on %(beside)d, within 3 on %(within3)d, furthest %(worst)d; "
              "beside the stairs down within 3 turns on %(at_stairs)d of %(levels)d levels, %(waits)d turns waited in all "
              "(a new kitten given %(lost)d times)" % st)
    return st


def MY_NAME(g, t):
    import mkmott
    return mkmott.CREATURES[t][1]


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
    if what == "items":
        # things laid round the hero, one picked up, and the pack
        g.clear_monsters()
        g.clear_objs()
        hx, hy = g.hero()
        kinds = ["LONGSWORD", "HEALING", "IDENTIFY", "WSTRIKING", "RPROTECTION", "GOLD", "PLATEMAIL", "MOTT",
                 "SLEEPING", "LIFESAVING"]
        spots = [(hx + dx, hy + dy) for dy in (-2, -1, 0, 1, 2) for dx in (-3, -2, -1, 1, 2, 3)
                 if 0 <= hx + dx < LW and 0 <= hy + dy < LH and g.kind(hx + dx, hy + dy) == K_FLOOR
                 and not g.byte("mat", (hy + dy) * LW + hx + dx)]
        for k, (x, y) in zip(kinds, spots):
            g.put_obj(g.c("O_" + k), x, y, q=42 if k == "GOLD" else 1)
            i = y * LW + x
            g.poke("lv", g.byte("lv", i) | F_SEEN | F_VIS, i)
        g.redraw()
        g.put_obj(g.c("O_SLEEPING"), hx, hy)
        g.command(COMMA)
        print(g.png("yd_items"), g.messages())
        g.command(KEY_I)
        print(g.png("yd_items_pack"))
        g.tap(SPACE)
    if what == "pack":
        # the pack, the level's things, a potion drunk
        print(g.png("yd_pack_level"), [(g.byte("ot", i), g.byte("ox", i), g.byte("oy", i)) for i in range(32)
                                         if g.byte("ot", i) != 255])
        g.tap([0x43])                      # i
        g.m.run_frame(10)
        print(g.png("yd_pack_inv"), [g.text(0, r, 40).rstrip() for r in range(2, 12)])
        g.tap(SPACE)
        g.m.run_frame(5)
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
        g.poke("lvl", 8)
        g.poke("px", g.byte("dnx"))
        g.poke("py", g.byte("dny"))
        i = g.byte("dny") * LW + g.byte("dnx")
        g.poke("lv", K_DOWN | (g.byte("lv", i) & 240), i)
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
            g.poke("lvl", d - 1)
            g.poke("px", g.byte("dnx"))
            g.poke("py", g.byte("dny"))
            if g.kind(g.byte("dnx"), g.byte("dny")) != K_DOWN:
                i = g.byte("dny") * LW + g.byte("dnx")
                g.poke("lv", K_DOWN | (g.byte("lv", i) & 240), i)
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
    if what == "shop":
        # down, a level at a time, to the first with a shop; the hero walked
        # into it, and the room lit round the keeper; a fountain, an altar
        # and every kind of trap poked into a lit room of the level after
        for d in range(2, 13):
            dn = (g.byte("dnx"), g.byte("dny"))
            g.poke("px", dn[0])
            g.poke("py", dn[1])
            g.shifted(DOT)
            g.m.run_frame(30)
            g.sturdy()
            g.clear_monsters(keep_pet=False)
            if g.byte("shroom") != 255:
                break
        print("depth", g.byte("depth"), "shop", g.byte("shroom"), "kind", g.byte("shtype"), "keeper", g.byte("shk"))
        if g.byte("shroom") != 255:
            g.put_monster(g.c("M_SHOPKEEPER"), g.byte("spx"), g.byte("spy"), hp=200)
            g.poke("shk", next(i for i in range(20) if g.byte("mtype", i) == g.c("M_SHOPKEEPER")))
            door = (g.byte("shdx"), g.byte("shdy"))
            out = next(((door[0] + dx, door[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                        if g.kind(door[0] + dx, door[1] + dy) == K_CORR), None)
            if out and g.walk_to(out):
                g.tap(KP[next(k for k, s in STEP.items() if (out[0] + s[0], out[1] + s[1]) == door)])
                print("   ", g.play())
            print(g.png("yd_shop"), g.messages(), "hero", g.hero(), "post", (g.byte("spx"), g.byte("spy")),
                  "monsters", g.monsters())
            g.walk_to((g.byte("dnx"), g.byte("dny")))
        hx, hy = g.hero()
        spots = [(hx + dx, hy + dy) for dy in (-2, -1, 1, 2) for dx in (-4, -2, 0, 2, 4)
                 if 0 <= hx + dx < LW and 0 <= hy + dy < LH and g.kind(hx + dx, hy + dy) == K_FLOOR]
        for n, (x, y) in enumerate(spots[:13]):
            if n == 0:
                g.set_kind(x, y, K_FOUNTAIN)
            elif n == 1:
                g.set_kind(x, y, K_ALTAR + 1)
            else:
                g.put_trap(n - 2, x, y, seen=True)
            g.poke("lv", g.byte("lv", y * LW + x) | F_SEEN | F_VIS, y * LW + x)
        g.redraw()
        print(g.png("yd_features"), "wrong pictures", g.wrong_pics()[:4])
        g.shifted(KEY_SLASH)
        g.m.run_frame(8)
        print(g.png("yd_help"))
        g.tap(SPACE)
    if what == "branches":
        # the mines' stairs, the caves, the town, Delphi, and Sokoban
        g.poke("mines_at", 2)
        g.poke("oracle_at", 5)
        g.down_to(2)
        print("level 2: mines stairs at", (g.byte("brx"), g.byte("bry")), "kind", g.kind(g.byte("brx"), g.byte("bry")))
        frames = g.stairs(DOT, (g.byte("brx"), g.byte("bry")))
        print(g.png("yd_mines1"), "lvl", g.byte("lvl"), "depth", g.byte("depth"), "hero", g.hero(), "frames", frames,
              "monsters", [(MY_NAME(g, m[1]), m[2], m[3]) for m in g.monsters()])
        g.stairs(DOT, (g.byte("dnx"), g.byte("dny")))
        print(g.png("yd_town"), "lvl", g.byte("lvl"), "depth", g.byte("depth"), "shop", g.byte("shroom"),
              "temple", g.byte("troom"), "priest", g.byte("tpri"), "monsters", g.monsters())
        g.stairs(DOT, (g.byte("dnx"), g.byte("dny")))
        print(g.png("yd_mineend"), "lvl", g.byte("lvl"), "down", (g.byte("dnx"), g.byte("dny")))
        g.stairs(COMMA, (g.byte("upx"), g.byte("upy")))
        g.stairs(COMMA, (g.byte("upx"), g.byte("upy")))
        g.stairs(COMMA, (g.byte("upx"), g.byte("upy")))
        print("back up: lvl", g.byte("lvl"), "hero", g.hero(), "branch", (g.byte("brx"), g.byte("bry")))
        g.down_to(4)
        print("level 4: Sokoban stairs at", (g.byte("brx"), g.byte("bry")), "kind", g.kind(g.byte("brx"), g.byte("bry")))
        g.stairs(COMMA, (g.byte("brx"), g.byte("bry")))
        print(g.png("yd_soko1"), "lvl", g.byte("lvl"), "depth", g.byte("depth"), "hero", g.hero(),
              "boulders", len([o for o in g.objs() if o[1] == g.c("O_BOULDER")]), "traps", g.traps())
        g.stairs(COMMA, (g.byte("upx"), g.byte("upy")))
        print(g.png("yd_soko2"), "lvl", g.byte("lvl"), "depth", g.byte("depth"), "hero", g.hero())
        g.stairs(DOT, (g.byte("dnx"), g.byte("dny")))
        g.stairs(DOT, (g.byte("dnx"), g.byte("dny")))
        print("back down: lvl", g.byte("lvl"), "hero", g.hero())
        g.stairs(DOT, (g.byte("dnx"), g.byte("dny")))
        print(g.png("yd_delphi"), "lvl", g.byte("lvl"), "depth", g.byte("depth"), "monsters", g.monsters())
    if what == "follow":
        follow(g, int(sys.argv[3]) if len(sys.argv) > 3 else 8)
    if what == "reach":
        survey(g, int(sys.argv[3]) if len(sys.argv) > 3 else 400)
    if what == "deep":
        for d in (5, 9):
            g.poke("depth", d - 1)
            g.poke("lvl", d - 1)
            dn = (g.byte("dnx"), g.byte("dny"))
            g.poke("px", dn[0])
            g.poke("py", dn[1])
            g.shifted(DOT)
            g.m.run_frame(30)
            print(g.png("yd_depth%d" % d), "depth", g.byte("depth"), "theme", g.byte("theme"))


if __name__ == "__main__":
    main()
