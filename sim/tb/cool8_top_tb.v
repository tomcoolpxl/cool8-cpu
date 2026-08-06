// cool8_top_tb — the three things the board wrapper adds.
//
// cool8_soc has its own testbenches and this one deliberately does not
// repeat them. What is only true at the top is:
//
//   1. Reset is manufactured, and it releases. A power-on counter that
//      never finishes is a board that does nothing at all, with no
//      symptom to read.
//   2. The LED pins are the inverse of the register, because the LED is
//      common anode. Getting this backwards is the difference between a
//      machine that reports its state and one that reports the opposite.
//   3. `uart_rx` and `uart_tx` reach the UART the right way round.
//
// So it drives the pins and nothing else — no hierarchical peeking, no
// deposited memory — and talks to the machine the way the iCELink
// bridge will. The boot ROM is not run here; sim/tb/cool8_soc_boot_tb.v
// does that, and doing it again at 115200 baud would add half a minute
// to say the same thing.
//
//   vvp cool8_top_tb.vvp
//
// Plusargs:
//   +vcd=FILE   dump waves

`default_nettype none
`timescale 1ns / 1ps

module cool8_top_tb;

    // A short power-on counter, so the test is about the counter
    // finishing rather than about waiting 4096 clocks for it.
    localparam integer POR_BITS = 5;
    localparam integer DIV0 = 15;

    localparam [7:0] ACK = 8'h4B, VERSION = 8'h01;
    localparam [7:0] C_WRITE = 8'h01, C_READ = 8'h02, C_HALT = 8'h04,
                     C_PING = 8'h07;

    reg          clk = 1'b0;
    integer      errors, checks, bitclk, n;
    reg [1023:0] vcdfile;

    reg          host_tx = 1'b1;
    reg [7:0]    csum_tx;

    wire         uart_tx;
    wire         led_r, led_g, led_b;

    // The PS/2 lines are open drain with a pull-up on the shifter, so
    // they are modelled as exactly that: nobody drives them high, and
    // with no keyboard plugged in the pull-up is the only thing on them.
    // Tying them to 1'b1 instead would fight the wrapper's own driver
    // the moment it pulled one down, and resolve to x.
    wire         ps2_clk, ps2_dat;
    pullup (ps2_clk);
    pullup (ps2_dat);

    reg [7:0]    rxq [0:255];
    integer      rxq_wr, rxq_rd;
    reg [7:0]    rxbyte, rxcsum, got8;

    always #5 clk = ~clk;

    // ------------------------------------------------------------ DUT
    //
    // No reset port: there is no reset pin on the board and that is the
    // point of the wrapper. The only stimulus is a clock and a wire.

    cool8_top #(
        .POR_BITS(POR_BITS),
        .PLL_SIM(1),                       // cells_sim.v gives the PLL no body
        .LED_ACTIVE_LOW(1),
        // The loader is a build option and the shipping image does not
        // carry it; this phase is about the board wrapper reaching it, so
        // it asks for the bring-up configuration.
        .LOADER(1)
    ) u_top (
        // The break button is not pressed. Left dangling it would be X,
        // and an X on NMI is an interrupt at a random instant.
        .clk(clk), .sw0(1'b1),
        .uart_rx(host_tx), .uart_tx(uart_tx),
        .led_r(led_r), .led_g(led_g), .led_b(led_b),
        // The PLL and the raster are the wrapper's now, so this
        // testbench carries the VGA pins whether it looks at them or
        // not — cool8_video_tb is where the picture is checked.
        .vga_r(), .vga_g(), .vga_b(), .vga_hs(), .vga_vs(),
        .ps2_clk(ps2_clk), .ps2_dat(ps2_dat),
        .flash_cs(), .flash_sck(), .flash_mosi(), .flash_miso(1'b1)
    );

    // The UART divider is cool8_soc's default, 72 for 115200 at 8.375 MHz,
    // and running the whole test at that rate would be slow for no
    // information. So the first thing the host does is reprogram it —
    // which is also a check that the default is what it claims to be,
    // since a frame sent at 73 clocks a bit only lands if it is.
    // ------------------------------------------------- the host's UART

    task send_bit;
        input b;
        begin
            host_tx <= b;
            repeat (bitclk) @(posedge clk);
        end
    endtask

    task send_byte;
        input [7:0] b;
        integer k;
        begin
            send_bit(1'b0);
            for (k = 0; k < 8; k = k + 1) send_bit(b[k]);
            send_bit(1'b1);
            repeat (bitclk) @(posedge clk);
        end
    endtask

    initial begin : receiver
        reg [7:0] b;
        integer k;
        rxq_wr = 0;
        rxq_rd = 0;
        // Nothing drives the line until the machine's own reset lets go,
        // and before that uart_tx is undriven rather than idle-high.
        repeat (4 * (1 << POR_BITS)) @(posedge clk);
        forever begin
            @(negedge uart_tx);
            repeat (bitclk + (bitclk / 2)) @(posedge clk);
            for (k = 0; k < 8; k = k + 1) begin
                b[k] = uart_tx;
                if (k < 7) repeat (bitclk) @(posedge clk);
            end
            repeat (bitclk) @(posedge clk);
            rxq[rxq_wr] = b;
            rxq_wr = rxq_wr + 1;
        end
    end

    task put;
        input [7:0] b;
        begin
            csum_tx = csum_tx + b;
            send_byte(b);
        end
    endtask

    task send_frame;
        input [7:0] cmd;
        input [15:0] a;
        input [15:0] l;
        begin
            send_byte(8'hC8);
            send_byte(8'h8C);
            csum_tx = 8'h00;
            put(cmd);
            put(a[7:0]);
            put(a[15:8]);
            put(l[7:0]);
            put(l[15:8]);
        end
    endtask

    task chk;
        input [511:0] name;
        input [31:0] got;
        input [31:0] exp;
        begin
            checks = checks + 1;
            if (got !== exp) begin
                errors = errors + 1;
                $display("FAIL %0s: got %0h, expected %0h", name, got, exp);
            end
        end
    endtask

    task get_reply;
        output [7:0] b;
        integer k;
        begin
            k = 0;
            while (rxq_rd == rxq_wr && k < 64 * bitclk * 16) begin
                @(posedge clk);
                k = k + 1;
            end
            if (rxq_rd == rxq_wr) begin
                errors = errors + 1;
                $display("FAIL: timed out waiting for a reply byte");
                b = 8'h00;
            end else begin
                b = rxq[rxq_rd];
                rxq_rd = rxq_rd + 1;
            end
        end
    endtask

    task bus_write;
        input [511:0] name;
        input [15:0] a;
        input [7:0] d;
        begin
            send_frame(C_WRITE, a, 16'd1);
            put(d);
            send_byte(csum_tx);
            get_reply(rxbyte);
            chk(name, {24'd0, rxbyte}, {24'd0, ACK});
        end
    endtask

    task chk_read;
        input [511:0] name;
        input [15:0] a;
        input [7:0] exp;
        begin
            send_frame(C_READ, a, 16'd1);
            send_byte(csum_tx);
            get_reply(got8);
            get_reply(rxcsum);
            chk(name, {24'd0, got8}, {24'd0, exp});
        end
    endtask

    // ==================================================================

    initial begin
        errors = 0;
        checks = 0;
        bitclk = 73;                     // cool8_soc's default divider + 1

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_top_tb);
        end

        // ---------------------------------------------------------- 1
        // The machine holds itself down and then lets go. Nothing drives
        // reset from outside, so if the counter is wrong this hangs and
        // the timeout below is the only symptom — which is exactly the
        // symptom a dead board gives, and the reason to check it here
        // where there is a waveform.

        chk("held in reset at power-on", {31'd0, u_top.rst_n}, 32'd0);
        n = 0;
        while (!u_top.rst_n && n < 8 * (1 << POR_BITS)) begin
            @(posedge clk);
            #1;                          // let the counter settle first
            n = n + 1;
        end
        chk("reset released", {31'd0, u_top.rst_n}, 32'd1);

        // And it counted to get there. A reset tied high would pass the
        // check above and leave the SPRAM's own power-up unwaited-for.
        checks = checks + 1;
        if (n < (1 << POR_BITS) - 2 || n > (1 << POR_BITS) + 2) begin
            errors = errors + 1;
            $display("FAIL: reset released after %0d clocks, expected ~%0d",
                     n, 1 << POR_BITS);
        end

        // The LED register resets to zero and the pins are the inverse,
        // so a board that has just configured is lit. That is worth
        // knowing before looking at one: dark means nothing has run.
        chk("all three pins high at reset",
            {29'd0, led_r, led_g, led_b}, 32'b111);

        // ---------------------------------------------------------- 2
        // The wire is connected the right way round, at the divider the
        // bitstream carries. A frame only lands if both are true.

        send_frame(C_PING, 16'd0, 16'd0);
        send_byte(csum_tx);
        get_reply(rxbyte);
        chk("PING at the default 115200", {24'd0, rxbyte}, {24'd0, VERSION});

        // Now drop to something quick for the rest. The reply to this
        // frame is unreadable by construction — the divider lands before
        // the checksum byte is sent, so the two ends are at different
        // rates for one byte — so it is drained rather than checked.
        // docs/04-system.md section 4.6 says as much.
        send_frame(C_WRITE, 16'hFE72, 16'd1);
        put(DIV0[7:0]);
        send_byte(csum_tx);
        bitclk = DIV0 + 1;
        repeat (48 * bitclk) @(posedge clk);
        rxq_rd = rxq_wr;
        send_frame(C_PING, 16'd0, 16'd0);
        send_byte(csum_tx);
        get_reply(rxbyte);
        chk("PING at the new rate", {24'd0, rxbyte}, {24'd0, VERSION});

        send_frame(C_HALT, 16'd0, 16'd0);
        send_byte(csum_tx);
        get_reply(rxbyte);
        chk("HALT", {24'd0, rxbyte}, {24'd0, ACK});

        // ---------------------------------------------------------- 3
        // The pins are the inverse of the register, and each colour is
        // its own pin. $FE03 bit 2 is red, bit 1 green, bit 0 blue — the
        // order sw/boot.asm's $01 relies on to mean blue.

        bus_write("LED := $00", 16'hFE03, 8'h00);
        chk("nothing lit is all pins high",
            {29'd0, led_r, led_g, led_b}, 32'b111);

        bus_write("LED := $04, red", 16'hFE03, 8'h04);
        chk("red pin low, the others high",
            {29'd0, led_r, led_g, led_b}, 32'b011);

        bus_write("LED := $02, green", 16'hFE03, 8'h02);
        chk("green pin low",
            {29'd0, led_r, led_g, led_b}, 32'b101);

        bus_write("LED := $01, blue", 16'hFE03, 8'h01);
        chk("blue pin low — what the boot ROM leaves behind",
            {29'd0, led_r, led_g, led_b}, 32'b110);

        bus_write("LED := $07, white", 16'hFE03, 8'h07);
        chk("all three low",
            {29'd0, led_r, led_g, led_b}, 32'b000);

        chk_read("the register still reads unnegated", 16'hFE03, 8'h07);

        // And the machine underneath really is the one with the boot ROM
        // in it, not an empty map — a top wired to the wrong parameters
        // would answer everything above just the same.
        chk_read("SYSCTRL: ROMEN set", 16'hFE00, 8'h01);
        chk_read("SYSSTAT is the default build id", 16'hFE02, 8'h05);

        $display("\n  %0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("\nPASS");
        else             $display("\nFAIL");
        $finish;
    end

    initial begin
        #20000000;
        $display("FAIL: timed out — the power-on reset may never release");
        $display("\nFAIL");
        $finish;
    end

endmodule

`default_nettype wire
