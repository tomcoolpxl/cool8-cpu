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
; **No palette here any more.** It used to seed sixteen entries
; because the block RAM came up zeroed and a screen without a palette
; is a black screen -- border included. The bitstream carries the
; default now ([D77], tools/palette.py), so the ROM comes up in colour
; without spending a byte or a cycle on it, and the table it used to
; hold is 32 bytes of ROM back.
; ---------------------------------------------------------------------

; Mode 0 with the display enabled: 80x30 cells of 8x16, the map at
; SCREEN with a stride of CSTRIDE. Writing VID_MODE loads VID_CTRL,
; VID_BASE and VID_STRIDE, so this one store is the whole of the setup.
;
; The map is already blank -- the clear above ran over it and glyph $00
; has no pixels in it -- so nothing has to be filled in first.

        MOV  R0,#$80
        ST   [VID_MODE],R0

; The banner, cell by cell: character in the even byte, attribute in the
; odd one. Row 1, column 2, which is SCREEN + 1*CSTRIDE + 2*2.
;
; **This was $8104 until [D70] moved the map**, and the ROM kept its own
; copy of the address while the display followed the preset. The banner
; was written faithfully into user RAM for a whole commit, invisibly.
; SCREEN and CSTRIDE now come from sw/sysbot.asm, which tools/memmap.py
; generates, so there is one number and the assembler does the sum.

        LDW  X,#banner
        LDW  Y,#SCREEN + CSTRIDE + 4
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
        ; CUR_LINES and the style bits are gone: the cursor inverts its
        ; whole cell now, in every mode, which is the only style the
        ; editor ever asked for and the one a C64 draws. The rate field
        ; stays: $11 is enabled at rate 2, 32 frames a phase, the same
        ; count the software cursor used and the same the console asks
        ; for. $01 is rate 0 and blinks four times as fast.
        MOV  R0,#$11            ; enabled, 32 frames a phase
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
        MOV  R0,#$02                    ; green: booted from flash. BASIC
        ST   [LED],R0                   ; turns it off once it is up, so
                                        ; the blink is the boot itself
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

banner: .ascii "COOL8"
        .byte 0

; The registers, generated by tools/ioregs.py from the Verilog that
; decodes them. The ROM used to carry twelve of the addresses here and
; the monitor nine more, overlapping but not agreeing on which ([D67]).
        .include "io.asm"

; SCREEN and CSTRIDE, generated by tools/memmap.py, for exactly the same
; reason one file along: the ROM carried its own $8000 through [D70] and
; drew a banner nobody could see.
        .include "sysbot.asm"

; A directory entry, read one at a time while autoboot walks the volume.
; It sits in the monitor's variable block, above everything the monitor
; itself uses, because by the time autoboot runs the RAM is cleared and
; the monitor has not started.
bootent = $EF60
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

; **No `.org` here any more, and that is what moving the I/O page
; bought.** The hole used to be at $FE00, splitting the ROM into
; $F000-$FDFF and a 248-byte island below the vectors -- and when
; autoboot and the W command pushed the image 89 bytes past $FDFF into
; the hole, the shift table had to be exiled to the island by hand. The
; page is at $FF00 now ([D67]), so ROM code runs contiguously from
; $F000 to $FEFF and the table simply follows the includes. Same total,
; one run instead of two, and 256 more bytes before anything has to be
; cut.
        .include "keymap.asm"

        .org  $FFF8
        .word reset
        .word trap
        .word trap
        .word trap
