// cool8_loader_tb — the UART and the hardware loader, over a real wire,
// against a real CPU.
//
// The loader is a bus master that nobody has ever watched work. Every
// interesting part of it is a handshake with something else — the UART's
// bit timing, the CPU's bus grant, the memory's ready line — so testing
// it against a byte-level stub would test nothing that is likely to be
// wrong. This testbench therefore has no stubs on the paths that matter:
//
//   - The host end is a bit-banged 8N1 line driven at the divider the
//     UART is programmed with. Bytes go in as edges on rx_pin and come
//     back out as edges on tx_pin, sampled by an independent receiver.
//   - The bus is arbitrated by cool8_core's own busak, and the loader
//     only gets the memory when the CPU has actually let go of it.
//   - Memory takes a programmable number of wait states, because the
//     SPRAM at M4 item 2 will take one.
//
// The CPU spins in a two-byte `BRA -2` loop at $0000 for the whole run,
// so it is genuinely executing — granting the bus at instruction
// boundaries, not parked in HALT — and never writes anywhere. The GO
// test is the exception: it moves the CPU to a loaded program and checks
// that the program ran.
//
//   vvp cool8_loader_tb.vvp +div=103 +ws=1 +vcd=waves.vcd
//
// Plusargs:
//   +div=N     UART divider; the host end uses the same N+1 clocks a bit
//   +ws=N      N wait states on every memory access
//   +vcd=FILE  dump waves
//   +verbose   print every check, not just the failures

`default_nettype none
`timescale 1ns / 1ps

module cool8_loader_tb;

    // Verilog-2001 wants every declaration ahead of its use, and Icarus
    // enforces it. Everything the blocks below refer to lives here.

    reg          clk = 1'b0;
    reg          rst_n = 1'b0;

    integer      ws, errors, checks, bitclk, i;
    reg [15:0]   divr;
    reg          verbose;
    reg [1023:0] vcdfile;

    reg          host_tx = 1'b1;       // the host's line into rx_pin
    reg [7:0]    csum_tx;              // running checksum of a sent frame

    wire         uart_tx;
    wire [7:0]   rx_data;
    wire         rx_valid;
    wire [7:0]   tx_data;
    wire         tx_start;
    wire         tx_busy;

    reg [7:0]    rxq [0:2047];         // bytes seen coming back
    integer      rxq_wr, rxq_rd;
    reg [7:0]    rxbyte;

    reg [7:0]    fwdq [0:255];         // bytes passed through to the CPU
    integer      fwd_wr, fwd_rd;
    reg [7:0]    fwdbyte;

    wire [7:0]   fwd_data;
    wire         fwd_valid;

    wire         busrq, busak;
    wire [15:0]  ldr_addr;
    wire [7:0]   ldr_wdata;
    wire         ldr_read, ldr_write;
    wire         ldr_cpu_rst_n, bootram, halt_req;

    reg          ctrl_we;
    reg [7:0]    ctrl_wdata;
    wire [7:0]   ctrl_rdata, stat_rdata;

    wire [15:0]  cpu_addr;
    wire [7:0]   cpu_wdata;
    wire         cpu_read, cpu_write;
    wire         o_fetch, o_halted, o_iack, o_retire;

    wire [15:0]  bus_addr;
    wire [7:0]   bus_wdata;
    wire         bus_read, bus_write, bus_access;
    wire [7:0]   bus_rdata;
    reg          mem_ready;
    reg [7:0]    mem [0:65535];
    reg [7:0]    wcnt;

    reg          cpu_rst_n;
    integer      cycle;
    integer      busak_low;            // cycles busak has been seen low

    always #5 clk = ~clk;

    always @(posedge clk) cycle <= cycle + 1;

    // ------------------------------------------------------------ DUT

    cool8_uart u_uart (
        .clk(clk), .rst_n(rst_n),
        .div(divr),
        .rx_pin(host_tx), .tx_pin(uart_tx),
        .rx_data(rx_data), .rx_valid(rx_valid),
        .tx_data(tx_data), .tx_start(tx_start), .tx_busy(tx_busy)
    );

    cool8_loader u_ldr (
        .clk(clk), .rst_n(rst_n),
        .rx_data(rx_data), .rx_valid(rx_valid),
        .tx_data(tx_data), .tx_start(tx_start), .tx_busy(tx_busy),
        .fwd_data(fwd_data), .fwd_valid(fwd_valid),
        .busrq(busrq), .busak(busak),
        .mem_addr(ldr_addr), .mem_wdata(ldr_wdata), .mem_rdata(bus_rdata),
        .mem_read(ldr_read), .mem_write(ldr_write), .mem_ready(mem_ready),
        .cpu_rst_n(ldr_cpu_rst_n), .bootram(bootram), .halt_req(halt_req),
        .ctrl_we(ctrl_we), .ctrl_wdata(ctrl_wdata),
        .ctrl_rdata(ctrl_rdata), .stat_rdata(stat_rdata)
    );

    // The loader's CPU reset is ANDed with the testbench's, exactly as
    // rtl/soc/cool8_soc.v will have to do it at M4 item 4.
    always @* cpu_rst_n = rst_n & ldr_cpu_rst_n;

    cool8_core u_cpu (
        .clk(clk), .rst_n(cpu_rst_n),
        .mem_addr(cpu_addr), .mem_wdata(cpu_wdata), .mem_rdata(bus_rdata),
        .mem_read(cpu_read), .mem_write(cpu_write), .mem_ready(mem_ready),
        .irq(1'b0), .nmi(1'b0),
        .busrq(busrq), .busak(busak),
        .o_fetch(o_fetch), .o_halted(o_halted), .o_iack(o_iack),
        .o_retire(o_retire)
    );

    // ------------------------------------------------- bus and memory

    assign bus_addr  = busak ? ldr_addr  : cpu_addr;
    assign bus_wdata = busak ? ldr_wdata : cpu_wdata;
    assign bus_read  = busak ? ldr_read  : cpu_read;
    assign bus_write = busak ? ldr_write : cpu_write;
    assign bus_access = bus_read | bus_write;
    assign bus_rdata = mem[bus_addr];

    always @(posedge clk) begin
        if (bus_write && mem_ready) mem[bus_addr] <= bus_wdata;
    end

    always @(posedge clk) begin
        if (!rst_n)                wcnt <= ws[7:0];
        else if (!bus_access)      wcnt <= ws[7:0];
        else if (wcnt != 8'd0)     wcnt <= wcnt - 8'd1;
        else                       wcnt <= ws[7:0];
    end

    always @* mem_ready = (wcnt == 8'd0);

    // The core must be completely off the bus while it holds busak, or
    // the mux above is hiding a contention that a real board would not.
    always @(posedge clk) begin
        if (rst_n && busak && (cpu_read || cpu_write)) begin
            errors = errors + 1;
            $display("FAIL: CPU drove a strobe during a bus grant, cycle %0d",
                     cycle);
        end
    end

    // ------------------------------------------------- pass-through tap

    always @(posedge clk) begin
        if (rst_n && fwd_valid) begin
            fwdq[fwd_wr] = fwd_data;
            fwd_wr = fwd_wr + 1;
        end
    end

    // -------------------------------------------------- the host's UART
    //
    // Transmit: hold each bit for exactly the divider the FPGA end is
    // programmed with, so any disagreement about what a bit time is
    // shows up as a corrupted byte rather than as a slow drift.

    task send_bit;
        input b;
        begin
            host_tx <= b;
            repeat (bitclk) @(posedge clk);
        end
    endtask

    task send_byte;
        input [7:0] b;
        integer n;
        begin
            send_bit(1'b0);
            for (n = 0; n < 8; n = n + 1) send_bit(b[n]);
            send_bit(1'b1);
            repeat (bitclk) @(posedge clk);   // one idle bit between bytes
        end
    endtask

    // Receive: free-running, so a reply that arrives while the host is
    // still talking is caught rather than missed. Samples one and a half
    // bit times after the falling edge and then once a bit.
    initial begin : receiver
        reg [7:0] b;
        integer n;
        rxq_wr = 0;
        rxq_rd = 0;
        wait (rst_n);
        forever begin
            @(negedge uart_tx);
            repeat (bitclk + (bitclk / 2)) @(posedge clk);
            for (n = 0; n < 8; n = n + 1) begin
                b[n] = uart_tx;
                if (n < 7) repeat (bitclk) @(posedge clk);
            end
            repeat (bitclk) @(posedge clk);   // through the stop bit
            rxq[rxq_wr] = b;
            rxq_wr = rxq_wr + 1;
        end
    end

    // ------------------------------------------------------- the frames

    task put;                        // a byte that counts towards csum
        input [7:0] b;
        begin
            csum_tx = csum_tx + b;
            send_byte(b);
        end
    endtask

    task send_hdr;
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

    task send_csum;
        begin
            send_byte(csum_tx);
        end
    endtask

    // ------------------------------------------------------- the checks

    task chk;
        input [511:0] name;
        input [31:0] got;
        input [31:0] exp;
        begin
            checks = checks + 1;
            if (got !== exp) begin
                errors = errors + 1;
                $display("FAIL %0s: got %0h, expected %0h", name, got, exp);
            end else if (verbose)
                $display("  ok  %0s = %0h", name, got);
        end
    endtask

    task get_reply;                  // one byte off the wire, or a timeout
        output [7:0] b;
        integer n;
        begin
            n = 0;
            while (rxq_rd == rxq_wr && n < 40 * bitclk * 32) begin
                @(posedge clk);
                n = n + 1;
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

    task expect_reply;
        input [511:0] name;
        input [7:0] exp;
        begin
            get_reply(rxbyte);
            chk(name, {24'd0, rxbyte}, {24'd0, exp});
        end
    endtask

    task expect_quiet;               // nothing more should come back
        input [511:0] name;
        begin
            repeat (12 * bitclk) @(posedge clk);
            checks = checks + 1;
            if (rxq_rd != rxq_wr) begin
                errors = errors + 1;
                $display("FAIL %0s: %0d unexpected reply byte(s), first %02h",
                         name, rxq_wr - rxq_rd, rxq[rxq_rd]);
                rxq_rd = rxq_wr;
            end else if (verbose)
                $display("  ok  %0s", name);
        end
    endtask

    task expect_fwd;
        input [511:0] name;
        input [7:0] exp;
        integer n;
        begin
            n = 0;
            while (fwd_rd == fwd_wr && n < 40 * bitclk) begin
                @(posedge clk);
                n = n + 1;
            end
            if (fwd_rd == fwd_wr) begin
                errors = errors + 1;
                checks = checks + 1;
                $display("FAIL %0s: nothing was forwarded to the CPU", name);
            end else begin
                fwdbyte = fwdq[fwd_rd];
                fwd_rd = fwd_rd + 1;
                chk(name, {24'd0, fwdbyte}, {24'd0, exp});
            end
        end
    endtask

    task expect_no_fwd;
        input [511:0] name;
        begin
            checks = checks + 1;
            if (fwd_rd != fwd_wr) begin
                errors = errors + 1;
                $display("FAIL %0s: %0d byte(s) forwarded, first %02h",
                         name, fwd_wr - fwd_rd, fwdq[fwd_rd]);
                fwd_rd = fwd_wr;
            end else if (verbose)
                $display("  ok  %0s", name);
        end
    endtask

    task chk_mem;
        input [511:0] name;
        input [15:0] a;
        input [7:0] exp;
        begin
            chk(name, {24'd0, mem[a]}, {24'd0, exp});
        end
    endtask

    // Wait for the CPU to reach a halt, or give up.
    task wait_halt;
        input [511:0] name;
        integer n;
        begin
            n = 0;
            while (!o_halted && n < 20000) begin
                @(posedge clk);
                n = n + 1;
            end
            checks = checks + 1;
            if (!o_halted) begin
                errors = errors + 1;
                $display("FAIL %0s: the CPU never halted (PC=%04h)",
                         name, u_cpu.pc);
            end else if (verbose)
                $display("  ok  %0s after %0d cycles", name, n);
        end
    endtask

    // ------------------------------------------------------------- run

    initial begin
        errors = 0;
        checks = 0;
        cycle = 0;
        fwd_wr = 0;
        fwd_rd = 0;
        ctrl_we = 1'b0;
        ctrl_wdata = 8'h00;
        csum_tx = 8'h00;
        busak_low = 0;

        if (!$value$plusargs("ws=%d", ws)) ws = 0;
        if (!$value$plusargs("div=%d", i)) i = 31;
        divr = i[15:0];
        bitclk = i + 1;
        verbose = $test$plusargs("verbose");

        for (i = 0; i < 65536; i = i + 1) mem[i] = 8'h00;

        // The CPU's home: BRA -2, a two-byte spin at $0000 that fetches
        // forever and writes nothing, reached through the reset vector.
        mem[16'h0000] = 8'h70;
        mem[16'h0001] = 8'hFE;
        mem[16'hFFF8] = 8'h00;
        mem[16'hFFF9] = 8'h00;

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_loader_tb);
        end

        $display("loader testbench: div=%0d (%0d clocks a bit), ws=%0d",
                 divr, bitclk, ws);

        wcnt = 8'd0;
        repeat (8) @(posedge clk);
        rst_n <= 1'b1;
        repeat (8) @(posedge clk);

        run_tests;

        $display("%0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("PASS");
        else             $display("FAIL");
        $finish;
    end

    task run_tests;
        integer n;
        begin

        // ---- 1. PING, before anything else has happened -------------
        send_hdr(8'h07, 16'h0000, 16'h0000);
        send_csum;
        expect_reply("ping version", 8'h01);
        expect_no_fwd("ping forwarded nothing");
        chk("stat seen_frame", {29'd0, stat_rdata[2]}, 32'd1);
        chk("stat csum_bad", {29'd0, stat_rdata[1]}, 32'd0);

        // ---- 2. ordinary traffic passes through ---------------------
        send_byte("A");
        send_byte(8'h00);
        send_byte(8'hFF);
        expect_fwd("forward A", "A");
        expect_fwd("forward $00", 8'h00);
        expect_fwd("forward $FF", 8'hFF);
        expect_quiet("pass-through is silent");

        // ---- 3. a lone $C8 --------------------------------------------
        // The one case where the sniffer has to put two bytes into a
        // one-byte-wide path.
        send_byte(8'hC8);
        send_byte("Z");
        expect_fwd("lone C8 forwards C8", 8'hC8);
        expect_fwd("lone C8 forwards Z", "Z");
        expect_quiet("lone C8 is silent");

        // ---- 4. $C8 $C8 $8C is still a frame --------------------------
        // The first $C8 is data, the second starts the magic. Getting
        // this wrong swallows a frame that a host is entitled to send.
        send_byte(8'hC8);
        send_hdr(8'h07, 16'h0000, 16'h0000);
        send_csum;
        expect_fwd("C8 C8 8C forwards the first C8", 8'hC8);
        expect_reply("C8 C8 8C is a frame", 8'h01);
        expect_no_fwd("no other byte leaked through");

        // ---- 5. $C8 $C8 <data> ----------------------------------------
        send_byte(8'hC8);
        send_byte(8'hC8);
        send_byte("Z");
        expect_fwd("C8 C8 Z forwards C8", 8'hC8);
        expect_fwd("C8 C8 Z forwards C8 again", 8'hC8);
        expect_fwd("C8 C8 Z forwards Z", "Z");
        expect_quiet("C8 C8 Z is silent");

        // ---- 6. WRITE -------------------------------------------------
        send_hdr(8'h01, 16'h0200, 16'h0008);
        for (n = 0; n < 8; n = n + 1) put(8'h10 + n[7:0]);
        send_csum;
        expect_reply("write ack", 8'h4B);
        for (n = 0; n < 8; n = n + 1)
            chk_mem("write landed", 16'h0200 + n[15:0], 8'h10 + n[7:0]);
        chk_mem("write did not run over the end", 16'h0208, 8'h00);
        chk_mem("write did not run under the start", 16'h01FF, 8'h00);
        expect_no_fwd("frame bytes are not forwarded");

        // ---- 7. READ --------------------------------------------------
        send_hdr(8'h02, 16'h0200, 16'h0008);
        send_csum;
        csum_tx = 8'h00;
        for (n = 0; n < 8; n = n + 1) begin
            get_reply(rxbyte);
            csum_tx = csum_tx + rxbyte;
            chk("read byte", {24'd0, rxbyte}, {24'd0, 8'h10 + n[7:0]});
        end
        get_reply(rxbyte);
        chk("read checksum", {24'd0, rxbyte}, {24'd0, csum_tx});
        expect_quiet("read sends nothing else");

        // ---- 8. the zero-length cases ---------------------------------
        // A zero-length WRITE is the documented liveness check: it takes
        // the bus, does nothing with it, and acks.
        send_hdr(8'h01, 16'h1234, 16'h0000);
        send_csum;
        expect_reply("zero-length write acks", 8'h4B);
        chk_mem("zero-length write wrote nothing", 16'h1234, 8'h00);

        send_hdr(8'h02, 16'h0200, 16'h0000);
        send_csum;
        expect_reply("zero-length read is just a checksum", 8'h00);
        expect_quiet("zero-length read sends nothing else");

        // ---- 9. a bad checksum ----------------------------------------
        send_hdr(8'h01, 16'h0210, 16'h0002);
        put(8'hAA);
        put(8'hBB);
        send_byte(csum_tx + 8'h01);
        expect_reply("bad checksum naks", 8'h21);
        chk("stat csum_bad set", {29'd0, stat_rdata[1]}, 32'd1);

        // The loader has no frame buffer, so a WRITE's payload is already
        // in memory by the time the checksum arrives. Recorded here as
        // the behaviour, not as an accident — see docs/07-loader.md.
        chk_mem("a naked WRITE has still written", 16'h0210, 8'hAA);

        // A good frame afterwards must clear the flag and be accepted:
        // one bad frame must not wedge the sniffer.
        send_hdr(8'h07, 16'h0000, 16'h0000);
        send_csum;
        expect_reply("ping after a bad frame", 8'h01);
        chk("stat csum_bad cleared", {29'd0, stat_rdata[1]}, 32'd0);

        // ---- 10. an unknown command -----------------------------------
        send_hdr(8'h7F, 16'h0000, 16'h0000);
        send_csum;
        expect_reply("unknown command naks", 8'h21);

        // ---- 11. HALT and RUN -----------------------------------------
        chk("CPU is running before HALT", {31'd0, o_halted}, 32'd0);
        send_hdr(8'h04, 16'h0000, 16'h0000);
        send_csum;
        expect_reply("halt ack", 8'h4B);
        chk("halt_req set", {31'd0, halt_req}, 32'd1);
        chk("ctrl HALT bit reads back", {29'd0, ctrl_rdata[4]}, 32'd1);

        // The grant has to be continuous, not a pulse: the CPU is frozen
        // at an instruction boundary for as long as HALT stands.
        busak_low = 0;
        for (n = 0; n < 4 * bitclk; n = n + 1) begin
            @(posedge clk);
            if (!busak) busak_low = busak_low + 1;
        end
        chk("busak held throughout HALT", busak_low, 32'd0);
        chk("stat busak", {31'd0, stat_rdata[0]}, 32'd1);

        // Memory still answers to the loader while the CPU is frozen.
        send_hdr(8'h01, 16'h0220, 16'h0004);
        put(8'hDE); put(8'hAD); put(8'hBE); put(8'hEF);
        send_csum;
        expect_reply("write while halted", 8'h4B);
        chk_mem("halted write landed", 16'h0220, 8'hDE);
        chk_mem("halted write landed", 16'h0223, 8'hEF);

        send_hdr(8'h05, 16'h0000, 16'h0000);
        send_csum;
        expect_reply("run ack", 8'h4B);
        chk("halt_req cleared", {31'd0, halt_req}, 32'd0);
        repeat (8) @(posedge clk);
        busak_low = 0;
        for (n = 0; n < 4 * bitclk; n = n + 1) begin
            @(posedge clk);
            if (!busak) busak_low = busak_low + 1;
        end
        chk("busak released by RUN", (busak_low > 0) ? 32'd1 : 32'd0, 32'd1);

        // ---- 12. GO ---------------------------------------------------
        // The whole point of the milestone: load a program over the wire
        // and run it. HALT first, exactly as docs/07-loader.md says to,
        // so the spinning CPU cannot wander into the program while it is
        // still half written.
        send_hdr(8'h04, 16'h0000, 16'h0000);
        send_csum;
        expect_reply("halt before loading", 8'h4B);

        //   0400  00 5A     MOV R0,#$5A
        //   0402  69 00 03  ST  [$0300],R0
        //   0405  21        HALT
        send_hdr(8'h01, 16'h0400, 16'h0006);
        put(8'h00); put(8'h5A); put(8'h69); put(8'h00); put(8'h03);
        put(8'h21);
        send_csum;
        expect_reply("program written", 8'h4B);

        chk("bootram clear before GO", {31'd0, bootram}, 32'd0);
        chk_mem("target byte starts clear", 16'h0300, 8'h00);

        send_hdr(8'h03, 16'h0400, 16'h0000);
        send_csum;
        expect_reply("go ack", 8'h4B);
        chk("bootram set by GO", {31'd0, bootram}, 32'd1);
        chk("ctrl BOOTRAM bit reads back", {29'd0, ctrl_rdata[5]}, 32'd1);
        chk("GO released the halt", {31'd0, halt_req}, 32'd0);
        chk_mem("reset vector low", 16'hFFF8, 8'h00);
        chk_mem("reset vector high", 16'hFFF9, 8'h04);

        wait_halt("the loaded program ran");
        chk_mem("the loaded program stored its byte", 16'h0300, 8'h5A);
        chk("the CPU stopped where the program says",
            {16'd0, u_cpu.pc}, 32'h0406);

        // ---- 13. RESET ------------------------------------------------
        // Clears BOOTRAM and pulses the CPU's reset. The vector still
        // points at $0400 here, so a working reset re-runs the program.
        send_hdr(8'h01, 16'h0300, 16'h0001);
        put(8'h00);
        send_csum;
        expect_reply("clear the target byte", 8'h4B);
        chk_mem("target byte cleared", 16'h0300, 8'h00);

        send_hdr(8'h06, 16'h0000, 16'h0000);
        send_csum;
        expect_reply("reset ack", 8'h4B);
        chk("bootram cleared by RESET", {31'd0, bootram}, 32'd0);

        wait_halt("the CPU restarted and ran again");
        chk_mem("the program ran a second time", 16'h0300, 8'h5A);

        // ---- 14. the $FE80 register file ------------------------------
        // Software can take the bus and put the boot ROM back without
        // the wire being involved at all.
        @(posedge clk);
        ctrl_wdata <= 8'h30;             // BOOTRAM | HALT
        ctrl_we <= 1'b1;
        @(posedge clk);
        ctrl_we <= 1'b0;
        @(posedge clk);
        chk("ctrl write sets BOOTRAM", {31'd0, bootram}, 32'd1);
        chk("ctrl write sets HALT", {31'd0, halt_req}, 32'd1);
        chk("ctrl readback", {24'd0, ctrl_rdata}, 32'h31);

        @(posedge clk);
        ctrl_wdata <= 8'h00;
        ctrl_we <= 1'b1;
        @(posedge clk);
        ctrl_we <= 1'b0;
        @(posedge clk);
        chk("ctrl write clears both", {24'd0, ctrl_rdata}, 32'h01);

        // ---- 15. a payload longer than 255 bytes ----------------------
        // len16 is little-endian and the high byte is never zero here,
        // so a byte-wide counter or a swapped pair shows up immediately.
        send_hdr(8'h01, 16'h8000, 16'd260);
        for (n = 0; n < 260; n = n + 1) put(n[7:0] ^ 8'h5A);
        send_csum;
        expect_reply("260-byte write acks", 8'h4B);
        for (n = 0; n < 260; n = n + 1)
            chk_mem("long write landed", 16'h8000 + n[15:0], n[7:0] ^ 8'h5A);
        chk_mem("long write stopped at the end", 16'h8104, 8'h00);

        send_hdr(8'h02, 16'h8100, 16'h0004);
        send_csum;
        csum_tx = 8'h00;
        for (n = 256; n < 260; n = n + 1) begin
            get_reply(rxbyte);
            csum_tx = csum_tx + rxbyte;
            chk("long read byte", {24'd0, rxbyte}, {24'd0, n[7:0] ^ 8'h5A});
        end
        get_reply(rxbyte);
        chk("long read checksum", {24'd0, rxbyte}, {24'd0, csum_tx});

        // ---- 16. a write that wraps the address space ------------------
        // addr + len runs past $FFFF. Nothing in the protocol forbids it
        // and the counter is 16 bits, so it has to wrap rather than jam.
        send_hdr(8'h01, 16'hFFFE, 16'h0004);
        put(8'h11); put(8'h22); put(8'h33); put(8'h44);
        send_csum;
        expect_reply("wrapping write acks", 8'h4B);
        chk_mem("wrapping write at $FFFE", 16'hFFFE, 8'h11);
        chk_mem("wrapping write at $FFFF", 16'hFFFF, 8'h22);
        chk_mem("wrapping write at $0000", 16'h0000, 8'h33);
        chk_mem("wrapping write at $0001", 16'h0001, 8'h44);

        end
    endtask

    // Nothing here should take anywhere near this long; a hang is a
    // failure and it should say so rather than sit there.
    initial begin
        repeat (8_000_000) @(posedge clk);
        $display("FAIL: watchdog expired at cycle %0d", cycle);
        $display("%0d checks, %0d failures", checks, errors + 1);
        $display("FAIL");
        $finish;
    end

endmodule

`default_nettype wire
