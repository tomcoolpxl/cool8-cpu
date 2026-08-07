' ---------------------------------------------------------------------
' edit.bas -- the COOL8 full-screen editor.
'
' Written in COOL8 BASIC and compiled by tools/cool8bas.py, which makes
' it the first real program the language has had to carry. Everything
' here runs on the machine.
'
' ## The buffer is a gap buffer
'
' Text lives in one 24 KB byte array with a hole in it, and the cursor
' is always at the hole. Inserting is one store and a pointer bump;
' moving the cursor copies one byte per step. The alternative -- a flat
' buffer with a memmove per keystroke -- costs 24,000 byte moves to type
' a character at the top of a long file, which is the difference between
' an editor and a demonstration.
'
'   buf(0 .. gs-1)     text before the cursor
'   buf(gs .. ge-1)    the gap
'   buf(ge .. SIZE-1)  text after the cursor
'
' ## The screen
'
' Mode 0, 128x32 cells of two bytes at stride 256. Row 0 is the status
' line and rows 1..29 are text, so 29 lines are visible at 80 columns.
' Every cell is a character byte and an attribute byte, which is what
' makes syntax colouring cost one extra store rather than a pass.
'
' ## Input
'
' The serial console, in ASCII, with ANSI escapes for the arrow keys.
' The PS/2 port delivers raw Set 2 scancodes and needs the translation
' table the monitor already carries; sharing that is the OS's job and
' not this file's.
' ---------------------------------------------------------------------

CONST SIZE   = 24576            ' the gap buffer, $2000..$7FFF
CONST SCREEN = $8200            ' the text map
CONST COLS   = 80
CONST ROWS   = 29               ' rows 1..29; row 0 is the status line

CONST UART_STAT = $FE70
CONST UART_DATA = $FE71
CONST VID_MODE  = $FE10
CONST CUR_X     = $FE22
CONST CUR_Y     = $FE23
CONST CUR_CTRL  = $FE24

' attributes: foreground in the low nibble, background in the high
CONST A_TEXT = $07
CONST A_KEY  = $0E
CONST A_NUM  = $0B
CONST A_REM  = $0A
CONST A_PUN  = $08
CONST A_STAT = $70

EXTERN KWTAB                    ' the keyword table, below

DIM buf(24575) AS BYTE AT $2000
DIM scr(8191) AS BYTE AT $8200

gs = 0                          ' gap start -- the cursor
ge = SIZE                       ' gap end
top = 0                         ' logical index of the first shown line
crow = 0                        ' cursor row on screen, 0..ROWS-1
ccol = 0
dirty = 0
done = 0
nlines = 1

' ---------------------------------------------------------------------
' The buffer, addressed logically.
' ---------------------------------------------------------------------

FUNCTION tlen() AS INT
  RETURN SIZE - ge + gs
END FUNCTION

FUNCTION chat(i AS INT) AS INT
  IF i < gs THEN
    RETURN buf(i)
  END IF
  RETURN buf(i + ge - gs)
END FUNCTION

SUB ins(c AS INT)
  IF gs < ge THEN
    buf(gs) = c
    gs = gs + 1
    dirty = 1
  END IF
END SUB

SUB delback()
  IF gs > 0 THEN
    gs = gs - 1
    dirty = 1
  END IF
END SUB

SUB delfwd()
  IF ge < SIZE THEN
    ge = ge + 1
    dirty = 1
  END IF
END SUB

SUB gapright()
  IF ge < SIZE THEN
    buf(gs) = buf(ge)
    gs = gs + 1
    ge = ge + 1
  END IF
END SUB

SUB gapleft()
  IF gs > 0 THEN
    gs = gs - 1
    ge = ge - 1
    buf(ge) = buf(gs)
  END IF
END SUB

' ---------------------------------------------------------------------
' Where lines begin and end.
' ---------------------------------------------------------------------

FUNCTION linestart(i AS INT) AS INT
  DO WHILE i > 0
    IF chat(i - 1) = 13 THEN
      RETURN i
    END IF
    i = i - 1
  LOOP
  RETURN 0
END FUNCTION

FUNCTION nextline(i AS INT) AS INT
  DIM n AS INT
  n = tlen()
  DO WHILE i < n
    IF chat(i) = 13 THEN
      RETURN i + 1
    END IF
    i = i + 1
  LOOP
  RETURN n
END FUNCTION

FUNCTION prevline(i AS INT) AS INT
  DIM s AS INT
  s = linestart(i)
  IF s = 0 THEN
    RETURN 0
  END IF
  RETURN linestart(s - 1)
END FUNCTION

' ---------------------------------------------------------------------
' Syntax colouring.
'
' A word is looked up in a table of length-prefixed keywords held in an
' ASM block, because the language has no strings yet and a table of
' bytes is what the tokeniser wants anyway.
' ---------------------------------------------------------------------

FUNCTION isalpha(c AS INT) AS INT
  IF c > 64 THEN
    IF c < 91 THEN
      RETURN 1
    END IF
  END IF
  IF c > 96 THEN
    IF c < 123 THEN
      RETURN 1
    END IF
  END IF
  RETURN 0
END FUNCTION

FUNCTION isdigit(c AS INT) AS INT
  IF c > 47 THEN
    IF c < 58 THEN
      RETURN 1
    END IF
  END IF
  RETURN 0
END FUNCTION

FUNCTION upper(c AS INT) AS INT
  IF c > 96 THEN
    IF c < 123 THEN
      RETURN c - 32
    END IF
  END IF
  RETURN c
END FUNCTION

' Is the word of `n` characters starting at logical `i` a keyword?
FUNCTION iskeyword(i AS INT, n AS INT) AS INT
  DIM p AS INT
  DIM m AS INT
  DIM k AS INT
  DIM hit AS INT
  p = KWTAB
  DO WHILE PEEK(p) <> 0
    m = PEEK(p)
    IF m = n THEN
      k = 0
      hit = 1
      DO WHILE k < n
        IF upper(chat(i + k)) <> PEEK(p + 1 + k) THEN
          hit = 0
        END IF
        k = k + 1
      LOOP
      IF hit = 1 THEN
        RETURN 1
      END IF
    END IF
    p = p + m + 1
  LOOP
  RETURN 0
END FUNCTION

' ---------------------------------------------------------------------
' Drawing.
' ---------------------------------------------------------------------

SUB clearrow(r AS INT)
  DIM base AS INT
  DIM c AS INT
  base = r * 256
  c = 0
  DO WHILE c < COLS
    scr(base + c + c) = 32
    scr(base + c + c + 1) = A_TEXT
    c = c + 1
  LOOP
END SUB

' Draw one logical line at screen row r, starting from buffer index i.
' Returns the index just past the line.
FUNCTION drawline(r AS INT, i AS INT) AS INT
  DIM base AS INT
  DIM n AS INT
  DIM c AS INT
  DIM incom AS INT
  DIM ch AS INT
  DIM a AS INT
  DIM w AS INT
  DIM k AS INT
  base = r * 256
  n = tlen()
  c = 0
  incom = 0
  CALL clearrow(r)
  DO WHILE i < n
    ch = chat(i)
    IF ch = 13 THEN
      RETURN i + 1
    END IF
    a = A_TEXT
    IF incom = 1 THEN
      a = A_REM
    ELSE
      IF ch = 39 THEN
        incom = 1
        a = A_REM
      ELSE
        IF isdigit(ch) <> 0 THEN
          a = A_NUM
        ELSE
          IF isalpha(ch) <> 0 THEN
            ' measure the word, then colour all of it at once
            w = 0
            DO WHILE isalpha(chat(i + w)) <> 0
              w = w + 1
            LOOP
            a = A_TEXT
            IF iskeyword(i, w) <> 0 THEN
              a = A_KEY
            END IF
            k = 0
            DO WHILE k < w
              IF c < COLS THEN
                scr(base + c + c) = chat(i + k)
                scr(base + c + c + 1) = a
                c = c + 1
              END IF
              k = k + 1
            LOOP
            i = i + w
            a = 0
          ELSE
            a = A_PUN
          END IF
        END IF
      END IF
    END IF
    IF a <> 0 THEN
      IF c < COLS THEN
        scr(base + c + c) = ch
        scr(base + c + c + 1) = a
        c = c + 1
      END IF
      i = i + 1
    END IF
  LOOP
  RETURN n
END FUNCTION

SUB drawall()
  DIM i AS INT
  DIM r AS INT
  i = top
  r = 1
  DO WHILE r <= ROWS
    IF i <= tlen() THEN
      i = drawline(r, i)
    ELSE
      CALL clearrow(r)
    END IF
    r = r + 1
  LOOP
END SUB

' Put the hardware cursor where the gap is, scrolling the view if the
' gap has left the window.
SUB locate()
  DIM i AS INT
  DIM r AS INT
  ' Count the line breaks between the top of the window and the gap.
  ' The earlier version walked line by line and asked whether the next
  ' line started past the cursor, which is one short whenever the cursor
  ' sits exactly at the end of the text -- and that is where a cursor
  ' spends most of its life while someone is typing.
  i = top
  r = 0
  DO WHILE i < gs
    IF chat(i) = 13 THEN
      r = r + 1
    END IF
    i = i + 1
  LOOP
  crow = r
  ccol = gs - linestart(gs)
  IF ccol > COLS - 1 THEN
    ccol = COLS - 1
  END IF
  POKE CUR_X, ccol
  POKE CUR_Y, crow + 1
END SUB

SUB scrollfit()
  DIM guard AS INT
  ' if the cursor is above the window, walk top back to its line
  IF gs < top THEN
    top = linestart(gs)
  END IF
  ' if it is below, walk top forward until it is inside
  guard = 0
  DO
    CALL locate()
    IF crow < ROWS THEN
      EXIT DO
    END IF
    top = nextline(top)
    guard = guard + 1
  LOOP WHILE guard < 200
END SUB

SUB status()
  DIM c AS INT
  DIM n AS INT
  base = 0
  c = 0
  DO WHILE c < COLS
    scr(c + c) = 32
    scr(c + c + 1) = A_STAT
    c = c + 1
  LOOP
  ' "COOL8 EDIT  bytes:NNNNN  line:NNNN  *"
  CALL puttext(2, 67, 79, 79, 76, 56)
  n = tlen()
  CALL putnum(20, n)
  CALL putnum(32, crow + 1)
  IF dirty <> 0 THEN
    scr(2 * 78) = 42
    scr(2 * 78 + 1) = A_STAT
  END IF
END SUB

SUB puttext(c AS INT, a AS INT, b AS INT, d AS INT, e AS INT, f AS INT)
  scr(c + c) = a
  scr(c + c + 1) = A_STAT
  scr(c + c + 2) = b
  scr(c + c + 3) = A_STAT
  scr(c + c + 4) = d
  scr(c + c + 5) = A_STAT
  scr(c + c + 6) = e
  scr(c + c + 7) = A_STAT
  scr(c + c + 8) = f
  scr(c + c + 9) = A_STAT
END SUB

SUB putnum(c AS INT, v AS INT)
  DIM d AS INT
  DIM lead AS INT
  DIM q AS INT
  d = 10000
  lead = 0
  DO WHILE d > 0
    q = 0
    DO WHILE v >= d
      v = v - d
      q = q + 1
    LOOP
    IF q <> 0 THEN
      lead = 1
    END IF
    IF lead <> 0 THEN
      scr(c + c) = 48 + q
      scr(c + c + 1) = A_STAT
      c = c + 1
    END IF
    IF d = 10000 THEN
      d = 1000
    ELSE
      IF d = 1000 THEN
        d = 100
      ELSE
        IF d = 100 THEN
          d = 10
        ELSE
          IF d = 10 THEN
            d = 1
          ELSE
            d = 0
          END IF
        END IF
      END IF
    END IF
  LOOP
  IF lead = 0 THEN
    scr(c + c) = 48
    scr(c + c + 1) = A_STAT
  END IF
END SUB

' ---------------------------------------------------------------------
' Movement.
' ---------------------------------------------------------------------

SUB left()
  CALL gapleft()
END SUB

SUB right()
  CALL gapright()
END SUB

SUB up()
  DIM col AS INT
  DIM p AS INT
  col = gs - linestart(gs)
  p = prevline(gs)
  CALL gotoline(p, col)
END SUB

SUB down()
  DIM col AS INT
  DIM p AS INT
  col = gs - linestart(gs)
  p = nextline(gs)
  IF p > tlen() THEN
    RETURN
  END IF
  CALL gotoline(p, col)
END SUB

' Move the gap to `start` + `col`, stopping at the end of that line.
SUB gotoline(start AS INT, col AS INT)
  DIM k AS INT
  DO WHILE gs > start
    CALL gapleft()
  LOOP
  DO WHILE gs < start
    CALL gapright()
  LOOP
  k = 0
  DO WHILE k < col
    IF gs >= tlen() THEN
      EXIT DO
    END IF
    IF chat(gs) = 13 THEN
      EXIT DO
    END IF
    CALL gapright()
    k = k + 1
  LOOP
END SUB

SUB home()
  DIM s AS INT
  s = linestart(gs)
  DO WHILE gs > s
    CALL gapleft()
  LOOP
END SUB

SUB endline()
  DO WHILE gs < tlen()
    IF chat(gs) = 13 THEN
      EXIT DO
    END IF
    CALL gapright()
  LOOP
END SUB

' ---------------------------------------------------------------------
' Files, through sw/fs.asm.
' ---------------------------------------------------------------------

SUB savefile()
  DIM n AS INT
  n = tlen()
  ' Close the gap, so the text is contiguous from buf(0) and fs_save can
  ' read it straight out of memory.
  DO WHILE ge < SIZE
    CALL gapright()
  LOOP
  CALL fssave(n)
  dirty = 0
END SUB

SUB fssave(n AS INT)
  ' The parameter is on the stack, where the calling convention puts it:
  ' [SP+0..1] is the return address and [SP+2..3] is the first argument.
  ASM
        LD   R0,[SP+2]
        ST   [fslen],R0
        LD   R0,[SP+3]
        ST   [fslen+1],R0
        CLR  R0
        CALL fs_mount
        LDW  X,#edname
        LDW  Y,#$2000
        CALL fs_save
  END ASM
END SUB

SUB loadfile()
  ASM
        CLR  R0
        CALL fs_mount
        LDW  X,#edname
        LDW  Y,#$2000
        CALL fs_load
        LD   R0,[fslen]
        ST   [v_ln],R0
        LD   R0,[fslen+1]
        ST   [v_ln+1],R0
  END ASM
  gs = ln
  ge = SIZE
  top = 0
  dirty = 0
  ' Put the cursor at the top, the way opening a file should.
  '
  ' Leaving it at the end is what a naive load does, and with top still
  ' at 0 the next scrollfit walks from the start of the file to the
  ' cursor once per line it has to scroll past -- O(lines squared), and
  ' on a 1,010-line file that is hundreds of millions of clocks. Moving
  ' the gap is O(bytes), once.
  DO WHILE gs > 0
    CALL gapleft()
  LOOP
END SUB

' ---------------------------------------------------------------------
' The loop.
' ---------------------------------------------------------------------

' Testing one bit needs an AND, which the language has not got yet, so
' this is four instructions of assembly rather than a division.
FUNCTION getkey() AS INT
  ASM
.gk:    LD   R0,[$FE70]
        BTST R0,#$01
        BEQ  .gk
        LD   R0,[$FE71]
        CLR  R1
        RET
  END ASM
END FUNCTION

ln = 0
full = 1
oldtop = 0
POKE VID_MODE, $80
POKE CUR_CTRL, $19              ' on, block, no blink

CALL drawall()
CALL scrollfit()
CALL status()

DO
  k = getkey()
  full = 1
  IF k = 27 THEN
    k = getkey()
    IF k = 91 THEN
      k = getkey()
      IF k = 65 THEN
        CALL up()
      END IF
      IF k = 66 THEN
        CALL down()
      END IF
      IF k = 67 THEN
        CALL right()
      END IF
      IF k = 68 THEN
        CALL left()
      END IF
      IF k = 72 THEN
        CALL home()
      END IF
      IF k = 70 THEN
        CALL endline()
      END IF
    END IF
  ELSE
    IF k = 13 THEN
      CALL ins(13)
      nlines = nlines + 1
    ELSE
      IF k = 8 THEN
        CALL delback()
      ELSE
        IF k = 127 THEN
          CALL delback()
        ELSE
          IF k = 4 THEN
            CALL delfwd()
          ELSE
            IF k = 19 THEN
              CALL savefile()
            ELSE
              IF k = 12 THEN
                CALL loadfile()
              ELSE
                IF k = 17 THEN
                  done = 1
                ELSE
                  IF k > 31 THEN
                    CALL ins(k)
                    full = 0
                  END IF
                END IF
              END IF
            END IF
          END IF
        END IF
      END IF
    END IF
  END IF
  ' Redraw the whole window only when the structure moved. Typing a
  ' character changes one row, and drawing 29 of them for it is the
  ' difference between an editor that keeps up and one that does not.
  oldtop = top
  CALL scrollfit()
  IF full = 1 THEN
    CALL drawall()
  ELSE
    IF oldtop <> top THEN
      CALL drawall()
    ELSE
      j = linestart(gs)
      k = drawline(crow + 1, j)
    END IF
  END IF
  CALL status()
LOOP WHILE done = 0
END

ASM
; ---- the keyword table: a length byte, then the letters, then a zero
KWTAB:
        .byte 3, "S","U","B"
        .byte 3, "D","I","M"
        .byte 3, "F","O","R"
        .byte 3, "E","N","D"
        .byte 2, "I","F"
        .byte 2, "D","O"
        .byte 2, "T","O"
        .byte 2, "A","S"
        .byte 4, "L","O","O","P"
        .byte 4, "N","E","X","T"
        .byte 4, "T","H","E","N"
        .byte 4, "E","L","S","E"
        .byte 4, "E","X","I","T"
        .byte 5, "W","H","I","L","E"
        .byte 5, "U","N","T","I","L"
        .byte 5, "C","O","N","S","T"
        .byte 6, "R","E","T","U","R","N"
        .byte 8, "F","U","N","C","T","I","O","N"
        .byte 0

edname: .ascii "SOURCE  BAS"

        .include "SW_FS_ASM"
END ASM
