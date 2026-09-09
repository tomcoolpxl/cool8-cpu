#!/usr/bin/env python3
"""The CoolAction! compiler, on the machine.

    python sim/test_action.py

Three questions, and a fourth that guards the other three:

- **Does the language do what docs/15-action.md says?** One program
  exercises every construct and leaves its answers in global arrays,
  which are read back by symbol. A wrong answer names the construct.
- **Is it fast?** sw/bench/sieve.act is sw/bench/sieve.bas statement
  for statement, and the clocks are reported beside the compiled BASIC
  figure sim/test_bas.py gates against (3,069,408).
- **Does a real program talk to the hardware?** demos/primes.act writes
  its answer to the UART, so the session machine's `said()` is the
  check -- the batch machine has no peripherals to write to.
- **Does the compiler's assembler agree with the project's?** Every
  program here is assembled a second time by tools/cool8asm.py from
  the compiler's own `--asm` output, and the bytes must be identical.
  The Rust assembler's table is generated from the same opcodes.py;
  this is what catches the logic around it drifting.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))
import cool8rsvm as vm                                   # noqa: E402

BASIC_SIEVE = 3_069_408        # sim/test_bas.py's golden for sieve.bas


def same_bytes(name, prg):
    """The compiler's assembly through tools/cool8asm.py, byte for byte."""
    code, _ = H.assemble(os.path.join(H.BUILD, name + ".asm"), name=name + "_py")
    check(bytes(code) == bytes(prg[2:]),
          "%s: Rust and Python assemblers agree on %d bytes" % (name, len(code)),
          "differ at byte %d" % next(
              (i for i, (a, b) in enumerate(zip(code, prg[2:])) if a != b),
              min(len(code), len(prg) - 2)))


def run(prg, budget=50_000_000):
    m = H.session()
    why = H.run_act(m, prg, budget=budget)
    return m, why


FEATURES = r'''
; every construct once; the answers land in out() and wout()
BYTE ARRAY out(64)
CARD ARRAY wout(32)
BYTE probe = $7000
CONST K = 7
TYPE Hero = [CARD x, y BYTE hp]
Hero h
Hero POINTER hp
BYTE ARRAY tab(4) = [1 2 3 4]
BYTE ARRAY msg = "Hi!"
CARD ARRAY cw(3) = [$1234 $5678 300]
CARD counter

FUNC BYTE Side()
  counter += 1
RETURN (1)

FUNC CARD Fact(BYTE n)
  IF n <= 1 THEN RETURN (1) FI
RETURN (n * Fact(n - 1))

PROC Fill(BYTE POINTER p, BYTE n, BYTE v)
  WHILE n > 0 DO
    *p = v
    p += 1
    n -= 1
  OD
RETURN

FUNC INT Neg(INT v)
RETURN (-v)

PROC Main()
  BYTE b, i
  BYTE q = [6]
  CARD c
  INT s
  BYTE ARRAY loc(4)
  BYTE POINTER p

  b = 200
  b += 100              ; wraps
  out(0) = b            ; 44
  wout(0) = 300 * 3     ; folded, 900
  c = b * 10            ; MUL 8x8
  wout(1) = c           ; 440
  c = 1000
  wout(2) = c / 7       ; 142
  wout(3) = c % 7       ; 6
  b = 250
  out(1) = b / 7        ; 35
  out(2) = b % 7        ; 5
  s = -100
  wout(4) = s / 7       ; -14
  wout(16) = s % 7      ; -2
  c = 1
  c <<= 9
  wout(17) = c          ; 512
  b = 255
  b >>= 3
  out(28) = b           ; 31
  i = 3
  wout(18) = 5 << i     ; 40
  c = 1024
  wout(19) = c >> i     ; 128
  out(3) = b < 40       ; 1
  s = -5
  out(4) = s < 3        ; 1, signed
  c = $8000
  out(5) = c > 1        ; 1, unsigned
  counter = 0
  IF 0 AND Side() THEN out(6) = 9 FI
  IF 1 OR Side() THEN FI
  IF 1 AND Side() THEN out(6) = 1 FI
  wout(20) = counter    ; 1: short-circuit
  b = 5
  IF b == 1 THEN out(7) = 1 ELSEIF b == 5 THEN out(7) = 2 ELSE out(7) = 3 FI
  i = 0
  WHILE 1 DO
    i += 1
    IF i == 9 THEN EXIT FI
  OD
  out(8) = i            ; 9
  i = 0
  DO i += 2 UNTIL i >= 7 OD
  out(9) = i            ; 8
  c = 0
  FOR i = 1 TO 10 DO c += i OD
  wout(5) = c           ; 55
  c = 0
  FOR i = 10 TO 1 STEP -1 DO c += i OD
  wout(6) = c           ; 55
  b = 0
  FOR i = 0 TO 10 STEP 3 DO b += 1 OD
  out(10) = b           ; 4
  c = 300
  out(11) = tab(3)      ; 4
  loc(2) = 9
  out(12) = loc(2)      ; 9
  loc(c - 298) = 7
  out(13) = loc(2)      ; 7
  wout(7) = cw(1)       ; $5678
  cw(2) += 1
  wout(8) = cw(2)       ; 301
  p = out + 20
  *p = 42
  p += 1
  *p = 43
  Fill(out + 40, 3, 9)
  h.x = 1000
  h.hp = 3
  hp = &h
  hp.y = hp.x + 1
  wout(9) = h.y         ; 1001
  out(14) = hp.hp       ; 3
  out(15) = msg(0)      ; 3
  out(16) = msg(1)      ; 'H'
  out(17) = K * 2       ; 14
  probe = 77
  wout(10) = Fact(5)    ; 120
  ASM
    MOV  R0,#$5A
    ST   [v_out+18],R0
  ENDASM
  out(19) = q           ; 6
  out(21) = 5
  out(21) *= 3          ; 15
  p = out + 22
  *p = 2
  *p <<= 2              ; 8
  out(23) = NOT (i == 100)   ; 1
  b = 31
  out(24) = b ^ $FF     ; 224
  wout(11) = Neg(3)     ; -3
  c = 60000
  IF c > 30000 THEN out(25) = 1 FI
  s = -30000
  IF s < 100 THEN out(26) = 1 FI
  c = 300
  wout(12) = c * 200    ; 60000, mul16
  c = 60000
  wout(13) = c / 16     ; 3750, a shift
  b = 100
  out(27) = b % 8       ; 4, a mask
  i = 4
  c = 3
  c <<= i
  wout(14) = c          ; 48
  s = -64
  s >>= 2
  wout(15) = s          ; -16, arithmetic
  wout(21) = Neg(-7)    ; 7
  out(29) = 'A'         ; 65
  s = -1
  IF s >= 0 THEN out(30) = 1 ELSE out(30) = 2 FI    ; 2
  c = 65535
  c += 1
  wout(22) = c          ; 0, wraps
  out(31) = h.hp + tab(1)   ; 5
RETURN
'''


def test_features():
    print("  the language, one construct at a time")
    prg, syms = H.build_act(FEATURES, "act_features")
    same_bytes("act_features", prg)
    m, why = run(prg)
    check(why == "halt", "features: ran to the HALT", why)
    check(m.cpu.sp == 0x0200, "features: stack neutral", "SP $%04X" % m.cpu.sp)

    out = m.bus.mem[syms["v_out"]:syms["v_out"] + 64]
    wo = m.bus.mem[syms["v_wout"]:syms["v_wout"] + 64]

    def w(i):
        return wo[2 * i] | (wo[2 * i + 1] << 8)

    for i, want, what in [
        (0, 44, "BYTE add wraps"), (1, 35, "BYTE / BYTE"), (2, 5, "BYTE % BYTE"),
        (3, 1, "BYTE <"), (4, 1, "INT < signed"), (5, 1, "CARD > unsigned"),
        (6, 1, "AND as a condition"), (7, 2, "ELSEIF"), (8, 9, "WHILE with EXIT"),
        (9, 8, "DO UNTIL"), (10, 4, "FOR STEP 3"), (11, 4, "initialised BYTE ARRAY"),
        (12, 9, "local array"), (13, 7, "local array, computed index"),
        (14, 3, "record field through a POINTER"), (15, 3, "string length byte"),
        (16, ord("H"), "string character"), (17, 14, "CONST"),
        (18, 0x5A, "ASM block"), (19, 6, "local =[init]"), (20, 42, "*p ="),
        (21, 15, "arr(i) *="), (22, 8, "*p <<="), (23, 1, "NOT"),
        (24, 224, "XOR"), (25, 1, "CARD > 30000"), (26, 1, "INT < 100"),
        (27, 4, "BYTE % 8 as a mask"), (28, 31, "BYTE >>="), (29, 65, "'A'"),
        (30, 2, "INT >= 0 on -1"), (31, 5, "record byte + array byte"),
        (30 + 0, 2, "ELSE"),
    ]:
        check(out[i] == want, "  %s" % what, "out(%d) = %d, want %d" % (i, out[i], want))
    check(out[40:43] == b"\x09\x09\x09" and out[43] == 0,
          "  Fill() through a pointer parameter", out[40:44].hex())
    for i, want, what in [
        (0, 900, "constant folding into a word"), (1, 440, "MUL 8x8"),
        (2, 142, "CARD / 7"), (3, 6, "CARD % 7"), (4, (-14) & 0xFFFF, "INT / 7"),
        (16, (-2) & 0xFFFF, "INT % 7"), (17, 512, "CARD <<= 9"),
        (18, 40, "5 << i"), (19, 128, "CARD >> i"), (20, 1, "short-circuit AND/OR"),
        (5, 55, "FOR 1 TO 10"), (6, 55, "FOR 10 TO 1 STEP -1"),
        (7, 0x5678, "initialised CARD ARRAY"), (8, 301, "CARD ARRAY element +="),
        (9, 1001, "record field via pointer, read and write"),
        (10, 120, "recursive FUNC"), (11, (-3) & 0xFFFF, "unary minus"),
        (12, 60000, "16x16 multiply"), (13, 3750, "CARD / 16"), (14, 48, "CARD <<= var"),
        (15, (-16) & 0xFFFF, "INT >>= 2 keeps the sign"), (21, 7, "-(-7)"),
        (22, 0, "CARD wraps at 65536"),
    ]:
        check(w(i) == want, "  %s" % what, "wout(%d) = %d, want %d" % (i, w(i), want))
    check(m.bus.mem[0x7000] == 77, "  a variable bound to an address",
          "$7000 = %d" % m.bus.mem[0x7000])
    print()


def test_sieve():
    print("  the Byte sieve, 8190")
    prg, syms = H.build_act("sw/bench/sieve.act", "act_sieve")
    same_bytes("act_sieve", prg)
    m, why = run(prg)
    check(why == "halt", "sieve: ran to the HALT", why)
    c = m.bus.mem[syms["v_c"]] | (m.bus.mem[syms["v_c"] + 1] << 8)
    check(c == 1899, "sieve: 1899 primes", "got %d" % c)
    cyc = m.cpu.cycles
    print("    %s clocks; compiled BASIC takes %s (%.1fx); %d bytes of code"
          % (f"{cyc:,}", f"{BASIC_SIEVE:,}", BASIC_SIEVE / cyc, len(prg) - 2))
    check(cyc < BASIC_SIEVE, "sieve: faster than the compiled BASIC")
    print()


def test_primes():
    print("  demos/primes.act, talking to the UART")
    prg, _ = H.build_act("demos/primes.act", "act_primes")
    same_bytes("act_primes", prg)
    m, why = run(prg)
    check(why == "halt", "primes: ran to the HALT", why)
    said = m.said().decode("latin-1")
    check(said == "Primes: 168\n", "primes: said 'Primes: 168'", repr(said))

    # the library and a program as one text, which is how a game is built
    prg, syms = H.build_act(H.ACT_LIB + ["demos/primes.act"], "act_both")
    same_bytes("act_both", prg)
    m, why = run(prg)
    check(why == "halt" and m.said() == b"Primes: 168\n" and "VFill" in syms,
          "primes: the same, compiled behind the library", why)
    print()


def test_library():
    print("  sw/io.act and sw/libaction.act")
    prg, syms = H.build_act(H.ACT_LIB, "act_lib")
    same_bytes("act_lib", prg)
    for name in ("VFill", "Plot", "Line", "Clg", "SetPalette", "FlipBuffer",
                 "SetTile", "SetSprite", "Sound", "WaitVBlank", "Print"):
        check(name in syms, "library: %s is a routine" % name)
    # the library declares no address of its own: every register name
    # it uses resolves to the generated file's binding
    prg2, why = H.try_build_act("sw/libaction.act", "act_lib_alone")
    check(prg2 is None and "undefined variable" in why,
          "library: names no register itself -- it does not compile without sw/io.act",
          "compiled" if prg2 else why)
    print("    %d bytes" % (len(prg) - 2))
    print()


HARDWARE = r'''
; every routine that touches a register, then the machine is asked
; what it saw -- VRAM, the palette, the sprite and sound arrays, the
; registers themselves, and the UART
CARD ARRAY pal(2) = [$0F0 $00F]
BYTE ARRAY out(8)

PROC Main()
  Graphics(4)
  Cursor(0)
  Clg(3)                        ; 4 bpp: every byte $33
  Plot(10, 20, 5)
  Plot(11, 20, 6)               ; the same byte, both nibbles
  HLine(0, 0, 4, 1)
  VLine(0, 100, 2, 2)
  SetTile(3, 2, 7, 9)           ; through the VRAM port, as a map entry
  SetColor(1, $F00)
  SetPalette(pal, 2, 2)
  Sound(1, 881, 12, 0)
  Border(7)
  SetSprite(3, 100, 200, $8020, 1, $40)
  SpritesOn(2)
  out(2) = Key()
  out(3) = Key()
  out(0) = Frame()
  WaitVBlank()
  out(1) = Frame()
  DoubleBuffer($00, $60)
  FlipBuffer()
  PrintE("OK")
RETURN
'''


def test_hardware():
    """The library against the machine, not against its own source.

    The first library compiled, was measured and passed every gate with
    seventeen wrong addresses, because no test ever ran it -- every
    check here reads back what the *hardware* holds after the call, so
    a routine that writes the right value to the wrong register fails
    by name.
    """
    import ioregs
    print("  the library, on the hardware")
    prg, syms = H.build_act(H.ACT_LIB + [HARDWARE], "act_hw")
    same_bytes("act_hw", prg)
    m = H.session()
    m.scancode([0x1C])                     # one make code queued
    why = H.run_act(m, prg, budget=4_000_000)
    check(why == "halt", "hardware: ran to the HALT (WaitVBlank returned)", why)
    check(m.cpu.sp == 0x0200, "hardware: stack neutral", "SP $%04X" % m.cpu.sp)
    reg = lambda n: m.bus.read(ioregs.addr_of(n))   # noqa: E731

    check(reg("VID_MODE") == 0x84, "Graphics(4): mode 4 with display enable",
          "VID_MODE $%02X" % reg("VID_MODE"))
    check(reg("CUR_CTRL") == 0x10, "Cursor(0): enable off, rate kept",
          "CUR_CTRL $%02X" % reg("CUR_CTRL"))

    vr = bytes(m.video.vram[0:38400])
    want = bytearray(b"\x33" * 38400)
    want[20 * 160 + 5] = 0x56
    want[0] = want[1] = 0x11
    want[100 * 160] = want[101 * 160] = 0x23
    want[2 * 128 + 6], want[2 * 128 + 7] = 7, 9
    bad = [i for i in range(38400) if vr[i] != want[i]]
    check(not bad, "Clg, Plot, HLine, VLine, SetTile: VRAM holds exactly what was drawn",
          "%d bytes differ; first at %d: got %02X want %02X"
          % (len(bad), bad[0] if bad else 0, vr[bad[0]] if bad else 0,
             want[bad[0]] if bad else 0))

    p = m.palette()
    check(p[1] == 0x0F00 and p[2] == 0x00F0 and p[3] == 0x000F,
          "SetColor, SetPalette: entries 1-3 are $F00 $0F0 $00F",
          "%03X %03X %03X" % (p[1], p[2], p[3]))
    s = m.sound()
    check(s[8] == 881 & 0xFF and s[9] == 881 >> 8 and s[12] == 12 and s[13] == 0x40,
          "Sound(1, 881, 12, 0): voice 1 programmed", s[8:14].hex())
    check(reg("VID_BORDER") == 7, "Border(7)", "VID_BORDER %d" % reg("VID_BORDER"))
    d = m.sprites()[24:32]
    check(bytes(d) == bytes([200, 0xC0, 100, 0, 0x01, 4, 0x40, 0]),
          "SetSprite(3, 100, 200, $8020, 1, $40): descriptor 3", d.hex())
    check(reg("SPR_CTRL") == 0x21, "SpritesOn(2): engine on, bank 2",
          "SPR_CTRL $%02X" % reg("SPR_CTRL"))

    out = m.bus.mem[syms["v_out"]:syms["v_out"] + 8]
    check(out[2] == 0x1C and out[3] == 0, "Key(): the queued scancode, then 0",
          "%02X %02X" % (out[2], out[3]))
    check(out[1] == (out[0] + 1) & 0xFF,
          "WaitVBlank(): returned on the very next frame",
          "frame %d before, %d after" % (out[0], out[1]))
    check(reg("VID_DBASE_H") == 0x60 and reg("VID_BASE_H") == 0x00
          and reg("VID_CTRL") & 0x40,
          "DoubleBuffer($00, $60) then FlipBuffer(): showing $60, drawing $00, bit 6 set",
          "DBASE_H $%02X BASE_H $%02X CTRL $%02X"
          % (reg("VID_DBASE_H"), reg("VID_BASE_H"), reg("VID_CTRL")))
    check(m.said() == b"OK\r\n", "PrintE: said OK", repr(m.said()))
    print()


def test_refusals():
    print("  what the compiler refuses, and how it says so")
    cases = [
        ("PROC Main()\n  x = 1\nRETURN", "undefined variable 'x'", "an undefined name"),
        ("PROC Main()\n  BYTE b\n  b = Nope(1)\nRETURN", "undefined routine", "an undefined routine"),
        ("PROC Main()\n  IF 1 THEN\nRETURN", "expected", "a block left open"),
        ("BYTE ARRAY a(4)\nPROC Main()\n  a = 1\nRETURN", "whole array", "assigning a whole array"),
        ("PROC P(BYTE a)\nRETURN\nPROC Main()\n  P(1, 2)\nRETURN", "takes 1 argument", "an arity mismatch"),
        ("PROC Main()\n  EXIT\nRETURN", "EXIT outside", "EXIT outside a loop"),
        ("PROC Main()\n  BYTE b\n  b = 10 % \nRETURN", "unexpected", "a dangling operator"),
    ]
    for src, want, what in cases:
        prg, why = H.try_build_act(src, "act_bad")
        ok = prg is None and want in why and "line" in why
        check(ok, "  refuses %s, naming the line" % what,
              "compiled" if prg is not None else why)
    prg, _ = H.try_build_act("PROC Main()\nRETURN", "act_org", org=0x0400)
    check(prg is not None and prg[:2] == b"\x00\x04", "  --org $0400 lands in the PRG header")
    print()


def test_every_encoding():
    """Every encoding the ISA has, rendered by tools/opcodes.py's own
    disassembler, through both assemblers. The Rust table is generated
    from opcodes.py; this is the logic around it -- operand
    normalisation, expressions, displacements -- held to the same
    bytes. A count is printed so a new encoding that neither accepts
    is a visible number, not a silent skip."""
    import opcodes
    print("  the compiler's assembler, on every encoding")
    lines, expect, pc = ["        .org $0200"], bytearray(), 0x0200
    n = 0
    for op in range(256):
        if op == 0x2F:
            continue
        buf = [op, 0x12, 0x34]
        text, ln = opcodes.disassemble(lambda a, b=buf, p=pc: b[a - p], pc)
        lines.append("        " + text)
        expect += bytes(buf[:ln])
        pc += ln
        n += 1
    for op2 in sorted(opcodes.page2):
        buf = [0x2F, op2, 0x12, 0x34]
        text, ln = opcodes.disassemble(lambda a, b=buf, p=pc: b[a - p], pc)
        lines.append("        " + text)
        expect += bytes(buf[:ln])
        pc += ln
        n += 1
    text = "\n".join(lines) + "\n"
    org, rs = H.assemble_act(text, "act_isa")
    check(org is not None, "every encoding: the Rust assembler accepts the whole ISA",
          str(rs)[:400])
    if org is None:
        return
    py, _ = H.assemble(os.path.join(H.BUILD, "act_isa.asm"), name="act_isa_py")
    check(bytes(rs) == bytes(expect), "every encoding: %d encodings re-encode to their own bytes" % n,
          "first difference at byte %d" % next(
              (i for i, (a, b) in enumerate(zip(rs, expect)) if a != b), min(len(rs), len(expect))))
    check(bytes(py) == bytes(expect), "every encoding: tools/cool8asm.py agrees")
    have = 255 + len(opcodes.page2)
    check(n == have, "every encoding: %d of %d assigned encodings tried" % (n, have))

    # the aliases, against what docs/08-assembler.md says they expand to
    alias = "\n".join("        " + l for l in [
        "SHL R0", "ROL R1", "CLR R2", "TST R3", "SEXC R0", "INC R1", "DEC R2",
        "BHS *+2", "BLO *+2", "BZ *+2", "BNZ *+2", "BN *+2", "BP *+2",
    ])
    plain = "\n".join("        " + l for l in [
        "ADD R0,R0", "ADC R1,R1", "SUB R2,R2", "OR R3,R3", "SBC R0,R0", "ADD R1,#1", "SUB R2,#1",
        "BCS *+2", "BCC *+2", "BEQ *+2", "BNE *+2", "BMI *+2", "BPL *+2",
    ])
    _, a = H.assemble_act("        .org $0200\n" + alias + "\n", "act_alias")
    _, b = H.assemble_act("        .org $0200\n" + plain + "\n", "act_plain")
    check(a == b and a is not None, "every encoding: the 13 aliases expand as documented")

    # relaxation: a branch that cannot reach grows the way cool8asm's does
    far = "        .org $0200\n        BEQ far\n        BRA far\n        .space 300\nfar:    NOP\n"
    _, a = H.assemble_act(far, "act_far")
    b, _ = H.assemble(os.path.join(H.BUILD, "act_far.asm"), name="act_far_py")
    check(a is not None and bytes(a) == bytes(b), "every encoding: out-of-range branches relax identically")
    print()


def profile_sieve():
    """`--profile`: where the sieve's clocks go, by loop label. The
    labels are the compiler's own (.do, .wh, .od ...), qualified by
    routine, so the report names the loop rather than the routine."""
    prg, syms = H.build_act("sw/bench/sieve.act", "act_sieve")
    m = H.session()
    org, end = H.load_act(m, prg)
    p = dbg.Profile(syms, org, end)
    p.run(m)
    print(p.report(top=12, roll=False))
    return 0


def main():
    if "--profile" in sys.argv:
        return profile_sieve()
    print("  A2 -- CoolAction! on the machine")
    print()
    test_every_encoding()
    test_features()
    test_sieve()
    test_primes()
    test_library()
    test_hardware()
    test_refusals()
    return H.report()


if __name__ == "__main__":
    sys.exit(main())
