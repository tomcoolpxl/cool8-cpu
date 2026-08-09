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

NTOK    = 57                    ; $80..$B8 -- graphics, sound, and the
                                ; language round-out, all appended
K_STEP  = $B3
K_DATA  = $B0
K_GOTOT = $A2                   ; GOTO's token, for ON to expect

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
        ST   [DDEPTH],R0        ; nor a DO, which a second RUN must not
                                ;   inherit from the first
        ST   [EDEPTH],R0        ; at statement level, not inside a paren
        ST   [NNAME],R0         ; and no long name is defined yet
        ST   [CDEPTH],R0        ; nor a call in progress
        CALL drst               ; the DATA pointer rewinds, unpositioned
        CLR  R0
        ST   [ibreak],R0        ; and nothing is asking it to stop
        ; Every SUB is found now, while LREC is still the program's
        ; first record -- the only moment that address is known without
        ; keeping a pointer to it. A call is then a name lookup rather
        ; than a search of the whole program.
        LD   R0,[LREC]
        PUSH R0
        LD   R0,[LREC+1]
        PUSH R0
        CALL subscan
        POP  R0
        ST   [LREC+1],R0
        POP  R0
        ST   [LREC],R0
        ; NTAB and HEAP are the caller's, like LREC and PEND: the table
        ; starts where the program's code ends and the heap comes down
        ; from MEMTOP, and only the caller knows where those are.
        ; LREC and PEND are set by the caller -- the editor passes the
        ; program it is holding, and the gate passes one it built.
        ;
        ; The FIRST record gets the same bound test every later one
        ; gets, through nextline's own tail. An empty program is
        ; LREC = PEND, and opening record zero anyway executes
        ; whatever is at PROG -- zeros on a harness, the relocating
        ; stub's leftover code on every flash boot.
        LD   R0,[LREC]
        LD   R1,[LREC+1]
        CALL lbound
        BCS  .go
        JMP  h_end              ; empty: a clean stop, nothing ran
.go:    JMP  stmt

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
; lbound -- R0:R1 holds LREC's value: open it if it is short of PEND
; and return with carry set, or carry clear for "the program is over".
; irun enters here for record zero, nextline falls through for the rest.
lbound: LD   R2,[PEND]
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
        ; Every statement starts with an empty accumulator. Doing it
        ; here rather than in each handler is what makes a string
        ; sub-expression safe to leave alone: `(A$ + B$)` has to go on
        ; appending, so nothing below statement level may reset.
        CLR  R2
        ST   [SLEN],R2
        ST   [STYPE],R2
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
        BCS  .tok               ; (the fifth time this branch has gone
        JMP  h_let              ;  out of range: a JMP, once and for all)
.tok:   INCW Y
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
        .word h_const           ; $84 CONST
        .word h_for             ; $85 FOR
        .word h_next            ; $86 NEXT
        .word bad               ; $87 TO
        .word h_do              ; $88 DO
        .word h_loop            ; $89 LOOP
        .word bad               ; $8A WHILE
        .word bad               ; $8B UNTIL
        .word h_exit            ; $8C EXIT
        .word h_if              ; $8D IF
        .word bad               ; $8E THEN
        .word h_else            ; $8F ELSE
        .word h_else            ; $90 ELSEIF
        .word h_end             ; $91 END
        .word h_ret             ; $92 RETURN
        .word h_call            ; $93 CALL
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
        .word h_mode            ; $A5 MODE
        .word h_vsync           ; $A6 VSYNC
        .word h_scroll          ; $A7 SCROLL
        .word h_palette         ; $A8 PALETTE
        .word h_sprite          ; $A9 SPRITE
        .word h_vpoke           ; $AA VPOKE
        .word h_sound           ; $AB SOUND
        .word h_hline           ; $AC HLINE
        .word h_plot            ; $AD PLOT
        .word h_line            ; $AE LINE
        .word h_input           ; $AF INPUT
        .word h_else            ; $B0 DATA -- executed, it is a line to
                                ;   step over, which is ELSE's whole job
        .word h_read            ; $B1 READ
        .word h_restore         ; $B2 RESTORE
        .word bad               ; $B3 STEP -- a clause, like TO
        .word h_on              ; $B4 ON
        .word h_tile            ; $B5 TILE
        .word h_clg             ; $B6 CLG
        .word h_pitch           ; $B7 PITCH
        .word h_gtext           ; $B8 GTEXT

h_end:  MOV  R0,#E_DONE         ; a clean stop, not an error
        ST   [ERR],R0
        RET

; ---------------------------------------------------------------------
; v = <expression>
;
; A name is one letter here: A-Z are resident, which is BBC BASIC's
; A%-Z% and is why a loop counter costs nothing to find.
; ---------------------------------------------------------------------
h_let:
        CALL varidx             ; R0 = the handle, Y past the name
        CMP  R0,#52
        BCC  .notstr            ; resident A-Z is never a string
        PUSH R0
        CALL isstr
        POP  R0
        BCS  .notstr
        JMP  h_lets             ; X is on its descriptor already
.notstr:
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
; The same table `varidx` indexes, so there is one statement of what a
; name may contain rather than two that have to agree. R0 comes back
; untouched: `nscan` folds it afterwards and would be folding a class
; byte otherwise.
nisid:  BTST R0,#$80            ; a token byte is never a name char,
        BNE  .no                ;   and ctab is 128 bytes, ASCII only
        PUSHW X
        PUSH R0
        LDW  X,#ctab
        LD   R1,[X+R0]
        POP  R0
        POPW X
        BTST R1,#$80
        BEQ  .no
        CLC
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
        BTST R0,#$80            ; a token: nothing that starts a name,
        BNE  .notname           ;   and past the 128-byte table
        LDW  X,#ctab
        LD   R0,[X+R0]          ; folded, classified and indexed at once
        BTST R0,#$40            ; a name starts with a letter
        BEQ  .notname
        INCW Y
        LD   R2,[Y]
        LD   R2,[X+R2]          ; and X is still on the table
        BTST R2,#$80            ; does the name carry on?
        BNE  .multi
        ; X comes back too, pointing at the value. `prim` wants it and
        ; is three of the five callers, and going back through varaddr
        ; for something varidx has already worked out cost 7 % of the
        ; benchmark.
        AND  R0,#$3F
        SHL  R0
        LDW  X,#VARS
        ADDW X,R0
        RET
.multi: DECW Y                  ; hand the whole name to the slow path
        BRA  vlong
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
; Y is the token pointer and the editor's routines are compiled BASIC,
; which uses Y freely -- `s_puts` walks it over the string it is given.
; So it is saved around every one of them. The numeric path survived
; without this only because `s_putn` happens not to touch it.
; PRINT items separated by ';' (butted) or ',' (one space), and a
; trailing separator holds the newline back -- the shape every BASIC
; taught. PRINT alone is a blank line.
h_print:
        SKIPSP
        TST  R2
        BNE  .item
        CALL pnl
        JMP  stmt
.item:  CALL eval
        LD   R2,[STYPE]
        BNE  .str
        PUSHW Y                 ; saved *first*: the argument has to be
        PUSH R1                 ;   on top when the call reads [SP+2]
        PUSH R0
        CALL s_putn
        POP  R0
        POP  R1
        POPW Y
        BRA  .sep
        ; A heap string is length-counted, so PRINT needs a sibling of
        ; puts that takes one rather than a NUL.
        ; putsn(p AS CARD, n AS INT). The compiler pushes right to left
        ; and **an INT is two bytes**, so the count needs a high byte of
        ; its own -- pushing one left the callee reading a length out of
        ; the saved Y and looping until the machine stopped answering.
.str:   PUSHW Y
        CLR  R2
        PUSH R2                 ; n, high byte
        LD   R2,[SLEN]
        PUSH R2                 ; n, low
        LD   R0,[SACC+1]
        PUSH R0                 ; p, high
        LD   R0,[SACC]
        PUSH R0                 ; p, low -- and so on top, at [SP+2]
        CALL s_putsn
        POP  R0
        POP  R0
        POP  R0
        POP  R0
        POPW Y
        ; spent: the next item may be a string too, and a number after
        ; a string must not take the string path
        CLR  R2
        ST   [SLEN],R2
        ST   [STYPE],R2
.sep:   SKIPSP
        CMP  R2,#$3B            ; ';'
        BEQ  .semi
        CMP  R2,#$2C            ; ','
        BEQ  .comma
        CALL pnl
        JMP  stmt
.comma: PUSHW Y
        CLR  R0
        PUSH R0
        MOV  R0,#$20
        PUSH R0
        CALL s_emit
        POP  R0
        POP  R0
        POPW Y
.semi:  INCW Y
        SKIPSP
        TST  R2
        BNE  .item
        JMP  stmt               ; a trailing separator: no newline

pnl:    PUSHW Y
        CALL s_newline
        POPW Y
        RET

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
        BEQ  .out
        CMP  R0,#K_ELSIF        ; a fresh condition, on the same line
        BNE  .false
        JMP  h_if
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
goton:  PUSH R1                 ; ON joins here with its pick in R0/R1
        PUSH R0
        CALL s_findline
        POP  R2
        POP  R2
        ST   [LREC],R0
        ST   [LREC+1],R1
        CALL openline
        CALL ipoll
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
        ; STEP, or the 1 it defaults to. Parsed before LBODY is taken,
        ; because the body starts after the whole clause.
        MOV  R0,#1
        ST   [LSTEP],R0
        CLR  R0
        ST   [LSTEP+1],R0
        SKIPSP
        CMP  R2,#K_STEP
        BNE  .nstep
        INCW Y
        CALL eval
        ST   [LSTEP],R0
        ST   [LSTEP+1],R1
.nstep: MOV  R0,YL
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
        LD   R0,[LSTEP]
        ADD  R2,R0
        LD   R0,[LSTEP+1]
        ADC  R3,R0
        ST   [X],R3
        DECW X
        ST   [X],R2
        ; Counting down flips the test: on while v >= limit. The sign
        ; of the step decides which comparison is the loop's.
        LD   R0,[LSTEP+1]
        AND  R0,#$80
        BNE  .down
        LD   R0,[LLIM]
        LD   R1,[LLIM+1]
        SUB  R0,R2              ; limit - v; go on while v <= limit
        SBC  R1,R3
        BLT  .out
        BRA  .back
.down:  LD   R0,[LLIM]
        LD   R1,[LLIM+1]
        SUB  R0,R2              ; limit - v; stop when it went positive,
        SBC  R1,R3              ;   which is v < limit
        SUB  R0,#1
        SBC  R1,#0
        BGE  .out
.back:
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
        CALL ipoll
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
; ---------------------------------------------------------------------
; eval -- the whole expression, bitwise operators included.
;
;   eval  = erel { AND | OR | XOR  erel }
;   erel  = sum  [ relational sum ]
;   sum   = prod { + - }
;   prod  = prim { * }
;
; AND, OR and XOR bind looser than the relationals, which is BBC BASIC's
; order and the reason `IF a < b AND c < d` needs no parentheses. They
; are one level rather than two -- BBC puts OR and EOR below AND -- which
; costs `a AND b OR c` its precedence and saves a whole recursion level
; off a 256-byte stack. Parenthesise if it matters.
; ---------------------------------------------------------------------
eval:   CALL erel
.more:  SKIPSP
        CMP  R2,#K_AND
        BEQ  .and
        CMP  R2,#K_OR
        BEQ  .or
        CMP  R2,#K_XOR
        BEQ  .xor
        RET
.and:   CALL .rhs
        AND  R0,R2
        AND  R1,R3
        BRA  .more
.or:    CALL .rhs
        OR   R0,R2
        OR   R1,R3
        BRA  .more
.xor:   CALL .rhs
        XOR  R0,R2
        XOR  R1,R3
        BRA  .more
        ; the operand after the operator, with the running value kept
.rhs:   INCW Y
        PUSH R1
        PUSH R0
        CALL erel
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        RET

erel:
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
        BEQ  .m1
        CMP  R2,#$2F            ; '/'
        BEQ  .d1
        CMP  R2,#$4D            ; 'M' -- only then is MOD worth probing
        BEQ  .m2                ;   for; the probe is three calls deep
        CMP  R2,#$6D            ;   and every operand would pay it
        BNE  .sum
.m2:    PUSH R1                 ; ismod needs R0, and R0:R1 is the value
        PUSH R0                 ;   being accumulated. POP leaves C.
        CALL ismod
        POP  R0
        POP  R1
        BCS  .sum
        CALL mdrhs
        CALL idiv16
        LD   R0,[DREM]          ; the same pass already produced it
        LD   R1,[DREM+1]
        BRA  .mul
.m1:    INCW Y
        CALL mdrhs
        CALL imul16
        BRA  .mul
.d1:    INCW Y
        CALL mdrhs
        CALL idiv16
        BRA  .mul
        ; ---- { + operand | - operand }
.sum:   CMP  R2,#$2B            ; '+', on the character .mul already has
        BEQ  .add
        CMP  R2,#$2D            ; '-'
        BEQ  .sub
        BRA  .rel
.add:   INCW Y
        LD   R2,[STYPE]
        BNE  .cat               ; the left was a string: append, not add
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
        ; Concatenation is the accumulator doing nothing special: the
        ; operand appends where the last one stopped.
.cat:   CALL prim
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
        ; ---- << and >>, at the same level the compiler holds them.
        ; A lone < or > is a relation and falls through with R2 put
        ; back the way .rel expects it.
.shq:   INCW Y
        LD   R2,[Y]
        CMP  R2,#$3C
        BEQ  .shl
        DECW Y                  ; a lone '<': the relation it always was,
        JMP  .rlt               ;   entered exactly as .rel entered it
.shl:   INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        AND  R0,#$0F
        MOV  R2,R0
        POP  R0
        POP  R1
.sll:   TST  R2
        BEQ  .shj
        ADD  R0,R0
        ADC  R1,R1
        SUB  R2,#1
        BRA  .sll
.srq:   INCW Y
        LD   R2,[Y]
        CMP  R2,#$3E
        BEQ  .shr
        DECW Y
        JMP  .rgt
.shr:   INCW Y
        PUSH R1
        PUSH R0
        CALL prim
        CALL mulrest
        AND  R0,#$0F
        MOV  R2,R0
        POP  R0
        POP  R1
.srl:   TST  R2
        BEQ  .shj
        SHR  R1
        ROR  R0
        SUB  R2,#1
        BRA  .srl
.shj:   JMP  .mul
        ; ---- one relation, if there is one
.rel:   CMP  R2,#$3C            ; '<' -- or the first half of '<<'
        BEQ  .shq
        CMP  R2,#$3E            ; '>' -- or of '>>'
        BEQ  .srq
        CMP  R2,#$3D            ; '=' -- '<' and '>' were taken above
        BEQ  .req
        RET

.req:   INCW Y
        LD   R2,[STYPE]
        BEQ  .nreq
        CALL srhs
        CALL scmp
        TST  R0
        BEQ  .y1
        JMP  false
.nreq:  CALL rhs
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
        LD   R2,[STYPE]
        BEQ  .nrne
        CALL srhs
        CALL scmp
        TST  R0
        BNE  .y3n
        JMP  false
.y3n:   JMP  true
.nrne:  CALL rhs
        SUB  R0,R2
        SBC  R1,R3
        OR   R0,R1
        BEQ  .y3
        JMP  true
.y3:    JMP  false
        ; a <= b is b >= a, so the two sides swap. `rhs` has already
        ; balanced its own pushes, so there is nothing on the stack to
        ; recover the left side from -- the POP/PUSH that used to be
        ; here took the caller's return address and put it back, which
        ; worked only because nothing between them faulted. And it
        ; branched past the subtraction it was setting up.
.rle:   INCW Y
        CALL rhs
        PUSH R1
        PUSH R0
        MOV  R0,R2
        MOV  R1,R3
        POP  R2
        POP  R3
        SUB  R0,R2
        SBC  R1,R3
        BRA  .cmpge
.rgt:   INCW Y
        LD   R2,[Y]
        CMP  R2,#$3D
        BEQ  .rge
        CALL rhs                ; a > b is b < a, and swaps the same way
        PUSH R1
        PUSH R0
        MOV  R0,R2
        MOV  R1,R3
        POP  R2
        POP  R3
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

; srhs -- the right-hand side of a string relation. It appends, and the
; split it returns in R2 is where the left one ended.
srhs:   LD   R2,[SLEN]
        PUSH R2
        CALL prim
        CALL sumrest
        POP  R2
        RET

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
        CMP  R2,#$2F            ; '/'
        BEQ  .dv
        CMP  R2,#$4D            ; 'M', as in .mul above
        BEQ  .m2
        CMP  R2,#$6D
        BNE  .out
.m2:    PUSH R1
        PUSH R0
        CALL ismod
        POP  R0
        POP  R1
        BCS  .out
        CALL mdrhs              ; ismod has stepped over the word
        CALL idiv16
        LD   R0,[DREM]
        LD   R1,[DREM+1]
        BRA  mulrest
.out:   RET
.go:    INCW Y
        CALL mdrhs
        CALL imul16
        BRA  mulrest
.dv:    INCW Y
        CALL mdrhs
        CALL idiv16
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
        LD   R2,[STYPE]
        BNE  .scat
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
.scat:  CALL prim
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

; TRUE is -1 and not 1, which is BBC BASIC's choice and is what makes
; AND, OR and XOR serve as logical operators and bitwise ones with a
; single implementation: every bit of a true is set, so `(a<b) AND (c<d)`
; and `mask AND $0F` are the same instruction. With 1 the first works by
; accident and stops working the moment anything is negated.
true:   MOV  R0,#$FF
        MOV  R1,#$FF
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
        CMP  R2,#$22            ; '"' -- a literal, stored with its quotes
        BEQ  .lit
        ; a name -- varidx leaves X on its value, unless a '(' says
        ; the name was an array's and X has to be worked out instead
        CALL varidx
        CMP  R0,#52
        BCC  .notstr            ; resident A-Z: neither of the below
        ; **A builtin is asked about first, and that order matters.**
        ; LEFT$, RIGHT$, MID$ and CHR$ all end in '$', so `isstr` says
        ; yes to every one of them and they would be read as string
        ; variables of those names. LEN and ASC do not, which is why
        ; they worked while the other four did not.
        ;
        ; X is the variable's value and isbuilt returns a handler in it,
        ; so it is kept across the question.
        PUSHW X
        PUSH R0
        CALL isbuilt
        POP  R0
        BCC  .built
        POPW X
        PUSH R0
        CALL isstr
        POP  R0
        BCS  .notstr
        JMP  sload              ; X is already on its descriptor
.built: ADDW SP,#2              ; not a variable after all
        JMP  [X]
.notstr:
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
        ; A literal needs no heap: tokenise keeps the quoted text
        ; verbatim, both quotes included, so it is copied straight out
        ; of the program into the accumulator.
.lit:   INCW Y
.lc:    LD   R0,[Y]
        BEQ  .ld                ; end of line: unterminated, take what is
        CMP  R0,#$22            ;   there rather than run off the record
        BEQ  .lq
        INCW Y
        CALL sputc
        BRA  .lc
.lq:    INCW Y
.ld:    MOV  R0,#1
        ST   [STYPE],R0
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

; ---------------------------------------------------------------------
; Strings.
;
; **One accumulator, and only assignment leaves it.** Every string
; expression is built up in STRACC, which is BBC BASIC's arrangement
; read off its disassembly, and it is what makes concatenation free:
; the second operand appends where the first stopped, so `A$ + B$ + C$`
; needs no code beyond not resetting the length, and no intermediate
; ever reaches the heap. Building a heap block per sub-expression is the
; obvious alternative and it costs an allocator call, a copy and a piece
; of garbage for every `+` in the program.
;
; A variable is four bytes -- where the characters are, how many there
; are, and how many were allocated -- in the name table's `value` and
; `aux` fields. The third is the one that earns its place: an assignment
; that fits in what the variable already has copies in place instead of
; allocating again. There is no garbage collection, and BBC BASIC has
; none either; a string that outgrows its space abandons the old bytes.
;
; The `$` is the type. `A` and `A$` are different names because the
; suffix is part of the name, so nothing needs a type field and nothing
; needs to agree about one.
; ---------------------------------------------------------------------

; sreset -- begin a string expression. The *statement* does this, not
; the evaluator, because a parenthesised sub-expression must go on
; appending rather than start again.
sreset: CLR  R0
        ST   [SLEN],R0
        ST   [STYPE],R0
        RET

; sputc -- append R0 to the accumulator.
sputc:  PUSHW X
        PUSH R0
        LD   R0,[SLEN]
        CMP  R0,#SMAX
        BCS  .full
        LD   R1,[SACC]
        MOV  XL,R1
        LD   R1,[SACC+1]
        MOV  XH,R1
        ADDW X,R0
        ADD  R0,#1
        ST   [SLEN],R0
        POP  R0
        ST   [X],R0
        POPW X
        RET
.full:  POP  R0
        POPW X
        MOV  R0,#E_STR
        ST   [ERR],R0
        RET

; sappend -- R2 characters from R0:R1 onto the accumulator.
sappend:
        MOV  R3,#1
        ST   [STYPE],R3
        TST  R2
        BEQ  .done
        PUSHW Y                 ; Y is the token pointer; borrow it
        MOV  YL,R0
        MOV  YH,R1
.cp:    LD   R0,[Y+]
        PUSH R2
        CALL sputc
        POP  R2
        SUB  R2,#1
        BNE  .cp
        POPW Y
.done:  RET

; isstr -- C clear if the name in NBUF ends with '$'. The suffix is the
; type, so this is the whole of the type system.
isstr:  PUSHW X
        LD   R0,[NLEN]
        CMP  R0,#NSIG
        BCC  .in
        MOV  R0,#NSIG           ; only the significant ones are kept
.in:    TST  R0
        BEQ  .no
        SUB  R0,#1
        LDW  X,#NBUF
        ADDW X,R0
        LD   R0,[X]
        CMP  R0,#$24            ; '$'
        BNE  .no
        POPW X
        CLC
        RET
.no:    POPW X
        SEC
        RET

; sload -- the string variable whose descriptor starts at X, appended.
sload:  LD   R0,[X]
        INCW X
        LD   R1,[X]
        INCW X
        LD   R2,[X]             ; the current length
        JMP  sappend

; sstore -- the accumulator into the descriptor at X.
sstore: MOV  R2,#3
        LD   R1,[X+R2]          ; how much this variable already has
        LD   R0,[SLEN]
        CMP  R1,R0
        BCS  .have              ; it fits where it is: no allocation
        PUSHW X
        CLR  R1
        CALL halloc
        POPW X
        LD   R2,[ERR]
        BNE  .out
        ST   [X],R0             ; the old bytes become garbage, which is
        INCW X                  ;   the bargain BBC BASIC makes as well
        ST   [X],R1
        DECW X
        LD   R0,[SLEN]
        MOV  R2,#3
        ST   [X+R2],R0
.have:  LD   R0,[SLEN]
        MOV  R2,#2
        ST   [X+R2],R0
        LD   R2,[X]
        INCW X
        LD   R3,[X]
        MOV  XL,R2
        MOV  XH,R3
        PUSHW Y
        LD   R0,[SACC]
        MOV  YL,R0
        LD   R0,[SACC+1]
        MOV  YH,R0
        LD   R2,[SLEN]
        TST  R2
        BEQ  .cpd
.cp:    LD   R0,[Y+]
        ST   [X],R0
        INCW X
        SUB  R2,#1
        BNE  .cp
.cpd:   POPW Y
.out:   RET

; h_lets -- A$ = <string expression>.
h_lets: PUSHW X
        SKIPSP
        INCW Y                  ; the '='
        CALL eval
        POPW X
        LD   R0,[ERR]
        BNE  .out
        CALL sstore
.out:   JMP  stmt

; scmp -- the accumulator holds both operands end to end, split at R2:
; the left is [0,R2) and the right is [R2,SLEN). R0 = 0 when they are
; equal. The accumulator is cut back to the split either way, so a
; comparison inside a longer expression leaves nothing behind.
;
; Comparing in place is the other half of what the accumulator buys.
; Neither side was ever copied to the heap, so `IF A$ = "Y"` allocates
; nothing at all.
scmp:   PUSH R2
        LD   R0,[SLEN]
        SUB  R0,R2
        MOV  R3,R2
        CMP  R0,R3              ; different lengths cannot be equal
        BNE  .ne
        PUSHW X
        PUSHW Y
        LD   R1,[SACC]
        MOV  XL,R1
        LD   R1,[SACC+1]
        MOV  XH,R1
        MOV  R1,XL
        MOV  YL,R1
        MOV  R1,XH
        MOV  YH,R1
        ADDW Y,R3               ; Y on the right half
        TST  R3
        BEQ  .same
.c:     LD   R0,[X]
        INCW X
        LD   R1,[Y+]
        SUB  R0,R1
        BNE  .diff
        SUB  R3,#1
        BNE  .c
.same:  POPW Y
        POPW X
        POP  R2                 ; the split, back to a number and a
        ST   [SLEN],R2          ;   length that forgets what was compared
        CLR  R0
        ST   [STYPE],R0
        CLR  R0
        RET
.diff:  POPW Y
        POPW X
.ne:    POP  R2
        ST   [SLEN],R2
        CLR  R0
        ST   [STYPE],R0
        MOV  R0,#1
        RET

; slen -- LEN(<string>). The text measured is not kept: SLEN goes back
; to where it was, so LEN inside a concatenation does not corrupt it.
slen:   SKIPSP
        INCW Y                  ; the '('
        LD   R2,[SLEN]
        PUSH R2
        CALL eval
        SKIPSP
        INCW Y                  ; the ')'
        POP  R2
        LD   R0,[SLEN]
        SUB  R0,R2
        CLR  R1
        ST   [SLEN],R2
        PUSH R0
        CLR  R0
        ST   [STYPE],R0
        POP  R0
        RET


; ---------------------------------------------------------------------
; Division, and why MOD is free.
;
; Restoring division: shift the dividend left a bit at a time into a
; remainder, subtract the divisor whenever it fits, and the bit that
; says whether it fitted is the quotient's. After sixteen passes the
; quotient has replaced the dividend and **the remainder is simply what
; is left** -- so `/` and `MOD` are one routine and MOD's only cost is
; its own entry in the dispatch.
;
; The four registers are all spoken for -- dividend, remainder -- so the
; divisor lives in page 0 and the counter in X, which nothing in the
; loop touches. Two ISA details make the inner loop short: `POP Rd`
; sets Z and N but **not C**, so the carry that decides the trial
; subtraction survives restoring the register it borrowed; and `ADDW SP`
; sets no flags, so the copy that was not needed is dropped without a
; second thought.
; ---------------------------------------------------------------------

; udiv16 -- unsigned R0:R1 / R2:R3. Quotient in R0:R1, remainder in DREM.
udiv16: ST   [DVSR],R2
        ST   [DVSR+1],R3
        CLR  R2                 ; the remainder
        CLR  R3
        LDW  X,#16
.loop:  SHL  R0                 ; the dividend left, its top bit out
        ROL  R1
        ROL  R2                 ; and on into the remainder
        ROL  R3
        PUSH R3                 ; the trial subtraction, undone if it
        PUSH R2                 ;   borrows
        PUSH R1
        LD   R1,[DVSR]
        SUB  R2,R1
        LD   R1,[DVSR+1]        ; LD leaves C alone, so the borrow keeps
        SBC  R3,R1
        POP  R1                 ; and so does POP
        BCS  .fits
        POP  R2                 ; it borrowed: put the remainder back
        POP  R3
        BRA  .next
.fits:  ADDW SP,#2              ; it fitted: the copy is not wanted
        ADD  R0,#1              ; and the quotient gains a bit
.next:  DECW X
        BNE  .loop
        ST   [DREM],R2
        ST   [DREM+1],R3
        RET

; idiv16 -- signed R0:R1 / R2:R3, truncating toward zero, with the
; remainder taking the dividend's sign. That is what BBC BASIC's DIV and
; MOD do, and what C settled on later.
idiv16: PUSH R3
        PUSH R2
        CLR  R2
        ST   [DSGN],R2
        TST  R1
        BPL  .dpos
        MOV  R2,#3              ; a negative dividend flips both
        ST   [DSGN],R2
        CALL negp16
.dpos:  POP  R2
        POP  R3
        TST  R3
        BPL  .vpos
        PUSH R1                 ; a negative divisor flips the quotient
        PUSH R0                 ;   only
        MOV  R0,R2
        MOV  R1,R3
        CALL negp16
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        PUSH R0                 ; DSGN needs a register and both of
        LD   R0,[DSGN]          ;   R0:R1 are the dividend
        XOR  R0,#1
        ST   [DSGN],R0
        POP  R0
.vpos:  TST  R2
        BNE  .go
        TST  R3
        BNE  .go
        MOV  R0,#E_DIV0
        ST   [ERR],R0
        CLR  R0
        CLR  R1
        RET
.go:    CALL udiv16
        LD   R2,[DSGN]
        BTST R2,#2              ; bit 1: the remainder follows the
                                ;   dividend. BTST takes a *mask*, not a
                                ;   bit number, so #1 tested bit 0 and
                                ;   MOD was right by accident.
        BEQ  .rok
        PUSH R1
        PUSH R0
        LD   R0,[DREM]
        LD   R1,[DREM+1]
        CALL negp16
        ST   [DREM],R0
        ST   [DREM+1],R1
        POP  R0
        POP  R1
.rok:   LD   R2,[DSGN]
        BTST R2,#1              ; bit 0: and so does the quotient
        BEQ  .qok
        CALL negp16
.qok:   RET

; ismod -- C clear if MOD stands at Y, and Y stepped past it.
;
; MOD has no token: TOKTAB is full at 36 entries, because `lookup`
; computes $80 + index and a 37th would be $A4, which is the numeric
; literal. So it arrives as three characters and is recognised as three
; characters. A second table starting at $A5 is the escape hatch if one
; is ever really needed; it has not been.
ismod:  LD   R0,[Y]
        CALL nupper
        CMP  R0,#$4D            ; 'M'
        BNE  .no
        INCW Y
        LD   R0,[Y]
        CALL nupper
        CMP  R0,#$4F            ; 'O'
        BNE  .b1
        INCW Y
        LD   R0,[Y]
        CALL nupper
        CMP  R0,#$44            ; 'D'
        BNE  .b2
        INCW Y
        CLC
        RET
.b2:    DECW Y
.b1:    DECW Y
.no:    SEC
        RET

; mdrhs -- the operand after a * / or MOD, with the running value kept.
mdrhs:  PUSH R1
        PUSH R0
        CALL prim
        MOV  R2,R0
        MOV  R3,R1
        POP  R0
        POP  R1
        RET

; ---------------------------------------------------------------------
; ctab -- one byte per character, and the whole of what varidx needs to
; know about one.
;
;   bit 7  may appear inside a name
;   bit 6  may start one, which is to say it is a letter
;   bits 0-5  the letter's index, already case-folded
;
; The fold, the letter test and the resident variable's index are one
; indexed load between them, and the second lookup costs nothing extra
; because X is still pointing at the table.
; ---------------------------------------------------------------------
ctab:
        .byte $00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00
        .byte $00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00
        .byte $00,$00,$00,$00,$80,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00
        .byte $80,$80,$80,$80,$80,$80,$80,$80,$80,$80,$00,$00,$00,$00,$00,$00
        .byte $00,$C0,$C1,$C2,$C3,$C4,$C5,$C6,$C7,$C8,$C9,$CA,$CB,$CC,$CD,$CE
        .byte $CF,$D0,$D1,$D2,$D3,$D4,$D5,$D6,$D7,$D8,$D9,$00,$00,$00,$00,$80
        .byte $00,$C0,$C1,$C2,$C3,$C4,$C5,$C6,$C7,$C8,$C9,$CA,$CB,$CC,$CD,$CE
        .byte $CF,$D0,$D1,$D2,$D3,$D4,$D5,$D6,$D7,$D8,$D9,$00,$00,$00,$00,$00
        ; 128 bytes, ASCII only: both indexers test bit 7 first, so the
        ; token half of the old 256 was one hundred twenty-eight zeros.

; ---------------------------------------------------------------------
; DO ... LOOP, with an optional WHILE or UNTIL at either end.
;
;   DO                LOOP              runs forever
;   DO WHILE c        LOOP              tests at the top
;   DO                LOOP UNTIL c      tests at the bottom, always once
;   DO UNTIL c        LOOP WHILE d      both, if anyone wants that
;
; The frame is where the body starts and which record that was, and the
; body starts *at* the WHILE or UNTIL rather than after it -- so LOOP
; jumps back to the token and the top test is re-evaluated without the
; frame having to remember whether there was one.
;
; EXIT and a failed top test are the same thing: drop the frame and walk
; forward to the matching LOOP, counting nested DOs on the way.
; ---------------------------------------------------------------------

; dofr -- X on the innermost open frame.
dofr:   LD   R0,[DDEPTH]
        SUB  R0,#1
        MOV  R1,#DOFR
        MUL  R0,R1
        ADDW X,#DOSTK
        RET

e_dos:  MOV  R0,#E_DOS
        ST   [ERR],R0
        RET

h_do:   LD   R0,[DDEPTH]
        CMP  R0,#MAXDO
        BCS  e_dos
        ADD  R0,#1
        ST   [DDEPTH],R0
        CALL dofr
        MOV  R0,YL
        ST   [X],R0
        INCW X
        MOV  R0,YH
        ST   [X],R0
        INCW X
        LD   R0,[LREC]
        ST   [X],R0
        INCW X
        LD   R0,[LREC+1]
        ST   [X],R0
        ; fall into docond

; docond -- test a `DO WHILE`/`DO UNTIL` condition, if there is one.
;
; **Separate from h_do because the second time round is not the first.**
; The frame keeps Y pointing just past the `DO` token, and `doback`
; restores it -- so if that re-entered through `stmt`, `stmt` would
; dispatch the `WHILE` sitting there as though it were a statement, and
; `sttab[$8A]` is `bad`. The loop ran once and then said `?SYNTAX ERROR`
; on its own second iteration. `LOOP WHILE` never showed it because
; nothing follows the `DO` in that form.
;
; So the condition is a routine, entered from both ends: h_do falls into
; it having pushed the frame, and doback jumps to it having restored
; one. A plain `DO` finds neither keyword and goes straight to stmt,
; which is what it did before.
docond: SKIPSP
        CMP  R2,#K_WHILE
        BEQ  .w
        CMP  R2,#K_UNTIL
        BEQ  .u
        JMP  stmt
.w:     INCW Y
        CALL eval
        MOV  R2,R0
        OR   R2,R1
        BNE  .on
        JMP  doquit
.u:     INCW Y
        CALL eval
        MOV  R2,R0
        OR   R2,R1
        BEQ  .on
        JMP  doquit
.on:    JMP  stmt

h_loop: LD   R0,[DDEPTH]
        BEQ  e_dos              ; LOOP without DO
        SKIPSP
        CMP  R2,#K_WHILE
        BEQ  .w
        CMP  R2,#K_UNTIL
        BEQ  .u
        JMP  doback
.w:     INCW Y
        CALL eval
        MOV  R2,R0
        OR   R2,R1
        BNE  .b
        JMP  dopop
.u:     INCW Y
        CALL eval
        MOV  R2,R0
        OR   R2,R1
        BEQ  .b
        JMP  dopop
.b:     JMP  doback

; doback -- round again, from the frame.
doback: CALL dofr
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        INCW X
        LD   R2,[X]
        ST   [LREC],R2
        INCW X
        LD   R2,[X]
        ST   [LREC+1],R2
        MOV  YL,R0
        MOV  YH,R1
        CALL ipoll
        JMP  docond             ; not stmt -- see docond

; dopop -- the loop is done and we are already past its LOOP.
dopop:  LD   R0,[DDEPTH]
        SUB  R0,#1
        ST   [DDEPTH],R0
        JMP  stmt

; h_exit / doquit -- leave from anywhere inside, which means finding the
; LOOP that closes this DO.
h_exit: LD   R0,[DDEPTH]
        BNE  doquit
        JMP  e_dos              ; EXIT with no loop open, and out of
                                ;   branch reach from down here
doquit: LD   R0,[DDEPTH]
        SUB  R0,#1
        ST   [DDEPTH],R0
        CLR  R0
        ST   [DNEST],R0
.scan:  SKIPSP
        TST  R2
        BEQ  .eol
        CMP  R2,#K_DO
        BEQ  .in
        CMP  R2,#K_LOOP
        BEQ  .out
        CALL skiptok
        BRA  .scan
.in:    LD   R0,[DNEST]
        ADD  R0,#1
        ST   [DNEST],R0
        CALL skiptok
        BRA  .scan
.out:   LD   R0,[DNEST]
        BEQ  .done
        SUB  R0,#1
        ST   [DNEST],R0
        CALL skiptok
        BRA  .scan
        ; The rest of that line belongs to the LOOP -- its WHILE or
        ; UNTIL and their expression -- so it goes with it.
.done:  LD   R2,[Y]
        TST  R2
        BEQ  .fin
        CALL skiptok
        BRA  .done
.fin:   JMP  stmt
.eol:   CALL nextline
        BCS  .scan
        RET                     ; the program ended inside the loop

; ---------------------------------------------------------------------
; The string functions.
;
; All of them are **plain names**, matched against a small table, not
; keywords. TOKTAB is full: `lookup` computes $80 + index and a 37th
; entry would be $A4, which is the numeric literal. The escape hatch is
; a second table from $A5, and it has not been needed -- a name costs a
; table entry here and nothing in the tokeniser.
;
; They are cheap for one reason: the argument has already appended
; itself to the accumulator by the time the function runs, so LEFT$ and
; friends are a length change and at most a move *within* the
; accumulator. Nothing allocates, nothing copies to the heap, and
; nothing has to be freed.
; ---------------------------------------------------------------------

; sopen -- step over the '(' ',' or ')' that has to be there.
sopen:  SKIPSP
        INCW Y
        RET

; strim -- of the argument that starts at R2, keep R0 characters from
; offset R3, moved down to R2. Both are clamped to what is there, which
; is what makes LEFT$(a$,99) the whole string rather than an error.
strim:  PUSHW X
        PUSHW Y
        LD   R1,[SLEN]
        SUB  R1,R2              ; how much the argument left
        CMP  R3,R1
        BCC  .in
        CLR  R0                 ; the offset is past the end: empty
        CLR  R3
        BRA  .move
.in:    PUSH R1
        SUB  R1,R3              ; what is left after the offset
        CMP  R0,R1
        BCC  .keep
        MOV  R0,R1
.keep:  POP  R1
.move:  PUSH R0
        LD   R1,[SACC]
        MOV  XL,R1
        LD   R1,[SACC+1]
        MOV  XH,R1
        MOV  R1,XL
        MOV  YL,R1
        MOV  R1,XH
        MOV  YH,R1
        ADDW X,R2               ; the destination
        ADDW Y,R2
        ADDW Y,R3               ; and the source
        MOV  R1,R0
        TST  R1
        BEQ  .done
.mv:    LD   R3,[Y+]
        ST   [X],R3
        INCW X
        SUB  R1,#1
        BNE  .mv
.done:  POP  R0
        ADD  R0,R2
        ST   [SLEN],R0
        MOV  R0,#1
        ST   [STYPE],R0
        POPW Y
        POPW X
        RET

sleft:  CALL sopen              ; '('
        LD   R2,[SLEN]
        PUSH R2
        CALL eval               ; the string, appended where R2 says
        CALL earg               ; ( expression )
        POP  R2
        CLR  R3
        JMP  strim

sright: CALL sopen
        LD   R2,[SLEN]
        PUSH R2
        CALL eval
        CALL earg               ; ( expression )
        POP  R2
        PUSH R0
        LD   R3,[SLEN]
        SUB  R3,R2              ; what the argument left
        POP  R0
        PUSH R3
        CMP  R3,R0
        BCS  .fits
        MOV  R0,R3              ; more asked for than there is
.fits:  POP  R3
        SUB  R3,R0              ; so the offset is the rest of it
        JMP  strim

smid:   CALL sopen
        LD   R2,[SLEN]
        PUSH R2
        CALL eval
        CALL sopen              ; ','
        CALL eval               ; where to start, counting from one
        PUSH R0
        CALL earg               ; ( expression )
        POP  R3
        TST  R3
        BEQ  .z
        SUB  R3,#1              ; one-based, as every BASIC has it
.z:     POP  R2
        JMP  strim

; schr -- CHR$(n). The one that makes a string out of nothing.
schr:   CALL earg               ; ( expression )
        CALL sputc
        MOV  R0,#1
        ST   [STYPE],R0
        RET

; sasc -- ASC(a$), and the accumulator forgets the argument again.
sasc:   CALL sopen
        LD   R2,[SLEN]
        PUSH R2
        CALL eval
        CALL sopen
        POP  R2
        LD   R0,[SLEN]
        SUB  R0,R2
        BEQ  .empty
        PUSHW X
        LD   R0,[SACC]
        MOV  XL,R0
        LD   R0,[SACC+1]
        MOV  XH,R0
        ADDW X,R2
        LD   R0,[X]
        POPW X
        CLR  R1
        BRA  .done
.empty: CLR  R0                 ; ASC("") is zero, not an error
        CLR  R1
.done:  ST   [SLEN],R2
        PUSH R0
        CLR  R0
        ST   [STYPE],R0
        POP  R0
        RET

; ---------------------------------------------------------------------
; The keyboard, as a program sees it.
;
; Two functions, because they answer two different questions and one of
; them cannot answer the other. INKEY takes the next key out of the ring
; the interrupt fills -- what was *typed*, in order, each key once. That
; is what a menu wants and it is the C64's GET.
;
; It is not what a game wants. A queue delivers a held key once, then
; nothing until auto-repeat starts, and it can only ever name one key at
; a time -- so left-and-fire is not expressible. KEY(c) reads the bitmap
; sw/kbd.asm maintains instead: is that key down *now*, asked of as many
; keys as you like. The C64 hit this exact wall, which is why its games
; read PEEK(197) rather than using GET, and why they then dropped to the
; CIA when one key at a time turned out not to be enough either.
; ---------------------------------------------------------------------

; Both reach outside the interpreter, and they are the only things here
; that do: `s_serialkey` is the editor's, and `kdbit` is sw/kbd.asm's.
; Neither exists when interp.asm is assembled on its own, so a harness
; that does that supplies them -- sim/test_interp.py and sim/test_asm.py
; stub both, and sim/test_run.py exercises the real ones on the whole
; system, which is the only place they mean anything.

; INKEY -- the next key, or 0 if none. No parentheses: `IF INKEY = 27`.
;
; s_serialkey is the editor's, and it is deliberately not bypassed: it
; is the one place that turns both a terminal's ESC [ A and the PS/2
; decoder's $80+n into K_UP, so a program gets the same code for a
; cursor key whichever keyboard the machine has in front of it.
inkey:  CALL s_serialkey
        PUSH R0
        CLR  R0
        ST   [STYPE],R0
        POP  R0
        RET

; KEY(c) -- is raw Set 2 scancode c held? TRUE (-1) or FALSE (0).
;
; The argument is a scancode and not ASCII, because this asks about a
; key and not about a character: shift is a key, the cursors are keys,
; and $1C is the one under your left middle finger whether or not it is
; currently producing an A. docs/04-system.md lists the ones a game
; reaches for.
ikey:   CALL earg               ; ( expression )
        MOV  R1,R0
        CALL kdbit              ; X on the byte, R0 the mask
        LD   R1,[X]
        AND  R0,R1
        BEQ  .up
        MOV  R0,#$FF            ; TRUE is -1, all ones (D47)
        MOV  R1,#$FF
        BRA  .fin
.up:    CLR  R0
        CLR  R1
.fin:   PUSH R0
        CLR  R0
        ST   [STYPE],R0
        POP  R0
        RET

; isbuilt -- the name in NBUF a builtin? C clear and X on its handler.
isbuilt:
        PUSHW Y
        LDW  X,#btab
.each:  MOV  R0,XL
        ST   [BENT],R0
        MOV  R0,XH
        ST   [BENT+1],R0
        LD   R0,[X]
        BEQ  .miss
        LD   R1,[NLEN]
        CMP  R0,R1
        BNE  .next
        INCW X
        LDW  Y,#NBUF
        MOV  R1,R0
.cmp:   LD   R2,[X]
        INCW X
        LD   R3,[Y+]
        SUB  R2,R3
        BNE  .next
        SUB  R1,#1
        BNE  .cmp
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        MOV  XL,R0
        MOV  XH,R1
        POPW Y
        CLC
        RET
.next:  LD   R0,[BENT]          ; back to the entry and over it whole
        MOV  XL,R0
        LD   R0,[BENT+1]
        MOV  XH,R0
        LD   R0,[X]
        ADDW X,R0
        ADDW X,#3
        BRA  .each
.miss:  POPW Y
        SEC
        RET

; Length, the name, then the handler. Six characters is NSIG, and
; RIGHT$ is exactly six.
btab:   .byte 3,"L","E","N"
        .word slen
        .byte 5,"L","E","F","T","$"
        .word sleft
        .byte 6,"R","I","G","H","T","$"
        .word sright
        .byte 4,"M","I","D","$"
        .word smid
        .byte 4,"C","H","R","$"
        .word schr
        .byte 3,"A","S","C"
        .word sasc
        .byte 4,"S","T","R","$"
        .word sstr
        .byte 3,"V","A","L"
        .word sval
        .byte 5,"I","N","S","T","R"
        .word sinstr
        .byte 5,"I","N","K","E","Y"
        .word inkey
        .byte 3,"K","E","Y"
        .word ikey
        .byte 3,"R","N","D"
        .word irnd
        .byte 5,"T","I","M","E","R"
        .word itimer
        .byte 5,"V","P","E","E","K"
        .word ivpeek
        .byte 4,"F","M","U","L"
        .word ifmul
        .byte 4,"F","D","I","V"
        .word ifdiv
        .byte 3,"F","I","X"
        .word ifix
        .byte 0

; ---------------------------------------------------------------------
; CALL and RETURN.
;
; **A SUB is found once, at RUN, not searched for at every call.** The
; scan below walks the program before a statement executes and gives
; each `SUB name` a name-table entry holding the record it starts at, so
; `CALL` is the same lookup a variable is. That is also the only moment
; the program's first record is known without keeping a pointer to it:
; `irun` is entered with LREC on it.
;
; The name gets a '#' appended, the way an array's gets a '(' -- the
; suffix is the namespace, so a SUB and a variable of the same spelling
; are simply different names and nothing needs a type field.
;
; v1 takes no arguments and returns nothing; data crosses through
; variables, which is the bargain BBC BASIC's PROC made before it grew
; parameters.
; ---------------------------------------------------------------------

e_call: MOV  R0,#E_CALL
        ST   [ERR],R0
        RET

; subname -- the name in NBUF becomes the SUB of that name.
subname:
        LD   R0,[NLEN]
        CMP  R0,#NSIG
        BCS  .bump
        PUSH R0
        LDW  X,#NBUF
        ADDW X,R0
        MOV  R0,#$23            ; '#'
        ST   [X],R0
        POP  R0
.bump:  ADD  R0,#1
        ST   [NLEN],R0
        RET

; cfr -- X on the frame at CDEPTH.
cfr:    LD   R0,[CDEPTH]
        MOV  R1,#CALLFR
        MUL  R0,R1
        LD   R0,[CSTK]
        MOV  R2,XL
        ADD  R2,R0
        MOV  XL,R2
        LD   R0,[CSTK+1]
        MOV  R2,XH
        ADC  R2,R0
        MOV  XH,R2
        RET

; subscan -- every SUB in the program, entered into the name table.
; Called with LREC on the first record and it leaves LREC elsewhere, so
; the caller saves it.
subscan:
        CALL openline
.each:  SKIPSP
        CMP  R2,#K_SUB
        BNE  .next
        INCW Y
        SKIPSP
        CALL nscan
        CALL subname
        CALL nfind              ; X on the value
        LD   R0,[LREC]
        ST   [X],R0
        INCW X
        LD   R0,[LREC+1]
        ST   [X],R0
.next:  CALL nextline
        BCS  .each
        RET

h_call: LD   R0,[CDEPTH]
        CMP  R0,#MAXCALL
        BCC  .room
        JMP  e_call
.room:  SKIPSP
        CALL nscan
        CALL subname
        CALL nlook
        BCC  .found
        ; Not a SUB. [D45](../docs/01-decisions.md) put the assembler's
        ; labels in this same table, so a *plain* name that is there is
        ; a block of machine code and CALL means call it. Dropping the
        ; '#' is all that separates the two namespaces.
        LD   R0,[NLEN]
        SUB  R0,#1
        ST   [NLEN],R0
        CALL nlook
        BCC  .native
        JMP  e_call             ; neither a SUB nor a label
.native:
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        MOV  XL,R0
        MOV  XH,R1
        PUSHW Y                 ; the block owns the registers, not Y
        CALL [X]
        POPW Y
        JMP  stmt
.found: LD   R0,[X]
        INCW X
        LD   R1,[X]
        PUSH R1                 ; where we are going
        PUSH R0
        CALL cfr                ; and where to come back to
        MOV  R0,YL
        ST   [X],R0
        INCW X
        MOV  R0,YH
        ST   [X],R0
        INCW X
        LD   R0,[LREC]
        ST   [X],R0
        INCW X
        LD   R0,[LREC+1]
        ST   [X],R0
        LD   R0,[CDEPTH]
        ADD  R0,#1
        ST   [CDEPTH],R0
        POP  R0
        POP  R1
        ST   [LREC],R0
        ST   [LREC+1],R1
        CALL openline
        SKIPSP
        INCW Y                  ; the SUB token
        SKIPSP
        CALL nscan              ; and its name
        JMP  stmt

h_ret:  LD   R0,[CDEPTH]
        BNE  .live
        JMP  e_call             ; RETURN without CALL
.live:  SUB  R0,#1
        ST   [CDEPTH],R0
        CALL cfr
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        INCW X
        LD   R2,[X]
        ST   [LREC],R2
        INCW X
        LD   R2,[X]
        ST   [LREC+1],R2
        MOV  YL,R0
        MOV  YH,R1
        CALL ipoll
        JMP  stmt


; A SUB definition met in the flow of execution is stepped over whole.
;
; It lives at the end and not beside `bad` for h_asm's reason: it
; grew from seven instructions to fifteen and put `BCC h_let`, the
; dispatcher's hot path, four bytes out of branch range.
; It spans records now that CALL can reach it, so this is h_asm's
; job with a different terminator rather than a walk to end of line.
h_sub:  CALL nextline
        BCC  .off
        SKIPSP
        CMP  R2,#K_END
        BNE  h_sub
        INCW Y
        SKIPSP
        CMP  R2,#K_SUB
        BNE  h_sub
        INCW Y
        JMP  stmt
.off:   MOV  R0,#E_DONE         ; the program ended inside it
        ST   [ERR],R0
        RET

; sstr -- STR$(n).
;
; `udiv16` once more: divide by ten until nothing is left and the
; remainders are the digits, least significant first. They go on the
; processor stack because the accumulator can only be appended to and
; there is nowhere to build them the right way round -- so they are
; pushed backwards and popped forwards, which costs one byte each and
; no buffer at all.
sstr:   CALL earg               ; ( expression )
        CLR  R2
        ST   [SDIG],R2
        TST  R1
        BPL  .digits
        PUSH R1                 ; a negative wears its sign first and
        PUSH R0                 ;   has its magnitude divided
        MOV  R0,#$2D            ; '-'
        CALL sputc
        POP  R0
        POP  R1
        CALL negp16
.digits:
        MOV  R2,#10
        CLR  R3
        CALL udiv16
        LD   R2,[DREM]
        ADD  R2,#$30            ; '0'
        PUSH R2
        LD   R2,[SDIG]
        ADD  R2,#1
        ST   [SDIG],R2
        MOV  R2,R0              ; zero divides once and prints "0"
        OR   R2,R1
        BNE  .digits
.emit:  LD   R2,[SDIG]
        TST  R2
        BEQ  .done
        SUB  R2,#1
        ST   [SDIG],R2
        POP  R0
        CALL sputc
        BRA  .emit
.done:  MOV  R0,#1
        ST   [STYPE],R0
        RET

; sval -- VAL(a$). The argument has appended itself, so this reads the
; accumulator's tail and then forgets it again.
sval:   CALL sopen
        LD   R2,[SLEN]
        PUSH R2
        CALL eval
        CALL sopen
        POP  R2
        PUSHW Y                 ; Y is the token pointer; borrow it
        LD   R0,[SACC]
        MOV  YL,R0
        LD   R0,[SACC+1]
        MOV  YH,R0
        ADDW Y,R2
        LD   R3,[SLEN]
        SUB  R3,R2
        ST   [SDIG],R3          ; characters to read
        ST   [SLEN],R2          ; and the accumulator drops them
        CLR  R0
        CLR  R1
        CLR  R3
        ST   [DSGN],R3          ; no division here, so DSGN is spare
        LD   R3,[SDIG]
        TST  R3
        BEQ  .fin
        LD   R2,[Y]
        CMP  R2,#$2D            ; '-'
        BNE  .loop
        INCW Y
        SUB  R3,#1
        ST   [SDIG],R3
        MOV  R2,#1
        ST   [DSGN],R2
.loop:  LD   R3,[SDIG]
        TST  R3
        BEQ  .fin
        LD   R2,[Y]
        CMP  R2,#$30
        BCC  .fin               ; anything but a digit ends it, which is
        CMP  R2,#$3A            ;   what makes VAL("12AB") twelve
        BCS  .fin
        INCW Y
        SUB  R3,#1
        ST   [SDIG],R3
        PUSH R2
        MOV  R2,#10
        CLR  R3
        CALL imul16
        POP  R2
        SUB  R2,#$30
        ADD  R0,R2
        MOV  R2,#0
        ADC  R1,R2
        BRA  .loop
.fin:   LD   R2,[DSGN]
        BEQ  .out
        CALL negp16
.out:   POPW Y
        CLR  R2
        ST   [STYPE],R2
        RET

; ---------------------------------------------------------------------
; sinstr -- INSTR(a$, b$): where b$ sits inside a$, counting from one,
; or zero.
;
; Both arguments append, so they arrive end to end in the accumulator
; with the split between them and nothing on the heap. The four offsets
; live in MTMP -- the multiply scratch, which is free here because both
; arguments are already evaluated and nothing multiplies afterwards.
; They are byte offsets because SLEN is a byte.
; ---------------------------------------------------------------------
sinstr: CALL sopen
        LD   R2,[SLEN]
        PUSH R2                 ; where the haystack starts
        CALL eval
        LD   R2,[SLEN]
        PUSH R2                 ; and where the needle does
        CALL earg               ; ( expression )
        POP  R3
        POP  R2
        ST   [MTMP],R2          ; base -- no eval runs past here, so the
        ST   [MTMP+2],R3        ;   multiply scratch is ours
        MOV  R0,R3
        SUB  R0,R2
        ST   [MTMP+1],R0        ; the haystack's length
        LD   R0,[SLEN]
        SUB  R0,R3
        ST   [MTMP+3],R0        ; the needle's
        LD   R0,[MTMP]          ; the accumulator forgets them both and
        ST   [SLEN],R0          ;   the answer is a number
        CLR  R0
        ST   [STYPE],R0
        LD   R0,[MTMP+3]
        BNE  .search
        MOV  R0,#1              ; an empty needle is found at one
        CLR  R1
        RET
.search:
        CLR  R3                 ; the offset being tried
.try:   LD   R0,[MTMP+3]
        ADD  R0,R3
        LD   R1,[MTMP+1]
        CMP  R0,R1              ; does the needle still fit?
        BEQ  .cmp
        BCS  .none
.cmp:   PUSHW X
        PUSHW Y                 ; Y is the token pointer; borrow it
        LD   R0,[SACC]
        MOV  XL,R0
        LD   R0,[SACC+1]
        MOV  XH,R0
        MOV  R0,XL
        MOV  YL,R0
        MOV  R0,XH
        MOV  YH,R0
        LD   R0,[MTMP]
        ADDW X,R0
        ADDW X,R3               ; X on the haystack at this offset
        LD   R0,[MTMP+2]
        ADDW Y,R0               ; Y on the needle
        LD   R1,[MTMP+3]
.c:     LD   R0,[X]
        INCW X
        LD   R2,[Y+]
        SUB  R0,R2
        BNE  .no
        SUB  R1,#1
        BNE  .c
        POPW Y
        POPW X
        MOV  R0,R3
        ADD  R0,#1              ; one-based, as MID$ is
        CLR  R1
        RET
.no:    POPW Y
        POPW X
        ADD  R3,#1
        BRA  .try
.none:  CLR  R0
        CLR  R1
        RET

; ---------------------------------------------------------------------
; The break flag.
;
; **The interpreter never touches a device.** It reads one byte, and
; something else keeps that byte fresh -- which is how both machines
; this design borrows from did it. The C64's `STOP` routine "does not
; scan the keyboard": the 60 Hz jiffy IRQ calls UDTIM, which scans the
; RUN/STOP row and sets a flag, and BASIC polls the flag. The BBC's
; 100 Hz interrupt sets the escape flag and BASIC polls that. Neither
; interpreter can afford to look at hardware, and neither can this one:
; a device read blocks, costs a bus cycle, and would have to know which
; wire the key came in on.
;
; `sw/basic.bas` owns the interrupt that sets this. It lives here so
; that sim/test_interp.py, which has no editor, still links.
ibreak  = $FF25                 ; in the workspace page, see basic.bas

; ipoll -- checked at the loop back-edges only, because those are the
; only places a program can spin: NEXT going round, LOOP going round,
; GOTO, and RETURN. A straight-line program cannot fail to end.
ipoll:  LD   R2,[ibreak]
        BEQ  .none
        CLR  R2
        ST   [ibreak],R2
        MOV  R2,#E_STOP
        ST   [ERR],R2
.none:  RET

; CONST name = value. An interpreter has no compile step in which to
; fold a constant, so this is an assignment -- which is what every
; interpreted BASIC that has the keyword does. It is not write
; protected, and saying so is better than refusing the statement.
h_const:
        SKIPSP                  ; the dispatcher left Y on the space
        JMP  h_let

; =====================================================================
; Graphics and sound: tokens $A5-$AE, and RND/TIMER/VPEEK in btab.
;
; **Every command is a thin wrapper over an auto-increment port.** The
; chip does the address arithmetic -- the pixel port multiplies y by
; the stride in a DSP and steps X by itself, the sprite, palette and
; sound ports walk their own arrays -- so a handler here is `eval` the
; arguments and a handful of stores. The one loop in the whole section
; that isn't argument parsing is LINE's Bresenham, and HLINE's span is
; one store per pixel because the hardware steps X.
; =====================================================================

GVMODE  = $FE10
GSCRX   = $FE16                 ; four registers: X L/H then Y L/H
GPALI   = $FE1E
GPALD   = $FE1F
GVRAL   = $FE26
GVRAH   = $FE27
GVRST   = $FE28
GVRD    = $FE29
GSPRI   = $FE2A
GSPRD   = $FE2B
GSPREN  = $FE2C
GPIXXL  = $FE34
GPIXXH  = $FE35
GPIXYL  = $FE36
GPIXYH  = $FE37
GPIXD   = $FE38
GSNDI   = $FE50
GSNDD   = $FE51

; The frame counter iisr keeps (TIMER reads it, VSYNC waits on it), the
; random seed, and scratch for up to five parsed arguments plus LINE's
; working set. Equates into the $FF00 workspace page (see basic.bas):
; page 0 is spoken for, and a .space would ship its zeros in the image.
; init seeds rseed to 1 after the page clear -- a zeroed xorshift stays
; zero forever.
frames  = $FF26                 ; 2
rseed   = $FF28                 ; 2
garg    = $FF2A                 ; 10
lwk     = $FF34                 ; 10  dx, dy, err, sx, sy -- all words
FORSTK  = $FF3E                 ; 72  MAXFOR frames of FORFR

; gargs -- R3 comma-separated expressions into garg, low byte first.
; eval leaves Y on the comma (its operator scan has already skipped the
; spaces), so stepping over it is one INCW, the h_poke idiom.
gargs:  LDW  X,#garg
.g:     PUSHW X
        PUSH R3
        CALL eval
        POP  R3
        POPW X
        ST   [X],R0
        INCW X
        ST   [X],R1
        INCW X
        SUB  R3,#1
        BEQ  .done
        INCW Y                  ; the comma
        BRA  .g
.done:  RET

; MODE n -- the preset, with the display kept enabled. dorun puts mode
; 0 back when the program is over, so an error in mode 4 is readable.
h_mode: MOV  R3,#1
        CALL gargs
        LD   R0,[garg]
        AND  R0,#$0F
        OR   R0,#$80
        ST   [GVMODE],R0
        JMP  stmt

; VSYNC -- hold until the frame counter moves. Bounded by one frame, so
; it needs no break poll; it is the pacing primitive every game loop
; wants and nothing else provides.
h_vsync:
        LD   R0,[frames]
.vw:    LD   R1,[frames]
        CMP  R1,R0
        BEQ  .vw
        JMP  stmt

; SCROLL x,y -- the fine-scroll registers, and that is the entire
; command: the engine moves where it reads, nothing moves in memory.
h_scroll:
        MOV  R3,#2
        CALL gargs
        LD   R0,[garg]
        ST   [GSCRX],R0
        LD   R0,[garg+1]
        ST   [GSCRX+1],R0
        LD   R0,[garg+2]
        ST   [GSCRX+2],R0
        LD   R0,[garg+3]
        ST   [GSCRX+3],R0
        JMP  stmt

; PALETTE i,v -- entry i becomes $0RGB. The R nibble goes first because
; that is the byte order the port commits on.
h_palette:
        MOV  R3,#2
        CALL gargs
        LD   R0,[garg]
        ST   [GPALI],R0
        LD   R0,[garg+3]
        ST   [GPALD],R0
        LD   R0,[garg+2]
        ST   [GPALD],R0
        JMP  stmt

; VPOKE a,b / VPEEK(a) -- the VRAM port. The step is set to +1 every
; time rather than trusted: some other user may have left it walking
; backwards by 256.
h_vpoke:
        MOV  R3,#2
        CALL gargs
        MOV  R0,#1
        ST   [GVRST],R0
        LD   R0,[garg]
        ST   [GVRAL],R0
        LD   R0,[garg+1]
        ST   [GVRAH],R0
        LD   R0,[garg+2]
        ST   [GVRD],R0
        JMP  stmt

; pixxy -- garg's first two words into the pixel port.
pixxy:  LD   R0,[garg]
        ST   [GPIXXL],R0
        LD   R0,[garg+1]
        ST   [GPIXXH],R0
        LD   R0,[garg+2]
        ST   [GPIXYL],R0
        LD   R0,[garg+3]
        ST   [GPIXYH],R0
        RET

; PLOT x,y,c -- one pixel, in the current mode's depth, masked by the
; hardware. Five stores end to end.
h_plot: MOV  R3,#3
        CALL gargs
        CALL pixxy
        LD   R0,[garg+4]
        ST   [GPIXD],R0
        JMP  stmt

; HLINE x,y,n,c -- n pixels rightward. One store each: the port steps X.
h_hline:
        MOV  R3,#4
        CALL gargs
        CALL pixxy
        LD   R1,[garg+6]
        LD   R2,[garg+4]
        LD   R3,[garg+5]
.hl:    MOV  R0,R2
        OR   R0,R3
        BEQ  .hd
        ST   [GPIXD],R1
        SUB  R2,#1
        BCS  .hl                ; C is *no borrow*: the high byte holds
        SUB  R3,#1
        BRA  .hl
.hd:    JMP  stmt

; SPRITE n,x,y,img,a -- descriptor n, whole. `img` is the pattern in
; 32-byte units; `a` packs what the descriptor scatters: bit 7 size,
; 6 enable, 5 V-flip, 4 H-flip, 3 behind the background. Setup of the
; patterns themselves is VPOKE's job, exactly as it is an assembly
; programmer's.
h_sprite:
        MOV  R3,#5
        CALL gargs
        LD   R0,[garg]
        ADD  R0,R0
        ADD  R0,R0
        ADD  R0,R0
        ST   [GSPRI],R0
        LD   R0,[garg+4]        ; b0: Y low
        ST   [GSPRD],R0
        LD   R0,[garg+8]        ; b1: size and enable, plus Y bit 8
        AND  R0,#$C0
        LD   R1,[garg+5]
        AND  R1,#$01
        OR   R0,R1
        ST   [GSPRD],R0
        LD   R0,[garg+2]        ; b2, b3: X
        ST   [GSPRD],R0
        LD   R0,[garg+3]
        AND  R0,#$03
        ST   [GSPRD],R0
        LD   R0,[garg+6]        ; b4, b5: the pattern address
        ST   [GSPRD],R0
        LD   R0,[garg+7]
        AND  R0,#$07
        ST   [GSPRD],R0
        LD   R0,[garg+8]        ; b6: flips and priority, a<<2
        AND  R0,#$38
        ADD  R0,R0
        ADD  R0,R0
        ST   [GSPRD],R0
        CLR  R0                 ; b7: the per-sprite bank nothing reads
        ST   [GSPRD],R0
        MOV  R0,#$01            ; the global gate: no descriptor shows
        ST   [GSPREN],R0        ;   until it opens, and using SPRITE at
                                ;   all is the statement that sprites
                                ;   are wanted. dorun closes it again.
        JMP  stmt

; SOUND v,pitch,vol,noise -- pitch is the phase increment (f ~ inc/2),
; vol 0-15, noise picks the LFSR over the square. Silence is vol 0.
; Two seeks because bytes 2-3 are the engine's phase and software
; leaves them alone.
h_sound:
        MOV  R3,#4
        CALL gargs
        LD   R0,[garg]
        ADD  R0,R0
        ADD  R0,R0
        ADD  R0,R0
        ST   [GSNDI],R0
        LD   R1,[garg+2]
        ST   [GSNDD],R1
        LD   R1,[garg+3]        ; the word commits on the odd byte
        ST   [GSNDD],R1
        ADD  R0,#4
        ST   [GSNDI],R0
        LD   R1,[garg+4]
        AND  R1,#$0F
        ST   [GSNDD],R1
        LD   R1,[garg+6]
        TST  R1
        BEQ  .sq
        MOV  R1,#$C0
        BRA  .sn
.sq:    MOV  R1,#$40
.sn:    ST   [GSNDD],R1
        JMP  stmt

; LINE x0,y0,x1,y1,c -- Bresenham, about six cycles a pixel through the
; port. The RTL cut DRAW_LINE for costing 200 LUT4; this is the same
; algorithm paid for in bytes instead. Coordinates are at most ten
; bits, so every quantity fits 16-bit signed arithmetic with room and
; the sign tests below cannot overflow.
h_line: MOV  R3,#5
        CALL gargs
        ; dx = |x1-x0|, sx = +-1 as a word
        LD   R0,[garg+4]
        LD   R1,[garg+5]
        LD   R3,[garg]
        SUB  R0,R3
        LD   R3,[garg+1]
        SBC  R1,R3
        MOV  R2,#$01
        MOV  R3,#$00
        BGE  .lx
        CALL negp16
        MOV  R2,#$FF
        MOV  R3,#$FF
.lx:    ST   [lwk],R0
        ST   [lwk+1],R1
        MOV  R0,R2
        ST   [lwk+6],R0
        MOV  R0,R3
        ST   [lwk+7],R0
        ; dy = -|y1-y0|, sy = +-1
        LD   R0,[garg+6]
        LD   R1,[garg+7]
        LD   R3,[garg+2]
        SUB  R0,R3
        LD   R3,[garg+3]
        SBC  R1,R3
        MOV  R2,#$FF
        MOV  R3,#$FF
        BLT  .ly                ; negative already is -|dy|
        CALL negp16
        MOV  R2,#$01
        MOV  R3,#$00
.ly:    ST   [lwk+2],R0
        ST   [lwk+3],R1
        MOV  R0,R2
        ST   [lwk+8],R0
        MOV  R0,R3
        ST   [lwk+9],R0
        ; err = dx + dy
        LD   R0,[lwk]
        LD   R1,[lwk+1]
        LD   R2,[lwk+2]
        LD   R3,[lwk+3]
        ADD  R0,R2
        ADC  R1,R3
        ST   [lwk+4],R0
        ST   [lwk+5],R1
.lp:    CALL pixxy              ; garg 0..3 are the walking x0,y0
        LD   R0,[garg+8]
        ST   [GPIXD],R0
        ; the last pixel is drawn before the walk is tested
        LD   R0,[garg]
        LD   R2,[garg+4]
        XOR  R0,R2
        MOV  R1,R0
        LD   R0,[garg+1]
        LD   R2,[garg+5]
        XOR  R0,R2
        OR   R1,R0
        LD   R0,[garg+2]
        LD   R2,[garg+6]
        XOR  R0,R2
        OR   R1,R0
        LD   R0,[garg+3]
        LD   R2,[garg+7]
        XOR  R0,R2
        OR   R1,R0
        BNE  .go
        JMP  stmt
.go:    ; if 2*err >= dy: err += dy, x0 += sx
        LD   R0,[lwk+4]
        LD   R1,[lwk+5]
        ADD  R0,R0
        ADC  R1,R1
        PUSH R1                 ; both tests must see this same e2 --
        PUSH R0                 ;   err changes between them
        LD   R2,[lwk+2]
        LD   R3,[lwk+3]
        SUB  R0,R2
        SBC  R1,R3
        BLT  .ny
        LD   R0,[lwk+4]
        ADD  R0,R2
        ST   [lwk+4],R0
        LD   R0,[lwk+5]
        ADC  R0,R3
        ST   [lwk+5],R0
        LD   R0,[garg]
        LD   R2,[lwk+6]
        ADD  R0,R2
        ST   [garg],R0
        LD   R0,[garg+1]
        LD   R2,[lwk+7]
        ADC  R0,R2
        ST   [garg+1],R0
.ny:    ; if 2*err <= dx: err += dx, y0 += sy
        POP  R2
        POP  R3
        LD   R0,[lwk]
        LD   R1,[lwk+1]
        SUB  R0,R2
        SBC  R1,R3
        BLT  .nx
        LD   R2,[lwk]
        LD   R0,[lwk+4]
        ADD  R0,R2
        ST   [lwk+4],R0
        LD   R2,[lwk+1]
        LD   R0,[lwk+5]
        ADC  R0,R2
        ST   [lwk+5],R0
        LD   R0,[garg+2]
        LD   R2,[lwk+8]
        ADD  R0,R2
        ST   [garg+2],R0
        LD   R0,[garg+3]
        LD   R2,[lwk+9]
        ADC  R0,R2
        ST   [garg+3],R0
.nx:    JMP  .lp


; earg -- "( expression )": the prologue every one-argument builtin
; shares, ten of them. The tail call keeps sopen error handling and
; its RET as the return.
earg:   CALL sopen
        CALL eval
        JMP  sopen

; negp16 -- R1:R0 negated, R2/R3 untouched (neg16 above clobbers them). The flags are the final ADC us; every caller
; stores or falls onward, none reads them (checked site by site).
negp16: XOR  R0,#$FF
        XOR  R1,#$FF
        ADD  R0,#1
        ADC  R1,#0
        RET

; RND(n) -- 0..n-1 from a 16-bit xorshift (7, 9, 8: full period), the
; remainder coming free out of udiv16. RND(0) is the raw word.
irnd:   CALL earg               ; ( expression )
        PUSH R1
        PUSH R0
        LD   R0,[rseed]
        LD   R1,[rseed+1]
        MOV  R2,R0
        MOV  R3,R1
        ADD  R2,R2              ; s ^= s << 7
        ADC  R3,R3
        ADD  R2,R2
        ADC  R3,R3
        ADD  R2,R2
        ADC  R3,R3
        ADD  R2,R2
        ADC  R3,R3
        ADD  R2,R2
        ADC  R3,R3
        ADD  R2,R2
        ADC  R3,R3
        ADD  R2,R2
        ADC  R3,R3
        XOR  R0,R2
        XOR  R1,R3
        MOV  R2,R1              ; s ^= s >> 9
        SHR  R2
        XOR  R0,R2
        XOR  R1,R0              ; s ^= s << 8
        ST   [rseed],R0
        ST   [rseed+1],R1
        POP  R2                 ; n, the divisor
        POP  R3
        PUSH R0
        MOV  R0,R2
        OR   R0,R3
        BEQ  .raw
        POP  R0
        CALL udiv16             ; remainder in R2/R3
        MOV  R0,R2
        MOV  R1,R3
        JMP  retnum
.raw:   POP  R0
        JMP  retnum

; TIMER -- frames since power-on, wrapping at 65536: eighteen minutes,
; which is a game's whole afternoon. No parentheses, like INKEY.
itimer: LD   R0,[frames]
        LD   R1,[frames+1]
        JMP  retnum

; VPEEK(a) -- the port's prefetch is armed by the address write and the
; data read stalls until the byte is real, so this is exact.
ivpeek: CALL earg               ; ( expression )
        MOV  R2,R0
        MOV  R0,#1
        ST   [GVRST],R0
        ST   [GVRAL],R2
        ST   [GVRAH],R1
        LD   R0,[GVRD]
        CLR  R1
        JMP  retnum

; =====================================================================
; The language round-out: INPUT, DATA/READ/RESTORE, ON GOTO, and the
; last of the graphics -- TILE, CLG, PITCH, GTEXT -- plus 8.8 fixed
; point as three functions. Scalar variables only for READ and INPUT;
; an array element is a place a program can copy to afterwards.
; =====================================================================

dptr:   .word 0                 ; where the next DATA item is
dneed:  .byte 1                 ; ...or 1: dptr is a record to scan from

; INPUT var -- digits echoed until Return, minus sign honoured,
; everything else ignored. Numeric scalars only.
h_input:
        SKIPSP
        CALL varidx
        PUSHW X
        PUSHW Y                 ; the editor's routines use Y freely
        CLR  R2
        ST   [garg],R2
        ST   [garg+1],R2
        ST   [garg+2],R2
.k:     CALL s_getkey
        TST  R1
        BNE  .k                 ; a named key is not a digit
        CMP  R0,#$0D
        BEQ  .cr
        CMP  R0,#$2D
        BNE  .dg
        MOV  R2,#1
        ST   [garg+2],R2
        BRA  .echo
.dg:    CMP  R0,#$30
        BCC  .k
        CMP  R0,#$3A
        BCS  .k
        PUSH R0
        LD   R2,[garg]          ; value = value * 10 + digit
        LD   R3,[garg+1]
        ADD  R2,R2
        ADC  R3,R3
        MOV  R0,R2
        MOV  R1,R3
        ADD  R2,R2
        ADC  R3,R3
        ADD  R2,R2
        ADC  R3,R3
        ADD  R2,R0
        ADC  R3,R1
        POP  R0
        PUSH R0
        SUB  R0,#$30
        ADD  R2,R0
        ADC  R3,#0              ; NOT `CLR R0 / ADC R3,R0`: CLR is
                                ; SUB Rd,Rd, and C is *no borrow*, so
                                ; CLR always leaves C set -- a phantom
                                ; +256 on every digit
        ST   [garg],R2
        ST   [garg+1],R3
        POP  R0
.echo:  PUSH R1
        PUSH R0
        CALL s_emit
        POP  R0
        POP  R1
        BRA  .k
.cr:    CALL pnl
        POPW Y
        POPW X
        LD   R0,[garg]
        LD   R1,[garg+1]
        LD   R2,[garg+2]
        TST  R2
        BEQ  .st
        CALL negp16
.st:    ST   [X],R0
        INCW X
        ST   [X],R1
        JMP  stmt

h_restore:
        CALL drst
        JMP  stmt

; drst -- DATA rewound to the program's first record, unpositioned.
; RUN does the same thing at the same address, so it is one routine.
drst:   MOV  R0,#1
        ST   [dneed],R0
        CLR  R0
        ST   [dptr],R0
        MOV  R0,#$02
        ST   [dptr+1],R0
        RET

; READ a, b, c -- each target takes the next DATA item.
h_read: SKIPSP
        CALL varidx
        PUSHW X
        CALL dnext
        POPW X
        LD   R2,[ERR]
        TST  R2
        BEQ  .ok
        JMP  stmt               ; stmt sees ERR and stops
.ok:    ST   [X],R0
        INCW X
        ST   [X],R1
        SKIPSP
        CMP  R2,#$2C
        BNE  .done
        INCW Y
        BRA  h_read
.done:  JMP  stmt

; dnext -- the next DATA value into R0/R1, or ?OUT OF DATA. The walk is
; token-wise through the stored records: a byte-wise scan would read the
; binary halves of literals as line ends, the skiptok lesson over again.
dnext:  PUSHW Y
        LDW  Y,[dptr]
        LD   R0,[dneed]
        BNE  .rec
        BRA  .at
.rec:   LD   R2,[PEND]          ; past the program: out of data
        LD   R3,[PEND+1]
        MOV  R0,YL
        MOV  R1,YH
        SUB  R0,R2
        SBC  R1,R3
        BLT  .in
        MOV  R0,#E_DATA
        ST   [ERR],R0
        POPW Y
        RET
.in:    INCW Y                  ; lineno, length
        INCW Y
        INCW Y
.tw:    LD   R0,[Y]
        TST  R0
        BEQ  .nrec
        CMP  R0,#K_DATA
        BEQ  .fnd
        CALL skiptok
        BRA  .tw
.nrec:  INCW Y
        BRA  .rec
.fnd:   INCW Y
        CLR  R0
        ST   [dneed],R0
        BRA  .val
.at:
.val:   LD   R0,[Y]             ; spaces are stored, commas separate,
        CMP  R0,#$20            ; and either may follow the other
        BEQ  .adv
        CMP  R0,#$2C
        BNE  .v1
.adv:   INCW Y
        BRA  .val
.v1:    TST  R0
        BEQ  .lend
        CLR  R2
        CMP  R0,#$2D
        BNE  .v2
        MOV  R2,#1
        INCW Y
        LD   R0,[Y]
.v2:    CMP  R0,#K_NUM
        BEQ  .lit
        MOV  R0,#E_SYN          ; something in a DATA list that is not
        ST   [ERR],R0           ;   a number
        POPW Y
        RET
.lit:   INCW Y
        LD   R0,[Y]
        INCW Y
        LD   R1,[Y]
        INCW Y
        STW  [dptr],Y           ; parked on whatever follows; the entry
                                ; loop above eats spaces and commas
        TST  R2
        BEQ  .pos
        CALL negp16
.pos:   POPW Y
        RET
.lend:  INCW Y                  ; this list is spent: the next record
        STW  [dptr],Y
        MOV  R0,#1
        ST   [dneed],R0
        BRA  .rec

; ON n GOTO l1, l2, ... -- the nth number in the list, or fall through.
; The list is numbers, not expressions, which is what makes walking it
; without evaluating it possible.
h_on:   CALL eval
        ST   [garg],R0
        SKIPSP
        INCW Y                  ; the GOTO
.on1:   SKIPSP
        CMP  R2,#K_NUM
        BNE  .off
        LD   R0,[garg]
        SUB  R0,#1
        ST   [garg],R0
        BEQ  .take
        INCW Y
        INCW Y
        INCW Y
        SKIPSP
        CMP  R2,#$2C
        BNE  .off
        INCW Y
        BRA  .on1
.take:  INCW Y
        LD   R0,[Y]
        INCW Y
        LD   R1,[Y]
        JMP  goton
.off:   JMP  h_else             ; no pick: the rest of the line is a
                                ;   thing to step over

; TILE x,y,t,a -- one map entry in mode 2: the map is stride 128 at the
; bottom of VRAM, an entry is index then attribute.
h_tile: MOV  R3,#4
        CALL gargs
        MOV  R0,#1
        ST   [GVRST],R0
        LD   R0,[garg+2]        ; y*128: hi = y>>1, lo = (y&1)<<7
        MOV  R1,R0
        SHR  R1
        AND  R0,#$01
        MOV  R2,#$00
        TST  R0
        BEQ  .t0
        MOV  R2,#$80
.t0:    LD   R0,[garg]          ; + x*2
        ADD  R0,R0
        ADD  R2,R0
        ADC  R1,#0
        ST   [GVRAL],R2
        ST   [GVRAH],R1
        LD   R0,[garg+4]
        ST   [GVRD],R0
        LD   R0,[garg+6]
        ST   [GVRD],R0
        JMP  stmt

; CLG c -- the whole surface to one colour, straight through the VRAM
; port: 240 rows of stride bytes from VID_BASE. The byte pattern is the
; colour replicated to the mode's depth, and the replication is a
; multiply: c*$FF at 1 bpp, c*$55 at 2, c*$11 at 4, c*$01 at 8.
h_clg:  MOV  R3,#1
        CALL gargs
        LD   R0,[$FE11]         ; bpp out of VID_CTRL
        SHR  R0
        SHR  R0
        AND  R0,#$03
        LDW  X,#clgm
        ADDW X,R0
        LD   R1,[X]
        LD   R2,[garg]
        AND  R2,R1
        ADDW X,#4
        LD   R1,[X]
        MUL  R2,R1              ; the pattern lands in XL
        MOV  R2,XL
        MOV  R0,#1
        ST   [GVRST],R0
        LD   R0,[$FE12]
        ST   [GVRAL],R0
        LD   R0,[$FE13]
        ST   [GVRAH],R0
        MOV  R3,#240
.row:   LD   R1,[$FE14]         ; stride low; 0 means 256, and the
.col:   ST   [GVRD],R2          ;   store-first loop makes that true
        SUB  R1,#1
        BNE  .col
        SUB  R3,#1
        BNE  .row
        JMP  stmt
clgm:   .byte $01,$03,$0F,$FF
        .byte $FF,$55,$11,$01

; PITCH v,p -- the two pitch bytes and nothing else: slides and vibrato
; without re-stating the volume.
h_pitch:
        MOV  R3,#2
        CALL gargs
        LD   R0,[garg]
        ADD  R0,R0
        ADD  R0,R0
        ADD  R0,R0
        ST   [GSNDI],R0
        LD   R0,[garg+2]
        ST   [GSNDD],R0
        LD   R0,[garg+3]
        ST   [GSNDD],R0
        JMP  stmt

; GTEXT x,y,s$,c -- 8x8 text in any bitmap mode, opaque, from the 1bpp
; font the boot stub seeds at VRAM $FC00 (8 bytes a glyph, from space).
; Set bits paint c, clear bits paint 0, and the pixel port streams each
; row -- so a character is 8 VRAM reads and 64 pixel writes.
h_gtext:
        MOV  R3,#2
        CALL gargs
        INCW Y                  ; the comma before the string
        CALL eval               ; the string, into the accumulator
        INCW Y                  ; ...and the one after it
        CLR  R0
        ST   [STYPE],R0         ; the colour is a number
        CALL eval
        ST   [garg+4],R0
        CLR  R0
        ST   [garg+6],R0        ; the index along the string
.ch:    LD   R0,[garg+6]
        LD   R1,[SLEN]
        CMP  R0,R1
        BCC  .chgo
        JMP  stmt
.chgo:  LD   R2,[SACC]
        MOV  XL,R2
        LD   R2,[SACC+1]
        MOV  XH,R2
        LD   R2,[X+R0]          ; the character
        SUB  R2,#$20
        MOV  R1,R2              ; glyph address: $FC00 + g*8
        SHR  R1
        SHR  R1
        SHR  R1
        SHR  R1
        SHR  R1
        ADD  R1,#$FC
        MOV  R0,R2
        ADD  R0,R0
        ADD  R0,R0
        ADD  R0,R0
        MOV  R2,#1
        ST   [GVRST],R2
        ST   [GVRAL],R0
        ST   [GVRAH],R1
        CLR  R3                 ; the row
.grow:  LD   R2,[GVRD]          ; its eight bits, MSB leftmost
        LD   R0,[garg]
        ST   [GPIXXL],R0
        LD   R0,[garg+1]
        ST   [GPIXXH],R0
        LD   R0,[garg+2]
        ADD  R0,R3
        ST   [GPIXYL],R0
        LD   R0,[garg+3]
        ADC  R0,#0
        ST   [GPIXYH],R0
        PUSH R3
        MOV  R3,#8
.gbit:  CLR  R0
        ADD  R2,R2              ; the top bit into C
        BCC  .g0
        LD   R0,[garg+4]
.g0:    ST   [GPIXD],R0
        SUB  R3,#1
        BNE  .gbit
        POP  R3
        ADD  R3,#1
        CMP  R3,#8
        BNE  .grow
        LD   R0,[garg]          ; x += 8, on to the next character
        ADD  R0,#8
        ST   [garg],R0
        LD   R0,[garg+1]
        ADC  R0,#0
        ST   [garg+1],R0
        LD   R0,[garg+6]
        ADD  R0,#1
        ST   [garg+6],R0
        JMP  .ch

; ---------------------------------------------------------------------
; 8.8 fixed point, as three functions. A value cell is 16 bits on this
; machine, so the fraction that fits it is 8.8: -128..127 and change,
; 1/256 steps -- sub-pixel positions and speeds, which is what games
; want a fraction for. + and - already work; FMUL and FDIV carry the
; point; FIX drops it. F(2.5) is spelled 640, or 2*256+128.
; ---------------------------------------------------------------------

; ffargs -- (a, b) parsed, signs folded into garg+4, both made positive.
ffargs: CALL sopen
        CALL eval
        ST   [garg],R0
        ST   [garg+1],R1
        INCW Y
        CALL eval
        CALL sopen
        ST   [garg+2],R0
        ST   [garg+3],R1
        LD   R2,[garg+1]
        XOR  R2,R1
        AND  R2,#$80
        ST   [garg+4],R2
        LD   R0,[garg+1]
        AND  R0,#$80
        BEQ  .p0
        LD   R0,[garg]
        LD   R1,[garg+1]
        CALL negp16
        ST   [garg],R0
        ST   [garg+1],R1
.p0:    LD   R0,[garg+3]
        AND  R0,#$80
        BEQ  .p2
        LD   R0,[garg+2]
        LD   R1,[garg+3]
        CALL negp16
        ST   [garg+2],R0
        ST   [garg+3],R1
.p2:    RET

; fsign -- the R0/R1 result negated if the folded sign says so, then
; the usual number-return dance.
fsign:  LD   R2,[garg+4]
        TST  R2
        BEQ  retnum
        CALL negp16
        ; retnum -- R0/R1 as a number: the tail every value-returning
        ; builtin needs, kept once.
retnum: PUSH R0
        CLR  R0
        ST   [STYPE],R0
        POP  R0
        RET

; FMUL(a,b) -- (a*b) >> 8, by four hardware multiplies. MUL leaves the
; product in X and its operands alone, which is what makes this short.
ifmul:  CALL ffargs
        LD   R0,[garg]
        LD   R1,[garg+2]
        MUL  R0,R1              ; al*bl -- only its high byte survives
        MOV  R2,XH
        CLR  R3
        LD   R0,[garg]
        LD   R1,[garg+3]
        MUL  R0,R1              ; al*bh
        MOV  R0,XL
        ADD  R2,R0
        MOV  R0,XH
        ADC  R3,R0
        LD   R0,[garg+1]
        LD   R1,[garg+2]
        MUL  R0,R1              ; ah*bl
        MOV  R0,XL
        ADD  R2,R0
        MOV  R0,XH
        ADC  R3,R0
        LD   R0,[garg+1]
        LD   R1,[garg+3]
        MUL  R0,R1              ; ah*bh, shifted left eight
        MOV  R0,XL
        ADD  R3,R0
        MOV  R0,R2
        MOV  R1,R3
        JMP  fsign

; FDIV(a,b) -- (a<<8)/b: the integer quotient takes the high byte and
; eight more restoring steps make the fraction, on the remainder udiv16
; hands back with the divisor still parked in DVSR.
ifdiv:  CALL ffargs
        LD   R0,[garg+2]
        LD   R1,[garg+3]
        MOV  R2,R0
        OR   R2,R1
        BNE  .go
        MOV  R0,#E_DIV0
        ST   [ERR],R0
        RET
.go:    MOV  R2,R0
        MOV  R3,R1
        LD   R0,[garg]
        LD   R1,[garg+1]
        CALL udiv16             ; q in R0/R1, remainder in R2/R3
        ST   [garg],R0          ; q's low byte becomes the high byte
        CLR  R0                 ; the fraction, a bit at a time
        MOV  R1,#8
.fd:    ADD  R2,R2
        ADC  R3,R3
        ADD  R0,R0
        PUSH R1
        LD   R1,[DVSR]
        SUB  R2,R1
        LD   R1,[DVSR+1]
        SBC  R3,R1
        BCS  .yes               ; C is *no borrow*: it fitted
        LD   R1,[DVSR]
        ADD  R2,R1
        LD   R1,[DVSR+1]
        ADC  R3,R1
        BRA  .nf
.yes:   ADD  R0,#1
.nf:    POP  R1
        SUB  R1,#1
        BNE  .fd
        LD   R1,[garg]
        JMP  fsign

; FIX(a) -- the integer part: an arithmetic shift right by the point.
ifix:   CALL earg               ; ( expression )
        MOV  R0,R1
        CLR  R1
        MOV  R2,R0
        AND  R2,#$80
        BEQ  .fx
        MOV  R1,#$FF
.fx:    JMP  retnum
