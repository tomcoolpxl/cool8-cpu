// cool8_soc — the machine: core, memory, I/O page, video, UART, loader,
// keyboard and the flash.
//
// Everything above this is pins and a clock (cool8_top.v); everything
// below it has been simulated on its own. This block is the wiring and
// the one thing that cannot be tested anywhere else — the I/O page.
//
// ## The I/O page always wins
//
// $FE00-$FEFF is decoded here, on the *bus*, ahead of cool8_mem. Not
// inside it, and not per-peripheral: one decode, one place to read, and
// no possibility of two blocks both answering. The rule from
// docs/04-system.md section 2 is absolute — the page is decoded whatever
// else claims the address, so the SPRAM underneath it and the boot ROM
// window over it are both unreachable there. 256 bytes of RAM is the
// price and it buys a memory map with no exceptions in it.
//
// Because the decode is on the bus rather than on the CPU's port, the
// loader reaches the I/O page too. That is deliberate: a WRITE frame to
// $FE03 lights the LED with no CPU, no program and no working boot ROM,
// which is the first thing worth doing to a board that has just come up.
// The other end of it is that a WRITE to $FE80 is the loader writing its
// own control register mid-frame; nothing stops that and nothing should
// pretend to.
//
// An I/O read costs the same one wait state a RAM read does, and it is
// not an accident of laziness. Answering in the address cycle means the
// read data is a combinational function of the address — and the core's
// address is a combinational function of the byte it is fetching, so the
// two close a loop through the bus that synthesis reports and that no
// timing analysis can cross. Registering the answer breaks it, and it
// puts every access in the machine on one shape: launch, then data.
// So all three memories — RAM, boot ROM and the I/O page — are read on
// every launch and the answer is picked afterwards, and `ready` has one
// source rather than three that must agree.
//
// ## One UART, two talkers
//
// The transmitter is shared between the loader's replies and the
// program's own output, and a shared transmitter is where bytes get
// lost. The loader has priority, absolutely: the CPU's byte waits in a
// one-deep holding register and only goes out on a cycle where the wire
// is idle, the loader is not starting a byte, and the loader is not in a
// state it will want the wire from. Since the loader only ever commits
// one cycle after seeing the wire idle, and the CPU is held off for
// every cycle it could commit on, neither can be interrupted and neither
// loses a byte.
//
// Priority has to run this way round. The first arrangement tried gave
// the CPU the wire whenever it had a byte queued and showed the loader a
// busy line instead — and a program transmitting flat out then starved
// the loader completely, because it refills the holding register in
// about fifteen clocks and a byte takes a thousand. A host that cannot
// interrupt a running program is a host that has to reach for the reset
// button, which is the one thing the loader exists to avoid.
//
// The receiver is not shared: every byte goes into the loader, which
// forwards the ones that are not part of a frame. That is what lets a
// running program use the serial port and still be interrupted and
// reloaded — docs/07-loader.md section 1.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_soc #(
    parameter ROM_FILE  = "boot.hex",
    parameter ROM_INIT  = 1,
    parameter FONT_FILE = "font.hex",
    parameter FONT_INIT = 1,
    // div = round(f_clk / baud) - 1. At 8.375 MHz, 115200 baud is 72,
    // which lands on 114726 — 0.41 % out, well inside what a UART
    // tolerates. The clock is cool8_pll's business and D32's.
    parameter [15:0] UART_DIV = 16'd72,
    // What $FE02 SYSSTAT reads back. The point of it is to be able to
    // ask a board which bitstream it is actually running, so bump it
    // when that answer would be useful.
    parameter [7:0]  BUILD_ID = 8'h05,
    // Receive FIFO depth, log2. The loader can forward two bytes in
    // consecutive cycles, so one entry is not enough on its own.
    parameter RX_ABITS = 4
) (
    input  wire        clk,
    input  wire        rst_n,          // board reset, active low

    // The raster's clock, 25.125 MHz, and its own reset. Decoupled from
    // everything above by D26; the join is inside two block RAMs.
    input  wire        pclk,
    input  wire        prst_n,

    input  wire        uart_rx,
    output wire        uart_tx,

    // PS/2, split into level and enable so the open drain lives on the
    // pad in cool8_top: `*_oe` high pulls the line down.
    input  wire        ps2_clk_i,
    input  wire        ps2_dat_i,
    output wire        ps2_clk_oe,
    output wire        ps2_dat_oe,

    // The configuration flash, released to user logic after CDONE
    output wire        spi_cs_n,
    output wire        spi_sck,
    output wire        spi_mosi,
    input  wire        spi_miso,

    output wire [11:0] rgb,            // 4 bits a channel, straight to pins
    output wire        hsync_n,
    output wire        vsync_n,

    // One pin, 1-bit sigma-delta. An RC low-pass on the board is the DAC.
    output wire        audio,

    output wire [2:0]  led,            // R, G, B — active high here

    // Synchronised and debounced outside; there are no sources yet.
    input  wire        irq,
    input  wire        nmi,

    output wire        o_halted
);

    localparam RX_DEPTH = 1 << RX_ABITS;

    localparam [7:0] A_SYSCTRL  = 8'h00,
                     A_SYSSTAT  = 8'h02,
                     A_LED      = 8'h03,
                     A_UARTSTAT = 8'h70,
                     A_UARTDATA = 8'h71,
                     A_UARTDIVL = 8'h72,
                     A_UARTDIVH = 8'h73,
                     A_LDRCTRL  = 8'h80,
                     A_LDRSTAT  = 8'h81;

    // ---------------------------------------------------------- state

    reg  [2:0]  led_r;
    reg  [15:0] uart_div;

    // A block RAM, and it was flip-flops until M6.
    //
    // The original reasoning was sound and its premises have both
    // reversed. Refusing the inference cost a measured **109 LUT4 and
    // 123 flip-flops** and saved one EBR, which was the right way round
    // when the font was about to claim eight blocks and the design sat
    // at 37 % of the logic. After M5 the part is 92 % full of logic with
    // three block RAMs spare, and the boot ROM is holding 174 bytes in
    // eight of them. The scarce resource is the other one now.
    //
    // Inference is still not what happens here. Left alone yosys would
    // retime the read capture into the block's own output register — a
    // legitimate transform that no test in this project reaches. So the
    // read register is written out, and the contract that makes a
    // block RAM's one-cycle read invisible is stated instead of assumed:
    // **`rx_head` is correct whenever `rx_avail` is set.** Anything that
    // can move either pointer raises `rx_settle` for the cycle after,
    // and `rx_avail` is suppressed while it is high. A push into a
    // non-empty FIFO does not move `rx_rd`, so the re-read returns the
    // same byte; a push into an empty one does, and nothing was
    // available to read anyway. cool8_ps2 carries the same arrangement.
    (* ram_style = "block" *)
    reg  [7:0]  rxq [0:RX_DEPTH-1];
    reg  [RX_ABITS:0] rx_wr, rx_rd;    // one extra bit tells full from empty
    reg  [7:0]  rx_head;
    reg         rx_settle;
    reg         rx_over;

    reg  [7:0]  cpu_tx_data;
    reg         cpu_tx_pend;

    reg  [7:0]  io_rdata;            // the decode, combinational
    reg  [7:0]  io_rdata_r;          // captured on the launch cycle
    reg         io_r;                // ...and so was "the I/O page answered"

    // ------------------------------------------------------ the pieces

    wire [15:0] cpu_addr, ldr_addr;
    wire [7:0]  cpu_wdata, ldr_wdata;
    wire        cpu_read, cpu_write, ldr_read, ldr_write;
    wire        busrq, busak;

    wire [7:0]  mem_rdata;
    wire        mem_ready, mem_launch;
    wire [7:0]  sysctrl_rdata;

    wire [7:0]  rx_data;
    wire        rx_valid;
    wire [7:0]  ldr_tx_data;
    wire        ldr_tx_start, ldr_tx_want;
    wire        tx_busy;
    wire [7:0]  fwd_data;
    wire        fwd_valid;

    wire        ldr_cpu_rst_n, bootram;
    wire [7:0]  ldr_ctrl_rdata, ldr_stat_rdata;

    // ------------------------------------------------------- the bus
    //
    // One master at a time, chosen by the core's own grant. The core
    // drives nothing while busak is high — cool8_loader_tb checks that
    // directly rather than trusting the mux to hide it.

    wire [15:0] bus_addr  = busak ? ldr_addr  : cpu_addr;
    wire [7:0]  bus_wdata = busak ? ldr_wdata : cpu_wdata;
    wire        bus_read  = busak ? ldr_read  : cpu_read;
    wire        bus_write = busak ? ldr_write : cpu_write;

    wire        io_sel = (bus_addr[15:8] == 8'hFE);
    wire [7:0]  io_a   = bus_addr[7:0];

    // ------------------------------------------- the video's memory port
    //
    // Text maps live in main RAM (D28), so the display fetch has to take
    // cycles from the CPU. It takes them by stealing the *launch* slot:
    // when it wants an access and the memory is not already answering
    // one, the memory sees its address instead and the master is held
    // off with ready low. A read is two cycles here as it is everywhere,
    // so the video gets one access every two cycles and never more.
    //
    // **Nothing the core drives takes part in that decision.**
    // `vid_ram_req` comes out of the fetch engine's state and `mem_pend`
    // is a flip-flop, so the grant is a function of registers alone. The
    // obvious version — let a master's write win, since a write is a
    // single cycle and never waits — put `bus_write` into it, and
    // `bus_write` comes combinationally off the byte the core is
    // fetching. That closes the arbiter into the machine's longest path
    // and costs about two megahertz. A write that loses simply waits a
    // cycle; the master is holding its address anyway.
    //
    // The cost is 5 % of main RAM in mode 0 (80 cells of two bytes, two
    // cycles each, per sixteen scanlines) and nothing at all in any other
    // mode, which is why this arbiter has no fairness logic in it.

    wire        vid_ram_req, vid_rvalid, vid_gnt;
    wire [15:0] vid_ram_addr;

    reg         mem_pend;              // the memory is in a read's data cycle
    reg         vid_own;               // ...and that read is the video's

    wire        vid_start = vid_ram_req & ~mem_pend;
    wire        vid_dcyc  = mem_pend & vid_own;
    wire        vid_busy  = vid_start | vid_dcyc;

    wire [15:0] m_addr  = vid_start ? vid_ram_addr : bus_addr;
    wire        m_read  = vid_start ? 1'b1 : bus_read;
    wire        m_write = vid_busy  ? 1'b0 : (bus_write & ~io_sel);

    assign vid_gnt    = vid_start & mem_launch;
    assign vid_rvalid = vid_dcyc;

    // A read's side effect must happen once. Three things can make the
    // memory launch more than once for a single access — a stolen cycle,
    // a video data cycle, and the SPRAM relaunching every other cycle
    // while the video port holds ready low — so "the access started" is
    // latched rather than taken from the launch each time. Without this
    // a stalled read of UART_DATA would pop the FIFO twice and the byte
    // in between would simply be gone.
    reg  io_rd_seen;
    reg  dp_r;                         // ...and it was a late-answering port
    reg  dpf_r;                        // ...specifically the flash's
    wire io_launch = io_sel & bus_read & mem_launch & ~vid_start;
    wire io_rd     = io_launch & ~io_rd_seen;

    wire        vid_sel, vid_dp_sel, vid_stall, vid_irq;
    wire [7:0]  vid_rdata, vid_dout;

    wire        ps2_sel, ps2_irq;
    wire [7:0]  ps2_rdata;

    wire        fls_sel, fls_dp_sel, fls_stall;
    wire [7:0]  fls_rdata, fls_dout;

    wire        snd_sel;

    // A write reaches the page exactly once, and the two signals below are
    // what makes that true rather than merely usual.
    //
    // `io_wreq` is what the master is *asking* for. It is suppressed on a
    // stolen cycle, because a write held across one would otherwise be
    // presented twice — a palette index advanced twice, a VRAM address
    // advanced twice.
    //
    // `io_we` is what the page may *act* on, and it is the same signal
    // qualified by everything else that can hold the transfer up. Without
    // that qualification the strobe stays high through a stall the page
    // itself asked for, and every side-effecting register on it fires
    // again. Nothing reachable does that today: the only block that stalls
    // a write is cool8_vport, and its own `~wr_pend` guard covers its own
    // register. That is coverage, not construction, and the audio engine
    // and the timer are both still to come.
    //
    // The two are separate because collapsing them closes a loop.
    // `vid_stall` carries cool8_vport's write-side stall, which is a
    // function of the write being offered; feeding the qualified signal
    // back in would make `io_we` depend on itself. So the port that
    // decides whether to stall sees `io_wreq`, and the ports that have
    // side effects see `io_we`.
    wire io_wreq   = io_sel & bus_write & ~vid_busy;
    wire io_we     = io_wreq & ~vid_stall & ~fls_stall;

    // Two registers on the page answer late rather than on the launch
    // cycle — VRAM_DATA and FLS_DATA — because neither byte is
    // necessarily there yet, which is the whole reason both blocks
    // stall. Everything else is a flip-flop and is captured exactly as
    // it always was.
    wire        dp_sel  = vid_dp_sel | fls_dp_sel;
    wire [7:0]  dp_dout = dpf_r ? fls_dout : vid_dout;

    wire [7:0]  bus_rdata = io_r ? (dp_r ? dp_dout : io_rdata_r)
                                 : mem_rdata;

    // `mem_ready` is not used here, and the difference is one logic
    // level on the machine's critical path. The memory's own ready is a
    // function of `m_read`, which carries `vid_start` in it; this is the
    // same expression with the video term already accounted for by
    // `vid_busy`, so it depends on `bus_read` directly and on `mem_pend`,
    // which is a flip-flop. Writes never wait on the memory at all.
    wire        ready_m   = ~(bus_read & ~mem_pend);
    wire        bus_ready = ~vid_busy & ~vid_stall & ~fls_stall &
                            (bus_write | ready_m);

    always @(posedge clk) begin
        if (!rst_n) begin
            io_r       <= 1'b0;
            dp_r       <= 1'b0;
            dpf_r      <= 1'b0;
            mem_pend   <= 1'b0;
            vid_own    <= 1'b0;
            io_rd_seen <= 1'b0;
        end else begin
            mem_pend <= mem_launch;
            if (mem_launch) vid_own <= vid_start;

            if (mem_launch & ~vid_start) begin
                io_r       <= io_sel;
                io_rdata_r <= io_rdata;
                dp_r       <= dp_sel;
                dpf_r      <= fls_dp_sel;
            end

            if (bus_ready)  io_rd_seen <= 1'b0;
            else if (io_rd) io_rd_seen <= 1'b1;
        end
    end

    wire        cpu_rst_n = rst_n & ldr_cpu_rst_n;

    // --------------------------------------------------- receive FIFO

    wire rx_avail = (rx_wr != rx_rd) & ~rx_settle;
    wire rx_full  = (rx_wr[RX_ABITS-1:0] == rx_rd[RX_ABITS-1:0]) &&
                    (rx_wr[RX_ABITS]     != rx_rd[RX_ABITS]);
    wire rx_pop   = io_rd & (io_a == A_UARTDATA) & rx_avail;
    wire rx_room  = ~rx_full | rx_pop;      // a pop this cycle frees a slot
    wire rx_push  = fwd_valid & rx_room;

    always @(posedge clk) begin
        if (!rst_n) begin
            rx_wr     <= {(RX_ABITS+1){1'b0}};
            rx_rd     <= {(RX_ABITS+1){1'b0}};
            rx_over   <= 1'b0;
            rx_head   <= 8'h00;
            rx_settle <= 1'b0;
        end else begin
            rx_head   <= rxq[rx_rd[RX_ABITS-1:0]];
            rx_settle <= rx_pop | rx_push;

            if (rx_pop) rx_rd <= rx_rd + 1'b1;
            // Write 1 to bit 2 of UART_STAT to acknowledge an overrun,
            // the same shape as VID_IRQ and TMR_STAT. Ordered before the
            // push so a byte lost in this very cycle is still reported.
            if (io_we && io_a == A_UARTSTAT && bus_wdata[2]) rx_over <= 1'b0;
            if (rx_push) begin
                rxq[rx_wr[RX_ABITS-1:0]] <= fwd_data;
                rx_wr <= rx_wr + 1'b1;
            end else if (fwd_valid) rx_over <= 1'b1;
        end
    end

    // ------------------------------------------------- transmit share

    wire cpu_tx_go = cpu_tx_pend & ~tx_busy & ~ldr_tx_start & ~ldr_tx_want;

    wire        uart_tx_start = ldr_tx_start | cpu_tx_go;
    wire [7:0]  uart_tx_data  = ldr_tx_start ? ldr_tx_data : cpu_tx_data;

    always @(posedge clk) begin
        if (!rst_n) begin
            cpu_tx_pend <= 1'b0;
            cpu_tx_data <= 8'h00;
        end else begin
            if (cpu_tx_go) cpu_tx_pend <= 1'b0;
            // Writing while the holding register is occupied loses the
            // byte, as it does on every UART: UART_STAT bit 1 is there
            // to be looked at first.
            if (io_we && io_a == A_UARTDATA && !cpu_tx_pend) begin
                cpu_tx_data <= bus_wdata;
                cpu_tx_pend <= 1'b1;
            end
        end
    end

    // ---------------------------------------------------- I/O registers

    always @(posedge clk) begin
        if (!rst_n) begin
            led_r    <= 3'b000;
            uart_div <= UART_DIV;
        end else if (io_we) begin
            case (io_a)
                A_LED:      led_r          <= bus_wdata[2:0];
                A_UARTDIVL: uart_div[7:0]  <= bus_wdata;
                A_UARTDIVH: uart_div[15:8] <= bus_wdata;
                default: ;
            endcase
        end
    end

    assign led = led_r;

    // Unlisted addresses read $FF and ignore writes, so a stray access
    // to the page reads as a floating bus would rather than as a
    // plausible zero. $FE01 CPUDIV is among them: D26 put the core on
    // the board's own clock and there is nothing yet for a divider to
    // divide.
    always @* begin
        if (vid_sel)      io_rdata = vid_rdata;
        else if (ps2_sel) io_rdata = ps2_rdata;
        else if (fls_sel) io_rdata = fls_rdata;
        else case (io_a)
            A_SYSCTRL:  io_rdata = sysctrl_rdata;
            A_SYSSTAT:  io_rdata = BUILD_ID;
            A_LED:      io_rdata = {5'b00000, led_r};
            A_UARTSTAT: io_rdata = {5'b00000, rx_over, ~cpu_tx_pend, rx_avail};
            A_UARTDATA: io_rdata = rx_head;
            A_UARTDIVL: io_rdata = uart_div[7:0];
            A_UARTDIVH: io_rdata = uart_div[15:8];
            A_LDRCTRL:  io_rdata = ldr_ctrl_rdata;
            A_LDRSTAT:  io_rdata = ldr_stat_rdata;
            default:    io_rdata = 8'hFF;
        endcase
    end

    // ------------------------------------------------------ instances

    cool8_core u_cpu (
        .clk(clk), .rst_n(cpu_rst_n),
        .mem_addr(cpu_addr), .mem_wdata(cpu_wdata), .mem_rdata(bus_rdata),
        .mem_read(cpu_read), .mem_write(cpu_write), .mem_ready(bus_ready),
        .irq(irq | vid_irq | ps2_irq), .nmi(nmi),
        .busrq(busrq), .busak(busak),
        .o_fetch(), .o_halted(o_halted), .o_iack(), .o_retire()
    );

    cool8_mem #(.ROM_FILE(ROM_FILE), .ROM_INIT(ROM_INIT)) u_mem (
        .clk(clk), .rst_n(rst_n), .cpu_rst_n(cpu_rst_n),
        // The address is the arbiter's, not the bus's: the display fetch
        // borrows this port. Reads go down unconditionally — the SPRAM is
        // what times the access and what defines the launch cycle, and
        // reading the shadowed byte underneath the I/O page has no side
        // effect. Writes are gated, because those do.
        .addr(m_addr), .wdata(bus_wdata),
        .read (m_read),
        .write(m_write),
        .rdata(mem_rdata), .ready(mem_ready), .o_launch(mem_launch),
        .bootram(bootram),
        .ctrl_we(io_we & (io_a == A_SYSCTRL)),
        .ctrl_wdata(bus_wdata),
        .ctrl_rdata(sysctrl_rdata)
    );

    cool8_uart u_uart (
        .clk(clk), .rst_n(rst_n),
        .div(uart_div),
        .rx_pin(uart_rx), .tx_pin(uart_tx),
        .rx_data(rx_data), .rx_valid(rx_valid),
        .tx_data(uart_tx_data), .tx_start(uart_tx_start), .tx_busy(tx_busy)
    );

    cool8_video #(.FONT_FILE(FONT_FILE), .FONT_INIT(FONT_INIT)) u_vid (
        .sclk(clk), .srst_n(rst_n),
        .pclk(pclk), .prst_n(prst_n),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wreq(io_wreq),
        .io_wdata(bus_wdata),
        .o_sel(vid_sel), .o_dp_sel(vid_dp_sel), .o_rdata(vid_rdata),
        .o_dout(vid_dout), .o_stall(vid_stall),
        .ram_req(vid_ram_req), .ram_addr(vid_ram_addr),
        .ram_gnt(vid_gnt), .ram_rvalid(vid_rvalid), .ram_rdata(mem_rdata),
        .rgb(rgb), .hsync_n(hsync_n), .vsync_n(vsync_n),
        .o_irq(vid_irq)
    );

    cool8_ps2 u_ps2 (
        .clk(clk), .rst_n(rst_n),
        .ps2_clk_i(ps2_clk_i), .ps2_dat_i(ps2_dat_i),
        .ps2_clk_oe(ps2_clk_oe), .ps2_dat_oe(ps2_dat_oe),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wdata(bus_wdata),
        .o_sel(ps2_sel), .o_rdata(ps2_rdata), .o_irq(ps2_irq)
    );

    cool8_flash u_fls (
        .clk(clk), .rst_n(rst_n),
        .spi_cs_n(spi_cs_n), .spi_sck(spi_sck),
        .spi_mosi(spi_mosi), .spi_miso(spi_miso),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wdata(bus_wdata),
        .o_sel(fls_sel), .o_dp_sel(fls_dp_sel), .o_rdata(fls_rdata),
        .o_dout(fls_dout), .o_stall(fls_stall)
    );

    cool8_snd u_snd (
        .clk(clk), .rst_n(rst_n),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wdata(bus_wdata),
        .o_sel(snd_sel),
        .o_pwm(audio)
    );

    cool8_loader u_ldr (
        .clk(clk), .rst_n(rst_n),
        .rx_data(rx_data), .rx_valid(rx_valid),
        .tx_data(ldr_tx_data), .tx_start(ldr_tx_start),
        .tx_want(ldr_tx_want), .tx_busy(tx_busy),
        .fwd_data(fwd_data), .fwd_valid(fwd_valid),
        .busrq(busrq), .busak(busak),
        .mem_addr(ldr_addr), .mem_wdata(ldr_wdata), .mem_rdata(bus_rdata),
        .mem_read(ldr_read), .mem_write(ldr_write), .mem_ready(bus_ready),
        .cpu_rst_n(ldr_cpu_rst_n), .bootram(bootram), .halt_req(),
        .ctrl_we(io_we & (io_a == A_LDRCTRL)),
        .ctrl_wdata(bus_wdata),
        .ctrl_rdata(ldr_ctrl_rdata), .stat_rdata(ldr_stat_rdata)
    );

endmodule

`default_nettype wire
