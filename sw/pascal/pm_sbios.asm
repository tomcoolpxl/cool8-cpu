; ---------------------------------------------------------------------
; sw/pascal/pm_sbios.asm -- Simplified Basic I/O Subsystem (SBIOS)
; ---------------------------------------------------------------------

; UnitRead(Unit, Addr, AddrOffset, Len, Block)
; Stack order (TOS down): Block, Len, AddrOffset, Addr, Unit
pm_sbios_unitread:
        CALL pm_pop             ; Mode in R1:R0
        CALL pm_pop             ; Block in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Len in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; AddrOffset in R1:R0
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Addr in R1:R0
        LDW  Y,#PM_TMP3
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Unit in R1:R0 (Unit in R0)

        ; Compute Effective Address = Addr + AddrOffset -> PM_TMP2
        PUSH R0                 ; Save Unit
        LDW  Y,#PM_TMP3
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP2
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        ST   [Y],R0             ; EffAddr low
        ST   [Y+1],R1           ; EffAddr high
        POP  R0                 ; Restore Unit

        CMP  R0,#1
        BEQ  .ur_console
        CMP  R0,#2
        BEQ  .ur_systerm
        CMP  R0,#4
        BEQ  pm_disk_read

        ; Unmounted unit (e.g. 5, 9, 10, 11, 12) -> IORSLT = 9 (device offline)
        MOV  R0,#9
        CLR  R1
        JMP  pm_sbios_set_iorslt

.ur_console:
        CLR  R0
        CLR  R1
        CALL pm_sbios_set_iorslt

        LDW  Y,#PM_TMP1         ; Len
        LD   R2,[Y]
        LD   R3,[Y+1]
        MOV  R0,R2
        OR   R0,R3
        BEQ  .ur_done

        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R1
        MOV  XL,R0

.ur_con_lp:
        CALL pm_get_key
        TST  R0
        BEQ  .ur_con_lp

        ; Store R0 into [EffAddr] and increment EffAddr
        PUSH R0
        LDW  X,#PM_TMP2
        LD   R2,[X]
        LD   R3,[X+1]
        MOV  XL,R2
        MOV  XH,R3
        POP  R0
        ST   [X+],R0
        PUSH R0
        MOV  R2,XL
        MOV  R3,XH
        LDW  X,#PM_TMP2
        ST   [X],R2
        ST   [X+1],R3

        ; Decrement Len in PM_TMP1
        LDW  X,#PM_TMP1
        LD   R2,[X]
        LD   R3,[X+1]
        SUB  R2,#1
        SBC  R3,#0
        ST   [X],R2
        ST   [X+1],R3

        ; Echo character
        POP  R0
        CALL pm_con_putc
.ur_con_chk:
        LDW  X,#PM_TMP1
        LD   R2,[X]
        LD   R3,[X+1]
        MOV  R0,R2
        OR   R0,R3
        BNE  .ur_con_lp
        BRA  .ur_done

.ur_systerm:
        CLR  R0
        CLR  R1
        CALL pm_sbios_set_iorslt

        LDW  Y,#PM_TMP1         ; Len
        LD   R2,[Y]
        LD   R3,[Y+1]
        MOV  R0,R2
        OR   R0,R3
        BEQ  .ur_done

.ur_sys_lp:
        CALL in_key
        TST  R0
        BEQ  .ur_sys_lp

        ; Store R0 into [EffAddr] and increment EffAddr
        PUSH R0
        LDW  X,#PM_TMP2
        LD   R2,[X]
        LD   R3,[X+1]
        MOV  XL,R2
        MOV  XH,R3
        POP  R0
        ST   [X+],R0
        MOV  R2,XL
        MOV  R3,XH
        LDW  X,#PM_TMP2
        ST   [X],R2
        ST   [X+1],R3

        ; Decrement Len in PM_TMP1
        LDW  X,#PM_TMP1
        LD   R2,[X]
        LD   R3,[X+1]
        SUB  R2,#1
        SBC  R3,#0
        ST   [X],R2
        ST   [X+1],R3
        MOV  R0,R2
        OR   R0,R3
        BNE  .ur_sys_lp
        BRA  .ur_done

.ur_done:
        RET

pm_get_key:
        CALL in_key
        TST  R0
        BEQ  .gk_none
        TST  R1
        BEQ  .gk_plain
        ; Named key (R1 == 1)
        CMP  R0,#6              ; K_DEL
        BEQ  .gk_bs
        CMP  R0,#2              ; K_LEFT
        BEQ  .gk_bs
        CMP  R0,#0              ; K_UP
        BEQ  .gk_up
        CMP  R0,#1              ; K_DOWN
        BEQ  .gk_down
        CMP  R0,#3              ; K_RIGHT
        BEQ  .gk_right
        BRA  pm_get_key
.gk_bs: MOV  R0,#$08
        RET
.gk_up: MOV  R0,#$0F
        RET
.gk_down: MOV R0,#$0C
        RET
.gk_right: MOV R0,#$15
        RET
.gk_plain:
        CMP  R0,#$7F            ; DEL ($7F) -> BS ($08)
        BNE  .gk_done
        MOV  R0,#$08
.gk_done:
        RET
.gk_none:
        RET

pm_disk_read:
.ur_disk:
        CLR  R0
        CLR  R1
        CALL pm_sbios_set_iorslt

.ur_blk_lp:
        ; Check if PM_TMP1 (remaining length) is 0
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        OR   R0,R1
        BEQ  .ur_disk_done

        ; Compute chunk size for this block: R2:R3 = min(PM_TMP1, 512)
        LD   R2,[Y]
        LD   R3,[Y+1]
        CMP  R3,#2
        BNE  .ur_chk_sz
        CMP  R2,#0
        BEQ  .ur_sz_512
.ur_chk_sz:
        BHI  .ur_sz_512
        BRA  .ur_sz_set
.ur_sz_512:
        CLR  R2
        MOV  R3,#2              ; 512 bytes ($0200)
.ur_sz_set:
        ; Save chunk size to PM_TMP4
        LDW  X,#PM_TMP4
        ST   [X],R2
        ST   [X+1],R3

        ; Search VRAM cache for block in PM_TMP0
        LD   R2,[PM_VCACHE_CNT]
        CLR  R3                 ; slot index = 0
        LDW  X,#PM_VCACHE_BLK
.ur_search_lp:
        LD   R2,[PM_VCACHE_CNT]
        CMP  R3,R2
        BEQ  .ur_not_cached
        LD   R0,[X+]
        LD   R1,[X+]
        LD   R2,[PM_TMP0]
        CMP  R0,R2
        BNE  .ur_next_slot
        LD   R2,[PM_TMP0+1]
        CMP  R1,R2
        BEQ  .ur_found_cache
.ur_next_slot:
        ADD  R3,#1
        BRA  .ur_search_lp

.ur_found_cache:
        ; Cached at slot R3! VRAM start address = R3 * 512 = (R3 << 9) = high byte (R3 << 1), low byte 0
        MOV  R0,R3
        SHL  R0                 ; R0 = R3 * 2 (high byte of VRAM address)
        CLR  R1
        ST   [VRAM_ADDR_L],R1
        ST   [VRAM_ADDR_H],R0
        MOV  R0,#1              ; auto-step +1
        ST   [VRAM_STEP],R0

        ; Destination pointer from PM_TMP2
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XL,R0
        MOV  XH,R1

        ; Read chunk bytes from VRAM_DATA
        LDW  Y,#PM_TMP4
        LD   R2,[Y]
        LD   R3,[Y+1]
.ur_vram_lp:
        MOV  R0,R2
        OR   R0,R3
        BEQ  .ur_blk_step
        LD   R0,[VRAM_DATA]
        ST   [X+],R0
        SUB  R2,#1
        SBC  R3,#0
        BRA  .ur_vram_lp

.ur_not_cached:
        ; Read from SPI Flash: Flash Address = $790000 + Block * 512
        LDW  Y,#PM_TMP0
        LD   R0,[Y]             ; Block_L
        LD   R1,[Y+1]           ; Block_H
        SHL  R0
        ROL  R1
        MOV  R2,R1
        ADD  R2,#$79

        CLR  R3
        ST   [FLS_CTRL],R3
        ST   [FLS_ADDR_L],R3
        ST   [FLS_ADDR_M],R0
        ST   [FLS_ADDR_H],R2
        MOV  R3,#1
        ST   [FLS_CTRL],R3

        ; Destination pointer from PM_TMP2
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XL,R0
        MOV  XH,R1

        ; Read chunk bytes from FLS_DATA
        LDW  Y,#PM_TMP4
        LD   R2,[Y]
        LD   R3,[Y+1]
.ur_fls_lp:
        MOV  R0,R2
        OR   R0,R3
        BEQ  .ur_fls_done
        LD   R0,[FLS_DATA]
        ST   [X+],R0
        SUB  R2,#1
        SBC  R3,#0
        BRA  .ur_fls_lp

.ur_fls_done:
        CLR  R0
        ST   [FLS_CTRL],R0

.ur_blk_step:
        ; Advance PM_TMP2 (RAM buffer pointer) by chunk in PM_TMP4
        LDW  Y,#PM_TMP4
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  X,#PM_TMP2
        LD   R2,[X]
        LD   R3,[X+1]
        ADD  R2,R0
        ADC  R3,R1
        ST   [X],R2
        ST   [X+1],R3

        ; Decrement PM_TMP1 (remaining length) by chunk in PM_TMP4
        LDW  X,#PM_TMP1
        LD   R2,[X]
        LD   R3,[X+1]
        SUB  R2,R0
        SBC  R3,R1
        ST   [X],R2
        ST   [X+1],R3

        ; Increment PM_TMP0 (Block number) by 1
        LDW  X,#PM_TMP0
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R0,#1
        ADC  R1,#0
        ST   [X],R0
        ST   [X+1],R1

        BRA  .ur_blk_lp

.ur_disk_done:
        RET

; Clear to end of line helper
pm_con_clreol:
        PUSH R0
        PUSH R1
        PUSH R2
        PUSH R3
        PUSHW X
        LD   R0,[CCY]
        LD   R1,[CCX]
.ce_lp: LD   R2,[CCOLS]
        CMP  R1,R2
        BHS  .ce_done
        MOV  R2,#$20            ; ' '
        LD   R3,[CATTR]
        PUSH R0
        PUSH R1
        CALL con_put
        POP  R1
        POP  R0
        ADD  R1,#1
        BRA  .ce_lp
.ce_done:
        POPW X
        POP  R3
        POP  R2
        POP  R1
        POP  R0
        RET

; UnitWrite(Unit, Addr, AddrOffset, Len, Block)
; Stack order (TOS down): Block, Len, AddrOffset, Addr, Unit
pm_sbios_unitwrite:
        CALL pm_pop             ; Mode in R1:R0
        CALL pm_pop             ; Block in R1:R0
        LDW  Y,#PM_TMP0
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Len in R1:R0
        LDW  Y,#PM_TMP1
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; AddrOffset in R1:R0
        LDW  Y,#PM_TMP2
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Addr in R1:R0
        LDW  Y,#PM_TMP3
        ST   [Y],R0
        ST   [Y+1],R1

        CALL pm_pop             ; Unit in R1:R0 (Unit in R0)

        ; Compute Effective Address = Addr + AddrOffset -> PM_TMP2
        PUSH R0                 ; Save Unit
        LDW  Y,#PM_TMP3
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  Y,#PM_TMP2
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        ST   [Y],R0             ; EffAddr low
        ST   [Y+1],R1           ; EffAddr high
        POP  R0                 ; Restore Unit

        CMP  R0,#1
        BEQ  .uw_console
        CMP  R0,#2
        BEQ  .uw_console
        CMP  R0,#3
        BEQ  .uw_disk
        CMP  R0,#4
        BEQ  .uw_disk

        ; Unmounted unit -> IORSLT = 9
        MOV  R0,#9
        CLR  R1
        JMP  pm_sbios_set_iorslt

.uw_disk:
        CLR  R0
        CLR  R1
        CALL pm_sbios_set_iorslt

.uw_blk_lp:
        ; Check if PM_TMP1 (remaining length) is 0
        LDW  Y,#PM_TMP1
        LD   R0,[Y]
        LD   R1,[Y+1]
        OR   R0,R1
        BEQ  .uw_disk_done

        ; Compute chunk size for this block: R2:R3 = min(PM_TMP1, 512)
        LD   R2,[Y]
        LD   R3,[Y+1]
        CMP  R3,#2
        BNE  .uw_chk_sz
        CMP  R2,#0
        BEQ  .uw_sz_512
.uw_chk_sz:
        BHI  .uw_sz_512
        BRA  .uw_sz_set
.uw_sz_512:
        CLR  R2
        MOV  R3,#2              ; 512 bytes ($0200)
.uw_sz_set:
        ; Save chunk size to PM_TMP4
        LDW  X,#PM_TMP4
        ST   [X],R2
        ST   [X+1],R3

        ; Search if block in PM_TMP0 is already in VRAM cache
        LD   R2,[PM_VCACHE_CNT]
        CLR  R3                 ; slot index = 0
        LDW  X,#PM_VCACHE_BLK
.uw_search_lp:
        LD   R2,[PM_VCACHE_CNT]
        CMP  R3,R2
        BEQ  .uw_alloc_slot
        LD   R0,[X+]
        LD   R1,[X+]
        LD   R2,[PM_TMP0]
        CMP  R0,R2
        BNE  .uw_next_slot
        LD   R2,[PM_TMP0+1]
        CMP  R1,R2
        BEQ  .uw_do_write
.uw_next_slot:
        ADD  R3,#1
        BRA  .uw_search_lp

.uw_alloc_slot:
        ; Not in cache. Allocate slot R3 = PM_VCACHE_CNT
        ; Check if cache full (32 slots)
        CMP  R2,#32
        BLO  .uw_slot_ok
        ; Cache full -> wrap or keep at 31
        MOV  R3,#31
        BRA  .uw_store_blk
.uw_slot_ok:
        MOV  R3,R2
        ADD  R2,#1
        ST   [PM_VCACHE_CNT],R2
.uw_store_blk:
        ; Store PM_TMP0 at PM_VCACHE_BLK + R3*2
        MOV  R0,R3
        SHL  R0                 ; R0 = R3 * 2
        LDW  X,#PM_VCACHE_BLK
        ADDW X,R0
        LDW  Y,#PM_TMP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        ST   [X],R0
        ST   [X+1],R1

.uw_do_write:
        ; Slot R3 is our VRAM block index!
        ; VRAM address = R3 * 512 = (R3 << 9) = high byte (R3 << 1), low byte 0
        MOV  R0,R3
        SHL  R0                 ; high byte of VRAM address
        CLR  R1
        ST   [VRAM_ADDR_L],R1
        ST   [VRAM_ADDR_H],R0
        MOV  R0,#1              ; auto-step +1
        ST   [VRAM_STEP],R0

        ; Source pointer from PM_TMP2
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XL,R0
        MOV  XH,R1

        ; Write chunk bytes to VRAM_DATA
        LDW  Y,#PM_TMP4
        LD   R2,[Y]
        LD   R3,[Y+1]
.uw_vram_lp:
        MOV  R0,R2
        OR   R0,R3
        BEQ  .uw_blk_step
        LD   R0,[X+]
        ST   [VRAM_DATA],R0
        SUB  R2,#1
        SBC  R3,#0
        BRA  .uw_vram_lp

.uw_blk_step:
        ; Advance PM_TMP2 (RAM buffer pointer) by chunk in PM_TMP4
        LDW  Y,#PM_TMP4
        LD   R0,[Y]
        LD   R1,[Y+1]
        LDW  X,#PM_TMP2
        LD   R2,[X]
        LD   R3,[X+1]
        ADD  R2,R0
        ADC  R3,R1
        ST   [X],R2
        ST   [X+1],R3

        ; Decrement PM_TMP1 (remaining length) by chunk in PM_TMP4
        LDW  X,#PM_TMP1
        LD   R2,[X]
        LD   R3,[X+1]
        SUB  R2,R0
        SBC  R3,R1
        ST   [X],R2
        ST   [X+1],R3

        ; Increment PM_TMP0 (Block number) by 1
        LDW  X,#PM_TMP0
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R0,#1
        ADC  R1,#0
        ST   [X],R0
        ST   [X+1],R1

        BRA  .uw_blk_lp

.uw_disk_done:
        RET

.uw_console:
        CLR  R0
        CLR  R1
        CALL pm_sbios_set_iorslt

        LDW  Y,#PM_TMP1
        LD   R2,[Y]             ; Len low
        LD   R3,[Y+1]           ; Len high
        LDW  Y,#PM_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R1
        MOV  XL,R0

.uw_con_lp:
        MOV  R0,R2
        OR   R0,R3
        BEQ  .uw_con_done
        LD   R0,[X+]
        SUB  R2,#1
        SBC  R3,#0

        PUSHW X
        PUSH R2
        PUSH R3
        CALL pm_con_putc
        POP  R3
        POP  R2
        POPW X
        BRA  .uw_con_lp

.uw_con_done:
        RET

pm_con_putc:
        ; Character in R0
        LDW  X,#PM_TERM_STATE
        LD   R1,[X]
        TST  R1
        BEQ  .st0
        CMP  R1,#1
        BEQ  .st1
        CMP  R1,#2
        BEQ  .st2
        CMP  R1,#3
        BEQ  .st3
        CLR  R0
        ST   [X],R0
        RET

.st0:
        CMP  R0,#$0D
        BEQ  .cr
        CMP  R0,#$0A
        BEQ  .lf
        CMP  R0,#$0C
        BEQ  .cls
        CMP  R0,#$08
        BEQ  .bs
        CMP  R0,#$0B
        BEQ  .clreos
        CMP  R0,#$1D
        BEQ  .clreol
        CMP  R0,#$1C
        BEQ  .right
        CMP  R0,#$19
        BEQ  .home
        CMP  R0,#$1E
        BEQ  .to_st1
        CMP  R0,#$1F
        BEQ  .up
        CMP  R0,#$10
        BEQ  .to_st3
        JMP  con_emit

.to_st1:
        MOV  R0,#1
        ST   [PM_TERM_STATE],R0
        RET

.to_st3:
        MOV  R0,#3
        ST   [PM_TERM_STATE],R0
        RET

.cr:    JMP  con_nl

.lf:    JMP  con_nl

.cls:   JMP  con_cls
.clreol: JMP pm_con_clreol


.home:  CLR  R0
        ST   [CCX],R0
        ST   [CCY],R0
        CALL con_setrow
        JMP  con_cursor

.right: LD   R0,[CCX]
        ADD  R0,#1
        CMP  R0,#80
        BHS  .ri_d
        ST   [CCX],R0
        JMP  con_cursor
.ri_d:  RET

.clreos:
        LD   R0,[CCY]
        PUSH R0
        LD   R0,[CCX]
        PUSH R0
        CALL pm_con_clreol
        LD   R0,[CCY]
.eos_lp:
        ADD  R0,#1
        CMP  R0,#32
        BHS  .eos_d
        PUSH R0
        ST   [CCY],R0
        CLR  R0
        ST   [CCX],R0
        CALL con_setrow
        CALL pm_con_clreol
        POP  R0
        BRA  .eos_lp
.eos_d: POP  R0
        ST   [CCX],R0
        POP  R0
        ST   [CCY],R0
        CALL con_setrow
        JMP  con_cursor

.bs:    LD   R0,[CCX]
        TST  R0
        BEQ  .bs_d
        SUB  R0,#1
        ST   [CCX],R0
        CALL con_cursor
.bs_d:  RET

.up:    LD   R0,[CCY]
        TST  R0
        BEQ  .up_d
        SUB  R0,#1
        ST   [CCY],R0
        CALL con_setrow
        CALL con_cursor
.up_d:  RET

.st1:
        SUB  R0,#32
        ST   [PM_TERM_X],R0
        MOV  R0,#2
        ST   [PM_TERM_STATE],R0
        RET

.st2:
        SUB  R0,#32
        ST   [CCY],R0
        LD   R0,[PM_TERM_X]
        ST   [CCX],R0
        CALL con_setrow
        CALL con_cursor
        CLR  R0
        ST   [PM_TERM_STATE],R0
        RET

.st3:
        SUB  R0,#32
        CLR  R1
        ST   [PM_TERM_STATE],R1
.st3_lp:
        TST  R0
        BEQ  .st3_d
        PUSH R0
        MOV  R0,#$20
        CALL con_emit
        POP  R0
        SUB  R0,#1
        BRA  .st3_lp
.st3_d: RET

; Helper: Set IORSLT in SYSCOM[0] to R1:R0
pm_sbios_set_iorslt:
        LDW  X,#PM_SYSCOM
        LD   R2,[X]
        LD   R3,[X+1]
        MOV  XH,R3
        MOV  XL,R2
        ST   [X],R0
        ST   [X+1],R1
        RET
