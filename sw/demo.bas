' ---------------------------------------------------------------------
' demo.bas -- sw/demo.asm, rewritten in COOL8 BASIC.
'
' The same picture and the same sound: a tiled background, eight 16x16
' sprites bouncing, and a two-voice arpeggio with a software envelope.
' sim/test_lib.py measures this against the assembly version.
' ---------------------------------------------------------------------

INCLUDE "lib.bas"

CONST NSPR    = 8
CONST TILEPAT = $4000
CONST SPRPAT  = $6000
' The descriptor holds bits 12:5 of the pattern address. Both operands
' are constants, so this folds to a number at compile time and the
' sprite writer never computes it at all.
CONST SPRID   = SPRPAT >> 5

' Coordinates and steps in bytes. A byte subscript is one load rather
' than a shift and two, and +1/-1 wrapping mod 256 is exactly what a
' step of 255 means.
DIM sx(8) AS BYTE
DIM sy(8) AS BYTE
DIM sdx(8) AS BYTE
DIM sdy(8) AS BYTE
DIM note(4)

CALL SetupVideo()
CALL SetupSprites()
CALL SetupSound()

DO
  CALL WaitVbl()
  CALL MoveSprites()
  CALL Music()
LOOP WHILE 0 = 0
END

' ---------------------------------------------------------------------

SUB SetupVideo()
  DIM j AS BYTE
  DIM k AS BYTE
  DIM v AS BYTE

  CALL Vfill(0, 8192, 0)

  ' two 8x8 patterns: a solid mid colour and a lighter one
  CALL Vseek(TILEPAT)
  k = 0
  DO WHILE k < 32
    POKE VRAM_DATA, $99
    k = k + 1
  LOOP
  k = 0
  DO WHILE k < 32
    POKE VRAM_DATA, $CC
    k = k + 1
  LOOP

  ' the map: 32 rows of 64 entries at stride 128
  CALL Vseek(0)
  j = 0
  DO WHILE j < 32
    k = 0
    DO WHILE k < 64
      POKE VRAM_DATA, k AND 1
      POKE VRAM_DATA, j AND 3
      k = k + 1
    LOOP
    k = 0
    DO WHILE k < 128
      POKE VRAM_DATA, 0
      k = k + 1
    LOOP
    j = j + 1
  LOOP

  CALL MakeSprPat()
  CALL SetPalette()

  CALL Mode(2)
  CALL PatBase(TILEPAT)
END SUB

' A filled diamond, 16x16 at 4 bits a pixel: two pixels to a byte.
SUB MakeSprPat()
  DIM x AS BYTE
  DIM y AS BYTE
  DIM l AS BYTE
  DIM r AS BYTE
  CALL Vseek(SPRPAT)
  y = 0
  DO WHILE y < 16
    x = 0
    DO WHILE x < 16
      l = Diamond(x, y)
      r = Diamond(x + 1, y)
      POKE VRAM_DATA, (l << 4) + r
      x = x + 2
    LOOP
    y = y + 1
  LOOP
END SUB

FUNCTION Diamond(x AS BYTE, y AS BYTE) AS INT
  DIM d AS BYTE
  d = Abs8(x) + Abs8(y)
  IF d >= 8 THEN
    RETURN 0
  END IF
  RETURN 8 - d
END FUNCTION

FUNCTION Abs8(v AS BYTE) AS INT
  IF v >= 8 THEN
    RETURN v - 8
  END IF
  RETURN 8 - v
END FUNCTION

SUB SetPalette()
  DIM k AS INT
  DIM r AS BYTE
  DIM bank AS BYTE
  k = 0
  DO WHILE k < 256
    r = k AND 15
    bank = (k >> 4) AND 3
    CALL Palette(k, r, bank * 5, 15 - r)
    k = k + 1
  LOOP
END SUB

' ---------------------------------------------------------------------

SUB SetupSprites()
  DIM i AS BYTE
  i = 0
  DO WHILE i < NSPR
    sx(i) = 40 + i * 16
    sy(i) = 100 + i * 8
    sdx(i) = 1
    IF (i AND 1) = 1 THEN
      sdx(i) = 255
    END IF
    sdy(i) = 1
    IF ((i >> 1) AND 1) = 1 THEN
      sdy(i) = 255
    END IF
    i = i + 1
  LOOP
  CALL SprCtrl(3, 1)
END SUB

SUB MoveSprites()
  DIM i AS BYTE
  DIM x AS BYTE
  DIM y AS BYTE
  DIM dx AS BYTE
  DIM dy AS BYTE
  ' The position and its step are read out of the arrays once, worked on
  ' in locals, and written back once.
  '
  ' The compiler has no register allocator, so every mention of `sx(i)`
  ' is a fresh address computation and a fresh load -- about fifteen
  ' clocks each, against three for a local. Hoisting is what the
  ' assembly version does by keeping the value in a register, and it is
  ' ordinary practice in any language whose compiler does not do it for
  ' you.
  i = 0
  DO WHILE i < NSPR
    x = sx(i)
    dx = sdx(i)
    y = sy(i)
    dy = sdy(i)

    x = (x + dx) AND 255
    IF x < 8 THEN
      dx = (0 - dx) AND 255
      x = 8
    END IF
    IF x > 239 THEN
      dx = (0 - dx) AND 255
      x = 239
    END IF

    y = (y + dy) AND 255
    IF y < 8 THEN
      dy = (0 - dy) AND 255
      y = 8
    END IF
    IF y > 209 THEN
      dy = (0 - dy) AND 255
      y = 209
    END IF

    sx(i) = x
    sdx(i) = dx
    sy(i) = y
    sdy(i) = dy
    CALL Spr16(i, x << 1, y << 1, SPRID)
    i = i + 1
  LOOP
END SUB

' ---------------------------------------------------------------------
' A minor seventh, stepped every sixteen frames, with the envelope
' walked down in software -- which is what D41 said envelopes would be.
' ---------------------------------------------------------------------

DIM tick AS BYTE
DIM cur AS BYTE
DIM vol AS BYTE

SUB SetupSound()
  note(0) = 881
  note(1) = 1048
  note(2) = 1319
  note(3) = 1571
  tick = 0
  cur = 0
  vol = 15
END SUB

SUB Music()
  IF vol > 0 THEN
    vol = vol - 1
  END IF
  tick = tick + 1
  IF (tick AND 15) = 0 THEN
    cur = (cur + 1) AND 3
    vol = 15
    CALL Voice(0, note(cur), vol, 0)
    CALL Voice(1, note(0) >> 1, vol >> 1, 0)
  END IF
  CALL Voice(0, note(cur), vol, 0)
  CALL Voice(1, note(0) >> 1, vol >> 1, 0)
END SUB
