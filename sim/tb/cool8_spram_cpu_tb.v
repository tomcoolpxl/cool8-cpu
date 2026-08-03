// cool8_spram_cpu_tb — the core running out of real SPRAM.
//
// Same trace format and the same plusargs as sim/tb/cool8_tb.v, so
// sim/cosim.py can diff it against the emulator without knowing what is
// underneath it. What is underneath it is cool8_spram and two
// SB_SPRAM256KA models rather than an idealised byte array, which makes
// this the one test where the core's stall logic meets the memory it
// will actually run from: a registered read, one wait state, and none on
// a write.
//
// SPRAM has no bitstream initialisation, so the image cannot be dropped
// into the array — it is written in a byte at a time through the
// controller's own port with the CPU held in reset, which is what the
// boot ROM and the loader will do on the real board. The dump at the end
// reads the SPRAM arrays directly using the mapping docs/06-roadmap.md
// specifies, so a controller that reads back its own wrong mapping
// consistently still fails.
//
//   vvp a.out +hex=prog.hex +trace=rtl.trace +memdump=rtl.mem
//
// Plusargs:
//   +hex=FILE        64 KB image, one hex byte per line
//   +trace=FILE      one line of state per retired instruction
//   +memdump=FILE    the whole address space at the end of the run
//   +maxcycles=N     give up after N clocks past reset
//   +maxinstr=N      stop after N retired instructions
//   +vcd=FILE        dump waves

`default_nettype none
`timescale 1ns / 1ps

module cool8_spram_cpu_tb;

    reg          clk = 1'b0;
    reg          rst_n = 1'b0;       // the CPU's, released after the load
    reg          mem_rst_n = 1'b0;   // the controller's, released first
    reg          preload = 1'b1;

    integer      cycle, icount, maxcycles, maxinstr, i, tf, halt_hold;
    reg [1023:0] tracefile, hexfile, memfile, vcdfile;
    reg          have_trace, have_mem;
    reg          retire_d, stop_now;

    reg [7:0]    image [0:65535];   // the hex file, before it is loaded
    reg [15:0]   pre_addr;
    reg [7:0]    pre_data;
    reg          pre_write;

    wire [15:0]  cpu_addr;
    wire [7:0]   cpu_wdata;
    wire         cpu_read, cpu_write;
    wire         o_fetch, o_halted, o_iack, o_retire;

    wire [15:0]  mem_addr  = preload ? pre_addr  : cpu_addr;
    wire [7:0]   mem_wdata = preload ? pre_data  : cpu_wdata;
    wire         mem_read  = preload ? 1'b0      : cpu_read;
    wire         mem_write = preload ? pre_write : cpu_write;
    wire [7:0]   mem_rdata;
    wire         mem_ready;

    always #5 clk = ~clk;

    cool8_spram u_mem (
        .clk(clk), .rst_n(mem_rst_n),
        .addr(mem_addr), .wdata(mem_wdata),
        .read(mem_read), .write(mem_write),
        .rdata(mem_rdata), .ready(mem_ready)
    );

    cool8_core u_cpu (
        .clk(clk), .rst_n(rst_n),
        .mem_addr(cpu_addr), .mem_wdata(cpu_wdata), .mem_rdata(mem_rdata),
        .mem_read(cpu_read), .mem_write(cpu_write), .mem_ready(mem_ready),
        .irq(1'b0), .nmi(1'b0), .busrq(1'b0), .busak(),
        .o_fetch(o_fetch), .o_halted(o_halted), .o_iack(o_iack),
        .o_retire(o_retire)
    );

    // --------------------------------------------------------- trace

    always @(posedge clk) begin
        if (!rst_n) retire_d <= 1'b0;
        else begin
            retire_d <= o_retire;
            // One cycle late, so the retiring instruction's writebacks
            // have landed. Identical to sim/tb/cool8_tb.v on purpose.
            if (retire_d) begin
                icount <= icount + 1;
                if (maxinstr > 0 && icount + 1 >= maxinstr) stop_now <= 1'b1;
                if (have_trace)
                    $fdisplay(tf, "%04h %02h%02h%02h%02h %04h %04h %04h %02h",
                              u_cpu.pc, u_cpu.r0, u_cpu.r1, u_cpu.r2,
                              u_cpu.r3, u_cpu.x, u_cpu.y, u_cpu.sp,
                              {3'b000, u_cpu.fi, u_cpu.fv, u_cpu.fn,
                               u_cpu.fz, u_cpu.fc});
            end
        end
    end

    always @(posedge clk) begin
        if (rst_n) begin
            cycle <= cycle + 1;
            if (cycle > maxcycles) begin
                $display("FAIL: cycle limit %0d reached, PC=%04h",
                         maxcycles, u_cpu.pc);
                dump_memory;
                if (have_trace) $fclose(tf);
                $finish;
            end
        end
    end

    // The mapping, spelled out rather than read back through the port:
    // block from addr[15], word from addr[14:1], half from addr[0].
    task dump_memory;
        integer mf, k;
        reg [15:0] word;
        begin
            if (have_mem) begin
                mf = $fopen(memfile, "w");
                for (k = 0; k < 65536; k = k + 1) begin
                    word = k[15] ? u_mem.u_hi.mem[k[14:1]]
                                 : u_mem.u_lo.mem[k[14:1]];
                    $fdisplay(mf, "%02h", k[0] ? word[15:8] : word[7:0]);
                end
                $fclose(mf);
            end
        end
    endtask

    // ----------------------------------------------------------- run

    initial begin
        cycle = 0; icount = 0; retire_d = 1'b0; stop_now = 1'b0;
        halt_hold = 0;
        pre_addr = 16'h0000; pre_data = 8'h00; pre_write = 1'b0;

        if (!$value$plusargs("maxcycles=%d", maxcycles)) maxcycles = 5000000;
        if (!$value$plusargs("maxinstr=%d", maxinstr))   maxinstr = 0;

        for (i = 0; i < 65536; i = i + 1) image[i] = 8'h00;

        if (!$value$plusargs("hex=%s", hexfile)) begin
            $display("FAIL: no +hex= given");
            $finish;
        end
        $readmemh(hexfile, image);

        have_trace = $value$plusargs("trace=%s", tracefile);
        if (have_trace) tf = $fopen(tracefile, "w");
        have_mem = $value$plusargs("memdump=%s", memfile);

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_spram_cpu_tb);
        end

        // Load the image the only way this memory can be loaded: one
        // byte per clock through the controller, CPU in reset.
        @(posedge clk);
        mem_rst_n <= 1'b1;
        @(posedge clk);
        for (i = 0; i < 65536; i = i + 1) begin
            pre_addr  <= i[15:0];
            pre_data  <= image[i];
            pre_write <= 1'b1;
            @(posedge clk);
        end
        pre_write <= 1'b0;
        @(posedge clk);
        preload <= 1'b0;
        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
    end

    // Stop one cycle after the halt, so the last retire line is written
    // before the trace file is closed.
    always @(posedge clk) begin
        if (rst_n) begin
            if (o_halted && !retire_d) halt_hold <= halt_hold + 1;
            else                       halt_hold <= 0;
            if (halt_hold > 8 || stop_now) begin
                dump_memory;
                if (have_trace) $fclose(tf);
                $display("%0s after %0d instructions, %0d cycles",
                         stop_now ? "LIMIT" : "HALT", icount, cycle);
                $finish;
            end
        end
    end

endmodule

`default_nettype wire
