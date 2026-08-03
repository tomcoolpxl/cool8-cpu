// cool8_vga_tb — the raster, against a model of a raster, every pixel.
//
// A timing generator is small enough that there is no reason to sample
// it: this runs a golden model of the same raster beside it and compares
// **every output on every one of 840,000 pixel clocks**, two whole
// frames. Anything that is off by one anywhere fails immediately and
// says where.
//
// It also writes the visible pixels of one frame out as a test pattern,
// which sim/test_video.py turns into a PNG. A count is a count; a
// picture with a border and a diagonal in it is the thing you can hold
// against a monitor later. Until the VGA PMOD exists that image is the
// only way to actually look at what this produces, and it stays useful
// afterwards as the reference the hardware has to match.
//
//   vvp cool8_vga_tb.vvp +frame=frame.hex
//
// Plusargs:
//   +frame=FILE   write the visible pixels of frame 1 here, 12-bit hex
//   +vcd=FILE     dump waves
//   +verbose      print the per-frame tallies

`default_nettype none
`timescale 1ns / 1ps

module cool8_vga_tb;

    localparam H_VIS = 640, H_FP = 16, H_SYNC = 96, H_BP = 48;
    localparam V_VIS = 480, V_FP = 10, V_SYNC = 2,  V_BP = 33;
    localparam H_TOTAL = H_VIS + H_FP + H_SYNC + H_BP;   // 800
    localparam V_TOTAL = V_VIS + V_FP + V_SYNC + V_BP;   // 525
    localparam FRAME = H_TOTAL * V_TOTAL;                // 420000

    reg          clk = 1'b0;
    reg          rst_n = 1'b0;

    integer      errors, checks, i, fh, frames;
    reg          verbose, dumping;
    reg [1023:0] vcdfile, framefile;

    // The golden raster.
    integer      gh, gv;
    integer      g_vis, g_hs, g_vs, g_pre, g_vbs;
    integer      n_vis, n_hs, n_vs, n_pre, n_vbs;
    integer      exp_pre_y;

    wire [9:0]   x, y;
    wire         visible, hsync_n, vsync_n, vblank;
    wire         o_prefetch, o_vblank_start;
    wire [9:0]   o_prefetch_y;

    reg [11:0]   rgb;

    always #5 clk = ~clk;

    cool8_vga #(
        .H_VIS(H_VIS), .H_FP(H_FP), .H_SYNC(H_SYNC), .H_BP(H_BP),
        .V_VIS(V_VIS), .V_FP(V_FP), .V_SYNC(V_SYNC), .V_BP(V_BP)
    ) u_vga (
        .clk(clk), .rst_n(rst_n),
        .x(x), .y(y), .visible(visible),
        .hsync_n(hsync_n), .vsync_n(vsync_n), .vblank(vblank),
        .o_prefetch(o_prefetch), .o_prefetch_y(o_prefetch_y),
        .o_vblank_start(o_vblank_start)
    );

    // ------------------------------------------------------ the pattern
    //
    // Chosen so that any timing error is visible rather than merely
    // detectable: a one-pixel border pins all four edges, a diagonal
    // shears if a line is the wrong length, and the ramps make a
    // shifted window obvious at a glance.

    function [11:0] pattern;
        input [9:0] px;
        input [9:0] py;
        begin
            if (px == 0 || py == 0 || px == H_VIS - 1 || py == V_VIS - 1)
                pattern = 12'hFFF;                       // white border
            else if (px[8:0] == py[8:0])
                pattern = 12'hF0F;                       // magenta diagonal
            else
                pattern = {px[9:6], py[8:5], ~px[9:6]};  // ramps
        end
    endfunction

    task chk;
        input [511:0] name;
        input [31:0] got;
        input [31:0] exp;
        begin
            checks = checks + 1;
            if (got !== exp) begin
                errors = errors + 1;
                if (errors < 12)
                    $display("FAIL %0s at (%0d,%0d): got %0d, expected %0d",
                             name, gh, gv, got, exp);
            end
        end
    endtask

    // ==================================================================

    initial begin
        errors = 0;
        checks = 0;
        frames = 0;
        n_vis = 0; n_hs = 0; n_vs = 0; n_pre = 0; n_vbs = 0;
        verbose = $test$plusargs("verbose");
        dumping = $value$plusargs("frame=%s", framefile);

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_vga_tb);
        end

        fh = 0;
        if (dumping) fh = $fopen(framefile, "w");

        repeat (4) @(posedge clk);
        rst_n = 1'b1;

        // The first edge out of reset is pixel (0,0); the golden model
        // starts there too. Everything is sampled on the falling edge,
        // where the outputs of the rising one have settled — reading
        // them in the same delta as the edge that produces them is a
        // race, and it reads as an off-by-one on every signal at once.
        @(posedge clk);
        gh = 0;
        gv = 0;

        for (i = 0; i < 2 * FRAME; i = i + 1) begin
            @(negedge clk);

            // --- what the model says this pixel is
            g_vis = (gh < H_VIS) && (gv < V_VIS);
            g_hs  = (gh >= H_VIS + H_FP) && (gh < H_VIS + H_FP + H_SYNC);
            g_vs  = (gv >= V_VIS + V_FP) && (gv < V_VIS + V_FP + V_SYNC);
            g_pre = (gh == H_VIS);
            g_vbs = (gh == 0) && (gv == V_VIS);
            exp_pre_y = (gv == V_TOTAL - 1) ? 0 : gv + 1;

            // --- and what the RTL says
            chk("x", {22'd0, x}, gh[31:0]);
            chk("y", {22'd0, y}, gv[31:0]);
            chk("visible", {31'd0, visible}, g_vis[31:0]);
            chk("hsync_n", {31'd0, hsync_n}, {31'd0, ~g_hs[0]});
            chk("vsync_n", {31'd0, vsync_n}, {31'd0, ~g_vs[0]});
            chk("vblank", {31'd0, vblank}, {31'd0, (gv >= V_VIS)});
            chk("o_prefetch", {31'd0, o_prefetch}, g_pre[31:0]);
            chk("o_vblank_start", {31'd0, o_vblank_start}, g_vbs[31:0]);
            if (g_pre)
                chk("o_prefetch_y", {22'd0, o_prefetch_y}, exp_pre_y[31:0]);

            if (i >= FRAME) begin
                if (g_vis) n_vis = n_vis + 1;
                if (g_hs)  n_hs  = n_hs + 1;
                if (g_vs)  n_vs  = n_vs + 1;
                if (g_pre) n_pre = n_pre + 1;
                if (g_vbs) n_vbs = n_vbs + 1;
            end

            // --- the picture, from frame 0, taken off the DUT's own
            // outputs rather than the model's
            if (dumping && i < FRAME && visible) begin
                rgb = pattern(x, y);
                $fwrite(fh, "%03h\n", rgb);
            end

            @(posedge clk);
            if (gh == H_TOTAL - 1) begin
                gh = 0;
                gv = (gv == V_TOTAL - 1) ? 0 : gv + 1;
            end else gh = gh + 1;
        end

        if (dumping) $fclose(fh);

        // The tallies the spec states, counted over one whole frame.
        chk("visible pixels per frame", n_vis[31:0], H_VIS * V_VIS);
        chk("hsync pixel clocks per frame", n_hs[31:0], H_SYNC * V_TOTAL);
        chk("vsync pixel clocks per frame", n_vs[31:0], V_SYNC * H_TOTAL);
        chk("prefetch pulses per frame", n_pre[31:0], V_TOTAL);
        chk("vblank starts per frame", n_vbs[31:0], 1);

        $display("  %0d x %0d visible in %0d x %0d total, %0d px/frame",
                 H_VIS, V_VIS, H_TOTAL, V_TOTAL, FRAME);
        $display("  %0d checks over two frames, %0d failures", checks, errors);
        if (errors == 0) $display("\nPASS");
        else             $display("\nFAIL");
        $finish;
    end

    initial begin
        #200000000;
        $display("FAIL: timed out");
        $display("\nFAIL");
        $finish;
    end

endmodule

`default_nettype wire
