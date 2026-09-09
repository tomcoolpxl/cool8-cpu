; ---------------------------------------------------------------------
; z3_mem.asm -- Memory management, SPI Flash demand paging & LRU cache
; ---------------------------------------------------------------------

; z_init_cache -- clears all 16 cache page tags
z_init_cache:
        LDW  X,#Z_TAGS_BASE
        MOV  R0,#16
.clp:   MOV  R1,#$FF            ; page $FFFF = empty
        ST   [X+],R1
        ST   [X+],R1
        MOV  R1,#255            ; max age
        ST   [X+],R1
        SUB  R0,#1
        BNE  .clp
        RET

; z_read_byte -- reads byte at story address (R1:X) -> R0
; R1 = high byte (bits 16..23), X = 16-bit address (bits 0..15)
z_read_byte:
        TST  R1
        BNE  .paged
        ; In 16-bit space, check if below static memory base
        LDW  Y,#Z_STATIC
        LD   R2,[Y]
        LD   R3,[Y+1]           ; R3:R2 = static base
        MOV  R0,XL
        CMP  R0,R2
        MOV  R0,XH
        SBC  R0,R3
        BHS  .paged

        ; Fast dynamic RAM read: $2000 + X
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        LD   R0,[Y]
        RET

.paged: ; Static / High memory read through 16-page LRU cache (512-byte pages)
        ; Page ID = (R1 << 7) | (XH >> 1)
        MOV  R0,R1
        SHL  R0
        SHL  R0
        SHL  R0
        SHL  R0
        SHL  R0
        SHL  R0
        SHL  R0
        MOV  R2,XH
        SHR  R2
        OR   R0,R2              ; R0 = Page ID Low
        MOV  R3,R1
        SHR  R3                 ; R3 = Page ID High

        ; Page offset high (bit 8) in R2
        MOV  R2,XH
        AND  R2,#1              ; R2 = offset high (bit 8)

        PUSHW X                 ; [1] original address
        PUSH R2                 ; [2] offset high bit
        PUSH R0                 ; [3] page ID low
        PUSH R3                 ; [4] page ID high

        ; Search 16 cache tags for (R3:R0)
        LDW  Y,#Z_TAGS_BASE
        CLR  R2                 ; slot index 0..15
.tchk:  LD   R1,[Y]
        CMP  R1,R0
        BNE  .tnext
        LD   R1,[Y+1]
        CMP  R1,R3
        BEQ  .tag_hit
.tnext: ADDW Y,#3
        ADD  R2,#1
        CMP  R2,#16
        BLO  .tchk

        ; Miss! Find LRU slot (maximum age)
        ; First, age all 16 slots (saturate at 255)
        LDW  Y,#Z_TAGS_BASE+2
        CLR  R0
.inc_age:
        LD   R1,[Y]
        CMP  R1,#$FF
        BEQ  .ag_sat
        ADD  R1,#1
        ST   [Y],R1
.ag_sat:ADDW Y,#3
        ADD  R0,#1
        CMP  R0,#16
        BLO  .inc_age

        LDW  Y,#Z_TAGS_BASE
        CLR  R2                 ; best slot = 0
        CLR  R1                 ; max age seen = 0
        CLR  R0                 ; loop counter = 0
.fage:  LD   R3,[Y+2]           ; age byte
        CMP  R3,R1
        BLO  .anext
        MOV  R1,R3
        MOV  R2,R0              ; best slot = R0
.anext: ADDW Y,#3
        ADD  R0,#1
        CMP  R0,#16
        BLO  .fage

        ; Slot R2 is chosen. Restore Page ID (R3:R0)
        POP  R3                 ; R3 = page ID high
        POP  R0                 ; R0 = page ID low
        PUSH R0                 ; keep on stack until tags written
        PUSH R3
        PUSH R2                 ; save chosen slot

        ; Calculate Flash Address: (R3:R0) << 9
        MOV  R1,R0
        SHL  R1                 ; R1 = mid byte
        MOV  R2,R0
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        MOV  R0,R3
        SHL  R0
        OR   R2,R0              ; R2 = high byte

        ; Add Flash Base
        LDW  X,#Z_FLS_L
        LD   R0,[X+1]           ; mid base
        ADD  R1,R0
        LD   R0,[X+2]           ; high base
        ADC  R2,R0

        ; Set SPI Flash read address and open stream
        CLR  R0
        ST   [FLS_CTRL],R0
        ST   [FLS_ADDR_L],R0
        ST   [FLS_ADDR_M],R1
        ST   [FLS_ADDR_H],R2
        MOV  R0,#1
        ST   [FLS_CTRL],R0

        ; Write Tag for slot (slot was saved on stack)
        POP  R2                 ; R2 = slot
        POP  R3                 ; R3 = page ID high
        POP  R0                 ; R0 = page ID low
        PUSH R2                 ; keep slot on stack

        MOV  R1,R2
        ADD  R1,R1
        ADD  R1,R2              ; R1 = slot * 3
        LDW  Y,#Z_TAGS_BASE
        ADDW Y,R1
        ST   [Y],R0
        ST   [Y+1],R3
        CLR  R1
        ST   [Y+2],R1           ; age = 0

        ; Buffer addr = Z_CACHE_BASE + (R2 << 9)
        LDW  X,#Z_CACHE_BASE
        MOV  R1,R2
        SHL  R1                 ; R1 = slot * 2
        ADD  R1,#>Z_CACHE_BASE
        MOV  XH,R1
        CLR  R1
        MOV  XL,R1

        ; Stream 512 bytes from FLS_DATA
        MOV  R0,#2              ; 2 pages of 256 bytes
.p512:  CLR  R1
.str512:LD   R3,[FLS_DATA]
        ST   [X+],R3
        SUB  R1,#1
        BNE  .str512
        SUB  R0,#1
        BNE  .p512

        CLR  R0
        ST   [FLS_CTRL],R0      ; close read stream
        POP  R2                 ; R2 = slot
        BRA  .thit

.tag_hit:
        POP  R3                 ; discard saved Page ID
        POP  R0

.thit:  ; Slot in R2. Reset slot R2 age to 0
        MOV  R1,R2
        ADD  R1,R1
        ADD  R1,R2              ; R1 = slot * 3
        LDW  Y,#Z_TAGS_BASE
        ADDW Y,R1
        CLR  R0
        ST   [Y+2],R0           ; age = 0

        ; Compute byte in slot: Z_CACHE_BASE + (R2 << 9) + offset
        POP  R1                 ; R1 = offset high bit
        POPW X                  ; X = original 16-bit address (XL = offset low)
        MOV  R0,R2
        SHL  R0                 ; R0 = R2 * 2
        OR   R0,R1              ; add offset high bit
        ADD  R0,#>Z_CACHE_BASE
        MOV  YH,R0
        MOV  R1,XL
        MOV  YL,R1
        LD   R0,[Y]
        RET

; z_read_word -- reads 16-bit big-endian word at (R1:X) -> X
z_read_word:
        PUSH R1
        PUSHW X
        CALL z_read_byte
        MOV  R2,R0              ; R2 = high byte
        POPW X
        POP  R1
        INCW X
        BNE  .nw1
        ADD  R1,#1
.nw1:   PUSH R2
        CALL z_read_byte        ; R0 = low byte
        POP  R1                 ; R1 = high byte
        MOV  XL,R0
        MOV  XH,R1
        RET

; z_write_byte -- writes byte R0 to dynamic RAM address X ($2000 + X)
z_write_byte:
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        ST   [Y],R0
        RET

; z_write_word -- writes 16-bit word (R1:R0) big-endian to dynamic RAM address X
z_write_word:
        MOVW Y,X
        ADDW Y,#Z_DYN_BASE
        ST   [Y],R1
        ST   [Y+1],R0
        RET

; z_fetch_pc_byte -- fetches byte at Z_PC and advances Z_PC -> R0
z_fetch_pc_byte:
        LDW  Y,#Z_PC_L
        LD   R0,[Y]
        LD   R1,[Y+1]
        LD   R2,[Y+2]
        MOV  XL,R0
        MOV  XH,R1
        MOV  R1,R2
        PUSH R1
        PUSHW X
        CALL z_read_byte        ; R0 = fetched byte
        POPW X
        POP  R1
        INCW X
        BNE  .pc1
        ADD  R1,#1
.pc1:   LDW  Y,#Z_PC_L
        MOV  R2,XL
        ST   [Y],R2
        MOV  R2,XH
        ST   [Y+1],R2
        ST   [Y+2],R1
        RET

; z_fetch_pc_word -- fetches 16-bit big-endian word at Z_PC -> X
z_fetch_pc_word:
        CALL z_fetch_pc_byte
        PUSH R0                 ; save high byte on stack
        CALL z_fetch_pc_byte    ; low byte in R0
        MOV  XL,R0
        POP  R0                 ; restore high byte
        MOV  XH,R0
        RET
