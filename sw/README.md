# sw

COOL8 software: boot ROM, monitor, demos, test programs.

| File | What it is |
|---|---|
| `boot.asm` | The boot ROM. Built into the EBR image by `tools/mkrom.py`; see [docs/04-system.md §3](../docs/04-system.md) |
| `lib.asm` | The M2 gate corpus — 26 routines, verified by `sim/test_corpus.py` |
| `gfx.asm`, `frames.asm` | The graphics half of the same corpus |

`boot.asm` is the one piece of this that is not a test: it is what the
machine runs at power-on. It is assembled into `sim/build/boot.hex` and
never committed, because a checked-in image that has drifted from its own
source is a boot ROM nobody can trust.
