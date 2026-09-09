; ---------------------------------------------------------------------
; sw/pascal/pascal.asm -- COOL8 Native UCSD Pascal p-System Interpreter
; ---------------------------------------------------------------------

        .org $0200
        JMP  main

        .include "../lowram.asm"
        .include "../console.asm"
        .include "../input.asm"
        .include "../kbd.asm"
        .include "../keymap.asm"
        .include "../kdown.asm"
        .include "pm_equ.asm"
        .include "pm_stack.asm"
        .include "pm_var.asm"
        .include "pm_arith.asm"
        .include "pm_jump.asm"
        .include "pm_string.asm"
        .include "pm_call.asm"
        .include "pm_sbios.asm"
        .include "pm_csp.asm"
        .include "pm_seg.asm"

inmi:   PUSH R0
        MOV  R0,#1
        ST   [ibreak],R0
        POP  R0
        RETI

iisr:   PUSH R0
        PUSH R1
        PUSH R2
        PUSH R3
        PUSHW X
        PUSHW Y
        MOV  R0,#$22
        ST   [VID_IRQ],R0
        LD   R0,[frames]
        ADD  R0,#1
        ST   [frames],R0
        LD   R0,[frames+1]
        ADC  R0,#0
        ST   [frames+1],R0
.more:  LD   R0,[UART_STAT]
        BTST R0,#$01
        BEQ  .kbd
        LD   R0,[UART_DATA]
        CALL irpush
        BRA  .more

.kbd:   LD   R0,[KBD_STAT]
        BTST R0,#$01
        BEQ  .done
        LD   R0,[KBD_DATA]
        CALL scancode
        TST  R0
        BEQ  .kbd
        CALL irpush
        BRA  .kbd

.done:  POPW Y
        POPW X
        POP  R3
        POP  R2
        POP  R1
        POP  R0
        RETI

irpush: LD   R2,[irhead]
        CLR  R3
        LDW  X,#irring
        ADDW X,R2
        ST   [X],R0
        ADD  R2,#1
        AND  R2,#15
        ST   [irhead],R2
        RET

main:
        LDW  X,#$0200
        MOVW SP,X
        DI
        MOV  R0,#<iisr
        ST   [$FFFC],R0
        MOV  R0,#>iisr
        ST   [$FFFD],R0
        MOV  R0,#<inmi
        ST   [$FFFA],R0
        MOV  R0,#>inmi
        ST   [$FFFB],R0
        MOV  R0,#$20
        ST   [VID_IRQ],R0
        MOV  R0,#$11
        ST   [KBD_CTRL],R0
        MOV  R0,#$10
        ST   [KBD_CTRL],R0

        CLR  R0
        ST   [irhead],R0
        ST   [irtail],R0

        EI

        MOV  R0,#$80
        ST   [VID_MODE],R0
        CALL con_init
        MOV  R0,#$0F
        ST   [CATTR],R0
        CLR  R0
        ST   [VID_BORDER],R0
        CALL con_cls

        ; 0. Zero entire work RAM (PM_EVAL_TOP to PM_MEM_TOP + 2 = $9800)
        LDW  X,#PM_EVAL_TOP
        CLR  R0
.zram_lp:
        ST   [X+],R0
        MOV  R1,XH
        CMP  R1,#$98
        BNE  .zram_lp

        ; 1. Initialize KP to top of memory, SP to evaluation stack top, and NP to heap base
        LDW  X,#PM_MEM_TOP
        MOV  R0,XL
        MOV  R1,XH
        LDW  Y,#PM_KP
        ST   [Y],R0
        ST   [Y+1],R1
        LDW  X,#PM_EVAL_TOP
        MOV  R0,XL
        MOV  R1,XH
        LDW  Y,#PM_SP
        ST   [Y],R0
        ST   [Y+1],R1
        LDW  X,#PM_HEAP_BASE
        MOV  R0,XL
        MOV  R1,XH
        LDW  Y,#PM_NP
        ST   [Y],R0
        ST   [Y+1],R1

        ; Clear VRAM disk write cache
        CLR  R0
        ST   [PM_VCACHE_CNT],R0

        ; 2. Allocate SYSCOM record at PM_SYSCOM_ADDR ($AC00)
        LDW  X,#PM_SYSCOM_ADDR
        MOV  R0,XL
        MOV  R1,XH
        LDW  Y,#PM_SYSCOM
        ST   [Y],R0
        ST   [Y+1],R1

        ; Load SYSTEM.MISCINFO (Block 6 = $790C00) directly into SYSCOM
        CLR  R3
        ST   [FLS_CTRL],R3
        ST   [FLS_ADDR_L],R3
        MOV  R3,#$0C
        ST   [FLS_ADDR_M],R3
        MOV  R3,#$79
        ST   [FLS_ADDR_H],R3
        MOV  R3,#1
        ST   [FLS_CTRL],R3

        LDW  X,#PM_SYSCOM_ADDR
        MOV  R2,#<512
        MOV  R3,#>512
.lsm_rd_lp:
        MOV  R0,R2
        OR   R0,R3
        BEQ  .lsm_rd_done
        LD   R0,[FLS_DATA]
        ST   [X],R0
        INCW X
        SUB  R2,#1
        SBC  R3,#0
        BRA  .lsm_rd_lp
.lsm_rd_done:
        CLR  R0
        ST   [FLS_CTRL],R0

        ; Set Screen Height to 30 rows (Word 37 = offset 74 in SYSCOM)
        MOV  R0,#30
        CLR  R1
        LDW  X,#PM_SYSCOM_ADDR + 74
        ST   [X+],R0
        ST   [X+],R1

        ; Initialize Segment table and load Segment 0 below SYSCOM
        CALL pm_init_seg_table
        CALL pm_load_seg0

        ; 3. Call Procedure 1 of Segment 0
        LDW  X,#PM_SEG_DICT + 4
        LD   R0,[X+]
        LD   R1,[X+]
        LDW  Y,#PM_TMP3
        ST   [Y],R0
        ST   [Y+1],R1
        MOV  R0,#1
        CLR  R2
        CLR  R3
        CALL pm_call_proc

        ; Set Base pointer PM_BP and PM_BASE_MP = PM_MP (Proc 1 of Segment 0 frame)
        LDW  X,#PM_MP
        LD   R0,[X]
        LD   R1,[X+1]
        LDW  X,#PM_BP
        ST   [X],R0
        ST   [X+1],R1
        LDW  X,#PM_BASE_MP
        ST   [X],R0
        ST   [X+1],R1

        ; 4. LocalAddr(1) of Proc 1 stores the pointer to SYSCOM
        CLR  R1
        MOV  R0,#1
        CALL pm_local_addr      ; X = LocalAddr(1)
        LDW  Y,#PM_SYSCOM
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X],R0
        ST   [X+1],R1

        ; LocalAddr(59) and LocalAddr(63) of Proc 1 store SYSTITLE '\x06SYSTEM\x00'
        CLR  R1
        MOV  R0,#59
        CALL pm_local_addr      ; X = LocalAddr(59)
        MOV  R0,#6
        ST   [X+],R0
        MOV  R0,#$53            ; 'S'
        ST   [X+],R0
        MOV  R0,#$59            ; 'Y'
        ST   [X+],R0
        MOV  R0,#$53            ; 'S'
        ST   [X+],R0
        MOV  R0,#$54            ; 'T'
        ST   [X+],R0
        MOV  R0,#$45            ; 'E'
        ST   [X+],R0
        MOV  R0,#$4D            ; 'M'
        ST   [X+],R0
        CLR  R0
        ST   [X+],R0

        CLR  R1
        MOV  R0,#63
        CALL pm_local_addr      ; X = LocalAddr(63)
        MOV  R0,#6
        ST   [X+],R0
        MOV  R0,#$53            ; 'S'
        ST   [X+],R0
        MOV  R0,#$59            ; 'Y'
        ST   [X+],R0
        MOV  R0,#$53            ; 'S'
        ST   [X+],R0
        MOV  R0,#$54            ; 'T'
        ST   [X+],R0
        MOV  R0,#$45            ; 'E'
        ST   [X+],R0
        MOV  R0,#$4D            ; 'M'
        ST   [X+],R0
        CLR  R0
        ; Initialize GlobalAddr(5) with pointer to LocalAddr(63) (VOLNAME)
        CLR  R1
        MOV  R0,#63
        CALL pm_local_addr      ; R1:R0 = LocalAddr(63)
        MOV  R2,XL
        MOV  R3,XH
        CLR  R1
        MOV  R0,#5
        CALL pm_global_addr     ; X = GlobalAddr(5)
        ST   [X],R2
        ST   [X+1],R3

        ; Initialize UnitTable at LocalAddr(126) for units 1..12 (12 bytes per entry)
        CLR  R1
        MOV  R0,#126
        CALL pm_local_addr      ; X = LocalAddr(126) = 0x773E
        CLR  R2                 ; Unit number 0..12
.init_unit_lp:
        ; Offset +0 (8 bytes): Name
        CMP  R2,#1
        BEQ  .init_u1_con
        CMP  R2,#2
        BEQ  .init_u2_sys
        CMP  R2,#4
        BEQ  .init_u4_sys
        BRA  .init_u_noname
.init_u1_con:
        MOV  R0,#7
        ST   [X+],R0
        MOV  R0,#$43            ; 'C'
        ST   [X+],R0
        MOV  R0,#$4F            ; 'O'
        ST   [X+],R0
        MOV  R0,#$4E            ; 'N'
        ST   [X+],R0
        MOV  R0,#$53            ; 'S'
        ST   [X+],R0
        MOV  R0,#$4F            ; 'O'
        ST   [X+],R0
        MOV  R0,#$4C            ; 'L'
        ST   [X+],R0
        MOV  R0,#$45            ; 'E'
        ST   [X+],R0
        BRA  .init_u_num
.init_u2_sys:
        MOV  R0,#7
        ST   [X+],R0
        MOV  R0,#$53            ; 'S'
        ST   [X+],R0
        MOV  R0,#$59            ; 'Y'
        ST   [X+],R0
        MOV  R0,#$53            ; 'S'
        ST   [X+],R0
        MOV  R0,#$54            ; 'T'
        ST   [X+],R0
        MOV  R0,#$45            ; 'E'
        ST   [X+],R0
        MOV  R0,#$52            ; 'R'
        ST   [X+],R0
        MOV  R0,#$4D            ; 'M'
        ST   [X+],R0
        BRA  .init_u_num
.init_u4_sys:
        MOV  R0,#6
        ST   [X+],R0
        MOV  R0,#$53            ; 'S'
        ST   [X+],R0
        MOV  R0,#$59            ; 'Y'
        ST   [X+],R0
        MOV  R0,#$53            ; 'S'
        ST   [X+],R0
        MOV  R0,#$54            ; 'T'
        ST   [X+],R0
        MOV  R0,#$45            ; 'E'
        ST   [X+],R0
        MOV  R0,#$4D            ; 'M'
        ST   [X+],R0
        CLR  R0
        ST   [X+],R0
        BRA  .init_u_num
.init_u_noname:
        CLR  R0
        ST   [X+],R0
        ST   [X+],R0
        ST   [X+],R0
        ST   [X+],R0
        ST   [X+],R0
        ST   [X+],R0
        ST   [X+],R0
        ST   [X+],R0
.init_u_num:
        ; Offset +8 (2 bytes): UnitNumber
        MOV  R0,R2
        ST   [X+],R0
        CLR  R0
        ST   [X+],R0
        ; Offset +10 (2 bytes): BlockCount (494 for Unit 4, 0 otherwise)
        CMP  R2,#4
        BEQ  .init_u4_blocks
        CLR  R0
        ST   [X+],R0
        ST   [X+],R0
        BRA  .init_u_next
.init_u4_blocks:
        MOV  R0,#<494
        ST   [X+],R0
        MOV  R0,#>494
        ST   [X+],R0
.init_u_next:
        ADD  R2,#1
        CMP  R2,#13
        BLO  .init_unit_lp

        ; Populate SYSCOM segment entries from block 186
        CALL pm_init_syscom_segments

        ; Initialize SYSCOM fields:
        ; SYSUNIT (word 2 = offset 4) = 4
        LDW  X,#PM_SYSCOM
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R0,#4
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        MOV  R0,#4
        ST   [X+],R0
        CLR  R0
        ST   [X+],R0

        ; MISCINFO (word 29 = offset 58) = $000D (HASCLOCK + HASLCCRT + HASXYCRT, USERKIND=0)
        LDW  X,#PM_SYSCOM
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R0,#58
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        MOV  R0,#$0D
        ST   [X+],R0
        CLR  R0
        ST   [X+],R0

        ; CRTHIGH (word 37 = offset 74) = 30
        LDW  X,#PM_SYSCOM
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R0,#74
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        MOV  R0,#30
        ST   [X+],R0
        CLR  R0
        ST   [X+],R0

        ; CRTWIDE (word 38 = offset 76) = 80
        LDW  X,#PM_SYSCOM
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R0,#76
        ADC  R1,#0
        MOV  XH,R1
        MOV  XL,R0
        MOV  R0,#80
        ST   [X+],R0
        CLR  R0
        ST   [X+],R0

        ; 5. Populate Segment Dictionary entries in SYSCOM from block 186
        CALL pm_init_syscom_segments

pm_main_loop:
        LDW  X,#PM_QUIT
        LD   R0,[X]
        TST  R0
        BNE  pm_exit

        CALL pm_fetch_b
        LDW  X,#PM_OP
        ST   [X],R0
        MOV  R2,R0

        CMP  R2,#128
        BLO  .do_sldc
        CMP  R2,#216
        BLO  .do_table
        CMP  R2,#232
        BLO  .do_sldl
        CMP  R2,#248
        BLO  .do_sldo
        CALL pm_op_sind
        BRA  pm_main_loop

.do_sldc:
        CALL pm_op_sldc
        BRA  pm_main_loop

.do_sldl:
        CALL pm_op_sldl
        BRA  pm_main_loop

.do_sldo:
        CALL pm_op_sldo
        BRA  pm_main_loop

.do_table:
        SUB  R2,#128
        CLR  R3
        SHL  R2
        ROL  R3
        LDW  X,#pm_optab_128
        MOV  R0,XL
        MOV  R1,XH
        ADD  R0,R2
        ADC  R1,R3
        MOV  XH,R1
        MOV  XL,R0
        LD   R0,[X+]
        LD   R1,[X]
        MOV  XH,R1
        MOV  XL,R0
        CALL [X]
        BRA  pm_main_loop

pm_exit:
        CALL con_nl
        LDW  X,#.str_exit
        CALL con_puts
        CALL con_nl
        RET

.str_exit:
        .asciz "[UCSD Pascal p-System Halted]"

pm_op_nop:
        RET

        .align 2
pm_optab_128:
        .word pm_op_abi         ; 128 ABI
        .word pm_op_nop         ; 129 ABR
        .word pm_op_adi         ; 130 ADI
        .word pm_op_nop         ; 131 ADR
        .word pm_op_land        ; 132 LAND
        .word pm_op_dif         ; 133 DIF
        .word pm_op_dvi         ; 134 DVI
        .word pm_op_nop         ; 135 DVR
        .word pm_op_chk         ; 136 CHK
        .word pm_op_nop         ; 137 FLO
        .word pm_op_nop         ; 138 FLT
        .word pm_op_inn         ; 139 INN
        .word pm_op_int         ; 140 INT
        .word pm_op_lor         ; 141 LOR
        .word pm_op_modi        ; 142 MODI
        .word pm_op_mpi         ; 143 MPI
        .word pm_op_nop         ; 144 MPR
        .word pm_op_ngi         ; 145 NGI
        .word pm_op_nop         ; 146 NGR
        .word pm_op_lnot        ; 147 LNOT
        .word pm_op_srs         ; 148 SRS
        .word pm_op_sbi         ; 149 SBI
        .word pm_op_nop         ; 150 SBR
        .word pm_op_sgs         ; 151 SGS
        .word pm_op_sqi         ; 152 SQI
        .word pm_op_nop         ; 153 SQR
        .word pm_op_sto         ; 154 STO
        .word pm_op_ixs         ; 155 IXS
        .word pm_op_uni         ; 156 UNI
        .word pm_op_lde         ; 157 LDE
        .word pm_op_csp         ; 158 CSP
        .word pm_op_ldcn        ; 159 LDCN
        .word pm_op_adj         ; 160 ADJ
        .word pm_op_fjp         ; 161 FJP
        .word pm_op_inc         ; 162 INC
        .word pm_op_ind         ; 163 IND
        .word pm_op_ixa         ; 164 IXA
        .word pm_op_lao         ; 165 LAO
        .word pm_op_lsa         ; 166 LSA
        .word pm_op_lae         ; 167 LAE
        .word pm_op_mov         ; 168 MOV
        .word pm_op_ldo         ; 169 LDO
        .word pm_op_sas         ; 170 SAS
        .word pm_op_sro         ; 171 SRO
        .word pm_op_xjp         ; 172 XJP
        .word pm_op_rnp         ; 173 RNP
        .word pm_op_cip         ; 174 CIP
        .word pm_op_equ         ; 175 EQU
        .word pm_op_geq         ; 176 GEQ
        .word pm_op_grt         ; 177 GRT
        .word pm_op_lda         ; 178 LDA
        .word pm_op_ldc         ; 179 LDC
        .word pm_op_leq         ; 180 LEQ
        .word pm_op_les         ; 181 LES
        .word pm_op_lod         ; 182 LOD
        .word pm_op_neq         ; 183 NEQ
        .word pm_op_str         ; 184 STR
        .word pm_op_ujp         ; 185 UJP
        .word pm_op_ldp         ; 186 LDP
        .word pm_op_stp         ; 187 STP
        .word pm_op_ldm         ; 188 LDM
        .word pm_op_stm         ; 189 STM
        .word pm_op_ldb         ; 190 LDB
        .word pm_op_stb         ; 191 STB
        .word pm_op_ixp         ; 192 IXP
        .word pm_op_rbp         ; 193 RBP
        .word pm_op_cbp         ; 194 CBP
        .word pm_op_equi        ; 195 EQUI
        .word pm_op_geqi        ; 196 GEQI
        .word pm_op_grti        ; 197 GRTI
        .word pm_op_lla         ; 198 LLA
        .word pm_op_ldci        ; 199 LDCI
        .word pm_op_leqi        ; 200 LEQI
        .word pm_op_lesi        ; 201 LESI
        .word pm_op_ldl         ; 202 LDL
        .word pm_op_neqi        ; 203 NEQI
        .word pm_op_stl         ; 204 STL
        .word pm_op_cxp         ; 205 CXP
        .word pm_op_clp         ; 206 CLP
        .word pm_op_cgp         ; 207 CGP
        .word pm_op_lpa         ; 208 LPA
        .word pm_op_ste         ; 209 STE
        .word pm_op_nop         ; 210 NOP
        .word pm_op_efj         ; 211 EFJ
        .word pm_op_nfj         ; 212 NFJ
        .word pm_op_nop         ; 213 BPT
        .word pm_op_nop         ; 214 XIT
        .word pm_op_nop         ; 215 NOP
