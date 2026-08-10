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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import cool8rsvm as vm                                   # noqa: E402
import cool8disk as disk                                 # noqa: E402

ROOT, BUILD = H.ROOT, H.BUILD
ORG = 0xA000
IMG = os.path.join(BUILD, "basic.img")
FAILS = H.FAILS


def build():
    return H.build_bas("basic.bas", org=ORG)


class Machine:
    def __init__(self, code, syms, flash=None, render=False):
        # render=True attaches the scanline renderer, so m.fb() answers
        # — for the checks that look at actual pixels.
        self.m = vm.Machine(flash_path=flash, render=render)
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
        # What every real boot guarantees before BASIC starts: the ROM
        # or the flash stub has cleared the screen to spaces. The
        # editor reads rows back, and a row padded with NULs instead of
        # spaces stores as a bloated record.
        self.m.bus.mem[0x8000:0xA000] = b"\x20\x07" * 0x1000
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
        #
        # The keyboard's own FIFO joined the list when sw/kbd.asm did,
        # and for the third time the same way: an empty ring stopped
        # meaning an empty *input*, so `key()` returned with six raw
        # scancodes still sitting in the PS/2 FIFO and the screen
        # unchanged. Every place a byte can be waiting has to be in this
        # condition or the harness is settling on a machine that is not
        # finished.
        self.irhead = syms["irhead"]
        self.irtail = syms["irtail"]

    def settle(self, budget=80_000_000):
        # The idle test lives on the machine now (m.settle) — it polls
        # per instruction, which must not cross the fast machine's
        # process boundary one tick at a time. Same loop, same
        # condition, whichever machine is underneath.
        if not self.m.settle(self.idle, self.irhead, self.irtail, budget):
            raise SystemExit("the machine never went idle")

    def type(self, text, chunk=8):
        data = text.replace("\n", "\r").encode("latin-1")
        for i in range(0, len(data), chunk):
            self.m.uart.feed(data[i:i + chunk])
            self.settle()
            if self.m.uart.overrun:
                raise SystemExit("the FIFO overran")

    def key(self, text):
        """Type at the keyboard rather than at the serial port.

        A character at a time, because a make and a break and possibly a
        shift round them is up to six bytes of a 16-byte FIFO, and
        because a person cannot press two keys at once by typing. Held
        keys are `m.scancode()`, which is deliberately not this.
        """
        for ch in text:
            self.m.key([ch])
            self.settle()
            if self.m.kbd.overrun:
                raise SystemExit("the keyboard FIFO overran")

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
        # Under the C64 key law, Home is 0,0 and DOWN at the bottom
        # SCROLLS -- so Home first, then exactly to the bottom row.
        self.type("\x1b[H", chunk=3)
        self.type("\x1b[B" * 29, chunk=3)
        self.type(s + "\r")

    def row(self, r):
        """One row of the text screen, from wherever the machine keeps
        the truth.

        In the text modes that is the display itself, read through the
        machine's own VID_BASE as always. In the tile and bitmap modes
        the display shows the *mirror* -- reading it through VID_BASE
        returns bitmap bytes -- and the text lives only in the cell
        map at $8000, the 128x32 truth the editor edits in every mode
        (docs/13-basic.md section 4). That map is an architectural
        invariant, not a harness guess at an address: a program that
        ends in MODE 4 leaves its PRINT output there, and nowhere
        readable else.
        """
        if self.m.video.ctrl & 3 == 0:
            return self.m.row(r)
        base = 0x8000 + ((r & 31) << 8)
        return "".join(chr(self.m.bus.mem[base + 2 * c])
                       for c in range(80)).replace("\x00", " ").rstrip()

    def screen(self):
        return [self.row(r) for r in range(32)]

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

    # ---- 1. it boots. The banner is the flash stub's job now --
    # sim/test_boot_basic.py checks it on the path a board takes; this
    # harness pokes the image in with no stub, so booting means the
    # editor is up and idle with a cursor, on a screen it did not paint.
    check(M.m.cpu.pc == syms["s_rawkey.rk0"],
          "boots to the editor, idle at the key loop")

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
    # One escape sequence per chunk: split across chunks the machine sees
    # a bare ESC and waits for the rest that is not there yet. Home is
    # 0,0 under the C64 law, so: home, then down to the listed row.
    M.type("\x1b[H", chunk=3)
    M.type("\x1b[B" * row, chunk=3)
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

    # ---- 5b. direct mode: a statement with no number runs on the
    # spot, and variables survive between statements -- the C64's
    # direct mode with the BBC's manners (one dispatch, no refusals).
    M.cmd("PRINT 314 + 1")
    check(any(r.strip() == "315" for r in M.screen()),
          "a direct PRINT executes on the spot")
    M.cmd("Q = 21")
    M.cmd("PRINT Q * 2")
    check(any(r.strip() == "42" for r in M.screen()),
          "and variables persist between direct lines")
    M.cmd("FOO 9")
    check(any(r.strip() == "?SYNTAX" for r in M.screen()),
          "junk is still ?SYNTAX, with no line number")

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

    # ---- 6b. direct mode against a program: persistence and resume
    M.cmd("10 W = 123")
    M.cmd("20 PRINT 777")
    M.cmd("30 END")
    M.cmd("RUN")
    M.cmd("PRINT W")
    check(any(r.strip() == "123" for r in M.screen()),
          "a variable the program set survives into direct mode")
    M.cmd("GOTO 20")
    n = sum(1 for r in M.screen() if r.strip() == "777")
    check(n >= 2, "and a direct GOTO resumes the program", f"saw {n}")
    M.cmd("NEW")

    print()
    files(code, syms)

    return H.report()


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
    check(any("NO FILE" in r for r in M.screen()),
          "and loading it now gives ?NO FILE",
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

    # ---- the AT forms: raw bytes, the BBC's *SAVE and *LOAD inside
    # the language. A poked marker, saved, zeroed, loaded back.
    M.cmd("POKE $6000, 201")
    M.cmd('SAVE "RAW" AT $6000, 8')
    M.cmd("POKE $6000, 0")
    M.cmd('LOAD "RAW" AT $6000')
    M.cmd("PRINT PEEK($6000)")
    check(any(r.strip() == "201" for r in M.screen()),
          "SAVE AT / LOAD AT round-trips raw bytes through flash")

    # ---- chaining: LOAD inside a running program replaces it and
    # continues at the new first line, variables kept.
    M.cmd("NEW")
    M.cmd("10 PRINT 4442")
    M.cmd("20 END")
    M.cmd('SAVE "PT2"')
    M.cmd("NEW")
    M.cmd("10 V = 66")
    M.cmd("20 PRINT 4441")
    M.cmd('30 LOAD "PT2"')
    M.cmd("40 PRINT 4449")
    M.cmd("RUN")
    scr = [r.strip() for r in M.screen()]
    check("4441" in scr and "4442" in scr and "4449" not in scr,
          "a program LOAD chains into the new program",
          " | ".join(r for r in scr if r.startswith("444")))
    M.cmd("PRINT V")
    check(any(r.strip() == "66" for r in M.screen()),
          "with variables carried across the chain")


if __name__ == "__main__":
    sys.exit(main())
