; ---------------------------------------------------------------------
; sw/pascal/pm_equ.asm -- P-Machine Zero Page Registers & Definitions
; ---------------------------------------------------------------------

PM_SP           = $0040         ; P-Machine Evaluation Stack Pointer (16-bit)
PM_MP           = $0042         ; Mark Pointer / Current Activation Frame (16-bit)
PM_BP           = $0044         ; Base Pointer / Global Variable Frame (16-bit)
PM_IPC          = $0046         ; Instruction Pointer Byte Counter (16-bit)
PM_SEGB         = $0048         ; Current Segment Base Address (16-bit)
PM_SEG          = $004A         ; Current Segment Dictionary Pointer (16-bit)
PM_JTAB         = $004C         ; Current Procedure Jump Table Pointer (16-bit)
PM_SYSCOM       = $004E         ; Pointer to System Communication Record (16-bit)
PM_NP           = $0050         ; Heap Pointer (Dynamic Memory Allocator) (16-bit)
PM_KP           = $0052         ; Program Space Top Pointer (16-bit)
PM_IORSLT       = $0054         ; I/O Result Status (16-bit)
PM_EVAL0        = $0056         ; Eval temporary 0
PM_TMP0         = $0058         ; Scratchpad 0 (4 bytes)
PM_TMP1         = $005A         ; Scratchpad 1
PM_TMP2         = $005C         ; Scratchpad 2
PM_TMP3         = $005E         ; Scratchpad 3
PM_TMP4         = $0062         ; Scratchpad 4 (16-bit)
PM_OP           = $0060         ; Current executing P-Code opcode (8-bit)
PM_QUIT         = $0061         ; Exit flag (8-bit)
PM_TERM_STATE   = $0064         ; Terminal parser state (8-bit)
PM_TERM_X       = $0065         ; Terminal GOTOXY X coordinate (8-bit)
PM_BASE_MP      = $0066         ; Root Segment 0 Base MP (16-bit)
PM_STR_BUF1     = $0068         ; Scratch buffer 1 for string comparisons (4 bytes)
PM_STR_BUF2     = $006C         ; Scratch buffer 2 for string comparisons (4 bytes)
PM_SET_K        = $0070         ; Current word index in set operations (16-bit)
PM_SET_W1       = $0072         ; Word1 temp in set operations (16-bit)
PM_SET_OP       = $0074         ; Operation selector in set operations (8-bit)
PM_VCACHE_CNT   = $0076         ; Number of cached VRAM disk blocks (8-bit)
PM_VCACHE_BLK   = $0078         ; Array of cached block numbers (32 words = 64 bytes)

; Mark Stack Frame Layout (offsets relative to MP):
MS_STAT         = 0             ; Static link pointer (parent lexical frame)
MS_DYN          = 2             ; Dynamic link pointer (caller MP)
MS_JTAB         = 4             ; Caller Jump Table pointer
MS_SEG          = 6             ; Caller Segment pointer
MS_IPC          = 8             ; Caller IPC (return address)
MS_SP           = 10            ; Caller Stack Pointer

; Resident System Tables in High RAM ($B000-$FEFF, in BASIC IMAGE space):
; SYSVARS ($AC00-$AE69) contains console state (CCOLS, CCX, CCY) and must NOT be overlapped.
PM_SYSCOM_ADDR  = $B000         ; SYSCOM record (340 bytes: $B000-$B153)
PM_SEC_BUF      = $B200         ; Disk Sector Buffer (512 bytes: $B200-$B3FF)
PM_SEG_DICT     = $B400         ; Segment Dictionary (128 bytes: $B400-$B47F)
PM_SEG0_BASE    = $B500         ; Segment 0 code base (7,768 bytes: $B500-$D357)
PM_HIGH_SEG1_BASE = $D358       ; Segment 1 resident slot in High RAM ($D358-$FDFF: 10.9 KB)
PM_HIGH_SEG1_MAX  = $FDFF       ; Top of High RAM segment 1 slot below I/O page

; Evaluation Stack ($2A50-$2FFF, 1456 bytes):
PM_EVAL_TOP     = $3000

; User RAM: Heap grows up from $3000, Stack grows down from $97FE
PM_HEAP_BASE    = $3000
PM_MEM_TOP      = $97FE         ; Top of User RAM below SCREEN ($9800)
PM_SYSCOM_SIZE  = 340           ; SYSCOM record size (170 words = 340 bytes)

