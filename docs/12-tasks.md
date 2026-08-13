# 12. Commands, and the runner that names them

Every command this project has is named in `pyproject.toml`: the job
table under `[tool.cool8.jobs]` for the suites, `[tool.poe.tasks]` for
the direct commands. That file is the vocabulary: if a command is not
in it, it is not a command, it is something someone typed once.

**The runner is pytest**, fed the job table by the one shim in
`sim/runner/test_jobs.py` — the shim shells each suite exactly as a
person would and holds no policy of its own. pytest-xdist runs jobs in
parallel (`-n auto`, the default), a group is a marker (`-m rtl`), and
`--durations` says where the time went. **poethepoet** (`poe`) names
the rest; `pip install -e ".[dev]"` once installs all three. Use
`python -m pytest` / `python -m poethepoet` where Scripts is not on
PATH.

```
poe test                 every software suite, in parallel  (pytest)
pytest -k "interp or asm"    just those two
poe test-rtl             the RTL side (cosim is the gate for any RTL change)
poe test-board           the physical board, one job at a time
poe test-all             software and RTL together
poe check                the generated tables, against what generated them
poe build                boot ROM, basic.bin, BOOT.BIN, with sizes
poe bench                the language benchmark
poe prof                 where the interpreter's clocks go
poe list                 everything the runner knows about
```

**Three phases, and they are not the same kind of thing.** `sw` runs on
the machine — `rust/`, driven through `tools/cool8rsvm.py`, so it needs
`cargo` and there is no fallback — and is the fast inner loop. `rtl`
runs iverilog against the hardware description: slower, and where a
change to `sw/boot.asm` actually gets checked, since the boot ROM is
compiled into the bitstream. `board` talks to real hardware over USB.

**Board jobs must not run in parallel.** There is one USB device and no
lock on it; two `icesprog` processes at once do not fail cleanly, they
interleave on the SPI and hand back a readback full of zeroes — which
reads as a corrupt bitstream rather than as a corrupt test. That
happened here. `poe test-board` therefore carries `-n 0`; never run the
board group with xdist enabled.

What the runner buys is the part that was being done by hand in a shell
loop for a year:

- **The suites run at once.** A dozen of them, serially, is minutes of
  waiting while eleven cores idle.
- **Each job gets its own build directory**, `sim/build/jobs/<group>-<id>`,
  passed as `COOL8_BUILD`. Every `sim/*.py` honours it. This is not a
  nicety: the suites all compile `basic.bin`, and without it parallel
  runs write it on top of each other and fail in ways that look like
  bugs in the machine.

  **The trap that comes with it:** a suite that reads an artifact
  *another* suite produced will not find it, because that one wrote to
  its own directory. `sim/test_vm.py` hit this and passed in 0.19 s
  having compared nothing. If a suite consumes another's output, it
  must search the sibling directories — and **treat a missing input as
  a failure, never a skip**. A check that cannot run has not passed.
- **Only failures print their output.** A pass is a dot and a duration.
- **The exit code is the answer**, so it can gate a commit.

A suite counts as passed when it exits 0 *and* the word `FAIL` does not
appear in its output — two of them report a count rather than a status,
and an exit code alone would take their word for it. The shim enforces
this, not the suites.

## Writing a suite

Every suite is an ordinary script: it builds something, drives the
machine, prints a line per check, and returns an exit code. What it
does **not** do is carry its own copy of any of that.

```python
import harness as H
import cool8rsvm as vm

def main():
    code, syms = H.build_bas("basic.bas")
    m = vm.Machine()
    ...
    H.check(m.shows("42"), "RUN prints its answer")
    return H.report()
```

`sim/harness.py` owns building, checking and the paths;
`sim/toolchain.py` owns iverilog, yosys and the RTL file lists
(`T.build`, `T.run`, `T.cells`, `T.CORE`). Both are described in
[AGENTS.md](../AGENTS.md) and [10-debugging.md](10-debugging.md), and
using them is standing rule 4 — not a style note. A suite that rolls
its own is a second implementation of the thing it is testing with.

**A suite that reads another suite's artifact must search for it and
fail loudly when it is missing** — see the per-job build directories
above.

## The jobs

### `sw` — the software suite (`poe test`)

| | |
|---|---|
| `interp` | the interpreter on the editor's stored form |
| `lib` | M14 -- `sw/demo.bas` against `sw/demo.asm`, work per frame |
| `asm` | the on-machine assembler, byte-identical to `tools/cool8asm.py` |
| `basic` | the screen editor, typed at |
| `run` | `RUN`, plus `INKEY` and `KEY` driven from the PS/2 port |
| `boot_basic` | reset → autoboot → relocate → BASIC → a keypress, off a flash image |
| `autoboot` | autoboot and the monitor's flash write |
| `corpus` | the compiler against its corpus |
| `fs` | the filesystem, both implementations |
| `bas` | the code-size gate: within 15 % of hand-written |
| `memmap` | in the `check` group — [`tools/memmap.py`](../tools/memmap.py) is the one machine-readable memory map, the same arrangement `opcodes.py` has for the encoding. It verifies itself against the equates every `sw/*.asm` actually declares, and refuses two names on one byte of page 0. **Import from it rather than writing an address down twice**: `sim/test_interp.py` used to carry its own `VARS = 0x0040` and `sim/build_basic.py` its own `ORG`/`TOP` |
| `fp` | the loadable float package of [D62](01-decisions.md#d62--floating-point-ships-as-a-loadable-library-not-as-part-of-the-system) — arithmetic, decimal text, trig. **It also prints its own size and timing table**, which is what the decision entries quote rather than a hand-typed copy. `--trace <op> <x> <y> <label> <n>` breakpoints a routine and decodes forward; that is how `fdiv16` was caught answering the wrong question |
| `names` | global name collisions across the system image |

The shelved on-machine compiler's gates — `sim/test_comp.py`,
`sim/test_emit.py`, `sim/test_lex.py` — are **not in the runner**: they
cost minutes to gate code that ships nowhere
([11-compiler.md](11-compiler.md)). Run them deliberately before
touching `sw/comp.bas`, `sw/emit.bas` or `sw/lex.bas`, and before any
change to the token table or the stored-program format, which both
sides of those diffs share.

### `rtl` — `poe test-rtl`

`cosim` is **the gate for any RTL change**. It takes about a minute. Run
it; do not reason about whether it would pass.

`monitor` is the one that matters after a change to `sw/boot.asm`,
`sw/kbd.asm` or `sw/keymap.asm`: it boots the whole SoC cold on the
parameters the bitstream carries and types at it on **both** the serial
line and the PS/2 clock, so a scancode takes the same path it takes on
the bench. That is where a keyboard change is really checked — the
machine models the PS/2 port at FIFO level, but only this runs the
receiver, the parity check and the FIFO itself.

| | |
|---|---|
| `cosim` `boot` `soc` | the CPU and the machine against the RTL |
| `ps2` `flash` `spram` `loader` | one peripheral each |
| `monitor` | type at the whole SoC, serial and PS/2 |
| `video` `vram` `vport` | every mode and visible pixel |
| `snd` | the sound engine — **and it writes `build/snd.hex`**, the golden `test_vm` gates against |

Not in the runner, because they are slower than the gate and are run
deliberately:

```bash
python sim/cosim.py mul        # exhaustive multiply (~2.5 min)
python sim/test_load.py        # the host loader, against the RTL
python sim/test_video.py --refresh    # also updates docs/img/
poe mutate                 # break the RTL on purpose; require a fail
poe synth                  # hygiene, LUT/FF count, gate estimate
poe timing                 # measured clocks per encoding
```

### Two that answer a question rather than gate a change

Neither is a test and neither belongs in the runner. Both exist because
a decision was resting on a guess.

```bash
python sim/cpi.py              # cycles per instruction, and what it
                               # costs to add one. ~1 min
python tools/mkbit.py --seeds 6   # Fmax per clock across placer seeds
                               # ~70 s for the first, ~40 s each after
```

**`sim/cpi.py`** measures CPI on three code shapes — native, bytecode
and the real interpreter — and turns it into the break-even clock for
any change that adds a cycle to the fetch. It priced
[D59](01-decisions.md#d59--cpi-is-259-and-pipelining-the-fetch-is-a-bet-rather-than-an-optimisation)
in minutes, against a question that had been open for four milestones.
Re-run it whenever the cycle table moves: **at CPI 2.59 one added cycle
per instruction is a 39 % penalty**, which is what makes
per-instruction overheads so expensive on this machine.

**`--seeds N`** is the honest way to read Fmax. One nextpnr run is not a
measurement — the placer spread is around 6 %, and
[D38](01-decisions.md#d38--the-fetch-path-next-state-is-decoded-flat-and-it-bought-area-rather-than-speed)
is the write-up of a single-seed result that was noise and was believed
for a round. Synthesis is deterministic, so yosys runs once and only
placement repeats. It reports `sclk` and `pclk` separately, which the
plain build did not: it used to print whichever clock nextpnr mentioned
last.

### `board` — `poe test-board`

| | |
|---|---|
| `probe` | the board answers at all: the SPI flash identifies itself |
| `flash` | both halves read back off the chip and compared byte for byte |

Neither writes anything. Both are exclusive.

### `rust` — `poe test-rust`

| | |
|---|---|
| `vm` | the machine against RTL-dumped goldens: every pixel of three frames (text, tiles, sprites over a bitmap), 4096 sound samples, and a boot to the monitor answering `D F000` with the bytes a real board gave |

Its own group rather than `sw` because it needs the RTL dumps in
`sim/build` — `sim/test_video.py` and `sim/test_snd.py` produce them,
and it SKIPs rather than fails when they are absent. Everything about
the machine — what it is, what is generated, what the gates prove — is
in [RUST_PORT.md](../RUST_PORT.md).

**What the board phase cannot check** is that the machine boots to a
picture. `LOADER` defaults to 0 ([D40](01-decisions.md)) so there is no
way to read the framebuffer over the wire, and BASIC writes to the video
rather than to the UART — a serial terminal shows nothing even when it
is working perfectly. That needs eyes on the VGA output and a PS/2
keyboard in the socket, and it is the one part of this that is not
automatable.

### The board

```
poe bit             build the bitstream: yosys, nextpnr, icepack
poe disk            a flash image with BASIC on volume 0. No board touched
poe flash           bitstream + BASIC: the whole board
poe flash-fpga      the bitstream only, to flash offset 0
poe flash-system    BASIC only, to flash offset $100000
poe flash-verify    read BOTH halves back off the board and compare
poe console -- --port COM6      the board's text screen, on the PC
poe load -- --port COM6 --load build/BOOT.BIN --at 0x200 --go 0x200
```

> **`console` and `load` need a `LOADER(1)` bitstream, which is not the
> one you have.** Both talk to the hardware loader, and `LOADER`
> defaults to 0 ([D40](01-decisions.md)) — so on a shipping board they
> reach nothing. `poe board-screen` is the screen reader that works
> there: it asks BASIC to POKE the framebuffer at the UART, which needs
> no loader. Build with `LOADER(1)` when a board will not boot and you
> need the bus-master read-back.

**The boot ROM is inside the bitstream.** There is no separate step for
it: a change to `sw/boot.asm`, `sw/kbd.asm` or `sw/keymap.asm` reaches
the board through `poe bit` and `poe flash-fpga`, and through
nothing else. `poe rom` builds `boot.hex` for the *simulators*.

Flash holds two unrelated things and every way of confusing them is
destructive, so `tools/flash.py` makes the mistakes impossible rather
than documenting them a fifth time:

| offset | what | if you get it wrong |
|---|---|---|
| `0` | the FPGA bitstream | the board does nothing until reprogrammed |
| `$100000` | volume 0, where `BOOT.BIN` lives | boots to the monitor, looking like a BASIC bug |

It refuses to write a disk image at offset 0, refuses a bitstream
anywhere else, refuses an image whose volume 0 has no `BOOT.BIN`, and
**refuses `-e` outright** — that is a whole-chip erase, not a sector
erase, and it takes the bitstream with it.

**The image is not what goes to the board.** `build/cool8.img` is the
whole 8 MB flash *with volume 0 at `$100000` inside it*, because that is
what `vm.Machine(flash_path=…)` wants. Handing it to
`icesprog -o 0x100000` writes 8 MB starting at 1 MB — a megabyte off the
end of the chip, and minutes of SPI to do it. Only volume 0's used
extent is written: 28 KB for BASIC, about two seconds. That mistake was
made here and it presented as a hang, which is why:

**Programming streams its output and prints elapsed seconds when it goes
quiet.** A tool that says nothing for a minute cannot be told from one
that has died. Measured on the board: the bitstream writes in 6 s and
reads back in 4, volume 0 writes in 2 s — with a heartbeat every 2 s
throughout.

**Every write reads itself back and compares**, both halves, and that is
the check rather than the exit code — `icesprog` reports `done` for a
zero-byte write exactly as happily as for a real one, which is how a
wrong length went unnoticed here once. A bitstream that is 99 % right is
a board that does nothing and gives no clue why.

| | offset | bytes | write | verify |
|---|---|---|---|---|
| bitstream | `0` | 104,090 | 6 s | 4 s |
| volume 0 | `$100000` | 28,672 | 2 s | 1 s |

`--drive` programs the bitstream by copying onto the iCELink drive
instead, which is the documented drag-and-drop route and needs no
`icesprog`. It is fire-and-forget: the debugger takes the file and tells
you nothing about what reached the chip, so it cannot be verified.
Prefer `icesprog`.

Programming the bitstream works either way: `icesprog`, or a copy onto
the iCELink drive, which is the programming operation on that board.
Reaching a flash *offset* needs `icesprog` — the drive takes a bitstream
and nothing else. `icesprog` **ships in the OSS CAD Suite's `bin`**
([05-board.md](05-board.md)), so it is found by `OSS_CAD_SUITE` or by
the suite being on `PATH`, exactly like `yosys`. A bare `which` in a
shell that has not set that up says "no" and means nothing.

### `check` and `build`

`check` runs `opcodes --check`, `mkasmtab --check`, `mkrsopc --check`
and the emulator's self-test — the ones that verify a generated table
still matches what generated it.

`build` produces the boot ROM and the system image and **prints the
sizes**, because the image grows down from `$FEFF` into a finite gap
above system storage and nothing else warns you as it fills. `check`
fails the build when that gap is gone and warns from 256 bytes out.

## Adding a command

Add it to the relevant job list in `pyproject.toml`'s `[tool.cool8.jobs]`: an `id`,
the `run` path, optional `args`, and an `about` line that says what it
proves. `slow: true` moves it to the front of the queue, since with a
fixed pool the long pole sets the wall clock.

Nothing else needs changing. `poe list` picks it up.

## Shells

**Run the RTL suites from PowerShell, not from the Bash tool.** Under
Bash, `yosys.exe` exits 0 having printed nothing and every downstream
script then fails on empty output, which reads like a broken script
rather than a broken shell.

There are two `oss-cad-suite` installs on this machine; use the `eda\`
one.

## What is generated

`sim/build/` and everything under it, including the per-job
subdirectories. `build/` is the bitstream's. Both are gitignored, as is
`node_modules/` — there are no dependencies, so nothing is installed and
`poe test` works on a fresh clone with Node present.
