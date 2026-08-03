// cool8_agu — the single 16-bit adder, time-shared.
//
// docs/03-microarchitecture.md section 3.2: there is exactly one 16-bit
// adder in the core, and every address computation and pointer update
// goes through it. Sharing costs the two input muxes below and saves
// roughly 40% of the core's combinational area against separate
// increment and add paths.
//
// `a_operand` is brought out because the memory address is either the
// A input unmodified (fetch at PC, pop at SP, post-increment at X) or
// the sum (displaced addressing, push at SP-1, pre-decrement at X-1).
// That is a 2:1 mux in the core rather than a second address mux here.
//
// The 8-bit ALU is separate and is never used for address arithmetic.

`default_nettype none

module cool8_agu (
    input  wire [2:0]  a_sel,
    input  wire [2:0]  b_sel,
    input  wire        sub,          // invert B and carry in — DECW, SUBW

    input  wire [15:0] pc,
    input  wire [15:0] x,
    input  wire [15:0] y,
    input  wire [15:0] sp,
    input  wire [15:0] tmp16,        // {TMPH, TMP} — abs16 and imm16
    input  wire [15:0] vec,          // $FFF8 | vector<<1

    input  wire [7:0]  tmp,          // displacement byte
    input  wire [7:0]  reg_b,        // index register, zero-extended

    output wire [15:0] a_operand,
    output wire [15:0] result
);

    localparam [2:0] A_PC = 3'd0, A_X = 3'd1, A_Y = 3'd2,
                     A_SP = 3'd3, A_T16 = 3'd4, A_VEC = 3'd5;

    localparam [2:0] B_ZERO = 3'd0,   // pass A through
                     B_ONE  = 3'd1,   // INCW, DECW, PUSH, POP, fetch
                     B_SEXT = 3'd2,   // [X+d8], ADDW SP,#d8, branches
                     B_ZEXT = 3'd3,   // [SP+u8], LEA
                     B_REG  = 3'd4,   // [X+Rs], ADDW X,Rd
                     B_T16  = 3'd5;   // ADDW X,#imm16

    reg [15:0] a;
    always @* begin
        case (a_sel)
            A_PC:    a = pc;
            A_X:     a = x;
            A_Y:     a = y;
            A_SP:    a = sp;
            A_T16:   a = tmp16;
            default: a = vec;
        endcase
    end

    reg [15:0] b;
    always @* begin
        case (b_sel)
            B_ZERO:  b = 16'h0000;
            B_ONE:   b = 16'h0001;
            B_SEXT:  b = {{8{tmp[7]}}, tmp};
            B_ZEXT:  b = {8'h00, tmp};
            B_REG:   b = {8'h00, reg_b};
            default: b = tmp16;
        endcase
    end

    wire [15:0] bop = sub ? ~b : b;

    assign a_operand = a;
    assign result    = a + bop + {15'b0, sub};

endmodule

`default_nettype wire
