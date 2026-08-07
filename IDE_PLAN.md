# COOL8 — the screen editor and the system around it

The machine has no IDE. It has a screen, a cursor and a Return key, and
that is the whole design — the Commodore 64 model, which was the best
thing anyone shipped on an 8-bit micro and which fits this machine for
the same reasons it fitted that one.

[`OS_PLAN.md`](OS_PLAN.md) is the system this lives in;
[`docs/09-os-options.md`](docs/09-os-options.md) has the language
decisions behind it. `sw/basic.bas` is the implementation and
`sim/test_basic.py` is the gate.

---

## 1. What this replaces

An earlier draft of this file had a split-pane editor, a command line in
its own window, twelve function keys, mode switching, and the source text
buffered in video RAM. It was a lot of machinery to reproduce what a C64
did with one screen, and it was never built.

The prototype that *was* built, `sw/edit.bas`, is deleted. It proved the
compiler could carry a real program and it did that job. It also carried
a defect worth remembering:

**It wrote its screen at `$8200` but never set `VID_BASE`.** `POKE
VID_MODE, $80` loads the mode-0 preset, which points the display at
`$8000`, so everything it drew landed two rows from where it put the
cursor. That is the "two headers" and the "cursor three lines below the
text" in one bug.

**And the harness hid it**, because `sim/test_edit.py` set
`m.video.base = 0x8200` itself before rendering. Every check passed
against a program that never configured the hardware it was using.

> **A harness that configures what the program is supposed to configure
> is not a test.** `sim/test_basic.py` reads `VID_MODE`, `VID_BASE` and
> `VID_STRIDE` out of the machine and renders from those, whatever they
> are. If the program forgets, the picture is wrong and the test says so.

Fixing the read alone was not enough to catch it: every check scanned for
its text *anywhere* on screen, so a screen drawn two rows off still
passed all of them. What the offset actually breaks is the one thing a
person sees immediately — the cursor stops being on the line they are
typing. So there is now a check that reads `CUR_X`/`CUR_Y` and requires
the character in front of the cursor to be the last one typed.

---

## 2. The editing model

**The screen is the buffer.** There is no separate edit line. Type
anywhere, press Return anywhere on a row, and the machine re-reads that
whole row off the screen and processes it.

- A row that starts with a number is **stored** as a program line.
- A row that does not is **executed** immediately.
- Re-entering a line number that already exists **replaces** it.
- A line number with nothing after it **deletes** that line.

That is the entire interaction. It is why a C64 needed no editor, no
mode switch and no save-before-run: cursor up onto a listed line, type
over it, press Return, and the program has changed.

**Typing over a shorter line leaves its tail behind.** `DELETE 20` typed
onto a row reading `20 PRINT 2` becomes `DELETE 202`. This is not a bug
to fix — it is the direct consequence of the screen being the buffer, it
is exactly what a C64 does, and people learn it in a minute. The test
harness respects it: `Machine.cmd()` walks to the blank bottom row before
typing, which is what a person does too.

### Keys

| | |
|---|---|
| Cursor keys | move, freely, anywhere on screen |
| Home / End | start of row / end of the text on that row |
| Insert / Delete / Backspace | within the row |
| Return | re-enter the row under the cursor |
| Esc | stop a running program |

Decoded from PS/2 scancodes and from ANSI sequences over the serial
port into the same internal key codes, so the emulator and the board
behave identically.

---

## 3. Stored form

```
  lineno (2, LE)   len (1)   tokens (len bytes)
```

Keywords and runtime names become single bytes ≥ `$80`; everything else
stays as text, and `LIST` expands them again. **No indentation is
stored** — it is reconstructed on `LIST`, which measured 23 % smaller
than keeping the text, about 2,020 lines against 1,552 in the same
space.

`len` makes skipping a line O(1), so finding line *n* is a walk rather
than a search. Lines are held in ascending order, so inserting one is a
memmove — which is what the 8-bit machines did, and what makes `RENUMBER`
and `DELETE` fall out cheaply.

Tokenising is **storage compression, not an interpreter**. There is no
interpreter: `RUN` compiles, every time. Turbo Basic XL and FastBasic
both tokenise and compile, for the same reason.

---

## 4. Memory

```
$0000-$01FF    512 B   zero page, runtime hot variables
$0200-$9FFF   39.5 KB  USER: program text, compiled code, variables, strings
$A000-$BFFF    8 KB    text screen, 128x32 at stride 256  (aligned: wrap works)
$C000-$FDFF   15.5 KB  resident: editor, tokeniser, commands, runtime, FS
$FE00-$FEFF            I/O page
$FF00-$FFFF            stack and vectors
```

Program text grows up from `$0200`, the string heap grows down from
`$9FFF`, and they meet at `?OUT OF MEMORY ERROR`.

`sw/basic.bas` currently compiles to **7,162 bytes** — 7.0 KB of the
15.5 KB resident budget, with files, the emitter and `RUN` still to come.

The screen base is `$2000`-aligned because the hardware scroll wraps
within `stride*32` using a power-of-two mask; misalign it and the wrap
lands in the wrong place.

### The compiler is not resident

It lives in video RAM and is copied into the top of the user area for
`RUN` and for immediate lines, emits code into video RAM, and the code is
copied back down when it finishes. 16 KB at ~3 clocks a byte is about
6 ms each way, so a `RUN` costs roughly 12 ms before the program starts.

**That is what buys 39.5 KB for the user**, against 23.5 KB with a
resident compiler and 32 KB in the original goal. In text mode all 64 KB
of video RAM is idle — the text map reads main RAM — so this space is
free.

---

## 5. Commands

Implemented: `LIST` `NEW` `FREE` `RENUMBER [start[,step]]` `DELETE a[-b]`
`CLS`

Planned: `RUN` `SAVE "n"` `LOAD "n"[,line]` `DIR [d:]` `DRIVE d:`
`ERA "n"` `COMPACT` `AUTO [start[,step]]`

`SAVE` appends a new version at the volume tail and marks the old one
deleted — the filesystem is log-structured, so that is the cheap
operation, not the expensive one. `LOAD "n",100` merges from a line
number instead of replacing.

Errors are C64-shaped and short, because string space is scarce:

```
?SYNTAX ERROR      ?OUT OF MEMORY ERROR   ?UNDEF'D LINE ERROR
?DISK FULL ERROR   ?FILE NOT FOUND ERROR  BREAK IN 100    READY.
```

---

## 6. Break and reset

`Esc` stops a running program. It is polled by the vblank interrupt, so
it costs compiled code nothing and can be defeated by a program that
disables interrupts — exactly as on a C64.

`SW[0]` fires the NMI for a warm start, keeping memory. `Ctrl+Alt+Del`
and the board's reset pin clear everything.

---

## 7. No monitor

The C64 shipped without one; the C128, C16 and Plus/4 had one. This
machine follows the C64.

The monitor and disassembler leave silicon entirely and `sw/boot.asm`
shrinks to a bootstrap: reset, clear RAM, load `SYSTEM.ROM` from drive 0
into `$C000` and the compiler image into video RAM, jump — plus a
fallback that receives an image over the serial port when the flash is
blank. About 600 bytes, freeing 7 of 30 block RAMs (28/30 → 21/30).

The real gain is that the OS becomes **one file to reflash** instead of a
bitstream rebuild.

---

## 8. State

| | |
|---|---|
| S0 | harness renders from the machine's own video registers — **done** |
| S1 | screen editor, tokenised storage, `LIST`/`NEW`/`RENUMBER`/`DELETE` — **done** |
| S2 | files: `SAVE` append, `LOAD` merge, `DIR`, `ERA`, `COMPACT` — **done** |
| S3 | the code emitter, byte-identical to `cool8asm.py` — **done** |
| S4 | the compiler: symbols, expressions, control flow, temporaries, `PEEK`/`POKE`, arrays, `SUB`/`CALL` — **done**, byte-identical to the cross-compiler |
| S5 | `ASM` blocks in the on-machine compiler, then shrink it to the overlay |
| S6 | `RUN` |
| S7 | `STRING` |
| S8 | bootstrap and the bitstream. **The board is not touched without asking.** |

## 9. Self-hosting is not a goal

The plan used to end at a fixed point: the compiler compiling its own
source, byte for byte, after which `tools/cool8bas.py` would freeze.
That is dropped, and the measurement that killed it is worth keeping:

```
compiler code + tables                30,020
its own source, comments stripped     36,686
resident system                       12,064
                                      ------
                                      78,770   of 65,536
```

It does not fit in the address space, and the gap is not the sort you
close by tightening a loop. With comments the source alone is 59 KB,
because the stored form keeps them verbatim so `LIST` can give them
back — prose costs the same as code.

**No 8-bit home computer self-hosted.** BBC BASIC was written on Acorn's
development systems; Commodore's on a cross-assembler. The machine's job
is to compile the user's programs, and it does that: seven feature areas,
byte-identical. Building the system stays the cross-compiler's job, and
`tools/cool8bas.py` therefore stays part of the toolchain rather than
being frozen and retired.

What survives from the exercise is the useful half. The on-machine
compiler is real and gated, and the thing that actually needs solving is
smaller and more honest: it is 30 KB against a 16 KB overlay.

## 10. What BBC BASIC did, and what is worth taking

It was the fastest 8-bit BASIC and it was an **interpreter** — 16 KB of
hand-written 6502 assembly. It carried features that should have made it
slower than its rivals (40-bit floats where others had 32, 32-bit
integers where others had 16, arbitrarily long variable names) and was
still fastest, because of how it was built rather than what it was:

- **Resident integer variables.** `A%`–`Z%` at fixed addresses
  `&0400`–`&046B`. No lookup at all; the name *is* an address.
- **Variable lookup by first character** — one linked list per starting
  letter, heads at `&0480`–`&04F5`. Short chains, not a scan.
- **Hot pointers in zero page.**
- **Structured control flow**, so `GOTO`'s line search rarely mattered.
- **An inline 6502 assembler** in `[ ]`: write the program in BASIC and
  the five per cent that needs speed in assembly, from inside BASIC.

Copying the interpreter wholesale is the wrong move here, and the reason
is measured rather than assumed: token dispatch on this ISA costs 31.2
clocks against 2.0 for native code, because there is no `LDW X,[X]` and
so no cheap indirect jump. `sim/bench_lang.py` measured compiled code
beating bytecode by 6.3x. The 6502 had no such penalty; COOL8 does.

**The inline assembler is the part to take.** It is what let a BBC user
put an inner loop in assembly without the interpreter having to be
clever about it, and this machine's compiler should offer the same.
