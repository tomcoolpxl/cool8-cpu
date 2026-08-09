' ---------------------------------------------------------------------
' lib.bas -- the COOL8 runtime library.
'
'   INCLUDE "lib.bas"
'
' Graphics, sound, the console and the odd bit of arithmetic. Written in
' COOL8 BASIC and compiled with the program that uses it, because a
' one-pass compiler has no linker and does not need one: INCLUDE is a
' textual splice and the code generator is the same either way.
'
' ## Why so much of this is one instruction
'
' Every register in the machine is at a known address, and the compiler
' turns `POKE <constant>, v` into a single `ST [abs16],R0`. So `Vput`
' costs a call and a store, and the parts of a program that push bytes
' at the video chip run at very nearly the speed of hand-written
' assembly. That is the whole reason the demo can be rewritten in this
' language without losing the frame.
'
' ## What is not here
'
' Floating point. `FLOAT.LIB` is meant to be loaded from flash when a
' program declares a REAL, and neither the type nor the library exists
' yet -- floats stay a future library (docs/11-compiler.md). Everything here is 16-bit integer.
' ---------------------------------------------------------------------

CONST VID_MODE   = $FE10
CONST VID_BASE_L = $FE12
CONST VID_BASE_H = $FE13
CONST VID_IRQ    = $FE1D
CONST PAL_IDX    = $FE1E
CONST PAL_DATA   = $FE1F
CONST VID_PAT_L  = $FE20
CONST VID_PAT_H  = $FE21
CONST CUR_X      = $FE22
CONST CUR_Y      = $FE23
CONST CUR_CTRL   = $FE24
CONST VRAM_ADDR_L = $FE26
CONST VRAM_ADDR_H = $FE27
CONST VRAM_STEP  = $FE28
CONST VRAM_DATA  = $FE29
CONST SPR_IDX    = $FE2A
CONST SPR_DATA   = $FE2B
CONST SPR_CTRL   = $FE2C
CONST SND_IDX    = $FE50
CONST SND_DATA   = $FE51
' The text map, 8 KB aligned because the row wrap is a mask. This used
' to be $8200, which is not aligned: Cls wrote 8192 bytes from there and
' spilled $200 past the end of the window into whatever followed.
CONST TXT        = $8000

' ---------------------------------------------------------------------
' The display.
' ---------------------------------------------------------------------

SUB Mode(m AS INT)
  POKE VID_MODE, 128 + m
END SUB

SUB Palette(i AS INT, r AS INT, g AS INT, b AS INT)
  POKE PAL_IDX, i
  POKE PAL_DATA, r
  POKE PAL_DATA, (g << 4) + b
END SUB

SUB PatBase(a AS INT)
  POKE VID_PAT_L, a AND 255
  POKE VID_PAT_H, a >> 8
END SUB

' Hi and Lo are still here for readability, but nothing hot should call
' them: `a >> 8` and `a AND 255` are two instructions each and are what
' the sprite and sound writers below use directly.
FUNCTION Hi(a AS INT) AS INT
  RETURN a >> 8
END FUNCTION

FUNCTION Lo(a AS INT) AS INT
  RETURN a AND 255
END FUNCTION

' ---------------------------------------------------------------------
' Video RAM, through the CPU's window. The address auto-increments, so a
' fill is a seek and then nothing but stores.
' ---------------------------------------------------------------------

SUB Vseek(a AS INT)
  POKE VRAM_ADDR_L, a AND 255
  POKE VRAM_ADDR_H, a >> 8
END SUB

SUB Vput(b AS INT)
  POKE VRAM_DATA, b
END SUB

SUB Vfill(a AS INT, n AS INT, b AS INT)
  ' A fill is a seek and then nothing but stores, so the loop belongs in
  ' assembly: eight thousand calls to Vput is eight thousand calling
  ' conventions.
  ASM
        LD   R0,[SP+2]
        ST   [$FE26],R0
        LD   R0,[SP+3]
        ST   [$FE27],R0
        LD   R2,[SP+4]
        LD   R3,[SP+5]
        LD   R1,[SP+6]
.vf:    MOV  R0,R2
        OR   R0,R3
        BEQ  .vf9
        ST   [$FE29],R1
        SUB  R2,#1
        BCS  .vf
        SUB  R3,#1
        BRA  .vf
.vf9:
  END ASM
END SUB

' ---------------------------------------------------------------------
' Sprites. Positions are in final raster coordinates, so a sprite over a
' 320x240 background places twice as finely as the background does.
' ---------------------------------------------------------------------

SUB SprCtrl(bank AS INT, on AS INT)
  POKE SPR_CTRL, (bank << 4) + on
END SUB

SUB Sprite(i AS INT, x AS INT, y AS INT, pat AS INT, big AS INT, fl AS INT)
  ' The hot one: eight of these a frame, and in BASIC it was nine POKEs
  ' of computed expressions plus the argument shuffle. Arguments are on
  ' the stack where the convention puts them -- first at [SP+2] -- so
  ' the routine can just read them.
  ASM
        LD   R0,[SP+2]                  ; i
        ADD  R0,R0
        ADD  R0,R0
        ADD  R0,R0
        ST   [$FE2A],R0                 ; SPR_IDX = i*8
        LD   R0,[SP+6]                  ; y low
        ST   [$FE2B],R0
        LD   R0,[SP+7]                  ; y high
        LD   R1,[SP+10]                 ; size
        TST  R1
        BEQ  .sm
        OR   R0,#$80
.sm:    OR   R0,#$40                    ; enable
        ST   [$FE2B],R0
        LD   R0,[SP+4]                  ; x low
        ST   [$FE2B],R0
        LD   R0,[SP+5]                  ; x high
        ST   [$FE2B],R0
        LD   R0,[SP+8]                  ; pattern 12:5
        ST   [$FE2B],R0
        LD   R0,[SP+9]                  ; pattern 15:13
        ST   [$FE2B],R0
        LD   R0,[SP+12]                 ; flips and priority
        ST   [$FE2B],R0
        CLR  R0
        ST   [$FE2B],R0                 ; the bank byte, ignored
  END ASM
END SUB

' Spr16 -- a 16x16 sprite, in front, no flips.
'
' This was written in BASIC and marked INLINE, to spend the calling
' convention rather than the body. **It measured slower** -- 2.72x
' against 2.51x for the assembly version below, which is called
' normally. Expanding nine BASIC statements in place does not beat nine
' hand-written instructions behind a CALL, and the measurement is the
' only reason to know that.
SUB Spr16(i AS INT, x AS INT, y AS INT, pat AS INT)
  ASM
        LD   R0,[SP+2]
        ADD  R0,R0
        ADD  R0,R0
        ADD  R0,R0
        ST   [$FE2A],R0
        LD   R0,[SP+6]
        ST   [$FE2B],R0
        LD   R0,[SP+7]
        OR   R0,#$C0                    ; 16x16, enabled
        ST   [$FE2B],R0
        LD   R0,[SP+4]
        ST   [$FE2B],R0
        LD   R0,[SP+5]
        ST   [$FE2B],R0
        LD   R0,[SP+8]
        ST   [$FE2B],R0
        LD   R0,[SP+9]
        ST   [$FE2B],R0
        CLR  R0
        ST   [$FE2B],R0
        ST   [$FE2B],R0
  END ASM
END SUB

SUB SprOff(i AS INT)
  POKE SPR_IDX, i << 3
  POKE SPR_DATA, 0
  POKE SPR_DATA, 0
END SUB

' ---------------------------------------------------------------------
' Sound. Eight voices, one datapath; the increment is the pitch and it
' is 0.4993 Hz a step, so middle A is 881.
' ---------------------------------------------------------------------

INLINE SUB Voice(v AS INT, inc AS INT, vol AS INT, noise AS INT)
  POKE SND_IDX, v << 3
  POKE SND_DATA, inc AND 255
  POKE SND_DATA, inc >> 8
  POKE SND_IDX, (v << 3) + 4
  POKE SND_DATA, vol
  POKE SND_DATA, (noise << 7) + 64
END SUB

SUB VoiceOff(v AS INT)
  POKE SND_IDX, (v << 3) + 4
  POKE SND_DATA, 0
  POKE SND_DATA, 0
END SUB

SUB Silence()
  DIM v AS INT
  v = 0
  DO WHILE v < 8
    CALL VoiceOff(v)
    v = v + 1
  LOOP
END SUB

' ---------------------------------------------------------------------
' Timing.
' ---------------------------------------------------------------------

' VID_IRQ bit 1 is a latched flag and only a write of a one clears it.
' Acknowledge first, then wait: waiting for it to fall first is a
' deadlock, because nothing else ever lowers it.
SUB WaitVbl()
  POKE VID_IRQ, 2
  ASM
.wv:    LD   R0,[$FE1D]
        BTST R0,#$02
        BEQ  .wv
  END ASM
  POKE VID_IRQ, 2
END SUB

' ---------------------------------------------------------------------
' The console. PRINT compiles into these.
' ---------------------------------------------------------------------

prow = 0
pcol = 0

SUB Cls()
  DIM k AS INT
  POKE VID_MODE, $80
  k = 0
  DO WHILE k < 8192
    POKE TXT + k, 32
    POKE TXT + k + 1, 7
    k = k + 2
  LOOP
  prow = 0
  pcol = 0
  CALL Locate(0, 0)
END SUB

SUB Locate(r AS INT, c AS INT)
  prow = r
  pcol = c
  POKE CUR_X, c
  POKE CUR_Y, r
END SUB

SUB Emit(ch AS INT)
  DIM a AS INT
  IF pcol > 79 THEN
    CALL Newline()
  END IF
  a = TXT + prow * 256 + pcol + pcol
  POKE a, ch
  POKE a + 1, 7
  pcol = pcol + 1
  POKE CUR_X, pcol
END SUB

SUB Newline()
  pcol = 0
  prow = prow + 1
  IF prow > 29 THEN
    prow = 29
    CALL Scroll()
  END IF
  POKE CUR_X, 0
  POKE CUR_Y, prow
END SUB

' Scrolling moves the origin, not the memory: the row pointer wraps
' inside stride*32 in hardware, so this is one register write and the
' clearing of the row that just came into view.
SUB Scroll()
  DIM k AS INT
  DIM a AS INT
  DIM row AS INT
  vtop = vtop + 1
  IF vtop > 31 THEN
    vtop = 0
  END IF
  POKE VID_BASE_H, $80 + vtop
  row = vtop + 29
  IF row > 31 THEN
    row = row - 32
  END IF
  a = TXT + 256 * row
  k = 0
  DO WHILE k < 160
    POKE a + k, 32
    POKE a + k + 1, 7
    k = k + 2
  LOOP
END SUB

SUB Puts(s AS INT)
  DIM c AS INT
  DO
    c = PEEK(s)
    IF c = 0 THEN
      EXIT DO
    END IF
    CALL Emit(c)
    s = s + 1
  LOOP
END SUB

SUB Putn(v AS INT)
  DIM d AS INT
  DIM q AS INT
  DIM lead AS INT
  IF v < 0 THEN
    CALL Emit(45)
    v = 0 - v
  END IF
  d = 10000
  lead = 0
  DO
    q = 0
    DO WHILE v >= d
      v = v - d
      q = q + 1
    LOOP
    IF q <> 0 THEN
      lead = 1
    END IF
    IF lead <> 0 THEN
      CALL Emit(48 + q)
    END IF
    IF d = 1 THEN
      EXIT DO
    END IF
    d = Tenth(d)
  LOOP
  IF lead = 0 THEN
    CALL Emit(48)
  END IF
END SUB

FUNCTION Tenth(d AS INT) AS INT
  IF d = 10000 THEN
    RETURN 1000
  END IF
  IF d = 1000 THEN
    RETURN 100
  END IF
  IF d = 100 THEN
    RETURN 10
  END IF
  RETURN 1
END FUNCTION

' ---------------------------------------------------------------------
' Arithmetic the language has no operator for yet.
' ---------------------------------------------------------------------

FUNCTION Rnd(n AS INT) AS INT
  ' A 16-bit LFSR, the same taps cool8_snd uses for its noise voice.
  DIM b AS INT
  IF seed = 0 THEN
    seed = $ACE1
  END IF
  ASM
        LD   R0,[v_seed]
        LD   R1,[v_seed+1]
        MOV  R2,R1
        MOV  R3,R1
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        XOR  R2,R3
        MOV  R3,R1
        SHR  R3
        SHR  R3
        SHR  R3
        SHR  R3
        SHR  R3
        XOR  R2,R3
        MOV  R3,R1
        SHR  R3
        SHR  R3
        SHR  R3
        SHR  R3
        XOR  R2,R3
        AND  R2,#$01
        ADD  R0,R0
        ADC  R1,R1
        OR   R0,R2
        ST   [v_seed],R0
        ST   [v_seed+1],R1
  END ASM
  ' Half is a logical shift, so this drops the sign bit. Modulo takes
  ' non-negative values, and an LFSR happily produces seeds whose top
  ' bit is set -- which a signed compare reads as negative and passes
  ' straight through.
  RETURN Modulo(seed >> 1, n)
END FUNCTION

FUNCTION Modulo(v AS INT, n AS INT) AS INT
  DIM m AS INT
  ' Shift the divisor up until doubling it would pass v, then subtract
  ' it down again. There is no divide instruction and no `/` operator
  ' yet, so this is what a remainder costs.
  IF n < 1 THEN
    RETURN 0
  END IF
  IF v < n THEN
    RETURN v
  END IF
  m = n
  DO WHILE m <= Half(v)
    m = m + m
  LOOP
  DO
    IF v >= m THEN
      v = v - m
    END IF
    IF m = n THEN
      EXIT DO
    END IF
    m = Half(m)
  LOOP
  RETURN v
END FUNCTION

FUNCTION Half(k AS INT) AS INT
  ASM
        LD   R0,[SP+2]
        LD   R1,[SP+3]
        SHR  R1
        ROR  R0
        RET
  END ASM
END FUNCTION

seed = 0
vtop = 0
