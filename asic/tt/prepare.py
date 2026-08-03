#!/usr/bin/env python3
"""Fill a TinyTapeout submission checkout with this project's sources.

TinyTapeout's CI config, cocotb harness and Wokwi glue change from
shuttle to shuttle, so this does not carry a copy of them. Instead:

    gh repo create cool8-tt --private \\
        --template TinyTapeout/ttsky-verilog-template --clone
    python asic/tt/prepare.py ../cool8-tt

which copies rtl/core and rtl/pads into the checkout's src/, drops in
info.yaml and docs/info.md, and rewrites PROJECT_SOURCES in test/Makefile
to match. Push, and the tt-gds-action workflow runs LibreLane and
publishes the GDS, the cell count, the utilisation and the timing report
as build artefacts.

Run it again after any RTL change; --check reports drift without
writing, which is what CI should use.
"""

import argparse
import filecmp
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SOURCES = [
    os.path.join(ROOT, "rtl", "core", "cool8_alu.v"),
    os.path.join(ROOT, "rtl", "core", "cool8_agu.v"),
    os.path.join(ROOT, "rtl", "core", "cool8_core.v"),
    os.path.join(ROOT, "rtl", "pads", "tt_um_cool8.v"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dest", help="a checkout made from the TT template")
    ap.add_argument("--check", action="store_true",
                    help="report drift, write nothing")
    args = ap.parse_args()

    dest = os.path.abspath(args.dest)
    src_dir = os.path.join(dest, "src")
    if not os.path.isdir(src_dir):
        sys.exit(f"{dest} does not look like a TT template checkout "
                 f"(no src/). Create it with:\n"
                 f"  gh repo create cool8-tt --private "
                 f"--template TinyTapeout/ttsky-verilog-template --clone")

    stale = []
    for s in SOURCES:
        d = os.path.join(src_dir, os.path.basename(s))
        if not os.path.exists(d) or not filecmp.cmp(s, d, shallow=False):
            stale.append(os.path.basename(s))
            if not args.check:
                shutil.copy2(s, d)

    # The template ships an example module and a testbench wired to it.
    example = os.path.join(src_dir, "project.v")
    if os.path.exists(example):
        stale.append("src/project.v (removed)")
        if not args.check:
            os.remove(example)

    tb = os.path.join(dest, "test", "tb.v")
    if os.path.exists(tb):
        text = open(tb, encoding="utf-8").read()
        if "tt_um_example" in text:
            stale.append("test/tb.v")
            if not args.check:
                open(tb, "w", encoding="utf-8", newline="\n").write(
                    text.replace("tt_um_example", "tt_um_cool8"))

    for rel, s in (("info.yaml", os.path.join(HERE, "info.yaml")),
                   (os.path.join("docs", "info.md"),
                    os.path.join(HERE, "docs", "info.md")),
                   (os.path.join("test", "test.py"),
                    os.path.join(HERE, "test", "test.py"))):
        d = os.path.join(dest, rel)
        if not os.path.exists(d) or not filecmp.cmp(s, d, shallow=False):
            stale.append(rel)
            if not args.check:
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)

    # The template's Makefile carries its own list of sources, and the
    # docs are explicit that it has to be kept in step with info.yaml.
    mk = os.path.join(dest, "test", "Makefile")
    if os.path.exists(mk):
        want = " ".join("$(PROJECT_SOURCES_DIR)/" + os.path.basename(s)
                        for s in SOURCES)
        text = open(mk, encoding="utf-8").read()
        new = re.sub(r"^PROJECT_SOURCES\s*=.*$", "PROJECT_SOURCES = " + want,
                     text, count=1, flags=re.M)
        if new != text:
            stale.append("test/Makefile")
            if not args.check:
                open(mk, "w", encoding="utf-8", newline="\n").write(new)

    if not stale:
        print("submission is up to date")
        return 0
    if args.check:
        print("out of date: " + ", ".join(stale))
        return 1
    print("updated: " + ", ".join(stale))
    print(f"\nNow, in {dest}:\n  git add -A && git commit && git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
