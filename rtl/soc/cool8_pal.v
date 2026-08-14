// cool8_pal — 256 entries of 12-bit colour, written at 8.375 MHz and
// read at 25.125 MHz.
//
// Every mode goes through this: a bitmap pixel, a tile pixel with its
// palette bank in the high nibble, a text attribute, the border colour
// and a sprite pixel all arrive as one 8-bit index (docs/04-system.md
// section 5.3). One table, one lookup, and the modes differ only in how
// many of the index's bits they actually vary.
//
// ## One block RAM, because a write is buffered until the pair is whole
//
// The format is the 12-bit VGA PMOD's: an even byte carries `0000RRRR`
// and the odd byte after it `GGGGBBBB`, so an entry is two stores and no
// packing. That is convenient for software and awkward for a block RAM,
// which has no byte enables in the configuration this needs — writing
// the red nibble alone would be a read-modify-write against a port the
// raster is using.
//
// So the even byte is not written at all. It is held in four flip-flops
// and the whole 12-bit entry is committed when the odd byte arrives.
// The cost is that a half-written entry has no effect until it is
// finished, which is what software does anyway; the saving is a whole
// EBR against the obvious arrangement of two arrays.
//
// **The palette is write-only.** A read port in the system domain is a
// second port the raster already occupies, and it would buy nothing but
// the ability to read back what software itself wrote. `PAL_IDX` is
// readable so an interrupt handler can save and restore the index it
// interrupted; `PAL_DATA` reads $FF.
//
// ## The second clock crossing
//
// This and the line buffer in cool8_pixel are the only two, and both are
// inside a block RAM with independent clocks, which is the arrangement
// D26 chose. Nothing crosses on a wire.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_pal #(parameter INIT_FILE = "pal.hex") (
    // ---- system domain: PAL_IDX / PAL_DATA
    input  wire        sclk,
    input  wire        we,             // a write of PAL_DATA
    input  wire [7:0]  entry,          // PAL_IDX
    input  wire        half,           // 0 = red byte, 1 = green/blue
    input  wire [7:0]  wdata,

    // ---- pixel domain
    input  wire        pclk,
    input  wire [7:0]  index,
    output wire [11:0] rgb             // one clock behind `index`
);

    reg [11:0] pal [0:255];

    // **The default palette, in the bitstream.** The block RAM comes up
    // zeroed otherwise -- 256 entries of black, border included, so a
    // machine that never writes the palette shows nothing at all. The
    // EBR is allocated either way; only its INIT bits change, so this
    // is measured at zero cells. Same arrangement cool8_rom.v has for
    // the boot image, and the same caveat: the file must resolve from
    // the working directory at elaboration.
    initial $readmemh(INIT_FILE, pal);
    reg [3:0]  red;                    // the even byte, waiting for its pair
    reg [11:0] q;

    always @(posedge sclk) begin
        if (we) begin
            if (!half) red <= wdata[3:0];
            else       pal[entry] <= {red, wdata};
        end
    end

    always @(posedge pclk)
        q <= pal[index];

    assign rgb = q;

endmodule

`default_nettype wire
