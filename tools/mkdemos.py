#!/usr/bin/env python3
"""Build the demo disc: every `demos/*.bas` onto drive 13, every
`demos/*.act` compiled onto drive 11, the machine-code systems and
their stubs onto drive 14.

    python tools/mkdemos.py [--img PATH] [--png NAME]

**Three drives, one per menu, split by language** (`cool8disk.MENUS`):
a program written in BASIC is a Demo on 13, games included; the
Z-Machine games and the p-System's loader are Software on 14, each a
`.BIN` behind a `.BAS` stub that sets the drive and `SYS`es it; and a
CoolAction! source is compiled behind `sw/libaction.act` and placed as
a bare `.BIN` on 11 -- no stub, started by `SYS "NAME.BIN"`. RAINBOW
and COBRA exist on both 11 and 13, which is the point: the two menus
are how the interpreter and the compiler get compared.

**The machine is booted, not poked.** `BOOT.BIN` goes on drive 0 and the
ROM autoboots it, which is `poe emu` without a window -- because the boot
stub is what uploads the fonts into VRAM and a text demo drawn on a
machine that never booted is a blue screen with nothing on it. That is
not a hypothetical: the first version of this script poked the image in
and jumped to `main`, and the first text demo rendered blank.

**The programs are typed at the machine, not written by this script.** A
program on disc is tokenised, and the only thing that knows the token
table is `sw/token.asm`; a host-side tokeniser would be a second
implementation of it and would drift the first time a keyword was added.
So the sources in `demos/` are the truth and the disc is derived.

Drive 15 is the p-System's own volume and not a menu. See
[docs/14-demos.md](../docs/14-demos.md).
"""

import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))
sys.path.insert(0, HERE)

import harness as H                                      # noqa: E402
import cool8disk as disk                                 # noqa: E402
import cool8rsvm as vm                                   # noqa: E402
import memmap                                            # noqa: E402
import mkboot                                            # noqa: E402
import test_basic as B                                   # noqa: E402

DEMOS = os.path.join(ROOT, "demos")
DRIVE = disk.DEMO_VOL     # the layout is cool8disk's, not written twice

# The machine-code systems: (menu name, story file, 5-byte tag, .BIN,
# story chunks, text attr, status attr, border, save name). Each has a
# stub `demos/<name>.bas` that goes on the Software drive beside it,
# and nowhere else -- a stub typed onto the demo drive would be a Demo
# that SYSes a file that is not there.
ADVENTURES = [
    ("HHGG", "hhgg.z3", b"HHGG0", "HHGG.BIN", ["HHGG0.DAT", "HHGG1.DAT"], 0x1F, 0xF1, 0x01, b"HHGG    SAV"),
    ("ZORK1", "zork1.z3", b"ZORK0", "ZORK1.BIN", ["ZORK0.DAT", "ZORK1.DAT"], 0x0E, 0xE0, 0x00, b"ZORK1   SAV"),
    ("PLANET", "planetfall.z3", b"PLAN0", "PLANET.BIN", ["PLAN0.DAT", "PLAN1.DAT"], 0x07, 0x70, 0x00, b"PLANET  SAV"),
    ("LGOP", "lgop.z3", b"LGOP0", "LGOP.BIN", ["LGOP0.DAT", "LGOP1.DAT"], 0x87, 0x78, 0x08, b"LGOP    SAV"),
]
SOFTWARE = [a[0].lower() + ".bas" for a in ADVENTURES] + ["pascal.bas"]


def sources():
    """The BASIC demos: every `demos/*.bas` that is not a Software stub."""
    return sorted(f for f in os.listdir(DEMOS)
                  if f.endswith(".bas") and f not in SOFTWARE)


def actions():
    """The CoolAction! demos, compiled: `demos/*.act`."""
    return sorted(f for f in os.listdir(DEMOS) if f.endswith(".act"))


def discname(f):
    name = os.path.splitext(f)[0].upper()
    if name == "COOLTRIS1":
        return "COOLTRS1"
    if name == "COOLTRIS2":
        return "COOLTRS2"
    if name == "MSCOOLMAN":
        return "MSCOOLMN"
    return name[:8]


def volume(imgpath, code):
    """Drive 0 bootable, drive 13 the demo disc, the rest the user's."""
    # **Write what `build` returned, do not add the BOOT.BIN lying in the
    # build directory.** `mkboot.build` returns the bytes and writes no
    # file; only tools/flash.py writes BOOT.BIN. Adding that path instead
    # boots whatever the last `poe disk` left there, so a source change
    # is typed at hours-old firmware and the machine looks buggy rather
    # than stale -- which is the trap flash.py names in its own comment,
    # and it cost a session here before this line existed.
    boot = mkboot.build(code, dest=memmap.ORG, build_dir=H.BUILD)
    bootpath = os.path.join(H.BUILD, "BOOT.BIN")
    with open(bootpath, "wb") as fh:
        fh.write(boot)
    disk.make_image(imgpath, bootbin=bootpath)   # the layout is shared
    return len(boot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default=os.path.join(H.BUILD, "demos.img"))
    ap.add_argument("--png", metavar="NAME", nargs="?", const="",
                    help="run this demo (default the first) and shoot it")
    ap.add_argument("--no-shots", action="store_true",
                    help="build the disc and stop -- no demo is run and no "
                         "picture taken, which is minutes rather than one")
    args = ap.parse_args()

    code, syms = B.build()
    n = volume(args.img, code)
    print("  16 volumes; drive 0 bootable (BOOT.BIN {:,}), drive {} is "
          "DEMOS".format(n, DRIVE))

    # **Bad Apple's chunks go in before the machine boots.** They used
    # to be written into the image file while the machine was running;
    # the machine's own flash never held them, so the `flush()` after
    # `SAVE "BAPPLE"` put the pre-chunk flash back over the file and
    # left erased $FF where the stream had just been placed. The stub
    # played confetti from a disc whose placement assertions had all
    # passed. Placed first, the chunks ride inside the machine's flash
    # from boot and every later flush carries them.
    bap = os.path.join(DEMOS, "bapple")
    manp = os.path.join(bap, "manifest.json")
    man = None
    if os.path.exists(manp):
        import json
        with open(manp) as fh:
            man = json.load(fh)
        im = disk.Image(args.img)
        for e in man:
            # **No chunk on a drive something owns.** The cap to drive
            # 12 lived only in a gitignored manifest for a round while
            # the generator still planned twelve drives down to 1 --
            # USER_VOL, where a cold machine comes up. The planner
            # refuses those drives now, and this catches a manifest
            # from before it did.
            assert e["drive"] not in disk.CLAIMED, (
                "chunk %s is planned for drive %d, which is %s's"
                % (e["name"], e["drive"], disk.labels()[e["drive"]]))
            vol = disk.Volume(im, e["drive"])
            off = vol.free_offset()
            assert vol.base + off == e["addr"], (
                "chunk %s: predicted $%06X, placed $%06X"
                % (e["name"], e["addr"], vol.base + off))
            vol.add(os.path.join(bap, e["name"]), e["name"])
        im.save()

    # **The Z-Machine interpreter and the stories go onto the Software
    # drive**, every one of them: the interpreter scans drive 14 for the
    # story tag first and 13 second (sw/z3/z3.asm `.scan_vols`), so 14
    # is where it looks first and where saves land.
    im = disk.Image(args.img)
    z3_src = os.path.join(ROOT, "sw", "z3", "z3.asm")
    if os.path.exists(z3_src):
        z3_code, z3_syms = H.assemble(z3_src)
        tag_off = z3_syms["z_story_tag"] - 0x0200
        attr_off = z3_syms["z_color_attr"] - 0x0200
        stat_off = z3_syms["z_color_status"] - 0x0200
        bord_off = z3_syms["z_color_border"] - 0x0200
        sav_off = z3_syms["z_save_filename"] - 0x0200

        vol_id = disk.SOFTWARE_VOL
        for name, story_fn, tag_bytes, bin_fn, chunks, cattr, cstat, cbord, sav_bytes in ADVENTURES:
            story_path = os.path.join(ROOT, "z3", "games", story_fn)
            if not os.path.exists(story_path):
                continue

            game_code = bytearray(z3_code)
            for i in range(len(tag_bytes)):
                game_code[tag_off + i] = tag_bytes[i]
            game_code[tag_off + len(tag_bytes)] = 0
            for i in range(11):
                game_code[sav_off + i] = sav_bytes[i]
            game_code[attr_off] = cattr
            game_code[stat_off] = cstat
            game_code[bord_off] = cbord

            prg = bytes([0x00, 0x02]) + bytes(game_code)
            prg_path = os.path.join(H.BUILD, bin_fn)
            with open(prg_path, "wb") as fh:
                fh.write(prg)

            with open(story_path, "rb") as fh:
                story_bytes = fh.read()

            chunk_size = 65280
            parts = [(chunks[0], story_bytes[:chunk_size])]
            if len(story_bytes) > chunk_size:
                parts.append((chunks[1], story_bytes[chunk_size:]))

            # **The loader goes on the Software drive; the story goes
            # there too if it fits, and onto the demo drive if not.**
            # The four stories are 438,218 bytes against 454,656 usable
            # a volume, before the five loaders, so one of them cannot
            # be on 14 -- and does not need to be: the interpreter
            # finds its story by scanning 14 and then 13 for the tag
            # (sw/z3/z3.asm `.scan_vols`), and saves beside it. The
            # stub's `DRIVE 14` is for the `.BIN`, which must be where
            # the stub is.
            vol = disk.Volume(im, vol_id)
            vol.add(prg_path, bin_fn)
            need = sum((len(b) + 255) & ~255 for _, b in parts)
            story_vol = vol_id
            if disk.DATA_END - vol.free_offset() < need:
                story_vol = disk.DEMO_VOL
                vol = disk.Volume(im, story_vol)
            for nm, blob in parts:
                p = os.path.join(H.BUILD, nm)
                with open(p, "wb") as fh:
                    fh.write(blob)
                vol.add(p, nm)

            print("  placed %-10s (%d bytes binary on drive %d, %d bytes story on drive %d)"
                  % (name, len(prg), vol_id, len(story_bytes), story_vol))

    # **The p-System's loader onto the Software drive; its own volume
    # is drive 15.**
    pascal_src = os.path.join(ROOT, "sw", "pascal", "pascal.asm")
    if os.path.exists(pascal_src):
        pas_code, _ = H.assemble(pascal_src, name="pascal", write=True)
        pas_prg = bytes([0x00, 0x02]) + bytes(pas_code)
        pas_prg_path = os.path.join(H.BUILD, "PASCAL.PRG")
        with open(pas_prg_path, "wb") as fh:
            fh.write(pas_prg)
        disk.Volume(im, disk.SOFTWARE_VOL).add(pas_prg_path, "PASCAL.BIN")

        vol_path = os.path.join(ROOT, "tools", "ucsd-psystem-vm", "disk-images", "system.vol")
        if os.path.exists(vol_path):
            with open(vol_path, "rb") as fh:
                system_vol = fh.read()
            v15_offset = disk.vol_base(disk.PASCAL_VOL)
            im.data[v15_offset:v15_offset + len(system_vol)] = system_vol
            print("  placed PASCAL.BIN on drive %d, system.vol (%d bytes) on drive %d"
                  % (disk.SOFTWARE_VOL, len(system_vol), disk.PASCAL_VOL))

    # **The CoolAction! demos, compiled onto drive 11.** A bare `.BIN`
    # each -- the PRG carries its own load address (D87), so `SYS
    # "NAME.BIN"` is the whole launch and there is no stub to type.
    # Behind the library, which is two files in a fixed order
    # (H.ACT_LIB); the compiler is built by the harness on the way.
    vol11 = disk.Volume(im, disk.ACTION_VOL)
    for f in actions():
        nm = discname(f)
        srcs = H.act_sources(os.path.join("demos", f))
        if srcs is None:
            # a program whose parts are private and not on this machine
            # (Ms. Cool-Man's ripped art): the manifest says which
            print("  %s: a part named in demos/%s.parts is not here, so it is not on the disc"
                  % (f, os.path.splitext(f)[0]))
            continue
        prg, _ = H.build_act(srcs, "disc_" + nm.lower())
        p = os.path.join(H.BUILD, nm + ".BIN")
        with open(p, "wb") as fh:
            fh.write(prg)
        vol11.add(p, nm + ".BIN")
        print("  compiled %-16s %6d bytes -> drive %d as %s.BIN"
              % (f, len(prg), disk.ACTION_VOL, nm))

    im.save()

    m = vm.boot(flash_path=args.img, render=True)
    for _ in range(90):
        m.run_frame()
    H.settle(m, syms)
    H.key(m, syms, "DRIVE %d\r" % DRIVE)

    for f in sources():
        H.key(m, syms, "NEW\r")
        # **`H.line`, not `H.key`: a round trip a line, not a
        # character.** The machine still tokenises every one of them --
        # the text goes where `ed_read` would have left it and the
        # machine enters `ed_inject`, so `sw/token.asm` is still the only
        # thing that knows a keyword and section 2 above still holds. The
        # disc came out byte-for-byte identical either way, floats
        # included, which is the gate `sim/test_run.py` now keeps.
        #
        # Typing five demos was ninety seconds, nearly all of it waiting
        # for the PS/2 queue: it is sixteen deep and a key is two
        # scancodes, so a line cannot be delivered in one go.
        for line in io.open(os.path.join(DEMOS, f),
                            encoding="utf-8").read().splitlines():
            if line.strip():
                H.line(m, syms, line)
        H.key(m, syms, 'SAVE "%s"\r' % discname(f))
        print("  typed and saved %-16s as %s" % (f, discname(f)))

    # **The Software stubs, on the Software drive and only there** --
    # each beside the `.BIN` it SYSes, and only when that `.BIN` was
    # placed: a stub whose system is missing would be a menu entry that
    # fails at the SYS.
    H.key(m, syms, "DRIVE %d\r" % disk.SOFTWARE_VOL)
    placed = {disk.stem(disk.show_name(e["name"]))
              for e in disk.Volume(disk.Image(args.img), disk.SOFTWARE_VOL).files()}
    for f in SOFTWARE:
        p = os.path.join(DEMOS, f)
        if not os.path.exists(p):
            continue
        if discname(f) not in placed:
            print("  %s: its %s.BIN is not on drive %d, so the stub is not typed"
                  % (f, discname(f), disk.SOFTWARE_VOL))
            continue
        H.key(m, syms, "NEW\r")
        for line in io.open(p, encoding="utf-8").read().splitlines():
            if line.strip():
                H.line(m, syms, line)
        H.key(m, syms, 'SAVE "%s"\r' % discname(f))
        print("  typed and saved %-16s on drive %d as %s" % (f, disk.SOFTWARE_VOL, discname(f)))
    H.key(m, syms, "DRIVE %d\r" % DRIVE)
    m.flash.flush()

    # **Bad Apple rides on its dedicated drives when it exists.** The
    # chunks and manifest in demos/bapple/ come from tools/mkbadapple.py
    # (run against the user's own mp4, or --selftest); its stub bakes
    # each chunk's *predicted* flash address, so the placement above is
    # asserted against the prediction -- a chunk that lands anywhere
    # else would stream garbage from the right-looking drive. The stub
    # itself is typed onto the demo drive like any other program.
    # **NEW first.** The stub used to be typed straight over the last
    # demo; every line number bapple.bas does not use survived the
    # overtyping -- WAVE's colour-ramp DATA lines 205-249 landed between
    # the stub's decoder DATA (200-204) and its chunk table (250+), and
    # READ served the palette as flash addresses. The program LISTed
    # clean for every line the stub does have, which is why eyeballing
    # missed it; only dumping the READ stream itself showed the ramp.
    if man is not None:
        H.key(m, syms, "NEW\r")
        for line in io.open(os.path.join(bap, "bapple.bas"),
                            encoding="utf-8").read().splitlines():
            if line.strip():
                H.line(m, syms, line)
        H.key(m, syms, 'SAVE "BAPPLE"\r')
        m.flash.flush()
        drives = sorted({e["drive"] for e in man}, reverse=True)
        print("  bad apple: %d chunks on drives %s, stub saved as BAPPLE"
              % (len(man), drives))

    # **The finished file is read back, not trusted.** The confetti bug
    # above survived every placement assertion because those ran against
    # an intermediate state of the image; only the bytes in the file the
    # user boots are the truth.
    if man is not None:
        with open(args.img, "rb") as fh:
            final = fh.read()
        for e in man:
            with open(os.path.join(bap, e["name"]), "rb") as fh:
                blob = fh.read()
            got = final[e["addr"]:e["addr"] + len(blob)]
            assert got == blob, "chunk %s is not on the finished disc" \
                % e["name"]

    for d, title in disk.MENUS:
        v = disk.Volume(disk.Image(args.img), d)
        print("  drive %d (%s) holds: %s"
              % (d, title, ", ".join(disk.show_name(e["name"]) for e in v.files())))

    # **Every demo gets shot, not just the first.** A picture is the
    # only review a demo really gets, and one that is never rendered is
    # one nobody looks at until a user does.
    # **The pictures are most of the wall clock.** Each demo is run for
    # twelve chunks of 500M cycles before its frame is grabbed, so
    # shooting five of them is minutes while typing them onto the disc is
    # not. `--no-shots` is for the caller that wants a bootable image and
    # will look at it in the window itself -- `cool8rsrun.py --rebuild`.
    for want in ([] if args.no_shots else
                 [args.png] if args.png else
                 [discname(f) for f in sources()]):
        # **Stop whatever is still running.** A demo ends in `GOTO` or
        # `LOOP` and never comes back, so the machine is not idle and
        # `H.key` would wait for a prompt that is never coming. The
        # break key is what a person would press.
        m.press_break()
        m.run(cycles=20_000_000)
        H.settle(m, syms)
        H.key(m, syms, "MODE 0\r")      # back to text to be typed at
        H.key(m, syms, "NEW\r")
        H.key(m, syms, "DRIVE %d\r" % DRIVE)
        H.key(m, syms, 'LOAD "%s"\r' % want)
        # **`H.key` settles after every keystroke, and a demo does not
        # settle** -- it ends in `GOTO` or `LOOP`, so the Return that
        # starts it never returns to the prompt. Type RUN, then press
        # Return without waiting for idle and give it a fixed slice.
        H.key(m, syms, "RUN")
        m.key(["\r"])
        # **Accumulated, not one big number.** `m.run(cycles=)` stops
        # at its own budget, so a single huge request silently runs far
        # less than asked -- which read as a demo that had stalled when
        # it had simply been cut short. bench needs ~50 s of machine
        # time before it has a report; mandel needs minutes.
        for _ in range(12):
            m.run(cycles=500_000_000)
        m.run_frame(2)
        import test_video as TV
        rgb = bytearray()
        for p in m.fb():
            rgb += bytes((((p >> 8) & 15) * 17, ((p >> 4) & 15) * 17,
                          (p & 15) * 17))
        out = os.path.join(ROOT, "docs", "img",
                           "demo-%s.png" % want.lower())
        TV.write_png(out, 640, 480, rgb)
        print("  %d colours on screen -> %s"
              % (len(set(m.fb())), os.path.relpath(out, ROOT)))
    print("  %s" % os.path.relpath(args.img, ROOT))


if __name__ == "__main__":
    main()
