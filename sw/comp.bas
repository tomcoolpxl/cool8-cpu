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
CONST KW_FOR   = $85
CONST KW_NEXT  = $86
CONST KW_TO    = $87
CONST KW_DO    = $88
CONST KW_LOOP  = $89
CONST KW_WHILE = $8A
CONST KW_UNTIL = $8B
CONST KW_EXIT  = $8C
CONST KW_IF    = $8D
CONST KW_THEN  = $8E
CONST KW_ELSE  = $8F
CONST KW_ELSIF = $90
CONST KW_POKE  = $98
CONST KW_AT    = $9D
CONST KW_SUB   = $81
CONST KW_FUNC  = $82
CONST KW_RET   = $92
CONST KW_CALL  = $93

' What a block stopped on.
CONST B_EOF   = 0
CONST B_ENDIF = 1
CONST B_ELSE  = 2
CONST B_ELSIF = 3
CONST B_LOOP  = 4
CONST B_NEXT  = 5
CONST B_ENDSUB = 6

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
CONST N_CMP = 3
CONST N_PEEK = 4
CONST N_INDEX = 5
CONST N_LOCAL = 6
CONST N_PARAM = 7
CONST N_CALL = 8

' Relations. GT and LE are never generated: a 16-bit SUB leaves Z from
' the high byte alone, so BGT and BLE would be wrong whenever the low
' bytes differ and the high ones match. a > b is compiled as b < a.
CONST R_LT = 0
CONST R_GE = 1
CONST R_EQ = 2
CONST R_NE = 3
CONST R_GT = 4
CONST R_LE = 5

' MAX-, not N-: the language is case-insensitive, so a constant NSYM
' and a variable nsym are one name -- the DIM won, the guard became
' `nsym >= nsym`, and the table looked full the moment it was empty.
' 255, not 256: the expression nodes hold a symbol index in one byte
' and 255 is the "no such symbol" answer. The compiler's own source
' declares 238, so the margin is thin but real.
CONST MAXSYM = 255
CONST MAXNODE = 48

CONST MAXPOOL = 1400

' ---- the symbol table
DIM spool(1399) AS BYTE          ' the names, end to end
DIM spend AS CARD
DIM syoff(255) AS CARD           ' where each one starts
DIM sylen(255) AS BYTE
DIM sykind(255) AS BYTE          ' 0 a variable, 1 a constant
DIM syw(255) AS BYTE             ' 1 byte wide, 2 word wide
DIM sysg(255) AS BYTE            ' 1 signed
DIM syval(255) AS CARD           ' a constant's value, or an AT address
DIM sycnt(255) AS CARD           ' an array's last index
DIM syat(255) AS BYTE            ' 1 if the array was laid over an address
DIM nsym AS BYTE
DIM sylb(255) AS BYTE           ' its label, or 255 before it needs one
DIM slab AS BYTE                ' the next permanent label to hand out

' ---- the expression tree
DIM nk(47) AS BYTE
DIM nop(47) AS BYTE
DIM na(47) AS BYTE
DIM nb(47) AS BYTE
DIM nv(47) AS CARD
DIM nn AS BYTE
DIM nnx(47) AS BYTE              ' the next argument of a call

DIM cerr AS BYTE                ' 0 while everything is still fine

' Control-flow labels, above the two each symbol takes. They are
' allocated on entering a construct and given back on leaving it, so
' what bounds them is how deeply the program nests, not how long it is.
DIM clab AS BYTE          ' not nlab: emit.bas has CONST NLAB
DIM ctmps AS BYTE               ' temporaries live right now
DIM ctmax AS BYTE               ' and the most that were ever live at once
DIM lpdone AS BYTE              ' the innermost loop's exit, for EXIT DO
DIM inloop AS BYTE

' ---- the scope inside a SUB
'
' Parameters are on the stack above the frame, locals inside it. A
' parameter is read with [SP+u8] at 3 clocks against 4 for [abs16], so
' it is cheaper than a global -- the opposite of the 6502, and why
' recursion was worth keeping.
CONST MAXLOC = 16
DIM lcoff(15) AS CARD
DIM lclen(15) AS BYTE
DIM lckind(15) AS BYTE          ' 0 a local, 1 a parameter
DIM lcidx(15) AS BYTE           ' frame offset, or parameter number
DIM lcw(15) AS BYTE
DIM lcsg(15) AS BYTE
DIM nloc AS BYTE
DIM inbody AS BYTE              ' 1 while a SUB body is being compiled
DIM cfrm AS BYTE                ' locals allocated so far
DIM cfmax AS BYTE               ' and the most there have been
DIM cbtot AS BYTE               ' this body's whole frame, for [SP+@n]

' Each SUB's frame, worked out by the silent pass and used by the real
' one. SUBs are scanned before anything else, so the k-th SUB is symbol
' k and this is indexed the same way.
DIM sbloc(15) AS BYTE           ' its locals
DIM sbtot(15) AS BYTE           ' and its whole frame
DIM cloc AS BYTE                ' the locals of the body being compiled
DIM mainfrm AS BYTE             ' what main turned out to need

' ---------------------------------------------------------------------
' Symbols.
' ---------------------------------------------------------------------

SUB cinit()
  nsym = 0
  spend = 0
  cerr = 0
  clab = NLAB - 1
  slab = 1
  inloop = 0
  ctmps = 0
  ctmax = 0
  nloc = 0
  inbody = 0
  cfrm = 0
  cfmax = 0
  cbtot = 0
  cloc = 0
END SUB

' A local or parameter by the name just read, or 255.
FUNCTION lcfind() AS BYTE
  DIM i AS BYTE
  DIM k AS BYTE
  DIM p AS CARD
  DIM hit AS BYTE
  IF inbody = 0 THEN
    RETURN 255
  END IF
  i = 0
  DO WHILE i < nloc
    IF lclen(i) = tsl THEN
      p = lcoff(i)
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

' The same, for a name already sitting at the top of the pool -- DIM
' has read past it by the time the type is known.
FUNCTION lcaddback(kind AS BYTE, idx AS BYTE, w AS BYTE, sg AS BYTE) AS BYTE
  DIM i AS BYTE
  IF nloc >= MAXLOC THEN
    cerr = 34
    RETURN 255
  END IF
  i = nloc
  lcoff(i) = spend
  lclen(i) = sylen(nsym)
  spend = spend + lclen(i)
  lckind(i) = kind
  lcidx(i) = idx
  lcw(i) = w
  lcsg(i) = sg
  nloc = nloc + 1
  RETURN i
END FUNCTION

FUNCTION lcadd(kind AS BYTE, idx AS BYTE, w AS BYTE, sg AS BYTE) AS BYTE
  DIM i AS BYTE
  DIM k AS BYTE
  IF nloc >= MAXLOC THEN
    cerr = 34
    RETURN 255
  END IF
  i = nloc
  lcoff(i) = spend
  lclen(i) = tsl
  k = 0
  DO WHILE k < tsl
    spool(spend) = upper(tsb(k))
    spend = spend + 1
    k = k + 1
  LOOP
  lckind(i) = kind
  lcidx(i) = idx
  lcw(i) = w
  lcsg(i) = sg
  nloc = nloc + 1
  RETURN i
END FUNCTION

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
  sycnt(i) = 0
  syat(i) = 0
  sylb(i) = 255                 ' no label until something needs one
  nsym = nsym + 1
  RETURN i
END FUNCTION

' syfind never matches a nameless slot, so a length of zero is enough
' to hide one.

' A symbol's label, made when it is first needed.
'
' Two apiece was simple and cost 476 labels on the compiler's own
' source, most of them never used: a constant needs none, a SUB and an
' array need one, and only a scalar needs the second for its high byte.
' On demand it is nearer 180. Permanent labels grow up from 0 and
' control-flow labels down from the top, so the two disciplines --
' never freed, and freed when a construct ends -- do not have to share
' a counter.
FUNCTION sylab(i AS BYTE) AS BYTE
  IF sylb(i) <> 255 THEN
    RETURN sylb(i)
  END IF
  IF slab >= clab THEN
    cerr = 38
    RETURN 0
  END IF
  sylb(i) = slab
  IF sykind(i) = 0 THEN
    slab = slab + 2             ' a scalar needs its high byte too
  ELSE
    slab = slab + 1
  END IF
  RETURN sylb(i)
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
  IF nk(i) = N_PEEK THEN
    RETURN 1
  END IF
  IF nk(i) = N_INDEX THEN
    RETURN syw(na(i))
  END IF
  IF nk(i) >= N_LOCAL THEN
    IF nk(i) = N_CALL THEN
      RETURN 2                  ' a FUNCTION hands back a whole word
    END IF
    RETURN lcw(na(i))
  END IF
  x = cwidth(na(i))
  y = cwidth(nb(i))
  IF y > x THEN
    RETURN y
  END IF
  RETURN x
END FUNCTION

' 0 unsigned, 1 signed, 2 a literal that takes whichever it is used
' with. Only a genuinely unsigned operand forces an unsigned compare.
FUNCTION csigned(i AS BYTE) AS BYTE
  DIM x AS BYTE
  DIM y AS BYTE
  IF nk(i) = N_NUM THEN
    RETURN 2
  END IF
  IF nk(i) = N_VAR THEN
    RETURN sysg(na(i))
  END IF
  IF nk(i) = N_PEEK THEN
    RETURN 0                    ' a byte off the bus is never negative
  END IF
  IF nk(i) = N_INDEX THEN
    RETURN sysg(na(i))
  END IF
  IF nk(i) = N_CALL THEN
    RETURN 1
  END IF
  IF nk(i) >= N_LOCAL THEN
    RETURN lcsg(na(i))
  END IF
  IF nk(i) = N_BIN THEN
    x = csigned(na(i))
    y = csigned(nb(i))
    IF x = 0 THEN
      RETURN 0
    END IF
    IF y = 0 THEN
      RETURN 0
    END IF
    IF x = 2 THEN
      IF y = 2 THEN
        RETURN 2
      END IF
    END IF
  END IF
  RETURN 1
END FUNCTION

FUNCTION mkcmp(op AS BYTE, a AS BYTE, b AS BYTE) AS BYTE
  DIM i AS BYTE
  i = nn
  nn = nn + 1
  nk(i) = N_CMP
  nop(i) = op
  na(i) = a
  nb(i) = b
  RETURN i
END FUNCTION

' A slot with no name: FOR's limit, evaluated once as every BASIC since
' Dartmouth has done. It is placed with the others, in the order the
' loop was met, which is where the cross-compiler puts it too.
FUNCTION syhidden(w AS BYTE) AS BYTE
  DIM i AS BYTE
  IF nsym >= MAXSYM THEN
    cerr = 1
    RETURN 255
  END IF
  i = nsym
  syoff(i) = spend
  sylen(i) = 0
  sykind(i) = 0
  syw(i) = w
  sysg(i) = 1
  sylb(i) = 255
  nsym = nsym + 1
  RETURN i
END FUNCTION

FUNCTION isleaf(i AS BYTE) AS BYTE
  IF nk(i) = N_BIN THEN
    RETURN 0
  END IF
  IF nk(i) = N_PEEK THEN
    RETURN 0
  END IF
  IF nk(i) = N_INDEX THEN
    RETURN 0
  END IF
  IF nk(i) = N_CALL THEN
    RETURN 0
  END IF
  RETURN 1
END FUNCTION

' ---------------------------------------------------------------------
' Generating.
' ---------------------------------------------------------------------

' A spill slot, by depth. Nesting an expression inside another needs a
' deeper one; unwinding gives it back. What has to be reserved is the
' deepest the program ever got, which is why the silent pass exists.
FUNCTION ctemp() AS BYTE
  DIM k AS BYTE
  k = ctmps
  ctmps = ctmps + 1
  IF ctmps > ctmax THEN
    ctmax = ctmps
  END IF
  RETURN k
END FUNCTION

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
  IF nk(i) = N_LOCAL THEN
    s = na(i)
    CALL eldstsp(r, 0, lcidx(s))
    IF w = 2 THEN
      IF lcw(s) = 1 THEN
        CALL ealur(E_SUB, r + 1, r + 1)
      ELSE
        CALL eldstsp(r + 1, 0, lcidx(s) + 1)
      END IF
    END IF
    RETURN
  END IF
  IF nk(i) = N_PARAM THEN
    s = na(i)
    CALL eldstsp(r, 0, 2 + lcidx(s) + lcidx(s) + cbtot)
    IF w = 2 THEN
      IF lcw(s) = 1 THEN
        CALL ealur(E_SUB, r + 1, r + 1)
      ELSE
        CALL eldstsp(r + 1, 0, 3 + lcidx(s) + lcidx(s) + cbtot)
      END IF
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
  DIM k AS BYTE
  IF isleaf(i) <> 0 THEN
    CALL cload(i, 0, w)
    RETURN
  END IF
  a = na(i)
  b = nb(i)
  IF nk(i) = N_CALL THEN
    CALL cgencall(na(i), nb(i))
    RETURN
  END IF
  IF nk(i) = N_INDEX THEN
    CALL caddr(na(i), nb(i))
    CALL eb($40)                ' LD R0,[X]
    IF syw(na(i)) = 2 THEN
      CALL eb($38)              ' INCW X
      CALL eb($42)              ' LD R1,[X]
    ELSE
      IF w = 2 THEN
        CALL ealur(E_SUB, 1, 1) ' CLR R1
      END IF
    END IF
    RETURN
  END IF
  IF nk(i) = N_PEEK THEN
    a = na(i)
    IF nk(a) = N_NUM THEN
      ' A known address is one instruction, and every I/O register in
      ' the machine is a known address. That is the difference between
      ' a language that can drive hardware and one that talks about it.
      CALL eb($61)
      CALL ew(nv(a))
    ELSE
      CALL cgen(a, cwidth(a))
      CALL cxfromr()
      CALL eb($40)              ' LD R0,[X]
    END IF
    IF w = 2 THEN
      CALL ealur(E_SUB, 1, 1)   ' CLR R1
    END IF
    RETURN
  END IF
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
    ' Right first, into a slot, so the operand order of a subtraction
    ' survives being evaluated inside out.
    CALL cgen(b, w)
    k = ctemp()
    CALL etmp(0, 1, cloc + k + k)
    IF w = 2 THEN
      CALL etmp(1, 1, cloc + k + k + 1)
    END IF
    CALL cgen(a, w)
    CALL etmp(2, 0, cloc + k + k)
    IF w = 2 THEN
      CALL etmp(3, 0, cloc + k + k + 1)
    END IF
    ctmps = ctmps - 1
  END IF
  CALL cbinop(nop(i), w)
END SUB

' A fresh control label.
'
' Labels are given back when a construct ends, so the same number comes
' round again -- and it has to arrive clean. A recycled label still
' holding a placed address made ebr emit a displacement to the previous
' construct; one still holding a chain head made elab walk a chain that
' was not there any more and poke bytes wherever the garbage pointed,
' which is how the compiler ended up executing the program it was
' writing.
FUNCTION newlab() AS BYTE
  DIM l AS BYTE
  IF clab <= slab THEN
    cerr = 38
    RETURN 0
  END IF
  clab = clab - 1
  l = clab
  labv(l) = 0
  labb(l) = 0
  labr(l) = 0
  RETURN l
END FUNCTION

' LDW X,#base, or #base+off. An array laid over an address knows where
' it is; one that was allocated has to wait for the data block.
SUB eldwx(sy AS BYTE, off AS CARD)
  CALL eb($2F)
  CALL eb($60)
  IF syat(sy) <> 0 THEN
    CALL ew(syval(sy) + off)
  ELSE
    CALL eabsoff(sylab(sy), off)
  END IF
END SUB

' X = base + index * size.
'
' Two things the general form does not need to know, and this one does.
' A constant index is a constant address, so note(0) is one LDW instead
' of six instructions and a doubling. And a small array cannot carry
' into the high byte -- for one whose last element is inside 256 bytes
' the add of the index's high byte is always of zero, and dropping it is
' eight clocks off every subscript.
SUB caddr(sy AS BYTE, idx AS BYTE)
  DIM span AS CARD
  DIM off AS CARD
  span = sycnt(sy) + 1
  IF syw(sy) = 2 THEN
    span = span + span
  END IF
  IF nk(idx) = N_NUM THEN
    off = nv(idx)
    IF syw(sy) = 2 THEN
      off = off + off
    END IF
    CALL eldwx(sy, off)
    RETURN
  END IF
  CALL cgen(idx, 2)
  IF syw(sy) = 2 THEN
    CALL ealur(E_ADD, 0, 0)
    CALL ealur(E_ADC, 1, 1)
  END IF
  CALL eldwx(sy, 0)
  CALL eb($2F)
  CALL eb($70)                  ' ADDW X,R0
  IF span > 256 THEN
    CALL eb($2F)
    CALL eb($49)                ' MOV R2,XH
    CALL ealur(E_ADD, 2, 1)
    CALL eb($2F)
    CALL eb($59)                ' MOV XH,R2
  END IF
END SUB

' The arguments of a call, threaded through nnx.
SUB cargs(c AS BYTE)
  DIM a AS BYTE
  DIM prev AS BYTE
  prev = 255
  IF isop(40) = 0 THEN
    RETURN
  END IF
  CALL nexttok()
  DO WHILE isop(41) = 0
    IF tk = T_EOF THEN
      cerr = 35
      RETURN
    END IF
    IF cerr <> 0 THEN
      RETURN                    ' cexpr can fail without consuming
    END IF
    a = cexpr()
    nnx(a) = 255
    IF prev = 255 THEN
      nb(c) = a
    ELSE
      nnx(prev) = a
    END IF
    prev = a
    IF isop(44) <> 0 THEN
      CALL nexttok()
    END IF
  LOOP
  CALL nexttok()
END SUB

' Push the arguments, call, and take them off again.
'
' Every argument is evaluated into a slot BEFORE anything is pushed.
' Pushing as they were computed would move SP while a later argument was
' still reading a parameter through [SP+u8], and it would read its
' neighbour instead. The pushes then go right to left, and each load has
' to say how far SP has already travelled.
SUB cgencall(sy AS BYTE, first AS BYTE)
  DIM a AS BYTE
  DIM n AS BYTE
  DIM k AS BYTE
  DIM j AS BYTE
  DIM base AS BYTE
  base = ctmps
  n = 0
  a = first
  DO WHILE a <> 255
    CALL cgen(a, 2)             ' arguments go on the stack as words
    k = ctemp()
    CALL etmp(0, 1, cloc + k + k)
    CALL etmp(1, 1, cloc + k + k + 1)
    n = n + 1
    a = nnx(a)
  LOOP
  j = 0
  DO WHILE j < n
    k = base + n - 1 - j
    CALL etmp(0, 0, cloc + k + k + j + j)
    CALL etmp(1, 0, cloc + k + k + 1 + j + j)
    CALL eb($31)                ' PUSH R1
    CALL eb($30)                ' PUSH R0
    j = j + 1
  LOOP
  ctmps = ctmps - n
  CALL ecall(sylab(sy))
  IF n > 0 THEN
    CALL eb($2F)
    CALL eb($6C)                ' ADDW SP,#2*args
    CALL eb(n + n)
  END IF
END SUB

' X = R0:R1, the address just computed.
SUB cxfromr()
  CALL eb($2F)
  CALL eb($50)                  ' MOV XL,R0
  CALL eb($2F)
  CALL eb($55)                  ' MOV XH,R1
END SUB

' A conditional branch to a label. Always long: one pass cannot see how
' far forward a block runs, so the short branch is inverted and jumps
' over a JMP. Three bytes and two clocks on the taken path, and not
' optional. The inverse of a condition is the condition with its low bit
' flipped -- BLT/BGE, BEQ/BNE and BCC/BCS are adjacent encodings.
SUB cbranch(cc AS BYTE, l AS BYTE)
  DIM skip AS BYTE
  skip = newlab()
  CALL ebr(cc XOR 1, skip)
  CALL ejmp(l)
  CALL elab(skip)
  clab = clab - 1
END SUB

' Evaluate a comparison and branch on it.
SUB cgencond(i AS BYTE, l AS BYTE, iffalse AS BYTE)
  DIM a AS BYTE
  DIM b AS BYTE
  DIM t AS BYTE
  DIM op AS BYTE
  DIM w AS BYTE
  DIM uns AS BYTE
  DIM k AS BYTE
  IF nk(i) <> N_CMP THEN
    cerr = 12
    RETURN
  END IF
  op = nop(i)
  a = na(i)
  b = nb(i)
  IF op = R_GT THEN
    op = R_LT
    t = a
    a = b
    b = t
  END IF
  IF op = R_LE THEN
    op = R_GE
    t = a
    a = b
    b = t
  END IF
  IF iffalse <> 0 THEN
    op = op XOR 1
  END IF
  w = cwidth(a)
  IF cwidth(b) > w THEN
    w = cwidth(b)
  END IF
  uns = 0
  IF csigned(a) = 0 THEN
    uns = 1
  END IF
  IF csigned(b) = 0 THEN
    uns = 1
  END IF
  IF isleaf(b) <> 0 THEN
    CALL cgen(a, w)
    CALL cload(b, 2, w)
  ELSE
    CALL cgen(b, w)
    k = ctemp()
    CALL etmp(0, 1, cloc + k + k)
    IF w = 2 THEN
      CALL etmp(1, 1, cloc + k + k + 1)
    END IF
    CALL cgen(a, w)
    CALL etmp(2, 0, cloc + k + k)
    IF w = 2 THEN
      CALL etmp(3, 0, cloc + k + k + 1)
    END IF
    ctmps = ctmps - 1
  END IF
  CALL ealur(E_SUB, 0, 2)
  IF w = 2 THEN
    CALL ealur(E_SBC, 1, 3)
    IF op >= R_EQ THEN
      CALL ealur(E_OR, 0, 1)    ' Z is the high byte alone otherwise
    END IF
  ELSE
    uns = 1                     ' two bytes compare unsigned, always
  END IF
  IF op = R_EQ THEN
    CALL cbranch(C_EQ, l)
    RETURN
  END IF
  IF op = R_NE THEN
    CALL cbranch(C_NE, l)
    RETURN
  END IF
  IF uns <> 0 THEN
    IF op = R_LT THEN
      CALL cbranch(C_CC, l)
    ELSE
      CALL cbranch(C_CS, l)
    END IF
    RETURN
  END IF
  IF op = R_LT THEN
    CALL cbranch(C_LT, l)
  ELSE
    CALL cbranch(C_GE, l)
  END IF
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
  DIM i AS BYTE
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
  IF tk = KW_PEEK THEN
    CALL nexttok()
    IF isop(40) = 0 THEN
      cerr = 23
      RETURN mknum(0)
    END IF
    CALL nexttok()
    r = cexpr()
    IF isop(41) = 0 THEN
      cerr = 24
    ELSE
      CALL nexttok()
    END IF
    i = nn
    nn = nn + 1
    nk(i) = N_PEEK
    na(i) = r
    RETURN i
  END IF
  IF tk = T_NAME THEN
    s = lcfind()
    IF s <> 255 THEN
      CALL nexttok()
      i = nn
      nn = nn + 1
      nk(i) = N_LOCAL
      IF lckind(s) = 1 THEN
        nk(i) = N_PARAM
      END IF
      na(i) = s
      RETURN i
    END IF
    s = syfind()
    IF s = 255 THEN
      cerr = 4
      RETURN mknum(0)
    END IF
    IF sykind(s) = 3 THEN
      CALL nexttok()
      i = nn
      nn = nn + 1
      nk(i) = N_CALL
      na(i) = s
      nb(i) = 255
      CALL cargs(i)
      RETURN i
    END IF
    CALL nexttok()
    IF sykind(s) = 1 THEN
      RETURN mknum(syval(s))
    END IF
    IF sykind(s) = 2 THEN
      IF isop(40) = 0 THEN
        cerr = 29
        RETURN mknum(0)
      END IF
      CALL nexttok()
      r = cexpr()
      IF isop(41) = 0 THEN
        cerr = 30
      ELSE
        CALL nexttok()
      END IF
      i = nn
      nn = nn + 1
      nk(i) = N_INDEX
      na(i) = s
      nb(i) = r
      RETURN i
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

' A relation, if there is one, on top of the bitwise layer.
FUNCTION cexpr() AS BYTE
  DIM a AS BYTE
  DIM b AS BYTE
  DIM i AS BYTE
  DIM r AS BYTE
  a = cbitwise()
  r = 255
  IF isop(60) <> 0 THEN
    r = R_LT
  END IF
  IF isop(62) <> 0 THEN
    r = R_GT
  END IF
  IF isop(61) <> 0 THEN
    r = R_EQ
  END IF
  IF isop2(60, 62) <> 0 THEN
    r = R_NE
  END IF
  IF isop2(60, 61) <> 0 THEN
    r = R_LE
  END IF
  IF isop2(62, 61) <> 0 THEN
    r = R_GE
  END IF
  IF r = 255 THEN
    RETURN a
  END IF
  CALL nexttok()
  b = cbitwise()
  i = nn
  nn = nn + 1
  nk(i) = N_CMP
  nop(i) = r
  na(i) = a
  nb(i) = b
  RETURN i
END FUNCTION

FUNCTION cbitwise() AS BYTE
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
  DIM e AS BYTE
  CALL nexttok()
  IF tk <> T_NAME THEN
    cerr = 6
    RETURN
  END IF
  s = syadd()
  CALL nexttok()
  IF isop(40) <> 0 THEN
    CALL nexttok()
    nn = 0
    e = cexpr()
    IF nk(e) <> N_NUM THEN
      cerr = 26
      RETURN
    END IF
    sycnt(s) = nv(e)
    sykind(s) = 2
    IF isop(41) = 0 THEN
      cerr = 27
      RETURN
    END IF
    CALL nexttok()
  END IF
  IF tk = KW_AS THEN
    CALL nexttok()
    IF tk = KW_BYTE THEN
      ' A BYTE is unsigned as well as narrow. It is not a small INT:
      ' `b + 2` compared against anything picks the unsigned branch,
      ' which for values that never go negative is the right one.
      syw(s) = 1
      sysg(s) = 0
    END IF
    IF tk = KW_CARD THEN
      sysg(s) = 0
    END IF
    CALL nexttok()
  END IF
  IF inbody <> 0 THEN
    IF sykind(s) = 0 THEN
      ' Inside a SUB a scalar is a local, in the frame. The symbol just
      ' added is undone; it was only ever a place to put the name.
      nsym = nsym - 1
      spend = syoff(s)
      CALL lcaddback(0, cfrm, syw(s), sysg(s))
      cfrm = cfrm + syw(s)
      IF cfrm > cfmax THEN
        cfmax = cfrm
      END IF
      RETURN
    END IF
  END IF
  IF tk = KW_AT THEN
    ' An array laid over an address rather than allocated: the screen,
    ' the I/O page, a buffer somewhere chosen.
    CALL nexttok()
    nn = 0
    e = cexpr()
    IF nk(e) <> N_NUM THEN
      cerr = 28
      RETURN
    END IF
    syat(s) = 1
    syval(s) = nv(e)
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
  DIM idx AS BYTE
  DIM w AS BYTE
  DIM k AS BYTE
  DIM l AS BYTE
  l = lcfind()
  IF l <> 255 THEN
    CALL nexttok()
    IF isop(61) = 0 THEN
      cerr = 10
      RETURN
    END IF
    CALL nexttok()
    nn = 0
    e = cexpr()
    CALL cgen(e, lcw(l))
    CALL cstoreloc(l)
    RETURN
  END IF
  s = syfind()
  IF s = 255 THEN
    s = syadd()
  END IF
  CALL nexttok()
  IF sykind(s) = 2 THEN
    IF isop(40) = 0 THEN
      cerr = 31
      RETURN
    END IF
    CALL nexttok()
    nn = 0
    idx = cexpr()
    IF isop(41) = 0 THEN
      cerr = 32
      RETURN
    END IF
    CALL nexttok()
    IF isop(61) = 0 THEN
      cerr = 33
      RETURN
    END IF
    CALL nexttok()
    e = cexpr()
    w = syw(s)
    IF isleaf(e) <> 0 THEN
      ' The address first, then the value straight into R0:R1. A leaf
      ' cannot disturb X, so the spill the general case needs is pure
      ' waste here -- and array stores are where inner loops live.
      CALL caddr(s, idx)
      CALL cload(e, 0, w)
    ELSE
      CALL cgen(e, w)
      k = ctemp()
      CALL etmp(0, 1, cloc + k + k)
      IF w = 2 THEN
        CALL etmp(1, 1, cloc + k + k + 1)
      END IF
      CALL caddr(s, idx)
      CALL etmp(0, 0, cloc + k + k)
      IF w = 2 THEN
        CALL etmp(1, 0, cloc + k + k + 1)
      END IF
      ctmps = ctmps - 1
    END IF
    CALL eb($48)                ' ST [X],R0
    IF w = 2 THEN
      CALL eb($38)              ' INCW X
      CALL eb($4A)              ' ST [X],R1
    END IF
    RETURN
  END IF
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

' ---------------------------------------------------------------------
' Statements and blocks.
' ---------------------------------------------------------------------

SUB cstoreloc(l AS BYTE)
  IF lckind(l) = 1 THEN
    CALL eldstsp(0, 1, 2 + lcidx(l) + lcidx(l) + cbtot)
    IF lcw(l) = 2 THEN
      CALL eldstsp(1, 1, 3 + lcidx(l) + lcidx(l) + cbtot)
    END IF
    RETURN
  END IF
  CALL eldstsp(0, 1, lcidx(l))
  IF lcw(l) = 2 THEN
    CALL eldstsp(1, 1, lcidx(l) + 1)
  END IF
END SUB

SUB cstoreto(sy AS BYTE, w AS BYTE)
  CALL eb($69)                                  ' ST [abs16],R0
  CALL eabs(sylab(sy))
  IF w = 2 THEN
    CALL eb($6B)                                ' ST [abs16],R1
    CALL eabs(sylab(sy) + 1)
  END IF
END SUB

SUB cif()
  DIM endl AS BYTE
  DIM nxt AS BYTE
  DIM e AS BYTE
  DIM r AS BYTE
  DIM save AS BYTE
  save = clab
  endl = newlab()
  nxt = newlab()
  CALL nexttok()
  nn = 0
  e = cexpr()
  IF tk <> KW_THEN THEN
    cerr = 15
    RETURN
  END IF
  CALL nexttok()
  CALL cgencond(e, nxt, 1)
  IF tk <> T_NL THEN
    CALL cstmt()                                ' a single-line IF
    CALL elab(nxt)
    clab = save
    RETURN
  END IF
  r = cblock()
  IF r = B_ELSE THEN
    CALL nexttok()
    CALL ejmp(endl)
    CALL elab(nxt)
    r = cblock()
    IF r <> B_ENDIF THEN
      cerr = 16
      RETURN
    END IF
    CALL nexttok()
    CALL elab(endl)
    clab = save
    RETURN
  END IF
  IF r = B_ELSIF THEN
    ' ELSEIF is an IF inside the else arm, which is all it ever was.
    CALL ejmp(endl)
    CALL elab(nxt)
    CALL cif()
    CALL elab(endl)
    clab = save
    RETURN
  END IF
  IF r <> B_ENDIF THEN
    cerr = 17
    RETURN
  END IF
  CALL nexttok()
  CALL elab(nxt)
  clab = save
END SUB

SUB cdo()
  DIM top AS BYTE
  DIM done AS BYTE
  DIM save AS BYTE
  DIM svd AS BYTE
  DIM svi AS BYTE
  DIM e AS BYTE
  DIM r AS BYTE
  save = clab
  top = newlab()
  done = newlab()
  CALL nexttok()
  CALL elab(top)
  IF tk = KW_WHILE THEN
    CALL nexttok()
    nn = 0
    e = cexpr()
    CALL cgencond(e, done, 1)
  ELSE
    IF tk = KW_UNTIL THEN
      CALL nexttok()
      nn = 0
      e = cexpr()
      CALL cgencond(e, done, 0)
    END IF
  END IF
  svd = lpdone
  svi = inloop
  lpdone = done
  inloop = 1
  r = cblock()
  lpdone = svd
  inloop = svi
  IF r <> B_LOOP THEN
    cerr = 18
    RETURN
  END IF
  CALL nexttok()
  IF tk = KW_WHILE THEN
    CALL nexttok()
    nn = 0
    e = cexpr()
    CALL cgencond(e, top, 0)
  ELSE
    IF tk = KW_UNTIL THEN
      CALL nexttok()
      nn = 0
      e = cexpr()
      CALL cgencond(e, top, 1)
    ELSE
      CALL ejmp(top)
    END IF
  END IF
  CALL elab(done)
  clab = save
END SUB

SUB cfor()
  DIM sy AS BYTE
  DIM lim AS BYTE
  DIM top AS BYTE
  DIM done AS BYTE
  DIM save AS BYTE
  DIM svd AS BYTE
  DIM svi AS BYTE
  DIM a AS BYTE
  DIM b AS BYTE
  DIM w AS BYTE
  DIM r AS BYTE
  save = clab
  top = newlab()
  done = newlab()
  CALL nexttok()
  IF tk <> T_NAME THEN
    cerr = 19
    RETURN
  END IF
  sy = syfind()
  IF sy = 255 THEN
    sy = syadd()
  END IF
  CALL nexttok()
  IF isop(61) = 0 THEN
    cerr = 20
    RETURN
  END IF
  CALL nexttok()
  nn = 0
  a = cexpr()
  IF tk <> KW_TO THEN
    cerr = 21
    RETURN
  END IF
  CALL nexttok()
  b = cexpr()
  w = syw(sy)
  lim = syhidden(w)
  ' The limit first, once, then the start.
  CALL cgen(b, w)
  CALL cstoreto(lim, w)
  CALL cgen(a, w)
  CALL cstoreto(sy, w)
  CALL elab(top)
  ' Tested at the top, so FOR i = 1 TO 0 runs no times at all.
  nn = 0
  CALL cgencond(mkcmp(R_LE, mkvar(sy), mkvar(lim)), done, 1)
  svd = lpdone
  svi = inloop
  lpdone = done
  inloop = 1
  r = cblock()
  lpdone = svd
  inloop = svi
  IF r <> B_NEXT THEN
    cerr = 22
    RETURN
  END IF
  CALL nexttok()
  IF tk = T_NAME THEN
    CALL nexttok()
  END IF
  nn = 0
  CALL cgen(mkbin(O_ADD, mkvar(sy), mknum(1)), w)
  CALL cstoreto(sy, w)
  CALL ejmp(top)
  CALL elab(done)
  clab = save
END SUB

' A SUB definition met while compiling main: its body comes later.
SUB cskipsub()
  DO
    IF tk = T_EOF THEN
      RETURN
    END IF
    IF tk = KW_END THEN
      CALL nexttok()
      IF tk = KW_SUB THEN
        CALL nexttok()
        RETURN
      END IF
      IF tk = KW_FUNC THEN
        CALL nexttok()
        RETURN
      END IF
    ELSE
      CALL nexttok()
    END IF
  LOOP
END SUB

SUB cpoke()
  DIM a AS BYTE
  DIM v AS BYTE
  DIM k AS BYTE
  CALL nexttok()
  nn = 0
  a = cexpr()
  IF isop(44) = 0 THEN
    cerr = 25
    RETURN
  END IF
  CALL nexttok()
  v = cexpr()
  IF nk(a) = N_NUM THEN
    CALL cgen(v, 1)             ' a POKE writes one byte
    CALL eb($69)
    CALL ew(nv(a))
    RETURN
  END IF
  IF isleaf(v) <> 0 THEN
    CALL cgen(a, cwidth(a))
    CALL cxfromr()
    CALL cload(v, 0, 2)
  ELSE
    ' At its own width, not the pointer's: `b + 2` on a byte stays a
    ' byte, and only the slot it is parked in is two wide.
    CALL cgen(v, cwidth(v))
    k = ctemp()
    CALL etmp(0, 1, cloc + k + k)
    CALL etmp(1, 1, cloc + k + k + 1)
    CALL cgen(a, cwidth(a))
    CALL cxfromr()
    CALL etmp(0, 0, cloc + k + k)
    CALL etmp(1, 0, cloc + k + k + 1)
    ctmps = ctmps - 1
  END IF
  CALL eb($48)                  ' ST [X],R0
END SUB

SUB cstmt()
  DIM e AS BYTE
  IF tk = KW_DIM THEN
    CALL cdim()
    RETURN
  END IF
  IF tk = KW_CONST THEN
    CALL cconst()
    RETURN
  END IF
  IF tk = KW_IF THEN
    CALL cif()
    RETURN
  END IF
  IF tk = KW_DO THEN
    CALL cdo()
    RETURN
  END IF
  IF tk = KW_FOR THEN
    CALL cfor()
    RETURN
  END IF
  IF tk = KW_EXIT THEN
    CALL nexttok()
    CALL nexttok()                              ' the DO
    IF inloop = 0 THEN
      cerr = 14
      RETURN
    END IF
    CALL ejmp(lpdone)
    RETURN
  END IF
  IF tk = KW_RET THEN
    CALL nexttok()
    IF tk <> T_NL THEN
      ' A FUNCTION hands back a full word whatever the expression's own
      ' width is, or the caller stores rubbish above the answer.
      nn = 0
      e = cexpr()
      CALL cgen(e, 2)
    END IF
    IF inbody <> 0 THEN
      ' Release the frame; R0:R1 stands. Nothing at all when there is
      ' no frame -- the cross-compiler drops the line, so an ADDW SP,#0
      ' here would be three bytes it never wrote.
      CALL eframeup(cbtot)
    END IF
    CALL eb($22)                ' RET
    RETURN
  END IF
  IF tk = KW_CALL THEN
    CALL nexttok()
    IF tk <> T_NAME THEN
      cerr = 36
      RETURN
    END IF
    nn = 0
    e = cprimary()
    CALL cgen(e, 2)
    RETURN
  END IF
  IF tk = KW_SUB THEN
    CALL cskipsub()
    RETURN
  END IF
  IF tk = KW_FUNC THEN
    CALL cskipsub()
    RETURN
  END IF
  IF tk = KW_POKE THEN
    CALL cpoke()
    RETURN
  END IF
  IF tk = T_NAME THEN
    CALL cassign()
    RETURN
  END IF
  cerr = 11
END SUB

' Statements up to a terminator. Which terminator it was.
FUNCTION cblock() AS BYTE
  DO
    IF cerr <> 0 THEN
      RETURN B_EOF
    END IF
    IF tk = T_EOF THEN
      RETURN B_EOF
    END IF
    IF tk = T_NL THEN
      CALL nexttok()
    ELSE
      IF tk = KW_ELSE THEN
        RETURN B_ELSE
      END IF
      IF tk = KW_ELSIF THEN
        RETURN B_ELSIF
      END IF
      IF tk = KW_LOOP THEN
        RETURN B_LOOP
      END IF
      IF tk = KW_NEXT THEN
        RETURN B_NEXT
      END IF
      IF tk = KW_END THEN
        CALL nexttok()
        IF tk = KW_IF THEN
          RETURN B_ENDIF
        END IF
        IF tk = KW_SUB THEN
          RETURN B_ENDSUB
        END IF
        IF tk = KW_FUNC THEN
          RETURN B_ENDSUB
        END IF
        CALL eb($21)                            ' a bare END is a HALT
      ELSE
        CALL cstmt()
      END IF
    END IF
  LOOP
END FUNCTION

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
    IF sykind(i) = 2 THEN
      IF syat(i) = 0 THEN
        CALL elab(sylab(i))
        cp = cp + syw(i) * (sycnt(i) + 1)
      END IF
    END IF
    i = i + 1
  LOOP
END SUB

' One look ahead for SUB names, so a call can come before its
' definition. It is the only thing this compiler reads twice -- and
' because it runs first in both passes, the k-th SUB is symbol k, which
' is how each body's frame survives from one pass to the other.
SUB cscan(src AS CARD)
  DIM sy AS BYTE
  DIM n AS BYTE
  DIM isfn AS BYTE
  CALL lexstart(src)
  CALL nexttok()
  DO WHILE tk <> T_EOF
    isfn = 2
    IF tk = KW_SUB THEN
      isfn = 0
    END IF
    IF tk = KW_FUNC THEN
      isfn = 1
    END IF
    IF cerr <> 0 THEN
      RETURN
    END IF
    IF isfn = 2 THEN
      CALL nexttok()
    ELSE
      CALL nexttok()
      IF tk = T_NAME THEN
        sy = syadd()
        sykind(sy) = 3
        syat(sy) = isfn
        n = 0
        CALL nexttok()
        IF isop(40) <> 0 THEN
          CALL nexttok()
          DO WHILE isop(41) = 0
            IF tk = T_EOF THEN
              EXIT DO
            END IF
            IF tk = T_NAME THEN
              n = n + 1
            END IF
            CALL nexttok()
          LOOP
        END IF
        sycnt(sy) = n
      END IF
    END IF
  LOOP
END SUB

' One SUB body. tk is on its SUB or FUNCTION.
SUB cbody(k AS BYTE)
  DIM l AS BYTE
  DIM i AS BYTE
  DIM r AS BYTE
  CALL nexttok()                ' the name
  CALL nexttok()
  nloc = 0
  inbody = 1
  cfrm = 0
  cfmax = 0
  ctmps = 0
  ctmax = 0
  cloc = sbloc(k)
  cbtot = sbtot(k)
  i = 0
  IF isop(40) <> 0 THEN
    CALL nexttok()
    DO WHILE isop(41) = 0
      IF tk = T_EOF THEN
        EXIT DO
      END IF
      IF tk <> T_NAME THEN
        EXIT DO
      END IF
      l = lcadd(1, i, 2, 1)
      i = i + 1
      CALL nexttok()
      IF tk = KW_AS THEN
        CALL nexttok()
        IF tk = KW_BYTE THEN
          lcw(l) = 1
          lcsg(l) = 0
        END IF
        IF tk = KW_CARD THEN
          lcsg(l) = 0
        END IF
        CALL nexttok()
      END IF
      IF isop(44) <> 0 THEN
        CALL nexttok()
      END IF
    LOOP
    CALL nexttok()
  END IF
  IF tk = KW_AS THEN            ' FUNCTION f(...) AS INT
    CALL nexttok()
    CALL nexttok()
  END IF
  CALL elab(sylab(k))
  CALL eframe(cbtot)
  r = cblock()
  IF r <> B_ENDSUB THEN
    cerr = 37
  END IF
  CALL nexttok()                ' the SUB or FUNCTION after END
  CALL eframeup(cbtot)
  CALL eb($22)                  ' RET
  inbody = 0
  sbloc(k) = cfmax
  sbtot(k) = cfmax + ctmax + ctmax
END SUB

' Every SUB body, after main, in the order they were written.
SUB csubs(src AS CARD)
  DIM k AS BYTE
  k = 0
  CALL lexstart(src)
  CALL nexttok()
  DO WHILE tk <> T_EOF
    IF cerr <> 0 THEN
      RETURN
    END IF
    IF tk = KW_SUB THEN
      CALL cbody(k)
      k = k + 1
    ELSE
      IF tk = KW_FUNC THEN
        CALL cbody(k)
        k = k + 1
      ELSE
        CALL nexttok()
      END IF
    END IF
  LOOP
END SUB

' One run over the program: the scan, the jump to main, the frame, the
' body, the closing HALT, the SUBs and the variables.
SUB cpass(src AS CARD, org AS CARD, frame AS INT, quiet AS BYTE)
  DIM r AS BYTE
  CALL cinit()
  CALL estart(org)
  ' After estart, which knows nothing about passes.
  equiet = quiet
  CALL cscan(src)
  ' The cross-compiler opens with a jump over the SUB bodies to main.
  CALL ejmp(0)
  CALL elab(0)
  CALL eframe(frame)
  cloc = 0
  cbtot = frame
  CALL lexstart(src)
  CALL nexttok()
  r = cblock()
  ' A HALT after the last statement, whether or not one was written --
  ' the cross-compiler emits it unconditionally, so falling off the end
  ' of a program stops rather than running into the variables.
  CALL eb($21)
  mainfrm = ctmax + ctmax
  CALL csubs(src)
  ' The variables go after the code, in the order they were declared --
  ' which is what the cross-compiler's .res block comes to.
  CALL cplace()
  CALL efixups()
END SUB

SUB compile(src AS CARD, org AS CARD)
  DIM i AS BYTE
  i = 0
  DO WHILE i < 16
    sbloc(i) = 0
    sbtot(i) = 0
    i = i + 1
  LOOP
  ' Once in the dark, to find out how deep every frame goes, then once
  ' for real with frames the right size.
  CALL cpass(src, org, 0, 1)
  CALL cpass(src, org, mainfrm, 0)
END SUB
