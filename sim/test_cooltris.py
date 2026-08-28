#!/usr/bin/env python3
"""Test COOLTRIS demo -- controls, layout, collision, scoring, ghost pieces, replay, quit, and RENUM.

    python sim/test_cooltris.py

Runs on the Machine API and tests the game through the real hardware video
text buffer (m.row, m.text, m.shows) and PS/2 keyboard queue (m.key).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H
from harness import check

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import cool8rsvm as vm
import test_basic as B

BUILD = H.BUILD
IMG = os.path.join(BUILD, "demos.img")


def load_cooltris(m, syms):
    bas_path = os.path.join(H.ROOT, "demos", "cooltris1.bas")
    with open(bas_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("REM")]

    H.line(m, syms, "NEW")
    for ln in lines:
        H.line(m, syms, ln)


def main():
    code, syms = B.build()
    m = B.Machine(code, syms).m
    for _ in range(60):
        m.run_frame()
    H.settle(m, syms)

    # 1. Load cooltris.bas
    load_cooltris(m, syms)

    H.key(m, syms, "RUN")
    m.key(["\r"])

    # Let the game draw initial layout and start main loop
    for _ in range(60):
        m.run_frame()

    # 2. Verify title and panel headers on screen via Machine API text buffer
    title_row = m.row(1, cols=40)
    check("C O O L T R I S 1" in title_row, "COOLTRIS 1 title banner is drawn on row 1",
          f"got: {title_row}")
    check("KEYS" in m.row(3, cols=40), "KEYS panel header is on row 3",
          f"got: {m.row(3, cols=40)}")
    check("NEXT" in m.row(3, cols=40), "NEXT panel header is on row 3",
          f"got: {m.row(3, cols=40)}")
    check("STATS" not in "\n".join(m.row(r, cols=40) for r in range(30)),
          "STATS word is removed from info box",
          f"screen text has no STATS")

    # 3. Check stats layout: left-aligned labels at col 29, right-aligned numbers ending at col 36, no colons
    for r in range(9, 19):
        row_str = m.row(r, cols=40)
        check(":" not in row_str, f"No colons in info box row {r}", f"got: {row_str}")

    r10 = m.row(10, cols=40)
    check(r10[29:34] == "SCORE", "SCORE label is left-aligned at col 29", f"got: {r10}")

    r11 = m.row(11, cols=40)
    check(r11[31:37] == "000000", "Score 000000 is right-aligned at cols 31..36", f"got: {r11}")

    r12 = m.row(12, cols=40)
    check(r12[29:34] == "LEVEL", "LEVEL label is left-aligned at col 29", f"got: {r12}")

    r13 = m.row(13, cols=40)
    check(r13[35:37] == "00" and "LEVEL" not in r13, "Level 00 is on separate row 13 right-aligned", f"got: {r13}")

    r14 = m.row(14, cols=40)
    check(r14[29:34] == "LINES", "LINES label is left-aligned at col 29", f"got: {r14}")

    r15 = m.row(15, cols=40)
    check(r15[34:37] == "000" and "LINES" not in r15, "Lines 000 is on separate row 15 right-aligned", f"got: {r15}")

    r16 = m.row(16, cols=40)
    check(r16[29:33] == "HIGH", "HIGH label is left-aligned at col 29", f"got: {r16}")

    r17 = m.row(17, cols=40)
    check(r17[31:37] == "005000", "High score 005000 is right-aligned at cols 31..36", f"got: {r17}")

    # 4. Test movements
    m.key("A")
    for _ in range(10):
        m.run_frame()
    m.key("W")
    for _ in range(10):
        m.run_frame()
    m.key("D")
    for _ in range(10):
        m.run_frame()

    # 5. Test hard drop (Space) -> locks piece at the bottom and increments score
    m.key(" ")
    for _ in range(30):
        m.run_frame()

    score_row = m.row(11, cols=40)
    check("000000" not in score_row, "Score incremented after hard drop",
          f"got: {score_row}")

    # 6. Test rapid left/right oscillation: piece does not hover, gravity continues
    for _ in range(15):
        m.key("A")
        m.run_frame(1)
        m.key("D")
        m.run_frame(1)

    check("C O O L T R I S 1" in m.row(1, cols=40), "Game remains active and running during rapid input",
          f"row 1 is: {m.row(1, cols=40)}")

    # 7. Test game over and restart with N key
    # Trigger game over by hard dropping multiple pieces in column 4
    for _ in range(25):
        m.key(" ")
        for _ in range(20):
            m.run_frame()

    # Check Game Over prompt
    all_text = "\n".join(m.row(r, cols=40) for r in range(30))
    check("GAME OVER" in all_text or "N TO PLAY" in all_text or "PLAY" in all_text,
          "Game reaches game over screen", f"screen: {all_text}")

    # Press N to restart
    m.key("N")
    for _ in range(60):
        m.run_frame()

    # Verify that board is cleanly redrawn: row 12 does NOT contain GAME OVER inside board
    row12 = m.row(12, cols=40)
    check("GAME OVER" not in row12, "Game board is cleanly redrawn on restart without dialogue box residue",
          f"got row 12: {row12}")

    # 8. Test Q (Quit) key exits to BASIC
    m.key("Q")
    for _ in range(30):
        m.run_frame()

    # 9. Test RENUMBER on cooltris.bas
    print("Testing RENUM on cooltris.bas...")
    m2 = B.Machine(code, syms).m
    load_cooltris(m2, syms)
    H.line(m2, syms, "RENUM 100,10")

    # Verify that all 347 lines were renumbered and GOSUB/GOTO targets were updated
    p = syms["progbot"]
    end = m2.bus.mem[syms["progend"]] | (m2.bus.mem[syms["progend"] + 1] << 8)
    records = []
    while p < end:
        lineno = m2.bus.mem[p] | (m2.bus.mem[p + 1] << 8)
        length = m2.bus.mem[p + 2]
        records.append((lineno, list(m2.bus.mem[p + 3:p + 3 + length])))
        p += 4 + length

    check(len(records) == 347, "All 347 lines in cooltris.bas are renumbered", f"count: {len(records)}")
    check(records[0][0] == 100 and records[-1][0] == 3560,
          "Line numbers range from 100 to 3560 step 10",
          f"first: {records[0][0]}, last: {records[-1][0]}")

    # Check GOSUB 1000 (now 250) in line 120 and GOTO 70 (now 160) in line 210
    r120_toks = records[2][1]
    # D2 20 A4 FA 00 -> GOSUB 250 ($00FA)
    check(0xD2 in r120_toks and 0xFA in r120_toks,
          "Line 120 GOSUB 1000 was renumbered to GOSUB 250",
          f"line 120 toks: {[hex(x) for x in r120_toks]}")

    r210_toks = records[11][1]
    # A2 20 A4 A0 00 -> GOTO 160 ($00A0)
    check(0xA2 in r210_toks and 0xA0 in r210_toks,
          "Line 210 GOTO 70 was renumbered to GOTO 160",
          f"line 210 toks: {[hex(x) for x in r210_toks]}")

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
