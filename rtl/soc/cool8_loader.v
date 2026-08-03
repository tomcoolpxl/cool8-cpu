// cool8_loader — the hardware loader: a bus master on the end of a wire.
//
// This is what makes software iteration a one-second `cat` instead of a
// bitstream rebuild, and it is why the roadmap says to build it before
// anything else on the FPGA — see D15 and docs/07-loader.md for the wire
// protocol.
//
// It watches every byte arriving on the UART. Bytes that are not part of
// a loader frame are passed through to the CPU's receive FIFO unchanged,
// so a running program can use the serial port and still be interrupted
// and reloaded. A frame is:
//
//   $C8 $8C cmd addr_lo addr_hi len_lo len_hi [data...] csum
//
// $C8 is not valid ASCII and $8C is its bit-reverse, so the pair is
// vanishingly unlikely in text or in a program's own output. A lone $C8
// is forwarded along with whatever followed it, which is why the
// pass-through path needs somewhere to put two bytes at once.
//
// FPGA-only. On the ASIC the equivalent is a microcontroller driving
// nBUSRQ and the merged bus strobes — same commands, different
// transport. See docs/07-loader.md section 4.

`default_nettype none

module cool8_loader (
    input  wire        clk,
    input  wire        rst_n,

    // From the UART receiver
    input  wire [7:0]  rx_data,
    input  wire        rx_valid,

    // To the UART transmitter
    output reg  [7:0]  tx_data,
    output reg         tx_start,
    input  wire        tx_busy,

    // Pass-through to the CPU's receive FIFO
    output reg  [7:0]  fwd_data,
    output reg         fwd_valid,

    // Bus mastering
    output reg         busrq,
    input  wire        busak,
    output reg  [15:0] mem_addr,
    output reg  [7:0]  mem_wdata,
    input  wire [7:0]  mem_rdata,
    output reg         mem_read,
    output reg         mem_write,
    input  wire        mem_ready,

    // CPU control
    output reg         cpu_rst_n,     // GO and RESET pulse this low
    output reg         bootram,       // suppress the boot ROM overlay
    output reg         halt_req,      // HALT / RUN hold the bus

    // Register file view, $FE80
    input  wire        ctrl_we,
    input  wire [7:0]  ctrl_wdata,
    output wire [7:0]  ctrl_rdata,
    output wire [7:0]  stat_rdata
);

    localparam [7:0] MAGIC0 = 8'hC8, MAGIC1 = 8'h8C;
    localparam [7:0] ACK = 8'h4B, NAK = 8'h21, VERSION = 8'h01;

    localparam [3:0] S_IDLE  = 4'd0,  // watching for $C8
                     S_MAGIC = 4'd1,  // saw $C8, is the next one $8C?
                     S_FWD2  = 4'd2,  // forwarding the second of two bytes
                     S_HDR   = 4'd3,  // cmd, addr16, len16
                     S_WAIT  = 4'd4,  // waiting for the bus grant
                     S_WDATA = 4'd5,  // WRITE payload
                     S_CSUM  = 4'd6,  // check and act
                     S_RDATA = 4'd7,  // READ payload out
                     S_RSUM  = 4'd8,  // READ checksum out
                     S_REPLY = 4'd9,  // one byte back
                     S_GO    = 4'd10; // write the reset vector, then run

    reg [3:0]  state;
    reg [2:0]  hdr_i;
    reg [7:0]  cmd, held;
    reg [15:0] addr, len, count;
    reg [7:0]  csum;
    reg [7:0]  reply;
    reg        csum_bad, seen_frame;
    reg        go_phase;              // which half of the vector

    assign ctrl_rdata = {2'b00, bootram, halt_req, 3'b000, 1'b1};
    assign stat_rdata = {5'b00000, seen_frame, csum_bad, busak};

    wire cmd_write = (cmd == 8'h01);
    wire cmd_read  = (cmd == 8'h02);

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= S_IDLE; busrq <= 1'b0; halt_req <= 1'b0;
            mem_read <= 1'b0; mem_write <= 1'b0;
            tx_start <= 1'b0; fwd_valid <= 1'b0;
            cpu_rst_n <= 1'b1; bootram <= 1'b0;
            csum_bad <= 1'b0; seen_frame <= 1'b0;
            hdr_i <= 3'd0; go_phase <= 1'b0;
        end else begin
            tx_start  <= 1'b0;
            fwd_valid <= 1'b0;
            cpu_rst_n <= 1'b1;

            // The CPU can also ask for a grant on its own behalf, and
            // software can clear BOOTRAM to get the boot ROM back.
            if (ctrl_we) begin
                halt_req <= ctrl_wdata[4];
                bootram  <= ctrl_wdata[5];
            end

            // busrq is held for as long as a frame is in flight, or for
            // as long as HALT has not been undone by RUN.
            busrq <= halt_req | (state >= S_WAIT && state != S_REPLY);

            case (state)

            S_IDLE: if (rx_valid) begin
                if (rx_data == MAGIC0) state <= S_MAGIC;
                else begin fwd_data <= rx_data; fwd_valid <= 1'b1; end
            end

            // $C8 arrived. If $8C follows it is a frame; otherwise both
            // bytes belong to the program and both must be forwarded.
            S_MAGIC: if (rx_valid) begin
                if (rx_data == MAGIC1) begin
                    state <= S_HDR; hdr_i <= 3'd0; csum <= 8'h00;
                end else begin
                    fwd_data <= MAGIC0; fwd_valid <= 1'b1;
                    held <= rx_data;
                    state <= S_FWD2;
                end
            end

            // A second $C8 starts a fresh candidate rather than being
            // swallowed — and it must not be forwarded from here, or it
            // would be both passed to the CPU and consumed as magic.
            // S_MAGIC forwards it if the byte after it is not $8C, which
            // is the same decision one byte later.
            S_FWD2: if (held == MAGIC0) state <= S_MAGIC;
                    else begin
                        fwd_data <= held; fwd_valid <= 1'b1;
                        state <= S_IDLE;
                    end

            S_HDR: if (rx_valid) begin
                csum <= csum + rx_data;
                case (hdr_i)
                    3'd0: cmd        <= rx_data;
                    3'd1: addr[7:0]  <= rx_data;
                    3'd2: addr[15:8] <= rx_data;
                    3'd3: len[7:0]   <= rx_data;
                    default: len[15:8] <= rx_data;
                endcase
                if (hdr_i == 3'd4) begin
                    count <= 16'd0;
                    state <= S_WAIT;
                end else hdr_i <= hdr_i + 3'd1;
            end

            // Every command takes the bus, even the ones that do not
            // touch memory: a zero-length WRITE is a documented liveness
            // check and it should exercise the same path.
            S_WAIT: if (busak) begin
                if (cmd_write) state <= (len == 16'd0) ? S_CSUM : S_WDATA;
                else           state <= S_CSUM;
            end

            S_WDATA: begin
                if (mem_write && mem_ready) begin
                    mem_write <= 1'b0;
                    count <= count + 16'd1;
                    addr  <= addr + 16'd1;
                    if (count + 16'd1 == len) state <= S_CSUM;
                end else if (!mem_write && rx_valid) begin
                    csum      <= csum + rx_data;
                    mem_addr  <= addr;
                    mem_wdata <= rx_data;
                    mem_write <= 1'b1;
                end
            end

            S_CSUM: if (rx_valid) begin
                seen_frame <= 1'b1;
                if (rx_data != csum) begin
                    csum_bad <= 1'b1;
                    reply <= NAK;
                    state <= S_REPLY;
                end else begin
                    csum_bad <= 1'b0;
                    csum  <= 8'h00;
                    count <= 16'd0;
                    case (cmd)
                        8'h02: begin                     // READ
                            state <= (len == 16'd0) ? S_RSUM : S_RDATA;
                        end
                        8'h03: begin                     // GO
                            bootram  <= 1'b1;
                            go_phase <= 1'b0;
                            state    <= S_GO;
                        end
                        8'h04: begin halt_req <= 1'b1;   // HALT
                                     reply <= ACK; state <= S_REPLY; end
                        8'h05: begin halt_req <= 1'b0;   // RUN
                                     reply <= ACK; state <= S_REPLY; end
                        8'h06: begin bootram <= 1'b0;    // RESET
                                     cpu_rst_n <= 1'b0;
                                     reply <= ACK; state <= S_REPLY; end
                        8'h07: begin reply <= VERSION;   // PING
                                     state <= S_REPLY; end
                        8'h01: begin reply <= ACK;       // WRITE
                                     state <= S_REPLY; end
                        default: begin reply <= NAK;
                                       state <= S_REPLY; end
                    endcase
                end
            end

            // GO writes the entry point into the reset vector at
            // $FFF8/$FFF9 and then lets the CPU out of reset. BOOTRAM is
            // already set, so it fetches that vector from RAM rather
            // than from the boot ROM.
            S_GO: begin
                if (mem_write && mem_ready) begin
                    mem_write <= 1'b0;
                    if (!go_phase) go_phase <= 1'b1;
                    else begin
                        cpu_rst_n <= 1'b0;
                        halt_req  <= 1'b0;
                        reply <= ACK;
                        state <= S_REPLY;
                    end
                end else if (!mem_write) begin
                    mem_addr  <= go_phase ? 16'hFFF9 : 16'hFFF8;
                    mem_wdata <= go_phase ? addr[15:8] : addr[7:0];
                    mem_write <= 1'b1;
                end
            end

            S_RDATA: begin
                if (mem_read && mem_ready) begin
                    mem_read <= 1'b0;
                    tx_data  <= mem_rdata;
                    tx_start <= 1'b1;
                    csum     <= csum + mem_rdata;
                    addr     <= addr + 16'd1;
                    count    <= count + 16'd1;
                    if (count + 16'd1 == len) state <= S_RSUM;
                end else if (!mem_read && !tx_busy && !tx_start) begin
                    mem_addr <= addr;
                    mem_read <= 1'b1;
                end
            end

            S_RSUM: if (!tx_busy && !tx_start) begin
                tx_data  <= csum;
                tx_start <= 1'b1;
                state    <= S_IDLE;
            end

            default: if (!tx_busy && !tx_start) begin   // S_REPLY
                tx_data  <= reply;
                tx_start <= 1'b1;
                state    <= S_IDLE;
            end

            endcase
        end
    end

endmodule

`default_nettype wire
