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

; ---------------------------------------------------------------------
; s_number -- the line number at `ip` in the editor's line buffer.
;
; Compiled, `number()` was 193 bytes: `skipsp`, an optional leading
; comma, its own digit loop, and an `any` flag returning -1 when there
; were no digits. **Only `enter` calls it**, and only after testing
; `isdigit` itself -- so the comma arm and the -1 both served a caller
; that no longer exists (the comment named RENUMBER, which does not use
; it any more). The digits are all that is live.
;
; So this is the shared parser and a position: `snumi` is `snum` with a
; point ending the number rather than starting a fraction, which is
; what a line number wants and what the editor did anyway -- "10.5" is
; line 10, pinned in sim/test_basic.py before this moved.
;
; `ip` advances by what `snumi` consumed, which `SDIG` reports: it
; counts down as characters are taken, so llen minus what is left is
; where the parser stopped. The value is returned in R0:R1, where a
; compiled FUNCTION leaves one, so `n = s_number()` reads unchanged.
;
; R2:R3 carry the position arithmetic *after* the call precisely so the
; value in R0:R1 survives without a push and a pop around it.
; ---------------------------------------------------------------------
s_number:
        PUSHW Y                 ; the editor's routines use Y freely
        LD   R0,[v_llen]
        LD   R1,[v_ip]
        SUB  R0,R1
        ST   [SDIG],R0          ; characters the parser may look at
        LDW  Y,#a_lbuf
        ADDW Y,R1
        CALL snumi
        LD   R2,[v_llen]        ; not R0:R1: those hold the answer
        LD   R3,[SDIG]
        SUB  R2,R3
        ST   [v_ip],R2
        POPW Y
        RET
