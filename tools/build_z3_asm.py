# Generator and builder for COOL8 Z-Machine Version 3 Interpreter
import os

os.makedirs("sw/z3", exist_ok=True)

# 1. z3_equ.asm
with open("sw/z3/z3_equ.asm", "w", encoding="utf-8") as f:
    f.write("""\
; ---------------------------------------------------------------------
; z3_equ.asm -- Constants, memory layout, and zero-page pointers for Z3
; ---------------------------------------------------------------------

Z_DYN_BASE      = $2800         ; Dynamic memory loaded into RAM ($2800..$67FF, 16 KB)
Z_STACK_BASE    = $6800         ; Z-Machine Evaluation Stack ($6800..$6BFF, 1 KB)
Z_CALL_BASE     = $6C00         ; Z-Machine Call Stack ($6C00..$73FF, 2 KB)
Z_TAGS_BASE     = $7400         ; 16 Cache Page Tags (16 * 3 = 48 bytes)
Z_CACHE_BASE    = $7800         ; 16 Pages * 512 Bytes = 8 KB ($7800..$97FF)

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
Z_CALL_DEPTH    = $0054         ; Call Depth (0..32)         ; Call Frame Pointer (16-bit offset from Z_CALL_BASE)

Z_FLS_L         = $0055         ; Flash Base Offset Low
Z_FLS_M         = $0056         ; Flash Base Offset Middle
Z_FLS_H         = $0057         ; Flash Base Offset High

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

; Text output buffer for word wrapping in RAM ($7440)
Z_WRAP_LEN      = $00A4         ; Current word length in wrap buffer
Z_WRAP_BUF      = $7440         ; 64 bytes word wrap buffer in RAM

; Scratch registers for routines
Z_TMP0          = $00A6
Z_TMP1          = $00A8
Z_TMP2          = $00AA
Z_TMP3          = $00AC

Z_ENC_W1        = $00B6         ; 16-bit encoded Z-word 1
Z_ENC_W2        = $00B8         ; 16-bit encoded Z-word 2

FLS_CTRL        = $FF8C         ; Flash streaming control register
""")

# 2. z3_mem.asm
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
""")

# 3. z3_stack.asm
with open("sw/z3/z3_stack.asm", "w", encoding="utf-8") as f:
    f.write("""\
; ---------------------------------------------------------------------
; z3_stack.asm -- Z-Machine stack, call frames, and variable access
; ---------------------------------------------------------------------

; z_push -- pushes 16-bit word X to evaluation stack
z_push:
        PUSHW Y
        LDW  Y,#Z_SP
        LD   R0,[Y]
        LD   R1,[Y+1]
        PUSHW X
        LDW  X,#Z_STACK_BASE
        ADDW X,R0
        POPW Y                  ; Y = value X
        MOV  R2,YH
        ST   [X],R2
        MOV  R2,YL
        ST   [X+1],R2
        ADD  R0,#2
        ADC  R1,#0
        LDW  X,#Z_SP
        ST   [X],R0
        ST   [X+1],R1
        POPW Y
        RET

; z_pop -- pops 16-bit word from evaluation stack -> X
z_pop:
        PUSHW Y
        LDW  Y,#Z_SP
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#2
        SBC  R1,#0
        ST   [Y],R0
        ST   [Y+1],R1
        LDW  X,#Z_STACK_BASE
        ADDW X,R0
        LD   R1,[X]             ; high byte
        LD   R0,[X+1]           ; low byte
        MOV  XH,R1
        MOV  XL,R0
        POPW Y
        RET

; z_read_var -- reads variable R0 -> 16-bit word X
z_read_var:
        TST  R0
        BNE  .notstk
        JMP  z_pop
.notstk:CMP  R0,#16
        BHS  .isglob
        ; Local variable (1..15) -> current frame: Z_CALL_BASE + Z_FP + 9 + (R0 - 1) * 2
        SUB  R0,#1
        ADD  R0,R0
        ADD  R0,#9              ; R0 = 9 + (var - 1) * 2
        LDW  Y,#Z_FP
        LD   R1,[Y]
        LD   R2,[Y+1]
        ADD  R1,R0
        ADC  R2,#0
        MOV  XL,R1
        MOV  XH,R2
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
        LDW  Y,#Z_GLOBS
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XL,R0
        MOV  XH,R1
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
        PUSHW X
        SUB  R0,#1
        ADD  R0,R0
        ADD  R0,#9
        LDW  Y,#Z_FP
        LD   R1,[Y]
        LD   R2,[Y+1]
        ADD  R1,R0
        ADC  R2,#0
        MOV  XL,R1
        MOV  XH,R2
        ADDW X,#Z_CALL_BASE
        POPW Y                  ; Y = value X
        MOV  R1,YH
        ST   [X],R1
        MOV  R1,YL
        ST   [X+1],R1
        RET

.wglob: ; Global variable (16..255)
        PUSHW X
        SUB  R0,#16
        CLR  R1
        SHL  R0
        ROL  R1
        LDW  Y,#Z_GLOBS
        LD   R2,[Y]
        LD   R3,[Y+1]
        ADD  R0,R2
        ADC  R1,R3
        MOV  XL,R0
        MOV  XH,R1
        POPW Y                  ; Y = value
        MOV  R1,YH
        MOV  R0,YL
        JMP  z_write_word

; z_call -- routine call to packed address in Z_OP0
z_call:
        LDW  Y,#Z_OP0
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XH,R0
        MOV  XL,R1
        OR   R0,R1
        BNE  .do_call
        ; Address is 0: store FALSE (0) in result variable
        LDW  X,#Z_RESVAR
        LD   R0,[X]
        LDW  X,#0
        JMP  z_write_var

.do_call:
        ; Calculate byte address = Z_OP0 * 2
        CLR  R0
        MOV  R3,XL
        MOV  R2,XH
        SHL  R3
        ROL  R2
        ROL  R0                 ; R0:R2:R3 = 24-bit routine byte address
        MOV  XL,R3
        MOV  XH,R2
        MOV  R1,R0

        ; Fetch number of locals at routine address
        PUSH R1
        PUSHW X
        CALL z_read_byte        ; R0 = local count (0..15)
        MOV  R2,R0              ; R2 = num_locals
        POPW X
        POP  R1
        INCW X
        BNE  .adv1
        ADD  R1,#1
.adv1:  ; R1:X = story address of local defaults ($572D), R2 = num_locals (3)
        PUSH R1
        PUSHW X
        PUSH R2

        ; Calculate new frame base Y = Z_CALL_BASE + new_FP
        LDW  Y,#Z_CALL_DEPTH
        LD   R0,[Y]
        TST  R0
        BEQ  .fbase0
        LDW  Y,#Z_FP
        LD   R0,[Y]
        LD   R3,[Y+1]
        ADD  R0,#39
        ADC  R3,#0
        BRA  .fbaseset
.fbase0:CLR  R0
        CLR  R3
.fbaseset:
        MOV  YL,R0
        MOV  YH,R3
        ADDW Y,#Z_CALL_BASE     ; Y = new frame base

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

        POP  R0
        PUSH R0
        ST   [Y+5],R0

        LDW  X,#Z_RESVAR
        LD   R0,[X]
        ST   [Y+6],R0

        LDW  X,#Z_SP
        LD   R0,[X]
        ST   [Y+7],R0
        LD   R0,[X+1]
        ST   [Y+8],R0

        ; Set Z_FP = new_FP
        LDW  X,#Z_CALL_DEPTH
        LD   R0,[X]
        TST  R0
        BEQ  .fpu0
        LDW  X,#Z_FP
        LD   R0,[X]
        LD   R3,[X+1]
        ADD  R0,#39
        ADC  R3,#0
        ST   [X],R0
        ST   [X+1],R3
        BRA  .fpudone
.fpu0:  LDW  X,#Z_FP
        CLR  R0
        ST   [X],R0
        ST   [X+1],R0
.fpudone:
        LDW  X,#Z_CALL_DEPTH
        LD   R0,[X]
        ADD  R0,#1
        ST   [X],R0

        POP  R2                 ; R2 = num_locals
        POPW X                  ; X = story address of local defaults ($572D)
        POP  R1                 ; R1 = story high byte

        ; Read default local values from story file into [Y+9..]
        ; Y = frame base, R1:X = story address of local defaults
        CLR  R3                 ; local index 0..14
.rd_loc:CMP  R3,R2
        BHS  .done_loc
        PUSH R1
        PUSHW X
        PUSH R2
        PUSH R3
        PUSHW Y
        CALL z_read_word        ; X = 16-bit default local value
        MOVW Y,X                ; Y = value
        POPW X                  ; X = frame base
        POP  R3
        POP  R2

        ; Write local value to frame: X + 9 + R3*2
        PUSHW X
        ADDW X,#9
        MOV  R0,R3
        ADD  R0,R0
        ADDW X,R0
        MOV  R0,YH
        ST   [X],R0
        MOV  R0,YL
        ST   [X+1],R0
        POPW Y                  ; Y = frame base

        POPW X                  ; restore story pointer X
        POP  R1                 ; restore story pointer R1
        INCW X
        INCW X
        BNE  .adv2
        ADD  R1,#1
.adv2:  ADD  R3,#1
        BRA  .rd_loc

.done_loc:
        ; Routine code starts at R1:X. Update Z_PC
        LDW  Y,#Z_PC_L
        MOV  R0,XL
        ST   [Y],R0
        MOV  R0,XH
        ST   [Y+1],R0
        ST   [Y+2],R1

        ; Overwrite passed arguments into local variables
        LDW  X,#Z_OPCOUNT
        LD   R0,[X]
        SUB  R0,#1              ; R0 = num_args passed
        BEQ  .no_args
        CLR  R3                 ; arg index 0..num_args-1
.arg_lp:CMP  R3,R0
        BHS  .no_args
        CMP  R3,R2              ; do not exceed local count
        BHS  .no_args
        ; Read Z_OP(R3+1)
        MOV  R1,R3
        ADD  R1,#1
        ADD  R1,R1              ; R1 = (R3+1) * 2
        LDW  X,#Z_OP0
        ADDW X,R1
        LD   R1,[X]             ; high byte
        LD   R0,[X+1]           ; low byte
        ; Write to frame local
        PUSH R0                 ; save low byte
        PUSH R2                 ; save num_locals
        PUSH R3                 ; save arg index
        MOV  R0,R3
        ADD  R0,R0
        LDW  Y,#Z_FP
        LD   R2,[Y]
        LD   R3,[Y+1]
        MOV  XL,R2
        MOV  XH,R3
        ADDW X,#Z_CALL_BASE+9
        ADDW X,R0
        ST   [X],R1             ; store high byte
        POP  R3                 ; restore arg index
        POP  R2                 ; restore num_locals
        POP  R0                 ; restore low byte
        ST   [X+1],R0           ; store low byte
        LDW  X,#Z_OPCOUNT
        LD   R0,[X]
        SUB  R0,#1              ; restore R0 = num_args passed
        ADD  R3,#1
        BRA  .arg_lp

.no_args:
        RET

; z_ret -- returns value in X from routine
z_ret:
        LDW  Y,#Z_CALL_DEPTH
        LD   R0,[Y]
        TST  R0
        BNE  .has_caller
        ; Top-level return -> finish program
        LDW  X,#Z_QUIT
        MOV  R0,#1
        ST   [X],R0
        RET

.has_caller:
        PUSHW X                 ; Preserve return value X
        SUB  R0,#1
        ST   [Y],R0

        ; Read frame header from Z_CALL_BASE + Z_FP
        LDW  Y,#Z_FP
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  YL,R0
        MOV  YH,R1
        ADDW Y,#Z_CALL_BASE     ; Y = current frame base

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

        POPW X                  ; Restore return value X

        ; Write return value X to variable R0
        JMP  z_write_var
""")

# 4. z3_branch.asm
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
        BTST R1,#$40
        BNE  .notaken
        CALL z_fetch_pc_byte    ; skip byte 2
.notaken:
        RET

.taken: ; Branch IS taken!
        BTST R1,#$40
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
        BTST R1,#$20
        BEQ  .pos14
        OR   R1,#$C0            ; sign-extend to 16 bits
.pos14: ; Offset in R1:R2 (R1=high, R2=low)
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
        SUB  R1,#2
        SBC  R2,#0

        ; Sign extend R2 into R3 for 24-bit arithmetic
        MOV  R3,R2
        BTST R3,#$80
        BEQ  .pos_pc
        MOV  R3,#$FF
        BRA  .add_pc
.pos_pc:CLR  R3
.add_pc:
        LDW  Y,#Z_PC_L
        LD   R0,[Y]             ; low
        ADD  R0,R1
        ST   [Y],R0
        LD   R0,[Y+1]           ; mid
        ADC  R0,R2
        ST   [Y+1],R0
        LD   R0,[Y+2]           ; high
        ADC  R0,R3
        ST   [Y+2],R0
        RET

.do_rfalse:
        LDW  X,#0
        JMP  z_ret

.do_rtrue:
        LDW  X,#1
        JMP  z_ret
""")

# 5. z3_text.asm
with open("sw/z3/z3_text.asm", "w", encoding="utf-8") as f:
    f.write("""\
; ---------------------------------------------------------------------
; z3_text.asm -- Z-Character text decompression, abbreviations, & wrapping
; ---------------------------------------------------------------------

z_a2_table:
        .byte $30, $31, $32, $33, $34, $35, $36, $37, $38, $39 ; 0123456789
        .byte $2E, $2C, $21, $3F, $5F, $23, $27, $22, $2F, $5C ; .,!?_#'"/\\
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
""")

# 6. z3_obj.asm
with open("sw/z3/z3_obj.asm", "w", encoding="utf-8") as f:
    f.write("""\
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
""")

# 7. z3_dict.asm
with open("sw/z3/z3_dict.asm", "w", encoding="utf-8") as f:
    f.write("""\
; ---------------------------------------------------------------------
; z3_dict.asm -- Dictionary binary search, string encoding, & sread lexer
; ---------------------------------------------------------------------

; z_encode_word -- encodes 6 ASCII characters at X into (Z_ENC_W1, Z_ENC_W2)
z_encode_word:
        LDW  Y,#$00BC
        CLR  R3                 ; char count 0..5
.enc_c: LD   R0,[X+]
        TST  R0
        BEQ  .pad_c
        CMP  R0,#$20
        BEQ  .pad_c

        CMP  R0,#$61            ; 'a'
        BLO  .chk_up
        CMP  R0,#$7B            ; 'z'+1
        BHS  .chk_punc
        SUB  R0,#$5B            ; 'a' - 6
        BRA  .put_5b

.chk_up:CMP  R0,#$41            ; 'A'
        BLO  .chk_punc
        CMP  R0,#$5B            ; 'Z'+1
        BHS  .chk_punc
        SUB  R0,#$3B            ; 'A' - 6
        BRA  .put_5b

.chk_punc:
        MOV  R0,#5
        BRA  .put_5b

.pad_c: DECW X
        MOV  R0,#5

.put_5b:ST   [Y+],R0
        ADD  R3,#1
        CMP  R3,#6
        BLO  .enc_c

        ; Pack into Word 1: (c0 << 10) | (c1 << 5) | c2
        LDW  Y,#$00BC
        LD   R0,[Y]             ; c0
        SHL  R0
        SHL  R0
        LD   R1,[Y+1]           ; c1
        MOV  R2,R1
        SHR  R2
        SHR  R2
        SHR  R2
        OR   R0,R2              ; R0 = high byte of Word 1
        MOV  R2,R1
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2
        LD   R1,[Y+2]           ; c2
        OR   R2,R1              ; R2 = low byte of Word 1
        LDW  X,#Z_ENC_W1
        ST   [X],R0
        ST   [X+1],R2

        ; Pack into Word 2: (1 << 15) | (c3 << 10) | (c4 << 5) | c5
        LD   R0,[Y+3]           ; c3
        SHL  R0
        SHL  R0
        OR   R0,#$80            ; bit 15 = 1 (terminal word)
        LD   R1,[Y+4]           ; c4
        MOV  R2,R1
        SHR  R2
        SHR  R2
        SHR  R2
        OR   R0,R2              ; R0 = high byte of Word 2
        MOV  R2,R1
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2
        SHL  R2
        LD   R1,[Y+5]           ; c5
        OR   R2,R1              ; R2 = low byte of Word 2
        LDW  X,#Z_ENC_W2
        ST   [X],R0
        ST   [X+1],R2
        RET

; z_find_dict_word -- binary searches dictionary for (Z_ENC_W1, Z_ENC_W2)
z_find_dict_word:
        LDW  Y,#Z_DICT
        LD   R0,[Y]
        LD   R1,[Y+1]
        MOV  XL,R0
        MOV  XH,R1
        CLR  R1
        PUSHW X
        CALL z_read_byte        ; R0 = num_separators (N)
        POPW X
        ADD  R0,#1
        ADDW X,R0

        ; Read entry length E
        PUSHW X
        CLR  R1
        CALL z_read_byte        ; R0 = entry length E
        MOV  R2,R0
        POPW X
        INCW X

        ; Read entry count C (16-bit word)
        PUSH R2
        PUSHW X
        CLR  R1
        CALL z_read_word        ; X = entry count C
        POPW Y
        POP  R2                 ; R2 = E
        INCW Y
        INCW Y                  ; Y = dictionary table address

        MOV  R0,XL
        MOV  R1,XH
        SUB  R0,#1
        SBC  R1,#0
        MOV  R3,R2

        LDW  X,#$00C2
        CLR  R2
        ST   [X],R2             ; low_L = 0
        ST   [X+1],R2           ; low_H = 0
        ST   [X+2],R0           ; high_L
        ST   [X+3],R1           ; high_H
        ST   [X+4],R3           ; entry_len
        MOV  R2,YL
        ST   [X+5],R2           ; table_base_L
        MOV  R2,YH
        ST   [X+6],R2           ; table_base_H

.bs_lp:
        LDW  X,#$00C2
        LD   R0,[X]             ; low_L
        LD   R1,[X+1]           ; low_H
        LD   R2,[X+2]           ; high_L
        LD   R3,[X+3]           ; high_H

        ; Check if high < low (i.e. high - low < 0) -> not in dictionary
        SUB  R2,R0
        SBC  R3,R1
        BLO  .not_in_dict

        ; mid = (low + high) / 2
        LD   R0,[X]
        LD   R2,[X+2]
        ADD  R0,R2
        LD   R1,[X+1]
        LD   R3,[X+3]
        ADC  R1,R3
        SHR  R1
        ROR  R0                 ; R1:R0 = mid (16-bit)

        ; Save mid in Z_TMP2
        LDW  Y,#Z_TMP2
        ST   [Y],R0             ; mid_L
        ST   [Y+1],R1           ; mid_H

        ; Calculate entry_offset = mid * entry_len (16-bit)
        LDW  Y,#$00C2
        LD   R2,[Y+4]           ; R2 = entry_len
        MUL  R0,R2              ; X = mid_L * entry_len
        TST  R1
        BEQ  .no_mid_hi
        PUSH R2
        MUL  R1,R2              ; X = mid_H * entry_len
        MOV  R0,XL
        POP  R2
        LDW  Y,#Z_TMP2
        LD   R1,[Y]             ; mid_L
        MUL  R1,R2              ; X = mid_L * entry_len
        MOV  R1,XH
        ADD  R1,R0
        MOV  XH,R1              ; add high contribution
.no_mid_hi:

        ; Add table base to X
        LDW  Y,#$00C2
        LD   R0,[Y+5]
        LD   R1,[Y+6]
        ADDW X,R0
        MOV  R0,XH
        ADD  R0,R1
        MOV  XH,R0              ; X = exact 16-bit entry story address!

        ; Read entry word 1
        PUSHW X
        CLR  R1
        CALL z_read_word        ; X = entry word 1
        LDW  Y,#Z_ENC_W1
        LD   R1,[Y]
        LD   R0,[Y+1]           ; R1:R0 = Target Word 1 (high:low)
        MOV  R2,XH
        CMP  R2,R1
        BLO  .w1_lo
        BHI  .w1_hi
        MOV  R2,XL
        CMP  R2,R0
        BLO  .w1_lo
        BHI  .w1_hi

        ; Word 1 matched! Check Word 2
        POPW X
        PUSHW X
        INCW X
        INCW X
        CLR  R1
        CALL z_read_word        ; X = entry word 2
        LDW  Y,#Z_ENC_W2
        LD   R1,[Y]
        LD   R0,[Y+1]           ; R1:R0 = Target Word 2 (high:low)
        MOV  R2,XH
        CMP  R2,R1
        BLO  .w1_lo
        BHI  .w1_hi
        MOV  R2,XL
        CMP  R2,R0
        BLO  .w1_lo
        BHI  .w1_hi

        ; Exactly matched! Return entry address in X
        POPW X
        RET

.w1_lo: ; Entry < Target -> low = mid + 1
        POPW X
        LDW  Y,#Z_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        ADD  R0,#1
        ADC  R1,#0
        LDW  X,#$00C2
        ST   [X],R0
        ST   [X+1],R1
        BRA  .bs_lp

.w1_hi: ; Entry > Target -> high = mid - 1
        POPW X
        LDW  Y,#Z_TMP2
        LD   R0,[Y]
        LD   R1,[Y+1]
        SUB  R0,#1
        SBC  R1,#0
        LDW  X,#$00C2
        ST   [X+2],R0
        ST   [X+3],R1
        BRA  .bs_lp

.not_in_dict:
        LDW  X,#0
        RET

; z_sread -- implements sread text_buf, parse_buf
z_sread:
        CALL z_show_status
        CALL z_flush_wrap

        LDW  Y,#Z_OP0
        LD   R1,[Y]
        LD   R0,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        ADDW X,#Z_DYN_BASE
        LD   R3,[X]             ; max input length
        INCW X

        CLR  R2                 ; current length
.in_lp: CALL in_key
        TST  R0
        BEQ  .in_lp

        CMP  R0,#$0D
        BEQ  .in_done
        CMP  R0,#$0A
        BEQ  .in_done

        CMP  R0,#$08
        BEQ  .in_bs
        CMP  R0,#$7F
        BEQ  .in_bs
        CMP  R0,#$86
        BEQ  .in_bs

        CMP  R2,R3
        BHS  .in_lp

        CMP  R0,#$41            ; 'A'
        BLO  .st_c
        CMP  R0,#$5B            ; 'Z'+1
        BHS  .st_c
        ADD  R0,#$20

.st_c:  ST   [X+],R0
        PUSH R0
        PUSH R2
        PUSH R3
        PUSHW X
        CALL con_emit
        POPW X
        POP  R3
        POP  R2
        POP  R0
        ADD  R2,#1
        BRA  .in_lp

.in_bs: TST  R2
        BEQ  .in_lp
        SUB  R2,#1
        DECW X
        LD   R0,[CCX]
        TST  R0
        BEQ  .in_lp
        SUB  R0,#1
        ST   [CCX],R0
        CALL con_setrow
        PUSH R2
        PUSH R3
        PUSHW X
        LD   R0,[CCY]
        LD   R1,[CCX]
        MOV  R2,#$20
        LD   R3,[CATTR]
        CALL con_put
        CALL con_cursor
        POPW X
        POP  R3
        POP  R2
        BRA  .in_lp

.in_done:
        CLR  R0
        ST   [X],R0
        CALL con_nl

        ; X = text buffer at start of string ($2000 + text_buf + 1)
        LDW  Y,#Z_OP0
        LD   R1,[Y]
        LD   R0,[Y+1]
        MOV  XH,R1
        MOV  XL,R0
        ADDW X,#Z_DYN_BASE+1

        ; Read max tokens from parse buffer
        LDW  Y,#Z_OP1
        LD   R1,[Y]
        LD   R0,[Y+1]
        MOV  YH,R1
        MOV  YL,R0
        ADDW Y,#Z_DYN_BASE
        LD   R0,[Y]
        LDW  Y,#Z_TMP3
        ST   [Y],R0             ; Z_TMP3 = max_tokens
        CLR  R2                 ; R2 = token count (0)

.tok_lp:LD   R0,[X]
        TST  R0
        BEQ  .tok_done
        CMP  R0,#$20
        BNE  .tok_start
        INCW X
        BRA  .tok_lp

.tok_start:
        PUSHW X                 ; [1] word_start_ptr
        PUSH R2                 ; [2] token count
        CALL z_encode_word
        CALL z_find_dict_word   ; returns dictionary address in X ($0000 if not found)
        LDW  Y,#Z_TMP0
        MOV  R0,XL
        ST   [Y],R0
        MOV  R0,XH
        ST   [Y+1],R0           ; Z_TMP0 = XL, Z_TMP0+1 = XH
        POP  R2
        POPW X                  ; restore word_start_ptr

        ; Measure word length in characters
        PUSHW X
        CLR  R0
.len_lp:LD   R1,[X+]
        TST  R1
        BEQ  .len_done
        CMP  R1,#$20
        BEQ  .len_done
        ADD  R0,#1
        BRA  .len_lp
.len_done:
        LDW  Y,#Z_TMP2
        ST   [Y],R0             ; Z_TMP2 = word length
        POPW Y                  ; Y = word_start_ptr
        PUSHW Y

        ; Calculate 1-based offset in text buffer: (word_start_ptr - text_buf_base)
        LDW  X,#Z_OP0
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  XH,R1
        MOV  XL,R0
        ADDW X,#Z_DYN_BASE
        MOV  R0,YL
        MOV  R1,XL
        SUB  R0,R1              ; R0 = token start offset (1-indexed)

        ; Write parse buffer entry at parse_buf + 2 + token_index * 4
        PUSH R2
        MOV  R1,R2
        SHL  R1
        SHL  R1                 ; R1 = token_index * 4
        LDW  X,#Z_OP1
        LD   R2,[X]
        LD   R3,[X+1]
        MOV  XH,R2
        MOV  XL,R3
        ADDW X,#Z_DYN_BASE+2
        ADDW X,R1
        LDW  Y,#Z_TMP0
        LD   R1,[Y]
        LD   R2,[Y+1]
        ST   [X],R2             ; dict addr high (big-endian)
        ST   [X+1],R1           ; dict addr low
        LDW  Y,#Z_TMP2
        LD   R1,[Y]             ; word length
        ST   [X+2],R1
        ST   [X+3],R0           ; word offset
        POP  R2

        ADD  R2,#1              ; tokens++
        POPW X                  ; restore word_start_ptr
        LDW  Y,#Z_TMP2
        LD   R0,[Y]
        ADDW X,R0               ; advance X past word in text buffer
        LDW  Y,#Z_TMP3
        LD   R0,[Y]             ; R0 = max_tokens
        CMP  R2,R0
        BLO  .tok_lp

.tok_done:
        LDW  X,#Z_OP1
        LD   R1,[X]
        LD   R0,[X+1]
        MOV  YH,R1
        MOV  YL,R0
        ADDW Y,#Z_DYN_BASE+1
        ST   [Y],R2             ; store final num_tokens in parse_buf[1]
        RET
""")

# 8. z3_io.asm
with open("sw/z3/z3_io.asm", "w", encoding="utf-8") as f:
    f.write("""\
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
""")

# 9. z3_opcodes.asm
with open("sw/z3/z3_opcodes.asm", "w", encoding="utf-8") as f:
    f.write("""\
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
        CLR  R0
        JMP  z_eval_branch

z_op_restore:
        CLR  R0
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
""")

# 10. z3_main.asm
with open("sw/z3/z3_main.asm", "w", encoding="utf-8") as f:
    f.write("""\
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
""")

# 11. sw/z3/z3.asm
with open("sw/z3/z3.asm", "w", encoding="utf-8") as f:
    f.write("""\
; ---------------------------------------------------------------------
; sw/z3/z3.asm -- COOL8 Native Z-Machine Version 3 Interpreter
; ---------------------------------------------------------------------

        .org $0200
        JMP  main

        .include "../lowram.asm"
        .include "../console.asm"
        .include "../input.asm"
        .include "../kbd.asm"
        .include "../keymap.asm"
        .include "../kdown.asm"
        .include "z3_equ.asm"
        .include "z3_mem.asm"
        .include "z3_stack.asm"
        .include "z3_branch.asm"
        .include "z3_text.asm"
        .include "z3_obj.asm"
        .include "z3_dict.asm"
        .include "z3_io.asm"
        .include "z3_opcodes.asm"
        .include "z3_main.asm"

inmi:   PUSH R0
        MOV  R0,#1
        ST   [ibreak],R0
        POP  R0
        RETI

iisr:   PUSH R0
        PUSH R1
        PUSHW X
        MOV  R0,#$22            ; acknowledge vblank, keep it enabled
        ST   [VID_IRQ],R0
        LD   R0,[frames]
        ADD  R0,#1
        ST   [frames],R0
        LD   R0,[frames+1]
        ADC  R0,#0
        ST   [frames+1],R0
.more:  LD   R0,[UART_STAT]     ; UART data from m.type()
        BTST R0,#$01
        BEQ  .kbd
        LD   R0,[UART_DATA]
        CALL irpush
        BRA  .more

.kbd:   LD   R0,[KBD_STAT]      ; PS/2 Keyboard data from m.key()
        BTST R0,#$01
        BEQ  .done
        LD   R0,[KBD_DATA]
        CALL scancode
        TST  R0
        BEQ  .kbd
        CALL irpush
        BRA  .kbd

.done:  POPW X
        POP  R1
        POP  R0
        RETI

irpush: LD   R1,[irhead]
        LDW  X,#irring
        ADDW X,R1
        ST   [X],R0
        ADD  R1,#1
        AND  R1,#15
        ST   [irhead],R1
        RET

main:
        DI
        MOV  R0,#<iisr
        ST   [$FFFC],R0
        MOV  R0,#>iisr
        ST   [$FFFD],R0
        MOV  R0,#<inmi
        ST   [$FFFA],R0
        MOV  R0,#>inmi
        ST   [$FFFB],R0
        MOV  R0,#$20            ; enable vblank interrupt
        ST   [VID_IRQ],R0
        MOV  R0,#$11            ; clear and enable keyboard FIFO
        ST   [KBD_CTRL],R0
        MOV  R0,#$10
        ST   [KBD_CTRL],R0

        CLR  R0
        ST   [irhead],R0
        ST   [irtail],R0

        EI                      ; Enable interrupts!

        CALL z_find_story_flash
        CALL con_init

        ; Apply game custom colors and border
        LD   R0,[z_color_attr]
        ST   [CATTR],R0
        LD   R0,[z_color_border]
        ST   [VID_BORDER],R0
        CALL con_cls

        JMP  z_init_restart

z_story_tag:
        .asciz "HHGG0"
z_color_attr:
        .byte $1F               ; default: $1F (Amiga white on blue)
z_color_status:
        .byte $F1               ; default: $F1 (Amiga inverted status line)
z_color_border:
        .byte $01               ; default: $01 (Amiga blue border)

z_find_story_flash:
        ; First check if story is at $000000 (standalone flash mode)
        ; Standalone has Z-machine version 3 at byte 0
        CLR  R0
        ST   [FLS_CTRL],R0
        ST   [FLS_ADDR_L],R0
        ST   [FLS_ADDR_M],R0
        ST   [FLS_ADDR_H],R0
        MOV  R0,#1
        ST   [FLS_CTRL],R0
        LD   R0,[FLS_DATA]
        CMP  R0,#3              ; Z-machine V3 header byte 0 is 3
        BNE  .scan_vols
        ; Standalone mode! Z_FLS = $000000
        CLR  R0
        ST   [FLS_CTRL],R0
        LDW  X,#Z_FLS_L
        ST   [X],R0
        ST   [X+1],R0
        ST   [X+2],R0
        RET

.scan_vols:
        ; Scan drives 14 ($72) and 13 ($6B)
        MOV  R3,#$72            ; Start with Drive 14 (ADVENTUR)
.try_vol:
        CLR  R0
        ST   [FLS_CTRL],R0
        ST   [FLS_ADDR_L],R0
        ST   [FLS_ADDR_M],R0
        ST   [FLS_ADDR_H],R3
        MOV  R0,#1
        ST   [FLS_CTRL],R0

        ; Scan 256 directory entries of 16 bytes
        LDW  X,#0               ; entry count 0..255
.dir_lp:
        ; Read and compare 5 bytes against z_story_tag
        LD   R0,[FLS_DATA]      ; Byte 0
        LDW  Y,#z_story_tag
        LD   R1,[Y]
        CMP  R0,R1
        BNE  .skip_ent_15
        LD   R0,[FLS_DATA]      ; Byte 1
        LD   R1,[Y+1]
        CMP  R0,R1
        BNE  .skip_ent_14
        LD   R0,[FLS_DATA]      ; Byte 2
        LD   R1,[Y+2]
        CMP  R0,R1
        BNE  .skip_ent_13
        LD   R0,[FLS_DATA]      ; Byte 3
        LD   R1,[Y+3]
        CMP  R0,R1
        BNE  .skip_ent_12
        LD   R0,[FLS_DATA]      ; Byte 4
        LD   R1,[Y+4]
        CMP  R0,R1
        BEQ  .found_match

.skip_ent_11:
        MOV  R0,#11
        BRA  .sk_lp
.skip_ent_12:
        MOV  R0,#12
        BRA  .sk_lp
.skip_ent_13:
        MOV  R0,#13
        BRA  .sk_lp
.skip_ent_14:
        MOV  R0,#14
        BRA  .sk_lp
.skip_ent_15:
        MOV  R0,#15
.sk_lp: LD   R1,[FLS_DATA]
        SUB  R0,#1
        BNE  .sk_lp
        INCW X
        MOV  R0,XL
        TST  R0
        BNE  .dir_lp

        ; If not found on Drive 14, try Drive 13 ($6B)
        CMP  R3,#$72
        BNE  .found_0
        MOV  R3,#$6B
        BRA  .try_vol

.found_match:
        ; Skip 7 more bytes of name + status (bytes 5..10 name, byte 11 status)
        MOV  R0,#7
.sk7:   LD   R1,[FLS_DATA]
        SUB  R0,#1
        BNE  .sk7

        ; Bytes 12..13: page offset (low, high) from volume base
        LD   R1,[FLS_DATA]      ; page low
        LD   R2,[FLS_DATA]      ; page high

        CLR  R0
        ST   [FLS_CTRL],R0      ; close read stream

        ; Flash address = (R3 << 16) + (page << 8)
        LDW  X,#Z_FLS_L
        ST   [X],R0             ; low byte = 0
        ST   [X+1],R1           ; mid byte = page low
        ADD  R2,R3              ; high byte = vol high + page high
        ST   [X+2],R2
        RET

.found_0:
        CLR  R0
        ST   [FLS_CTRL],R0
        LDW  X,#Z_FLS_L
        ST   [X],R0
        ST   [X+1],R0
        ST   [X+2],R0
        RET
""")

print("Generated all sw/z3 files.")
