// cool8_snd — the sound engine. One datapath, eight voices.
//
// ## Why this is not four dividers
//
// D12 specified three square-wave channels and a noise channel, each
// with its own divider and attenuator, and budgeted ~250 LUT4. That is
// the SN76489's shape, and the SN76489's shape is an answer to the
// SN76489's problem: a 4 MHz part with no cycles to spare had to make
// four voices in parallel because it could not make them in series.
//
// This part has 8.375 MHz and wants a ~32 kHz sample rate, which is
// **256 system clocks between samples**. A voice needs four. So there is
// one of everything and it is time-multiplexed, and the consequence is
// the whole design:
//
//   - **A phase accumulator, not a divider.** Per voice in parallel a
//     divider is smaller, which is what D12 measured against. Shared, it
//     is the other way round: an accumulator is one adder for every
//     voice, where a divider needs a reload comparator each. The pitch
//     resolution is better everywhere as well, rather than coarsening at
//     the top of the range the way a divider does.
//
//   - **Voice state in one block RAM.** 8 voices x 3 words is 24 of 256.
//     As flip-flops it would be 8 x 36 = 288, which is what the parallel
//     design would have spent it on.
//
//   - **The mixer is serial**, so it is one 4-bit add into an
//     accumulator rather than a tree of them.
//
// The point of all of it: **once the datapath is shared, the voice count
// is nearly free.** Going from one voice to eight costs RAM words and
// clocks out of a budget with 224 spare, not logic. The expensive step is
// the first voice, not the eighth.
//
// ## What is deliberately not here
//
// No envelopes, no frequency sweep, no ring modulation, no filter. A
// vblank handler doing envelopes is about twenty instructions and can do
// shapes no hardware ADSR offers. No hardware would make the machine
// louder; it would make it bigger.
//
// **And no DSP block**, although seven sit idle. A square wave times a
// 4-bit volume is a sign and a mux, not a multiply. The DSP earns its
// place the day a voice reads a wavetable or a sample out of memory —
// that is the upgrade path and it is a good one — but spending it on
// squares would buy nothing.
//
// ## The register map — two addresses, not twenty
//
//   $FE50  SND_IDX   which byte of the voice array
//   $FE51  SND_DATA  ...and it, auto-incrementing
//
// Twenty-four direct-mapped registers is twenty-four address decodes. An
// indexed port is two, and it is the idiom PAL_IDX/PAL_DATA and
// SPR_IDX/SPR_DATA already use. Setting a voice is three consecutive
// stores with no address arithmetic between them.
//
//   voice v, byte 0,1   phase increment [15:0]  — the pitch
//   voice v, byte 2     {noise, enable, -, -, volume[3:0]}
//
//   f_out = increment * 8375000 / 256 / 65536 = increment * 0.4993 Hz
//
// so middle A is increment 881, and a 16-bit increment reaches 32 kHz
// with 0.5 Hz resolution everywhere — where a 12-bit divider gave 46 Hz
// at the bottom and 12 kHz steps at the top.
//
// ## One write port, arbitrated
//
// SB_RAM40_4K has one write port and one read port, and both the CPU and
// the engine write — the engine puts back every phase it advances. The
// CPU wins, and the engine simply loses that voice's update for one
// sample. A sample is 30 us and a store is rare; nothing can hear it.
//
// FPGA-only. None of this goes to the ASIC.

`default_nettype none

module cool8_snd #(
    // 8.375 MHz / 256 = 32.7 kHz. Any power of two; the pitch constant
    // above follows it.
    parameter integer SR_LOG2 = 8
) (
    input  wire       clk,
    input  wire       rst_n,

    // ---- the I/O page, $FE50-$FE51
    input  wire [7:0] io_a,
    input  wire       io_rd,
    input  wire       io_we,
    input  wire [7:0] io_wdata,
    output wire       o_sel,

    // ---- one pin, through an RC low-pass
    output reg        o_pwm
);

    localparam [7:0] A_IDX = 8'h50,            //: SND_IDX      voice to address
                     A_DATA = 8'h51;           //: SND_DATA     that voice's registers

    assign o_sel = (io_a == A_IDX) || (io_a == A_DATA);

    wire wr = io_we & o_sel;

    // ------------------------------------------------------- the voices
    //
    // 16 bits wide because the increment is, and the whole point of the
    // block RAM is that the other two fields ride along for nothing.
    //
    //   {v, 2'b00}  increment
    //   {v, 2'b01}  phase
    //   {v, 2'b10}  {noise, enable, 6'-, volume[3:0]} in the low byte

    reg [15:0] vmem [0:31];
    reg [15:0] vq;

    // Six bits, because eight voices of six bytes is forty-eight. An
    // eight-bit index would let software point at RAM that is not there.
    reg [5:0]  idx;
    reg [7:0]  hold;                   // the even byte, waiting for its pair

    // A byte pair commits together, as cool8_pal and cool8_sprite do and
    // for the same reason: this configuration of block RAM has no byte
    // enables.
    wire       cpu_we = wr & (io_a == A_DATA) & idx[0];
    wire [4:0] cpu_a  = idx[5:1];
    wire [15:0] cpu_d = {io_wdata, hold};

    // ------------------------------------------------------ the sequencer
    //
    // Four clocks a voice: name the increment, name the phase, add them,
    // put the phase back and mix. The block RAM answers a cycle late, so
    // each step reads for the one after it.

    reg [SR_LOG2-1:0] tick;            // when the next sample starts
    reg [2:0]  v;                      // which voice
    reg [1:0]  ph;                     // which of its four clocks
    reg        busy;

    // **The phase is read last and never stored.** Reading it first meant
    // holding it in a register, adding the increment into a second one,
    // and writing that back the cycle after — three 16-bit registers to
    // move one number. Read in the order control, increment, phase and
    // the sum is formed combinationally out of the block RAM's own output
    // on the cycle it is written back, so `phase_r`, `nxt_phase` and the
    // carry flag all go. That is 33 flip-flops for six, and it is what
    // took the machine from not fitting the part to fitting it.
    reg [15:0] inc_r;
    reg [5:0]  ctl_r;                  // {noise, enable, volume[3:0]}

    wire [16:0] phase_sum = {1'b0, vq} + {1'b0, inc_r};

    reg signed [8:0] mix;              // 8 voices x +-15 fits in 9 bits
    reg signed [8:0] sample;

    // The modulator counts upwards, so the signed mix is offset. Declared
    // here rather than beside the logic that uses it because Verilog-2001
    // wants declarations before use and Icarus enforces it.
    reg  [7:0] sd;
    wire [7:0] level = {~sample[8], sample[7:1]};

    // One LFSR for every noise voice. Advanced when the voice that wants
    // it wraps, so its pitch register sets the noise rate exactly as it
    // sets a square's frequency.
    reg [15:0] lfsr;

    wire       v_noise = ctl_r[5];
    wire       v_en    = ctl_r[4];
    wire [3:0] v_vol   = ctl_r[3:0];
    wire       v_wave  = v_noise ? lfsr[0] : vq[15];   // vq is the phase now

    wire signed [8:0] v_step = v_en ? (v_wave ? {5'd0, v_vol}
                                              : -{5'd0, v_vol})
                                    : 9'sd0;

    // Control, increment, phase — in that order, so the phase arrives on
    // the cycle it is written back and never needs a register.
    wire [4:0] eng_ra = (ph == 2'd0) ? {v, 2'b10} :   // control
                        (ph == 2'd1) ? {v, 2'b00} :   // increment
                                       {v, 2'b01};    // phase
    wire       eng_we = busy & (ph == 2'd3);

    always @(posedge clk) begin
        // The CPU wins the one write port. The engine loses that voice's
        // phase for one sample of 30 us, which nothing can hear.
        if (cpu_we)      vmem[cpu_a] <= cpu_d;
        else if (eng_we) vmem[{v, 2'b01}] <= phase_sum[15:0];
        vq <= vmem[cpu_we ? cpu_a : eng_ra];
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            idx <= 6'd0; hold <= 8'd0;
            tick <= {SR_LOG2{1'b0}};
            v <= 3'd0; ph <= 2'd0; busy <= 1'b0;
            inc_r <= 16'd0; ctl_r <= 6'd0;
            mix <= 9'sd0; sample <= 9'sd0;
            lfsr <= 16'hACE1;
            sd <= 8'd0;                // the modulator's residue
            o_pwm <= 1'b0;
        end else begin
            // ---- the register port
            if (wr) begin
                if (io_a == A_IDX) idx <= io_wdata[5:0];
                else begin
                    hold <= io_wdata;
                    idx  <= idx + 6'd1;
                end
            end

            // ---- a sample every 2^SR_LOG2 clocks
            tick <= tick + 1'b1;
            if (&tick) begin
                sample <= mix;
                mix    <= 9'sd0;
                v      <= 3'd0;
                ph     <= 2'd0;
                busy   <= 1'b1;
            end else if (busy) begin
                ph <= ph + 2'd1;
                case (ph)
                    2'd0: ;                          // control on its way
                    2'd1: ctl_r <= {vq[15], vq[14], vq[3:0]};
                    2'd2: inc_r <= vq;               // ...phase on its way
                    default: begin                   // phase is on `vq` now
                        mix <= mix + v_step;
                        // The noise voice clocks the shift register at its
                        // own pitch, which is what makes noise pitch mean
                        // something rather than being one of four rates.
                        if (v_noise & v_en & phase_sum[16])
                            lfsr <= {lfsr[14:0],
                                     lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
                        if (v == 3'd7) busy <= 1'b0;
                        v <= v + 3'd1;
                    end
                endcase
            end

            // ---- one pin
            //
            // First-order sigma-delta at the full 8.375 MHz against a
            // 32.7 kHz sample: 256 carries to spend on each one, which is
            // eight bits of resolution and is all an eight-bit machine's
            // music needs. An RC low-pass on the pin is the DAC.
            {o_pwm, sd} <= {1'b0, sd} + {1'b0, level};
        end
    end

    // **The whole port is write-only**, which PAL_DATA and SPR_DATA are
    // already and SND_IDX now is too. The array's read port belongs to
    // the engine; reading back a value software itself wrote costs an
    // entry in the I/O page's read mux and buys the ability to ask a
    // question software already knows the answer to. Both addresses read
    // $FF, the same as an address nobody claims.
    wire _unused = &{1'b0, io_rd, vq[13:4], 1'b0};

endmodule

`default_nettype wire
