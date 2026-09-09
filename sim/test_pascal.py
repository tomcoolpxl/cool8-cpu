#!/usr/bin/env python3
"""sim/test_pascal.py -- Test UCSD Pascal p-System II.0 on COOL8.

Tests:
1. Assembly and packaging of PASCAL.BIN and Drive 15 (PASCAL) volume.
2. VM boot and execution of P-Machine core.
3. Verification of opcode execution and system startup.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8disk as disk
import cool8rsvm as vm
import harness as H


class TestPascal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Assemble pascal.asm
        asm_path = os.path.join(ROOT, "sw", "pascal", "pascal.asm")
        cls.code, cls.syms = H.assemble(asm_path, name="pascal", write=True)

        # Ensure demos.img has Drive 15 packaged
        img_path = os.path.join(ROOT, "demos.img")
        if not os.path.exists(img_path):
            disk.make_image(img_path)
        vol_path = os.path.join(ROOT, "tools", "ucsd-psystem-vm", "disk-images", "system.vol")
        if os.path.exists(vol_path):
            with open(vol_path, "rb") as f:
                system_vol = f.read()
            im = disk.Image(img_path)
            v15 = disk.vol_base(disk.PASCAL_VOL)
            im.data[v15:v15 + len(system_vol)] = system_vol
            im.save()
        cls.img_path = img_path

    def test_assembly_size(self):
        """P-Machine native interpreter must fit in designated memory budget ($0200-$2FFF = 11776 bytes)."""
        self.assertLess(len(self.code), 11776, f"PASCAL.BIN is {len(self.code)} bytes (budget 11776 bytes)")
        print(f"PASCAL.BIN size: {len(self.code)} bytes")

    def test_boot_pascal(self):
        """Boot PASCAL.BIN on the VM and verify P-Machine initialization and command prompt."""
        m = vm.boot(flash_path=self.img_path, render=True)
        org = 0x0200
        m.bus.mem[org:org + len(self.code)] = self.code
        m.cpu.pc = org
        m.cpu.sp = 0x0200
        m.romen = False

        # Run 100 frames to reach command prompt
        for _ in range(100):
            m.run_frame()

        # Check that main command prompt is displayed on Row 0
        r0 = m.row(0)
        self.assertTrue(r0.startswith("Command: E(dit, R(un"), f"Row 0 was: {r0!r}")

        # Test interactive toggle via '?'
        m.key("?")
        for _ in range(20):
            m.run_frame()
        r0_page2 = m.row(0)
        self.assertTrue(r0_page2.startswith("Command: U(ser restart"), f"Row 0 after ? was: {r0_page2!r}")

        # Toggle back
        m.key("?")
        for _ in range(20):
            m.run_frame()
        self.assertTrue(m.row(0).startswith("Command: E(dit, R(un"))

    def test_filer_navigation(self):
        """Test launching Filer, date utility, and quitting back to main prompt."""
        m = vm.boot(flash_path=self.img_path, render=True)
        org = 0x0200
        m.bus.mem[org:org + len(self.code)] = self.code
        m.cpu.pc = org
        m.cpu.sp = 0x0200
        m.romen = False

        for _ in range(100):
            m.run_frame()

        # Enter Filer
        m.key("F")
        for _ in range(30):
            m.run_frame()
        self.assertTrue(m.row(0).startswith("Filer: G(et, S(ave"), f"Row 0 was: {m.row(0)!r}")

        # Quit Filer
        m.key("Q")
        for _ in range(30):
            m.run_frame()
        self.assertTrue(m.row(0).startswith("Command: E(dit, R(un"), f"Row 0 after Q was: {m.row(0)!r}")

    def test_editor_and_compiler_launch(self):
        """Test launching the UCSD Pascal Screen Editor and Compiler."""
        m = vm.boot(flash_path=self.img_path, render=True)
        org = 0x0200
        m.bus.mem[org:org + len(self.code)] = self.code
        m.cpu.pc = org
        m.cpu.sp = 0x0200
        m.romen = False

        for _ in range(100):
            m.run_frame()

        # Launch Compiler with 'C'
        m.key("C")
        for _ in range(30):
            m.run_frame()
        self.assertTrue("Compil" in m.row(0), f"Row 0 after C was: {m.row(0)!r}")

    def test_compiler_compiles_hello(self):
        """Test loading HELLO.TEXT via Filer and compiling with SYSTEM.COMPILER."""
        m = vm.boot(flash_path=self.img_path, render=True)
        org = 0x0200
        m.bus.mem[org:org + len(self.code)] = self.code
        m.cpu.pc = org
        m.cpu.sp = 0x0200
        m.romen = False

        for _ in range(100):
            m.run_frame()

        # Enter Filer
        m.key("F")
        for _ in range(30):
            m.run_frame()

        # Get HELLO
        m.key("G")
        for _ in range(20):
            m.run_frame()
        for ch in "HELLO\r":
            m.key(ch)
            for _ in range(5):
                m.run_frame()
        for _ in range(30):
            m.run_frame()

        # Quit Filer
        m.key("Q")
        for _ in range(30):
            m.run_frame()

        # Launch Compiler with 'C'
        m.key("C")
        for _ in range(30):
            m.run_frame()

        for ch in "HELLO\r":
            m.key(ch)
            for _ in range(5):
                m.run_frame()

        for _ in range(30):
            m.run_frame()

        # Specify output codefile HELLO
        for ch in "HELLO\r":
            m.key(ch)
            for _ in range(5):
                m.run_frame()
        for _ in range(180):
            m.run_frame()

        screen = "\n".join(f"[{r:02d}] {m.row(r)}" for r in range(30) if m.row(r).strip())
        print(f"\nCompiler screen output:\n{screen}\n")
        self.assertNotIn("error", screen.lower())

        # Execute compiled program with 'X'
        m.key("X")
        for _ in range(30):
            m.run_frame()
        for ch in "HELLO\r":
            m.key(ch)
            for _ in range(5):
                m.run_frame()
        for _ in range(60):
            m.run_frame()

        exec_screen = "\n".join(f"[{r:02d}] {m.row(r)}" for r in range(30) if m.row(r).strip())
        self.assertIn("Welcome to UCSD Pascal", exec_screen)

    def test_launch_from_basic(self):
        """Test booting BASIC, executing DRIVE 13: LOAD 'PASCAL': RUN, and entering Pascal."""
        import test_basic as B
        bcode, bsyms = B.build()
        m = vm.boot(flash_path=self.img_path, render=True)

        for _ in range(50):
            m.run_frame()
        H.settle(m, bsyms)

        H.key(m, bsyms, "DRIVE 13\r")
        H.key(m, bsyms, 'LOAD "PASCAL"\r')

        # Type RUN
        for ch in "RUN\r":
            m.key([ch])
            for _ in range(5):
                m.run_frame()

        for _ in range(120):
            m.run_frame()
            if m.row(0).startswith("Command: E(dit, R(un"):
                break

        self.assertTrue(m.row(0).startswith("Command: E(dit, R(un"),
                        f"Failed to reach Pascal prompt from BASIC RUN, row 0 was: {m.row(0)!r}")

        # Now press 'F'
        m.key("F")
        for _ in range(30):
            m.run_frame()
        self.assertTrue(m.row(0).startswith("Filer: G(et, S(ave"),
                        f"Failed to enter Filer from BASIC launch, row 0 was: {m.row(0)!r}")

    def test_editor_insert_and_quit(self):
        """Test typing code in Editor, accepting with ETX, and quitting back to command prompt."""
        m = vm.boot(flash_path=self.img_path, render=True)
        org = 0x0200
        m.bus.mem[org:org + len(self.code)] = self.code
        m.cpu.pc = org
        m.cpu.sp = 0x0200
        m.romen = False

        for _ in range(100):
            m.run_frame()

        # Enter Editor and open blank buffer
        m.key("E")
        for _ in range(40):
            m.run_frame()
        m.key("\r")
        for _ in range(40):
            m.run_frame()
        self.assertIn("Edit:", m.row(0))

        # Enter Insert mode
        m.key("I")
        for _ in range(40):
            m.run_frame()
        self.assertIn("Insert:", m.row(0))

        # Type code
        text = "PROGRAM HELLO;"
        for ch in text:
            m.key(ch)
            for _ in range(10):
                m.run_frame()
        self.assertTrue(m.row(1).startswith(text), f"Row 1 text was: {m.row(1)!r}")

        # Accept with ETX (\x03)
        m.type("\x03")
        for _ in range(50):
            m.run_frame()
        self.assertIn("Edit:", m.row(0))

        # Quit editor
        m.key("Q")
        for _ in range(50):
            m.run_frame()
        self.assertIn("Quit:", m.row(0))

        # Exit without updating
        m.key("E")
        for _ in range(80):
            m.run_frame()
        self.assertTrue(m.row(0).startswith("Command: E(dit, R(un"),
                        f"Failed to return to Command prompt, row 0 was: {m.row(0)!r}")


if __name__ == "__main__":
    unittest.main()
