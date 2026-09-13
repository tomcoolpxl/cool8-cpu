"""Galaga's (Namco, 1981) attack phase: the dive scheduler, boss sorties with escorts, enemy
bombs, the fighter's collisions, scoring and the death/respawn sequence.

    python tools/galaga_dives.py      stage 1's first twenty seconds of attacks as
                                      sim/build/attack_stage1.png, and the events printed

**The reference GALAGA's dives and bombs are held to**, as sim/test_action.py
holds the game's divers and bombs to `simulate_attack()` frame by frame.
tools/mkgalaga.py takes the scheduler's tables from here. It extends the
reference interpreter in tools/galaga_paths.py with the main-CPU and
sub-CPU code that decides *when* and *who* dives, from the hackbar/galaga
disassembly (line references beside each):

  f_0857   (game_ctrl.s:1386)  per-frame parameter -> timer reloads, bomb flags, max bombers
  f_1B65   (gg1-2_fx.s:857)    dive launcher: bmbr_boss_pool, 3 sortie timers, selection
  j_1CAE / c_1D03 (gg1-2_fx.s:1175/1275)  boss + escort selection, bonus score code
  f_1A80   (gg1-2_fx.s:681)    bonus-bee ("clone attack") launcher, stage >= 4
  f_08D3 bomb counters b0E/b0F + l_0D8D_got_a_bullet (gg1-5.s:2345-2461)
  f_1EA4   (gg1-2_fx.s:1737)   bomb motion
  c_23E0   (gg1-3.s:766)       object states, active-enemy count, off-screen culling
  f_05EE / hitd_det_fghtr (gg1-5.s:654/838)  fighter vs enemy / bomb collision
  hitd_det_rckt (gg1-5.s:1059) rocket vs enemy test (function rocket_hits)
  hitd_dspchr + gctl_supv_score (gg1-5.s:1177, game_ctrl.s:1084)  scoring
  gctl_stg_restart_hdlr / c_player_respawn (game_ctrl.s:508, gg1-2.s:1009)  death + respawn

Randomness: NONE in this phase.  The only call of the ROM's pseudo-random routine c_1000
(R register + frame counter + ROM byte, gg1-2.s:33) is in c_25A2 (gg1-3.s:1289), which places
the entry-wave transients.  `rng_seed` feeds that placement only (it changes stage-4+ entry
timing, hence stage time and frame phase at the start of the attack phase).  Given the stage,
rank, the frame-counter phase `frame0` and the fighter X trajectory, the attack phase is
deterministic.

"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import random                                   # noqa: E402
import galaga_paths as gp                       # noqa: E402
from galaga_paths import (Machine, HPOS, c_0EAA, stage_parms, stage_row,   # noqa: E402
                          build_wave_table, D_1D2C_WINGMEN, D_2908, D_290E)

# ============================================================================
# ROM tables (line references to the hackbar/galaga listing)
# ============================================================================
# game_ctrl.s:1503-1513  d_08CD  red-butterfly sortie timer reload [parm2*3 + tmrIdx]
D_08CD = [0x09, 0x07, 0x05, 0x08, 0x06, 0x04, 0x07, 0x05, 0x04, 0x06, 0x04, 0x03, 0x05, 0x03, 0x03,
          0x04, 0x03, 0x03, 0x04, 0x02, 0x02, 0x03, 0x03, 0x02, 0x03, 0x02, 0x02, 0x02, 0x02, 0x02]
# game_ctrl.s:1514-1524  d_08EB  bee sortie timer reload [parm3*3 + tmrIdx]
D_08EB = [0x06, 0x05, 0x04, 0x05, 0x04, 0x03, 0x05, 0x03, 0x03, 0x04, 0x03, 0x02, 0x04, 0x02, 0x02,
          0x03, 0x03, 0x02, 0x03, 0x02, 0x01, 0x02, 0x02, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01, 0x01]
# game_ctrl.s:1527-1539  d_0909 (bomb flags, [parm0*4 + enemies//10]) and d_0929 (boss timer,
# [32 + parm1*4 + enemies//10]) are one contiguous table; index 44 (parm1=2, >=40 enemies)
# runs into the first opcode byte of f_0935 (0x3A, game_ctrl.s:1555 'ld a,(nn)'); the listing
# has nothing between d_0929 and f_0935, so this is what the ROM reads.
D_0909 = [0x03, 0x03, 0x01, 0x01, 0x03, 0x03, 0x03, 0x01, 0x07, 0x03, 0x03, 0x01, 0x07, 0x03, 0x03, 0x03,
          0x07, 0x07, 0x03, 0x03, 0x0F, 0x07, 0x03, 0x03, 0x0F, 0x07, 0x07, 0x03, 0x0F, 0x07, 0x07, 0x07,
          0x06, 0x0A, 0x0F, 0x0F, 0x04, 0x08, 0x0D, 0x0D, 0x04, 0x06, 0x0A, 0x0A, 0x3A]
# gg1-2_fx.s:1255-1258  d_1CFD  boss bonus code by escort count (ixl): (add to hit_mult[15], score sprite)
D_1CFD = [(16 - 3, 0x80 + 0x3A), (8 - 3, 0x80 + 0x37), (4 - 3, 0x80 + 0x35)]
# gg1-2_fx.s:837-844  bonus-bee trio bonus (hit_mult[15] add) and paths, by colour 4/5/6
D_1B59 = [(0x1E, 0xBD), (0x0A, 0xB8), (0x14, 0xBC)]
D_1B5F = ['db_04EA', 'db_0473', 'db_04AB']
# game_ctrl.s:1288-1290  d_scoreman_inc_lut, indexed [15 - colour]; BCD tens/hundreds nibbles
_LUT = [0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x50, 0x08, 0x08, 0x08, 0x05, 0x08, 0x15, 0x00]
SCORE_PER_COUNT = [((_LUT[15 - i] >> 4) * 100 + (_LUT[15 - i] & 15) * 10) for i in range(16)]
# -> colour 1 (hit boss) 150, 2 (red butterfly) 80, 3 (bee) 50, 4/5/6 (bonus bees) 80,
#    7 (captured red fighter) 500, slot 15 = 100 per count (bonus increments)

FIGHTER_Y9 = 0x129          # gg1-2.s:1051-1062 (sprite Y 297, non-flipped)
BOMB_OBJS = [0x68 + 2 * n for n in range(8)]
BOSS_FOR_B = {4: 0x30, 3: 0x34, 2: 0x36, 1: 0x32}   # c_1C8D ordinal -> boss id


def bomb_flag_bits():
    """c_2896/c_28E9 (gg1-3.s:1573-1625): bit7 'may bomb during entry' per object, MSB-first
    from d_2908 for ids 08-2E, 30-3E, 40-5E."""
    bits = []
    for byte in D_2908:
        for k in range(8):
            bits.append((byte >> (7 - k)) & 1)
    flags = {}
    i = 0
    for rng in (range(0x08, 0x30, 2), range(0x30, 0x40, 2), range(0x40, 0x60, 2)):
        for o in rng:
            flags[o] = bits[i]
            i += 1
    return flags


BOMB_FLAG = bomb_flag_bits()


def rocket_hits(obj_x, obj_y9, rkt_x, rkt_y9, two_ship=False):
    """hitd_det_rckt (gg1-5.s:1085-1126), exact.  Coordinates are sprite registers."""
    dy = ((obj_y9 >> 1) - (rkt_y9 >> 1)) & 0xFF
    if ((dy - 3) & 0xFF) + 6 <= 0xFF:              # (obj.y>>1)-(rkt.y>>1) in [-3, +2]
        return False
    dx = (obj_x - rkt_x) & 0xFF
    if not two_ship:
        return ((dx - 6) & 0xFF) + 11 > 0xFF       # obj.x-rkt.x in [-5, +5]
    a = ((dx - 20) & 0xFF) + 11                    # [9, 19]
    if a > 0xFF:
        return True
    a += 4                                         # [5, 8] -> miss
    if a > 0xFF:
        return False
    return ((a & 0xFF) + 11) > 0xFF                # [-6, +4]


def fighter_touches(obj_x, obj_y9, fx, fy9=FIGHTER_Y9):
    """hitd_det_fghtr (gg1-5.s:857-872), exact: |dx| <= 6 and (y>>1) difference in [-3, +3]."""
    if obj_x == 0:
        return False
    if ((obj_x - fx - 7) & 0xFF) + 13 <= 0xFF:
        return False
    return ((((obj_y9 >> 1) - (fy9 >> 1) - 4) & 0xFF) + 7) > 0xFF


# ============================================================================
# The attack-phase machine
# ============================================================================
class AttackMachine(Machine):

    def __init__(self, stage=1, rank=3, fighter_x_fn=None, frame0=0, rng_seed=0,
                 fighter_dies=False, ships=3, keep_tracks=False, hooks=(), entry_fighter_x=0x7A):
        parms = stage_parms(stage, rank)
        super().__init__(frame0=frame0, parm8=parms[8], parm9=parms[9])
        self.stage, self.rank, self.parms = stage, rank, parms
        self.kind = stage_row(stage, rank)[0]
        self.challenge = self.kind == 'challenge'
        self.hdr0, self.hdr1, self.wave_table = build_wave_table(stage, rank, random.Random(rng_seed))
        self.fighter_x_fn = fighter_x_fn or (lambda t: 0x7A)
        self.fighter_dies, self.ships, self.keep_tracks = fighter_dies, ships, keep_tracks
        self.user_hooks = list(hooks)
        self.entry_fighter_x = entry_fighter_x
        # --- stg_init_env (task_man.s:256-310) + c_2C00 (new_stage.s:100-103)
        self.game_tmrs = [2, 0, 120, 0]
        self.timers = [0x16, 0x02, 0x02]        # b_92C0[0..2]: boss, red, bee (in decrement order)
        self.reload = [0, 0, 0]                 # b_92C0[4..6]
        self.bomb_flags = 0                     # b_92C0[8]
        self.pool = [[0xFF, None] for _ in range(4)]   # bmbr_boss_pool (game_ctrl.s:63 memset FF)
        self.cflag, self.cobj, self.wingm = 0, 1, 0
        self.bbee_obj, self.bbee_tmr, self.bbee_clr = 1, 0, 0
        self.x3cfg = [0, 0, 0]
        self.boss_scode = {0: D_1CFD[2], 2: D_1CFD[2], 4: D_1CFD[2], 6: D_1CFD[2]}
        self.glbl_enemy_enbl = 3
        self.f2916_active, self.f1B65_active, self.f1A80_active = True, False, False
        self.atk_wv_enbl = 1
        self.task14 = self.task15 = self.f05EE = 1
        self.task1D = 0
        self.wptr, self.wave_ctr = 0, 0
        self.bugs_actv_cnt = self.bugs_actv_nbr = 0
        self.cont_bomb = 0
        self.spr_color = [0] * 0x80
        self.expl = [0] * 0x80
        self.bomb_rate = [0] * 8
        self.bomb_rem = [0] * 8
        self.form.sway_active = True
        self.fighter_alive = True
        self.fighter_sx = 0x7A
        self.death = None                       # death/respawn state machine
        self.cap = None                         # capture-boss hook state
        self.score = 0
        self.events = []
        self.attack_start_tick = None
        self.stage_clear_tick = None
        self.overlap = set()
        self._init_objects()

    # ------------------------------------------------------------ helpers
    def t(self):
        """Frames since the attack phase was enabled; None during the entry waves."""
        return None if self.attack_start_tick is None else self.tick - self.attack_start_tick

    def ev(self, kind, **kw):
        t = self.t()
        d = dict(tick=self.tick, t=-1 if t is None else t, phase='entry' if t is None else 'attack',
                 frame=self.frame, kind=kind)
        d.update(kw)
        self.events.append(d)
        return d

    def _init_objects(self):
        """c_2896 sprite code/colour per class (gg1-3.s:1533-1588)."""
        if self.challenge:
            v = D_290E[(self.stage >> 2) & 7]
            code_bm = ((v >> 1) & 0x78, (v >> 1) & 7)
            classes = ((range(0x08, 0x30, 2), code_bm), (range(0x30, 0x40, 2), (0x08, 0)),
                       (range(0x40, 0x60, 2), code_bm))
        else:
            classes = ((range(0x08, 0x30, 2), (0x18, 3)), (range(0x30, 0x40, 2), (0x08, 0)),
                       (range(0x40, 0x60, 2), (0x10, 2)))
        for rng, (code, col) in classes:
            for o in rng:
                self.spr_code[o] = code
                self.spr_color[o] = col

    @staticmethod
    def kind_of(obj):
        if obj < 0x08:
            return 'rogue'
        if obj < 0x30:
            return 'bee'
        if obj < 0x38:
            return 'boss'
        if obj < 0x40:
            return 'transient'
        if obj < 0x60:
            return 'red'
        return 'bomb'

    # ------------------------------------------------------------ recording hook
    def _rec(self, obj, moved, ev):
        if self.keep_tracks:
            super()._rec(obj, moved, ev)
        if not ev:
            return
        for e in ev:
            if e.endswith(':F6'):                  # case_0BA8 also reloads b0F (gg1-5.s:1978-1980)
                s = self.slots[self.obj_slot[obj]]
                s.b[0x0F] = self.bomb_flags
            elif e.endswith(':F4') and obj == self.cobj:   # case_0A53 enables f_21CB
                self.cap = dict(phase='aim', obj=obj, t=0)
            elif e == 'HOME':
                self.ev('home', obj=obj)
                if obj == self.bbee_obj:          # l_0E08 colour>=4 check (gg1-5.s:2482-2503)
                    self.bbee_obj = 1

    # ------------------------------------------------------------ f_0857
    def f_0857(self):
        p = self.parms
        tm2 = self.game_tmrs[2]
        if tm2 < 0x3C:
            p[4] = p[5]
        tens = self.bugs_actv_nbr // 10
        self.bomb_flags = D_0909[4 * p[0] + tens]
        if self.cont_bomb:
            self.reload = [2, 2, 2]
            return
        self.reload[0] = D_0909[32 + 4 * p[1] + tens]
        idx = (1 if tm2 < 0x28 else 0) + (1 if tm2 == 0 else 0)
        self.reload[1] = D_08CD[3 * p[2] + idx]
        self.reload[2] = D_08EB[3 * p[3] + idx]

    # ------------------------------------------------------------ f_2916 (entry waves)
    def f_2916(self):
        tab = self.wave_table
        tok = tab[self.wptr]
        if tok == 0x7F:
            if self.flying_nbr == 0:
                self.f2916_active = False
                self.f1A80_active = True
                self.f1B65_active = True
                self.form.nestlr_inh = 1
                self.attack_start_tick = self.tick
                self.ev('attack_phase_enabled', tmr2=self.game_tmrs[2])
            return
        if tok == 0x7E:
            if not self.atk_wv_enbl:
                return
            if self.flying_nbr:
                self.game_tmrs[0] = 2
                return
            if self.challenge and self.game_tmrs[0]:
                return
            self.wptr += 1
            self.wave_ctr += 1
            return
        if not (tok & 0x80) and (self.frame & 7):
            return
        for sl in self.slots:
            if not sl.b[0x13] & 1:
                break
        else:
            return
        raw = tab[self.wptr + 1]
        obj = raw & ~0x40 if (raw & 0x78) == 0x78 else raw
        self.wptr += 2
        s = self.launch_entry(sl.idx, obj, tok)
        if (obj & 0x38) == 0x38:
            if raw & 0x40:
                self.spr_code[obj], self.spr_color[obj] = 0x10, 2
            elif self.wave_ctr == 2:
                self.spr_code[obj], self.spr_color[obj] = 0x08, 0
            else:
                self.spr_code[obj], self.spr_color[obj] = 0x18, 3
            s.b[0x0F] = 0
        else:
            s.b[0x0F] = self.hdr1 if BOMB_FLAG.get(obj, 0) else 0

    # ------------------------------------------------------------ c_23E0 (full)
    def c_23E0(self):
        fc = self.frame
        if not fc & 1:
            if fc & 2:                             # l_2596_even_frame
                self.bugs_actv_nbr = self.bugs_actv_cnt
                self.bugs_actv_cnt = 0
            return
        cnt = self.bugs_actv_cnt
        for obj in range(fc & 2, 0x80, 4):
            st = self.state[obj]
            if st & 0x80 or st == 0:
                continue
            if st == 9:                            # case_2422
                if obj < 0x60:
                    row, col = HPOS[obj], HPOS[obj + 1]
                    sl = self.slots[self.obj_slot[obj]]
                    sl.b[0x11] = self.form.loc_t[col]
                    sl.b[0x12] = self.form.loc_t[row]
                cnt += 1
            elif st == 7:                          # case_2590
                self.state[obj] = 3
                cnt += 1
            elif st in (3, 6):                     # case_254D
                x, y9 = self.spr_x[obj], self.spr_y[obj]
                if x >= 0xF4 or (y9 >> 1) < 0x0B or (y9 >> 1) >= 0xA5:
                    if st == 3:
                        self.slots[self.obj_slot[obj]].b[0x13] = 0
                    self.state[obj] = 0x80
                    self.spr_x[obj] = 0
                    if st == 6:
                        self.ev('bomb_off', bomb=(obj - 0x68) // 2, x=x, y9=y9)
                elif st == 3:
                    cnt += 1
            elif st == 2 and obj < 0x60:           # case_245F
                if self.spr_ctrl[obj] & 1:
                    if (self.spr_code[obj] & 7) == 0:
                        self.spr_ctrl[obj] &= ~1
                    else:
                        self.spr_code[obj] -= 1
                elif (self.spr_code[obj] & 7) == 6:
                    self.state[obj] = 1
                else:
                    self.spr_code[obj] += 1
                self.spr_x[obj], self.spr_y[obj] = self.form.slot_xy(obj)
                cnt += 1
            elif st == 1 and obj < 0x60:           # case_2488
                if self.glbl_enemy_enbl:
                    self.spr_x[obj], self.spr_y[obj] = self.form.slot_xy(obj)
                cnt += 1
            elif st == 4:                          # case_24B2: 40..45 then inactive (or score sprite)
                if self.expl[obj] == 0x45:
                    self.state[obj] = 0x80
                    self.spr_x[obj] = 0
                else:
                    self.expl[obj] += 1
            elif st == 5:
                self.state[obj] = 0x80
        self.bugs_actv_cnt = cnt

    # ------------------------------------------------------------ f_1EA4 bombs
    def f_1EA4(self):
        dy = 2 + (self.frame & 1)
        for n, bo in enumerate(BOMB_OBJS):
            if self.spr_x[bo] == 0:
                continue
            b = self.bomb_rate[n]
            a = (b & 0x7E) + self.bomb_rem[n]
            self.bomb_rem[n] = a & 0x1F
            dx = (a >> 5) & 7
            if b & 0x80:
                dx = -dx
            self.spr_x[bo] = (self.spr_x[bo] + dx) & 0xFF
            self.spr_y[bo] = (self.spr_y[bo] + dy) & 0x1FF

    # ------------------------------------------------------------ bomb drop (f_08D3 2345-2461)
    def _posn_set(self, s, obj):
        super()._posn_set(s, obj)
        b = s.b
        b[0x0E] = (b[0x0E] - 1) & 0xFF
        if b[0x0E]:
            return
        cy = b[0x0F] & 1
        b[0x0F] >>= 1
        if cy and b[0x01] >= 0x4C and self.task15 and self.game_tmrs[1] == 0:
            for n, bo in enumerate(BOMB_OBJS):
                if self.state[bo] == 0x80:
                    self._drop_bomb(n, obj)
                    break
            else:
                self.ev('bomb_none_free', obj=obj)
        b[0x0E] = self.hdr0

    def _drop_bomb(self, n, obj):
        bo = BOMB_OBJS[n]
        self.state[bo] = 6
        x, y9 = self.spr_x[obj], self.spr_y[obj]
        self.spr_x[bo], self.spr_y[bo] = x, y9
        self.spr_code[bo] = 0x30
        fx = self.fighter_sx
        d = fx - x
        borrow = 1 if d < 0 else 0
        mag = abs(d) & 0xFF
        dy = 0x95 - (y9 >> 1)
        dy = abs(dy) & 0xFF
        q, _ = c_0EAA((mag << 8) | (bo + 1), dy)
        v = ((q + (q >> 2)) & 0xFFFF) >> 2
        if v > 0xFF or v >= 0x60:
            v = 0x60
        self.bomb_rate[n] = (borrow << 7) | (v >> 1)
        self.bomb_rem[n] = 0
        self.ev('bomb', obj=obj, bomb=n, x=x, y9=y9, fighter_x=fx, rate=self.bomb_rate[n],
                xspeed=(-1 if borrow else 1) * ((v >> 1) & 0x7E) / 32.0)

    # ------------------------------------------------------------ launches
    def _launch(self, obj, path, mirror, how):
        s = self.launch_dive(obj, path, mirror)
        if s is None:
            self.ev('launch_no_slot', obj=obj, path=path)
            return None
        s.b[0x0F] = self.bomb_flags if self.glbl_enemy_enbl else 0
        self.ev('launch', obj=obj, who=self.kind_of(obj), path=path, mirror=int(bool(mirror)),
                how=how, slot=s.idx, x=self.spr_x[obj], y9=self.spr_y[obj], flying=self.flying_nbr)
        return s

    def c_1083(self, obj, path, how):
        return self._launch(obj, path, (obj >> 1) & 1, how)

    # ------------------------------------------------------------ f_1B65 dive launcher
    def f_1B65(self):
        if self.glbl_enemy_enbl:
            if not (self.task15 and not self.task1D):
                return
        for i in range(4):                         # l_1B75: boss+escort pool, one per frame
            e, path = self.pool[i]
            if e != 0xFF:
                self.pool[i] = [0xFF, None]
                obj = e & 0x7F
                if self.state[obj] != 1:
                    self.ev('pool_skip', obj=obj)
                    return
                self._launch(obj, path, e >> 7, 'pool[%d]' % i)
                return
        if self.frame & 0x0F:
            return
        for n in range(3):                         # l_1BA8: boss, red, bee
            self.timers[n] = (self.timers[n] - 1) & 0xFF
            if self.timers[n] == 0:
                break
        else:
            return
        if self.flying_nbr >= self.parms[4]:       # l_1BB4
            self.timers[n] += 1
            self.ev('sortie_blocked', timer=('boss', 'red', 'bee')[n], flying=self.flying_nbr,
                    max=self.parms[4])
            return
        self.timers[n] = self.reload[n]
        if n == 2:
            self._select_bee_red(range(0x08, 0x30, 2), 'db_flv_atk_yllw', 'timer bee')
        elif n == 1:
            self._select_bee_red(range(0x40, 0x60, 2), 'db_flv_atk_red', 'timer red')
        else:
            self.case_bmbr_boss()

    def _select_bee_red(self, rng, path, how):
        for o in rng:
            if self.state[o] == 1 and o != self.bbee_obj:
                return self.c_1083(o, path, how)
        self.ev('sortie_none_standby', how=how)
        return None

    def case_bmbr_boss(self):
        if self.cflag == 0:
            self.wingm = (self.wingm + 1) & 0xFF
            if not self.wingm & 1:
                for e in (0x30, 0x32, 0x34, 0x36):
                    if self.state[e] == 1:
                        self.cflag, self.cobj = 1, e
                        self.ev('capture_boss_selected', obj=e)
                        return self.j_1CAE(e, 2, 0, 0, 'db_0454')
                self.ev('capture_boss_none_standby')
                return None
        c = 0
        for e in D_1D2C_WINGMEN:                   # 4A 52 5A 58 50 48 -> bit5..bit0
            bit = 0 if e == self.bbee_obj else (1 if self.state[e] == 1 else 0)
            c = ((c << 1) | bit) & 0xFF
        for ixl in (0, 1):
            cc = c
            for B in (4, 3, 2, 1):
                a = cc & 7
                ok = (a != 4 and a >= 3) if ixl == 0 else (a != 0)
                if ok and self.state[BOSS_FOR_B[B]] == 1:
                    return self.j_1CAE(BOSS_FOR_B[B], ixl, B, cc, 'db_flv_0411')
                cc >>= 1
        for e in (0x30, 0x32, 0x34, 0x36):         # third pass: lone boss
            if self.state[e] == 1:
                return self.j_1CAE(e, 2, 0, 0, 'db_flv_0411')
        for e in (0x00, 0x02, 0x04, 0x06):         # last pass: captured fighter in formation
            if self.state[e] == 1:
                return self.c_1083(e, 'db_fltv_rogefgter', 'rogue')
        self.ev('sortie_none_standby', how='boss')
        return None

    def j_1CAE(self, e, ixl, B, cc, path):
        mirror = (e >> 1) & 1
        self.pool[0] = [e | (mirror << 7), path]
        self.boss_scode[e & 7] = D_1CFD[ixl]
        escorts = []
        if ixl != 2:
            b = (B + 1) & 0xFF
            k = 1
            for _ in range(2 if ixl == 0 else 1):  # c_1D03
                cy = cc & 1
                cc = ((cc >> 1) | (cy << 7)) & 0xFF
                if not cy:
                    b -= 1
                    cy = cc & 1
                    cc = ((cc >> 1) | (cy << 7)) & 0xFF
                    if not cy:
                        b -= 1
                esc = D_1D2C_WINGMEN[b]
                b -= 1
                self.pool[k] = [esc | (mirror << 7), path]
                escorts.append(esc)
                k += 1
        cap = e & 7
        if self.state[cap] == 1:                   # l_1CE3 rogue fighter joins
            for k in range(1, 4):
                if self.pool[k][0] == 0xFF:
                    self.pool[k] = [cap | (mirror << 7), path]
                    break
        self.ev('boss_sortie', obj=e, path=path, escorts=escorts, ixl=ixl,
                bonus=(self.boss_scode[e & 7][0] * 100 + 300))
        return True

    # ------------------------------------------------------------ f_1A80 bonus bee
    def f_1A80(self):
        if not self.f1A80_active:
            return
        if self.bugs_actv_nbr >= self.parms[10]:
            return
        if self.bbee_tmr == 0:
            for o in list(range(0x08, 0x30, 2)) + list(range(0x40, 0x60, 2)):
                if self.state[o] == 1:
                    self.bbee_tmr = 0xC0
                    self.bbee_obj = o
                    self.bbee_clr = ((self.stage >> 2) % 3) + 4
                    self.ev('bonus_bee_armed', obj=o, colour=self.bbee_clr)
                    return
            return
        a = (self.bbee_tmr + 1) & 0xFF
        if a:
            self.bbee_tmr = a
            if self.state[self.bbee_obj] != 1:
                self.f1A80_active = False
            return
        if not self.task15:
            self.bbee_tmr = 0xE0
            return
        o = self.bbee_obj
        self.f1A80_active = False
        if self.state[o] != 1:
            return
        self.x3cfg = [3, D_1B59[self.bbee_clr - 4][0], D_1B59[self.bbee_clr - 4][1]]
        self.spr_color[o] = self.bbee_clr
        self.c_1083(o, D_1B5F[self.bbee_clr - 4], 'bonus bee')

    # ------------------------------------------------------------ capture boss (f_21CB/f_2222)
    def capture_hook(self):
        cp = self.cap
        if cp is None:
            return
        obj = cp['obj']
        if self.state[obj] != 9:                   # l_221A
            self.cflag = 0
            self.cap = None
            return
        b = self.slots[self.obj_slot[obj]].b
        if cp['phase'] == 'aim':
            if b[0x0A] != 0:
                return
            b[0x0C] = 0xF4 if b[5] & 1 else 0x0C
            if ((((b[5] & 1) << 7) | (b[4] >> 1)) - 0x78) & 0xFF < 0x10:
                b[0x0C] = 0
                cp['phase'] = 'beam'
                cp['t'] = 0
                cp['frames'] = 20 * self.parms[6] + 65     # [I] see spec 5.3
                self.ev('beam_start', obj=obj, beam_x=self.captr0)
        elif cp['phase'] == 'beam':
            b[0x0D] = 0xFF
            cp['t'] += 1
            p6 = self.parms[6]
            if 1 + 10 * p6 <= cp['t'] < 1 + 10 * p6 + 64 and self.fighter_alive:
                if ((self.captr0 - self.fighter_sx + 0x1B) & 0xFF) < 0x36 and not cp.get('warned'):
                    cp['warned'] = True
                    self.ev('capture_window_fighter_under_beam', obj=obj)   # not modelled further
            if cp['t'] >= cp['frames']:
                b[0x0D] = 1
                self.cflag, self.cobj = 0, 1
                self.cap = None
                self.ev('beam_end', obj=obj)

    # ------------------------------------------------------------ hits and scoring
    def hit_enemy(self, obj, by='rocket'):
        """hitd_dspchr for an enemy (gg1-5.s:1177-1408).  Returns points scored."""
        st = self.state[obj]
        col = self.spr_color[obj]
        if col == 0:                               # l_08CA green boss: turns blue, no score
            self.spr_color[obj] = 1
            self.ev('boss_hit_once', obj=obj, by=by)
            return 0
        flying = True if by == 'fighter' else (((st - 1) & 0xFE) != 0)
        pts = SCORE_PER_COUNT[col] * (2 if flying else 1)
        if flying:
            if st in (3, 7, 9):
                self.slots[self.obj_slot[obj]].b[0x13] = 0
            if col != 7 and obj != self.bbee_obj and (obj & 0x38) != 0x38 and col == 1:
                pts += self.boss_scode[obj & 7][0] * 100
                self.game_tmrs[1] = 6              # l_0899: bombs suppressed ~6 counts
        if obj == self.cobj:
            self.cflag, self.cobj = 0, 1
        self.state[obj] = 4
        self.expl[obj] = 0x40
        self.score += pts
        self.ev('enemy_destroyed', obj=obj, by=by, flying=int(flying), points=pts)
        return pts

    def shoot(self, obj):
        """Convenience for hooks: a rocket hit on obj (no geometry check)."""
        if self.state[obj] & 0x80 or (self.state[obj] & 0xFE) == 4:
            return 0
        return self.hit_enemy(obj, 'rocket')

    # ------------------------------------------------------------ f_05EE fighter collision
    def f_05EE(self):
        if not (self.task14 and self.f05EE and self.fighter_alive):
            return
        fx = self.fighter_sx
        objs = range(0x38, 0x40, 2) if self.f2916_active else range(0x00, 0x60, 2)
        now = set()
        hit = False
        for obj in objs:
            st = self.state[obj]
            if st & 0x80 or (st & 0xFE) == 4 or st == 0:
                continue
            if fighter_touches(self.spr_x[obj], self.spr_y[obj], fx):
                now.add(obj)
                if obj not in self.overlap:
                    self.ev('collision_enemy', obj=obj, x=self.spr_x[obj], y9=self.spr_y[obj], fx=fx)
                if self.fighter_dies:
                    self.hit_enemy(obj, 'fighter')
                    hit = True
        for n, bo in enumerate(BOMB_OBJS):
            if self.state[bo] != 6:
                continue
            if fighter_touches(self.spr_x[bo], self.spr_y[bo], fx):
                self.ev('collision_bomb', bomb=n, x=self.spr_x[bo], y9=self.spr_y[bo], fx=fx)
                self.spr_x[bo] = 0                 # l_0815_bomb_hit (bomb always consumed)
                self.state[bo] = 0x80
                if self.fighter_dies:
                    hit = True
                break
        self.overlap = now
        if hit:
            self._fighter_destroyed()

    def _fighter_destroyed(self):
        """l_0639 + hitd_fghtr_hit (gg1-5.s:708-769), then gctl_stg_restart_hdlr."""
        self.task14 = self.task15 = self.f05EE = 0
        self.fighter_alive = False
        self.atk_wv_enbl = 0                       # gctl_supv_stage l_081B
        self.game_tmrs[3] = 4                      # game_ctrl.s:513
        self.death = 'explode'
        self.ev('fighter_destroyed', fx=self.fighter_sx)

    def game_control(self):
        """Background loop pieces (game_ctrl.s gctl_supv_stage & friends), polled per frame."""
        if not self.f2916_active and self.bugs_actv_nbr == 0 and self.stage_clear_tick is None \
                and self.attack_start_tick is not None and self.death is None:
            self.stage_clear_tick = self.tick
            self.game_tmrs[3] = 4
            self.ev('stage_clear')
        d = self.death
        if d == 'explode' and self.game_tmrs[3] == 0:
            self.ships -= 1
            if self.ships < 0:
                self.death = 'game_over'
                self.ev('game_over')
                return
            self.task14 = 1                        # c_player_respawn
            self.death = 'ready'
            self.ev('READY_shown')
        if self.death == 'ready' and self.flying_nbr == 0:
            self.fighter_alive = True              # fighter placed at X 0x7A (gg1-2.s:1058)
            t2 = self.game_tmrs[2] + 0x1E          # game_ctrl.s:859-865
            self.game_tmrs[2] = t2 if t2 < 0x78 else 0x78
            self.game_tmrs[3] = 3                  # c_tdelay_3
            self.death = 'delay'
            self.ev('fighter_placed', tmr2=self.game_tmrs[2])
        if self.death == 'delay' and self.game_tmrs[3] == 0:
            self.task15 = self.f05EE = self.atk_wv_enbl = 1     # plyr_respawn_rdy
            self.death = None
            self.ev('respawn_ready')

    # ------------------------------------------------------------ frame
    def step(self):
        self.tick += 1
        self.frame = (self.frame + 1) & 0xFF
        m = self.frame & 0x1F
        if m == 1:
            self.cts2 = (self.cts2 + 1) & 0xFF
        elif m == 0:
            self.cts2 = ((self.cts2 | 1) + 1) & 0xFF
        # main CPU, task-table order (task_man.s:41-76)
        for h in self.user_hooks:
            h(self)
        self.f_1A80()                              # 0x04
        self.f_0857()                              # 0x05
        if self.f2916_active:
            self.f_2916()                          # 0x08
        self.form.f_1DE6(self.frame)               # 0x09
        self.form.f_2A90(self.frame, self.bugs_actv_nbr != 0, self.f2916_active)   # 0x0A
        self.c_23E0()                              # 0x0C
        self.f_1EA4()                              # 0x0D
        if self.f1B65_active:
            self.f_1B65()                          # 0x10
        if not self.cts2 & 1:                      # 0x17 f_1DD2
            self.game_tmrs = [v - 1 if v else 0 for v in self.game_tmrs]
        self.capture_hook()                        # 0x18/0x19
        self.game_control()
        # sub CPU (gg1-5.s:480-489, then d_003B order)
        self.cont_bomb = 1 if (self.bugs_actv_nbr < self.parms[7] and self.task15) else 0
        t = self.t()
        fx = self.entry_fighter_x if t is None else self.fighter_x_fn(t)
        fx = max(0x12, min(0xE1, int(fx)))             # f_1F85 limits (gg1-2_fx.s:2116-2129)
        self.fighter_sx = fx if self.fighter_alive else 0
        self.fighter_x = self.fighter_sx
        self.task1D = 0
        self.run_motion()                          # f_08D3 incl. bomb drops
        self.f_05EE()


def simulate_attack(stage=1, frames=1200, fighter_x_fn=None, rank=3, frame0=0, rng_seed=0,
                    fighter_dies=False, ships=3, hooks=(), max_entry_frames=6000,
                    entry_fighter_x=0x7A, stop_at_clear=True):
    """Run the stage's entry waves (not recorded) and then `frames` frames of the attack phase,
    starting with the frame on which f_2916 enables f_1B65.  fighter_x_fn(t) -> fighter sprite X
    (t = frames since the attack phase started, 0 = that frame); during the entry waves the
    fighter stands at entry_fighter_x.  Events from the entry carry phase='entry', t=-1.

    Returns a list (one dict per frame) with .machine and .events attributes:
      {'t', 'tick', 'frame', 'divers': [(obj, x, y9, tile, ctrl, state, slot)],
       'bombs': [(n, x, y9)], 'fighter_x', 'flying', 'enemies', 'cont_bomb'}
    """
    m = AttackMachine(stage, rank, fighter_x_fn, frame0, rng_seed, fighter_dies, ships, hooks=hooks,
                      entry_fighter_x=entry_fighter_x)
    n = 0
    while m.attack_start_tick is None and n < max_entry_frames:
        m.step()
        n += 1
    out = AttackRecords()
    out.machine = m
    out.events = m.events
    out.entry_frames = n
    for _ in range(frames):
        m.step()
        divers = []
        for s in m.slots:
            if s.b[0x13] & 1:
                o = s.b[0x10]
                divers.append((o, m.spr_x[o], m.spr_y[o], m.spr_code[o] & 7, m.spr_ctrl[o],
                               m.state[o], s.idx))
        bombs = [(k, m.spr_x[bo], m.spr_y[bo]) for k, bo in enumerate(BOMB_OBJS)
                 if m.state[bo] == 6 and m.spr_x[bo]]
        out.append(dict(t=m.t(), tick=m.tick, frame=m.frame, divers=divers, bombs=bombs,
                        fighter_x=m.fighter_sx, flying=m.flying_nbr, enemies=m.bugs_actv_nbr,
                        cont_bomb=m.cont_bomb))
        if m.death == 'game_over' or (stop_at_clear and m.stage_clear_tick is not None):
            break
    return out


class AttackRecords(list):
    machine = None
    events = None
    entry_frames = 0


# ============================================================================
# Tables for the spec
# ============================================================================
def attack_param_table(rank=3, stages=range(1, 28)):
    lines = ['| stage | kind | raw bytes | p0 bomb row | p1 boss row | p2 red row | p3 bee row | '
             'max bombers p4->p5 | p6 beam step | p7 cont.bomb < | p8 | p9 | p10 bonus bee < |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for st in stages:
        p = stage_parms(st, rank)
        kind = stage_row(st, rank)[0][:5]
        a = st
        while a >= 0x1B:
            a -= 4
        base = [0x82, 0x82 * 2, 0x82 * 3, 0][rank]
        raw = gp.BMBR_STG_CFG_DAT[base + (a - 1) * 5: base + (a - 1) * 5 + 5]
        lines.append('| %d | %s | %s | %d | %d | %d | %d | %d->%d | %d | %d | %d | %d | %d |' % (
            st, kind, ' '.join('%02X' % v for v in raw), p[0], p[1], p[2], p[3], p[4], p[5], p[6],
            p[7], p[8], p[9], p[10]))
    return '\n'.join(lines)


def reload_summary_table(rank=3, stages=range(1, 27)):
    """Per-stage decoded timers.  Enemy bands are b_bugs_actv_nbr//10 = 0,1,2,3,4;
    time index 0: game_tmrs[2] >= 40, 1: 1..39, 2: 0 (c_08AD)."""
    lines = ['| stage | bomb flags b_92C0[8] by enemies 0-9/10-19/20-29/30-39/40+ | boss reload (ticks) by enemies | '
             'red reload by time 0/1/2 | bee reload by time 0/1/2 | max bombers | cont. bombing below |',
             '|---|---|---|---|---|---|---|']
    for st in stages:
        p = stage_parms(st, rank)
        if stage_row(st, rank)[0] == 'challenge':
            lines.append('| %d | (challenge: no sorties, max bombers 0) | | | | 0 | - |' % st)
            continue
        rows, reds, bees = reload_table(st, rank)
        lines.append('| %d | %s | %s | %s | %s | %d, %d after tmr2<60 | %d |' % (
            st, ' '.join('%02X' % r[1] for r in rows), ' '.join('%d' % r[2] for r in rows),
            '/'.join('%d' % v for v in reds), '/'.join('%d' % v for v in bees), p[4], p[5], p[7]))
    return '\n'.join(lines)


def reload_table(stage, rank=3):
    p = stage_parms(stage, rank)
    rows = []
    for tens in range(5):
        rows.append((tens, D_0909[4 * p[0] + tens], D_0909[32 + 4 * p[1] + tens]))
    reds = [D_08CD[3 * p[2] + i] for i in range(3)]
    bees = [D_08EB[3 * p[3] + i] for i in range(3)]
    return rows, reds, bees


# ============================================================================
# Demo / plot
# ============================================================================
KIND_COL = {'bee': (255, 220, 60), 'red': (255, 80, 80), 'boss': (80, 255, 120),
            'transient': (200, 120, 255), 'rogue': (255, 255, 255)}


def sweep(t):
    """Demo fighter: triangle sweep 0x28..0xC8 (sprite X) at 1 px/frame, period 320 frames."""
    ph = (t + 80) % 320
    return 0x28 + (ph if ph < 160 else 320 - ph)


def plot_attack(rec, filename, title):
    from PIL import Image, ImageDraw
    S = 2
    m = rec.machine
    img = Image.new('RGB', (224 * S, 288 * S), (6, 6, 18))
    dr = ImageDraw.Draw(img)

    def scr(x, y):          # sprite registers -> centre pixel of a 16x16 sprite on the portrait screen
        return ((x - 17 + 8) * S, (y - 40 + 8) * S)

    for o in range(0x08, 0x60, 2):
        if 0x38 <= o < 0x40:
            continue
        x, y = m.form.origin_xy(o)
        cx, cy = scr(x, y)
        dr.rectangle([cx - 7 * S, cy - 7 * S, cx + 7 * S, cy + 7 * S], outline=(45, 45, 70))
    trails = {}
    last = {}
    for r in rec:
        active = set()
        for (o, x, y, tile, ctrl, st, slot) in r['divers']:
            key = (o, slot)
            active.add(key)
            if key not in last or last[key] is None:
                trails.setdefault(key, []).append([])
            trails[key][-1].append(scr(x, y))
            last[key] = True
        for key in list(last):
            if key not in active:
                last[key] = None
    for (o, slot), runs in trails.items():
        col = KIND_COL.get(AttackMachine.kind_of(o), (200, 200, 200))
        for pts in runs:
            seg = pts[:1]
            for p in pts[1:]:
                if abs(p[0] - seg[-1][0]) + abs(p[1] - seg[-1][1]) > 24 * S:
                    if len(seg) > 1:
                        dr.line(seg, fill=col, width=1)
                    seg = [p]
                else:
                    seg.append(p)
            if len(seg) > 1:
                dr.line(seg, fill=col, width=1)
    for e in rec.events:
        if e['kind'] == 'launch' and e['t'] >= 0:
            cx, cy = scr(e['x'], e['y9'])
            col = KIND_COL.get(e['who'], (255, 255, 255))
            dr.rectangle([cx - 3 * S, cy - 3 * S, cx + 3 * S, cy + 3 * S], outline=col)
    for r in rec:
        for (k, x, y) in r['bombs']:
            cx, cy = scr(x, y)
            dr.point([(cx, cy), (cx + 1, cy)], fill=(235, 235, 255))
    fy = scr(0, FIGHTER_Y9)[1]
    xs = sorted(set(r['fighter_x'] for r in rec if r['fighter_x']))
    if xs:
        dr.line([scr(xs[0], FIGHTER_Y9)[0], fy, scr(xs[-1], FIGHTER_Y9)[0], fy], fill=(90, 160, 255), width=2)
    for e in rec.events:
        if e['kind'] in ('collision_bomb', 'collision_enemy'):
            cx, cy = scr(e['fx'], FIGHTER_Y9)
            dr.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=(255, 60, 200))
    dr.text((4, 4), title, fill=(220, 220, 220))
    dr.text((4, 16), 'yellow=bee  red=butterfly  green=boss  white dots=bombs  blue=fighter sweep',
            fill=(150, 150, 170))
    dr.text((4, 288 * S - 14), 'boxes = launch points; magenta = fighter touched by bomb/enemy',
            fill=(150, 150, 170))
    img.save(filename)


def _fmt(e):
    out = []
    for a, b in e.items():
        if a in ('tick', 't', 'frame', 'kind', 'phase'):
            continue
        if a in ('obj',) and isinstance(b, int):
            b = '%02X' % b
        elif a == 'escorts':
            b = ' '.join('%02X' % v for v in b)
        out.append('%s=%s' % (a, b))
    return ' '.join(out)


def main():
    rec = simulate_attack(1, frames=1200, fighter_x_fn=sweep)
    m = rec.machine
    print('stage 1 rank A: entry waves took %d frames; attack phase enabled at tick %d '
          '(frame counter %d, game_tmrs[2]=%d)' % (rec.entry_frames, m.attack_start_tick,
                                                  (m.attack_start_tick) & 0xFF,
                                                  [e for e in m.events if e['kind'] == 'attack_phase_enabled'][0]['tmr2']))
    print('stage parms:', m.parms)
    print('\n t    event')
    nb = 0
    for e in m.events:
        if e['t'] < 0:
            continue
        k = e['kind']
        if k == 'launch':
            print('%5d  launch %-5s %02X %s mirror=%d slot=%d from (%d,%d) flying_before=%d path=%s' % (
                e['t'], e['who'], e['obj'], e['how'], e['mirror'], e['slot'], e['x'], e['y9'],
                e['flying'], e['path']))
        elif k == 'boss_sortie':
            print('%5d  boss sortie %02X path=%s escorts=%s bonus-if-shot-diving=%d' % (
                e['t'], e['obj'], e['path'], ' '.join('%02X' % v for v in e['escorts']), e['bonus']))
        elif k == 'bomb':
            nb += 1
            print('%5d  bomb#%d by %02X at (%d,%d) fighterX=%d rate=%02X (%.3f px/frame)' % (
                e['t'], e['bomb'], e['obj'], e['x'], e['y9'], e['fighter_x'], e['rate'], e['xspeed']))
        elif k in ('sortie_blocked', 'home', 'bomb_off'):
            continue
        else:
            print('%5d  %s %s' % (e['t'], k, _fmt(e)))
    maxd = max(len(r['divers']) for r in rec)
    maxb = max(len(r['bombs']) for r in rec)
    print('\n%d frames: %d launches, %d bombs, max simultaneous divers %d, max bombs on screen %d, '
          'blocked sortie ticks %d, collisions %d' % (
              len(rec), sum(1 for e in m.events if e['kind'] == 'launch' and e['t'] >= 0), nb, maxd, maxb,
              sum(1 for e in m.events if e['kind'] == 'sortie_blocked'),
              sum(1 for e in m.events if e['kind'].startswith('collision'))))
    out = os.path.join(os.path.dirname(HERE), 'sim', 'build')
    os.makedirs(out, exist_ok=True)
    plot_attack(rec, os.path.join(out, 'attack_stage1.png'),
                'Galaga stage 1 rank A: first 20 s of attacks (sim, fighter sweeping)')
    # second demo: kill enemies over time to reach continuous bombing, fighter dies
    def killer(mm):
        t = mm.t()
        if t is None:
            return
        if t > 0 and t % 60 == 0:
            for o in list(range(0x08, 0x30, 2)) + list(range(0x40, 0x60, 2)) + [0x30, 0x32, 0x34, 0x36]:
                if mm.state[o] == 1:
                    mm.shoot(o)
                    if mm.spr_color[o] == 1 and mm.state[o] == 1:
                        mm.shoot(o)
                    break
    rec2 = simulate_attack(1, frames=3600, fighter_x_fn=sweep, fighter_dies=True, ships=9, hooks=[killer])
    m2 = rec2.machine
    print('\nstage 1, one resting enemy shot per second, fighter vulnerable:')
    for e in m2.events:
        if e['t'] >= 0 and e['kind'] in ('fighter_destroyed', 'READY_shown', 'fighter_placed',
                                         'respawn_ready', 'stage_clear', 'boss_sortie',
                                         'capture_boss_selected', 'beam_start', 'beam_end'):
            print('%5d  %s %s' % (e['t'], e['kind'], _fmt(e)))
    cont = next((r['t'] for r in rec2 if r['cont_bomb']), None)
    print('continuous bombing first set at t=%s; score %d; frames simulated %d' % (cont, m2.score, len(rec2)))


if __name__ == '__main__':
    main()
