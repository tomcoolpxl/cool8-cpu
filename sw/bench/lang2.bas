' PEEK, POKE, AT, FUNCTION and inline assembly.
DIM scr(63) AS BYTE AT $8200

w = 0
POKE $8200, 65
x = PEEK($8200)
scr(1) = 7
y = scr(1)
z = Twice(21)

FUNCTION Twice(n AS INT) AS INT
  RETURN n + n
END FUNCTION

ASM
        MOV  R0,#99
        ST   [v_w],R0
        CLR  R0
        ST   [v_w+1],R0
END ASM
END
