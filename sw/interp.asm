; ---------------------------------------------------------------------
; interp.asm -- COOL8 BASIC, executing the program it holds.
;
; The stored program IS the program. There is no compile step and no
; second copy in memory: what LIST shows is what runs.
;
; ## It executes the editor's tokens, not its own
;
; I1 invented a private token space and was poked into memory by hand.
; That was wrong the moment it met a real program: $80 is PRINT in the
; editor's TOKTAB, not LET. This walks the stored form directly --
;
;     lineno (2, LE) | len (1) | tokens (len)
;
; -- with the same token bytes the editor writes. Statement tokens are
; not consecutive in TOKTAB, so dispatch is a table indexed by
; token - $80 with every unimplemented slot pointing at one handler.
;
; ## Recursion is bounded, and that is deliberate
;
; The stack is 256 bytes and the I/O page sits directly below it, so a
; stack that runs past ~250 bytes pushes return addresses into hardware
; registers where they are silently lost. That cost a day earlier in
; this project.
;
; The expression evaluator is recursive descent, which is safe here for
; a reason worth writing down: a level costs one return address, so a
; parenthesis costs six bytes, not the sixty a compiled recursive
; descent cost. Depth 20 is 120 bytes. The compiler blew the stack
; because its frames were large, not because it recursed.
; ---------------------------------------------------------------------

; ---- the editor's tokens (sw/basic.bas TOKTAB, order frozen)
K_PRINT = $80
K_SUB   = $81
K_FUNC  = $82
K_DIM   = $83
K_CONST = $84
K_FOR   = $85
K_NEXT  = $86
K_TO    = $87
K_DO    = $88
K_LOOP  = $89
K_WHILE = $8A
K_UNTIL = $8B
K_EXIT  = $8C
K_IF    = $8D
K_THEN  = $8E
K_ELSE  = $8F
K_ELSIF = $90
K_END   = $91
K_RET   = $92
K_CALL  = $93
K_PEEK  = $97
K_POKE  = $98
K_AND   = $99
K_OR    = $9A
K_XOR   = $9B
K_GOTO  = $A2
K_NUM   = $A4                   ; a binary literal: two bytes follow

NTOK    = 37                    ; $80..$A4

; ---- state, all in zero page: every one is touched per statement
IP      = $0010                 ; 2: where we are in the token stream
LEND    = $0012                 ; 2: end of the current line's tokens
LREC    = $0014                 ; 2: the current line record
PEND    = $0016                 ; 2: progend, snapshot at RUN
ERR     = $0018                 ; 1: nonzero stops the program
TVAR    = $0019                 ; 1: a variable index, doubled
LVAR    = $001A                 ; 1: the FOR variable, doubled
LLIM    = $001B                 ; 2: its limit
LBODY   = $001D                 ; 2: where its body starts
LLINE   = $001F                 ; 2: and which line that was
LLEND   = $0021                 ; 2: and where that line's tokens end
MTMP    = $0023                 ; 4: multiply scratch

VARS    = $0040                 ; 52: A-Z, two bytes each

; ---------------------------------------------------------------------
; run -- execute from the first line to the last.
;
; X and Y are both needed for memory access, so the token pointer lives
; in Y and everything else is reloaded. Y is the thing there are most
; accesses to.
; ---------------------------------------------------------------------
irun:
        CLR  R0
        ST   [ERR],R0
        LDW  X,#VARS            ; every variable starts at zero
        MOV  R1,#52
.iz:    CLR  R0
        ST   [X],R0
        INCW X
        SUB  R1,#1
        BNE  .iz
        ; LREC and PEND are set by the caller -- the editor passes the
        ; program it is holding, and the gate passes one it built.
        CALL openline
        JMP  stmt

; openline -- LREC points at a record; set Y past its header and LEND
; past its tokens.
openline:
        LD   R0,[LREC]
        MOV  YL,R0
        LD   R0,[LREC+1]
        MOV  YH,R0
        INCW Y
        INCW Y
        LD   R0,[Y]             ; the length byte
        INCW Y
        MOV  R1,YL
        ADD  R1,R0
        ST   [LEND],R1
        MOV  R1,YH
        MOV  R2,#0
        ADC  R1,R2
        ST   [LEND+1],R1
        RET

; nextline -- LREC = the record after this one. Carry clear when the
; program has run out.
nextline:
        LD   R0,[LEND]
        ST   [LREC],R0
        LD   R1,[LEND+1]
        ST   [LREC+1],R1
        LD   R2,[PEND]
        LD   R3,[PEND+1]
        SUB  R0,R2              ; LREC - progend
        SBC  R1,R3
        BLT  .more
        CLC
        RET
.more:  CALL openline
        SEC
        RET

; ---------------------------------------------------------------------
; The statement loop.
; ---------------------------------------------------------------------
stmt:
        LD   R0,[ERR]
        TST  R0
        BEQ  .live
        RET
.live:
        MOV  R0,YL              ; end of line?
        LD   R2,[LEND]
        MOV  R1,YH
        LD   R3,[LEND+1]
        SUB  R0,R2
        SBC  R1,R3
        BLT  .more
        CALL nextline
        BCS  stmt
        RET                     ; fell off the end: stop
.more:
        LD   R0,[Y]
        CMP  R0,#$80            ; below $80 it is a name: an assignment
        BCC  h_let
        INCW Y
        SUB  R0,#$80
        CMP  R0,#NTOK
        BCS  bad
        SHL  R0
        LDW  X,#sttab
        LD   R1,[X+R0]
        ADD  R0,#1
        LD   R2,[X+R0]
        MOV  XL,R1
        MOV  XH,R2
        JMP  [X]

bad:    MOV  R0,#1              ; ?SYNTAX ERROR
        ST   [ERR],R0
        RET

; $80..$A4. Everything not implemented lands on `bad`, which is the
; honest answer and costs one slot each.
sttab:
        .word h_print           ; $80 PRINT
        .word h_sub             ; $81 SUB -- a definition, skipped
        .word h_sub             ; $82 FUNCTION
        .word bad               ; $83 DIM
        .word bad               ; $84 CONST
        .word h_for             ; $85 FOR
        .word h_next            ; $86 NEXT
        .word bad               ; $87 TO
        .word bad               ; $88 DO
        .word bad               ; $89 LOOP
        .word bad               ; $8A WHILE
        .word bad               ; $8B UNTIL
        .word bad               ; $8C EXIT
        .word h_if              ; $8D IF
        .word bad               ; $8E THEN
        .word h_else            ; $8F ELSE
        .word bad               ; $90 ELSEIF
        .word h_end             ; $91 END
        .word bad               ; $92 RETURN
        .word bad               ; $93 CALL
        .word bad               ; $94 AS
        .word bad               ; $95 INT
        .word bad               ; $96 BYTE
        .word bad               ; $97 PEEK
        .word h_poke            ; $98 POKE
        .word bad               ; $99 AND
        .word bad               ; $9A OR
        .word bad               ; $9B XOR
        .word bad               ; $9C CARD
        .word bad               ; $9D AT
        .word bad               ; $9E ASM
        .word bad               ; $9F EXTERN
        .word bad               ; $A0 INCLUDE
        .word bad               ; $A1 INLINE
        .word h_goto            ; $A2 GOTO
        .word bad               ; $A3 WEND
        .word bad               ; $A4 NUM

h_end:  MOV  R0,#255            ; a clean stop, not an error
        ST   [ERR],R0
        RET

; A SUB definition met while running is skipped to its END.
h_sub:  LD   R0,[LEND]
        MOV  YL,R0
        LD   R0,[LEND+1]
        MOV  YH,R0
        JMP  stmt

; ---------------------------------------------------------------------
; v = <expression>
;
; A name is one letter here: A-Z are resident, which is BBC BASIC's
; A%-Z% and is why a loop counter costs nothing to find.
; ---------------------------------------------------------------------
h_let:
        CALL varidx             ; R0 = index*2, Y past the name
        ST   [TVAR],R0
        INCW Y                  ; the '='
        CALL eval
        LDW  X,#VARS
        LD   R2,[TVAR]
        ADDW X,R2
        ST   [X],R0
        INCW X
        ST   [X],R1
        JMP  stmt

; varidx -- the variable at Y, as an index into VARS, doubled.
varidx:
        LD   R0,[Y]
        INCW Y
        SUB  R0,#65             ; 'A'
        SHL  R0
        RET

; ---------------------------------------------------------------------
; POKE addr, value
; ---------------------------------------------------------------------
h_poke:
        CALL eval
        MOV  XL,R0
        MOV  XH,R1
        PUSHW X
        INCW Y                  ; the comma
        CALL eval
        POPW X
        ST   [X],R0
        JMP  stmt

; ---------------------------------------------------------------------
; PRINT <expr> -- one number, then a newline. The editor's own screen
; routines do the work; there is no second console.
; ---------------------------------------------------------------------
h_print:
        CALL eval
        PUSH R1
        PUSH R0
        CALL s_putn
        CALL s_newline
        POP  R0
        POP  R1
        JMP  stmt

; ---------------------------------------------------------------------
; IF <expr> THEN ...
;
; True runs the rest of the line. False skips it -- to ELSE if this line
; has one, otherwise to the next line. Single-line IF only, which is the
; shape that costs nothing to find the end of.
; ---------------------------------------------------------------------
h_if:
        CALL eval
        MOV  R2,R0
        OR   R2,R1
        BEQ  .false
        INCW Y                  ; step over THEN
        JMP  stmt
        ; False: walk to an ELSE on this line, or to the end of it. The
        ; statement loop takes it from there -- reaching the end of a
        ; line is exactly what it already knows how to handle.
.false: MOV  R0,YL
        LD   R2,[LEND]
        MOV  R1,YH
        LD   R3,[LEND+1]
        SUB  R0,R2
        SBC  R1,R3
        BLT  .scan
        JMP  stmt
.scan:  LD   R0,[Y]
        INCW Y
        CMP  R0,#K_ELSE
        BNE  .false
        JMP  stmt

; ELSE reached while running means the true arm just finished.
h_else: LD   R0,[LEND]
        MOV  YL,R0
        LD   R0,[LEND+1]
        MOV  YH,R0
        JMP  stmt

; ---------------------------------------------------------------------
; GOTO n
; ---------------------------------------------------------------------
h_goto:
        CALL eval               ; the line number
        PUSH R1
        PUSH R0
        CALL s_findline
        POP  R2
        POP  R2
        ST   [LREC],R0
        ST   [LREC+1],R1
        CALL openline
        JMP  stmt

; ---------------------------------------------------------------------
; FOR v = <expr> TO <expr>   /   NEXT [v]
;
; One level, which is what the gate needs; a stack of them costs the
; same per iteration because the state is read from fixed addresses
; either way.
; ---------------------------------------------------------------------
h_for:
        CALL varidx
        ST   [LVAR],R0
        INCW Y                  ; the '='
        CALL eval
        LDW  X,#VARS
        LD   R2,[LVAR]
        ADDW X,R2
        ST   [X],R0
        INCW X
        ST   [X],R1
        INCW Y                  ; the TO
        CALL eval
        ST   [LLIM],R0
        ST   [LLIM+1],R1
        MOV  R0,YL
        ST   [LBODY],R0
        MOV  R0,YH
        ST   [LBODY+1],R0
        LD   R0,[LREC]
        ST   [LLINE],R0
        LD   R0,[LREC+1]
        ST   [LLINE+1],R0
        ; the body;s end too, so NEXT never re-reads the line header
        LD   R0,[LEND]
        ST   [LLEND],R0
        LD   R0,[LEND+1]
        ST   [LLEND+1],R0
        JMP  stmt

h_next:
        LD   R0,[Y]             ; an optional variable name
        CMP  R0,#$80
        BCS  .go
        INCW Y
.go:    LDW  X,#VARS
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
        SUB  R0,R2              ; limit - v; go on while v <= limit
        SBC  R1,R3
        BLT  .out
        ; Back to the body without re-opening the line. openline was
        ; 16 % of the whole benchmark and half of its calls were this
        ; one, re-deriving what FOR already knew.
        LD   R0,[LLINE]
        ST   [LREC],R0
        LD   R0,[LLINE+1]
        ST   [LREC+1],R0
        LD   R0,[LLEND]
        ST   [LEND],R0
        LD   R0,[LLEND+1]
        ST   [LEND+1],R0
        LD   R0,[LBODY]
        MOV  YL,R0
        LD   R0,[LBODY+1]
        MOV  YH,R0
        JMP  stmt
.out:   JMP  stmt

; ---------------------------------------------------------------------
; The expression evaluator.
;
; Recursive descent, value in R0:R1, one level per precedence. A level
; costs a return address, so a parenthesis costs six bytes of stack --
; which is why this may recurse where the compiler could not.
;
;   eval  = sum  [ relational sum ]
;   sum   = prod { + - }
;   prod  = prim { * }
;   prim  = number | variable | ( eval ) | - prim | PEEK ( eval )
; ---------------------------------------------------------------------
eval:
        CALL prim               ; the first operand
        ; ---- { * operand }, highest precedence, checked inline
.mul:   LD   R2,[Y]
        CMP  R2,#$2A            ; '*'
        BNE  .sum
        INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        CALL imul16
        BRA  .mul
        ; ---- { + operand | - operand }
.sum:   LD   R2,[Y]
        CMP  R2,#$2B            ; '+'
        BEQ  .add
        CMP  R2,#$2D            ; '-'
        BEQ  .sub
        BRA  .rel
.add:   INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        ADD  R0,R2
        ADC  R1,R3
        BRA  .sum
.sub:   INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        SUB  R0,R2
        SBC  R1,R3
        BRA  .sum
        ; ---- one relation, if there is one
.rel:   LD   R2,[Y]
        CMP  R2,#$3D            ; '='
        BEQ  .req
        CMP  R2,#$3C            ; '<'
        BEQ  .rlt
        CMP  R2,#$3E            ; '>'
        BEQ  .rgt
        RET

.req:   INCW Y
        CALL rhs
        SUB  R0,R2
        SBC  R1,R3
        OR   R0,R1
        BEQ  .y1
        JMP  false
.y1:    JMP  true

.rlt:   INCW Y
        LD   R2,[Y]
        CMP  R2,#$3D
        BEQ  .rle
        CMP  R2,#$3E
        BEQ  .rne
        CALL rhs
        SUB  R0,R2
        SBC  R1,R3
        BLT  .y2
        JMP  false
.y2:    JMP  true
.rne:   INCW Y
        CALL rhs
        SUB  R0,R2
        SBC  R1,R3
        OR   R0,R1
        BEQ  .y3
        JMP  true
.y3:    JMP  false
.rle:   INCW Y                  ; a <= b is b >= a
        CALL rhs
        MOV  R0,R2              ; swap: compare b - a
        MOV  R1,R3
        POP  R2
        POP  R3
        PUSH R3
        PUSH R2
        BRA  .cmpge
.rgt:   INCW Y
        LD   R2,[Y]
        CMP  R2,#$3D
        BEQ  .rge
        CALL rhs                ; a > b is b < a
        MOV  R0,R2
        MOV  R1,R3
        POP  R2
        POP  R3
        PUSH R3
        PUSH R2
        SUB  R0,R2
        SBC  R1,R3
        BLT  .y4
        JMP  false
.y4:    JMP  true
.rge:   INCW Y
        CALL rhs
        SUB  R0,R2
        SBC  R1,R3
.cmpge: BGE  .y5
        JMP  false
.y5:    JMP  true

; rhs -- the right-hand side of a relation, with its own * and +/-.
; The left side is preserved in R0:R1 across it.
rhs:    PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        CALL sumrest
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        RET

; mulrest -- { * operand } applied to whatever is in R0:R1.
mulrest:
        LD   R2,[Y]
        CMP  R2,#$2A
        BEQ  .go
        RET
.go:    INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        CALL imul16
        BRA  mulrest

; sumrest -- { + operand | - operand } applied to R0:R1.
sumrest:
        LD   R2,[Y]
        CMP  R2,#$2B
        BEQ  .a
        CMP  R2,#$2D
        BEQ  .s
        RET
.a:     INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        ADD  R0,R2
        ADC  R1,R3
        BRA  sumrest
.s:     INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        SUB  R0,R2
        SBC  R1,R3
        BRA  sumrest

true:   MOV  R0,#1
        CLR  R1
        RET
false:  CLR  R0
        CLR  R1
        RET

prim:
        LD   R0,[Y]
        CMP  R0,#K_NUM
        BEQ  .num
        CMP  R0,#$28            ; '('
        BEQ  .paren
        CMP  R0,#$2D            ; unary minus
        BEQ  .neg
        CMP  R0,#K_PEEK
        BEQ  .peek
        ; a name
        CALL varidx
        LDW  X,#VARS
        ADDW X,R0
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        RET
.num:   INCW Y
        LD   R0,[Y]
        INCW Y
        LD   R1,[Y]
        INCW Y
        RET
.paren: INCW Y
        CALL eval
        INCW Y                  ; the ')'
        RET
.neg:   INCW Y
        CALL prim
        MOV  R2,R0
        MOV  R3,R1
        CLR  R0
        CLR  R1
        SUB  R0,R2
        SBC  R1,R3
        RET
.peek:  INCW Y
        INCW Y                  ; the '('
        CALL eval
        INCW Y                  ; the ')'
        MOV  XL,R0
        MOV  XH,R1
        LD   R0,[X]
        CLR  R1
        RET

; ---------------------------------------------------------------------
; R0:R1 = R0:R1 * R2:R3. MUL is 8x8 and lands in X, so the four partial
; products are added by hand and X is spilled around each.
; ---------------------------------------------------------------------
imul16:
        ST   [MTMP],R0
        ST   [MTMP+1],R1
        ST   [MTMP+2],R2
        ST   [MTMP+3],R3
        LD   R0,[MTMP]          ; low * low
        LD   R1,[MTMP+2]
        MUL  R0,R1
        MOV  R0,XL
        MOV  R1,XH
        LD   R2,[MTMP]          ; low * high, into the high byte only
        LD   R3,[MTMP+3]
        MUL  R2,R3
        MOV  R2,XL
        ADD  R1,R2
        LD   R2,[MTMP+1]        ; high * low, likewise
        LD   R3,[MTMP+2]
        MUL  R2,R3
        MOV  R2,XL
        ADD  R1,R2
        RET
