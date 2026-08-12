; ---------------------------------------------------------------------
; ed.asm -- editor routines written by hand.
;
; **`sw/basic.bas` is 52 % of the image.** `sim/build_basic.py
; --by-file` puts the editor at 12,378 bytes against `interp.asm`'s
; 6,615, and the difference is not what they do -- it is that one is
; compiled BASIC and the other is assembly. `sim/test_lib.py` measures
; the same program at 704 bytes by hand and 3,634 compiled: **5.16x**.
;
; That ratio comes from `sw/demo.bas`, which is array- and call-heavy
; and is what docs/11-compiler.md section 5a names as this compiler's
; worst case, so it is an upper bound rather than a forecast. This file
; exists to replace the forecast with a measurement, one routine at a
; time, keeping the suite green throughout. If the editor's own ratio
; comes back near 2x the case for continuing is overwhelming; if it
; comes back near 1.2x the idea dies cheaply and this file goes away.
;
; **The calling convention is the compiler's, not a new one.** A
; compiled `CALL name(a, b)` pushes right to left and clears the stack
; afterwards, so an argument is at [SP+2] upward, low byte first, and
; the routine simply returns. `EXTERN name` in the BASIC source is what
; makes the name callable -- tools/cool8bas.py's gen_call takes the
; extern path and skips the arity check, because the compiler cannot
; know what the assembly wants.
; ---------------------------------------------------------------------

; ---------------------------------------------------------------------
; s_putn -- a CARD as decimal digits, to the screen.
;
; Compiled: 196 bytes. This: see docs/13-basic.md section 10.
;
; **Divide and push, where the BASIC subtracted.** The compiled version
; walked 10000, 1000, 100, 10, 1 subtracting each in a loop and
; suppressing leading zeros with a flag, because a divide is a call in
; BASIC and five constants looked cheaper. In assembly `udiv16` is
; already here for `/` and MOD, so the digits come out of the remainder
; least significant first, go on the stack, and come back off in the
; right order -- which is `sstr`'s algorithm exactly, and that is the
; point: the editor and the interpreter should not disagree about what
; a number looks like.
;
; **A zero floor rather than a counter.** The digits pushed are '0' to
; '9' and never 0, so a 0 underneath them says where to stop. That is
; one byte of stack instead of a byte of page 0, and page 0 is the
; resource with no slack.
;
; An INT arrives as its bit pattern, so the top bit is its sign: say
; minus, then print the magnitude, which in CARD arithmetic is exactly
; 0 - v and gets -32768 right for free.
; ---------------------------------------------------------------------
s_putn: LD   R0,[SP+2]          ; the argument, low byte first
        LD   R1,[SP+3]
        TST  R1
        BPL  .pos
        PUSH R1                 ; the value, across the call
        PUSH R0
        CLR  R1
        MOV  R0,#$2D            ; '-'
        CALL emitc
        POP  R0
        POP  R1
        CALL negp16
.pos:   CLR  R2
        PUSH R2                 ; the floor
.dv:    MOV  R2,#10
        CLR  R3
        CALL udiv16
        LD   R2,[DREM]
        ADD  R2,#$30
        PUSH R2
        MOV  R2,R0              ; zero divides once and prints "0"
        OR   R2,R1
        BNE  .dv
.em:    POP  R0
        TST  R0
        BEQ  .out
        CLR  R1
        CALL emitc
        BRA  .em
.out:   RET
