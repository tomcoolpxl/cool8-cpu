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
    // 2^POR_BITS clocks of reset after configuration: 4096 is 341 us at
    // 12 MHz, which is far longer than anything needs and costs 12
    // flip-flops.
    parameter POR_BITS = 12,
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
    output wire led_b            // pin 39
);

    // ------------------------------------------------------------ reset
    //
    // The board has no reset pin and no button assigned to one, so reset
    // is made here. iCE40 flip-flops come out of configuration at zero,
    // so a counter that stops at all-ones holds the machine down for
    // 2^POR_BITS clocks and then never moves again — no free-running
    // counter, no second edge, nothing to glitch later.
    //
    // No button for it on purpose. `SW[0]` is spoken for as the NMI
    // break button (04-system.md section 6) and the other three are
    // unassigned, but a reset button whose polarity is guessed wrong
    // holds the machine in reset forever and looks exactly like a dead
    // board. It can be added once the board is known to work, which is
    // the only state in which it is worth anything.

    reg [POR_BITS-1:0] por = {POR_BITS{1'b0}};
    wire rst_n = &por;

    always @(posedge clk)
        if (!rst_n) por <= por + 1'b1;

    // -------------------------------------------------------------- LED
    //
    // led[2:0] is R, G, B — the order $FE03 uses, so the boot ROM's $01
    // is blue.

    wire [2:0] led;

    assign {led_r, led_g, led_b} = LED_ACTIVE_LOW ? ~led : led;

    // ---------------------------------------------------------- machine
    //
    // Every parameter left at its default, which is what
    // sim/tb/cool8_soc_boot_tb.v simulates. There are no interrupt
    // sources yet: the timer, video and keyboard arrive at M5 and M7,
    // and the break button with the monitor it would break into at M6.

    cool8_soc u_soc (
        .clk(clk), .rst_n(rst_n),
        .uart_rx(uart_rx), .uart_tx(uart_tx),
        .led(led),
        .irq(1'b0), .nmi(1'b0),
        .o_halted()
    );

endmodule

`default_nettype wire
