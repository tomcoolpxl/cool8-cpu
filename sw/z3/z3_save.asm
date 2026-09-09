; ---------------------------------------------------------------------
; z3_save.asm -- Flash Disk Save and Restore for Z-Machine Version 3
; ---------------------------------------------------------------------

; z_do_save -- saves dynamic RAM, stacks, and PC to flash disk
; Returns R0 = 1 on success, R0 = 0 on error
z_do_save:
        ; 1. Mount current game volume
        LD   R0,[z_save_drive]
        CALL fs_mount

        ; 2. Delete any existing save file
        LDW  X,#z_save_filename
        CALL fs_find
        BCC  .sv_not_found
        LDW  X,#z_save_filename
        CALL fs_delete
.sv_not_found:

        ; 3. Calculate total save length = 16 + Z_STATIC + Z_SP + Z_FP
        LDW  X,#Z_STATIC
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R0,#16
        ADC  R1,#0
        LDW  X,#Z_SP
        LD   R2,[X]
        LD   R3,[X+1]
        ADD  R0,R2
        ADC  R1,R3
        LDW  X,#Z_FP
        LD   R2,[X]
        LD   R3,[X+1]
        ADD  R0,R2
        ADC  R1,R3
        ST   [fslen],R0
        ST   [fslen+1],R1

        ; 4. Check if file fits on disk
        LD   R0,[fsfent]
        CMP  R0,#$FF
        BEQ  .sv_fail                   ; directory full

        LD   R0,[fsfpg]
        LD   R2,[fsfpg+1]
        LD   R1,[fslen+1]
        ADD  R0,R1
        BCC  .fsp1
        ADD  R2,#1
.fsp1:  LD   R1,[fslen]
        TST  R1
        BEQ  .fsp2
        ADD  R0,#1
        BCC  .fsp2
        ADD  R2,#1
.fsp2:  CMP  R2,#6
        BCC  .fsp3
        BNE  .sv_fail
        CMP  R0,#$F1
        BCC  .fsp3
.sv_fail:
        CLR  R0
        RET

.fsp3:
        ; 5. Copy 11-byte filename into fsent
        LDW  X,#z_save_filename
        LDW  Y,#fsent
        MOV  R1,#11
.sn1:   LD   R0,[X+]
        ST   [Y+],R0
        SUB  R1,#1
        BNE  .sn1

        MOV  R0,#1                      ; file status = 1
        ST   [fsent+11],R0
        LD   R0,[fsfpg]
        ST   [fsent+12],R0
        LD   R0,[fsfpg+1]
        ST   [fsent+13],R0
        LD   R0,[fslen]
        ST   [fsent+14],R0
        LD   R0,[fslen+1]
        ST   [fsent+15],R0

        ; 6. Seek flash to file payload start
        CALL fs_seekfile

        ; 7. Write 16-byte metadata header
        MOV  R0,#$5A                    ; "Z"
        CALL fls_prog
        MOV  R0,#$33                    ; "3"
        CALL fls_prog
        MOV  R0,#$53                    ; "S"
        CALL fls_prog
        MOV  R0,#$56                    ; "V"
        CALL fls_prog

        LD   R0,[Z_PC_L]
        CALL fls_prog
        LD   R0,[Z_PC_M]
        CALL fls_prog
        LD   R0,[Z_PC_H]
        CALL fls_prog

        LD   R0,[Z_SP]
        CALL fls_prog
        LD   R0,[Z_SP+1]
        CALL fls_prog

        LD   R0,[Z_FP]
        CALL fls_prog
        LD   R0,[Z_FP+1]
        CALL fls_prog

        LD   R0,[Z_CALL_DEPTH]
        CALL fls_prog

        LD   R0,[Z_STATIC]
        CALL fls_prog
        LD   R0,[Z_STATIC+1]
        CALL fls_prog

        CLR  R0
        CALL fls_prog                   ; Reserved 0
        CALL fls_prog                   ; Reserved 0

        ; 8. Program Dynamic Memory (Z_STATIC bytes from Z_DYN_BASE)
        LD   R2,[Z_STATIC]
        LD   R3,[Z_STATIC+1]
        LDW  Y,#Z_DYN_BASE
.sdyn:  MOV  R0,R2
        OR   R0,R3
        BEQ  .sdyn_done
        LD   R0,[Y+]
        CALL fls_prog
        SUB  R2,#1
        BCS  .sdyn
        SUB  R3,#1
        BRA  .sdyn
.sdyn_done:

        ; 9. Program Evaluation Stack (Z_SP bytes from Z_STACK_BASE)
        LD   R2,[Z_SP]
        LD   R3,[Z_SP+1]
        LDW  Y,#Z_STACK_BASE
.ssp:   MOV  R0,R2
        OR   R0,R3
        BEQ  .ssp_done
        LD   R0,[Y+]
        CALL fls_prog
        SUB  R2,#1
        BCS  .ssp
        SUB  R3,#1
        BRA  .ssp
.ssp_done:

        ; 10. Program Call Stack (Z_FP bytes from Z_CALL_BASE)
        LD   R2,[Z_FP]
        LD   R3,[Z_FP+1]
        LDW  Y,#Z_CALL_BASE
.sfp:   MOV  R0,R2
        OR   R0,R3
        BEQ  .sfp_done
        LD   R0,[Y+]
        CALL fls_prog
        SUB  R2,#1
        BCS  .sfp
        SUB  R3,#1
        BRA  .sfp
.sfp_done:

        ; 11. Write directory entry to commit file
        LD   R0,[fsfent]
        CALL fs_seekent
        LDW  Y,#fsent
        MOV  R1,#16
.sdir:  LD   R0,[Y+]
        CALL fls_prog
        SUB  R1,#1
        BNE  .sdir

        ; 12. Mount volume again to update free page pointer
        LD   R0,[z_save_drive]
        CALL fs_mount

        MOV  R0,#1                      ; Success!
        RET


; z_do_restore -- restores dynamic RAM, stacks, and PC from flash disk
; Returns R0 = 1 on success, R0 = 0 on error
z_do_restore:
        ; 1. Mount current game volume
        LD   R0,[z_save_drive]
        CALL fs_mount

        ; 2. Look for save file
        LDW  X,#z_save_filename
        CALL fs_find
        BCS  .rst_found
        CLR  R0                         ; File not found
        RET

.rst_found:
        ; 3. Open streaming read from file start
        CALL fs_stream

        ; 4. Read & verify 4-byte magic signature
        LD   R0,[FLS_DATA]
        CMP  R0,#$5A                    ; "Z"
        BNE  .rst_err
        LD   R0,[FLS_DATA]
        CMP  R0,#$33                    ; "3"
        BNE  .rst_err
        LD   R0,[FLS_DATA]
        CMP  R0,#$53                    ; "S"
        BNE  .rst_err
        LD   R0,[FLS_DATA]
        CMP  R0,#$56                    ; "V"
        BNE  .rst_err

        ; 5. Read Z_PC into temporary storage
        LD   R0,[FLS_DATA]
        ST   [Z_TMP0],R0                ; PC_L
        LD   R0,[FLS_DATA]
        ST   [Z_TMP0+1],R0              ; PC_M
        LD   R0,[FLS_DATA]
        ST   [Z_TMP1],R0                ; PC_H

        ; 6. Read Z_SP
        LD   R0,[FLS_DATA]
        ST   [Z_TMP1+1],R0              ; SP_L
        LD   R0,[FLS_DATA]
        ST   [Z_TMP2],R0                ; SP_H

        ; 7. Read Z_FP
        LD   R0,[FLS_DATA]
        ST   [Z_TMP2+1],R0              ; FP_L
        LD   R0,[FLS_DATA]
        ST   [Z_TMP3],R0                ; FP_H

        ; 8. Read Z_CALL_DEPTH
        LD   R0,[FLS_DATA]
        ST   [Z_CALL_DEPTH],R0

        ; 9. Read Z_STATIC
        LD   R2,[FLS_DATA]              ; STATIC_L
        LD   R3,[FLS_DATA]              ; STATIC_H

        ; Skip 2 reserved bytes
        LD   R0,[FLS_DATA]
        LD   R0,[FLS_DATA]

        ; 10. Stream Dynamic Memory (R3:R2 bytes into Z_DYN_BASE)
        LDW  Y,#Z_DYN_BASE
.rdyn:  MOV  R0,R2
        OR   R0,R3
        BEQ  .rdyn_done
        LD   R0,[FLS_DATA]
        ST   [Y+],R0
        SUB  R2,#1
        BCS  .rdyn
        SUB  R3,#1
        BRA  .rdyn
.rdyn_done:

        ; 11. Stream Evaluation Stack (SP bytes into Z_STACK_BASE)
        LD   R2,[Z_TMP1+1]
        LD   R3,[Z_TMP2]
        LDW  Y,#Z_STACK_BASE
.rsp:   MOV  R0,R2
        OR   R0,R3
        BEQ  .rsp_done
        LD   R0,[FLS_DATA]
        ST   [Y+],R0
        SUB  R2,#1
        BCS  .rsp
        SUB  R3,#1
        BRA  .rsp
.rsp_done:

        ; 12. Stream Call Stack (FP bytes into Z_CALL_BASE)
        LD   R2,[Z_TMP2+1]
        LD   R3,[Z_TMP3]
        LDW  Y,#Z_CALL_BASE
.rfp:   MOV  R0,R2
        OR   R0,R3
        BEQ  .rfp_done
        LD   R0,[FLS_DATA]
        ST   [Y+],R0
        SUB  R2,#1
        BCS  .rfp
        SUB  R3,#1
        BRA  .rfp
.rfp_done:

        ; 13. Close flash read stream
        CALL fls_close

        ; 14. Commit restored registers
        LD   R0,[Z_TMP0]
        ST   [Z_PC_L],R0
        LD   R0,[Z_TMP0+1]
        ST   [Z_PC_M],R0
        LD   R0,[Z_TMP1]
        ST   [Z_PC_H],R0

        LD   R0,[Z_TMP1+1]
        ST   [Z_SP],R0
        LD   R0,[Z_TMP2]
        ST   [Z_SP+1],R0

        LD   R0,[Z_TMP2+1]
        ST   [Z_FP],R0
        LD   R0,[Z_TMP3]
        ST   [Z_FP+1],R0

        ; 15. Invalidate / flush LRU cache
        CALL z_init_cache

        MOV  R0,#1                      ; Success!
        RET

.rst_err:
        CALL fls_close
        CLR  R0
        RET
