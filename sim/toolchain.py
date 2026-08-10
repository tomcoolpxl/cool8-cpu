"""The OSS CAD Suite, found and driven — the layer every RTL suite sits on.

This lived inside `sim/cosim.py`, and ten other suites reached into it
by its private names (`cosim._tool`, `cosim._build`). That worked, and
it meant a keyboard test could not run without importing the CPU
co-simulation gate. When ten modules use your underscore names, the
layer wants to be a module.

    import toolchain as T

    vvp = T.build("cool8_ps2_tb", TB, T.CORE + [T.cells()])
    out = T.run(vvp, ["+quiet"])

`OSS_CAD_SUITE` points at the suite root, or its `bin` is on `PATH`.
Neither is written into the source: it differs per machine, and
`poe doctor` says which tools were found and where.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")

RTL = os.path.join(ROOT, "rtl")
TB = os.path.join(HERE, "tb")

# The three files that are the CPU, named once. Four suites carried
# identical copies of this list.
CORE = [os.path.join(RTL, "core", f)
        for f in ("cool8_alu.v", "cool8_agu.v", "cool8_core.v")]


def core(*extra):
    """The CPU, plus whatever else a testbench needs."""
    return CORE + list(extra)


def soc(*names):
    """`rtl/soc/` files, by bare name."""
    return [os.path.join(RTL, "soc", n) for n in names]


def pads(*names):
    return [os.path.join(RTL, "pads", n) for n in names]


def tb(name):
    """A testbench in `sim/tb/`, by bare name."""
    return os.path.join(TB, name)


# ------------------------------------------------------------ the binaries

def _with_libs(root, path):
    """Put the toolchain's own directories on PATH before running it.

    Every suite says "set OSS_CAD_SUITE if it is not on PATH", and that
    was not quite true: an absolute path finds the executable, but `vvp`
    then loads `libvvp-1.dll` beside itself and Windows resolves that
    against PATH. Setting the variable alone gave a process that died
    with 0xC0000135 and no output at all, which reads like a simulator
    that produced nothing rather than one that never started.
    """
    for d in (os.path.join(root, "bin"), os.path.join(root, "lib")):
        if os.path.isdir(d) and d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    return path


def tool(name):
    """An executable from the suite, or from PATH, or a clear exit."""
    root = os.environ.get("OSS_CAD_SUITE")
    if root:
        for cand in (os.path.join(root, "bin", name + ".exe"),
                     os.path.join(root, "bin", name)):
            if os.path.exists(cand):
                return _with_libs(root, cand)
    found = shutil.which(name)
    if not found:
        sys.exit(f"{name} not found. Put the OSS CAD Suite on PATH or set "
                 f"OSS_CAD_SUITE to its root directory.")
    return found


def cells():
    """The toolchain's own SB_* simulation models.

    Not vendored into the repository: the models must match the yosys
    that maps the design, and a stale copy of a memory primitive is a
    bug that looks like an RTL bug.
    """
    roots = []
    if os.environ.get("OSS_CAD_SUITE"):
        roots.append(os.environ["OSS_CAD_SUITE"])
    roots.append(os.path.dirname(os.path.dirname(tool("yosys"))))
    for r in roots:
        cand = os.path.join(r, "share", "yosys", "ice40", "cells_sim.v")
        if os.path.exists(cand):
            return cand
    sys.exit("ice40 cells_sim.v not found; set OSS_CAD_SUITE to the "
             "toolchain root")


# ------------------------------------------------------ build and run a sim

def build(name, testbench, sources, gen="2005"):
    """Compile a testbench to a `.vvp`, skipping the work if it is newer
    than every source that goes into it.

    `gen="2012"` only where a testbench instantiates an `SB_` primitive:
    yosys's `cells_sim.v` uses default port values, which Verilog-2001
    does not have. Everything in `rtl/` stays Verilog-2001 and is
    compiled as such (AGENTS.md, "the structural rule").
    """
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, name + ".vvp")
    newest = max(os.path.getmtime(f) for f in list(sources) + [testbench])
    if os.path.exists(out) and os.path.getmtime(out) > newest:
        return out
    subprocess.run([tool("iverilog"), "-g" + gen, "-Wall", "-Wno-timescale",
                    "-o", out, testbench] + list(sources), check=True)
    return out


def run(vvp_file, args=(), cwd=None):
    """Run a compiled testbench. Its stdout is the result."""
    r = subprocess.run([tool("vvp"), vvp_file] + list(args),
                       capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("simulator failed")
    return r.stdout
