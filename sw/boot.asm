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

; Step 5: into the monitor, which is in the ROM alongside this and runs
; where it stands. It is not copied into RAM and the overlay is not
; dropped -- see D36. The monitor never returns; the way out of it is G,
; or the loader, or a reset.
;
; The cursor is left where the monitor's console will start writing,
; which is the row below the banner.

        MOV  R0,#0
        ST   [mon_cx],R0
        MOV  R0,#3
        ST   [mon_cy],R0

; Step 5a: autoboot.
;
; Look on drive 0 for a file called BOOT.BIN and, if it is there, load it
; to $0200 and run it. That is the whole of what this ROM knows about the
; filesystem -- it walks the 256 directory entries of volume 0 looking
; for one name, and takes the start page and length out of the entry it
; finds. It does not mount, allocate, or write; sw/fs.asm does all of
; that and lives in the OS, where it belongs.
;
; Volume 0's directory is at $100000 and a volume base is 64 KB aligned,
; so a file's address is `low = 0, mid = page low, high = $10 + page
; high` -- one add, and the reason 448 KB was chosen for a volume.
;
; If there is no such file the machine falls through to the monitor,
; which is what a board with blank flash does and what you want while
; developing.

; Inline, not a subroutine: a CALL would push a return address below the
; stack pointer and leave it there, and the sequence this implements
; promises the monitor a cleared RAM. Two bytes, but the promise is
; either kept or it is not.

autoboot:
        CLR  R0                         ; the directory, at $100000
        ST   [FLS_ADDR_L],R0
        ST   [FLS_ADDR_M],R0
        MOV  R0,#$10
        ST   [FLS_ADDR_H],R0
        MOV  R0,#1
        ST   [FLS_CTRL],R0

        CLR  R3                         ; entry counter
.ab1:   LDW  Y,#bootent
        MOV  R1,#16
.ab2:   LD   R0,[FLS_DATA]
        ST   [Y],R0
        INCW Y
        SUB  R1,#1
        BNE  .ab2

        LD   R0,[bootent+11]            ; status
        CMP  R0,#$FF
        BEQ  .ab8                       ; never used
        TST  R0
        BEQ  .ab8                       ; deleted
        CMP  R0,#$80
        BEQ  .ab8                       ; the volume label

        LDW  X,#bootent
        LDW  Y,#bootname
        MOV  R1,#11
.ab3:   LD   R0,[X]
        LD   R2,[Y]
        CMP  R0,R2
        BNE  .ab8
        INCW X
        INCW Y
        SUB  R1,#1
        BNE  .ab3
        BRA  .abgo

.ab8:   ADD  R3,#1
        BNE  .ab1                       ; 256 entries, and it wrapped
        CLR  R0                         ; nothing to boot
        ST   [FLS_CTRL],R0
        ; Put the scratch back. The boot sequence promises RAM is clear
        ; when the monitor starts, and sixteen bytes of directory entry
        ; left lying about would make that promise false -- quietly, and
        ; only for whoever looked.
        LDW  Y,#bootent
        MOV  R1,#16
.ab9:   ST   [Y],R0
        INCW Y
        SUB  R1,#1
        BNE  .ab9
        JMP  monitor

; Found it. Close the directory stream, re-open at the file, and pull it
; into $0200.
.abgo:  CLR  R0
        ST   [FLS_CTRL],R0
        CLR  R0
        ST   [FLS_ADDR_L],R0
        LD   R0,[bootent+12]            ; start page, low
        ST   [FLS_ADDR_M],R0
        LD   R0,[bootent+13]            ; start page, high
        ADD  R0,#$10                    ; + the volume base
        ST   [FLS_ADDR_H],R0
        MOV  R0,#1
        ST   [FLS_CTRL],R0

        LDW  Y,#$0200
        LD   R2,[bootent+14]            ; length
        LD   R3,[bootent+15]
.ab4:   MOV  R0,R2
        OR   R0,R3
        BEQ  .ab5
        LD   R0,[FLS_DATA]
        ST   [Y],R0
        INCW Y
        SUB  R2,#1
        BCS  .ab4
        SUB  R3,#1
        BRA  .ab4

.ab5:   CLR  R0
        ST   [FLS_CTRL],R0
        MOV  R0,#$07                    ; all three LEDs: booted
        ST   [LED],R0
        LDW  X,#$0200
        JMP  [X]

bootname:
        .ascii "BOOT    BIN"

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
FLS_ADDR_L = $FE88
FLS_ADDR_M = $FE89
FLS_ADDR_H = $FE8A
FLS_DATA   = $FE8B
FLS_CTRL   = $FE8C

; A directory entry, read one at a time while autoboot walks the volume.
; It sits in the monitor's variable block, above everything the monitor
; itself uses, because by the time autoboot runs the RAM is cleared and
; the monitor has not started.
bootent = $EF60
VID_MODE  = $FE10
PAL_IDX   = $FE1E
PAL_DATA  = $FE1F
CUR_X     = $FE22
CUR_Y     = $FE23
CUR_CTRL  = $FE24
CUR_LINES = $FE25
stack   = $0200

; The monitor's cursor, so the boot code can leave it below the banner
; rather than have the monitor's first line overwrite it.
mon_cx  = $EF42
mon_cy  = $EF43

; ---------------------------------------------------------------------
; The monitor, and the disassembler it uses. Same ROM image: there is
; only one, and 4 KB of EBR was already spent on it whether or not
; anything was in it.
; ---------------------------------------------------------------------

        .include "monitor.asm"
        .include "disasm.asm"

; The last 248 bytes below the vectors are ROM too, and were empty.
; Autoboot and the W command pushed the image 89 bytes past $FDFF into
; the I/O hole, which is not addressable at all -- so the shift table
; moves up here rather than something useful being cut. It has to come
; after both includes, or the disassembler would be assembled on top of
; it and run off the end of the image.

        .org  $FF00

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

; The ROM's own vectors. Only RESET is ever fetched from here in
; practice -- the code above copies all four into RAM, and after the
; overlay goes away those are the ones that count.

        .org  $FFF8
        .word reset
        .word trap
        .word trap
        .word trap
