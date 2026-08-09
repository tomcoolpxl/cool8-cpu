' ---------------------------------------------------------------------
' basic.bas -- COOL8 BASIC, the system.
'
' One screen, a cursor, and a Return key. Type a line and it runs; put a
' number in front and it is stored instead. That is the whole model, and
' it is the Commodore one because it is the right one: no modes, no
' panes, nothing to switch between.
'
' ## The screen is the buffer
'
' There is no edit buffer. LIST puts lines on the screen; you move the
' cursor onto one, type over it, and press Return anywhere on the row.
' The system reads the whole 80-character row back, and if it starts
' with a number, that line replaces whatever line had that number.
'
' Editing a program and entering one are therefore the same operation,
' which is why this needs a fraction of the machinery a separate editor
' does.
'
' ## Where things live (OS_PLAN section 2.1)
'
'   $0200-$7FFF   program text, then compiled code, variables, strings
'   $8000-$9FFF   the screen: 128x32 cells at stride 256, 80x30 shown
'   $A000-$FDFF   this program
'
' The map must be 8 KB aligned -- the row wrap is a mask, not a compare
' -- so the screen sits at $8000 or $A000 and nowhere between. It is at
' $8000 because that is where mode 0's preset, the boot ROM's banner and
' the monitor already put it; the editor used to override the preset to
' $A000, and that override was the only thing forcing this program up to
' $C000. Moving it back buys 8 KB of system space for 8 KB of program
' space, and leaves one screen base instead of three.
'
' Program text grows up from $0200 and is kept in ascending line order,
' tokenised: keywords become one byte each, which measured 23 % smaller
' than storing the text.
' ---------------------------------------------------------------------

EXTERN TOKTAB
EXTERN CMDTAB
EXTERN BANNERTAB
EXTERN ERRTAB
EXTERN RUNTAB
EXTERN iisr
EXTERN irring
EXTERN irhead
EXTERN irtail
EXTERN ibreak
EXTERN MSGFREE
EXTERN MSGKFREE

CONST SCREEN  = $8000
CONST PROG    = $0200           ' program text starts here
CONST MEMTOP  = $7FFF
' The user area really ends here. RUN puts the string accumulator at
' $7F00 and the CALL stack at $7EE0, so the top 288 bytes are not a
' program's to fill. FREE reported MEMTOP - progend, and a program
' that believed it would have run into both.
CONST USERTOP = $7EDF
CONST COLS    = 80
CONST ROWS    = 30

CONST VID_MODE   = $FE10
CONST VID_BASE_L = $FE12
CONST VID_BASE_H = $FE13
CONST CUR_X      = $FE22
CONST CUR_Y      = $FE23
CONST CUR_CTRL   = $FE24
CONST UART_STAT  = $FE70
CONST UART_DATA  = $FE71

' attributes: foreground in the low nibble, background in the high
CONST A_TEXT = $07
CONST A_BANR = $0B
CONST A_HEAD = $08
CONST A_VAL  = $0F
CONST A_FREE = $0E
CONST A_ERR  = $04

' key codes above 255 -- the decoder returns these for named keys
CONST K_UP    = 256
CONST K_DOWN  = 257
CONST K_LEFT  = 258
CONST K_RIGHT = 259
CONST K_HOME  = 260
CONST K_END   = 261
CONST K_DEL   = 262
CONST K_INS   = 263

' A numeric literal, stored as two binary bytes rather than as digits.
' Without it a loop re-parses decimal on every iteration, which is most
' of what makes an interpreted FOR slow. Appended, so saved programs
' keep working -- TOKTAB order is frozen.
CONST T_LIT   = $A4

DIM cx AS BYTE                  ' cursor column on screen
DIM cy AS BYTE                  ' cursor row on screen
DIM vtop AS BYTE                ' which map row is displayed at the top
' CARD, not INT: $9FFF is 40,959 and as a signed value that is
' negative, which makes every bounds check on an address backwards.
DIM progend AS CARD             ' first free byte of program text
DIM lbuf(127) AS BYTE           ' the line being worked on, as text
DIM llen AS BYTE
DIM tbuf(127) AS BYTE           ' the same line, tokenised
DIM tlen AS BYTE

' ---------------------------------------------------------------------
' Screen addressing.
'
' Scrolling moves the origin rather than the memory: the fetch engine
' wraps the row pointer inside stride*32, so displayed row r is map row
' (vtop + r) AND 31 and scrolling is one register write.
' ---------------------------------------------------------------------

FUNCTION rowaddr(r AS INT) AS CARD
  RETURN SCREEN + (((vtop + r) AND 31) << 8)
END FUNCTION

SUB putat(r AS INT, c AS INT, ch AS INT, a AS INT)
  DIM p AS CARD
  IF c > COLS - 1 THEN
    RETURN
  END IF
  p = rowaddr(r) + c + c
  POKE p, ch
  POKE p + 1, a
END SUB

FUNCTION getat(r AS INT, c AS INT) AS INT
  RETURN PEEK(rowaddr(r) + c + c)
END FUNCTION

SUB clearrow(r AS INT)
  DIM c AS BYTE
  c = 0
  DO WHILE c < COLS
    CALL putat(r, c, 32, A_TEXT)
    c = c + 1
  LOOP
END SUB

SUB cls()
  DIM r AS BYTE
  r = 0
  DO WHILE r < 32
    CALL clearrow(r)
    r = r + 1
  LOOP
  cx = 0
  cy = 0
  CALL showcur()
END SUB

SUB showcur()
  POKE CUR_X, cx
  POKE CUR_Y, cy
END SUB

' One register write, and clear the row that just came into view.
SUB scroll()
  vtop = (vtop + 1) AND 31
  POKE VID_BASE_H, (SCREEN >> 8) + vtop
  CALL clearrow(ROWS - 1)
END SUB

SUB newline()
  cx = 0
  IF cy < ROWS - 1 THEN
    cy = cy + 1
  ELSE
    CALL scroll()
  END IF
  CALL showcur()
END SUB

SUB emit(ch AS INT)
  CALL putat(cy, cx, ch, A_TEXT)
  IF cx < COLS - 1 THEN
    cx = cx + 1
  ELSE
    CALL newline()
  END IF
  CALL showcur()
END SUB

SUB puts(s AS CARD)
  DIM c AS BYTE
  DO
    c = PEEK(s)
    IF c = 0 THEN
      EXIT DO
    END IF
    CALL emit(c)
    s = s + 1
  LOOP
END SUB

SUB putn(v AS CARD)
  DIM d AS CARD
  DIM q AS BYTE
  DIM lead AS BYTE
  ' An INT arrives as its bit pattern, so the top bit is its sign: say
  ' minus, then print the magnitude -- which in CARD arithmetic is
  ' exactly 0 - v, and -32768 comes out right for free. Nothing prints
  ' a true CARD above 32767: FREE's ceiling is 31967.
  IF v >= 32768 THEN
    CALL emit(45)
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
      CALL emit(48 + q)
    END IF
    IF d = 1 THEN
      EXIT DO
    END IF
    d = tenth(d)
  LOOP
  IF lead = 0 THEN
    CALL emit(48)
  END IF
END SUB

FUNCTION tenth(d AS CARD) AS CARD
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
' The keyboard.
'
' PS/2 Set 2 scancodes are what a keyboard sends, and are the only way
' to see a cursor key or Home. The serial console is decoded from ANSI
' into the same codes, so nothing above this cares which wire a key
' arrived on.
' ---------------------------------------------------------------------

FUNCTION getkey() AS INT
  DIM c AS INT
  DO
    c = serialkey()
    IF c <> 0 THEN
      RETURN c
    END IF
  LOOP
END FUNCTION

' Non-blocking: 0 if nothing is waiting.
'
' It reads the ring the interrupt fills, not the device. That is the
' C64's arrangement and the BBC's -- the interrupt keeps the input
' fresh and everything above it reads memory -- and it is what lets a
' *running* program be stopped, since a running program cannot poll.
' `.rk0` is still the "nothing waiting" branch: sim/test_basic.py
' settles on it.
FUNCTION rawkey() AS INT
  ASM
        LD   R0,[irtail]
        LD   R1,[irhead]
        CMP  R0,R1
        BEQ  .rk0
        PUSHW X
        LDW  X,#irring
        ADDW X,R0
        LD   R1,[X]
        POPW X
        ADD  R0,#1
        AND  R0,#15
        ST   [irtail],R0
        MOV  R0,R1
        CLR  R1
        RET
.rk0:   CLR  R0
        CLR  R1
        RET
  END ASM
END FUNCTION

FUNCTION waitraw() AS INT
  DIM c AS INT
  DO
    c = rawkey()
    IF c <> 0 THEN
      RETURN c
    END IF
  LOOP
END FUNCTION

' ESC [ A and friends into the named key codes -- and $80+n, which is
' what sw/kbd.asm returns for the same keys off the PS/2 port. The two
' wires meet here and nowhere else, so everything above this function
' sees one set of key codes whichever one a key arrived on.
FUNCTION serialkey() AS INT
  DIM c AS INT
  DIM d AS INT
  c = rawkey()
  IF c = 0 THEN
    RETURN 0
  END IF
  IF c >= 128 THEN
    RETURN K_UP + (c - 128)
  END IF
  IF c <> 27 THEN
    RETURN c
  END IF
  ' A lone Escape is Escape. Waiting for the rest of a sequence that is
  ' never coming would hang a game's loop on the one key it is most
  ' likely to test for; a terminal sends ESC [ A in a single burst and
  ' the interrupt has the whole of it in the ring before anything looks.
  IF PEEK(irhead) = PEEK(irtail) THEN
    RETURN 27
  END IF
  d = waitraw()
  IF d <> 91 THEN
    IF d <> 79 THEN
      RETURN 27
    END IF
  END IF
  d = waitraw()
  IF d = 65 THEN
    RETURN K_UP
  END IF
  IF d = 66 THEN
    RETURN K_DOWN
  END IF
  IF d = 67 THEN
    RETURN K_RIGHT
  END IF
  IF d = 68 THEN
    RETURN K_LEFT
  END IF
  IF d = 72 THEN
    RETURN K_HOME
  END IF
  IF d = 70 THEN
    RETURN K_END
  END IF
  IF d = 51 THEN
    d = waitraw()
    RETURN K_DEL
  END IF
  IF d = 50 THEN
    d = waitraw()
    RETURN K_INS
  END IF
  RETURN 27
END FUNCTION

' ---------------------------------------------------------------------
' Reading a logical line back off the screen.
'
' This is the whole trick: Return does not read what you typed, it reads
' what is on the row. Move the cursor onto a listed line, change a
' character, press Return, and the line is re-entered.
' ---------------------------------------------------------------------

SUB readrow(r AS INT)
  DIM c AS BYTE
  DIM last AS BYTE
  c = 0
  last = 0
  DO WHILE c < COLS
    lbuf(c) = getat(r, c)
    IF lbuf(c) <> 32 THEN
      last = c + 1
    END IF
    c = c + 1
  LOOP
  llen = last
END SUB

' ---------------------------------------------------------------------
' Tokenising.
'
' A word that is a keyword becomes one byte >= $80; everything else is
' copied. Quoted text and comments are copied whole -- PRINT "FOR" must
' not become PRINT <FOR-token>.
' ---------------------------------------------------------------------



' A character that can appear inside a name: a letter, a digit, or _.


' The token for the word of `n` characters at lbuf(i), or 0.
' The character classes live in their own file because the compiler's
' lexer needs exactly the same ones, and two copies would be two
' answers to "is this a letter".
INCLUDE "chars.bas"

FUNCTION lookup(i AS INT, n AS INT) AS INT
  DIM p AS CARD
  DIM m AS BYTE
  DIM k AS BYTE
  DIM hit AS BYTE
  DIM tok AS BYTE
  p = TOKTAB
  tok = $80
  DO WHILE PEEK(p) <> 0
    m = PEEK(p)
    IF m = n THEN
      k = 0
      hit = 1
      DO WHILE k < n
        IF upper(lbuf(i + k)) <> PEEK(p + 1 + k) THEN
          hit = 0
        END IF
        k = k + 1
      LOOP
      IF hit = 1 THEN
        RETURN tok
      END IF
    END IF
    p = p + m + 1
    tok = tok + 1
  LOOP
  RETURN 0
END FUNCTION

' A literal into tbuf as T_LIT and two bytes.
SUB puttnum(v AS CARD)
  tbuf(tlen) = T_LIT
  tlen = tlen + 1
  tbuf(tlen) = v AND 255
  tlen = tlen + 1
  tbuf(tlen) = v >> 8
  tlen = tlen + 1
END SUB

FUNCTION ishex(c AS INT) AS INT
  IF isdigit(c) <> 0 THEN
    RETURN 1
  END IF
  IF upper(c) > 64 THEN
    IF upper(c) < 71 THEN
      RETURN 1
    END IF
  END IF
  RETURN 0
END FUNCTION

FUNCTION hexof(c AS INT) AS INT
  IF isdigit(c) <> 0 THEN
    RETURN c - 48
  END IF
  RETURN upper(c) - 55
END FUNCTION

SUB tokenise()
  DIM i AS BYTE
  DIM v AS CARD
  DIM w AS BYTE
  DIM t AS BYTE
  DIM k AS BYTE
  DIM q AS BYTE
  i = 0
  tlen = 0
  q = 0
  DO WHILE i < llen
    IF lbuf(i) = 34 THEN
      q = 1 - q
    END IF
    IF q = 1 THEN
      tbuf(tlen) = lbuf(i)
      tlen = tlen + 1
      i = i + 1
    ELSE
      IF lbuf(i) = 39 THEN
        ' a comment runs to the end of the line, verbatim
        DO WHILE i < llen
          tbuf(tlen) = lbuf(i)
          tlen = tlen + 1
          i = i + 1
        LOOP
      ELSE
        IF isalpha(lbuf(i)) <> 0 THEN
          ' A whole identifier, digits and underscores included -- not
          ' just the letters. Scanning only letters split `x_end` into
          ' `x_` and `end`, and `end` is a keyword, so the tail of the
          ' name turned into a keyword token and the name came back from
          ' LIST as something else entirely.
          ' **Bounded by llen, and that is not decoration.**
          ' `shiftlbuf` slides the line down over the line number and
          ' shortens llen without clearing what it left behind, so
          ' `20 END` becomes `END` with `END` still sitting at lbuf(3).
          ' An unbounded scan read `ENDEND`, found no keyword, and
          ' stored six characters where the END token belonged -- so the
          ' interpreter walked off the end of the program instead of
          ' stopping. `PRINT` escaped it only because its own stale tail
          ' happened to begin with a space.
          w = 0
          DO WHILE i + w < llen
            IF isident(lbuf(i + w)) = 0 THEN
              EXIT DO
            END IF
            w = w + 1
          LOOP
          ' A trailing $ is part of the name, not the start of a hex
          ' literal. The suffix is the type -- it is what keeps A and A$
          ' apart -- so it is taken here, before the $ arm below can
          ' claim it. A bare $FE70 still parses as hex, because it does
          ' not follow an identifier.
          IF i + w < llen THEN
            IF lbuf(i + w) = 36 THEN
              w = w + 1
            END IF
          END IF
          ' REM starts a comment, as it does everywhere else. It is a
          ' comment and not a keyword, so nothing inside it is looked up
          ' and LIST gives back exactly what was typed.
          IF w = 3 THEN
            IF upper(lbuf(i)) = 82 THEN
              IF upper(lbuf(i + 1)) = 69 THEN
                IF upper(lbuf(i + 2)) = 77 THEN
                  DO WHILE i < llen
                    tbuf(tlen) = lbuf(i)
                    tlen = tlen + 1
                    i = i + 1
                  LOOP
                  w = 0
                END IF
              END IF
            END IF
          END IF
          t = lookup(i, w)
          IF w = 0 THEN
            t = 0
          END IF
          IF t <> 0 THEN
            tbuf(tlen) = t
            tlen = tlen + 1
          ELSE
            k = 0
            DO WHILE k < w
              tbuf(tlen) = lbuf(i + k)
              tlen = tlen + 1
              k = k + 1
            LOOP
          END IF
          i = i + w
        ELSE
          IF isdigit(lbuf(i)) <> 0 THEN
            v = 0
            DO WHILE i < llen
              IF isdigit(lbuf(i)) = 0 THEN
                EXIT DO
              END IF
              v = v * 10 + (lbuf(i) - 48)
              i = i + 1
            LOOP
            CALL puttnum(v)
          ELSE
            IF lbuf(i) = 36 THEN
              ' $ and hex digits
              v = 0
              i = i + 1
              DO WHILE i < llen
                IF ishex(lbuf(i)) = 0 THEN
                  EXIT DO
                END IF
                v = (v << 4) + hexof(lbuf(i))
                i = i + 1
              LOOP
              CALL puttnum(v)
            ELSE
              tbuf(tlen) = lbuf(i)
              tlen = tlen + 1
              i = i + 1
            END IF
          END IF
        END IF
      END IF
    END IF
  LOOP
END SUB

' A token byte back into its word, printed.
SUB puttok(t AS INT)
  DIM p AS CARD
  DIM m AS BYTE
  DIM k AS BYTE
  DIM n AS BYTE
  p = TOKTAB
  n = $80
  DO WHILE PEEK(p) <> 0
    m = PEEK(p)
    IF n = t THEN
      k = 0
      DO WHILE k < m
        CALL emit(PEEK(p + 1 + k))
        k = k + 1
      LOOP
      RETURN
    END IF
    p = p + m + 1
    n = n + 1
  LOOP
END SUB

' ---------------------------------------------------------------------
' The program: tokenised lines in ascending order.
'
'   lineno (2, little endian)   len (1)   tokens (len bytes)
'
' `len` makes skipping a line one add, so finding line n is a walk and
' not a search.
' ---------------------------------------------------------------------

FUNCTION lineno(p AS CARD) AS INT
  RETURN PEEK(p) + (PEEK(p + 1) << 8)
END FUNCTION

FUNCTION linelen(p AS CARD) AS INT
  RETURN PEEK(p + 2)
END FUNCTION

' A record is lineno(2) len(1) tokens(len) and then a zero, so the
' interpreter can ask "end of line?" with one load instead of a 16-bit
' compare against a maintained end pointer. The terminator is not
' counted in len, so LIST and the memmoves are unchanged.
FUNCTION nextline(p AS CARD) AS CARD
  RETURN p + 4 + linelen(p)
END FUNCTION

' The first line with a number >= n, or progend.
FUNCTION findline(n AS INT) AS CARD
  DIM p AS CARD
  p = PROG
  DO WHILE p < progend
    IF lineno(p) >= n THEN
      RETURN p
    END IF
    p = nextline(p)
  LOOP
  RETURN progend
END FUNCTION

SUB memmove(dst AS CARD, src AS CARD, n AS CARD)
  ' Overlapping copies both ways: growing a line moves the tail up,
  ' shrinking it moves the tail down, and the direction has to follow
  ' or the copy eats itself.
  '
  ' The count is tested at the top of each loop, before the borrow is
  ' propagated. Testing after it means R2:R3 has already wrapped to
  ' $FFFF and the loop never ends.
  ASM
        LD   R0,[SP+2]
        MOV  XL,R0
        LD   R0,[SP+3]
        MOV  XH,R0
        LD   R0,[SP+4]
        MOV  YL,R0
        LD   R0,[SP+5]
        MOV  YH,R0
        LD   R2,[SP+6]
        LD   R3,[SP+7]
        LD   R0,[SP+2]                  ; dst - src, 16-bit
        LD   R1,[SP+4]
        SUB  R0,R1
        LD   R0,[SP+3]
        LD   R1,[SP+5]
        SBC  R0,R1
        BLO  .up                        ; dst below src: walk up
        ADDW X,R2                       ; else point past the end
        MOV  R0,XH
        ADD  R0,R3
        MOV  XH,R0
        ADDW Y,R2
        MOV  R0,YH
        ADD  R0,R3
        MOV  YH,R0
.dn:    MOV  R0,R2
        OR   R0,R3
        BEQ  .mm9
        DECW X
        DECW Y
        LD   R0,[Y]
        ST   [X],R0
        SUB  R2,#1
        BCS  .dn
        SUB  R3,#1
        BRA  .dn
.up:    MOV  R0,R2
        OR   R0,R3
        BEQ  .mm9
        LD   R0,[Y]
        ST   [X],R0
        INCW X
        INCW Y
        SUB  R2,#1
        BCS  .up
        SUB  R3,#1
        BRA  .up
.mm9:
  END ASM
END SUB

' Store, replace or delete the line now in tbuf with number n.
SUB storeline(n AS INT)
  DIM p AS CARD
  DIM old AS INT
  DIM need AS INT
  DIM k AS BYTE
  p = findline(n)
  old = 0
  IF p < progend THEN
    IF lineno(p) = n THEN
      old = 4 + linelen(p)
    END IF
  END IF
  need = 0
  IF tlen > 0 THEN
    need = 4 + tlen
  END IF
  IF progend - old + need > USERTOP THEN
    CALL errmsg(1)
    RETURN
  END IF
  ' make the hole the right size
  IF need <> old THEN
    CALL memmove(p + need, p + old, progend - p - old)
    progend = progend - old + need
  END IF
  IF need = 0 THEN
    RETURN
  END IF
  POKE p, n AND 255
  POKE p + 1, n >> 8
  POKE p + 2, tlen
  k = 0
  DO WHILE k < tlen
    POKE p + 3 + k, tbuf(k)
    k = k + 1
  LOOP
  POKE p + 3 + tlen, 0          ' the end-of-line marker
END SUB

' ---------------------------------------------------------------------
' Commands.
' ---------------------------------------------------------------------

SUB list(a AS INT, b AS INT)
  DIM p AS CARD
  DIM k AS BYTE
  DIM t AS BYTE
  DIM v AS CARD
  p = PROG
  DO WHILE p < progend
    IF lineno(p) >= a THEN
      IF lineno(p) > b THEN
        RETURN
      END IF
      CALL putn(lineno(p))
      CALL emit(32)
      k = 0
      DO WHILE k < linelen(p)
        t = PEEK(p + 3 + k)
        IF t = T_LIT THEN
          ' a binary literal: two bytes, printed back as digits
          v = PEEK(p + 4 + k)
          v = v + (PEEK(p + 5 + k) << 8)
          CALL putn(v)
          k = k + 3
        ELSE
          IF t > 127 THEN
            CALL puttok(t)
          ELSE
            CALL emit(t)
          END IF
          k = k + 1
        END IF
      LOOP
      CALL newline()
    END IF
    p = nextline(p)
  LOOP
END SUB

SUB new()
  progend = PROG
END SUB

SUB renumber(start AS INT, step AS INT)
  DIM p AS CARD
  DIM n AS INT
  n = start
  p = PROG
  DO WHILE p < progend
    POKE p, n AND 255
    POKE p + 1, n >> 8
    n = n + step
    p = nextline(p)
  LOOP
END SUB

SUB deleterange(a AS INT, b AS INT)
  DIM p AS CARD
  DIM q AS CARD
  p = findline(a)
  q = p
  DO WHILE q < progend
    IF lineno(q) > b THEN
      EXIT DO
    END IF
    q = nextline(q)
  LOOP
  IF q > p THEN
    CALL memmove(p, q, progend - q)
    progend = progend - (q - p)
  END IF
END SUB

FUNCTION freebytes() AS CARD
  RETURN USERTOP - progend
END FUNCTION

' ---------------------------------------------------------------------
' Errors, C64-shaped: short, because string space is scarce.
' ---------------------------------------------------------------------

' ---------------------------------------------------------------------
' RUN.
'
' The interpreter walks the program the editor is holding -- there is no
' compile step and no second copy -- so all this does is tell it where
' everything is, assemble any ASM blocks, and go.
'
' The map above the program, from the top down:
'
'   $7F00-$7FFF   the string accumulator, 256 bytes
'   $7EE0-$7EFF   the CALL stack, 8 frames of 4
'   ...-$7EDF     the heap, growing down
'   codetop...    the name table, growing up
'   progend...    the assembled ASM blocks
'   $0200...      the program text
'
' The name table starts where the assembled code ends, which is why the
' assembly pass runs first: until it has, codetop is not known.
' ---------------------------------------------------------------------
SUB dorun()
  DIM e AS BYTE
  DIM p AS CARD
  ASM
        MOV  R0,#$00            ; LREC = PROG, the first record
        ST   [$0014],R0
        MOV  R0,#$02
        ST   [$0015],R0
        MOV  R0,#$00            ; ACBASE: code goes after the program
        ST   [$00DC],R0
        MOV  R0,#$7F            ; SACC = $7F00
        ST   [$0034],R0
        MOV  R0,#$00
        ST   [$0033],R0
        MOV  R0,#$E0            ; CSTK = $7EE0
        ST   [$003C],R0
        MOV  R0,#$7E
        ST   [$003D],R0
        MOV  R0,#$DF            ; HEAP comes down from $7EDF
        ST   [$002A],R0
        MOV  R0,#$7E
        ST   [$002B],R0
  END ASM
  ' PEND and the code base need progend, which is a BASIC variable
  POKE $0016, progend AND 255
  POKE $0017, progend >> 8
  POKE $00DC, progend AND 255
  POKE $00DD, progend >> 8
  ASM
        MOV  R0,#$00            ; the assembly pass, over the whole
        MOV  R1,#$02            ;   program, before a statement runs
        CALL aprog
        LD   R0,[$0018]         ; did it fault?
        TST  R0
        BNE  .out
        LD   R0,[$00DA]         ; the name table starts where the
        ST   [$0027],R0         ;   assembled code ended
        LD   R0,[$00DB]
        ST   [$0028],R0
        MOV  R0,#$00            ; and LREC goes back to the first
        ST   [$0014],R0         ;   record: the assembly pass walked it
        MOV  R0,#$02            ;   all the way to the end
        ST   [$0015],R0
        CALL irun
.out:
  END ASM
  ' Whatever mode, scroll or noise the program left behind, the editor
  ' gets its screen and its quiet back before a word is said about how
  ' the run ended. The palette is deliberately NOT restored -- the
  ' default lives in the boot stub, which the first typed line
  ' reclaimed, and a changed palette is a look, not a fault.
  POKE $FE10, $80
  POKE VID_BASE_L, 0
  POKE VID_BASE_H, (SCREEN >> 8) + vtop
  POKE $FE16, 0
  POKE $FE17, 0
  POKE $FE18, 0
  POKE $FE19, 0
  p = 4
  DO
  POKE $FE50, p
  POKE $FE51, 0
  POKE $FE51, 0
  p = p + 8
  LOOP WHILE p < 68
  e = PEEK($0018)
  IF e <> 255 THEN
    IF e <> 0 THEN
      CALL runerr(e)
    END IF
  END IF
END SUB

' ?<what> IN <line>. LREC still holds the record that failed, so the
' line number is a read rather than a search.
SUB runerr(n AS INT)
  DIM p AS CARD
  DIM k AS BYTE
  DIM r AS CARD
  p = RUNTAB
  k = 1
  DO WHILE k < n
    DO WHILE PEEK(p) <> 0
      p = p + 1
    LOOP
    p = p + 1
    k = k + 1
  LOOP
  CALL emit(63)
  CALL puts(p)
  r = PEEK($0014) + (PEEK($0015) << 8)
  IF r >= PROG THEN
    IF r < progend THEN
      CALL emit(32)
      CALL emit(73)
      CALL emit(78)
      CALL emit(32)
      CALL putn(lineno(r))
    END IF
  END IF
  CALL newline()
END SUB

' puts' length-counted sibling. A heap string carries its length rather
' than a terminator, so PRINT of one cannot go through puts -- which
' would run on into whatever follows it in the accumulator.
SUB putsn(p AS CARD, n AS INT)
  DIM k AS BYTE
  k = 0
  DO WHILE k < n
    CALL emit(PEEK(p + k))
    k = k + 1
  LOOP
END SUB

SUB errmsg(n AS INT)
  DIM p AS CARD
  DIM k AS BYTE
  p = ERRTAB
  k = 0
  DO WHILE k < n
    DO WHILE PEEK(p) <> 0
      p = p + 1
    LOOP
    p = p + 1
    k = k + 1
  LOOP
  CALL emit(63)
  CALL puts(p)
  CALL newline()
END SUB


' ---------------------------------------------------------------------
' Files.
'
' sw/fs.asm does the flash; this turns a typed name into the eleven-byte
' 8.3 field the directory holds, and hands it the program text.
'
' The volume is log-structured, so SAVE over a name that already exists
' deletes the old entry and appends a new one at the tail. On NOR flash
' that is the cheap operation and not the expensive one: programming can
' only clear bits, so deleting is one byte cleared to $00 and writing is
' bytes that are still $FF. Nothing is erased and nothing is rewritten in
' place, and no 4 KB buffer is needed anywhere.
' ---------------------------------------------------------------------

' Two of fs.asm's variables, by address, because BASIC cannot see an
' assembler equate. They must track FSVARS in sw/fs.asm, which is at
' $0074 -- it was moved out of $0100 so that page 1 is the CPU stack and
' nothing else. If fs.asm moves again these move with it.
CONST FSENT = $007B             ' fs.asm's fsent -- FSVARS+7
CONST FSFPG = $0078             ' and its first free page -- FSVARS+4
CONST VOLPGS = 1776             ' data pages; the rest is scratch

DIM fname(10) AS BYTE           ' 8.3, space padded, upper case
DIM faddr AS CARD               ' where the bytes are, or go
DIM flen AS CARD                ' how many of them
DIM fdrv AS BYTE                ' the mounted drive
DIM fidx AS BYTE                ' the directory entry DIR is reading
DIM fok AS BYTE                 ' did the last call succeed

SUB fsmount()
  ASM
        LD   R0,[v_fdrv]
        CALL fs_mount
  END ASM
END SUB

SUB fsfind()
  ASM
        LDW  X,#a_fname
        CALL fs_find
        BCC  .fn1
        LD   R0,[fsent+14]
        ST   [v_flen],R0
        LD   R0,[fsent+15]
        ST   [v_flen+1],R0
        MOV  R0,#1
        BRA  .fn2
.fn1:   CLR  R0
.fn2:   ST   [v_fok],R0
  END ASM
END SUB

SUB fssave()
  ASM
        LD   R0,[v_flen]
        ST   [fslen],R0
        LD   R0,[v_flen+1]
        ST   [fslen+1],R0
        LDW  X,#a_fname
        LDW  Y,[v_faddr]
        CALL fs_save
        BCC  .sv1
        MOV  R0,#1
        BRA  .sv2
.sv1:   CLR  R0
.sv2:   ST   [v_fok],R0
  END ASM
END SUB

SUB fsload()
  ASM
        LDW  X,#a_fname
        LDW  Y,[v_faddr]
        CALL fs_load
        BCC  .ld1
        LD   R0,[fslen]
        ST   [v_flen],R0
        LD   R0,[fslen+1]
        ST   [v_flen+1],R0
        MOV  R0,#1
        BRA  .ld2
.ld1:   CLR  R0
.ld2:   ST   [v_fok],R0
  END ASM
END SUB

SUB fserase()
  ASM
        LDW  X,#a_fname
        CALL fs_delete
        BCC  .er1
        MOV  R0,#1
        BRA  .er2
.er1:   CLR  R0
.er2:   ST   [v_fok],R0
  END ASM
END SUB

' ---- whole pages, for COMPACT

DIM pbuf(255) AS BYTE           ' one page in transit
DIM cpage AS INT                ' the page it comes from or goes to

SUB rdpage(p AS INT)
  cpage = p
  ASM
        LD   R0,[v_cpage]
        ST   [fspg],R0
        LD   R0,[v_cpage+1]
        ST   [fspg+1],R0
        LDW  X,#a_pbuf
        STW  [fsbuf],X
        CALL fs_rdpg
  END ASM
END SUB

SUB wrpage(p AS INT)
  cpage = p
  ASM
        LD   R0,[v_cpage]
        ST   [fspg],R0
        LD   R0,[v_cpage+1]
        ST   [fspg+1],R0
        LDW  X,#a_pbuf
        STW  [fsbuf],X
        CALL fs_wrpg
  END ASM
END SUB

SUB erasesect(p AS INT)
  cpage = p
  ASM
        LD   R0,[v_cpage]
        ST   [fspg],R0
        LD   R0,[v_cpage+1]
        ST   [fspg+1],R0
        CALL fs_erapg
  END ASM
END SUB

' Read directory entry `fidx` into fs.asm's fsent, where DIR PEEKs it.
SUB fsreadent()
  ASM
        LD   R0,[v_fidx]
        CALL fs_seekent
        CALL fls_seek
        CALL fls_open
        CALL fs_rdent
        CALL fls_close
  END ASM
END SUB

' ---------------------------------------------------------------------
' The command line: what Return does with a row.
' ---------------------------------------------------------------------

DIM ip AS BYTE                  ' where the parser is in lbuf

SUB skipsp()
  DO WHILE ip < llen
    IF lbuf(ip) <> 32 THEN
      EXIT DO
    END IF
    ip = ip + 1
  LOOP
END SUB

' A decimal number at ip, or -1 if there is not one.
FUNCTION number() AS INT
  DIM v AS INT
  DIM any AS BYTE
  v = 0
  any = 0
  CALL skipsp()
  ' A comma between arguments is a separator, not a value. RENUMBER
  ' 100,5 was reading the step as absent and defaulting it to 10.
  IF ip < llen THEN
    IF lbuf(ip) = 44 THEN
      ip = ip + 1
      CALL skipsp()
    END IF
  END IF
  DO WHILE ip < llen
    IF isdigit(lbuf(ip)) = 0 THEN
      EXIT DO
    END IF
    v = v * 10 + (lbuf(ip) - 48)
    any = 1
    ip = ip + 1
  LOOP
  IF any = 0 THEN
    RETURN 0 - 1
  END IF
  RETURN v
END FUNCTION

' A file name at ip -- NAME, "NAME", or either with .EXT -- into fname as
' the eleven-byte 8.3 field the directory holds. 1 if there was one.
FUNCTION parsename() AS INT
  DIM k AS BYTE
  DIM c AS BYTE
  DIM q AS BYTE
  k = 0
  DO WHILE k < 11
    fname(k) = 32
    k = k + 1
  LOOP
  CALL skipsp()
  q = 0
  IF ip < llen THEN
    IF lbuf(ip) = 34 THEN
      q = 1
      ip = ip + 1
    END IF
  END IF
  k = 0
  DO WHILE ip < llen
    c = upper(lbuf(ip))
    IF c = 34 THEN
      ip = ip + 1
      EXIT DO
    END IF
    IF q = 0 THEN
      IF c = 32 THEN
        EXIT DO
      END IF
      IF c = 44 THEN
        EXIT DO
      END IF
    END IF
    IF c = 46 THEN
      k = 8
    ELSE
      IF k < 11 THEN
        fname(k) = c
        k = k + 1
      END IF
    END IF
    ip = ip + 1
  LOOP
  IF fname(0) = 32 THEN
    RETURN 0
  END IF
  ' Nothing typed after the dot: a program is a .BAS.
  IF fname(8) = 32 THEN
    fname(8) = 66
    fname(9) = 65
    fname(10) = 83
  END IF
  RETURN 1
END FUNCTION

SUB dosave()
  DIM had AS BYTE
  IF parsename() = 0 THEN
    CALL errmsg(0)
    RETURN
  END IF
  ' Write first, delete second -- the order matters twice over.
  '
  ' Deleting first would drop the old file out of the scan that derives
  ' the free pointer, so the new version would be programmed on top of
  ' the old one's pages. Those pages are not $FF any more and
  ' programming only clears bits, so what came back would be the two
  ' versions ANDed together.
  '
  ' It is also the safe order across a power cut: the worst that can be
  ' interrupted is a second copy nobody is using yet, and the old one
  ' still loads. fs_find takes the first match scanning from entry zero,
  ' which is the older of the two, so the delete afterwards removes the
  ' right one.
  CALL fsfind()
  had = fok
  faddr = PROG
  flen = progend - PROG
  CALL fssave()
  IF fok = 0 THEN
    CALL errmsg(3)
    RETURN
  END IF
  IF had <> 0 THEN
    CALL fserase()
  END IF
END SUB

' Copy the stored line at p into tbuf, so storeline can place it.
SUB fetchline(p AS CARD)
  DIM k AS BYTE
  tlen = linelen(p)
  k = 0
  DO WHILE k < tlen
    tbuf(k) = PEEK(p + 3 + k)
    k = k + 1
  LOOP
END SUB

SUB doload()
  DIM from AS INT
  DIM p AS CARD
  DIM top AS CARD
  IF parsename() = 0 THEN
    CALL errmsg(0)
    RETURN
  END IF
  from = number()
  IF from < 0 THEN
    CALL new()
    faddr = PROG
    CALL fsload()
    IF fok = 0 THEN
      CALL errmsg(4)
      RETURN
    END IF
    progend = PROG + flen
    RETURN
  END IF
  ' LOAD "n",100 merges the file from line 100 on into what is already
  ' there. The file lands at the top of free memory and the lines are
  ' stored one at a time, which keeps the program in order and costs
  ' nothing that a typed-in line does not. The text grows upward as they
  ' go in, so the two must not meet: the worst case is the whole file.
  CALL fsfind()
  IF fok = 0 THEN
    CALL errmsg(4)
    RETURN
  END IF
  top = MEMTOP - flen + 1
  IF progend + flen >= top THEN
    CALL errmsg(1)
    RETURN
  END IF
  faddr = top
  CALL fsload()
  IF fok = 0 THEN
    CALL errmsg(4)
    RETURN
  END IF
  p = top
  DO WHILE p < top + flen
    IF lineno(p) >= from THEN
      CALL fetchline(p)
      CALL storeline(lineno(p))
    END IF
    p = nextline(p)
  LOOP
END SUB

' ---------------------------------------------------------------------
' COMPACT -- the only command that erases.
'
' Deleting a file clears its status byte and leaves the bytes where they
' are, because that is all NOR flash lets you do cheaply. COMPACT is what
' gets the space back: it slides the live files down and rewrites the
' directory.
'
' Sliding means erasing a 4 KB sector before rewriting it, which destroys
' whatever else lives in that sector -- so the contents have to be
' somewhere else first. There is nowhere in RAM to put 4 KB: main RAM
' holds the user's program and video RAM holds their sprites and the
' compiler image, and a command that quietly ate either would be worse
' than no command. So the somewhere else is the last sector of the
' volume, reserved for exactly this. Gather a sector's worth into the
' scratch, erase the destination, copy it back.
'
' It costs 4 KB of every volume, and it is slow -- every byte is
' programmed twice, and a program is one flash opcode. Compaction was
' slow on every machine that had it.
' ---------------------------------------------------------------------

CONST SCRATCH = 1776            ' the reserved sector, and the data end
CONST LASTSEC = 110             ' the last sector of data

DIM ci AS INT                   ' the entry nextsrc is walking
DIM cleft AS INT                ' pages left in it
DIM csrc AS INT                 ' and its next source page
DIM spg(15) AS INT              ' the sixteen sources for one sector

FUNCTION entpages() AS INT
  DIM n AS INT
  n = PEEK(FSENT + 15)
  IF PEEK(FSENT + 14) <> 0 THEN
    n = n + 1                   ' a partial page still costs a page
  END IF
  RETURN n
END FUNCTION

FUNCTION entpage() AS INT
  DIM n AS INT
  n = PEEK(FSENT + 13)
  n = n << 8
  RETURN n + PEEK(FSENT + 12)
END FUNCTION

' The live files' pages, in order, one per call. 0 when there are no
' more. Entries are appended and data goes at the tail, so walking the
' directory in index order walks the pages in increasing order too.
FUNCTION nextsrc() AS INT
  DIM st AS BYTE
  DIM r AS INT
  DO WHILE cleft = 0
    IF ci > 255 THEN
      RETURN 0
    END IF
    fidx = ci
    ci = ci + 1
    CALL fsreadent()
    st = PEEK(FSENT + 11)
    IF st = 255 THEN
      ci = 256
      RETURN 0
    END IF
    IF st <> 0 THEN
      IF st <> 128 THEN
        csrc = entpage()
        cleft = entpages()
      END IF
    END IF
  LOOP
  r = csrc
  csrc = csrc + 1
  cleft = cleft - 1
  RETURN r
END FUNCTION

' The directory, rebuilt: the live entries at new page numbers, in the
' same order, with the deleted ones gone.
SUB rewritedir()
  DIM i AS INT
  DIM slot AS INT
  DIM k AS INT
  DIM st AS BYTE
  DIM dst AS INT
  DIM np AS INT
  ' Build it in the scratch first, so the old directory is still there
  ' to read while the new one is being written.
  CALL erasesect(SCRATCH)
  k = 0
  DO WHILE k < 256
    pbuf(k) = 255
    k = k + 1
  LOOP
  slot = 0
  dst = 16
  i = 0
  DO WHILE i < 256
    fidx = i
    CALL fsreadent()
    st = PEEK(FSENT + 11)
    IF st = 255 THEN
      EXIT DO
    END IF
    IF st <> 0 THEN
      k = 0
      DO WHILE k < 16
        pbuf((slot AND 15) * 16 + k) = PEEK(FSENT + k)
        k = k + 1
      LOOP
      IF st <> 128 THEN
        np = entpages()
        pbuf((slot AND 15) * 16 + 12) = dst AND 255
        pbuf((slot AND 15) * 16 + 13) = dst >> 8
        dst = dst + np
      END IF
      slot = slot + 1
      IF (slot AND 15) = 0 THEN
        CALL wrpage(SCRATCH + (slot >> 4) - 1)
        k = 0
        DO WHILE k < 256
          pbuf(k) = 255
          k = k + 1
        LOOP
      END IF
    END IF
    i = i + 1
  LOOP
  IF (slot AND 15) <> 0 THEN
    CALL wrpage(SCRATCH + (slot >> 4))
  END IF
  ' Now the swap. Everything above the entries stays $FF from the erase.
  CALL erasesect(0)
  k = 0
  DO WHILE k <= slot >> 4
    CALL rdpage(SCRATCH + k)
    CALL wrpage(k)
    k = k + 1
  LOOP
END SUB

SUB docompact()
  DIM sect AS INT
  DIM n AS INT
  DIM s AS INT
  DIM moved AS BYTE
  DIM done AS BYTE
  ci = 0
  cleft = 0
  sect = 1
  done = 0
  DO WHILE sect <= LASTSEC
    IF done <> 0 THEN
      ' past the live data: stale bytes, and nothing may be appended
      ' over them, so they have to go back to $FF.
      CALL erasesect(sect * 16)
    ELSE
      n = 0
      moved = 0
      DO WHILE n < 16
        s = nextsrc()
        IF s = 0 THEN
          EXIT DO
        END IF
        spg(n) = s
        IF s <> sect * 16 + n THEN
          moved = 1
        END IF
        n = n + 1
      LOOP
      IF n < 16 THEN
        moved = 1               ' a partial sector: its tail must be clean
        done = 1
      END IF
      IF moved <> 0 THEN
        ' Read before erasing, always. The sources are all at or above
        ' this sector, and sixteen live pages consumed from at or above
        ' its start leaves the cursor past its end -- so by the time the
        ' destination is erased there is nothing left in it to lose.
        CALL erasesect(SCRATCH)
        s = 0
        DO WHILE s < n
          CALL rdpage(spg(s))
          CALL wrpage(SCRATCH + s)
          s = s + 1
        LOOP
        CALL erasesect(sect * 16)
        s = 0
        DO WHILE s < n
          CALL rdpage(SCRATCH + s)
          CALL wrpage(sect * 16 + s)
          s = s + 1
        LOOP
      END IF
    END IF
    sect = sect + 1
  LOOP
  CALL rewritedir()
  CALL fsmount()
END SUB

SUB dodir()
  DIM i AS INT
  DIM k AS BYTE
  DIM st AS BYTE
  DIM sz AS CARD
  i = 0
  DO WHILE i < 256
    fidx = i
    CALL fsreadent()
    st = PEEK(FSENT + 11)
    IF st = 255 THEN
      EXIT DO
    END IF
    ' $00 is deleted and $80 is the volume label; neither is a file.
    IF st <> 0 THEN
      IF st <> 128 THEN
        k = 0
        DO WHILE k < 11
          IF k = 8 THEN
            CALL emit(46)
          END IF
          CALL emit(PEEK(FSENT + k))
          k = k + 1
        LOOP
        CALL emit(32)
        sz = PEEK(FSENT + 15)
        sz = sz << 8
        sz = sz + PEEK(FSENT + 14)
        CALL putn(sz)
        CALL newline()
      END IF
    END IF
    i = i + 1
  LOOP
  ' What is left is the tail, in pages of 256 bytes -- 448 KB of them
  ' does not fit in sixteen bits, so this counts in KB.
  sz = PEEK(FSFPG + 1)
  sz = sz << 8
  sz = sz + PEEK(FSFPG)
  CALL putn((VOLPGS - sz) >> 2)
  CALL puts(MSGKFREE)
  CALL newline()
END SUB

' Does lbuf at ip start with the word at table entry `idx`?
FUNCTION iscmd(p AS CARD) AS INT
  DIM m AS BYTE
  DIM k AS BYTE
  m = PEEK(p)
  k = 0
  DO WHILE k < m
    IF upper(lbuf(ip + k)) <> PEEK(p + 1 + k) THEN
      RETURN 0
    END IF
    k = k + 1
  LOOP
  ip = ip + m
  RETURN 1
END FUNCTION

SUB docommand()
  DIM p AS CARD
  DIM idx AS BYTE
  DIM a AS INT
  DIM b AS INT
  CALL skipsp()
  IF ip >= llen THEN
    RETURN
  END IF
  p = CMDTAB
  idx = 0
  DO WHILE PEEK(p) <> 0
    IF iscmd(p) <> 0 THEN
      EXIT DO
    END IF
    p = p + PEEK(p) + 1
    idx = idx + 1
  LOOP
  IF PEEK(p) = 0 THEN
    CALL errmsg(0)
    RETURN
  END IF

  IF idx = 0 THEN                       ' LIST
    a = number()
    IF a < 0 THEN
      a = 0
    END IF
    CALL skipsp()
    b = 32767
    IF ip < llen THEN
      IF lbuf(ip) = 45 THEN
        ip = ip + 1
        b = number()
        IF b < 0 THEN
          b = 32767
        END IF
      ELSE
        b = a
      END IF
    END IF
    CALL list(a, b)
    RETURN
  END IF
  IF idx = 1 THEN                       ' NEW
    CALL new()
    RETURN
  END IF
  IF idx = 2 THEN                       ' FREE
    CALL putn(freebytes())
    CALL puts(MSGFREE)
    CALL newline()
    RETURN
  END IF
  IF idx = 3 THEN                       ' RENUMBER
    a = number()
    IF a < 0 THEN
      a = 10
    END IF
    b = number()
    IF b < 0 THEN
      b = 10
    END IF
    CALL renumber(a, b)
    RETURN
  END IF
  IF idx = 4 THEN                       ' DELETE
    a = number()
    IF a < 0 THEN
      RETURN
    END IF
    CALL skipsp()
    b = a
    IF ip < llen THEN
      IF lbuf(ip) = 45 THEN
        ip = ip + 1
        b = number()
        IF b < 0 THEN
          b = 32767
        END IF
      END IF
    END IF
    CALL deleterange(a, b)
    RETURN
  END IF
  IF idx = 5 THEN                       ' CLS
    CALL cls()
    RETURN
  END IF
  IF idx = 6 THEN                       ' SAVE
    CALL dosave()
    RETURN
  END IF
  IF idx = 7 THEN                       ' LOAD
    CALL doload()
    RETURN
  END IF
  IF idx = 8 THEN                       ' DIR
    CALL dodir()
    RETURN
  END IF
  IF idx = 9 THEN                       ' ERA
    IF parsename() = 0 THEN
      CALL errmsg(0)
      RETURN
    END IF
    CALL fserase()
    IF fok = 0 THEN
      CALL errmsg(4)
    END IF
    RETURN
  END IF
  IF idx = 10 THEN                      ' COMPACT
    CALL docompact()
    RETURN
  END IF
  IF idx = 11 THEN                      ' DRIVE
    a = number()
    IF a < 0 THEN
      a = 0
    END IF
    fdrv = a AND 15
    CALL fsmount()
    RETURN
  END IF
  IF idx = 12 THEN                      ' RUN
    CALL dorun()
    RETURN
  END IF
  CALL errmsg(0)
END SUB


' Return was pressed on row r.
SUB enter(r AS INT)
  DIM n AS INT
  CALL readrow(r)
  CALL newline()
  ip = 0
  CALL skipsp()
  IF ip >= llen THEN
    RETURN
  END IF
  IF isdigit(lbuf(ip)) <> 0 THEN
    n = number()
    ' the rest of the row is the line; drop one separating space
    IF ip < llen THEN
      IF lbuf(ip) = 32 THEN
        ip = ip + 1
      END IF
    END IF
    CALL shiftlbuf()
    CALL tokenise()
    CALL storeline(n)
    RETURN
  END IF
  CALL docommand()
END SUB

' Slide lbuf down so the line body starts at 0.
SUB shiftlbuf()
  DIM k AS BYTE
  k = 0
  DO WHILE ip + k < llen
    lbuf(k) = lbuf(ip + k)
    k = k + 1
  LOOP
  llen = k
  ip = 0
END SUB

' ---------------------------------------------------------------------
' The boot screen: what the machine found, and how much is free.
' ---------------------------------------------------------------------

SUB banner()
  DIM p AS CARD
  DIM k AS BYTE
  DIM a AS BYTE
  p = BANNERTAB
  cy = 1
  DO
    a = PEEK(p)
    IF a = 0 THEN
      EXIT DO
    END IF
    cx = 4
    p = p + 1
    DO WHILE PEEK(p) <> 0
      CALL putat(cy, cx, PEEK(p), a)
      cx = cx + 1
      p = p + 1
    LOOP
    p = p + 1
    cy = cy + 1
  LOOP
  cx = 4
  CALL putn(freebytes())
  CALL puts(MSGFREE)
  cy = cy + 2
  cx = 4
  CALL showcur()
END SUB

' ---------------------------------------------------------------------
' The loop.
' ---------------------------------------------------------------------

DIM k AS INT

POKE VID_MODE, $80
POKE VID_BASE_L, SCREEN AND 255
POKE VID_BASE_H, SCREEN >> 8
POKE CUR_CTRL, $09              ' block cursor, blink rate 1 (~2 Hz).
                                ' $19 was rate 3 -- the hardware's
                                ' "solid, no blink" -- by an old choice
                                ' the machine's owner has overruled
vtop = 0
progend = PROG
fdrv = 0

' The input interrupt. sw/boot.asm leaves NMI, IRQ and BRK all pointing
' at a bare RETI and never enables interrupts, so this is the first
' handler the machine has had. Vblank is the tick for the *UART*, which
' cannot raise an interrupt of its own -- the core sees
' `irq | vid_irq | ps2_irq` and nothing carries the UART to it -- so the
' tick does the reading, exactly as the C64's jiffy IRQ scans a keyboard
' that cannot interrupt either.
'
' The keyboard is not in that position: KBD_CTRL bit 4 puts it on the
' same line, so a keypress is seen when it happens rather than up to a
' frame later. Both sources land in one handler and one ring.
POKE $FFFC, iisr AND 255
POKE $FFFD, iisr >> 8
POKE $FE1D, $20                 ' enable the vertical blank interrupt
POKE $FE42, $11                 ' clear the keyboard FIFO and enable its
POKE $FE42, $10                 ' interrupt -- stale codes are not input
ASM
        EI
END ASM
CALL fsmount()
CALL cls()
CALL banner()
' The banner is indented four columns by design; the cursor is not.
cx = 0
CALL showcur()
' The boot ROM lit the green LED when it found BOOT.BIN; the system is
' up now, so out it goes. Its whole duration is the relocation and this
' startup -- a blink, with no timer anywhere.
POKE $FE03, 0

DO
  k = getkey()
  IF k = 13 THEN
    CALL enter(cy)
  ELSE
    IF k = K_LEFT THEN
      IF cx > 0 THEN
        cx = cx - 1
      END IF
      CALL showcur()
    ELSE
      IF k = K_RIGHT THEN
        IF cx < COLS - 1 THEN
          cx = cx + 1
        END IF
        CALL showcur()
      ELSE
        IF k = K_UP THEN
          IF cy > 0 THEN
            cy = cy - 1
          END IF
          CALL showcur()
        ELSE
          IF k = K_DOWN THEN
            IF cy < ROWS - 1 THEN
              cy = cy + 1
            END IF
            CALL showcur()
          ELSE
            IF k = K_HOME THEN
              cx = 0
              CALL showcur()
            ELSE
              IF k = K_END THEN
                CALL gotoend()
              ELSE
                IF k = 8 THEN
                  CALL backspace()
                ELSE
                  IF k = 127 THEN
                    CALL backspace()
                  ELSE
                    IF k = K_DEL THEN
                      CALL delchar()
                    ELSE
                      IF k > 31 THEN
                        IF k < 127 THEN
                          CALL emit(k)
                        END IF
                      END IF
                    END IF
                  END IF
                END IF
              END IF
            END IF
          END IF
        END IF
      END IF
    END IF
  END IF
LOOP WHILE 0 = 0
END

SUB gotoend()
  DIM c AS BYTE
  DIM last AS BYTE
  c = 0
  last = 0
  DO WHILE c < COLS
    IF getat(cy, c) <> 32 THEN
      last = c + 1
    END IF
    c = c + 1
  LOOP
  cx = last
  IF cx > COLS - 1 THEN
    cx = COLS - 1
  END IF
  CALL showcur()
END SUB

SUB delchar()
  DIM c AS BYTE
  c = cx
  DO WHILE c < COLS - 1
    CALL putat(cy, c, getat(cy, c + 1), A_TEXT)
    c = c + 1
  LOOP
  CALL putat(cy, COLS - 1, 32, A_TEXT)
END SUB

SUB backspace()
  IF cx = 0 THEN
    RETURN
  END IF
  cx = cx - 1
  CALL delchar()
  CALL showcur()
END SUB

ASM
; ---- the keyword table. It is its own file because sw/asm.asm reads
; ---- it too -- the editor tokenises the inside of an ASM block, so the
; ---- assembler has to turn those bytes back into words.
        .include "toktab.asm"

; ---- commands, in the order docommand tests them
CMDTAB:
        .byte 4, "L","I","S","T"
        .byte 3, "N","E","W"
        .byte 4, "F","R","E","E"
        .byte 8, "R","E","N","U","M","B","E","R"
        .byte 6, "D","E","L","E","T","E"
        .byte 3, "C","L","S"
        .byte 4, "S","A","V","E"
        .byte 4, "L","O","A","D"
        .byte 3, "D","I","R"
        .byte 3, "E","R","A"
        .byte 7, "C","O","M","P","A","C","T"
        .byte 5, "D","R","I","V","E"
; Appended, never inserted: docommand branches on the positional idx, so
; RUN is 12 and no existing arm moves.
        .byte 3, "R","U","N"
        .byte 0

; ---- the interpreter's errors, indexed by ERR.
;
; Deliberately not ERRTAB: that is the editor's list and the codes do
; not line up. `errmsg(1)` is OUT OF MEMORY where `ERR = 1` is a syntax
; error, so sharing one table would report the wrong fault confidently.
RUNTAB:
        .asciz "SYNTAX ERROR"
        .asciz "TOO MANY FORS ERROR"
        .asciz "NEXT WITHOUT FOR ERROR"
        .asciz "FORMULA TOO COMPLEX ERROR"
        .asciz "OUT OF MEMORY ERROR"
        .asciz "TOO MANY VARIABLES ERROR"
        .asciz "SUBSCRIPT ERROR"
        .asciz "STRING TOO LONG ERROR"
        .asciz "TYPE MISMATCH ERROR"
        .asciz "SYNTAX ERROR IN ASM"
        .asciz "NO SUCH INSTRUCTION"
        .asciz "UNDEFINED SYMBOL"
        .asciz "ERROR"
        .asciz "BRANCH OUT OF RANGE"
        .asciz "DIVISION BY ZERO ERROR"
        .asciz "LOOP ERROR"
        .asciz "CALL ERROR"
        .asciz "BREAK"
        .asciz "OUT OF DATA ERROR"
        .byte 0

; ---- errors. C64-shaped: a ? , the fault, and ERROR.
ERRTAB:
        .asciz "SYNTAX ERROR"
        .asciz "OUT OF MEMORY ERROR"
        .asciz "UNDEF'D LINE ERROR"
        .asciz "DISK FULL ERROR"
        .asciz "FILE NOT FOUND ERROR"
        .byte 0

MSGFREE:
        .asciz " BYTES FREE"

MSGKFREE:
        .asciz "K FREE"

; ---- the boot screen: an attribute byte, then the text, then a zero.
; ---- Every line here is something the machine checked.
BANNERTAB:
        .byte $0B
        .asciz "COOL8"
        .byte $0F
        .asciz "8-bit, and all of it original"
        .byte $07
        .asciz ""
        .byte $08
        .asciz "CPU     COOL8 @ 8.375 MHz        RAM    64K main, 64K video"
        .byte $08
        .asciz "VIDEO   640x480, 32 sprites      SOUND  8 voices, 1-bit DAC"
        .byte $07
        .asciz ""
        .byte $0E
        .asciz "COOL8 BASIC 1.0"
        .byte 0

; ---- the filesystem, whole. Its state lives at $0074, in page 0 with
; ---- the interpreter's, so that page 1 is the CPU stack alone.
        .include "fs.asm"

; ---------------------------------------------------------------------
; The input ring, and the interrupt that fills it.
;
; **Neither the editor nor the interpreter reads a device.** The C64's
; STOP routine "does not scan the keyboard" -- the 60 Hz jiffy IRQ sets
; a flag and BASIC polls it -- and the BBC's 100 Hz interrupt sets the
; escape flag the same way. Copying that is what lets a *running*
; program be stopped at all: it cannot poll, so something else must.
;
; The vertical blank is the tick for the UART, which cannot raise an
; interrupt (docs/04-system.md section 6: the core sees
; `irq | vid_irq | ps2_irq` and nothing carries the UART to it). So the
; tick does the reading, which is the C64's shape exactly -- its jiffy
; IRQ scans a keyboard that cannot interrupt either.
;
; The PS/2 port *is* on that line, through KBD_CTRL bit 4, so a keypress
; is handled when it happens. Both sources end in the same ring and
; nothing above here can tell which wire a key came in on.
;
; Sixteen bytes, which is the UART's own FIFO depth. At 115200 a full
; line arrives faster than 60 Hz can drain it, so a host that streams
; will still overrun -- a person typing never will, and the harness
; waits for the ring to empty between chunks.
IRSIZE  = 16
irring: .space 16
irhead: .byte 0
irtail: .byte 0

; kbd.asm's state. It declares none of its own, because the same source
; is assembled into the boot ROM where a .byte would land in ROM and
; could never be written.
kshift: .byte 0
kbrk:   .byte 0
kext:   .byte 0
kdown:  .space 16

iisr:   PUSH R0
        PUSH R1
        PUSHW X
        MOV  R0,#$22            ; acknowledge vblank, keep it enabled
        ST   [$FE1D],R0
        LD   R0,[frames]        ; the tick TIMER reads and VSYNC waits on
        ADD  R0,#1
        ST   [frames],R0
        LD   R0,[frames+1]      ; LD leaves C alone, so the carry rides
        ADC  R0,#0
        ST   [frames+1],R0
.more:  LD   R0,[$FE70]         ; UART_STAT: anything waiting?
        BTST R0,#$01
        BEQ  .kbd
        LD   R0,[$FE71]         ; taking it is the only way to see it
        CMP  R0,#$03            ; Ctrl-C, the serial console's Break
        BNE  .keep
.stop:  MOV  R0,#1
        ST   [ibreak],R0        ; the flag the interpreter polls
        BRA  .more
.keep:  CALL irpush
        BRA  .more

        ; The keyboard. Raw Set 2 arrives and kbd.asm turns it into a
        ; key, or into nothing at all for a prefix, a release or a
        ; shift. Ctrl+Pause decodes to $03, so the Break key and the
        ; serial console's Ctrl-C are the same byte and stop a program
        ; through the same test above.
.kbd:   LD   R0,[$FE40]         ; KBD_STAT
        BTST R0,#$01
        BEQ  .done
        LD   R0,[$FE41]         ; KBD_DATA, read has a side effect
        CALL scancode
        TST  R0
        BEQ  .kbd
        CMP  R0,#$03
        BEQ  .stop
        CALL irpush
        BRA  .kbd
.done:  POPW X
        POP  R1
        POP  R0
        RETI

; irpush -- R0 into the ring. Both inputs come through here.
irpush: LD   R1,[irhead]
        LDW  X,#irring
        ADDW X,R1
        ST   [X],R0
        ADD  R1,#1
        AND  R1,#15
        ST   [irhead],R1
        RET

; ---- the interpreter and the on-machine assembler. Both are written
; ---- without .org for exactly this: every address in the image is
; ---- relative and nothing hardcodes one, so joining them here shifts
; ---- everything and breaks nothing.
;
; zp.asm comes first and exactly once. Neither of the two includes it,
; because in the built system both are present and a second copy would
; redefine every name.
        .include "zp.asm"
        .include "interp.asm"
        .include "asm.asm"

; ---- the keyboard, the same source the boot ROM's monitor is built
; ---- from. It cannot be shared at run time: this image ends at $F20A,
; ---- so its last 523 bytes are under the ROM window and turning ROMEN
; ---- on to call into the ROM would hide those bytes from the CPU.
; ---- kdown.asm is the half the monitor does not want, and the reason
; ---- kdset/kdclr are the includer's rather than kbd.asm's own.
        .include "kbd.asm"
        .include "keymap.asm"
        .include "kdown.asm"
END ASM
