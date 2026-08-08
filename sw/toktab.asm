; ---------------------------------------------------------------------
; toktab.asm -- the keyword table, and the one copy of it.
;
; Length, then the word. **The order fixes the token byte**: the first
; entry is $80 and programs already saved to disk hold the old numbering,
; so entries are appended and never inserted or reordered.
;
; Three things read this and they must read the same bytes:
;
;   sw/basic.bas   tokenise() turns a word into a byte, list() turns it
;                  back
;   sw/asm.asm     agetc turns it back again, because the editor
;                  tokenises the inside of an ASM block too
;   sim/test_lex.py, sim/test_interp.py, sim/test_asm.py
;
; $A4 is the next value and is taken: it is T_NUM, a numeric literal
; followed by two binary bytes. A 37th keyword would collide with it, so
; growing the language past here needs a second table rather than one
; more line.
; ---------------------------------------------------------------------
TOKTAB:
        .byte 5, "P","R","I","N","T"
        .byte 3, "S","U","B"
        .byte 8, "F","U","N","C","T","I","O","N"
        .byte 3, "D","I","M"
        .byte 5, "C","O","N","S","T"
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
        .byte 3, "A","S","M"
        .byte 6, "E","X","T","E","R","N"
        .byte 7, "I","N","C","L","U","D","E"
        .byte 6, "I","N","L","I","N","E"
        .byte 4, "G","O","T","O"
        .byte 4, "W","E","N","D"
        .byte 0
