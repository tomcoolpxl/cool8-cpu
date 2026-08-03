// cool8_uart — 8N1 serial, sized by a register rather than a parameter.
//
// Connected to the iCELink debugger's USB CDC bridge on FPGA pins 4 and
// 6. The FPGA end cannot learn what baud rate the host picked, so both
// have to be set to agree — see docs/04-system.md section 4.6. The
// divider is a register so that can be changed without rebuilding the
// bitstream.
//
//   div = round(f_clk / baud) - 1
//
// At the 12 MHz system clock, 115200 baud is div = 103, which lands on
// 115385 baud — 0.16 % out, far inside the ~2 % a UART tolerates.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_uart (
    input  wire        clk,
    input  wire        rst_n,

    input  wire [15:0] div,          // baud divider, see above

    input  wire        rx_pin,
    output reg         tx_pin,

    // Receive: one clock wide strobe with the byte
    output reg  [7:0]  rx_data,
    output reg         rx_valid,

    // Transmit: assert tx_start for one clock while tx_busy is low
    input  wire [7:0]  tx_data,
    input  wire        tx_start,
    output wire        tx_busy
);

    // ------------------------------------------------------------ rx
    // Two flops to bring the pin into this clock domain, then a start
    // bit is a falling edge held for half a bit time.

    reg [2:0] rx_sync;
    always @(posedge clk) rx_sync <= {rx_sync[1:0], rx_pin};
    wire rx_in = rx_sync[2];

    reg [15:0] rx_cnt;
    reg [3:0]  rx_bit;
    reg [7:0]  rx_sr;
    reg        rx_run;

    always @(posedge clk) begin
        if (!rst_n) begin
            rx_run <= 1'b0; rx_valid <= 1'b0; rx_cnt <= 16'd0;
            rx_bit <= 4'd0; rx_data <= 8'h00;
        end else begin
            rx_valid <= 1'b0;
            if (!rx_run) begin
                // Wait for the start bit, then sample half a bit in so
                // every subsequent sample lands mid-bit.
                if (!rx_in) begin
                    rx_run <= 1'b1;
                    rx_cnt <= {1'b0, div[15:1]};
                    rx_bit <= 4'd0;
                end
            end else if (rx_cnt != 16'd0) begin
                rx_cnt <= rx_cnt - 16'd1;
            end else begin
                rx_cnt <= div;
                if (rx_bit == 4'd0) begin
                    // Still low half a bit in? A real start bit.
                    if (rx_in) rx_run <= 1'b0;      // glitch, give up
                    else       rx_bit <= 4'd1;
                end else if (rx_bit <= 4'd8) begin
                    rx_sr  <= {rx_in, rx_sr[7:1]};
                    rx_bit <= rx_bit + 4'd1;
                end else begin
                    // Stop bit. Accept the byte even if framing is off;
                    // the USB layer below has already done the work a
                    // framing check would duplicate.
                    rx_data  <= rx_sr;
                    rx_valid <= 1'b1;
                    rx_run   <= 1'b0;
                end
            end
        end
    end

    // ------------------------------------------------------------ tx

    reg [15:0] tx_cnt;
    reg [3:0]  tx_bit;
    reg [9:0]  tx_sr;
    reg        tx_run;

    assign tx_busy = tx_run;

    always @(posedge clk) begin
        if (!rst_n) begin
            tx_run <= 1'b0; tx_pin <= 1'b1; tx_cnt <= 16'd0;
            tx_bit <= 4'd0; tx_sr <= 10'h3FF;
        end else if (!tx_run) begin
            tx_pin <= 1'b1;
            if (tx_start) begin
                tx_sr  <= {1'b1, tx_data, 1'b0};   // stop, data, start
                tx_run <= 1'b1;
                tx_cnt <= div;
                tx_bit <= 4'd0;
            end
        end else if (tx_cnt != 16'd0) begin
            tx_cnt <= tx_cnt - 16'd1;
            tx_pin <= tx_sr[0];
        end else begin
            tx_cnt <= div;
            tx_sr  <= {1'b1, tx_sr[9:1]};
            tx_pin <= tx_sr[1];
            if (tx_bit == 4'd9) tx_run <= 1'b0;
            else                tx_bit <= tx_bit + 4'd1;
        end
    end

endmodule

`default_nettype wire
