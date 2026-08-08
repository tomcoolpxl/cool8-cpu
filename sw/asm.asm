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
; ## Where the size went, measured
;
; 2,521 bytes of code and 313 of table, against a plan that said
; 1,600-2,170 for both. The estimate was optimistic about the encoders
; and nothing else: 1.8-2.1 bytes an instruction held, but each `if` in
; mkasmtab.py's rule() becomes three or four instructions here, not one,
; because the operand *shape* has to be validated as well as encoded --
; and it has to be, or `MOV [X],R0` emits something instead of saying
; no.
;
; What came back out, once it was measured rather than guessed:
;
;   84  per-routine trampolines to `aerr` and `asyn`. An inverted branch
;       plus a JMP is five bytes at every site; a local `JMP aerr` is
;       three once and two at each site. Only the four routines too long
;       to reach one still use the macro.
;   46  INC/DEC, PUSH/POP and the page 2 unary group are all
;       K + base*4 + d over one register, so they share `ek4d`, and
;       `areg1` is the operand check four encoders were repeating.
;   23  AEXTRA became bit flags -- bit 0 the operand, bit 1 the width --
;       so `aemit` computes one address instead of branching four ways.
;   20  `avalt`, the value capture five arms of `aoper` had in common.
;
; What was tried and left alone: moving `aoper`'s pointer subfield from
; the stack into page 0. There is no zero-page addressing mode
; ([D6](../docs/01-decisions.md)), so a byte there costs three bytes to
; touch and a stack slot costs one. The PUSH/POP pairs are already the
; cheap form.
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

; ---- what trails the opcode. The encoders set AEXTRA; `eb` reads it.
;
; Which operand the value comes from is part of the code rather than a
; rule, because it genuinely varies: `LD R0,[X+5]` takes it from the
; second operand and `ST [X+5],R0` from the first, and so do
; `LDW X,#w` against `STW [w],X`.
; Bit 0 picks the operand and bit 1 the width, so `aemit` computes one
; address instead of branching four ways. Bit 2 only marks "there is
; one", which keeps AX_NONE zero and the test a single BEQ.
AX_NONE = 0
AX_B0   = 4                     ; one byte, from AV0
AX_B1   = 5                     ; one byte, from AV1
AX_W0   = 6                     ; two bytes, from AV0
AX_W1   = 7                     ; two bytes, from AV1
AX_REL  = 8                     ; one byte, AV0 relative to the next pc

; ---- the 16-bit block is the one corner that is not arithmetic.
;
; tools/mkasmtab.py carries it as a dict for the same reason, and
; sw/disasm.asm bakes the operand text into w16_ops going the other way.
; Fifteen entries map a whole operand signature onto $60+index:
;
;     base | shape0<<4 | shape1 | sub0<<4 | sub1 | AX_*
;
; and the four irregular families around it are handled in code, not
; here: INCW/DECW/PUSHW/POPW ($38+), ADDW X|Y,#w (page 2 $2C), and
; ADDW/SUBW X|Y,Rn (page 2 $70/$78).

; The page 0 map and the error codes are in sw/zp.asm, which the
; including file supplies once. There is no symbol table here and no
; state for one: labels are BASIC variables, in the name table
; sw/interp.asm owns.

; ---- A conditional branch reaches +/-127 bytes and the operand parser
; ---- is longer than that, so the error exits are out of reach from
; ---- most of it. sw/disasm.asm hit this first and solved it the same
; ---- way: invert the test and let an unconditional JMP carry the
; ---- distance. The assembler names the overshoot, so the need for
; ---- these is measured rather than guessed at.
.macro  JNE  t
        BEQ  @over
        JMP  \t
@over:
.endm
.macro  JEQ  t
        BNE  @over
        JMP  \t
@over:
.endm
.macro  JCS  t
        BCC  @over
        JMP  \t
@over:
.endm

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

; aisid -- C clear if R0 can appear inside an identifier.
;
; `nisid` in sw/interp.asm decides everything except the dot, which is
; here because a local label is `.name` and the whole thing has to scan
; as one word. BASIC's own names must not take a dot, so the two rules
; differ by exactly this and share the rest. `nupper` does the folding.
aisid:  CMP  R0,#$2E            ; '.'
        BEQ  .yes
        JMP  nisid
.yes:   CLC
        RET

; ---------------------------------------------------------------------
; atok -- one token. Class into ATK, and:
;
;   AT_NUM   value in AVAL
;   AT_ID    NBUF and NLEN, folded upper -- the name table's own shape
;            -- plus AKEY, the mnemonic table's three bytes
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

; ---- an identifier: into NBUF and NLEN, which is the shape the name
; ---- table wants, plus the three-byte key the mnemonic table wants.
; ---- NBUF is not blanked: nlook compares the length first.
.id:    CLR  R0
        ST   [NLEN],R0
.iloop: LD   R0,[ACH]
        CALL aisid
        BCS  .idone
        CALL nupper
        PUSH R0
        LD   R1,[NLEN]
        CMP  R1,#NSIG           ; keep only the significant ones
        BCC  .keep
        POP  R0
        BRA  .ibump
.keep:  LDW  X,#NBUF
        ADDW X,R1
        POP  R0
        ST   [X],R0
.ibump: LD   R1,[NLEN]
        CMP  R1,#0
        BNE  .not0
        ST   [AKEY],R0          ; the first character
.not0:  CMP  R1,#1
        BNE  .not1
        ST   [AKEY+1],R0        ; the second
.not1:  ST   [AKEY+2],R0        ; and the last, overwritten as we go
        ADD  R1,#1
        ST   [NLEN],R1
        CALL agetc              ; next character of the word
        ST   [ACH],R0
        BRA  .iloop
.idone: LD   R1,[NLEN]
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
; Symbols. There are none: a label is a BASIC variable.
;
; [D45](../docs/01-decisions.md) -- BBC BASIC's design, where `.label`
; assigns the program counter to the variable of that name and the
; assembler carries no symbol table at all. Here that means `nfind` and
; `nlook` in sw/interp.asm, the same name table `A` and `COUNT` live in,
; which buys three things: 448 bytes of RAM that a private table would
; have wanted, `CALL other_block_label` across blocks for nothing, and
; symbols that are still there at run time for I5's `h_call`.
;
; The consequence worth knowing is that an assembler label and a BASIC
; variable of the same name are one variable. That is BBC BASIC's
; behaviour too, and it is how data crosses between an ASM block and the
; program around it.
;
; The scanner fills NBUF and NLEN, which is exactly what nfind wants, so
; there is no copying between two shapes of name either.
; ---------------------------------------------------------------------

; alabel -- the name in NBUF takes the current address.
alabel: CALL nfind              ; X on its value, created if new
        LD   R0,[ACP]
        ST   [X],R0
        INCW X
        LD   R0,[ACP+1]
        ST   [X],R0
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
        ; A name is looked up but never created here. `nlook` rather
        ; than `nfind` is the whole point: if a reference defined the
        ; symbol at zero, pass 1 would create it and pass 2 would find
        ; it, and an undefined label would assemble to zero in silence
        ; instead of saying so.
.name:  CMP  R0,#AT_ID
        BNE  .star
        CALL nlook
        BCS  .undef
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        RET
.undef: LD   R0,[APASS]         ; unknown: fine while laying out
        BEQ  .zero
        MOV  R0,#E_ASYM
        ST   [ERR],R0
.zero:  CLR  R0
        CLR  R1
        RET
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
; aregof -- is the name in NBUF a register? C clear, shape in R0 and
; subfield R1.
; ---------------------------------------------------------------------
aregof: LD   R0,[NLEN]
        CMP  R0,#1
        BEQ  .one
        CMP  R0,#2
        BEQ  .two
        SEC
        RET
.one:   LD   R0,[NBUF]
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
.two:   LD   R0,[NBUF]
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
.rn:    LD   R1,[NBUF+1]
        SUB  R1,#$30            ; '0'
        CMP  R1,#4
        BCS  .no
        MOV  R0,#AS_REG
        CLC
        RET
.sp:    LD   R1,[NBUF+1]
        CMP  R1,#$50            ; 'P'
        BNE  .no
        MOV  R0,#AS_SP
        CLR  R1
        CLC
        RET
.half:  SUB  R0,#$58            ; X -> 0, Y -> 1
        SHL  R0
        LD   R1,[NBUF+1]
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

; aadv -- consume the token in hand and fetch the next.
aadv:   CALL anext
        JMP  atok

; aclose -- the ']' that ends an indirect operand.
aclose: LD   R0,[ATK]
        CMP  R0,#AT_PUNC
        BNE  .asyn
        LD   R0,[ACH]
        CMP  R0,#$5D            ; ']'
        BNE  .asyn
        JMP  aadv
.asyn:  JMP  asyn

; avalt -- a value, captured where astore will look for it. Five arms
; of aoper wanted the same three instructions.
avalt:  CALL avalue
        ST   [AVT],R0
        ST   [AVT+1],R1
        RET

asyn:   MOV  R0,#E_ASYN
        ST   [ERR],R0
        CLR  R0
        CLR  R1
        RET

; ---------------------------------------------------------------------
; aoper -- one operand: shape in R0, subfield in R1, value in AVT.
;
; The thirty-one spellings collapse to fourteen shapes and a subfield --
; which pointer, which half, which index register -- and the encoders
; then switch on the shape *pair*. That is what makes them arithmetic
; rather than a table: `LD R0,[X+5]` and `ST [Y+5],R3` reach the same
; four instructions with different addends.
;
; A '-' inside brackets is deliberately left for `avalue` to read as its
; own negate prefix, because that is what makes `[X-3+1]` mean -(3+1),
; the same as tools/cool8asm.py's `-(rest)`.
; ---------------------------------------------------------------------
aoper:  CLR  R0
        ST   [AVT],R0
        ST   [AVT+1],R0
        LD   R0,[ATK]
        CMP  R0,#AT_PUNC
        BEQ  .punc
        CMP  R0,#AT_ID
        BNE  .val               ; a number: a bare value
        CALL aregof
        BCS  .val               ; an ordinary name: a value
        PUSH R0
        PUSH R1
        CALL aadv               ; step past the register's name
        POP  R1
        POP  R0
        RET
.val:   CALL avalt
        MOV  R0,#AS_N
        CLR  R1
        RET
.punc:  LD   R0,[ACH]
        CMP  R0,#$23            ; '#'
        BEQ  .imm
        CMP  R0,#$5B            ; '['
        BEQ  .ind
        BRA  .val               ; '-' '<' '>' begin a value
.imm:   CLR  R0
        ST   [ACH],R0
        CALL atok
        CALL avalt
        MOV  R0,#AS_IMM
        CLR  R1
        RET

        ; ---- [ ... ]
.ind:   CLR  R0
        ST   [ACH],R0
        CALL atok
        LD   R0,[ATK]
        CMP  R0,#AT_ID
        BEQ  .ireg
        CMP  R0,#AT_PUNC
        BNE  .iabs
        LD   R0,[ACH]
        CMP  R0,#$2D            ; [-X] and [-Y]
        BNE  .iabs
        CALL aadv
        CALL aregof
        JCS  asyn
        CMP  R0,#AS_PTR
        JNE  asyn
        MOV  R2,R1
        PUSH R2
        CALL aadv
        CALL aclose
        POP  R1
        MOV  R0,#AS_PRE
        RET
.ireg:  CALL aregof
        BCS  .iabs              ; a label: an absolute address
        CMP  R0,#AS_PTR
        BEQ  .iptr
        CMP  R0,#AS_SP
        JEQ  .isp
        JMP  asyn
.iabs:  CALL avalt
        CALL aclose
        MOV  R0,#AS_ABS
        CLR  R1
        RET

        ; ---- [X] [X+] [X+5] [X-5] [X+R2]
.iptr:  MOV  R2,R1              ; 0 = X, 1 = Y
        PUSH R2
        CALL aadv
        POP  R2
        LD   R0,[ATK]
        CMP  R0,#AT_PUNC
        JNE  asyn
        LD   R0,[ACH]
        CMP  R0,#$5D            ; [X]
        BEQ  .iplain
        CMP  R0,#$2D            ; [X-5]: the '-' is avalue's prefix
        BEQ  .idisp
        CMP  R0,#$2B
        BNE  .asyn
        PUSH R2
        CALL aadv               ; past the '+'
        POP  R2
        LD   R0,[ATK]
        CMP  R0,#AT_ID
        BEQ  .irx
        CMP  R0,#AT_PUNC
        BNE  .idisp
        LD   R0,[ACH]
        CMP  R0,#$5D            ; [X+]
        BNE  .idisp
        PUSH R2
        CALL aadv
        POP  R1
        MOV  R0,#AS_POST
        RET
.iplain:
        PUSH R2
        CALL aadv
        POP  R1
        MOV  R0,#AS_IND
        RET
.irx:   PUSH R2
        CALL aregof
        POP  R2
        BCS  .idisp             ; a label, not R0-R3
        CMP  R0,#AS_REG
        BNE  .idisp
        MOV  R0,R2              ; sub = isY*4 + n, as page 2 indexes it
        SHL  R0
        SHL  R0
        ADD  R0,R1
        MOV  R2,R0
        PUSH R2
        CALL aadv
        CALL aclose
        POP  R1
        MOV  R0,#AS_RIDX
        RET
.idisp: PUSH R2
        CALL avalt
        CALL aclose
        POP  R1
        MOV  R0,#AS_IDX
        RET

        ; ---- [SP+n]
.isp:   CALL aadv
        LD   R0,[ATK]
        CMP  R0,#AT_PUNC
        BNE  .asyn
        LD   R0,[ACH]
        CMP  R0,#$2D            ; [SP-n], the '-' left for avalue
        BEQ  .isp2
        CMP  R0,#$2B
        BNE  .asyn
        CALL aadv
.isp2:  CALL avalt
        CALL aclose
        MOV  R0,#AS_SPN
        CLR  R1
        RET
.asyn:  JMP  asyn

; astore -- file R0/R1/AVT as operand R2 (0 for the first, 4 for the
; second). AOP0..AV0 and AOP1..AV1 are four bytes apart on purpose.
astore: PUSHW X
        LDW  X,#AOP0
        ADDW X,R2
        ST   [X],R0
        INCW X
        ST   [X],R1
        INCW X
        LD   R0,[AVT]
        ST   [X],R0
        INCW X
        LD   R0,[AVT+1]
        ST   [X],R0
        POPW X
        RET

; aopers -- none, one or two operands, into the two slots.
aopers: CLR  R0
        ST   [ANOPS],R0
        LD   R0,[ATK]
        CMP  R0,#AT_EOL
        BEQ  .none
        CALL aoper
        CLR  R2
        CALL astore
        MOV  R0,#1
        ST   [ANOPS],R0
        LD   R0,[ATK]
        CMP  R0,#AT_PUNC
        BNE  .none
        LD   R0,[ACH]
        CMP  R0,#$2C            ; ','
        BNE  .none
        CALL aadv
        CALL aoper
        MOV  R2,#4
        CALL astore
        MOV  R0,#2
        ST   [ANOPS],R0
.none:  RET

; ---------------------------------------------------------------------
; alook -- AKEY in amtab? AFAM and ABASE set, C clear.
;
; First, second and last character. Measured over every mnemonic and
; alias, that collides exactly once -- SEC against SEXC -- and SEXC is
; cut, being SBC Rd,Rd spelled out. Three bytes beats five, and
; ADD/ADDW, MOV/MOVW, PUSH/PUSHW, LD/LDW, ST/STW and RET/RETI all
; separate on the last character.
; ---------------------------------------------------------------------
alook:  LDW  X,#amtab
.each:  LD   R0,[X]
        BEQ  .miss
        LD   R1,[AKEY]
        CMP  R0,R1
        BNE  .next
        MOV  R2,#1
        LD   R0,[X+R2]
        LD   R1,[AKEY+1]
        CMP  R0,R1
        BNE  .next
        MOV  R2,#2
        LD   R0,[X+R2]
        LD   R1,[AKEY+2]
        CMP  R0,R1
        BNE  .next
        MOV  R2,#3
        LD   R0,[X+R2]          ; family in the high nibble, base in the low
        MOV  R1,R0
        SHR  R1
        SHR  R1
        SHR  R1
        SHR  R1
        ST   [AFAM],R1
        AND  R0,#$0F
        ST   [ABASE],R0
        CLC
        RET
.next:  ADDW X,#AMENT
        BRA  .each
.miss:  SEC
        RET

; ---------------------------------------------------------------------
; The encoders. Thirteen families, one per arithmetic rule.
;
; **tools/mkasmtab.py's rule() is the specification and this mirrors it
; line for line.** That function implements every rule in Python and
; verify() requires it to reproduce all 488 reachable encodings in
; cool8asm.TABLE before sw/asmtab.asm is written at all -- so the
; arithmetic here is known good before it is typed, and guessing at it
; is how eight wrong encodings got written the first time.
;
; Each sets APRE ($00 or $2F), AOPC, and AEXTRA for whatever trails.
; ---------------------------------------------------------------------

aerr:   MOV  R0,#E_AENC
        ST   [ERR],R0
        RET

; areg1 -- exactly one operand and it is a register; its number in R1,
; C clear. Four encoders were opening with the same six instructions.
areg1:  LD   R0,[ANOPS]
        CMP  R0,#1
        BNE  aerrc
        LD   R0,[AOP0]
        CMP  R0,#AS_REG
        BNE  aerrc
        LD   R1,[ASUB0]
        CLC
        RET
aerrc:  MOV  R0,#E_AENC
        ST   [ERR],R0
        SEC
        RET

; ap2 -- opcode R0, on page 2.
ap2:    ST   [AOPC],R0
        MOV  R0,#$2F
        ST   [APRE],R0
        RET

; axb / axw -- the trailing value belongs to the memory operand, which
; is the second for LD and the first for ST.
axb:    LD   R0,[ABASE]
        MOV  R1,#AX_B1
        SUB  R1,R0
        ST   [AEXTRA],R1
        RET
axw:    LD   R0,[ABASE]
        MOV  R1,#AX_W1
        SUB  R1,R0
        ST   [AEXTRA],R1
        RET

aenc:   CLR  R0
        ST   [APRE],R0
        ST   [AEXTRA],R0        ; AX_NONE
        LD   R0,[AFAM]
        SHL  R0
        LDW  X,#aftab
        LD   R1,[X+R0]
        ADD  R0,#1
        LD   R2,[X+R0]
        MOV  XL,R1
        MOV  XH,R2
        JMP  [X]

aftab:  .word e_none            ; AF_NONE
        .word e_alu             ; AF_ALU
        .word e_adup            ; AF_ALUDUP
        .word e_aim1            ; AF_ALUIM1
        .word e_br              ; AF_BR
        .word e_unary           ; AF_UNARY
        .word e_bit             ; AF_BIT
        .word e_ldst            ; AF_LDST
        .word e_w16             ; AF_W16
        .word e_stk             ; AF_STK
        .word e_jmp             ; AF_JMP
        .word e_mul             ; AF_MUL
        .word e_xor             ; AF_XOR

; ---- no operands: prefix and opcode straight out of amnone
e_none: LD   R0,[ANOPS]
        JNE  aerr
        LD   R0,[ABASE]
        SHL  R0
        LDW  X,#amnone
        ADDW X,R0
        LD   R0,[X]
        ST   [APRE],R0
        INCW X
        LD   R0,[X]
        ST   [AOPC],R0
        RET

; ---- ALU: Rd,#N is $00+op*4+d, Rd,Rs is $80+op*16+d*4+s, and MOV
; ---- alone also reaches the pointer halves on page 2.
e_alu:  LD   R0,[ANOPS]
        CMP  R0,#2
        BNE  .aerr
        LD   R0,[AOP0]
        CMP  R0,#AS_HALF
        BEQ  .movto
        CMP  R0,#AS_REG
        BNE  .aerr
        LD   R0,[AOP1]
        CMP  R0,#AS_IMM
        BEQ  .imm
        CMP  R0,#AS_REG
        BEQ  .rr
        CMP  R0,#AS_HALF
        BEQ  .movfr
        BRA  .aerr
.imm:   LD   R0,[ABASE]
        SHL  R0
        SHL  R0
        LD   R1,[ASUB0]
        ADD  R0,R1
        ST   [AOPC],R0
        MOV  R0,#AX_B1
        ST   [AEXTRA],R0
        RET
.rr:    LD   R0,[ABASE]
        SHL  R0
        SHL  R0
        SHL  R0
        SHL  R0
        LD   R1,[ASUB0]
        SHL  R1
        SHL  R1
        ADD  R0,R1
        LD   R1,[ASUB1]
        ADD  R0,R1
        OR   R0,#$80
        ST   [AOPC],R0
        RET
.movfr: LD   R0,[ABASE]         ; MOV Rd,pp -- page 2 $40
        BNE  .aerr
        LD   R0,[ASUB0]
        SHL  R0
        SHL  R0
        LD   R1,[ASUB1]
        ADD  R0,R1
        OR   R0,#$40
        JMP  ap2
.movto: LD   R0,[ABASE]         ; MOV pp,Rd -- page 2 $50
        BNE  .aerr
        LD   R0,[AOP1]
        CMP  R0,#AS_REG
        BNE  .aerr
        LD   R0,[ASUB1]
        SHL  R0
        SHL  R0
        LD   R1,[ASUB0]
        ADD  R0,R1
        OR   R0,#$50
        JMP  ap2
.aerr:  JMP  aerr

; ---- CLR/TST/SHL/ROL: the register duplicated into both fields
e_adup: CALL areg1
        BCS  .x
        LD   R0,[ABASE]
        SHL  R0
        SHL  R0
        SHL  R0
        SHL  R0
        MOV  R2,R1
        SHL  R2
        SHL  R2
        ADD  R0,R2
        ADD  R0,R1
        OR   R0,#$80
        ST   [AOPC],R0
.x:     RET

; ---- INC/DEC, PUSH/POP and the page 2 unary group are all
; ---- K + base*4 + d over one register operand. Three short arms pick
; ---- K, the page, and anything trailing; the arithmetic is shared.
e_aim1: MOV  R2,#$00            ; INC/DEC -> ADD/SUB Rd,#1
        CLR  R3
        MOV  R0,#AX_B1          ; the 1 is implied, not typed
        ST   [AEXTRA],R0
        MOV  R0,#1
        ST   [AV1],R0
        CLR  R0
        ST   [AV1+1],R0
        BRA  ek4d
e_stk:  MOV  R2,#$30            ; PUSH/POP
        CLR  R3
        BRA  ek4d
e_unary:
        MOV  R2,#$14            ; NOT NEG SWAP SHR SAR ROR, page 2
        MOV  R3,#1
ek4d:   CALL areg1              ; leaves R2 and R3 alone
        BCS  .x
        LD   R0,[ABASE]
        SHL  R0
        SHL  R0
        ADD  R0,R2
        ADD  R0,R1
        TST  R3
        BNE  .p2
        ST   [AOPC],R0
.x:     RET
.p2:    JMP  ap2

; ---- Bcc: $70 + cc, and a displacement from the next pc
e_br:   LD   R0,[ANOPS]
        CMP  R0,#1
        BNE  .aerr
        LD   R0,[AOP0]
        CMP  R0,#AS_N
        BNE  .aerr
        LD   R0,[ABASE]
        OR   R0,#$70
        ST   [AOPC],R0
        MOV  R0,#AX_REL
        ST   [AEXTRA],R0
        RET
.aerr:  JMP  aerr

; ---- NOT/NEG/SWAP/SHR/SAR/ROR: page 2 $14 + group*4 + d. The empty
; ---- ROL slot between ROR and BSET keeps this affine.
; ---- BSET/BCLR/BTST: page 2 $30 + group*4 + d, then a mask
e_bit:  LD   R0,[ANOPS]
        CMP  R0,#2
        BNE  .aerr
        LD   R0,[AOP0]
        CMP  R0,#AS_REG
        BNE  .aerr
        LD   R0,[AOP1]
        CMP  R0,#AS_IMM
        BNE  .aerr
        MOV  R0,#AX_B1
        ST   [AEXTRA],R0
        LD   R0,[ABASE]
        SHL  R0
        SHL  R0
        ADD  R0,#$30
        LD   R1,[ASUB0]
        ADD  R0,R1
        JMP  ap2
.aerr:  JMP  aerr

; ---- MUL Rd,Rs: page 2 $F0, and it writes only X
e_mul:  LD   R0,[ANOPS]
        CMP  R0,#2
        BNE  .aerr
        LD   R0,[AOP0]
        CMP  R0,#AS_REG
        BNE  .aerr
        LD   R0,[AOP1]
        CMP  R0,#AS_REG
        BNE  .aerr
        LD   R0,[ASUB0]
        SHL  R0
        SHL  R0
        LD   R1,[ASUB1]
        ADD  R0,R1
        OR   R0,#$F0
        JMP  ap2
.aerr:  JMP  aerr

; ---- XOR: the eighth ALU operation, with no room in the one-byte
; ---- blocks, so both its forms live on page 2
e_xor:  LD   R0,[ANOPS]
        CMP  R0,#2
        BNE  .aerr
        LD   R0,[AOP0]
        CMP  R0,#AS_REG
        BNE  .aerr
        LD   R0,[AOP1]
        CMP  R0,#AS_IMM
        BEQ  .imm
        CMP  R0,#AS_REG
        BNE  .aerr
        LD   R0,[ASUB0]
        SHL  R0
        SHL  R0
        LD   R1,[ASUB1]
        ADD  R0,R1
        JMP  ap2
.imm:   MOV  R0,#AX_B1
        ST   [AEXTRA],R0
        LD   R0,[ASUB0]
        ADD  R0,#$10
        JMP  ap2
.aerr:  JMP  aerr

; ---- PUSH/POP: $30 + which*4 + d
; ---- JMP/CALL: $28/$29 absolute, $2A-$2D through a pointer
e_jmp:  LD   R0,[ANOPS]
        CMP  R0,#1
        BNE  .aerr
        LD   R0,[AOP0]
        CMP  R0,#AS_N
        BEQ  .abs
        CMP  R0,#AS_IND
        BNE  .aerr
        LD   R0,[ABASE]
        SHL  R0
        ADD  R0,#$2A
        LD   R1,[ASUB0]
        ADD  R0,R1
        ST   [AOPC],R0
        RET
.abs:   LD   R0,[ABASE]
        ADD  R0,#$28
        ST   [AOPC],R0
        MOV  R0,#AX_W0
        ST   [AEXTRA],R0
        RET
.aerr:  JMP  aerr

; ---- LD/ST in six addressing modes, three of them on page 2.
;
; The register and the memory operand swap sides between LD and ST, so
; they are picked apart first and everything after is common: $40/$50
; are [X|Y] and [X|Y+d8], $60 is [SP+u8] and [abs16], and page 2 carries
; the register-indexed and auto-increment forms.
e_ldst: LD   R0,[ANOPS]
        CMP  R0,#2
        JNE  aerr
        LD   R0,[ABASE]         ; 0 = LD, 1 = ST
        BNE  .st
        LD   R3,[AOP0]
        CMP  R3,#AS_REG
        JNE  aerr
        LD   R2,[ASUB0]         ; d
        LD   R3,[AOP1]          ; the memory operand
        LD   R1,[ASUB1]
        BRA  .have
.st:    LD   R3,[AOP1]
        CMP  R3,#AS_REG
        BNE  .aerr
        LD   R2,[ASUB1]
        LD   R3,[AOP0]
        LD   R1,[ASUB0]
.have:  CMP  R3,#AS_RIDX        ; the one form on a different basis
        BEQ  .ridx
        PUSH R3
        PUSH R1
        LD   R0,[ABASE]
        SHL  R0
        SHL  R0
        SHL  R0                 ; st*8
        MOV  R3,R2
        SHL  R3                 ; d*2
        ADD  R0,R3
        POP  R1
        POP  R3
        CMP  R3,#AS_IND
        BEQ  .ind
        CMP  R3,#AS_IDX
        BEQ  .idx
        CMP  R3,#AS_SPN
        BEQ  .spn
        CMP  R3,#AS_ABS
        BEQ  .abs
        CMP  R3,#AS_POST
        BEQ  .post
        CMP  R3,#AS_PRE
        BEQ  .pre
        BRA  .aerr
.ind:   ADD  R0,R1
        ADD  R0,#$40
        ST   [AOPC],R0
        RET
.idx:   ADD  R0,R1
        ADD  R0,#$50
        ST   [AOPC],R0
        JMP  axb
.spn:   ADD  R0,#$60
        ST   [AOPC],R0
        JMP  axb
.abs:   ADD  R0,#$61
        ST   [AOPC],R0
        JMP  axw
.post:  ADD  R0,R1              ; $C0 post-increment, $D0 pre-decrement:
        ADD  R0,#$C0            ;   the same shape as $40/$50
        JMP  ap2
.pre:   ADD  R0,R1
        ADD  R0,#$D0
        JMP  ap2
.ridx:  LD   R0,[ABASE]         ; page 2 $80 + st*32 + isY*16 + d*4 + n
        SHL  R0
        SHL  R0
        SHL  R0
        SHL  R0
        SHL  R0                 ; st*32
        MOV  R3,R2
        SHL  R3
        SHL  R3                 ; d*4
        ADD  R0,R3
        MOV  R3,R1              ; sub = isY*4 + n
        CMP  R3,#4
        BCC  .rx
        SUB  R3,#4
        ADD  R0,#16
.rx:    ADD  R0,R3
        ADD  R0,#$80
        JMP  ap2
.aerr:  JMP  aerr

; ---- the 16-bit block. Four families are arithmetic and the rest is
; ---- the fifteen-entry table, which is the only irregular corner.
e_w16:  LD   R0,[ABASE]
        CMP  R0,#6              ; INCW DECW PUSHW POPW
        BCC  .two
        LD   R1,[ANOPS]
        CMP  R1,#1
        JNE  aerr
        LD   R1,[AOP0]
        CMP  R1,#AS_PTR
        JNE  aerr
        SUB  R0,#6
        SHL  R0
        ADD  R0,#$38
        LD   R1,[ASUB0]
        ADD  R0,R1
        ST   [AOPC],R0
        RET
.two:   LD   R1,[ANOPS]
        CMP  R1,#2
        JNE  aerr
        CMP  R0,#3              ; ADDW
        BEQ  .aw
        CMP  R0,#4              ; SUBW
        BEQ  .sw
        BRA  .tab
.aw:    LD   R1,[AOP0]
        CMP  R1,#AS_PTR
        BNE  .tab
        LD   R1,[AOP1]
        CMP  R1,#AS_REG
        BEQ  .awr
        CMP  R1,#AS_IMM
        BNE  .tab
        MOV  R0,#AX_W1          ; ADDW X|Y,#w -- page 2 $2C, imm16
        ST   [AEXTRA],R0
        LD   R0,[ASUB0]
        ADD  R0,#$2C
        JMP  ap2
.awr:   CLR  R2
        BRA  .wr
.sw:    LD   R1,[AOP0]
        CMP  R1,#AS_PTR
        BNE  .tab
        LD   R1,[AOP1]
        CMP  R1,#AS_REG
        BNE  .tab
        MOV  R2,#8
.wr:    LD   R0,[ASUB0]
        SHL  R0
        SHL  R0                 ; isY*4
        ADD  R0,R2
        LD   R1,[ASUB1]
        ADD  R0,R1
        ADD  R0,#$70
        JMP  ap2
.tab:   LDW  X,#aw16
        CLR  R2
.ts:    CMP  R2,#15
        BCS  .aerr
        LD   R3,[X]
        LD   R0,[ABASE]
        CMP  R0,R3
        BNE  .tn
        MOV  R3,#1
        LD   R3,[X+R3]          ; the shape pair
        LD   R0,[AOP0]
        SHL  R0
        SHL  R0
        SHL  R0
        SHL  R0
        LD   R1,[AOP1]
        ADD  R0,R1
        CMP  R0,R3
        BNE  .tn
        MOV  R3,#2
        LD   R3,[X+R3]          ; and the subfields
        LD   R0,[ASUB0]
        SHL  R0
        SHL  R0
        SHL  R0
        SHL  R0
        LD   R1,[ASUB1]
        ADD  R0,R1
        CMP  R0,R3
        BNE  .tn
        MOV  R3,#3
        LD   R0,[X+R3]
        ST   [AEXTRA],R0
        MOV  R0,R2
        ADD  R0,#$60
        JMP  ap2
.tn:    ADDW X,#4
        ADD  R2,#1
        BRA  .ts
.aerr:  JMP  aerr

; base, shape0<<4|shape1, sub0<<4|sub1, what trails -- opcode $60+index
aw16:   .byte 0,(AS_PTR<<4)|AS_IMM,$00,AX_W1    ; $60 LDW X,#w
        .byte 0,(AS_PTR<<4)|AS_IMM,$10,AX_W1    ; $61 LDW Y,#w
        .byte 0,(AS_PTR<<4)|AS_ABS,$00,AX_W1    ; $62 LDW X,[a]
        .byte 0,(AS_PTR<<4)|AS_ABS,$10,AX_W1    ; $63 LDW Y,[a]
        .byte 1,(AS_ABS<<4)|AS_PTR,$00,AX_W0    ; $64 STW [a],X
        .byte 1,(AS_ABS<<4)|AS_PTR,$01,AX_W0    ; $65 STW [a],Y
        .byte 2,(AS_PTR<<4)|AS_PTR,$01,AX_NONE  ; $66 MOVW X,Y
        .byte 2,(AS_PTR<<4)|AS_PTR,$10,AX_NONE  ; $67 MOVW Y,X
        .byte 2,(AS_SP<<4)|AS_PTR,$00,AX_NONE   ; $68 MOVW SP,X
        .byte 2,(AS_SP<<4)|AS_PTR,$01,AX_NONE   ; $69 MOVW SP,Y
        .byte 2,(AS_PTR<<4)|AS_SP,$00,AX_NONE   ; $6A MOVW X,SP
        .byte 2,(AS_PTR<<4)|AS_SP,$10,AX_NONE   ; $6B MOVW Y,SP
        .byte 3,(AS_SP<<4)|AS_IMM,$00,AX_B1     ; $6C ADDW SP,#d
        .byte 5,(AS_PTR<<4)|AS_SPN,$00,AX_B1    ; $6D LEA X,[SP+u]
        .byte 5,(AS_PTR<<4)|AS_SPN,$10,AX_B1    ; $6E LEA Y,[SP+u]

; ---------------------------------------------------------------------
; Emitting.
;
; **Pass 1 is pass 2 with a flag.** No instruction's length depends on a
; label's value -- Bcc is always 2, JMP/CALL abs16 always 3, LDW X,#w
; always 4, and opcodes.py has no short/long selection -- so both passes
; walk identical pc sequences and the first one simply does not store.
; That is six bytes inside `eb` and it is the whole of the machinery
; sw/emit.bas needs a chain of forward references for.
; ---------------------------------------------------------------------

; eb -- one byte at ACP, stored only on pass 2; ACP moves either way.
eb:     LD   R1,[APASS]
        BEQ  .bump
        PUSHW X
        LD   R1,[ACP]
        MOV  XL,R1
        LD   R1,[ACP+1]
        MOV  XH,R1
        ST   [X],R0
        POPW X
        ; ACP + 1, and the carry has to survive the store: ST and MOV
        ; set no flags and LD sets only Z and N, so C reaches the ADC.
.bump:  LD   R0,[ACP]
        ADD  R0,#1
        ST   [ACP],R0
        LD   R0,[ACP+1]
        MOV  R1,#0
        ADC  R0,R1
        ST   [ACP+1],R0
        RET

; ebyte -- R0:R1 as one byte, if it fits in one.
ebyte:  TST  R1
        BEQ  eb
        CMP  R1,#$FF            ; a negative that still fits
        BNE  arng
        CMP  R0,#$80
        BCC  arng
        JMP  eb

; eword -- R0:R1, low byte first.
eword:  PUSH R1
        CALL eb
        POP  R0
        JMP  eb

arng:   MOV  R0,#E_ARNG
        ST   [ERR],R0
        RET

; aemit -- the prefix, the opcode, and whatever AEXTRA says trails it.
aemit:  LD   R0,[APRE]
        BEQ  .op
        CALL eb
.op:    LD   R0,[AOPC]
        CALL eb
        LD   R0,[AEXTRA]
        BEQ  .done
        CMP  R0,#AX_REL
        BEQ  .rel
        PUSH R0
        AND  R0,#1              ; which operand holds it
        SHL  R0
        SHL  R0                 ; AV0 and AV1 are four bytes apart
        LDW  X,#AV0
        ADDW X,R0
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        POP  R2
        AND  R2,#2              ; and how wide it is
        BNE  .wide
        JMP  ebyte
.wide:  JMP  eword
.done:  RET
        ; A branch reaches +/-127 from the instruction after it. On pass
        ; 1 the target may still be zero, so the range is not checked
        ; there -- only the byte count matters, and it is fixed.
.rel:   LD   R0,[APASS]
        BNE  .rel2
        CLR  R0
        JMP  eb
.rel2:  LD   R0,[AV0]
        LD   R1,[AV0+1]
        LD   R2,[ACP]
        LD   R3,[ACP+1]
        SUB  R0,R2
        SBC  R1,R3
        SUB  R0,#1              ; and past the displacement byte itself
        MOV  R2,#0
        SBC  R1,R2
        TST  R1
        BEQ  .rfwd
        CMP  R1,#$FF
        BNE  arng
        CMP  R0,#$80
        BCC  arng
        JMP  eb
.rfwd:  CMP  R0,#$80
        BCS  arng
        JMP  eb

; ---------------------------------------------------------------------
; adirect -- .byte/.db and .word/.dw.
;
; They arrive as one identifier because `agetc` hands back '.' and then
; BYTE's letters, and `aisid` takes the dot -- so ".BYTE" scans as a
; single word and no rejoining is needed. `word` is not in TOKTAB, so
; .word arrives as plain characters; that asymmetry costs nothing here.
;
; Cut, and why: .org (a block does not choose where it lives), .equ/.set
; (a label is a variable, so `n = 5` is BASIC's job), .align/.space/.fill,
; .include, and .macro/.endm -- several hundred bytes of parameter
; substitution in cool8asm.py alone.
; ---------------------------------------------------------------------
adirect:
        LD   R0,[NBUF+1]
        CMP  R0,#$42            ; ".BYTE"
        BEQ  .byte
        CMP  R0,#$57            ; ".WORD"
        BEQ  .word
        CMP  R0,#$44            ; ".DB" or ".DW"
        JNE  asyn
        LD   R0,[NBUF+2]
        CMP  R0,#$42
        BEQ  .byte
        CMP  R0,#$57
        BEQ  .word
        JMP  asyn
.byte:  CLR  R0
        BRA  .go
.word:  MOV  R0,#1
.go:    ST   [ADW],R0
        CALL aadv
.item:  CALL avalue
        LD   R2,[ADW]
        BEQ  .b1
        CALL eword
        BRA  .more
.b1:    CALL ebyte
.more:  LD   R0,[ERR]
        BNE  .end
        LD   R0,[ATK]
        CMP  R0,#AT_PUNC
        BNE  .end
        LD   R0,[ACH]
        CMP  R0,#$2C            ; ','
        BNE  .end
        CALL aadv
        BRA  .item
.end:   RET

; ---------------------------------------------------------------------
; aline -- one source line.
;
;   line := [ label ':' ] [ mnemonic [ operand { ',' operand } ] ]
;
; The colon needs no lookahead: `atok` leaves the character an
; identifier stopped on in ACH, so a label is recognised without
; fetching another token -- which matters, because fetching one would
; overwrite AKEY with the first operand's name.
; ---------------------------------------------------------------------
aline:  CLR  R0
        ST   [ACH],R0
        ST   [AKLEN],R0
        ST   [ANOPS],R0
        CALL atok
.head:  LD   R0,[ATK]
        CMP  R0,#AT_EOL
        BEQ  .ret
        CMP  R0,#AT_ID
        JNE  asyn
        LD   R0,[ACH]           ; what the name stopped on
        CMP  R0,#$3A            ; ':' -- a label
        BNE  .mnem
        CALL alabel
        CLR  R0
        ST   [ACH],R0
        CALL atok
        BRA  .head
.mnem:  LD   R0,[NBUF]
        CMP  R0,#$2E            ; '.' -- a directive
        JEQ  adirect
        CALL alook              ; AFAM and ABASE, before AKEY is lost
        JCS  asyn
        CALL aadv
        CALL aopers
        LD   R0,[ERR]
        BNE  .ret
        CALL aenc
        LD   R0,[ERR]
        BNE  .ret
        JMP  aemit
.ret:   RET

; ---------------------------------------------------------------------
; The two passes, over the stored program itself.
;
; The block's source *is* the program, so a second pass is a re-walk of
; the same records: no buffer, no copy, no allocation. `nextline` and
; `openline` in sw/interp.asm do the walking, which gives `nextline` a
; caller again.
;
; ASM is $9E as a line's first token and END ASM is $91 $9E, both
; checked as raw bytes at the record level -- so the untokeniser is
; never asked to undo its own delimiter.
; ---------------------------------------------------------------------

; aprog -- assemble every ASM block. R0:R1 is the first record.
aprog:  PUSH R1
        PUSH R0
        CLR  R2
        ST   [APASS],R2
        CALL apass
        POP  R0
        POP  R1
        LD   R2,[ERR]
        BNE  .out
        MOV  R2,#1
        ST   [APASS],R2
        JMP  apass
.out:   RET

apass:  ST   [LREC],R0
        ST   [LREC+1],R1
        LD   R0,[ACBASE]        ; both passes lay out from the same base
        ST   [ACP],R0
        LD   R0,[ACBASE+1]
        ST   [ACP+1],R0
        CALL openline
        ; The delimiters are checked as raw token bytes, so the
        ; untokeniser is never asked to undo its own. The spaces are
        ; still the editor's, though: `END ASM` is stored $91 ' ' $9E.
.scan:  SKIPSP
        CMP  R2,#$9E            ; ASM
        BEQ  .block
.next:  CALL nextline
        BCS  .scan
        RET
.block: CALL nextline
        BCC  .done              ; the program ended inside the block
        PUSHW Y
        SKIPSP
        CMP  R2,#$91            ; END
        BNE  .pop
        INCW Y
        SKIPSP
        CMP  R2,#$9E            ; END ASM closes it
        BNE  .pop
        POPW Y
        BRA  .next
.pop:   POPW Y
.body:  CALL aline
        LD   R0,[ERR]
        BNE  .done
        BRA  .block
.done:  RET
