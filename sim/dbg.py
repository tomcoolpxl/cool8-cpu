#!/usr/bin/env python3
"""Debugging the self-hosted compiler from outside it.

The compiler runs on the emulated machine, so when it goes wrong the
only thing to hand is a program counter. That is not enough, and finding
out the hard way cost a day: a misaligned disassembly said `MOV R0,#$00`
six times running while the machine was executing data, and the first
*symptom* was ten thousand steps after the first *fault*.

So this gives four things the raw machine does not.

**Exact disassembly.** Every routine is decoded forward from its label,
so instruction boundaries are known rather than guessed. An address that
is not a boundary is reported as such -- which is itself the answer,
because it means control has left the rails.

**The first fault, not the tenth.** A shadow call stack pairs every CALL
with its RET. The moment one returns somewhere it was not called from,
that is the fault; everything after is consequence.

**Where the compiler was in the program it was compiling.** The stored
program is a chain of records, each starting with its line number, and
the compiler keeps its position in `lxrec`. Reading it turns "$5A38"
into "line 70", which is the difference between a puzzle and a bug.

**A side-by-side diff of the two code streams**, aligned on instruction
boundaries, stopping at the first structural difference rather than the
first differing byte -- an operand that differs because everything after
it shifted is noise.
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get("COOL8_BUILD") or os.path.join(HERE, "build")
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cool8vm as vm                                     # noqa: E402
import cool8bas as bas                                   # noqa: E402
import opcodes                                           # noqa: E402


class Image:
    """A compiled driver, with its symbols and an exact instruction map."""

    def __init__(self, source, org=0x0200, name="dbg"):
        asm = bas.compile_source(source, org)
        apath = os.path.join(BUILD, name + ".asm")
        with open(apath, "w") as fh:
            fh.write(asm)
        out = os.path.join(BUILD, name + ".bin")
        sym = os.path.join(BUILD, name + ".sym")
        r = subprocess.run([sys.executable,
                            os.path.join(ROOT, "tools", "cool8asm.py"),
                            apath, "-o", out, "--symbols", sym,
                            "-I", os.path.join(ROOT, "sw")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(r.stdout + r.stderr)
        with open(out, "rb") as fh:
            self.code = fh.read()
        self.org = org
        self.end = org + len(self.code)
        self.sym = {}
        for line in open(sym):
            p = line.split()
            if len(p) == 2:
                self.sym[p[1]] = int(p[0], 16)
        self.addr = sorted((a, n) for n, a in self.sym.items())
        # How wide each variable is, from the .res directives -- the
        # symbol table gives addresses but not sizes, and guessing them
        # printed convincing nonsense.
        self.size = {}
        for line in open(apath):
            m = re.match(r"\s*([A-Za-z_][\w]*):\s*\.res\s+(\d+)", line)
            if m:
                self.size[m.group(1)] = int(m.group(2))
        self.entries = {a: n for n, a in self.sym.items()
                        if n.startswith("s_") and "." not in n}
        self._map_instructions()

    # ---------------------------------------------------------- symbols

    def name(self, a):
        lo = None
        for ad, n in self.addr:
            if ad <= a:
                lo = (ad, n)
            else:
                break
        if lo is None:
            return f"${a:04X}"
        return f"{lo[1]}+{a - lo[0]}" if a != lo[0] else lo[1]

    def _map_instructions(self):
        """Decode forward from every routine label.

        Walking from a known start is the whole point: decoding from an
        arbitrary address gives plausible-looking nonsense.
        """
        self.insn = {}
        self.length = {}
        def rd(a):
            i = a - self.org
            return self.code[i] if 0 <= i < len(self.code) else 0
        # Seed from everything that is code: main and the runtime
        # helpers are not s_ labels, and leaving them unmapped made the
        # boundary check fire on the program's first jump.
        seeds = set(self.entries)
        seeds.add(self.org)
        for n, a in self.sym.items():
            if "." in n or n.startswith(("v_", "a_", "str_")):
                continue
            seeds.add(a)
        for start in sorted(seeds):
            a = start
            while self.org <= a < self.end:
                if a in self.insn:
                    break
                text, n = opcodes.disassemble(rd, a)
                if n <= 0:
                    break
                self.insn[a] = text
                self.length[a] = n
                if text.split()[0] in ("RET", "RETI", "HALT"):
                    a += n
                    if a in self.insn or a not in self.entries:
                        # keep going: routines sit end to end
                        pass
                    continue
                a += n

    def at(self, a):
        return self.insn.get(a)


class Fault(Exception):
    pass


class Run:
    """The machine, watched."""

    def __init__(self, img, src=None, stored=b"", out=0xA000, sp=0x7FF0):
        self.img = img
        self.m = vm.Machine()
        self.m.bus.mem[img.org:img.end] = img.code
        if src is not None:
            self.m.bus.mem[src:src + len(stored)] = stored
        self.m.cpu.pc = img.org
        # NOT $FFF7. OS_PLAN's map gives the stack $FF00-$FFFF, and
        # directly below it is the I/O page at $FE00-$FEFF -- so a stack
        # that grows past 250 bytes pushes return addresses into
        # hardware registers, where they are quietly lost. The compiler
        # spends six frames per level of parenthesis and goes far past
        # that. It runs with a deep stack in the user area instead.
        self.m.cpu.sp = sp
        self.m.romen = False
        self.out = out
        self.stack = []
        self.trail = []

    # ------------------------------------------------ where the compiler is

    def source_line(self):
        """The line number of the record the lexer is on, if it is on one."""
        a = self.img.sym.get("v_lxrec")
        if a is None:
            return None
        rec = self.m.bus.mem[a] | (self.m.bus.mem[a + 1] << 8)
        if not 0x0200 <= rec <= 0xFFFD:
            return None
        return self.m.bus.mem[rec] | (self.m.bus.mem[rec + 1] << 8)

    def report(self, why):
        img = self.img
        out = [f"  FAULT: {why}",
               f"    pc=${self.m.cpu.pc:04X} ({img.name(self.m.cpu.pc)}) "
               f"sp=${self.m.cpu.sp:04X}"]
        ln = self.source_line()
        if ln is not None:
            out.append(f"    the compiler was on line {ln} of the program "
                       f"it was compiling")
        here = img.at(self.m.cpu.pc)
        out.append(f"    instruction: {here}" if here else
                   "    pc is NOT at an instruction boundary -- control "
                   "has left the code")
        sp = self.m.cpu.sp
        mem = self.m.bus.mem
        window = " ".join(f"{mem[a] & 0xFF:02X}" for a in
                          range(max(0, sp - 6), min(0x10000, sp + 6)))
        out.append(f"    stack ${sp - 6:04X}..${sp + 5:04X}: {window}"
                   f"   (sp marks byte 7)")
        if self.stack:
            out.append("    call stack, innermost last:")
            for ret, who, sp0 in self.stack[-8:]:
                out.append(f"      {who:<22} returns to {img.name(ret)} "
                           f"(sp was ${sp0:04X})")
        if self.trail:
            out.append("    routines entered, most recent last:")
            out.append("      " + " ".join(self.trail[-12:]))
        return "\n".join(out)

    def state(self, *names):
        """The compiler's own variables, by name, decoded.

        This is the "halt and look at RAM" that the raw machine does not
        give you: the symbol table already says where `v_nsym` lives and
        how wide it is, so there is no reason to be reading hex.
        """
        img, mem = self.img, self.m.bus.mem
        if not names:
            names = ("cerr", "nsym", "cp", "ctmax", "ctmps", "clab",
                     "nloc", "inbody", "cfrm", "cbtot", "cloc", "spend",
                     "nn", "tk", "tsl", "equiet", "nfx")
        out = []
        for n in names:
            a = img.sym.get("v_" + n)
            if a is None:
                continue
            if img.size.get("v_" + n, 1) == 1:
                out.append(f"{n}={mem[a]}")
            else:
                out.append(f"{n}=${mem[a] | (mem[a + 1] << 8):04X}")
        ln = self.source_line()
        if ln is not None:
            out.append(f"line={ln}")
        return "  ".join(out)

    def watch(self, lo, hi=None):
        """Report every write into an address range, with the culprit.

        Hand-rolled three times while chasing one bug; permanent now.
        """
        hi = lo if hi is None else hi
        bus = self.m.bus
        orig = bus.write
        self.hits = []
        img = self.img
        run = self

        def guard(a, v):
            if lo <= a <= hi:
                pc = run.m.cpu.pc
                run.hits.append(
                    f"    ${a:04X}=${v:02X} sp=${run.m.cpu.sp:04X} "
                    f"by {img.name(pc)}: {img.at(pc) or '(not an instruction)'}"
                    + (f"  line {run.source_line()}"
                       if run.source_line() else ""))
            orig(a, v)
        bus.write = guard

    # ------------------------------------------------------------- running

    def go(self, limit=200_000_000, stop_at=None):
        """Until HALT, or a breakpoint, or something structurally wrong.

        `stop_at` is a routine name -- run stops on entry to it and
        returns, so the caller can look around with state() and step on.
        """
        img = self.img
        mem = self.m.bus.mem
        brk = img.sym.get("s_" + stop_at) if stop_at else None
        last = -1
        for _ in range(limit):
            pc = self.m.cpu.pc
            if pc == last:
                return                              # HALT
            if pc == brk:
                return "breakpoint"
            last = pc
            op = mem[pc]
            if pc in img.entries:
                self.trail.append(img.entries[pc][2:])
            # tick, not cpu.step: the machine advances the raster and
            # the interrupt flags, and code being debugged may be
            # waiting on one.
            self.m.tick()
            new = self.m.cpu.pc
            if op == 0x29:
                self.stack.append((pc + 3, img.entries.get(new, img.name(new)),
                                   self.m.cpu.sp))
            elif op in (0x2C, 0x2D):
                self.stack.append((pc + 1, img.entries.get(new, img.name(new)),
                                   self.m.cpu.sp))
            elif op == 0x22:
                if not self.stack:
                    raise Fault(self.report("RET with no CALL outstanding"))
                want, who, sp0 = self.stack.pop()
                # A routine must leave the stack where it found it. When
                # it does not, the return address it pops is somebody
                # else's -- and this names the routine, where the bad
                # return only names its victim.
                if self.m.cpu.sp != sp0 + 2:
                    self.m.cpu.pc = pc
                    raise Fault(self.report(
                        f"{who} left the stack {self.m.cpu.sp - sp0 - 2:+d} "
                        f"bytes from where it found it"))
                if new != want:
                    self.m.cpu.pc = pc              # report at the RET
                    raise Fault(self.report(
                        f"{who} returned to ${new:04X} ({img.name(new)}), "
                        f"but was called from ${want:04X} "
                        f"({img.name(want)})"))
            if not (img.org <= new < img.end):
                raise Fault(self.report(
                    f"control left the code, to ${new:04X}"))
            # The check that depends on nothing else: every program
            # counter must be the start of an instruction. The first
            # time it is not is the first fault, whatever the shadow
            # call stack thinks -- because once execution is misaligned
            # every opcode it reads afterwards is fiction.
            if new not in img.insn:
                self.m.cpu.pc = pc
                raise Fault(self.report(
                    f"jumped to ${new:04X}, which is not an instruction"))
            # Falling off the end of one routine into the next one's
            # label. In this language that is a FUNCTION with a path
            # that reaches END FUNCTION without a RETURN, and it is
            # invisible until some later RET pops the wrong frame.
            if new in img.entries and pc in img.length:
                if pc + img.length[pc] == new and op not in (
                        0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D):
                    raise Fault(self.report(
                        f"fell through into {img.entries[new]} -- the "
                        f"routine before it ends without returning"))
        raise Fault(self.report(f"still running after {limit:,} steps"))

    def word(self, a):
        return self.m.bus.mem[a] | (self.m.bus.mem[a + 1] << 8)


class Profile:
    """Where the clocks went, by routine.

    Guessing does not work. Flattening the interpreter's expression
    evaluator from three nested calls per operand to one was an obvious
    win on paper and moved a benchmark by 1.6 % -- because the cost was
    somewhere else entirely. This says where.

    Attribution is by nearest preceding code label, and the cost of an
    instruction is the emulator's own cycle count for it, so the numbers
    add up to the total rather than approximating it.
    """

    def __init__(self, syms, org, end):
        self.org, self.end = org, end
        # code labels only: v_ and a_ are data, and a dotted name is a
        # local label, which is the granularity we want to keep
        self.labels = sorted(
            (a, n) for n, a in syms.items()
            if org <= a < end and not n.startswith(("v_", "a_", "str_")))
        self.by = {}
        self.total = 0

    def _who(self, pc):
        lo = None
        for a, n in self.labels:
            if a <= pc:
                lo = n
            else:
                break
        return lo or f"${pc:04X}"

    def run(self, m, limit=80_000_000):
        """Step to a halt, charging each instruction to its routine."""
        last = -1
        for _ in range(limit):
            pc = m.cpu.pc
            if pc == last:
                break
            last = pc
            before = m.cpu.cycles
            m.tick()
            cost = m.cpu.cycles - before
            who = self._who(pc)
            self.by[who] = self.by.get(who, 0) + cost
            self.total += cost
        return self.total

    def report(self, top=14, roll=True):
        """Roll local labels up into the routine that owns them."""
        rows = {}
        for n, c in self.by.items():
            key = n.split(".")[0] if roll else n
            rows[key] = rows.get(key, 0) + c
        out = [f"  {self.total:,} clocks total"]
        for n, c in sorted(rows.items(), key=lambda kv: -kv[1])[:top]:
            out.append(f"    {n:<22}{c:>10,}  {100*c/self.total:>5.1f}%")
        rest = self.total - sum(sorted(rows.values(), reverse=True)[:top])
        if rest > 0:
            out.append(f"    {'the rest':<22}{rest:>10,}")
        return "\n".join(out)


# ------------------------------------------------------------- comparing

def walk(buf, base, limit):
    """(address, text, length) for each instruction in a byte stream."""
    out, a = [], 0
    while a < limit:
        text, n = opcodes.disassemble(
            lambda i: buf[i] if 0 <= i < len(buf) else 0, a)
        if n <= 0:
            break
        out.append((base + a, text, n))
        a += n
    return out


def diff(got, want, base, limit_got=None, limit_want=None):
    """The first structural difference between two code streams.

    Structural, not byte-for-byte: once one stream is a byte longer,
    every address operand after it differs and a byte diff drowns in
    noise. Comparing mnemonics finds where the streams actually parted.
    """
    A = walk(want, base, limit_want if limit_want is not None else len(want))
    B = walk(got, base, limit_got if limit_got is not None else len(got))
    for i in range(max(len(A), len(B))):
        x = A[i] if i < len(A) else None
        y = B[i] if i < len(B) else None
        if x is None or y is None or x[1].split()[0] != y[1].split()[0]:
            lines = ["    reference                | machine"]
            for j in range(max(0, i - 5), min(max(len(A), len(B)), i + 5)):
                p = f"{A[j][0]:04X} {A[j][1]}" if j < len(A) else "-"
                q = f"{B[j][0]:04X} {B[j][1]}" if j < len(B) else "-"
                mark = "   <<<" if j == i else ""
                lines.append(f"    {p:<24} | {q:<24}{mark}")
            return "\n".join(lines)
    if len(want) != len(got):
        return f"    same instructions, different length: {len(got)} " \
               f"against {len(want)}"
    bad = [i for i in range(len(want)) if want[i] != got[i]]
    if bad:
        i = bad[0]
        return (f"    same instructions; {len(bad)} operand bytes differ, "
                f"first at +${i:04X}: ${got[i]:02X} against ${want[i]:02X}")
    return None
