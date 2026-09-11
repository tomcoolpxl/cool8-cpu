"""Arkanoid on the session VM: the driver the gate and the eye use.

`Game` compiles demos/arkanoid.act behind its generated art, makes a
flash image with its two data files on drive 11 -- where the demos disc
puts them, and where the game looks -- loads the PRG on a rendering
session machine with that flash, and plays: it holds and taps keys
through the keyboard's scancodes, and reads what the program holds by
the compiler's symbol table. Run it to look:

    python sim/arkanoid.py [MODE] [round]

MODE is title, round, play, powers, enemies, profile, doh or intro,
which play and write the frames to sim/build/ark_*.png; or one of the
Vaus's collisions -- touch, late, vaus, up -- which print what they
find and which the gate holds (each function says what it does).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness as H          # noqa: E402

SOURCE = "demos/arkanoid.act"
# the rounds' tiles and patterns, and the intro's and DOH's: two files,
# a file on a drive being at most 65,535 bytes
DATS = [os.path.join(H.ROOT, "assets", "arkanoid", n) for n in ("ARKANOID.DAT", "ARKSCENE.DAT")]
DAT = DATS[0]
# make and break codes: the cursor keys are E0-prefixed
LEFT, RIGHT, SPACE = [0xE0, 0x6B], [0xE0, 0x74], [0x29]


def sources():
    """The files that compile the game, or None without the art."""
    if not all(os.path.exists(p) for p in DATS):
        return None
    return H.act_sources(SOURCE)


def flash_image(name="arkanoid"):
    """A formatted flash with the two data files on drive 11."""
    import cool8disk as disk
    img = os.path.join(H.BUILD, name + ".img")
    disk.make_image(img)
    im = disk.Image(img)
    vol = disk.Volume(im, disk.ACTION_VOL)
    for p in DATS:
        vol.add(p, os.path.basename(p))
    im.save()
    return img


class Game:
    def __init__(self, render=True, tag="arkanoid"):
        """`tag` names the build and the flash image in sim/build, so that
        runs side by side do not write over each other's."""
        src = sources()
        if src is None:
            raise SystemExit("Arkanoid: the art is not here (assets/arkanoid/)")
        prg, syms = H.try_build_act(src, tag)
        if prg is None:
            raise SystemExit("compile failed:\n" + syms)
        self.prg, self.syms = prg, syms
        self.m = H.session(render=render, flash_path=flash_image(tag))
        self.org, self.end = H.load_act(self.m, prg)

    def profile(self, frames, top=16):
        """Where the clocks went over so many frames of the autopilot."""
        import dbg
        p = dbg.Profile(self.syms, self.org, self.end)
        f0, l0 = self.m.frames, self.uword("loops")
        p.start(self.m)
        self.autopilot(frames)
        p.collect(self.m)
        return p.report(top=top), self.m.frames - f0, self.uword("loops") - l0

    # ------------------------------------------------------- the program
    def addr(self, n):
        return self.syms["v_" + n]

    def word(self, n, i=0):
        a = self.addr(n) + 2 * i
        v = self.m.bus.mem[a] | (self.m.bus.mem[a + 1] << 8)
        return v - 65536 if v >= 32768 else v

    def uword(self, n, i=0):
        a = self.addr(n) + 2 * i
        return self.m.bus.mem[a] | (self.m.bus.mem[a + 1] << 8)

    def byte(self, n, i=0):
        return self.m.bus.mem[self.addr(n) + i]

    def poke(self, n, v, i=0):
        self.m.bus.mem[self.addr(n) + i] = v & 0xFF

    def pokew(self, n, v, i=0):
        a = self.addr(n) + 2 * i
        self.m.bus.mem[a] = v & 0xFF
        self.m.bus.mem[a + 1] = (v >> 8) & 0xFF

    def cell(self, col, row):
        """A map cell: (tile, attribute)."""
        a = row * 128 + col * 2
        v = self.m.video.vram[a:a + 2]
        return v[0], v[1]

    # ----------------------------------------------------------- playing
    def hold(self, codes, frames):
        """A key held for so many frames, then let go."""
        self.m.kbd.feed(codes)
        self.m.run_frame(frames)
        self.m.kbd.feed(codes[:-1] + [0xF0, codes[-1]])
        self.m.run_frame(1)

    def tap(self, codes):
        self.hold(codes, 2)

    def start(self):
        """Through the title, and the intro skipped, into round 1."""
        self.m.run_frame(40)
        self.tap(SPACE)
        self.m.run_frame(20)
        self.tap(SPACE)

    def balls(self):
        """(x, y) of each ball in play."""
        return [(self.uword("bx", b) >> 8, self.uword("by", b) >> 8) for b in range(3) if self.byte("bon", b)]

    def autopilot(self, frames, until=None):
        """Plays: the Vaus put under the lowest ball each frame, landing it
        somewhere different every half second so the angles vary. Stops
        early when `until()` says so; returns the frames it ran."""
        import random
        rng = random.Random(1)
        off = 10
        for t in range(frames):
            bs = self.balls()
            if bs:
                x, _ = max(bs, key=lambda p: p[1])
                if t % 30 == 0:
                    off = rng.randint(2, 26)
                self.pokew("vx", max(8, min(184, x - off)))
            self.m.run_frame(1)
            if until and until():
                return t + 1
        return frames

    def drop(self, letter):
        """A capsule of that letter dropped just over the Vaus."""
        k = "SCLEDBP".index(letter)
        self.poke("cap_k", k)
        self.pokew("cap_x", self.word("vx") + 8)
        self.pokew("cap_y", 196)
        self.poke("cap_t", 0)
        self.poke("cap_on", 1)

    def png(self, name):
        path = os.path.join(H.BUILD, name + ".png")
        H.shot(self.m, path)
        return path


# ------------------------------------------------ the Vaus's collisions
# Each starts from the ball waiting on the Vaus, the loop of play running,
# and returns what it saw: main() prints it and the gate holds it.

def playing(g, cap=600):
    """Frames until the loop of play runs, the ball waiting on the Vaus."""
    l0 = g.uword("loops")
    for t in range(cap):
        g.m.run_frame(1)
        if g.uword("loops") != l0:
            return t + 1
    raise SystemExit("the loop of play never ran")


def calm(g):
    """No enemy about and none coming, no capsule falling: the gate held
    shut."""
    g.pokew("en_timer", 60000)
    g.poke("gt_state", 0)
    g.poke("cap_on", 0)
    for e in range(3):
        g.poke("en_on", 0, e)


def touch(g, step=3, shots=False):
    """An enemy straight down onto the Vaus standing still, at each
    overlap from past its left end to past its right, the ball kept on
    the Vaus as catch keeps it. For each: its offset from vx; how it
    ended, "burst", "gone" or "never"; on which frame and where; and the
    frames it was over the Vaus's body and had not burst. `shots` writes
    the case 7 pixels in every four frames to sim/build/ark_touch_NN.png."""
    vy = g.syms["c_VAUS_Y"]
    vx = 100
    out = []
    for x in range(vx - 20, vx + 36, step):
        calm(g)
        g.pokew("en_x", x)
        g.pokew("en_y", vy - 24)
        g.poke("en_t", 1)
        g.poke("en_dx", 1)
        g.poke("en_dy", 2)
        g.poke("en_on", 1)
        shoot = shots and x - vx == 7
        over, end = [], None
        for t in range(60):
            g.poke("bheld", 1)
            g.pokew("bhold_t", 0)
            g.pokew("vx", vx)
            g.m.run_frame(1)
            if shoot and t % 4 == 0 and t < 44:
                g.png("ark_touch_%02d" % t)
            on, ex, ey = g.byte("en_on"), g.word("en_x"), g.word("en_y")
            if end is None and on != 1:
                end = ("burst" if on == 2 else "gone", t, (ex, ey))
            if end is None and ey + 15 >= vy and ey <= vy + 7 and ex + 15 >= g.word("vleft") and ex <= g.word("vright"):
                over.append((t, ex, ey))
            if end and not (shoot and t < 44):
                break
        out.append((x - vx,) + (end or ("never", None, (g.word("en_x"), g.word("en_y")))) + (over,))
    return out


def late(g):
    """The Vaus arriving under a falling ball: the ball straight down at
    two pixels a frame, and the Vaus put under it when the ball's bottom
    is d pixels past the Vaus's top -- 0 is where it would cross in step,
    8 is its top four rows from the Vaus's last. For each d, whether it
    bounced."""
    vy = g.syms["c_VAUS_Y"]
    out = []
    for d in range(9):
        calm(g)
        g.poke("bheld", 0)
        g.pokew("vx", 150)
        g.m.run_frame(1)
        g.pokew("bx", 60 << 8)
        g.pokew("by", (vy - 4 + d) << 8)
        g.pokew("bdx", 0)
        g.pokew("bdy", 512)
        g.pokew("vx", 46)
        bounced = False
        for _ in range(6):
            g.m.run_frame(1)
            if g.word("bdy") < 0:
                bounced = True
                break
            if (g.uword("by") >> 8) > vy + 8:
                break
        out.append((d, bounced))
        g.poke("bheld", 1)             # back on the Vaus for the next
        g.poke("bheld_b", 0)
        g.pokew("bhold", 14)
        g.pokew("bhold_t", 0)
        g.m.run_frame(2)
    return out


def body(g, hold=None):
    """The Vaus as drawn, row by row: the screen with it where it is
    against one with it 90 pixels off, (left, right) from vx on each of
    rows 208-223 it changes -- its shadow's with it, four down and four
    right. `hold()` runs before every frame."""
    def run(n):
        for _ in range(n):
            if hold:
                hold()
            g.m.run_frame(1)
    x = g.word("vx")
    run(2)
    a = g.m.fb()
    g.pokew("vx", x + 90 if x < 120 else x - 90)
    run(2)
    b = g.m.fb()
    g.pokew("vx", x)
    run(2)
    rows = {}
    for r in range(208, 224):
        # where it was, not where it went: the enlarged form reaches 8
        # left and 40 right, its shadow 4 more
        xs = [px for px in range(max(0, x - 16), min(224, x + 56))
              if a[2 * r * 640 + 2 * px] != b[2 * r * 640 + 2 * px]]
        if xs:
            rows[r] = (xs[0] - x, xs[-1] - x)
    return rows


def top(rows):
    """Rows 216-219 of `body()` as one (left, right): the body the ball
    lands on, over the shadow's rows."""
    rs = [rows[r] for r in range(216, 220) if r in rows]
    return (min(l for l, _ in rs), max(r for _, r in rs)) if rs else None


# a morph plays while vform already says where it goes: growing and
# arming say the form they go to; shrinking and disarming, the same
# frames backwards, say the normal one
MORPHS = (("GROW", "grow", 2, "shrink"), ("ARM", "arm", 1, "disarm"))


def vaus(g, xs=range(96, 104)):
    """The Vaus as drawn against the body the ball bounces off (vleft,
    vright): each form standing at the pixel offsets `xs`, then each
    frame of each morph with vform as that morph has it. For each: what,
    the drawn body on rows 216-219 and the ball's, both from vx."""
    calm(g)
    g.poke("bheld", 0)                 # the ball parked, still, under the bricks and over the Vaus
    g.pokew("bx", 200 << 8)
    g.pokew("by", 180 << 8)
    g.pokew("bdx", 0)
    g.pokew("bdy", 0)
    out = []
    for form in (0, 1, 2):
        g.poke("vform", form)
        g.poke("mo_n", 0)
        for x in xs:
            g.pokew("vx", x)
            out.append(("form %d at x %d" % (form, x), top(body(g)), (g.word("vleft") - x, g.word("vright") - x)))
    c = lambda n: g.syms["c_" + n]     # noqa: E731
    g.pokew("vx", 100)
    def held(f, form):
        def hold():
            for n, v in (("vform", form), ("mo_n", 1), ("mo_f0", f), ("mo_i", 0), ("mo_t", 0),
                         ("mo_rev", 0), ("mo_next", 255)):
                g.poke(n, v)
        return hold

    def ball():
        return (g.word("vleft") - 100, g.word("vright") - 100)
    for name, going, form, back in MORPHS:
        for i in range(c("VN_" + name)):
            f = c("VF_" + name) + i
            drawn = top(body(g, held(f, form)))
            out.append(("%s frame %d" % (going, i), drawn, ball()))
            # the same frame the other way: what is drawn is the frame's,
            # so only the ball's body is read again
            hold = held(f, 0)
            for _ in range(2):
                hold()
                g.m.run_frame(1)
            out.append(("%s frame %d" % (back, i), drawn, ball()))
    g.poke("vform", 0)
    g.poke("mo_n", 0)
    return out


def up(g, frames=96, shots=False):
    """An enemy made to head up from near the field's top every frame,
    as one heading in eight sends it: the highest it got, and each eight
    frames whether it is about and its y; `shots` writes those frames to
    sim/build/ark_up_NN.png."""
    calm(g)
    g.pokew("en_x", 60)
    g.pokew("en_y", 12)
    g.poke("en_t", 1)
    g.poke("en_dx", 1)
    g.poke("en_on", 1)
    ys, seen = [], []
    for t in range(frames):
        g.poke("en_dy", 0)
        g.poke("bheld", 1)
        g.pokew("bhold_t", 0)
        g.m.run_frame(1)
        ys.append(g.word("en_y"))
        if t % 8 == 7:
            seen.append((t, g.byte("en_on"), ys[-1]))
            if shots:
                g.png("ark_up_%02d" % t)
    return min(ys), seen


def collisions(g, what):
    """One of the experiments above, printed."""
    playing(g)
    if what == "touch":
        for dx, how, t, at, over in touch(g, shots=True):
            print("  an enemy %+3d from vx: %s%s at %s%s" % (
                dx, how, "" if t is None else " on frame %d" % t, at,
                "; over the body unburst on %d frames from %s" % (len(over), over[0]) if over else ""))
    elif what == "late":
        for d, bounced in late(g):
            print("  the ball's bottom %d past the Vaus's top when it came: %s"
                  % (d, "bounced" if bounced else "went through"))
    elif what == "vaus":
        for label, drawn, ball in vaus(g):
            ok = drawn and all(abs(a - b) <= 1 for a, b in zip(drawn, ball))
            print("  %-17s drawn %-10s the ball's %s%s" % (label, drawn, ball, "" if ok else "   <-- differ"))
    elif what == "up":
        low, seen = up(g, shots=True)
        for t, on, y in seen:
            print("  frame %2d: en_on %d, y %d" % (t, on, y))
        print("  the highest it got: y %d" % low)


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "title"
    g = Game(tag="ark_" + what)
    print("PRG %d bytes" % (len(g.prg) - 2))
    g.m.run_frame(40)
    print(g.png("ark_title"))
    if what == "title":
        return
    # the round a game starts on, set on the title: DOH's for "doh"
    if len(sys.argv) > 2:
        g.poke("start_round", int(sys.argv[2]))
    elif what == "doh":
        g.poke("start_round", 33)
    g.tap(SPACE)
    if g.byte("start_round") == 1:
        if what == "intro":
            # the story typed over the ship, its second page, the Vaus away
            for n, name in ((120, "ark_intro0"), (420, "ark_intro1"), (170, "ark_intro2"), (40, "ark_intro3")):
                g.m.run_frame(n)
                print(g.png(name))
            return
        g.m.run_frame(20)
        g.tap(SPACE)                   # the intro skipped
    g.m.run_frame(60)
    print(g.png("ark_round"))
    if what == "round":
        return
    if what in ("touch", "late", "vaus", "up"):
        collisions(g, what)
        return
    g.m.run_frame(200)
    print(g.png("ark_ready"))
    g.tap(SPACE)
    f0, l0 = g.m.frames, g.uword("loops")
    if what == "play":
        for i in range(6):
            g.autopilot(120)
            print(g.png("ark_play%d" % i), "balls", g.balls(), "score", g.uword("score10") * 10,
                  "bricks", g.uword("bricks_left"), "round", g.byte("round"), "lives", g.byte("lives"))
    elif what == "powers":
        for letter in "ELCDSBP":
            g.drop(letter)
            g.autopilot(40)
            print(letter, g.png("ark_power_" + letter), "form", g.byte("vform"), "power", g.byte("vpower"),
                  "balls", g.balls(), "exit", g.byte("ex_on"), "lives", g.byte("lives"))
            if letter == "L":
                g.m.kbd.feed(SPACE)
                g.autopilot(20)
                g.m.kbd.feed([0xF0, 0x29])
                print("  beams", [g.byte("bm_on", j) for j in range(6)], g.png("ark_laser"))
    elif what == "profile":
        # the busiest play there is: the exit crackling, three balls, the
        # enemies coming, the Vaus moving every frame
        g.drop("B")
        g.autopilot(40)
        g.drop("D")
        g.autopilot(40)
        rep, fr, lp = g.profile(300)
        print(rep)
        print("  %d frames, the loop ran %d" % (fr, lp))
    elif what == "doh":
        g.autopilot(300)
        print(g.png("ark_doh"), "hits", g.byte("doh_hits"), "state", g.byte("doh_state"),
              "shots", [g.byte("dsh_on", s) for s in range(3)], "lives", g.byte("lives"))
        g.poke("doh_hits", 15)
        n = g.autopilot(900, until=lambda: g.byte("doh_state") >= 9)
        print("  the sixteenth hit after %d frames" % n, g.png("ark_doh_hit"))
        g.m.run_frame(110)
        print(g.png("ark_doh_dying"), "doh_on", g.byte("doh_on"))
        g.m.run_frame(60)
        print(g.png("ark_doh_wire"))
        g.m.run_frame(120)
        print(g.png("ark_doh_gone"), "doh_on", g.byte("doh_on"), "score", g.uword("score10") * 10)
    elif what == "enemies":
        g.autopilot(900)
        print(g.png("ark_enemies"), "enemies", [(g.byte("en_on", e), g.word("en_x", e), g.word("en_y", e)) for e in range(3)])
    print("frames %d, the loop ran %d of them; sp %s" % (g.m.frames - f0, g.uword("loops") - l0, hex(g.m.cpu.sp)))


if __name__ == "__main__":
    main()
