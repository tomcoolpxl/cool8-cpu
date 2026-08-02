# 02 — COOL8 instruction set architecture

**Version 0.1 — draft.** No RTL exists yet; this is the specification
the RTL will be written against.

The encoding rules in this document are mirrored in machine-readable
form in [`tools/opcodes.py`](../tools/opcodes.py), which expands them to
a flat table and self-checks that the primary page is exactly covered.
The assembler, disassembler and reference emulator will import that
rather than each carrying their own copy. If the two ever disagree, this
document is normative and the table is the bug.

```
$ python tools/opcodes.py --check
primary page : 256/256 encodings assigned
page 2       : 234/256 assigned, 22 reserved
doc examples : 20/20 match
```

---

## 1. Programmer-visible state

| Register | Width | Description |
|---|---|---|
| `R0` `R1` `R2` `R3` | 8 | General purpose. Fully interchangeable — every ALU operation accepts any of them as source and destination. |
| `X` | 16 | Pointer register. Halves `XL` (low) and `XH` (high) reachable via page 2. |
| `Y` | 16 | Pointer register. Halves `YL`, `YH`. |
| `SP` | 16 | Stack pointer. Full descending. |
| `PC` | 16 | Program counter. |
| `F` | 8 | Flags. |

Total architectural state: 4×8 + 4×16 + 8 = **104 bits**.

X and Y are *not* aliases of R0–R3. See
[D3](01-decisions.md#d3--x-and-y-are-separate-16-bit-registers-not-aliases-of-r0r3).

### 1.1 Flags register

```
 bit    7   6   5   4   3   2   1   0
       ─   ─   ─   I   V   N   Z   C
```

| Flag | Bit | Meaning |
|---|---|---|
| `C` | 0 | Carry out of bit 7 on add; **no borrow** on subtract |
| `Z` | 1 | Result was zero |
| `N` | 2 | Result bit 7 set (negative, two's complement) |
| `V` | 3 | Signed overflow |
| `I` | 4 | Interrupt enable (1 = IRQ enabled) |
| — | 7:5 | Reserved, read as 0, ignored on write |

**Carry convention.** On `SUB`, `SBC` and `CMP`, `C = 1` means no borrow
occurred — the unsigned result did not go negative. `SBC` computes
`Rd - Rs - (1 - C)`. `BCS` therefore means "unsigned greater or equal".
This is the 6502/ARM convention and it is normative; see
[D9](01-decisions.md#d9--carry-means-no-borrow-on-subtract).

### 1.2 Flag effects

Normative. `✓` = set from the result, `–` = unchanged, `0`/`1` = forced.
Where this table and the prose disagree, this table wins.

| Instruction | C | Z | N | V |
|---|---|---|---|---|
| `MOV Rd,Rs`, `MOV Rd,#imm8` | – | – | – | – |
| `ADD`, `ADC` | ✓ carry out of bit 7 | ✓ | ✓ | ✓ signed overflow |
| `SUB`, `SBC`, `CMP` | ✓ **no borrow** | ✓ | ✓ | ✓ |
| `AND`, `OR`, `XOR` | – | ✓ | ✓ | – |
| `NOT`, `SWAP` | – | ✓ | ✓ | – |
| `NEG` (a subtraction from 0) | ✓ | ✓ | ✓ | ✓ |
| `SHR`, `SAR`, `ROR` | ✓ bit shifted out | ✓ | ✓ | – |
| `BTST`, `BSET`, `BCLR` | – | ✓ | ✓ | – |
| `MUL` | 0 | ✓ from the 16-bit product | ✓ from bit 15 | 0 |
| `LD` (any addressing mode) | – | ✓ | ✓ | – |
| `ST` (any addressing mode) | – | – | – | – |
| `PUSH Rd`, `PUSHW`, `POPW` | – | – | – | – |
| `POP Rd` | – | ✓ | ✓ | – |
| `INCW`, `DECW` | – | ✓ from the 16-bit result | – | – |
| `ADDW`, `SUBW`, `LEA`, `MOVW` | – | – | – | – |
| `JMP`, `CALL`, `RET`, `Bcc`, `NOP`, `HALT` | – | – | – | – |
| `CLC`, `SEC` | 0 / 1 | – | – | – |
| `CLV` | – | – | – | 0 |
| `EI`, `DI` | – | – | – | – | (`I` only) |
| `POP F`, `RETI` | all four restored from the popped byte |

Three rules generate most of that, and they are the ones to remember:

1. **`MOV` never touches flags; loads do.** So `MOV Rd,Rd` is a genuine
   one-byte `NOP`, and registers can be shuffled between a `CMP` and its
   branch without destroying the comparison. Loads set `Z`/`N` because
   `LD` then `BEQ` is the single most common two-instruction sequence in
   8-bit code and it should not need a `TST` between them.
2. **Logical operations leave `C` and `V` alone.** A carry survives a
   masking step, which is what multi-precision arithmetic needs.
3. **Pointer arithmetic sets no flags at all.** `INCW`/`DECW` are the
   sole exception, and only for `Z`, because a 16-bit loop counter is
   worth the two gates.

`I` is changed only by `EI`, `DI`, `POP F`, `RETI` and interrupt entry.

### 1.3 Endianness

Little-endian. A 16-bit value at address `n` has its low byte at `n` and
its high byte at `n+1`. This applies to absolute addresses in
instruction streams, pushed return addresses, `LDW`/`STW`, and the
reset/interrupt vectors.

### 1.4 Stack

Full descending. `SP` points at the most recently pushed byte.

```
PUSH:   SP ← SP - 1;  mem[SP] ← data
POP:    data ← mem[SP];  SP ← SP + 1
```

`[SP+d8]` therefore reaches upward into the current frame, and `[SP+0]`
is the top of the stack.

---

## 2. Addressing modes

| Mode | Syntax | Bytes | Effective address |
|---|---|---|---|
| Register | `R1` | — | — |
| Immediate | `#imm8` | +1 | — |
| Pointer indirect | `[X]` `[Y]` | +0 | `X` or `Y` |
| Pointer + displacement | `[X+d8]` `[Y+d8]` | +1 | `X + sext(d8)` |
| Stack relative | `[SP+u8]` | +1 | `SP + zext(u8)` |
| Absolute | `[abs16]` | +2 | `abs16` |
| PC relative | `label` | +1 | `PC_next + sext(rel8)` |
| Pointer + register *(page 2)* | `[X+Rs]` | +0 | `X + zext(Rs)` |

**Note the asymmetry:** `[X+d8]` and `[Y+d8]` take a **signed**
displacement (−128…+127), because a pointer may sit in the middle of a
structure. `[SP+u8]` takes an **unsigned** displacement (0…255), because
nothing meaningful exists below the stack pointer and unsigned doubles
the reach into the frame.

---

## 3. Instruction encoding overview

The primary opcode page occupies all 256 values. Opcode `$2F` escapes
into a second 256-entry page.

| Range | Count | Pattern | Group |
|---|---|---|---|
| `$00–$1F` | 32 | `000 ooo dd` | ALU `Rd, #imm8` |
| `$20–$2F` | 16 | `0010 xxxx` | Control and flow |
| `$30–$37` | 8 | `00110 t dd` | `PUSH` / `POP Rd` |
| `$38–$3F` | 8 | `00111 xxx` | 16-bit pointer quick ops |
| `$40–$4F` | 16 | `0100 t dd b` | `LD`/`ST Rd,[X\|Y]` |
| `$50–$5F` | 16 | `0101 t dd b` | `LD`/`ST Rd,[X\|Y + d8]` |
| `$60–$6F` | 16 | `0110 t dd b` | `LD`/`ST Rd,[SP+u8]` and `[abs16]` |
| `$70–$7F` | 16 | `0111 cccc` | `Bcc rel8` |
| `$80–$FF` | 128 | `1 ooo dd ss` | ALU `Rd, Rs` |

Field meanings:

```
dd, ss   00 = R0   01 = R1   10 = R2   11 = R3
b        0  = X    1  = Y                      (in $40–$5F)
b        0  = SP-relative     1 = absolute     (in $60–$6F)
t        0  = load / push     1 = store / pop
ooo      000 MOV  001 ADD  010 ADC  011 SUB
         100 SBC  101 AND   110 OR   111 CMP
cccc     see section 6
```

The `ooo` field has **identical meaning** in the immediate group and the
register-register group. One eight-entry ALU operation decoder serves
both.

---

## 4. Primary opcode map

### 4.1 `$00–$1F` — ALU `Rd, #imm8` (2 bytes)

`000 ooo dd`, followed by the immediate byte.

| ooo | Mnemonic | Opcodes | Operation |
|---|---|---|---|
| 000 | `MOV Rd,#imm8` | `$00 $01 $02 $03` | `Rd ← imm8` (load immediate) |
| 001 | `ADD Rd,#imm8` | `$04 $05 $06 $07` | `Rd ← Rd + imm8` |
| 010 | `ADC Rd,#imm8` | `$08 $09 $0A $0B` | `Rd ← Rd + imm8 + C` |
| 011 | `SUB Rd,#imm8` | `$0C $0D $0E $0F` | `Rd ← Rd − imm8` |
| 100 | `SBC Rd,#imm8` | `$10 $11 $12 $13` | `Rd ← Rd − imm8 − (1−C)` |
| 101 | `AND Rd,#imm8` | `$14 $15 $16 $17` | `Rd ← Rd & imm8` |
| 110 | `OR  Rd,#imm8` | `$18 $19 $1A $1B` | `Rd ← Rd \| imm8` |
| 111 | `CMP Rd,#imm8` | `$1C $1D $1E $1F` | flags from `Rd − imm8`, no writeback |

Within each row the four opcodes are `R0, R1, R2, R3` in order.

### 4.2 `$20–$2F` — control and flow

| Opcode | Mnemonic | Bytes | Operation |
|---|---|---|---|
| `$20` | `NOP` | 1 | — |
| `$21` | `HALT` | 1 | Stop until reset or interrupt |
| `$22` | `RET` | 1 | `PC ← pop16` |
| `$23` | `RETI` | 1 | `F ← pop8; PC ← pop16` |
| `$24` | `EI` | 1 | `I ← 1` |
| `$25` | `DI` | 1 | `I ← 0` |
| `$26` | `CLC` | 1 | `C ← 0` |
| `$27` | `SEC` | 1 | `C ← 1` |
| `$28` | `JMP abs16` | 3 | `PC ← abs16` |
| `$29` | `CALL abs16` | 3 | `push16 PC_next; PC ← abs16` |
| `$2A` | `JMP [X]` | 1 | `PC ← X` |
| `$2B` | `JMP [Y]` | 1 | `PC ← Y` |
| `$2C` | `CALL [X]` | 1 | `push16 PC_next; PC ← X` |
| `$2D` | `CALL [Y]` | 1 | `push16 PC_next; PC ← Y` |
| `$2E` | `BRK` | 1 | Software interrupt via the `BRK` vector |
| `$2F` | *(escape)* | — | Next byte selects from page 2 |

### 4.3 `$30–$37` — stack, 8-bit (1 byte)

| Opcodes | Mnemonic |
|---|---|
| `$30 $31 $32 $33` | `PUSH R0 … PUSH R3` |
| `$34 $35 $36 $37` | `POP R0 … POP R3` |

### 4.4 `$38–$3F` — 16-bit pointer quick operations (1 byte)

These are one byte precisely because they are the hottest 16-bit
operations in the machine.

| Opcode | Mnemonic | | Opcode | Mnemonic |
|---|---|---|---|---|
| `$38` | `INCW X` | | `$3C` | `PUSHW X` |
| `$39` | `INCW Y` | | `$3D` | `PUSHW Y` |
| `$3A` | `DECW X` | | `$3E` | `POPW X` |
| `$3B` | `DECW Y` | | `$3F` | `POPW Y` |

`INCW`/`DECW` set `Z` from the full 16-bit result and leave `C`, `N`
and `V` unchanged. `PUSHW` pushes the high byte first, so the low byte
ends up at the lower address (little-endian in memory).

### 4.5 `$40–$4F` — pointer indirect (1 byte)

`0100 t dd b`

| | `[X]` | `[Y]` |
|---|---|---|
| `LD R0,` | `$40` | `$41` |
| `LD R1,` | `$42` | `$43` |
| `LD R2,` | `$44` | `$45` |
| `LD R3,` | `$46` | `$47` |
| `ST …,R0` | `$48` | `$49` |
| `ST …,R1` | `$4A` | `$4B` |
| `ST …,R2` | `$4C` | `$4D` |
| `ST …,R3` | `$4E` | `$4F` |

Loads set `Z` and `N` from the loaded byte. Stores affect no flags.

### 4.6 `$50–$5F` — pointer plus signed displacement (2 bytes)

`0101 t dd b`, followed by the signed displacement byte. Same layout as
§4.5: `$50` = `LD R0,[X+d8]`, `$51` = `LD R0,[Y+d8]`, …,
`$5F` = `ST [Y+d8],R3`.

### 4.7 `$60–$6F` — stack relative and absolute

`0110 t dd b`, where `b=0` selects `[SP+u8]` (2 bytes total) and `b=1`
selects `[abs16]` (3 bytes total).

| | `[SP+u8]` | `[abs16]` |
|---|---|---|
| `LD R0,` | `$60` | `$61` |
| `LD R1,` | `$62` | `$63` |
| `LD R2,` | `$64` | `$65` |
| `LD R3,` | `$66` | `$67` |
| `ST …,R0` | `$68` | `$69` |
| `ST …,R1` | `$6A` | `$6B` |
| `ST …,R2` | `$6C` | `$6D` |
| `ST …,R3` | `$6E` | `$6F` |

### 4.8 `$70–$7F` — conditional branch (2 bytes)

`0111 cccc`, followed by a signed 8-bit displacement relative to the
address of the **next** instruction. Range −128…+127.

See section 6 for the condition table.

### 4.9 `$80–$FF` — ALU `Rd, Rs` (1 byte)

`1 ooo dd ss`. Opcode = `$80 + (ooo × 16) + (dd × 4) + ss`.

| ooo | Mnemonic | Range | Operation |
|---|---|---|---|
| 000 | `MOV Rd,Rs` | `$80–$8F` | `Rd ← Rs` |
| 001 | `ADD Rd,Rs` | `$90–$9F` | `Rd ← Rd + Rs` |
| 010 | `ADC Rd,Rs` | `$A0–$AF` | `Rd ← Rd + Rs + C` |
| 011 | `SUB Rd,Rs` | `$B0–$BF` | `Rd ← Rd − Rs` |
| 100 | `SBC Rd,Rs` | `$C0–$CF` | `Rd ← Rd − Rs − (1−C)` |
| 101 | `AND Rd,Rs` | `$D0–$DF` | `Rd ← Rd & Rs` |
| 110 | `OR  Rd,Rs` | `$E0–$EF` | `Rd ← Rd \| Rs` |
| 111 | `CMP Rd,Rs` | `$F0–$FF` | flags from `Rd − Rs`, no writeback |

Within each 16-opcode row: `dd` in the upper two bits of the low nibble,
`ss` in the lower two. So `$90` = `ADD R0,R0`, `$91` = `ADD R0,R1`,
`$94` = `ADD R1,R0`, `$9F` = `ADD R3,R3`.

#### 4.9.1 Free idioms

Because the group is fully orthogonal, `dd == ss` gives useful
operations for nothing:

| Encoding | Assembler alias | Effect |
|---|---|---|
| `ADD Rd,Rd` | `SHL Rd` | Shift left. `C ← old bit 7`. Sets `V`, being an add. |
| `ADC Rd,Rd` | `ROL Rd` | Rotate left through carry. Sets `V`. |
| `SUB Rd,Rd` | `CLR Rd` | `Rd ← 0`, `Z=1`, `C=1`, `N=0`, `V=0`. |
| `SBC Rd,Rd` | `SEXC Rd` | `Rd ← $00` if `C=1`, `$FF` if `C=0`. |
| `OR Rd,Rd` | `TST Rd` | Set `N` and `Z` from `Rd`. `C` and `V` untouched. |
| `AND Rd,Rd` | `TST Rd` | Same. |
| `MOV Rd,Rd` | — | Genuinely nothing, including no flag change. One byte. |
| `CMP Rd,Rd` | — | Always `Z=1`, `C=1`, `N=0`, `V=0`. |

Left shifts and rotates therefore cost one byte and zero opcode space.
Only the right-shifting operations need page 2.

---

## 5. Page 2 — escape opcodes

Every page-2 instruction is prefixed with `$2F`. Byte counts below
**include** the `$2F`.

**Reserved second bytes trap.** The primary page is fully assigned, so
there are no undefined opcodes there — but page 2 has 22 reserved
encodings, and executing one takes the `BRK` vector exactly as a `BRK`
instruction would, with `PC` pointing after the two-byte sequence.

A runaway program counter therefore stops at the first reserved encoding
it hits and lands in the monitor, instead of silently ploughing through
memory executing garbage. On a machine with no memory protection and no
operating system, that is worth the one comparator it costs — and it
costs only one because only page 2 needs checking.

### 5.1 Extra ALU and unary operations

| Second byte | Mnemonic | Bytes | Operation |
|---|---|---|---|
| `$00–$0F` | `XOR Rd,Rs` | 2 | `Rd ← Rd ^ Rs` (`dd ss` layout as §4.9) |
| `$10–$13` | `XOR Rd,#imm8` | 3 | |
| `$14–$17` | `NOT Rd` | 2 | `Rd ← ~Rd` |
| `$18–$1B` | `NEG Rd` | 2 | `Rd ← 0 − Rd` |
| `$1C–$1F` | `SWAP Rd` | 2 | Exchange nibbles |
| `$20–$23` | `SHR Rd` | 2 | Logical right, `0 → b7`, `b0 → C` |
| `$24–$27` | `SAR Rd` | 2 | Arithmetic right, `b7` preserved |
| `$28–$2B` | `ROR Rd` | 2 | Rotate right through carry |
| `$2C–$2F` | *reserved* | | |
| `$30–$33` | `BSET Rd,#mask8` | 3 | `Rd ← Rd \| mask` |
| `$34–$37` | `BCLR Rd,#mask8` | 3 | `Rd ← Rd & ~mask` |
| `$38–$3B` | `BTST Rd,#mask8` | 3 | Flags from `Rd & mask`, no writeback |
| `$3C–$3F` | *reserved* | | |

There is deliberately **no page-2 `ROL` or `SHL`**. Both already exist as
one-byte primary encodings (`ADC Rd,Rd` and `ADD Rd,Rd`, §4.9.1), so a
two-byte duplicate would be strictly worse and the assembler emits the
short form for the `ROL`/`SHL` mnemonics. The consequence is that left
shifts set `V` (they are genuinely adds) while the page-2 right shifts
leave it alone. That asymmetry is real; it is the price of the left
shifts being free.

### 5.2 Pointer half-register access

`pp`: `00` = `XL`, `01` = `XH`, `10` = `YL`, `11` = `YH`.

| Second byte | Mnemonic | Bytes |
|---|---|---|
| `$40–$4F` | `MOV Rd,<pp>` (`0100 dd pp`) | 2 |
| `$50–$5F` | `MOV <pp>,Rs` (`0101 ss pp`) | 2 |

### 5.3 16-bit operations

| Second byte | Mnemonic | Bytes | Operation |
|---|---|---|---|
| `$60` | `LDW X,#imm16` | 4 | |
| `$61` | `LDW Y,#imm16` | 4 | |
| `$62` | `LDW X,[abs16]` | 4 | |
| `$63` | `LDW Y,[abs16]` | 4 | |
| `$64` | `STW [abs16],X` | 4 | |
| `$65` | `STW [abs16],Y` | 4 | |
| `$66` | `MOVW X,Y` | 2 | |
| `$67` | `MOVW Y,X` | 2 | |
| `$68` | `MOVW SP,X` | 2 | |
| `$69` | `MOVW SP,Y` | 2 | |
| `$6A` | `MOVW X,SP` | 2 | |
| `$6B` | `MOVW Y,SP` | 2 | |
| `$6C` | `ADDW SP,#d8` | 3 | Signed. Frame allocate/release. |
| `$6D` | `LEA X,[SP+u8]` | 3 | Frame pointer setup |
| `$6E` | `LEA Y,[SP+u8]` | 3 | |
| `$6F` | *reserved* | | |
| `$70–$73` | `ADDW X,Rd` | 2 | `X ← X + zext(Rd)` |
| `$74–$77` | `ADDW Y,Rd` | 2 | |
| `$78–$7B` | `SUBW X,Rd` | 2 | |
| `$7C–$7F` | `SUBW Y,Rd` | 2 | |

### 5.4 Register-indexed addressing

| Second byte | Mnemonic | Bytes |
|---|---|---|
| `$80–$8F` | `LD Rd,[X+Rs]` (`dd ss`) | 2 |
| `$90–$9F` | `LD Rd,[Y+Rs]` | 2 |
| `$A0–$AF` | `ST [X+Rs],Rd` | 2 |
| `$B0–$BF` | `ST [Y+Rs],Rd` | 2 |

Index is zero-extended, so this reaches 256 bytes above the pointer.
The 6502's `abs,X` analogue.

### 5.5 Auto-increment / auto-decrement

`1100 t dd b` and `1101 t dd b`, same field layout as §4.5.

| Second byte | Mnemonic | Bytes |
|---|---|---|
| `$C0–$CF` | `LD Rd,[X+]` / `ST [Y+],Rd` etc. — post-increment | 2 |
| `$D0–$DF` | `LD Rd,[−X]` / `ST [−Y],Rd` etc. — pre-decrement | 2 |

These exist for assembler convenience; they are **not** faster or
smaller than `LD Rd,[X]` + `INCW X`, which is also two bytes. See
[D14](01-decisions.md#d14--post-increment-addressing-dropped-from-v1).

### 5.6 System

| Second byte | Mnemonic | Bytes |
|---|---|---|
| `$E0` | `PUSH F` | 2 |
| `$E1` | `POP F` | 2 |
| `$E2` | `CLV` | 2 |
| `$E3–$EF` | *reserved* | |

### 5.7 Multiply

| Second byte | Mnemonic | Bytes | Operation |
|---|---|---|---|
| `$F0–$FF` | `MUL Rd,Rs` (`1111 dd ss`) | 2 | `X ← Rd × Rs`, unsigned |

The 16-bit product lands in **X**, not in a register pair — there are no
general-purpose pairs, and multiply is most often used to compute an
address, so landing the result somewhere you can immediately dereference
is what you actually want:

```asm
        ; X = screen_base + row × 40
        MOV  R0,#40
        MUL  R1,R0             ; $2F $F4   X = R1 × 40
        ADDW X,R2              ; $2F $70   (if the base fits in 8 bits)
        LD   R3,[X]
```

`Rd` and `Rs` are unchanged. Flags: `Z` from the full 16-bit product,
`N` from bit 15, `C` and `V` cleared. Unsigned only — for signed
multiply, negate the operands and fix the sign afterwards.

Implemented as a multi-cycle shift-add that reuses the existing 8-bit
ALU, with `X` itself acting as the accumulator and `TMP` as the shifted
multiplier. It therefore adds no architectural state and roughly 150
gates. See
[D18](01-decisions.md#d18--8x8-multiply-landing-in-x).

---

## 6. Condition codes

`Bcc rel8`, opcodes `$70–$7F`.

| cccc | Opcode | Mnemonic | Condition | Meaning |
|---|---|---|---|---|
| 0000 | `$70` | `BRA` | always | Unconditional |
| 0001 | `$71` | — | never | *Reserved* |
| 0010 | `$72` | `BEQ` / `BZ` | `Z=1` | Equal / zero |
| 0011 | `$73` | `BNE` / `BNZ` | `Z=0` | Not equal / non-zero |
| 0100 | `$74` | `BCS` / `BHS` | `C=1` | Unsigned ≥ |
| 0101 | `$75` | `BCC` / `BLO` | `C=0` | Unsigned < |
| 0110 | `$76` | `BMI` | `N=1` | Negative |
| 0111 | `$77` | `BPL` | `N=0` | Positive or zero |
| 1000 | `$78` | `BVS` | `V=1` | Signed overflow |
| 1001 | `$79` | `BVC` | `V=0` | No signed overflow |
| 1010 | `$7A` | `BHI` | `C=1 ∧ Z=0` | Unsigned > |
| 1011 | `$7B` | `BLS` | `C=0 ∨ Z=1` | Unsigned ≤ |
| 1100 | `$7C` | `BGE` | `N=V` | Signed ≥ |
| 1101 | `$7D` | `BLT` | `N≠V` | Signed < |
| 1110 | `$7E` | `BGT` | `Z=0 ∧ N=V` | Signed > |
| 1111 | `$7F` | `BLE` | `Z=1 ∨ N≠V` | Signed ≤ |

---

## 7. Reset and interrupts

### 7.1 Vectors

| Address | Vector |
|---|---|
| `$FFF8` | `RESET` |
| `$FFFA` | `NMI` |
| `$FFFC` | `IRQ` |
| `$FFFE` | `BRK` |

Each is a 16-bit little-endian address.

### 7.2 Reset

```
SP ← $FFF8        (first push writes to $FFF7)
F  ← $00          (I = 0, interrupts disabled)
PC ← mem16[$FFF8]
```

X, Y and R0–R3 are undefined after reset.

`SP` resets to `$FFF8` — immediately below the vector table — so that
the first `PUSH` or `CALL` lands at `$FFF7` and does no harm even if
software never sets `SP`. Resetting it to `$0000` would wrap the first
push onto `$FFFF`, quietly corrupting the high byte of the `BRK` vector.
Software should still set `SP` explicitly; this just makes forgetting
survivable.

### 7.3 Interrupt sequence

`IRQ` is level-sensitive and masked by `I`. `NMI` is edge-sensitive and
cannot be masked. Both are recognised at instruction boundaries only —
there are no restartable long-running instructions in this ISA, which is
the whole reason block operations were left out.

```
push16 PC          ; address of the next instruction
push8  F
I ← 0
PC ← mem16[vector]
```

`RETI` reverses it: `F ← pop8`, `PC ← pop16`. Because `I` is part of
`F`, the interrupt enable state is restored automatically.

`BRK` performs the same sequence through the `BRK` vector, with `PC`
pointing after the `BRK` byte.

`HALT` stops instruction fetch. An enabled `IRQ` or an `NMI` resumes
execution at the handler; `RETI` then returns to the instruction after
the `HALT`.

### 7.4 Bus grant

An external agent can take the memory bus away from the CPU between
instructions. This is not programmer-visible state and there is no
instruction for it — the CPU simply stops for a while and then carries
on, with every register, flag and the program counter exactly as they
were. Nothing is pushed and no vector is taken.

The only way a program can observe it at all is by timing. Code that
must not be interrupted this way does not exist: bus grant is how
software gets loaded and how the debugger works, and it takes priority
over `NMI`.

See [03-microarchitecture.md §2.2](03-microarchitecture.md#22-bus-request-and-grant).

---

## 8. Timing model (provisional)

Cycle counts assume the FPGA configuration: one memory access per clock,
no wait states. **These are targets, not measurements** — they will be
replaced once the RTL exists.

| Class | Cycles |
|---|---|
| `NOP`, `CLC`, `SEC`, `EI`, `DI` | 2 |
| ALU `Rd,Rs` | 2 |
| ALU `Rd,#imm8` | 3 |
| `INCW`/`DECW X\|Y` | 2 |
| `LD`/`ST Rd,[X\|Y]` | 3 |
| `PUSH`/`POP Rd` | 3 |
| `LD`/`ST Rd,[X+d8]` or `[SP+u8]` | 5 |
| `LD`/`ST Rd,[abs16]` | 5 |
| `PUSHW`/`POPW` | 4 |
| `Bcc` not taken | 3 |
| `Bcc` taken | 4 |
| `JMP abs16` | 4 |
| `JMP [X]` | 2 |
| `CALL abs16` | 7 |
| `RET` | 5 |
| `RETI` | 6 |
| Interrupt entry | 7 |
| Any page-2 instruction | primary equivalent + 1 |
| `MUL Rd,Rs` | 12 (8 shift-add steps + setup) |

On the TinyTapeout ASIC every memory access takes three bus cycles
instead of one; see
[03-microarchitecture.md](03-microarchitecture.md).

---

## 9. Worked examples

### 9.1 Byte copy

```asm
        ; X = source, Y = destination, R0 = byte count (1..256, 0 = 256)
copy:   LD   R1,[X]            ; $42        1 byte
        ST   [Y],R1            ; $4B        1
        INCW X                 ; $38        1
        INCW Y                 ; $39        1
        SUB  R0,#1             ; $0C $01    2
        BNE  copy              ; $73 rel    2
                               ;            8 bytes total
```

R2 and R3 are untouched and available.

### 9.2 Structure field access

Given an object pointed to by X with layout
`0:x  1:y  2:width  3:height  4:flags`:

```asm
        LD   R0,[X+0]          ; $50 $00
        ADD  R0,[X+2]          ; -- not available: ALU has no memory operand
```

The ALU is register-to-register only, so:

```asm
        LD   R0,[X+0]          ; $50 $00     x
        LD   R1,[X+2]          ; $52 $02     width
        ADD  R0,R1             ; $91         x += width
        ST   [X+0],R0          ; $58 $00
        LD   R0,[X+4]          ; $50 $04     flags
        BTST R0,#$01           ; $2F $38 $01
        BEQ  not_visible       ; $72 rel
```

This is a deliberate trade: no memory-operand ALU means no read-modify-
write bus cycle, which keeps the microarchitecture and the interrupt
model simple.

### 9.3 A subroutine with a stack frame

```asm
;   int add_bytes(char *p, int n)     X = p, R0 = n
;   two bytes of locals

add_bytes:
        ADDW SP,#-2            ; $2F $6C $FE   allocate frame
        SUB  R1,R1             ; $B5           accumulator = 0
        ST   [SP+0],R0         ; $68 $00       stash the count
.loop:  LD   R2,[X]            ; $44
        ADD  R1,R2             ; $96
        INCW X                 ; $38
        LD   R0,[SP+0]         ; $60 $00
        SUB  R0,#1             ; $0C $01
        ST   [SP+0],R0         ; $68 $00
        BNE  .loop             ; $73
        MOV  R0,R1             ; $81           result in R0
        ADDW SP,#2             ; $2F $6C $02   release frame
        RET                    ; $22
```

(Real code would keep the count in R3 rather than spilling it; the spill
is shown to exercise `[SP+u8]`.)

### 9.4 Multi-byte arithmetic

Adding two 16-bit values, `R1:R0 += R3:R2`:

```asm
        ADD  R0,R2             ; $92
        ADC  R1,R3             ; $A7
```

---

## 10. Assembler syntax conventions

- Hexadecimal `$1234`, binary `%10110001`, decimal bare, character
  `'A'`.
- Immediates take `#`. `MOV R0,#$40` loads the constant; `LD R0,[$40]`
  reads memory.
- Square brackets always mean a memory access.
- Destination first: `op dst, src`.
- Labels beginning with `.` are local to the preceding global label.
- The assembler is expected to accept the §4.9.1 aliases (`SHL`, `ROL`,
  `CLR`, `TST`) and emit the corresponding orthogonal encoding.

---

## 11. Encoding summary card

```
000 ooo dd  imm8              ALU Rd,#imm8
0010 xxxx                     control / flow
00110 t dd                    PUSH/POP Rd
00111 xxx                     INCW/DECW/PUSHW/POPW X|Y
0100 t dd b                   LD/ST Rd,[X|Y]
0101 t dd b  d8               LD/ST Rd,[X|Y + d8]      d8 signed
0110 t dd 0  u8               LD/ST Rd,[SP+u8]         u8 unsigned
0110 t dd 1  lo hi            LD/ST Rd,[abs16]
0111 cccc    rel8             Bcc
1 ooo dd ss                   ALU Rd,Rs
$2F <byte> …                  page 2

ooo   000 MOV  001 ADD  010 ADC  011 SUB
      100 SBC  101 AND  110 OR   111 CMP
dd/ss 00 R0  01 R1  10 R2  11 R3
b     0 X    1 Y      (or 0 SP-rel, 1 absolute)
t     0 load 1 store
```
