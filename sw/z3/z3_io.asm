; ---------------------------------------------------------------------
; z3_io.asm -- Statusline, screen clear, numbers out, and cursor restore
; ---------------------------------------------------------------------

; z_print_num -- prints signed 16-bit integer in X (Z_OP0)
z_print_num:
        MOV  R0,XH
        BTST R0,#$80
        BEQ  .pos_num
        PUSHW X
        MOV  R0,#$2D            ; '-'
        CALL z_putc
        POPW X
        MOV  R0,XL
        NOT  R0
        MOV  XL,R0
        MOV  R0,XH
        NOT  R0
        MOV  XH,R0
        INCW X

.pos_num:
        CLR  R3                 ; digit count
.div_lp:MOV  R1,XH
        MOV  R0,XL
        PUSH R3
        CALL num_div10          ; X = quotient, R0 = remainder
        POP  R3
        ADD  R0,#$30            ; '0'
        PUSH R0
        ADD  R3,#1
        MOV  R0,XL
        MOV  R1,XH
        OR   R0,R1
        BNE  .div_lp

.emit_d:POP  R0
        PUSH R3
        CALL z_putc
        POP  R3
        SUB  R3,#1
        BNE  .emit_d
        RET

num_div10:
        MOV  R2,XH
        MOV  R3,XL
        LDW  X,#0
        CLR  R0
        MOV  R1,#16
.d10_lp:SHL  R3
        ROL  R2
        ROL  R0
        CMP  R0,#10
        BLO  .d10_nxt
        SUB  R0,#10
        ADD  R3,#1
.d10_nxt:
        SUB  R1,#1
        BNE  .d10_lp
        MOV  XH,R2
        MOV  XL,R3
        RET

; z_show_status -- paints the top-row status bar
z_show_status:
        CALL z_flush_wrap

        LD   R0,[CCX]
        LD   R1,[CCY]
        PUSH R0
        PUSH R1

        CLR  R0
        ST   [CCX],R0
        ST   [CCY],R0
        CALL con_setrow

        LD   R0,[CATTR]
        PUSH R0
        LD   R0,[z_color_status]
        ST   [CATTR],R0

        CLR  R0
        CALL con_fill

        MOV  R0,#1
        ST   [CCX],R0
        CLR  R0
        ST   [CCY],R0

        ; Read global variable 0 (room object)
        LDW  Y,#Z_GLOBS
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XL,R0
        MOV  XH,R1
        CLR  R1
        CALL z_read_word
        MOV  R0,XL
        CALL z_print_obj
        CALL z_flush_wrap

        LD   R1,[CCOLS]
        SUB  R1,#26
        ST   [CCX],R1

        LDW  X,#.str_sc
        CALL con_puts

        ; Read global variable 1 (Score)
        LDW  Y,#Z_GLOBS
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XL,R0
        MOV  XH,R1
        INCW X
        INCW X
        CLR  R1
        CALL z_read_word
        CALL z_print_num
        CALL z_flush_wrap

        LDW  X,#.str_mv
        CALL con_puts

        ; Read global variable 2 (Moves)
        LDW  Y,#Z_GLOBS
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XL,R0
        MOV  XH,R1
        ADDW X,#4
        CLR  R1
        CALL z_read_word
        CALL z_print_num
        CALL z_flush_wrap

        POP  R0
        ST   [CATTR],R0
        POP  R1
        POP  R0
        ST   [CCY],R1
        ST   [CCX],R0
        CALL con_setrow
        CALL con_cursor
        RET

.str_sc:.asciz "Score: "
.str_mv:.asciz "  Moves: "
