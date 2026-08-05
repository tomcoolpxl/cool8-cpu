; ---------------------------------------------------------------------
; boot.asm -- the COOL8 boot ROM.
;
; Lives in EBR at $F000-$FFFF, which is bitstream-initialisable; SPRAM is
; not, so all 64 KB of main memory is garbage at power-on and this is
; what makes the machine into something that can be reasoned about. See
; docs/04-system.md section 3 for the sequence this implements.
;
; **Deliberately minimal.** Steps 3, 5 and 6 of that sequence -- bring up
; video, copy a monitor down, drop the overlay and jump to it -- need
; hardware and software that do not exist until M5 and M6. What is here
; is only what the overlay itself needs in order to be provably working:
; a reset vector fetched from ROM, RAM cleared, vectors installed in RAM
; through the overlay, and a stop. The ROM contents are software and grow
; with the monitor; the overlay is the part that is hard to retrofit.
;
; $FE00-$FEFF is the I/O page and always wins the decode, so it is a hole
; in this image at ROM offset $0E00-$0EFF. tools/mkrom.py refuses to
; build an image with anything in it.
; ---------------------------------------------------------------------

        .org  $F000

; ---------------------------------------------------------------------
; Reset entry. ROMEN comes up 1 -- unless the loader set BOOTRAM, in
; which case none of this runs and the CPU starts in RAM instead.
; ---------------------------------------------------------------------

reset:  LDW  X,#stack
        MOVW SP,X

; Clear $0000-$EFFF. Nothing above that: $F000-$FDFF and $FF00-$FFFF are
; behind the ROM overlay on reads but are ordinary RAM on writes, and
; $FE00-$FEFF is I/O. Zeroing them would be harmless for the RAM and
; wrong for the I/O page.
;
; The loop exits when Y carries into $F000, which costs a byte-compare of
; the high half rather than a 16-bit compare the ISA does not have.
;
; Unrolled sixteen ways, and worth it: the three-instruction test costs
; about as much as three stores once SPRAM's wait state is counted, so
; the rolled version spent most of its time deciding whether to go round
; again. Measured in simulation, from reset to the HALT below: rolled,
; 1,229,036 clocks, 102 ms at 12 MHz. Unrolled, 365,036 -- 30 ms, and
; 5.9 clocks a byte. 60 KB is 3840 iterations of sixteen exactly, and
; $F000 is sixteen-aligned, so the loop lands on the boundary rather
; than needing a tail.

.macro  clr16
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
        ST   [Y+],R0
.endm

        LDW  Y,#$0000
        CLR  R0
.clear: clr16
        MOV  R1,YH
        CMP  R1,#$F0
        BNE  .clear

; Install the vectors in RAM at $FFF8-$FFFF. **These writes go to RAM
; even though reads there come from the ROM** -- that asymmetry is the
; whole point of the overlay, and it is what lets the machine leave the
; ROM behind later without a chicken-and-egg problem.

        LDW  X,#vectors
        LDW  Y,#$FFF8
        MOV  R0,#8
.vec:   LD   R1,[X+]
        ST   [Y+],R1
        SUB  R0,#1
        BNE  .vec

; ---------------------------------------------------------------------
; Step 3: bring up video, and say something.
;
; The palette has to go in first. Block RAM comes up zeroed from the
; bitstream, so every entry is black and a screen brought up without it
; is a screen with nothing on it -- including the border, which is
; entry $00. Sixteen entries is all text mode indexes.
;
; PAL_IDX counts *entries*; the half within an entry is implicit and
; advances with each write of PAL_DATA, so the whole table is one loop
; and one register write to start it.
; ---------------------------------------------------------------------

        CLR  R0
        ST   [PAL_IDX],R0
        LDW  X,#palette
        MOV  R0,#32
.pal:   LD   R1,[X+]
        ST   [PAL_DATA],R1
        SUB  R0,#1
        BNE  .pal

; Mode 0 with the display enabled: 80x30 cells of 8x16, the map at
; $8000 with a stride of 256. Writing VID_MODE loads VID_CTRL, VID_BASE
; and VID_STRIDE, so this one store is the whole of the setup.
;
; The map is already blank -- the clear above ran over $8000 and glyph
; $00 has no pixels in it -- so nothing has to be filled in first.

        MOV  R0,#$80
        ST   [VID_MODE],R0

; The banner, cell by cell: character in the even byte, attribute in the
; odd one. Row 1, column 2, which is $8000 + 1*256 + 2*2.

        LDW  X,#banner
        LDW  Y,#$8104
.msg:   LD   R1,[X+]
        CMP  R1,#0
        BEQ  .cursor
        ST   [Y+],R1
        MOV  R0,#$0B            ; light cyan on black
        ST   [Y+],R0
        BRA  .msg

; A cursor on the line below it, blinking, so the screen is visibly
; *live* rather than a still picture that might have been left there by
; the last bitstream.

.cursor:
        MOV  R0,#2
        ST   [CUR_X],R0
        MOV  R0,#3
        ST   [CUR_Y],R0
        MOV  R0,#$0F            ; rows 0..15 of the cell
        ST   [CUR_LINES],R0
        MOV  R0,#$01            ; enabled, block, slowest blink
        ST   [CUR_CTRL],R0

; Blue on the board LED: the ROM ran, RAM is clear, vectors are in, and
; there is a picture. The one thing this machine could say out loud
; before it had a screen.

        MOV  R0,#$01
        ST   [LED],R0

; Stop. There is no monitor to jump to yet. A halted CPU still grants the
; bus, so the loader can take memory and start a program from here --
; which at M4 is exactly how software arrives.

        HALT
        JMP  reset              ; if anything ever wakes it, start over

; ---------------------------------------------------------------------
; The vector table copied into RAM, and the ROM's own copy at the top.
; NMI, IRQ and BRK all land on a return: nothing here installs a handler,
; and a stray interrupt should not take the machine down.
; ---------------------------------------------------------------------

trap:   RETI

vectors:
        .word reset             ; RESET
        .word trap              ; NMI
        .word trap              ; IRQ
        .word trap              ; BRK

; The sixteen CGA colours, as the 12-bit VGA PMOD wants them: the first
; byte of a pair is 0000RRRR and the second GGGGBBBB.

palette:
        .byte $00,$00           ; 0 black
        .byte $00,$0A           ; 1 blue
        .byte $00,$A0           ; 2 green
        .byte $00,$AA           ; 3 cyan
        .byte $0A,$00           ; 4 red
        .byte $0A,$0A           ; 5 magenta
        .byte $0A,$50           ; 6 brown
        .byte $0A,$AA           ; 7 light grey
        .byte $05,$55           ; 8 dark grey
        .byte $05,$5F           ; 9 light blue
        .byte $05,$F5           ; A light green
        .byte $05,$FF           ; B light cyan
        .byte $0F,$55           ; C light red
        .byte $0F,$5F           ; D light magenta
        .byte $0F,$F5           ; E yellow
        .byte $0F,$FF           ; F white

banner: .ascii "COOL8"
        .byte 0

LED     = $FE03
VID_MODE  = $FE10
PAL_IDX   = $FE1E
PAL_DATA  = $FE1F
CUR_X     = $FE22
CUR_Y     = $FE23
CUR_CTRL  = $FE24
CUR_LINES = $FE25
stack   = $0200

; The ROM's own vectors. Only RESET is ever fetched from here in
; practice -- the code above copies all four into RAM, and after the
; overlay goes away those are the ones that count.

        .org  $FFF8
        .word reset
        .word trap
        .word trap
        .word trap
