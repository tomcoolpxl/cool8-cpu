; ---------------------------------------------------------------------
; z3_dict.asm -- Dictionary binary search, string encoding, & sread lexer
; ---------------------------------------------------------------------

; z_encode_word -- encodes 6 ASCII characters at X into (Z_ENC_W1, Z_ENC_W2)
z_encode_word:
        LDW  Y,#$00BC
        CLR  R3                 ; char count 0..5
.enc_c: LD   R0,[X+]
        TST  R0
        BEQ  .pad_c
        CMP  R0,#$20
        BEQ  .pad_c

        CMP  R0,#$61            ; 'a'
        BLO  .chk_up
        CMP  R0,#$7B            ; 'z'+1
        BHS  .chk_punc
        SUB  R0,#$5B            ; 'a' - 6
        BRA  .put_5b

.chk_up:CMP  R0,#$41            ; 'A'
        BLO  .chk_punc
        CMP  R0,#$5B            ; 'Z'+1
        BHS  .chk_punc
        SUB  R0,#$3B            ; 'A' - 6
        BRA  .put_5b

.chk_punc:
        MOV  R0,#5
        BRA  .put_5b

.pad_c: DECW X
        MOV  R0,#5

.put_5b:ST   [Y+],R0
        ADD  R3,#1
        CMP  R3,#6
        BLO  .enc_c

        ; Pack into Word 1: (c0 << 10) | (c1 << 5) | c2
        LDW  Y,#$00BC
        LD   R0,[Y]             ; c0
        SHL  R0
        SHL  R0
        LD   R1,[Y+1]           ; c1
        MOV  R2,R1
        SHR  R2
        SHR  R2
        SHR  R2
        OR   R0,R2              ; R0 = high byte of Word 1
        MOV  R2,R1
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2
        LD   R1,[Y+2]           ; c2
        OR   R2,R1              ; R2 = low byte of Word 1
        LDW  X,#Z_ENC_W1
        ST   [X],R0
        ST   [X+1],R2

        ; Pack into Word 2: (1 << 15) | (c3 << 10) | (c4 << 5) | c5
        LD   R0,[Y+3]           ; c3
        SHL  R0
        SHL  R0
        OR   R0,#$80            ; bit 15 = 1 (terminal word)
        LD   R1,[Y+4]           ; c4
        MOV  R2,R1
        SHR  R2
        SHR  R2
        SHR  R2
        OR   R0,R2              ; R0 = high byte of Word 2
        MOV  R2,R1
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2
        LD   R1,[Y+5]           ; c5
        OR   R2,R1              ; R2 = low byte of Word 2
        LDW  X,#Z_ENC_W2
        ST   [X],R0
        ST   [X+1],R2
        RET

; z_find_dict_word -- binary searches dictionary for (Z_ENC_W1, Z_ENC_W2)
z_find_dict_word:
        LDW  Y,#Z_DICT
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XL,R0
        MOV  XH,R1
        CLR  R1
        PUSHW X
        CALL z_read_byte        ; R0 = num_separators (N)
        POPW X
        ADD  R0,#1
        ADDW X,R0

        ; Read entry length E
        PUSHW X
        CLR  R1
        CALL z_read_byte        ; R0 = entry length E
        MOV  R2,R0
        POPW X
        INCW X

        ; Read entry count C (16-bit word)
        PUSH R2
        PUSHW X
        CLR  R1
        CALL z_read_word        ; X = entry count C
        POPW Y
        POP  R2                 ; R2 = E
        INCW Y
        INCW Y                  ; Y = dictionary table address

        MOV  R0,XL
        MOV  R1,XH
        SUB  R0,#1
        SBC  R1,#0
        MOV  R3,R2

        LDW  X,#$00C2
        CLR  R2
        ST   [X],R2             ; low_L = 0
        ST   [X+1],R2           ; low_H = 0
        ST   [X+2],R0           ; high_L
        ST   [X+3],R1           ; high_H
        ST   [X+4],R3           ; entry_len
        MOV  R2,YL
        ST   [X+5],R2           ; table_base_L
        MOV  R2,YH
        ST   [X+6],R2           ; table_base_H

.bs_lp:
        LDW  X,#$00C2
        LD   R0,[X]             ; low_L
        LD   R1,[X+1]           ; low_H
        LD   R2,[X+2]           ; high_L
        LD   R3,[X+3]           ; high_H

        ; Check if high < low (i.e. high - low < 0) -> not in dictionary
        SUB  R2,R0
        SBC  R3,R1
        BLO  .not_in_dict

        ; mid = (low + high) / 2
        LD   R0,[X]
        LD   R2,[X+2]
        ADD  R0,R2
        LD   R1,[X+1]
        LD   R3,[X+3]
        ADC  R1,R3
        SHR  R1
        ROR  R0                 ; R1:R0 = mid (16-bit)

        ; Save mid in Z_TMP2
        LDW  Y,#Z_TMP2
        ST   [Y],R0             ; mid_L
        ST   [Y+1],R1           ; mid_H

        ; Calculate entry_offset = mid * entry_len (16-bit)
        LDW  Y,#$00C2
        LD   R2,[Y+4]           ; R2 = entry_len
        MUL  R0,R2              ; X = mid_L * entry_len
        TST  R1
        BEQ  .no_mid_hi
        PUSH R2
        MUL  R1,R2              ; X = mid_H * entry_len
        MOV  R0,XL
        POP  R2
        LDW  Y,#Z_TMP2
        LD   R1,[Y]             ; mid_L
        MUL  R1,R2              ; X = mid_L * entry_len
        MOV  R1,XH
        ADD  R1,R0
        MOV  XH,R1              ; add high contribution
.no_mid_hi:

        ; Add table base to X
        LDW  Y,#$00C2
        LD   R0,[Y+5]
        LD   R1,[Y+6]
        ADDW X,R0
        MOV  R0,XH
        ADD  R0,R1
        MOV  XH,R0              ; X = exact 16-bit entry story address!

        ; Read entry word 1
        PUSHW X
        CLR  R1
        CALL z_read_word        ; X = entry word 1
        LDW  Y,#Z_ENC_W1
        LD   R1,[Y]
        LD   R0,[Y+1]           ; R1:R0 = Target Word 1 (high:low)
        MOV  R2,XH
        CMP  R2,R1
        BLO  .w1_lo
        BHI  .w1_hi
        MOV  R2,XL
        CMP  R2,R0
        BLO  .w1_lo
        BHI  .w1_hi

        ; Word 1 matched! Check Word 2
        POPW X
        PUSHW X
        INCW X
        INCW X
        CLR  R1
        CALL z_read_word        ; X = entry word 2
        LDW  Y,#Z_ENC_W2
        LD   R1,[Y]
        LD   R0,[Y+1]           ; R1:R0 = Target Word 2 (high:low)
        MOV  R2,XH
        CMP  R2,R1
        BLO  .w1_lo
        BHI  .w1_hi
        MOV  R2,XL
        CMP  R2,R0
        BLO  .w1_lo
        BHI  .w1_hi

        ; Exactly matched! Return entry address in X
        POPW X
        RET

.w1_lo: ; Entry < Target -> low = mid + 1
        POPW X
        LDW  Y,#Z_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R0,#1
        ADC  R1,#0
        LDW  X,#$00C2
        ST   [X],R0
        ST   [X+1],R1
        BRA  .bs_lp

.w1_hi: ; Entry > Target -> high = mid - 1
        POPW X
        LDW  Y,#Z_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#1
        SBC  R1,#0
        LDW  X,#$00C2
        ST   [X+2],R0
        ST   [X+3],R1
        BRA  .bs_lp

.not_in_dict:
        LDW  X,#0
        RET

; z_sread -- implements sread text_buf, parse_buf
z_sread:
        CALL z_show_status
        CALL z_flush_wrap

        LDW  Y,#Z_OP0
        LD   R1,[Y]
        LD   R0,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        ADDW X,#Z_DYN_BASE
        LD   R3,[X]             ; max input length
        INCW X

        CLR  R2                 ; current length
.in_lp: CALL in_key
        TST  R0
        BEQ  .in_lp

        CMP  R0,#$0D
        BEQ  .in_done
        CMP  R0,#$0A
        BEQ  .in_done

        CMP  R0,#$08
        BEQ  .in_bs
        CMP  R0,#$7F
        BEQ  .in_bs
        CMP  R0,#$86
        BEQ  .in_bs

        CMP  R2,R3
        BHS  .in_lp

        CMP  R0,#$41            ; 'A'
        BLO  .st_c
        CMP  R0,#$5B            ; 'Z'+1
        BHS  .st_c
        ADD  R0,#$20

.st_c:  ST   [X+],R0
        PUSH R0
        PUSH R2
        PUSH R3
        PUSHW X
        CALL con_emit
        POPW X
        POP  R3
        POP  R2
        POP  R0
        ADD  R2,#1
        BRA  .in_lp

.in_bs: TST  R2
        BEQ  .in_lp
        SUB  R2,#1
        DECW X
        LD   R0,[CCX]
        TST  R0
        BEQ  .in_lp
        SUB  R0,#1
        ST   [CCX],R0
        CALL con_setrow
        PUSH R2
        PUSH R3
        PUSHW X
        LD   R0,[CCY]
        LD   R1,[CCX]
        MOV  R2,#$20
        LD   R3,[CATTR]
        CALL con_put
        CALL con_cursor
        POPW X
        POP  R3
        POP  R2
        BRA  .in_lp

.in_done:
        CLR  R0
        ST   [X],R0
        CALL con_nl

        ; X = text buffer at start of string ($2000 + text_buf + 1)
        LDW  Y,#Z_OP0
        LD   R1,[Y]
        LD   R0,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        ADDW X,#Z_DYN_BASE+1

        ; Read max tokens from parse buffer
        LDW  Y,#Z_OP1
        LD   R1,[Y]
        LD   R0,[Y+1]
        MOV  YH,R1
        MOV  YL,R0
        ADDW Y,#Z_DYN_BASE
        LD   R0,[Y]
        LDW  Y,#Z_TMP3
        ST   [Y],R0             ; Z_TMP3 = max_tokens
        CLR  R2                 ; R2 = token count (0)

.tok_lp:LD   R0,[X]
        TST  R0
        BEQ  .tok_done
        CMP  R0,#$20
        BNE  .tok_start
        INCW X
        BRA  .tok_lp

.tok_start:
        PUSHW X                 ; [1] word_start_ptr
        PUSH R2                 ; [2] token count
        CALL z_encode_word
        CALL z_find_dict_word   ; returns dictionary address in X ($0000 if not found)
        LDW  Y,#Z_TMP0
        MOV  R0,XL
        ST   [Y],R0
        MOV  R0,XH
        ST   [Y+1],R0           ; Z_TMP0 = XL, Z_TMP0+1 = XH
        POP  R2
        POPW X                  ; restore word_start_ptr

        ; Measure word length in characters
        PUSHW X
        CLR  R0
.len_lp:LD   R1,[X+]
        TST  R1
        BEQ  .len_done
        CMP  R1,#$20
        BEQ  .len_done
        ADD  R0,#1
        BRA  .len_lp
.len_done:
        LDW  Y,#Z_TMP2
        ST   [Y],R0             ; Z_TMP2 = word length
        POPW Y                  ; Y = word_start_ptr
        PUSHW Y

        ; Calculate 1-based offset in text buffer: (word_start_ptr - text_buf_base)
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        ADDW X,#Z_DYN_BASE
        MOV  R0,YL
        MOV  R1,XL
        SUB  R0,R1              ; R0 = token start offset (1-indexed)

        ; Write parse buffer entry at parse_buf + 2 + token_index * 4
        PUSH R2
        MOV  R1,R2
        SHL  R1
        SHL  R1                 ; R1 = token_index * 4
        LDW  X,#Z_OP1
        LD   R2,[X]
        LD   R3,[X+1]
        MOV  XH,R2
        MOV  XL,R3
        ADDW X,#Z_DYN_BASE+2
        ADDW X,R1
        LDW  Y,#Z_TMP0
        LD   R1,[Y]
        LD   R2,[Y+1]
        ST   [X],R2             ; dict addr high (big-endian)
        ST   [X+1],R1           ; dict addr low
        LDW  Y,#Z_TMP2
        LD   R1,[Y]             ; word length
        ST   [X+2],R1
        ST   [X+3],R0           ; word offset
        POP  R2

        ADD  R2,#1              ; tokens++
        POPW X                  ; restore word_start_ptr
        LDW  Y,#Z_TMP2
        LD   R0,[Y]
        ADDW X,R0               ; advance X past word in text buffer
        LDW  Y,#Z_TMP3
        LD   R0,[Y]             ; R0 = max_tokens
        CMP  R2,R0
        BLO  .tok_lp

.tok_done:
        LDW  X,#Z_OP1
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  YH,R1
        MOV  YL,R0
        ADDW Y,#Z_DYN_BASE+1
        ST   [Y],R2             ; store final num_tokens in parse_buf[1]
        RET
