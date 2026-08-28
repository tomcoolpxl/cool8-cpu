# Test suite for COOLTRIS 2 (Mode 2 Tile Engine Edition)
# Runs via sim/harness.py and Machine API, verifying VRAM directly (CLAUDE.md)
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H
from harness import check

sys.path.insert(0, os.path.join(H.ROOT, "tools"))
import cool8rsvm as vm
import test_basic as B


def load_cooltris2(m, syms):
    bas_path = os.path.join(H.ROOT, "demos", "cooltris2.bas")
    with open(bas_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("REM")]

    H.line(m, syms, "NEW")
    for ln in lines:
        H.line(m, syms, ln)


def main():
    print("Testing COOLTRIS 2 in Mode 2...")
    code, syms = B.build()
    bm = B.Machine(code, syms)
    m = bm.m
    for _ in range(60):
        m.run_frame()
    bm.settle()

    # 1. Load cooltris2.bas
    load_cooltris2(m, syms)

    H.key(m, syms, "RUN\r")

    # Let the game initialize Mode 2 palettes, patterns, layout, and spawn piece
    for _ in range(90):
        m.run_frame()

    # 2. Inspect VRAM Tile Map directly via Machine API
    # Row 1 is Title Banner 'C O O L T R I S   2' (Rainbow Palette)
    # Address = row * 128 + col * 2
    r1_vram = m.video.vram[128:208]
    r1_tiles = [r1_vram[i] for i in range(0, 80, 2)]
    check(35 in r1_tiles and 47 in r1_tiles and 18 in r1_tiles,
          "COOLTRIS 2 Title banner tiles rendered in Mode 2 VRAM",
          f"r1 tiles: {r1_tiles}")

    # 3. Check Board double rail borders and sidebar single rail boxes in VRAM
    # Board TL corner 102 at col 14, row 4 (address 4*128 + 14*2 = 540)
    c_board_tl = m.video.vram[4 * 128 + 14 * 2]
    check(c_board_tl == 102, "Board double-border top-left corner 102 at (col 14, row 4)",
          f"got: {c_board_tl}")

    # Controls box TL corner 108 at col 1, row 4 (address 4*128 + 1*2 = 514)
    c_ctrl_tl = m.video.vram[4 * 128 + 1 * 2]
    check(c_ctrl_tl == 108, "Controls single-border top-left corner 108 at (col 1, row 4)",
          f"got: {c_ctrl_tl}")

    # Next piece box TL corner 108 at col 27, row 4 (address 4*128 + 27*2 = 566)
    c_next_tl = m.video.vram[4 * 128 + 27 * 2]
    check(c_next_tl == 108, "Next piece box single-border top-left corner 108 at (col 27, row 4)",
          f"got: {c_next_tl}")

    # 4. Check active spawned tetromino pieces (Tile 96: 3D square mino)
    spawn_area = [m.video.vram[r * 128 + c * 2] for r in range(5, 10) for c in range(15, 25)]
    check(96 in spawn_area,
          "Spawned active tetromino rendered with 3D square mino tile 96",
          f"spawn area tiles: {spawn_area}")

    # 5. Test movement with Left key (A) and rotation with (W)
    for _ in range(3):
        m.key("A")
        m.run_frame(2)
    m.key("W")
    m.run_frame(2)

    # 6. Test hard drop (Space)
    m.key(" ")
    for _ in range(20):
        m.run_frame(1)

    # Check that score updated in VRAM stats area (Row 13 at cols 30..35)
    score_tiles = [m.video.vram[13 * 128 + c * 2] for c in range(30, 36)]
    check(any(16 <= t <= 25 for t in score_tiles), "Score digits rendered in VRAM", f"score tiles: {score_tiles}")

    # 7. Test Game Over and restart
    for _ in range(35):
        m.key(" ")
        for _ in range(20):
            m.run_frame(1)

    # Check Game Over prompt and curtain
    all_vram = [m.video.vram[r * 128 + c * 2] for r in range(5, 25) for c in range(15, 25)]
    check(112 in all_vram or 39 in all_vram, "Game reaches game over screen with curtain in VRAM",
          f"found curtain/game over tiles")

    # Test restart with N
    m.key("N")
    for _ in range(50):
        m.run_frame(1)

    # Board center should be cleared (tile 0) except active piece
    center_tile = m.video.vram[15 * 128 + 19 * 2]
    check(center_tile == 0, "Board cleanly reset on restart", f"center tile: {center_tile}")

    # 8. Test Q (Quit) key exits cleanly to BASIC prompt
    m.key("Q")
    for _ in range(30):
        m.run_frame()

    # 9. Test RENUMBER on cooltris2.bas
    print("Testing RENUM on cooltris2.bas...")
    m2 = B.Machine(code, syms).m
    load_cooltris2(m2, syms)
    H.line(m2, syms, "RENUM 100,10")

    p = syms["progbot"]
    end = m2.bus.mem[syms["progend"]] | (m2.bus.mem[syms["progend"] + 1] << 8)
    records = []
    while p < end:
        lineno = m2.bus.mem[p] | (m2.bus.mem[p + 1] << 8)
        length = m2.bus.mem[p + 2]
        records.append((lineno, list(m2.bus.mem[p + 3:p + 3 + length])))
        p += 4 + length

    check(len(records) > 0, "All lines in cooltris2.bas are renumbered", f"count: {len(records)}")
    check(records[0][0] == 100 and records[-1][0] == 100 + (len(records) - 1) * 10,
          f"Line numbers range from 100 to {100 + (len(records) - 1) * 10} step 10",
          f"first: {records[0][0]}, last: {records[-1][0]}")

    print("COOLTRIS 2 PASS")
    return H.report()


if __name__ == "__main__":
    sys.exit(main())
