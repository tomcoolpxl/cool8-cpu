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

        .include "org.asm"   ; generated: top-aligned under the I/O page

; **The first three bytes of the image are its entry point.**
;
; The relocating stub jumps to $A000 because that is the address it was
; told to load at; it has no symbol table and cannot find `main`. While
; the system was compiled BASIC that worked by accident -- the compiler
; put the program's entry first. Here `main` is at the far end, past
; every module, so $A000 was the first instruction of sw/console.asm
; and booting from flash executed the console's internals from the
; middle. It relocated correctly, painted the banner the stub had left,
; and then ran off into user RAM with no vectors installed.
;
; Three bytes, and the image has one door again.
        JMP  main

MAINK   = $AC00                 ;: 2 the key just read

; ---------------------------------------------------------------------
; The stack, stated once, bottom first.
;
; **This order is the design, not an accident of nesting.** Each module
; includes what it needs and the includes are idempotent, so any of them
; assembles alone -- but a reader should be able to see the layering in
; one place, and this is that place. A module may call downward in this
; list and never upward ([D68]).
;
; `fscmd` is above `interp` and not below it, which the move of the disk
; handlers made obvious: they use `eval`, `cnext` and the `SKIPSP` macro,
; so a `fscmd` assembled first does not even parse.
; ---------------------------------------------------------------------
        .include "zp.asm"       ; the storage map, and the I/O page
        .include "console.asm"  ; the screen, the cursor, characters out
        .include "num.asm"      ; numbers as text
        .include "input.asm"    ; keys in, from either wire
        .include "token.asm"    ; text to tokens and back
        .include "prog.asm"     ; the stored program
        .include "interp.asm"   ; the language
        .include "fp.asm"       ; floating point
        .include "fpbas.asm"    ;   ...and its binding
        .include "edit.asm"     ; the screen as document
        .include "fscmd.asm"    ; the disk commands
        .include "kbd.asm"      ; PS/2 decoding
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
        CALL idrct
        JMP  main_err           ; ?WHAT IN nn, if it set ERR

; sys_pre -- SYS an address, or SYS a file ([D87]).
;
; Here for `run_pre`'s reason: `interp.asm` holds `h_sys` and is below
; `fscmd.asm`, which holds the loader, so the fork cannot live in either
; -- only in the layer that may call both. A quote is the whole test.
sys_pre:
        SKIPSP
        CMP  R2,#$22            ; '"' -- a file rather than an address
        BEQ  h_sysf
        JMP  h_sys

; run_pre -- RUN, with the read stream shut first ([D82]).
;
; **Here and not in `h_run`, because of the layering.** `interp.asm` is
; below `fscmd.asm` and may not call upward ([D68]), so a statement
; handler cannot close a file. `main.asm` is the composition layer and
; may call anything -- the same argument `sttab` makes for living here.
;
; RUN and not `main_pre`: main_pre runs before every *direct* line too,
; and `OPENIN "D"` followed by `PRINT BGET` is two direct lines. Closing
; there would make the feature unusable from the keyboard.
run_pre:
        CALL frclose
        JMP  h_run

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
        ; **The call stack and the save stack are the user's memory.**
        ; They sit directly above the name table, which is itself at
        ; PROGEND -- 32 frames and 256 bytes of saves is 416 bytes, and
        ; that does not fit the image's growth slack while being nothing
        ; against 40,448 ([D72]). BBC BASIC puts its stack in the user's
        ; memory too, descending from HIMEM.
        LD   R0,[PROGEND]
        LD   R1,[PROGEND+1]
        ADD  R0,#<(MAXNAME*NENT)
        ST   [CSTK],R0
        MOV  R0,#>(MAXNAME*NENT)
        ADC  R1,R0
        ST   [CSTK+1],R1
        ; **The heap is not reset here.** It used to be, and main_pre
        ; runs before every direct line as well as before RUN, so every
        ; direct line threw away every array and every string the last
        ; one made. `prg_store` and `irun` call `vclear`; a direct line
        ; must not. The heap comes down from the top of the user's
        ; region, which is one region again -- the screen, system
        ; storage and the image are all above it, so `$0200` runs
        ; contiguously to USERTOP and a program may spend it as text or
        ; as arrays in any proportion ([D69]).
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
        CALL con_setrow
.udone: CALL con_cursor
        BRA  main_loop
.down:  CALL con_down
        CALL con_cursor
        BRA  main_loop
.home:  CLR  R0
        ST   [CCX],R0
        ST   [CCY],R0
        CALL con_setrow
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
; The interrupts. Both inputs end in one ring, and nothing above them
; can tell which wire a key came in on.
; =====================================================================

; The break button. SW[0]'s NMI lands here now that BASIC owns the
; machine: the ROM's bare-RETI handler went away with the overlay, and
; an unhandled NMI executed whatever image bytes sat at the stale
; vector -- a break that half worked and an interpreter that needed a
; reboot. One flag, the same one Ctrl+Pause and the serial Ctrl-C set,
; so every way of asking for a break is the same break.
inmi:   PUSH R0
        ; Ctrl+Esc arrives here too -- the keyboard raises NMI for it and
        ; latches a flag saying which it was, so the break button and the
        ; restart chord share one unmaskable path and are told apart by
        ; asking. Acknowledged by writing the bit back, the shape
        ; VID_IRQ and UART_STAT use.
        LD   R0,[KBD_MOD]
        BTST R0,#$08
        BEQ  .brk
        MOV  R0,#$08
        ST   [KBD_MOD],R0
        MOV  R0,#1
        ST   [irst],R0          ; the prompt loop does the restart
.brk:   MOV  R0,#1
        ST   [ibreak],R0
        POP  R0
        RETI

iisr:   PUSH R0
        PUSH R1
        PUSHW X
        MOV  R0,#$22            ; acknowledge vblank, keep it enabled
        ST   [VID_IRQ],R0
        LD   R0,[frames]        ; the tick TIMER reads and VSYNC waits on
        ADD  R0,#1
        ST   [frames],R0
        LD   R0,[frames+1]      ; LD leaves C alone, so the carry rides
        ADC  R0,#0
        ST   [frames+1],R0
.more:  LD   R0,[UART_STAT]     ; anything waiting on the wire?
        BTST R0,#$01
        BEQ  .kbd
        LD   R0,[UART_DATA]     ; taking it is the only way to see it
        CMP  R0,#$03            ; Ctrl-C, the serial console's Break
        BNE  .keep
.stop:  MOV  R0,#1
        ST   [ibreak],R0        ; the flag the interpreter polls
        BRA  .more
.keep:  CALL irpush
        BRA  .more

        ; The keyboard. Raw Set 2 arrives and kbd.asm turns it into a
        ; key, or into nothing at all for a prefix, a release or a
        ; shift. Ctrl+Pause decodes to $03, so the Break key and the
        ; serial console's Ctrl-C are the same byte and stop a program
        ; through the same test above.
.kbd:   LD   R0,[KBD_STAT]
        BTST R0,#$01
        BEQ  .done
        LD   R0,[KBD_DATA]      ; reading has a side effect
        CALL scancode
        TST  R0
        BEQ  .kbd
        CMP  R0,#$03
        BEQ  .stop
        CALL irpush
        BRA  .kbd
.done:  POPW X
        POP  R1
        POP  R0
        RETI

; irpush -- R0 into the ring. Both inputs come through here.
irpush: LD   R1,[irhead]
        LDW  X,#irring
        ADDW X,R1
        ST   [X],R0
        ADD  R1,#1
        AND  R1,#15
        ST   [irhead],R1
        RET

; =====================================================================
; main_err -- `?WHAT IN nn`, or `?WHAT` for a line that was typed.
;
; **One message table for the whole system**, which is what [D46] and
; the editor's own `errmsg` were separately reaching into: entries 0-18
; are indexed by `ERR - 1` and the tail is the disk's, reached by the
; same arithmetic. The `?` is the whole ceremony -- there is no ERROR
; suffix anywhere, which is the C64's economy and the reason the table
; fits at all.
;
; LREC still holds the record that failed, so the line number is a read
; rather than a search -- and a record outside the program is a typed
; line, which prints no number.
; =====================================================================
; **The handler is entered from here, and that is why it is cheap.**
; The interpreter unwinds a fault by returning -- every handler, every
; loop, every CALL frame -- so by the time an error is visible in this
; routine the CPU stack is already back at main's level. Trapping needs
; no longjmp and no saved stack pointer: it needs a line number.
;
; `goton` is the whole of the jump. It is GOTO's own tail -- prg_find,
; LREC, openline, ipoll, JMP stmt -- and `stmt` returns when the program
; stops, so CALL goton reads as "run from this line until it ends" and
; the loop below catches whatever it ends with.
;
; **Three things this deliberately does not do.** It does not trap
; E_STOP, or a program with a handler and a loop could never be stopped
; by the break key. It does not trap E_DONE, which is a clean finish.
; And it **disarms on entry**, so a fault inside the handler prints
; rather than re-entering it forever; a program that wants to go on
; catching says `ON ERROR GOTO` again, which is BBC's arrangement too.
main_err:
.again: LD   R0,[ERR]
        TST  R0
        BEQ  .out
        CMP  R0,#E_DONE         ; 255 is a clean stop, not a fault
        BEQ  .clr
        CMP  R0,#E_STOP         ; the break key stays the user's
        BEQ  .tell
        LD   R0,[EHAND]
        LD   R1,[EHAND+1]
        MOV  R2,R0
        OR   R2,R1
        BEQ  .tell              ; nothing armed: say so as before
        PUSH R0
        PUSH R1
        LD   R0,[ERR]
        ST   [ELAST],R0         ; what ERR will report
        CLR  R0
        ST   [ERR],R0
        ST   [EHAND],R0         ; disarmed: the handler runs untrapped
        ST   [EHAND+1],R0
        POP  R1
        POP  R0
        CALL goton
        BRA  .again
        ; **ERR again, because the handler test spent R0.** The walk
        ; below indexes the message table on it, and reaching here
        ; through the `no handler armed` branch left EHAND's low
        ; byte there -- which is zero, so every untrapped fault
        ; printed the table's first entry walked to nowhere.
.tell:  LD   R0,[ERR]
        PUSHW X
        PUSHW Y
        LDW  X,#RUNTAB          ; walk to the message ERR - 1 selects
        MOV  R3,R0
        SUB  R3,#1
        BEQ  .say
.w:     LD   R0,[X]
        INCW X
        TST  R0
        BNE  .w
        SUB  R3,#1
        BNE  .w
.say:   MOV  R0,#$3F            ; '?'
        PUSHW X
        CALL con_emit
        POPW X
        CALL con_puts
        ; A line number, if the record that failed is inside the program.
        LD   R0,[LREC]
        LD   R1,[LREC+1]
        MOV  R2,#<PROGBOT
        MOV  R3,#>PROGBOT
        SUB  R0,R2
        SBC  R1,R3
        BLO  .nl
        LD   R0,[LREC]
        LD   R1,[LREC+1]
        LD   R2,[PROGEND]
        LD   R3,[PROGEND+1]
        SUB  R0,R2
        SBC  R1,R3
        BHS  .nl
        LDW  X,#MSGIN
        CALL con_puts
        LDW  X,[LREC]
        CALL prg_no
        CALL num_put
.nl:    CALL con_nl
        POPW Y
        POPW X
.clr:   CLR  R0
        ST   [ERR],R0
.out:   RET

; RUNTAB and the messages are in sw/console.asm: every module that
; prints includes the console, and three of them print these ([D68]).

; =====================================================================
; main -- the entry point. The flash stub jumps here.
; =====================================================================
main:
        ; **Interrupts off before anything else.**
        ;
        ; The boot ROM enables the vertical blank and the keyboard to
        ; drive its own loading screen, and it is still enabled when it
        ; jumps here. Between that jump and the `EI` below there are two
        ; windows of tens of thousands of instructions -- the RAM wipe
        ; and the relocation before it -- during which $FFFC still holds
        ; the ROM's handler, and the overlay it lived in is gone. An
        ; interrupt in that window dispatches to $F140, which is now
        ; image bytes, and the CPU executes the middle of a routine.
        ;
        ; That is what happened: booting from flash landed at $020E with
        ; the vectors never installed, while every test that pokes the
        ; image in and jumps to `main` was fine, because none of them
        ; had a live interrupt to arrive.
        DI

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
        ; **To the top of the user's region, which is the map's floor.**
        ; This said $7F, the page above the old user area, and [D69]'s
        ; repack moved that top from $7C75 to $A3FF -- leaving
        ; $7F00-$A3FF unwiped, where a stale byte reads as a line record
        ; and the interpreter walks off into it. `?SYNTAX IN -32763` was
        ; a line number read out of $8005.
        CMP  R1,#>CSCRN
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

        CALL prg_new            ; which empties the variables too
        CALL fsc_init           ; the drive a cold machine starts on
        CALL con_warm           ; **not con_init**, which ends in con_cls
        ; The screen already shows the boot banner -- the stub painted
        ; it, and it was just wiped from RAM. The cursor goes under it.
        ; That only stayed true while nothing here reached the console:
        ; `con_init` clears, so the first boot that actually got this far
        ; wiped the banner it was written to preserve.
        MOV  R0,#10
        ST   [CCY],R0
        CALL con_setrow
        CLR  R0
        ST   [CCX],R0
        CALL con_cursor
        ; The boot ROM lit the green LED when it found BOOT.BIN; the
        ; system is up now, so out it goes. Its whole duration is the
        ; relocation and this startup -- a blink, with no timer.
        CLR  R0
        ST   [LED],R0
        JMP  main_loop

; =====================================================================
; sttab -- the statement table, and the only place that names them all
;
; **It lives here because it is the composition, not the language.**
; A statement token indexes this table and stmt in sw/interp.asm jumps
; through it; the entries point at handlers spread over every module --
; PRINT is the interpreter's, LIST is prog.asm's, SAVE is fscmd.asm's,
; CLS is console.asm's. Wherever this table sits, that file depends on
; all of them, so it sits at the top where depending on everything is
; the job ([D68]).
;
; That leaves interp.asm naming sttab upward, which is the one
; deliberate exception to the call-downward rule and the usual shape for
; a dispatcher: the interpreter says a table of this form must exist,
; and the system says what is in it. Before this move the table sat in
; the middle of interp.asm and dragged the whole image into anything
; that wanted the expression evaluator.
;
; $80... Everything not implemented lands on ad, which is the
; honest answer and costs one slot each.
; =====================================================================
sttab:
        .word h_print           ; $80 PRINT
                                ;: PRINT [item][; | ,]...  strings and numbers; a trailing separator holds the newline
        .word h_sub             ; $81 SUB -- a definition, skipped
                                ;: SUB name  a definition; stepped over when execution reaches it
        .word bad               ; $82 -- reserved, was FUNCTION
                                ;: ! -- reserved  was FUNCTION, which only ever parsed as SUB
        .word h_dim             ; $83 DIM
                                ;: DIM name(size:int[,size:int[,size:int]])  up to three dimensions; the name's suffix picks the element -- none integer, # float, $ string !intonly
        .word run_pre           ; $84 RUN, up from the tail when
                                ;: RUN
                                ;   CONST left
        .word h_for             ; $85 FOR
                                ;: FOR var = from:int TO to:int [STEP step:int]  eight deep !intonly
        .word h_next            ; $86 NEXT
                                ;: NEXT [var]  naming an outer var closes the inner loops
        .word bad               ; $87 TO
        .word h_do              ; $88 DO
                                ;: DO [WHILE cond | UNTIL cond]
        .word h_loop            ; $89 LOOP
                                ;: LOOP [WHILE cond | UNTIL cond]
        .word bad               ; $8A WHILE
        .word bad               ; $8B UNTIL
        .word h_exit            ; $8C EXIT
                                ;: EXIT DO
        .word h_if              ; $8D IF
                                ;: IF cond THEN stmt [ELSE stmt]  single line; the arm is one statement
        .word bad               ; $8E THEN
        .word h_else            ; $8F ELSE
                                ;: ELSE stmt
        .word h_else            ; $90 ELSEIF
                                ;: ELSEIF cond THEN stmt
        .word h_end             ; $91 END
                                ;: END
        .word h_ret             ; $92 RETURN
                                ;: RETURN
        .word h_call            ; $93 CALL
                                ;: CALL name  no parameters and no locals
        .word bad               ; $94 AS
        .word bad               ; $95 INT
                                ;: INT(a:float) -> int  floors; the float-to-integer crossing
        .word bad               ; $96 BYTE
        .word bad               ; $97 PEEK
                                ;: PEEK(addr:int) -> int  a function, not a statement !intonly
        .word h_poke            ; $98 POKE
                                ;: POKE addr:int, value:int !intonly
        .word bad               ; $99 AND
        .word bad               ; $9A OR
        .word bad               ; $9B XOR
        .word bad               ; $9C CARD
        .word bad               ; $9D AT
        .word sys_pre           ; $9E SYS
                                ;: SYS addr:int | name:string  jumps to an address, or loads a PRG and jumps where its first two bytes say !intonly
        .word bad               ; $9F EXTERN
        .word bad               ; $A0 INCLUDE
        .word bad               ; $A1 INLINE
        .word h_goto            ; $A2 GOTO
                                ;: GOTO line:int
        .word bad               ; $A3 WEND
        .word bad               ; $A4 NUM
                                ;: (reserved)  K_NUM: a numeric literal with two binary bytes after it. The "?" entry in TOKTAB holds the slot open
        .word h_mode            ; $A5 MODE
                                ;: MODE n:int !intonly
        .word h_vsync           ; $A6 VSYNC
                                ;: VSYNC  waits for the next frame
        .word bad          ; $A7 SCROLL
                                ;: (removed)  was SCROLL dx, dy -- POKE VID_SCX/VID_SCY, see 04a-registers.md
        .word h_color     ; $A8 COLOR
                                ;: COLOR fg:int[, bg:int]  the pen every PRINT, CLS and scroll writes. 0-15 each; with no bg the paper stays as it was
        .word h_cursor     ; $A9 CURSOR
                                ;: CURSOR on:int[, rate:int]  0 off, 1 on. Rate 0-3 is 8, 16, 32 frames a phase and 3 is solid; the blink is the hardware's
                                ;: (removed)  was SPRITE n, x, y, pattern, attr -- POKE SPR_IDX = n*8, eight bytes to SPR_DATA, then SPR_CTRL
        .word bad           ; $AA VPOKE
                                ;: (removed)  was VPOKE addr, value -- POKE VRAM_ADDR_L/H, VRAM_STEP, then VRAM_DATA, which auto-steps
        .word h_sound           ; $AB SOUND
                                ;: SOUND voice:int, pitch:int, volume:int, length:int !intonly
        .word bad               ; $AC HLINE
                                ;: (removed)  was HLINE x, y, n, colour -- set PIX_X/PIX_Y, then POKE PIX_DATA n times; the port steps X itself
        .word h_plot            ; $AD PLOT
                                ;: PLOT x:int, y:int, colour:int !intonly
        .word h_line            ; $AE LINE
                                ;: LINE x1:int, y1:int, x2:int, y2:int, colour:int !intonly
        .word h_input           ; $AF INPUT
                                ;: INPUT var  a line of text; the variable's suffix decides -- string, float or integer
        .word h_else            ; $B0 DATA -- executed, it is a line to
                                ;: DATA n[, n]...  numbers only; skipped when execution reaches it
                                ;   step over, which is ELSE's whole job
        .word h_read            ; $B1 READ
                                ;: READ var[, var]...  scalar targets only
        .word h_restore         ; $B2 RESTORE
                                ;: RESTORE
        .word bad               ; $B3 STEP -- a clause, like TO
        .word h_on              ; $B4 ON
                                ;: ON e:int GOTO line[, line]...  literal lines; out of range falls through
        .word bad            ; $B5 TILE
                                ;: (removed)  was TILE x, y, tile, attr -- the map entry through the VRAM port
        .word h_clg             ; $B6 CLG
                                ;: CLG colour:int !intonly
        .word h_pitch           ; $B7 PITCH
                                ;: PITCH voice:int, pitch:int !intonly
        .word h_gtext           ; $B8 GTEXT
                                ;: GTEXT x:int, y:int, text:string !intonly
        .word h_list            ; $B9 LIST -- the former editor
                                ;: LIST [from:int][, to:int]
        .word h_new             ; $BA NEW     commands, one vocabulary
                                ;: NEW
        .word h_free            ; $BB FREE    now: every one runs in a
                                ;: FREE  prints the bytes left
        .word h_renum           ; $BC RENUM  program or typed direct
                                ;: RENUM
        .word h_del             ; $BD DELETE
                                ;: DELETE from:int[, to:int]
        .word h_cls             ; $BE CLS
                                ;: CLS
        .word h_save            ; $BF SAVE
                                ;: SAVE name:string [AT addr:int, len:int]  no AT saves the program; AT saves len bytes of memory, and the length is not optional
        .word h_load            ; $C0 LOAD
                                ;: LOAD name:string [AT addr:int | , line:int]  no AT loads a program and chains into it; AT loads raw bytes, the file's own length; a comma merges from that line up
        .word h_dir             ; $C1 DIR
                                ;: DIR
        .word h_era             ; $C2 ERA
                                ;: ERA name:string
        .word h_compact         ; $C3 COMPACT
                                ;: COMPACT
        .word h_drive           ; $C4 DRIVE
                                ;: DRIVE n:int
        .word h_rem             ; $C5 REM
                                ;: REM text  stored verbatim; nothing inside is tokenised
        ; $C6 is the float literal's marker and never a statement. A
        ; line cannot begin with one -- tokenise only writes it after a
        ; digit or a point -- so reaching here means a corrupt line, and
        ; ?SYNTAX is the right answer.
        .word bad               ; $C6 !
                                ;: ! -- reserved  the float literal marker, never a statement
        .word h_clear           ; $C7 CLEAR
                                ;: CLEAR  every variable away, the program kept
        .word h_local           ; $C8 LOCAL
                                ;: LOCAL name[,name]  inside a SUB: the caller's values come back on RETURN
        .word bad               ; $C9 TAB -- PRINT only
                                ;: TAB(col:int)  in PRINT: spaces out to that column, or nothing if already past it
        .word bad               ; $CA SPC -- PRINT only
                                ;: SPC(n:int)  in PRINT: n spaces
        .word h_pause           ; $CB PAUSE
                                ;: PAUSE frames:int  wait, still answering the break key !intonly
        .word h_cont            ; $CC CONT
                                ;: CONT  resume a program the break key stopped
        .word bad               ; $CD NOT -- a prefix in an expression
                                ;: NOT n:int  -1 - n, bitwise; binds looser than a comparison and tighter than AND !intonly
        .word h_stop            ; $CE STOP
                                ;: STOP  stops with ?BREAK, and CONT resumes; the break key's own tail
        .word h_openin          ; $CF OPENIN
                                ;: OPENIN name:string  positions a read stream at the file's first byte; one at a time
        .word h_close           ; $D0 CLOSE
                                ;: CLOSE  abandons the read stream; harmless if none is open
        .word bad               ; $D1 ERROR -- a clause after ON
                                ;: ON ERROR GOTO line:int  arm a handler; GOTO 0 disarms. ERR says which fault fired
        .word h_gosub           ; $D2 GOSUB
                                ;: GOSUB line:int  call a line; RETURN comes back. Shares CALL's frame and its depth limit


