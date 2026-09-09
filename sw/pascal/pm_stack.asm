; ---------------------------------------------------------------------
; sw/pascal/pm_stack.asm -- P-Machine Evaluation Stack & Fetch Helpers
; ---------------------------------------------------------------------

pm_push:
        PUSH R2
        PUSH R3
        LDW  X,#PM_SP
        LD   R2,[X]
        LD   R3,[X+1]
        SUB  R2,#2
        SBC  R3,#0
        ST   [X],R2
        ST   [X+1],R3
        MOV  XH,R3
        MOV  XL,R2
        ST   [X],R0
        ST   [X+1],R1
        POP  R3
        POP  R2
        RET

pm_pop:
        PUSH R2
        PUSH R3
        LDW  X,#PM_SP
        LD   R2,[X]
        LD   R3,[X+1]
        MOV  XH,R3
        MOV  XL,R2
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R2,#2
        ADC  R3,#0
        LDW  X,#PM_SP
        ST   [X],R2
        ST   [X+1],R3
        POP  R3
        POP  R2
        RET

pm_fetch_b:
        LDW  X,#PM_SEGB
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#PM_IPC
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]

        ADD  R2,#1
        ADC  R3,#0
        ST   [Y],R2
        ST   [Y+1],R3
        RET

pm_fetch_w:
        LDW  X,#PM_SEGB
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#PM_IPC
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X+]
        LD   R1,[X]

        ADD  R2,#2
        ADC  R3,#0
        ST   [Y],R2
        ST   [Y+1],R3
        RET

pm_fetch_big:
        CALL pm_fetch_b
        TST  R0
        BPL  .fb_small
        AND  R0,#$7F
        PUSH R0                 ; Save high byte on stack
        CALL pm_fetch_b         ; Low byte in R0 (clobbers R1)
        POP  R1                 ; Restore high byte into R1
        RET
.fb_small:
        CLR  R1
        RET
