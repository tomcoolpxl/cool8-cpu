; ---------------------------------------------------------------------
; monitor.asm -- the COOL8 monitor.
;
; Included by boot.asm and assembled into the same ROM image. Reached at
; the end of the boot sequence and never left: this is what the machine
; is when nothing else is running.
;
; **It runs in place, out of the ROM window.** docs/04-system.md section
; 3 used to say the boot code copies a monitor down into RAM and drops
; the overlay; it does not, and the reasons are in D36. A monitor in RAM
; is a monitor a loaded program can overwrite, which is precisely when
; you want it; leaving ROMEN set costs 4 KB of an address space with
; 60 KB free in it, and a program that wants the space can clear ROMEN
; itself with one store.
;
; The only RAM it needs is a page of variables, and that lives at $EF00 --
; just below the ROM window, inside the region the boot code has already
; cleared.
;
; Commands, one letter each:
;
;   D [addr]              dump memory, eight lines of sixteen
;   E addr bb bb ...      enter bytes
;   U [addr]              unassemble sixteen instructions
;   G addr                go
;   L dest len [flashH]   copy from the SPI flash into memory
;   ?                     the list
;
; Input comes from the serial port and the PS/2 keyboard as peers, and
; output goes to the serial port and the screen together, so the machine
; is usable over a wire before the keyboard is built and after.
; ---------------------------------------------------------------------

; ------------------------------------------------------------ registers

UART_STAT = $FE70
UART_DATA = $FE71
KBD_STAT  = $FE40
KBD_DATA  = $FE41
FLS_ADDR_L = $FE88
FLS_ADDR_M = $FE89
FLS_ADDR_H = $FE8A
FLS_DATA  = $FE8B
FLS_CTRL  = $FE8C
FLS_STAT  = $FE8D
FLS_WDATA = $FE8E
FLS_WCTRL = $FE8F
VID_BASE_H = $FE13              ; the display origin, high byte

SCREEN    = $8000               ; mode 0's map, stride 256
COLS      = 80
ROWS      = 30
ATTR      = $07                 ; light grey on black

; ------------------------------------------------------------ variables
;
; $EF00 is below the ROM window and above anything a small program will
; use. The boot code cleared it, so every one of these starts at zero
; and none of them needs initialising here.

MVARS   = $EF00
linebuf = MVARS                 ; 64 bytes
linelen = MVARS+64
lineptr = MVARS+65
cx      = MVARS+66
cy      = MVARS+67
kshift  = MVARS+68
kbrk    = MVARS+69
kext    = MVARS+70
vtop    = MVARS+71              ; which map row is at the top of the screen
dumpad  = MVARS+72              ; word -- where D and U carry on from
ldest   = MVARS+74              ; word
llen    = MVARS+76              ; word
wsrc    = MVARS+78              ; word -- W: where the bytes come from
wlen    = MVARS+80              ; word
wadr    = MVARS+82              ; 3 bytes -- the flash address, 24-bit

; ---------------------------------------------------------------------
; The command loop.
; ---------------------------------------------------------------------

monitor:
        LDW  X,#mstack
        MOVW SP,X
        LDW  X,#msg_hello
        CALL puts

.loop:  MOV  R0,#'*'
        CALL putc
        CALL getline
        CLR  R0
        ST   [lineptr],R0
        CALL skipsp
        CALL peek
        TST  R0
        BEQ  .loop              ; a blank line is not an error
        CALL bump

        ; Fold to upper case, but only a letter. `BCLR R0,#$20` on its
        ; own turns '?' ($3F) into $1F, which matches nothing and makes
        ; the help command the one command that does not work.
        CMP  R0,#'a'
        BLO  .nofold
        CMP  R0,#'z'+1
        BHS  .nofold
        BCLR R0,#$20
.nofold:

        ; The table is walked rather than compared against in line,
        ; because a chain of CMP/BEQ puts every command inside one
        ; branch's reach of the dispatcher and they are not.
        LDW  X,#cmdtab
.find:  LD   R1,[X]
        TST  R1
        BEQ  .what
        INCW X
        CMP  R1,R0
        BEQ  .run
        INCW X
        INCW X
        BRA  .find

.run:   LD   R1,[X]
        INCW X
        LD   R2,[X]
        MOV  XL,R1
        MOV  XH,R2
        CALL [X]
        BRA  .loop

.what:  LDW  X,#msg_what
        CALL puts
        BRA  .loop

cmdtab: .byte 'D'
        .word cmd_d
        .byte 'E'
        .word cmd_e
        .byte 'U'
        .word cmd_u
        .byte 'G'
        .word cmd_g
        .byte 'L'
        .word cmd_l
        .byte 'W'
        .word cmd_w
        .byte '?'
        .word cmd_h
        .byte 0

; ---------------------------------------------------------------------
; D [addr] -- dump.
;
; Reading $FE00-$FEFF really does read the I/O page, and half of it has
; side effects: dumping over UART_DATA pops the receive FIFO. That is
; not a bug to fix, it is what a monitor is for, and it is the reason
; the range is worth knowing before you type it.
; ---------------------------------------------------------------------

cmd_d:  CALL skipsp
        CALL gethex
        TST  R0
        BEQ  .go
        STW  [dumpad],X
.go:    MOV  R2,#8
.line:  LDW  X,[dumpad]
        CALL puthex4
        MOV  R0,#' '
        CALL putc
        MOV  R3,#16
.hex:   LDW  X,[dumpad]
        LD   R0,[X]
        CALL puthex2
        MOV  R0,#' '
        CALL putc
        LDW  X,[dumpad]
        INCW X
        STW  [dumpad],X
        SUB  R3,#1
        BNE  .hex

        MOV  R0,#'|'
        CALL putc
        LDW  X,[dumpad]
        ADDW X,#$FFF0           ; back sixteen
        MOV  R3,#16
.txt:   LD   R0,[X]
        CMP  R0,#' '
        BLO  .dot
        CMP  R0,#$7F
        BLO  .pr
.dot:   MOV  R0,#'.'
.pr:    CALL putc
        INCW X
        SUB  R3,#1
        BNE  .txt

        CALL newline
        SUB  R2,#1
        BNE  .line
        RET

; ---------------------------------------------------------------------
; E addr bb bb ... -- enter bytes.
; ---------------------------------------------------------------------

cmd_e:  CALL skipsp
        CALL gethex
        TST  R0
        BEQ  .err
        STW  [dumpad],X
.more:  CALL skipsp
        CALL gethex
        TST  R0
        BEQ  .done
        MOV  R0,XL
        LDW  X,[dumpad]
        ST   [X],R0
        INCW X
        STW  [dumpad],X
        BRA  .more
.done:  RET
.err:   LDW  X,#msg_what
        JMP  puts

; ---------------------------------------------------------------------
; G addr -- go. There is no coming back: whatever is there owns the
; machine, and the way to get the monitor again is a reset.
; ---------------------------------------------------------------------

cmd_g:  CALL skipsp
        CALL gethex
        TST  R0
        BEQ  .err
        JMP  [X]
.err:   LDW  X,#msg_what
        JMP  puts

; ---------------------------------------------------------------------
; L dest len [flashH] -- copy from the SPI flash.
;
; `flashH` is the top sixteen bits of the flash address and defaults to
; $1000, which is offset $100000 -- a megabyte in, with the bitstream's
; 104 KB a long way below it. docs/04-system.md section 4.8, and D16 for
; why nothing here can write.
; ---------------------------------------------------------------------

cmd_l:  CALL skipsp
        CALL gethex
        TST  R0
        BEQ  .err
        STW  [ldest],X
        CALL skipsp
        CALL gethex
        TST  R0
        BEQ  .err
        STW  [llen],X
        CALL skipsp
        CALL gethex
        TST  R0
        BNE  .addr
        LDW  X,#$1000
.addr:  CLR  R0
        ST   [FLS_ADDR_L],R0
        MOV  R0,XL
        ST   [FLS_ADDR_M],R0
        MOV  R0,XH
        ST   [FLS_ADDR_H],R0
        MOV  R0,#1
        ST   [FLS_CTRL],R0

        LDW  X,[llen]
        MOV  R2,XL
        MOV  R3,XH
        LDW  Y,[ldest]
        ; A read of FLS_DATA stalls until the byte is there, so this
        ; loop needs no status poll -- it runs at whatever the SPI
        ; clock allows and nothing is dropped.
.cp:    MOV  R0,R2
        OR   R0,R3
        BEQ  .fin
        LD   R0,[FLS_DATA]
        ST   [Y],R0
        INCW Y
        SUB  R2,#1
        BCS  .cp                ; C is *no borrow*: the high byte holds
        SUB  R3,#1
        BRA  .cp
.fin:   CLR  R0
        ST   [FLS_CTRL],R0
        LDW  X,#msg_ok
        JMP  puts
.err:   LDW  X,#msg_what
        JMP  puts

; ---------------------------------------------------------------------
; ? -- the list.
; ---------------------------------------------------------------------

cmd_h:  LDW  X,#msg_help
        JMP  puts

; ---------------------------------------------------------------------
; W src len [flashH] -- program memory into the flash.
;
; The counterpart to L, and the reason a board with blank flash can be
; given its first OS without a PC. `flashH` is the top sixteen bits of
; the destination and defaults to $1000, so the default target is the
; megabyte mark -- above the hardware floor, which refuses anything
; below it in gates whatever this code asks for (D42).
;
; **The address does not advance on a program the way it does on a
; read.** The part is sent one opcode per byte, so every byte costs a
; seek as well. That is why saving is slow and why a page-program burst
; is the obvious next thing to build.
; ---------------------------------------------------------------------

cmd_w:  CALL skipsp
        CALL gethex
        TST  R0
        BNE  .w1
        JMP  .werr                      ; past a branch's reach
.w1:    STW  [wsrc],X
        CALL skipsp
        CALL gethex
        TST  R0
        BNE  .w2
        JMP  .werr
.w2:    STW  [wlen],X
        CALL skipsp
        CALL gethex
        TST  R0
        BNE  .wad
        LDW  X,#$1000
.wad:   CLR  R0
        ST   [wadr],R0
        MOV  R0,XL
        ST   [wadr+1],R0
        MOV  R0,XH
        ST   [wadr+2],R0

        MOV  R0,#$04                    ; clear any earlier refusal
        ST   [FLS_WCTRL],R0

        LDW  Y,[wsrc]
        LDW  X,[wlen]
        MOV  R2,XL
        MOV  R3,XH
.wl:    MOV  R0,R2
        OR   R0,R3
        BEQ  .wdone
        LD   R0,[wadr]                  ; the address, every single byte
        ST   [FLS_ADDR_L],R0
        LD   R0,[wadr+1]
        ST   [FLS_ADDR_M],R0
        LD   R0,[wadr+2]
        ST   [FLS_ADDR_H],R0
        LD   R0,[Y]
        ST   [FLS_WDATA],R0
        MOV  R0,#1
        ST   [FLS_WCTRL],R0
.wbusy: LD   R0,[FLS_WCTRL]
        BTST R0,#$01
        BNE  .wbusy
        INCW Y
        CALL wadvance
        SUB  R2,#1
        BCS  .wl
        SUB  R3,#1
        BRA  .wl

.wdone: LD   R0,[FLS_WCTRL]
        BTST R0,#$04                    ; refused: below the floor
        BNE  .wref
        LDW  X,#msg_ok
        JMP  puts
.wref:  LDW  X,#msg_refused
        JMP  puts
.werr:  LDW  X,#msg_what
        JMP  puts

; wadvance -- wadr = wadr + 1, 24-bit
wadvance:
        PUSH R0
        LD   R0,[wadr]
        ADD  R0,#1
        ST   [wadr],R0
        BNE  .wa9
        LD   R0,[wadr+1]
        ADD  R0,#1
        ST   [wadr+1],R0
        BNE  .wa9
        LD   R0,[wadr+2]
        ADD  R0,#1
        ST   [wadr+2],R0
.wa9:   POP  R0
        RET

; ---------------------------------------------------------------------
; U [addr] -- unassemble.
; ---------------------------------------------------------------------

cmd_u:  CALL skipsp
        CALL gethex
        TST  R0
        BEQ  .go
        STW  [dumpad],X
.go:    MOV  R3,#16
.one:   LDW  X,[dumpad]
        CALL puthex4
        MOV  R0,#' '
        CALL putc
        LDW  X,[dumpad]
        CALL disasm
        STW  [dumpad],X
        CALL newline
        SUB  R3,#1
        BNE  .one
        RET

; ---------------------------------------------------------------------
; The console.
;
; Two outputs and two inputs, and neither pair has a preferred half. The
; serial port existed first and is how a board with no keyboard and no
; monitor is used at all; the screen and the keyboard are what make this
; a computer rather than a peripheral.
; ---------------------------------------------------------------------

; putc -- R0 = character, to the wire and to the glass.
putc:   PUSHW Y
        PUSH R1
        PUSH R2
        MOV  R2,R0

.txw:   LD   R1,[UART_STAT]
        BTST R1,#$02            ; the transmitter is free
        BEQ  .txw
        ST   [UART_DATA],R2

        ; On the screen a return is a new line and a line feed is
        ; nothing, so a CRLF going down the wire is one row here.
        CMP  R2,#$0D
        BEQ  .nl
        CMP  R2,#$08
        BEQ  .bs
        CMP  R2,#' '
        BLO  .done

        CALL scraddr
        ST   [Y],R2
        INCW Y
        MOV  R1,#ATTR
        ST   [Y],R1
        LD   R1,[cx]
        ADD  R1,#1
        ST   [cx],R1
        CMP  R1,#COLS
        BLO  .done

.nl:    CLR  R1
        ST   [cx],R1
        LD   R1,[cy]
        ADD  R1,#1
        ST   [cy],R1
        CMP  R1,#ROWS
        BLO  .done
        CALL scroll
        MOV  R1,#ROWS-1
        ST   [cy],R1
        BRA  .done

.bs:    LD   R1,[cx]
        TST  R1
        BEQ  .done
        SUB  R1,#1
        ST   [cx],R1
        CALL scraddr
        CLR  R1
        ST   [Y],R1

.done:  CALL curpos
        POP  R2
        POP  R1
        POPW Y
        RET

; scraddr -- Y = the cell at (cx, cy). A stride of 256 is what makes this
; a few moves instead of a multiply.
;
; Screen row `cy` is map row `(vtop + cy) & 31`, because scrolling moves
; the window rather than the text -- see `scroll`. The mask is the whole
; of the difference and it is one instruction, which is the argument D30
; made for a power-of-two stride in the first place.
scraddr:
        PUSH R0
        PUSH R1
        LD   R0,[cy]
        LD   R1,[vtop]
        ADD  R0,R1
        AND  R0,#31
        ADD  R0,#>SCREEN
        MOV  YH,R0
        LD   R0,[cx]
        SHL  R0
        MOV  YL,R0
        POP  R1
        POP  R0
        RET

; curpos -- put the hardware cursor where the text is.
curpos: PUSH R0
        LD   R0,[cx]
        ST   [CUR_X],R0
        LD   R0,[cy]
        ST   [CUR_Y],R0
        POP  R0
        RET

; scroll -- move the window down one row, and blank the row that appears.
;
; **Nothing moves in memory.** The map is 32 rows and 30 are displayed
; (D30), and the fetch engine wraps its row pointer within `stride * 32`,
; so scrolling a terminal is: advance the display origin by one row, and
; clear the row that has just come into view at the bottom.
;
; This used to copy 29 rows of 160 bytes a byte at a time -- about 46,000
; cycles, 5.5 ms a line at 8.375 MHz, with the machine doing nothing else.
; It is now about thirty cycles. The hardware for it was built at M5 and
; had never been used.
;
; **Software has to wrap the origin itself**, and that is the part the
; documentation was missing. The hardware wraps its row pointer inside
; `base & ~(stride*32 - 1)`, so a base allowed to walk past $9FFF takes
; the whole window with it and the map appears to relocate. Keeping
; `vtop` masked to 0..31 is what keeps the base inside $8000-$9F00.
;
; VID_BASE is latched at vblank, so the move takes effect at the start of
; the next frame and the picture cannot tear.
scroll: PUSHW Y
        PUSH R0
        PUSH R1

        LD   R0,[vtop]
        ADD  R0,#1
        AND  R0,#31
        ST   [vtop],R0

        MOV  R1,R0
        ADD  R1,#>SCREEN
        ST   [VID_BASE_H],R1    ; VID_BASE_L is 0 and stays 0

        ; The row the window just uncovered is the bottom one on screen.
        ADD  R0,#ROWS-1
        AND  R0,#31
        ADD  R0,#>SCREEN
        MOV  YH,R0
        CLR  R0
        MOV  YL,R0

        MOV  R0,#COLS
.clr:   CLR  R1
        ST   [Y],R1
        INCW Y
        MOV  R1,#ATTR
        ST   [Y],R1
        INCW Y
        SUB  R0,#1
        BNE  .clr

        POP  R1
        POP  R0
        POPW Y
        RET

; newline -- CRLF on the wire, one row on the screen.
newline:
        PUSH R0
        MOV  R0,#$0D
        CALL putc
        MOV  R0,#$0A
        CALL putc
        POP  R0
        RET

; puts -- X = a NUL-terminated string.
puts:   PUSHW X
        PUSH R0
.l:     LD   R0,[X]
        TST  R0
        BEQ  .e
        INCW X
        CALL putc
        BRA  .l
.e:     POP  R0
        POPW X
        RET

; puthex1 -- the low nibble of R0.
puthex1:
        AND  R0,#$0F
        CMP  R0,#10
        BLO  .dig
        ADD  R0,#'A'-10-'0'
.dig:   ADD  R0,#'0'
        JMP  putc

; puthex2 -- R0 as two digits.
puthex2:
        PUSH R0
        SWAP R0
        CALL puthex1
        POP  R0
        JMP  puthex1

; puthex4 -- X as four digits.
puthex4:
        PUSH R0
        MOV  R0,XH
        CALL puthex2
        MOV  R0,XL
        CALL puthex2
        POP  R0
        RET

; getc -- block for a character from either input. The keyboard returns
; nothing for most scancodes -- a break code, a prefix, a shift -- and
; those go round again rather than out.
getc:   LD   R0,[UART_STAT]
        BTST R0,#$01
        BNE  .ser
        LD   R0,[KBD_STAT]
        BTST R0,#$01
        BEQ  getc
        LD   R0,[KBD_DATA]
        CALL scancode
        TST  R0
        BEQ  getc
        RET
.ser:   LD   R0,[UART_DATA]
        RET

; getline -- a line into linebuf, echoed, with backspace.
getline:
        PUSH R0
        PUSH R1
        PUSHW X
        CLR  R1
        ST   [linelen],R1
.gl:    CALL getc
        CMP  R0,#$0D
        BEQ  .end
        CMP  R0,#$0A
        BEQ  .end
        CMP  R0,#$08
        BEQ  .back
        CMP  R0,#$7F
        BEQ  .back
        CMP  R0,#' '
        BLO  .gl
        CMP  R0,#$80            ; a named key -- the monitor has no use
        BHS  .gl                ; for one, and it is not text
        LD   R1,[linelen]
        CMP  R1,#64
        BHS  .gl
        LDW  X,#linebuf
        ADDW X,R1
        ST   [X],R0
        ADD  R1,#1
        ST   [linelen],R1
        CALL putc
        BRA  .gl
.back:  LD   R1,[linelen]
        TST  R1
        BEQ  .gl
        SUB  R1,#1
        ST   [linelen],R1
        MOV  R0,#$08
        CALL putc
        BRA  .gl
.end:   CALL newline
        POPW X
        POP  R1
        POP  R0
        RET

; The keyboard. Shared with sw/basic.bas -- the editor needs the same
; decoder and cannot reach this one, because basic.bin ends at $F20A
; and 523 bytes of it sit under the ROM window. The tables are up at
; $FF00 with the rest of what would not fit down here.

        .include "kbd.asm"

; The bitmap kbd.asm maintains for whoever wants it. Nothing in the
; monitor asks which keys are held -- that is KEY(), in the interpreter
; -- so both hooks are one byte and sw/kdown.asm stays out of the ROM.

kdset:
kdclr:  RET

; ---------------------------------------------------------------------
; Parsing the command line.
; ---------------------------------------------------------------------

; peek -- R0 = the character at lineptr, 0 past the end.
peek:   PUSH R1
        PUSHW X
        LD   R0,[lineptr]
        LD   R1,[linelen]
        CMP  R0,R1
        BHS  .end
        LDW  X,#linebuf
        ADDW X,R0
        LD   R0,[X]
        BRA  .p
.end:   CLR  R0
.p:     POPW X
        POP  R1
        RET

bump:   PUSH R0
        LD   R0,[lineptr]
        ADD  R0,#1
        ST   [lineptr],R0
        POP  R0
        RET

skipsp: PUSH R0
.s:     CALL peek
        CMP  R0,#' '
        BNE  .d
        CALL bump
        BRA  .s
.d:     POP  R0
        RET

; hexval -- R0 = a character, returns its value or $FF.
hexval: CMP  R0,#'0'
        BLO  .bad
        CMP  R0,#'9'+1
        BHS  .a
        SUB  R0,#'0'
        RET
.a:     BCLR R0,#$20
        CMP  R0,#'A'
        BLO  .bad
        CMP  R0,#'F'+1
        BHS  .bad
        SUB  R0,#'A'-10
        RET
.bad:   MOV  R0,#$FF
        RET

; gethex -- up to four hex digits at lineptr into X. R0 = how many, so
; "no argument" and "the argument 0" are different answers.
gethex: PUSH R1
        PUSH R2
        PUSH R3
        CLR  R1
        CLR  R2
        CLR  R3
.g:     CALL peek
        CALL hexval
        CMP  R0,#$FF
        BEQ  .d
        SHL  R1
        ROL  R2
        SHL  R1
        ROL  R2
        SHL  R1
        ROL  R2
        SHL  R1
        ROL  R2
        OR   R1,R0
        ADD  R3,#1
        CALL bump
        BRA  .g
.d:     MOV  XL,R1
        MOV  XH,R2
        MOV  R0,R3
        POP  R3
        POP  R2
        POP  R1
        RET

; ---------------------------------------------------------------------
; Strings.
; ---------------------------------------------------------------------

msg_hello:
        .byte $0D,$0A
        .asciz "COOL8 monitor. ? for help."
msg_what:
        .byte $0D,$0A
        .asciz "?"
msg_ok: .byte $0D,$0A
        .asciz "ok"
msg_refused:
        .byte $0D,$0A
        .asciz "refused - below the floor"
msg_help:
        .byte $0D,$0A
        .ascii "D [addr]            dump"
        .byte $0D,$0A
        .ascii "E addr bb bb ...    enter"
        .byte $0D,$0A
        .ascii "U [addr]            unassemble"
        .byte $0D,$0A
        .ascii "G addr              go"
        .byte $0D,$0A
        .ascii "L dest len [flsH]   load from flash"
        .byte $0D,$0A
        .ascii "W src len [flsH]    write to flash"
        .byte $0D,$0A,0

; The US layout, indexed by Set 2 make code. Zero means the key has no
; character -- a function key, a modifier, something on the numeric pad
; nobody has asked for yet.

mstack  = $0200
