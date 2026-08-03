; ---------------------------------------------------------------------
; gfx.asm -- graphics inner loops.
;
; Part of the M2 gate corpus. These are the loops the machine actually
; exists to run, and they are where register pressure bites hardest:
; a source pointer, a destination pointer, a counter and pixel data all
; want to be live at the same time.
;
; Mode 2 geometry: 320x200, 2 bits per pixel, but these routines treat
; it as 1bpp monochrome for clarity -- the addressing arithmetic is what
; is being measured, not the pixel format.
; ---------------------------------------------------------------------

        .org  $0600

        .equ  SCREEN,   $A000           ; page-aligned, and that matters
        .equ  STRIDE,   40              ; 320 pixels / 8 per byte
        .equ  ROWS,     200


; ---------------------------------------------------------------------
; pixel_addr -- R0 = x (0..255), R1 = y (0..199)
; Returns X = byte address, R2 = bit mask.
;
; ADDW X,#imm16 exists because this routine needed it: adding SCREEN to
; X previously took three instructions via the pointer halves, and six
; if the base had not been page-aligned. See D20.
; ---------------------------------------------------------------------
pixel_addr:
        MOV  R2,#STRIDE
        MUL  R1,R2              ; X = y * STRIDE
        MOV  R2,R0
        SHR  R2
        SHR  R2
        SHR  R2                 ; x >> 3
        ADDW X,R2
        ADDW X,#SCREEN
        AND  R0,#7              ; bit within the byte
        MOV  R2,#$80
.shift: TST  R0
        BEQ  .done
        SHR  R2
        SUB  R0,#1
        BRA  .shift
.done:  RET


; ---------------------------------------------------------------------
; setpixel -- R0 = x, R1 = y
; ---------------------------------------------------------------------
setpixel:
        CALL pixel_addr
        LD   R0,[X]
        OR   R0,R2
        ST   [X],R0
        RET


; ---------------------------------------------------------------------
; hline -- Y = destination, R0 = byte count, R1 = pattern
; ---------------------------------------------------------------------
hline:  ST   [Y],R1
        INCW Y
        SUB  R0,#1
        BNE  hline
        RET


; ---------------------------------------------------------------------
; vline -- X = top address, R0 = row count, R1 = mask
; Walks down the screen a row at a time, OR-ing in the mask.
; ---------------------------------------------------------------------
vline:  MOV  R3,#STRIDE
.row:   LD   R2,[X]
        OR   R2,R1
        ST   [X],R2
        ADDW X,R3
        SUB  R0,#1
        BNE  .row
        RET


; ---------------------------------------------------------------------
; blit8 -- X = 8-byte sprite, Y = screen address. Opaque copy.
; ---------------------------------------------------------------------
blit8:  MOV  R0,#8
        MOV  R2,#STRIDE
.row:   LD   R1,[X]
        ST   [Y],R1
        INCW X
        ADDW Y,R2
        SUB  R0,#1
        BNE  .row
        RET


; ---------------------------------------------------------------------
; blit8_or -- X = 8-byte sprite, Y = screen address. Transparent,
; OR-ing the sprite into the background.
;
; This is the tightest graphics loop in the corpus: source pointer,
; destination pointer, row counter, stride, sprite byte and screen byte
; are all live at once. It fits in four registers plus X and Y with
; nothing to spare -- and only because the stride can stay in R2 rather
; than being reloaded each pass.
; ---------------------------------------------------------------------
blit8_or:
        MOV  R0,#8
        MOV  R2,#STRIDE
.row:   LD   R1,[X]             ; sprite byte
        LD   R3,[Y]             ; background byte
        OR   R3,R1
        ST   [Y],R3
        INCW X
        ADDW Y,R2
        SUB  R0,#1
        BNE  .row
        RET


; ---------------------------------------------------------------------
; blit8_mask -- X = sprite, Y = screen, and a mask table walked by a
; third pointer. Three pointers are needed and there are only two, so
; the mask pointer lives in memory and is reloaded each row.
;
; This is the routine that would most obviously benefit from a third
; pointer register.
; ---------------------------------------------------------------------
blit8_mask:
        MOV  R0,#8
.row:   LD   R1,[X]             ; sprite
        LD   R3,[Y]             ; background
        PUSHW Y                 ; spill: no third pointer register
        LDW  Y,[maskptr]
        LD   R2,[Y]             ; mask byte
        INCW Y
        STW  [maskptr],Y
        POPW Y
        MOV  R3,R3
        AND  R3,R2              ; punch the hole
        OR   R3,R1              ; drop the sprite in
        ST   [Y],R3
        INCW X
        MOV  R2,#STRIDE
        ADDW Y,R2
        SUB  R0,#1
        BNE  .row
        RET

maskptr:
        .word 0


; ---------------------------------------------------------------------
; scroll_up -- move the whole screen up one text row (8 pixel rows).
; Nested loops keep the 16-bit count out of the registers entirely.
; ---------------------------------------------------------------------
scroll_up:
        LDW  X,#SCREEN+STRIDE*8
        LDW  Y,#SCREEN
        MOV  R0,#(ROWS/8)-1
.block: MOV  R1,#STRIDE*8/2     ; two bytes per pass
.col:   LD   R2,[X]
        ST   [Y],R2
        INCW X
        INCW Y
        LD   R2,[X]
        ST   [Y],R2
        INCW X
        INCW Y
        SUB  R1,#1
        BNE  .col
        SUB  R0,#1
        BNE  .block
        RET


; ---------------------------------------------------------------------
; clear_screen -- R0 = fill byte
; ---------------------------------------------------------------------
clear_screen:
        LDW  Y,#SCREEN
        MOV  R1,#ROWS/8         ; 25 blocks of 320 bytes
.block: MOV  R2,#STRIDE*8/2
.byte2: ST   [Y],R0
        INCW Y
        ST   [Y],R0
        INCW Y
        SUB  R2,#1
        BNE  .byte2
        SUB  R1,#1
        BNE  .block
        RET
