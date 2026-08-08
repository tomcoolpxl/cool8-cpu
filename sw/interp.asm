; ---------------------------------------------------------------------
; interp.asm -- COOL8 BASIC, executing the program it holds.
;
; The stored program IS the program. There is no compile step and no
; second copy in memory: what LIST shows is what runs.
;
; ## It executes the editor's tokens, not its own
;
; I1 invented a private token space and was poked into memory by hand.
; That was wrong the moment it met a real program: $80 is PRINT in the
; editor's TOKTAB, not LET. This walks the stored form directly --
;
;     lineno (2, LE) | len (1) | tokens (len)
;
; -- with the same token bytes the editor writes. Statement tokens are
; not consecutive in TOKTAB, so dispatch is a table indexed by
; token - $80 with every unimplemented slot pointing at one handler.
;
; ## Recursion is bounded, and the bound is tighter than it looks
;
; The stack is 256 bytes. It is not where an earlier version of this
; comment said: sw/boot.asm:339 sets SP to $0200 and nothing moves it,
; so it grows down through page 1, and page 0 below holds this file's
; state, the A-Z variables and the filesystem's workspace. An overrun
; corrupts those rather than the I/O page.
;
; The expression evaluator is recursive descent, which is cheap here
; because a level costs one return address rather than a frame -- the
; compiler blew its stack because its frames were large, not because it
; recursed.
;
; **Measured, by sim/test_interp.py, rather than assumed: a parenthesis
; costs 4.0 bytes** -- 26 bytes at depth 5, 106 at depth 25. The earlier
; guess of six was pessimistic in the wrong direction, because the real
; problem is not the slope but where it ends up:
;
;   a stored line holds 127 token bytes, so the deepest expression a
;   user can type is about 60 parentheses, and that reaches 246 bytes
;   of the 256.
;
; Ten bytes of margin, measured from an empty stack -- and the editor is
; already 78 bytes down when it calls RUN, so 78 + 246 does not fit.
;
; So the evaluator counts its own nesting and refuses past MAXEXPR with
; ?FORMULA TOO COMPLEX, which is the error C64 BASIC has for exactly
; this reason. 24 levels is about 102 bytes, which leaves the editor its
; 78 and 76 spare. The counter is only touched where prim actually
; recurses, so an expression without a parenthesis pays nothing.
; sim/test_interp.py gates both the slope and the refusal.
; ---------------------------------------------------------------------

; ---- the editor's tokens (sw/basic.bas TOKTAB, order frozen)
K_PRINT = $80
K_SUB   = $81
K_FUNC  = $82
K_DIM   = $83
K_CONST = $84
K_FOR   = $85
K_NEXT  = $86
K_TO    = $87
K_DO    = $88
K_LOOP  = $89
K_WHILE = $8A
K_UNTIL = $8B
K_EXIT  = $8C
K_IF    = $8D
K_THEN  = $8E
K_ELSE  = $8F
K_ELSIF = $90
K_END   = $91
K_RET   = $92
K_CALL  = $93
K_PEEK  = $97
K_POKE  = $98
K_AND   = $99
K_OR    = $9A
K_XOR   = $9B
K_GOTO  = $A2
K_NUM   = $A4                   ; a binary literal: two bytes follow

NTOK    = 37                    ; $80..$A4

; ---- state
;
; The page 0 map and the error codes are in sw/zp.asm, which the
; including file supplies once. LVAR/LLIM/LBODY/LLINE are adjacent there
; on purpose: they are the innermost FOR's frame and fpush copies them
; as seven consecutive bytes.
;
; The FOR stack is the BBC Micro's shape rather than BBC BASIC (86)'s.
; The BBC gave FOR, REPEAT and GOSUB a stack each and said "Too many
; FORs" when one filled; BBC BASIC (86) merged them onto the processor
; stack. The first is right here, because the processor stack is 256
; bytes shared with everything else and a deeply parenthesised
; expression already reaches 246 of it.

; ---- how deep an expression may nest
;
; Measured at 4.0 bytes of stack a level, so 24 is about 102 bytes. The
; editor is already 78 bytes down when it calls RUN and the whole stack
; is 256, which is where the number comes from: it is a stack budget,
; not a limit on what anyone would write. Ten nested parentheses is
; already beyond what BBC or C64 BASIC will take.
MAXEXPR = 24

; ---------------------------------------------------------------------
; SKIPSP -- Y forward over spaces; R2 = the character it stopped on.
;
; The editor stores the line as it was typed. `sw/basic.bas:1536-1541`
; drops exactly one space after the line number and `tokenise` copies
; every interior space verbatim, so `10 A = 7` is stored as
; A ' ' = ' ' $A4 07 00 -- and LIST gives the indentation back because of
; it. That is BBC BASIC's arrangement and 6502 Microsoft BASIC's alike:
; both keep the spaces and skip them at read time.
;
; Nothing here did, and no gate could see it, because every case in
; sim/test_interp.py builds its token stream by hand with no separators.
; A space reaching `varidx` became variable ($20-'A')*2 = 190, so
; `A = 7` assigned VARS+190 = $00FE -- silently, with ERR still zero.
;
; **Inlined, and that is measured.** As a subroutine it was 17.2 % of
; the expression benchmark, whose lines hold no spaces at all: 6 clocks
; of CALL and 3 of RET to discover there was nothing to do. The test
; itself is 7. This is CHRGOT, and it is inline for the reason CHRGOT
; is.
;
; R2 and not R0, because every operator peek in `eval` runs with the
; value it is accumulating live in R0:R1.
; ---------------------------------------------------------------------
.macro  SKIPSP
        LD   R2,[Y]
        CMP  R2,#$20
        BNE  @go
        CALL skipsp
@go:
.endm

; ---------------------------------------------------------------------
; run -- execute from the first line to the last.
;
; X and Y are both needed for memory access, so the token pointer lives
; in Y and everything else is reloaded. Y is the thing there are most
; accesses to.
; ---------------------------------------------------------------------
irun:
        CLR  R0
        ST   [ERR],R0
        LDW  X,#VARS            ; every variable starts at zero
        MOV  R1,#52
.iz:    CLR  R0
        ST   [X],R0
        INCW X
        SUB  R1,#1
        BNE  .iz
        CLR  R0
        ST   [FDEPTH],R0        ; and no FOR loop is running
        ST   [EDEPTH],R0        ; at statement level, not inside a paren
        ST   [NNAME],R0         ; and no long name is defined yet
        ; NTAB and HEAP are the caller's, like LREC and PEND: the table
        ; starts where the program's code ends and the heap comes down
        ; from MEMTOP, and only the caller knows where those are.
        ; LREC and PEND are set by the caller -- the editor passes the
        ; program it is holding, and the gate passes one it built.
        CALL openline
        JMP  stmt

; openline -- LREC points at a record; put Y on its first token.
;
; There is nothing else to do. The line ends with a zero byte, so the
; statement loop asks "end of line?" with one load rather than a 16-bit
; compare against an end pointer that had to be maintained here.
openline:
        LD   R0,[LREC]
        MOV  YL,R0
        LD   R0,[LREC+1]
        MOV  YH,R0
        INCW Y
        INCW Y
        INCW Y
        RET

; nextline -- LREC = the record after this one. Carry clear when the
; program has run out.
nextline:
        LD   R0,[LREC]          ; this record + 4 + its length
        LD   R1,[LREC+1]
        MOV  XL,R0
        MOV  XH,R1
        INCW X
        INCW X
        LD   R2,[X]
        ADD  R0,#4
        MOV  R3,#0
        ADC  R1,R3
        ADD  R0,R2
        ADC  R1,R3
        ST   [LREC],R0
        ST   [LREC+1],R1
        LD   R2,[PEND]
        LD   R3,[PEND+1]
        SUB  R0,R2              ; LREC - progend
        SBC  R1,R3
        BLT  .more
        CLC
        RET
.more:  CALL openline
        SEC
        RET

; ---------------------------------------------------------------------
; The statement loop.
; ---------------------------------------------------------------------
stmt:
        LD   R0,[ERR]
        TST  R0
        BEQ  .live
        RET
.live:
        SKIPSP             ; end of line? one load, past the spaces.
        TST  R2
        BNE  .more
        ; Y is sitting on the terminator, so the next record begins at
        ; Y+1. There is no address to compute: nextline was 18 % of the
        ; run doing arithmetic the position already answered.
        INCW Y
        MOV  R0,YL
        ST   [LREC],R0
        MOV  R1,YH
        ST   [LREC+1],R1
        LD   R2,[PEND]
        LD   R3,[PEND+1]
        SUB  R0,R2
        SBC  R1,R3
        BLT  .open
        RET                     ; past the last line: stop
.open:  CALL openline
        JMP  stmt
.more:
        CMP  R2,#$80            ; below $80 it is a name: an assignment
        BCC  h_let
        INCW Y
        MOV  R0,R2
        SUB  R0,#$80
        CMP  R0,#NTOK
        BCS  bad
        SHL  R0
        LDW  X,#sttab
        LD   R1,[X+R0]
        ADD  R0,#1
        LD   R2,[X+R0]
        MOV  XL,R1
        MOV  XH,R2
        JMP  [X]

bad:    MOV  R0,#E_SYN
        ST   [ERR],R0
        RET

; $80..$A4. Everything not implemented lands on `bad`, which is the
; honest answer and costs one slot each.
sttab:
        .word h_print           ; $80 PRINT
        .word h_sub             ; $81 SUB -- a definition, skipped
        .word h_sub             ; $82 FUNCTION
        .word h_dim             ; $83 DIM
        .word bad               ; $84 CONST
        .word h_for             ; $85 FOR
        .word h_next            ; $86 NEXT
        .word bad               ; $87 TO
        .word bad               ; $88 DO
        .word bad               ; $89 LOOP
        .word bad               ; $8A WHILE
        .word bad               ; $8B UNTIL
        .word bad               ; $8C EXIT
        .word h_if              ; $8D IF
        .word bad               ; $8E THEN
        .word h_else            ; $8F ELSE
        .word bad               ; $90 ELSEIF
        .word h_end             ; $91 END
        .word bad               ; $92 RETURN
        .word bad               ; $93 CALL
        .word bad               ; $94 AS
        .word bad               ; $95 INT
        .word bad               ; $96 BYTE
        .word bad               ; $97 PEEK
        .word h_poke            ; $98 POKE
        .word bad               ; $99 AND
        .word bad               ; $9A OR
        .word bad               ; $9B XOR
        .word bad               ; $9C CARD
        .word bad               ; $9D AT
        .word h_asm             ; $9E ASM
        .word bad               ; $9F EXTERN
        .word bad               ; $A0 INCLUDE
        .word bad               ; $A1 INLINE
        .word h_goto            ; $A2 GOTO
        .word bad               ; $A3 WEND
        .word bad               ; $A4 NUM

h_end:  MOV  R0,#E_DONE         ; a clean stop, not an error
        ST   [ERR],R0
        RET

; A SUB definition met while running is skipped to its END.
h_sub:  LD   R0,[Y]
        TST  R0
        BEQ  .done
        CALL skiptok
        BRA  h_sub
.done:  JMP  stmt

; ---------------------------------------------------------------------
; v = <expression>
;
; A name is one letter here: A-Z are resident, which is BBC BASIC's
; A%-Z% and is why a loop counter costs nothing to find.
; ---------------------------------------------------------------------
h_let:
        CALL varidx             ; R0 = the handle, Y past the name
        SKIPSP
        CMP  R2,#$28            ; '(' -- a subscripted assignment
        BNE  .scalar
        JMP  h_leta             ; it lives at the end, out of branch reach
.scalar:
        ST   [TVAR],R0
        SKIPSP
        INCW Y                  ; the '='
        CALL eval
        PUSH R1
        PUSH R0
        LD   R0,[TVAR]
        CALL varaddr
        POP  R0
        POP  R1
        ST   [X],R0
        INCW X
        ST   [X],R1
        JMP  stmt

; ---------------------------------------------------------------------
; Variables, and the two kinds of them.
;
; `varidx` returns a one-byte **handle**, not an address, and the split
; is the whole point:
;
;   0..50 even    A-Z, resident, the value at VARS + handle
;   52 + slot     a long name, the value in the name table's entry
;
; A handle rather than an address because `FOR` caches its variable in
; LVAR, one byte of a seven-byte frame that `fpush` copies whole; making
; it two would take FORSTK to 64 bytes and it has 56. It also keeps the
; resident path exactly what it was -- one load, one subtract, one shift
; -- which is most of the speed in a loop and the reason A-Z exist.
;
; What is new is that a name is now *scanned* rather than assumed to be
; one character. That closes a real fault as well as adding long names:
; any token byte below $80 that was not `(`, `-` or $A4 used to be taken
; for a variable, so a stray quote indexed VARS+194 = $0102 and `h_let`
; wrote there.
; ---------------------------------------------------------------------

; nisid -- C clear if R0 can appear inside a name. tokenise() uses the
; same rule (sw/chars.bas), so a name the editor kept as one word is one
; word here too.
nisid:  CMP  R0,#$5F            ; '_'
        BEQ  .yes
        CMP  R0,#$30            ; '0'
        BCC  .no
        CMP  R0,#$3A            ; past '9'
        BCC  .yes
        CALL nupper
        CMP  R0,#$41            ; 'A'
        BCC  .no
        CMP  R0,#$5B            ; past 'Z'
        BCS  .no
.yes:   CLC
        RET
.no:    SEC
        RET

; nupper -- R0 folded to upper case. The language is case-insensitive
; (sim/check_names.py enforces that on the compiler's own sources), and
; the assembler needs it too: the tokeniser folds keyword case but keeps
; typed case, so `Loop:` and `LOOP:` must reach one symbol.
nupper: CMP  R0,#$61            ; 'a'
        BCC  .n
        CMP  R0,#$7B            ; past 'z'
        BCS  .n
        SUB  R0,#$20
.n:     RET

; ---------------------------------------------------------------------
; varidx -- the variable at Y, as a handle. Y ends past the whole name.
;
; **The resident case is straight-line and calls nothing.** Written the
; obvious way -- scan into a buffer, then notice it was one character --
; the expression benchmark went from 8.73x to 17.4x, because A-Z are the
; hot path and a loop counter was suddenly a subroutine.
;
; What it costs now, and cannot avoid costing, is **one lookahead**: a
; name ends where its characters stop, so the next byte has to be
; classified before `K` can be told from `KOUNT`. Not doing that was the
; old fault, not an optimisation. The tests are ordered so the
; terminators that actually occur -- a space, and every operator, all of
; which are below '0' -- are caught by the first compare.
; ---------------------------------------------------------------------
varidx:
        LD   R0,[Y]
        CMP  R0,#$61            ; fold case inline; nupper is a call
        BCC  .nf
        CMP  R0,#$7B
        BCS  .nf
        SUB  R0,#$20
.nf:    CMP  R0,#$41            ; a name starts with a letter, and this
        BCC  .notname           ;   is what a stray quote now trips on
        CMP  R0,#$5B
        BCS  .notname
        INCW Y
        LD   R2,[Y]             ; does the name carry on?
        CMP  R2,#$30            ; ' ' and every operator land here
        BCC  .single
        CMP  R2,#$3A            ; '0'-'9'
        BCC  .multi
        CMP  R2,#$41            ; ':' ';' '<' '=' '>' '?' '@'
        BCC  .single
        CMP  R2,#$5B            ; 'A'-'Z'
        BCC  .multi
        CMP  R2,#$5F            ; '_'
        BEQ  .multi
        CMP  R2,#$61
        BCC  .single
        CMP  R2,#$7B            ; 'a'-'z'; a token byte ends it
        BCS  .single
.multi: DECW Y                  ; hand the whole name to the slow path
        BRA  vlong
        ; X comes back too, pointing at the value. `prim` wants it and
        ; is three of the five callers, and going back through varaddr
        ; for something varidx has already worked out cost 7 % of the
        ; benchmark.
.single:
        SUB  R0,#65             ; 'A'
        SHL  R0
        LDW  X,#VARS
        ADDW X,R0
        RET
        ; Nothing that could start a name. That used to be undetectable:
        ; any token byte below $80 was taken for a variable.
.notname:
        MOV  R0,#E_SYN
        ST   [ERR],R0
        CLR  R0
        RET

; vlong -- two characters or more: into NBUF, then the table.
;
; NBUF is not blanked first. `nfind` compares the stored length before
; it compares any characters, so only the significant ones are ever
; looked at and whatever follows them is never read.
vlong:  CALL nscan
        JMP  nfind

; nscan -- the identifier at Y into NBUF and NLEN, however short. Y ends
; past it. Split out of vlong because a subscripted `A(3)` needs the
; name in NBUF even when varidx took the one-character fast path.
nscan:  CLR  R0
        ST   [NLEN],R0
.scan:  LD   R0,[Y]
        CALL nisid
        BCS  .done
        CALL nupper
        LD   R1,[NLEN]
        CMP  R1,#NSIG           ; past six: counted, not stored
        BCC  .keep
        BRA  .bump
.keep:  PUSH R0
        LDW  X,#NBUF
        ADDW X,R1
        POP  R0
        ST   [X],R0
.bump:  LD   R1,[NLEN]
        ADD  R1,#1
        ST   [NLEN],R1
        INCW Y
        BRA  .scan
.done:  RET

; nsigc -- R3 = how many characters of NBUF are significant.
nsigc:  LD   R3,[NLEN]
        CMP  R3,#NSIG
        BCC  .n
        MOV  R3,#NSIG
.n:     RET

; nlook -- NBUF in the name table? Handle in R0 and X on its value, with
; C clear; C set and nothing else touched if it is not there.
;
; Split from `nfind` for the assembler: BASIC wants first mention to be
; definition, but an assembler needs to tell "defined at zero" from
; "never defined" or an undefined label reads as zero and assembles
; silently wrong bytes.
; nvalp -- entry R2 as a handle in R0, with X on its value. A global and
; not a local label because both nlook and nfind end here, and a local
; belongs to whichever routine encloses it.
nvalp:  MOV  R0,R2
        CALL nentry
        ADDW X,#NSIG+2
        MOV  R0,R2
        ADD  R0,#52
        CLC
        RET

nlook:  CLR  R2
.each:  LD   R0,[NNAME]
        CMP  R2,R0
        BCC  .try
        SEC
        RET
.try:   MOV  R0,R2
        CALL nentry             ; X = entry R2
        INCW X                  ; past the type byte
        LD   R0,[X]             ; the stored length, compared first so
        LD   R1,[NLEN]          ;   the characters after the significant
        SUB  R0,R1              ;   ones are never read at all
        BNE  .next
        CALL nsigc
        MOV  R1,R3
        PUSHW Y
        LDW  Y,#NBUF
.cmp:   INCW X
        LD   R0,[X]
        LD   R3,[Y+]
        SUB  R0,R3
        BNE  .no
        SUB  R1,#1
        BNE  .cmp
        POPW Y
        BRA  nvalp
.no:    POPW Y
.next:  ADD  R2,#1
        BRA  .each

; nfind -- nlook, but first mention is definition. BASIC has no
; declaration and an unset variable has to read zero, the same as A-Z do.
nfind:  CALL nlook
        BCS  .make
        RET
.make:  LD   R0,[NNAME]
        CMP  R0,#MAXNAME
        BCC  .room
        MOV  R0,#E_NAMES
        ST   [ERR],R0
        MOV  R0,#52             ; a handle that exists, so nothing faults
        RET
.room:  CALL nentry             ; X = the new entry
        MOV  R0,#1              ; type 1: a 16-bit integer
        ST   [X],R0
        INCW X
        LD   R0,[NLEN]
        ST   [X],R0
        PUSHW Y
        LDW  Y,#NBUF
        MOV  R1,#NSIG
.cp:    INCW X
        LD   R0,[Y+]
        ST   [X],R0
        SUB  R1,#1
        BNE  .cp
        POPW Y
        INCW X                  ; the value, two bytes of zero
        CLR  R0
        ST   [X],R0
        INCW X
        ST   [X],R0
        LD   R0,[NNAME]
        MOV  R2,R0
        ADD  R0,#1
        ST   [NNAME],R0
        BRA  nvalp

; nentry -- X = the address of name-table entry R0.
nentry: MOV  R1,#NENT
        MUL  R0,R1              ; X = R0 * NENT, and MUL leaves both alone
        LD   R0,[NTAB]
        MOV  R1,XL
        ADD  R1,R0
        MOV  XL,R1
        LD   R0,[NTAB+1]
        MOV  R1,XH
        ADC  R1,R0
        MOV  XH,R1
        RET

; varaddr -- X = where handle R0's value lives.
varaddr:
        CMP  R0,#52
        BCS  .named
        LDW  X,#VARS
        ADDW X,R0
        RET
.named: SUB  R0,#52
        CALL nentry
        ADDW X,#NSIG+2          ; past the type, the length and the name
        RET

; skipsp -- SKIPSP's slow half: there really was a space. Reached only
; when the inlined test found one, so the loop costs nothing to the
; overwhelming majority of reads that find a token straight away.
skipsp: INCW Y
        LD   R2,[Y]
        CMP  R2,#$20
        BEQ  skipsp
        RET

; ---------------------------------------------------------------------
; POKE addr, value
; ---------------------------------------------------------------------
h_poke:
        CALL eval
        MOV  XL,R0
        MOV  XH,R1
        PUSHW X
        INCW Y                  ; the comma
        CALL eval
        POPW X
        ST   [X],R0
        JMP  stmt

; ---------------------------------------------------------------------
; PRINT <expr> -- one number, then a newline. The editor's own screen
; routines do the work; there is no second console.
; ---------------------------------------------------------------------
h_print:
        CALL eval
        PUSH R1
        PUSH R0
        CALL s_putn
        CALL s_newline
        POP  R0
        POP  R1
        JMP  stmt

; ---------------------------------------------------------------------
; IF <expr> THEN ...
;
; True runs the rest of the line. False skips it -- to ELSE if this line
; has one, otherwise to the next line. Single-line IF only, which is the
; shape that costs nothing to find the end of.
; ---------------------------------------------------------------------
; ---------------------------------------------------------------------
; skiptok -- R0 = the token at Y, and Y past the whole of it.
;
; **A literal is three bytes, not one.** $A4 is followed by two binary
; bytes, and the high byte of every value below 256 is zero -- so a scan
; that walks a byte at a time meets that zero and calls it the end of
; the line. `IF 1 = 2 THEN A = 5` resumed three bytes inside its own
; record, executed a length byte as a token, and assigned A whatever
; followed. It went unnoticed because the wrong answer happened to be
; the right one until the code around it moved.
;
; Every walk to end of line goes through here. It lives beside its three
; callers and not beside `bad`, because eight bytes between the
; dispatcher and `h_let` put `BCC h_let` four bytes out of range.
; ---------------------------------------------------------------------
skiptok:
        LD   R0,[Y]
        INCW Y
        CMP  R0,#K_NUM
        BNE  .done
        INCW Y                  ; the value rides with the token
        INCW Y
.done:  RET

h_if:
        CALL eval
        MOV  R2,R0
        OR   R2,R1
        BEQ  .false
        INCW Y                  ; step over THEN
        JMP  stmt
        ; False: walk to an ELSE on this line, or to the end of it. The
        ; statement loop takes it from there -- reaching the end of a
        ; line is exactly what it already knows how to handle.
.false: LD   R0,[Y]
        TST  R0
        BEQ  .out
        CALL skiptok
        CMP  R0,#K_ELSE
        BNE  .false
.out:   JMP  stmt

; ELSE reached while running means the true arm just finished.
h_else: LD   R0,[Y]
        TST  R0
        BEQ  .done
        CALL skiptok
        BRA  h_else
.done:  JMP  stmt

; ---------------------------------------------------------------------
; GOTO n
; ---------------------------------------------------------------------
h_goto:
        CALL eval               ; the line number
        PUSH R1
        PUSH R0
        CALL s_findline
        POP  R2
        POP  R2
        ST   [LREC],R0
        ST   [LREC+1],R1
        CALL openline
        JMP  stmt

; ---------------------------------------------------------------------
; FOR v = <expr> TO <expr>   /   NEXT [v]
;
; Nested to MAXFOR levels, and the claim the one-level version made --
; that a stack costs the same per iteration -- turned out to be true, so
; it is built that way: the innermost loop stays in the four cached
; locations and only the *enclosing* ones are pushed. NEXT's hot path
; therefore gains one load and one branch over the whole nesting
; question, and nothing else.
;
; Before this, a nested FOR overwrote the outer loop's variable, limit,
; body and line, and the outer NEXT then counted the inner variable
; toward the inner limit. It did not fail; it silently ran the wrong
; program.
; ---------------------------------------------------------------------
; The two errors the FOR stack can raise. They live here rather than
; beside `bad` because only this code reaches them, and putting them up
; there pushed sttab twelve bytes further from the dispatcher -- which
; put `BCC h_let`, the hot path for an assignment, out of branch range.
e_fors: MOV  R0,#E_FORS         ; ?TOO MANY FORS
        ST   [ERR],R0
        RET
e_next: MOV  R0,#E_NEXT         ; ?NEXT WITHOUT FOR
        ST   [ERR],R0
        RET

; fpush / fpop -- the cached frame to and from FORSTK[R0].
;
; LVAR, LLIM, LBODY and LLINE were laid out adjacent for this: the frame
; is seven consecutive bytes at $001A, so saving one is a block copy
; rather than seven named moves. MUL puts Rd*Rs in X and touches neither
; operand, so the slot address is one instruction.
;
; Y is the token pointer and the copy needs a second pointer, so Y is
; spilled for the duration -- two bytes, and only on a FOR or a NEXT
; that ends a loop, never per iteration.
fpush:  MOV  R1,#FORFR
        MUL  R0,R1              ; X = R0 * FORFR
        ADDW X,#FORSTK
        PUSHW Y
        LDW  Y,#LVAR
        MOV  R1,#FORFR
.fp:    LD   R0,[Y+]
        ST   [X],R0
        INCW X
        SUB  R1,#1
        BNE  .fp
        POPW Y
        RET

fpop:   MOV  R1,#FORFR
        MUL  R0,R1
        ADDW X,#FORSTK
        PUSHW Y
        LDW  Y,#LVAR
        MOV  R1,#FORFR
.fq:    LD   R0,[X]
        ST   [Y+],R0
        INCW X
        SUB  R1,#1
        BNE  .fq
        POPW Y
        RET

h_for:
        ; Room for another? The innermost lives in the cache, so the
        ; stack holds FDEPTH-1 frames and FDEPTH is the count of loops.
        LD   R0,[FDEPTH]
        CMP  R0,#MAXFOR
        BCC  .room
        JMP  e_fors             ; out of reach for a branch
.room:  CMP  R0,#0
        BEQ  .first             ; nothing cached yet, nothing to save
        SUB  R0,#1
        CALL fpush              ; the loop we are about to displace
.first: LD   R0,[FDEPTH]
        ADD  R0,#1
        ST   [FDEPTH],R0

        SKIPSP             ; the dispatcher left Y on the FOR's space
        CALL varidx
        ST   [LVAR],R0
        SKIPSP
        INCW Y                  ; the '='
        CALL eval
        PUSH R1
        PUSH R0
        LD   R0,[LVAR]
        CALL varaddr
        POP  R0
        POP  R1
        ST   [X],R0
        INCW X
        ST   [X],R1
        INCW Y                  ; the TO
        CALL eval
        ST   [LLIM],R0
        ST   [LLIM+1],R1
        MOV  R0,YL
        ST   [LBODY],R0
        MOV  R0,YH
        ST   [LBODY+1],R0
        LD   R0,[LREC]
        ST   [LLINE],R0
        LD   R0,[LREC+1]
        ST   [LLINE+1],R0
        JMP  stmt

h_next:
        LD   R0,[FDEPTH]
        BNE  .live
        JMP  e_next             ; NEXT without FOR
        ; An optional variable name, and it has to be tested for as a
        ; letter rather than as "not a token". A bare NEXT at the end of
        ; a line sits on the terminator, which is $00 and therefore also
        ; below $80; the looser test consumed it as a name.
.live:  SKIPSP
        CMP  R2,#$41            ; 'A'
        BCC  .go
        CMP  R2,#$5B            ; past 'Z'
        BCS  .go
        CALL varidx             ; R0 = its doubled index, Y past it
        ; `NEXT i` when an inner loop is still open closes the inner one
        ; -- the BBC's rule, and the thing that makes GOTO out of a loop
        ; recoverable rather than a slow leak.
.match: LD   R1,[LVAR]
        CMP  R0,R1
        BEQ  .go
        LD   R1,[FDEPTH]
        SUB  R1,#1
        ST   [FDEPTH],R1
        CMP  R1,#0
        BEQ  .nomatch
        PUSH R0
        SUB  R1,#1
        MOV  R0,R1
        CALL fpop
        POP  R0
        BRA  .match
.nomatch:
        JMP  e_next
.go:    LD   R0,[LVAR]
        CALL varaddr
        LD   R2,[X]
        INCW X
        LD   R3,[X]
        MOV  R0,#1
        ADD  R2,R0
        MOV  R0,#0
        ADC  R3,R0
        ST   [X],R3
        DECW X
        ST   [X],R2
        LD   R0,[LLIM]
        LD   R1,[LLIM+1]
        SUB  R0,R2              ; limit - v; go on while v <= limit
        SBC  R1,R3
        BLT  .out
        ; Back to the body without re-opening the line. openline was
        ; 16 % of the whole benchmark and half of its calls were this
        ; one, re-deriving what FOR already knew.
        LD   R0,[LLINE]
        ST   [LREC],R0
        LD   R0,[LLINE+1]
        ST   [LREC+1],R0
        LD   R0,[LBODY]
        MOV  YL,R0
        LD   R0,[LBODY+1]
        MOV  YH,R0
        JMP  stmt
        ; The loop is done: drop it and bring the enclosing one back
        ; into the cache, if there is one.
.out:   LD   R0,[FDEPTH]
        SUB  R0,#1
        ST   [FDEPTH],R0
        CMP  R0,#0
        BEQ  .last
        SUB  R0,#1
        CALL fpop
.last:  JMP  stmt

; ---------------------------------------------------------------------
; The expression evaluator.
;
; Recursive descent, value in R0:R1, one level per precedence. A level
; costs a return address, so a parenthesis costs six bytes of stack --
; which is why this may recurse where the compiler could not.
;
;   eval  = sum  [ relational sum ]
;   sum   = prod { + - }
;   prod  = prim { * }
;   prim  = number | variable | ( eval ) | - prim | PEEK ( eval )
; ---------------------------------------------------------------------
eval:
        CALL prim               ; the first operand
        ; ---- { * operand }, highest precedence, checked inline
        ;
        ; One peek serves all three levels. skipsp leaves the character
        ; in R2, and *, + - and the relationals are each tested against
        ; it in turn without touching Y again -- so an operand costs one
        ; skip, not three. Every arm that consumes an operator rejoins
        ; at .mul, which is where the next peek happens.
.mul:   SKIPSP
        CMP  R2,#$2A            ; '*'
        BNE  .sum
        INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        CALL imul16
        BRA  .mul
        ; ---- { + operand | - operand }
.sum:   CMP  R2,#$2B            ; '+', on the character .mul already has
        BEQ  .add
        CMP  R2,#$2D            ; '-'
        BEQ  .sub
        BRA  .rel
.add:   INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        ADD  R0,R2
        ADC  R1,R3
        BRA  .mul
.sub:   INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        SUB  R0,R2
        SBC  R1,R3
        BRA  .mul
        ; ---- one relation, if there is one
.rel:   CMP  R2,#$3D            ; '='
        BEQ  .req
        CMP  R2,#$3C            ; '<'
        BEQ  .rlt
        CMP  R2,#$3E            ; '>'
        BEQ  .rgt
        RET

.req:   INCW Y
        CALL rhs
        SUB  R0,R2
        SBC  R1,R3
        OR   R0,R1
        BEQ  .y1
        JMP  false
.y1:    JMP  true

.rlt:   INCW Y
        LD   R2,[Y]
        CMP  R2,#$3D
        BEQ  .rle
        CMP  R2,#$3E
        BEQ  .rne
        CALL rhs
        SUB  R0,R2
        SBC  R1,R3
        BLT  .y2
        JMP  false
.y2:    JMP  true
.rne:   INCW Y
        CALL rhs
        SUB  R0,R2
        SBC  R1,R3
        OR   R0,R1
        BEQ  .y3
        JMP  true
.y3:    JMP  false
.rle:   INCW Y                  ; a <= b is b >= a
        CALL rhs
        MOV  R0,R2              ; swap: compare b - a
        MOV  R1,R3
        POP  R2
        POP  R3
        PUSH R3
        PUSH R2
        BRA  .cmpge
.rgt:   INCW Y
        LD   R2,[Y]
        CMP  R2,#$3D
        BEQ  .rge
        CALL rhs                ; a > b is b < a
        MOV  R0,R2
        MOV  R1,R3
        POP  R2
        POP  R3
        PUSH R3
        PUSH R2
        SUB  R0,R2
        SBC  R1,R3
        BLT  .y4
        JMP  false
.y4:    JMP  true
.rge:   INCW Y
        CALL rhs
        SUB  R0,R2
        SBC  R1,R3
.cmpge: BGE  .y5
        JMP  false
.y5:    JMP  true

; rhs -- the right-hand side of a relation, with its own * and +/-.
; The left side is preserved in R0:R1 across it.
rhs:    PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        CALL sumrest
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        RET

; mulrest -- { * operand } applied to whatever is in R0:R1.
mulrest:
        SKIPSP
        CMP  R2,#$2A
        BEQ  .go
        RET
.go:    INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        CALL imul16
        BRA  mulrest

; sumrest -- { + operand | - operand } applied to R0:R1.
sumrest:
        SKIPSP
        CMP  R2,#$2B
        BEQ  .a
        CMP  R2,#$2D
        BEQ  .s
        RET
.a:     INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        ADD  R0,R2
        ADC  R1,R3
        BRA  sumrest
.s:     INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        SUB  R0,R2
        SBC  R1,R3
        BRA  sumrest

true:   MOV  R0,#1
        CLR  R1
        RET
false:  CLR  R0
        CLR  R1
        RET

; edin / edout -- one level of expression nesting, and back.
;
; Only the three places prim actually recurses call these, so an
; expression without a parenthesis pays nothing at all -- which matters,
; because prim runs once per operand and is the hottest thing here after
; NEXT. R2 is scratch across prim already; nothing survives it.
;
; edin returns with C set when it has refused, and the caller hands back
; zero. It does not try to unwind: ERR is set, every enclosing level
; refuses in turn because the counter is still at the limit, and the
; expression collapses to a value nobody uses because `stmt` checks ERR
; before running another statement.
edin:   LD   R2,[EDEPTH]
        CMP  R2,#MAXEXPR
        BCS  .over
        ADD  R2,#1
        ST   [EDEPTH],R2
        CLC
        RET
.over:  MOV  R2,#E_DEEP         ; ?FORMULA TOO COMPLEX
        ST   [ERR],R2
        SEC
        RET

edout:  LD   R2,[EDEPTH]
        SUB  R2,#1
        ST   [EDEPTH],R2
        RET

prim:
        SKIPSP
        CMP  R2,#K_NUM
        BEQ  .num
        CMP  R2,#$28            ; '('
        BEQ  .paren
        CMP  R2,#$2D            ; unary minus
        BEQ  .neg
        CMP  R2,#K_PEEK
        BEQ  .peek
        ; a name -- varidx leaves X on its value, unless a '(' says
        ; the name was an array's and X has to be worked out instead
        CALL varidx
        SKIPSP                  ; `A (3)` is stored with the space in it
        CMP  R2,#$28            ; '('
        BEQ  .sub
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        RET
.sub:   CALL arrelem
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        RET
.num:   INCW Y
        LD   R0,[Y]
        INCW Y
        LD   R1,[Y]
        INCW Y
        RET
.paren: INCW Y
        CALL edin
        BCS  .deep
        CALL eval
        CALL edout
        INCW Y                  ; the ')'
        RET
.neg:   INCW Y
        CALL edin
        BCS  .deep
        CALL prim
        CALL edout
        MOV  R2,R0
        MOV  R3,R1
        CLR  R0
        CLR  R1
        SUB  R0,R2
        SBC  R1,R3
        RET
.peek:  INCW Y
        SKIPSP
        INCW Y                  ; the '('
        CALL edin
        BCS  .deep
        CALL eval
        CALL edout
        INCW Y                  ; the ')'
        MOV  XL,R0
        MOV  XH,R1
        LD   R0,[X]
        CLR  R1
        RET
        ; Refused. The value is never used -- stmt stops on ERR before
        ; the statement that would have consumed it completes.
.deep:  CLR  R0
        CLR  R1
        RET

; ---------------------------------------------------------------------
; R0:R1 = R0:R1 * R2:R3. MUL is 8x8 and lands in X, so the four partial
; products are added by hand and X is spilled around each.
; ---------------------------------------------------------------------
imul16:
        ST   [MTMP],R0
        ST   [MTMP+1],R1
        ST   [MTMP+2],R2
        ST   [MTMP+3],R3
        LD   R0,[MTMP]          ; low * low
        LD   R1,[MTMP+2]
        MUL  R0,R1
        MOV  R0,XL
        MOV  R1,XH
        LD   R2,[MTMP]          ; low * high, into the high byte only
        LD   R3,[MTMP+3]
        MUL  R2,R3
        MOV  R2,XL
        ADD  R1,R2
        LD   R2,[MTMP+1]        ; high * low, likewise
        LD   R3,[MTMP+2]
        MUL  R2,R3
        MOV  R2,XL
        ADD  R1,R2
        RET

; ---------------------------------------------------------------------
; h_asm -- an ASM block met while running.
;
; The block was assembled at RUN, before a single statement executed, so
; there is nothing to do here but step over it. That is `h_sub`'s job
; done across records rather than within a line, and it is why the
; assembler runs as one linear pass first: a forward CALL into a block
; that had not been reached yet would otherwise fail, and a block inside
; an untaken IF would never be assembled at all.
;
; It lives at the end of the file, not beside `bad`. Twelve bytes
; between the dispatcher and `h_let` already put `BCC h_let` out of
; range once.
; ---------------------------------------------------------------------
h_asm:  CALL nextline
        BCC  .off
        SKIPSP
        CMP  R2,#K_END
        BNE  h_asm
        INCW Y
        SKIPSP
        CMP  R2,#$9E            ; ASM -- so this is END ASM
        BNE  h_asm
        INCW Y                  ; and run whatever follows on that line
        JMP  stmt
        ; Falling off the end inside a block is not an error: the
        ; program simply finished.
.off:   MOV  R0,#E_DONE
        ST   [ERR],R0
        RET

; ---------------------------------------------------------------------
; Arrays, and the heap they live in.
;
; **The name table grows up and the heap grows down, and they meet at
; ?OUT OF MEMORY.** That is BBC BASIC's shape -- its heap climbs from
; LOMEM while the stack descends from HIMEM -- with one difference that
; is deliberate. BBC keeps variables and arrays in a single heap and
; must chain them, because its entries are variable length; a lookup
; walks a linked list per initial letter. These entries are a fixed ten
; bytes, so `nentry` is a multiply and no walk exists to be slow. The
; price is that variable-length data cannot live among them, which is
; why it comes down from MEMTOP instead.
;
; Two places this deliberately parts company with BBC BASIC II, having
; read what it actually does:
;
;   **Subscripts are checked.** BBC checks only at DIM, that the bound
;   fits in fourteen bits, and does no range test at all when indexing.
;   That is defensible when the running program is a separate compiled
;   copy. Here the stored program *is* the program, so an unchecked
;   subscript writes over the source of the statement executing it, or
;   over the name table, or page zero. Fifteen bytes and a compare buys
;   ?SUBSCRIPT instead of a program that silently rewrites itself.
;
;   **`A` and `A(` are different variables.** BBC has one namespace and
;   simply refuses the collision, which it can afford because it has no
;   resident scalars. A-Z here are resident and free, so an array called
;   A has nowhere to be but the name table -- and appending the '(' to
;   its name, the way Microsoft BASIC does, keeps the two apart for
;   twelve bytes and no new field.
;
; One dimension. BBC stores a dimension count and each size as a word,
; then folds subscripts by iterated multiply; that is the way to extend
; this, and it is deferred rather than designed out.
; ---------------------------------------------------------------------

; halloc -- R0:R1 bytes off the top of the heap. Address in R0:R1, C
; clear; C set and ?OUT OF MEMORY if the heap would reach the names.
halloc: LD   R2,[HEAP]
        LD   R3,[HEAP+1]
        SUB  R2,R0
        SBC  R3,R1
        PUSH R3
        PUSH R2
        LD   R0,[NNAME]
        CALL nentry             ; X = one past the last name-table entry
        POP  R2
        POP  R3
        MOV  R0,R2              ; would the heap come down past it?
        MOV  R1,XL
        SUB  R0,R1
        MOV  R0,R3
        MOV  R1,XH
        SBC  R0,R1
        BLT  .full
        ST   [HEAP],R2
        ST   [HEAP+1],R3
        MOV  R0,R2
        MOV  R1,R3
        CLC
        RET
.full:  MOV  R0,#E_MEM
        ST   [ERR],R0
        SEC
        RET

; arrname -- the name in NBUF becomes the array of that name.
;
; NLEN always grows, even when the '(' itself will not fit in the
; significant characters, because nlook compares the length before it
; compares a single byte -- so the two stay apart either way.
arrname:
        LD   R0,[NLEN]
        CMP  R0,#NSIG
        BCS  .bump
        PUSH R0
        LDW  X,#NBUF
        ADDW X,R0
        MOV  R0,#$28            ; '('
        ST   [X],R0
        POP  R0
.bump:  ADD  R0,#1
        ST   [NLEN],R0
        RET

esubs:  MOV  R0,#E_SUBS
        ST   [ERR],R0
        LDW  X,#MTMP            ; somewhere harmless; stmt stops on ERR
        RET

; aelem -- X on one element of the array whose block is at R0:R1, with Y
; on the '(' of the subscript. Y ends past the ')'.
;
; The block is a count word and then the elements, so the bound travels
; with the data and the name table entry stays ten bytes.
aelem:  PUSH R1
        PUSH R0
        INCW Y                  ; the '('
        CALL eval
        SKIPSP
        INCW Y                  ; the ')'
        POP  R2
        POP  R3
        MOV  XL,R2
        MOV  XH,R3
        LD   R2,[X]             ; the count, which the block carries
        INCW X
        LD   R3,[X]
        INCW X                  ; and now X is on element zero
        PUSH R1
        PUSH R0
        TST  R1                 ; negative subscripts are out of range
        BMI  .bad               ;   too, and unsigned compare misses them
        SUB  R0,R2
        SBC  R1,R3
        BGE  .bad
        POP  R0
        POP  R1
        SHL  R0                 ; two bytes an element
        ROL  R1
        ADDW X,R0
        MOV  R2,XH
        ADD  R2,R1
        MOV  XH,R2
        RET
.bad:   POP  R0
        POP  R1
        JMP  esubs

; arrelem -- X on the element named by handle R0, with Y on its '('.
arrelem:
        CMP  R0,#52
        BCS  .named             ; a long name: NBUF and NLEN are set
        ; A resident handle, so varidx's fast path never filled NBUF.
        ; The name is rebuilt from the handle rather than rescanned,
        ; because Y has already gone past the spaces to the '(' and
        ; backing it up would land on one of them.
        SHR  R0                 ; the handle is the index doubled
        ADD  R0,#65             ; 'A'
        LDW  X,#NBUF
        ST   [X],R0
        MOV  R0,#1
        ST   [NLEN],R0
.named: CALL arrname
        CALL nlook
        BCS  esubs              ; never dimensioned
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        JMP  aelem

; ---------------------------------------------------------------------
; DIM name(bound)
;
; Eleven elements for DIM A(10), subscripts 0 to 10 -- BBC BASIC's rule
; and Microsoft's, and the one every published program assumes.
; Re-dimensioning is allowed and simply allocates again: the old block
; becomes garbage, which is the same bargain assignment makes, and every
; RUN starts with an empty name table anyway.
; ---------------------------------------------------------------------
h_dim:  SKIPSP
        CALL nscan
        CALL arrname
        CALL nfind              ; X on the entry's value
        PUSHW X
        SKIPSP
        INCW Y                  ; the '('
        CALL eval
        SKIPSP
        INCW Y                  ; the ')'
        ADD  R0,#1              ; the bound is inclusive
        MOV  R2,#0
        ADC  R1,R2
        PUSH R1
        PUSH R0
        SHL  R0                 ; two bytes each, after the count word
        ROL  R1
        ADD  R0,#2
        MOV  R2,#0
        ADC  R1,R2
        CALL halloc
        BCS  .fail
        POP  R2                 ; the count
        POP  R3
        MOV  XL,R0
        MOV  XH,R1
        ST   [X],R2
        INCW X
        ST   [X],R3
        INCW X
        PUSH R1                 ; keep the block for the entry
        PUSH R0
.zero:  MOV  R0,R2              ; an unwritten element reads zero, the
        OR   R0,R3              ;   same as an unset scalar does
        BEQ  .done
        CLR  R0
        ST   [X],R0
        INCW X
        ST   [X],R0
        INCW X
        SUB  R2,#1
        MOV  R0,#0
        SBC  R3,R0
        BRA  .zero
.done:  POP  R0
        POP  R1
        POPW X                  ; the name table entry
        ST   [X],R0
        INCW X
        ST   [X],R1
        JMP  stmt
.fail:  POP  R2                 ; halloc has set ERR
        POP  R2
        POPW X
        RET

; h_leta -- A(i) = expr. The element's address is worked out before the
; right-hand side is evaluated, because eval needs X for itself.
h_leta: CALL arrelem
        PUSHW X
        SKIPSP
        INCW Y                  ; the '='
        CALL eval
        POPW X
        ST   [X],R0
        INCW X
        ST   [X],R1
        JMP  stmt
