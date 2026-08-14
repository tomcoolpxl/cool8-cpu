// cool8_video_tb — every mode, every visible pixel, against a model that
// was written from the documents rather than from the RTL.
//
// The engine is parameterised enough that no count can check it. A
// bitmap with the wrong shift, a tile with its palette bank taken from
// the wrong nibble, a text row one glyph line out — each of those still
// produces exactly 307,200 pixels of plausible colour. So the testbench
// carries its own answer: `golden()` computes the colour of pixel (x,y)
// straight from the register values, the memory image and the font, by
// the arithmetic docs/04-system.md section 5 states, and every visible
// pixel of every mode is compared against it.
//
// Written the long way round on purpose. `golden` multiplies where the
// RTL accumulates, it flips a tile by renumbering its pixels where the
// RTL reverses nibbles and swaps words, and it indexes the palette
// through its own copy. Two derivations that agree are evidence; one
// derivation checked against itself is not.
//
// The two clocks are deliberately incommensurate — 10 ns for pixels and
// 21 ns for the system side — because the line buffer and the palette
// between them are the only clock crossings in the design (D26) and a
// testbench that clocked both from one edge would not exercise them.
//
//   vvp cool8_video_tb.vvp +frame=text.hex +which=0
//
// Plusargs:
//   +frame=FILE   the visible pixels of the named phase, 12-bit hex
//   +which=N      which phase to dump (default 0, mode 0 text)
//   +slow         make main RAM grudging, so the text fetch has to wait
//   +vcd=FILE     dump waves

`default_nettype none
`timescale 1ns / 1ps

module cool8_video_tb;

    localparam H_VIS = 640, V_VIS = 480;
    localparam COLS = 80, ROWS = 30;

    reg          pclk = 1'b0;
    reg          sclk = 1'b0;
    reg          rst_n = 1'b0;

    reg  [7:0]   io_a;
    reg          io_rd, io_we;
    reg  [7:0]   io_wdata;
    wire         vid_sel, vid_dp_sel, vid_stall, vid_irq;
    wire [7:0]   vid_rdata, vid_dout;

    wire         ram_req;
    wire [15:0]  ram_addr;
    wire         ram_gnt;
    reg          ram_rvalid;
    reg  [7:0]   ram_rdata;

    wire [11:0]  rgb;
    wire         hsync_n, vsync_n;

    // ---- the memories, and the testbench's own copies of them
    reg  [7:0]   mram [0:65535];       // main RAM: text maps
    reg  [15:0]  vref [0:32767];       // what was put into the SPRAM
    reg  [7:0]   font [0:4095];
    reg  [11:0]  pal_ref [0:255];

    // ---- the mode, mirrored so `golden` needs no hierarchical reference
    reg          g_dis, g_hdbl, g_vdbl, g_curon;
    reg  [1:0]   g_eng, g_bpp, g_cstyle;
    reg  [15:0]  g_base, g_stride, g_pat;
    reg  [10:0]  g_hact, g_hstart;
    reg  [9:0]   g_vact, g_vstart, g_scrx, g_scry;
    reg  [6:0]   g_curx;
    reg  [4:0]   g_cury;
    reg  [7:0]   g_clines, g_border;

    // ---- the sprites, mirrored the same way the modes are
    reg          sp_en  [0:31];
    reg          sp_big [0:31];
    reg          sp_hf  [0:31];
    reg          sp_vf  [0:31];
    reg          sp_bh  [0:31];
    reg  [9:0]   sp_x   [0:31];
    reg  [9:0]   sp_y   [0:31];
    reg  [15:0]  sp_pat [0:31];
    // Still written into descriptor byte 7 and deliberately *not* read by
    // the model: every sprite takes its palette bank from SPR_CTRL[7:4]
    // now, and leaving the per-sprite field in the stimulus is what
    // proves the hardware ignores it.
    reg  [3:0]   sp_bank[0:31];
    reg  [3:0]   g_sbank;              // SPR_CTRL[7:4], shared by all

    integer      i, j, k, fh, pixels, checks, fails, phase, dump_which;
    integer      from_phase, to_phase;
    reg          dumping, armed, slow, spr_on;
    reg  [1023:0] vcdfile, framefile;
    reg  [15:0]  screen [0:COLS*ROWS-1];
    reg  [11:0]  got, want;
    reg  [31:0]  lfsr;

    always #5    pclk = ~pclk;
    always #10.5 sclk = ~sclk;

    cool8_video #(.FONT_FILE("font.hex")) u_vid (
        .sclk(sclk), .srst_n(rst_n),
        .pclk(pclk), .prst_n(rst_n),
        // Asked for, and accepted — see cool8_soc for why a write needs
        // both and cool8_vport for what goes wrong with one.
        .io_a(io_a), .io_rd(io_rd),
        .io_wreq(io_we), .io_we(io_we & ~vid_stall), .io_wdata(io_wdata),
        .o_sel(vid_sel), .o_dp_sel(vid_dp_sel), .o_rdata(vid_rdata),
        .o_dout(vid_dout), .o_stall(vid_stall),
        .ram_req(ram_req), .ram_addr(ram_addr),
        .ram_gnt(ram_gnt), .ram_rvalid(ram_rvalid), .ram_rdata(ram_rdata),
        .rgb(rgb), .hsync_n(hsync_n), .vsync_n(vsync_n),
        .o_irq(vid_irq)
    );

    // -------------------------------------------------------- main RAM
    //
    // Grants on the cycle it is asked and answers on the next, which is
    // what cool8_soc's arbiter does when nothing else wants the memory.
    // `+slow` makes it refuse at random instead, so the fetch has to
    // cope with the CPU actually using its own memory.

    // The grant is combinational, exactly as `vid_start & mem_launch` is
    // in cool8_soc. A registered grant would stay asserted for a second
    // cycle after the request dropped and hand the fetch engine two
    // answers to one question — which is how the first version of this
    // model made every text cell read its own low byte twice.
    assign ram_gnt = ram_req & (!slow | lfsr[24]);

    always @(posedge sclk) begin
        lfsr <= {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
        ram_rvalid <= ram_gnt;
        if (ram_gnt) ram_rdata <= mram[ram_addr];
    end

    // -------------------------------------------------------- the tasks

    task io_wr;
        input [7:0] a;
        input [7:0] d;
        begin
            @(posedge sclk);
            io_a <= a; io_wdata <= d; io_we <= 1'b1;
            @(posedge sclk);
            io_we <= 1'b0;
        end
    endtask

    task vram_put;                     // word address, 0..32767
        input [14:0] wa;
        input [15:0] d;
        begin
            vref[wa] = d;
            if (wa[14]) u_vid.u_vram.u_hi.mem[wa[13:0]] = d;
            else        u_vid.u_vram.u_lo.mem[wa[13:0]] = d;
        end
    endtask

    task put_pal;
        input [7:0] e;
        input [3:0] pr, pg, pb;
        begin
            pal_ref[e] = {pr, pg, pb};
            io_wr(8'h1E, e);
            io_wr(8'h1F, {4'h0, pr});
            io_wr(8'h1F, {pg, pb});
        end
    endtask

    task set_mode;                     // preset, then mirror what it loaded
        input [3:0] m;
        begin
            io_wr(8'h10, {1'b1, 3'b000, m});
            g_dis = 1'b1;
            case (m)
                // 160, as cool8_vregs.v's presets say. **This is a
                // second copy of that table** and it went stale the
                // moment the text map stopped being 256 bytes a row --
                // 426,520 pixels wrong, from a testbench filling a map
                // the hardware no longer reads that way.
                4'd0: begin g_eng=0; g_bpp=0; g_hdbl=0; g_vdbl=0;
                            g_base=16'h9800; g_stride=160; g_vact=480; end
                4'd1: begin g_eng=0; g_bpp=0; g_hdbl=1; g_vdbl=0;
                            g_base=16'h9800; g_stride=160; g_vact=480; end
                4'd2: begin g_eng=1; g_bpp=2; g_hdbl=1; g_vdbl=1;
                            g_base=16'h0000; g_stride=128; g_vact=480; end
                4'd3: begin g_eng=2; g_bpp=0; g_hdbl=0; g_vdbl=0;
                            g_base=16'h0000; g_stride=80;  g_vact=480; end
                4'd4: begin g_eng=2; g_bpp=2; g_hdbl=1; g_vdbl=1;
                            g_base=16'h0000; g_stride=160; g_vact=480; end
                4'd5: begin g_eng=2; g_bpp=2; g_hdbl=1; g_vdbl=1;
                            g_base=16'h0000; g_stride=128; g_vact=384; end
                default: begin g_eng=2; g_bpp=3; g_hdbl=1; g_vdbl=1;
                            g_base=16'h0000; g_stride=256; g_vact=480; end
            endcase
            derive;
        end
    endtask

    // The three values section 4.2 derives rather than stores, computed
    // here the way that section words them.
    task derive;
        reg [10:0] hdisp, imgw;
        begin
            hdisp = g_hdbl ? 11'd320 : 11'd640;
            imgw  = (g_eng != 2) ? hdisp : (g_stride << (3 - g_bpp));
            g_hact   = (imgw < hdisp) ? imgw : hdisp;
            g_hstart = (imgw < hdisp) ? ((hdisp - imgw) >> 1) : 11'd0;
            g_vstart = (10'd480 - g_vact) >> 1;
        end
    endtask

    task set_base;
        input [15:0] v;
        begin
            g_base = v; derive;
            io_wr(8'h12, v[7:0]); io_wr(8'h13, v[15:8]);
        end
    endtask

    task set_stride;
        input [15:0] v;
        begin
            g_stride = v; derive;
            io_wr(8'h14, v[7:0]); io_wr(8'h15, v[15:8]);
        end
    endtask

    task set_scroll;
        input [9:0] sxv, syv;
        begin
            g_scrx = sxv; g_scry = syv;
            io_wr(8'h16, sxv[7:0]); io_wr(8'h17, {6'd0, sxv[9:8]});
            io_wr(8'h18, syv[7:0]); io_wr(8'h19, {6'd0, syv[9:8]});
        end
    endtask

    task set_cursor;
        input [6:0] cx;
        input [4:0] cy;
        input [1:0] style;
        input [7:0] lines;
        begin
            g_curx = cx; g_cury = cy; g_cstyle = style; g_clines = lines;
            g_curon = 1'b1;
            io_wr(8'h22, {1'b0, cx});
            io_wr(8'h23, {3'b000, cy});
            // $25 (CUR_LINES) and the style field are gone with the
            // style mux; rate 3 is still the solid cursor, which is the
            // one a testbench can predict without a frame counter.
            io_wr(8'h24, {2'b11, 2'b00, 1'b1});
        end
    endtask

    task put_spr;
        input [4:0]  ii;
        input        en, big, hf, vf, bh;
        input [9:0]  xx, yy;
        input [15:0] pp;
        input [3:0]  bk;
        begin
            sp_en[ii]=en; sp_big[ii]=big; sp_hf[ii]=hf; sp_vf[ii]=vf;
            sp_bh[ii]=bh; sp_x[ii]=xx; sp_y[ii]=yy; sp_pat[ii]=pp;
            sp_bank[ii]=bk;
            io_wr(8'h2A, {ii, 3'b000});
            io_wr(8'h2B, yy[7:0]);
            io_wr(8'h2B, {big, en, 5'b00000, yy[8]});
            io_wr(8'h2B, xx[7:0]);
            io_wr(8'h2B, {6'b000000, xx[9:8]});
            io_wr(8'h2B, pp[12:5]);
            io_wr(8'h2B, {5'b00000, pp[15:13]});
            io_wr(8'h2B, {vf, hf, bh, 5'b00000});
            io_wr(8'h2B, {4'b0000, bk});
        end
    endtask

    task no_sprites;
        integer q;
        begin
            for (q = 0; q < 32; q = q + 1)
                put_spr(q[4:0], 1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                        10'd0, 10'd0, 16'd0, 4'd0);
            io_wr(8'h2C, 8'h00);
            spr_on  = 1'b0;
            g_sbank = 4'd0;
        end
    endtask

    // ------------------------------------------------------ the model

    // A text or tile map row, wrapped within the map.
    //
    // **This was the mask** -- `(g_base & ~m) | ((g_base + r*stride) & m)`
    // with `m = stride*32 - 1` -- which is a third copy of the formula
    // cool8_fetch.v used, and it stopped being right for the same
    // reason: a mask can only derive the map's origin when the map is
    // aligned to a power-of-two size. The origin is a register in the
    // hardware now, and here it is `g_base`, which this bench never
    // scrolls -- so the wrap is a compare and a subtract, and for r < 32
    // it never fires.
    function [15:0] row_addr;
        input [9:0] r;
        reg [15:0] span, off;
        begin
            span = g_stride << 5;
            off  = r * g_stride;
            row_addr = g_base + ((off >= span) ? off - span : off);
        end
    endfunction

    function [11:0] golden;
        input [9:0] gx, gy;
        reg [10:0] xl, rel, sx;
        reg [9:0]  vrel, vlog, vsrc;
        reg [7:0]  idx, at, fb, pixv;
        reg [15:0] cw, ent, w, ra, pa;
        reg [15:0] ps;
        reg [3:0]  grow;
        reg [2:0]  sub, p;
        reg        curhit, lit;
        reg [9:0]  sh, sdy, sdx, srow, scol;
        reg [15:0] spa, sw, sps, spx;
        reg [7:0]  sidx;
        reg        sbh, sfnd;
        integer    bpp, ppw, kk, si, sn;
        begin
            xl   = g_hdbl ? (gx >> 1) : gx;
            rel  = xl - g_hstart;
            vrel = gy - g_vstart;
            vlog = g_vdbl ? (vrel >> 1) : vrel;
            idx  = 8'h00;

            if (!g_dis || (xl < g_hstart) || (rel >= g_hact) ||
                (gy < g_vstart) || (vrel >= g_vact)) begin
                idx = g_border;
            end else if (g_eng == 2'd0) begin
                // ---- text: a cw is two bytes of main RAM
                vsrc = vrel + (g_scry & 10'd15);
                grow = vsrc[3:0];
                ra   = row_addr(vsrc >> 4);
                cw = {mram[ra + (rel >> 3) * 2 + 1],
                        mram[ra + (rel >> 3) * 2]};
                at   = cw[15:8];
                fb   = font[{cw[7:0], grow}];
                lit  = fb[3'd7 - rel[2:0]];
                // **One cursor, and it inverts the palette index.**
                // The four styles and CUR_LINES are gone: the cursor is
                // applied to the finished index in cool8_pixel.v, which
                // is what let it cover the tile and bitmap modes as
                // well, and a block that inverts its cell is the only
                // style the editor ever asked for.
                curhit = g_curon && ((rel >> 3) == {4'd0, g_curx}) &&
                         ((vsrc >> 4) == {5'd0, g_cury});
                idx = lit ? {4'h0, at[3:0]} : {4'h0, at[7:4]};
                if (curhit) idx = idx ^ 8'h0F;
            end else if (g_eng == 2'd1) begin
                // ---- tile: map entry, then the pattern row it names
                vsrc = vlog + (g_scry & 10'd7);
                ra   = row_addr(vsrc >> 3);
                sx   = rel + (g_scrx & 11'd7);
                ent  = vref[(ra >> 1) + (sx >> 3)];
                at   = ent[15:8];
                // The flip is a renumbering here, where the RTL reverses
                // nibbles and swaps the pair.
                sub  = sx[2:0];
                p    = at[6] ? (3'd7 - sub) : sub;
                pa   = g_pat + (at[5:4] << 13) + (ent[7:0] << 5) +
                       ((at[7] ? (3'd7 - vsrc[2:0]) : vsrc[2:0]) << 2);
                w    = vref[(pa >> 1) + {14'd0, p[2]}];
                ps   = {w[7:0], w[15:8]};
                pixv = (ps >> (12 - {p[1:0], 2'b00})) & 16'h000F;
                idx  = {at[3:0], pixv[3:0]};
            end else begin
                // ---- bitmap: the row pitch is the row
                bpp = 1 << g_bpp;
                ppw = 16 / bpp;
                ra  = g_base + vlog * g_stride;
                sx  = rel + {1'b0, g_scrx};
                w   = vref[(ra >> 1) + (sx / ppw)];
                ps  = {w[7:0], w[15:8]};
                kk  = sx % ppw;
                pixv = (ps >> (16 - bpp - kk * bpp)) &
                       ((bpp == 8) ? 16'h00FF : ((1 << bpp) - 1));
                idx = pixv;
            end

            // ---- the sprites, over whatever the background produced
            //
            // The rule is the one section 5.6 states: among the first
            // eight descriptors that touch this line, in index order, the
            // lowest-numbered one whose pixel is not colour zero wins.
            // The RTL gets there by rendering backwards and letting the
            // last write stand; this gets there by looking.
            if (spr_on) begin
                sn   = 0;
                sfnd = 1'b0;
                sidx = 8'h00;
                sbh  = 1'b0;
                for (si = 0; si < 32; si = si + 1) begin
                    sh  = sp_big[si] ? 10'd16 : 10'd8;
                    sdy = (gy - sp_y[si]) & 10'h3FF;
                    // Two lines past the bottom a sprite is still in the
                    // list, spending one of the eight slots to write the
                    // zeros that tidy its span away — but drawing
                    // nothing.
                    if (sp_en[si] && (sdy < sh + 10'd2) && (sn < 8)) begin
                        sn  = sn + 1;
                        sdx = (gx - sp_x[si]) & 10'h3FF;
                        if (!sfnd && (sdy < sh) && (sdx < sh)) begin
                            srow = sp_vf[si] ? (sh - 10'd1 - sdy) : sdy;
                            scol = sp_hf[si] ? (sh - 10'd1 - sdx) : sdx;
                            spa  = sp_pat[si] + srow * (sh >> 1);
                            sw   = vref[(spa >> 1) + (scol >> 2)];
                            sps  = {sw[7:0], sw[15:8]};
                            spx  = (sps >> (12 - {scol[1:0], 2'b00})) &
                                   16'h000F;
                            if (spx != 16'd0) begin
                                sfnd = 1'b1;
                                sidx = {g_sbank, spx[3:0]};
                                sbh  = sp_bh[si];
                            end
                        end
                    end
                end
                if (sfnd && (!sbh || (idx == 8'h00))) idx = sidx;
            end

            golden = pal_ref[idx];
        end
    endfunction

    // --------------------------------------------------------- checking

    // `+from=N` and `+to=M` select a range of phases, and a phase outside
    // it costs **nothing**: its set-up still runs, because later phases
    // build on the registers and memory earlier ones wrote, but the three
    // frames of raster do not.
    //
    // That is where the minutes were. Every phase is three frames — two to
    // let a mode change settle and one to compare — and at 420,000 pixel
    // clocks a frame in an interpreted simulator, sixteen phases is twenty
    // million edges whether anyone is looking at them or not. `+from`
    // used to skip only the per-pixel comparison and simulate the frames
    // regardless, so selecting one phase saved almost nothing.
    //
    // With the frames skipped as well, a single phase runs in about the
    // time one phase deserves, and sim/test_video.py runs all sixteen as
    // separate processes at once.
    task run_frame;
        input [8*24-1:0] name;
        input integer    id;
        integer          n;
        begin
            phase = id;
            if ((id < from_phase) || (id > to_phase)) begin
                $display("  %0s: skipped", name);
            end else begin
                // Two frame boundaries: the first lets a mode change
                // settle, the second is the one that gets looked at.
                // **`armed` goes up after them, not before** — arming
                // early compares the settling frames as well, which is
                // 307,200 extra checks against a picture that is still
                // half the previous mode.
                @(posedge u_vid.u_vga.o_vblank_start);
                @(posedge u_vid.u_vga.o_vblank_start);
                pixels = 0;
                armed  = 1'b1;
                n = fails;
                while (pixels < H_VIS * V_VIS) @(posedge pclk);
                armed = 1'b0;
                $display("  %0s: %0d pixels, %0d failures", name,
                         pixels, fails - n);
            end
        end
    endtask

    always @(posedge pclk) begin
        if (armed && u_vid.visible && pixels < H_VIS * V_VIS) begin
            got  = rgb;
            want = golden(u_vid.x, u_vid.y);
            checks = checks + 1;
            if (got !== want) begin
                if (fails < 20)
                    $display("FAIL phase %0d (%0d,%0d): got %03h want %03h",
                             phase, u_vid.x, u_vid.y, got, want);
                fails = fails + 1;
            end
            if (dumping && phase == dump_which)
                $fwrite(fh, "%03h\n", rgb);
            pixels = pixels + 1;
        end
    end

    // ------------------------------------------------------- the screen
    //
    // The same screen cool8_text_tb built, so the picture this produces
    // is the picture docs/img/text-mode-0.png already holds — which
    // makes it the check that the general engine reproduces the
    // special-purpose one it replaced, pixel for pixel.

    task put_str;
        input integer row;
        input integer col;
        input [8*72-1:0] s;
        input [7:0] attr;
        integer m, n;
        reg [7:0] ch;
        begin
            n = 0;
            for (m = 71; m >= 0; m = m - 1) begin
                ch = s[m*8 +: 8];
                if (ch != 8'h00) begin
                    if (col + n < COLS)
                        screen[row * COLS + col + n] = {attr, ch};
                    n = n + 1;
                end
            end
        end
    endtask

    task build_screen;
        begin
            for (k = 0; k < COLS * ROWS; k = k + 1)
                screen[k] = 16'h0720;

            screen[0 * COLS + 0] = 16'h0FC9;
            screen[0 * COLS + (COLS-1)] = 16'h0FBB;
            screen[4 * COLS + 0] = 16'h0FC8;
            screen[4 * COLS + (COLS-1)] = 16'h0FBC;
            for (k = 1; k < COLS - 1; k = k + 1) begin
                screen[0 * COLS + k] = 16'h0FCD;
                screen[4 * COLS + k] = 16'h0FCD;
            end
            for (k = 1; k < 4; k = k + 1) begin
                screen[k * COLS + 0] = 16'h0FBA;
                screen[k * COLS + (COLS-1)] = 16'h0FBA;
            end

            put_str(1, 3, "COOL8", 8'h0E);
            put_str(1, 9, "text mode 0 - 80x30 cells of 8x16", 8'h0B);
            put_str(2, 3, "the font is real, the raster is real,", 8'h07);
            put_str(3, 3, "and this frame came out of a simulator", 8'h08);

            for (k = 0; k < 16; k = k + 1)
                for (j = 0; j < 4; j = j + 1)
                    screen[6 * COLS + 3 + k * 4 + j] =
                        {4'h0, k[3:0], 8'hDB};
            for (k = 0; k < 16; k = k + 1)
                for (j = 0; j < 4; j = j + 1)
                    screen[7 * COLS + 3 + k * 4 + j] =
                        {k[3:0], 4'h0, 8'h20};

            for (k = 0; k < 256; k = k + 1)
                screen[(10 + k / 16) * COLS + 3 + (k % 16) * 3] =
                    {8'h0A, k[7:0]};

            for (k = 0; k < 64; k = k + 1) begin
                screen[27 * COLS + 8 + k] = {4'h0, k[5:2], 8'hDB};
                screen[28 * COLS + 8 + k] =
                    {4'h0, k[5:2], (k[1:0] == 0) ? 8'hB0 :
                                   (k[1:0] == 1) ? 8'hB1 :
                                   (k[1:0] == 2) ? 8'hB2 : 8'hDB};
            end
        end
    endtask

    // The map is 128 cells wide (stride 256) with 80 shown, which is D30's
    // canonical shape — so a row of the screen is not a row of the map.
    task load_text_map;
        begin
            for (k = 0; k < 65536; k = k + 1) mram[k] = 8'h00;
            for (j = 0; j < ROWS; j = j + 1)
                for (k = 0; k < COLS; k = k + 1) begin
                    mram[16'h9800 + j * 160 + k * 2]     =
                        screen[j * COLS + k][7:0];
                    mram[16'h9800 + j * 160 + k * 2 + 1] =
                        screen[j * COLS + k][15:8];
                end
        end
    endtask

    // ==================================================================

    initial begin
        io_a = 8'h00; io_rd = 1'b0; io_we = 1'b0; io_wdata = 8'h00;
        ram_rvalid = 1'b0; ram_rdata = 8'h00;
        armed = 1'b0; pixels = 0; checks = 0; fails = 0; phase = 0;
        lfsr = 32'hACE1_2345;
        g_scrx = 0; g_scry = 0; g_border = 8'h00; g_pat = 16'h0000;
        g_curon = 1'b0; g_curx = 0; g_cury = 0; g_cstyle = 0;
        g_clines = 8'hF0; spr_on = 1'b0; g_sbank = 4'd0;
        for (k = 0; k < 32; k = k + 1) begin
            sp_en[k]=1'b0; sp_big[k]=1'b0; sp_hf[k]=1'b0;
            sp_vf[k]=1'b0; sp_bh[k]=1'b0;
            sp_x[k]=10'd0; sp_y[k]=10'd0; sp_pat[k]=16'd0;
            sp_bank[k]=4'd0;
        end

        slow = $test$plusargs("slow");
        dumping = $value$plusargs("frame=%s", framefile);
        if (!$value$plusargs("which=%d", dump_which)) dump_which = 0;
        if (!$value$plusargs("from=%d", from_phase)) from_phase = 0;
        if (!$value$plusargs("to=%d", to_phase))     to_phase = 999;
        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_video_tb);
        end

        $readmemh("font.hex", font);
        // The sprite line buffer is EBR and EBR is initialised from the
        // bitstream, so on the board it starts at zero. SPRAM does not
        // and is deliberately left undefined here, which is why the two
        // are set up differently.
        for (k = 0; k < 2048; k = k + 1) u_vid.u_pixel.sb[k] = 14'd0;
        for (k = 0; k < 128;  k = k + 1) u_vid.u_spr.desc[k]  = 16'd0;
        for (k = 0; k < 32768; k = k + 1) vref[k] = 16'h0000;
        for (k = 0; k < 256; k = k + 1) pal_ref[k] = 12'h000;

        build_screen;
        load_text_map;

        repeat (4) @(posedge pclk);
        rst_n = 1'b1;
        repeat (8) @(posedge sclk);

        if (dumping) fh = $fopen(framefile, "w");

        // The sixteen CGA colours in the low entries, and a ramp above
        // them so the deeper modes have something to be wrong about.
        put_pal(8'h00, 4'h0, 4'h0, 4'h0);  put_pal(8'h01, 4'h0, 4'h0, 4'hA);
        put_pal(8'h02, 4'h0, 4'hA, 4'h0);  put_pal(8'h03, 4'h0, 4'hA, 4'hA);
        put_pal(8'h04, 4'hA, 4'h0, 4'h0);  put_pal(8'h05, 4'hA, 4'h0, 4'hA);
        put_pal(8'h06, 4'hA, 4'h5, 4'h0);  put_pal(8'h07, 4'hA, 4'hA, 4'hA);
        put_pal(8'h08, 4'h5, 4'h5, 4'h5);  put_pal(8'h09, 4'h5, 4'h5, 4'hF);
        put_pal(8'h0A, 4'h5, 4'hF, 4'h5);  put_pal(8'h0B, 4'h5, 4'hF, 4'hF);
        put_pal(8'h0C, 4'hF, 4'h5, 4'h5);  put_pal(8'h0D, 4'hF, 4'h5, 4'hF);
        put_pal(8'h0E, 4'hF, 4'hF, 4'h5);  put_pal(8'h0F, 4'hF, 4'hF, 4'hF);
        for (k = 16; k < 256; k = k + 1)
            put_pal(k[7:0], k[3:0], k[7:4], k[5:2] ^ 4'h9);

        // ------------------------------------------------ mode 0, text
        set_mode(4'd0);
        run_frame("text 80x30", 0);

        // ...and again with the CPU fighting for main RAM.
        slow = 1'b1;
        run_frame("text, RAM busy", 1);
        slow = $test$plusargs("slow");

        // ---------------------------------------- mode 0, scrolled, cursor
        set_scroll(10'd0, 10'd5);
        set_cursor(7'd13, 5'd4, 2'd0, 8'hF0);
        run_frame("text, scrolled", 2);
        // There is one cursor style now -- the block that inverts its
        // cell -- so what these two phases vary is where it is, not what
        // it looks like. They were "underline" and "inverse" while
        // CUR_CTRL had a style field and CUR_LINES existed.
        set_cursor(7'd40, 5'd12, 2'd0, 8'hEC);
        run_frame("text, cursor mid-screen", 3);
        set_cursor(7'd7, 5'd9, 2'd0, 8'hF0);
        run_frame("text, cursor low", 4);
        g_curon = 1'b0; io_wr(8'h24, 8'h00);
        set_scroll(10'd0, 10'd0);

        // ------------------------------------------------ mode 1, 40x30
        set_mode(4'd1);
        run_frame("text 40x30", 5);

        // --------------------------------------------- the bitmap modes
        for (k = 0; k < 32768; k = k + 1)
            vram_put(k[14:0], {k[7:0] ^ 8'h5A, k[15:8] + 8'h37});

        io_wr(8'h1A, 8'h2B);  g_border = 8'h2B;

        set_mode(4'd3);  run_frame("bitmap 1 bpp 640", 6);
        set_mode(4'd4);  run_frame("bitmap 4 bpp 320", 7);
        set_mode(4'd5);  run_frame("bitmap 4 bpp bordered", 8);
        set_mode(4'd6);  run_frame("bitmap 8 bpp", 9);

        // Scrolled, and with a base that is not zero — the two things
        // that move the row pointer.
        // A bitmap scrolls horizontally into a row pitch wider than the
        // screen � 256 bytes is 512 pixels at 4 bpp against 320 shown �
        // which is what section 5.5 means by moving the base. Scrolling
        // past the end of the row is not a mode, it is a bug in software.
        set_mode(4'd4);
        set_base(16'h1000);
        set_stride(16'd256);
        set_scroll(10'd37, 10'd0);
        run_frame("bitmap, scrolled", 10);
        set_scroll(10'd0, 10'd0);
        set_base(16'h0000);

        // ------------------------------------------------- mode 2, tiles
        set_mode(4'd2);
        io_wr(8'h20, 8'h00); io_wr(8'h21, 8'h40);   // patterns at $4000
        g_pat = 16'h4000;
        // A map of 64 columns at stride 128, every attribute combination
        // among them, and patterns that are not symmetric so a flip that
        // does nothing is visible.
        for (j = 0; j < 32; j = j + 1)
            for (k = 0; k < 64; k = k + 1)
                vram_put((j * 128 + k * 2) >> 1,
                         {j[3:0] ^ k[3:0], k[5:0] + j[5:0], 2'b00} ^
                         {k[7:0], j[7:0]});
        for (k = 0; k < 4096; k = k + 1)
            vram_put(15'h2000 + k[14:0], {k[3:0], k[11:4] ^ 8'h6D, k[7:4]});
        run_frame("tiles 40x30", 11);
        set_scroll(10'd5, 10'd3);
        run_frame("tiles, scrolled", 12);

        // ------------------------------------------------ the sprites
        //
        // Patterns at $6000, with every one asymmetric in both
        // directions: a flip taken from the wrong bit, or a row index
        // that does not follow it, then shows up as a wrong pixel rather
        // than as a symmetry nobody notices.
        for (k = 0; k < 2048; k = k + 1)
            vram_put(15'h3000 + k[14:0],
                     {k[3:0] + 4'd1, k[7:4] ^ 4'h6, k[11:8] + 4'd3,
                      k[5:2] ^ 4'hA});

        set_mode(4'd4);
        set_base(16'h0000);
        // The tile phase left a fine scroll set, and five pixels of it
        // pushes the right-hand edge of a 160-byte row past the end of
        // the row — which is out of spec for a bitmap (section 5.5) and
        // has nothing to do with sprites.
        set_scroll(10'd0, 10'd0);
        // Bank $5 rather than $0, so the shared bank is actually carried
        // rather than passing by being zero. Every descriptor below still
        // sets a *different* per-sprite bank, and none of them shows.
        io_wr(8'h2C, {4'h5, 4'h1});
        spr_on  = 1'b1;
        g_sbank = 4'h5;

        // Eight on a line, overlapping in pairs so priority shows, both
        // sizes, every flip, and two behind the background.
        put_spr(5'd0,  1'b1, 1'b1, 1'b0, 1'b0, 1'b0,
                10'd40,  10'd60,  16'h6000, 4'h1);
        put_spr(5'd1,  1'b1, 1'b1, 1'b1, 1'b0, 1'b0,
                10'd48,  10'd60,  16'h6080, 4'h2);
        put_spr(5'd2,  1'b1, 1'b1, 1'b0, 1'b1, 1'b0,
                10'd100, 10'd60,  16'h6100, 4'h3);
        put_spr(5'd3,  1'b1, 1'b1, 1'b1, 1'b1, 1'b1,
                10'd108, 10'd60,  16'h6180, 4'h4);
        put_spr(5'd4,  1'b1, 1'b0, 1'b0, 1'b0, 1'b0,
                10'd200, 10'd62,  16'h6200, 4'h5);
        put_spr(5'd5,  1'b1, 1'b0, 1'b1, 1'b0, 1'b0,
                10'd204, 10'd62,  16'h6220, 4'h6);
        put_spr(5'd6,  1'b1, 1'b0, 1'b0, 1'b1, 1'b1,
                10'd300, 10'd64,  16'h6240, 4'h7);
        put_spr(5'd7,  1'b1, 1'b1, 1'b0, 1'b0, 1'b0,
                10'd400, 10'd58,  16'h6260, 4'h8);
        // Wrapped round the left edge, hanging off the right, and off
        // the bottom of the screen.
        put_spr(5'd8,  1'b1, 1'b1, 1'b0, 1'b0, 1'b0,
                10'd1016, 10'd200, 16'h6300, 4'h9);
        put_spr(5'd9,  1'b1, 1'b1, 1'b0, 1'b0, 1'b0,
                10'd632,  10'd200, 16'h6380, 4'hA);
        put_spr(5'd10, 1'b1, 1'b1, 1'b0, 1'b0, 1'b0,
                10'd300,  10'd472, 16'h6400, 4'hB);
        run_frame("sprites over a bitmap", 13);

        // A ninth and a tenth on one line: the ones past eight are
        // dropped, in descriptor order, and the model drops the same ones.
        //
        // They start *inside* the crowded band rather than above it, so
        // they are dropped from their first line onwards. A sprite drawn
        // on one line and dropped on the next leaves its last row in the
        // buffer until something overwrites it — real behaviour, flagged
        // by SPR_CTRL bit 1, and not something the model reproduces
        // because the model has no memory of previous lines.
        put_spr(5'd11, 1'b1, 1'b0, 1'b0, 1'b0, 1'b0,
                10'd60,  10'd64, 16'h6480, 4'hC);
        put_spr(5'd12, 1'b1, 1'b0, 1'b0, 1'b0, 1'b0,
                10'd80,  10'd64, 16'h6500, 4'hD);
        run_frame("sprites, ten on a line", 14);

        // The same sprites over text, which is a different background
        // engine and a different memory entirely.
        set_mode(4'd0);
        run_frame("sprites over text", 15);

        no_sprites;

        if (dumping) $fclose(fh);
        repeat (10) @(posedge pclk);

        $display("  %0d checks, %0d failures", checks, fails);
        if (fails == 0) $display("\nPASS");
        else            $display("\nFAIL");
        $finish;
    end

    initial begin
        #900000000;
        $display("FAIL: timed out");
        $display("\nFAIL");
        $finish;
    end

endmodule

`default_nettype wire
