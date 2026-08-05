// cool8_vram_tb — the video memory and its arbiter, against a word array.
//
// Three things can be wrong here and none of them is visible by reading
// the code: the address mapping, the nibble write masks, and the
// arbitration. So the testbench keeps its own 32K-word reference with a
// per-nibble written/not-written mask — SPRAM comes up undefined and an
// unwritten nibble reads x, which is the truth and not something to
// paper over — and drives all four requesters as real ones behave,
// holding a request until it is granted.
//
// The scoreboard runs continuously rather than per phase: every cycle,
// any requester whose rvalid is high has its data held against what was
// in the reference when its grant went out. So the directed cases, the
// priority cases and the random stream are all checked by the same
// logic, and a read that returns another requester's data fails
// wherever it happens.
//
// The requesters' outputs are driven with non-blocking assignments. With
// blocking ones the CHIPSELECT the SPRAM model samples at a clock edge
// would depend on whether the testbench or the model ran first — the
// same class of bug AGENTS.md warns about for the ALE latch.
//
//   vvp cool8_vram_tb.vvp +n=20000 +seed=1
//
// Plusargs:
//   +n=N       randomised cycles of concurrent traffic
//   +seed=N    stream seed
//   +vcd=FILE  dump waves
//   +verbose   print every check

`default_nettype none
`timescale 1ns / 1ps

module cool8_vram_tb;

    reg          clk = 1'b0;
    reg          rst_n = 1'b0;

    integer      errors, checks, nrand, i, j, cycle;
    integer      n_dsp, n_spr, n_cpu, n_blt;      // grants counted
    reg [31:0]   seed, rnd;
    reg          verbose, rand_on, rand_on_q;
    reg [1023:0] vcdfile;

    reg          dsp_req;
    reg [15:1]   dsp_addr;
    wire         dsp_gnt, dsp_rvalid;

    reg          spr_req;
    reg [15:1]   spr_addr;
    wire         spr_gnt, spr_rvalid;

    reg          cpu_req, cpu_we;
    reg [15:1]   cpu_addr;
    reg [15:0]   cpu_wdata;
    reg [3:0]    cpu_mask;
    wire         cpu_gnt, cpu_rvalid;

    reg          blt_req, blt_we;
    reg [15:1]   blt_addr;
    reg [15:0]   blt_wdata;
    reg [3:0]    blt_mask;
    wire         blt_gnt, blt_rvalid;

    wire [15:0]  rdata;

    // The reference. One 16-bit word per address, plus a nibble mask of
    // what has actually been written — the rest of the array is x on a
    // real part and comparing against it would be comparing against
    // nothing.
    reg [15:0]   golden [0:32767];
    reg [3:0]    vmask  [0:32767];

    // What each requester's outstanding read should bring back, captured
    // on its grant cycle.
    reg [15:0]   exp_dsp, exp_spr, exp_cpu, exp_blt;
    reg [3:0]    expm_dsp, expm_spr, expm_cpu, expm_blt;
    reg          cpu_wr_q, blt_wr_q;

    reg [15:0]   got;
    integer      took;

    always #5 clk = ~clk;
    always @(posedge clk) cycle <= cycle + 1;

    cool8_vram u_vram (
        .clk(clk), .rst_n(rst_n),
        .dsp_req(dsp_req), .dsp_addr(dsp_addr),
        .dsp_gnt(dsp_gnt), .dsp_rvalid(dsp_rvalid),
        .spr_req(spr_req), .spr_addr(spr_addr),
        .spr_gnt(spr_gnt), .spr_rvalid(spr_rvalid),
        .cpu_req(cpu_req), .cpu_addr(cpu_addr), .cpu_wdata(cpu_wdata),
        .cpu_we(cpu_we), .cpu_mask(cpu_mask),
        .cpu_gnt(cpu_gnt), .cpu_rvalid(cpu_rvalid),
        .blt_req(blt_req), .blt_addr(blt_addr), .blt_wdata(blt_wdata),
        .blt_we(blt_we), .blt_mask(blt_mask),
        .blt_gnt(blt_gnt), .blt_rvalid(blt_rvalid),
        .rdata(rdata)
    );

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

    // Hold one returning word against the reference, nibble by nibble,
    // skipping nibbles nothing has ever written.
    task score;
        input [511:0] who;
        input [15:0]  g;
        input [15:0]  e;
        input [3:0]   m;
        integer       k;
        begin
            for (k = 0; k < 4; k = k + 1) begin
                if (m[k]) begin
                    checks = checks + 1;
                    if (g[k*4 +: 4] !== e[k*4 +: 4]) begin
                        errors = errors + 1;
                        $display("FAIL %0s nibble %0d at cycle %0d: got %0h, expected %0h",
                                 who, k, cycle, g[k*4 +: 4], e[k*4 +: 4]);
                    end
                end
            end
        end
    endtask

    // ------------------------------------- the reference and scoreboard
    //
    // One block, so the ordering between updating the reference on a
    // write, capturing an expectation on a grant, and checking a return
    // is fixed rather than a race between processes. Every read of the
    // arrays here sees their pre-edge contents, which is exactly what the
    // SPRAM sees.

    always @(posedge clk) begin
        if (!rst_n) begin
            expm_dsp <= 4'h0;
            expm_spr <= 4'h0;
            expm_cpu <= 4'h0;
            expm_blt <= 4'h0;
            cpu_wr_q <= 1'b0;
            blt_wr_q <= 1'b0;
        end else begin
            // ---- check what came back, against what was captured for it
            if (dsp_rvalid) score("dsp", rdata, exp_dsp, expm_dsp);
            if (spr_rvalid) score("spr", rdata, exp_spr, expm_spr);
            if (cpu_rvalid) score("cpu", rdata, exp_cpu, expm_cpu);
            if (blt_rvalid) score("blt", rdata, exp_blt, expm_blt);

            // A write must not announce read data — and the two signals
            // are a cycle apart, because rvalid in cycle N answers the
            // grant in N-1. Comparing them in the same cycle is what the
            // first version of this check did, and it fails on every
            // write that happens to follow a read.
            cpu_wr_q <= cpu_gnt & cpu_we;
            blt_wr_q <= blt_gnt & blt_we;
            if (cpu_wr_q && cpu_rvalid)
                chk("a cpu write raised rvalid", 32'd1, 32'd0);
            if (blt_wr_q && blt_rvalid)
                chk("a blt write raised rvalid", 32'd1, 32'd0);

            // ---- capture what the grants going out now should return
            exp_dsp  <= golden[dsp_addr];
            expm_dsp <= dsp_gnt ? vmask[dsp_addr] : 4'h0;
            exp_spr  <= golden[spr_addr];
            expm_spr <= spr_gnt ? vmask[spr_addr] : 4'h0;
            exp_cpu  <= golden[cpu_addr];
            expm_cpu <= (cpu_gnt && !cpu_we) ? vmask[cpu_addr] : 4'h0;
            exp_blt  <= golden[blt_addr];
            expm_blt <= (blt_gnt && !blt_we) ? vmask[blt_addr] : 4'h0;

            // ---- and commit the write, if there was one
            if (cpu_gnt && cpu_we) begin
                for (j = 0; j < 4; j = j + 1)
                    if (cpu_mask[j])
                        golden[cpu_addr][j*4 +: 4] <= cpu_wdata[j*4 +: 4];
                vmask[cpu_addr] <= vmask[cpu_addr] | cpu_mask;
            end
            if (blt_gnt && blt_we) begin
                for (j = 0; j < 4; j = j + 1)
                    if (blt_mask[j])
                        golden[blt_addr][j*4 +: 4] <= blt_wdata[j*4 +: 4];
                vmask[blt_addr] <= vmask[blt_addr] | blt_mask;
            end

            // ---- tally grants, so starvation is measurable
            //
            // Cleared and counted here rather than from the stimulus
            // process, which would be a race: a blocking `n_dsp = 0` in
            // the initial block lands before this block's non-blocking
            // update from the same edge and is immediately overwritten.
            // The first run of this testbench reported 3204 grants in
            // 3000 cycles for exactly that reason.
            rand_on_q <= rand_on;
            if (rand_on && !rand_on_q) begin
                n_dsp <= 0; n_spr <= 0; n_cpu <= 0; n_blt <= 0;
            end else if (rand_on) begin
                n_dsp <= n_dsp + (dsp_gnt ? 1 : 0);
                n_spr <= n_spr + (spr_gnt ? 1 : 0);
                n_cpu <= n_cpu + (cpu_gnt ? 1 : 0);
                n_blt <= n_blt + (blt_gnt ? 1 : 0);
            end
        end
    end

    // -------------------------------------------- single-requester tasks
    //
    // Used by the directed phase. Each holds its request until the grant
    // comes back, then samples on the cycle its rvalid is high — which is
    // the contract every real requester has to implement.

    task blt_write;
        input [15:1] wa;
        input [15:0] wd;
        input [3:0]  wm;
        begin
            blt_addr  <= wa;
            blt_wdata <= wd;
            blt_mask  <= wm;
            blt_we    <= 1'b1;
            blt_req   <= 1'b1;
            took = 0;
            @(posedge clk);
            took = took + 1;
            while (!blt_gnt) begin
                @(posedge clk);
                took = took + 1;
            end
            blt_req <= 1'b0;
            blt_we  <= 1'b0;
        end
    endtask

    task blt_read;
        input  [15:1] ra;
        output [15:0] rd_out;
        begin
            blt_addr <= ra;
            blt_we   <= 1'b0;
            blt_req  <= 1'b1;
            took = 0;
            @(posedge clk);
            took = took + 1;
            while (!blt_gnt) begin
                @(posedge clk);
                took = took + 1;
            end
            blt_req <= 1'b0;
            @(posedge clk);             // rvalid and rdata are up now
            took = took + 1;
            rd_out = rdata;
            if (!blt_rvalid) begin
                errors = errors + 1;
                $display("FAIL no blt_rvalid one cycle after grant, cycle %0d",
                         cycle);
            end
        end
    endtask

    task dsp_read;
        input  [15:1] ra;
        output [15:0] rd_out;
        begin
            dsp_addr <= ra;
            dsp_req  <= 1'b1;
            @(posedge clk);
            dsp_req  <= 1'b0;
            @(posedge clk);
            rd_out = rdata;
            if (!dsp_rvalid) begin
                errors = errors + 1;
                $display("FAIL no dsp_rvalid one cycle after grant, cycle %0d",
                         cycle);
            end
        end
    endtask

    task idle;
        input integer n;
        begin
            dsp_req <= 1'b0;
            spr_req <= 1'b0;
            cpu_req <= 1'b0;
            blt_req <= 1'b0;
            repeat (n) @(posedge clk);
        end
    endtask

    // Write a whole word through the blitter port and read it straight
    // back through the same one.
    task write_check;
        input [511:0] name;
        input [15:1]  wa;
        input [15:0]  wd;
        begin
            blt_write(wa, wd, 4'hF);
            blt_read(wa, got);
            chk(name, {16'd0, got}, {16'd0, wd});
        end
    endtask

    function [31:0] next_rnd;
        input dummy;
        begin
            rnd = rnd * 32'd1103515245 + 32'd12345;
            next_rnd = rnd;
        end
    endfunction

    // ---------------------------------------- the concurrent random load
    //
    // Four agents in one block. Each issues a new request only when it is
    // idle or has just been granted, so an address is stable for as long
    // as its request is outstanding — the contract cool8_vram relies on.
    //
    // The rates are the worst-case load docs/04-system.md section 5.10
    // budgets for — an 8 bpp display at 34 %, sprites at 8 %, and a CPU
    // hammering the indirect port — with the blitter asking on every
    // cycle. Section 5.10 claims the blitter still gets the better half
    // of the memory under that load, and `random_stream` asserts it.
    //
    // Decisions are taken from the *high* bits of the LCG. Its low bits
    // have a period of sixteen and are worthless: the first run of this
    // testbench drew on `r[3:0]` and the sprite port was granted once in
    // three thousand cycles, which looked like an arbiter fault and was
    // a stimulus fault.

    reg [31:0] r;

    always @(posedge clk) if (rand_on && rst_n) begin
        if (!dsp_req || dsp_gnt) begin
            r = next_rnd(1'b0);
            dsp_req  <= (r[31:24] < 8'd87);       // 34 %
            dsp_addr <= r[22:8];
        end
        if (!spr_req || spr_gnt) begin
            r = next_rnd(1'b0);
            spr_req  <= (r[31:24] < 8'd20);       // 8 %
            spr_addr <= r[22:8];
        end
        if (!cpu_req || cpu_gnt) begin
            r = next_rnd(1'b0);
            cpu_req   <= (r[31:24] < 8'd20);      // 8 %
            cpu_addr  <= r[22:8];
            cpu_we    <= r[23];
            cpu_wdata <= {r[15:8], r[22:15]};
            // A byte-sized requester: the low half or the high half,
            // which is what the indirect port will actually present.
            cpu_mask  <= r[7] ? 4'b1100 : 4'b0011;
        end
        if (!blt_req || blt_gnt) begin
            r = next_rnd(1'b0);
            blt_req   <= 1'b1;                    // always wants the bus
            blt_addr  <= r[22:8];
            blt_we    <= r[23];
            blt_wdata <= {r[22:15], r[15:8]};
            // The blitter writes whole words, single nibbles (a 4 bpp
            // pixel) and bytes (8 bpp), so all three shapes are exercised.
            blt_mask  <= (r[30:29] == 2'b00) ? (4'b0001 << r[28:27]) :
                         (r[30:29] == 2'b01) ? (r[26] ? 4'b1100 : 4'b0011)
                                             : 4'b1111;
        end
    end

    // ----------------------------------------------------------- run

    initial begin
        errors = 0;
        checks = 0;
        cycle  = 0;
        n_dsp = 0; n_spr = 0; n_cpu = 0; n_blt = 0;
        rand_on = 1'b0;

        dsp_req = 1'b0; dsp_addr = 15'h0000;
        spr_req = 1'b0; spr_addr = 15'h0000;
        cpu_req = 1'b0; cpu_addr = 15'h0000;
        cpu_wdata = 16'h0000; cpu_we = 1'b0; cpu_mask = 4'h0;
        blt_req = 1'b0; blt_addr = 15'h0000;
        blt_wdata = 16'h0000; blt_we = 1'b0; blt_mask = 4'h0;

        if (!$value$plusargs("n=%d", nrand))  nrand = 20000;
        if (!$value$plusargs("seed=%d", i))   i = 1;
        seed = i;
        rnd  = i;
        verbose = $test$plusargs("verbose");

        for (i = 0; i < 32768; i = i + 1) begin
            golden[i] = 16'h0000;
            vmask[i]  = 4'h0;
        end

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_vram_tb);
        end

        $display("vram testbench: %0d random cycles, seed %0d", nrand, seed);

        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
        repeat (4) @(posedge clk);

        directed;
        priority_order;
        throughput;
        crosstalk;
        random_stream;

        $display("  grants: dsp %0d  spr %0d  cpu %0d  blt %0d",
                 n_dsp, n_spr, n_cpu, n_blt);
        $display("%0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("PASS");
        else             $display("FAIL");
        $finish;
    end

    task directed;
        begin

        // ---- the handshake -------------------------------------------
        // An uncontended grant is immediate and the data is one cycle
        // behind it. Anything else is a lost cycle on every access, and
        // the bandwidth arithmetic in section 5.10 stops being true.
        idle(2);
        chk("nothing is granted when nothing asks",
            {28'd0, blt_gnt, cpu_gnt, spr_gnt, dsp_gnt}, 32'd0);

        blt_write(15'h0000, 16'h1234, 4'hF);
        chk("an uncontended write is granted at once", took, 32'd1);

        blt_read(15'h0000, got);
        chk("a read is granted at once", took, 32'd2);
        chk("and returns what was written", {16'd0, got}, 32'h1234);

        // ---- nibble write masks ---------------------------------------
        // A 4 bpp pixel is one nibble, so each of the four has to land on
        // its own and leave the other three alone. This is the thing that
        // makes the pixel port cheap, and it is invisible in any count.
        blt_write(15'h0010, 16'h0000, 4'hF);
        blt_write(15'h0010, 16'hAAAA, 4'b0001);
        blt_read(15'h0010, got);
        chk("nibble 0 alone", {16'd0, got}, 32'h000A);
        blt_write(15'h0010, 16'hBBBB, 4'b0010);
        blt_read(15'h0010, got);
        chk("nibble 1 alone", {16'd0, got}, 32'h00BA);
        blt_write(15'h0010, 16'hCCCC, 4'b0100);
        blt_read(15'h0010, got);
        chk("nibble 2 alone", {16'd0, got}, 32'h0CBA);
        blt_write(15'h0010, 16'hDDDD, 4'b1000);
        blt_read(15'h0010, got);
        chk("nibble 3 alone", {16'd0, got}, 32'hDCBA);

        // The two byte shapes the CPU's indirect port will present.
        blt_write(15'h0011, 16'h0000, 4'hF);
        blt_write(15'h0011, 16'h5555, 4'b0011);
        blt_read(15'h0011, got);
        chk("low byte alone", {16'd0, got}, 32'h0055);
        blt_write(15'h0011, 16'h9999, 4'b1100);
        blt_read(15'h0011, got);
        chk("high byte alone", {16'd0, got}, 32'h9955);

        // A mask of zero must write nothing at all.
        blt_write(15'h0011, 16'hFFFF, 4'b0000);
        blt_read(15'h0011, got);
        chk("an empty mask writes nothing", {16'd0, got}, 32'h9955);

        // ---- the two blocks -------------------------------------------
        // $0000 and $4000 in word terms are the same offset in different
        // blocks. A dropped addr[15] makes them the same word.
        write_check("block 1 word 0", 15'h4000, 16'hDEAD);
        blt_read(15'h0000, got);
        chk("block 0 unaffected", {16'd0, got}, 32'h1234);
        blt_write(15'h0000, 16'hBEEF, 4'hF);
        blt_read(15'h4000, got);
        chk("block 1 unaffected by a block 0 write", {16'd0, got}, 32'hDEAD);

        // ---- the seam and the ends ------------------------------------
        write_check("last word of block 0", 15'h3FFF, 16'h3FFF);
        write_check("first word of block 1", 15'h4000, 16'h4000);
        blt_read(15'h3FFF, got);
        chk("the seam did not smear", {16'd0, got}, 32'h3FFF);
        write_check("top of memory", 15'h7FFF, 16'h7FFF);
        write_check("one below the top", 15'h7FFE, 16'h7FFE);
        blt_read(15'h7FFF, got);
        chk("top of memory kept", {16'd0, got}, 32'h7FFF);

        // ---- every address bit ----------------------------------------
        // A walking one over all fifteen, plus zero. A swapped or dropped
        // bit aliases two of these and the second write clobbers the
        // first.
        for (i = 0; i < 15; i = i + 1)
            blt_write(15'h0001 << i, 16'hC000 + i[15:0], 4'hF);
        blt_write(15'h0000, 16'hB000, 4'hF);
        for (i = 0; i < 15; i = i + 1) begin
            blt_read(15'h0001 << i, got);
            chk("walking one", {16'd0, got}, {16'd0, 16'hC000 + i[15:0]});
        end
        blt_read(15'h0000, got);
        chk("walking one, address zero", {16'd0, got}, 32'hB000);

        // ---- a read of the word just written --------------------------
        blt_write(15'h0100, 16'h0F0F, 4'hF);
        blt_read(15'h0100, got);
        chk("read straight after writing the same word",
            {16'd0, got}, 32'h0F0F);

        // ---- a different requester reads it ---------------------------
        // The display fetch and the blitter are different ports onto the
        // same array, which is the entire point of the block.
        dsp_read(15'h0100, got);
        chk("the display sees what the blitter wrote",
            {16'd0, got}, 32'h0F0F);

        idle(2);
        end
    endtask

    // Priority is fixed and the order is load-bearing: a display fetch
    // that loses a cycle to the blitter is a line buffer that misses its
    // deadline. Assert all four and walk them down one at a time.
    task priority_order;
        begin
            idle(2);
            dsp_addr <= 15'h0100; spr_addr <= 15'h0100;
            cpu_addr <= 15'h0100; blt_addr <= 15'h0100;
            cpu_we <= 1'b0; blt_we <= 1'b0;
            dsp_req <= 1'b1; spr_req <= 1'b1;
            cpu_req <= 1'b1; blt_req <= 1'b1;
            @(posedge clk);
            chk("all four asking: display wins",
                {28'd0, blt_gnt, cpu_gnt, spr_gnt, dsp_gnt}, 32'b0001);

            dsp_req <= 1'b0;
            @(posedge clk);
            chk("three asking: sprite wins",
                {28'd0, blt_gnt, cpu_gnt, spr_gnt, dsp_gnt}, 32'b0010);

            spr_req <= 1'b0;
            @(posedge clk);
            chk("two asking: the CPU port wins",
                {28'd0, blt_gnt, cpu_gnt, spr_gnt, dsp_gnt}, 32'b0100);

            cpu_req <= 1'b0;
            @(posedge clk);
            chk("one asking: the blitter finally gets it",
                {28'd0, blt_gnt, cpu_gnt, spr_gnt, dsp_gnt}, 32'b1000);

            // ...and a requester that is not asking is never granted,
            // which is the other half of the same property.
            idle(2);
            blt_req <= 1'b1; blt_we <= 1'b0;
            @(posedge clk);
            chk("only the asking requester is granted",
                {28'd0, blt_gnt, cpu_gnt, spr_gnt, dsp_gnt}, 32'b1000);
            idle(2);
        end
    endtask

    // A grant every cycle, with no turnaround bubble between them. This
    // is what separates this block from cool8_spram, and the whole
    // bandwidth budget in section 5.10 assumes it.
    task throughput;
        integer got_grants;
        begin
            idle(2);
            got_grants = 0;
            blt_we    <= 1'b1;
            blt_mask  <= 4'hF;
            blt_req   <= 1'b1;
            for (i = 0; i < 64; i = i + 1) begin
                blt_addr  <= 15'h0200 + i[14:0];
                blt_wdata <= 16'h7000 + i[15:0];
                @(posedge clk);
                if (blt_gnt) got_grants = got_grants + 1;
            end
            blt_req <= 1'b0;
            blt_we  <= 1'b0;
            chk("64 uncontended writes take 64 cycles",
                got_grants, 32'd64);

            idle(2);
            got_grants = 0;
            blt_req <= 1'b1;
            for (i = 0; i < 64; i = i + 1) begin
                blt_addr <= 15'h0200 + i[14:0];
                @(posedge clk);
                if (blt_gnt) got_grants = got_grants + 1;
            end
            blt_req <= 1'b0;
            chk("and 64 back-to-back reads take 64 cycles",
                got_grants, 32'd64);
            idle(3);
        end
    endtask

    // Two requesters reading different words on consecutive cycles. The
    // read bus is shared, so a mistake in rvalid hands one requester the
    // other's data — and both are plausible values, which is why the
    // scoreboard exists rather than an eyeball.
    task crosstalk;
        begin
            idle(2);
            blt_write(15'h0300, 16'hA1A1, 4'hF);
            blt_write(15'h0301, 16'hB2B2, 4'hF);
            idle(2);

            // dsp reads $0300 in cycle N, blt reads $0301 in N+1.
            dsp_addr <= 15'h0300; dsp_req <= 1'b1;
            blt_addr <= 15'h0301; blt_req <= 1'b1; blt_we <= 1'b0;
            @(posedge clk);                       // dsp granted
            dsp_req <= 1'b0;
            @(posedge clk);                       // blt granted; dsp data up
            chk("the display got its own word", {16'd0, rdata}, 32'hA1A1);
            chk("and only the display's rvalid is high",
                {28'd0, blt_rvalid, cpu_rvalid, spr_rvalid, dsp_rvalid},
                32'b0001);
            blt_req <= 1'b0;
            @(posedge clk);                       // blt data up
            chk("the blitter got its own word", {16'd0, rdata}, 32'hB2B2);
            chk("and only the blitter's rvalid is high",
                {28'd0, blt_rvalid, cpu_rvalid, spr_rvalid, dsp_rvalid},
                32'b1000);
            idle(2);
        end
    endtask

    // All four at once, for a long time, against the reference. This is
    // where an arbiter that drops a grant, a read that returns a
    // neighbour's data, or a nibble mask that leaks shows up.
    task random_stream;
        integer before_blt;
        begin
            idle(2);
            before_blt = 0;
            rand_on = 1'b1;
            repeat (nrand) @(posedge clk);
            rand_on = 1'b0;
            idle(4);

            // Strict priority is only defensible because the arithmetic
            // says the lowest requester still gets a useful share. If it
            // does not, the arbiter needs a policy and section 5.10 needs
            // redoing — so this is an assertion about the design, not the
            // RTL.
            //
            // The load above is harsher than section 5.10's worst case:
            // that one is display plus sprites at 42 %, leaving 58 %, and
            // this adds a CPU port asking on 8 % of cycles on top. The
            // blitter measures 51.3 % under it, with a standard deviation
            // of about 0.7 % over 5000 cycles. The threshold is 45 % —
            // nine sigma below the mean, so it does not flake, and still
            // two orders of magnitude above what a broken arbiter gives.
            checks = checks + 1;
            if (n_blt * 20 < nrand * 9) begin
                errors = errors + 1;
                $display("FAIL blitter starved: %0d grants in %0d cycles",
                         n_blt, nrand);
            end

            // Every requester must have been served at all, or the stream
            // proved nothing about three quarters of the block.
            chk("the display was served", (n_dsp > 0) ? 32'd1 : 32'd0, 32'd1);
            chk("the sprite port was served", (n_spr > 0) ? 32'd1 : 32'd0, 32'd1);
            chk("the CPU port was served", (n_cpu > 0) ? 32'd1 : 32'd0, 32'd1);

            // Nothing may be granted in a cycle it did not ask in — the
            // tally cannot exceed the number of cycles available.
            checks = checks + 1;
            if (n_dsp + n_spr + n_cpu + n_blt > nrand) begin
                errors = errors + 1;
                $display("FAIL more grants (%0d) than cycles (%0d)",
                         n_dsp + n_spr + n_cpu + n_blt, nrand);
            end
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
