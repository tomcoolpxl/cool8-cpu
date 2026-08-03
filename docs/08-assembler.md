# 08 — Assembler

[`tools/cool8asm.py`](../tools/cool8asm.py). Two-pass, purpose-built.

```bash
python tools/cool8asm.py sw/lib.asm -o lib.bin
python tools/cool8asm.py sw/lib.asm --listing lib.lst --symbols lib.sym
python tools/cool8asm.py sw/gfx.asm --pressure
```

---

## 1. Where the mnemonic table comes from

It does not have one. The assembler builds its table at import time by
**disassembling every encoding in `tools/opcodes.py` and normalising the
result**, then normalising each source line through the identical
function.

That gives a property worth stating plainly: **any text the disassembler
can emit is text the assembler accepts.** The two cannot drift, because
there is only one table and only one notion of what an addressing mode
looks like. Adding an instruction to `opcodes.py` makes it assemblable
with no change here at all — `ADDW X,#imm16` ([D20](01-decisions.md#d20--addw-xyimm16-added-after-the-m2-gate))
was added to the table and the assembler picked it up for free.

Instruction lengths are fixed per mnemonic and addressing mode — there
is no branch relaxation, no zero-page shortening, nothing whose size
depends on an operand's value. Two-pass assembly is therefore trivially
convergent; pass 1 can compute every address without resolving a single
expression.

---

## 2. Syntax

### 2.1 Lines

```asm
label:  MNEMONIC operands        ; comment
```

Labels **require a colon**. That is what keeps `.loop:` (a local label)
unambiguous from `.byte` (a directive), since both start with a dot.

Mnemonics, register names and directives are case-insensitive. **Labels
are case-sensitive.**

### 2.2 Labels

| Form | Meaning |
|---|---|
| `name:` | Global. Also starts a new routine for the listing and pressure report. |
| `.name:` | Local to the enclosing global label. Stored internally as `global.name`. |
| `@name` | Macro-local. Expands to a local label unique to the invocation. |

### 2.3 Numbers and expressions

| Form | Example |
|---|---|
| Hexadecimal | `$FE71` |
| Binary | `%10110001` |
| Decimal | `200` |
| Character | `'A'`, `'\n'`, `'\0'` |
| Current address | `*` |

Operators, loosest binding first:

```
|    ^    &    << >>    + -    * / %
```

Unary: `-` negate, `~` complement, `<` low byte, `>` high byte.
Parentheses group.

```asm
        MOV  R0,#<SCREEN        ; low byte of a 16-bit constant
        MOV  R1,#>SCREEN        ; high byte
        MOV  R2,#'A'-10
        LDW  X,#SCREEN+STRIDE*8
```

Note that `<` and `>` are unary prefixes in a value position and shift
operators in an operator position; the parser tracks which it is
expecting, so both work without ambiguity.

### 2.4 Directives

| Directive | Effect |
|---|---|
| `.org expr` | Set the assembly address |
| `.equ NAME, expr` / `NAME = expr` | Define a constant |
| `.byte` / `.db` | Emit bytes; string literals allowed |
| `.word` / `.dw` | Emit little-endian 16-bit words |
| `.ascii "..."` | Emit a string |
| `.asciz "..."` | Emit a string with a terminating NUL |
| `.space n [, fill]` | Reserve `n` bytes |
| `.align n` | Pad to a multiple of `n` |
| `.include "file"` | Textual include; circular includes are an error |
| `.macro name a, b` … `.endm` | Define a macro |

### 2.5 Macros

Parameters are substituted as `\name`. Labels written `@name` become
local to the invocation, so a macro used twice inside one routine does
not collide with itself — and, because they expand to *local* labels,
a macro used inside a routine cannot accidentally end that routine's
label scope.

```asm
.macro  memclr ptr, count
        LDW  Y,#\ptr
        MOV  R0,#\count
        CLR  R1
@loop:  ST   [Y],R1
        INCW Y
        SUB  R0,#1
        BNE  @loop
.endm

clear_buf:
        memclr scratch, 32
        RET
```

### 2.6 Aliases

These assemble to existing orthogonal encodings rather than to
instructions of their own — see
[02-isa.md §4.9.1](02-isa.md#491-free-idioms).

| Written | Emitted | Bytes |
|---|---|---|
| `SHL Rd` | `ADD Rd,Rd` | 1 |
| `ROL Rd` | `ADC Rd,Rd` | 1 |
| `CLR Rd` | `SUB Rd,Rd` | 1 |
| `TST Rd` | `OR Rd,Rd` | 1 |
| `SEXC Rd` | `SBC Rd,Rd` | 1 |
| `INC Rd` | `ADD Rd,#1` | 2 |
| `DEC Rd` | `SUB Rd,#1` | 2 |
| `BHS` `BLO` `BZ` `BNZ` `BN` `BP` | `BCS` `BCC` `BEQ` `BNE` `BMI` `BPL` | 2 |

---

## 3. Outputs

### 3.1 Listing (`--listing`)

Address, bytes, **cycle cost**, source. Conditional branches show
`not-taken/taken`. Per-routine totals follow the body.

```
0400  2F 2C E8 03     6  ptr_bump:
0404  22              5          RET
0405  42              3  memcpy: LD   R1,[X]
0406  4B              3          ST   [Y],R1
0407  38              2          INCW X
0408  39              2          INCW Y
0409  0C 01           3          SUB  R0,#1
040B  73 F8         3/4          BNE  memcpy
```

Cycle counts come from `opcodes.cycles()`, the same table the emulator's
own accounting is cross-checked against, so a listing and a trace cannot
disagree about timing. That makes "is this loop fast enough to fit in a
raster line" answerable by reading the listing.

### 3.2 Symbols (`--symbols`)

`address  name`, sorted by address. For the loader, the debugger and the
disassembler.

### 3.3 Register-pressure report (`--pressure`)

Per routine: instruction count, bytes, cycles, how many distinct general
registers and pointers it touches, and its **spill traffic** — pushes
and pops of a general register, `PUSHW`/`POPW` of a pointer, and stack
slot loads and stores. Those are work the machine does only because it
ran out of registers.

This is the evidence that closed the four-register question at the M2
gate ([D21](01-decisions.md#d21--four-general-registers-is-enough-confirmed-question-closed)),
and it is a mechanically-derived number rather than an impression.

```
routine               insn  byte    cyc  GPRs  ptr  spill  spill%
blit8_or                11    16     34     4    2      0    0.0%
blit8_mask              19    30     67     4    2      2   10.5%
```

**Caveat worth knowing:** `PUSHW`/`POPW` is counted as spill traffic,
but it is also the legitimate way to save a pointer around a call. The
number is a signal, not a verdict — read the routine before drawing a
conclusion from it.

---

## 4. Errors

Reported as `file:line: message`, with all errors from a pass shown
rather than stopping at the first. Range violations name the fix:

```
lib.asm:212: branch out of range: +153 bytes (target $04C8 from
             $0428); use JMP or move the target closer
```

---

## 5. Testing

The assembler is exercised by [`sim/test_corpus.py`](../sim/test_corpus.py),
which assembles all three corpus files and runs every routine in the
reference emulator against results computed in Python — random operand
pairs for `mul16` and `div8`, six array sizes for `sort8`, real geometry
for the graphics routines.

That suite is mutation-tested: deliberate bugs are injected into the
corpus assembly and the suite must fail on each. It initially caught 9
of 10, and the escape was a real gap — nothing verified that `mul16`
restored the caller's `X`, which is the entire reason that routine
spills. Deleting the spill passed every other test. The check was added.
