#!/usr/bin/env python3
"""The host assembler, gated directly.

    python sim/test_cool8asm.py

**`tools/cool8asm.py` had no suite of its own.** Eight suites assemble
something and so would notice it break, but none of them asks it a
question about *assembly*: what a branch encodes to, what happens at
the edge of a displacement, whether a macro's local labels really are
local. A tool that everything depends on and nothing tests is the
shape this project has been bitten by before, and it is about to be
changed -- [D66](../docs/01-decisions.md) wants branch relaxation so a
twelve-kilobyte hand port is not fought one displacement at a time.

So this exists first, and deliberately pins **current** behaviour. A
characterisation suite is worth having even where the behaviour is
wrong: the point is that a change is visible, not that everything here
is desirable.

The encodings are not restated. `tools/opcodes.py` is normative and
this asks it what the answer should be, because a second opinion
written out by hand would only ever drift from it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness as H                                      # noqa: E402
from harness import check                                # noqa: E402

sys.path.insert(0, os.path.join(H.ROOT, "tools"))

import opcodes                                           # noqa: E402
import cool8asm                                          # noqa: E402


def opcodes_sig(mnemonic):
    """The opcode for a one-target instruction, asked of the table the
    assembler itself derives from `tools/opcodes.py`. Writing $72 here
    would be the second mnemonic table AGENTS.md says to stop at."""
    return cool8asm.TABLE[(mnemonic, ("N",))][0]


def asm(text, name="ta"):
    """Assemble a fragment at a known origin, or hand back the error."""
    return H.try_assemble_text(text, name) if hasattr(
        H, "try_assemble_text") else _try(text, name)


def _try(text, name):
    path = os.path.join(H.BUILD, name + ".asm")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return H.try_assemble(path)


def head(*body):
    return "        .org $0200\n" + "\n".join(body) + "\n"


def main():
    print("  A1 -- tools/cool8asm.py, asked about assembly")
    print()

    # ---- the table is opcodes.py's, so ask it rather than restate it
    code, why = asm(head("        NOP", "        RET"))
    check(code is not None, "a fragment assembles", str(why))
    if code is None:
        return H.report()

    # ---- branches, and the edge of the displacement.
    #
    # A REL8 displacement is measured from the *end* of the branch, so
    # a backward branch to a label 128 bytes behind the next
    # instruction is the last one that fits and 129 is the first that
    # does not. `.space` makes the distance exactly.
    ok, why = asm(head("back:   NOP",
                       "        .space 125",
                       "        BRA back"))
    check(ok is not None, "a backward branch at the edge of reach", str(why))

    # ---- past reach, the assembler grows the branch rather than
    # ---- refusing. [D66] added this: a hand port moves code
    # ---- constantly and every refusal was a routine reshaped around
    # ---- the assembler. sw/disasm.asm's jlo/jhs/jeq macros exist for
    # ---- no other reason.
    code, why = asm(head("back:   NOP",
                         "        .space 126",
                         "        BRA back"))
    check(code is not None, "a backward branch past reach is grown",
          str(why))

    code, why = asm(head("        BRA fwd",
                         "        .space 128",
                         "fwd:    NOP"))
    check(code is not None, "and a forward one", str(why))

    # **The bytes, not just that it assembled.** An unconditional
    # branch out of reach is simply a JMP; a conditional one becomes
    # its own inverse over a JMP, and the inverse comes from
    # opcodes.COND's ordering rather than a second table.
    jmp = opcodes_sig("JMP")
    code, why = asm(head("        BRA fwd",
                         "        .space 200",
                         "fwd:    NOP"))
    check(code is not None and code[0] == jmp,
          "BRA past reach becomes JMP, three bytes",
          None if code is None else "first byte $%02X" % code[0])

    code, why = asm(head("        BEQ fwd",
                         "        .space 200",
                         "fwd:    NOP"))
    want = [opcodes_sig("BNE"), 3, jmp]
    check(code is not None and list(code[:3]) == want,
          "BEQ past reach becomes BNE over a JMP",
          None if code is None else
          "got %s, wanted %s" % ([hex(b) for b in code[:3]],
                                 [hex(b) for b in want]))

    # **And it must still branch the same way**, which bytes alone do
    # not prove. Run both arms on the machine: the near branch and the
    # grown one have to reach the same answer.
    for cond, when, want in (("BEQ", "SUB  R0,R0", 1), ("BEQ", "MOV R0,#1", 2)):
        code, why = asm(head("        MOV  R1,#0",
                             "        " + when,
                             "        %s taken" % cond,
                             "        MOV  R1,#2",
                             "        JMP  done",
                             "        .space 200",
                             "taken:  MOV  R1,#1",
                             "done:   HALT"), "tarun")
        if code is None:
            check(False, "a grown %s still branches" % cond, str(why))
            continue
        m = H.machine()
        m.bus.mem[0x0200:0x0200 + len(code)] = code
        m.cpu.pc, m.cpu.sp, m.romen = 0x0200, 0x7FF0, False
        m.run(budget=100_000)
        check(m.cpu.r[1] == want,
              "a grown %s branches as a near one would (%s)" % (cond, when),
              "R1 = %d, wanted %d" % (m.cpu.r[1], want))

    # ---- a branch encodes from the end of the instruction, and the
    # ---- sign is what a hand-written table gets wrong.
    code, why = asm(head("here:   BRA here"))
    check(code is not None and code[1] == 0xFE,
          "a branch to itself is -2, measured from the next instruction",
          None if code is None else "disp $%02X" % code[1])

    code, why = asm(head("        BRA fwd", "fwd:    NOP"))
    check(code is not None and code[1] == 0x00,
          "and to the very next instruction is 0",
          None if code is None else "disp $%02X" % code[1])

    # ---- macros, and the local labels inside one.
    #
    # A macro used twice in one routine would collide on any label it
    # declares, so `@name` becomes a local of the enclosing global.
    # Without that, sw/disasm.asm's jlo/jhs/jeq could be used once per
    # routine and no more.
    code, why = asm(head(
        "        .macro SKIPZ",
        "        BNE @on",
        "        NOP",
        "@on:",
        "        .endm",
        "r:      SKIPZ",
        "        SKIPZ",
        "        RET"))
    check(code is not None, "a macro twice in one routine", str(why))

    # ---- the assembler refuses what it cannot encode, rather than
    # ---- emitting something plausible.
    ok, why = asm(head("        MOV  R0,#$1234"))
    check(ok is None, "an immediate too wide for the operand is refused",
          str(why)[:80])

    ok, why = asm(head("        JMP  nowhere"))
    check(ok is None and "nowhere" in str(why),
          "an undefined symbol is named", str(why)[:80])

    # ---- the trap AGENTS.md records: operands split on commas before
    # ---- character literals are recognised, so `#','` is three
    # ---- operands and nothing matches. Pinned because the error is
    # ---- otherwise mystifying and the workaround is `#$2C`.
    ok, why = asm(head("        MOV  R0,#','"))
    check(ok is None, "a comma character literal is still refused",
          str(why)[:80])
    code, why = asm(head("        MOV  R0,#$2C"))
    check(code is not None, "and $2C is how it is written", str(why))

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
