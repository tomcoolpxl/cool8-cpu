#!/usr/bin/env python3
"""S3 -- the code emitter, gated byte for byte against the assembler.

    python sim/test_emit.py

`sw/emit.bas` is the back end of the self-hosted compiler, and it runs on
the machine. This drives it with a program chosen to exercise every
addressing mode the compiler emits, plus the thing that is actually hard
in one pass -- naming an address before you know what it is -- and then
compares what the machine produced with what `tools/cool8asm.py`
produces from the same program written as text.

Identical, or it fails. There is no partial credit for a code generator.

## What the program is chosen to hit

  every addressing mode   ALU immediate and register, [X]/[Y], indexed,
                          [SP+u8], [abs16]
  a backward branch       the displacement is known when it is emitted
  a forward branch        it is not, so the site has to be patched later
  two forward branches    to the SAME label, so the chain has to have
                          more than one link in it
  a forward JMP and CALL  16-bit sites, which chain differently from
                          8-bit ones, and to a label that also has
                          branches pending -- so both chains have to
                          survive each other

## Why the size is printed

S3 is where the plan says the size risk gets measured. The emitter is
the most assembly-shaped part of the compiler, so what it costs in COOL8
BASIC against the Python it replaces is the number the rest of the
compiler gets extrapolated from.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import cool8rsvm as vm                                   # noqa: E402
import cool8bas as bas                                   # noqa: E402

ROOT, BUILD = H.ROOT, H.BUILD

ORG = 0x0200            # where the driver runs
CODE = 0x6000           # where it emits
FAILS = H.FAILS


# The program, twice: once as calls into the emitter, once as text for
# the assembler. Writing it twice is the point -- a single source could
# only ever agree with itself.
#
# Labels: 0 = loop (backward), 1 = done (forward, three sites), 2 = sub.
DRIVER = """
INCLUDE "emit.bas"

CALL estart($6000)

CALL ealui(E_MOV, 0, 10)
CALL ealui(E_MOV, 1, 0)
CALL elab(0)
CALL ealur(E_ADD, 1, 0)
CALL eldst(2, 0, 0)
CALL eldst(2, 1, 1)
CALL eldstd(3, 0, 0, 5)
CALL eldstd(3, 1, 1, 100)
CALL eldstsp(0, 0, 4)
CALL eldstsp(1, 1, 6)
CALL eldstabs(2, 0, $1234)
CALL eldstabs(3, 1, $ABCD)
CALL ealui(E_SUB, 0, 1)
CALL ebr(C_EQ, 1)
CALL ecall(2)
CALL ealui(E_CMP, 1, 200)
CALL ebr(C_CS, 1)
CALL ebr(C_RA, 0)
CALL ejmp(1)
CALL elab(1)
CALL ealui(E_MOV, 0, 0)
CALL eb($22)
CALL elab(2)
CALL ealur(E_MOV, 3, 2)
CALL eb($22)
POKE $7F00, cp AND 255
POKE $7F01, cp >> 8
END
"""

SOURCE = """
        .org $6000
        MOV  R0,#10
        MOV  R1,#0
loop:   ADD  R1,R0
        LD   R2,[X]
        ST   [Y],R2
        LD   R3,[X+5]
        ST   [Y+100],R3
        LD   R0,[SP+4]
        ST   [SP+6],R1
        LD   R2,[$1234]
        ST   [$ABCD],R3
        SUB  R0,#1
        BEQ  done
        CALL sub
        CMP  R1,#200
        BCS  done
        BRA  loop
        JMP  done
done:   MOV  R0,#0
        RET
sub:    MOV  R3,R2
        RET
"""


def compile_bas(src, org, name):
    code, _ = H.compile_bas(src, name, org=org)
    return code


def assemble(apath, name):
    code, _ = H.assemble(apath, name=name)
    return code


def main():
    print("  S3 -- sw/emit.bas, against tools/cool8asm.py")
    print()

    # What the assembler makes of the program.
    spath = os.path.join(BUILD, "emit_ref.asm")
    with open(spath, "w") as fh:
        fh.write(SOURCE)
    want = assemble(spath, "emit_ref")

    # What the machine makes of it.
    code = compile_bas(DRIVER, ORG, "emit_drv")
    print(f"  driver + emitter: {len(code):,} bytes")

    m = vm.Machine()
    m.bus.mem[ORG:ORG + len(code)] = code
    m.cpu.pc = ORG
    m.cpu.sp = 0xFFF7
    m.romen = False
    # END compiles to HALT; the emulator has no halted flag, so stop
    # when the program counter stops moving.
    # m.run, not a stepping loop: the machine advances the raster and
    # the interrupt flags and a bare loop does not (AGENTS.md).
    if m.run(budget=20_000_000) != "halt":
        raise SystemExit("the driver never halted")

    end = m.bus.mem[0x7F00] | (m.bus.mem[0x7F01] << 8)
    got = bytes(m.bus.mem[CODE:end])

    check(len(got) == len(want),
          f"the machine emitted {len(got)} bytes, the assembler {len(want)}",
          f"{len(got)} against {len(want)}")

    if len(got) == len(want):
        bad = [i for i in range(len(want)) if got[i] != want[i]]
        check(not bad, "and every one of them is identical",
              f"{len(bad)} differ, first at +{bad[0]:02X}: "
              f"{got[bad[0]]:02X} against {want[bad[0]]:02X}"
              if bad else "")
    else:
        check(False, "and every one of them is identical",
              f"got  {got.hex()}\n    want {want.hex()}")

    print()
    print("PASS" if not FAILS else f"FAIL -- {len(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
