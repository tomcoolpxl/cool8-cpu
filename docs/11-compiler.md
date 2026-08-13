# The COOL8 compilers

There are two, and they are not the same program.

**`tools/cool8bas.py`** is the cross-compiler. It runs on a PC, compiles
COOL8 BASIC to COOL8 machine code, and is how everything on this machine
gets built — `sw/basic.bas`, `sw/lib.bas`, the demos, and the compiler
below. **It is not going away.** An earlier plan had it freeze once the
machine could compile its own system; that plan is dropped (§4), so this
stays the toolchain.

**`sw/comp.bas` and friends** are the on-machine compiler: the same
language, compiled to bytes, running on the machine itself. It works and
it is gated. It is **shelved rather than finished**, and this file is
the record of where it got to and why it stopped, so that reviving it is
a decision rather than an excavation.

---

## 1. What the on-machine compiler is

Four sources, all COOL8 BASIC, compiled by the cross-compiler:

| | | |
|---|---|---|
| `sw/chars.bas` | 38 lines | what counts as a letter, a digit, a name |
| `sw/lex.bas` | 204 lines | tokens out of the stored program |
| `sw/emit.bas` | 165 lines | bytes out, and backpatching |
| `sw/comp.bas` | ~1,100 lines | symbols, expressions, statements |

It compiles: `CONST`, `DIM` including arrays and `AT`, assignment,
`IF`/`ELSE`/`ELSEIF` and single-line `IF`, `DO`/`LOOP` with `WHILE` or
`UNTIL` at either end, `EXIT DO`, `FOR`/`NEXT`, `PEEK`/`POKE`,
`SUB`/`FUNCTION` with parameters and locals, `RETURN`, calls in
expressions and as statements, and the temporaries that non-leaf
operands need.

(`FUNCTION` was retired from the language by [D73] and `SUB` grew
parameters and `LOCAL` in the same entry -- so the interpreter now has,
at run time, most of what this list describes the compiler doing ahead
of time. The list is left as it was: it records what the shelved
compiler accepted, not what the language is.)

It does not do `PRINT`, `INLINE`, `ASM` blocks, `EXTERN`, string
literals or `INCLUDE`.

### What it costs

```
code    22,998 bytes  (22.5 KB)
tables   4,386 bytes  (4.3 KB)
```

The code is what an overlay would hold. The tables are working RAM and
belong in the user area either way.

---

## 2. How it is proved

`sim/test_comp.py` compiles seven programs on the machine and with the
cross-compiler and requires **the bytes to be identical** — and the
variables to land at the same addresses, because correct instructions
about the wrong memory is not a working compiler.

```
scalars      173 bytes of code    temporaries  215
branches     173                  loops        217
hardware     140                  arrays       316
subs         438
```

One program per feature, so a failure names the feature. That was not
the first design: a single 126-line program covering everything gave one
bit and took minutes, because the compiler walks the token stream three
times per pass and its symbol lookup is a linear scan, so cost grows
faster than length.

`sim/test_lex.py` and `sim/test_emit.py` gate the front and back ends
separately, against `cool8bas.py`'s lexer and against `cool8asm.py`.

---

## 3. The four things worth keeping

**The encodings are arithmetic, not a table.** Every form the compiler
emits is one add — `ALU Rd,Rs` is `$80 + op*16 + rd*4 + rs`, `Bcc` is
`$70 + cc`, load/store is `$40/$50/$60 + st*8 + rd*2 + which`. There is
no opcode table anywhere in `emit.bas`, and that is most of why it fits.
The inverse of a branch condition is its low bit flipped.

**Forward references cost no memory.** An unplaced label holds the head
of a chain of the sites waiting for it, threaded through those sites'
own operand fields. Absolute and relative sites need separate chains,
because a byte cannot hold an address — a branch site holds the distance
back to the previous branch site, which fits because a `Bcc` only
reaches 127. Array element addresses are the exception: `base + off`
cannot be chained, because the operand field is already holding the
link, so those go in a side table of 128 and are filled in at the end.

**The silent pass.** The frame prologue is `ADDW SP,#-total` and the
cross-compiler deletes the line when the total is zero. A byte emitter
cannot delete what it has written and cannot know the total until the
body has been read — so the body is compiled twice, the first time with
`equiet` set. `cp` advances exactly as it will the second time, because
no instruction's length depends on a label's value.

**Labels on demand.** Two per symbol cost 476 on a large source, most
never used: a constant needs none, a SUB and an array need one, only a
scalar needs a second for its high byte. Permanent labels grow up from
zero and control-flow labels down from the top, so "never freed" and
"freed when the construct ends" do not share a counter.

---

## 4. Why it stopped

Two limits, measured rather than guessed.

**It cannot compile itself.** That was S4's gate and it does not fit:

```
compiler code + tables                30,020
its own source, comments stripped     36,686
resident system                       12,064
                                      ------
                                      78,770   of 65,536
```

With comments the source alone is 59 KB — the stored form keeps them
verbatim so `LIST` can give them back, so prose costs the same as code.
No 8-bit home computer self-hosted; BBC BASIC was written on Acorn's
development systems and Commodore's on a cross-assembler.

**The overlay it needs costs too much program space.** At 22.5 KB of
code plus 4.3 KB of tables in a 39.5 KB user area, a program has about
12 KB left. A statement interpreter has no compiled output at all, so
the same machine gives a program ~43 KB — three and a half times more,
for 3–5x the time. (Measured by `sim/bench_interp.py` and
`sim/bench_interp2.py`, which are deleted now the question is settled —
git history has them, and the numbers here are the record they leave.)

Neither limit is a defect in the compiler. It does what it was built to
do, correctly, and is gated to prove it.

---

## 5. Reviving it

The sources are all still here and every correctness gate still exists;
`comp`, `emit` and `lex` run deliberately rather than in `poe test`,
because they gate code that ships nowhere (see
[12-tasks.md](12-tasks.md)). The dispatch benchmarks that settled the
compile-or-interpret question are deleted — their numbers are recorded
in §4 and the scripts are in git history. What reviving would need:

- **A 24 KB overlay** rather than 16. Video RAM is 64 KB and idle in
  text mode, so the cost is user RAM during a `RUN`, not permanently.
- **`ASM` blocks**, which need an assembler on the machine. The
  encodings being arithmetic makes that smaller than it sounds, but the
  editor tokenises `AND`, `OR`, `XOR` and `CALL` even inside an `ASM`
  block, so the assembler has to accept those keyword tokens as
  mnemonics.
- **`PRINT`, strings, `EXTERN`**, for parity with the cross-compiler.

It is worth reviving for one job in particular: **compiling a program
the user has written, on the machine, when they want the speed** — the
5% case that `ASM` blocks otherwise serve. That is a different and much
smaller requirement than compiling the system.

---

## 5a. What the generated code still leaves on the floor

Found by profiling `sw/demo.bas` against its assembly twin
(`sim/test_lib.py`, and [D58](01-decisions.md)), in the order they
cost:

| | |
|---|---|
| **A mask that cannot do anything** | `x AND 255` where `x` is `BYTE` emits `MOV R2,#255` + `AND R0,R2`. The add already wrapped and the store truncates. A width-aware peephole would delete it; until then, do not write it |
| **A call per iteration** | `CALL Spr16(i, x << 1, y << 1, SPRID)` pushes four 16-bit parameters and builds a frame, eight times a frame, to reach a body that is itself hand-written `ASM` |
| **Every array access recomputes its address** | `sx(i)` is `LDW X,#a_sx` + `ADDW X,R0` + `LD`, about five instructions, with no strength reduction across a loop that walks `i` upward |

None is a defect: this is a one-pass compiler with no register
allocator and no peephole, which is what §3 says it is. They are
listed because the first one is free to avoid by hand, and because
together they are most of the 2.3x that `sim/test_lib.py` gates.

## 6. The bytecode VM

`sim/bench_lang.py` carries a complete stack-machine bytecode emitter
and a 379-byte interpreter, written as the control for the "compile or
interpret" measurement. **It is kept deliberately**, as a host-side
development path: it is the smallest way to get a program running on the
machine when neither native code nor the interpreter is convenient, and
it is the only second implementation of the language's semantics, which
is what makes the native emitter's answers trustworthy.

---

## 7. Everything that gates a compiler here

| | |
|---|---|
| `sim/test_lex.py` | the machine's lexer against `cool8bas.py`'s, token for token — run deliberately |
| `sim/test_emit.py` | the machine's emitter against `cool8asm.py`, byte for byte — run deliberately |
| `sim/test_comp.py` | the machine's compiler against the cross-compiler, one program per feature — run deliberately |
| `sim/test_bas.py` | the cross-compiler's own correctness suite |
| `sim/bench_lang.py` | native against bytecode: 6.7x, and the size it costs. Kept: it carries the language's only second implementation |
| `sim/check_names.py` | every top-level name declared once |

(`bench_dispatch.py`, `bench_interp.py` and `bench_interp2.py` answered
the settled question above and are deleted; git history keeps them.)

The pattern throughout: **write it twice and make the two agree.** See
[docs/10-debugging.md](10-debugging.md) for the tooling that makes a
disagreement findable.
