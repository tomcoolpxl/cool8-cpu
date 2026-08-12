; ---------------------------------------------------------------------
; prog.asm -- the stored program: find a line, insert one, delete a
; range, list it, renumber it.
;
; A record is `lineno` (2), `len` (1), `len` token bytes, and a zero. The
; terminator is not counted in `len`, so the interpreter can ask "end of
; line?" with one load rather than a 16-bit compare against an end
; pointer it would have to maintain -- and LIST and the moves are
; unaffected by it ([D46]).
;
; Lines are kept in ascending order, so the store is an ordered insert
; into one contiguous run and there is no free list to go wrong.
;
; Calls downward only: `token` to spell a keyword back, `num` to print a
; line number, `console` for the newline ([D68]).
; ---------------------------------------------------------------------

PROGBOT = $0200                 ; the program text starts here
PROGEND = $7CA7                 ;: 2 first free byte above it

        .include "token.asm"    ; which brings num, console and the map

; =====================================================================
; Walking
; =====================================================================

; prg_no -- R0:R1 = the line number of the record at X.
prg_no: LD   R0,[X]
        PUSHW X
        INCW X
        LD   R1,[X]
        POPW X
        RET

; prg_next -- X = the record after the one at X: 4 + its length.
prg_next:
        PUSHW X
        INCW X
        INCW X
        LD   R0,[X]
        POPW X
        ADD  R0,#4
        CLR  R1
        JMP  addx16

; prg_end -- carry set while X is still inside the program. Every
; register survives.
;
; **The branch comes before the pops, and that is the whole point.** An
; earlier version compared, then restored the registers, then branched
; -- and `POP` writes a register, so the flags the comparison set were
; gone by the time anything looked at them. Every walk in this file
; terminated on whatever the last POP happened to leave behind, which
; presented as ranges that would not delete and a renumber that wrote
; one number three times.
prg_end:
        PUSH R2
        PUSH R3
        PUSH R0
        PUSH R1
        MOV  R0,XL
        MOV  R1,XH
        LD   R2,[PROGEND]
        LD   R3,[PROGEND+1]
        SUB  R0,R2
        SBC  R1,R3
        BLO  .in
        POP  R1
        POP  R0
        POP  R3
        POP  R2
        CLC
        RET
.in:    POP  R1
        POP  R0
        POP  R3
        POP  R2
        SEC
        RET

; prg_find -- X = the first record with a number >= R0:R1, or the end.
prg_find:
        PUSH R0
        PUSH R1
        LDW  X,#PROGBOT
.l:     CALL prg_end
        BCC  .out
        PUSHW X
        CALL prg_no
        MOV  R2,R0
        MOV  R3,R1
        POPW X
        ; The wanted number, off the two pushes at entry. **[SP+0] and
        ; [SP+1], not [SP+2]:** a routine reads its *caller's* arguments
        ; at [SP+2] because the return address is on top of them, but
        ; its own pushes are underneath nothing. Reading [SP+2] here
        ; compared every line number against half a return address.
        LD   R1,[SP+0]          ; high, pushed second
        LD   R0,[SP+1]          ; low, pushed first
        SUB  R2,R0              ; record - wanted
        SBC  R3,R1
        BHS  .out               ; >= wanted: this is the one
        CALL prg_next
        BRA  .l
.out:   POP  R1
        POP  R0
        RET

; =====================================================================
; prg_move -- R2:R3 bytes from Y to X, overlapping either way.
;
; Growing a line moves the tail up and shrinking it moves the tail down,
; so the direction has to follow or the copy eats itself.
;
; **The count is tested at the top of the loop, before the borrow is
; propagated.** Testing it after means R2:R3 has already wrapped to
; $FFFF and the loop never ends.
; =====================================================================
prg_move:
        MOV  R0,XL              ; dst - src, to pick the direction
        MOV  R1,YL
        SUB  R0,R1
        MOV  R0,XH
        MOV  R1,YH
        SBC  R0,R1
        BLO  .up
        ; dst above src: point both past their ends and walk down. The
        ; 16-bit add is done in place on each pointer rather than through
        ; addx16, which only knows X.
        ADDW X,R2
        MOV  R0,XH
        ADD  R0,R3
        MOV  XH,R0
        ADDW Y,R2
        MOV  R0,YH
        ADD  R0,R3
        MOV  YH,R0
.dn:    MOV  R0,R2
        OR   R0,R3
        BEQ  .done
        DECW X
        DECW Y
        LD   R0,[Y]
        ST   [X],R0
        SUB  R2,#1
        BCS  .dn
        SUB  R3,#1
        BRA  .dn
.up:    MOV  R0,R2
        OR   R0,R3
        BEQ  .done
        LD   R0,[Y]
        ST   [X],R0
        INCW X
        INCW Y
        SUB  R2,#1
        BCS  .up
        SUB  R3,#1
        BRA  .up
.done:  RET

; =====================================================================
; prg_new -- forget the program.
; =====================================================================
prg_new:
        MOV  R0,#<PROGBOT
        ST   [PROGEND],R0
        MOV  R0,#>PROGBOT
        ST   [PROGEND+1],R0
        RET

; prg_free -- R0:R1 = bytes a program may still grow into.
prg_free:
        MOV  R0,#<USERTOP
        MOV  R1,#>USERTOP
        LD   R2,[PROGEND]
        LD   R3,[PROGEND+1]
        SUB  R0,R2
        SBC  R1,R3
        RET

; =====================================================================
; prg_store -- the line now in TBUF, numbered R0:R1.
;
; Insert, replace or delete, all as one operation: make the hole the
; right size and fill it. An empty TBUF means the hole is zero, which is
; how typing a bare line number deletes a line.
; =====================================================================
; ---------------------------------------------------------------------
; The command scratch: six bytes, shared.
;
; **One block, not one claim per routine.** `prg_store`, `prg_del`,
; `prg_list` and `prg_renum` are all reached from the top level and none
; of them can be running while another is -- there is no path from any
; of them back into another. So they overlay the same six bytes rather
; than owning thirteen between them, which is what a 6502 program does
; with its zero page and what the four registers here make necessary:
; each of these routines has three or four live 16-bit values and there
; are two pointers and four bytes to hold them in.
;
; **The invariant is the whole safety argument, so it is written down**:
; nothing below the top level may use this block, and no routine here
; may call another. `prg_newno` is the one that looks like an exception
; and is not -- it *reads* the start and step `prg_renum` left, and
; writes nothing.
;
; Per-routine claims would have been safer and cost seven more bytes of
; a region that has none to spare in principle; the check in
; `tools/memmap.py` cannot see this invariant, which is exactly why it
; is stated here rather than assumed.
; ---------------------------------------------------------------------
PRGW    = $7CA1                 ;: 6 the top-level commands' scratch

PRGN    = PRGW+0                ; prg_store: the line number
PRGP    = PRGW+2                ;   where it goes
PRGOLD  = PRGW+4                ;   how many bytes were there
PRGNEW  = PRGW+5                ;   and how many are wanted

prg_store:
        ST   [PRGN],R0
        MOV  R0,R1
        ST   [PRGN+1],R0
        LD   R0,[PRGN]
        LD   R1,[PRGN+1]
        CALL prg_find
        MOV  R0,XL
        ST   [PRGP],R0
        MOV  R0,XH
        ST   [PRGP+1],R0

        CLR  R0                 ; how much is there now
        ST   [PRGOLD],R0
        CALL prg_end
        BCC  .sz
        CALL prg_no             ; the record found -- is it this number?
        LD   R2,[PRGN]
        LD   R3,[PRGN+1]
        CMP  R0,R2
        BNE  .sz
        CMP  R1,R3
        BNE  .sz
        PUSHW X
        INCW X
        INCW X
        LD   R0,[X]
        POPW X
        ADD  R0,#4
        ST   [PRGOLD],R0
.sz:    CLR  R0                 ; and how much is wanted
        LD   R1,[TLEN]
        TST  R1
        BEQ  .nw
        MOV  R0,R1
        ADD  R0,#4
.nw:    ST   [PRGNEW],R0

        ; Resize the hole. progend moves by new - old, and the tail
        ; above it moves with it.
        LD   R2,[PRGNEW]
        LD   R3,[PRGOLD]
        CMP  R2,R3
        BEQ  .fill
        PUSHW Y
        LDW  X,[PRGP]           ; destination: the record + new
        LD   R0,[PRGNEW]
        CLR  R1
        CALL addx16
        MOVW Y,X
        LDW  X,[PRGP]           ; source: the record + old
        LD   R0,[PRGOLD]
        CLR  R1
        CALL addx16
        ; X is the source, Y wants to be it and X the destination.
        PUSHW X
        MOVW X,Y
        POPW Y
        ; count = progend - (record + old)
        LD   R2,[PROGEND]
        LD   R3,[PROGEND+1]
        MOV  R0,YL
        MOV  R1,YH
        SUB  R2,R0
        SBC  R3,R1
        CALL prg_move
        POPW Y
        ; progend += new - old
        LD   R0,[PROGEND]
        LD   R1,[PROGEND+1]
        LD   R2,[PRGOLD]
        CLR  R3
        SUB  R0,R2
        SBC  R1,R3
        LD   R2,[PRGNEW]
        CLR  R3
        ADD  R0,R2
        ADC  R1,R3
        ST   [PROGEND],R0
        MOV  R0,R1
        ST   [PROGEND+1],R0

.fill:  LD   R0,[PRGNEW]
        TST  R0
        BEQ  .done              ; a bare line number: the line is gone
        LDW  X,[PRGP]
        LD   R0,[PRGN]
        ST   [X],R0
        INCW X
        LD   R0,[PRGN+1]
        ST   [X],R0
        INCW X
        LD   R0,[TLEN]
        ST   [X],R0
        INCW X
        PUSHW Y
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
.z:     CLR  R0                 ; the end-of-line marker
        ST   [X],R0
        POPW Y
.done:  RET

; =====================================================================
; prg_del -- every line from R0:R1 to R2:R3 inclusive.
; =====================================================================
; **Named scratch, not the stack.** Three live 16-bit values -- the two
; bounds and how big the deletion is -- do not fit four 8-bit registers
; and two pointers, and an earlier draft that juggled them through
; PUSH/POP got the depth wrong in two places.
PRGA    = PRGW+0                ; prg_del, prg_list: the lower bound
PRGB    = PRGW+2                ;   the upper bound
PRGG    = PRGW+4                ;   how many bytes a deletion removes

prg_del:
        ST   [PRGB],R2
        MOV  R2,R3
        ST   [PRGB+1],R2
        CALL prg_find           ; X = the first record at or above R0:R1
        MOV  R0,XL
        ST   [PRGA],R0
        MOV  R0,XH
        ST   [PRGA+1],R0
.l:     CALL prg_end
        BCC  .go
        PUSHW X
        CALL prg_no
        LD   R2,[PRGB]
        LD   R3,[PRGB+1]
        SUB  R2,R0              ; bound - record
        SBC  R3,R1
        POPW X
        BLO  .go                ; past the bound: X is the first to keep
        CALL prg_next
        BRA  .l
.go:    ; gap = X - PRGA, the bytes about to disappear
        MOV  R0,XL
        MOV  R1,XH
        LD   R2,[PRGA]
        LD   R3,[PRGA+1]
        SUB  R0,R2
        SBC  R1,R3
        ST   [PRGG],R0
        MOV  R0,R1
        ST   [PRGG+1],R0
        LD   R0,[PRGG]
        OR   R0,R1
        BEQ  .none              ; nothing matched the range
        ; count = progend - X, then move the tail down over the hole
        LD   R2,[PROGEND]
        LD   R3,[PROGEND+1]
        MOV  R0,XL
        MOV  R1,XH
        SUB  R2,R0
        SBC  R3,R1
        PUSHW Y
        PUSHW X
        POPW Y                  ; source: the first record to keep
        LDW  X,[PRGA]           ; destination: where the deletion began
        CALL prg_move
        POPW Y
        LD   R0,[PROGEND]
        LD   R1,[PROGEND+1]
        LD   R2,[PRGG]
        LD   R3,[PRGG+1]
        SUB  R0,R2
        SBC  R1,R3
        ST   [PROGEND],R0
        MOV  R0,R1
        ST   [PROGEND+1],R0
.none:  RET

; =====================================================================
; prg_list -- every line whose number is in [R0:R1, R2:R3].
; =====================================================================
prg_list:
        ST   [PRGA],R0
        MOV  R0,R1
        ST   [PRGA+1],R0
        ST   [PRGB],R2
        MOV  R0,R3
        ST   [PRGB+1],R0
        LDW  X,#PROGBOT
.l:     CALL prg_end
        BCC  .done
        PUSHW X
        CALL prg_no
        MOV  R2,R0              ; record - lower
        MOV  R3,R1
        LD   R0,[PRGA]
        LD   R1,[PRGA+1]
        SUB  R2,R0
        SBC  R3,R1
        POPW X
        BLO  .skip
        PUSHW X
        CALL prg_no
        MOV  R2,R0
        MOV  R3,R1
        LD   R0,[PRGB]          ; upper - record
        LD   R1,[PRGB+1]
        SUB  R0,R2
        SBC  R1,R3
        POPW X
        BLO  .done              ; past the top of the range: stop
        PUSHW X
        CALL prg_show
        POPW X
.skip:  CALL prg_next
        BRA  .l
.done:  RET

; =====================================================================
; prg_renum -- renumber from R0:R1 in steps of R2.
;
; **This used to corrupt every program it touched.** The compiled
; version rewrote each line's own number and never looked inside the
; tokens, so a `GOTO 30` still said 30 after the line it meant had
; become 100. Nothing in the suite caught it ([D68]).
;
; Two passes, and it is allowed to be slow -- almost nobody runs it, and
; a slow correct RENUM beats a fast wrong one:
;
;   1. walk the program mapping old number -> new, rewriting each
;      record's own number as it goes;
;   2. walk it again, and wherever a keyword carrying `F_LINE` is
;      followed by a literal, put that literal through the same map.
;
; The map is not stored. Pass 2 re-derives a target's new number by
; searching pass 1's own arithmetic: the nth record has number
; start + n*step, so finding the old number's position is a walk and
; the new one is arithmetic. That is O(lines^2) and needs no memory,
; which is the right trade for a command run once in a session.
; =====================================================================
PRGST   = PRGW+0                ; prg_renum: the first new number
PRGSP   = PRGW+2                ;   and the step. prg_newno reads both
                                ;   and writes neither, which is why it
                                ;   may be called from inside the walk.

prg_renum:
        ST   [PRGST],R0
        MOV  R0,R1
        ST   [PRGST+1],R0
        MOV  R0,R2
        ST   [PRGSP],R0

        ; ---- pass 2 first, while the old numbers are still in place:
        ; every line reference is rewritten to what pass 1 is about to
        ; make it. Doing it the other way round would look the new
        ; numbers up in a program that no longer has the old ones.
        LDW  X,#PROGBOT
.p2:    CALL prg_end
        BCC  .p1
        PUSHW X
        CALL prg_fixrefs
        POPW X
        CALL prg_next
        BRA  .p2

        ; ---- pass 1: each record takes its new number.
.p1:    LDW  X,#PROGBOT
        LD   R2,[PRGST]
        LD   R3,[PRGST+1]
.l:     CALL prg_end
        BCC  .done
        ST   [X],R2
        PUSHW X
        INCW X
        ST   [X],R3
        POPW X
        LD   R0,[PRGSP]
        ADD  R2,R0
        MOV  R0,#0
        ADC  R3,R0
        CALL prg_next
        BRA  .l
.done:  RET

; prg_fixrefs -- rewrite the line references in the record at X.
prg_fixrefs:
        PUSHW Y
        MOVW Y,X
        INCW Y
        INCW Y
        LD   R3,[Y]             ; the length
        INCW Y
        CLR  R2                 ; are we expecting a line number?
.c:     TST  R3
        BEQ  .out
        LD   R0,[Y]
        CMP  R0,#T_LIT
        BEQ  .lit
        CMP  R0,#K_FLT
        BEQ  .skip4
        CMP  R0,#$80
        BLO  .plain
        ; a keyword: does a line number follow it?
        PUSH R3
        CALL tok_flags
        POP  R3
        MOV  R2,R1
        AND  R2,#F_LINE
        INCW Y
        SUB  R3,#1
        BRA  .c
.plain: CMP  R0,#$2C            ; a comma continues a list of them
        BEQ  .keep
        CLR  R2                 ; anything else ends the expectation
.keep:  INCW Y
        SUB  R3,#1
        BRA  .c
.skip4: INCW Y
        INCW Y
        INCW Y
        INCW Y
        SUB  R3,#4
        CLR  R2
        BRA  .c
        ; The pushes are R3 then Y, so the pops are Y then R3. Written
        ; the other way round, `POPW Y` took R3 and half of Y and the
        ; reference was rewritten somewhere that was not the literal.
.lit:   TST  R2
        BEQ  .skip3
        PUSH R3
        PUSHW Y
        INCW Y
        LD   R0,[Y]
        INCW Y
        LD   R1,[Y]
        CALL prg_newno          ; R0:R1 = what that line will be called
        POPW Y                  ; ...Y back to the marker
        PUSHW Y
        INCW Y
        ST   [Y],R0
        INCW Y
        ST   [Y],R1
        POPW Y
        POP  R3
.skip3: INCW Y
        INCW Y
        INCW Y
        SUB  R3,#3
        BRA  .c
.out:   POPW Y
        RET

; prg_newno -- the number line R0:R1 will have after the renumber, or
; the number itself if there is no such line (a GOTO into nowhere is
; left alone rather than aimed somewhere arbitrary).
PRGT    = PRGW+3                ; prg_newno: the old number being mapped

prg_newno:
        ST   [PRGT],R0
        MOV  R0,R1
        ST   [PRGT+1],R0
        PUSHW X
        LDW  X,#PROGBOT
        LD   R2,[PRGST]         ; the new number this position will get
        LD   R3,[PRGST+1]
.l:     CALL prg_end
        BCC  .miss
        PUSHW X
        PUSH R2
        PUSH R3
        CALL prg_no             ; R0:R1 = this record's old number
        LD   R2,[PRGT]
        LD   R3,[PRGT+1]
        CMP  R0,R2
        BNE  .no
        CMP  R1,R3
        BNE  .no
        POP  R3                 ; found it: the candidate is the answer
        POP  R2
        POPW X
        MOV  R0,R2
        MOV  R1,R3
        POPW X
        RET
.no:    POP  R3
        POP  R2
        POPW X
        LD   R0,[PRGSP]         ; next position, next new number
        ADD  R2,R0
        MOV  R0,#0
        ADC  R3,R0
        CALL prg_next
        BRA  .l
.miss:  POPW X                  ; no such line: leave the reference alone
        LD   R0,[PRGT]
        LD   R1,[PRGT+1]
        RET

; prg_show -- one record at X, detokenised.
prg_show:
        PUSHW X
        CALL prg_no
        CALL num_put
        MOV  R0,#$20
        CALL con_emit
        POPW X
        PUSHW X
        PUSHW Y
        MOVW Y,X
        INCW Y
        INCW Y
        LD   R3,[Y]             ; the length
        INCW Y
.c:     TST  R3
        BEQ  .end
        LD   R0,[Y]
        CMP  R0,#T_LIT
        BEQ  .lit
        CMP  R0,#K_FLT
        BEQ  .flt
        CMP  R0,#$80
        BHS  .kw
        PUSH R3
        PUSHW Y
        CALL con_emit
        POPW Y
        POP  R3
        INCW Y
        SUB  R3,#1
        BRA  .c
.kw:    PUSH R3
        PUSHW Y
        CALL tok_show
        POPW Y
        POP  R3
        INCW Y
        SUB  R3,#1
        BRA  .c
        ; A binary literal comes back as digits, which is the other half
        ; of what tok_line did on the way in.
.lit:   INCW Y
        LD   R0,[Y]
        INCW Y
        LD   R1,[Y]
        INCW Y
        PUSH R3
        CALL num_put
        POP  R3
        SUB  R3,#3
        BRA  .c
        ; ...and a float through fstr, which is what PRINT renders one
        ; with, so a literal LISTs back exactly as it would print.
.flt:   INCW Y
        PUSHW Y
        MOVW X,Y
        CALL fload
        POPW Y
        INCW Y
        INCW Y
        INCW Y
        PUSH R3
        PUSHW Y
        CALL fstr
        MOVW X,Y
        CALL con_putsn
        POPW Y
        POP  R3
        SUB  R3,#4
        BRA  .c
.end:   POPW Y
        POPW X
        JMP  con_nl
