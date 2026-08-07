' ---------------------------------------------------------------------
' chars.bas -- what counts as a letter, a digit, a name.
'
' Shared by the screen editor's tokeniser and by the compiler's lexer,
' because the two have to agree: a character the tokeniser treats as
' part of a name and the lexer does not is a name that survives being
' typed and then fails to compile.
' ---------------------------------------------------------------------

FUNCTION upper(c AS INT) AS INT
  IF c > 96 THEN
    IF c < 123 THEN
      RETURN c - 32
    END IF
  END IF
  RETURN c
END FUNCTION

FUNCTION isalpha(c AS INT) AS INT
  DIM u AS BYTE
  u = upper(c)
  IF u > 64 THEN
    IF u < 91 THEN
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

FUNCTION isident(c AS INT) AS INT
  IF isalpha(c) <> 0 THEN
    RETURN 1
  END IF
  IF isdigit(c) <> 0 THEN
    RETURN 1
  END IF
  IF c = 95 THEN
    RETURN 1
  END IF
  RETURN 0
END FUNCTION
