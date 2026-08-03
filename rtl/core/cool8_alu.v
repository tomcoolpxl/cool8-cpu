// cool8_alu — the 8-bit ALU and flag generator.
//
// One 8-bit adder, shared by ADD/ADC/SUB/SBC/CMP. Subtraction feeds it
// ~b with a carry in, which is why C comes out as "no borrow" for free
// (docs/02-isa.md section 1.1).
//
// The op field 0..7 is deliberately identical to the ISA's `ooo` field,
// so the decoder passes it straight through for both the $00-$1F and
// $80-$FF groups. 8..14 are the page-2 extras.
//
// NOT and NEG have no op of their own: NOT is XOR against $FF and NEG
// is SUB with zero on the A input, both arranged by the operand muxes
// in cool8_core.
//
// set_c / set_zn / set_v are a pure function of the op, per the
// normative flag table in docs/02-isa.md section 1.2. The core ANDs
// them with its own write enable.

`default_nettype none

module cool8_alu (
    input  wire [3:0] op,
    input  wire [7:0] a,
    input  wire [7:0] b,
    input  wire       cin,          // the current C flag

    output reg  [7:0] result,
    output wire       c_out,
    output wire       z_out,
    output wire       n_out,
    output wire       v_out,
    output wire       set_c,        // this op writes C
    output wire       set_zn,       // this op writes Z and N
    output wire       set_v         // this op writes V
);

    localparam [3:0] OP_MOV  = 4'd0,   // r = b, no flags at all
                     OP_ADD  = 4'd1,
                     OP_ADC  = 4'd2,
                     OP_SUB  = 4'd3,
                     OP_SBC  = 4'd4,
                     OP_AND  = 4'd5,
                     OP_OR   = 4'd6,
                     OP_CMP  = 4'd7,   // SUB with no writeback
                     OP_XOR  = 4'd8,
                     OP_SWAP = 4'd9,
                     OP_SHR  = 4'd10,
                     OP_SAR  = 4'd11,
                     OP_ROR  = 4'd12,
                     OP_BIC  = 4'd13,  // a & ~b, for BCLR
                     OP_LDB  = 4'd14;  // r = b, sets Z and N — loads

    // ---------------------------------------------------------- adder

    wire is_sub  = (op == OP_SUB) | (op == OP_SBC) | (op == OP_CMP);
    wire is_arith = (op == OP_ADD) | (op == OP_ADC) | is_sub;

    wire [7:0] bop = is_sub ? ~b : b;

    // ADD  a +  b + 0      SUB/CMP  a + ~b + 1
    // ADC  a +  b + C      SBC      a + ~b + C
    wire adder_cin = ((op == OP_ADC) | (op == OP_SBC)) ? cin : is_sub;

    wire [8:0] sum = {1'b0, a} + {1'b0, bop} + {8'b0, adder_cin};

    // Signed overflow: operands agreed in sign, the result disagrees.
    wire v_arith = (~(a[7] ^ bop[7])) & (a[7] ^ sum[7]);

    // ----------------------------------------------------- shift group

    wire is_shift = (op == OP_SHR) | (op == OP_SAR) | (op == OP_ROR);

    // --------------------------------------------------------- result

    always @* begin
        case (op)
            OP_MOV, OP_LDB: result = b;
            OP_ADD, OP_ADC,
            OP_SUB, OP_SBC,
            OP_CMP:         result = sum[7:0];
            OP_AND:         result = a & b;
            OP_OR:          result = a | b;
            OP_XOR:         result = a ^ b;
            OP_BIC:         result = a & ~b;
            OP_SWAP:        result = {a[3:0], a[7:4]};
            OP_SHR:         result = {1'b0, a[7:1]};
            OP_SAR:         result = {a[7], a[7:1]};
            OP_ROR:         result = {cin,  a[7:1]};
            default:        result = b;
        endcase
    end

    assign c_out  = is_shift ? a[0] : sum[8];
    assign z_out  = ~|result;
    assign n_out  = result[7];
    assign v_out  = v_arith;

    assign set_c  = is_arith | is_shift;
    assign set_v  = is_arith;
    assign set_zn = (op != OP_MOV);

endmodule

`default_nettype wire
