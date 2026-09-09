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
