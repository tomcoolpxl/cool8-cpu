// cool8_wire_tb — the serial port as a pipe, so the host tool can be
// tested against the machine instead of against a description of it.
//
// This has no opinions. It bit-bangs a script onto `uart_rx`, records
// everything that comes back off `uart_tx`, and writes that to another
// file. Every check lives in sim/test_load.py, which builds the script
// with tools/cool8load.py's own frame builder and parses the output with
// its own reply parser — so what is under test is whether the host's
// idea of the wire format is the board's idea of it.
//
// The script is nine bits wide, because a host does two things and one
// of them is waiting:
//
//   0xx   send this byte
//   1nn   wait until nn more reply bytes have arrived
//
// The waiting is not politeness. The loader ignores its receiver from
// the moment it asks for the bus until it has finished answering, so a
// frame sent on top of the previous reply is dropped without a trace —
// found here, on the first run, by a script that did not wait.
// docs/07-loader.md section 3 states the rule.
//
// Recorded rather than interactive: no host frame depends on the
// *content* of the reply before it, only on its arrival. Retry-on-NAK is
// the one thing that does, and it is pure Python, unit-tested in
// sim/test_load.py against a fake board.
//
// The boot ROM is a two-byte spin loop, so the CPU is genuinely
// executing and granting the bus at instruction boundaries for the whole
// run without ever touching RAM of its own accord — until something is
// loaded and told to GO, which is the point.
//
//   vvp cool8_wire_tb.vvp +in=session.hex +out=replies.hex
//
// Plusargs:
//   +in=FILE    the script, three hex digits per line, ending xxx
//   +out=FILE   bytes received, two hex digits per line
//   +vcd=FILE   dump waves

`default_nettype none
`timescale 1ns / 1ps

module cool8_wire_tb;

    localparam [15:0] DIV0 = 16'd15;
    localparam integer MAXIN = 16384;
    localparam integer MAXOUT = 16384;

    // Stop when the board has been quiet this long. A READ of 256 bytes
    // answers with 257, so a fixed drain would have to be sized for the
    // largest reply anyone might ever ask for; going idle is the honest
    // end of a session.
    localparam integer IDLE_BITS = 40;

    reg          clk = 1'b0;
    reg          pclk = 1'b0;
    reg          rst_n = 1'b0;

    integer      bitclk, i, n, idle, fh, sent, got;
    reg [1023:0] vcdfile, infile, outfile;

    reg          host_tx = 1'b1;
    wire         uart_tx;
    wire [2:0]   led;
    wire         o_halted;

    reg [8:0]    inq [0:MAXIN-1];
    reg [7:0]    outq [0:MAXOUT-1];
    integer      outq_wr, want, waited, stalls;

    always #5 clk = ~clk;
    // The raster's clock. Incommensurate with the system's on
    // purpose: the video subsystem is inside the SoC now and the
    // only thing these tests want from it is that its clock
    // crossing does not disturb anything on this side of it.
    always #2.39 pclk = ~pclk;

    cool8_soc #(
        .ROM_INIT(0),
        .UART_DIV(DIV0),
        .RX_ABITS(4)
    ) u_soc (
        .clk(clk), .rst_n(rst_n),
        .pclk(pclk), .prst_n(rst_n),
        .rgb(), .hsync_n(), .vsync_n(),
        .uart_rx(host_tx), .uart_tx(uart_tx),
        // Idle high, which is what the pull-ups give when nothing is
        // plugged in. Left floating they are x, and x on the PS/2
        // clock reaches the filter and then the whole block.
        .ps2_clk_i(1'b1), .ps2_dat_i(1'b1),
        .ps2_clk_oe(), .ps2_dat_oe(),
        .spi_cs_n(), .spi_sck(), .spi_mosi(), .spi_miso(1'b1),
        .led(led),
        .irq(1'b0), .nmi(1'b0),
        .o_halted(o_halted)
    );

    // ------------------------------------------------------------ wire

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
        outq_wr = 0;
        wait (rst_n);
        forever begin
            @(negedge uart_tx);
            repeat (bitclk + (bitclk / 2)) @(posedge clk);
            for (k = 0; k < 8; k = k + 1) begin
                b[k] = uart_tx;
                if (k < 7) repeat (bitclk) @(posedge clk);
            end
            repeat (bitclk) @(posedge clk);
            if (outq_wr < MAXOUT) begin
                outq[outq_wr] = b;
                outq_wr = outq_wr + 1;
            end
        end
    end

    // -------------------------------------------------------- boot ROM

    task fill_rom;
        integer k;
        begin
            for (k = 0; k < 4096; k = k + 1)
                u_soc.u_mem.u_rom.rom[k] = 8'h00;
            u_soc.u_mem.u_rom.rom[12'h000] = 8'h70;      // BRA -2
            u_soc.u_mem.u_rom.rom[12'h001] = 8'hFE;
            u_soc.u_mem.u_rom.rom[12'hFF8] = 8'h00;      // RESET = $F000
            u_soc.u_mem.u_rom.rom[12'hFF9] = 8'hF0;
        end
    endtask

    // ==================================================================

    initial begin
        bitclk = DIV0 + 1;

        if (!$value$plusargs("in=%s", infile))   infile  = "session.hex";
        if (!$value$plusargs("out=%s", outfile)) outfile = "replies.hex";
        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_wire_tb);
        end

        for (i = 0; i < MAXIN; i = i + 1) inq[i] = 9'hxxx;
        $readmemh(infile, inq);
        n = 0;
        while (n < MAXIN && inq[n] !== 9'hxxx) n = n + 1;

        fill_rom;
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (8) @(posedge clk);

        sent = 0;
        stalls = 0;
        for (i = 0; i < n; i = i + 1) begin
            if (inq[i][8]) begin
                // Wait for the board to finish answering before saying
                // anything else, which is what a host has to do.
                want = outq_wr + inq[i][7:0];
                waited = 0;
                while (outq_wr < want && waited < 400) begin
                    repeat (bitclk) @(posedge clk);
                    waited = waited + 1;
                end
                if (outq_wr < want) stalls = stalls + 1;
            end else begin
                send_byte(inq[i][7:0]);
                sent = sent + 1;
            end
        end

        // Let the board finish answering. A GO in the session leaves a
        // program running, so this also collects whatever it says.
        idle = 0;
        got = outq_wr;
        n = 0;
        while (idle < IDLE_BITS && n < 200000) begin
            repeat (bitclk) @(posedge clk);
            n = n + 1;
            if (outq_wr != got) begin
                got = outq_wr;
                idle = 0;
            end else idle = idle + 1;
        end

        fh = $fopen(outfile, "w");
        for (i = 0; i < outq_wr; i = i + 1) $fwrite(fh, "%02x\n", outq[i]);
        $fclose(fh);

        $display("  sent %0d bytes, received %0d, %0d reply timeout(s)",
                 sent, outq_wr, stalls);
        $display("\nPASS");
        $finish;
    end

    initial begin
        #200000000;
        $display("FAIL: timed out");
        $display("\nFAIL");
        $finish;
    end

endmodule

`default_nettype wire
