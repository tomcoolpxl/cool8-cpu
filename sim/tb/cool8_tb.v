// cool8_tb — the co-simulation testbench.
//
// A simple byte-wide memory with a programmable number of wait states,
// plus interrupt and bus-request stimulus, wrapped around cool8_core.
// After every retired instruction it writes one line of architectural
// state in exactly the format tools/cool8emu.py produces, so the two
// can be diffed directly. See sim/cosim.py.
//
//   vvp a.out +hex=prog.hex +trace=rtl.trace +memdump=rtl.mem \
//             +maxcycles=200000 +ws=0
//
// Plusargs:
//   +hex=FILE        64 KB of memory, one hex byte per line
//   +trace=FILE      one line of state per retired instruction
//   +memdump=FILE    the whole address space at the end of the run
//   +maxcycles=N     give up after N clocks (a hang is a failure)
//   +ws=N            N wait states on every access
//   +wsrnd=SEED      0..2 wait states, pseudorandomly
//   +irqat=N         raise irq at cycle N   (+irqoff=N lowers it)
//   +nmiat=N         pulse nmi at cycle N
//   +busrqat=N       raise busrq at cycle N for +busrqlen=M cycles
//   +vcd=FILE        dump waves

`default_nettype none
`timescale 1ns / 1ps

module cool8_tb;

    reg clk = 1'b0;
    reg rst_n = 1'b0;

    always #5 clk = ~clk;

    // ---------------------------------------------------------- DUT

    wire [15:0] mem_addr;
    wire [7:0]  mem_wdata;
    wire        mem_read, mem_write;
    reg         mem_ready;
    reg         irq = 1'b0, nmi = 1'b0, busrq = 1'b0;
    wire        busak, o_fetch, o_halted, o_iack, o_retire;

    // --- everything the blocks below refer to, declared up front
    reg [7:0]    mem [0:65535];
    integer      ws, wsrnd;
    reg [7:0]    wcnt;
    reg [31:0]   rndstate;
    integer      irqat, irqoff, nmiat, busrqat, busrqlen, maxcycles;
    integer      irqafter, nmiafter, busrqafter;
    integer      nmi_off;
    integer      cycle;
    integer      tf;
    reg [1023:0] tracefile, hexfile, memfile, vcdfile;
    reg          have_trace, have_mem;
    reg          retire_d;
    reg          stop_now = 1'b0;
    integer      icount, maxinstr;
    reg          halted_d;
    integer      halt_hold;
    integer      cf;
    reg [1023:0] cycfile;
    reg          have_cyc;
    integer      i;

    wire [7:0]  mem_rdata = mem[mem_addr];

    cool8_core u_cpu (
        .clk(clk), .rst_n(rst_n),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_rdata(mem_rdata),
        .mem_read(mem_read), .mem_write(mem_write), .mem_ready(mem_ready),
        .irq(irq), .nmi(nmi), .busrq(busrq), .busak(busak),
        .o_fetch(o_fetch), .o_halted(o_halted), .o_iack(o_iack),
        .o_retire(o_retire)
    );

    // -------------------------------------------------------- memory

    wire access = mem_read | mem_write;

    always @(posedge clk) begin
        if (mem_write && mem_ready) mem[mem_addr] <= mem_wdata;
    end

    // ---- wait states
    function [7:0] next_ws;
        input dummy;
        begin
            if (wsrnd != 0) begin
                rndstate = rndstate * 32'd1103515245 + 32'd12345;
                next_ws  = (rndstate >> 16) % 3;
            end else next_ws = ws[7:0];
        end
    endfunction

    always @(posedge clk) begin
        if (!rst_n)            wcnt <= next_ws(1'b0);
        else if (!access)      wcnt <= next_ws(1'b0);
        else if (wcnt != 8'd0) wcnt <= wcnt - 8'd1;
        else                   wcnt <= next_ws(1'b0);
    end

    always @* mem_ready = (wcnt == 8'd0);

    // ----------------------------------------------- bus-grant check
    // The core must be completely off the bus while it holds busak.
    always @(posedge clk) begin
        if (rst_n && busak && (mem_read || mem_write)) begin
            $display("FAIL: strobe asserted during bus grant at cycle %0d",
                     cycle);
            $finish;
        end
    end

    // ------------------------------------------------------ stimulus

    always @(posedge clk) begin
        if (rst_n) begin
            cycle <= cycle + 1;
            if (irqat   >= 0 && cycle == irqat)   irq <= 1'b1;
            if (irqoff  >= 0 && cycle == irqoff)  irq <= 1'b0;
            if (nmiat   >= 0 && cycle == nmiat)   nmi <= 1'b1;
            if (nmiat   >= 0 && cycle == nmiat + 2) nmi <= 1'b0;
            if (busrqat >= 0 && cycle == busrqat) busrq <= 1'b1;
            if (busrqat >= 0 && cycle == busrqat + busrqlen) busrq <= 1'b0;
            // Injection counted in retired instructions rather than
            // clock cycles, so the emulator can be lined up with it
            // exactly. The emulator samples at the same boundary.
            if (irqafter   >= 0 && icount == irqafter)   irq <= 1'b1;
            if (nmiafter   >= 0 && icount == nmiafter && nmi_off == 0) begin
                nmi <= 1'b1; nmi_off <= cycle + 2;
            end
            if (nmi_off > 0 && cycle == nmi_off) nmi <= 1'b0;
            if (busrqafter >= 0 && icount == busrqafter && busrqat < 0) begin
                busrq <= 1'b1; busrqat <= cycle;
            end
            if (cycle > maxcycles) begin
                $display("FAIL: cycle limit %0d reached, PC=%04h",
                         maxcycles, u_cpu.pc);
                dump_memory;
                $fclose(tf);
                $finish;
            end
        end
    end

    // --------------------------------------------------------- trace

    always @(posedge clk) begin
        if (!rst_n) retire_d <= 1'b0;
        else begin
            retire_d <= o_retire;
            // Sampled one cycle late, so the writebacks of the retiring
            // instruction have landed.
            if (retire_d) begin
                icount <= icount + 1;
                if (maxinstr > 0 && icount + 1 >= maxinstr) stop_now <= 1'b1;
                if (have_cyc)
                    $fdisplay(cf, "%04h %0d", u_cpu.pc, cycle);
                if (have_trace)
                    $fdisplay(tf, "%04h %02h%02h%02h%02h %04h %04h %04h %02h",
                              u_cpu.pc, u_cpu.r0, u_cpu.r1, u_cpu.r2,
                              u_cpu.r3, u_cpu.x, u_cpu.y, u_cpu.sp,
                              {3'b000, u_cpu.fi, u_cpu.fv, u_cpu.fn,
                               u_cpu.fz, u_cpu.fc});
            end
        end
    end

    task dump_memory;
        integer mf, i;
        begin
            if (have_mem) begin
                mf = $fopen(memfile, "w");
                for (i = 0; i < 65536; i = i + 1)
                    $fdisplay(mf, "%02h", mem[i]);
                $fclose(mf);
            end
        end
    endtask

    // ----------------------------------------------------------- run

    initial begin
        cycle = 0; icount = 0; retire_d = 1'b0;
        rndstate = 32'h1234_5678;

        if (!$value$plusargs("ws=%d", ws))               ws = 0;
        if (!$value$plusargs("wsrnd=%d", wsrnd))         wsrnd = 0;
        if (!$value$plusargs("maxcycles=%d", maxcycles)) maxcycles = 5000000;
        if (!$value$plusargs("irqat=%d", irqat))         irqat = -1;
        if (!$value$plusargs("irqoff=%d", irqoff))       irqoff = -1;
        if (!$value$plusargs("nmiat=%d", nmiat))         nmiat = -1;
        if (!$value$plusargs("busrqat=%d", busrqat))     busrqat = -1;
        if (!$value$plusargs("busrqlen=%d", busrqlen))   busrqlen = 10;
        if (!$value$plusargs("maxinstr=%d", maxinstr))   maxinstr = 0;
        if (!$value$plusargs("irqafter=%d", irqafter))   irqafter = -1;
        if (!$value$plusargs("nmiafter=%d", nmiafter))   nmiafter = -1;
        if (!$value$plusargs("busrqafter=%d", busrqafter)) busrqafter = -1;
        nmi_off = 0;
        if (wsrnd != 0) rndstate = wsrnd;

        for (i = 0; i < 65536; i = i + 1) mem[i] = 8'h00;

        if (!$value$plusargs("hex=%s", hexfile)) begin
            $display("FAIL: no +hex= given");
            $finish;
        end
        $readmemh(hexfile, mem);

        have_trace = $value$plusargs("trace=%s", tracefile);
        if (have_trace) tf = $fopen(tracefile, "w");
        have_mem = $value$plusargs("memdump=%s", memfile);
        have_cyc = $value$plusargs("cyc=%s", cycfile);
        if (have_cyc) cf = $fopen(cycfile, "w");

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_tb);
        end

        wcnt = 0;
        halt_hold = 0;
        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
    end

    // Stop one cycle after the halt, so the final retire line is
    // written before the trace file is closed.
    // A halted machine can still be woken by an interrupt, so give any
    // scheduled stimulus a window to arrive before calling it a day.
    always @(posedge clk) begin
        halted_d <= o_halted;
        if (o_halted && !retire_d) halt_hold <= halt_hold + 1;
        else                       halt_hold <= 0;
        if (halt_hold > 300 || stop_now) begin
            dump_memory;
            if (have_trace) $fclose(tf);
            if (have_cyc) $fclose(cf);
            $display("%0s after %0d instructions, %0d cycles",
                     stop_now ? "LIMIT" : "HALT", icount, cycle);
            $finish;
        end
    end

endmodule

`default_nettype wire
