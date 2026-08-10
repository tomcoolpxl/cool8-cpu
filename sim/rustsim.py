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


# ---------------------------------------------------------------------
# Machine level: the whole machine of rust/src/machine.rs against
# cool8vm.Machine, over a real boot.
#
# The same contract again, one level up. A stimulus script — UART bytes,
# PS/2 scancodes, frames to run — is executed identically on both sides:
# the Rust runner reads the file, and this driver applies the same ops
# to the Python machine through its own API (m.type / m.scancode /
# m.tick — never a bare cpu.step loop). The Rust trace streams over
# stdout and is compared in lockstep, one line per retired instruction,
# so a divergence stops the run early and no quarter-gigabyte trace
# file is ever written. RAM, VRAM and everything said on the UART are
# compared at the end.
#
# Both sides run on tick(), not run_line(): the two differ in how a
# line boundary falls mid-instruction, and mixing them diverges the
# interrupt timing.

FMT = "%04x %02x%02x%02x%02x %04x %04x %04x %02x"


def _state(m):
    c = m.cpu
    return FMT % (c.pc, c.r[0], c.r[1], c.r[2], c.r[3], c.x, c.y, c.sp, c.f)


def _mdisasm(m, pc):
    """Disassemble for a divergence report, without touching the live
    bus — an I/O-page read has side effects, a report must not."""
    import opcodes

    def rd(a):
        a &= 0xFFFF
        if m.romen and (a & 0xF000) == 0xF000:
            return m.rom[a & 0x0FFF]
        return m.bus.mem[a]

    try:
        return opcodes.disassemble(rd, pc)[0]
    except Exception:
        return "??"


def _script_file(tag, ops):
    path = os.path.join(BUILD, f"{tag}.script")
    with open(path, "w", newline="\n") as f:
        for kind, arg in ops:
            if kind == "frames":
                f.write(f"frames {arg}\n")
            elif kind == "poke":
                addr, data = arg
                f.write("poke %04x " % addr
                        + " ".join("%02x" % b for b in data) + "\n")
            else:
                f.write(kind + " " + " ".join("%02x" % b for b in arg)
                        + "\n")
    return path


def machine_pair(tag, ops, flash_path=None, sanity=None, fb=False):
    """Run one script on both machines, comparing in lockstep.

    `ops` is [("type", bytes) | ("scan", bytes) | ("frames", n) |
    ("poke", (addr, bytes)), ...] — a poke writes every byte to that
    one address through the bus, which is what makes the
    auto-incrementing data ports scriptable. `sanity(m, said)` may
    return an error string; it guards against the trap of a workload
    that diverges nowhere because it silently stopped doing anything.

    With `fb=True` the Rust side renders every scanline as it runs and
    the final frame is compared against cool8vid.render_np on the
    Python machine — the model that is itself checked against the
    RTL's own pixels by sim/test_vm.py. The registers must be static
    over the last full frame for the two to be comparable, cursor
    included: poke it off and idle before ending the script.
    """
    import cool8vm as vm

    rom, font = _rom_font()
    rom_path = os.path.join(BUILD, "machine_rom.bin")
    with open(rom_path, "wb") as f:
        f.write(rom)
    script = _script_file(tag, ops)

    mem_p = os.path.join(BUILD, f"{tag}.rstmem")
    vram_p = os.path.join(BUILD, f"{tag}.rstvram")
    said_p = os.path.join(BUILD, f"{tag}.rstsaid")
    fb_p = os.path.join(BUILD, f"{tag}.rstfb")
    cmd = [EXE, f"+rom={rom_path}", f"+script={script}", "+trace=-",
           f"+memdump={mem_p}", f"+vramdump={vram_p}", f"+said={said_p}"]
    if fb:
        font_path = os.path.join(BUILD, "machine_font.bin")
        with open(font_path, "wb") as f:
            f.write(font)
        cmd += [f"+font={font_path}", f"+fbdump={fb_p}"]
    if flash_path:
        cmd.append(f"+flash={flash_path}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)

    m = vm.Machine(rom=rom, font=font, flash_path=flash_path)
    idx = 0
    fail = None
    try:
        for kind, arg in ops:
            if kind == "type":
                m.uart.feed(bytes(arg))
            elif kind == "scan":
                m.scancode(bytes(arg))
            elif kind == "poke":
                addr, data = arg
                for b in data:
                    m.bus.write(addr, b)
            else:
                target = m.frames + arg
                while m.frames < target:
                    before = m.cpu.instructions
                    prev = m.cpu.pc
                    m.tick()
                    if m.cpu.instructions == before:
                        continue
                    idx += 1
                    mine = _state(m)
                    theirs = proc.stdout.readline().rstrip("\n")
                    if mine != theirs:
                        fail = (f"    {tag}: DIVERGED at instruction {idx}\n"
                                f"      at      {prev:04x}  "
                                f"{_mdisasm(m, prev)}\n"
                                f"      py  {mine}\n"
                                f"      rs  {theirs or '<ended>'}")
                        raise StopIteration
        extra = proc.stdout.readline()
        if extra:
            fail = (f"    {tag}: rust traced past the python machine "
                    f"at instruction {idx + 1}: {extra.strip()}")
    except StopIteration:
        pass
    finally:
        proc.stdout.close()
        proc.stderr.read()
        proc.wait()

    if fail:
        print(fail)
        return False, idx

    rst_mem = cosim.read_memdump(mem_p)
    rst_vram = cosim.read_memdump(vram_p)
    with open(said_p, "rb") as f:
        rst_said = f.read()

    said = m.said()
    for name, mine, theirs in (("RAM", bytes(m.bus.mem), rst_mem),
                               ("VRAM", bytes(m.video.vram), rst_vram),
                               ("UART", said, rst_said)):
        if mine != theirs:
            first = next(i for i in range(min(len(mine), len(theirs)) + 1)
                         if i >= len(mine) or i >= len(theirs)
                         or mine[i] != theirs[i])
            print(f"    {tag}: {name} differs, first at ${first:04X}")
            return False, idx
    if fb:
        try:
            import numpy as np
            import cool8vid
        except ImportError:
            print(f"    {tag}: numpy not available, frame not compared")
        else:
            want = np.asarray(cool8vid.render_np(m))
            with open(fb_p, "rb") as f:
                got = np.frombuffer(f.read(), dtype="<u2")
            got = got.reshape(480, 640).astype(np.int64)
            if not np.array_equal(want, got):
                bad = np.argwhere(want != got)
                y, x = bad[0]
                print(f"    {tag}: frame differs at {len(bad)} pixels, "
                      f"first at ({x},{y}): py ${want[y, x]:03X} "
                      f"rs ${got[y, x]:03X}")
                return False, idx
    if sanity:
        err = sanity(m, said)
        if err:
            print(f"    {tag}: workload sanity: {err}")
            return False, idx
    return True, idx


_ROM_FONT = []


def _rom_font():
    if not _ROM_FONT:
        import cool8vm as vm
        _ROM_FONT.append(vm.build_rom())
    return _ROM_FONT[0]


def _basic_image():
    """A flash image with BOOT.BIN on volume 0 — the path a board runs,
    borrowed from sim/test_boot_basic.py."""
    import cool8disk as disk
    import mkboot
    import test_basic as B

    code, syms = B.build()
    boot = mkboot.build(code, dest=0xA000, build_dir=BUILD)
    img = os.path.join(BUILD, "rs_boot.img")
    if os.path.exists(img):
        os.remove(img)
    image = disk.Image(img, create=True)
    v = disk.Volume(image, 0)
    v.format("SYSTEM")
    p = os.path.join(BUILD, "BOOT.BIN")
    with open(p, "wb") as fh:
        fh.write(boot)
    v.add(p, "BOOT.BIN")
    image.save()
    return img


def _keys(text):
    """Scancode bytes for typed text, from the real sw/keymap.asm —
    encoded once, here, so both machines are fed identical bytes."""
    import cool8vm as vm
    return vm._encode_keys(text)


def test_machine_monitor():
    print("machine — boot ROM to the monitor, over the serial console")
    t0 = time.time()
    ops = [("frames", 8),
           ("type", b"D F000\r"), ("frames", 8),
           ("type", b"D F070\r"), ("frames", 8)]

    def sanity(m, said):
        said = said.decode("latin-1")
        if "COOL8 monitor" not in said:
            return "the monitor never introduced itself"
        if "F000 2F 60 00 02" not in said:
            return "D F000 did not answer with the reset vector"
        return None

    ok, n = machine_pair("rs_monitor", ops, sanity=sanity)
    print(f"  24 frames, {n} instructions : {'ok' if ok else 'FAIL'} "
          f"({time.time() - t0:.1f}s)")
    return ok


def test_machine_basic():
    """Reset to BASIC off a flash image, then a program typed at the
    PS/2 port and RUN — flash, autoboot, the relocation, ROMEN, the
    keyboard interrupt and the video registers, all on one diff."""
    print("machine — flash, autoboot, BASIC, a typed program")
    t0 = time.time()
    img = _basic_image()

    ops = [("frames", 90)]
    for ch in "10 PRINT 6 * 7\r20 END\rRUN\r":
        ops += [("scan", _keys(ch)), ("frames", 2)]
    ops += [("frames", 30)]

    def sanity(m, _said):
        if m.romen:
            return "ROMEN is still on: autoboot never handed over"
        if not m.shows("42"):
            return "RUN never printed 42: " + " | ".join(
                r.strip() for r in m.text() if r.strip())[:100]
        return None

    ok, n = machine_pair("rs_basic", ops, flash_path=img, sanity=sanity)
    print(f"  {n} instructions : {'ok' if ok else 'FAIL'} "
          f"({time.time() - t0:.1f}s)")
    return ok


# ---- building a display scene by poking the real I/O ports

def _pal(entries):
    """PAL_IDX/PAL_DATA writes for [(index, rgb12), ...]."""
    ops = []
    for idx, rgb in entries:
        ops.append(("poke", (0xFE1E, [idx])))
        ops.append(("poke", (0xFE1F, [(rgb >> 8) & 0x0F, rgb & 0xFF])))
    return ops


def _vram(addr, data):
    """VADDR/VSTEP/VDATA writes: `data` bytes from `addr`, step 1."""
    return [("poke", (0xFE26, [addr & 0xFF])),
            ("poke", (0xFE27, [addr >> 8])),
            ("poke", (0xFE28, [1])),
            ("poke", (0xFE29, list(data)))]


def _sprites(descs, ctrl):
    """SPR_IDX/SPR_DATA for 8-byte descriptors from index 0, then CTRL."""
    data = []
    for d in descs:
        data += list(d)
    return [("poke", (0xFE2A, [0])), ("poke", (0xFE2B, data)),
            ("poke", (0xFE2C, [ctrl]))]


def _desc(x, y, pat, big=False, hflip=False, vflip=False, behind=False):
    """One descriptor, packed as cool8_sprite's scan reads it."""
    v = pat >> 5
    return [y & 0xFF,
            (0x80 if big else 0) | 0x40 | ((y >> 8) & 1),
            x & 0xFF, (x >> 8) & 3,
            v & 0xFF, (v >> 8) & 7,
            (0x80 if vflip else 0) | (0x40 if hflip else 0)
            | (0x20 if behind else 0),
            0]


def _asym(n):
    """An asymmetric 4 bpp pattern, n rows of n pixels, colour 0 in the
    top-left quarter so transparency and `behind` have something to
    show through."""
    out = []
    for r in range(n):
        row = [(0 if (r < n // 2 and c < n // 2) else ((r + c) % 15) + 1)
               for c in range(n)]
        for i in range(0, n, 2):
            out.append((row[i] << 4) | row[i + 1])
    return out


def test_render():
    """The scanline renderer against cool8vid.render_np, per pixel.

    render_np is the model sim/test_vm.py compares against the RTL's
    own rendered output, so agreement here chains back to hardware.
    Static frames only — the per-line renderer's whole point, a
    mid-frame change, is exactly what a whole-frame model cannot
    check, so that part rests on the RTL derivation in render.rs.
    """
    print("machine — the scanline renderer against cool8vid, per pixel")
    ok = True

    # ---- text: the monitor's own boot screen, cursor off
    ops = [("frames", 8), ("type", b"D F000\r"), ("frames", 4),
           ("poke", (0xFE24, [0x00])), ("frames", 2)]
    t0 = time.time()
    good, _ = machine_pair("rs_fb_text", ops, fb=True)
    print(f"  text, the monitor's screen : "
          f"{'ok' if good else 'FAIL'} ({time.time() - t0:.1f}s)")
    ok &= good

    # ---- tiles: every attribute bit, fine scroll, sprites over them
    ops = [("frames", 8), ("poke", (0xFE10, [0x82]))]      # preset 2 + enable
    ops += [("poke", (0xFE20, [0x00])), ("poke", (0xFE21, [0x40]))]
    ops += _pal([(i, 0x111 * (i & 15)) for i in range(16)]
                + [(0x10 + i, (i << 8) | 0x0F0) for i in range(16)]
                + [(0x50 + i, (i << 4) | 0xF00) for i in range(16)])
    ops += _vram(0x4020, _asym(8))                          # tile 1
    row0 = []
    for i, attr in enumerate([0x01, 0x41, 0x81, 0xC1, 0x00, 0x01] * 6):
        row0 += [0x01 if attr != 0x00 else 0x00, attr]
    ops += _vram(0x0000, row0)                              # map row 0
    ops += _vram(128, [0x01, 0x01] * 20)                    # map row 1
    ops += _vram(0x0800, _asym(8))                          # sprite 8x8
    ops += _vram(0x0900, _asym(16))                         # sprite 16x16
    descs = [_desc(20 + 12 * i, 40, 0x0800) for i in range(10)]
    descs += [_desc(60, 100, 0x0900, big=True),
              _desc(90, 100, 0x0800, hflip=True),
              _desc(110, 100, 0x0800, vflip=True),
              _desc(130, 100, 0x0800, behind=True),
              _desc(130, 10, 0x0800, behind=True)]
    ops += _sprites(descs, 0x51)                            # bank 5, enable
    ops += [("poke", (0xFE16, [3])), ("poke", (0xFE18, [5]))]
    ops += [("frames", 3)]
    t0 = time.time()
    good, _ = machine_pair("rs_fb_tile", ops, fb=True)
    print(f"  tiles, flips, scroll, 15 sprites : "
          f"{'ok' if good else 'FAIL'} ({time.time() - t0:.1f}s)")
    ok &= good

    # ---- bitmap: 8 bpp, scrolled, sprites with `behind` over it
    ops = [("frames", 8), ("poke", (0xFE10, [0x86]))]      # preset 6 + enable
    ops += _pal([(i, i * 0x011) for i in range(16)])
    rows = bytes((x * (y + 1)) & 0xFF if x > 40 else 0
                 for y in range(6) for x in range(256))
    ops += _vram(0x0000, rows)
    ops += _vram(0x0800, _asym(8))
    ops += _sprites([_desc(30, 1, 0x0800),
                     _desc(60, 1, 0x0800, behind=True)], 0x11)
    ops += [("poke", (0xFE16, [7])), ("frames", 3)]
    t0 = time.time()
    good, _ = machine_pair("rs_fb_bmp", ops, fb=True)
    print(f"  bitmap 8 bpp, scrolled, behind : "
          f"{'ok' if good else 'FAIL'} ({time.time() - t0:.1f}s)")
    ok &= good
    return ok


def speed_machine():
    """The machine-level number: the same boot, no trace being compared.

    The Python figure is m.tick() alone, the discipline the parity run
    uses; the Rust figure is the runner's own stepping time off stderr.
    """
    import cool8vm as vm

    rom, font = _rom_font()
    ops = [("frames", 90)]
    script = _script_file("rs_mspeed", ops)
    rom_path = os.path.join(BUILD, "machine_rom.bin")

    m = vm.Machine(rom=rom, font=font)
    t0 = time.time()
    while m.frames < 90:
        m.tick()
    t_py = time.time() - t0
    n = m.cpu.instructions

    r = subprocess.run([EXE, f"+rom={rom_path}", f"+script={script}"],
                       capture_output=True, text=True)
    t_rs = float(r.stderr.strip().split()[-1].rstrip("s"))

    print(f"speed — 90 frames of boot ROM, {n} instructions")
    print(f"  python  {t_py:8.4f}s  {n / t_py / 1e6:8.2f} M instr/s")
    print(f"  rust    {t_rs:8.4f}s  {n / t_rs / 1e6:8.2f} M instr/s"
          f"   ({t_py / t_rs:.0f}x)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="skip the exhaustive multiply, the BASIC boot "
                         "and the speed runs")
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
    ok &= test_machine_monitor()
    if not args.quick:
        ok &= test_mul()
        ok &= test_machine_basic()
        ok &= test_render()
        speed()
        speed_machine()

    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
