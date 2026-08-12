; ---------------------------------------------------------------------
; main.asm -- boot, and the prompt loop.
;
; The top of the stack ([D68]): it may call anything and nothing calls
; it. This is where `sw/basic.bas` used to be, and the shape is BBC
; BASIC's exactly -- read a line, tokenise it at entry, look for a line
; number, store it or run it now.
;
; The loop itself is the C64's: there is no prompt and no input buffer.
; The screen is the document, the cursor keys move over it, and Return
; enters whichever logical line the cursor is on -- which may be one
; typed ten seconds ago, or a line of a LIST.
; ---------------------------------------------------------------------

MAINK   = $7C7A                 ;: 2 the key just read

        .include "fscmd.asm"    ; which brings everything below it
        .include "input.asm"
        .include "interp.asm"
        .include "fp.asm"
        .include "fpbas.asm"
        .include "kbd.asm"
        .include "keymap.asm"
        .include "kdown.asm"

K_LEFT  = 258
K_RIGHT = 259
K_UPK   = 256
K_DOWNK = 257
K_HOMEK = 260
K_ENDK  = 261
K_DELK  = 262
K_INSK  = 263

; =====================================================================
; ed_direct -- a line with no number: run it now.
;
; The line is already tokenised in TBUF. It is staged as a record at
; DIRBUF with the sentinel line number $FFFF -- no legal line is 65535,
; and `nextline` recognises the staged record by its page -- and then
; executed by `idrct`, which is `irun` without the variable clear.
;
; What is deliberately not done: no variable clear, so `PRINT A` after a
; break works; and none of RUN's mode restore, so a direct `MODE 3`
; takes effect and *stays*. That is the whole point and exactly the
; C64's freedom -- `MODE 0` typed blind brings the editor back.
; =====================================================================
ed_direct:
        MOV  R0,#$FF
        ST   [DIRBUF],R0
        ST   [DIRBUF+1],R0
        LD   R0,[TLEN]
        ST   [DIRBUF+2],R0
        PUSHW X
        PUSHW Y
        LDW  X,#DIRBUF+3
        LDW  Y,#TBUF
        LD   R3,[TLEN]
        TST  R3
        BEQ  .z
.c:     LD   R0,[Y]
        ST   [X],R0
        INCW X
        INCW Y
        SUB  R3,#1
        BNE  .c
.z:     CLR  R0
        ST   [X],R0             ; the end-of-line marker
        POPW Y
        POPW X
        CALL main_pre
        JMP  idrct

; main_pre -- the preflight both RUN and a direct line need: where the
; program, the heap, the accumulator and the CALL stack are.
main_pre:
        MOV  R0,#<PROGBOT
        ST   [LREC],R0
        MOV  R0,#>PROGBOT
        ST   [LREC+1],R0
        MOV  R0,#>SACCBUF
        ST   [SACC+1],R0
        MOV  R0,#<SACCBUF
        ST   [SACC],R0
        MOV  R0,#<CSTKBUF
        ST   [CSTK],R0
        MOV  R0,#>CSTKBUF
        ST   [CSTK+1],R0
        MOV  R0,#<USERTOP
        ST   [HEAP],R0
        MOV  R0,#>USERTOP
        ST   [HEAP+1],R0
        LD   R0,[PROGEND]       ; PEND and the name table both start at
        ST   [PEND],R0          ;   the end of the program text
        ST   [NTAB],R0
        LD   R0,[PROGEND+1]
        ST   [PEND+1],R0
        ST   [NTAB+1],R0
        CLR  R0
        ST   [ERR],R0
        RET

; =====================================================================
; The prompt loop
; =====================================================================
main_loop:
        CALL in_get             ; blocks, blinking the soft cursor
        ST   [MAINK],R0
        MOV  R0,R1
        ST   [MAINK+1],R0

        LD   R0,[irst]          ; Ctrl+Esc asked for the editor back
        TST  R0
        BEQ  .k
        CALL main_reset

.k:     LD   R1,[MAINK+1]
        TST  R1
        BNE  .named             ; 256 and up: a cursor key or Home
        LD   R0,[MAINK]
        CMP  R0,#13
        BEQ  .enter
        CMP  R0,#8              ; backspace
        BEQ  .bs
        CMP  R0,#$7F
        BEQ  .bs
        CMP  R0,#$20            ; anything else printable is typed in
        BLO  main_loop
        CALL con_emit
        BRA  main_loop
.enter: LD   R0,[CCY]
        CALL ed_enter
        BRA  main_loop
.bs:    CALL ed_bs
        BRA  main_loop

.named: LD   R0,[MAINK]         ; the offset from K_UP
        CMP  R0,#<K_LEFT
        BEQ  .left
        CMP  R0,#<K_RIGHT
        BEQ  .right
        CMP  R0,#<K_UPK
        BEQ  .up
        CMP  R0,#<K_DOWNK
        BEQ  .down
        CMP  R0,#<K_HOMEK
        BEQ  .home
        CMP  R0,#<K_ENDK
        BEQ  .end
        CMP  R0,#<K_DELK
        BEQ  .del
        CMP  R0,#<K_INSK
        BEQ  .ins
        BRA  main_loop
.left:  CALL ed_left
        CALL con_cursor
        BRA  main_loop
        ; The C64's right: past the row's end, on to the next row -- and
        ; at the bottom the screen scrolls rather than wrapping to the
        ; top.
.right: LD   R0,[CCX]
        LD   R1,[CCOLS]
        SUB  R1,#1
        CMP  R0,R1
        BHS  .rwrap
        ADD  R0,#1
        ST   [CCX],R0
        BRA  .rdone
.rwrap: CLR  R0
        ST   [CCX],R0
        CALL con_down
.rdone: CALL con_cursor
        BRA  main_loop
.up:    LD   R0,[CCY]
        TST  R0
        BEQ  .udone
        SUB  R0,#1
        ST   [CCY],R0
.udone: CALL con_cursor
        BRA  main_loop
.down:  CALL con_down
        CALL con_cursor
        BRA  main_loop
.home:  CLR  R0
        ST   [CCX],R0
        ST   [CCY],R0
        CALL con_cursor
        BRA  main_loop
.end:   CALL ed_end
        BRA  main_loop
.del:   CALL ed_del
        CALL con_cursor
        BRA  main_loop
.ins:   CALL ed_ins
        CALL con_cursor
        BRA  main_loop

; =====================================================================
; main_reset -- Ctrl+Esc: put the machine back where the editor can be
; used, and keep the program.
;
; That is the state a program ruins rather than the memory it fills:
; MODE 4 with sprites over an unreadable screen is a working machine
; nobody can see, and the listing is the thing worth not losing.
; Ctrl+Shift+Esc does not come here -- the keyboard resets the machine
; itself, because a program that has stopped listening cannot be asked
; to.
; =====================================================================
main_reset:
        CLR  R0
        ST   [irst],R0
        MOV  R0,#$80            ; mode 0, display on
        ST   [VID_MODE],R0
        MOV  R0,#<CSCRN
        ST   [VID_BASE_L],R0
        MOV  R0,#>CSCRN
        ST   [VID_BASE_H],R0
        CLR  R0
        ST   [SPR_CTRL],R0      ; sprites off
        JMP  con_init

; =====================================================================
; main -- the entry point. The flash stub jumps here.
; =====================================================================
main:
        ; User RAM and the system storage region above it, wiped in one
        ; pass: the relocating stub -- and the boot screen it painted
        ; from -- lived at $0200, and nothing of it may survive to be
        ; executed, LISTed or LOADed over. Before EI, because the
        ; interrupt writes the key ring.
        LDW  X,#PROGBOT
        CLR  R0
.wz:    ST   [X],R0
        INCW X
        MOV  R1,XH
        CMP  R1,#$7F
        BNE  .wz
        MOV  R0,#1              ; a zeroed xorshift stays zero forever
        ST   [rseed],R0

        ; The vectors. The ROM's handlers went away with the overlay, so
        ; an uninstalled one would send an interrupt into image bytes.
        MOV  R0,#<iisr
        ST   [$FFFC],R0
        MOV  R0,#>iisr
        ST   [$FFFD],R0
        MOV  R0,#<inmi
        ST   [$FFFA],R0
        MOV  R0,#>inmi
        ST   [$FFFB],R0
        MOV  R0,#$20            ; the vertical blank interrupt
        ST   [VID_IRQ],R0
        MOV  R0,#$11            ; clear the keyboard FIFO and enable it:
        ST   [KBD_CTRL],R0      ;   stale codes are not input
        MOV  R0,#$10
        ST   [KBD_CTRL],R0
        EI

        CALL prg_new
        CALL fsc_mount
        CALL con_init
        ; The screen already shows the boot banner -- the stub painted
        ; it, and it was just wiped from RAM. The cursor goes under it.
        MOV  R0,#10
        ST   [CCY],R0
        CLR  R0
        ST   [CCX],R0
        CALL con_cursor
        ; The boot ROM lit the green LED when it found BOOT.BIN; the
        ; system is up now, so out it goes. Its whole duration is the
        ; relocation and this startup -- a blink, with no timer.
        CLR  R0
        ST   [LED],R0
        JMP  main_loop
