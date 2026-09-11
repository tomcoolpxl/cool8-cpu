"""Arkanoid on the session VM: the driver the gate and the eye use.

`Game` compiles demos/arkanoid.act behind its generated art, makes a
flash image with ARKANOID.DAT on drive 11 -- where the demos disc puts
it, and where the game looks -- loads the PRG on a rendering session
machine with that flash, and plays: it holds and taps keys through the
keyboard's scancodes, and reads what the program holds by the
compiler's symbol table. Run it to look:

    python sim/arkanoid.py [title|round|play] [round]

writes the frames to sim/build/ark_*.png.
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
