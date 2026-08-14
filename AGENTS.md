# AGENTS.md

Notes for agents working on COOL8 — a clean-sheet 8-bit CPU and the
retro home computer around it, built on an iCE40UP5K FPGA and designed
to be fabricable on TinyTapeout.

## This file is a pointer, not a record

**`docs/` is the source of truth for everything about this project.**
This file exists to tell you where to look and how to work; it does not
restate what the documents say, and it must not start to.

When you learn something durable — a decision, a measurement, a
constraint, a piece of hardware behaviour — **write it into the relevant
document under `docs/`**, not here and not into a new file. An
architectural call gets a numbered entry in
[docs/01-decisions.md](docs/01-decisions.md) with the argument on both
sides. A measurement replaces the estimate it supersedes rather than
sitting next to it.

If you catch yourself adding a fact to this file, it belongs in `docs/`.
If a fact here has drifted from `docs/`, `docs/` is right and this file
is the bug.

**All project memory lives in this repository — in this file and the
documents it points at.** Nothing goes in an agent's own store outside
the repo. A note kept there is invisible to the user, invisible to
review, invisible to the next agent that clones this tree, and it cannot
be corrected when it goes stale. If something is worth remembering
between sessions, it is worth a commit.

## Standing rules

1. **Never touch the physical board without asking first.** Not to
   program it, not to read from it, not "just to check".
2. **Profile before optimising**, and report the number afterwards —
   including when it got worse (§"Debug and measure with the tooling").
3. **Report the size at every milestone**, not at the end.
4. **Investigate through the harness and the tooling — never a
   throwaway script.** The section below is not advice; it is how work
   is done here.
5. **Never move the memory map without asking first.** Every byte the
   text map moves down comes off `FREE` one for one — it is the user's
   BASIC memory, and "the image needs room" is not authority to spend
   it. When the image is short, the bytes come from dead reservations,
   from the image itself, or from a decision the user makes. D80 took
   5,120 bytes of `FREE` to buy growth room nobody had asked for, and
   the only reason it was caught is that the user read the number.

| Document | Owns, and is normative for |
|---|---|
| [00-goals.md](docs/00-goals.md) | Scope, the hard constraints C1–C3, non-goals, the FPGA resource budget |
| [01-decisions.md](docs/01-decisions.md) | Every architectural decision and why, plus what was rejected. Open questions |
| [02-isa.md](docs/02-isa.md) | The instruction set. **§1.2's flag table is normative** and wins over prose anywhere they conflict. §8 is measured cycle counts |
| [03-microarchitecture.md](docs/03-microarchitecture.md) | Datapath, control FSM, bus protocol, the TinyTapeout pin profile, and the synthesis, area and timing results |
| [04-system.md](docs/04-system.md) | Memory map, video, audio, keyboard, flash, boot sequence, and the monitor |
| [05-board.md](docs/05-board.md) | iCESugar pinout, PMODs, external circuits, BOM |
| [06-roadmap.md](docs/06-roadmap.md) | Milestones, what each one delivers, and its gate |
| [07-loader.md](docs/07-loader.md) | Loader wire protocol |
| [08-assembler.md](docs/08-assembler.md) | Assembler reference |
| [10-debugging.md](docs/10-debugging.md) | **The debug and profiling tooling, and the rules that came out of using it** |
| [11-compiler.md](docs/11-compiler.md) | The shelved self-hosted compiler, and the size arithmetic that shelved it |
| [12-tasks.md](docs/12-tasks.md) | **Every command, and the runner that names them.** What each job proves, the gates, and how to add one |
| [13-basic.md](docs/13-basic.md) | **COOL8 BASIC, the language reference** — every statement, function, operator, the graphics/sound set, floating point, and the size ceiling |
| [14-demos.md](docs/14-demos.md) | The demo disc — which drive it is, what a demo may assume, and why `mkdemos.py` types the sources at the machine rather than tokenising them on the host |

`README.md` is a summary derived from those. Keep it in step, but do not
put anything in it that is not already recorded properly somewhere else.

Two files are themselves normative, in code rather than prose:

- **`tools/opcodes.py`** — the single source of truth for the encoding.
  The assembler, disassembler and test generators all import
  it; nothing carries its own copy of the opcode map. Adding an
  instruction there makes it assemblable, disassemblable and tested with
  no other change. If you find yourself writing a second mnemonic table,
  stop.
  `tools/mkrsopc.py` generates `rust/src/optab.rs` from it, and
  `poe check` fails on drift.
- **`rust/` is the machine and `rtl/` is the hardware, and they are
  checked against each other** instruction by instruction (`sim/cosim.py`)
  and pixel by pixel (`sim/test_vm.py`). When the two disagree, one is
  wrong and `docs/02-isa.md` decides which. Do not resolve a
  co-simulation failure by changing whichever side is easier to change.

## The structural rule

`rtl/core/` is Verilog-2001 strictly: no vendor primitives, no inferred
RAM, no tri-state, no clock gating, no asynchronous reset. FPGA-only
logic lives in `rtl/soc/` and may use iCE40 primitives freely.

**The ASIC path is shelved and the rule stays anyway**
([D33](docs/01-decisions.md)). It costs nothing to keep the core
portable and it costs a rewrite to get it back, so break the rule only
where a measurement says it buys speed — not because it is now allowed.
Stated in full in [00-goals.md](docs/00-goals.md) C2 and
[03-microarchitecture.md](docs/03-microarchitecture.md) §1.

`python sim/synth.py` enforces it. Run it before calling an RTL change
done.

## Toolchain

**Most work needs none of it.** `poe test`, `poe check` and `poe build`
run with nothing but Python and `cargo` — measured: the whole software
suite passes in 45 s with `OSS_CAD_SUITE` unset. **This section used to
open "Everything needs OSS CAD Suite", which is false and expensive**:
an agent reading that prefixes the toolchain to every command it runs,
and a session of software work drags the hardware flow behind it for
no reason at all.

What needs it is the hardware, and only the hardware:

| | OSS CAD Suite |
|---|---|
| `poe test` (`sw`), `poe check`, `poe build` | **no** |
| `poe test-rtl`, `poe test-board`, `sim/cosim.py`, `sim/synth.py`, `sim/timing.py`, `tools/mkbit.py` | yes |

Every file importing `sim/toolchain.py` is in the `rtl` group and
nowhere else, which is the rule in one line: **if the question is about
software, the toolchain is not involved.**

When it *is*: [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build)
on `PATH`, or `OSS_CAD_SUITE` pointing at its root.

**On this machine it is installed at `C:\Users\thraa\eda\oss-cad-suite`
and nothing sets the variable at login.** Every shell has to set it
itself. In PowerShell, which is where these commands are known to work:

```powershell
$env:OSS_CAD_SUITE = "C:\Users\thraa\eda\oss-cad-suite"
$env:PATH = "$env:OSS_CAD_SUITE\bin;$env:OSS_CAD_SUITE\lib;$env:PATH"
```

`yosys`, `nextpnr-ice40`, `icepack` and `iverilog` all live in `bin`;
`lib` carries the DLLs they load, so both go on the path.

There is a second, unrelated copy at
`C:\Users\thraa\.icestudio\apio\packages\tools-oss-cad-suite`. It belongs
to Icestudio, it is a different version, and pointing the build at it
means the `SB_` primitive models no longer match the yosys that maps the
design — which is the failure mode `sim/test_boot.py` exists to catch.
Use the `eda\` one.

**Run the suites from PowerShell, not from the Bash tool.** Under Bash,
`yosys.exe` exits 0 having printed nothing and every downstream script
then fails on empty output, which reads like a broken script rather than
a broken shell.

## Commands

`poe test`, `poe build`, `poe check`, `poe list` (or `python -m
poethepoet ...` if Scripts is not on PATH). Every command is named in
`pyproject.toml`: the suites are the job table under `[tool.cool8]`,
fed to **pytest** by the one shim in `sim/runner/` — pytest-xdist fans
them out in parallel and each job gets its own build directory — and
the direct commands are `[tool.poe.tasks]`. There is no Node and no
package.json; `pip install -e ".[dev]"` once is the setup.

**[docs/12-tasks.md](docs/12-tasks.md) is normative for all of it** --
what each job proves, the tests that are deliberately not in the
runner, and how to add one. `sim/cosim.py all` is the gate for any RTL
change: run it, do not reason about whether it would pass.

## "How did BBC BASIC do it" has one source, and it is not a manual

COOL8 BASIC borrows from BBC BASIC deliberately and repeatedly. When you
need to know what it actually did, read the annotated disassembly:

```
https://raw.githubusercontent.com/ivop/bbc-basic/master/basic.s
```

Not the manuals, not BeebWiki, not a search summary. The manuals were
wrong twice here: they implied array subscripts are range-checked at run
time (the disassembly shows the check is only at `DIM`, that the bound
fits fourteen bits), and they gave nothing usable on string storage,
where the disassembly shows a four-byte descriptor — address, current
length, maximum length — and one `STRACC` accumulator that every string
expression builds into.

It is a 16 KB ROM disassembly, so ask it a narrow question; a broad one
gets a summary that misses the answer. If something cannot be reached,
say it was not confirmed rather than filling it in from memory.

## Every investigation goes through the harness. No exceptions.

**`sim/harness.py` and the Machine API are how you look at this
machine — in a test, in a one-off experiment, in a five-minute "let me
just check something".** There is no second way, and reaching for one
is the mistake this project has paid for most often.

```python
import harness as H

code, syms = H.build_bas("basic.bas")     # compile + assemble + symbols
m = vm.Machine()                          # or H-built drivers, see below
H.check(m.shows("42"), "RUN prints its answer")
return H.report()
```

| you want | use | not |
|---|---|---|
| BASIC compiled and assembled | `H.build_bas`, `H.compile_bas` | your own `subprocess` to `cool8asm.py` |
| assembly text built | `H.assemble_text`, `H.assemble` | the same, again |
| assembly that *should* fail | `H.try_assemble` → `(None, why)` | catching a non-zero exit |
| a pass/fail line and an exit code | `H.check`, `H.report` | a fourteenth copy of `check()` |
| paths | `H.ROOT`, `H.BUILD`, `H.SW` | a fresh `HERE`/`ROOT` preamble |
| the iverilog toolchain | `sim/toolchain.py` — `T.tool`, `T.build`, `T.run`, `T.cells`, `T.CORE` | reaching into `cosim`'s privates |

**Why this is a rule and not a preference.** Every one of those had
between six and thirteen copies, and copies drift silently: the
project has already lost rounds to a harness with its own stepping
loop that could not deliver an interrupt, a harness that read the
screen where the editor *wrote* rather than where the display pointed,
and a gate that compared two programs against a third, private model
of the I/O page. A private copy is not a shortcut, it is a second
implementation nobody is checking.

**A throwaway script also throws away the finding.** If a run is worth
tracing twice, it belongs in the suite that already builds and runs
the image — `sim/test_interp.py`, `sim/test_asm.py`, `sim/test_run.py`
— so the next regression is caught rather than re-diagnosed. Adding a
case there is usually three lines, because the harness is already
holding the machine.

**Reach for the tooling at the *first* sign of a fault, not the
tenth.** `m.trace()`/`m.run(until=…)` say what the machine did;
`m.profile_start()`/`m.profile_cycles()` say where the clocks went;
`m.sp_min()` says how deep the stack got; `sim/dbg.py` says whether
every `RET` found its `CALL`. Bisecting by re-running variant programs
and squinting at the screen is the ad-hoc stepping loop wearing a
different hat — it cost a round on the keyboard work before one
`m.trace()` call showed the machine had simply already finished.
[docs/10-debugging.md](docs/10-debugging.md) is the full tour and is
normative for the tooling.

**If the API cannot answer the question, extend it** — `key`,
`scancode`, `settle`, the profiler and the SP watermark all exist
because the question came up and the answer was not there. Extending
`sim/harness.py` or the `+serve` protocol in `rust/src/main.rs` is the
supported move; a local loop is not.

## The machine is the Machine API. Drive it through its API.

**Every software test runs on the Machine API, and nothing reimplements
part of it.** That is not a style preference: for a year each harness
grew its own stepping loop, and each one was a subtly different machine.
One of them could not deliver an interrupt at all and nobody knew until
software wanted one.

**The machine is `rust/` and `tools/cool8rsvm.py` is how Python drives
it** ([RUST_PORT.md](RUST_PORT.md), [D57](docs/01-decisions.md)). The
Python emulator it grew from is gone: it was gated against this one per
retired instruction until the hand-over, and the RTL holds the seat it
used to. **Needs `cargo`** — without it there is no machine, and the
suites say so rather than limping.

Two shapes: `machine()` is the batch machine (CPU and RAM per call,
one shared server), `Machine()`/`boot()` the session machine (a
persistent machine with peripherals, `render=True` for a frame). Reach
them through **`H.machine()`** and **`H.session()`**, which refuse
clearly when `rust/` has not been built rather than falling back to
something — there is nothing to fall back to.

### The VM is the default. The RTL is the exception.

**Any question about software runs on the VM.** It steps at ~66 M
instructions a second; Icarus simulating `rtl/` manages a few
thousand. That is not a choice between two similar things — it is
seconds against a wait nobody sits through, and it is why the software
suite is 45 s.

**Go to the RTL only when the hardware itself is the question**:
`sim/cosim.py` checking the two models agree instruction by
instruction, `sim/test_vm.py` pixel by pixel, a peripheral testbench.
Those are the `rtl` job group and they are the only things that need
the toolchain at all. The two models are gated against each other
*precisely so* a software test can trust the fast one — using the slow
one for a software question throws that away and buys nothing.

**Anything that must watch the machine *while it runs* is a
server-side command, never a Python loop** — `settle`, the cycle
profiler, the SP low-water mark. A round trip per instruction is the
one thing this boundary cannot afford, so a new question of that shape
extends the protocol in `rust/src/main.rs`.

```python
import cool8rsvm as vm
m = vm.Machine()
org = memmap.ORG                 # derived; never write it down
m.bus.mem[org:org + len(code)] = code
m.cpu.pc, m.cpu.sp, m.romen = org, 0x0200, False
```

| want | call |
|---|---|
| one instruction, peripherals in step | `m.tick()` |
| run to a PC, a predicate, a cycle count | `m.run(until=…, cycles=…)` → `"until"`, `"breakpoint"`, `"halt"`, `"cycles"`, `"budget"` |
| stop at an address | `m.breakpoints.add(addr)` |
| type at it | `m.type("10 PRINT 1
RUN
")` |
| what it said on the wire | `m.said()` |
| type at the **keyboard**, not the cable | `m.key("HI")`, `m.key(["K_UP"])` |
| hold a key, or send a malformed code | `m.scancode([0x1C])` — a make with no break |
| the text screen | `m.text()`, `m.row(r)`, `m.shows("42")` |
| what it just executed | `m.trace(n, syms)` then `print(m.trace_report(rows))` — both machines; `into=False` steps over `CALL`s |
| who wrote to an address | `m.watch(lo, hi)` then read `m.hits` — `(pc, addr, value)` |
| where the clocks went | `m.profile(syms, org, end)` then `m.profile_report()` |

**`m.type()` is the serial console; `m.key()` is the keyboard.** They are
different drivers, a different interrupt and, until `sw/kbd.asm` existed,
one of them had no driver in BASIC at all. A test that only ever calls
`type()` proves nothing about the machine a person holds. `m.key()` sends
the make code, the break code and any shift around them, out of the real
`sw/keymap.asm`; `m.scancode()` is the raw form, and the only way to
express a key that is *held* — which is what `KEY()` reads.

**`m.trace()` is for "what did it do", which a breakpoint cannot say.**
A breakpoint tells you where it stopped. The trace decodes forward from
the live PC, one instruction at a time, so boundaries are the ones the
CPU used — never decoded backwards from a symptom, the mistake written
up at the top of `sim/dbg.py`. `into=False` steps over `CALL`s so one
routine's shape is not buried under its callees. A round trip per
instruction, so it takes an `n`; watching a whole run is a server-side
command instead.

`python sim/test_basic.py --trace <label> "<line>" [n] [--over]` is the
way into the *editor*, which had none;
`python sim/test_interp.py --trace "<case>"` is the same for a stored
program. **Both were written after a round was lost to bisecting by
re-running the suite** — the tooling reached for at the tenth sign of
the fault rather than the first, which is what the rule above is
about. `m.trace`/`m.trace_report` were described here and in
[10-debugging.md](docs/10-debugging.md) while existing on neither
machine, so the one suite that called them had a dead `--trace` mode.
A documented tool that is not there is worse than none: it is the one
you reach for.

**Never loop on `cpu.step()`.** Only the machine advances the raster,
the sound and the interrupt flags, so a bare stepping loop runs a
machine where *no time passes* — no vblank, no raster compare, no
interrupt that can ever fire.

**Never compute a screen address.** `m.row()` reads through the
machine's own `VID_BASE`, which is what catches a program that never set
it — the rule [docs/10-debugging.md](docs/10-debugging.md) §3 exists for.
`sim/test_basic.py` once reached into a renderer's private address
helper, and every new harness copied it.

**`sim/dbg.py` still owns the structural checks**, and they are a
different job: exact disassembly decoded forward from a label, a shadow
call stack that pairs every `RET` with its `CALL`, the SP-neutrality
check that names the culprit rather than the victim, and `dbg.diff`,
which aligns two code streams on instruction boundaries so the first
differing *mnemonic* is the answer. Reach for it when the fault is
structural; reach for `Machine` when you want to drive, watch or
measure.

**Profile before optimising, and believe the profile.** A round once
went into the expression evaluator at 16 % of a run while the line
machinery was 48 %. A 256-byte lookup table built on an estimate of 10 %
bought 2 %. `python tools/cool8asm.py <file> --pressure` is the same
question for bytes.

## The verification contract

Both models emit one line of full architectural state per retired
instruction, in an identical format, and `sim/cosim.py` diffs them and
reports the first divergence with disassembly. The whole 64 KB memory
image is compared too, so a store to a wrong address cannot hide.

Easy to get wrong:

- **The trace formats must match exactly.** Icarus `%h` is lowercase;
  the emulator's `%02x` matches it. Change one side, change both.
- **What counts as a retired instruction.** `BRK` and the reserved
  page-2 trap retire — they are instructions. A hardware interrupt entry
  does not, and neither does reset. `o_retire` is the RTL's signal for
  this and the emulator's `instructions` counter is its mirror.
- **Interrupt injection is counted in retired instructions, not
  cycles**, because the two models cannot agree on a cycle. Better
  still, make a test deterministic through the program itself — assert
  the line at reset and let `EI` decide the boundary, or inject during a
  `HALT` where arrival time cannot change the instruction sequence.
- **A bus grant must be architecturally invisible.** The test is that
  the trace is byte-identical to a run without one. Keep it that way.

## Traps already hit here

- **A private copy of a shared thing is a second implementation.**
  `check()` had thirteen identical copies, the compile-assemble-symbols
  pipeline six, the paths preamble twenty-six, and `sim/test_lib.py`
  carried a whole private model of the I/O page so it could fake a
  vblank flag — which meant its gate compared two programs against a
  third machine nobody was checking, and it measured nothing for a
  year. Use `sim/harness.py` and `sim/toolchain.py`; extend them when
  they fall short.

- **Verilog-2001 requires declarations before use.** Icarus rejects a
  testbench referring to a `reg` declared further down. Declare
  everything at the top of the module.
- **Verilog has no adjacent string-literal concatenation.** `$display("a"
  "b", x)` is a syntax error, not C.
- **Do not model a transparent latch as `always @* if (le) q = d;`.**
  ALE and the address change on the same clock edge, so the outcome
  depends on the order the simulator settles them. Capture on the edge
  where LE actually falls — see `sim/tb/cool8_bus_tb.v`.
- **`sim/progen.py` has a fixed memory map**, and the probe array's end
  address is load-bearing: stubs and scratch must stay above it. Changing
  `PROG`, `SLOT` or the probe count without rechecking silently corrupts
  the generated program.
- **Anything instantiating an `SB_` primitive must compile at `-g2012`**,
  because yosys's `cells_sim.v` uses default port values. That drags in
  the SystemVerilog keyword list with it: a testbench array called `ref`
  stops being legal. The RTL itself stays Verilog-2001.
- **`cool8_rom.v` reads its image with `$readmemh` at elaboration**, so
  both `yosys` and `vvp` need `boot.hex` resolvable from their working
  directory. `sim/test_boot.py` builds it into `sim/build` and runs there.
- **A combinational loop is a yosys *warning*, not an error.** `check
  -assert` does not catch one that runs between modules, and `synth_ice40`
  prints "found logic loop" and carries on. Anything that closes a path
  from `mem_rdata` back to `mem_addr` — the core's decoder reads the
  opcode straight off the bus during a fetch — has to be broken by a
  register. `sim/test_soc.py` greps the transcript for it.
- **`cell` is a reserved word** at `-g2012`, along with the rest of the
  SystemVerilog keyword list — the same trap the testbench array called
  `ref` hit. A function-local `reg cell` in a testbench fails to parse
  and the error points at the *next* line.
- **A testbench that models a memory port must grant combinationally**
  if the design does. A grant registered one cycle late stays asserted
  after the request has dropped, which hands a request two answers; in
  `cool8_video_tb` that made every text cell read its own low byte twice
  and looked exactly like an RTL bug.
- **cocotb does not run locally on Windows** with this toolchain — the
  suite's bundled Python has no SSL and `vvp` rejects an external
  interpreter. TinyTapeout's CI runs it on Linux; that is where those
  tests get validated.
- **`expect` is a reserved word** at `-g2012`, the same trap `cell` and
  `ref` hit. A testbench task called `expect` parses as a SystemVerilog
  property statement and the errors point at the *end of the module*,
  tens of lines past the real one.
- **`~` on a reduction is not `!`.** `~(^data)` in an expression whose
  width comes from a 32-bit task port inverts all thirty-two bits and
  compares 1 against `$FFFFFFFF`. Inside a concatenation it is
  self-determined and correct, which is why the same expression is right
  in `cool8_ps2.v` and wrong in its testbench. Use `!` where the width
  is not obviously one.
- **The COOL8 assembler splits operands on commas before it recognises
  character literals**, so `MOV R0,#','` is three operands and no
  encoding matches. Write `#$2C`.
- **The Python machine could not deliver an interrupt to anything.** It
  set `cpu.irq` where the CPU read `irq_line`, so the assignment made a
  new attribute nobody read. Nothing noticed for as long as no software
  wanted an interrupt, and the first thing that did — BASIC's break key
  — simply hung. Python will invent an attribute for you; the machine's
  own name is the one to check against. (Both models are gone; the
  lesson is why the client is a thin, explicit protocol now.)
- **`romen` is machine state, not client belief.** The flash stub drops
  the ROM overlay before jumping to BASIC. A client that pushes its own
  remembered `romen` back before each run re-enables the overlay
  mid-boot, and the failure looks like a bad relocation. It round-trips
  with the registers on every stepping reply.
- **The machine can be typed at and read from directly.**
  `Machine.type()`, `.said()`, `.row()`, `.text()` and `.shows()` are
  on the machine client, so an external test program needs to know
  nothing about where the screen lives. A harness that computes a
  screen address is a harness that cannot catch an unset `VID_BASE`.
- **`con` is a reserved device name on Windows, extension or not.** The
  console module was written as `sw/con.asm` and every tool could read
  it — the assembler, the suites, Python — but `git add` failed with
  `open("sw/con.asm"): No such file or directory` on a file `ls` showed
  at 30 KB. `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9` and `LPT1`–`LPT9`
  are devices, so `con.asm` cannot be committed and cannot even be
  renamed onto. It is `sw/console.asm`; the `con_` symbol prefix is
  fine, because only the *filename* is reserved.
- **A local label belongs to the global label above it, so two entry
  points cannot share one.** Writing `frclose: … BEQ .none` above
  `frshut: … .none: RET` asks for `frclose.none`, which does not exist,
  and the assembler says so at the *branch* rather than at the label.
  Hit twice in one session — `ipoll`/`h_stop` and `frclose`/`frshut`.
  Invert the test and branch to the other **global** label instead;
  falling through into a second entry point is fine, branching into one
  is not.
- **A conditional branch reaches ±127 bytes** and a dispatcher at the
  top of a large file does not. `sw/disasm.asm` defines `jlo`/`jhs`/`jeq`
  macros that invert the test and let a `JMP` carry the distance; the
  assembler's error names the overshoot, so this is caught rather than
  guessed at.

## When timing changes

Cycle counts live in three places that must agree: `rtl/core`,
`tools/opcodes.py:cycles()`, and the emulator's own accounting — with
[02-isa.md §8](docs/02-isa.md) as the human-readable copy. Touch the
control FSM and you must run `python sim/timing.py`, which measures
every encoding from the RTL, then update the other three. The
assembler's listings read `cycles()`, so a stale table is a wrong
listing.

## The TinyTapeout submission

`asic/tt/` holds the metadata; the Verilog is **not** duplicated there.
`python asic/tt/prepare.py <checkout>` copies it out of `rtl/`, and
`--check` reports drift. Never edit the generated repo directly —
changes there are silently overwritten and the submission stops matching
what co-simulation tested.

The shuttle's CI config and cocotb harness are deliberately not
vendored; they change between shuttles and TinyTapeout maintains them.

## Writing style

The documents explain *why*, not just what, and record what was rejected
as well as what was chosen. Match that.

Comments in the RTL follow the same rule. `// one 8-bit adder, shared by
ADD/ADC/SUB/SBC/CMP` earns its place; `// increment the counter` does
not.

## Before proposing anything architectural

Read [docs/01-decisions.md](docs/01-decisions.md) first. Most obvious
improvements have already been considered and rejected there for a
stated reason — the register count, a third pointer, where bus request
belongs, what gets cut if area overruns. Reopening one needs new
evidence of the kind that closed it: real code, measured.
