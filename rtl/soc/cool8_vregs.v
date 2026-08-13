// cool8_vregs — the video register file, $FE10-$FE25, and the mode
// presets behind it.
//
// docs/04-system.md section 4.2 is the map. Everything here is a
// flip-flop and a decode; the interesting parts are the three places
// where a value is *derived* rather than stored, because each of those
// is a register the design does not have to carry.
//
// ## The modes are presets, not hardware
//
// `VID_MODE` is a four-bit preset number that loads `VID_CTRL`,
// `VID_BASE`, `VID_STRIDE` and the vertical extent, and nothing else in
// the machine knows a mode number afterwards — the fetch engine and the
// pixel stage read the registers. Software may override any of them
// after a mode is loaded, which is what makes a 288-line bitmap or a
// 96-column text screen possible without new gates.
//
// Presets $7-$F load nothing. That is the way to change bit 7, display
// enable, without disturbing registers software has already tuned.
//
// ## Three derived values
//
//   the image width   `VID_STRIDE` is the row pitch in bytes, so the
//                     image is `stride * 8 / bpp` pixels wide and there
//                     is no width register. Modes 5 and 6 are bordered
//                     precisely because their pitch is shorter than the
//                     screen
//   the centring      the border is split evenly, so `hstart` is half
//                     the difference. A mode is centred by arithmetic
//                     rather than by a preset constant
//   the palette half  `PAL_IDX` counts entries, not bytes. Section 4.2
//                     called it a byte index 0-511, which does not fit
//                     in the eight-bit register it is; the half within
//                     an entry is implicit, advances with each write of
//                     `PAL_DATA` and is reset by writing `PAL_IDX`
//
// The one value that could not be derived is the vertical extent: 192
// lines in mode 5 against 240 in mode 6 is not visible in anything else
// the registers hold, and nothing in VRAM says where a bitmap stops. It
// is an internal register loaded by the preset — not software-visible,
// which is what section 5.11 traded away when it dropped the
// programmable viewport.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_vregs (
    input  wire        clk,
    input  wire        rst_n,

    // ---- the I/O page, $FE10-$FE25
    input  wire [7:0]  io_a,
    input  wire        io_rd,          // launch pulse; a read's side effect
    input  wire        io_we,
    input  wire [7:0]  io_wdata,
    output wire        o_sel,
    output reg  [7:0]  o_rdata,

    // ---- what the engines read
    output wire        disp_en,
    output wire [1:0]  engine,         // 0 text, 1 tile, 2 bitmap
    output wire [1:0]  bpp_log,        // 0=1bpp, 1=2, 2=4, 3=8
    output wire        hdouble,
    output wire        vdouble,
    output wire [15:0] base,
    output wire [15:0] stride,
    output wire [15:0] pat_base,
    // Where the text/tile map starts, as opposed to which row of it is
    // displayed first. See the wrap in cool8_fetch.v.
    output wire [15:0] map_org,
    output wire [9:0]  scrl_x,
    output wire [9:0]  scrl_y,
    output wire [7:0]  border,

    // Derived, in logical pixels — see the header.
    output wire [10:0] hactive,
    output wire [10:0] hstart,
    output wire [9:0]  vactive,        // raster lines
    output wire [9:0]  vstart,

    // ---- the cursor
    output wire [6:0]  cur_x,
    output wire [4:0]  cur_y,
    output wire        cur_on,         // enabled, and lit this frame

    // ---- the palette write port
    output wire        pal_we,
    output wire [7:0]  pal_entry,
    output wire        pal_half,

    // ---- the raster, carried across from the pixel domain coherently
    input  wire        line_start,
    input  wire [9:0]  line_y,
    input  wire        frame_start,
    output wire        o_irq
);

    localparam [7:0] A_MODE = 8'h10,           //: VID_MODE     screen mode, low nibble
                     A_CTRL = 8'h11,           //: VID_CTRL     display enable, sprite enable, blanking
                     A_BASEL = 8'h12,          //: VID_BASE_L   character/bitmap base, low
                     A_BASEH = 8'h13,          //: VID_BASE_H   character/bitmap base, high
                     A_STRDL = 8'h14,          //: VID_STRIDE_L bytes per row, low
                     A_STRDH = 8'h15,          //: VID_STRIDE_H bytes per row, high
                     A_SCXL = 8'h16,           //: VID_SCX_L    horizontal scroll, low
                     A_SCXH = 8'h17,           //: VID_SCX_H    horizontal scroll, high
                     A_SCYL = 8'h18,           //: VID_SCY_L    vertical scroll, low
                     A_SCYH = 8'h19,           //: VID_SCY_H    vertical scroll, high
                     A_BORDER = 8'h1A,         //: VID_BORDER   border colour index
                     A_RASTER = 8'h1B,         //: VID_RASTER   current raster line, read-only
                     A_RCMP = 8'h1C,           //: VID_RCMP     raster line to compare against
                     A_IRQ = 8'h1D,            //: VID_IRQ      interrupt enable and acknowledge
                     A_PALIDX = 8'h1E,         //: PAL_IDX      palette entry to address
                     A_PALDAT = 8'h1F,         //: PAL_DATA     that entry's colour
                     A_PATL = 8'h20,           //: VID_PAT_L    pattern/tile base, low
                     A_PATH = 8'h21,           //: VID_PAT_H    pattern/tile base, high
                     A_CURX = 8'h22,           //: CUR_X        text cursor column
                     A_CURY = 8'h23,           //: CUR_Y        text cursor row
                     A_CURCTL = 8'h24;         //: CUR_CTRL     cursor enable and blink

    reg [7:0]  mode_r;
    reg [5:0]  ctrl_r;
    reg [15:0] base_r, stride_r, pat_r;
    reg [15:0] maporg_r;
    reg [9:0]  scx_r, scy_r;
    reg [7:0]  border_r;
    reg [7:0]  rcmp_r;
    reg [1:0]  irq_en, irq_fl;
    reg [7:0]  pal_idx;
    reg        pal_hf;
    reg [6:0]  curx_r;
    reg [4:0]  cury_r;
    reg [4:0]  curctl_r;
    reg [9:0]  vact_r;
    reg [9:0]  raster_r;
    reg [6:0]  blink_r;
    reg [6:0]  curx_d;              // the display's cursor, latched at
    reg [4:0]  cury_d;              //   frame start like VID_BASE
    reg        blrst;               // a move's blink restart, pending

    assign o_sel = (io_a[7:4] == 4'h1) ||
                   (io_a[7:4] == 4'h2 && io_a[3:0] <= 4'h5);

    assign disp_en   = mode_r[7];
    assign engine    = ctrl_r[1:0];
    assign bpp_log   = ctrl_r[3:2];
    assign hdouble   = ctrl_r[4];
    assign vdouble   = ctrl_r[5];
    assign base      = base_r;
    assign stride    = stride_r;
    assign pat_base  = pat_r;
    assign map_org   = maporg_r;
    assign scrl_x    = scx_r;
    assign scrl_y    = scy_r;
    assign border    = border_r;
    // The display reads the frame-latched copies, never the written
    // registers — see the latch at frame_start below.
    assign cur_x     = curx_d;
    assign cur_y     = cury_d;
    assign vactive   = vact_r;

    // The blink lives here rather than in the pixel domain because this
    // is where the frame tick and CUR_X/CUR_Y already are, and a phase
    // that restarts when the cursor moves is what makes a cursor
    // followable while typing. Rate 3 is no blink at all — a solid
    // cursor is what a full-screen editor wants and it costs a mux entry.
    wire [6:0] blink_sel = 7'd1 << (3 + curctl_r[4:3]);
    assign cur_on = curctl_r[0] &
                    ((curctl_r[4:3] == 2'd3) ? 1'b1 : ~|(blink_r & blink_sel));

    // ------------------------------------------------- the derived widths
    //
    // `hdisp` is the screen in logical pixels: 640, or 320 when every
    // pixel is drawn twice. `img_w` is what the row pitch actually holds
    // — `stride * 8 / bpp` — which for text and tiles is the full screen
    // by construction and for a bitmap is whatever software set. Where
    // the image is narrower the difference is border, split evenly.

    wire [10:0] hdisp = hdouble ? 11'd320 : 11'd640;

    wire [10:0] img_w = (engine != 2'd2) ? hdisp :
                        (bpp_log == 2'd0) ? {stride_r[7:0], 3'b000} :
                        (bpp_log == 2'd1) ? {stride_r[8:0], 2'b00}  :
                        (bpp_log == 2'd2) ? {stride_r[9:0], 1'b0}   :
                                             stride_r[10:0];

    // Registered, not wired. A compare, a subtract and a shift is four
    // levels of logic, and combinationally it lands on the capture
    // flip-flops in cool8_pixel across the width of the chip — which
    // `nextpnr` reported as the tail of the machine's critical path. The
    // values only move when software changes a mode, so a cycle of
    // latency on them is a cycle nobody can observe.
    wire narrow = (img_w < hdisp);
    reg [10:0] hact_r, hstart_r;
    reg [9:0]  vstart_r;

    assign hactive = hact_r;
    assign hstart  = hstart_r;
    assign vstart  = vstart_r;

    always @(posedge clk) begin
        hact_r   <= narrow ? img_w : hdisp;
        hstart_r <= narrow ? ((hdisp - img_w) >> 1) : 11'd0;
        vstart_r <= (10'd480 - vact_r) >> 1;
    end

    // ------------------------------------------------------- the presets

    reg [5:0]  p_ctrl;
    reg [15:0] p_base, p_stride;
    reg [9:0]  p_vact;
    reg        p_load;

    always @* begin
        p_load = 1'b1;
        case (io_wdata[3:0])
            // engine, bpp, hdouble, vdouble
            // 160: eighty cells of char and attribute, the widest text
            // this machine shows. It was 256 so the map's size was a
            // power of two, which the mask needed to derive the origin
            // ([D30]); the origin is a register now, so the 3072 bytes
            // of padding bought nothing. Mode 1 writes the left forty
            // cells of the same row and leaves the rest.
            //
            // **160 works and is one investigation from being on.**
            // Flipping this, the reset value below, and con_row's
            // arithmetic makes sim/test_main.py pass in full -- the
            // whole system, typed at, at a 5120-byte map. What still
            // fails is two graphics cases in test_run/test_basic:
            // `MODE 4 : PLOT 10,3,15 : VPEEK(3*160+5)` reads zero
            // because VID_BASE is $0500 by then, one graphics scroll
            // in, and the test assumes a base of zero.
            //
            // **The reset value matters as much as the preset**, which
            // is what cost the first attempt: a harness that pokes the
            // image in and jumps to `main` never writes VID_MODE, so
            // the console meets the reset stride, and con_row addressed
            // rows 160 apart on a display reading them 256 apart.
            4'd0: begin p_ctrl = 6'b00_00_00; p_base = 16'h8000;
                        p_stride = 16'd256; p_vact = 10'd480; end
            4'd1: begin p_ctrl = 6'b01_00_00; p_base = 16'h8000;
                        p_stride = 16'd256; p_vact = 10'd480; end
            4'd2: begin p_ctrl = 6'b11_10_01; p_base = 16'h0000;
                        p_stride = 16'd128; p_vact = 10'd480; end
            4'd3: begin p_ctrl = 6'b00_00_10; p_base = 16'h0000;
                        p_stride = 16'd80;  p_vact = 10'd480; end
            4'd4: begin p_ctrl = 6'b11_10_10; p_base = 16'h0000;
                        p_stride = 16'd160; p_vact = 10'd480; end
            4'd5: begin p_ctrl = 6'b11_10_10; p_base = 16'h0000;
                        p_stride = 16'd128; p_vact = 10'd384; end
            4'd6: begin p_ctrl = 6'b11_11_10; p_base = 16'h0000;
                        p_stride = 16'd256; p_vact = 10'd480; end
            default: begin p_ctrl = 6'b0; p_base = 16'h0000;
                           p_stride = 16'd0; p_vact = 10'd480;
                           p_load = 1'b0; end
        endcase
    end

    // ------------------------------------------------------- the raster
    //
    // `line_y` arrives with `line_start` from the pixel domain, already
    // coherent — the crossing is a toggle in cool8_video and the value
    // has been stable for lines by the time it is sampled here. So the
    // compare is an ordinary synchronous compare and VID_RASTER is an
    // ordinary register, with no chance of reading a line number that
    // was never on the screen.
    //
    // VID_RCMP is eight bits against a ten-bit line, so a compare value
    // matches three times a frame below line 480. That is the register
    // width section 4.2 specifies; a handler that cares tests VID_RASTER
    // itself.

    wire raster_hit = line_start & (line_y[7:0] == rcmp_r);

    assign o_irq = |(irq_fl & irq_en);

    // ---------------------------------------------------------- writes

    wire wr = io_we & o_sel;

    assign pal_we    = wr & (io_a == A_PALDAT);
    assign pal_entry = pal_idx;
    assign pal_half  = pal_hf;

    wire cur_reset = wr & ((io_a == A_CURX) | (io_a == A_CURY));

    always @(posedge clk) begin
        if (!rst_n) begin
            mode_r   <= 8'h00;
            ctrl_r   <= 6'b00_00_00;
            base_r   <= 16'h8000;
            maporg_r <= 16'h8000;
            stride_r <= 16'd256;
            pat_r    <= 16'h0000;
            scx_r    <= 10'd0;
            scy_r    <= 10'd0;
            border_r <= 8'h00;
            rcmp_r   <= 8'h00;
            irq_en   <= 2'b00;
            irq_fl   <= 2'b00;
            pal_idx  <= 8'h00;
            pal_hf   <= 1'b0;
            curx_r   <= 7'd0;
            cury_r   <= 5'd0;
            curctl_r <= 5'b00000;
            vact_r   <= 10'd480;
            raster_r <= 10'd0;
            blink_r  <= 7'd0;
            curx_d   <= 7'd0;
            cury_d   <= 5'd0;
            blrst    <= 1'b0;
        end else begin
            if (line_start) raster_r <= line_y;

            // The cursor the screen shows updates only at frame start,
            // the way the fetch engine latches VID_BASE: a mid-frame
            // move cannot split the block across two columns, and the
            // blink-phase restart waits for the same edge so the
            // cursor's whole screen state changes atomically. Software
            // sees nothing: CUR_X and CUR_Y read back what was
            // written, as they always did.
            if (frame_start) begin
                curx_d  <= curx_r;
                cury_d  <= cury_r;
                blink_r <= (blrst | cur_reset) ? 7'd0 : blink_r + 1'b1;
                blrst   <= 1'b0;
            end else if (cur_reset)
                blrst   <= 1'b1;

            // Set before the acknowledge below, so a hit in the very
            // cycle a handler clears the flag is not lost.
            if (raster_hit)  irq_fl[0] <= 1'b1;
            if (frame_start) irq_fl[1] <= 1'b1;

            if (wr) begin
                case (io_a)
                    A_MODE: begin
                        mode_r <= io_wdata;
                        if (p_load) begin
                            ctrl_r   <= p_ctrl;
                            base_r   <= p_base;
                            // **The map's address, latched here and
                            // nowhere else.** VID_BASE says which row is
                            // displayed first and moves on every scroll;
                            // this says where the map itself begins, and
                            // only a mode change moves it. They used to
                            // be the same register, separated by a mask,
                            // which is what forced the map to be aligned
                            // to its own size.
                            maporg_r <= p_base;
                            stride_r <= p_stride;
                            vact_r   <= p_vact;
                        end
                    end
                    A_CTRL:   ctrl_r         <= io_wdata[5:0];
                    A_BASEL:  base_r[7:0]    <= io_wdata;
                    A_BASEH:  base_r[15:8]   <= io_wdata;
                    A_STRDL:  stride_r[7:0]  <= io_wdata;
                    A_STRDH:  stride_r[15:8] <= io_wdata;
                    A_SCXL:   scx_r[7:0]     <= io_wdata;
                    A_SCXH:   scx_r[9:8]     <= io_wdata[1:0];
                    A_SCYL:   scy_r[7:0]     <= io_wdata;
                    A_SCYH:   scy_r[9:8]     <= io_wdata[1:0];
                    A_BORDER: border_r       <= io_wdata;
                    A_RCMP:   rcmp_r         <= io_wdata;
                    A_IRQ: begin
                        irq_en <= io_wdata[5:4];
                        // Write 1 to clear, the shape UART_STAT and
                        // TMR_STAT already use.
                        if (io_wdata[0]) irq_fl[0] <= 1'b0;
                        if (io_wdata[1]) irq_fl[1] <= 1'b0;
                    end
                    A_PALIDX: begin pal_idx <= io_wdata; pal_hf <= 1'b0; end
                    A_PALDAT: begin
                        pal_hf <= ~pal_hf;
                        if (pal_hf) pal_idx <= pal_idx + 1'b1;
                    end
                    A_PATL:   pat_r[7:0]     <= io_wdata;
                    A_PATH:   pat_r[15:8]    <= io_wdata;
                    A_CURX:   curx_r         <= io_wdata[6:0];
                    A_CURY:   cury_r         <= io_wdata[4:0];
                    A_CURCTL: curctl_r       <= io_wdata[4:0];
                    default: ;
                endcase
            end
        end
    end

    // ----------------------------------------------------------- reads

    always @* begin
        case (io_a)
            A_MODE:   o_rdata = mode_r;
            A_CTRL:   o_rdata = {2'b00, ctrl_r};
            A_BASEL:  o_rdata = base_r[7:0];
            A_BASEH:  o_rdata = base_r[15:8];
            A_STRDL:  o_rdata = stride_r[7:0];
            A_STRDH:  o_rdata = stride_r[15:8];
            A_SCXL:   o_rdata = scx_r[7:0];
            A_SCXH:   o_rdata = {6'b000000, scx_r[9:8]};
            A_SCYL:   o_rdata = scy_r[7:0];
            A_SCYH:   o_rdata = {6'b000000, scy_r[9:8]};
            A_BORDER: o_rdata = border_r;
            A_RASTER: o_rdata = raster_r[7:0];
            A_RCMP:   o_rdata = rcmp_r;
            A_IRQ:    o_rdata = {2'b00, irq_en, 2'b00, irq_fl};
            A_PALIDX: o_rdata = pal_idx;
            A_PATL:   o_rdata = pat_r[7:0];
            A_PATH:   o_rdata = pat_r[15:8];
            A_CURX:   o_rdata = {1'b0, curx_r};
            A_CURY:   o_rdata = {3'b000, cury_r};
            A_CURCTL: o_rdata = {3'b000, curctl_r};
            // PAL_DATA among them: the palette is write-only, and this
            // is the same $FF an address nobody claims reads.
            default:  o_rdata = 8'hFF;
        endcase
    end

    // `io_rd` is not used: nothing in this block has a read side effect.
    // Named in the port list all the same, because every other block on
    // the page takes it and a missing port is easier to misread than an
    // unused one.
    wire _unused = &{1'b0, io_rd, 1'b0};

endmodule

`default_nettype wire
