; ---------------------------------------------------------------------
; z3_main.asm -- Header parser, loader, and main instruction loop
; ---------------------------------------------------------------------

z_init_restart:
        CALL z_init_cache

        CLR  R0
        ST   [FLS_CTRL],R0
        LDW  X,#Z_FLS_L
        LD   R0,[X]
        ST   [FLS_ADDR_L],R0
        LD   R1,[X+1]
        ST   [FLS_ADDR_M],R1
        LD   R2,[X+2]
        ST   [FLS_ADDR_H],R2
        MOV  R0,#1
        ST   [FLS_CTRL],R0

        LDW  X,#Z_DYN_BASE
        MOV  R0,#64
.hdr_lp:LD   R1,[FLS_DATA]
        ST   [X+],R1
        SUB  R0,#1
        BNE  .hdr_lp

        ; HighMem: [Z_DYN_BASE+4..5]
        LDW  X,#Z_DYN_BASE+4
        LD   R1,[X]
        LD   R0,[X+1]
        LDW  Y,#Z_HIMEM
        ST   [Y],R0
        ST   [Y+1],R1

        ; InitPC: [Z_DYN_BASE+6..7]
        LDW  X,#Z_DYN_BASE+6
        LD   R1,[X]
        LD   R0,[X+1]
        LDW  Y,#Z_PC_L
        ST   [Y],R0
        ST   [Y+1],R1
        CLR  R0
        ST   [Y+2],R0

        ; Dict: [Z_DYN_BASE+8..9]
        LDW  X,#Z_DYN_BASE+8
        LD   R1,[X]
        LD   R0,[X+1]
        LDW  Y,#Z_DICT
        ST   [Y],R0
        ST   [Y+1],R1

        ; Objects: [Z_DYN_BASE+10..11]
        LDW  X,#Z_DYN_BASE+10
        LD   R1,[X]
        LD   R0,[X+1]
        LDW  Y,#Z_OBJS
        ST   [Y],R0
        ST   [Y+1],R1

        ; Globals: [Z_DYN_BASE+12..13]
        LDW  X,#Z_DYN_BASE+12
        LD   R1,[X]
        LD   R0,[X+1]
        LDW  Y,#Z_GLOBS
        ST   [Y],R0
        ST   [Y+1],R1

        ; StaticBase: [Z_DYN_BASE+14..15]
        LDW  X,#Z_DYN_BASE+14
        LD   R1,[X]
        LD   R0,[X+1]
        LDW  Y,#Z_STATIC
        ST   [Y],R0
        ST   [Y+1],R1

        ; Abbrev: [Z_DYN_BASE+24..25]
        LDW  X,#Z_DYN_BASE+24
        LD   R1,[X]
        LD   R0,[X+1]
        LDW  Y,#Z_ABBREV
        ST   [Y],R0
        ST   [Y+1],R1

        ; Length = StaticBase - 64
        LDW  X,#Z_STATIC
        LD   R0,[X]
        LD   R1,[X+1]
        SUB  R0,#64
        SBC  R1,#0

        LDW  X,#Z_DYN_BASE+64
.dyn_lp:TST  R0
        BNE  .dyn_b
        TST  R1
        BEQ  .dyn_done
.dyn_b: LD   R2,[FLS_DATA]
        ST   [X+],R2
        SUB  R0,#1
        SBC  R1,#0
        BRA  .dyn_lp

.dyn_done:
        CLR  R0
        ST   [FLS_CTRL],R0      ; close read stream

        LDW  X,#Z_SP
        CLR  R0
        ST   [X],R0
        ST   [X+1],R0
        LDW  X,#Z_FP
        ST   [X],R0
        ST   [X+1],R0
        LDW  X,#Z_CALL_DEPTH
        ST   [X],R0
        LDW  X,#Z_QUIT
        ST   [X],R0
        LDW  X,#Z_WRAP_LEN
        ST   [X],R0
        LDW  X,#Z_RND_SEED
        MOV  R0,#$5A
        ST   [X],R0

z_main_loop:
        LDW  X,#Z_QUIT
        LD   R0,[X]
        TST  R0
        BNE  z_main_exit

        CALL z_fetch_pc_byte
        LDW  Y,#Z_TMP3
        ST   [Y],R0             ; save full opcode in Z_TMP3
        MOV  R3,R0

        CMP  R3,#$80
        BLO  .is_2op_long
        CMP  R3,#$B0
        BLO  .is_1op
        CMP  R3,#$C0
        BLO  .is_0op
        CMP  R3,#$E0
        BLO  .is_2op_var
        BRA  .is_var

.is_2op_long:
        LDW  Y,#Z_TMP3
        LD   R3,[Y]

        BTST R3,#$40
        BNE  .op0_var
        CALL z_fetch_pc_byte
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1
        BRA  .st_op0
.op0_var:
        CALL z_fetch_pc_byte
        CALL z_read_var
.st_op0:LDW  Y,#Z_OP0
        MOV  R0,XH
        ST   [Y],R0
        MOV  R0,XL
        ST   [Y+1],R0

        LDW  Y,#Z_TMP3
        LD   R3,[Y]             ; reload full opcode
        BTST R3,#$20
        BNE  .op1_var
        CALL z_fetch_pc_byte
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1
        BRA  .st_op1
.op1_var:
        CALL z_fetch_pc_byte
        CALL z_read_var
.st_op1:LDW  Y,#Z_OP1
        MOV  R0,XH
        ST   [Y],R0
        MOV  R0,XL
        ST   [Y+1],R0

        LDW  Y,#Z_OPCOUNT
        MOV  R0,#2
        ST   [Y],R0

        LDW  Y,#Z_TMP3
        LD   R0,[Y]
        AND  R0,#$1F
        ADD  R0,R0
        LDW  X,#z_table_2op
        ADDW X,R0
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XL,R0
        MOV  XH,R1
        CALL [X]
        BRA  z_main_loop

.is_1op:
        LDW  Y,#Z_TMP3
        LD   R3,[Y]

        MOV  R0,R3
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        AND  R0,#3
        BEQ  .op1_large
        CMP  R0,#1
        BEQ  .op1_small
        CALL z_fetch_pc_byte
        CALL z_read_var
        BRA  .st_1op

.op1_large:
        CALL z_fetch_pc_word
        BRA  .st_1op

.op1_small:
        CALL z_fetch_pc_byte
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1

.st_1op:LDW  Y,#Z_OP0
        MOV  R0,XH
        ST   [Y],R0
        MOV  R0,XL
        ST   [Y+1],R0

        LDW  Y,#Z_OPCOUNT
        MOV  R0,#1
        ST   [Y],R0

        LDW  Y,#Z_TMP3
        LD   R0,[Y]
        AND  R0,#$0F
        ADD  R0,R0
        LDW  X,#z_table_1op
        ADDW X,R0
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XL,R0
        MOV  XH,R1
        CALL [X]
        BRA  z_main_loop

.is_0op:
        LDW  Y,#Z_TMP3
        LD   R0,[Y]
        AND  R0,#$0F
        ADD  R0,R0
        LDW  X,#z_table_0op
        ADDW X,R0
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XL,R0
        MOV  XH,R1
        CALL [X]
        BRA  z_main_loop

.is_2op_var:
        CALL z_decode_var_operands

        LDW  Y,#Z_TMP3
        LD   R0,[Y]
        AND  R0,#$1F
        ADD  R0,R0
        LDW  X,#z_table_2op
        ADDW X,R0
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XL,R0
        MOV  XH,R1
        CALL [X]
        BRA  z_main_loop

.is_var:
        CALL z_decode_var_operands

        LDW  Y,#Z_TMP3
        LD   R0,[Y]
        AND  R0,#$1F
        ADD  R0,R0
        LDW  X,#z_table_var
        ADDW X,R0
        LD   R0,[X]
        LD   R1,[X+1]
        MOV  XL,R0
        MOV  XH,R1
        CALL [X]
        BRA  z_main_loop

z_decode_var_operands:
        CALL z_fetch_pc_byte
        MOV  R2,R0
        CLR  R3

.var_op_lp:
        MOV  R0,R2
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        AND  R0,#3

        CMP  R0,#3
        BEQ  .var_ops_done

        PUSH R2
        PUSH R3
        TST  R0
        BEQ  .v_large
        CMP  R0,#1
        BEQ  .v_small
        CALL z_fetch_pc_byte
        CALL z_read_var
        BRA  .v_store

.v_large:
        CALL z_fetch_pc_word
        BRA  .v_store

.v_small:
        CALL z_fetch_pc_byte
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1

.v_store:
        POP  R3
        POP  R2
        MOV  R1,R3
        ADD  R1,R1
        LDW  Y,#Z_OP0
        ADDW Y,R1
        MOV  R0,XH
        ST   [Y],R0
        MOV  R0,XL
        ST   [Y+1],R0

        SHL  R2
        SHL  R2
        ADD  R3,#1
        CMP  R3,#4
        BLO  .var_op_lp

.var_ops_done:
        LDW  Y,#Z_OPCOUNT
        ST   [Y],R3
        RET

z_main_exit:
        CALL con_nl
        LDW  X,#.str_exit
        CALL con_puts
        CALL con_nl
        RET

.str_exit:
        .asciz "*** THE END ***"
