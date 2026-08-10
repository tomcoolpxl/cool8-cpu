// cool8_soc_tb — the machine's I/O page, reached the way a host reaches it.
//
// Everything below the SoC has its own testbench. What only exists here
// is the decode: 256 bytes at $FE00 that have to win against 64 KB of
// SPRAM underneath them and a 4 KB boot ROM over the top, and answer on
// the same ready-gated protocol both of those do.
//
// There is no bus stub. The bus master is `cool8_loader`, driven by
// frames bit-banged onto `uart_rx` at the divider the UART is programmed
// with, and later `cool8_core` running programs the assembler built —
// which is the only way to find out whether the CPU's own accesses reach
// the page, wait state and all. Registers are read back through the
// loader's READ command rather than by peeking at the RTL, so a register
// that exists but is not decoded fails here.
//
// Two things are looked at rather than through:
//
//   - The RAM under the I/O page is written by depositing into the
//     SPRAM arrays, because the bus cannot reach it. That is the whole
//     point of the test: prove the page answered and the RAM did not.
//   - The boot ROM is filled from here rather than from an image, with a
//     pattern that depends on the *whole* address, so a byte fetched out
//     of the ROM window is recognisable as such and an aliased high
//     address bit cannot hide behind a matching low byte. The real image
//     boots in cool8_soc_boot_tb.
//
//   vvp cool8_soc_tb.vvp +led=led.hex +echo=echo.hex ...
//
// Plusargs:
//   +led=F +echo=F +talk=F +tx2=F   the four test programs, as hex images
//   +vcd=FILE                       dump waves
//   +verbose                        print every check, not just failures

`default_nettype none
`timescale 1ns / 1ps

module cool8_soc_tb;

    // Verilog-2001 wants declarations ahead of use and Icarus enforces
    // it, so everything the blocks below touch lives here.

    localparam [15:0] DIV0  = 16'd15;      // fast, so the run is short
    localparam [7:0]  BUILD = 8'h5E;       // nothing else in the map reads this
    localparam [7:0]  ACK = 8'h4B, VERSION = 8'h01;
    localparam [7:0]  C_WRITE = 8'h01, C_READ = 8'h02, C_GO = 8'h03,
                      C_HALT = 8'h04, C_RESET = 8'h06, C_PING = 8'h07;

    reg          clk = 1'b0;
    reg          pclk = 1'b0;
    reg          rst_n = 1'b0;

    integer      errors, checks, bitclk, i, n;
    reg          verbose;
    reg [1023:0] vcdfile, ledf, echof, talkf, tx2f;

    reg          host_tx = 1'b1;           // the host's line into uart_rx
    reg [7:0]    csum_tx;                  // running checksum of a sent frame

    wire         uart_tx;
    wire [2:0]   led;
    wire         o_halted;

    reg [7:0]    rxq [0:4095];             // bytes seen coming back
    integer      rxq_wr, rxq_rd;
    reg [7:0]    rxbyte, rxcsum, got8;

    reg [7:0]    prog [0:255];             // an assembled test program
    integer      prog_n;

    reg [15:0]   w16;
    integer      ping_seen, want_next;

    always #5 clk = ~clk;
    // The raster's clock. Incommensurate with the system's on
    // purpose: the video subsystem is inside the SoC now and the
    // only thing these tests want from it is that its clock
    // crossing does not disturb anything on this side of it.
    always #2.39 pclk = ~pclk;

    // ------------------------------------------------------------ DUT

    // LOADER(1): it is a build option now and off by default, but
    // the I/O page includes $FE80-$FE81, which are the loader.
    cool8_soc #(
        .LOADER(1),
        .ROM_INIT(0),                      // filled below, not from an image
        .UART_DIV(DIV0),
        .BUILD_ID(BUILD),
        .RX_ABITS(4)
    ) u_soc (
        .clk(clk), .rst_n(rst_n),
        .pclk(pclk), .prst_n(rst_n),
        .rgb(), .hsync_n(), .vsync_n(),
        .uart_rx(host_tx), .uart_tx(uart_tx),
        // Idle high, which is what the pull-ups give when nothing is
        // plugged in. Left floating they are x, and x on the PS/2
        // clock reaches the filter and then the whole block.
        .ps2_clk_i(1'b1), .ps2_dat_i(1'b1),
        .ps2_clk_oe(), .ps2_dat_oe(),
        .spi_cs_n(), .spi_sck(), .spi_mosi(), .spi_miso(1'b1),
        .led(led),
        .irq(1'b0), .nmi(1'b0),
        .o_halted(o_halted)
    );

    // ------------------------------------------------- the host's UART
    //
    // Each bit is held for exactly the divider the FPGA end is
    // programmed with, so a disagreement about what a bit time is
    // corrupts a byte instead of drifting quietly.

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
            repeat (bitclk) @(posedge clk);      // one idle bit between bytes
        end
    endtask

    // Free-running, so a reply that arrives while the host is still
    // talking is caught rather than missed — which the shared
    // transmitter test depends on.
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
            repeat (bitclk) @(posedge clk);      // through the stop bit
            rxq[rxq_wr] = b;
            rxq_wr = rxq_wr + 1;
        end
    end

    // ------------------------------------------------------- the frames

    task put;                                    // a byte that counts to csum
        input [7:0] b;
        begin
            csum_tx = csum_tx + b;
            send_byte(b);
        end
    endtask

    task send_hdr;
        input [7:0] cmd;
        input [15:0] a;
        input [15:0] l;
        begin
            send_byte(8'hC8);
            send_byte(8'h8C);
            csum_tx = 8'h00;
            put(cmd);
            put(a[7:0]);
            put(a[15:8]);
            put(l[7:0]);
            put(l[15:8]);
        end
    endtask

    task send_csum;
        begin
            send_byte(csum_tx);
        end
    endtask

    task send_cmd;                               // a whole payload-free frame
        input [7:0] cmd;
        input [15:0] a;
        begin
            send_hdr(cmd, a, 16'd0);
            send_csum;
        end
    endtask

    // ------------------------------------------------------- the checks

    task chk;
        input [511:0] name;
        input [31:0] got;
        input [31:0] exp;
        begin
            checks = checks + 1;
            if (got !== exp) begin
                errors = errors + 1;
                $display("FAIL %0s: got %0h, expected %0h", name, got, exp);
            end else if (verbose)
                $display("  ok  %0s = %0h", name, got);
        end
    endtask

    task get_reply;
        output [7:0] b;
        integer k;
        begin
            k = 0;
            while (rxq_rd == rxq_wr && k < 64 * bitclk * 16) begin
                @(posedge clk);
                k = k + 1;
            end
            if (rxq_rd == rxq_wr) begin
                errors = errors + 1;
                $display("FAIL: timed out waiting for a reply byte");
                b = 8'h00;
            end else begin
                b = rxq[rxq_rd];
                rxq_rd = rxq_rd + 1;
            end
        end
    endtask

    task expect_reply;
        input [511:0] name;
        input [7:0] exp;
        begin
            get_reply(rxbyte);
            chk(name, {24'd0, rxbyte}, {24'd0, exp});
        end
    endtask

    // The talk test leaves a program transmitting $80-$FF for as long as
    // it is allowed to run, so a reply has to be picked out of a stream.
    // Nothing the loader ever sends has bit 7 set.
    task expect_reply_amid_stream;
        input [511:0] name;
        input [7:0] exp;
        integer k;
        begin
            k = 0;
            rxbyte = 8'hFF;
            while (rxbyte[7] && k < 64) begin
                get_reply(rxbyte);
                k = k + 1;
            end
            chk(name, {24'd0, rxbyte}, {24'd0, exp});
        end
    endtask

    task expect_quiet;                           // nothing more comes back
        input [511:0] name;
        begin
            repeat (14 * bitclk) @(posedge clk);
            checks = checks + 1;
            if (rxq_rd != rxq_wr) begin
                errors = errors + 1;
                $display("FAIL %0s: %0d unexpected byte(s), first %02h",
                         name, rxq_wr - rxq_rd, rxq[rxq_rd]);
                rxq_rd = rxq_wr;
            end else if (verbose)
                $display("  ok  %0s", name);
        end
    endtask

    task drain;                                  // after a deliberate desync
        begin
            repeat (48 * bitclk) @(posedge clk);
            rxq_rd = rxq_wr;
        end
    endtask

    // ------------------------------------------ the bus, seen from a host

    task bus_write;
        input [511:0] name;
        input [15:0] a;
        input [7:0] d;
        begin
            send_hdr(C_WRITE, a, 16'd1);
            put(d);
            send_csum;
            expect_reply(name, ACK);
        end
    endtask

    // A READ replies with the data and then the frame checksum, which
    // for one byte is the byte itself — checked every time, since it is
    // free and it catches a reply that lost its place in the stream.
    //
    // One byte at a time: the loader advances the address between bytes,
    // so a length-3 READ at $FE71 would read three different registers
    // rather than popping the FIFO three times.
    task bus_read;
        input [15:0] a;
        output [7:0] d;
        begin
            send_hdr(C_READ, a, 16'd1);
            send_csum;
            get_reply(d);
            get_reply(rxcsum);
            checks = checks + 1;
            if (rxcsum !== d) begin
                errors = errors + 1;
                $display("FAIL: read of %04h returned %02h with checksum %02h",
                         a, d, rxcsum);
            end
        end
    endtask

    task chk_read;
        input [511:0] name;
        input [15:0] a;
        input [7:0] exp;
        begin
            bus_read(a, got8);
            chk(name, {24'd0, got8}, {24'd0, exp});
        end
    endtask

    // Deliberately unchecked: after the divider has been changed out
    // from under a frame the receive FIFO holds whatever the loader made
    // of the garbled bytes, and the tests that follow need it empty.
    task drain_rxfifo;
        integer k;
        begin
            k = 0;
            bus_read(16'hFE70, got8);
            while (got8[0] && k < 64) begin
                bus_read(16'hFE71, rxbyte);
                bus_read(16'hFE70, got8);
                k = k + 1;
            end
            send_hdr(C_WRITE, 16'hFE70, 16'd1);
            put(8'h04);                          // acknowledge any overrun
            send_csum;
            get_reply(rxbyte);
        end
    endtask

    // ------------------------------------------------ under the I/O page
    //
    // The bus cannot reach the RAM below $FE00-$FEFF, which is exactly
    // what is being tested, so the only way to put a distinguishable
    // byte there is to deposit it into the SPRAM arrays.

    function [7:0] ram_byte;
        input [15:0] a;
        reg [15:0] w;
        begin
            w = a[15] ? u_soc.u_mem.u_ram.u_hi.mem[a[14:1]]
                      : u_soc.u_mem.u_ram.u_lo.mem[a[14:1]];
            ram_byte = a[0] ? w[15:8] : w[7:0];
        end
    endfunction

    task ram_poke;
        input [15:0] a;
        input [7:0] d;
        begin
            w16 = a[15] ? u_soc.u_mem.u_ram.u_hi.mem[a[14:1]]
                        : u_soc.u_mem.u_ram.u_lo.mem[a[14:1]];
            if (a[0]) w16[15:8] = d;
            else      w16[7:0]  = d;
            if (a[15]) u_soc.u_mem.u_ram.u_hi.mem[a[14:1]] = w16;
            else       u_soc.u_mem.u_ram.u_lo.mem[a[14:1]] = w16;
        end
    endtask

    // ------------------------------------------------------- the boot ROM

    function [7:0] rom_at;
        input [15:0] a;
        begin rom_at = a[7:0] ^ a[15:8] ^ 8'h5A; end
    endfunction

    // A two-byte spin at $F000 and a reset vector pointing at it, so the
    // CPU is genuinely executing for the whole run without ever touching
    // RAM or the I/O page of its own accord.
    task fill_rom;
        integer k;
        begin
            for (k = 0; k < 4096; k = k + 1)
                u_soc.u_mem.u_rom.rom[k] = rom_at(16'hF000 + k[15:0]);
            u_soc.u_mem.u_rom.rom[12'h000] = 8'h70;      // BRA -2
            u_soc.u_mem.u_rom.rom[12'h001] = 8'hFE;
            u_soc.u_mem.u_rom.rom[12'hFF8] = 8'h00;      // RESET = $F000
            u_soc.u_mem.u_rom.rom[12'hFF9] = 8'hF0;
        end
    endtask

    // ------------------------------------------------- loading programs

    task load_prog;
        input [1023:0] fname;
        integer k;
        begin
            for (k = 0; k < 256; k = k + 1) prog[k] = 8'hxx;
            $readmemh(fname, prog);
            prog_n = 0;
            while (prog_n < 256 && prog[prog_n] !== 8'hxx)
                prog_n = prog_n + 1;
            if (prog_n == 0) begin
                errors = errors + 1;
                $display("FAIL: %0s held no bytes", fname);
            end
        end
    endtask

    // HALT, WRITE the image at $0400, GO there. GO sets BOOTRAM, writes
    // the reset vector into RAM and pulses CPU reset, so the program
    // starts with the boot ROM out of the map — the loader's whole
    // reason to exist, exercised for real every time this is called.
    //
    // The HALT is not decoration. The loader releases the bus between
    // frames, so without it the CPU resumes into whatever half of the
    // new program has landed so far and runs it. That is exactly what
    // happened the first time this loaded over a running program, and
    // it is why the sequence a host sends is HALT, WRITE, GO — see
    // docs/07-loader.md section 3.
    task load_and_go;
        input [1023:0] fname;
        integer k;
        begin
            load_prog(fname);
            send_cmd(C_HALT, 16'd0);
            expect_reply("HALT before loading", ACK);
            send_hdr(C_WRITE, 16'h0400, prog_n[15:0]);
            for (k = 0; k < prog_n; k = k + 1) put(prog[k]);
            send_csum;
            expect_reply("program loaded", ACK);
            send_cmd(C_GO, 16'h0400);
            expect_reply("GO", ACK);
        end
    endtask

    // ==================================================================
    // The run
    // ==================================================================

    initial begin
        errors = 0;
        checks = 0;
        ping_seen = 0;
        verbose = $test$plusargs("verbose");
        bitclk = DIV0 + 1;

        if (!$value$plusargs("led=%s", ledf))   ledf  = "prog_led.hex";
        if (!$value$plusargs("echo=%s", echof)) echof = "prog_echo.hex";
        if (!$value$plusargs("talk=%s", talkf)) talkf = "prog_talk.hex";
        if (!$value$plusargs("tx2=%s",  tx2f))  tx2f  = "prog_tx2.hex";

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_soc_tb);
        end

        fill_rom;
        // Distinguishable bytes in the RAM immediately below and above
        // the I/O page, deposited before anything runs so that every
        // check from here on can tell a ROM answer from a RAM one.
        ram_poke(16'hFDFF, 8'h6C);
        ram_poke(16'hFF00, 8'hC6);
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (8) @(posedge clk);

        // ---------------------------------------------------------- 1
        // Park the CPU on the loader's bus grant. Everything in this
        // section is the host talking to a machine with nothing else
        // moving, which is how a bring-up actually starts.

        send_cmd(C_HALT, 16'd0);
        expect_reply("HALT", ACK);
        chk("loader owns the bus", {31'd0, u_soc.busak}, 32'd1);

        // ---------------------------------------------------------- 2
        // The registers that exist.

        chk_read("SYSSTAT is the build id",    16'hFE02, BUILD);
        chk_read("SYSCTRL: ROMEN after reset", 16'hFE00, 8'h01);

        bus_write("LED := $05", 16'hFE03, 8'h05);
        chk("led pins follow the register", {29'd0, led}, 32'd5);
        chk_read("LED reads back",             16'hFE03, 8'h05);

        bus_write("LED := $02", 16'hFE03, 8'h02);
        chk("led pins changed", {29'd0, led}, 32'd2);
        chk_read("LED reads back again",       16'hFE03, 8'h02);

        // Every register on the page has a write strobe of its own, and
        // a write to one must not be a write to the next. The overlay is
        // the visible end of SYSCTRL, and $02 has bit 0 clear — so a LED
        // write that also landed on SYSCTRL would drop the boot ROM out
        // of the map right here.
        chk_read("the LED write left ROMEN alone", 16'hFDFF,
                 rom_at(16'hFDFF));

        chk_read("LDR_CTRL",  16'hFE80, 8'h11);   // BOOTRAM=0, HALT=1, en=1
        chk_read("LDR_STAT",  16'hFE81, 8'h05);   // owns the bus, seen a frame

        chk_read("UART_DIV_L is the parameter", 16'hFE72, DIV0[7:0]);
        chk_read("UART_DIV_H is the parameter", 16'hFE73, DIV0[15:8]);
        chk_read("UART_STAT: idle",             16'hFE70, 8'h02);

        // ---------------------------------------------------------- 3
        // The registers that do not. An unlisted address reads $FF and
        // swallows a write; a bus that answered $00 would look like a
        // register holding zero, which is the wrong kind of plausible.

        // $FE0C and $FE3F are chosen because nothing claims them and
        // nothing is scheduled to: $FE3F is the byte below the sprite
        // and blitter ports, inside the video block's neighbourhood but
        // outside its decode, which is where a decode one nibble too
        // wide would show.
        chk_read("CPUDIV is unimplemented",     16'hFE01, 8'hFF);
        chk_read("an unused address",           16'hFE0C, 8'hFF);
        chk_read("below the sprite ports",      16'hFE3F, 8'hFF);
        bus_write("write to an unused address", 16'hFE0C, 8'hA5);
        chk_read("...and it is still $FF",      16'hFE0C, 8'hFF);
        chk_read("...and nothing near it moved", 16'hFE03, 8'h02);

        // ---- the video page, $FE10-$FE3F
        //
        // The registers themselves are cool8_video_tb's; what is only
        // testable here is that the SoC's decode reaches them and that
        // the VRAM data port's alias claims the top quarter of the page.
        chk_read("VID_MODE out of reset",       16'hFE10, 8'h00);
        bus_write("VID_MODE := mode 4, on",     16'hFE10, 8'h84);
        chk_read("...reads back",               16'hFE10, 8'h84);
        // Writing a preset loads three registers software never wrote.
        chk_read("...and loaded VID_CTRL",      16'hFE11, 8'h3A);
        chk_read("...and VID_STRIDE low",       16'hFE14, 8'hA0);
        chk_read("...and VID_STRIDE high",      16'hFE15, 8'h00);
        bus_write("VID_BORDER := $5C",          16'hFE1A, 8'h5C);
        chk_read("...reads back",               16'hFE1A, 8'h5C);
        bus_write("VRAM_ADDR := $1234 low",     16'hFE26, 8'h34);
        bus_write("VRAM_ADDR := $1234 high",    16'hFE27, 8'h12);
        chk_read("VRAM_ADDR_L reads back",      16'hFE26, 8'h34);
        chk_read("VRAM_ADDR_H reads back",      16'hFE27, 8'h12);
        bus_write("VRAM_DATA := $9E",           16'hFE29, 8'h9E);
        chk_read("...the address advanced",     16'hFE26, 8'h35);
        bus_write("VRAM_DATA := $7D",           16'hFE29, 8'h7D);
        // The alias: every address in $FEC0-$FEFF is the same
        // auto-incrementing data port, which is what lets one loader
        // READ frame walk 64 consecutive bytes of VRAM instead of
        // re-reading one register 64 times.
        bus_write("VRAM_ADDR back to $1234",    16'hFE26, 8'h34);
        bus_write("...high half",               16'hFE27, 8'h12);
        chk_read("$FEC0 is the data port",      16'hFEC0, 8'h9E);
        chk_read("...and $FEFF is the same one", 16'hFEFF, 8'h7D);

        // ---------------------------------------------------------- 4
        // The page wins. There is RAM under every one of these
        // addresses and it must never be what answers.

        ram_poke(16'hFE00, 8'h11);
        ram_poke(16'hFE03, 8'h22);
        ram_poke(16'hFE0C, 8'h33);
        ram_poke(16'hFE3F, 8'h44);
        chk_read("SYSCTRL, not the RAM under it", 16'hFE00, 8'h01);
        chk_read("LED, not the RAM under it",     16'hFE03, 8'h02);
        chk_read("unused, not the RAM under it",  16'hFE0C, 8'hFF);
        chk_read("$FE3F, not the RAM under it",   16'hFE3F, 8'hFF);

        // ...and a write to the page must not reach the RAM either.
        bus_write("LED := $07", 16'hFE03, 8'h07);
        chk("the RAM under LED is untouched",
            {24'd0, ram_byte(16'hFE03)}, 32'h22);
        chk("led pins", {29'd0, led}, 32'd7);

        // The page is exactly 256 bytes wide. Below it and above it,
        // with ROMEN still set, is boot ROM.
        chk_read("$FDFF is the ROM window", 16'hFDFF, rom_at(16'hFDFF));
        chk_read("$FF00 is the ROM window", 16'hFF00, rom_at(16'hFF00));
        bus_write("$00FF is RAM", 16'h00FF, 8'h3C);
        chk_read("...and reads back",       16'h00FF, 8'h3C);

        // The other direction, which is the one that would be found
        // late: a write to RAM whose low byte happens to alias a live
        // register. Every program load does this — $0400 aliases
        // SYSCTRL and $0403 aliases LED — so a decode that forgot to
        // qualify on the high byte would corrupt the machine every time
        // software arrived, and would look like a loader fault.
        bus_write("$1200 is RAM, not SYSCTRL", 16'h1200, 8'h00);
        bus_write("$1203 is RAM, not LED",     16'h1203, 8'h05);
        bus_write("$1272 is RAM, not UART_DIV", 16'h1272, 8'hFF);
        bus_write("$1270 is RAM, not UART_STAT", 16'h1270, 8'h04);
        chk("led pins did not move", {29'd0, led}, 32'd7);
        chk_read("LED did not move",      16'hFE03, 8'h07);
        chk_read("SYSCTRL did not move",  16'hFE00, 8'h01);
        chk_read("UART_DIV_L did not move", 16'hFE72, DIV0[7:0]);
        chk_read("$1203 is what was written", 16'h1203, 8'h05);

        // ---------------------------------------------------------- 5
        // SYSCTRL really drives the overlay, through the decode rather
        // than through cool8_mem's own port.

        bus_write("ROMEN := 0", 16'hFE00, 8'h00);
        chk_read("SYSCTRL reads 0",        16'hFE00, 8'h00);
        chk_read("$FDFF is RAM now",       16'hFDFF, 8'h6C);
        chk_read("$FF00 is RAM now",       16'hFF00, 8'hC6);
        bus_write("ROMEN := 1", 16'hFE00, 8'h01);
        chk_read("$FDFF is the ROM again", 16'hFDFF, rom_at(16'hFDFF));

        // ---------------------------------------------------------- 6
        // The receive path: bytes the sniffer forwards land in the FIFO
        // and come back out of UART_DATA in order.

        chk_read("UART_STAT: nothing received", 16'hFE70, 8'h02);
        send_byte(8'h41);
        send_byte(8'h42);
        send_byte(8'h43);
        repeat (4 * bitclk) @(posedge clk);
        chk_read("UART_STAT: data available", 16'hFE70, 8'h03);
        chk_read("first byte",  16'hFE71, 8'h41);
        chk_read("second byte", 16'hFE71, 8'h42);
        chk_read("third byte",  16'hFE71, 8'h43);
        chk_read("UART_STAT: drained", 16'hFE70, 8'h02);

        // Sixteen bytes is the whole FIFO and must fit exactly.
        for (i = 0; i < 16; i = i + 1) send_byte(8'hB0 + i[7:0]);
        repeat (4 * bitclk) @(posedge clk);
        chk_read("UART_STAT: full but no overrun", 16'hFE70, 8'h03);
        for (i = 0; i < 16; i = i + 1)
            chk_read("in order", 16'hFE71, 8'hB0 + i[7:0]);
        chk_read("UART_STAT: drained again", 16'hFE70, 8'h02);

        // ---------------------------------------------------------- 7
        // Eighteen do not. The overflow is reported and it is the tail
        // that is lost, not the head — a FIFO that drops its oldest byte
        // turns a diagnosable overrun into scrambled input.

        for (i = 0; i < 18; i = i + 1) send_byte(8'h30 + i[7:0]);
        repeat (4 * bitclk) @(posedge clk);
        chk_read("UART_STAT: overrun", 16'hFE70, 8'h07);
        for (i = 0; i < 16; i = i + 1)
            chk_read("the head survived", 16'hFE71, 8'h30 + i[7:0]);
        chk_read("UART_STAT: empty, still flagged", 16'hFE70, 8'h06);
        bus_write("acknowledge the overrun", 16'hFE70, 8'h04);
        chk_read("UART_STAT: clear", 16'hFE70, 8'h02);

        // Reading an empty FIFO returns a stale byte, which is fine.
        // What must not happen is the read pointer moving.
        bus_read(16'hFE71, got8);
        chk_read("UART_STAT: still empty", 16'hFE70, 8'h02);

        // ---------------------------------------------------------- 8
        // The transmit path, and the share. The byte written to
        // UART_DATA is queued while the loader is still mid-frame, so it
        // goes out ahead of the loader's own ACK — that is the arbiter
        // working, not an accident of ordering.

        send_hdr(C_WRITE, 16'hFE71, 16'd1);
        put(8'h96);
        send_csum;
        expect_reply("the CPU's byte goes first", 8'h96);
        expect_reply("then the loader's ACK",     ACK);
        expect_quiet("and nothing else");

        // ---------------------------------------------------------- 9
        // The divider is a register and it really drives the UART.
        // Changing it desynchronises the byte after it by construction:
        // the rate changes the moment the register lands and the host
        // has not switched yet. A host tool changes rate and re-syncs on
        // the next start bit, and so does this — whatever the loader
        // made of the trailing checksum is drained and not checked.

        send_hdr(C_WRITE, 16'hFE72, 16'd1);
        put(8'h1F);
        send_csum;
        bitclk = 32;
        drain;
        send_cmd(C_PING, 16'd0);
        expect_reply("PING at the new rate", VERSION);
        chk_read("UART_DIV_L took", 16'hFE72, 8'h1F);

        send_hdr(C_WRITE, 16'hFE73, 16'd1);
        put(8'h01);
        send_csum;
        bitclk = 288;                            // div = $011F
        drain;
        send_cmd(C_PING, 16'd0);
        expect_reply("PING at the slow rate", VERSION);
        chk_read("UART_DIV_H took", 16'hFE73, 8'h01);

        send_hdr(C_WRITE, 16'hFE73, 16'd1);
        put(8'h00);
        send_csum;
        bitclk = 32;
        drain;
        send_hdr(C_WRITE, 16'hFE72, 16'd1);
        put(DIV0[7:0]);
        send_csum;
        bitclk = DIV0 + 1;
        drain;
        send_cmd(C_PING, 16'd0);
        expect_reply("PING back at the original rate", VERSION);

        drain_rxfifo;

        // --------------------------------------------------------- 10
        // Now the CPU. Everything above reached the page from the
        // loader's port; this reaches it from the core's, which is a
        // different master, a different address source, and the one that
        // has to live with the wait state.

        bus_write("LED := $00 before the program runs", 16'hFE03, 8'h00);
        chk("led pins cleared", {29'd0, led}, 32'd0);

        load_and_go(ledf);
        n = 0;
        while (!o_halted && n < 20000) begin
            @(posedge clk);
            n = n + 1;
        end
        chk("the program halted", {31'd0, o_halted}, 32'd1);
        chk("the CPU lit the LED", {29'd0, led}, 32'd6);
        chk_read("...and the register agrees", 16'hFE03, 8'h06);

        // --------------------------------------------------------- 11
        // A program that talks: poll UART_STAT, read UART_DATA, write it
        // back. Every byte makes the whole round trip — sniffer, FIFO,
        // the CPU's own load and store through the I/O page, the shared
        // transmitter, the wire.

        load_and_go(echof);
        repeat (400) @(posedge clk);
        send_byte(8'h68);
        expect_reply("echo of $68", 8'h68);
        send_byte(8'h69);
        expect_reply("echo of $69", 8'h69);
        send_byte(8'hC8);                        // a lone magic byte is data
        send_byte(8'h5A);
        expect_reply("echo of a lone $C8",       8'hC8);
        expect_reply("echo of what followed it", 8'h5A);
        expect_quiet("the echo said nothing else");

        // --------------------------------------------------------- 11b
        // The same program, fed a *stream* rather than a byte at a
        // time -- and that difference is the whole test.
        //
        // Sending one byte and waiting for it leaves the receive FIFO
        // empty every time the CPU reads it, which is the one
        // arrangement in which the fault below cannot happen. A byte
        // arriving in the very cycle a read of UART_DATA launched used
        // to suppress the pop: the read returned the right byte, the
        // pointer did not move, and the next read handed the same byte
        // out again. Software could not defend against it -- its poll
        // of UART_STAT had already said ready. It needed a push during
        // a read, so only a continuous stream produced it, and on the
        // bench it was an occasional doubled character at 115200.
        //
        // A stream, rather than a byte at a time: the FIFO holds
        // several at once and the program reads while more arrive.
        // Nothing here is timed against the receiver -- the one-cycle
        // coincidence that duplicates a byte is built deliberately in
        // 11c below, because a stream this short will not find it --
        // but a stream that comes back in order is worth its own
        // check, and the gaps keep the arrivals off a single cadence.
        for (i = 0; i < 32; i = i + 1) begin
            repeat (i) @(posedge clk);
            send_byte(8'hE0 + i[7:0]);
        end
        for (i = 0; i < 32; i = i + 1)
            expect_reply("a streamed byte comes back once, in order",
                         8'hE0 + i[7:0]);
        expect_quiet("and the stream produced no extra byte");

        // The one-cycle coincidence that duplicates a byte is NOT
        // reachable from here, and it is worth saying why rather than
        // leaving the next person to try it. The host has one wire:
        // `bus_read` is a loader frame over the same line `send_byte`
        // uses, so a read cannot be issued *while* a byte is arriving
        // -- forking the two collides on host_tx and corrupts the
        // protocol rather than racing the FIFO. Driving it from a
        // program instead puts the read where the program's own loop
        // puts it, which is what makes the odds one in a byte-time.
        //
        // sim/test_monitor.py is the gate for that fault: it types
        // thousands of characters through a consumer slow enough to
        // keep the FIFO non-empty, which is exactly the condition, and
        // it caught the duplicate that this file could not.

        // --------------------------------------------------------- 12
        // A program that writes UART_DATA without looking at whether
        // there is room. The byte already accepted must survive and the
        // late one must be the one that is lost — see sim/asm/soc_tx2.asm.

        load_and_go(tx2f);
        expect_reply("the first byte",  8'hA1);
        expect_reply("the second byte", 8'hA2);
        expect_quiet("the third had nowhere to go");

        // --------------------------------------------------------- 13
        // The share, the hard way round: a program transmitting as fast
        // as the wire allows while a frame arrives. The loader's reply
        // must get out, and not one of the program's bytes may be lost
        // or corrupted on the way past it.

        load_and_go(talkf);
        send_cmd(C_PING, 16'd0);
        want_next = 8'h80;
        for (i = 0; i < 14; i = i + 1) begin
            get_reply(rxbyte);
            if (rxbyte == VERSION) ping_seen = ping_seen + 1;
            else begin
                chk("the program's bytes are unbroken",
                    {24'd0, rxbyte}, want_next);
                want_next = 8'h80 + ((want_next - 8'h80 + 1) & 8'h7F);
            end
        end
        chk("the PING was answered exactly once", ping_seen, 32'd1);

        // --------------------------------------------------------- 14
        // RESET puts it back: BOOTRAM cleared, so ROMEN reloads to 1 and
        // the machine is looking at the boot ROM again.

        send_cmd(C_HALT, 16'd0);
        expect_reply_amid_stream("HALT stopped the program", ACK);
        drain;
        send_cmd(C_RESET, 16'd0);
        expect_reply("RESET", ACK);
        chk_read("SYSCTRL: ROMEN is back",        16'hFE00, 8'h01);
        chk_read("$FDFF is the ROM window again", 16'hFDFF, rom_at(16'hFDFF));

        $display("\n  %0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("\nPASS");
        else             $display("\nFAIL");
        $finish;
    end

    // A run that wedges must say so rather than hanging the suite.
    initial begin
        #40000000;
        $display("FAIL: timed out");
        $display("\nFAIL");
        $finish;
    end

endmodule

`default_nettype wire
