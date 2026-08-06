; ---------------------------------------------------------------------
; demo.asm -- sprites and sound, driven by the machine itself.
;
; Written to be looked at and listened to rather than measured: it is
; what tools/cool8run.py shows when there is nothing else to run, and it
; is the smallest complete example of driving the two blocks an
; operating system will have to drive.
;
;   - a tile background, because a bitmap would be a memset and would
;     teach nothing about the mode
;   - eight 16x16 sprites bouncing, which is the per-scanline limit and
;     therefore the interesting number
;   - a four-note arpeggio on two voices, stepped from the frame loop
;
; Envelopes are software here, as D41 said they would be: the volume is
; walked down every frame, which is twelve instructions and gives a
; decay no hardware ADSR would have offered.
;
;   python tools/cool8asm.py sw/demo.asm -o build/demo.bin
;   python tools/cool8run.py --load build/demo.bin --at 0x0200
; ---------------------------------------------------------------------

        .org  $0200

        .equ  VID_MODE,   $FE10
        .equ  VID_BASE_L, $FE12
        .equ  VID_BASE_H, $FE13
        .equ  VID_PAT_L,  $FE20
        .equ  VID_PAT_H,  $FE21
        .equ  VID_RASTER, $FE1B
        .equ  VID_IRQ,    $FE1D
        .equ  PAL_IDX,    $FE1E
        .equ  PAL_DATA,   $FE1F
        .equ  SPR_IDX,    $FE2A
        .equ  SPR_DATA,   $FE2B
        .equ  SPR_CTRL,   $FE2C
        .equ  VP_ADDR_L,  $FE26         ; VRAM_ADDR -- $FE30 is the
        .equ  VP_ADDR_H,  $FE27         ;   blitter's reserved space
        .equ  VP_DATA,    $FE29         ;   and reads $FF
        .equ  SND_IDX,    $FE50
        .equ  SND_DATA,   $FE51

        .equ  NSPR,       8             ; the per-scanline limit
        .equ  PATBASE,    $4000         ; tile patterns
        .equ  SPRPAT,     $6000         ; sprite patterns

; ---- state, above the program
        .equ  VARS,   $0100
        .equ  sx,     VARS+0            ; NSPR bytes: x, low
        .equ  sxh,    VARS+8            ; NSPR bytes: x, high bit
        .equ  sy,     VARS+16
        .equ  sdx,    VARS+24           ; 1 or $FF
        .equ  sdy,    VARS+32
        .equ  tick,   VARS+40
        .equ  note,   VARS+41
        .equ  vol,    VARS+42


start:  CALL  vp_clear
        CALL  make_tiles
        CALL  make_sprpat
        CALL  palette

        MOV   R0,#$82                   ; enable + mode 2, tiles
        ST    [VID_MODE],R0
        MOV   R0,#<PATBASE
        ST    [VID_PAT_L],R0
        MOV   R0,#>PATBASE
        ST    [VID_PAT_H],R0

        CALL  spr_init
        MOV   R0,#$31                   ; palette bank 3, sprites on
        ST    [SPR_CTRL],R0

        CLR   R0
        ST    [tick],R0
        ST    [note],R0
        MOV   R0,#15
        ST    [vol],R0

; ---------------------------------------------------------------------
; The frame loop. Polled rather than interrupt-driven, because a demo
; that owns the machine has nothing else to do with the time and this
; way the whole program is one page of straight-line code.
; ---------------------------------------------------------------------
loop:   CALL  wait_vbl
        CALL  move_sprites
        CALL  music
        BRA   loop


; VID_IRQ bit 1 is a latched flag, and the only thing that clears it is
; writing a one back. Acknowledge *first*, then wait for the next one --
; waiting for it to go low first is a deadlock, because nothing but this
; routine ever lowers it.
wait_vbl:
        PUSH  R0
        MOV   R0,#$02
        ST    [VID_IRQ],R0              ; clear whatever is pending
.w:     LD    R0,[VID_IRQ]
        BTST  R0,#$02
        BEQ   .w
        MOV   R0,#$02
        ST    [VID_IRQ],R0
        POP   R0
        RET


; ---------------------------------------------------------------------
; The picture.
; ---------------------------------------------------------------------

; vp_clear -- zero the first 8 KB of VRAM through the CPU's window, so
; the map and the patterns start from something known.
vp_clear:
        PUSH  R0
        PUSH  R1
        CLR   R0
        ST    [VP_ADDR_L],R0
        ST    [VP_ADDR_H],R0
        PUSH  R2
        MOV   R1,#32                    ; 32 x 256 bytes
        CLR   R0
.outer: MOV   R2,#0
.inner: ST    [VP_DATA],R0              ; the port auto-increments
        SUB   R2,#1
        BNE   .inner
        SUB   R1,#1
        BNE   .outer
        POP   R2
        POP   R1
        POP   R0
        RET


; make_tiles -- a checkerboard map over two patterns.
;
; Entry format is {attr, tile}: the low byte picks the pattern and the
; high nibble of the attribute picks the palette bank, so alternating
; the attribute alternates the colour without touching the pattern.
make_tiles:
        PUSH  R0
        PUSH  R1
        PUSH  R2
        ; ---- two 8x8 patterns at PATBASE: solid, and a diagonal
        MOV   R0,#<PATBASE
        ST    [VP_ADDR_L],R0
        MOV   R0,#>PATBASE
        ST    [VP_ADDR_H],R0
        MOV   R1,#32                    ; pattern 0: a solid mid colour
        MOV   R0,#$99
.p0:    ST    [VP_DATA],R0
        SUB   R1,#1
        BNE   .p0
        MOV   R1,#32                    ; pattern 1: a lighter one
        MOV   R0,#$CC
.p1:    ST    [VP_DATA],R0
        SUB   R1,#1
        BNE   .p1

        ; ---- the map: 32 rows of 64 entries at stride 128
        CLR   R0
        ST    [VP_ADDR_L],R0
        ST    [VP_ADDR_H],R0
        MOV   R2,#32                    ; rows
.row:   MOV   R1,#64                    ; entries
.cell:  MOV   R0,R1
        AND   R0,#1                     ; alternate the pattern
        ST    [VP_DATA],R0
        MOV   R0,R2
        AND   R0,#$03                   ; attr[3:0] is the palette bank;
        ST    [VP_DATA],R0              ;   attr[5:4] would pick patterns
        SUB   R1,#1
        BNE   .cell
        MOV   R1,#128                   ; skip the undisplayed half row
.pad:   CLR   R0
        ST    [VP_DATA],R0
        SUB   R1,#1
        BNE   .pad
        SUB   R2,#1
        BNE   .row
        POP   R2
        POP   R1
        POP   R0
        RET


; make_sprpat -- one 16x16 sprite pattern: a filled diamond.
;
; 4 bpp, so a row is eight bytes and the whole thing is 128. Built by
; comparing |x-8| + |y-8| against 8, which is two subtractions and a
; compare per pixel and needs no table.
make_sprpat:
        PUSH  R0
        PUSH  R1
        PUSH  R2
        PUSH  R3
        MOV   R0,#<SPRPAT
        ST    [VP_ADDR_L],R0
        MOV   R0,#>SPRPAT
        ST    [VP_ADDR_H],R0
        CLR   R3                        ; y
.prow:  CLR   R2                        ; x, counted in pairs
.ppair: MOV   R0,R2
        SHL   R0                        ; the left pixel of the pair
        CALL  diamond
        MOV   R1,R0
        SHL   R1
        SHL   R1
        SHL   R1
        SHL   R1                        ; the left pixel is the high nibble
        MOV   R0,R2
        SHL   R0
        ADD   R0,#1                     ; the right pixel
        CALL  diamond
        ADD   R0,R1
        ST    [VP_DATA],R0
        ADD   R2,#1
        CMP   R2,#8
        BLO   .ppair
        ADD   R3,#1
        CMP   R3,#16
        BLO   .prow
        POP   R3
        POP   R2
        POP   R1
        POP   R0
        RET

; diamond -- R0 = x, R3 = y. Returns R0 = colour, 0 for transparent.
diamond:
        PUSH  R1
        PUSH  R2
        CMP   R0,#8                     ; R2 = |x - 8|
        BHS   .xp
        MOV   R2,#8
        SUB   R2,R0
        BRA   .xd
.xp:    MOV   R2,R0
        SUB   R2,#8
.xd:    MOV   R1,R3                     ; R1 = |y - 8|
        CMP   R1,#8
        BHS   .yp
        MOV   R0,#8
        SUB   R0,R1
        MOV   R1,R0
        BRA   .yd
.yp:    SUB   R1,#8
.yd:    ADD   R2,R1
        CMP   R2,#8
        BHS   .out
        MOV   R0,#8                     ; the rim
        SUB   R0,R2                     ; ...shading inwards
        AND   R0,#$0F
        BNE   .done
        MOV   R0,#1
        BRA   .done
.out:   CLR   R0
.done:  POP   R2
        POP   R1
        RET


; palette -- sixteen entries a bank, four banks used.
palette:
        PUSH  R0
        PUSH  R1
        CLR   R0
        ST    [PAL_IDX],R0
        PUSH  R2
        MOV   R1,#0
.pl:    MOV   R0,R1                     ; red follows the pixel value
        AND   R0,#$0F
        ST    [PAL_DATA],R0
        MOV   R0,R1                     ; green follows the bank, x5 so
        SHR   R0                        ;   four banks span the range
        SHR   R0
        SHR   R0
        SHR   R0
        AND   R0,#$03
        MOV   R2,R0
        SHL   R2
        SHL   R2
        ADD   R2,R0
        SHL   R2
        SHL   R2
        SHL   R2
        SHL   R2
        MOV   R0,R1                     ; blue is red's complement, so
        AND   R0,#$0F                   ;   nothing comes out grey
        XOR   R0,#$0F
        ADD   R0,R2
        ST    [PAL_DATA],R0
        ADD   R1,#1
        BNE   .pl
        POP   R2
        POP   R1
        POP   R0
        RET


; ---------------------------------------------------------------------
; The sprites.
; ---------------------------------------------------------------------

spr_init:
        PUSH  R0
        PUSH  R1
        PUSHW X
        CLR   R1                        ; sprite index
.si:    LDW   X,#sx
        ADDW  X,R1
        MOV   R0,R1
        SHL   R0
        SHL   R0
        SHL   R0
        SHL   R0
        ADD   R0,#40                    ; x = 40 + 16*i
        ST    [X],R0
        LDW   X,#sxh
        ADDW  X,R1
        CLR   R0
        ST    [X],R0
        LDW   X,#sy
        ADDW  X,R1
        MOV   R0,R1
        SHL   R0
        SHL   R0
        SHL   R0
        ADD   R0,#100                   ; y = 100 + 8*i
        ST    [X],R0
        LDW   X,#sdx
        ADDW  X,R1
        MOV   R0,R1
        AND   R0,#1
        BEQ   .dxp
        MOV   R0,#$FF
        BRA   .dxs
.dxp:   MOV   R0,#1
.dxs:   ST    [X],R0
        LDW   X,#sdy
        ADDW  X,R1
        MOV   R0,R1
        AND   R0,#2
        BEQ   .dyp
        MOV   R0,#$FF
        BRA   .dys
.dyp:   MOV   R0,#1
.dys:   ST    [X],R0
        ADD   R1,#1
        CMP   R1,#NSPR
        BLO   .si
        POPW  X
        POP   R1
        POP   R0
        RET


; move_sprites -- step each one, bounce it off the edges, write it out.
move_sprites:
        PUSH  R0
        PUSH  R1
        PUSH  R2
        PUSHW X
        CLR   R1
.ms:    ; ---- x
        LDW   X,#sx
        ADDW  X,R1
        LD    R0,[X]
        LDW   Y,#sdx
        ADDW  Y,R1
        LD    R2,[Y]
        ADD   R0,R2
        CMP   R0,#8
        BLO   .bx
        CMP   R0,#240
        BLO   .xok
.bx:    LD    R2,[Y]                    ; reverse
        CLR   R0
        SUB   R0,R2
        ST    [Y],R0
        LD    R0,[X]                    ; and stay put this frame
.xok:   ST    [X],R0
        ; ---- y
        LDW   X,#sy
        ADDW  X,R1
        LD    R0,[X]
        LDW   Y,#sdy
        ADDW  Y,R1
        LD    R2,[Y]
        ADD   R0,R2
        CMP   R0,#8
        BLO   .by
        CMP   R0,#210
        BLO   .yok
.by:    LD    R2,[Y]
        CLR   R0
        SUB   R0,R2
        ST    [Y],R0
        LD    R0,[X]
.yok:   ST    [X],R0

        ; ---- the descriptor: eight bytes from an even index
        MOV   R0,R1
        SHL   R0
        SHL   R0
        SHL   R0
        ST    [SPR_IDX],R0
        LDW   X,#sy
        ADDW  X,R1
        LD    R0,[X]
        SHL   R0                        ; the raster is 480 lines
        ST    [SPR_DATA],R0
        MOV   R0,#$C0                   ; 16x16, enabled, y bit 8 clear
        ST    [SPR_DATA],R0
        LDW   X,#sx
        ADDW  X,R1
        LD    R0,[X]
        SHL   R0                        ; ...and 640 across
        ST    [SPR_DATA],R0
        CLR   R0
        ST    [SPR_DATA],R0
        MOV   R0,#>SPRPAT               ; pattern address 12:5
        SHL   R0
        SHL   R0
        SHL   R0
        ST    [SPR_DATA],R0
        MOV   R0,#>SPRPAT
        SHR   R0
        SHR   R0
        SHR   R0
        SHR   R0
        SHR   R0
        ST    [SPR_DATA],R0
        CLR   R0                        ; no flips, in front
        ST    [SPR_DATA],R0
        ST    [SPR_DATA],R0             ; the bank byte, ignored

        ADD   R1,#1
        CMP   R1,#NSPR
        BHS   .msend                    ; the body is past a branch's reach
        JMP   .ms
.msend: POPW  X
        POP   R2
        POP   R1
        POP   R0
        RET


; ---------------------------------------------------------------------
; The music. Two voices: an arpeggio that steps every sixteen frames,
; and a bass a quarter of its pitch.
;
; The increment is Hz / 0.4993, so the table is pitches rather than
; dividers -- which is the difference D41 argued for.
; ---------------------------------------------------------------------
music:
        PUSH  R0
        PUSH  R1
        PUSHW X

        LD    R0,[vol]                  ; the envelope, one step a frame
        TST   R0
        BEQ   .env
        SUB   R0,#1
        ST    [vol],R0
.env:
        LD    R0,[tick]
        ADD   R0,#1
        ST    [tick],R0
        AND   R0,#$0F
        BNE   .set                      ; a new note every sixteen frames

        LD    R0,[note]
        ADD   R0,#1
        AND   R0,#$03
        ST    [note],R0
        MOV   R0,#15
        ST    [vol],R0                  ; retrigger

        LD    R0,[note]
        SHL   R0                        ; two bytes an entry
        LDW   X,#notes
        ADDW  X,R0
        CLR   R0
        ST    [SND_IDX],R0              ; voice 0, increment
        LD    R0,[X]
        ST    [SND_DATA],R0
        INCW  X
        LD    R0,[X]
        ST    [SND_DATA],R0

        MOV   R0,#8                     ; voice 1, increment
        ST    [SND_IDX],R0
        LDW   X,#notes
        LD    R0,[X]
        SHR   R0                        ; ...an octave down, and then some
        ST    [SND_DATA],R0
        INCW  X
        LD    R0,[X]
        SHR   R0
        ST    [SND_DATA],R0

.set:   MOV   R0,#4                     ; voice 0, control
        ST    [SND_IDX],R0
        LD    R0,[vol]
        ST    [SND_DATA],R0
        MOV   R0,#$40                   ; enabled, square
        ST    [SND_DATA],R0

        MOV   R0,#12                    ; voice 1, control
        ST    [SND_IDX],R0
        LD    R0,[vol]
        SHR   R0
        ST    [SND_DATA],R0
        MOV   R0,#$40
        ST    [SND_DATA],R0

        POPW  X
        POP   R1
        POP   R0
        RET


; A minor seventh, as phase increments: A4, C5, E5, G5.
notes:  .word 881, 1048, 1319, 1571
