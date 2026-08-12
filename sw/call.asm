; ---------------------------------------------------------------------
; call.asm -- reaching compiled BASIC from assembly, correctly.
;
; **A compiled routine takes its arguments on the stack, not in
; registers.** `tools/cool8bas.py` emits, for `CALL f(a, b)`, the
; arguments pushed *right to left* and the caller clearing them
; afterwards, so the callee reads `[SP+2]` upward, low byte first. A
; hand-written caller that puts the value in R0 instead does not fail
; loudly: it calls the routine with whatever happened to be pushed
; last.
;
; That is not hypothetical. `s_putn`'s first version emitted its minus
; sign that way and printed the value's own low byte instead, and it
; passed every test that printed a positive number -- the sign path is
; the only one that reveals it. The same mistake broke INPUT's echo in
; the same sitting.
;
; So the convention gets a name. `CALLB` is the only way this project
; calls into compiled BASIC from assembly, and it cannot be written
; wrongly because there is nothing to get wrong.
;
; [D66](../docs/01-decisions.md) is the port these are for: basic.bas
; is 52 % of the image and moves to assembly routine by routine, so
; every ported routine still has to talk to the ones that have not
; moved yet.
; ---------------------------------------------------------------------

; CALLB1 f, R0:R1 -- one 16-bit argument.
;
; The argument is already in R0:R1; this pushes it, calls, and clears.
; R0 and R1 are the callee's to destroy, which is why the caller saves
; them if it still wants them -- the same contract a compiled caller
; works under.
.macro  CALLB1 dest
        PUSH R1
        PUSH R0
        CALL \dest
        POP  R0
        POP  R1
.endm

; CALLB1K f, #k -- one 16-bit constant argument.
;
; The common shape when the assembly is emitting a character: a
; literal, and nothing worth preserving in R0:R1 afterwards.
.macro  CALLB1K dest, k
        SUB  R1,R1
        MOV  R0,\k
        PUSH R1
        PUSH R0
        CALL \dest
        POP  R0
        POP  R1
.endm
