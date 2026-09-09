# Generator for COOL8 Z-Machine Version 3 Interpreter
import os

os.makedirs("sw/z3", exist_ok=True)

# =====================================================================
# 1. sw/z3/z3_equ.asm
# =====================================================================
with open("sw/z3/z3_equ.asm", "w", encoding="utf-8") as f:
    f.write("""\
; ---------------------------------------------------------------------
; z3_equ.asm -- Constants, memory layout, and zero-page pointers for Z3
; ---------------------------------------------------------------------

Z_DYN_BASE      = $2000         ; Dynamic memory loaded into RAM ($2000..$5FFF, 16 KB)
Z_STACK_BASE    = $6000         ; Z-Machine Evaluation Stack ($6000..$63FF, 1 KB)
Z_CALL_BASE     = $6400         ; Z-Machine Call Stack ($6400..$67CF, ~1 KB)
Z_TAGS_BASE     = $67D0         ; 16 Cache Page Tags (16 * 3 = 48 bytes)
Z_CACHE_BASE    = $6800         ; 16 Pages * 512 Bytes = 8 KB ($6800..$87FF)

; Zero-Page / Scratch Workspace ($0040..$00BF)
Z_PC_L          = $0040         ; Story PC, 24-bit (Low byte)
Z_PC_M          = $0041         ; Story PC (Middle byte)
Z_PC_H          = $0042         ; Story PC (High byte)

Z_HIMEM         = $0044         ; High Memory Base (16-bit)
Z_STATIC        = $0046         ; Static Memory Base (16-bit)
Z_DICT          = $0048         ; Dictionary Address (16-bit)
Z_OBJS          = $004A         ; Object Table Address (16-bit)
Z_GLOBS         = $004C         ; Global Variables Address (16-bit)
Z_ABBREV        = $004E         ; Abbreviations Table Address (16-bit)

Z_SP            = $0050         ; Evaluation Stack Pointer (16-bit offset from Z_STACK_BASE)
Z_FP            = $0052         ; Call Frame Pointer (16-bit offset from Z_CALL_BASE)

Z_FLS_L         = $0054         ; Flash Base Offset Low
Z_FLS_M         = $0055         ; Flash Base Offset Middle
Z_FLS_H         = $0056         ; Flash Base Offset High

Z_OPCOUNT       = $0058         ; Number of operands (0..8)
Z_RESVAR        = $0059         ; Result destination variable ID
Z_BRANCH1       = $005A         ; Branch byte 1
Z_BRANCH2       = $005B         ; Branch byte 2
Z_QUIT          = $005C         ; Quit flag

Z_RND_SEED      = $005E         ; PRNG seed (16-bit)

Z_OP0           = $0060         ; Operand 0 (16-bit)
Z_OP1           = $0062         ; Operand 1 (16-bit)
Z_OP2           = $0064         ; Operand 2 (16-bit)
Z_OP3           = $0066         ; Operand 3 (16-bit)
Z_OP4           = $0068         ; Operand 4 (16-bit)
Z_OP5           = $006A         ; Operand 5 (16-bit)
Z_OP6           = $006C         ; Operand 6 (16-bit)
Z_OP7           = $006E         ; Operand 7 (16-bit)

; Text output buffer for word wrapping ($0080..$00BF)
Z_WRAP_LEN      = $0080         ; Current word length in wrap buffer
Z_WRAP_BUF      = $0082         ; 32 bytes word wrap buffer

; Scratch registers for routines
Z_TMP0          = $00A4
Z_TMP1          = $00A6
Z_TMP2          = $00A8
Z_TMP3          = $00AA
""")

# =====================================================================
# 2. sw/z3/z3_mem.asm
# =====================================================================
with open("sw/z3/z3_mem.asm", "w", encoding="utf-8") as f:
    f.write("""\
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
        CMP  XL,R2
        MOV  R0,XH
        SBC  R0,R3
        BHS  .paged

        ; Fast dynamic RAM read: $2000 + X
        LDW  Y,#Z_DYN_BASE
        ADDW Y,X
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

        ; Page offset = ((XH & 1) << 8) | XL
        MOV  R2,XH
        AND  R2,#1              ; R2 = offset high (bit 8)

        ; Search 16 cache tags for (R3:R0)
        PUSH X
        PUSH R2
        LDW  Y,#Z_TAGS_BASE
        CLR  R2                 ; slot index 0..15
.tchk:  LD   R1,[Y]
        CMP  R1,R0
        BNE  .tnext
        LD   R1,[Y+1]
        CMP  R1,R3
        BEQ  .thit
.tnext: ADDW Y,#3
        ADD  R2,#1
        CMP  R2,#16
        BLO  .tchk

        ; Miss! Find LRU slot (maximum age)
        LDW  Y,#Z_TAGS_BASE
        CLR  R2                 ; best slot
        CLR  R1                 ; max age seen
        CLR  R0                 ; loop counter
.fage:  LD   R3,[Y+2]           ; age byte
        CMP  R3,R1
        BLO  .anext
        MOV  R1,R3
        MOV  R2,R0              ; best slot = R0
.anext: ADDW Y,#3
        ADD  R0,#1
        CMP  R0,#16
        BLO  .fage

        ; Slot R2 is chosen. Load 512-byte page (R3:R0) into slot R2
        ; Flash Byte Address = Z_FLS_BASE + Page_ID * 512
        PUSH R0
        PUSH R2
        PUSH R3

        ; Calculate Flash Address: (R3:R0) << 9
        ; Low byte = 0
        ; Mid byte = (R0 << 1) & $FE
        ; High byte = (R3 << 1) | (R0 >> 7)
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

        ; Set SPI Flash read address
        CLR  R0
        ST   [FLS_ADDR_L],R0
        ST   [FLS_ADDR_M],R1
        ST   [FLS_ADDR_H],R2

        ; Target buffer = Z_CACHE_BASE + Slot * 512
        POP  R3
        POP  R2                 ; R2 = slot
        POP  R0                 ; R0 = page low

        ; Tag address for slot R2
        MOV  R1,R2
        ADD  R1,R1
        ADD  R1,R2              ; R1 = R2 * 3
        LDW  Y,#Z_TAGS_BASE
        ADDW Y,R1
        ST   [Y],R0
        ST   [Y+1],R3
        CLR  R1
        ST   [Y+2],R1           ; age = 0

        ; Buffer addr = Z_CACHE_BASE + (R2 << 9)
        LDW  X,#Z_CACHE_BASE
        MOV  R1,R2
        SHL  R1                 ; R1 = slot * 2 (high byte offset)
        MOV  XH,R1
        ADD  XH,#>Z_CACHE_BASE
        CLR  XL

        ; Stream 512 bytes from FLS_DATA
        MOV  R0,#0              ; 256 words = 512 bytes
        MOV  R1,#2              ; 2 * 256
.str512:
        LD   R3,[FLS_DATA]
        ST   [X+],R3
        SUB  R0,#1
        SBC  R1,#0
        BNE  .str512

.thit:  ; Slot in R2. Age all other slots, reset slot R2 age to 0
        LDW  Y,#Z_TAGS_BASE
        CLR  R0
.agelp: CMP  R0,R2
        BEQ  .agself
        LD   R1,[Y+2]
        CMP  R1,#254
        BHS  .agself
        ADD  R1,#1
        ST   [Y+2],R1
        BRA  .agnxt
.agself:CLR  R1
        ST   [Y+2],R1
.agnxt: ADDW Y,#3
        ADD  R0,#1
        CMP  R0,#16
        BLO  .agelp

        ; Compute byte in slot: Z_CACHE_BASE + (R2 << 9) + offset
        POP  R1                 ; R1 = offset high
        POP  X                  ; X = original 16-bit address (XL = offset low)
        MOV  R0,R2
        SHL  R0                 ; R0 = R2 * 2
        OR   R0,R1              ; add offset high bit
        ADD  R0,#>Z_CACHE_BASE
        MOV  YH,R0
        MOV  YL,XL
        LD   R0,[Y]
        RET

; z_read_word -- reads 16-bit big-endian word at (R1:X) -> X
z_read_word:
        PUSH R1
        PUSH X
        CALL z_read_byte
        MOV  R2,R0              ; R2 = high byte
        POP  X
        POP  R1
        ADDW X,#1
        BCC  .nw1
        ADD  R1,#1
.nw1:   PUSH R2
        CALL z_read_byte        ; R0 = low byte
        POP  R1                 ; R1 = high byte
        MOV  XL,R0
        MOV  XH,R1
        RET

; z_write_byte -- writes byte R0 to dynamic RAM address X ($2000 + X)
z_write_byte:
        LDW  Y,#Z_DYN_BASE
        ADDW Y,X
        ST   [Y],R0
        RET

; z_write_word -- writes 16-bit word (R1:R0) big-endian to dynamic RAM address X
z_write_word:
        LDW  Y,#Z_DYN_BASE
        ADDW Y,X
        ST   [Y],R1
        ST   [Y+1],R0
        RET

; z_fetch_pc_byte -- fetches byte at Z_PC and advances Z_PC -> R0
z_fetch_pc_byte:
        LDW  X,#Z_PC_L
        LD   XL,[X]
        LD   XH,[X+1]
        LD   R1,[X+2]
        PUSH R1
        PUSH X
        CALL z_read_byte        ; R0 = fetched byte
        POP  X
        POP  R1
        ADDW X,#1
        BCC  .pc1
        ADD  R1,#1
.pc1:   LDW  Y,#Z_PC_L
        ST   [Y],XL
        ST   [Y+1],XH
        ST   [Y+2],R1
        RET

; z_fetch_pc_word -- fetches 16-bit big-endian word at Z_PC -> X
z_fetch_pc_word:
        CALL z_fetch_pc_byte
        MOV  R2,R0              ; high byte
        CALL z_fetch_pc_byte    ; low byte
        MOV  XL,R0
        MOV  XH,R2
        RET
""")

# =====================================================================
# 3. sw/z3/z3_stack.asm
# =====================================================================
with open("sw/z3/z3_stack.asm", "w", encoding="utf-8") as f:
    f.write("""\
; ---------------------------------------------------------------------
; z3_stack.asm -- Z-Machine stack, call frames, and variable access
; ---------------------------------------------------------------------

; z_push -- pushes 16-bit word X to evaluation stack
z_push:
        PUSH Y
        LDW  Y,#Z_SP
        LD   R0,[Y]
        LD   R1,[Y+1]
        PUSH X
        LDW  X,#Z_STACK_BASE
        ADDW X,R0
        POP  Y                  ; Y = value X
        ST   [X],YH
        ST   [X+1],YL
        ADD  R0,#2
        BCC  .sp1
        ADD  R1,#1
.sp1:   LDW  X,#Z_SP
        ST   [X],R0
        ST   [X+1],R1
        POP  Y
        RET

; z_pop -- pops 16-bit word from evaluation stack -> X
z_pop:
        PUSH Y
        LDW  Y,#Z_SP
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#2
        BCS  .sp2
        SUB  R1,#1
.sp2:   ST   [Y],R0
        ST   [Y+1],R1
        LDW  X,#Z_STACK_BASE
        ADDW X,R0
        LD   R1,[X]             ; high byte
        LD   R0,[X+1]           ; low byte
        MOV  XH,R1
        MOV  XL,R0
        POP  Y
        RET

; z_read_var -- reads variable R0 -> 16-bit word X
z_read_var:
        TST  R0
        BNE  .notstk
        JMP  z_pop
.notstk:CMP  R0,#16
        BHS  .isglob
        ; Local variable (1..15) -> current frame: Z_CALL_BASE + Z_FP + (R0 - 1) * 2
        SUB  R0,#1
        ADD  R0,R0              ; R0 = (var - 1) * 2
        LDW  X,#Z_FP
        LD   XL,[X]
        LD   XH,[X+1]
        ADDW X,#9               ; skip 9-byte call frame header
        ADDW X,R0
        ADDW X,#Z_CALL_BASE
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        RET

.isglob:; Global variable (16..255) -> Globals Base + (R0 - 16) * 2
        SUB  R0,#16
        CLR  R1
        SHL  R0
        ROL  R1                 ; R1:R0 = (var - 16) * 2
        LDW  X,#Z_GLOBS
        LD   XL,[X]
        LD   XH,[X+1]
        ADDW X,R0
        CLR  R1
        JMP  z_read_word

; z_write_var -- writes 16-bit word X to variable R0
z_write_var:
        TST  R0
        BNE  .wntstk
        JMP  z_push
.wntstk:CMP  R0,#16
        BHS  .wglob
        ; Local variable (1..15)
        SUB  R0,#1
        ADD  R0,R0
        PUSH X
        LDW  X,#Z_FP
        LD   XL,[X]
        LD   XH,[X+1]
        ADDW X,#9
        ADDW X,R0
        ADDW X,#Z_CALL_BASE
        POP  Y                  ; Y = value X
        ST   [X],YH
        ST   [X+1],YL
        RET

.wglob: ; Global variable (16..255)
        SUB  R0,#16
        CLR  R1
        SHL  R0
        ROL  R1
        PUSH X                  ; push value X
        LDW  X,#Z_GLOBS
        LD   XL,[X]
        LD   XH,[X+1]
        ADDW X,R0
        POP  Y                  ; Y = value
        MOV  R1,YH
        MOV  R0,YL
        JMP  z_write_word

; z_call -- routine call to packed address in Z_OP0
z_call:
        LDW  X,#Z_OP0
        LD   XL,[X]
        LD   XH,[X+1]
        ; Check if routine address is 0 (legal in Z-machine: returns FALSE immediately)
        MOV  R0,XL
        OR   R0,XH
        BNE  .do_call
        ; Address is 0: store FALSE (0) in result variable
        LDW  X,#Z_RESVAR
        LD   R0,[X]
        CLR  XL
        CLR  XH
        JMP  z_write_var

.do_call:
        ; Calculate byte address = Z_OP0 * 2
        CLR  R1
        SHL  XL
        ROL  XH
        ROL  R1                 ; R1:X = 24-bit routine byte address

        ; Fetch number of locals at routine address
        PUSH R1
        PUSH X
        CALL z_read_byte        ; R0 = local count (0..15)
        MOV  R2,R0              ; R2 = num_locals
        POP  X
        POP  R1
        ADDW X,#1
        BCC  .adv1
        ADD  R1,#1
.adv1:  ; Now R1:X points to default local values in story file

        ; Setup new call frame at Z_CALL_BASE + Z_FP
        LDW  Y,#Z_FP
        LD   YL,[Y]
        LD   YH,[Y+1]
        ADDW Y,#Z_CALL_BASE     ; Y = frame base

        ; Frame header:
        ; [Y+0..2] = Z_PC_L, Z_PC_M, Z_PC_H
        ; [Y+3..4] = caller Z_FP
        ; [Y+5]    = caller num_locals (R2)
        ; [Y+6]    = Z_RESVAR
        ; [Y+7..8] = Z_SP at call time
        LDW  X,#Z_PC_L
        LD   R0,[X]
        ST   [Y],R0
        LD   R0,[X+1]
        ST   [Y+1],R0
        LD   R0,[X+2]
        ST   [Y+2],R0

        LDW  X,#Z_FP
        LD   R0,[X]
        ST   [Y+3],R0
        LD   R0,[X+1]
        ST   [Y+4],R0

        ST   [Y+5],R2

        LDW  X,#Z_RESVAR
        LD   R0,[X]
        ST   [Y+6],R0

        LDW  X,#Z_SP
        LD   R0,[X]
        ST   [Y+7],R0
        LD   R0,[X+1]
        ST   [Y+8],R0

        ; Read default local values from story file into [Y+9..]
        ; R1:X = address of default values
        PUSH Y
        CLR  R3                 ; local index 0..14
.rd_loc:CMP  R3,R2
        BHS  .done_loc
        PUSH R1
        PUSH X
        PUSH R2
        PUSH R3
        CALL z_read_word        ; X = 16-bit default local value
        MOV  YH,XH
        MOV  YL,XL              ; Y = value
        POP  R3
        POP  R2
        POP  X
        POP  R1
        ADDW X,#2
        BCC  .adv2
        ADD  R1,#1
.adv2:  POP  X                  ; X = frame base
        PUSH X
        ADDW X,#9
        MOV  R0,R3
        ADD  R0,R0
        ADDW X,R0
        ST   [X],YH
        ST   [X+1],YL
        ADD  R3,#1
        BRA  .rd_loc

.done_loc:
        POP  Y                  ; Y = frame base
        ; Routine code starts at R1:X. Update Z_PC
        LDW  X,#Z_PC_L
        ST   [X],XL
        ST   [X+1],XH
        ST   [X+2],R1

        ; Overwrite passed arguments into local variables
        ; Z_OPCOUNT has number of operands (1..8)
        ; Arguments are Z_OP1..Z_OP(count-1)
        LDW  X,#Z_OPCOUNT
        LD   R0,[X]
        SUB  R0,#1              ; R0 = num_args passed
        BEQ  .no_args
        CLR  R3                 ; arg index 0..num_args-1
.arg_lp:CMP  R3,R0
        BHS  .no_args
        CMP  R3,R2              ; don not exceed local count
        BHS  .no_args
        ; Read Z_OP(R3+1)
        MOV  R1,R3
        ADD  R1,#1
        ADD  R1,R1              ; R1 = (R3+1) * 2
        LDW  X,#Z_OP0
        ADDW X,R1
        LD   XH,[X]
        LD   XL,[X+1]           ; X = arg value
        ; Write to frame local
        MOV  R1,R3
        ADD  R1,R1
        LDW  X,#Z_FP
        LD   XL,[X]
        LD   XH,[X+1]
        ADDW X,#Z_CALL_BASE+9
        ADDW X,R1
        LDW  Y,#Z_OP0
        ADDW Y,R1
        LD   R1,[Y]
        ST   [X],R1
        LD   R1,[Y+1]
        ST   [X+1],R1
        ADD  R3,#1
        BRA  .arg_lp

.no_args:
        ; Advance Z_FP to next frame slot: Z_FP = Z_FP + 39
        LDW  X,#Z_FP
        LD   R0,[X]
        LD   R1,[X+1]
        ADD  R0,#39
        BCC  .fp1
        ADD  R1,#1
.fp1:   ST   [X],R0
        ST   [X+1],R1
        RET

; z_ret -- returns value in X from routine
z_ret:
        ; Step back Z_FP: Z_FP = Z_FP - 39
        LDW  Y,#Z_FP
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#39
        BCS  .fp2
        SUB  R1,#1
.fp2:   ST   [Y],R0
        ST   [Y+1],R1

        ; Read frame header from Z_CALL_BASE + Z_FP
        LDW  Y,#Z_CALL_BASE
        ADDW Y,R0

        ; Restore Z_PC: [Y+0..2]
        LDW  X,#Z_PC_L
        LD   R0,[Y]
        ST   [X],R0
        LD   R0,[Y+1]
        ST   [X+1],R0
        LD   R0,[Y+2]
        ST   [X+2],R0

        ; Restore Z_SP: [Y+7..8]
        LDW  X,#Z_SP
        LD   R0,[Y+7]
        ST   [X],R0
        LD   R0,[Y+8]
        ST   [X+1],R0

        ; Read result destination variable: [Y+6]
        LD   R0,[Y+6]

        ; Restore caller Z_FP: [Y+3..4]
        LD   R1,[Y+3]
        LD   R2,[Y+4]
        LDW  Y,#Z_FP
        ST   [Y],R1
        ST   [Y+1],R2

        ; Write return value X to variable R0
        JMP  z_write_var
""")

# =====================================================================
# 4. sw/z3/z3_branch.asm
# =====================================================================
with open("sw/z3/z3_branch.asm", "w", encoding="utf-8") as f:
    f.write("""\
; ---------------------------------------------------------------------
; z3_branch.asm -- Z-Machine branch condition evaluation & jumps
; ---------------------------------------------------------------------

; z_eval_branch -- evaluates branch on condition R0 (0=FALSE, 1=TRUE)
z_eval_branch:
        PUSH R0                 ; save condition
        CALL z_fetch_pc_byte
        MOV  R1,R0              ; R1 = branch byte 1
        POP  R0                 ; R0 = condition

        ; Bit 7 of R1: 1 = branch on TRUE, 0 = branch on FALSE
        MOV  R2,R1
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2
        SHR  R2                 ; R2 = bit 7 (0 or 1)

        ; Condition match: (R0 == R2)
        CMP  R0,R2
        BEQ  .taken

        ; Not taken: skip second byte if 2-byte branch (bit 6 == 0)
        BTST R1,#6
        BNE  .notaken
        CALL z_fetch_pc_byte    ; skip byte 2
.notaken:
        RET

.taken: ; Branch IS taken!
        BTST R1,#6
        BEQ  .two_byte

        ; Single-byte branch: offset = R1 & $3F (unsigned 0..63)
        AND  R1,#$3F
        CLR  R2                 ; R2:R1 = offset
        BRA  .do_jump

.two_byte:
        ; Two-byte branch: offset = ((R1 & $3F) << 8) | byte2 (signed 14-bit)
        AND  R1,#$3F
        PUSH R1
        CALL z_fetch_pc_byte
        MOV  R2,R0              ; R2 = byte 2 (low byte)
        POP  R1                 ; R1 = high byte
        ; Check sign bit (bit 5 of original byte 1, now bit 5 of R1)
        BTST R1,#5
        BEQ  .pos14
        OR   R1,#$C0            ; sign-extend to 16 bits
.pos14: ; Offset in R1:R2 (R1=high, R2=low)
        ; Swap to R2:R1 (R2=high, R1=low) for jump helper
        PUSH R1
        MOV  R1,R2
        POP  R2

.do_jump:
        ; Check special offsets 0 (rfalse) and 1 (rtrue)
        TST  R2
        BNE  .rel_jump
        TST  R1
        BEQ  .do_rfalse
        CMP  R1,#1
        BEQ  .do_rtrue

.rel_jump:
        ; Target PC = Z_PC + offset - 2
        ; Offset in R2:R1 (R2=high, R1=low)
        SUB  R1,#2
        SBC  R2,#0

        LDW  X,#Z_PC_L
        LD   XL,[X]
        LD   XH,[X+1]
        LD   R0,[X+2]           ; R0:X = current 24-bit Z_PC

        ADD  XL,R1
        ADC  XH,R2
        ADC  R0,#0

        ST   [X],XL
        ST   [X+1],XH
        ST   [X+2],R0
        RET

.do_rfalse:
        CLR  XL
        CLR  XH
        JMP  z_ret

.do_rtrue:
        MOV  XL,#1
        CLR  XH
        JMP  z_ret
""")

print("Generated z3_equ.asm, z3_mem.asm, z3_stack.asm, z3_branch.asm")
