// cool8_flash_tb — the SPI master, against a flash.
//
// The device end is a behavioural W25Q: it decodes the opcode off the
// wire, and it only knows one. Anything other than $03 makes it fail the
// test rather than quietly return zeros, which is how D16's promise —
// **this hardware cannot issue a program or an erase** — gets checked
// instead of asserted. A master that grew a write path would have to get
// past a device that treats one as an error.
//
// The model samples MOSI on the rising edge of SCK and changes MISO on
// the falling one, which is SPI mode 0 stated from the device's side.
// The master implements the same protocol from the host's side, so the
// two agree only if both are right.
//
// The register interface is driven the way cool8_soc drives it, which
// for FLS_DATA means honouring `o_stall`: a read is launched with a
// one-cycle `io_rd` and then held until the block lets go, exactly as
// mem_ready does it. Reading without that would test a port the machine
// does not have.
//
//   vvp cool8_flash_tb.vvp +vcd=fls.vcd
//
// Plusargs:
//   +vcd=FILE  dump waves
//   +verbose   print every check

`default_nettype none
`timescale 1ns / 1ps

module cool8_flash_tb;

    localparam [7:0] A_ADDR_L = 8'h88,
                     A_ADDR_M = 8'h89,
                     A_ADDR_H = 8'h8A,
                     A_DATA   = 8'h8B,
                     A_CTRL   = 8'h8C,
                     A_WDATA  = 8'h8E,
                     A_WCTRL  = 8'h8F,
                     A_STAT   = 8'h8D;

    reg          clk = 1'b0;
    reg          rst_n = 1'b0;

    integer      errors, checks, i, guard, stalls;
    reg          verbose;
    reg [1023:0] vcdfile;

    reg  [7:0]   io_a, io_wdata;
    reg          io_rd, io_we;
    reg  [7:0]   cap, got;

    wire         o_sel, o_dp_sel, o_stall;
    wire [7:0]   o_rdata, o_dout;
    wire         spi_cs_n, spi_sck, spi_mosi;

    // ------------------------------------------------------- the device

    reg  [7:0]   flash [0:65535];        // 64 KB of the part is plenty
    reg  [7:0]   d_sr;                   // what is being shifted in
    reg  [7:0]   d_out;                  // ...and out
    reg  [23:0]  d_a;                    // where the part thinks it is
    reg  [7:0]   d_op;
    integer      d_bit;                  // bits seen since chip select fell
    reg          d_miso;
    reg          d_bad;                  // an opcode this part does not have
    reg          d_floor;                // ...or a write inside the bitstream
    reg          d_wel;                  // write-enable latch
    integer      ei;

    wire         spi_miso = d_miso;

    always #5 clk = ~clk;

    cool8_flash dut (
        .clk(clk), .rst_n(rst_n),
        .spi_cs_n(spi_cs_n), .spi_sck(spi_sck),
        .spi_mosi(spi_mosi), .spi_miso(spi_miso),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wdata(io_wdata),
        .o_sel(o_sel), .o_dp_sel(o_dp_sel), .o_rdata(o_rdata),
        .o_dout(o_dout), .o_stall(o_stall)
    );

    always @(posedge clk) if (io_rd) cap <= o_rdata;

    // Chip select going high ends the session. Everything about the
    // device resets here and nowhere else, which is what makes "the
    // stream stayed open" a testable property rather than a hope.
    always @(posedge spi_cs_n) begin
        d_bit   = 0;
        d_op    = 8'h00;
        d_miso  = 1'b1;
    end

    // MOSI is sampled on the rising edge — the device's side of mode 0 —
    // and the command is assembled a byte at a time because that is how
    // the part reads it: one opcode, then three address bytes, then it
    // starts streaming and never looks at MOSI again.
    always @(posedge spi_sck) if (!spi_cs_n) begin
        d_sr  = {d_sr[6:0], spi_mosi};
        d_bit = d_bit + 1;
        case (d_bit)
            8: begin
                d_op = d_sr;
                // Five opcodes and no others. A sixth means a master that
                // has learned to say something it must not be able to say.
                if (d_op !== 8'h03 && d_op !== 8'h06 && d_op !== 8'h02 &&
                    d_op !== 8'h20 && d_op !== 8'h05) begin
                    d_bad = 1'b1;
                    $display("FAIL opcode %02h is not one this part has (t=%0t)",
                             d_op, $time);
                end
                if (d_op === 8'h06) d_wel = 1'b1;
            end
            16: d_a[23:16] = d_sr;
            24: d_a[15:8]  = d_sr;
            32: begin
                d_a[7:0] = d_sr;
                d_out    = flash[d_a[15:0]];
                // **The guarantee, tested rather than commented.** An
                // erase below $100000 is inside the bitstream, and no
                // sequence of register writes may be able to produce one.
                if (d_op === 8'h20) begin
                    if (d_a < 24'h100000) begin
                        d_floor = 1'b1;
                        $display("FAIL erase at $%06h is below the floor (t=%0t)",
                                 d_a, $time);
                    end
                    if (!d_wel) begin
                        d_bad = 1'b1;
                        $display("FAIL erase with no write enable (t=%0t)", $time);
                    end
                    for (ei = 0; ei < 4096; ei = ei + 1)
                        flash[(d_a[15:0] & 16'hF000) + ei[15:0]] = 8'hFF;
                    d_wel = 1'b0;
                end
            end
            40: if (d_op === 8'h02) begin
                    if (d_a < 24'h100000) begin
                        d_floor = 1'b1;
                        $display("FAIL program at $%06h is below the floor (t=%0t)",
                                 d_a, $time);
                    end
                    if (!d_wel) begin
                        d_bad = 1'b1;
                        $display("FAIL program with no write enable (t=%0t)", $time);
                    end
                    // A flash can only clear bits; the erase above is what
                    // sets them. Modelling that is what makes the erase
                    // test mean something.
                    flash[d_a[15:0]] = flash[d_a[15:0]] & d_sr;
                    d_wel = 1'b0;
                end
            default: ;
        endcase
    end

    // MISO changes on the falling edge, and the first data bit has to be
    // on the line for the very next rising one — which is the falling
    // edge of the last address bit, before the master has asked for
    // anything.
    // RDSR answers from bit 8 onwards, and this model is never busy, so
    // the status is zero and one poll is always enough.
    always @(negedge spi_sck) if (!spi_cs_n && d_op === 8'h05 && d_bit >= 8)
        d_miso = 1'b0;

    always @(negedge spi_sck) if (!spi_cs_n && d_op === 8'h03 && d_bit >= 32) begin
        d_miso = d_out[7];
        d_out  = {d_out[6:0], 1'b0};
        if (((d_bit - 32) % 8) == 7) begin
            d_a   = d_a + 24'd1;         // the byte just finished
            d_out = flash[d_a[15:0]];
        end
    end

    // ---------------------------------------------------------- helpers

    task check;
        input         cond;
        input [255:0] what;
        begin
            checks = checks + 1;
            if (!cond) begin
                errors = errors + 1;
                $display("FAIL %0s  (t=%0t)", what, $time);
            end else if (verbose) $display("  ok  %0s", what);
        end
    endtask

    task check_eq;
        input [31:0]  a;
        input [31:0]  b;
        input [255:0] what;
        begin
            checks = checks + 1;
            if (a !== b) begin
                errors = errors + 1;
                $display("FAIL %0s: got %02h want %02h  (t=%0t)",
                         what, a, b, $time);
            end else if (verbose) $display("  ok  %0s = %02h", what, a);
        end
    endtask

    // A program or an erase is three transactions and a poll; the model
    // is never busy, so it settles in a few hundred clocks.
    task wait_write;
        integer w;
        begin
            w = 0;
            while (w < 40000 && (dut.wst != 3'd0 || w < 8)) begin
                @(posedge clk);
                w = w + 1;
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

    // A register read: one cycle, no stall possible.
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

    // FLS_DATA, held across the stall exactly as mem_ready holds it. The
    // launch pulse comes once and does not come again, so a block that
    // needed a second one would hang here — which is the bug this shape
    // exists to catch.
    task io_read_data;
        begin
            @(negedge clk);
            io_a = A_DATA; io_rd = 1'b1;
            @(negedge clk);
            io_rd = 1'b0;
            guard = 0;
            while (o_stall && guard < 100000) begin
                stalls = stalls + 1;
                guard  = guard + 1;
                @(negedge clk);
            end
            if (guard >= 100000) $display("FAIL stalled forever (t=%0t)",
                                          $time);
            got = o_dout;
        end
    endtask

    // ------------------------------------------------------------- runs

    initial begin
        errors = 0; checks = 0; stalls = 0;
        io_a = 8'h00; io_wdata = 8'h00; io_rd = 1'b0; io_we = 1'b0;
        d_bit = 0; d_sr = 8'h00; d_out = 8'h00; d_miso = 1'b1;
        d_op = 8'h00; d_bad = 1'b0; d_floor = 1'b0; d_wel = 1'b0;
        d_a = 24'h000000;
        cap = 8'h00; got = 8'h00;

        for (i = 0; i < 65536; i = i + 1)
            flash[i] = (i[7:0] ^ i[15:8] ^ 8'h5A);

        verbose = $test$plusargs("verbose");
        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_flash_tb);
        end

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (4) @(posedge clk);

        // ---------------------------------------------------- the decode
        io_a = 8'h88; #1; check(o_sel, "$FE88 claimed");
        io_a = 8'h8D; #1; check(o_sel, "$FE8D claimed");
        io_a = 8'h8B; #1; check(o_dp_sel, "$FE8B is the data port");
        io_a = 8'h8C; #1; check(!o_dp_sel, "$FE8C is not");
        io_a = 8'h87; #1; check(!o_sel, "$FE87 is somebody else's");
        io_a = 8'h8E; #1; check(o_sel, "$FE8E is the write data");
        io_a = 8'h8F; #1; check(o_sel, "$FE8F is the write control");
        io_a = 8'h90; #1; check(!o_sel, "$FE90 is somebody else's");

        check(spi_cs_n, "chip select is high at reset");

        // ------------------------------------------------ the registers
        io_write(A_ADDR_L, 8'h34);
        io_write(A_ADDR_M, 8'h12);
        io_write(A_ADDR_H, 8'h00);
        io_read(A_ADDR_L); check_eq(got, 8'h34, "ADDR_L reads back");
        io_read(A_ADDR_M); check_eq(got, 8'h12, "ADDR_M reads back");
        io_read(A_ADDR_H); check_eq(got, 8'h00, "ADDR_H reads back");
        io_read(A_STAT);
        check_eq(got[1], 1'b0, "no stream open yet");

        // ------------------------------------------------- a short read
        //
        // Sixteen bytes from $001234, which is the shape of every load
        // this machine will ever do.
        io_write(A_CTRL, 8'h01);
        io_read(A_STAT);
        check_eq(got[1], 1'b1, "the stream is open");
        check_eq(got[0], 1'b1, "and the command is going out");

        for (i = 0; i < 16; i = i + 1) begin
            io_read_data;
            check_eq(got, flash[16'h1234 + i[15:0]], "streamed byte");
        end

        check(!spi_cs_n, "chip select stayed low through the run");
        check(!d_bad, "and only opcode $03 was ever issued");

        // Open and idle — the one combination that tells the two status
        // bits apart. Every reading taken while a fetch is in flight has
        // both of them set and would pass with the pair exchanged.
        repeat (400) @(negedge clk);
        io_read(A_STAT);
        check_eq(got[1], 1'b1, "still open with the prefetch done");
        check_eq(got[0], 1'b0, "and no longer busy");

        // The address register tracks where the stream got to, so a
        // monitor can show progress without keeping its own count.
        io_read(A_ADDR_L); check_eq(got, 8'h44, "ADDR_L followed the stream");
        io_read(A_ADDR_M); check_eq(got, 8'h12, "ADDR_M followed the stream");

        // Writing the address while the stream is open would put the
        // register out of step with the part, which is counting on its
        // own. It is ignored, so the register never lies.
        io_write(A_ADDR_L, 8'hFF);
        io_read(A_ADDR_L);
        check_eq(got, 8'h44, "an address write while open is ignored");

        // ------------------------------------------------------- close
        io_write(A_CTRL, 8'h00);
        check(spi_cs_n, "closing raises chip select");
        io_read(A_STAT);
        check_eq(got[1], 1'b0, "and the stream is shut");
        check_eq(got[0], 1'b0, "with nothing in flight");

        // ------------------------------------ re-open somewhere else
        //
        // A second session has to issue a fresh command, not carry on:
        // the part has no memory of the last one.
        io_write(A_ADDR_L, 8'h00);
        io_write(A_ADDR_M, 8'hF0);
        io_write(A_ADDR_H, 8'h00);
        io_write(A_CTRL, 8'h01);
        for (i = 0; i < 8; i = i + 1) begin
            io_read_data;
            check_eq(got, flash[16'hF000 + i[15:0]], "second session");
        end
        io_write(A_CTRL, 8'h00);

        // ------------------------------------------- crossing a boundary
        //
        // $00FFFF to $010000 carries into the top address byte, which is
        // the one place a 24-bit counter built out of three 8-bit
        // registers goes wrong.
        io_write(A_ADDR_L, 8'hFD);
        io_write(A_ADDR_M, 8'hFF);
        io_write(A_ADDR_H, 8'h00);
        io_write(A_CTRL, 8'h01);
        for (i = 0; i < 4; i = i + 1) io_read_data;
        io_write(A_CTRL, 8'h00);
        io_read(A_ADDR_L); check_eq(got, 8'h01, "ADDR_L wrapped");
        io_read(A_ADDR_M); check_eq(got, 8'h00, "ADDR_M wrapped");
        io_read(A_ADDR_H); check_eq(got, 8'h01, "and ADDR_H carried");

        // ------------------------------------------------- the stalling
        //
        // A byte is sixteen system clocks and the CPU can ask for one in
        // two, so a tight copy loop has to be held off. If nothing ever
        // stalled, the prefetch would be doing something impossible.
        check(stalls > 100, "reads really did stall");

        // A read with no stream open must not hang: there is nothing to
        // fetch and nothing to wait for.
        io_read(A_STAT);
        check_eq(got[1], 1'b0, "no stream");
        @(negedge clk);
        io_a = A_DATA; io_rd = 1'b1;
        @(negedge clk);
        io_rd = 1'b0;
        repeat (200) @(negedge clk);
        check(!o_stall, "a read with no stream open does not hang");

        // ================================================================
        // Writing, and the floor that makes it safe
        // ================================================================
        //
        // Last in the file on purpose. An erase clears a whole 4 KB
        // sector, and the device model aliases every address into its
        // 64 KB array, so an erase placed earlier wipes bytes a later read
        // phase checks — which is exactly what happened the first time.

        // ---- a program above the floor lands
        io_write(A_ADDR_L, 8'h00);
        io_write(A_ADDR_M, 8'h50);
        io_write(A_ADDR_H, 8'h10);          // $105000
        io_write(A_WDATA,  8'h5A);
        flash[16'h5000] = 8'hFF;            // erased, so the AND shows
        io_write(A_WCTRL, 8'h01);
        wait_write;
        check(flash[16'h5000] == 8'h5A, "a byte above the floor programmed");

        // ---- an erase above the floor clears its sector
        flash[16'h6010] = 8'h00;
        io_write(A_ADDR_L, 8'h10);
        io_write(A_ADDR_M, 8'h60);
        io_write(A_ADDR_H, 8'h10);          // $106010
        io_write(A_WCTRL, 8'h02);
        wait_write;
        check(flash[16'h6010] == 8'hFF, "the sector above the floor erased");

        // ---- **and neither does anything below it**
        flash[16'h0100] = 8'h77;
        io_write(A_ADDR_L, 8'h00);
        io_write(A_ADDR_M, 8'h01);
        io_write(A_ADDR_H, 8'h00);          // $000100 — inside the bitstream
        io_write(A_WDATA,  8'h00);
        io_write(A_WCTRL, 8'h01);
        repeat (600) @(posedge clk);
        check(flash[16'h0100] == 8'h77, "a program below the floor did nothing");
        io_read(A_WCTRL);
        check(cap[2], "...and the refusal is visible");

        io_write(A_WCTRL, 8'h02);
        repeat (600) @(posedge clk);
        check(flash[16'h0100] == 8'h77, "an erase below the floor did nothing");
        check(spi_cs_n, "and chip select never went low for either");

        io_write(A_WCTRL, 8'h04);
        io_read(A_WCTRL);
        check(!cap[2], "the refusal clears by writing its own bit");

        check(!d_bad, "and only opcodes this part has were issued");
        check(!d_floor, "and nothing was ever written below $100000");


        $display("\n  %0d checks, %0d failures, %0d stalled cycles",
                 checks, errors, stalls);
        if (errors == 0 && !d_bad) $display("PASS");
        else                       $display("FAILED");
        $finish;
    end

    initial begin
        #40000000;
        $display("FAIL timeout");
        $display("FAILED");
        $finish;
    end

endmodule

`default_nettype wire
