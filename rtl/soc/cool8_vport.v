// cool8_vport — the CPU's window onto video RAM: $FE26-$FE29, and the
// data port aliased across $FEC0-$FEFF.
//
// VRAM is a separate address space (D28) and the CPU reaches it through
// an address register, a step and a data register. Writing or reading
// the data register moves the address on by the step, so a run of bytes
// is a straight loop with no address arithmetic between the stores —
// which is the fastest shape an 8-bit CPU has.
//
//   $FE26  VRAM_ADDR_L
//   $FE27  VRAM_ADDR_H
//   $FE28  VRAM_STEP    [2:0] amount, [3] decrement
//   $FE29  VRAM_DATA    auto-advances; a read has a side effect
//
// ## Why there is a prefetch, and why it is not optional
//
// The I/O page has one timing shape and cannot negotiate: an access is
// launched in one cycle and answered in the next (cool8_soc.v, and
// docs/03-microarchitecture.md section 6.3). A VRAM read cannot meet
// that — it has to win the arbiter and then wait a cycle for DATAOUT,
// which is two cycles at best and more when the display is fetching.
//
// So the port keeps the byte at the current address in a register,
// fetched ahead of time. A read of VRAM_DATA hands over the register,
// advances the address and starts the next fetch. That is the same
// arrangement every VDP with a data port has used, and the reason those
// chips all want a dummy read after setting the address.
//
// When the byte is not ready anyway — the first read after a run of
// writes, or a fetch that lost several cycles to the display — the port
// raises `o_stall` and the SoC holds mem_ready low. The core tolerates
// arbitrary wait states and sim/cosim.py proves it against randomised
// ones, so this is correct rather than merely usual.
//
// **A prefetch is issued after a read and after an address write, never
// after a write of data.** Writing is the bulk direction — loading a
// tile set, clearing a buffer — and prefetching after each one would
// double the port's VRAM traffic to serve a read that is not coming.
// The cost is one stall on the first read after a write burst.
//
// ## No cached word
//
// A 16-bit fetch straddles two byte addresses, so holding it would serve
// two sequential reads from one access. It is not done: the blitter and
// the CPU write the same memory, and a cache with no invalidation from
// the other three requesters would return a stale byte after any blit
// that touched it. One fetch per read, and the bandwidth is there.
//
// ## The $FEC0 alias
//
// Every address in $FEC0-$FEFF is VRAM_DATA. That is not for the CPU —
// it makes no difference which address a store uses — it is for the
// loader and for tools/cool8screen.py, whose READ command walks
// *consecutive* addresses. Without it, dumping VRAM would mean one frame
// per byte; with it, one frame per 64. VRAM would otherwise be invisible
// to the two tools that made M4 tractable (D28).
//
// It costs less logic than decoding the address precisely would.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_vport (
    input  wire        clk,
    input  wire        rst_n,

    // ---- the I/O page. `io_rd` is the launch pulse of a read, already
    //      qualified so a read's side effect happens once; `io_we` is a
    //      write, which the core holds asserted until it is taken.
    input  wire [7:0]  io_a,
    input  wire        io_rd,
    input  wire        io_we,
    input  wire [7:0]  io_wdata,

    output wire        o_sel,           // this block claims io_a
    output wire        o_dp_sel,        // ...and it is the data port
    output reg  [7:0]  o_rdata,         // ADDR_L/H and STEP, combinational
    output wire [7:0]  o_dout,          // the data port's byte, registered
    output wire        o_stall,         // hold mem_ready low

    // VID_STRIDE, so one step code follows the mode's row pitch
    input  wire [15:0] stride,

    // ---- the VRAM arbiter's CPU port
    output wire        vram_req,
    output wire [15:1] vram_addr,
    output wire [15:0] vram_wdata,
    output wire        vram_we,
    output wire [3:0]  vram_mask,
    input  wire        vram_gnt,
    input  wire        vram_rvalid,
    input  wire [15:0] vram_rdata
);

    localparam [7:0] A_ADDR_L = 8'h26,
                     A_ADDR_H = 8'h27,
                     A_STEP   = 8'h28,
                     A_DATA   = 8'h29;

    // ------------------------------------------------------- the decode

    wire alias_sel = (io_a[7:6] == 2'b11);          // $FEC0-$FEFF
    wire reg_sel   = (io_a == A_ADDR_L) | (io_a == A_ADDR_H) |
                     (io_a == A_STEP)   | (io_a == A_DATA);

    assign o_sel    = reg_sel | alias_sel;
    assign o_dp_sel = (io_a == A_DATA) | alias_sel;

    wire dp_rd = io_rd & o_dp_sel;
    wire dp_we = io_we & o_dp_sel;

    // ---------------------------------------------------------- state

    reg [15:0] addr;
    reg [3:0]  step;

    reg [7:0]  pf;                     // the byte at `addr`
    reg        pf_valid;               // ...and whether it is really there
    reg        pf_want;                // a fetch is needed
    reg        pf_infl;                // ...and has been granted, data due
    reg        pf_half;                // which half of the word to take
    reg        pf_stale;               // the one in flight is for an address
                                       // that has since moved

    reg [15:0] wr_addr;                // one posted write
    reg [7:0]  wr_data;
    reg        wr_pend;

    reg        rd_hold;                // a read is waiting for the prefetch

    // ------------------------------------------------------ the advance

    wire [15:0] step_val = (step[2:0] == 3'd0) ? 16'd0   :
                           (step[2:0] == 3'd1) ? 16'd1   :
                           (step[2:0] == 3'd2) ? 16'd2   :
                           (step[2:0] == 3'd3) ? 16'd4   :
                           (step[2:0] == 3'd4) ? 16'd8   :
                           (step[2:0] == 3'd5) ? 16'd16  :
                           (step[2:0] == 3'd6) ? 16'd256 : stride;

    wire [15:0] addr_next = step[3] ? (addr - step_val) : (addr + step_val);

    // ------------------------------------------------- the CPU handshake
    //
    // A read completes on the first cycle the prefetched byte is there,
    // which may be the launch cycle or several later. `rd_hold` carries
    // the access across the gap, because `io_rd` is a single pulse — the
    // launch does not come again while mem_ready is low.

    wire rd_active = dp_rd | rd_hold;
    wire rd_done   = rd_active &  pf_valid;
    wire rd_wait   = rd_active & ~pf_valid;

    // A second write while the first is still queued has to wait. The
    // core holds `io_we` asserted across the stall, so this resolves
    // itself the cycle the queue empties, and the `~wr_pend` guard is
    // what stops it being taken twice.
    wire we_wait   = dp_we & wr_pend;

    assign o_stall = rd_wait | we_wait;

    // Any access that moves the address invalidates the prefetch.
    wire addr_wr    = io_we & ((io_a == A_ADDR_L) | (io_a == A_ADDR_H));
    wire advance    = rd_done | (dp_we & ~wr_pend);
    wire addr_moves = addr_wr | advance;

    // ------------------------------------------------- the VRAM request
    //
    // A queued write goes first. It is the only thing the CPU can be
    // blocked on, and a prefetch has nobody waiting for it yet.

    assign vram_req   = wr_pend | (pf_want & ~pf_infl);
    assign vram_we    = wr_pend;
    assign vram_addr  = wr_pend ? wr_addr[15:1] : addr[15:1];
    assign vram_wdata = {wr_data, wr_data};      // both halves; the mask picks
    assign vram_mask  = wr_addr[0] ? 4'b1100 : 4'b0011;

    wire pf_gnt = vram_gnt & ~wr_pend;           // the grant was ours

    // --------------------------------------------------------- the port

    always @(posedge clk) begin
        if (!rst_n) begin
            addr     <= 16'h0000;
            step     <= 4'd1;          // +1: the useful default
            pf       <= 8'h00;
            pf_valid <= 1'b0;
            pf_want  <= 1'b0;
            pf_infl  <= 1'b0;
            pf_half  <= 1'b0;
            wr_addr  <= 16'h0000;
            wr_data  <= 8'h00;
            wr_pend  <= 1'b0;
            rd_hold  <= 1'b0;
            pf_stale <= 1'b0;
        end else begin
            rd_hold <= rd_wait;

            // ---- the register file
            if (io_we && io_a == A_STEP) step <= io_wdata[3:0];

            // ---- the address
            if (addr_wr) begin
                if (io_a == A_ADDR_L) addr[7:0]  <= io_wdata;
                else                  addr[15:8] <= io_wdata;
            end else if (advance) begin
                addr <= addr_next;
            end

            // ---- the prefetch out
            //
            // Written as one priority chain rather than several
            // independent `if`s, because two of these fire in the same
            // cycle often enough to matter and the last assignment would
            // otherwise silently win. An address written in the very
            // cycle a fetch is granted has to keep its request *and*
            // discard the fetch, and only stating the order gets that
            // right.
            if (addr_moves) begin
                pf_valid <= 1'b0;
                // Only a read arms the next fetch. A write burst would
                // otherwise spend a VRAM access per byte on data nobody
                // asked for; the cost is one stall on the read that
                // follows the burst.
                pf_want  <= addr_wr | rd_done;
            end else if (pf_gnt) begin
                pf_want  <= 1'b0;
            end else if (rd_wait && !pf_want && !pf_infl) begin
                // The first read after a write burst: nothing armed and
                // nothing in flight, so arm it now and stall.
                pf_want  <= 1'b1;
            end

            if (pf_gnt) begin
                pf_infl <= 1'b1;
                pf_half <= addr[0];
            end

            // A fetch already granted, or granted this very cycle, was
            // issued against the address as it stood. If the address
            // moves now, that data is for somewhere else and must not be
            // allowed to land as valid.
            if (addr_moves && (pf_infl || pf_gnt)) pf_stale <= 1'b1;

            // ---- ...and back
            if (vram_rvalid) begin
                pf      <= pf_half ? vram_rdata[15:8] : vram_rdata[7:0];
                pf_infl <= 1'b0;
                pf_stale <= 1'b0;
                if (!pf_stale && !addr_moves) pf_valid <= 1'b1;
            end

            // ---- the posted write
            if (vram_gnt && wr_pend) wr_pend <= 1'b0;
            if (dp_we && !wr_pend) begin
                wr_addr <= addr;
                wr_data <= io_wdata;
                wr_pend <= 1'b1;
            end
        end
    end

    // The byte goes out of `pf` directly, and the margin is structural
    // rather than lucky. A read completes in cycle N; the SoC's mem_ready
    // is high in N+1 and that is when the core samples. The next fetch is
    // armed at the end of N, so its request stands in N+1, its earliest
    // grant is N+1, and rvalid is always the cycle after a grant — so the
    // soonest `pf` can change is the end of N+2.
    //
    // Capturing it into a second register was tried and is wrong: the
    // capture lands at the end of N, which is correct for an unstalled
    // read and a cycle late for a stalled one, and stalled reads are
    // exactly the case that needed the care.
    assign o_dout = pf;

    // ADDR_L, ADDR_H and STEP are read back through the SoC's ordinary
    // registered path. The data port is not: its byte is already a
    // register, so it goes straight out on `o_dout` and closes no loop
    // through the address.
    always @* begin
        case (io_a)
            A_ADDR_L: o_rdata = addr[7:0];
            A_ADDR_H: o_rdata = addr[15:8];
            A_STEP:   o_rdata = {4'h0, step};
            default:  o_rdata = o_dout;
        endcase
    end

endmodule

`default_nettype wire
