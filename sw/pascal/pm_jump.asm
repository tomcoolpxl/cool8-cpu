; ---------------------------------------------------------------------
; sw/pascal/pm_jump.asm -- P-Machine Control Flow & Case Jump Opcodes
; ---------------------------------------------------------------------

pm_jump_calc:
        BTST R0,#$80
        BNE  .jp_back
        CLR  R1
        LDW  X,#PM_IPC
        LD   R2,[X]
        LD   R3,[X+1]
        ADD  R0,R2
        ADC  R1,R3
        RET

.jp_back:
        CLR  R2
        SUB  R2,R0
        MOV  R0,R2              ; R0 = d = -disp
        PUSH R0                 ; Save d

        ; w2 = MemRd(JTab - d)
        LDW  X,#PM_JTAB
        LD   R2,[X]
        LD   R3,[X+1]
        CLR  R1
        SUB  R2,R0
        SBC  R3,R1
        MOV  XH,R3
        MOV  XL,R2
        LD   R2,[X]             ; w2 low
        LD   R3,[X+1]           ; w2 high
        POP  R0                 ; d
        PUSH R0
        ADD  R2,R0              ; w2 + d
        ADC  R3,#0
        LDW  Y,#PM_TMP0
        ST   [Y],R2             ; (w2 + d) low
        ST   [Y+1],R3           ; (w2 + d) high

        ; w1 = MemRd(JTab - 2)
        LDW  X,#PM_JTAB
        LD   R0,[X]
        LD   R1,[X+1]
        SUB  R0,#2
        SBC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]             ; w1 low
        LD   R1,[X+1]           ; w1 high
        ADD  R0,#2              ; w1 + 2
        ADC  R1,#0

        ; Result = (w1 + 2) - (w2 + d)
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        SUB  R0,R2
        SBC  R1,R3
        POP  R2                 ; Balance stack
        RET

pm_op_ujp:
        CALL pm_fetch_b
        CALL pm_jump_calc
        LDW  X,#PM_IPC
        ST   [X],R0
        ST   [X+1],R1
        RET

pm_op_fjp:
        CALL pm_fetch_b
        PUSH R0
        CALL pm_pop
        POP  R2
        BTST R0,#$01
        BNE  .fjp_true
        MOV  R0,R2
        CALL pm_jump_calc
        LDW  X,#PM_IPC
        ST   [X],R0
        ST   [X+1],R1
.fjp_true:
        RET

pm_op_efj:
        CALL pm_fetch_b         ; Jump offset in R0
        PUSH R0                 ; Save offset
        CALL pm_pop             ; Val1 in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1
        CALL pm_pop             ; Val2 in R1:R0
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        CMP  R0,R2
        BNE  .efj_do_jump
        CMP  R1,R3
        BNE  .efj_do_jump
        POP  R0                 ; Discard offset (no jump)
        RET

.efj_do_jump:
        POP  R0                 ; Restore offset
        CALL pm_jump_calc
        LDW  X,#PM_IPC
        ST   [X],R0
        ST   [X+1],R1
        RET

pm_op_nfj:
        CALL pm_fetch_b         ; Jump offset in R0
        PUSH R0                 ; Save offset
        CALL pm_pop             ; Val1 in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1
        CALL pm_pop             ; Val2 in R1:R0
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        CMP  R0,R2
        BNE  .nfj_no_jump
        CMP  R1,R3
        BNE  .nfj_no_jump
        POP  R0                 ; Restore offset
        CALL pm_jump_calc
        LDW  X,#PM_IPC
        ST   [X],R0
        ST   [X+1],R1
        RET

.nfj_no_jump:
        POP  R0                 ; Discard offset (no jump)
        RET

pm_op_xjp:
        ; Align IPC to word boundary
        LDW  X,#PM_IPC
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R0,#1
        ADC  R1,#0
        AND  R0,#$FE
        ST   [X],R0
        ST   [X+1],R1

        CALL pm_fetch_w         ; Lo in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_fetch_w         ; Hi in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Val in R1:R0
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1

        ; Check if Lo <= Val <= Hi
        ; Val - Lo
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        SUB  R0,R2
        SBC  R1,R3
        BMI  .xjp_out           ; Val < Lo -> out of range

        ; Hi - Val
        LDW  Y,#PM_TMP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R2,R0
        SBC  R3,R1
        BMI  .xjp_out           ; Val > Hi -> out of range

        ; In range: Table entry at IPC + 2 * (Val - Lo)
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        SUB  R0,R2
        SBC  R1,R3
        SHL  R0
        ROL  R1
        LDW  X,#PM_IPC
        LD   R2,[X]
        LD   R3,[X+1]
        ADD  R0,R2
        ADC  R1,R3
        ADD  R0,#2              ; Skip 2-byte default jump instruction (UJP)
        ADC  R1,#0
        ST   [X],R0             ; PM_IPC = entry_offset
        ST   [X+1],R1

        ; Read jump displacement self-relative from entry_offset:
        CALL pm_fetch_w         ; Disp in R1:R0, PM_IPC advanced by 2
        LDW  X,#PM_IPC
        LD   R2,[X]
        LD   R3,[X+1]
        SUB  R2,#2              ; PM_IPC = entry_offset
        SBC  R3,#0
        SUB  R2,R0              ; PM_IPC = entry_offset - Disp
        SBC  R3,R1
        ST   [X],R2
        ST   [X+1],R3
        RET

.xjp_out:
        ; Out of range: IPC is at the default jump word, execute it directly
        RET

