// Does it make a sound, the right one, and the one the model predicts?
//
// Three things, in order of how external they are:
//
//   1. **The pin's DC level.** What the RC filter on it would produce,
//      measured as a duty cycle over a long window. Silence, one voice,
//      the sign of the wave, eight of them summing, and noise.
//
//   2. **The modulator is lossless.** A first-order sigma-delta fed a
//      constant `level` for 256 clocks emits exactly `level` carries in
//      those 256 clocks — the residue it starts a window with is the
//      residue it ends with. That is checked here rather than assumed,
//      because it is the whole argument for putting a DAC on one pin.
//
//   3. **A stream to gate a model against.** `+dump=snd.hex` writes the
//      level byte at every sample, which is the number the pin's duty
//      cycle equals and therefore the one an emulator has to reproduce.
//      tools/cool8vm.py's Sound is checked against this file by
//      sim/test_vm.py, sample for sample.
//
// The engine is written to be indistinguishable from eight parallel
// voices, so the register program below deliberately runs voices at
// different pitches at once: a datapath that walked the array wrongly
// would still pass a one-voice test.

`default_nettype none
`timescale 1ns / 1ps

module cool8_snd_tb;

    reg        clk = 1'b0;
    reg        rst_n = 1'b0;
    reg [7:0]  io_a;
    reg        io_rd, io_we;
    reg [7:0]  io_wdata;
    wire       o_sel;
    wire       o_pwm;

    integer    i, hi, tot, errors, checks;
    integer    fh, dumping;
    reg [1023:0] dumpfile, vcdfile;

    // 8.375 MHz
    always #59.7 clk = ~clk;

    cool8_snd u_snd (
        .clk(clk), .rst_n(rst_n),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wdata(io_wdata),
        .o_sel(o_sel), .o_pwm(o_pwm)
    );

    task io_wr;
        input [7:0] a;
        input [7:0] d;
        begin
            @(posedge clk);
            io_a <= a; io_wdata <= d; io_we <= 1'b1;
            @(posedge clk);
            io_we <= 1'b0;
            @(posedge clk);
        end
    endtask

    // voice v. The array is 16-bit words and the port is bytes, so a
    // word commits on its odd byte — the same shape PAL_DATA has.
    //
    //   byte 8v+0,1   increment
    //   byte 8v+2,3   phase   (the engine's; software leaves it alone)
    //   byte 8v+4,5   {noise, enable, ...} : {..., volume[3:0]}
    task set_voice;
        input [2:0]  v;
        input [15:0] inc;
        input        en, noise;
        input [3:0]  vol;
        begin
            io_wr(8'h50, {2'b00, v, 3'b000});
            io_wr(8'h51, inc[7:0]);
            io_wr(8'h51, inc[15:8]);
            io_wr(8'h50, {2'b00, v, 3'b100});
            io_wr(8'h51, {4'h0, vol});
            io_wr(8'h51, {noise, en, 6'b000000});
        end
    endtask

    // The DC level the RC filter sees, and the tone under it.
    task measure;
        input [8*24-1:0] name;
        input integer    want_pct;
        input integer    tol;
        integer          k, pct;
        begin
            hi = 0; tot = 0;
            for (k = 0; k < 400000; k = k + 1) begin
                @(posedge clk);
                tot = tot + 1;
                if (o_pwm) hi = hi + 1;
            end
            pct = (hi * 100) / tot;
            checks = checks + 1;
            $display("  %0s: duty %0d %% (want %0d +-%0d)",
                     name, pct, want_pct, tol);
            if (pct < want_pct - tol || pct > want_pct + tol) begin
                $display("FAIL %0s: duty %0d, want %0d +-%0d",
                         name, pct, want_pct, tol);
                errors = errors + 1;
            end
        end
    endtask

    // ------------------------------------------------ the lossless check
    //
    // Count carries between one sample boundary and the next and compare
    // against the level that was held across it. A sigma-delta that
    // dropped or duplicated a carry — an off-by-one in the accumulator
    // width, a reset that clears the residue mid-stream — shows up here
    // as a window that is one out, and nowhere else: the duty test above
    // averages over 1500 windows and would not see it.

    integer carries, held, win_errors;
    reg     watching;

    initial begin
        watching = 1'b0; carries = 0; win_errors = 0;
    end

    always @(posedge clk) begin
        if (watching) begin
            if (o_pwm) carries = carries + 1;
            if (u_snd.tick == 8'd0) begin           // a window just closed
                if (held !== -1 && carries !== held) begin
                    if (win_errors < 8)
                        $display("FAIL window: %0d carries, level %0d",
                                 carries, held);
                    win_errors = win_errors + 1;
                end
                held    = u_snd.level;
                carries = 0;
            end
        end
    end

    // ------------------------------------------------------ the stream
    //
    // One level byte per sample, which is what an emulator must match.
    // Sampled one clock after the boundary so `sample` has been latched
    // and `level` is the value the whole window will be modulated with.

    // Start every voice from a known phase.
    //
    // Configuring eight voices is 144 clocks of register writes and a
    // window is 256, so a boundary lands somewhere in the middle of them
    // and the voices written before it have advanced once more than the
    // ones written after. That is a real property of the hardware and
    // completely inaudible, but it makes the stream depend on where the
    // writes happened to fall — which no model can reproduce and none
    // should have to. Forced at tick 200: the engine's 32-clock walk is
    // long over and the next one has not begun, so nothing races.
    task align_phases;
        integer k;
        begin
            @(posedge clk);
            while (u_snd.tick != 8'd200) @(posedge clk);
            for (k = 0; k < 8; k = k + 1) u_snd.vmem[k * 4 + 1] = 16'd0;
            u_snd.lfsr = 16'hACE1;
        end
    endtask

    task dump_samples;
        input integer n;
        integer k;
        begin
            // `sample` holds the window *before* the one now running, so
            // the first boundary after the phases are forced still
            // carries the old mix. Skip it; everything after it is a
            // window that began from phase zero.
            @(posedge clk);
            while (u_snd.tick != 8'd1) @(posedge clk);
            for (k = 0; k < n; k = k + 1) begin
                @(posedge clk);
                while (u_snd.tick != 8'd1) @(posedge clk);
                if (dumping) $fwrite(fh, "%02h\n", u_snd.level);
            end
        end
    endtask

    initial begin
        io_a = 0; io_rd = 0; io_we = 0; io_wdata = 0;
        errors = 0; checks = 0; held = -1;

        dumping = $value$plusargs("dump=%s", dumpfile);
        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_snd_tb);
        end

        // Block RAM comes up zeroed from the bitstream on the real part,
        // exactly as cool8_pixel's sprite buffer relies on. Simulation
        // starts it undefined, so say so explicitly rather than measure X.
        for (i = 0; i < 32; i = i + 1) u_snd.vmem[i] = 16'd0;

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (10) @(posedge clk);
        watching = 1'b1;

        // ---- nothing enabled: the pin should sit at half scale, which is
        //      what silence is for a modulator that cannot output a
        //      negative voltage.
        measure("silence", 50, 3);

        // ---- one voice, full volume. A square either side of zero
        //      averages to the same half scale, so the *level* does not
        //      move — what moves is that there is now a tone in it.
        set_voice(3'd0, 16'd881, 1'b1, 1'b0, 4'd15);
        measure("one voice at full", 50, 3);

        // ---- One voice held on one level for the whole window, which
        //      is what an increment of 1 gives: the phase moves 1562 of
        //      65536 in 400,000 clocks, so the square never leaves its
        //      low half. -15 of a +-128 swing is 47 % of full scale, and
        //      that number is the mixer's sign working.
        set_voice(3'd0, 16'd1, 1'b1, 1'b0, 4'd15);
        measure("one voice low", 47, 3);

        // ---- the same voice in its high half, by starting the phase
        //      there. The level has to mirror about the middle, or the
        //      sign is coming from somewhere other than the wave.
        u_snd.vmem[1] = 16'h8000;
        measure("one voice high", 52, 3);
        u_snd.vmem[1] = 16'h0000;

        // ---- eight of them at once. Eight times -15 is -120 of -128,
        //      so the pin sits near the bottom of its range: this is the
        //      serial mixer actually accumulating rather than replacing.
        for (i = 1; i < 8; i = i + 1)
            set_voice(i[2:0], 16'd1, 1'b1, 1'b0, 4'd15);
        measure("eight voices low", 26, 3);

        // ---- and off again
        for (i = 0; i < 8; i = i + 1)
            set_voice(i[2:0], 16'd1, 1'b0, 1'b0, 4'd0);
        measure("all disabled", 50, 3);

        // ---- noise: the LFSR should make the pin wander, not sit
        set_voice(3'd0, 16'd8000, 1'b1, 1'b1, 4'd15);  // noise
        measure("noise", 50, 6);

        // ------------------------------------------------ the stream
        //
        // A chord of five squares at unrelated pitches, two silent
        // voices between them, and a noise voice on top. Unrelated
        // pitches matter: eight voices at the same increment stay in
        // phase for ever, and an engine that mixed voice 3 twice and
        // voice 5 never would give the identical answer.
        if (dumping) begin
            fh = $fopen(dumpfile, "w");
            for (i = 0; i < 8; i = i + 1)
                set_voice(i[2:0], 16'd0, 1'b0, 1'b0, 4'd0);
            for (i = 0; i < 32; i = i + 1) u_snd.vmem[i] = 16'd0;

            set_voice(3'd0, 16'd881,   1'b1, 1'b0, 4'd15);  // A4
            set_voice(3'd1, 16'd1109,  1'b1, 1'b0, 4'd10);  // C#5
            set_voice(3'd2, 16'd1319,  1'b1, 1'b0, 4'd7);   // E5
            set_voice(3'd3, 16'd37,    1'b1, 1'b0, 4'd3);   // a slow LFO-ish
            set_voice(3'd4, 16'd20000, 1'b1, 1'b0, 4'd4);   // near Nyquist
            set_voice(3'd5, 16'd500,   1'b0, 1'b0, 4'd15);  // set but silent
            set_voice(3'd6, 16'd0,     1'b1, 1'b0, 4'd9);   // never advances
            set_voice(3'd7, 16'd3000,  1'b1, 1'b1, 4'd12);  // noise

            align_phases;
            dump_samples(4096);
            $fclose(fh);
            $display("  stream: 4096 samples written");
        end

        checks = checks + 1;
        if (win_errors != 0) begin
            $display("FAIL modulator: %0d windows off", win_errors);
            errors = errors + 1;
        end else begin
            $display("  modulator: every window's carries equal its level");
        end

        $display("");
        $display("%0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("PASS");
        else             $display("FAILED %0d", errors);
        $finish;
    end

endmodule

`default_nettype wire
