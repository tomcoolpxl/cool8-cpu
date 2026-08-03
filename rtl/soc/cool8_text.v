// cool8_text — mode 0: 80x30 characters of 8x16, and the colour that
// comes out of the pins.
//
// Takes the raster from cool8_vga and turns it into pixels. One cell is
// a 16-bit word — character in the low byte, attribute `bg[7:4] fg[3:0]`
// in the high — which is why a cell is one SPRAM access and not two
// (docs/04-system.md section 5.2).
//
// ## The line buffer is the clock crossing
//
// Memory runs at 12 MHz and the raster at 25.125 MHz, and
// [D26](docs/01-decisions.md) chose to join them inside a block RAM
// rather than with an arbiter that spans both: the cell buffer here is
// written on `sclk` and read on `pclk`, and `SB_RAM40_4K` has
// independent clocks for exactly this. Nothing else crosses.
//
// Two banks of 80 cells, so a fetch fills one while the raster reads the
// other. A character row lasts sixteen scanlines — 509 us — and 80 word
// reads at one wait state cost 13.3 us, so the fetch has forty times the
// room it needs. `bank` is chosen by the writer and is stable for a
// whole character row, which is what makes it safe to sample here
// without a handshake.
//
// ## Two cycles of lookahead
//
// A cell read costs a cycle and the font read after it costs another, so
// the address presented at pixel *x* produces its glyph byte at *x+2*.
// Rather than a shift register and a load strobe, the address simply
// runs two pixels ahead and wraps with the line — which puts the glyph
// byte for cell *x/8* on the bus exactly at *x*, with no cadence to get
// wrong. The wrap is why the row index has to look ahead too: at the
// last two pixels of a line the raster is still reporting the old `y`,
// and the cells being prepared belong to the next one.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_text #(
    parameter FONT_FILE = "font.hex",
    parameter FONT_INIT = 1,
    parameter H_TOTAL   = 800,
    parameter COLS      = 80
) (
    // ---- pixel domain
    input  wire        pclk,
    input  wire        prst_n,
    input  wire [9:0]  x,
    input  wire [9:0]  y,
    input  wire        visible,
    output wire [11:0] rgb,            // 4 bits each, straight to the pins

    // Which bank the raster reads. Held by the writer for a whole
    // character row, so it is stable across the crossing.
    input  wire        read_bank,

    // ---- system domain: the line buffer fill
    input  wire        sclk,
    input  wire        cell_we,
    input  wire        cell_bank,
    input  wire [6:0]  cell_col,
    input  wire [15:0] cell_data,

    // ---- system domain: the palette, $FE20-$FE3F
    input  wire        pal_we,
    input  wire [4:0]  pal_addr,       // {entry[3:0], odd}
    input  wire [7:0]  pal_data
);

    // ------------------------------------------------------ line buffer

    reg [15:0] cells [0:255];
    reg [15:0] cell_q;

    always @(posedge sclk)
        if (cell_we) cells[{cell_bank, cell_col}] <= cell_data;

    // ------------------------------------------------------- lookahead

    // Two pixels ahead, wrapping with the line rather than with the
    // counter's width, so the cells for column 0 are fetched during the
    // back porch and are ready at pixel 0.
    wire [10:0] ahead = {1'b0, x} + 11'd2;
    wire        wrapped = (ahead >= H_TOTAL);
    wire [10:0] xa   = wrapped ? (ahead - H_TOTAL) : ahead;

    // ...and the row within the glyph has to follow the wrap, because at
    // the last two pixels of a line `y` is still the line just finished.
    wire [9:0]  ya   = wrapped ? (y + 10'd1) : y;

    reg [3:0]  row_d;
    reg [7:0]  attr_d;
    reg [2:0]  col_d, col_dd;

    wire [7:0] font_q;

    always @(posedge pclk) begin
        if (!prst_n) begin
            cell_q <= 16'h0000;
            row_d  <= 4'd0;
            attr_d <= 8'h00;
            col_d  <= 3'd0;
            col_dd <= 3'd0;
        end else begin
            cell_q <= cells[{read_bank, xa[9:3]}];
            row_d  <= ya[3:0];
            attr_d <= cell_q[15:8];
            col_d  <= xa[2:0];
            col_dd <= col_d;
        end
    end

    // The font is the same 4 KB synchronous ROM the boot image uses:
    // 256 glyphs of 16 rows, addressed {character, row}.
    cool8_rom #(.INIT_FILE(FONT_FILE), .INIT(FONT_INIT)) u_font (
        .clk(pclk), .read(1'b1),
        .addr({cell_q[7:0], row_d}),
        .rdata(font_q)
    );

    // ---------------------------------------------------------- palette

    reg [3:0] pal_r [0:15];
    reg [3:0] pal_g [0:15];
    reg [3:0] pal_b [0:15];

    // Even byte is `0000RRRR`, odd is `GGGGBBBB` — the 12-bit VGA PMOD's
    // layout, so a palette entry is two stores and no packing.
    always @(posedge sclk) begin
        if (pal_we) begin
            if (!pal_addr[0]) pal_r[pal_addr[4:1]] <= pal_data[3:0];
            else begin
                pal_g[pal_addr[4:1]] <= pal_data[7:4];
                pal_b[pal_addr[4:1]] <= pal_data[3:0];
            end
        end
    end

    // ------------------------------------------------------- the pixel

    wire       lit   = font_q[3'd7 - col_dd];
    wire [3:0] index = lit ? attr_d[3:0] : attr_d[7:4];

    assign rgb = visible ? {pal_r[index], pal_g[index], pal_b[index]}
                         : 12'h000;

endmodule

`default_nettype wire
