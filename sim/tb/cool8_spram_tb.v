// cool8_spram_tb — the SPRAM controller against a byte array.
//
// Two things can be wrong here and neither is visible by reading the
// code: the address mapping, and the handshake. So the testbench keeps
// its own flat 64 KB reference with a written/not-written bitmap —
// SPRAM comes up undefined and an unwritten byte reads x, which is the
// truth and not something to paper over — and drives the controller as a
// real master does, holding an access until mem_ready takes it.
//
// The master's outputs are driven with non-blocking assignments. With
// blocking ones the CHIPSELECT the SPRAM model samples at a clock edge
// would depend on whether the testbench or the model ran first, which is
// the same class of bug AGENTS.md warns about for the ALE latch.
//
//   vvp cool8_spram_tb.vvp +n=20000 +seed=1
//
// Plusargs:
//   +n=N       randomised accesses after the directed cases
//   +seed=N    stream seed
//   +vcd=FILE  dump waves
//   +verbose   print every check

`default_nettype none
`timescale 1ns / 1ps

module cool8_spram_tb;

    reg          clk = 1'b0;
    reg          rst_n = 1'b0;

    integer      errors, checks, nrand, i, cycle;
    reg [31:0]   seed, rnd;
    reg          verbose;
    reg [1023:0] vcdfile;

    reg [15:0]   addr;
    reg [7:0]    wdata;
    reg          read, write;
    wire [7:0]   rdata;
    wire         ready;

    reg [7:0]    golden  [0:65535];    // what should be there
    reg          valid [0:65535];   // ...where we have actually written

    reg [7:0]    got;
    integer      took;              // clocks the last access needed
    reg [15:0]   a;
    reg [7:0]    d;

    always #5 clk = ~clk;
    always @(posedge clk) cycle <= cycle + 1;

    cool8_spram u_mem (
        .clk(clk), .rst_n(rst_n),
        .addr(addr), .wdata(wdata), .read(read), .write(write),
        .rdata(rdata), .ready(ready)
    );

    // ------------------------------------------------------ the master

    task do_write;
        input [15:0] wa;
        input [7:0]  wd;
        begin
            addr  <= wa;
            wdata <= wd;
            write <= 1'b1;
            took = 0;
            @(posedge clk);
            took = took + 1;
            while (!ready) begin
                @(posedge clk);
                took = took + 1;
            end
            write <= 1'b0;
            golden[wa]   = wd;
            valid[wa] = 1'b1;
        end
    endtask

    task do_read;
        input [15:0] ra;
        output [7:0] rd_out;
        begin
            addr <= ra;
            read <= 1'b1;
            took = 0;
            @(posedge clk);
            took = took + 1;
            while (!ready) begin
                @(posedge clk);
                took = took + 1;
            end
            rd_out = rdata;          // valid in the cycle ready is high
            read <= 1'b0;
        end
    endtask

    task idle;
        input integer n;
        begin
            read  <= 1'b0;
            write <= 1'b0;
            repeat (n) @(posedge clk);
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

    // Read one byte and hold it against the reference.
    task check_byte;
        input [511:0] name;
        input [15:0]  ca;
        begin
            do_read(ca, got);
            checks = checks + 1;
            if (got !== golden[ca]) begin
                errors = errors + 1;
                $display("FAIL %0s at $%04h: got %02h, expected %02h",
                         name, ca, got, golden[ca]);
            end else if (verbose)
                $display("  ok  %0s at $%04h = %02h", name, ca, got);
        end
    endtask

    task write_check;                // write, then read it back
        input [511:0] name;
        input [15:0]  wa;
        input [7:0]   wd;
        begin
            do_write(wa, wd);
            check_byte(name, wa);
        end
    endtask

    function [31:0] next_rnd;
        input dummy;
        begin
            rnd = rnd * 32'd1103515245 + 32'd12345;
            next_rnd = rnd;
        end
    endfunction

    // ----------------------------------------------------------- run

    initial begin
        errors = 0;
        checks = 0;
        cycle  = 0;
        addr   = 16'h0000;
        wdata  = 8'h00;
        read   = 1'b0;
        write  = 1'b0;

        if (!$value$plusargs("n=%d", nrand))  nrand = 20000;
        if (!$value$plusargs("seed=%d", i))   i = 1;
        seed = i;
        rnd  = i;
        verbose = $test$plusargs("verbose");

        for (i = 0; i < 65536; i = i + 1) begin
            golden[i]   = 8'h00;
            valid[i] = 1'b0;
        end

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_spram_tb);
        end

        $display("spram testbench: %0d random accesses, seed %0d",
                 nrand, seed);

        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
        repeat (4) @(posedge clk);

        directed;
        random_stream;
        sweep_back;

        $display("%0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("PASS");
        else             $display("FAIL");
        $finish;
    end

    task directed;
        begin

        // ---- the handshake -------------------------------------------
        // A read is one wait state and a write is none. Anything else is
        // either a lost cycle on every instruction fetch or a protocol
        // violation, and both are worth failing loudly over.
        idle(2);
        chk("ready is high when idle", {31'd0, ready}, 32'd1);

        do_write(16'h0000, 8'h11);
        chk("a write takes one clock", took, 32'd1);

        do_read(16'h0000, got);
        chk("a read takes two clocks", took, 32'd2);
        chk("and returns what was written", {24'd0, got}, 32'h11);

        idle(3);
        chk("ready is high again after an access", {31'd0, ready}, 32'd1);

        // ---- byte lanes within a word --------------------------------
        // Both halves of word 0, then one of them rewritten: if MASKWREN
        // is wrong the untouched half goes with it.
        write_check("low half", 16'h0000, 8'h11);
        write_check("high half", 16'h0001, 8'h22);
        check_byte("low half survived the high", 16'h0000);

        do_write(16'h0000, 8'hAA);
        check_byte("low half rewritten", 16'h0000);
        check_byte("high half untouched by the low", 16'h0001);

        do_write(16'h0001, 8'h55);
        check_byte("high half rewritten", 16'h0001);
        check_byte("low half untouched by the high", 16'h0000);

        // ---- the two blocks ------------------------------------------
        // $0000 and $8000 are the same word offset in different blocks.
        // A dropped addr[15] makes them the same byte.
        write_check("block 1 word 0 low", 16'h8000, 8'hDE);
        write_check("block 1 word 0 high", 16'h8001, 8'hAD);
        check_byte("block 0 low unaffected", 16'h0000);
        check_byte("block 0 high unaffected", 16'h0001);

        do_write(16'h0000, 8'h01);
        check_byte("block 1 unaffected by a block 0 write", 16'h8000);

        // ---- the seam and the ends -----------------------------------
        write_check("last byte of block 0", 16'h7FFF, 8'h7F);
        write_check("first byte of block 1", 16'h8000, 8'h80);
        check_byte("the seam did not smear", 16'h7FFF);
        write_check("second to last byte", 16'h7FFE, 8'h7E);
        check_byte("still there", 16'h7FFF);
        write_check("top of memory", 16'hFFFF, 8'hFF);
        write_check("one below the top", 16'hFFFE, 8'hFE);
        check_byte("top of memory kept", 16'hFFFF);

        // ---- every address bit ---------------------------------------
        // A walking one over all sixteen bits, plus the all-zero
        // address. A swapped or dropped bit aliases two of these onto
        // each other and the second write clobbers the first.
        for (i = 0; i < 16; i = i + 1)
            do_write(16'h0001 << i, 8'hC0 + i[7:0]);
        do_write(16'h0000, 8'hB0);
        for (i = 0; i < 16; i = i + 1)
            check_byte("walking one", 16'h0001 << i);
        check_byte("walking one, address zero", 16'h0000);

        // ---- accesses with no gap ------------------------------------
        // The controller must not carry state from one access into the
        // next: a second read launched in the cycle the first completes,
        // and a read of the address just written.
        do_write(16'h1000, 8'h5A);
        do_write(16'h1001, 8'hA5);
        check_byte("back-to-back writes, first", 16'h1000);
        check_byte("back-to-back writes, second", 16'h1001);

        do_read(16'h1000, got);
        chk("back-to-back read still takes two", took, 32'd2);
        do_read(16'h1001, got);
        chk("read straight after a read", {24'd0, got}, 32'hA5);

        do_write(16'h1000, 8'h3C);
        do_read(16'h1000, got);
        chk("read straight after writing the same byte",
            {24'd0, got}, 32'h3C);

        do_read(16'h8000, got);
        do_read(16'h0000, got);
        chk("read crossing blocks with no gap", {24'd0, got}, 32'hB0);

        // ---- the address is captured, not re-read ---------------------
        // A conforming master holds its address while it is stalled, so
        // this is a stronger contract than the bus protocol asks for.
        // cool8_spram.v claims it anyway, and a claim that is not tested
        // is a comment. Launch a read, then scribble the other block and
        // the other half onto the bus while ready is low: the byte that
        // comes back must be the one the read was launched for.
        do_write(16'h2000, 8'h11);
        do_write(16'hA001, 8'h99);

        addr <= 16'h2000;
        read <= 1'b1;
        @(posedge clk);                  // the launch cycle; ready is low
        chk("still stalled", {31'd0, ready}, 32'd0);
        addr <= 16'hA001;                // a master behaving badly
        @(posedge clk);
        got  = rdata;
        read <= 1'b0;
        chk("the launch address wins over a scribbled one",
            {24'd0, got}, 32'h11);

        end
    endtask

    // A long mixed stream. Addresses are drawn to land on the same word
    // as the previous access as often as not, because that is where the
    // byte-lane and the registered-read bugs live.
    task random_stream;
        integer n;
        reg [31:0] r;
        begin
        a = 16'h0000;
        for (n = 0; n < nrand; n = n + 1) begin
            r = next_rnd(1'b0);
            if (r[30]) a = a ^ (16'h0001 << (r[27:24] & 4'hF));
            else       a = r[15:0];
            r = next_rnd(1'b0);
            d = r[20:13];
            if (r[16]) do_write(a, d);
            else if (valid[a]) check_byte("random read", a);
            if (r[23:20] == 4'h0) idle(1);
        end
        end
    endtask

    // Finally read back everything the stream ever wrote, in address
    // order rather than the order it was written, so a byte that was
    // quietly overwritten by an aliasing address is caught even if the
    // stream never read it again.
    task sweep_back;
        integer n, count;
        begin
            count = 0;
            for (n = 0; n < 65536; n = n + 1) begin
                if (valid[n]) begin
                    do_read(n[15:0], got);
                    if (got !== golden[n]) begin
                        errors = errors + 1;
                        $display("FAIL sweep at $%04h: got %02h, expected %02h",
                                 n[15:0], got, golden[n]);
                    end
                    count = count + 1;
                end
            end
            checks = checks + count;
            $display("  swept %0d written bytes back", count);
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
