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
    output wire        spi_cs_n,
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

    localparam [7:0] A_ADDR_L = 8'h88,         //: FLS_ADDR_L   SPI flash address, low
                     A_ADDR_M = 8'h89,         //: FLS_ADDR_M   SPI flash address, middle
                     A_ADDR_H = 8'h8A,         //: FLS_ADDR_H   SPI flash address, high
                     A_DATA = 8'h8B,           //: FLS_DATA     read the byte at that address
                     A_CTRL = 8'h8C,           //: FLS_CTRL     start a read, select the device
                     A_STAT = 8'h8D,           //: FLS_STAT     busy and done
                     A_WDATA = 8'h8E,          //: FLS_WDATA    byte to program
                     A_WCTRL = 8'h8F;          //: FLS_WCTRL    program and erase control

    // The five opcodes this master has, and there are no others in the
    // gates. A sixth would have to be added here to exist at all.
    localparam [7:0] OP_READ = 8'h03,
                     OP_WREN = 8'h06,    // write enable, before any change
                     OP_PP   = 8'h02,    // page program
                     OP_SE   = 8'h20,    // sector erase, 4 KB
                     OP_RDSR = 8'h05;    // read status, for the busy bit

    // **The floor.** Every program and every erase is compared against
    // this, in gates, on the cycle the request arrives — and one below it
    // is refused before an opcode has been chosen, so there is no path
    // from a bad request to a shifted command. The bitstream lives at
    // offset 0 and the part loads it on every power-on; no discipline in
    // software makes reaching it impossible, and a comparator does.
    localparam [23:0] FLOOR = 24'h100000;

    assign o_sel    = (io_a[7:3] == 5'b10001) & (io_a[2:0] <= 3'd7);
    assign o_dp_sel = (io_a == A_DATA);

    // ---------------------------------------------------------- state

    reg [23:0] addr;
    reg        open_r;

    reg [31:0] sr;                     // command out, or data in on the low 8
    reg [5:0]  n;                      // bits left in the current shift
    reg [1:0]  phase;                 // four clocks a bit, see the shifter
    reg        miso_q;                // MISO, sampled mid-high
    reg        busy;
    reg        cmd;                    // this shift is the 32-bit command

    // ---- the wake-up, once, at reset
    //
    // **The iCE40 leaves the flash asleep, and a bare $03 to a sleeping
    // chip is silence for ever.** picosoc -- the one design proven to
    // read this flash on this board -- sends two frames before its
    // first read, on every reset: $FF (exit continuous-read mode, in
    // case a previous master left the part there) and $AB (release from
    // deep power-down), each under its own chip select. spimemio.v
    // states 0-3. This controller went straight to $03 and read $FF at
    // every address on the bench while passing every testbench, because
    // the model flash starts awake.
    //
    // I_WAIT covers tRES1, the recovery after $AB: 3 us on a W25Q64,
    // given 4095 clocks here (~490 us at 8.375 MHz) because it happens
    // once and margin is free.
    localparam [1:0] I_FF = 2'd0, I_AB = 2'd1, I_WAIT = 2'd2,
                     I_DONE = 2'd3;
    reg  [1:0]  ist;
    reg         i_cs;
    reg  [11:0] iwait;
    wire        init_done = (ist == I_DONE);

    reg [7:0]  pf;                     // the byte at `addr`
    reg        pf_valid;
    reg        pf_want;
    reg        rd_hold;

    // ---- writing
    //
    // A program is three SPI transactions, not one: enable, command, then
    // poll the status register until the part says it has finished. Each
    // is its own chip select, because a flash latches an opcode on the
    // *rising* edge of CS and will simply ignore two commands run
    // together. `W_GAP` states are that rising edge, and they are the
    // whole reason this is a state machine rather than a sequence.
    //
    // The poll is in gates rather than in software because software would
    // have to name the RDSR opcode to do it, and the point of this block
    // is that software cannot name an opcode at all.
    localparam [2:0] W_IDLE = 3'd0, W_WREN = 3'd1, W_GAP  = 3'd2,
                     W_CMD  = 3'd3, W_GAP2 = 3'd4, W_POLL = 3'd5,
                     W_PGAP = 3'd6;

    reg [2:0]  wst;
    reg        w_run;                  // a command is shifting: CS is low
    reg        w_prog;                 // program, rather than erase
    reg        w_denied;               // the last request was below the floor
    reg [7:0]  status;                 // what RDSR last returned
    reg [7:0]  wbuf;                   // the byte being programmed

    wire       w_busy = (wst != W_IDLE);

    // **The only driver of chip select in this file.** A read stream holds
    // it low for as long as it is open; a write holds it low for exactly
    // one command. Two drivers is what the first attempt at this had, and
    // the commands ran together with no edge between them.
    assign spi_cs_n = ~(open_r | w_run | i_cs);

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

    // $FE8F FLS_WCTRL: 1 programs the byte in FLS_WDATA at FLS_ADDR,
    // 2 erases the 4 KB sector it is in, 4 acknowledges a refusal. Both
    // are ignored while a read stream is open, because the address means
    // something different then, and while a write is already running.
    wire wctrl_we  = io_we & (io_a == A_WCTRL) & ~open_r & ~w_busy;
    wire ask_prog  = wctrl_we & io_wdata[0];
    wire ask_erase = wctrl_we & io_wdata[1] & ~io_wdata[0];
    wire below     = (addr < FLOOR);

    // Gated on the wake-up: an open or close arriving in the first
    // ~490 us after reset is dropped rather than allowed to seize a
    // shifter the init frames are using. Nothing real asks that early
    // -- the boot ROM spends tens of milliseconds clearing RAM first.
    wire ctrl_we = io_we & (io_a == A_CTRL);
    wire opening = ctrl_we &  io_wdata[0] & ~open_r & init_done;
    wire closing = ctrl_we & ~io_wdata[0] & init_done;

    always @(posedge clk) begin
        if (!rst_n) begin
            addr     <= 24'h000000;
            open_r   <= 1'b0;
            spi_sck  <= 1'b0;
            sr       <= 32'd0;
            n        <= 6'd0;
            phase    <= 2'd0;
            busy     <= 1'b0;
            cmd      <= 1'b0;
            pf       <= 8'h00;
            pf_valid <= 1'b0;
            pf_want  <= 1'b0;
            rd_hold  <= 1'b0;
            wst      <= W_IDLE;
            w_run    <= 1'b0;
            w_prog   <= 1'b0;
            w_denied <= 1'b0;
            status   <= 8'h00;
            wbuf     <= 8'h00;
            ist      <= I_FF;
            i_cs     <= 1'b0;
            iwait    <= 12'd0;
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
            spi_sck  <= 1'b0;
            busy     <= 1'b0;
            cmd      <= 1'b0;
            n        <= 6'd0;
            phase    <= 2'd0;
            pf_valid <= 1'b0;
            pf_want  <= 1'b0;
            rd_hold  <= 1'b0;
            wst      <= W_IDLE;
            w_run    <= 1'b0;
        end else begin
            rd_hold <= rd_wait;

            // ---- the wake-up frames, through the ordinary shifter.
            //      Each command is: drop CS, shift eight bits, raise CS
            //      -- its own frame, exactly as spimemio does it. `cmd`
            //      is set so the shifter keeps nothing. Nothing else
            //      can be running: open and close are gated on
            //      init_done and the write machine is idle.
            case (ist)
                I_FF: if (!busy) begin
                    if (!i_cs) begin
                        i_cs  <= 1'b1;
                        sr    <= {8'hFF, 24'h0};
                        n     <= 6'd8;
                        phase <= 2'd0;
                        busy  <= 1'b1;
                        cmd   <= 1'b1;
                    end else begin
                        i_cs <= 1'b0;
                        ist  <= I_AB;
                    end
                end
                I_AB: if (!busy) begin
                    if (!i_cs) begin
                        i_cs  <= 1'b1;
                        sr    <= {8'hAB, 24'h0};
                        n     <= 6'd8;
                        phase <= 2'd0;
                        busy  <= 1'b1;
                        cmd   <= 1'b1;
                    end else begin
                        i_cs  <= 1'b0;
                        iwait <= 12'd0;
                        ist   <= I_WAIT;
                    end
                end
                I_WAIT: begin
                    iwait <= iwait + 12'd1;
                    if (&iwait) ist <= I_DONE;
                end
                default: ;
            endcase

            // ---- the write registers
            if (io_we && io_a == A_WDATA) wbuf <= io_wdata;
            // Write 1 to bit 2 to acknowledge a refusal, the shape
            // UART_STAT and VID_IRQ already use. Ahead of the machine
            // below, so a refusal raised this cycle survives being
            // acknowledged in it.
            if (io_we && io_a == A_WCTRL && io_wdata[2]) w_denied <= 1'b0;

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
                sr       <= {OP_READ, addr};
                n        <= 6'd32;
                phase    <= 2'd0;
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
                if (phase != 2'd3) begin
                    // 0: raise SCK.  1: sample MISO in the middle of the
                    // high half.  2: lower SCK.  3: shift, which moves
                    // MOSI -- after the falling edge, never before it.
                    if (phase == 2'd0) spi_sck <= 1'b1;
                    if (phase == 2'd1) miso_q  <= spi_miso;
                    if (phase == 2'd2) spi_sck <= 1'b0;
                    phase <= phase + 2'd1;
                end else begin
                    phase   <= 2'd0;
                    sr      <= {sr[30:0], miso_q};
                    n       <= n - 6'd1;
                    if (n == 6'd1) begin
                        busy <= 1'b0;
                        // The command shift keeps nothing; a data shift
                        // ends holding the byte. `sr` is being written
                        // in this same cycle, so the byte has to be
                        // named as the value that is landing.
                        if (!cmd) begin
                            pf       <= {sr[6:0], miso_q};
                            pf_valid <= 1'b1;
                            pf_want  <= 1'b0;
                        end
                        // Only RDSR's answer is ever looked at, and only
                        // in W_PGAP, so capturing it for every write
                        // command costs nothing and needs no condition.
                        if (w_run) status <= {sr[6:0], miso_q};
                    end
                end
            end else if (open_r && pf_want && !pf_valid) begin
                busy  <= 1'b1;
                n     <= 6'd8;
                phase <= 2'd0;
                cmd   <= 1'b0;
            end

            // A page program is 40 bits and the shifter is 32, so the
            // data byte is dropped into the top as the address leaves it:
            // when nine bits remain, the next eight are the byte. This
            // must land *after* the shift above, which is why it is here
            // and not inside it.
            if (w_run && busy && (phase == 2'd3) && w_prog && (n == 6'd9))
                sr[31:24] <= wbuf;

            // ---- the write machine
            //
            // Every arm sets `w_run` and the shifter clears `busy`; a
            // command is over on the first cycle both are true, and the
            // GAP states that follow are the rising edge of chip select
            // that makes the part act on what it was just sent.
            case (wst)
                W_IDLE: if ((ask_prog | ask_erase) && init_done) begin
                    if (below) begin
                        // Refused, and nothing happens: no enable, no
                        // opcode, no chip select. The flag is how software
                        // finds out.
                        w_denied <= 1'b1;
                    end else begin
                        w_prog <= ask_prog;
                        w_run  <= 1'b1;
                        sr     <= {OP_WREN, 24'd0};
                        n      <= 6'd8;
                        phase  <= 2'd0;
                        busy   <= 1'b1;
                        cmd    <= 1'b1;
                        wst    <= W_WREN;
                    end
                end

                W_WREN: if (w_run && !busy) begin
                    w_run <= 1'b0;
                    wst   <= W_GAP;
                end

                W_GAP: begin
                    w_run <= 1'b1;
                    sr    <= w_prog ? {OP_PP, addr} : {OP_SE, addr};
                    n     <= w_prog ? 6'd40 : 6'd32;
                    phase <= 2'd0;
                    busy  <= 1'b1;
                    cmd   <= 1'b1;
                    wst   <= W_CMD;
                end

                W_CMD: if (w_run && !busy) begin
                    w_run <= 1'b0;
                    wst   <= W_GAP2;
                end

                W_GAP2, W_PGAP: begin
                    // A program takes milliseconds and an erase tens of
                    // them, and the part ignores everything meanwhile. Ask
                    // it, and keep asking until bit 0 of its status clears.
                    if ((wst == W_GAP2) || status[0]) begin
                        w_run <= 1'b1;
                        sr    <= {OP_RDSR, 24'd0};
                        n     <= 6'd16;
                        phase <= 2'd0;
                        busy  <= 1'b1;
                        cmd   <= 1'b1;
                        wst   <= W_POLL;
                    end else begin
                        w_prog <= 1'b0;
                        wst    <= W_IDLE;
                    end
                end

                default: if (w_run && !busy) begin   // W_POLL
                    w_run <= 1'b0;
                    wst   <= W_PGAP;
                end
            endcase
        end
    end

    always @* begin
        case (io_a)
            A_ADDR_L: o_rdata = addr[7:0];
            A_ADDR_M: o_rdata = addr[15:8];
            A_ADDR_H: o_rdata = addr[23:16];
            A_CTRL:   o_rdata = {7'b0000000, open_r};
            A_STAT:   o_rdata = {5'b00000, w_busy, open_r, busy};
            // $FE8F: bit 0 a write is running, bit 2 the last request was
            // below the floor and was refused.
            A_WCTRL:  o_rdata = {5'b00000, w_denied, 1'b0, w_busy};
            default:  o_rdata = o_dout;
        endcase
    end

endmodule

`default_nettype wire
