; ---------------------------------------------------------------------
; sw/pascal/pm_call.asm -- P-Machine Procedure Calls & Frame Management
; ---------------------------------------------------------------------

; Calculate JTab for procedure in R0 of segment in PM_TMP3
; Returns JTab in X
pm_proc_jtab:
        SHL  R0
        CLR  R1
        LDW  X,#PM_TMP3
        LD   R2,[X]
        LD   R3,[X+1]
        SUB  R2,R0
        SBC  R3,R1
        MOV  XH,R3
        MOV  XL,R2
        LD   R0,[X]
        LD   R1,[X+1]
        SUB  R2,R0
        SBC  R3,R1
        MOV  XH,R3
        MOV  XL,R2
        RET

; Calculate ProcBase for JTab in X
; Returns ProcBase in R1:R0
pm_proc_base:
        MOV  R2,XL
        MOV  R3,XH
        SUB  R2,#2
        SBC  R3,#0
        MOV  XH,R3
        MOV  XL,R2
        LD   R0,[X]
        LD   R1,[X+1]
        SUB  R2,R0
        SBC  R3,R1
        MOV  R0,R2
        MOV  R1,R3
        RET

; Calculate Static Link for NewJTab in X
; Returns StaticLink in R3:R2
pm_calc_static_link:
        LD   R0,[X]             ; ProcNumber
        TST  R0
        BNE  .csl_has_proc
        CLR  R2
        CLR  R3
        RET

.csl_has_proc:
        LD   R1,[X+1]           ; NewLexLevel in R1 (signed)
        LDW  Y,#PM_JTAB
        LD   R2,[Y]
        LD   R3,[Y+1]
        MOV  YH,R3
        MOV  YL,R2
        LD   R0,[Y+1]           ; CallerLexLevel in R0 (signed)

        LDW  Y,#PM_MP
        LD   R2,[Y]
        LD   R3,[Y+1]

        ; Count = CallerLexLevel - NewLexLevel + 1 (signed)
        SUB  R0,R1
        ADD  R0,#1
        TST  R0
        BLE  .csl_done          ; If Count <= 0, return MP directly

.csl_loop:
        MOV  YH,R3
        MOV  YL,R2
        LD   R2,[Y]             ; [p + 0] = MS_STAT (static link)
        LD   R3,[Y+1]
        SUB  R0,#1
        BNE  .csl_loop

.csl_done:
        RET

; pm_call_proc
; Input: ProcNr in R0, static_link in R3:R2, NewSeg in PM_TMP3
pm_call_proc:
        LDW  Y,#PM_TMP0
        ST   [Y],R2             ; static link
        ST   [Y+1],R3

        CALL pm_proc_jtab       ; X = NewJTab
        LDW  Y,#PM_TMP2
        MOV  R0,XL
        ST   [Y],R0             ; NewJTab low
        MOV  R0,XH
        ST   [Y+1],R0           ; NewJTab high

        ; Read DataSize at [NewJTab - 8]
        MOV  R0,#8
        SUBW X,R0
        LD   R2,[X]             ; DataSize low
        LD   R3,[X+1]           ; DataSize high

        ; Read ParamSize at [NewJTab - 6]
        ADDW X,#2
        LD   R0,[X]             ; ParamSize low
        LD   R1,[X+1]           ; ParamSize high
        LDW  Y,#PM_TMP4
        ST   [Y],R0             ; ParamSize low
        ST   [Y+1],R1           ; ParamSize high

        ; Total Frame = DataSize + ParamSize + 12 (MS header)
        ADD  R2,R0
        ADC  R3,R1
        ADD  R2,#12
        ADC  R3,#0

        ; NewMp = PM_KP - Total Frame
        LDW  Y,#PM_KP
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,R2
        SBC  R1,R3

        LDW  Y,#PM_TMP1
        ST   [Y],R0             ; NewMp low
        ST   [Y+1],R1           ; NewMp high

        ; If ParamSize > 0, copy ParamSize bytes from PM_SP to (NewMp + 12)
        LDW  Y,#PM_TMP4
        LD   R2,[Y]             ; ParamSize low
        LD   R3,[Y+1]           ; ParamSize high
        OR   R2,R3
        BEQ  .no_params

        ; Dest in X = NewMp + 12
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R0,#12
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0

        ; Number of bytes in R2
        LDW  Y,#PM_TMP4
        LD   R2,[Y]

        ; Src in Y = PM_SP
        LDW  Y,#PM_SP
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  YH,R1
        MOV  YL,R0

.cp_param_lp:
        TST  R2
        BEQ  .param_copied
        LD   R0,[Y+]
        ST   [X+],R0
        SUB  R2,#1
        BRA  .cp_param_lp

.param_copied:
        ; Advance PM_SP by ParamSize
        LDW  Y,#PM_TMP4
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  X,#PM_SP
        LD   R2,[X]
        LD   R3,[X+1]
        ADD  R2,R0
        ADC  R3,R1
        ST   [X],R2
        ST   [X+1],R3

.no_params:
        ; If LexLevel <= 0: [NewMp - 2] = OldBase; PM_BP = NewMp
        LDW  X,#PM_TMP2         ; NewJTab
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        INCW X
        LD   R0,[X]             ; LexLevel
        TST  R0
        BGT  .no_push_base

        ; Push Base on PM_SP:
        LDW  X,#PM_BP
        LD   R0,[X]
        LD   R1,[X+1]
        CALL pm_push

        ; PM_BP = NewMp
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  X,#PM_BP
        ST   [X],R0
        ST   [X+1],R1

.no_push_base:
        ; Store Mark Stack Header at NewMp:
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#2
        SBC  R1,#0
        MOV  XH,R1
        MOV  XL,R0

        ; [NewMp - 2] = Old PM_KP
        LDW  Y,#PM_KP
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X+],R0
        ST   [X+],R1

        ; [NewMp + 0] = static_link
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X+],R0
        ST   [X+],R1

        ; [NewMp + 2] = Old PM_MP
        LDW  Y,#PM_MP
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X+],R0
        ST   [X+],R1

        ; [NewMp + 4] = Old PM_JTAB
        LDW  Y,#PM_JTAB
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X+],R0
        ST   [X+],R1

        ; [NewMp + 6] = Old PM_SEG
        LDW  Y,#PM_SEG
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X+],R0
        ST   [X+],R1

        ; [NewMp + 8] = Old PM_IPC
        LDW  Y,#PM_IPC
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X+],R0
        ST   [X+],R1

        ; [NewMp + 10] = PM_SP (after Push Base)
        LDW  Y,#PM_SP
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X+],R0
        ST   [X+],R1


        ; Commit NewMp to PM_MP
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  X,#PM_MP
        ST   [X],R0
        ST   [X+1],R1

        ; Commit NewJTab to PM_JTAB
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  X,#PM_JTAB
        ST   [X],R0
        ST   [X+1],R1

        ; Commit NewSeg to PM_SEG
        LDW  Y,#PM_TMP3
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  X,#PM_SEG
        ST   [X],R0
        ST   [X+1],R1

        ; Compute ProcBase(NewJTab) -> PM_SEGB
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        CALL pm_proc_base
        LDW  Y,#PM_SEGB
        ST   [Y],R0
        ST   [Y+1],R1

        ; Set IPC = 0
        CLR  R0
        LDW  X,#PM_IPC
        ST   [X],R0
        ST   [X+1],R0
        ; Set PM_KP = NewMp - 2
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#2
        SBC  R1,#0
        LDW  X,#PM_KP
        ST   [X],R0
        ST   [X+1],R1

        RET

pm_op_clp:
        CALL pm_fetch_b
        LDW  X,#PM_SEG
        LD   R2,[X]
        LD   R3,[X+1]
        LDW  Y,#PM_TMP3
        ST   [Y],R2
        ST   [Y+1],R3
        LDW  X,#PM_MP
        LD   R2,[X]
        LD   R3,[X+1]
        JMP  pm_call_proc

pm_op_cgp:
        CALL pm_fetch_b
        LDW  X,#PM_SEG
        LD   R2,[X]
        LD   R3,[X+1]
        LDW  Y,#PM_TMP3
        ST   [Y],R2
        ST   [Y+1],R3
        LDW  X,#PM_BP
        LD   R2,[X]
        LD   R3,[X+1]
        JMP  pm_call_proc

pm_op_cbp:
        CALL pm_fetch_b
        LDW  X,#PM_SEG
        LD   R2,[X]
        LD   R3,[X+1]
        LDW  Y,#PM_TMP3
        ST   [Y],R2
        ST   [Y+1],R3
        LDW  X,#PM_BASE_MP
        LD   R2,[X]
        LD   R3,[X+1]
        JMP  pm_call_proc

pm_op_cip:
        CALL pm_fetch_b
        LDW  X,#PM_SEG
        LD   R2,[X]
        LD   R3,[X+1]
        LDW  Y,#PM_TMP3
        ST   [Y],R2
        ST   [Y+1],R3
        PUSH R0
        CALL pm_proc_jtab
        CALL pm_calc_static_link
        POP  R0
        JMP  pm_call_proc

pm_call_cxp_seg0:
        ; Call Procedure ProcNo (in R0) of Segment 0 (OS trap)
        PUSH R0                 ; Save ProcNo
        LDW  X,#PM_SEG_DICT + 4
        LD   R0,[X+]            ; Seg low
        LD   R1,[X+]            ; Seg high
        LDW  Y,#PM_TMP3
        ST   [Y],R0
        ST   [Y+1],R1
        POP  R0                 ; Restore ProcNo
        PUSH R0                 ; Save ProcNo
        CALL pm_proc_jtab       ; NewJTab in X
        LDW  Y,#PM_BASE_MP
        LD   R2,[Y]
        LD   R3,[Y+1]           ; StaticLink = PM_BASE_MP
        POP  R0                 ; Restore ProcNo
        JMP  pm_call_proc

pm_op_cxp:
        CALL pm_fetch_b         ; SegNo in R0
        PUSH R0                 ; Stack: [SegNo]
        CALL pm_fetch_b         ; ProcNo in R0
        PUSH R0                 ; Stack: [SegNo, ProcNo]

        POP  R0                 ; R0 = ProcNo
        POP  R1                 ; R1 = SegNo
        PUSH R0                 ; Stack: [ProcNo]
        PUSH R1                 ; Stack: [ProcNo, SegNo]

        MOV  R0,R1              ; R0 = SegNo
        TST  R0
        BEQ  .cxp_no_load
        CALL pm_load_segment    ; pm_load_segment(SegNo)
.cxp_no_load:

        POP  R1                 ; R1 = SegNo
        POP  R0                 ; R0 = ProcNo
        PUSH R0                 ; Stack: [ProcNo]
        PUSH R1                 ; Stack: [ProcNo, SegNo]

        ; Lookup Seg in SegDict[SegNo] (offset +4)
        MOV  R0,R1              ; SegNo
        SHL  R0
        SHL  R0
        SHL  R0                 ; 8 * SegNo
        CLR  R1
        LDW  X,#PM_SEG_DICT
        ADDW X,R0
        ADDW X,#4
        LD   R0,[X+]            ; Seg low
        LD   R1,[X+]            ; Seg high
        LDW  Y,#PM_TMP3
        ST   [Y],R0
        ST   [Y+1],R1

        ; Compute NewJTab for (NewSeg, ProcNo)
        POP  R1                 ; SegNo
        POP  R0                 ; ProcNo
        PUSH R0                 ; Save ProcNo for pm_call_proc
        CALL pm_proc_jtab       ; NewJTab in X
        CALL pm_calc_static_link ; StaticLink in R3:R2
        POP  R0                 ; ProcNo
        JMP  pm_call_proc

pm_do_ret_tail:
        ; Copy return words from [OldMp + 12] to evaluation stack if return count > 0
.ret_push_lp:
        TST  R0
        BEQ  .ret_restore
        PUSH R0
        CLR  R1
        CALL pm_local_addr
        LD   R0,[X]
        LD   R1,[X+1]
        CALL pm_push
        POP  R0
        SUB  R0,#1
        BRA  .ret_push_lp

.ret_restore:
        ; Save OldSegNo before restoring registers:
        CALL pm_find_seg_no     ; OldSegNo in R0
        PUSH R0                 ; Save OldSegNo on CPU stack

        ; Read OldKp, OldMp, OldJTab, OldSeg, OldIPC
        LDW  X,#PM_MP
        LD   R0,[X]
        LD   R1,[X+1]
        SUB  R0,#2
        SBC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R2,[X+]            ; OldKp low
        LD   R3,[X+]            ; OldKp high
        LDW  Y,#PM_KP
        ST   [Y],R2
        ST   [Y+1],R3

        ; Skip StaticLink ([OldMp + 0])
        ADDW X,#2

        LD   R2,[X+]            ; OldMp ([OldMp + 2])
        LD   R3,[X+]
        LDW  Y,#PM_MP
        ST   [Y],R2
        ST   [Y+1],R3

        LD   R2,[X+]            ; OldJTab ([OldMp + 4])
        LD   R3,[X+]
        LDW  Y,#PM_JTAB
        ST   [Y],R2
        ST   [Y+1],R3

        LD   R2,[X+]            ; OldSeg ([OldMp + 6])
        LD   R3,[X+]
        LDW  Y,#PM_SEG
        ST   [Y],R2
        ST   [Y+1],R3

        LD   R2,[X+]            ; OldIPC ([OldMp + 8])
        LD   R3,[X+]
        LDW  Y,#PM_IPC
        ST   [Y],R2
        ST   [Y+1],R3

        ; Restore ProcBase for OldJTab -> PM_SEGB
        LDW  Y,#PM_JTAB
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        CALL pm_proc_base
        LDW  Y,#PM_SEGB
        ST   [Y],R0
        ST   [Y+1],R1

        ; Check for cross-segment return:
        CALL pm_find_seg_no     ; NewSegNo in R0
        POP  R2                 ; OldSegNo in R2
        CMP  R0,R2
        BEQ  .ret_done
        MOV  R0,R2              ; OldSegNo in R0
        CALL pm_unload_segment
.ret_done:
        RET

; pm_find_seg_no: returns SegNo (0..15) in R0 for PM_SEG
pm_find_seg_no:
        LDW  Y,#PM_SEG
        LD   R2,[Y]
        LD   R3,[Y+1]           ; R3:R2 = PM_SEG
        LDW  X,#PM_SEG_DICT + 4 ; Seg pointer offset
        CLR  R0                 ; SegNo = 0
.fs_lp: LD   R1,[X]
        CMP  R1,R2
        BNE  .fs_next
        LD   R1,[X+1]
        CMP  R1,R3
        BEQ  .fs_found
.fs_next:
        MOV  R1,#8
        ADDW X,R1
        ADD  R0,#1
        CMP  R0,#16
        BLO  .fs_lp
        CLR  R0                 ; Default to 0
.fs_found:
        RET

pm_op_rnp:
        CALL pm_fetch_b         ; Return count
        PUSH R0

        ; Restore SP from [PM_MP + 10] (MS_SP)
        LDW  X,#PM_MP
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R0,#10
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R2,[X+]
        LD   R3,[X+]
        LDW  Y,#PM_SP
        ST   [Y],R2
        ST   [Y+1],R3

        POP  R0
        JMP  pm_do_ret_tail

pm_op_rbp:
        CALL pm_fetch_b         ; Return count
        PUSH R0

        ; Restore SP from [PM_MP + 10] (MS_SP)
        LDW  X,#PM_MP
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R0,#10
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R2,[X+]
        LD   R3,[X+]
        LDW  Y,#PM_SP
        ST   [Y],R2
        ST   [Y+1],R3
        ; Pop Base from PM_SP:
        CALL pm_pop             ; OldBase in R1:R0
        LDW  X,#PM_BP
        ST   [X],R0
        ST   [X+1],R1

        POP  R0                 ; Restore return count
        JMP  pm_do_ret_tail
