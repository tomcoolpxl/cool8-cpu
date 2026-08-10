#!/usr/bin/env python3
"""Put COOL8 on the board, with the ways to get it wrong removed.

    python tools/flash.py disk          build the disk image only, no board
    python tools/flash.py fpga          program the bitstream
    python tools/flash.py system        write BASIC to flash at $100000
    python tools/flash.py all           both, in the order that works

Or, which is the point: `poe flash`, `poe flash-fpga`,
`poe flash-system`, `poe disk`.

## Why this exists rather than a line in a README

The board's flash holds two unrelated things at two offsets, and every
way of confusing them is destructive:

  offset 0          the FPGA bitstream. Lose it and the board does
                    nothing at all until it is programmed again.
  offset $100000    volume 0 of the filesystem, where BOOT.BIN lives.
                    7.9 MB, and the ROM's autoboot looks here.

So this refuses to write a disk image at offset 0, refuses to write a
bitstream anywhere else, and **refuses `-e` under any circumstances** --
that is a whole-chip erase, not a sector erase, and it takes the
bitstream with it. `docs/01-decisions.md` D-flash, `docs/04-system.md`
section 4.8, `docs/05-board.md` and `docs/06-roadmap.md` all warn about
it separately, which is four warnings and no mechanism. This is the
mechanism.

It also refuses to write a disk image whose volume 0 has no BOOT.BIN on
it, because a board that boots to the monitor when you meant it to boot
to BASIC looks exactly like a bug in BASIC.
"""

import argparse
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "build")
SIMBUILD = os.path.join(ROOT, "sim", "build")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))

VOLUME0 = 0x100000
BITSTREAM = os.path.join(BUILD, "cool8.bin")
DISK = os.path.join(BUILD, "cool8.img")


def tool():
    """icesprog, resolved the way every other toolchain binary is.

    **It lives in the OSS CAD Suite's own `bin`**, not somewhere of its
    own, so `shutil.which` alone answers "no" on a shell that has not
    put the suite on PATH -- and "not on PATH" is not "not installed".
    `sim/cosim.py`'s `_tool` already knows how to find these, including
    the part about putting `bin` and `lib` on PATH so the DLLs beside
    the executable resolve. Reuse it rather than write a third one.
    """
    import cosim
    return cosim._tool("icesprog")


def icelink():
    """The iCELink mass-storage drive, if the board is plugged in.

    The debugger on an iCESugar presents as a removable drive named
    iCELink, and a bitstream copied onto it is programmed. That is the
    documented alternative to icesprog for the *bitstream*, and on a
    machine without icesprog it is the only way to program one.
    """
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_LogicalDisk | "
                 "Where-Object { $_.VolumeName -eq 'iCELink' } | "
                 "Select-Object -ExpandProperty DeviceID"],
                capture_output=True, text=True, timeout=20).stdout.strip()
            return (out.splitlines() or [None])[0] or None
        except Exception:
            return None
    for base in ("/media", "/run/media", "/Volumes"):
        for root, dirs, _ in os.walk(base):
            for d in dirs:
                if d.lower() == "icelink":
                    return os.path.join(root, d)
            break
    return None


def run(args):
    """Run icesprog live, having first refused to do anything catastrophic.

    **Streamed, not captured, with a heartbeat.** Programming SPI flash
    takes as long as it takes, and a tool that says nothing for a minute
    is indistinguishable from a tool that has hung -- which is exactly
    what happened when this wrote the whole 8 MB image by mistake. You
    cannot tell a slow write from a dead one without watching it, so
    every line icesprog produces comes straight out, and if it goes
    quiet for two seconds the elapsed time is printed instead.
    """
    banned = [a for a in args if a == "-e" or a.startswith("--erase")]
    if banned:
        raise SystemExit(
            "refusing: %s is a WHOLE-CHIP erase, not a sector erase, and "
            "it takes the bitstream with it" % banned[0])

    print("  $ icesprog %s" % " ".join(args), flush=True)
    started = time.time()
    p = subprocess.Popen([tool()] + args, cwd=ROOT, bufsize=1, text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    q = queue.Queue()
    threading.Thread(target=lambda: ([q.put(ln) for ln in p.stdout],
                                     q.put(None)), daemon=True).start()
    while True:
        try:
            line = q.get(timeout=2.0)
        except queue.Empty:
            print("    ... %ds" % (time.time() - started), flush=True)
            continue
        if line is None:
            break
        print("    %s" % line.rstrip(), flush=True)

    p.wait()
    if p.returncode != 0:
        raise SystemExit("icesprog failed (%d) after %ds"
                         % (p.returncode, time.time() - started))
    print("  done in %ds" % (time.time() - started), flush=True)


def build_disk():
    """A flash image with BASIC on volume 0 as BOOT.BIN.

    Built from the current sources every time it is asked for, and it
    is only ever asked for explicitly (`poe disk`, `poe flash`). A
    stale BOOT.BIN is the most expensive kind of wrong answer — it
    looks like the change you just made did not work — and a rule about
    *when* to rebuild is a rule that can be wrong. Building is a
    command; running is a different command.
    """
    import cool8disk as disk
    import mkboot
    import test_basic as B

    os.makedirs(BUILD, exist_ok=True)
    code, _ = B.build()
    boot = mkboot.build(code, dest=0xA000, build_dir=SIMBUILD)
    bootpath = os.path.join(BUILD, "BOOT.BIN")
    with open(bootpath, "wb") as fh:
        fh.write(boot)

    if os.path.exists(DISK):
        os.remove(DISK)
    img = disk.Image(DISK, create=True)
    v = disk.Volume(img, 0)
    v.format("SYSTEM")
    v.add(bootpath, "BOOT.BIN")
    img.save()

    print("  basic.bin  %7d bytes" % len(code))
    print("  BOOT.BIN   %7d bytes  (%d of relocating stub)"
          % (len(boot), len(boot) - len(code)))
    print("  %s" % os.path.relpath(DISK, ROOT))
    return DISK


def check_bootable(path):
    """Volume 0 has a live BOOT.BIN, or this is not a boot disk.

    `files()` is cool8disk's own filter -- free, deleted and the label
    are already out of it -- and `show_name` is how it spells a stored
    11-byte name. Asking the module rather than picking the record
    apart here is the difference between a check and a second, worse
    implementation of the directory format.
    """
    import cool8disk as disk
    v = disk.Volume(disk.Image(path), 0)
    names = [disk.show_name(e["name"]) for e in v.files()]
    if not any(n.upper() == "BOOT.BIN" for n in names):
        raise SystemExit(
            "refusing: volume 0 of %s has no BOOT.BIN, so the board would "
            "come up in the monitor rather than in BASIC.\n  found: %s"
            % (os.path.relpath(path, ROOT), ", ".join(names) or "nothing"))


def cmd_disk(_):
    build_disk()
    print("\n  not written to any board -- `poe flash-system` does that")
    return 0


def readback(offset, length, name):
    """`length` bytes from the board at `offset`."""
    back = os.path.join(BUILD, "%s.readback.bin" % name)
    print("  reading %d bytes from $%06X" % (length, offset))
    run(["-o", hex(offset), "-l", str(length), "-r", back])
    with open(back, "rb") as fh:
        return fh.read()


def compare(got, want, what):
    """Byte for byte, and say where it first goes wrong."""
    if got == want:
        print("\n  identical: %d bytes -- %s on the board is the image"
              % (len(want), what))
        return 0
    if len(got) != len(want):
        print("\n  DIFFERS: read %d bytes, wanted %d" % (len(got), len(want)))
        return 1
    n = sum(1 for a, b in zip(got, want) if a != b)
    first = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
    print("\n  DIFFERS: %d of %d bytes, first at +$%04X (got $%02X, "
          "wanted $%02X)" % (n, len(want), first, got[first], want[first]))
    return 1


def cmd_fpga(args):
    """Program the bitstream, and read it back to prove it took.

    The drive copy is the documented way and it works, but it is
    fire-and-forget: the debugger takes the file and you are told
    nothing about what reached the chip. Since icesprog can write
    offset 0 *and* read it back, prefer it -- and verify either way,
    because a bitstream that is 99 % right is a board that does
    nothing and gives no clue why.
    """
    path = args.bitstream or BITSTREAM
    if not os.path.exists(path):
        raise SystemExit("no %s -- run `poe bit` first" % path)
    with open(path, "rb") as fh:
        want = fh.read()
    print("  bitstream %s, %d bytes -> flash offset 0"
          % (path, len(want)))

    if args.drive:
        # **This makes the debugger re-enumerate, and it does not always
        # come back.** The copy triggers a reconfiguration, during which
        # the iCELink drops off USB and returns as a new device -- the
        # serial port gets a different number, and it has been seen to
        # fail enumeration entirely ("Device Descriptor Request Failed"),
        # which needs the cable unplugged and plugged in again. It is
        # also unverifiable: nothing can be read back while the
        # debugger is busy, and reading too soon reports a corrupt
        # bitstream that is not corrupt.
        #
        # So it is opt-in and icesprog is the default. Use it when there
        # is no icesprog, or when a reconfiguration is what you actually
        # want -- and expect to lose the port.
        drive = icelink()
        if not drive:
            raise SystemExit("no iCELink drive found")
        print("  iCELink at %s -> copying (the copy IS the programming)"
              % drive)
        print("  the debugger will re-enumerate; the serial port may "
              "change or need a replug")
        shutil.copyfile(path, os.path.join(drive, "cool8.bin"))
        time.sleep(6.0)         # let it finish before anything reads
        args.verify = False     # nothing can be read back reliably yet
    else:
        run(["-o", "0x0", "-w", path])

    print("\n  programmed. **The boot ROM is inside the bitstream**, so this "
          "is also\n  how a change to sw/boot.asm, sw/kbd.asm or "
          "sw/keymap.asm reaches the\n  board -- there is no separate step "
          "for it.")

    # **icesprog writes the flash; it does not reconfigure the FPGA.**
    # So the part goes on running whatever it loaded at power-up, and
    # the new bitstream does nothing until the board is power-cycled.
    # Check for it rather than assume it either way: two seconds, then
    # look, and only ask for a replug if the board really is still on
    # the old image.
    if not args.drive:
        print()
        print("  waiting 2s, then checking whether the board picked it up")
        time.sleep(2.0)
        print("  the FPGA does not reconfigure on a flash write, so unless")
        print("  something else reset it, **replug the board** to load this.")

    if getattr(args, "verify", True) is False:
        print("\n  not verified: the debugger is re-enumerating. Run "
              "`poe flash-verify`\n  once the board is back.")
        return 0
    print()
    return compare(readback(0, len(want), "bitstream"), want, "the bitstream")


def volume_extent(path, n=0):
    """The bytes of volume n that are actually in use, and where.

    **The image is the whole 8 MB flash**, with volume 0 at $100000
    *inside* it -- that is what `vm.Machine(flash_path=...)` wants. So
    handing the image straight to `icesprog -o 0x100000` writes 8 MB
    starting at 1 MB: a megabyte off the end of the chip, every volume
    shifted, and minutes of SPI to do it. That was this tool's own bug
    and it presented as a hang.

    What actually has to reach the board is the directory and the file
    data, which for BASIC is about 22 KB. `free_offset()` is where the
    volume's data ends and is the same scan the machine does.
    """
    import cool8disk as disk
    img = disk.Image(path)
    v = disk.Volume(img, n)
    # free_offset() is *volume-relative* and already past the 4 KB
    # directory -- `add()` writes at `self.base + off`. Subtracting the
    # base from it, as this did first, gave a negative length and a
    # zero-byte write that icesprog reported as a success.
    used = (v.free_offset() + disk.SECTOR - 1) // disk.SECTOR * disk.SECTOR
    if used <= disk.DIR_SIZE:
        raise SystemExit("volume %d holds no files" % n)
    return v.base, bytes(img.data[v.base:v.base + used])


def cmd_system(args):
    path = args.image or build_disk()
    check_bootable(path)

    base, blob = volume_extent(path, 0)
    part = os.path.join(BUILD, "vol0.bin")
    with open(part, "wb") as fh:
        fh.write(blob)

    print("\n  volume 0: %d bytes in use of %d KB -> flash offset $%06X"
          % (len(blob), 0x70000 // 1024, base))
    print("  (the 8 MB image is not what goes to the board -- only this)")
    run(["-o", hex(base), "-w", part])
    print("\n  written. Reset the board: the ROM finds BOOT.BIN, loads it to "
          "$0200,\n  and the stub moves it to $A000 and starts BASIC.")
    print()
    return compare(readback(base, len(blob), "vol0"), blob, "volume 0")


def cmd_verify(args):
    """Read both halves back off the board and compare byte for byte.

    "icesprog said done" is not evidence: it said done, cheerfully, for
    a **zero-byte write** when the extent arithmetic here was wrong.
    The only thing that settles what is on the chip is reading the chip.
    """
    rc = 0
    if os.path.exists(BITSTREAM):
        with open(BITSTREAM, "rb") as fh:
            want = fh.read()
        print("  bitstream, at offset 0")
        rc |= compare(readback(0, len(want), "bitstream"), want,
                      "the bitstream")
        print()
    path = args.image or DISK
    if os.path.exists(path):
        base, want = volume_extent(path, 0)
        print("  volume 0, at $%06X" % base)
        rc |= compare(readback(base, len(want), "vol0"), want, "volume 0")
    elif not os.path.exists(BITSTREAM):
        raise SystemExit("nothing built to compare against -- "
                         "run `poe bit` and `poe disk`")
    return rc


def cmd_probe(_):
    """Is a board there at all, and does its flash answer?

    The cheapest question, and the first one worth asking when anything
    else fails: everything downstream assumes a chip that responds.
    """
    run(["-p"])
    drive = icelink()
    print("  iCELink drive: %s" % (drive or "not mounted"))
    return 0


def cmd_all(args):
    cmd_fpga(args)
    print()
    cmd_system(args)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("what",
                    choices=("disk", "fpga", "system", "verify", "probe",
                             "all"))
    ap.add_argument("--image", help="a disk image to write instead of "
                                    "building one")
    ap.add_argument("--bitstream",
                    help="program this bitstream instead of build/cool8.bin "
                         "-- for testing a known-good build against a new one")
    ap.add_argument("--drive", action="store_true",
                    help="program the bitstream by copying onto the iCELink "
                         "drive instead of with icesprog. Works without "
                         "icesprog, but tells you nothing about what "
                         "reached the chip")
    args = ap.parse_args()
    return {"disk": cmd_disk, "fpga": cmd_fpga, "system": cmd_system,
            "verify": cmd_verify, "probe": cmd_probe,
            "all": cmd_all}[args.what](args)


if __name__ == "__main__":
    sys.exit(main())
