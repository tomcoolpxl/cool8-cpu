// CoolAction! code generator: AST to COOL8 assembly text.
//
// The model, in one paragraph. An expression leaves its value in R0
// (one byte) or R1:R0 (two, low byte in R0). A binary operator wants
// its right operand in R2/R3, which a constant or a plain variable can
// be loaded into directly; anything else is evaluated first and the
// left side pushed around it, and `depth` tracks those pushes so a
// local's `[SP+u8]` slot is still found. X and Y are never live across
// a sub-expression: Y is the address a load or store is about to use,
// X is MUL's product and the pointer `LEA` hands back. Locals sit in a
// frame `ADDW SP` opens, parameters above the return address, and a
// FUNC answers in R0 or R1:R0. docs/15-action.md says the rest.

use super::ast::*;
use super::token::Span;
use std::collections::{BTreeSet, HashMap};

#[derive(Debug, Clone)]
enum Loc {
    /// A global: its label in the data section.
    Label(String),
    /// A hardware register, or anything bound with `= address`.
    Abs(u16),
    /// Offset into the current frame, before `depth` is added.
    Stack(usize),
}

#[derive(Debug, Clone)]
struct Sym {
    ty: TypeKind,
    loc: Loc,
}

/// Where a load or store goes, once the address side is computed.
#[derive(Debug, Clone)]
enum LVal {
    At(Loc, usize),
    /// `[Y]`, `[Y+1]`
    Y,
    /// `[Y+d]`, `[Y+d+1]`
    YD(usize),
    /// `[Y+Rn]`, one byte
    YR(u8),
}

/// An operand that can be loaded into any register pair without
/// disturbing the others.
#[derive(Debug, Clone)]
enum Simple {
    Const(i64),
    Var(Sym),
    Addr(Loc),
}

/// One line of output, by what it is: an instruction the generator
/// emitted and the peephole pass may rewrite, a label, or text passed
/// through untouched -- an ASM block, a runtime routine, data.
#[derive(Debug, Clone, PartialEq)]
pub enum LineKind {
    Code,
    Label,
    /// A label every path into which carries the same register facts:
    /// the `.cm` of a word compare, reached by the fall-through and by
    /// the `BNE` over one `CMP`. The peephole pass keeps its facts
    /// across one where a `Label` makes it forget them.
    Join,
    Raw,
}

pub struct Codegen {
    lines: Vec<(LineKind, String)>,
    org: u16,
    globals: HashMap<String, Sym>,
    records: HashMap<String, RecordDecl>,
    routines: HashMap<String, RoutineDecl>,
    locals: HashMap<String, Sym>,
    frame: usize,
    depth: usize,
    labels: usize,
    strings: Vec<(String, Vec<u8>)>,
    loops: Vec<String>,
    runtime: BTreeSet<&'static str>,
    cur_routine: Option<RoutineDecl>,
}

fn err(span: &Span, msg: &str) -> String {
    format!("line {}: {}", span.line, msg)
}

const R: [&str; 4] = ["R0", "R1", "R2", "R3"];

impl Codegen {
    pub fn new(org: u16) -> Self {
        Self {
            lines: Vec::new(),
            org,
            globals: HashMap::new(),
            records: HashMap::new(),
            routines: HashMap::new(),
            locals: HashMap::new(),
            frame: 0,
            depth: 0,
            labels: 0,
            strings: Vec::new(),
            loops: Vec::new(),
            runtime: BTreeSet::new(),
            cur_routine: None,
        }
    }

    // ---------------------------------------------------------- output

    fn emit(&mut self, s: &str) {
        self.lines.push((LineKind::Code, s.to_string()));
    }

    fn label(&mut self, l: &str) {
        self.lines.push((LineKind::Label, l.to_string()));
    }

    /// A label whose every predecessor holds the same registers -- see
    /// LineKind::Join. Only for a label the generator can vouch for.
    fn join(&mut self, l: &str) {
        self.lines.push((LineKind::Join, l.to_string()));
    }

    fn raw(&mut self, s: &str) {
        self.lines.push((LineKind::Raw, s.to_string()));
    }

    /// The text, after the peephole pass (peep.rs) over the emitted code.
    fn text(&self) -> String {
        let mut out = String::new();
        for (kind, s) in super::peep::optimise(&self.lines) {
            match kind {
                LineKind::Code => {
                    out.push_str("    ");
                    out.push_str(&s);
                }
                LineKind::Label | LineKind::Join => {
                    out.push_str(&s);
                    out.push(':');
                }
                LineKind::Raw => out.push_str(&s),
            }
            out.push('\n');
        }
        out
    }

    /// A fresh local label. Local, so dbg.Profile rolls its cost up
    /// into the routine that owns it.
    fn lbl(&mut self, tag: &str) -> String {
        self.labels += 1;
        format!(".{}{}", tag, self.labels)
    }

    fn push(&mut self, r: &str) {
        self.emit(&format!("PUSH    {}", r));
        self.depth += 1;
    }

    fn pop(&mut self, r: &str) {
        self.emit(&format!("POP     {}", r));
        self.depth -= 1;
    }

    fn push_pair(&mut self, w: usize) {
        if w == 2 {
            self.push("R1");
        }
        self.push("R0");
    }

    fn pop_pair(&mut self, w: usize) {
        self.pop("R0");
        if w == 2 {
            self.pop("R1");
        }
    }

    fn operand(&self, loc: &Loc, add: usize) -> Result<String, String> {
        Ok(match loc {
            Loc::Label(l) if add == 0 => format!("[{}]", l),
            Loc::Label(l) => format!("[{}+{}]", l, add),
            Loc::Abs(a) => format!("[${:04X}]", *a as usize + add),
            Loc::Stack(o) => {
                let off = o + add + self.depth;
                if off > 255 {
                    return Err("frame too deep: a local is more than 255 bytes below the top".into());
                }
                format!("[SP+{}]", off)
            }
        })
    }

    fn load_loc(&mut self, loc: &Loc, add: usize, reg: &str) -> Result<(), String> {
        let o = self.operand(loc, add)?;
        self.emit(&format!("LD      {},{}", reg, o));
        Ok(())
    }

    fn store_loc(&mut self, loc: &Loc, add: usize, reg: &str) -> Result<(), String> {
        let o = self.operand(loc, add)?;
        self.emit(&format!("ST      {},{}", o, reg));
        Ok(())
    }

    fn load_lval(&mut self, lv: &LVal, w: usize) -> Result<(), String> {
        match lv {
            LVal::At(loc, off) => {
                self.load_loc(loc, *off, "R0")?;
                if w == 2 {
                    self.load_loc(loc, off + 1, "R1")?;
                }
            }
            LVal::Y => {
                self.emit("LD      R0,[Y]");
                if w == 2 {
                    self.emit("LD      R1,[Y+1]");
                }
            }
            LVal::YD(d) => {
                self.emit(&format!("LD      R0,[Y+{}]", d));
                if w == 2 {
                    self.emit(&format!("LD      R1,[Y+{}]", d + 1));
                }
            }
            LVal::YR(r) => {
                self.emit(&format!("LD      R0,[Y+{}]", R[*r as usize]));
                if w == 2 {
                    return Err("internal: indexed load of a word".into());
                }
            }
        }
        Ok(())
    }

    fn store_lval(&mut self, lv: &LVal, w: usize) -> Result<(), String> {
        match lv {
            LVal::At(loc, off) => {
                self.store_loc(loc, *off, "R0")?;
                if w == 2 {
                    self.store_loc(loc, off + 1, "R1")?;
                }
            }
            LVal::Y => {
                self.emit("ST      [Y],R0");
                if w == 2 {
                    self.emit("ST      [Y+1],R1");
                }
            }
            LVal::YD(d) => {
                self.emit(&format!("ST      [Y+{}],R0", d));
                if w == 2 {
                    self.emit(&format!("ST      [Y+{}],R1", d + 1));
                }
            }
            LVal::YR(r) => {
                self.emit(&format!("ST      [Y+{}],R0", R[*r as usize]));
                if w == 2 {
                    return Err("internal: indexed store of a word".into());
                }
            }
        }
        Ok(())
    }

    // --------------------------------------------------------- symbols

    fn lookup(&self, name: &str, span: &Span) -> Result<Sym, String> {
        if let Some(s) = self.locals.get(name) {
            return Ok(s.clone());
        }
        if let Some(s) = self.globals.get(name) {
            return Ok(s.clone());
        }
        Err(err(span, &format!("undefined variable '{}'", name)))
    }

    fn size_of(&self, t: &TypeKind, span: &Span) -> Result<usize, String> {
        match t {
            TypeKind::UserDefined(r) => self
                .records
                .get(r)
                .map(|d| d.size_bytes)
                .ok_or_else(|| err(span, &format!("unknown type '{}'", r))),
            TypeKind::Array(elem, n) => Ok(self.size_of(elem, span)? * n),
            _ => Ok(t.size_bytes()),
        }
    }

    fn field(&self, rec: &str, field: &str, span: &Span) -> Result<FieldDecl, String> {
        let d = self
            .records
            .get(rec)
            .ok_or_else(|| err(span, &format!("unknown type '{}'", rec)))?;
        d.fields
            .iter()
            .find(|f| f.name == field)
            .cloned()
            .ok_or_else(|| err(span, &format!("'{}' has no field '{}'", rec, field)))
    }

    // ------------------------------------------------------------ types

    /// The static type of an expression, with no code emitted.
    fn type_of(&self, e: &Expr) -> Result<TypeKind, String> {
        Ok(match &e.kind {
            ExprKind::Number(v) => {
                if (0..=255).contains(v) {
                    TypeKind::Byte
                } else if *v < 0 {
                    TypeKind::Int
                } else {
                    TypeKind::Card
                }
            }
            ExprKind::CharLit(_) => TypeKind::Byte,
            ExprKind::Str(_) => TypeKind::Pointer(Box::new(TypeKind::Byte)),
            ExprKind::Variable(name) => match self.lookup(name, &e.span)?.ty {
                TypeKind::Array(elem, _) => TypeKind::Pointer(elem),
                t @ TypeKind::UserDefined(_) => TypeKind::Pointer(Box::new(t)),
                t => t,
            },
            ExprKind::AddrOf(name) => match self.lookup(name, &e.span)?.ty {
                TypeKind::Array(elem, _) => TypeKind::Pointer(elem),
                t => TypeKind::Pointer(Box::new(t)),
            },
            ExprKind::Deref(inner) => match self.type_of(inner)? {
                TypeKind::Pointer(t) => *t,
                _ => TypeKind::Byte,
            },
            ExprKind::FieldAccess { base, field } => {
                let rec = match self.type_of(base)? {
                    TypeKind::Pointer(t) => *t,
                    t => t,
                };
                match rec {
                    TypeKind::UserDefined(r) => self.field(&r, field, &e.span)?.type_kind,
                    _ => return Err(err(&e.span, "field access on something that is not a record")),
                }
            }
            ExprKind::Call { name, .. } => {
                if let Ok(sym) = self.lookup(name, &e.span) {
                    if let TypeKind::Array(elem, _) = sym.ty {
                        return Ok(*elem);
                    }
                }
                match self.routines.get(name) {
                    Some(r) => match &r.return_type {
                        Some(t) => t.clone(),
                        None => return Err(err(&e.span, &format!("PROC '{}' has no value", name))),
                    },
                    None => return Err(err(&e.span, &format!("undefined routine '{}'", name))),
                }
            }
            ExprKind::Unary { op, expr } => match op {
                UnaryOp::Neg => TypeKind::Int,
                UnaryOp::BitNot => self.type_of(expr)?,
                UnaryOp::LogicalNot => TypeKind::Byte,
            },
            ExprKind::Binary { op, left, right } => {
                let lt = self.type_of(left)?;
                let rt = self.type_of(right)?;
                match op {
                    BinaryOp::Eq
                    | BinaryOp::Ne
                    | BinaryOp::Lt
                    | BinaryOp::Le
                    | BinaryOp::Gt
                    | BinaryOp::Ge
                    | BinaryOp::LogicalAnd
                    | BinaryOp::LogicalOr => TypeKind::Byte,
                    BinaryOp::Shl | BinaryOp::Shr => lt,
                    BinaryOp::Mul if lt.width() == 1 && rt.width() == 1 => TypeKind::Card,
                    _ => {
                        if matches!(lt, TypeKind::Pointer(_)) {
                            lt
                        } else if matches!(rt, TypeKind::Pointer(_)) {
                            rt
                        } else if lt.is_signed() || rt.is_signed() {
                            TypeKind::Int
                        } else if lt.width() == 2 || rt.width() == 2 {
                            TypeKind::Card
                        } else {
                            TypeKind::Byte
                        }
                    }
                }
            }
        })
    }

    fn const_of(&self, e: &Expr) -> Option<i64> {
        Some(match &e.kind {
            ExprKind::Number(v) => *v,
            ExprKind::CharLit(c) => *c as i64,
            ExprKind::Unary { op: UnaryOp::Neg, expr } => -self.const_of(expr)?,
            ExprKind::Unary { op: UnaryOp::BitNot, expr } => !self.const_of(expr)?,
            ExprKind::Binary { op, left, right } => {
                let a = self.const_of(left)?;
                let b = self.const_of(right)?;
                match op {
                    BinaryOp::Add => a + b,
                    BinaryOp::Sub => a - b,
                    BinaryOp::Mul => a * b,
                    BinaryOp::Div if b != 0 => a / b,
                    BinaryOp::Mod if b != 0 => a % b,
                    BinaryOp::BitAnd => a & b,
                    BinaryOp::BitOr => a | b,
                    BinaryOp::BitXor => a ^ b,
                    BinaryOp::Shl => a << (b & 31),
                    BinaryOp::Shr => a >> (b & 31),
                    _ => return None,
                }
            }
            _ => return None,
        })
    }

    fn simple(&self, e: &Expr) -> Option<Simple> {
        if let Some(v) = self.const_of(e) {
            return Some(Simple::Const(v));
        }
        match &e.kind {
            ExprKind::Variable(name) => {
                let sym = self.lookup(name, &e.span).ok()?;
                match sym.ty {
                    TypeKind::Array(..) | TypeKind::UserDefined(_) => Some(Simple::Addr(sym.loc)),
                    _ => Some(Simple::Var(sym)),
                }
            }
            ExprKind::AddrOf(name) => {
                let sym = self.lookup(name, &e.span).ok()?;
                Some(Simple::Addr(sym.loc))
            }
            _ => None,
        }
    }

    /// Load a simple operand into `lo` (and `hi` when `w` is 2).
    fn load_simple(&mut self, s: &Simple, lo: &str, hi: &str, w: usize) -> Result<(), String> {
        match s {
            Simple::Const(v) => {
                self.emit(&format!("MOV     {},#{}", lo, v & 0xFF));
                if w == 2 {
                    self.emit(&format!("MOV     {},#{}", hi, (v >> 8) & 0xFF));
                }
            }
            Simple::Var(sym) => {
                self.load_loc(&sym.loc, 0, lo)?;
                if w == 2 {
                    if sym.ty.width() == 2 {
                        self.load_loc(&sym.loc, 1, hi)?;
                    } else {
                        self.emit(&format!("CLR     {}", hi));
                    }
                }
            }
            Simple::Addr(loc) => match loc {
                Loc::Label(l) => {
                    self.emit(&format!("MOV     {},#<{}", lo, l));
                    if w == 2 {
                        self.emit(&format!("MOV     {},#>{}", hi, l));
                    }
                }
                Loc::Abs(a) => {
                    self.emit(&format!("MOV     {},#{}", lo, a & 0xFF));
                    if w == 2 {
                        self.emit(&format!("MOV     {},#{}", hi, a >> 8));
                    }
                }
                Loc::Stack(o) => {
                    let off = o + self.depth;
                    if off > 255 {
                        return Err("frame too deep".into());
                    }
                    self.emit(&format!("LEA     X,[SP+{}]", off));
                    self.emit(&format!("MOV     {},XL", lo));
                    if w == 2 {
                        self.emit(&format!("MOV     {},XH", hi));
                    }
                }
            },
        }
        Ok(())
    }

    // ----------------------------------------------------------- driver

    pub fn generate(&mut self, program: &Program) -> Result<String, String> {
        let mut consts = Vec::new();
        for item in &program.items {
            match item {
                Item::Record(rec) => {
                    self.records.insert(rec.name.clone(), rec.clone());
                }
                Item::Routine(r) => {
                    let u = r.name.to_uppercase();
                    if R.contains(&u.as_str()) || ["X", "Y", "SP", "XL", "XH", "YL", "YH"].contains(&u.as_str()) {
                        return Err(err(&r.span, &format!("'{}' is a register name", r.name)));
                    }
                    if self.routines.insert(r.name.clone(), r.clone()).is_some() {
                        return Err(err(&r.span, &format!("routine '{}' declared twice", r.name)));
                    }
                }
                Item::GlobalVar(v) => {
                    let loc = match v.hw_address {
                        Some(a) => Loc::Abs(a),
                        None => Loc::Label(format!("v_{}", v.name)),
                    };
                    if self
                        .globals
                        .insert(v.name.clone(), Sym { ty: v.type_kind.clone(), loc })
                        .is_some()
                    {
                        return Err(err(&v.span, &format!("'{}' declared twice", v.name)));
                    }
                }
                Item::Const(name, value) => consts.push((name.clone(), *value)),
            }
        }

        let entry = if self.routines.contains_key("Main") {
            "Main".to_string()
        } else {
            match program.items.iter().rev().find_map(|i| match i {
                Item::Routine(r) => Some(r.name.clone()),
                _ => None,
            }) {
                Some(n) => n,
                None => return Err("no PROC to run".into()),
            }
        };

        self.raw("; CoolAction! generated assembly for COOL8");
        self.raw(&format!("        .org    ${:04X}", self.org));
        for (name, value) in &consts {
            self.raw(&format!("c_{} = {}", name, value));
        }
        for item in &program.items {
            if let Item::GlobalVar(v) = item {
                if let Some(a) = v.hw_address {
                    self.raw(&format!("v_{} = ${:04X}", v.name, a));
                }
            }
        }
        self.raw("");

        // The entry: run the program, come back to whoever loaded it --
        // with interrupts on, because the library's TakeKeys turns them
        // off to own the keyboard FIFO (sw/libaction.act), and BASIC,
        // the usual loader, needs them back. Harmless where they were
        // never off.
        self.label("_start");
        self.emit(&format!("CALL    {}", entry));
        self.emit("EI");
        self.emit("RET");
        self.raw("");

        for item in &program.items {
            if let Item::Routine(r) = item {
                self.gen_routine(r)?;
            }
        }

        self.gen_runtime();

        self.raw("; --- data ---");
        for item in &program.items {
            if let Item::GlobalVar(v) = item {
                if v.hw_address.is_some() {
                    continue;
                }
                self.gen_data(v)?;
            }
        }
        if self.runtime.contains("div16") {
            self.raw("__dv:   .space  2");
        }
        if self.runtime.contains("idiv16") {
            self.raw("__sg:   .space  2");
        }
        let strings = std::mem::take(&mut self.strings);
        for (lbl, bytes) in &strings {
            self.raw(&format!("{}:", lbl));
            self.emit(&format!(".byte   {}", bytes.len()));
            self.emit_bytes(bytes);
        }
        Ok(self.text())
    }

    fn emit_bytes(&mut self, bytes: &[u8]) {
        for chunk in bytes.chunks(16) {
            let s: Vec<String> = chunk.iter().map(|b| format!("${:02X}", b)).collect();
            self.emit(&format!(".byte   {}", s.join(",")));
        }
    }

    fn gen_data(&mut self, v: &VarDecl) -> Result<(), String> {
        let size = self.size_of(&v.type_kind, &v.span)?;
        if size == 0 {
            return Err(err(&v.span, &format!("'{}' has no size", v.name)));
        }
        self.raw(&format!("v_{}:", v.name));
        let elem_w = match &v.type_kind {
            TypeKind::Array(elem, _) => elem.width(),
            t => t.width(),
        };
        match &v.init {
            Init::None => self.emit(&format!(".space  {}", size)),
            Init::Str(s) => {
                let mut bytes = vec![s.len() as u8];
                bytes.extend_from_slice(s);
                self.emit_bytes(&bytes);
                if size > bytes.len() {
                    self.emit(&format!(".space  {}", size - bytes.len()));
                }
            }
            Init::Values(vals) => {
                if vals.len() * elem_w > size {
                    return Err(err(&v.span, &format!("'{}': more initial values than elements", v.name)));
                }
                for chunk in vals.chunks(if elem_w == 1 { 16 } else { 8 }) {
                    let s: Vec<String> = chunk
                        .iter()
                        .map(|x| {
                            if elem_w == 1 {
                                format!("${:02X}", x & 0xFF)
                            } else {
                                format!("${:04X}", x & 0xFFFF)
                            }
                        })
                        .collect();
                    self.emit(&format!("{}   {}", if elem_w == 1 { ".byte" } else { ".word" }, s.join(",")));
                }
                let used = vals.len() * elem_w;
                if size > used {
                    self.emit(&format!(".space  {}", size - used));
                }
            }
        }
        Ok(())
    }

    // --------------------------------------------------------- routines

    fn gen_routine(&mut self, r: &RoutineDecl) -> Result<(), String> {
        self.label(&r.name);
        self.locals.clear();
        self.loops.clear();
        self.depth = 0;
        self.cur_routine = Some(r.clone());

        let mut frame = 0;
        for local in &r.locals {
            frame += self.size_of(&local.type_kind, &local.span)?;
        }
        if frame > 200 {
            return Err(err(&r.span, &format!("'{}' has {} bytes of locals; 200 is the most", r.name, frame)));
        }
        self.frame = frame;
        self.adjust_sp(-(frame as i64));

        let mut off = 0;
        for local in &r.locals {
            let sz = self.size_of(&local.type_kind, &local.span)?;
            if self.locals.contains_key(&local.name) {
                return Err(err(&local.span, &format!("'{}' declared twice", local.name)));
            }
            self.locals.insert(
                local.name.clone(),
                Sym { ty: local.type_kind.clone(), loc: Loc::Stack(off) },
            );
            off += sz;
        }
        let mut poff = frame + 2;
        for p in &r.params {
            if self.locals.contains_key(&p.name) {
                return Err(err(&r.span, &format!("'{}' declared twice", p.name)));
            }
            self.locals.insert(p.name.clone(), Sym { ty: p.type_kind.clone(), loc: Loc::Stack(poff) });
            poff += p.type_kind.width();
        }
        if poff > 255 {
            return Err(err(&r.span, "too many parameter bytes"));
        }

        // =[value] on a local is a store at entry
        for local in &r.locals {
            let sym = self.locals[&local.name].clone();
            match &local.init {
                Init::None => {}
                Init::Values(vals) => {
                    let ew = match &local.type_kind {
                        TypeKind::Array(elem, _) => elem.width(),
                        t => t.width(),
                    };
                    for (i, v) in vals.iter().enumerate() {
                        self.emit(&format!("MOV     R0,#{}", v & 0xFF));
                        self.store_loc(&sym.loc, i * ew, "R0")?;
                        if ew == 2 {
                            self.emit(&format!("MOV     R0,#{}", (v >> 8) & 0xFF));
                            self.store_loc(&sym.loc, i * ew + 1, "R0")?;
                        }
                    }
                }
                Init::Str(s) => {
                    self.emit(&format!("MOV     R0,#{}", s.len()));
                    self.store_loc(&sym.loc, 0, "R0")?;
                    for (i, b) in s.iter().enumerate() {
                        self.emit(&format!("MOV     R0,#{}", b));
                        self.store_loc(&sym.loc, i + 1, "R0")?;
                    }
                }
            }
        }

        for stmt in &r.body {
            self.gen_stmt(stmt)?;
        }
        if !matches!(r.body.last().map(|s| &s.kind), Some(StmtKind::Return(_))) {
            self.gen_return(None, &r.span)?;
        }
        self.raw("");
        self.cur_routine = None;
        Ok(())
    }

    fn adjust_sp(&mut self, mut n: i64) {
        while n != 0 {
            let step = n.clamp(-128, 127);
            self.emit(&format!("ADDW    SP,#{}", step));
            n -= step;
        }
    }

    fn gen_return(&mut self, value: Option<&Expr>, span: &Span) -> Result<(), String> {
        let r = self.cur_routine.clone().unwrap();
        match (value, &r.return_type) {
            (Some(e), Some(rt)) => {
                let w = rt.width();
                self.gen_expr_w(e, w)?;
            }
            (Some(_), None) => return Err(err(span, "a PROC returns no value")),
            (None, Some(_)) => return Err(err(span, "a FUNC must RETURN (value)")),
            (None, None) => {}
        }
        self.adjust_sp(self.frame as i64);
        self.emit("RET");
        Ok(())
    }

    // ------------------------------------------------------- statements

    fn gen_block(&mut self, body: &[Stmt]) -> Result<(), String> {
        for s in body {
            self.gen_stmt(s)?;
        }
        Ok(())
    }

    fn gen_stmt(&mut self, stmt: &Stmt) -> Result<(), String> {
        let span = &stmt.span;
        match &stmt.kind {
            StmtKind::Assign { target, op, value } => self.gen_assign(target, op, value, span)?,
            StmtKind::Call { name, args } => {
                self.gen_call(name, args, span)?;
            }
            StmtKind::If { cond, then_branch, else_ifs, else_branch } => {
                let end = self.lbl("fi");
                let mut next = self.lbl("el");
                self.gen_cond(cond, &next, false)?;
                self.gen_block(then_branch)?;
                let more = !else_ifs.is_empty() || else_branch.is_some();
                if more {
                    self.emit(&format!("BRA     {}", end));
                }
                self.label(&next);
                for (i, (c, b)) in else_ifs.iter().enumerate() {
                    next = self.lbl("el");
                    self.gen_cond(c, &next, false)?;
                    self.gen_block(b)?;
                    if i + 1 < else_ifs.len() || else_branch.is_some() {
                        self.emit(&format!("BRA     {}", end));
                    }
                    self.label(&next);
                }
                if let Some(b) = else_branch {
                    self.gen_block(b)?;
                }
                self.label(&end);
            }
            StmtKind::While { cond, body } => {
                // Tested at the bottom: one branch a pass instead of a
                // test, a branch and a BRA back. The entry jumps to
                // the test, so a false condition still runs the body
                // zero times.
                let top = self.lbl("wh");
                let test = self.lbl("wt");
                let end = self.lbl("od");
                self.emit(&format!("BRA     {}", test));
                self.label(&top);
                self.loops.push(end.clone());
                self.gen_block(body)?;
                self.loops.pop();
                self.label(&test);
                self.gen_cond(cond, &top, true)?;
                self.label(&end);
            }
            StmtKind::DoLoop { body, until_cond } => {
                let top = self.lbl("do");
                let end = self.lbl("od");
                self.label(&top);
                self.loops.push(end.clone());
                self.gen_block(body)?;
                self.loops.pop();
                match until_cond {
                    Some(c) => self.gen_cond(c, &top, false)?,
                    None => self.emit(&format!("BRA     {}", top)),
                }
                self.label(&end);
            }
            StmtKind::For { var, start, to, step, body } => {
                let sym = self.lookup(var, span)?;
                if matches!(sym.ty, TypeKind::Array(..) | TypeKind::UserDefined(_)) {
                    return Err(err(span, "loop variable must be a BYTE, CARD or INT"));
                }
                let var_e = Expr { kind: ExprKind::Variable(var.clone()), span: span.clone() };
                let step_e = step
                    .clone()
                    .unwrap_or(Expr { kind: ExprKind::Number(1), span: span.clone() });
                let down = self.const_of(&step_e).map(|v| v < 0).unwrap_or(false);
                self.gen_assign(&var_e, &AssignOp::Assign, start, span)?;
                // Tested at the bottom, like WHILE: the step and the
                // test are one straight run, and the peephole pass then
                // finds the stepped value still in R0 for the compare.
                let top = self.lbl("for");
                let test_l = self.lbl("ft");
                let end = self.lbl("od");
                let test = Expr {
                    kind: ExprKind::Binary {
                        op: if down { BinaryOp::Lt } else { BinaryOp::Gt },
                        left: Box::new(var_e.clone()),
                        right: Box::new(to.clone()),
                    },
                    span: span.clone(),
                };
                self.emit(&format!("BRA     {}", test_l));
                self.label(&top);
                self.loops.push(end.clone());
                self.gen_block(body)?;
                self.loops.pop();
                self.gen_assign(&var_e, &AssignOp::PlusAssign, &step_e, span)?;
                self.label(&test_l);
                self.gen_cond(&test, &top, false)?;
                self.label(&end);
            }
            StmtKind::Return(e) => self.gen_return(e.as_ref(), span)?,
            StmtKind::Exit => match self.loops.last() {
                Some(l) => {
                    let l = l.clone();
                    self.emit(&format!("BRA     {}", l));
                }
                None => return Err(err(span, "EXIT outside a loop")),
            },
            StmtKind::Asm(raw) => {
                for line in raw.lines() {
                    let t = line.trim();
                    if t.is_empty() {
                        continue;
                    }
                    // A global label here would end the routine's local
                    // label scope halfway through, and the compiler's own
                    // labels are local ones.
                    if let Some(p) = t.find(':') {
                        let head = t[..p].trim();
                        if !head.is_empty()
                            && !head.starts_with('.')
                            && head.chars().all(|c| c.is_alphanumeric() || c == '_')
                        {
                            return Err(err(span, "an ASM block may define local labels (.name) only"));
                        }
                    }
                    // as written, and a wall to the peephole pass: a
                    // hand-written block may branch on a load's flags
                    self.raw(&format!("    {}", t));
                }
            }
            StmtKind::Assert { cond, msg } => {
                let ok = self.lbl("ok");
                self.gen_cond(cond, &ok, true)?;
                if let Some(m) = msg {
                    let l = self.string(m.clone());
                    self.emit(&format!("LDW     X,#{}", l));
                }
                self.emit("BRK");
                self.label(&ok);
            }
            StmtKind::Break => self.emit("BRK"),
        }
        Ok(())
    }

    fn string(&mut self, bytes: Vec<u8>) -> String {
        let l = format!("str_{}", self.strings.len() + 1);
        self.strings.push((l.clone(), bytes));
        l
    }

    /// Can the address side be computed without touching R0/R1?
    fn lvalue_simple(&self, target: &Expr) -> bool {
        match &target.kind {
            ExprKind::Variable(_) => true,
            ExprKind::Deref(inner) => matches!(inner.kind, ExprKind::Variable(_)),
            ExprKind::FieldAccess { base, .. } => match &base.kind {
                ExprKind::Variable(_) => true,
                ExprKind::Deref(inner) => matches!(inner.kind, ExprKind::Variable(_)),
                _ => false,
            },
            ExprKind::Call { name, args } => {
                if args.len() != 1 {
                    return false;
                }
                let sym = match self.lookup(name, &target.span) {
                    Ok(s) => s,
                    Err(_) => return false,
                };
                if !matches!(sym.ty, TypeKind::Array(..)) {
                    return false;
                }
                let idx = match self.simple(&args[0]) {
                    Some(s) => s,
                    None => return false,
                };
                // A 16-bit index into a local array needs LEA and the
                // pair; anything else fits in R2/R3.
                let idx_w = match &idx {
                    Simple::Const(v) => if (0..=255).contains(v) { 1 } else { 2 },
                    Simple::Var(s) => s.ty.width(),
                    Simple::Addr(_) => 2,
                };
                !(idx_w == 2 && matches!(sym.loc, Loc::Stack(_)))
            }
            _ => false,
        }
    }

    fn gen_assign(&mut self, target: &Expr, op: &AssignOp, value: &Expr, span: &Span) -> Result<(), String> {
        let tt = self.type_of(target)?;
        if matches!(tt, TypeKind::Array(..) | TypeKind::UserDefined(_)) {
            return Err(err(span, "cannot assign a whole array or record"));
        }
        let value = match op.binary() {
            Some(b) => Expr {
                kind: ExprKind::Binary { op: b, left: Box::new(target.clone()), right: Box::new(value.clone()) },
                span: span.clone(),
            },
            None => value.clone(),
        };
        let w = tt.width();
        if self.lvalue_simple(target) {
            self.gen_expr_w(&value, w)?;
            let (lv, _) = self.lvalue(target, false)?;
            self.store_lval(&lv, w)
        } else {
            self.gen_expr_w(&value, w)?;
            self.push_pair(w);
            let (lv, _) = self.lvalue(target, true)?;
            if let LVal::YR(0) = lv {
                // A byte at a computed byte index: the index is in R0, so
                // the value comes off the stack beside it and not over it.
                // Popped into R0 it was, and `arr(i + 1) = v` stored v at
                // arr + v -- until SLIDES' LoadRpl wrote a file name 82
                // bytes past its array (D104).
                self.pop("R2");
                self.emit("ST      [Y+R0],R2");
                return Ok(());
            }
            self.pop_pair(w);
            self.store_lval(&lv, w)
        }
    }

    /// Compute the address side of `e`. With `free01` false only R2, R3
    /// and Y may be used, which `lvalue_simple` guarantees is enough.
    fn lvalue(&mut self, e: &Expr, free01: bool) -> Result<(LVal, TypeKind), String> {
        let span = &e.span;
        match &e.kind {
            ExprKind::Variable(name) => {
                let sym = self.lookup(name, span)?;
                if matches!(sym.ty, TypeKind::Array(..) | TypeKind::UserDefined(_)) {
                    return Err(err(
                        span,
                        &format!("cannot assign a whole array or record; '{}' takes an element or a field", name),
                    ));
                }
                Ok((LVal::At(sym.loc, 0), sym.ty))
            }
            ExprKind::Deref(inner) => {
                let t = match self.type_of(inner)? {
                    TypeKind::Pointer(t) => *t,
                    _ => TypeKind::Byte,
                };
                self.ptr_to_y(inner, free01)?;
                Ok((LVal::Y, t))
            }
            ExprKind::FieldAccess { base, field } => {
                let bt = self.type_of(base)?;
                match bt {
                    TypeKind::Pointer(t) => {
                        let rec = match *t {
                            TypeKind::UserDefined(r) => r,
                            _ => return Err(err(span, "field access on something that is not a record")),
                        };
                        let f = self.field(&rec, field, span)?;
                        if f.offset > 126 {
                            return Err(err(span, "record too large"));
                        }
                        // The base is either a record variable (its
                        // address is static) or a pointer to one.
                        if let ExprKind::Variable(name) = &base.kind {
                            let sym = self.lookup(name, span)?;
                            if matches!(sym.ty, TypeKind::UserDefined(_)) {
                                return Ok((LVal::At(sym.loc, f.offset), f.type_kind));
                            }
                        }
                        self.ptr_to_y(base, free01)?;
                        Ok((LVal::YD(f.offset), f.type_kind))
                    }
                    _ => Err(err(span, "field access on something that is not a record")),
                }
            }
            ExprKind::Call { name, args } => {
                let sym = self.lookup(name, span)?;
                let elem = match &sym.ty {
                    TypeKind::Array(elem, _) => (**elem).clone(),
                    _ => return Err(err(span, &format!("'{}' is not an array", name))),
                };
                if args.len() != 1 {
                    return Err(err(span, "an array takes one index"));
                }
                let ew = elem.width();
                let idx = &args[0];
                let it = self.type_of(idx)?;
                let idx_w = if let Some(v) = self.const_of(idx) {
                    if (0..=255).contains(&v) { 1 } else { 2 }
                } else {
                    it.width()
                };
                let (lo, hi) = if free01 { ("R0", "R1") } else { ("R2", "R3") };
                if idx_w == 1 {
                    // Y = base; [Y+Rn] for bytes, Y += 2*index for words
                    match self.simple(idx) {
                        Some(s) => self.load_simple(&s, lo, hi, 1)?,
                        None => {
                            self.gen_expr_w(idx, 1)?;
                        }
                    }
                    match &sym.loc {
                        Loc::Label(l) => self.emit(&format!("LDW     Y,#{}", l)),
                        Loc::Abs(a) => self.emit(&format!("LDW     Y,#${:04X}", a)),
                        Loc::Stack(o) => {
                            let off = o + self.depth;
                            if off > 255 {
                                return Err(err(span, "frame too deep"));
                            }
                            self.emit(&format!("LEA     Y,[SP+{}]", off));
                        }
                    }
                    if ew == 1 {
                        let r = if free01 { 0 } else { 2 };
                        return Ok((LVal::YR(r), elem));
                    }
                    self.emit(&format!("ADDW    Y,{}", lo));
                    self.emit(&format!("ADDW    Y,{}", lo));
                    return Ok((LVal::Y, elem));
                }
                // 16-bit index: scale it, add the base, hand it to Y.
                // A word variable in memory indexing a byte array is
                // the sieve's inner loop, and LDW Y,[abs] is the
                // pair loaded and moved in one instruction.
                if ew == 1 {
                    if let Some(Simple::Var(s)) = self.simple(idx) {
                        if s.ty.width() == 2 && !matches!(s.loc, Loc::Stack(_)) {
                            let o = self.operand(&s.loc, 0)?;
                            self.emit(&format!("LDW     Y,{}", o));
                            match &sym.loc {
                                Loc::Label(l) => self.emit(&format!("ADDW    Y,#{}", l)),
                                Loc::Abs(a) => self.emit(&format!("ADDW    Y,#${:04X}", a)),
                                Loc::Stack(_) => unreachable!(),
                            }
                            return Ok((LVal::Y, elem));
                        }
                    }
                }
                match self.simple(idx) {
                    Some(s) => self.load_simple(&s, lo, hi, 2)?,
                    None => {
                        if !free01 {
                            return Err(err(span, "internal: complex index in a simple lvalue"));
                        }
                        self.gen_expr_w(idx, 2)?;
                    }
                }
                if ew == 2 {
                    self.emit(&format!("ADD     {},{}", lo, lo));
                    self.emit(&format!("ADC     {},{}", hi, hi));
                }
                match &sym.loc {
                    Loc::Label(l) => {
                        self.emit(&format!("MOV     YL,{}", lo));
                        self.emit(&format!("MOV     YH,{}", hi));
                        self.emit(&format!("ADDW    Y,#{}", l));
                    }
                    Loc::Abs(a) => {
                        self.emit(&format!("MOV     YL,{}", lo));
                        self.emit(&format!("MOV     YH,{}", hi));
                        self.emit(&format!("ADDW    Y,#${:04X}", a));
                    }
                    Loc::Stack(o) => {
                        if !free01 {
                            return Err(err(span, "internal: local array with a word index in a simple lvalue"));
                        }
                        let off = o + self.depth;
                        if off > 255 {
                            return Err(err(span, "frame too deep"));
                        }
                        self.emit(&format!("LEA     X,[SP+{}]", off));
                        self.emit("MOV     R2,XL");
                        self.emit("MOV     R3,XH");
                        self.emit("ADD     R0,R2");
                        self.emit("ADC     R1,R3");
                        self.emit("MOV     YL,R0");
                        self.emit("MOV     YH,R1");
                    }
                }
                Ok((LVal::Y, elem))
            }
            _ => Err(err(span, "not something that can be assigned to")),
        }
    }

    /// Put the value of a pointer expression in Y.
    fn ptr_to_y(&mut self, e: &Expr, free01: bool) -> Result<(), String> {
        if let ExprKind::Variable(name) = &e.kind {
            let sym = self.lookup(name, &e.span)?;
            match (&sym.ty, &sym.loc) {
                (TypeKind::Array(..), _) | (TypeKind::UserDefined(_), _) => {
                    return Err(err(&e.span, &format!("'{}' is not a pointer", name)));
                }
                (_, Loc::Label(l)) => {
                    self.emit(&format!("LDW     Y,[{}]", l));
                    return Ok(());
                }
                (_, Loc::Abs(a)) => {
                    self.emit(&format!("LDW     Y,[${:04X}]", a));
                    return Ok(());
                }
                (_, Loc::Stack(_)) => {
                    let (lo, hi) = if free01 { ("R0", "R1") } else { ("R2", "R3") };
                    self.load_simple(&Simple::Var(sym.clone()), lo, hi, 2)?;
                    self.emit(&format!("MOV     YL,{}", lo));
                    self.emit(&format!("MOV     YH,{}", hi));
                    return Ok(());
                }
            }
        }
        if !free01 {
            return Err(err(&e.span, "internal: complex pointer in a simple lvalue"));
        }
        self.gen_expr_w(e, 2)?;
        self.emit("MOV     YL,R0");
        self.emit("MOV     YH,R1");
        Ok(())
    }

    // ------------------------------------------------------------ calls

    fn gen_call(&mut self, name: &str, args: &[Expr], span: &Span) -> Result<Option<TypeKind>, String> {
        let decl = match self.routines.get(name) {
            Some(d) => d.clone(),
            None => {
                if self.lookup(name, span).is_ok() {
                    return Err(err(span, &format!("'{}' is a variable, not a routine", name)));
                }
                return Err(err(span, &format!("undefined routine '{}'", name)));
            }
        };
        if args.len() != decl.params.len() {
            return Err(err(
                span,
                &format!("'{}' takes {} argument(s), given {}", name, decl.params.len(), args.len()),
            ));
        }
        let mut bytes = 0;
        for (arg, p) in args.iter().zip(decl.params.iter()).rev() {
            let w = p.type_kind.width();
            self.gen_expr_w(arg, w)?;
            self.push_pair(w);
            bytes += w;
        }
        self.emit(&format!("CALL    {}", name));
        if bytes > 0 {
            self.adjust_sp(bytes as i64);
            self.depth -= bytes;
        }
        Ok(decl.return_type)
    }

    // ------------------------------------------------------- conditions

    /// Branch to `target` when `e` is true (or false).
    fn gen_cond(&mut self, e: &Expr, target: &str, jump_if_true: bool) -> Result<(), String> {
        if let Some(v) = self.const_of(e) {
            if (v != 0) == jump_if_true {
                self.emit(&format!("BRA     {}", target));
            }
            return Ok(());
        }
        match &e.kind {
            ExprKind::Binary { op: BinaryOp::LogicalAnd, left, right } => {
                if jump_if_true {
                    let skip = self.lbl("an");
                    self.gen_cond(left, &skip, false)?;
                    self.gen_cond(right, target, true)?;
                    self.label(&skip);
                } else {
                    self.gen_cond(left, target, false)?;
                    self.gen_cond(right, target, false)?;
                }
                return Ok(());
            }
            ExprKind::Binary { op: BinaryOp::LogicalOr, left, right } => {
                if jump_if_true {
                    self.gen_cond(left, target, true)?;
                    self.gen_cond(right, target, true)?;
                } else {
                    let skip = self.lbl("or");
                    self.gen_cond(left, &skip, true)?;
                    self.gen_cond(right, target, false)?;
                    self.label(&skip);
                }
                return Ok(());
            }
            ExprKind::Unary { op: UnaryOp::LogicalNot, expr } => {
                return self.gen_cond(expr, target, !jump_if_true);
            }
            ExprKind::Binary { op, left, right }
                if matches!(
                    op,
                    BinaryOp::Eq | BinaryOp::Ne | BinaryOp::Lt | BinaryOp::Le | BinaryOp::Gt | BinaryOp::Ge
                ) =>
            {
                let lt = self.type_of(left)?;
                let rt = self.type_of(right)?;
                let w = lt.width().max(rt.width());
                let signed = lt.is_signed() || rt.is_signed();
                let rc = self.const_of(right);
                if w == 1 {
                    if let Some(v) = rc {
                        self.gen_expr_w(left, 1)?;
                        self.emit(&format!("CMP     R0,#{}", v & 0xFF));
                    } else {
                        self.operands(left, right, 1)?;
                        self.emit("CMP     R0,R2");
                    }
                } else if matches!(op, BinaryOp::Lt | BinaryOp::Le | BinaryOp::Gt | BinaryOp::Ge)
                    && !(rc == Some(0) && !signed)
                {
                    // **An ordering of two words is a subtraction and one
                    // branch.** SUB/SBC leaves the 16-bit result's sign and
                    // overflow in N and V, which BLT/BGE read, and its
                    // borrow in C, which BLO/BHS read -- so a signed
                    // compare is 7 clocks where flipping both sign bits
                    // and comparing twice was 15, and an unsigned one 7
                    // for 9. `>` and `<=` are the other operand's `<` and
                    // `>=`: against a constant that is the constant plus
                    // one, otherwise the subtraction is done the other
                    // way round into R2:R3. Z after SBC is the high
                    // byte's alone, which is why BGT/BLE are not used.
                    let mut cmp_lt = matches!(op, BinaryOp::Lt | BinaryOp::Gt);
                    let mut swap = matches!(op, BinaryOp::Gt | BinaryOp::Le);
                    let mut cval = rc;
                    if swap {
                        if let Some(v) = rc {
                            let top = if signed { 32767 } else { 65535 };
                            if v < top {
                                cval = Some(v + 1);
                                swap = false;
                                cmp_lt = !cmp_lt; // a > k is a >= k+1; a <= k is a < k+1
                            } else {
                                cval = None;
                            }
                        }
                    }
                    if let Some(v) = cval {
                        self.gen_expr_w(left, 2)?;
                        self.emit(&format!("SUB     R0,#{}", v & 0xFF));
                        self.emit(&format!("SBC     R1,#{}", (v >> 8) & 0xFF));
                    } else {
                        self.operands(left, right, 2)?;
                        if swap {
                            self.emit("SUB     R2,R0");
                            self.emit("SBC     R3,R1");
                        } else {
                            self.emit("SUB     R0,R2");
                            self.emit("SBC     R1,R3");
                        }
                    }
                    // the branch takes when the difference is negative
                    // for `<` wanted true or `>=` wanted false
                    let neg = cmp_lt == jump_if_true;
                    let br = match (signed, neg) {
                        (true, true) => "BLT",
                        (true, false) => "BGE",
                        (false, true) => "BLO",
                        (false, false) => "BHS",
                    };
                    self.emit(&format!("{}     {}", br, target));
                    return Ok(());
                } else if rc == Some(0)
                    && !signed
                    && matches!(op, BinaryOp::Eq | BinaryOp::Ne | BinaryOp::Gt | BinaryOp::Le)
                {
                    // a word against zero: `n > 0`, `n == 0`, the test of
                    // every countdown loop -- one OR of the two bytes
                    // and a Z branch, not two compares and a label
                    self.gen_expr_w(left, 2)?;
                    self.emit("OR      R0,R1");
                    let br = match (op, jump_if_true) {
                        (BinaryOp::Eq, true) | (BinaryOp::Le, true) => "BEQ",
                        (BinaryOp::Eq, false) | (BinaryOp::Le, false) => "BNE",
                        (BinaryOp::Ne, true) | (BinaryOp::Gt, true) => "BNE",
                        _ => "BEQ",
                    };
                    self.emit(&format!("{}     {}", br, target));
                    return Ok(());
                } else if let Some(v) = rc {
                    // against a constant: the immediates, no R2/R3. A
                    // signed compare flips the sign bit of both sides
                    // so that unsigned branches order them; with a
                    // constant that is one XOR on R1 and a flipped
                    // immediate, not two registers loaded and flipped.
                    self.gen_expr_w(left, 2)?;
                    let l = self.lbl("cm");
                    let hi = ((v >> 8) & 0xFF) ^ if signed { 0x80 } else { 0 };
                    if signed {
                        self.emit("XOR     R1,#$80");
                    }
                    self.emit(&format!("CMP     R1,#{}", hi));
                    self.emit(&format!("BNE     {}", l));
                    self.emit(&format!("CMP     R0,#{}", v & 0xFF));
                    self.join(&l);
                } else {
                    self.operands(left, right, 2)?;
                    if signed {
                        self.emit("XOR     R1,#$80");
                        self.emit("XOR     R3,#$80");
                    }
                    let l = self.lbl("cm");
                    self.emit("CMP     R1,R3");
                    self.emit(&format!("BNE     {}", l));
                    self.emit("CMP     R0,R2");
                    self.join(&l);
                }
                let br = match (op, jump_if_true) {
                    (BinaryOp::Eq, true) | (BinaryOp::Ne, false) => "BEQ",
                    (BinaryOp::Eq, false) | (BinaryOp::Ne, true) => "BNE",
                    (BinaryOp::Lt, true) | (BinaryOp::Ge, false) => "BLO",
                    (BinaryOp::Lt, false) | (BinaryOp::Ge, true) => "BHS",
                    (BinaryOp::Le, true) | (BinaryOp::Gt, false) => "BLS",
                    (BinaryOp::Le, false) | (BinaryOp::Gt, true) => "BHI",
                    _ => unreachable!(),
                };
                self.emit(&format!("{}     {}", br, target));
                return Ok(());
            }
            _ => {}
        }
        let t = self.gen_expr(e)?;
        if t.width() == 1 {
            self.emit("OR      R0,R0");
        } else {
            self.emit("OR      R0,R1");
        }
        self.emit(&format!("{}     {}", if jump_if_true { "BNE" } else { "BEQ" }, target));
        Ok(())
    }

    // ------------------------------------------------------ expressions

    /// Evaluate to R0 / R1:R0, widened or narrowed to `w` bytes.
    fn gen_expr_w(&mut self, e: &Expr, w: usize) -> Result<TypeKind, String> {
        let t = self.gen_expr(e)?;
        if w == 2 && t.width() == 1 {
            self.emit("CLR     R1");
        }
        Ok(t)
    }

    /// Left into R0/R1 and right into R2/R3, both `w` wide.
    fn operands(&mut self, left: &Expr, right: &Expr, w: usize) -> Result<(), String> {
        if let Some(s) = self.simple(right) {
            self.gen_expr_w(left, w)?;
            self.load_simple(&s, "R2", "R3", w)?;
        } else if let Some(s) = self.simple(left) {
            self.gen_expr_w(right, w)?;
            self.emit("MOV     R2,R0");
            if w == 2 {
                self.emit("MOV     R3,R1");
            }
            self.load_simple(&s, "R0", "R1", w)?;
        } else {
            self.gen_expr_w(left, w)?;
            self.push_pair(w);
            self.gen_expr_w(right, w)?;
            self.emit("MOV     R2,R0");
            if w == 2 {
                self.emit("MOV     R3,R1");
            }
            self.pop_pair(w);
        }
        Ok(())
    }

    fn gen_const(&mut self, v: i64) -> TypeKind {
        if v == 0 {
            self.emit("CLR     R0"); // SUB R0,R0: 2 clocks against MOV's 3
            TypeKind::Byte
        } else if (0..=255).contains(&v) {
            self.emit(&format!("MOV     R0,#{}", v));
            TypeKind::Byte
        } else {
            self.emit(&format!("MOV     R0,#{}", v & 0xFF));
            self.emit(&format!("MOV     R1,#{}", (v >> 8) & 0xFF));
            if v < 0 { TypeKind::Int } else { TypeKind::Card }
        }
    }

    pub fn gen_expr(&mut self, e: &Expr) -> Result<TypeKind, String> {
        let span = &e.span;
        if let Some(v) = self.const_of(e) {
            return Ok(self.gen_const(v));
        }
        match &e.kind {
            ExprKind::Number(_) | ExprKind::CharLit(_) => unreachable!(),
            ExprKind::Str(s) => {
                let l = self.string(s.clone());
                self.emit(&format!("MOV     R0,#<{}", l));
                self.emit(&format!("MOV     R1,#>{}", l));
                Ok(TypeKind::Pointer(Box::new(TypeKind::Byte)))
            }
            ExprKind::Variable(name) => {
                let sym = self.lookup(name, span)?;
                match &sym.ty {
                    TypeKind::Array(elem, _) => {
                        self.load_simple(&Simple::Addr(sym.loc.clone()), "R0", "R1", 2)?;
                        Ok(TypeKind::Pointer(elem.clone()))
                    }
                    TypeKind::UserDefined(_) => {
                        self.load_simple(&Simple::Addr(sym.loc.clone()), "R0", "R1", 2)?;
                        Ok(TypeKind::Pointer(Box::new(sym.ty.clone())))
                    }
                    t => {
                        let w = t.width();
                        self.load_simple(&Simple::Var(sym.clone()), "R0", "R1", w)?;
                        Ok(t.clone())
                    }
                }
            }
            ExprKind::AddrOf(name) => {
                let sym = self.lookup(name, span)?;
                self.load_simple(&Simple::Addr(sym.loc.clone()), "R0", "R1", 2)?;
                Ok(match sym.ty {
                    TypeKind::Array(elem, _) => TypeKind::Pointer(elem),
                    t => TypeKind::Pointer(Box::new(t)),
                })
            }
            ExprKind::Deref(_) | ExprKind::FieldAccess { .. } => {
                let (lv, t) = self.lvalue(e, true)?;
                if matches!(t, TypeKind::UserDefined(_) | TypeKind::Array(..)) {
                    return Err(err(span, "a record has no value; name a field"));
                }
                self.load_lval(&lv, t.width())?;
                Ok(t)
            }
            ExprKind::Call { name, args } => {
                if let Ok(sym) = self.lookup(name, span) {
                    if matches!(sym.ty, TypeKind::Array(..)) {
                        let (lv, t) = self.lvalue(e, true)?;
                        self.load_lval(&lv, t.width())?;
                        return Ok(t);
                    }
                }
                match self.gen_call(name, args, span)? {
                    Some(t) => Ok(t),
                    None => Err(err(span, &format!("PROC '{}' has no value", name))),
                }
            }
            ExprKind::Unary { op, expr } => match op {
                UnaryOp::Neg => {
                    self.gen_expr_w(expr, 2)?;
                    self.emit("NOT     R0");
                    self.emit("NOT     R1");
                    self.emit("ADD     R0,#1");
                    self.emit("ADC     R1,#0");
                    Ok(TypeKind::Int)
                }
                UnaryOp::BitNot => {
                    let t = self.gen_expr(expr)?;
                    self.emit("NOT     R0");
                    if t.width() == 2 {
                        self.emit("NOT     R1");
                    }
                    Ok(t)
                }
                UnaryOp::LogicalNot => self.gen_bool(e),
            },
            ExprKind::Binary { op, left, right } => self.gen_binary(op, left, right, span),
        }
    }

    /// A condition as a value: 0 or 1 in R0.
    fn gen_bool(&mut self, e: &Expr) -> Result<TypeKind, String> {
        let t = self.lbl("tr");
        let end = self.lbl("bo");
        self.gen_cond(e, &t, true)?;
        self.emit("MOV     R0,#0");
        self.emit(&format!("BRA     {}", end));
        self.label(&t);
        self.emit("MOV     R0,#1");
        self.label(&end);
        Ok(TypeKind::Byte)
    }

    fn gen_binary(&mut self, op: &BinaryOp, left: &Expr, right: &Expr, span: &Span) -> Result<TypeKind, String> {
        let whole = Expr {
            kind: ExprKind::Binary { op: op.clone(), left: Box::new(left.clone()), right: Box::new(right.clone()) },
            span: span.clone(),
        };
        let lt = self.type_of(left)?;
        let rt = self.type_of(right)?;
        let result = self.type_of(&whole)?;
        match op {
            BinaryOp::Eq
            | BinaryOp::Ne
            | BinaryOp::Lt
            | BinaryOp::Le
            | BinaryOp::Gt
            | BinaryOp::Ge
            | BinaryOp::LogicalAnd
            | BinaryOp::LogicalOr => self.gen_bool(&whole),

            BinaryOp::Mul => {
                // by a small power of two: shifts. A BYTE times 2 is
                // CLR R1 / ADD R0,R0 / ADC R1,R1, 6 clocks, where the
                // MUL path is 20; a word times 4 is 16 where __mul16 is
                // a call and a loop. `c * 2` is every other array index.
                if let Some(d) = self.const_of(right) {
                    if d > 0 && (d & (d - 1)) == 0 && d <= 16 {
                        let k = d.trailing_zeros() as usize;
                        self.gen_expr_w(left, result.width())?;
                        self.shift_const(true, k, result.width(), false);
                        return Ok(result);
                    }
                }
                if lt.width() == 1 && rt.width() == 1 {
                    self.operands(left, right, 1)?;
                    self.emit("MUL     R0,R2");
                    self.emit("MOV     R0,XL");
                    self.emit("MOV     R1,XH");
                } else {
                    self.operands(left, right, 2)?;
                    self.runtime.insert("mul16");
                    self.emit("CALL    __mul16");
                }
                Ok(result)
            }

            BinaryOp::Div | BinaryOp::Mod => {
                let signed = lt.is_signed() || rt.is_signed();
                if let Some(d) = self.const_of(right) {
                    if d > 0 && (d & (d - 1)) == 0 && !signed {
                        let k = d.trailing_zeros() as usize;
                        let w = lt.width();
                        self.gen_expr(left)?;
                        if *op == BinaryOp::Div {
                            self.shift_const(false, k, w, false);
                        } else if w == 1 {
                            self.emit(&format!("AND     R0,#{}", (d - 1) & 0xFF));
                        } else {
                            self.emit(&format!("AND     R0,#{}", (d - 1) & 0xFF));
                            self.emit(&format!("AND     R1,#{}", ((d - 1) >> 8) & 0xFF));
                        }
                        return Ok(lt);
                    }
                    // signed, by a power of two: C's truncation towards
                    // zero is an arithmetic shift of the value biased by
                    // d-1 when it is negative. MANDEL's iteration is
                    // `a*b/32` and `a*a/64` twice a pass, and each was a
                    // call into a sixteen-step division loop.
                    if d > 0 && (d & (d - 1)) == 0 && signed && *op == BinaryOp::Div && d <= 256 {
                        let k = d.trailing_zeros() as usize;
                        self.gen_expr_w(left, 2)?;
                        let pos = self.lbl("dp");
                        self.emit("OR      R1,R1");
                        self.emit(&format!("BPL     {}", pos));
                        self.emit(&format!("ADD     R0,#{}", (d - 1) & 0xFF));
                        self.emit(&format!("ADC     R1,#{}", ((d - 1) >> 8) & 0xFF));
                        self.label(&pos);
                        self.shift_const(false, k, 2, true);
                        return Ok(TypeKind::Int);
                    }
                }
                let w = lt.width().max(rt.width());
                if w == 1 {
                    self.operands(left, right, 1)?;
                    self.emit("MOV     R1,R2");
                    self.runtime.insert("div8");
                    self.emit("CALL    __div8");
                    if *op == BinaryOp::Mod {
                        self.emit("MOV     R0,R2");
                    }
                    return Ok(TypeKind::Byte);
                }
                self.operands(left, right, 2)?;
                if signed {
                    self.runtime.insert("div16");
                    self.runtime.insert("idiv16");
                    self.emit("CALL    __idiv16");
                } else {
                    self.runtime.insert("div16");
                    self.emit("CALL    __div16");
                }
                if *op == BinaryOp::Mod {
                    self.emit("MOV     R0,R2");
                    self.emit("MOV     R1,R3");
                }
                Ok(result)
            }

            BinaryOp::Shl | BinaryOp::Shr => {
                let w = lt.width();
                let left_shift = *op == BinaryOp::Shl;
                let arith = lt.is_signed();
                if let Some(n) = self.const_of(right) {
                    self.gen_expr(left)?;
                    self.shift_const(left_shift, n.max(0) as usize, w, arith);
                    return Ok(lt);
                }
                match self.simple(right) {
                    Some(s) => {
                        self.gen_expr(left)?;
                        self.load_simple(&s, "R2", "R3", 1)?;
                    }
                    None => {
                        self.gen_expr(left)?;
                        self.push_pair(w);
                        self.gen_expr(right)?;
                        self.emit("MOV     R2,R0");
                        self.pop_pair(w);
                    }
                }
                let top = self.lbl("sh");
                let end = self.lbl("sd");
                self.emit("OR      R2,R2");
                self.emit(&format!("BEQ     {}", end));
                self.label(&top);
                self.shift_const(left_shift, 1, w, arith);
                self.emit("SUB     R2,#1");
                self.emit(&format!("BNE     {}", top));
                self.label(&end);
                Ok(lt)
            }

            BinaryOp::Add | BinaryOp::Sub | BinaryOp::BitAnd | BinaryOp::BitOr | BinaryOp::BitXor => {
                let w = result.width();
                let (m8, m16, imm) = match op {
                    BinaryOp::Add => ("ADD", "ADC", true),
                    BinaryOp::Sub => ("SUB", "SBC", true),
                    BinaryOp::BitAnd => ("AND", "AND", true),
                    BinaryOp::BitOr => ("OR", "OR", true),
                    _ => ("XOR", "XOR", true),
                };
                if let Some(v) = self.const_of(right) {
                    if imm {
                        self.gen_expr_w(left, w)?;
                        self.emit(&format!("{:<7} R0,#{}", m8, v & 0xFF));
                        if w == 2 {
                            self.emit(&format!("{:<7} R1,#{}", m16, (v >> 8) & 0xFF));
                        }
                        return Ok(result);
                    }
                }
                self.operands(left, right, w)?;
                self.emit(&format!("{:<7} R0,R2", m8));
                if w == 2 {
                    self.emit(&format!("{:<7} R1,R3", m16));
                }
                Ok(result)
            }
        }
    }

    fn shift_const(&mut self, left: bool, n: usize, w: usize, arith: bool) {
        if n == 0 {
            return;
        }
        if w == 1 {
            if n >= 8 {
                if !left && arith {
                    // sign fill: not reachable, bytes are unsigned
                }
                self.emit("CLR     R0");
                return;
            }
            for _ in 0..n {
                if left {
                    self.emit("ADD     R0,R0");
                } else {
                    self.emit("SHR     R0");
                }
            }
            return;
        }
        // **The sign extension of R1 into itself is three instructions,
        // and the first version had it wrong.** `SEXC` is `SBC Rd,Rd`,
        // which under D9's carry-means-no-borrow is $00 when C is set
        // and $FF when it is clear; `ADD R1,R1` puts the sign bit in C,
        // so the pair gives the *inverse* and needs the `NOT`. The old
        // sequence was `SAR R1 / SEXC R1`, which extended from the bit
        // shifted out -- bit 0 -- and `INT >> 8` came out as 255 for
        // -1. It was never reached until signed division by a power of
        // two became a shift, and the features test caught it then.
        let sext = |cg: &mut Self| {
            cg.emit("ADD     R1,R1");
            cg.emit("SEXC    R1");
            cg.emit("NOT     R1");
        };
        let mut n = n;
        if n >= 16 {
            if left || !arith {
                self.emit("CLR     R0");
                self.emit("CLR     R1");
            } else {
                sext(self);
                self.emit("MOV     R0,R1");
            }
            return;
        }
        if n >= 8 {
            if left {
                self.emit("MOV     R1,R0");
                self.emit("CLR     R0");
            } else {
                self.emit("MOV     R0,R1");
                if arith {
                    sext(self);
                } else {
                    self.emit("CLR     R1");
                }
            }
            n -= 8;
        }
        for _ in 0..n {
            if left {
                self.emit("ADD     R0,R0");
                self.emit("ADC     R1,R1");
            } else {
                self.emit(if arith { "SAR     R1" } else { "SHR     R1" });
                self.emit("ROR     R0");
            }
        }
    }

    // ---------------------------------------------------------- runtime

    /// The routines an operator calls into, emitted only when used.
    fn gen_runtime(&mut self) {
        let used = self.runtime.clone();
        if used.contains("mul16") {
            // R1:R0 = R1:R0 * R3:R2, low 16 bits. Clobbers R2, X.
            self.raw("__mul16:");
            for l in [
                "MUL     R0,R2", "PUSHW   X", "MUL     R0,R3", "MOV     R0,XL", "MUL     R1,R2",
                "MOV     R1,XL", "ADD     R1,R0", "POPW    X", "MOV     R0,XL", "MOV     R2,XH",
                "ADD     R1,R2", "RET",
            ] {
                self.emit(l);
            }
            self.raw("");
        }
        if used.contains("div8") {
            // R0 = R0 / R1, R2 = R0 % R1. Clobbers R3.
            self.raw("__div8:");
            for l in [
                "CLR     R2", "MOV     R3,#8", ".l:", "ADD     R0,R0", "ADC     R2,R2", "BCS     .s",
                "CMP     R2,R1", "BLO     .n", ".s:", "SUB     R2,R1", "OR      R0,#1", ".n:",
                "SUB     R3,#1", "BNE     .l", "RET",
            ] {
                if l.ends_with(':') { self.raw(l) } else { self.emit(l) }
            }
            self.raw("");
        }
        if used.contains("div16") {
            // R1:R0 = R1:R0 / R3:R2, remainder in R3:R2. Clobbers Y.
            self.raw("__div16:");
            for l in [
                "ST      [__dv],R2", "ST      [__dv+1],R3", "CLR     R2", "CLR     R3", "LDW     Y,#16",
                ".l:", "ADD     R0,R0", "ADC     R1,R1", "ADC     R2,R2", "ADC     R3,R3", "BCS     .s",
                "PUSH    R0", "LD      R0,[__dv+1]", "CMP     R3,R0", "BNE     .c", "LD      R0,[__dv]",
                "CMP     R2,R0", ".c:", "POP     R0", "BLO     .n", ".s:", "PUSH    R0", "LD      R0,[__dv]",
                "SUB     R2,R0", "LD      R0,[__dv+1]", "SBC     R3,R0", "POP     R0", "OR      R0,#1",
                ".n:", "DECW    Y", "BNE     .l", "RET",
            ] {
                if l.ends_with(':') { self.raw(l) } else { self.emit(l) }
            }
            self.raw("");
        }
        if used.contains("idiv16") {
            // Signed: negate what is negative, divide, fix the signs.
            // The quotient takes the sign of the pair, the remainder
            // the dividend's, as C does.
            self.raw("__idiv16:");
            for l in [
                "ST      [__sg],R1", "PUSH    R1", "XOR     R1,R3", "ST      [__sg+1],R1", "POP     R1",
                "OR      R1,R1", "BPL     .a", "NOT     R0", "NOT     R1", "ADD     R0,#1", "ADC     R1,#0",
                ".a:", "OR      R3,R3", "BPL     .b", "NOT     R2", "NOT     R3", "ADD     R2,#1", "ADC     R3,#0",
                ".b:", "CALL    __div16", "PUSH    R0", "LD      R0,[__sg+1]", "BPL     .q", "POP     R0",
                "NOT     R0", "NOT     R1", "ADD     R0,#1", "ADC     R1,#0", "BRA     .r", ".q:", "POP     R0",
                ".r:", "PUSH    R0", "LD      R0,[__sg]", "BPL     .p", "POP     R0", "NOT     R2", "NOT     R3",
                "ADD     R2,#1", "ADC     R3,#0", "RET", ".p:", "POP     R0", "RET",
            ] {
                if l.ends_with(':') { self.raw(l) } else { self.emit(l) }
            }
            self.raw("");
        }
    }
}
