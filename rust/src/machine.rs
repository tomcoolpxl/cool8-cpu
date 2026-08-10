// The COOL8 machine — a hand port of tools/cool8vm.py's Machine, its
// bus and its peripherals, to the same rule as cpu.rs: cool8vm.py is
// the reference, this copy is never authoritative, and sim/rustsim.py
// diffs the two per retired instruction over a real boot with the RAM
// and the VRAM compared at the end.
//
// What is here is what the CPU can see: the register files, the FIFOs,
// the flash, the scanline accounting that makes time pass. Rendering is
// deliberately absent — cool8vid.py stays the only renderer — and so is
// the font, which no register exposes.
//
// The machine is scanline-accurate through tick(), cool8vm's own
// discipline: one instruction, then the raster, the sound clock and the
// interrupt flags kept in step through the owed-cycles accumulator.
// Both sides of the parity diff must use tick(), not run_line(): the
// two differ in how a line boundary falls mid-instruction, and mixing
// them diverges the interrupt timing.

use crate::cpu::{Bus, Cpu};
use std::collections::VecDeque;

// docs/04-system.md section 5.1 and D32.
pub const CYCLES_PER_LINE: u64 = 266;
pub const V_TOTAL: u32 = 525;
const SND_DIV: u64 = 256;

// ------------------------------------------------------------------ UART

pub struct Uart {
    pub rx: VecDeque<u8>,
    pub tx: Vec<u8>, // everything the machine has said
    pub overrun: bool,
    pub div: u16,
}

impl Uart {
    const DEPTH: usize = 16;

    fn new() -> Uart {
        Uart { rx: VecDeque::new(), tx: Vec::new(), overrun: false, div: 72 }
    }

    pub fn feed(&mut self, data: &[u8]) {
        for &b in data {
            if self.rx.len() < Uart::DEPTH {
                self.rx.push_back(b);
            } else {
                self.overrun = true;
            }
        }
    }

    fn read(&mut self, a: u8) -> u8 {
        match a {
            0x70 => {
                (if self.rx.is_empty() { 0 } else { 0x01 })
                    | 0x02
                    | (if self.overrun { 0x04 } else { 0 })
            }
            0x71 => self.rx.pop_front().unwrap_or(0xFF),
            0x72 => self.div as u8,
            0x73 => (self.div >> 8) as u8,
            _ => 0xFF,
        }
    }

    fn write(&mut self, a: u8, v: u8) {
        match a {
            0x70 => {
                if v & 0x04 != 0 {
                    self.overrun = false;
                }
            }
            0x71 => self.tx.push(v),
            0x72 => self.div = (self.div & 0xFF00) | v as u16,
            0x73 => self.div = (self.div & 0x00FF) | (v as u16) << 8,
            _ => {}
        }
    }
}

// ------------------------------------------------------------------- PS/2

pub struct Ps2 {
    pub q: VecDeque<u8>,
    pub overrun: bool,
    pub irq_en: bool,
}

impl Ps2 {
    const DEPTH: usize = 16;

    fn new() -> Ps2 {
        Ps2 { q: VecDeque::new(), overrun: false, irq_en: false }
    }

    pub fn feed(&mut self, codes: &[u8]) {
        for &b in codes {
            if self.q.len() < Ps2::DEPTH {
                self.q.push_back(b);
            } else {
                self.overrun = true;
            }
        }
    }

    fn irq(&self) -> bool {
        self.irq_en && !self.q.is_empty()
    }

    fn read(&mut self, a: u8) -> u8 {
        match a {
            0x40 => {
                (if self.q.is_empty() { 0 } else { 0x01 })
                    | (if self.overrun { 0x02 } else { 0 })
            }
            0x41 => self.q.pop_front().unwrap_or(0xFF),
            0x42 => if self.irq_en { 0x10 } else { 0x00 },
            _ => 0xFF,
        }
    }

    fn write(&mut self, a: u8, v: u8) {
        match a {
            0x40 => {
                if v & 0x02 != 0 {
                    self.overrun = false;
                }
            }
            0x42 => {
                self.irq_en = v & 0x10 != 0;
                if v & 0x01 != 0 {
                    self.q.clear();
                }
            }
            _ => {}
        }
    }
}

// ------------------------------------------------------------------ flash

pub struct Flash {
    pub mem: Vec<u8>,
    addr: u32,
    open_r: bool,
    wdata: u8,
    denied: bool,
}

impl Flash {
    const SIZE: usize = 8 << 20;
    const FLOOR: u32 = 0x100000;
    const SECTOR: usize = 4096;

    fn new(image: Option<Vec<u8>>) -> Flash {
        let mut mem = vec![0xFFu8; Flash::SIZE];
        if let Some(d) = image {
            let n = d.len().min(Flash::SIZE);
            mem[..n].copy_from_slice(&d[..n]);
        }
        Flash { mem, addr: 0, open_r: false, wdata: 0, denied: false }
    }

    fn read(&mut self, a: u8) -> u8 {
        match a {
            0x88 => self.addr as u8,
            0x89 => (self.addr >> 8) as u8,
            0x8A => (self.addr >> 16) as u8,
            0x8B => {
                // a read advances the stream
                if !self.open_r {
                    return 0xFF;
                }
                let b = self.mem[self.addr as usize % Flash::SIZE];
                self.addr = (self.addr + 1) & 0xFFFFFF;
                b
            }
            0x8C => if self.open_r { 0x01 } else { 0x00 },
            0x8D => if self.open_r { 0x02 } else { 0x00 },
            0x8F => if self.denied { 0x04 } else { 0x00 },
            _ => 0xFF,
        }
    }

    fn write(&mut self, a: u8, v: u8) {
        match a {
            0x88 | 0x89 | 0x8A if !self.open_r => {
                let sh = match a {
                    0x88 => 0,
                    0x89 => 8,
                    _ => 16,
                };
                self.addr = (self.addr & !(0xFF << sh)) | (v as u32) << sh;
            }
            0x8C => self.open_r = v & 1 != 0,
            0x8E => self.wdata = v,
            0x8F => {
                if v & 0x04 != 0 {
                    self.denied = false;
                }
                if self.open_r {
                    return;
                }
                if v & 0x01 != 0 {
                    // program: a flash can only clear bits
                    if self.addr < Flash::FLOOR {
                        self.denied = true;
                    } else {
                        let i = self.addr as usize % Flash::SIZE;
                        self.mem[i] &= self.wdata;
                    }
                } else if v & 0x02 != 0 {
                    // erase the 4 KB sector
                    if self.addr < Flash::FLOOR {
                        self.denied = true;
                    } else {
                        let base = (self.addr as usize % Flash::SIZE)
                            & !(Flash::SECTOR - 1);
                        self.mem[base..base + Flash::SECTOR].fill(0xFF);
                    }
                }
            }
            _ => {}
        }
    }
}

// ------------------------------------------------------------------ sound

pub struct Sound {
    inc: [u16; 8],
    phase: [u16; 8],
    vol: [u8; 8],
    enable: [bool; 8],
    noise: [bool; 8],
    idx: u8,
    hold: u8,
    lfsr: u16,
    pub samples: Vec<u8>, // unsigned 8-bit, SND_HZ
}

impl Sound {
    const VOICES: usize = 8;

    fn new() -> Sound {
        Sound {
            inc: [0; 8],
            phase: [0; 8],
            vol: [0; 8],
            enable: [false; 8],
            noise: [false; 8],
            idx: 0,
            hold: 0,
            lfsr: 0xACE1,
            samples: Vec::new(),
        }
    }

    fn write(&mut self, a: u8, v: u8) {
        if a == 0x50 {
            self.idx = v & 0x3F;
        } else if a == 0x51 {
            if self.idx & 1 != 0 {
                // the odd byte commits the word
                let word = (v as u16) << 8 | self.hold as u16;
                let (vc, which) = ((self.idx >> 3) as usize,
                                   (self.idx >> 1) & 3);
                if vc < Sound::VOICES {
                    if which == 0 {
                        self.inc[vc] = word;
                    } else if which == 1 {
                        self.phase[vc] = word;
                    } else {
                        self.vol[vc] = (word & 0x0F) as u8;
                        self.enable[vc] = word & 0x4000 != 0;
                        self.noise[vc] = word & 0x8000 != 0;
                    }
                }
            } else {
                self.hold = v;
            }
            self.idx = (self.idx + 1) & 0x3F;
        }
    }

    /// One mixed sample, signed, in the mixer's own -128..127 range.
    fn sample(&mut self) -> i32 {
        let mut mix: i32 = 0;
        for v in 0..Sound::VOICES {
            let nxt = (self.phase[v] as u32 + self.inc[v] as u32) & 0x1FFFF;
            let wrapped = nxt > 0xFFFF;
            let old = self.phase[v];
            self.phase[v] = nxt as u16;
            if !self.enable[v] {
                continue;
            }
            let wave = if self.noise[v] {
                let w = self.lfsr & 1;
                if wrapped {
                    let bit = ((self.lfsr >> 15) ^ (self.lfsr >> 13)
                        ^ (self.lfsr >> 12) ^ (self.lfsr >> 10)) & 1;
                    self.lfsr = (self.lfsr << 1) | bit;
                }
                w
            } else {
                (old >> 15) & 1
            };
            mix += if wave != 0 { self.vol[v] as i32 } else { -(self.vol[v] as i32) };
        }
        mix.clamp(-128, 127)
    }

    /// The byte the modulator is fed. The halving is the headroom that
    /// lets eight voices sum without the pin clipping — see cool8vm.py.
    fn level(&mut self) -> u8 {
        (128 + (self.sample() >> 1)) as u8
    }

    fn tick(&mut self, n: u64) {
        for _ in 0..n {
            let l = self.level();
            self.samples.push(l);
        }
    }
}

// ------------------------------------------------------------------ video

/// The register file, VRAM, and the state a frame is drawn from —
/// everything software can see and set, and nothing about how a
/// scanline is assembled.
pub struct Video {
    pub vram: Box<[u8; 0x10000]>,
    pub pal: [u16; 256],

    pub mode: u8,
    pub ctrl: u8,
    pub base: u16,
    pub stride: u16,
    pub pat_base: u16,
    pub scrl_x: u16,
    pub scrl_y: u16,
    pub border: u8,
    pub rcmp: u8,
    pub irq_en: u8,
    pub irq_fl: u8,
    pub vactive: u16,
    pub raster: u32,
    pub blink: u32, // frames; the phase restarts on a move

    pal_idx: u8,
    pal_half: bool,
    pal_red: u8,

    pub cur_x: u8,
    pub cur_y: u8,
    pub cur_ctrl: u8,
    pub cur_lines: u8,

    // VRAM port
    vaddr: u16,
    vstep: u8,

    // pixel port
    pix_x: u16,
    pix_y: u16,

    // sprites: 32 descriptors of 8 bytes
    pub spr: [u8; 256],
    spr_idx: u8,
    spr_hold: u8,
    pub spr_en: bool,
    pub spr_overrun: bool,
    pub spr_bank: u8,
}

// Mode presets, as cool8vm.Video.PRESETS: (ctrl, base, stride, vactive).
const PRESETS: [(u8, u16, u16, u16); 7] = [
    (0b00_00_00, 0x8000, 256, 480),
    (0b01_00_00, 0x8000, 256, 480),
    (0b11_10_01, 0x0000, 128, 480),
    (0b00_00_10, 0x0000, 80, 480),
    (0b11_10_10, 0x0000, 160, 480),
    (0b11_10_10, 0x0000, 128, 384),
    (0b11_11_10, 0x0000, 256, 480),
];

impl Video {
    fn new() -> Video {
        Video {
            vram: vec![0u8; 0x10000].into_boxed_slice().try_into().unwrap(),
            pal: [0; 256],
            mode: 0,
            ctrl: 0,
            base: 0x8000,
            stride: 256,
            pat_base: 0,
            scrl_x: 0,
            scrl_y: 0,
            border: 0,
            rcmp: 0,
            irq_en: 0,
            irq_fl: 0,
            vactive: 480,
            raster: 0,
            blink: 0,
            pal_idx: 0,
            pal_half: false,
            pal_red: 0,
            cur_x: 0,
            cur_y: 0,
            cur_ctrl: 0,
            cur_lines: 0xF0,
            vaddr: 0,
            vstep: 1,
            pix_x: 0,
            pix_y: 0,
            spr: [0; 256],
            spr_idx: 0,
            spr_hold: 0,
            spr_en: false,
            spr_overrun: false,
            spr_bank: 0,
        }
    }

    pub fn bpp_log(&self) -> u8 {
        (self.ctrl >> 2) & 3
    }

    /// The per-line slot scan, as cool8_sprite.v runs it and exactly as
    /// cool8vm.Video.scan_sprites states it: eight sprites fit on a
    /// scanline, the ninth sets the overrun flag, and the two trailing
    /// rows past a sprite's bottom edge take slots like anything else.
    pub fn scan_sprites(&mut self, line: u32) {
        let mut hits = 0;
        for si in (0..256).step_by(8) {
            let d1 = self.spr[si + 1];
            if d1 & 0x40 == 0 {
                continue;
            }
            let h = if d1 & 0x80 != 0 { 16u32 } else { 8 };
            let y = ((d1 as u32 & 0x01) << 8) | self.spr[si] as u32;
            let dy = line.wrapping_sub(y) & 0x3FF;
            if !(dy < h + 2 && (line < 480 || dy >= h)) {
                continue;
            }
            if hits == 8 {
                self.spr_overrun = true;
            } else {
                hits += 1;
            }
        }
    }

    fn irq(&self) -> bool {
        self.irq_fl & (self.irq_en >> 4) != 0
    }

    fn step_val(&self) -> u16 {
        match self.vstep & 7 {
            0 => 0,
            1 => 1,
            2 => 2,
            3 => 4,
            4 => 8,
            5 => 16,
            6 => 256,
            _ => self.stride,
        }
    }

    fn vadvance(&mut self) {
        let d = self.step_val();
        self.vaddr = if self.vstep & 8 != 0 {
            self.vaddr.wrapping_sub(d)
        } else {
            self.vaddr.wrapping_add(d)
        };
    }

    fn read(&mut self, a: u8) -> u8 {
        match a {
            0x10 => self.mode,
            0x11 => self.ctrl,
            0x12 => self.base as u8,
            0x13 => (self.base >> 8) as u8,
            0x14 => self.stride as u8,
            0x15 => (self.stride >> 8) as u8,
            0x16 => self.scrl_x as u8,
            0x17 => (self.scrl_x >> 8) as u8,
            0x18 => self.scrl_y as u8,
            0x19 => (self.scrl_y >> 8) as u8,
            0x1A => self.border,
            0x1B => self.raster as u8,
            0x1C => self.rcmp,
            0x1D => self.irq_en | self.irq_fl,
            0x1E => self.pal_idx,
            0x20 => self.pat_base as u8,
            0x21 => (self.pat_base >> 8) as u8,
            0x22 => self.cur_x,
            0x23 => self.cur_y,
            0x24 => self.cur_ctrl,
            0x25 => self.cur_lines,
            0x26 => self.vaddr as u8,
            0x27 => (self.vaddr >> 8) as u8,
            0x28 => self.vstep,
            0x29 | 0xC0..=0xFF => {
                // VRAM_DATA, and its $FEC0 alias
                let b = self.vram[self.vaddr as usize];
                self.vadvance();
                b
            }
            0x2A => self.spr_idx,
            0x2C => {
                (self.spr_bank << 4)
                    | (if self.spr_overrun { 0x02 } else { 0 })
                    | (if self.spr_en { 0x01 } else { 0 })
            }
            0x34 | 0x35 | 0x36 | 0x37 => {
                let v = if a < 0x36 { self.pix_x } else { self.pix_y };
                if a & 1 == 0 { v as u8 } else { ((v >> 8) & 7) as u8 }
            }
            _ => 0xFF,
        }
    }

    fn write(&mut self, a: u8, v: u8) {
        match a {
            0x10 => {
                self.mode = v;
                if let Some(p) = PRESETS.get((v & 0x0F) as usize) {
                    self.ctrl = p.0;
                    self.base = p.1;
                    self.stride = p.2;
                    self.vactive = p.3;
                }
            }
            0x11 => self.ctrl = v & 0x3F,
            0x12 => self.base = (self.base & 0xFF00) | v as u16,
            0x13 => self.base = (self.base & 0x00FF) | (v as u16) << 8,
            0x14 => self.stride = (self.stride & 0xFF00) | v as u16,
            0x15 => self.stride = (self.stride & 0x00FF) | (v as u16) << 8,
            0x16 => self.scrl_x = (self.scrl_x & 0x300) | v as u16,
            0x17 => self.scrl_x = (self.scrl_x & 0xFF) | ((v & 3) as u16) << 8,
            0x18 => self.scrl_y = (self.scrl_y & 0x300) | v as u16,
            0x19 => self.scrl_y = (self.scrl_y & 0xFF) | ((v & 3) as u16) << 8,
            0x1A => self.border = v,
            0x1C => self.rcmp = v,
            0x1D => {
                self.irq_en = v & 0x30;
                self.irq_fl &= !(v & 0x03);
            }
            0x1E => {
                self.pal_idx = v;
                self.pal_half = false;
            }
            0x1F => {
                if self.pal_half {
                    self.pal[self.pal_idx as usize] =
                        (self.pal_red as u16) << 8 | v as u16;
                    self.pal_idx = self.pal_idx.wrapping_add(1);
                    self.pal_half = false;
                } else {
                    self.pal_red = v & 0x0F;
                    self.pal_half = true;
                }
            }
            0x20 => self.pat_base = (self.pat_base & 0xFF00) | v as u16,
            0x21 => self.pat_base = (self.pat_base & 0x00FF) | (v as u16) << 8,
            0x22 => {
                self.cur_x = v & 0x7F;
                self.blink = 0;
            }
            0x23 => {
                self.cur_y = v & 0x1F;
                self.blink = 0;
            }
            0x24 => self.cur_ctrl = v & 0x1F,
            0x25 => self.cur_lines = v,
            0x26 => self.vaddr = (self.vaddr & 0xFF00) | v as u16,
            0x27 => self.vaddr = (self.vaddr & 0x00FF) | (v as u16) << 8,
            0x28 => self.vstep = v & 0x0F,
            0x29 | 0xC0..=0xFF => {
                self.vram[self.vaddr as usize] = v;
                self.vadvance();
            }
            0x2A => self.spr_idx = v,
            0x2B => {
                if self.spr_idx & 1 != 0 {
                    self.spr[(self.spr_idx - 1) as usize] = self.spr_hold;
                    self.spr[self.spr_idx as usize] = v;
                } else {
                    self.spr_hold = v;
                }
                self.spr_idx = self.spr_idx.wrapping_add(1);
            }
            0x2C => {
                self.spr_en = v & 1 != 0;
                self.spr_bank = (v >> 4) & 0x0F;
                if v & 2 != 0 {
                    self.spr_overrun = false;
                }
            }
            0x34 => self.pix_x = (self.pix_x & 0x700) | v as u16,
            0x35 => self.pix_x = (self.pix_x & 0xFF) | ((v & 7) as u16) << 8,
            0x36 => self.pix_y = (self.pix_y & 0x700) | v as u16,
            0x37 => self.pix_y = (self.pix_y & 0xFF) | ((v & 7) as u16) << 8,
            0x38 => self.plot(v),
            _ => {}
        }
    }

    /// PIX_DATA: one pixel at (X, Y), then X advances. Write-only.
    fn plot(&mut self, colour: u8) {
        let bpp = 1u32 << self.bpp_log();
        let row = self.base as u32 + self.pix_y as u32 * self.stride as u32;
        let byte = ((row + ((self.pix_x as u32 * bpp) >> 3)) & 0xFFFF) as usize;
        if bpp == 8 {
            self.vram[byte] = colour;
        } else {
            let sub = (self.pix_x as u32 * bpp) & 7;
            let shift = 8 - bpp - sub;
            let mask = (((1u32 << bpp) - 1) << shift) as u8;
            self.vram[byte] = (self.vram[byte] & !mask)
                | (((colour as u32) << shift) as u8 & mask);
        }
        self.pix_x = (self.pix_x + 1) & 0x7FF;
    }
}

// ---------------------------------------------------------------- the bus

/// The memory map of docs/04-system.md section 2: the I/O page wins,
/// reads at $F000-$FFFF come from ROM while ROMEN is set, and writes
/// always go to RAM.
pub struct MachineBus {
    pub mem: Box<[u8; 0x10000]>,
    pub rom: [u8; 4096],
    pub romen: bool,
    pub led: u8,
    build_id: u8,
    pub uart: Uart,
    pub kbd: Ps2,
    pub sound: Sound,
    pub video: Video,
    pub flash: Flash,
}

impl MachineBus {
    fn io_read(&mut self, a: u8) -> u8 {
        match a {
            0x00 => if self.romen { 0x01 } else { 0x00 },
            0x02 => self.build_id,
            0x03 => self.led,
            0x10..=0x3F | 0xC0..=0xFF => self.video.read(a),
            0x40..=0x43 => self.kbd.read(a),
            0x50..=0x51 => 0xFF, // sound is write-only, as the hardware is
            0x70..=0x73 => self.uart.read(a),
            0x88..=0x8F => self.flash.read(a),
            _ => 0xFF, // as a bus nobody is driving reads
        }
    }

    fn io_write(&mut self, a: u8, v: u8) {
        match a {
            0x00 => self.romen = v & 1 != 0,
            0x03 => self.led = v & 7,
            0x10..=0x3F | 0xC0..=0xFF => self.video.write(a, v),
            0x40..=0x43 => self.kbd.write(a, v),
            0x50..=0x51 => self.sound.write(a, v),
            0x70..=0x73 => self.uart.write(a, v),
            0x88..=0x8F => self.flash.write(a, v),
            _ => {}
        }
    }
}

impl Bus for MachineBus {
    fn read(&mut self, addr: u16) -> u8 {
        if addr & 0xFF00 == 0xFE00 {
            return self.io_read(addr as u8);
        }
        if self.romen && addr & 0xF000 == 0xF000 {
            return self.rom[(addr & 0x0FFF) as usize];
        }
        self.mem[addr as usize]
    }

    fn write(&mut self, addr: u16, value: u8) {
        if addr & 0xFF00 == 0xFE00 {
            self.io_write(addr as u8, value);
            return;
        }
        self.mem[addr as usize] = value;
    }
}

// ------------------------------------------------------------ the machine

pub struct Machine {
    pub cpu: Cpu,
    pub bus: MachineBus,
    pub line: u32,
    pub frames: u64,
    snd_owed: u64,
    tick_owed: u64,
    /// Display only, never CPU-visible: parity with cool8vm.Machine is
    /// untouched whether this is attached or not.
    pub renderer: Option<crate::render::Renderer>,
}

impl Machine {
    pub fn new(rom: [u8; 4096], flash_image: Option<Vec<u8>>) -> Machine {
        let mut m = Machine {
            cpu: Cpu::new(),
            bus: MachineBus {
                mem: vec![0u8; 0x10000].into_boxed_slice().try_into()
                    .unwrap(),
                rom,
                romen: true,
                led: 0,
                build_id: 0x05,
                uart: Uart::new(),
                kbd: Ps2::new(),
                sound: Sound::new(),
                video: Video::new(),
                flash: Flash::new(flash_image),
            },
            line: 0,
            frames: 0,
            snd_owed: 0,
            tick_owed: 0,
            renderer: None,
        };
        m.cpu.reset(&mut m.bus);
        m
    }

    fn irq(&self) -> bool {
        self.bus.video.irq() || self.bus.kbd.irq()
    }

    /// The bookkeeping that happens when a scanline finishes.
    fn end_line(&mut self) {
        self.snd_owed += CYCLES_PER_LINE;
        let n = self.snd_owed / SND_DIV;
        self.snd_owed %= SND_DIV;
        self.bus.sound.tick(n);

        self.line += 1;
        if self.line >= V_TOTAL {
            self.line = 0;
            self.frames += 1;
        }
        if self.line == 480 {
            // At the start of vertical blanking, as cool8_vga raises
            // frame_start — cool8vm.py's rule, corrected to the RTL's.
            self.bus.video.blink += 1;
            self.bus.video.irq_fl |= 0x02; // vblank
        }
        self.bus.video.raster = self.line;
        if self.line & 0xFF == self.bus.video.rcmp as u32 {
            self.bus.video.irq_fl |= 0x01; // raster compare
        }
        if self.bus.video.spr_en {
            self.bus.video.scan_sprites(self.line);
        }
        if let Some(r) = self.renderer.as_mut() {
            r.line_event(self.line, &self.bus);
        }
    }

    /// One instruction, with the raster and the interrupts kept in step
    /// with it — cool8vm.Machine.tick, minus the profiling hooks.
    pub fn tick(&mut self) {
        self.cpu.irq_line = self.irq();
        let before = self.cpu.cycles;
        self.cpu.step(&mut self.bus);
        self.tick_owed += self.cpu.cycles - before;
        while self.tick_owed >= CYCLES_PER_LINE {
            self.tick_owed -= CYCLES_PER_LINE;
            self.end_line();
        }
    }
}
