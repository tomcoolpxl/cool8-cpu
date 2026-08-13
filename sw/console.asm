; ---------------------------------------------------------------------
; con.asm -- the console: the screen in all four kinds of mode, the
; cursor, and the character output every other module reaches it
; through.
;
; **This is the KERNAL layer** ([D68]): it knows about cells, pixels and
; the cursor and nothing at all about BASIC. Nothing here calls upward.
;
; ## The model: one truth, and a mirror
;
; The cell map at $8000 is the truth -- 128x32 cells of char+attribute,
; stride 256 -- and it is what the editor reads a line back out of. In
; the text modes the fetch engine reads those cells itself and there is
; nothing more to do. In the tile and bitmap modes the display looks
; somewhere else entirely, so every write is repeated -- mirrored --
; into the tile map or blitted into the framebuffer.
;
; Scrolling moves the *origin*, never the memory: the engine wraps the
; row pointer inside stride*32, so displayed row r is map row
; (CTOP + r) AND 31, and a scroll is one register write.
;
; ## Three things the compiled console did that this does not
;
; **The mirror is a vector, not a test.** `putat` asked `IF gkind = 1
; ... ELSE ...` on every character written. `con_geom` stores the mirror
; routine in `CMIR` once, and the text modes get the address of a bare
; RET, so the hot path is one indirect jump either way and never a test
; of what kind of screen this is.
;
; **A row address is a byte, not a shift.** `SCREEN + (((vtop+r) AND 31)
; << 8)` compiled to a sixteen-bit shift loop. The map is 8 KB aligned
; with a 256-byte stride, so the row *is* the high byte: add, mask,
; done.
;
; **Clearing a row does not go through the character path.** `clearrow`
; called `putat` once per column, which recomputed the address and
; re-dispatched the mirror eighty times; `cls` did that 2,560 times.
; Here the cell map is filled directly and the mirror is repainted once.
; ---------------------------------------------------------------------

; ---- state.
;
; Named claims in the system storage region ([D67]), which is why
; `tools/memmap.py --check` can see them and refuse a second owner. The
; compiled console pinned the same values with `DIM x AT $00xx`, which
; emits no symbol and no size -- so `bglyph` reached them as raw
; literals like `[$00D2]` and nothing in the tree could say what lived
; there.
CROWA   = $7DAD                 ;: 2 the address of row CCY, cached
CONT    = $7DAF                 ;: 32 per map row: is it a continuation
CMIR    = $7DCF                 ;: 2 the mirror for this mode, a vector
CFONT   = $7DD1                 ;: 2 font base for the current cell height
CBASE   = $7DD3                 ;: 2 bitmap display base, tracked
CGS8    = $7DD5                 ;: 2 bitmap stride * 8: one cell row down
CSTR    = $7DD7                 ;: 2 bitmap stride: one raster row
GFA     = $7DD9                 ;: 2 bglyph: the font row address
GVA     = $7DDB                 ;: 2 bglyph: the framebuffer cell address
CCX     = $7DDD                 ;: 1 cursor column
CCY     = $7DDE                 ;: 1 cursor row
CTOP    = $7DDF                 ;: 1 which map row is displayed row 0
CCOLS   = $7DE0                 ;: 1 visible columns: 80, 40 or 32
CROWS   = $7DE1                 ;: 1 visible rows: 30 or 24
CRPL    = $7DE2                 ;: 1 rows a full logical line spans
CKIND   = $7DE3                 ;: 1 0 text, 1 tiles, 2 bitmap
; Four bytes the hardware cursor gave back -- CPHASE and GINV here, BLB
; in sw/input.asm -- kept as named claims rather than as holes, because
; `tools/memmap.py --check` refuses a gap and closing one properly means
; shifting every claim below it. Take them for the next thing that needs
; storage in this region; repack when something does.
CSPARE  = $7DE4                 ;: 1 free: was CPHASE
GSPARE  = $7DE8                 ;: 1 free: was GINV
CFROW   = $7DE5                 ;: 1 font rows per glyph, 8 or 16
CBPC    = $7DE6                 ;: 1 bytes per cell row, which is the bpp
CLIM    = $7DE7                 ;: 1 base high byte that forces a repaint

CSCRN   = $8000                 ; the cell map
CSTRIDE = 256                   ; bytes per map row: 80 cells of char and
                                ;   attribute, the widest text this
                                ;   machine shows, and 160 is what this
                                ;   wants to be: the hardware allows it
                                ;   now, and the only thing still in the
                                ;   way is sim/test_run.py's reader --
                                ;   see the recipe in cool8_vregs.v. Named rather
                                ;   than shifted so that nothing, the
                                ;   suites included, can lose track of
                                ;   it: a harness writing `<< 8` cannot
                                ;   follow the map when it changes.
A_TEXT  = $07                   ; light grey on black
F8      = $FC00                 ; the 8x8 font, in VRAM
F16     = $F600                 ; and the 8x16 set mode 3 uses

; The I/O registers, generated by tools/ioregs.py from the Verilog that
; decodes them. Include-once, so it costs nothing that main.asm asks for
; it too and that this file can be assembled on its own for a test.
        .include "io.asm"

; ---------------------------------------------------------------------
; addx16 -- X = X + R1:R0.
;
; There is no 16-bit register add, and every address in this file is
; base + a computed 16-bit offset. `ADDW X,R0` already carries into the
; high half, so adding the high byte afterwards finishes it -- four
; instructions, and it is why nothing here builds an address by adding
; $0100 in a loop.
; ---------------------------------------------------------------------
addx16: ADDW X,R0
        MOV  R0,XH
        ADD  R0,R1
        MOV  XH,R0
        RET

; =====================================================================
; Addressing
; =====================================================================

; con_row -- X = the cell address of displayed row R0. R0, R1 lost.
;
; The whole of screen addressing, and it is short because the map is
; 8 KB aligned with a 256-byte stride: the wrapped row number IS the
; high byte of the address.
; base + row * 256: the wrapped row number IS the high byte.
;
; **The 160-byte row is one step away and it is not this routine.** The
; arithmetic for it is three adds and a byte shift -- 160 is 5 * 32 and
; 5r fits in a byte for r < 32, so the product is `q = 5r` and then
; `q << 5`, high `q >> 3` and low `(q AND 7) << 5`, no MUL and no spill
; of X. It was written, and it works; what does not yet work is
; con_scroll, where the rows a scroll exposes stop lining up with the
; rows it wrote. The hardware is ready: cool8_fetch.v has an explicit
; map origin now and neither the stride nor the alignment constrains it.
con_row:
        LD   R1,[CTOP]
        ADD  R0,R1
        AND  R0,#31
        ADD  R0,#>CSCRN
        MOV  XH,R0
        CLR  R0
        MOV  XL,R0
        RET

; con_cell -- X = the cell address of row R0, column R1. R0, R1 lost.
;
; Two bytes to a cell. A column cannot reach 128, so the doubling cannot
; carry out of a byte and `ADDW X,R1` finishes it.
con_cell:
        PUSH R2
        LD   R2,[CCY]
        CMP  R0,R2
        BEQ  .cached
        POP  R2
        PUSH R1
        CALL con_row
        POP  R1
        ADD  R1,R1
        ADDW X,R1
        RET
.cached:
        POP  R2
        LDW  X,[CROWA]
        ADD  R1,R1
        ADDW X,R1
        RET

; con_setrow -- CROWA = the address of row CCY.
;
; **The row address was recomputed for every character.** con_emit goes
; through con_put and con_cell to con_row on each one, and con_row's
; seven instructions answer a question whose inputs -- CCY and CTOP --
; change once a line. Cached here instead, and every site that moves
; either one calls this; con_cell takes the cached answer whenever the
; row asked for is the cursor's, and computes for any other, which is
; what con_get and con_fill need when they walk the screen.
;
; It also stops the row address depending on the stride being a power of
; two: at 256 the row IS the high byte, and that is the whole of [D30]'s
; argument for an 8192-byte map to show 80x30. With this, any stride
; costs the same and the map can be 5120.
;
; Every register survives, because eleven call sites in three files do
; not agree on what is live.
con_setrow:
        PUSH R0
        PUSH R1
        PUSHW X
        LD   R0,[CCY]
        CALL con_row
        STW  [CROWA],X
        POPW X
        POP  R1
        POP  R0
        RET

; =====================================================================
; Writing a cell
; =====================================================================

; conw -- write character R2, attribute R3, at row R0 column R1, with
; the cell address already in X. R0 and R1 survive for the mirror.
;
; Split from con_put because `con_emit` has the address cached and must
; not pay for con_cell again.
conw:   ST   [X],R2
        INCW X
        ST   [X],R3
        LD   R3,[CKIND]
        TST  R3
        BEQ  .done              ; text: the engine reads the cells itself
        ; The mirror covers the VISIBLE rows only. Map rows 30 and 31
        ; exist for the scroll wrap, and in mode 6 their mirrored
        ; addresses land on the font at $FC00 -- CLS ate it, once.
        LD   R3,[CROWS]
        CMP  R0,R3
        BHS  .done
        LDW  X,[CMIR]
        JMP  [X]
.done:  RET

; con_put -- character R2, attribute R3, at row R0 column R1.
;
; A column off the right is dropped, not wrapped: the map is 128 wide
; and the mode may be showing 32 of them, so wrapping would put the
; character on the next row instead of nowhere.
con_put:
        PUSH R0
        LD   R0,[CCOLS]
        CMP  R1,R0
        BHS  .drop
        POP  R0
        PUSH R0
        PUSH R1
        CALL con_cell
        POP  R1
        POP  R0
        JMP  conw
.drop:  POP  R0
        RET

; con_get -- R0 = the character at row R0, column R1.
con_get:
        CALL con_cell
        LD   R0,[X]
        RET

; =====================================================================
; The mirrors. One of these is in CMIR; each takes row R0, column R1,
; character R2.
; =====================================================================

; con_nomir -- the text modes'. The vector always exists, so the hot
; path never has to ask which kind of screen this is.
con_nomir:
        RET

; con_tmir -- mode 2: one tile-map entry, the glyph as a tile. The
; attribute's low nibble picks palette bank 0 (normal) or 2 (the
; inverse pair the cursor blinks with). The map mirrors the cell map's
; circular rows, so the row wrap is the same one con_row does.
con_tmir:
        CMP  R2,#32             ; control codes draw as blank
        BHS  .ok
        MOV  R2,#32
.ok:    PUSH R2
        LD   R2,[CTOP]          ; a = ((CTOP + r) AND 31) * 128 + c*2
        ADD  R0,R2
        AND  R0,#31
        ; **Not seven shifts of a pair.** A row is under 32, so row*128
        ; is exactly (row >> 1) in the high byte and (row & 1) << 7 in
        ; the low one -- the shift count is bigger than the field.
        MOV  R2,R0
        SHR  R2                 ; high byte
        AND  R0,#1
        BEQ  .lo
        MOV  R0,#$80
.lo:    ADD  R1,R1              ; + c + c, which cannot carry: c < 128
        ADD  R0,R1
        ADC  R2,#0
        ST   [VRAM_ADDR_L],R0
        ST   [VRAM_ADDR_H],R2
        POP  R2
        SUB  R2,#32
        ST   [VRAM_DATA],R2     ; the glyph, as a tile index
        CLR  R0                 ; palette bank 0; the cursor's inverse
        ST   [VRAM_DATA],R0     ;   pair went with the software cursor
        RET

; con_bmir -- the bitmap modes: one glyph expanded from the 1 bpp font
; to the mode's depth, into the framebuffer.
;
; `con_geom` has already chosen the font and the stride, so this is two
; address computations and a call. The row loop is `bglyph`.
con_bmir:
        CMP  R2,#32
        BHS  .ok
        MOV  R2,#32
.ok:    SUB  R2,#32
        PUSH R0                 ; the row, for the framebuffer address
        PUSH R1
        LDW  X,[CFONT]          ; font row = base + glyph * rows
        MOV  R0,R2
        CLR  R1
        SHL  R0                 ; *8 for the 8x8 set...
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        LD   R2,[CFROW]
        CMP  R2,#16
        BNE  .fa
        SHL  R0                 ; ...and once more for the 8x16 one
        ROL  R1
.fa:    CALL addx16
        STW  [GFA],X

        LDW  X,[CBASE]          ; cell = base + row*CGS8 + col*bpc
        POP  R2                 ; the column
        POP  R3                 ; the row
.rl:    TST  R3                 ; row * CGS8, one row at a time: thirty
        BEQ  .rd                ;   at worst, and only on a mode nothing
        PUSH R2                 ;   prints to in a loop
        PUSH R3
        LD   R0,[CGS8]
        LD   R1,[CGS8+1]
        CALL addx16
        POP  R3
        POP  R2
        SUB  R3,#1
        BRA  .rl
.rd:    LD   R0,[CBPC]          ; column * bytes per cell
        CLR  R1
.cl:    TST  R2
        BEQ  .cd
        PUSH R2
        PUSH R0
        CALL addx16
        POP  R0
        POP  R2
        CLR  R1
        SUB  R2,#1
        BRA  .cl
.cd:    STW  [GVA],X
        JMP  bglyph

; =====================================================================
; bglyph -- one glyph, font row by font row, into the framebuffer.
;
; GFA is the font row, GVA the framebuffer cell, GINV the complement the
; cursor draws with, CFROW the rows, CBPC the depth, CSTR the raster
; stride. Both addresses walk as it goes.
;
; Carried over from the compiled console's inline assembly, which is
; where it always was -- compiled bit-twiddling measured 400 bytes the
; ceiling did not have. The literals it used to reach page 0 with are
; names now.
; =====================================================================
bglyph: LD   R3,[CFROW]
.bg:    PUSH R3
        LDW  X,[GFA]            ; seek the font row
        MOV  R0,XL
        ST   [VRAM_ADDR_L],R0
        MOV  R0,XH
        ST   [VRAM_ADDR_H],R0
        LD   R1,[VRAM_DATA]
        LDW  X,[GVA]            ; seek the cell row
        MOV  R0,XL
        ST   [VRAM_ADDR_L],R0
        MOV  R0,XH
        ST   [VRAM_ADDR_H],R0
        LD   R0,[CBPC]
        CMP  R0,#4
        BEQ  .b4
        CMP  R0,#8
        BEQ  .b8
        ST   [VRAM_DATA],R1     ; 1 bpp: the row goes in raw
        BRA  .bnx
.b4:    MOV  R3,#4              ; 4 bpp: two bits to a byte, four times
.b4l:   CLR  R2
        ADD  R1,R1
        ADC  R2,R2
        ADD  R1,R1
        ADC  R2,R2
        LDW  X,#nibtab
        ADDW X,R2
        LD   R0,[X]
        ST   [VRAM_DATA],R0
        SUB  R3,#1
        BNE  .b4l
        BRA  .bnx
.b8:    MOV  R3,#8              ; 8 bpp: one bit to a byte -- entry 15,
.b8l:   CLR  R0                 ;   the seeded white; 255 is unseeded
        ADD  R1,R1              ;   black and the text would be invisible
        BCC  .b80
        MOV  R0,#$0F
.b80:   ST   [VRAM_DATA],R0
        SUB  R3,#1
        BNE  .b8l
.bnx:   LDW  X,[GFA]            ; the next font row is the next byte
        INCW X
        STW  [GFA],X
        LDW  X,[GVA]            ; the next cell row is one stride down
        LD   R0,[CSTR]
        ADDW X,R0
        LD   R0,[CSTR+1]
.bh:    TST  R0
        BEQ  .bs
        ADDW X,#$0100
        SUB  R0,#1
        BRA  .bh
.bs:    STW  [GVA],X
        POP  R3
        SUB  R3,#1
        BNE  .bg
        RET

; The 4 bpp expansion: two source bits become two pixels of the mode's
; brightest colour or of zero. A table, because the alternative is four
; branches per pixel pair.
nibtab: .byte $00,$0F,$F0,$FF

; =====================================================================
; Clearing
; =====================================================================

; con_fill -- row R0 filled with spaces.
;
; **Not eighty calls to con_put.** The compiled `clearrow` went through
; the character path once per column, recomputing the address and
; re-dispatching the mirror each time, and `cls` did that 2,560 times.
; The cell map is a flat run, so this walks it; the mirror is repainted
; once by the caller that needs it.
con_fill:
        PUSH R0
        CALL con_row
        LD   R3,[CCOLS]
        MOV  R2,#32
.f:     ST   [X],R2
        INCW X
        MOV  R0,#A_TEXT
        ST   [X],R0
        INCW X
        SUB  R3,#1
        BNE  .f
        POP  R0
        RET

; con_cls -- every row blank, every continuation cleared, cursor home.
;
; All 32 map rows, not just the visible ones: rows 30 and 31 are what
; the scroll wraps through, and leaving them dirty means a scroll pulls
; old text up from under the screen.
con_cls:
        CLR  R0
.r:     PUSH R0
        CALL con_fill
        POP  R0
        LDW  X,#CONT
        ADDW X,R0
        CLR  R1
        ST   [X],R1
        ADD  R0,#1
        CMP  R0,#32
        BLO  .r
        CLR  R0
        ST   [CCX],R0
        ST   [CCY],R0
        CALL con_setrow
        CALL con_paint
        JMP  con_cursor

; con_paint -- every visible cell redrawn into the mirror from the cell
; map, which is the truth. The bitmap window reset, and what a scroll
; falls back on when its tracked base would reach the font.
con_paint:
        LD   R0,[CKIND]
        TST  R0
        BEQ  .done              ; text modes mirror nothing
        CLR  R3                 ; row
.r:     LD   R0,[CROWS]
        CMP  R3,R0
        BHS  .done
        CLR  R2                 ; column
.c:     LD   R0,[CCOLS]
        CMP  R2,R0
        BHS  .rn
        MOV  R0,R3
        MOV  R1,R2
        PUSH R2
        PUSH R3
        CALL con_get
        POP  R3
        POP  R2
        MOV  R1,R2              ; con_get left the character in R0
        PUSH R1
        PUSH R2
        PUSH R3
        MOV  R2,R0
        MOV  R0,R3
        LDW  X,[CMIR]
        CALL [X]
        POP  R3
        POP  R2
        POP  R1
        ADD  R2,#1
        BRA  .c
.rn:    ADD  R3,#1
        BRA  .r
.done:  RET

; =====================================================================
; The cursor
; =====================================================================

; con_cursor -- the hardware cursor follows in the text modes; elsewhere
; the soft cursor restarts its phase and the caller blinks it.
con_cursor:
        LD   R0,[CCX]
        ST   [CUR_X],R0
        LD   R0,[CCY]
        ST   [CUR_Y],R0
        RET

; **There is no software cursor.** con_blink lived here, with GINV and
; CPHASE, drawing an inverted cell in the five modes the hardware
; cursor did not cover. The hardware covers all seven now -- the invert
; moved to `pal_index` in cool8_pixel.v, which is one XOR and works in
; every engine -- so the console writes CUR_X/CUR_Y and draws nothing.
;
; That deletes the second place that remembered where the cursor is,
; which is what made it blink in a stale spot after a mode change: two
; implementations, each right about its own state, disagreeing on the
; boundary.

; =====================================================================
; Characters out
; =====================================================================

; con_emit -- the character in R0 at the cursor, which then advances.
;
; Past the right-hand edge the line either continues on the next row --
; linked, while the logical line is still short of its limit -- or a new
; one starts. That link is what lets the editor read a wrapped line back
; as one line.
con_emit:
        PUSH R0
        LD   R0,[CCY]
        LD   R1,[CCX]
        POP  R2
        MOV  R3,#A_TEXT
        PUSH R2
        CALL con_put
        POP  R2
        LD   R0,[CCX]
        ADD  R0,#1
        LD   R1,[CCOLS]
        CMP  R0,R1
        BLO  .same
        ; The row is full. `CRPL` is how many rows a full logical line
        ; may span in this mode -- 1 at 80 columns, 2 at 40, 3 at 32 --
        ; so a line is always at most 80 characters however narrow the
        ; screen is.
        CALL con_lstart         ; R0 = the row this logical line began on
        LD   R1,[CCY]
        SUB  R1,R0
        ADD  R1,#1
        LD   R0,[CRPL]
        CMP  R1,R0
        BHS  .newl
        CLR  R0
        ST   [CCX],R0
        CALL con_down
        LD   R0,[CCY]           ; and link it to the row above
        LDW  X,#CONT
        ADDW X,R0
        MOV  R0,#1
        ST   [X],R0
        JMP  con_cursor
.newl:  JMP  con_nl
.same:  ST   [CCX],R0
        JMP  con_cursor

; con_lstart -- R0 = the first row of the logical line the cursor is on,
; walking the continuation links back up.
con_lstart:
        LD   R0,[CCY]
.u:     TST  R0
        BEQ  .done
        LDW  X,#CONT
        ADDW X,R0
        LD   R1,[X]
        TST  R1
        BEQ  .done
        SUB  R0,#1
        BRA  .u
.done:  RET

; con_down -- the cursor one row down, column kept. At the bottom the
; screen scrolls and the cursor stays: the C64's rule, and it never
; wraps to the top.
con_down:
        LD   R0,[CCY]
        ADD  R0,#1
        LD   R1,[CROWS]
        CMP  R0,R1
        BHS  .scr
        ST   [CCY],R0
        JMP  con_setrow
.scr:   JMP  con_scroll

; con_nl -- a new logical line at column 0.
;
; Any stale chain hanging below is cut, or a later Return would drag
; leftover screen text into the line it reads. (Found the classic way:
; break a printing loop, type LIST, get the listing and then ?SYNTAX.)
con_nl: CLR  R0
        ST   [CCX],R0
        CALL con_down
        LD   R0,[CCY]
        LDW  X,#CONT
        ADDW X,R0
        CLR  R1
        ST   [X],R1
.cut:   ADD  R0,#1
        LD   R1,[CROWS]
        CMP  R0,R1
        BHS  .done
        LDW  X,#CONT
        ADDW X,R0
        LD   R1,[X]
        TST  R1
        BEQ  .done
        CLR  R1
        ST   [X],R1
        BRA  .cut
.done:  JMP  con_cursor

; con_puts -- the zero-terminated string at X.
con_puts:
        LD   R0,[X]
        TST  R0
        BEQ  .done
        PUSHW X
        CALL con_emit
        POPW X
        INCW X
        BRA  con_puts
.done:  RET

; con_putsn -- R0 bytes from X, which is what a counted string wants and
; what the float formatter hands back.
con_putsn:
        TST  R0
        BEQ  .done
        PUSH R0
        LD   R0,[X]
        PUSHW X
        CALL con_emit
        POPW X
        POP  R0
        INCW X
        SUB  R0,#1
        BRA  con_putsn
.done:  RET

; =====================================================================
; Scrolling
; =====================================================================

; con_scroll -- everything up one row.
;
; The memory does not move: the link table shifts with the rows and the
; origin advances, which is one register write in the text and tile
; modes. The bitmap modes track a base instead and repaint from the cell
; map when the window would reach the font -- about one repaint in
; sixty.
con_scroll:
        CLR  R0                 ; the links move with the rows
.l:     LDW  X,#CONT
        ADDW X,R0
        MOV  R1,R0
        ADD  R1,#1
        PUSHW X
        LDW  X,#CONT
        ADDW X,R1
        LD   R1,[X]
        POPW X
        ST   [X],R1
        ADD  R0,#1
        CMP  R0,#31
        BLO  .l
        LDW  X,#CONT+31
        CLR  R1
        ST   [X],R1

        LD   R0,[CTOP]
        ADD  R0,#1
        AND  R0,#31
        ST   [CTOP],R0
        CALL con_setrow

        LD   R1,[CKIND]
        TST  R1
        BNE  .gfx
        ; Text: the display origin is the address of displayed row 0,
        ; which con_row(0) computes -- it applies CTOP itself. Written
        ; this way rather than as one store to VID_BASE_H so that the
        ; stride lives in one place; at 256 only the high byte moves and
        ; the low one is already zero.
        CLR  R0
        CALL con_row
        MOV  R0,XL
        ST   [VID_BASE_L],R0
        MOV  R0,XH
        ST   [VID_BASE_H],R0
        BRA  .last
.gfx:   CMP  R1,#1
        BNE  .bmp
        MOV  R1,R0              ; tiles: the map wraps the same 32 rows
        SHR  R1
        AND  R0,#1
        BEQ  .t0
        MOV  R0,#$80
.t0:    ST   [VID_BASE_L],R0
        ST   [VID_BASE_H],R1
        BRA  .last
.bmp:   LDW  X,[CBASE]          ; bitmap: track the base a cell row on
        LD   R0,[CGS8]
        LD   R1,[CGS8+1]
        CALL addx16
        STW  [CBASE],X
        MOV  R0,XH
        LD   R1,[CLIM]
        CMP  R0,R1
        BLO  .bset
        CLR  R0                 ; the window would reach the font: start
        CLR  R1                 ;   again at zero and redraw from truth
        MOV  XL,R0
        MOV  XH,R1
        STW  [CBASE],X
        CALL con_paint
        LDW  X,[CBASE]
.bset:  MOV  R0,XL
        ST   [VID_BASE_L],R0
        MOV  R0,XH
        ST   [VID_BASE_H],R0
.last:  LD   R0,[CROWS]         ; the row scrolled in is blank
        SUB  R0,#1
        JMP  con_fill

; =====================================================================
; Geometry
; =====================================================================

; The seven modes, six bytes each: columns, rows, kind, bytes per cell
; row, font rows, and how many screen rows a full logical line may span.
;
; **A table, not seven `IF`s.** The compiled `setgeom` tested the mode
; against every value in turn and assigned the fields one at a time,
; which is 416 bytes for what is a lookup. The last field is the reason
; a logical line is always at most 80 characters however narrow the
; screen is: 1 row at 80 columns, 2 at 40, 3 at 32.
GEOMTAB:
        .byte 80,30,0,0,0,1     ; 0  text, 80x30
        .byte 40,30,0,0,0,2     ; 1  text, 40x30
        .byte 40,30,1,0,0,2     ; 2  tiles, 40x30
        .byte 80,30,2,1,16,1    ; 3  bitmap, 1 bpp, undoubled: 8x16 cells
        .byte 40,30,2,4,8,2     ; 4  bitmap, 4 bpp
        .byte 32,24,2,4,8,3     ; 5  bitmap, 4 bpp, 32x24
        .byte 32,30,2,8,8,3     ; 6  bitmap, 8 bpp
GEOMN   = 7

; con_init -- the console from cold: origin at the top, cursor home,
; geometry read from the hardware, screen cleared.
;
; SPRAM powers up undefined, so nothing here may assume its own state.
; The boot ROM clears $0000-$EFFF and the storage region is inside that,
; but a test driver -- or a warm restart that skipped the clear -- is
; not owed the same, and CTOP being garbage puts the origin somewhere
; the screen is not.
; con_warm -- set the console up over whatever is already on the screen.
;
; **The half of con_init that does not clear.** At boot the relocating
; stub has painted its banner and BASIC is supposed to leave it there
; and put the cursor underneath -- which stopped happening the moment
; `main` actually reached `con_init`, because that ends in `con_cls`
; and the banner went with it. Separated rather than special-cased, so
; the warm restart can use it too: a console that wakes up in whatever
; mode a program left is exactly what con_geom is for.
con_warm:
        CLR  R0
        ST   [CTOP],R0
        ST   [CCX],R0
        ST   [CCY],R0
        CALL con_setrow
        JMP  con_geom

con_init:
        CALL con_warm
        JMP  con_cls

; con_geom -- read the hardware and set the console up for whatever mode
; the machine is in RIGHT NOW.
;
; Called whenever the editor regains control, because a program or a
; direct MODE leaves the mode exactly as it set it. Nothing is restored:
; mode, palette, sprites and sound all stay as the program left them and
; the console simply works wherever it wakes up.
con_geom:
        LD   R0,[VID_MODE]
        AND  R0,#15
        CMP  R0,#GEOMN
        BLO  .ok
        CLR  R0                 ; an undecoded mode reads as plain text
.ok:    MOV  R1,R0              ; entry = table + mode * 6
        ADD  R0,R0
        ADD  R0,R1
        ADD  R0,R0
        LDW  X,#GEOMTAB
        ADDW X,R0
        LD   R0,[X]
        ST   [CCOLS],R0
        INCW X
        LD   R0,[X]
        ST   [CROWS],R0
        INCW X
        LD   R0,[X]
        ST   [CKIND],R0
        INCW X
        LD   R0,[X]
        ST   [CBPC],R0
        INCW X
        LD   R0,[X]
        ST   [CFROW],R0
        INCW X
        LD   R0,[X]
        ST   [CRPL],R0

        ; The mirror, once, so no character written afterwards has to
        ; ask what kind of screen this is.
        LD   R0,[CKIND]
        LDW  X,#con_nomir
        TST  R0
        BEQ  .mset
        CMP  R0,#1
        BNE  .bm
        LDW  X,#con_tmir
        BRA  .mset
.bm:    LDW  X,#con_bmir
.mset:  STW  [CMIR],X

        ; The cursor, on, in every mode -- there is one now, in
        ; silicon, and it inverts its cell wherever CUR_X/CUR_Y point.
        ; This used to enable it for text and disable it for everything
        ; else, because everything else was drawn by con_blink.
        MOV  R0,#$01
        ST   [CUR_CTRL],R0
        CALL con_cursor         ; and where the console thinks it is

        ; **The palette is the boot stub's, not this routine's.** A
        ; draft of the mode fix seeded entries 1 and 15 here, on the
        ; theory that an unseeded entry was why the bitmap modes drew
        ; black on black. They were black, and that was not why:
        ; tools/mkboot.py seeds both banks at boot and its writes were
        ; going to $FE1E/$FE1F, the I/O page's address before [D67]
        ; moved it. Nothing was reaching the palette at all, and the
        ; same stale-address bug was eating the font upload. Seeding
        ; here would have papered over one symptom of it.
        LD   R0,[CKIND]
        CMP  R0,#1
        BEQ  con_tilefont       ; mode 2 needs its glyphs as tiles

        ; ---- the bitmap modes' working set.
        LD   R0,[CFROW]         ; the font that matches the cell height
        CMP  R0,#16
        BEQ  .f16
        LDW  X,#F8
        BRA  .fset
.f16:   LDW  X,#F16
        ; Mode 3 is the one bitmap mode without line doubling, so its
        ; cells are 16 raster lines and the console uses the 8x16 face
        ; at $F600 -- the same Spleen the text modes read from ROM, at
        ; full height. 30 rows x 16 is the whole screen, where 8-line
        ; cells covered half of it.
        ;
        ; **Entry 1 is white here and nowhere else.** One bit per pixel
        ; can only name entries 0 and 1, and entry 1 of the boot
        ; palette is CGA blue -- correct for a bank whose slot meanings
        ; are kept, and wrong for the only colour this mode can write
        ; text in. So mode 3, alone, overrides it. The 4 and 8 bpp modes
        ; reach entry 15 and want no override; a draft that seeded both
        ; for every mode was chasing a different bug entirely, which
        ; turned out to be tools/mkboot.py writing the palette to the
        ; I/O page's old address.
        MOV  R0,#1
        ST   [PAL_IDX],R0
        MOV  R0,#$0F
        ST   [PAL_DATA],R0
        MOV  R0,#$FF
        ST   [PAL_DATA],R0
.fset:  STW  [CFONT],X

        LD   R0,[VID_BASE_L]    ; where the display is reading now
        MOV  XL,R0
        LD   R0,[VID_BASE_H]
        MOV  XH,R0
        STW  [CBASE],X

        LD   R0,[VID_STRIDE_L]  ; one raster row
        MOV  XL,R0
        LD   R0,[VID_STRIDE_H]
        MOV  XH,R0
        STW  [CSTR],X
        MOV  R0,XL              ; a cell row is eight of them...
        MOV  R1,XH
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        LD   R2,[CFROW]         ; ...or sixteen, where the cell is
        CMP  R2,#16
        BNE  .gs
        SHL  R0
        ROL  R1
.gs:    MOV  XL,R0
        MOV  XH,R1
        STW  [CGS8],X

        ; Repaint when the scrolled window would reach the fonts, whose
        ; floor is the 8x16 set at $F600. glim = ($F600 - rows*gs8) >> 8,
        ; and since only the high byte is kept the shift is free.
        CLR  R0                 ; X = rows * CGS8, a row at a time
        MOV  XL,R0
        MOV  XH,R0
        LD   R2,[CROWS]
.gl:    TST  R2
        BEQ  .gld
        PUSH R2
        LD   R0,[CGS8]
        LD   R1,[CGS8+1]
        CALL addx16
        POP  R2
        SUB  R2,#1
        BRA  .gl
.gld:   MOV  R0,XL
        MOV  R1,XH
        MOV  R2,#<F16
        MOV  R3,#>F16
        SUB  R2,R0
        SBC  R3,R1
        MOV  R0,R3
        ST   [CLIM],R0
        RET

; con_tilefont -- mode 2's console: the 96 text glyphs expanded once
; into 4 bpp tile patterns at VRAM $1000, and palette bank 2 seeded as
; bank 0's inverse pair so the cursor can blink by flipping one
; attribute nibble. PAT_BASE points at the set and the map is the
; mirror.
con_tilefont:
        CLR  R0
        ST   [VID_PAT_L],R0
        MOV  R0,#$10
        ST   [VID_PAT_H],R0

        MOV  R0,#8              ; the blitter does the expansion: four
        ST   [CFROW],R0         ;   bits per pixel straight into the
        MOV  R0,#4              ;   pattern slot, rows contiguous, so
        ST   [CBPC],R0          ;   the stride is 4 and not the screen's
        MOV  R0,#4
        MOV  XL,R0
        CLR  R0
        MOV  XH,R0
        STW  [CSTR],X

        CLR  R3                 ; glyph 0..95
.g:     LDW  X,#F8              ; font row = $FC00 + glyph * 8
        MOV  R0,R3
        CLR  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        CALL addx16
        STW  [GFA],X
        LDW  X,#$1000           ; pattern slot = $1000 + glyph * 32
        MOV  R0,R3
        CLR  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        CALL addx16
        STW  [GVA],X
        PUSH R3
        CALL bglyph
        POP  R3
        ADD  R3,#1
        CMP  R3,#96
        BLO  .g

        MOV  R0,#32             ; bank 2 is bank 0's inverse pair:
        ST   [PAL_IDX],R0       ;   entry 32 white, entry 47 black
        MOV  R0,#$0F
        ST   [PAL_DATA],R0
        MOV  R0,#$FF
        ST   [PAL_DATA],R0
        MOV  R0,#47
        ST   [PAL_IDX],R0
        CLR  R0
        ST   [PAL_DATA],R0
        ST   [PAL_DATA],R0
        RET

; con_at -- the cursor to row R0, column R1.
con_at: ST   [CCY],R0
        CALL con_setrow
        MOV  R0,R1
        ST   [CCX],R0
        JMP  con_cursor

; ---------------------------------------------------------------------
; There is deliberately no `con_putn` here.
;
; The compiled console had one, and `sw/ed.asm` hand-wrote it, and the
; interpreter has `sstr` -- which is [D66]'s "number to text, two
; implementations" with the console as the second. Formatting a number
; is not the console's job: the console emits characters, and whoever
; holds a number formats it and calls `con_putsn`.
;
; So the duplicate is not ported and not replaced, it is *removed* by
; the layering, which is the outcome [D66] wanted and could not reach
; while the two halves were in different languages. `con_putn` would
; also have had to call `udiv16` in `sw/interp.asm` -- a call upward,
; which the module rule in [D68] forbids and which is exactly the smell
; that says a routine is in the wrong file.
; ---------------------------------------------------------------------

; One message table for the editor and the interpreter alike. Entries
; 0-18 are indexed by ERR - 1; the tail is the disk's, by the same
; arithmetic, so a failed SAVE stops the statement the way every other
; error does rather than printing and carrying on.
RUNTAB:
        .asciz "SYNTAX"
        .asciz "FORS"
        .asciz "NO FOR"
        .asciz "COMPLEX"
        .asciz "OUT OF MEM"
        .asciz "VARS"
        .asciz "INDEX"
        .asciz "STR LEN"
        .asciz "TYPE"
        .asciz "ASM"
        .asciz "NO INSTR"
        .asciz "SYMBOL"
        .asciz "ERR"
        .asciz "BRANCH"
        .asciz "DIV BY 0"
        .asciz "LOOP"
        .asciz "CALL"
        .asciz "BREAK"
        .asciz "NO DATA"
        .asciz "DISK FULL"
        .asciz "NO FILE"
        .byte 0

MSGIN:    .asciz " IN "
MSGFREE:  .asciz " BYTES FREE"
MSGKFREE: .asciz "K FREE"