# rtl/core

The CPU core, and nothing else.

No vendor primitives, no inferred RAM, no tri-state, no clock gating,
no asynchronous reset. This is what goes to the ASIC. See
docs/03-microarchitecture.md section 1. Verilog-2001, so that every tool
in the chain accepts it with no dialect flags.

| File | Contents |
|---|---|
| `cool8_core.v` | Registers, decoder, control FSM, writeback |
| `cool8_alu.v` | The 8-bit ALU and flag generator — one adder |
| `cool8_agu.v` | The single 16-bit adder and its operand muxes |

Checked instruction by instruction against the machine (`rust/`); see
`sim/`. `python sim/synth.py` enforces the rules above.
