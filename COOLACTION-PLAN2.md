# CoolAction! plan 2 — a demo disc, three menus, and two ports

**Status: executed, 2026-09-10.** All six phases are done and green;
the record is in the repository, not here -- [D98](docs/01-decisions.md)
for the library and the gate, [D99](docs/01-decisions.md) for the disc
and the menus, [15-action.md](docs/15-action.md) section 5 for the
measured numbers, [14-demos.md](docs/14-demos.md) for what ships. Two
things the plan did not foresee: drive 14 cannot hold all four Infocom
stories, so one spills to 13 where the interpreter looks second; and
the window binary could not be built on the machine that did the work
(no `cmake` for SDL), so `rust/src/bar.rs`'s three menus are unverified
there. The text below is the plan as proposed.

**Rectify the standard library first. Nothing else starts until it is
done.** Seventeen of the thirty hardware addresses in
`sw/libaction.act` do not match the machine. It was written from plan
1's prose, which invented a register map, rather than from the
generated one. `SetColor` writes the cursor position, `WaitVBlank`
polls the border colour and would hang, and the timer calls write into
a hole nothing decodes. It compiles cleanly, which is why nobody
noticed — the gate that would have caught it reads only `.asm` and
`.bas`, so `.act` walked straight past it. Both ports need this fixed
first, since one sets a palette and the other flips a double buffer.
That is [1.1](#11-swlibactionact-has-the-wrong-hardware-addresses) and
it is phase 1.

One thing has already been done, because it was a mess rather than a
decision: `demos/bapple/` was tidied and documented (see 1.2).

The first round shipped the compiler, the language reference
([docs/15-action.md](docs/15-action.md)) and its gate
([D97](docs/01-decisions.md)). This round is about getting compiled
programs onto a disc, in front of the user, and proving the language
on real demos rather than a benchmark.

---

## 1. What the research turned up

Five things that were not obvious from the outside, in order of how
much they change the plan.

### 1.1 `sw/libaction.act` has the wrong hardware addresses

**Seventeen of its thirty register equates are wrong.** The standard
library was written from plan 1's prose, which invented a register
map, rather than from `tools/ioregs.py`, which reads the real one out
of the Verilog that decodes it.

| `libaction.act` says | it is really |
|---|---|
| `pal_idx = $FF22` | `CUR_X` — the palette index is `$FF1E` |
| `pal_data_l = $FF23` | `CUR_Y` — palette data is `$FF1F` |
| `vid_status = $FF1A` | `VID_BORDER` |
| `pix_ctrl = $FF30` | `VID_DBASE_H` |
| `pat_base = $FF20` | `VID_PAT_L` |
| `vid_scrlx = $FF16` | `VID_SCX_L` |
| `tmr0_cnt = $FF52`, `tmr0_ctrl = $FF54` | nothing decodes there at all |

So `SetColor` writes the cursor position, `WaitVBlank` polls the
border colour and never returns, and the timer calls write into a hole.
The library compiles, and its size was reported, and none of that
means anything.

**Nothing caught it because the gate does not look at `.act` files.**
`tools/ioregs.py` globs `sw/*.asm` and `sw/*.bas`; `poe check` fails on
a bare `$FFxx` anywhere in those and has done since
[D67](docs/01-decisions.md). `.act` is a third source language nobody
told it about. This is exactly the trap D67 exists to prevent, entered
through a door that was not there when D67 was written.

**The fix is the one the project already uses**: `tools/ioregs.py`
grows an `sw/io.act` output beside `sw/io.asm` and `sw/io.bas`,
`libaction.act` includes those names instead of writing addresses down,
and the check's glob grows `*.act` so this cannot recur. That is a
prerequisite for both ports — RAINBOW sets a palette and COBRA flips a
double buffer, and neither can work against an invented map.

### 1.2 Bad Apple was already capped to one drive — but only on disk

**Drive 11 is free, and the film is not a hazard.** An earlier session
capped Bad Apple to drive 12 alone and the cap is real; what it is not
is *recorded*. It lives entirely in a directory `.gitignore` excludes:

| | |
|---|---|
| `demos/bapple/` | 7 chunks, 344 frames, **drive 12 only** — what every disc build uses |
| `demos/bapple/full-12-drive/` | the full build, kept and not used: 82 chunks, 3,257 frames, manifest naming **drives 1–12** |

**Decision: keep the full build, ship the cut.** The twelve-drive film
stays on disk; drive 12 alone is what the disc gets. That directory has
been tidied and now carries a `README.md` saying which half is live,
that the stub and the manifest are a matched pair, and what the traps
are — a duplicate orphan chunk was removed from the top level and the
one genuine orphan in the full build, an 83rd chunk predating the
credits-tail trim, is documented rather than deleted.

`tools/mkdemos.py` walks `demos/bapple/manifest.json`, so the live
manifest is what decides, and it names one drive. That is the working
state and it is deliberate.

The repository still describes the other one. `tools/mkbadapple.py`
line 61 is `DRIVES = list(range(12, 0, -1))`, and `docs/14-demos.md`
still says "82 chunks across all twelve dedicated drives" with 3,257
frames. So **a rebuild from the mp4 goes straight back to twelve
drives** and would overwrite whatever is on 11 — not because the cap
was forgotten, but because nothing in the tree knows about it.

One more thing the full build settles: its manifest really does reach
**drive 1**, which is `USER_VOL`, so the twelve-drive plan always
collided with the volume a cold machine comes up on. The cap avoids
that as a side effect, which is a second reason not to undo it.

**So the remaining work here is bookkeeping.** Take drive 11, and make
the cap something the repository states rather than something the
working directory happens to be in:

- `tools/mkbadapple.py` takes the drive list as a parameter with drive
  12 the default, so the capped build is the one it makes.
- `docs/14-demos.md` says what ships — one drive, 344 frames — and that
  the full film is a rebuild, what it costs in drives, and that it
  collides with `USER_VOL` if allowed all twelve.
- `tools/mkdemos.py` asserts that no manifest chunk lands on a drive
  another volume claims, so this can never be silent again.

For reference, the allocation as it stands:

| drive | holds |
|---|---|
| 0 | `SYSTEM` — `BOOT.BIN` |
| 1 | `USER_VOL`, where a cold machine comes up |
| 2–10 | free |
| **11** | **`ACTION` — the CoolAction disc, the Demos menu's compiled twin** |
| 12 | `BAPPLE`, capped to this one drive |
| 13 | `DEMOS` — the Demos menu |
| 14 | `ADVENTUR`, relabelled `SOFTWARE` — the Software menu |
| 15 | `PASCAL` — the p-System's own volume, not a menu |

For the record, the arithmetic behind the cap: the full stream is
5,259,513 bytes against 454,656 usable per volume, **11.57 volumes**,
which is why it took twelve and reached drive 1. The capped build is
344 of 3,257 frames and fills drive 12 alone.

### 1.3 The launcher can only launch `.BAS`, by design

`cool8disk.catalogue()` returns `.BAS` files only, and its docstring
argues the case: the menu restarts the machine and types
`DRIVE n` / `LOAD "STEM"` / `RUN`, and anything that is not a `.BAS`
cannot be launched that way. Bad Apple is why — it once put 82
unrunnable `.DAT` chunks in the menu.

A compiled CoolAction program is a `.BIN`, and it *can* be launched:
`SYS "NAME.BIN"` loads it to the address in its own two-byte header and
jumps there ([D87](docs/01-decisions.md)). So the catalogue grows a
**kind** per entry — `bas` or `bin` — the docstring's rule becomes "a
program is something the machine can start, and there are two ways",
and `web/app.js` types one of two launch strings depending on kind.

### 1.4 `LINE` is a specific Bresenham, and "exact" means matching it

Both ports draw lines, and `sw/libaction.act` has no line routine —
only `Plot`, `HLine` and `VLine`. BASIC's is `h_line` at
`sw/interp.asm:5518`, and it is not a textbook Bresenham:

- `y0 == y1` is not handled there at all; it jumps to `hrun`, a
  separate horizontal span writer that runs at about 22 cycles a pixel.
- Otherwise the line is **always drawn downward** — if `y1 < y0` the
  endpoints are swapped — so the y step is always the pixel port's own
  `PIX_DATA_Y` increment and there is no `sy` to carry.
- The endpoint test is a **pixel countdown**, `max(dx,dy)+1`, not a
  coordinate compare.
- On exact half-step ties this picks the mirror pixel of what a walk
  from the caller's end would choose, and the comment says
  `sim/test_run.py`'s fan is the contract for that.

A port that draws visibly the same picture but ties differently is not
an exact port. So `Line()` in the library follows `h_line`'s structure —
same swap, same countdown, same error initialisation — and gets a test
that draws a fan both ways and compares the framebuffers pixel for
pixel.

### 1.5 "The lines thing" is `RAINBOW` — confirmed

There is no `demos/lines.bas`. The demo that is about lines is
**`RAINBOW`** — `docs/14-demos.md` calls it "a bouncing line with a
fifteen-line trail": two endpoints bounce independently around mode
4's 320×240, a ring buffer of fifteen holds the older lines so the
trail erases oldest-first, and the colour is the ring slot so the trail
walks the palette. Confirmed as the first port.

It is a good first port for the reason the doc gives: it is a
demonstration of `VSYNC` more than of `LINE`, so it exercises frame
pacing, a palette write, arrays and a ring buffer, and it is 60 lines.

---

## 2. What the two ports actually need

### RAINBOW — small, and mostly already there

| needs | status |
|---|---|
| `MODE 4`, cursor off | `Graphics()` exists; needs the corrected `VID_MODE` and `CUR_CTRL` |
| 16-entry palette write | **blocked on 1.1** — `SetColor` writes the wrong register |
| `CLG 0` | **missing** — the plan promised `Clg` and the library has no such routine |
| `LINE` | **missing** — see 1.4 |
| `VSYNC` | `WaitVBlank` exists and polls the wrong address |
| `DIM A(14)`…`D(14)`, ring index | arrays work, tested |
| `DATA` for the palette | no `READ`/`DATA` in the language; becomes `CARD ARRAY pal = [...]` |

Everything else is integer arithmetic and `IF`, which the language has.
**Estimated: one file, ~90 lines, once the library is fixed.**

### COBRA — large, and the interesting one

Elite's Cobra Mk III: 72 precomputed frames of a rotating wireframe
with hidden lines removed, played back on mode 5's double buffer.

| needs | status |
|---|---|
| `MODE 5`, double buffer flip | needs correct `VID_DBASE_H` / `VID_BASE_H`; `FlipBuffer` was promised and does not exist |
| 13 arrays, ~19 KB total | arrays work; `CARD ARRAY H(1772)` and friends are the bulk |
| `READ`/`DATA`, ~2,300 numbers | becomes initialised arrays; the culling table is ~1,850 bytes |
| integer `/256` | `>> 8`, already generated well |
| `LINE` × ~1,771 per frame | see 1.4 |

Two things to decide while writing it, neither blocking:

- **The vertex arrays can be `BYTE`.** `H`/`J`/`L`/`M` hold mode-5
  screen coordinates and the DATA never leaves 0–255, so byte arrays
  halve 14 KB to 7 KB. The BASIC uses integer arrays because BASIC has
  only integers. Byte is the same picture in half the memory; it is a
  judgement call whether that is still "exact".
- **`.space` costs file size.** An uninitialised array is emitted as
  zeros, so ~19 KB of arrays is ~19 KB of PRG. It fits a 448 KB volume
  many times over, so this is a note, not a problem.

**Estimated: one large file, ~400 lines including the data tables,
plus a generator to turn the `DATA` statements into initialisers.**

---

## 3. The plan

Six phases, in order. Each ends somewhere the tree is green.

**Phase 1 blocks every other phase.** It is not sequencing preference:
phases 2, 5 and 6 all write to video registers, and until the library
names the right ones there is no way to tell a broken port from a
broken library. A green phase 1 is what makes every later failure mean
something.

### Phase 1 — make the library true *(blocking)*

Rectifying 1.1: the library's register map is wrong in seventeen of
thirty entries, and the gate that should have caught it does not read
`.act`. Fix both, in that order — the map, then the gate that keeps it
fixed.

1. `tools/ioregs.py` emits `sw/io.act` beside `sw/io.asm` / `sw/io.bas`.
2. Its checker and its rewriter glob `sw/*.act` as well, so a bare
   `$FFxx` in a `.act` file fails `poe check` the way it does elsewhere.
3. `sw/libaction.act` drops its own equates and uses the generated
   names. Every routine that touched a wrong register is re-read against
   [docs/04-system.md](docs/04-system.md) §4.
4. Add what was promised and missing: `Clg`, `FlipBuffer`, `Line`.
5. `sim/test_action.py` grows a hardware section: `Plot` then read the
   pixel back, `Clg` then check the framebuffer, `SetColor` then check
   `m.palette()`, `WaitVBlank` returns within one frame rather than
   hanging.

**Gate:** `poe check` fails on a bad `.act` address, and the new library
tests pass.

### Phase 2 — `Line()`, exactly

Port `h_line`'s structure, including the horizontal special case and
the downward-swap convention. Test it against BASIC's by drawing the
same fan from both and comparing framebuffers pixel for pixel — the
same shape of gate `sim/test_run.py` already uses for `LINE`.

**Gate:** identical framebuffers for a fan through all eight octants,
plus the horizontal and vertical degenerate cases.

### Phase 3 — the disc

1. `ACTION_VOL = 11` in `tools/cool8disk.py` beside `DEMO_VOL` and
   friends, with a volume label.
2. `tools/mkdemos.py` learns to compile `demos/*.act` with `coolaction`
   and add each `.BIN` to that volume.
3. `catalogue()` grows the `kind` field and stops filtering `.BIN` out;
   its docstring records why the rule changed.
4. Write Bad Apple's cap into the tree, per 1.2: the drive list becomes
   a parameter defaulting to drive 12, `docs/14-demos.md` describes what
   ships rather than what was once built, and `tools/mkdemos.py` asserts
   that no chunk lands on a drive another volume claims.

**Gate:** a disc build places both `.BIN` files and `sim/test_action.py`
finds them in the catalogue.

### Phase 4 — the three menus

`web/index.html` gets three selects where there is one: **Demos**,
**Software**, **CoolAction**.

**A menu is a drive, and that is the whole rule.** The emulator groups
`discs.json` by the volume an entry came from and labels the group from
a table in `tools/cool8disk.py`. Nothing hardcodes a program list, which
is the principle `catalogue()`'s docstring already sets — the emulator
is never taught the disc format. It launches by `kind`: `LOAD`+`RUN`
for `bas`, `SYS "NAME.BIN"` for `bin`.

For that to hold, the discs have to match the menus, and today they do
not — the Infocom and Pascal loader stubs sit on drive 13 with the
demos. Phase 3 moves them:

| drive | menu | holds |
|---|---|---|
| 13 `DEMOS` | **Demos** | every BASIC program: the graphics and sound demos, plus TAIPAN and both COOLTRIS |
| 14 `SOFTWARE` | **Software** | the machine-code systems' loaders and binaries: HHGG, ZORK1, PLANET, LGOP, PASCAL |
| 11 `ACTION` | **CoolAction** | the compiled `.BIN` demos |

Drive 14's label becomes `SOFTWARE` rather than `ADVENTUR`, since UCSD
Pascal is not an adventure.

**Gate:** `poe web-build` produces a `discs.json` whose entries carry a
drive that maps to exactly one of three menus, and the page starts a
program from each — including a `.BIN`, which is the launch path that
does not exist yet.

### Phase 5 — RAINBOW

Exact port. Gate: run both, compare the framebuffer after a fixed
number of frames. They should be identical; if they are not, the
difference is `Line`'s tie-breaking and phase 2 was wrong.

### Phase 6 — COBRA

Exact port, with a small generator that turns the `DATA` statements
into CoolAction initialisers so the tables are transcribed by machine
rather than by hand. Gate: same framebuffer comparison, plus a clock
count beside the BASIC original — this is the first real answer to
"how much faster is compiled code than the interpreter" on something
that is not a benchmark.

---

## 4. What this does not include

- **New demos.** The ask was ports first. Once COBRA works, the
  language will have been exercised enough to say what a new one should
  be.
- **Sound.** Neither port uses it, and `libaction.act`'s sound
  wrappers are as unverified as everything else in 1.1.
- **The compiler's register allocation.** D97 records that loop
  variables living in memory is the next optimisation and that the sieve
  profile is the evidence. COBRA will produce a second, better piece of
  evidence. Doing it before the ports would be optimising on one data
  point.

---

## 5. Risks

| | |
|---|---|
| The library rewrite is larger than it looks | 1.1 means every routine touching video is unverified, not just the seventeen equates — a routine can name the right register and still write the wrong bits. Phase 1 re-reads each against [04-system.md](docs/04-system.md) §4 and may find more than an address to change. It is the one phase whose size is genuinely unknown, and it is also the one that cannot be skipped. |
| `Line` may not match exactly | The tie-breaking comment says the contract is a test, not a specification. If the fan does not match, phase 2 grows a careful read of `h_line`'s error term. |
| COBRA's data transcription | ~2,300 numbers. Done by generator, not by hand, or it will be wrong in one place and the picture will be subtly bent. |
| A full Bad Apple rebuild | The cap lives in a gitignored directory and the tree still says twelve drives, so a rebuild from the mp4 walks over drives 1–11 without complaint. Phase 3 puts the cap in code and adds the assertion. |

---

## 6. Questions — all answered

1. **Is "the lines thing" `RAINBOW`?** **Yes.** It is the first port.
2. **Which drive, and what happens to Bad Apple?** **Drive 11.** Bad
   Apple was already cut to drive 12; the full twelve-drive build is
   kept beside it, unused. See 1.2.
3. **How do the existing programs split across the menus?** **By
   language, not by genre.** Everything written in BASIC is a Demo,
   games included; Software is strictly the machine-code systems.
4. **What are the menus called?** **Demos**, **Software**,
   **CoolAction**.
5. **Does a CoolAction demo get a `.BAS` stub?** **No — bare `.BIN`.**
   One file per demo, started from the menu or by `SYS "NAME.BIN"`. This
   is what forces the `kind` field in 1.3: the launcher has to know
   which of two things to type.

### The menu split

| menu | drive | programs |
|---|---|---|
| **Demos** | 13 | MAZE, RAINBOW, WAVE, PLASMA, INTRO, BOING, TRIANGLES, MANDEL, COBRA, SYNTH, BENCH, MINIBNCH, BAPPLE, TAIPAN, COOLTRIS 1, COOLTRIS 2 |
| **Software** | 14 | HHGG, ZORK1, PLANET, LGOP, PASCAL |
| **CoolAction** | 11 | RAINBOW, COBRA *(the ports)* |

The line is the language: if it is BASIC it is a Demo, and TAIPAN and
the two COOLTRIS being games does not move them. Software is what the
machine runs natively — the Z-Machine and the p-System — reached
through a small BASIC stub that `SYS`es into the interpreter.

**Note the collision that follows.** RAINBOW and COBRA will exist twice
under the same name, once in BASIC on drive 13 and once compiled on
drive 11. That is the point — the two menus are how you compare them —
but the disc build must not let the names clash on one volume, and the
menu label is what tells them apart on screen.
