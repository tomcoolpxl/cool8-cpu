// cool8_ps2 — the keyboard port: $FE40-$FE43.
//
// Raw Set 2 scancodes in, a FIFO, and a transmit path for the handful of
// commands a keyboard actually needs. Translation to ASCII is software's
// job and lives in the monitor — docs/04-system.md section 4.3.
//
// ## The wire
//
// Two open-drain lines with pull-ups, and *the device owns the clock*.
// A frame is eleven bits — start 0, eight data least significant first,
// odd parity, stop 1 — and the device changes data while the clock is
// high, so the host reads it on the falling edge. The clock runs at
// 10-16.7 kHz, which is 500 to 840 system clocks per half period. There
// is no hurry anywhere in this block.
//
// Host-to-device inverts that rule and it is the classic place a
// transmit path goes wrong: the *host* changes data while the clock is
// low and the device reads it while the clock is high. Same eleven bits
// on the same wires, opposite sampling. Sequence, from the protocol:
//
//   1. hold the clock low for at least 100 us      — inhibit
//   2. pull data low                               — the start bit
//   3. release the clock                           — request to send
//   4-8. the device now clocks; put a bit out on every falling edge
//   9. release data after the parity bit           — the stop bit
//   10-12. the device pulls data low for one more clock — the ack
//
// ## The watchdog is not optional
//
// Nothing in a PS/2 frame identifies where it starts. A glitch, a cable
// pulled mid-frame, or a keyboard plugged in while the machine is
// running leaves the bit counter at some value that is not zero, and
// every subsequent frame is then shifted by that amount forever. There
// is no self-correction to wait for.
//
// So an idle clock resynchronises: **60 us with no edge and the frame is
// abandoned**. That is longer than any gap inside a real frame — the
// slowest legal half period is 50 us — and far shorter than the gap
// between frames. It is the whole reason hot-plugging works, and it
// costs one comparator on a counter this block needs anyway.
//
// The same counter carries the two other times that matter: the 100 us
// inhibit, and — prescaled by 256 — the 15 ms the protocol gives a
// device to start clocking after a request to send. A keyboard that
// never answers must not wedge `tx_busy` forever, because a monitor
// setting the caps-lock LED would then hang on a wire nobody has
// plugged in.
//
// ## The FIFO is a block RAM
//
// Sixteen bytes in flip-flops is a measured 109 LUT4 and 123 registers —
// the number cool8_soc.v paid for the receive FIFO when block RAM was
// the scarce resource and logic was not. At M6 that is the wrong way
// round, so this one is storage plus a read register.
//
// A block RAM reads a cycle late, and the contract that makes that
// invisible is narrow enough to state: **`head` is correct whenever
// `avail` is set**. Anything that can move either pointer raises
// `settle` for the cycle afterwards and `avail` is suppressed while it
// is high. A push into a non-empty FIFO does not move `rd`, so the
// re-read returns the same byte and nothing is disturbed; a push into an
// empty one does, and `avail` was already low. This is written out
// rather than inferred because a retimed read port is a transform no
// test in this project reaches.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_ps2 #(
    // Everything below is in system clocks. The defaults are 8.375 MHz
    // (D32); a testbench overrides them to keep simulations short.
    parameter integer FILT    = 48,      // ~5.7 us of line filtering
    parameter integer T60US   = 503,     // the receive watchdog
    parameter integer T100US  = 838,     // the transmit inhibit
    parameter integer TXTO    = 256      // x T60US ~ 15 ms, the device limit
) (
    input  wire        clk,
    input  wire        rst_n,

    // The pads. Open drain lives in cool8_top: `*_oe` high pulls the
    // line down, low lets the pull-up have it.
    input  wire        ps2_clk_i,
    input  wire        ps2_dat_i,
    output wire        ps2_clk_oe,
    output wire        ps2_dat_oe,

    // ---- the I/O page, same shape as every other block on it
    input  wire [7:0]  io_a,
    input  wire        io_rd,
    input  wire        io_we,
    input  wire [7:0]  io_wdata,

    output wire        o_sel,
    output reg  [7:0]  o_rdata,

    output wire        o_irq,

    // Ctrl+Shift+Esc and Ctrl+Esc, decoded from the byte stream -- see
    // "modifiers, and the chords" below for why they live here and not
    // in software.
    output wire        o_reset,
    output wire        o_warm
);

    localparam [7:0] A_STAT = 8'h40,
                     A_DATA = 8'h41,
                     A_CTRL = 8'h42,
                     A_TX   = 8'h43,
                     A_MOD  = 8'h44;

    localparam AB = 4;                   // FIFO address bits: 16 bytes
    localparam DEPTH = 1 << AB;

    assign o_sel = (io_a == A_STAT) | (io_a == A_DATA) |
                   (io_a == A_CTRL) | (io_a == A_TX) |
                   (io_a == A_MOD);

    // ------------------------------------------------- the lines, filtered
    //
    // Two flip-flops to cross into this domain, then a level has to hold
    // for FILT clocks before it is believed. The counter restarts every
    // time the raw pin agrees with the filtered value, so it measures
    // "how long has this been trying to change" and nothing else.

    reg [1:0] cs, ds;
    reg [5:0] fcnt;
    reg       cf, cf_d;                  // the filtered clock, and delayed

    always @(posedge clk) begin
        if (!rst_n) begin
            cs <= 2'b11; ds <= 2'b11; fcnt <= 6'd0; cf <= 1'b1; cf_d <= 1'b1;
        end else begin
            cs   <= {cs[0], ps2_clk_i};
            ds   <= {ds[0], ps2_dat_i};
            cf_d <= cf;
            if (cs[1] == cf)          fcnt <= 6'd0;
            else if (fcnt >= FILT[5:0]) begin
                cf   <= cs[1];
                fcnt <= 6'd0;
            end else                  fcnt <= fcnt + 6'd1;
        end
    end

    wire c_fall = cf_d & ~cf;
    wire dat_in = ds[1];

    // ------------------------------------------------------- the timer
    //
    // One counter, three jobs, and they cannot overlap: the watchdog only
    // matters while a frame is part-received, the inhibit only while
    // transmitting, and the device timeout only after that. `tmr_clr` is
    // driven from whichever is in charge.

    reg [9:0] tmr;
    reg [7:0] tos;                       // prescaler for the 15 ms limit

    wire tmr_60  = (tmr >= T60US[9:0]);
    wire tmr_100 = (tmr >= T100US[9:0]);

    // --------------------------------------------------------- transmit

    localparam [2:0] T_IDLE = 3'd0,      // the device may talk
                     T_INH  = 3'd1,      // clock held low, 100 us
                     T_RTS  = 3'd2,      // data low, clock released
                     T_BITS = 3'd3,      // eight data, then parity
                     T_STOP = 3'd4,      // data released
                     T_ACK  = 3'd5;      // the device pulls data low

    reg [2:0]  ts;
    reg [8:0]  tx_sr;                    // {parity, data}
    reg [3:0]  tx_n;
    reg        tx_dat;                   // 1 = pull data low
    reg        tx_err;

    wire txing = (ts != T_IDLE);

    assign ps2_clk_oe = (ts == T_INH);
    assign ps2_dat_oe = tx_dat;

    // ---------------------------------------------------------- receive

    reg [10:0] rx_sr;
    reg [3:0]  rx_n;
    reg        par_err;

    wire [10:0] rx_next = {dat_in, rx_sr[10:1]};
    wire        rx_last = (rx_n == 4'd10);

    // Start 0, stop 1, and an odd number of ones across the eight data
    // bits and the parity bit together.
    wire rx_ok = (rx_next[0] == 1'b0) & (rx_next[10] == 1'b1) &
                 (^rx_next[9:1] == 1'b1);

    wire rx_done = c_fall & ~txing & rx_last;
    wire push    = rx_done & rx_ok;

    // ------------------------------------------------------------ FIFO

    (* ram_style = "block" *)
    reg [7:0] q [0:DEPTH-1];
    reg [AB:0] wr, rd;                   // one extra bit tells full from empty
    reg [7:0]  head;
    reg        settle;
    reg        over;

    wire full  = (wr[AB-1:0] == rd[AB-1:0]) & (wr[AB] != rd[AB]);
    wire clr   = io_we & (io_a == A_CTRL) & io_wdata[0];
    wire pop   = io_rd & (io_a == A_DATA) & (wr != rd) & ~settle;
    wire avail = (wr != rd) & ~settle;

    always @(posedge clk) begin
        if (!rst_n) begin
            wr <= {(AB+1){1'b0}};
            rd <= {(AB+1){1'b0}};
            settle <= 1'b0;
            over   <= 1'b0;
            head   <= 8'h00;
        end else begin
            head   <= q[rd[AB-1:0]];
            settle <= push | pop | clr;

            if (push && !full) begin
                q[wr[AB-1:0]] <= rx_next[8:1];
                wr <= wr + 1'b1;
            end
            if (push && full) over <= 1'b1;

            if (pop) rd <= rd + 1'b1;
            if (clr) begin
                rd   <= wr;
                over <= 1'b0;
            end
            // Writing 1 to the flag's own bit clears it, the shape
            // UART_STAT and VID_IRQ already use.
            if (io_we && io_a == A_STAT && io_wdata[1]) over <= 1'b0;
        end
    end

    // ------------------------------------------------------ the machine

    reg irq_en;

    assign o_irq = irq_en & avail;

    always @(posedge clk) begin
        if (!rst_n) begin
            rx_sr   <= 11'd0;
            rx_n    <= 4'd0;
            par_err <= 1'b0;
            tmr     <= 10'd0;
            tos     <= 8'd0;
            ts      <= T_IDLE;
            tx_sr   <= 9'd0;
            tx_n    <= 4'd0;
            tx_dat  <= 1'b0;
            tx_err  <= 1'b0;
            irq_en  <= 1'b0;
        end else begin
            // ---- the register file
            // Write-one-to-clear on the two sticky flags, the shape
            // UART_STAT and VID_IRQ already use. Placed ahead of the
            // machine below so a fault raised this very cycle survives
            // being acknowledged in it.
            if (io_we && io_a == A_CTRL) irq_en <= io_wdata[4];
            if (io_we && io_a == A_STAT) begin
                if (io_wdata[2]) par_err <= 1'b0;
                if (io_wdata[4]) tx_err  <= 1'b0;
            end

            // ---- the timer. Every clock edge on the wire restarts it,
            //      so it only ever runs during a gap. Both edges, not
            //      just the falling one: half a period of silence is
            //      already longer than any gap inside a frame.
            if (cf != cf_d) begin
                tmr <= 10'd0;
                tos <= 8'd0;
            end else if (!tmr_100) begin
                tmr <= tmr + 10'd1;
            end

            case (ts)

            // ---------------------------------------------- receiving
            T_IDLE: begin
                if (c_fall) begin
                    rx_sr <= rx_next;
                    if (rx_last) begin
                        rx_n <= 4'd0;
                        if (!rx_ok) par_err <= 1'b1;
                    end else begin
                        rx_n <= rx_n + 4'd1;
                    end
                end else if (rx_n != 4'd0 && tmr_60) begin
                    // Nothing for 60 us with a frame part-received: give
                    // up on it rather than stay out of step forever.
                    rx_n <= 4'd0;
                end

                // A write to KBD_TX starts a transmission. Mid-frame is
                // fine — the inhibit is what a device is required to
                // tolerate, and the abandoned frame is the caller's
                // choice to make.
                if (io_we && io_a == A_TX) begin
                    tx_sr  <= {~(^io_wdata), io_wdata};   // odd parity
                    tx_n   <= 4'd0;
                    rx_n   <= 4'd0;
                    tx_err <= 1'b0;
                    tmr    <= 10'd0;
                    ts     <= T_INH;
                end
            end

            // ------------------------------------ 1. clock low, 100 us
            T_INH: if (tmr_100) begin
                tx_dat <= 1'b1;                  // 2. data low: the start bit
                tmr    <= 10'd0;
                tos    <= 8'd0;
                ts     <= T_RTS;                 // 3. and release the clock
            end

            // --------------- 4. the device answers by clocking, or does not
            T_RTS: begin
                if (c_fall) begin
                    tx_dat <= ~tx_sr[0];         // 5. present the first bit
                    tx_sr  <= {1'b0, tx_sr[8:1]};
                    tx_n   <= 4'd1;
                    ts     <= T_BITS;
                end else if (tmr_60) begin
                    tmr <= 10'd0;
                    tos <= tos + 8'd1;
                    if (tos >= TXTO[7:0]) begin  // ~15 ms and no clock
                        tx_dat <= 1'b0;
                        tx_err <= 1'b1;
                        ts     <= T_IDLE;
                    end
                end
            end

            // ---------------------- eight data bits, then the parity bit
            T_BITS: if (c_fall) begin
                tx_dat <= ~tx_sr[0];
                tx_sr  <= {1'b0, tx_sr[8:1]};
                if (tx_n == 4'd9) begin
                    tx_dat <= 1'b0;              // 9. release: the stop bit
                    ts     <= T_STOP;
                end else begin
                    tx_n <= tx_n + 4'd1;
                end
            end

            // ------------------------------- 10. the device acknowledges
            T_STOP: if (c_fall) begin
                if (dat_in) tx_err <= 1'b1;      // no ack
                ts <= T_ACK;
            end

            // The device holds data low through the ack and releases it
            // afterwards. Going straight back to T_IDLE would read that
            // release as the start of a frame, so wait for the line.
            T_ACK: if (dat_in) begin
                rx_n <= 4'd0;
                ts   <= T_IDLE;
            end

            default: ts <= T_IDLE;

            endcase
        end
    end

    // ------------------------------------------- modifiers, and the chords
    //
    // Ctrl+Shift+Esc resets the machine and Ctrl+Esc asks for a warm
    // restart. **They are decoded here because software cannot be
    // relied on to do it**: a game may take the interrupt vectors,
    // disable interrupts and never read the FIFO, and the board has no
    // reset pin -- so without this the only way out of a wedged machine
    // is the power switch. A reset driven from the byte stream cannot
    // be masked, intercepted or ignored.
    //
    // The state is taken from the arriving bytes rather than the FIFO,
    // and on `push` rather than on a successful enqueue: a key really
    // did go down or come up even if the queue was full and dropped it.
    //
    // $E0 is not consumed here. Left and right Ctrl differ only by that
    // prefix, and treating them as one key is what sw/kdown.asm already
    // does with the same justification -- there is no keypad on this
    // machine, so the shared code cannot be ambiguous.
    //
    // **These bits say "now", and the FIFO says "earlier".** A byte is
    // read out of the queue long after it arrived, so translating a
    // queued character with these would use a shift that may already
    // have been released. Character translation stays with the
    // in-stream state sw/kbd.asm keeps; these are for chords and for
    // games asking what is held this instant.
    reg m_shift, m_ctrl, m_alt, brk_p, warm_l;

    wire [7:0] rxb      = rx_next[8:1];
    wire       is_brk   = (rxb == 8'hF0);
    wire       is_ext   = (rxb == 8'hE0);
    wire       key_byte = push & ~is_brk & ~is_ext;
    wire       chord    = key_byte & ~brk_p & (rxb == 8'h76) & m_ctrl;

    assign o_reset = chord &  m_shift;
    assign o_warm  = chord & ~m_shift;

    always @(posedge clk) begin
        if (!rst_n) begin
            m_shift <= 1'b0;
            m_ctrl  <= 1'b0;
            m_alt   <= 1'b0;
            brk_p   <= 1'b0;
            warm_l  <= 1'b0;
        end else begin
            if (push) begin
                if (is_brk)      brk_p <= 1'b1;
                else if (!is_ext) begin
                    brk_p <= 1'b0;
                    case (rxb)
                        8'h12, 8'h59: m_shift <= ~brk_p;
                        8'h14:        m_ctrl  <= ~brk_p;
                        8'h11:        m_alt   <= ~brk_p;
                        default: ;
                    endcase
                end
            end
            // Set after the acknowledge, so a chord struck in the very
            // cycle a handler clears the flag is not lost -- the shape
            // VID_IRQ and UART_STAT already use.
            if (io_we && io_a == A_MOD && io_wdata[3]) warm_l <= 1'b0;
            if (o_warm) warm_l <= 1'b1;
        end
    end

    // ---------------------------------------------------------- read back

    // KBD_TX is write-only and reads $FF, the same answer the page gives
    // for an address nobody claims.
    always @* begin
        case (io_a)
            A_STAT:  o_rdata = {3'b000, tx_err, txing, par_err, over, avail};
            A_DATA:  o_rdata = head;
            A_CTRL:  o_rdata = {3'b000, irq_en, 4'b0000};
            A_MOD:   o_rdata = {4'b0000, warm_l, m_alt, m_ctrl, m_shift};
            default: o_rdata = 8'hFF;
        endcase
    end

endmodule

`default_nettype wire
