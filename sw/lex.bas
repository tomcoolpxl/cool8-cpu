' ---------------------------------------------------------------------
' lex.bas -- the compiler's front end, on the machine.
'
' Hands the parser one token at a time out of the stored program. Gated
' against tools/cool8bas.py's lex() by sim/test_lex.py: the same source
' has to produce the same tokens, in the same order, with the same
' values, or the compilers cannot agree on anything downstream.
'
' ## Half the work is already done
'
' The stored program is tokenised: keywords are single bytes >= $80,
' put there when the line was typed. So this does not carry a keyword
' table or match any strings -- a byte >= $80 IS the keyword, and its
' value is the kind. That is a large part of why tokenised storage was
' worth having, beyond the 23 % it saves on space.
'
' What is left is numbers, names, strings, operators, and knowing where
' the lines end.
'
' ## Line ends are tokens
'
' Each stored line is a record: lineno (2), len (1), then len bytes. The
' record boundary is the newline -- there is no $0A anywhere. A line
' that holds nothing but a comment still ends with one, and two in a row
' never come out, both of which are what the reference lexer does.
' ---------------------------------------------------------------------

CONST T_EOF  = 0
CONST T_NL   = 1
CONST T_NUM  = 2
CONST T_NAME = 3
CONST T_STR  = 4
CONST T_OP   = 5

DIM lxrec AS CARD               ' the record being read
DIM lxp AS CARD                 ' where in its token bytes
DIM lxend AS CARD               ' and where they stop
DIM lxdone AS BYTE              ' 1 once the last record is behind us
DIM lxnl AS BYTE                ' 1 if the last token handed out was T_NL

DIM tk AS BYTE                  ' the kind just read, or the keyword byte
DIM tnum AS CARD                ' its value, if T_NUM
DIM tsl AS BYTE                 ' its text, if T_NAME, T_OP or T_STR
DIM tsb(31) AS BYTE

SUB lexstart(p AS CARD)
  lxrec = p
  lxp = p + 3
  lxend = p + 3 + PEEK(p + 2)
  lxdone = 0
  lxnl = 1                      ' a leading blank line is not a token
END SUB

' Move to the next record. 0 if there is not one.
FUNCTION lexnextrec() AS INT
  lxrec = lxend
  IF lxrec >= progend THEN
    lxdone = 1
    RETURN 0
  END IF
  lxp = lxrec + 3
  lxend = lxrec + 3 + PEEK(lxrec + 2)
  RETURN 1
END FUNCTION

SUB tspush(c AS INT)
  IF tsl < 31 THEN
    tsb(tsl) = c
    tsl = tsl + 1
  END IF
END SUB

FUNCTION hexval(c AS INT) AS INT
  DIM u AS BYTE
  IF isdigit(c) <> 0 THEN
    RETURN c - 48
  END IF
  u = upper(c)
  IF u > 64 THEN
    IF u < 71 THEN
      RETURN u - 55
    END IF
  END IF
  RETURN 0 - 1
END FUNCTION

' Is a comment starting here? REM is stored as text, not as a keyword
' byte, because it introduces one -- so it is recognised here and not in
' the table. REMAINDER is a name, hence the check on what follows.
FUNCTION isrem() AS INT
  IF lxp + 3 > lxend THEN
    RETURN 0
  END IF
  IF upper(PEEK(lxp)) <> 82 THEN
    RETURN 0
  END IF
  IF upper(PEEK(lxp + 1)) <> 69 THEN
    RETURN 0
  END IF
  IF upper(PEEK(lxp + 2)) <> 77 THEN
    RETURN 0
  END IF
  IF lxp + 3 < lxend THEN
    IF isident(PEEK(lxp + 3)) <> 0 THEN
      RETURN 0
    END IF
  END IF
  RETURN 1
END FUNCTION

' The next token. Its kind lands in tk; a number in tnum, text in tsb.
FUNCTION nexttok() AS INT
  DIM c AS BYTE
  DIM d AS BYTE
  DIM two AS BYTE
  tsl = 0
  tnum = 0
  DO
    IF lxdone <> 0 THEN
      ' One more newline after the last line's own, then eof. The
      ' reference appends its closing newline unconditionally, so a
      ' source ending in one -- which a stored program always does,
      ' every record being a whole line -- yields two.
      IF lxdone = 1 THEN
        lxdone = 2
        tk = T_NL
        RETURN T_NL
      END IF
      tk = T_EOF
      RETURN T_EOF
    END IF
    ' spaces first, so an all-blank tail does not look like content
    DO WHILE lxp < lxend
      IF PEEK(lxp) <> 32 THEN
        EXIT DO
      END IF
      lxp = lxp + 1
    LOOP
    IF lxp < lxend THEN
      c = PEEK(lxp)
      ' a comment is the rest of the record, and the record still ends
      IF c = 39 THEN
        lxp = lxend
      ELSE
        IF isrem() <> 0 THEN
          lxp = lxend
        END IF
      END IF
    END IF
    IF lxp >= lxend THEN
      IF lexnextrec() = 0 THEN
        ' The stream always ends with a newline and then eof, whether or
        ' not the last line already ended in one. lexnextrec has set
        ' lxdone, so the next call comes out of the top as eof.
        tk = T_NL
        RETURN T_NL
      END IF
      IF lxnl = 0 THEN
        lxnl = 1
        tk = T_NL
        RETURN T_NL
      END IF
    ELSE
      EXIT DO
    END IF
  LOOP

  lxnl = 0
  c = PEEK(lxp)

  ' ---- a keyword, already one byte
  IF c > 127 THEN
    lxp = lxp + 1
    tk = c
    RETURN c
  END IF

  ' ---- a number, decimal or $hex
  IF c = 36 THEN
    lxp = lxp + 1
    DO WHILE lxp < lxend
      d = hexval(PEEK(lxp))
      IF d > 15 THEN
        EXIT DO
      END IF
      tnum = (tnum << 4) + d
      lxp = lxp + 1
    LOOP
    tk = T_NUM
    RETURN T_NUM
  END IF
  IF isdigit(c) <> 0 THEN
    DO WHILE lxp < lxend
      IF isdigit(PEEK(lxp)) = 0 THEN
        EXIT DO
      END IF
      tnum = tnum * 10 + (PEEK(lxp) - 48)
      lxp = lxp + 1
    LOOP
    tk = T_NUM
    RETURN T_NUM
  END IF

  ' ---- a name
  IF isident(c) <> 0 THEN
    DO WHILE lxp < lxend
      IF isident(PEEK(lxp)) = 0 THEN
        EXIT DO
      END IF
      CALL tspush(PEEK(lxp))
      lxp = lxp + 1
    LOOP
    tk = T_NAME
    RETURN T_NAME
  END IF

  ' ---- a string, without its quotes
  IF c = 34 THEN
    lxp = lxp + 1
    DO WHILE lxp < lxend
      IF PEEK(lxp) = 34 THEN
        lxp = lxp + 1
        EXIT DO
      END IF
      CALL tspush(PEEK(lxp))
      lxp = lxp + 1
    LOOP
    tk = T_STR
    RETURN T_STR
  END IF

  ' ---- an operator. << >> <> <= >= are one token, not two.
  CALL tspush(c)
  lxp = lxp + 1
  two = 0
  IF lxp < lxend THEN
    d = PEEK(lxp)
    IF c = 60 THEN
      IF d = 60 THEN
        two = 1
      END IF
      IF d = 62 THEN
        two = 1
      END IF
      IF d = 61 THEN
        two = 1
      END IF
    END IF
    IF c = 62 THEN
      IF d = 62 THEN
        two = 1
      END IF
      IF d = 61 THEN
        two = 1
      END IF
    END IF
  END IF
  IF two <> 0 THEN
    CALL tspush(PEEK(lxp))
    lxp = lxp + 1
  END IF
  tk = T_OP
  RETURN T_OP
END FUNCTION
