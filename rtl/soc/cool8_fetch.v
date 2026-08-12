// cool8_fetch — the display fetch: one source row into one bank of the
// line buffer, a row ahead of the raster.
//
// Three engines share one sequencer, because they differ only in what an
// item is and where it comes from (docs/04-system.md section 5.3):
//
//   text     80 or 40 cells of one 16-bit word, from **main RAM**
//   tile     41 or 81 tiles: a map entry, then the two pattern words for
//            the row inside the tile, from VRAM
//   bitmap   `stride/2` words straight out of VRAM
//
// **Which memory is read is a function of the mode decode and of
// nothing else** — D28. There is no register that could point a bitmap
// at main RAM or a text map at VRAM, so the guarantee that the blitter
// and the sprite engine never contend with the CPU is structural rather
// than a rule software has to keep.
//
// ## A row ahead, and which bank
//
// A source row lives in bank `row[0]` and is filled during the row
// before it, which is what makes the swap a wire and not a decision. So
// at the first raster line of source row R the read bank becomes R[0]
// and the fill of row R+1 starts into the other one. Row 0 has no row
// before it and is primed at the start of vertical blanking, where there
// are 45 blank lines and nothing else to do — the blank top line that
// dropped out of the testbench when this was left out is in
// docs/06-roadmap.md.
//
// The same priming covers the other end: the fill triggered on the last
// active line runs one row past the bottom of the screen and lands in
// the bank row 0 will want. It is harmless because vertical blanking
// refills that bank afterwards, and it costs one row of bandwidth out of
// thirty against a comparator it would take to avoid.
//
// A source row is a raster line in a bitmap, a raster line pair when
// lines are doubled, and sixteen raster lines in text — so the fill
// window is one line at worst and sixteen at best.
//
// ## One access outstanding, except in a bitmap
//
// Text and tiles run request-grant-data with nothing in flight behind,
// which costs two cycles an access and still fits: 80 cells of two bytes
// is 320 cycles against the 4256 a character row lasts, and 41 tiles of
// three words is 246 against the 532 a doubled line lasts.
//
// A bitmap does not have that slack — mode 6 is 128 words in one line of
// 266 cycles — so its requests and its write-backs run on separate
// counters and the port is asked on every cycle. That is exactly what
// cool8_vram was built to allow: the display is priority zero, so its
// grant is unconditional and data comes back one cycle later, forever.
// The bandwidth table in section 5.10 is counted in those accesses.
//
// ## The circular wrap
//
// Text and tile maps are 32 rows tall (D30), so the row pointer wraps
// within `stride * 32` bytes and scrolling a terminal really is one add
// on `VID_BASE` with no bulk copy anywhere. **The wrap is a mask, so it
// is only correct for a power-of-two stride** — which is the argument
// D30 made for a power-of-two stride in the first place. Software that
// sets 160 to get the 4800-byte screen back gets no hardware wrap with
// it and has to scroll by copying, and that is the trade it chose.
//
// Bitmaps do not wrap: a frame buffer is not a torus and a row pitch of
// 80 says nothing about where the buffer ends.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_fetch (
    input  wire        clk,
    input  wire        rst_n,

    // ---- the raster, carried over from the pixel domain
    input  wire        line_start,     // one pulse per line
    input  wire [9:0]  line_y,         // the line about to be displayed
    input  wire        frame_start,    // one pulse per frame, at vblank

    // ---- the mode
    input  wire        disp_en,
    input  wire [1:0]  engine,         // 0 text, 1 tile, 2 bitmap
    input  wire        hdouble,
    input  wire        vdouble,
    input  wire [15:0] base,
    input  wire [15:0] stride,
    input  wire [15:0] pat_base,
    input  wire [9:0]  scrl_y,
    input  wire [9:0]  vactive,
    input  wire [9:0]  vstart,

    // ---- main RAM, for text maps only. One access outstanding.
    output wire        ram_req,
    output wire [15:0] ram_addr,
    input  wire        ram_gnt,
    input  wire        ram_rvalid,
    input  wire [7:0]  ram_rdata,

    // ---- VRAM, the display port of cool8_vram
    output wire        vr_req,
    output wire [15:1] vr_addr,
    input  wire        vr_gnt,
    input  wire        vr_rvalid,
    input  wire [15:0] vr_rdata,

    // ---- the line buffer's write side
    output wire        lb_we,
    output wire        lb_bank,
    output wire [7:0]  lb_addr,
    output wire [15:0] lb_data,

    output reg         o_read_bank
);

    localparam [1:0] E_TEXT = 2'd0, E_TILE = 2'd1, E_BITMAP = 2'd2;

    localparam [2:0] S_IDLE   = 3'd0,
                     S_BMP    = 3'd1,
                     S_TXT_LO = 3'd2,
                     S_TXT_HI = 3'd3,
                     S_MAP    = 3'd4,
                     S_PAT0   = 3'd5,
                     S_PAT1   = 3'd6,
                     S_DONE   = 3'd7;

    reg  [2:0]  st;
    reg  [7:0]  i;                     // item: cell, tile or word
    reg  [7:0]  n;                     // how many of them
    reg  [7:0]  wb;                    // bitmap write-backs, behind `i`
    reg         fbank;                 // the bank being filled
    reg         inflight;              // an access is out, data not yet in

    reg  [15:0] row_ptr;               // the row being fetched
    reg  [2:0]  trow;                  // the row inside a tile
    reg  [15:0] wrap_span;             // stride * 32: the map's height

    // The row pointer's wrap, once, for the two engines that need it.
    //
    // **This was a mask**, `(base & ~mask) | ((row_ptr + stride) & mask)`
    // with `mask = stride*32 - 1`, which is only correct when the stride
    // is a power of two -- the argument D30 made for a stride of 256 and
    // a 128x32 map, 8192 bytes to display 80x30. A compare and a
    // subtract costs about what the mask's three 16-bit bitwise ops did
    // and holds for any stride, so a 160-byte row is a legal map again
    // and the padding is 3072 bytes of main RAM the user can have back.
    // **Two subtractors, and that is the cheap version -- measured.**
    // The obvious saving is to register `base + span` and compare
    // against it, which removes the `- base` here. It costs 36 logic
    // cells more (5193 against 5157): sixteen flip-flops for the limit
    // and an adder maintaining it every cycle, against a subtractor
    // yosys can share with the compare beside it. Do not re-derive it.
    wire [15:0] rp_next = row_ptr + stride;
    wire [15:0] rp_off  = rp_next - base;
    wire [15:0] rp_wrap = (rp_off >= wrap_span) ? (rp_next - wrap_span)
                                                : rp_next;

    reg  [7:0]  lo_byte;               // a text cell's first half
    reg  [15:0] ent;                   // a tile's map entry
    reg  [15:0] pat_a;                 // ...and its pattern address

    reg         prime;                 // vblank's fetch is the first of two
    reg         primed;                // ...and both are still untouched

    wire is_text   = (engine == E_TEXT);
    wire is_tile   = (engine == E_TILE);
    wire is_bitmap = (engine == E_BITMAP);

    // -------------------------------------------------- where the line is
    //
    // `vrel` is the line counted from the top of the image rather than
    // the top of the screen, so a bordered mode fetches nothing while the
    // raster is in the border and its first source row is still row 0.

    wire [9:0] vrel  = line_y - vstart;
    wire       vin   = (line_y >= vstart) && (vrel < vactive);
    wire [9:0] vlog  = vdouble ? {1'b0, vrel[9:1]} : vrel;

    // Fine vertical scroll only: the coarse part is a move of VID_BASE,
    // which is what "increment the origin row" means in section 5.5 and
    // is one 16-bit add in software against a multiplier in gates.
    wire [9:0] vsrc_t = vrel + {6'd0, scrl_y[3:0]};

    // The first raster line of a new source row. Text rows are sixteen
    // lines of glyph; everything else refills every logical line, because
    // a tile's pattern row changes as fast as a bitmap's does.
    wire row_edge = is_text ? (vsrc_t[3:0] == 4'd0)
                            : (vdouble ? (vrel[0] == 1'b0) : 1'b1);

    wire disp_bank = is_text ? vsrc_t[4] : vlog[0];

    // Vertical blanking fills **two** rows, not one. Without a scroll the
    // first row boundary is line 0 itself and one primed row would do —
    // but a fine vertical scroll of five moves that boundary to line 11,
    // and nothing between vblank and line 11 would have fetched the row
    // the raster wants there. Two rows cost 640 cycles of the 17,145 in
    // a vertical blank, and they remove the special case rather than
    // guarding it.
    //
    // The first active line then has to *not* trigger a fetch, or it
    // would overwrite one of the two. `primed` says so, and it is
    // cleared by that line whether or not the line is a row boundary —
    // which is what makes the scrolled and unscrolled cases the same
    // rule.
    wire start_row   = line_start & vin & row_edge & disp_en & ~primed;
    wire start_frame = frame_start & disp_en;

    // ---------------------------------------------------- how many items

    wire [7:0] n_text = hdouble ? 8'd40 : 8'd80;
    // One more tile than the screen shows, so a fine horizontal scroll
    // has something to scroll in from.
    wire [7:0] n_tile = hdouble ? 8'd41 : 8'd81;
    // The row pitch is the row: `stride/2` words hold exactly the pixels
    // the pitch describes, which is why there is no width register.
    //
    // **A bitmap row is at most 255 words, so `VID_STRIDE` above 510
    // silently clamps.** That is the line buffer's bank size — 256 words —
    // and not an arbitrary limit, but nothing else says so, and a mode
    // built by hand with a longer pitch loses the end of every row rather
    // than failing. docs/04-system.md section 5.3 records it; the widest
    // mode in the set is mode 6 at 256 bytes, so there is a factor of two
    // of headroom before anyone meets it.
    wire [7:0] n_bmp  = (|stride[15:9]) ? 8'd255 : stride[8:1];

    wire [7:0] n_next = is_text ? n_text : is_tile ? n_tile : n_bmp;

    // ------------------------------------------------- the tile addresses
    //
    // Attribute: [7] V-flip, [6] H-flip, [5:4] pattern bank, [3:0]
    // palette bank. A tile is 8x8 at 4 bpp, so 32 bytes, and one row of
    // it is four — which is why the pattern address is a concatenation
    // and not a multiply.

    wire hflip = ent[14];

    // A pattern word's four pixels run left to right from the high nibble
    // of the low-addressed byte, so reversing a row is a nibble reversal
    // of the whole word and a swap of the pair. Both are wiring.
    function [15:0] revw;
        input [15:0] w;
        revw = {w[3:0], w[7:4], w[11:8], w[15:12]};
    endfunction

    // ------------------------------------------------------ the requests

    wire want_bmp = (st == S_BMP) && (i < n);
    wire want_vr  = want_bmp |
                    (((st == S_MAP) | (st == S_PAT0) | (st == S_PAT1)) &
                     ~inflight);
    wire want_ram = ((st == S_TXT_LO) | (st == S_TXT_HI)) & ~inflight;

    assign vr_req  = want_vr;
    assign ram_req = want_ram;

    assign vr_addr = (st == S_BMP)  ? (row_ptr[15:1] + {7'd0, i}) :
                     (st == S_MAP)  ? (row_ptr[15:1] + {7'd0, i}) :
                     (st == S_PAT0) ? pat_a[15:1]
                                    : (pat_a[15:1] + 15'd1);

    // A cell is two bytes at `row_ptr + 2i`, low half first.
    assign ram_addr = row_ptr + {7'd0, i, 1'b0} +
                      {15'd0, (st == S_TXT_HI)};

    // -------------------------------------------------- the write-backs

    wire [7:0] i3 = {i[6:0], 1'b0} + i;                // three words a tile

    assign lb_we   = (st == S_BMP)    ? vr_rvalid  :
                     (st == S_TXT_HI) ? ram_rvalid :
                     ((st == S_MAP) | (st == S_PAT0) | (st == S_PAT1))
                                      ? vr_rvalid  : 1'b0;

    assign lb_bank = fbank;

    assign lb_addr = (st == S_BMP)    ? wb :
                     (st == S_TXT_HI) ? i  :
                     (st == S_MAP)    ? i3 :
                     (st == S_PAT0)   ? (i3 + (hflip ? 8'd2 : 8'd1))
                                      : (i3 + (hflip ? 8'd1 : 8'd2));

    wire pat_state = (st == S_PAT0) | (st == S_PAT1);

    assign lb_data = (st == S_TXT_HI)     ? {ram_rdata, lo_byte} :
                     (pat_state & hflip)  ? revw(vr_rdata)
                                          : vr_rdata;

    // ------------------------------------------------------ the sequencer

    always @(posedge clk) begin
        if (!rst_n) begin
            st          <= S_IDLE;
            i           <= 8'd0;
            n           <= 8'd0;
            wb          <= 8'd0;
            fbank       <= 1'b0;
            inflight    <= 1'b0;
            row_ptr     <= 16'h0000;
            trow        <= 3'd0;
            wrap_span   <= 16'h2000;
            lo_byte     <= 8'h00;
            ent         <= 16'h0000;
            pat_a       <= 16'h0000;
            prime       <= 1'b0;
            primed      <= 1'b0;
            o_read_bank <= 1'b0;
        end else begin
            // 32 rows of `stride`. Registered rather than recomputed,
            // to keep the shift off the address path.
            wrap_span <= (stride << 5);

            // Qualified by `disp_en` for the same reason `start_row` is:
            // with the display off nothing is being filled, so nothing
            // should be swapping either. It made no visible difference —
            // the picture is blanked — but a bank that walks while the
            // fetch engine is idle is a thing to have to reason about.
            if (line_start & vin & row_edge & disp_en)
                o_read_bank <= disp_bank;

            // The first active line of a frame has both primed rows
            // waiting for it, so it consumes the flag and fetches
            // nothing. Everything after it is an ordinary row boundary.
            if (line_start & vin) primed <= 1'b0;

            // A new trigger always wins. The margins say one cannot
            // arrive while a fill is still running, and a fill that
            // hangs on a memory that never answers would otherwise stop
            // the display for good rather than for a frame.
            if (start_frame) begin
                i        <= 8'd0;
                wb       <= 8'd0;
                n        <= n_next;
                fbank    <= 1'b0;
                inflight <= 1'b0;
                row_ptr  <= base;
                trow     <= scrl_y[2:0];
                prime    <= 1'b1;
                primed   <= 1'b1;
                // Row 0 always lands in bank 0: the first active line of
                // a frame has `vrel` zero whatever the scroll is, so the
                // bank it reads is zero however the bank is derived.
                o_read_bank <= 1'b0;
                st       <= is_text ? S_TXT_LO : is_tile ? S_MAP : S_BMP;
            end else if (start_row) begin
                i        <= 8'd0;
                wb       <= 8'd0;
                n        <= n_next;
                fbank    <= ~disp_bank;
                inflight <= 1'b0;
                st       <= is_text ? S_TXT_LO : is_tile ? S_MAP : S_BMP;
            end else begin
                case (st)
                    // ---- bitmap: issue and collect on separate counters
                    S_BMP: begin
                        if (vr_req & vr_gnt) i <= i + 1'b1;
                        if (vr_rvalid) begin
                            wb <= wb + 1'b1;
                            if (wb + 8'd1 == n) begin
                                st <= S_DONE;
                                row_ptr <= row_ptr + stride;
                            end
                        end
                    end

                    // ---- text: two bytes make a cell
                    S_TXT_LO: begin
                        if (ram_req & ram_gnt) inflight <= 1'b1;
                        if (ram_rvalid) begin
                            lo_byte  <= ram_rdata;
                            inflight <= 1'b0;
                            st       <= S_TXT_HI;
                        end
                    end
                    S_TXT_HI: begin
                        if (ram_req & ram_gnt) inflight <= 1'b1;
                        if (ram_rvalid) begin
                            inflight <= 1'b0;
                            i        <= i + 1'b1;
                            if (i + 8'd1 == n) begin
                                st      <= S_DONE;
                                row_ptr <= rp_wrap;
                            end else st <= S_TXT_LO;
                        end
                    end

                    // ---- tile: the map entry decides the pattern address
                    S_MAP: begin
                        if (vr_req & vr_gnt) inflight <= 1'b1;
                        if (vr_rvalid) begin
                            ent      <= vr_rdata;
                            inflight <= 1'b0;
                            st       <= S_PAT0;
                        end
                    end
                    S_PAT0: begin
                        if (vr_req & vr_gnt) inflight <= 1'b1;
                        if (vr_rvalid) begin
                            inflight <= 1'b0;
                            st       <= S_PAT1;
                        end
                    end
                    S_PAT1: begin
                        if (vr_req & vr_gnt) inflight <= 1'b1;
                        if (vr_rvalid) begin
                            inflight <= 1'b0;
                            i        <= i + 1'b1;
                            if (i + 8'd1 == n) begin
                                st   <= S_DONE;
                                trow <= trow + 1'b1;
                                // The map row only moves every eighth
                                // line of tile; the pattern row moves
                                // every one.
                                if (trow == 3'd7)
                                    row_ptr <= rp_wrap;
                            end else st <= S_MAP;
                        end
                    end

                    // One row is finished. During vertical blanking the
                    // next one follows it straight into the other bank;
                    // at every other time there is nothing to do until
                    // the next row boundary.
                    S_DONE: begin
                        if (prime) begin
                            prime    <= 1'b0;
                            i        <= 8'd0;
                            wb       <= 8'd0;
                            fbank    <= ~fbank;
                            inflight <= 1'b0;
                            st       <= is_text ? S_TXT_LO :
                                        is_tile ? S_MAP : S_BMP;
                        end else st <= S_IDLE;
                    end

                    default: ;
                endcase
            end

            // The pattern address is formed the cycle the map entry
            // lands, so S_PAT0 has it ready to present.
            if ((st == S_MAP) && vr_rvalid)
                pat_a <= pat_base + {1'b0, vr_rdata[13:12], vr_rdata[7:0],
                                     (vr_rdata[15] ? ~trow : trow), 2'b00};
        end
    end

    wire _unused = &{1'b0, is_bitmap, 1'b0};

endmodule

`default_nettype wire
