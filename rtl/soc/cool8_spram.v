// cool8_spram — 64 KB of byte-addressed memory out of two SB_SPRAM256KA.
//
// The core wants a flat 16-bit address space, one byte per access, on
// the ready-gated protocol in docs/03-microarchitecture.md section 2.1.
// SB_SPRAM256KA is 16K x 16 with four nibble write enables and a
// *registered* read output. This block is the whole of the difference.
//
//   addr[15]    picks the block
//   addr[14:1]  is the word inside it
//   addr[0]     picks the half, through two of the four MASKWREN bits
//
// Reads cost one wait state, because DATAOUT appears the cycle after the
// address. Writes cost none: the SPRAM commits on the same rising edge
// the core completes its transfer on, so making a write wait would spend
// a cycle to buy nothing. That asymmetry is invisible above the bus —
// the core only ever looks at mem_ready.
//
// The address is captured on the launch cycle rather than re-read on the
// data cycle. The bus protocol does say a master holds the address
// stable while it is stalled, so this is not strictly needed; it costs
// two flip-flops, it makes the block correct for a master that does not,
// and it keeps the block and byte selects off the read data path, which
// D26 measured as the critical one in the whole system.
//
// SPRAM has no bitstream initialisation: all 64 KB is garbage at
// power-on and the boot ROM's first job is to clear it. See
// docs/04-system.md section 3.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_spram (
    input  wire        clk,
    input  wire        rst_n,

    input  wire [15:0] addr,
    input  wire [7:0]  wdata,
    input  wire        read,
    input  wire        write,
    output wire [7:0]  rdata,
    output wire        ready,

    // The address cycle of a read. Anything sharing this port and
    // answering in the same slot — the boot ROM overlay, the video
    // arbiter later — captures its own selects on this, so there is one
    // definition of when an access starts rather than two that must
    // agree.
    output wire        o_launch
);

    reg  rd_pend;                  // the data cycle of a read is now
    reg  blk_r, byte_r;            // which block and half it came from

    // A read occupies two cycles and only the first presents an address;
    // asserting CHIPSELECT again on the second would re-read the same
    // word for nothing.
    wire launch_rd = read & ~rd_pend;
    wire active    = launch_rd | write;

    // Low only while a read is waiting for its data. High when idle, so
    // a master that samples it outside an access is not misled.
    assign ready    = ~launch_rd;
    assign o_launch = launch_rd;

    wire [15:0] dout0, dout1;
    wire [15:0] dout = blk_r ? dout1 : dout0;
    assign rdata = byte_r ? dout[15:8] : dout[7:0];

    // Both halves carry the byte; MASKWREN decides which one lands.
    wire [15:0] din  = {wdata, wdata};
    wire [3:0]  mask = addr[0] ? 4'b1100 : 4'b0011;

    always @(posedge clk) begin
        if (!rst_n) begin
            rd_pend <= 1'b0;
            blk_r   <= 1'b0;
            byte_r  <= 1'b0;
        end else begin
            rd_pend <= launch_rd;
            if (launch_rd) begin
                blk_r  <= addr[15];
                byte_r <= addr[0];
            end
        end
    end

    // POWEROFF is active low — 1'b1 is the powered state, and tying it
    // low would zero the array on every simulation start and hide the
    // fact that real SPRAM comes up undefined.
    SB_SPRAM256KA u_lo (
        .ADDRESS(addr[14:1]), .DATAIN(din), .MASKWREN(mask),
        .WREN(write), .CHIPSELECT(active & ~addr[15]),
        .CLOCK(clk), .STANDBY(1'b0), .SLEEP(1'b0), .POWEROFF(1'b1),
        .DATAOUT(dout0)
    );

    SB_SPRAM256KA u_hi (
        .ADDRESS(addr[14:1]), .DATAIN(din), .MASKWREN(mask),
        .WREN(write), .CHIPSELECT(active & addr[15]),
        .CLOCK(clk), .STANDBY(1'b0), .SLEEP(1'b0), .POWEROFF(1'b1),
        .DATAOUT(dout1)
    );

endmodule

`default_nettype wire
