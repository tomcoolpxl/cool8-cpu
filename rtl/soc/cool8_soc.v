// cool8_soc — the machine: core, memory, I/O page, UART and loader.
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
    parameter ROM_FILE = "boot.hex",
    parameter ROM_INIT = 1,
    // div = round(f_clk / baud) - 1. At 12 MHz, 115200 baud is 103.
    parameter [15:0] UART_DIV = 16'd103,
    // What $FE02 SYSSTAT reads back. The point of it is to be able to
    // ask a board which bitstream it is actually running, so bump it
    // when that answer would be useful.
    parameter [7:0]  BUILD_ID = 8'h04,
    // Receive FIFO depth, log2. The loader can forward two bytes in
    // consecutive cycles, so one entry is not enough on its own.
    parameter RX_ABITS = 4
) (
    input  wire        clk,
    input  wire        rst_n,          // board reset, active low

    input  wire        uart_rx,
    output wire        uart_tx,

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

    // Flip-flops, not a block RAM. Left alone yosys puts these 128 bits
    // into a 4 Kbit EBR, retiming the read capture below into the
    // block's own output register. That is a legitimate inference and it
    // costs 89 LUT4 and 123 flip-flops to refuse — but it would put the
    // read data path inside a transform that only a netlist-level run
    // could confirm, and the one that exists (sim/test_boot.py, for the
    // ROM image) does not reach in here. Given the choice between
    // verifying an inference and not making one, on 3 % occupancy of a
    // block the font wants at M5, not making it is the cheaper answer.
    (* ram_style = "logic" *)
    reg  [7:0]  rxq [0:RX_DEPTH-1];
    reg  [RX_ABITS:0] rx_wr, rx_rd;    // one extra bit tells full from empty
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
    // A read's side effect must happen once, and bus_read is high for
    // both cycles of a read — so it is qualified by the launch, which is
    // the memory's own definition of when an access starts. A write
    // takes no wait state anywhere, so bus_write is already one cycle.
    wire        io_rd  = io_sel & bus_read & mem_launch;
    wire        io_we  = io_sel & bus_write;

    wire [7:0]  bus_rdata = io_r ? io_rdata_r : mem_rdata;
    wire        bus_ready = mem_ready;

    always @(posedge clk) begin
        if (!rst_n) io_r <= 1'b0;
        else if (mem_launch) begin
            io_r       <= io_sel;
            io_rdata_r <= io_rdata;
        end
    end

    wire        cpu_rst_n = rst_n & ldr_cpu_rst_n;

    // --------------------------------------------------- receive FIFO

    wire rx_avail = (rx_wr != rx_rd);
    wire rx_full  = (rx_wr[RX_ABITS-1:0] == rx_rd[RX_ABITS-1:0]) &&
                    (rx_wr[RX_ABITS]     != rx_rd[RX_ABITS]);
    wire rx_pop   = io_rd & (io_a == A_UARTDATA) & rx_avail;
    wire rx_room  = ~rx_full | rx_pop;      // a pop this cycle frees a slot
    wire [7:0] rx_head = rxq[rx_rd[RX_ABITS-1:0]];

    always @(posedge clk) begin
        if (!rst_n) begin
            rx_wr   <= {(RX_ABITS+1){1'b0}};
            rx_rd   <= {(RX_ABITS+1){1'b0}};
            rx_over <= 1'b0;
        end else begin
            if (rx_pop) rx_rd <= rx_rd + 1'b1;
            // Write 1 to bit 2 of UART_STAT to acknowledge an overrun,
            // the same shape as VID_IRQ and TMR_STAT. Ordered before the
            // push so a byte lost in this very cycle is still reported.
            if (io_we && io_a == A_UARTSTAT && bus_wdata[2]) rx_over <= 1'b0;
            if (fwd_valid) begin
                if (rx_room) begin
                    rxq[rx_wr[RX_ABITS-1:0]] <= fwd_data;
                    rx_wr <= rx_wr + 1'b1;
                end else rx_over <= 1'b1;
            end
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
    // the raw 12 MHz clock and there is nothing yet for a divider to
    // divide.
    always @* begin
        case (io_a)
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
        .irq(irq), .nmi(nmi),
        .busrq(busrq), .busak(busak),
        .o_fetch(), .o_halted(o_halted), .o_iack(), .o_retire()
    );

    cool8_mem #(.ROM_FILE(ROM_FILE), .ROM_INIT(ROM_INIT)) u_mem (
        .clk(clk), .rst_n(rst_n), .cpu_rst_n(cpu_rst_n),
        .addr(bus_addr), .wdata(bus_wdata),
        // Reads go down unconditionally — the SPRAM is what times the
        // access and what defines the launch cycle, and reading the
        // shadowed byte underneath the I/O page has no side effect.
        // Writes are gated, because those do.
        .read (bus_read),
        .write(bus_write & ~io_sel),
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
