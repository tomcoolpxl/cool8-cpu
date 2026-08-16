// cool8_pixel — the line buffer, and everything between it and the pins.
//
// This is the pixel domain: 25.125 MHz, one palette index out per pixel
// clock. The line buffer is where it meets the rest of the machine, and
// apart from the palette it is the only place the two clocks touch.
//
// ## Raw words in, pixels out
//
// The buffer holds words exactly as the fetch engine read them, not
// decoded pixels. That is the whole reason it is one block RAM and not
// four: mode 6 is 128 words a line where it would be 256 decoded pixels,
// and a decoded buffer would also have to be *written* at 640 entries a
// line, which is more writes than a line has system cycles. Shifting
// belongs on the fast side of the crossing, where a pixel clock is
// exactly one pixel.
//
// Two banks of 256 words. A source row lives in bank row[0] and is
// filled during the row before it, so `read_bank` is stable for a whole
// row and can be sampled without a handshake — the same argument
// cool8_text made before this replaced it, and the same one that
// makes the crossing safe.
//
// ## Three cycles of lookahead, and no cadence
//
// A buffer read costs a cycle, the font read after it another, and the
// palette a third. Rather than a shift register and a load strobe the
// address simply runs three pixels ahead and wraps with the line, which
// puts the colour for pixel *x* on the pins exactly at *x*. The wrap is
// the part worth reading twice: at the last three pixels of a line the
// raster still reports the old `y`, so the row inside the glyph has to
// look ahead as well, or column 0 of every character row is drawn from
// the wrong slice.
//
// ## One extractor for four depths and two engines
//
// A word's pixels run left to right from the high nibble of the
// low-addressed byte, so the pixel *stream* is `{word[7:0],
// word[15:8]}` and pixel *k* sits at bit `15 - k*bpp`. Shifting the
// stream left by `k*bpp` therefore lands any pixel of any depth at the
// top, and one 16-bit barrel shifter plus a four-way mask covers 1, 2, 4
// and 8 bpp. Tiles are 4 bpp and go through the same shifter; only the
// index differs, because a tile adds its palette bank as the high
// nibble and a bitmap does not.
//
// ## The one place tiles need a second read
//
// A tile's palette bank and flip bits live in the map entry, not in the
// pattern, so the pixel stage needs two words where text and bitmaps
// need one. There is no second read port, so one cycle per tile is
// stolen: on the **last raster pixel of a tile** the read fetches the
// *next* tile's map entry instead of a pattern word. Nothing is lost —
// the pattern word for the second half of a tile was already read three
// pixels earlier and is still in `src_word`, which is why it is
// registered rather than used straight out of the buffer.
//
// ## What crosses on a wire, and why that is allowed
//
// `read_bank` gets two flip-flops, because it changes every line and a
// metastable sample would take a whole line with it. The mode
// registers get one: they change when software writes them, which is a
// few times a second at most, and the failure mode of a bad sample is a
// single wrong pixel on the boundary. Section 5.9's rule that writes
// take effect immediately is what rules out the alternative — latching
// the mode at vblank would make a raster split impossible, and raster
// splits are the reason those registers are readable mid-frame at all.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_pixel #(
    parameter FONT_FILE = "font.hex",
    parameter FONT_INIT = 1,
    parameter H_TOTAL   = 800,
    parameter V_TOTAL   = 525
) (
    // ---- pixel domain
    input  wire        pclk,
    input  wire        prst_n,
    input  wire [9:0]  x,
    input  wire [9:0]  y,
    input  wire        visible,
    output wire [11:0] rgb,

    // ---- the palette, one clock behind `pal_index`
    output wire [7:0]  pal_index,
    input  wire [11:0] pal_rgb,

    // ---- system domain: the line buffer's write side
    input  wire        sclk,
    input  wire        lb_we,
    input  wire        lb_bank,
    input  wire [7:0]  lb_addr,
    input  wire [15:0] lb_data,
    input  wire        read_bank,

    // ---- system domain: the sprite line buffer's write side
    input  wire        sb_we,
    input  wire [10:0] sb_addr,
    input  wire [9:0]  sb_data,
    input  wire [3:0]  spr_bank,        // shared by every sprite

    // ---- system domain: the mode. Quasi-static; see the header.
    input  wire        disp_en,
    input  wire [1:0]  engine,
    input  wire [1:0]  bpp_log,
    input  wire        hdouble,
    input  wire        vdouble,
    input  wire [7:0]  border,
    input  wire [10:0] hactive,
    input  wire [10:0] hstart,
    input  wire [9:0]  vactive,
    input  wire [9:0]  vstart,
    input  wire [9:0]  scrl_x,
    input  wire [9:0]  scrl_y,
    input  wire [6:0]  cur_x,
    input  wire [4:0]  cur_y,
    input  wire        cur_on
);

    localparam [1:0] E_TEXT = 2'd0, E_TILE = 2'd1;

    // ------------------------------------------------------ the crossing

    reg        rb_meta, rb;
    reg        c_dis;
    reg [1:0]  c_eng, c_bpp;
    reg        c_hdbl, c_vdbl;
    reg [7:0]  c_bord;
    reg [10:0] c_hact, c_hstart;
    reg [9:0]  c_vact, c_vstart;
    reg [9:0]  c_scrx, c_scry;
    reg [6:0]  c_curx;
    reg [4:0]  c_cury;
    reg        c_curon;
    reg [3:0]  c_sbank;

    always @(posedge pclk) begin
        rb_meta  <= read_bank;
        rb       <= rb_meta;
        c_dis    <= disp_en;
        c_eng    <= engine;
        c_bpp    <= bpp_log;
        c_hdbl   <= hdouble;
        c_vdbl   <= vdouble;
        c_bord   <= border;
        c_hact   <= hactive;
        c_hstart <= hstart;
        c_vact   <= vactive;
        c_vstart <= vstart;
        c_scrx   <= scrl_x;
        c_scry   <= scrl_y;
        c_curx   <= cur_x;
        c_cury   <= cur_y;
        c_curon  <= cur_on;
        c_sbank  <= spr_bank;
    end

    // ------------------------------------------------------ line buffer

    reg [15:0] lb [0:511];
    reg [15:0] lb_q;

    always @(posedge sclk)
        if (lb_we) lb[{lb_bank, lb_addr}] <= lb_data;

    // ---- and the sprites', which is a pixel per entry rather than a
    // word, because a sprite pixel has a palette bank and a priority
    // riding with it and there is nothing to shift.
    // **This one relies on block RAM coming up zeroed**, which it does:
    // EBR is initialised from the bitstream and yosys writes zeros where
    // nothing says otherwise. An entry of all zeros is generation zero
    // and colour zero, and colour zero is transparent — so the first two
    // lines of the first frame show background rather than whatever was
    // in the array. SPRAM has no such initialisation, which is why the
    // two memories are treated so differently everywhere else.
    // Nine bits, not fourteen: 2048 entries deep is 2 bits wide per block
    // RAM on this part, so the entry width *is* the block count. The
    // palette bank came out to pay for that; cool8_sprite's header has
    // the argument and why it stops at nine and not eight.
    reg [9:0] sb [0:2047];

    always @(posedge sclk)
        if (sb_we) sb[sb_addr] <= sb_data;

    // ------------------------------------------------------- lookahead
    //
    // Three pixels ahead, wrapping with the line rather than with the
    // counter's width, so the words for column 0 are read during the back
    // porch and the colour is on the pins at pixel 0. `xa2` is one
    // further still and is used only to name the next tile.
    //
    // **The second chain looks like duplication and is cheaper than not
    // duplicating it.** Deriving `sx2` by incrementing `sx1` — the
    // increment being `xa1[0]` under hdouble, and the next line's first
    // tile at the wrap, which is a constant per mode — was built and
    // measured at **+23 LUT4**. Everything below shares structure with
    // the first chain and the mapper exploits it; the derived version
    // adds a separate constant-path adder and a register that share with
    // nothing. Do not "optimise" this again without measuring it.

    wire [10:0] ah1 = {1'b0, x} + 11'd3;
    wire [10:0] ah2 = {1'b0, x} + 11'd4;
    wire        w1  = (ah1 >= H_TOTAL);
    wire        w2  = (ah2 >= H_TOTAL);
    wire [10:0] xa1 = w1 ? (ah1 - H_TOTAL) : ah1;
    wire [10:0] xa2 = w2 ? (ah2 - H_TOTAL) : ah2;

    // ...and the line follows the wrap, because at the last pixels of a
    // line `y` is still the line just finished. It wraps at the frame as
    // well: without that, the three pixels prepared during the last line
    // of a frame are prepared for line 525, which is outside the image
    // and comes out as border — three pixels of the wrong colour in the
    // top left corner of every frame.
    wire [9:0]  yn  = (y + 10'd1 >= V_TOTAL) ? 10'd0 : (y + 10'd1);
    wire [9:0]  ya  = w1 ? yn : y;

    // ---------------------------------------------------- where we are

    wire [10:0] xl1 = c_hdbl ? {1'b0, xa1[10:1]} : xa1;
    wire [10:0] xl2 = c_hdbl ? {1'b0, xa2[10:1]} : xa2;

    wire [10:0] rel1 = xl1 - c_hstart;
    wire [10:0] rel2 = xl2 - c_hstart;

    // Fine horizontal scroll only. The coarse part is a move of
    // VID_BASE, the same bargain the vertical direction makes, and a
    // bitmap gets the whole thing for nothing because its row is in the
    // buffer entire. **Text takes the low four bits** -- section 5.5
    // said so for a milestone while this mux passed text through
    // untouched (D93): the documented-but-absent trap, caught when the
    // scroller demo reached for it.
    wire [10:0] sx1 = (c_eng == E_TILE) ? rel1 + {8'd0, c_scrx[2:0]} :
                      (c_eng == E_TEXT) ? rel1 + {7'd0, c_scrx[3:0]} :
                      rel1 + {1'b0, c_scrx};
    wire [10:0] sx2 = (c_eng == E_TILE) ? rel2 + {8'd0, c_scrx[2:0]} :
                      (c_eng == E_TEXT) ? rel2 + {7'd0, c_scrx[3:0]} :
                      rel2 + {1'b0, c_scrx};

    wire [9:0]  vrel = ya - c_vstart;
    wire [9:0]  vsrc = (c_eng == E_TEXT) ? (vrel + {6'd0, c_scry[3:0]})
                                         : vrel;
    wire [3:0]  grow = vsrc[3:0];

    wire hborder = (xl1 < c_hstart) || (rel1 >= c_hact);
    wire vborder = (ya < c_vstart) || (vrel >= c_vact);
    wire blank   = hborder | vborder | ~c_dis;

    // ------------------------------------------------- the read address
    //
    // Three words to a tile: the map entry, then the two pattern words.
    // Not four — the multiply by three is one eight-bit add and it keeps
    // 81 tiles inside a 256-word bank, where a power-of-two stride would
    // have needed 324.

    wire [7:0] t1  = sx1[10:3];
    wire [7:0] t2  = sx2[10:3];
    wire [7:0] t1x3 = {t1[6:0], 1'b0} + t1;
    wire [7:0] t2x3 = {t2[6:0], 1'b0} + t2;

    // The last raster pixel of a tile, said as "the next pixel is in a
    // different tile" rather than as "this is pixel seven". The two are
    // the same everywhere except at the end of a line, and that is the
    // one place it matters: `xa2` wraps to the start of the next line, so
    // this fires there too and tile 0 gets its attribute. Testing for
    // pixel seven does not, and with a fine scroll the first tile on
    // every line is then drawn in the palette bank of the last tile of
    // the line before.
    wire last_of_tile = (t2 != t1);

    wire [3:0] ppw_log = 4'd4 - {2'd0, c_bpp};
    wire [10:0] wsel = sx1 >> ppw_log;

    wire [7:0] raddr = (c_eng == E_TEXT) ? sx1[10:3] :
                       (c_eng == E_TILE) ?
                           (last_of_tile ? t2x3 : (t1x3 + 8'd1 +
                                                   {7'd0, sx1[2]}))
                                          : wsel[7:0];

    // ---------------------------------------------------- the pipeline

    reg [15:0] src_word;               // the pattern or bitmap word
    reg [7:0]  attr_q;                 // a text cell's attribute
    reg [7:0]  attr_next, attr_cur;    // a tile's, one tile early
    reg [3:0]  d1_grow, d2_grow;
    reg [3:0]  d1_sub,  d2_sub;
    reg [2:0]  d1_col,  d2_col;
    reg        d1_blank, d2_blank;
    reg        d1_steal;
    reg        d1_last, d2_last;
    reg [7:0]  d1_cell, d2_cell;
    reg [4:0]  d1_trow, d2_trow;
    reg [9:0]  sb_q, sb_d;
    reg [4:0]  d1_tag, d2_tag;

    // For a bitmap the sub-index is the pixel inside the word; for a
    // tile it is the pixel inside the pattern word, which is 4 bpp, so
    // both feed the same shifter.
    wire [3:0] sub_now = (c_eng == E_TILE) ? {2'b00, sx1[1:0]}
                                           : (sx1[3:0] &
                                              ((4'd1 << ppw_log) - 4'd1));

    wire [7:0] font_q;

    always @(posedge pclk) begin
        if (!prst_n) begin
            lb_q      <= 16'h0000;
            src_word  <= 16'h0000;
            attr_q    <= 8'h00;
            attr_next <= 8'h00;
            attr_cur  <= 8'h00;
            d1_grow   <= 4'd0;  d2_grow  <= 4'd0;
            d1_sub    <= 4'd0;  d2_sub   <= 4'd0;
            d1_col    <= 3'd0;  d2_col   <= 3'd0;
            d1_blank  <= 1'b1;  d2_blank <= 1'b1;
            d1_steal  <= 1'b0;
            d1_last   <= 1'b0;  d2_last  <= 1'b0;
            d1_cell   <= 8'd0;  d2_cell  <= 8'd0;
            d1_trow   <= 5'd0;  d2_trow  <= 5'd0;
            sb_q      <= 10'd0; sb_d     <= 10'd0;
            d1_tag    <= 5'd0;  d2_tag   <= 5'd0;
        end else begin
            lb_q     <= lb[{rb, raddr}];

            // The sprite buffer is indexed by raster x, not by anything
            // the background modes scale, so it is read straight off the
            // lookahead and needs no arithmetic at all.
            sb_q     <= sb[{ya[0], xa1[9:0]}];
            sb_d     <= sb_q;
            d1_tag   <= ya[5:1];
            d2_tag   <= d1_tag;

            d1_grow  <= grow;      d2_grow  <= d1_grow;
            d1_sub   <= sub_now;   d2_sub   <= d1_sub;
            d1_col   <= sx1[2:0];  d2_col   <= d1_col;
            d1_blank <= blank;     d2_blank <= d1_blank;
            d1_last  <= last_of_tile;
            d2_last  <= d1_last;
            d1_steal <= (c_eng == E_TILE) & last_of_tile;
            d1_cell  <= sx1[10:3];  d2_cell <= d1_cell;
            // **One divisor, because every mode's console row is 16
            // display lines.** 30 rows over 480 in modes 0-4 and 6, 24
            // over 384 in mode 5: sixteen every time. The doubler
            // stretches source lines to fill the screen and the console
            // halves its glyph height to match, so the *display* pitch
            // of a row never changes -- and this counts display lines.
            //
            // It was `c_vdbl ? vsrc[7:3] : vsrc[8:4]`, which made the
            // cursor cell eight lines tall in the doubled modes: half
            // height, and on the wrong row once the row number no
            // longer meant the same thing on both sides. Choosing per
            // mode was the fault; there is nothing to choose.
            d1_trow  <= vsrc[8:4];
            d2_trow <= d1_trow;

            // A stolen cycle carries a map entry, not a pattern: leaving
            // `src_word` alone is what makes the theft free, because the
            // word it still holds is the one this half of the tile needs.
            if (d1_steal) attr_next <= lb_q[15:8];
            else          src_word  <= lb_q;

            attr_q <= lb_q[15:8];

            // Two cycles behind the steal, which is when the extraction
            // first asks for the new tile's bank.
            if (d2_last) attr_cur <= attr_next;
        end
    end

    // The font is the same 4 KB synchronous ROM the boot image uses: 256
    // glyphs of 16 rows, addressed {character, row}. It has its own port,
    // so a glyph costs no memory bandwidth anywhere.
    cool8_rom #(.INIT_FILE(FONT_FILE), .INIT(FONT_INIT)) u_font (
        .clk(pclk), .read(1'b1),
        .addr({lb_q[7:0], d1_grow}),
        .rdata(font_q)
    );

    // ------------------------------------------------------ the pixel

    wire [15:0] ps  = {src_word[7:0], src_word[15:8]};
    wire [3:0]  off = d2_sub << c_bpp;
    wire [15:0] shl = ps << off;
    wire [7:0]  pxr = shl[15:8];

    wire [7:0] pix = (c_bpp == 2'd0) ? {7'd0, pxr[7]}    :
                     (c_bpp == 2'd1) ? {6'd0, pxr[7:6]}  :
                     (c_bpp == 2'd2) ? {4'd0, pxr[7:4]}  : pxr;

    // ---- the cursor, in every mode
    //
    // **The compare was never text-specific.** `d2_cell` and `d2_trow`
    // are computed unconditionally, not gated by `engine`, so the cell
    // a pixel belongs to is known in all seven modes. What made the
    // cursor text-only was applying the result *here*, inside the text
    // path's `lit`. So the console grew a second, software cursor for
    // the other five modes -- and two things that each remember where
    // the cursor is disagree the moment a mode changes. That was the
    // cursor blinking in a stale spot until a key moved it.
    //
    // The invert moves to `pal_index` below: one XOR on the finished
    // index, which is visible in text, tile and bitmap alike. The style
    // mux and `in_lines` go with it -- the editor has only ever set
    // style 3, and a block that inverts its cell is what a C64 draws.
    wire cur_cell = c_curon && (d2_cell == {1'b0, c_curx}) &&
                    (d2_trow == c_cury);

    wire lit = font_q[3'd7 - d2_col];

    wire [7:0] bg_index = (c_eng == E_TEXT) ?
                              {4'h0, lit ? attr_q[3:0] : attr_q[7:4]} :
                          (c_eng == E_TILE) ? {attr_cur[3:0], pix[3:0]}
                                            : pix;

    // A sprite pixel counts if it was written for *this* line — the
    // generation bit is what makes clearing the buffer unnecessary — and
    // if it is not colour zero, which is the transparent one. `behind`
    // puts it under the background wherever the background is not itself
    // colour zero.
    wire spr_here   = (sb_d[9:5] == d2_tag) && (sb_d[3:0] != 4'd0);
    wire spr_wins   = spr_here && (!sb_d[4] || (bg_index == 8'h00));

    // The cursor inverts the finished index, after the sprite has had
    // its say: an editor cursor over a sprite is still a cursor, and
    // one XOR here covers three engines where three separate inverts
    // inside them would not have fitted.
    assign pal_index = d2_blank ? c_bord :
                       (spr_wins ? {c_sbank, sb_d[3:0]} : bg_index)
                       ^ (cur_cell ? 8'h0F : 8'h00);

    // Blanking is black on the pins, not the border colour: outside the
    // display window a monitor is not looking, and a sync separator that
    // is might be.
    assign rgb = visible ? pal_rgb : 12'h000;

    // Vertical doubling is the fetch engine's business — it decides which
    // source row a raster line reads — so nothing here needs it.
    wire _unused = &{1'b0, c_vdbl, sx2[2:0], 1'b0};

endmodule

`default_nettype wire
