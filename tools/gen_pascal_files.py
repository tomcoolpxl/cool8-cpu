import os

files = {}

files["sw/pascal/pm_stack.asm"] = """\
; ---------------------------------------------------------------------
; sw/pascal/pm_stack.asm -- P-Machine Evaluation Stack & Fetch Helpers
; ---------------------------------------------------------------------

pm_push:
        PUSH R2
        LDW  X,#PM_SP
        LD   R2,[X]
        SUB  R2,#2
        ST   [X],R2
        LD   R2,[X+1]
        SBC  R2,#0
        ST   [X+1],R2
        MOV  XH,R2
        LD   R2,[X-1]
        MOV  XL,R2
        ST   [X],R0
        ST   [X+1],R1
        POP  R2
        RET

pm_pop:
        PUSH R2
        LDW  X,#PM_SP
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  X,#PM_SP
        LD   R2,[X]
        ADD  R2,#2
        ST   [X],R2
        LD   R2,[X+1]
        ADC  R2,#0
        ST   [X+1],R2
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
        CALL pm_fetch_b
        PUSH R0
        CALL pm_fetch_b
        MOV  R1,R0
        POP  R0
        RET

pm_fetch_big:
        CALL pm_fetch_b
        CMP  R0,#$80
        BLO  .pb_small
        AND  R0,#$7F
        PUSH R0
        CALL pm_fetch_b
        MOV  R2,R0
        POP  R1
        MOV  R0,R2
        RET
.pb_small:
        CLR  R1
        RET
"""

for path, content in files.items():
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
print("Batch 1 written.")
