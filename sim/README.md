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
| `tb/cool8_tb.v` | Core against a byte-wide memory with programmable wait states |
| `tb/cool8_bus_tb.v` | The ASIC path: pad wrapper, two 74HC573 latches, one SRAM |

```bash
python sim/cosim.py all      # directed, random, interrupts, ASIC bus
python sim/cosim.py mul      # 65536 exhaustive operand pairs
python sim/synth.py
python sim/timing.py
```

Needs [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build) on
`PATH`, or `OSS_CAD_SUITE` pointing at its root. `sim/build/` is
generated and ignored.
