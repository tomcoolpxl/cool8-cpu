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
    // The data pins are `inout` and go through SB_IO below, which is not
    // optional on this part -- see the instantiation for why. Chip
    // select and the clock are ordinary outputs, exactly as picosoc has
    // them.
    output wire flash_cs,
    output wire flash_sck,
    inout  wire flash_mosi,
    inout  wire flash_miso,

    // /WP and /HOLD on the W25Q64, both active low and both driven
    // high. They are not optional: floating, /HOLD freezes the chip.
    inout  wire flash_wp,
    inout  wire flash_hold
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
    // **Stability, not a hold-off.** The first version of this fired the
    // moment the pin read low and then ignored it for 62 ms, which is the
    // usual way to absorb contact bounce — and it is the wrong way round
    // for a pin that might not be connected to anything. An iCE40 input
    // with nothing holding it floats, a floating input oscillates, and
    // that version fired an NMI on every oscillation it caught. On a real
    // board it produced a machine taking interrupts continuously.
    //
    // So the line has to be **continuously low for two milliseconds**
    // before it counts as a press. The counter resets on any high sample,
    // so noise never accumulates; it saturates at the top, so one press
    // gives exactly one NMI however untidily the contact closes; and it
    // cannot fire again until the button is released.
    //
    // The pin also carries a pull-up now — see board/icesugar.pcf. Both
    // are needed: the pull-up makes an unconnected pin read as released,
    // and the counter makes a noisy one harmless.
    //
    // docs/04-system.md section 6: press it and a hung program lands in
    // the monitor with all of its state intact, because an NMI pushes PC
    // and F and changes nothing else.

    reg [1:0]  sw_sync;
    reg [13:0] sw_low;           // 2^14 / 8.375 MHz = 1.96 ms
    reg        brk_nmi;

    always @(posedge sclk) begin
        if (!rst_n) begin
            sw_sync <= 2'b11;
            sw_low  <= 14'd0;
            brk_nmi <= 1'b0;
        end else begin
            sw_sync <= {sw_sync[0], sw0};
            brk_nmi <= 1'b0;
            if (sw_sync[1]) begin
                sw_low <= 14'd0;                   // released, or noise
            end else if (~&sw_low) begin
                sw_low  <= sw_low + 1'b1;
                brk_nmi <= (sw_low == {{13{1'b1}}, 1'b0});
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

    // ------------------------------------------------- the flash's pins
    //
    // **These four are the configuration pins and they need SB_IO by
    // hand.** Declared as a plain `output`/`input` pair the design
    // builds, meets timing, passes every testbench -- and drives
    // nothing at all on the board: every read comes back $FF because
    // the input floats, and every write vanishes because the output was
    // never driven. That is what this machine did from the day the
    // flash reader was written until the day someone finally read a
    // directory off a real chip.
    //
    // Both of the vendor's own designs that use this flash do it this
    // way and neither leaves it to inference:
    //
    //   picosoc  SB_IO #(.PIN_TYPE(6'b1010_01), .PULLUP(0))
    //            over {flash_io3, flash_io2, flash_io1, flash_io0}
    //   icicle   io0_en / io1_en carried out to the top level
    //
    // `1010_01` is a simple (unregistered) output with its enable under
    // control, and a simple input. We only ever drive MOSI and only
    // ever read MISO, so the enables are constants -- but they have to
    // exist, because it is the *primitive* that claims the pin.
    //
    // Chip select and the clock are ordinary outputs; picosoc leaves
    // those inferred too.
    // All four, exactly as picosoc drives them: io0 out, io1 in, and
    // **io2/io3 driven high**. /WP and /HOLD are active low on a
    // W25Q64, and a floating /HOLD stops the chip responding at all --
    // which is what this machine did, in both directions, for as long
    // as the flash reader has existed.
    wire [3:0] flash_io_i;
    wire       flash_mosi_o;

    // Four named instances, not one [3:0] array: iverilog refuses an
    // instance array of a module whose ports carry default values —
    // which every SB_ primitive in yosys's cells_sim.v does — with a
    // "sorry", and sim/test_soc.py compiles exactly that combination.
    // Same gates either way; only the elaborator cares.
    SB_IO #(.PIN_TYPE(6'b1010_01), .PULLUP(1'b0)) u_flash_io3 (
        .PACKAGE_PIN(flash_hold), .OUTPUT_ENABLE(1'b1),
        .D_OUT_0(1'b1), .D_IN_0(flash_io_i[3]));
    SB_IO #(.PIN_TYPE(6'b1010_01), .PULLUP(1'b0)) u_flash_io2 (
        .PACKAGE_PIN(flash_wp), .OUTPUT_ENABLE(1'b1),
        .D_OUT_0(1'b1), .D_IN_0(flash_io_i[2]));
    SB_IO #(.PIN_TYPE(6'b1010_01), .PULLUP(1'b0)) u_flash_io1 (
        .PACKAGE_PIN(flash_miso), .OUTPUT_ENABLE(1'b0),
        .D_OUT_0(1'b0), .D_IN_0(flash_io_i[1]));
    SB_IO #(.PIN_TYPE(6'b1010_01), .PULLUP(1'b0)) u_flash_io0 (
        .PACKAGE_PIN(flash_mosi), .OUTPUT_ENABLE(1'b1),
        .D_OUT_0(flash_mosi_o), .D_IN_0(flash_io_i[0]));

    wire flash_miso_i = flash_io_i[1];

    cool8_soc #(.LOADER(LOADER)) u_soc (
        .clk(sclk), .rst_n(rst_n),
        .pclk(pclk), .prst_n(prst_n),
        .uart_rx(uart_rx), .uart_tx(uart_tx),
        .ps2_clk_i(ps2_clk), .ps2_dat_i(ps2_dat),
        .ps2_clk_oe(ps2_clk_oe), .ps2_dat_oe(ps2_dat_oe),
        .spi_cs_n(flash_cs), .spi_sck(flash_sck),
        .spi_mosi(flash_mosi_o), .spi_miso(flash_miso_i),
        .rgb(rgb), .hsync_n(vga_hs), .vsync_n(vga_vs),
        .audio(audio),
        .led(led),
        .irq(1'b0), .nmi(brk_nmi),
        .o_halted()
    );

endmodule

`default_nettype wire
