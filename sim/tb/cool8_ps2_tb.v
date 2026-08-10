// cool8_ps2_tb — the keyboard port, against a keyboard.
//
// The device end is modelled as a device, not as a stimulus list: it
// owns the clock, it drives open drain, and it obeys the same protocol
// the block does. The two lines are wired-AND with a pull-up, which is
// what an open-drain bus is —
//
//     ps2_clk = ~(dut_clk_oe | kb_clk_oe)
//
// so nothing in this testbench can drive a line high, exactly as nothing
// on a real PS/2 bus can. A block that tried would fail here rather than
// on a bench.
//
// **The device-to-host and host-to-device directions sample on opposite
// clock levels** and the model implements both from the protocol rather
// than from the block, which is the only reason it can disagree with it.
// Device to host: the keyboard changes data while the clock is high and
// the host reads on the falling edge. Host to device: the host changes
// data while the clock is low and the device reads while it is high.
//
// The register interface is driven the way the I/O page drives it — a
// one-cycle `io_rd` pulse, `io_we` held — and the read value is captured
// by a monitor on the launch edge, which is what cool8_soc does with
// `io_rdata_r`. Reading `o_rdata` at some other moment would test a
// timing the machine never uses.
//
//   vvp cool8_ps2_tb.vvp +vcd=ps2.vcd
//
// Plusargs:
//   +vcd=FILE  dump waves
//   +verbose   print every check

`default_nettype none
`timescale 1ns / 1ps

module cool8_ps2_tb;

    // Scaled down so a simulation is short. The ratios are what matter:
    // the filter is a few clocks, a half period is comfortably longer
    // than the filter, and the watchdog is longer than a half period and
    // shorter than the gap between frames.
    localparam integer FILT   = 4;
    localparam integer T60US  = 100;
    localparam integer T100US = 150;
    localparam integer TXTO   = 4;

    reg saw_reset;

    localparam integer HP = 20;          // clocks per PS/2 half period

    localparam [7:0] A_STAT = 8'h40,
                     A_MOD  = 8'h44,
                     A_DATA = 8'h41,
                     A_CTRL = 8'h42,
                     A_TX   = 8'h43;

    reg          clk = 1'b0;
    reg          rst_n = 1'b0;

    integer      errors, checks, i, j, n, hits, total, inhibit_n;
    reg  [7:0]   curb;
    reg          verbose;
    reg [1023:0] vcdfile;

    reg  [7:0]   io_a, io_wdata;
    reg          io_rd, io_we;
    reg  [7:0]   cap;                    // what the CPU would have got
    reg  [7:0]   got, st;

    reg          kb_clk_oe, kb_dat_oe;
    reg  [10:0]  txbits;                 // what the device saw us send
    reg  [7:0]   expect_q [0:63];        // bytes the model believes it sent
    integer      exp_wr, exp_rd;

    wire         dut_clk_oe, dut_dat_oe;
    wire         o_sel, o_irq;
    wire         o_reset, o_warm;        // the two keyboard chords
    wire [7:0]   o_rdata;

    // Open drain: either end pulls down, the pull-up does the rest.
    wire ps2_clk = ~(dut_clk_oe | kb_clk_oe);
    wire ps2_dat = ~(dut_dat_oe | kb_dat_oe);

    always #5 clk = ~clk;

    cool8_ps2 #(.FILT(FILT), .T60US(T60US), .T100US(T100US), .TXTO(TXTO))
    dut (
        .clk(clk), .rst_n(rst_n),
        .ps2_clk_i(ps2_clk), .ps2_dat_i(ps2_dat),
        .ps2_clk_oe(dut_clk_oe), .ps2_dat_oe(dut_dat_oe),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wdata(io_wdata),
        .o_sel(o_sel), .o_rdata(o_rdata), .o_irq(o_irq),
        .o_reset(o_reset), .o_warm(o_warm)
    );

    // The I/O page captures a read on the launch edge. Doing the same
    // here means a block that answered a cycle late would fail, which is
    // the failure this project has already had once in cool8_vport.
    always @(posedge clk) if (io_rd) cap <= o_rdata;

    // ---------------------------------------------------------- helpers

    task check;
        input        cond;
        input [255:0] what;
        begin
            checks = checks + 1;
            if (!cond) begin
                errors = errors + 1;
                $display("FAIL %0s  (t=%0t)", what, $time);
            end else if (verbose) begin
                $display("  ok  %0s", what);
            end
        end
    endtask

    task check_eq;
        input [31:0] a;
        input [31:0] b;
        input [255:0] what;
        begin
            checks = checks + 1;
            if (a !== b) begin
                errors = errors + 1;
                $display("FAIL %0s: got %02h want %02h  (t=%0t)",
                         what, a, b, $time);
            end else if (verbose) begin
                $display("  ok  %0s = %02h", what, a);
            end
        end
    endtask

    task io_write;
        input [7:0] a;
        input [7:0] d;
        begin
            @(negedge clk);
            io_a = a; io_wdata = d; io_we = 1'b1;
            @(negedge clk);
            io_we = 1'b0;
        end
    endtask

    // One cycle of `io_rd`, and the byte is whatever the launch edge
    // captured — the pop happens exactly once, as it does on the page.
    task io_read;
        input [7:0] a;
        begin
            @(negedge clk);
            io_a = a; io_rd = 1'b1;
            @(negedge clk);
            io_rd = 1'b0;
            got = cap;
        end
    endtask

    // ------------------------------------------------------ the keyboard
    //
    // Device to host. The data line is set while the clock is high and
    // the host is expected to read it on the falling edge; the model
    // never looks at what the host does, so a host that sampled on the
    // wrong edge would read the neighbouring bit.

    task kb_bit;
        input b;
        begin
            kb_dat_oe = ~b;                       // drive low for a zero
            repeat (HP) @(posedge clk);
            kb_clk_oe = 1'b1;                     // the falling edge
            repeat (HP) @(posedge clk);
            kb_clk_oe = 1'b0;
        end
    endtask

    // Every bit of the frame is a parameter, because every one of them
    // is a thing the block is supposed to check. `nbits` cuts the frame
    // short, which is what the watchdog is for.
    task kb_frame;
        input        start;
        input [7:0]  d;
        input        par;
        input        stop;
        input integer nbits;
        integer      b;
        begin
            if (nbits > 0) kb_bit(start);
            for (b = 0; b < 8; b = b + 1)
                if (nbits > b + 1) kb_bit(d[b]);
            if (nbits > 9)  kb_bit(par);
            if (nbits > 10) kb_bit(stop);
            kb_dat_oe = 1'b0;
            repeat (HP) @(posedge clk);
        end
    endtask

    task kb_send;
        input [7:0] d;
        begin
            kb_frame(1'b0, d, !(^d), 1'b1, 11);   // odd parity
            expect_q[exp_wr] = d;
            exp_wr = exp_wr + 1;
        end
    endtask

    // Drain whatever is in the FIFO, counting how many of the bytes were
    // `want`. Used where the question is not "what came back" but
    // "was anything lost".
    task drain;
        input  [7:0] want;
        output integer hits;
        output integer total;
        integer guard;
        begin
            hits = 0; total = 0; guard = 0;
            io_read(A_STAT);
            while (got[0] && guard < 64) begin
                io_read(A_DATA);
                total = total + 1;
                if (got == want) hits = hits + 1;
                io_read(A_STAT);
                guard = guard + 1;
            end
        end
    endtask

    // Host to device. The device clocks; the host is expected to put a
    // bit out after each falling edge and the device reads it while the
    // clock is high. Eleven pulses: eight data, parity, stop, ack.
    //
    // The task returns **still holding the acknowledge low**, because
    // whether the host waits that out is a thing worth checking, and a
    // model that let go on its own would hide it. `kb_release` ends it.
    //
    // `do_ack` is a parameter for the same reason: a keyboard that is
    // not there does not acknowledge, and neither does one that did not
    // understand the command.
    task kb_receive;
        input   do_ack;
        integer b;
        begin
            txbits    = 11'h7FF;
            inhibit_n = 0;

            // The inhibit. Its *length* is the protocol's requirement —
            // a device is entitled to ignore anything shorter than
            // 100 us — so the model measures it rather than merely
            // noticing it happened.
            wait (dut_clk_oe);
            while (dut_clk_oe) begin
                @(posedge clk);
                inhibit_n = inhibit_n + 1;
            end
            repeat (HP) @(posedge clk);

            for (b = 1; b <= 11; b = b + 1) begin
                // The acknowledge is the one bit the device drives, and
                // it goes on the line while the clock is high — the
                // protocol's own exception, and worth doing properly
                // because a block that sampled it on the wrong level
                // would still pass a lazier model.
                if (b == 11 && do_ack) kb_dat_oe = 1'b1;
                repeat (HP) @(posedge clk);
                kb_clk_oe = 1'b1;                 // falling edge
                repeat (HP) @(posedge clk);
                kb_clk_oe = 1'b0;                 // rising edge
                repeat (HP / 2) @(posedge clk);
                txbits[b - 1] = ps2_dat;          // read while high
                repeat (HP / 2) @(posedge clk);
            end
        end
    endtask

    task kb_release;
        begin
            kb_dat_oe = 1'b0;
            repeat (2 * HP) @(posedge clk);
        end
    endtask

    // Wait for KBD_STAT to report a byte, with a bound so a block that
    // never delivers one fails rather than hangs.
    task wait_avail;
        integer guard;
        begin
            guard = 0;
            st = 8'h00;
            while (!st[0] && guard < 20000) begin
                io_read(A_STAT);
                st = got;
                guard = guard + 1;
            end
            check(st[0], "a byte arrived");
        end
    endtask

    // ------------------------------------------------------------- runs

    initial begin
        errors = 0; checks = 0;
        exp_wr = 0; exp_rd = 0;
        io_a = 8'h00; io_wdata = 8'h00; io_rd = 1'b0; io_we = 1'b0;
        kb_clk_oe = 1'b0; kb_dat_oe = 1'b0;
        cap = 8'h00; got = 8'h00; st = 8'h00;

        verbose = $test$plusargs("verbose");
        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_ps2_tb);
        end

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (4) @(posedge clk);

        // ---------------------------------------------------- the decode
        check(!o_sel, "idle address is not claimed");
        io_a = 8'h40; #1; check(o_sel, "$FE40 claimed");
        io_a = 8'h43; #1; check(o_sel, "$FE43 claimed");
        io_a = 8'h3F; #1; check(!o_sel, "$FE3F is somebody else's");
        io_a = 8'h44; #1; check(o_sel, "$FE44 claimed: the modifiers");
        io_a = 8'h45; #1; check(!o_sel, "$FE45 is somebody else's");

        io_read(A_STAT);
        check_eq(got, 8'h00, "everything quiet at reset");

        // ------------------------------------------------- one scancode
        //
        // $1C is 'A' in Set 2, which is the byte the monitor's table has
        // to turn back into a letter.
        kb_send(8'h1C);
        wait_avail;
        io_read(A_DATA);
        check_eq(got, 8'h1C, "the scancode came through");

        io_read(A_STAT);
        check_eq(got[0], 1'b0, "and the FIFO is empty again");
        exp_rd = exp_wr;

        // ------------------------------------------- a break sequence
        //
        // Releasing a key sends $F0 then the code, so three bytes have to
        // come back in order and not merely arrive.
        kb_send(8'h1C);
        kb_send(8'hF0);
        kb_send(8'h1C);
        for (i = 0; i < 3; i = i + 1) begin
            wait_avail;
            io_read(A_DATA);
            check_eq(got, expect_q[exp_rd], "in order");
            exp_rd = exp_rd + 1;
        end

        // -------------------------------------------------- parity error
        //
        // The byte must be dropped, not queued with a flag beside it: a
        // scancode nobody can trust is worse than a missing one, because
        // it desynchronises a break sequence.
        kb_frame(1'b0, 8'h55, ^8'h55, 1'b1, 11);   // even parity: wrong
        repeat (4 * HP) @(posedge clk);
        io_read(A_STAT);
        check_eq(got[2], 1'b1, "parity error flagged");
        check_eq(got[0], 1'b0, "and the byte was dropped");

        io_write(A_STAT, 8'h04);             // write 1 to clear
        io_read(A_STAT);
        check_eq(got[2], 1'b0, "parity error acknowledged");

        // ------------------------------------------ a framing error
        //
        // The start and stop bits are the only evidence a frame is a
        // frame. A block that ignored them would accept eleven bits of
        // line noise as a keystroke, and the noise a PS/2 cable picks up
        // is exactly what those two bits exist to reject.
        kb_frame(1'b1, 8'h55, !(^8'h55), 1'b1, 11);
        repeat (4 * HP) @(posedge clk);
        io_read(A_STAT);
        check_eq(got[0], 1'b0, "a frame with no start bit is rejected");
        check_eq(got[2], 1'b1, "and reported");
        io_write(A_STAT, 8'h04);

        kb_frame(1'b0, 8'h55, !(^8'h55), 1'b0, 11);
        repeat (4 * HP) @(posedge clk);
        io_read(A_STAT);
        check_eq(got[0], 1'b0, "a frame with no stop bit is rejected");
        check_eq(got[2], 1'b1, "and reported");
        io_write(A_STAT, 8'h04);

        // ----------------------------------------------- the watchdog
        //
        // Five bits and then silence. Without the watchdog the next
        // frame lands six bits out of step and every frame after it is
        // wrong forever, which is the failure mode that makes hot
        // plugging impossible.
        kb_frame(1'b0, 8'hAA, 1'b0, 1'b1, 5);
        repeat (3 * T60US) @(posedge clk);
        kb_send(8'h29);                      // space
        wait_avail;
        io_read(A_DATA);
        check_eq(got, 8'h29, "resynchronised after a half frame");

        io_write(A_STAT, 8'h04);             // the half frame may have set it
        io_write(A_CTRL, 8'h01);

        // ------------------------------------------------ a clock glitch
        //
        // Shorter than the filter, so it must not be seen at all. A
        // filter that let it through would shift a bit in and the frame
        // after would be wrong.
        kb_clk_oe = 1'b1;
        repeat (FILT - 2) @(posedge clk);
        kb_clk_oe = 1'b0;
        repeat (4 * HP) @(posedge clk);
        kb_send(8'h1B);                      // 'S'
        wait_avail;
        io_read(A_DATA);
        check_eq(got, 8'h1B, "a glitch shorter than the filter is ignored");

        // ------------------------------------------------- the FIFO fills
        //
        // Sixteen deep, and the seventeenth byte is the one lost — the
        // newest, which is what keeps the oldest keystrokes rather than
        // the newest noise.
        io_write(A_CTRL, 8'h01);             // clear
        exp_wr = 0; exp_rd = 0;
        for (i = 0; i < 16; i = i + 1)
            kb_send(8'h10 + i[7:0]);
        repeat (2 * HP) @(posedge clk);
        io_read(A_STAT);
        check_eq(got[1], 1'b0, "sixteen bytes is not an overflow");

        kb_send(8'hEE);                      // the seventeenth
        repeat (2 * HP) @(posedge clk);
        io_read(A_STAT);
        check_eq(got[1], 1'b1, "the seventeenth overflows");

        for (i = 0; i < 16; i = i + 1) begin
            wait_avail;
            io_read(A_DATA);
            check_eq(got, 8'h10 + i[7:0], "the sixteen that fitted");
        end
        io_read(A_STAT);
        check_eq(got[0], 1'b0, "and the newest byte is the one that went");

        io_write(A_STAT, 8'h02);
        io_read(A_STAT);
        check_eq(got[1], 1'b0, "overflow acknowledged");

        // ------------------------------- a read landing on the push
        //
        // The FIFO is a block RAM and a block RAM reads a cycle late, so
        // for one cycle after a byte lands in an empty FIFO the read
        // register still holds the previous one. `settle` is what stops
        // that cycle being visible, and nothing above would notice if it
        // were removed: every test so far polls KBD_STAT first and the
        // poll is what hides it.
        //
        // So: one *blind* read of KBD_DATA, swept across the window the
        // byte arrives in, and the property is not what the read
        // returned but that **the byte is neither lost nor duplicated**.
        // A stale read is the failure that matters because it pops as
        // well as lies — it takes the keystroke with it.
        //
        // The byte changes every iteration on a period of 13, so the
        // value left in the read register by an earlier round can never
        // be mistaken for this round's.
        for (j = 380; j < 460; j = j + 1) begin
            curb = 8'h50 + (j % 13);
            io_write(A_CTRL, 8'h01);
            repeat (4) @(posedge clk);
            fork
                kb_frame(1'b0, curb, !(^curb), 1'b1, 11);
                begin
                    repeat (j) @(posedge clk);
                    io_read(A_DATA);
                    n = (got == curb) ? 1 : 0;
                end
            join
            drain(curb, hits, total);
            check(n + hits == 1, "a blind read never loses the byte");
            check(total <= 1, "and never duplicates it");
        end

        // ------------------------------------------------- the FIFO clear
        exp_wr = 0; exp_rd = 0;
        kb_send(8'h12);
        kb_send(8'h59);
        wait_avail;
        io_write(A_CTRL, 8'h01);
        repeat (4) @(posedge clk);
        io_read(A_STAT);
        check_eq(got[0], 1'b0, "clear empties the FIFO");

        // ---------------------------------------------------- interrupts
        io_read(A_CTRL);
        check_eq(got, 8'h00, "interrupts start disabled");
        check(!o_irq, "and the line is low");

        // A byte with interrupts *off* is the case that matters: the
        // line has to stay low with something in the FIFO, and every
        // check that only looks at an empty FIFO passes either way.
        kb_send(8'h1C);
        wait_avail;
        check(!o_irq, "a byte with interrupts off does not raise the line");
        io_read(A_DATA);

        io_write(A_CTRL, 8'h10);
        io_read(A_CTRL);
        check_eq(got, 8'h10, "interrupt enable reads back");
        check(!o_irq, "still low with an empty FIFO");

        kb_send(8'h1C);
        wait_avail;
        check(o_irq, "a byte raises the line");
        io_read(A_DATA);
        repeat (2) @(posedge clk);
        check(!o_irq, "and reading it lowers it again");

        io_write(A_CTRL, 8'h00);

        // ------------------------------------------------ host to device
        //
        // $ED is SET LEDS, the one command a monitor has a use for.
        fork
            kb_receive(1'b1);
            io_write(A_TX, 8'hED);
        join

        check_eq(txbits[7:0], 8'hED, "the device received the byte");
        // `!` and not `~`. A reduction gives one bit, but the width of
        // this expression is set by the 32-bit task port it is passed
        // to, so `~` inverts all thirty-two of them and compares 1
        // against $FFFFFFFF. Logical negation is self-determined.
        check_eq(txbits[8], !(^8'hED), "with odd parity");
        check_eq(txbits[9], 1'b1, "and a stop bit");

        // The protocol's own number, and the reason this block has a
        // 100 us timer in it at all. A device is entitled to ignore a
        // shorter one.
        check(inhibit_n >= T100US, "the inhibit was long enough");

        // The device is still holding the acknowledge down. The host has
        // to wait that out rather than call the transfer finished and
        // start reading the line again — a release read as a start bit
        // is a phantom keystroke.
        io_read(A_STAT);
        check_eq(got[3], 1'b1, "still busy while the device holds the ack");

        kb_release;
        io_read(A_STAT);
        check_eq(got[3], 1'b0, "transmit finished once it lets go");
        check_eq(got[4], 1'b0, "and was acknowledged");

        // The keyboard answers $FA, and it has to be received normally —
        // a transmit path that left the receiver out of step would show
        // up exactly here and nowhere earlier.
        kb_send(8'hFA);
        wait_avail;
        io_read(A_DATA);
        check_eq(got, 8'hFA, "the keyboard's ack byte came back");

        // ------------------------------------------- a command refused
        //
        // A device that clocks the byte in and then does not acknowledge
        // it has not accepted it, and the difference between that and
        // success is the whole value of the status bit.
        fork
            kb_receive(1'b0);
            io_write(A_TX, 8'hEE);
        join
        repeat (4 * HP) @(posedge clk);
        io_read(A_STAT);
        check_eq(got[4], 1'b1, "a missing acknowledge is reported");
        check_eq(got[3], 1'b0, "and the transmit still ended");
        io_write(A_STAT, 8'h10);

        // -------------------------------------------- nobody plugged in
        //
        // A monitor setting the caps-lock LED must not hang on a wire
        // with no keyboard on the end of it.
        io_write(A_TX, 8'h ED);
        io_read(A_STAT);
        check_eq(got[3], 1'b1, "transmit is busy");

        n = 0;
        st = 8'h08;
        while (st[3] && n < 40000) begin
            io_read(A_STAT);
            st = got;
            n = n + 1;
        end
        check_eq(st[3], 1'b0, "and gives up when nothing answers");
        check_eq(st[4], 1'b1, "reporting the timeout");

        io_write(A_STAT, 8'h10);
        io_read(A_STAT);
        check_eq(got[4], 1'b0, "timeout acknowledged");

        // The wire has to be left alone afterwards, or the keyboard that
        // is eventually plugged in never gets to talk.
        check(!dut_clk_oe, "the clock line is released");
        check(!dut_dat_oe, "and so is the data line");

        // ------------------------------------- the modifiers and the chords
        //
        // The state is tracked here rather than in software because a
        // program that has taken the vectors and stopped reading the
        // FIFO still has to be interruptible -- see the module header.
        // What is checked is that it follows the byte stream, break
        // codes included, and that neither chord fires by accident.
        // The frames above were sent as data, and some of them happen to
        // be modifier scancodes -- which the tracker believed, correctly.
        // So this phase starts by putting everything back up.
        io_write(A_MOD, 8'h08);                  // and clear a stale flag
        kb_send(8'hF0); kb_send(8'h11);          // Alt up
        wait_avail; io_read(A_DATA);
        wait_avail; io_read(A_DATA);
        kb_send(8'hF0); kb_send(8'h12);          // Shift up
        wait_avail; io_read(A_DATA);
        wait_avail; io_read(A_DATA);
        kb_send(8'hF0); kb_send(8'h14);          // Ctrl up
        wait_avail; io_read(A_DATA);
        wait_avail; io_read(A_DATA);
        io_read(A_MOD);
        check_eq(got, 8'h00, "nothing is held to begin with");

        kb_send(8'h14);                          // Ctrl down
        wait_avail; io_read(A_DATA);
        io_read(A_MOD);
        check_eq(got, 8'h02, "Ctrl down shows in the modifiers");

        kb_send(8'h12);                          // Shift down as well
        wait_avail; io_read(A_DATA);
        io_read(A_MOD);
        check_eq(got, 8'h03, "...and Shift beside it");

        kb_send(8'hF0); kb_send(8'h12);          // Shift up again
        wait_avail; io_read(A_DATA);
        wait_avail; io_read(A_DATA);
        io_read(A_MOD);
        check_eq(got, 8'h02, "a break code takes Shift away");
        check(!o_reset && !o_warm, "and no chord fired on the way");

        // Ctrl is still down, so Esc is the warm chord: a pulse, and a
        // flag that stays until it is acknowledged.
        kb_send(8'h76);
        wait_avail; io_read(A_DATA);
        io_read(A_MOD);
        check_eq(got, 8'h0A, "Ctrl+Esc latches the warm-restart flag");
        io_write(A_MOD, 8'h08);
        io_read(A_MOD);
        check_eq(got, 8'h02, "...and writing the bit back clears it");

        // With Shift held it is the cold one, which resets the machine
        // rather than asking anybody.
        kb_send(8'h12);
        wait_avail; io_read(A_DATA);
        fork
            begin
                kb_send(8'h76);
                wait_avail; io_read(A_DATA);
            end
            begin : watch_reset
                integer k;
                saw_reset = 1'b0;
                for (k = 0; k < 40000; k = k + 1) begin
                    @(posedge clk);
                    if (o_reset) saw_reset = 1'b1;
                end
            end
        join
        check(saw_reset, "Ctrl+Shift+Esc asks for a reset");

        // Esc on its own is a key like any other -- the chord must not
        // fire for it, or Escape would restart the machine.
        io_write(A_MOD, 8'h08);
        kb_send(8'hF0); kb_send(8'h14);          // Ctrl up
        wait_avail; io_read(A_DATA);
        wait_avail; io_read(A_DATA);
        kb_send(8'h76);
        wait_avail; io_read(A_DATA);
        io_read(A_MOD);
        check_eq(got, 8'h01, "a plain Escape is not a chord");

        $display("\n  %0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("PASS");
        else             $display("FAILED");
        $finish;
    end

    // Nothing here should take this long; a hang is a failure with a
    // useful name rather than a test run that never ends.
    initial begin
        #40000000;
        $display("FAIL timeout");
        $display("FAILED");
        $finish;
    end

endmodule

`default_nettype wire
