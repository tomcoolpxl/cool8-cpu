; ---------------------------------------------------------------------
; The key-down bitmap: one bit per scancode, 128 keys in 16 bytes.
;
; The C64 kept the *one* key currently down in a byte at 197 and games
; read it with PEEK; the BBC asked about one key at a time with
; INKEY(-n). A bitmap costs sixteen bytes and answers both questions at
; once, including the one neither machine could -- left and fire
; together.
;
; The index is the raw scancode, so an $E0-prefixed key shares a bit
; with the keypad key it shares a scancode with. That is not a
; collision: this machine has no keypad, so only one of the two can ever
; be pressed.
; ---------------------------------------------------------------------

; kdset / kdclr -- R1 = the scancode. Both leave R1 alone; the caller is
; part-way through decoding it.
kdset:  PUSH R0
        PUSH R2
        PUSHW X
        CALL kdbit
        LD   R2,[X]
        OR   R2,R0
        ST   [X],R2
        POPW X
        POP  R2
        POP  R0
        RET

kdclr:  PUSH R0
        PUSH R2
        PUSHW X
        CALL kdbit
        NOT  R0
        LD   R2,[X]
        AND  R2,R0
        ST   [X],R2
        POPW X
        POP  R2
        POP  R0
        RET

; kdbit -- R1 = scancode; returns X on its byte and R0 holding its mask.
;
; The mask comes out of a table rather than a shift loop: there is no
; SHL on this machine (ADD Rd,Rd is the idiom, see tools/opcodes.py) and
; eight bytes of table is shorter than the loop that would replace it,
; as well as being the same handful of cycles for every key.
;
; Scancodes $80 and up are not keys -- $E1 opens Pause, $AA and $FA are
; the keyboard answering a command -- so they get a zero mask and set
; and clear nothing.
kdbit:  PUSH R2
        MOV  R2,R1
        AND  R2,#$07            ; the bit within the byte
        LDW  X,#bitmask
        ADDW X,R2
        LD   R0,[X]
        MOV  R2,R1
        SHR  R2                 ; the byte within the bitmap
        SHR  R2
        SHR  R2
        AND  R2,#$0F
        LDW  X,#kdown
        ADDW X,R2
        MOV  R2,R1
        BTST R2,#$80
        BEQ  .ok
        CLR  R0
.ok:    POP  R2
        RET

; One bit set, eight ways -- see kdbit above.

bitmask:
        .byte $01,$02,$04,$08,$10,$20,$40,$80
