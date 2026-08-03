// cool8_bus_tb — the ASIC path, through real external glue.
//
// tt_um_cool8 driving a behavioural model of the board in
// docs/03-microarchitecture.md section 5.5: two 74HC573 transparent
// latches reconstructing A[15:0] from the multiplexed AD bus, and one
// asynchronous SRAM. Same program, same trace format and same
// comparison as cool8_tb, so a divergence here and not there means the
// multiplexer is wrong rather than the CPU.
//
// Plusargs as cool8_tb, plus:
//   +wsrnd=SEED   pull the READY pin low pseudorandomly

`default_nettype none
`timescale 1ns / 1ps

module cool8_bus_tb;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    always #5 clk = ~clk;

    reg  [7:0] ui_in;
    wire [7:0] uo_out, uio_out, uio_oe;

    // --- declarations first, Verilog-2001 style
    reg [7:0]    mem [0:65535];
    reg [7:0]    lat_lo, lat_hi;
    reg [31:0]   rndstate;
    integer      wsrnd, maxcycles, maxinstr;
    integer      cycle, icount, tf;
    reg [1023:0] tracefile, hexfile, memfile;
    reg          have_trace, have_mem, retire_d, stop_now;
    integer      halt_hold, i;

    wire ale_l  = uo_out[0];
    wire ale_h  = uo_out[1];
    wire n_rd   = uo_out[2];
    wire n_wr   = uo_out[3];
    wire busak  = uo_out[7];

    wire [15:0] a_ext = {lat_hi, lat_lo};
    wire [7:0]  sram_q = mem[a_ext];

    // The CPU drives AD, or the SRAM does when nOE is low and the CPU
    // has released the bus. Nothing else is ever on it.
    wire [7:0] uio_in = (uio_oe == 8'hFF) ? uio_out : sram_q;

    // --- 2 x 74HC573. A transparent latch captures what is on its
    // input at the moment LE falls, which for the half-cycle ALE
    // pulses is the falling clock edge — where the address is stable
    // and phase and clk are not changing together. Writing it as a
    // zero-delay `always @* if (le)` instead makes the model sensitive
    // to the order the simulator happens to settle ALE and AD in at a
    // phase boundary, which the real part's 10 ns minimum pulse width
    // makes irrelevant.
    always @(negedge clk) begin
        if (ale_l) lat_lo <= uio_out;
        if (ale_h) lat_hi <= uio_out;
    end

    // --- asynchronous SRAM. With nWE held low it writes for as long as
    // it is held low; address and data are stable throughout T3, so the
    // repeats a wait state causes are idempotent. Qualifying this with
    // the READY pin instead would be wrong, because the wrapper sees
    // READY two flops later than the board drives it.
    always @(posedge clk) if (!n_wr) mem[a_ext] <= uio_out;

    tt_um_cool8 dut (
        .ui_in(ui_in), .uo_out(uo_out),
        .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(1'b1), .clk(clk), .rst_n(rst_n)
    );

    // --- READY, pulled low to insert wait states
    function ready_next;
        input dummy;
        begin
            if (wsrnd != 0) begin
                rndstate = rndstate * 32'd1103515245 + 32'd12345;
                ready_next = ((rndstate >> 18) % 3) != 0;
            end else ready_next = 1'b1;
        end
    endfunction

    always @(posedge clk) ui_in[2] <= ready_next(1'b0);

    // --- the core must be entirely off the bus during a grant
    always @(posedge clk) begin
        if (rst_n && busak && (uio_oe != 8'h00 || !n_rd || !n_wr ||
                               ale_l || ale_h)) begin
            $display("FAIL: wrapper still driving during a grant, cycle %0d",
                     cycle);
            $finish;
        end
    end

    // ------------------------------------------------------- trace

    always @(posedge clk) begin
        if (!rst_n) retire_d <= 1'b0;
        else begin
            cycle <= cycle + 1;
            retire_d <= dut.u_core.o_retire;
            if (retire_d) begin
                icount <= icount + 1;
                if (maxinstr > 0 && icount + 1 >= maxinstr) stop_now <= 1'b1;
                if (have_trace)
                    $fdisplay(tf, "%04h %02h%02h%02h%02h %04h %04h %04h %02h",
                              dut.u_core.pc, dut.u_core.r0, dut.u_core.r1,
                              dut.u_core.r2, dut.u_core.r3, dut.u_core.x,
                              dut.u_core.y, dut.u_core.sp,
                              {3'b000, dut.u_core.fi, dut.u_core.fv,
                               dut.u_core.fn, dut.u_core.fz, dut.u_core.fc});
            end
            if (cycle > maxcycles) begin
                $display("FAIL: cycle limit reached, PC=%04h", dut.u_core.pc);
                $finish;
            end
        end
    end

    task dump_memory;
        integer mf, k;
        begin
            if (have_mem) begin
                mf = $fopen(memfile, "w");
                for (k = 0; k < 65536; k = k + 1) $fdisplay(mf, "%02h", mem[k]);
                $fclose(mf);
            end
        end
    endtask

    always @(posedge clk) begin
        if (dut.u_core.o_halted && !retire_d) halt_hold <= halt_hold + 1;
        else                                  halt_hold <= 0;
        if (halt_hold > 900 || stop_now) begin
            dump_memory;
            if (have_trace) $fclose(tf);
            $display("done after %0d instructions, %0d cycles", icount, cycle);
            $finish;
        end
    end

    initial begin
        cycle = 0; icount = 0; retire_d = 1'b0; stop_now = 1'b0;
        halt_hold = 0; lat_lo = 8'h00; lat_hi = 8'h00;
        rndstate = 32'h2468_ACE0;
        ui_in = 8'b1111_1111;          // all active-low inputs idle, READY high

        if (!$value$plusargs("wsrnd=%d", wsrnd))         wsrnd = 0;
        if (!$value$plusargs("maxcycles=%d", maxcycles)) maxcycles = 20000000;
        if (!$value$plusargs("maxinstr=%d", maxinstr))   maxinstr = 0;
        if (wsrnd != 0) rndstate = wsrnd;

        for (i = 0; i < 65536; i = i + 1) mem[i] = 8'h00;
        if (!$value$plusargs("hex=%s", hexfile)) begin
            $display("FAIL: no +hex= given"); $finish;
        end
        $readmemh(hexfile, mem);

        have_trace = $value$plusargs("trace=%s", tracefile);
        if (have_trace) tf = $fopen(tracefile, "w");
        have_mem = $value$plusargs("memdump=%s", memfile);

        if ($value$plusargs("vcd=%s", tracefile)) begin
            $dumpfile("sim/build/bus.vcd");
            $dumpvars(0, cool8_bus_tb);
        end

        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
    end

endmodule

`default_nettype wire
