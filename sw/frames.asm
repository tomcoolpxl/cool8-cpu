; ---------------------------------------------------------------------
; frames.asm -- what a C compiler would emit.
;
; Part of the M2 gate corpus. This is deliberately *not* hand-optimised
; assembly: it is written the way a straightforward compiler back end
; would generate it, with arguments passed on the stack, locals in the
; frame, and values reloaded rather than kept in registers.
;
; The point is to test the claim in docs/00-goals.md that COOL8 is a
; plausible compiler target, which is a different question from whether
; it is pleasant to hand-write. A high spill count here is the expected
; and correct result -- it is what [SP+u8] exists for.
;
; Convention (cdecl-like):
;   arguments pushed right to left by the caller
;   caller cleans up
;   return value in R0
;   after CALL:  [SP+0..1] = return address, [SP+2] = first argument
; ---------------------------------------------------------------------

        .org  $0800


; ---------------------------------------------------------------------
; unsigned char sum3(unsigned char a, unsigned char b, unsigned char c)
; {
;     return a + b + c;
; }
;
; No locals, so no frame adjustment is needed.
; ---------------------------------------------------------------------
sum3:   LD   R0,[SP+2]          ; a
        LD   R1,[SP+3]          ; b
        ADD  R0,R1
        LD   R1,[SP+4]          ; c
        ADD  R0,R1
        RET


; ---------------------------------------------------------------------
; unsigned char poly(unsigned char x)
; {
;     unsigned char t = x * x;
;     unsigned char u = t + x;
;     return u + 3;
; }
;
; Two locals in the frame. Note that the compiler stores t and u even
; though a human would keep both in registers -- that is the point.
; ---------------------------------------------------------------------
poly:   ADDW SP,#-2             ; allocate t at [SP+0], u at [SP+1]
        LD   R0,[SP+4]          ; x  (2 locals + 2 bytes of return address)
        MUL  R0,R0              ; X = x * x
        MOV  R0,XL
        ST   [SP+0],R0          ; t = x * x
        LD   R1,[SP+4]          ; x
        LD   R0,[SP+0]          ; t
        ADD  R0,R1
        ST   [SP+1],R0          ; u = t + x
        LD   R0,[SP+1]          ; u
        ADD  R0,#3
        ADDW SP,#2              ; release the frame
        RET


; ---------------------------------------------------------------------
; unsigned char outer(unsigned char n)
; {
;     return sum3(n, poly(n), 1);
; }
;
; A nested call with a live value across it. n must survive the call to
; poly, so it goes in the frame -- exactly what a compiler does when a
; value is live across a call and every register is caller-saved.
; ---------------------------------------------------------------------
outer:  ADDW SP,#-1             ; one local: n, live across the call
        LD   R0,[SP+3]          ; argument n
        ST   [SP+0],R0

        LD   R0,[SP+0]          ; poly(n)
        PUSH R0
        CALL poly
        ADDW SP,#1              ; caller cleans up
        MOV  R3,R0              ; t = poly(n)

        MOV  R0,#1              ; sum3(n, t, 1) -- pushed right to left
        PUSH R0                 ; c
        PUSH R3                 ; b
        LD   R0,[SP+2]          ; n, now two pushes deeper
        PUSH R0                 ; a
        CALL sum3
        ADDW SP,#3

        ADDW SP,#1
        RET


; ---------------------------------------------------------------------
; unsigned char sum_array(unsigned char *p, unsigned char n)
; {
;     unsigned char total = 0;
;     while (n--) total += *p++;
;     return total;
; }
;
; A pointer argument. The compiler pulls it into X once and keeps it
; there, which is the case COOL8 handles well.
; ---------------------------------------------------------------------
sum_array:
        LD   R0,[SP+2]          ; p low
        MOV  XL,R0
        LD   R0,[SP+3]          ; p high
        MOV  XH,R0
        LD   R1,[SP+4]          ; n
        CLR  R0                 ; total
.loop:  TST  R1
        BEQ  .done
        LD   R2,[X]
        ADD  R0,R2
        INCW X
        SUB  R1,#1
        BRA  .loop
.done:  RET


; ---------------------------------------------------------------------
; A four-deep call chain, each level holding a local across the call.
; This is the shape that a fixed 256-byte stack would strangle and a
; 16-bit SP handles without noticing.
; ---------------------------------------------------------------------
depth4: ADDW SP,#-1
        LD   R0,[SP+3]
        ADD  R0,#1
        ST   [SP+0],R0
        PUSH R0
        CALL depth3
        ADDW SP,#1
        LD   R1,[SP+0]
        ADD  R0,R1
        ADDW SP,#1
        RET

depth3: ADDW SP,#-1
        LD   R0,[SP+3]
        ADD  R0,#1
        ST   [SP+0],R0
        PUSH R0
        CALL depth2
        ADDW SP,#1
        LD   R1,[SP+0]
        ADD  R0,R1
        ADDW SP,#1
        RET

depth2: ADDW SP,#-1
        LD   R0,[SP+3]
        ADD  R0,#1
        ST   [SP+0],R0
        PUSH R0
        CALL depth1
        ADDW SP,#1
        LD   R1,[SP+0]
        ADD  R0,R1
        ADDW SP,#1
        RET

depth1: LD   R0,[SP+2]
        ADD  R0,#1
        RET
