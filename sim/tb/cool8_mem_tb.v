// cool8_mem_tb — the boot ROM overlay.
//
// The overlay is four rules and every one of them is asymmetric, which
// is why it gets a testbench of its own rather than being taken on trust
// once the CPU boots:
//
//   1. Reads at $F000-$FDFF and $FF00-$FFFF come from ROM while ROMEN.
//   2. Writes there go to RAM regardless — that is what lets the ROM
//      install vectors at $FFF8 inside its own read window.
//   3. $FE00-$FEFF is a hole: the I/O page wins, so the ROM must not
//      answer for it even though it is inside $F000-$FFFF.
//   4. ROMEN reloads from ~bootram on every CPU reset, and only a board
//      reset touches bootram itself.
//
// The ROM is filled with a pattern that cannot be confused with the RAM
// pattern, so "which memory answered" is readable from the data alone.
// Nothing here depends on sw/boot.asm; sim/tb/cool8_boot_tb.v does that.
//
//   vvp cool8_mem_tb.vvp +vcd=waves.vcd
//
// Plusargs:
//   +vcd=FILE  dump waves
//   +verbose   print every check

`default_nettype none
`timescale 1ns / 1ps

module cool8_mem_tb;

    reg          clk = 1'b0;
    reg          rst_n = 1'b0;
    reg          cpu_rst_n = 1'b1;

    integer      errors, checks, i, cycle;
    reg          verbose;
    reg [1023:0] vcdfile;

    reg [15:0]   addr;
    reg [7:0]    wdata;
    reg          read, write;
    wire [7:0]   rdata;
    wire         ready;

    reg          bootram;
    reg          ctrl_we;
    reg [7:0]    ctrl_wdata;
    wire [7:0]   ctrl_rdata;

    reg [7:0]    got;
    integer      took;

    always #5 clk = ~clk;
    always @(posedge clk) cycle <= cycle + 1;

    cool8_mem #(.ROM_INIT(0)) u_dut (
        .clk(clk), .rst_n(rst_n), .cpu_rst_n(cpu_rst_n),
        .addr(addr), .wdata(wdata), .read(read), .write(write),
        .rdata(rdata), .ready(ready),
        .bootram(bootram),
        .ctrl_we(ctrl_we), .ctrl_wdata(ctrl_wdata),
        .ctrl_rdata(ctrl_rdata)
    );

    // What each memory says when asked. Two properties, both of which
    // were learned the hard way from a mutant that survived: the two
    // patterns must differ at every address, so a byte says which memory
    // answered; and each must depend on the *whole* address, so an
    // aliased high bit is not hidden by a byte that happens to match.
    // They differ by $FF, so no address can collide.
    function [7:0] rom_at;
        input [15:0] a;
        begin rom_at = a[7:0] ^ a[15:8] ^ 8'h5A; end
    endfunction

    function [7:0] ram_at;
        input [15:0] a;
        begin ram_at = a[7:0] ^ a[15:8] ^ 8'hA5; end
    endfunction

    // ------------------------------------------------------ the master

    task do_write;
        input [15:0] wa;
        input [7:0]  wd;
        begin
            addr  <= wa; wdata <= wd; write <= 1'b1;
            took = 0;
            @(posedge clk); took = took + 1;
            while (!ready) begin @(posedge clk); took = took + 1; end
            write <= 1'b0;
        end
    endtask

    task do_read;
        input [15:0] ra;
        output [7:0] rd_out;
        begin
            addr <= ra; read <= 1'b1;
            took = 0;
            @(posedge clk); took = took + 1;
            while (!ready) begin @(posedge clk); took = took + 1; end
            rd_out = rdata;
            read <= 1'b0;
        end
    endtask

    task romen_write;                // what $FE00 will do at M4 item 4
        input v;
        begin
            @(posedge clk);
            ctrl_wdata <= {7'b0, v}; ctrl_we <= 1'b1;
            @(posedge clk);
            ctrl_we <= 1'b0;
            @(posedge clk);
        end
    endtask

    task pulse_cpu_reset;
        begin
            @(posedge clk);
            cpu_rst_n <= 1'b0;
            @(posedge clk);
            cpu_rst_n <= 1'b1;
            @(posedge clk);
        end
    endtask

    // ------------------------------------------------------ the checks

    task chk;
        input [511:0] name;
        input [31:0]  g;
        input [31:0]  e;
        begin
            checks = checks + 1;
            if (g !== e) begin
                errors = errors + 1;
                $display("FAIL %0s: got %0h, expected %0h", name, g, e);
            end else if (verbose)
                $display("  ok  %0s = %0h", name, g);
        end
    endtask

    task expect_rom;
        input [15:0] a;
        begin
            do_read(a, got);
            checks = checks + 1;
            if (got !== rom_at(a)) begin
                errors = errors + 1;
                $display("FAIL $%04h: got %02h, expected ROM %02h%0s",
                         a, got, rom_at(a),
                         got === ram_at(a) ? " (this is the RAM byte)" : "");
            end else if (verbose)
                $display("  ok  $%04h is ROM (%02h)", a, got);
        end
    endtask

    task expect_ram;
        input [15:0] a;
        begin
            do_read(a, got);
            checks = checks + 1;
            if (got !== ram_at(a)) begin
                errors = errors + 1;
                $display("FAIL $%04h: got %02h, expected RAM %02h%0s",
                         a, got, ram_at(a),
                         got === rom_at(a) ? " (this is the ROM byte)" : "");
            end else if (verbose)
                $display("  ok  $%04h is RAM (%02h)", a, got);
        end
    endtask

    // ----------------------------------------------------------- run

    initial begin
        errors = 0; checks = 0; cycle = 0;
        addr = 16'h0000; wdata = 8'h00; read = 1'b0; write = 1'b0;
        bootram = 1'b0; ctrl_we = 1'b0; ctrl_wdata = 8'h00;
        verbose = $test$plusargs("verbose");

        for (i = 0; i < 4096; i = i + 1)
            u_dut.u_rom.rom[i] = rom_at(16'hF000 + i[15:0]);

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_mem_tb);
        end

        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
        repeat (4) @(posedge clk);

        run_tests;

        $display("%0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("PASS");
        else             $display("FAIL");
        $finish;
    end

    task run_tests;
        integer n;
        begin

        // ---- ROMEN comes up set --------------------------------------
        chk("ROMEN after board reset", {24'd0, ctrl_rdata}, 32'h01);

        // Fill the whole ROM window and its edges with the RAM pattern,
        // underneath the overlay. Every one of these writes has to reach
        // RAM even though a read of the same address will not.
        for (i = 32'hEFFE; i < 65536; i = i + 1)
            do_write(i[15:0], ram_at(i[15:0]));
        do_write(16'h0000, ram_at(16'h0000));
        do_write(16'h1234, ram_at(16'h1234));
        do_write(16'h2000, ram_at(16'h2000));

        // ---- what answers where, with ROMEN set ----------------------
        expect_ram(16'h0000);
        expect_ram(16'h1234);
        expect_ram(16'hEFFE);
        expect_ram(16'hEFFF);           // last byte below the window
        expect_rom(16'hF000);           // first byte of it
        expect_rom(16'hF001);
        expect_rom(16'hFDFF);           // last byte before the I/O page
        expect_ram(16'hFE00);           // the hole: I/O page, not ROM
        expect_ram(16'hFE03);
        expect_ram(16'hFEFF);
        expect_rom(16'hFF00);           // and ROM again above it
        expect_rom(16'hFFF8);           // the vectors
        expect_rom(16'hFFFF);

        // ---- writes went to RAM after all ----------------------------
        // Same addresses, overlay off. If a write had been swallowed the
        // byte would be undefined, because SPRAM comes up undefined and
        // nothing else has been near it.
        romen_write(1'b0);
        chk("ROMEN cleared", {24'd0, ctrl_rdata}, 32'h00);

        expect_ram(16'hF000);
        expect_ram(16'hF001);
        expect_ram(16'hFDFF);
        expect_ram(16'hFF00);
        expect_ram(16'hFFF8);
        expect_ram(16'hFFFF);

        // ---- and back ------------------------------------------------
        romen_write(1'b1);
        chk("ROMEN set again", {24'd0, ctrl_rdata}, 32'h01);
        expect_rom(16'hF000);
        expect_rom(16'hFFFF);

        // ---- a write under the overlay, after the fact ---------------
        // The specific thing the boot ROM does at $FFF8: write into its
        // own read window and find the value later.
        do_write(16'hFFF8, 8'h5E);
        expect_rom(16'hFFF8);           // still the ROM byte on a read
        romen_write(1'b0);
        do_read(16'hFFF8, got);
        chk("the write landed in RAM underneath", {24'd0, got}, 32'h5E);
        do_write(16'hFFF8, ram_at(16'hFFF8));
        romen_write(1'b1);

        // ---- timing is the same either way ---------------------------
        // If the ROM answered a cycle later than the SPRAM the mux would
        // still look right in a waveform and be wrong on the board.
        do_read(16'hF000, got);
        chk("a ROM read takes two clocks", took, 32'd2);
        do_read(16'h1234, got);
        chk("a RAM read takes two clocks", took, 32'd2);
        do_write(16'hF000, ram_at(16'hF000));
        chk("a write under the overlay takes one clock", took, 32'd1);

        // ---- crossing the boundary with no gap -----------------------
        // rom_r is captured per access; a stale copy shows up as the
        // wrong memory answering the second of a pair.
        for (n = 0; n < 4; n = n + 1) begin
            expect_rom(16'hF100);
            expect_ram(16'h2000);
            expect_rom(16'hFF10);
            expect_ram(16'hFE80);
        end

        // ---- the launch address decides ------------------------------
        // Same claim cool8_spram makes, one level up: scribble a RAM
        // address onto the bus while a ROM read is stalled.
        addr <= 16'hF9A5; read <= 1'b1;
        @(posedge clk);
        chk("still stalled", {31'd0, ready}, 32'd0);
        addr <= 16'h3123;
        @(posedge clk);
        got  = rdata;
        read <= 1'b0;
        chk("a scribbled address does not change which memory answered",
            {24'd0, got}, {24'd0, rom_at(16'hF9A5)});

        // ---- ROMEN and CPU reset -------------------------------------
        // The mechanism behind the loader's GO: BOOTRAM decides what the
        // machine wakes up looking at.
        romen_write(1'b0);
        chk("ROMEN off before the reset", {24'd0, ctrl_rdata}, 32'h00);
        pulse_cpu_reset;
        chk("a CPU reset with BOOTRAM clear puts the ROM back",
            {24'd0, ctrl_rdata}, 32'h01);
        expect_rom(16'hF000);

        bootram <= 1'b1;
        @(posedge clk);
        chk("BOOTRAM alone does not move the overlay",
            {24'd0, ctrl_rdata}, 32'h01);
        expect_rom(16'hF000);

        pulse_cpu_reset;
        chk("a CPU reset with BOOTRAM set leaves the ROM out",
            {24'd0, ctrl_rdata}, 32'h00);
        expect_ram(16'hF000);
        expect_ram(16'hFFF8);

        // Software can still put the ROM back afterwards.
        romen_write(1'b1);
        expect_rom(16'hF000);
        pulse_cpu_reset;
        chk("and BOOTRAM still decides at the next reset",
            {24'd0, ctrl_rdata}, 32'h00);

        bootram <= 1'b0;
        pulse_cpu_reset;
        chk("clearing BOOTRAM boots from ROM again",
            {24'd0, ctrl_rdata}, 32'h01);
        expect_rom(16'hF000);

        end
    endtask

    initial begin
        repeat (2_000_000) @(posedge clk);
        $display("FAIL: watchdog expired at cycle %0d", cycle);
        $display("FAIL");
        $finish;
    end

endmodule

`default_nettype wire
