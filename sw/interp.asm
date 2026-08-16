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

; ---- the tokens, generated from TOKTAB by tools/vocab.py.
;
; **These were twenty-five equates written out here**, which is the
; numbering hand-copied into a second place -- and [D65] then called the
; table order frozen on the strength of it. `poe check` fails if the
; generated file is stale, so `sw/toktab.asm` can be reordered or given
; a flags byte by rebuilding ([D68]).
;
; Generating them found four that had a definition and no user:
; `K_FUNC`, `K_RET`, `K_GOTOT` -- and `K_CONST`, which said `$84` long
; after `CONST` was removed and `RUN` took that byte, so anything that
; had reached for it would have matched the wrong keyword.
;
; $95 is INT. It is in toktab as the compiled dialect's type name, so
; the editor tokenises it before the interpreter can look it up, and a
; btab entry spelled "INT" could never be reached -- the token byte
; never spells itself. It is a builtin here instead, dispatched in
; `prim` the way PEEK is. $94 (AS) and $96 (BYTE) are still unused.
        .include "tokens.asm"

; ---- state
;
; The page 0 map and the error codes are in sw/lowram.asm, which the
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


; CALLB1 and friends: the convention for calling compiled BASIC.
; Included here rather than by basic.bas because this file is what
; uses them, and sim/test_interp.py assembles this file against a
; stub that never sees the editor.
        .include "call.asm"

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
        CALL vwipe              ; every variable to zero, and the heap
        CLR  R0
        ST   [FDEPTH],R0        ; and no FOR loop is running
        ST   [DDEPTH],R0        ; nor a DO, which a second RUN must not
                                ;   inherit from the first
        ST   [EDEPTH],R0        ; at statement level, not inside a paren
        ST   [CDEPTH],R0        ; nor a call in progress
        ST   [FSP],R0           ; nor a float operand pending -- see
                                ;   idrct for why this one matters most
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

; ---------------------------------------------------------------------
; The former editor commands, as statements. Thin token-side parsers
; over the same compiled cores the editor always used -- one
; vocabulary, so a program can SAVE itself, LOAD its sequel, CLS, or
; ask FREE, exactly as on the machines this one descends from. No
; guards and no ILLEGAL DIRECT: DELETE from a running program is legal
; and self-inflicted. The one exception is RUN, direct-only by ruling:
; a program restarting itself would stack a frame per restart.
; ---------------------------------------------------------------------

; rangel -- [lit ['-' [lit]]] into garg+0 and garg+2, presence in R3:
; bit 0 first number, bit 1 dash, bit 2 second number.
rangel: CLR  R3
        SKIPSP
        CMP  R2,#T_LIT
        BNE  .dash
        CALL rlit
        ST   [garg],R0
        ST   [garg+1],R1
        MOV  R3,#1
.dash:  SKIPSP
        CMP  R2,#$2D
        BNE  .out
        INCW Y
        OR   R3,#2
        SKIPSP
        CMP  R2,#T_LIT
        BNE  .out
        CALL rlit
        ST   [garg+2],R0
        ST   [garg+3],R1
        OR   R3,#4
.out:   RET

; rlit -- Y on T_LIT: the two bytes into R0:R1, Y past.
rlit:   INCW Y
        LD   R0,[Y]
        INCW Y
        LD   R1,[Y]
        INCW Y
        RET

esyn:   MOV  R0,#E_SYN
        ST   [ERR],R0
        RET

; **pshab is gone.** It pushed garg as two stacked call arguments, which
; is how a *compiled* SUB took them -- and sw/basic.bas went with [D68],
; so LIST, DELETE and RENUM read garg directly and nothing called it.
; cnext -- where every command handler ends. A compiled core clobbers
; X and Y both, so the walk resumes from LREC, which survives: the
; command was its line's last statement by construction (there is no
; ':'), and nextline already knows how to say "that was the direct
; line" or open the next record with Y rebuilt.
; cnext -- abandon the rest of this line and go to the next.
;
; **Only for statements that moved the program under the interpreter.**
; DELETE, RENUM, a program LOAD and a MERGE all rewrite the records that
; `LREC` is pointing into, so carrying on where we stood would run
; whatever landed there. Everything else -- CLS, FREE, DIR, SAVE, ERA,
; DRIVE, COMPACT, OPENIN, CLOSE, LIST, LOAD..AT -- leaves the program
; alone and ends in `JMP stmt`, which continues on the line and reaches
; the next record by itself when the line runs out.
;
; **That distinction did not matter until [D86].** With no separator
; there was never anything after these statements, so skipping the rest
; of the line was free; the moment `:` became legal, `CLS:PRINT 1`
; silently dropped the PRINT. Thirteen of the seventeen were wrong the
; day the colon landed.
cnext:  CALL nextline
        BCS  .cn
        RET
.cn:    JMP  stmt


; LIST [a[-[b]]]
h_list: CALL rangel
        TST  R3
        BNE  .some
        CLR  R0                 ; bare LIST: everything
        ST   [garg],R0
        ST   [garg+1],R0
        BRA  .all
.some:  CMP  R3,#1
        BNE  .dash
        LD   R0,[garg]          ; one number: that line alone
        ST   [garg+2],R0
        LD   R0,[garg+1]
        ST   [garg+3],R0
        BRA  .go
.dash:  CMP  R3,#7
        BEQ  .go
.all:   MOV  R0,#$FF            ; open-ended: to 32767
        ST   [garg+2],R0
        MOV  R0,#$7F
        ST   [garg+3],R0
.go:    LD   R0,[garg]          ; the bounds, in registers now
        LD   R1,[garg+1]
        LD   R2,[garg+2]
        LD   R3,[garg+3]
        CALL prg_list
        JMP  stmt 

; DELETE a[-[b]]
h_del:  CALL rangel
        BTST R3,#1
        BNE  .r1                ; no first number: nothing to do
        JMP  stmt 
.r1:    BTST R3,#2
        BNE  .r2
        LD   R0,[garg]          ; DELETE n: that line
        ST   [garg+2],R0
        LD   R0,[garg+1]
        ST   [garg+3],R0
        BRA  .go
.r2:    BTST R3,#4
        BNE  .go
        MOV  R0,#$FF            ; DELETE n-: to the end
        ST   [garg+2],R0
        MOV  R0,#$7F
        ST   [garg+3],R0
.go:    LD   R0,[garg]
        LD   R1,[garg+1]
        LD   R2,[garg+2]
        LD   R3,[garg+3]
        CALL prg_del
        JMP  cnext

; RENUM [start [step]]
h_renum:
        MOV  R0,#10
        ST   [garg],R0
        ST   [garg+2],R0
        CLR  R0
        ST   [garg+1],R0
        ST   [garg+3],R0
        SKIPSP
        CMP  R2,#T_LIT
        BNE  .go
        CALL rlit
        ST   [garg],R0
        ST   [garg+1],R1
        SKIPSP
        CMP  R2,#$2C            ; RENUM 100,5 and RENUM 100 5
        BNE  .st
        INCW Y
        SKIPSP
.st:    CMP  R2,#T_LIT
        BNE  .go
        CALL rlit
        ST   [garg+2],R0
        ST   [garg+3],R1
.go:    LD   R0,[garg]          ; start in R0:R1, step in R2
        LD   R1,[garg+1]
        LD   R2,[garg+2]
        CALL prg_renum
        JMP  cnext

h_new:  CALL prg_new              ; the program deleted itself: stop, as
        MOV  R0,#E_DONE         ; the C64 did
        ST   [ERR],R0
        RET

h_free: CALL prg_free           ; the count, then the word for it
        CALL num_putu           ; a size, not a value: 40,448 > 32767
        LDW  X,#MSGFREE
        CALL con_puts
        CALL con_nl
        JMP  stmt 

; vwipe -- A-Z to zero, then the heap and the name table.
;
; RUN's variable clear, split out because CLEAR is exactly that and
; nothing else: the program, and where it is, are untouched.
vwipe:  LDW  X,#VARS
        MOV  R1,#52
.z:     CLR  R0
        ST   [X],R0
        INCW X
        SUB  R1,#1
        BNE  .z
        JMP  vclear

; ---------------------------------------------------------------------
; LOCAL name[,name] -- the caller's values come back on RETURN.
;
; **The same save stack a parameter uses, minus the assignment.** That
; is the whole of it, and the reason it earns its place at forty-odd
; bytes: once values can be saved and put back, a local is a parameter
; nobody passed.
;
; Zeroed after saving, which is BBC's behaviour and the only predictable
; choice -- leaving the caller's value visible would make a local read
; as whatever the caller last had.
; ---------------------------------------------------------------------
h_local:
        LD   R0,[CDEPTH]
        BNE  .live
        JMP  e_call             ; outside a SUB nothing would put it back
.live:  SKIPSP
        CALL varidx
        LD   R2,[ERR]
        BNE  .out
        MOV  R2,R0
        PUSH R2
        CALL lpush
        POP  R2
        LD   R0,[ERR]
        BNE  .out
        MOV  R0,R2
        PUSH R2
        CALL varaddr
        POP  R2
        CLR  R0
        ST   [X],R0
        INCW X
        ST   [X],R0
        CMP  R2,#52             ; a resident owns only those two
        BLO  .next
        INCW X
        ST   [X],R0
        INCW X
        ST   [X],R0
.next:  SKIPSP
        CMP  R2,#$2C            ; ',' -- another one
        BNE  .done
        INCW Y
        BRA  .live
.done:  JMP  stmt
.out:   RET

h_clear:
        CALL vwipe
        JMP  stmt

; ---------------------------------------------------------------------
; PAUSE n -- n frames, and the break key still works.
;
; Frames rather than milliseconds because `frames` is what the machine
; counts and what TIMER reports, so `PAUSE 60` and `TIMER` measure the
; same second. Sixty a second.
;
; **It polls `ipoll` rather than spinning.** A wait that cannot be
; interrupted is a machine that has hung as far as anyone watching is
; concerned, and this is the one statement whose whole job is to take a
; long time.
;
; The count is on the CPU stack, not in a claim: PAUSE cannot nest and
; the storage region has nothing spare.
; ---------------------------------------------------------------------
h_pause:
        CALL eval
        PUSH R1
        PUSH R0
.next:  LD   R0,[SP+0]
        LD   R1,[SP+1]
        MOV  R2,R0
        OR   R2,R1
        BEQ  .done
        LD   R2,[frames]        ; wait for the counter to tick once
.spin:  PUSH R2                 ; **ipoll returns the break flag in R2**
        CALL ipoll              ;   and this is the frame it is watching
        POP  R2                 ;   -- without the save, the compare
        LD   R0,[ERR]           ;   below was against 0 and PAUSE
                                ;   returned instantly, measured at
                                ;   zero frames waited
        BNE  .done
        LD   R0,[frames]
        CMP  R0,R2
        BEQ  .spin
        LD   R0,[SP+0]
        SUB  R0,#1
        ST   [SP+0],R0
        BCS  .next              ; carry set is no borrow ([D9])
        LD   R0,[SP+1]
        SUB  R0,#1
        ST   [SP+1],R0
        BRA  .next
.done:  ADDW SP,#2
        JMP  stmt

; ---------------------------------------------------------------------
; CONT -- resume the program the break key stopped.
;
; **Validated against the program, not only against a flag.** The record
; lives at a derived address above the name table, which is itself at
; PROGEND -- so editing the program moves it and the bytes read there
; are whatever happened to be in the heap. A saved LREC outside
; $0200..PROGEND cannot be a statement of the program that is loaded
; now, which is the same thing the C64 means by "editing a line loses
; CONT", arrived at from the other end.
; ---------------------------------------------------------------------
h_cont: CALL csave
        MOV  R0,XL
        ADD  R0,#9
        MOV  R1,XH
        MOV  R2,#0
        ADC  R1,R2
        MOV  XL,R0
        MOV  XH,R1
        LD   R0,[X]
        TST  R0
        BEQ  .no
        CLR  R0
        ST   [X],R0             ; one resume per break

        CALL csave
        LD   R0,[X]             ; the record it stopped in
        INCW X
        LD   R1,[X]
        INCW X
        PUSH R1                 ; ...checked before anything is restored
        PUSH R0
        LD   R2,[PROGEND]
        LD   R3,[PROGEND+1]
        SUB  R0,R2
        SBC  R1,R3
        BHS  .stale             ; at or past the end: a different program
        POP  R0
        POP  R1
        ST   [LREC],R0
        ST   [LREC+1],R1

        LD   R0,[X]             ; Y, kept while the depths go back
        INCW X
        PUSH R0
        LD   R0,[X]
        INCW X
        PUSH R0
        LD   R0,[X]
        ST   [FDEPTH],R0
        INCW X
        LD   R0,[X]
        ST   [DDEPTH],R0
        INCW X
        LD   R0,[X]
        ST   [EDEPTH],R0
        INCW X
        LD   R0,[X]
        ST   [CDEPTH],R0
        INCW X
        LD   R0,[X]
        ST   [LDEPTH],R0
        POP  R0
        MOV  YH,R0
        POP  R0
        MOV  YL,R0
        JMP  stmt

        ; **Not ?CALL, which means "no such SUB".** Four ways to get
        ; here and all of them are the same fact: there is no break to
        ; go back to. Nothing was stopped; the program was edited, so
        ; the saved record names a statement that is not there any more;
        ; NEW or RUN emptied it; or this break has already been
        ; continued once.
.stale: POP  R0
        POP  R1
.no:    MOV  R0,#E_CONT
        ST   [ERR],R0
        RET

h_cls:  CALL con_cls
        JMP  stmt 

; COLOR fg[, bg] -- the pen, which is CATTR: bg in the high nibble, fg
; in the low.
;
; **The background is optional and that is the whole design.** Changing
; ink is the common case by a wide margin, and a program that had to
; name the paper every time would either repeat itself or keep its own
; copy of it -- so `COLOR 14` reads the byte back and keeps the nibble
; it is not being asked about. Both are masked to 0-15, so no value can
; reach into the other's nibble.
;
; con_fill reads the same byte, so CLS and a scroll paint in the current
; paper rather than reverting to grey.
; CURSOR on[, rate] -- CUR_CTRL: bit 0 enables, bits 4:3 pick the
; blink.
;
; **Nothing here blinks anything.** `blink_r` counts frames in
; cool8_vregs.v and the rate selects which of its bits to test, so
; rate 0 is 8 frames a phase, 1 is 16, 2 is 32 and 3 short-circuits
; to solid. The phase also restarts whenever the cursor moves, which
; is what keeps it visible while a key is held -- none of which
; software could do as well per frame.
;
; A warm restart puts it back: `con_geom` writes $11 whatever a
; program left, so a demo cannot strand a machine with no cursor.
h_cursor:
        CALL eval               ; 0 off, 1 on
        AND  R0,#$01
        PUSH R0
        LD   R2,[Y]             ; a rate as well?
        CMP  R2,#$2C
        BEQ  .rate
        MOV  R0,#2              ; no: 32 frames a phase, the machine's
        BRA  .set
.rate:  INCW Y
        CALL eval
        AND  R0,#$03
.set:   ADD  R0,R0              ; the rate lives in bits 4:3
        ADD  R0,R0
        ADD  R0,R0
        POP  R2
        OR   R0,R2
        ST   [CUR_CTRL],R0
        JMP  stmt

h_color:
        CALL eval               ; the ink
        AND  R0,#$0F
        PUSH R0
        ; **The comma is read straight off Y, as h_poke reads its
        ; own.** `SKIPSP` here saw no comma at all and every paper
        ; silently became 0; the two-argument idiom in this file is
        ; `INCW Y` over a comma the evaluator left Y sitting on.
        LD   R2,[Y]
        CMP  R2,#$2C            ; ',' -- a paper as well?
        BEQ  .paper
        LD   R0,[CATTR]         ; no: keep the one already set
        AND  R0,#$F0
        BRA  .set
.paper: INCW Y
        CALL eval
        AND  R0,#$0F
        ; **Four adds, not MUL.** `MUL R0,R1` puts its product in
        ; X and leaves both registers alone -- `nentry` says so in
        ; its own comment -- so multiplying here left the paper
        ; exactly where it started and every one came out 0.
        ADD  R0,R0              ; into the high nibble
        ADD  R0,R0
        ADD  R0,R0
        ADD  R0,R0
.set:   POP  R2
        OR   R0,R2
        ST   [CATTR],R0
        JMP  stmt

h_run:  LD   R0,[LREC+1]        ; direct only: a program restarting
        CMP  R0,#>DIRBUF        ;   itself stacks a frame per restart
        BEQ  .ok
        JMP  esyn
.ok:
        CALL main_pre           ; where the program and the heap are
        CALL irun
        CALL main_err           ; ?WHAT IN nn, if it set ERR
        MOV  R0,#E_DONE
        ST   [ERR],R0
        RET

; idrct -- the staged record at DIRBUF, run with the machine's state
; LEFT ALONE. This is irun minus the variable clear: A-Z, arrays and
; the heap survive from the last run, which is what a direct PRINT A
; after a break is FOR -- the C64's direct mode with the BBC's manners.
; The caller (dodirect) has run the same preflight RUN gets, so a
; direct CALL reaches assembled ASM blocks and scanned SUB names, and
; PEND is progend: a direct GOTO lands in the program and simply keeps
; walking -- resume falls out of the record machinery.
idrct:  CLR  R0
        ST   [FDEPTH],R0        ; statement level, fresh
        ST   [DDEPTH],R0
        ST   [EDEPTH],R0
        ST   [CDEPTH],R0
        ST   [FSP],R0           ; **not optional.** fsav refuses past
                                ;   FSDEEP without pushing, and its
                                ;   caller pops regardless, so one
                                ;   over-nested expression leaves FSP
                                ;   five below zero -- and a byte
                                ;   underflows to 251, past every
                                ;   depth test. Every expression for
                                ;   the rest of the session then failed
                                ;   ?COMPLEX and returned rubbish:
                                ;   2 + 2 printed 1538. Resetting here
                                ;   bounds it to the statement.
        CALL drst               ; READ starts at the first DATA
        CLR  R0
        ST   [ibreak],R0
        LD   R0,[LREC]          ; subscan walks the program (LREC is
        PUSH R0                 ;   PROG here) exactly as irun's does
        LD   R0,[LREC+1]
        PUSH R0
        CALL subscan
        POP  R0
        POP  R0
        MOV  R0,#<DIRBUF        ; then the record is the staged one
        ST   [LREC],R0
        MOV  R0,#>DIRBUF
        ST   [LREC+1],R0
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
;
; A record on DIRBUF's page is the staged direct line: it has no next
; record by construction, and its address is the whole mark -- the BBC's
; immediate-mode test was address-based too, and for the same reason:
; nothing else can be there. Program records live from $0200 up to
; progend, which cannot reach USERTOP, and the system storage region
; starts above USERTOP.
;
; **This was `CMP R0,#$FF`**, from when DIRBUF was at $FF88 in the old
; workspace page. When the I/O page took that page and DIRBUF moved to
; the storage region ([D67]), the constant did not move with it, so
; every direct line walked off its own record into the heap: RUN printed
; nothing and `MODE 4` never reached the hardware. The high byte is
; taken from DIRBUF now, so the mark follows the buffer.
nextline:
        LD   R0,[LREC+1]
        CMP  R0,#>DIRBUF
        BNE  .adv
        CLC
        RET
.adv:   LD   R0,[LREC]          ; this record + 4 + its length
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
        ; **Ask about the record that just ran, before overwriting the
        ; pointer to it.** This tested `R1` -- the high byte of the
        ; *next* record -- after LREC had already been advanced, so it
        ; only answered correctly while a direct line began and ended on
        ; the same page. DIRBUF sits at $B5FA, six bytes below the
        ; boundary, so `PRINT 6` ends at $B602 and the next record is on
        ; page $B6: the test compared $B6 against $B5, said "not the
        ; direct line", and walked on. LREC then marched up through
        ; memory four bytes at a time reading zeros as empty records
        ; until it reached the image at $BB97 and tried to run it --
        ; which is where the `?SYNTAX` after every direct statement came
        ; from. The answer had already been printed, so the machine
        ; looked like it was working and complaining anyway.
        ;
        ; Still the page and not the whole address: `nextline` beside
        ; this makes the identical test, program records cannot reach
        ; $B5xx, and comparing both bytes was built and measured at
        ; **seven bytes more** for a robustness against DIRBUF moving to
        ; a shared page -- which `tools/memmap.py --check` would refuse
        ; anyway. Three bytes buys the fix; ten buys the fix and a
        ; second opinion.
        LD   R0,[LREC+1]
        CMP  R0,#>DIRBUF
        BEQ  .stop              ; the staged direct line has no next

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
.stop:  RET                     ; past the last line: stop
.open:  CALL openline
        JMP  stmt
.more:
        ; **The $80 split first, because every statement needs it.** A
        ; token dispatches; anything below is a name, a separator or a
        ; comment. This used to test the apostrophe -- the rarest of the
        ; three -- ahead of the split that decides all of them, so every
        ; token-led statement paid for a case it could not be.
        ;
        ; Putting the split first is what makes `:` free on that path
        ; rather than a third test in front of it.
        CMP  R2,#$80
        BCS  .tok
        ; **`:` is a separator, and it is all it is.** This loop already
        ; ran statement after statement to the end of a line -- a handler
        ; ends in `JMP stmt` and only a zero byte sends it to the next
        ; record -- so `A=5 PRINT A` has always worked and nobody could
        ; have guessed it. What did not work was the colon every BASIC
        ; programmer types, because it is below $80 and fell through to
        ; `h_let`, which read it as a variable name.
        ;
        ; Punctuation, not a token: stored as itself, costing no slot in
        ; TOKTAB, and LIST gives it back for nothing.
        CMP  R2,#$3A            ; ':'
        BEQ  .sep
        ; An apostrophe comment is stored as itself -- it is punctuation,
        ; so it gets no token. Sending it to h_rem is what keeps
        ; `' like this` from being parsed as a variable named `'`.
        CMP  R2,#$27
        BEQ  .rem
        JMP  h_let              ; a name: an assignment
.sep:   INCW Y
        BRA  stmt
.rem:   JMP  h_rem
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

; ---------------------------------------------------------------------
; REM, and the apostrophe stmt sends here: a comment.
;
; The tokeniser stores the text verbatim after the marker, so there is
; nothing here to interpret -- walk to the record's terminator and let
; the statement loop do what it already does with the end of a line.
;
; **Raw bytes, not skiptok.** A comment may contain a quote, and
; skiptok would take it for the start of a string and run past the
; terminator looking for the close.
; ---------------------------------------------------------------------
h_rem:  LD   R2,[Y]
        TST  R2
        BEQ  .out
        INCW Y
        BRA  h_rem
.out:   JMP  stmt

; END, and `END SUB` which is not the same statement at all.
;
; **Falling into `END SUB` used to stop the program.** A SUB returned
; only through `RETURN`; `END SUB` was a marker `h_sub` scanned for when
; stepping over a definition, and if execution ever reached one, `END`
; ran and set E_DONE. A sub whose last statement was not RETURN ended
; the whole program, silently and with the right answer already
; printed -- the shape of fault this file keeps producing.
h_end:  SKIPSP
        CMP  R2,#K_SUB
        BNE  .stop
        INCW Y                  ; over SUB: this is a return, not a stop
        JMP  h_ret
.stop:  MOV  R0,#E_DONE         ; a clean stop, not an error
        ST   [ERR],R0
        RET

; ---------------------------------------------------------------------
; v = <expression>
;
; A name is one letter here: A-Z are resident, which is BBC BASIC's
; A%-Z% and is why a loop counter costs nothing to find.
; ---------------------------------------------------------------------
; ---------------------------------------------------------------------
; MID$(a$, start [, n]) = expr -- the one assignment target that is not
; a variable or an array element.
;
; **A special case here because it is a special case in the language.**
; Every BASIC that has this implements it apart from ordinary assignment,
; because the left-hand side is a function call in every other context.
; The C64 has it; BBC BASIC does not.
;
; It **overwrites in place and never changes the length**, which is the
; whole reason it exists: no allocation, no garbage, and a fixed-width
; field can be rewritten as often as a program likes. Everything is
; clamped to what is there -- past the end writes nothing, too long a
; replacement is truncated -- so it cannot extend a string or run off
; the end of one.
; ---------------------------------------------------------------------

midnam: .byte "m","i","d","$","("

; ismid -- is the statement `MID$(`? C set and Y past it if so, Y
; untouched if not.
;
; Folded with OR $20, which turns a letter lower case and leaves `$` and
; `(` alone -- both already have bit 5 set. So this reads `mid$(` and
; `MID$(` alike without the tokeniser having to fold identifiers, which
; it does not: a name that is not a keyword is copied verbatim.
ismid:  PUSHW Y
        LDW  X,#midnam
        MOV  R3,#5
.mc:    LD   R0,[X]
        INCW X
        LD   R1,[Y]
        INCW Y
        OR   R1,#$20
        CMP  R0,R1
        BNE  .no
        SUB  R3,#1
        BNE  .mc
        POPW X                  ; matched: drop the saved Y, keep the walk
        SEC
        RET
.no:    POPW Y
        CLC
        RET

h_midst:
        CALL varidx             ; the target, X on its descriptor
        CMP  R0,#52
        BCS  .long
        JMP  esyn               ; A-Z is never a string, so nor is this
.long:  PUSHW X
        CALL isstr
        BCC  .str
        POPW X
        JMP  esyn
.str:   CALL sopen              ; ','
        CALL eval               ; where to start, counting from one
        PUSH R0
        ; **Two arguments means "to the end"**, the same shape `smid`
        ; uses for reading, and for the same reason: the count is asked
        ; for only if a ',' follows, and everything below clamps.
        SKIPSP
        CMP  R2,#$29            ; ')'
        BNE  .three
        INCW Y
        MOV  R0,#$FF
        BRA  .have
.three: CALL earg               ; , n )
.have:  PUSH R0
        SKIPSP
        INCW Y                  ; the '='
        CALL eval               ; the replacement, into the accumulator
        POP  R3                 ; how many
        POP  R2                 ; where
        POPW X                  ; the descriptor
        LD   R0,[ERR]
        BEQ  .go
        JMP  stmt
.go:    PUSHW Y                 ; Y is the token pointer; borrow it

        TST  R2                 ; one-based, and 0 reads as 1
        BNE  .s1
        MOV  R2,#1
.s1:    SUB  R2,#1              ; ...so this is the offset

        MOV  R1,#2
        LD   R1,[X+R1]          ; what the variable actually holds
        CMP  R2,R1
        BCC  .in
        BRA  .done              ; start past the end: nothing to write
.in:    SUB  R1,R2              ; room from there to the end
        CMP  R3,R1
        BCC  .n1
        MOV  R3,R1
.n1:    LD   R0,[SLEN]          ; and no more than there is to say
        CMP  R3,R0
        BCC  .n2
        MOV  R3,R0
.n2:    TST  R3
        BEQ  .done

        LD   R0,[X]             ; the heap bytes, at the offset
        INCW X
        LD   R1,[X]
        MOV  XL,R0
        MOV  XH,R1
        ADDW X,R2
        LD   R0,[SACC]
        MOV  YL,R0
        LD   R0,[SACC+1]
        MOV  YH,R0
.cp:    LD   R0,[Y+]
        ST   [X],R0
        INCW X
        SUB  R3,#1
        BNE  .cp
.done:  POPW Y
        JMP  stmt               ; `stmt` empties the accumulator, and a
                                ;   handler that does it too is six bytes
                                ;   saying what the loop already said

h_let:
        ; **One byte before anything else.** This is the hottest
        ; statement in the language -- `A = A + 1` inside a loop is here
        ; every iteration -- and MID$ on the left is rare, so the first
        ; character answers it and only a name beginning with M pays for
        ; the rest. Calling `ismid` unconditionally cost thirteen
        ; instructions per assignment to say no, which is the shape
        ; `nextline` was already caught in.
        LD   R0,[Y]
        OR   R0,#$20
        CMP  R0,#$6D            ; 'm', folded
        BNE  .let
        CALL ismid              ; MID$(a$,s[,n]) = ... ?
        BCS  h_midst
.let:   CALL varidx             ; R0 = the handle, Y past the name
        CMP  R0,#52
        BCC  .notstr            ; resident A-Z is never a string
        ; The subscript first, for the reason `prim` gives: the suffix
        ; test fired ahead of it, so `A$(3) = "x"` assigned the scalar
        ; A$ and left the subscript behind.
        SKIPSP
        CMP  R2,#$28            ; '('
        BEQ  .notstr
        PUSH R0
        CALL isflt
        POP  R0
        BCC  .flt
        PUSH R0
        CALL isstr
        POP  R0
        BCS  .notstr
        JMP  h_lets             ; X is on its descriptor already
.flt:   JMP  h_letf
.notstr:
        SKIPSP
        CMP  R2,#$28            ; '(' -- a subscripted assignment
        BNE  .scalar
        JMP  h_leta             ; it lives at the end, out of branch reach
.scalar:
        ST   [TVAR],R0
        SKIPSP
        INCW Y                  ; the '='
        CALL evali              ; [D88] a float crosses here, flooring
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
        ; **And the aux field, which this did not touch.** An entry is
        ; type, length, six name bytes, value and aux, and a slot is
        ; reused the moment NNAME goes back to zero -- so a new string
        ; variable landing on an old one's slot inherited its length
        ; while getting a zeroed address. Harmless for an integer, which
        ; does not use aux; for a string it is a descriptor half of
        ; which is somebody else's.
        INCW X
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
        CALL evali              ; [D88] the address is an integer
        MOV  XL,R0
        MOV  XH,R1
        PUSHW X
        INCW Y                  ; the comma
        CALL evali              ; ...and so is the byte
        POPW X
        ST   [X],R0
        JMP  stmt

; ---------------------------------------------------------------------
; emitc -- one character in R0:R1 to the screen.
;
; **`s_emit` is a compiled SUB, so its argument travels on the stack**,
; not in a register: `SUB emit(ch AS INT)` reads [SP+2] upward. Calling
; it with the character in R0 emits whatever happened to be pushed
; last, which is the bug this routine exists to stop anyone writing
; twice -- it cost a round here and broke INPUT's echo at the same
; time, and only a negative number showed it, because the wrong byte
; happened to be the value's own low byte.
;
; It lives here rather than beside its other caller in sw/ed.asm
; because this file is what both include paths share: sim/test_interp.py
; builds interp.asm against stubs and never sees the editor.
; ---------------------------------------------------------------------
; **`CALLB1` is gone with the language that needed it.** `con_emit`
; takes the character in R0, which is where every caller already had it,
; so the macro that pushed it and cleared the stack afterwards has
; nothing left to do ([D68]).
emitc:  JMP  con_emit

; sacout -- the accumulator to the screen, and then spent.
;
; PRINT's string item and INPUT's prompt are the same act, so they are
; one routine: put SLEN characters from SACC, then empty the accumulator
; because the next thing along may be a string too and a number after a
; string must not take the string path. INPUT wants that reset just as
; much -- its read loop appends where the prompt stopped otherwise.
;
; con_putsn(p AS CARD, n AS INT) and **an INT is two bytes**, so the
; count needs a high byte of its own: pushing one left the callee
; reading a length out of the saved Y and looping until the machine
; stopped answering.
sacout: PUSHW Y
        CLR  R2
        PUSH R2                 ; n, high byte
        LD   R0,[SACC]          ; X = the accumulator, R0 = how much
        MOV  XL,R0
        LD   R0,[SACC+1]
        MOV  XH,R0
        LD   R0,[SLEN]
        CALL con_putsn
        POP  R0
        POPW Y
        CLR  R2
        ST   [SLEN],R2
        ST   [STYPE],R2
        RET

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
        ; **TAB and SPC are items, not values.** They produce spacing
        ; and leave nothing for the type machinery to look at, so they
        ; are taken before `eval` rather than inside it -- which is also
        ; why they are `bad` in sttab: one outside a PRINT is ?SYNTAX
        ; rather than a statement that quietly does nothing.
.item:  SKIPSP
        CMP  R2,#K_TAB
        BEQ  .tab
        CMP  R2,#K_SPC
        BEQ  .spc
        CALL eval
        LD   R2,[STYPE]
        BNE  .nn
        BRA  .num
        ; A float renders into FSBUF and goes out through the string
        ; path: `fstr` answers exactly the (pointer, count) pair
        ; s_putsn wants, so PRINT grew a branch and not a printer.
.nn:    CMP  R2,#2
        BNE  .str
        PUSHW Y
        CALL fprint
        POPW Y
        BRA  .str
.num:   PUSHW Y                 ; num_put takes R0:R1 and walks Y
        CALL num_put
        POPW Y
        BRA  .sep
        ; A heap string is length-counted, so PRINT needs a sibling of
        ; puts that takes one rather than a NUL.
        ; putsn(p AS CARD, n AS INT). The compiler pushes right to left
        ; and **an INT is two bytes**, so the count needs a high byte of
        ; its own -- pushing one left the callee reading a length out of
        ; the saved Y and looping until the machine stopped answering.
.str:   CALL sacout
.sep:   SKIPSP
        CMP  R2,#$3B            ; ';'
        BEQ  .semi
        CMP  R2,#$2C            ; ','
        BEQ  .comma
        CALL pnl
        JMP  stmt
.comma: PUSHW Y
        MOV  R0,#$20
        CALL con_emit
        POPW Y
.semi:  INCW Y
        SKIPSP
        TST  R2
        BEQ  .last
        ; **A `:` after the separator ends the list, it is not an item.**
        ; `PRINT A;:GOSUB 100` is ordinary BASIC and this raised ?SYNTAX
        ; on it: anything non-zero went back to `.item` and `eval` was
        ; handed a statement separator. The zero test alone only covered
        ; a separator at end of *line*, so the fault needed a second
        ; statement on the same one to show at all.
        CMP  R2,#$3A            ; ':'
        BNE  .item
.last:  JMP  stmt               ; a trailing separator: no newline

        ; TAB(col): out to that column. **Already past it does
        ; nothing** -- it does not wrap to the next line, because a
        ; PRINT that silently gains a newline when a field runs long is
        ; a report that misaligns rather than one that overflows.
.tab:   INCW Y                  ; over the token
        CALL earg               ; ( col )
        PUSHW Y
        MOV  R2,R0
.tl:    LD   R0,[CCX]
        CMP  R0,R2
        BHS  .tdone
        MOV  R0,#$20
        PUSH R2
        CALL con_emit           ; which owns Y, hence the push above
        POP  R2
        BRA  .tl
.tdone: POPW Y
        JMP  .sep

        ; SPC(n): n spaces, wherever the cursor is.
.spc:   INCW Y
        CALL earg
        PUSHW Y
        MOV  R2,R0
.sl:    TST  R2
        BEQ  .sdone
        MOV  R0,#$20
        PUSH R2
        CALL con_emit
        POP  R2
        SUB  R2,#1
        BRA  .sl
.sdone: POPW Y
        JMP  .sep

pnl:    PUSHW Y
        CALL con_nl
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
        CMP  R0,#K_ELSEIF        ; a fresh condition, on the same line
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
goton:  CALL prg_find           ; ON joins here with its pick in R0:R1
        MOV  R0,XL
        MOV  R1,XH
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
        CALL evali              ; [D88] the control variable is integer
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
        CALL evali              ; [D88] FOR I=1 TO X# read the limit as 1
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
        CALL evali              ; [D88] and the STEP with it
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
        ; **NOT is here and not in `prim`, and the level is the whole
        ; point.** Microsoft's precedence puts it below the relations
        ; and above AND/OR, so `NOT A = 1` means `NOT (A = 1)`. `erel`
        ; is exactly the relational level and AND/OR sit above it in
        ; `.more`, so taking NOT at this entry gives that grouping for
        ; free. In `prim` it would bind tightest and mean `(NOT A) = 1`.
        ;
        ; Recursive, so `NOT NOT x` is x. TRUE is -1 ([D47]), so the
        ; complement is the same operation for logic and for bits and
        ; there is one of it.
        SKIPSP
        CMP  R2,#K_NOT
        BNE  .noneg
        INCW Y
        CALL erel
        XOR  R0,#$FF
        XOR  R1,#$FF
        RET
.noneg:
        CALL prim               ; the first operand
        ; ---- { ^ * / MOD operand }, highest precedence.
        ;
        ; **This level used to be written twice** -- inline here, and
        ; again as `mulrest` for the callers that need the mul level
        ; without the two above it. The copies drifted, and every float
        ; bug in [D63] came out of the gap: `mulrest` was integer-only,
        ; so `A# = B# + C# * D#` dropped the multiply, and it never knew
        ; `^` at all, so `0 - 2 ^ 2` was -2. One evaluator now, called
        ; from both places, which is the only way the two stay equal.
        ;
        ; It returns with the character that stopped it still in R2, so
        ; `.sum` reads it without touching Y again -- one skip per
        ; operand, not three, which is what the two copies were for.
.mul:   CALL mulrest
        ; ---- { + operand | - operand }
.sum:   CMP  R2,#$2B            ; '+', on the character .mul already has
        BEQ  .add
        CMP  R2,#$2D            ; '-'
        BEQ  .sub
        JMP  .rel
        ; A float left goes the same way an integer one does -- fsav
        ; puts either on the stack and fpair sorts them out once the
        ; right is known. Only a string still peels off here, and the
        ; test for it is unchanged: any non-zero type that is not 2.
.add:   INCW Y
        LD   R2,[STYPE]
        CMP  R2,#2
        BEQ  .adds
        TST  R2
        BNE  .cat               ; the left was a string: append, not add
.adds:  CALL fsav
        CALL prim
        CALL mulrest
        CALL fpair
        BCS  .fadd
        ADD  R0,R2
        ADC  R1,R3
        JMP  .mul
.fadd:  CALL fopadd
        ; The value is in FACC now, not R0:R1, and the type says so --
        ; then straight back to .mul, which looks for the next operator
        ; exactly as it does after an integer one.
        ; The float arms pushed .mul past a branch's reach, so the tail
        ; of this level jumps. Three bytes each, and the alternative is
        ; a trampoline that costs the same and reads worse. The type is
        ; set by the fop* wrappers now, which all end at fretf.
.fdone: JMP  .mul
        ; Concatenation is the accumulator doing nothing special: the
        ; operand appends where the last one stopped.
.cat:   CALL prim
        JMP  .mul
.sub:   INCW Y
        CALL fsav
        CALL prim
        CALL mulrest
        CALL fpair
        BCS  .fsub
        SUB  R0,R2
        SBC  R1,R3
        JMP  .mul
.fsub:  CALL fopsub
        BRA  .fdone
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
        CALL srhsn
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
        CALL srhsn
        SUB  R0,R2
        SBC  R1,R3
        BLT  .y2
        JMP  false
.y2:    JMP  true
.rne:   INCW Y
        CALL srhsn
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
        CALL srhsn
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
        CALL srhsn              ; a > b is b < a, and swaps the same way
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
        CALL srhsn
        SUB  R0,R2
        SBC  R1,R3
.cmpge: BGE  .y5
        JMP  false
.y5:    JMP  true

; srhs -- the right-hand side of a string relation. It appends, and the
; split it returns in R2 is where the left one ended.
; srhsn -- the right-hand side of any relation, as a number.
;
; **This is why the six operators need no string arms at all.** A
; numeric relation ends in `SUB R0,R2 / SBC R1,R3` and a branch on the
; sign; `scmp` already answers $FF, 0 or 1 for less, equal, greater. So
; a string comparison is turned into exactly the subtraction the numeric
; path was going to do -- the three-way in R0:R1, zero in R2:R3 -- and
; every arm keeps the code it already had, swaps included.
;
; The first shape of this gave `<`, `<=`, `>` and `>=` a bespoke arm
; each and left `=` and `<>` theirs: six copies of the same idea, about
; 90 bytes, and six places for the next operator to be forgotten in.
; This is one routine and one call site per operator.
srhsn:  LD   R2,[STYPE]
        CMP  R2,#1              ; 1 is a string; 0 and 2 both go to rhs,
        BNE  rhs                ;   which sorts an integer from a float
        CALL srhs
        CALL scmp
        CLR  R1                 ; sign-extend $FF/0/1 into R0:R1
        CMP  R0,#$FF
        BNE  .z
        MOV  R1,#$FF
.z:     CLR  R2                 ; against zero, which is what makes the
        CLR  R3                 ;   numeric branch mean the right thing
        RET

srhs:   LD   R2,[SLEN]
        PUSH R2
        CALL prim
        CALL sumrest
        POP  R2
        RET

; rhs -- the right-hand side of a relation, with its own * and +/-.
; The left side is preserved in R0:R1 across it.
; rhs -- the right of a relational, and the one place all six of them
; go through, which is why the float case is handled here and not in
; each arm.
;
; **A comparison does not need a float comparison.** `fpair` has already
; promoted both sides, `fcmp` already answers $FF/0/1 for below, equal
; and above, and every arm below already subtracts R0:R1 - R2:R3 and
; branches on the result. So the float case rewrites the pair as
; (sign, 0) and lets the integer arms run unchanged -- six operators
; for one arm's worth of code. The push/pop the integer path used is
; now fsav/fpair, which is the same save with a type on it.
; `erel` rather than prim/mulrest/sumrest: the latter three are the
; integer-only continuation, so `IF A# > B# / C#` evaluated the right in
; integers and compared against rubbish, while the same expression on
; the *left* was correct because erel's own arms promote. Calling erel
; is one call instead of three and gets the promotion for nothing.
;
; It also consumes a second relational, and **right to left**, not the
; left-to-right an earlier version of this comment claimed: the right
; operand is a whole `erel`, so `1 < 2 < 3` is `1 < (2 < 3)` and is
; false. Measured, not reasoned -- it is pinned in sim/test_run.py.
; Chained relationals are not meaningful in any BASIC of this era, so
; this is documented rather than defended.
rhs:    CALL fsav
        CALL erel
        CALL fpair
        BCC  .ri                ; both integers: R0:R1 and R2:R3, as before
        PUSHW Y                 ; fp.asm owns Y
        CALL fcmp
        POPW Y
        CLR  R1                 ; the right becomes 0 and the left the sign
        CLR  R2
        CLR  R3
        CMP  R0,#$80
        BCC  .ri
        MOV  R1,#$FF            ; $FF is -1: sign-extend it
.ri:    RET

; mulrest -- { * operand } applied to whatever is in R0:R1.
mulrest:
        SKIPSP
        CMP  R2,#$5E            ; '^', the level above this one. Tested
        BNE  .nopw              ;   inline: `CALL pwrest` here would pay
        CALL pwapply            ;   a CALL and a RET on every operand
        BRA  mulrest            ;   and every loop pass to discover the
.nopw:  CMP  R2,#$2A            ;   common case, that there is no '^'
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
        ; fsav/fpair rather than mdrhs, for the same reason `rhs` gave
        ; up prim/mulrest/sumrest: this is the continuation the *float*
        ; arms of .add and .sub call to get `b * c` before adding it,
        ; and while it was integer-only `A# = B# + C# * D#` silently
        ; lost the multiply. Every one of mulrest's callers wanted the
        ; promotion; none of them could have it.
.go:    INCW Y
        CALL fopnd
        BCS  .fg
        CALL imul16
        BRA  mulrest
.fg:    CALL fopmul
        BRA  mulrest
.dv:    INCW Y
        CALL fopnd
        BCS  .fv
        CALL idiv16
        BRA  mulrest
.fv:    CALL fopdiv
        BRA  mulrest

; ---------------------------------------------------------------------
; pwrest -- { ^ operand }, the level between unary minus and `*`.
;
; **`^` binds tighter than a leading minus, because that is what the
; notation means.** -x^2 is -(x^2) in mathematics, where the exponent
; belongs to the x and the sign belongs to the result; writing (-x)^2
; is how you say the other thing. Microsoft's 6502 BASIC agrees and
; prices it exactly here -- its OPTAB gives `^` 127 and negation 125,
; with `*` on 123 below both. This used to be a level lower: `.neg`
; took a whole primary and negated it, so -A^2 was (-A)^2, which then
; met a negative base and came back as -A.
;
; It is its own routine rather than an arm of mulrest so that `.neg`
; can call it without also taking the `*` and `/` that must stay
; outside the minus -- -A*B is (-A)*B in both dialects.
;
; Left-associative, so 2^3^2 is 64: the loop applies each `^` before
; looking for the next, and the right operand is a bare `prim`. MS
; BASIC lands the same way, and for the same reason -- FRMEVL compares
; the pending precedence with `BCS`, so equal binds left.
;
; `^` is exp(y ln x) and has no integer form, so two integers are
; promoted rather than given a second power routine.
; ---------------------------------------------------------------------
; Two routines, because the callers want different halves. `mulrest`
; has already tested the character and wants one application; `.neg`
; and `fopnd` are starting cold and want the loop. Splitting them keeps
; the operator itself written once -- the duplication that cost this
; project three bugs -- while leaving mulrest's test inline.
pwapply:
        INCW Y
        CALL fsav               ; not fopnd: that applies pwrest to the
        CALL prim               ;   right operand, which would make `^`
        CALL fpair              ;   right-associative
        BCS  .pf
        CALL fprom
.pf:    JMP  foppow

pwrest: SKIPSP
        CMP  R2,#$5E            ; '^'
        BNE  .pout
        CALL pwapply
        BRA  pwrest
.pout:  RET

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
        CMP  R2,#K_FLT          ; a float literal: three packed bytes
        BEQ  .flt
        CMP  R2,#$28            ; '('
        BEQ  .paren
        CMP  R2,#$2D            ; unary minus
        BEQ  .neg
        ; Both of these arms are past a conditional branch's +-127 now
        ; that the float paths sit between, so each inverts and lets a
        ; JMP carry the distance -- sw/disasm.asm's macros, by hand.
        CMP  R2,#K_PEEK
        BNE  .npeek
        JMP  .peek
.npeek:
        CMP  R2,#K_INT
        BNE  .nint
        JMP  .int
.nint:  CMP  R2,#$22            ; '"' -- a literal, stored with its quotes
        BEQ  .lit
        ; a name -- varidx leaves X on its value, unless a '(' says
        ; the name was an array's and X has to be worked out instead
        ;
        ; **A keyword reaching here is not worth a test.** `PRINT FREE`
        ; falls through to `varidx`, reads the token as a variable name
        ; and answers whatever is in the slot it lands on, then
        ; `?SYNTAX`. FREE, CLS and LIST are statements and stand alone,
        ; so the line is meaningless and the error is right; only the
        ; number in front of it is noise. Rejecting `R2 >= $80` here was
        ; built and measured at **10 bytes**, and it does not even
        ; suppress the number -- PRINT emits before anything looks at
        ; ERR. Ten bytes to change which wrong number precedes a correct
        ; error is not a trade this machine can make.
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

        ; **The subscript is asked about before the suffix**, and it has
        ; to be. The suffix test fired first, so `A$(3)` was read as the
        ; scalar A$ and the subscript left for whatever came next to
        ; choke on -- which is why typed arrays could not exist however
        ; the storage was arranged. A builtin still goes first: LEFT$,
        ; RIGHT$, MID$ and CHR$ all end in '$' and are followed by '(',
        ; so they look exactly like string arrays from here.
        SKIPSP
        CMP  R2,#$28            ; '('
        BEQ  .notstr            ; an array of any type: .sub sorts it out

        PUSH R0
        CALL isflt
        POP  R0
        BCC  .fvar
        PUSH R0
        CALL isstr
        POP  R0
        BCS  .notstr
        JMP  sload              ; X is already on its descriptor
.fvar:  JMP  floadv
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
        ; **The element's type decides, and the scalar routines take
        ; it from here unchanged.** `aelem` leaves X on the element and
        ; R2 saying what it is, and a float element is exactly what
        ; `floadv` wants -- three packed bytes at X -- while a string
        ; element is exactly the four-byte descriptor `sload` wants.
        ; That is why typed arrays cost so little: nothing new loads or
        ; stores anything.
.sub:   CALL arrelem
        CMP  R2,#1
        BEQ  .afl
        CMP  R2,#2
        BEQ  .ast
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        RET
.afl:   JMP  floadv
.ast:   JMP  sload
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
        ; **An integer says so too.** `.lit` below sets STYPE 1 and
        ; `.flt` sets 2; this arm set nothing and handed back R0:R1, so
        ; an integer literal inherited the type of whatever was
        ; evaluated last. Nothing observed has depended on it -- the
        ; assignment and print paths reset STYPE on their own way in --
        ; which is exactly why it should not stay: the rule is that
        ; every arm of prim states the type it produced, and an arm
        ; quietly exempt from it is a bug waiting for the first caller
        ; that trusts the rule. Four bytes.
.num:   CLR  R2                 ; R2 held the K_NUM token, now spent
        ST   [STYPE],R2
        INCW Y
        LD   R0,[Y]
        INCW Y
        LD   R1,[Y]
        INCW Y
        RET
        ; A float literal. `tok_line` laid the three packed bytes down
        ; with `fstore`, which is the same shape a float variable holds,
        ; so `fload` reads it back and the literal and the variable
        ; cannot disagree. STYPE 2 is what tells everything above that
        ; the value is in FACC and not in R0:R1 ([D68]).
.flt:   INCW Y
        PUSHW Y                 ; fp.asm owns Y; the caller's is the
        MOVW X,Y                ;   token pointer, so it is saved
        CALL fload
        POPW Y
        INCW Y
        INCW Y
        INCW Y
        MOV  R0,#2
        ST   [STYPE],R0
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
        CALL pwrest             ; -x^2 is -(x^2); see pwrest's header
        CALL edout
        LD   R2,[STYPE]         ; a float's sign is its own byte, and
        CMP  R2,#2              ;   negating R0:R1 would silently drop it
        BNE  .negi
        JMP  fneg
.negi:  MOV  R2,R0
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
        ; INT(a). `iint` is `earg` then the shift then `retnum`, which is
        ; the same tail every btab function returns through, so this is a
        ; tail call and costs two instructions over a table entry.
.int:   INCW Y                  ; over the token; earg takes the '('
        JMP  iint
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
; h_sys -- `SYS expr`: call machine code at an address.
;
; **This is what replaced the on-machine assembler** ([D63]). Removing
; `asm.asm` took 2,886 bytes and 38 of page 0 with it, and took away the
; only route from BASIC to machine code -- `CALL name` needs the
; assembler to have defined the name. Ten bytes put the route back:
; assemble on the host with tools/cool8asm.py, `LOAD "x" AT addr`, and
; `SYS addr`.
;
; **There is no `CALL [X]`**, so the call is a `CALL` to a one-
; instruction trampoline that jumps. Falling straight into `JMP [X]`
; instead looks tidier and is wrong: the callee's `RET` then returns
; past the dispatcher, and the statement after `SYS` never runs. The
; symptom is a program that prints nothing and does not error.
;
; Y is the token pointer and a called routine owns every register, so it
; is saved across -- the same reason `h_print` saves it around the
; editor's own screen routines.
;
; It lives at the end of the file, not beside `bad`. Twelve bytes
; between the dispatcher and `h_let` already put `BCC h_let` out of
; range once.
; ---------------------------------------------------------------------
h_sys:  CALL eval
        MOV  XL,R0
        MOV  XH,R1
        PUSHW Y
        CALL .go
        POPW Y
        JMP  stmt
.go:    JMP  [X]

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
        ; **A request bigger than the heap wraps, and used to pass.**
        ; `HEAP - size` borrows when the array is larger than everything
        ; below the heap, and the borrowed result is a *high* address --
        ; so the compare against the name table said yes and the array
        ; was allocated somewhere above the machine. It never showed
        ; while a DIM big enough to do it was also bigger than the
        ; 64 KB the bound can express; [D69]'s repack made the user's
        ; region large enough that the old test case stopped failing and
        ; this one started. Carry clear is borrow ([D9]).
        BLO  .full
        ; **Against the name table.** The heap comes down from USERTOP
        ; towards the program text and its names, so the question is
        ; whether it has reached them -- one region, shared, which is
        ; what [D69]'s repack chose over two fixed ones.
        ; **Against the top of the two stacks, not the name table.**
        ; It compared `nentry(NNAME)` -- one past the last name defined
        ; -- which grew only as names appeared. The call and save stacks
        ; live above the table's full extent now, so that test would let
        ; the heap eat them: a deep call during a big DIM, and the
        ; frames are underneath an array.
        PUSH R3
        PUSH R2
        CALL ltop
        POP  R2
        POP  R3
        MOV  R0,R2
        MOV  R1,XL
        SUB  R0,R1
        MOV  R0,R3
        MOV  R1,XH
        SBC  R0,R1
        BLO  .full
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
; aelem -- X = the address of the element, R2 = what kind it is.
;
; R0:R1 is the block and Y is on the '('. On return X points at the
; element and R2 is 0, 1 or 2 -- integer, float or string -- which is
; all a caller needs to pick between the scalar load and store routines
; it already has.
;
; **Every byte of state is on the CPU stack, deliberately.** `A(B(1))`
; nests: the outer call has parsed nothing when the inner one runs, so
; anything in the storage region would be the outer subscript
; overwritten by the inner, and the type with it. `h_dim` cannot nest
; and does use scratch; this cannot and does not.
;
; The frame, from the top: d, index lo, index hi, type, rank, block lo,
; block hi. `eval` is balanced, so the offsets hold across it.
; ---------------------------------------------------------------------
; **One dimension has its own path, and it is the one that matters.**
; The general form below carries a seven-byte frame, a dimension
; counter and a Horner step that a one-dimensional array never uses --
; measured at about 147 cycles an access more than the untyped version
; it replaced. This does the same job with three bytes of frame, the
; count read straight out of the header, and no loop: the common case
; does not pay for the general one.
aelem:  MOV  XL,R0
        MOV  XH,R1
        LD   R2,[X]             ; rank
        CMP  R2,#1
        BNE  agen

        PUSH R1                 ; block hi
        PUSH R0                 ; block lo
        INCW X
        LD   R2,[X]             ; type
        PUSH R2

        INCW Y                  ; the '('
        CALL eval
        LD   R2,[ERR]
        BNE  .bad1

        LD   R2,[SP+1]          ; the block again, for count[0]
        LD   R3,[SP+2]
        MOV  XL,R2
        MOV  XH,R3
        INCW X                  ; past rank
        INCW X                  ; past type
        LD   R2,[X]
        INCW X
        LD   R3,[X]

        TST  R1                 ; negative, which an unsigned compare
        BMI  .bad1              ;   would read as 65535
        SUB  R0,R2
        SBC  R1,R3
        BHS  .bad1              ; not below the bound
        ADD  R0,R2              ; and back: (a - b) + b is a
        ADC  R1,R3

        SKIPSP
        INCW Y                  ; the ')'
        POP  R2                 ; type
        PUSH R2

        CMP  R2,#1              ; index * width, no multiply
        BEQ  .f3
        ADD  R0,R0
        ROL  R1
        CMP  R2,#2
        BNE  .fh
        ADD  R0,R0
        ROL  R1
        BRA  .fh
.f3:    MOV  R2,R0
        MOV  R3,R1
        ADD  R0,R0
        ROL  R1
        ADD  R0,R2
        ADC  R1,R3
.fh:    POP  R2                 ; the type, for the caller
        ADD  R0,#4              ; the header: rank, type, one count
        MOV  R3,#0
        ADC  R1,R3
        POP  R3                 ; block lo
        MOV  XL,R3
        POP  R3                 ; block hi
        MOV  XH,R3
        JMP  addx16

.bad1:  ADDW SP,#3
        CLR  R2
        JMP  esubs

; agen -- two or three dimensions. R0:R1 is still the block.
agen:   PUSH R1                 ; block hi
        PUSH R0                 ; block lo
        MOV  XL,R0
        MOV  XH,R1
        LD   R2,[X]             ; rank
        INCW X
        LD   R3,[X]             ; type
        PUSH R2                 ; rank
        PUSH R3                 ; type
        CLR  R0
        PUSH R0                 ; index hi
        PUSH R0                 ; index lo
        PUSH R0                 ; d

        ; **The first dimension is peeled out of the loop.** It is the
        ; only one for a one-dimensional array, and it needs no multiply
        ; and no running index to combine with -- so the common case
        ; pays for neither. Everything after it goes round `.next`.
        BRA  .take

.loop:  SKIPSP
        CMP  R2,#$2C            ; ',' -- another subscript
        BNE  .bad
.take:  INCW Y                  ; over the '(' or that ','
        CALL eval
        LD   R2,[ERR]
        BNE  .bad

        ; count[d], out of the header
        PUSH R1
        PUSH R0
        LD   R0,[SP+2]          ; d
        ADD  R0,R0
        ADD  R0,#2              ; past rank and type
        LD   R2,[SP+7]          ; block lo
        LD   R3,[SP+8]          ; block hi
        MOV  XL,R2
        MOV  XH,R3
        ADDW X,R0
        LD   R2,[X]
        INCW X
        LD   R3,[X]
        POP  R0
        POP  R1

        ; **0 <= subscript < count[d], and the compare puts it back
        ; rather than saving it.** This pushed all four registers to
        ; compare without destroying them, which is eight stack
        ; operations per dimension; subtracting and adding the same
        ; value back is four instructions and exact. The sign test is
        ; not redundant -- an unsigned compare lets -1 through as 65535,
        ; and a signed one would fail on a legitimate count above 32767.
        TST  R1
        BMI  .bad
        SUB  R0,R2
        SBC  R1,R3
        BHS  .bad               ; not below the bound
        ADD  R0,R2              ; and back: (a - b) + b is a
        ADC  R1,R3

        LD   R2,[SP+0]          ; d
        TST  R2
        BNE  .horner
        ST   [SP+1],R0          ; the first: the index *is* the subscript
        MOV  R2,R1
        ST   [SP+2],R2
        BRA  .next

        ; index = index * count[d] + subscript. The only multiply in the
        ; path, and a one-dimensional array never arrives here.
.horner:
        PUSH R1                 ; subscript hi
        PUSH R0                 ; subscript lo
        LD   R0,[SP+3]          ; index lo
        LD   R1,[SP+4]          ; index hi
        CALL amul16             ; R1:R0 = index * count[d]
        POP  R2                 ; subscript lo
        ADD  R0,R2
        POP  R2                 ; subscript hi
        ADC  R1,R2
        ST   [SP+1],R0
        MOV  R2,R1
        ST   [SP+2],R2

.next:  LD   R0,[SP+0]          ; d = d + 1
        ADD  R0,#1
        ST   [SP+0],R0
        LD   R2,[SP+4]          ; rank
        CMP  R0,R2
        BLO  .loop

.flat:  SKIPSP
        INCW Y                  ; the ')'
        POP  R2                 ; d, spent
        POP  R0                 ; index lo
        POP  R1                 ; index hi
        POP  R2                 ; type
        PUSH R2                 ; ...which the caller wants as well

        ; index * width. **No multiply anywhere**: 2 is a doubling, 4 is
        ; two of them, and 3 is a doubling and an add.
        CMP  R2,#1
        BEQ  .e3
        ADD  R0,R0
        ROL  R1
        CMP  R2,#2
        BNE  .ehdr
        ADD  R0,R0              ; a string descriptor is four
        ROL  R1
        BRA  .ehdr
.e3:    MOV  R2,R0              ; three: (n << 1) + n
        MOV  R3,R1
        ADD  R0,R0
        ROL  R1
        ADD  R0,R2
        ADC  R1,R3

.ehdr:  POP  R2                 ; the type, this routine's second answer
        POP  R3                 ; rank -- the header is 2 + 2*rank
        ADD  R3,R3
        ADD  R3,#2
        ADD  R0,R3
        MOV  R3,#0              ; MOV #imm leaves the carry alone, which
        ADC  R1,R3              ;   is what makes this idiom work
        POP  R3                 ; block lo
        MOV  XL,R3
        POP  R3                 ; block hi
        MOV  XH,R3
        JMP  addx16             ; X = block + header + index*width;
                                ;   R2 survives it, and is the type

        ; **R2 must be a type even on the way out.** The caller
        ; branches on it, and `esubs` leaves it as whatever the failing
        ; compare happened to put there -- so a bad subscript could
        ; dispatch into `sload` with X on the multiply scratch. Zero is
        ; the integer path, which reads two bytes and discards them
        ; because `stmt` stops on ERR before the next statement.
.bad:   ADDW SP,#7              ; d, index, type, rank, block
        CLR  R2
        JMP  esubs

; ---------------------------------------------------------------------
; DIM name(bound)
;
; Eleven elements for DIM A(10), subscripts 0 to 10 -- BBC BASIC's rule
; and Microsoft's, and the one every published program assumes.
; Re-dimensioning is allowed and simply allocates again: the old block
; becomes garbage, which is the same bargain assignment makes, and every
; RUN starts with an empty name table anyway.
; ---------------------------------------------------------------------
; amul16 -- R1:R0 = R1:R0 * R3:R2, the low sixteen bits.
;
; `sw/lib.asm` has this routine and `sw/lib.asm` is not in the image, so
; it is here rather than dragging the file in for twenty bytes. MUL
; writes to X, so a caller's pointer is saved across it -- the cost of
; that destination choice, and this is where it shows.
;
; **The low half is all that is wanted.** Every use is Horner-flattening
; a subscript whose dimensions were range-checked at DIM, so the
; flattened index cannot exceed the element count; `h_dim` is where the
; product is checked for overflow, once, rather than here on every
; access.
amul16: PUSHW X
        MUL  R0,R3              ; a.lo * b.hi
        MOV  R3,XL
        MUL  R1,R2              ; a.hi * b.lo
        MOV  R1,XL
        ADD  R3,R1              ; the cross terms, low byte only
        MUL  R0,R2              ; a.lo * b.lo
        MOV  R0,XL
        MOV  R1,XH
        ADD  R1,R3
        POPW X
        RET

h_dim:  SKIPSP
        CALL nscan              ; the name, suffix and all, into NBUF

        ; **The element type is the name's suffix**, read before
        ; `arrname` appends the '(' that makes it an array key. That is
        ; the whole of the typing: `A(`, `A#(` and `A$(` were already
        ; three different names in the table, so nothing had to be
        ; invented to tell them apart.
        CLR  R0
        ST   [DTYPE],R0
        CALL isflt
        BCS  .nf
        MOV  R0,#1
        ST   [DTYPE],R0
        BRA  .haveto
.nf:    CALL isstr
        BCS  .haveto
        MOV  R0,#2
        ST   [DTYPE],R0
.haveto:
        CALL arrname
        CALL nfind              ; X on the entry's value

        ; **Dimensioned twice is an error, not a silent leak.** The old
        ; block was simply abandoned, and with no garbage collector a
        ; DIM inside a loop eats the heap and reports ?OUT OF MEM a long
        ; way from the cause. A fresh entry has a zero block pointer,
        ; which is what `nfind` writes and what `vclear` restores.
        PUSHW X
        LD   R0,[X]
        PUSHW X
        INCW X
        LD   R1,[X]
        POPW X
        OR   R0,R1
        BEQ  .fresh
        POPW X
        MOV  R0,#E_REDIM
        ST   [ERR],R0
        RET

.fresh: CLR  R0
        ST   [DRANK],R0
        MOV  R0,#1              ; the running product, in elements
        ST   [DTOT],R0
        CLR  R0
        ST   [DTOT+1],R0
        SKIPSP
        INCW Y                  ; the '('

.bound: CALL eval
        LD   R2,[ERR]
        BNE  .bail
        ADD  R0,#1              ; inclusive: DIM A(10) is eleven elements
        MOV  R2,#0
        ADC  R1,R2

        ; count[rank] = R0:R1
        PUSH R1
        PUSH R0
        LD   R0,[DRANK]
        ADD  R0,R0
        LDW  X,#DCNT
        ADDW X,R0
        POP  R0
        ST   [X],R0
        INCW X
        POP  R0
        ST   [X],R0

        ; **The product has to be checked, not just computed.** A 16-bit
        ; multiply that wraps gives a block *smaller* than the bounds
        ; the subscript checks then use, so every write past the wrap
        ; lands on whatever is next in the heap -- silent corruption,
        ; from a DIM that looked like it worked. 65535 / count is the
        ; largest running total that can survive the multiply, and DIM
        ; is cold enough to afford the divide to find out.
        LD   R0,[DRANK]
        ADD  R0,R0
        LDW  X,#DCNT
        ADDW X,R0
        LD   R2,[X]
        INCW X
        LD   R3,[X]
        MOV  R0,R2              ; a zero-length dimension is refused
        OR   R0,R3
        BEQ  .huge
        MOV  R0,#$FF
        MOV  R1,#$FF
        CALL udiv16             ; R0:R1 = 65535 / count
        LD   R2,[DTOT]
        LD   R3,[DTOT+1]
        SUB  R0,R2              ; limit - total, borrow means total wins
        SBC  R1,R3
        BLO  .huge

        LD   R0,[DTOT]
        LD   R1,[DTOT+1]
        LD   R0,[DRANK]
        ADD  R0,R0
        LDW  X,#DCNT
        ADDW X,R0
        LD   R2,[X]
        INCW X
        LD   R3,[X]
        LD   R0,[DTOT]
        LD   R1,[DTOT+1]
        CALL amul16
        ST   [DTOT],R0
        MOV  R0,R1
        ST   [DTOT+1],R0

        LD   R0,[DRANK]
        ADD  R0,#1
        ST   [DRANK],R0

        SKIPSP
        CMP  R2,#$2C            ; ',' -- another dimension
        BNE  .close
        LD   R0,[DRANK]
        CMP  R0,#3              ; three is the cap ([D71])
        BHS  .huge
        INCW Y
        BRA  .bound

.close: SKIPSP
        INCW Y                  ; the ')'

        ; bytes = 2 + 2*rank of header, then total elements of `width`.
        ; **No multiply for the width**: 2 is a shift, 4 is two, and 3 is
        ; a shift and an add. Only the Horner step in `aelem` ever needs
        ; mul16, and a one-dimensional array never reaches it.
        LD   R0,[DTOT]
        LD   R1,[DTOT+1]
        LD   R2,[DTYPE]
        CMP  R2,#1
        BEQ  .w3
        PUSH R1                 ; width 2 and width 4 share the doubling
        PUSH R0
        ADD  R0,R0
        ROL  R1
        ADDW SP,#2
        CMP  R2,#2
        BNE  .wdone
        ADD  R0,R0              ; ...and a string descriptor doubles again
        ROL  R1
        BRA  .wdone
.w3:    MOV  R2,R0              ; three: (n << 1) + n
        MOV  R3,R1
        ADD  R0,R0
        ROL  R1
        ADD  R0,R2
        ADC  R1,R3
.wdone:
        PUSH R1
        PUSH R0
        LD   R2,[DRANK]         ; the header: rank, type, one count each
        ADD  R2,R2
        ADD  R2,#2
        POP  R0
        POP  R1
        ADD  R0,R2
        MOV  R2,#0
        ADC  R1,R2
        BCS  .huge              ; the size itself wrapped

        CALL halloc
        BCS  .bail              ; halloc has set ERR

        ; The block: header first, then every element zeroed. An
        ; unwritten element reads as 0, 0.0 or "" -- a zeroed string
        ; descriptor is an empty string, which is what `sload` makes of
        ; a zero length without looking at the address.
        MOV  XL,R0
        MOV  XH,R1
        PUSH R1                 ; keep the block for the entry
        PUSH R0
        LD   R0,[DRANK]
        ST   [X],R0
        INCW X
        LD   R0,[DTYPE]
        ST   [X],R0
        INCW X
        CLR  R2
.hdr:   LD   R0,[DRANK]
        CMP  R2,R0
        BHS  .hdone
        PUSH R2
        ADD  R2,R2
        PUSHW X
        LDW  X,#DCNT
        ADDW X,R2
        LD   R0,[X]
        INCW X
        LD   R1,[X]
        POPW X
        ST   [X],R0
        INCW X
        MOV  R0,R1
        ST   [X],R0
        INCW X
        POP  R2
        ADD  R2,#1
        BRA  .hdr
.hdone:
        ; X is on element zero; DTOT elements of DTYPE's width follow.
        LD   R2,[DTOT]
        LD   R3,[DTOT+1]
.zel:   MOV  R0,R2
        OR   R0,R3
        BEQ  .done
        CLR  R0
        ST   [X],R0
        INCW X
        ST   [X],R0
        INCW X
        LD   R1,[DTYPE]
        TST  R1
        BEQ  .znext
        ST   [X],R0             ; float: a third byte
        INCW X
        CMP  R1,#2
        BNE  .znext
        ST   [X],R0             ; string: a fourth
        INCW X
.znext: SUB  R2,#1
        MOV  R0,#0
        SBC  R3,R0
        BRA  .zel

.done:  POP  R0
        POP  R1
        POPW X                  ; the name table entry
        ST   [X],R0
        INCW X
        ST   [X],R1
        JMP  stmt

.huge:  MOV  R0,#E_MEM
        ST   [ERR],R0
.bail:  POPW X
        RET

; h_leta -- A(i) = expr. The element's address is worked out before the
; right-hand side is evaluated, because eval needs X for itself.
h_leta: CALL arrelem
        ; **Stop here if the subscript was refused.** `aelem` fails
        ; before it consumes the ')', so carrying on skips the wrong
        ; byte and `eval` parses whatever follows -- which reported
        ; ?SYNTAX over the top of the ?INDEX that was already set, and
        ; named the fault as the wrong thing entirely. `stmt` returns
        ; immediately when ERR is set, so this is the whole of it. R3,
        ; not R2: R2 is the element type.
        LD   R3,[ERR]
        BNE  .aerr
        ; The element's type, and the scalar assignment routines take it
        ; from here: h_letf wants X on three packed bytes and h_lets
        ; wants X on a four-byte descriptor, which is what an element of
        ; each kind already is.
        CMP  R2,#1
        BEQ  h_letf
        CMP  R2,#2
        BEQ  h_lets
        PUSHW X
        SKIPSP
        INCW Y                  ; the '='
        CALL evali              ; [D88] as the scalar above
        POPW X
        ST   [X],R0
        INCW X
        ST   [X],R1
.aerr:  JMP  stmt

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

; isstr / isflt -- C clear if the name in NBUF ends with '$' or '#'.
; **The suffix is the type, and that is the whole of the type system**:
; A, A# and A$ are three unrelated variables because the character is
; part of the name, so nothing needs a type field and nothing needs to
; agree about one. Six bytes bought the float half of it.
isflt:  MOV  R3,#$23            ; '#'
        BRA  issuf
isstr:  MOV  R3,#$24            ; '$'
issuf:  PUSHW X
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
        CMP  R0,R3              ; the suffix the caller asked about
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
        PUSHW X
        PUSHW Y
        LD   R0,[SLEN]
        SUB  R0,R2              ; R0 = the right's length
        MOV  R3,R2              ; R3 = the left's
        LD   R1,[SACC]
        MOV  XL,R1
        LD   R1,[SACC+1]
        MOV  XH,R1
        MOV  R1,XL
        MOV  YL,R1
        MOV  R1,XH
        MOV  YH,R1
        ADDW Y,R3               ; Y on the right half

        ; Compare over the shorter of the two, byte by byte. **The
        ; first difference decides**, which is what makes this an
        ; ordering rather than an equality test: it used to give up the
        ; moment the lengths differed, so `<` on strings fell through to
        ; the numeric path and silently answered false.
        MOV  R2,R3              ; R2 = min(left, right)
        CMP  R0,R2
        BHS  .have
        MOV  R2,R0
.have:  TST  R2
        BEQ  .bylen             ; a common prefix of nothing

        ; **Nothing is stacked inside the loop.** Keeping the right's
        ; length in R0 across it cost a PUSH and a POP per character,
        ; and worse, it made `.diff` unwind the stack by hand on two
        ; exit paths -- a balance to get wrong rather than a speed
        ; problem. The length is recomputed at `.bylen`, which runs
        ; once, from the split still on the stack.
.c:     LD   R0,[X]
        INCW X
        LD   R1,[Y+]
        SUB  R0,R1
        BNE  .diff
        SUB  R2,#1
        BNE  .c

        ; Equal as far as both go, so the shorter is the smaller --
        ; "AB" < "ABC". R3 is the left's length; the right's is what is
        ; left of the accumulator past the split, and the split is under
        ; the two saved pointers.
.bylen: LD   R0,[SP+4]
        LD   R1,[SLEN]
        SUB  R1,R0              ; the right's length
        MOV  R0,R3
        CMP  R0,R1
        BEQ  .eq
        BLO  .lt
        BRA  .gt

        ; The byte that differed: R0 is left-minus-right and the borrow
        ; says which way ([D9] -- carry means no borrow).
.diff:  BCS  .gt
        BRA  .lt

.eq:    CLR  R0
        BRA  .out
.lt:    MOV  R0,#$FF
        BRA  .out
.gt:    MOV  R0,#1
        ; The accumulator is cut back to the split either way, so a
        ; comparison inside a longer expression leaves nothing behind.
.out:   POPW Y
        POPW X
        POP  R2
        PUSH R0
        ST   [SLEN],R2
        CLR  R0
        ST   [STYPE],R0
        POP  R0
        RET
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
        ; $23 '#' and $24 '$' both carry bit 7, so a suffix scans as
        ; part of the name and `A`, `A#` and `A$` are three names.
        .byte $00,$00,$00,$80,$80,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00
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

; STRING$(n, s) -- s repeated n times, and it needs no buffer.
;
; **The pattern is already the tail of the accumulator** by the time the
; arguments are read, and the accumulator is a fixed buffer that never
; moves -- so every further copy reads from where the first one landed
; and appends past it. `sappend` is exactly "R2 characters from R0:R1
; onto the accumulator", which is the whole loop body, and `sputc`
; inside it raises ?STRING at SMAX. So this is the argument parse, an
; address, and a counted call: no second copier, and no temporary.
;
; BBC BASIC's argument order, count first. The C64 has no STRING$.
sstring:
        CALL sopen              ; '('
        CALL eval               ; how many
        ; **The count is sixteen bits and the loop runs on eight.**
        ; Taking R0 alone made STRING$(256,"x") the empty string and
        ; STRING$(300,"yz") eighty-eight characters -- silently, while
        ; STRING$(200,"yz") correctly said ?STR LEN. Anything past 255
        ; cannot fit SMAX for a pattern of any length, so it is clamped
        ; to 255 and reaches that same error by that same route rather
        ; than by a second check that could disagree with it.
        TST  R1
        BEQ  .lo
        MOV  R0,#$FF
.lo:    PUSH R0
        CALL sopen              ; ','
        LD   R2,[SLEN]
        PUSH R2                 ; where the pattern starts
        CALL eval               ; the pattern, appended where R2 said
        CALL sopen              ; ')'
        POP  R2                 ; ...start
        POP  R3                 ; ...and count, in the order pushed
        MOV  R0,#1
        ST   [STYPE],R0         ; a string either way, empty included
        LD   R0,[SLEN]
        SUB  R0,R2              ; the pattern's own length
        BEQ  .out               ; nothing to repeat
        TST  R3
        BNE  .some
        ST   [SLEN],R2          ; STRING$(0,s) is the empty string
        BRA  .out
.some:  SUB  R3,#1              ; the first copy is already in place
        BEQ  .out
        PUSH R0                 ; the length, while the address is built
        LD   R0,[SACC]
        ADD  R0,R2
        LD   R1,[SACC+1]
        MOV  R2,#0
        ADC  R1,R2
        POP  R2                 ; the length, where sappend wants it
.rep:   PUSH R0
        PUSH R1
        PUSH R2
        PUSH R3
        CALL sappend
        POP  R3
        POP  R2
        POP  R1
        POP  R0
        SUB  R3,#1
        BNE  .rep
.out:   RET

smid:   CALL sopen
        LD   R2,[SLEN]
        PUSH R2
        CALL eval
        CALL sopen              ; ','
        CALL eval               ; where to start, counting from one
        PUSH R0
        ; **Two arguments means "to the end"**, which is what both the
        ; C64 and the BBC give. The count is not optional in the parser
        ; -- it is asked for only if a ',' follows, and `strim` already
        ; clamps, so 255 is the whole rest of any string this machine
        ; can hold.
        SKIPSP
        CMP  R2,#$29            ; ')'
        BNE  .three
        INCW Y
        MOV  R0,#$FF
        BRA  .have
.three: CALL earg               ; , expression )
.have:  POP  R3
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
inkey:  CALL in_key
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
; **The length is the discriminator, so nothing else happens first.**
; This is 24 % of a run that calls one builtin in a loop -- more than
; the divide the builtin itself does -- because a name is matched here
; by walking the table, at evaluation time, every time. A-Z and A$-Z$
; are resident and never arrive; every builtin call and every long
; variable name does, and a long name walks all of it and misses.
;
; The saved entry pointer used to be written on every iteration, and
; read back on every rejection: twelve instructions of bookkeeping per
; entry. But X has not moved when the *length* disagrees, which is what
; nearly every entry does -- so that case now skips the entry whole
; from where it stands, and BENT is written only for the handful of
; entries whose length matches and whose characters are about to walk
; X destructively.
isbuilt:
        PUSHW Y
        LDW  X,#btab
.each:  LD   R0,[X]             ; the length, X still on the entry head
        BEQ  .miss
        LD   R1,[NLEN]
        CMP  R0,R1
        BEQ  .try
        ADDW X,R0               ; wrong length: over it without a save
        ADDW X,#3
        BRA  .each
.try:   MOV  R1,XL              ; the compare below eats X, so keep it
        ST   [BENT],R1
        MOV  R1,XH
        ST   [BENT+1],R1
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
btab:
        ; **On its own line, and that matters.** This entry shared
        ; the line with the label, and `tools/vocab.py` starts
        ; reading after the label -- so LEN was skipped by the
        ; parser, missing from the generated vocabulary, and
        ; invisible to the check that refuses an entry with no
        ; signature. A check cannot flag what it never saw.
        .byte 3,"L","E","N"
        .word slen
                                ;: LEN(s:string) -> int
        .byte 5,"L","E","F","T","$"
        .word sleft
                                ;: LEFT$(s:string, n:int) -> string  clamps past the end
        .byte 6,"R","I","G","H","T","$"
        .word sright
                                ;: RIGHT$(s:string, n:int) -> string  clamps past the end
        .byte 4,"M","I","D","$"
        .word smid
                                ;: MID$(s:string, start:int[, n:int]) -> string  two arguments run to the end; empty past the end
        .byte 4,"C","H","R","$"
        .word schr
                                ;: CHR$(n:int) -> string !intonly
        .byte 3,"A","S","C"
        .word sasc
                                ;: ASC(s:string) -> int
        .byte 4,"S","T","R","$"
        .word sstr
                                ;: STR$(n:int|float) -> string  a float renders as PRINT would
        .byte 3,"V","A","L"
        .word sval
                                ;: VAL(s:string) -> same  a fraction gives a float, four digits of it; nonsense is 0
        .byte 5,"I","N","S","T","R"
        .word sinstr
                                ;: INSTR(hay:string, needle:string) -> int
        .byte 5,"I","N","K","E","Y"
        .word inkey
                                ;: INKEY -> int  0 when nothing was typed
        .byte 3,"K","E","Y"
        .word ikey
                                ;: KEY(code:int) -> int  is that key held down !intonly
        .byte 3,"R","N","D"
        .word irnd
                                ;: RND(n:int) -> int  0..n-1; RND(0) is the raw word !intonly
        .byte 5,"T","I","M","E","R"
        .word itimer
                                ;: TIMER -> int  frames since boot
        .byte 3,"E","R","R"
        .word ierr
                                ;: ERR -> int  the code of the fault ON ERROR caught, 0 if none has
        .byte 4,"B","G","E","T"
        .word ibget
                                ;: BGET -> int  the next byte of the open stream, or -1 past the end
        .byte 3,"E","O","F"
        .word ieof
                                ;: EOF -> int  -1 when the stream has no more bytes, or none is open
        .byte 4,"G","E","T","$"
        .word igets
                                ;: GET$ -> string  one line of the open stream, without its CR; empty at the end
        .byte 3,"P","O","S"
        .word ipos
                                ;: POS -> int  the cursor's column, 0 at the left margin
        .byte 4,"V","P","O","S"
        .word ivpos
                                ;: VPOS -> int  the cursor's row, 0 at the top
        .byte 4,"T","R","U","E"
        .word itrue
                                ;: TRUE -> int  -1, which is what a comparison answers ([D47])
        .byte 5,"F","A","L","S","E"
        .word ifalse
                                ;: FALSE -> int  0
        ; Seven characters, and NSIG is seven because of it: `isbuilt`
        ; compares NLEN against the entry length and then that many
        ; bytes out of NBUF, so at six this entry's last compare read
        ; NLEN itself and never matched.
        .byte 7,"S","T","R","I","N","G","$"
        .word sstring
                                ;: STRING$(n:int, s:string) -> string  s repeated n times; 0 gives the empty string
        .byte 5,"V","P","E","E","K"
        .word ivpeek
                                ;: VPEEK(addr:int) -> int !intonly
        ; FMUL and FDIV are gone -- [D63] made a real multiply and a
        ; real divide resident, and 8.8 was only ever the fraction that
        ; fitted a 16-bit cell.
        ; ---- floating point ([D63]). Six bytes an entry, and six more
        ; ---- for the handler in sw/fpbas.asm, because fp.asm already
        ; ---- holds the arithmetic.
        .byte 2,"P","I"
        .word i_pi
                                ;: PI -> float  3.1416, from the table fatan folds against
        .byte 3,"S","I","N"
        .word i_sin
                                ;: SIN(x:float) -> float  radians
        .byte 3,"C","O","S"
        .word i_cos
                                ;: COS(x:float) -> float  radians
        .byte 3,"T","A","N"
        .word i_tan
                                ;: TAN(x:float) -> float  radians; unchecked at a pole
        .byte 3,"A","T","N"
        .word i_atn
                                ;: ATN(x:float) -> float  radians
        .byte 3,"S","Q","R"
        .word i_sqr
                                ;: SQR(x:float) -> float  a negative returns the argument, silently
        .byte 3,"L","O","G"
        .word i_log
                                ;: LOG(x:float) -> float  natural; not-positive returns the argument
        .byte 3,"E","X","P"
        .word i_exp
                                ;: EXP(x:float) -> float
        .byte 3,"F","L","T"
        .word i_flt
                                ;: FLT(n:int) -> float
        .byte 3,"A","B","S"
        .word i_abs
                                ;: ABS(n:int|float) -> same  keeps the type it was given
        .byte 3,"S","G","N"
        .word i_sgn
                                ;: SGN(n:int|float) -> int  -1, 0 or 1, always an integer
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
; subname -- NBUF gets the sigil that makes it a SUB's name.
;
; **'!' and not '#'.** `#` is the float suffix, so `SUB FOO` and the
; float variable `FOO#` keyed the same name-table entry: whichever was
; written last won, and `CALL FOO` jumped into the float's bit pattern
; and did nothing at all -- no error, no output. Measured: a SUB alone
; prints, a SUB beside an unrelated `BAR#` prints, a SUB beside `FOO#`
; is silent.
;
; `!` carries no bit 7 in `ctab`, so no identifier can ever end with it
; -- the same property `(` has, which is what makes arrays a separate
; namespace. Three sigils, three namespaces: none, `(`, `!`.
subname:
        LD   R0,[NLEN]
        CMP  R0,#NSIG
        BCS  .bump
        PUSH R0
        LDW  X,#NBUF
        ADDW X,R0
        MOV  R0,#$21            ; '!'
        ST   [X],R0
        POP  R0
.bump:  ADD  R0,#1
        ST   [NLEN],R0
        RET

; lstk -- X on the save stack's base.
;
; **Derived, not stored.** It is always directly above the call stack,
; and page 0 was full to the byte -- a stored pointer would have meant
; moving the map, which [D72] prices at forty claims for two bytes.
lstk:   LD   R0,[CSTK]
        MOV  R1,#<(MAXCALL*CALLFR)
        ADD  R0,R1
        MOV  XL,R0
        LD   R0,[CSTK+1]
        MOV  R1,#>(MAXCALL*CALLFR)
        ADC  R0,R1
        MOV  XH,R0
        RET

; csave -- X on CONT's record, directly above the save stack.
;
; Ten bytes in the user's memory with the two stacks, for their reason:
; the storage region is packed and this is per-program state, like the
; name table it sits above.
csave:  CALL lstk
        MOV  R0,XH
        ADD  R0,#>LSTKSZ
        MOV  XH,R0
        RET

; ltop -- X one past everything the stacks and CONT's record own, which
; is the floor the heap may not come below.
ltop:   CALL csave
        MOV  R0,XL
        ADD  R0,#CSAVESZ
        MOV  R1,XH
        MOV  R2,#0
        ADC  R1,R2
        MOV  XL,R0
        MOV  XH,R1
        RET

; icsv -- remember where a break happened, so CONT can go back to it.
;
; **`ipoll` fires at a statement boundary and nowhere else.** All four
; of its callers are loop and branch back-edges, each one `JMP stmt`
; immediately after -- so LREC and Y already name the statement that
; was about to run, and CONT resumes exactly there rather than
; somewhere in the middle of one.
;
; The five depths go with it because `idrct` resets them for every
; direct line, CONT included: the FOR, DO, ELSE, CALL and save stacks
; still hold their frames, but the counters that say how many would be
; zero by the time CONT ran. Without these, continuing out of a loop
; would be ?NEXT WITHOUT FOR.
icsv:   PUSHW X
        PUSH R0
        PUSH R1
        CALL csave
        LD   R0,[LREC]
        ST   [X],R0
        INCW X
        LD   R0,[LREC+1]
        ST   [X],R0
        INCW X
        MOV  R0,YL
        ST   [X],R0
        INCW X
        MOV  R0,YH
        ST   [X],R0
        INCW X
        LD   R0,[FDEPTH]
        ST   [X],R0
        INCW X
        LD   R0,[DDEPTH]
        ST   [X],R0
        INCW X
        LD   R0,[EDEPTH]
        ST   [X],R0
        INCW X
        LD   R0,[CDEPTH]
        ST   [X],R0
        INCW X
        LD   R0,[LDEPTH]
        ST   [X],R0
        INCW X
        MOV  R0,#1
        ST   [X],R0
        POP  R1
        POP  R0
        POPW X
        RET

; ---------------------------------------------------------------------
; The save stack: what a parameter or a LOCAL hid, and where it went.
;
; **A parameter and a local are the same mechanism** -- save the
; variable's current value on entry, restore it on the way out. That is
; BBC BASIC's shape, and it is nearly free here because every variable
; already lives at a fixed address: A-Z resident, or a name-table slot.
; No new binding, no scope chain, and crucially **no cost at all to
; reading the variable inside the sub** -- a parameter is an ordinary
; variable at its ordinary address, so the sub's body runs at exactly
; the speed it ran at before. Recursion works because each level saves
; and restores its own.
;
; A record is the handle and the four bytes it hid. Residents only own
; two of those -- the other two belong to the next letter -- so reading
; four is harmless and only two are ever put back.
; ---------------------------------------------------------------------

; lpush -- save the variable whose handle is R2.
lpush:  LD   R0,[LDEPTH]
        CMP  R0,#(LSTKSZ/LSAVE)
        BHS  .full
        PUSH R2
        MOV  R1,#LSAVE
        MUL  R0,R1              ; X = depth * LSAVE
        MOV  R0,XL
        MOV  R1,XH
        PUSH R1                 ; **lstk uses R0 and R1.** The offset
        PUSH R0                 ;   was in them, so every save landed in
        CALL lstk               ;   slot zero and the last one written
        POP  R0                 ;   came back at every level: 4 3 2 1
        POP  R1                 ;   going down and 2 2 2 coming up.
        CALL addx16             ; X = the slot
        POP  R2
        MOV  R0,R2
        ST   [X],R0             ; the handle it belongs to
        INCW X
        PUSHW X
        MOV  R0,R2
        CALL varaddr            ; X = where the variable lives
        MOV  R0,XL
        MOV  R1,XH
        POPW X
        PUSHW Y
        MOV  YL,R0
        MOV  YH,R1
        MOV  R1,#4
.cp:    LD   R0,[Y+]
        ST   [X],R0
        INCW X
        SUB  R1,#1
        BNE  .cp
        POPW Y
        LD   R0,[LDEPTH]
        ADD  R0,#1
        ST   [LDEPTH],R0
        CLC
        RET
.full:  MOV  R0,#E_CALL
        ST   [ERR],R0
        SEC
        RET

; lunwind -- put back every save above depth R2.
lunwind:
        LD   R0,[LDEPTH]
        CMP  R0,R2
        BLS  .done
        SUB  R0,#1
        ST   [LDEPTH],R0
        PUSH R2
        MOV  R1,#LSAVE
        MUL  R0,R1
        MOV  R0,XL
        MOV  R1,XH
        PUSH R1                 ; lstk uses R0 and R1; see lpush
        PUSH R0
        CALL lstk
        POP  R0
        POP  R1
        CALL addx16             ; X = the slot being undone
        LD   R2,[X]             ; the handle
        INCW X
        MOV  R0,XL
        MOV  R1,XH
        PUSHW Y
        MOV  YL,R0
        MOV  YH,R1              ; Y walks the saved bytes
        MOV  R0,R2
        PUSH R2
        CALL varaddr            ; X = where they go back
        POP  R2
        MOV  R1,#4              ; a resident owns only the first two
        CMP  R2,#52
        BHS  .four
        MOV  R1,#2
.four:  LD   R0,[Y+]
        ST   [X],R0
        INCW X
        SUB  R1,#1
        BNE  .four
        POPW Y
        POP  R2
        BRA  lunwind
.done:  RET

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

; cpush -- the return frame: where Y is, which record, and how many
; saves to undo.
;
; **GOSUB and CALL push the same five bytes**, and `h_ret` pops them
; without caring which put them there. A GOSUB frame records the save
; depth *unchanged*, so the unwind on the way back does nothing -- which
; is why RETURN needed no change at all to serve both.
cpush:  CALL cfr
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
        INCW X
        LD   R0,[LDEPTH]        ; how far to unwind on the way back
        ST   [X],R0
        LD   R0,[CDEPTH]
        ADD  R0,#1
        ST   [CDEPTH],R0
        RET

; GOSUB line -- CALL's frame, GOTO's jump.
;
; The frame is pushed *after* the line number is evaluated, so Y is
; already past the expression and RETURN resumes at the next statement.
h_gosub:
        LD   R0,[CDEPTH]
        CMP  R0,#MAXCALL
        BCC  .room
        JMP  e_call
.room:  CALL eval               ; the line number, as GOTO evaluates it
        PUSH R1
        PUSH R0
        CALL cpush
        POP  R0
        POP  R1
        JMP  goton              ; and go, exactly where GOTO goes

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
        CALL cpush              ; and where to come back to
        POP  R0
        POP  R1
        ST   [LREC],R0
        ST   [LREC+1],R1
        CALL openline
        SKIPSP
        INCW Y                  ; the SUB token
        SKIPSP
        CALL nscan              ; and its name
        JMP  argpass            ; the parameters, if it has any

; ---------------------------------------------------------------------
; argpass -- bind the arguments at the call site to the formals in the
; SUB's header. Y is on the SUB's header, past its name; the call site
; is in the frame this call just pushed.
;
; **Two lines are open and there is one Y**, so the SUB side stays in Y
; and the call site is read from and written back to the frame slot it
; already occupies. Nothing new stores it.
;
; The order is the one chosen deliberately: each formal is saved, then
; its argument evaluated, then assigned, left to right. So an argument
; naming one of this sub's own parameters sees the value already put
; there -- `SUB F(A,B)` called `CALL F(1,A)` gives B the 1, not the
; caller's A. Evaluating every argument first would avoid that and needs
; somewhere to hold them, which the single string accumulator cannot be:
; two string arguments would each have to reach the heap first.
; ---------------------------------------------------------------------
argpass:
        SKIPSP
        CMP  R2,#$28            ; '(' -- does this SUB take any?
        BEQ  .some
        ; None. The call site must not be offering any either, or its
        ; `(1)` is left for the caller's own line to parse when the sub
        ; returns -- which read as a subscript and said ?INDEX, naming
        ; the call rather than the mismatch.
        PUSHW Y
        CALL cs_get
        SKIPSP
        CMP  R2,#$28
        BEQ  .noargs
        POPW Y
        JMP  stmt               ; no parameters: nothing to bind

.some:  ; the call site must open a list too. **Y is stacked around
        ; every excursion**: cs_get puts the call site in it and there
        ; is only one Y, so without this the loop walks the caller's
        ; line looking for the sub's formals.
        PUSHW Y                 ; the SUB side
        CALL cs_get
        SKIPSP
        CMP  R2,#$28
        BNE  .noargs
        ; **Left sitting on the '(' deliberately.** `.each` skips one
        ; byte on each side per argument -- the '(' first time round and
        ; the ',' after -- so consuming it here as well put `eval` one
        ; byte into the first argument's literal, where $07 is not a
        ; token that can start anything.
        CALL cs_put
        POPW Y

.each:  INCW Y                  ; the SUB side, over '(' or ','
        SKIPSP                  ; **`SUB F(A, B)` has a space in it** and
                                ;   varidx reads [Y] straight off without
                                ;   skipping any. Measured: without this
                                ;   the definition is ?SYNTAX the moment
                                ;   anyone writes the comma the way they
                                ;   would write it anywhere else.
        CALL varidx             ; R0 = the formal's handle, Y past it
        LD   R2,[ERR]
        BNE  .bad
        MOV  R2,R0

        ; What this parameter is, read off its suffix **now** -- `eval`
        ; scans names of its own and NBUF will not survive it.
        CLR  R3
        CMP  R2,#52
        BLO  .typed             ; a resident A-Z is always an integer
        PUSH R2
        CALL isflt
        POP  R2
        BCS  .nfl
        MOV  R3,#2
        BRA  .typed
.nfl:   PUSH R2
        CALL isstr
        POP  R2
        BCS  .typed
        MOV  R3,#1
.typed: PUSH R3

        PUSH R2
        CALL lpush              ; what the caller had, kept
        POP  R2
        LD   R0,[ERR]
        BNE  .bad3

        ; over to the call site for the argument, and back again
        PUSH R2
        PUSHW Y                 ; the SUB side
        CALL cs_get
        INCW Y                  ; over '(' or ','
        CALL eval
        PUSH R1
        PUSH R0
        CALL cs_put             ; where the call site got to
        ; **ERR is read while the value is still on the stack.** Reading
        ; it into R0 after the pops destroys the low byte of an integer
        ; argument, which is why every integer parameter arrived as 0
        ; while floats and strings -- which travel in FACC and SACC --
        ; came through correctly.
        LD   R0,[ERR]
        TST  R0
        BNE  .bade
        POP  R0
        POP  R1
        POPW Y                  ; the SUB side again
        POP  R2
        POP  R3                 ; what the parameter wants

        CALL argst              ; assign, with the type checked
        LD   R0,[ERR]
        BNE  .bad

        SKIPSP                  ; another formal?
        CMP  R2,#$2C
        BEQ  .each
        SKIPSP
        INCW Y                  ; the ')' on the SUB side
        PUSHW Y
        CALL cs_get             ; and on the call site
        SKIPSP
        CMP  R2,#$29
        BNE  .bad2
        INCW Y
        CALL cs_put
        POPW Y                  ; back to the SUB, which is where the
        JMP  stmt               ;   next statement executed lives
.bad2:  POPW Y
        JMP  e_call
.noargs:
        POPW Y                  ; .some's copy of the SUB side. Branched
        JMP  e_call             ;   to, not fallen into, so it undoes
                                ;   its own push or the machine hangs
.bade:  ADDW SP,#7              ; value, Y, handle, wanted type
        RET
.bad3:  ADDW SP,#1              ; the wanted type, never read
.bad:   RET                     ; ERR is set; stmt stops

; cs_get / cs_put -- Y is the call site, out of and back into the frame
; of the call in progress. CDEPTH has already been bumped, so the frame
; wanted is the one below it.
cfrp:   LD   R0,[CDEPTH]
        SUB  R0,#1
        MOV  R1,#CALLFR
        MUL  R0,R1
        MOV  R0,XL
        MOV  R1,XH
        LD   R2,[CSTK]
        MOV  XL,R2
        LD   R2,[CSTK+1]
        MOV  XH,R2
        JMP  addx16

cs_get: PUSH R0
        PUSH R1
        PUSH R2
        CALL cfrp
        LD   R0,[X]
        MOV  YL,R0
        INCW X
        LD   R0,[X]
        MOV  YH,R0
        POP  R2
        POP  R1
        POP  R0
        RET

cs_put: PUSH R0
        PUSH R1
        PUSH R2
        CALL cfrp
        MOV  R0,YL
        ST   [X],R0
        INCW X
        MOV  R0,YH
        ST   [X],R0
        POP  R2
        POP  R1
        POP  R0
        RET

; argst -- the argument in R0:R1 (or FACC, or SACC) into the formal
; whose handle is R2, when the formal wants type R3.
;
; **The wanted type is decided before `eval` runs**, because `eval`
; scans names of its own and NBUF is gone by the time the value
; arrives. A resident A-Z is always an integer; anything longer carries
; its suffix.
argst:  ; **R0:R1 is the integer argument and almost everything here
        ; wants R0.** Reading STYPE into it destroyed the low byte
        ; before the store ever ran, so every integer parameter arrived
        ; as 0 while floats and strings -- which travel in FACC and
        ; SACC and never touch R0:R1 -- came through perfectly. Stacked
        ; across the whole type decision.
        PUSH R1
        PUSH R0
        LD   R0,[STYPE]
        CMP  R0,R3
        BEQ  .same
        ; The only conversion: an integer handed to a float parameter
        ; promotes, exactly as `A# = 1` does. Nothing else converts.
        CMP  R3,#2
        BNE  .type
        TST  R0
        BNE  .type
        POP  R0
        POP  R1
        PUSH R2                 ; ffromi does not preserve it, and R2 is
        CALL ffromi             ;   the handle everything below needs
        POP  R2
        BRA  .stf
.same:  POP  R0
        POP  R1
        TST  R3
        BEQ  .sti
        CMP  R3,#2
        BEQ  .stf
        BRA  .sts
.type:  ADDW SP,#2
        MOV  R0,#E_TYPE
        ST   [ERR],R0
        RET

.sti:   PUSH R1
        PUSH R0
        MOV  R0,R2
        CALL varaddr
        POP  R0
        ST   [X],R0
        INCW X
        POP  R0
        ST   [X],R0
        RET

.stf:   MOV  R0,R2
        CALL varaddr
        JMP  fstore

        ; **The descriptor is cleared before the string is stored.**
        ; Otherwise `sstore` reads the caller's maxlen, decides the new
        ; value fits, and writes into the caller's characters -- which
        ; RETURN then restores a descriptor pointing at. Cleared, it
        ; allocates its own, which is what a parameter costs: one block
        ; per call, and nothing reclaims it until RUN.
.sts:   PUSH R2
        MOV  R0,R2
        CALL varaddr
        CLR  R0
        ST   [X],R0
        INCW X
        ST   [X],R0
        INCW X
        ST   [X],R0
        INCW X
        ST   [X],R0
        POP  R2
        MOV  R0,R2
        CALL varaddr
        JMP  sstore

h_ret:  LD   R0,[CDEPTH]
        BNE  .live
        JMP  e_call             ; RETURN without CALL
.live:  SUB  R0,#1
        ST   [CDEPTH],R0
        ; **The saves come back before the frame does.** The frame's
        ; fifth byte is the save depth when the call was made, so a sub
        ; that took three parameters and declared two locals unwinds
        ; five, whatever order they went on in.
        CALL cfr
        MOV  R0,XL
        ADD  R0,#4
        MOV  XL,R0
        MOV  R0,XH
        ADC  R0,#0
        MOV  XH,R0
        LD   R2,[X]
        CALL lunwind
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
        LD   R2,[STYPE]         ; a float renders itself; see .flt
        CMP  R2,#2
        BEQ  .flt
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
        ; STR$ of a float, and it needed no printer: `fstr` renders into
        ; FSBUF and answers a length, and `sappend` takes exactly a
        ; (pointer, count) -- the same pair PRINT hands to s_putsn. So
        ; the digits come from the code that already prints them, and
        ; STR$(X#) and PRINT X# cannot disagree about a value.
        ;
        ; **Appended, not assigned.** `fprint` points SACC at FSBUF,
        ; which is right for PRINT and wrong here: STR$ builds onto the
        ; accumulator, so `A$ + STR$(X#)` must keep what is already
        ; there. sappend copies, and sets STYPE to 1 on the way out.
.flt:   PUSHW Y                 ; fstr walks Y over its output
        CALL fstr
        POPW Y
        MOV  R2,R0              ; the length it answered
        LDW  X,#FSBUF
        MOV  R0,XL
        MOV  R1,XH
        JMP  sappend

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
        CALL snum
        POPW Y
        RET

; ---------------------------------------------------------------------
; snum -- SDIG characters of text at Y, as a number.
;
; **This is Microsoft's FIN**, and it is factored out for the same
; reason theirs is: INPUT and VAL must agree about what a typed number
; means, and the only way to guarantee that is one routine. Their INPUT
; reads a line into BUF and calls FIN; ours reads a line into the
; string accumulator and calls this.
;
; Leaves an integer in R0:R1 with STYPE 0, or a float in FACC with
; STYPE 2 -- the decimal point is what decides, and the caller reads
; STYPE to know which. Clobbers Y; the caller saves it.
; ---------------------------------------------------------------------
; snumi -- the same digits, but a '.' *ends* the number instead of
; starting a fraction. A line number, a subscript and a RENUMBER step
; all want that; VAL and INPUT want the other. One seed value is the
; whole difference, so the two share every instruction below rather
; than the editor keeping a second parser -- which is what [D66] is
; about, and `number()` in sw/basic.bas was 193 bytes of it.
; The join is a global because a local resolves against whichever
; global precedes it, so `snumi` could not branch into `snum`'s scope.
; `snumb` owns the locals below; nothing outside this file names them.
snumi:  MOV  R2,#$FE            ; a point is not part of this number
        BRA  snumb
snum:   MOV  R2,#$FF            ; ...but may start a fraction in this one
snumb:  ST   [SFRAC],R2
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
        BCC  .dot               ; not a digit -- a '.' continues, and
        CMP  R2,#$3A            ;   anything else ends it, which is what
        BCS  .fin               ;   makes VAL("12AB") twelve
        INCW Y
        SUB  R3,#1
        ST   [SDIG],R3
        LD   R3,[SFRAC]         ; four fraction digits is all 4.8 decimal
        CMP  R3,#4              ;   digits can carry, and it is also what
        BEQ  .loop              ;   keeps 10^n inside sixteen bits below
        PUSH R2
        MOV  R2,#10
        CLR  R3
        CALL imul16
        POP  R2
        SUB  R2,#$30
        ADD  R0,R2
        MOV  R2,#0
        ADC  R1,R2
        LD   R2,[SFRAC]
        CMP  R2,#5              ; **one predicate, used twice**: under
        BCS  .loop              ;   five means counting fraction digits,
                                ;   so $FF (no point yet) and $FE (a
                                ;   point may not start one) both fall
                                ;   out here. Testing $FF alone let the
                                ;   integer-only seed be incremented
                                ;   into the fraction seed by the first
                                ;   digit, and "10.5" became a float.
        ADD  R2,#1
        ST   [SFRAC],R2
        BRA  .loop
        ; A '.' switches the same loop into counting mode. A second one
        ; ends the number, the way any other non-digit does.
.dot:   CMP  R2,#$2E
        BNE  .fin
        LD   R2,[SFRAC]
        CMP  R2,#$FF
        BNE  .fin
        CLR  R2
        ST   [SFRAC],R2
        INCW Y
        SUB  R3,#1
        ST   [SDIG],R3
        BRA  .loop
.fin:   LD   R2,[DSGN]
        BEQ  .nsg
        CALL negp16
.nsg:   LD   R2,[SFRAC]
        CMP  R2,#5              ; 0..4 counted fraction digits; $FE and
        BCC  .flt               ;   $FF are both "no fraction here"
.out:   CLR  R2
        ST   [STYPE],R2
        RET
        ; **One divide, and no constant.** The digits are already an
        ; integer; 10^n for n up to four is 10000, which fits sixteen
        ; bits, so the scale is built with the imul16 already here and
        ; converted once. Dividing by ten n times instead would need a
        ; float ten in the image and up to four times the work.
.flt:   PUSH R1
        PUSH R0
        MOV  R0,#1
        CLR  R1
.pw:    LD   R2,[SFRAC]
        TST  R2
        BEQ  .pwd
        SUB  R2,#1
        ST   [SFRAC],R2
        MOV  R2,#10
        CLR  R3
        CALL imul16
        BRA  .pw
.pwd:   CALL ffromi             ; FACC = 10^n
        CALL fa2b               ; FARG = 10^n
        POP  R0
        POP  R1
        CALL ffromi             ; FACC = the digits, sign and all
        CALL fdiv
        JMP  fretf

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
; `ibreak` is in sw/lowram.asm's system storage region ([D67]).

; ipoll -- checked at the loop back-edges only, because those are the
; only places a program can spin: NEXT going round, LOOP going round,
; GOTO, and RETURN. A straight-line program cannot fail to end.
ipoll:  LD   R2,[ibreak]
        BNE  .brk
        RET
.brk:   CLR  R2
        ST   [ibreak],R2
        ; **STOP is this, and nothing else.** The break key and the
        ; keyword are the same event -- stop here, remember here, let
        ; CONT come back -- so the statement is ipoll's own tail with a
        ; label on it, and the test above is inverted so it falls in.
        ; One byte for the whole statement. Writing it separately would
        ; have been a second answer to "what does stopping mean", and
        ; the two would have drifted the first time CONT changed.
        ;
        ; A STOP typed in direct mode records a record outside
        ; $0200..PROGEND, which is exactly what `h_cont` rejects as
        ; stale -- so it stops, and there is nothing to resume. That
        ; falls out; it is not a check anybody wrote.
h_stop: CALL icsv               ; where to come back to, for CONT
        MOV  R2,#E_STOP
        ST   [ERR],R2
        ; **The editor is about to have the screen back, so it takes its
        ; cursor with it.** A program may have turned it off (`CURSOR 0`)
        ; and a break is not a warm restart -- nothing else on this path
        ; puts it back, and a machine that returns to a prompt you cannot
        ; see is one you have to power-cycle to recover.
        ;
        ; Here and not in `main_err`, which a *direct* line also passes
        ; through: doing it there made a typed `CURSOR 0` switch itself
        ; back on before the next keystroke.
        JMP  con_geom           ; ...and its RET is this routine's


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

; The register addresses are `sw/io.asm`'s, which `tools/ioregs.py`
; generates from the Verilog that decodes them and `lowram.asm` includes.
; They used to be eighteen literals here under a private `G`-prefixed
; spelling -- `GVMODE` for `VID_MODE` -- which docs/04a-registers.md
; carried a section apologising for. One name per register now, and the
; address is written down nowhere in `sw/` at all ([D67]).

; The frame counter iisr keeps (TIMER reads it, VSYNC waits on it), the
; random seed, and scratch for up to five parsed arguments plus LINE's
; working set. Equates into the $FF00 workspace page (see basic.bas):
; page 0 is spoken for, and a .space would ship its zeros in the image.
; init seeds rseed to 1 after the page clear -- a zeroed xorshift stays
; zero forever.
; `frames`, `rseed`, `garg`, `lwk`, `FORSTK` and `DIRBUF` are in
; sw/lowram.asm's system storage region now. They were equates here, in the
; $FF00 page, "because page 0 is spoken for and a .space would ship its
; zeros in the image" -- only the second half of which was ever
; architectural, and the I/O page has since moved on top of that page
; ([D67]).

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
; MODE n -- and **the console has to be told**.
;
; `con_geom` reads the hardware and sets the cell size, the row count,
; the font and the mirror that every character write goes through. Its
; header says it is called whenever the editor regains control, which is
; true and was not enough: `MODE 4 : PRINT "X"` prints before the editor
; regains anything, and so does every program that sets a mode and draws.
;
; Without it the console kept the *previous* mode's mirror -- the text
; one -- so the characters went into the cell map, correctly, and no
; glyph was ever drawn. The map had the text and the screen was blank,
; in every mode but the text ones. Modes 2 to 5 looked broken and were
; one call away from working.
h_mode: MOV  R3,#1
        CALL gargs
        LD   R0,[garg]
        AND  R0,#$0F
        OR   R0,#$80
        ST   [VID_MODE],R0
        PUSHW Y                 ; Y is the token pointer; con_tilefont
        CALL con_geom           ;   borrows Y to walk the font
        POPW Y
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
pixxy:  LD   R0,[garg]
        ST   [PIX_X_L],R0
        LD   R0,[garg+1]
        ST   [PIX_X_H],R0
        LD   R0,[garg+2]
        ST   [PIX_Y_L],R0
        LD   R0,[garg+3]
        ST   [PIX_Y_H],R0
        RET

; PLOT x,y,c -- one pixel, in the current mode's depth, masked by the
; hardware. Five stores end to end.
h_plot: MOV  R3,#3
        CALL gargs
        CALL pixxy
        LD   R0,[garg+4]
        ST   [PIX_DATA],R0
        JMP  stmt

; HLINE x,y,n,c -- n pixels rightward. One store each: the port steps X.
; HLINE is gone, and it was never the algorithm it looked like. The
; pixel port advances X itself after every plot (`S_END: pix_x <=
; pix_x + 1` in rtl/soc/cool8_pixport.v), which is why the loop here
; wrote PIX_DATA over and over without touching a coordinate. So a run of
; pixels is four register writes and then one POKE each -- the same
; single store per pixel this did -- and the command was carrying no
; work the hardware was not already doing. See 13-basic.md section 5.
h_sound:
        MOV  R3,#4
        CALL gargs
        LD   R0,[garg]
        ADD  R0,R0
        ADD  R0,R0
        ADD  R0,R0
        ST   [SND_IDX],R0
        LD   R1,[garg+2]
        ST   [SND_DATA],R1
        LD   R1,[garg+3]        ; the word commits on the odd byte
        ST   [SND_DATA],R1
        ADD  R0,#4
        ST   [SND_IDX],R0
        LD   R1,[garg+4]
        AND  R1,#$0F
        ST   [SND_DATA],R1
        LD   R1,[garg+6]
        TST  R1
        BEQ  .sq
        MOV  R1,#$C0
        BRA  .sn
.sq:    MOV  R1,#$40
.sn:    ST   [SND_DATA],R1
        JMP  stmt

; LINE x0,y0,x1,y1,c -- Bresenham over the pixel port's two
; auto-incrementing stores (D91). Measured before the rework: 225-260
; cycles a pixel, octant depending -- pixxy rewrote four port bytes for
; every pixel and four 16-bit words were compared to decide whether to
; stop. Measured after: **121 steep, 101 vertical, 170-181 shallow and
; diagonal** -- the y walk is PIX_DATA_Y's own step, the rightward x
; walk is PIX_DATA's, the endpoint test is a pixel countdown, and only
; a leftward or diagonal x step rewrites a coordinate. `hrun` below
; still takes the horizontal case at about 22. Coordinates are at most
; ten bits, so every quantity fits 16-bit signed arithmetic with room
; and the sign tests cannot overflow.
h_line: MOV  R3,#5
        CALL gargs
        ; **y0 == y1 goes somewhere else entirely.** See `hrun`.
        LD   R0,[garg+2]
        LD   R2,[garg+6]
        CMP  R0,R2
        BNE  .bres
        LD   R0,[garg+3]
        LD   R2,[garg+7]
        CMP  R0,R2
        BNE  .bres
        JMP  hrun
.bres:  ; **Drawn downward, always.** If y1 < y0 the endpoints swap, so
        ; sy is +1 by construction and every y step is PIX_DATA_Y's own
        ; increment (D91) -- no sy word, no y bookkeeping, the port
        ; carries y for the whole line. On the exact half-step ties
        ; this picks the mirror pixel of what the old walk chose from
        ; the caller's end; sim/test_run.py's fan is the contract.
        LD   R0,[garg+6]
        LD   R1,[garg+7]
        LD   R2,[garg+2]
        LD   R3,[garg+3]
        SUB  R0,R2
        SBC  R1,R3
        BGE  .cdn
        LD   R0,[garg]          ; four byte pairs, unrolled -- there is
        LD   R2,[garg+4]        ; no indexed displacement mode to loop
        ST   [garg],R2          ; with
        ST   [garg+4],R0
        LD   R0,[garg+1]
        LD   R2,[garg+5]
        ST   [garg+1],R2
        ST   [garg+5],R0
        LD   R0,[garg+2]
        LD   R2,[garg+6]
        ST   [garg+2],R2
        ST   [garg+6],R0
        LD   R0,[garg+3]
        LD   R2,[garg+7]
        ST   [garg+3],R2
        ST   [garg+7],R0
.cdn:   ; dx = |x1-x0| -> lwk, the x direction as a byte flag -> lwk+6
        LD   R0,[garg+4]
        LD   R1,[garg+5]
        LD   R3,[garg]
        SUB  R0,R3
        LD   R3,[garg+1]
        SBC  R1,R3
        MOV  R2,#$00
        BGE  .lx
        CALL negp16
        MOV  R2,#$01
.lx:    ST   [lwk],R0
        ST   [lwk+1],R1
        MOV  R0,R2
        ST   [lwk+6],R0
        ; dy = y1-y0, positive now; count = max(dx,dy)+1 pixels, which
        ; replaces the old four-word endpoint compare -- the dominant
        ; axis steps every iteration, so the length is known up front
        LD   R0,[garg+6]
        LD   R1,[garg+7]
        LD   R3,[garg+2]
        SUB  R0,R3
        LD   R3,[garg+3]
        SBC  R1,R3
        MOV  R2,R0
        MOV  R3,R1
        LD   R0,[lwk]
        LD   R1,[lwk+1]
        SUB  R0,R2
        SBC  R1,R3
        BGE  .cdx
        MOV  R0,R2              ; dy is dominant
        MOV  R1,R3
        BRA  .cst
.cdx:   LD   R0,[lwk]
        LD   R1,[lwk+1]
.cst:   ADD  R0,#1
        BLO  .cs2
        ADD  R1,#1
.cs2:   ST   [lwk+7],R0
        ST   [lwk+8],R1
        MOV  R0,R2              ; dyn = -dy -> lwk+2
        MOV  R1,R3
        CALL negp16
        ST   [lwk+2],R0
        ST   [lwk+3],R1
        ; err = dx + dyn
        LD   R0,[lwk]
        LD   R1,[lwk+1]
        LD   R2,[lwk+2]
        LD   R3,[lwk+3]
        ADD  R0,R2
        ADC  R1,R3
        ST   [lwk+4],R0
        ST   [lwk+5],R1
        CALL pixxy              ; the port holds the current pixel from
                                ; here on -- every branch below plots
                                ; through the store whose auto-increment
                                ; lands the port on the next one
.lp:    LD   R0,[lwk+4]
        LD   R1,[lwk+5]
        ADD  R0,R0
        ADC  R1,R1
        PUSH R1                 ; both tests must see this same e2 --
        PUSH R0                 ;   err changes between them
        LD   R2,[lwk+2]
        LD   R3,[lwk+3]
        SUB  R0,R2
        SBC  R1,R3
        BLT  .yst               ; e2 < dy: the y-only step
        LD   R0,[lwk+4]         ; x steps: err += dy
        ADD  R0,R2
        ST   [lwk+4],R0
        LD   R0,[lwk+5]
        ADC  R0,R3
        ST   [lwk+5],R0
        POP  R0                 ; and y too?  e2 <= dx
        POP  R1
        LD   R2,[lwk]
        LD   R3,[lwk+1]
        SUB  R2,R0
        SBC  R3,R1
        BLT  .xst
        LD   R0,[lwk]           ; both: err += dx, plot stepping y,
        LD   R2,[lwk+4]         ; then walk x by sx
        ADD  R2,R0
        ST   [lwk+4],R2
        LD   R0,[lwk+1]
        LD   R2,[lwk+5]
        ADC  R2,R0
        ST   [lwk+5],R2
        LD   R0,[garg+8]
        ST   [PIX_DATA_Y],R0
        CALL lxmov
        BRA  .ltl
.xst:   ; x alone: plot stepping x. Rightward the port's own step *is*
        ; the walk and software x only follows; leftward the port
        ; stepped the wrong way and lxmov rewrites it outright.
        LD   R0,[garg+8]
        ST   [PIX_DATA],R0
        LD   R0,[lwk+6]
        OR   R0,R0
        BNE  .xsl
        LD   R0,[garg]
        ADD  R0,#1
        ST   [garg],R0
        BLO  .ltl
        LD   R0,[garg+1]
        ADD  R0,#1
        ST   [garg+1],R0
        BRA  .ltl
.xsl:   CALL lxmov
        BRA  .ltl
.yst:   POP  R0                 ; discard the saved e2
        POP  R0
        LD   R0,[lwk]           ; err += dx
        LD   R2,[lwk+4]
        ADD  R2,R0
        ST   [lwk+4],R2
        LD   R0,[lwk+1]
        LD   R2,[lwk+5]
        ADC  R2,R0
        ST   [lwk+5],R2
        LD   R0,[garg+8]
        ST   [PIX_DATA_Y],R0    ; port x is already right, y steps
.ltl:   LD   R0,[lwk+7]         ; one more pixel down
        SUB  R0,#1
        ST   [lwk+7],R0
        BHS  .ltz
        LD   R0,[lwk+8]
        SUB  R0,#1
        ST   [lwk+8],R0
.ltz:   LD   R0,[lwk+7]
        LD   R1,[lwk+8]
        OR   R0,R1
        BEQ  .lfin
        JMP  .lp
.lfin:  JMP  stmt

; lxmov -- the walking x, one step by sx: garg's copy moves and the
; port is rewritten to match. **X_H is stored every time, not only
; when garg's low byte wraps**: a leftward step follows a PIX_DATA
; store, and the port's auto-increment moved the whole 11-bit
; register -- at x=255 the port sits at 256 with high bits the port
; set itself, and a low-byte-only rewrite landed it on 510. Shared by
; the diagonal and the leftward x step; the rightward x-only step
; never calls it, because PIX_DATA's own increment is the walk.
lxmov:  LD   R0,[lwk+6]
        OR   R0,R0
        BNE  .neg
        LD   R0,[garg]
        ADD  R0,#1
        ST   [garg],R0
        ST   [PIX_X_L],R0
        BLO  .done
        LD   R0,[garg+1]
        ADD  R0,#1
        ST   [garg+1],R0
.done:  LD   R0,[garg+1]
        ST   [PIX_X_H],R0
        RET
.neg:   LD   R0,[garg]
        SUB  R0,#1
        ST   [garg],R0
        ST   [PIX_X_L],R0
        BHS  .fin
        LD   R0,[garg+1]
        SUB  R0,#1
        ST   [garg+1],R0
.fin:   LD   R0,[garg+1]
        ST   [PIX_X_H],R0
        RET

; ---------------------------------------------------------------------
; hrun -- LINE where y0 == y1: set the port once, then store.
;
; **PIX_DATA auto-increments X** (04-system.md section 5.7). The
; Bresenham loop above uses the port's steps too now (D91), but a
; horizontal span still has nothing to decide per pixel, so this stays
; the fastest path: measured when it was written, a 256-pixel span
; through the old general loop cost **6.4 ms -- 209 cycles a pixel**,
; against CLG's 10 on the same memory path doing the same work. The
; hardware was never the limit; the general algorithm was.
;
; Left to right, because the port only steps one way, so x0 > x1 swaps
; the ends. The count is 16-bit -- a span reaches 640 pixels in mode 3
; -- and SUB's borrow carries it into the high byte.
;
; The colour sits in R2 for the whole run, so nothing in here may call
; anything that clobbers it.
; ---------------------------------------------------------------------
hrun:   LD   R0,[garg+4]        ; x1 - x0
        LD   R1,[garg+5]
        LD   R2,[garg]
        LD   R3,[garg+1]
        SUB  R0,R2
        SBC  R1,R3
        BGE  .fwd
        CALL negp16             ; |x1 - x0|, and x1 is the left end
        LD   R2,[garg+4]
        ST   [garg],R2
        LD   R2,[garg+5]
        ST   [garg+1],R2
.fwd:   PUSH R1                 ; pixxy walks R0; the count must survive
        PUSH R0
        CALL pixxy              ; PIX_X = the left end, PIX_Y = y0
        POP  R0
        POP  R1
        LD   R2,[garg+8]        ; the colour, held for the whole run
.st:    ST   [PIX_DATA],R2      ; and the port steps X itself
        MOV  R3,R0              ; n == 0 means that was the last pixel
        OR   R3,R1
        BEQ  .fin
        SUB  R0,#1
        BHS  .st                ; carry is "no borrow" (D9)
        SUB  R1,#1
        BRA  .st
.fin:   JMP  stmt


; earg -- "( expression )": the prologue every one-argument builtin
; shares, ten of them. The tail call keeps sopen error handling and
; its RET as the return.
earg:   CALL sopen
        CALL eval
        JMP  sopen

; ---------------------------------------------------------------------
; evali -- eval, and answer an integer in R0:R1 whichever type it was.
;
; **The float-to-integer crossing, at the door of everything that wants
; an integer** ([D88]). Before this, a float assigned to an integer kept
; whatever `eval` left in R0:R1 -- raw bits, not a value -- so
; `A = 110*SIN(X#)` stored 2 while `PRINT` of the same expression
; printed 110. The arithmetic could be checked at the prompt, agree, and
; still be wrong once stored, which is the worst shape a fault takes.
;
; **`ftoi` and not a second conversion**: it is the flooring `INT()`
; already uses (`iint` below), so the implicit crossing and the explicit
; one cannot drift apart, and a program that adds `INT()` by hand gets
; the same answer it had without it.
;
; The type is not recomputed -- `STYPE` is a byte every value already
; sets so `PRINT` can pick `fprint` over `num_put` -- so correct integer
; code pays one load and one compare, once per value, never per
; operation.
;
; **Not folded into `earg`**, which is the tempting place because
; `PLOT`, subscripts and the builtins all go through it. `STR$` reads
; `STYPE` itself to render a float, and `INT()` needs the float intact
; to floor it; converting inside `earg` would make `STR$(3.5)` say "3".
; The crossing belongs where an integer is *wanted*, not where an
; argument is *parsed*.
; ---------------------------------------------------------------------
evali:  CALL eval
        LD   R2,[STYPE]
        CMP  R2,#2              ; 2 is float here -- STYPE's 1 is string
        BNE  .done
        PUSHW Y                 ; every caller parses on from Y
        CALL ftoi               ; FACC -> R0:R1, flooring, saturating
        POPW Y
.done:  RET

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

; ERR -- which fault the handler was entered for. Zero until one is
; caught, and it is *not* cleared by reading: a handler that wants to
; know twice should not have to save it.
ierr:   LD   R0,[ELAST]
        CLR  R1
        JMP  retnum

; POS and VPOS -- where the cursor is, which TAB already knew and
; nothing could ask. The console's own CCX and CCY, so they are right
; after anything that *moved* the cursor rather than after anything that
; printed. One tail, because a column and a row differ only in which
; byte they read: VPOS branches over POS's load and both fall into the
; widening and the return.
ivpos:  LD   R0,[CCY]
        BRA  posr
ipos:   LD   R0,[CCX]
posr:   CLR  R1
        JMP  retnum

; TRUE and FALSE -- -1 and 0, and they share a tail because [D47] made
; them one thing: TRUE is all bits set precisely so AND/OR/XOR serve
; logic and bits with one implementation. Two constants that differ only
; in the byte they start from is what that decision looks like from
; here, and writing them apart would have hidden it.
itrue:  MOV  R0,#$FF
        BRA  tfr
ifalse: CLR  R0
tfr:    MOV  R1,R0
        JMP  retnum

; VPEEK(a) -- the port's prefetch is armed by the address write and the
; data read stalls until the byte is real, so this is exact.
ivpeek: CALL earg               ; ( expression )
        MOV  R2,R0
        MOV  R0,#1
        ST   [VRAM_STEP],R0
        ST   [VRAM_ADDR_L],R2
        ST   [VRAM_ADDR_H],R1
        LD   R0,[VRAM_DATA]
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

; INPUT var -- a line of text, and then the variable's own suffix
; decides what it meant.
;
; **Microsoft's arrangement, and every part of it already existed
; here.** Their INLIN reads a whole line into BUF, PTRGET reads the '$'
; off the name, and one shared routine assigns -- FIN for a number,
; STRLIT for a string. Ours:
;
;   BUF     the string accumulator, because `stmt` leaves it empty and
;           nothing below statement level may reset it
;   PTRGET  varidx, then isflt/isstr on the name it just buffered --
;           the same three-way h_let does
;   FIN     `snum`, factored out of VAL so a typed number and VAL agree
;   STRLIT  `sstore`, the store h_lets already ends at
;
; So `INPUT A`, `INPUT A$` and `INPUT A#` are one path, and what went
; away is the private digit loop that used to be here -- forty lines
; that could not read a '.' and wrote a number into a string variable.
;
; **Safeguards are the C64's or fewer.** No ?REDO FROM START, no comma
; splitting, and the only bound is SMAX, which is what one byte of
; length allows. Text that is not a number reads as zero, exactly as
; VAL("ABC") does, because it is the same routine saying so.
h_input:
        ; **A prompt is a leading string literal, and that is one byte to
        ; detect.** The C64's rule exactly: a quote starts one, a ';'
        ; ends it. Testing for '"' rather than "is this a string
        ; expression" is what keeps `INPUT A$` and `INPUT "X"; A$`
        ; apart without a lookahead -- and `eval` from the quote takes
        ; a concatenation too, which costs nothing to allow.
        SKIPSP
        CMP  R2,#$22            ; '"'
        BNE  .var
        CALL eval               ; the prompt, into the accumulator
        CALL sacout             ; ...out, and the accumulator emptied
        SKIPSP
        CMP  R2,#$3B            ; ';'
        BNE  .var
        INCW Y
.var:   SKIPSP
        CALL varidx             ; R0 the handle, X the slot, Y past it
        PUSH R0
        PUSHW X
        PUSHW Y                 ; the editor's routines use Y freely
        ; The '? ' both references print, and it goes after the prompt
        ; rather than before it, because `NAME? ` is what a C64 shows.
        ; A bare INPUT printed nothing at all before this, which is a
        ; program that looks hung. The space is the C64's too and it is
        ; the whole difference between `NAME? SAM` and `NAME?SAM`.
        ; After PUSHW Y, because emitc walks it.
        MOV  R0,#$3F
        CLR  R1
        CALL emitc
        MOV  R0,#$20
        CLR  R1
        CALL emitc
.k:     CALL in_get
        TST  R1
        BNE  .k                 ; a named key is not text
        CMP  R0,#$0D
        BEQ  .cr
        PUSH R0
        CALL sputc              ; append; SMAX is the only limit
        POP  R0
        CLR  R1
        CALL emitc              ; s_emit takes its argument on the stack
        BRA  .k
.cr:    CALL pnl
        POPW Y
        POPW X
        POP  R0
        CMP  R0,#52
        BCC  .num               ; resident A-Z is never a string or float
        PUSHW X
        PUSH R0
        CALL isflt
        POP  R0
        POPW X
        BCC  .fvar
        PUSHW X
        CALL isstr
        POPW X
        BCS  .num
        MOV  R2,#1              ; the text is already where sstore wants
        ST   [STYPE],R2
        CALL sstore
        BRA  .more
        ; A# takes whatever was typed, promoting a whole number the way
        ; `A# = 1` does.
.fvar:  CALL .parse
        LD   R2,[STYPE]
        CMP  R2,#2
        BEQ  .fst
        CALL ffromi
.fst:   CALL fstore             ; three bytes; X only, no Y
        BRA  .more
        ; An integer variable floors a typed fraction rather than
        ; storing the stale registers a float would leave -- three
        ; bytes to keep one silent wrong answer out of the language.
.num:   CALL .parse
        LD   R2,[STYPE]
        CMP  R2,#2
        BNE  .ist
        PUSHW Y
        CALL ftoi
        POPW Y
.ist:   ST   [X],R0
        INCW X
        ST   [X],R1
        ; A comma is another variable, and that means another prompt on
        ; another line -- **not one line split on commas**.
        ;
        ; Splitting is the C64's rule and it drags ?REDO FROM START in
        ; with it: too few items on the line has to re-ask, too many has
        ; to complain, and both need the accumulator cut into pieces
        ; while `snum` reads it whole. The note above is still the
        ; policy -- safeguards are the C64's or fewer -- and a prompt per
        ; item needs no policy at all, because a line that ends is one
        ; answer by construction. It is READ's walk, character for
        ; character, which is the other statement that takes a list of
        ; scalar targets.
.more:  SKIPSP
        CMP  R2,#$2C            ; ','
        BNE  .fin
        INCW Y
        BRA  .var
.fin:   JMP  stmt
        ; The whole accumulator is the number, and it is spent either
        ; way: snum takes the text at Y for SDIG characters.
.parse: PUSHW X
        PUSHW Y
        LD   R2,[SACC]
        MOV  YL,R2
        LD   R2,[SACC+1]
        MOV  YH,R2
        LD   R2,[SLEN]
        ST   [SDIG],R2
        CLR  R2
        ST   [SLEN],R2
        CALL snum
        POPW Y
        POPW X
        RET

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
; ON ERROR GOTO n arms a handler; ON e GOTO n1,n2 is the computed jump.
; **One token apart, and the test costs nothing** because `ON` has to
; SKIPSP before its expression anyway -- `ERROR` is a keyword, so this
; is a compare against a byte rather than a name match.
;
; `ON ERROR GOTO 0` disarms, which is what MS BASIC means by it and
; needs no code: zero is the "no handler" value, and nothing looks the
; line up until a fault actually fires.
h_on:   SKIPSP
        CMP  R2,#K_ERROR
        BNE  .comp
        INCW Y                  ; over ERROR
        SKIPSP
        INCW Y                  ; ...and over the GOTO
        CALL eval
        ST   [EHAND],R0
        MOV  R0,R1
        ST   [EHAND+1],R0
        JMP  stmt
.comp:  CALL eval
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
h_clg:  MOV  R3,#1
        CALL gargs
        LD   R0,[VID_CTRL]         ; bpp out of VID_CTRL
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
        ST   [VRAM_STEP],R0
        LD   R0,[VID_BASE_L]
        ST   [VRAM_ADDR_L],R0
        LD   R0,[VID_BASE_H]
        ST   [VRAM_ADDR_H],R0
        MOV  R3,#240
.row:   LD   R1,[VID_STRIDE_L]         ; stride low; 0 means 256, and the
.col:   ST   [VRAM_DATA],R2          ;   store-first loop makes that true
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
        ST   [SND_IDX],R0
        LD   R0,[garg+2]
        ST   [SND_DATA],R0
        LD   R0,[garg+3]
        ST   [SND_DATA],R0
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
        ST   [VRAM_STEP],R2
        ST   [VRAM_ADDR_L],R0
        ST   [VRAM_ADDR_H],R1
        CLR  R3                 ; the row
.grow:  LD   R2,[VRAM_DATA]          ; its eight bits, MSB leftmost
        LD   R0,[garg]
        ST   [PIX_X_L],R0
        LD   R0,[garg+1]
        ST   [PIX_X_H],R0
        LD   R0,[garg+2]
        ADD  R0,R3
        ST   [PIX_Y_L],R0
        LD   R0,[garg+3]
        ADC  R0,#0
        ST   [PIX_Y_H],R0
        PUSH R3
        MOV  R3,#8
.gbit:  CLR  R0
        ADD  R2,R2              ; the top bit into C
        BCC  .g0
        LD   R0,[garg+4]
.g0:    ST   [PIX_DATA],R0
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
; 8.8 fixed point: FMUL and FDIV are gone, INT stays.
;
; They existed because a 16-bit cell was the only number this machine
; had, and 8.8 was the fraction that fitted it. [D63] made floating
; point resident, so a real multiply and a real divide now exist with
; range and an exponent -- and ffargs, fsign, ifmul and ifdiv were 234
; bytes of a worse answer to the same question.
;
; **INT is not part of that and stays.** It is the way a float or a
; fixed-point value crosses back to an integer, which is what PLOT and
; POKE and a subscript need, and docs/13-basic.md section 8 turns on it.
; ---------------------------------------------------------------------

; retnum -- R0:R1 as a number: the tail every value-returning builtin
; returns through, and `fretf` in sw/fpbas.asm is its float twin. It sat
; inside the fixed-point block and is nothing to do with it.
retnum: PUSH R0
        CLR  R0
        ST   [STYPE],R0
        POP  R0
        RET

; INT(a) -- a float to the integer at or below it, and **the last of the
; 8.8 fixed point to go**.
;
; It used to be an arithmetic shift right by eight, because 8.8 was the
; only fraction a 16-bit cell could hold and dropping the point meant
; dropping a byte. [D63] made real floats resident, so 8.8 is over and
; that shift is simply wrong now: `INT(7)` must be 7, not 0.
;
; It still **floors**, which is BBC BASIC's INT and the right rounding
; for motion -- every value gets a cell of equal width, so a constant
; velocity gives constant pixel steps, where truncation towards zero
; would give the origin a double-width cell and stall an object crossing
; it. `ftoi` in sw/fp.asm does that and says why at length.
;
; An integer argument comes back unchanged; there is nothing to drop.
iint:   CALL earg               ; ( expression )
        LD   R2,[STYPE]
        CMP  R2,#2
        BNE  .already
        CALL ftoi
.already:
        JMP  retnum