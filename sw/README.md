# sw

COOL8 software: boot ROM, monitor, demos, test programs.

| File | What it is |
|---|---|
| `boot.asm` | The boot ROM. Built into the EBR image by `tools/mkrom.py`; see [docs/04-system.md §3](../docs/04-system.md) |
| `monitor.asm` | The monitor: console, line editor, `D`/`E`/`U`/`G`/`L`, and the Set 2 scancode table. Included by `boot.asm` |
| `disasm.asm` | One instruction, printed. Included by `monitor.asm`'s side of the same image |
| `lib.asm` | The M2 gate corpus — 26 routines, verified by `sim/test_corpus.py` |
| `gfx.asm`, `frames.asm` | The graphics half of the same corpus |

`boot.asm` is the one piece of this that is not a test: it is what the
machine runs at power-on. It is assembled into `sim/build/boot.hex` and
never committed, because a checked-in image that has drifted from its own
source is a boot ROM nobody can trust.

The three files are one image. `boot.asm` `.include`s the other two, so
the whole thing is assembled at once and `tools/mkrom.py` refuses it if
anything lands in the I/O page's hole at `$FE00-$FEFF` or reaches past
the 4 KB window. **3028 of those 4096 bytes are used.**

The monitor is checked end to end by `sim/test_monitor.py`, which boots
the machine cold and types at it — over the serial line, and by clocking
Set 2 scancodes in on a PS/2 wire.
