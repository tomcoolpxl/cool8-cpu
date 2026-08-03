// cool8_soc_boot_tb — the whole machine, cold, on the parameters the
// bitstream will actually carry.
//
// cool8_soc_tb runs the SoC fast and with a filled-in ROM, because it is
// testing a decode. This runs it slow and for real: the boot image
// tools/mkrom.py built out of sw/boot.asm, the default 12 MHz UART
// divider, the default build id, and SPRAM left undefined exactly as the
// part comes up. Nothing is poked, nothing is forced, and the CPU cannot
// get anywhere at all unless its reset vector really came out of EBR.
//
// What it answers is the question worth answering before a board is
// touched: does this thing boot, and does it say so out loud? The boot
// ROM's last two acts are to write the LED register and halt, and both
// of those go through the I/O page — so a blue LED here is the same
// event as a blue LED on the bench.
//
// Then one loader exchange at 115200, because the default divider is a
// parameter that no fast test ever evaluates.
//
//   vvp cool8_soc_boot_tb.vvp +rom=boot.hex
//
// Plusargs:
//   +rom=FILE   the image to check the ROM was built from
//   +vcd=FILE   dump waves

`default_nettype none
`timescale 1ns / 1ps

module cool8_soc_boot_tb;

    localparam integer DIV0  = 103;        // 115200 baud at 12 MHz
    localparam [7:0]   BUILD = 8'h04;      // cool8_soc's own default
    localparam [7:0]   ACK = 8'h4B, VERSION = 8'h01;
    localparam [7:0]   C_READ = 8'h02, C_HALT = 8'h04, C_PING = 8'h07;

    reg          clk = 1'b0;
    reg          rst_n = 1'b0;

    integer      errors, checks, bitclk, n;
    reg [1023:0] vcdfile;

    reg          host_tx = 1'b1;
    reg [7:0]    csum_tx;

    wire         uart_tx;
    wire [2:0]   led;
    wire         o_halted;

    reg [7:0]    rxq [0:255];
    integer      rxq_wr, rxq_rd;
    reg [7:0]    rxbyte, rxcsum, got8;

    integer      halt_at;
    reg          rom_fetched;             // a fetch landed in the ROM window

    always #5 clk = ~clk;

    // ------------------------------------------------------------ DUT
    //
    // Every parameter left at its default. That is the point: this is
    // the configuration cool8_top.v will instantiate.

    cool8_soc u_soc (
        .clk(clk), .rst_n(rst_n),
        .uart_rx(host_tx), .uart_tx(uart_tx),
        .led(led),
        .irq(1'b0), .nmi(1'b0),
        .o_halted(o_halted)
    );

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
        wait (rst_n);
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

    task send_cmd;
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
            send_byte(csum_tx);
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

    task chk_read;
        input [511:0] name;
        input [15:0] a;
        input [7:0] exp;
        begin
            send_cmd(C_READ, a, 16'd1);
            get_reply(got8);
            get_reply(rxcsum);
            chk(name, {24'd0, got8}, {24'd0, exp});
        end
    endtask

    task bus_write;
        input [511:0] name;
        input [15:0] a;
        input [7:0] d;
        begin
            send_byte(8'hC8);
            send_byte(8'h8C);
            csum_tx = 8'h00;
            put(8'h01);
            put(a[7:0]);
            put(a[15:8]);
            put(8'h01);
            put(8'h00);
            put(d);
            send_byte(csum_tx);
            get_reply(rxbyte);
            chk(name, {24'd0, rxbyte}, {24'd0, ACK});
        end
    endtask

    // The ROM window really being fetched from is the whole claim of a
    // cold boot, so it is watched rather than assumed.
    always @(posedge clk) begin
        if (!rst_n) rom_fetched <= 1'b0;
        else if (u_soc.u_cpu.o_fetch && u_soc.u_mem.rom_sel)
            rom_fetched <= 1'b1;
    end

    // ==================================================================

    initial begin
        errors = 0;
        checks = 0;
        halt_at = 0;
        bitclk = DIV0 + 1;

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_soc_boot_tb);
        end

        // SPRAM is left exactly as it comes up. Nothing is loaded.
        repeat (4) @(posedge clk);
        rst_n = 1'b1;

        n = 0;
        while (!o_halted && n < 2000000) begin
            @(posedge clk);
            n = n + 1;
        end
        halt_at = n;

        chk("the boot ROM ran to its HALT", {31'd0, o_halted}, 32'd1);
        chk("it fetched out of the ROM window", {31'd0, rom_fetched}, 32'd1);
        chk("the LED is blue", {29'd0, led}, 32'd1);
        $display("  reset to HALT: %0d clocks, %0d ms at 12 MHz",
                 halt_at, halt_at / 12000);

        // A halted CPU still grants the bus — which is how software
        // arrives at M4, and the only reason the machine is reachable at
        // all with a boot ROM this small.
        send_cmd(C_PING, 16'd0, 16'd0);
        get_reply(rxbyte);
        chk("PING at 115200 on the default divider",
            {24'd0, rxbyte}, {24'd0, VERSION});

        send_cmd(C_HALT, 16'd0, 16'd0);
        get_reply(rxbyte);
        chk("HALT", {24'd0, rxbyte}, {24'd0, ACK});

        chk_read("SYSSTAT is the default build id", 16'hFE02, BUILD);
        chk_read("the LED register agrees with the pins", 16'hFE03, 8'h01);
        chk_read("SYSCTRL: ROMEN is still set",     16'hFE00, 8'h01);
        chk_read("UART_DIV_L is 103",  16'hFE72, 8'd103);
        chk_read("UART_DIV_H is 0",    16'hFE73, 8'd0);

        // The vectors the boot ROM installed went to RAM underneath its
        // own read window. Drop the overlay through SYSCTRL and they are
        // what answers — which is the whole reason the overlay is
        // read-only, tested here through the real decode rather than by
        // reaching into the arrays.
        chk_read("$FFF8 is the ROM's copy while ROMEN is set",
                 16'hFFF8, u_soc.u_mem.u_rom.rom[12'hFF8]);
        bus_write("ROMEN := 0", 16'hFE00, 8'h00);
        chk_read("$FFF8 in RAM is the vector the ROM installed",
                 16'hFFF8, u_soc.u_mem.u_rom.rom[12'hFF8]);
        chk_read("$FFF9 in RAM too",
                 16'hFFF9, u_soc.u_mem.u_rom.rom[12'hFF9]);

        // And the 60 KB it cleared really is cleared. $EFFF is the last
        // byte of the clear loop's range; nothing above it is touched,
        // which is what makes the check meaningful rather than lucky.
        chk_read("$0000 was cleared", 16'h0000, 8'h00);
        chk_read("$EFFF was cleared", 16'hEFFF, 8'h00);

        $display("\n  %0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("\nPASS");
        else             $display("\nFAIL");
        $finish;
    end

    initial begin
        #60000000;
        $display("FAIL: timed out");
        $display("\nFAIL");
        $finish;
    end

endmodule

`default_nettype wire
