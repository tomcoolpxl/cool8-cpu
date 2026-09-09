; ---------------------------------------------------------------------
; z3_branch.asm -- Z-Machine branch condition evaluation & jumps
; ---------------------------------------------------------------------

; z_eval_branch -- evaluates branch on condition R0 (0=FALSE, 1=TRUE)
z_eval_branch:
        PUSH R0                 ; save condition
        CALL z_fetch_pc_byte
        MOV  R1,R0              ; R1 = branch byte 1
        POP  R0                 ; R0 = condition

        ; Bit 7 of R1: 1 = branch on TRUE, 0 = branch on FALSE
        MOV  R2,R1
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2                 ; R2 = bit 7 (0 or 1)

        ; Condition match: (R0 == R2)
        CMP  R0,R2
        BEQ  .taken

        ; Not taken: skip second byte if 2-byte branch (bit 6 == 0)
        BTST R1,#$40
        BNE  .notaken
        CALL z_fetch_pc_byte    ; skip byte 2
.notaken:
        RET

.taken: ; Branch IS taken!
        BTST R1,#$40
        BEQ  .two_byte

        ; Single-byte branch: offset = R1 & $3F (unsigned 0..63)
        AND  R1,#$3F
        CLR  R2                 ; R2:R1 = offset
        BRA  .do_jump

.two_byte:
        ; Two-byte branch: offset = ((R1 & $3F) << 8) | byte2 (signed 14-bit)
        AND  R1,#$3F
        PUSH R1
        CALL z_fetch_pc_byte
        MOV  R2,R0              ; R2 = byte 2 (low byte)
        POP  R1                 ; R1 = high byte
        ; Check sign bit (bit 5 of original byte 1, now bit 5 of R1)
        BTST R1,#$20
        BEQ  .pos14
        OR   R1,#$C0            ; sign-extend to 16 bits
.pos14: ; Offset in R1:R2 (R1=high, R2=low)
        PUSH R1
        MOV  R1,R2
        POP  R2

.do_jump:
        ; Check special offsets 0 (rfalse) and 1 (rtrue)
        TST  R2
        BNE  .rel_jump
        TST  R1
        BEQ  .do_rfalse
        CMP  R1,#1
        BEQ  .do_rtrue

.rel_jump:
        ; Target PC = Z_PC + offset - 2
        SUB  R1,#2
        SBC  R2,#0

        ; Sign extend R2 into R3 for 24-bit arithmetic
        MOV  R3,R2
        BTST R3,#$80
        BEQ  .pos_pc
        MOV  R3,#$FF
        BRA  .add_pc
.pos_pc:CLR  R3
.add_pc:
        LDW  Y,#Z_PC_L
        LD   R0,[Y]             ; low
        ADD  R0,R1
        ST   [Y],R0
        LD   R0,[Y+1]           ; mid
        ADC  R0,R2
        ST   [Y+1],R0
        LD   R0,[Y+2]           ; high
        ADC  R0,R3
        ST   [Y+2],R0
        RET

.do_rfalse:
        LDW  X,#0
        JMP  z_ret

.do_rtrue:
        LDW  X,#1
        JMP  z_ret
