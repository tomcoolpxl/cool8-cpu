; ---------------------------------------------------------------------
; sw/pascal/pm_string.asm -- P-Machine Strings, Arrays, & Indexing
; ---------------------------------------------------------------------

pm_op_lsa:
        ; Push address of string literal (pointing to the Len byte at PM_IPC!)
        LDW  X,#PM_SEGB
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#PM_IPC
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        CALL pm_push

        ; Fetch length byte (advances IPC by 1)
        CALL pm_fetch_b         ; Len in R0
        CLR  R1

        ; Advance IPC by Len
        LDW  Y,#PM_IPC
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R2,R0
        ADC  R3,R1
        ST   [Y],R2
        ST   [Y+1],R3
        RET

pm_op_sas:
        CALL pm_fetch_b         ; MaxLen in R0 (1 unsigned byte)
        PUSH R0                 ; Save MaxLen

        CALL pm_pop             ; w in R1:R0 (Src pointer or char)
        TST  R1
        BEQ  .sas_char          ; If high byte == 0, it's a single char!

        ; Save Src pointer on stack
        PUSH R0
        PUSH R1
        CALL pm_pop             ; Dest in R1:R0
        MOV  YH,R1
        MOV  YL,R0
        POP  R1
        POP  R0
        MOV  XH,R1
        MOV  XL,R0

        ; Read Len at [Src]
        LD   R0,[X]             ; Len byte
        POP  R1                 ; MaxLen
        CMP  R0,R1
        BLS  .sas_len_ok
        MOV  R0,R1              ; Len = MaxLen
.sas_len_ok:
        MOV  R2,R0              ; Count = Len
        ADD  R2,#1              ; Total bytes = Len + 1 (including Len byte)

.sas_copy_lp:
        TST  R2
        BEQ  .sas_done
        LD   R0,[X+]
        ST   [Y+],R0
        SUB  R2,#1
        BRA  .sas_copy_lp
.sas_done:
        RET

.sas_char:
        POP  R2                 ; Discard MaxLen
        PUSH R0                 ; Save char in R0
        CALL pm_pop             ; Dest in R1:R0
        MOV  XH,R1
        MOV  XL,R0
        MOV  R0,#1
        ST   [X+],R0            ; Length = 1
        POP  R0                 ; Char byte
        ST   [X],R0             ; Dest[1] = char
        RET

pm_op_ixa:
        CALL pm_fetch_big       ; ElemWords in R1:R0
        MOV  R2,R0
        MOV  R3,R1
        CALL pm_pop             ; Index in R1:R0
        CALL pm_mul16           ; Index * ElemWords in R1:R0
        SHL  R0                 ; Convert words to byte offset (* 2)
        ROL  R1
        PUSH R0                 ; Save byte offset low
        PUSH R1                 ; Save byte offset high
        CALL pm_pop             ; ArrayBase in R1:R0
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        JMP  pm_push

pm_op_ixs:
        CALL pm_pop             ; Index in R1:R0
        PUSH R0
        PUSH R1
        CALL pm_pop             ; String Base in R1:R0
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        JMP  pm_push

pm_op_ixp:
        CALL pm_fetch_b         ; p1 in R0 (elements per word)
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        CALL pm_fetch_b         ; p2 in R0 (bits per element)
        LDW  Y,#PM_TMP4
        ST   [Y],R0             ; p2 in PM_TMP4

        CALL pm_pop             ; Index in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; BaseAddr in R1:R0
        LDW  Y,#PM_TMP3
        ST   [Y],R0
        ST   [Y+1],R1

        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        CLR  R3
        ST   [Y+1],R3           ; 16-bit divisor p1 in PM_TMP0
        CALL pm_udivmod16       ; Index / p1 -> Quotient in R1:R0, Remainder in PM_TMP0

        ; WordAddr = BaseAddr + 2 * Quotient
        SHL  R0
        ROL  R1
        LDW  Y,#PM_TMP3
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        CALL pm_push             ; Push WordAddr

        ; Push Size (p2)
        LDW  Y,#PM_TMP4
        LD   R0,[Y]
        CLR  R1
        CALL pm_push             ; Push Size

        ; Push Offset = Remainder * p2
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP4
        LD   R2,[Y]
        CLR  R3
        CALL pm_mul16
        JMP  pm_push             ; Push Offset

pm_op_lpa:
        ; Fetch length byte (advances IPC by 1)
        CALL pm_fetch_b         ; Len in R0
        CLR  R1
        PUSH R0
        PUSH R1

        ; Push address of characters (at PM_IPC)
        LDW  X,#PM_SEGB
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#PM_IPC
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        CALL pm_push

        ; Advance IPC by Len
        POP  R1
        POP  R0
        LDW  Y,#PM_IPC
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R2,R0
        ADC  R3,R1
        ST   [Y],R2
        ST   [Y+1],R3
        RET

pm_op_ldp:
        CALL pm_pop             ; Offset in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0             ; Offset

        CALL pm_pop             ; Size in R1:R0
        ST   [Y+1],R0           ; Size

        CALL pm_pop             ; Addr in R1:R0
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X+]
        LD   R1,[X]

        ; Shift right by Offset
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
.ldp_sh_lp:
        TST  R2
        BEQ  .ldp_sh_done
        SHR  R1
        ROR  R0
        SUB  R2,#1
        BRA  .ldp_sh_lp
.ldp_sh_done:
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        ; Build Mask in R3:R2 = ((1 << Size) - 1)
        LDW  Y,#PM_TMP0+1
        LD   R0,[Y]             ; Size
        MOV  R2,#1
        CLR  R3
.ldp_m_lp:
        TST  R0
        BEQ  .ldp_m_done
        SHL  R2
        ROL  R3
        SUB  R0,#1
        BRA  .ldp_m_lp
.ldp_m_done:
        SUB  R2,#1
        SBC  R3,#0

        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        AND  R0,R2
        AND  R1,R3
        JMP  pm_push

pm_op_stp:
        CALL pm_pop             ; Value in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Offset in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0             ; Offset

        CALL pm_pop             ; Size in R1:R0
        LDW  Y,#PM_TMP1+1
        ST   [Y],R0             ; Size

        CALL pm_pop             ; Addr in R1:R0
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1

        ; Build Mask in R3:R2 = ((1 << Size) - 1)
        LDW  Y,#PM_TMP1+1
        LD   R0,[Y]             ; Size
        MOV  R2,#1
        CLR  R3
.stp_m_lp:
        TST  R0
        BEQ  .stp_m_done
        SHL  R2
        ROL  R3
        SUB  R0,#1
        BRA  .stp_m_lp
.stp_m_done:
        SUB  R2,#1
        SBC  R3,#0

        ; Value = Value & Mask
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        AND  R0,R2
        AND  R1,R3
        ST   [Y],R0
        ST   [Y+1],R1

        ; Save Mask in PM_TMP3
        LDW  Y,#PM_TMP3
        ST   [Y],R2
        ST   [Y+1],R3

        ; Shift Masked Value (in PM_TMP0) and Mask (in PM_TMP3) left by Offset
        LDW  Y,#PM_TMP1
        LD   R2,[Y]             ; Offset
.stp_sh_lp:
        TST  R2
        BEQ  .stp_sh_done
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        SHL  R0
        ROL  R1
        ST   [Y],R0
        ST   [Y+1],R1

        LDW  Y,#PM_TMP3
        LD   R0,[Y]
        LD   R1,[Y+1]
        SHL  R0
        ROL  R1
        ST   [Y],R0
        ST   [Y+1],R1

        SUB  R2,#1
        BRA  .stp_sh_lp
.stp_sh_done:

        ; WordMask = ~Mask
        LDW  Y,#PM_TMP3
        LD   R2,[Y]
        LD   R3,[Y+1]
        XOR  R2,#$FF
        XOR  R3,#$FF

        ; Read existing word at [Addr]
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X+]
        LD   R1,[X]

        ; NewWord = (ExistingWord & WordMask) | MaskedValue
        AND  R0,R2
        AND  R1,R3

        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        OR   R0,R2
        OR   R1,R3

        ; Store NewWord to [Addr]
        LDW  Y,#PM_TMP2
        LD   R2,[Y]
        LD   R3,[Y+1]
        MOV  XH,R3
        MOV  XL,R2
        ST   [X+],R0
        ST   [X],R1
        RET

; ---------------------------------------------------------------------
; Multi-Type Comparisons (EQU, NEQ, LEQ, GEQ, LES, GRT)
; ---------------------------------------------------------------------

pm_cmp_multi:
        CALL pm_fetch_b         ; Type in R0 (2=Real, 4=String, 6=Bool, 8=Set, 10=ByteArr, 12=WordArr)
        CMP  R0,#4
        BEQ  .cm_str
        CMP  R0,#6
        BEQ  .cm_bool
        CMP  R0,#10
        BEQ  .cm_bytearr
        CMP  R0,#12
        BEQ  .cm_wordarr

        ; Fallback for other types: pop 2 words and compare
        CALL pm_pop             ; Val2 in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1
        CALL pm_pop             ; Val1 in R1:R0
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        CMP  R1,R3
        BLT  .cm_ret_neg
        BGT  .cm_ret_pos
        CMP  R0,R2
        BLO  .cm_ret_neg
        BHI  .cm_ret_pos
        CLR  R0
        RET

.cm_bool:
        CALL pm_pop             ; Val2
        AND  R0,#1
        MOV  R2,R0
        CALL pm_pop             ; Val1
        AND  R0,#1
        CMP  R0,R2
        BLO  .cm_ret_neg
        BHI  .cm_ret_pos
        CLR  R0
        RET

.cm_str:
        CALL pm_pop             ; S2 in R1:R0
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1
        CALL pm_pop             ; S1 in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        ; Check if S1 is a char (high byte == 0)
        LDW  Y,#PM_TMP1+1
        LD   R0,[Y]
        TST  R0
        BNE  .cm_s1_ptr
        LDW  Y,#PM_TMP1
        LD   R0,[Y]             ; char
        LDW  X,#PM_STR_BUF1
        MOV  R2,#1
        ST   [X+],R2            ; len = 1
        ST   [X],R0             ; char
        LDW  X,#PM_STR_BUF1
        MOV  R0,XL
        MOV  R1,XH
        ST   [Y],R0
        ST   [Y+1],R1
.cm_s1_ptr:
        ; Check if S2 is a char (high byte == 0)
        LDW  Y,#PM_TMP2+1
        LD   R0,[Y]
        TST  R0
        BNE  .cm_s2_ptr
        LDW  Y,#PM_TMP2
        LD   R0,[Y]             ; char
        LDW  X,#PM_STR_BUF2
        MOV  R2,#1
        ST   [X+],R2            ; len = 1
        ST   [X],R0             ; char
        LDW  X,#PM_STR_BUF2
        MOV  R0,XL
        MOV  R1,XH
        ST   [Y],R0
        ST   [Y+1],R1
.cm_s2_ptr:
        ; S1 in X, S2 in Y
        LDW  X,#PM_TMP1
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  YH,R1
        MOV  YL,R0

        ; Len1 at [X], Len2 at [Y]
        LD   R2,[X+]            ; Len1 in R2
        LD   R3,[Y+]            ; Len2 in R3
        PUSH R2                 ; Save Len1
        PUSH R3                 ; Save Len2

        ; MinLen in R0 = min(Len1, Len2)
        MOV  R0,R2
        CMP  R0,R3
        BLS  .str_min_ok
        MOV  R0,R3
.str_min_ok:
        MOV  R1,R0              ; Loop count in R1

.str_cmp_lp:
        TST  R1
        BEQ  .str_chars_eq
        LD   R0,[X+]
        LD   R2,[Y+]
        CMP  R0,R2
        BLO  .str_lt
        BHI  .str_gt
        SUB  R1,#1
        BRA  .str_cmp_lp

.str_chars_eq:
        POP  R3                 ; Len2
        POP  R2                 ; Len1
        CMP  R2,R3
        BLO  .cm_ret_neg        ; Len1 < Len2 -> S1 < S2
        BHI  .cm_ret_pos        ; Len1 > Len2 -> S1 > S2
        CLR  R0                 ; Len1 == Len2 -> S1 == S2
        RET

.str_lt:
        POP  R3
        POP  R2
        BRA  .cm_ret_neg

.str_gt:
        POP  R3
        POP  R2
        BRA  .cm_ret_pos

.cm_bytearr:
        CALL pm_fetch_big       ; Len in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1
        CALL pm_pop             ; BA2
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1
        CALL pm_pop             ; BA1
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        LDW  X,#PM_TMP1
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  YH,R1
        MOV  YL,R0
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]

.ba_lp: MOV  R0,R2
        OR   R0,R3
        BEQ  .ba_eq
        LD   R0,[X+]
        LD   R1,[Y+]
        CMP  R0,R1
        BLO  .cm_ret_neg
        BHI  .cm_ret_pos
        SUB  R2,#1
        SBC  R3,#0
        BRA  .ba_lp
.ba_eq: CLR  R0
        RET

.cm_wordarr:
        CALL pm_fetch_big       ; Len in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1
        CALL pm_pop             ; WA2
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1
        CALL pm_pop             ; WA1
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        LDW  X,#PM_TMP1
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  YH,R1
        MOV  YL,R0
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]

.wa_lp: MOV  R0,R2
        OR   R0,R3
        BEQ  .wa_eq
        LD   R0,[X+]
        LD   R1,[Y+]
        CMP  R0,R1
        BNE  .cm_ret_pos
        LD   R0,[X+]
        LD   R1,[Y+]
        CMP  R0,R1
        BNE  .cm_ret_pos
        SUB  R2,#1
        SBC  R3,#0
        BRA  .wa_lp
.wa_eq: CLR  R0
        RET

.cm_ret_neg:
        MOV  R0,#-1
        RET

.cm_ret_pos:
        MOV  R0,#1
        RET

pm_op_equ:
        CALL pm_cmp_multi
        TST  R0
        BEQ  pm_cmp_t
        BRA  pm_cmp_f

pm_op_neq:
        CALL pm_cmp_multi
        TST  R0
        BNE  pm_cmp_t
        BRA  pm_cmp_f

pm_op_leq:
        CALL pm_cmp_multi
        CMP  R0,#1
        BNE  pm_cmp_t
        BRA  pm_cmp_f

pm_op_geq:
        CALL pm_cmp_multi
        CMP  R0,#-1
        BNE  pm_cmp_t
        BRA  pm_cmp_f

pm_op_les:
        CALL pm_cmp_multi
        CMP  R0,#-1
        BEQ  pm_cmp_t
        BRA  pm_cmp_f

pm_op_grt:
        CALL pm_cmp_multi
        CMP  R0,#1
        BEQ  pm_cmp_t
        BRA  pm_cmp_f
