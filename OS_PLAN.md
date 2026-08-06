# COOL8 OS — the plan

**Nothing here is built yet.** This is the plan of record. The options
that were weighed, the measurements behind them and the rejected
alternatives are in [`docs/09-os-options.md`](docs/09-os-options.md);
this file says what is going to be made.

---

## 1. What it is

A single integrated system that boots from flash into a full-screen IDE:
editor, one-pass native-code compiler for a structured BASIC, a runtime
library, and a filesystem over the 8 MB flash. Roughly Action!'s shape —
edit, press RUN, it compiles in milliseconds and runs at near-assembly
speed — with a language people will recognise and an 80-column screen
none of them had.

**The design centre:** a program compiled by this system should be fast
enough that games and demos are written *in the language* rather than in
assembly. That is what makes the machine best in class rather than
period-plausible, and it is the reason for every choice below.

### Decisions

| | Chosen | Because |
|---|---|---|
| Execution | Native code, one pass, no optimiser | measured 28 clocks/statement, 299,000 statements/sec — 6.3× a bytecode interpreter on this ISA |
| Numbers | Integer by default, floats as a flash-loaded library | implicit floats are the single biggest reason the era's BASICs were slow |
| Syntax | Structured BASIC, QBasic-shaped, no line numbers | where BASIC actually ended up, and block structure is what a full-screen editor wants |
| Locals | Stack frames, recursion kept | `[SP+u8]` is 3 clocks against 4 for `[abs16]` — cheaper than Action!'s fixed addresses, so its reason to drop recursion does not apply here |
| Screen | 8 KB at stride 256 | one add per row address instead of a `MUL` that clobbers `X`, and the hardware scroll works |
| Storage | 16 fake drives of 448 KB, log-structured | flash can only clear bits; append-only needs no read-modify-write and no RAM buffer |
| Source buffer | Automatic: main RAM, VRAM, or spilled on `RUN` | modes 0–4 leave 27 KB of VRAM; mode 6 leaves 4 KB |
| Boot ROM | Rebuild: autoboot + raw flash write | closes a real gap — the hardware can write flash and no software does |

---

## 2. Memory

### 2.1 Main RAM

```
$0000–$00FF    256 B   compiler and runtime hot variables
$0100–$01FF    256 B   OS variables, file control blocks, line buffer
$0200–$81FF     32 KB  ══ USER: compiled code, variables, string heap ══
$8200–$A1FF      8 KB  text screen — 128×32 cells at stride 256
$A200–$FDFF     23 KB  the system: editor, compiler, runtime, FS, drivers
$FE00–$FEFF    256 B   I/O page
$FF00–$FFF7            stack, growing down from $FFF7
$FFF8–$FFFF      8 B   vectors
```

The user area grows **code upward from `$0200`** and the **string heap
downward from `$81FF`**, with variables in a fixed block between them.
Collision is the out-of-memory condition and is checked at compile time
for code and at allocation time for strings.

`ROMEN` goes to 0 once the OS is resident; `$F000–$FDFF` is ordinary RAM
from then on. It goes back to 1 only to enter the debugger (§7).

### 2.2 VRAM

Text mode uses none of it (D28), so in the editor all 64 KB is available.
What each display mode claims, and what is left:

| Mode | Used | Left |
|---|---|---|
| 0/1 text | 0 | 65,536 |
| 2 tiles | 12,288 | 53,248 |
| 3, 4 bitmap | 38,400 | 27,136 |
| 5 bitmap, double-buffered | 49,152 | 16,384 |
| 6 bitmap 8 bpp | 61,440 | 4,096 |

**The source buffer is placed by the OS, per program:**

1. **Main RAM** — default for short programs. All VRAM belongs to the
   program, in every mode.
2. **VRAM above the framebuffer** — when the source exceeds ~8 KB and the
   mode leaves room. Sequential access at ~2–3 clocks a byte, so a 16 KB
   source recompiles in about 30 ms.
3. **Spilled to flash on `RUN`** — when the mode does not leave room.
   16 KB at ~500 KB/s is 32 ms, read back on return to the editor.

The rule is documented in the OS reference, not left as folklore.

---

## 3. The language

### 3.1 Shape

```basic
CONST WIDTH = 40

DIM bars(WIDTH) AS INT

SUB DrawBar (x AS INT, h AS INT)
  FOR y = 0 TO h - 1
    PLOT x, 200 - y
  NEXT y
END SUB

FUNCTION Clamp (v AS INT, lo AS INT, hi AS INT) AS INT
  IF v < lo THEN RETURN lo
  IF v > hi THEN RETURN hi
  RETURN v
END FUNCTION

MODE 4
FOR i = 0 TO WIDTH - 1
  bars(i) = Clamp(RND(255), 8, 180)
  DrawBar i * 8, bars(i)
NEXT i

DO
  IF INKEY = 27 THEN EXIT DO
LOOP
```

- **No line numbers.** `GOTO` exists and takes a label; it is not the
  control structure.
- `SUB`, `FUNCTION`, `DIM`, `CONST`, `IF/ELSEIF/ELSE/END IF`,
  `FOR/NEXT`, `DO/LOOP` with `WHILE`/`UNTIL`/`EXIT DO`,
  `SELECT CASE`, `RETURN`.
- **Recursion works.**
- **Inline assembler**, delimited by `ASM` / `END ASM`. Nearly free:
  [`tools/opcodes.py`](tools/opcodes.py) is already the single encoding
  table shared by the assembler, disassembler and emulator, so the
  compiler links against the same one.

### 3.2 Types

| Type | Size | Notes |
|---|---|---|
| `BYTE` | 1 | unsigned |
| `INT` | 2 | signed, **the default** |
| `CARD` | 2 | unsigned |
| `LONG` | 4 | signed |
| `FIX` | 4 | 16.16 fixed point, in the base system |
| `REAL` | 4 | **only if the program declares one** — pulls `FLOAT.LIB` from flash |
| `STRING` | var | length-prefixed, heap-allocated |

Arrays of any of these, one and two dimensional. Pointers via `@name`
and `PEEK`/`POKE` for the machine-level work an 8-bit machine always
needs.

**Nothing is ever promoted to `REAL` implicitly.** A program that does
not name the type does not pay for it — no RAM, no library load, no
speed. Mixed-type arithmetic promotes only within the integer family.

### 3.3 Calling convention

The convention already exists and was validated at M2:
[`sw/frames.asm`](sw/frames.asm) is the corpus written to test exactly
this, and D21 measured its spill behaviour.

```
arguments pushed right to left by the caller
caller cleans up
return value in R0 (8-bit), R0:R1 (16-bit), or a temp slot (32-bit)
after CALL:  [SP+0..1] = return address, [SP+2] = first argument
locals allocated with ADDW SP,#-n, addressed [SP+u8]
```

---

## 4. The compiler

One pass, source to native code, no intermediate representation and no
optimiser. Speed of compilation is a feature: it is what lets `RUN` feel
like an interpreter.

### 4.1 Code generation model

**Leaf-aware accumulator.** The current value lives in `R0:R1`. When the
right-hand operand of a binary operator is a leaf — a variable, a
constant, a `CONST` — it is loaded into `R2:R3` and the operation is one
or two instructions. Only a nested right-hand side spills, and it spills
to a compile-time-allocated temp slot in the frame rather than to the
hardware stack.

```
A = B + C        LD R0,[B] / LD R1,[B+1] / LD R2,[C] / LD R3,[C+1]
                 ADD R0,R2 / ADC R1,R3 / ST [A],R0 / ST [A+1],R1
```

That is the 28-clock sequence that was measured. Real expressions are
mostly of this shape, which is why the measurement is worth trusting more
than a synthetic one.

**Addresses** go in `X` and `Y`. Array indexing uses `MUL` (11 clocks,
lands in `X` — which is what you want, because you are about to
dereference it) and `LD Rd,[X+Rs]` for the byte fetch.

**Anything large is a `CALL`** into the runtime: multiply and divide
beyond `MUL`'s 8×8, strings, `PRINT` formatting, graphics primitives,
file I/O, floats. A `CALL abs16` is 6 clocks, so the boundary between
inlined and called is drawn at about four instructions.

### 4.2 Symbol table

A Forth-style dictionary — the one thing worth taking from Forth. Chained
entries with an 8-bit hash for the first probe, name, type, storage class
and address. Locals are pushed on entry to a `SUB` and popped at
`END SUB`, so scope is the dictionary's own structure and needs no
separate mechanism.

### 4.3 Errors

Compile stops at the first error, puts the cursor on the offending
token, and prints one line. There is no error recovery and no attempt to
find a second error — a one-pass compiler that fast can simply be run
again.

---

## 5. The IDE

```
┌────────────────────────────────────────────────── 80 × 30 ──┐
│ file        drive 0:      line 142:18      mod     28,914 free │  row 0
├─────────────────────────────────────────────────────────────┤
│ source, syntax-coloured, 80 columns                         │  rows 1–27
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ messages and immediate mode                                 │  rows 28–29
└─────────────────────────────────────────────────────────────┘
```

- **Syntax colouring costs one extra store per character.** Every cell is
  a character byte and an attribute byte with 16 foreground and 16
  background colours; the tokeniser already knows the colour.
- **Scrolling is one register write.** `VID_BASE` moves and the row
  pointer wraps in hardware.
- **Two source panes** on request, as Action! had.
- **Immediate mode** compiles one statement into a scratch buffer and
  calls it — the same code generator, so there is exactly one
  implementation of the language.
- **A sprite is the mouse pointer**, or the marked search hit, or the
  breakpoint arrow. The sprite engine is independent of the background
  mode and positions in raster coordinates, so this costs the editor
  nothing.

---

## 6. The filesystem

### 6.1 Geometry

7 MB usable above the `$100000` hardware floor, divided exactly:

```
volume N  at  $100000 + N × $70000        N = 0..15
16 volumes × 448 KB = $700000 = 7 MB      $100000 + $700000 = 8 MB
```

Each volume: **one 4 KB directory sector, then 111 sectors of data.**
Mounted and named by number — `0:`, `1:` … `15:`.

### 6.2 The directory

256 entries of 16 bytes. Entry 0 is the volume header.

| Bytes | Field |
|---|---|
| 0–10 | name, 8.3, space padded |
| 11 | status — `$FF` never used, `$01–$7F` type, `$00` deleted |
| 12–13 | start, in 256-byte pages from the volume base |
| 14–15 | length in bytes |

**This layout is built around what NOR flash can actually do.** Erased
flash is `$FF`, and programming can only clear bits:

- **Creating a file** writes into an entry that is still `$FF` — no
  erase, no read-modify-write, **no 4 KB RAM buffer anywhere.**
- **Deleting a file** clears the status byte to `$00` — one byte
  programmed, nothing erased.
- **Free space is the tail.** Files are written sequentially into the
  volume's unused end; there is no allocation bitmap.
- **The free pointer is not stored**, because a monotonically increasing
  value cannot be rewritten in place. It is derived at mount by scanning
  the 256 entries for `max(start + length)` — one 4 KB read, about 8 ms.
- **Compaction** (`COMPACT 0:`) rewrites a volume to reclaim deleted
  files. It is the only operation that erases, and it is explicit.

Maximum file size is 64 KB, which is the machine's whole address space —
not a limit anyone will meet.

### 6.3 On the PC

`tools/cool8disk.py`: create, list, add, extract, and dump a volume
image; write it to the board through `icesprog`. Gated against
`cool8vm`'s flash model, including the `$100000` floor and the
can-only-clear-bits behaviour, so the tool and the machine agree by
construction.

---

## 7. Boot, and the monitor

### 7.1 Boot

```
reset → ROM → clear RAM → look for the OS signature at $100000
     ├─ found    → load, ROMEN ← 0, jump to the IDE
     └─ absent   → the monitor prompt, as today
```

### 7.2 The monitor's two jobs

**Bootstrap**, above — and **the debugger**, which is the part worth
designing rather than inheriting. Three hardware traps already vector
through RAM at `$FFF8`:

- `BRK` — a software interrupt with its own vector
- **reserved page-2 encodings trap** — a runaway program counter lands in
  the debugger instead of executing garbage
- the **break button** on `SW[0]` — an NMI with a 2 ms hardware debounce

The OS installs handlers on all three that **set `ROMEN` back to 1 and
enter the monitor**. So the debugger is reachable from anything, at any
time, including from a program that has destroyed itself.

**The division that keeps this honest:**

> The monitor knows about **flash offsets**. The OS knows about **files**.

The monitor does not grow a filesystem. It gains exactly one thing: a
raw flash **write**, so a board with blank flash can be given its first
OS without a PC. Both additions must fit in the ROM's 1,067 free bytes.

**This is a bitstream change.** The machine currently boots correctly on
real silicon and that is a state worth not breaking casually — the ROM
rebuild is gated on the full battery plus a hardware re-verification.

---

## 8. Milestones

Each has a gate, in this project's sense: a thing that either passes or
does not.

### M10 — Benchmark before compiler ✅

**Gate: native ≥3× bytecode on real programs. Worst case 5.26×, PASS.**

[`sim/bench_lang.py`](sim/bench_lang.py) — six benchmarks written once as
an IR, emitted by two back ends, measured on `cool8emu`. Both back ends
produce the same answers, including 1899 primes from the sieve, which is
what says this measures code generation rather than a bug in one of them.

| Benchmark | Native | Bytecode | Ratio |
|---|---|---|---|
| BM1 `FOR K=1 TO 1000` | 47,015 | 360,131 | 7.66× |
| BM2 `K=K+1` ×1000 | 47,015 | 360,131 | 7.66× |
| BM3 `A=K*2+3-K` | 200,015 | 1,051,131 | 5.26× |
| BM6 nested loop + `CALL` | 340,015 | 2,666,131 | 7.84× |
| BM7 `M(L)=A` | 505,055 | 3,176,303 | 6.29× |
| **Byte sieve, 8190** | **3,069,408** | 20,575,348 | 6.70× |
| **Total** | **4,208,523 — 503 ms** | 28,189,175 — 3,366 ms | **6.70×** |

Geometric mean **6.83×**. The single-statement estimate that this plan
was built on said 6.3×; on real programs it is better, not worse.

**Two numbers changed, and both improve the plan:**

**Native code is 17.2 bytes a statement, not 20** — and it is only
**2.30×** the size of bytecode, not the 5× the earlier estimate implied.
Real statements carry array indexing and comparisons whose bytecode
operands are two-byte addresses, so the bytecode's advantage shrinks as
programs get realistic. **32 KB of native code holds about 1,910
statements.**

**The bytecode interpreter is 379 bytes.** So the size argument for
bytecode was never really about the interpreter; it was about the
program, and that gap is half what was assumed.

**Three things learned that the compiler has to handle:**

- **`Bcc` reaches ±127 bytes and the sieve's loops do not fit.** A
  one-pass compiler cannot see forward, so it inverts the test and jumps:
  3 more bytes and 2 more clocks on the taken path. This is in the
  emitter and must be in the compiler.
- **The runtime multiply uses `Y` as scratch**, which is free in native
  code and costs the bytecode model 6 clocks on every call, because `Y`
  is its interpreter pointer. Holding the IP in a register the runtime
  wants is a real, recurring cost.
- **The back end is about 150 lines.** That is the strongest evidence so
  far for the 8–10 KB compiler estimate: code generation is the small
  part, and the tokeniser, dictionary and expression parser are where the
  size will actually go.

**The subroutine-threaded fallback was not measured**, because it is only
reached if native turns out too bulky and it did not. The one-statement
figures stand if it is ever needed: 37 clocks against 28, 3 bytes against
20.

### M11 — Filesystem and the PC tool

Volume format, directory, mount, open, read, write, delete, compact.
`tools/cool8disk.py` alongside it.

**Gate:** the machine creates a file, the PC tool reads it; the PC tool
creates one, the machine reads it. Both against `cool8vm`'s flash model,
with the floor and the bit-clearing behaviour exercised. **Everything
else waits on this** — the float library and autoboot both need named
files.

### M12 — The compiler

Tokeniser, dictionary, expression code generator, control flow,
procedures, arrays. Integer only.

**Gate:** the M10 benchmarks, compiled by the compiler rather than by
hand, within 15% of the hand-compiled clocks. That is what says the code
generator is real.

### M13 — The editor

Full screen, syntax colour, hardware scroll, two panes, immediate mode,
the source-placement rule of §2.2.

**Gate:** a program of over 1,000 lines is written, edited, saved,
reloaded and run entirely on the machine — in the emulator, with no host
tools involved.

### M14 — The runtime library

Graphics (`PLOT`, `LINE`, `RECT`, `MODE`, sprites), sound (the eight
voices, envelopes), strings, `PRINT` formatting, file statements, and
`FLOAT.LIB` as a loadable.

**Gate:** `sw/demo.asm` rewritten in the language, and no slower than the
assembly version by more than 2×.

### M15 — ROM, autoboot, and hardware

Rebuild the boot ROM with autoboot and raw flash write. Bring the whole
thing up on the board.

**Gate:** power on the iCESugar and get the IDE, with no PC attached.
Full battery green, and the hardware re-verified — this is the milestone
that touches the bitstream.

---

## 9. How it is checked

The same way everything else here is: against something that was derived
independently.

- **`sim/test_vm.py` already gates the emulator** against the RTL's own
  output — 1,843,200 pixels and 4,096 samples. The OS is developed on
  that emulator, so the screen it draws is the screen the gates would
  draw.
- **`tools/cool8emu.py` counts clocks**, so every performance claim in
  this document is falsifiable without hardware.
- **The compiler gets a corpus**, as the CPU did at M2 — real programs,
  measured, not a feature checklist.
- **`tools/opcodes.py` stays the only encoding table.** The compiler's
  code generator reads it, exactly as the assembler and emulator do. A
  second table would be the same mistake this project has refused three
  times.

---

## 10. Risks

**The compiler is the biggest single thing ever written for this
machine**, at an estimated 8–10 KB, and the estimate is soft. M10 exists
partly to firm it up: knowing what the generated code looks like tells
you how much generator there has to be.

**The 23 KB system budget has no slack.** Editor, compiler, runtime and
filesystem all live in it. If it overruns, the escape route is that the
runtime library and the filesystem can be paged in from flash the same
way `FLOAT.LIB` is — but that has to be designed in from the start, not
retrofitted.

**The ROM rebuild risks a working machine.** It is deliberately last.

**1,500 lines may not be enough** for the ambitious programs this is
meant to enable. If M10 shows native code is bulkier than 20 bytes a
statement, the subroutine-threaded model is the fallback — it measured
37 clocks against 28, and 3 bytes a statement against 20. That trade is
already understood, which is why it is a fallback and not a crisis.
