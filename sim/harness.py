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
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")
SW = os.path.join(ROOT, "sw")

sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

import cool8asm                                          # noqa: E402
import cool8bas as bas                                   # noqa: E402

os.makedirs(BUILD, exist_ok=True)


# ---------------------------------------------------------------- results

FAILS = []


def check(ok, what, detail=""):
    """One check, printed, remembered if it failed. Returns `ok`, so a
    caller can gate the next step on it."""
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return bool(ok)


def report():
    """The trailing verdict, and the exit code to return from main()."""
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


def build_bas(src, org=0xA000, name=None, optimize=True, lower=True):
    """The system image, the way every suite that boots BASIC wants it:
    `sw/<src>` compiled at `org` with symbols folded down."""
    stem = name or os.path.splitext(os.path.basename(src))[0]
    return compile_bas(src, stem, org=org, optimize=optimize, lower=lower,
                       write=True)
