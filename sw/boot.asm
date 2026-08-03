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

; Blue on the board LED: the ROM ran, RAM is clear, vectors are in.
; The one thing this machine can say out loud at M4.

        MOV  R0,#$01
        ST   [LED],R0

; Stop. There is no monitor to jump to yet. A halted CPU still grants the
; bus, so the loader can take memory and start a program from here --
; which at M4 is exactly how software arrives.

        HALT
        BRA  reset              ; if anything ever wakes it, start over

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

LED     = $FE03
stack   = $0200

; The ROM's own vectors. Only RESET is ever fetched from here in
; practice -- the code above copies all four into RAM, and after the
; overlay goes away those are the ones that count.

        .org  $FFF8
        .word reset
        .word trap
        .word trap
        .word trap
