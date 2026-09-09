; ---------------------------------------------------------------------
; z3_opcodes.asm -- Complete Z3 opcode dispatch tables and handlers
; ---------------------------------------------------------------------

z_table_2op:
        .word z_op_nop          ; 00
        .word z_op_je           ; 01 je
        .word z_op_jl           ; 02 jl
        .word z_op_jg           ; 03 jg
        .word z_op_dec_chk      ; 04 dec_chk
        .word z_op_inc_chk      ; 05 inc_chk
        .word z_op_jin          ; 06 jin
        .word z_op_test         ; 07 test
        .word z_op_or           ; 08 or
        .word z_op_and          ; 09 and
        .word z_op_test_attr    ; 0A test_attr
        .word z_op_set_attr     ; 0B set_attr
        .word z_op_clear_attr   ; 0C clear_attr
        .word z_op_store        ; 0D store
        .word z_op_insert_obj   ; 0E insert_obj
        .word z_op_loadw        ; 0F loadw
        .word z_op_loadb        ; 10 loadb
        .word z_op_get_prop     ; 11 get_prop
        .word z_op_get_prop_addr; 12 get_prop_addr
        .word z_op_get_next_prop; 13 get_next_prop
        .word z_op_add          ; 14 add
        .word z_op_sub          ; 15 sub
        .word z_op_mul          ; 16 mul
        .word z_op_div          ; 17 div
        .word z_op_mod          ; 18 mod
        .word z_op_call_2s      ; 19 call_2s
        .word z_op_nop          ; 1A
        .word z_op_nop          ; 1B
        .word z_op_nop          ; 1C
        .word z_op_nop          ; 1D
        .word z_op_nop          ; 1E
        .word z_op_nop          ; 1F

z_table_1op:
        .word z_op_jz           ; 00 jz
        .word z_op_get_sibling  ; 01 get_sibling
        .word z_op_get_child    ; 02 get_child
        .word z_op_get_parent   ; 03 get_parent
        .word z_op_get_prop_len ; 04 get_prop_len
        .word z_op_inc          ; 05 inc
        .word z_op_dec          ; 06 dec
        .word z_op_print_addr   ; 07 print_addr
        .word z_op_call_1s      ; 08 call_1s
        .word z_op_remove_obj   ; 09 remove_obj
        .word z_op_print_obj    ; 0A print_obj
        .word z_op_ret          ; 0B ret
        .word z_op_jump         ; 0C jump
        .word z_op_print_paddr  ; 0D print_paddr
        .word z_op_load         ; 0E load
        .word z_op_not          ; 0F not

z_table_0op:
        .word z_op_rtrue        ; 00 rtrue
        .word z_op_rfalse       ; 01 rfalse
        .word z_op_print        ; 02 print
        .word z_op_print_ret    ; 03 print_ret
        .word z_op_nop          ; 04 nop
        .word z_op_save         ; 05 save
        .word z_op_restore      ; 06 restore
        .word z_op_restart      ; 07 restart
        .word z_op_ret_popped   ; 08 ret_popped
        .word z_op_pop          ; 09 pop
        .word z_op_quit         ; 0A quit
        .word z_op_new_line     ; 0B new_line
        .word z_op_show_status  ; 0C show_status
        .word z_op_verify       ; 0D verify
        .word z_op_nop          ; 0E
        .word z_op_nop          ; 0F

z_table_var:
        .word z_op_call         ; 00 call
        .word z_op_storew       ; 01 storew
        .word z_op_storeb       ; 02 storeb
        .word z_op_put_prop     ; 03 put_prop
        .word z_op_sread        ; 04 sread
        .word z_op_print_char   ; 05 print_char
        .word z_op_print_num    ; 06 print_num
        .word z_op_random       ; 07 random
        .word z_op_push         ; 08 push
        .word z_op_pull         ; 09 pull
        .word z_op_split_window ; 0A split_window
        .word z_op_set_window   ; 0B set_window
        .word z_op_erase_window ; 0C erase_window
        .word z_op_erase_line   ; 0D erase_line
        .word z_op_set_cursor   ; 0E set_cursor
        .word z_op_nop          ; 0F
        .word z_op_nop          ; 10
        .word z_op_nop          ; 11
        .word z_op_nop          ; 12
        .word z_op_output_stream; 13 output_stream
        .word z_op_input_stream ; 14 input_stream
        .word z_op_sound_effect ; 15 sound_effect
        .word z_op_nop          ; 16
        .word z_op_nop          ; 17
        .word z_op_nop          ; 18
        .word z_op_nop          ; 19
        .word z_op_nop          ; 1A
        .word z_op_nop          ; 1B
        .word z_op_nop          ; 1C
        .word z_op_nop          ; 1D
        .word z_op_nop          ; 1E
        .word z_op_nop          ; 1F

z_op_nop:
        RET

; 01 je a, b, c, d
z_op_je:
        LDW  X,#Z_OPCOUNT
        LD   R3,[X]
        LDW  X,#Z_OP0
        LD   R0,[X]
        LD   R1,[X+1]
        PUSH R3

        LDW  Y,#Z_OP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        CMP  R0,R2
        BNE  .je_c
        CMP  R1,R3
        BEQ  .je_match

.je_c:  POP  R3
        PUSH R3
        CMP  R3,#3
        BLO  .je_fail
        LDW  Y,#Z_OP2
        LD   R2,[Y]
        LD   R3,[Y+1]
        CMP  R0,R2
        BNE  .je_d
        CMP  R1,R3
        BEQ  .je_match

.je_d:  POP  R3
        PUSH R3
        CMP  R3,#4
        BLO  .je_fail
        LDW  Y,#Z_OP3
        LD   R2,[Y]
        LD   R3,[Y+1]
        CMP  R0,R2
        BNE  .je_fail
        CMP  R1,R3
        BEQ  .je_match

.je_fail:
        POP  R3
        CLR  R0
        JMP  z_eval_branch

.je_match:
        POP  R3
        MOV  R0,#1
        JMP  z_eval_branch

; 02 jl a, b
z_op_jl:
        LDW  X,#Z_OP0
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#Z_OP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        SUB  R1,R3
        SBC  R0,R2
        BLT  .jl_yes
        CLR  R0
        BRA  .jl_ev
.jl_yes:MOV  R0,#1
.jl_ev: JMP  z_eval_branch

; 03 jg a, b
z_op_jg:
        LDW  X,#Z_OP0
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#Z_OP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        SUB  R3,R1
        SBC  R2,R0
        BLT  .jg_yes
        CLR  R0
        BRA  .jg_ev
.jg_yes:MOV  R0,#1
.jg_ev: JMP  z_eval_branch

; 04 dec_chk var, value
z_op_dec_chk:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        PUSH R0
        CALL z_read_var
        DECW X
        POP  R0
        PUSHW X
        CALL z_write_var
        POPW X
        LDW  Y,#Z_OP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        MOV  R0,XL
        SUB  R0,R3
        MOV  R0,XH
        SBC  R0,R2
        BLT  .dec_yes
        CLR  R0
        BRA  .dec_ev
.dec_yes:
        MOV  R0,#1
.dec_ev:JMP  z_eval_branch

; 05 inc_chk var, value
z_op_inc_chk:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        PUSH R0
        CALL z_read_var
        INCW X
        POP  R0
        PUSHW X
        CALL z_write_var
        POPW X
        LDW  Y,#Z_OP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        MOV  R0,XL
        SUB  R3,R0
        MOV  R0,XH
        SBC  R2,R0
        BLT  .inc_yes
        CLR  R0
        BRA  .inc_ev
.inc_yes:
        MOV  R0,#1
.inc_ev:JMP  z_eval_branch

; 06 jin obj1, obj2
z_op_jin:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        CALL z_get_parent
        LDW  Y,#Z_OP1
        LD   R1,[Y+1]
        MOV  R0,XL
        CMP  R0,R1
        BNE  .jin_no
        MOV  R0,#1
        BRA  .jin_ev
.jin_no:CLR  R0
.jin_ev:JMP  z_eval_branch

; 07 test bitmap, flags
z_op_test:
        LDW  X,#Z_OP0
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#Z_OP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        AND  R0,R2
        AND  R1,R3
        CMP  R0,R2
        BNE  .tst_no
        CMP  R1,R3
        BNE  .tst_no
        MOV  R0,#1
        BRA  .tst_ev
.tst_no:CLR  R0
.tst_ev:JMP  z_eval_branch

; 08 or a, b -> res
z_op_or:
        LDW  X,#Z_OP0
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#Z_OP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        OR   R0,R2
        OR   R1,R3
        MOV  XH,R0
        MOV  XL,R1
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 09 and a, b -> res
z_op_and:
        LDW  X,#Z_OP0
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#Z_OP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        AND  R0,R2
        AND  R1,R3
        MOV  XH,R0
        MOV  XL,R1
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 0A test_attr obj, attr
z_op_test_attr:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        LDW  Y,#Z_OP1
        LD   R1,[Y+1]
        CALL z_test_attr
        JMP  z_eval_branch

; 0B set_attr obj, attr
z_op_set_attr:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        LDW  Y,#Z_OP1
        LD   R1,[Y+1]
        JMP  z_set_attr

; 0C clear_attr obj, attr
z_op_clear_attr:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        LDW  Y,#Z_OP1
        LD   R1,[Y+1]
        JMP  z_clear_attr

; 0D store var, value
z_op_store:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        LDW  Y,#Z_OP1
        LD   R1,[Y]
        LD   R2,[Y+1]
        MOV  XH,R1
        MOV  XL,R2
        JMP  z_write_var

; 0E insert_obj obj, dest
z_op_insert_obj:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        LDW  Y,#Z_OP1
        LD   R1,[Y+1]
        JMP  z_insert_obj

; 0F loadw array, index -> res
z_op_loadw:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        LDW  Y,#Z_OP1
        LD   R3,[Y]
        LD   R2,[Y+1]
        SHL  R2
        ROL  R3
        MOV  R0,XL
        ADD  R0,R2
        MOV  XL,R0
        MOV  R0,XH
        ADC  R0,R3
        MOV  XH,R0
        CLR  R1
        CALL z_read_word
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 10 loadb array, index -> res
z_op_loadb:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        LDW  Y,#Z_OP1
        LD   R3,[Y]
        LD   R2,[Y+1]
        MOV  R0,XL
        ADD  R0,R2
        MOV  XL,R0
        MOV  R0,XH
        ADC  R0,R3
        MOV  XH,R0
        CLR  R1
        CALL z_read_byte
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 11 get_prop obj, prop -> res
z_op_get_prop:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        LDW  Y,#Z_OP1
        LD   R1,[Y+1]
        CALL z_get_prop
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 12 get_prop_addr obj, prop -> res
z_op_get_prop_addr:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        LDW  Y,#Z_OP1
        LD   R1,[Y+1]
        CALL z_get_prop_addr
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 13 get_next_prop obj, prop -> res
z_op_get_next_prop:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        LDW  Y,#Z_OP1
        LD   R1,[Y+1]
        CALL z_get_next_prop
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 14 add a, b -> res
z_op_add:
        LDW  X,#Z_OP0
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#Z_OP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R1,R3
        ADC  R0,R2
        MOV  XH,R0
        MOV  XL,R1
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 15 sub a, b -> res
z_op_sub:
        LDW  X,#Z_OP0
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  Y,#Z_OP1
        LD   R2,[Y]
        LD   R3,[Y+1]
        SUB  R1,R3
        SBC  R0,R2
        MOV  XH,R0
        MOV  XL,R1
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 16 mul a, b -> res
z_op_mul:
        ; X = (a_L * b_L) + ((a_H * b_L + a_L * b_H) << 8)
        LDW  X,#Z_OP0
        LD   R0,[X+1]           ; a_L
        LDW  Y,#Z_OP1
        LD   R1,[Y+1]           ; b_L
        MUL  R0,R1              ; X = a_L * b_L
        PUSHW X                 ; [1] low product
        LDW  X,#Z_OP0
        LD   R0,[X]             ; a_H
        LDW  Y,#Z_OP1
        LD   R1,[Y+1]           ; b_L
        MUL  R0,R1              ; X = a_H * b_L
        MOV  R2,XL              ; R2 = (a_H * b_L) low byte
        LDW  X,#Z_OP0
        LD   R0,[X+1]           ; a_L
        LDW  Y,#Z_OP1
        LD   R1,[Y]             ; b_H
        MUL  R0,R1              ; X = a_L * b_H
        MOV  R0,XL              ; R0 = (a_L * b_H) low byte
        ADD  R2,R0              ; R2 = high cross contribution
        POPW X                  ; restore low product
        MOV  R0,XH
        ADD  R0,R2
        MOV  XH,R0              ; X = full 16-bit product!
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 17 div a, b -> res
z_op_div:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        CALL z_signed_div
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 18 mod a, b -> res
z_op_mod:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        CALL z_signed_div
        MOVW X,Y
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 19 call_2s
z_op_call_2s:
        CALL z_fetch_pc_byte
        LDW  X,#Z_RESVAR
        ST   [X],R0
        JMP  z_call

; 00 jz a
z_op_jz:
        LDW  X,#Z_OP0
        LD   R0,[X]
        LD   R1,[X+1]
        OR   R0,R1
        BEQ  .jz_yes
        CLR  R0
        BRA  .jz_ev
.jz_yes:MOV  R0,#1
.jz_ev: JMP  z_eval_branch

; 01 get_sibling obj -> res
z_op_get_sibling:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        CALL z_get_sibling
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        PUSHW X
        CALL z_write_var
        POPW X
        MOV  R0,XL
        MOV  R1,XH
        OR   R0,R1
        BEQ  .sib_0
        MOV  R0,#1
        BRA  .sib_ev
.sib_0: CLR  R0
.sib_ev:JMP  z_eval_branch

; 02 get_child obj -> res
z_op_get_child:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        CALL z_get_child
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        PUSHW X
        CALL z_write_var
        POPW X
        MOV  R0,XL
        MOV  R1,XH
        OR   R0,R1
        BEQ  .ch_0
        MOV  R0,#1
        BRA  .ch_ev
.ch_0:  CLR  R0
.ch_ev: JMP  z_eval_branch

; 03 get_parent obj -> res
z_op_get_parent:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        CALL z_get_parent
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 04 get_prop_len prop_addr -> res
z_op_get_prop_len:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        CALL z_get_prop_len
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 05 inc var
z_op_inc:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        PUSH R0
        CALL z_read_var
        INCW X
        POP  R0
        JMP  z_write_var

; 06 dec var
z_op_dec:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        PUSH R0
        CALL z_read_var
        DECW X
        POP  R0
        JMP  z_write_var

; 07 print_addr byte_addr
z_op_print_addr:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        JMP  z_print_addr

; 08 call_1s
z_op_call_1s:
        CALL z_fetch_pc_byte
        LDW  X,#Z_RESVAR
        ST   [X],R0
        JMP  z_call

; 09 remove_obj obj
z_op_remove_obj:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        JMP  z_remove_obj

; 0A print_obj obj
z_op_print_obj:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        JMP  z_print_obj

; 0B ret value
z_op_ret:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        JMP  z_ret

; 0C jump offset
z_op_jump:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        SUB  R0,#2
        SBC  R1,#0

        ; Sign extend R1 into R2
        MOV  R2,R1
        BTST R2,#$80
        BEQ  .j_pos
        MOV  R2,#$FF
        BRA  .j_add
.j_pos: CLR  R2
.j_add:
        LDW  Y,#Z_PC_L
        LD   R3,[Y]
        ADD  R3,R0
        ST   [Y],R3
        LD   R3,[Y+1]
        ADC  R3,R1
        ST   [Y+1],R3
        LD   R3,[Y+2]
        ADC  R3,R2
        ST   [Y+2],R3
        RET

; 0D print_paddr packed_addr
z_op_print_paddr:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        JMP  z_print_paddr

; 0E load var -> res
z_op_load:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        CALL z_read_var
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

; 0F not a -> res
z_op_not:
        LDW  X,#Z_OP0
        LD   R0,[X]
        LD   R1,[X+1]
        NOT  R0
        NOT  R1
        MOV  XH,R0
        MOV  XL,R1
        PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

z_op_rtrue:
        LDW  X,#1
        JMP  z_ret

z_op_rfalse:
        LDW  X,#0
        JMP  z_ret

z_op_print:
        LDW  Y,#Z_PC_L
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XL,R0
        MOV  XH,R1
        LD   R1,[Y+2]
        CALL z_print_zstr
        LDW  Y,#Z_PC_L
        MOV  R0,XL
        ST   [Y],R0
        MOV  R0,XH
        ST   [Y+1],R0
        ST   [Y+2],R1
        RET

z_op_print_ret:
        CALL z_op_print
        CALL con_nl
        JMP  z_op_rtrue

z_op_save:
        CALL z_do_save
        JMP  z_eval_branch

z_op_restore:
        CALL z_do_restore
        JMP  z_eval_branch

z_op_restart:
        JMP  z_init_restart

z_op_ret_popped:
        CALL z_pop
        JMP  z_ret

z_op_pop:
        JMP  z_pop

z_op_quit:
        LDW  X,#Z_QUIT
        MOV  R0,#1
        ST   [X],R0
        RET

z_op_new_line:
        CALL z_flush_wrap
        JMP  con_nl

z_op_show_status:
        JMP  z_show_status

z_op_verify:
        MOV  R0,#1
        JMP  z_eval_branch

z_op_call:
        CALL z_fetch_pc_byte
        LDW  X,#Z_RESVAR
        ST   [X],R0
        JMP  z_call

z_op_storew:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        LDW  Y,#Z_OP1
        LD   R3,[Y]
        LD   R2,[Y+1]
        SHL  R2
        ROL  R3
        MOV  R0,XL
        ADD  R0,R2
        MOV  XL,R0
        MOV  R0,XH
        ADC  R0,R3
        MOV  XH,R0
        LDW  Y,#Z_OP2
        LD   R1,[Y]
        LD   R0,[Y+1]
        JMP  z_write_word

z_op_storeb:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        LDW  Y,#Z_OP1
        LD   R3,[Y]
        LD   R2,[Y+1]
        MOV  R0,XL
        ADD  R0,R2
        MOV  XL,R0
        MOV  R0,XH
        ADC  R0,R3
        MOV  XH,R0
        LDW  Y,#Z_OP2
        LD   R0,[Y+1]
        JMP  z_write_byte

z_op_put_prop:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        LDW  Y,#Z_OP1
        LD   R1,[Y+1]
        LDW  Y,#Z_OP2
        LD   R2,[Y]
        LD   R3,[Y+1]
        MOV  XH,R2
        MOV  XL,R3
        JMP  z_put_prop

z_op_sread:
        JMP  z_sread

z_op_print_char:
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        JMP  z_putc

z_op_print_num:
        LDW  Y,#Z_OP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R0
        MOV  XL,R1
        JMP  z_print_num

z_op_random:
        LDW  X,#Z_RND_SEED
        LD   R0,[X]
        MOV  R1,#109
        MUL  R0,R1
        MOV  R0,XL
        ADD  R0,#89
        LDW  X,#Z_RND_SEED
        ST   [X],R0
        LDW  Y,#Z_OP0
        LD   R1,[Y+1]
        TST  R1
        BEQ  .rnd_0
.rnd_m: CMP  R0,R1
        BLO  .rnd_d
        SUB  R0,R1
        BRA  .rnd_m
.rnd_d: ADD  R0,#1
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1
        BRA  .rnd_st
.rnd_0: LDW  X,#0
.rnd_st:PUSHW X
        CALL z_fetch_pc_byte
        POPW X
        JMP  z_write_var

z_op_push:
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        JMP  z_push

z_op_pull:
        CALL z_pop
        LDW  Y,#Z_OP0
        LD   R0,[Y+1]
        JMP  z_write_var

z_op_split_window:
z_op_set_window:
z_op_output_stream:
z_op_input_stream:
z_op_sound_effect:
        RET

; 0C erase_window window
z_op_erase_window:
        CALL z_flush_wrap
        CALL con_cls
        JMP  z_show_status

; 0D erase_line
z_op_erase_line:
        JMP  z_clr_eol

; 0E set_cursor line, column
z_op_set_cursor:
        CALL z_flush_wrap
        LDW  X,#Z_OP0
        LD   R0,[X+1]
        TST  R0
        BEQ  .cr_yok
        SUB  R0,#1              ; 1-indexed to 0-indexed
.cr_yok:ST   [CCY],R0

        LDW  X,#Z_OP1
        LD   R1,[X+1]
        TST  R1
        BEQ  .cr_xok
        SUB  R1,#1              ; 1-indexed to 0-indexed
.cr_xok:ST   [CCX],R1

        CALL con_setrow
        JMP  con_cursor

; z_signed_div -- divides Z_OP0 by Z_OP1 -> quotient in X, remainder in Y
z_signed_div:
        LDW  X,#Z_OP1
        LD   R0,[X]
        LD   R1,[X+1]
        OR   R0,R1
        BNE  .div_nonzero
        ; Division by zero -> return 0
        LDW  X,#0
        LDW  Y,#0
        RET

.div_nonzero:
        ; Setup signs: Z_TMP0 holds sign_quot, Z_TMP0+1 holds sign_rem
        LDW  Y,#Z_TMP0
        CLR  R0
        ST   [Y],R0             ; sign_quot = 0
        ST   [Y+1],R0           ; sign_rem = 0

        ; Load Z_OP0 (dividend) into Z_TMP1
        LDW  X,#Z_OP0
        LD   R0,[X]
        LD   R1,[X+1]
        TST  R0
        BPL  .div_pos_a
        ; Negative dividend: a = -a, sign_quot ^= 1, sign_rem = 1
        CLR  R2
        CLR  R3
        SUB  R3,R1
        SBC  R2,R0
        MOV  R0,R2
        MOV  R1,R3
        LDW  Y,#Z_TMP0
        MOV  R2,#1
        ST   [Y],R2             ; sign_quot = 1
        ST   [Y+1],R2           ; sign_rem = 1
.div_pos_a:
        LDW  Y,#Z_TMP1
        ST   [Y],R0             ; quot_H (initial dividend_H)
        ST   [Y+1],R1           ; quot_L (initial dividend_L)

        ; Load Z_OP1 (divisor) into Z_TMP2
        LDW  X,#Z_OP1
        LD   R0,[X]
        LD   R1,[X+1]
        TST  R0
        BPL  .div_pos_b
        ; Negative divisor: b = -b, sign_quot ^= 1
        CLR  R2
        CLR  R3
        SUB  R3,R1
        SBC  R2,R0
        MOV  R0,R2
        MOV  R1,R3
        LDW  Y,#Z_TMP0
        LD   R2,[Y]
        XOR  R2,#1
        ST   [Y],R2
.div_pos_b:
        LDW  Y,#Z_TMP2
        ST   [Y],R0             ; b_H
        ST   [Y+1],R1           ; b_L

        ; 16-bit shift-subtract division loop
        ; R0:R1 = remainder (R0=high, R1=low, init 0)
        CLR  R0
        CLR  R1
        MOV  R3,#16             ; loop counter

.div_lp:PUSH R3
        ; Shift left Z_TMP1 (quot) and R0:R1 (rem)
        LDW  Y,#Z_TMP1
        LD   R2,[Y+1]           ; quot_L
        SHL  R2
        ST   [Y+1],R2
        LD   R2,[Y]             ; quot_H
        ROL  R2
        ST   [Y],R2
        ROL  R1                 ; rem_L
        ROL  R0                 ; rem_H

        ; Compare remainder R0:R1 with divisor Z_TMP2
        LDW  Y,#Z_TMP2
        LD   R2,[Y]             ; b_H
        LD   R3,[Y+1]           ; b_L
        CMP  R0,R2
        BLO  .div_next_bit
        BHI  .div_sub_bit
        CMP  R1,R3
        BLO  .div_next_bit

.div_sub_bit:
        SUB  R1,R3
        SBC  R0,R2
        LDW  Y,#Z_TMP1
        LD   R2,[Y+1]
        OR   R2,#1
        ST   [Y+1],R2

.div_next_bit:
        POP  R3
        SUB  R3,#1
        BNE  .div_lp

        ; Save unsigned remainder in Z_TMP2
        LDW  Y,#Z_TMP2
        ST   [Y],R0             ; rem_H
        ST   [Y+1],R1           ; rem_L

        ; Load unsigned quotient into X
        LDW  Y,#Z_TMP1
        LD   R2,[Y]             ; quot_H
        LD   R3,[Y+1]           ; quot_L
        MOV  XH,R2
        MOV  XL,R3

        ; Apply sign to quotient X
        LDW  Y,#Z_TMP0
        LD   R2,[Y]
        TST  R2
        BEQ  .div_chk_rem_sign
        CLR  R2
        CLR  R3
        MOV  R0,XL
        MOV  R1,XH
        SUB  R3,R0
        SBC  R2,R1
        MOV  XL,R3
        MOV  XH,R2

.div_chk_rem_sign:
        LDW  Y,#Z_TMP2
        LD   R0,[Y+1]           ; rem_L
        LD   R1,[Y]             ; rem_H
        LDW  Y,#Z_TMP0
        LD   R2,[Y+1]
        TST  R2
        BEQ  .div_done
        CLR  R2
        CLR  R3
        SUB  R3,R0
        SBC  R2,R1
        MOV  R0,R3
        MOV  R1,R2

.div_done:
        MOV  YL,R0
        MOV  YH,R1
        RET
