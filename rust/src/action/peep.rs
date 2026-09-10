//! The peephole pass: loads the registers already hold, removed.
//!
//! The generator evaluates every statement into R0 (or R1:R0) from
//! memory and stores the result back, and the next statement loads it
//! again. In the Byte sieve that was `ST [v_i],R0 / ST [v_i+1],R1 /
//! LD R0,[v_i] / LD R1,[v_i+1]` at the top of every loop, and `i + i`
//! loaded `i` twice into two register pairs -- eight and sixteen clocks
//! of nothing, in the loop that was 35 % of the run. The generator is
//! not made cleverer about it; this pass walks the code it produced
//! with one fact per register -- which memory byte, if any, it is known
//! to equal -- and turns a load of a byte a register already holds into
//! a `MOV` from that register (2 clocks against 3 or 4), or into
//! nothing when it is the same register.
//!
//! What it must never do is believe a fact past the point it stops
//! being true, so the facts are dropped:
//!
//! - at every label -- another path may arrive with anything;
//! - at every `CALL` -- the callee clobbers every register and may
//!   store anywhere;
//! - on a store through `X` or `Y` -- it may have hit the byte a
//!   register was known to equal (`*p = v` where `p` points at a
//!   global);
//! - for the `[SP+n]` facts, on anything that moves `SP` -- the same
//!   text names a different byte afterwards;
//! - for every register an instruction writes.
//!
//! Hardware registers, which the generator writes as `[$FFxx]`, are
//! never cached: a status register read twice must be read twice. Any
//! `[$....]` operand is treated that way, which also keeps a variable
//! bound to a RAM address out of the game.
//!
//! **Flags.** `LD` sets Z and N and `MOV` does not (02-isa.md 1.2), so
//! replacing one with the other changes the flags. The generator never
//! branches on a load's flags -- every condition it emits is a `CMP` or
//! an `OR` of its own -- and `ASM` blocks and the runtime routines are
//! raw lines this pass does not touch and treats as walls.

use super::codegen::LineKind;

const REGS: [&str; 4] = ["R0", "R1", "R2", "R3"];

fn reg_index(s: &str) -> Option<usize> {
    REGS.iter().position(|r| *r == s)
}

/// A memory operand the pass may reason about: a local or a global by
/// name, never a pointer and never an absolute address.
fn cacheable(op: &str) -> bool {
    op.starts_with("[SP+")
        || (op.starts_with('[') && !op.contains('$') && !op.starts_with("[X") && !op.starts_with("[Y"))
}

fn split(line: &str) -> (String, Vec<String>) {
    let mut it = line.splitn(2, char::is_whitespace);
    let mn = it.next().unwrap_or("").to_uppercase();
    let ops = it
        .next()
        .map(|rest| rest.split(',').map(|o| o.trim().to_string()).collect())
        .unwrap_or_default();
    (mn, ops)
}

pub fn optimise(lines: &[(LineKind, String)]) -> Vec<(LineKind, String)> {
    let mut out: Vec<(LineKind, String)> = Vec::with_capacity(lines.len());
    // what each of R0..R3 is known to equal: a memory operand string
    let mut known: [Option<String>; 4] = [None, None, None, None];

    let forget_all = |known: &mut [Option<String>; 4]| {
        for k in known.iter_mut() {
            *k = None;
        }
    };
    let forget_sp = |known: &mut [Option<String>; 4]| {
        for k in known.iter_mut() {
            if k.as_deref().map_or(false, |s| s.starts_with("[SP+")) {
                *k = None;
            }
        }
    };
    let forget_mem = |known: &mut [Option<String>; 4], loc: &str, except: Option<usize>| {
        for (i, k) in known.iter_mut().enumerate() {
            if Some(i) != except && k.as_deref() == Some(loc) {
                *k = None;
            }
        }
    };

    // the join labels: a BEQ/BNE into one is the high-byte half of a
    // word compare whose carry the branch after the join still reads
    let joins: std::collections::HashSet<&str> = lines
        .iter()
        .filter(|(k, _)| *k == LineKind::Join)
        .map(|(_, t)| t.as_str())
        .collect();

    for (n, (kind, text)) in lines.iter().enumerate() {
        match kind {
            LineKind::Label | LineKind::Raw => {
                forget_all(&mut known);
                out.push((kind.clone(), text.clone()));
                continue;
            }
            LineKind::Join => {
                out.push((kind.clone(), text.clone()));
                continue;
            }
            LineKind::Code => {}
        }
        let (mn, ops) = split(text);
        // `LD` sets Z and N from what it loaded (02-isa.md 1.2), so the
        // `OR Rd,Rd` or `CMP Rd,#0` the generator puts before a BEQ/BNE
        // is nothing when the line before it -- as emitted, not as
        // written, since a load this pass turned into a MOV sets no
        // flags -- loaded that register. Only for a BEQ/BNE that ends
        // the condition: CMP #0 also sets C, which the BLO/BHS/BLS/BHI
        // after a word compare's join still reads, so a branch *into*
        // a join keeps its CMP. The first version dropped that one and
        // every WHILE n > 0 ran zero times.
        if (mn == "OR" && ops.len() == 2 && ops[0] == ops[1] && reg_index(&ops[0]).is_some())
            || (mn == "CMP" && ops.len() == 2 && ops[1] == "#0" && reg_index(&ops[0]).is_some())
        {
            let prev_ld = out.last().map_or(false, |(k, t)| {
                *k == LineKind::Code && {
                    let (pm, po) = split(t);
                    pm == "LD" && po.first() == Some(&ops[0])
                }
            });
            let next_zbr = lines.get(n + 1).map_or(false, |(k, t)| {
                *k == LineKind::Code && {
                    let (nm, no) = split(t);
                    (nm == "BEQ" || nm == "BNE")
                        && !no.first().map_or(false, |l| joins.contains(l.as_str()))
                }
            });
            if prev_ld && next_zbr {
                continue;
            }
        }
        match mn.as_str() {
            "LD" if ops.len() == 2 => {
                let (d, src) = (reg_index(&ops[0]), ops[1].as_str());
                match d {
                    Some(d) if cacheable(src) => {
                        if known[d].as_deref() == Some(src) {
                            continue; // already there
                        }
                        if let Some(s) = (0..4).find(|&i| known[i].as_deref() == Some(src)) {
                            out.push((LineKind::Code, format!("MOV     {},{}", REGS[d], REGS[s])));
                        } else {
                            out.push((kind.clone(), text.clone()));
                        }
                        known[d] = Some(src.to_string());
                        continue;
                    }
                    Some(d) => known[d] = None,
                    None => {}
                }
            }
            "ST" if ops.len() == 2 => {
                let (dst, s) = (ops[0].as_str(), reg_index(&ops[1]));
                if cacheable(dst) {
                    forget_mem(&mut known, dst, s);
                    if let Some(s) = s {
                        known[s] = Some(dst.to_string());
                    }
                } else if !dst.contains('$') {
                    forget_all(&mut known); // through a pointer: anywhere
                }
            }
            "STW" => forget_all(&mut known),
            "MOV" if ops.len() == 2 => {
                if let Some(d) = reg_index(&ops[0]) {
                    known[d] = reg_index(&ops[1]).and_then(|s| known[s].clone());
                }
            }
            "CALL" => forget_all(&mut known),
            "PUSH" | "PUSHW" | "POPW" => forget_sp(&mut known),
            "POP" => {
                forget_sp(&mut known);
                if let Some(d) = ops.first().and_then(|o| reg_index(o)) {
                    known[d] = None;
                }
            }
            "ADDW" | "SUBW" | "MOVW" | "LDW" | "LEA" | "INCW" | "DECW" => {
                if ops.first().map_or(false, |o| o == "SP") {
                    forget_sp(&mut known);
                }
            }
            "CMP" | "TST" | "BTST" | "MUL" | "NOP" | "RET" | "RETI" | "HALT" | "BRK" | "CLC" | "SEC"
            | "CLV" | "EI" | "DI" | "JMP" | "BRA" | "BEQ" | "BNE" | "BLO" | "BHS" | "BLS" | "BHI"
            | "BMI" | "BPL" | "BCS" | "BCC" | "BZ" | "BNZ" | "BN" | "BP" | "BLT" | "BGE" | "BGT"
            | "BLE" | "BVS" | "BVC" => {}
            _ => {
                // an ALU or unary instruction: its first operand, if a
                // register, is written; anything unrecognised forgets all
                match ops.first().and_then(|o| reg_index(o)) {
                    Some(d) => known[d] = None,
                    None => {
                        if !mn.starts_with('.') {
                            forget_all(&mut known);
                        }
                    }
                }
            }
        }
        out.push((kind.clone(), text.clone()));
    }
    out
}
