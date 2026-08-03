#!/usr/bin/env python3
"""COOL8 reference emulator — the executable specification.

Written from docs/02-isa.md before any RTL exists. When the RTL and this
model disagree, one of them is wrong and the document decides which.

Instruction semantics are decoded here from bit fields, deliberately
*independently* of tools/opcodes.py, which is used only for disassembly
and instruction length. A disagreement between the two is therefore a
real signal rather than a shared mistake; --selftest checks them against
each other.

    python tools/cool8emu.py --selftest
    python tools/cool8emu.py prog.bin --at 0x0400 --trace
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opcodes  # noqa: E402

# ALU operation indices, matching the `ooo` field
MOV, ADD, ADC, SUB, SBC, AND, OR, CMP = range(8)

RESET_VEC, NMI_VEC, IRQ_VEC, BRK_VEC = 0xFFF8, 0xFFFA, 0xFFFC, 0xFFFE


class Bus:
    """64 KB of RAM with optional I/O hooks in the $FE00-$FEFF page."""

    def __init__(self, size=0x10000):
        self.mem = bytearray(size)
        self.read_hooks = {}
        self.write_hooks = {}

    def read(self, addr):
        addr &= 0xFFFF
        h = self.read_hooks.get(addr)
        return h() & 0xFF if h else self.mem[addr]

    def write(self, addr, value):
        addr &= 0xFFFF
        value &= 0xFF
        h = self.write_hooks.get(addr)
        if h:
            h(value)
        else:
            self.mem[addr] = value

    def load(self, addr, data):
        self.mem[addr:addr + len(data)] = data

    def read16(self, addr):
        return self.read(addr) | (self.read(addr + 1) << 8)

    def write16(self, addr, value):
        self.write(addr, value & 0xFF)
        self.write(addr + 1, (value >> 8) & 0xFF)


class Trap(Exception):
    """Raised by the harness, not by the CPU. See Cool8.on_halt."""


class Cool8:
    def __init__(self, bus=None):
        self.bus = bus or Bus()
        self.reset()

    # ---------------------------------------------------------- state

    def reset(self):
        self.r = [0, 0, 0, 0]
        self.x = 0
        self.y = 0
        self.sp = 0xFFF8          # first push lands at $FFF7, below vectors
        self.C = self.Z = self.N = self.V = self.I = False
        self.pc = self.bus.read16(RESET_VEC)
        self.cycles = 0
        self.instructions = 0
        self.halted = False
        self.irq_line = False     # level sensitive
        self.nmi_edge = False     # set by pulse_nmi()

    @property
    def f(self):
        return ((self.C << 0) | (self.Z << 1) | (self.N << 2) |
                (self.V << 3) | (self.I << 4))

    @f.setter
    def f(self, v):
        self.C = bool(v & 1)
        self.Z = bool(v & 2)
        self.N = bool(v & 4)
        self.V = bool(v & 8)
        self.I = bool(v & 16)

    def pulse_nmi(self):
        self.nmi_edge = True

    # ------------------------------------------------------- primitives

    def _fetch(self):
        b = self.bus.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return b

    def _fetch16(self):
        lo = self._fetch()
        return lo | (self._fetch() << 8)

    def _push(self, v):
        self.sp = (self.sp - 1) & 0xFFFF
        self.bus.write(self.sp, v)

    def _pop(self):
        v = self.bus.read(self.sp)
        self.sp = (self.sp + 1) & 0xFFFF
        return v

    def _push16(self, v):
        self._push((v >> 8) & 0xFF)   # high first, so low ends up lower
        self._push(v & 0xFF)

    def _pop16(self):
        lo = self._pop()
        return lo | (self._pop() << 8)

    def _nz(self, v):
        self.Z = v == 0
        self.N = bool(v & 0x80)

    # -------------------------------------------------------------- ALU

    @staticmethod
    def _addcore(a, b, cin):
        """The hardware adder. Subtraction feeds it ~b and cin=1, which
        is why C comes out as 'no borrow' for free."""
        r = a + b + cin
        c = r > 0xFF
        r &= 0xFF
        v = bool(~(a ^ b) & (a ^ r) & 0x80)
        return r, c, v

    def alu(self, op, a, b):
        """Returns the result, or None when the operation writes nothing.
        Flag effects follow docs/02-isa.md section 1.2."""
        if op == MOV:
            return b                                    # no flags at all
        if op in (ADD, ADC):
            r, c, v = self._addcore(a, b, self.C if op == ADC else 0)
            self.C, self.V = c, v
            self._nz(r)
            return r
        if op in (SUB, SBC, CMP):
            cin = self.C if op == SBC else 1
            r, c, v = self._addcore(a, b ^ 0xFF, cin)
            self.C, self.V = c, v
            self._nz(r)
            return None if op == CMP else r
        r = (a & b) if op == AND else (a | b)
        self._nz(r)                                     # C and V untouched
        return r

    # ------------------------------------------------------- conditions

    def cond(self, c):
        if c == 0:
            return True                                 # BRA
        if c == 1:
            return False                                # BNV, reserved
        if c == 2:
            return self.Z
        if c == 3:
            return not self.Z
        if c == 4:
            return self.C
        if c == 5:
            return not self.C
        if c == 6:
            return self.N
        if c == 7:
            return not self.N
        if c == 8:
            return self.V
        if c == 9:
            return not self.V
        if c == 10:
            return self.C and not self.Z
        if c == 11:
            return (not self.C) or self.Z
        if c == 12:
            return self.N == self.V
        if c == 13:
            return self.N != self.V
        if c == 14:
            return (not self.Z) and self.N == self.V
        return self.Z or self.N != self.V

    # ------------------------------------------------------- interrupts

    def _enter(self, vector):
        self._push16(self.pc)
        self._push(self.f)
        self.I = False
        self.pc = self.bus.read16(vector)
        self.cycles += 7
        self.halted = False

    def _service_interrupts(self):
        if self.nmi_edge:
            self.nmi_edge = False
            self._enter(NMI_VEC)
            return True
        if self.irq_line and self.I:
            self._enter(IRQ_VEC)
            return True
        return False

    # ------------------------------------------------------------ step

    def step(self):
        """Execute one instruction. Returns the cycles it consumed."""
        if self._service_interrupts():
            return 7
        if self.halted:
            self.cycles += 1
            return 1

        start = self.cycles
        op = self._fetch()

        if op < 0x20:
            self._alu_imm(op)
        elif op < 0x30:
            self._control(op)
        elif op < 0x38:
            self._pushpop(op)
        elif op < 0x40:
            self._ptr_quick(op)
        elif op < 0x50:
            self._ldst_ptr(op)
        elif op < 0x60:
            self._ldst_ptr_disp(op)
        elif op < 0x70:
            self._ldst_sp_abs(op)
        elif op < 0x80:
            self._branch(op)
        else:
            self._alu_reg(op)

        self.instructions += 1
        return self.cycles - start

    # ----------------------------------------------------- instructions

    def _alu_imm(self, op):                             # $00-$1F
        ooo, dd = (op >> 2) & 7, op & 3
        r = self.alu(ooo, self.r[dd], self._fetch())
        if r is not None:
            self.r[dd] = r
        self.cycles += 3

    def _alu_reg(self, op):                             # $80-$FF
        ooo, dd, ss = (op >> 4) & 7, (op >> 2) & 3, op & 3
        r = self.alu(ooo, self.r[dd], self.r[ss])
        if r is not None:
            self.r[dd] = r
        self.cycles += 2

    def _pushpop(self, op):                             # $30-$37
        dd = op & 3
        if op & 4:
            self.r[dd] = self._pop()
            self._nz(self.r[dd])                        # POP sets Z/N
        else:
            self._push(self.r[dd])                      # PUSH sets nothing
        self.cycles += 3

    def _ptr_quick(self, op):                           # $38-$3F
        which = op & 7
        if which < 4:
            delta = 1 if which < 2 else -1
            if which & 1:
                self.y = (self.y + delta) & 0xFFFF
                self.Z = self.y == 0
            else:
                self.x = (self.x + delta) & 0xFFFF
                self.Z = self.x == 0
            self.cycles += 2
        else:
            if which < 6:
                self._push16(self.y if which & 1 else self.x)
            else:
                v = self._pop16()
                if which & 1:
                    self.y = v
                else:
                    self.x = v
            self.cycles += 4

    def _ldst_ptr(self, op):                            # $40-$4F
        dd, ptr = (op >> 1) & 3, (self.y if op & 1 else self.x)
        self._memop(op & 8, dd, ptr)
        self.cycles += 3

    def _ldst_ptr_disp(self, op):                       # $50-$5F
        d = self._fetch()
        d = d - 256 if d > 127 else d                   # signed
        base = self.y if op & 1 else self.x
        self._memop(op & 8, (op >> 1) & 3, (base + d) & 0xFFFF)
        self.cycles += 5

    def _ldst_sp_abs(self, op):                         # $60-$6F
        if op & 1:
            ea = self._fetch16()                        # absolute
        else:
            ea = (self.sp + self._fetch()) & 0xFFFF     # SP + unsigned
        self._memop(op & 8, (op >> 1) & 3, ea)
        self.cycles += 5

    def _memop(self, is_store, dd, ea):
        if is_store:
            self.bus.write(ea, self.r[dd])              # stores set nothing
        else:
            self.r[dd] = self.bus.read(ea)
            self._nz(self.r[dd])                        # loads set Z/N

    def _branch(self, op):                              # $70-$7F
        d = self._fetch()
        d = d - 256 if d > 127 else d
        if self.cond(op & 15):
            self.pc = (self.pc + d) & 0xFFFF            # relative to next
            self.cycles += 4
        else:
            self.cycles += 3

    def _control(self, op):                             # $20-$2F
        if op == 0x20:
            self.cycles += 2
        elif op == 0x21:
            self.halted = True
            self.cycles += 2
            self.on_halt()
        elif op == 0x22:
            self.pc = self._pop16()
            self.cycles += 5
        elif op == 0x23:
            self.f = self._pop()
            self.pc = self._pop16()
            self.cycles += 6
        elif op == 0x24:
            self.I = True
            self.cycles += 2
        elif op == 0x25:
            self.I = False
            self.cycles += 2
        elif op == 0x26:
            self.C = False
            self.cycles += 2
        elif op == 0x27:
            self.C = True
            self.cycles += 2
        elif op == 0x28:
            self.pc = self._fetch16()
            self.cycles += 4
        elif op == 0x29:
            t = self._fetch16()
            self._push16(self.pc)
            self.pc = t
            self.cycles += 7
        elif op in (0x2A, 0x2B):
            self.pc = self.y if op & 1 else self.x
            self.cycles += 2
        elif op in (0x2C, 0x2D):
            t = self.y if op & 1 else self.x
            self._push16(self.pc)
            self.pc = t
            self.cycles += 5
        elif op == 0x2E:
            self._enter(BRK_VEC)
        else:
            self._page2()

    # ----------------------------------------------------------- page 2

    def _page2(self):
        op = self._fetch()
        self.cycles += 1

        if op not in opcodes.page2:                     # reserved -> trap
            self._enter(BRK_VEC)
            return

        dd, ss = (op >> 2) & 3, op & 3

        if op < 0x10:                                   # XOR Rd,Rs
            self.r[dd] ^= self.r[ss]
            self._nz(self.r[dd])
            self.cycles += 2
        elif op in (0x2C, 0x2D):                        # ADDW X|Y,#imm16
            v = self._fetch16()
            if op & 1:
                self.y = (self.y + v) & 0xFFFF          # sets no flags
            else:
                self.x = (self.x + v) & 0xFFFF
            self.cycles += 5
        elif op < 0x40:
            self._unary(op)
        elif op < 0x50:                                 # MOV Rd,<half>
            self.r[dd] = self._half(op & 3)
            self._nz(self.r[dd])
            self.cycles += 2
        elif op < 0x60:                                 # MOV <half>,Rs
            self._set_half(op & 3, self.r[(op >> 2) & 3])
            self.cycles += 2
        elif op < 0x70:
            self._wide(op)
        elif op < 0x80:                                 # ADDW/SUBW X|Y,Rd
            which, d = (op >> 2) & 3, self.r[op & 3]
            delta = d if which < 2 else -d
            if which & 1:
                self.y = (self.y + delta) & 0xFFFF      # sets no flags
            else:
                self.x = (self.x + delta) & 0xFFFF
            self.cycles += 3
        elif op < 0xC0:                                 # [X|Y + Rs]
            base = self.y if (op >> 4) & 1 else self.x
            self._memop(op >= 0xA0, dd, (base + self.r[ss]) & 0xFFFF)
            self.cycles += 4
        elif op < 0xE0:                                 # auto inc / dec
            self._autoinc(op)
        elif op == 0xE0:
            self._push(self.f)
            self.cycles += 3
        elif op == 0xE1:
            self.f = self._pop()
            self.cycles += 3
        elif op == 0xE2:
            self.V = False
            self.cycles += 2
        else:                                           # $F0-$FF MUL
            p = self.r[dd] * self.r[ss]
            self.x = p & 0xFFFF
            self.Z = self.x == 0
            self.N = bool(self.x & 0x8000)
            self.C = self.V = False
            self.cycles += 12

    def _unary(self, op):
        group, dd = (op - 0x10) >> 2, op & 3
        a = self.r[dd]
        if group == 0:                                  # XOR Rd,#imm8
            self.r[dd] = a ^ self._fetch()
            self._nz(self.r[dd])
            self.cycles += 3
            return
        if group == 1:                                  # NOT
            self.r[dd] = a ^ 0xFF
            self._nz(self.r[dd])
        elif group == 2:                                # NEG, a subtraction
            r, c, v = self._addcore(0, a ^ 0xFF, 1)
            self.r[dd], self.C, self.V = r, c, v
            self._nz(r)
        elif group == 3:                                # SWAP nibbles
            self.r[dd] = ((a << 4) | (a >> 4)) & 0xFF
            self._nz(self.r[dd])
        elif group == 4:                                # SHR logical
            self.C = bool(a & 1)
            self.r[dd] = a >> 1
            self._nz(self.r[dd])
        elif group == 5:                                # SAR arithmetic
            self.C = bool(a & 1)
            self.r[dd] = (a >> 1) | (a & 0x80)
            self._nz(self.r[dd])
        elif group == 6:                                # ROR through carry
            cin = 0x80 if self.C else 0
            self.C = bool(a & 1)
            self.r[dd] = (a >> 1) | cin
            self._nz(self.r[dd])
        else:                                           # 8,9,10: bit ops
            mask = self._fetch()
            if group == 8:
                self.r[dd] = a | mask
                self._nz(self.r[dd])
            elif group == 9:
                self.r[dd] = a & (mask ^ 0xFF)
                self._nz(self.r[dd])
            else:
                self._nz(a & mask)                      # BTST, no writeback
            self.cycles += 3
            return
        self.cycles += 2

    def _half(self, pp):
        return [self.x & 0xFF, self.x >> 8,
                self.y & 0xFF, self.y >> 8][pp]

    def _set_half(self, pp, v):
        if pp == 0:
            self.x = (self.x & 0xFF00) | v
        elif pp == 1:
            self.x = (self.x & 0x00FF) | (v << 8)
        elif pp == 2:
            self.y = (self.y & 0xFF00) | v
        else:
            self.y = (self.y & 0x00FF) | (v << 8)

    def _wide(self, op):
        if op in (0x60, 0x61):
            v = self._fetch16()
            if op & 1:
                self.y = v
            else:
                self.x = v
            self.cycles += 5
        elif op in (0x62, 0x63):
            v = self.bus.read16(self._fetch16())
            if op & 1:
                self.y = v
            else:
                self.x = v
            self.cycles += 7
        elif op in (0x64, 0x65):
            self.bus.write16(self._fetch16(), self.y if op & 1 else self.x)
            self.cycles += 7
        elif op == 0x66:
            self.x = self.y
            self.cycles += 2
        elif op == 0x67:
            self.y = self.x
            self.cycles += 2
        elif op == 0x68:
            self.sp = self.x
            self.cycles += 2
        elif op == 0x69:
            self.sp = self.y
            self.cycles += 2
        elif op == 0x6A:
            self.x = self.sp
            self.cycles += 2
        elif op == 0x6B:
            self.y = self.sp
            self.cycles += 2
        elif op == 0x6C:                                # ADDW SP,#d8 signed
            d = self._fetch()
            self.sp = (self.sp + (d - 256 if d > 127 else d)) & 0xFFFF
            self.cycles += 4
        else:                                           # LEA X|Y,[SP+u8]
            v = (self.sp + self._fetch()) & 0xFFFF
            if op == 0x6D:
                self.x = v
            else:
                self.y = v
            self.cycles += 4

    def _autoinc(self, op):
        pre = bool(op & 0x10)
        dd, use_y = (op >> 1) & 3, op & 1
        ptr = self.y if use_y else self.x
        if pre:
            ptr = (ptr - 1) & 0xFFFF
        self._memop(op & 8, dd, ptr)
        if not pre:
            ptr = (ptr + 1) & 0xFFFF
        if use_y:
            self.y = ptr
        else:
            self.x = ptr
        self.cycles += 4

    # -------------------------------------------------------- harness

    def on_halt(self):
        """Overridable hook. The CPU itself just stops."""

    def flagstr(self):
        return "".join(c if f else c.lower() for c, f in
                       zip("CZNVI", (self.C, self.Z, self.N, self.V, self.I)))

    def trace_line(self):
        text, n = opcodes.disassemble(self.bus.read, self.pc)
        raw = " ".join(f"{self.bus.read(self.pc + i):02X}" for i in range(n))
        return (f"{self.pc:04X} {raw:<11} {text:<20} "
                f"R{self.r[0]:02X}{self.r[1]:02X}{self.r[2]:02X}{self.r[3]:02X} "
                f"X{self.x:04X} Y{self.y:04X} S{self.sp:04X} "
                f"{self.flagstr()} {self.cycles:8d}")

    def run(self, max_instructions=1_000_000, trace=False, out=sys.stdout):
        while self.instructions < max_instructions:
            if self.halted and not (self.nmi_edge or
                                    (self.irq_line and self.I)):
                return "halted"
            if trace:
                print(self.trace_line(), file=out)
            self.step()
        return "instruction limit"


# ====================================================================
# Self-test
# ====================================================================

def _selftest():
    fails = []

    def check(name, ok, detail=""):
        if not ok:
            fails.append(f"{name}: {detail}")

    cpu = Cool8()

    # --- 1. Exhaustive ALU flags against independent signed arithmetic.
    # The implementation uses bit tricks; this reference uses Python
    # integers and range checks, so it is a genuinely separate derivation.
    def sgn(v):
        return v - 256 if v > 127 else v

    bad = 0
    for a in range(256):
        for b in range(256):
            for cin in (False, True):
                # ADC
                cpu.C = cin
                r = cpu.alu(ADC, a, b)
                exp = a + b + cin
                if (r != exp & 0xFF or cpu.C != (exp > 0xFF) or
                        cpu.V != (not -128 <= sgn(a) + sgn(b) + cin <= 127) or
                        cpu.Z != (exp & 0xFF == 0) or
                        cpu.N != bool(exp & 0x80)):
                    bad += 1
                # SBC:  a - b - (1-C)
                cpu.C = cin
                r = cpu.alu(SBC, a, b)
                borrow = 0 if cin else 1
                exp = a - b - borrow
                sexp = sgn(a) - sgn(b) - borrow
                if (r != exp & 0xFF or cpu.C != (exp >= 0) or
                        cpu.V != (not -128 <= sexp <= 127) or
                        cpu.Z != (exp & 0xFF == 0)):
                    bad += 1
    check("ALU flags (ADC/SBC, 131072 cases)", bad == 0, f"{bad} mismatches")

    # CMP must never write back, and must match SUB's flags
    for a, b in ((0, 0), (5, 5), (0x80, 0x7F), (0x7F, 0x80), (0, 1)):
        cpu.C = True
        cpu.r[0] = a
        f_sub = (lambda: (cpu.alu(SUB, a, b), cpu.f))()[1]
        cpu.C = True
        f_cmp = (lambda: (cpu.alu(CMP, a, b), cpu.f))()[1]
        check(f"CMP flags match SUB ({a},{b})", f_sub == f_cmp)

    # --- 2. MOV writes no flags; loads and pops do.
    cpu.reset()
    cpu.C = cpu.Z = cpu.N = cpu.V = True
    before = cpu.f
    cpu.alu(MOV, 0x00, 0x00)
    check("MOV leaves flags alone", cpu.f == before)

    # --- 3. Logical ops preserve C and V.
    cpu.C, cpu.V = True, True
    cpu.alu(AND, 0xF0, 0x0F)
    check("AND preserves C", cpu.C is True)
    check("AND preserves V", cpu.V is True)
    check("AND sets Z", cpu.Z is True)

    # --- 4. Documented free idioms behave as claimed.
    cpu.reset()
    cpu.r[0] = 0x81
    cpu.C = False
    cpu.alu(ADD, cpu.r[0], cpu.r[0])
    check("ADD Rd,Rd is SHL (carry out)", cpu.C is True)
    cpu.C = True
    r = cpu.alu(ADC, 0x80, 0x80)
    check("ADC Rd,Rd is ROL", r == 0x01 and cpu.C is True, f"r={r:02X}")
    r = cpu.alu(SUB, 0x42, 0x42)
    check("SUB Rd,Rd clears", r == 0 and cpu.Z and cpu.C)
    cpu.C = False
    r = cpu.alu(SBC, 0x42, 0x42)
    check("SBC Rd,Rd sign-extends carry (C=0)", r == 0xFF, f"r={r:02X}")
    cpu.C = True
    r = cpu.alu(SBC, 0x42, 0x42)
    check("SBC Rd,Rd sign-extends carry (C=1)", r == 0x00, f"r={r:02X}")

    # --- 5. Every primary opcode executes without blowing up, and the
    #        table's mnemonic agrees with what the decoder did.
    for op in range(256):
        b = Bus()
        b.load(0x0200, bytes([op, 0x00, 0x00, 0x00]))
        b.write16(RESET_VEC, 0x0200)
        b.write16(BRK_VEC, 0x0300)
        c = Cool8(b)
        try:
            c.step()
        except Exception as e:                          # noqa: BLE001
            check(f"opcode ${op:02X} executes", False, repr(e))
    check("all 256 primary opcodes execute", True)

    # --- 6. Instruction lengths agree with the table for every opcode.
    for op in range(256):
        if op == 0x2F:
            continue
        b = Bus()
        b.load(0x0200, bytes([op, 0x11, 0x22, 0x33]))
        b.write16(RESET_VEC, 0x0200)
        c = Cool8(b)
        c.step()
        # branches and jumps move PC elsewhere; only check straight-line
        if not (0x70 <= op <= 0x7F) and op not in (
                0x22, 0x23, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E):
            want = opcodes.length(op)
            got = (c.pc - 0x0200) & 0xFFFF
            check(f"length of ${op:02X}", got == want, f"{got} != {want}")

    # --- 7. Page 2: every assigned opcode runs; every reserved one traps.
    for op2 in range(256):
        b = Bus()
        b.load(0x0200, bytes([0x2F, op2, 0x11, 0x22]))
        b.write16(RESET_VEC, 0x0200)
        b.write16(BRK_VEC, 0x0300)
        c = Cool8(b)
        c.step()
        if op2 in opcodes.page2:
            check(f"page2 ${op2:02X} does not trap", c.pc != 0x0300)
        else:
            check(f"page2 ${op2:02X} traps to BRK", c.pc == 0x0300,
                  f"pc={c.pc:04X}")

    # --- 8. MUL, exhaustively.
    bad = 0
    for a in range(256):
        for bb in range(256):
            b = Bus()
            b.load(0x0200, bytes([0x2F, 0xF4]))         # MUL R1,R0
            b.write16(RESET_VEC, 0x0200)
            c = Cool8(b)
            c.r[1], c.r[0] = a, bb
            c.step()
            if c.x != a * bb or c.Z != (a * bb == 0):
                bad += 1
    check("MUL exhaustive (65536 cases)", bad == 0, f"{bad} mismatches")

    # --- 9. Reset SP is below the vector table.
    c = Cool8()
    c.reset()
    check("reset SP is $FFF8", c.sp == 0xFFF8, f"{c.sp:04X}")
    c._push(0xAA)
    check("first push lands at $FFF7", c.sp == 0xFFF7)
    check("first push misses the vectors", c.bus.mem[BRK_VEC + 1] == 0)

    # --- 10. The byte-copy loop from docs/02-isa.md section 9.1.
    prog = bytes([
        0x42,              # loop: LD   R1,[X]
        0x4B,              #       ST   [Y],R1
        0x38,              #       INCW X
        0x39,              #       INCW Y
        0x0C, 0x01,        #       SUB  R0,#1
        0x73, 0xF8,        #       BNE  loop
        0x21,              #       HALT
    ])
    check("copy loop is 8 bytes + HALT", len(prog) == 9)
    b = Bus()
    b.load(0x0200, prog)
    b.load(0x1000, bytes(range(64)))
    b.write16(RESET_VEC, 0x0200)
    c = Cool8(b)
    c.x, c.y, c.r[0] = 0x1000, 0x2000, 64
    c.run(2000)
    check("copy loop moved 64 bytes",
          bytes(b.mem[0x2000:0x2040]) == bytes(range(64)))
    check("copy loop left R2/R3 alone", c.r[2] == 0 and c.r[3] == 0)
    check("copy loop advanced both pointers",
          c.x == 0x1040 and c.y == 0x2040, f"X={c.x:04X} Y={c.y:04X}")

    # --- 11. CALL/RET round trip and little-endian stack order.
    b = Bus()
    b.load(0x0200, bytes([0x29, 0x00, 0x03, 0x21]))     # CALL $0300 ; HALT
    b.load(0x0300, bytes([0x22]))                       # RET
    b.write16(RESET_VEC, 0x0200)
    c = Cool8(b)
    c.step()
    check("CALL pushed the return address", c.sp == 0xFFF6)
    check("return address is little-endian",
          b.mem[0xFFF6] == 0x03 and b.mem[0xFFF7] == 0x02,
          f"{b.mem[0xFFF6]:02X} {b.mem[0xFFF7]:02X}")
    c.step()
    check("RET returned", c.pc == 0x0203 and c.sp == 0xFFF8)

    # --- 12. Interrupts: entry pushes PC then F, RETI restores both.
    b = Bus()
    b.load(0x0200, bytes([0x20, 0x21]))                 # NOP ; HALT
    b.load(0x0400, bytes([0x2F, 0x23]))                 # (RETI is $23)
    b.load(0x0400, bytes([0x23]))
    b.write16(RESET_VEC, 0x0200)
    b.write16(IRQ_VEC, 0x0400)
    c = Cool8(b)
    c.I = True
    c.C = True
    c.irq_line = True
    c.step()
    check("IRQ taken when I is set", c.pc == 0x0400, f"pc={c.pc:04X}")
    check("IRQ cleared I", c.I is False)
    c.irq_line = False
    c.step()
    check("RETI restored PC", c.pc == 0x0200, f"pc={c.pc:04X}")
    check("RETI restored I", c.I is True)
    check("RETI restored C", c.C is True)

    # IRQ must be ignored while I is clear; NMI must not be.
    c = Cool8(b)
    c.I = False
    c.irq_line = True
    c.step()
    check("IRQ ignored when I is clear", c.pc != 0x0400)
    b.write16(NMI_VEC, 0x0500)
    c = Cool8(b)
    c.I = False
    c.pulse_nmi()
    c.step()
    check("NMI taken regardless of I", c.pc == 0x0500, f"pc={c.pc:04X}")

    # --- 13. Signed branch conditions, the ones easiest to get wrong.
    for a, bb, cc, name in ((0x7F, 0x80, 13, "BLT 127 < -128 is false"),
                            (0x80, 0x7F, 13, "BLT -128 < 127 is true"),
                            (0x05, 0x05, 15, "BLE 5 <= 5 is true"),
                            (0x05, 0x06, 14, "BGT 5 > 6 is false")):
        c = Cool8()
        c.alu(CMP, a, bb)
        want = {"BLT 127 < -128 is false": False,
                "BLT -128 < 127 is true": True,
                "BLE 5 <= 5 is true": True,
                "BGT 5 > 6 is false": False}[name]
        check(name, c.cond(cc) == want)

    # --- 14. Directed semantics for every page-2 group and every
    #         addressing mode. Sections 5-7 only prove nothing crashes;
    #         these prove the results are right.
    def run_prog(code, setup=None, steps=1, mem=None):
        b = Bus()
        b.load(0x0200, bytes(code))
        b.write16(RESET_VEC, 0x0200)
        b.write16(BRK_VEC, 0x0300)
        if mem:
            for a, v in mem.items():
                b.write(a, v)
        c = Cool8(b)
        if setup:
            setup(c)
        for _ in range(steps):
            c.step()
        return c

    def setr(**kw):
        def f(c):
            for k, v in kw.items():
                if k.startswith("r"):
                    c.r[int(k[1])] = v
                else:
                    setattr(c, k, v)
        return f

    # shifts and rotates -- SAR preserving the sign bit is the one that
    # a "does it execute" test silently misses
    cases = [
        ("SHR $81", [0x2F, 0x20], setr(r0=0x81), lambda c: c.r[0] == 0x40 and c.C),
        ("SHR $40", [0x2F, 0x20], setr(r0=0x40), lambda c: c.r[0] == 0x20 and not c.C),
        # bit 0 and bit 7 must disagree here, or a carry taken from the
        # wrong end of the byte looks identical
        ("SHR $03 carry from bit 0", [0x2F, 0x20], setr(r0=0x03),
         lambda c: c.r[0] == 0x01 and c.C),
        ("SHR $80 carry from bit 0", [0x2F, 0x20], setr(r0=0x80),
         lambda c: c.r[0] == 0x40 and not c.C),
        ("SAR $03 carry from bit 0", [0x2F, 0x24], setr(r0=0x03),
         lambda c: c.r[0] == 0x01 and c.C),
        ("ROR $80 carry from bit 0", [0x2F, 0x28], setr(r0=0x80, C=False),
         lambda c: c.r[0] == 0x40 and not c.C),
        ("SAR $81 keeps sign", [0x2F, 0x24], setr(r0=0x81),
         lambda c: c.r[0] == 0xC0 and c.C and c.N),
        ("SAR $40 stays positive", [0x2F, 0x24], setr(r0=0x40),
         lambda c: c.r[0] == 0x20 and not c.C and not c.N),
        ("ROR carry in", [0x2F, 0x28], setr(r0=0x01, C=True),
         lambda c: c.r[0] == 0x80 and c.C),
        ("ROR carry out", [0x2F, 0x28], setr(r0=0x02, C=False),
         lambda c: c.r[0] == 0x01 and not c.C),
        ("SWAP nibbles", [0x2F, 0x1C], setr(r0=0x3C), lambda c: c.r[0] == 0xC3),
        ("NOT", [0x2F, 0x14], setr(r0=0x0F), lambda c: c.r[0] == 0xF0 and c.N),
        ("NEG 1", [0x2F, 0x18], setr(r0=0x01),
         lambda c: c.r[0] == 0xFF and not c.C),
        ("NEG 0", [0x2F, 0x18], setr(r0=0x00), lambda c: c.r[0] == 0 and c.C),
        ("XOR imm", [0x2F, 0x10, 0xFF], setr(r0=0x5A), lambda c: c.r[0] == 0xA5),
        ("XOR reg", [0x2F, 0x01], setr(r0=0xF0, r1=0x3C),
         lambda c: c.r[0] == 0xCC),
        ("BSET", [0x2F, 0x30, 0x81], setr(r0=0x00), lambda c: c.r[0] == 0x81),
        ("BCLR", [0x2F, 0x34, 0x0F], setr(r0=0xFF), lambda c: c.r[0] == 0xF0),
        ("BTST hit", [0x2F, 0x38, 0x01], setr(r0=0x01),
         lambda c: c.r[0] == 0x01 and not c.Z),
        ("BTST miss", [0x2F, 0x38, 0x02], setr(r0=0x01),
         lambda c: c.r[0] == 0x01 and c.Z),
        # pointer halves
        ("MOV R0,XH", [0x2F, 0x41], setr(x=0xBEEF), lambda c: c.r[0] == 0xBE),
        ("MOV R0,XL", [0x2F, 0x40], setr(x=0xBEEF), lambda c: c.r[0] == 0xEF),
        ("MOV YH,R0", [0x2F, 0x53], setr(r0=0xAB, y=0x00CD),
         lambda c: c.y == 0xABCD),
        # 16-bit
        ("LDW X,#imm16", [0x2F, 0x60, 0x34, 0x12], None,
         lambda c: c.x == 0x1234),
        ("MOVW Y,X", [0x2F, 0x67], setr(x=0x1234), lambda c: c.y == 0x1234),
        ("MOVW SP,X", [0x2F, 0x68], setr(x=0x0180), lambda c: c.sp == 0x0180),
        ("ADDW SP,#-2", [0x2F, 0x6C, 0xFE], setr(sp=0x0100),
         lambda c: c.sp == 0x00FE),
        ("ADDW SP,#+2", [0x2F, 0x6C, 0x02], setr(sp=0x0100),
         lambda c: c.sp == 0x0102),
        ("LEA X,[SP+4]", [0x2F, 0x6D, 0x04], setr(sp=0x0100),
         lambda c: c.x == 0x0104),
        ("ADDW X,R0", [0x2F, 0x70], setr(x=0x1000, r0=0x20),
         lambda c: c.x == 0x1020),
        ("SUBW X,R0", [0x2F, 0x78], setr(x=0x1000, r0=0x20),
         lambda c: c.x == 0x0FE0),
        ("ADDW does not set flags", [0x2F, 0x70], setr(x=0xFFFF, r0=1, Z=False),
         lambda c: c.x == 0 and not c.Z),
        # addressing modes
        ("[X+d8] positive", [0x50, 0x05], setr(x=0x1000),
         lambda c: c.r[0] == 0x55),
        ("[X+d8] negative", [0x50, 0xFB], setr(x=0x100A),
         lambda c: c.r[0] == 0x55),
        ("[SP+u8] is unsigned", [0x60, 0xC8], setr(sp=0x2000),
         lambda c: c.r[0] == 0x77),
        ("[abs16]", [0x61, 0x05, 0x10], None, lambda c: c.r[0] == 0x55),
        ("[X+Rs] indexed", [0x2F, 0x81], setr(x=0x1000, r1=0x05),
         lambda c: c.r[0] == 0x55),
        ("[X+] post-increment", [0x2F, 0xC0], setr(x=0x1005),
         lambda c: c.r[0] == 0x55 and c.x == 0x1006),
        ("[-X] pre-decrement", [0x2F, 0xD0], setr(x=0x1006),
         lambda c: c.r[0] == 0x55 and c.x == 0x1005),
        # INCW wrapping sets Z from the full 16 bits
        ("INCW X wraps to zero sets Z", [0x38], setr(x=0xFFFF),
         lambda c: c.x == 0 and c.Z),
        ("INCW X does not set Z at $00FF", [0x38], setr(x=0x00FF),
         lambda c: c.x == 0x0100 and not c.Z),
        ("DECW Y to zero sets Z", [0x3B], setr(y=0x0001),
         lambda c: c.y == 0 and c.Z),
    ]
    probe = {0x1005: 0x55, 0x20C8: 0x77}
    assert len(probe) == 2 and 0x1005 not in (0x20C8,), "probe collision"
    for name, code, setup, want in cases:
        c = run_prog(code, setup, mem=probe)
        check(name, want(c), f"R={[f'{v:02X}' for v in c.r]} X={c.x:04X} "
                             f"Y={c.y:04X} SP={c.sp:04X} F={c.flagstr()}")

    # store side of each addressing mode
    stores = [
        ("ST [X]", [0x48], setr(x=0x3000, r0=0x5A), 0x3000),
        ("ST [X+d8]", [0x58, 0x04], setr(x=0x3000, r0=0x5A), 0x3004),
        ("ST [SP+u8]", [0x68, 0x08], setr(sp=0x3000, r0=0x5A), 0x3008),
        ("ST [abs16]", [0x69, 0x00, 0x30], setr(r0=0x5A), 0x3000),
        ("ST [X+Rs]", [0x2F, 0xA1], setr(x=0x3000, r0=0x5A, r1=0x03), 0x3003),
    ]
    for name, code, setup, addr in stores:
        c = run_prog(code, setup)
        check(name, c.bus.read(addr) == 0x5A, f"mem[{addr:04X}]")

    # PUSHW / POPW round trip, and stack byte order
    c = run_prog([0x3C, 0x3E], setr(x=0xBEEF, sp=0x0200), steps=1)
    check("PUSHW stored little-endian",
          c.bus.read(0x01FE) == 0xEF and c.bus.read(0x01FF) == 0xBE,
          f"{c.bus.read(0x01FE):02X} {c.bus.read(0x01FF):02X}")
    c.x = 0
    c.step()
    check("POPW restored X", c.x == 0xBEEF and c.sp == 0x0200)

    # --- 15. The emulator's own cycle accounting must agree with the
    #         static table in opcodes.py, which drives the assembler
    #         listing. Two independent statements of the timing model.
    for op in range(256):
        if op == 0x2F:
            continue
        want = opcodes.cycles(op)
        if isinstance(want, tuple):
            for taken, expect in ((False, want[0]), (True, want[1])):
                c = run_prog([op, 0x02], setr(Z=taken) if op == 0x72 else None)
                if op == 0x72:                        # BEQ, a clean probe
                    check(f"cycles ${op:02X} taken={taken}",
                          c.cycles == expect, f"{c.cycles} != {expect}")
            continue
        c = run_prog([op, 0x00, 0x00])
        check(f"cycles ${op:02X}", c.cycles == want, f"{c.cycles} != {want}")
    for op2 in sorted(opcodes.page2):
        c = run_prog([0x2F, op2, 0x00, 0x00])
        want = opcodes.cycles(0x2F, op2)
        check(f"cycles $2F ${op2:02X}", c.cycles == want,
              f"{c.cycles} != {want}")
    c = run_prog([0x2F, 0x03])                        # a reserved page-2 op
    check("cycles of a reserved page-2 trap",
          c.cycles == opcodes.cycles(0x2F, 0x03), c.cycles)

    # --- 16. Disassembly round-trips for every primary opcode.
    for op in range(256):
        b = Bus()
        b.load(0x0200, bytes([op, 0x34, 0x12]))
        text, n = opcodes.disassemble(b.read, 0x0200)
        check(f"disasm ${op:02X} has no placeholder left",
              "{" not in text, text)

    print(f"self-test: {len(fails)} failure(s)")
    for f in fails[:40]:
        print("  FAIL", f)
    if len(fails) > 40:
        print(f"  ... and {len(fails) - 40} more")
    return not fails


def main():
    ap = argparse.ArgumentParser(description="COOL8 reference emulator")
    ap.add_argument("image", nargs="?", help="flat binary to load")
    ap.add_argument("--at", default="0x0200",
                    help="load address (default 0x0200)")
    ap.add_argument("--go", help="entry point (defaults to the load address)")
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("--max", type=int, default=1_000_000)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if _selftest() else 1)
    if not args.image:
        ap.error("an image is required unless --selftest is given")

    at = int(args.at, 0)
    go = int(args.go, 0) if args.go else at
    bus = Bus()
    with open(args.image, "rb") as fh:
        bus.load(at, fh.read())
    bus.write16(RESET_VEC, go)
    # minimal console: writing UART_DATA goes to stdout
    bus.write_hooks[0xFE71] = lambda v: sys.stdout.write(chr(v))
    bus.read_hooks[0xFE70] = lambda: 0x02                # TX always ready

    cpu = Cool8(bus)
    why = cpu.run(args.max, trace=args.trace)
    print(f"\n-- {why} after {cpu.instructions} instructions, "
          f"{cpu.cycles} cycles", file=sys.stderr)


if __name__ == "__main__":
    main()
