"""GALAGA on the session VM: the driver the gate and the eye use.

`Game` compiles demos/galaga.act behind its generated art, makes a flash
image with GALAGA.DAT on drive 11 -- where the demos disc puts it, and
where the game looks -- loads the PRG on a rendering session machine with
that flash, and plays: it holds and taps keys through the keyboard's
scancodes, and reads what the program holds by the compiler's symbol
table. Run it to look:

    python sim/galaga.py [MODE]

MODE is play, which writes frames to sim/build/gal_*.png; levels, a
frame of each backdrop; bitmap, which holds the bitmap to the program's
state as the formation breathes; split, the raster lines the palette is
written on; shoot [apart|trace], a volley into the formation -- trace
checks every frame for a pixel strayed outside a live explosion; or
profile, which measures the work in every frame -- the clocks that are
not WaitVBlank's -- and says where the busiest frame's went.
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

    def start(self):
        """From the title, space, and on through STAGE 1 to the stage's first
        frame."""
        self.m.run_frame(20)
        self.tap(SPACE)
        t = self.until(lambda: self.byte("launching") == 1 and 0 < self.uword("stage_frames") < 4, 600)
        assert t is not None, "stage 1 never started"

    def goto_stage(self, n):
        """Straight on to stage n's intro, from the first frames of stage 1
        (before anything has launched): stage 1 made done."""
        self.poke("launching", 0)
        self.poke("stage", n - 1)
        self.until(lambda: self.byte("stage") == n and self.byte("launching") == 1, 600)

    def autopilot(self, frames, until=None):
        """Plays: the fighter put under the lowest thing flying -- or the
        lowest column of the formation -- and firing whenever a shot is
        free. Stops early when `until()` says so; returns the frames run."""
        n = self.c("NFLY")
        for t in range(frames):
            st = self.array("fl_state", n)
            sy = self.m.bus.mem[self.addr("fl_sy"):self.addr("fl_sy") + 2 * n]
            sx = self.m.bus.mem[self.addr("fl_sx"):self.addr("fl_sx") + 2 * n]
            best = None
            for k in range(n):
                if st[k] in (3, 7, 9):
                    y = sy[2 * k] | (sy[2 * k + 1] << 8)
                    x = sx[2 * k] | (sx[2 * k + 1] << 8)
                    y = y - 65536 if y >= 32768 else y
                    x = x - 65536 if x >= 32768 else x
                    if 0 <= y < 200 and -8 < x < 216 and (best is None or y > best[1]):
                        best = (x, y)
            if best is None:
                on = [i for i in range(self.c("NSLOT")) if self.byte("sl_on", i)]
                if on:
                    i = max(on, key=lambda i: self.byte("sl_y", i))
                    best = (self.byte("sl_x", i), 0)
            if best is not None:
                self.pokew("fx", max(1, min(207, best[0])))
            if t % 3 == 0:
                self.m.kbd.feed(SPACE)
            elif t % 3 == 1:
                self.m.kbd.feed([0xF0] + SPACE)
            self.m.run_frame(1)
            if until and until():
                return t + 1
        return frames

    def crash(self):
        """A flyer that is not yet homing moved onto the fighter, in the
        arcade's coordinates its motion keeps: the slot's index, or None."""
        n = self.c("NFLY")
        for k in range(n):
            if self.byte("fl_state", k) in (3, 7) and not self.byte("fl_fl", k) & 0x40:
                x8 = self.word("fx") + 17
                y9 = self.c("FIGHTER_Y") + 56          # the one-for-one rows' mapping, near enough here
                self.pokew("fl_x", (x8 >> 1) << 8, k)
                self.pokew("fl_y", ((0x161 - 297) >> 1) << 8, k)
                return k
        return None

    def drop_on_fighter(self):
        """A bomb put where the fighter is, on bomb 0 and sprite 31, for the
        next frame's collision to find."""
        self.poke("bo_on", 1, 0)
        self.poke("bo_x", self.word("fx") + 17, 0)
        self.pokew("bo_y", 0x129, 0)
        self.poke("bo_sp", 31, 0)
        self.poke("bo_own", self.byte("bo_own") | 1)

    def until(self, pred, cap=600):
        for t in range(cap):
            if pred():
                return t
            self.m.run_frame(1)
        return None

    def frame_work(self, frames, spare=False):
        """The clocks each of so many frames spent on something other than
        waiting for the next, and the profile of the busiest; `spare` plays
        them with spared_frame."""
        import dbg
        worst, costs = None, []
        for _ in range(frames):
            p = dbg.Profile(self.syms, self.org, self.end)
            p.start(self.m)
            if spare:
                self.spared_frame()
            else:
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

    def calls(self, frames, routines):
        """Every call of the named routines over so many frames, with the
        frame it came in and its first six bytes of arguments -- read off
        the stack at the routine's first instruction, where the first is at
        [SP + 2]: [(frame, routine, args)]."""
        where = {self.syms[r]: r for r in routines}
        for a in where:
            self.m.breakpoints.add(a)
        out = []
        try:
            end = self.m.frames + frames
            while self.m.frames < end:
                why = self.m.run(budget=400_000)
                if why == "breakpoint" and self.m.cpu.pc in where:
                    sp = self.m.cpu.sp
                    out.append((self.m.frames, where[self.m.cpu.pc], list(self.m.bus.mem[sp + 2:sp + 8])))
                    for a in where:
                        self.m.breakpoints.discard(a)
                    self.m.tick()
                    for a in where:
                        self.m.breakpoints.add(a)
        finally:
            for a in where:
                self.m.breakpoints.discard(a)
        return out

    def array(self, n, count):
        """A byte array of the program's, in one read."""
        return self.m.bus.mem[self.addr(n):self.addr(n) + count]

    def bitmap_diff(self):
        """The field's pixels that are not what the program's own state says
        should be there -- each character at rest drawn where its slot says
        it is drawn, each star it says is lit, and the band's backdrop as
        its copy in VRAM holds it -- as (x, y, have, want); an empty list is
        a bitmap no list left a pixel behind in. VRAM and the arrays are read
        once each: the client's reads are a round trip apiece."""
        import mkgalaga as A
        if not hasattr(self, "_fimgs"):
            s = A.Sheet("sprites")
            self._fimgs = [A.grid_cell(s, c, A.ROWS[n]) for n, c in A.FORMATION]
        fx, fw = self.c("FX"), self.c("FW")
        want = [[0] * fw for _ in range(240)]
        by, bh = self.c("BAND_Y"), self.c("BAND_H")
        bram = self.m.video.vram[self.c("BD_VRAM"):self.c("BD_VRAM") + bh * 112]
        for y in range(bh):
            row = want[by + y]
            for x in range(224):
                b = bram[y * 112 + (x >> 1)]
                row[x] = b >> 4 if x % 2 == 0 else b & 15
        ns = self.c("NSLOT")
        on, fr, sx, sy = (self.array(n, ns) for n in ("sl_on", "sl_fr", "sl_x", "sl_y"))
        for i in range(ns):
            if on[i]:
                img = self._fimgs[fr[i]]
                for y in range(16):
                    for x in range(16):
                        if img[y][x]:
                            want[sy[i] + y][sx[i] + x] = img[y][x]
        n = self.c("NSTAR")
        son, stx, sty, stc = (self.array(k, n) for k in ("st_on", "st_x", "st_y", "st_c"))
        for i in range(n):
            if son[i]:
                assert want[sty[i]][stx[i]] == 0, "star %d lit on a drawn pixel %d,%d" % (i, stx[i], sty[i])
                want[sty[i]][stx[i]] = stc[i]
        vram = self.m.video.vram[0:240 * 160]
        out = []
        for y in range(240):
            for x in range(fw):
                sxx = fx + x
                b = vram[y * 160 + (sxx >> 1)]
                have = b >> 4 if sxx % 2 == 0 else b & 15
                if have != want[y][x]:
                    out.append((sxx, y, have, want[y][x]))
        return out

    def flights(self, frames, each=None):
        """Every moving flyer's arcade sprite position after each of so many
        frames of play, from the stage's start: {obj: [(frame, x, y9)]}, the
        frame counted from the stage's first (`stage_frames`), and the frame
        each object was launched on. `each()` is called after every frame."""
        n = self.c("NFLY")
        tracks, launched, seen = {}, {}, set()
        for f in range(frames):
            self.m.run_frame(1)
            if each:
                each()
            self.at_rest()
            loops = self.uword("stage_frames")
            on, obj, x8 = (self.array(k, n) for k in ("fl_on", "fl_obj", "fl_x8"))
            y9 = self.m.bus.mem[self.addr("fl_y9"):self.addr("fl_y9") + 2 * n]
            st = self.array("fl_state", n)
            for k in range(n):
                if st[k] and obj[k] not in seen:
                    seen.add(obj[k])
                    launched[obj[k]] = loops
                if on[k]:
                    tracks.setdefault(obj[k], []).append((loops, x8[k], y9[2 * k] | (y9[2 * k + 1] << 8)))
        return tracks, launched

    def spared_frame(self, catch=False):
        """A frame of play in which the fighter cannot be destroyed or
        captured: each call of FighterHit and of Caught returned from at its
        first instruction, as the reference's `fighter_dies=False` leaves
        its fighter -- or, with `catch`, only destroyed. Ends at the
        loop's next WaitVBlank, as at_rest does; returns the calls skipped."""
        wv, hit, caught = self.syms["WaitVBlank"], self.syms["FighterHit"], self.syms["Caught"]
        skipped = 0
        if self.m.cpu.pc == wv:
            self.m.tick()
        self.m.breakpoints.update((wv, hit) if catch else (wv, hit, caught))
        try:
            while True:
                why = self.m.run(budget=4_000_000)
                assert why == "breakpoint", why
                if self.m.cpu.pc == wv:
                    return skipped
                sp = self.m.cpu.sp
                self.m.cpu.pc = self.m.bus.mem[sp] | (self.m.bus.mem[sp + 1] << 8)
                self.m.cpu.sp = sp + 2
                skipped += 1
        finally:
            self.m.breakpoints.discard(wv)
            self.m.breakpoints.discard(hit)
            self.m.breakpoints.discard(caught)

    def capture(self, frames=6000, seen=None):
        """Plays on, the fighter left where it is and spared bombs and
        rammers but not the beam, until a capture boss has taken it and gone
        home and the next fighter is on its way: {event: stage frame} for
        beam (fully out), pull, text, home and after, with `seen(event)`
        called at each."""
        out = {}
        for f in range(frames):
            self.spared_frame(catch=True)
            s1, dead, home, pull = self.byte("cap_s1"), self.byte("ftr_dead"), self.byte("cap_home"), self.byte("cap_pull")
            key = None
            if self.byte("cap_ph") == 2 and s1 == 0x40 and "beam" not in out:
                key = "beam"
            elif dead == 5 and pull == 1 and self.uword("ftr_y9") < 0x110 and "pull" not in out:
                key = "pull"
            elif home == 2 and self.byte("tx_y") and "text" not in out:
                key = "text"
            elif home == 2 and not self.byte("tx_y") and self.byte("cap_n") > 20 and "home" not in out:
                key = "home"
            elif "home" in out and dead in (1, 2, 3) and "after" not in out:
                key = "after"
            if key:
                out[key] = self.uword("stage_frames")
                if seen:
                    seen(key)
            if "after" in out:
                break
        return out

    def attack(self, frames, until=None, spare=False, each=None):
        """What flies and falls after each of so many frames of play, from
        wherever the game is: [(stage frame, dives on, fighter's state,
        sorted [(obj, x, y9)] of the moving flyers, sorted [(x, y9)] of the
        bombs), the flyers' states, which sprites of each bombs have]. Stops early when `until()` says so; `spare` plays the
        frames with spared_frame; `each()` is called before every frame."""
        n, nb = self.c("NFLY"), self.c("NBOMB")
        out = []
        for f in range(frames):
            if each:
                each()
            if spare:
                self.spared_frame()
            else:
                self.m.run_frame(1)
                self.at_rest()
            on, obj, x8 = (self.array(k, n) for k in ("fl_on", "fl_obj", "fl_x8"))
            y9 = self.m.bus.mem[self.addr("fl_y9"):self.addr("fl_y9") + 2 * n]
            bon, bx = self.array("bo_on", nb), self.array("bo_x", nb)
            by = self.m.bus.mem[self.addr("bo_y"):self.addr("bo_y") + 2 * nb]
            out.append((self.uword("stage_frames"), self.byte("dv_on"), self.byte("ftr_dead"),
                        sorted((obj[k], x8[k], y9[2 * k] | (y9[2 * k + 1] << 8)) for k in range(n) if on[k]),
                        sorted((bx[k], by[2 * k] | (by[2 * k + 1] << 8)) for k in range(nb) if bon[k]),
                        list(self.array("fl_state", n)), list(self.array("fl_bm", n))))
            if until and until():
                break
        return out

    def split(self, frames=3):
        """Which raw raster lines the palette's last eight were written on,
        and with what, over so many frames: [(line, entry, $0RGB)]."""
        self.m.pal_log_start()
        self.m.run_frame(frames)
        return [(ln, e, v) for _, ln, e, v in self.m.pal_log()]

    def png(self, name):
        path = os.path.join(H.BUILD, name + ".png")
        H.shot(self.m, path)
        return path


def sound_check():
    """A new game's start theme as voices 0-2 play it, frame by frame, against
    tools/galaga_sound.py's rendering: (frames compared, frames that differ,
    the first difference)."""
    import galaga_sound as S
    g = Game(tag="gal_sound", render=False)
    g.m.run_frame(20)
    g.tap(SPACE)
    g.until(lambda: g.byte("snd_on", 0x0B), 60)
    want = S.render(0x0B, chain=False)
    seen = []
    for f in range(len(want[0]) + 8):
        g.m.run_frame(1)
        snd = g.m.sound()
        seen.append([(snd[8 * v] | (snd[8 * v + 1] << 8), snd[8 * v + 4] & 15, snd[8 * v + 5] & 0x40) for v in range(3)])
    # where sampling starts against the stream's first frame depends on when
    # the poll above saw the sound begin: align on the notes, either way
    rows = [[(0 if hz is None else min(65535, round(S.target_increment(hz))), 0 if hz is None else vol)
             for (_, hz, vol) in (want[v][f] for v in range(3))] for f in range(len(want[0]))]
    best = None
    for lag in range(-3, 4):
        bad = []
        for f, row in enumerate(rows):
            if not 0 <= f + lag < len(seen):
                continue
            got = seen[f + lag]
            for v in range(3):
                inc, vol = row[v]
                ginc, gvol, on = got[v]
                if (vol and (ginc, gvol) != (inc, vol)) or (not vol and on and gvol):
                    bad.append((f, v, row[v], got[v]))
        if best is None or len(bad) < len(best[1]):
            best = (lag, bad)
    lag, bad = best
    return len(rows), len(bad), lag, bad[:3]


def compare_flights(g, stage, frames, each=None):
    """The game's flights of a stage from its first frame, each object held
    to tools/galaga_paths.py's machine flying it from the frame the game
    launched it on -- so an object a full set of flyers kept waiting is
    compared too, the formation's sway depending only on the stage's frame.
    Returns (objects that matched, [(obj, what differed)])."""
    import random
    import galaga_paths as P
    tracks, launched = g.flights(frames, each)
    _, _, table = P.build_wave_table(stage, 3, random.Random(stage))
    token = {}
    i = 0
    while i < len(table):
        if table[i] in (0x7E, 0x7F):
            i += 1
            continue
        raw = table[i + 1]
        obj = raw & ~0x40 if (raw & 0x78) == 0x78 else raw
        token[obj] = table[i]
        i += 2
    same, bad = 0, []
    for obj, tick in sorted(launched.items(), key=lambda kv: kv[1]):
        m = P.Machine(frame0=0)
        m.form.sway_active = True
        m.f2916_active = True

        def hook(mm, obj=obj, tick=tick):
            if mm.tick == tick:
                slot = next(s.idx for s in mm.slots if not s.b[0x13] & 1)
                mm.launch_entry(slot, obj, token[obj])
        m.hooks.append(hook)
        for _ in range(tick + 400):
            m.step()
            recs = m.tracks.get(obj, [])
            if recs and recs[-1]["event"] and ("HOME" in recs[-1]["event"] or "END" in recs[-1]["event"]):
                break
        want = {r["tick"]: (r["x"], r["y"]) for r in m.tracks.get(obj, [])
                if r["moved"] and "HOME" not in (r["event"] or "") and r["tick"] <= frames}
        have = {t: (x, y) for t, x, y in tracks.get(obj, [])}
        wrong = [(t, want[t], have.get(t)) for t in sorted(want) if want[t] != have.get(t)]
        if wrong:
            bad.append((obj, "%d of %d frames differ, first at frame %d: reference %s, game %s"
                        % (len(wrong), len(want), wrong[0][0], wrong[0][1], wrong[0][2])))
        else:
            same += 1
    return same, bad


def compare_dives(g, stage, frames, kill_every=0):
    """A stage from its first frame, the fighter left where it starts and
    spared, against tools/galaga_dives.py's machine: every frame's moving
    flyers and falling bombs, up to the first time an enemy flies into the
    fighter -- a bomb that touches it is gone in both, and nothing else. The
    machine's entry is the game's -- each object launched on the frame the
    game launched it, the dives enabled on the game's frame -- since six
    flyers hold a wave back where the arcade's twelve do not; from there
    the machine decides everything. Returns (frames compared, the frame the
    dives began, the frame an enemy reached the fighter or None,
    [(frame, what differed)], the bombs and dives the game had no sprites
    left for, the frames compared with continuous bombing on)."""
    import random
    import galaga_dives as D
    fx8 = g.word("fx") + 17
    kills = {}

    def kill():
        # every kill_every frames of the dives, the first bee or butterfly
        # at rest is gone from the formation -- its count, not its picture
        f = g.uword("stage_frames")
        if not kill_every or not g.byte("dv_on") or f % kill_every:
            return
        for obj in list(range(0x08, 0x30, 2)) + list(range(0x40, 0x60, 2)):
            slot = g.byte("obj_slot", obj >> 1)
            if slot != 255 and g.byte("sl_on", slot) and not g.byte("sl_wait", slot):
                g.poke("sl_on", 0, slot)
                kills[f + 1] = obj
                return
    have = g.attack(frames, spare=True, each=kill)
    launched, began, before = {}, None, set()
    for f, on, dead, flyers, bombs, _, _ in have:
        if began is None and on:
            began = f
        now = set(obj for obj, _, _ in flyers)
        if began is None:
            for obj in sorted(now - before):
                launched.setdefault(f, []).append(obj)
        before = now
    hit = None
    _, _, table = D.gp.build_wave_table(stage, 3, random.Random(stage))
    entries, i = [], 0
    while i < len(table):
        if table[i] in (0x7E, 0x7F):
            i += 1
            continue
        raw = table[i + 1]
        entries.append((raw & ~0x40 if (raw & 0x78) == 0x78 else raw, table[i]))
        i += 2

    class Follow(D.AttackMachine):
        def f_2916(self):
            for obj in launched.get(self.tick, []):
                sl = next(s for s in self.slots if not s.b[0x13] & 1)
                want, tok = entries.pop(0)
                assert want == obj, "frame %d: the game launched %02X where the waves have %02X" % (self.tick, obj, want)
                s = self.launch_entry(sl.idx, obj, tok)
                s.b[0x0F] = 0 if (obj & 0x38) == 0x38 else (self.hdr1 if D.BOMB_FLAG.get(obj, 0) else 0)
            if self.tick == began:
                self.f2916_active = False
                self.f1A80_active = self.f1B65_active = True
                self.form.nestlr_inh = 1
                self.attack_start_tick = self.tick

    def shoot(mm):
        if mm.tick in kills:
            assert mm.state[kills[mm.tick]] == 1, "frame %d: %02X is not at rest in the reference" % (mm.tick, kills[mm.tick])
            mm.shoot(kills[mm.tick])
    m = Follow(stage, 3, lambda t: fx8, 0, stage, entry_fighter_x=fx8, hooks=(shoot,))
    bad, n, lost, cont = [], 0, 0, 0
    for f, on, dead, flyers, bombs, states, bm in have:
        while m.tick < f:
            m.step()
        if any(e["kind"] == "collision_enemy" for e in m.events):
            hit = f
            break
        # a diver the reference launched this frame that the game had no
        # slot for -- each flying, or holding bombs -- stays at rest in the
        # game: put back in the reference too
        if all(st in (3, 7, 9) or b for st, b in zip(states, bm)):
            for e in m.events:
                if e["kind"] == "launch" and e["tick"] == f and e["obj"] not in [o for o, _, _ in flyers]:
                    sl = next(sl for sl in m.slots if sl.b[0x13] & 1 and sl.b[0x10] == e["obj"])
                    sl.b[0x13] = 0
                    m.state[e["obj"]] = 1
                    m.spr_x[e["obj"]], m.spr_y[e["obj"]] = m.form.slot_xy(e["obj"])
                    m.flying_cnt -= 1
                    lost += 1
        divers = sorted((sl.b[0x10], m.spr_x[sl.b[0x10]], m.spr_y[sl.b[0x10]]) for sl in m.slots if sl.b[0x13] & 1)
        # a bomb the reference dropped this frame that the game had no
        # sprite for -- twenty-six less four a flying slot and one a bomb
        # left none -- is not dropped in the game: taken out of the
        # reference too, so that what follows is still compared
        # (a bomb the fighter took this frame still had its sprite at the
        # drop, and a flyer home this frame may have been flying then)
        taken = sum(1 for e in m.events if e["kind"] == "collision_bomb" and e["tick"] == f)
        home = sum(1 for e in m.events if e["kind"] == "home" and e["tick"] == f)
        if divers == flyers and 26 - 4 * (sum(st in (3, 7, 9) for st in states) + home) - len(bombs) - taken <= 0:
            for e in m.events:
                if e["kind"] == "bomb" and e["tick"] == f:
                    bo = D.BOMB_OBJS[e["bomb"]]
                    if (m.spr_x[bo], m.spr_y[bo]) not in bombs:
                        m.state[bo], m.spr_x[bo] = 0x80, 0
                        lost += 1
        falling = sorted((m.spr_x[bo], m.spr_y[bo]) for bo in D.BOMB_OBJS if m.state[bo] == 6 and m.spr_x[bo])
        n += 1
        cont += m.cont_bomb
        if (divers, falling) != (flyers, bombs):
            bad.append((f, "reference %s %s, game %s %s, the game's flyers' states %s"
                        % (divers, falling, flyers, bombs, have[[h[0] for h in have].index(f)][5])))
    return n, began, hit, bad, lost, cont


def sizes():
    """Where the PRG's bytes are: each symbol's span to the next, the
    largest first, and the totals of code and of data."""
    src = sources()
    prg, syms = H.try_build_act(src, "gal_sizes")
    org = prg[0] | (prg[1] << 8)
    end = org + len(prg) - 2
    # constants are not places, and a routine's local labels are its own
    marks = sorted((a, n) for n, a in syms.items() if org <= a < end and not n.startswith("c_"))
    by = {}
    for (a, n), (b, _) in zip(marks, marks[1:] + [(end, None)]):
        key = n.split(".")[0]
        by[key] = by.get(key, 0) + b - a
    spans = [(z, n) for n, z in by.items() if z]
    data = sum(z for z, n in spans if n.startswith(("v_", "a_", "str_")))
    print("PRG %d bytes: %d in data, %d in code" % (len(prg) - 2, data, len(prg) - 2 - data))
    for z, n in sorted(spans, reverse=True)[:40]:
        print("  %6d  %s" % (z, n))


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "play"
    if what == "sizes":
        return sizes()
    g = Game(tag="gal_" + "_".join(sys.argv[1:]))
    print("PRG %d bytes, %04X-%04X" % (len(g.prg) - 2, g.org, g.end))
    g.m.run_frame(30)
    print(g.png("gal_title"))
    g.start()
    print(g.png("gal_start"), "loops", g.uword("loops"))
    if what == "play":
        for i in range(4):
            g.m.run_frame(60)
            print(g.png("gal_play%d" % i), "loops", g.uword("loops"), "frames", g.m.frames)
    elif what == "levels":
        for k in range(4):
            h = Game(tag="gal_levels%d" % k)
            h.start()
            if k:
                h.goto_stage(1 + 4 * k)
            h.m.run_frame(400)
            print(h.png("gal_level%d" % k))
    elif what == "shoot":
        # under each column in turn, a shot at it, until eight have hit
        s0 = g.uword("score10")
        if "trace" in sys.argv:
            fx0 = g.c("FX")
            for col in (0, 3, 4, 5, 9, 2, None, None, None):
                if col is not None:
                    g.pokew("fx", g.byte("col_x", col))
                    g.m.kbd.feed(SPACE)
                for f in range(10):
                    g.m.run_frame(1)
                    if f == 1 and col is not None:
                        g.m.kbd.feed([0xF0] + SPACE)
                    g.at_rest()
                    boxes = [(g.byte("bm_x", b), g.byte("bm_y", b), g.byte("bm_f", b))
                             for b in range(g.c("NBOOM")) if g.byte("bm_on", b)]
                    stray = [p for p in g.bitmap_diff()
                             if not any(bx <= p[0] - fx0 < bx + 32 and by <= p[1] < by + 32 for bx, by, _ in boxes)]
                    if stray:
                        print("frame %d, column %s: %d stray, e.g. %s; explosions %s"
                              % (g.m.frames, col, len(stray), stray[:4], boxes))
                        sx0, sy0 = stray[0][0] - fx0, stray[0][1]
                        import mkgalaga as A
                        vram = g.m.video.vram[0:38400]
                        for i in range(g.c("NSLOT")):
                            if g.byte("sl_on", i):
                                x0, y0 = g.byte("sl_x", i), g.byte("sl_y", i)
                                if x0 <= sx0 < x0 + 16 and y0 <= sy0 < y0 + 16:
                                    print("slot %d col %d row %d at %d,%d frame %d (target %d,%d)" % (
                                        i, g.byte("sl_col", i), g.byte("sl_row", i), x0, y0, g.byte("sl_fr", i),
                                        g.byte("col_x", g.byte("sl_col", i)), g.byte("row_y", g.byte("sl_row", i))))
                                    for yy in range(-1, 17):
                                        row = ""
                                        for xx in range(-1, 17):
                                            X, Y = fx0 + x0 + xx, y0 + yy
                                            b = vram[Y * 160 + (X >> 1)]
                                            row += "%X" % (b >> 4 if X % 2 == 0 else b & 15)
                                        print("   " + row)
                        return
            print("no stray pixel outside a live explosion")
            return
        apart = "apart" in sys.argv
        for col in (0, 3, 4, 5, 9, 2):
            g.pokew("fx", g.byte("col_x", col))
            g.tap(SPACE)
            g.m.run_frame(10)
            if apart:
                g.until(lambda: g.byte("booms") == 0, 120)
                g.at_rest()
                print("  column %d: %d differ" % (col, len(g.bitmap_diff())))
        print(g.png("gal_shoot"), "score", g.uword("score10") * 10, "booms", g.byte("booms"))
        g.until(lambda: g.byte("booms") == 0, 120)
        g.at_rest()
        d = g.bitmap_diff()
        on = sum(g.byte("sl_on", i) for i in range(g.c("NSLOT")))
        print("after the explosions: %d characters, score %d, %d pixels differ %s"
              % (on, (g.uword("score10") - s0) * 10, len(d), d[:6]))
    elif what == "shoot1":
        # one shot, the bitmap checked before it, as it hits, and after
        col = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        g.at_rest()
        print("before: %d pixels differ" % len(g.bitmap_diff()))
        g.pokew("fx", g.byte("col_x", col))
        g.tap(SPACE)
        g.until(lambda: g.byte("booms") > 0, 60)
        print("hit at frame %d, slots on %d" % (g.m.frames, sum(g.byte("sl_on", i) for i in range(g.c("NSLOT")))))
        for step in range(8):
            g.m.run_frame(3)
            g.at_rest()
            d = g.bitmap_diff()
            print("  booms %d frame %d: %d differ, e.g. %s" % (g.byte("booms"), g.byte("bm_f"), len(d), d[:4]))
    elif what == "flights":
        g = Game(tag="gal_flights")
        g.start()
        same, bad = compare_flights(g, 1, 1500)
        print("stage 1's %d objects all home by frame %d" % (sum(g.byte("sl_on", i) for i in range(g.c("NSLOT"))),
                                                           g.uword("loops")))
        for obj, why in bad:
            print("obj %02X: %s" % (obj, why))
        print("%d objects fly the reference's path exactly, frame for frame; %d do not" % (same, len(bad)))
    elif what == "dives":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        if n > 1:
            g.goto_stage(n)
        frames = int(sys.argv[3]) if len(sys.argv) > 3 else 1200
        kill_every = int(sys.argv[5]) if len(sys.argv) > 5 else 0
        if len(sys.argv) > 4:
            g.pokew("fx", int(sys.argv[4]))
        count, began, hit, bad, lost, cont = compare_dives(g, n, frames, kill_every)
        print("stage %d: dives began at frame %s, an enemy reached the fighter at %s; %d frames compared, %d differ;"
              " %d bombs and dives the sprites ran out for; %d frames of continuous bombing; %d enemies left"
              % (n, began, hit, count, len(bad), lost, cont, g.byte("en_nbr")))
        for f, why in bad[:6]:
            print("  frame %d: %s" % (f, why))
        print(g.png("gal_dives%d" % n))
    elif what == "bombs":
        # stage n from frame a to b: the flyers' states, the bombs and whose sprites they have
        n, a, b = (int(v) for v in sys.argv[2:5])
        if n > 1:
            g.goto_stage(n)
        if len(sys.argv) > 5:
            g.pokew("fx", int(sys.argv[5]))
        while g.uword("stage_frames") < a:
            g.spared_frame()
        while g.uword("stage_frames") <= b:
            g.spared_frame()
            nb = g.c("NBOMB")
            print(g.uword("stage_frames"), "states", list(g.array("fl_state", 6)), "fl_bm", list(g.array("fl_bm", 6)),
                  "own", g.byte("bo_own"), "on", list(g.array("bo_on", nb)), "sp", list(g.array("bo_sp", nb)),
                  "be", list(g.array("fl_be", 6)), "bf", list(g.array("fl_bf", 6)), "gt1", g.byte("gt", 1))
    elif what == "attack":
        # the autopilot into the dives: a picture every 90 frames once they are on
        g.autopilot(3000, until=lambda: g.byte("dv_on"))
        for i in range(4):
            g.autopilot(90)
            print(g.png("gal_attack%d" % i), "score", g.uword("score10") * 10, "lives", g.byte("lives"),
                  "dead", g.byte("ftr_dead"), "enemies", g.byte("en_nbr"))
    elif what == "sound":
        # the start theme on voices 0-2 against the rendered streams
        print(sound_check())
    elif what == "capture":
        # the fighter left still, spared bombs but not the beam: the capture
        # boss's beam, the fighter taken up, FIGHTER CAPTURED, and home
        g.pokew("fx", 104)
        ev = g.capture(seen=lambda k: print(k, g.uword("stage_frames"), g.png("gal_capture_" + k)))
        print(ev, "captured fighters at rest in slots", [i for i in range(4) if g.byte("sl_on", i)],
              "lives", g.byte("lives"))
    elif what == "results":
        # the game given up to the last fighter: GAME OVER and the results
        g.poke("lives", 0)
        g.pokew("shots", 40)
        g.pokew("hits", 29)
        g.until(lambda: g.byte("ftr_on"), 900)
        g.at_rest()
        g.drop_on_fighter()
        g.until(lambda: g.byte("game_over"), 900)
        g.m.run_frame(30)
        print(g.png("gal_results"), "game over", g.byte("game_over"))
    elif what == "death":
        g.until(lambda: g.crash() is not None, 200)
        g.until(lambda: g.byte("ftr_dead"), 10)
        g.m.run_frame(6)
        print(g.png("gal_death"), "dead", g.byte("ftr_dead"), "lives", g.byte("lives"))
        g.until(lambda: g.byte("ftr_dead") == 0, 400)
        print("back in play: lives", g.byte("lives"), "fx", g.word("fx"))
    elif what == "challenge":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        g.goto_stage(n)
        g.m.run_frame(90)
        print(g.png("gal_challenge%d" % n))
        g.autopilot(2400, until=lambda: g.byte("stage") != n)
        print("stage now", g.byte("stage"), "hits", g.byte("ch_hits"), "score", g.uword("score10") * 10)
    elif what == "split":
        log = g.split()
        print("%d commits; lines %s" % (len(log), sorted(set(ln for ln, _, _ in log))))
        print(log[:20])
    elif what == "bitmap":
        for i in range(12):
            g.m.run_frame(37)
            g.at_rest()
            d = g.bitmap_diff()
            print("after %4d frames: %d pixels differ %s" % (g.m.frames, len(d), d[:6]))
    elif what == "intro":
        # the work of the frames under PLAYER 1, from the space bar
        h = Game(tag="gal_intro")
        h.m.run_frame(20)
        h.tap(SPACE)
        costs, (work, p) = h.frame_work(60)
        print("intro frames, thousands of clocks:", " ".join("%d" % (c // 1000) for c in costs))
        print(p.report(top=8))
    elif what == "profile":
        # profile [stage] [frames first, the fighter at the left and spared]
        if len(sys.argv) > 2:
            n = int(sys.argv[2])
            if n > 1:
                g.goto_stage(n)
            g.pokew("fx", 1)
            for _ in range(int(sys.argv[3]) if len(sys.argv) > 3 else 0):
                g.spared_frame()
        costs, (work, p) = g.frame_work(240, spare=len(sys.argv) > 2)
        print("work per frame over %d frames: mean %d, max %d clocks (%.0f%% of a frame)"
              % (len(costs), sum(costs) // len(costs), max(costs), 100 * max(costs) / FRAME))
        print("the frames, in thousands of clocks:")
        for i in range(0, len(costs), 24):
            print("  " + " ".join("%3d" % (c // 1000) for c in costs[i:i + 24]))
        print("the busiest frame:")
        print(p.report(top=12))


if __name__ == "__main__":
    main()
