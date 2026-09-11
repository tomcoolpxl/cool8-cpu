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
import dbg                                               # noqa: E402

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
  s = -300
  wout(23) = s / 256    ; -1: truncation, not an arithmetic shift
  wout(24) = s % 256    ; -44: the sign of the dividend
  s = -256
  wout(25) = s / 256    ; -1
  s = 300
  wout(26) = s / 256    ; 1
  s = -1
  wout(27) = s >> 8     ; -1: the sign extends from bit 15, not from bit 0
  s = -2
  wout(28) = s / 2      ; -1
  s = -3
  wout(29) = s / 2      ; -1, towards zero
  wout(30) = s * 4      ; -12
  c = 3
  b = 0
  WHILE c > 0 DO        ; a word countdown: the test the maps found broken
    b += 1
    c -= 1
  OD
  out(32) = b           ; 3
  c = 0
  WHILE c > 0 DO b = 99 OD
  out(33) = b           ; still 3: zero passes
  c = 258
  IF c == 0 THEN out(34) = 1 ELSE out(34) = 2 FI    ; 2: both bytes count
  i = 1
  out(i + 34) = tab(i * 2 + 1)   ; 4: a value pushed and an index computed, kept apart
  out(i + 35) = 9                ; 9: and the value need not be complex, only the index
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
        (32, 3, "WHILE on a word counting down"), (33, 3, "WHILE false runs zero times"),
        (34, 2, "a word against zero tests both bytes"),
        (35, 4, "arr(expr) = arr(expr): the index is not the value -- SLIDES' LoadRpl found it"),
        (36, 9, "arr(expr) = constant"),
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
        (23, (-1) & 0xFFFF, "INT / 256 truncates towards zero, as BASIC's does"),
        (24, (-44) & 0xFFFF, "INT % 256 takes the dividend's sign"),
        (25, (-1) & 0xFFFF, "-256 / 256"), (26, 1, "300 / 256"),
        (27, (-1) & 0xFFFF, "INT >> 8 extends the sign from bit 15"),
        (28, (-1) & 0xFFFF, "-2 / 2"), (29, (-1) & 0xFFFF, "-3 / 2 truncates towards zero"),
        (30, (-12) & 0xFFFF, "INT * 4 as a shift keeps the sign"),
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
CARD ARRAY wout(8)

PROC Main()
  out(2) = Key()                  ; the bare make code queued first
  wout(0) = Rnd(0)
  wout(1) = Rnd(0)
  wout(2) = Rnd(100)
  wout(3) = ReadKey()             ; shift C, from the queue
  wout(4) = ReadKey()             ; d
  wout(5) = ReadKey()             ; the right arrow
  wout(6) = ReadKey()             ; nothing left: 0
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
  out(3) = Key()                  ; nothing left: 0
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
    # shift-C, d and the right arrow for ReadKey, then a bare make code
    # for Key() -- all queued before the program starts
    m.scancode([0x1C, 0x12, 0x21, 0xF0, 0x21, 0xF0, 0x12, 0x23, 0xF0, 0x23,
                0xE0, 0x74, 0xE0, 0xF0, 0x74])
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
    wo = m.bus.mem[syms["v_wout"]:syms["v_wout"] + 16]
    w = [wo[2 * i] | (wo[2 * i + 1] << 8) for i in range(8)]
    # the interpreter's xorshift from seed 1: s ^= s<<7, s ^= s>>9, s ^= s<<8
    s, ref = 1, []
    for _ in range(3):
        s ^= (s << 7) & 0xFFFF
        s ^= s >> 9
        s ^= (s << 8) & 0xFFFF
        ref.append(s)
    check(w[0] == ref[0] and w[1] == ref[1] and w[2] == ref[2] % 100,
          "Rnd(): the interpreter's xorshift from seed 1, and RND(n) is the remainder",
          "%d %d %d, want %d %d %d" % (w[0], w[1], w[2], ref[0], ref[1], ref[2] % 100))
    check(w[3:7] == [ord("C"), ord("d"), 259, 0],
          "ReadKey(): shift-C is C, d is d, the right arrow is K_RIGHT, then 0",
          "%s" % w[3:7])
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


def test_line():
    """`Line` against BASIC's LINE, pixel for pixel: sim/test_run.py's
    fan -- every octant, both x directions, the horizontal and vertical
    special cases, the half-step ties -- through the compiled routine,
    and the whole mode 4 frame compared with the reference that gates
    the interpreter. A tie broken the other way is one byte, and it
    fails."""
    import test_run as R
    print("  Line(), against LINE")
    flat = [v for line in R.LINE_FAN for v in line]
    src = "CARD ARRAY fan(%d) = [%s]\n" % (len(flat), " ".join(str(v) for v in flat))
    src += r'''
PROC Main()
  CARD j
  Graphics(4)
  Clg(0)
  j = 0
  WHILE j < %d DO
    Line(fan(j), fan(j + 1), fan(j + 2), fan(j + 3), fan(j + 4))
    j += 5
  OD
RETURN
''' % len(flat)
    prg, syms = H.build_act(H.ACT_LIB + [src], "act_line")
    same_bytes("act_line", prg)
    m = H.session()
    org, end = H.load_act(m, prg)
    p = dbg.Profile(syms, org, end)
    p.run(m, limit=20_000_000)
    check(0xFEF0 <= m.cpu.pc <= 0xFEF4 and m.cpu.sp == 0x0200,
          "line: ran to the HALT, stack neutral", "PC $%04X SP $%04X" % (m.cpu.pc, m.cpu.sp))
    want = R.fan_bytes()
    got = bytes(m.video.vram[0:38400])
    bad = [i for i in range(38400) if got[i] != want[i]]
    check(not bad, "line: lights exactly LINE's pixels, all octants and both ties",
          "%d bytes differ; first at %d (row %d): got %02X want %02X"
          % (len(bad), bad[0] if bad else 0, (bad[0] // 160) if bad else 0,
             got[bad[0]] if bad else 0, want[bad[0]] if bad else 0))
    npx = sum(len(R.line_ref(*l[:4])) for l in R.LINE_FAN)
    inline = sum(c for n, c in p.by.items() if n.split(".")[0] == "Line")
    print("    %d pixels, %s clocks in Line: %.0f a pixel over the fan; "
          "BASIC's LINE is 101-181" % (npx, f"{inline:,}", inline / npx))
    print()


def test_rainbow():
    """The first port, held to the original: demos/rainbow.bas on the
    interpreter and demos/rainbow.act compiled, each run the same
    number of frames -- parked at the K-th VSYNC / WaitVBlank, where a
    frame's work is whole -- and the mode 4 frame and the sixteen
    palette entries must be identical. The picture after 40 frames has
    every one of the fifteen trail lines drawn and the oldest erased
    twice over, so a Line that tied the other way, a bounce off by one,
    or a palette entry byte-swapped is a different frame."""
    import test_basic as B
    K = 40
    print("  RAINBOW: the port against the original, %d frames" % K)
    code, bsyms = B.build()
    M = B.Machine(code, bsyms)
    M.settle()
    for ln in open(os.path.join(H.ROOT, "demos", "rainbow.bas"), encoding="utf-8"):
        if ln.strip():
            H.line(M.m, bsyms, ln.rstrip("\r\n"))
    M.m.type("RUN\r")
    # **A tick between stops.** `run(until=)` checks the PC before it
    # steps, so called again from the address it stopped at it returns
    # at once: forty calls were one VSYNC, and the first version of
    # this gate compared two blank screens and passed.
    for _ in range(K):
        why = M.m.run(until=bsyms["h_vsync"], budget=60_000_000)
        M.m.tick()
    check(why == "until", "rainbow: the BASIC reached VSYNC %d times" % K,
          "%s; screen: %s" % (why, [r for r in M.m.text() if r][:4]))
    bas_vram = bytes(M.m.video.vram[0:38400])
    bas_pal = M.m.palette()[:16]
    bas_cyc = M.m.cpu.cycles
    check(sum(1 for b in bas_vram if b) > 200, "rainbow: the BASIC drew something",
          "%d lit bytes, mode %d" % (sum(1 for b in bas_vram if b), M.m.video.ctrl))

    prg, syms = H.build_act(H.ACT_LIB + ["demos/rainbow.act"], "act_rainbow")
    same_bytes("act_rainbow", prg)
    m = H.session()
    H.load_act(m, prg)
    for _ in range(K):
        why = m.run(until=syms["WaitVBlank"], budget=20_000_000)
        m.tick()
    check(why == "until", "rainbow: reached WaitVBlank %d times" % K, why)
    act_vram = bytes(m.video.vram[0:38400])
    bad = [i for i in range(38400) if act_vram[i] != bas_vram[i]]
    check(not bad, "rainbow: the same 38,400 bytes of VRAM as the BASIC after %d frames" % K,
          "%d bytes differ; first at %d (row %d): compiled %02X BASIC %02X"
          % (len(bad), bad[0] if bad else 0, (bad[0] // 160) if bad else 0,
             act_vram[bad[0]] if bad else 0, bas_vram[bad[0]] if bad else 0))
    check(m.palette()[:16] == bas_pal, "rainbow: the same sixteen palette entries",
          " ".join("%03X" % p for p in m.palette()[:16]))
    lit = sum(1 for b in act_vram if b)
    check(lit > 200, "rainbow: something is on the screen", "%d lit bytes" % lit)
    print("    %s clocks compiled against %s interpreted to the %dth frame, "
          "%d bytes of PRG" % (f"{m.cpu.cycles:,}", f"{bas_cyc:,}", K, len(prg)))
    print()


def cobra_lines(entries):
    """Lines()'s pixels for a list of (x0, y0, x1, y1), as its four loops
    choose them: the end with the smaller y first; along X rightward from
    the left end, along Y downward; the error starting at half the long
    distance and the short axis stepping when it runs out."""
    px = set()
    for x0, y0, x1, y1 in entries:
        if y0 > y1:
            x0, y0, x1, y1 = x1, y1, x0, y0
        dy, dx = y1 - y0, abs(x1 - x0)
        sx = 1 if x1 >= x0 else -1
        if dx >= dy:                        # .rx, or .lx from the lower-left end
            x, y, s = (x0, y0, 1) if sx > 0 else (x1, y1, -1)
            err = dx >> 1
            for _ in range(dx + 1):
                px.add((x, y))
                x += 1
                if err >= dy:
                    err -= dy
                else:
                    err += dx - dy
                    y += s
        else:                               # .ry and .ly, from the top
            x, y, err = x0, y0, dy >> 1
            for _ in range(dy + 1):
                px.add((x, y))
                y += 1
                if err >= dx:
                    err -= dx
                else:
                    err += dy - dx
                    x += sx
    return px


def test_cobra():
    """COBRA (demos/cobra.act, D105): Elite's Cobra Mk III tumbling on
    three axes, every frame computed between two vertical blanks. It is
    not the BASIC's twin any more, so it is held to its own claims
    rather than to demos/cobra.bas's pages:

    - a frame every vblank -- over ten seconds of the machine the loop
      runs once a frame, so no frame's work ever overran one;
    - what it draws is what its own arithmetic says: at poses along the
      tumble, the rotation and every vertex are tools/mk3d.py's integer
      pipeline's, each face's visibility is its normal through the
      program's own matrix against its threshold, agrees with its
      triangle's area on the screen wherever that area is past
      mk3d.SURE, and the page's edge list is exactly the edges
      bordering a visible face -- and the page is that list's lines,
      pixel for pixel;
    - every vertex on the screen, and the next frame on the glass is the
      finished page, never the one being drawn;
    - a page erased by drawing its last frame again in black is the page
      a clear would have left: the same frames, run once erasing and
      once clearing (the `clean` byte), leave the same two pages."""
    import mk3d
    cobra_run("cobra", "COBRA: the tumble, every frame computed",
              (mk3d.YAWR, mk3d.PITCHR, mk3d.ROLLR), mk3d.HYST, sky=False)


def test_cobra2():
    """COBRA 2 (demos/cobra2.act, D106): COBRA's ship and arithmetic at
    a sixth of its rates, read as a camera circling a ship that flies straight,
    and a sky that is fixed in the world. Every claim COBRA is held to,
    faces hysteresis on the way out only, and on top:

    - at the same poses, where Respawn() begins the page's dot list is
      exactly where tools/mk3d.py's models of the program put every star
      and speck, stars first, each in its colour, and the on-screen
      flags are those models' answers;
    - the page is the dots with the lines over them, pixel for pixel and
      colour for colour, and the glass shows it in one shade a colour;
    - over 120 consecutive frames the ship flies mk3d.SPEED a frame
      along its nose, every star on the screen keeps its direction and
      every speck its place in the world until it leaves; and what is
      recycled is back on the screen the next frame."""
    import mk3d
    cobra_run("cobra2", "COBRA 2: the camera circles, the ship flies, the sky stays put",
              mk3d.RATES2, mk3d.TURNIN2, sky=True, FR=1800)    # 77 % of a frame: thirty seconds of it


def cobra_run(name, title, rates, turn_in, sky, FR=600):
    """The claims the compiled COBRAs are held to (test_cobra,
    test_cobra2): `rates` and `turn_in` are the program's tumble and its
    faces' hysteresis on the way in, `sky` adds COBRA 2's, and a frame is
    computed in every one of FR vblanks."""
    import mk3d
    print("  " + title)
    prg, syms = H.build_act(H.ACT_LIB + ["demos/%s.act" % name], "act_" + name)
    same_bytes("act_" + name, prg)
    print("    %d bytes of PRG" % (len(prg) - 2))

    def arr(m, nm, n):
        a = syms["v_" + nm]
        return bytes(m.bus.mem[a:a + n])

    def word(m, nm):
        a = syms["v_" + nm]
        return m.bus.mem[a] | (m.bus.mem[a + 1] << 8)

    def ints(m, nm, n):
        b = arr(m, nm, 2 * n)
        return [((b[2 * j] | b[2 * j + 1] << 8) + 0x8000) % 0x10000 - 0x8000 for j in range(n)]

    m = H.session(render=True)
    org, end = H.load_act(m, prg)
    why = m.run(until=syms["WaitVBlank"], budget=40_000_000)
    check(why == "until", "%s: its mode set and both pages cleared, to the first frame wait" % name, why)
    f0, t0 = word(m, "frames"), m.frames
    p = dbg.Profile(syms, org, end)
    p.start(m)
    m.run_frame(FR)
    m.run(until=syms["WaitVBlank"], budget=2_000_000)   # the last vblank's pass finished too
    p.collect(m)
    passes, frames = word(m, "frames") - f0, m.frames - t0
    check(passes == frames, "%s: a frame computed and drawn in every one of %d vblanks -- sixty a second"
          % (name, FR), "%d passes in %d frames" % (passes, frames))
    n = max(1, passes)
    parts = [("the transform", ["Transform"]), ("the lines", ["Lines"]), ("the rotation", ["Matrix", "Row"]),
             ("culling and listing", ["Faces", "Visible"])]
    if sky:
        parts += [("the sky", ["Sky"]), ("its dots", ["Dots", "DotsAsm"]),
                  ("putting it back", ["Respawn", "Transpose", "Place", "PlaceAsm", "Store", "StarAt", "DustAt",
                                       "Rnd", "__div16", "__mod16"])]
    parts.append(("16-bit multiplies", ["__mul16"]))
    per = lambda c: "{:,}".format(int(c / n))                 # noqa: E731
    print("    a frame's work: %s clocks of 139,583 -- %s" % (
        per(p.total - p.of("WaitVBlank")),
        ", ".join("%s %s" % (per(sum(p.of(r) for r in rs if r in syms)), what) for what, rs in parts)))

    md = mk3d.act_model(rates, turn_in)
    stern = mk3d.stern_vertices()
    scr = md["scr"]                                 # each face's triangle, positive turned to the viewer
    nb = arr(m, "nb", 65)
    ea, eb, e1, e2 = (arr(m, nm, 38) for nm in ("ea", "eb", "ef1", "ef2"))
    nhid = 0
    if sky:
        sk = mk3d.sky_model()
        NS, ND = mk3d.STARS, mk3d.DUST
        dlp = (NS + ND) * 3
        rim = arr(m, "rim", 38)
        rlo, rhi = mk3d.recip_tables()
    angles = lambda: (word(m, a) * mk3d.SINES >> 16 for a in ("yaw", "pitch", "roll"))   # noqa: E731
    wrong_face = wrong_screen = wrong_list = wrong_mat = wrong_proj = wrong_px = wrong_glass = off = 0
    wrong_sky = 0
    first_px = first_sky = ""
    counts, ndots = [], []
    for _ in range(12):
        m.run_frame(23)
        m.run(until=syms["Faces"], budget=2_000_000)
        was = arr(m, "fv", 13)                              # the faces as the last frame left them
        dots = []
        if sky:
            # the sky as Sky() leaves it for Respawn(): where the models say
            m.run(until=syms["Respawn"], budget=2_000_000)
            cur = m.bus.mem[syms["v_cur"]]
            mat = md["matrix"](*angles())
            sd, sc, sv = arr(m, "sd", NS * 5), arr(m, "sc", NS), arr(m, "sv", NS)
            dw, sh, dv = ints(m, "dw", ND * 3), ints(m, "sh", 3), arr(m, "dv", ND)
            # the ship's outline, as Visible() lists it and as the model makes it
            fv0, sx0, sy0 = arr(m, "fv", 13), arr(m, "sx", 28), arr(m, "sy", 28)
            sil = [(sx0[ea[e]], sy0[ea[e]], sx0[eb[e]], sy0[eb[e]]) for e in range(38)
                   if rim[e] and fv0[e1[e]] != fv0[e2[e]]]
            raw = arr(m, "sl", 152)[:4 * m.bus.mem[syms["v_sln"]]]
            have_sil = [tuple(raw[j:j + 4]) for j in range(0, len(raw), 4)]
            recs, box = mk3d.outline(sil, rlo, rhi)
            want, fs, fd = [], [], []
            for i in range(NS):
                s = mk3d.star_screen(mat, [b - 128 for b in sd[5 * i:5 * i + 3]], sk["srz"])
                fs.append(1 if s else 0)
                if s and mk3d.hidden(recs, box, s[0], s[1]):
                    nhid += 1
                elif s:
                    want.append((s[0], s[1], sc[i]))
            for i in range(ND):
                p = mk3d.dust_rel(dw[3 * i:3 * i + 3], sh)     # its place from the ship, or past reach
                t = mk3d.dust_screen(mat, p, sk["drz"]) if p else None
                fd.append(1 if t else 0)
                if t and t[3] >= 0 and mk3d.hidden(recs, box, t[0], t[1]):
                    nhid += 1                   # behind the ship's centre, inside its outline
                elif t:
                    want.append((t[0], t[1], 4 if t[2] else 5))
            k = m.bus.mem[syms["v_dn"] + cur]
            raw = arr(m, "dl", 2 * dlp)[cur * dlp:cur * dlp + 3 * k]
            dots = [tuple(raw[j:j + 3]) for j in range(0, len(raw), 3)]
            if (dots != want or list(sv) != fs or list(dv) != fd or have_sil != sil
                    or any(y > 239 for _, y, _ in dots)):
                wrong_sky += 1
                if not first_sky:
                    first_sky = "list %s, models %s; flags %s %s" % (dots[:4], want[:4], list(sv) == fs,
                                                                     list(dv) == fd)
            ndots.append(len(dots))
        m.run(until=syms["WaitVBlank"], budget=2_000_000)   # this frame's page complete
        sx, sy, fv = arr(m, "sx", 28), arr(m, "sy", 28), arr(m, "fv", 13)
        mz = [b - 128 for b in arr(m, "mp", 9)[6:9]]      # the matrix's Z row, signed
        cur = m.bus.mem[syms["v_cur"]]
        mat = md["matrix"](*angles())
        wrong_mat += list(arr(m, "mp", 9)) != [e + 128 for row in mat for e in row]
        # COBRA 2 works out the stern's panel vertices only while the stern is shown
        keep = [v for v in range(28) if not ("v_vd" in syms and not fv[mk3d.STERN] and stern[v])]
        proj = md["project"](mat)
        wrong_proj += [(sx[v], sy[v]) for v in keep] != [proj[v] for v in keep]
        for f in range(13):
            n = [b - 128 for b in nb[5 * f:5 * f + 3]]
            t = ((nb[5 * f + 3] | nb[5 * f + 4] << 8) - 128 * sum(n) + 0x8000) % 0x10000 - 0x8000
            q = sum(a * b for a, b in zip(mz, n)) - t
            wrong_face += (q - mk3d.HYST < 0 if was[f] else q + turn_in < 0) != bool(fv[f])
            (xa, ya), (xb, yb), (xc, yc) = ((sx[v], sy[v]) for v in scr[f])
            area = ((xb - xa) >> 1) * ((yc - ya) >> 1) - ((yb - ya) >> 1) * ((xc - xa) >> 1)
            wrong_screen += abs(area) > mk3d.SURE and (area > 0) != bool(fv[f])
        edges = [e for e in range(38) if fv[e1[e]] or fv[e2[e]]]
        lst = []
        for e in edges:
            lst += [sx[ea[e]], sy[ea[e]], sx[eb[e]], sy[eb[e]]]
        nl = m.bus.mem[syms["v_nl"] + cur]
        have = arr(m, "lst", 304)[cur * 152:cur * 152 + 4 * nl]
        wrong_list += have != bytes(lst)
        # the page drawn is exactly its dots and then its list's lines,
        # pixel for pixel and colour for colour
        base = m.bus.mem[syms["v_pg"] + cur] << 8
        page = bytes(m.video.vram[base:base + 30720])
        colour = {}
        for i, b in enumerate(page):
            if b:
                y, xb = divmod(i, 128)
                if b >> 4:
                    colour[(2 * xb, y)] = b >> 4
                if b & 15:
                    colour[(2 * xb + 1, y)] = b & 15
        want = {(x, y): c for x, y, c in dots}
        for xy in cobra_lines([tuple(have[j:j + 4]) for j in range(0, len(have), 4)]):
            want[xy] = 1
        if colour != want:
            wrong_px += 1
            if not first_px:
                extra = sorted(xy for xy in colour if colour[xy] != want.get(xy))
                lost = sorted(xy for xy in want if xy not in colour)
                first_px = "%d pixels lit off the picture or in the wrong colour, %d missing: %s %s" % (
                    len(extra), len(lost), extra[:4], lost[:4])
        off += sum(1 for y in sy if y > 239)
        counts.append(len(edges))
        # and the next frame on the glass is that page, whole: not the one
        # being erased and drawn. This stop is mid-frame and the frame it
        # is in scans the page latched at its start, so the first frame
        # from this page is the one after (mode 6's picture starts 64
        # pixels in, every pixel doubled both ways); one shade a colour
        m.run_frame(2)
        fb = m.fb()
        glass = {(x, y): fb[2 * y * 640 + 64 + 2 * x] for y in range(240) for x in range(256)
                 if fb[2 * y * 640 + 64 + 2 * x] != 0}
        shade = {}
        wrong_glass += set(glass) != set(colour) or any(
            shade.setdefault(c, glass.get(xy)) != glass.get(xy) for xy, c in colour.items())
    tag = name + ":"
    check(not wrong_face, "%s at 12 poses, every face's visibility is its normal through the program's "
          "own matrix against its threshold, %d of hysteresis on the way out, %d on the way in"
          % (tag, mk3d.HYST, turn_in), "%d faces wrong" % wrong_face)
    check(not wrong_screen, "%s and agrees with its triangle on the screen wherever the area is past %d"
          % (tag, mk3d.SURE), "%d faces disagree" % wrong_screen)
    check(not wrong_list, "%s and each page's list is exactly the edges bordering a visible face, %d-%d of them"
          % (tag, min(counts), max(counts)), "%d lists wrong" % wrong_list)
    check(not off, "%s every vertex on the screen" % tag, "%d below it" % off)
    check(not wrong_mat, "%s the rotation is tools/mk3d.py's, entry for entry" % tag,
          "%d poses differ" % wrong_mat)
    check(not wrong_proj, "%s and every vertex lands where its integer pipeline puts it" % tag,
          "%d poses differ" % wrong_proj)
    if sky:
        check(not wrong_sky, "%s and every star and speck lands where tools/mk3d.py's models of Sky() put "
              "them, in their colours, %d-%d dots a frame -- and none behind the ship's outline, %d of them "
              "hidden at 12 poses" % (tag, min(ndots), max(ndots), nhid),
              "%d frames differ: %s" % (wrong_sky, first_sky))
    check(not wrong_px, "%s each page is exactly its %slist's lines, pixel for pixel"
          % (tag, "dots and then its " if sky else ""), "%d pages differ: %s" % (wrong_px, first_px))
    check(not wrong_glass, "%s and the next frame on the glass is that page, whole -- never the one being drawn"
          % tag, "%d of 12 frames showed something else" % wrong_glass)

    if sky:
        # the flight: consecutive frames, where Respawn() begins
        def state():
            return (arr(m, "sd", NS * 5), arr(m, "sv", NS), ints(m, "dw", ND * 3), arr(m, "dv", ND),
                    ints(m, "sh", 3))
        m.run(until=syms["Respawn"], budget=2_000_000)
        prev = state()
        wrong_fly = kept = held = recycled = back = 0
        for _ in range(120):
            m.tick()
            m.run(until=syms["Respawn"], budget=2_000_000)
            now = state()
            (psd, psv, pdw, pdv, psh), (sd, sv, dw, dv, sh) = prev, now
            wrong_fly += sh != [psh[0], psh[1], (psh[2] + mk3d.SPEED + 0x8000) % 0x10000 - 0x8000]
            for i in range(NS):
                if psv[i]:
                    kept += 1
                    wrong_fly += sd[5 * i:5 * i + 5] != psd[5 * i:5 * i + 5]
                else:
                    recycled += 1
                    back += sv[i]
            for i in range(ND):
                if pdv[i]:
                    held += 1
                    wrong_fly += dw[3 * i:3 * i + 3] != pdw[3 * i:3 * i + 3]
                else:
                    recycled += 1
                    back += dv[i]
            prev = now
        check(not wrong_fly, "%s over 120 frames the ship flies %d a frame along its nose, and every star on the "
              "screen keeps its direction and every speck its place in the world until it leaves -- %d kept, "
              "%d held" % (tag, mk3d.SPEED, kept, held), "%d moved otherwise" % wrong_fly)
        # a speck gets three tries at a place in reach and ahead of the ship,
        # the last mirrored through its centre if none is, and now and then
        # that lands just outside the view: it is simply put back again the
        # next frame
        check(back * 10 >= recycled * 8, "%s and what is recycled is back on the screen the next frame: %d of %d"
              % (tag, back, recycled), "%d of %d" % (back, recycled))

    N = 40

    def pages(clean):
        mm = H.session()
        H.load_act(mm, prg)
        mm.bus.mem[syms["v_clean"]] = clean
        mm.run(until=syms["WaitVBlank"], budget=40_000_000)
        for _ in range(N):
            mm.tick()
            mm.run(until=syms["WaitVBlank"], budget=20_000_000)
        return bytes(mm.video.vram[0:0xF000])
    a, b = pages(0), pages(1)
    diff = sum(x != y for x, y in zip(a, b))
    check(not diff, "%s %d frames erased by drawing each page's last frame again in black leave "
          "both pages as clearing them would" % (tag, N), "%d bytes differ" % diff)
    lit = sum(1 for x in a if x)
    check(lit > 200, "%s a ship on the pages" % tag, "%d lit bytes" % lit)
    print()


# ------------------------------------------------- the ports, as pairs
#
# Every port is held to its original the same way: the BASIC typed at
# the interpreter and the .act compiled behind the library, each run
# to the K-th entry of a chosen routine -- a frame wait, an RND call,
# the key wait at the end -- and then what the machine holds compared:
# VRAM, the palette, the text map, the sound array, the registers.
# The stop is a routine *entry* on both sides, so the two machines are
# at the same point of the same algorithm whatever the clock says.

_BASIC = []


def basic_image():
    """The interpreter, built once for every pair."""
    import test_basic as B
    if not _BASIC:
        _BASIC.append(B.build())
    return _BASIC[0]


def to_kth(m, addr, k, budget):
    """Run to the k-th arrival at `addr`: a tick between stops, because
    `run(until=)` from the address it stopped at returns at once."""
    why = None
    for i in range(k):
        if i:
            m.tick()
        why = m.run(until=addr, budget=budget)
        if why != "until":
            break
    return why


def pair(name, stop_bas, stop_act, k, budget_bas=900_000_000, budget_act=100_000_000):
    """Both machines parked at the k-th `stop`: `(M, m, bsyms, syms, prg)`."""
    import test_basic as B
    code, bsyms = basic_image()
    M = B.Machine(code, bsyms)
    M.settle()
    for ln in open(os.path.join(H.ROOT, "demos", name + ".bas"), encoding="utf-8"):
        if ln.strip():
            H.line(M.m, bsyms, ln.rstrip("\r\n"))
    M.m.type("RUN\r")
    why = to_kth(M.m, bsyms[stop_bas], k, budget_bas)
    check(why == "until", "%s: the BASIC reached %s %d times" % (name, stop_bas, k), why)

    prg, syms = H.build_act(H.ACT_LIB + ["demos/%s.act" % name], "act_" + name)
    same_bytes("act_" + name, prg)
    m = H.session()
    H.load_act(m, prg)
    why = to_kth(m, syms[stop_act], k, budget_act)
    check(why == "until", "%s: the port reached %s %d times" % (name, stop_act, k), why)
    return M.m, m, bsyms, syms, prg


def same_bytes_of(name, what, a, b):
    bad = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
    check(not bad and len(a) == len(b), "%s: the same %s" % (name, what),
          "%d bytes differ; first at %d: port %02X BASIC %02X"
          % (len(bad), bad[0] if bad else 0, a[bad[0]] if bad else 0, b[bad[0]] if bad else 0))


def same_vram(name, mb, ma, n, what):
    same_bytes_of(name, what, bytes(ma.video.vram[0:n]), bytes(mb.video.vram[0:n]))


def same_palette(name, mb, ma, lo=0, hi=256):
    pa, pb = ma.palette()[lo:hi], mb.palette()[lo:hi]
    bad = [i for i in range(hi - lo) if pa[i] != pb[i]]
    check(not bad, "%s: the same palette entries %d-%d" % (name, lo, hi - 1),
          "%d differ; entry %d is %03X, BASIC %03X"
          % (len(bad), lo + bad[0] if bad else 0, pa[bad[0]] if bad else 0, pb[bad[0]] if bad else 0))


def same_regs(name, mb, ma, regs):
    import ioregs
    got = [(r, ma.bus.read(ioregs.addr_of(r)), mb.bus.read(ioregs.addr_of(r))) for r in regs]
    bad = [g for g in got if g[1] != g[2]]
    check(not bad, "%s: the same %s" % (name, ", ".join(regs)),
          "; ".join("%s port %02X BASIC %02X" % g for g in bad))


def text_map(m):
    """The 32-row text map of modes 0 and 1, all 5,120 bytes.

    At the machine's map, not at VID_BASE: a scroller has slid the base
    up to 78 bytes into the map, and reading 5,120 bytes from there
    ran off its end into the interpreter's workspace, where one byte
    of editor state failed the INTRO gate. memmap.SCREEN is where the
    machine keeps its map, derived from the same claims the image is
    built from."""
    import memmap
    return bytes(m.bus.mem[memmap.SCREEN:memmap.SCREEN + 160 * 32])


def voices(m):
    """The programmed bytes of the eight voices: pitch, volume, the
    noise and enable bits. Not bytes 2 and 3, the engine's own phase
    accumulator, which two machines that wrote the same pitch at
    different clocks within a frame will never agree on."""
    s = m.sound()
    return bytes(b for v in range(8) for b in (s[8 * v], s[8 * v + 1], s[8 * v + 4], s[8 * v + 5]))


def test_ports():
    """The seven ports of this round, each against its original."""
    print("  TRIANGLES: to the 281st Rnd -- forty triangles, same random numbers")
    mb, ma, bs, s, prg = pair("triangles", "irnd", "Rnd", 7 * 40 + 1, 400_000_000, 60_000_000)
    same_vram("triangles", mb, ma, 38400, "38,400 bytes of mode 4 VRAM")
    print("    %d bytes of PRG" % len(prg))
    print()

    print("  MAZE: to the 1341st Rnd -- the map, twelve scroll steps in")
    mb, ma, bs, s, prg = pair("maze", "irnd", "Rnd", 1280 + 5 * 12 + 1, 400_000_000, 60_000_000)
    same_vram("maze", mb, ma, 0x4040, "map and tile in VRAM")
    same_palette("maze", mb, ma, 0, 16)
    same_regs("maze", mb, ma, ["VID_BASE_L", "VID_BASE_H", "VID_SCY_L", "VID_PAT_L", "VID_PAT_H", "VID_MODE"])
    print("    %d bytes of PRG" % len(prg))
    print()

    print("  PLASMA: to the 5th frame wait -- painted, four rotations in")
    mb, ma, bs, s, prg = pair("plasma", "h_vsync", "WaitVBlank", 5, 900_000_000, 60_000_000)
    same_vram("plasma", mb, ma, 61440, "61,440 bytes of mode 6 VRAM")
    same_palette("plasma", mb, ma, 0, 48)
    print("    %d bytes of PRG" % len(prg))
    print()

    print("  WAVE: to the 120th frame wait")
    mb, ma, bs, s, prg = pair("wave", "h_vsync", "WaitVBlank", 120, 400_000_000, 60_000_000)
    same_vram("wave", mb, ma, 61440, "61,440 bytes of mode 6 VRAM")
    same_palette("wave", mb, ma)
    print("    %d bytes of PRG" % len(prg))
    print()

    print("  SYNTH: to the 120th frame wait -- thirteen steps of the tune")
    mb, ma, bs, s, prg = pair("synth", "h_vsync", "WaitVBlank", 120, 400_000_000, 60_000_000)
    same_bytes_of("synth", "5,120-byte text map", text_map(ma), text_map(mb))
    same_bytes_of("synth", "eight voices: pitch, volume, noise, enable", voices(ma), voices(mb))
    same_palette("synth", mb, ma, 0, 16)
    same_regs("synth", mb, ma, ["VID_BORDER", "VID_MODE", "CUR_CTRL"])
    # the editor, on the compiled one alone: 4 mutes the drums, an
    # arrow moves the cursor, a letter lands in the screen the player
    # reads, and a lowercase one upcases -- synth_screen's cases
    import ioregs
    base = ma.bus.read(ioregs.addr_of("VID_BASE_L")) | (ma.bus.read(ioregs.addr_of("VID_BASE_H")) << 8)
    ma.key("4")
    to_kth(ma, s["WaitVBlank"], 12, 20_000_000)
    check(ma.bus.mem[base + 6 * 160 + 1] == 107, "synth: pressing 4 mutes the drums, digit dim",
          "label attr %02X" % ma.bus.mem[base + 6 * 160 + 1])
    ma.key(["K_RIGHT"])
    to_kth(ma, s["WaitVBlank"], 6, 20_000_000)
    cur = base + 3 * 160 + 8 * 2
    check(ma.bus.mem[cur + 1] == 22, "synth: the cursor moved right and shows",
          "attr at col 8 is %02X" % ma.bus.mem[cur + 1])
    ma.key("C")
    to_kth(ma, s["WaitVBlank"], 6, 20_000_000)
    check(ma.bus.mem[cur] == 67, "synth: typing C writes the note into the screen the player reads",
          "cell holds %02X" % ma.bus.mem[cur])
    ma.key(["K_RIGHT"])
    to_kth(ma, s["WaitVBlank"], 6, 20_000_000)
    ma.key("d")
    to_kth(ma, s["WaitVBlank"], 6, 20_000_000)
    check(ma.bus.mem[cur + 2] == 68, "synth: a lowercase keypress lands as its uppercase note",
          "cell holds %02X" % ma.bus.mem[cur + 2])
    print("    %d bytes of PRG" % len(prg))
    print()

    print("  INTRO: to the 120th frame wait")
    mb, ma, bs, s, prg = pair("intro", "h_vsync", "WaitVBlank", 120, 400_000_000, 60_000_000)
    same_bytes_of("intro", "5,120-byte text map", text_map(ma), text_map(mb))
    same_bytes_of("intro", "eight voices: pitch, volume, noise, enable", voices(ma), voices(mb))
    same_regs("intro", mb, ma, ["VID_BASE_L", "VID_BASE_H", "VID_SCX_L", "VID_SCY_L", "VID_BORDER", "VID_MODE"])
    print("    %d bytes of PRG" % len(prg))
    print()

    print("  MANDEL: to the key wait at the end -- the whole set")
    c0 = None
    mb, ma, bs, s, prg = pair("mandel", "inkey", "ReadKey", 1, 6_000_000_000, 200_000_000)
    same_vram("mandel", mb, ma, 61440, "61,440 bytes of mode 6 VRAM")
    same_palette("mandel", mb, ma)
    print("    %s clocks compiled against %s interpreted to the finished set; %d bytes of PRG"
          % (f"{ma.cpu.cycles:,}", f"{mb.cpu.cycles:,}", len(prg)))
    print()


KEYS = r"""
; KeyPoll and KeyHeld: the bitmap of what is down, from the FIFO
BYTE ARRAY out(8)

PROC Main()
  DO KeyPoll() UNTIL KeyHeld($F5) OD   ; until the up arrow is down
  out(0) = KeyHeld($F5)           ; the up arrow, $E0 75: held
  out(1) = KeyHeld($1C)           ; A: pressed and released
  out(2) = KeyHeld($29)           ; space: held
  out(3) = KeyHeld($F2)           ; the down arrow: never touched
  out(4) = KeyHeld($74)           ; $74 alone is the keypad's right, not the arrow's $F4
  KeyPoll()                       ; the FIFO is empty: nothing changes
  out(5) = KeyHeld($F5)
  out(6) = KeyHit($1C)            ; A was pressed since we last asked: yes, once
  out(7) = KeyHit($1C)            ; and now it was not
RETURN
"""


def test_keys():
    """KeyPoll/KeyHeld: what is held, as a game asks, from the same FIFO."""
    print("  KeyPoll and KeyHeld")
    prg, syms = H.build_act(H.ACT_LIB + [KEYS], "act_keys")
    m = H.session()
    # up pressed, A pressed and released, space pressed
    m.scancode([0xE0, 0x75, 0x1C, 0xF0, 0x1C, 0x29])
    why = H.run_act(m, prg, budget=2_000_000)
    check(why == "halt", "keys: ran to the HALT", why)
    out = bytes(m.bus.mem[syms["v_out"]:syms["v_out"] + 6])
    check(out[0] != 0 and out[2] != 0, "keys: the up arrow and space are held", out.hex())
    check(out[1] == 0 and out[3] == 0, "keys: a released key and an untouched one are not", out.hex())
    check(out[4] == 0, "keys: the arrow's E0-prefixed code is $80 apart from the keypad's", out.hex())
    check(out[5] != 0, "keys: a poll of an empty FIFO changes nothing", out.hex())
    out = bytes(m.bus.mem[syms["v_out"]:syms["v_out"] + 8])
    check(out[6] != 0 and out[7] == 0,
          "keys: KeyHit sees a make-and-break that came in one poll, once -- a tap, or a typed character",
          out.hex())

    # The same, SYS'd from BASIC -- whose interrupt handler drains the
    # FIFO into its own ring every frame, which is where every port's
    # "press a key" hung on the web page while the bare-machine gates
    # above passed. TakeKeys turns interrupts off; the stub's EI hands
    # them back, and BASIC must still be listening afterwards.
    import test_basic as B
    code, bsyms = basic_image()
    M = B.Machine(code, bsyms)
    M.settle()
    org = prg[0] | (prg[1] << 8)
    M.m.bus.mem[org:org + len(prg) - 2] = prg[2:]
    M.m.type("SYS %d\r" % org)
    M.m.run_frame(3)
    check(M.m.cpu.pc >= org and M.m.cpu.pc < org + len(prg),
          "keys under BASIC: SYS is in the program, waiting", "PC $%04X" % M.m.cpu.pc)
    M.m.scancode([0xE0, 0x75, 0x1C, 0xF0, 0x1C, 0x29])
    M.m.run_frame(3)
    out = bytes(M.m.bus.mem[syms["v_out"]:syms["v_out"] + 6])
    check(out[0] != 0 and out[2] != 0 and out[1] == 0 and out[3] == 0 and out[5] != 0,
          "keys under BASIC: the raw FIFO reaches the program past the interrupt handler", out.hex())
    M.m.scancode([0xF0, 0x29, 0xE0, 0xF0, 0x75])
    M.type("PRINT 6*7\r")
    check(M.m.shows("42"), "keys under BASIC: the program returned and BASIC hears its keyboard again")
    print()


def test_keytest():
    """KEYTEST from the flash-booted disc: the raw stream on the screen
    and down the serial port, the library's reading under it, Esc
    twice back to BASIC."""
    import cool8rsvm as vm
    import test_basic as B
    print("  KEYTEST, from the demos disc")
    img = os.path.join(H.BUILD, "demos.img")
    if not os.path.exists(img):
        print("    SKIPPED: %s is not built (poe demos)" % img)
        print()
        return
    code, bsyms = basic_image()
    m = vm.boot(flash_path=img, render=True)
    for _ in range(90):
        m.run_frame()
    check(m.settle(bsyms["in_raw.rk0"], bsyms["irhead"], bsyms["irtail"], 80_000_000),
          "keytest: BASIC booted from the demos disc")
    H.key(m, bsyms, 'DRIVE 11\r')
    H.key(m, bsyms, 'SYS "KEYTEST.BIN"')
    m.key(["\r"])
    m.run_frame(30)
    m.uart.take()
    m.kbd.feed([0xE0, 0x75])
    m.run_frame(3)
    m.kbd.feed([0x29])
    m.run_frame(3)
    row = m.text()[2].rstrip()
    check(row == "E0 75 29", "keytest: the stream on the screen, byte by byte", repr(row))
    check(m.text()[24].rstrip() == "HIT: SPACE", "keytest: KeyHit saw the space bar", repr(m.text()[24].rstrip()))
    m.kbd.feed([0xF0, 0x29, 0xE0, 0xF0, 0x75])
    m.run_frame(3)
    said = m.uart.take()
    check(said == b"E0 75 29 F0 29 E0 F0 75 ", "keytest: the same stream down the serial port", repr(said))
    m.kbd.feed([0x76, 0xF0, 0x76])
    m.run_frame(3)
    m.kbd.feed([0x76, 0xF0, 0x76])
    m.run_frame(3)
    for _ in range(130):
        m.run_frame()
    check(m.settle(bsyms["in_raw.rk0"], bsyms["irhead"], bsyms["irtail"], 80_000_000)
          and any("COOLBASIC" in r for r in m.text()),
          "keytest: Esc twice, the program returned into the loader's Reset(), and the machine rebooted to the banner")
    print()


def test_loader():
    """The loader (sw/loader.act, D102): SYS "RAINBOW.BIN" from the
    flash-booted disc puts the stub in BASIC's user area; the stub
    traps the vectors, turns the interrupt sources off, streams
    RAINBOW.PRG to $1400 by its own catalogue lookup and runs it; the
    program's final key press returns into Reset(), and the machine
    boots again."""
    import cool8rsvm as vm
    import cool8disk
    import ioregs
    print("  the loader, from the demos disc")
    img = os.path.join(H.BUILD, "demos.img")
    if not os.path.exists(img):
        print("    SKIPPED: %s is not built (poe demos)" % img)
        print()
        return
    prg, _ = H.build_act(H.ACT_LIB + ["demos/rainbow.act"], "rainbow_payload", org=H.PAYLOAD_ORG)
    vol = cool8disk.Volume(cool8disk.Image(img), 11)
    check(vol.get("RAINBOW.PRG") == bytes(prg), "loader: RAINBOW.PRG on the disc is this build at $%04X" % H.PAYLOAD_ORG,
          "differs: poe demos")
    stub = vol.get("RAINBOW.BIN")
    check(stub[0] | (stub[1] << 8) == 0x0200 and 0x0200 + len(stub) - 2 <= H.PAYLOAD_ORG,
          "loader: the stub loads at $0200 and ends below the payload", "%d bytes" % len(stub))
    code, bsyms = basic_image()
    m = vm.boot(flash_path=img, render=True)
    for _ in range(90):
        m.run_frame()
    check(m.settle(bsyms["in_raw.rk0"], bsyms["irhead"], bsyms["irtail"], 80_000_000), "loader: BASIC booted")
    H.key(m, bsyms, 'DRIVE 11\r')
    H.key(m, bsyms, 'SYS "RAINBOW.BIN"')
    m.key(["\r"])
    m.run_frame(90)
    # the program is running and writing its own globals by now, so
    # its code is what can be compared: the entry stub and the first
    # routine
    check(bytes(m.bus.mem[H.PAYLOAD_ORG:H.PAYLOAD_ORG + 64]) == bytes(prg[2:66]),
          "loader: the payload's code is in memory at $%04X" % H.PAYLOAD_ORG)
    trap = m.bus.mem[0xFFFA] | (m.bus.mem[0xFFFB] << 8)
    check(m.bus.mem[0xFFFC] | (m.bus.mem[0xFFFD] << 8) == trap and 0x0200 <= trap < H.PAYLOAD_ORG,
          "loader: NMI and IRQ vectors point into the stub", "$%04X" % trap)
    check(m.bus.read(ioregs.addr_of("VID_MODE")) == 0x84 and H.PAYLOAD_ORG <= m.cpu.pc < 0xFF00,
          "loader: RAINBOW runs from there, in mode 4",
          "MODE %02X PC $%04X" % (m.bus.read(ioregs.addr_of("VID_MODE")), m.cpu.pc))
    m.kbd.feed([0x29, 0xF0, 0x29])
    for _ in range(130):
        m.run_frame()
    check(m.settle(bsyms["in_raw.rk0"], bsyms["irhead"], bsyms["irtail"], 80_000_000)
          and any("COOLBASIC" in r for r in m.text()),
          "loader: its key press returned into Reset(), and the machine booted again to the banner")
    check(m.bus.mem[0xFFFA] | (m.bus.mem[0xFFFB] << 8) != trap,
          "loader: the ROM took the vectors back", "NMI still $%04X" % trap)
    print()


def test_mscoolman():
    """Ms. Cool-Man, on the machine: the picture the map holds, and the
    rules -- dots, the pill, a ghost eaten and home again, a death, two
    levels cleared into the blue maze. Skips, loudly, without the art."""
    import subprocess
    import ioregs
    import mscool
    print("  MS. COOL-MAN")
    if mscool.sources() is None:
        print("    SKIPPED: the art part is not here -- "
              "tools/mkmscool.py makes assets/misscool/mscoolman_art.act from the sheets")
        print()
        return
    r = subprocess.run([sys.executable, os.path.join(H.ROOT, "tools", "mkmscool.py"), "--check"],
                       capture_output=True, text=True)
    check(r.returncode == 0, "mscoolman: the art file is what the generator writes",
          (r.stdout + r.stderr).strip()[-200:])
    g = mscool.Game()
    same_bytes("mscoolman", g.prg)
    print("    %d bytes of PRG" % len(g.prg))
    reg = lambda n: g.m.bus.read(ioregs.addr_of(n))   # noqa: E731
    sym = g.syms
    mem = g.m.bus.mem

    # the title: mode 2, scrolled four lines, the pink maze's own tile
    # in the corner, her name in yellow, the sprite engine on bank 15
    # (the start-up -- palettes, tiles, 35 KB of sprite patterns
    # recoloured into VRAM, the maze -- takes some thirty frames)
    g.m.run_frame(45)
    check(reg("VID_MODE") == 0x82 and reg("VID_SCY_L") == 4 and reg("VID_PAT_H") == 0x40,
          "mscoolman: mode 2, VID_SCY 4, patterns at $4000",
          "MODE %02X SCY %d PAT_H %02X" % (reg("VID_MODE"), reg("VID_SCY_L"), reg("VID_PAT_H")))
    check(reg("SPR_CTRL") & 0xF1 == 0xF1, "mscoolman: sprites on, palette bank 15",
          "SPR_CTRL %02X" % reg("SPR_CTRL"))
    check(g.cell(0, 0) == (mem[sym["v_mz1_map"]], 0), "mscoolman: the corner cell is maze 1's own tile",
          str(g.cell(0, 0)))
    check(g.cell(9, 7) == (64 + 22, 2), "mscoolman: the M of the title, yellow, at (9, 7)",
          str(g.cell(9, 7)))

    # (a copy poked in at $0200 under a running BASIC is not tried: at
    # 56 KB the game lies over BASIC, which is what the loader is for;
    # the path from the disc below runs it as a person does)
    import test_basic as B
    code, bsyms = basic_image()

    # And the path a person takes: the real ROM booting the demos disc,
    # the launcher's DRIVE 11 / SYS "MSCOOLMN.BIN" typed at the
    # keyboard, and the space bar -- the same bytes the web page and
    # the window send. Nothing poked, nothing bare. The disc is
    # `poe demos`' output; its absence is said, not passed over.
    import cool8rsvm as vm
    import cool8disk
    img = os.path.join(H.BUILD, "demos.img")
    if not os.path.exists(img):
        print("    SKIPPED the flash boot: %s is not built (poe demos)" % img)
    elif cool8disk.Volume(cool8disk.Image(img), 11).get("MSCOOLMN.PRG") != bytes(
            H.build_act(mscool.sources(), "mscoolman_payload", org=H.PAYLOAD_ORG)[0]):
        # a disc from before this build is not this build: the flash
        # path once passed a stale game and failed a fresh one, and
        # neither answer meant anything
        check(False, "mscoolman from flash: the demos disc holds this build",
              "MSCOOLMN.PRG on %s differs from the PRG just compiled at $%04X: poe demos" % (img, H.PAYLOAD_ORG))
    else:
        m = vm.boot(flash_path=img, render=True)
        for _ in range(90):
            m.run_frame()
        check(m.settle(bsyms["in_raw.rk0"], bsyms["irhead"], bsyms["irtail"], 80_000_000),
              "mscoolman from flash: BASIC booted from the demos disc and went idle")
        H.key(m, bsyms, 'DRIVE 11\r')
        H.key(m, bsyms, 'SYS "MSCOOLMN.BIN"')
        m.key(["\r"])
        up = None
        for i in range(60):
            m.run_frame(5)
            v = m.video.vram
            if (v[9 * 2 + 7 * 128], v[9 * 2 + 7 * 128 + 1]) == (64 + 22, 2):
                up = (i + 1) * 5
                break
        check(up is not None, "mscoolman from flash: SYS loads the game from drive 11 and the title is up",
              "PC $%04X after 300 frames" % m.cpu.pc)
        # the space bar as a tap: make and break in one burst, the way
        # the window typed a character until D101's day and a fast
        # finger still can -- KeyHit must catch it
        m.kbd.feed([0x29, 0xF0, 0x29])
        m.run_frame(60)
        v = m.video.vram
        check((v[11 * 2 + 17 * 128], v[11 * 2 + 17 * 128 + 1]) == (64 + 27, 2),
              "mscoolman from flash: a tap of the space bar starts the game, READY! is on",
              str((v[11 * 2 + 17 * 128], v[11 * 2 + 17 * 128 + 1])))
        m.kbd.feed([0xE0, 0x75])
        m.run_frame(360)
        m.kbd.feed([0xE0, 0xF0, 0x75])
        v = m.video.vram
        HUDC = 39                      # the score's last digit
        sc = v[HUDC * 2 + 2 * 128] - 64
        check(0 <= sc <= 9 and (v[(HUDC - 1) * 2 + 2 * 128] - 64) in range(1, 10),
              "mscoolman from flash: she has walked and scored; the arrow key reached her",
              "score cells %s" % [v[(HUDC - k) * 2 + 2 * 128] - 64 for k in range(3)])
        del m
    pal = g.m.palette()
    want = [mem[sym["v_mz1_pal"] + 2 * i] | (mem[sym["v_mz1_pal"] + 2 * i + 1] << 8) for i in range(16)]
    check(pal[:16] == want, "mscoolman: palette bank 0 is the pink maze's", str(pal[:5]))

    # READY!, then she walks left eating dots
    g.m.kbd.feed([0x29])
    g.m.run_frame(2)
    g.m.kbd.feed([0xF0, 0x29])
    g.m.run_frame(60)
    check(g.cell(11, 17) == (64 + 27, 2), "mscoolman: READY! in yellow at (11, 17)", str(g.cell(11, 17)))
    check(g.word("dots_left") == 224 and g.byte("lives") == 3 and g.word("score") == 0,
          "mscoolman: 224 dots and pills, three lives, no score",
          "%d %d %d" % (g.word("dots_left"), g.byte("lives"), g.word("score")))
    check(g.cell(29, 1) == (64 + 1, 1), "mscoolman: 1UP beside the maze", str(g.cell(29, 1)))
    v = voices(g.m)
    check(v[0:2] != b"\x00\x00" and (v[3] & 0x40) != 0, "mscoolman: the jingle is playing on voice 0",
          v.hex())
    g.m.run_frame(200)
    x0, y0 = g.her()
    g.poke("want", 1)
    g.m.run_frame(40)
    x1, y1 = g.her()
    n = 224 - g.word("dots_left")
    check(x1 < x0 and y1 == y0 == 188 and n > 0, "mscoolman: she walks left along row 23 and eats",
          "(%d,%d) -> (%d,%d), %d dots" % (x0, y0, x1, y1, n))
    check(g.word("score") == 10 * n, "mscoolman: ten a dot", "%d for %d dots" % (g.word("score"), n))
    # her start tile has no dot; the first she ate is two to the left
    ate = (x0 >> 3) - 2
    check(g.cell(ate, 23) == (sym["c_MZ1_BLANK"], 0) and g.kind()[23 * 28 + ate] == mscool.K_PATH,
          "mscoolman: an eaten dot is a path and a blank cell", str(g.cell(ate, 23)))
    states = [s for _, _, s in g.ghosts()]
    check(states[0] == mscool.G_OUT and states[1] == mscool.G_OUT and states[2] == mscool.G_HOME,
          "mscoolman: Blinky and Pinky are loose, Inky waits for 30 dots", str(states))

    # the pill at (1, 2): she is put on the dot above it, walks down
    # onto it -- that dot, then the pill
    g.pokew("cx", 12)
    g.pokew("cy", 12)
    g.poke("cdir", 3)
    g.poke("want", 3)
    s0 = g.word("score")
    g.m.run_frame(14)
    check(g.word("fright_left") > 300 and g.word("score") == s0 + 60,
          "mscoolman: the pill: fifty points and six seconds of blue",
          "fright %d score %d" % (g.word("fright_left"), g.word("score")))
    states = [s for _, _, s in g.ghosts()]
    check(states[0] == mscool.G_FRIGHT and states[1] == mscool.G_FRIGHT,
          "mscoolman: the loose ghosts are frightened", str(states))

    # Blinky, blue, is put just under her on the pill's tile, which
    # is bare now: eaten, eyes, home, out again. Everything pauses
    # while the score shows, so no dot is eaten meanwhile.
    g.pokew("cx", 12, mscool.BLINKY)
    g.pokew("cy", 26, mscool.BLINKY)
    g.pokew("cx", 12)
    g.pokew("cy", 20)
    s0 = g.word("score")
    g.m.run_frame(4)
    check(g.byte("gstate", mscool.BLINKY) == mscool.G_EYES and g.word("score") == s0 + 200,
          "mscoolman: a blue ghost eaten is 200 and a pair of eyes",
          "state %d score %d" % (g.byte("gstate", mscool.BLINKY), g.word("score")))
    for t in range(200):
        g.m.run_frame(5)
        if g.byte("gstate", mscool.BLINKY) == mscool.G_ENTER:
            break
    bx, by, bs = g.ghosts()[0]
    check(bs == mscool.G_ENTER and bx == 112, "mscoolman: the eyes find the door", "(%d,%d) state %d" % (bx, by, bs))
    for t in range(200):
        g.m.run_frame(5)
        if g.byte("gstate", mscool.BLINKY) == mscool.G_OUT:
            break
    bx, by, bs = g.ghosts()[0]
    check(bs == mscool.G_OUT and by <= 92, "mscoolman: and Blinky is out again", "(%d,%d) state %d" % (bx, by, bs))

    # a red ghost under her: a life
    g.pokew("fright_left", 0)
    for gh in range(1, 5):
        if g.byte("gstate", gh) == mscool.G_FRIGHT:
            g.poke("gstate", mscool.G_OUT, gh)
    g.pokew("cx", g.word("cx"), mscool.PINKY)
    g.pokew("cy", g.word("cy"), mscool.PINKY)
    g.poke("gstate", mscool.G_OUT, mscool.PINKY)
    g.m.run_frame(160)
    check(g.byte("lives") == 2 and g.byte("died") == 1, "mscoolman: caught: a life gone",
          "lives %d" % g.byte("lives"))
    g.m.run_frame(10)
    check(g.her() == (112, 188) and g.ghosts()[0][:2] == (112, 92),
          "mscoolman: everyone back at the start", "%s %s" % (g.her(), g.ghosts()[0]))
    check(g.cell(29, 24) == (112, 15), "mscoolman: one life in hand, her icon beside the maze",
          str(g.cell(29, 24)))

    # two levels cleared: the pink maze again, then the blue one
    g.m.run_frame(125)
    check(g.clear_but_one(), "mscoolman: the last dot eaten, the next level's READY! on")
    check(g.byte("level") == 2 and g.byte("maze") == 1 and g.word("dots_left") == 224,
          "mscoolman: level 2 is the pink maze, refilled",
          "level %d maze %d dots %d" % (g.byte("level"), g.byte("maze"), g.word("dots_left")))
    check(g.clear_but_one(), "mscoolman: and again")
    want = [mem[sym["v_mz2_pal"] + 2 * i] | (mem[sym["v_mz2_pal"] + 2 * i + 1] << 8) for i in range(16)]
    check(g.byte("level") == 3 and g.byte("maze") == 2 and g.word("dots_left") == 244
          and g.m.palette()[:16] == want and g.cell(0, 0) == (mem[sym["v_mz2_map"]], 0),
          "mscoolman: level 3 is the blue maze: 244 dots, its palette, its tiles",
          "level %d maze %d dots %d" % (g.byte("level"), g.byte("maze"), g.word("dots_left")))
    check(g.cell(29, 27) == (116 + 8, 15), "mscoolman: the orange, level 3's fruit, beside the maze",
          str(g.cell(29, 27)))

    # the acts: the level poked to the one before each, cleared, and the
    # clapperboard, its digit and (for the first) the tune looked for;
    # then the later mazes as the levels pass
    def act_after(level, digit, frames, tune):
        g.poke("level", level)
        kind = bytearray(g.kind())
        x, y = g.her()
        best = min((abs((i % 28) - (x >> 3)) + abs((i // 28) - (y >> 3)), i)
                   for i in range(868) if kind[i] in (mscool.K_DOT, mscool.K_PILL))
        for i in range(868):
            if kind[i] in (mscool.K_DOT, mscool.K_PILL) and i != best[1]:
                kind[i] = mscool.K_PATH
        g.set_kind(kind)
        g.pokew("dots_left", 1)
        for t in range(600):
            d = g.route(best[1] % 28, best[1] // 28)
            if d is not None:
                g.poke("want", d)
            g.m.run_frame(1)
            if g.word("dots_left") == 0:
                break
        g.m.run_frame(200)
        clap = g.cell(12, 0) in ((144, 15), (160, 15), (176, 15)) and g.cell(17, 2) == (192 + digit - 1, 15)
        v = voices(g.m)
        playing = v[0:2] != b"\x00\x00" and (v[3] & 0x40) != 0
        check(clap, "mscoolman: after level %d the clapperboard says ACT %d" % (level, digit),
              "%s %s" % (g.cell(12, 0), g.cell(17, 2)))
        check(playing == tune, "mscoolman: act %d %s" % (digit, "plays its tune" if tune else "has no tune to play"),
              v[:4].hex())
        g.m.run_frame(frames)
        check(g.byte("level") == level + 1 and g.cell(11, 17) == (64 + 27, 2),
              "mscoolman: and level %d's READY! follows" % (level + 1),
              "level %d cell %s" % (g.byte("level"), g.cell(11, 17)))
    act_after(2, 1, 560, True)
    g.m.run_frame(130)
    act_after(5, 2, 1150, False)
    g.m.run_frame(130)
    want = [mem[sym["v_mz3_pal"] + 2 * i] | (mem[sym["v_mz3_pal"] + 2 * i + 1] << 8) for i in range(16)]
    check(g.byte("maze") == 3 and g.m.palette()[:16] == want and g.cell(0, 0) == (mem[sym["v_mz3_map"]], 0)
          and g.word("dots_start") == 242,
          "mscoolman: level 6 is the orange maze, 242 dots, its palette, its tiles",
          "maze %d dots %d" % (g.byte("maze"), g.word("dots_start")))
    act_after(9, 3, 420, False)
    g.m.run_frame(130)
    want = [mem[sym["v_mz4_pal"] + 2 * i] | (mem[sym["v_mz4_pal"] + 2 * i + 1] << 8) for i in range(16)]
    check(g.byte("maze") == 4 and g.m.palette()[:16] == want and g.cell(0, 0) == (mem[sym["v_mz4_map"]], 0)
          and g.word("dots_start") == 238,
          "mscoolman: level 10 is the navy maze, 238 dots",
          "maze %d dots %d" % (g.byte("maze"), g.word("dots_start")))
    act_after(13, 3, 420, False)
    g.m.run_frame(130)
    want = [mem[sym["v_mz5_pal"] + 2 * i] | (mem[sym["v_mz5_pal"] + 2 * i + 1] << 8) for i in range(16)]
    check(g.byte("maze") == 5 and g.m.palette()[:16] == want and g.cell(0, 0) == (mem[sym["v_mz3_map"]], 0),
          "mscoolman: level 14 is the orange maze's shape in magenta and yellow",
          "maze %d" % g.byte("maze"))

    # the fruit walks in after 70 dots; and the sprite engine's line
    # budget through 240 frames of play
    g.m.run_frame(3)
    g.pokew("dots_left", g.word("dots_start") - 69)
    over = g.eat(240)
    fx = g.word("cx", mscool.FRUIT)
    check(g.word("fruit_left") > 0 and 0 <= fx < 224, "mscoolman: the fruit came in and is walking the maze",
          "fruit_left %d x %d" % (g.word("fruit_left"), fx))
    # how many depends on where the four loose ghosts happen to be --
    # 32 to 165 of 240 seen -- so the number is reported, not gated
    print("    %d of 240 frames overran the sprite engine's line budget" % over)
    check(over < 240, "mscoolman: the engine is not overrun on every frame", "%d of 240" % over)
    check(0x100 < g.m.cpu.sp <= 0x200, "mscoolman: the stack is where it should be",
          "SP $%04X" % g.m.cpu.sp)
    print()


def test_arkanoid():
    """Arkanoid, on the machine, with its two data files on drive 11 of a
    flash of its own: the title's logo, round 1 as the arcade draws it,
    the Vaus composed into the background, a frame of play in every
    vblank, each capsule's power, an enemy through a gate, the exit to
    round 2, a life lost, and DOH beaten. Skips, loudly, without the art."""
    import subprocess
    import ioregs
    import arkanoid as A
    print("  ARKANOID")
    if A.sources() is None:
        print("    SKIPPED: the art is not here -- tools/mkarkanoid.py makes "
              "assets/arkanoid/arkanoid_art.act and its two data files from the sheets")
        print()
        return
    r = subprocess.run([sys.executable, os.path.join(H.ROOT, "tools", "mkarkanoid.py"), "--check"],
                       capture_output=True, text=True)
    check(r.returncode == 0, "arkanoid: the art file and the two data files are what the generator writes",
          (r.stdout + r.stderr).strip()[-200:])
    g = A.Game(tag="arkanoid")
    same_bytes("arkanoid", g.prg)
    print("    %d bytes of PRG" % (len(g.prg) - 2))
    reg = lambda n: g.m.bus.read(ioregs.addr_of(n))   # noqa: E731
    sym = g.syms
    mem = g.m.bus.mem
    c_ = lambda n: sym["c_" + n]                       # noqa: E731

    # the title: mode 2, patterns at $1000, the sprite engine on bank 15,
    # and the arcade's logo out of the data file, in pattern bank 1
    g.m.run_frame(40)
    check(reg("VID_MODE") & 0x0F == 2 and reg("VID_PAT_H") == 0x10, "arkanoid: mode 2, patterns at $1000",
          "MODE %02X PAT_H %02X" % (reg("VID_MODE"), reg("VID_PAT_H")))
    check(reg("SPR_CTRL") & 0xF1 == 0xF1, "arkanoid: sprites on, palette bank 15", "SPR_CTRL %02X" % reg("SPR_CTRL"))
    lx, ly = c_("LOGO_X"), 6
    check(g.cell(lx, ly) == (mem[sym["v_logo_map"]], c_("B_LOGO") | 0x10),
          "arkanoid: the logo's first cell on the title, in its bank", str(g.cell(lx, ly)))

    # the game, its intro skipped: round 1 as the arcade draws it
    g.tap(A.SPACE)
    g.m.run_frame(20)
    g.tap(A.SPACE)
    g.m.run_frame(60)
    tb, bb = c_("T_BRICK"), c_("B_BRICK")
    check(g.cell(1, 5) == (tb + 16, bb) and g.cell(2, 5) == (tb + 17, bb),
          "arkanoid: round 1's first silver brick, both halves, at row 5", "%s %s" % (g.cell(1, 5), g.cell(2, 5)))
    check(g.cell(1, 10) == (tb + 6, bb), "arkanoid: and its green one five rows down", str(g.cell(1, 10)))
    fn, fd = sym["v_fn"], sym["v_fd"]
    check(g.cell(3, 11) == (mem[fd + 11 * 28 + 3], 0) and mem[fd + 11 * 28 + 3] != mem[fn + 11 * 28 + 3],
          "arkanoid: under the green row, one cell right, the background's dark tile: the bricks' shadow",
          str(g.cell(3, 11)))
    check(g.cell(4, 21) == (mem[fn + 21 * 28 + 4], 0), "arkanoid: and further down, the background as it is",
          str(g.cell(4, 21)))
    check(g.cell(10, 18)[0] == c_("T_FONT") + 27, "arkanoid: ROUND over the field", str(g.cell(10, 18)))
    v = voices(g.m)
    check(v[0:2] != b"\x00\x00" and (v[3] & 0x40) != 0, "arkanoid: the board's round-start tune on voice 0", v.hex())
    g.m.run_frame(230)
    tv = c_("T_VAUS")
    vc = [g.cell(tx, 27) for tx in range(28)]
    ours = [tx for tx, (t, a) in enumerate(vc) if tv <= t < tv + 2 * c_("NSLOT") and a in (c_("B_VA"), c_("B_VB"))]
    check(len(ours) >= 4, "arkanoid: the Vaus is cells of the background, in its own banks", str(ours))
    sh = [g.cell(tx, 28) for tx in ours]
    check(all(tv <= t < tv + 2 * c_("NSLOT") for t, _ in sh), "arkanoid: and its shadow is in the row under it", str(sh))

    # play: the loop runs a frame of play in every vblank, and bricks go
    g.tap(A.SPACE)
    f0, l0 = g.m.frames, g.uword("loops")
    g.autopilot(600)
    loops, frames = g.uword("loops") - l0, g.m.frames - f0
    check(loops == frames, "arkanoid: a frame of play in every one of %d vblanks" % frames, "%d of %d" % (loops, frames))
    check(g.uword("score10") > 0 and g.uword("bricks_left") < 77, "arkanoid: bricks broken, points scored",
          "score %d bricks %d" % (g.uword("score10") * 10, g.uword("bricks_left")))

    # each capsule dropped on the Vaus, and what it does: the Vaus held
    # under it until it lands -- the autopilot would steer it away after
    # the ball -- then play on while the power takes
    def caught(letter, frames=40):
        g.drop(letter)
        x = g.word("vx")
        for _ in range(30):
            g.pokew("vx", x)
            g.m.run_frame(1)
            if not g.byte("cap_on"):
                break
        g.autopilot(frames)
    lives = g.byte("lives")
    caught("E")
    check(g.byte("vform") == 2 and g.byte("vpower") == 3, "arkanoid: E, the Vaus enlarged", str(g.byte("vform")))
    caught("L")
    g.m.kbd.feed(A.SPACE)
    g.autopilot(8)
    g.m.kbd.feed([0xF0, 0x29])
    beams = sum(g.byte("bm_on", j) for j in range(6))
    check(g.byte("vform") == 1 and beams >= 2, "arkanoid: L, the laser, and space fires its beams",
          "form %d beams %d" % (g.byte("vform"), beams))
    caught("C")
    check(g.byte("vform") == 0 and g.byte("vpower") == 1, "arkanoid: C, catch, the Vaus normal again",
          "form %d power %d" % (g.byte("vform"), g.byte("vpower")))
    caught("D")
    check(len(g.balls()) == 3 and g.byte("nballs") == 3, "arkanoid: D, three balls", str(g.balls()))
    g.poke("bspeed", 5)
    caught("S", 20)
    check(g.byte("bspeed") == g.byte("bbase"), "arkanoid: S, the ball slowed to the round's speed", str(g.byte("bspeed")))
    caught("P", 20)
    check(g.byte("lives") == lives + 1, "arkanoid: P, a Vaus more", "%d -> %d" % (lives, g.byte("lives")))
    caught("B", 30)
    te = c_("T_EXIT")
    check(g.byte("ex_on") and te <= g.cell(27, 27)[0] < te + 15, "arkanoid: B, the exit open in the right wall",
          str(g.cell(27, 27)))

    # an enemy through a gate within the round's first minute
    g.poke("en_timer", 10)
    n = g.autopilot(200, until=lambda: any(g.byte("en_on", e) == 1 and g.word("en_y", e) >= 8 for e in range(3)))
    check(n < 200, "arkanoid: an enemy comes in through a gate in the frame's top", "%d frames" % n)

    # out through the exit: ten thousand, and round 2 -- the Vaus walked
    # into it by hand, the autopilot keeping it inside the field
    if not g.byte("ex_on"):
        caught("B", 10)
    s0 = g.uword("score10")
    for _ in range(30):
        g.pokew("vx", 210)
        g.m.run_frame(1)
        if g.byte("round") == 2:
            break
    g.m.run_frame(100)
    check(g.byte("round") == 2 and g.uword("score10") >= s0 + 1000, "arkanoid: out through the exit, 10,000 and round 2",
          "round %d score %d" % (g.byte("round"), g.uword("score10") * 10))
    g.m.run_frame(300)
    check(g.cell(1, 3) == (tb, bb), "arkanoid: round 2's staircase, its white brick at row 3", str(g.cell(1, 3)))

    # the balls lost: a life
    g.tap(A.SPACE)
    g.autopilot(30)
    lives = g.byte("lives")
    for b in range(3):
        g.poke("bon", 0, b)
    g.poke("nballs", 0)
    g.m.run_frame(160)
    check(g.byte("lives") == lives - 1, "arkanoid: the ball lost, a Vaus gone", "%d -> %d" % (lives, g.byte("lives")))
    check(0x100 < g.m.cpu.sp <= 0x200, "arkanoid: the stack is where it should be", "SP $%04X" % g.m.cpu.sp)
    del g

    # And the path a person takes: the real ROM booting the demos disc,
    # DRIVE 11 and SYS "ARKANOID.BIN" typed at the keyboard, and the
    # game finding its two data files on the drive it came from. The
    # disc is `poe demos`' output; its absence is said, not passed over.
    import cool8rsvm as vm
    import cool8disk
    img = os.path.join(H.BUILD, "demos.img")
    pay, psyms = H.build_act(A.sources(), "arkanoid_payload", org=H.PAYLOAD_ORG)
    if not os.path.exists(img):
        print("    SKIPPED the flash boot: %s is not built (poe demos)" % img)
    else:
        vol = cool8disk.Volume(cool8disk.Image(img), 11)
        on = [vol.get("ARKANOID.PRG") == bytes(pay)] + \
             [vol.get(os.path.basename(p)) == open(p, "rb").read() for p in A.DATS]
        if not all(on):
            check(False, "arkanoid from flash: the demos disc holds this build and its two data files",
                  "ARKANOID.PRG, ARKANOID.DAT, ARKSCENE.DAT current: %s -- poe demos" % on)
        else:
            code, bsyms = basic_image()
            m = vm.boot(flash_path=img, render=True)
            for _ in range(90):
                m.run_frame()
            check(m.settle(bsyms["in_raw.rk0"], bsyms["irhead"], bsyms["irtail"], 80_000_000),
                  "arkanoid from flash: BASIC booted from the demos disc and went idle")
            H.key(m, bsyms, 'DRIVE 11\r')
            H.key(m, bsyms, 'SYS "ARKANOID.BIN"')
            m.key(["\r"])
            lx = psyms["c_LOGO_X"]
            want = (pay[psyms["v_logo_map"] - H.PAYLOAD_ORG + 2], psyms["c_B_LOGO"] | 0x10)
            up = None
            for i in range(60):
                m.run_frame(5)
                v = m.video.vram
                if (v[lx * 2 + 6 * 128], v[lx * 2 + 6 * 128 + 1]) == want:
                    up = (i + 1) * 5
                    break
            check(up is not None,
                  "arkanoid from flash: SYS loads it from drive 11, it finds its data files, the logo is up",
                  "PC $%04X after 300 frames" % m.cpu.pc)
            # a tap to start, a tap to skip the intro
            m.kbd.feed([0x29, 0xF0, 0x29])
            m.run_frame(30)
            m.kbd.feed([0x29, 0xF0, 0x29])
            m.run_frame(80)
            v = m.video.vram
            cell = (v[1 * 2 + 5 * 128], v[1 * 2 + 5 * 128 + 1])
            check(cell == (psyms["c_T_BRICK"] + 16, psyms["c_B_BRICK"]),
                  "arkanoid from flash: space starts it, the intro skipped, round 1 on the screen", str(cell))
            del m

    # DOH's round: his face drawn over his wall, and sixteen hits
    g = A.Game(tag="arkanoid_doh")
    sym = g.syms
    c_ = lambda n: sym["c_" + n]                       # noqa: E731
    g.m.run_frame(40)
    g.poke("start_round", 33)
    g.tap(A.SPACE)
    g.m.run_frame(320)
    dx, dy = c_("DOH_TX"), c_("DOH_TY")
    t0 = g.m.bus.mem[sym["v_doh_maps"]]
    check(g.cell(dx, dy) == (t0, c_("B_DOH") | 0x20), "arkanoid: round 33 is DOH, his face from pattern bank 2",
          str(g.cell(dx, dy)))
    g.tap(A.SPACE)
    g.poke("doh_hits", 15)
    n = g.autopilot(1500, until=lambda: g.byte("doh_state") >= 9)
    check(g.byte("doh_state") >= 9, "arkanoid: the sixteenth hit on DOH", "%d frames, hits %d" % (n, g.byte("doh_hits")))
    g.m.run_frame(400)
    bgt = g.m.bus.mem[sym["v_doh_bgmap"] + dy * 28 + dx]
    check(g.byte("doh_on") == 0 and g.cell(dx, dy) == (bgt, 0x10), "arkanoid: DOH gone, the black he sat in",
          "%s, doh_on %d" % (g.cell(dx, dy), g.byte("doh_on")))
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
    routine, so the report names the loop rather than the routine.
    `--profile line` does the same for the library's Line over
    test_run.py's fan."""
    if "line" in sys.argv:
        import test_run as R
        flat = [v for line in R.LINE_FAN for v in line]
        src = "CARD ARRAY fan(%d) = [%s]\n" % (len(flat), " ".join(str(v) for v in flat))
        src += ("PROC Main()\n  CARD j\n  Graphics(4)\n  Clg(0)\n  j = 0\n"
                "  WHILE j < %d DO\n    Line(fan(j), fan(j + 1), fan(j + 2), fan(j + 3), fan(j + 4))\n"
                "    j += 5\n  OD\nRETURN\n" % len(flat))
        prg, syms = H.build_act(H.ACT_LIB + [src], "act_line")
    else:
        prg, syms = H.build_act("sw/bench/sieve.act", "act_sieve")
    m = H.session()
    org, end = H.load_act(m, prg)
    p = dbg.Profile(syms, org, end)
    p.run(m)
    print(p.report(top=16, roll=False))
    return 0


# ---------------------------------------------------------------- SLIDES

SLIDES_BLANK = 45 * 266     # the vertical blank in clocks: lines 480-524, 266 clocks a line


def slides_image(name, files):
    """A flash image, every volume formatted, with `files` -- (8.3 name,
    bytes) -- on the picture drive in that order."""
    import cool8disk as disk
    img = os.path.join(H.BUILD, name + ".img")
    disk.make_image(img)
    im = disk.Image(img)
    vol = disk.Volume(im, disk.PICTURE_VOL)
    for nm, blob in files:
        p = os.path.join(H.BUILD, "%s_%s" % (name, nm))
        with open(p, "wb") as fh:
            fh.write(blob)
        vol.add(p, nm)
    im.save()
    return img


def shown(m, blob):
    """What differs between the screen and picture file `blob` -- mode 6,
    its pixels in VRAM from VID_BASE, its palette, its border -- or ''."""
    import ioregs
    import mkpics
    pal, pix, border = mkpics.unpack(blob)
    reg = lambda n: m.bus.read(ioregs.addr_of(n))   # noqa: E731
    base = reg("VID_BASE_L") | (reg("VID_BASE_H") << 8)
    bad = []
    if reg("VID_MODE") != 0x86:
        bad.append("VID_MODE %02X" % reg("VID_MODE"))
    v = bytes(m.video.vram[base:base + len(pix)])
    if v != pix:
        bad.append("%d of %d pixels differ" % (sum(a != b for a, b in zip(v, pix)), len(pix)))
    p = m.palette()
    if p != pal:
        bad.append("%d palette entries differ" % sum(a != b for a, b in zip(p, pal)))
    if reg("VID_BORDER") != border:
        bad.append("border %d, not %d" % (reg("VID_BORDER"), border))
    return ", ".join(bad)


def on_glass(m, blob, rpl=None):
    """How many of the rendered frame's 640 x 480 raster pixels are not
    picture file `blob` as mode 6 shows it: a pixel 2 x 2, the 512
    columns centred, the border's colour either side -- and with its
    change list `rpl`, every row through its own palette."""
    import mkpics
    pal, pix, border = mkpics.unpack(blob)
    changes = mkpics.unpack_rpl(rpl) if rpl else None
    pal = list(pal)
    fb = m.fb()
    side = (640 - 2 * mkpics.W) // 2
    bad = 0
    for r in range(mkpics.H):
        if changes:
            for e, c in changes[r][0] + changes[r][1]:
                pal[e] = c
        row = pix[r * mkpics.W:(r + 1) * mkpics.W]
        want = ([pal[border]] * side + [pal[row[x // 2]] for x in range(2 * mkpics.W)]
                + [pal[border]] * side)
        for y in (2 * r, 2 * r + 1):
            bad += sum(a != b for a, b in zip(fb[y * 640:(y + 1) * 640], want))
    return bad


# The last clock after VID_RASTER names a line at which a palette commit
# still lands before the palette is read for that line's first mode-6
# picture pixel: the change reaches VID_RASTER at pixel 648-650 of the
# line before (cool8_video's crossing, three system clocks after the
# prefetch pulse at 640), and cool8_pixel reads the palette for pixel 64
# one clock before it goes out -- 213 pixel clocks at worst, 71 system
# clocks, so a commit must be in by the 70th. 04-system.md section 5.9.
SLIDES_WINDOW = 70


def raster_faults(log, blob):
    """The commits in a palette-write log that a pixel on the screen would
    have seen: one to an entry a row shows, landing after that row's first
    line is under way -- or the border's entry made anything but black."""
    import mkpics
    _, pix, border = mkpics.unpack(blob)
    used = [set(pix[r * mkpics.W:(r + 1) * mkpics.W]) for r in range(mkpics.H)]
    bad = []
    for off, line, e, rgb in log:
        if e == border:
            if rgb != 0:
                bad.append((off, line, e, rgb))
        elif line < 2 * mkpics.H:
            before = line % 2 == 0 and off <= SLIDES_WINDOW
            if not before and e in used[line // 2]:
                bad.append((off, line, e, rgb))
    return bad


def in_vram(m, blob):
    """Whether VRAM from VID_BASE holds picture file `blob`'s pixels, in
    mode 6 -- the part of `shown` that holds whichever version it is."""
    import ioregs
    import mkpics
    _, pix, _ = mkpics.unpack(blob)
    reg = lambda n: m.bus.read(ioregs.addr_of(n))   # noqa: E731
    base = reg("VID_BASE_L") | (reg("VID_BASE_H") << 8)
    return reg("VID_MODE") == 0x86 and bytes(m.video.vram[base:base + len(pix)]) == pix


def raster_picture():
    """A made-up version-2 picture and its change list, `(pic, rpl)`.

    Row r shows 32 entries, a window stepping three a row round 1..200,
    so each row brings three entries the row above did not show --
    changed while that row is drawn -- and two it keeps are recoloured,
    which can only be done in the blanking before it. Every row's palette
    is five entries away from the last."""
    import mkpics
    ent = lambda r, k: 1 + (k + 3 * r) % 200                # noqa: E731
    pal = [0] + [((i * 0x2B7) & 0xFFF) | 0x111 for i in range(1, 256)]
    pix = bytes(ent(r, x // 8) for r in range(mkpics.H) for x in range(mkpics.W))
    changes = [([], [])]
    for r in range(1, mkpics.H):
        hot = [(ent(r, 5), (r * 0x35 + 0x480) & 0xFFF | 0x100),
               (ent(r, 17), (r * 0x61 + 0x0C4) & 0xFFF | 0x001)]
        free = [(ent(r, 29 + j), (r * 0x25 + j * 0x5B + 0x303) & 0xFFF | 0x010) for j in range(3)]
        changes.append((hot, free))
    return mkpics.pack(pal, pix, 0, version=2), mkpics.pack_rpl(changes, 0)


def space(m, frames=60):
    """The space bar as the window types it, make and break in one
    burst, and time for the next picture to arrive."""
    m.kbd.feed([0x29, 0xF0, 0x29])
    m.run_frame(frames)


def slides_from_disc(demos):
    """The path a person takes: the ROM booting the disc, the launcher's
    `DRIVE 11` and `SYS "SLIDES.BIN"`, and time for the first picture.
    `(machine, '')`, or `(None, why not)`."""
    import cool8disk as disk
    v11 = disk.Volume(disk.Image(demos), disk.ACTION_VOL)
    payload, _ = H.build_act(H.ACT_LIB + ["demos/slides.act"], "slides_payload", org=H.PAYLOAD_ORG)
    if not v11.find("SLIDES.PRG") or v11.get("SLIDES.PRG") != bytes(payload):
        return None, "SLIDES.PRG on %s is not this build: poe demos" % demos
    code, bsyms = basic_image()
    m = vm.boot(flash_path=demos, render=True)
    for _ in range(90):
        m.run_frame()
    if not m.settle(bsyms["in_raw.rk0"], bsyms["irhead"], bsyms["irtail"], 80_000_000):
        return None, "BASIC did not boot from %s" % demos
    H.key(m, bsyms, 'DRIVE %d\r' % disk.ACTION_VOL)
    H.key(m, bsyms, 'SYS "SLIDES.BIN"')
    m.key(["\r"])
    m.run_frame(60)
    return m, ""


def test_slides():
    """SLIDES (demos/slides.act, D103): every .PIC on the picture drive
    in catalogue order, the next at a space, round again after the last.
    Held first to two made-up pictures on a flash image of its own, with
    a file that is not a picture, a .PIC too short to be one and a .PIC
    whose header says otherwise among them -- so the format and the
    viewer are proved without the photographs, which the repository does
    not hold -- then, when `poe demos` has put the real ones on the disc,
    from there as a person runs it."""
    import cool8disk as disk
    import ioregs
    import mkpics
    print("  SLIDES")
    prg, syms = H.build_act(H.ACT_LIB + ["demos/slides.act"], "slides")
    same_bytes("slides", prg)
    print("    %d bytes of PRG" % (len(prg) - 2))
    org = prg[0] | (prg[1] << 8)
    vol = prg[2 + syms["v_pic_vol"] - org]
    check(vol == disk.PICTURE_VOL,
          "slides: it reads drive %d, the one cool8disk.PICTURE_VOL names" % disk.PICTURE_VOL,
          "pic_vol is %d" % vol)

    def picture(seed, border):
        pal = [(i * seed) & 0xFFF for i in range(256)]
        pal[border] = 0
        pix = bytes((x * seed + y * 7) & 0xFF for y in range(mkpics.H) for x in range(mkpics.W))
        return mkpics.pack(pal, pix, border)
    one, two = picture(0x131, 0), picture(0x2C7, 77)
    ras, rpl = raster_picture()
    img = slides_image("slides_test", [
        ("ONE.PIC", one),
        ("NOTES.TXT", b"not a picture\r\n"),
        ("BAD.PIC", one[:3] + b"\x03" + one[4:]),     # a version this viewer does not know
        ("SHORT.PIC", one[:4096]),                    # too short to be a picture at all
        ("TWO.PIC", two),
        ("LONE.PIC", ras),                            # version 2, and no LONE.RPL beside it
        ("RAS.PIC", ras),
        ("RAS.RPL", rpl)])
    m = vm.Machine(flash_path=img, render=True)
    org, end = H.load_act(m, prg)
    # the cursor on in the middle of the screen, as BASIC leaves it at a
    # SYS: the owner saw it blinking over the first version's pictures,
    # which this machine, cursor off from reset, never showed
    for reg, v in (("CUR_X", 40), ("CUR_Y", 15), ("CUR_CTRL", 0x11)):
        m.bus.write(ioregs.addr_of(reg), v)
    why = m.run(until=syms["Show"], budget=20_000_000)
    p = dbg.Profile(syms, org, end)
    p.start(m)
    why2 = m.run(until=syms["KeyPoll"], budget=20_000_000)
    p.collect(m)
    check(why == "until" and why2 == "until",
          "slides: the drive scanned, the first picture shown, the keys asked", "%s, %s" % (why, why2))
    diff = shown(m, one)
    check(not diff, "slides: ONE.PIC on the screen -- mode 6, its 61,440 pixels, its 256 entries, its border", diff)
    print("    a picture in %s clocks, %d ms: %s streaming the pixels, %s the header and palette,"
          " %s waiting for frames, %s blacking out, %s committing the palette"
          % tuple(["{:,}".format(p.total), p.total // 8375] +
                  ["{:,}".format(p.of(r)) for r in ("Show", "FlashRead", "WaitVBlank", "Black", "Commit")]))
    check(p.of("Black") < SLIDES_BLANK and p.of("Commit") < SLIDES_BLANK,
          "slides: the palette goes black, and comes back, inside a vertical blank each",
          "%d and %d clocks of %d" % (p.of("Black"), p.of("Commit"), SLIDES_BLANK))
    check(34 * 61440 <= p.of("Show") < 35 * 61440,
          "slides: the pixels stream at the flash's own rate, 34 clocks a byte -- "
          "what sim/tb/cool8_flash_tb.v measures on the RTL",
          "%s clocks for 61,440 bytes" % "{:,}".format(p.of("Show")))
    m.run_frame(2)
    bad = on_glass(m, one)
    check(not bad, "slides: and on the glass -- every raster pixel of a frame the picture's, or the border's",
          "%d of 307,200 differ" % bad)
    check(not m.bus.read(ioregs.addr_of("CUR_CTRL")) & 1,
          "slides: the text cursor off -- BASIC leaves it on, and it blinks over a bitmap too")
    m.run_frame(32)
    bad = on_glass(m, one)
    check(not bad, "slides: and 32 frames on, the blink's other phase, still only the picture",
          "%d of 307,200 differ" % bad)
    space(m)
    diff = shown(m, two)
    check(not diff, "slides: a space shows the next -- BAD.PIC's header refused, "
          "SHORT.PIC and NOTES.TXT never listed", diff)
    space(m)
    bad = on_glass(m, ras, rpl)
    check(in_vram(m, ras) and not bad,
          "slides: the next is RAS.PIC -- LONE.PIC, version 2 with no change list, refused -- "
          "and every row of a frame is drawn in its own palette",
          "%d of 307,200 raster pixels differ" % bad)
    m.pal_log_start()
    m.run_frame(2)
    log = m.pal_log()
    faults = raster_faults(log, ras)
    check(len(log) > 2 * 239 * 5 and not faults,
          "slides: %d palette writes in two frames, and not one lands under a pixel showing its entry"
          % len(log), "%d do; the first: %s" % (len(faults), faults[:1]))
    _, rpix, _ = mkpics.unpack(ras)
    early = [off for off, line, e, _ in log if e and line < 480 and line % 2 == 0
             and e in set(rpix[(line // 2) * 256:(line // 2 + 1) * 256])]
    if early:
        print("    a row's blanking writes land %d to %d clocks after VID_RASTER names its line;"
              " %d is the last that beats its first pixel" % (min(early), max(early), SLIDES_WINDOW))
    space(m)
    diff = shown(m, one)
    check(not diff, "slides: and after the last, the first again", diff)

    m = vm.Machine(flash_path=slides_image("slides_empty", []), render=True)
    H.load_act(m, prg)
    why = m.run(until=syms["ReadKey"], budget=20_000_000)
    check(why == "until" and any("NO PICTURES" in r for r in m.text()),
          "slides: an empty picture drive says so on the text screen and waits for a key", why)

    demos = os.path.join(H.BUILD, "demos.img")
    files = mkpics.present()
    if not os.path.exists(demos):
        print("    SKIPPED the disc: %s is not built (poe demos)" % demos)
    elif not files:
        print("    SKIPPED the disc: no pictures here -- python tools/mkpics.py --fetch")
    else:
        v10 = disk.Volume(disk.Image(demos), disk.PICTURE_VOL)
        blobs = {nm: open(path, "rb").read() for nm, path in files}
        on = {nm: v10.get(nm) if v10.find(nm) else None for nm in blobs}
        check(on == blobs, "slides from flash: drive %d holds the %d files tools/mkpics.py wrote"
              % (disk.PICTURE_VOL, len(blobs)), "not the same: poe demos")
        pics = [nm for nm, _ in files if nm.endswith(".PIC")]
        m, why = slides_from_disc(demos)
        check(m is not None, 'slides from flash: SYS "SLIDES.BIN" from drive 11 of the booted disc', why)

        def looks(nm):
            """What is wrong with picture `nm` on the screen, or ''."""
            pic, rpl = blobs[nm], blobs.get(nm[:-4] + ".RPL")
            if rpl is None:
                return shown(m, pic)
            m.pal_log_start()
            m.run_frame(1)
            faults = raster_faults(m.pal_log(), pic)
            bad = on_glass(m, pic, rpl)
            return ", ".join(s for s in (
                "" if in_vram(m, pic) else "VRAM is not its pixels",
                "%d of 307,200 raster pixels differ" % bad if bad else "",
                "%d palette writes land under a pixel showing the entry" % len(faults) if faults else "")
                if s)

        if m is not None:
            check(not m.bus.read(ioregs.addr_of("CUR_CTRL")) & 1,
                  "slides from flash: BASIC's cursor is off over the pictures")
            for nm in pics:
                diff = looks(nm)
                check(not diff, "slides from flash: %s on the screen, %d colours in the frame"
                      % (nm, len(set(m.fb()))), diff)
                space(m)
            diff = looks(pics[0])
            check(not diff, "slides from flash: and round again to %s" % pics[0], diff)
    print()


def shoot_slides():
    """`python sim/test_action.py --slides`: every picture on the built
    disc, from the machine's own frame, into sim/build/slides_<name>.png."""
    import mkpics
    m, why = slides_from_disc(os.path.join(H.BUILD, "demos.img"))
    if m is None:
        print("  " + why)
        return 1
    for nm in [n for n, _ in mkpics.present() if n.endswith(".PIC")]:
        path = os.path.join(H.BUILD, "slides_%s.png" % nm.split(".")[0].lower())
        print("  %d colours on screen -> %s" % (H.shot(m, path), os.path.relpath(path, H.ROOT)))
        space(m)
    return 0


def shoot_cobra():
    """`python sim/test_action.py --cobra`: the compiled COBRA 340 frames
    into its tumble, stern on, from the machine's own frame, into
    docs/img/demo-act-cobra.png -- the picture 14-demos.md shows.
    `--cobra 30 200 ...`: those frames instead, into
    sim/build/cobra_<frame>.png, to look along the tumble. `--cobra2`
    the same for COBRA 2, into demo-act-cobra2.png or cobra2_<frame>.png."""
    frames = [int(a) for a in sys.argv[1:] if a.isdigit()]
    name = "cobra2" if "--cobra2" in sys.argv else "cobra"
    prg, syms = H.build_act(H.ACT_LIB + ["demos/%s.act" % name], "act_%s_shot" % name)
    m = H.session(render=True)
    H.load_act(m, prg)
    at = 0
    for fr in frames or [{"cobra": 340, "cobra2": 200}[name]]:
        m.run_frame(max(1, fr - at))
        at = fr + 1
        # the page just finished, its edges named by vertex, then shown
        m.run(until=syms["WaitVBlank"], budget=2_000_000)
        mem = m.bus.mem
        cur = mem[syms["v_cur"]]
        where = {}
        for v in range(28):
            where.setdefault((mem[syms["v_sx"] + v], mem[syms["v_sy"] + v]), []).append(v)
        a = syms["v_lst"] + cur * 152
        ends = []
        for j in range(mem[syms["v_nl"] + cur]):
            x0, y0, x1, y1 = mem[a + 4 * j:a + 4 * j + 4]
            ends.append((where.get((x0, y0), ["?"]), (x0, y0), where.get((x1, y1), ["?"]), (x1, y1)))
        deg = {}
        for va, _, vb, _ in ends:
            for v in va + vb:
                deg[v] = deg.get(v, 0) + 1
        if frames:
            print("  frame %d: %s" % (fr, ", ".join("%s%s-%s%s" % ("/".join(map(str, va)), pa,
                                                                   "/".join(map(str, vb)), pb)
                                                  for va, pa, vb, pb in ends)))
            print("    a vertex on one edge: %s" % sorted(v for v, d in deg.items() if d == 1))
        m.run_frame(2)                  # the frame after this one scans the page
        at += 2
        path = (os.path.join(H.BUILD, "%s_%03d.png" % (name, fr)) if frames
                else os.path.join(H.ROOT, "docs", "img", "demo-act-%s.png" % name))
        print("  %d colours on screen -> %s" % (H.shot(m, path), os.path.relpath(path, H.ROOT)))
    return 0


def main():
    if "--profile" in sys.argv:
        return profile_sieve()
    if "--slides" in sys.argv:
        return shoot_slides()
    if "--cobra" in sys.argv or "--cobra2" in sys.argv:
        return shoot_cobra()
    print("  A2 -- CoolAction! on the machine")
    print()
    only = [a for a in sys.argv[1:] if not a.startswith("--")]    # e.g. `cobra`: just those
    for t in (test_every_encoding, test_features, test_sieve, test_primes, test_library,
              test_hardware, test_line, test_rainbow, test_cobra, test_cobra2, test_ports, test_keys,
              test_keytest, test_loader, test_mscoolman, test_arkanoid, test_slides, test_refusals):
        if not only or any(o in t.__name__ for o in only):
            t()
    return H.report()


if __name__ == "__main__":
    sys.exit(main())
