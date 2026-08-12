; ---------------------------------------------------------------------
; num.asm -- numbers as text, and the divide that makes them.
;
; The bottom of the stack with the console ([D68]): it calls `con_emit`
; and nothing else. LIST wants a line number printed, PRINT wants a
; value printed, and the tokeniser wants text read back -- and the whole
; point of a module here is that they cannot disagree about what a
; number looks like.
;
; ## Why this is not in console.asm
;
; It was, briefly. `con_putn` would have had to call `udiv16` in
; `sw/interp.asm`, which is a call *upward* and the smell that says a
; routine is in the wrong file. Formatting a number is not the console's
; job -- the console emits characters -- so the console exports
; `con_emit` and this exports the thing that decides which characters.
;
; ## Still owed
;
; `snum`, the text-to-number direction, belongs here too and is still in
; `sw/interp.asm` because it is entangled with the float package. When
; it moves, `sw/token.asm`'s one call upward goes with it.
; ---------------------------------------------------------------------

        .include "console.asm"

; ---------------------------------------------------------------------
; num_div10 -- R0:R1 = R0:R1 / 10, remainder in R2.
;
; Restoring division, sixteen steps: the dividend shifts left out of the
; top into the remainder and the quotient shifts in at the bottom, so
; one register pair does both and there is nothing to copy at the end.
;
; **Not `udiv16`.** The interpreter's general divide is the right
; routine for `/` and `MOD` and the wrong one here: it lives above this
; module, and it costs a 16-bit divisor, a sign rule and two page-0
; words for a job whose divisor is always ten.
; ---------------------------------------------------------------------
num_div10:
        CLR  R2
        MOV  R3,#16
.l:     SHL  R0
        ROL  R1
        ROL  R2
        CMP  R2,#10
        BLO  .n
        SUB  R2,#10
        OR   R0,#1
.n:     SUB  R3,#1
        BNE  .l
        RET

; ---------------------------------------------------------------------
; num_put -- R0:R1 as decimal, signed, to the console.
;
; **Divide and push.** The compiled `putn` walked 10000, 1000, 100, 10
; and 1, subtracting each in a loop and suppressing leading zeros with a
; flag, because a divide is a call in BASIC and five constants looked
; cheaper. Here the digits come out of the remainder least significant
; first, go on the stack, and come back off in the right order.
;
; The digits pushed are '0' to '9' and never 0, so a 0 underneath them
; says where to stop -- one byte of stack rather than a counter.
;
; An INT arrives as its bit pattern, so the top bit is the sign: say
; minus, then print the magnitude, which in unsigned arithmetic is
; exactly 0 - v and gets -32768 right without a special case.
; ---------------------------------------------------------------------
num_put:
        TST  R1
        BPL  .pos
        PUSH R1
        PUSH R0
        MOV  R0,#$2D            ; '-'
        CALL con_emit
        POP  R0
        POP  R1
        MOV  R2,R0              ; negate: 0 - v
        MOV  R3,R1
        CLR  R0
        CLR  R1
        SUB  R0,R2
        SBC  R1,R3
.pos:   CLR  R2
        PUSH R2                 ; the floor
.dv:    CALL num_div10          ; quotient stays in R0:R1 for the next
        ADD  R2,#$30            ;   round, remainder is this digit
        PUSH R2
        MOV  R2,R0              ; zero divides once and prints "0"
        OR   R2,R1
        BNE  .dv
.em:    POP  R0
        TST  R0
        BEQ  .out
        PUSH R0
        CALL con_emit
        POP  R0
        BRA  .em
.out:   RET
