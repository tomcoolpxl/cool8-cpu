; ---------------------------------------------------------------------
; lib.asm -- COOL8 standard routines.
;
; Part of the M2 gate corpus: real code, written to be good rather than
; to flatter the architecture. Where a routine needs to spill, it spills,
; and the comment says why.
;
; Calling convention used throughout:
;   arguments  R0-R3 and X/Y
;   returns    R0 (byte) or X (word)
;   registers  all caller-saved
; ---------------------------------------------------------------------

        .org  $0400

; ---------------------------------------------------------------------
; Macros
; ---------------------------------------------------------------------

; The ISA has ADDW X,Rd but no ADDW X,#imm16, so adding a 16-bit
; constant to a pointer takes six instructions. Worth a macro.
.macro  addx16 val
        MOV  R2,XL
        ADD  R2,#<\val
        MOV  XL,R2
        MOV  R2,XH
        ADC  R2,#>\val
        MOV  XH,R2
.endm

; Zero a block. @loop is macro-local: it expands to a label scoped to
; whatever routine the macro is used in.
.macro  memclr ptr, count
        LDW  Y,#\ptr
        MOV  R0,#\count
        CLR  R1
@loop:  ST   [Y],R1
        INCW Y
        SUB  R0,#1
        BNE  @loop
.endm


; ---------------------------------------------------------------------
; Block moves
; ---------------------------------------------------------------------

; memcpy -- X = source, Y = dest, R0 = count (0 means 256)
memcpy: LD   R1,[X]
        ST   [Y],R1
        INCW X
        INCW Y
        SUB  R0,#1
        BNE  memcpy
        RET

; memset -- Y = dest, R0 = value, R1 = count (0 means 256)
memset: ST   [Y],R0
        INCW Y
        SUB  R1,#1
        BNE  memset
        RET

; memcmp -- X, Y = blocks, R0 = count. Returns R0 = 0 if equal,
; otherwise the signed difference of the first differing byte.
memcmp: LD   R2,[X]
        LD   R3,[Y]
        CMP  R2,R3
        BNE  .diff
        INCW X
        INCW Y
        SUB  R0,#1
        BNE  memcmp
        CLR  R0
        RET
.diff:  MOV  R0,R2
        SUB  R0,R3
        RET


; ---------------------------------------------------------------------
; Strings
; ---------------------------------------------------------------------

; strlen -- X = string. Returns R0 = length, X = address of the NUL.
strlen: CLR  R0
.loop:  LD   R1,[X]
        BEQ  .done
        INCW X
        ADD  R0,#1
        BRA  .loop
.done:  RET

; strcpy -- X = source, Y = dest. Copies the NUL too.
strcpy: LD   R0,[X]
        ST   [Y],R0
        INCW X
        INCW Y
        TST  R0                 ; ST sets no flags, so test explicitly
        BNE  strcpy
        RET

; strcmp -- X, Y = strings. Returns R0 = 0 if equal, else the
; difference of the first differing pair.
strcmp: LD   R0,[X]
        LD   R1,[Y]
        CMP  R0,R1
        BNE  .diff
        TST  R0
        BEQ  .same
        INCW X
        INCW Y
        BRA  strcmp
.diff:  SUB  R0,R1
        RET
.same:  CLR  R0
        RET


; ---------------------------------------------------------------------
; 16-bit arithmetic
;
; There are no general-purpose 16-bit register pairs, so these work on
; memory operands addressed through X and Y.
; ---------------------------------------------------------------------

; add16 -- [X] += [Y], little-endian 16-bit
add16:  LD   R0,[X]
        LD   R1,[Y]
        ADD  R0,R1
        ST   [X],R0
        LD   R0,[X+1]
        LD   R1,[Y+1]
        ADC  R0,R1
        ST   [X+1],R0
        RET

; sub16 -- [X] -= [Y]
sub16:  LD   R0,[X]
        LD   R1,[Y]
        SUB  R0,R1
        ST   [X],R0
        LD   R0,[X+1]
        LD   R1,[Y+1]
        SBC  R0,R1
        ST   [X+1],R0
        RET

; cmp16 -- compare [X] with [Y]; flags are set for an unsigned compare
cmp16:  LD   R0,[X+1]
        LD   R1,[Y+1]
        CMP  R0,R1
        BNE  .done
        LD   R0,[X]
        LD   R1,[Y]
        CMP  R0,R1
.done:  RET

; shl16 -- [X] <<= 1
shl16:  LD   R0,[X]
        SHL  R0
        ST   [X],R0
        LD   R0,[X+1]
        ROL  R0
        ST   [X+1],R0
        RET

; mul16 -- R1:R0 = R1:R0 * R3:R2, low 16 bits of the product.
;
; MUL writes its result to X, so a caller's pointer has to be saved
; across it. That is a genuine cost of the destination choice, and this
; is the routine where it shows.
mul16:  PUSHW X                 ; spill: MUL clobbers X
        MUL  R0,R3              ; a.lo * b.hi
        MOV  R3,XL
        MUL  R1,R2              ; a.hi * b.lo
        MOV  R1,XL
        ADD  R3,R1              ; cross terms, low byte only
        MUL  R0,R2              ; a.lo * b.lo
        MOV  R0,XL              ; result low
        MOV  R1,XH
        ADD  R1,R3              ; result high
        POPW X
        RET

; div8 -- R0 / R1. Returns R0 = quotient, R1 = remainder.
; Restoring division, eight iterations. Divisor 0 yields $FF.
;
; This routine uses all four general registers at once and has nowhere
; left to put anything. It is the tightest thing in the corpus.
div8:   CLR  R2                 ; remainder
        MOV  R3,#8              ; loop counter
.loop:  SHL  R0                 ; dividend MSB -> C
        ROL  R2                 ; ... into the remainder
        CMP  R2,R1
        BLO  .skip
        SUB  R2,R1
        ADD  R0,#1              ; SHL vacated bit 0, so this sets it
.skip:  SUB  R3,#1
        BNE  .loop
        MOV  R1,R2
        RET


; ---------------------------------------------------------------------
; Sorting
; ---------------------------------------------------------------------

; sort8 -- insertion sort, ascending. X = array, R0 = count (>= 1).
;
; Live at once: base pointer, count, i, j, key, and a temp for a[j-1].
; That is one more than the machine has, so the count goes on the stack.
; This is the clearest four-registers-is-tight result in the corpus.
sort8:  ADDW SP,#-1
        ST   [SP+0],R0          ; spill: count has nowhere else to live
        MOV  R1,#1              ; i = 1
.outer: LD   R0,[SP+0]
        CMP  R1,R0
        BHS  .done
        LD   R3,[X+R1]          ; key = a[i]
        MOV  R2,R1              ; j = i
.inner: TST  R2
        BEQ  .place
        MOV  R0,R2
        SUB  R0,#1
        LD   R0,[X+R0]          ; a[j-1]
        CMP  R0,R3
        BLS  .place             ; a[j-1] <= key, insertion point found
        ST   [X+R2],R0          ; shift it up
        SUB  R2,#1
        BRA  .inner
.place: ST   [X+R2],R3
        ADD  R1,#1
        BRA  .outer
.done:  ADDW SP,#1
        RET


; ---------------------------------------------------------------------
; Formatting
; ---------------------------------------------------------------------

; hex8 -- R0 = value, Y = output buffer. Writes two ASCII characters.
hex8:   MOV  R1,R0
        SWAP R1
        AND  R1,#$0F
        CALL .nib
        MOV  R1,R0
        AND  R1,#$0F
        CALL .nib
        RET
.nib:   CMP  R1,#10
        BLO  .digit
        ADD  R1,#'A'-10
        BRA  .put
.digit: ADD  R1,#'0'
.put:   ST   [Y],R1
        INCW Y
        RET

; dec8 -- R0 = value, Y = output buffer. Writes three ASCII digits,
; leading zeros included.
dec8:   MOV  R1,#100
        CALL .digit
        MOV  R1,#10
        CALL .digit
        ADD  R0,#'0'
        ST   [Y],R0
        INCW Y
        RET
.digit: MOV  R2,#'0'
.count: CMP  R0,R1
        BLO  .emit
        SUB  R0,R1
        ADD  R2,#1
        BRA  .count
.emit:  ST   [Y],R2
        INCW Y
        RET


; ---------------------------------------------------------------------
; Macro users, so the expansions get assembled and measured
; ---------------------------------------------------------------------

; ptr_bump -- X += 1000, using the addx16 macro
ptr_bump:
        addx16 1000
        RET

; clear_buf -- zero the 32-byte scratch buffer
clear_buf:
        memclr scratch, 32
        RET

scratch:
        .space 32
