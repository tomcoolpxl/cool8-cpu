; ---------------------------------------------------------------------
; fp.asm -- a 3-byte binary float, gated behind an address-based API.
;
; **This is a size experiment, not yet a feature.** The question it
; answers is the one docs/13-basic.md section 10 could only estimate:
; what does real floating point actually cost on a machine with 21 bytes
; free? Measure it standalone first, integrate second.
;
; ## Why three bytes, and why gated
;
; A float that can appear in an expression forces every value slot in
; the interpreter to widen -- the accumulator, the eval stack, variables,
; FOR, arrays, DATA -- and forces a float-to-int coercion at every
; graphics command. That was priced at ~1.5-2 KB and none of it is
; arithmetic. Gating the type behind `F...(addr, addr)` calls that only
; ever hand back an integer or a string removes all of it: nothing else
; in the language learns that floats exist.
;
; Gating also buys the format. Because floats never live in a variable,
; nothing forces the mantissa to a convenient width -- so it is 16 bits,
; which is exactly the width `mul16` and `udiv16` already work in. A
; 24-bit mantissa would need new wide multiply and divide; this one
; reuses what the interpreter already carries for `*` and `/`.
;
;   byte 0   exponent, excess-128. **0 means the value is zero.**
;   byte 1   bit 7 sign, bits 6-0 the top 7 fraction bits
;   byte 2   the low 8 fraction bits
;
;   value = (-1)^s x 1.f x 2^(e-128)
;
; 15 stored fraction bits plus the implied leading 1 is 16 significant
; bits, about 4.8 decimal digits, over a range of roughly 10^+-38.
;
; ## The internal form is four bytes, not three
;
; Packing costs a shift and a mask on every access, so arithmetic works
; on an unpacked accumulator instead: sign, exponent, and the significand
; with the implied 1 restored into bit 15. Only `fload` and `fstore`
; touch the packed form. That is the same trade BBC BASIC makes with its
; five-byte memory format and a wider internal one.
; ---------------------------------------------------------------------

; ## The register contract: these routines own X **and Y**
;
; `fcp4` and `fswap` take a destination in Y, `fload` sets it, `fstr`
; walks it and `fmul` does `MOVW Y,X`. Only `ffromi`, `ftoi` and
; `fstore` leave it alone. **A caller with a live pointer in Y must save
; it**, which sw/fpbas.asm does at every site.
;
; This was free while the package was a loadable library called from a
; driver that owned nothing. It stopped being free the moment BASIC
; called it, because Y is the interpreter's token pointer -- and the
; symptom was not a crash but `PRINT SQR(2)` working while
; `PRINT SQR(2) + 1` printed nothing, the `+ 1` having been lost with
; the program position.
;
; **No `.org` here.** This is included into the system image now
; ([D63]), so every address in it is relative and the includer decides
; where it lands -- the same rule interp.asm follows. `sim/test_fp.py`
; wraps it in one when it wants to weigh the package on its own.

; ---------------------------------------------------------------------
; The jump table, and it is the ABI.
;
; This package is meant to be loaded, not linked ([D62]), so callers
; cannot know where anything landed. **Every entry point is reached at a
; fixed offset from the base and nowhere else.** Entries are appended,
; never inserted or reordered, for the same reason toktab's are: a
; program saved against offset 21 must still find `fmul` there.
;
;   +0  fload    X -> FACC        +21 fmul    FACC *= FARG
;   +3  floadb   X -> FARG        +24 fdiv    FACC /= FARG, C on /0
;   +6  fstore   FACC -> X        +27 fstr    FACC -> text, len in R0
;   +9  ffromi   R0:R1 -> FACC    +30 fsqrt   C set if negative
;  +12  ftoi     FACC -> R0:R1    +33 fexp
;  +15  fadd     FACC += FARG     +36 flog    C set if not positive
;  +18  fsub     FACC -= FARG     +39 fpow    FACC ^ FARG
;
;  +42  fsin     radians          +54 fabs
;  +45  fcos                      +57 fneg
;  +48  ftan     C set at a pole  +60 fsgn
;  +51  fatan                     +63 fcmp    R0 = $FF, 0 or 1
; ---------------------------------------------------------------------
FPBASE: JMP  fload
        JMP  floadb
        JMP  fstore
        JMP  ffromi
        JMP  ftoi
        JMP  fadd
        JMP  fsub
        JMP  fmul
        JMP  fdiv
        JMP  fstr
        JMP  fsqrt
        JMP  fexp
        JMP  flog
        JMP  fpow
        JMP  fsin
        JMP  fcos
        JMP  ftan
        JMP  fatan
        JMP  fabs
        JMP  fneg
        JMP  fsgn
        JMP  fcmp

; The unpacked accumulators are FACC and FARG, declared with the rest of
; the workspace at the foot of this file: +0 sign (0 or $80), +1
; exponent, +2 significand low, +3 significand high with the implied 1.

BIAS    = 128

; ---------------------------------------------------------------------
; fload -- the packed float at X into FACC.
; ---------------------------------------------------------------------
; **The destination is a parameter, not a fixed cell.** The first
; version loaded FACC only and reached FARG by loading and swapping,
; which works for a caller assembling two fresh operands and is useless
; to `fstr`, which has to pull a constant into FARG while keeping the
; value it is printing.
fload:  LDW  Y,#FACC
        BRA  floadc
floadb: LDW  Y,#FARG
floadc: LD   R0,[X]             ; exponent; 0 is the zero encoding
        INCW X
        LD   R1,[X]             ; sign and the top fraction bits
        INCW X
        LD   R2,[X]
        MOV  R3,R1
        AND  R3,#$80
        ST   [Y+],R3            ; sign
        ST   [Y+],R0            ; exponent
        ST   [Y+],R2            ; significand low
        OR   R1,#$80            ; the implied 1 back into bit 15
        ST   [Y+],R1
        RET

; ---------------------------------------------------------------------
; fcmpa -- C set if FACC is at or above FARG. **Magnitudes only**: the
; one caller, fstr's scaling loop, has already taken the sign off.
; Exponent decides unless it ties, then the significand, high byte
; first -- which is just an unsigned compare of the three bytes that
; matter, in order.
; ---------------------------------------------------------------------
fcmpa:  LD   R0,[FACC+1]
        LD   R1,[FARG+1]
        CMP  R0,R1
        BNE  .out
        LD   R0,[FACC+3]
        LD   R1,[FARG+3]
        CMP  R0,R1
        BNE  .out
        LD   R0,[FACC+2]
        LD   R1,[FARG+2]
        CMP  R0,R1
.out:   RET

; ---------------------------------------------------------------------
; fstore -- FACC packed to X. A zero exponent stores three zero bytes so
; that a zero has one representation and `fload` cannot resurrect a
; stale sign from it.
; ---------------------------------------------------------------------
fstore: LD   R0,[FACC+1]
        ST   [X],R0
        INCW X
        AND  R0,R0
        BEQ  .z
        LD   R0,[FACC+3]
        AND  R0,#$7F            ; drop the implied 1, make room for sign
        LD   R1,[FACC]
        OR   R0,R1
        ST   [X],R0
        INCW X
        LD   R0,[FACC+2]
        ST   [X],R0
        RET
.z:     CLR  R0
        ST   [X],R0
        INCW X
        ST   [X],R0
        RET

; ---------------------------------------------------------------------
; fnorm -- shift FACC's significand up until bit 15 is set, paying one
; exponent count a bit. An exponent that reaches 0 on the way is an
; underflow and the answer is zero, which is also what a significand of
; zero arrives as.
; ---------------------------------------------------------------------
fnorm:  LD   R0,[FACC+3]
        LD   R1,[FACC+2]
        LD   R2,[FACC+1]
.lp:    AND  R0,R0
        BMI  .st
        AND  R2,R2
        BEQ  .z
        SHL  R1
        ROL  R0
        SUB  R2,#1
        BRA  .lp
.st:    ST   [FACC+3],R0
        ST   [FACC+2],R1
        ST   [FACC+1],R2
        RET
.z:     CLR  R0
        ST   [FACC+1],R0        ; exponent 0 is the zero encoding
        RET

; ---------------------------------------------------------------------
; ffromi -- the signed 16-bit value in R0 (low) : R1 (high) into FACC.
;
; The significand starts as the integer itself and the exponent as
; BIAS+15, which is what says "the binary point is above bit 15"; fnorm
; then slides it up and pays for each bit. An integer of zero falls out
; through fnorm's underflow arm without a special case.
; ---------------------------------------------------------------------
ffromi: CLR  R2
        ST   [FACC],R2          ; assume positive
        AND  R1,R1
        BPL  .p
        MOV  R2,#$80
        ST   [FACC],R2          ; negative: sign out, magnitude in
        ; Complement-and-increment, not a subtract from zero. The
        ; normative flag table says nothing about what CLR does to C, so
        ; a CLR between the SUB and the SBC is an assumption; XOR is
        ; documented to leave C alone.
        XOR  R0,#$FF
        XOR  R1,#$FF
        ADD  R0,#1
        MOV  R2,#0
        ADC  R1,R2
.p:     ST   [FACC+2],R0
        ST   [FACC+3],R1
        MOV  R2,#BIAS+15
        ST   [FACC+1],R2
        JMP  fnorm

; ---------------------------------------------------------------------
; ftoi -- FACC to a signed 16-bit integer in R0:R1, **flooring**, which
; is what INT does and what motion wants (docs/13-basic.md section 8).
;
; The significand is 1.f x 2^15 in its own right, so the integer part is
; it shifted right by (BIAS+15 - e). Past 16 the answer is zero; at or
; below 0 the value does not fit and is left saturated rather than
; wrapped, because a wrapped coordinate is a bug that looks like data.
; ---------------------------------------------------------------------
ftoi:   LD   R2,[FACC+1]
        AND  R2,R2
        BEQ  .zero
        MOV  R3,#BIAS+15
        SUB  R3,R2              ; how far right to slide it
        BCC  .big               ; e above BIAS+15: too large to fit
        CMP  R3,#16
        BCS  .small             ; slid off the bottom entirely
        LD   R0,[FACC+2]
        LD   R1,[FACC+3]
.lp:    AND  R3,R3
        BEQ  .sign
        SHR  R1
        ROR  R0
        SUB  R3,#1
        BRA  .lp
.sign:  LD   R2,[FACC]
        AND  R2,R2
        BPL  .done
        ; Negative. Negate the magnitude, then floor: any fraction that
        ; was shifted out means the true value sat below the integer we
        ; have, so one more down. Cheaper than testing the lost bits:
        ; re-widen and compare would cost more than the subtract.
        XOR  R0,#$FF
        XOR  R1,#$FF
        ADD  R0,#1
        MOV  R2,#0
        ADC  R1,R2
        CALL ffrac
        BEQ  .done
        SUB  R0,#1
        MOV  R2,#0
        SBC  R1,R2
.done:  RET
.zero:  CLR  R0
        CLR  R1
        RET
.small: LD   R2,[FACC]          ; |v| < 1: floor is 0, or -1 if negative
        AND  R2,R2
        BPL  .zero
        MOV  R0,#$FF
        MOV  R1,#$FF
        RET
.big:   MOV  R0,#$FF            ; saturate rather than wrap
        MOV  R1,#$7F
        RET

; ---------------------------------------------------------------------
; ffrac -- Z clear if FACC has a fractional part below the integer it
; was truncated to. Only ftoi's floor needs it, and only for negatives.
; ---------------------------------------------------------------------
ffrac:  PUSH R0
        PUSH R1
        LD   R2,[FACC+1]
        MOV  R3,#BIAS+15
        SUB  R3,R2
        LD   R0,[FACC+2]
        LD   R1,[FACC+3]
        CLR  R2
.lp:    AND  R3,R3
        BEQ  .out
        SHR  R1
        ROR  R0
        BCC  .nx
        MOV  R2,#1              ; a 1 fell off the bottom
.nx:    SUB  R3,#1
        BRA  .lp
        ; **The pops come before the test, not after.** `POP` sets Z, so
        ; testing first and restoring second hands the caller the flags
        ; of whatever was on the stack. That is what made ftoi floor an
        ; exact -1.0 down to -2.
.out:   POP  R1
        POP  R0
        AND  R2,R2
        RET

; ---------------------------------------------------------------------
; fadd -- FACC = FACC + FARG.
;
; Align to the larger exponent, then add or subtract magnitudes
; depending on whether the signs agree. The two are one routine because
; the alignment and the renormalise are the whole cost; the add itself
; is four instructions.
; ---------------------------------------------------------------------
fadd:   LD   R0,[FARG+1]
        AND  R0,R0
        BEQ  .ret               ; adding zero
        LD   R1,[FACC+1]
        AND  R1,R1
        BEQ  .takearg           ; zero plus x
        ; ---- order them so FACC holds the larger exponent
        CMP  R1,R0
        BCS  .ord
        CALL fswap
.ord:   LD   R0,[FACC+1]
        LD   R1,[FARG+1]
        SUB  R0,R1              ; the shift FARG needs
        CMP  R0,#17
        BCS  .ret               ; FARG vanishes under the alignment
        MOV  R3,R0
        LD   R0,[FARG+2]
        LD   R1,[FARG+3]
.al:    AND  R3,R3
        BEQ  .signs
        SHR  R1
        ROR  R0
        SUB  R3,#1
        BRA  .al
        ; ---- same sign is an add, opposite is a subtract
.signs: LD   R2,[FACC]
        LD   R3,[FARG]
        XOR  R2,R3
        BMI  .sub
        LD   R2,[FACC+2]
        ADD  R0,R2
        LD   R2,[FACC+3]
        ADC  R1,R2
        BCC  .st                ; no overflow out of the top
        ROR  R1                 ; carry back in, one place down
        ROR  R0
        LD   R2,[FACC+1]
        ADD  R2,#1
        ST   [FACC+1],R2
        BRA  .st
.sub:   LD   R2,[FACC+2]        ; FACC - aligned FARG, magnitudes
        LD   R3,[FACC+3]
        SUB  R2,R0
        MOV  R0,R2
        MOV  R2,R3
        LD   R3,[FACC+3]
        SBC  R3,R1
        MOV  R1,R3
        BCS  .st2               ; FACC was the larger magnitude
        XOR  R0,#$FF            ; it was not: negate and flip the sign
        XOR  R1,#$FF
        ADD  R0,#1
        MOV  R2,#0
        ADC  R1,R2
        LD   R2,[FACC]
        XOR  R2,#$80
        ST   [FACC],R2
.st2:   ST   [FACC+2],R0
        ST   [FACC+3],R1
        JMP  fnorm
.st:    ST   [FACC+2],R0
        ST   [FACC+3],R1
.ret:   RET
.takearg:
        CALL fswap
        RET

; ---------------------------------------------------------------------
; fsub -- FACC = FACC - FARG, by flipping the operand's sign. The flip
; is left in place: FARG is scratch and no caller reads it back.
; ---------------------------------------------------------------------
fsub:   LD   R0,[FARG]
        XOR  R0,#$80
        ST   [FARG],R0
        JMP  fadd

; ---------------------------------------------------------------------
; fswap -- FACC and FARG exchanged, four bytes at a time.
; ---------------------------------------------------------------------
fswap:  MOV  R3,#4
        LDW  X,#FACC
        LDW  Y,#FARG
.lp:    LD   R0,[X]
        LD   R1,[Y]
        ST   [X],R1
        ST   [Y],R0
        INCW X
        INCW Y
        SUB  R3,#1
        BNE  .lp
        RET

; ---------------------------------------------------------------------
; fmul -- FACC = FACC x FARG.
;
; Exponents add and the bias is paid once. The significands are two
; 16-bit values with bit 15 set in each, so the product has bit 31 or
; bit 30 set and the top 16 bits are the answer -- one renormalising
; shift at most, no loop. Four 8x8 MULs, which is what the hardware
; multiplier is for.
; ---------------------------------------------------------------------
fmul:   LD   R0,[FACC+1]
        AND  R0,R0
        BEQ  .zero
        LD   R1,[FARG+1]
        AND  R1,R1
        BEQ  .zero
        ; ---- sign is the exclusive or
        LD   R2,[FACC]
        LD   R3,[FARG]
        XOR  R2,R3
        ST   [FACC],R2
        ; ---- Exponent: one bias removed, and one count back because
        ; ---- the product of two 16-bit significands is taken from the
        ; ---- top 16 bits of 32, which divides by 2^16 where the format
        ; ---- wants 2^15.
        ADD  R0,R1
        SUB  R0,#BIAS-1
        ST   [FACC+1],R0
        ; ---- ah*bh is the only partial product that lands whole in the
        ; ---- result; the two cross terms contribute their high bytes
        ; ---- and al*bl only its carry, which is dropped. Truncation,
        ; ---- not rounding: a rounding step costs bytes and this format
        ; ---- has none to spare.
        LD   R0,[FACC+3]
        LD   R1,[FARG+3]
        MUL  R0,R1              ; ah*bh -> X
        MOVW Y,X
        LD   R0,[FACC+3]
        LD   R1,[FARG+2]
        MUL  R0,R1              ; ah*bl
        MOV  R2,XH
        CLR  R3
        MOV  R0,YL
        ADD  R0,R2
        MOV  YL,R0
        MOV  R0,YH
        ADC  R0,R3
        MOV  YH,R0
        LD   R0,[FACC+2]
        LD   R1,[FARG+3]
        MUL  R0,R1              ; al*bh
        MOV  R2,XH
        CLR  R3
        MOV  R0,YL
        ADD  R0,R2
        MOV  YL,R0
        MOV  R0,YH
        ADC  R0,R3
        MOV  YH,R0
        MOV  R0,YL
        ST   [FACC+2],R0
        MOV  R0,YH
        ST   [FACC+3],R0
        JMP  fnorm              ; at most one shift, but fnorm is here
.zero:  CLR  R0
        ST   [FACC+1],R0
        RET

; ---------------------------------------------------------------------
; fdiv -- FACC = FACC / FARG. C set on return means division by zero.
;
; Restoring division, sixteen trial subtractions, the same shape as the
; interpreter's udiv16. The dividend is pre-shifted down one place when
; it is the larger, so the quotient always lands with bit 15 set and the
; normalise afterwards has nothing to do in the common case.
; ---------------------------------------------------------------------
fdiv:   LD   R0,[FARG+1]
        AND  R0,R0
        BEQ  .dz
        LD   R1,[FACC+1]
        AND  R1,R1
        BEQ  .zok               ; zero over anything is zero
        LD   R2,[FACC]
        LD   R3,[FARG]
        XOR  R2,R3
        ST   [FACC],R2
        MOV  R2,R1
        SUB  R2,R0
        ADD  R2,#BIAS
        ST   [FACC+1],R2
        ; ---- **Always halve the dividend, and never touch the
        ; ---- exponent for it.** fdiv16 returns floor(D x 2^16 / SB).
        ; ---- With D = SA/2 that is 2^15 x SA/SB, which is exactly the
        ; ---- significand the format wants, for every pair -- because
        ; ---- both operands are normalised, so SA/SB is in (0.5, 2) and
        ; ---- the result lands in (2^14, 2^16). fnorm takes up the one
        ; ---- shift needed when SA < SB.
        ; ----
        ; ---- The first version compared the two and shifted only when
        ; ---- the dividend was larger, paying an exponent count for it.
        ; ---- That is the textbook form and it is wrong here twice
        ; ---- over: the paid count made every quotient double, and the
        ; ---- unshifted branch overflowed 16 bits. Unconditional is
        ; ---- correct and twenty bytes shorter.
        LD   R0,[FACC+3]
        LD   R1,[FACC+2]
        SHR  R0
        ROR  R1
        ST   [FACC+3],R0
        ST   [FACC+2],R1
        CALL fdiv16
        ; **CLC, and it is not decoration.** The header promises "C set
        ; on return means division by zero", but the success path used
        ; to end `JMP fnorm` and inherit whatever carry the normalise
        ; left -- so the contract was only half true, and the first
        ; caller to believe it (fopdiv, reporting ?DIVISION BY ZERO)
        ; failed on FLT(1)/FLT(3). A documented flag has to be set on
        ; every path or it is not documented.
        CALL fnorm
        CLC
        RET
.zok:   CLC
        RET
.dz:    SEC
        RET

; ---------------------------------------------------------------------
; fdiv16 -- FACC significand / FARG significand, 16 quotient bits, the
; remainder discarded. The dividend doubles as the quotient the way
; udiv16's does, which is what keeps this to four live bytes.
; ---------------------------------------------------------------------
; **The counter lives in X**, as udiv16's does, because all four
; registers are spoken for and `DECW` sets Z from the 16-bit result. A
; spilled counter cannot work here: reloading it means a `POP` to get
; the register back, and **`POP` sets Z**, so the branch would test the
; restored value instead of the count. That bug ran the loop until a
; quotient byte happened to reach zero.
; **The remainder starts as the whole dividend and zeros shift in.**
; udiv16's loop feeds the dividend in a bit at a time, which computes
; the integer quotient D/SB; a float needs the fractional one,
; D x 2^16 / SB. The first version here was udiv16's shape and returned
; a quotient of 1 for 1.0/1.0 -- right answer to the wrong question.
;
; Shifting the remainder up can carry out of bit 15, and that 17th bit
; means the trial subtraction fits whatever the 16-bit compare says. It
; is kept in FC17 across the subtract because all four registers are
; live and PUSH and MOV both leave C alone, so ROL can still catch it.
fdiv16: LD   R2,[FACC+2]        ; the remainder *is* the dividend
        LD   R3,[FACC+3]
        CLR  R0                 ; the quotient builds here
        CLR  R1
        LDW  X,#16
.lp:    SHL  R0                 ; quotient up one
        ROL  R1
        SHL  R2                 ; remainder up one, bit 16 out into C
        ROL  R3
        PUSH R1
        PUSH R0
        MOV  R0,#0
        ROL  R0                 ; bit 16 caught before anything sets C
        ST   [FC17],R0
        LD   R0,[FARG+2]
        LD   R1,[FARG+3]
        SUB  R2,R0
        SBC  R3,R1
        BCS  .fits
        LD   R1,[FC17]
        AND  R1,R1
        BNE  .fits              ; bit 16 was set, so it fitted after all
        LD   R1,[FARG+3]
        ADD  R2,R0              ; it truly borrowed: put it back
        ADC  R3,R1
        POP  R0
        POP  R1
        BRA  .nx
.fits:  POP  R0
        POP  R1
        ADD  R0,#1              ; the bit that says it fitted
.nx:    DECW X
        BNE  .lp
        ST   [FACC+2],R0
        ST   [FACC+3],R1
        CLC
        RET

; ---------------------------------------------------------------------
; fstr -- FACC as decimal text at FSBUF, the length in R0.
;
; Scale into [1000, 10000) by multiplying or dividing by ten, counting
; the decimal exponent as it goes; that leaves exactly four significant
; digits, which is what sixteen significand bits are worth (4.8, and the
; fifth would be a lie). Then place the point.
;
; Scaling by repeated multiply is the slow way and it is the small one:
; a table of powers of ten would be three bytes an entry plus the code
; to pick from it, against one constant and a loop. Nothing here is on
; a hot path -- a program printing floats is a program waiting for a
; human to read them.
; ---------------------------------------------------------------------
fstr:   CLR  R0
        ST   [FNEG],R0
        LD   R0,[FACC+1]
        AND  R0,R0
        BNE  .nz
        LDW  Y,#FSBUF           ; zero prints as one character
        MOV  R0,#$30
        ST   [Y+],R0
        MOV  R0,#1
        RET
.nz:    LD   R0,[FACC]
        AND  R0,R0
        BPL  .pos
        MOV  R0,#1
        ST   [FNEG],R0
        CLR  R0
        ST   [FACC],R0          ; scale the magnitude, sign goes on later
.pos:   CLR  R0
        ST   [FDEXP],R0
.up:    LDW  X,#K10000
        CALL floadb
        CALL fcmpa
        BCC  .dn
        LDW  X,#K10
        CALL floadb
        CALL fdiv
        LD   R0,[FDEXP]
        ADD  R0,#1
        ST   [FDEXP],R0
        BRA  .up
.dn:    LDW  X,#K1000
        CALL floadb
        CALL fcmpa
        BCS  .got
        LDW  X,#K10
        CALL floadb
        CALL fmul
        LD   R0,[FDEXP]
        SUB  R0,#1
        ST   [FDEXP],R0
        BRA  .dn
.got:   CALL ftoi
        ST   [FNUM],R0
        ST   [FNUM+1],R1
        ; ---- four digits, by taking each power of ten away as often as
        ; ---- it goes. Slow and short; see the head of this routine.
        LDW  Y,#P10
        LDW  X,#FDIG
        MOV  R0,#4
        ST   [FDCNT],R0
.dg:    LD   R2,[Y]
        INCW Y
        LD   R3,[Y]
        INCW Y
        CLR  R1
.s2:    LD   R0,[FNUM]
        SUB  R0,R2
        PUSH R0                 ; PUSH leaves C, so the SBC still sees it
        LD   R0,[FNUM+1]
        SBC  R0,R3
        BCC  .s3
        ST   [FNUM+1],R0
        POP  R0
        ST   [FNUM],R0
        ADD  R1,#1
        BRA  .s2
.s3:    POP  R0                 ; the subtraction that borrowed, discarded
        MOV  R0,R1
        ADD  R0,#$30
        ST   [X],R0
        INCW X
        LD   R0,[FDCNT]
        SUB  R0,#1
        ST   [FDCNT],R0
        BNE  .dg
        ; ---- place the point. P is the count of digits before it.
        LD   R0,[FDEXP]
        ADD  R0,#4
        ST   [FP],R0
        LDW  Y,#FSBUF
        LD   R0,[FNEG]
        AND  R0,R0
        BEQ  .np
        MOV  R0,#$2D
        ST   [Y+],R0
.np:    LD   R0,[FP]
        AND  R0,R0
        BMI  .lead
        BEQ  .lead
        CMP  R0,#7
        BCS  .enot              ; too many integer digits to write out
        ; ---- P digits, then a point and the rest
        LDW  X,#FDIG
        LD   R2,[FP]
        CLR  R3
.i1:    CMP  R3,#4
        BCS  .i2
        LD   R0,[X]
        INCW X
        BRA  .i3
.i2:    MOV  R0,#$30            ; ran past the four we have: pad
.i3:    ST   [Y+],R0
        ADD  R3,#1
        CMP  R3,R2
        BCC  .i1
        CMP  R3,#4              ; nothing left over: no point, no trim.
        BCC  .i5                ; .fin is past a branch's reach, so the
        JMP  .fin               ; test inverts and a JMP carries it
.i5:    MOV  R0,#$2E
        ST   [Y+],R0
.i4:    LD   R0,[X]
        INCW X
        ST   [Y+],R0
        ADD  R3,#1
        CMP  R3,#4
        BCC  .i4
        CALL ftrim
        BRA  .fin
        ; ---- 0.000ddd, for P at or below zero
        ; P is signed and the compare is not, so zero has to be let
        ; through on its own: 0 reads as below $FE and would take the
        ; exponent form, which printed 0.5 as 5E-01.
.lead:  LD   R0,[FP]
        AND  R0,R0
        BEQ  .lok
        CMP  R0,#$FE            ; -2 is as far as this form goes
        BCC  .enot
.lok:   MOV  R0,#$30
        ST   [Y+],R0
        MOV  R0,#$2E
        ST   [Y+],R0
        LD   R2,[FP]
.z1:    AND  R2,R2
        BEQ  .z2
        MOV  R0,#$30
        ST   [Y+],R0
        ADD  R2,#1
        BRA  .z1
.z2:    CALL fdigs
        CALL ftrim
        BRA  .fin
        ; ---- d.dddE+nn
.enot:  LDW  X,#FDIG
        LD   R0,[X]
        INCW X
        ST   [Y+],R0
        MOV  R0,#$2E
        ST   [Y+],R0
        MOV  R3,#1
.e1:    LD   R0,[X]
        INCW X
        ST   [Y+],R0
        ADD  R3,#1
        CMP  R3,#4
        BCC  .e1
        CALL ftrim
        MOV  R0,#$45            ; 'E'
        ST   [Y+],R0
        LD   R0,[FP]
        SUB  R0,#1              ; the scientific exponent
        AND  R0,R0
        BMI  .em
        MOV  R1,#$2B
        BRA  .es
.em:    XOR  R0,#$FF
        ADD  R0,#1
        MOV  R1,#$2D
.es:    ST   [Y+],R1
        CLR  R1
.e2:    CMP  R0,#10
        BCC  .e3
        SUB  R0,#10
        ADD  R1,#1
        BRA  .e2
.e3:    ADD  R1,#$30
        ST   [Y+],R1
        ADD  R0,#$30
        ST   [Y+],R0
        ; The length, as the low bytes' difference. FSBUF is a label now
        ; rather than a page-0 constant, so it is no longer a byte-sized
        ; immediate -- and the difference is right modulo 256 whatever
        ; page the buffer straddles, because the string can never reach
        ; that long.
.fin:   LDW  X,#FSBUF
        MOV  R0,YL
        MOV  R1,XL
        SUB  R0,R1
        RET

; ---- fdigs: all four digits out, for the callers that want them whole
fdigs:  LDW  X,#FDIG
        CLR  R3
.d1:    LD   R0,[X]
        INCW X
        ST   [Y+],R0
        ADD  R3,#1
        CMP  R3,#4
        BCC  .d1
        RET

; ---- ftrim: back Y over trailing zeros, and over the point if the
; ---- whole fraction went. Only ever called where a point was written,
; ---- so it can never eat into an integer part.
ftrim:  DECW Y
        LD   R0,[Y]
        CMP  R0,#$30
        BEQ  ftrim
        CMP  R0,#$2E
        BEQ  .d
        INCW Y
.d:     RET

; =====================================================================
; The transcendentals.
;
; These exist because the package is loadable rather than resident
; ([D62]) -- against the 21 free bytes in the system image they were
; unthinkable, and in a file the user loads when a school assignment
; wants an integral plotted they cost nothing anybody else pays.
;
; All four are built on the four operations above and a Horner loop, so
; none of them carries its own arithmetic. Slow is the right trade here
; twice over: nothing calls these in a frame loop, and a game that wants
; a sine wants a table.
; =====================================================================

; ---- fcp4: four unpacked bytes from X to Y. The whole reason the
; ---- transcendentals fit in this little code is that everything moves
; ---- through one copy rather than a routine per direction.
fcp4:   MOV  R3,#4
.l:     LD   R0,[X]
        INCW X
        ST   [Y+],R0
        SUB  R3,#1
        BNE  .l
        RET

; ---- fmac: FACC = FACC * FT0 + [X], one Horner step. X is a packed
; ---- constant. FT0 is the running variable the polynomial is in --
; ---- r for exp, z^2 for log -- so a step costs six bytes at the call.
fmac:   PUSHW X
        LDW  X,#FT0
        LDW  Y,#FARG
        CALL fcp4
        CALL fmul
        POPW X
        CALL floadb
        JMP  fadd

; ---------------------------------------------------------------------
; fsqrt -- Newton, y <- (y + v/y)/2, four times. C set if the argument
; is negative.
;
; The first guess is the exponent halved about the bias, which is never
; worse than a factor of root two out; Newton doubles the correct bits
; each pass, so four is comfortably past the sixteen this format holds.
; Halving is a decrement of the exponent, not a divide.
; ---------------------------------------------------------------------
fsqrt:  LD   R0,[FACC+1]
        AND  R0,R0
        BEQ  .ok                ; sqrt(0) is 0
        LD   R0,[FACC]
        AND  R0,R0
        BMI  .neg
        LDW  X,#FACC
        LDW  Y,#FT0
        CALL fcp4               ; FT0 = v
        LD   R0,[FACC+1]
        SUB  R0,#BIAS
        SAR  R0                 ; signed halve: the guess
        ADD  R0,#BIAS
        ST   [FACC+1],R0
        MOV  R0,#4
        ST   [FCNT2],R0
.it:    LDW  X,#FACC
        LDW  Y,#FT1
        CALL fcp4               ; FT1 = y
        LDW  X,#FT1
        LDW  Y,#FARG
        CALL fcp4
        LDW  X,#FT0
        LDW  Y,#FACC
        CALL fcp4
        CALL fdiv               ; v / y
        LDW  X,#FT1
        LDW  Y,#FARG
        CALL fcp4
        CALL fadd               ; y + v/y
        LD   R0,[FACC+1]
        AND  R0,R0
        BEQ  .nx
        SUB  R0,#1              ; halved
        ST   [FACC+1],R0
.nx:    LD   R0,[FCNT2]
        SUB  R0,#1
        ST   [FCNT2],R0
        BNE  .it
.ok:    CLC
        RET
.neg:   SEC
        RET

; ---------------------------------------------------------------------
; fexp -- e^x, by k = round(x/ln2) and a Taylor series on the remainder.
;
; Range reduction is what makes six terms enough: r never leaves about
; +-ln2, where r^6/720 is below what sixteen significand bits can see.
; Scaling by 2^k afterwards is an add to the exponent byte, which is the
; one place a binary float is cheaper than a decimal one.
; ---------------------------------------------------------------------
fexp:   LDW  X,#FACC
        LDW  Y,#FT2
        CALL fcp4               ; FT2 = x
        LDW  X,#KILN2
        CALL floadb
        CALL fmul
        CALL ftoi               ; k
        ST   [FK],R0
        CALL ffromi
        LDW  X,#KLN2
        CALL floadb
        CALL fmul               ; k*ln2
        LDW  X,#FACC
        LDW  Y,#FARG
        CALL fcp4
        LDW  X,#FT2
        LDW  Y,#FACC
        CALL fcp4
        CALL fsub               ; r = x - k*ln2
        LDW  X,#FACC
        LDW  Y,#FT0
        CALL fcp4               ; FT0 = r, the Horner variable
        LDW  X,#K1_120
        CALL fload
        LDW  X,#K1_24
        CALL fmac
        LDW  X,#K1_6
        CALL fmac
        LDW  X,#KHALF
        CALL fmac
        LDW  X,#KONE
        CALL fmac
        LDW  X,#KONE
        CALL fmac
        LD   R0,[FACC+1]
        AND  R0,R0
        BEQ  .z                 ; underflowed to zero: leave it there
        LD   R1,[FK]
        ADD  R0,R1
        ST   [FACC+1],R0
.z:     CLC
        RET

; ---------------------------------------------------------------------
; flog -- natural log. C set unless the argument is strictly positive.
;
; ln(m x 2^n) = ln(m) + n ln2, and for m in [1,2) the series in
; z = (m-1)/(m+1) converges on z <= 1/3, so four terms of
; 2z(1 + z^2/3 + z^4/5 + z^6/7) is already past this format's precision.
; Splitting the exponent off first is free -- it is a byte.
; ---------------------------------------------------------------------
        ; The refusals sit at the far end of the routine, past a
        ; conditional branch's reach, so both tests invert and let a JMP
        ; carry the distance.
flog:   LD   R0,[FACC+1]
        AND  R0,R0
        BNE  .p1
        JMP  .err
.p1:    LD   R0,[FACC]
        AND  R0,R0
        BPL  .p0
        JMP  .err
.p0:    LD   R0,[FACC+1]
        SUB  R0,#BIAS
        ST   [FN],R0            ; n, signed
        MOV  R0,#BIAS
        ST   [FACC+1],R0        ; what is left is m in [1,2)
        LDW  X,#FACC
        LDW  Y,#FT2
        CALL fcp4               ; FT2 = m
        LDW  X,#KONE
        CALL floadb
        CALL fsub
        LDW  X,#FACC
        LDW  Y,#FT1
        CALL fcp4               ; FT1 = m-1
        LDW  X,#FT2
        LDW  Y,#FACC
        CALL fcp4
        LDW  X,#KONE
        CALL floadb
        CALL fadd               ; m+1
        LDW  X,#FACC
        LDW  Y,#FARG
        CALL fcp4
        LDW  X,#FT1
        LDW  Y,#FACC
        CALL fcp4
        CALL fdiv               ; z
        LDW  X,#FACC
        LDW  Y,#FT1
        CALL fcp4               ; FT1 = z
        LDW  X,#FACC
        LDW  Y,#FARG
        CALL fcp4
        CALL fmul               ; z^2
        LDW  X,#FACC
        LDW  Y,#FT0
        CALL fcp4               ; FT0 = z^2
        LDW  X,#K1_7
        CALL fload
        LDW  X,#K1_5
        CALL fmac
        LDW  X,#K1_3
        CALL fmac
        LDW  X,#KONE
        CALL fmac
        LDW  X,#FT1
        LDW  Y,#FARG
        CALL fcp4
        CALL fmul               ; z * p
        LD   R0,[FACC+1]
        AND  R0,R0
        BEQ  .nn
        ADD  R0,#1              ; doubled
        ST   [FACC+1],R0
.nn:    LDW  X,#FACC
        LDW  Y,#FT1
        CALL fcp4               ; FT1 = ln(m)
        LD   R0,[FN]
        CLR  R1
        AND  R0,R0
        BPL  .p2
        MOV  R1,#$FF            ; sign extend n to sixteen bits
.p2:    CALL ffromi
        LDW  X,#KLN2
        CALL floadb
        CALL fmul               ; n ln2
        LDW  X,#FT1
        LDW  Y,#FARG
        CALL fcp4
        CALL fadd
        CLC
        RET
.err:   SEC
        RET

; ---------------------------------------------------------------------
; fpow -- FACC ^ FARG, as exp(y ln x). Twenty bytes once log and exp
; exist, which is the argument for building them in that order.
; ---------------------------------------------------------------------
fpow:   LDW  X,#FARG
        LDW  Y,#FT3
        CALL fcp4               ; FT3 = y, before flog takes FACC
        CALL flog
        BCS  .e
        LDW  X,#FT3
        LDW  Y,#FARG
        CALL fcp4
        CALL fmul
        JMP  fexp
.e:     RET

; ---------------------------------------------------------------------
; fabs, fneg, fsgn -- the cheap ones, because the sign is its own byte.
; A float package without these makes callers reach into the
; representation, and then the representation can never change.
; ---------------------------------------------------------------------
fabs:   CLR  R0
        ST   [FACC],R0
        RET

fneg:   LD   R0,[FACC+1]
        AND  R0,R0
        BEQ  .z                 ; zero has one representation; keep it
        LD   R0,[FACC]
        XOR  R0,#$80
        ST   [FACC],R0
.z:     RET

fsgn:   LD   R0,[FACC+1]
        AND  R0,R0
        BEQ  .z
        LD   R0,[FACC]
        PUSH R0
        LDW  X,#KONE
        CALL fload
        POP  R0
        ST   [FACC],R0
.z:     RET

; ---------------------------------------------------------------------
; fcmp -- R0 is $FF, 0 or 1 as FACC is below, equal to or above FARG.
;
; **A float library without a comparison is unusable**, and a caller
; cannot build one out of fsub without knowing the format. Signs decide
; first; when both are negative the magnitude order reverses, which is
; the whole of the difference from fcmpa.
; ---------------------------------------------------------------------
fcmp:   LD   R0,[FACC+1]
        LD   R1,[FARG+1]
        AND  R0,R0
        BNE  .an
        AND  R1,R1
        BEQ  .eq                ; both zero
.an:    LD   R2,[FACC]
        LD   R3,[FARG]
        LD   R0,[FACC+1]
        AND  R0,R0
        BNE  .a2
        CLR  R2                 ; a zero is positive, whatever its byte
.a2:    LD   R0,[FARG+1]
        AND  R0,R0
        BNE  .a3
        CLR  R3
.a3:    MOV  R0,R2
        XOR  R0,R3
        BPL  .same              ; signs agree: magnitudes decide
        AND  R2,R2
        BMI  .lo                ; FACC negative, FARG not
        BRA  .hi
.same:  CALL fcmpa
        BCC  .lo2
        BEQ  .eq                ; fcmpa's last CMP left Z on equality
        AND  R2,R2
        BMI  .lo
        BRA  .hi
.lo2:   AND  R2,R2
        BMI  .hi                ; both negative: smaller magnitude is more
.lo:    MOV  R0,#$FF
        RET
.hi:    MOV  R0,#1
        RET
.eq:    CLR  R0
        RET

; ---------------------------------------------------------------------
; fsin -- range reduce to a quadrant, then one of two short series.
;
; n = round(x . 2/pi) and r = x - n.(pi/2) leaves |r| <= pi/4, which is
; what makes four terms enough; the quadrant in n's low two bits then
; picks sine or cosine and whether to flip the sign. Reducing to a
; *quadrant* rather than to 2pi is what keeps the series short -- the
; alternative is more terms, and terms cost more than this arithmetic.
;
; **Accuracy dies for large arguments** and that is inherent: r is the
; difference of two close numbers, so at x ~ 10^4 there is little left
; of sixteen significand bits. Every small float package has this and
; the honest fix is not to call it with huge angles.
; ---------------------------------------------------------------------
fsin:   LDW  X,#FACC
        LDW  Y,#FT3
        CALL fcp4               ; FT3 = x
        LDW  X,#KIPI2
        CALL floadb
        CALL fmul
        LDW  X,#KHALF
        CALL floadb
        CALL fadd               ; x.2/pi + 1/2, so ftoi's floor rounds
        CALL ftoi
        ; **Mask into R2, not R0.** The quadrant is n's low two bits but
        ; ffromi still needs the whole of n, and masking in place threw
        ; the rest away -- invisible while |n| < 4, wrong the moment the
        ; angle passed 2pi or went negative.
        MOV  R2,R0
        AND  R2,#3              ; correct for negative n too
        ST   [FQ],R2
        CALL ffromi             ; back as a float, n
        LDW  X,#KPI2
        CALL floadb
        CALL fmul               ; n.(pi/2)
        LDW  X,#FACC
        LDW  Y,#FARG
        CALL fcp4
        LDW  X,#FT3
        LDW  Y,#FACC
        CALL fcp4
        CALL fsub               ; r
        LDW  X,#FACC
        LDW  Y,#FT1
        CALL fcp4               ; FT1 = r
        LDW  X,#FACC
        LDW  Y,#FARG
        CALL fcp4
        CALL fmul               ; r^2
        LDW  X,#FACC
        LDW  Y,#FT0
        CALL fcp4               ; FT0 = r^2, the Horner variable
        LD   R0,[FQ]
        AND  R0,#1
        BNE  .cosq
        ; ---- sin(r) = r.(1 - r^2/6 + r^4/120 - r^6/5040)
        LDW  X,#KN1_5040
        CALL fload
        LDW  X,#K1_120
        CALL fmac
        LDW  X,#KN1_6
        CALL fmac
        LDW  X,#KONE
        CALL fmac
        LDW  X,#FT1
        LDW  Y,#FARG
        CALL fcp4
        CALL fmul               ; times r
        BRA  .sgn
        ; ---- cos(r) = 1 - r^2/2 + r^4/24 - r^6/720
.cosq:  LDW  X,#KN1_720
        CALL fload
        LDW  X,#K1_24
        CALL fmac
        LDW  X,#KNHALF
        CALL fmac
        LDW  X,#KONE
        CALL fmac
.sgn:   LD   R0,[FQ]
        AND  R0,#2
        BEQ  .out
        JMP  fneg               ; quadrants 2 and 3 are the reflection
.out:   RET

; ---------------------------------------------------------------------
; fcos -- sin(x + pi/2). Fourteen bytes against a second series, and
; the quadrant machinery is already there to absorb the shift.
; ---------------------------------------------------------------------
fcos:   LDW  X,#KPI2
        CALL floadb
        CALL fadd
        JMP  fsin

; ---------------------------------------------------------------------
; ftan -- sin/cos. No separate series: tan's own converges badly near
; pi/2 and the division reports the pole through fdiv's carry.
; ---------------------------------------------------------------------
ftan:   LDW  X,#FACC
        LDW  Y,#FT4
        CALL fcp4
        CALL fsin
        LDW  X,#FACC
        LDW  Y,#FT5
        CALL fcp4               ; FT5 = sin x
        LDW  X,#FT4
        LDW  Y,#FACC
        CALL fcp4
        CALL fcos
        LDW  X,#FACC
        LDW  Y,#FARG
        CALL fcp4
        LDW  X,#FT5
        LDW  Y,#FACC
        CALL fcp4
        JMP  fdiv

; ---------------------------------------------------------------------
; fatan -- arctangent, in radians, over the whole line.
;
; Two reductions, because one is not enough. |x| > 1 folds through
; atan(x) = pi/2 - atan(1/x); what is left still reaches 1, where the
; series crawls, so anything above tan(pi/8) folds again through
; atan(x) = pi/4 + atan((x-1)/(x+1)). After both, |u| <= 0.4142 and five
; terms clear this format.
; ---------------------------------------------------------------------
fatan:  LD   R0,[FACC+1]
        AND  R0,R0
        BNE  .nz
        RET                     ; atan(0) = 0
.nz:    LD   R0,[FACC]
        ST   [FASGN],R0         ; work positive, put the sign back after
        CLR  R0
        ST   [FACC],R0
        CLR  R0
        ST   [FAINV],R0
        ST   [FAOCT],R0
        LDW  X,#KONE
        CALL floadb
        CALL fcmp
        AND  R0,R0
        BMI  .oct               ; |x| <= 1 already
        MOV  R0,#1
        ST   [FAINV],R0
        LDW  X,#FACC
        LDW  Y,#FARG
        CALL fcp4
        LDW  X,#KONE
        CALL fload
        CALL fdiv               ; 1/x
.oct:   LDW  X,#KTP8
        CALL floadb
        CALL fcmp
        AND  R0,R0
        BMI  .ser
        MOV  R0,#1
        ST   [FAOCT],R0
        LDW  X,#FACC
        LDW  Y,#FT3
        CALL fcp4
        LDW  X,#KONE
        CALL floadb
        CALL fsub               ; x-1
        LDW  X,#FACC
        LDW  Y,#FT2
        CALL fcp4
        LDW  X,#FT3
        LDW  Y,#FACC
        CALL fcp4
        LDW  X,#KONE
        CALL floadb
        CALL fadd               ; x+1
        LDW  X,#FACC
        LDW  Y,#FARG
        CALL fcp4
        LDW  X,#FT2
        LDW  Y,#FACC
        CALL fcp4
        CALL fdiv               ; u = (x-1)/(x+1)
.ser:   LDW  X,#FACC
        LDW  Y,#FT1
        CALL fcp4               ; FT1 = u
        LDW  X,#FACC
        LDW  Y,#FARG
        CALL fcp4
        CALL fmul
        LDW  X,#FACC
        LDW  Y,#FT0
        CALL fcp4               ; FT0 = u^2
        LDW  X,#KN1_11
        CALL fload
        LDW  X,#K1_9
        CALL fmac
        LDW  X,#KN1_7
        CALL fmac
        LDW  X,#K1_5
        CALL fmac
        LDW  X,#KN1_3
        CALL fmac
        LDW  X,#KONE
        CALL fmac
        LDW  X,#FT1
        LDW  Y,#FARG
        CALL fcp4
        CALL fmul               ; u . p
        LD   R0,[FAOCT]
        AND  R0,R0
        BEQ  .ni
        LDW  X,#KPI4
        CALL floadb
        CALL fadd
.ni:    LD   R0,[FAINV]
        AND  R0,R0
        BEQ  .fs
        CALL fneg
        LDW  X,#KPI2
        CALL floadb
        CALL fadd               ; pi/2 - atan(1/x)
.fs:    LD   R0,[FASGN]
        AND  R0,R0
        BPL  .done
        JMP  fneg
.done:  RET

; ---------------------------------------------------------------------
; The workspace, and why it is here rather than in page 0.
;
; **Page 0 is fully allocated** -- sw/lowram.asm hands out every byte of it:
; FSVARS to $00A1, FORSTK to $00D9, the assembler to the end. The first
; version of this package put FACC at $0090 and its temporaries at
; $00C0, which is the filesystem's workspace, the **FOR stack** and the
; assembler's scratch. An integral plot is a FOR loop calling these
; routines, so it would have corrupted itself on the first iteration.
;
; There was never a reason to want page 0. [D6] gives COOL8 no zero-page
; addressing mode, so $0040 costs exactly what $9040 costs; reaching for
; it was 6502 habit and nothing else. Living inside the package means
; the workspace relocates with the code, which is what a loadable
; library needs anyway -- one base address and no second thing to place.
; ---------------------------------------------------------------------
FACC:   .byte 0,0,0,0           ; sign, exponent, significand low, high
FARG:   .byte 0,0,0,0
FT0:    .byte 0,0,0,0           ; the Horner variable
FT1:    .byte 0,0,0,0
FT2:    .byte 0,0,0,0
FT3:    .byte 0,0,0,0
FT4:    .byte 0,0,0,0
FT5:    .byte 0,0,0,0
FC17:   .byte 0                 ; the divide's seventeenth bit
FDEXP:  .byte 0
FNUM:   .byte 0,0
FDIG:   .byte 0,0,0,0
FNEG:   .byte 0
FP:     .byte 0
FDCNT:  .byte 0
FCNT2:  .byte 0
FK:     .byte 0
FN:     .byte 0
FQ:     .byte 0
FASGN:  .byte 0
FAINV:  .byte 0
FAOCT:  .byte 0
FSBUF:  .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0

KONE:   .byte 128,$00,$00       ; 1.0
KHALF:  .byte 127,$00,$00       ; 0.5
KLN2:   .byte 127,$31,$72       ; ln 2
KILN2:  .byte 128,$38,$AA       ; 1/ln 2
K1_6:   .byte 125,$2A,$AA
K1_24:  .byte 123,$2A,$AA
K1_120: .byte 121,$08,$88
K1_3:   .byte 126,$2A,$AA
K1_5:   .byte 125,$4C,$CC
K1_7:   .byte 125,$12,$49
K1_9:   .byte 124,$63,$8E
; **The three share a mantissa by construction**, because halving a
; float here is the exponent alone: pi, pi/2 and pi/4 are $49,$0F at
; 129, 128 and 127. If one is ever re-derived the other two move with
; it, and a copy that disagrees is a bug rather than a rounding choice.
KPI:    .byte 129,$49,$0F       ; pi, for BASIC's PI
KPI2:   .byte 128,$49,$0F       ; pi/2
KIPI2:  .byte 127,$22,$F9       ; 2/pi
KPI4:   .byte 127,$49,$0F       ; pi/4
KTP8:   .byte 126,$54,$13       ; tan(pi/8), the second fold's threshold
KNHALF: .byte 127,$80,$00       ; -1/2
KN1_6:  .byte 125,$AA,$AA
KN1_720:  .byte 118,$B6,$0B
KN1_5040: .byte 115,$D0,$0D
KN1_3:  .byte 126,$AA,$AA
KN1_7:  .byte 125,$92,$49
KN1_11: .byte 124,$BA,$2E

K10:    .byte 131,$20,$00       ; 10.0
K1000:  .byte 137,$7A,$00       ; 1000.0
K10000: .byte 141,$1C,$40       ; 10000.0
P10:    .word 1000, 100, 10, 1
