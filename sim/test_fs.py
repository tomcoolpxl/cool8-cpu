#!/usr/bin/env python3
"""M11 -- the filesystem, from both ends.

    python sim/test_fs.py

`sw/fs.asm` and `tools/cool8disk.py` are the same filesystem written
twice: once in COOL8 assembly for the machine, once in Python for the
desktop. This is the gate that makes them agree.

  the PC writes, the machine reads    a file put in by cool8disk.py is
                                      loaded by fs_load, byte for byte
  the machine writes, the PC reads    a file saved by fs_save is pulled
                                      back out by cool8disk.py
  the machine deletes                 and the PC sees it gone, with the
                                      bytes still there until a compact
  the free pointer is derived         a second save lands after the
                                      first, with nothing stored to say so
  the floor holds                     a program below $100000 is refused
                                      and sets the flag, and the image is
                                      unchanged

**Two implementations, no shared code.** The Python does not import the
assembler's constants and the assembly does not read the Python's; both
were written from the layout in their own headers. An agreement between
them is therefore evidence, which is the same reason cool8emu and the
RTL are kept apart.

The machine runs on tools/cool8vm.py, whose flash models the two things
that make this format work -- the $100000 floor in gates, and
programming that can only clear bits.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8vm as vm                                     # noqa: E402
import cool8disk as disk                                 # noqa: E402

ASM = os.path.join(ROOT, "tools", "cool8asm.py")
FS = os.path.join(ROOT, "sw", "fs.asm").replace("\\", "/")
IMG = os.path.join(BUILD, "fs.img")

OK = 0x5000          # the machine leaves its result here
LEN = 0x5002
DEST = 0x4000


def build(name, body):
    """Assemble a driver with sw/fs.asm behind it."""
    src = os.path.join(BUILD, name + ".asm")
    out = os.path.join(BUILD, name + ".bin")
    with open(src, "w") as fh:
        # A leading global label: local labels are scoped to the last
        # global one, so a driver whose first label is `.bad` has
        # nowhere to hang it.
        fh.write("        .org $0200\nmain:\n" + body +
                 f'\n        .include "{FS}"\n')
    r = subprocess.run([sys.executable, ASM, src, "-o", out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("assembly failed: " + name)
    with open(out, "rb") as fh:
        return fh.read()


def run(code, steps=40_000_000):
    """A bare machine: no ROM, the program at $0200, our image as flash."""
    m = vm.Machine(flash_path=IMG)
    m.bus.mem[0x200:0x200 + len(code)] = code
    m.cpu.pc = 0x200
    m.cpu.sp = 0xFFF7
    m.romen = False
    n = 0
    while n < steps and not m.cpu.halted:
        m.tick()
        n += 1
    if not m.cpu.halted:
        raise SystemExit("the machine did not halt")
    return m


def name8_3(s):
    return disk.pad_name(s).decode("ascii")


FAILS = []


def check(cond, what, detail=""):
    print(f"  {what:<52} {'ok' if cond else 'FAIL'}")
    if not cond:
        FAILS.append(what)
        if detail:
            print("    " + detail)


# =====================================================================

def main():
    print("  M11 -- sw/fs.asm against tools/cool8disk.py")
    print()

    # ---------------------------------------------- the PC makes a disk
    if os.path.exists(IMG):
        os.remove(IMG)
    img = disk.Image(IMG, create=True)
    v = disk.Volume(img, 0)
    v.format("COOL8")
    payload = bytes(range(256)) * 2 + b"the end."
    p1 = os.path.join(BUILD, "fs_p1.bin")
    with open(p1, "wb") as fh:
        fh.write(payload)
    v.add(p1, "HELLO.TXT")
    img.save()

    # ------------------------------------- 1. the PC writes, machine reads
    code = build("fs_load", f"""
        CLR  R0
        CALL fs_mount
        LDW  X,#nm
        LDW  Y,#${DEST:04X}
        CALL fs_load
        BCC  .bad
        LD   R0,[fslen]
        ST   [${LEN:04X}],R0
        LD   R0,[fslen+1]
        ST   [${LEN+1:04X}],R0
        MOV  R0,#1
        ST   [${OK:04X}],R0
        HALT
.bad:   CLR  R0
        ST   [${OK:04X}],R0
        HALT
nm:     .ascii "{name8_3('HELLO.TXT')}"
""")
    m = run(code)
    got = bytes(m.bus.mem[DEST:DEST + len(payload)])
    n = m.bus.mem[LEN] | (m.bus.mem[LEN + 1] << 8)
    check(m.bus.mem[OK] == 1 and n == len(payload) and got == payload,
          f"the PC writes, the machine reads it ({len(payload)} bytes)",
          f"flag={m.bus.mem[OK]} len={n} want={len(payload)}")

    # ------------------------------------ 2. the machine writes, PC reads
    body = "".join(f"        .byte ${b:02X}\n" for b in b"saved by COOL8!")
    code = build("fs_save", f"""
        CLR  R0
        CALL fs_mount
        LDW  X,#nm
        LDW  Y,#dat
        MOV  R0,#<datlen
        ST   [fslen],R0
        MOV  R0,#>datlen
        ST   [fslen+1],R0
        CALL fs_save
        BCC  .bad
        MOV  R0,#1
        ST   [${OK:04X}],R0
        HALT
.bad:   CLR  R0
        ST   [${OK:04X}],R0
        HALT
nm:     .ascii "{name8_3('SAVED.BIN')}"
dat:
{body}datend:
datlen  = datend-dat
""")
    m = run(code)
    m.flash.flush()
    check(m.bus.mem[OK] == 1, "fs_save reports success")

    v = disk.Volume(disk.Image(IMG), 0)
    e = v.find("SAVED.BIN")
    check(e is not None and v.get("SAVED.BIN") == b"saved by COOL8!",
          "the machine writes, the PC reads it back",
          "not found" if e is None else repr(v.get("SAVED.BIN")))

    # the older file must be untouched
    check(v.get("HELLO.TXT") == payload,
          "and the file that was already there is unharmed")

    # ------------------------------- 3. the free pointer really is derived
    # Exactly the next free page, not merely somewhere after it. This
    # used to read `>=`, and passed for a long time while fs_mount was
    # deriving a pointer 256 pages too high on every file whose length
    # was not a multiple of 256 -- the machine and the PC tool disagreed
    # about where the free space started, which is the one thing this
    # file exists to catch.
    want = (0x1000 + len(payload) + 255) // 256
    check(e is not None and e["page"] == want,
          "the second file lands on exactly the next free page",
          "" if e is None else f"page {e['page']}, wanted {want}")

    # ------------------------------------------- 4. the machine deletes
    code = build("fs_del", f"""
        CLR  R0
        CALL fs_mount
        LDW  X,#nm
        CALL fs_delete
        BCC  .bad
        MOV  R0,#1
        ST   [${OK:04X}],R0
        HALT
.bad:   CLR  R0
        ST   [${OK:04X}],R0
        HALT
nm:     .ascii "{name8_3('HELLO.TXT')}"
""")
    m = run(code)
    m.flash.flush()
    v = disk.Volume(disk.Image(IMG), 0)
    check(m.bus.mem[OK] == 1 and v.find("HELLO.TXT") is None,
          "the machine deletes, and the PC agrees it is gone")

    raw = disk.Image(IMG).data
    at = v.base + 0x1000
    check(bytes(raw[at:at + len(payload)]) == payload,
          "the bytes are still there -- a delete erases nothing")

    kept = v.compact()
    check(kept == 1, "compaction keeps the one live file", f"kept {kept}")

    # --------------------------------------------- 5. the floor holds
    code = build("fs_floor", f"""
        CLR  R0
        ST   [$FE88],R0
        ST   [$FE89],R0
        ST   [$FE8A],R0        ; address $000000 -- the bitstream
        MOV  R0,#$AA
        ST   [$FE8E],R0
        MOV  R0,#1
        ST   [$FE8F],R0        ; program
        LD   R0,[$FE8F]
        ST   [${OK:04X}],R0
        HALT
""")
    before = bytes(disk.Image(IMG).data[:64])
    m = run(code)
    m.flash.flush()
    after = bytes(disk.Image(IMG).data[:64])
    check((m.bus.mem[OK] & 0x04) != 0 and before == after,
          "a program below $100000 is refused, and nothing changes",
          f"WCTRL read ${m.bus.mem[OK]:02X}")

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
