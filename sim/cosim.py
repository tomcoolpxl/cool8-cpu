#!/usr/bin/env python3
"""COOL8 RTL co-simulation — the RTL against the reference emulator.

The emulator (tools/cool8emu.py) is the executable specification. This
runs the same program through it and through the Verilog, each emitting
one line of full architectural state per retired instruction, and reports
the first line where they disagree together with the disassembly of the
instruction that caused it.

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
import cool8emu                             # noqa: E402
import progen                               # noqa: E402

RTL = [os.path.join(ROOT, "rtl", "core", f)
       for f in ("cool8_alu.v", "cool8_agu.v", "cool8_core.v")]
TB = os.path.join(HERE, "tb", "cool8_tb.v")
PADS = os.path.join(ROOT, "rtl", "pads", "tt_um_cool8.v")
BUSTB = os.path.join(HERE, "tb", "cool8_bus_tb.v")
SPRAM = os.path.join(ROOT, "rtl", "soc", "cool8_spram.v")
SPRAMTB = os.path.join(HERE, "tb", "cool8_spram_cpu_tb.v")


# ------------------------------------------------------------- toolchain

def _with_libs(root, path):
    """Put the toolchain's own directories on PATH before running it.

    Every suite here says "set OSS_CAD_SUITE if it is not on PATH", and
    that was not quite true: an absolute path finds the executable, but
    `vvp` then loads `libvvp-1.dll` beside itself and Windows resolves
    that against PATH. Setting the variable alone gave a process that
    died with 0xC0000135 and no output at all, which reads like a
    simulator that produced nothing rather than one that never started.
    """
    for d in (os.path.join(root, "bin"), os.path.join(root, "lib")):
        if os.path.isdir(d) and d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    return path


def _tool(name):
    root = os.environ.get("OSS_CAD_SUITE")
    if root:
        cand = os.path.join(root, "bin", name + ".exe")
        if os.path.exists(cand):
            return _with_libs(root, cand)
        cand = os.path.join(root, "bin", name)
        if os.path.exists(cand):
            return _with_libs(root, cand)
    found = shutil.which(name)
    if not found:
        sys.exit(f"{name} not found. Put the OSS CAD Suite on PATH or set "
                 f"OSS_CAD_SUITE to its root directory.")
    return found


def ice40_cells():
    """The toolchain's own SB_* simulation models.

    Not vendored into the repository: the models must match the yosys
    that maps the design, and a stale copy of a memory primitive is a bug
    that looks like an RTL bug.
    """
    roots = []
    if os.environ.get("OSS_CAD_SUITE"):
        roots.append(os.environ["OSS_CAD_SUITE"])
    roots.append(os.path.dirname(os.path.dirname(_tool("yosys"))))
    for r in roots:
        cand = os.path.join(r, "share", "yosys", "ice40", "cells_sim.v")
        if os.path.exists(cand):
            return cand
    sys.exit("ice40 cells_sim.v not found; set OSS_CAD_SUITE to the "
             "toolchain root")


def _build(name, tb, sources, gen="2005"):
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, name + ".vvp")
    newest = max(os.path.getmtime(f) for f in sources + [tb])
    if os.path.exists(out) and os.path.getmtime(out) > newest:
        return out
    subprocess.run([_tool("iverilog"), "-g" + gen, "-Wall", "-Wno-timescale",
                    "-o", out, tb] + sources, check=True)
    return out


def build_sim():
    return _build("cool8_tb", TB, RTL)


def build_bus_sim():
    return _build("cool8_bus_tb", BUSTB, RTL + [PADS])


def build_spram_sim():
    # -g2012 only because yosys's cells_sim.v uses default port values.
    # Everything in rtl/ is still Verilog-2001 and is compiled as such by
    # sim/synth.py and by every other build here.
    return _build("cool8_spram_cpu_tb", SPRAMTB,
                  RTL + [SPRAM, ice40_cells()], gen="2012")


def run_sim(vvp_file, args):
    r = subprocess.run([_tool("vvp"), vvp_file] + args,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("simulator failed")
    return r.stdout


# --------------------------------------------------------------- emulator

def emu_trace(image, path, max_instr=0, events=None):
    """Run the emulator, writing the same state line the testbench does.

    `events` maps a retired-instruction count to an action on the CPU,
    applied immediately after that instruction retires and before the
    halt check — so an event aimed at a halted machine still fires.
    """
    bus = cool8emu.Bus()
    bus.mem[:] = image
    cpu = cool8emu.Cool8(bus)
    ev = dict(events or {})
    n = 0
    if 0 in ev:
        ev[0](cpu)
    with open(path, "w") as f:
        while True:
            before = cpu.instructions
            cpu.step()
            if cpu.instructions != before:
                n += 1
                if n in ev:
                    ev[n](cpu)
                f.write("%04x %02x%02x%02x%02x %04x %04x %04x %02x\n" % (
                    cpu.pc, cpu.r[0], cpu.r[1], cpu.r[2], cpu.r[3],
                    cpu.x, cpu.y, cpu.sp, cpu.f))
                if max_instr and n >= max_instr:
                    break
            if cpu.halted and not (cpu.nmi_edge or (cpu.irq_line and cpu.I)):
                break
            if n > 20_000_000:
                raise SystemExit("emulator runaway")
    return n, bytes(bus.mem)


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
    n, emu_mem = emu_trace(image, emu_t, max_instr=max_instr, events=events)

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
        n, emu_mem = emu_trace(image, emu_t, events=ev)
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
        n, emu_mem = emu_trace(image, emu_t)
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
    n, emu_mem = emu_trace(image, emu_t)
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
