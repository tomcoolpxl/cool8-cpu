#!/usr/bin/env python3
"""sim/test_z3.py -- Test COOL8 Z-Machine Version 3 Interpreter on Infocom Suite

Verifies native Z-Machine V3 execution on:
- The Hitchhiker's Guide to the Galaxy (HHGG on Drive 13)
- Zork I: The Great Underground Empire (ZORK1 on Drive 14)
- Planetfall (PLANET on Drive 14)
- Leather Goddesses of Phobos (LGOP on Drive 14)

Checks VRAM and screen text directly via Machine API (CLAUDE.md).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H
from harness import check

sys.path.insert(0, os.path.join(H.ROOT, "tools"))
import cool8rsvm as vm
import cool8disk as disk
import test_basic as B


def test_disc_catalogue(demos_img):
    im = disk.Image(demos_img)
    vol12 = disk.Volume(im, disk.BAPPLE_VOL)
    vol13 = disk.Volume(im, disk.DEMO_VOL)
    vol14 = disk.Volume(im, disk.ADVENTURE_VOL)

    check(vol12.find("BA000.DAT") is not None, "Bad Apple 7-chunk preview on Drive 12")
    check(vol13.find("HHGG.BIN") is not None, "HHGG.BIN on Drive 13 (DEMOS)")
    check(vol13.find("HHGG0.DAT") is not None, "HHGG0.DAT on Drive 13 (DEMOS)")
    check(vol14.find("ZORK1.BIN") is not None, "ZORK1.BIN on Drive 14 (ADVENTUR)")
    check(vol14.find("PLANET.BIN") is not None, "PLANET.BIN on Drive 14 (ADVENTUR)")
    check(vol14.find("LGOP.BIN") is not None, "LGOP.BIN on Drive 14 (ADVENTUR)")


def test_game_on_disc(demos_img, syms, game_name, drive_num, expected_keywords, exp_attr, exp_stat, exp_bord, input_cmd=None):
    m = vm.boot(flash_path=demos_img, render=True)
    for _ in range(90):
        m.run_frame()
    H.settle(m, syms)

    H.key(m, syms, f"DRIVE {drive_num}\r")
    H.key(m, syms, f"LOAD \"{game_name}\"\r")
    H.key(m, syms, "RUN")
    m.key(["\r"])

    for _ in range(120):
        m.run_frame()

    import memmap
    screen_base = memmap.SCREEN
    row0_attr = m.bus.mem[screen_base + 1]
    border = m.bus.read(0xFF1A)

    check(border == exp_bord, f"[{game_name}] Border color is ${exp_bord:02x}", f"got ${border:02x}")
    check(row0_attr == exp_stat, f"[{game_name}] Status line attr is ${exp_stat:02x}", f"got ${row0_attr:02x}")

    if input_cmd:
        if input_cmd == "\r":
            m.key(["\r"])
        else:
            m.key(input_cmd + "\r")
        for _ in range(90):
            m.run_frame()

    text = "\n".join(m.text())
    for kw in expected_keywords:
        check(kw.lower() in text.lower(),
              f"[{game_name}] Screen contains '{kw}'",
              f"screen: {text[:200]}")


def test_save_restore(demos_img, syms):
    m = vm.boot(flash_path=demos_img, render=True)
    for _ in range(90):
        m.run_frame()
    H.settle(m, syms)

    H.key(m, syms, "DRIVE 13\r")
    H.key(m, syms, "LOAD \"HHGG\"\r")
    H.key(m, syms, "RUN")
    m.key(["\r"])

    for _ in range(120):
        m.run_frame()

    z3_code, z3_syms = H.assemble("sw/z3/z3.asm")
    sread_sym = z3_syms["z_sread"]
    m.breakpoints.add(sread_sym)

    def type_cmd(cmd_str):
        m.run(until=sread_sym)
        m.tick()
        for ch in cmd_str:
            m.key([ch])
            for _ in range(6):
                m.run_frame()
        for _ in range(60):
            m.run_frame()

    # Step 1: Turn on light
    type_cmd("turn on light\r")

    # Step 2: Save game to flash
    type_cmd("save\r")

    text_save = "\n".join(m.text())
    check("ok." in text_save.lower(), "[HHGG SAVE] Game confirms save with 'Ok.'", f"got {text_save[:200]}")

    # Step 3: Turn off light
    type_cmd("turn off light\r")

    # Step 4: Restore game from flash
    type_cmd("restore\r")

    text_rst = "\n".join(m.text())
    check("ok." in text_rst.lower(), "[HHGG RESTORE] Game confirms restore with 'Ok.'", f"got {text_rst[:200]}")

    # Step 5: Look (room must be lit, not dark!)
    type_cmd("look\r")

    text_look = "\n".join(m.text())
    check("bedroom, in the bed" in text_look.lower(), "[HHGG RESTORE] Restored lit room state successfully", f"got {text_look[:200]}")


def main():
    print("=== Testing COOL8 Native Z-Machine Infocom Suite ===")
    demos_img = os.path.join(H.BUILD, "demos.img")
    if not os.path.exists(demos_img):
        print(f"demos.img not found at {demos_img}")
        return 1

    test_disc_catalogue(demos_img)

    code, syms = B.build()

    # 1. The Hitchhiker's Guide to the Galaxy (Drive 13: Amiga dark blue bg $1, white text $F, status $F1)
    test_game_on_disc(demos_img, syms, "HHGG", 13, ["Bedroom", "Infocom", "wake up"], 0x1F, 0xF1, 0x01)

    # 2. Zork I: The Great Underground Empire (Drive 14: Black bg $0, amber text $E, status $E0)
    test_game_on_disc(demos_img, syms, "ZORK1", 14, ["West of House", "Infocom", "mailbox"], 0x0E, 0xE0, 0x00)

    # 3. Planetfall (Drive 14: Default black bg $0, light grey text $7, status $70)
    test_game_on_disc(demos_img, syms, "PLANET", 14, ["PLANETFALL", "Feinstein", "Deck Nine"], 0x07, 0x70, 0x00)

    # 4. Leather Goddesses of Phobos (Drive 14: Dark gray bg $8, light gray text $7, status $78, border $8)
    test_game_on_disc(demos_img, syms, "LGOP", 14, ["LEATHER GODDESSES", "Upper Sandusky"], 0x87, 0x78, 0x08, input_cmd="\r")

    # 5. Persistent Flash Disk Save and Restore
    test_save_restore(demos_img, syms)

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
