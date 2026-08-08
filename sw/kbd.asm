; ---------------------------------------------------------------------
; The keyboard, decoded once for both machines that need it.
;
; Set 2 scancodes arrive raw, prefixes and break codes and all, because
; that is what the hardware promised (04-system.md section 4.3) and
; because a table is cheaper here than a state machine is in gates.
;
; This file is included twice: by sw/boot.asm, where it is the monitor's
; keyboard, and by sw/basic.bas, where it is the editor's. It cannot be
; *shared* at run time -- basic.bin ends at $F20A, so 523 bytes of it sit
; under the $F000-$FDFF ROM window, and turning ROMEN on to reach the
; ROM's copy would hide BASIC from itself. Sharing the source is the
; same answer sw/toktab.asm gives, for the same reason.
;
; **It declares no storage.** In the ROM build a `.byte 0` here would
; land in ROM and could never be written, so the includer owns the
; variables and this file only names them:
;
;   kshift  1   either shift is down
;   kbrk    1   the next code is a release
;   kext    1   the next code had an $E0 in front of it
;
; and the same goes for `kdset`/`kdclr`, called on every make and every
; break: sw/basic.bas includes sw/kdown.asm for the real thing, and the
; monitor answers both with a bare RET.
;
; The tables are in keymap.asm, which the includer places where it has
; room -- in the ROM they are up at $FF00, because the code down in
; $F000-$FDFF does not fit with them.
; ---------------------------------------------------------------------

; scancode -- R0 = a raw code, returns a key or 0 for "not a character".
;
; A key is ASCII, or $80+n for one of the eight named keys in extmap.
; $80 and up cannot come out of the keymap -- the BTST below rejects
; every scancode that high -- so the range is free, and it means a named
; key is one byte in a byte-wide ring rather than an ANSI sequence.
scancode:
        PUSH R1
        MOV  R1,R0

        LD   R0,[kbrk]
        TST  R0
        BNE  .brk

        MOV  R0,R1
        CMP  R0,#$F0
        BNE  .n1
        MOV  R0,#1
        ST   [kbrk],R0
        BRA  .none
.n1:    CMP  R0,#$E0
        BNE  .n2
        MOV  R0,#1
        ST   [kext],R0
        BRA  .none

        ; Held, from here on: this is a make code for a real key. The
        ; bitmap is set before the shifts are dealt with, because the
        ; shifts branch away below and would otherwise never be marked.
.n2:    CALL kdset
        MOV  R0,R1
        CMP  R0,#$12
        BEQ  .shon
        CMP  R0,#$59
        BNE  .look
.shon:  MOV  R0,#1
        ST   [kshift],R0
        BRA  .none

        ; A break code: the release of whatever comes after $F0. Only
        ; the shifts matter to the character, and dropping the rest is
        ; what makes auto-repeat work without any effort -- but every
        ; release clears its bit, which is what KEY() reads.
.brk:   CLR  R0
        ST   [kbrk],R0
        ST   [kext],R0
        CALL kdclr
        MOV  R0,R1
        CMP  R0,#$12
        BEQ  .shoff
        CMP  R0,#$59
        BNE  .none
.shoff: CLR  R0
        ST   [kshift],R0
        BRA  .none

        ; An $E0 in front means one of the eight keys that have no
        ; character: the cursors, Home, End, Delete, Insert. They share
        ; their scancodes with the numeric keypad and are told apart
        ; only by the prefix, which is why dropping it -- as this did
        ; before kbd.asm existed -- made cursor-up type an 8.
.look:  LD   R0,[kext]
        TST  R0
        BNE  .ext
        MOV  R0,R1
        BTST R0,#$80
        BNE  .none
        PUSHW X
        LDW  X,#keymap
        ADDW X,R0
        LD   R0,[X]
        POPW X
        TST  R0
        BEQ  .none
        LD   R1,[kshift]
        TST  R1
        BEQ  .done
        CALL shiftit
.done:  POP  R1
        RET
.none:  CLR  R0
        POP  R1
        RET

.ext:   CLR  R0
        ST   [kext],R0
        PUSHW X
        LDW  X,#extmap
.el:    LD   R0,[X]
        TST  R0
        BEQ  .emiss
        INCW X
        CMP  R0,R1
        BEQ  .ehit
        INCW X
        BRA  .el
.ehit:  LD   R0,[X]
        POPW X
        POP  R1
        RET
.emiss: POPW X
        CLR  R0
        POP  R1
        RET

; shiftit -- R0 = the unshifted character, returns the shifted one.
; Letters are a bit; everything else is a short table, which is 42 bytes
; against the 128 a second keymap would cost.
shiftit:
        PUSH R1
        PUSHW X
        CMP  R0,#'a'
        BLO  .sym
        CMP  R0,#'z'+1
        BHS  .sym
        BCLR R0,#$20
        BRA  .sd
.sym:   LDW  X,#shiftmap
.sl:    LD   R1,[X]
        TST  R1
        BEQ  .sd
        INCW X
        CMP  R1,R0
        BEQ  .hit
        INCW X
        BRA  .sl
.hit:   LD   R0,[X]
.sd:    POPW X
        POP  R1
        RET

; ---------------------------------------------------------------------
; The key-down bitmap is the includer's too.
;
; `scancode` calls kdset and kdclr on every make and every break, but
; only the interpreter's KEY() ever reads the result. The monitor
; answers both with a bare RET and spends one byte, rather than 115 of
; a 4 KB ROM on a bitmap nothing in it looks at; sw/basic.bas includes
; sw/kdown.asm and gets the real ones.
; ---------------------------------------------------------------------
