# COOL8 BASIC — the interpreter

The machine runs the program it holds. There is no compile step, no
second copy of the program in memory, and therefore no overlay: what
`LIST` shows is what executes.

That decision is measured, not assumed. See §5.

---

## 1. Why this and not the compiler

The compiler works ([docs/11-compiler.md](docs/11-compiler.md)) and is
shelved for one reason: 22.5 KB of code plus 4.3 KB of tables in a
39.5 KB user area leaves a program about 12 KB. An interpreter has no
compiled output at all, so the same machine gives a program **~43 KB**.

```
                              program space    speed
compiler in a 24 KB overlay        ~12 KB       1.0x
statement interpreter, 20 KB       ~43 KB       3-5x
```

Three and a half times the room for three to five times the time, and
`ASM` blocks cover the cases where the time matters. That is the bargain
BBC BASIC made and it is a better one here than it was on a 6502,
because this ISA's `CALL`/`RET` is 9 clocks and its table dispatch 38.

---

## 2. Shape

**Statement-level dispatch.** One table jump per statement, not per
operation — 38 clocks paid once for a whole statement. Measured in
`sim/bench_dispatch.py`; the alternatives (direct threading at 19,
subroutine threading at 9) buy less than they cost in program bytes,
because they need a translated copy of the program.

**Resident variables.** Single letters `A`–`Z`, two bytes each, at a
fixed table. `K` is not looked up; it is index 10 of a known address.
This is BBC BASIC's `A%`–`Z%` and it is most of the speed in a loop.
Longer names live on a heap and cost a lookup, so the hot ones are the
short ones — which is exactly the habit the BBC taught.

**Integers first.** 16-bit signed is the working type. Floats are a
library the interpreter calls, never something it pays for by default.

**`ASM` blocks.** The escape hatch, and the reason 3-5x is acceptable.
Assembled at `RUN` into a buffer and called. The encodings are
arithmetic (`docs/11-compiler.md` §3), so the assembler is small.

---

## 3. Memory

```
$0000-$01FF    512 B   zero page: the interpreter's hot state
$0200-$AFFF   43.5 KB  program text, variables, arrays, strings
$B000-$FDFF   20 KB    the system: editor, interpreter, filesystem
$FE00-$FEFF            I/O
$FF00-$FFFF            stack and vectors
```

The screen moves out of `$A000` and into video RAM's text page, freeing
8 KB — text mode reads main RAM today only because the boot ROM set it
that way.

**The stack is 256 bytes and the I/O page is directly below it.** A
stack that grows past ~250 bytes pushes return addresses into hardware
registers, where they are silently lost. The interpreter's expression
evaluator must therefore be iterative, not recursive — which it is
anyway, for speed.

---

## 4. The stored form is the program

Unchanged from the editor: `lineno (2) | len (1) | tokens (len)`,
ascending, keywords one byte. `RUN` walks it. `LIST` prints it. There is
no third representation.

Line numbers are found by walking, and `len` makes that O(1) per line.
`GOTO`/`GOSUB` cache the resolved address on first execution, so a loop
containing one pays the search once.

---

## 5. What is measured

| | |
|---|---|
| `sim/bench_dispatch.py` | token table 49 clocks/op, direct thread 30, subroutine 20, native 11 |
| `sim/bench_interp.py` | `FOR K=1 TO 1000: NEXT` — 1.88x native, 1.48x with a tight `NEXT` |
| `sim/bench_interp2.py` | expression 5.04x, subscript 3.11x, call 4.56x |

The loop figure flatters: one dispatch covers a whole iteration. The
expression figure is the real one, and it is where the work goes.

**The open question.** `bench_interp2`'s expression walker calls a
`term` subroutine per operand. Folding the common cases — a variable, a
small constant — inline should recover much of the 5x, and that is the
first thing to build and measure. If it does not, a hybrid becomes worth
looking at: interpret statements, compile expressions.

---

## 6. Order of work

| | |
|---|---|
| I1 | the core: dispatch, resident variables, an inlined expression walker, `LET`, `FOR`/`NEXT`, `END`. **Gate: the same answers as native, and the expression case measured.** |
| I2 | the rest of the statements: `IF`, `GOTO`, `GOSUB`, `PRINT`, `INPUT`, arrays |
| I3 | `ASM` blocks |
| I4 | strings |
| I5 | wired to `RUN` in the editor, replacing the overlay |

I1 is the one that decides the design, so it carries the measurement.
