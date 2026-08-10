#!/usr/bin/env python3
"""What is installed, what is missing, and what that stops you doing.

    poe doctor

Every failure this reports has been mistaken for something else at least
once. `which icesprog` in a shell that has not put the OSS CAD Suite on
`PATH` answers "no", and **"not on PATH" is not "not installed"** -- a
whole round went into that. The board's serial port re-enumerates when
the FPGA is reconfigured, so a port that worked five minutes ago may not
exist now. This asks all of it in one place and says which commands each
answer enables.

Nothing here is hardcoded to a machine: the suite is found through
`OSS_CAD_SUITE` or `PATH`, exactly as `sim/cosim.py` finds `iverilog`.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))

OK, BAD, DIM, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[0m"

def _cfg():
    """pyproject.toml's [tool.cool8] -- the one place these are named."""
    import tomllib
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        return tomllib.load(fh).get("tool", {}).get("cool8", {})


# What each tool is for, and what stops working without it. The *list*
# of tools and the name of the environment variable come from
# pyproject.toml, so adding one is a config change and not a code change.
WHAT = {
    "yosys":         ("synthesis",         "poe bit, poe synth"),
    "nextpnr-ice40": ("place and route",   "poe bit"),
    "icepack":       ("bitstream packing", "poe bit"),
    "iverilog":      ("RTL simulation",    "poe test-rtl, poe cosim"),
    "vvp":           ("RTL simulation",    "poe test-rtl"),
    "icesprog":      ("programming flash", "poe flash, poe test-board"),
}
_TC = _cfg().get("toolchain", {})
SUITE_ENV = _TC.get("env", "OSS_CAD_SUITE")
SUITE = [(n,) + WHAT.get(n, ("", "")) for n in _TC.get("tools", [])]

rows = []


def say(ok, what, detail=""):
    mark = f"{OK}ok  {OFF}" if ok else f"{BAD}MISS{OFF}"
    print(f"  {mark}  {what:<34}{DIM}{detail}{OFF}")
    rows.append(ok)
    return ok


def suite_root():
    return os.environ.get(SUITE_ENV)


def find(name):
    """The suite first, then PATH -- cosim's rule, not a second one."""
    root = suite_root()
    if root:
        for cand in (os.path.join(root, "bin", name + ".exe"),
                     os.path.join(root, "bin", name)):
            if os.path.exists(cand):
                return cand
    return shutil.which(name)


def main():
    print("\n  environment\n")
    say(sys.version_info >= (3, 11), "python %d.%d"
        % sys.version_info[:2], sys.executable)
    try:
        import pytest
        say(True, "pytest %s" % pytest.__version__, "the suite runner")
    except ImportError:
        say(False, "pytest", 'pip install -e ".[dev]" -- poe test')
    try:
        v = subprocess.run(["cargo", "--version"], capture_output=True,
                           text=True).stdout.strip()
        say(bool(v), v or "cargo",
            "the fast machine and the emulator window; without it the "
            "suites fall back to the Python reference")
    except Exception:
        say(False, "cargo", "poe emu needs it; poe test slows without it")

    try:
        import serial
        say(True, "pyserial %s" % serial.__version__,
            "poe board, poe console")
    except ImportError:
        say(False, "pyserial", 'pip install -e "." -- poe board')

    root = suite_root()
    print()
    if root:
        say(os.path.isdir(root), "OSS_CAD_SUITE", root)
    else:
        print(f"  {DIM}      OSS_CAD_SUITE is not set; looking on PATH{OFF}")

    print("\n  toolchain\n")
    for name, what, enables in SUITE:
        p = find(name)
        say(bool(p), "%-16s %s" % (name, what),
            p if p else "not found -- blocks: " + enables)

    print("\n  board\n")
    drives, port = [], None
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_LogicalDisk | "
                 "Where-Object { $_.VolumeName -eq 'iCELink' } | "
                 "Select-Object -ExpandProperty DeviceID"],
                capture_output=True, text=True, timeout=20).stdout.split()
            drives = out
        except Exception:
            pass
    say(bool(drives), "iCELink drive",
        drives[0] if drives else "not mounted -- the board may be unplugged")

    try:
        import board as _board
        from serial.tools import list_ports
        ports = list(list_ports.comports())
        for p in ports:
            if (p.vid, p.pid) == _board.ICELINK_USB:
                port = p.device
        say(bool(port), "board serial port",
            "%s (%04X:%04X)" % (port, *_board.ICELINK_USB) if port
            else "none with the iCELink USB ID. saw: %s"
            % (", ".join(p.device for p in ports) or "nothing"))
    except ImportError:
        say(False, "board serial port", "pyserial not installed")

    bad = rows.count(False)
    print()
    if bad:
        print(f"  {BAD}{bad} missing{OFF} -- see what each one blocks above")
    else:
        print(f"  {OK}everything present{OFF}")
    print()

    # Missing hardware is not a broken checkout. Only a missing *tool*
    # is worth a non-zero exit, or this cannot be used in a script that
    # runs where no board is plugged in.
    tools_missing = any(not find(n) for n, _, _ in SUITE)
    return 1 if tools_missing else 0


if __name__ == "__main__":
    sys.exit(main())
