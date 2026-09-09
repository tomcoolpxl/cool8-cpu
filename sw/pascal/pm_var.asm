; ---------------------------------------------------------------------
; sw/pascal/pm_var.asm -- P-Machine Variable Loads, Stores, & Constants
; ---------------------------------------------------------------------

pm_local_addr:
        SHL  R0
        ROL  R1
        ADD  R0,#10
        ADC  R1,#0
        LDW  X,#PM_MP
        LD   R2,[X]
        LD   R3,[X+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        RET

pm_global_addr:
        SHL  R0
        ROL  R1
        ADD  R0,#10
        ADC  R1,#0
        LDW  X,#PM_BP
        LD   R2,[X]
        LD   R3,[X+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        RET

pm_intermediate_mp:
        LDW  X,#PM_MP
        LD   R2,[X]
        LD   R3,[X+1]
.im_lp: TST  R0
        BEQ  .im_done
        MOV  XH,R3
        MOV  XL,R2
        LD   R2,[X]             ; [p + 0] = MS_STAT (static link)
        LD   R3,[X+1]
        SUB  R0,#1
        BRA  .im_lp
.im_done:
        RET

pm_op_sldc:
        LDW  X,#PM_OP
        LD   R0,[X]
        CLR  R1
        JMP  pm_push

pm_op_ldcn:
        CLR  R0
        CLR  R1
        JMP  pm_push

pm_op_ldci:
        CALL pm_fetch_w
        JMP  pm_push

pm_op_ldc:
        CALL pm_fetch_b         ; Word count in R0
        PUSH R0                 ; Save word count on stack

        ; Word-align IPC: IPC = (IPC + 1) & (~1)
        LDW  Y,#PM_IPC
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R0,#1
        ADC  R1,#0
        AND  R0,#$FE
        ST   [Y],R0
        ST   [Y+1],R1

.ldc_lp:
        POP  R2                 ; R2 = remaining words
        TST  R2
        BEQ  .ldc_done
        SUB  R2,#1
        PUSH R2                 ; Save remaining words on stack
        CALL pm_fetch_w         ; Fetch word in R1:R0
        CALL pm_push            ; Push to evaluation stack
        BRA  .ldc_lp

.ldc_done:
        RET

pm_op_sldl:
        LDW  X,#PM_OP
        LD   R0,[X]
        SUB  R0,#215
        CLR  R1
        CALL pm_local_addr
        LD   R0,[X]
        LD   R1,[X+1]
        JMP  pm_push

pm_op_ldl:
        CALL pm_fetch_big
        CALL pm_local_addr
        LD   R0,[X]
        LD   R1,[X+1]
        JMP  pm_push

pm_op_stl:
        CALL pm_fetch_big
        CALL pm_local_addr
        PUSHW X
        CALL pm_pop
        POPW X
        ST   [X],R0
        ST   [X+1],R1
        RET

pm_op_lla:
        CALL pm_fetch_big
        CALL pm_local_addr
        MOV  R1,XH
        MOV  R0,XL
        JMP  pm_push

pm_op_sldo:
        LDW  X,#PM_OP
        LD   R0,[X]
        SUB  R0,#231
        CLR  R1
        CALL pm_global_addr
        LD   R0,[X]
        LD   R1,[X+1]
        JMP  pm_push

pm_op_ldo:
        CALL pm_fetch_big
        CALL pm_global_addr
        LD   R0,[X]
        LD   R1,[X+1]
        JMP  pm_push

pm_op_sro:
        CALL pm_fetch_big
        CALL pm_global_addr
        PUSHW X
        CALL pm_pop
        POPW X
        ST   [X],R0
        ST   [X+1],R1
        RET

pm_op_lao:
        CALL pm_fetch_big
        CALL pm_global_addr
        MOV  R1,XH
        MOV  R0,XL
        JMP  pm_push

pm_op_lod:
        CALL pm_fetch_b
        CALL pm_intermediate_mp
        PUSH R2
        PUSH R3
        CALL pm_fetch_big
        SHL  R0
        ROL  R1
        ADD  R0,#10
        ADC  R1,#0
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]
        LD   R1,[X+1]
        JMP  pm_push

pm_op_str:
        CALL pm_fetch_b
        CALL pm_intermediate_mp
        PUSH R2
        PUSH R3
        CALL pm_fetch_big
        SHL  R0
        ROL  R1
        ADD  R0,#10
        ADC  R1,#0
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        PUSHW X
        CALL pm_pop
        POPW X
        ST   [X],R0
        ST   [X+1],R1
        RET

pm_op_lda:
        CALL pm_fetch_b
        CALL pm_intermediate_mp
        PUSH R2
        PUSH R3
        CALL pm_fetch_big
        SHL  R0
        ROL  R1
        ADD  R0,#10
        ADC  R1,#0
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        JMP  pm_push

pm_op_sind:
        LDW  X,#PM_OP
        LD   R0,[X]
        SUB  R0,#248            ; 0..7 words
        SHL  R0                 ; 0..14 bytes
        CLR  R1
        PUSH R0
        PUSH R1
        CALL pm_pop             ; Address in R1:R0
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]
        LD   R1,[X+1]
        JMP  pm_push

pm_op_ind:
        CALL pm_fetch_big       ; Words in R1:R0
        SHL  R0                 ; Bytes in R1:R0
        ROL  R1
        PUSH R0
        PUSH R1
        CALL pm_pop             ; Address in R1:R0
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]
        LD   R1,[X+1]
        JMP  pm_push

pm_op_sto:
        CALL pm_pop
        PUSH R0
        PUSH R1
        CALL pm_pop
        MOV  XH,R1
        MOV  XL,R0
        POP  R1
        POP  R0
        ST   [X],R0
        ST   [X+1],R1
        RET

pm_op_ldm:
        CALL pm_fetch_b         ; Word count in R0 (unsigned byte)
        TST  R0
        BNE  .ldm_start
        JMP  pm_pop             ; Word count 0: just pop source pointer
.ldm_start:
        PUSH R0                 ; Save Word count
        CALL pm_pop             ; Source pointer in R1:R0
        POP  R2                 ; Word count in R2
        ; Compute EndPtr = Source + WordCount * 2 in PM_TMP1
        MOV  R3,R2              ; Word count
        SHL  R3                 ; Bytes to add (WordCount * 2)
        ADD  R0,R3
        ADC  R1,#0              ; R1:R0 is EndPtr
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

.ldm_loop:
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#2
        SBC  R1,#0
        ST   [Y],R0
        ST   [Y+1],R1
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]
        LD   R1,[X+1]
        PUSH R2                 ; Save counter
        CALL pm_push            ; Push word on stack
        POP  R2
        SUB  R2,#1
        BNE  .ldm_loop
        RET

pm_op_stm:
        CALL pm_fetch_b         ; Word count in R0
        TST  R0
        BNE  .stm_start
        JMP  pm_pop             ; Word count 0: just pop Dest pointer
.stm_start:
        PUSH R0                 ; Save Word count
        ; Dest pointer is buried at SP + 2 * WordCount
        MOV  R2,R0
        SHL  R2                 ; Offset in bytes = 2 * WordCount
        LDW  Y,#PM_SP
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R0,R2
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]             ; Dest low
        LD   R1,[X+1]           ; Dest high
        ; Save Dest pointer in PM_TMP0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1
        POP  R2                 ; Word count in R2

.stm_loop:
        PUSH R2                 ; Save counter
        CALL pm_pop             ; Pop word from stack (word 0, then 1, ...)
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        MOV  XH,R3
        MOV  XL,R2
        ST   [X+],R0
        ST   [X+],R1            ; Store word and advance Dest by 2
        MOV  R0,XL
        MOV  R1,XH
        ST   [Y],R0
        ST   [Y+1],R1
        POP  R2
        SUB  R2,#1
        BNE  .stm_loop

        ; Finally pop the Dest pointer itself off the stack
        JMP  pm_pop

pm_op_ldb:
        CALL pm_pop             ; Byte index in R1:R0
        PUSH R0
        PUSH R1
        CALL pm_pop             ; Base pointer in R1:R0
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]
        CLR  R1
        JMP  pm_push

pm_op_stb:
        CALL pm_pop             ; Byte value in R1:R0 (low byte in R0)
        PUSH R0
        CALL pm_pop             ; Byte index in R1:R0
        PUSH R0
        PUSH R1
        CALL pm_pop             ; Base pointer in R1:R0
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        POP  R0                 ; Byte value
        ST   [X],R0
        RET

pm_op_mov:
        CALL pm_fetch_big       ; Word count in R1:R0
        SHL  R0                 ; Byte count in R1:R0
        ROL  R1
        LDW  Y,#PM_TMP0
        ST   [Y],R0             ; Byte count low
        ST   [Y+1],R1           ; Byte count high

        CALL pm_pop             ; Src in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Dst in R1:R0
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1

        LDW  Y,#PM_TMP0
        LD   R2,[Y]             ; Byte count low
        LD   R3,[Y+1]           ; Byte count high

        ; Y = Src, X = Dst
        LDW  X,#PM_TMP1
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  YH,R1
        MOV  YL,R0

        LDW  X,#PM_TMP2
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XH,R1
        MOV  XL,R0

.mov_lp:
        MOV  R0,R2
        OR   R0,R3
        BEQ  .mov_done
        LD   R0,[Y+]
        ST   [X+],R0
        SUB  R2,#1
        SBC  R3,#0
        BRA  .mov_lp

.mov_done:
        RET

pm_op_lae:
        CALL pm_fetch_b         ; SegNo in R0
        PUSH R0
        CALL pm_fetch_big       ; Offset in R1:R0
        SHL  R0
        ROL  R1
        POP  R2                 ; SegNo in R2
        PUSH R0
        PUSH R1
        MOV  R0,R2
        SHL  R0
        SHL  R0
        SHL  R0                 ; 8 * SegNo
        CLR  R1
        LDW  X,#PM_SEG_DICT + 4
        ADDW X,R0
        LD   R0,[X+]            ; Seg low
        LD   R1,[X+]            ; Seg high
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        JMP  pm_push

pm_op_lde:
        CALL pm_fetch_b         ; SegNo in R0
        PUSH R0
        CALL pm_fetch_big       ; Offset in R1:R0
        SHL  R0
        ROL  R1
        POP  R2                 ; SegNo in R2
        PUSH R0
        PUSH R1
        MOV  R0,R2
        SHL  R0
        SHL  R0
        SHL  R0
        CLR  R1
        LDW  X,#PM_SEG_DICT + 4
        ADDW X,R0
        LD   R0,[X+]
        LD   R1,[X+]
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]
        LD   R1,[X+1]
        JMP  pm_push

pm_op_ste:
        CALL pm_fetch_b         ; SegNo in R0
        PUSH R0
        CALL pm_fetch_big       ; Offset in R1:R0
        SHL  R0
        ROL  R1
        POP  R2                 ; SegNo in R2
        PUSH R0
        PUSH R1
        MOV  R0,R2
        SHL  R0
        SHL  R0
        SHL  R0
        CLR  R1
        LDW  X,#PM_SEG_DICT + 4
        ADDW X,R0
        LD   R0,[X+]
        LD   R1,[X+]
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        PUSHW X
        CALL pm_pop             ; Pop Value in R1:R0
        POPW X
        ST   [X],R0
        ST   [X+1],R1
        RET
