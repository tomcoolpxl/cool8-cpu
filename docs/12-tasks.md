# 12. Commands, and the runner that names them

Every command this project has is named in `package.json` and run by
`tools/run.mjs`. That file is the vocabulary: if a command is not in it,
it is not a command, it is something someone typed once.

```
npm test                 every software suite, in parallel
npm test -- interp asm   just those two
npm run test:rtl         the RTL side (cosim is the gate for any RTL change)
npm run test:board       the physical board, one job at a time
npm run test:all         software and RTL together
npm run check            encoding tables and the CPU self-test
npm run build            boot ROM, basic.bin, BOOT.BIN, with sizes
npm run bench            the interpreter benchmarks
npm run prof             where the interpreter's clocks go
npm run list             everything the runner knows about
```

**Three phases, and they are not the same kind of thing.** `sw` runs on
the emulator and is the fast inner loop. `rtl` runs iverilog against the
hardware description — slower, and where a change to `sw/boot.asm`
actually gets checked, since the boot ROM is compiled into the
bitstream. `board` talks to real hardware over USB.

**Long jobs report that they are alive.** Every ten seconds the runner
names what is still going and for how long — `test_run` takes four
minutes and `cosim` a minute, and a job that says nothing for that long
cannot be told from one that has hung. `COOL8_HEARTBEAT_MS` changes the
interval.

**Board jobs are exclusive and drop the pool to one.** There is one USB
device and no lock on it; two `icesprog` processes at once do not fail
cleanly, they interleave on the SPI and hand back a readback full of
zeroes — which reads as a corrupt bitstream rather than as a corrupt
test. That happened here the first time `test:board` ran two jobs in
parallel. Mark any job that touches hardware `"exclusive": true`.

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

### `rtl` — `npm run test:rtl`

`cosim` is **the gate for any RTL change**. It takes about a minute. Run
it; do not reason about whether it would pass.

`monitor` is the one that matters after a change to `sw/boot.asm`,
`sw/kbd.asm` or `sw/keymap.asm`: it boots the whole SoC cold on the
parameters the bitstream carries and types at it on **both** the serial
line and the PS/2 clock, so a scancode takes the same path it takes on
the bench. That is where a keyboard change is really checked — the
emulator models the PS/2 port, but only this runs the receiver, the
parity check and the FIFO.

| | |
|---|---|
| `cosim` `boot` `soc` | the CPU and the machine against the emulator |
| `ps2` `flash` `spram` `loader` | one peripheral each |
| `monitor` | type at the whole SoC, serial and PS/2 |
| `video` `vram` `vport` | every mode and visible pixel |

Not in the runner, because they are slower than the gate and are run
deliberately:

```bash
python sim/cosim.py mul        # exhaustive multiply (~2.5 min)
python sim/test_load.py        # the host loader, against the RTL
python sim/test_video.py --refresh    # also updates docs/img/
npm run mutate                 # break the RTL on purpose; require a fail
npm run synth                  # hygiene, LUT/FF count, gate estimate
npm run timing                 # measured clocks per encoding
```

### `board` — `npm run test:board`

| | |
|---|---|
| `probe` | the board answers at all: the SPI flash identifies itself |
| `flash` | both halves read back off the chip and compared byte for byte |

Neither writes anything. Both are exclusive.

### `rust` — `npm run test:rust`

| | |
|---|---|
| `rust` | the Rust fast runner against the emulator and the machine: trace, memory, VRAM and UART parity over cosim's programs and a real flash-to-BASIC boot, then the measured speeds |

One job, its own group rather than `sw`, because it needs `cargo` and
`npm test` must keep working on a fresh clone with only Node and Python
present. Everything about the runner — what it is for, what is
generated, what the gate proves — is in [RUST_PORT.md](../RUST_PORT.md).

**What the board phase cannot check** is that the machine boots to a
picture. `LOADER` defaults to 0 ([D40](01-decisions.md)) so there is no
way to read the framebuffer over the wire, and BASIC writes to the video
rather than to the UART — a serial terminal shows nothing even when it
is working perfectly. That needs eyes on the VGA output and a PS/2
keyboard in the socket, and it is the one part of this that is not
automatable.

### The board

```
npm run bit             build the bitstream: yosys, nextpnr, icepack
npm run disk            a flash image with BASIC on volume 0. No board touched
npm run flash           bitstream + BASIC: the whole board
npm run flash:fpga      the bitstream only, to flash offset 0
npm run flash:system    BASIC only, to flash offset $100000
npm run flash:verify    read BOTH halves back off the board and compare
npm run console -- --port COM6      the board's text screen, on the PC
npm run load -- --port COM6 --load build/BOOT.BIN --at 0x200 --go 0x200
```

**The boot ROM is inside the bitstream.** There is no separate step for
it: a change to `sw/boot.asm`, `sw/kbd.asm` or `sw/keymap.asm` reaches
the board through `npm run bit` and `npm run flash:fpga`, and through
nothing else. `npm run rom` builds `boot.hex` for the *emulator*.

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
