# 09 — The operating system: options, and what was chosen

**Status: decided, not built.** Every number marked *measured* came out
of `tools/cool8emu.py` counting clocks on the real instruction set;
everything else is marked as an estimate.

## The decisions

| | Chosen | Section |
|---|---|---|
| Execution | **Native code**, one pass, Action!'s model | §3 |
| Numbers | Integer by default; **floats as a library loaded from flash** | §3.3 |
| Syntax | **Structured BASIC, QBasic-shaped** — `SUB`/`FUNCTION`, no line numbers | §3.3 |
| Locals | **Stack frames, recursion kept** — settled by the timing table, not by preference | §3.3 |
| Screen | **8 KB at stride 256**, keeping the hardware scroll | §2 |
| Storage | **Fake disk drives**, 16 volumes of 448 KB, own format, append-only directories | §5 |
| Source buffer | **Automatic** — main RAM, or VRAM, or spilled to flash on `RUN` | §3.4 |
| Boot ROM | **Rebuild**: autoboot from `$100000`, plus a raw flash *write* command | §6 |
| First work | **Benchmark before compiler** — measure the real programs, then generate code | §7 |

**Three consequences of the combination, worth seeing together:**

**Named files are now on the critical path.** Floats load from flash on
demand, the OS image itself is loaded by autoboot, and both need the
filesystem before either works. The directory code is the first thing
everything else waits on.

**The ROM change means a bitstream rebuild**, and therefore
re-verification on real silicon. The machine currently boots correctly on
hardware; that is a state worth not breaking casually. The ROM has 1,067
bytes free and both features must fit in it.

**The program-size ceiling is about 1,500 lines** in modes 0–4, where
native code lives in the 32 KB and the source sits in VRAM above the
framebuffer — and about 600–900 when both share main RAM. That is a large
program for an 8-bit machine and it is a real limit; §7's benchmark work
should confirm the 20-bytes-a-statement figure before it is relied on.

The goal stated for this milestone:

- **32 KB free for user programs**
- a **full-screen IDE**, as the better machines of the era had
- a language **like BASIC but fast like BBC BASIC**
- storage that feels like disks
- and a machine that is **best in class**, not merely period-plausible

---

## 1. What this machine brings that the era's did not

Worth listing first, because three of these change what the right answer
is rather than just making it nicer.

| | COOL8 | What the era had |
|---|---|---|
| Clock | 8.375 MHz, 2 clocks a register op | BBC Micro 2 MHz, C64 1 MHz |
| Text | 80×30, per-cell foreground and background nibbles | 40 columns, mostly one colour |
| Scrolling | the row pointer wraps in hardware — one register write | a 4 KB memcpy |
| Second memory | **64 KB of VRAM sits unused in text mode** | — |
| Sprites | independent of the background mode, so they work over text | sprites over text was rare and awkward |
| Storage | 8 MB flash, writable above `$100000` | 100–800 KB floppies |
| Debugger | a break button, a monitor in ROM, and reserved opcodes that trap | a reset button |

**The instruction rate is roughly four times a BBC Micro's.** 8.375 MHz
against 2 MHz, with comparable clocks per instruction. That is the single
most important fact for the language question: *the slowest option below
is already about as fast as the machine the goal names.*

**The 64 KB of free VRAM is the second.** Text modes read main RAM
(D28), so in mode 0 nothing but sprite patterns lives in VRAM. It is
reachable through `VRAM_ADDR`/`VRAM_DATA` with a programmable step:

| Access | Cost |
|---|---|
| Sequential byte, auto-increment | ~2–3 clocks — near main-RAM speed |
| Random byte (set the 16-bit address first) | ~11 clocks |

So VRAM is an excellent home for anything **scanned in order** and a
poor home for anything **indexed at random**. That maps exactly onto the
split an IDE wants: source text and disk buffers are sequential; variables
and compiled code are random.

---

## 2. Where the 32 KB comes from

```
$0000–$00FF    256 B   interpreter hot variables (this machine's zero page)
$0100–$01FF    256 B   OS variables, file control blocks, line buffer
$0200–$81FF     32 KB  ── USER: compiled code, variables, string heap ──
$8200–$A1FF      8 KB  text screen (mode 0 map, stride 256)
$A200–$FDFF     23 KB  the OS: editor, compiler, runtime, filesystem, drivers
$FE00–$FEFF    256 B   I/O page
$FF00–$FFF7            RAM; stack grows down from $FFF7
$FFF8–$FFFF      8 B   vectors
```

**32 KB user, 23 KB system, and it fits with room to spare.** For scale:
FastBasic's whole integer IDE on the Atari is 8 KB with a runtime under
3 KB, and Action! — editor, compiler, debugger and a 70-routine library —
was a 16 KB cartridge.

Three notes on that map:

**The 8 KB screen is the price of 80 columns with free scrolling.**
D30 chose a 128×32-cell map at stride 256 so a row address is one add
instead of a `MUL`, and so the hardware wrap works. Writing 160 to
`VID_STRIDE` gets a 4800-byte screen back and costs the multiply on every
row address *and* the hardware scroll — the wrap is a power-of-two mask.
**Recommendation: pay the 8 KB.** The editor performs row-address
arithmetic constantly and scrolls on every keystroke at the bottom of the
screen.

**The ROM overlay can be switched off.** `ROMEN=0` makes `$F000–$FDFF`
ordinary RAM, which is where the last 3.5 KB above comes from. It can be
switched back on — see §6.

**The source text does not appear in this map at all**, because it
should live in VRAM. That is the next section's point and it is worth
about 16–32 KB.

---

## 3. The language

### 3.1 What the measurements say

Three execution models, each running `A% = A% + B%` on two 16-bit
variables, 200 times, measured on `cool8emu`:

| Model | Clocks/statement | Statements/sec | Bytes/statement |
|---|---|---|---|
| **Native code**, variable addresses compiled in | **28** | **299,000** | 20 |
| **Subroutine-threaded**, one `CALL` per compiled statement | **37** | **226,000** | 3 |
| **Stack bytecode**, token → jump table | **176** | **47,500** | 4 |

And the dispatch overhead alone, with an empty operation:

| | Clocks per operation |
|---|---|
| Native — nothing to dispatch | 2.0 |
| `CALL abs16` + `RET` | **9.0** |
| Token → 16-bit table → `JMP [X]` | **31.2** |

**Token dispatch is unusually expensive on this ISA, and that is a
machine-specific finding that inverts the usual advice.** The reason is
concrete: there is no `LDW X,[X]`. Fetching a 16-bit handler address out
of a table costs a `LDW X,#table` (5), two indexed byte loads (6), two
half-register moves (6) and the jump (2) — and the table base has to be
re-established every time, because the machine has only two pointers and
the jump destroys one of them.

`CALL abs16` does the whole thing in **6 clocks**, in one instruction,
using the CPU's own program counter as the interpreter pointer.

**So on COOL8, subroutine threading beats bytecode dispatch by 3.5×.**
FastBasic chose bytecode on the 6502 for *size*; the same choice here
costs more and buys less.

### 3.2 The options

**A. Classic tokenised BASIC — MS/Atari style.**
Line numbers, `GOTO` by linear search, floating point by default.
~10 KB. This is the bottom of every benchmark table ever published and
there is no reason to build it.
*Verdict: no.*

**B. BBC BASIC's language, interpreted from tokens.**
Named `PROC`/`FN` with local variables, `REPEAT`/`UNTIL`, integer
variables, inline assembler. Re-scans and re-parses the token stream on
every execution. ~16 KB.
*Implication:* lands near the 47,500 statements/sec row — already about
a BBC Micro, on a machine that could do six times better. The language is
right; the implementation strategy is the one to leave behind.

**C. Compile to bytecode, interpret with a threaded loop — the FastBasic
model.**
Compile on entry or on `RUN`; a compact bytecode; 8 KB IDE + 3 KB
runtime on the Atari, 2× *compiled* Turbo-Basic XL.
*Implication:* the smallest user programs (4 bytes a statement) and the
slowest execution of the three serious options, because §3.1 measured
this machine's dispatch at 31 clocks. **The strategy that is right on a
6502 is the weakest one here.**

**D. Compile to native code — the Action! model.** ← *recommended*
One pass, no optimiser, variables at fixed addresses, code emitted
straight into the user area. Action! did this on a 6502 and ran **219×
Atari BASIC**, with compiles that felt instantaneous.
*Implication:* 299,000 statements/sec measured, and ~20 bytes per
statement. A 32 KB user area holds roughly 1,600 compiled statements —
**which is why the source belongs in VRAM** (§3.3). Costs the most
compiler: perhaps 8–10 KB against 4–5 KB for a bytecode compiler.

**E. Forth.**
The smallest and, per byte, the fastest — and its threading model is
exactly the `CALL`-based one this machine likes. 8–12 KB for a complete
system with its own editor and block storage.
*Implication:* it is not "a language like BASIC", it will not attract
anyone who did not already want it, and the block editor is a worse
answer than §4. Worth stealing *from* — its dictionary structure is a
good model for the symbol table — rather than adopting.

### 3.3 The recommendation

**BBC BASIC's language, compiled the way Action! compiled.**

- **Language:** procedures and functions with parameters and locals,
  `REPEAT`/`UNTIL`, `WHILE`, `CASE`, no line numbers, and an **inline
  assembler**. BBC BASIC's assembler was its best feature and it is
  nearly free here: `tools/opcodes.py` is already the single encoding
  table shared by the assembler, disassembler and emulator.
- **Types:** integer-first. `BYTE` (8), `INT` (16, signed) and `CARD`
  (16, unsigned) as Action! had them, plus 32-bit. **Floating point as a
  loadable library, never implicit** — implicit floats are the single
  biggest reason the era's BASICs were slow.
- **Codegen:** native, one pass, variables at fixed addresses. `CALL` to
  runtime routines for anything large — string operations, `PRINT`,
  array indexing, multiply-divide, graphics.
- **Source text in VRAM where it fits, compiled code in main RAM.**
  Recompiling from VRAM is a sequential scan at ~2–3 clocks a byte:
  **a 16 KB source recompiles in about 30 ms**, which is Action!'s
  "instantaneous" and then some. §3.4 is the part that decides when it
  fits.

**The one thing to decide with your eyes open: recursion.** Action!
dropped it to put locals at fixed addresses, and that is where a large
part of its speed came from. COOL8 has a full 16-bit stack pointer and
`LD/ST [SP+u8]` in 3 clocks, so *this machine can afford real stack
frames where the 6502 could not* — `sim/timing.py` and the M2 corpus
already exercise exactly that. Recommendation: **keep recursion**; the
frame costs about 3 clocks per local access instead of 4, and it is the
difference between a toy language and a real one.

### 3.4 Graphics and where the source lives

**The obvious objection: if the source is in VRAM, can a program use
graphics?** Yes — but the previous section stated its recommendation as
though VRAM were always free, and it is only free in text mode. What
each mode actually claims:

| Mode | VRAM used | Left over |
|---|---|---|
| 0/1 — text 80×30, 40×30 | 0 | **65,536** |
| 2 — tiles 40×30 (map + 256 patterns) | 12,288 | 53,248 |
| 3 — bitmap 640×480, 1 bpp | 38,400 | 27,136 |
| 4 — bitmap 320×240, 4 bpp | 38,400 | 27,136 |
| 5 — bitmap 256×192, 4 bpp, double-buffered | 49,152 | 16,384 |
| 6 — bitmap 256×240, 8 bpp | 61,440 | **4,096** |

Sprite patterns come out of the leftover column — up to about 8 KB if
every descriptor uses a different one.

**The fact that resolves this: the source is only needed at compile
time.** Once compiled, the program is native code in main RAM and the
source is dead weight for the whole of `RUN`. So there are three regimes,
and the OS can pick per program rather than once and for all:

**A. Source in main RAM — the default, and what every 8-bit machine
did.** Source, compiled code and variables share the 32 KB. **All 64 KB
of VRAM belongs to the program, in every mode including mode 6.** At
20 bytes a statement and ~30 characters a line, the ceiling is roughly
600–900 lines. *This alone meets the stated goal* — the VRAM trick is
what raises the ceiling, not what makes 32 KB possible.

**B. Source in VRAM, above the framebuffer.** In modes 0–4 there are
27 KB or more spare, so the editor's buffer and a full graphics mode
coexist with nothing given up. The ceiling roughly doubles, to ~1,500
lines, and the 32 KB in main RAM is compiled code and data only.

**C. Source spilled to flash on `RUN`.** For modes 5 and 6, and for any
program that wants every byte of VRAM. Writing 16 KB at ~500 KB/s is
about **32 ms** — one frame and a half, invisible against the compile
itself — and it is read back when you return to the editor. Flash
endures 100,000 erase cycles a sector, so this is not a wear concern at
one write per `RUN`.

**Regime C always works**, which makes it the honest general answer: the
editor's buffer is a cache, its permanent home is the file, and `RUN`
flushes it. A and B are then optimisations that avoid the 32 ms when
there is room — and there is room in every mode except 6.

**The one real casualty is editing and mode 6 at the same time**, which
is a thing no machine of the era could do either.

---

## 4. The IDE

### 4.1 What the era actually did, and what to take

| System | Approach | Worth copying |
|---|---|---|
| Atari/MS BASIC | line numbers, line editor | nothing |
| BBC Micro | line editor with the *copy cursor* — move the cursor over any text on screen and copy it into the current line | the idea that **the screen is the source of input**, yes; the mechanism, no |
| **Action!** | full-screen editor, no line numbers, two windows, block operations, global search and replace, built-in monitor as debugger | **all of it** |
| FastBasic | full-screen editor, compile-on-run, error jumps to the line | the error model |
| Forth | block editor, 16×64 screens | no |

**No line numbers is the decision that unlocks everything else.** Line
numbers exist because a line editor needs a way to name a line. A
full-screen editor does not, and once they are gone the language gets
procedures, the editor gets ordinary text handling, and `GOTO` stops
being the control structure.

### 4.2 What this machine can do that none of them could

- **Syntax highlighting, free.** Every text cell is a character byte and
  an attribute byte — 16 foreground and 16 background colours per cell.
  The editor is already writing the character; writing the colour beside
  it costs one more store, and the tokeniser already knows what colour it
  should be. **No 8-bit home computer had this.**
- **Scrolling costs one register write.** `VID_BASE` moves and the row
  pointer wraps in hardware. Scrolling a 4640-byte screen used to be a
  memory copy; the monitor already exploits this.
- **80 columns means real code.** 40-column machines forced abbreviations
  and one-letter names into the culture. This one does not.
- **A hardware pointer over text.** The sprite engine is independent of
  the background mode and positions in final raster coordinates, so a
  mouse cursor — or a marked search hit, or a breakpoint arrow — can sit
  over 80-column text at no cost to the editor.
- **Two windows fit.** 30 rows split as 14/14 with a status line and a
  command line, which is Action!'s layout with room the Atari did not
  have.
- **The break button is a debugger key.** `SW[0]` is an NMI in hardware
  with a 2 ms debounce; it can stop a runaway program and hand it to the
  monitor.

### 4.3 The proposal

A single integrated screen, Action!-shaped:

```
┌────────────────────────────────────────────────── 80 x 30 ──┐
│ status: file, drive, line:col, dirty flag, free bytes       │  row 0
├─────────────────────────────────────────────────────────────┤
│ source, syntax-coloured, 80 columns                         │  rows 1-27
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ immediate mode / compiler messages                          │  rows 28-29
└─────────────────────────────────────────────────────────────┘
```

- Compile on `RUN`; on error, put the cursor on the offending token and
  the message on row 28.
- Immediate mode compiles one statement into a scratch buffer and calls
  it — the same code generator, so there is no second implementation of
  the language.
- Split the source pane in two on request (Action!'s two windows).

---

## 5. Storage

### 5.1 What the flash actually is

- 8 MB, of which **everything below `$100000` is refused in gates**
  (D42) — 7 MB usable.
- Erase granularity is a **4 KB sector**; erase sets a sector to `$FF`.
- **Programming can only clear bits.** This is the fact the design should
  be built around, not worked around.

That last point matters more than it sounds. A directory entry can be
**marked deleted by clearing a byte to `$00`** without erasing anything,
and a new entry can be **appended into the erased tail of a sector**.
So an append-only directory needs no read-modify-write and no 4 KB RAM
buffer at all — compaction happens rarely, when a sector fills.

### 5.2 The options

**A. No filesystem — flash offsets, as now.**
`L dest len flashH` copies from an offset. Zero code.
*Implication:* fine for a monitor, hopeless for an OS. No names, no
sizes, no way to know what is there.

**B. Fixed-size slots — the cartridge model.**
7 MB ÷ 64 KB = 112 slots, each with a 16-byte header (name, length, load
address, type). Directory = a scan of the headers.
*Implication:* ~500 bytes of code, no fragmentation ever, saving is
"erase 16 sectors and program". Wastes almost all of the flash on small
files, and there is no way to have 400 short BASIC programs.

**C. Fake disk drives — your idea, and a good one.** ← *recommended*
Carve the 7 MB into volumes and mount them by number: `0:`, `1:`, `2:`.
Sixteen volumes of 448 KB each, or eight of 896 KB. Each volume has a
4 KB directory sector at its front (256 entries of 16 bytes) and a flat
data area.
*Implication:* it is what the era actually felt like — the BBC's DFS was
100 KB a side and nobody minded. Each volume is independently
backed up as one file on the PC. The append-only directory of §5.1 fits
inside one sector per volume. **Code: ~2 KB.** No subdirectories, which
at 256 files a volume is not a real loss.

**D. FAT12 or FAT16.**
*Implication:* the machine and your desktop read and write **the same
filesystem**. Build a disk image on the PC, `icesprog` it, and COOL8 sees
the files — and vice versa. That is a genuine best-of-class argument and
nothing else on this list has it.
*Cost:* ~4 KB of code, a 4 KB sector buffer for read-modify-write (put it
in VRAM — see §1), FAT12's 224-entry root directory limit, and none of
the append-only trick above, because FAT wants to rewrite in place.

**E. LittleFS or SPIFFS.**
*Implication:* out. LittleFS targets systems with ~32 KB of RAM and
512 KB of ROM — that is this entire machine, twice over.

### 5.3 The recommendation

**Option C, with a PC-side tool that reads and writes the volume format
— and reconsider D if desktop interop turns out to matter more than
simplicity.**

The interop argument for FAT is real but it is mostly satisfied by a
50-line Python tool in `tools/`, which this project would write anyway
and can gate against the emulator's flash model. What FAT buys over that
is mounting the image directly in Windows Explorer. That is a genuine
convenience and it costs 2 KB of code and the sector buffer; it is a
reasonable thing to choose, and it should be chosen deliberately rather
than by drift.

---

## 6. How the monitor ties in

The monitor is 4 KB of block RAM at `$F000`, present at reset, and it is
already three of the things an OS needs and none of the things it
shouldn't be.

**At boot.** ROM → clear RAM → monitor. To reach an OS, either:

1. **The monitor autoboots** — look for a signature at `$100000`, load
   and run it, fall back to the prompt if it is absent. Costs a few dozen
   bytes of the 1,067 currently free in the ROM, and changes the ROM,
   which means rebuilding the bitstream.
2. **The user types `L` then `G`** — costs nothing and is worse every
   single time.

Option 1, clearly — but note it is a *hardware* change in the sense that
the bitstream carries the ROM.

**After boot.** The OS switches `ROMEN` off and owns `$F000–$FDFF`. The
monitor's code is then not addressable.

**As the debugger.** This is the part worth designing rather than
inheriting. Three hardware features already point at the monitor:

- `BRK` — a software interrupt with its own vector
- **reserved page-2 encodings trap** — so a runaway program counter lands
  in the debugger instead of executing garbage
- the **break button** on `SW[0]`, an NMI

All three vector through RAM at `$FFF8`. So the OS installs handlers
that **set `ROMEN` back to 1 and jump into the monitor**, and the monitor
becomes a debugger reachable from anything, at any time, including from a
program that has destroyed itself. The 8 KB text screen is untouched by
this, so the debugger can display over the IDE's screen and give it back.

**What the monitor should not become.** It should not grow the
filesystem, or a save command that duplicates the OS's. It is the
bootstrap and the last resort. The division that keeps it honest:

> The monitor knows about **flash offsets**. The OS knows about
> **files**.

If the ROM is being rebuilt for autoboot anyway, the one addition worth
considering is a raw flash *write* command — purely so the machine can
bootstrap its own OS onto a blank board without a PC. That is a real
capability gap today: the hardware can write flash and no software does.

---

## 7. The combination, as chosen

The table below was the recommendation; every row of it was taken. The
plan that follows from it is [`OS_PLAN.md`](../OS_PLAN.md).

| | Choice | Why |
|---|---|---|
| Language | BBC BASIC's shape — procedures, locals, structured loops, inline assembler | it is the goal named, and it is the best of the era's languages |
| Types | integer-first, floats as a library | implicit floats are why the era was slow |
| Execution | **native code, one pass, Action!'s model** | measured 299,000 statements/sec — 6.3× a bytecode interpreter on this ISA |
| Stack frames | keep recursion | `[SP+u8]` in 3 clocks; the 6502's excuse does not apply here |
| Source | home is the file; buffered in VRAM when the mode leaves room, spilled on `RUN` when it does not | modes 0–4 leave 27 KB or more; mode 6 leaves 4 KB and costs a 32 ms spill (§3.4) |
| Editor | full screen, no line numbers, two panes, syntax colour | 80×30 with per-cell attributes makes it free |
| Storage | fake drives on flash, append-only directories | fits NOR flash's physics with no RAM buffer |
| Monitor | autoboot, then the always-reachable debugger | it already has the three traps that make that work |
| Budget | 32 KB user, 23 KB system, 8 KB screen | Action! did all of it in 16 KB |

### What to measure before committing

This project's rule is that a limit asserted is a limit nobody knows —
D43 cost a milestone to learn that. The emulator now counts clocks, so
all of these are answerable in an afternoon and none of them needs
hardware:

1. **A real benchmark, not one statement.** Sieve, and the Rugg/Feldman
   set, hand-compiled into each of the three models. The 6.3× spread
   above is one statement's worth of evidence.
2. **How big is the compiler, really?** Write the code generator for
   *one* statement type and extrapolate. If native codegen turns out to
   be 14 KB rather than 9, the budget changes.
3. **How much does a 32 KB user area actually hold** in native code —
   compile a real 500-line program and look.
4. **Is VRAM-resident source fast enough for the editor's inner loops?**
   Insert a character in the middle of a 16 KB buffer and time it.
5. **The `[SP+u8]` frame cost against fixed addresses**, to settle the
   recursion question with a number rather than a preference.

---

## 8. Questions that are yours, not mine

- **Floats at all?** Action! shipped without them and was loved. A
  machine that cannot evaluate `1/3` will still surprise people.
- **FAT12, or our own format with a PC-side tool?** Simplicity against
  plugging the flash image into Explorer.
- **Does the ROM get rebuilt** for autoboot and raw flash write? It is a
  bitstream change and the ROM has 1,067 bytes free.
- **Is the language BASIC-shaped or Action!-shaped in its syntax?**
  `PROC`/`ENDPROC` or `PROC`/`RETURN`; `PRINT` or `PrintF`. The
  implementation is identical either way — this is purely what it should
  feel like to type.

---

## Sources

Era implementations referenced above:
[Action!](https://en.wikipedia.org/wiki/Action!_(programming_language)) ·
[FastBasic](https://github.com/dmsc/fastbasic) ·
[Turbo-BASIC XL](https://en.wikipedia.org/wiki/Turbo-BASIC_XL) ·
[6502 BBC BASIC](https://beebwiki.mdfs.net/6502_BBC_BASIC) ·
[littlefs design](https://github.com/littlefs-project/littlefs/blob/master/DESIGN.md)
