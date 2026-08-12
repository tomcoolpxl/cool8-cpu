; ---------------------------------------------------------------------
; input.asm -- keys in, from whichever wire they arrived on.
;
; PS/2 Set 2 scancodes are what a keyboard sends, and are the only way
; to see a cursor key or Home. The serial console is decoded from ANSI
; into the same codes, so **nothing above this file cares which wire a
; key came in on** ([D68]). The two wires meet here and nowhere else.
;
; `sw/kbd.asm` is below this: it decodes PS/2 into characters and the
; $80+n named codes. This is the ring and the line discipline above it.
;
; ## Reading the ring, not the device
;
; The interrupt fills a sixteen-byte ring and everything here reads
; memory. That is the C64's arrangement and the BBC's -- the interrupt
; keeps the input fresh -- and it is what lets a *running* program be
; stopped, since a running program cannot poll.
;
; ## What the compiled version spent 393 bytes on
;
; `serialkey` decoded `ESC [ A` with a chain of eight `IF d = nn`
; comparisons, each returning a different named code. It is a lookup:
; the codes `K_UP` through `K_INS` are contiguous, so the table holds
; the final ANSI byte and an offset, and the two keys that end with a
; `~` are marked with a bit rather than given cases of their own.
; ---------------------------------------------------------------------

BLB     = $7DAD                 ;: 2 frame count at the last blink flip

K_UP    = 256                   ; named keys live above the byte range,
K_NAMED = 8                     ;   K_UP..K_INS, and are contiguous

; The console, for the soft cursor, and the storage map for the ring the
; interrupt fills and the frame counter it keeps. Both includes are
; idempotent, so it costs nothing that main.asm asks for them too and
; that this file can be assembled on its own for a test.
;
; `irring`, `irhead`, `irtail` and `frames` are claims in sw/zp.asm
; today because that is where [D67] put the region. They are input's
; state and the interrupt's, and they move into this file when
; sw/basic.bas goes and there is no longer a second owner to collide
; with.
        .include "zp.asm"
        .include "console.asm"

; ---------------------------------------------------------------------
; in_raw -- R0 = the next byte from the ring, 0 if nothing is waiting.
; R1 = 0 always: the ring holds bytes.
;
; `.rk0` is the "nothing waiting" branch and is the one address that
; means idle rather than busy -- `sim/test_basic.py` settles on it, so
; the label is part of the interface.
; ---------------------------------------------------------------------
in_raw: LD   R0,[irtail]
        LD   R1,[irhead]
        CMP  R0,R1
        BEQ  .rk0
        PUSHW X
        LDW  X,#irring
        ADDW X,R0
        LD   R1,[X]
        POPW X
        ADD  R0,#1
        AND  R0,#15
        ST   [irtail],R0
        MOV  R0,R1
        CLR  R1
        RET
.rk0:   CLR  R0
        CLR  R1
        RET

; in_wait -- the same, but block. R0 = the byte.
in_wait:
        CALL in_raw
        TST  R0
        BEQ  in_wait
        RET

; ---------------------------------------------------------------------
; The escape table: the byte that ends an ANSI sequence, and which named
; key it is as an offset from K_UP. Bit 7 marks the two that are
; followed by a `~` which has to be swallowed.
; ---------------------------------------------------------------------
ESCTIL  = $80                   ; ...and a tilde follows

esctab: .byte $41,0             ; ESC [ A   up
        .byte $42,1             ; ESC [ B   down
        .byte $44,2             ; ESC [ D   left
        .byte $43,3             ; ESC [ C   right
        .byte $48,4             ; ESC [ H   home
        .byte $46,5             ; ESC [ F   end
        .byte $33,ESCTIL+6      ; ESC [ 3 ~ delete
        .byte $32,ESCTIL+7      ; ESC [ 2 ~ insert
        .byte 0

; ---------------------------------------------------------------------
; in_key -- one key, decoded, or 0. R0:R1, because a named key is 256
; and above and does not fit a byte.
; ---------------------------------------------------------------------
in_key: CALL in_raw
        TST  R0
        BEQ  .none
        CMP  R0,#128
        BLO  .notnamed
        SUB  R0,#128            ; PS/2 named key: $80+n is K_UP+n, and
        MOV  R1,#1              ;   K_UP is 256, so the high byte is 1
        RET
.notnamed:
        CMP  R0,#27
        BNE  .plain
        ; **A lone Escape is Escape.** Waiting for the rest of a
        ; sequence that is never coming would hang a game's loop on the
        ; one key it is most likely to test for. A terminal sends
        ; ESC [ A in a single burst, so the interrupt has the whole of
        ; it in the ring before anything looks -- an empty ring here
        ; means the user pressed Escape.
        LD   R2,[irhead]
        LD   R3,[irtail]
        CMP  R2,R3
        BEQ  .esc
        CALL in_wait
        CMP  R0,#$5B            ; '['
        BEQ  .final
        CMP  R0,#$4F            ; 'O', which some terminals send
        BNE  .esc
.final: CALL in_wait
        LDW  X,#esctab
.f:     LD   R2,[X]
        TST  R2
        BEQ  .esc               ; ran off the end: not a key we know
        CMP  R2,R0
        BEQ  .hit
        ADDW X,#2
        BRA  .f
.hit:   INCW X
        LD   R0,[X]
        BTST R0,#ESCTIL
        BEQ  .named
        AND  R0,#$7F
        PUSH R0
        CALL in_wait            ; swallow the '~'
        POP  R0
.named: MOV  R1,#1
        RET
.esc:   MOV  R0,#27
.plain: CLR  R1
        RET
.none:  RET

; ---------------------------------------------------------------------
; in_get -- block until a key, blinking the soft cursor while waiting.
;
; The blink is C64-timed: 20 frames a phase, and only while waiting,
; which is also the only time the C64 blinked. The hardware cursor does
; it in silicon in the text modes, so `con_blink` is a no-op there and
; this loop costs a compare.
;
; **The frame counter is read, not counted.** `frames` is what the
; vertical-blank interrupt keeps, so the phase does not drift with how
; long the caller spends between keys.
; ---------------------------------------------------------------------
in_get: CALL in_key
        TST  R0
        BNE  .got
        TST  R1
        BNE  .got
        LD   R0,[CKIND]         ; text modes blink in silicon
        TST  R0
        BEQ  in_get
        LD   R0,[frames]        ; frames - BLB >= 32 ?
        LD   R1,[frames+1]
        LD   R2,[BLB]
        LD   R3,[BLB+1]
        SUB  R0,R2
        SBC  R1,R3
        TST  R1
        BNE  .flip
        CMP  R0,#32
        BLO  in_get
.flip:  LD   R0,[CPHASE]
        XOR  R0,#1
        ST   [CPHASE],R0
        CALL con_blink
        LD   R0,[frames]
        ST   [BLB],R0
        LD   R0,[frames+1]
        ST   [BLB+1],R0
        BRA  in_get
.got:   ; Any key lifts the soft cursor off before whatever happens
        ; next, or it is left drawn over the character the key produces.
        PUSH R0
        PUSH R1
        LD   R0,[CPHASE]
        TST  R0
        BEQ  .out
        CLR  R0
        ST   [CPHASE],R0
        CALL con_blink
.out:   POP  R1
        POP  R0
        RET
