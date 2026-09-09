; ---------------------------------------------------------------------
; z3_text.asm -- Z-Character text decompression, abbreviations, & wrapping
; ---------------------------------------------------------------------

z_a2_table:
        .byte $30, $31, $32, $33, $34, $35, $36, $37, $38, $39 ; 0123456789
        .byte $2E, $2C, $21, $3F, $5F, $23, $27, $22, $2F, $5C ; .,!?_#'"/\
        .byte $2D, $3A, $28, $29                               ; -:()

Z_TXT_ALPH      = $00B0         ; Current alphabet (0=A0, 1=A1, 2=A2)
Z_TXT_SHIFT     = $00B1         ; Shift state (0=none, 1=A1, 2=A2)
Z_TXT_ABBR      = $00B2         ; Abbrev mode (0=none, 1=bank 0, 2=bank 1, 3=bank 2)
Z_TXT_ZSCII     = $00B3         ; ZSCII mode (0=none, 1=hi, 2=lo)
Z_TXT_ZHI       = $00B4         ; ZSCII high 5 bits

; z_print_paddr -- prints Z-string at packed address in X
z_print_paddr:
        CLR  R1
        MOV  R2,XL
        MOV  R3,XH
        SHL  R2
        ROL  R3
        ROL  R1                 ; R1:X = byte address = paddr * 2
        MOV  XL,R2
        MOV  XH,R3
        JMP  z_print_zstr

; z_print_addr -- prints Z-string at byte address in X
z_print_addr:
        CLR  R1
        JMP  z_print_zstr

; z_print_zstr -- decodes and prints Z-string at (R1:X), returns updated (R1:X)
z_print_zstr:
        PUSHW Y
        LDW  Y,#Z_TXT_ALPH
        CLR  R0
        ST   [Y],R0             ; alph = 0
        ST   [Y+1],R0           ; shift = 0
        ST   [Y+2],R0           ; abbrev = 0
        ST   [Y+3],R0           ; zscii = 0
        POPW Y

.wrd_lp:
        PUSH R1
        PUSHW X
        CALL z_read_word        ; X = 16-bit word
        MOVW Y,X                ; Y = 16-bit word
        POPW X
        POP  R1
        INCW X
        INCW X
        BNE  .nw
        ADD  R1,#1
.nw:
        ; Char 1 = (Y >> 10) & $1F
        MOV  R0,YH
        SHR  R0
        SHR  R0
        AND  R0,#$1F
        PUSH R1
        PUSHW X
        PUSHW Y
        CALL z_decode_char

        ; Char 2 = (Y >> 5) & $1F
        POPW Y
        MOV  R0,YH
        SHL  R0
        SHL  R0
        SHL  R0
        MOV  R2,YL
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        OR   R0,R2
        AND  R0,#$1F
        PUSHW Y
        CALL z_decode_char

        ; Char 3 = Y & $1F
        POPW Y
        MOV  R0,YL
        AND  R0,#$1F
        PUSHW Y
        CALL z_decode_char
        POPW Y
        POPW X
        POP  R1

        ; Check terminal bit 15 of Y
        MOV  R0,YH
        BTST R0,#$80
        BEQ  .wrd_lp            ; loop if bit 15 is 0
        RET

; z_decode_char -- decodes single 5-bit Z-character in R0
z_decode_char:
        LDW  X,#Z_TXT_ABBR
        LD   R2,[X]
        TST  R2
        BEQ  .not_abbr

        ; Abbreviation: index = (R2 - 1) * 32 + R0
        CLR  R3
        ST   [X],R3             ; reset abbrev mode
        SUB  R2,#1
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2                 ; R2 = (R2 - 1) * 32
        OR   R2,R0              ; R2 = abbrev index 0..95

        CLR  R3
        SHL  R2
        ROL  R3                 ; R3:R2 = index * 2
        LDW  Y,#Z_ABBREV
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XL,R0
        MOV  XH,R1
        ADDW X,R2
        CLR  R1
        CALL z_read_word        ; X = packed string address

        ; Preserve alphabet state across abbreviation
        LDW  Y,#Z_TXT_ALPH
        LD   R0,[Y]
        PUSH R0                 ; save caller alphabet
        CALL z_print_paddr
        POP  R0
        LDW  Y,#Z_TXT_ALPH
        ST   [Y],R0             ; restore caller alphabet
        CLR  R0
        ST   [Y+1],R0           ; reset shift to 0
        ST   [Y+2],R0           ; reset abbrev mode to 0
        ST   [Y+3],R0           ; reset zscii mode to 0
        RET

.not_abbr:
        LDW  X,#Z_TXT_ZSCII
        LD   R2,[X]
        TST  R2
        BEQ  .not_zscii
        CMP  R2,#1
        BNE  .zscii2
        LDW  X,#Z_TXT_ZHI
        ST   [X],R0
        LDW  X,#Z_TXT_ZSCII
        MOV  R0,#2
        ST   [X],R0
        RET

.zscii2:
        LDW  X,#Z_TXT_ZHI
        LD   R2,[X]
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2
        OR   R0,R2              ; R0 = raw ASCII character
        LDW  X,#Z_TXT_ZSCII
        CLR  R2
        ST   [X],R2
        JMP  z_putc

.not_zscii:
        TST  R0
        BNE  .not_spc
        MOV  R0,#$20            ; space
        JMP  z_putc

.not_spc:
        CMP  R0,#4
        BHS  .not_ab_sel
        LDW  X,#Z_TXT_ABBR
        ST   [X],R0
        RET

.not_ab_sel:
        CMP  R0,#4
        BNE  .not_sh4
        LDW  X,#Z_TXT_SHIFT
        MOV  R0,#1              ; shift to A1
        ST   [X],R0
        RET

.not_sh4:
        CMP  R0,#5
        BNE  .not_sh5
        LDW  X,#Z_TXT_SHIFT
        MOV  R0,#2              ; shift to A2
        ST   [X],R0
        RET

.not_sh5:
        LDW  X,#Z_TXT_SHIFT
        LD   R2,[X]
        TST  R2
        BNE  .use_shift
        LDW  X,#Z_TXT_ALPH
        LD   R2,[X]             ; R2 = current alphabet (0, 1, 2)
        BRA  .do_alph

.use_shift:
        CLR  R3
        ST   [X],R3

.do_alph:
        TST  R2
        BEQ  .is_a0
        CMP  R2,#1
        BEQ  .is_a1

        ; Alphabet 2 (A2)
        CMP  R0,#6
        BNE  .not_zesc
        LDW  X,#Z_TXT_ZSCII
        MOV  R0,#1
        ST   [X],R0
        RET

.not_zesc:
        CMP  R0,#7
        BNE  .not_a2_nl
        MOV  R0,#$0A            ; newline
        JMP  z_putc

.not_a2_nl:
        SUB  R0,#8
        LDW  X,#z_a2_table
        ADDW X,R0
        LD   R0,[X]
        JMP  z_putc

.is_a0:
        SUB  R0,#6
        ADD  R0,#$61            ; 'a'
        JMP  z_putc

.is_a1:
        SUB  R0,#6
        ADD  R0,#$41            ; 'A'
        JMP  z_putc

; z_putc -- emits character in R0 with word wrapping
z_putc:
        CMP  R0,#$0A            ; newline
        BEQ  .flush_nl
        CMP  R0,#$20            ; space
        BEQ  .flush_spc

        LDW  X,#Z_WRAP_LEN
        LD   R1,[X]
        CMP  R1,#30
        BHS  .force_emit
        LDW  Y,#Z_WRAP_BUF
        ADDW Y,R1
        ST   [Y],R0
        ADD  R1,#1
        ST   [X],R1
        RET

.force_emit:
        PUSH R0
        CALL z_flush_wrap
        POP  R0
        JMP  con_emit

.flush_spc:
        CALL z_flush_wrap
        MOV  R0,#$20
        JMP  con_emit

.flush_nl:
        CALL z_flush_wrap
        CALL z_clr_eol
        JMP  con_nl

; z_clr_eol -- clears from cursor CCX to CCOLS-1 with spaces
z_clr_eol:
        LD   R1,[CCX]
        LD   R0,[CCOLS]
        CMP  R1,R0
        BHS  .eol_done
        MOV  R2,#$20
        LD   R3,[CATTR]
.eol_lp:PUSH R0
        PUSH R1
        PUSH R2
        PUSH R3
        LD   R0,[CCY]
        CALL con_put            ; con_put(row=R0, col=R1, char=R2, attr=R3)
        POP  R3
        POP  R2
        POP  R1
        POP  R0
        ADD  R1,#1
        CMP  R1,R0
        BLO  .eol_lp
.eol_done:
        RET

; z_flush_wrap -- outputs the buffered word, wrapping to new line if necessary
z_flush_wrap:
        LDW  X,#Z_WRAP_LEN
        LD   R2,[X]
        TST  R2
        BEQ  .done_fl

        LD   R0,[CCX]
        ADD  R0,R2
        LD   R1,[CCOLS]
        SUB  R1,#1
        CMP  R0,R1
        BLO  .fit
        CALL z_clr_eol
        CALL con_nl

.fit:
        LDW  X,#Z_WRAP_LEN
        LD   R2,[X]
        TST  R2
        BEQ  .done_fl

        LDW  Y,#Z_WRAP_BUF
.em_lp: LD   R0,[Y+]
        PUSH R2
        PUSHW Y
        CALL con_emit
        POPW Y
        POP  R2
        SUB  R2,#1
        BNE  .em_lp

        LDW  X,#Z_WRAP_LEN
        CLR  R0
        ST   [X],R0

.done_fl:
        RET
