# Debugging COOL8

Software that runs on the machine is hard to debug from outside it: the
only thing the emulator hands back is a program counter. This is the
tooling that closes that gap, and the rules that came out of using it.

There are two layers and they do different jobs.

**`tools/cool8vm.py`'s `Machine` is the machine, and everything drives
it through the same API** — running, typing, reading the screen,
watching an address, profiling. Nothing reimplements part of it.

**`sim/dbg.py` sits on top for the *structural* checks** — exact
disassembly, a shadow call stack, SP neutrality, and a diff of two code
streams. Those need a decoded image and bookkeeping the machine has no
business carrying.

---

## 0. Driving the machine

```python
import cool8vm as vm
m = vm.Machine()
m.bus.mem[0xA000:0xA000 + len(code)] = code
m.cpu.pc, m.cpu.sp, m.romen = 0xA000, 0x0200, False
```

| | |
|---|---|
| `m.tick()` | one instruction, with the raster, sound and interrupt flags kept in step |
| `m.run(until=…, cycles=…, budget=…)` | returns `"until"`, `"breakpoint"`, `"halt"`, `"cycles"` or `"budget"`. `until` takes a PC, a set of PCs, or a predicate |
| `m.breakpoints.add(addr)` | stop there, whatever else was asked |
| `m.type("10 PRINT 1
RUN
")` | keystrokes, `
` sent as Return |
| `m.said()` | everything the machine has put on the wire |
| `m.key("HI")`, `m.key(["K_UP"])` | keystrokes at the **PS/2 port**: make, break, and any shift |
| `m.scancode([0x1C])` | raw Set 2 — a make with no break is a key *held* |
| `m.text()`, `m.row(r)`, `m.shows("42")` | the text screen, through the machine's own `VID_BASE` |
| `m.trace(n, syms)` → `m.trace_report(rows)` | the last n instructions, disassembled, with registers |
| `m.watch(lo, hi)` → `m.hits` | every write into the range, as `(pc, addr, value)` |
| `m.profile(syms, org, end)` → `m.profile_report()` | where the clocks went, by routine |

`type()` and `key()` are not interchangeable. One is the serial console
and one is the keyboard on the desk — different drivers, a different
interrupt, and for a long time only one of them existed in BASIC at all.
The codes `key()` sends come out of `sw/keymap.asm` itself, so the day
the table changes the harness changes with it.

`trace()` answers the question a breakpoint cannot. A breakpoint says
where the machine stopped; a trace says what it did on the way, and it
decodes *forward* from the live PC rather than backwards from a symptom
— which is the failure this whole document opens with. Pass
`into=False` to step over `CALL`s when a routine's own shape is what you
are looking at.

**Two rules, and both were learned the hard way.**

*Never loop on `cpu.step()`.* Only the machine advances the raster, the
sound and the interrupt flags. A bare stepping loop is a machine where
no time passes — no vblank, no raster compare, no interrupt that could
ever fire — and anything waiting on one waits for ever. That went
unnoticed for as long as every harness polled its devices, and the first
software that wanted an interrupt simply hung.

*Never compute a screen address.* `m.row()` reads through the machine's
own `VID_BASE`, which is what catches a program that never set it (§3).
`sim/test_basic.py` used to reach into `cool8vid._row_addr_v`, a private
function, and every new harness copied the arithmetic.

### All four at once

Typing at the editor, reading the screen, catching who wrote to a byte,
and measuring where the time went — one machine, one run:

```python
import test_basic as B
code, syms = B.build()
M = B.Machine(code, syms); M.settle()

M.m.profile(syms, 0xA000, 0xFE00)   # where the clocks go
M.m.watch(0x0018)                   # ERR: who stops the program

M.cmd("10 PRINT 6 * 7"); M.cmd("20 END"); M.cmd("RUN")
M.settle(120_000_000)

M.screen()[-1]                      # '42'
M.m.hits[-1]                        # (0xa9d6, 0x18, 255) -- h_end
M.m.profile_report(3)               # [('s_serialkey', 4430535, 33.5), ...]
```

The watch answers "who set `ERR`" with an address, not a guess: `$A9D6`
is `h_end`, and 255 is the clean stop. The profile says a third of that
run was `serialkey` — which is the editor waiting for a key, not the
interpreter, and is exactly the kind of thing an estimate gets wrong.

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

**The stack is 256 bytes, and below it is hardware.**

`OS_PLAN.md` puts the stack at `$FF00-$FFFF` and the I/O page directly
below it at `$FE00-$FEFF`. A stack that grows past about 250 bytes
therefore pushes return addresses **into hardware registers**, where
they are silently lost — the push appears to work, and the matching
`RET` returns to zero.

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
