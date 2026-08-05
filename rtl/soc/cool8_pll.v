// cool8_pll — both clocks, out of the one PLL the part has.
//
// ## Why the system clock is not 12 MHz any more
//
// The UP5K has a single PLL and its reference is a *pad*, not a fabric
// net: on the SG48 package that pad is pin 35, which is where the
// iCESugar's 12 MHz arrives. Taking the clock straight off pin 35 *and*
// running the PLL from it is not a thing the silicon can do —
// `nextpnr` refuses to place the PLL, in as many words:
//
//     PLL bel 'X12/Y31/pll_3' cannot be used as it conflicts with
//     input 'clk$sb_io' on pin '35'
//
// So one of the two clocks has to give, and it is not the pixel clock:
// a monitor is counting those and 25.125 MHz is already 0.2 % off
// nominal. The system clock therefore has to be a division of it.
//
//   VCO      12 x 67   = 804 MHz     DIVR 0, DIVF 66, DIVQ 5
//   PLL      804 / 32  = 25.125 MHz  GENCLK — the raster
//   fabric   25.125 / 3 = 8.375 MHz  everything else
//
// ## ...and why it is divided by three rather than by two
//
// Half the pixel clock is 12.5625 MHz and the machine does not run
// there. Measured, placed and routed with the video engine in it, the
// system clock closes at **11.0 to 11.6 MHz across six placer seeds** —
// the spread is the placer, the shortfall is the design. The critical
// path is the one D26 named and M4 measured: SPRAM read data, through
// the block and byte selects, the boot ROM's mux and the I/O page's, the
// instruction decode, and into the next state. It is thirty-seven levels
// of logic and 87 ns of them, and no seed makes that 79.6.
//
// Two thirds of the way, at 8.375 MHz, leaves 36 % margin — which is the
// point of choosing it over the 10.05 MHz a divide-by-five would give.
// The blitter and the sprite engine are still to be added and they will
// take the design from 73 % to 92 % occupancy, where
// routing gets worse rather than better. A clock that only just closes
// today is a clock that has to be revisited twice more before M5 ends.
//
// The divider is registered rather than decoded, so `sclk` comes out of
// a flip-flop and cannot glitch, and it goes onto a global net through
// an explicit `SB_GB`. One clock in three is high, which is a 33 % duty
// cycle: nothing here is level-sensitive and 39.8 ns is far more than
// any flip-flop's minimum pulse width.
//
// The two clocks are now phase-related, which the design does not use
// and must not start using: the crossing in cool8_video is a toggle
// through two flip-flops either way. A relationship the tools do not
// constrain is not a relationship to build on, and it costs six
// flip-flops to ignore it.
//
// ## The simulation branch
//
// The toolchain's `cells_sim.v` gives SB_PLL40_2F_PAD no body at all —
// its outputs are simply undriven — so a testbench that instantiated
// cool8_top would have no clock anywhere. Rather than force nets from
// outside, the substitution is made here where it is legible: `SIM`
// passes the pad straight through as the system clock, so a testbench's
// own clock still sets the machine's speed, and free-runs a pixel clock
// beside it.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_pll #(
    parameter SIM = 0
) (
    input  wire pin,                   // the PLL's pad: 12 MHz, pin 35
    output wire pclk,                  // 25.125 MHz, the raster
    output wire sclk,                  // 12.5625 MHz, everything else
    output wire lock
);

    generate
    if (SIM) begin : g_sim
        reg p = 1'b0;
        always #19.900 p = ~p;         // 25.125 MHz
        assign pclk = p;
        assign sclk = pin;
        // Locked from the start: there is nothing here to lock, and a
        // simulated lock delay would only move the power-on counter's
        // release without saying anything true about it.
        assign lock = 1'b1;
    end else begin : g_pll
        SB_PLL40_PAD #(
            .FEEDBACK_PATH("SIMPLE"),
            .DIVR(4'b0000),
            .DIVF(7'b1000010),
            .DIVQ(3'b101),
            .FILTER_RANGE(3'b001)
        ) u_pll (
            .PACKAGEPIN(pin),
            .PLLOUTGLOBAL(pclk),
            .PLLOUTCORE(),
            .LOCK(lock),
            .RESETB(1'b1),
            .BYPASS(1'b0)
        );

        reg [1:0] cnt = 2'd0;
        reg       s   = 1'b0;

        always @(posedge pclk) begin
            cnt <= (cnt == 2'd2) ? 2'd0 : (cnt + 1'b1);
            s   <= (cnt == 2'd1);
        end

        SB_GB u_gb (
            .USER_SIGNAL_TO_GLOBAL_BUFFER(s),
            .GLOBAL_BUFFER_OUTPUT(sclk)
        );
    end
    endgenerate

endmodule

`default_nettype wire
