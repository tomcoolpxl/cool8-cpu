; ---------------------------------------------------------------------
; sw/pascal/pm_seg.asm -- Segment Dictionary & Dynamic Segment Loader
; ---------------------------------------------------------------------

pm_init_seg_table:
        ; Clear 16 entries in Segment Dictionary (128 bytes at $2180)
        LDW  X,#PM_SEG_DICT
        MOV  R0,#128
        CLR  R1
.is_lp: ST   [X+],R1
        SUB  R0,#1
        BNE  .is_lp

        ; Read block 186 (SYSTEM.PASCAL Segment Dictionary) into PM_SEC_BUF ($2200)
        ; Flash address = $790000 + 186 * 512 = $7A7400
        CLR  R0
        ST   [FLS_CTRL],R0
        ST   [FLS_ADDR_L],R0
        MOV  R0,#$74
        ST   [FLS_ADDR_M],R0
        MOV  R0,#$7A
        ST   [FLS_ADDR_H],R0
        MOV  R0,#1
        ST   [FLS_CTRL],R0

        LDW  X,#PM_SEC_BUF
        MOV  R2,#<512
        MOV  R3,#>512
.is_rd: MOV  R0,R2
        OR   R0,R3
        BEQ  .is_done
        LD   R0,[FLS_DATA]
        ST   [X+],R0
        SUB  R2,#1
        SBC  R3,#0
        BRA  .is_rd
.is_done:
        CLR  R0
        ST   [FLS_CTRL],R0
        RET

pm_init_syscom_segments:
        ; Parse 16 segment entries from PM_SEC_BUF into SYSCOM
        ; SYSCOM + 96 + 6 * SegNo
        CLR  R0                 ; index i = 0..15
.is_seg_lp:
        PUSH R0
        ; Read CodeAddr at [PM_SEC_BUF + 4 * i]
        MOV  R1,R0
        SHL  R1
        SHL  R1
        MOV  R0,R1
        CLR  R1
        LDW  X,#PM_SEC_BUF
        ADDW X,R0
        LD   R2,[X+]            ; CodeAddr low
        LD   R3,[X+]            ; CodeAddr high
        LDW  Y,#PM_TMP0
        ST   [Y],R2
        ST   [Y+1],R3
        LD   R0,[X+]            ; CodeLeng low
        LD   R1,[X+]            ; CodeLeng high
        ST   [Y+2],R0
        ST   [Y+3],R1

        ; If CodeLeng == 0 -> skip
        MOV  R2,R0
        OR   R2,R1
        BEQ  .is_nxt_seg

        ; Absolute block = 186 + CodeAddr
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R2,#<186
        ADC  R3,#>186
        ST   [Y],R2             ; Abs Block
        ST   [Y+1],R3

        ; Read SegInfo at [PM_SEC_BUF + $100 + 2 * i]
        POP  R0
        PUSH R0
        SHL  R0
        CLR  R1
        LDW  X,#PM_SEC_BUF + $100
        ADDW X,R0
        LD   R2,[X+]            ; SegInfo low = SegNo
        LD   R3,[X+]            ; SegInfo high

        ; Target in SYSCOM: PM_SYSCOM + 96 + 6 * SegNo
        MOV  R0,R2              ; SegNo
        MOV  R1,R0
        SHL  R1                 ; 2 * SegNo
        ADD  R1,R0              ; 3 * SegNo
        SHL  R1                 ; 6 * SegNo
        ADD  R1,#96             ; byte offset in SYSCOM
        LDW  X,#PM_SYSCOM
        LD   R2,[X]
        LD   R3,[X+1]
        ADD  R2,R1
        ADC  R3,#0
        MOV  XH,R3
        MOV  XL,R2

        ; Store SegUnit (4)
        MOV  R0,#4
        ST   [X+],R0
        CLR  R0
        ST   [X+],R0

        ; Store SegBlock
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X+],R0
        ST   [X+],R1

        ; Store SegSize
        LD   R0,[Y+2]
        LD   R1,[Y+3]
        ST   [X+],R0
        ST   [X+],R1

.is_nxt_seg:
        POP  R0
        ADD  R0,#1
        CMP  R0,#16
        BLO  .is_seg_lp
        RET

; pm_load_segment(SegNo in R0)
pm_load_segment:
        TST  R0
        BEQ  .ls_ret            ; Segment 0 is resident, never loaded
        ; Check if already loaded: SegDict[SegNo].UseCount != 0
        PUSH R0
        MOV  R1,R0
        SHL  R1
        SHL  R1
        SHL  R1                 ; 8 * SegNo
        MOV  R0,R1
        CLR  R1
        LDW  X,#PM_SEG_DICT
        ADDW X,R0
        LD   R2,[X]
        LD   R3,[X+1]
        MOV  R0,R2
        OR   R0,R3
        BEQ  .ls_do_load

        ; Already loaded: increment UseCount
        ADD  R2,#1
        ADC  R3,#0
        ST   [X],R2
        ST   [X+1],R3
        POP  R0
.ls_ret:
        RET

.ls_do_load:
        POP  R0
        PUSH R0
        ; Read SegUnit, SegBlock, SegSize from SYSCOM
        MOV  R1,R0
        SHL  R1
        ADD  R1,R0
        SHL  R1
        ADD  R1,#96
        LDW  X,#PM_SYSCOM
        LD   R2,[X]
        LD   R3,[X+1]
        ADD  R2,R1
        ADC  R3,#0
        MOV  XH,R3
        MOV  XL,R2
        ADDW X,#2
        LD   R2,[X+]            ; SegBlock low
        LD   R3,[X+]            ; SegBlock high
        LD   R0,[X+]            ; SegSize low
        LD   R1,[X+]            ; SegSize high

        LDW  Y,#PM_TMP0
        ST   [Y],R2             ; SegBlock
        ST   [Y+1],R3
        ST   [Y+2],R0           ; SegSize
        ST   [Y+3],R1

        ; Check if this is Segment 1 and fits in High RAM slot ($D358-$FDFF: 10,919 bytes)
        POP  R0
        PUSH R0
        CMP  R0,#1
        BNE  .ls_lower_ram

        ; Check if SegSize <= (PM_HIGH_SEG1_MAX - PM_HIGH_SEG1_BASE)
        LDW  Y,#PM_TMP0+2       ; SegSize
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_HIGH_SEG1_MAX - PM_HIGH_SEG1_BASE
        MOV  R2,YL
        MOV  R3,YH
        SUB  R2,R0
        SBC  R3,R1
        BMI  .ls_lower_ram      ; If too large for High RAM slot, use Lower RAM

        ; --- High RAM Slot Allocation for Segment 1 ---
        ; SegBase = PM_HIGH_SEG1_BASE ($D358)
        ; Seg = PM_HIGH_SEG1_BASE + SegSize - 2
        ; OldKp = 0 (permanent/fixed, does not alter Lower RAM PM_KP)
        POP  R0
        PUSH R0
        MOV  R1,R0
        SHL  R1
        SHL  R1
        SHL  R1
        MOV  R0,R1
        CLR  R1
        LDW  X,#PM_SEG_DICT
        ADDW X,R0

        MOV  R0,#1
        ST   [X+],R0            ; UseCount = 1
        CLR  R0
        ST   [X+],R0
        ST   [X+],R0            ; OldKp low = 0
        ST   [X+],R0            ; OldKp high = 0

        LDW  Y,#PM_HIGH_SEG1_BASE
        MOV  R0,YL
        MOV  R1,YH
        LDW  Y,#PM_TMP0+2       ; SegSize
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        SUB  R0,#2
        SBC  R1,#0
        ST   [X+],R0            ; Seg low
        ST   [X+],R1            ; Seg high

        LDW  Y,#PM_HIGH_SEG1_BASE
        MOV  R0,YL
        MOV  R1,YH
        ST   [X+],R0            ; SegBase low
        ST   [X+],R1            ; SegBase high

        LDW  X,#PM_HIGH_SEG1_BASE ; Load target buffer
        BRA  .ls_do_read

.ls_lower_ram:
        ; Allocate in memory: NewKP = PM_KP - SegSize
        LDW  Y,#PM_TMP0+2       ; SegSize
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_KP
        LD   R2,[Y]
        LD   R3,[Y+1]
        SUB  R2,R0
        SBC  R3,R1

        ; Guard: NewKP must be >= PM_HEAP_BASE + 512 ($3200)
        LDW  Y,#PM_HEAP_BASE + 512
        MOV  R0,YL
        MOV  R1,YH
        PUSH R2
        PUSH R3
        CMP  R2,R0
        SBC  R3,R1
        POP  R3
        POP  R2
        BCS  .ls_kp_ok
        ; Out of memory error
        HALT

.ls_kp_ok:
        LDW  Y,#PM_KP
        ST   [Y],R2
        ST   [Y+1],R3

        ; SegDict[SegNo]:
        ; UseCount = 1, OldKp = old_KP, Seg = OldKp - 2, SegBase = NewKP
        POP  R0
        PUSH R0
        MOV  R1,R0
        SHL  R1
        SHL  R1
        SHL  R1
        MOV  R0,R1
        CLR  R1
        LDW  X,#PM_SEG_DICT
        ADDW X,R0

        MOV  R0,#1
        ST   [X+],R0            ; UseCount = 1
        CLR  R0
        ST   [X+],R0

        LDW  Y,#PM_KP           ; OldKp was PM_KP + SegSize
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP0+2
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        ST   [X+],R0            ; OldKp low
        ST   [X+],R1            ; OldKp high
        ; If SegBlock != 0 -> Code Segment: Seg = OldKp - 2
        ; If SegBlock == 0 -> Data Segment: Seg = NewKP - 2
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        OR   R0,R1
        BEQ  .ls_data_seg

        ; Code segment: Seg = OldKp - 2
        LDW  Y,#PM_KP
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP0+2
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        SUB  R0,#2
        SBC  R1,#0
        ST   [X+],R0            ; Seg
        ST   [X+],R1

        ; SegBase = NewKP
        LDW  Y,#PM_KP
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X+],R0            ; SegBase
        ST   [X+],R1

        MOV  XH,R1
        MOV  XL,R0

.ls_do_read:
        MOV  R0,XL
        MOV  R1,XH
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1

        LDW  Y,#PM_TMP0+2
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_disk_read
        POP  R0
        RET

.ls_data_seg:
        ; Data segment: Seg = NewKP - 2
        LDW  Y,#PM_KP
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#2
        SBC  R1,#0
        ST   [X+],R0            ; Seg
        ST   [X+],R1
        LDW  Y,#PM_KP
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X+],R0            ; SegBase
        ST   [X+],R1
        POP  R0
        RET

; pm_unload_segment(SegNo in R0)
pm_unload_segment:
        TST  R0
        BEQ  .uls_done           ; Segment 0 is never unloaded
        PUSH R0
        MOV  R1,R0
        SHL  R1
        SHL  R1
        SHL  R1                 ; 8 * SegNo
        MOV  R0,R1
        CLR  R1
        LDW  X,#PM_SEG_DICT
        ADDW X,R0
        LD   R2,[X]
        LD   R3,[X+1]
        MOV  R0,R2
        OR   R0,R3
        BEQ  .uls_pop_done       ; UseCount == 0 -> done
        SUB  R2,#1
        SBC  R3,#0
        ST   [X+],R2             ; UseCount--
        ST   [X+],R3
        MOV  R0,R2
        OR   R0,R3
        BNE  .uls_pop_done       ; UseCount > 0 -> still in use
        ; Restore PM_KP from OldKp if non-zero
        LD   R0,[X+]            ; OldKp low
        LD   R1,[X+]            ; OldKp high
        MOV  R2,R0
        OR   R2,R1
        BEQ  .uls_no_kp
        LDW  Y,#PM_KP
        ST   [Y],R0
        ST   [Y+1],R1
.uls_no_kp:
        ; Clear OldKp, Seg, SegBase
        CLR  R0
        MOV  R1,#2
        SUBW X,R1
        ST   [X+],R0            ; OldKp = 0
        ST   [X+],R0
        ST   [X+],R0            ; Seg = 0
        ST   [X+],R0
        ST   [X+],R0            ; SegBase = 0
        ST   [X+],R0
.uls_pop_done:
        POP  R0
.uls_done:
        RET

pm_load_seg0:
        ; Segment 0 lives in High RAM at PM_SEG0_BASE ($B000)
        ; SegDict[0]: UseCount = 1, OldKp = 0, Seg = PM_SEG0_BASE + 7768 - 2, SegBase = PM_SEG0_BASE
        LDW  X,#PM_SEG_DICT
        MOV  R0,#1
        ST   [X],R0             ; UseCount low = 1
        CLR  R0
        ST   [X+1],R0           ; UseCount high = 0
        ST   [X+2],R0           ; OldKp low = 0 (never unloaded)
        ST   [X+3],R0           ; OldKp high = 0
        LDW  Y,#PM_SEG0_BASE + 7768 - 2
        MOV  R0,YL
        MOV  R1,YH
        ST   [X+4],R0           ; Seg low
        ST   [X+5],R1           ; Seg high
        LDW  Y,#PM_SEG0_BASE
        MOV  R0,YL
        MOV  R1,YH
        ST   [X+6],R0           ; SegBase low
        ST   [X+7],R1           ; SegBase high

        ; Read 7768 bytes from block 203 into PM_SEG0_BASE ($B000)
        ; Flash Addr = $790000 + 203 * 512 = $7A9600
        CLR  R3
        ST   [FLS_CTRL],R3
        ST   [FLS_ADDR_L],R3
        MOV  R3,#$96
        ST   [FLS_ADDR_M],R3
        MOV  R3,#$7A
        ST   [FLS_ADDR_H],R3
        MOV  R3,#1
        ST   [FLS_CTRL],R3

        LDW  X,#PM_SEG0_BASE
        MOV  R2,#<7768
        MOV  R3,#>7768

.ls0_rd_lp:
        MOV  R0,R2
        OR   R0,R3
        BEQ  .ls0_rd_done
        LD   R0,[FLS_DATA]
        ST   [X],R0
        INCW X
        SUB  R2,#1
        SBC  R3,#0
        BRA  .ls0_rd_lp

.ls0_rd_done:
        CLR  R0
        ST   [FLS_CTRL],R0
        RET
