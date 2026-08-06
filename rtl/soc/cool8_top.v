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
    parameter LED_ACTIVE_LOW = 1,
    // The hardware loader, off by default — see cool8_soc. Build a
    // bring-up image with LOADER(1) and drop something else when a board
    // will not boot and you need the bus-master read-back.
    parameter LOADER = 0
) (
    input  wire clk,             // pin 35, 12 MHz from the iCELink debugger

    // SW[0], the break button. docs/04-system.md section 6: press it and
    // a hung program lands in the monitor with all of its state intact,
    // because an NMI pushes PC and F and changes nothing else. It is the
    // escape hatch that makes a machine with no other input device
    // debuggable, and it is what replaced the loader's HALT when the
    // loader became a build option.
    input  wire sw0,             // pin 18, P4_4
    input  wire uart_rx,         // pin 4
    output wire uart_tx,         // pin 6
    // Sound: one pin, 1-bit sigma-delta, into the RC low-pass and
    // coupling capacitor of docs/05-board.md. P1_3.
    output wire audio,           // pin 3

    output wire led_r,           // pin 40
    output wire led_g,           // pin 41
    output wire led_b,           // pin 39

    // MuseLab PMOD-VGA on PMOD2 + PMOD3 — docs/05-board.md section 3
    output wire [3:0] vga_r,
    output wire [3:0] vga_g,
    output wire [3:0] vga_b,
    output wire vga_hs,
    output wire vga_vs,

    // PS/2 keyboard through the level shifter of docs/05-board.md
    // section 4.1. Open drain both ways: the machine only ever pulls a
    // line down, and the pull-up on the shifter provides the high.
    inout  wire ps2_clk,         // pin 27
    inout  wire ps2_dat,         // pin 25

    // The configuration flash, pins 14-17. The iCE40 hands these to user
    // logic once CDONE goes high, so nothing here drives them while the
    // bitstream is still loading — see docs/05-board.md section 2.
    output wire flash_cs,
    output wire flash_sck,
    output wire flash_mosi,
    input  wire flash_miso
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

    // ------------------------------------------------------ break button
    //
    // Fire once on a press and then ignore the switch for 62 ms, which is
    // longer than any contact bounces for. That is cheaper than a
    // stability counter and it is the behaviour a break button wants
    // anyway: one NMI per press, however untidily the contact closes.
    //
    // The core's NMI input is edge sensitive already, so a single-cycle
    // pulse is the whole interface.
    //
    // **The polarity is the one thing here not checked against hardware.**
    // The iCESugar's tactile switches pull to ground, so a press is a low
    // — the same assumption, and the same caveat, as LED_ACTIVE_LOW.

    reg [1:0]  sw_sync;
    reg [18:0] brk_hold;         // 2^19 / 8.375 MHz = 62 ms
    reg        brk_nmi;

    always @(posedge sclk) begin
        if (!rst_n) begin
            sw_sync  <= 2'b11;
            brk_hold <= 19'd0;
            brk_nmi  <= 1'b0;
        end else begin
            sw_sync <= {sw_sync[0], sw0};
            brk_nmi <= 1'b0;
            if (|brk_hold)         brk_hold <= brk_hold - 1'b1;
            else if (!sw_sync[1]) begin
                brk_nmi  <= 1'b1;
                brk_hold <= {19{1'b1}};
            end
        end
    end

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
    // interrupts and the keyboard's are ORed in inside cool8_soc. What
    // is still missing is the timer, at M7, and the break button.

    wire [11:0] rgb;

    assign {vga_r, vga_g, vga_b} = rgb;

    // ----------------------------------------------------- the PS/2 pads
    //
    // The only tri-state in the design, and it is here rather than in
    // cool8_ps2 so that block stays a testable pair of levels and
    // enables. A PS/2 line is never driven high by anybody: the device
    // and the host both pull down and let go, and the pull-up does the
    // rest. Driving one high would put two outputs in opposition the
    // moment both ends spoke at once, which is exactly what the
    // request-to-send handshake arranges.

    wire ps2_clk_oe, ps2_dat_oe;

    assign ps2_clk = ps2_clk_oe ? 1'b0 : 1'bz;
    assign ps2_dat = ps2_dat_oe ? 1'b0 : 1'bz;

    cool8_soc #(.LOADER(LOADER)) u_soc (
        .clk(sclk), .rst_n(rst_n),
        .pclk(pclk), .prst_n(prst_n),
        .uart_rx(uart_rx), .uart_tx(uart_tx),
        .ps2_clk_i(ps2_clk), .ps2_dat_i(ps2_dat),
        .ps2_clk_oe(ps2_clk_oe), .ps2_dat_oe(ps2_dat_oe),
        .spi_cs_n(flash_cs), .spi_sck(flash_sck),
        .spi_mosi(flash_mosi), .spi_miso(flash_miso),
        .rgb(rgb), .hsync_n(vga_hs), .vsync_n(vga_vs),
        .audio(audio),
        .led(led),
        .irq(1'b0), .nmi(brk_nmi),
        .o_halted()
    );

endmodule

`default_nettype wire
