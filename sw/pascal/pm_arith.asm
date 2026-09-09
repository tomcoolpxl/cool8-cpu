; ---------------------------------------------------------------------
; sw/pascal/pm_arith.asm -- P-Machine Integer, Logical, & Set Operations
; ---------------------------------------------------------------------

pm_op_inc:
        CALL pm_fetch_big       ; Big in R1:R0 (in words)
        SHL  R0                 ; Byte offset = 2 * Words
        ROL  R1
        PUSH R0
        PUSH R1
        CALL pm_pop             ; Address in R1:R0
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        JMP  pm_push

pm_op_chk:
        CALL pm_pop             ; Hi bound in R1:R0
        CALL pm_pop             ; Lo bound in R1:R0
        RET

pm_cmp_t:
        MOV  R0,#1
        CLR  R1
        JMP  pm_push

pm_cmp_f:
        CLR  R0
        CLR  R1
        JMP  pm_push

pm_op_adi:
        CALL pm_pop
        PUSH R0
        PUSH R1
        CALL pm_pop
        POP  R3
        POP  R2
        ADD  R0,R2
        ADC  R1,R3
        JMP  pm_push

pm_op_sbi:
        CALL pm_pop
        PUSH R0
        PUSH R1
        CALL pm_pop
        POP  R3
        POP  R2
        SUB  R0,R2
        SBC  R1,R3
        JMP  pm_push

pm_op_ngi:
        CALL pm_pop
        CLR  R2
        CLR  R3
        SUB  R2,R0
        SBC  R3,R1
        MOV  R0,R2
        MOV  R1,R3
        JMP  pm_push

pm_op_abi:
        CALL pm_pop
        BTST R1,#$80
        BEQ  .ab_pos
        CLR  R2
        CLR  R3
        SUB  R2,R0
        SBC  R3,R1
        MOV  R0,R2
        MOV  R1,R3
.ab_pos:JMP  pm_push

pm_op_land:
        CALL pm_pop
        PUSH R0
        PUSH R1
        CALL pm_pop
        POP  R3
        POP  R2
        AND  R0,R2
        AND  R1,R3
        JMP  pm_push

pm_op_lor:
        CALL pm_pop
        PUSH R0
        PUSH R1
        CALL pm_pop
        POP  R3
        POP  R2
        OR   R0,R2
        OR   R1,R3
        JMP  pm_push

pm_op_lnot:
        CALL pm_pop
        MOV  R2,R0
        OR   R2,R1
        BNE  .lnot_f
        MOV  R0,#1
        CLR  R1
        JMP  pm_push
.lnot_f:
        CLR  R0
        CLR  R1
        JMP  pm_push

pm_op_mpi:
        CALL pm_pop             ; B in R1:R0
        MOV  R2,R0
        MOV  R3,R1
        CALL pm_pop             ; A in R1:R0
        CALL pm_mul16
        JMP  pm_push

pm_op_sqi:
        CALL pm_pop             ; A in R1:R0
        MOV  R2,R0
        MOV  R3,R1
        CALL pm_mul16
        JMP  pm_push

; pm_mul16
; Input: A in R1:R0, B in R3:R2
; Returns Product (A * B) in R1:R0
pm_mul16:
        LDW  Y,#PM_TMP0
        ST   [Y],R0             ; A_low
        ST   [Y+1],R1           ; A_high
        ST   [Y+2],R2           ; B_low
        ST   [Y+3],R3           ; B_high

        CLR  R2                 ; Prod_low = 0
        CLR  R3                 ; Prod_high = 0

        MOV  R0,#16             ; Bit counter

.m16_lp:
        PUSH R0                 ; Save counter
        LDW  Y,#PM_TMP0+2
        LD   R0,[Y]
        LD   R1,[Y+1]
        SHR  R1
        ROR  R0
        ST   [Y],R0
        ST   [Y+1],R1
        BCC  .m16_no_add

        ; Prod += A
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R2,R0
        ADC  R3,R1

.m16_no_add:
        ; A <<= 1
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        SHL  R0
        ROL  R1
        ST   [Y],R0
        ST   [Y+1],R1

        POP  R0                 ; Restore counter
        SUB  R0,#1
        BNE  .m16_lp

        MOV  R0,R2              ; Return product in R1:R0
        MOV  R1,R3
        RET

pm_op_dvi:
        CALL pm_divmod16
        JMP  pm_push

pm_op_modi:
        CALL pm_divmod16
        MOV  R0,R2
        MOV  R1,R3
        JMP  pm_push

; pm_udivmod16:
; Input: Dividend in PM_TMP1, Divisor in PM_TMP0
; Output: Quotient in PM_TMP1 (and R1:R0), Remainder in R3:R2 (and PM_TMP0)
pm_udivmod16:
        CLR  R2
        CLR  R3
        MOV  R0,#16
        LDW  Y,#PM_TMP2
        ST   [Y],R0

.udiv_bit_lp:
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        SHL  R0
        ROL  R1
        ST   [Y],R0
        ST   [Y+1],R1
        ROL  R2
        ROL  R3

        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        CMP  R3,R1
        BLO  .udiv_no_sub
        BNE  .udiv_do_sub
        CMP  R2,R0
        BLO  .udiv_no_sub
.udiv_do_sub:
        SUB  R2,R0
        SBC  R3,R1
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        OR   R0,#1
        ST   [Y],R0

.udiv_no_sub:
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        SUB  R0,#1
        ST   [Y],R0
        BNE  .udiv_bit_lp

        LDW  Y,#PM_TMP0
        ST   [Y],R2
        ST   [Y+1],R3
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        RET

pm_divmod16:
        CALL pm_pop             ; Divisor in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1
        CALL pm_pop             ; Dividend in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        CLR  R2
        LDW  Y,#PM_TMP1+1
        LD   R0,[Y]
        BTST R0,#$80
        BEQ  .div_a_pos
        ADD  R2,#1
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        CLR  R3
        SUB  R3,R0
        ST   [Y],R3
        MOV  R3,#0
        SBC  R3,R1
        ST   [Y+1],R3
.div_a_pos:
        LDW  Y,#PM_TMP0+1
        LD   R0,[Y]
        BTST R0,#$80
        BEQ  .div_b_pos
        XOR  R2,#1
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        CLR  R3
        SUB  R3,R0
        ST   [Y],R3
        MOV  R3,#0
        SBC  R3,R1
        ST   [Y+1],R3
.div_b_pos:
        LDW  Y,#PM_TMP3
        ST   [Y],R2

        CALL pm_udivmod16

        LDW  Y,#PM_TMP3
        LD   R2,[Y]
        TST  R2
        BEQ  .div_done
        CLR  R2
        SUB  R2,R0
        MOV  R0,R2
        MOV  R2,#0
        SBC  R2,R1
        MOV  R1,R2
.div_done:
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        RET

pm_op_equi:
        CALL pm_pop
        PUSH R0
        PUSH R1
        CALL pm_pop
        POP  R3
        POP  R2
        CMP  R0,R2
        BNE  .eq_f
        CMP  R1,R3
        BNE  .eq_f
        JMP  pm_cmp_t
.eq_f:  JMP  pm_cmp_f

pm_op_neqi:
        CALL pm_op_equi
        JMP  pm_op_lnot

pm_cmp_signed_less:
        BTST R1,#$80
        BNE  .csl_a_neg
        BTST R3,#$80
        BNE  .csl_f
        BRA  .csl_same
.csl_a_neg:
        BTST R3,#$80
        BEQ  .csl_t
.csl_same:
        SUB  R0,R2
        SBC  R1,R3
        BTST R1,#$80
        BNE  .csl_t
.csl_f:
        CLR  R0
        RET
.csl_t:
        MOV  R0,#1
        RET

pm_op_lesi:
        CALL pm_pop
        PUSH R0
        PUSH R1
        CALL pm_pop
        POP  R3
        POP  R2
        CALL pm_cmp_signed_less
        TST  R0
        BNE  .les_t
        JMP  pm_cmp_f
.les_t: JMP  pm_cmp_t

pm_op_leqi:
        CALL pm_pop
        PUSH R0
        PUSH R1
        CALL pm_pop
        POP  R3
        POP  R2
        CMP  R0,R2
        BNE  .leq_check_les
        CMP  R1,R3
        BEQ  .leq_t
.leq_check_les:
        CALL pm_cmp_signed_less
        TST  R0
        BNE  .leq_t
        JMP  pm_cmp_f
.leq_t: JMP  pm_cmp_t

pm_op_grti:
        CALL pm_op_leqi
        JMP  pm_op_lnot

pm_op_geqi:
        CALL pm_op_lesi
        JMP  pm_op_lnot

; ---------------------------------------------------------------------
; Set Operations: SGS, SRS, ADJ, UNI, INT, DIF, INN
; ---------------------------------------------------------------------

pm_op_sgs:
        CALL pm_pop             ; i in R1:R0
        TST  R1
        BMI  .sgs_null          ; i < 0
        BNE  .sgs_null          ; i >= 256
        ; WordIdx = i >> 4
        MOV  R3,R0
        SHR  R3
        SHR  R3
        SHR  R3
        SHR  R3
        ; Save Size = WordIdx + 1 in PM_TMP0
        MOV  R2,R3
        ADD  R2,#1
        LDW  Y,#PM_TMP0
        ST   [Y],R2
        ; BitIdx = i & 15
        MOV  R2,R0
        AND  R2,#15
        ; Compute Word W = 1 << BitIdx in R1:R0
        MOV  R0,#1
        CLR  R1
.sgs_b_lp:
        TST  R2
        BEQ  .sgs_b_done
        SHL  R0
        ROL  R1
        SUB  R2,#1
        BRA  .sgs_b_lp
.sgs_b_done:
        PUSH R3                 ; Save WordIdx
        CALL pm_push            ; Push Word W
        POP  R3
.sgs_z_lp:
        TST  R3
        BEQ  .sgs_push_sz
        PUSH R3
        CLR  R0
        CLR  R1
        CALL pm_push            ; Push 0
        POP  R3
        SUB  R3,#1
        BRA  .sgs_z_lp
.sgs_push_sz:
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        CLR  R1
        JMP  pm_push            ; Push Size
.sgs_null:
        CLR  R0
        CLR  R1
        JMP  pm_push            ; Push Size = 0

pm_op_srs:
        CALL pm_pop             ; j in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0             ; j low
        ST   [Y+1],R1           ; j high
        CALL pm_pop             ; i in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0             ; i low
        ST   [Y+1],R1           ; i high

        ; Check valid range: 0 <= i <= j < 256
        TST  R1
        BMI  .srs_null
        BNE  .srs_null
        LDW  Y,#PM_TMP0
        LD   R2,[Y]
        LD   R3,[Y+1]
        TST  R3
        BMI  .srs_null
        BNE  .srs_null
        CMP  R2,R0              ; j vs i
        BLO  .srs_null          ; j < i

        ; Total words S = (j >> 4) + 1
        MOV  R0,R2
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        ADD  R0,#1
        LDW  Y,#PM_TMP2
        ST   [Y],R0             ; S
        SUB  R0,#1
        ST   [Y+1],R0           ; current w = S - 1

.srs_w_lp:
        ; Build word w (bits 15 down to 0)
        CLR  R2                 ; word low
        CLR  R3                 ; word high
        MOV  R0,#15
        LDW  Y,#PM_TMP3
        ST   [Y],R0             ; bit = 15
.srs_b_lp:
        ; Element = (w << 4) | bit
        LDW  Y,#PM_TMP2
        LD   R0,[Y+1]           ; w
        SHL  R0
        SHL  R0
        SHL  R0
        SHL  R0
        LDW  Y,#PM_TMP3
        LD   R1,[Y]             ; bit
        OR   R0,R1              ; Element in R0

        ; Check i <= Element <= j
        LDW  Y,#PM_TMP1
        LD   R1,[Y]             ; i
        CMP  R0,R1
        BLO  .srs_bit_0
        LDW  Y,#PM_TMP0
        LD   R1,[Y]             ; j
        CMP  R0,R1
        BHI  .srs_bit_0
        SEC
        BRA  .srs_bit_shift
.srs_bit_0:
        CLC
.srs_bit_shift:
        ROL  R2
        ROL  R3
        LDW  Y,#PM_TMP3
        LD   R0,[Y]             ; bit
        SUB  R0,#1
        ST   [Y],R0
        BPL  .srs_b_lp          ; repeat while bit >= 0

        ; Push Word w
        MOV  R0,R2
        MOV  R1,R3
        CALL pm_push

        ; Decrement w
        LDW  Y,#PM_TMP2
        LD   R0,[Y+1]
        SUB  R0,#1
        ST   [Y+1],R0
        BPL  .srs_w_lp

        ; Push Size S
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        CLR  R1
        JMP  pm_push

.srs_null:
        CLR  R0
        CLR  R1
        JMP  pm_push            ; Push Size = 0

pm_op_adj:
        CALL pm_fetch_b         ; S in R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0             ; S
        CLR  R0
        ST   [Y+1],R0

        CALL pm_pop             ; szorig in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0             ; szorig
        ST   [Y+1],R1

        ; Read S words from PM_SP into PM_SEC_BUF (zero-fill if k >= szorig)
        CLR  R0
        LDW  Y,#PM_SET_K
        ST   [Y],R0

.adj_rd_lp:
        LDW  Y,#PM_SET_K
        LD   R0,[Y]             ; k
        LDW  Y,#PM_TMP0
        LD   R1,[Y]             ; S
        CMP  R0,R1
        BHS  .adj_rd_done

        ; Default word = 0
        CLR  R2
        CLR  R3
        LDW  Y,#PM_TMP1
        LD   R1,[Y]             ; szorig
        CMP  R0,R1
        BHS  .adj_st_buf        ; if k >= szorig, word is 0

        ; Word = [PM_SP + 2 * k]
        SHL  R0                 ; R0 = 2 * k
        LDW  Y,#PM_SP
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R2,R0
        ADC  R3,#0
        MOV  XH,R3
        MOV  XL,R2
        LD   R2,[X]
        LD   R3,[X+1]

.adj_st_buf:
        LDW  Y,#PM_SET_K
        LD   R0,[Y]             ; k
        SHL  R0                 ; 2 * k
        LDW  X,#PM_SEC_BUF
        ADDW X,R0
        ST   [X+],R2
        ST   [X],R3

        LDW  Y,#PM_SET_K
        LD   R0,[Y]
        ADD  R0,#1
        ST   [Y],R0
        BRA  .adj_rd_lp

.adj_rd_done:
        ; BASE = old_SP + szorig * 2
        LDW  Y,#PM_SP
        LD   R2,[Y]
        LD   R3,[Y+1]
        LDW  Y,#PM_TMP1
        LD   R0,[Y]             ; szorig
        SHL  R0
        ADD  R2,R0
        ADC  R3,#0              ; R3:R2 = BASE

        ; new_SP = BASE - S * 2
        LDW  Y,#PM_TMP0
        LD   R0,[Y]             ; S
        SHL  R0
        SUB  R2,R0
        SBC  R3,#0              ; R3:R2 = new_SP
        LDW  Y,#PM_SP
        ST   [Y],R2
        ST   [Y+1],R3           ; PM_SP = new_SP

        ; Copy S words from PM_SEC_BUF to new_SP
        CLR  R0
        LDW  Y,#PM_SET_K
        ST   [Y],R0

.adj_wr_lp:
        LDW  Y,#PM_SET_K
        LD   R0,[Y]             ; k
        LDW  Y,#PM_TMP0
        LD   R1,[Y]             ; S
        CMP  R0,R1
        BHS  .adj_done

        SHL  R0                 ; 2 * k
        LDW  Y,#PM_SEC_BUF
        ADDW Y,R0
        LD   R2,[Y+]
        LD   R3,[Y]             ; R3:R2 = word

        LDW  Y,#PM_SET_K
        LD   R0,[Y]             ; k
        SHL  R0                 ; 2 * k
        LDW  X,[PM_SP]
        ADDW X,R0
        ST   [X+],R2
        ST   [X],R3

        LDW  Y,#PM_SET_K
        LD   R0,[Y]
        ADD  R0,#1
        ST   [Y],R0
        BRA  .adj_wr_lp

.adj_done:
        RET

pm_op_uni:
        MOV  R0,#0
        BRA  pm_set_binop
pm_op_int:
        MOV  R0,#1
        BRA  pm_set_binop
pm_op_dif:
        MOV  R0,#2
pm_set_binop:
        LDW  Y,#PM_SET_OP
        ST   [Y],R0             ; save operation (0=UNI, 1=INT, 2=DIF)

        CALL pm_pop             ; S2 in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0             ; TMP0 = S2
        CLR  R1
        ST   [Y+1],R1

        ; Addr2 = PM_SP
        LDW  Y,#PM_SP
        LD   R2,[Y]
        LD   R3,[Y+1]
        LDW  Y,#PM_TMP2
        ST   [Y],R2             ; TMP2 = Addr2
        ST   [Y+1],R3

        ; Skip Set2: PM_SP += S2 * 2
        LDW  Y,#PM_TMP0
        LD   R0,[Y]             ; S2
        SHL  R0
        ADD  R2,R0
        ADC  R3,#0
        LDW  Y,#PM_SP
        ST   [Y],R2
        ST   [Y+1],R3

        CALL pm_pop             ; S1 in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0             ; TMP1 = S1
        CLR  R1
        ST   [Y+1],R1

        ; Addr1 = PM_SP
        LDW  Y,#PM_SP
        LD   R2,[Y]
        LD   R3,[Y+1]
        LDW  Y,#PM_TMP3
        ST   [Y],R2             ; TMP3 = Addr1
        ST   [Y+1],R3

        ; Calculate S_result in PM_TMP4:
        ; If UNI (op 0): max(S1, S2)
        ; If INT (op 1): min(S1, S2)
        ; If DIF (op 2): S1
        LDW  Y,#PM_TMP1
        LD   R0,[Y]             ; S1
        LDW  Y,#PM_SET_OP
        LD   R1,[Y]
        CMP  R1,#2
        BEQ  .binop_have_sres   ; DIF -> S1
        LDW  Y,#PM_TMP0
        LD   R2,[Y]             ; S2
        CMP  R1,#1
        BEQ  .binop_calc_min    ; INT -> min(S1, S2)
        ; UNI -> max(S1, S2)
        CMP  R0,R2
        BHS  .binop_have_sres
        MOV  R0,R2
        BRA  .binop_have_sres
.binop_calc_min:
        CMP  R0,R2
        BLS  .binop_have_sres
        MOV  R0,R2
.binop_have_sres:
        LDW  Y,#PM_TMP4
        ST   [Y],R0             ; TMP4 = S_res
        CLR  R1
        ST   [Y+1],R1

        ; Compute S_res words into PM_SEC_BUF
        CLR  R0
        LDW  Y,#PM_SET_K
        ST   [Y],R0

.binop_lp:
        LDW  Y,#PM_SET_K
        LD   R0,[Y]             ; k
        LDW  Y,#PM_TMP4
        LD   R1,[Y]             ; S_res
        CMP  R0,R1
        BHS  .binop_done

        ; Fetch Word1 from Addr1[k] (0 if k >= S1)
        CLR  R2
        CLR  R3
        LDW  Y,#PM_TMP1
        LD   R1,[Y]             ; S1
        CMP  R0,R1
        BHS  .binop_have_w1
        SHL  R0                 ; 2 * k
        LDW  Y,#PM_TMP3
        LD   R2,[Y]
        LD   R3,[Y+1]           ; Addr1
        ADD  R2,R0
        ADC  R3,#0
        MOV  XH,R3
        MOV  XL,R2
        LD   R2,[X]
        LD   R3,[X+1]
.binop_have_w1:
        LDW  Y,#PM_SET_W1
        ST   [Y],R2
        ST   [Y+1],R3

        ; Fetch Word2 from Addr2[k] (0 if k >= S2)
        CLR  R2
        CLR  R3
        LDW  Y,#PM_SET_K
        LD   R0,[Y]             ; k
        LDW  Y,#PM_TMP0
        LD   R1,[Y]             ; S2
        CMP  R0,R1
        BHS  .binop_have_w2
        SHL  R0                 ; 2 * k
        LDW  Y,#PM_TMP2
        LD   R2,[Y]
        LD   R3,[Y+1]           ; Addr2
        ADD  R2,R0
        ADC  R3,#0
        MOV  XH,R3
        MOV  XL,R2
        LD   R2,[X]
        LD   R3,[X+1]
.binop_have_w2:
        ; Now combine Word1 (in PM_SET_W1) and Word2 (in R3:R2)
        LDW  Y,#PM_SET_OP
        LD   R0,[Y]
        TST  R0
        BNE  .binop_not_uni
        ; UNI: Word1 | Word2
        LDW  Y,#PM_SET_W1
        LD   R0,[Y]
        LD   R1,[Y+1]
        OR   R0,R2
        OR   R1,R3
        BRA  .binop_st_buf
.binop_not_uni:
        CMP  R0,#2
        BNE  .binop_is_int
        ; DIF: Word1 & ~Word2
        XOR  R2,#$FF
        XOR  R3,#$FF
.binop_is_int:
        ; INT or DIF: Word1 & Word2
        LDW  Y,#PM_SET_W1
        LD   R0,[Y]
        LD   R1,[Y+1]
        AND  R0,R2
        AND  R1,R3
.binop_st_buf:
        ; Store R1:R0 into PM_SEC_BUF[2*k]
        LDW  Y,#PM_SET_K
        LD   R2,[Y]
        SHL  R2
        LDW  X,#PM_SEC_BUF
        ADDW X,R2
        ST   [X+],R0
        ST   [X],R1

        LDW  Y,#PM_SET_K
        LD   R0,[Y]
        ADD  R0,#1
        ST   [Y],R0
        BRA  .binop_lp

.binop_done:
        ; BASE = Addr1 + S1 * 2
        LDW  Y,#PM_TMP3
        LD   R2,[Y]
        LD   R3,[Y+1]
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        SHL  R0
        ADD  R2,R0
        ADC  R3,#0

        ; PM_SP = BASE - S_res * 2
        LDW  Y,#PM_TMP4
        LD   R0,[Y]             ; S_res
        SHL  R0
        SUB  R2,R0
        SBC  R3,#0
        LDW  Y,#PM_SP
        ST   [Y],R2
        ST   [Y+1],R3

        ; Copy S_res words from PM_SEC_BUF to PM_SP
        CLR  R0
        LDW  Y,#PM_SET_K
        ST   [Y],R0
.binop_cp_lp:
        LDW  Y,#PM_SET_K
        LD   R0,[Y]
        LDW  Y,#PM_TMP4
        LD   R1,[Y]
        CMP  R0,R1
        BHS  .binop_push_res
        SHL  R0
        LDW  Y,#PM_SEC_BUF
        ADDW Y,R0
        LD   R2,[Y+]
        LD   R3,[Y]
        LDW  Y,#PM_SET_K
        LD   R0,[Y]
        SHL  R0
        LDW  X,[PM_SP]
        ADDW X,R0
        ST   [X+],R2
        ST   [X],R3
        LDW  Y,#PM_SET_K
        LD   R0,[Y]
        ADD  R0,#1
        ST   [Y],R0
        BRA  .binop_cp_lp

.binop_push_res:
        LDW  Y,#PM_TMP4
        LD   R0,[Y]
        CLR  R1
        JMP  pm_push




pm_op_inn:
        ; Stack layout on entry:
        ; [PM_SP]     = Size in words (sza)
        ; [PM_SP + 2] = set[0]
        ; ...
        ; [PM_SP + 2 + 2*sza] = Val (i)
        ; [PM_SP + 4 + 2*sza] = rest of stack
        CALL pm_pop             ; Size in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0             ; Size low
        ST   [Y+1],R1           ; Size high

        ; Addr_set = PM_SP (points to set[0])
        LDW  Y,#PM_SP
        LD   R2,[Y]
        LD   R3,[Y+1]
        LDW  Y,#PM_TMP2
        ST   [Y],R2             ; Addr_set low
        ST   [Y+1],R3           ; Addr_set high

        ; Addr_i = Addr_set + Size * 2
        LDW  Y,#PM_TMP1
        LD   R0,[Y]             ; Size
        SHL  R0
        ADD  R2,R0
        ADC  R3,#0
        MOV  XH,R3
        MOV  XL,R2
        LD   R0,[X]             ; Val low
        LD   R1,[X+1]           ; Val high
        LDW  Y,#PM_TMP0
        ST   [Y],R0             ; Val low
        ST   [Y+1],R1           ; Val high

        ; Advance PM_SP past Val: Addr_i + 2
        ADD  R2,#2
        ADC  R3,#0
        LDW  Y,#PM_SP
        ST   [Y],R2
        ST   [Y+1],R3

        ; Check if Val in range: Val < 0 or Val high != 0
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        TST  R1
        BMI  .inn_f             ; Val < 0
        BNE  .inn_f             ; Val >= 256

        ; WordIdx = Val >> 4
        MOV  R1,R0
        SHR  R1
        SHR  R1
        SHR  R1
        SHR  R1                 ; WordIdx in R1

        ; Check if WordIdx >= Size
        LDW  Y,#PM_TMP1
        LD   R2,[Y]             ; Size
        CMP  R1,R2
        BHS  .inn_f             ; WordIdx >= Size

        ; Load set[WordIdx]
        SHL  R1                 ; 2 * WordIdx
        LDW  Y,#PM_TMP2
        LD   R2,[Y]
        LD   R3,[Y+1]           ; Addr_set
        ADD  R2,R1
        ADC  R3,#0
        MOV  XH,R3
        MOV  XL,R2
        LD   R2,[X]
        LD   R3,[X+1]           ; Word in R3:R2

        ; BitIdx = Val & 15
        AND  R0,#15
.inn_sh_lp:
        TST  R0
        BEQ  .inn_test
        SHR  R3
        ROR  R2
        SUB  R0,#1
        BRA  .inn_sh_lp
.inn_test:
        BTST R2,#$01
        BNE  .inn_t
.inn_f: JMP  pm_cmp_f
.inn_t: JMP  pm_cmp_t
