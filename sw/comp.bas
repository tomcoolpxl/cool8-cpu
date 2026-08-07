' ---------------------------------------------------------------------
' comp.bas -- the compiler's middle, on the machine.
'
' Symbols and expressions: DIM, CONST, assignment, and the arithmetic
' between them. Sits on lex.bas at the front and emit.bas at the back,
' and is gated by sim/test_comp.py against tools/cool8bas.py -- the same
' program has to compile to the same bytes, and the variables have to
' land at the same addresses.
'
' ## Why there is a tree here at all
'
' The rest of the compiler is one pass and emits as it parses. This part
' cannot, quite: the code for `a + b` depends on whether `b` is a leaf,
' and the width of every operand depends on the width of the whole
' expression. Both are answers you only have once the expression has
' been read. So an expression is parsed into a handful of nodes, asked
' those two questions, and then generated -- and the nodes are reused by
' the next statement.
'
' ## Where the variables go
'
' The cross-compiler emits its variables after the code, in declaration
' order, and the assembler gives them addresses. This does the same: a
' variable is a label, every mention of it chains through emit.bas until
' the end of the program, and then the labels are placed one after
' another past the last instruction. Two labels each, because a chain
' patches in exactly the address it is given and the high byte needs
' its own.
' ---------------------------------------------------------------------

' Keyword token bytes, in TOKTAB order.
CONST KW_DIM   = $83
CONST KW_CONST = $84
CONST KW_END   = $91
CONST KW_AS    = $94
CONST KW_INT   = $95
CONST KW_BYTE  = $96
CONST KW_PEEK  = $97
CONST KW_AND   = $99
CONST KW_OR    = $9A
CONST KW_XOR   = $9B
CONST KW_CARD  = $9C

' Operators, as the generator names them.
CONST O_ADD = 0
CONST O_SUB = 1
CONST O_AND = 2
CONST O_OR  = 3
CONST O_XOR = 4
CONST O_SHL = 5
CONST O_SHR = 6

' Expression nodes.
CONST N_NUM = 0
CONST N_VAR = 1
CONST N_BIN = 2

' MAX-, not N-: the language is case-insensitive, so a constant NSYM
' and a variable nsym are one name -- the DIM won, the guard became
' `nsym >= nsym`, and the table looked full the moment it was empty.
CONST MAXSYM = 40
CONST MAXNODE = 48

' Labels above the symbols' own two-each.
CONST LMAIN = 80
CONST MAXPOOL = 512

' ---- the symbol table
DIM spool(511) AS BYTE          ' the names, end to end
DIM spend AS CARD
DIM syoff(39) AS CARD           ' where each one starts
DIM sylen(39) AS BYTE
DIM sykind(39) AS BYTE          ' 0 a variable, 1 a constant
DIM syw(39) AS BYTE             ' 1 byte wide, 2 word wide
DIM sysg(39) AS BYTE            ' 1 signed
DIM syval(39) AS CARD           ' a constant's value
DIM nsym AS BYTE

' ---- the expression tree
DIM nk(47) AS BYTE
DIM nop(47) AS BYTE
DIM na(47) AS BYTE
DIM nb(47) AS BYTE
DIM nv(47) AS CARD
DIM nn AS BYTE

DIM cerr AS BYTE                ' 0 while everything is still fine

' ---------------------------------------------------------------------
' Symbols.
' ---------------------------------------------------------------------

SUB cinit()
  nsym = 0
  spend = 0
  cerr = 0
END SUB

' The symbol whose name is the token just read, or 255.
FUNCTION syfind() AS BYTE
  DIM i AS BYTE
  DIM k AS BYTE
  DIM p AS CARD
  DIM hit AS BYTE
  i = 0
  DO WHILE i < nsym
    IF sylen(i) = tsl THEN
      p = syoff(i)
      k = 0
      hit = 1
      DO WHILE k < tsl
        IF spool(p + k) <> upper(tsb(k)) THEN
          hit = 0
        END IF
        k = k + 1
      LOOP
      IF hit = 1 THEN
        RETURN i
      END IF
    END IF
    i = i + 1
  LOOP
  RETURN 255
END FUNCTION

' Add the token just read as a new symbol. Its index, or 255.
FUNCTION syadd() AS BYTE
  DIM i AS BYTE
  DIM k AS BYTE
  IF nsym >= MAXSYM THEN
    cerr = 1
    RETURN 255
  END IF
  i = nsym
  syoff(i) = spend
  sylen(i) = tsl
  k = 0
  DO WHILE k < tsl
    spool(spend) = upper(tsb(k))
    spend = spend + 1
    k = k + 1
  LOOP
  sykind(i) = 0
  syw(i) = 2
  sysg(i) = 1
  syval(i) = 0
  nsym = nsym + 1
  RETURN i
END FUNCTION

' A variable's low-byte label. The high byte is the next one along.
FUNCTION sylab(i AS BYTE) AS BYTE
  RETURN i * 2
END FUNCTION

' ---------------------------------------------------------------------
' The tree.
' ---------------------------------------------------------------------

FUNCTION mknum(v AS CARD) AS BYTE
  DIM i AS BYTE
  i = nn
  nn = nn + 1
  nk(i) = N_NUM
  nv(i) = v
  RETURN i
END FUNCTION

FUNCTION mkvar(s AS BYTE) AS BYTE
  DIM i AS BYTE
  i = nn
  nn = nn + 1
  nk(i) = N_VAR
  na(i) = s
  RETURN i
END FUNCTION

' A binary node, folded if both sides are already known. Not an
' optimisation: it is the difference between SIZE + 1 being an add and
' being a number, and a number is a leaf where an add is not.
FUNCTION mkbin(op AS BYTE, a AS BYTE, b AS BYTE) AS BYTE
  DIM i AS BYTE
  DIM x AS CARD
  DIM y AS CARD
  IF nk(a) = N_NUM THEN
    IF nk(b) = N_NUM THEN
      x = nv(a)
      y = nv(b)
      IF op = O_ADD THEN
        x = x + y
      END IF
      IF op = O_SUB THEN
        x = x - y
      END IF
      IF op = O_AND THEN
        x = x AND y
      END IF
      IF op = O_OR THEN
        x = x OR y
      END IF
      IF op = O_XOR THEN
        x = x XOR y
      END IF
      ' A shift by a counted amount, because the language only shifts by
      ' a constant -- which is the rule this compiler enforces too.
      IF op = O_SHL THEN
        DO WHILE y > 0
          x = x + x
          y = y - 1
        LOOP
      END IF
      IF op = O_SHR THEN
        DO WHILE y > 0
          x = x >> 1
          y = y - 1
        LOOP
      END IF
      nv(a) = x
      nn = a + 1
      RETURN a
    END IF
  END IF
  i = nn
  nn = nn + 1
  nk(i) = N_BIN
  nop(i) = op
  na(i) = a
  nb(i) = b
  RETURN i
END FUNCTION

' 1 for a byte, 2 for a word. A literal takes whichever width it is used
' at, so x + 1 on bytes stays a byte.
FUNCTION cwidth(i AS BYTE) AS BYTE
  DIM x AS BYTE
  DIM y AS BYTE
  IF nk(i) = N_NUM THEN
    IF nv(i) < 256 THEN
      RETURN 1
    END IF
    RETURN 2
  END IF
  IF nk(i) = N_VAR THEN
    RETURN syw(na(i))
  END IF
  x = cwidth(na(i))
  y = cwidth(nb(i))
  IF y > x THEN
    RETURN y
  END IF
  RETURN x
END FUNCTION

FUNCTION isleaf(i AS BYTE) AS BYTE
  IF nk(i) = N_BIN THEN
    RETURN 0
  END IF
  RETURN 1
END FUNCTION

' ---------------------------------------------------------------------
' Generating.
' ---------------------------------------------------------------------

' A leaf into Rr, or Rr:Rr+1 at word width. A byte source read wide is
' zero-extended with a CLR, which is one instruction; a wide source read
' narrow simply drops its high half, which is none.
SUB cload(i AS BYTE, r AS BYTE, w AS BYTE)
  DIM s AS BYTE
  IF nk(i) = N_NUM THEN
    CALL ealui(E_MOV, r, nv(i) AND 255)
    IF w = 2 THEN
      CALL ealui(E_MOV, r + 1, nv(i) >> 8)
    END IF
    RETURN
  END IF
  s = na(i)
  IF sykind(s) = 1 THEN
    CALL ealui(E_MOV, r, syval(s) AND 255)
    IF w = 2 THEN
      CALL ealui(E_MOV, r + 1, syval(s) >> 8)
    END IF
    RETURN
  END IF
  CALL eb($61 + r * 2)
  CALL eabs(sylab(s))
  IF w = 2 THEN
    IF syw(s) = 1 THEN
      CALL ealur(E_SUB, r + 1, r + 1)           ' CLR
    ELSE
      CALL eb($61 + (r + 1) * 2)
      CALL eabs(sylab(s) + 1)
    END IF
  END IF
END SUB

' R0:R1 shifted by a constant. Eight of them is a byte move, which is
' why x >> 8 costs two instructions and not eight pairs.
SUB cshift(op AS BYTE, n AS BYTE, w AS BYTE)
  DIM k AS BYTE
  IF w = 1 THEN
    k = 0
    DO WHILE k < n
      IF k >= 8 THEN
        EXIT DO
      END IF
      IF op = O_SHL THEN
        CALL ealur(E_ADD, 0, 0)
      ELSE
        CALL eb($2F)
        CALL eb($20)                            ' SHR R0
      END IF
      k = k + 1
    LOOP
    RETURN
  END IF
  IF n >= 8 THEN
    IF op = O_SHL THEN
      CALL ealur(E_MOV, 1, 0)
      CALL ealur(E_SUB, 0, 0)
    ELSE
      CALL ealur(E_MOV, 0, 1)
      CALL ealur(E_SUB, 1, 1)
    END IF
    n = n - 8
  END IF
  k = 0
  DO WHILE k < n
    IF op = O_SHL THEN
      CALL ealur(E_ADD, 0, 0)
      CALL ealur(E_ADC, 1, 1)
    ELSE
      CALL eb($2F)
      CALL eb($21)                              ' SHR R1
      CALL eb($2F)
      CALL eb($28)                              ' ROR R0
    END IF
    k = k + 1
  LOOP
END SUB

SUB cbinop(op AS BYTE, w AS BYTE)
  IF op = O_ADD THEN
    CALL ealur(E_ADD, 0, 2)
    IF w = 2 THEN
      CALL ealur(E_ADC, 1, 3)
    END IF
    RETURN
  END IF
  IF op = O_SUB THEN
    CALL ealur(E_SUB, 0, 2)
    IF w = 2 THEN
      CALL ealur(E_SBC, 1, 3)
    END IF
    RETURN
  END IF
  IF op = O_AND THEN
    CALL ealur(E_AND, 0, 2)
    IF w = 2 THEN
      CALL ealur(E_AND, 1, 3)
    END IF
    RETURN
  END IF
  IF op = O_OR THEN
    CALL ealur(E_OR, 0, 2)
    IF w = 2 THEN
      CALL ealur(E_OR, 1, 3)
    END IF
    RETURN
  END IF
  ' XOR is on page two, and takes the same dd ss layout.
  CALL eb($2F)
  CALL eb(0 * 16 + 0 * 4 + 2)
  IF w = 2 THEN
    CALL eb($2F)
    CALL eb(1 * 4 + 3)
  END IF
END SUB

' The value of node i into R0, or R0:R1 when it is two wide.
SUB cgen(i AS BYTE, w AS BYTE)
  DIM a AS BYTE
  DIM b AS BYTE
  DIM wa AS BYTE
  IF isleaf(i) <> 0 THEN
    CALL cload(i, 0, w)
    RETURN
  END IF
  a = na(i)
  b = nb(i)
  IF nop(i) >= O_SHL THEN
    ' The operand keeps its own width. Narrowing first would load the
    ' low byte and then shift it away, which is what a >> 8 became the
    ' moment BYTE existed.
    wa = cwidth(a)
    IF w > wa THEN
      wa = w
    END IF
    CALL cgen(a, wa)
    CALL cshift(nop(i), nv(b) AND 15, wa)
    RETURN
  END IF
  IF isleaf(b) <> 0 THEN
    CALL cgen(a, w)
    CALL cload(b, 2, w)
  ELSE
    ' Without temporaries yet: this is what S4c adds.
    cerr = 2
    RETURN
  END IF
  CALL cbinop(nop(i), w)
END SUB

' ---------------------------------------------------------------------
' Parsing.
' ---------------------------------------------------------------------

FUNCTION isop(c AS INT) AS BYTE
  IF tk <> T_OP THEN
    RETURN 0
  END IF
  IF tsl <> 1 THEN
    RETURN 0
  END IF
  IF tsb(0) <> c THEN
    RETURN 0
  END IF
  RETURN 1
END FUNCTION

FUNCTION isop2(a AS INT, b AS INT) AS BYTE
  IF tk <> T_OP THEN
    RETURN 0
  END IF
  IF tsl <> 2 THEN
    RETURN 0
  END IF
  IF tsb(0) <> a THEN
    RETURN 0
  END IF
  IF tsb(1) <> b THEN
    RETURN 0
  END IF
  RETURN 1
END FUNCTION

FUNCTION cprimary() AS BYTE
  DIM s AS BYTE
  DIM r AS BYTE
  IF tk = T_NUM THEN
    r = mknum(tnum)
    CALL nexttok()
    RETURN r
  END IF
  IF isop(40) <> 0 THEN                         ' (
    CALL nexttok()
    r = cexpr()
    IF isop(41) = 0 THEN
      cerr = 3
    ELSE
      CALL nexttok()
    END IF
    RETURN r
  END IF
  IF tk = T_NAME THEN
    s = syfind()
    IF s = 255 THEN
      cerr = 4
      RETURN mknum(0)
    END IF
    CALL nexttok()
    IF sykind(s) = 1 THEN
      RETURN mknum(syval(s))
    END IF
    RETURN mkvar(s)
  END IF
  cerr = 5
  RETURN mknum(0)
END FUNCTION

FUNCTION cunary() AS BYTE
  DIM r AS BYTE
  IF isop(45) <> 0 THEN                         ' -
    CALL nexttok()
    r = cunary()
    IF nk(r) = N_NUM THEN
      nv(r) = 0 - nv(r)
      RETURN r
    END IF
    RETURN mkbin(O_SUB, mknum(0), r)
  END IF
  RETURN cprimary()
END FUNCTION

FUNCTION cterm() AS BYTE
  DIM a AS BYTE
  DIM op AS BYTE
  a = cunary()
  DO
    op = 255
    IF isop2(60, 60) <> 0 THEN
      op = O_SHL
    END IF
    IF isop2(62, 62) <> 0 THEN
      op = O_SHR
    END IF
    IF op = 255 THEN
      EXIT DO
    END IF
    CALL nexttok()
    a = mkbin(op, a, cunary())
  LOOP
  RETURN a
END FUNCTION

FUNCTION carith() AS BYTE
  DIM a AS BYTE
  DIM op AS BYTE
  a = cterm()
  DO
    op = 255
    IF isop(43) <> 0 THEN
      op = O_ADD
    END IF
    IF isop(45) <> 0 THEN
      op = O_SUB
    END IF
    IF op = 255 THEN
      EXIT DO
    END IF
    CALL nexttok()
    a = mkbin(op, a, cterm())
  LOOP
  RETURN a
END FUNCTION

FUNCTION cexpr() AS BYTE
  DIM a AS BYTE
  DIM op AS BYTE
  a = carith()
  DO
    op = 255
    IF tk = KW_AND THEN
      op = O_AND
    END IF
    IF tk = KW_OR THEN
      op = O_OR
    END IF
    IF tk = KW_XOR THEN
      op = O_XOR
    END IF
    IF op = 255 THEN
      EXIT DO
    END IF
    CALL nexttok()
    a = mkbin(op, a, carith())
  LOOP
  RETURN a
END FUNCTION

' ---- statements

SUB cdim()
  DIM s AS BYTE
  CALL nexttok()
  IF tk <> T_NAME THEN
    cerr = 6
    RETURN
  END IF
  s = syadd()
  CALL nexttok()
  IF tk = KW_AS THEN
    CALL nexttok()
    IF tk = KW_BYTE THEN
      syw(s) = 1
    END IF
    IF tk = KW_CARD THEN
      sysg(s) = 0
    END IF
    CALL nexttok()
  END IF
END SUB

SUB cconst()
  DIM s AS BYTE
  DIM e AS BYTE
  CALL nexttok()
  IF tk <> T_NAME THEN
    cerr = 7
    RETURN
  END IF
  s = syadd()
  CALL nexttok()
  IF isop(61) = 0 THEN
    cerr = 8
    RETURN
  END IF
  CALL nexttok()
  nn = 0
  e = cexpr()
  IF nk(e) <> N_NUM THEN
    cerr = 9
    RETURN
  END IF
  sykind(s) = 1
  syval(s) = nv(e)
END SUB

SUB cassign()
  DIM s AS BYTE
  DIM e AS BYTE
  DIM w AS BYTE
  s = syfind()
  IF s = 255 THEN
    s = syadd()
  END IF
  CALL nexttok()
  IF isop(61) = 0 THEN
    cerr = 10
    RETURN
  END IF
  CALL nexttok()
  nn = 0
  e = cexpr()
  w = syw(s)
  CALL cgen(e, w)
  CALL eb($69)                                  ' ST [abs16],R0
  CALL eabs(sylab(s))
  IF w = 2 THEN
    CALL eb($6B)                                ' ST [abs16],R1
    CALL eabs(sylab(s) + 1)
  END IF
END SUB

' ---------------------------------------------------------------------
' The whole program.
' ---------------------------------------------------------------------

SUB cplace()
  DIM i AS BYTE
  i = 0
  DO WHILE i < nsym
    IF sykind(i) = 0 THEN
      CALL elab(sylab(i))
      cp = cp + 1
      IF syw(i) = 2 THEN
        CALL elab(sylab(i) + 1)
        cp = cp + 1
      END IF
    END IF
    i = i + 1
  LOOP
END SUB

SUB compile(src AS CARD, org AS CARD)
  CALL cinit()
  CALL estart(org)
  ' The cross-compiler opens with a jump over the SUB bodies to main.
  ' There are no SUBs yet, so main is the next byte -- but the jump is
  ' still there, and byte-identical means identical.
  CALL ejmp(LMAIN)
  CALL elab(LMAIN)
  CALL lexstart(src)
  CALL nexttok()
  DO
    IF tk = T_EOF THEN
      EXIT DO
    END IF
    IF cerr <> 0 THEN
      EXIT DO
    END IF
    IF tk = T_NL THEN
      CALL nexttok()
    ELSE
      IF tk = KW_DIM THEN
        CALL cdim()
      ELSE
        IF tk = KW_CONST THEN
          CALL cconst()
        ELSE
          IF tk = KW_END THEN
            CALL eb($21)                        ' HALT
            CALL nexttok()
          ELSE
            IF tk = T_NAME THEN
              CALL cassign()
            ELSE
              cerr = 11
            END IF
          END IF
        END IF
      END IF
    END IF
  LOOP
  ' A HALT after the last statement, whether or not one was written --
  ' the cross-compiler emits it unconditionally, so falling off the end
  ' of a program stops rather than running into the variables.
  CALL eb($21)
  ' The variables go after the code, in the order they were declared --
  ' which is what the cross-compiler's .res block comes to.
  CALL cplace()
END SUB
