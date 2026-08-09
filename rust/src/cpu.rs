// COOL8 CPU core — a hand port of tools/cool8emu.py, the executable
// specification. This copy is never authoritative: when the two
// disagree, this one is wrong. sim/rustsim.py diffs the two per retired
// instruction, whole-memory compare included — the same contract the
// RTL is held to by sim/cosim.py.
//
// Cycle costs and the page-2 assigned/reserved split come only from the
// generated optab.rs; nothing here restates a table. Semantics are the
// hand-written part, and the trace diff is what polices them.

use crate::optab;

pub const RESET_VEC: u16 = 0xFFF8;
pub const NMI_VEC: u16 = 0xFFFA;
pub const IRQ_VEC: u16 = 0xFFFC;
pub const BRK_VEC: u16 = 0xFFFE;

// ALU operation indices, matching the `ooo` field.
const MOV: u8 = 0;
const ADD: u8 = 1;
const ADC: u8 = 2;
const SUB: u8 = 3;
const SBC: u8 = 4;
const AND: u8 = 5;
const OR: u8 = 6;
const CMP: u8 = 7;

pub struct Cpu {
    pub mem: Box<[u8; 0x10000]>,
    pub r: [u8; 4],
    pub x: u16,
    pub y: u16,
    pub sp: u16,
    pub pc: u16,
    pub c: bool,
    pub z: bool,
    pub n: bool,
    pub v: bool,
    pub i: bool,
    pub cycles: u64,
    pub instructions: u64,
    pub halted: bool,
    pub irq_line: bool, // level sensitive
    pub nmi_edge: bool, // set by pulse_nmi()
}

impl Cpu {
    pub fn new() -> Cpu {
        Cpu {
            mem: vec![0u8; 0x10000].into_boxed_slice().try_into().unwrap(),
            r: [0; 4],
            x: 0,
            y: 0,
            sp: 0,
            pc: 0,
            c: false,
            z: false,
            n: false,
            v: false,
            i: false,
            cycles: 0,
            instructions: 0,
            halted: false,
            irq_line: false,
            nmi_edge: false,
        }
    }

    pub fn reset(&mut self) {
        self.r = [0; 4];
        self.x = 0;
        self.y = 0;
        self.sp = 0xFFF8; // first push lands at $FFF7, below vectors
        self.c = false;
        self.z = false;
        self.n = false;
        self.v = false;
        self.i = false;
        self.pc = self.read16(RESET_VEC);
        self.cycles = 0;
        self.instructions = 0;
        self.halted = false;
        self.irq_line = false;
        self.nmi_edge = false;
    }

    pub fn f(&self) -> u8 {
        (self.c as u8)
            | (self.z as u8) << 1
            | (self.n as u8) << 2
            | (self.v as u8) << 3
            | (self.i as u8) << 4
    }

    fn set_f(&mut self, v: u8) {
        self.c = v & 1 != 0;
        self.z = v & 2 != 0;
        self.n = v & 4 != 0;
        self.v = v & 8 != 0;
        self.i = v & 16 != 0;
    }

    pub fn pulse_nmi(&mut self) {
        self.nmi_edge = true;
    }

    // ------------------------------------------------------ primitives

    fn read(&self, addr: u16) -> u8 {
        self.mem[addr as usize]
    }

    fn write(&mut self, addr: u16, value: u8) {
        self.mem[addr as usize] = value;
    }

    fn read16(&self, addr: u16) -> u16 {
        self.read(addr) as u16 | (self.read(addr.wrapping_add(1)) as u16) << 8
    }

    fn fetch(&mut self) -> u8 {
        let b = self.read(self.pc);
        self.pc = self.pc.wrapping_add(1);
        b
    }

    fn fetch16(&mut self) -> u16 {
        let lo = self.fetch() as u16;
        lo | (self.fetch() as u16) << 8
    }

    fn push(&mut self, v: u8) {
        self.sp = self.sp.wrapping_sub(1);
        self.write(self.sp, v);
    }

    fn pop(&mut self) -> u8 {
        let v = self.read(self.sp);
        self.sp = self.sp.wrapping_add(1);
        v
    }

    fn push16(&mut self, v: u16) {
        self.push((v >> 8) as u8); // high first, so low ends up lower
        self.push(v as u8);
    }

    fn pop16(&mut self) -> u16 {
        let lo = self.pop() as u16;
        lo | (self.pop() as u16) << 8
    }

    fn nz(&mut self, v: u8) {
        self.z = v == 0;
        self.n = v & 0x80 != 0;
    }

    // ------------------------------------------------------------- ALU

    /// The hardware adder. Subtraction feeds it !b and cin=1, which is
    /// why C comes out as "no borrow" for free.
    fn addcore(a: u8, b: u8, cin: bool) -> (u8, bool, bool) {
        let wide = a as u16 + b as u16 + cin as u16;
        let r = wide as u8;
        let c = wide > 0xFF;
        let v = !(a ^ b) & (a ^ r) & 0x80 != 0;
        (r, c, v)
    }

    /// Returns the result, or None when the operation writes nothing.
    /// Flag effects follow docs/02-isa.md section 1.2.
    fn alu(&mut self, op: u8, a: u8, b: u8) -> Option<u8> {
        match op {
            MOV => Some(b), // no flags at all
            ADD | ADC => {
                let cin = if op == ADC { self.c } else { false };
                let (r, c, v) = Cpu::addcore(a, b, cin);
                self.c = c;
                self.v = v;
                self.nz(r);
                Some(r)
            }
            SUB | SBC | CMP => {
                let cin = if op == SBC { self.c } else { true };
                let (r, c, v) = Cpu::addcore(a, b ^ 0xFF, cin);
                self.c = c;
                self.v = v;
                self.nz(r);
                if op == CMP { None } else { Some(r) }
            }
            AND | OR => {
                let r = if op == AND { a & b } else { a | b };
                self.nz(r); // C and V untouched
                Some(r)
            }
            _ => unreachable!("ooo is a 3-bit field"),
        }
    }

    fn cond(&self, c: u8) -> bool {
        match c {
            0 => true,  // BRA
            1 => false, // BNV, reserved
            2 => self.z,
            3 => !self.z,
            4 => self.c,
            5 => !self.c,
            6 => self.n,
            7 => !self.n,
            8 => self.v,
            9 => !self.v,
            10 => self.c && !self.z,
            11 => !self.c || self.z,
            12 => self.n == self.v,
            13 => self.n != self.v,
            14 => !self.z && self.n == self.v,
            _ => self.z || self.n != self.v,
        }
    }

    // ------------------------------------------------------ interrupts

    /// Control transfer only — the cycle cost is the caller's, so the
    /// generated table stays the single statement of every cost.
    fn enter(&mut self, vector: u16) {
        let pc = self.pc;
        self.push16(pc);
        let f = self.f();
        self.push(f);
        self.i = false;
        self.pc = self.read16(vector);
        self.halted = false;
    }

    fn service_interrupts(&mut self) -> bool {
        if self.nmi_edge {
            self.nmi_edge = false;
            self.enter(NMI_VEC);
            self.cycles += optab::INTERRUPT_CYCLES;
            return true;
        }
        if self.irq_line && self.i {
            self.enter(IRQ_VEC);
            self.cycles += optab::INTERRUPT_CYCLES;
            return true;
        }
        false
    }

    // ------------------------------------------------------------ step

    /// Execute one instruction, exactly as cool8emu.Cool8.step does:
    /// a serviced interrupt and a halted tick are not retired.
    pub fn step(&mut self) {
        if self.service_interrupts() {
            return;
        }
        if self.halted {
            self.cycles += 1;
            return;
        }

        let op = self.fetch();
        match op {
            0x00..=0x1F => self.alu_imm(op),
            0x20..=0x2F => self.control(op),
            0x30..=0x37 => self.pushpop(op),
            0x38..=0x3F => self.ptr_quick(op),
            0x40..=0x4F => self.ldst_ptr(op),
            0x50..=0x5F => self.ldst_ptr_disp(op),
            0x60..=0x6F => self.ldst_sp_abs(op),
            0x70..=0x7F => self.branch(op),
            _ => self.alu_reg(op),
        }
        self.instructions += 1;
    }

    // ---------------------------------------------------- instructions

    fn alu_imm(&mut self, op: u8) {
        // $00-$1F
        let (ooo, dd) = ((op >> 2) & 7, (op & 3) as usize);
        let a = self.r[dd];
        let b = self.fetch();
        if let Some(r) = self.alu(ooo, a, b) {
            self.r[dd] = r;
        }
        self.cycles += optab::CYCLES[op as usize] as u64;
    }

    fn alu_reg(&mut self, op: u8) {
        // $80-$FF
        let (ooo, dd, ss) = ((op >> 4) & 7, ((op >> 2) & 3) as usize,
                            (op & 3) as usize);
        let (a, b) = (self.r[dd], self.r[ss]);
        if let Some(r) = self.alu(ooo, a, b) {
            self.r[dd] = r;
        }
        self.cycles += optab::CYCLES[op as usize] as u64;
    }

    fn pushpop(&mut self, op: u8) {
        // $30-$37
        let dd = (op & 3) as usize;
        if op & 4 != 0 {
            let v = self.pop();
            self.r[dd] = v;
            self.nz(v); // POP sets Z/N
        } else {
            self.push(self.r[dd]); // PUSH sets nothing
        }
        self.cycles += optab::CYCLES[op as usize] as u64;
    }

    fn ptr_quick(&mut self, op: u8) {
        // $38-$3F
        let which = op & 7;
        if which < 4 {
            let delta: u16 = if which < 2 { 1 } else { 0xFFFF };
            if which & 1 != 0 {
                self.y = self.y.wrapping_add(delta);
                self.z = self.y == 0;
            } else {
                self.x = self.x.wrapping_add(delta);
                self.z = self.x == 0;
            }
        } else if which < 6 {
            let v = if which & 1 != 0 { self.y } else { self.x };
            self.push16(v);
        } else {
            let v = self.pop16();
            if which & 1 != 0 {
                self.y = v;
            } else {
                self.x = v;
            }
        }
        self.cycles += optab::CYCLES[op as usize] as u64;
    }

    fn ldst_ptr(&mut self, op: u8) {
        // $40-$4F
        let dd = ((op >> 1) & 3) as usize;
        let ptr = if op & 1 != 0 { self.y } else { self.x };
        self.memop(op & 8 != 0, dd, ptr);
        self.cycles += optab::CYCLES[op as usize] as u64;
    }

    fn ldst_ptr_disp(&mut self, op: u8) {
        // $50-$5F
        let d = self.fetch() as i8; // signed
        let base = if op & 1 != 0 { self.y } else { self.x };
        let ea = base.wrapping_add(d as u16);
        self.memop(op & 8 != 0, ((op >> 1) & 3) as usize, ea);
        self.cycles += optab::CYCLES[op as usize] as u64;
    }

    fn ldst_sp_abs(&mut self, op: u8) {
        // $60-$6F
        let ea = if op & 1 != 0 {
            self.fetch16() // absolute
        } else {
            let u = self.fetch() as u16;
            self.sp.wrapping_add(u) // SP + unsigned
        };
        self.memop(op & 8 != 0, ((op >> 1) & 3) as usize, ea);
        self.cycles += optab::CYCLES[op as usize] as u64;
    }

    fn memop(&mut self, is_store: bool, dd: usize, ea: u16) {
        if is_store {
            self.write(ea, self.r[dd]); // stores set nothing
        } else {
            let v = self.read(ea);
            self.r[dd] = v;
            self.nz(v); // loads set Z/N
        }
    }

    fn branch(&mut self, op: u8) {
        // $70-$7F
        let d = self.fetch() as i8;
        if self.cond(op & 15) {
            self.pc = self.pc.wrapping_add(d as u16); // relative to next
            self.cycles += optab::CYCLES_TAKEN[op as usize] as u64;
        } else {
            self.cycles += optab::CYCLES[op as usize] as u64;
        }
    }

    fn control(&mut self, op: u8) {
        // $20-$2F
        match op {
            0x20 => {} // NOP
            0x21 => self.halted = true,
            0x22 => self.pc = self.pop16(),
            0x23 => {
                let f = self.pop();
                self.set_f(f);
                self.pc = self.pop16();
            }
            0x24 => self.i = true,
            0x25 => self.i = false,
            0x26 => self.c = false,
            0x27 => self.c = true,
            0x28 => self.pc = self.fetch16(),
            0x29 => {
                let t = self.fetch16();
                let pc = self.pc;
                self.push16(pc);
                self.pc = t;
            }
            0x2A | 0x2B => {
                self.pc = if op & 1 != 0 { self.y } else { self.x };
            }
            0x2C | 0x2D => {
                let t = if op & 1 != 0 { self.y } else { self.x };
                let pc = self.pc;
                self.push16(pc);
                self.pc = t;
            }
            0x2E => self.enter(BRK_VEC), // BRK; cost is in the table
            _ => {
                self.page2();
                return; // page 2 accounts for its own cost
            }
        }
        self.cycles += optab::CYCLES[op as usize] as u64;
    }

    // ---------------------------------------------------------- page 2

    fn page2(&mut self) {
        let op = self.fetch();
        self.cycles += optab::P2_CYCLES[op as usize] as u64;

        if !optab::P2_ASSIGNED[op as usize] {
            self.enter(BRK_VEC); // reserved -> trap
            return;
        }

        let (dd, ss) = (((op >> 2) & 3) as usize, (op & 3) as usize);

        match op {
            0x00..=0x0F => {
                // XOR Rd,Rs
                self.r[dd] ^= self.r[ss];
                let v = self.r[dd];
                self.nz(v);
            }
            0x2C | 0x2D => {
                // ADDW X|Y,#imm16
                let v = self.fetch16();
                if op & 1 != 0 {
                    self.y = self.y.wrapping_add(v); // sets no flags
                } else {
                    self.x = self.x.wrapping_add(v);
                }
            }
            0x10..=0x3F => self.unary(op),
            0x40..=0x4F => {
                // MOV Rd,<half> — a MOV: no flags
                self.r[dd] = self.half(op & 3);
            }
            0x50..=0x5F => {
                // MOV <half>,Rs
                let v = self.r[dd];
                self.set_half(op & 3, v);
            }
            0x60..=0x6F => self.wide(op),
            0x70..=0x7F => {
                // ADDW/SUBW X|Y,Rd — sets no flags
                let which = (op >> 2) & 3;
                let d = self.r[ss] as u16;
                let delta = if which < 2 { d } else { d.wrapping_neg() };
                if which & 1 != 0 {
                    self.y = self.y.wrapping_add(delta);
                } else {
                    self.x = self.x.wrapping_add(delta);
                }
            }
            0x80..=0xBF => {
                // [X|Y + Rs]
                let base = if (op >> 4) & 1 != 0 { self.y } else { self.x };
                let ea = base.wrapping_add(self.r[ss] as u16);
                self.memop(op >= 0xA0, dd, ea);
            }
            0xC0..=0xDF => self.autoinc(op),
            0xE0 => {
                let f = self.f();
                self.push(f);
            }
            0xE1 => {
                let f = self.pop();
                self.set_f(f);
            }
            0xE2 => self.v = false,
            _ => {
                // $F0-$FF MUL: X <- Rd * Rs, unsigned
                let p = self.r[dd] as u16 * self.r[ss] as u16;
                self.x = p;
                self.z = p == 0;
                self.n = p & 0x8000 != 0;
                self.c = false;
                self.v = false;
            }
        }
    }

    fn unary(&mut self, op: u8) {
        let group = (op - 0x10) >> 2;
        let dd = (op & 3) as usize;
        let a = self.r[dd];
        match group {
            0 => {
                // XOR Rd,#imm8
                let b = self.fetch();
                self.r[dd] = a ^ b;
                let v = self.r[dd];
                self.nz(v);
            }
            1 => {
                // NOT
                self.r[dd] = a ^ 0xFF;
                let v = self.r[dd];
                self.nz(v);
            }
            2 => {
                // NEG, a subtraction
                let (r, c, v) = Cpu::addcore(0, a ^ 0xFF, true);
                self.r[dd] = r;
                self.c = c;
                self.v = v;
                self.nz(r);
            }
            3 => {
                // SWAP nibbles
                let r = (a << 4) | (a >> 4);
                self.r[dd] = r;
                self.nz(r);
            }
            4 => {
                // SHR logical
                self.c = a & 1 != 0;
                let r = a >> 1;
                self.r[dd] = r;
                self.nz(r);
            }
            5 => {
                // SAR arithmetic
                self.c = a & 1 != 0;
                let r = (a >> 1) | (a & 0x80);
                self.r[dd] = r;
                self.nz(r);
            }
            6 => {
                // ROR through carry
                let cin = if self.c { 0x80 } else { 0 };
                self.c = a & 1 != 0;
                let r = (a >> 1) | cin;
                self.r[dd] = r;
                self.nz(r);
            }
            _ => {
                // 8, 9, 10: bit ops with a mask byte
                let mask = self.fetch();
                if group == 8 {
                    let r = a | mask;
                    self.r[dd] = r;
                    self.nz(r);
                } else if group == 9 {
                    let r = a & !mask;
                    self.r[dd] = r;
                    self.nz(r);
                } else {
                    self.nz(a & mask); // BTST, no writeback
                }
            }
        }
    }

    fn half(&self, pp: u8) -> u8 {
        match pp {
            0 => self.x as u8,
            1 => (self.x >> 8) as u8,
            2 => self.y as u8,
            _ => (self.y >> 8) as u8,
        }
    }

    fn set_half(&mut self, pp: u8, v: u8) {
        match pp {
            0 => self.x = (self.x & 0xFF00) | v as u16,
            1 => self.x = (self.x & 0x00FF) | (v as u16) << 8,
            2 => self.y = (self.y & 0xFF00) | v as u16,
            _ => self.y = (self.y & 0x00FF) | (v as u16) << 8,
        }
    }

    fn wide(&mut self, op: u8) {
        match op {
            0x60 | 0x61 => {
                let v = self.fetch16();
                if op & 1 != 0 { self.y = v } else { self.x = v }
            }
            0x62 | 0x63 => {
                let a = self.fetch16();
                let v = self.read16(a);
                if op & 1 != 0 { self.y = v } else { self.x = v }
            }
            0x64 | 0x65 => {
                let a = self.fetch16();
                let v = if op & 1 != 0 { self.y } else { self.x };
                self.write(a, v as u8);
                self.write(a.wrapping_add(1), (v >> 8) as u8);
            }
            0x66 => self.x = self.y,
            0x67 => self.y = self.x,
            0x68 => self.sp = self.x,
            0x69 => self.sp = self.y,
            0x6A => self.x = self.sp,
            0x6B => self.y = self.sp,
            0x6C => {
                // ADDW SP,#d8 signed
                let d = self.fetch() as i8;
                self.sp = self.sp.wrapping_add(d as u16);
            }
            _ => {
                // LEA X|Y,[SP+u8]
                let u = self.fetch() as u16;
                let v = self.sp.wrapping_add(u);
                if op == 0x6D { self.x = v } else { self.y = v }
            }
        }
    }

    fn autoinc(&mut self, op: u8) {
        let pre = op & 0x10 != 0;
        let dd = ((op >> 1) & 3) as usize;
        let use_y = op & 1 != 0;
        let mut ptr = if use_y { self.y } else { self.x };
        if pre {
            ptr = ptr.wrapping_sub(1);
        }
        self.memop(op & 8 != 0, dd, ptr);
        if !pre {
            ptr = ptr.wrapping_add(1);
        }
        if use_y {
            self.y = ptr;
        } else {
            self.x = ptr;
        }
    }
}
