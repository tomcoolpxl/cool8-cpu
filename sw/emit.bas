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

' Every variable takes two: one label for its low byte and one for its
' high, placed a byte apart. A chain patches in the address it is given,
' so `v+1` cannot be expressed as an offset from `v` -- it has to be its
' own label.
CONST NLAB = 192

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

' ## Why there is a silent pass
'
' The frame prologue is ADDW SP,#-total, and the cross-compiler deletes
' the line altogether when the total is zero. This emitter writes bytes,
' so it cannot delete one it has already written, and it cannot know the
' total until the body has been read.
'
' So the body is compiled twice. The first time equiet is set: cp still
' advances exactly as it will the second time -- no instruction's length
' depends on a label's value, because every forward branch is emitted
' long -- but nothing is written and no chain is touched. That pass
' costs only time, and it is the only thing that knows how many
' temporaries the program wants before the program has been read.
DIM equiet AS BYTE

' ## Offset references need a table
'
' The chain cannot carry `base + off`: the operand field holds the link
' to the previous site waiting on the label, and there is nowhere left
' to put an addend. Array element addresses are the only place it comes
' up -- LDW X,#base+off -- so those sites are recorded here instead and
' filled in once every label has been placed.
CONST MAXFIX = 128
DIM fxsite(127) AS CARD
DIM fxlab(127) AS BYTE
DIM fxoff(127) AS CARD
DIM nfx AS BYTE

DIM cp AS CARD                  ' where the next byte goes, and runs
DIM labv(191) AS CARD            ' placed address, or the abs16 chain head
DIM labb(191) AS CARD            ' the rel8 chain head
DIM labr(191) AS BYTE            ' 1 once the label has been placed

SUB estart(a AS CARD)
  ' CARD, not BYTE: NLAB is 256 and a byte counter never reaches it --
  ' it wraps to 0 and the loop runs for ever. The same trap cost a
  ' session once already.
  DIM i AS CARD
  cp = a
  nfx = 0
  i = 0
  DO WHILE i < NLAB
    labv(i) = 0
    labb(i) = 0
    labr(i) = 0
    i = i + 1
  LOOP
END SUB

SUB eb(b AS INT)
  IF equiet = 0 THEN
    POKE cp, b
  END IF
  cp = cp + 1
END SUB

SUB ew(w AS CARD)
  IF equiet = 0 THEN
    POKE cp, w AND 255
    POKE cp + 1, w >> 8
  END IF
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
  IF equiet <> 0 THEN
    RETURN
  END IF
  IF labr(l) = 0 THEN
    labv(l) = cp - 2
  END IF
END SUB

' A 16-bit operand naming label l plus a constant offset.
SUB eabsoff(l AS BYTE, off AS CARD)
  IF equiet = 0 THEN
    IF nfx < MAXFIX THEN
      fxsite(nfx) = cp
      fxlab(nfx) = l
      fxoff(nfx) = off
      nfx = nfx + 1
    END IF
  END IF
  CALL ew(0)
END SUB

' Every offset reference, now that the labels are all placed.
SUB efixups()
  DIM i AS BYTE
  DIM a AS CARD
  IF equiet <> 0 THEN
    RETURN
  END IF
  i = 0
  DO WHILE i < nfx
    a = labv(fxlab(i)) + fxoff(i)
    POKE fxsite(i), a AND 255
    POKE fxsite(i) + 1, a >> 8
    i = i + 1
  LOOP
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
  IF equiet <> 0 THEN
    labv(l) = cp
    labr(l) = 1
    RETURN
  END IF
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
  IF equiet <> 0 THEN
    CALL eb(0)
    RETURN
  END IF
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

' A frame of `n` bytes, or nothing at all when there is none.
SUB eframe(n AS INT)
  IF n = 0 THEN
    RETURN
  END IF
  CALL eb($2F)
  CALL eb($6C)                  ' ADDW SP,#d8, signed
  CALL eb((0 - n) AND 255)
END SUB

' And giving it back.
SUB eframeup(n AS INT)
  IF n = 0 THEN
    RETURN
  END IF
  CALL eb($2F)
  CALL eb($6C)
  CALL eb(n AND 255)
END SUB

' A temporary at [SP+off]: st = 0 load into Rr, 1 store from Rr.
SUB etmp(rd AS BYTE, st AS BYTE, off AS INT)
  CALL eb($60 + st * 8 + rd * 2)
  CALL eb(off AND 255)
END SUB

SUB ecalla(a AS CARD)
  CALL eb($29)
  CALL ew(a)
END SUB
