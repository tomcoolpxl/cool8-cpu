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
  commands    NEW empties it, DELETE removes a range, RENUM renumbers

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

import harness as H
import memmap                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import cool8rsvm as vm                                   # noqa: E402
import cool8disk as disk                                 # noqa: E402

ROOT, BUILD = H.ROOT, H.BUILD
ORG = memmap.ORG
IMG = os.path.join(BUILD, "basic.img")
FAILS = H.FAILS


def build():
    # The system is sw/main.asm now, not compiled BASIC ([D68]).
    #
    # **sw/org.asm and sw/sysbot.asm are inputs to this assembly and
    # derived from it**, so they are made current here rather than by
    # whichever `build` job happened to run first. Without this, a
    # change to the size of BASIC failed `poe build` once and passed on
    # the next run, with an error that named neither the size nor the
    # ordering. memmap.ensure() writes only what actually moved.
    #
    # ORG is re-read afterwards because it is captured at import: a
    # module that loaded before the origin moved would go on loading the
    # image at the old address, which is the same class of fault one
    # level up.
    global ORG
    memmap.ensure()
    ORG = memmap.ORG
    return H.assemble(os.path.join(H.SW, "main.asm"), name="basic",
                      lower=True, write=True)


class Machine:
    def __init__(self, code, syms, flash=None, render=False):
        # render=True attaches the scanline renderer, so m.fb() answers
        # — for the checks that look at actual pixels.
        self.cstride = syms["cstride"]
        self.cscrn = syms["cscrn"]
        self.sym_ctop = syms["ctop"]
        self.m = vm.Machine(flash_path=flash, render=render)
        self.m.bus.mem[ORG:ORG + len(code)] = code
        self.m.cpu.pc = syms["main"]
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
        # The map, wherever the image put it. [D69] moved it above the
        # user's region, so clearing $8000 cleared program space and
        # left the real map full of NULs -- which `ed_read` cannot trim,
        # so an eight-character line stored as a seventy-five byte one.
        scrn, cs = syms["cscrn"], syms["cstride"]
        self.m.bus.mem[scrn:scrn + cs * 32] = b" " * (cs * 16)
        # rawkey's `.rk0` is reached only when nothing is waiting, so it
        # is the one address that means "idle" rather than "busy".
        self.idle = syms["in_raw.rk0"]
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
        # con_row, in Python, and the two numbers come out of the
        # image: displayed row r is map row (CTOP + r) AND 31, and a
        # map row is CSTRIDE bytes. This was `((r & 31) << 8)` -- a
        # 256-byte row and no CTOP at all, so it read the right rows
        # only on a screen that had never scrolled, and could not
        # follow the map when the console stopped using 256.
        top = self.m.bus.mem[self.sym_ctop]
        base = self.cscrn + ((top + r) & 31) * self.cstride
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


def trace(label, text, n=40, into=True):
    """`python sim/test_basic.py --trace s_putn "PRINT 0 - 7" [n]`

    Boot the editor, break at `label`, type `text`, and print what the
    machine executed from there. **The editor had no way in.** When
    `s_putn` moved to hand assembly in sw/ed.asm and printing broke,
    the only tools to hand were re-running the suite and reading the
    source -- which is the bisect-by-rerun AGENTS.md names, and it took
    a round. A breakpoint says where it stopped; this says what it did.

    `--over` steps over CALLs, so one routine's shape is not buried
    under the editor's screen routines.
    """
    code, syms = build()
    # **`-` as the label means "I do not know where it is."** Type the
    # lines, let it run, and trace from wherever the PC ended up. That
    # is the question a hang actually asks, and a breakpoint cannot
    # answer it, because not knowing where to put one is the problem.
    # Several lines may be given, separated by `;`.
    if label != "-" and label not in syms:
        raise SystemExit("no symbol %r" % label)
    M = Machine(code, syms)
    M.syms_progend = syms["progend"]
    M.settle()
    if label != "-":
        M.m.breakpoints.add(syms[label])
    why = None
    for part in text.split(";"):
        # `!` prefix drives it the way the suites do -- through `cmd`,
        # which settles after every chunk -- so a settle that never
        # succeeds fails here, on the input that caused it, instead of
        # forty million cycles later with no idea which line it was.
        if part.startswith("!"):
            try:
                M.cmd(part[1:])
            except SystemExit as e:
                print("  settle failed on %r: %s" % (part[1:], e))
                print("  pc now $%04X, sp $%04X" % (M.m.cpu.pc, M.m.cpu.sp))
                print()
                print(M.m.trace_report(M.m.trace(n, syms, into=into)))
                return 1
            why = "settled"
            continue
        M.m.type(part + "\r")
        why = M.m.run(cycles=40_000_000)
        if why == "breakpoint":
            break
    print("  %s, %s" % (text, ("breaking at %s ($%04X)"
                               % (label, syms[label])) if label != "-"
                        else "run until it stopped"))
    print("  run -> %s, pc now $%04X" % (why, M.m.cpu.pc))
    print()
    if label != "-" and why != "breakpoint":
        print("  never reached it")
        return 1
    print(M.m.trace_report(M.m.trace(n, syms, into=into)))
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--trace":
        into = "--over" not in sys.argv
        rest = [a for a in sys.argv[2:] if a != "--over"]
        return trace(rest[0], rest[1],
                     int(rest[2]) if len(rest) > 2 else 40, into)
    print("  S1 -- sw/basic.bas, typed at")
    print()
    code, syms = build()
    print(f"  system: {len(code):,} bytes at ${ORG:04X}, "
          f"{len(code)/1024:.1f} KB of the 15.5 KB resident budget")
    print()

    M = Machine(code, syms)
    M.syms_progend = syms["progend"]
    M.settle()

    # ---- 1. it boots. The banner is the flash stub's job now --
    # sim/test_boot_basic.py checks it on the path a board takes; this
    # harness pokes the image in with no stub, so booting means the
    # editor is up and idle with a cursor, on a screen it did not paint.
    check(M.m.cpu.pc == syms["in_raw.rk0"],
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

    # ---- 2b. the line number itself, which `number()` parses.
    #
    # Characterised before that routine moves to assembly ([D66]): the
    # shared parser `snum` handles a decimal point and this one stops
    # at it, so "10.5" is the case where a careless port would change
    # the language. Pinned at what the editor does today.
    M.cmd("NEW")
    M.type("  40 PRINT 4\n")
    check([n for n, _ in M.prog()] == [40],
          "leading spaces before a line number are skipped",
          "%s" % [n for n, _ in M.prog()])

    M.cmd("NEW")
    M.type("30000 PRINT 5\n")
    check([n for n, _ in M.prog()] == [30000],
          "a line number near the top of the range",
          "%s" % [n for n, _ in M.prog()])

    M.cmd("NEW")
    M.type("10.5 PRINT 6\n")
    got = [n for n, _ in M.prog()]
    check(got == [10], "a number stops at a decimal point -- line 10",
          "%s" % got)

    # Put back exactly what section 2 left, because everything below
    # reads that program. A characterisation block dropped into the
    # middle of a suite has to leave the state it found.
    M.cmd("NEW")
    M.type("20 PRINT 2\n10 PRINT 1\n30 PRINT 3\n")

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

    # ---- the number printer itself, which is `s_putn` in sw/ed.asm:
    # hand assembly where the rest of the editor is compiled BASIC.
    #
    # **The sign path is what these are really for.** `s_emit` is a
    # compiled SUB, so its argument travels on the stack -- calling it
    # with the character in a register emits whatever happened to be
    # pushed last. The first version of s_putn did exactly that and the
    # minus sign came out as the low byte of the value, which is a fault
    # only a negative number reveals. Zero is here because the digit
    # loop divides before it tests, and -32768 because the magnitude of
    # the most negative number is itself.
    for text, want in (("PRINT 7", "7"),
                       ("PRINT 0", "0"),
                       ("PRINT 0 - 7", "-7"),
                       ("PRINT 30000", "30000"),
                       ("PRINT 0 - 32768", "-32768")):
        M.cmd(text)
        check(any(r.strip() == want for r in M.screen()),
              f"{text} prints {want}",
              " | ".join(r.strip() for r in M.screen() if r.strip())[-60:])
    M.cmd("FOO 9")
    check(any(r.strip() == "?SYNTAX" for r in M.screen()),
          "junk is still ?SYNTAX, with no line number")

    # ---- 6. commands
    M.type("\r")                               # abandon that line
    M.cmd("DELETE 20")
    check(sorted(dict(M.prog())) == [10, 30], "DELETE removes a line",
          f"{sorted(dict(M.prog()))}")
    M.cmd("RENUM 100,5")
    check(sorted(dict(M.prog())) == [100, 105], "RENUM renumbers",
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
    M.syms_progend = syms["progend"]
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
    M.syms_progend = syms["progend"]
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

    # ---- variables live across direct lines, and die when they should.
    #
    # A-Z are resident; everything else -- arrays, strings, floats, long
    # names -- lives in the name table, based at PROGEND, with the heap
    # coming down from the top. Both were being reset before *every*
    # direct line: `main_pre` reset HEAP and `idrct` reset NNAME, which
    # between them is exactly the variable clear `idrct` documents
    # itself as leaving out. `DIM Q(4)` then `Q(2)=77` on the next line
    # answered ?INDEX; `A$="HI"` then `PRINT A$` printed nothing. Only
    # A-Z survived, so the fault was invisible to anyone using integers.
    M.cmd("NEW")
    M.cmd("CLS")
    M.cmd("DIM Q(4)")
    M.cmd("Q(2)=77")
    M.cmd("PRINT Q(2)")
    check(any(r.strip() == "77" for r in M.screen()),
          "an array survives from one direct line to the next",
          " | ".join(r.strip() for r in M.screen() if r.strip())[:90])
    M.cmd('A$="HI"')
    M.cmd("A#=1.5")
    M.cmd("TOT=9")
    M.cmd("PRINT A$")
    M.cmd("PRINT A#")
    M.cmd("PRINT TOT")
    scr = [r.strip() for r in M.screen()]
    check("HI" in scr and "1.5" in scr and "9" in scr,
          "...and so do strings, floats and long names",
          " | ".join(r for r in scr if r)[:90])

    # The other half: the clear still has to happen where it always did.
    # The name table is based at PROGEND, so editing the program moves
    # it and every entry indexed off the old base would be read out of
    # the new one -- which is why the C64 clears variables when you type
    # a program line, and why this does too.
    for after in ("NEW", "RUN", "10 PRINT 1"):
        M.cmd("NEW")
        M.cmd('A$="KEEP"')
        M.cmd(after)
        # CLS *after* the clearing command, so what is on the screen is
        # only what PRINT put there -- scanning the whole screen also
        # finds the echo of the line that set it.
        M.cmd("CLS")
        M.cmd("PRINT A$")
        scr = [r.strip() for r in M.screen() if r.strip()]
        check("KEEP" not in scr,
              "%-11s clears the variables" % after,
              " | ".join(scr)[:80])

    # ---- a SUB returns when execution reaches END SUB.
    #
    # It used to end the whole program: a SUB returned only through
    # RETURN, and `END SUB` was a marker h_sub scanned for when stepping
    # over a definition, so reaching one ran END and set E_DONE. The
    # answer was already printed, so it looked like it worked.
    M.cmd("NEW")
    M.cmd("CLS")
    for l in ("10 CALL F", "20 PRINT 222", "30 END", "40 SUB F",
              "50 PRINT 111", "60 END SUB"):
        M.cmd(l)
    M.cmd("RUN")
    scr = [r.strip() for r in M.screen()]
    check("111" in scr and "222" in scr,
          "falling into END SUB returns, it does not stop the program",
          " | ".join(r for r in scr if r)[-60:])
    M.cmd("NEW")
    M.cmd("CLS")
    for l in ("10 PRINT 111", "20 END", "30 PRINT 222"):
        M.cmd(l)
    M.cmd("RUN")
    scr = [r.strip() for r in M.screen()]
    check("111" in scr and "222" not in scr,
          "...and a bare END still stops it",
          " | ".join(r for r in scr if r)[-60:])

    # ---- DIM: up to three dimensions, three element types ([D71]).
    #
    # The element type is the name's suffix, which costs nothing to
    # parse because `arrname` appends '(' to the scanned name: A(, A#(
    # and A$( were already three different keys in the name table.
    M.cmd("NEW")
    M.cmd("CLS")
    for line, want, why in [
        ("DIM A(5)",        None, None),
        ("A(2)=77",         None, None),
        ("PRINT A(2)",      "77", "a one-dimensional integer array"),
        ("DIM B(2,3)",      None, None),
        ("B(1,2)=42",       None, None),
        ("PRINT B(1,2)",    "42", "two dimensions"),
        ("DIM C(1,1,1)",    None, None),
        ("C(1,1,1)=9",      None, None),
        ("PRINT C(1,1,1)",  "9",  "three, which is the cap"),
        ("DIM F#(3)",       None, None),
        ("F#(1)=1.5",       None, None),
        ("PRINT F#(1)",     "1.5", "float elements, three bytes each"),
        ("DIM S$(3)",       None, None),
        ('S$(1)="HI"',      None, None),
        ("PRINT S$(1)",     "HI", "string elements, a descriptor each"),
        ("DIM G#(2,2)",     None, None),
        ("G#(1,1)=2.25",    None, None),
        ("PRINT G#(1,1)",   "2.25", "and both at once"),
    ]:
        M.cmd(line)
        if want is not None:
            check(any(r.strip() == want for r in M.screen()), why,
                  " | ".join(r.strip() for r in M.screen() if r.strip())[-70:])

    # `aelem` keeps its whole working set on the CPU stack because this
    # nests: the outer call has parsed nothing when the inner one runs.
    M.cmd("A(0)=3")
    M.cmd("A(3)=1")
    M.cmd("PRINT A(A(0))")
    check(any(r.strip() == "1" for r in M.screen()),
          "a subscript that is itself a subscripted read",
          " | ".join(r.strip() for r in M.screen() if r.strip())[-60:])

    # Corners of a two-dimensional array must not alias, which is the
    # check that would fail if the Horner flattening were wrong.
    M.cmd("NEW")
    M.cmd("DIM D(2,2)")
    M.cmd("D(0,0)=7")
    M.cmd("D(2,2)=8")
    M.cmd("CLS")
    M.cmd("PRINT D(0,0)")
    check(any(r.strip() == "7" for r in M.screen()),
          "opposite corners of a 2-D array are different elements",
          " | ".join(r.strip() for r in M.screen() if r.strip())[:60])

    for lines, want, why in [
        (["DIM A(5)", "PRINT A(99)"],  "?INDEX", "a subscript past the bound"),
        (["DIM A(5)", "PRINT A(-1)"],  "?INDEX", "a negative subscript"),
        (["PRINT Q(1)"],               "?INDEX", "an array never dimensioned"),
        (["DIM B(2,3)", "PRINT B(1)"], "?INDEX", "too few subscripts"),
        (["DIM A(5)", "DIM A(5)"],     "?REDIM", "dimensioned twice"),
        # 400*400 elements is 160,000, which wraps a 16-bit product to a
        # block far smaller than the bounds then range-check against --
        # every write past the wrap would land on the next thing in the
        # heap. DIM checks the product rather than discovering it later.
        (["DIM Z(400,400)"],      "?OUT OF MEM", "a product that overflows"),
    ]:
        M.cmd("NEW")
        M.cmd("CLS")
        for l in lines:
            M.cmd(l)
        check(any(r.strip() == want for r in M.screen()), why,
              " | ".join(r.strip() for r in M.screen() if r.strip())[:70])

    # ---- a direct statement ends after itself.
    #
    # **The answer alone, and nothing after it.** The statement loop's
    # inlined `nextline` asked whether the record just run was the
    # staged direct line *after* advancing LREC to the next one, so it
    # tested the page it was moving to. DIRBUF is at $B5FA, six bytes
    # below the boundary, so `PRINT 6` ends on the next page and the
    # test missed: LREC walked up through memory four bytes at a time
    # until it reached the image and tried to run it. Every direct
    # statement that parsed an expression printed its answer and then
    # `?SYNTAX`, which reads like a parser bug and was a record bug.
    #
    # Checked with a statement that produces output and one that does
    # not, because the fault is in what happens *after* either.
    M.cmd("NEW")
    M.cmd("CLS")
    for line in ("PRINT 6*7", 'PRINT "HI"', "POKE 0,0", "MODE 0", "A=5"):
        M.cmd(line)
    scr = [r.strip() for r in M.screen() if r.strip()]
    check("?SYNTAX" not in scr,
          "a direct statement stops at the end of its own record",
          " | ".join(scr))
    check("42" in scr and "HI" in scr,
          "...and still produces its answer",
          " | ".join(scr))


if __name__ == "__main__":
    sys.exit(main())
