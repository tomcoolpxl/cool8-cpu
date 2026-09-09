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
        .include "../fs.asm"
        .include "z3_save.asm"
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

        ; Set save drive: if R3 == $72 (vol 14) -> 14, else 13
        CMP  R3,#$72
        BNE  .is_d13
        MOV  R0,#14
        BRA  .st_drv
.is_d13:MOV  R0,#13
.st_drv:ST   [z_save_drive],R0

        ; Flash address = (R3 << 16) + (page << 8)
        LDW  X,#Z_FLS_L
        CLR  R0
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

z_save_drive:
        .byte 13
z_save_filename:
        .ascii "HHGG    SAV"

