// cool8_flash — the configuration flash as mass storage: $FE88-$FE8D.
//
// The iCE40 releases pins 14-17 to user logic once CDONE goes high, so
// the 8 MB part the bitstream came out of is also the machine's disk. It
// is the cartridge slot, and it costs nothing on the PMOD budget —
// docs/05-board.md section 2.
//
//   $FE88  FLS_ADDR_L   address 7:0
//   $FE89  FLS_ADDR_M   address 15:8
//   $FE8A  FLS_ADDR_H   address 23:16
//   $FE8B  FLS_DATA     one byte, address advances. A read has a side effect
//   $FE8C  FLS_CTRL     bit 0: open the stream / close it
//   $FE8D  FLS_STAT     bit 0 busy, bit 1 stream open
//
// ## Read-only in hardware, and that is the point
//
// The only opcode this master can issue is $03, READ. There is no
// write-enable, no page program and no erase anywhere in the logic, so
// no amount of software error — a wild pointer, a runaway loop, a
// program loaded to the wrong address — can corrupt the bitstream living
// at offset 0. D16 argues that at length. A filesystem would want
// writing; a filesystem can want it from the host, over the loader.
//
// ## Why a read stalls instead of reporting busy
//
// A byte off the wire is sixteen system clocks and the CPU can ask for
// one in two, so something has to give. The documented shape of the copy
// loop (04-system.md section 4.8) has no status poll in it — it is a
// `LD` and a `ST` and nothing else, because that is what makes 64 KB
// take 125 ms instead of twice that. So `o_stall` holds mem_ready low
// until the byte is there, exactly as cool8_vport does for VRAM, and the
// core's tolerance of arbitrary wait states is what pays for it.
//
// FLS_STAT is still there, and it is not redundant: it is how a program
// asks whether the *stream* is open without touching the data register,
// and a read of it never stalls.
//
// The byte is prefetched, so the loop above only ever stalls for what
// the SPI clock genuinely costs. Opening the stream starts the first
// fetch; every read hands over the register and starts the next.
//
// ## SPI clock
//
// Mode 0 — the clock idles low, the device samples MOSI on the rising
// edge and presents MISO on the falling one. SCK is the system clock
// divided by two, which is 4.19 MHz at D32's 8.375: about 500 KB/s, and
// 64 KB of program in 125 ms. Opcode $03 has no dummy cycles and no
// upper frequency worth chasing here — it is specified to 50 MHz on
// these parts and the system clock is the limit long before the flash
// is.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_flash (
    input  wire        clk,
    input  wire        rst_n,

    // ---- the pads
    output reg         spi_cs_n,
    output reg         spi_sck,
    output wire        spi_mosi,
    input  wire        spi_miso,

    // ---- the I/O page
    input  wire [7:0]  io_a,
    input  wire        io_rd,
    input  wire        io_we,
    input  wire [7:0]  io_wdata,

    output wire        o_sel,
    output wire        o_dp_sel,        // ...and it is FLS_DATA
    output reg  [7:0]  o_rdata,         // the registers, combinational
    output wire [7:0]  o_dout,          // the streamed byte, registered
    output wire        o_stall
);

    localparam [7:0] A_ADDR_L = 8'h88,
                     A_ADDR_M = 8'h89,
                     A_ADDR_H = 8'h8A,
                     A_DATA   = 8'h8B,
                     A_CTRL   = 8'h8C,
                     A_STAT   = 8'h8D;

    assign o_sel    = (io_a[7:3] == 5'b10001) & (io_a[2:0] <= 3'd5);
    assign o_dp_sel = (io_a == A_DATA);

    // ---------------------------------------------------------- state

    reg [23:0] addr;
    reg        open_r;

    reg [31:0] sr;                     // command out, or data in on the low 8
    reg [5:0]  n;                      // bits left in the current shift
    reg        phase;                  // 0 = drive, 1 = sample
    reg        busy;
    reg        cmd;                    // this shift is the 32-bit command

    reg [7:0]  pf;                     // the byte at `addr`
    reg        pf_valid;
    reg        pf_want;
    reg        rd_hold;

    assign spi_mosi = sr[31];

    // A read completes on the first cycle the prefetched byte is there.
    // `rd_hold` carries it across the gap because `io_rd` is one pulse
    // and the launch does not come again while mem_ready is low — the
    // same reasoning, and the same shape, as cool8_vport.
    wire dp_rd     = io_rd & o_dp_sel;
    wire rd_active = dp_rd | rd_hold;

    // With no stream open there is nothing to wait for and nothing on
    // its way, so the read completes at once and returns whatever the
    // last one left behind. Stalling instead would be a hang: no fetch
    // is armed, none can be, and `mem_ready` would never come back.
    wire rd_ok     = pf_valid | ~open_r;
    wire rd_done   = rd_active &  rd_ok;
    wire rd_wait   = rd_active & ~rd_ok;

    // Not asserted on the launch cycle: that cycle already has mem_ready
    // low from the memory, so the term is redundant, and leaving it out
    // keeps `io_a` off the ready path. cool8_vport says why that matters.
    assign o_stall = rd_hold & ~pf_valid;

    assign o_dout  = pf;

    wire ctrl_we = io_we & (io_a == A_CTRL);
    wire opening = ctrl_we &  io_wdata[0] & ~open_r;
    wire closing = ctrl_we & ~io_wdata[0];

    always @(posedge clk) begin
        if (!rst_n) begin
            addr     <= 24'h000000;
            open_r   <= 1'b0;
            spi_cs_n <= 1'b1;
            spi_sck  <= 1'b0;
            sr       <= 32'd0;
            n        <= 6'd0;
            phase    <= 1'b0;
            busy     <= 1'b0;
            cmd      <= 1'b0;
            pf       <= 8'h00;
            pf_valid <= 1'b0;
            pf_want  <= 1'b0;
            rd_hold  <= 1'b0;
        // Closing is written as its own branch rather than as one more
        // `if` in the sequence below, and that is not tidiness. A shift
        // in progress assigns `sr`, `n` and `spi_sck` from further down
        // the same block, so a close that shares a cycle with one gets
        // half of itself overwritten and leaves the machine holding a
        // part-finished transfer. The next open then shifts a command
        // built out of the wreckage, and the flash sees an opcode that
        // is not $03 — which is exactly what cool8_flash_tb's device
        // model refused to answer.
        end else if (closing) begin
            open_r   <= 1'b0;
            spi_cs_n <= 1'b1;
            spi_sck  <= 1'b0;
            busy     <= 1'b0;
            cmd      <= 1'b0;
            n        <= 6'd0;
            phase    <= 1'b0;
            pf_valid <= 1'b0;
            pf_want  <= 1'b0;
            rd_hold  <= 1'b0;
        end else begin
            rd_hold <= rd_wait;

            // ---- the address register. Writing it while the stream is
            //      open does nothing to the stream: the flash is already
            //      counting on its own and only a close and a re-open
            //      moves it. That is the part worth knowing about a
            //      streaming read.
            if (io_we && !open_r) begin
                case (io_a)
                    A_ADDR_L: addr[7:0]   <= io_wdata;
                    A_ADDR_M: addr[15:8]  <= io_wdata;
                    A_ADDR_H: addr[23:16] <= io_wdata;
                    default: ;
                endcase
            end

            // ---- open
            if (opening) begin
                open_r   <= 1'b1;
                spi_cs_n <= 1'b0;
                sr       <= {8'h03, addr};
                n        <= 6'd32;
                phase    <= 1'b0;
                busy     <= 1'b1;
                cmd      <= 1'b1;
                pf_valid <= 1'b0;
                pf_want  <= 1'b1;          // fetch the first byte after it
            end

            // ---- hand the byte over and arm the next fetch. A read
            //      with no stream open completed above without one, and
            //      must not move an address the part is not counting.
            if (rd_done && open_r) begin
                pf_valid <= 1'b0;
                pf_want  <= 1'b1;
                addr     <= addr + 24'd1;
            end

            // ---- the shifter. Two system clocks a bit: MOSI is set up
            //      with SCK low, then SCK rises and the device samples
            //      it. MISO changes on the falling edge and is read back
            //      in the high half, which is mode 0 exactly. The
            //      device's setup time is a whole system clock rather
            //      than a routing delay.
            if (busy) begin
                if (!phase) begin
                    spi_sck <= 1'b1;
                    phase   <= 1'b1;
                end else begin
                    spi_sck <= 1'b0;
                    phase   <= 1'b0;
                    sr      <= {sr[30:0], spi_miso};
                    n       <= n - 6'd1;
                    if (n == 6'd1) begin
                        busy <= 1'b0;
                        // The command shift keeps nothing; a data shift
                        // ends holding the byte. `sr` is being written
                        // in this same cycle, so the byte has to be
                        // named as the value that is landing.
                        if (!cmd) begin
                            pf       <= {sr[6:0], spi_miso};
                            pf_valid <= 1'b1;
                            pf_want  <= 1'b0;
                        end
                    end
                end
            end else if (open_r && pf_want && !pf_valid) begin
                busy  <= 1'b1;
                n     <= 6'd8;
                phase <= 1'b0;
                cmd   <= 1'b0;
            end
        end
    end

    always @* begin
        case (io_a)
            A_ADDR_L: o_rdata = addr[7:0];
            A_ADDR_M: o_rdata = addr[15:8];
            A_ADDR_H: o_rdata = addr[23:16];
            A_CTRL:   o_rdata = {7'b0000000, open_r};
            A_STAT:   o_rdata = {6'b000000, open_r, busy};
            default:  o_rdata = o_dout;
        endcase
    end

endmodule

`default_nettype wire
