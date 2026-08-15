; ---------------------------------------------------------------------
; fpbas.asm -- floating point, as BASIC sees it.
;
; `sw/fp.asm` is the arithmetic and knows nothing about the language.
; This is the join: the functions BASIC calls, and the convention that
; lets a float travel through the expression evaluator.
;
; ## A float is STYPE 2, and it lives in FACC
;
; The evaluator already had a type byte, because strings needed one:
; `STYPE` is 0 for a number and non-zero for a string, and a string's
; value is not in R0:R1 either -- it is in SACC/SLEN, and every operator
; that cares tests STYPE and takes the other path (`erel`'s `.cat` is
; the model). **Floats are the same shape with a third value: STYPE 2,
; and the number is in FACC.**
;
; That is why this costs as little as it does. Nothing new was invented
; for it; the mechanism strings needed in 1977 is the mechanism floats
; need now, and D63 bought the space by deleting the assembler.
;
; ## Promotion is one-way and implicit
;
; An integer meeting a float is converted to float, never the reverse.
; A float reaching somewhere that must have an integer -- a `POKE`
; address, `PLOT`'s coordinates, a `FOR` limit -- is not converted at
; all: those read R0:R1 and a float never put anything there. Use `INT`
; to cross back deliberately, which is the same rule as [D62]'s gated
; calls and one a reader can hold.
; ---------------------------------------------------------------------

; ---- fretf: the tail every float-valued builtin returns through, the
; ---- way `retnum` is the one every integer-valued builtin uses.
fretf:  MOV  R0,#2
        ST   [STYPE],R0
        RET

; ---- PI -- a constant, and the only builtin here that reads no
; ---- argument at all. `4*ATN(1)` is the same number and costs a
; ---- Gregory series to get it; three bytes in the table `fatan`
; ---- already draws its folds from is the honest way to spell it.
; ----
; ---- No '#' on the name. The suffix is a *variable's* type in this
; ---- language and every float-valued builtin here -- SIN, COS, SQR,
; ---- FLT -- goes without one; PI# would have been the only exception
; ---- and would have implied a type system that does not exist.
; ---- `fload` writes through Y, so this saves it like every one of its
; ---- neighbours and leaves through `frtn` rather than `fretf`. Going
; ---- straight to fretf was wrong in the one way a test of `PRINT PI`
; ---- alone cannot see: the value was right and the *rest of the
; ---- expression* was gone, so PI-1 printed 3.141 and so did PI*2.
i_pi:   PUSHW Y
        LDW  X,#KPI
        CALL fload
        BRA  frtn

; ---- fargf: "( expression )" for a function that wants a float.
; ----
; ---- The argument may already be one -- `SIN(A#)` -- so the type is
; ---- read before converting. R2 carries the test because R0:R1 still
; ---- holds the integer that ffromi is about to take.
fargf:  CALL earg
        LD   R2,[STYPE]
        CMP  R2,#2
        BEQ  .have
        JMP  ffromi
.have:  RET

; ---------------------------------------------------------------------
; **Every entry into fp.asm goes through here, and the reason is Y.**
;
; `fcp4` and `fswap` take their destination in Y, and `fstr` walks Y
; over its output. That was free while the package was a library called
; from a driver. It is not free now: **Y is the interpreter's token
; pointer**, so a float routine returning leaves the program position
; pointing at nothing.
;
; The symptom was not a crash. `PRINT SQR(2)` worked, because a wrecked
; Y reads as end-of-line and PRINT was finished anyway; `PRINT SQR(2) +
; 1` printed nothing, because the `+ 1` had been lost. Anything that
; called a float routine and then kept parsing failed, and anything that
; stopped immediately did not.
;
; Four bytes a site. Saving inside fp.asm instead is not possible --
; the caller is what puts the destination in Y.
; ---------------------------------------------------------------------
; **Caller saves, and inline.** The first version routed every call
; through one trampoline that took the routine in X and jumped to it.
; That was worse on both counts it was meant to help: an extra CALL and
; an indirect JMP on every float operation, and *more* bytes, because
; six per site plus the trampoline beats five per site.
;
; Callee-preserves -- PUSHW Y inside fp.asm's own entries -- reads
; better and costs more, because the nesting is real: fsqrt calls fdiv
; and fadd four times each, so a save inside them is four redundant
; saves per square root.
;
; Two instructions at a call site, against 350 cycles for a multiply, is
; under two per cent.

i_sin:  CALL fargf
        PUSHW Y
        CALL fsin
        BRA  frtn
i_cos:  CALL fargf
        PUSHW Y
        CALL fcos
        BRA  frtn
i_tan:  CALL fargf
        PUSHW Y
        CALL ftan
        BRA  frtn
i_atn:  CALL fargf
        PUSHW Y
        CALL fatan
        BRA  frtn
i_sqr:  CALL fargf
        PUSHW Y
        CALL fsqrt
        BRA  frtn
i_log:  CALL fargf
        PUSHW Y
        CALL flog
        BRA  frtn
i_exp:  CALL fargf
        PUSHW Y
        CALL fexp
frtn:   POPW Y
        JMP  fretf

; ---- FLT(n): an integer as a float, for when nothing in an expression
; ---- would otherwise promote it. `A# = FLT(1) / FLT(3)` is how you
; ---- write a third without a float literal in the tokeniser.
i_flt:  CALL earg
        LD   R2,[STYPE]
        CMP  R2,#2
        BEQ  fretf
        CALL ffromi
        JMP  fretf

; ---- ABS(n) and SGN(n), the two the package always had and the
; ---- language did not: fabs and fsgn sit at jump-table +54 and +60.
; ----
; ---- **ABS keeps the type and SGN does not**, and both are deliberate.
; ---- The magnitude of a float is still a float, so ABS has to branch;
; ---- but a sign is only ever -1, 0 or 1, and as an integer it can
; ---- subscript, POKE and drive a FOR where a float cannot. Answering
; ---- an integer also lets one path serve both argument types, which
; ---- is why SGN is six instructions: fargf promotes an integer
; ---- argument, fsgn reduces it, ftoi brings it back.
i_abs:  CALL earg
        LD   R2,[STYPE]
        CMP  R2,#2
        BEQ  .f
        TST  R1
        BPL  .p
        CALL negp16
.p:     JMP  retnum
.f:     CALL fabs
        JMP  fretf

i_sgn:  CALL fargf
        PUSHW Y                 ; fp.asm owns Y
        CALL fsgn
        CALL ftoi
        POPW Y
        JMP  retnum

; =====================================================================
; Operators.
;
; `+ - * / ^` promote: if either side is a float the other is converted
; and the float routine runs. Comparisons promote too, through `rhs`.
;
; Everything else in the language stays integer -- `FOR`, `POKE`,
; `PLOT`, a subscript and a line number read R0:R1, and a float never
; put anything there. **This comment used to claim that was a `?TYPE`
; rather than a silent truncation. It is not, and there is no ?TYPE:**
; they act on whatever the integer registers last held and say nothing.
; Measured, not assumed -- the cases are pinned in sim/test_run.py.
; `INT` crosses back.
;
; ## Why the left operand goes on the stack
;
; The evaluator is recursive and there is one FACC. By the time the
; right operand has been worked out it may itself have been a float
; expression, and it will have overwritten the left. So the left is
; pushed before `prim` runs and recovered after -- five bytes, one
; frame per pending operator, which nests exactly as the expression
; does.
;
; **Everything here addresses FACC and FARG absolutely, and touches
; neither X nor Y.** Y is the token pointer; borrowing it for a
; four-byte copy would lose the caller's place in the program.
; =====================================================================

; =====================================================================
; A#-Z#, and any longer name ending in '#'.
;
; **A float variable needs no storage of its own.** A name table entry
; is ten bytes with a two-byte `value` and a two-byte `aux` beside it,
; contiguous -- that is how a string keeps a pointer, a length and a
; capacity in one entry. A packed float is three bytes and simply lives
; there. Nothing was allocated, no base address exists, and `A`, `A#`
; and `A$` are three unrelated variables because the suffix is part of
; the name.
;
; The cost was one bit in `ctab` -- '#' joins '$' as a character that
; may appear inside a name -- and a second entry point on `isstr`.
; =====================================================================

; ---- floadv: the float whose entry starts at X, into FACC. `fload`
; ---- unpacks and takes Y for its destination, so Y is saved.
floadv: PUSHW Y
        CALL fload
        POPW Y
        JMP  fretf

; ---- h_letf: A# = <expression>. An integer right-hand side is
; ---- promoted, so `A# = 1` is 1.0 and not a bit pattern.
h_letf: PUSHW X                 ; the entry, across eval
        SKIPSP
        INCW Y                  ; the '='
        CALL eval
        LD   R2,[STYPE]
        CMP  R2,#2
        BEQ  .have
        CALL ffromi
.have:  POPW X
        CALL fstore             ; packs three bytes; X only, no Y
        JMP  stmt

; ---- fsav: the left operand onto a stack of its own.
; ----
; ---- **Not the CPU stack.** The first version pushed there and it
; ---- cannot work: `fsav` is reached by CALL, so its pushes bury its
; ---- own return address, and `fpair`'s first POP takes the return
; ---- address instead of the type. The symptom was every expression in
; ---- the language evaluating to 0.
; ----
; ---- Five bytes a frame -- a type and four of value -- and one frame
; ---- per pending operator, so the depth is the expression's. FSDEEP,
; ---- at the foot of this file, says how many there are.
fsav:   LD   R3,[FSP]
        CMP  R3,#FSDEEP*5
        BCC  .room
        ; Past the top. Refuse the way `edin` refuses a too-deep
        ; expression: set ERR and carry on, because every enclosing
        ; level will refuse in turn and `stmt` checks ERR before it runs
        ; anything else.
        ;
        ; **The check is not optional.** FSTK ends at $00FC and FSP and
        ; FLTY are the two bytes after it, so an eighth frame would
        ; overwrite the stack pointer that put it there and then run on
        ; into $0100, the far end of the CPU stack.
        MOV  R3,#E_DEEP
        ST   [ERR],R3
        RET
.room:  LDW  X,#FSTK
        ADDW X,R3
        ADD  R3,#5
        ST   [FSP],R3
        LD   R2,[STYPE]
        ST   [X],R2
        INCW X
        CMP  R2,#2
        BEQ  .f
        ST   [X],R0             ; an integer: two bytes and two spare
        INCW X
        ST   [X],R1
        BRA  .z
.f:     LD   R2,[FACC]
        ST   [X],R2
        INCW X
        LD   R2,[FACC+1]
        ST   [X],R2
        INCW X
        LD   R2,[FACC+2]
        ST   [X],R2
        INCW X
        LD   R2,[FACC+3]
        ST   [X],R2
        ; ---- and the right operand starts out an integer.
        ;
        ; **`prim` does not clear STYPE for a number**, and never had to:
        ; only strings used the type, and `sreset` cleared it once per
        ; statement. With floats in it that leaks -- after `SQR(2)` the
        ; type is still 2, so the `1` in `SQR(2) + 1` was read as a float
        ; and fpair went to FACC for a value that was the left operand.
        ; Clearing it here is right because this is the one moment that
        ; is always immediately before the right operand is evaluated.
.z:     CLR  R2
        ST   [STYPE],R2
        RET

; ---- fa2b: FACC into FARG, absolutely. No pointer register is free.
fa2b:   LD   R0,[FACC]
        ST   [FARG],R0
        LD   R0,[FACC+1]
        ST   [FARG+1],R0
        LD   R0,[FACC+2]
        ST   [FARG+2],R0
        LD   R0,[FACC+3]
        ST   [FARG+3],R0
        RET

; ---- the four operators, token pointer protected. erel calls these and
; ---- never fp.asm directly. fdiv happens not to touch Y today, and is
; ---- wrapped anyway: the contract is the package's, not one routine's.
; ---- They share a tail, and the tail is `fretf`: the answer is in FACC
; ---- so the type must say 2, and every caller wanted that anyway. It
; ---- being here rather than at each call site is what pays for the
; ---- promotion in mulrest.
fopadd: PUSHW Y
        CALL fadd
        BRA  fptl
fopsub: PUSHW Y
        CALL fsub
        BRA  fptl
fopmul: PUSHW Y
        CALL fmul
        BRA  fptl
        ; The one domain error that is wired up, because leaving it
        ; silent made the language inconsistent with itself: `1 / 0` is
        ; ?DIVISION BY ZERO and `X# / FLT(0)` quietly returned the
        ; numerator. fdiv already sets carry for it -- the jump table
        ; promises "C on /0" -- so this is the test, not the detection.
        ; LOG and SQR still discard theirs; see 13-basic.md section 8.
fopdiv: PUSHW Y
        CALL fdiv
        BCS  .z
        BRA  fptl
.z:     POPW Y
        MOV  R0,#E_DIV0
        ST   [ERR],R0
        RET
foppow: PUSHW Y
        CALL fpow
fptl:   POPW Y
        JMP  fretf

; ---- fopnd: save the left, take the right operand, pair them. Five
; ---- arms open exactly this way -- erel's *, / and ^, and mulrest's
; ---- two -- so it is one call there instead of three. Carry is
; ---- fpair's: clear for two integers, set with both promoted.
fopnd:  CALL fsav
        CALL prim
        CALL pwrest             ; `2 * 3 ^ 2` is 2 * (3^2): the right
        JMP  fpair              ;   operand takes its own powers first

; ---- fprom: both operands were integers and the operator wants floats
; ---- anyway. Only `^` does: `2 ^ 10` has an integer answer but the
; ---- route to it is exp(y ln x), and half-promoting would be a second
; ---- power routine for the case that saves least.
fprom:  PUSH R1                 ; the left, while the right goes first
        PUSH R0
        MOV  R0,R2
        MOV  R1,R3
        CALL ffromi
        CALL fa2b               ; FARG = right
        POP  R0
        POP  R1
        JMP  ffromi             ; FACC = left

; ---------------------------------------------------------------------
; fpair -- both operands in place for the operator about to run.
;
;   C clear  both were integers: left in R0:R1, right in R2:R3
;   C set    at least one was a float: FACC is the left, FARG the right
;
; The caller does not have to know which; it branches on carry and runs
; either the integer instruction or the fp.asm routine.
; ---------------------------------------------------------------------
fpair:  LD   R3,[FSP]
        SUB  R3,#5
        ST   [FSP],R3
        LDW  X,#FSTK
        ADDW X,R3               ; X on the frame fsav wrote
        LD   R2,[X]             ; the left's type
        ST   [FLTY],R2          ; kept: the arms below clobber R2
        INCW X
        LD   R3,[STYPE]
        CMP  R3,#2
        BEQ  .rfl               ; the right is a float, already in FACC
        CMP  R2,#2
        BEQ  .rint              ; left float, right integer: promote it
        ; ---- both integers: the right moves aside, the left comes back
        MOV  R2,R0
        MOV  R3,R1
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        CLC
        RET
.rint:  PUSHW X                 ; ffromi needs R0:R1 and takes X
        CALL ffromi
        POPW X
.rfl:   CALL fa2b               ; the right belongs in FARG
        ; ---- and now the left, **promoted if it is an integer**. The
        ; ---- first version copied its two bytes into FACC as though
        ; ---- they were a float, which is a wild exponent -- and the
        ; ---- symptom was not a wrong answer but a hang, because fstr's
        ; ---- scaling loop divides until the value is under 10000.
        LD   R2,[FLTY]
        CMP  R2,#2
        BEQ  .lf
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        CALL ffromi             ; FARG is untouched by this
        SEC
        RET
.lf:    LD   R0,[X]
        ST   [FACC],R0
        INCW X
        LD   R0,[X]
        ST   [FACC+1],R0
        INCW X
        LD   R0,[X]
        ST   [FACC+2],R0
        INCW X
        LD   R0,[X]
        ST   [FACC+3],R0
        SEC                     ; a float pair
        RET
;
; `fstr` renders into FSBUF and answers a length, which is exactly the
; (pointer, count) pair `s_putsn` already takes -- so a float prints
; through the code a string prints through, and PRINT grows by a branch
; rather than by a printer.
; ---------------------------------------------------------------------
fprint: PUSHW Y                 ; fstr walks Y over its output
        CALL fstr
        POPW Y
        ST   [SLEN],R0
        LDW  X,#FSBUF
        MOV  R0,XL
        ST   [SACC],R0
        MOV  R0,XH
        ST   [SACC+1],R0
        RET

; FSTK, FSP, FLTY and FSDEEP are in sw/lowram.asm now, in the 38 bytes of
; page 0 the assembler used to hold. They were four frames of image data
; here while this was being written, which was a size compromise; the
; cleanup pass paid it off and got three more frames for nothing.
