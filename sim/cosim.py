#!/usr/bin/env python3
"""COOL8 RTL co-simulation — the RTL against the software model.

This runs the same program through the model and through the Verilog,
each emitting one line of full architectural state per retired
instruction, and reports the first line where they disagree together
with the disassembly of the instruction that caused it.

The model side is cool8rs — the machine (RUST_PORT.md). The Python
reference emulator retired (D57 in docs/01-decisions.md); this diff,
against the silicon-truth of the RTL, is now the contract that holds
the model honest, exactly as it once held the RTL to the emulator.

    python sim/cosim.py directed          # one probe per encoding
    python sim/cosim.py random            # constrained-random streams
    python sim/cosim.py interrupts        # irq, nmi, brk, halt, busrq
    python sim/cosim.py mul               # 65536 exhaustive operand pairs
    python sim/cosim.py all

Set OSS_CAD_SUITE to the toolchain root if iverilog is not on PATH.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")

sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

import opcodes                              # noqa: E402
import cool8rsvm                            # noqa: E402
import progen                               # noqa: E402
import toolchain as T                       # noqa: E402

RTL = T.CORE
TB = os.path.join(HERE, "tb", "cool8_tb.v")
PADS = os.path.join(ROOT, "rtl", "pads", "tt_um_cool8.v")
BUSTB = os.path.join(HERE, "tb", "cool8_bus_tb.v")
SPRAM = os.path.join(ROOT, "rtl", "soc", "cool8_spram.v")
SPRAMTB = os.path.join(HERE, "tb", "cool8_spram_cpu_tb.v")


# ------------------------------------------------------------- toolchain
#
# In sim/toolchain.py, which every RTL suite shares. It lived here, and
# ten other files reached in through its private names.

def build_sim():
    return T.build("cool8_tb", TB, RTL)


def build_bus_sim():
    return T.build("cool8_bus_tb", BUSTB, RTL + [PADS])


def build_spram_sim():
    return T.build("cool8_spram_cpu_tb", SPRAMTB,
                   RTL + [SPRAM, T.cells()], gen="2012")


def run_sim(vvp_file, args):
    return T.run(vvp_file, args)


# --------------------------------------------------------------- emulator

def rs_trace(hexf, path, max_instr=0, plusargs=()):
    """The same trace out of cool8rs — the fast model, ~150x the speed.

    The runner takes the RTL testbench's plusarg vocabulary verbatim
    (hardware-only knobs accepted and ignored), which is why the same
    `sim_args` the vvp gets can be passed straight through: an
    interrupt spec expressed as `+irqafter=` means the same retirement
    boundary to both.
    """
    memf = path + ".mem"
    cmd = [cool8rsvm.EXE, f"+hex={hexf}", f"+trace={path}",
           f"+memdump={memf}"]
    if max_instr:
        cmd.append(f"+maxinstr={max_instr}")
    cmd += list(plusargs)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("cool8rs failed")
    n = int(r.stdout.split()[1])        # "-- N instructions, ..."
    return n, read_memdump(memf)


def model_trace(image, hexf, path, max_instr=0, events=None, plusargs=()):
    """One model-side trace, out of cool8rs.

    `image` and `events` are unused now the Python emulator has
    retired — kept in the signature so the call sites, which mirror
    the RTL invocations beside them, do not churn. The interrupt spec
    travels as `plusargs`, the vocabulary the model and the testbench
    share.
    """
    del image, events
    if not cool8rsvm.available():
        raise SystemExit("cosim needs cool8rs (cargo) — see RUST_PORT.md")
    return rs_trace(hexf, path, max_instr=max_instr, plusargs=plusargs)


# ------------------------------------------------------------------ diff

def disasm_at(image, pc):
    text, _ = opcodes.disassemble(lambda a: image[a & 0xFFFF], pc)
    return text


HDR = "  PC   R0R1R2R3 X    Y    SP   F"


def compare(name, emu_path, rtl_path, emu_mem, rtl_mem, image):
    with open(emu_path) as f:
        a = f.read().split("\n")
    with open(rtl_path) as f:
        b = f.read().split("\n")

    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            if not a[i] and not b[i]:
                continue
            prev = a[i - 1].split()[0] if i else "reset"
            print(f"\n  {name}: DIVERGED at instruction {i}")
            print(f"    after   {prev}  {disasm_at(image, int(prev, 16))}"
                  if i else "    at the first instruction")
            print(f"    {HDR}")
            print(f"    emu {a[i]}")
            print(f"    rtl {b[i]}")
            return False

    la, lb = len([x for x in a if x]), len([x for x in b if x])
    if la != lb:
        print(f"\n  {name}: instruction counts differ — "
              f"emulator {la}, RTL {lb}")
        return False

    if emu_mem is not None and rtl_mem is not None:
        bad = [i for i in range(0x10000) if emu_mem[i] != rtl_mem[i]]
        if bad:
            print(f"\n  {name}: {len(bad)} memory bytes differ, first at "
                  f"${bad[0]:04X}: emu ${emu_mem[bad[0]]:02X} "
                  f"rtl ${rtl_mem[bad[0]]:02X}")
            return False
    return True


def read_memdump(path):
    with open(path) as f:
        return bytes(int(x, 16) for x in f.read().split())


# ------------------------------------------------------------------ tests

def _run_pair(tag, mem, vvp, sim_args=(), max_instr=0, events=None,
              check_mem=True):
    os.makedirs(BUILD, exist_ok=True)
    hexf = os.path.join(BUILD, f"{tag}.hex")
    image = progen.write_hex(mem, hexf)

    emu_t = os.path.join(BUILD, f"{tag}.emu")
    n, emu_mem = model_trace(image, hexf, emu_t, max_instr=max_instr,
                             events=events, plusargs=sim_args)

    rtl_t = os.path.join(BUILD, f"{tag}.rtl")
    rtl_m = os.path.join(BUILD, f"{tag}.rtlmem")
    args = [f"+hex={hexf}", f"+trace={rtl_t}", f"+memdump={rtl_m}",
            "+maxcycles=40000000"] + list(sim_args)
    if max_instr:
        args.append(f"+maxinstr={max_instr}")
    run_sim(vvp, args)

    rtl_mem = read_memdump(rtl_m) if check_mem else None
    ok = compare(tag, emu_t, rtl_t, emu_mem if check_mem else None,
                 rtl_mem, image)
    return ok, n


def test_directed(vvp, waits):
    print("directed — one probe per encoding")
    mem, nprobes = progen.directed()
    allok = True
    for ws in waits:
        tag = f"directed_ws{ws}"
        args = ["+wsrnd=12345"] if ws == "r" else [f"+ws={ws}"]
        t0 = time.time()
        ok, n = _run_pair(tag, mem, vvp, args)
        allok &= ok
        print(f"  {nprobes} encodings, {n} instructions, "
              f"wait states {ws:>1} : {'ok' if ok else 'FAIL'} "
              f"({time.time() - t0:.1f}s)")
    return allok


def test_random(vvp, seeds, count):
    print(f"random — {len(seeds)} streams of {count} instructions")
    allok = True
    for s in seeds:
        mem = progen.random_prog(s, count=count)
        ws = ["+wsrnd=%d" % (s * 7 + 1)] if s % 2 else ["+ws=%d" % (s % 3)]
        ok, n = _run_pair(f"random{s}", mem, vvp, ws, max_instr=count)
        allok &= ok
        if not ok:
            print(f"  seed {s}: FAIL")
    if allok:
        print(f"  seeds {min(seeds)}..{max(seeds)} : ok")
    return allok


def test_interrupts(vvp):
    """IRQ, NMI, BRK, HALT wake-up and bus grant.

    Interrupts are injected after a given number of retired
    instructions rather than at a given cycle, so the emulator and the
    testbench agree on exactly which instruction boundary the line was
    raised at without either having to model the other's timing.

    The bus-grant case is the important one: a grant must be
    architecturally invisible, so a run with one has to be byte-for-byte
    identical to a run without.
    """
    print("interrupts, halt and bus grant")
    ok = True

    mem, _ = progen.directed(seed=3)
    base_ok, _ = _run_pair("grant_none", mem, vvp, ["+ws=0"])
    grant_ok, _ = _run_pair("grant_mid", mem, vvp,
                            ["+ws=0", "+busrqat=5000", "+busrqlen=97"])
    grant2_ok, _ = _run_pair("grant_b", mem, vvp,
                             ["+wsrnd=7", "+busrqafter=1200", "+busrqlen=31"])
    with open(os.path.join(BUILD, "grant_none.rtl")) as f:
        a = f.read()
    same = True
    for other in ("grant_mid", "grant_b"):
        with open(os.path.join(BUILD, other + ".rtl")) as f:
            same &= (a == f.read())
    print(f"  bus grant is architecturally invisible : "
          f"{'ok' if same and grant_ok and grant2_ok else 'FAIL'}")
    ok &= base_ok and grant_ok and grant2_ok and same

    for name, (mem, ev, args) in (
            ("irq wakes HALT   ", _halt_irq_prog()),
            ("irq mid-stream   ", _irq_stream_prog()),
            ("nmi is unmaskable", _nmi_prog()),
            ("brk and the page-2 trap", _brk_prog())):
        tag = name.split()[0] + str(abs(hash(name)) % 97)
        hexf = os.path.join(BUILD, f"{tag}.hex")
        image = progen.write_hex(mem, hexf)
        emu_t = os.path.join(BUILD, f"{tag}.emu")
        n, emu_mem = model_trace(image, hexf, emu_t, events=ev,
                                 plusargs=args)
        rtl_t = os.path.join(BUILD, f"{tag}.rtl")
        rtl_m = os.path.join(BUILD, f"{tag}.rtlmem")
        run_sim(vvp, [f"+hex={hexf}", f"+trace={rtl_t}", f"+memdump={rtl_m}",
                      "+maxcycles=2000000"] + args)
        good = compare(tag, emu_t, rtl_t, emu_mem, read_memdump(rtl_m), image)
        print(f"  {name} : {'ok' if good else 'FAIL'} ({n} instructions)")
        ok &= good
    return ok


def _stub_vectors(mem, handler):
    progen._w(mem, progen.RESET_VEC, progen._lo_hi(progen.PROG))
    progen._w(mem, progen.NMI_VEC, progen._lo_hi(handler))
    progen._w(mem, progen.IRQ_VEC, progen._lo_hi(handler))
    progen._w(mem, progen.BRK_VEC, progen._lo_hi(handler))


# The saved flags sit at [SP+0] on entry, the return address above them.
# Clearing I there stops a level-sensitive IRQ re-entering forever, and
# exercises [SP+u8] and BCLR on the way.
_ACK_HANDLER = ([0x60, 0x00] +          # LD   R0,[SP+0]
                [0x2F, 0x34, 0x10] +    # BCLR R0,#$10
                [0x68, 0x00])           # ST   [SP+0],R0


def _prologue():
    return ([0x2F, 0x60] + progen._lo_hi(progen.SPV) +   # LDW X,#SP
            [0x2F, 0x68])                                # MOVW SP,X


def _halt_irq_prog():
    """EI, HALT, and an IRQ that wakes it."""
    mem = {}
    h = progen.STUBS
    body = _prologue() + [
        0x00, 0x00,          # MOV R0,#0
        0x24,                # EI
        0x21,                # HALT
        0x04, 0x01,          # ADD R0,#1
        0x21,                # HALT   (I is clear by now, so this sticks)
    ]
    progen._w(mem, progen.PROG, body)
    progen._w(mem, h, _ACK_HANDLER + [0x02, 0x55, 0x23])   # MOV R2,#$55; RETI
    _stub_vectors(mem, h)
    # instructions: 0 LDW, 1 MOVW, 2 MOV, 3 EI, 4 HALT -> raise at 5
    return mem, {5: lambda c: setattr(c, "irq_line", True)}, ["+irqafter=5"]


def _irq_stream_prog():
    """An IRQ taken between two ordinary instructions.

    The line is asserted from reset and I is clear, so the boundary at
    which the interrupt is taken is decided by the EI in the program
    rather than by when the testbench happens to raise the pin. That
    makes the test independent of cycle timing on either side.
    """
    mem = {}
    h = progen.STUBS
    body = _prologue() + [0x00, 0x00]              # MOV R0,#0
    body += [0x04, 0x01] * 3                       # ADD R0,#1 x3
    body += [0x24]                                 # EI  -> taken here
    body += [0x04, 0x01] * 4
    body += [0x21]
    progen._w(mem, progen.PROG, body)
    progen._w(mem, h, _ACK_HANDLER + [0x02, 0xAA, 0x23])
    _stub_vectors(mem, h)
    return mem, {0: lambda c: setattr(c, "irq_line", True)}, ["+irqat=0"]


def _nmi_prog():
    """NMI with interrupts disabled — it must be taken anyway, and it
    must wake a halted machine."""
    mem = {}
    h = progen.STUBS
    body = _prologue() + [
        0x00, 0x00,          # MOV R0,#0
        0x25,                # DI
        0x21,                # HALT
        0x04, 0x01,          # ADD R0,#1
        0x21,                # HALT   (nothing left to wake it)
    ]
    progen._w(mem, progen.PROG, body)
    progen._w(mem, h, [0x03, 0x99, 0x23])          # MOV R3,#$99 ; RETI
    _stub_vectors(mem, h)
    # 0 LDW, 1 MOVW, 2 MOV, 3 DI, 4 HALT
    return mem, {5: lambda c: c.pulse_nmi()}, ["+nmiafter=5"]


def _brk_prog():
    mem = {}
    h = progen.STUBS
    body = _prologue() + [
        0x00, 0x11,          # MOV R0,#$11
        0x2E,                # BRK
        0x01, 0x22,          # MOV R1,#$22
        0x2F, 0x2E,          # reserved page-2 encoding -> BRK vector
        0x02, 0x33,          # MOV R2,#$33
        0x21,
    ]
    progen._w(mem, progen.PROG, body)
    progen._w(mem, h, [0x03, 0x77, 0x23])          # MOV R3,#$77 ; RETI
    _stub_vectors(mem, h)
    return mem, {}, []


def _mul_prog():
    """All 65536 operand pairs, folded into a position-dependent
    checksum so the whole sweep fits in one short program."""
    mem = {}
    a = progen.ABSV
    prog = progen.PROG
    body = ([0x2F, 0x60] + progen._lo_hi(progen.SPV) + [0x2F, 0x68] +
            [0x02, 0x00])                                   # MOV R2,#0
    outer = prog + len(body)
    body += [0x03, 0x00]                                    # MOV R3,#0
    inner = prog + len(body)
    body += [0x2F, 0xFB]                                    # MUL R2,R3
    for half, addr in ((0x40, a), (0x41, a + 1)):           # XL then XH
        body += [0x2F, half]                                # MOV R0,<half>
        body += [0x63] + progen._lo_hi(addr)                # LD R1,[abs]
        body += [0x95]                                      # ADD R1,R1  (SHL)
        body += [0xA4]                                      # ADC R1,R0
        body += [0x6B] + progen._lo_hi(addr)                # ST [abs],R1
    body += [0x07, 0x01]                                    # ADD R3,#1
    rel = inner - (prog + len(body) + 2)
    body += [0x73, rel & 0xFF]                              # BNE inner
    body += [0x06, 0x01]                                    # ADD R2,#1
    rel = outer - (prog + len(body) + 2)
    body += [0x73, rel & 0xFF]                              # BNE outer
    body += [0x21]                                          # HALT
    progen._w(mem, prog, body)
    _stub_vectors(mem, progen.STUBS)
    progen._w(mem, progen.STUBS, [0x23])
    return mem


def test_bus(vvp_unused):
    """The same instruction-level check, but through the TinyTapeout
    three-phase multiplexer and a behavioural 74HC573 pair and SRAM.

    A failure here that does not also fail cool8_tb is a pad-wrapper
    bug, not a CPU bug.
    """
    print("ASIC bus — three-phase multiplexer, latches and SRAM")
    vvp = build_bus_sim()
    mem, nprobes = progen.directed()
    allok = True
    for tag, args in (("bus", []), ("bus_ws", ["+wsrnd=999"])):
        hexf = os.path.join(BUILD, f"{tag}.hex")
        image = progen.write_hex(mem, hexf)
        emu_t = os.path.join(BUILD, f"{tag}.emu")
        t0 = time.time()
        n, emu_mem = model_trace(image, hexf, emu_t)
        rtl_t = os.path.join(BUILD, f"{tag}.rtl")
        rtl_m = os.path.join(BUILD, f"{tag}.rtlmem")
        run_sim(vvp, [f"+hex={hexf}", f"+trace={rtl_t}", f"+memdump={rtl_m}"]
                + args)
        ok = compare(tag, emu_t, rtl_t, emu_mem, read_memdump(rtl_m), image)
        allok &= ok
        print(f"  {nprobes} encodings, {n} instructions"
              f"{', READY pulled low at random' if args else ''} : "
              f"{'ok' if ok else 'FAIL'} ({time.time() - t0:.1f}s)")
    return allok


def test_spram(vvp_unused):
    """The same instruction-level check, but out of two SB_SPRAM256KA.

    The timing here is not a testbench's idea of a wait state — it is the
    registered read the part actually has, one clock on every fetch and
    every load, and none on a store. A failure here that does not also
    fail cool8_tb is in rtl/soc/cool8_spram.v, not in the CPU.
    """
    print("SPRAM — the core running out of two SB_SPRAM256KA")
    vvp = build_spram_sim()
    allok = True

    mem, nprobes = progen.directed()
    t0 = time.time()
    ok, n = _run_pair("spram_directed", mem, vvp)
    allok &= ok
    print(f"  {nprobes} encodings, {n} instructions : "
          f"{'ok' if ok else 'FAIL'} ({time.time() - t0:.1f}s)")

    for s in (1, 2, 3):
        mem = progen.random_prog(s, count=3000)
        ok, _ = _run_pair(f"spram_random{s}", mem, vvp, max_instr=3000)
        allok &= ok
        if not ok:
            print(f"  seed {s}: FAIL")
    if allok:
        print("  3 random streams of 3000 instructions : ok")
    return allok


def test_mul(vvp):
    print("multiply — 65536 exhaustive operand pairs")
    mem = _mul_prog()
    hexf = os.path.join(BUILD, "mul.hex")
    image = progen.write_hex(mem, hexf)

    # Independent check: what the product should be, computed in Python.
    lo = hi = 0
    for aa in range(256):
        for bb in range(256):
            p = aa * bb
            lo = ((lo << 1) + (p & 0xFF) + (lo >> 7)) & 0xFF
            hi = ((hi << 1) + ((p >> 8) & 0xFF) + (hi >> 7)) & 0xFF

    t0 = time.time()
    emu_t = os.path.join(BUILD, "mul.emu")
    n, emu_mem = model_trace(image, hexf, emu_t)
    rtl_m = os.path.join(BUILD, "mul.rtlmem")
    run_sim(vvp, [f"+hex={hexf}", f"+memdump={rtl_m}", "+maxcycles=200000000"])
    rtl_mem = read_memdump(rtl_m)

    a = progen.ABSV
    ok = (rtl_mem[a] == emu_mem[a] == lo and
          rtl_mem[a + 1] == emu_mem[a + 1] == hi)
    print(f"  checksum python ${hi:02X}{lo:02X}  "
          f"emu ${emu_mem[a+1]:02X}{emu_mem[a]:02X}  "
          f"rtl ${rtl_mem[a+1]:02X}{rtl_mem[a]:02X} : "
          f"{'ok' if ok else 'FAIL'} ({time.time() - t0:.0f}s, "
          f"{n} instructions)")
    return ok


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", nargs="?", default="all",
                    choices=["directed", "random", "interrupts", "bus",
                             "spram", "mul", "all"])
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--count", type=int, default=3000)
    args = ap.parse_args()

    vvp = build_sim()
    ok = True
    if args.what in ("directed", "all"):
        ok &= test_directed(vvp, [0, 1, "r"])
    if args.what in ("random", "all"):
        ok &= test_random(vvp, range(1, args.seeds + 1), args.count)
    if args.what in ("interrupts", "all"):
        ok &= test_interrupts(vvp)
    if args.what in ("bus", "all"):
        ok &= test_bus(vvp)
    if args.what in ("spram", "all"):
        ok &= test_spram(vvp)
    if args.what == "mul":
        ok &= test_mul(vvp)

    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
