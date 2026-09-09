; ---------------------------------------------------------------------
; sw/pascal/pm_csp.asm -- P-Machine Standard Procedures (CSP)
; ---------------------------------------------------------------------

pm_op_csp:
        CALL pm_fetch_b         ; CSP procedure number in R0
        CMP  R0,#0              ; IOC (IoCheck)
        BEQ  .csp_ioc
        CMP  R0,#1              ; NEW
        BEQ  .csp_new
        CMP  R0,#2              ; MVL (MoveLeft)
        BEQ  .csp_mvl
        CMP  R0,#3              ; MVR (MoveRight)
        BEQ  .csp_mvr
        CMP  R0,#4              ; XIT (Exit)
        BEQ  .csp_exit
        CMP  R0,#5              ; UREAD (UnitRead)
        BEQ  .csp_uread
        CMP  R0,#6              ; UWRITE (UnitWrite)
        BEQ  .csp_uwrite
        CMP  R0,#7              ; IDS (IdSearch)
        BEQ  .csp_ids
        CMP  R0,#8              ; TRS (TreeSearch)
        BEQ  .csp_trs
        CMP  R0,#9              ; TIM (Time)
        BEQ  .csp_time
        CMP  R0,#10             ; FLC (FillChar)
        BEQ  .csp_flc
        CMP  R0,#11             ; SCN (Scan)
        BEQ  .csp_scan
        CMP  R0,#21             ; LDSEG (LoadSegment)
        BEQ  .csp_ldseg
        CMP  R0,#22             ; ULDSEG (UnloadSegment)
        BEQ  .csp_uldseg
        CMP  R0,#32             ; MRK (Mark)
        BEQ  .csp_mrk
        CMP  R0,#33             ; RLS (Release)
        BEQ  .csp_rls
        CMP  R0,#34             ; IOR (IOResult)
        BEQ  .csp_ior
        CMP  R0,#38             ; UCLEAR (UnitClear)
        BEQ  .csp_clear
        CMP  R0,#39             ; HLT (Halt)
        BEQ  .csp_halt
        CMP  R0,#40             ; MAV (MemAvail)
        BEQ  .csp_mav
        RET

.csp_ldseg:
        CALL pm_pop             ; SegNo in R1:R0
        JMP  pm_load_segment

.csp_uldseg:
        CALL pm_pop             ; SegNo in R1:R0
        JMP  pm_unload_segment

.csp_ioc:
        RET

.csp_new:
        ; New(var P: pointer, SizeInWords: integer)
        ; Pop SizeInWords, Pop PtrAddr, [PtrAddr] = PM_NP, PM_NP = PM_NP + SizeInWords * 2
        CALL pm_pop             ; Size in words in R1:R0
        SHL  R0
        ROL  R1
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1
        CALL pm_pop             ; PtrAddr in R1:R0
        MOV  XH,R1
        MOV  XL,R0

        LDW  Y,#PM_NP
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X],R0
        ST   [X+1],R1

        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        LDW  Y,#PM_NP
        ST   [Y],R0
        ST   [Y+1],R1
        RET

.csp_mvl:
        ; MoveLeft(Dst, DstOffset, Src, SrcOffset, Len)
        ; Stack (TOS down): Len, DstOffset, Dst, SrcOffset, Src
        CALL pm_pop             ; Len
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; DstOffset
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Dst
        LDW  Y,#PM_TMP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; SrcOffset
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Src
        LDW  Y,#PM_TMP2
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        ST   [Y],R0
        ST   [Y+1],R1

        ; Copy Len bytes from TMP2 (Src) to TMP1 (Dst)
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        TST  R3
        BMI  .mvl_done

.mvl_lp:MOV  R0,R2

        OR   R0,R3
        BEQ  .mvl_done
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X+]
        MOV  R1,XL
        ST   [Y],R1
        MOV  R1,XH
        ST   [Y+1],R1

        LDW  Y,#PM_TMP1
        LD   R1,[Y+1]
        MOV  XH,R1
        LD   R1,[Y]
        MOV  XL,R1
        ST   [X+],R0
        MOV  R1,XL
        ST   [Y],R1
        MOV  R1,XH
        ST   [Y+1],R1

        SUB  R2,#1
        SBC  R3,#0
        BRA  .mvl_lp
.mvl_done:
        RET

.csp_mvr:
        JMP  .csp_mvl

.csp_exit:
        ; CSP_XIT: Exit from procedure
        ; Pop ProcNo, Pop SegNo
        CALL pm_pop             ; ProcNo in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0             ; TMP0 = Target ProcNo
        ST   [Y+1],R1

        CALL pm_pop             ; SegNo in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0             ; TMP1 = Target SegNo
        ST   [Y+1],R1

        ; Compute ProcExitIpc(PM_JTAB):
        ; exit_ipc = [PM_JTAB - 2] - [PM_JTAB - 4] - 2
        LDW  Y,#PM_JTAB
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#2
        SBC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R2,[X+]            ; [JTab - 2]
        LD   R3,[X+]
        SUB  R0,#2
        SBC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X+]            ; [JTab - 4]
        LD   R1,[X+]
        SUB  R2,R0
        SBC  R3,R1
        SUB  R2,#2
        SBC  R3,#0
        ; Set current IPC = exit_ipc
        LDW  Y,#PM_IPC
        ST   [Y],R2
        ST   [Y+1],R3

        ; xMp = PM_MP
        LDW  Y,#PM_MP
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP2
        ST   [Y],R0             ; TMP2 = xMp
        ST   [Y+1],R1

        ; xJTab = PM_JTAB
        LDW  Y,#PM_JTAB
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP3
        ST   [Y],R0             ; TMP3 = xJTab
        ST   [Y+1],R1

        ; xSeg = PM_SEG
        LDW  Y,#PM_SEG
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP4
        ST   [Y],R0             ; TMP4 = xSeg
        ST   [Y+1],R1

.xit_loop:
        ; Check if ProcNumber(xJTab) == Target ProcNo AND SegNumber(xSeg) == Target SegNo
        LDW  Y,#PM_TMP3
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        LD   R2,[X]             ; ProcNumber(xJTab)
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        CMP  R2,R0
        BNE  .xit_unwind

        LDW  Y,#PM_TMP4
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        LD   R2,[X]             ; SegNumber(xSeg)
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        CMP  R2,R0
        BEQ  .xit_done

.xit_unwind:
        ; Check if xMp == 0
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  R2,R0
        OR   R2,R1
        BEQ  .xit_done

        ; Advance to caller:
        ; Read caller's JTab from [xMp + 4] (MS_JTAB)
        ADD  R0,#4
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R2,[X+]
        LD   R3,[X+]
        LDW  Y,#PM_TMP3
        ST   [Y],R2
        ST   [Y+1],R3

        ; Read caller's Seg from [xMp + 6] (MS_SEG)
        LD   R2,[X+]
        LD   R3,[X+]
        LDW  Y,#PM_TMP4
        ST   [Y],R2
        ST   [Y+1],R3

        ; Compute ProcExitIpc for caller's xJTab
        ; [xJTab - 2] - [xJTab - 4] - 2
        LDW  Y,#PM_TMP3
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#2
        SBC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R2,[X+]            ; [xJTab - 2]
        LD   R3,[X+]
        SUB  R0,#2
        SBC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X+]            ; [xJTab - 4]
        LD   R1,[X+]
        SUB  R2,R0
        SBC  R3,R1
        SUB  R2,#2
        SBC  R3,#0

        ; Write to [xMp + 8] (MS_IPC)
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R0,#8
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        ST   [X+],R2
        ST   [X],R3

        ; Advance xMp = [xMp + 2] (MS_DYN)
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R0,#2
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R2,[X+]
        LD   R3,[X+]
        LDW  Y,#PM_TMP2
        ST   [Y],R2
        ST   [Y+1],R3
        BRA  .xit_loop

.xit_done:
        RET


.csp_uread:
        JMP  pm_sbios_unitread

.csp_uwrite:
        JMP  pm_sbios_unitwrite

.csp_time:
        ; Time(var Hi, Lo: integer)
        ; Stack has [HiPtr, LoPtr]
        ; Pop LoPtr into X
        CALL pm_pop             ; LoPtr in R1:R0
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[frames]
        LD   R1,[frames+1]
        ST   [X+],R0            ; Write low word to [LoPtr]
        ST   [X],R1

        ; Write low word to SYSCOM.LOWTIME (SYSCOM + 54)
        LDW  Y,#PM_SYSCOM
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R2,#54
        ADC  R3,#0
        MOV  XH,R3
        MOV  XL,R2
        ST   [X+],R0
        ST   [X],R1

        ; Pop HiPtr into X
        CALL pm_pop             ; HiPtr in R1:R0
        MOV  XH,R1
        MOV  XL,R0
        CLR  R0
        CLR  R1
        ST   [X+],R0            ; Write high word to [HiPtr]
        ST   [X],R1

        ; Write high word to SYSCOM.HIGHTIME (SYSCOM + 56)
        LDW  Y,#PM_SYSCOM
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R2,#56
        ADC  R3,#0
        MOV  XH,R3
        MOV  XL,R2
        ST   [X+],R0
        ST   [X],R1
        RET

.csp_ids:
        ; IdSearch(var SymCursor: integer; var SymBuf: packed array [0..1023] of char)
        ; Stack (TOS down): SymBufPtr, SymInfoPtr
        CALL pm_pop             ; SymBufPtr in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; SymInfoPtr in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        ; Read SYMCURSOR from [SymInfoPtr]
        MOV  XH,R1
        MOV  XL,R0
        LD   R2,[X+]            ; SYMCURSOR low
        LD   R3,[X]             ; SYMCURSOR high

        ; Source pointer X = SymBufPtr + SYMCURSOR
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0

        ; Initialize PM_STR_BUF1 with 8 spaces ($20)
        LDW  Y,#PM_STR_BUF1
        MOV  R0,#$20
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y],R0

        LDW  Y,#PM_STR_BUF1
        CLR  R1                 ; stored char count (0..8)

.ids_loop:
        LD   R0,[X+]
        ADD  R2,#1
        ADC  R3,#0

        CMP  R0,#'_'            ; underscore?
        BEQ  .ids_loop          ; ignore underscore

        ; Check uppercase 'A'..'Z'
        CMP  R0,#'A'
        BLO  .ids_try_digit
        CMP  R0,#'Z' + 1
        BLO  .ids_char_ok

        ; Check lowercase 'a'..'z'
        CMP  R0,#'a'
        BLO  .ids_done
        CMP  R0,#'z' + 1
        BHS  .ids_done
        SUB  R0,#32             ; convert to uppercase
        BRA  .ids_char_ok

.ids_try_digit:
        CMP  R0,#'0'
        BLO  .ids_done
        CMP  R0,#'9' + 1
        BHS  .ids_done

.ids_char_ok:
        CMP  R1,#8
        BHS  .ids_loop          ; already got 8 chars, don't store more
        ST   [Y+],R0
        ADD  R1,#1
        BRA  .ids_loop

.ids_done:
        ; SYMCURSOR was incremented past the delimiter.
        ; INSYMBOL expects SYMCURSOR to point to the LAST char of the identifier.
        ; Therefore, subtract 2 from R3:R2.
        SUB  R2,#2
        SBC  R3,#0

        ; Write updated SYMCURSOR to SymInfo[0..1]
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        ST   [X+],R2            ; SymInfo+0 (SYMCURSOR low)
        ST   [X+],R3            ; SymInfo+1 (SYMCURSOR high)

        ; Now X points to SymInfo+2!
        ; Search .pm_rw_table (42 entries, 10 bytes each)
        LDW  Y,#.pm_rw_table
        MOV  R2,#42

.ids_rw_loop:
        PUSHW X                 ; save SymInfo+2
        LDW  X,#PM_STR_BUF1
        MOV  R3,#8
.ids_rw_cmp:
        LD   R0,[X+]
        LD   R1,[Y+]
        CMP  R0,R1
        BNE  .ids_rw_mismatch
        SUB  R3,#1
        BNE  .ids_rw_cmp

        ; Match found!
        POPW X                  ; restore SymInfo+2
        LD   R0,[Y+]            ; SY
        CLR  R1
        ST   [X+],R0            ; SymInfo+2 (SY low)
        ST   [X+],R1            ; SymInfo+3 (SY high)
        LD   R0,[Y]             ; OP
        ST   [X+],R0            ; SymInfo+4 (OP low)
        ST   [X+],R1            ; SymInfo+5 (OP high)
        BRA  .ids_copy_id

.ids_rw_mismatch:
        ; Advance Y past remaining bytes in this 10-byte entry
        INC  R3
        ADDW Y,R3
        POPW X                  ; restore SymInfo+2
        SUB  R2,#1
        BNE  .ids_rw_loop

        ; Not a reserved word: ordinary identifier!
        ; SY = 0 (IDENT), OP = 15 (NOOP)
        CLR  R0
        ST   [X+],R0            ; SymInfo+2 = 0
        ST   [X+],R0            ; SymInfo+3 = 0
        MOV  R0,#15
        ST   [X+],R0            ; SymInfo+4 = 15
        CLR  R0
        ST   [X+],R0            ; SymInfo+5 = 0

.ids_copy_id:
        ; Copy 8 bytes from PM_STR_BUF1 to SymInfo+6..13
        LDW  Y,#PM_STR_BUF1
        LD   R0,[Y+]
        ST   [X+],R0
        LD   R0,[Y+]
        ST   [X+],R0
        LD   R0,[Y+]
        ST   [X+],R0
        LD   R0,[Y+]
        ST   [X+],R0
        LD   R0,[Y+]
        ST   [X+],R0
        LD   R0,[Y+]
        ST   [X+],R0
        LD   R0,[Y+]
        ST   [X+],R0
        LD   R0,[Y]
        ST   [X],R0
        RET

.pm_rw_table:
        .ascii "AND     "
        .byte 39, 2
        .ascii "ARRAY   "
        .byte 44, 15
        .ascii "BEGIN   "
        .byte 19, 15
        .ascii "CASE    "
        .byte 21, 15
        .ascii "CONST   "
        .byte 28, 15
        .ascii "DIV     "
        .byte 39, 3
        .ascii "DO      "
        .byte 6, 15
        .ascii "DOWNTO  "
        .byte 8, 15
        .ascii "ELSE    "
        .byte 13, 15
        .ascii "END     "
        .byte 9, 15
        .ascii "EXTERNAL"
        .byte 53, 15
        .ascii "FILE    "
        .byte 46, 15
        .ascii "FOR     "
        .byte 24, 15
        .ascii "FORWARD "
        .byte 34, 15
        .ascii "FUNCTION"
        .byte 32, 15
        .ascii "GOTO    "
        .byte 26, 15
        .ascii "IF      "
        .byte 20, 15
        .ascii "IMPLEMEN"
        .byte 52, 15
        .ascii "IN      "
        .byte 41, 14
        .ascii "INTERFAC"
        .byte 51, 15
        .ascii "LABEL   "
        .byte 27, 15
        .ascii "MOD     "
        .byte 39, 4
        .ascii "NOT     "
        .byte 38, 15
        .ascii "OF      "
        .byte 11, 15
        .ascii "OR      "
        .byte 40, 7
        .ascii "PACKED  "
        .byte 43, 15
        .ascii "PROCEDUR"
        .byte 31, 15
        .ascii "PROGRAM "
        .byte 33, 15
        .ascii "RECORD  "
        .byte 45, 15
        .ascii "REPEAT  "
        .byte 22, 15
        .ascii "SEGMENT "
        .byte 33, 15
        .ascii "SEPARATE"
        .byte 54, 15
        .ascii "SET     "
        .byte 42, 15
        .ascii "THEN    "
        .byte 12, 15
        .ascii "TO      "
        .byte 7, 15
        .ascii "TYPE    "
        .byte 29, 15
        .ascii "UNIT    "
        .byte 50, 15
        .ascii "UNTIL   "
        .byte 10, 15
        .ascii "USES    "
        .byte 49, 15
        .ascii "VAR     "
        .byte 30, 15
        .ascii "WHILE   "
        .byte 23, 15
        .ascii "WITH    "
        .byte 25, 15

.csp_trs:
        ; TreeSearch(TokenBuf, ResultPtr, NodePtr)
        ; Pop TokenBuf, Pop ResultPtr, Pop NodePtr
        CALL pm_pop             ; TokenBuf in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; ResultPtr in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; NodePtr in R1:R0
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1

.trs_loop:
        ; Compare 8 bytes between TokenBuf (TMP0) and Node (TMP2)
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R1
        MOV  XL,R0

        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  YH,R1
        MOV  YL,R0

        MOV  R2,#8              ; compare 8 bytes
.trs_cmp:
        TST  R2
        BEQ  .trs_found
        LD   R0,[X+]
        LD   R1,[Y+]
        CMP  R0,R1
        BLO  .trs_lt            ; Token < Node -> follow RightLink (offset 10)
        BHI  .trs_gt            ; Token > Node -> follow LeftLink (offset 8)
        SUB  R2,#1
        BRA  .trs_cmp

.trs_lt:
        ; Right link at [Node + 10]
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R0,#10
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X+]
        LD   R1,[X]
        MOV  R2,R0
        OR   R2,R1
        BEQ  .trs_not_found_rt
        CMP  R0,#$FF
        BNE  .trs_has_rt
        CMP  R1,#$FF
        BEQ  .trs_not_found_rt
.trs_has_rt:
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1
        BRA  .trs_loop

.trs_not_found_rt:
        CALL .trs_store_result
        MOV  R0,#$FF
        MOV  R1,#$FF
        JMP  pm_push

.trs_gt:
        ; Left link at [Node + 8]
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R0,#8
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X+]
        LD   R1,[X]
        MOV  R2,R0
        OR   R2,R1
        BEQ  .trs_not_found_lt
        CMP  R0,#$FF
        BNE  .trs_has_lt
        CMP  R1,#$FF
        BEQ  .trs_not_found_lt
.trs_has_lt:
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1
        BRA  .trs_loop

.trs_not_found_lt:
        CALL .trs_store_result
        MOV  R0,#1
        CLR  R1
        JMP  pm_push

.trs_found:
        CALL .trs_store_result
        CLR  R0
        CLR  R1
        JMP  pm_push

.trs_store_result:
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X+],R0
        ST   [X],R1
        RET

.csp_flc:
        ; FillChar(Addr, Offset, Len, Char)
        ; Stack (TOS down): Char, Len, Offset, Addr
        CALL pm_pop             ; Char byte in R0
        PUSH R0

        CALL pm_pop             ; Len in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Offset in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Addr in R1:R0
        LDW  Y,#PM_TMP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0

        POP  R0                 ; Char byte
        LDW  Y,#PM_TMP0
        LD   R2,[Y]             ; Len low
        LD   R3,[Y+1]           ; Len high
        TST  R3
        BMI  .flc_done

.flc_lp:MOV  R1,R2

        OR   R1,R3
        BEQ  .flc_done
        ST   [X+],R0
        SUB  R2,#1
        SBC  R3,#0
        BRA  .flc_lp
.flc_done:
        RET

.csp_scan:
        ; Scan(Limit, Match, Char, Buf, Offset, Dummy)
        ; Pops 6 words: Dummy, Offset, Buf, Char, Match, Limit
        CALL pm_pop             ; Dummy

        CALL pm_pop             ; Offset in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Buf in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Char in R1:R0
        LDW  Y,#PM_TMP2
        ST   [Y],R0             ; Char in PM_TMP2

        CALL pm_pop             ; Match in R1:R0
        ST   [Y+1],R0           ; Match in PM_TMP2+1

        CALL pm_pop             ; Limit in R1:R0
        LDW  Y,#PM_TMP3
        ST   [Y],R0
        ST   [Y+1],R1

        ; StartAddr = Buf + Offset -> X
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0

        ; Res = 0 in PM_TMP4
        CLR  R0
        CLR  R1
        LDW  Y,#PM_TMP4
        ST   [Y],R0
        ST   [Y+1],R1

.scn_lp:
        LDW  Y,#PM_TMP4
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP3
        LD   R2,[Y]
        LD   R3,[Y+1]
        CMP  R0,R2
        BNE  .scn_chk
        CMP  R1,R3
        BEQ  .scn_done

.scn_chk:
        LD   R0,[X+]
        LDW  Y,#PM_TMP2
        LD   R2,[Y]             ; Char
        LD   R3,[Y+1]           ; Match
        CMP  R0,R2
        BNE  .scn_neq
        ; Byte == Char
        TST  R3
        BEQ  .scn_done          ; Match == 0 (seeking ==) -> found!
        BRA  .scn_nxt
.scn_neq:
        ; Byte != Char
        TST  R3
        BNE  .scn_done          ; Match != 0 (seeking !=) -> found!

.scn_nxt:
        LDW  Y,#PM_TMP4
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R0,#1
        ADC  R1,#0
        ST   [Y],R0
        ST   [Y+1],R1
        BRA  .scn_lp

.scn_done:
        LDW  Y,#PM_TMP4
        LD   R0,[Y]
        LD   R1,[Y+1]
        JMP  pm_push

.csp_mrk:
        CALL pm_pop             ; PtrAddr
        MOV  XH,R1
        MOV  XL,R0
        LDW  Y,#PM_NP
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X],R0
        ST   [X+1],R1
        RET

.csp_rls:
        ; Release(var P: pointer) -> PM_NP = [P]
        CALL pm_pop             ; PtrAddr in R1:R0
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#PM_NP
        ST   [Y],R0
        ST   [Y+1],R1
        RET

.csp_ior:
        LDW  X,#PM_SYSCOM
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X]             ; IORSLT low
        LD   R1,[X+1]           ; IORSLT high
        CLR  R2
        ST   [X],R2             ; Clear IORSLT
        ST   [X+1],R2
        JMP  pm_push

.csp_clear:
        CALL pm_pop             ; Unit in R1:R0
        CLR  R0
        CLR  R1
        JMP  pm_sbios_set_iorslt

.csp_halt:
        LDW  X,#PM_QUIT
        MOV  R0,#1
        ST   [X],R0
        RET

.csp_mav:
        ; MemAvail = (PM_KP - PM_NP) / 2 words
        LDW  Y,#PM_KP
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_NP
        LD   R2,[Y]
        LD   R3,[Y+1]
        SUB  R0,R2
        SBC  R1,R3
        BHI  .mav_ok
        CLR  R0
        CLR  R1
        JMP  pm_push
.mav_ok:
        SHR  R1
        ROR  R0
        JMP  pm_push


