// tt_um_cool8 — the TinyTapeout pad wrapper.
//
// The three-phase bus multiplexer from docs/03-microarchitecture.md
// section 5. The core's flat 16-bit address and 8-bit data interface
// does not fit in TinyTapeout's 24 usable pins, so address low, address
// high and data share the eight bidirectional pins across three clocks,
// with two external 74HC573 latches reconstructing the full address.
//
//              T1          T2          T3
//   AD      ==<A[7:0]>===<A[15:8]>===<  D[7:0] >==
//   ALE_L   __/‾‾‾‾\_________________________
//   ALE_H   __________/‾‾‾‾\________________
//   nRD     ‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\______/‾‾‾‾
//
// Read data is sampled on the rising edge of nRD, which is the clock
// edge that ends T3 — the same edge on which the core latches it.
//
// Every memory access therefore costs three clocks here against one on
// the FPGA. The core neither knows nor cares: it sees mem_ready low for
// two cycles and high on the third, which is the same protocol the
// SPRAM controller presents.
//
// This is the M3 form of the wrapper: enough to harden and measure. The
// end-to-end bus-grant load path against real latch and SRAM models is
// M8 work — see docs/06-roadmap.md.

`default_nettype none

module tt_um_cool8 (
    input  wire [7:0] ui_in,     // dedicated inputs
    output wire [7:0] uo_out,    // dedicated outputs
    input  wire [7:0] uio_in,    // bidirectional, input path
    output wire [7:0] uio_out,   // bidirectional, output path
    output wire [7:0] uio_oe,    // bidirectional, per-bit output enable
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    localparam [1:0] T1 = 2'd0, T2 = 2'd1, T3 = 2'd2;

    // ------------------------------------------------------ pin names

    wire n_irq   = ui_in[0];
    wire n_nmi   = ui_in[1];
    wire ready   = ui_in[2];     // hold low to insert wait states
    wire n_busrq = ui_in[3];

    // Interrupt and arbitration inputs are asynchronous to this clock;
    // the core expects them already synchronised.
    reg [1:0] irq_s, nmi_s, busrq_s, ready_s;
    always @(posedge clk) begin
        if (!rst_n) begin
            irq_s <= 2'b00; nmi_s <= 2'b00;
            busrq_s <= 2'b00; ready_s <= 2'b11;
        end else begin
            irq_s   <= {irq_s[0],   ~n_irq};
            nmi_s   <= {nmi_s[0],   ~n_nmi};
            busrq_s <= {busrq_s[0], ~n_busrq};
            ready_s <= {ready_s[0], ready};
        end
    end

    // ---------------------------------------------------------- core

    wire [15:0] mem_addr;
    wire [7:0]  mem_wdata;
    wire        mem_read, mem_write;
    wire        busak, o_fetch, o_halted, o_iack, o_retire;

    wire access = mem_read | mem_write;

    reg [1:0] phase;
    always @(posedge clk) begin
        if (!rst_n)             phase <= T1;
        else if (!access)       phase <= T1;
        else if (phase == T3)   phase <= ready_s[1] ? T1 : T3;
        else                    phase <= phase + 2'd1;
    end

    wire in_t3     = (phase == T3);
    wire mem_ready = in_t3 & ready_s[1];

    cool8_core u_core (
        .clk(clk), .rst_n(rst_n),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata),
        .mem_rdata(uio_in),                 // valid in T3, sampled at its end
        .mem_read(mem_read), .mem_write(mem_write), .mem_ready(mem_ready),
        .irq(irq_s[1]), .nmi(nmi_s[1]),
        .busrq(busrq_s[1]), .busak(busak),
        .o_fetch(o_fetch), .o_halted(o_halted), .o_iack(o_iack),
        .o_retire(o_retire)
    );

    // ----------------------------------------------- the multiplexer

    reg [7:0] ad;
    always @* begin
        case (phase)
            T1:      ad = mem_addr[7:0];
            T2:      ad = mem_addr[15:8];
            default: ad = mem_wdata;
        endcase
    end

    // The core is off the bus entirely while it holds BUSAK, so the
    // external agent's strobes can simply be OR/AND-merged with these
    // on the board — see section 5.3.
    wire driving = access & ~busak & ~(in_t3 & mem_read);

    assign uio_out = ad;
    assign uio_oe  = {8{driving}};

    // The ALE pulses are half a clock wide, not a whole one. AD changes
    // on the rising edge that ends each phase, so a full-width strobe
    // would fall at the same instant the address it is latching goes
    // away — zero hold time into the 74HC573. Closing the latch on the
    // falling edge instead leaves half a clock of hold, which is what
    // the waveform in docs/03-microarchitecture.md section 5.4 draws
    // and what the 8085 this is descended from does.
    wire ale_l = access & ~busak & (phase == T1) & clk;
    wire ale_h = access & ~busak & (phase == T2) & clk;
    wire n_rd  = ~(mem_read  & ~busak & in_t3);
    wire n_wr  = ~(mem_write & ~busak & in_t3);

    assign uo_out = {busak, o_iack, o_halted, o_fetch,
                     n_wr, n_rd, ale_h, ale_l};

    wire _unused = &{ena, ui_in[7:4], o_retire, 1'b0};

endmodule

`default_nettype wire
