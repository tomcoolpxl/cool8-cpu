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
compiled output at all, so the same machine gives a program **31.5 KB**.

```
                                 program space    speed
compiler in a 24 KB overlay           ~12 KB       1.0x
statement interpreter, 23.5 KB        31.5 KB      1.9x a loop
                                                   12.6x an expression
```

Two and a half times the room, and `ASM` blocks cover the cases where
the time matters. That is the bargain BBC BASIC made.

**This table used to say 3-5x, and that number was never real.** It came
from `sim/bench_dispatch.py` and `sim/bench_interp.py`, which measure a
*dispatch* — 38 clocks for a table jump — against a native instruction.
A dispatch is not a statement. A real one also skips spaces, scans a
name, decides whether that name is subscripted or a string, walks the
operator precedence and maintains the line machinery, and none of that
was in the prototypes. So every honest measurement since has looked like
a regression against a figure that had never been measured.

**12.6x is where a tokenised BASIC lives.** BBC BASIC is in the same
band for the same work, and it is *behind* on one thing this design got
right: BBC stores a numeric literal as ASCII and re-parses it every time
round a loop, where `$A4` and two binary bytes cost nothing per
iteration. The loop figure, 1.9x, is the one that flatters — a single
dispatch covers a whole iteration.

**The decision does not turn on the speed figure and never did.** It was
made on program space: 31.5 KB against ~12 KB. That is unchanged. What
changed is that the speed column is now measured rather than projected,
and §5 records what each feature cost.

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

**`ASM` blocks.** The escape hatch, and the reason the interpreted ratio
is acceptable at all — BBC BASIC's own answer to the same question.
Assembled at `RUN` into a buffer and called. The encodings are
arithmetic (`docs/11-compiler.md` §3), so the assembler is small.

---

## 3. Memory

```
$0000-$00FF    256 B   the interpreter's hot state
$0200-$7FFF   31.5 KB  program text, variables, arrays, strings
$8000-$9FFF    8 KB    the screen: 128x32 cells at stride 256
$A000-$FDFF   23.5 KB  the system: editor, interpreter, filesystem
$FE00-$FEFF            I/O
$FF00-$FFFF            vectors
```

**An earlier version of this file said the screen could move into video
RAM's text page, "because text mode reads main RAM today only because
the boot ROM set it that way". That was wrong.** Which memory the text
fetch reads is fixed by the engine decode in `rtl/soc/cool8_fetch.v` —
`want_ram` is asserted by the text states and `want_vr` by the tile and
bitmap states, and nothing else chooses. [D28](docs/01-decisions.md)
refused to add a `VID_ADDRSPACE` bit on purpose, so *"the failure mode
does not exist to be documented"*. No sequence of `VID_BASE`,
`VID_CTRL` or `VID_MODE` writes can move the text map, and doing it in
RTL is D28's rejected runner-up: first light would go behind an indirect
port and `tools/cool8screen.py` would lose the screen entirely.

What actually happened is cheaper. The map has to be 8 KB aligned,
because the row wrap is a mask rather than a compare, so it sits at
`$8000` or `$A000` and nowhere between. Mode 0's preset, the boot ROM's
banner and the monitor all use `$8000`; the editor was overriding the
preset to `$A000`, and that override was the only thing forcing the
system up to `$C000`. Moving it back buys **8 KB of system space for
8 KB of program space** and leaves one screen base where there were
three.

So the program area is 31.5 KB, not 43.5 KB. Against the compiler's
~12 KB that is still the argument this design was chosen on. The
43.5 KB number needs the RTL move, and the RTL move needs D28 reopened
with evidence.

**The stack is 256 bytes, and what is below it is not the I/O page.**
An earlier version of this file said the stack lives at `$FF00-$FFFF`
with `$FE00-$FEFF` directly beneath, so an overrun would push return
addresses into hardware registers. That is the ISA's reset value
(`SP <- $FFF8`) and it is not what runs: `sw/boot.asm:339` sets
`stack = $0200` and `reset` loads it, and `sw/basic.bas` never touches
`SP`. So the stack grows down through `$01FF`, and at depth ~210 it
reaches `FSVARS` at `$0100` — the filesystem's own state
(`sw/fs.asm:52-64`). The failure is quieter than the documented one: not
a lost return address, but a corrupted mount.

**The harnesses do not reproduce this.** `sim/test_basic.py:93` and
`sim/test_fs.py:80` set `SP = $FFF7`; `sim/test_interp.py:240` sets
`$7FF0`. None of them runs at `$0200`, so none of them can catch a depth
problem the real machine would hit. That matters at I5, where `RUN`
enters the interpreter several frames deep inside `docommand` rather
than at the top of an empty stack.

The expression evaluator is recursive descent, and that is cheap here
because a level costs one return address rather than a frame — the
compiler blew its stack because its frames were large, not because it
recursed. **Measured: a parenthesis costs 4.0 bytes.** A stored line
holds 127 token bytes, so the deepest expression that could be typed was
about 60 parentheses — 246 of the 256, ten bytes of margin, and that
from an *empty* stack when the editor is already 78 bytes down at `RUN`.

So the evaluator counts its own nesting and refuses past 24 levels with
`?FORMULA TOO COMPLEX`, the error C64 BASIC has for exactly this. 24 is
about 102 bytes, which leaves the editor its 78 and 76 spare. It is a
stack budget rather than a limit on what anyone would write — ten nested
parentheses is already past what BBC or C64 BASIC will take. The counter
is touched only where the evaluator actually recurses, so an expression
without a parenthesis pays nothing and the benchmark did not move.

**The language's own stacks do not go on the CPU stack.** `FOR` keeps
its innermost loop in four fixed locations and pushes only the enclosing
ones, onto a bounded stack of its own in page 0, with `?TOO MANY FORS`
when it fills. That is the BBC Micro's shape — it gave `FOR`, `REPEAT`
and `GOSUB` a stack each — rather than BBC BASIC (86)'s, which merged
them onto the processor stack. `DO`/`LOOP` and `CALL` join it at I4.
Caching the innermost rather than the top of the stack is what makes
nesting free: `h_for` is 0.0% of the expression benchmark.

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
| `sim/test_interp.py` | **the real interpreter, not a prototype: 12.80x on the expression case**, 4,264 bytes, and a parenthesis costs 4.0 bytes of stack |
| `sim/test_run.py` | **the whole thing, typed at over the UART**: boot, enter a program a character at a time, `RUN`, and read the answer off the screen. Ten programs, three faults that must name their line, and Ctrl-C stopping a loop that never ends. `basic.bin` is 21,003 bytes |
| `sim/test_asm.py` | `sw/asm.asm` against `tools/cool8asm.py`, byte for byte: 96 single instructions, 16 multi-line cases, 7 refusals, and **every one of the 488 reachable encodings**. 2,521 bytes of code and 313 of table |

The first three rows measure prototypes. The last measures
`sw/interp.asm` itself and is the one to believe.

The loop figure flatters: one dispatch covers a whole iteration. The
expression figure is the real one, and it is where the work goes.

**7.63x became 8.73x when the interpreter learned about spaces, and that
is not a regression to recover.** The stored form keeps the line as it
was typed — `sw/basic.bas:1536-1541` drops one space after the line
number and `tokenise` copies every interior space verbatim, which is
what makes `LIST` give back the indentation. Nothing in the interpreter
skipped them, and no gate could see it, because every case in
`sim/test_interp.py` built its token stream by hand with no separators.
A space reaching `varidx` became variable `($20-'A')*2 = 190`, so a
typed `A = 7` assigned `VARS+190 = $00FE`, which at the time was the
assembler's symbol-table pointer, and left `ERR` at zero. Silently wrong, on the
first line anyone would type.

Keeping the spaces and skipping them at read time is BBC BASIC's
arrangement and 6502 Microsoft BASIC's alike; the latter's `CHRGET`
lives in page zero for exactly this reason. The cost was measured, not
assumed: as a subroutine the skip was **17.2%** of the benchmark — 6
clocks of `CALL` and 3 of `RET` to discover there was nothing to do — so
it is inlined, and `eval` was restructured to peek once for `*`, `+ -`
and the relationals together rather than three times. What is left is
+14.4%: about 14,000 token reads paying 6 clocks each to ask.

**Long names cost another 16%, and it is the same shape of cost.** A
name now has to be *scanned*, which means one lookahead: the byte after
`K` has to be classified before `K` can be told from `KOUNT`. Written
the obvious way — scan into a buffer, then notice it was one character
— the benchmark went to 17.4x, because A-Z are the hot path and a loop
counter had become a subroutine. The resident case is straight-line and
calls nothing, `varidx` hands back the address it already computed
rather than making `prim` ask `varaddr` for it again, and the lookahead
tests are ordered so that a space and every operator are caught by the
first compare. That is 10.16x, and the residue is what knowing where a
name ends costs.

Both of these are corrections, not regressions. So is a third, found
while measuring them: **a literal is three bytes and every walk to end
of line was treating it as one.** `$A4` carries two binary bytes and the
high byte of any value below 256 is zero, so `h_if`'s false-arm scan
stopped inside the number and resumed three bytes into the middle of its
own record — executing a length byte as a token and assigning whatever
followed. `skiptok` is now the one way to step a token, and
`sim/test_interp.py` gates the ELSE arm being reached at all.

**The open question is closed, and the answer is to accept it.** It was
framed as a choice between a hybrid — interpret statements, compile
expressions — and leaning on `ASM` blocks. Reading what BBC BASIC
actually does settles it: **BBC compiles nothing.** `AEEXPR` walks the
token stream every time, into `IACC`, and the inline assembler exists
precisely so the 5% that matters can leave the interpreter altogether.
The hybrid is a departure from that design, not a return to it, and this
machine now has the assembler ([D45](docs/01-decisions.md)).

**What the cost is made of**, measured feature by feature rather than
guessed at:

| | ratio | what it bought |
|---|---|---|
| I2 | 7.63x | |
| + spaces | 8.73x | typed lines stop being silently wrong |
| + long names | 10.16x | one lookahead per name; a stray byte stops being a variable |
| + arrays | 10.61x | a subscript test on every variable read |
| + `AND`/`OR`/`XOR` | 10.98x | one operator serving logic and bits |
| + strings | 11.99x | a type test per read, and a reset per statement |
| + `/` and `MOD` | 12.86x | two more tests in the operator peek |
| class table | 12.61x | one indexed load for the name lookahead |
| + Ctrl-C | 12.80x | one flag read at each loop back-edge |

Every step but the last adds a test to the same inner loop, which is why
the total compounds. `sim/prof_interp.py` says where it lands: `stmt`
22.8%, `erel` 19.2%, `prim` 14.5%, `varidx` 12.2%. It is **distributed**,
so there is no single hot spot left to attack — the class table, the
biggest structural change available, bought 2%.

`prim`'s five-way chain was measured and deliberately left alone: moving
it onto the table saves 4 clocks on a name and costs 15 on a
parenthesis, a `PEEK` or a literal.

**Space skipping is ~10% and it stays.** Removing the test means
crunching the stored form, and a space inside an `ASM` block is a
separator — `MOV  R0,#5` crunched is one identifier where there were
two. [D45](docs/01-decisions.md) records why BBC declined the same fix.

---

## 6. Order of work

| | |
|---|---|
| I1 | the core: dispatch, resident variables, an inlined expression walker, `LET`, `FOR`/`NEXT`, `END`. **Gate: the same answers as native, and the expression case measured.** — done |
| I2 | the editor's own tokens, executed: assignment, precedence, parens, unary minus, `IF`/`THEN`/`ELSE`, the six relationals, `FOR`/`NEXT`, `GOTO`, `POKE`/`PEEK`, `END`. 8.73x on the expression benchmark — done |
| I2b | the screen to `$8000`, so the system has room for the rest; the filesystem's workspace out of the stack's page; `FOR` given a bounded stack so it nests — done |
| I3a | long names: the name table, and `varidx` scanning an identifier. Pulled in front of the assembler by [D45](docs/01-decisions.md). The heap, `DIM` and arrays are still to come — the assembler did not need them — done |
| I3b | `ASM` blocks. Byte-identical to `tools/cool8asm.py` across all 488 reachable encodings — done |
| I4a | `AND`/`OR`/`XOR`, and `TRUE` becomes -1 so one implementation serves logic and bits both. The `<=` and `>` arms of the evaluator fixed � they popped the caller's return address � done |
| I4b | strings: the `$` suffix, the accumulator, the four-byte descriptor, literals, assignment, concatenation, `LEN`, equality and `PRINT` � done |
| I4c | `DO`/`LOOP` with `WHILE`/`UNTIL` at either end, `EXIT`, `ELSEIF`, `CALL`/`RETURN`, `/` and `MOD`, and the string functions: `LEN`, `LEFT$`, `RIGHT$`, `MID$`, `CHR$`, `ASC`, `STR$`, `VAL`, `INSTR` — done |
| I5 | wired to `RUN` in the editor, replacing the overlay, with Ctrl-C stopping a running program through a vblank interrupt ([D49](docs/01-decisions.md)) — done |

I4 is complete, and nothing I2 deferred is still deferred. Nineteen
`sttab` slots point at `bad`, and fourteen of them should: `TO`,
`WHILE`, `UNTIL`, `THEN`, `AS`, `INT`, `BYTE`, `CARD`, `AT`, `PEEK`,
`AND`, `OR`, `XOR` and `$A4` are tokens that only ever appear *inside* a
statement, so meeting one where a statement should start is a syntax
error and `bad` is the right answer.

The five that are genuinely unimplemented are `CONST`, `EXTERN`,
`INCLUDE`, `INLINE` and `WEND`. The middle three are compiler-era
keywords with no meaning to an interpreter that has no separate
compilation step, and `WEND` is the `WHILE`/`WEND` loop that
`DO`/`LOOP` replaced. Only `CONST` is a real gap.

**I3 and I4 were reordered, and the seam was already there.** The
assembler was to carry its own symbol table, its own cut-down value
parser and its own pass driver — about 300 bytes of code and 448 of RAM
reimplementing, worse, machinery the interpreter has. BBC BASIC's
assembler has none of the three: a label is an assignment to a BASIC
variable, an operand is a BASIC expression, and the two passes are a
`FOR` loop the user writes. Taking that needs a variable namespace with
long names, which is the first half of what I4 was going to be, and I4's
own risk note had already named that as where it would split. So it
splits there. [D45](docs/01-decisions.md) carries the argument and what
it cost.

I1 is the one that decides the design, so it carries the measurement.

I2 shipped a subset: `DIM`, `DO`/`LOOP`, `EXIT`, `ELSEIF`, `RETURN`,
`CALL` and the bitwise operators are still `bad` in `sttab`. They moved
out of a milestone of their own because strings need a name table and a
heap and so do arrays, and building that machinery twice would be the
waste. The assembler turned out to need it too, which is why the name
table is now I3a and comes first.
