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
| `test_soc.py` | The I/O page, the machine booting cold, and the SoC's area |
| `test_load.py` | `tools/cool8load.py`: its wire format against the RTL, its command loops against a fake board |
| `test_video.py` | The raster, the font, text mode 0 — and the frames README.md shows |
| `asm/` | Test programs the CPU runs in `cool8_soc_tb`, assembled on every run |
| `tb/cool8_tb.v` | Core against a byte-wide memory with programmable wait states |
| `tb/cool8_bus_tb.v` | The ASIC path: pad wrapper, two 74HC573 latches, one SRAM |
| `tb/cool8_loader_tb.v` | UART and loader, bit-banged 8N1 in, a real core arbitrating the bus |
| `tb/cool8_spram_tb.v` | The SPRAM controller alone, driven as a bus master |
| `tb/cool8_spram_cpu_tb.v` | The core running out of two `SB_SPRAM256KA`, traced for `cosim.py` |
| `tb/cool8_rom_tb.v` | 4 KB read back through the port — runs against the RTL *and* the netlist |
| `tb/cool8_mem_tb.v` | The ROM overlay: what answers where, and what `BOOTRAM` does to a reset |
| `tb/cool8_boot_tb.v` | Cold boot from undefined SPRAM, then the loader's `BOOTRAM` path |
| `tb/cool8_soc_tb.v` | The I/O page: what wins the decode, reached from the loader and then from the CPU |
| `tb/cool8_soc_boot_tb.v` | The whole machine, cold, on the parameters the bitstream will carry |
| `tb/cool8_top_tb.v` | The board wrapper: the reset it manufactures, and the LED pins' polarity |
| `tb/cool8_wire_tb.v` | The serial port as a pipe, so the host tool can be tested against the machine |
| `tb/cool8_vga_tb.v` | The raster against a golden model of a raster, output for output |
| `tb/cool8_video_tb.v` | Every mode, every visible pixel, against a model written from the documents; and screens off the RGB pins with the two clocks running apart |

```bash
python sim/cosim.py all      # directed, random, interrupts, ASIC bus, SPRAM
python sim/cosim.py mul      # 65536 exhaustive operand pairs
python sim/test_loader.py    # UART and loader
python sim/test_spram.py     # SPRAM controller
python sim/test_boot.py      # boot ROM, overlay, cold boot
python sim/test_soc.py       # the I/O page, and the machine as a whole
python sim/test_load.py      # the host loader
python sim/test_video.py     # the raster, and build/frame.png
python sim/synth.py
python sim/timing.py
```

`test_soc.py` assembles `asm/soc_*.asm` into `build/` on every run and
`cool8_soc_tb` loads them over the wire, so the program the CPU executes
is the program in the file rather than a byte array that has drifted
from its comment. It also runs a synthesis gate for `cool8_soc`, which
`synth.py` does not cover — that one is about `rtl/core` and the ASIC
rules, and the SoC's own hazards are different. A combinational loop
through the bus is the interesting one, and it is a warning rather than
an error, so it has to be read out of the yosys transcript deliberately.

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
