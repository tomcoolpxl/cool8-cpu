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


def line(m, syms, text):
    """One line of BASIC into the running editor, in **one** round trip.

    `key()` is what a person does and stays the thing to test with; this
    is what a *builder* wants. Typing costs a round trip a character --
    the PS/2 queue is sixteen deep and a key is two scancodes, so a line
    cannot be delivered in one go and `key` settles after every one.
    Five demos onto a disc was ninety seconds, nearly all of it waiting.

    **The machine still tokenises it.** The text goes where `ed_read`
    would have left it and the machine enters `ed_inject`, which is
    `ed_enter` minus the screen scrape, so `sw/token.asm` remains the
    only thing that turns BASIC into tokens -- the design
    [14-demos.md](../docs/14-demos.md) section 2 exists to protect.

    Every address is derived from the symbol table: LBUF, LLEN and the
    entry point. **Nothing is written into RAM to make the call** -- the
    return address is pushed, so the machine comes back to the PC it was
    already sitting on. An earlier version poked `CALL / HALT` into four
    bytes of low RAM, which needed a byte nothing else owned, and
    `sw/lowram.asm` says in its own header that its map "has been
    wrong". The fourth argument is the vestige of that and is ignored.
    """
    r = m.inject(syms["lbuf"], syms["llen"], syms["ed_inject"], 0, text)
    if r != "done":
        raise SystemExit("inject refused %r: %s" % (text[:40], r))


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
    # **The relaxation count belongs to the assembler's own command, not
    # to every build.** A grown branch is three bytes nobody wrote and
    # this project measures itself to the byte, which is why it is
    # reported at all -- but it was reported *here*, on the library path,
    # so every suite, every demo build and every emulator launch opened
    # with "44 branches relaxed in main.asm" whether or not anything in
    # the run was about size. The note above this said "nothing relaxes
    # today, so this stays quiet until something does": forty-four do,
    # and it has been shouting ever since.
    #
    # `python tools/cool8asm.py <file>` still prints it, which is the
    # place someone is asking about an image rather than using one, and
    # `--pressure` is the fuller question.
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
# ------------------------------------------------------------- CoolAction!

ACT_EXE = os.path.join(ROOT, "rust", "target", "release",
                       "coolaction.exe" if os.name == "nt" else "coolaction")
_ACT_BUILT = [False]

# **The library is two files, in this order, and this is the one place
# that says so.** There is no INCLUDE (15-action.md 2.7): the register
# names come from sw/io.act, generated by tools/ioregs.py out of the
# Verilog that decodes them, and sw/libaction.act uses those names and
# declares none of its own. A caller that lists the library without
# io.act gets "undefined variable 'VID_MODE'" and nothing worse; one
# that lists them the other way round gets the same. `H.build_act(
# H.ACT_LIB + ["game.act"], ...)` is the shape.
ACT_LIB = ["sw/io.act", "sw/libaction.act"]


def act_sources(path):
    """The files that compile a CoolAction! program: the library, then
    the parts its `.parts` manifest names, then itself -- or None when
    a part is missing.

    A manifest is one path a line, relative to ROOT, for a program
    whose data is generated elsewhere: Ms. Cool-Man's art, which
    tools/mkmscool.py writes from the arcade sheets. A tree without the
    part gets None here and says so rather than a compile error.
    """
    rel = path if not os.path.isabs(path) else os.path.relpath(path, ROOT)
    parts = []
    manifest = os.path.join(ROOT, os.path.splitext(rel)[0] + ".parts")
    if os.path.exists(manifest):
        for line in open(manifest, encoding="utf-8"):
            line = line.split("#")[0].strip()
            if not line:
                continue
            if not os.path.exists(os.path.join(ROOT, line)):
                return None
            parts.append(line)
    return ACT_LIB + parts + [rel]


def _act_exe():
    """The compiler binary, built once per process. `cargo build` on an
    up-to-date tree is a tenth of a second, and running it every time
    is what keeps a suite from testing a stale compiler -- the trap
    flash.py's BOOT.BIN comment names, in a different coat."""
    import shutil
    import subprocess
    if not _ACT_BUILT[0]:
        # cargo is on PowerShell's PATH and not always on a Git Bash
        # one; %USERPROFILE%/.cargo/bin is where AGENTS.md says it
        # lives, and a stale binary used in silence is the trap this
        # function exists to avoid -- it cost a round of D101.
        cargo = shutil.which("cargo") or next(
            (c for c in [os.path.join(os.environ.get("USERPROFILE", ""), ".cargo", "bin", "cargo.exe"),
                         os.path.expanduser("~/.cargo/bin/cargo")] if os.path.exists(c)), None)
        if not cargo:
            if not os.path.exists(ACT_EXE):
                raise SystemExit("coolaction needs cargo; none on PATH")
            sys.stderr.write("harness: cargo not found, using the coolaction binary as it is\n")
        else:
            r = subprocess.run([cargo, "build", "--release", "--bin",
                                "coolaction", "--quiet"],
                               cwd=os.path.join(ROOT, "rust"),
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit("cargo build coolaction failed:\n" + r.stderr)
        _ACT_BUILT[0] = True
    return ACT_EXE


def try_build_act(source, name, org=0x0200):
    """Compile CoolAction!: `(prg, syms)` or `(None, error_text)`.

    `source` is a path (absolute, or relative to ROOT), a list of
    paths compiled as one text in that order (the library first), or
    the program text. The generated assembly is left at `BUILD/<name>.asm`, which
    is what makes a code-generation fault readable and what lets a
    suite assemble the same text with tools/cool8asm.py and compare.
    `prg` carries its two-byte load address (D87); `syms` is the label
    table -- a global `foo` is `v_foo`, a routine is its own name.
    """
    import subprocess

    def path_of(s):
        # a path, or program text written to BUILD -- so a list can be
        # `H.ACT_LIB + [text]`, the library in front of a test program
        if "\n" not in s and (s.endswith(".act") or os.path.exists(s)):
            return s if os.path.isabs(s) else os.path.join(ROOT, s)
        p = os.path.join(BUILD, name + ".act")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(s)
        return p

    if isinstance(source, (list, tuple)):
        paths = [path_of(s) for s in source]
    else:
        paths = [path_of(source)]
    stem = os.path.join(BUILD, name)
    r = subprocess.run([_act_exe()] + paths + ["-o", stem + ".bin",
                        "--asm", stem + ".asm", "--sym", stem + ".sym",
                        "--org", "$%04X" % org],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout).strip()
    with open(stem + ".bin", "rb") as fh:
        prg = fh.read()
    syms = {}
    with open(stem + ".sym", encoding="utf-8") as fh:
        for line in fh:
            addr, _, sym = line.strip().partition(" ")
            if sym:
                syms[sym] = int(addr, 16)
    return prg, syms


def build_act(source, name, org=0x0200):
    """`try_build_act`, exiting on a compile error."""
    prg, syms = try_build_act(source, name, org)
    if prg is None:
        raise SystemExit("CoolAction! compile failed: %s\n%s" % (name, syms))
    return prg, syms


def assemble_act(text, name):
    """The compiler's own assembler on assembly text: `(org, image)`,
    or `(None, error_text)`. For holding it to `assemble()` -- the
    same text through tools/cool8asm.py -- byte for byte."""
    import subprocess
    path = os.path.join(BUILD, name + ".asm")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    out = os.path.join(BUILD, name + ".rs.bin")
    r = subprocess.run([_act_exe(), "--assemble", path, "-o", out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout).strip()
    org = int(r.stdout.split("at $")[1].split(",")[0], 16)
    with open(out, "rb") as fh:
        return org, fh.read()


def load_act(m, prg, at=0xFEF0, sp=0x0200):
    """Load a PRG where its header says, ready to run: `(org, end)`.

    The program's `_start` is `CALL Main / RET`, so four bytes of
    `CALL org / HALT` at `at` -- high in RAM, where no program this
    size reaches -- are the caller it returns to. For the caller that
    wants to drive or profile the run itself; `run_act` is the whole
    thing.
    """
    org = prg[0] | (prg[1] << 8)
    code = prg[2:]
    m.bus.mem[org:org + len(code)] = code
    m.bus.mem[at:at + 4] = bytes([0x29, org & 0xFF, org >> 8, 0x21])
    m.cpu.pc, m.cpu.sp, m.romen = at, sp, False
    return org, org + len(code)


def run_act(m, prg, at=0xFEF0, sp=0x0200, budget=50_000_000):
    """Load a PRG where its header says and run it to completion.

    Returns why the machine stopped; "halt" is the answer a finished
    program gives, and afterwards `m.cpu.sp` back at `sp` is the
    stack-neutrality check every frame and every call has to pass.
    """
    load_act(m, prg, at, sp)
    return m.run(budget=budget)


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