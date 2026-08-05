// cool8_boot_tb — the machine actually booting.
//
// Core, SPRAM, boot ROM and the overlay, from power-on, running the real
// image built out of sw/boot.asm. Nothing is preloaded and nothing is
// forced: SPRAM starts undefined, exactly as the part does, so the CPU
// cannot get anywhere at all unless its reset vector really came out of
// the ROM.
//
// Then the other way in — the loader's path. BOOTRAM is set, a program
// and a reset vector are written into RAM, CPU reset is pulsed, and the
// machine has to come up in RAM with the ROM out of the map and never
// execute a byte of it. That is what GO does, checked here at the memory
// map rather than down a serial cable.
//
//   vvp cool8_boot_tb.vvp +rom=sim/build/boot.hex
//
// Plusargs:
//   +rom=FILE  the 4096-line ROM image from tools/mkrom.py
//   +vcd=FILE  dump waves
//   +verbose   print every check

`default_nettype none
`timescale 1ns / 1ps

module cool8_boot_tb;

    reg          clk = 1'b0;
    reg          rst_n = 1'b0;
    reg          hold_cpu = 1'b1;    // the testbench's own CPU reset
    reg          preload = 1'b0;     // the testbench owns the bus

    integer      errors, checks, i, cycle, n_bad;
    reg          verbose;
    reg [1023:0] vcdfile, romfile;
    reg [7:0]    byte_at;

    reg          bootram;
    reg          ctrl_we;
    reg [7:0]    ctrl_wdata;
    wire [7:0]   ctrl_rdata;

    reg [15:0]   pre_addr;
    reg [7:0]    pre_data;
    reg          pre_write;

    wire [15:0]  cpu_addr;
    wire [7:0]   cpu_wdata;
    wire         cpu_read, cpu_write;
    wire         o_fetch, o_halted, o_iack, o_retire;

    wire         cpu_rst_n = rst_n & ~hold_cpu;

    wire [15:0]  mem_addr  = preload ? pre_addr  : cpu_addr;
    wire [7:0]   mem_wdata = preload ? pre_data  : cpu_wdata;
    wire         mem_read  = preload ? 1'b0      : cpu_read;
    wire         mem_write = preload ? pre_write : cpu_write;
    wire [7:0]   mem_rdata;
    wire         mem_ready;

    // Anything the CPU fetches out of the ROM window trips this, so
    // "the ROM never ran" is a measurement rather than an inference.
    reg          rom_fetched;

    always #5 clk = ~clk;
    always @(posedge clk) cycle <= cycle + 1;

    cool8_mem #(.ROM_INIT(0)) u_mem (
        .clk(clk), .rst_n(rst_n), .cpu_rst_n(cpu_rst_n),
        .addr(mem_addr), .wdata(mem_wdata),
        .read(mem_read), .write(mem_write),
        .rdata(mem_rdata), .ready(mem_ready),
        .bootram(bootram),
        .ctrl_we(ctrl_we), .ctrl_wdata(ctrl_wdata),
        .ctrl_rdata(ctrl_rdata)
    );

    cool8_core u_cpu (
        .clk(clk), .rst_n(cpu_rst_n),
        .mem_addr(cpu_addr), .mem_wdata(cpu_wdata), .mem_rdata(mem_rdata),
        .mem_read(cpu_read), .mem_write(cpu_write), .mem_ready(mem_ready),
        .irq(1'b0), .nmi(1'b0), .busrq(1'b0), .busak(),
        .o_fetch(o_fetch), .o_halted(o_halted), .o_iack(o_iack),
        .o_retire(o_retire)
    );

    always @(posedge clk) begin
        if (!rst_n) rom_fetched <= 1'b0;
        else if (o_fetch && cpu_read && u_mem.rom_sel) rom_fetched <= 1'b1;
    end

    // RAM, straight out of the SPRAM arrays, so what is checked is what
    // is stored and not what the read path chose to report.
    function [7:0] ram_byte;
        input [15:0] a;
        reg [15:0] w;
        begin
            w = a[15] ? u_mem.u_ram.u_hi.mem[a[14:1]]
                      : u_mem.u_ram.u_lo.mem[a[14:1]];
            ram_byte = a[0] ? w[15:8] : w[7:0];
        end
    endfunction

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

    task wait_halt;
        input [511:0] name;
        input integer limit;
        integer k;
        begin
            k = 0;
            while (!o_halted && k < limit) begin
                @(posedge clk);
                k = k + 1;
            end
            checks = checks + 1;
            if (!o_halted) begin
                errors = errors + 1;
                $display("FAIL %0s: no halt after %0d clocks (PC=%04h)",
                         name, limit, u_cpu.pc);
            end else
                $display("  %0s after %0d clocks", name, k);
        end
    endtask

    task poke;                       // write one byte with the CPU held off
        input [15:0] a;
        input [7:0]  d;
        begin
            pre_addr <= a; pre_data <= d; pre_write <= 1'b1;
            @(posedge clk);
            while (!mem_ready) @(posedge clk);
            pre_write <= 1'b0;
        end
    endtask

    initial begin
        errors = 0; checks = 0; cycle = 0;
        bootram = 1'b0; ctrl_we = 1'b0; ctrl_wdata = 8'h00;
        pre_addr = 16'h0000; pre_data = 8'h00; pre_write = 1'b0;
        verbose = $test$plusargs("verbose");

        if (!$value$plusargs("rom=%s", romfile)) begin
            $display("FAIL: no +rom= given");
            $finish;
        end
        $readmemh(romfile, u_mem.u_rom.rom);

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_boot_tb);
        end

        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
        repeat (4) @(posedge clk);
        hold_cpu <= 1'b0;            // power-on: nothing but the ROM exists

        boot_from_rom;
        boot_from_ram;

        $display("%0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("PASS");
        else             $display("FAIL");
        $finish;
    end

    task boot_from_rom;
        begin
        $display("cold boot, ROM overlay on");
        chk("ROMEN at power-on", {31'd0, u_mem.romen}, 32'd1);

        // Clearing 60 KB of RAM is nearly all of this, and the clock
        // count is worth printing rather than just bounding: it is the
        // machine's power-on latency, 365k clocks or 30 ms at 12 MHz.
        wait_halt("the boot ROM ran to its HALT", 2_000_000);

        chk("it halted inside the ROM", {16'd0, u_cpu.pc & 16'hF000},
            32'h0000_F000);
        chk("the ROM was fetched from", {31'd0, rom_fetched}, 32'd1);

        // RAM is clear. Undefined at power-on and never written except by
        // the ROM, so an x here is a byte the clear loop missed.
        //
        // The banner is the exception, and it is skipped rather than
        // tolerated: the ROM writes its text map row at $8104 after the
        // clear, so those ten bytes are the one place in 60 KB where a
        // non-zero byte is the right answer. Everything else, including
        // the rest of that row, still has to be zero.
        n_bad = 0;
        for (i = 0; i < 16'hF000; i = i + 1) begin
            byte_at = ram_byte(i[15:0]);
            if ((byte_at !== 8'h00) &&
                !(i >= 16'h8104 && i < 16'h8104 + 16'd10)) begin
                if (n_bad < 4)
                    $display("FAIL $%04h is %02h, not cleared", i[15:0],
                             byte_at);
                n_bad = n_bad + 1;
            end
        end
        chk("$0000-$EFFF cleared", n_bad, 32'd0);

        // ...and the banner really is there. "COOL8" in light cyan,
        // character in the even byte and attribute in the odd one, which
        // is the layout the fetch engine reads a cell in.
        chk("the banner: C",     {24'd0, ram_byte(16'h8104)}, 32'h43);
        chk("...its attribute",  {24'd0, ram_byte(16'h8105)}, 32'h0B);
        chk("the banner: O",     {24'd0, ram_byte(16'h8106)}, 32'h4F);
        chk("the banner: 8",     {24'd0, ram_byte(16'h810C)}, 32'h38);
        chk("...and it stopped", {24'd0, ram_byte(16'h810E)}, 32'h00);

        // The vectors are in RAM, underneath the ROM window they were
        // written through. This is the overlay's whole reason for being
        // asymmetric, and nothing else in the system could have put them
        // there.
        chk("RESET vector low in RAM",  {24'd0, ram_byte(16'hFFF8)}, 32'h00);
        chk("RESET vector high in RAM", {24'd0, ram_byte(16'hFFF9)}, 32'hF0);
        chk("NMI vector in RAM", {8'd0, ram_byte(16'hFFFB),
                                  ram_byte(16'hFFFA), 8'd0},
            {8'd0, ram_byte(16'hFFFD), ram_byte(16'hFFFC), 8'd0});
        chk("BRK vector low in RAM", {24'd0, ram_byte(16'hFFFE)},
            {24'd0, ram_byte(16'hFFFA)});

        // and a read there still comes back from the ROM
        chk("a read at $FFF8 is still the ROM's copy",
            {24'd0, u_mem.u_rom.rom[12'hFF8]}, {24'd0, ram_byte(16'hFFF8)});

        // The LED store executed. There is no I/O decode in this
        // testbench, so it landed in RAM — which is enough to say the
        // instruction ran.
        chk("the LED store executed", {24'd0, ram_byte(16'hFE03)}, 32'h01);
        end
    endtask

    task boot_from_ram;
        begin
        $display("warm boot, BOOTRAM set — the loader's path");
        hold_cpu <= 1'b1;
        @(posedge clk);
        preload <= 1'b1;
        bootram <= 1'b1;
        @(posedge clk);

        // A program in RAM, and a reset vector pointing at it. Exactly
        // what a GO frame leaves behind.
        //   0400  00 3C     MOV R0,#$3C
        //   0402  69 20 03  ST  [$0320],R0
        //   0405  21        HALT
        poke(16'h0400, 8'h00);  poke(16'h0401, 8'h3C);
        poke(16'h0402, 8'h69);  poke(16'h0403, 8'h20);
        poke(16'h0404, 8'h03);  poke(16'h0405, 8'h21);
        poke(16'hFFF8, 8'h00);  poke(16'hFFF9, 8'h04);
        poke(16'h0320, 8'h00);

        @(posedge clk);
        preload <= 1'b0;
        rom_fetched = 1'b0;
        @(posedge clk);
        hold_cpu <= 1'b0;            // the CPU reset GO ends with

        chk("BOOTRAM took the ROM out of the map",
            {31'd0, u_mem.romen}, 32'd0);

        wait_halt("the loaded program ran", 2000);
        chk("it halted in the loaded program",
            {16'd0, u_cpu.pc}, 32'h0000_0406);
        chk("the loaded program stored its byte",
            {24'd0, ram_byte(16'h0320)}, 32'h3C);
        chk("the boot ROM was never fetched from",
            {31'd0, rom_fetched}, 32'd0);

        // and the way back: clear BOOTRAM, reset, the ROM is in the map
        // again. The loader's RESET command.
        bootram <= 1'b0;
        @(posedge clk);
        hold_cpu <= 1'b1;
        repeat (3) @(posedge clk);
        chk("clearing BOOTRAM and resetting puts the ROM back",
            {31'd0, u_mem.romen}, 32'd1);
        end
    endtask

    initial begin
        repeat (4_000_000) @(posedge clk);
        $display("FAIL: watchdog expired at cycle %0d", cycle);
        $display("FAIL");
        $finish;
    end

endmodule

`default_nettype wire
