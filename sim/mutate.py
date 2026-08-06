#!/usr/bin/env python3
"""Mutation testing: break the RTL on purpose and require a failure.

Every block in this project since M1 has been checked this way, and the
exercise has never once been a formality — it has found a real coverage
gap in the suite for `cool8_spram`, `cool8_soc`, `cool8_vport` and
`cool8_video` in turn. A suite that passes proves nothing about the bugs
it cannot see.

Each mutation is a textual edit to one RTL file: a term dropped, a
polarity flipped, an index moved by one. The file is patched, the
block's own suite is run, and the mutation is **caught** if the suite
fails. A mutation that survives is either a missing test or an
equivalent transformation, and the two are worth telling apart by hand —
so this prints the survivors rather than just counting them.

    python sim/mutate.py                # every block that has a list
    python sim/mutate.py ps2            # one of them
    python sim/mutate.py flash -v

A pattern that is absent, or that appears more than once, is an error
rather than a skipped mutation: it means the RTL moved and the mutation
is no longer describing what it claims to.

Set OSS_CAD_SUITE to the toolchain root if iverilog is not on PATH.
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RTL = os.path.join(ROOT, "rtl", "soc")


# Each entry: (name, [(find, replace), ...]) — several edits at once when
# a single bug would naturally touch more than one line.
PS2 = [
    ("data sampled on the rising clock edge",
     [("wire c_fall = cf_d & ~cf;", "wire c_fall = ~cf_d & cf;")]),
    ("no line filtering at all",
     [("else if (fcnt >= FILT[5:0]) begin", "else if (1'b1) begin")]),
    ("the receive watchdog never fires",
     [("end else if (rx_n != 4'd0 && tmr_60) begin",
       "end else if (1'b0) begin")]),
    ("parity accepted when even",
     [("(^rx_next[9:1] == 1'b1)", "(^rx_next[9:1] == 1'b0)")]),
    ("the start bit is not checked",
     [("(rx_next[0] == 1'b0) &", "(1'b1) &")]),
    ("the stop bit is not checked",
     [("(rx_next[10] == 1'b1) &", "(1'b1) &")]),
    ("a frame is ten bits, not eleven",
     [("wire        rx_last = (rx_n == 4'd10);",
       "wire        rx_last = (rx_n == 4'd9);")]),
    ("the queued byte is taken one bit low",
     [("q[wr[AB-1:0]] <= rx_next[8:1];", "q[wr[AB-1:0]] <= rx_next[7:0];")]),
    ("a full FIFO is written anyway",
     [("if (push && !full) begin", "if (push) begin")]),
    ("overflow is never reported",
     [("if (push && full) over <= 1'b1;", "if (1'b0) over <= 1'b1;")]),
    ("the block RAM read is never settled",
     [("settle <= push | pop | clr;", "settle <= 1'b0;")]),
    ("a pop does not advance the read pointer",
     [("if (pop) rd <= rd + 1'b1;", "if (1'b0) rd <= rd + 1'b1;")]),
    ("clearing the FIFO does nothing",
     [("rd   <= wr;", "rd   <= rd;")]),
    ("transmit parity is even",
     [("tx_sr  <= {~(^io_wdata), io_wdata};",
       "tx_sr  <= {(^io_wdata), io_wdata};")]),
    ("transmit sends the most significant bit first",
     [("                tx_dat <= ~tx_sr[0];\n"
       "                tx_sr  <= {1'b0, tx_sr[8:1]};",
       "                tx_dat <= ~tx_sr[8];\n"
       "                tx_sr  <= {tx_sr[7:0], 1'b0};")]),
    ("no inhibit before the request to send",
     [("T_INH: if (tmr_100) begin", "T_INH: if (1'b1) begin")]),
    ("the data line is never released for the stop bit",
     [("tx_dat <= 1'b0;              // 9. release: the stop bit",
       "tx_dat <= 1'b1;              // 9. release: the stop bit")]),
    ("a missing acknowledge is not noticed",
     [("if (dat_in) tx_err <= 1'b1;      // no ack",
       "if (1'b0) tx_err <= 1'b1;      // no ack")]),
    ("a device that never answers is waited on for ever",
     [("if (tos >= TXTO[7:0]) begin", "if (1'b0) begin")]),
    ("the interrupt ignores its enable",
     [("assign o_irq = irq_en & avail;", "assign o_irq = avail;")]),
    ("the acknowledge is not waited out",
     [("T_ACK: if (dat_in) begin", "T_ACK: if (1'b1) begin")]),
    ("a transmit leaves the receiver out of step",
     [("                    tx_n   <= 4'd0;\n                    rx_n   <= 4'd0;",
       "                    tx_n   <= 4'd0;")]),
]

FLASH = [
    ("a different opcode is issued",
     [("sr       <= {OP_READ, addr};", "sr       <= {8'h0B, addr};")]),
    ("the address goes out least significant byte first",
     [("sr       <= {OP_READ, addr};",
       "sr       <= {OP_READ, addr[7:0], addr[15:8], addr[23:16]};")]),
    ("the command is 24 bits, not 32",
     [("n        <= 6'd32;", "n        <= 6'd24;")]),
    ("a data shift is seven bits",
     [("n     <= 6'd8;", "n     <= 6'd7;")]),
    ("MISO is never shifted in",
     [("sr      <= {sr[30:0], spi_miso};", "sr      <= {sr[30:0], 1'b0};")]),
    ("MOSI comes off the wrong end of the shift register",
     [("assign spi_mosi = sr[31];", "assign spi_mosi = sr[0];")]),
    ("the address does not advance",
     [("addr     <= addr + 24'd1;", "addr     <= addr;")]),
    ("the byte is taken a bit late",
     [("pf       <= {sr[6:0], spi_miso};", "pf       <= sr[7:0];")]),
    ("the command shift is treated as data",
     [("cmd      <= 1'b1;", "cmd      <= 1'b0;")]),
    ("...and a data shift delivers nothing",
     [("if (!cmd) begin", "if (1'b0) begin")]),
    ("the command shift also delivers a byte",
     [("if (!cmd) begin", "if (1'b1) begin")]),
    ("reads never stall",
     [("assign o_stall = rd_hold & ~pf_valid;", "assign o_stall = 1'b0;")]),
    ("chip select is not taken low to open",
     [("assign spi_cs_n = ~(open_r | w_run);",
       "assign spi_cs_n = ~w_run;")]),
    ("closing does not shut the stream",
     [("            open_r   <= 1'b0;\n            spi_sck  <= 1'b0;\n"
       "            busy     <= 1'b0;\n            cmd      <= 1'b0;\n"
       "            n        <= 6'd0;",
       "            open_r   <= open_r;\n            spi_sck  <= 1'b0;\n"
       "            busy     <= 1'b0;\n            cmd      <= 1'b0;\n"
       "            n        <= 6'd0;")]),
    ("the address can be written while the stream is open",
     [("if (io_we && !open_r) begin", "if (io_we) begin")]),
    ("the data port is decoded as the control register",
     [("assign o_dp_sel = (io_a == A_DATA);",
       "assign o_dp_sel = (io_a == A_CTRL);")]),
    ("the decode claims two addresses too many",
     [("& (io_a[2:0] <= 3'd7)", "& (io_a[2:0] <= 3'd6)")]),
    ("SCK never rises",
     [("                    spi_sck <= 1'b1;\n                    phase   <= 1'b1;",
       "                    spi_sck <= 1'b0;\n                    phase   <= 1'b1;")]),
    ("a read completes whether the byte is there or not",
     [("wire rd_ok     = pf_valid | ~open_r;", "wire rd_ok     = 1'b1;")]),
    ("the status bits are the other way round",
     [("A_STAT:   o_rdata = {5'b00000, w_busy, open_r, busy};",
       "A_STAT:   o_rdata = {5'b00000, w_busy, busy, open_r};")]),
    # the one that matters
    ("the floor does not stop a write",
     [("                    if (below) begin", "                    if (1'b0) begin")]),
    ("an erase is issued without the write enable first",
     [("                        wst    <= W_WREN;", "                        wst    <= W_GAP;")]),
    ("chip select never rises between commands",
     [("assign spi_cs_n = ~(open_r | w_run);",
       "assign spi_cs_n = ~(open_r | w_busy);")]),
]

BLOCKS = {
    "ps2":   ("cool8_ps2.v",   "test_ps2.py",   PS2),
    "flash": ("cool8_flash.v", "test_flash.py", FLASH),
}


# Mutations that cannot be caught because they do not change behaviour.
# Kept in the list rather than deleted, because "no test covers this" and
# "there is nothing here to cover" are different answers and the second
# one needs an argument. If one of these is ever *caught*, the argument
# has gone stale and the entry has to be re-examined rather than moved.
EQUIVALENT = {
    ("ps2", "a transmit leaves the receiver out of step"):
        "rx_n is cleared twice over. A transmit that completes leaves "
        "through T_ACK, which clears it; a transmit that times out "
        "leaves with the timer saturated well past the watchdog "
        "threshold and no edge having restarted it, so the first cycle "
        "back in T_IDLE clears it. The assignment states the intent and "
        "changes nothing.",
}


def run(name, verbose):
    src, suite, muts = BLOCKS[name]
    path = os.path.join(RTL, src)
    backup = path + ".orig"
    original = open(path, encoding="utf-8").read()
    shutil.copyfile(path, backup)

    caught = survived = 0
    survivors = []
    stale = []
    try:
        for label, edits in muts:
            text = original
            for find, repl in edits:
                n = text.count(find)
                if n != 1:
                    sys.exit(f"\n  mutation '{label}': pattern occurs {n} "
                             f"times in {src}, expected once.\n"
                             f"  The RTL moved; fix the mutation list.")
                text = text.replace(find, repl, 1)

            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)

            r = subprocess.run([sys.executable,
                                os.path.join(HERE, suite)],
                               capture_output=True, text=True)
            # A mutation is caught if the suite notices — a failure, or a
            # build error, or a hang the testbench's own timeout ends.
            hit = "\nPASS" not in r.stdout
            known = (name, label) in EQUIVALENT
            if hit:
                caught += 1
                if known:
                    stale.append(label)
            else:
                survived += 1
                if not known:
                    survivors.append(label)
            if verbose or (not hit and not known):
                print(f"    {'caught ' if hit else 'SURVIVED'}  {label}")
    finally:
        shutil.copyfile(backup, path)
        os.remove(backup)

    print(f"  {src:<16} {caught} of {caught + survived} caught, "
          f"{survived} equivalent by argument")
    for label in stale:
        print(f"    STALE: '{label}' is listed as equivalent but the "
              f"suite caught it — the argument no longer holds")
    return survivors + stale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("blocks", nargs="*", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    names = args.blocks or list(BLOCKS)
    for n in names:
        if n not in BLOCKS:
            sys.exit(f"no mutation list for '{n}'; have {list(BLOCKS)}")

    print("mutation testing — a mutation is caught if the suite fails\n")
    left = {}
    for n in names:
        left[n] = run(n, args.verbose)

    total = sum(len(v) for v in left.values())
    if total:
        print("\nunexplained survivors — each is a missing test until "
              "somebody argues otherwise in EQUIVALENT:")
        for n, v in left.items():
            for label in v:
                print(f"  {n}: {label}")
    print("\n" + ("PASS" if total == 0 else f"{total} unexplained"))
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
