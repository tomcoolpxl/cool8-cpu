// cool8_vport_tb — the indirect VRAM port, against a real cool8_vram.
//
// The port is driven the way the I/O page drives it — a one-cycle launch
// pulse for a read, a write held until it is taken, and mem_ready gated
// by o_stall — and the VRAM underneath is the real block, not a model,
// with a synthetic display fetch contending for it on demand. That
// matters: everything interesting about this port is what happens when
// the prefetch does not come back in time, and it never does not come
// back in time unless something else is using the memory.
//
// **The handshake is sampled on the negative edge**, and it has to be.
// The obvious version registers o_stall and reads the register after
// `@(posedge clk)` — but a task resumes in the active region, before
// that non-blocking update has landed, so it reads the value from one
// edge earlier and lets go of the access a cycle too soon. The first run
// of this testbench did exactly that and reported every read returning
// its predecessor's byte, which looks like a broken prefetch and is a
// broken testbench. Mid-cycle everything has settled and there is
// nothing to get wrong.
//
//   vvp cool8_vport_tb.vvp +n=4000 +seed=1
//
// Plusargs:
//   +n=N       randomised port operations
//   +seed=N    stream seed
//   +vcd=FILE  dump waves
//   +verbose   print every check

`default_nettype none
`timescale 1ns / 1ps

module cool8_vport_tb;

    localparam [7:0] A_ADDR_L = 8'h26,
                     A_ADDR_H = 8'h27,
                     A_STEP   = 8'h28,
                     A_DATA   = 8'h29;

    reg          clk = 1'b0;
    reg          rst_n = 1'b0;

    integer      errors, checks, nrand, i, k, cycle, stalls;
    reg [31:0]   seed, rnd, r;
    reg          verbose;
    reg [1023:0] vcdfile;

    reg  [7:0]   io_a, io_wdata;
    reg          io_rd, io_we;
    reg  [15:0]  stride;

    wire         o_sel, o_dp_sel, o_stall;
    wire [7:0]   o_rdata, o_dout;

    // The synthetic display fetch. `dsp_duty` out of 16 cycles, so the
    // port can be squeezed hard without deadlocking it.
    reg  [3:0]   dsp_duty;
    reg  [3:0]   duty_ctr;
    reg          dsp_req;
    wire         dsp_gnt, dsp_rvalid;

    wire         vram_req, vram_we;
    wire [15:1]  vram_addr;
    wire [15:0]  vram_wdata, vram_rdata;
    wire [3:0]   vram_mask;
    wire         vram_gnt, vram_rvalid;

    // What the port should have put in VRAM, byte by byte.
    reg [7:0]    vref [0:65535];
    reg          vset [0:65535];

    reg [7:0]    got;
    reg [15:0]   a16;

    always #5 clk = ~clk;
    always @(posedge clk) begin
        cycle <= cycle + 1;
        if (o_stall) stalls <= stalls + 1;
    end

    cool8_vport u_port (
        .clk(clk), .rst_n(rst_n),
        // The bus splits a write into what is asked for and what is
        // accepted, and cool8_soc is where the split is explained: the
        // port's own write stall is a function of the request, so the
        // accepted strobe has to be the request qualified by it. Driving
        // both from one reg here would model a bus that does not exist.
        .io_a(io_a), .io_rd(io_rd),
        .io_wreq(io_we), .io_we(io_we & ~o_stall), .io_wdata(io_wdata),
        .o_sel(o_sel), .o_dp_sel(o_dp_sel),
        .o_rdata(o_rdata), .o_dout(o_dout), .o_stall(o_stall),
        .stride(stride),
        .vram_req(vram_req), .vram_addr(vram_addr),
        .vram_wdata(vram_wdata), .vram_we(vram_we), .vram_mask(vram_mask),
        .vram_gnt(vram_gnt), .vram_rvalid(vram_rvalid),
        .vram_rdata(vram_rdata)
    );

    cool8_vram u_vram (
        .clk(clk), .rst_n(rst_n),
        .dsp_req(dsp_req), .dsp_addr(15'h0000),
        .dsp_gnt(dsp_gnt), .dsp_rvalid(dsp_rvalid),
        .spr_req(1'b0), .spr_addr(15'h0000),
        .spr_gnt(), .spr_rvalid(),
        .cpu_req(vram_req), .cpu_addr(vram_addr), .cpu_wdata(vram_wdata),
        .cpu_we(vram_we), .cpu_mask(vram_mask),
        .cpu_gnt(vram_gnt), .cpu_rvalid(vram_rvalid),
        .blt_req(1'b0), .blt_addr(15'h0000), .blt_wdata(16'h0000),
        .blt_we(1'b0), .blt_mask(4'h0),
        .blt_gnt(), .blt_rvalid(),
        .rdata(vram_rdata)
    );

    // The display asks on `dsp_duty` cycles out of every 16.
    always @(posedge clk) begin
        if (!rst_n) begin
            duty_ctr <= 4'd0;
            dsp_req  <= 1'b0;
        end else begin
            duty_ctr <= duty_ctr + 4'd1;
            dsp_req  <= (duty_ctr < dsp_duty);
        end
    end

    // ------------------------------------------------------ the checks

    task chk;
        input [511:0] name;
        input [31:0]  g;
        input [31:0]  e;
        begin
            checks = checks + 1;
            if (g !== e) begin
                errors = errors + 1;
                $display("FAIL %0s at cycle %0d: got %0h, expected %0h",
                         name, cycle, g, e);
            end else if (verbose)
                $display("  ok  %0s = %0h", name, g);
        end
    endtask

    // ---------------------------------------------------- the bus model

    task idle;
        input integer n;
        begin
            io_rd <= 1'b0;
            io_we <= 1'b0;
            repeat (n) @(posedge clk);
        end
    endtask

    // A write is held until it is taken, exactly as the core holds one
    // while mem_ready is low. The edge after the last unstalled cycle is
    // the one the port latches on.
    task io_write;
        input [7:0] a;
        input [7:0] d;
        begin
            io_a     <= a;
            io_wdata <= d;
            io_we    <= 1'b1;
            @(negedge clk);
            while (o_stall) @(negedge clk);
            @(posedge clk);
            io_we <= 1'b0;
            @(posedge clk);
        end
    endtask

    // A read launches once — io_rd is the launch pulse and does not come
    // again while the access is stalled — and the byte is on o_dout in
    // the cycle after the stall clears, which is where mem_ready puts it.
    task io_read;
        input  [7:0] a;
        output [7:0] d;
        begin
            io_a  <= a;
            io_rd <= 1'b1;
            @(posedge clk);            // the launch cycle, ended properly:
            io_rd <= 1'b0;             //   dropping io_rd at the negedge
                                       //   would take the pulse away
                                       //   before this edge sampled it
            @(negedge clk);
            while (o_stall) @(negedge clk);
            d = o_dout;                // the byte stands in this cycle
            @(posedge clk);
        end
    endtask

    // ADDR_L, ADDR_H and STEP have no read side effect and go out on the
    // combinational path, so they need no launch pulse.
    task rd_reg;
        input  [7:0] a;
        output [7:0] d;
        begin
            io_a <= a;
            @(negedge clk);
            d = o_rdata;
            @(posedge clk);
        end
    endtask

    task set_addr;
        input [15:0] a;
        begin
            io_write(A_ADDR_L, a[7:0]);
            io_write(A_ADDR_H, a[15:8]);
        end
    endtask

    // Write one byte through the data port and remember what it should be.
    task port_write;
        input [15:0] at;
        input [7:0]  d;
        begin
            io_write(A_DATA, d);
            vref[at] = d;
            vset[at] = 1'b1;
        end
    endtask

    task port_check;
        input [511:0] name;
        input [15:0]  at;
        begin
            io_read(A_DATA, got);
            checks = checks + 1;
            if (vset[at] && got !== vref[at]) begin
                errors = errors + 1;
                $display("FAIL %0s at $%04h, cycle %0d: got %02h, expected %02h",
                         name, at, cycle, got, vref[at]);
            end else if (verbose)
                $display("  ok  %0s at $%04h = %02h", name, at, got);
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
        errors = 0; checks = 0; cycle = 0; stalls = 0;
        io_a = 8'h00; io_wdata = 8'h00; io_rd = 1'b0; io_we = 1'b0;
        stride = 16'd160;
        dsp_duty = 4'd0;

        if (!$value$plusargs("n=%d", nrand))  nrand = 4000;
        if (!$value$plusargs("seed=%d", i))   i = 1;
        seed = i;
        rnd  = i;
        verbose = $test$plusargs("verbose");

        for (i = 0; i < 65536; i = i + 1) begin
            vref[i] = 8'h00;
            vset[i] = 1'b0;
        end

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_vport_tb);
        end

        $display("vport testbench: %0d random operations, seed %0d",
                 nrand, seed);

        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
        repeat (4) @(posedge clk);

        decode;
        basics;
        steps;
        the_alias;
        stale_prefetch;
        under_contention;
        random_stream;

        $display("  %0d cycles stalled", stalls);
        $display("%0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("PASS");
        else             $display("FAIL");
        $finish;
    end

    // The decode, including the alias. $FEC0-$FEFF is the whole point of
    // the block for the loader, and a decode that is a nibble wide or in
    // the wrong place makes VRAM invisible to it.
    task decode;
        begin
            idle(2);
            io_a <= A_ADDR_L; @(posedge clk);
            chk("claims $FE26", {31'd0, o_sel}, 32'd1);
            chk("...and it is not the data port", {31'd0, o_dp_sel}, 32'd0);
            io_a <= A_DATA; @(posedge clk);
            chk("claims $FE29", {31'd0, o_sel}, 32'd1);
            chk("...and it is the data port", {31'd0, o_dp_sel}, 32'd1);
            io_a <= 8'hC0; @(posedge clk);
            chk("claims $FEC0", {31'd0, o_sel & o_dp_sel}, 32'd1);
            io_a <= 8'hFF; @(posedge clk);
            chk("claims $FEFF", {31'd0, o_sel & o_dp_sel}, 32'd1);
            io_a <= 8'hBF; @(posedge clk);
            chk("does not claim $FEBF", {31'd0, o_sel}, 32'd0);
            io_a <= 8'h25; @(posedge clk);
            chk("does not claim $FE25", {31'd0, o_sel}, 32'd0);
            io_a <= 8'h2A; @(posedge clk);
            chk("does not claim $FE2A", {31'd0, o_sel}, 32'd0);
            idle(2);
        end
    endtask

    task basics;
        begin
            idle(2);
            rd_reg(A_STEP, got);
            chk("step really resets to +1", {24'd0, got}, 32'h01);
            rd_reg(A_ADDR_L, got);
            chk("address resets low", {24'd0, got}, 32'h00);
            rd_reg(A_ADDR_H, got);
            chk("address resets high", {24'd0, got}, 32'h00);

            // A run of writes, then a run of reads over the same range.
            // Both byte lanes, because the port halves a 16-bit memory.
            set_addr(16'h1000);
            for (i = 0; i < 16; i = i + 1)
                port_write(16'h1000 + i[15:0], 8'hA0 + i[7:0]);

            rd_reg(A_ADDR_L, got);
            chk("the address advanced with the writes", {24'd0, got}, 32'h10);
            rd_reg(A_ADDR_H, got);
            chk("...in both halves", {24'd0, got}, 32'h10);

            set_addr(16'h1000);
            for (i = 0; i < 16; i = i + 1)
                port_check("read back", 16'h1000 + i[15:0]);

            // Starting on an odd address, so the first access is the high
            // half of a word and the run is out of phase with it.
            set_addr(16'h2001);
            for (i = 0; i < 8; i = i + 1)
                port_write(16'h2001 + i[15:0], 8'h50 + i[7:0]);
            set_addr(16'h2001);
            for (i = 0; i < 8; i = i + 1)
                port_check("odd-aligned run", 16'h2001 + i[15:0]);

            // The byte below the run must be untouched — a mask that
            // wrote the whole word would have taken it.
            set_addr(16'h2000);
            port_write(16'h2000, 8'h11);
            set_addr(16'h2001);
            port_check("the neighbour survived", 16'h2001);

            // A read of an address register must not move anything.
            set_addr(16'h3000);
            io_read(A_ADDR_L, got);
            io_read(A_STEP, got);
            rd_reg(A_ADDR_L, got);
            chk("reading a register is not a data access", {24'd0, got}, 32'h00);
            rd_reg(A_ADDR_H, got);
            chk("...in either half", {24'd0, got}, 32'h30);
            idle(2);
        end
    endtask

    // Every step code, in both directions. The address is read back
    // rather than inferred, so a code that decodes to the wrong amount
    // fails here rather than as corrupt pixels three blocks later.
    task steps;
        integer s;
        reg [15:0] want;
        begin
            idle(2);
            stride = 16'd160;
            for (s = 0; s < 8; s = s + 1) begin
                io_write(A_STEP, s[7:0]);
                set_addr(16'h4000);
                io_write(A_DATA, 8'h5A);
                want = (s == 0) ? 16'h4000 :
                       (s == 1) ? 16'h4001 :
                       (s == 2) ? 16'h4002 :
                       (s == 3) ? 16'h4004 :
                       (s == 4) ? 16'h4008 :
                       (s == 5) ? 16'h4010 :
                       (s == 6) ? 16'h4100 : 16'h40A0;
                rd_reg(A_ADDR_L, got);
                chk("step up, low", {24'd0, got}, {24'd0, want[7:0]});
                rd_reg(A_ADDR_H, got);
                chk("step up, high", {24'd0, got}, {24'd0, want[15:8]});

                io_write(A_STEP, 8'h08 | s[7:0]);        // decrement
                set_addr(16'h4000);
                io_write(A_DATA, 8'h5A);
                want = 16'h4000 - (want - 16'h4000);
                rd_reg(A_ADDR_L, got);
                chk("step down, low", {24'd0, got}, {24'd0, want[7:0]});
                rd_reg(A_ADDR_H, got);
                chk("step down, high", {24'd0, got}, {24'd0, want[15:8]});
            end

            // The stride code follows VID_STRIDE, which is the whole
            // reason there is no fixed table of awkward row pitches.
            stride = 16'd256;
            io_write(A_STEP, 8'd7);
            set_addr(16'h5000);
            io_write(A_DATA, 8'h5A);
            rd_reg(A_ADDR_H, got);
            chk("the stride code follows VID_STRIDE", {24'd0, got}, 32'h51);
            stride = 16'd160;

            // ...and the address wraps rather than saturating.
            io_write(A_STEP, 8'd1);
            set_addr(16'hFFFF);
            io_write(A_DATA, 8'h99);
            rd_reg(A_ADDR_L, got);
            chk("the address wraps, low", {24'd0, got}, 32'h00);
            rd_reg(A_ADDR_H, got);
            chk("the address wraps, high", {24'd0, got}, 32'h00);
            idle(2);
        end
    endtask

    // The loader's READ command walks consecutive addresses, so a 64-byte
    // frame at $FEC0 has to pull 64 consecutive VRAM bytes. Without that,
    // dumping VRAM is one frame per byte and cool8screen.py cannot see it
    // at all.
    task the_alias;
        begin
            idle(2);
            io_write(A_STEP, 8'd1);
            set_addr(16'h6000);
            for (i = 0; i < 64; i = i + 1)
                port_write(16'h6000 + i[15:0], 8'h40 ^ i[7:0]);

            set_addr(16'h6000);
            for (i = 0; i < 64; i = i + 1) begin
                io_read(8'hC0 + i[7:0], got);
                checks = checks + 1;
                if (got !== vref[16'h6000 + i[15:0]]) begin
                    errors = errors + 1;
                    $display("FAIL alias byte %0d, cycle %0d: got %02h, expected %02h",
                             i, cycle, got, vref[16'h6000 + i[15:0]]);
                end
            end

            // A write through the alias is a write to the data port too.
            set_addr(16'h6100);
            io_write(8'hD5, 8'h77);
            vref[16'h6100] = 8'h77; vset[16'h6100] = 1'b1;
            set_addr(16'h6100);
            port_check("a write through the alias landed", 16'h6100);
            idle(2);
        end
    endtask

    // The hazard this block was rewritten for: a fetch issued against one
    // address, and the address moved before the data came back. The
    // returning byte belongs to somewhere else and must not land as
    // valid. The window is a cycle or two wide, so the address write is
    // walked across it rather than aimed at it.
    task stale_prefetch;
        integer gap;
        begin
            idle(2);
            io_write(A_STEP, 8'd1);

            // Two distinguishable bytes, far apart.
            set_addr(16'h7000); port_write(16'h7000, 8'h11);
            set_addr(16'h7800); port_write(16'h7800, 8'h22);

            for (gap = 0; gap < 6; gap = gap + 1) begin
                // Arm a fetch at $7000...
                set_addr(16'h7000);
                idle(gap);
                // ...and move the address while it is out.
                set_addr(16'h7800);
                port_check("a fetch outrun by its address", 16'h7800);
            end

            // The same thing with the memory busy, so the fetch is
            // genuinely slow rather than merely in flight.
            dsp_duty = 4'd12;
            for (gap = 0; gap < 6; gap = gap + 1) begin
                set_addr(16'h7000);
                idle(gap);
                set_addr(16'h7800);
                port_check("...and again with the display fetching",
                           16'h7800);
            end
            dsp_duty = 4'd0;
            idle(4);
        end
    endtask

    // A read after a run of writes has nothing prefetched — the port does
    // not fetch after a write on purpose — so it has to stall and fetch.
    // With the display taking three cycles in four, the stall is long.
    task under_contention;
        begin
            idle(2);
            dsp_duty = 4'd12;
            io_write(A_STEP, 8'd1);
            set_addr(16'h8000);
            for (i = 0; i < 32; i = i + 1)
                port_write(16'h8000 + i[15:0], 8'h80 + i[7:0]);
            set_addr(16'h8000);
            for (i = 0; i < 32; i = i + 1)
                port_check("contended read back", 16'h8000 + i[15:0]);

            // Interleaved, which is the case that mixes a posted write
            // with a prefetch for a different address.
            for (i = 0; i < 32; i = i + 1) begin
                set_addr(16'h9000 + i[15:0]);
                port_write(16'h9000 + i[15:0], 8'hC0 ^ i[7:0]);
                set_addr(16'h9000 + i[15:0]);
                port_check("write then read, contended",
                           16'h9000 + i[15:0]);
            end
            dsp_duty = 4'd0;
            idle(4);
        end
    endtask

    // A long mixed stream: random addresses, random steps, runs of reads
    // and writes, and the display load changing underneath.
    task random_stream;
        integer n, runlen;
        reg [15:0] cur;
        reg [3:0]  st;
        begin
            idle(2);
            for (n = 0; n < nrand; n = n + 1) begin
                r = next_rnd(1'b0);
                dsp_duty = r[31:28];
                st = {1'b0, r[26:24]};
                if (st == 4'd7) st = 4'd1;      // keep the stride out of it
                if (r[23]) st = st | 4'd8;      // sometimes downwards
                io_write(A_STEP, {4'd0, st});

                r = next_rnd(1'b0);
                cur = r[27:12];
                set_addr(cur);

                r = next_rnd(1'b0);
                runlen = 1 + (r[29:27] & 3'd7);

                if (r[30]) begin
                    for (k = 0; k < runlen; k = k + 1) begin
                        r = next_rnd(1'b0);
                        port_write(cur, r[19:12]);
                        cur = st[3] ? (cur - step_of(st)) : (cur + step_of(st));
                    end
                end else begin
                    for (k = 0; k < runlen; k = k + 1) begin
                        port_check("random read", cur);
                        cur = st[3] ? (cur - step_of(st)) : (cur + step_of(st));
                    end
                end
            end
            dsp_duty = 4'd0;
            idle(2);
        end
    endtask

    function [15:0] step_of;
        input [3:0] s;
        begin
            step_of = (s[2:0] == 3'd0) ? 16'd0   :
                      (s[2:0] == 3'd1) ? 16'd1   :
                      (s[2:0] == 3'd2) ? 16'd2   :
                      (s[2:0] == 3'd3) ? 16'd4   :
                      (s[2:0] == 3'd4) ? 16'd8   :
                      (s[2:0] == 3'd5) ? 16'd16  :
                      (s[2:0] == 3'd6) ? 16'd256 : stride;
        end
    endfunction

    initial begin
        repeat (8_000_000) @(posedge clk);
        $display("FAIL: watchdog expired at cycle %0d", cycle);
        $display("FAIL");
        $finish;
    end

endmodule

`default_nettype wire
