// ---------------------------------------------------------------------
// A bring-up top level: the flash reader, a UART, and nothing else.
//
// The machine could not read its own flash on the board while every
// testbench passed, and a whole SoC is too large a thing to bisect from
// the outside. This is the smallest design that can answer the
// question: does `cool8_flash` fetch bytes off a real chip?
//
// It opens the flash at $100000 and streams what it reads out of the
// serial port for ever, so `npm run board` or any terminal at 115200
// shows the volume 0 directory -- `SYSTEM` then `BOOT    BIN` -- if the
// reader works, and nothing but $FF if it does not.
//
// **No PLL and no CPU.** The 12 MHz oscillator on pin 35 drives
// everything directly, so a fault here cannot be the PLL, the core, the
// bus or the boot ROM. What is left is the flash controller, the four
// pads and the constraints.
//
//     yosys -p 'synth_ice40 -top cool8_flashtest -json ft.json' \
//           rtl/soc/cool8_flash.v rtl/soc/cool8_flashtest.v
//     nextpnr-ice40 --up5k --package sg48 --json ft.json \
//                   --pcf board/flashtest.pcf --asc ft.asc
//     icepack ft.asc ft.bin
// ---------------------------------------------------------------------

module cool8_flashtest (
    input  wire clk,                    // 12 MHz, pin 35

    output wire uart_tx,

    output wire flash_cs,
    output wire flash_sck,
    inout  wire flash_mosi,
    inout  wire flash_miso,
    inout  wire flash_wp,
    inout  wire flash_hold,

    output wire led_g
);
    // ---- reset, held for a while after configuration
    reg [7:0] rstc = 0;
    wire rst_n = &rstc;
    always @(posedge clk) if (!rst_n) rstc <= rstc + 1'b1;

    // ---- the pads, exactly as picosoc drives them
    wire [3:0] io_i;
    wire       mosi_o;

    SB_IO #(
        .PIN_TYPE(6'b1010_01),
        .PULLUP(1'b0)
    ) u_io [3:0] (
        .PACKAGE_PIN({flash_hold, flash_wp, flash_miso, flash_mosi}),
        .OUTPUT_ENABLE({1'b1, 1'b1, 1'b0, 1'b1}),
        .D_OUT_0({1'b1, 1'b1, 1'b0, mosi_o}),
        .D_IN_0(io_i)
    );

    // ---- the reader under test
    reg  [7:0] io_a;
    reg        io_rd, io_we;
    reg  [7:0] io_wdata;
    wire [7:0] dout;
    wire       stall;

    cool8_flash u_fls (
        .clk(clk), .rst_n(rst_n),
        .spi_cs_n(flash_cs), .spi_sck(flash_sck),
        .spi_mosi(mosi_o),  .spi_miso(io_i[1]),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wdata(io_wdata),
        .o_sel(), .o_dp_sel(), .o_rdata(), .o_dout(dout), .o_stall(stall)
    );

    // ---- a transmit-only UART, 12 MHz / 115200 = 104
    localparam integer DIV = 104;
    reg [9:0] shreg = 10'h3FF;
    reg [7:0] baud  = 0;
    reg [3:0] bit_n = 0;
    wire      tx_busy = (bit_n != 0);
    reg       tx_go = 0;
    reg [7:0] tx_dat;

    assign uart_tx = shreg[0];

    always @(posedge clk) begin
        if (baud != 0) baud <= baud - 1'b1;
        else begin
            baud <= DIV - 1;
            if (tx_busy) begin
                shreg <= {1'b1, shreg[9:1]};
                bit_n <= bit_n - 1'b1;
            end else if (tx_go) begin
                shreg <= {1'b1, tx_dat, 1'b0};
                bit_n <= 10;
            end
        end
    end

    // ---- the sequence: point at $100000, open, then read for ever
    localparam S_AL = 0, S_AM = 1, S_AH = 2, S_OPEN = 3,
               S_RD = 4, S_WAIT = 5, S_SEND = 6, S_HOLD = 7;
    reg [2:0] st = S_AL;
    reg [7:0] seen = 0;

    assign led_g = ~(seen != 8'hFF && seen != 8'h00);   // lit if real data

    always @(posedge clk) begin
        io_rd <= 0; io_we <= 0; tx_go <= 0;
        if (!rst_n) st <= S_AL;
        else case (st)
            S_AL:   begin io_a <= 8'h88; io_wdata <= 8'h00; io_we <= 1;
                          st <= S_AM; end
            S_AM:   begin io_a <= 8'h89; io_wdata <= 8'h00; io_we <= 1;
                          st <= S_AH; end
            S_AH:   begin io_a <= 8'h8A; io_wdata <= 8'h10; io_we <= 1;
                          st <= S_OPEN; end
            S_OPEN: begin io_a <= 8'h8C; io_wdata <= 8'h01; io_we <= 1;
                          st <= S_RD; end
            S_RD:   begin io_a <= 8'h8B; io_rd <= 1; st <= S_WAIT; end
            S_WAIT: if (!stall) begin seen <= dout; st <= S_SEND; end
                    else io_rd <= 1;
            S_SEND: if (!tx_busy) begin
                        tx_dat <= dout; tx_go <= 1; st <= S_HOLD;
                    end
            S_HOLD: if (tx_busy) st <= S_RD;
        endcase
    end
endmodule
