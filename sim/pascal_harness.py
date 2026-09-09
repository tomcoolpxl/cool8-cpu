"""sim/pascal_harness.py -- Test harness and P-Code debugger for UCSD Pascal on COOL8.

Wraps cool8rsvm.Machine to provide high-level inspection of the UCSD Pascal
P-Machine running inside the COOL8 CPU.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8rsvm as vm
import harness as H


def _load_opcode_names():
    names = {}
    asm_path = os.path.join(ROOT, "sw", "pascal", "pascal.asm")
    if os.path.exists(asm_path):
        with open(asm_path, "r", encoding="utf-8") as f:
            for line in f:
                if ".word" in line and ";" in line:
                    parts = line.split(";")
                    tokens = parts[1].strip().split()
                    if len(tokens) >= 2 and tokens[0].isdigit():
                        names[int(tokens[0])] = tokens[1]
    return names

OPCODE_NAMES = _load_opcode_names()



class PascalMachine:
    def __init__(self, img_path="demos.img"):
        asm_path = os.path.join(ROOT, "sw", "pascal", "pascal.asm")
        self.code, self.syms = H.assemble(asm_path, name="pascal", write=False)
        self.m = vm.boot(flash_path=img_path, render=True)
        self.m.bus.mem[0x0200 : 0x0200 + len(self.code)] = self.code
        self.m.cpu.pc = 0x0200
        self.m.cpu.sp = 0x0200
        self.m.romen = False

        self.main_loop = self.syms.get("pm_main_loop")
        self.ur_done = self.syms.get("pm_sbios_unitread.ur_done")

    def boot(self, frames=100):
        """Run until Pascal boots to the command prompt."""
        for _ in range(frames):
            self.m.run_frame()

    def get_w(self, addr):
        return self.m.bus.mem[addr] | (self.m.bus.mem[addr + 1] << 8)

    def state(self):
        """Read P-Machine registers from zero page."""
        sp = self.get_w(0x0040)
        mp = self.get_w(0x0042)
        bp = self.get_w(0x0044)
        ipc = self.get_w(0x0046)
        segb = self.get_w(0x0048)
        kp = self.get_w(0x0052)
        syscom = self.get_w(0x004E)

        jtab = self.get_w(mp + 4) if mp < 0xFFF0 else 0
        proc_num = self.m.bus.mem[jtab] if jtab < 0x10000 else 0
        op = self.m.bus.mem[segb + ipc] if (segb + ipc) < 0x10000 else 0
        op_name = OPCODE_NAMES.get(op, f"OP_{op}")

        return {
            "sp": sp, "mp": mp, "bp": bp, "ipc": ipc, "segb": segb,
            "kp": kp, "syscom": syscom, "proc": proc_num,
            "op": op, "op_name": op_name,
            "cpu_pc": self.m.cpu.pc, "cpu_sp": self.m.cpu.sp
        }

    def call_stack(self, max_depth=10):
        """Walk dynamic link chain to return active P-code procedure frames."""
        frames = []
        cur = self.get_w(0x0042)
        depth = 0
        while cur >= 0x0500 and cur < 0x9900 and depth < max_depth:
            stat = self.get_w(cur)
            dyn = self.get_w(cur + 2)
            jtab = self.get_w(cur + 4)
            seg = self.get_w(cur + 6)
            ret_ipc = self.get_w(cur + 8)
            ms_sp = self.get_w(cur + 10)
            proc_num = self.m.bus.mem[jtab] if jtab < 0x10000 else 0
            frames.append({
                "depth": depth, "mp": cur, "dyn": dyn, "stat": stat,
                "jtab": jtab, "proc": proc_num, "seg": seg,
                "ret_ipc": ret_ipc, "ms_sp": ms_sp
            })
            cur = dyn
            depth += 1
        return frames

    def print_stack(self):
        print("--- P-Code Call Stack ---")
        for f in self.call_stack():
            print(f"  Frame {f['depth']}: MP=0x{f['mp']:04X} Proc={f['proc']:2d} "
                  f"ret_IPC=0x{f['ret_ipc']:04X} Stat=0x{f['stat']:04X} Dyn=0x{f['dyn']:04X}")

    def step_pcode(self, max_cycles=100000):
        """Step one P-Code instruction."""
        res = self.m.run(until=self.main_loop, cycles=max_cycles)
        st = self.state()
        self.m.tick()
        return st

    def trace_pcode(self, n=50):
        """Trace next n P-Code instructions."""
        for i in range(n):
            st = self.step_pcode()
            print(f"#{i:3d}: Proc {st['proc']:2d} | SegB=0x{st['segb']:04X} "
                  f"IPC=0x{st['ipc']:04X} {st['op_name']:<8} (0x{st['op']:02X}) SP=0x{st['sp']:04X}")

    def screen(self):
        """Return non-empty screen rows as [(row_num, text)]."""
        return [(r, row.rstrip()) for r, row in enumerate(self.m.text()) if row.strip()]

    def screen_matrix(self):
        """Return full 30x80 screen matrix as list of strings."""
        return [row.rstrip() for row in self.m.text()]

    def prompt(self):
        """Return the Command/Status line (Row 0)."""
        return self.m.row(0).rstrip()

    def cursor(self):
        """Return (col, row) cursor position from hardware registers."""
        return (self.m.bus.video.cur_x() if hasattr(self.m.bus, 'video') else self.m.bus.mem[0xFF05],
                self.m.bus.video.cur_y() if hasattr(self.m.bus, 'video') else self.m.bus.mem[0xFF06])

    def print_screen(self, show_cursor=True):
        """Print the current screen with border and cursor marker."""
        print("+" + "-" * 80 + "+")
        rows = self.screen_matrix()
        cx, cy = self.cursor()
        for r, row in enumerate(rows):
            if row or (show_cursor and r == cy):
                line = row.ljust(80)
                if show_cursor and r == cy and cx < 80:
                    ch = line[cx] if cx < len(line) else ' '
                    line = line[:cx] + "\033[7m" + ch + "\033[0m" + line[cx+1:]
                print(f"|{line}| {r:2d}")
        print("+" + "-" * 80 + "+")

    def find_on_screen(self, text):
        """Find if text appears on screen, returns (row, col) or None."""
        for r, row in enumerate(self.m.text()):
            pos = row.find(text)
            if pos != -1:
                return (r, pos)
        return None

    def key(self, ch, frames=20):
        """Send keyboard character and advance frames."""
        self.m.key(ch)
        for _ in range(frames):
            self.m.run_frame()

    def type_key(self, ch, wait_idle=True, max_frames=50):
        """Send a single character and wait until Pascal is ready for input."""
        self.m.key(ch)
        # Advance at least 2 frames for IRQ to trigger and key to be consumed
        self.m.run_frame()
        self.m.run_frame()
        if not wait_idle:
            return self.prompt()

        # Settle until CPU PC returns to keyboard input loop (in_raw or ur_con_lp)
        input_pcs = {
            self.syms.get("in_raw.rk0"),
            self.syms.get("pm_sbios_unitread.ur_con_lp") + 3,
            self.syms.get("pm_sbios_unitread.ur_con_lp"),
            0x18AF, 0x07E4, 0x07C8
        }
        for f in range(max_frames):
            self.m.run_frame()
            if self.m.cpu.pc in input_pcs:
                break
        return self.prompt()

    def type_line(self, line):
        """Type a full line ending in return, waiting for each character."""
        for ch in line:
            self.type_key(ch)
        self.type_key("\r")
        return self.screen()

