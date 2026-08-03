// cool8_mem — the memory map: 64 KB of SPRAM with the boot ROM overlaid.
//
// Presents one ready-gated port and hides which of the two answered it.
// The overlay is the whole of the difference and it is one rule:
//
//   **Reads at $F000-$FDFF and $FF00-$FFFF come from ROM while ROMEN is
//   set. Writes always go to RAM.**
//
// That asymmetry is not a convenience, it is what makes the boot
// sequence possible at all: the ROM installs the interrupt vectors at
// $FFF8-$FFFF, which is inside its own read window, and later drops the
// overlay to find them there. A read-write ROM window would need the
// vectors written somewhere else and copied, and a read-only one with no
// write path underneath would have nowhere to put them. See
// docs/04-system.md sections 2 and 3.
//
// `ROMEN` reloads on every CPU reset, from `bootram` rather than from a
// constant. That is the entire mechanism behind the loader's GO command:
// set BOOTRAM, pulse CPU reset, and the machine comes up with the ROM
// out of the map and the reset vector taken from the RAM the loader just
// wrote. Clear BOOTRAM and pulse reset and it boots normally. The bit
// survives a CPU reset and only a board reset clears it — which is why
// the two resets are separate ports here.
//
// $FE00-$FEFF still reaches this block and is ordinary RAM to it. The
// I/O page is decoded above, in cool8_soc.v, and always wins; keeping
// that in one place is why it is not also decoded here. The one thing
// this block does know about it is that it is a hole in the ROM window.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_mem #(
    parameter ROM_FILE = "boot.hex",
    parameter ROM_INIT = 1
) (
    input  wire        clk,
    input  wire        rst_n,        // board reset
    input  wire        cpu_rst_n,    // CPU reset — reloads ROMEN

    input  wire [15:0] addr,
    input  wire [7:0]  wdata,
    input  wire        read,
    input  wire        write,
    output wire [7:0]  rdata,
    output wire        ready,

    input  wire        bootram,      // loader: ROMEN's reset value is ~this

    // $FE00 SYSCTRL, bit 0
    input  wire        ctrl_we,
    input  wire [7:0]  ctrl_wdata,
    output wire [7:0]  ctrl_rdata
);

    reg  romen;
    reg  rom_r;                      // the launched read came from ROM

    wire [7:0] ram_rdata, rom_rdata;
    wire       launch;

    // $F000-$FFFF less the I/O page. The hole is stated here as well as
    // in the SoC's decode because this block must not answer for it: a
    // read of $FE12 with ROMEN set has to miss the ROM, or the I/O
    // register underneath would be shadowed by whatever the ROM image
    // happens to hold at that offset.
    wire rom_win = (addr[15:12] == 4'hF) && (addr[15:8] != 8'hFE);
    wire rom_sel = romen & rom_win;

    assign ctrl_rdata = {7'b0000000, romen};

    always @(posedge clk) begin
        if (!rst_n)          romen <= 1'b1;
        else if (!cpu_rst_n) romen <= ~bootram;
        else if (ctrl_we)    romen <= ctrl_wdata[0];
    end

    always @(posedge clk) begin
        if (!rst_n)     rom_r <= 1'b0;
        else if (launch) rom_r <= rom_sel;
    end

    // Both are read on every launch and the answer is picked afterwards.
    // Suppressing the SPRAM read under the overlay would save a little
    // power for the few milliseconds the ROM is mapped, and would cost a
    // second copy of the ready logic to keep in step with the first —
    // which is the kind of trade that only ever looks good in the
    // abstract.
    cool8_spram u_ram (
        .clk(clk), .rst_n(rst_n),
        .addr(addr), .wdata(wdata), .read(read), .write(write),
        .rdata(ram_rdata), .ready(ready), .o_launch(launch)
    );

    cool8_rom #(.INIT_FILE(ROM_FILE), .INIT(ROM_INIT)) u_rom (
        .clk(clk), .read(launch & rom_sel), .addr(addr[11:0]),
        .rdata(rom_rdata)
    );

    assign rdata = rom_r ? rom_rdata : ram_rdata;

endmodule

`default_nettype wire
