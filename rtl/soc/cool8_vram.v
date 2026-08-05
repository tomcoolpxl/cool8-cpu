// cool8_vram — 64 KB of video memory over the other two SB_SPRAM256KA,
// and the four-way arbiter in front of it.
//
// This is the memory D28 split off from the CPU's. Text modes read main
// RAM through cool8_spram; everything else — bitmaps, tile maps, glyph
// and tile patterns, sprite patterns, blitter source and destination —
// lives here, where the CPU is not competing for it. That is the whole
// reason the blitter can run flat out and cost the CPU nothing.
//
// ## Sixteen bits wide, not eight
//
// cool8_spram presents a byte port because the core has an 8-bit data
// bus and no choice. Nothing here has that constraint: a bitmap fetch
// wants four 4 bpp pixels at once, a cell is a 16-bit word, and the
// blitter moves rectangles. So the port is the width the memory
// actually is, and the byte-sized requester — the CPU's indirect port —
// does its own halving outside. The bandwidth numbers in
// docs/04-system.md section 5.10 are counted in these accesses.
//
// ## MASKWREN is a 4 bpp pixel write
//
// SB_SPRAM256KA has four write enables, one per nibble. A 4 bpp pixel
// *is* a nibble, so plotting one is a native masked write with no
// read-modify-write anywhere — which is worth knowing, because 4 bpp is
// the mode most drawing happens in. 8 bpp is two nibbles. Only 1 and
// 2 bpp need the pixel port to read first.
//
// ## Fully pipelined: a grant every cycle
//
// DATAOUT is registered, so an address presented in cycle N produces
// data in cycle N+1 — but SPRAM will accept a new address in N+1 all
// the same. cool8_spram spends that second cycle as a wait state only
// because the core's protocol makes it, and nothing here does. So the
// arbiter grants on every cycle it has a requester, and `*_rvalid` is
// simply the matching grant delayed by one.
//
// Exactly one requester is granted per cycle, so exactly one rvalid is
// high per cycle, so there is one shared read bus and no read mux.
//
// ## Priority is fixed, and the order is the argument
//
//   display fetch   the only requester with a deadline it cannot miss —
//                   the line buffer has to be full before the raster
//                   reaches it
//   sprite fetch    a deadline too, but with a line of slack
//   CPU port        one access, and software is blocked on it. Above the
//                   blitter so a long blit cannot stall a store
//   blitter         last, because it is the only requester that can wait
//                   indefinitely with nothing breaking
//
// No round robin and no anti-starvation counter, because the arithmetic
// says none is needed: the display takes at most 34 % of a line (8 bpp),
// sprites 8 %, and the CPU port cannot exceed one access per store. The
// blitter's share is bounded below by about half. A display engine that
// requests every cycle is a bug in the display engine, not a case for
// the arbiter to handle.
//
// ## The address is a word address
//
// `*_addr[15:1]` is deliberately not [15:0]: bit 0 selects a half of a
// word, which is a requester's business and not this block's. The
// mapping matches cool8_spram exactly — addr[15] picks the block,
// addr[14:1] the word inside it — so a byte address means the same
// thing in both memories.
//
// SPRAM has no bitstream initialisation. All 64 KB is garbage at
// power-on, exactly as main RAM is.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_vram (
    input  wire        clk,
    input  wire        rst_n,

    // ---- 0: display fetch. Read only, highest priority.
    input  wire        dsp_req,
    input  wire [15:1] dsp_addr,
    output wire        dsp_gnt,
    output wire        dsp_rvalid,

    // ---- 1: sprite pattern fetch. Read only.
    input  wire        spr_req,
    input  wire [15:1] spr_addr,
    output wire        spr_gnt,
    output wire        spr_rvalid,

    // ---- 2: the CPU's indirect port, $FE26-$FE29.
    input  wire        cpu_req,
    input  wire [15:1] cpu_addr,
    input  wire [15:0] cpu_wdata,
    input  wire        cpu_we,
    input  wire [3:0]  cpu_mask,       // one bit per nibble
    output wire        cpu_gnt,
    output wire        cpu_rvalid,

    // ---- 3: the blitter.
    input  wire        blt_req,
    input  wire [15:1] blt_addr,
    input  wire [15:0] blt_wdata,
    input  wire        blt_we,
    input  wire [3:0]  blt_mask,
    output wire        blt_gnt,
    output wire        blt_rvalid,

    // One reader is valid per cycle, so one bus. Sample it in the cycle
    // your own rvalid is high; it says nothing in any other.
    output wire [15:0] rdata
);

    // ------------------------------------------------------ the arbiter

    // Strict priority, written out rather than encoded: four terms of at
    // most four inputs is smaller than a priority encoder and a decoder,
    // and it is the specification in the same shape as the comment above.
    assign dsp_gnt = dsp_req;
    assign spr_gnt = spr_req & ~dsp_req;
    assign cpu_gnt = cpu_req & ~dsp_req & ~spr_req;
    assign blt_gnt = blt_req & ~dsp_req & ~spr_req & ~cpu_req;

    wire active = dsp_gnt | spr_gnt | cpu_gnt | blt_gnt;

    wire [15:1] addr = dsp_gnt ? dsp_addr :
                       spr_gnt ? spr_addr :
                       cpu_gnt ? cpu_addr : blt_addr;

    // Only two requesters ever write, so the write path is a 2:1 mux and
    // not a 4:1. The display and sprite fetches cannot write at all —
    // there is no port for it, which is a stronger guarantee than a bit
    // they are trusted to leave clear.
    wire [15:0] wdata = cpu_gnt ? cpu_wdata : blt_wdata;
    wire [3:0]  mask  = cpu_gnt ? cpu_mask  : blt_mask;
    wire        we    = (cpu_gnt & cpu_we) | (blt_gnt & blt_we);

    // ----------------------------------------------- the returning data

    reg dsp_v, spr_v, cpu_v, blt_v;
    reg blk_r;                         // which block the pending read hit

    assign dsp_rvalid = dsp_v;
    assign spr_rvalid = spr_v;
    assign cpu_rvalid = cpu_v;
    assign blt_rvalid = blt_v;

    always @(posedge clk) begin
        if (!rst_n) begin
            dsp_v <= 1'b0;
            spr_v <= 1'b0;
            cpu_v <= 1'b0;
            blt_v <= 1'b0;
            blk_r <= 1'b0;
        end else begin
            dsp_v <= dsp_gnt;
            spr_v <= spr_gnt;
            cpu_v <= cpu_gnt & ~cpu_we;
            blt_v <= blt_gnt & ~blt_we;
            // Captured on the grant cycle rather than re-read on the data
            // cycle, so the block select stays off the read data path —
            // D26 measured that path as the critical one in the machine,
            // and this is the same reasoning cool8_spram uses.
            if (active) blk_r <= addr[15];
        end
    end

    wire [15:0] dout0, dout1;
    assign rdata = blk_r ? dout1 : dout0;

    // POWEROFF is active low; 1'b1 is the powered state. Tying it low
    // would zero the array at every simulation start and hide the fact
    // that real SPRAM comes up undefined.
    SB_SPRAM256KA u_lo (
        .ADDRESS(addr[14:1]), .DATAIN(wdata), .MASKWREN(mask),
        .WREN(we), .CHIPSELECT(active & ~addr[15]),
        .CLOCK(clk), .STANDBY(1'b0), .SLEEP(1'b0), .POWEROFF(1'b1),
        .DATAOUT(dout0)
    );

    SB_SPRAM256KA u_hi (
        .ADDRESS(addr[14:1]), .DATAIN(wdata), .MASKWREN(mask),
        .WREN(we), .CHIPSELECT(active & addr[15]),
        .CLOCK(clk), .STANDBY(1'b0), .SLEEP(1'b0), .POWEROFF(1'b1),
        .DATAOUT(dout1)
    );

endmodule

`default_nettype wire
