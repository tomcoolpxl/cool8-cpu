// cool8_vga — the raster. Counters, syncs, and where the beam is.
//
// 640x480 at ~60 Hz, both syncs active low, from a 25.125 MHz pixel
// clock — docs/04-system.md section 5.1. Nothing here knows what a
// character is or where memory lives; it says where the beam is and when
// to go and fetch the next line, and everything else hangs off that.
//
// **This runs in the pixel domain, not the system domain.** The two are
// decoupled — [D26] — because 25.125 MHz is a number a monitor is
// counting and 8.375 MHz is what the machine closes at. The join is a
// scanline
// buffer written by the system clock and read by this one, which is why
// `o_prefetch` exists: it fires once per line, in the blanking, naming
// the line that is *about* to be displayed, so the fetch has a whole
// horizontal blank to complete in.
//
// Every output is registered off the same counters, so `x`, `y`,
// `visible` and the two syncs are always consistent with each other and
// the pixel presented for (`x`,`y`) is the pixel for that position. A
// fetch pipeline runs off `o_prefetch` a line ahead, not off `x`.
//
// The timing is parameterised so a testbench can run a raster small
// enough to check exhaustively as well as the real one. The defaults are
// the real one.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_vga #(
    parameter H_VIS  = 640,
    parameter H_FP   = 16,
    parameter H_SYNC = 96,
    parameter H_BP   = 48,
    parameter V_VIS  = 480,
    parameter V_FP   = 10,
    parameter V_SYNC = 2,
    parameter V_BP   = 33,
    parameter HBITS  = 10,
    parameter VBITS  = 10
) (
    input  wire              clk,        // pixel clock
    input  wire              rst_n,

    output reg  [HBITS-1:0]  x,          // 0..H_VIS-1 while visible
    output reg  [VBITS-1:0]  y,
    output reg               visible,    // inside the display window
    output reg               hsync_n,
    output reg               vsync_n,
    output reg               vblank,     // the whole vertical blanking

    // One pulse per line, at the start of the horizontal blanking, with
    // the line that will be displayed next. A scanline buffer has from
    // here to the end of the back porch — H_FP + H_SYNC + H_BP pixel
    // clocks, 160 of them, about 6.4 us — to fill itself.
    output reg               o_prefetch,
    output reg  [VBITS-1:0]  o_prefetch_y,

    // One pulse per frame, at the start of vertical blanking. The
    // vblank interrupt and the frame-buffer swap hang off this.
    output reg               o_vblank_start
);

    localparam H_TOTAL = H_VIS + H_FP + H_SYNC + H_BP;
    localparam V_TOTAL = V_VIS + V_FP + V_SYNC + V_BP;

    localparam H_SYNC_ON  = H_VIS + H_FP;
    localparam H_SYNC_OFF = H_VIS + H_FP + H_SYNC;
    localparam V_SYNC_ON  = V_VIS + V_FP;
    localparam V_SYNC_OFF = V_VIS + V_FP + V_SYNC;

    reg [HBITS-1:0] hpos;
    reg [VBITS-1:0] vpos;

    wire h_last = (hpos == H_TOTAL - 1);
    wire v_last = (vpos == V_TOTAL - 1);

    // What the counters will hold next cycle. Everything below is
    // derived from these rather than from hpos/vpos, so the registered
    // outputs describe the same pixel the counters do.
    wire [HBITS-1:0] hnext = h_last ? {HBITS{1'b0}} : hpos + 1'b1;
    wire [VBITS-1:0] vnext = !h_last ? vpos :
                             v_last  ? {VBITS{1'b0}} : vpos + 1'b1;

    // The line after the one being scanned, wrapping at the frame, which
    // is the line a scanline buffer should be filling. During the last
    // line of the frame that is line 0 of the next one.
    wire [VBITS-1:0] fetch_y = (vnext >= V_TOTAL - 1) ? {VBITS{1'b0}}
                                                      : vnext + 1'b1;

    always @(posedge clk) begin
        if (!rst_n) begin
            // One short of the wrap, so the first clock out of reset
            // produces pixel (0,0) rather than skipping it.
            hpos <= H_TOTAL - 1;
            vpos <= V_TOTAL - 1;
            x <= {HBITS{1'b0}};
            y <= {VBITS{1'b0}};
            visible <= 1'b0;
            hsync_n <= 1'b1;
            vsync_n <= 1'b1;
            vblank  <= 1'b0;
            o_prefetch <= 1'b0;
            o_prefetch_y <= {VBITS{1'b0}};
            o_vblank_start <= 1'b0;
        end else begin
            hpos <= hnext;
            vpos <= vnext;

            x <= hnext;
            y <= vnext;
            visible <= (hnext < H_VIS) && (vnext < V_VIS);
            hsync_n <= ~((hnext >= H_SYNC_ON) && (hnext < H_SYNC_OFF));
            vsync_n <= ~((vnext >= V_SYNC_ON) && (vnext < V_SYNC_OFF));
            vblank  <= (vnext >= V_VIS);

            // At the first pixel of the front porch, naming the next
            // line. One clock wide.
            o_prefetch   <= (hnext == H_VIS);
            o_prefetch_y <= fetch_y;

            // Coincident with `vblank` going high, so the two cannot
            // drift apart and a handler that trusts either is right.
            o_vblank_start <= (hnext == 0) && (vnext == V_VIS);
        end
    end

endmodule

`default_nettype wire
