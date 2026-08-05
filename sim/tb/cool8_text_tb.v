// cool8_text_tb — a screen of real characters, rendered to a picture.
//
// Drives cool8_vga and cool8_text with a screen built here, plays the
// part of the fetch engine that M5 has still to build, and writes every
// visible pixel out for sim/test_video.py to turn into a PNG. The point
// is to *look* at it: a font with a row inverted or a pipeline off by one
// still passes any count you care to take, and is obvious in an image.
//
// The two clocks are deliberately incommensurate — 10 ns for pixels and
// 21 ns for the system side — because the line buffer between them is
// the only clock crossing in the design (D26) and a testbench that
// clocked both from the same edge would not exercise it at all.
//
// The fetch engine here does what the real one will: a character row
// lasts sixteen scanlines, so it fills the bank the raster is not
// reading and swaps at the row boundary. Row R lives in bank R[0], which
// makes the swap a wire rather than a decision.
//
//   vvp cool8_text_tb.vvp +frame=text.hex
//
// Plusargs:
//   +frame=FILE   the visible pixels, 12-bit hex, one per line
//   +vcd=FILE     dump waves

`default_nettype none
`timescale 1ns / 1ps

module cool8_text_tb;

    localparam H_VIS = 640, H_FP = 16, H_SYNC = 96, H_BP = 48;
    localparam V_VIS = 480, V_FP = 10, V_SYNC = 2,  V_BP = 33;
    localparam H_TOTAL = 800, V_TOTAL = 525;
    localparam COLS = 80, ROWS = 30;

    reg          pclk = 1'b0;
    reg          sclk = 1'b0;
    reg          rst_n = 1'b0;

    integer      i, r, c, fh, pixels;
    reg          dumping;
    reg [1023:0] vcdfile, framefile;

    wire [9:0]   x, y;
    wire         visible, hsync_n, vsync_n, vblank;
    wire         o_prefetch, o_vblank_start;
    wire [9:0]   o_prefetch_y;
    wire [11:0]  rgb;

    reg          read_bank;
    reg          cell_we, cell_bank;
    reg [6:0]    cell_col;
    reg [15:0]   cell_data;
    reg          pal_we;
    reg [4:0]    pal_addr;
    reg [7:0]    pal_data;

    reg [15:0]   screen [0:COLS*ROWS-1];
    reg          armed;

    always #5    pclk = ~pclk;
    always #10.5 sclk = ~sclk;

    cool8_vga u_vga (
        .clk(pclk), .rst_n(rst_n),
        .x(x), .y(y), .visible(visible),
        .hsync_n(hsync_n), .vsync_n(vsync_n), .vblank(vblank),
        .o_prefetch(o_prefetch), .o_prefetch_y(o_prefetch_y),
        .o_vblank_start(o_vblank_start)
    );

    cool8_text #(.FONT_FILE("font.hex"), .H_TOTAL(H_TOTAL), .COLS(COLS))
    u_text (
        .pclk(pclk), .prst_n(rst_n),
        .x(x), .y(y), .visible(visible), .rgb(rgb),
        .read_bank(read_bank),
        .sclk(sclk),
        .cell_we(cell_we), .cell_bank(cell_bank),
        .cell_col(cell_col), .cell_data(cell_data),
        .pal_we(pal_we), .pal_addr(pal_addr), .pal_data(pal_data)
    );

    // ------------------------------------------------------- the writer

    task put_cell;
        input bank;
        input [6:0] col;
        input [15:0] dat;
        begin
            @(posedge sclk);
            cell_bank <= bank;
            cell_col  <= col;
            cell_data <= dat;
            cell_we   <= 1'b1;
            @(posedge sclk);
            cell_we   <= 1'b0;
        end
    endtask

    task fill_bank;                      // one character row into one bank
        input integer row;
        integer k;
        begin
            for (k = 0; k < COLS; k = k + 1)
                put_cell(row[0], k[6:0],
                         (row < ROWS) ? screen[row * COLS + k] : 16'h0720);
        end
    endtask

    task put_pal;
        input [3:0] entry;
        input [3:0] pr;
        input [3:0] pg;
        input [3:0] pb;
        begin
            @(posedge sclk);
            pal_addr <= {entry, 1'b0}; pal_data <= {4'h0, pr}; pal_we <= 1'b1;
            @(posedge sclk);
            pal_addr <= {entry, 1'b1}; pal_data <= {pg, pb};
            @(posedge sclk);
            pal_we <= 1'b0;
        end
    endtask

    // ------------------------------------------------------- the screen

    task put_str;
        input integer row;
        input integer col;
        input [8*72-1:0] s;
        input [7:0] attr;
        integer k, n;
        reg [7:0] ch;
        begin
            // The string is right-justified in the vector, so walk down
            // from the top and skip the leading zero padding.
            n = 0;
            for (k = 71; k >= 0; k = k - 1) begin
                ch = s[k*8 +: 8];
                if (ch != 8'h00) begin
                    if (col + n < COLS)
                        screen[row * COLS + col + n] = {attr, ch};
                    n = n + 1;
                end
            end
        end
    endtask

    task build_screen;
        integer k, j;
        begin
            for (k = 0; k < COLS * ROWS; k = k + 1)
                screen[k] = 16'h0720;                    // grey on black

            // A box in CP437 line-drawing characters.
            screen[0 * COLS + 0] = 16'h0FC9;             // top left
            screen[0 * COLS + (COLS-1)] = 16'h0FBB;
            screen[4 * COLS + 0] = 16'h0FC8;
            screen[4 * COLS + (COLS-1)] = 16'h0FBC;
            for (k = 1; k < COLS - 1; k = k + 1) begin
                screen[0 * COLS + k] = 16'h0FCD;         // horizontal
                screen[4 * COLS + k] = 16'h0FCD;
            end
            for (k = 1; k < 4; k = k + 1) begin
                screen[k * COLS + 0] = 16'h0FBA;         // vertical
                screen[k * COLS + (COLS-1)] = 16'h0FBA;
            end

            put_str(1, 3, "COOL8", 8'h0E);
            put_str(1, 9, "text mode 0 - 80x30 cells of 8x16", 8'h0B);
            put_str(2, 3, "the font is real, the raster is real,", 8'h07);
            put_str(3, 3, "and this frame came out of a simulator", 8'h08);

            // Every attribute, so a palette that is wrong shows up as a
            // colour that is wrong rather than as nothing at all.
            for (k = 0; k < 16; k = k + 1)
                for (j = 0; j < 4; j = j + 1)
                    screen[6 * COLS + 3 + k * 4 + j] =
                        {4'h0, k[3:0], 8'hDB};           // solid block
            for (k = 0; k < 16; k = k + 1)
                for (j = 0; j < 4; j = j + 1)
                    screen[7 * COLS + 3 + k * 4 + j] =
                        {k[3:0], 4'h0, 8'h20};           // as a background

            // The whole character set, sixteen to a row.
            for (k = 0; k < 256; k = k + 1)
                screen[(10 + k / 16) * COLS + 3 + (k % 16) * 3] =
                    {8'h0A, k[7:0]};

            // Sixteen colours, each at the four dither levels the font
            // carries — $B0 $B1 $B2 $DB, a quarter to solid. Both rows
            // take their colour from the same k[5:2], so a column is one
            // hue and the two rows together are the palette against the
            // shades rather than the palette and then some grey.
            for (k = 0; k < 64; k = k + 1) begin
                screen[27 * COLS + 8 + k] = {4'h0, k[5:2], 8'hDB};
                screen[28 * COLS + 8 + k] =
                    {4'h0, k[5:2], (k[1:0] == 0) ? 8'hB0 :
                                   (k[1:0] == 1) ? 8'hB1 :
                                   (k[1:0] == 2) ? 8'hB2 : 8'hDB};
            end
        end
    endtask

    // ==================================================================

    initial begin
        cell_we = 1'b0; pal_we = 1'b0;
        cell_bank = 1'b0; cell_col = 7'd0; cell_data = 16'h0000;
        pal_addr = 5'd0; pal_data = 8'h00;
        read_bank = 1'b0;
        armed = 1'b0;
        pixels = 0;

        dumping = $value$plusargs("frame=%s", framefile);
        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_text_tb);
        end

        build_screen;

        // The sixteen CGA colours, in 12-bit.
        put_pal(4'h0, 4'h0, 4'h0, 4'h0);   put_pal(4'h1, 4'h0, 4'h0, 4'hA);
        put_pal(4'h2, 4'h0, 4'hA, 4'h0);   put_pal(4'h3, 4'h0, 4'hA, 4'hA);
        put_pal(4'h4, 4'hA, 4'h0, 4'h0);   put_pal(4'h5, 4'hA, 4'h0, 4'hA);
        put_pal(4'h6, 4'hA, 4'h5, 4'h0);   put_pal(4'h7, 4'hA, 4'hA, 4'hA);
        put_pal(4'h8, 4'h5, 4'h5, 4'h5);   put_pal(4'h9, 4'h5, 4'h5, 4'hF);
        put_pal(4'hA, 4'h5, 4'hF, 4'h5);   put_pal(4'hB, 4'h5, 4'hF, 4'hF);
        put_pal(4'hC, 4'hF, 4'h5, 4'h5);   put_pal(4'hD, 4'hF, 4'h5, 4'hF);
        put_pal(4'hE, 4'hF, 4'hF, 4'h5);   put_pal(4'hF, 4'hF, 4'hF, 4'hF);

        // Rows 0 and 1 have to be there before the raster starts.
        fill_bank(0);
        fill_bank(1);

        repeat (4) @(posedge pclk);
        rst_n = 1'b1;

        if (dumping) fh = $fopen(framefile, "w");

        // Skip whatever frame is in progress and capture the next whole
        // one, so the picture starts at its top left corner.
        @(posedge o_vblank_start);
        armed = 1'b1;
        while (pixels < H_VIS * V_VIS) @(posedge pclk);
        repeat (10) @(posedge pclk);

        if (dumping) $fclose(fh);
        $display("  %0d visible pixels captured", pixels);
        $display("\nPASS");
        $finish;
    end

    // The fetch engine M5 has still to build in gates: at each character
    // row boundary, point the raster at the bank already holding that
    // row and fill the other one. Filling costs 1.7 us and the rows are
    // 509 us apart, which is the margin the real one will have too.
    //
    // **Row 0 has to be primed in the vertical blanking**, because
    // nothing else fills it — every other row is filled at the boundary
    // of the row before it and there is no row before row 0. The first
    // version of this did not, and the top line of the screen came out
    // blank from the second frame onwards: the banks were seeded before
    // reset, and row 29's boundary then overwrote bank 0 with the blanks
    // of a row that does not exist. Off-screen rows are skipped for the
    // same reason.
    initial begin : fetcher
        wait (rst_n);
        forever begin
            @(posedge pclk);
            if (o_vblank_start) begin
                fill_bank(0);
            end else if (o_prefetch && o_prefetch_y[3:0] == 4'd0 &&
                         o_prefetch_y < V_VIS) begin
                read_bank = o_prefetch_y[4];
                if (o_prefetch_y[8:4] + 1 < ROWS)
                    fill_bank(o_prefetch_y[8:4] + 1);
            end
        end
    end

    // Capture the frame off the pins, exactly as a monitor would see it.
    always @(posedge pclk) begin
        if (armed && visible && dumping && pixels < H_VIS * V_VIS) begin
            $fwrite(fh, "%03h\n", rgb);
            pixels = pixels + 1;
        end
    end

    initial begin
        #100000000;
        $display("FAIL: timed out");
        $display("\nFAIL");
        $finish;
    end

endmodule

`default_nettype wire
