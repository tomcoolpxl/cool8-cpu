# Debugging COOL8

Software that runs on the machine is hard to debug from outside it: the
only thing a running machine hands back is a program counter. This is
the tooling that closes that gap, and the rules that came out of using
it.

**Using this tooling is not optional.** An investigation, an
experiment, a quick check — all of it goes through the harness and the
Machine API, never a throwaway script
([AGENTS.md](../AGENTS.md), standing rule 4). The reason is in this
document: every rule below was bought with a lost day.

There are three layers and they do different jobs.

**`sim/harness.py` builds what you are going to look at** — `build_bas`
and `compile_bas` (compile, assemble and hand back the symbols),
`assemble_text` for a driver written in the test, `try_assemble` where
a refusal is the expected answer, and `check`/`report` for the verdict.
It is also where `ROOT`, `BUILD` and `SW` come from. Nothing spawns
`cool8asm.py`: the assembler is a module.

**The machine is `rust/`, and `tools/cool8rsvm.py` is the one API
everything drives it through** — running, typing, reading the screen,
profiling. Nothing reimplements part of it. Observation that needs
every instruction (the idle test, the cycle profile, the stack's
low-water mark) is a command the machine answers, not a Python loop:
see [RUST_PORT.md](../RUST_PORT.md) and
[D57](01-decisions.md).

**`sim/dbg.py` sits on top for the *structural* checks** — exact
disassembly, a shadow call stack, SP neutrality, and a diff of two code
streams. Those need a decoded image and bookkeeping the machine has no
business carrying.

---

## 0. Driving the machine

```python
import cool8rsvm as vm
m = vm.Machine()
m.bus.mem[0xA000:0xA000 + len(code)] = code
m.cpu.pc, m.cpu.sp, m.romen = 0xA000, 0x0200, False
```

| | |
|---|---|
| `m.tick()` | one instruction, with the raster, sound and interrupt flags kept in step |
| `m.run(until=…, cycles=…, budget=…)` | returns `"until"`, `"breakpoint"`, `"halt"`, `"cycles"` or `"budget"`. `until` takes a PC or a set of PCs |
| `m.breakpoints.add(addr)` | stop there, whatever else was asked |
| `m.type("10 PRINT 1
RUN
")` | keystrokes, `
` sent as Return |
| `m.said()` | everything the machine has put on the wire |
| `m.key("HI")`, `m.key(["K_UP"])` | keystrokes at the **PS/2 port**: make, break, and any shift |
| `m.scancode([0x1C])` | raw Set 2 — a make with no break is a key *held* |
| `m.text()`, `m.row(r)`, `m.shows("42")` | the text screen, through the machine's own `VID_BASE` |
| `m.settle(idle, irhead, irtail)` | run until nothing is waiting and the PC is at the idle label |
| `m.profile_start()` → `m.profile_cycles()` | cycles by PC; `dbg.Profile` rolls them up by routine |
| `m.sp_clear()` → `m.sp_min()` | the stack's low-water mark |
| `m.fb()` | the rendered frame, with `Machine(render=True)` |
| `m.palette()`, `m.sprites()`, `m.sound()`, `m.samples()` | the programmed peripheral state |

`type()` and `key()` are not interchangeable. One is the serial console
and one is the keyboard on the desk — different drivers, a different
interrupt, and for a long time only one of them existed in BASIC at all.
The codes `key()` sends come out of `sw/keymap.asm` itself, so the day
the table changes the harness changes with it.

**Three rules, all learned the hard way.**

*Never write your own stepping loop.* Only the machine advances the
raster, the sound and the interrupt flags. A bare loop over single
steps is a machine where no time passes — no vblank, no raster
compare, no interrupt that could ever fire — and anything waiting on
one waits for ever. That went unnoticed for as long as every harness
polled its devices, and the first software that wanted an interrupt
simply hung.

*Never compute a screen address.* `m.row()` reads through the
machine's own `VID_BASE`, which is what catches a program that never
set it (§3). A harness that once reached into a renderer's private
address helper was copied by every harness after it.

*Never ask a question one instruction at a time across the wire.* The
machine runs in its own process, so a Python loop that ticks and looks
pays a round trip per instruction. Every such question is a command
the machine answers itself — `settle`, the profiler, `sp_min` — and a
new one extends the protocol (`rust/src/main.rs`) rather than growing
a loop here.

### Several at once

Typing at the editor, reading the screen back, and measuring where the
time went — one machine, one run:

```python
import test_basic as B
code, syms = B.build()
M = B.Machine(code, syms); M.settle()

M.m.profile_start()                 # where the clocks go

M.cmd("10 PRINT 6 * 7"); M.cmd("20 END"); M.cmd("RUN")
M.settle(120_000_000)

M.screen()[-1]                      # '42'
p = dbg.Profile(syms, 0xA000, 0xFE00)
p.by.update(M.m.profile_cycles())   # cycles by PC, rolled up by label
print(p.report(3))                  # s_serialkey 4,430,535  33.5%
```

The profile says a third of that run was `serialkey` — the editor
waiting for a key, not the interpreter, and exactly the kind of thing
an estimate gets wrong.

### `trace` — what it did, which a breakpoint cannot say

A breakpoint tells you where the machine stopped. `trace` tells you
what it executed, decoded **forward** from the live PC through
`opcodes.disassemble`, so the instruction boundaries are the ones the
CPU used rather than ones guessed backwards from a symptom.

```python
m.breakpoints.add(syms["s_putn"])
m.type("PRINT 0 - 7")
m.run(cycles=40_000_000)
print(m.trace_report(m.trace(16, syms, into=False)))
```

```
  s_putn         $C246  LD R0,[SP+2]
                 $C24A  OR R1,R1
                 $C24B  BPL $C25A
                 $C250  MOV R0,#$2D
                 $C252  CALL $AE24
```

`into=False` steps over a `CALL`, so one routine's shape is not buried
under its callees. Both machines have it: the session machine steps
with `tick`, and the batch machine — which has no peripherals and so no
interrupts — steps by running exactly one instruction's worth of
cycles, `opcodes.cycles()` being normative and gated against the RTL.

**It is a round trip per instruction**, so it takes an `n` and is for
tens or hundreds of instructions. Anything that watches a whole run is
a server-side command instead — that is what `settle`, the profiler and
the SP watermark are.

`python sim/test_basic.py --trace <label> "<line>" [n] [--over]` boots
the editor, breaks at a label and prints this, which is the way in that
the editor did not have. `sim/test_interp.py --trace "<case>"` is the
same idea for a stored program.

> **This existed only in the documentation for a while.** AGENTS.md and
> this file both described `m.trace()`/`m.trace_report()`, one suite's
> `--trace` mode called them, and neither machine had either method —
> so the mode had been dead for as long as nobody ran it. It was found
> by reaching for the documented tool during a real fault and getting
> an `AttributeError`, having already lost a round to bisecting by
> re-running the suite instead. A documented tool that does not exist
> is worse than none: it is the one you reach for.

## 1. What dbg.py adds

### Exact disassembly

Every routine is decoded **forward from its label**, so instruction
boundaries are known rather than guessed.

This matters more than it sounds. Decoding from an arbitrary address
produces plausible-looking nonsense: chasing one bug, a misaligned dump
showed `MOV R0,#$00` six times running while the machine was executing
data, and that reading was believed for an hour.

`img.at(addr)` returns the instruction, or `None` — and `None` is the
answer, because it means the address is not an instruction at all.

### The first fault, not its tenth symptom

`Run.go()` watches four invariants and stops at the first violation:

| | |
|---|---|
| every PC is an instruction boundary | the check that depends on nothing else |
| every `RET` returns where its `CALL` came from | a shadow call stack pairs them |
| every routine leaves SP where it found it | names the *culprit*, not the victim |
| control never leaves the code | |

The order matters. Once execution is misaligned, every opcode read
afterwards is fiction, so the boundary check is the one to trust — the
shadow call stack is only meaningful while the machine is still on the
rails.

### Where the compiler was in the program it was compiling

The stored program is a chain of records, each beginning with its line
number, and the compiler keeps its position in `lxrec`. `Run.source_line()`
reads it, so a fault says **"line 70"** instead of `$5A38`.

### The compiler's own variables, decoded

`Run.state()` prints them by name, with widths read from the `.res`
directives in the generated assembly — the symbol table gives addresses
but not sizes, and guessing them printed convincing nonsense.

```
cerr=0  nsym=3  cp=$A067  ctmax=1  clab=81  inbody=0  equiet=1  line=70
```

### Watchpoints and breakpoints

`Run.watch(lo, hi)` records every write into a range with the
instruction that did it and the source line it was on. `Run.go(stop_at="cbody")`
runs to a routine and returns, so you can look around and step on.

### A structural diff of two code streams

`dbg.diff(got, want, base)` aligns on instruction boundaries and stops
at the first differing **mnemonic**. A byte diff is useless here: once
one stream is a byte longer, every address operand after it differs too,
and the real divergence drowns.

---

## 2. How to use it

```python
import dbg
img = dbg.Image(driver_source, org=0x0200, name="mydrv")
r = dbg.Run(img, src=0x8000, stored=program_bytes)
try:
    r.go()
except dbg.Fault as f:
    print(f)          # symbolised, with the source line and the stack
    print(r.state())
```

To investigate rather than assert, run without the guards by stepping
`r.m.cpu` yourself, or set a watch first and read `r.hits` afterwards.

---

## 3. Two rules that came out of this

**`m.run(until=...)` advances the CPU, not the raster.** A machine run
to a PC that way has had no vblank, no UART drain and no interrupt —
the no-time-passes trap in a second costume. Use `run(cycles=)` or
`tick()` when peripherals must live, and `until` only for "get me to
this address fast".

**An armed `until` or breakpoint at the current PC returns in zero
cycles**, forever, and a loop around it spins without the machine
moving. Step off first — one `tick()` — or discard the breakpoint on
each stop. Both of these were rediscovered the hard way in the same
session; the transcript is in the direct-mode work.

**The stack is 256 bytes, and running out is silent.**

The machine's stack is page 1, `$0100-$01FF`, growing down from
`$0200`. (An early map put it at `$FF00` over the I/O page — that map
is gone; `$FF00` is the interpreter's workspace page now.) A stack
that grows past its page walks into page 0's interpreter state, where
pushes appear to work and the damage surfaces somewhere else entirely.

The self-hosted compiler spends six frames per level of parenthesis in
an expression, so `w - ((b + 1) + 2)` is enough to go over. It runs with
a deep stack in the user area instead; `dbg.Run` defaults `sp` to
`$7FF0` for that reason. Anything else that recurses needs the same
consideration, and this is the first thing to suspect when a return
address comes back as `$0000`.

**A harness that configures what the program should configure is not a
test.** `sim/test_edit.py` set `VID_BASE` itself and so passed a program
that never set it at all. Read the machine's own registers; if the
program forgets, the test must fail.

---

## 4. The rest of the battery

| | |
|---|---|
| `sim/check_names.py` | every top-level name declared once across the compiler's sources — the language is case-insensitive, so `CONST NLAB` and `DIM nlab` are one name and the `DIM` wins, silently |
| `sim/test_lex.py` | the machine's lexer against `cool8bas.py`'s, token for token |
| `sim/test_emit.py` | the machine's emitter against `cool8asm.py`, byte for byte |
| `sim/test_comp.py` | the compiler against the cross-compiler, one program per feature |
| `sim/test_basic.py` | the editor, typed at over the UART |
| `sim/test_fs.py` | `sw/fs.asm` against `tools/cool8disk.py` — the same filesystem written twice |
| `sim/cosim.py` | the RTL against the emulator |
| `sim/test_run.py` | `RUN`, typed at the editor over the UART, read off the screen |

Every one of those drives `vm.Machine` through the API in §0.
`sim/test_corpus.py` is the deliberate exception: it calls compiled
routines on a bare CPU with no peripherals, because that is what it is
testing.

The pattern throughout: **write it twice and make the two agree.** A
single implementation can only ever agree with itself, and every one of
these gates has caught something a self-consistent test would not.
