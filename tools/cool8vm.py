#!/usr/bin/env python3
"""The Cool8 machine, in software. No board required.

    python tools/cool8vm.py                 # boot the ROM, talk to the monitor
    python tools/cool8vm.py --run prog.bin --at 0x0200
    python tools/cool8vm.py --headless --cycles 2000000

This is the whole computer, not just the CPU: the memory map and its ROM
overlay, the I/O page, video, sound, the keyboard, the UART and the SPI
flash. It exists so an operating system can be written against a machine
that answers in milliseconds rather than one that has to be flashed.

## What it is faithful to, and what it is not

**The CPU is not modelled here.** `tools/cool8emu.py` is imported and
used as-is. It is the executable specification the RTL is checked against
instruction by instruction (`sim/cosim.py`, all 511 encodings), so
forking it to make a "faster" copy would create two models that must
agree — the trap AGENTS.md warns about for opcode tables. There is one
CPU model in this project.

**The machine is scanline-accurate, not cycle-accurate.** The CPU runs
for a scanline's worth of cycles, then a scanline is drawn from the
registers as they stand, then the raster and vblank interrupts are
raised. That is how most 8-bit emulators are built and it is what makes
raster splits, mid-frame palette changes and sprite multiplexing behave.
What it does *not* model is contention: the display fetch stealing a
cycle from the CPU, `cool8_vport` stalling on a busy arbiter, the exact
instant a store lands. Code whose correctness depends on those needs the
RTL, and `sim/` is where that lives.

**Timing that software can observe is right**; timing that only a logic
analyser can see is not.

## The register map is complete on purpose

An emulator that models only the registers the boot ROM happens to touch
is an emulator that lies to the first program that does something new.
Every address in docs/04-system.md section 4 is here, including the ones
nothing writes yet, and unlisted addresses read `$FF` exactly as the
hardware's do.

FPGA-only concerns — wait states, the launch/data split, `io_wreq` versus
`io_we` — have no meaning above the bus and are absent.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import cool8emu as emu                              # noqa: E402
import opcodes                                      # noqa: E402
import mkrom                                        # noqa: E402
import mkfont                                       # noqa: E402

# docs/04-system.md section 5.1 and D32: 25.125 MHz pixel clock, a third
# of it for the system, 800x525 of raster.
SYS_HZ = 8_375_000
H_TOTAL, V_TOTAL = 800, 525
H_VIS, V_VIS = 640, 480
CYCLES_PER_LINE = 266                   # 8.375 MHz / (25.125 MHz / 800)
FRAME_HZ = 60

# The sound engine takes a sample every 256 system clocks (D41).
SND_DIV = 256
SND_HZ = SYS_HZ // SND_DIV


class Uart:
    """8N1 to a host console. The wire is instant; the FIFO is not.

    Sixteen bytes deep with the overrun flag, because that depth and that
    flag are visible to software and a program that ignores them behaves
    differently here and on the board.
    """

    DEPTH = 16

    def __init__(self):
        self.rx = bytearray()
        self.tx = bytearray()           # everything the machine has said
        self.overrun = False
        self.div = 72

    def feed(self, data):
        """Type at the machine."""
        for b in data:
            if len(self.rx) < self.DEPTH:
                self.rx.append(b)
            else:
                self.overrun = True

    def take(self):
        """Everything said since the last call."""
        out = bytes(self.tx)
        self.tx.clear()
        return out

    def read(self, a):
        if a == 0x70:
            return (0x01 if self.rx else 0) | 0x02 | (0x04 if self.overrun
                                                      else 0)
        if a == 0x71:
            return self.rx.pop(0) if self.rx else 0xFF
        if a == 0x72:
            return self.div & 0xFF
        if a == 0x73:
            return (self.div >> 8) & 0xFF
        return 0xFF

    def write(self, a, v):
        if a == 0x70:
            if v & 0x04:
                self.overrun = False
        elif a == 0x71:
            self.tx.append(v)
        elif a == 0x72:
            self.div = (self.div & 0xFF00) | v
        elif a == 0x73:
            self.div = (self.div & 0x00FF) | (v << 8)


class Ps2:
    """Raw Set 2 scancodes and a 16-byte FIFO, as docs section 4.3."""

    DEPTH = 16

    def __init__(self):
        self.q = bytearray()
        self.overrun = False
        self.irq_en = False

    def feed(self, codes):
        for b in codes:
            if len(self.q) < self.DEPTH:
                self.q.append(b)
            else:
                self.overrun = True

    @property
    def irq(self):
        return self.irq_en and bool(self.q)

    def read(self, a):
        if a == 0x40:
            return (0x01 if self.q else 0) | (0x02 if self.overrun else 0)
        if a == 0x41:
            return self.q.pop(0) if self.q else 0xFF
        if a == 0x42:
            return 0x10 if self.irq_en else 0x00
        return 0xFF

    def write(self, a, v):
        if a == 0x40:
            if v & 0x02:
                self.overrun = False
        elif a == 0x42:
            self.irq_en = bool(v & 0x10)
            if v & 0x01:
                self.q.clear()


def _operands(line):
    """The values on one `.byte` line, honouring quotes.

    One pass, because both the separator and the comment marker occur as
    characters in the table itself: `.byte 0,',','k'` rules out
    `split(",")` and `.byte 0,'.','/','l',';','p'` rules out cutting the
    comment off first.
    """
    line = line.strip()[len(".byte"):]
    out, cur, q = [], "", False
    for c in line:
        if c == "'":
            q = not q
            cur += c
        elif q:
            cur += c
        elif c == ";":
            break
        elif c == ",":
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        out.append(cur.strip())
    return out


def _value(tok):
    if tok.startswith("'"):
        return ord(tok[1])
    if tok.startswith("$"):
        return int(tok[1:], 16)
    return int(tok, 0)


def _table(text, label):
    """Every `.byte` value under `label`, up to the blank line after it."""
    body = text.split(label + ":", 1)[1]
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith(".byte"):
            if line.startswith(";") or not line:
                continue
            break
        out += [_value(t) for t in _operands(line)]
    return out


def _kbd_tables(_cache={}):
    """keymap, shiftmap and extmap, read out of sw/keymap.asm.

    **Read, not restated.** The machine decodes with that table; a copy
    here would only ever agree with itself, and the one thing this is for
    is catching the day they disagree. sim/test_lex.py reads
    sw/toktab.asm for the same reason.

    Returns character -> (scancode, shifted) and name -> scancode, the
    K_* names coming from sw/basic.bas so even the ordering is the
    machine's rather than a guess about it.
    """
    if _cache:
        return _cache["chars"], _cache["named"]

    here = os.path.dirname(os.path.abspath(__file__))
    sw = os.path.join(os.path.dirname(here), "sw")
    with open(os.path.join(sw, "keymap.asm"), encoding="utf-8") as fh:
        text = fh.read()

    keymap = _table(text, "keymap")
    shiftmap = _table(text, "shiftmap")
    extmap = _table(text, "extmap")

    # Ascending, so the main row wins over the keypad: '1' is $16 before
    # it is $69, and a test that meant to press the 1 key means that one.
    chars = {}
    for code, ch in enumerate(keymap):
        if ch:
            chars.setdefault(chr(ch), (code, False))
    for i in range(0, len(shiftmap) - 1, 2):
        plain, shifted = chr(shiftmap[i]), chr(shiftmap[i + 1])
        if plain in chars:
            chars.setdefault(shifted, (chars[plain][0], True))
    for ch in "abcdefghijklmnopqrstuvwxyz":
        if ch in chars:
            chars.setdefault(ch.upper(), (chars[ch][0], True))
    if "\r" in chars:
        chars.setdefault("\n", chars["\r"])

    # The K_* constants, so `K_UP` here is the K_UP the editor compares
    # against rather than a number that happens to match today.
    with open(os.path.join(sw, "basic.bas"), encoding="utf-8") as fh:
        consts = dict(re.findall(r"^CONST\s+(K_\w+)\s*=\s*(\d+)",
                                 fh.read(), re.M))
    base = min(int(v) for v in consts.values()) if consts else 256
    named = {}
    for name, v in consts.items():
        want = 0x80 + (int(v) - base)
        for i in range(0, len(extmap) - 1, 2):
            if extmap[i + 1] == want:
                named[name] = extmap[i]
    _cache["chars"], _cache["named"] = chars, named
    return chars, named


def _encode_keys(text):
    """Characters and K_* names to the make and break codes a keyboard sends."""
    chars, named = _kbd_tables()
    if isinstance(text, str):
        text = list(text)
    out = bytearray()
    for item in text:
        if item in named:
            out += bytes((0xE0, named[item], 0xE0, 0xF0, named[item]))
            continue
        if item not in chars:
            raise KeyError("no key on this keyboard sends %r" % (item,))
        code, shifted = chars[item]
        if shifted:
            out += bytes((0x12,))
        out += bytes((code, 0xF0, code))
        if shifted:
            out += bytes((0xF0, 0x12))
    return bytes(out)


class Flash:
    """8 MB of SPI flash, readable and writable above the floor.

    **The floor is modelled because it is a guarantee, not a convenience.**
    D42 puts a comparator against $100000 in the gates so the bitstream at
    offset 0 cannot be reached by any sequence of register writes; an
    emulator that let software scribble there would be teaching the
    opposite of what the machine does. A refused request sets bit 2 of
    FLS_WCTRL and changes nothing, exactly as the hardware's does.

    A flash can only clear bits — an erase is what sets them — and that is
    modelled too, because software that programs twice without erasing
    gets the AND on real silicon and would not notice here otherwise.
    """

    SIZE = 8 << 20
    FLOOR = 0x100000
    SECTOR = 4096

    def __init__(self, path=None):
        self.mem = bytearray(b'\xFF' * self.SIZE)
        self.path = path
        if path and os.path.exists(path):
            with open(path, 'rb') as fh:
                d = fh.read(self.SIZE)
            self.mem[:len(d)] = d
        self.addr = 0
        self.open_r = False
        self.wdata = 0
        self.denied = False

    def flush(self):
        if self.path:
            with open(self.path, 'wb') as fh:
                fh.write(self.mem)

    def read(self, a):
        if a == 0x88:
            return self.addr & 0xFF
        if a == 0x89:
            return (self.addr >> 8) & 0xFF
        if a == 0x8A:
            return (self.addr >> 16) & 0xFF
        if a == 0x8B:                       # a read advances the stream
            if not self.open_r:
                return 0xFF
            b = self.mem[self.addr % self.SIZE]
            self.addr = (self.addr + 1) & 0xFFFFFF
            return b
        if a == 0x8C:
            return 0x01 if self.open_r else 0x00
        if a == 0x8D:
            return 0x02 if self.open_r else 0x00
        if a == 0x8F:
            return 0x04 if self.denied else 0x00
        return 0xFF

    def write(self, a, v):
        if a in (0x88, 0x89, 0x8A) and not self.open_r:
            sh = {0x88: 0, 0x89: 8, 0x8A: 16}[a]
            self.addr = (self.addr & ~(0xFF << sh)) | (v << sh)
        elif a == 0x8C:
            self.open_r = bool(v & 1)
        elif a == 0x8E:
            self.wdata = v
        elif a == 0x8F:
            if v & 0x04:
                self.denied = False
            if self.open_r:
                return
            if v & 0x01:                    # program
                if self.addr < self.FLOOR:
                    self.denied = True
                else:
                    i = self.addr % self.SIZE
                    self.mem[i] &= self.wdata
            elif v & 0x02:                  # erase the 4 KB sector
                if self.addr < self.FLOOR:
                    self.denied = True
                else:
                    base = (self.addr % self.SIZE) & ~(self.SECTOR - 1)
                    self.mem[base:base + self.SECTOR] = b'\xFF' * self.SECTOR


class Sound:
    """Eight voices, as D41 built them.

    Modelled at the sample rather than the clock: the hardware walks one
    datapath eight times per sample and the order it does that in is not
    observable, so this adds the increments and mixes in one go. What is
    observable — the pitch, the volume, the noise rate, the +-128 range
    the mixer sums into — is the same.
    """

    VOICES = 8

    def __init__(self):
        self.inc = [0] * self.VOICES
        self.phase = [0] * self.VOICES
        self.vol = [0] * self.VOICES
        self.enable = [False] * self.VOICES
        self.noise = [False] * self.VOICES
        self.idx = 0
        self.hold = 0
        self.lfsr = 0xACE1
        self.samples = bytearray()      # unsigned 8-bit, SND_HZ

    def write(self, a, v):
        if a == 0x50:
            self.idx = v & 0x3F
        elif a == 0x51:
            if self.idx & 1:            # the odd byte commits the word
                word = (v << 8) | self.hold
                vc, which = self.idx >> 3, (self.idx >> 1) & 3
                if vc < self.VOICES:
                    if which == 0:
                        self.inc[vc] = word
                    elif which == 1:
                        self.phase[vc] = word
                    else:
                        self.vol[vc] = word & 0x0F
                        self.enable[vc] = bool(word & 0x4000)
                        self.noise[vc] = bool(word & 0x8000)
            else:
                self.hold = v
            self.idx = (self.idx + 1) & 0x3F

    def read(self, a):
        return 0xFF                     # write-only, as the hardware is

    def sample(self):
        """One mixed sample, signed, in the mixer's own -128..127 range."""
        mix = 0
        for v in range(self.VOICES):
            nxt = (self.phase[v] + self.inc[v]) & 0x1FFFF
            wrapped = nxt > 0xFFFF
            old = self.phase[v]
            self.phase[v] = nxt & 0xFFFF
            if not self.enable[v]:
                continue
            if self.noise[v]:
                wave = self.lfsr & 1
                if wrapped:
                    bit = ((self.lfsr >> 15) ^ (self.lfsr >> 13) ^
                           (self.lfsr >> 12) ^ (self.lfsr >> 10)) & 1
                    self.lfsr = ((self.lfsr << 1) | bit) & 0xFFFF
            else:
                wave = (old >> 15) & 1
            mix += self.vol[v] if wave else -self.vol[v]
        return max(-128, min(127, mix))

    def level(self):
        """The byte the modulator is fed — what the pin's duty cycle is.

        The RTL forms it as `{~sample[8], sample[7:1]}`: drop the bottom
        bit and flip the sign into an offset. That is 128 + (mix >> 1),
        so the mixer's +-120 becomes 68..188 out of 256 and silence is
        exactly half scale. **The halving is not a detail** — it is the
        headroom that lets eight voices sum without the pin clipping, and
        a model that skipped it would be twice as loud as the hardware.
        """
        return (128 + (self.sample() >> 1)) & 0xFF

    def tick(self, n):
        for _ in range(n):
            self.samples.append(self.level())

    def take(self):
        out = bytes(self.samples)
        self.samples.clear()
        return out


class Video:
    """The register file, VRAM, and the state a frame is drawn from.

    Rendering lives in cool8vid.py; what is here is everything software
    can see and set. The split is deliberate — an OS cares about the
    registers and never about how a scanline is assembled.
    """

    def __init__(self):
        self.vram = bytearray(0x10000)
        self.pal = [0] * 256
        self.font = bytearray(4096)

        self.mode = 0x00
        self.ctrl = 0x00
        self.base = 0x8000
        self.stride = 256
        self.pat_base = 0
        self.scrl_x = 0
        self.scrl_y = 0
        self.border = 0
        self.rcmp = 0
        self.irq_en = 0
        self.irq_fl = 0
        self.vactive = 480
        self.raster = 0
        self.frame = 0

        self.pal_idx = 0
        self._pal_half = 0
        self._pal_red = 0

        self.cur_x = 0
        self.cur_y = 0
        self.cur_ctrl = 0
        self.cur_lines = 0xF0
        self.blink = 0                  # frames; the phase restarts on a move


        # VRAM port
        self.vaddr = 0
        self.vstep = 1

        # pixel port
        self.pix_x = 0
        self.pix_y = 0

        # sprites: 32 descriptors of 8 bytes
        self.spr = bytearray(256)
        self.spr_idx = 0
        self._spr_hold = 0
        self.spr_en = False
        self.spr_overrun = False
        self.spr_bank = 0

    # ---- the derived viewport, as cool8_vregs computes it
    @property
    def hdouble(self):
        return bool(self.ctrl & 0x10)

    @property
    def vdouble(self):
        return bool(self.ctrl & 0x20)

    @property
    def engine(self):
        return self.ctrl & 3

    @property
    def bpp_log(self):
        return (self.ctrl >> 2) & 3

    @property
    def hdisp(self):
        return 320 if self.hdouble else 640

    @property
    def img_w(self):
        if self.engine != 2:
            return self.hdisp
        return (self.stride << 3) >> self.bpp_log

    @property
    def hactive(self):
        return min(self.img_w, self.hdisp)

    @property
    def hstart(self):
        return max(0, (self.hdisp - self.img_w) // 2)

    @property
    def vstart(self):
        return (480 - self.vactive) // 2

    @property
    def cur_on(self):
        """Enabled, and lit this frame.

        The phase restarts whenever CUR_X or CUR_Y is written, which is
        what makes a cursor followable while typing. Rate 3 is no blink at
        all — a solid cursor is what a full-screen editor wants.
        """
        if not (self.cur_ctrl & 1):
            return False
        rate = (self.cur_ctrl >> 3) & 3
        if rate == 3:
            return True
        return not (self.blink & (1 << (3 + rate)))

    @property
    def irq(self):
        return bool(self.irq_fl & (self.irq_en >> 4))

    PRESETS = {
        0: (0b00_00_00, 0x8000, 256, 480),
        1: (0b01_00_00, 0x8000, 256, 480),
        2: (0b11_10_01, 0x0000, 128, 480),
        3: (0b00_00_10, 0x0000, 80, 480),
        4: (0b11_10_10, 0x0000, 160, 480),
        5: (0b11_10_10, 0x0000, 128, 384),
        6: (0b11_11_10, 0x0000, 256, 480),
    }

    def _step_val(self):
        s = self.vstep & 7
        return (0, 1, 2, 4, 8, 16, 256, self.stride)[s]

    def _vadvance(self):
        d = self._step_val()
        self.vaddr = ((self.vaddr - d) if (self.vstep & 8)
                      else (self.vaddr + d)) & 0xFFFF

    def read(self, a):
        if a == 0x10:
            return self.mode
        if a == 0x11:
            return self.ctrl
        if a == 0x12:
            return self.base & 0xFF
        if a == 0x13:
            return self.base >> 8
        if a == 0x14:
            return self.stride & 0xFF
        if a == 0x15:
            return self.stride >> 8
        if a == 0x16:
            return self.scrl_x & 0xFF
        if a == 0x17:
            return self.scrl_x >> 8
        if a == 0x18:
            return self.scrl_y & 0xFF
        if a == 0x19:
            return self.scrl_y >> 8
        if a == 0x1A:
            return self.border
        if a == 0x1B:
            return self.raster & 0xFF
        if a == 0x1C:
            return self.rcmp
        if a == 0x1D:
            return self.irq_en | self.irq_fl
        if a == 0x1E:
            return self.pal_idx
        if a == 0x20:
            return self.pat_base & 0xFF
        if a == 0x21:
            return self.pat_base >> 8
        if a == 0x22:
            return self.cur_x
        if a == 0x23:
            return self.cur_y
        if a == 0x24:
            return self.cur_ctrl
        if a == 0x25:
            return self.cur_lines
        if a == 0x26:
            return self.vaddr & 0xFF
        if a == 0x27:
            return self.vaddr >> 8
        if a == 0x28:
            return self.vstep
        if a == 0x29 or a >= 0xC0:          # VRAM_DATA, and its $FEC0 alias
            b = self.vram[self.vaddr]
            self._vadvance()
            return b
        if a == 0x2A:
            return self.spr_idx
        if a == 0x2C:
            return ((self.spr_bank << 4) | (0x02 if self.spr_overrun else 0)
                    | (0x01 if self.spr_en else 0))
        if a in (0x34, 0x35, 0x36, 0x37):
            v = self.pix_x if a < 0x36 else self.pix_y
            return (v & 0xFF) if not (a & 1) else (v >> 8) & 7
        return 0xFF

    def write(self, a, v):
        if a == 0x10:
            self.mode = v
            p = self.PRESETS.get(v & 0x0F)
            if p:
                self.ctrl, self.base, self.stride, self.vactive = p
        elif a == 0x11:
            self.ctrl = v & 0x3F
        elif a == 0x12:
            self.base = (self.base & 0xFF00) | v
        elif a == 0x13:
            self.base = (self.base & 0x00FF) | (v << 8)
        elif a == 0x14:
            self.stride = (self.stride & 0xFF00) | v
        elif a == 0x15:
            self.stride = (self.stride & 0x00FF) | (v << 8)
        elif a == 0x16:
            self.scrl_x = (self.scrl_x & 0x300) | v
        elif a == 0x17:
            self.scrl_x = (self.scrl_x & 0xFF) | ((v & 3) << 8)
        elif a == 0x18:
            self.scrl_y = (self.scrl_y & 0x300) | v
        elif a == 0x19:
            self.scrl_y = (self.scrl_y & 0xFF) | ((v & 3) << 8)
        elif a == 0x1A:
            self.border = v
        elif a == 0x1C:
            self.rcmp = v
        elif a == 0x1D:
            self.irq_en = v & 0x30
            self.irq_fl &= ~(v & 0x03)
        elif a == 0x1E:
            self.pal_idx = v
            self._pal_half = 0
        elif a == 0x1F:
            if self._pal_half:
                self.pal[self.pal_idx] = (self._pal_red << 8) | v
                self.pal_idx = (self.pal_idx + 1) & 0xFF
                self._pal_half = 0
            else:
                self._pal_red = v & 0x0F
                self._pal_half = 1
        elif a == 0x20:
            self.pat_base = (self.pat_base & 0xFF00) | v
        elif a == 0x21:
            self.pat_base = (self.pat_base & 0x00FF) | (v << 8)
        elif a == 0x22:
            self.cur_x = v & 0x7F
            self.blink = 0
        elif a == 0x23:
            self.cur_y = v & 0x1F
            self.blink = 0
        elif a == 0x24:
            self.cur_ctrl = v & 0x1F
        elif a == 0x25:
            self.cur_lines = v
        elif a == 0x26:
            self.vaddr = (self.vaddr & 0xFF00) | v
        elif a == 0x27:
            self.vaddr = (self.vaddr & 0x00FF) | (v << 8)
        elif a == 0x28:
            self.vstep = v & 0x0F
        elif a == 0x29 or a >= 0xC0:
            self.vram[self.vaddr] = v
            self._vadvance()
        elif a == 0x2A:
            self.spr_idx = v
        elif a == 0x2B:
            if self.spr_idx & 1:
                self.spr[self.spr_idx - 1] = self._spr_hold
                self.spr[self.spr_idx] = v
            else:
                self._spr_hold = v
            self.spr_idx = (self.spr_idx + 1) & 0xFF
        elif a == 0x2C:
            self.spr_en = bool(v & 1)
            self.spr_bank = (v >> 4) & 0x0F
            if v & 2:
                self.spr_overrun = False
        elif a in (0x34, 0x35):
            self.pix_x = ((self.pix_x & 0x700) | v if a == 0x34
                          else (self.pix_x & 0xFF) | ((v & 7) << 8))
        elif a in (0x36, 0x37):
            self.pix_y = ((self.pix_y & 0x700) | v if a == 0x36
                          else (self.pix_y & 0xFF) | ((v & 7) << 8))
        elif a == 0x38:
            self._plot(v)

    def _plot(self, colour):
        """PIX_DATA: one pixel at (X, Y), then X advances. Write-only."""
        bpp = 1 << self.bpp_log
        row = self.base + self.pix_y * self.stride
        byte = (row + ((self.pix_x * bpp) >> 3)) & 0xFFFF
        if bpp == 8:
            self.vram[byte] = colour & 0xFF
        else:
            sub = (self.pix_x * bpp) & 7
            shift = 8 - bpp - sub
            mask = ((1 << bpp) - 1) << shift
            self.vram[byte] = ((self.vram[byte] & ~mask) |
                               ((colour << shift) & mask)) & 0xFF
        self.pix_x = (self.pix_x + 1) & 0x7FF


class MachineBus(emu.Bus):
    """The memory map of docs section 2, and nothing the CPU cannot see.

    Three rules, and they are the whole of it:

      the I/O page at $FE00-$FEFF is decoded first and always wins;
      reads at $F000-$FFFF come from ROM while ROMEN is set, less that
        hole;
      **writes always go to RAM**, which is what lets the boot code
        install vectors at $FFF8 that it cannot yet read back.
    """

    def __init__(self, machine):
        super().__init__()
        self.m = machine

    def read(self, addr):
        addr &= 0xFFFF
        if (addr & 0xFF00) == 0xFE00:
            return self.m.io_read(addr & 0xFF)
        if self.m.romen and (addr & 0xF000) == 0xF000:
            return self.m.rom[addr & 0x0FFF]
        return self.mem[addr]

    def write(self, addr, value):
        addr &= 0xFFFF
        # A watch costs one compare when nothing is watched, which is
        # why it can live on the bus rather than in a separate wrapper.
        if self.m._wlo <= addr <= self.m._whi:
            self.m.hits.append((self.m.cpu.pc, addr, value & 0xFF))
        if (addr & 0xFF00) == 0xFE00:
            self.m.io_write(addr & 0xFF, value & 0xFF)
            return
        self.mem[addr] = value & 0xFF


class Machine:
    def __init__(self, rom=None, font=None, flash_path=None):
        self.rom = rom if rom is not None else bytearray(4096)
        self.romen = True
        self.led = 0
        self.build_id = 0x05

        self.video = Video()
        self.sound = Sound()
        self.uart = Uart()
        self.kbd = Ps2()
        self.flash = Flash(flash_path)
        if font is not None:
            self.video.font[:len(font)] = font

        self.bus = MachineBus(self)
        self.cpu = emu.Cool8(self.bus)
        self.cpu.reset()

        self.line = 0
        self.frames = 0
        self._snd_owed = 0
        self._tick_owed = 0
        self.breakpoints = set()
        self._wlo, self._whi = 1, 0     # an empty watch range
        self.hits = []
        self._plabels = None            # profiling off costs one test
        self._pby, self._ptotal = {}, 0

    # -------------------------------------------------------- the I/O page

    def io_read(self, a):
        if a == 0x00:
            return 0x01 if self.romen else 0x00
        if a == 0x02:
            return self.build_id
        if a == 0x03:
            return self.led
        if 0x10 <= a <= 0x3F or a >= 0xC0:
            return self.video.read(a)
        if 0x40 <= a <= 0x43:
            return self.kbd.read(a)
        if 0x50 <= a <= 0x51:
            return self.sound.read(a)
        if 0x70 <= a <= 0x73:
            return self.uart.read(a)
        if 0x88 <= a <= 0x8F:
            return self.flash.read(a)
        return 0xFF                     # as a bus nobody is driving reads

    def io_write(self, a, v):
        if a == 0x00:
            self.romen = bool(v & 1)
        elif a == 0x03:
            self.led = v & 7
        elif 0x10 <= a <= 0x3F or a >= 0xC0:
            self.video.write(a, v)
        elif 0x40 <= a <= 0x43:
            self.kbd.write(a, v)
        elif 0x50 <= a <= 0x51:
            self.sound.write(a, v)
        elif 0x70 <= a <= 0x73:
            self.uart.write(a, v)
        elif 0x88 <= a <= 0x8F:
            self.flash.write(a, v)

    # ---------------------------------------------------------- running

    def _irq(self):
        return self.video.irq or self.kbd.irq

    # ------------------------------------------------ driving it from outside
    #
    # A test program should be able to type at this machine and read what
    # it said back without knowing how either works. Both of these went
    # unwritten for a long time and every harness grew its own copy --
    # `sim/test_basic.py` reached into `cool8vid._row_addr_v`, a private
    # function, to work out where a row of text lives.

    def type(self, text):
        """Type at the machine. `\\n` becomes Return, as a terminal sends it.

        Bytes go into the UART's 16-byte FIFO, so feed a line at a time
        and let the machine drain it -- exactly the constraint a real
        serial console has at 115200.
        """
        if isinstance(text, str):
            text = text.replace("\n", "\r").encode("latin-1")
        self.uart.feed(text)

    def said(self):
        """Everything the machine has sent since the last call."""
        return self.uart.take()

    def key(self, text):
        """Type at the machine's *keyboard*, rather than at its serial port.

        `type()` reaches the UART, which is the console on a desk with a
        cable to it. This reaches the PS/2 port, which is what a person
        at the board uses -- a different driver, a different interrupt
        and, until sw/kbd.asm existed, no driver at all in BASIC. A test
        that only ever calls `type()` proves nothing about the machine
        anyone will actually hold.

        Each character becomes its Set 2 make code and its `$F0` break
        code, with shift wrapped round the ones that need it, so what
        arrives is what a keyboard sends. Named keys go in as `K_*`
        strings: `m.key(["K_UP", "K_UP"])` or `m.key("HI" + "\\n")`.
        """
        self.kbd.feed(_encode_keys(text))

    def scancode(self, codes):
        """Raw Set 2 bytes, for the cases `key()` cannot express.

        A make with no matching break -- a key *held* -- is the obvious
        one, and it is the whole point of the bitmap KEY() reads. Also
        `$E0` prefixes, `$E1`, and anything else being fed deliberately
        malformed to see what the decoder does with it.
        """
        self.kbd.feed(bytes(codes))

    def row(self, r, cols=80):
        """One row of the text screen, through the machine's own VID_BASE.

        Read from the registers rather than from a remembered address, so
        a program that forgets to set VID_BASE fails here the way it
        would on the board -- the rule docs/10-debugging.md section 3 was
        written about.
        """
        import cool8vid as _vid
        base = _vid._row_addr_v(self.video, r)
        return "".join(chr(self.bus.mem[(base + 2 * c) & 0xFFFF])
                       for c in range(cols)).replace("\x00", " ").rstrip()

    def text(self, rows=30, cols=80):
        """The visible text screen, as a list of strings."""
        return [self.row(r, cols) for r in range(rows)]

    def shows(self, want):
        """Is `want` a line on the screen, ignoring surrounding space?"""
        return any(r.strip() == want for r in self.text())

    # ------------------------------------------------------- debugging
    #
    # Breakpoints, a watch and a profile live on the machine itself,
    # because the alternative is what happened for a year: every harness
    # grew its own stepping loop, and each one was a machine with
    # slightly different behaviour. sim/dbg.py still owns the
    # *structural* checks -- that every RET matches its CALL, that no PC
    # lands mid-instruction -- which need a shadow stack and a decoded
    # image and are a different job.

    def watch(self, lo, hi=None):
        """Record every write into [lo, hi] as (pc, addr, value).

        `m.hits` is the log. This is the tool for "who wrote to that
        byte" -- the question that otherwise gets answered by bisecting
        print statements.
        """
        self._wlo, self._whi = lo, hi if hi is not None else lo
        self.hits = []

    def unwatch(self):
        self._wlo, self._whi = 1, 0        # an empty range: never matches
        self.hits = []

    def trace(self, n=40, syms=None, into=True):
        """Run n instructions and return what they were.

        Each row is `(pc, label, text, regs)` -- the address, the nearest
        preceding symbol, the disassembly, and R0-R3/X/Y/SP/flags *after*
        it ran. `print(m.trace_report(...))` formats it.

        This is the question a breakpoint alone cannot answer: not "where
        did it stop" but "what did it do on the way". Decoding is
        forward from the live PC, one instruction at a time, so the
        boundaries are the ones the CPU actually used rather than a
        guess made by decoding backwards from a symptom -- the mistake
        that cost a day and is written up at the top of sim/dbg.py.

        `into=False` runs CALLs to completion instead of stepping into
        them, which is how you watch one routine's shape without its
        callees burying it.
        """
        rd = lambda a: self.bus.mem[a & 0xFFFF]           # noqa: E731
        rows = []
        for _ in range(n):
            pc = self.cpu.pc
            try:
                text, size = opcodes.disassemble(rd, pc)
            except Exception:
                text, size = "??", 1
            depth = 0
            self.tick()
            if not into and text.split()[0] == "CALL":
                # Back to the instruction after the call, however deep it
                # went. A stack-pointer test, not a matching-RET test:
                # RETI and a hand-rolled return both land here too.
                sp = self.cpu.sp
                while self.cpu.sp < sp and depth < 5_000_000:
                    self.tick()
                    depth += 1
            c = self.cpu
            regs = (c.r[0], c.r[1], c.r[2], c.r[3], c.x, c.y, c.sp,
                    "".join(f for f, b in
                            (("Z", c.Z), ("N", c.N), ("C", c.C))
                            if b) or "-")
            rows.append((pc, self._sym(pc, syms), text, regs))
        return rows

    def trace_report(self, rows):
        """A trace as text, one instruction a line."""
        out = []
        for pc, label, text, r in rows:
            out.append("$%04X %-14s %-22s R %02X %02X %02X %02X  "
                       "X %04X Y %04X SP %04X %s"
                       % (pc, label or "", text, r[0], r[1], r[2], r[3],
                          r[4], r[5], r[6], r[7]))
        return "\n".join(out)

    def _sym(self, pc, syms):
        if not syms:
            return ""
        best = None
        for n, a in syms.items():
            if a <= pc and (best is None or a > best[1]):
                best = (n, a)
        if best is None:
            return ""
        return best[0] if best[1] == pc else "%s+%d" % (best[0], pc - best[1])

    def profile(self, syms, org=0, end=0x10000):
        """Attribute every cycle from here on to the routine it ran in.

        Attribution is by nearest preceding code label and the cost is
        the emulator's own cycle count, so the numbers add up to the
        total rather than approximating it. `profile_report()` reads
        them back.

        **Profile before optimising.** A round once went into the
        expression evaluator at 16 % of a run while the line machinery
        was 48 %, and a 256-byte lookup table built on a guess bought
        2 %.
        """
        self._plabels = sorted(
            (a, n) for n, a in syms.items()
            if org <= a < end and not n.startswith(("v_", "a_", "str_")))
        self._pby, self._ptotal = {}, 0

    def profile_report(self, top=14):
        """[(name, cycles, percent)], heaviest first."""
        t = self._ptotal or 1
        rows = sorted(self._pby.items(), key=lambda kv: -kv[1])[:top]
        return [(n, c, 100.0 * c / t) for n, c in rows]

    def _pwho(self, pc):
        lo = None
        for a, n in self._plabels:
            if a <= pc:
                lo = n
            else:
                break
        return lo or f"${pc:04X}"

    def run(self, until=None, cycles=None, budget=200_000_000):
        """Run the machine. Returns why it stopped.

        `until` is a predicate on the machine, a PC, or a set of PCs.
        Stops on a breakpoint in `m.breakpoints` whatever else is asked,
        and on a HALT -- a PC that does not move.
        """
        if isinstance(until, int):
            until = {until}
        if isinstance(until, (set, frozenset, list, tuple)):
            want = set(until)
            until = lambda mm: mm.cpu.pc in want          # noqa: E731
        start, last = self.cpu.cycles, -1
        for _ in range(budget):
            if until is not None and until(self):
                return "until"
            if self.breakpoints and self.cpu.pc in self.breakpoints:
                return "breakpoint"
            if cycles is not None and self.cpu.cycles - start >= cycles:
                return "cycles"
            if self.cpu.pc == last:
                return "halt"
            last = self.cpu.pc
            self.tick()
        return "budget"

    def _end_line(self):
        """The bookkeeping that happens when a scanline finishes."""
        # Sound is taken at a fixed rate rather than per line, so the
        # sample stream is the right length however long a line runs.
        self._snd_owed += CYCLES_PER_LINE
        n, self._snd_owed = divmod(self._snd_owed, SND_DIV)
        self.sound.tick(n)

        self.line += 1
        if self.line >= V_TOTAL:
            self.line = 0
            self.frames += 1
            self.video.blink += 1
            self.video.irq_fl |= 0x02           # vblank
        self.video.raster = self.line
        if (self.line & 0xFF) == self.video.rcmp:
            self.video.irq_fl |= 0x01           # raster compare

    def run_line(self):
        """One scanline: the CPU, then the raster, then the interrupts."""
        target = self.cpu.cycles + CYCLES_PER_LINE
        while self.cpu.cycles < target:
            # irq_line, not irq. cool8emu.py's input is `irq_line`;
            # assigning `irq` made a new attribute the CPU never read,
            # so this machine could not deliver an interrupt to anything
            # and nothing noticed until software wanted one.
            self.cpu.irq_line = self._irq()
            self.cpu.step()
        self._end_line()

    def tick(self):
        """One instruction, with the raster and the interrupts kept in
        step with it.

        **A harness that loops on `cpu.step()` runs a machine where no
        time passes.** Only `run_line` advanced the raster, the sound and
        the interrupt flags, so a bare stepping loop gave a machine with
        no vblank, no raster compare and no interrupt that could ever
        fire -- and anything waiting on one waited for ever. That was
        invisible while every harness polled its devices; it stops being
        invisible the moment software wants an interrupt.

        Instruction granularity rather than a whole line, because a
        harness watching for a particular PC has to see every one.
        """
        self.cpu.irq_line = self._irq()
        before = self.cpu.cycles
        pc = self.cpu.pc
        self.cpu.step()
        spent = self.cpu.cycles - before
        if self._plabels is not None:
            who = self._pwho(pc)
            self._pby[who] = self._pby.get(who, 0) + spent
            self._ptotal += spent
        self._tick_owed += spent
        while self._tick_owed >= CYCLES_PER_LINE:
            self._tick_owed -= CYCLES_PER_LINE
            self._end_line()

    def run_frame(self):
        for _ in range(V_TOTAL):
            self.run_line()

    def press_break(self):
        """SW[0]. An NMI, and nothing else changes."""
        self.cpu.pulse_nmi()


def build_rom():
    base, img, rom = mkrom.build(os.path.join(ROOT, 'sw', 'boot.asm'))
    font, _, _ = mkfont.build(os.path.join(ROOT, 'assets', 'font',
                                           'spleen-8x16.bdf'))
    return bytearray(rom), bytearray(font)


def boot(flash_path=None):
    """A machine with the real ROM in it, sitting at its reset vector."""
    rom, font = build_rom()
    return Machine(rom=rom, font=font, flash_path=flash_path)


def converse(m, text='', frames=8):
    """Type at the machine, and collect what it says back."""
    if text:
        m.uart.feed(text.replace('\\r', '\r').encode('latin-1'))
    for _ in range(frames):
        m.run_frame()
    return m.uart.take().decode('latin-1')


def selftest():
    """The machine boots, and answers the way the hardware answers.

    **The dump below came off a real board's serial console**, not out of
    this file. That is the point of it: a divergence here is the emulator
    drifting from the machine, not from itself.
    """
    m = boot()
    fails = 0

    def check(ok, what):
        nonlocal fails
        print(f'  {"ok  " if ok else "FAIL"} {what}')
        fails += not ok

    said = converse(m)
    check('COOL8 monitor' in said, 'it introduces itself')
    check('*' in said, 'and prompts')

    said = converse(m, 'D F000\r')
    check('F000 2F 60 00 02' in said,
          'D F000 starts with the reset vector\'s LDW X,#$0200')
    check('F070 F2 00 02 69 22 FE 00 03 69 23 FE 00 0F 69 25 FE' in said,
          '...and $F070 matches the board byte for byte')

    check(m.led == 0x01, 'the boot ROM left the LED blue')

    # The flash, and the floor that is the whole reason it is safe.
    m.flash.mem[0x100000] = 0xFF
    for a, v in ((0x88, 0x00), (0x89, 0x00), (0x8A, 0x10),
                 (0x8E, 0x5A), (0x8F, 0x01)):
        m.flash.write(a, v)
    check(m.flash.mem[0x100000] == 0x5A, 'a byte above the floor programmed')

    m.flash.mem[0x000100] = 0x77
    for a, v in ((0x8A, 0x00), (0x89, 0x01), (0x88, 0x00),
                 (0x8E, 0x00), (0x8F, 0x01)):
        m.flash.write(a, v)
    check(m.flash.mem[0x000100] == 0x77 and m.flash.denied,
          'and one below it was refused, and said so')

    print('\nPASS' if not fails else f'\nFAILED {fails}')
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--frames', type=int, default=8)
    ap.add_argument('--type', default='', help='send this to the monitor')
    ap.add_argument('--flash', help='a file to back the SPI flash with')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    m = boot(args.flash)
    sys.stdout.write(converse(m, args.type, args.frames))
    sys.stdout.write('\n')
    print(f'-- {m.frames} frames, {m.cpu.cycles} cycles, LED ${m.led:02X}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
