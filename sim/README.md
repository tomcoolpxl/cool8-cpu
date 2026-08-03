# sim

Testbenches and co-simulation harnesses.

The golden model lives in `tools/cool8emu.py`; this directory drives RTL
against it and compares architectural state after every instruction, and
the whole 64 KB address space at the end of the run.

| File | Contents |
|---|---|
| `cosim.py` | The driver: builds programs, runs both models, diffs, reports the first divergence with disassembly |
| `progen.py` | Program generators — one probe per encoding, and constrained-random streams. Built from `tools/opcodes.py`, so a new instruction is tested by adding it to the table |
| `synth.py` | Synthesis hygiene and the area gate |
| `timing.py` | Measures what every encoding costs, in clocks |
| `test_corpus.py` | The 26-routine software corpus, against results computed in Python |
| `test_loader.py` | The SoC serial path, across baud dividers and wait states |
| `test_spram.py` | The SPRAM controller against its own 64 KB reference |
| `test_boot.py` | The boot ROM image, the overlay, and the machine booting |
| `tb/cool8_tb.v` | Core against a byte-wide memory with programmable wait states |
| `tb/cool8_bus_tb.v` | The ASIC path: pad wrapper, two 74HC573 latches, one SRAM |
| `tb/cool8_loader_tb.v` | UART and loader, bit-banged 8N1 in, a real core arbitrating the bus |
| `tb/cool8_spram_tb.v` | The SPRAM controller alone, driven as a bus master |
| `tb/cool8_spram_cpu_tb.v` | The core running out of two `SB_SPRAM256KA`, traced for `cosim.py` |
| `tb/cool8_rom_tb.v` | 4 KB read back through the port — runs against the RTL *and* the netlist |
| `tb/cool8_mem_tb.v` | The ROM overlay: what answers where, and what `BOOTRAM` does to a reset |
| `tb/cool8_boot_tb.v` | Cold boot from undefined SPRAM, then the loader's `BOOTRAM` path |

```bash
python sim/cosim.py all      # directed, random, interrupts, ASIC bus, SPRAM
python sim/cosim.py mul      # 65536 exhaustive operand pairs
python sim/test_loader.py    # UART and loader
python sim/test_spram.py     # SPRAM controller
python sim/test_boot.py      # boot ROM, overlay, cold boot
python sim/synth.py
python sim/timing.py
```

Everything involving SPRAM, EBR or the boot ROM uses the toolchain's own
`SB_*` models (`share/yosys/ice40/cells_sim.v`), found through
`OSS_CAD_SUITE`. They are deliberately not vendored: the models have to
match the yosys that maps the design. Those builds run at `-g2012`
because that file uses default port values; everything in `rtl/` is
still Verilog-2001.

`test_boot.py` writes `build/boot.hex` from `sw/boot.asm` before it runs
anything, and `cool8_rom.v` reads that name relative to the working
directory — so the ROM tests run with `sim/build` as cwd.

Needs [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build) on
`PATH`, or `OSS_CAD_SUITE` pointing at its root. `sim/build/` is
generated and ignored.
