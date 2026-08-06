// cool8_core — the COOL8 CPU.
//
// Multicycle, non-pipelined, single memory port. Written against
// docs/02-isa.md; the reference emulator in tools/cool8emu.py is the
// executable form of the same specification and this core is checked
// against it instruction by instruction (sim/cosim.py).
//
// Contains no vendor primitives, no inferred RAM, no tri-state, no
// initial blocks with content, no clock gating and no asynchronous
// reset — see docs/03-microarchitecture.md section 1. The register file
// is flip-flops, because 32 bits of storage is cheaper as flops than as
// any RAM you could instantiate.
//
// One 8-bit ALU (cool8_alu) and one 16-bit adder (cool8_agu). Every
// address computation and pointer update goes through the latter.
//
// Bus protocol: assert mem_read or mem_write with a stable mem_addr;
// the transfer completes on the rising edge where mem_ready is high,
// and mem_rdata must be valid in that same cycle. While mem_ready is
// low the core holds everything and stalls.

`default_nettype none

module cool8_core (
    input  wire        clk,
    input  wire        rst_n,

    // Memory interface — one access at a time
    output wire [15:0] mem_addr,
    output reg  [7:0]  mem_wdata,
    input  wire [7:0]  mem_rdata,
    output reg         mem_read,
    output reg         mem_write,
    input  wire        mem_ready,

    // Interrupts (active high, synchronised outside the core)
    input  wire        irq,
    input  wire        nmi,

    // Bus arbitration — an external agent takes the memory bus
    input  wire        busrq,
    output wire        busak,

    // Status / debug
    output wire        o_fetch,      // this access is an opcode fetch
    output wire        o_halted,
    output wire        o_iack,
    output wire        o_retire      // an instruction completes this cycle
);

    // ================================================================
    // Constants
    // ================================================================

    localparam [3:0] S_RESET  = 4'd0,
                     S_VEC    = 4'd1,   // read a vector into PC
                     S_FETCH  = 4'd2,   // opcode
                     S_FETCH2 = 4'd3,   // page-2 second opcode byte
                     S_OPND   = 4'd4,   // 1 or 2 operand bytes
                     S_EXEC   = 4'd5,
                     S_MEM    = 4'd6,   // 1 or 2 data accesses
                     S_PUSH   = 4'd7,   // 2 or 3 byte push sequence
                     S_POP    = 4'd8,   // 2 or 3 byte pop sequence
                     S_MULT   = 4'd9,   // 8 shift-add steps
                     S_HALT   = 4'd10,
                     S_BUSAK  = 4'd11;

    // ALU ops — 0..7 are the ISA's `ooo` field, unchanged
    localparam [3:0] OP_MOV = 4'd0,  OP_ADD  = 4'd1,  OP_ADC = 4'd2,
                     OP_SUB = 4'd3,  OP_SBC  = 4'd4,  OP_AND = 4'd5,
                     OP_OR  = 4'd6,  OP_CMP  = 4'd7,  OP_XOR = 4'd8,
                     OP_SWAP= 4'd9,  OP_SHR  = 4'd10, OP_SAR = 4'd11,
                     OP_ROR = 4'd12, OP_BIC  = 4'd13, OP_LDB = 4'd14;

    localparam [2:0] A_PC = 3'd0, A_X = 3'd1, A_Y = 3'd2,
                     A_SP = 3'd3, A_T16 = 3'd4, A_VEC = 3'd5;
    localparam [2:0] B_ZERO = 3'd0, B_ONE = 3'd1, B_SEXT = 3'd2,
                     B_ZEXT = 3'd3, B_REG = 3'd4, B_T16  = 3'd5;

    // ALU operand sources
    localparam [1:0] AA_RA = 2'd0, AA_ZERO = 2'd1, AA_XH = 2'd2;
    localparam [2:0] AB_RB = 3'd0, AB_TMP = 3'd1, AB_RDATA = 3'd2,
                     AB_FF = 3'd3, AB_HALF = 3'd4, AB_MULB = 3'd5,
                     AB_RA = 3'd6;

    // Push / store data sources
    localparam [1:0] WD_RA = 2'd0, WD_F = 2'd1, WD_HI = 2'd2, WD_LO = 2'd3;
    localparam [1:0] W16_PC = 2'd0, W16_X = 2'd1, W16_Y = 2'd2;

    // Vector select — address is $FFF8 | vec<<1
    localparam [1:0] V_RESET = 2'd0, V_NMI = 2'd1,
                     V_IRQ   = 2'd2, V_BRK = 2'd3;

    // ================================================================
    // Architectural and microarchitectural state
    // ================================================================

    reg [7:0]  r0, r1, r2, r3;
    reg [15:0] x, y, sp, pc;
    reg        fc, fz, fn, fv, fi;

    reg [7:0]  ir;                  // opcode, or the page-2 second byte
    reg        p2;                  // ir holds a page-2 opcode
    reg [7:0]  tmp, tmph;           // immediate / displacement / address
    reg [3:0]  state;
    reg [2:0]  step;
    reg [1:0]  vec_sel;
    reg        in_int;              // the push sequence is an entry
    reg        iack_r;
    reg        halted;
    reg        nmi_d, nmi_pending;

    wire [7:0] flags = {3'b000, fi, fv, fn, fz, fc};

    // ================================================================
    // Decode
    // ================================================================

    // During a fetch the opcode is still on the bus, so the decoder
    // looks at mem_rdata rather than at the register it is about to be
    // written into. One 8-bit mux buys the whole next-state path.
    wire [7:0] d_ir = (state == S_FETCH || state == S_FETCH2)
                      ? mem_rdata : ir;
    wire       d_p2 = (state == S_FETCH)  ? 1'b0 :
                      (state == S_FETCH2) ? 1'b1 : p2;

    wire [3:0] hi4 = d_ir[7:4];
    wire [3:0] lo4 = d_ir[3:0];

    // --- primary page groups
    wire g_alui = !d_p2 && (d_ir[7:5] == 3'b000);          // $00-$1F
    wire g_ctrl = !d_p2 && (hi4 == 4'h2);                  // $20-$2F
    wire g_stk  = !d_p2 && (d_ir[7:3] == 5'b00110);        // $30-$37
    wire g_ptrq = !d_p2 && (d_ir[7:3] == 5'b00111);        // $38-$3F
    wire g_ld1  = !d_p2 && (hi4 == 4'h4);                  // $40-$4F
    wire g_ld2  = !d_p2 && (hi4 == 4'h5);                  // $50-$5F
    wire g_ld3  = !d_p2 && (hi4 == 4'h6);                  // $60-$6F
    wire g_br   = !d_p2 && (hi4 == 4'h7);                  // $70-$7F
    wire g_alur = !d_p2 && d_ir[7];                        // $80-$FF

    // --- page-2 groups
    wire p_xor  = d_p2 && (hi4 == 4'h0);                   // XOR Rd,Rs
    wire p_un   = d_p2 && (hi4 == 4'h1 || hi4 == 4'h2 || hi4 == 4'h3);
    wire p_movh = d_p2 && (hi4 == 4'h4);                   // MOV Rd,pp
    wire p_movp = d_p2 && (hi4 == 4'h5);                   // MOV pp,Rs
    wire p_wide = d_p2 && (hi4 == 4'h6);                   // $60-$6F
    wire p_aw   = d_p2 && (hi4 == 4'h7);                   // ADDW/SUBW X|Y,Rd
    wire p_idx  = d_p2 && (d_ir[7:6] == 2'b10);            // [X|Y + Rs]
    wire p_auto = d_p2 && (d_ir[7:5] == 3'b110);           // auto inc / dec
    wire p_sys  = d_p2 && (hi4 == 4'hE);                   // PUSH F/POP F/CLV
    wire p_mul  = d_p2 && (hi4 == 4'hF);

    // The primary page is fully assigned, so only page 2 needs the
    // reserved check — docs/02-isa.md section 5.
    wire p2_res = d_p2 && ((d_ir[7:1] == 7'b0010111) ||    // $2E-$2F
                           (d_ir[7:2] == 6'b001111)  ||    // $3C-$3F
                           (d_ir     == 8'h6F)       ||    // $6F
                           (hi4 == 4'hE && lo4 >= 4'h3));  // $E3-$EF

    // ADDW X|Y,#imm16 sits inside the unary block at $2C-$2D
    wire p_addwi = d_p2 && (d_ir[7:1] == 7'b0010110);
    wire [3:0] ug = d_ir[5:2];      // unary sub-group, $10-$3F

    // --- register file indices
    reg [1:0] rd_idx, rs_idx;
    always @* begin
        rd_idx = d_ir[1:0];
        rs_idx = d_ir[1:0];
        if (!d_p2) begin
            if (d_ir[7])                     rd_idx = d_ir[3:2];  // ALU Rd,Rs
            else if (d_ir[7:6] == 2'b01)     rd_idx = d_ir[2:1];  // LD/ST
        end else begin
            if (hi4 == 4'h0 || hi4 == 4'h4 ||
                hi4 == 4'h5 || hi4 == 4'hF)  rd_idx = d_ir[3:2];
            else if (d_ir[7:6] == 2'b10)     rd_idx = d_ir[3:2];  // [X+Rs]
            else if (d_ir[7:5] == 3'b110)    rd_idx = d_ir[2:1];  // auto
        end
    end

    reg [7:0] ra, rb;
    always @* case (rd_idx)
        2'd0: ra = r0;  2'd1: ra = r1;  2'd2: ra = r2;  default: ra = r3;
    endcase
    always @* case (rs_idx)
        2'd0: rb = r0;  2'd1: rb = r1;  2'd2: rb = r2;  default: rb = r3;
    endcase

    // pointer halves: 00 XL, 01 XH, 10 YL, 11 YH
    reg [7:0] half;
    always @* case (d_ir[1:0])
        2'd0: half = x[7:0];   2'd1: half = x[15:8];
        2'd2: half = y[7:0];   default: half = y[15:8];
    endcase

    // --- operand bytes following the opcode
    reg [1:0] nopnd;
    always @* begin
        nopnd = 2'd0;
        if (!d_p2) begin
            if      (d_ir[7:5] == 3'b000)             nopnd = 2'd1;
            else if (hi4 == 4'h2 && (lo4 == 4'h8 ||
                                     lo4 == 4'h9))    nopnd = 2'd2;
            else if (hi4 == 4'h5)                     nopnd = 2'd1;
            else if (hi4 == 4'h6)                     nopnd = d_ir[0]
                                                              ? 2'd2 : 2'd1;
            else if (hi4 == 4'h7)                     nopnd = 2'd1;
        end else begin
            if      (d_ir[7:2] == 6'b000100)          nopnd = 2'd1;  // XOR #
            else if (p_addwi)                         nopnd = 2'd2;
            else if (hi4 == 4'h3 && lo4[3:2] != 2'b11) nopnd = 2'd1; // bit ops
            else if (hi4 == 4'h6) begin
                if      (lo4 <= 4'h5)                 nopnd = 2'd2;
                else if (lo4 >= 4'hC && lo4 <= 4'hE)  nopnd = 2'd1;
            end
        end
    end

    // --- branch condition
    reg cond;
    always @* case (d_ir[3:0])
        4'h0: cond = 1'b1;                    // BRA
        4'h1: cond = 1'b0;                    // reserved, never
        4'h2: cond = fz;                      4'h3: cond = !fz;
        4'h4: cond = fc;                      4'h5: cond = !fc;
        4'h6: cond = fn;                      4'h7: cond = !fn;
        4'h8: cond = fv;                      4'h9: cond = !fv;
        4'hA: cond = fc && !fz;               4'hB: cond = !fc || fz;
        4'hC: cond = (fn == fv);              4'hD: cond = (fn != fv);
        4'hE: cond = !fz && (fn == fv);       default: cond = fz || (fn != fv);
    endcase

    // --- memory-access shape, for the LD/ST classes
    wire use_y   = (g_ld1 || g_ld2 || p_auto) ? d_ir[0] : d_ir[4];
    wire is_store = (g_ld1 || g_ld2 || g_ld3) ? d_ir[3]
                  : p_auto                    ? d_ir[3]
                  : p_idx                     ? d_ir[5]
                  : p_wide                    ? (lo4 == 4'h4 || lo4 == 4'h5)
                  : g_stk                     ? !d_ir[2]      // PUSH Rd
                  : p_sys                     ? (lo4 == 4'h0) // PUSH F
                  : 1'b0;

    // Which state runs once the opcode and its operands are in
    reg [3:0] exec_state;
    always @* begin
        exec_state = S_EXEC;
        if (g_ld1 || g_ld2 || g_ld3 || p_idx || p_auto) exec_state = S_MEM;
        else if (g_stk)                                 exec_state = S_MEM;
        else if (p_sys && lo4 <= 4'h1)                  exec_state = S_MEM;
        else if (p_wide && lo4 >= 4'h2 && lo4 <= 4'h5)  exec_state = S_MEM;
        else if (g_ptrq && lo4[2]) exec_state = lo4[1] ? S_POP : S_PUSH;
        else if (g_ctrl) begin
            case (lo4)
                4'h2, 4'h3:             exec_state = S_POP;   // RET, RETI
                4'h9, 4'hC, 4'hD, 4'hE: exec_state = S_PUSH;  // CALL, BRK
                default:                exec_state = S_EXEC;
            endcase
        end
    end

    // --- the next state out of a fetch, as a flat function of the opcode
    //
    // This is `nopnd` and `exec_state` again, restricted to the primary
    // page and written as one case rather than derived from the group
    // wires above. That is duplication on purpose.
    //
    // Those group wires are shared with S_MEM and S_EXEC, which have
    // enormous timing slack, and with S_FETCH, which has none: the cone
    // from the byte arriving on `mem_rdata` to the state register is the
    // 37 levels and 87 ns that docs/01-decisions.md's open question is
    // about, and it is why the system clock is a third of the pixel clock
    // rather than a half. Factoring that a slack path wants is factoring
    // the tight path pays for. Here the eight opcode bits reach four
    // output bits directly and the mapper can flatten them.
    //
    // In S_FETCH `d_ir` is `mem_rdata` and `d_p2` is 0, so this must agree
    // with the general path for every primary opcode — and sim/cosim.py
    // walks all 511 encodings, which is what makes duplicating it safe.
    reg [3:0] f_nxt;
    always @* begin
        case (mem_rdata[7:4])
            4'h0, 4'h1: f_nxt = S_OPND;                    // ALU Rd,#imm8
            4'h2: case (mem_rdata[3:0])
                      4'h2, 4'h3:       f_nxt = S_POP;     // RET, RETI
                      4'h8, 4'h9:       f_nxt = S_OPND;    // JMP/CALL abs16
                      4'hC, 4'hD, 4'hE: f_nxt = S_PUSH;    // CALL [X|Y], BRK
                      4'hF:             f_nxt = S_FETCH2;  // the escape
                      default:          f_nxt = S_EXEC;
                  endcase
            // $30-$37 PUSH/POP Rd, $38-$3B INCW/DECW, $3C-$3D PUSHW,
            // $3E-$3F POPW
            4'h3: f_nxt = !mem_rdata[3] ? S_MEM  :
                          !mem_rdata[2] ? S_EXEC :
                           mem_rdata[1] ? S_POP  : S_PUSH;
            4'h4: f_nxt = S_MEM;                           // LD/ST [X|Y]
            4'h5, 4'h6, 4'h7: f_nxt = S_OPND;
            default: f_nxt = S_EXEC;                       // $80-$FF
        endcase
    end

    // ================================================================
    // Interrupts and bus arbitration
    // ================================================================

    // An instruction that changes I does so in the same cycle it
    // retires, and the boundary check has to see the new value: reading
    // the old one would let an interrupt in immediately after DI, and
    // keep one out immediately after EI. Decoded here from state and IR
    // alone so there is no path back from the control block.
    wire ei_cycle   = (state == S_EXEC) && g_ctrl && (lo4 == 4'h4);
    wire di_cycle   = (state == S_EXEC) && g_ctrl && (lo4 == 4'h5);
    wire fpop_cycle = (state == S_MEM)  && p_sys  && (lo4 == 4'h1);

    wire fi_now = ei_cycle   ? 1'b1 :
                  di_cycle   ? 1'b0 :
                  fpop_cycle ? mem_rdata[4] : fi;

    wire irq_take    = irq & fi_now;
    wire int_pending = nmi_pending | irq_take;

    // Priority at an instruction boundary: busrq > nmi > irq.
    reg [3:0] nxt_boundary;
    always @* begin
        if (busrq)            nxt_boundary = S_BUSAK;
        else if (int_pending) nxt_boundary = S_PUSH;
        else                  nxt_boundary = S_FETCH;
    end
    wire boundary_int = !busrq && int_pending;

    // ================================================================
    // Datapath
    // ================================================================

    reg [2:0] agu_a_sel, agu_b_sel;
    reg       agu_sub;
    reg [1:0] alu_a_sel;
    reg [2:0] alu_b_sel;
    reg [3:0] alu_op;

    wire [15:0] vec_addr = {13'h1FFF, vec_sel, 1'b0};   // $FFF8 + vec*2
    wire [15:0] tmp16    = {tmph, tmp};

    wire [15:0] agu_a, agu_r;

    cool8_agu u_agu (
        .a_sel(agu_a_sel), .b_sel(agu_b_sel), .sub(agu_sub),
        .pc(pc), .x(x), .y(y), .sp(sp), .tmp16(tmp16), .vec(vec_addr),
        .tmp(tmp), .reg_b(rb),
        .a_operand(agu_a), .result(agu_r)
    );

    wire [7:0] mul_b = tmp & {8{x[0]}};

    reg [7:0] alu_a, alu_b;
    always @* case (alu_a_sel)
        AA_ZERO: alu_a = 8'h00;
        AA_XH:   alu_a = x[15:8];
        default: alu_a = ra;
    endcase
    always @* case (alu_b_sel)
        AB_TMP:   alu_b = tmp;
        AB_RDATA: alu_b = mem_rdata;
        AB_FF:    alu_b = 8'hFF;
        AB_HALF:  alu_b = half;
        AB_MULB:  alu_b = mul_b;
        AB_RA:    alu_b = ra;
        default:  alu_b = rb;
    endcase

    wire [7:0] alu_r;
    wire alu_c, alu_z, alu_n, alu_v, alu_set_c, alu_set_zn, alu_set_v;

    cool8_alu u_alu (
        .op(alu_op), .a(alu_a), .b(alu_b), .cin(fc),
        .result(alu_r), .c_out(alu_c), .z_out(alu_z),
        .n_out(alu_n), .v_out(alu_v),
        .set_c(alu_set_c), .set_zn(alu_set_zn), .set_v(alu_set_v)
    );

    // The multiply accumulator: X is the product and the shifted
    // multiplier at once. Each step conditionally adds the multiplicand
    // (held in TMP) to the high half, then shifts the 17-bit sum right.
    wire [15:0] mul_next = {alu_c, alu_r, x[7:1]};

    // ================================================================
    // Control
    // ================================================================

    reg        addr_r;          // 0 = the A input, 1 = the sum
    reg [1:0]  wd_sel, w16_sel;
    reg        ir_we, tmp_we, tmph_we;
    reg        reg_we, flag_we;
    reg        pc_we_agu, pc_we_bus;
    reg        x_we, y_we, sp_we;         // 16-bit, from the AGU
    reg        x_we_mul;
    reg        xl_we, xh_we, yl_we, yh_we;
    reg        bsrc_ra;                   // byte source: 0 rdata, 1 ra
    reg        f_we_bus, f_clc, f_sec, f_ei, f_di, f_clv;
    reg        z16_we, mul_flags;
    reg        set_halt, clr_nmi, set_int, clr_int, set_iack, clr_iack;
    reg [3:0]  nxt;
    reg [2:0]  nxt_step;
    reg [1:0]  nxt_vec;
    reg        vec_we;
    reg        retire;
    reg        at_boundary;    // this cycle completes an instruction

    wire adv = (mem_read | mem_write) ? mem_ready : 1'b1;

    reg [15:0] w16;
    always @* case (w16_sel)
        W16_X:   w16 = x;
        W16_Y:   w16 = y;
        default: w16 = pc;
    endcase

    always @* begin
        // ---- defaults
        mem_read = 1'b0;  mem_write = 1'b0;
        addr_r = 1'b0;
        agu_a_sel = A_PC; agu_b_sel = B_ZERO; agu_sub = 1'b0;
        alu_a_sel = AA_RA; alu_b_sel = AB_RB; alu_op = OP_MOV;
        wd_sel = WD_RA;   w16_sel = W16_PC;
        ir_we = 1'b0; tmp_we = 1'b0; tmph_we = 1'b0;
        reg_we = 1'b0; flag_we = 1'b0;
        pc_we_agu = 1'b0; pc_we_bus = 1'b0;
        x_we = 1'b0; y_we = 1'b0; sp_we = 1'b0; x_we_mul = 1'b0;
        xl_we = 1'b0; xh_we = 1'b0; yl_we = 1'b0; yh_we = 1'b0;
        bsrc_ra = 1'b0;
        f_we_bus = 1'b0; f_clc = 1'b0; f_sec = 1'b0;
        f_ei = 1'b0; f_di = 1'b0; f_clv = 1'b0;
        z16_we = 1'b0; mul_flags = 1'b0;
        set_halt = 1'b0; clr_nmi = 1'b0;
        set_int = 1'b0; clr_int = 1'b0;
        set_iack = 1'b0; clr_iack = 1'b0;
        vec_we = 1'b0; nxt_vec = V_RESET;
        nxt = state; nxt_step = 3'd0;
        retire = 1'b0; at_boundary = 1'b0;

        case (state)

        // ------------------------------------------------ reset entry
        S_RESET: begin
            vec_we = 1'b1; nxt_vec = V_RESET;
            nxt = S_VEC;
        end

        // ------------------------------------------- vector into PC
        S_VEC: begin
            mem_read = 1'b1;
            agu_a_sel = A_VEC;
            if (step == 3'd0) begin
                agu_b_sel = B_ZERO; addr_r = 1'b0;
                tmp_we = 1'b1;
                nxt = S_VEC; nxt_step = 3'd1;
            end else begin
                agu_b_sel = B_ONE;  addr_r = 1'b1;
                pc_we_bus = 1'b1;                 // PC <- {rdata, TMP}
                clr_iack = 1'b1;
                // BRK and the reserved-page-2 trap are instructions and
                // retire here. A hardware interrupt entry is not, and
                // neither is reset.
                retire = (vec_sel == V_BRK);
                nxt = busrq ? S_BUSAK : S_FETCH;
            end
        end

        // ---------------------------------------------------- fetch
        S_FETCH: begin
            mem_read = 1'b1;
            agu_a_sel = A_PC; agu_b_sel = B_ONE; addr_r = 1'b0;
            pc_we_agu = 1'b1;
            ir_we = 1'b1;

            nxt = f_nxt;

            // BRK's state is already S_PUSH above; what it needs on top is
            // the vector and the in-interrupt flag. Those are single bits
            // out of a much shallower cone than the state, so they stay on
            // the shared decode.
            if (g_ctrl && lo4 == 4'hE) begin
                set_int = 1'b1;
                vec_we = 1'b1; nxt_vec = V_BRK;
            end
        end

        S_FETCH2: begin
            mem_read = 1'b1;
            agu_a_sel = A_PC; agu_b_sel = B_ONE; addr_r = 1'b0;
            pc_we_agu = 1'b1;
            ir_we = 1'b1;

            if (p2_res) begin                            // reserved -> BRK
                nxt = S_PUSH; set_int = 1'b1;
                vec_we = 1'b1; nxt_vec = V_BRK;
            end
            else if (nopnd != 2'd0)      nxt = S_OPND;
            else                         nxt = exec_state;
        end

        // ------------------------------------------- operand bytes
        S_OPND: begin
            mem_read = 1'b1;
            agu_a_sel = A_PC; agu_b_sel = B_ONE; addr_r = 1'b0;
            pc_we_agu = 1'b1;

            if (step == 3'd0) begin
                tmp_we = 1'b1;
                if (nopnd == 2'd2) begin
                    nxt = S_OPND; nxt_step = 3'd1;
                end else if (g_br) begin
                    // Bcc: PC already addresses the next instruction
                    if (cond) nxt = S_EXEC;
                    else begin at_boundary = 1'b1; end
                end else nxt = exec_state;
            end else begin
                if (!d_p2 && g_ctrl && lo4 == 4'h8) begin   // JMP abs16
                    pc_we_agu = 1'b0;
                    pc_we_bus = 1'b1;                       // PC<-{rdata,TMP}
                    at_boundary = 1'b1;
                end else begin
                    tmph_we = 1'b1;
                    nxt = exec_state;
                end
            end
        end

        // -------------------------------------------- data accesses
        S_MEM: begin
            // --- address
            if (g_stk) begin                                // PUSH/POP Rd
                agu_a_sel = A_SP; agu_b_sel = B_ONE;
                agu_sub = !d_ir[2]; addr_r = !d_ir[2];
                sp_we = 1'b1;
            end else if (p_sys) begin                       // PUSH F/POP F
                agu_a_sel = A_SP; agu_b_sel = B_ONE;
                agu_sub = !d_ir[0]; addr_r = !d_ir[0];
                sp_we = 1'b1;
            end else if (g_ld1) begin                       // [X|Y]
                agu_a_sel = use_y ? A_Y : A_X; agu_b_sel = B_ZERO;
            end else if (g_ld2) begin                       // [X|Y+d8]
                agu_a_sel = use_y ? A_Y : A_X; agu_b_sel = B_SEXT;
                addr_r = 1'b1;
            end else if (g_ld3) begin
                if (d_ir[0]) begin                          // [abs16]
                    agu_a_sel = A_T16; agu_b_sel = B_ZERO;
                end else begin                              // [SP+u8]
                    agu_a_sel = A_SP;  agu_b_sel = B_ZEXT; addr_r = 1'b1;
                end
            end else if (p_idx) begin                       // [X|Y+Rs]
                agu_a_sel = use_y ? A_Y : A_X; agu_b_sel = B_REG;
                addr_r = 1'b1;
            end else if (p_auto) begin
                agu_a_sel = use_y ? A_Y : A_X; agu_b_sel = B_ONE;
                agu_sub = d_ir[4]; addr_r = d_ir[4];        // pre-decrement
                if (use_y) y_we = 1'b1; else x_we = 1'b1;
            end else begin                                  // LDW/STW abs16
                agu_a_sel = A_T16;
                agu_b_sel = (step == 3'd0) ? B_ZERO : B_ONE;
                addr_r    = (step != 3'd0);
            end

            // --- direction and data
            if (is_store) begin
                mem_write = 1'b1;
                if (p_wide) begin
                    w16_sel = d_ir[0] ? W16_Y : W16_X;
                    wd_sel  = (step == 3'd0) ? WD_LO : WD_HI;
                end else if (p_sys) wd_sel = WD_F;
                else                wd_sel = WD_RA;
            end else begin
                mem_read = 1'b1;
                if (p_wide) begin
                    if (d_ir[0]) begin
                        if (step == 3'd0) yl_we = 1'b1; else yh_we = 1'b1;
                    end else begin
                        if (step == 3'd0) xl_we = 1'b1; else xh_we = 1'b1;
                    end
                end else if (p_sys) f_we_bus = 1'b1;        // POP F
                else begin
                    alu_op = OP_LDB; alu_b_sel = AB_RDATA;
                    reg_we = 1'b1; flag_we = 1'b1;
                end
            end

            // --- sequencing
            if (p_wide && step == 3'd0) begin
                nxt = S_MEM; nxt_step = 3'd1;
            end else begin
                at_boundary = 1'b1;
            end
        end

        // ---------------------------------------- multi-byte pushes
        // PUSHW X|Y and CALL push high byte first, so the low byte
        // ends up at the lower address. Interrupt entry then adds F.
        S_PUSH: begin
            mem_write = 1'b1;
            agu_a_sel = A_SP; agu_b_sel = B_ONE;
            agu_sub = 1'b1; addr_r = 1'b1;
            sp_we = 1'b1;

            w16_sel = in_int              ? W16_PC :
                      (g_ptrq && d_ir[0]) ? W16_Y  :
                      g_ptrq              ? W16_X  : W16_PC;

            case (step)
                3'd0: begin wd_sel = WD_HI; nxt = S_PUSH; nxt_step = 3'd1; end
                3'd1: begin
                    wd_sel = WD_LO;
                    if (in_int) begin nxt = S_PUSH; nxt_step = 3'd2; end
                    else if (g_ptrq) begin                  // PUSHW
                        at_boundary = 1'b1;
                    end else nxt = S_EXEC;                  // CALL
                end
                default: begin                              // entry: push F
                    wd_sel = WD_F; f_di = 1'b1; clr_int = 1'b1;
                    nxt = S_VEC;
                end
            endcase
        end

        // ----------------------------------------- multi-byte pops
        S_POP: begin
            mem_read = 1'b1;
            agu_a_sel = A_SP; agu_b_sel = B_ONE; addr_r = 1'b0;
            sp_we = 1'b1;

            if (g_ptrq) begin                               // POPW X|Y
                if (d_ir[0]) begin
                    if (step == 3'd0) yl_we = 1'b1; else yh_we = 1'b1;
                end else begin
                    if (step == 3'd0) xl_we = 1'b1; else xh_we = 1'b1;
                end
                if (step == 3'd0) begin nxt = S_POP; nxt_step = 3'd1; end
                else begin
                    at_boundary = 1'b1;
                end
            end else begin                                  // RET / RETI
                // RETI pops F first, then the return address.
                if (lo4 == 4'h3 && step == 3'd0) begin
                    f_we_bus = 1'b1;
                    nxt = S_POP; nxt_step = 3'd1;
                end else if ((lo4 == 4'h3 && step == 3'd1) ||
                             (lo4 == 4'h2 && step == 3'd0)) begin
                    tmp_we = 1'b1;
                    nxt = S_POP; nxt_step = 3'd2;
                end else begin
                    pc_we_bus = 1'b1;
                    at_boundary = 1'b1;
                end
            end
        end

        // ------------------------------------------- multiply steps
        S_MULT: begin
            alu_a_sel = AA_XH; alu_b_sel = AB_MULB; alu_op = OP_ADD;
            x_we_mul = 1'b1;
            if (step == 3'd7) begin
                mul_flags = 1'b1;
                at_boundary = 1'b1;
            end else begin
                nxt = S_MULT; nxt_step = step + 3'd1;
            end
        end

        // ------------------------------------------------ halt, grant
        S_HALT: begin
            if (busrq)            nxt = S_BUSAK;
            else if (int_pending) begin
                nxt = S_PUSH; set_int = 1'b1; clr_nmi = 1'b1;
                set_iack = 1'b1;
                vec_we = 1'b1; nxt_vec = nmi_pending ? V_NMI : V_IRQ;
            end
            else                  nxt = S_HALT;
        end

        S_BUSAK: begin
            if (busrq)       nxt = S_BUSAK;
            else if (halted) nxt = S_HALT;
            else if (int_pending) begin
                nxt = S_PUSH; set_int = 1'b1; clr_nmi = 1'b1;
                set_iack = 1'b1;
                vec_we = 1'b1; nxt_vec = nmi_pending ? V_NMI : V_IRQ;
            end
            else             nxt = S_FETCH;
        end

        // --------------------------------------------------- execute
        default: begin      // S_EXEC
            at_boundary = 1'b1;

            if (g_alui) begin                       // ALU Rd,#imm8
                alu_op = {1'b0, d_ir[4:2]}; alu_b_sel = AB_TMP;
                reg_we = (d_ir[4:2] != 3'b111);     // CMP writes nothing
                flag_we = 1'b1;
            end
            else if (g_alur) begin                  // ALU Rd,Rs
                alu_op = {1'b0, d_ir[6:4]}; alu_b_sel = AB_RB;
                reg_we = (d_ir[6:4] != 3'b111);
                flag_we = 1'b1;
            end
            else if (g_br) begin                    // taken branch
                agu_a_sel = A_PC; agu_b_sel = B_SEXT; pc_we_agu = 1'b1;
            end
            else if (g_ptrq) begin                  // INCW / DECW
                agu_a_sel = d_ir[0] ? A_Y : A_X;
                agu_b_sel = B_ONE; agu_sub = d_ir[1];
                if (d_ir[0]) y_we = 1'b1; else x_we = 1'b1;
                z16_we = 1'b1;                      // Z only, from 16 bits
            end
            else if (g_ctrl) begin
                case (lo4)
                    4'h1: set_halt = 1'b1;                       // HALT
                    4'h4: f_ei = 1'b1;
                    4'h5: f_di = 1'b1;
                    4'h6: f_clc = 1'b1;
                    4'h7: f_sec = 1'b1;
                    4'h9: begin agu_a_sel = A_T16;               // CALL abs16
                                agu_b_sel = B_ZERO; pc_we_agu = 1'b1; end
                    4'hA, 4'hB: begin                            // JMP [X|Y]
                                agu_a_sel = lo4[0] ? A_Y : A_X;
                                agu_b_sel = B_ZERO; pc_we_agu = 1'b1; end
                    4'hC, 4'hD: begin                            // CALL [X|Y]
                                agu_a_sel = lo4[0] ? A_Y : A_X;
                                agu_b_sel = B_ZERO; pc_we_agu = 1'b1; end
                    default: ;                                   // NOP
                endcase
                if (lo4 == 4'h1) begin
                    // HALT retires, but the machine stops rather than
                    // going to a boundary. Any pending interrupt is
                    // sampled by S_HALT on the next cycle, which is what
                    // resumes execution.
                    at_boundary = 1'b0; retire = 1'b1; nxt = S_HALT;
                end
            end
            else if (p_xor) begin                   // XOR Rd,Rs
                alu_op = OP_XOR; alu_b_sel = AB_RB;
                reg_we = 1'b1; flag_we = 1'b1;
            end
            else if (p_addwi) begin                 // ADDW X|Y,#imm16
                agu_a_sel = d_ir[0] ? A_Y : A_X; agu_b_sel = B_T16;
                if (d_ir[0]) y_we = 1'b1; else x_we = 1'b1;
            end
            else if (p_un) begin
                reg_we = 1'b1; flag_we = 1'b1;
                case (ug)
                    4'd4: begin alu_op = OP_XOR; alu_b_sel = AB_TMP;  end
                    4'd5: begin alu_op = OP_XOR; alu_b_sel = AB_FF;   end
                    4'd6: begin alu_op = OP_SUB; alu_a_sel = AA_ZERO;
                                alu_b_sel = AB_RA;                    end
                    4'd7:       alu_op = OP_SWAP;
                    4'd8:       alu_op = OP_SHR;
                    4'd9:       alu_op = OP_SAR;
                    4'd10:      alu_op = OP_ROR;
                    4'd12: begin alu_op = OP_OR;  alu_b_sel = AB_TMP; end
                    4'd13: begin alu_op = OP_BIC; alu_b_sel = AB_TMP; end
                    default: begin alu_op = OP_AND; alu_b_sel = AB_TMP;
                                   reg_we = 1'b0;                     end
                endcase
            end
            else if (p_movh) begin                  // MOV Rd,<pp>
                // A MOV, and MOV never touches flags — symmetric with
                // MOV <pp>,Rs below. See docs/02-isa.md section 1.2.
                alu_op = OP_MOV; alu_b_sel = AB_HALF;
                reg_we = 1'b1;
            end
            else if (p_movp) begin                  // MOV <pp>,Rs
                bsrc_ra = 1'b1;
                case (d_ir[1:0])
                    2'd0: xl_we = 1'b1;   2'd1: xh_we = 1'b1;
                    2'd2: yl_we = 1'b1;   default: yh_we = 1'b1;
                endcase
            end
            else if (p_aw) begin                    // ADDW/SUBW X|Y,Rd
                // $70 ADDW X  $74 ADDW Y  $78 SUBW X  $7C SUBW Y
                agu_a_sel = d_ir[2] ? A_Y : A_X;
                agu_b_sel = B_REG; agu_sub = d_ir[3];
                if (d_ir[2]) y_we = 1'b1; else x_we = 1'b1;
            end
            else if (p_wide) begin
                case (lo4)
                    4'h0, 4'h1: begin                       // LDW X|Y,#imm16
                        agu_a_sel = A_T16; agu_b_sel = B_ZERO;
                        if (lo4[0]) y_we = 1'b1; else x_we = 1'b1; end
                    4'h6: begin agu_a_sel = A_Y; x_we = 1'b1; end
                    4'h7: begin agu_a_sel = A_X; y_we = 1'b1; end
                    4'h8: begin agu_a_sel = A_X; sp_we = 1'b1; end
                    4'h9: begin agu_a_sel = A_Y; sp_we = 1'b1; end
                    4'hA: begin agu_a_sel = A_SP; x_we = 1'b1; end
                    4'hB: begin agu_a_sel = A_SP; y_we = 1'b1; end
                    4'hC: begin agu_a_sel = A_SP; agu_b_sel = B_SEXT;
                                sp_we = 1'b1; end               // ADDW SP,#d8
                    4'hD: begin agu_a_sel = A_SP; agu_b_sel = B_ZEXT;
                                x_we = 1'b1; end                // LEA X
                    default: begin agu_a_sel = A_SP; agu_b_sel = B_ZEXT;
                                y_we = 1'b1; end                // LEA Y
                endcase
            end
            else if (p_sys) begin                   // CLV
                f_clv = 1'b1;
            end
            else if (p_mul) begin                   // multiply setup
                x_we_mul = 1'b0;
                xl_we = 1'b1; xh_we = 1'b1;         // X <- {$00, Rd}
                bsrc_ra = 1'b1;
                tmp_we = 1'b1;                      // TMP <- Rs
                nxt = S_MULT; nxt_step = 3'd0;
                at_boundary = 1'b0;
            end
        end
        endcase

        // One place where an instruction ends. busrq > nmi > irq, and
        // the interrupt is set up here so that S_PUSH starts the entry
        // sequence on the very next cycle.
        if (at_boundary) begin
            nxt      = nxt_boundary;
            retire   = 1'b1;
            set_int  = boundary_int;
            clr_nmi  = boundary_int;
            set_iack = boundary_int;
            vec_we   = boundary_int;
            nxt_vec  = nmi_pending ? V_NMI : V_IRQ;
        end

        // Nothing at all happens in a cycle whose memory access has not
        // completed. Address and strobes are already stable because the
        // registers feeding them are.
        if (!adv) begin
            nxt = state; nxt_step = step;
            ir_we = 1'b0; tmp_we = 1'b0; tmph_we = 1'b0;
            reg_we = 1'b0; flag_we = 1'b0;
            pc_we_agu = 1'b0; pc_we_bus = 1'b0;
            x_we = 1'b0; y_we = 1'b0; sp_we = 1'b0; x_we_mul = 1'b0;
            xl_we = 1'b0; xh_we = 1'b0; yl_we = 1'b0; yh_we = 1'b0;
            f_we_bus = 1'b0; f_clc = 1'b0; f_sec = 1'b0;
            f_ei = 1'b0; f_di = 1'b0; f_clv = 1'b0;
            z16_we = 1'b0; mul_flags = 1'b0;
            set_halt = 1'b0; clr_nmi = 1'b0;
            set_int = 1'b0; clr_int = 1'b0;
            set_iack = 1'b0; clr_iack = 1'b0;
            vec_we = 1'b0; retire = 1'b0;
        end
    end

    // ---------------------------------------------------- bus outputs

    assign mem_addr = addr_r ? agu_r : agu_a;

    always @* case (wd_sel)
        WD_F:    mem_wdata = flags;
        WD_HI:   mem_wdata = w16[15:8];
        WD_LO:   mem_wdata = w16[7:0];
        default: mem_wdata = ra;
    endcase

    wire [7:0] bsrc = bsrc_ra ? ra : mem_rdata;

    // The 16-bit value being written back, for the Z-from-16-bits cases
    wire [15:0] w16res = x_we_mul ? mul_next : agu_r;

    assign busak    = (state == S_BUSAK);
    assign o_fetch  = (state == S_FETCH) | (state == S_FETCH2);
    assign o_halted = halted;
    assign o_iack   = iack_r;
    assign o_retire = retire;

    // ================================================================
    // Sequential
    // ================================================================

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= S_RESET;
            step  <= 3'd0;
            pc    <= 16'h0000;
            sp    <= 16'hFFF8;      // first push lands at $FFF7
            x     <= 16'h0000;
            y     <= 16'h0000;
            r0 <= 8'h00; r1 <= 8'h00; r2 <= 8'h00; r3 <= 8'h00;
            fc <= 1'b0; fz <= 1'b0; fn <= 1'b0; fv <= 1'b0; fi <= 1'b0;
            ir <= 8'h00; p2 <= 1'b0; tmp <= 8'h00; tmph <= 8'h00;
            vec_sel <= V_RESET;
            in_int <= 1'b0; iack_r <= 1'b0; halted <= 1'b0;
            nmi_d <= 1'b0; nmi_pending <= 1'b0;
        end else begin
            state <= nxt;
            step  <= nxt_step;

            // NMI is edge sensitive and cannot be masked
            nmi_d <= nmi;
            if (nmi & ~nmi_d) nmi_pending <= 1'b1;
            else if (clr_nmi) nmi_pending <= 1'b0;

            if (vec_we)  vec_sel <= nxt_vec;
            if (set_int) in_int  <= 1'b1;
            if (clr_int) in_int  <= 1'b0;
            if (set_iack) iack_r <= 1'b1;
            if (clr_iack) iack_r <= 1'b0;
            if (set_halt) halted <= 1'b1;
            if (set_int)  halted <= 1'b0;

            if (ir_we)   begin ir <= mem_rdata; p2 <= (state == S_FETCH2); end
            if (tmp_we)  tmp  <= (state == S_EXEC) ? rb : mem_rdata;
            if (tmph_we) tmph <= mem_rdata;

            if (pc_we_agu) pc <= agu_r;
            if (pc_we_bus) pc <= {mem_rdata, tmp};

            if (x_we)     x <= agu_r;
            if (x_we_mul) x <= mul_next;
            if (y_we)     y <= agu_r;
            if (sp_we)    sp <= agu_r;

            // MUL setup drives both halves at once: X <- {$00, Rd}
            if (xl_we) x[7:0]  <= bsrc;
            if (xh_we) x[15:8] <= (state == S_EXEC && p_mul) ? 8'h00 : bsrc;
            if (yl_we) y[7:0]  <= bsrc;
            if (yh_we) y[15:8] <= bsrc;

            if (reg_we) case (rd_idx)
                2'd0: r0 <= alu_r;  2'd1: r1 <= alu_r;
                2'd2: r2 <= alu_r;  default: r3 <= alu_r;
            endcase

            // ---- flags
            if (flag_we) begin
                if (alu_set_c)  fc <= alu_c;
                if (alu_set_zn) begin fz <= alu_z; fn <= alu_n; end
                if (alu_set_v)  fv <= alu_v;
            end
            if (z16_we)    fz <= ~|w16res;             // INCW / DECW
            if (mul_flags) begin
                fz <= ~|mul_next; fn <= mul_next[15];
                fc <= 1'b0;       fv <= 1'b0;
            end
            if (f_we_bus) begin                        // POP F, RETI
                fc <= mem_rdata[0]; fz <= mem_rdata[1]; fn <= mem_rdata[2];
                fv <= mem_rdata[3]; fi <= mem_rdata[4];
            end
            if (f_clc) fc <= 1'b0;
            if (f_sec) fc <= 1'b1;
            if (f_clv) fv <= 1'b0;
            if (f_ei)  fi <= 1'b1;
            if (f_di)  fi <= 1'b0;
        end
    end

endmodule

`default_nettype wire
