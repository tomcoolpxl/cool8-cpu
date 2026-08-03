// cool8_rom — the boot ROM, 4 KB of EBR.
//
// SPRAM has no bitstream initialisation and EBR does, which is the only
// reason this block exists: at power-on it is the only memory in the
// machine with anything in it. docs/04-system.md section 3.
//
// Synchronous read with the data one cycle later, matching
// cool8_spram.v exactly, so the overlay in cool8_mem.v is a data mux and
// not a second timing model.
//
// The image covers $F000-$FFFF, addressed here by its low 12 bits. Bytes
// $0E00-$0EFF of it are unreachable — that window is the I/O page and
// the I/O decode always wins. tools/mkrom.py refuses to build an image
// with anything in that hole.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_rom #(
    parameter INIT_FILE = "boot.hex",
    parameter INIT      = 1          // 0 lets a testbench fill it instead
) (
    input  wire        clk,
    input  wire        read,         // capture on the launch cycle
    input  wire [11:0] addr,
    output reg  [7:0]  rdata
);

    reg [7:0] rom [0:4095];

    generate
        if (INIT) begin : g_init
            initial $readmemh(INIT_FILE, rom);
        end
    endgenerate

    always @(posedge clk)
        if (read) rdata <= rom[addr];

endmodule

`default_nettype wire
