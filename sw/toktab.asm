; ---------------------------------------------------------------------
; toktab.asm -- the keyword table, and the one copy of it.
;
; Length, then the word. **The order fixes the token byte**: the first
; entry is $80 and programs already saved to disk hold the old numbering,
; so entries are appended and never inserted or reordered.
;
; These read this and must read the same bytes:
;
;   sw/basic.bas   tokenise() turns a word into a byte, list() turns it
;                  back
;   sw/interp.asm  sttab dispatches $80+n, one .word per entry here, in
;                  this order -- the two tables are one table in two
;                  files and NTOK is their shared length
;   sim/test_lex.py, sim/test_interp.py
;
; **$A4 is K_NUM**, the marker for a numeric literal with two binary
; bytes after it, so no keyword may have that value. It is held open by
; the one-character `"?"` entry below rather than by stopping the table:
; an earlier header said a 37th keyword would collide and that growth
; past here needed a second table. It did not -- the slot is reserved
; and the table simply continues. There are 70 keywords now, $80-$C5.
;
; sw/asm.asm was the third reader until [D63] deleted the on-machine
; assembler; nothing tokenises the inside of an ASM block any more.
; ---------------------------------------------------------------------
TOKTAB:
        .byte 5, "P","R","I","N","T"
        .byte 3, "S","U","B"
        ; $82 was FUNCTION, which parsed as SUB and could not return
        ; a value, so it was a longer word for a thing we already had.
        ; Retired the way $A4 and $C6 are: a one-character entry nobody
        ; can spell holds the byte open, so nothing after it renumbers
        ; and a saved program still means what it said.
        .byte 1, "!"
        .byte 3, "D","I","M"
        .byte 3, "R","U","N"    ; $84 was CONST (removed: an
                                ;   interpreter folds nothing). RUN
                                ;   moved up from the tail so nothing
                                ;   else renumbers.
        .byte 3, "F","O","R"
        .byte 4, "N","E","X","T"
        .byte 2, "T","O"
        .byte 2, "D","O"
        .byte 4, "L","O","O","P"
        .byte 5, "W","H","I","L","E"
        .byte 5, "U","N","T","I","L"
        .byte 4, "E","X","I","T"
        .byte 2, "I","F"
        .byte 4, "T","H","E","N"
        .byte 4, "E","L","S","E"
        .byte 6, "E","L","S","E","I","F"
        .byte 3, "E","N","D"
        .byte 6, "R","E","T","U","R","N"
        .byte 4, "C","A","L","L"
        .byte 2, "A","S"
        .byte 3, "I","N","T"
        .byte 4, "B","Y","T","E"
        .byte 4, "P","E","E","K"
        .byte 4, "P","O","K","E"
        .byte 3, "A","N","D"
        .byte 2, "O","R"
        .byte 3, "X","O","R"
; ---- the rest of the language, so the compiler sees keywords as
; ---- keywords. Appended, because the order fixes the token byte and
; ---- programs already saved to disk hold the old ones.
        .byte 4, "C","A","R","D"
        .byte 2, "A","T"
; ---- $9E was ASM. The on-machine assembler is gone ([D63]) and this
; ---- slot is SYS, which is what replaced it: three letters for three,
; ---- so every token after it keeps its number and saved programs are
; ---- undisturbed except for the one keyword that no longer did
; ---- anything anyway.
        .byte 3, "S","Y","S"
        .byte 6, "E","X","T","E","R","N"
        .byte 7, "I","N","C","L","U","D","E"
        .byte 6, "I","N","L","I","N","E"
        .byte 4, "G","O","T","O"
        .byte 4, "W","E","N","D"
; ---- $A4 is T_LIT, the stored literal's marker -- a token with no
; ---- keyword. The slot below exists only to keep every later entry's
; ---- position honest, and it can never be typed: '?' is punctuation,
; ---- and only identifiers are looked up here. Leaving it out shifted
; ---- MODE onto T_LIT itself, and the first `MODE 4` ever typed was
; ---- stored as half a number.
        .byte 1, "?"
; ---- graphics and sound, appended in one block: $A5-$AE. RND, TIMER
; ---- and VPEEK are btab functions, not keywords -- they match as
; ---- identifiers the way LEN and INKEY do, so they cost no tokens.
        .byte 4, "M","O","D","E"
        .byte 5, "V","S","Y","N","C"
        .byte 6, "S","C","R","O","L","L"
        .byte 7, "P","A","L","E","T","T","E"
        .byte 6, "S","P","R","I","T","E"
        .byte 5, "V","P","O","K","E"
        .byte 5, "S","O","U","N","D"
        .byte 5, "H","L","I","N","E"
        .byte 4, "P","L","O","T"
        .byte 4, "L","I","N","E"
; ---- the language round-out: $AF-$B8
        .byte 5, "I","N","P","U","T"
        .byte 4, "D","A","T","A"
        .byte 4, "R","E","A","D"
        .byte 7, "R","E","S","T","O","R","E"
        .byte 4, "S","T","E","P"
        .byte 2, "O","N"
        .byte 4, "T","I","L","E"
        .byte 3, "C","L","G"
        .byte 5, "P","I","T","C","H"
        .byte 5, "G","T","E","X","T"
; ---- the editor's former commands, now ordinary statements: $B9-$C5.
; ---- One vocabulary, as the C64 and the BBC always had it -- a
; ---- program can SAVE itself and LOAD its sequel.
        .byte 4, "L","I","S","T"
        .byte 3, "N","E","W"
        .byte 4, "F","R","E","E"
        .byte 5, "R","E","N","U","M"
        .byte 6, "D","E","L","E","T","E"
        .byte 3, "C","L","S"
        .byte 4, "S","A","V","E"
        .byte 4, "L","O","A","D"
        .byte 3, "D","I","R"
        .byte 3, "E","R","A"
        .byte 7, "C","O","M","P","A","C","T"
        .byte 5, "D","R","I","V","E"
; ---- $C6: the comment. A keyword like any other, so the interpreter
; ---- skips a whole line on one dispatch instead of matching three
; ---- characters at run time -- and LIST gives "REM" back because the
; ---- text after it is stored verbatim. `'` needs no entry: it is
; ---- punctuation, stored as itself, and stmt sends it the same way.
        .byte 3, "R","E","M"
; ---- $C7: the float literal's marker, and not a word anybody types.
;
; The same trick `?` plays at $A4 for the integer marker: a
; one-character entry nobody can spell holds the byte open, so the
; numbering stays the table's own order and no second table is needed.
; `!` cannot be typed as a keyword because a lone `!` is punctuation and
; tokenise stores it as itself -- it only ever reaches a program as
; three packed bytes written by `tok_line` ([D68]).
        .byte 1, "!"
        ; $C7 CLEAR -- variables away, program kept. BBC's name, which
        ; is why it is not CLR: CLS and CLG are BBC's too and the three
        ; belong together.
        .byte 5, "C","L","E","A","R"
        ; $C8 LOCAL -- the same save stack parameters use, without the
        ; assignment. BBC's name and BBC's mechanism.
        .byte 5, "L","O","C","A","L"
        .byte 0
