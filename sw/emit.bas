' ---------------------------------------------------------------------
' emit.bas -- the code emitter, on the machine.
'
' The back end of the self-hosted compiler: bytes out, and the machinery
' for naming an address before you know what it is. INCLUDEd by
' basic.bas, and by sim/test_emit.py's driver, which is what gates it --
' the bytes it produces have to be identical to what tools/cool8asm.py
' produces for the same program.
'
' ## The encodings are arithmetic, not a table
'
' The ISA's regularity pays for itself here. Every form the compiler
' needs is one add:
'
'   ALU Rd,#imm8        op*4 + rd
'   ALU Rd,Rs           $80 + op*16 + rd*4 + rs
'   Bcc rel8            $70 + cc
'   LD/ST Rd,[X|Y]      $40 + st*8 + rd*2 + isy
'   LD/ST Rd,[X|Y+d8]   $50 + st*8 + rd*2 + isy
'   LD/ST Rd,[SP+u8]    $60 + st*8 + rd*2 + 0
'   LD/ST Rd,[abs16]    $60 + st*8 + rd*2 + 1
'
' So there is no opcode table to carry, which is most of why this fits.
'
' ## Forward references cost no memory
'
' A label that has not been placed yet holds the head of a chain of the
' sites waiting for it, and the chain runs through the operand fields of
' those sites -- each one holds the address of the previous. When the
' label is placed the chain is walked and every field overwritten with
' the real address. Nothing is allocated per reference, which is what
' makes a one-pass compiler possible in this much memory.
'
' Absolute and relative sites need separate chains, because a byte
' cannot hold an address: a branch site holds the DISTANCE back to the
' previous branch site instead. That fits in a byte because a Bcc only
' reaches 127, so every site waiting on a label is within 127 bytes of
' it and no two of them are further apart than that.
' ---------------------------------------------------------------------

CONST NLAB = 32

' ALU operation numbers, in encoding order.
CONST E_MOV = 0
CONST E_ADD = 1
CONST E_ADC = 2
CONST E_SUB = 3
CONST E_SBC = 4
CONST E_AND = 5
CONST E_OR  = 6
CONST E_CMP = 7

' Condition codes, in encoding order.
CONST C_RA = 0
CONST C_NV = 1
CONST C_EQ = 2
CONST C_NE = 3
CONST C_CS = 4
CONST C_CC = 5
CONST C_MI = 6
CONST C_PL = 7
CONST C_VS = 8
CONST C_VC = 9
CONST C_HI = 10
CONST C_LS = 11
CONST C_GE = 12
CONST C_LT = 13
CONST C_GT = 14
CONST C_LE = 15

DIM cp AS CARD                  ' where the next byte goes, and runs
DIM labv(31) AS CARD            ' placed address, or the abs16 chain head
DIM labb(31) AS CARD            ' the rel8 chain head
DIM labr(31) AS BYTE            ' 1 once the label has been placed

SUB estart(a AS CARD)
  DIM i AS BYTE
  cp = a
  i = 0
  DO WHILE i < NLAB
    labv(i) = 0
    labb(i) = 0
    labr(i) = 0
    i = i + 1
  LOOP
END SUB

SUB eb(b AS INT)
  POKE cp, b
  cp = cp + 1
END SUB

SUB ew(w AS CARD)
  POKE cp, w AND 255
  POKE cp + 1, w >> 8
  cp = cp + 2
END SUB

FUNCTION rdw(p AS CARD) AS CARD
  DIM h AS CARD
  h = PEEK(p + 1)
  h = h << 8
  RETURN h + PEEK(p)
END FUNCTION

' ---- naming an address

' A 16-bit operand naming label l.
SUB eabs(l AS BYTE)
  CALL ew(labv(l))              ' the target, or the site before this one
  IF labr(l) = 0 THEN
    labv(l) = cp - 2
  END IF
END SUB

' A raw 16-bit operand -- an address that is already known.
SUB eaddr(a AS CARD)
  CALL ew(a)
END SUB

' The label is here. Walk both chains and fill in what they were waiting
' for, then remember the address for everything that comes after.
SUB elab(l AS BYTE)
  DIM p AS CARD
  DIM q AS CARD
  DIM d AS BYTE
  p = labv(l)
  DO WHILE p <> 0
    q = rdw(p)
    POKE p, cp AND 255
    POKE p + 1, cp >> 8
    p = q
  LOOP
  p = labb(l)
  DO WHILE p <> 0
    d = PEEK(p)
    POKE p, (cp - p - 1) AND 255
    IF d = 0 THEN
      p = 0
    ELSE
      p = p - d
    END IF
  LOOP
  labv(l) = cp
  labb(l) = 0
  labr(l) = 1
END SUB

' ---- instructions

SUB ealui(op AS BYTE, rd AS BYTE, imm AS INT)
  CALL eb(op * 4 + rd)
  CALL eb(imm AND 255)
END SUB

SUB ealur(op AS BYTE, rd AS BYTE, rs AS BYTE)
  CALL eb($80 + op * 16 + rd * 4 + rs)
END SUB

' st = 0 load, 1 store. isy = 0 X, 1 Y.
SUB eldst(rd AS BYTE, st AS BYTE, isy AS BYTE)
  CALL eb($40 + st * 8 + rd * 2 + isy)
END SUB

SUB eldstd(rd AS BYTE, st AS BYTE, isy AS BYTE, d AS INT)
  CALL eb($50 + st * 8 + rd * 2 + isy)
  CALL eb(d AND 255)
END SUB

SUB eldstsp(rd AS BYTE, st AS BYTE, u AS INT)
  CALL eb($60 + st * 8 + rd * 2)
  CALL eb(u AND 255)
END SUB

SUB eldstabs(rd AS BYTE, st AS BYTE, a AS CARD)
  CALL eb($60 + st * 8 + rd * 2 + 1)
  CALL ew(a)
END SUB

' A branch to label l. The displacement is measured from the byte after
' it, which is where the program counter will be.
SUB ebr(cc AS BYTE, l AS BYTE)
  CALL eb($70 + cc)
  IF labr(l) <> 0 THEN
    CALL eb((labv(l) - cp - 1) AND 255)
    RETURN
  END IF
  IF labb(l) = 0 THEN
    CALL eb(0)                  ' nothing before this one
  ELSE
    CALL eb(cp - labb(l))       ' the distance back to the last site
  END IF
  labb(l) = cp - 1
END SUB

SUB ejmp(l AS BYTE)
  CALL eb($28)
  CALL eabs(l)
END SUB

SUB ecall(l AS BYTE)
  CALL eb($29)
  CALL eabs(l)
END SUB

SUB ecalla(a AS CARD)
  CALL eb($29)
  CALL ew(a)
END SUB
