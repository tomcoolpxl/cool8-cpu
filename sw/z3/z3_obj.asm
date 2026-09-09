; ---------------------------------------------------------------------
; z3_obj.asm -- Object table, hierarchy, attributes, and property access
; ---------------------------------------------------------------------

; z_get_obj_addr -- R0 = object number (1..255) -> X = RAM address of 9-byte entry
z_get_obj_addr:
        TST  R0
        BNE  .valid_obj
        LDW  X,#0
        RET
.valid_obj:
        PUSH R1
        PUSH R2
        PUSH R3
        SUB  R0,#1              ; R0 = obj - 1 (0..254)
        CLR  R1                 ; R1:R0 = obj - 1
        MOV  R2,R0
        MOV  R3,R1              ; R3:R2 = (obj - 1)
        SHL  R0
        ROL  R1                 ; *2
        SHL  R0
        ROL  R1                 ; *4
        SHL  R0
        ROL  R1                 ; *8
        ADD  R0,R2
        ADC  R1,R3              ; *9
        ADD  R0,#62
        ADC  R1,#0              ; R1:R0 = 62 + (obj - 1) * 9

        ; Add Object Table Base (Z_OBJS)
        LDW  Y,#Z_OBJS
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XL,R0
        MOV  XH,R1
        POP  R3
        POP  R2
        POP  R1
        RET

; z_test_attr -- R0 = obj, R1 = attr (0..31) -> R0 = 1 if set, 0 if clear
z_test_attr:
        PUSH R1
        CALL z_get_obj_addr     ; X = obj entry addr
        POP  R1
        MOV  R2,R1
        SHR  R2
        SHR  R2
        SHR  R2
        ADDW X,R2
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        LD   R0,[Y]
        AND  R1,#7
        MOV  R2,#7
        SUB  R2,R1
.tsh:   TST  R2
        BEQ  .tdone
        SHR  R0
        SUB  R2,#1
        BRA  .tsh
.tdone: AND  R0,#1
        RET

; z_set_attr -- R0 = obj, R1 = attr (0..31)
z_set_attr:
        PUSH R1
        CALL z_get_obj_addr
        POP  R1
        MOV  R2,R1
        SHR  R2
        SHR  R2
        SHR  R2
        ADDW X,R2
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        LD   R0,[Y]
        AND  R1,#7
        MOV  R2,#7
        SUB  R2,R1
        MOV  R3,#1
.ssh:   TST  R2
        BEQ  .sdone
        SHL  R3
        SUB  R2,#1
        BRA  .ssh
.sdone: OR   R0,R3
        ST   [Y],R0
        RET

; z_clear_attr -- R0 = obj, R1 = attr (0..31)
z_clear_attr:
        PUSH R1
        CALL z_get_obj_addr
        POP  R1
        MOV  R2,R1
        SHR  R2
        SHR  R2
        SHR  R2
        ADDW X,R2
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        LD   R0,[Y]
        AND  R1,#7
        MOV  R2,#7
        SUB  R2,R1
        MOV  R3,#1
.csh:   TST  R2
        BEQ  .cdone
        SHL  R3
        SUB  R2,#1
        BRA  .csh
.cdone: NOT  R3
        AND  R0,R3
        ST   [Y],R0
        RET

; z_get_parent -- R0 = obj -> X = parent object number (16-bit word)
z_get_parent:
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        LD   R0,[Y+4]           ; byte 4 = parent
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1
        RET

; z_get_sibling -- R0 = obj -> X = sibling object number
z_get_sibling:
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        LD   R0,[Y+5]           ; byte 5 = sibling
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1
        RET

; z_get_child -- R0 = obj -> X = child object number
z_get_child:
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        LD   R0,[Y+6]           ; byte 6 = child
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1
        RET

; z_remove_obj -- R0 = obj: detaches obj from parent & sibling chain
z_remove_obj:
        TST  R0
        BEQ  .rm_ret
        PUSH R0
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        LD   R1,[Y+4]           ; R1 = parent obj
        TST  R1
        BEQ  .rm_done           ; no parent, already detached

        ; Read obj->sibling into R3
        LD   R3,[Y+5]           ; R3 = obj->sibling

        ; Check if parent->child == obj
        MOV  R0,R1
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE      ; Y = parent RAM addr
        LD   R2,[Y+6]           ; R2 = parent->child
        POP  R0                 ; R0 = obj
        PUSH R0
        CMP  R2,R0
        BNE  .rm_sib

        ; obj is first child: parent->child = obj->sibling
        ST   [Y+6],R3
        BRA  .rm_clr

.rm_sib:
        ; Find predecessor in sibling list: curr->sibling == obj
        MOV  R1,R2              ; R1 = curr obj
.sib_lp:MOV  R0,R1
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE      ; Y = curr RAM addr
        LD   R2,[Y+5]           ; R2 = curr->sibling
        POP  R0                 ; R0 = obj
        PUSH R0
        CMP  R2,R0
        BEQ  .sib_fnd
        MOV  R1,R2              ; curr = curr->sibling
        TST  R1
        BNE  .sib_lp
        BRA  .rm_clr

.sib_fnd:
        ; Y is curr RAM addr. curr->sibling = obj->sibling (R3)
        ST   [Y+5],R3

.rm_clr:
        ; Clear obj->parent and obj->sibling
        POP  R0                 ; R0 = obj
        PUSH R0
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        CLR  R0
        ST   [Y+4],R0           ; obj->parent = 0
        ST   [Y+5],R0           ; obj->sibling = 0

.rm_done:
        POP  R0
.rm_ret:RET

; z_insert_obj -- R0 = obj, R1 = dest_parent
z_insert_obj:
        TST  R0
        BEQ  .ins_ret
        PUSH R1
        PUSH R0
        CALL z_remove_obj
        POP  R0
        POP  R1
        TST  R1
        BEQ  .ins_ret           ; inserting into parent 0 is just remove

        PUSH R1
        PUSH R0

        ; Set obj->parent = dest_parent
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        ST   [Y+4],R1           ; obj->parent = dest_parent

        ; Get dest_parent->child
        MOV  R0,R1
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE      ; Y = dest_parent RAM addr
        LD   R2,[Y+6]           ; R2 = old child

        ; dest_parent->child = obj
        POP  R0                 ; R0 = obj
        ST   [Y+6],R0

        ; obj->sibling = old child (R2)
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        ST   [Y+5],R2

        POP  R1
.ins_ret:
        RET

; z_get_prop_table -- R0 = obj -> X = address of first property entry
z_get_prop_table:
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        LD   R1,[Y+7]
        LD   R0,[Y+8]
        MOV  XH,R1
        MOV  XL,R0

        CLR  R1
        PUSHW X
        CALL z_read_byte        ; R0 = text length in words
        POPW X
        ADD  R0,R0
        ADD  R0,#1
        ADDW X,R0
        RET

; z_get_prop_addr -- R0 = obj, R1 = prop_num -> X = property data address (or 0)
z_get_prop_addr:
        PUSH R1
        CALL z_get_prop_table
        POP  R1

.prop_lp:
        PUSH R1
        PUSHW X
        CLR  R1
        CALL z_read_byte        ; R0 = size byte S
        POPW X
        POP  R1
        TST  R0
        BEQ  .not_fnd

        MOV  R2,R0
        AND  R2,#$1F
        CMP  R2,R1
        BEQ  .found
        BLO  .not_fnd

        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        ADD  R0,#2
        ADDW X,R0
        BRA  .prop_lp

.found: INCW X
        RET

.not_fnd:
        LDW  X,#0
        RET

; z_get_prop_len -- X = property data address -> R0 = property length (1..8)
z_get_prop_len:
        DECW X
        CLR  R1
        CALL z_read_byte
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        ADD  R0,#1
        RET

; z_get_prop -- R0 = obj, R1 = prop_num -> X = 16-bit property value
z_get_prop:
        PUSH R1
        PUSH R0
        CALL z_get_prop_addr
        POP  R0
        POP  R1
        MOV  R2,XL
        MOV  R3,XH
        OR   R2,R3
        BNE  .rd_data

        SUB  R1,#1
        ADD  R1,R1
        LDW  Y,#Z_OBJS
        LD   R0,[Y]
        LD   R2,[Y+1]
        MOV  XL,R0
        MOV  XH,R2
        ADDW X,R1
        CLR  R1
        JMP  z_read_word

.rd_data:
        PUSHW X
        CALL z_get_prop_len
        POPW X
        CMP  R0,#1
        BNE  .wrd_prop
        CLR  R1
        CALL z_read_byte
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1
        RET

.wrd_prop:
        CLR  R1
        JMP  z_read_word

; z_put_prop -- R0 = obj, R1 = prop_num, X = value
z_put_prop:
        PUSHW X
        CALL z_get_prop_addr
        POPW Y                  ; Y = value
        MOV  R0,XL
        MOV  R1,XH
        OR   R0,R1
        BEQ  .put_done

        PUSHW X
        PUSHW Y
        CALL z_get_prop_len
        POPW Y
        POPW X
        CMP  R0,#1
        BNE  .put_wrd
        MOV  R0,YL
        JMP  z_write_byte

.put_wrd:
        MOV  R1,YH
        MOV  R0,YL
        JMP  z_write_word

.put_done:
        RET

; z_get_next_prop -- R0 = obj, R1 = prop_num -> X = next property number
z_get_next_prop:
        TST  R1
        BNE  .find_curr

        CALL z_get_prop_table
        CLR  R1
        CALL z_read_byte
        AND  R0,#$1F
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1
        RET

.find_curr:
        PUSH R1
        CALL z_get_prop_table
        POP  R1

.nxt_lp:PUSH R1
        PUSHW X
        CLR  R1
        CALL z_read_byte
        POPW X
        POP  R1
        TST  R0
        BEQ  .end_props

        MOV  R2,R0
        AND  R2,#$1F
        CMP  R2,R1
        BEQ  .advance_nxt

        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        ADD  R0,#2
        ADDW X,R0
        BRA  .nxt_lp

.advance_nxt:
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        ADD  R0,#2
        ADDW X,R0

        CLR  R1
        CALL z_read_byte
        AND  R0,#$1F
        MOV  XL,R0
        CLR  R1
        MOV  XH,R1
        RET

.end_props:
        LDW  X,#0
        RET

; z_print_obj -- R0 = obj: prints short name of object
z_print_obj:
        TST  R0
        BEQ  .no_name
        CALL z_get_obj_addr
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        LD   R1,[Y+7]
        LD   R0,[Y+8]
        MOV  XH,R1
        MOV  XL,R0

        CLR  R1
        PUSHW X
        CALL z_read_byte        ; R0 = name length in words
        POPW X
        TST  R0
        BEQ  .no_name
        INCW X
        JMP  z_print_addr

.no_name:
        RET
