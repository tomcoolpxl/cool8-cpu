// cool8_pixport — plot a pixel by coordinate. $FE34-$FE38.
//
// Write X, write Y, write a colour, and the pixel appears. X then
// advances on its own, so a horizontal span is one store per pixel and
// the address arithmetic happens here rather than in the CPU's four
// registers.
//
// ## Why this survived when the blitter did not
//
// The M5 gate measured the video engine at 1386 LUT4 against an estimate
// of 1051, and a blitter and a sprite engine on top of that did not fit
// the part — 5438 logic cells against the 5280 that exist. The sprite
// engine was kept, because tiles plus sprites is a machine that draws
// nothing per frame (section 5.3) and is the one arrangement that needs
// no acceleration at all.
//
// What that leaves is the bitmap modes, and they would be close to
// unusable without this. Plotting a 4 bpp pixel through VRAM_DATA by
// hand is: compute an address with a multiply the CPU has to sequence,
// set it, read a byte, mask a nibble, write it back — about twenty
// cycles. Here it is five stores for the first pixel of a span and one
// for every pixel after it, and at 4 and 8 bpp there is no read at all,
// because a pixel is a whole number of nibbles and MASKWREN writes
// nibbles.
//
// So this is not a small blitter. It is the address arithmetic, which is
// the part the CPU is genuinely bad at: `y * stride` on an 8-bit machine
// is a sequenced multiply and here it is one expression.
//
// **It is not a DSP block, although it was written expecting to be.**
// `synth_ice40 -dsp` is passed and `ice40_dsp` checks this multiply and
// declines it -- it maps when the module is synthesised alone and not
// when the design is flattened around it. Chased in 2026-08, and the
// answer is to leave it: **the whole multiply costs 8 logic cells**,
// measured by replacing it with a shift and rebuilding (5183 against
// 5175). yosys is already reducing it far below a general 11x16
// multiplier, so a DSP could buy 8 cells and a hard primitive
// dependency. Do not re-open this without a measurement that beats 8.
//
// ## The byte is the unit
//
// A pixel is at most eight bits and never straddles a byte, so the merge
// happens in eight bits and the result is written into *both* halves of
// the 16-bit word with MASKWREN choosing which one lands — the same
// trick cool8_spram uses for the CPU's byte port. Doing it in sixteen
// bits instead is what made the blitter twice the size it should have
// been.
//
//     sb  = (x << bpp_log) & 7     the pixel's offset inside its byte
//     hi  = {addr[0], ~sb}         its top bit inside the word, as wiring
//
// ## PIX_DATA is write-only
//
// It was readable, and reading it cost two more variable shifters — one
// to bring the pixel down out of its byte and one to mask it — plus a
// stall path, a state and a holding register, because the byte has to be
// fetched before the answer exists.
//
// Nothing wanted it. The port is an *output* device: the thing an 8-bit
// CPU is bad at is working out where a pixel lives, and once the address
// arithmetic is in hardware the only remaining reason to read a pixel
// back is collision detection, which section 5.11 already answers with
// software bounding-box tests. Software that genuinely needs to read a
// surface has VRAM_ADDR/VRAM_DATA, which reads bytes and does not stall
// on arithmetic it did not need.
//
// So a read of $FE38 returns $FF, the same answer the page gives for an
// address nobody claims, and this block never holds the bus at all.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_pixport (
    input  wire        clk,
    input  wire        rst_n,

    // ---- the I/O page, $FE34-$FE38
    input  wire [7:0]  io_a,
    input  wire        io_rd,
    input  wire        io_we,
    input  wire [7:0]  io_wdata,
    output wire        o_sel,
    output reg  [7:0]  o_rdata,

    // ---- the surface: the display's own base and pitch
    input  wire [1:0]  bpp_log,
    input  wire [15:0] base,
    input  wire [15:0] stride,

    // ---- the VRAM arbiter's blitter port
    output wire        vr_req,
    output wire [15:1] vr_addr,
    output wire [15:0] vr_wdata,
    output wire        vr_we,
    output wire [3:0]  vr_mask,
    input  wire        vr_gnt,
    input  wire        vr_rvalid,
    input  wire [15:0] vr_rdata
);

    localparam [7:0] A_PXL = 8'h34,            //: PIX_X_L      plot X, low
                     A_PXH = 8'h35,            //: PIX_X_H      plot X, high
                     A_PYL = 8'h36,            //: PIX_Y_L      plot Y, low
                     A_PYH = 8'h37,            //: PIX_Y_H      plot Y, high
                     A_PDAT = 8'h38;           //: PIX_DATA     write plots the pixel at X,Y

    localparam [2:0] S_IDLE = 3'd0, S_MUL = 3'd1, S_RD = 3'd2,
                     S_WR   = 3'd3, S_END = 3'd4;

    reg [10:0] pix_x, pix_y;
    reg [7:0]  wdat;
    reg        go;
    reg [2:0]  st;

    reg [15:0] a_byte;
    reg [7:0]  old_b;
    reg        req_r, we_r;
    reg [15:0] addr_r, wdata_r;
    reg [3:0]  mask_r;

    assign vr_req   = req_r;
    assign vr_we    = we_r;
    assign vr_addr  = addr_r[15:1];
    assign vr_wdata = wdata_r;
    assign vr_mask  = mask_r;

    assign o_sel   = (io_a >= A_PXL) && (io_a <= A_PDAT);

    wire wr = io_we & o_sel;

    // ----------------------------------------------------- the geometry

    wire [1:0]  pshift = 2'd3 - bpp_log;
    wire [3:0]  bpp    = 4'd1 << bpp_log;

    // 8 logic cells, measured -- not the SB_MAC16 the header once
    // claimed. It is still the difference between a pixel port and a
    // novelty; it is just cheaper than anyone thought.
    wire [31:0] mul_r  = {5'd0, pix_y} * stride;

    wire [2:0]  sb     = (pix_x << bpp_log) & 3'd7;
    wire [3:0]  b_hi   = {a_byte[0], ~sb};
    wire [3:0]  b_lo   = b_hi + 4'd1 - {2'd0, bpp[3:2], bpp[1:0]};

    // The colour, pushed up against the top of a byte, and the mask that
    // covers it there. Both are four-way muxes on the depth, not shifts.
    wire [7:0] top   = (bpp_log == 2'd0) ? {wdat[0],   7'd0} :
                       (bpp_log == 2'd1) ? {wdat[1:0], 6'd0} :
                       (bpp_log == 2'd2) ? {wdat[3:0], 4'd0} : wdat;
    wire [7:0] tmask = (bpp_log == 2'd0) ? 8'h80 :
                       (bpp_log == 2'd1) ? 8'hC0 :
                       (bpp_log == 2'd2) ? 8'hF0 : 8'hFF;

    wire [7:0] new_b = (old_b & ~(tmask >> sb)) | (top >> sb);

    // At 4 and 8 bpp the field is whole nibbles, so the mask covers it
    // exactly and nothing has to be read first.
    wire native = (bpp_log >= 2'd2);

    function [3:0] nibbles;
        input [3:0] h;
        input [3:0] l;
        nibbles = (h[3:2] == l[3:2]) ? (4'b0001 << h[3:2])
                                     : ((4'b0001 << h[3:2]) |
                                        (4'b0001 << l[3:2]));
    endfunction

    // ---------------------------------------------------------- the port

    always @(posedge clk) begin
        if (!rst_n) begin
            pix_x <= 11'd0; pix_y <= 11'd0;
            wdat <= 8'd0;
            go <= 1'b0;
            st <= S_IDLE; a_byte <= 16'd0; old_b <= 8'd0;
            req_r <= 1'b0; we_r <= 1'b0; addr_r <= 16'd0;
            wdata_r <= 16'd0; mask_r <= 4'd0;
        end else begin
            if (req_r & vr_gnt) req_r <= 1'b0;

            if (wr) begin
                case (io_a)
                    A_PXL: pix_x[7:0]  <= io_wdata;
                    A_PXH: pix_x[10:8] <= io_wdata[2:0];
                    A_PYL: pix_y[7:0]  <= io_wdata;
                    A_PYH: pix_y[10:8] <= io_wdata[2:0];
                    A_PDAT: begin
                        wdat  <= io_wdata;
                        go    <= 1'b1;
                    end
                    default: ;
                endcase
            end

            case (st)
                S_IDLE: if (go) begin
                    go <= 1'b0;
                    st <= S_MUL;
                end

                S_MUL: begin
                    a_byte <= base + mul_r[15:0] +
                              ({5'd0, pix_x} >> pshift);
                    st     <= native ? S_WR : S_RD;
                end

                // 1 and 2 bpp only: the field is narrower than a nibble,
                // so MASKWREN cannot cover it exactly and the byte around
                // it has to be read first. 4 and 8 bpp skip this entirely.
                S_RD: begin
                    if (!req_r) begin
                        req_r  <= 1'b1;
                        we_r   <= 1'b0;
                        addr_r <= a_byte;
                    end
                    if (vr_rvalid) begin
                        old_b <= a_byte[0] ? vr_rdata[15:8] : vr_rdata[7:0];
                        st    <= S_WR;
                    end
                end

                S_WR: begin
                    if (!req_r) begin
                        req_r   <= 1'b1;
                        we_r    <= 1'b1;
                        addr_r  <= a_byte;
                        // Both halves carry the byte; the mask decides
                        // which one lands, and which nibbles of it.
                        wdata_r <= {new_b, new_b};
                        mask_r  <= nibbles(b_hi, b_lo);
                        st      <= S_END;
                    end
                end

                S_END: begin
                    pix_x <= pix_x + 11'd1;
                    st    <= S_IDLE;
                end

                default: st <= S_IDLE;
            endcase
        end
    end

    always @* begin
        case (io_a)
            A_PXL:   o_rdata = pix_x[7:0];
            A_PXH:   o_rdata = {5'b00000, pix_x[10:8]};
            A_PYL:   o_rdata = pix_y[7:0];
            A_PYH:   o_rdata = {5'b00000, pix_y[10:8]};
            // PIX_DATA is write-only — see the header.
            default: o_rdata = 8'hFF;
        endcase
    end

    wire _unused = &{1'b0, mul_r[31:16], io_rd, 1'b0};

endmodule

`default_nettype wire
