# ASM_MOVE_PLAN.md — moving the editor into assembly, by subsystem

**The working plan for [D68](docs/01-decisions.md).** `docs/` stays the
source of truth for *why*; this file is the ordered list of *what next*,
and it is expected to be edited as modules land. When it disagrees with
`docs/01-decisions.md`, the decision entry wins.

Same standing as [RUST_PORT.md](RUST_PORT.md): a port plan, kept until
the port is done, then deleted.

---

## 1. Why, in numbers

| | |
|---|---|
| `sw/basic.bas` | **11,008 bytes**, 87 routines, ~47 % of a 23,528-byte image |
| measured density penalty | **5.4x** (`putn`, 266 → 49), **6.4x** (`number`, 193 → ~30) |
| where the bytes go | **63.6 % moving data**, 21.7 % arithmetic, 13.9 % control flow |
| what a peephole could save instead | **697 bytes** of 11,008 |

`python sim/build_basic.py --waste` prints the last two. Two thirds of
every compiled routine is shuffling values between stack slots and
registers, because `tools/cool8bas.py` has no register allocator. That
is the whole of the 5x, it is not the algorithms, and it is not
cheaply fixable — which is why this is a hand-port and not a compiler
project.

**`console.asm` is the first real measurement, and it came in at ~2.0x, not
5x.** It replaces 2,170 bytes of compiled routines with about 1,080 of
comparable code (1,258 total, less `bglyph`, which was already hand
assembly and was never counted in the 11,008).

So **revise the expectation down**: if the rest behaves like the
console, 11,008 becomes ~5,500 and the port recovers **~5,500 bytes**,
not the 7,300–8,800 first projected off `putn` and `number`. Those two
were small, arithmetic-heavy leaves — the best case for hand-writing,
not a sample. The console is probably the *worst* case, being address
arithmetic and mode tables, so the truth is likely between; `token.asm`
is the next honest data point.

Recording it here rather than quietly hoping, because a plan that
quotes a number it cannot hit is worse than one that admits a range.

---

## 2. The shape it is moving into

Modules by subsystem, each entirely in one language, with command
handlers next to their dispatch. Not one flat file: today
`sw/interp.asm` calls **23 routines inside `sw/basic.bas`**, so the
language boundary runs through the middle of every subsystem, and a flat
merge would remove the language line without creating a single boundary.

| module | what it owns | it may call |
|---|---|---|
| `console.asm` | screen in all four modes, cursor, scroll, `emit`/`puts`/`putn` | nothing |
| `kbd.asm` | keys and the serial line, into one ring | nothing |
| `token.asm` | tokenise **and** detokenise, over one table | `con` (LIST), `snum` |
| `prog.asm` | the store: find, insert, delete, renumber, list | `con`, `token` |
| `edit.asm` | screen-as-document: read a row back, continuation lines, insert/delete | `con`, `kbd`, `token`, `prog` |
| `interp.asm` | the language, and the command handlers | `con`, `prog`, `token`, `fs` |
| `fs.asm` / `fscmd.asm` | volumes, and the disk commands | `con`, `prog` |
| `main.asm` | boot and the prompt loop | everything |

**The rule that keeps it honest:** a module may only call downward in
that table. If a routine wants to call upward, it is in the wrong
module.

---

## 3. Method — not optional

These are the rules the last two sessions were bought with.

1. **Characterise before porting.** The routine's behaviour goes into
   the suite *first*, so the port is a refactor with a net under it.
   `s_putn` went in without one, broke `PRINT` for negatives, and cost a
   round.
2. **Report the size at every milestone**, not at the end.
   `python sim/build_basic.py`.
3. **Run `python tools/memmap.py --check`** after anything that claims
   storage. Every `;:` claim is checked for a second owner; the region's
   floor is computed, not chosen ([D67]).
4. **Reach for the tooling at the first sign of a fault**, not the
   tenth. `sim/test_basic.py --trace <label> "<line>"`, `m.trace()`,
   `m.watch()`. Bisecting by re-running the suite has cost this project
   multiple rounds.
5. **No throwaway scripts.** Everything through `sim/harness.py` and the
   Machine API; extend them when they fall short.
6. **Leave the state you found** when adding cases mid-suite — inserting
   a `NEW` once broke three downstream tests.
7. **Review each routine after writing it**, and do an optimisation pass
   at the end. Size first, then speed — but it is sometimes right to be
   bigger for an accumulated speed win.

### The gate for every step

```
python -m poethepoet test      # 12
python -m poethepoet check     #  6
python sim/build_basic.py      # size, reported
```

RTL is only involved if `rtl/` changes — it should not, in this whole
plan.

---

## 4. The order, and what is in each module

Sizes are the compiled cost today, from the symbol table. They
reconcile to 11,008.

### 4.1 `console.asm` — the console — 2,179 bytes  ← **start here**

`setgeom` 416 · `scroll` 229 · `bput` 195 · `putat` 189 · `tilefont`
180 · `emit` 139 · `newline` 105 · `tput` 104 · `curdrw` 103 ·
`brepaint` 95 · `cls` 66 · `clearrow` 59 · `putsn` 58 · `puts` 55 ·
*`putn` 49 (done)* · `rowaddr` 41 · `dnrow` 41 · `getat` 32 ·
`showcur` 23

**Why first.** Everything calls it: 7 of the 23 boundary crossings are
console, and every routine ported after this one prints. Doing it first
removes `CALLB1` from the hot path and means no later module has to
call *up* into compiled BASIC. It is also the most mechanical code in
the file — address arithmetic and stores, no parsing to get wrong.

**The hard part is `setgeom` (416)**, which reconciles four screen modes
with the editor's idea of geometry. Port it last within the module,
after the primitives it uses exist.

**Watch:** `putat`/`tput`/`bput` are three renderers for one job (text
cell, tile, bitmap glyph). Look for the shared shape before writing
three routines.

### 4.2 `kbd.asm` — input — 622 bytes

`serialkey` 393 · `getkey` 158 · `waitraw` 39 · `rawkey` 32

`sw/kbd.asm` already exists and owns PS/2 decoding; this is the *ring
and the line discipline* above it. `serialkey` is large because it
decodes ANSI escape sequences.

### 4.3 `token.asm` — the tokeniser — 1,719 bytes

`tokenise` 872 · `lookup` 209 · `puttok` 145 · `ishex` 105 · `puttnum`
85 · `isident` 80 · `isalpha` 57 · `hexof` 51 · `upper` 44 · `isdigit`
39 · *`number` 32 (done)*

**Redesigned, not ported** — see §5. This is where the float literal
lands and where `isdigit`/`ctab` stop being two answers to one question.

### 4.4 `prog.asm` — the program store — 1,392 bytes

`storeline` 444 · `list` 338 · `deleterange` 180 · `renumber` 127 ·
`findline` 92 · `memmove` 79 · `lineno` 48 · `nextline` 42 · `linelen`
17 · `freebytes` 14 · `new` 11

**Delicate.** `storeline` and `memmove` are where a bug corrupts the
user's program rather than printing something wrong. Characterise
hardest here.

### 4.5 `edit.asm` — screen as document — 1,335 bytes

`writelog` 200 · `delchar` 195 · `insch` 191 · `readrow` 171 · `enter`
168 · `lend` 90 · `shiftlbuf` 76 · `backspace` 55 · `lpos` 50 ·
`curleft` 49 · `lstart` 40 · `doreset` 37 · `gotoend` 13

The C64's arrangement: the screen *is* the document and a logical line
is read back off it. `cont[]` marks continuation rows.

### 4.6 `interp.asm` — the command handlers come home

No new bytes; this is where `h_list`, `h_new`, `h_save`, `h_run` and the
rest stop being `CALLB1` into compiled BASIC and become handlers next to
their `sttab` entry. Do it as each module lands, not as a separate step.

### 4.7 `fscmd.asm` — the disk commands — 2,942 bytes

`rewritedir` 636 · `docompact` 456 · `loadcore` 314 · `parsename` 307 ·
`dodir` 304 · `nextsrc` 196 · `fetchline` 80 · `savecore` 79 ·
`loaddata` 62 · `skipsp` 47 · `entpage` 47 · `savedata` 46 · `entpages`
46 · `wrpage` 34 · `rdpage` 34 · `fssave` 34 · `fsload` 34 ·
`drivecore` 33 · `fsfind` 30 · `dofree` 27 · `erasesect` 26 ·
`eracore` 26 · `fsreadent` 19 · `fserase` 18 · `fsmount` 7

**Cold code, and the least-exercised in the image** — which is the risk.
Second-largest module and pure size win, no speed argument either way.
Last, because a fault here is a corrupted volume rather than a wrong
character on screen.

### 4.8 `main.asm` — the shell — 819 bytes

`dodirect` 328 · `runerr` 238 · `dorun` 138 · `errmsg` 115

Last. When this lands, `sw/basic.bas` is empty and is deleted, and the
entry point moves. This is [D66]'s stage 5 and the shape stays the one
BBC BASIC has: read a line, tokenise it at entry, look for a line
number, store it or run it now.

---

## 5. Cross-cutting work, and when

### 5.1 Generate the token values — **before `token.asm`**

`TOKTAB`'s numbering is currently hand-copied into ~25 `K_*` equates in
`sw/interp.asm`, a `CONST T_LIT` in `sw/basic.bas`, and a **private
37-word list in `sim/test_interp.py`** — in a table of seventy.
[D65] called the order frozen because "programs on disk hold the old
numbering"; **there is no installed base**, every `.img` under
`sim/build/` is generated by the suites, and the only real dependencies
are those copies.

`tools/vocab.py` already reads `TOKTAB`, `sttab` and `btab`. Have it
generate `sw/tokens.asm`, gate it in `poe check` like `ioregs.py`, and
the order stops being something anyone has to remember.

### 5.2 Token flag bits — **with `token.asm`**

Read from the BBC BASIC disassembly, not a manual: its `TOKENS` entries
carry eight flags. COOL8 wants two.

- **rest of the line is verbatim** — deletes the inline `REM`
  special-case `tokenise` carries today.
- **a line number follows** — after `GOTO`, `GOSUB`, `THEN`, `LIST`,
  `DELETE`.

70 bytes of table for both.

### 5.3 Fix `RENUMBER` — **with the flags**

**It is broken today.** It rewrites each line's own number and never
looks inside the tokens, so every `GOTO` in a renumbered program points
at the wrong line, and nothing in the suite catches it. With the
line-number flag it is two passes: build the old-to-new map, then walk
the program rewriting references.

**Keep it small; it is allowed to be slow.** Almost nobody runs
RENUMBER, so a re-scan per line is fine and no table needs to be
cached.

### 5.4 The float literal — **with `token.asm`**

`PRINT 1.5` is `?SYNTAX` today, the last loud gap in
[13-basic.md §8](docs/13-basic.md). A hand-written tokeniser calls
`snum`, which already parses fractions and already decides integer or
float, and emits `T_LIT`+2 or a new `T_FLT`+3. Then `prim` grows an arm
and `LIST` renders through `fstr`.

BBC packs numeric constants at entry too (`tknCONST` + 3 bytes), so
COOL8's `T_LIT` + 2 was inherited correctly — this is finishing it, not
departing from it.

### 5.5 Evict the compiled globals — **with `prog.asm` / `edit.asm`**

`a_lbuf` (128), `a_tbuf` (128) and `a_spg` (32) are **324 bytes of `.res`
zeros inside the image**, carried in flash and copied at boot purely to
reserve RAM. They become claims in the system storage region ([D67]) as
the routines that use them are hand-written. 324 of the current 792 free
bytes are already spoken for by this.

### 5.6 One of each — **as the modules land, not as a stage**

[D66]'s stage 0. These stop being duplicates for free once both sides
are assembly, so do not schedule them separately:

| job | implementations today | resolves with |
|---|---|---|
| text → number | `snum`, `tokenise`'s inline loop, `number()` | `token.asm` |
| number → text | `sstr` (accumulator), `s_putn` (screen) | `console.asm` |
| "is this a digit" | `isdigit` in BASIC, `ctab` in the interpreter | `token.asm` |

---

## 6. Burn-down

**Measured, not ticked off by hand:**

```
python sim/build_basic.py --by-module
```

```
    module   routines    bytes
    con            19    2,179     written: sw/console.asm, 1,258 b, sim/test_con.py
    kbd             4      622     <- next
    token          11    1,719
    prog           11    1,392
    edit           13    1,335
    fscmd          25    2,942
    main            4      819
    total          87   11,008
```

The compiled column stays at 11,008 until `main.asm` takes the entry
point and `basic.bas` is deleted — the new modules are a *parallel*
implementation and nothing calls them yet, which is deliberate: no
shims, no `CALLB1`, no EXTERN dance, and the machine keeps working
throughout. Each module gets a suite of its own at the time it is
written, the way `sim/test_fs.py` drives `sw/fs.asm`.

The grouping lives in `MODULES` in `sim/build_basic.py` because *which
module a routine belongs to* is a decision and belongs to this plan. The
bytes are read from the symbol table, and a routine that has moved to
assembly stops being an `s_` symbol with a compiled body — so
"remaining" falls out on its own and **this table cannot go stale**. A
routine in neither the plan nor a module is reported by name.

Every hand-maintained table this project has written down has drifted —
the drop table in 13-basic.md was five guesses, `zp.asm`'s free-space
figure was wrong three times running, `memmap.py`'s page-0 map missed
thirteen bytes. This one is measured for that reason.

Already done, in `sw/ed.asm`: `putn` (266 → 49), `number` (193 → ~30).

Image was **23,528 bytes, 792 free** when this plan was written.

---

## 7. Traps this plan already knows about

- **A compiled `FUNCTION foo()` is label `s_foo`.** Do not squat on the
  name in assembly unless you are replacing it.
- **`s_emit` is a compiled `SUB`**: the argument is on the stack, not in
  R0. Use `CALLB1` while the caller is still BASIC.
- **Local labels resolve against the preceding global**, so a
  cross-scope branch needs a global join point.
- **The assembler splits operands on commas before recognising
  character literals** — `MOV R0,#','` is three operands. Write `#$2C`.
- **Heredocs mangle backslashes** in this environment; use the Edit tool
  or build the byte.
- **A ported routine runs in the editor's context.** Check
  `tools/memmap.py --check` before, not after the wild jump.
- **An address written down is a fault waiting for something to move.**
  [D67] cost a session proving it: `nextline` marked direct mode by
  testing `LREC+1 == $FF` because `DIRBUF` happened to live at `$FF88`.
  Use symbols.
