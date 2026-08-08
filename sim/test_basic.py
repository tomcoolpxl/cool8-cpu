#!/usr/bin/env python3
"""S1 -- the screen editor, typed at.

    python sim/test_basic.py

`sw/basic.bas` is COOL8 BASIC itself: one screen, a cursor, and a Return
key. This drives it the way a person would -- every character goes in
over the wire and every check reads the screen back out.

What is checked:

  boot        the machine comes up with its banner and a free-memory line
  stored      numbered lines are stored, tokenised, in ascending order
  LIST        and come back out in order, detokenised, whatever order
              they were typed in
  the trick   cursor up onto a listed line, type over it, press Return,
              and that line is replaced -- the screen *is* the buffer
  cursor      the hardware cursor is where the typing is
  commands    NEW empties it, DELETE removes a range, RENUMBER renumbers

## Two rules this file follows

**Read through the machine's own video registers**, never a hardcoded
address. `sim/test_edit.py` used to read where the editor *wrote* rather
than where the display was pointed, so it passed a program that never
set `VID_BASE` at all.

**Settle means idle, not "the FIFO drained".** The byte is taken out of
the FIFO before it is acted on, so a harness that stops there reads the
state one keystroke early and blames the machine.
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
import cool8vid as vid                                   # noqa: E402
import cool8bas as bas                                   # noqa: E402
import cool8disk as disk                                 # noqa: E402

ORG = 0xA000
IMG = os.path.join(BUILD, "basic.img")
FAILS = []


def check(ok, what, detail=""):
    print(f"  {what:<52} {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILS.append(what)
        if detail:
            print("    " + detail)
    return ok


def build():
    src = os.path.join(ROOT, "sw", "basic.bas")
    with open(src, encoding="utf-8") as fh:
        asm = bas.compile_source(fh.read(), ORG)
    apath = os.path.join(BUILD, "basic.asm")
    with open(apath, "w") as fh:
        fh.write(asm)
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "cool8asm.py"), apath,
                        "-o", os.path.join(BUILD, "basic.bin"),
                        "--symbols", os.path.join(BUILD, "basic.sym"),
                        "-I", os.path.join(ROOT, "sw")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("compile failed")
    syms = {}
    for line in open(os.path.join(BUILD, "basic.sym")):
        p = line.split()
        if len(p) == 2:
            syms[p[1].lower()] = int(p[0], 16)
    with open(os.path.join(BUILD, "basic.bin"), "rb") as fh:
        return fh.read(), syms


class Machine:
    def __init__(self, code, syms, flash=None):
        self.m = vm.Machine(flash_path=flash) if flash else vm.Machine()
        self.m.bus.mem[ORG:ORG + len(code)] = code
        self.m.cpu.pc = ORG
        # Where sw/boot.asm:339 leaves it, not somewhere roomier. The
        # stack grows down through page 1 and page 0 holds the
        # interpreter's state and the filesystem's, so a harness that
        # hands BASIC a 63 KB stack cannot fail the way the machine
        # would. Measured high-water mark for the whole S1-S3 run is 78
        # bytes, in s_rowaddr, leaving 178 spare.
        self.m.cpu.sp = 0x0200
        self.m.romen = False
        # rawkey's `.rk0` is reached only when nothing is waiting, so it
        # is the one address that means "idle" rather than "busy".
        self.idle = syms["s_rawkey.rk0"]
        # ...and an empty UART FIFO no longer means an empty *input*.
        # The vblank interrupt drains the FIFO into a ring and rawkey
        # reads the ring, so a machine can sit at `.rk0` for an instant
        # with bytes still queued. Settling on the FIFO alone let `type`
        # feed its next chunk on top of one still being consumed, and
        # the line arrived scrambled -- which looked like a division bug
        # because it only bit lines past a certain length.
        self.irhead = syms["irhead"]
        self.irtail = syms["irtail"]

    def settle(self, budget=80_000_000):
        n = 0
        while n < budget:
            if (not self.m.uart.rx
                    and self.m.bus.mem[self.irhead]
                    == self.m.bus.mem[self.irtail]
                    and self.m.cpu.pc == self.idle):
                return
            # tick, not cpu.step: only the machine advances the raster
            # and the interrupt flags, so a bare stepping loop runs a
            # machine where no time passes and no interrupt can fire.
            self.m.tick()
            n += 1
        raise SystemExit("the machine never went idle")

    def type(self, text, chunk=8):
        data = text.replace("\n", "\r").encode("latin-1")
        for i in range(0, len(data), chunk):
            self.m.uart.feed(data[i:i + chunk])
            self.settle()
            if self.m.uart.overrun:
                raise SystemExit("the FIFO overran")

    def vol(self, n=0):
        """Drive n as the PC-side tool sees it.

        The flush matters: the emulator holds programmed bytes until
        asked, so reading the image file without it shows the volume as
        it was before the machine touched it."""
        self.m.flash.flush()
        return disk.Volume(disk.Image(IMG), n)

    def cmd(self, s):
        """Type a command on a blank row, the way a person would.

        Typing over a row that still holds text leaves its tail behind
        -- `DELETE 20` onto a row reading `20 PRINT 2` becomes
        `DELETE 202`. That is exactly what a C64 does and it is a
        property to respect, not work around: so go to the bottom of the
        screen, which is blank, and type there.
        """
        self.type("\x1b[B" * 29, chunk=3)
        self.type("\x1b[H", chunk=3)
        self.type(s + "\r")

    def row(self, r):
        """One displayed row, through the machine's own VID_BASE.

        The machine knows where its screen is. This used to reach into
        `cool8vid._row_addr_v`, a private function, and work it out
        again -- so every harness that wanted the screen had to.
        """
        return self.m.row(r)

    def screen(self):
        return self.m.text()

    def find(self, text):
        for r, line in enumerate(self.screen()):
            if line.strip() == text:
                return r
        return -1

    def prog(self):
        """The stored program, decoded from memory -- the check that the
        lines really are tokenised and in order."""
        end = (self.m.bus.mem[self.syms_progend]
               | (self.m.bus.mem[self.syms_progend + 1] << 8))
        out, p = [], 0x0200
        while p < end:
            n = self.m.bus.mem[p] | (self.m.bus.mem[p + 1] << 8)
            ln = self.m.bus.mem[p + 2]
            out.append((n, bytes(self.m.bus.mem[p + 3:p + 3 + ln])))
            p += 4 + ln   # tokens, then the end-of-line zero
        return out


def main():
    print("  S1 -- sw/basic.bas, typed at")
    print()
    code, syms = build()
    print(f"  system: {len(code):,} bytes at ${ORG:04X}, "
          f"{len(code)/1024:.1f} KB of the 15.5 KB resident budget")
    print()

    M = Machine(code, syms)
    M.syms_progend = syms["v_progend"]
    M.settle()

    # ---- 1. it boots
    scr = M.screen()
    check(any("COOL8" in r for r in scr) and any("BYTES FREE" in r
                                                 for r in scr),
          "boots to a banner with a free-memory line",
          " | ".join(r for r in scr[:8] if r.strip())[:90])

    # ---- 2. numbered lines are stored, tokenised, in order
    M.type("20 PRINT 2\n10 PRINT 1\n30 PRINT 3\n")
    p = M.prog()
    check([n for n, _ in p] == [10, 20, 30],
          "numbered lines stored in ascending order, typed out of order",
          f"{[n for n, _ in p]}")
    check(all(b[0] >= 0x80 for _, b in p),
          "and tokenised -- PRINT is one byte",
          f"{[b[:4] for _, b in p]}")

    # ---- 3. LIST brings them back
    M.cmd("LIST")
    check(M.find("10 PRINT 1") >= 0 and M.find("20 PRINT 2") >= 0
          and M.find("30 PRINT 3") >= 0,
          "LIST detokenises them back in order",
          " | ".join(r for r in M.screen() if r.strip())[-90:])

    # ---- 4. the trick: edit a listed line in place
    #
    # Clear first, then LIST, so the row found is the listed one and not
    # the echo of what was typed earlier -- both are on screen and only
    # one of them is the thing under test.
    M.cmd("CLS")
    M.cmd("LIST")
    row = M.find("30 PRINT 3")
    cy = M.m.video.cur_y
    # One escape sequence per chunk: split across chunks the machine sees
    # a bare ESC and waits for the rest that is not there yet.
    M.type("\x1b[A" * (cy - row), chunk=3)
    M.type("\x1b[H", chunk=3)                  # Home: column 0
    before = M.row(row)
    M.type("30 PRINT 9")                       # type over it
    M.type("\r")                               # Return anywhere on the row
    p = dict(M.prog())
    # a literal is stored as T_NUM and two binary bytes now, not digits
    check(p.get(30, b"")[-3:] == bytes([0xA4, 9, 0]),
          "cursor up onto a listed line, retype, Return -- it is replaced",
          f"row {row} was {before!r}, is now {M.row(row)!r}; "
          f"line 30 is {p.get(30)!r}")
    check([n for n in sorted(p)] == [10, 20, 30],
          "and nothing else moved")

    # ---- 5. the cursor is where the typing is
    # Return moved the cursor off the edited row onto the blank one
    # below it, so there is nothing to step over first.
    M.type("PRINT")
    cx, cy = M.m.video.cur_x, M.m.video.cur_y
    check(M.row(cy)[:cx].endswith("PRINT"),
          f"the cursor is where the typing is (row {cy}, col {cx})",
          f"row {cy} = {M.row(cy)[:40]!r}")

    # ---- 6. commands
    M.type("\r")                               # abandon that line
    M.cmd("DELETE 20")
    check(sorted(dict(M.prog())) == [10, 30], "DELETE removes a line",
          f"{sorted(dict(M.prog()))}")
    M.cmd("RENUMBER 100,5")
    check(sorted(dict(M.prog())) == [100, 105], "RENUMBER renumbers",
          f"{sorted(dict(M.prog()))}")
    M.cmd("NEW")
    check(M.prog() == [], "NEW empties it")

    print()
    files(code, syms)

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


def blank(code, syms, label="PROGRAMS"):
    """A machine with a formatted drive 0 and nothing on it."""
    if os.path.exists(IMG):
        os.remove(IMG)
    img = disk.Image(IMG, create=True)
    disk.Volume(img, 0).format(label)
    img.save()
    M = Machine(code, syms, flash=IMG)
    M.syms_progend = syms["v_progend"]
    M.settle()
    return M


def files(code, syms):
    """S2 -- SAVE, LOAD, DIR, ERA, and running out of room.

    Everything here is typed. The PC-side tool `tools/cool8disk.py` is
    used only to make the volume and to read it back, which is the whole
    point of it existing: it is the same filesystem written twice, and a
    file written by one has to be readable by the other.
    """
    print("  S2 -- files")

    M = blank(code, syms)
    M.type("10 PRINT 1\n20 PRINT 2\n30 PRINT 3\n")
    wrote = M.prog()
    M.cmd('SAVE "TEST"')

    v = M.vol()
    e = v.find("TEST.BAS")
    check(e is not None and len(v.get("TEST.BAS")) ==
          sum(4 + len(b) for _, b in wrote),
          "SAVE writes the program, and the PC tool reads it back",
          f"entry {e}")

    # ---- NEW, then LOAD, and the program is the one that was saved
    M.cmd("NEW")
    M.cmd('LOAD "TEST"')
    check(M.prog() == wrote, "NEW, LOAD, and it is byte for byte the same",
          f"{[n for n, _ in M.prog()]} against {[n for n, _ in wrote]}")

    # ---- saving again appends a version and deletes the old entry
    M.type("40 PRINT 4\n")
    M.cmd('SAVE "TEST"')
    v = M.vol()
    live = [x for x in v.files() if x["name"].startswith(b"TEST")]
    dead = [x for x in v.entries() if x["status"] == 0]
    check(len(live) == 1 and len(dead) == 1
          and live[0]["page"] > dead[0]["page"],
          "SAVE again appends a new version and marks the old deleted",
          f"{len(live)} live, {len(dead)} deleted")
    want = b"".join(bytes((n & 255, n >> 8, len(b))) + b + bytes(1)
                    for n, b in M.prog())
    check(v.get("TEST.BAS") == want,
          "and the live one is the newer program, byte for byte",
          "a version programmed over unerased pages comes back as the "
          "two ANDed together, and only the bytes show it")

    # ---- DIR lists it
    M.cmd("CLS")
    M.cmd("DIR")
    scr = " ".join(M.screen())
    check("TEST    .BAS" in scr and "K FREE" in scr,
          "DIR lists the live file and the space left",
          " | ".join(r for r in M.screen() if r.strip())[:90])

    # ---- LOAD "n",line merges from a line number
    M.cmd("NEW")
    M.type("10 PRINT 9\n")
    M.cmd('LOAD "TEST",30')
    got = [n for n, _ in M.prog()]
    check(got == [10, 30, 40], "LOAD n,30 merges from line 30 on",
          f"{got}")
    check(dict(M.prog())[10][-3:] == bytes([0xA4, 9, 0]),
          "and the line already there is the typed one, not the file's",
          f"line 10 is {dict(M.prog())[10]!r}")

    # ---- ERA
    M.cmd('ERA "TEST"')
    v = M.vol()
    check(v.find("TEST.BAS") is None, "ERA removes it")
    M.cmd('LOAD "TEST"')
    check(any("FILE NOT FOUND" in r for r in M.screen()),
          "and loading it now gives ?FILE NOT FOUND ERROR",
          " | ".join(r for r in M.screen() if r.strip())[-70:])

    # ---- a full volume
    #
    # Filled from the PC side rather than by typing: 448 KB through the
    # machine's own SAVE is 51 million clocks of emulation to prove
    # something the last page proves just as well. What is tested is the
    # machine's check, and that runs either way.
    if os.path.exists(IMG):
        os.remove(IMG)
    img = disk.Image(IMG, create=True)
    vol = disk.Volume(img, 0)
    vol.format("FULL")
    filler = os.path.join(BUILD, "filler.bin")
    i = 0
    while True:
        room = disk.DATA_END - vol.free_offset()
        if not room:
            break
        n = min(room, 65280)                    # 255 whole pages at a time
        with open(filler, "wb") as fh:
            fh.write(b"\xA5" * n)
        vol.add(filler, f"F{i}.BIN")
        i += 1
    img.save()
    left = (disk.DATA_END
            - disk.Volume(disk.Image(IMG), 0).free_offset()) // 256
    M = Machine(code, syms, flash=IMG)
    M.syms_progend = syms["v_progend"]
    M.settle()
    M.type("10 PRINT 1\n")
    M.cmd('SAVE "TOOBIG"')
    check(any("DISK FULL" in r for r in M.screen()),
          f"a volume with {left} pages left gives ?DISK FULL ERROR",
          " | ".join(r for r in M.screen() if r.strip())[-70:])
    check(M.vol().find("TOOBIG.BAS") is None,
          "and nothing was written past the end of the volume")

    print()
    compact(code, syms)


def compact(code, syms):
    """COMPACT -- the only command that erases.

    The thing being proved is not just that the space comes back. It is
    that it comes back **without the machine borrowing memory it does
    not own**: the user's program stays in RAM and video RAM keeps the
    sprites and patterns that were in it. There is nowhere in RAM to put
    a 4 KB sector, so the scratch is on the disk.
    """
    print("  COMPACT")

    M = blank(code, syms)
    saved = {}
    for name, line in (("ONE", 1), ("TWO", 2), ("THREE", 3)):
        M.cmd("NEW")
        M.type(f"10 PRINT {line}\n20 PRINT {line}\n")
        M.cmd(f'SAVE "{name}"')
        saved[name] = M.vol().get(f"{name}.BAS")

    M.cmd('ERA "TWO"')
    before = M.vol()
    dead = [e for e in before.entries() if e["status"] == 0]
    check(len(dead) == 1 and before.find("THREE.BAS")["page"] == 18,
          "three files, the middle one deleted, THREE still at page 18",
          f"{[(e['name'], e['page']) for e in before.files()]}")

    # What must survive: a program in RAM, and a pattern in video RAM.
    M.cmd("NEW")
    M.type("10 PRINT 7\n")
    inram = M.prog()
    pattern = bytes((i * 7 + 13) & 0xFF for i in range(4096))
    M.m.video.vram[0x4000:0x5000] = pattern

    M.cmd("COMPACT")

    v = M.vol()
    check(v.find("THREE.BAS")["page"] == 17,
          "COMPACT slides THREE down onto the hole at page 17",
          f"{[(e['name'], e['page']) for e in v.files()]}")
    check(v.get("ONE.BAS") == saved["ONE"]
          and v.get("THREE.BAS") == saved["THREE"],
          "and both survivors come back byte for byte")
    check(v.find("TWO.BAS") is None
          and not [e for e in v.entries() if e["status"] == 0],
          "the deleted entry is gone, not just marked",
          f"{[e['status'] for e in v.entries()[:5]]}")
    check(v.label() == "PROGRAMS", "the volume label survives",
          f"label is {v.label()!r}")
    check(v.free_offset() == 18 * 256,
          "and the free pointer drops by the page that was freed",
          f"free at page {v.free_offset() // 256}")

    # The tail has to be $FF again: a program can only clear bits, so a
    # later SAVE onto stale bytes would come back as the two ANDed.
    img = disk.Image(IMG)
    tail = img.data[before.base + 18 * 256:before.base + disk.DATA_END]
    check(set(tail) == {0xFF},
          "everything above the live data is erased, ready to append",
          f"{len(tail) - tail.count(0xFF)} bytes are not $FF")

    check(M.prog() == inram, "the program in RAM is untouched",
          f"{[n for n, _ in M.prog()]} against {[n for n, _ in inram]}")
    check(bytes(M.m.video.vram[0x4000:0x5000]) == pattern,
          "and so is video RAM -- the scratch is on the disk")

    # And the volume still works afterwards.
    M.cmd('SAVE "FOUR"')
    check(M.vol().get("FOUR.BAS") is not None
          and M.vol().find("FOUR.BAS")["page"] == 18,
          "a SAVE after COMPACT lands in the reclaimed space",
          f"{[(e['name'], e['page']) for e in M.vol().files()]}")


if __name__ == "__main__":
    sys.exit(main())
