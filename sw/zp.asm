; ---------------------------------------------------------------------
; zp.asm -- page 0, and who owns which byte of it.
;
; Page 0 is not faster than anywhere else: COOL8 has no zero-page
; addressing mode (D6), so $0040 costs exactly what $9040 costs. What
; this layout buys is that **page 1 holds the CPU stack and nothing
; else** -- sw/boot.asm:339 sets SP to $0200 and nothing moves it, so
; the stack grows down through page 1, and the filesystem's workspace
; used to sit at $0100 where a deep expression would quietly corrupt a
; mounted volume. That is the arrangement the BBC Micro used, with its
; filing system workspace in page 0 below the stack.
;
;   $0000-$0011   DO/LOOP's own stack
;   $0014-$0022   the interpreter
;   $0023-$0026   multiply scratch
;   $0027-$0032   long names: the table, the heap floor, the scan buffer
;   $0040-$0073   VARS, A-Z, two bytes each
;   $0074-$00A1   sw/fs.asm's FSVARS, 46 bytes
;   $00A2-$00A3   FDEPTH and EDEPTH
;   $00A4-$00D9   free, 54 bytes -- FORSTK's until STEP made it too big
;   $00DA-$00FE   floating point's operand stack (was the assembler)
;   $0100-$01FF   the CPU stack, growing down from $0200
;
; **This comment is not the source of truth and has been wrong.** It
; still listed FORSTK in page 0 long after it left. `tools/memmap.py`
; holds the map machine-readably, `poe check` verifies it against the
; equates below, and it also refuses two names on one byte -- which is
; the mistake page 0 invites, being full and tempting. The equates in
; this file are what the assembler reads and remain authoritative; the
; prose above is a convenience that a check now keeps honest.
;
; **Include this exactly once**, before interp.asm or asm.asm. Both
; assume it and neither includes it, because in the built system both
; are present and a second copy would redefine every name.
; ---------------------------------------------------------------------

; ---- DO/LOOP.
;
; A stack of its own, in the BBC Micro's shape: it gave FOR, REPEAT and
; GOSUB one each and said so when one filled, rather than merging them
; onto the processor stack the way BBC BASIC (86) did. The processor
; stack here is 256 bytes shared with a recursive evaluator, so the
; Micro is the one to copy.
;
; No cached innermost frame, unlike FOR. FOR pays per *iteration* and
; the cache is most of why nesting is free; a DO pays twice per loop, at
; the top and at the bottom, and the indexing is lost in the test.
DOFR    = 4                     ; where the body starts, and its record
MAXDO   = 4
DOSTK   = $0000                 ; 16: MAXDO frames of DOFR
DDEPTH  = $0010                 ; 1: loops open, 0 = none
DNEST   = $0011                 ; 1: nesting seen while skipping one
BENT    = $0012                 ; 2: the builtin table entry being tried

; ---- the interpreter
LREC    = $0014                 ; 2: the current line record
PEND    = $0016                 ; 2: progend, snapshot at RUN
ERR     = $0018                 ; 1: nonzero stops the program
TVAR    = $0019                 ; 1: a variable index, doubled

; The innermost FOR, held in fixed locations rather than at the top of
; the stack, so that nesting costs nothing per iteration.
LVAR    = $001A                 ; 1: the FOR variable, doubled
LLIM    = $001B                 ; 2: its limit
LBODY   = $001D                 ; 2: where its body starts
LLINE   = $001F                 ; 2: and which line that was
LSTEP   = $0021                 ; 2: the step, 1 unless STEP said otherwise.
                                ;    Contiguous with the four above: fpush
                                ;    block-copies the frame, so the frame
                                ;    is an address range, not a struct.
FDEPTH  = $00A2                 ; 1: FOR loops active, 0 = none. Moved
SFRAC   = $00A4                 ; 1: VAL's fraction digits, $FF until a
                                ;    '.' is met. Doubles as the flag and
                                ;    the count, which is why $FF rather
                                ;    than a second byte for "seen one"
EDEPTH  = $00A3                 ; 1: expression nesting -- STEP took their
                                ;    old $21-$22, and $12-$13 is BENT's,
                                ;    which the first draft of this move
                                ;    sat on. They live in FORSTK's old
                                ;    ground; $00A4-$00D9 stays free.

MTMP    = $0023                 ; 4: multiply scratch

; ---- long names.
;
; A-Z stay resident and stay the fast path; anything longer lives in a
; linearly-searched table of fixed 10-byte entries, so a slot number
; times NENT is its address and no walk is needed to index one. Six
; significant characters rather than five, because the assembler's
; labels are now BASIC variables ([D45](docs/01-decisions.md)) and
; `.done1`/`.done2` have to stay apart.
NSIG    = 6                     ; significant characters
NENT    = 12                    ; type, length, NSIG name bytes, value, aux
MAXNAME = 32

; A string variable's four bytes are BBC BASIC's descriptor exactly:
; where the characters are, how many there are, and how many were
; allocated. The last is what lets an assignment that fits reuse the
; space instead of abandoning it -- the entry's `value` is the address
; and `aux` is the two lengths.

NTAB    = $0027                 ; 2: the table's base, fixed at RUN
NNAME   = $0029                 ; 1: how many names are defined
HEAP    = $002A                 ; 2: the heap floor; arrays grow down
NBUF    = $002C                 ; 6: the identifier just scanned, folded
NLEN    = $0032                 ; 1: how long it really was

; ---- strings.
;
; Every string expression is built in one accumulator and only an
; assignment copies out of it, which is BBC BASIC's STRACC and the
; reason concatenation needs no code at all: the second operand simply
; appends where the first stopped, and no intermediate ever reaches the
; heap.
SMAX    = 255                   ; as much as one byte of length allows
SACC    = $0033                 ; 2: where the accumulator lives
SLEN    = $0035                 ; 1: how much of it is in use
STYPE   = $0036                 ; 1: 1 when the last value was a string

; ---- division. One restoring pass gives the quotient and the
; remainder both, so MOD costs a dispatch entry and nothing else.
DVSR    = $0037                 ; 2: the divisor, out of the way of the
                                ;    four registers the loop needs
DREM    = $0039                 ; 2: what was left over
DSGN    = $003B                 ; 1: bit 0 negates the quotient, bit 1
                                ;    the remainder

; ---- CALL/RETURN. A stack of its own again, and out in the user area
; because page 0 has no room left for eight frames -- which costs
; nothing, since there is no zero-page addressing mode to lose (D6).
CALLFR  = 4                     ; where to resume, and in which record
MAXCALL = 8
CSTK    = $003C                 ; 2: where that stack lives
CDEPTH  = $003E                 ; 1: calls active, 0 = none
SDIG    = $003F                 ; 1: digits STR$ has stacked, or
                                ;    characters VAL has left

VARS    = $0040                 ; 52: A-Z, two bytes each

FORFR   = 9                     ; bytes per FOR frame, STEP included
MAXFOR  = 8                     ; nesting levels, as it always was
; FORSTK left page 0 when STEP made the frame nine bytes: eight frames
; is 72 and the page had 56. It lives with the interpreter's other
; absolutes in sw/interp.asm now, and **$00A2-$00D9 is free** -- the
; first 56 bytes page 0 has ever gained back.

; ---- floating point's operand stack, in what the assembler left
;
; **$00DA-$00FF was the on-machine assembler's**, all 38 bytes of it,
; until [D63] took the assembler out of the image. This is what the
; space went to.
;
; `erel` pushes the left operand here before evaluating the right, so
; one frame is one pending operator and the depth is the expression's.
; Five bytes a frame: a type and four of value, the same size whether
; the value is a two-byte integer or a four-byte unpacked float, so the
; pop does not have to branch before it knows which.
;
; **Seven frames because thirty-eight bytes is what there was.** It sat
; at four in the image while the binding was being written, which was a
; size compromise and is paid off here: this is RAM the image no longer
; carries, and deeper besides. `fsav` refuses past the top with
; ?FORMULA TOO COMPLEX rather than writing off the end -- the same error
; `edin` gives, and for the same reason.
FSDEEP  = 7                     ; frames
FSTK    = $00DA                 ; 35: FSDEEP frames of five
FSP     = $00FD                 ; 1: the next free byte, an offset
FLTY    = $00FE                 ; 1: the left's type, across fpair
; $00FF is free.

; ---- error codes. The interpreter's caller reads ERR; 255 is a clean
; ---- stop and everything else is a fault.
E_SYN   = 1                     ; ?SYNTAX ERROR
E_FORS  = 2                     ; ?TOO MANY FORS ERROR
E_NEXT  = 3                     ; ?NEXT WITHOUT FOR ERROR
E_DEEP  = 4                     ; ?FORMULA TOO COMPLEX ERROR
E_MEM   = 5                     ; ?OUT OF MEMORY ERROR
E_NAMES = 6                     ; ?TOO MANY VARIABLES ERROR
E_SUBS  = 7                     ; ?SUBSCRIPT ERROR
E_STR   = 8                     ; ?STRING TOO LONG ERROR
E_TYPE  = 9                     ; ?TYPE MISMATCH ERROR
E_ASYN  = 10                    ; ?SYNTAX ERROR, in an ASM line
E_AENC  = 11                    ; no encoding for that operand shape
E_ASYM  = 12                    ; undefined symbol
E_ARNG  = 14                    ; branch out of range
E_DIV0  = 15                    ; ?DIVISION BY ZERO ERROR
E_DOS   = 16                    ; ?TOO MANY DOS / ?LOOP WITHOUT DO
E_CALL  = 17                    ; ?NO SUCH SUB / ?RETURN WITHOUT CALL
E_STOP  = 18                    ; ?BREAK -- the user stopped it
E_DATA  = 19                    ; ?OUT OF DATA -- READ past the last DATA
; 13 was E_AFULL, "too many symbols". There is no symbol table to fill:
; a label is a BASIC variable, so running out of them is E_NAMES.
E_DONE  = 255
