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
;   $0014-$0022   the interpreter
;   $0023-$0026   multiply scratch
;   $0027-$0032   long names: the table, the heap floor, the scan buffer
;   $0040-$0073   VARS, A-Z, two bytes each
;   $0074-$00A1   sw/fs.asm's FSVARS, 46 bytes
;   $00A2-$00D9   FORSTK, 8 frames of 7
;   $00DA-$00FF   the assembler
;   $0100-$01FF   the CPU stack, growing down from $0200
;
; **Include this exactly once**, before interp.asm or asm.asm. Both
; assume it and neither includes it, because in the built system both
; are present and a second copy would redefine every name.
; ---------------------------------------------------------------------

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
FDEPTH  = $0021                 ; 1: FOR loops active, 0 = none
EDEPTH  = $0022                 ; 1: expression nesting, 0 at statement level

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

VARS    = $0040                 ; 52: A-Z, two bytes each

FORFR   = 7                     ; bytes per FOR frame
MAXFOR  = 8                     ; nesting levels
FORSTK  = $00A2                 ; 56: MAXFOR * FORFR, $00A2-$00D9

; ---- the assembler
ACP     = $00DA                 ; 2: where the next byte goes
ACBASE  = $00DC                 ; 2: where this block started
APASS   = $00DE                 ; 1: 0 = laying out, 1 = emitting
ACH     = $00E0                 ; 1: the character the scanner stopped on
AKSRC   = $00E1                 ; 2: TOKTAB expansion in progress
AKLEN   = $00E3                 ; 1: characters left in it
ATK     = $00E4                 ; 1: the token class
AVAL    = $00E5                 ; 2: its value, for AT_NUM
AFAM    = $00E7                 ; 1
ABASE   = $00E8                 ; 1
AOP0    = $00E9                 ; 1: first operand shape
ASUB0   = $00EA                 ; 1
AV0     = $00EB                 ; 2
AOP1    = $00ED                 ; 1: second operand shape
ASUB1   = $00EE                 ; 1
AV1     = $00EF                 ; 2
ANOPS   = $00F1                 ; 1: how many operands were given
APRE    = $00F2                 ; 1: $00 or $2F
AOPC    = $00F3                 ; 1
AEXTRA  = $00F4                 ; 1: what trails the opcode, see asm.asm
AKEY    = $00F5                 ; 3: first, second and last of a name
AVT     = $00F8                 ; 2: one operand's value, before aline
                                ;    files it as AV0 or AV1
ADW     = $00FA                 ; 1: .word rather than .byte
; $00FB-$00FF is free. It held ANAME, ANLEN and ASYMS -- the assembler's
; own copy of a name and its own symbol table -- until D45 made a label
; a BASIC variable and left the scan in NBUF/NLEN, which is what the
; name table already wanted.

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
; 13 was E_AFULL, "too many symbols". There is no symbol table to fill:
; a label is a BASIC variable, so running out of them is E_NAMES.
E_DONE  = 255
