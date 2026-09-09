; ---------------------------------------------------------------------
; z3_stack.asm -- Z-Machine stack, call frames, and variable access
; ---------------------------------------------------------------------

; z_push -- pushes 16-bit word X to evaluation stack
z_push:
        PUSHW Y
        LDW  Y,#Z_SP
        LD   R0,[Y]
        LD   R1,[Y+1]
        PUSHW X
        LDW  X,#Z_STACK_BASE
        ADDW X,R0
        POPW Y                  ; Y = value X
        MOV  R2,YH
        ST   [X],R2
        MOV  R2,YL
        ST   [X+1],R2
        ADD  R0,#2
        ADC  R1,#0
        LDW  X,#Z_SP
        ST   [X],R0
        ST   [X+1],R1
        POPW Y
        RET

; z_pop -- pops 16-bit word from evaluation stack -> X
z_pop:
        PUSHW Y
        LDW  Y,#Z_SP
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#2
        SBC  R1,#0
        ST   [Y],R0
        ST   [Y+1],R1
        LDW  X,#Z_STACK_BASE
        ADDW X,R0
        LD   R1,[X]             ; high byte
        LD   R0,[X+1]           ; low byte
        MOV  XH,R1
        MOV  XL,R0
        POPW Y
        RET

; z_read_var -- reads variable R0 -> 16-bit word X
z_read_var:
        TST  R0
        BNE  .notstk
        JMP  z_pop
.notstk:CMP  R0,#16
        BHS  .isglob
        ; Local variable (1..15) -> current frame: Z_CALL_BASE + Z_FP + 9 + (R0 - 1) * 2
        SUB  R0,#1
        ADD  R0,R0
        ADD  R0,#9              ; R0 = 9 + (var - 1) * 2
        LDW  Y,#Z_FP
        LD   R1,[Y]
        LD   R2,[Y+1]
        ADD  R1,R0
        ADC  R2,#0
        MOV  XL,R1
        MOV  XH,R2
        ADDW X,#Z_CALL_BASE
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        RET

.isglob:; Global variable (16..255) -> Globals Base + (R0 - 16) * 2
        SUB  R0,#16
        CLR  R1
        SHL  R0
        ROL  R1                 ; R1:R0 = (var - 16) * 2
        LDW  Y,#Z_GLOBS
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XL,R0
        MOV  XH,R1
        CLR  R1
        JMP  z_read_word

; z_write_var -- writes 16-bit word X to variable R0
z_write_var:
        TST  R0
        BNE  .wntstk
        JMP  z_push
.wntstk:CMP  R0,#16
        BHS  .wglob
        ; Local variable (1..15)
        PUSHW X
        SUB  R0,#1
        ADD  R0,R0
        ADD  R0,#9
        LDW  Y,#Z_FP
        LD   R1,[Y]
        LD   R2,[Y+1]
        ADD  R1,R0
        ADC  R2,#0
        MOV  XL,R1
        MOV  XH,R2
        ADDW X,#Z_CALL_BASE
        POPW Y                  ; Y = value X
        MOV  R1,YH
        ST   [X],R1
        MOV  R1,YL
        ST   [X+1],R1
        RET

.wglob: ; Global variable (16..255)
        PUSHW X
        SUB  R0,#16
        CLR  R1
        SHL  R0
        ROL  R1
        LDW  Y,#Z_GLOBS
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XL,R0
        MOV  XH,R1
        POPW Y                  ; Y = value
        MOV  R1,YH
        MOV  R0,YL
        JMP  z_write_word

; z_call -- routine call to packed address in Z_OP0
z_call:
        LDW  Y,#Z_OP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R0
        MOV  XL,R1
        OR   R0,R1
        BNE  .do_call
        ; Address is 0: store FALSE (0) in result variable
        LDW  X,#Z_RESVAR
        LD   R0,[X]
        LDW  X,#0
        JMP  z_write_var

.do_call:
        ; Calculate byte address = Z_OP0 * 2
        CLR  R0
        MOV  R3,XL
        MOV  R2,XH
        SHL  R3
        ROL  R2
        ROL  R0                 ; R0:R2:R3 = 24-bit routine byte address
        MOV  XL,R3
        MOV  XH,R2
        MOV  R1,R0

        ; Fetch number of locals at routine address
        PUSH R1
        PUSHW X
        CALL z_read_byte        ; R0 = local count (0..15)
        MOV  R2,R0              ; R2 = num_locals
        POPW X
        POP  R1
        INCW X
        BNE  .adv1
        ADD  R1,#1
.adv1:  ; R1:X = story address of local defaults ($572D), R2 = num_locals (3)
        PUSH R1
        PUSHW X
        PUSH R2

        ; Calculate new frame base Y = Z_CALL_BASE + new_FP
        LDW  Y,#Z_CALL_DEPTH
        LD   R0,[Y]
        TST  R0
        BEQ  .fbase0
        LDW  Y,#Z_FP
        LD   R0,[Y]
        LD   R3,[Y+1]
        ADD  R0,#39
        ADC  R3,#0
        BRA  .fbaseset
.fbase0:CLR  R0
        CLR  R3
.fbaseset:
        MOV  YL,R0
        MOV  YH,R3
        ADDW Y,#Z_CALL_BASE     ; Y = new frame base

        ; Frame header:
        ; [Y+0..2] = Z_PC_L, Z_PC_M, Z_PC_H
        ; [Y+3..4] = caller Z_FP
        ; [Y+5]    = caller num_locals (R2)
        ; [Y+6]    = Z_RESVAR
        ; [Y+7..8] = Z_SP at call time
        LDW  X,#Z_PC_L
        LD   R0,[X]
        ST   [Y],R0
        LD   R0,[X+1]
        ST   [Y+1],R0
        LD   R0,[X+2]
        ST   [Y+2],R0

        LDW  X,#Z_FP
        LD   R0,[X]
        ST   [Y+3],R0
        LD   R0,[X+1]
        ST   [Y+4],R0

        POP  R0
        PUSH R0
        ST   [Y+5],R0

        LDW  X,#Z_RESVAR
        LD   R0,[X]
        ST   [Y+6],R0

        LDW  X,#Z_SP
        LD   R0,[X]
        ST   [Y+7],R0
        LD   R0,[X+1]
        ST   [Y+8],R0

        ; Set Z_FP = new_FP
        LDW  X,#Z_CALL_DEPTH
        LD   R0,[X]
        TST  R0
        BEQ  .fpu0
        LDW  X,#Z_FP
        LD   R0,[X]
        LD   R3,[X+1]
        ADD  R0,#39
        ADC  R3,#0
        ST   [X],R0
        ST   [X+1],R3
        BRA  .fpudone
.fpu0:  LDW  X,#Z_FP
        CLR  R0
        ST   [X],R0
        ST   [X+1],R0
.fpudone:
        LDW  X,#Z_CALL_DEPTH
        LD   R0,[X]
        ADD  R0,#1
        ST   [X],R0

        POP  R2                 ; R2 = num_locals
        POPW X                  ; X = story address of local defaults ($572D)
        POP  R1                 ; R1 = story high byte

        ; Read default local values from story file into [Y+9..]
        ; Y = frame base, R1:X = story address of local defaults
        CLR  R3                 ; local index 0..14
.rd_loc:CMP  R3,R2
        BHS  .done_loc
        PUSH R1
        PUSHW X
        PUSH R2
        PUSH R3
        PUSHW Y
        CALL z_read_word        ; X = 16-bit default local value
        MOVW Y,X                ; Y = value
        POPW X                  ; X = frame base
        POP  R3
        POP  R2

        ; Write local value to frame: X + 9 + R3*2
        PUSHW X
        ADDW X,#9
        MOV  R0,R3
        ADD  R0,R0
        ADDW X,R0
        MOV  R0,YH
        ST   [X],R0
        MOV  R0,YL
        ST   [X+1],R0
        POPW Y                  ; Y = frame base

        POPW X                  ; restore story pointer X
        POP  R1                 ; restore story pointer R1
        INCW X
        INCW X
        BNE  .adv2
        ADD  R1,#1
.adv2:  ADD  R3,#1
        BRA  .rd_loc

.done_loc:
        ; Routine code starts at R1:X. Update Z_PC
        LDW  Y,#Z_PC_L
        MOV  R0,XL
        ST   [Y],R0
        MOV  R0,XH
        ST   [Y+1],R0
        ST   [Y+2],R1

        ; Overwrite passed arguments into local variables
        LDW  X,#Z_OPCOUNT
        LD   R0,[X]
        SUB  R0,#1              ; R0 = num_args passed
        BEQ  .no_args
        CLR  R3                 ; arg index 0..num_args-1
.arg_lp:CMP  R3,R0
        BHS  .no_args
        CMP  R3,R2              ; do not exceed local count
        BHS  .no_args
        ; Read Z_OP(R3+1)
        MOV  R1,R3
        ADD  R1,#1
        ADD  R1,R1              ; R1 = (R3+1) * 2
        LDW  X,#Z_OP0
        ADDW X,R1
        LD   R1,[X]             ; high byte
        LD   R0,[X+1]           ; low byte
        ; Write to frame local
        PUSH R0                 ; save low byte
        PUSH R2                 ; save num_locals
        PUSH R3                 ; save arg index
        MOV  R0,R3
        ADD  R0,R0
        LDW  Y,#Z_FP
        LD   R2,[Y]
        LD   R3,[Y+1]
        MOV  XL,R2
        MOV  XH,R3
        ADDW X,#Z_CALL_BASE+9
        ADDW X,R0
        ST   [X],R1             ; store high byte
        POP  R3                 ; restore arg index
        POP  R2                 ; restore num_locals
        POP  R0                 ; restore low byte
        ST   [X+1],R0           ; store low byte
        LDW  X,#Z_OPCOUNT
        LD   R0,[X]
        SUB  R0,#1              ; restore R0 = num_args passed
        ADD  R3,#1
        BRA  .arg_lp

.no_args:
        RET

; z_ret -- returns value in X from routine
z_ret:
        LDW  Y,#Z_CALL_DEPTH
        LD   R0,[Y]
        TST  R0
        BNE  .has_caller
        ; Top-level return -> finish program
        LDW  X,#Z_QUIT
        MOV  R0,#1
        ST   [X],R0
        RET

.has_caller:
        PUSHW X                 ; Preserve return value X
        SUB  R0,#1
        ST   [Y],R0

        ; Read frame header from Z_CALL_BASE + Z_FP
        LDW  Y,#Z_FP
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  YL,R0
        MOV  YH,R1
        ADDW Y,#Z_CALL_BASE     ; Y = current frame base

        ; Restore Z_PC: [Y+0..2]
        LDW  X,#Z_PC_L
        LD   R0,[Y]
        ST   [X],R0
        LD   R0,[Y+1]
        ST   [X+1],R0
        LD   R0,[Y+2]
        ST   [X+2],R0

        ; Restore Z_SP: [Y+7..8]
        LDW  X,#Z_SP
        LD   R0,[Y+7]
        ST   [X],R0
        LD   R0,[Y+8]
        ST   [X+1],R0

        ; Read result destination variable: [Y+6]
        LD   R0,[Y+6]

        ; Restore caller Z_FP: [Y+3..4]
        LD   R1,[Y+3]
        LD   R2,[Y+4]
        LDW  Y,#Z_FP
        ST   [Y],R1
        ST   [Y+1],R2

        POPW X                  ; Restore return value X

        ; Write return value X to variable R0
        JMP  z_write_var
