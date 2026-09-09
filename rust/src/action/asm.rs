// The COOL8 assembler, in Rust, for the CoolAction! compiler.
//
// It carries no mnemonic table. `optab::ENCODINGS` is tools/opcodes.py
// rendered through tools/cool8asm.py's own normalisation, so the
// signature a source line reduces to here is the one the Python
// assembler reduces it to, and the bytes are the table's. What this
// file re-implements is the logic of tools/cool8asm.py -- operand
// normalisation, the expression grammar, local labels, the directives
// and the branch-relaxation policy -- and sim/test_action.py holds the
// two assemblers to byte-identical output on the compiler's own code.
//
// Not carried over: `.include` and `.macro`. Generated code needs
// neither, and an ASM block in a CoolAction! program is a few lines.

use crate::optab;
use std::collections::HashMap;

const REGS8: [&str; 4] = ["R0", "R1", "R2", "R3"];
const REGS16: [&str; 3] = ["X", "Y", "SP"];
const HALVES: [&str; 4] = ["XL", "XH", "YL", "YH"];

#[derive(Debug, Clone, PartialEq)]
enum Kind {
    Insn,
    Data,
    Org,
}

#[derive(Debug, Clone)]
struct Item {
    addr: u16,
    kind: Kind,
    line: usize,
    size: usize,
    data: Vec<u8>,
    op: u8,
    op2: Option<u8>,
    operand: u8,
    exprs: Vec<String>,
    width: usize,       // data: 1 or 2
    relax: Option<Relax>,
    global: String,     // enclosing global label, for local references
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum Relax {
    Jmp,
    Br(u8, Option<u8>),
}

pub struct Assembler {
    syms: HashMap<String, i64>,
    symat: HashMap<String, usize>,
    items: Vec<Item>,
    pc: u16,
    cur_global: String,
    table: HashMap<&'static str, &'static optab::Enc>,
    errors: Vec<String>,
    pub relaxed: usize,
}

impl Default for Assembler {
    fn default() -> Self {
        Self::new()
    }
}

impl Assembler {
    pub fn new() -> Self {
        let mut table = HashMap::new();
        for e in optab::ENCODINGS {
            table.entry(e.sig).or_insert(e);
        }
        Self {
            syms: HashMap::new(),
            symat: HashMap::new(),
            items: Vec::new(),
            pc: 0,
            cur_global: String::new(),
            table,
            errors: Vec::new(),
            relaxed: 0,
        }
    }

    /// Assemble a whole text: `(origin, image, symbols)`.
    pub fn assemble(&mut self, source: &str) -> Result<(u16, Vec<u8>, HashMap<String, u16>), String> {
        for (i, raw) in source.lines().enumerate() {
            let line = i + 1;
            if let Err(e) = self.pass1_line(raw, line) {
                self.errors.push(format!("line {}: {}", line, e));
            }
        }
        if self.errors.is_empty() {
            self.relax();
            self.pass2();
        }
        if !self.errors.is_empty() {
            return Err(self.errors.join("\n"));
        }
        let (org, img) = self.image();
        let syms = self
            .syms
            .iter()
            .map(|(k, v)| (k.clone(), (*v & 0xFFFF) as u16))
            .collect();
        Ok((org, img, syms))
    }

    // ------------------------------------------------------------ pass 1

    /// Strip the comment, respecting quotes.
    fn split(raw: &str) -> String {
        let mut out = String::new();
        let mut q: Option<char> = None;
        let chars: Vec<char> = raw.chars().collect();
        let mut i = 0;
        while i < chars.len() {
            let ch = chars[i];
            if let Some(qq) = q {
                out.push(ch);
                if ch == '\\' && i + 1 < chars.len() {
                    out.push(chars[i + 1]);
                    i += 1;
                } else if ch == qq {
                    q = None;
                }
            } else if ch == '"' || ch == '\'' {
                q = Some(ch);
                out.push(ch);
            } else if ch == ';' {
                break;
            } else {
                out.push(ch);
            }
            i += 1;
        }
        out
    }

    fn pass1_line(&mut self, raw: &str, line: usize) -> Result<(), String> {
        let mut code = Self::split(raw).trim().to_string();
        if code.is_empty() {
            return Ok(());
        }

        // label:  (a leading dot is a local label; `.byte` has no colon)
        if let Some(pos) = code.find(':') {
            let head = code[..pos].trim();
            let is_label = !head.is_empty()
                && head
                    .chars()
                    .all(|c| c.is_alphanumeric() || c == '_' || c == '.' || c == '@')
                && !head.contains(' ');
            if is_label {
                let name = if let Some(local) = head.strip_prefix('.') {
                    if self.cur_global.is_empty() {
                        return Err("local label before any global label".into());
                    }
                    format!("{}.{}", self.cur_global, local)
                } else {
                    self.cur_global = head.to_string();
                    head.to_string()
                };
                if self.syms.contains_key(&name) {
                    return Err(format!("duplicate label '{}'", name));
                }
                self.syms.insert(name.clone(), self.pc as i64);
                self.symat.insert(name, self.items.len());
                code = code[pos + 1..].trim().to_string();
                if code.is_empty() {
                    return Ok(());
                }
            }
        }

        let (head, rest) = match code.find(char::is_whitespace) {
            Some(p) => (code[..p].to_string(), code[p..].trim().to_string()),
            None => (code.clone(), String::new()),
        };

        // NAME = expr
        if !head.starts_with('.') {
            if let Some(eq) = code.find('=') {
                let name = code[..eq].trim();
                let is_name = !name.is_empty()
                    && name.chars().all(|c| c.is_alphanumeric() || c == '_' || c == '.')
                    && !name.chars().next().unwrap().is_ascii_digit();
                if is_name {
                    let v = self.eval(&code[eq + 1..], self.pc, &self.cur_global.clone())?;
                    self.syms.insert(name.to_string(), v);
                    return Ok(());
                }
            }
        }

        if head.starts_with('.') {
            return self.directive(&head.to_lowercase(), &rest, line);
        }
        self.instruction(&head, &rest, line)
    }

    fn directive(&mut self, name: &str, rest: &str, line: usize) -> Result<(), String> {
        let global = self.cur_global.clone();
        match name {
            ".org" => {
                let v = self.eval(rest, self.pc, &global)? as u16;
                if !self.items.is_empty() {
                    let it = Item {
                        addr: v,
                        kind: Kind::Org,
                        line,
                        size: 0,
                        data: vec![],
                        op: 0,
                        op2: None,
                        operand: 0,
                        exprs: vec![],
                        width: 0,
                        relax: None,
                        global,
                    };
                    self.items.push(it);
                }
                self.pc = v;
                Ok(())
            }
            ".equ" | ".set" => {
                let (n, e) = rest.split_once(',').ok_or("`.equ NAME, expr`")?;
                let v = self.eval(e, self.pc, &global)?;
                self.syms.insert(n.trim().to_string(), v);
                Ok(())
            }
            ".align" => {
                let n = self.eval(rest, self.pc, &global)?;
                if n <= 0 {
                    return Err("bad alignment".into());
                }
                let pad = ((-(self.pc as i64)).rem_euclid(n)) as usize;
                if pad > 0 {
                    self.push_data(vec![0u8; pad], line);
                }
                Ok(())
            }
            ".byte" | ".db" | ".word" | ".dw" => {
                let width = if name == ".byte" || name == ".db" { 1 } else { 2 };
                let args = split_args(rest);
                let mut size = 0;
                for a in &args {
                    size += if width == 1 && is_str(a) {
                        strbytes(a)?.len()
                    } else {
                        width
                    };
                }
                let it = Item {
                    addr: self.pc,
                    kind: Kind::Data,
                    line,
                    size,
                    data: vec![],
                    op: 0,
                    op2: None,
                    operand: 0,
                    exprs: args,
                    width,
                    relax: None,
                    global,
                };
                self.items.push(it);
                self.pc = self.pc.wrapping_add(size as u16);
                Ok(())
            }
            ".ascii" | ".asciz" => {
                let mut body = strbytes(rest.trim())?;
                if name == ".asciz" {
                    body.push(0);
                }
                self.push_data(body, line);
                Ok(())
            }
            ".space" | ".res" | ".fill" => {
                let args = split_args(rest);
                if args.is_empty() {
                    return Err("`.space n [, fill]`".into());
                }
                let n = self.eval(&args[0], self.pc, &global)?;
                if n < 0 {
                    return Err("negative .space".into());
                }
                let fill = if args.len() > 1 {
                    self.eval(&args[1], self.pc, &global)? as u8
                } else {
                    0
                };
                self.push_data(vec![fill; n as usize], line);
                Ok(())
            }
            _ => Err(format!("unknown directive '{}'", name)),
        }
    }

    fn push_data(&mut self, data: Vec<u8>, line: usize) {
        if data.is_empty() {
            return;
        }
        let size = data.len();
        let it = Item {
            addr: self.pc,
            kind: Kind::Data,
            line,
            size,
            data,
            op: 0,
            op2: None,
            operand: 0,
            exprs: vec![],
            width: 0,
            relax: None,
            global: self.cur_global.clone(),
        };
        self.items.push(it);
        self.pc = self.pc.wrapping_add(size as u16);
    }

    fn instruction(&mut self, mnem: &str, rest: &str, line: usize) -> Result<(), String> {
        let mut mnem = mnem.to_uppercase();
        let mut rest = rest.to_string();
        let args = split_args(&rest);
        if args.len() == 1 {
            for (alias, m, ops) in optab::ALIASES {
                if *alias == mnem {
                    mnem = m.to_string();
                    rest = ops.replace("{0}", args[0].trim());
                    break;
                }
            }
        }
        let (sig, exprs) = norm_line(&mnem, &rest)?;
        let enc = match self.table.get(sig.as_str()) {
            Some(e) => *e,
            None => return Err(format!("no encoding for {}", sig)),
        };
        let global = self.cur_global.clone();
        let exprs: Vec<String> = exprs.iter().map(|e| qualify(e, &global)).collect();
        let size = 1 + usize::from(enc.op2.is_some()) + optab::EXTRA[enc.kind as usize] as usize;
        let it = Item {
            addr: self.pc,
            kind: Kind::Insn,
            line,
            size,
            data: vec![],
            op: enc.op,
            op2: enc.op2,
            operand: enc.kind,
            exprs,
            width: 0,
            relax: None,
            global,
        };
        self.items.push(it);
        self.pc = self.pc.wrapping_add(size as u16);
        Ok(())
    }

    // -------------------------------------------------------- relaxation

    fn cond_index(op: u8, op2: Option<u8>) -> Option<usize> {
        if op2.is_none() && (0x70..0x80).contains(&op) {
            Some((op - 0x70) as usize)
        } else {
            None
        }
    }

    /// Grow every branch that cannot reach, until none is left -- the
    /// policy of tools/cool8asm.py: `BRA far` becomes `JMP far`, and an
    /// out-of-range `BEQ far` becomes `BNE` over a `JMP far`.
    fn relax(&mut self) {
        loop {
            let mut grew = 0;
            for i in 0..self.items.len() {
                let it = &self.items[i];
                if it.kind != Kind::Insn || it.relax.is_some() || it.operand != optab::K_REL8 {
                    continue;
                }
                let v = match self.eval(&it.exprs[0], it.addr, &it.global) {
                    Ok(v) => v,
                    Err(_) => continue,
                };
                let d = v - (it.addr as i64 + it.size as i64);
                if (-128..=127).contains(&d) {
                    continue;
                }
                let ci = match Self::cond_index(it.op, it.op2) {
                    Some(c) => c,
                    None => continue,
                };
                let it = &mut self.items[i];
                if ci == 0 {
                    it.relax = Some(Relax::Jmp);
                    it.size = 3;
                } else {
                    let inv = 0x70 | ((ci ^ 1) as u8);
                    it.relax = Some(Relax::Br(inv, None));
                    it.size = 5;
                }
                grew += 1;
            }
            if grew == 0 {
                return;
            }
            self.relaxed += grew;
            self.replace();
        }
    }

    /// Re-lay the image after a branch grew, symbols with it.
    fn replace(&mut self) {
        let mut at: HashMap<usize, Vec<String>> = HashMap::new();
        for (name, idx) in &self.symat {
            at.entry(*idx).or_default().push(name.clone());
        }
        let mut pc: u16 = self.items.first().map(|i| i.addr).unwrap_or(0);
        for i in 0..self.items.len() {
            if let Some(names) = at.get(&i) {
                for n in names {
                    self.syms.insert(n.clone(), pc as i64);
                }
            }
            if self.items[i].kind == Kind::Org {
                pc = self.items[i].addr;
                continue;
            }
            self.items[i].addr = pc;
            pc = pc.wrapping_add(self.items[i].size as u16);
        }
        if let Some(names) = at.get(&self.items.len()) {
            for n in names {
                self.syms.insert(n.clone(), pc as i64);
            }
        }
    }

    // ------------------------------------------------------------ pass 2

    fn pass2(&mut self) {
        for i in 0..self.items.len() {
            let it = self.items[i].clone();
            let r = match it.kind {
                Kind::Insn => self.encode(&it).map(Some),
                Kind::Data if !it.exprs.is_empty() => {
                    let mut out = Vec::new();
                    let mut err = None;
                    for a in &it.exprs {
                        if it.width == 1 && is_str(a) {
                            match strbytes(a) {
                                Ok(b) => out.extend(b),
                                Err(e) => err = Some(e),
                            }
                            continue;
                        }
                        match self.eval(a, it.addr, &it.global) {
                            Ok(v) => {
                                out.push((v & 0xFF) as u8);
                                if it.width == 2 {
                                    out.push(((v >> 8) & 0xFF) as u8);
                                }
                            }
                            Err(e) => err = Some(e),
                        }
                    }
                    match err {
                        Some(e) => Err(e),
                        None if out.len() != it.size => Err("data size changed between passes".into()),
                        None => Ok(Some(out)),
                    }
                }
                _ => Ok(None),
            };
            match r {
                Ok(Some(d)) => self.items[i].data = d,
                Ok(None) => {}
                Err(e) => self.errors.push(format!("line {}: {}", it.line, e)),
            }
        }
    }

    fn encode(&self, it: &Item) -> Result<Vec<u8>, String> {
        let mut out = vec![it.op];
        if let Some(o2) = it.op2 {
            out.push(o2);
        }
        let n = optab::EXTRA[it.operand as usize];
        if n == 0 {
            return Ok(out);
        }
        let v = self.eval(&it.exprs[0], it.addr, &it.global)?;
        match it.operand {
            optab::K_REL8 => match it.relax {
                Some(Relax::Jmp) => Ok(vec![0x28, (v & 0xFF) as u8, ((v >> 8) & 0xFF) as u8]),
                Some(Relax::Br(inv, _)) => Ok(vec![inv, 3, 0x28, (v & 0xFF) as u8, ((v >> 8) & 0xFF) as u8]),
                None => {
                    let d = v - (it.addr as i64 + it.size as i64);
                    if !(-128..=127).contains(&d) {
                        return Err(format!(
                            "branch out of range: {:+} bytes (target ${:04X} from ${:04X})",
                            d, v & 0xFFFF, it.addr
                        ));
                    }
                    out.push((d & 0xFF) as u8);
                    Ok(out)
                }
            },
            optab::K_ABS16 | optab::K_IMM16 => {
                out.push((v & 0xFF) as u8);
                out.push(((v >> 8) & 0xFF) as u8);
                Ok(out)
            }
            optab::K_DISP8 => {
                if !(-128..=127).contains(&v) {
                    return Err(format!("signed displacement {} out of range (-128..127)", v));
                }
                out.push((v & 0xFF) as u8);
                Ok(out)
            }
            optab::K_U8 => {
                if !(0..=255).contains(&v) {
                    return Err(format!("unsigned displacement {} out of range (0..255)", v));
                }
                out.push(v as u8);
                Ok(out)
            }
            _ => {
                if !(-128..=255).contains(&v) {
                    return Err(format!("immediate {} does not fit in a byte", v));
                }
                out.push((v & 0xFF) as u8);
                Ok(out)
            }
        }
    }

    fn image(&self) -> (u16, Vec<u8>) {
        let placed: Vec<&Item> = self.items.iter().filter(|i| !i.data.is_empty()).collect();
        if placed.is_empty() {
            return (0, vec![]);
        }
        let lo = placed.iter().map(|i| i.addr as usize).min().unwrap();
        let hi = placed.iter().map(|i| i.addr as usize + i.data.len()).max().unwrap();
        let mut img = vec![0u8; hi - lo];
        for it in placed {
            let a = it.addr as usize - lo;
            img[a..a + it.data.len()].copy_from_slice(&it.data);
        }
        (lo as u16, img)
    }

    // ------------------------------------------------------- expressions

    fn eval(&self, text: &str, pc: u16, global: &str) -> Result<i64, String> {
        let toks = tokenize(&qualify(text, global))?;
        let mut p = 0;
        let v = self.parse(&toks, &mut p, pc, 0)?;
        if p != toks.len() {
            return Err(format!("trailing junk in expression '{}'", text.trim()));
        }
        Ok(v)
    }

    fn parse(&self, toks: &[String], p: &mut usize, pc: u16, level: usize) -> Result<i64, String> {
        const PREC: [&[&str]; 6] = [&["|"], &["^"], &["&"], &["<<", ">>"], &["+", "-"], &["*", "/", "%"]];
        if level == PREC.len() {
            return self.parse_unary(toks, p, pc);
        }
        let mut val = self.parse(toks, p, pc, level + 1)?;
        while *p < toks.len() && PREC[level].contains(&toks[*p].as_str()) {
            let opr = toks[*p].clone();
            *p += 1;
            let rhs = self.parse(toks, p, pc, level + 1)?;
            val = match opr.as_str() {
                "+" => val.wrapping_add(rhs),
                "-" => val.wrapping_sub(rhs),
                "*" => val.wrapping_mul(rhs),
                "/" => {
                    if rhs == 0 {
                        return Err("division by zero in expression".into());
                    }
                    val.div_euclid(rhs)
                }
                "%" => {
                    if rhs == 0 {
                        return Err("division by zero in expression".into());
                    }
                    val.rem_euclid(rhs)
                }
                "&" => val & rhs,
                "|" => val | rhs,
                "^" => val ^ rhs,
                "<<" => val << (rhs & 63),
                _ => val >> (rhs & 63),
            };
        }
        Ok(val)
    }

    fn parse_unary(&self, toks: &[String], p: &mut usize, pc: u16) -> Result<i64, String> {
        if *p >= toks.len() {
            return Err("expression ended early".into());
        }
        let t = toks[*p].clone();
        *p += 1;
        match t.as_str() {
            "-" => Ok(-self.parse_unary(toks, p, pc)?),
            "+" => self.parse_unary(toks, p, pc),
            "~" => Ok(!self.parse_unary(toks, p, pc)?),
            "<" => Ok(self.parse_unary(toks, p, pc)? & 0xFF),
            ">" => Ok((self.parse_unary(toks, p, pc)? >> 8) & 0xFF),
            "(" => {
                let v = self.parse(toks, p, pc, 0)?;
                if *p >= toks.len() || toks[*p] != ")" {
                    return Err("unbalanced parenthesis".into());
                }
                *p += 1;
                Ok(v)
            }
            "*" => Ok(pc as i64),
            _ => {
                if let Some(h) = t.strip_prefix('$') {
                    return i64::from_str_radix(h, 16).map_err(|_| format!("bad hex '{}'", t));
                }
                if let Some(b) = t.strip_prefix('%') {
                    return i64::from_str_radix(b, 2).map_err(|_| format!("bad binary '{}'", t));
                }
                if t.starts_with('\'') {
                    let body = &t[1..t.len() - 1];
                    let c = if let Some(e) = body.strip_prefix('\\') {
                        match e.chars().next() {
                            Some('n') => '\n',
                            Some('r') => '\r',
                            Some('t') => '\t',
                            Some('0') => '\0',
                            Some(c) => c,
                            None => return Err("bad character literal".into()),
                        }
                    } else {
                        body.chars().next().ok_or("empty character literal")?
                    };
                    return Ok(c as i64);
                }
                if t.chars().next().unwrap().is_ascii_digit() {
                    return t.parse::<i64>().map_err(|_| format!("bad number '{}'", t));
                }
                match self.syms.get(&t) {
                    Some(v) => Ok(*v),
                    None => Err(format!("undefined symbol '{}'", t)),
                }
            }
        }
    }
}

// ---------------------------------------------------------------- helpers

/// Rewrite bare local labels (.foo) to Global.foo.
fn qualify(expr: &str, global: &str) -> String {
    if global.is_empty() {
        return expr.to_string();
    }
    let chars: Vec<char> = expr.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        let prev_ok = i == 0 || !(chars[i - 1].is_alphanumeric() || chars[i - 1] == '_' || chars[i - 1] == '.');
        if c == '.' && prev_ok && i + 1 < chars.len() && (chars[i + 1].is_alphanumeric() || chars[i + 1] == '_') {
            out.push_str(global);
            out.push('.');
            i += 1;
            continue;
        }
        out.push(c);
        i += 1;
    }
    out
}

fn tokenize(text: &str) -> Result<Vec<String>, String> {
    let chars: Vec<char> = text.chars().collect();
    let mut toks = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c.is_whitespace() {
            i += 1;
            continue;
        }
        if c == '$' {
            let s = i;
            i += 1;
            while i < chars.len() && chars[i].is_ascii_hexdigit() {
                i += 1;
            }
            toks.push(chars[s..i].iter().collect());
        } else if c == '%' && i + 1 < chars.len() && (chars[i + 1] == '0' || chars[i + 1] == '1') {
            let s = i;
            i += 1;
            while i < chars.len() && (chars[i] == '0' || chars[i] == '1') {
                i += 1;
            }
            toks.push(chars[s..i].iter().collect());
        } else if c == '\'' {
            let s = i;
            i += 1;
            if i < chars.len() && chars[i] == '\\' {
                i += 1;
            }
            i += 1;
            if i >= chars.len() || chars[i] != '\'' {
                return Err("bad character literal".into());
            }
            i += 1;
            toks.push(chars[s..i].iter().collect());
        } else if c.is_ascii_digit() {
            let s = i;
            while i < chars.len() && chars[i].is_ascii_digit() {
                i += 1;
            }
            toks.push(chars[s..i].iter().collect());
        } else if c.is_alphabetic() || c == '_' || c == '.' || c == '@' {
            let s = i;
            while i < chars.len() && (chars[i].is_alphanumeric() || chars[i] == '_' || chars[i] == '.' || chars[i] == '@') {
                i += 1;
            }
            toks.push(chars[s..i].iter().collect());
        } else if (c == '<' || c == '>') && i + 1 < chars.len() && chars[i + 1] == c {
            toks.push(format!("{}{}", c, c));
            i += 2;
        } else if "-+*/%&|^~()<>".contains(c) {
            toks.push(c.to_string());
            i += 1;
        } else {
            return Err(format!("bad character '{}' in expression", c));
        }
    }
    Ok(toks)
}

/// Split operands on top-level commas, respecting brackets and quotes.
pub fn split_args(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut depth = 0i32;
    let mut cur = String::new();
    let mut q: Option<char> = None;
    for ch in text.chars() {
        if let Some(qq) = q {
            cur.push(ch);
            if ch == qq {
                q = None;
            }
            continue;
        }
        if ch == '"' || ch == '\'' {
            q = Some(ch);
            cur.push(ch);
            continue;
        }
        if ch == '[' || ch == '(' {
            depth += 1;
        } else if ch == ']' || ch == ')' {
            depth -= 1;
        }
        if ch == ',' && depth == 0 {
            out.push(cur.trim().to_string());
            cur.clear();
        } else {
            cur.push(ch);
        }
    }
    if !cur.trim().is_empty() {
        out.push(cur.trim().to_string());
    }
    out
}

fn is_str(a: &str) -> bool {
    a.trim().starts_with('"')
}

fn strbytes(a: &str) -> Result<Vec<u8>, String> {
    let a = a.trim();
    if !a.starts_with('"') || !a.ends_with('"') || a.len() < 2 {
        return Err(format!("expected a string, got {}", a));
    }
    let body = &a[1..a.len() - 1];
    let mut out = Vec::new();
    let mut it = body.chars();
    while let Some(c) = it.next() {
        if c == '\\' {
            match it.next() {
                Some('n') => out.push(b'\n'),
                Some('r') => out.push(b'\r'),
                Some('t') => out.push(b'\t'),
                Some('0') => out.push(0),
                Some('"') => out.push(b'"'),
                Some('\\') => out.push(b'\\'),
                Some(c) => {
                    out.push(b'\\');
                    out.push(c as u32 as u8);
                }
                None => out.push(b'\\'),
            }
        } else {
            out.push(c as u32 as u8);
        }
    }
    Ok(out)
}

/// `(canonical_form, expression_or_None)` -- tools/cool8asm.py's
/// norm_operand, line for line.
fn norm_operand(text: &str) -> Result<(String, Option<String>), String> {
    let t = text.trim();
    let u = t.to_uppercase();
    if REGS8.contains(&u.as_str()) || REGS16.contains(&u.as_str()) || HALVES.contains(&u.as_str()) {
        return Ok((u, None));
    }
    if let Some(imm) = t.strip_prefix('#') {
        return Ok(("#N".into(), Some(imm.to_string())));
    }
    if t.starts_with('[') && t.ends_with(']') {
        let inner = t[1..t.len() - 1].trim();
        let iu = inner.to_uppercase();
        if ["X", "Y", "X+", "Y+", "-X", "-Y"].contains(&iu.as_str()) {
            return Ok((format!("[{}]", iu), None));
        }
        // base +/- rest
        let bases = ["SP", "X", "Y"];
        for b in bases {
            if iu.starts_with(b) {
                let after = inner[b.len()..].trim_start();
                if let Some(sign) = after.chars().next() {
                    if sign == '+' || sign == '-' {
                        let rest = after[1..].trim();
                        let ru = rest.to_uppercase();
                        if REGS8.contains(&ru.as_str()) {
                            if b == "SP" {
                                return Err("SP cannot be indexed by a register".into());
                            }
                            return Ok((format!("[{}+{}]", b, ru), None));
                        }
                        let expr = if sign == '+' { rest.to_string() } else { format!("-({})", rest) };
                        return Ok((format!("[{}+N]", b), Some(expr)));
                    }
                }
                if after.is_empty() {
                    return Ok((format!("[{}]", b), None));
                }
            }
        }
        return Ok(("[N]".into(), Some(inner.to_string())));
    }
    Ok(("N".into(), Some(t.to_string())))
}

fn norm_line(mnemonic: &str, operand_text: &str) -> Result<(String, Vec<String>), String> {
    let mut canon = Vec::new();
    let mut exprs = Vec::new();
    if !operand_text.trim().is_empty() {
        for o in split_args(operand_text) {
            let (c, e) = norm_operand(&o)?;
            canon.push(c);
            if let Some(e) = e {
                exprs.push(e);
            }
        }
    }
    let sig = if canon.is_empty() {
        mnemonic.to_uppercase()
    } else {
        format!("{} {}", mnemonic.to_uppercase(), canon.join(","))
    };
    Ok((sig, exprs))
}
