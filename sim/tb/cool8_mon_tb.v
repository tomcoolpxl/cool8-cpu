// cool8_mon_tb — M6's gate: type at the machine and it answers.
//
// The whole SoC, cold, on the parameters the bitstream carries: the real
// boot image, SPRAM undefined, the default 115200 divider. Nothing is
// poked and nothing is forced. Then characters are bit-banged in on the
// serial line and on the PS/2 clock, and what comes back out is
// compared against what the monitor is supposed to say.
//
// **The keyboard is driven as a keyboard**, with the same open-drain
// wire and the same eleven-bit frames cool8_ps2_tb uses, because the
// point of this test is the path a keystroke really takes: scancode,
// FIFO, the CPU's own load, the translation table in ROM, the echo, and
// out. A test that poked KBD_DATA would prove none of it.
//
// What the output is checked against is text, not a byte count. Every
// phase names a string the monitor has to produce, and the receiver
// scans for it with a bounded wait — so a monitor that answers the
// wrong thing fails as loudly as one that answers nothing.
//
//   vvp cool8_mon_tb.vvp
//
// Plusargs:
//   +vcd=FILE  dump waves
//   +verbose   echo everything the machine says

`default_nettype none
`timescale 1ns / 1ps

module cool8_mon_tb;

    localparam integer DIV0 = 72;          // 115200 at 8.375 MHz
    localparam integer HP   = 400;         // system clocks per PS/2 half period

    reg          clk = 1'b0;
    reg          pclk = 1'b0;
    reg          rst_n = 1'b0;

    integer      errors, checks, i, n;

    // **Whether the origin ever moved, not where it happens to be now.**
    // `vtop` wraps at 32 rows, so a session that scrolls a multiple of
    // 32 times leaves VID_BASE back at $8000 and a sampled check reads
    // that as "never scrolled". One extra line in the monitor's help
    // text was enough to land on it. A latch cannot be fooled that way.
    reg          base_moved;
    reg          verbose;
    reg [1023:0] vcdfile;

    reg          host_tx = 1'b1;
    integer      bitclk;

    wire         uart_tx;
    wire [2:0]   led;

    // Everything the machine has said, as a flat buffer the scanner
    // walks. 4 KB is more than any one phase produces.
    reg [7:0]    rxq [0:4095];
    integer      rxq_wr, rxq_rd;

    reg  [7:0]   pat [0:63];               // what we are looking for
    integer      patlen;

    reg          kb_clk_oe, kb_dat_oe;
    wire         ps2_clk_oe, ps2_dat_oe;
    wire         ps2_clk = ~(ps2_clk_oe | kb_clk_oe);
    wire         ps2_dat = ~(ps2_dat_oe | kb_dat_oe);

    // A flash on the other end, so the monitor's L command has
    // something to load from. Same model as cool8_flash_tb's, and it
    // fails the run on any opcode it does not know for the same
    // reason. It knows three: $03 read, and the $FF / $AB wake-up
    // frames cool8_flash sends once at reset — the controller grew
    // those for the real part, which sleeps, and a model that flagged
    // them was a model still assuming the flash starts awake.
    wire         spi_cs_n, spi_sck, spi_mosi;
    reg  [7:0]   flash [0:65535];
    reg  [7:0]   d_sr, d_out;
    reg  [23:0]  d_a;
    integer      d_bit;
    reg          d_miso, d_bad;
    wire         spi_miso = d_miso;

    always @(posedge clk) begin
        if (!rst_n) base_moved <= 1'b0;
        else if (u_soc.u_vid.u_vregs.base_r != 16'h8000) base_moved <= 1'b1;
    end

    always #5 clk = ~clk;
    always #2.39 pclk = ~pclk;

    cool8_soc u_soc (
        .clk(clk), .rst_n(rst_n),
        .pclk(pclk), .prst_n(rst_n),
        .uart_rx(host_tx), .uart_tx(uart_tx),
        .ps2_clk_i(ps2_clk), .ps2_dat_i(ps2_dat),
        .ps2_clk_oe(ps2_clk_oe), .ps2_dat_oe(ps2_dat_oe),
        .spi_cs_n(spi_cs_n), .spi_sck(spi_sck),
        .spi_mosi(spi_mosi), .spi_miso(spi_miso),
        .rgb(), .hsync_n(), .vsync_n(),
        .led(led),
        .irq(1'b0), .nmi(1'b0),
        .o_halted()
    );

    // +rxdbg: every byte the UART strobes and every FIFO pop, for
    // chasing a duplicated or lost character to its side of the FIFO.
    reg rxdbg;
    always @(posedge clk) if (rxdbg) begin
        if (u_soc.fwd_valid)
            $display("RXDBG strobe %02h t=%0t", u_soc.fwd_data, $time);
        if (u_soc.rx_pop)
            $display("RXDBG pop %02h rd=%0d wr=%0d t=%0t",
                     u_soc.rx_head, u_soc.rx_rd, u_soc.rx_wr, $time);
        if (u_soc.uart_tx_start)
            $display("RXDBG txgo %02h t=%0t", u_soc.uart_tx_data, $time);
        if (u_soc.io_we && u_soc.io_a == 8'h71)
            $display("RXDBG txwr %02h pc=%04h t=%0t",
                     u_soc.bus_wdata, u_soc.u_cpu.pc, $time);
    end

    always @(posedge spi_cs_n) begin
        d_bit  = 0;
        d_miso = 1'b1;
    end

    always @(posedge spi_sck) if (!spi_cs_n) begin
        d_sr  = {d_sr[6:0], spi_mosi};
        d_bit = d_bit + 1;
        case (d_bit)
            8: if (d_sr !== 8'h03 && d_sr !== 8'hFF && d_sr !== 8'hAB)
               begin
                   d_bad = 1'b1;
                   $display("FAIL opcode %02h, this part only has $03/$FF/$AB",
                            d_sr);
               end
            16: d_a[23:16] = d_sr;
            24: d_a[15:8]  = d_sr;
            32: begin
                d_a[7:0] = d_sr;
                d_out    = flash[d_a[15:0]];
            end
            default: ;
        endcase
    end

    always @(negedge spi_sck) if (!spi_cs_n && d_bit >= 32) begin
        d_miso = d_out[7];
        d_out  = {d_out[6:0], 1'b0};
        if (((d_bit - 32) % 8) == 7) begin
            d_a   = d_a + 24'd1;
            d_out = flash[d_a[15:0]];
        end
    end

    // ------------------------------------------------- the host's wire

    task send_bit;
        input b;
        begin
            host_tx <= b;
            repeat (bitclk) @(posedge clk);
        end
    endtask

    task send_byte;
        input [7:0] b;
        integer k;
        begin
            send_bit(1'b0);
            for (k = 0; k < 8; k = k + 1) send_bit(b[k]);
            send_bit(1'b1);
            repeat (bitclk) @(posedge clk);
        end
    endtask

    initial begin : receiver
        reg [7:0] b;
        integer k;
        rxq_wr = 0;
        rxq_rd = 0;
        wait (rst_n);
        forever begin
            @(negedge uart_tx);
            repeat (bitclk + (bitclk / 2)) @(posedge clk);
            for (k = 0; k < 8; k = k + 1) begin
                b[k] = uart_tx;
                if (k < 7) repeat (bitclk) @(posedge clk);
            end
            repeat (bitclk) @(posedge clk);
            if (rxq_wr < 4096) begin
                rxq[rxq_wr] = b;
                rxq_wr = rxq_wr + 1;
            end
            if (rxdbg) $display("RXDBG txrx %02h t=%0t", b, $time);
            if (verbose) $write("%0s", b);
        end
    end

    // ---------------------------------------------------- the keyboard

    task kb_bit;
        input b;
        begin
            kb_dat_oe = ~b;
            repeat (HP) @(posedge clk);
            kb_clk_oe = 1'b1;
            repeat (HP) @(posedge clk);
            kb_clk_oe = 1'b0;
        end
    endtask

    task kb_send;
        input [7:0] d;
        integer b;
        begin
            kb_bit(1'b0);
            for (b = 0; b < 8; b = b + 1) kb_bit(d[b]);
            kb_bit(!(^d));                 // odd parity
            kb_bit(1'b1);
            kb_dat_oe = 1'b0;
            repeat (HP) @(posedge clk);
        end
    endtask

    // A make code and the break that follows it, which is what pressing
    // a key actually sends. The break has to be swallowed by the ROM's
    // translation or every keystroke would arrive twice.
    task kb_key;
        input [7:0] d;
        begin
            kb_send(d);
            kb_send(8'hF0);
            kb_send(d);
        end
    endtask

    // ------------------------------------------------------- the check
    //
    // `expect_str` scans forward from wherever the last one finished, so the
    // phases are ordered in time and a reply that arrives out of order
    // fails. It consumes clocks while it waits, which is what lets the
    // machine get on with answering.

    task put_pat;
        input [7:0] c;
        begin
            pat[patlen] = c;
            patlen = patlen + 1;
        end
    endtask

    // `scanned` is carried across the wait rather than reset inside it.
    // Restarting the scan on every clock edge makes this O(clocks x
    // buffer) — three million iterations over a thousand bytes — and the
    // first version of this file did exactly that and simply never
    // finished. Each byte is now looked at once per pattern.
    task expect_str;
        input [511:0] what;
        integer k, j, hit, scanned;
        begin
            k = 0;
            hit = -1;
            scanned = rxq_rd;
            while (hit < 0 && k < 3000000) begin
                while (scanned + patlen <= rxq_wr && hit < 0) begin
                    j = 0;
                    while (j < patlen && rxq[scanned + j] === pat[j])
                        j = j + 1;
                    if (j == patlen) hit = scanned;
                    else scanned = scanned + 1;
                end
                if (hit < 0) begin
                    @(posedge clk);
                    k = k + 1;
                end
            end
            checks = checks + 1;
            if (hit < 0) begin
                errors = errors + 1;
                $display("FAIL the machine never said \"%0s\"", what);
            end else begin
                rxq_rd = hit + patlen;
                if (verbose) $display("\n  ok  \"%0s\"", what);
            end
            patlen = 0;
        end
    endtask

    // type -- a string down the wire, then a return.
    task type_ch;
        input [7:0] c;
        begin
            send_byte(c);
        end
    endtask

    // ==================================================================

    initial begin
        errors = 0; checks = 0; patlen = 0;
        bitclk = DIV0 + 1;
        kb_clk_oe = 1'b0; kb_dat_oe = 1'b0;

        rxdbg = $test$plusargs("rxdbg");
        d_bit = 0; d_sr = 8'h00; d_out = 8'h00; d_miso = 1'b1;
        d_bad = 1'b0; d_a = 24'h000000;
        for (i = 0; i < 65536; i = i + 1)
            flash[i] = (i[7:0] ^ i[15:8] ^ 8'h5A);

        verbose = $test$plusargs("verbose");
        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_mon_tb);
        end

        repeat (4) @(posedge clk);
        rst_n = 1'b1;

        // ---- the machine comes up and introduces itself
        put_pat("C"); put_pat("O"); put_pat("O"); put_pat("L");
        put_pat("8"); put_pat(" "); put_pat("m"); put_pat("o");
        put_pat("n"); put_pat("i"); put_pat("t"); put_pat("o");
        put_pat("r");
        expect_str("COOL8 monitor");

        put_pat("*");
        expect_str("the prompt");

        // ---- an unknown command is refused rather than ignored
        type_ch("Z");
        type_ch(8'h0D);
        put_pat("?");
        expect_str("? for an unknown command");

        // ---- ?: the help. It is here because it is the one command
        //      that is not a letter, and folding the command to upper
        //      case with a single `BCLR #$20` turns '?' ($3F) into $1F.
        //      Every other command survives that and this one does not,
        //      so a test that only exercises letters would never see it.
        type_ch("?");
        type_ch(8'h0D);
        put_pat("u"); put_pat("n"); put_pat("a"); put_pat("s");
        put_pat("s"); put_pat("e"); put_pat("m"); put_pat("b");
        put_pat("l"); put_pat("e");
        expect_str("? lists the commands");

        // ---- D: dump. $F000 is the reset vector's target and the first
        //      bytes of the ROM, so the answer is known without reading
        //      it out of the design.
        type_ch("D"); type_ch(" ");
        type_ch("F"); type_ch("0"); type_ch("0"); type_ch("0");
        type_ch(8'h0D);
        put_pat("F"); put_pat("0"); put_pat("0"); put_pat("0");
        put_pat(" "); put_pat("2"); put_pat("F"); put_pat(" ");
        put_pat("6"); put_pat("0");
        expect_str("D F000 -> 2F 60");

        // ---- E then D: a byte written and read back. This is the whole
        //      of "the machine can be told something and remembers it".
        type_ch("E"); type_ch(" ");
        type_ch("0"); type_ch("5"); type_ch("0"); type_ch("0");
        type_ch(" "); type_ch("A"); type_ch("5");
        type_ch(" "); type_ch("5"); type_ch("A");
        type_ch(8'h0D);
        put_pat("*");                    // E says nothing; it prompts again
        expect_str("E accepted and prompted");

        type_ch("D"); type_ch(" ");
        type_ch("0"); type_ch("5"); type_ch("0"); type_ch("0");
        type_ch(8'h0D);
        put_pat("0"); put_pat("5"); put_pat("0"); put_pat("0");
        put_pat(" "); put_pat("A"); put_pat("5"); put_pat(" ");
        put_pat("5"); put_pat("A");
        expect_str("D 0500 -> A5 5A");

        // ---- U: unassemble. $F000 is `LDW X,#$0200`, the first
        //      instruction the machine ever executes.
        type_ch("U"); type_ch(" ");
        type_ch("F"); type_ch("0"); type_ch("0"); type_ch("0");
        type_ch(8'h0D);
        put_pat("L"); put_pat("D"); put_pat("W"); put_pat(" ");
        put_pat(" "); put_pat("X"); put_pat(","); put_pat("#");
        put_pat("$"); put_pat("0"); put_pat("2"); put_pat("0");
        put_pat("0");
        expect_str("U F000 -> LDW  X,#$0200");

        // ---- L: load from the flash. Four bytes from flash $000200 to
        //      $0600, then read them back — which is the only phase that
        //      exercises the stall on FLS_DATA, since the copy loop has
        //      no status poll in it and the SPI is eight times slower
        //      than the CPU asking.
        type_ch("L"); type_ch(" ");
        type_ch("0"); type_ch("6"); type_ch("0"); type_ch("0");
        type_ch(" "); type_ch("4");
        type_ch(" "); type_ch("0"); type_ch("0"); type_ch("0");
        type_ch("2");
        type_ch(8'h0D);
        put_pat("o"); put_pat("k");
        expect_str("L reported ok");

        type_ch("D"); type_ch(" ");
        type_ch("0"); type_ch("6"); type_ch("0"); type_ch("0");
        type_ch(8'h0D);
        put_pat("0"); put_pat("6"); put_pat("0"); put_pat("0");
        put_pat(" "); put_pat("5"); put_pat("8"); put_pat(" ");
        put_pat("5"); put_pat("9"); put_pat(" "); put_pat("5");
        put_pat("A"); put_pat(" "); put_pat("5"); put_pat("B");
        expect_str("the flash bytes landed in memory");

        // ---- the keyboard. Set 2 $1C is 'A'; with no shift it is 'a',
        //      and the monitor echoes what it reads. Then $12 is the
        //      left shift, held, and the same key is 'A'.
        kb_key(8'h1C);
        put_pat("a");
        expect_str("a keystroke echoed");

        kb_send(8'h12);                  // shift down
        kb_key(8'h1C);
        kb_send(8'hF0); kb_send(8'h12);  // shift up
        put_pat("A");
        expect_str("and shift held gives the capital");

        // ---- the scroll moved the window, not the text
        //
        // Everything above has printed far more than thirty lines, so
        // `scroll` has run many times. It works by advancing VID_BASE
        // rather than copying 4640 bytes (D30, D35), and the two things
        // that have to stay true while it does are exactly the two the
        // hardware's circular wrap depends on:
        //
        //   the origin stays inside the 32-row map, because the fetch
        //   engine wraps within `base & ~(stride*32 - 1)` and a base
        //   allowed to walk past $9FFF takes the window with it;
        //
        //   the origin stays a whole number of rows, because the wrap is
        //   a mask and a base off a row boundary shifts every row on the
        //   screen by the remainder.
        //
        // Neither is visible in the serial output, which is why this is a
        // peek rather than an `expect_str`. The monitor scrolled by
        // copying until M7 and this check is what stops it regressing to
        // that quietly — a bulk copy leaves VID_BASE at $8000 and passes
        // every other phase in this file.
        checks = checks + 1;
        if (!base_moved) begin
            errors = errors + 1;
            $display("FAIL VID_BASE never moved — scroll is copying again");
        end else if (u_soc.u_vid.u_vregs.base_r[7:0] != 8'h00) begin
            errors = errors + 1;
            $display("FAIL VID_BASE $%04h is not on a row boundary",
                     u_soc.u_vid.u_vregs.base_r);
        end else if (u_soc.u_vid.u_vregs.base_r[15:13] != 3'b100) begin
            errors = errors + 1;
            $display("FAIL VID_BASE $%04h has left the 32-row map",
                     u_soc.u_vid.u_vregs.base_r);
        end else if (verbose)
            $display("\n  ok  VID_BASE $%04h — scrolled in hardware",
                     u_soc.u_vid.u_vregs.base_r);

        type_ch(8'h0D);                  // finish that line

        $display("\n\n  %0d checks, %0d failures", checks, errors);
        if (errors == 0 && !d_bad) $display("PASS");
        else                       $display("FAILED");
        $finish;
    end

    initial begin
        #400000000;
        $display("FAIL timed out");
        $display("FAILED");
        $finish;
    end

endmodule

`default_nettype wire
