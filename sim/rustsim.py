#!/usr/bin/env python3
"""The Rust fast runner against the reference emulator.

tools/cool8emu.py is the executable specification; rust/ is a fast,
never-authoritative copy of the CPU (RUST_PORT.md). This holds the copy
to the specification with the exact contract sim/cosim.py holds the RTL
to: the same programs out of sim/progen.py, one line of architectural
state per retired instruction, diffed to the first divergence, whole
64 KB memory image compared.

    python sim/rustsim.py             # drift check, build, full parity
    python sim/rustsim.py --quick     # skip the exhaustive multiply

The trace format, the retired-instruction rules and the
inject-by-retired-count interrupt scheme are all cosim's; the Rust
runner speaks the testbench's plusarg vocabulary so the call sites here
look like cosim's on purpose.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")

sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

import cosim                                # noqa: E402
import progen                               # noqa: E402

EXE = os.path.join(ROOT, "rust", "target", "release",
                   "cool8rs.exe" if os.name == "nt" else "cool8rs")


def build_runner():
    """`cargo build --release`, and the drift gate before it: a stale
    optab.rs must fail here, not misexecute quietly."""
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "mkrsopc.py"),
                        "--check"], capture_output=True, text=True)
    print(f"  {r.stdout.strip()}")
    if r.returncode != 0:
        return False
    if not shutil.which("cargo"):
        print("  cargo not found: install Rust (rustup) to run this suite")
        return False
    r = subprocess.run(["cargo", "build", "--release"],
                       cwd=os.path.join(ROOT, "rust"),
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        return False
    return os.path.exists(EXE)


def rust_run(tag, hexf, extra=(), trace=True):
    """One run of the Rust runner. Returns (trace path, memory bytes)."""
    rst_t = os.path.join(BUILD, f"{tag}.rst")
    rst_m = os.path.join(BUILD, f"{tag}.rstmem")
    args = [EXE, f"+hex={hexf}"] + list(extra)
    if trace:
        args += [f"+trace={rst_t}", f"+memdump={rst_m}"]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("rust runner failed")
    return rst_t, (cosim.read_memdump(rst_m) if trace else None)


def run_pair(tag, mem, max_instr=0, events=None, extra=()):
    os.makedirs(BUILD, exist_ok=True)
    hexf = os.path.join(BUILD, f"{tag}.hex")
    image = progen.write_hex(mem, hexf)

    emu_t = os.path.join(BUILD, f"{tag}.emu")
    n, emu_mem = cosim.emu_trace(image, emu_t, max_instr=max_instr,
                                 events=events)

    args = list(extra)
    if max_instr:
        args.append(f"+maxinstr={max_instr}")
    rst_t, rst_mem = rust_run(tag, hexf, args)

    ok = cosim.compare(tag, emu_t, rst_t, emu_mem, rst_mem, image)
    return ok, n


def test_directed():
    print("directed — one probe per encoding")
    mem, nprobes = progen.directed()
    t0 = time.time()
    ok, n = run_pair("rs_directed", mem)
    print(f"  {nprobes} encodings, {n} instructions : "
          f"{'ok' if ok else 'FAIL'} ({time.time() - t0:.1f}s)")
    return ok


def test_random(seeds, count):
    print(f"random — {len(seeds)} streams of {count} instructions")
    allok = True
    for s in seeds:
        mem = progen.random_prog(s, count=count)
        ok, _ = run_pair(f"rs_random{s}", mem, max_instr=count)
        allok &= ok
        if not ok:
            print(f"  seed {s}: FAIL")
    if allok:
        print(f"  seeds {min(seeds)}..{max(seeds)} : ok")
    return allok


def test_interrupts():
    """The same four programs cosim uses, events and plusargs included —
    the runner takes the testbench's argument vocabulary on purpose."""
    print("interrupts, halt and brk")
    ok = True
    for name, (mem, ev, args) in (
            ("irq wakes HALT   ", cosim._halt_irq_prog()),
            ("irq mid-stream   ", cosim._irq_stream_prog()),
            ("nmi is unmaskable", cosim._nmi_prog()),
            ("brk and the page-2 trap", cosim._brk_prog())):
        tag = "rs_" + name.split()[0] + str(abs(hash(name)) % 97)
        good, n = run_pair(tag, mem, events=ev, extra=args)
        print(f"  {name} : {'ok' if good else 'FAIL'} ({n} instructions)")
        ok &= good
    return ok


def test_mul():
    print("multiply — 65536 exhaustive operand pairs")
    t0 = time.time()
    ok, n = run_pair("rs_mul", cosim._mul_prog())
    print(f"  {n} instructions : {'ok' if ok else 'FAIL'} "
          f"({time.time() - t0:.1f}s)")
    return ok


def speed():
    """The number this runner exists for, measured rather than assumed.

    Both sides run the mul program with no trace being written, so this
    is stepping speed, not file I/O. The emulator side reuses the trace
    machinery's images to keep the comparison honest.
    """
    import cool8emu
    hexf = os.path.join(BUILD, "rs_speed.hex")
    image = progen.write_hex(cosim._mul_prog(), hexf)

    bus = cool8emu.Bus()
    bus.mem[:] = image
    cpu = cool8emu.Cool8(bus)
    t0 = time.time()
    while not cpu.halted:
        cpu.step()
    t_py = time.time() - t0
    n = cpu.instructions

    # The runner reports its own stepping time, so process start-up and
    # the hex parse do not flatter the comparison in either direction.
    r = subprocess.run([EXE, f"+hex={hexf}"], capture_output=True, text=True)
    t_rs = float(r.stdout.strip().split()[-1].rstrip("s"))

    print(f"speed — {n} instructions of the multiply sweep")
    print(f"  python  {t_py:8.4f}s  {n / t_py / 1e6:8.2f} M instr/s")
    print(f"  rust    {t_rs:8.4f}s  {n / t_rs / 1e6:8.2f} M instr/s"
          f"   ({t_py / t_rs:.0f}x)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="skip the exhaustive multiply and the speed run")
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--count", type=int, default=3000)
    args = ap.parse_args()

    os.makedirs(BUILD, exist_ok=True)
    print("build")
    if not build_runner():
        print("\nFAIL")
        return 1

    ok = test_directed()
    ok &= test_random(range(1, args.seeds + 1), args.count)
    ok &= test_interrupts()
    if not args.quick:
        ok &= test_mul()
        speed()

    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
