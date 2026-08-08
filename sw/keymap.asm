; ---------------------------------------------------------------------
; The keyboard's tables, split from sw/kbd.asm because the two do not
; fit in the same place.
;
; In the boot ROM the code lives down in $F000-$FDFF with the rest of
; the monitor and these live up at $FF00, in the 248 bytes below the
; vectors that were otherwise empty -- autoboot and the W command had
; already pushed the image past $FDFF once, and moving tables up is what
; was done about it then. sw/basic.bas has no such split and includes
; both together.
;
; Included exactly once per build, like kbd.asm.
; ---------------------------------------------------------------------

; Set 2 scancode to unshifted character, 0 for a key with none.

keymap:
        .byte 0,0,0,0,0,0,0,0                   ; $00
        .byte 0,0,0,0,0,$09,'`',0               ; $08  $0D tab
        .byte 0,0,0,0,0,'q','1',0               ; $10
        .byte 0,0,'z','s','a','w','2',0         ; $18
        .byte 0,'c','x','d','e','4','3',0       ; $20
        .byte 0,' ','v','f','t','r','5',0       ; $28
        .byte 0,'n','b','h','g','y','6',0       ; $30
        .byte 0,0,'m','j','u','7','8',0         ; $38
        .byte 0,',','k','i','o','0','9',0       ; $40
        .byte 0,'.','/','l',';','p','-',0       ; $48
        .byte 0,0,$27,0,'[','=',0,0             ; $50  $27 apostrophe
        .byte 0,0,$0D,']',0,$5C,0,0             ; $58  $5C backslash
        .byte 0,0,0,0,0,0,$08,0                 ; $60  $66 backspace
        .byte 0,'1',0,'4','7',0,0,0             ; $68
        .byte '0','.','2','5','6','8',$1B,0     ; $70  $76 escape
        .byte 0,'+','3','-','*','9',0,0         ; $78

; The keys shift does something to that is not a case change.

shiftmap:
        .byte '`','~'
        .byte '1','!'
        .byte '2','@'
        .byte '3','#'
        .byte '4','$'
        .byte '5','%'
        .byte '6','^'
        .byte '7','&'
        .byte '8','*'
        .byte '9','('
        .byte '0',')'
        .byte '-','_'
        .byte '=','+'
        .byte '[','{'
        .byte ']','}'
        .byte $5C,'|'
        .byte ';',':'
        .byte $27,$22
        .byte ',','<'
        .byte '.','>'
        .byte '/','?'
        .byte 0

; The eight keys that have no character, reached only with an $E0 in
; front. `scancode` returns $80+n for these and sw/basic.bas's
; serialkey() turns that into K_UP..K_INS -- the same codes it makes out
; of the terminal's ESC [ A, so nothing above the decoder can tell which
; wire a key arrived on. The order here is the order of those constants.
;
; Every one of these scancodes is also a keypad key. The prefix is the
; only thing telling them apart, which is why this table is reached from
; the kext branch and not from keymap.

extmap:
        .byte $75,$80           ; K_UP
        .byte $72,$81           ; K_DOWN
        .byte $6B,$82           ; K_LEFT
        .byte $74,$83           ; K_RIGHT
        .byte $6C,$84           ; K_HOME
        .byte $69,$85           ; K_END
        .byte $71,$86           ; K_DEL
        .byte $70,$87           ; K_INS

; Ctrl+Pause, which a PS/2 keyboard sends as $E0 $7E, is the Break key
; and comes out as $03 -- the very byte the serial console's Ctrl-C
; already produces. So there is one break path rather than two: the
; interrupt handler's existing test catches both and nothing else in the
; machine has to know which keyboard stopped the program. Escape stays
; an ordinary character, which a game's menu wants it to be.

        .byte $7E,$03           ; Break
        .byte 0
