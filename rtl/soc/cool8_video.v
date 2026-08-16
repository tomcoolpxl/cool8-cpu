// cool8_video — the video subsystem: everything behind $FE10-$FE3F and
// $FEC0-$FEFF, plus 64 KB of its own memory and the pins the picture
// comes out of.
//
// The pieces are separately simulated; what lives here is the wiring and
// the one thing that cannot be tested anywhere else — the crossing
// between the two clocks.
//
// ## The clock crossing, in one direction only
//
// The raster runs at 25.125 MHz because a monitor is counting; the rest
// of the machine runs at 8.375 MHz, a third of it, because the part's
// one PLL owns the pin the board clock arrives on (D32, D29). Two
// things have to get from the fast side to the slow one:
// which line to fetch, and when a frame ends.
//
// Both go across as a **toggle**, not a pulse. `o_prefetch` is one pixel
// clock wide — 39.8 ns — and the system clock's period is 119 ns, so a
// pulse would be missed most of the time. A toggle cannot be
// missed; it is synchronised with two flip-flops and turned back into a
// pulse by an edge detector. The line number rides along in a holding
// register that has been stable for three system clocks by the time
// anything reads it.
//
// Nothing crosses the other way on a wire. The mode registers are
// sampled in the pixel domain and the reasoning for that is in
// cool8_pixel; the line buffer and the palette are dual-clock block
// RAMs, which is the arrangement D26 chose.
//
// ## Where the two memories meet
//
// Text maps come from main RAM through `ram_*`, which the SoC arbitrates
// against the CPU. Everything else — patterns, tile maps, bitmaps,
// sprite patterns, blitter source and destination — is in the VRAM
// instantiated here, which the CPU can only reach through cool8_vport.
// That split is D28 and it is what stops a blit from stalling a store.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_video #(
    parameter FONT_FILE = "font.hex",
    parameter FONT_INIT = 1,
    parameter H_TOTAL   = 800
) (
    // ---- system domain
    input  wire        sclk,
    input  wire        srst_n,

    // ---- pixel domain
    input  wire        pclk,
    input  wire        prst_n,

    // ---- the I/O page
    input  wire [7:0]  io_a,
    input  wire        io_rd,
    input  wire        io_we,
    // The write as *asked for*, before the page's own stalls qualify it.
    // Only cool8_vport takes it, and only to decide whether to stall —
    // see cool8_soc for why the two cannot be the same signal.
    input  wire        io_wreq,
    input  wire [7:0]  io_wdata,
    output wire        o_sel,
    output wire        o_dp_sel,       // ...and it is the VRAM data port
    output wire [7:0]  o_rdata,        // captured on launch by the SoC
    output wire [7:0]  o_dout,         // the data port's byte, live
    output wire        o_stall,

    // ---- main RAM, for text maps. Arbitrated in cool8_soc.
    output wire        ram_req,
    output wire [15:0] ram_addr,
    input  wire        ram_gnt,
    input  wire        ram_rvalid,
    input  wire [7:0]  ram_rdata,

    // ---- the pins
    output wire [11:0] rgb,
    output wire        hsync_n,
    output wire        vsync_n,

    output wire        o_irq
);

    // -------------------------------------------------------- the raster

    wire [9:0] x, y, prefetch_y;
    wire       visible, vblank, prefetch, vblank_start;

    cool8_vga u_vga (
        .clk(pclk), .rst_n(prst_n),
        .x(x), .y(y), .visible(visible),
        .hsync_n(hsync_n), .vsync_n(vsync_n), .vblank(vblank),
        .o_prefetch(prefetch), .o_prefetch_y(prefetch_y),
        .o_vblank_start(vblank_start)
    );

    // ------------------------------------------------------ the crossing

    reg        pf_tog, vb_tog;
    reg [9:0]  pf_y;

    always @(posedge pclk) begin
        if (!prst_n) begin
            pf_tog <= 1'b0;
            vb_tog <= 1'b0;
            pf_y   <= 10'd0;
        end else begin
            if (prefetch) begin
                pf_y   <= prefetch_y;
                pf_tog <= ~pf_tog;
            end
            if (vblank_start) vb_tog <= ~vb_tog;
        end
    end

    reg [2:0] pf_s, vb_s;
    reg [9:0] line_y;

    wire line_start = pf_s[2] ^ pf_s[1];

    // The line number is captured one edge *ahead* of the pulse that
    // announces it, so it is already the right value when the pulse
    // arrives. Capturing both on the same edge looks equivalent and is
    // not: `line_y` would still hold the previous line's number
    // throughout the cycle its consumers act on, and the display would
    // change bank one scanline late — which is a picture whose every
    // character row draws its first line from the row above it.
    wire ls_early   = pf_s[1] ^ pf_s[0];
    wire frame_start = vb_s[2] ^ vb_s[1];

    always @(posedge sclk) begin
        if (!srst_n) begin
            pf_s   <= 3'b000;
            vb_s   <= 3'b000;
            line_y <= 10'd0;
        end else begin
            pf_s <= {pf_s[1:0], pf_tog};
            vb_s <= {vb_s[1:0], vb_tog};
            // Stable for two system clocks by now: the toggle it arrived
            // with is one synchroniser stage from being seen.
            if (ls_early) line_y <= pf_y;
        end
    end

    // ------------------------------------------------------- the modes

    wire        disp_en, hdouble, vdouble, cur_on;
    wire [1:0]  engine, bpp_log;
    wire [15:0] base, stride, pat_base, map_org;
    wire [9:0]  scrl_x, scrl_y, vactive, vstart;
    wire [10:0] hactive, hstart;
    wire [7:0]  border, pal_entry;
    wire [6:0]  cur_x;
    wire [15:0] disp_base;
    wire [4:0]  cur_y;
    wire        pal_we, pal_half;
    wire        vreg_sel;
    wire [7:0]  vreg_rdata;

    cool8_vregs u_vregs (
        .clk(sclk), .rst_n(srst_n),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wdata(io_wdata),
        .o_sel(vreg_sel), .o_rdata(vreg_rdata),
        .disp_en(disp_en), .engine(engine), .bpp_log(bpp_log),
        .hdouble(hdouble), .vdouble(vdouble),
        .base(base), .disp_base(disp_base),
        .stride(stride), .pat_base(pat_base),
        .map_org(map_org),
        .scrl_x(scrl_x), .scrl_y(scrl_y), .border(border),
        .hactive(hactive), .hstart(hstart),
        .vactive(vactive), .vstart(vstart),
        .cur_x(cur_x), .cur_y(cur_y), .cur_on(cur_on),
        .pal_we(pal_we), .pal_entry(pal_entry), .pal_half(pal_half),
        .line_start(line_start), .line_y(line_y),
        .frame_start(frame_start), .o_irq(o_irq)
    );

    // --------------------------------------------------------- the VRAM

    wire        dsp_req, dsp_gnt, dsp_rvalid;
    wire [15:1] dsp_addr;
    wire        cpu_req, cpu_gnt, cpu_rvalid, cpu_we;
    wire [15:1] cpu_addr;
    wire [15:0] cpu_wdata;
    wire [3:0]  cpu_mask;
    wire [15:0] vram_rdata;

    wire        spr_req, spr_gnt, spr_rvalid;
    wire [15:1] spr_addr;
    wire        sprite_sel;
    wire [7:0]  sprite_rdata;
    wire        sb_we;
    wire [10:0] sb_addr;
    wire [9:0]  sb_data;
    wire [3:0]  spr_bank;

    wire        blt_req, blt_gnt, blt_rvalid, blt_we;
    wire [15:1] blt_addr;
    wire [15:0] blt_wdata;
    wire [3:0]  blt_mask;
    wire        pxp_sel;
    wire [7:0]  pxp_rdata;

    cool8_vram u_vram (
        .clk(sclk), .rst_n(srst_n),
        .dsp_req(dsp_req), .dsp_addr(dsp_addr),
        .dsp_gnt(dsp_gnt), .dsp_rvalid(dsp_rvalid),
        .spr_req(spr_req), .spr_addr(spr_addr),
        .spr_gnt(spr_gnt), .spr_rvalid(spr_rvalid),
        .cpu_req(cpu_req), .cpu_addr(cpu_addr), .cpu_wdata(cpu_wdata),
        .cpu_we(cpu_we), .cpu_mask(cpu_mask),
        .cpu_gnt(cpu_gnt), .cpu_rvalid(cpu_rvalid),
        .blt_req(blt_req), .blt_addr(blt_addr), .blt_wdata(blt_wdata),
        .blt_we(blt_we), .blt_mask(blt_mask),
        .blt_gnt(blt_gnt), .blt_rvalid(blt_rvalid),
        .rdata(vram_rdata)
    );

    cool8_sprite u_spr (
        .clk(sclk), .rst_n(srst_n),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wdata(io_wdata),
        .o_sel(sprite_sel), .o_rdata(sprite_rdata),
        .line_start(line_start), .line_y(line_y),
        .frame_start(frame_start),
        .vr_req(spr_req), .vr_addr(spr_addr), .vr_gnt(spr_gnt),
        .vr_rvalid(spr_rvalid), .vr_rdata(vram_rdata),
        .sb_we(sb_we), .sb_addr(sb_addr), .sb_data(sb_data),
        .o_bank(spr_bank)
    );

    cool8_pixport u_pxp (
        .clk(sclk), .rst_n(srst_n),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wdata(io_wdata),
        .o_sel(pxp_sel), .o_rdata(pxp_rdata),
        .bpp_log(bpp_log), .base(base), .stride(stride),
        .vr_req(blt_req), .vr_addr(blt_addr), .vr_wdata(blt_wdata),
        .vr_we(blt_we), .vr_mask(blt_mask),
        .vr_gnt(blt_gnt), .vr_rvalid(blt_rvalid), .vr_rdata(vram_rdata)
    );

    wire       vport_sel, vport_stall;
    wire [7:0] vport_rdata;

    // One block on this page can hold the bus: the VRAM data port, while
    // its prefetch is still out. The pixel port used to be the other one
    // and is not any more — PIX_DATA is write-only and a write never
    // waits, so there is nothing left for it to stall for.
    assign o_stall = vport_stall;

    cool8_vport u_vport (
        .clk(sclk), .rst_n(srst_n),
        .io_a(io_a), .io_rd(io_rd), .io_we(io_we), .io_wreq(io_wreq),
        .io_wdata(io_wdata),
        .o_sel(vport_sel), .o_dp_sel(o_dp_sel), .o_rdata(vport_rdata),
        .o_dout(o_dout), .o_stall(vport_stall),
        .stride(stride),
        .vram_req(cpu_req), .vram_addr(cpu_addr), .vram_wdata(cpu_wdata),
        .vram_we(cpu_we), .vram_mask(cpu_mask),
        .vram_gnt(cpu_gnt), .vram_rvalid(cpu_rvalid),
        .vram_rdata(vram_rdata)
    );

    // ---------------------------------------------------- fetch and pixel

    wire        lb_we, lb_bank, read_bank;
    wire [7:0]  lb_addr;
    wire [15:0] lb_data;

    cool8_fetch u_fetch (
        .clk(sclk), .rst_n(srst_n),
        .line_start(line_start), .line_y(line_y),
        .frame_start(frame_start),
        .disp_en(disp_en), .engine(engine),
        .hdouble(hdouble), .vdouble(vdouble),
        // the display's base, not the drawing one: D92 splits them so
        // a hidden page can be drawn while a finished one is scanned
        .base(disp_base), .stride(stride), .pat_base(pat_base),
        .map_org(map_org),
        .scrl_y(scrl_y), .vactive(vactive), .vstart(vstart),
        .ram_req(ram_req), .ram_addr(ram_addr), .ram_gnt(ram_gnt),
        .ram_rvalid(ram_rvalid), .ram_rdata(ram_rdata),
        .vr_req(dsp_req), .vr_addr(dsp_addr), .vr_gnt(dsp_gnt),
        .vr_rvalid(dsp_rvalid), .vr_rdata(vram_rdata),
        .lb_we(lb_we), .lb_bank(lb_bank), .lb_addr(lb_addr),
        .lb_data(lb_data),
        .o_read_bank(read_bank)
    );

    wire [7:0]  pal_index;
    wire [11:0] pal_rgb;

    cool8_pal u_pal (
        .sclk(sclk), .we(pal_we), .entry(pal_entry), .half(pal_half),
        .wdata(io_wdata),
        .pclk(pclk), .index(pal_index), .rgb(pal_rgb)
    );

    cool8_pixel #(.FONT_FILE(FONT_FILE), .FONT_INIT(FONT_INIT),
                  .H_TOTAL(H_TOTAL))
    u_pixel (
        .pclk(pclk), .prst_n(prst_n),
        .x(x), .y(y), .visible(visible), .rgb(rgb),
        .pal_index(pal_index), .pal_rgb(pal_rgb),
        .sclk(sclk),
        .lb_we(lb_we), .lb_bank(lb_bank), .lb_addr(lb_addr),
        .lb_data(lb_data), .read_bank(read_bank),
        .sb_we(sb_we), .sb_addr(sb_addr), .sb_data(sb_data),
        .spr_bank(spr_bank),
        .disp_en(disp_en), .engine(engine), .bpp_log(bpp_log),
        .hdouble(hdouble), .vdouble(vdouble), .border(border),
        .hactive(hactive), .hstart(hstart),
        .vactive(vactive), .vstart(vstart),
        .scrl_x(scrl_x), .scrl_y(scrl_y),
        .cur_x(cur_x), .cur_y(cur_y), .cur_on(cur_on)
    );

    // --------------------------------------------------------- the decode

    assign o_sel   = vreg_sel | vport_sel | pxp_sel | sprite_sel;
    assign o_rdata = vport_sel  ? vport_rdata  :
                     pxp_sel    ? pxp_rdata    :
                     sprite_sel ? sprite_rdata : vreg_rdata;

    wire _unused = &{1'b0, vblank, 1'b0};

endmodule

`default_nettype wire
