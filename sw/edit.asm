; ---------------------------------------------------------------------
; edit.asm -- the screen is the document.
;
; The C64's arrangement, generalised: a logical line may span several
; screen rows, `CONT` marks which rows are continuations, and pressing
; Return reads the whole logical line back *off the display* rather than
; out of a buffer somebody maintained. Nothing here remembers what was
; typed; the screen is the only copy until the line is entered.
;
; That is why every editing operation has the same three-step shape --
; **read the logical line whole, edit the buffer, write it back** -- and
; why one implementation covers all four modes and all three widths.
; Three rows of 32 columns is the worst case.
;
; Calls downward: `console` for the cells and the cursor, `token` for
; LBUF and the tokeniser, `prog` to store what was typed ([D68]).
; ---------------------------------------------------------------------

EDNUM   = $AC26                 ;: 2 the line number Return just read
EDN     = $AC28                 ;: 1 how many rows the line spans
EDR0    = $AC29                 ;: 1 the logical line's first row
EDIP    = $AC2A                 ;: 1 how far into LBUF the line scan is

        .include "prog.asm"     ; which brings token, num, console, map

; =====================================================================
; Which rows a logical line covers
; =====================================================================

; ed_start -- R0 = the first row of the logical line holding row R0.
ed_start:
        TST  R0
        BEQ  .out
        PUSHW X
.u:     LDW  X,#CONT
        ADDW X,R0
        LD   R1,[X]
        TST  R1
        BEQ  .done
        SUB  R0,#1
        BNE  .u
.done:  POPW X
.out:   RET

; ed_last -- R0 = the last row of the logical line starting at row R0.
ed_last:
        PUSHW X
.d:     LD   R1,[CROWS]
        SUB  R1,#1
        CMP  R0,R1
        BHS  .done
        MOV  R1,R0
        ADD  R1,#1
        LDW  X,#CONT
        ADDW X,R1
        LD   R1,[X]
        TST  R1
        BEQ  .done
        ADD  R0,#1
        BRA  .d
.done:  POPW X
        RET

; =====================================================================
; ed_read -- the logical line holding row R0 into LBUF, trailing spaces
; trimmed. Sets LLEN, and leaves EDR0/EDN describing the rows it came
; from so a caller can write it back.
; =====================================================================
ed_read:
        CALL ed_start
        ST   [EDR0],R0
        CALL ed_last
        LD   R1,[EDR0]
        SUB  R0,R1
        ADD  R0,#1
        ST   [EDN],R0

        CLR  R0
        ST   [LLEN],R0          ; the last non-blank seen, plus one
        LD   R3,[EDR0]          ; the row being read
        CLR  R2                 ; how much is in LBUF
.r:     PUSH R2
        PUSH R3
        MOV  R0,R3
        LD   R1,[EDR0]
        SUB  R0,R1
        LD   R1,[EDN]
        CMP  R0,R1
        POP  R3
        POP  R2
        BHS  .done
        CLR  R1                 ; the column
.c:     PUSH R1
        PUSH R2
        PUSH R3
        MOV  R0,R3
        CALL con_get            ; R0 = the character in that cell
        POP  R3
        POP  R2
        POP  R1
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R2
        ST   [X],R0
        POPW X
        CMP  R0,#$20            ; a blank does not extend the line
        BEQ  .nb
        PUSH R0
        MOV  R0,R2
        ADD  R0,#1
        ST   [LLEN],R0
        POP  R0
.nb:    ADD  R2,#1
        ADD  R1,#1
        PUSH R1
        LD   R0,[CCOLS]
        CMP  R1,R0
        POP  R1
        BLO  .c
        ADD  R3,#1
        BRA  .r
.done:  RET

; =====================================================================
; ed_write -- LBUF back over the rows EDR0/EDN describe, links kept.
; =====================================================================
ed_write:
        LD   R3,[EDR0]
        CLR  R2                 ; how much of LBUF has gone out
.r:     PUSH R2
        PUSH R3
        MOV  R0,R3
        LD   R1,[EDR0]
        SUB  R0,R1
        LD   R1,[EDN]
        CMP  R0,R1
        POP  R3
        POP  R2
        BHS  .done
        CLR  R1                 ; the column
.c:     PUSH R1
        PUSH R2
        PUSH R3
        LD   R0,[LLEN]          ; past the text: blank the rest
        CMP  R2,R0
        BHS  .sp
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R2
        LD   R0,[X]
        POPW X
        BRA  .put
.sp:    MOV  R0,#$20
        ; The pushes above are column, index, row -- so the row is on
        ; top at [SP+0] and the column two below it. Counting from the
        ; wrong end here is the same slip that had prg_find comparing
        ; line numbers against a return address.
.put:   MOV  R2,R0
        MOV  R3,#A_TEXT
        LD   R0,[SP+0]          ; the row, pushed last
        LD   R1,[SP+2]          ; the column, pushed first
        CALL con_put
        POP  R3
        POP  R2
        POP  R1
        ADD  R2,#1
        ADD  R1,#1
        PUSH R1
        LD   R0,[CCOLS]
        CMP  R1,R0
        POP  R1
        BLO  .c
        ; every row after the first is a continuation of the first
        PUSH R3
        LD   R0,[EDR0]
        CMP  R3,R0
        BEQ  .nx
        LDW  X,#CONT
        ADDW X,R3
        MOV  R0,#1
        ST   [X],R0
.nx:    POP  R3
        ADD  R3,#1
        BRA  .r
.done:  RET

; ed_pos -- R0 = where the cursor is within the logical line.
ed_pos: LD   R0,[CCY]
        CALL ed_start
        LD   R1,[CCY]
        SUB  R1,R0              ; rows into the line
        LD   R0,[CCOLS]
        CLR  R2
.m:     TST  R1
        BEQ  .d
        ADD  R2,R0
        SUB  R1,#1
        BRA  .m
.d:     LD   R0,[CCX]
        ADD  R0,R2
        RET

; =====================================================================
; The editing operations. Read, edit, write.
; =====================================================================

; ed_del -- the character under the cursor.
ed_del: LD   R0,[CCY]
        CALL ed_read
        CALL ed_pos
        LD   R1,[LLEN]
        CMP  R0,R1
        BHS  .out               ; past the end: nothing to delete
        MOV  R2,R0              ; slide the tail down one
.s:     MOV  R0,R2
        ADD  R0,#1
        LD   R1,[LLEN]
        CMP  R0,R1
        BHS  .fin
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R0
        LD   R0,[X]
        POPW X
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R2
        ST   [X],R0
        POPW X
        ADD  R2,#1
        BRA  .s
.fin:   LD   R0,[LLEN]
        SUB  R0,#1
        ST   [LLEN],R0
        JMP  ed_write
.out:   RET

; ed_ins -- a space at the cursor, the tail pushed right.
ed_ins: LD   R0,[CCY]
        CALL ed_read
        LD   R0,[LLEN]
        CMP  R0,#80             ; a logical line is 80 characters, always
        BHS  .out
        CALL ed_pos
        MOV  R3,R0              ; where the gap goes
        LD   R2,[LLEN]          ; slide the tail up one, from the top
.s:     CMP  R2,R3
        BLS  .fin
        MOV  R0,R2
        SUB  R0,#1
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R0
        LD   R0,[X]
        POPW X
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R2
        ST   [X],R0
        POPW X
        SUB  R2,#1
        BRA  .s
.fin:   PUSHW X
        LDW  X,#LBUF
        ADDW X,R3
        MOV  R0,#$20
        ST   [X],R0
        POPW X
        LD   R0,[LLEN]
        ADD  R0,#1
        ST   [LLEN],R0
        JMP  ed_write
.out:   RET

; ed_left -- the cursor one left, wrapping to the previous row's end.
; The C64's rule, and nothing at the very home position.
ed_left:
        LD   R0,[CCX]
        TST  R0
        BEQ  .wrap
        SUB  R0,#1
        ST   [CCX],R0
        RET
.wrap:  LD   R0,[CCY]
        TST  R0
        BEQ  .out
        SUB  R0,#1
        ST   [CCY],R0
        CALL con_setrow
        LD   R0,[CCOLS]
        SUB  R0,#1
        ST   [CCX],R0
.out:   RET

; ed_bs -- backspace: left, then delete. At column 0 it only works if
; this row continues the one above, or Return's line would be joined to
; a line it has nothing to do with.
ed_bs:  LD   R0,[CCX]
        TST  R0
        BNE  .go
        LD   R0,[CCY]
        PUSHW X
        LDW  X,#CONT
        ADDW X,R0
        LD   R0,[X]
        POPW X
        TST  R0
        BEQ  .out
.go:    CALL ed_left
        CALL ed_del
        JMP  con_cursor
.out:   RET

; ed_end -- the cursor to the row's edge.
;
; The row's edge and not the last character: scanning for it cost fifty
; bytes that mode 3's CLS needed more.
ed_end: LD   R0,[CCOLS]
        SUB  R0,#1
        ST   [CCX],R0
        JMP  con_cursor

; =====================================================================
; ed_enter -- Return on row R0.
;
; **This is the whole grammar**, and it is BBC BASIC's `SPTSTN`: read
; the line, tokenise it at entry, and look for a line number. A number
; means store it; no number means run it now. One branch.
; =====================================================================
ed_enter:
        CALL ed_read
        ; The cursor lands after the whole LOGICAL line, as on the C64 --
        ; not after the row Return was pressed on.
        LD   R0,[EDR0]
        CALL ed_last
        ST   [CCY],R0
        CALL con_setrow
        CALL con_nl

        CLR  R0
        ST   [EDIP],R0
        CALL ed_skipsp
        LD   R0,[EDIP]
        LD   R1,[LLEN]
        CMP  R0,R1
        BHS  .out               ; a blank line does nothing

        PUSHW X                 ; is it a digit?
        LDW  X,#LBUF
        ADDW X,R0
        LD   R0,[X]
        POPW X
        CALL tok_digit
        BCC  .direct

        ; A line number. `snumi` is `snum` with one seed changed so a
        ; point *ends* the number instead of starting a fraction, which
        ; is what a line number wants -- "10.5" is line 10.
        ; The number goes in EDNUM, not on the stack. An earlier version
        ; pushed it across the position arithmetic and then unwound the
        ; pushes against a `PUSHW Y` that was still outstanding, so the
        ; line was stored under whichever half of a saved pointer came
        ; back first -- every line arrived numbered 0.
        PUSHW Y
        LD   R0,[LLEN]
        LD   R1,[EDIP]
        SUB  R0,R1
        ST   [SDIG],R0
        LDW  Y,#LBUF
        ADDW Y,R1
        CALL snumi
        ST   [EDNUM],R0
        MOV  R0,R1
        ST   [EDNUM+1],R0
        POPW Y
        LD   R0,[LLEN]
        LD   R1,[SDIG]
        SUB  R0,R1
        ST   [EDIP],R0
        ; drop one separating space, so `10 PRINT` stores `PRINT`
        LD   R0,[EDIP]
        LD   R1,[LLEN]
        CMP  R0,R1
        BHS  .shift
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R0
        LD   R1,[X]
        POPW X
        CMP  R1,#$20
        BNE  .shift
        ADD  R0,#1
        ST   [EDIP],R0
.shift: CALL ed_shift
        CALL tok_line
        LD   R0,[EDNUM]
        LD   R1,[EDNUM+1]
        JMP  prg_store
.direct:
        ; No line number: run it now. Commands are ordinary statements,
        ; so this one branch is the entire grammar.
        CALL tok_line
        JMP  ed_direct
.out:   RET

; ed_skipsp -- EDIP forward over spaces.
ed_skipsp:
        LD   R0,[EDIP]
        LD   R1,[LLEN]
        CMP  R0,R1
        BHS  .out
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R0
        LD   R1,[X]
        POPW X
        CMP  R1,#$20
        BNE  .out
        ADD  R0,#1
        ST   [EDIP],R0
        BRA  ed_skipsp
.out:   RET

; ed_shift -- slide LBUF down so the line body starts at 0.
ed_shift:
        CLR  R2
.s:     LD   R0,[EDIP]
        ADD  R0,R2
        LD   R1,[LLEN]
        CMP  R0,R1
        BHS  .done
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R0
        LD   R0,[X]
        POPW X
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R2
        ST   [X],R0
        POPW X
        ADD  R2,#1
        BRA  .s
.done:  MOV  R0,R2
        ST   [LLEN],R0
        CLR  R0
        ST   [EDIP],R0
        RET
