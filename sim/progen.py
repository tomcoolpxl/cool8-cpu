#!/usr/bin/env python3
"""Test-program generators for COOL8 co-simulation.

Two shapes, both built straight from tools/opcodes.py so that adding an
instruction to the table adds it to the tests:

  directed()   one probe per encoding — 511 of them. Each probe sets the
               whole architectural state to a known value, executes one
               instruction, and jumps to the next probe. Control-flow
               instructions have their targets arranged so that every
               path converges on the same jump.

  random_prog() a stream of randomly chosen instructions with sane
               operands, re-anchoring the pointers every few
               instructions so that memory accesses land somewhere
               useful rather than immediately wandering off.

Neither generator knows anything about the RTL. sim/cosim.py runs the
result through both the emulator and the simulator and diffs the traces.
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "tools"))
import opcodes  # noqa: E402

# --- memory map for the generated programs ---------------------------
PROG    = 0x0200          # first probe
SLOT    = 64              # bytes per probe
SCRATCH = 0x9000          # data the programs are allowed to trample
XV      = 0x9100
YV      = 0x9180
ABSV    = 0x9200
SPV     = 0x9800
# Above the last probe: 511 probes of 64 bytes from $0200 end at $81C0.
STUBS   = 0x8800
RET_STUB  = STUBS + 0     # a bare RET, for CALL to land on
INT_STUB  = STUBS + 8     # a bare RETI, for BRK / IRQ / NMI

RESET_VEC, NMI_VEC, IRQ_VEC, BRK_VEC = 0xFFF8, 0xFFFA, 0xFFFC, 0xFFFE


def _w(mem, addr, data):
    for i, b in enumerate(data):
        mem[addr + i] = b & 0xFF


def _lo_hi(v):
    return [v & 0xFF, (v >> 8) & 0xFF]


def _preamble(fval, regs, xval, yval):
    """Put the whole architectural state somewhere known."""
    return ([0x2F, 0x60] + _lo_hi(SPV) +      # LDW X,#SPV
            [0x2F, 0x68] +                    # MOVW SP,X
            [0x00, fval & 0x1F] +             # MOV R0,#fval
            [0x30] +                          # PUSH R0
            [0x2F, 0xE1] +                    # POP F
            [0x00, regs[0]] + [0x01, regs[1]] +
            [0x02, regs[2]] + [0x03, regs[3]] +
            [0x2F, 0x60] + _lo_hi(xval) +     # LDW X,#xval
            [0x2F, 0x61] + _lo_hi(yval))      # LDW Y,#yval


def _encoding_list():
    """Every encoding, once. $2F is covered by the page-2 probes and
    HALT goes last because it ends the run."""
    ops = [(op, None) for op in range(256) if op not in (0x2F, 0x21)]
    ops += [(0x2F, op2) for op2 in range(256)]
    ops += [(0x21, None)]
    return ops


# Address of the instruction under test in each probe of the most
# recent directed() call, keyed by (op, op2). sim/timing.py reads the
# cycle cost of each encoding out of this.
PROBE_ADDR = {}


def directed(seed=1):
    """One probe per encoding. Returns (memory dict, probe count)."""
    rnd = random.Random(seed)
    mem = {}
    ops = _encoding_list()
    PROBE_ADDR.clear()

    for i, (op, op2) in enumerate(ops):
        base = PROG + i * SLOT
        jmp_at = base + SLOT - 3          # every path converges here
        nxt = base + SLOT

        xval, yval = XV, YV
        pre_extra = []

        # --- instructions that need their target arranged in advance
        if op == 0x2A:                     # JMP [X]
            xval = jmp_at
        elif op == 0x2B:                   # JMP [Y]
            yval = jmp_at
        elif op == 0x2C:                   # CALL [X]
            xval = RET_STUB
        elif op == 0x2D:                   # CALL [Y]
            yval = RET_STUB
        elif op in (0x22, 0x23):           # RET, RETI
            pre_extra = ([0x2F, 0x60] + _lo_hi(jmp_at) +   # LDW X,#jmp_at
                         [0x3C])                           # PUSHW X
            if op == 0x23:                                 # RETI also pops F
                pre_extra = ([0x2F, 0x60] + _lo_hi(jmp_at) + [0x3C] +
                             [0x00, rnd.randrange(32)] + [0x30])
            pre_extra += [0x2F, 0x60] + _lo_hi(xval)       # restore X

        regs = [rnd.randrange(256) for _ in range(4)]
        code = _preamble(rnd.randrange(256), regs, xval, yval) + pre_extra

        at = base + len(code)
        PROBE_ADDR[(op, op2)] = at
        code += _instruction(op, op2, at, jmp_at, rnd)

        # pad to the trailing jump
        code += [0x20] * (jmp_at - base - len(code))
        code += [0x28] + _lo_hi(nxt)
        assert len(code) == SLOT, (hex(op), len(code))
        _w(mem, base, code)

    _w(mem, RET_STUB, [0x22])
    _w(mem, INT_STUB, [0x23])
    _w(mem, RESET_VEC, _lo_hi(PROG))
    _w(mem, NMI_VEC,   _lo_hi(INT_STUB))
    _w(mem, IRQ_VEC,   _lo_hi(INT_STUB))
    _w(mem, BRK_VEC,   _lo_hi(INT_STUB))
    return mem, len(ops)


def _instruction(op, op2, at, jmp_at, rnd):
    """Emit one encoding with operands that keep the program on the
    rails: displacements stay inside the scratch area, branch and jump
    targets land on the probe's trailing jump."""
    if op == 0x2F:
        entry = opcodes.page2.get(op2)
        head = [0x2F, op2]
        if entry is None:
            return head                      # reserved — traps to BRK
        kind = entry[1]
        length = 2
    else:
        entry = opcodes.primary[op]
        head = [op]
        kind = entry[1]
        length = 1

    n = opcodes.EXTRA[kind]
    total = length + n

    if n == 0:
        return head
    if kind == opcodes.REL8:
        rel = jmp_at - (at + total)
        assert -128 <= rel <= 127
        return head + [rel & 0xFF]
    if kind == opcodes.DISP8:
        return head + [(rnd.randrange(-32, 32)) & 0xFF]
    if kind == opcodes.U8:
        return head + [rnd.randrange(0, 64)]
    if kind in (opcodes.IMM8, opcodes.MASK8):
        return head + [rnd.randrange(256)]
    if kind == opcodes.ABS16:
        if op == 0x28:                       # JMP abs16
            return head + _lo_hi(jmp_at)
        if op == 0x29:                       # CALL abs16
            return head + _lo_hi(RET_STUB)
        return head + _lo_hi(ABSV + rnd.randrange(0, 64))
    if kind == opcodes.IMM16:
        return head + _lo_hi(rnd.randrange(0x10000))
    raise AssertionError("unhandled operand kind")


# ---------------------------------------------------------------------
# Randomised streams
# ---------------------------------------------------------------------

# Encodings that would end or derail a random run rather than test it.
_RANDOM_SKIP_PRIMARY = {0x21, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F,
                        0x22, 0x23}


def random_prog(seed, count=4000, anchor_every=6):
    """A stream of random instructions. Pointers and SP are re-anchored
    every `anchor_every` instructions so accesses keep hitting scratch;
    between anchors the code is free to do whatever it likes, including
    corrupting its own pointers."""
    rnd = random.Random(seed)
    mem = {}

    pool = [(op, None) for op in range(256)
            if op not in _RANDOM_SKIP_PRIMARY]
    pool += [(0x2F, o2) for o2 in sorted(opcodes.page2)]

    body = []
    emitted = 0
    while emitted < count:
        if emitted % anchor_every == 0:
            body += _preamble(rnd.randrange(256),
                              [rnd.randrange(256) for _ in range(4)], XV, YV)
            emitted += 11
            continue
        op, op2 = rnd.choice(pool)
        at = PROG + len(body)
        # A backward branch could spin; keep them short and forward.
        if 0x70 <= op <= 0x7F:
            body += [op, rnd.randrange(0, 8)]
        else:
            body += _instruction(op, op2, at, at + 2, rnd)
        emitted += 1

    body += [0x21]                            # HALT
    _w(mem, PROG, body)
    _w(mem, RET_STUB, [0x22])
    _w(mem, INT_STUB, [0x23])
    _w(mem, RESET_VEC, _lo_hi(PROG))
    _w(mem, NMI_VEC,   _lo_hi(INT_STUB))
    _w(mem, IRQ_VEC,   _lo_hi(INT_STUB))
    _w(mem, BRK_VEC,   _lo_hi(INT_STUB))
    return mem


def write_hex(mem, path):
    """64 K of memory, one hex byte per line, for $readmemh."""
    full = bytearray(0x10000)
    for a, b in mem.items():
        full[a] = b
    with open(path, "w") as f:
        f.write("".join("%02x\n" % b for b in full))
    return full
