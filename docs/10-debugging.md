# Debugging COOL8

Software that runs on the machine is hard to debug from outside it: the
only thing the emulator hands back is a program counter. This is the
tooling that closes that gap, and the rules that came out of using it.

`sim/dbg.py` is the module. It wraps `tools/cool8vm.py` rather than
changing it — the emulator is gated byte-identical against the RTL and
must stay a model of the hardware, not a debugger.

---

## 1. What it gives you

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

The pattern throughout: **write it twice and make the two agree.** A
single implementation can only ever agree with itself, and every one of
these gates has caught something a self-consistent test would not.
