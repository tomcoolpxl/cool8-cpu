// cool8_top — the board: pins, a reset that has to be manufactured, and
// the machine.
//
// Everything the FPGA actually does is in cool8_soc, which has its own
// testbenches. What is here is only what a real board makes different:
// the clock arrives on a pin, there is no reset signal anywhere so one
// has to be invented, and the LED is wired the other way up.
//
// Deliberately thin. Anything with behaviour in it belongs below this,
// where it can be tested against the emulator or against a wire rather
// than against a board.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_top #(
    // 2^POR_BITS clocks of reset after the PLL locks: 4096 is 489 us at
    // 8.375 MHz, which is far longer than anything needs and costs 12
    // flip-flops.
    parameter POR_BITS = 12,
    // 1 replaces the PLL with a pass-through — see cool8_pll.
    parameter PLL_SIM = 0,
    // The one fact in this file that has not been checked against the
    // hardware — see docs/05-board.md section 3. The RGB LED on an
    // iCESugar is common anode, so the pin sinks current and a lit
    // channel is a *low* pin. If the board comes up bright and goes dark
    // when the boot ROM finishes, this is backwards and it is a one-line
    // change and a rebuild.
    parameter LED_ACTIVE_LOW = 1
) (
    input  wire clk,             // pin 35, 12 MHz from the iCELink debugger
    input  wire uart_rx,         // pin 4
    output wire uart_tx,         // pin 6
    output wire led_r,           // pin 40
    output wire led_g,           // pin 41
    output wire led_b,           // pin 39

    // MuseLab PMOD-VGA on PMOD2 + PMOD3 — docs/05-board.md section 3
    output wire [3:0] vga_r,
    output wire [3:0] vga_g,
    output wire [3:0] vga_b,
    output wire vga_hs,
    output wire vga_vs
);

    // ------------------------------------------------------- the clocks
    //
    // Both of them come out of the one PLL, because the part cannot give
    // the fabric pin 35 and run the PLL from it at the same time. The
    // whole argument, and what it cost, is in cool8_pll.

    wire pclk, sclk, pll_lock;

    cool8_pll #(.SIM(PLL_SIM)) u_pll (
        .pin(clk), .pclk(pclk), .sclk(sclk), .lock(pll_lock)
    );

    // ------------------------------------------------------------ reset
    //
    // The board has no reset pin and no button assigned to one, so reset
    // is made here. iCE40 flip-flops come out of configuration at zero,
    // so a counter that stops at all-ones holds the machine down for
    // 2^POR_BITS clocks and then never moves again — no free-running
    // counter, no second edge, nothing to glitch later.
    //
    // It counts from the moment the PLL says it is locked, not from
    // configuration: before that the clock it is counting is not a clock.
    //
    // No button for it on purpose. `SW[0]` is spoken for as the NMI
    // break button (04-system.md section 6) and the other three are
    // unassigned, but a reset button whose polarity is guessed wrong
    // holds the machine in reset forever and looks exactly like a dead
    // board. It can be added once the board is known to work, which is
    // the only state in which it is worth anything.

    reg [POR_BITS-1:0] por = {POR_BITS{1'b0}};
    wire rst_n = &por;

    always @(posedge sclk)
        if (!pll_lock)   por <= {POR_BITS{1'b0}};
        else if (!rst_n) por <= por + 1'b1;

    // The raster's reset: the system's, brought into the pixel domain
    // through two flip-flops. Nothing coordinates the two releases and
    // nothing needs to — the domains only meet inside dual-clock block
    // RAMs, and a frame of nonsense at power-on is 16 ms nobody sees.
    reg [1:0] prst_sync;
    wire prst_n = prst_sync[1];

    always @(posedge pclk)
        prst_sync <= {prst_sync[0], rst_n};

    // -------------------------------------------------------------- LED
    //
    // led[2:0] is R, G, B — the order $FE03 uses, so the boot ROM's $01
    // is blue.

    wire [2:0] led;

    assign {led_r, led_g, led_b} = LED_ACTIVE_LOW ? ~led : led;

    // ---------------------------------------------------------- machine
    //
    // Every parameter left at its default, which is what
    // sim/tb/cool8_soc_boot_tb.v simulates. `irq` is tied low here and
    // is not the only source: the video block's raster and vblank
    // interrupts are ORed in inside cool8_soc. What is still missing is
    // the timer and the keyboard, at M7 and M6, and the break button
    // with the monitor it would break into.

    wire [11:0] rgb;

    assign {vga_r, vga_g, vga_b} = rgb;

    cool8_soc u_soc (
        .clk(sclk), .rst_n(rst_n),
        .pclk(pclk), .prst_n(prst_n),
        .uart_rx(uart_rx), .uart_tx(uart_tx),
        .rgb(rgb), .hsync_n(vga_hs), .vsync_n(vga_vs),
        .led(led),
        .irq(1'b0), .nmi(1'b0),
        .o_halted()
    );

endmodule

`default_nettype wire
