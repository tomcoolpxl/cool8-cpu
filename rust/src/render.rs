// The scanline renderer — modeled on the RTL, not on cool8vid.py.
//
// cool8vid.py draws a whole frame from the registers as they stand,
// because at CPython speed that is all a frame can afford; its own
// header names the consequence — a mid-frame register change is not
// visible in a rendered frame. This is the model the Python renderer
// could not afford: the display path of rtl/soc, done functionally,
// one scanline at a time, in step with the machine's own raster.
//
// What is modeled, and from which file:
//
//   cool8_fetch.v   the line buffer filled a source row ahead of the
//                   raster; `row_ptr` walking by stride from a base
//                   captured at frame start (not recomputed per line);
//                   the circular wrap for text and tile maps; text
//                   cells latched for sixteen lines; tile patterns
//                   flipped at fetch time; the two rows primed in
//                   vertical blanking; stride above 510 clamping at
//                   the buffer's 255 words
//   cool8_pixel.v   the extractor: the byte-swapped pixel stream, one
//                   shifter for every depth, tiles carrying their
//                   palette bank, the cursor styles, border outside
//                   the window
//   cool8_sprite.v  per-line evaluation: eight slots a line with
//                   trailing rows counting (the slot scan itself lives
//                   in the Machine, because the overrun flag is
//                   CPU-visible); descriptor-order priority; the
//                   shared palette bank; `behind` losing to a
//                   non-zero background
//
// So a raster split lands on the exact line the write preceded, a
// palette change mid-frame colours only the lines below it, and a
// VID_BASE change mid-frame behaves as the accumulator does in
// hardware — partially, which is the true behaviour.
//
// What is not modeled: fetch and sprite-render *bandwidth*. A line
// here always completes, where eight 16x16 sprites on the RTL run out
// of clocks (the render-overrun case). The slot rule and its overrun
// flag are modeled; the cycle budget is not.
//
// None of this is CPU-visible. The renderer hangs off the machine and
// reads it; it never writes anything the CPU can see, so machine
// parity (sim/rustsim.py) is untouched by its presence.

use crate::machine::MachineBus;

pub const H_VIS: usize = 640;
pub const V_VIS: usize = 480;

/// The derived viewport, as cool8_vregs derives it.
struct View {
    disp_en: bool,
    engine: u8,
    bpp_log: u8,
    hdouble: bool,
    vdouble: bool,
    hstart: u32,
    hactive: u32,
    vstart: u32,
    vactive: u32,
}

fn view(bus: &MachineBus) -> View {
    let v = &bus.video;
    let hdouble = v.ctrl & 0x10 != 0;
    let engine = v.ctrl & 3;
    let bpp_log = v.bpp_log();
    let hdisp: u32 = if hdouble { 320 } else { 640 };
    let img_w: u32 = if engine != 2 {
        hdisp
    } else {
        ((v.stride as u32) << 3) >> bpp_log
    };
    View {
        disp_en: v.mode & 0x80 != 0,
        engine,
        bpp_log,
        hdouble,
        vdouble: v.ctrl & 0x20 != 0,
        hstart: if img_w < hdisp { (hdisp - img_w) / 2 } else { 0 },
        hactive: img_w.min(hdisp),
        vstart: (480 - v.vactive as u32) / 2,
        vactive: v.vactive as u32,
    }
}

/// A VRAM word off the display port: word-aligned, little-endian.
fn vw(bus: &MachineBus, byte_addr: u16) -> u16 {
    let a = (byte_addr & 0xFFFE) as usize;
    bus.video.vram[a] as u16 | (bus.video.vram[(a + 1) & 0xFFFF] as u16) << 8
}

/// The pixel stream: pixels run left to right from the high nibble of
/// the low-addressed byte, so the stream is the word byte-swapped.
fn bswap(w: u16) -> u16 {
    w.rotate_left(8)
}

/// Reversing a pattern row is a nibble reversal of the whole word —
/// cool8_fetch's `revw`, applied at fetch time so the pixel stage
/// never sees a flip.
fn revw(w: u16) -> u16 {
    (w & 0x000F) << 12 | (w & 0x00F0) << 4 | (w & 0x0F00) >> 4 | (w >> 12)
}

pub struct Renderer {
    lb: [[u16; 256]; 2],   // the line buffer, raw words as fetched
    read_bank: usize,
    row_ptr: u16,          // walks by stride from the frame's base
    trow: u8,              // the row inside a tile
    primed: bool,          // vblank filled both banks; line 0 fetches nothing
    sline: [[u8; H_VIS]; 2], // sprites: {behind << 4 | pix}; 0 = nothing
    // The cursor the screen shows, latched at frame start as
    // cool8_vregs latches it: a mid-frame move cannot split the block.
    cur_x: u8,
    cur_y: u8,
    cur_lit: bool,
    pub font: [u8; 4096],
    pub fb: Vec<u16>,      // 12-bit palette colours, row-major
}

impl Renderer {
    pub fn new(font: [u8; 4096]) -> Renderer {
        Renderer {
            lb: [[0; 256]; 2],
            read_bank: 0,
            row_ptr: 0,
            trow: 0,
            primed: false,
            sline: [[0; H_VIS]; 2],
            cur_x: 0,
            cur_y: 0,
            cur_lit: false,
            font,
            fb: vec![0; H_VIS * V_VIS],
        }
    }

    /// Called by the machine at every line boundary, with the line the
    /// raster is entering. Line 480 is the start of vertical blanking —
    /// cool8_vga's `frame_start` — where the next frame's first two
    /// rows are primed and sprite line 0 is prepared.
    pub fn line_event(&mut self, line: u32, bus: &MachineBus) {
        let vv = view(bus);

        if line == 480 {
            // The cursor's screen state, atomically per frame.
            let v = &bus.video;
            let rate = (v.cur_ctrl >> 3) & 3;
            self.cur_x = v.cur_x;
            self.cur_y = v.cur_y;
            self.cur_lit = v.cur_ctrl & 1 != 0
                && (rate == 3 || v.blink & (1 << (3 + rate)) == 0);
            if vv.disp_en {
                self.row_ptr = bus.video.base;
                self.trow = (bus.video.scrl_y & 7) as u8;
                self.read_bank = 0;
                self.fill_row(0, &vv, bus);
                self.fill_row(1, &vv, bus);
                self.primed = true;
            }
            if bus.video.spr_en {
                self.sprite_line(0, bus);
            }
            return;
        }
        if line > 480 {
            return; // the rest of the blanking: nothing to draw or fetch
        }

        let vin = line >= vv.vstart && line - vv.vstart < vv.vactive;
        if vin {
            let vrel = line - vv.vstart;
            let was_primed = self.primed;
            self.primed = false; // the first active line consumes the flag

            let vsrc_t = vrel + (bus.video.scrl_y as u32 & 15);
            let row_edge = match vv.engine {
                0 => vsrc_t & 15 == 0,
                _ => !vv.vdouble || vrel & 1 == 0,
            };
            if row_edge && vv.disp_en {
                let disp_bank = match vv.engine {
                    0 => (vsrc_t >> 4) as usize & 1,
                    _ => {
                        let vlog = if vv.vdouble { vrel >> 1 } else { vrel };
                        vlog as usize & 1
                    }
                };
                self.read_bank = disp_bank;
                if !was_primed {
                    self.fill_row(disp_bank ^ 1, &vv, bus);
                }
            }
        }

        self.render_line(line, &vv, bus);
        if bus.video.spr_en && line < 479 {
            self.sprite_line(line + 1, bus);
        }
    }

    /// One source row into one bank — cool8_fetch's job, done at the
    /// row rather than the cycle. Registers are read now, which is
    /// within a line of when the hardware reads them.
    fn fill_row(&mut self, bank: usize, vv: &View, bus: &MachineBus) {
        let v = &bus.video;
        // The same wrap cool8_fetch.v does: within the map, whose
        // origin is its own register now rather than `base` rounded
        // down by a mask. That is what lifts the "aligned to its own
        // size" rule, and with it the power-of-two stride.
        let span = (v.stride << 5) as u16;
        let wrapped = |ptr: u16| -> u16 {
            let next = ptr.wrapping_add(v.stride);
            if next.wrapping_sub(v.map_org) >= span { next.wrapping_sub(span) }
            else { next }
        };
        match vv.engine {
            0 => {
                // text: cells out of main RAM — never through the ROM
                // overlay, which only the CPU sees
                let n = if vv.hdouble { 40 } else { 80 };
                for i in 0..n {
                    let a = self.row_ptr.wrapping_add(2 * i as u16);
                    self.lb[bank][i] = bus.mem[a as usize] as u16
                        | (bus.mem[a.wrapping_add(1) as usize] as u16) << 8;
                }
                self.row_ptr = wrapped(self.row_ptr);
            }
            1 => {
                // tile: one more than the screen shows, for the scroll
                let n = if vv.hdouble { 41 } else { 81 };
                for i in 0..n {
                    let ent = vw(bus, self.row_ptr.wrapping_add(2 * i as u16));
                    let trow_eff = if ent & 0x8000 != 0 {
                        !self.trow & 7
                    } else {
                        self.trow
                    };
                    let pat = v
                        .pat_base
                        .wrapping_add((ent >> 12 & 3) << 13)
                        .wrapping_add((ent & 0xFF) << 5)
                        .wrapping_add((trow_eff as u16) << 2);
                    let w0 = vw(bus, pat);
                    let w1 = vw(bus, pat.wrapping_add(2));
                    self.lb[bank][i * 3] = ent;
                    if ent & 0x4000 != 0 {
                        self.lb[bank][i * 3 + 1] = revw(w1);
                        self.lb[bank][i * 3 + 2] = revw(w0);
                    } else {
                        self.lb[bank][i * 3 + 1] = w0;
                        self.lb[bank][i * 3 + 2] = w1;
                    }
                }
                let advance = self.trow == 7;
                self.trow = (self.trow + 1) & 7;
                if advance {
                    self.row_ptr = wrapped(self.row_ptr);
                }
            }
            _ => {
                // bitmap: stride/2 words, clamped at the bank's 255 —
                // a longer pitch loses the end of every row, as the
                // hardware's does. No wrap: a frame buffer is not a
                // torus.
                let n = if v.stride >= 512 {
                    255
                } else {
                    (v.stride >> 1) as usize
                };
                for i in 0..n {
                    self.lb[bank][i] =
                        vw(bus, self.row_ptr.wrapping_add(2 * i as u16));
                }
                self.row_ptr = self.row_ptr.wrapping_add(v.stride);
            }
        }
    }

    /// One sprite line into the bank the raster will read — the render
    /// half of cool8_sprite. The slot cut, and the clock budget with
    /// it, come from the Machine's own sprite_plan, so what is *drawn*
    /// matches what the CPU-visible overrun flag counted: a line that
    /// runs out of clocks loses its last-rendered — lowest-numbered —
    /// sprites, exactly as the hardware does.
    fn sprite_line(&mut self, ln: u32, bus: &MachineBus) {
        let out = &mut self.sline[(ln & 1) as usize];
        out.fill(0);
        let (hits, n, lost, _) = bus.video.sprite_plan(ln);
        // The aborted tail of the render order is the *head* of the
        // ascending hit list, reals only.
        let mut skip = lost;
        for &(si, big, trail, dy) in &hits[..n] {
            if trail {
                continue; // writes zeros; a fresh buffer already is
            }
            if skip > 0 {
                skip -= 1;
                continue; // outrun by the next line: never drawn
            }
            let d = &bus.video.spr[si * 8..si * 8 + 8];
            let h: u32 = if big { 16 } else { 8 };

            let sx = (d[3] as u32 & 3) << 8 | d[2] as u32;
            let vflip = d[6] & 0x80 != 0;
            let hflip = d[6] & 0x40 != 0;
            let behind = d[6] & 0x20 != 0;
            let pat = ((d[5] as u16 & 7) << 8 | d[4] as u16) << 5;
            let row = if vflip { h - 1 - dy } else { dy };

            for cnt in 0..h {
                let w = vw(bus, pat
                    .wrapping_add((row * (h >> 1)) as u16)
                    .wrapping_add(((cnt >> 2) << 1) as u16));
                let pix = (bswap(w) >> (12 - (cnt & 3) * 4)) & 0xF;
                if pix == 0 {
                    continue; // colour zero is transparent
                }
                let px = (sx + if hflip { h - 1 - cnt } else { cnt }) & 0x3FF;
                // Descriptor order wins: first writer keeps the pixel,
                // which is the RTL's reversed last-writer-wins.
                if (px as usize) < H_VIS && out[px as usize] == 0 {
                    out[px as usize] = (if behind { 0x10 } else { 0 })
                        | pix as u8;
                }
            }
        }
    }

    /// The pixel stage for one line — cool8_pixel, functionally.
    fn render_line(&mut self, line: u32, vv: &View, bus: &MachineBus) {
        let v = &bus.video;
        let vrel = line.wrapping_sub(vv.vstart);
        let vborder = line < vv.vstart || vrel >= vv.vactive;
        let sline = &self.sline[(line & 1) as usize];
        let row = &mut self.fb[line as usize * H_VIS..][..H_VIS];

        for gx in 0..H_VIS {
            let xl = if vv.hdouble { gx as u32 >> 1 } else { gx as u32 };
            let blank = !vv.disp_en || vborder || xl < vv.hstart
                || xl - vv.hstart >= vv.hactive;

            let mut cell_of: u32 = 0;
            let mut trow_of: u32 = 0;
            let mut idx: u8 = if blank {
                v.border
            } else {
                let rel = xl - vv.hstart;
                // The cell this pixel is in, in every engine — the same
                // unconditional computation cool8_pixel.v makes. A cell
                // is 16 source lines, or 8 where the doubler is
                // stretching them, which is exactly the modes the
                // console gives CFROW 8.
                cell_of = rel >> 3;
                // One divisor: every mode's console row is 16 display
                // lines, so there is nothing to choose. cool8_pixel.v
                // makes the same unconditional computation.
                trow_of = vrel >> 4;
                match vv.engine {
                    0 => {
                        // ---- text
                        let vsrc = vrel + (v.scrl_y as u32 & 15);
                        let grow = vsrc & 15;
                        let cell = rel >> 3;
                        let w = self.lb[self.read_bank][cell as usize];
                        let attr = (w >> 8) as u8;
                        let fb = self.font
                            [(((w & 0xFF) << 4) | grow as u16) as usize];
                        let lit = fb & (1 << (7 - (rel & 7))) != 0;
                        if lit { attr & 0x0F } else { attr >> 4 }
                    }
                    1 => {
                        // ---- tile
                        let sx = rel + (v.scrl_x as u32 & 7);
                        let t = (sx >> 3) as usize;
                        let ent = self.lb[self.read_bank][t * 3];
                        let w = self.lb[self.read_bank]
                            [t * 3 + 1 + (sx as usize >> 2 & 1)];
                        let pix = (bswap(w) >> (12 - (sx & 3) * 4)) & 0xF;
                        ((ent >> 8) as u8 & 0x0F) << 4 | pix as u8
                    }
                    _ => {
                        // ---- bitmap
                        let bpp = 1u32 << vv.bpp_log;
                        let ppw = 16 / bpp;
                        let sx = rel + v.scrl_x as u32;
                        let w = self.lb[self.read_bank]
                            [(sx / ppw) as usize & 0xFF];
                        let ps = bswap(w) as u32;
                        (((ps << ((sx % ppw) * bpp)) >> (16 - bpp))
                            & ((1 << bpp) - 1)) as u8
                    }
                }
            };

            if !blank && v.spr_en {
                let s = sline[gx];
                if s & 0x0F != 0 && (s & 0x10 == 0 || idx == 0) {
                    idx = v.spr_bank << 4 | (s & 0x0F);
                }
            }
            // The cursor inverts the finished index, in every engine and
            // after the sprite has had its say — cool8_pixel.v does the
            // same XOR in the same place. It used to be a text-only
            // fiddle with `lit`, which is why the console carried a
            // second cursor for the other five modes.
            if !blank && self.cur_lit && cell_of == self.cur_x as u32
                && trow_of == self.cur_y as u32
            {
                idx ^= 0x0F;
            }
            row[gx] = v.pal[idx as usize] & 0x0FFF;
        }
    }
}
