; ---------------------------------------------------------------------
; token.asm -- text to tokens at line entry, and back again for LIST.
;
; A word that is a keyword becomes one byte >= $80; everything else is
; copied. Quoted text and comments are copied whole -- `PRINT "FOR"`
; must not become PRINT <FOR-token>. A number becomes a marker and its
; binary value, which is BBC BASIC's `tknCONST` arrangement and the
; reason an interpreted `FOR` does not re-parse decimal per iteration.
;
; ## What is redesigned rather than ported ([D68])
;
; **The keyword's flags come out of a table.** `sw/tokflag.asm` is
; generated beside `sw/tokens.asm` from the same `TOKTAB`, one byte per
; keyword. `F_VERB` is what makes REM take the rest of the line, so the
; inline REM special-case the compiled `tokenise` carried is gone;
; `F_LINE` is read by RENUMBER rather than here, and is what lets it
; find a line-number reference to rewrite.
;
; **The number parser is `snum`, not a fourth digit loop.** The compiled
; tokeniser had one inline, `number()` had another, `snum` is the
; interpreter's, and `sim/test_lib.py` measured the cost of that in
; bytes. `snum` already parses a fraction and already decides integer or
; float, so the float literal -- `PRINT 1.5`, the last loud gap in
; docs/13-basic.md section 8 -- costs a token and a three-byte store
; rather than a parser.
;
; **Still owed:** `snum` lives in `sw/interp.asm`, so this file calls
; *upward*, which [D68]'s module rule forbids. The parser, `imul16`,
; `negp16` and `sstr` belong in a `num.asm` below both this and the
; interpreter; they are entangled with the float package and moving them
; is its own change. ASM_MOVE_PLAN.md carries it.
; ---------------------------------------------------------------------

; ---- the line, in both forms.
;
; These were `DIM lbuf(127)` and `DIM tbuf(127)` in sw/basic.bas, which
; the compiler turned into `.res` -- 256 bytes of zeros carried inside
; the image and copied out of flash at boot purely to reserve RAM. As
; claims in the storage region they cost the image nothing, which is
; [D67]'s 324-byte eviction happening for the half this module owns.
LBUF    = $A833                 ;: 128 the line being worked on, as text
LLEN    = $A8B3                 ;: 1 how much of it there is
TBUF    = $A8B4                 ;: 128 the same line, tokenised
TLEN    = $A934                 ;: 1 and how long that came out
TOKI    = $A935                 ;: 1 how far along the text the scan is
TOKQ    = $A936                 ;: 1 inside a quoted string

        .include "zp.asm"
        .include "toktab.asm"
        .include "tokens.asm"
        .include "tokflag.asm"
        .include "num.asm"       ; which brings console.asm with it

; =====================================================================
; Character classes
;
; Deliberately inline compares and not the interpreter's `ctab`: that
; table is in sw/interp.asm, and reaching it from here is the same call
; upward the header admits to for `snum`. Four instructions each, and
; they collapse into `ctab` when the shared bottom module exists.
; =====================================================================

; tok_upper -- R0 folded to upper case.
tok_upper:
        CMP  R0,#$61            ; 'a'
        BLO  .out
        CMP  R0,#$7B            ; 'z' + 1
        BHS  .out
        SUB  R0,#32
.out:   RET

; tok_alpha -- carry set if R0 is a letter, either case.
tok_alpha:
        PUSH R0
        CALL tok_upper
        CMP  R0,#$41            ; 'A'
        BLO  .no
        CMP  R0,#$5B            ; 'Z' + 1
        BHS  .no
        POP  R0
        SEC
        RET
.no:    POP  R0
        CLC
        RET

; tok_digit -- carry set if R0 is a digit.
tok_digit:
        CMP  R0,#$30
        BLO  .no
        CMP  R0,#$3A
        BHS  .no
        SEC
        RET
.no:    CLC
        RET

; tok_ident -- carry set if R0 may appear inside a name: a letter, a
; digit, or an underscore.
tok_ident:
        CALL tok_alpha
        BCS  .yes
        CALL tok_digit
        BCS  .yes
        CMP  R0,#$5F            ; '_'
        BEQ  .yes
        CLC
        RET
.yes:   SEC
        RET

; tok_hexd -- carry set if R0 is a hex digit; R1 = its value.
tok_hexd:
        CALL tok_digit
        BCC  .ab
        MOV  R1,R0
        SUB  R1,#$30
        SEC
        RET
.ab:    PUSH R0
        CALL tok_upper
        CMP  R0,#$41            ; 'A'
        BLO  .no
        CMP  R0,#$47            ; 'F' + 1
        BHS  .no
        MOV  R1,R0
        SUB  R1,#55
        POP  R0
        SEC
        RET
.no:    POP  R0
        CLC
        RET

; =====================================================================
; The keyword table
; =====================================================================

; tok_look -- the token for the R2-character word at X, or 0.
;
; A linear walk of TOKTAB, which is what BBC BASIC does too -- its table
; is sorted so the search can leave early on the first letter, and that
; is a speed optimisation for a routine that runs once per line typed.
; The word is folded as it is compared, so `print` and `PRINT` are one
; keyword and the table holds only the upper-case spelling.
tok_look:
        PUSHW Y
        LDW  Y,#TOKTAB
        MOV  R3,#K_PRINT        ; the first entry's token
.e:     LD   R0,[Y]             ; the entry's length, 0 ends the table
        TST  R0
        BEQ  .miss
        CMP  R0,R2
        BNE  .next
        ; Same length: compare the characters.
        PUSHW X
        PUSHW Y
        PUSH R3
        MOV  R3,R2              ; characters left to match
.c:     INCW Y
        LD   R0,[X]
        CALL tok_upper
        LD   R1,[Y]
        CMP  R0,R1
        BNE  .bad
        INCW X
        SUB  R3,#1
        BNE  .c
        POP  R0                 ; matched: R0 is the token
        POPW Y
        POPW X
        POPW Y
        SEC
        RET
.bad:   POP  R3
        POPW Y
        POPW X
.next:  LD   R0,[Y]             ; step over length + that many characters
        ADDW Y,R0
        INCW Y
        ADD  R3,#1
        BRA  .e
.miss:  POPW Y
        CLR  R0
        CLC
        RET

; tok_flags -- R1 = the flags of token R0, or 0 if it is not a keyword.
tok_flags:
        CLR  R1
        CMP  R0,#K_PRINT
        BLO  .out
        PUSHW X
        PUSH R0
        SUB  R0,#K_PRINT
        CMP  R0,#NTOK
        BHS  .off
        LDW  X,#TOKFLG
        ADDW X,R0
        LD   R1,[X]
.off:   POP  R0
        POPW X
.out:   RET

; =====================================================================
; Emitting
; =====================================================================

; tok_byte -- append R0 to TBUF.
;
; No bound test: TBUF is 128 and so is LBUF, and a line can only grow
; where a number shrinks three characters into three bytes -- which it
; cannot do more often than it has characters.
tok_byte:
        PUSHW X
        PUSH R0
        LD   R0,[TLEN]
        LDW  X,#TBUF
        ADDW X,R0
        ADD  R0,#1
        ST   [TLEN],R0
        POP  R0
        ST   [X],R0
        POPW X
        RET

; tok_word -- append T_LIT and the 16-bit value in R0:R1.
tok_word:
        PUSH R1
        PUSH R0
        MOV  R0,#T_LIT
        CALL tok_byte
        POP  R0
        CALL tok_byte
        POP  R0
        JMP  tok_byte

; ---------------------------------------------------------------------
; tok_show -- print the word for token R0, for LIST.
;
; The other direction over the same table, which is why detokenising
; lives here and not in the lister: `TOKTAB` is walked by exactly two
; routines and they are both in this file, so a keyword cannot come back
; spelled differently from the way it went in.
; ---------------------------------------------------------------------
tok_show:
        PUSHW X
        PUSH R3
        LDW  X,#TOKTAB
        MOV  R3,#K_PRINT
.e:     LD   R1,[X]
        TST  R1
        BEQ  .out               ; past the end: print nothing
        CMP  R3,R0
        BEQ  .hit
        ADDW X,R1               ; step over length + that many characters
        INCW X
        ADD  R3,#1
        BRA  .e
.hit:   MOV  R3,R1              ; the length
.c:     INCW X
        PUSH R3
        PUSHW X
        LD   R0,[X]
        CALL con_emit
        POPW X
        POP  R3
        SUB  R3,#1
        BNE  .c
.out:   POP  R3
        POPW X
        RET

; =====================================================================
; Reading the text
; =====================================================================

; tok_atr -- R0 = LBUF[R0].
tok_atr:
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R0
        LD   R0,[X]
        POPW X
        RET

; tok_at -- R0 = the character the scan is on.
tok_at: LD   R0,[TOKI]
        JMP  tok_atr

; tok_take -- copy the character the scan is on, and step over it.
tok_take:
        CALL tok_at
        CALL tok_byte
        LD   R0,[TOKI]
        ADD  R0,#1
        ST   [TOKI],R0
        RET

; tok_more -- carry set while there is text left.
tok_more:
        LD   R0,[TOKI]
        LD   R1,[LLEN]
        CMP  R0,R1
        BHS  .no
        SEC
        RET
.no:    CLC
        RET

; tok_rest -- copy everything left, verbatim. REM and a comment.
tok_rest:
        CALL tok_more
        BCC  .done
        CALL tok_take
        BRA  tok_rest
.done:  RET

; =====================================================================
; tok_line -- LBUF[0..LLEN) into TBUF, setting TLEN.
; =====================================================================
tok_line:
        CLR  R0
        ST   [TLEN],R0
        ST   [TOKI],R0
        ST   [TOKQ],R0
.next:  CALL tok_more
        BCC  .done
        CALL tok_at
        CMP  R0,#$22            ; '"' toggles: quoted text is copied
        BNE  .nq                ;   whole, so PRINT "FOR" keeps its FOR
        LD   R1,[TOKQ]
        XOR  R1,#1
        ST   [TOKQ],R1
.nq:    LD   R1,[TOKQ]
        TST  R1
        BEQ  .code
        CALL tok_take
        BRA  .next
.code:  CMP  R0,#$27            ; a comment runs to the end of the line
        BNE  .c2
        CALL tok_rest
        BRA  .done
.c2:    CALL tok_alpha
        BCS  .word
        CALL tok_digit
        BCS  .num
        CMP  R0,#$2E            ; a number may open with its point: .5
        BEQ  .num
        CMP  R0,#$24            ; '$' and hex digits
        BEQ  .hex
        CALL tok_take
        BRA  .next
.done:  RET

        ; ---- a word.
        ;
        ; **The whole identifier, digits and underscores included** --
        ; not just the letters. Scanning only letters split `x_end` into
        ; `x_` and `end`, and `end` is a keyword, so the tail of the name
        ; turned into a token and LIST gave back something else entirely.
        ;
        ; Bounded by LLEN, and that is not decoration: `shiftlbuf` slides
        ; the line down over its line number and shortens LLEN without
        ; clearing what it left behind, so `20 END` becomes `END` with
        ; `END` still sitting further along. An unbounded scan read
        ; `ENDEND`, matched nothing, and stored six characters where the
        ; END token belonged -- so the interpreter walked off the end of
        ; the program instead of stopping.
.word:  LD   R0,[TOKI]
        MOV  R2,R0              ; scan position
        CLR  R3                 ; and the width so far
.wl:    LD   R0,[LLEN]
        CMP  R2,R0
        BHS  .wsfx
        PUSH R2
        PUSH R3
        MOV  R0,R2
        CALL tok_atr
        CALL tok_ident
        POP  R3
        POP  R2
        BCC  .wsfx
        ADD  R2,#1
        ADD  R3,#1
        BRA  .wl
        ; A trailing `$` or `#` is part of the name, not the start of a
        ; hex literal: the suffix is the type, and it is what keeps `A`,
        ; `A$` and `A#` three different variables. Taken here, before
        ; the `$` arm above can claim it. A bare `$FE70` still parses as
        ; hex, because it does not follow an identifier.
.wsfx:  LD   R0,[LLEN]
        CMP  R2,R0
        BHS  .wgo
        PUSH R2
        PUSH R3
        MOV  R0,R2
        CALL tok_atr
        CMP  R0,#$24            ; '$'
        BEQ  .wsy
        CMP  R0,#$23            ; '#'
        BNE  .wno
.wsy:   POP  R3
        POP  R2
        ADD  R2,#1
        ADD  R3,#1
        BRA  .wgo
.wno:   POP  R3
        POP  R2
.wgo:   ; R3 is the width. Look it up.
        PUSHW X
        LDW  X,#LBUF
        LD   R0,[TOKI]
        ADDW X,R0
        MOV  R2,R3
        PUSH R3
        CALL tok_look
        POP  R3
        POPW X
        BCC  .wplain
        ; A keyword. REM takes the rest of the line with it, so LIST
        ; prints the word back from the token and the comment exactly as
        ; typed, and the interpreter skips the line on one dispatch.
        ; Stored as plain text it reached the assignment handler instead
        ; and every REM was ?SYNTAX.
        PUSH R3
        CALL tok_byte
        CALL tok_flags
        POP  R3
        PUSH R1
        LD   R0,[TOKI]          ; step over the word either way
        ADD  R0,R3
        ST   [TOKI],R0
        POP  R1
        BTST R1,#F_VERB
        BEQ  .next
        CALL tok_rest
        BRA  .done
.wplain:
        ; Not a keyword: copy the characters as they were typed.
        TST  R3
        BEQ  .wone
.wc:    CALL tok_take
        SUB  R3,#1
        BNE  .wc
        BRA  .next
.wone:  CALL tok_take           ; a zero-width word cannot happen, but a
        BRA  .next              ;   scan that made no progress would hang

        ; ---- a number. `snum` is the parser the interpreter uses for
        ; VAL and INPUT, so a typed constant and a typed answer cannot
        ; disagree -- and because it already reads a fraction, `1.5` in
        ; source costs a token here rather than a parser.
.num:   PUSHW Y
        LD   R0,[LLEN]          ; characters it may look at
        LD   R1,[TOKI]
        SUB  R0,R1
        ST   [SDIG],R0
        LDW  Y,#LBUF
        ADDW Y,R1
        CALL snum
        LD   R2,[LLEN]          ; SDIG counts down as it consumes, so
        LD   R3,[SDIG]          ;   what is left says where it stopped
        SUB  R2,R3
        ST   [TOKI],R2
        LD   R2,[STYPE]
        POPW Y
        CMP  R2,#2
        BEQ  .flt
        CALL tok_word
        BRA  .next
        ; A float literal: the marker, then the three packed bytes, laid
        ; down by `fstore` rather than copied out of FACC. FACC is the
        ; *unpacked* accumulator and only fload/fstore may see it -- the
        ; packed form is the same three bytes a float variable holds, so
        ; the literal and the variable cannot drift apart.
.flt:   MOV  R0,#K_FLT
        CALL tok_byte
        PUSHW X
        LDW  X,#TBUF
        LD   R0,[TLEN]
        ADDW X,R0
        ADD  R0,#3
        ST   [TLEN],R0
        CALL fstore
        POPW X
        BRA  .next

        ; ---- `$` and hex digits.
.hex:   LD   R0,[TOKI]
        ADD  R0,#1
        ST   [TOKI],R0
        CLR  R2                 ; the value, R3:R2
        CLR  R3
.hl:    CALL tok_more
        BCC  .hd
        PUSH R2
        PUSH R3
        CALL tok_at
        CALL tok_hexd
        MOV  R0,R1
        POP  R3
        POP  R2
        BCC  .hd
        PUSH R0
        MOV  R0,R2              ; value <<= 4
        MOV  R1,R3
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        ADD  R2,R0
        MOV  R0,#0
        ADC  R3,R0
        LD   R0,[TOKI]
        ADD  R0,#1
        ST   [TOKI],R0
        BRA  .hl
.hd:    MOV  R0,R2
        MOV  R1,R3
        CALL tok_word
        BRA  .next
