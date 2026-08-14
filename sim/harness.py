"""What every software suite needs, written once.

Before this, each suite carried its own copy of three things: the
`check`/`FAILS` reporter (thirteen byte-identical copies), the paths
preamble (twenty-six), and the compile-assemble-read-symbols pipeline
(six, each spawning `cool8asm.py` as a subprocess even though the
assembler is an importable module). None of it was ever wrong, which
is exactly why it spread: nobody had a reason to look at it.

    import harness as H

    code, syms = H.build_bas("basic.bas", org=0xA000, optimize=True)
    H.check(m.shows("42"), "RUN prints its answer")
    return H.report()

**The assembler is imported, not spawned.** `cool8asm.assemble()`
returns the image and the symbol table directly — the same bytes and
the same `{name: addr}` the `--symbols` file holds, since that file is
written from this dict. A subprocess per assembly cost an interpreter
start and a file round trip to arrive at the same answer.

`ROOT` and `BUILD` come from here too. `BUILD` honours `COOL8_BUILD`,
which the job runner sets per job so parallel suites cannot write each
other's `basic.bin` (docs/12-tasks.md).

## The VM is the default. The RTL is the exception.

`H.machine()` and `H.session()` hand back the Rust machine, and that is
what a software test runs on unless it has a stated reason not to. It
steps at roughly **66 million instructions a second**; the Icarus
simulation of `rtl/` manages a few thousand. That is not a preference
between two similar things, it is the difference between a suite that
runs in seconds and one nobody waits for.

**Reach for the RTL only when the hardware itself is the question** —
`sim/cosim.py` checking the two models agree instruction by
instruction, `sim/test_vm.py` checking them pixel by pixel, a
testbench for a peripheral. Those go through `sim/toolchain.py` and
live in the `rtl` job group, not the `sw` one. Anything asking what
*software* does has no business there: the two models are gated
against each other precisely so that a software test can trust the
fast one.

There is no third machine. The Python emulator this grew from is
retired ([D57](../docs/01-decisions.md)), and without `cargo` there is
no machine at all — the suites say so rather than quietly running
something else.
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")
SW = os.path.join(ROOT, "sw")

sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

import cool8asm                                          # noqa: E402
import cool8bas as bas                                   # noqa: E402
import cool8rsvm as _vm                                  # noqa: E402
import memmap                                            # noqa: E402

os.makedirs(BUILD, exist_ok=True)


# ---------------------------------------------------------------- results

FAILS = []

# Wall time charged to each check: the gap since the previous one, which
# is the work that produced it. pytest's --durations answers this for
# whole jobs and a job is minutes; this answers it for the case inside
# the job, which is where a suite actually goes slow. Reported by
# report() whenever a run is slow enough for the question to matter.
_TIMES = []
_last = [time.time()]


def machine():
    """The batch VM: a CPU and RAM, no peripherals. **The default.**

    What a test wants when it has code and a question about what the
    code does. `run(until=…, cycles=…)`, `bus.mem`, the registers, and
    `trace` for what it executed.

    Peripheral state does not survive between runs, because each is a
    fresh machine around the carried CPU and memory. A test that needs
    the screen, the keyboard or flash wants `session()`.
    """
    _require()
    return _vm.machine()


def session(render=False):
    """The session VM: one persistent machine with peripherals.

    For anything involving the screen, the keyboard, the UART or flash
    — `type`, `key`, `row`, `shows`, `settle`, `run_frame`, and `fb()`
    with `render=True`.
    """
    _require()
    return _vm.Machine(render=render) if render else _vm.Machine()


def settle(m, syms, budget=40_000_000):
    """Wait for the editor to go idle -- the machine's own idle test.

    Both FIFOs empty, the input ring drained, and the CPU sitting at
    `in_raw`'s "nothing waiting" branch. That is one question with one
    answer, so it lives here rather than in each caller.
    """
    return m.settle(syms["in_raw.rk0"], syms["irhead"], syms["irtail"],
                    budget)


def key(m, syms, text, budget=40_000_000):
    """Type `text` at the **keyboard**, a character at a time, waiting
    for the editor after each.

    `m.type()` is the serial console and `m.key()` is the keyboard --
    different drivers and a different interrupt -- so a script that only
    ever types at the cable proves nothing about the machine a person
    holds.

    **This had two copies before the demo builder wanted a third**, in
    `sim/test_boot_basic.py` and in `tools/mkdemos.py`, which is the trap
    at the top of AGENTS.md arriving in the tooling that exists to avoid
    it. Raises rather than returning a flag: a dropped character is a
    typo the caller cannot recover from.
    """
    for ch in text:
        m.key([ch])
        if not settle(m, syms, budget):
            raise SystemExit("the machine never went idle after %r" % ch)


_FONT = None


def font():
    """The machine's font, as the renderer needs it.

    **`render=True` without this draws nothing at all** -- a frame of
    one colour, in every mode, including the ones that plainly work on a
    real screen. That is not a subtle failure: it makes a pixel check
    look like it cannot tell modes apart, which is exactly how a "the
    text is in the cell map" proxy ends up standing in for "the text is
    visible", and a black-on-black screen passes.

    sim/test_vm.py had the one copy of this. It is here now because any
    suite asking what is on the screen needs it.
    """
    global _FONT
    if _FONT is None:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import mkfont
        _FONT = mkfont.build(os.path.join(ROOT, "assets", "font",
                                          "spleen-8x16.bdf"))[0]
    return _FONT


def _require():
    if not _vm.available():
        raise SystemExit(
            "no machine: rust/ is not built and cargo was not found. "
            "The suites do not fall back -- there is nothing to fall "
            "back to (docs/01-decisions.md D57).")


def check(ok, what, detail=""):
    """One check, printed, remembered if it failed. Returns `ok`, so a
    caller can gate the next step on it."""
    now = time.time()
    _TIMES.append((now - _last[0], what))
    _last[0] = now
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return bool(ok)


def report(slow=3.0, top=6):
    """The trailing verdict, and the exit code to return from main().

    A run that took real time names where it went, so the next person
    asking "why is this suite slow" has the answer in the output they
    already have rather than in a profiling session.
    """
    total = sum(t for t, _ in _TIMES)
    if total >= slow:
        worst = sorted(_TIMES, reverse=True)[:top]
        print(f"\n  {total:.1f}s total; slowest checks:")
        for t, what in worst:
            if t >= 0.05:
                print(f"    {t:6.1f}s  {what}")
    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


# ------------------------------------------------------------- building

def _syms(a, lower):
    return {(k.lower() if lower else k): v for k, v in a.syms.items()}


def assemble(path, name=None, lower=False, incdirs=(SW,), write=False):
    """Assemble a file. Returns `(code, syms)`.

    `lower` folds symbol names to lower case — some suites look up
    `s_rawkey.rk0` and the source writes it that way, others index
    `CONST`-style names that are upper case in the source, so this has
    to stay the caller's choice. `write` also leaves `<name>.bin` and
    `<name>.sym` in BUILD, for the suites that hand those to another
    program.
    """
    a = cool8asm.assemble(path, incdirs=list(incdirs))
    if a.errors:
        for e in a.errors:
            print(f"error: {e}", file=sys.stderr)
        raise SystemExit("assembly failed: " + os.path.basename(path))
    # **A grown branch is three bytes nobody wrote**, and this project
    # measures itself to the byte. Silence here would let relaxation
    # quietly inflate every size figure the docs quote. Nothing relaxes
    # today, so this stays quiet until something does.
    if a.relaxed:
        print("  %d branch%s relaxed in %s" %
              (a.relaxed, "" if a.relaxed == 1 else "es",
               os.path.basename(path)), file=sys.stderr)
    _, img = a.image()
    code = bytes(img)
    if write:
        stem = os.path.join(BUILD, name or
                            os.path.splitext(os.path.basename(path))[0])
        with open(stem + ".bin", "wb") as fh:
            fh.write(code)
        with open(stem + ".sym", "w", encoding="utf-8") as fh:
            fh.write(a.symbols() + "\n")
    return code, _syms(a, lower)


def try_assemble(path, incdirs=(SW,)):
    """Assemble, but hand back the complaint instead of exiting:
    `(code, syms)` or `(None, error_text)`.

    For the suites that feed the assembler input it *should* reject —
    `sim/test_asm.py` checks that the machine's assembler refuses the
    same things this one does, so a refusal is a result, not a crash.
    """
    try:
        a = cool8asm.assemble(path, incdirs=list(incdirs))
    except Exception as e:                                # noqa: BLE001
        return None, str(e)
    if a.errors:
        return None, "\n".join(str(e) for e in a.errors)
    _, img = a.image()
    return bytes(img), dict(a.syms)


def assemble_text(text, name, lower=False, incdirs=(SW,), write=False):
    """The same, for assembly generated in the test rather than on disk.
    The `.asm` is written to BUILD so a failure can be read."""
    path = os.path.join(BUILD, name + ".asm")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return assemble(path, name=name, lower=lower, incdirs=incdirs,
                    write=write)


def compile_bas(source, name, org=None, optimize=False, lower=False,
                incdirs=(SW,), write=False):
    """Compile COOL8 BASIC and assemble the result: `(code, syms)`.

    `source` is a path or the program text. The generated assembly is
    kept at `BUILD/<name>.asm`, which is what makes a code-generation
    failure readable — and what `dbg.Image` reads back for `.res`
    sizes.
    """
    if os.path.exists(source) or source.endswith(".bas"):
        path = source if os.path.isabs(source) else os.path.join(SW, source)
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
    asm = bas.compile_source(source, org, optimize=optimize)
    return assemble_text(asm, name, lower=lower, incdirs=incdirs,
                         write=write)
def call(m, syms, routine, regs=(), at=0x0200, budget=20_000_000):
    """Call one routine in the loaded system image and come back.

        m = H.session()
        H.load(m, code)
        H.call(m, syms, "tok_line")

    **A trampoline, not a driver.** Every module suite used to assemble
    its own program in front of the module it was testing, with its own
    include list and its own stubs for whatever that dragged in -- and
    since `sw/interp.asm` names every command handler, "whatever that
    dragged in" was the entire system. Four suites ended up splitting one
    stub block apart on a comment line to take the half they wanted,
    which is the private-copy trap AGENTS.md names, arrived at from a
    direction nobody planned.

    There is one image ([D68]), so a suite loads it and pokes four bytes
    of `CALL routine / HALT` somewhere harmless. No driver, no stubs, no
    second idea of what the machine is -- and the routine under test is
    the one that ships, not a copy of it assembled differently.

    `regs` is (R0, R1, R2, R3), each None to leave alone.
    """
    addr = syms[routine.lower()]
    m.bus.mem[at] = 0x29                        # CALL abs16
    m.bus.mem[at + 1] = addr & 0xFF
    m.bus.mem[at + 2] = addr >> 8
    m.bus.mem[at + 3] = 0x21                    # HALT
    for i, v in enumerate(regs):
        if v is not None:
            setattr(m.cpu, "r%d" % i, v)
    m.cpu.pc = at
    why = m.run(budget=budget)
    if why != "halt":
        raise SystemExit("%s did not return: %s, pc $%04X"
                         % (routine, why, m.cpu.pc))
    return m


def load(m, code, org=None, sp=0x0200):
    """The system image into a machine, ready to be called into."""
    org = memmap.ORG if org is None else org
    m.bus.mem[org:org + len(code)] = code
    m.cpu.sp = sp
    m.romen = False
    return m


def build_system(name="basic"):
    """The system image: `sw/main.asm` and everything it includes.

    **This is what `build_bas("basic.bas")` used to be.** The editor was
    compiled BASIC and the interpreter was assembly, so a suite that
    wanted one without the other assembled it against a private block of
    stubs — and by the end four suites were splitting that block apart
    with string surgery to take the half they wanted, which is the
    private-copy trap this module exists to stop ([D68]).

    There is one image now. A suite that wants to drive `irun` on a
    hand-built program loads this and pokes the program in; nothing has
    to model the half it is not testing, because there is no half.
    """
    return assemble(os.path.join(SW, "main.asm"), name=name,
                    lower=True, write=True)


_IMAGE = None


def fresh(sp=0x0200, mk=None):
    """A machine with the system in it, ready to be called into.

        m, syms = H.fresh()
        H.call(m, syms, "tok_line")

    **The one line every module suite starts with.** The image is
    assembled once per process and copied into each new machine, so a
    suite of twenty cases costs one build rather than twenty.

    The stack sits at $0200 by default, which is also where `H.call`
    puts its trampoline -- they grow apart, the trampoline upward from
    $0200 and the stack downward from it, and four bytes of code have
    never met a stack that deep.

    `mk` swaps the machine for one a case needs a different view of --
    `vm.Machine()` rather than a session, for the stack high-water mark,
    which has to be read server-side because it cannot cross the session
    pipe a tick at a time.
    """
    global _IMAGE
    if _IMAGE is None:
        _IMAGE = build_system()
    code, syms = _IMAGE
    return load((mk or session)(), code, sp=sp), syms


_EQU = None


def drive(body, at=0x0200, sp=0x0200, run=False, budget=20_000_000, mk=None):
    """A snippet of assembly, assembled against the real image.

        m, syms = H.drive('''
                CALL ed_start
                CALL ed_enter
        ''', run=True)

    **The linker this project does not have, in six lines.** `H.call`
    covers a suite that wants one routine; a suite that wants a sequence
    -- set this up, call that, check what moved -- needs to write code,
    and writing code meant assembling the module again with stand-ins
    for everything above it.

    So the image's symbols go in front of the snippet as equates and the
    snippet is assembled alone. It calls the shipped routines at the
    addresses they actually occupy. Nothing is stubbed, because nothing
    is rebuilt.

    Local labels are dropped: `.l` inside a routine is not a name the
    caller may use, and an equate for it would not assemble anyway.
    """
    global _EQU
    m, syms = fresh(sp=sp, mk=mk)
    if _EQU is None:
        # Both cases. The image's table is folded down (`lower=True`) and
        # the assembler is not case-insensitive, so `TLEN` and `tok_line`
        # are two different names to it and a snippet may reasonably
        # write either -- the source it is copied from writes storage in
        # capitals and routines in lower.
        _EQU = "".join("%s = $%04X\n%s = $%04X\n" % (n, a, n.upper(), a)
                       for n, a in sorted(syms.items())
                       if n.replace("_", "").isalnum() and not n[0].isdigit())
    code, _ = assemble_text(
        _EQU + "\n        .org $%04X\n" % at + body + "\n        HALT\n",
        "drive", lower=True)
    m.bus.mem[at:at + len(code)] = code
    m.cpu.pc = at
    if run:
        why = m.run(budget=budget)
        if why != "halt":
            raise SystemExit("snippet did not halt: %s, pc $%04X"
                             % (why, m.cpu.pc))
    return m, syms


def build_bas(src, org=0xA000, name=None, optimize=True, lower=True):
    """The system image, the way every suite that boots BASIC wants it:
    `sw/<src>` compiled at `org` with symbols folded down."""
    stem = name or os.path.splitext(os.path.basename(src))[0]
    return compile_bas(src, stem, org=org, optimize=optimize, lower=lower,
                       write=True)