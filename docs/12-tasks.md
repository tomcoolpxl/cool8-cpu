# 12. Commands, and the runner that names them

Every command this project has is named in `package.json` and run by
`tools/run.mjs`. That file is the vocabulary: if a command is not in it,
it is not a command, it is something someone typed once.

```
npm test                 every software suite, in parallel
npm test -- interp asm   just those two
npm test -- --group rtl  the RTL side (cosim: the gate for any RTL change)
npm run check            encoding tables and the CPU self-test
npm run build            boot ROM, basic.bin, BOOT.BIN, with sizes
npm run bench            the interpreter benchmarks
npm run prof             where the interpreter's clocks go
npm run cosim            RTL against the emulator
npm run list             everything the runner knows about
```

Node runs none of the machine. It spawns Python, and what it buys is the
part that was being done by hand in a shell loop for a year:

- **The suites run at once.** Thirteen of them, serially, is minutes of
  waiting on `test_run` and `test_basic` while eleven cores idle.
- **Each job gets its own build directory**, `sim/build/<id>`, passed as
  `COOL8_BUILD`. Every `sim/*.py` honours it. This is not a nicety:
  thirteen suites all compile `basic.bin`, and without it parallel runs
  write it on top of each other and fail in ways that look like bugs in
  the machine.
- **Only failures print.** A pass is one line and a duration.
- **The exit code is the answer**, so it can gate a commit.

A suite counts as passed when it exits 0 *and* the word `FAIL` does not
appear in its output — two of them report a count rather than a status,
and an exit code alone would take their word for it.

## The jobs

### `sw` — the software suite (`npm test`)

| | |
|---|---|
| `interp` | the interpreter on the editor's stored form |
| `asm` | the on-machine assembler, byte-identical to `tools/cool8asm.py` |
| `basic` | the screen editor, typed at |
| `run` | `RUN`, plus `INKEY` and `KEY` driven from the PS/2 port |
| `boot_basic` | reset → autoboot → relocate → BASIC → a keypress, off a flash image |
| `autoboot` | autoboot and the monitor's flash write |
| `corpus` | the compiler against its corpus |
| `emit` | the code emitter, gated against the assembler |
| `comp` | the self-hosted compiler |
| `lex` | the compiler's front end |
| `fs` | the filesystem, both implementations |
| `bas` | the code-size gate: within 15 % of hand-written |
| `names` | global name collisions across the system image |

### `rtl`

`cosim` is **the gate for any RTL change**. It takes about a minute. Run
it; do not reason about whether it would pass.

The rest of the RTL tests are not in the runner because they are slower
than the gate and are run deliberately, one at a time:

```bash
python sim/cosim.py mul        # exhaustive multiply (~2.5 min)
python sim/test_loader.py      # UART and loader, over a bit-banged wire
python sim/test_spram.py       # SPRAM controller against a byte array
python sim/test_boot.py        # boot ROM, overlay, a cold boot
python sim/test_soc.py         # the I/O page, and the whole machine
python sim/test_load.py        # the host loader, against the RTL
python sim/test_video.py       # every mode and visible pixel. --refresh
                               #   updates docs/img/
python sim/test_vram.py        # video RAM and its four-way arbiter
python sim/test_vport.py       # the CPU's indirect VRAM port
python sim/test_ps2.py         # the keyboard port, against a keyboard
python sim/test_flash.py       # the SPI reader, against a flash
python sim/test_monitor.py     # M6's gate: type at it and it answers
python sim/mutate.py           # break the RTL on purpose; require a fail
python sim/synth.py            # hygiene, LUT/FF count, gate estimate
python sim/timing.py           # measured clocks per encoding
python tools/mkbit.py          # the bitstream: yosys, nextpnr, icepack
```

### `check` and `build`

`check` runs `opcodes --check`, `mkasmtab --check` and the emulator's
self-test — the three that verify a generated table still matches what
generated it.

`build` produces the boot ROM and the system image and **prints the
sizes**, because the system has to stay inside `$A000-$FDFF` and nothing
else warns you as it fills.

## Adding a command

Add it to the relevant list in `package.json`'s `cool8` block: an `id`,
the `run` path, optional `args`, and an `about` line that says what it
proves. `slow: true` moves it to the front of the queue, since with a
fixed pool the long pole sets the wall clock.

Nothing else needs changing. `npm run list` picks it up.

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
`npm test` works on a fresh clone with Node present.
