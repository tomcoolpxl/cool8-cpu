; ---------------------------------------------------------------------
; interp.asm -- COOL8 BASIC, executing the program it holds.
;
; I1: statement dispatch, resident variables, an inlined expression
; walker, LET, FOR/NEXT and END. Gated by sim/test_interp.py, which
; runs the same program as native code and requires the same answers,
; then reports what the interpretation cost.
;
; ## The two decisions this file is built on, both measured
;
; **Dispatch once per statement.** sim/bench_dispatch.py: a token table
; costs 38 clocks of overhead, direct threading 19, subroutine threading
; 9. The cheap ones need a translated copy of the program in memory,
; which is the whole thing an interpreter exists to avoid -- so the
; expensive one is used, and paid once per statement rather than once
; per operation.
;
; **A variable name is an address.** `K` is not looked up, it is index
; 10 of VARS. BBC BASIC did this with A%-Z% and it is most of the speed
; in a loop.
;
; ## Why the expression walker is written out flat
;
; sim/bench_interp2.py measured an expression at 5x native with a `term`
; subroutine per operand: a CALL and a RET is 9 clocks, and an operand
; is barely more work than that. Here the two cases that matter -- a
; variable and a constant -- are inline in the walk, and only the rest
; go anywhere.
;
; The walk is iterative. It has to be: the stack is 256 bytes and the
; I/O page sits directly below it, so anything that recurses on
; expression depth pushes return addresses into hardware registers.
; ---------------------------------------------------------------------

; ---- tokens
;
; Statements are $80 upward and consecutive, so the dispatch index is
; token - $80. Expression tokens are $C0 upward.
T_LET   = $80
T_FOR   = $81
T_NEXT  = $82
T_END   = $83
NSTMT   = 4

E_CON   = $C0                   ; a 16-bit constant follows
E_VAR   = $C1                   ; a variable index follows
E_ADD   = $D0
E_SUB   = $D1
E_EOX   = $FF                   ; end of expression

; ---- state, in zero page: every one of these is touched per statement
IP      = $0010                 ; 2: where we are in the program
ACC     = $0012                 ; 2: the expression accumulator
TMP     = $0014                 ; 2
TVAR    = $0016                 ; 1: the target of a LET
LVAR    = $0017                 ; 1: the FOR variable, doubled
LLIM    = $0018                 ; 2: its limit
LBODY   = $001A                 ; 2: where its body starts

VARS    = $0040                 ; 52: A-Z, two bytes each

; ---------------------------------------------------------------------
; The dispatcher.
;
; Y is the program pointer throughout. Keeping it in a register rather
; than reloading it from IP is worth two instructions per token, and
; tokens are the thing there are most of.
; ---------------------------------------------------------------------
run:
        LDW  Y,[IP]
disp:
        LD   R0,[Y]
        INCW Y
        SUB  R0,#T_LET
        SHL  R0
        LDW  X,#sttab
        LD   R1,[X+R0]
        ADD  R0,#1
        LD   R2,[X+R0]
        MOV  XL,R1
        MOV  XH,R2
        JMP  [X]

sttab:  .word h_let
        .word h_for
        .word h_next
        .word h_end

h_end:  STW  [IP],Y
        RET

; ---------------------------------------------------------------------
; LET v = <expression>
;
; The target is read, then the walk runs to E_EOX and the accumulator is
; stored. One dispatch covers all of it.
; ---------------------------------------------------------------------
h_let:
        LD   R0,[Y]
        INCW Y
        SHL  R0
        ST   [TVAR],R0
        CALL expr
        LDW  X,#VARS
        LD   R0,[TVAR]
        ADDW X,R0
        LD   R0,[ACC]
        ST   [X],R0
        INCW X
        LD   R0,[ACC+1]
        ST   [X],R0
        JMP  disp

; ---------------------------------------------------------------------
; expr -- the walk. Leaves the value in ACC and Y past the E_EOX.
;
; The first operand and every operand after an operator go through the
; same inline code: fetch the token, and branch on the two cases worth
; having. A constant is two bytes inline; a variable is an index into a
; table at a known address.
; ---------------------------------------------------------------------
expr:
        ; ---- first operand, straight into the accumulator
        LD   R0,[Y]
        INCW Y
        CMP  R0,#E_CON
        BNE  .v1
        LD   R0,[Y]             ; a constant
        INCW Y
        ST   [ACC],R0
        LD   R0,[Y]
        INCW Y
        ST   [ACC+1],R0
        BRA  .op
.v1:    LD   R0,[Y]             ; a variable
        INCW Y
        SHL  R0
        LDW  X,#VARS
        ADDW X,R0
        LD   R0,[X]
        ST   [ACC],R0
        INCW X
        LD   R0,[X]
        ST   [ACC+1],R0

        ; ---- operator, operand, accumulate
        ;
        ; The operator is branched on before its operand is fetched, so
        ; the operand can go straight into R2:R3 and stay there. Saving
        ; the operator somewhere and reloading it afterwards costs the
        ; register the operand is already in -- which is the bug this
        ; shape exists to avoid.
        ;
        ; The fetch is written out twice rather than called. It is
        ; fourteen instructions against a CALL and a RET at nine clocks,
        ; and this is the hottest path in the interpreter.
.op:    LD   R0,[Y]
        INCW Y
        CMP  R0,#E_ADD
        BEQ  .padd
        CMP  R0,#E_SUB
        BEQ  .psub
        RET                     ; E_EOX, and Y is already past it

.padd:  LD   R0,[Y]
        INCW Y
        CMP  R0,#E_CON
        BNE  .av
        LD   R2,[Y]
        INCW Y
        LD   R3,[Y]
        INCW Y
        BRA  .adone
.av:    LD   R0,[Y]
        INCW Y
        SHL  R0
        LDW  X,#VARS
        ADDW X,R0
        LD   R2,[X]
        INCW X
        LD   R3,[X]
.adone: LD   R0,[ACC]
        LD   R1,[ACC+1]
        ADD  R0,R2
        ADC  R1,R3
        ST   [ACC],R0
        ST   [ACC+1],R1
        BRA  .op

.psub:  LD   R0,[Y]
        INCW Y
        CMP  R0,#E_CON
        BNE  .sv
        LD   R2,[Y]
        INCW Y
        LD   R3,[Y]
        INCW Y
        BRA  .sdone
.sv:    LD   R0,[Y]
        INCW Y
        SHL  R0
        LDW  X,#VARS
        ADDW X,R0
        LD   R2,[X]
        INCW X
        LD   R3,[X]
.sdone: LD   R0,[ACC]
        LD   R1,[ACC+1]
        SUB  R0,R2
        SBC  R1,R3
        ST   [ACC],R0
        ST   [ACC+1],R1
        BRA  .op

; ---------------------------------------------------------------------
; FOR v = <expr> TO <expr>
;
; The start goes into the variable, the limit and the address of the
; body go into the loop state. One deep, which is what I1 needs; a
; stack of them costs the same per iteration because the state is read
; from fixed addresses either way.
; ---------------------------------------------------------------------
h_for:
        LD   R0,[Y]
        INCW Y
        SHL  R0
        ST   [LVAR],R0
        CALL expr               ; the start
        LDW  X,#VARS
        LD   R0,[LVAR]
        ADDW X,R0
        LD   R0,[ACC]
        ST   [X],R0
        INCW X
        LD   R0,[ACC+1]
        ST   [X],R0
        CALL expr               ; the limit
        LD   R0,[ACC]
        ST   [LLIM],R0
        LD   R0,[ACC+1]
        ST   [LLIM+1],R0
        MOV  R0,YL
        ST   [LBODY],R0
        MOV  R0,YH
        ST   [LBODY+1],R0
        JMP  disp

; ---------------------------------------------------------------------
; NEXT v
;
; Increment, compare, and go back to the body. The variable index is
; skipped rather than checked: a mismatched NEXT is a program error and
; checking it costs every iteration.
; ---------------------------------------------------------------------
h_next:
        INCW Y
nx:     LDW  X,#VARS
        LD   R0,[LVAR]
        ADDW X,R0
        LD   R2,[X]
        INCW X
        LD   R3,[X]
        MOV  R0,#1
        ADD  R2,R0
        MOV  R0,#0
        ADC  R3,R0
        ST   [X],R3
        DECW X
        ST   [X],R2
        LD   R0,[LLIM]
        LD   R1,[LLIM+1]
        SUB  R0,R2              ; limit - v; carry on while v <= limit
        SBC  R1,R3
        BLT  .out
        LD   R0,[LBODY]
        MOV  YL,R0
        LD   R0,[LBODY+1]
        MOV  YH,R0
        LD   R0,[Y]             ; an empty body is just this NEXT again
        CMP  R0,#T_NEXT
        BEQ  .again
        JMP  disp
.again: INCW Y
        INCW Y
        BRA  nx
.out:   JMP  disp
