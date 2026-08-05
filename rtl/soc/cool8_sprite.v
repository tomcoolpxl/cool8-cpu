// cool8_sprite — 32 sprites, eight to a scanline. $FE2A-$FE2C.
//
// Independent of the background mode, because it does not touch the
// background: it fills a line buffer of its own and cool8_pixel merges
// the two at the last moment. So sprites work over text, tiles and
// bitmaps alike, and none of the three background engines knows they
// exist.
//
// ## The descriptor is packed for the scan, not for the eye
//
// Section 5.6 lists the eight bytes of a descriptor in a readable order.
// This does not use that order, and the reason is arithmetic: at
// 8.375 MHz a scanline is **266 system clocks**, and every one of the 32
// descriptors has to be asked "are you on this line" inside it. Four
// byte reads each would be 128 clocks before a single pattern was
// fetched.
//
// So the block RAM is sixteen bits wide and the whole test — enable,
// size, and all nine bits of Y — lives in **word 0**. The scan is then
// one read per descriptor, 33 clocks, and the other three words are read
// only for the eight sprites that matter.
//
//   bytes 0,1   Y[7:0]  |  {size, enable, -, -, -, -, -, Y[8]}
//   bytes 2,3   X[7:0]  |  {-, -, -, -, -, -, X[9:8]}
//   bytes 4,5   pattern[12:5] | {-, -, -, -, -, pattern[15:13]}
//   bytes 6,7   {vflip, hflip, behind, -, -, -, -, -} | palette bank
//
// A descriptor is written as byte *pairs*: the even byte is held in
// flip-flops and the odd byte commits both, the same arrangement
// cool8_pal uses and for the same reason — a block RAM in this
// configuration has no byte enables. Software writes descriptors in
// order from an even index, which it does anyway.
//
// ## Priority is descriptor order, done backwards
//
// Section 5.6 says the lowest-numbered sprite wins, implemented as
// first-writer-wins. That needs the line buffer read back before every
// write, and an iCE40 block RAM has one read port and one write port —
// and the read port belongs to the raster. So the eight sprites of a
// line are rendered **in reverse**, seven first and zero last, and
// last-writer-wins produces exactly the same picture with no reads at
// all. Pixel value zero is transparent and simply skips its write.
//
// ## Two lines a sprite writes, and one sweep that catches the rest
//
// Clearing the buffer would take 640 of the 266 clocks a line has, so
// nothing clears it outright. Three things keep it honest instead, and
// each of them exists because the one before it was not enough.
//
// **A sprite is rendered for two lines past its bottom edge, writing
// zeros.** That puts a transparent entry in both banks of the span it
// used — two lines because the banks alternate — so a sprite that has
// moved or gone leaves nothing behind. Those trailing rows take slots in
// the eight-per-line budget like anything else, and past line 480 they
// are the only thing rendered at all: a real row written there would be
// tagged like a row at the top of the screen and would appear there.
//
// **Every entry carries the line it was written for**, five bits of it,
// compared against the line being displayed; a mismatch reads as
// transparent. The first version of that was one bit — the parity of
// the line pair — which separates a line from the one two lines earlier
// and *not* from the one four earlier, so a sprite's last row came back
// four lines under it in a band that repeated down the screen.
//
// **And 64 entries of the bank about to be filled are zeroed at the
// start of every fill**, walking the bank. Widening the tag alone does
// not close it: a transparent pixel is never written, because writing it
// would erase a lower-priority sprite showing through the hole, so an
// entry can survive arbitrarily long and no finite tag outlasts that.
// The sweep bounds it — nothing survives more than ten fills of a bank,
// which is twenty lines, and five bits of tag separate thirty-two fills,
// which is sixty-four. It runs alongside the descriptor scan, on a
// different memory, so it costs no time.
//
// The symptom this last one fixes is worth stating, because it is what a
// design like this looks like when it is subtly wrong: a hole inside a
// sprite showing that sprite's own colour from four rows higher up.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_sprite (
    input  wire        clk,
    input  wire        rst_n,

    // ---- the I/O page, $FE2A-$FE2C
    input  wire [7:0]  io_a,
    input  wire        io_rd,
    input  wire        io_we,
    input  wire [7:0]  io_wdata,
    output wire        o_sel,
    output reg  [7:0]  o_rdata,

    // ---- the raster, from cool8_video's crossing
    input  wire        line_start,
    input  wire [9:0]  line_y,
    input  wire        frame_start,

    // ---- VRAM, the sprite port of cool8_vram
    output wire        vr_req,
    output wire [15:1] vr_addr,
    input  wire        vr_gnt,
    input  wire        vr_rvalid,
    input  wire [15:0] vr_rdata,

    // ---- the sprite line buffer's write side, in cool8_pixel
    output wire        sb_we,
    output wire [10:0] sb_addr,        // {bank, x[9:0]}
    output wire [13:0] sb_data         // {tag[4:0], behind, bank, pix}
);

    localparam [7:0] A_IDX = 8'h2A, A_DATA = 8'h2B, A_CTRL = 8'h2C;

    localparam [3:0] S_IDLE  = 4'd0, S_SCAN = 4'd1, S_TALLY = 4'd2,
                     S_SEL   = 4'd3, S_D0   = 4'd4, S_D1    = 4'd5,
                     S_D2    = 4'd6, S_D3   = 4'd7, S_FW    = 4'd8,
                     S_PUSH  = 4'd9;

    // ---------------------------------------------------- the registers

    reg [7:0]  idx;
    reg        spr_en, overrun;
    reg [7:0]  hold;                   // the even byte, waiting for its pair

    assign o_sel = (io_a >= A_IDX) && (io_a <= A_CTRL);
    wire wr = io_we & o_sel;

    // ---------------------------------------------------------- state

    reg [3:0]  st;
    reg [9:0]  ln;                     // the line being prepared
    reg [4:0]  s, s_q;                 // the scan's counter, and its echo
    reg        scan_v;
    reg [3:0]  nhit, k;
    reg        pass;                   // 0 = the trailing rows, 1 = sprites
    reg        trail;                  // ...and which this one is
    reg [4:0]  hit_s [0:7];
    reg [5:0]  hit_y [0:7];            // {trailing, size, row in sprite}

    reg [9:0]  sx;
    reg [15:0] pat;
    reg [3:0]  pbank, yy;
    reg        hflip, vflip, behind, big;
    reg [2:0]  w;                      // which pattern word
    reg [15:0] pw;                     // ...and the four pixels in it
    reg [1:0]  n;                      // which of them is going out

    reg        req_r;
    reg [15:0] preq;

    // The sweep. Its base walks the bank 64 entries at a time, one step
    // per fill of that bank, so ten fills cover all 640.
    reg [9:0]  swp_base [0:1];
    reg [6:0]  swp_cnt;                // bit 6 set means idle
    wire       swp_busy = ~swp_cnt[6];
    wire [9:0] swp_x    = swp_base[ln[0]] + {4'd0, swp_cnt[5:0]};

    assign vr_req  = req_r;
    assign vr_addr = preq[15:1];

    // ------------------------------------------------ the descriptor RAM

    reg [15:0] desc [0:127];
    reg [15:0] dq;
    reg [6:0]  daddr;

    wire        dwe = wr & (io_a == A_DATA) & idx[0];
    wire [6:0]  dwa = idx[7:1];
    wire [15:0] dwd = {io_wdata, hold};

    // The scan drives the address straight off its counter so it can ask
    // one descriptor per cycle; everything else uses the register.
    wire [6:0] ra = (st == S_SCAN) ? {s, 2'b00} : daddr;

    always @(posedge clk) begin
        if (dwe) desc[dwa] <= dwd;
        dq <= desc[ra];
    end

    // ---- word 0, as the scan reads it
    wire       d_size = dq[15];
    wire       d_en   = dq[14];
    wire [9:0] d_y    = {1'b0, dq[8], dq[7:0]};
    wire [9:0] d_dy   = ln - d_y;
    wire [9:0] d_h    = d_size ? 10'd16 : 10'd8;
    // Two lines past the bottom edge, where the sprite writes zeros over
    // its own span instead of pixels.
    wire       d_trail = (d_dy >= d_h);
    // Past the bottom of the screen only the trailing rows are rendered.
    // Those lines' bank-and-generation tags alias the top of the screen,
    // so a *real* row written there would appear at the top of the next
    // frame — which is exactly what a sprite at line 472 did. A trailing
    // row writes zeros, and a zero is transparent whatever it is tagged
    // with, so it is safe there and it is the only thing that can finish
    // cleaning up after a sprite that runs off the bottom.
    wire       d_hit   = d_en & (d_dy < (d_h + 10'd2)) &
                         ((ln < 10'd480) | d_trail);

    // ---- the row inside the sprite, flipped if it has to be
    wire [3:0] row_e = vflip ? ((big ? 4'd15 : 4'd7) - yy) : yy;

    // ---- the pixel going out
    wire [15:0] ps   = {pw[7:0], pw[15:8]};
    wire [3:0]  pix  = ps >> ({2'b00, ~n} << 2);
    wire [3:0]  cnt  = {w[1:0], 2'b00} + {2'b00, n};
    wire [3:0]  span = big ? 4'd15 : 4'd7;
    wire [9:0]  px   = sx + (hflip ? {6'd0, span - cnt} : {6'd0, cnt});

    // Colour zero is transparent and skips its write — except on a
    // trailing row, where writing the zero *is* the job.
    wire render_we = (st == S_PUSH) && (trail || (pix != 4'd0)) &&
                     (px < 10'd640);

    assign sb_we   = swp_busy ? 1'b1 : render_we;
    assign sb_addr = swp_busy ? {ln[0], swp_x} : {ln[0], px};
    assign sb_data = swp_busy ? 14'd0 : {ln[5:1], behind, pbank, pix};

    // ---------------------------------------------------------- the run

    wire [9:0] next_line = line_y + 10'd1;
    // Every line, including the blanking ones: a sprite that runs off the
    // bottom still has to write the zeros that tidy its span away, and
    // those land past line 480. `d_hit` is what makes that safe.
    wire       start = (frame_start | line_start) & spr_en;

    integer i;

    always @(posedge clk) begin
        if (!rst_n) begin
            idx <= 8'd0; spr_en <= 1'b0; overrun <= 1'b0; hold <= 8'd0;
            daddr <= 7'd0; ln <= 10'd0; s <= 5'd0; s_q <= 5'd0;
            nhit <= 4'd0; k <= 4'd0; scan_v <= 1'b0; st <= S_IDLE;
            sx <= 10'd0; pat <= 16'd0; pbank <= 4'd0; yy <= 4'd0;
            hflip <= 1'b0; vflip <= 1'b0; behind <= 1'b0; big <= 1'b0;
            w <= 3'd0; pw <= 16'd0; n <= 2'd0;
            pass <= 1'b0; trail <= 1'b0;
            req_r <= 1'b0; preq <= 16'd0;
            swp_cnt <= 7'h40;
            swp_base[0] <= 10'd0;
            swp_base[1] <= 10'd0;
            for (i = 0; i < 8; i = i + 1) begin
                hit_s[i] <= 5'd0;
                hit_y[i] <= 6'd0;
            end
        end else begin
            if (req_r & vr_gnt) req_r <= 1'b0;

            if (wr) begin
                case (io_a)
                    A_IDX:  idx <= io_wdata;
                    A_DATA: begin
                        idx  <= idx + 8'd1;
                        hold <= io_wdata;
                    end
                    A_CTRL: begin
                        spr_en <= io_wdata[0];
                        if (io_wdata[1]) overrun <= 1'b0;
                    end
                    default: ;
                endcase
            end

            // A new line always wins. The margins say one cannot arrive
            // while the last is still running, and a render that hung on
            // a memory which never answered would otherwise take the
            // sprites away for good rather than for a frame.
            // The sweep free-runs against the state machine and shares
            // only the line buffer's write port, which the render cannot
            // reach until S_TALLY has waited for it.
            if (swp_busy) begin
                swp_cnt <= swp_cnt + 7'd1;
                if (swp_cnt[5:0] == 6'd63)
                    swp_base[ln[0]] <= (swp_base[ln[0]] >= 10'd576)
                                       ? 10'd0
                                       : (swp_base[ln[0]] + 10'd64);
            end

            if (start) begin
                swp_cnt <= 7'd0;
                ln     <= frame_start ? 10'd0 : next_line;
                s      <= 5'd0;
                s_q    <= 5'd0;
                nhit   <= 4'd0;
                scan_v <= 1'b0;
                req_r  <= 1'b0;
                st     <= S_SCAN;
            end else begin
                case (st)
                    // ---- one read per descriptor, tested a cycle behind
                    S_SCAN: begin
                        s_q    <= s;
                        scan_v <= 1'b1;
                        if (s != 5'd31) s <= s + 5'd1;

                        if (scan_v) begin
                            if (d_hit) begin
                                if (nhit < 4'd8) begin
                                    hit_s[nhit[2:0]] <= s_q;
                                    hit_y[nhit[2:0]] <= {d_trail, d_size,
                                                         d_dy[3:0]};
                                    nhit <= nhit + 4'd1;
                                end else overrun <= 1'b1;
                            end
                            if (s_q == 5'd31) st <= S_TALLY;
                        end
                    end

                    // `nhit` settles one edge after the last test, and
                    // the sweep owns the write port until it is done.
                    S_TALLY: if (!swp_busy) begin
                        k    <= nhit;
                        pass <= 1'b0;
                        st   <= S_SEL;
                    end

                    // ---- two passes over the list.
                    //
                    // The trailing rows go down **first**, whatever their
                    // descriptor index, so a real sprite can overwrite
                    // them. Doing it in one pass would let a low-numbered
                    // sprite's clear land on a high-numbered sprite's
                    // pixels, which is the opposite of the priority rule.
                    //
                    // Within a pass the order is backwards, so sprite 0
                    // is written last and wins.
                    S_SEL: begin
                        if (k == 4'd0) begin
                            if (!pass) begin
                                pass <= 1'b1;
                                k    <= nhit;
                            end else st <= S_IDLE;
                        end else begin
                            k <= k - 4'd1;
                            if (hit_y[k[2:0] - 3'd1][5] == ~pass) begin
                                trail <= ~pass;
                                yy    <= hit_y[k[2:0] - 3'd1][3:0];
                                big   <= hit_y[k[2:0] - 3'd1][4];
                                daddr <= {hit_s[k[2:0] - 3'd1], 2'b01};
                                st    <= S_D0;
                            end
                        end
                    end

                    // A block RAM answers a cycle late, so the state right
                    // after an address goes out has nothing on the bus
                    // yet. Naming it costs one cycle a sprite and removes
                    // every off-by-one from the three that follow.
                    S_D0: begin
                        daddr <= {daddr[6:2], 2'b10};
                        st    <= S_D1;
                    end

                    S_D1: begin
                        sx    <= {dq[9:8], dq[7:0]};
                        daddr <= {daddr[6:2], 2'b11};
                        st    <= S_D2;
                    end

                    S_D2: begin
                        // Pattern addresses are 32-byte granular, which is
                        // one 8x8 tile of 4 bpp; a 16x16 sprite is four of
                        // them and its rows are eight bytes rather than
                        // four.
                        pat <= {dq[10:8], dq[7:0], 5'b00000};
                        st  <= S_D3;
                    end

                    S_D3: begin
                        // A word is {odd byte, even byte}, so byte 6 is
                        // the low half and byte 7 the high one. Reading
                        // them the other way round gave every sprite the
                        // palette bank's bits as its flips and a bank of
                        // zero — which looks like the background's own
                        // colours coming out of the sprite engine.
                        vflip  <= dq[7];
                        hflip  <= dq[6];
                        behind <= dq[5];
                        pbank  <= dq[11:8];
                        w      <= 3'd0;
                        st     <= S_FW;
                    end

                    S_FW: begin
                        // A trailing row has no pattern to read: it is
                        // sixteen zeros wide and the point of it is that
                        // it costs no VRAM bandwidth to tidy up.
                        if (trail) begin
                            pw <= 16'd0;
                            n  <= 2'd0;
                            st <= S_PUSH;
                        end else if (!req_r) begin
                            req_r <= 1'b1;
                            preq  <= pat +
                                     (big ? {8'd0, row_e, 3'b000}
                                          : {9'd0, row_e[2:0], 2'b00}) +
                                     {13'd0, w[1:0], 1'b0};
                        end
                        if (vr_rvalid) begin
                            pw <= vr_rdata;
                            n  <= 2'd0;
                            st <= S_PUSH;
                        end
                    end

                    // ---- four pixels out, one a cycle
                    S_PUSH: begin
                        n <= n + 2'd1;
                        if (n == 2'd3) begin
                            w  <= w + 3'd1;
                            st <= ((w + 3'd1) < (big ? 3'd4 : 3'd2))
                                  ? S_FW : S_SEL;
                        end
                    end

                    default: st <= S_IDLE;
                endcase
            end
        end
    end

    // ----------------------------------------------------------- reads

    always @* begin
        case (io_a)
            A_IDX:  o_rdata = idx;
            A_CTRL: o_rdata = {6'b000000, overrun, spr_en};
            // SPR_DATA is write-only, as PAL_DATA is: the descriptors'
            // read port is the one the scan uses.
            default: o_rdata = 8'hFF;
        endcase
    end

    wire _unused = &{1'b0, io_rd, dq[12:11], 1'b0};

endmodule

`default_nettype wire
