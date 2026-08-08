; ---------------------------------------------------------------------
; asm.asm -- COOL8 assembly, assembled on the machine, for ASM blocks
; inside a BASIC program.
;
; ## It reads characters, not tokens
;
; The editor tokenises everything, including the inside of an ASM block:
; SUB becomes $81, AND $99, OR $9A, XOR $9B, CALL $93 -- and so does any
; label spelled LOOP, NEXT, END, TO, DO, IF, AT, AS or any other TOKTAB
; word. Numbers become $A4 and two binary bytes. Keyword case is lost;
; everything else is kept as typed.
;
; Rather than special-case each collision, `agetc` undoes the
; tokenisation: a byte below $80 comes back as itself, a keyword byte
; comes back as its letters one at a time out of TOKTAB, and $A4 comes
; back as one NUMBER marker with the value in AVAL. Ninety bytes, and
; every collision above disappears at once -- including `.byte`, which
; arrives as '.' followed by the BYTE token, and `.local` labels, which
; only scan as one identifier because this works in characters.
;
; Two things survive and are handled: numbers arrive pre-parsed, which
; is a gift (no digit or hex parsing anywhere), and case must be folded
; because `Loop:` and `LOOP:` have to reach the same symbol.
;
; ## The encoding is arithmetic
;
; Every form is one add -- ALU Rd,Rs is $80 + op*16 + rd*4 + rs, Bcc is
; $70 + cc, load/store is $40/$50/$60 + st*8 + rd*2 + which. So the
; mnemonic table holds only a family and a base field, and thirteen
; encoders cover all 488 reachable encodings. sw/asmtab.asm is generated
; from tools/opcodes.py by tools/mkasmtab.py, which proves the same
; thirteen rules against every encoding before emitting anything.
;
; ## Two passes, not chained forward references
;
; sw/emit.bas threads unresolved references through the operand fields
; because the compiler cannot re-read its input. This can: the source is
; the stored program, so a second pass is a re-walk and costs nothing.
; That buys `label+offset`, which cannot be chained at all, and drops
; about 120 bytes of chain walking. No instruction's length depends on a
; label's value, so both passes lay out identically -- the property
; emit.bas already relies on for its silent pass.
; ---------------------------------------------------------------------

        .include "asmtab.asm"

; ---- operand shapes. The 31 spellings collapse to these plus a
; ---- subfield: which pointer, which half, which index register.
AS_NONE = 0
AS_REG  = 1                     ; R0-R3          sub = 0-3
AS_PTR  = 2                     ; X Y            sub = 0-1
AS_SP   = 3                     ; SP
AS_IMM  = 4                     ; #N
AS_IND  = 5                     ; [X] [Y]        sub = 0-1
AS_IDX  = 6                     ; [X+N] [Y+N]    sub = 0-1
AS_SPN  = 7                     ; [SP+N]
AS_ABS  = 8                     ; [N]
AS_N    = 9                     ; N -- a target or a bare address
AS_HALF = 10                    ; XL XH YL YH    sub = 0-3
AS_RIDX = 11                    ; [X+Rn] [Y+Rn]  sub = isY*4 + n
AS_POST = 12                    ; [X+] [Y+]      sub = 0-1
AS_PRE  = 13                    ; [-X] [-Y]      sub = 0-1

; ---- token classes out of atok
AT_EOL  = 0
AT_NUM  = 1
AT_ID   = 2
AT_PUNC = 3

; The page 0 map and the error codes are in sw/zp.asm, which the
; including file supplies once.
;
; The symbol table is 7 bytes an entry -- five significant characters
; and a word -- and lives in the user area, not page 0; ASYMS points at
; it. Five rather than four because .done1 and .done2 key identically
; at four, and a silent collision is the one thing a byte-exact gate
; exists to prevent.
ASYMSZ  = 7
AMAXSYM = 64

; ---------------------------------------------------------------------
; agetc -- the next character of the block, undoing tokenisation.
;
; $00 means end of line and leaves Y on the terminator; $01 means a
; number, with the value already in AVAL. No real source holds either.
; ---------------------------------------------------------------------
agetc:  LD   R0,[AKLEN]
        BEQ  .fresh
        SUB  R0,#1              ; still expanding a keyword
        ST   [AKLEN],R0
        LD   R0,[AKSRC]
        MOV  XL,R0
        LD   R0,[AKSRC+1]
        MOV  XH,R0
        LD   R0,[X]
        INCW X
        MOV  R1,XL
        ST   [AKSRC],R1
        MOV  R1,XH
        ST   [AKSRC+1],R1
        RET
.fresh: LD   R0,[Y]
        BEQ  .eol
        INCW Y
        CMP  R0,#$A4            ; K_NUM
        BEQ  .num
        CMP  R0,#$80
        BCC  .plain
        CALL atkexp             ; a keyword: expand it and take its first
        BRA  agetc
.plain: RET
.num:   LD   R0,[Y]
        ST   [AVAL],R0
        INCW Y
        LD   R0,[Y]
        ST   [AVAL+1],R0
        INCW Y
        MOV  R0,#1
        RET
.eol:   CLR  R0
        RET

; atkexp -- point AKSRC/AKLEN at TOKTAB entry (R0 - $80).
atkexp: SUB  R0,#$80
        LDW  X,#TOKTAB
.sk:    CMP  R0,#0
        BEQ  .at
        LD   R1,[X]             ; length, then that many characters
        INCW X
        ADDW X,R1
        SUB  R0,#1
        BRA  .sk
.at:    LD   R1,[X]
        ST   [AKLEN],R1
        INCW X
        MOV  R1,XL
        ST   [AKSRC],R1
        MOV  R1,XH
        ST   [AKSRC+1],R1
        RET

; aupper -- R0 folded to upper case.
aupper: CMP  R0,#$61            ; 'a'
        BCC  .no
        CMP  R0,#$7B            ; past 'z'
        BCS  .no
        SUB  R0,#$20
.no:    RET

; aisid -- C clear if R0 can appear inside an identifier.
; Letters, digits, underscore and a dot -- the dot because a local label
; is .name and the whole thing has to scan as one word.
aisid:  CMP  R0,#$2E            ; '.'
        BEQ  .yes
        CMP  R0,#$5F            ; '_'
        BEQ  .yes
        CMP  R0,#$30            ; '0'
        BCC  .no
        CMP  R0,#$3A            ; past '9'
        BCC  .yes
        CALL aupper
        CMP  R0,#$41            ; 'A'
        BCC  .no
        CMP  R0,#$5B            ; past 'Z'
        BCS  .no
.yes:   CLC
        RET
.no:    SEC
        RET

; ---------------------------------------------------------------------
; atok -- one token. Class into ATK, and:
;
;   AT_NUM   value in AVAL
;   AT_ID    ANAME (5, upper, space padded), AKEY, ANLEN
;   AT_PUNC  the character in ACH
;
; ACH always holds the character the scanner stopped on, so a caller
; that wants the punctuation does not have to ask twice.
; ---------------------------------------------------------------------
atok:   LD   R0,[ACH]
        BNE  .have
        CALL agetc              ; nothing pushed back: take a fresh one
        ST   [ACH],R0
.have:  LD   R0,[ACH]
        CMP  R0,#$20            ; a space
        BNE  .go
        CLR  R0                 ; drop it and look again
        ST   [ACH],R0
        BRA  atok
.go:    CMP  R0,#0
        BEQ  .eol
        CMP  R0,#1
        BEQ  .num
        CMP  R0,#$3B            ; ';' -- a comment to end of line
        BEQ  .cmt
        CMP  R0,#$27            ; a quote comment, which tokenise keeps
        BEQ  .cmt
        CALL aisid
        BCC  .id
        MOV  R0,#AT_PUNC        ; punctuation: leave it in ACH
        ST   [ATK],R0
        RET
.eol:   MOV  R0,#AT_EOL
        ST   [ATK],R0
        RET
.cmt:   CLR  R0                 ; swallow the rest of the line
        ST   [AKLEN],R0
.cm2:   LD   R0,[Y]
        BEQ  .cmz
        INCW Y
        BRA  .cm2
.cmz:   CLR  R0
        ST   [ACH],R0
        MOV  R0,#AT_EOL
        ST   [ATK],R0
        RET
.num:   CLR  R0
        ST   [ACH],R0
        MOV  R0,#AT_NUM
        ST   [ATK],R0
        RET

; ---- an identifier: up to five significant characters, plus the key
.id:    CLR  R0
        ST   [ANLEN],R0
        LDW  X,#ANAME           ; blank the five
        MOV  R1,#5
        MOV  R0,#$20
.ib:    ST   [X],R0
        INCW X
        SUB  R1,#1
        BNE  .ib
.iloop: LD   R0,[ACH]
        CALL aisid
        BCS  .idone
        CALL aupper
        PUSH R0
        LD   R1,[ANLEN]
        CMP  R1,#5              ; keep only the first five
        BCC  .keep
        POP  R0
        BRA  .ibump
.keep:  LDW  X,#ANAME
        ADDW X,R1
        POP  R0
        ST   [X],R0
.ibump: LD   R1,[ANLEN]
        CMP  R1,#0
        BNE  .not0
        ST   [AKEY],R0          ; the first character
.not0:  CMP  R1,#1
        BNE  .not1
        ST   [AKEY+1],R0        ; the second
.not1:  ST   [AKEY+2],R0        ; and the last, overwritten as we go
        ADD  R1,#1
        ST   [ANLEN],R1
        CALL agetc              ; next character of the word
        ST   [ACH],R0
        BRA  .iloop
.idone: LD   R1,[ANLEN]
        CMP  R1,#1              ; a one-character name has no second
        BNE  .i2
        MOV  R0,#$20
        ST   [AKEY+1],R0
.i2:    MOV  R0,#AT_ID
        ST   [ATK],R0
        RET

; anext -- consume the token in hand, so atok fetches a new one.
anext:  LD   R0,[ATK]
        CMP  R0,#AT_PUNC
        BNE  .n1
        CLR  R0                 ; punctuation lives in ACH; drop it
        ST   [ACH],R0
.n1:    RET

; ---------------------------------------------------------------------
; The symbol table: five significant characters and a word, 7 bytes an
; entry, in the user area rather than page 0.
;
; Five and not four because .done1 and .done2 key identically at four,
; and a collision here is a silently wrong assembly -- the one failure
; a byte-exact gate exists to prevent. Linear search: 64 entries is a
; few hundred clocks and this runs once, at RUN.
; ---------------------------------------------------------------------

; asymptr -- X = the start of entry R0.
asymptr:
        MOV  R1,#ASYMSZ
        MUL  R0,R1              ; X = R0 * 7, and MUL leaves both alone
        LD   R0,[ASYMS]
        MOV  R1,XL
        ADD  R1,R0
        MOV  XL,R1
        LD   R0,[ASYMS+1]
        MOV  R1,XH
        ADC  R1,R0
        MOV  XH,R1
        RET

; asymfind -- ANAME in the table? C clear and the value in R0:R1.
asymfind:
        LD   R0,[ANSYM]
        BEQ  .miss
        CLR  R0
.each:  PUSH R0
        CALL asymptr
        PUSHW Y
        LDW  Y,#ANAME
        MOV  R1,#5
.cmp:   LD   R0,[X]
        INCW X
        LD   R2,[Y+]
        SUB  R0,R2
        BNE  .no
        SUB  R1,#1
        BNE  .cmp
        POPW Y                  ; a hit: the value follows the name
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        DECW X                  ; leave X on the value, for asymdef
        POP  R2
        CLC
        RET
.no:    POPW Y
        POP  R0
        ADD  R0,#1
        LD   R1,[ANSYM]
        CMP  R0,R1
        BCC  .each
.miss:  SEC
        RET

; asymdef -- ANAME takes the value R0:R1, defined or redefined.
asymdef:
        PUSH R1
        PUSH R0
        CALL asymfind
        BCC  .set               ; already there: pass 2 rewrites it
        LD   R0,[ANSYM]
        CMP  R0,#AMAXSYM
        BCC  .room
        MOV  R0,#E_AFULL
        ST   [ERR],R0
        POP  R0
        POP  R1
        RET
.room:  CALL asymptr            ; X = the new entry
        PUSHW Y
        LDW  Y,#ANAME
        MOV  R1,#5
.cp:    LD   R0,[Y+]
        ST   [X],R0
        INCW X
        SUB  R1,#1
        BNE  .cp
        POPW Y
        LD   R0,[ANSYM]
        ADD  R0,#1
        ST   [ANSYM],R0
.set:   POP  R0                 ; X points at the value either way
        POP  R1
        ST   [X],R0
        INCW X
        ST   [X],R1
        RET

; ---------------------------------------------------------------------
; avalue -- a value into R0:R1.
;
;   value := ['-' | '<' | '>'] term { ('+' | '-') term }
;   term  := <number> | <name> | '*'
;
; Left to right, no precedence, no parentheses. cool8asm.py has a full
; precedence-climbing evaluator with shifts and masks; an operand inside
; an ASM block is a number, a label, or label+offset, and the difference
; is about 300 bytes.
;
; An unknown name is zero on pass 1 -- that is what the second pass is
; for -- and an error on pass 2.
; ---------------------------------------------------------------------
avalue: CLR  R2                 ; R2: 1 negate, 2 low byte, 3 high byte
        LD   R0,[ATK]
        CMP  R0,#AT_PUNC
        BNE  .first
        LD   R0,[ACH]
        CMP  R0,#$2D            ; '-'
        BNE  .lo
        MOV  R2,#1
        BRA  .eat
.lo:    CMP  R0,#$3C            ; '<'
        BNE  .hi
        MOV  R2,#2
        BRA  .eat
.hi:    CMP  R0,#$3E            ; '>'
        BNE  .first
        MOV  R2,#3
.eat:   PUSH R2
        CLR  R0
        ST   [ACH],R0
        CALL atok
        POP  R2
.first: PUSH R2
        CALL aterm
        POP  R2
        PUSH R2
.rest:  PUSH R1                 ; the running total
        PUSH R0
        CALL atok
        LD   R0,[ATK]
        CMP  R0,#AT_PUNC
        BNE  .end
        LD   R0,[ACH]
        CMP  R0,#$2B            ; '+'
        BEQ  .add
        CMP  R0,#$2D
        BEQ  .sub
        BRA  .end
.add:   CLR  R0
        ST   [ACH],R0
        CALL atok
        CALL aterm
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        ADD  R0,R2
        ADC  R1,R3
        BRA  .rest
.sub:   CLR  R0
        ST   [ACH],R0
        CALL atok
        CALL aterm
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        SUB  R0,R2
        SBC  R1,R3
        BRA  .rest
.end:   POP  R0
        POP  R1
        POP  R2                 ; the prefix, applied last
        CMP  R2,#1
        BNE  .nlo
        MOV  R2,R0              ; negate
        MOV  R3,R1
        CLR  R0
        CLR  R1
        SUB  R0,R2
        SBC  R1,R3
        RET
.nlo:   CMP  R2,#2
        BNE  .nhi
        CLR  R1                 ; low byte
        RET
.nhi:   CMP  R2,#3
        BNE  .done
        MOV  R0,R1              ; high byte
        CLR  R1
.done:  RET

; aterm -- a number, a name, or '*' for the current address.
aterm:  LD   R0,[ATK]
        CMP  R0,#AT_NUM
        BNE  .name
        LD   R0,[AVAL]
        LD   R1,[AVAL+1]
        RET
.name:  CMP  R0,#AT_ID
        BNE  .star
        CALL asymfind
        BCC  .got
        LD   R0,[APASS]         ; unknown: fine while laying out
        BEQ  .zero
        MOV  R0,#E_ASYM
        ST   [ERR],R0
.zero:  CLR  R0
        CLR  R1
.got:   RET
.star:  CMP  R0,#AT_PUNC
        BNE  .bad
        LD   R0,[ACH]
        CMP  R0,#$2A            ; '*' -- here
        BNE  .bad
        CLR  R0
        ST   [ACH],R0
        LD   R0,[ACP]
        LD   R1,[ACP+1]
        RET
.bad:   MOV  R0,#E_ASYN
        ST   [ERR],R0
        CLR  R0
        CLR  R1
        RET

; ---------------------------------------------------------------------
; aregof -- is ANAME a register? C clear, shape in R0 and subfield R1.
; ---------------------------------------------------------------------
aregof: LD   R0,[ANLEN]
        CMP  R0,#1
        BEQ  .one
        CMP  R0,#2
        BEQ  .two
        SEC
        RET
.one:   LD   R0,[ANAME]
        CMP  R0,#$58            ; 'X'
        BEQ  .x
        CMP  R0,#$59            ; 'Y'
        BEQ  .y
        SEC
        RET
.x:     MOV  R0,#AS_PTR
        CLR  R1
        CLC
        RET
.y:     MOV  R0,#AS_PTR
        MOV  R1,#1
        CLC
        RET
.two:   LD   R0,[ANAME]
        CMP  R0,#$52            ; 'R'
        BEQ  .rn
        CMP  R0,#$53            ; 'S' -- SP
        BEQ  .sp
        CMP  R0,#$58            ; 'X' -- XL or XH
        BEQ  .half
        CMP  R0,#$59            ; 'Y'
        BEQ  .half
        SEC
        RET
.rn:    LD   R1,[ANAME+1]
        SUB  R1,#$30            ; '0'
        CMP  R1,#4
        BCS  .no
        MOV  R0,#AS_REG
        CLC
        RET
.sp:    LD   R1,[ANAME+1]
        CMP  R1,#$50            ; 'P'
        BNE  .no
        MOV  R0,#AS_SP
        CLR  R1
        CLC
        RET
.half:  SUB  R0,#$58            ; X -> 0, Y -> 1
        SHL  R0
        LD   R1,[ANAME+1]
        CMP  R1,#$4C            ; 'L'
        BEQ  .hl
        CMP  R1,#$48            ; 'H'
        BNE  .no
        ADD  R0,#1
.hl:    MOV  R1,R0              ; XL=0 XH=1 YL=2 YH=3, as page 2 wants
        MOV  R0,#AS_HALF
        CLC
        RET
.no:    SEC
        RET
