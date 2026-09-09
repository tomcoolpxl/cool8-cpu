// CoolAction! Parser
//
// Recursive descent over the token stream. The grammar has no
// statement terminator, as Action!'s did not, so two things stand in
// for one: a binary operator that begins a line ends the expression
// before it (`Token::bol`), and a returned value is always written
// `RETURN (expr)` -- without the parentheses `RETURN` followed by a
// statement starting with a name would read as returning that name.

use super::ast::*;
use super::lexer::Lexer;
use super::token::{Span, Token, TokenKind};
use std::collections::{HashMap, HashSet};

pub struct Parser<'a> {
    lexer: Lexer<'a>,
    current: Token,
    previous: Token,
    user_types: HashSet<String>,
    consts: HashMap<String, i64>,
}

fn err_at(span: &Span, msg: &str) -> String {
    format!("line {}, col {}: {}", span.line, span.col, msg)
}

impl<'a> Parser<'a> {
    pub fn new(src: &'a str) -> Result<Self, String> {
        let mut lexer = Lexer::new(src);
        let current = lexer.next_token()?;
        let previous = current.clone();
        Ok(Self {
            lexer,
            current,
            previous,
            user_types: HashSet::new(),
            consts: HashMap::new(),
        })
    }

    fn advance(&mut self) -> Result<(), String> {
        self.previous = self.current.clone();
        self.current = self.lexer.next_token()?;
        Ok(())
    }

    fn check(&self, kind: &TokenKind) -> bool {
        std::mem::discriminant(&self.current.kind) == std::mem::discriminant(kind)
    }

    fn match_token(&mut self, kind: &TokenKind) -> Result<bool, String> {
        if self.check(kind) {
            self.advance()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    /// Consume a binary operator only if it does not begin a line.
    fn match_op(&mut self, kind: &TokenKind) -> Result<bool, String> {
        if self.check(kind) && !self.current.bol {
            self.advance()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    fn expect(&mut self, kind: &TokenKind, what: &str) -> Result<Token, String> {
        if self.check(kind) {
            let tok = self.current.clone();
            self.advance()?;
            Ok(tok)
        } else {
            Err(err_at(
                &self.current.span,
                &format!("expected {}, found {:?}", what, self.current.kind),
            ))
        }
    }

    fn expect_ident(&mut self, what: &str) -> Result<String, String> {
        let tok = self.expect(&TokenKind::Ident(String::new()), what)?;
        match tok.kind {
            TokenKind::Ident(s) => Ok(s),
            _ => unreachable!(),
        }
    }

    // ------------------------------------------------------------ items

    pub fn parse_program(&mut self) -> Result<Program, String> {
        let mut items = Vec::new();
        while !self.check(&TokenKind::Eof) {
            items.extend(self.parse_item()?);
        }
        Ok(Program { items })
    }

    fn parse_item(&mut self) -> Result<Vec<Item>, String> {
        if self.check(&TokenKind::Proc) || self.check(&TokenKind::Func) {
            Ok(vec![Item::Routine(self.parse_routine()?)])
        } else if self.check(&TokenKind::Type) {
            Ok(vec![Item::Record(self.parse_record()?)])
        } else if self.match_token(&TokenKind::Module)? {
            Ok(vec![])
        } else if self.match_token(&TokenKind::Const)? {
            let name = self.expect_ident("constant name")?;
            self.expect(&TokenKind::Assign, "=")?;
            let e = self.parse_expr()?;
            let v = self
                .const_value(&e)
                .ok_or_else(|| err_at(&e.span, "CONST needs a constant expression"))?;
            self.consts.insert(name.clone(), v);
            Ok(vec![Item::Const(name, v)])
        } else if self.is_type_start() {
            Ok(self.parse_var_decls(true)?.into_iter().map(Item::GlobalVar).collect())
        } else {
            Err(err_at(
                &self.current.span,
                &format!("unexpected {:?} at top level", self.current.kind),
            ))
        }
    }

    fn is_type_start(&self) -> bool {
        match &self.current.kind {
            TokenKind::Byte | TokenKind::Char | TokenKind::Int | TokenKind::Card => true,
            TokenKind::Ident(s) => self.user_types.contains(s),
            _ => false,
        }
    }

    fn parse_type(&mut self) -> Result<TypeKind, String> {
        let span = self.current.span.clone();
        let base = match &self.current.kind {
            TokenKind::Byte => TypeKind::Byte,
            TokenKind::Char => TypeKind::Char,
            TokenKind::Int => TypeKind::Int,
            TokenKind::Card => TypeKind::Card,
            TokenKind::Ident(name) if self.user_types.contains(name) => TypeKind::UserDefined(name.clone()),
            _ => return Err(err_at(&span, "expected a type name")),
        };
        self.advance()?;

        if self.match_token(&TokenKind::Pointer)? {
            Ok(TypeKind::Pointer(Box::new(base)))
        } else if self.match_token(&TokenKind::Array)? {
            // BYTE ARRAY name(size) -- the size follows the name; 0 here
            // marks "unsized until then".
            Ok(TypeKind::Array(Box::new(base), 0))
        } else {
            Ok(base)
        }
    }

    fn const_number(&mut self) -> Result<i64, String> {
        let e = self.parse_unary()?;
        self.const_value(&e)
            .ok_or_else(|| err_at(&e.span, "expected a number"))
    }

    fn parse_var_decls(&mut self, global: bool) -> Result<Vec<VarDecl>, String> {
        let type_kind = self.parse_type()?;
        let mut decls = Vec::new();

        loop {
            let span = self.current.span.clone();
            let name = self.expect_ident("variable name")?;

            let mut var_type = type_kind.clone();
            if let TypeKind::Array(elem, _) = &var_type {
                if self.match_token(&TokenKind::LParen)? {
                    let e = self.parse_expr()?;
                    let n = self
                        .const_value(&e)
                        .ok_or_else(|| err_at(&e.span, "array size must be constant"))?;
                    if n <= 0 || n > 65535 {
                        return Err(err_at(&span, "array size out of range"));
                    }
                    self.expect(&TokenKind::RParen, "')' after array size")?;
                    var_type = TypeKind::Array(elem.clone(), n as usize);
                }
            }

            let mut hw_address = None;
            let mut init = Init::None;

            if self.match_token(&TokenKind::Assign)? {
                if self.match_token(&TokenKind::LBracket)? {
                    // =[1 2 3] initial values, space or comma separated
                    let mut vals = Vec::new();
                    while !self.check(&TokenKind::RBracket) {
                        if self.check(&TokenKind::Eof) {
                            return Err(err_at(&span, "unterminated initial value list"));
                        }
                        if let TokenKind::Str(s) = &self.current.kind {
                            vals.extend(s.bytes().map(|b| b as i64));
                            self.advance()?;
                        } else {
                            vals.push(self.const_number()?);
                        }
                        self.match_token(&TokenKind::Comma)?;
                    }
                    self.expect(&TokenKind::RBracket, "]")?;
                    if !matches!(var_type, TypeKind::Array(..)) && vals.len() != 1 {
                        return Err(err_at(&span, "a scalar takes one initial value"));
                    }
                    if let TypeKind::Array(elem, 0) = &var_type {
                        var_type = TypeKind::Array(elem.clone(), vals.len());
                    }
                    init = Init::Values(vals);
                } else if let TokenKind::Str(s) = &self.current.kind {
                    // ="text": a length byte then the characters
                    let bytes: Vec<u8> = s.bytes().collect();
                    self.advance()?;
                    if bytes.len() > 255 {
                        return Err(err_at(&span, "string longer than 255"));
                    }
                    match &var_type {
                        TypeKind::Array(elem, n) if elem.is_byte() => {
                            let need = bytes.len() + 1;
                            if *n == 0 {
                                var_type = TypeKind::Array(elem.clone(), need);
                            } else if *n < need {
                                return Err(err_at(&span, "string does not fit the array"));
                            }
                        }
                        _ => return Err(err_at(&span, "only a BYTE ARRAY takes a string")),
                    }
                    init = Init::Str(bytes);
                } else {
                    // =address: the variable lives there
                    if !global {
                        return Err(err_at(&span, "a local cannot be bound to an address; use =[value]"));
                    }
                    let e = self.parse_expr()?;
                    let a = self
                        .const_value(&e)
                        .ok_or_else(|| err_at(&e.span, "an address must be constant"))?;
                    if !(0..=0xFFFF).contains(&a) {
                        return Err(err_at(&span, "address out of range"));
                    }
                    hw_address = Some(a as u16);
                }
            }

            if let TypeKind::Array(_, 0) = &var_type {
                if hw_address.is_none() {
                    return Err(err_at(&span, "array needs a size: name(n)"));
                }
            }

            decls.push(VarDecl {
                name,
                type_kind: var_type,
                init,
                hw_address,
                span,
            });

            if !self.match_token(&TokenKind::Comma)? {
                break;
            }
        }
        Ok(decls)
    }

    fn parse_record(&mut self) -> Result<RecordDecl, String> {
        let span = self.current.span.clone();
        self.expect(&TokenKind::Type, "TYPE")?;
        let name = self.expect_ident("record name")?;
        self.expect(&TokenKind::Assign, "=")?;
        self.expect(&TokenKind::LBracket, "[")?;

        let mut fields = Vec::new();
        let mut offset = 0;
        while !self.check(&TokenKind::RBracket) {
            if self.check(&TokenKind::Eof) {
                return Err(err_at(&span, "unterminated TYPE"));
            }
            let field_type = self.parse_type()?;
            if matches!(field_type, TypeKind::Array(..) | TypeKind::UserDefined(_)) {
                return Err(err_at(&span, "a field is BYTE, CARD, INT or a POINTER"));
            }
            loop {
                let f_name = self.expect_ident("field name")?;
                fields.push(FieldDecl {
                    name: f_name,
                    type_kind: field_type.clone(),
                    offset,
                });
                offset += field_type.size_bytes();
                if !self.match_token(&TokenKind::Comma)? {
                    break;
                }
            }
        }
        self.expect(&TokenKind::RBracket, "]")?;
        self.user_types.insert(name.clone());
        Ok(RecordDecl {
            name,
            fields,
            size_bytes: offset,
            span,
        })
    }

    fn parse_routine(&mut self) -> Result<RoutineDecl, String> {
        let span = self.current.span.clone();
        let is_func = self.match_token(&TokenKind::Func)?;
        let mut return_type = None;
        if is_func {
            return_type = Some(self.parse_type()?);
        } else {
            self.expect(&TokenKind::Proc, "PROC")?;
        }
        let name = self.expect_ident("routine name")?;

        let mut params = Vec::new();
        if self.match_token(&TokenKind::LParen)? {
            if !self.check(&TokenKind::RParen) {
                loop {
                    let p_type = self.parse_type()?;
                    if matches!(p_type, TypeKind::Array(..)) {
                        return Err(err_at(&span, "pass an array as a POINTER"));
                    }
                    let p_name = self.expect_ident("parameter name")?;
                    params.push(ParamDecl {
                        name: p_name,
                        type_kind: p_type,
                    });
                    if !self.match_token(&TokenKind::Comma)? {
                        break;
                    }
                }
            }
            self.expect(&TokenKind::RParen, ")")?;
        }

        // Declarations come first, then statements, and the body runs
        // to the next PROC, FUNC or MODULE -- or to a declaration,
        // which cannot be a statement once the locals are done, so a
        // global after a routine needs no MODULE before it. That is
        // what lets a library and a program compile as one text.
        let mut locals = Vec::new();
        while self.is_type_start() {
            locals.extend(self.parse_var_decls(false)?);
        }
        let mut body = Vec::new();
        while !self.check(&TokenKind::Proc)
            && !self.check(&TokenKind::Func)
            && !self.check(&TokenKind::Module)
            && !self.check(&TokenKind::Type)
            && !self.check(&TokenKind::Const)
            && !self.is_type_start()
            && !self.check(&TokenKind::Eof)
        {
            body.push(self.parse_stmt()?);
        }

        Ok(RoutineDecl {
            name,
            is_func,
            return_type,
            params,
            locals,
            body,
            span,
        })
    }

    // ------------------------------------------------------- statements

    fn parse_block(&mut self, enders: &[TokenKind]) -> Result<Vec<Stmt>, String> {
        let mut body = Vec::new();
        loop {
            if self.check(&TokenKind::Eof) {
                return Err(err_at(&self.current.span, "unexpected end of file inside a block"));
            }
            if enders.iter().any(|k| self.check(k)) {
                return Ok(body);
            }
            body.push(self.parse_stmt()?);
        }
    }

    fn parse_stmt(&mut self) -> Result<Stmt, String> {
        let span = self.current.span.clone();

        if self.match_token(&TokenKind::If)? {
            self.parse_if(span)
        } else if self.match_token(&TokenKind::While)? {
            let cond = self.parse_expr()?;
            self.expect(&TokenKind::Do, "DO")?;
            let body = self.parse_block(&[TokenKind::Od])?;
            self.expect(&TokenKind::Od, "OD")?;
            Ok(Stmt { kind: StmtKind::While { cond, body }, span })
        } else if self.match_token(&TokenKind::Do)? {
            let body = self.parse_block(&[TokenKind::Od, TokenKind::Until])?;
            let until_cond = if self.match_token(&TokenKind::Until)? {
                Some(self.parse_expr()?)
            } else {
                None
            };
            self.expect(&TokenKind::Od, "OD")?;
            Ok(Stmt { kind: StmtKind::DoLoop { body, until_cond }, span })
        } else if self.match_token(&TokenKind::For)? {
            self.parse_for(span)
        } else if self.match_token(&TokenKind::Return)? {
            let val = if self.check(&TokenKind::LParen) && !self.current.bol {
                self.advance()?;
                let e = self.parse_expr()?;
                self.expect(&TokenKind::RParen, ")")?;
                Some(e)
            } else {
                None
            };
            Ok(Stmt { kind: StmtKind::Return(val), span })
        } else if self.match_token(&TokenKind::Exit)? {
            Ok(Stmt { kind: StmtKind::Exit, span })
        } else if self.match_token(&TokenKind::Break)? {
            Ok(Stmt { kind: StmtKind::Break, span })
        } else if self.match_token(&TokenKind::Assert)? {
            let cond = self.parse_expr()?;
            let mut msg = None;
            if self.match_token(&TokenKind::Comma)? {
                let tok = self.expect(&TokenKind::Str(String::new()), "assertion message")?;
                if let TokenKind::Str(s) = tok.kind {
                    msg = Some(s.into_bytes());
                }
            }
            Ok(Stmt { kind: StmtKind::Assert { cond, msg }, span })
        } else if self.check(&TokenKind::Asm) {
            // The lexer stands just past ASM while ASM is the current
            // token; take the raw text from there, then step onto
            // whatever follows ENDASM.
            let (raw_asm, asm_span) = self.lexer.read_until_endasm()?;
            self.advance()?;
            Ok(Stmt { kind: StmtKind::Asm(raw_asm), span: asm_span })
        } else {
            let expr = self.parse_expr()?;
            if let Some(op) = self.check_assign_op() {
                self.advance()?;
                let value = self.parse_expr()?;
                match &expr.kind {
                    ExprKind::Variable(_) | ExprKind::Call { .. } | ExprKind::Deref(_) | ExprKind::FieldAccess { .. } => {}
                    _ => return Err(err_at(&span, "cannot assign to that")),
                }
                Ok(Stmt { kind: StmtKind::Assign { target: expr, op, value }, span })
            } else if let ExprKind::Call { name, args } = expr.kind {
                Ok(Stmt { kind: StmtKind::Call { name, args }, span })
            } else {
                Err(err_at(&span, "expected an assignment or a call"))
            }
        }
    }

    fn check_assign_op(&self) -> Option<AssignOp> {
        match self.current.kind {
            TokenKind::Assign => Some(AssignOp::Assign),
            TokenKind::PlusAssign => Some(AssignOp::PlusAssign),
            TokenKind::MinusAssign => Some(AssignOp::MinusAssign),
            TokenKind::MulAssign => Some(AssignOp::MulAssign),
            TokenKind::DivAssign => Some(AssignOp::DivAssign),
            TokenKind::ModAssign => Some(AssignOp::ModAssign),
            TokenKind::AndAssign => Some(AssignOp::AndAssign),
            TokenKind::OrAssign => Some(AssignOp::OrAssign),
            TokenKind::XorAssign => Some(AssignOp::XorAssign),
            TokenKind::ShlAssign => Some(AssignOp::ShlAssign),
            TokenKind::ShrAssign => Some(AssignOp::ShrAssign),
            _ => None,
        }
    }

    fn parse_if(&mut self, span: Span) -> Result<Stmt, String> {
        let enders = [TokenKind::ElseIf, TokenKind::Else, TokenKind::Fi];
        let cond = self.parse_expr()?;
        self.expect(&TokenKind::Then, "THEN")?;
        let then_branch = self.parse_block(&enders)?;

        let mut else_ifs = Vec::new();
        while self.match_token(&TokenKind::ElseIf)? {
            let c = self.parse_expr()?;
            self.expect(&TokenKind::Then, "THEN")?;
            let b = self.parse_block(&enders)?;
            else_ifs.push((c, b));
        }
        let else_branch = if self.match_token(&TokenKind::Else)? {
            Some(self.parse_block(&[TokenKind::Fi])?)
        } else {
            None
        };
        self.expect(&TokenKind::Fi, "FI")?;
        Ok(Stmt {
            kind: StmtKind::If { cond, then_branch, else_ifs, else_branch },
            span,
        })
    }

    fn parse_for(&mut self, span: Span) -> Result<Stmt, String> {
        let var = self.expect_ident("loop variable")?;
        self.expect(&TokenKind::Assign, "=")?;
        let start = self.parse_expr()?;
        self.expect(&TokenKind::To, "TO")?;
        let to = self.parse_expr()?;
        let step = if self.match_token(&TokenKind::Step)? {
            Some(self.parse_expr()?)
        } else {
            None
        };
        self.expect(&TokenKind::Do, "DO")?;
        let body = self.parse_block(&[TokenKind::Od])?;
        self.expect(&TokenKind::Od, "OD")?;
        Ok(Stmt {
            kind: StmtKind::For { var, start, to, step, body },
            span,
        })
    }

    // ------------------------------------------------------ expressions
    //
    // Loosest first: OR, AND, NOT, comparisons, |, ^, &, shifts, + -,
    // * / %, unary. Comparisons bind looser than the bitwise operators
    // -- Python's order, not C's -- so `status & 1 == 0` asks about the
    // masked bit, which is the question a hardware register invites.

    pub fn parse_expr(&mut self) -> Result<Expr, String> {
        self.parse_logical_or()
    }

    fn binary(&mut self, op: BinaryOp, left: Expr, right: Expr) -> Expr {
        let span = self.previous.span.clone();
        Expr {
            kind: ExprKind::Binary { op, left: Box::new(left), right: Box::new(right) },
            span,
        }
    }

    fn parse_logical_or(&mut self) -> Result<Expr, String> {
        let mut expr = self.parse_logical_and()?;
        while self.match_op(&TokenKind::LogicalOr)? {
            let right = self.parse_logical_and()?;
            expr = self.binary(BinaryOp::LogicalOr, expr, right);
        }
        Ok(expr)
    }

    fn parse_logical_and(&mut self) -> Result<Expr, String> {
        let mut expr = self.parse_logical_not()?;
        while self.match_op(&TokenKind::LogicalAnd)? {
            let right = self.parse_logical_not()?;
            expr = self.binary(BinaryOp::LogicalAnd, expr, right);
        }
        Ok(expr)
    }

    fn parse_logical_not(&mut self) -> Result<Expr, String> {
        let span = self.current.span.clone();
        if self.match_token(&TokenKind::LogicalNot)? {
            let e = self.parse_logical_not()?;
            return Ok(Expr {
                kind: ExprKind::Unary { op: UnaryOp::LogicalNot, expr: Box::new(e) },
                span,
            });
        }
        self.parse_comparison()
    }

    fn parse_comparison(&mut self) -> Result<Expr, String> {
        let mut expr = self.parse_bitwise_or()?;
        loop {
            let op = if self.match_op(&TokenKind::Equal)? {
                BinaryOp::Eq
            } else if self.match_op(&TokenKind::NotEqual)? {
                BinaryOp::Ne
            } else if self.match_op(&TokenKind::Less)? {
                BinaryOp::Lt
            } else if self.match_op(&TokenKind::LessEqual)? {
                BinaryOp::Le
            } else if self.match_op(&TokenKind::Greater)? {
                BinaryOp::Gt
            } else if self.match_op(&TokenKind::GreaterEqual)? {
                BinaryOp::Ge
            } else {
                break;
            };
            let right = self.parse_bitwise_or()?;
            expr = self.binary(op, expr, right);
        }
        Ok(expr)
    }

    fn parse_bitwise_or(&mut self) -> Result<Expr, String> {
        let mut expr = self.parse_bitwise_xor()?;
        while self.match_op(&TokenKind::Pipe)? {
            let right = self.parse_bitwise_xor()?;
            expr = self.binary(BinaryOp::BitOr, expr, right);
        }
        Ok(expr)
    }

    fn parse_bitwise_xor(&mut self) -> Result<Expr, String> {
        let mut expr = self.parse_bitwise_and()?;
        while self.match_op(&TokenKind::BitXor)? {
            let right = self.parse_bitwise_and()?;
            expr = self.binary(BinaryOp::BitXor, expr, right);
        }
        Ok(expr)
    }

    fn parse_bitwise_and(&mut self) -> Result<Expr, String> {
        let mut expr = self.parse_shift()?;
        while self.match_op(&TokenKind::BitAnd)? {
            let right = self.parse_shift()?;
            expr = self.binary(BinaryOp::BitAnd, expr, right);
        }
        Ok(expr)
    }

    fn parse_shift(&mut self) -> Result<Expr, String> {
        let mut expr = self.parse_additive()?;
        loop {
            let op = if self.match_op(&TokenKind::Shl)? {
                BinaryOp::Shl
            } else if self.match_op(&TokenKind::Shr)? {
                BinaryOp::Shr
            } else {
                break;
            };
            let right = self.parse_additive()?;
            expr = self.binary(op, expr, right);
        }
        Ok(expr)
    }

    fn parse_additive(&mut self) -> Result<Expr, String> {
        let mut expr = self.parse_multiplicative()?;
        loop {
            let op = if self.match_op(&TokenKind::Plus)? {
                BinaryOp::Add
            } else if self.match_op(&TokenKind::Minus)? {
                BinaryOp::Sub
            } else {
                break;
            };
            let right = self.parse_multiplicative()?;
            expr = self.binary(op, expr, right);
        }
        Ok(expr)
    }

    fn parse_multiplicative(&mut self) -> Result<Expr, String> {
        let mut expr = self.parse_unary()?;
        loop {
            let op = if self.match_op(&TokenKind::Star)? {
                BinaryOp::Mul
            } else if self.match_op(&TokenKind::Slash)? {
                BinaryOp::Div
            } else if self.match_op(&TokenKind::Percent)? {
                BinaryOp::Mod
            } else {
                break;
            };
            let right = self.parse_unary()?;
            expr = self.binary(op, expr, right);
        }
        Ok(expr)
    }

    fn parse_unary(&mut self) -> Result<Expr, String> {
        let span = self.current.span.clone();
        if self.match_token(&TokenKind::Minus)? {
            let expr = self.parse_unary()?;
            Ok(Expr { kind: ExprKind::Unary { op: UnaryOp::Neg, expr: Box::new(expr) }, span })
        } else if self.match_token(&TokenKind::Tilde)? {
            let expr = self.parse_unary()?;
            Ok(Expr { kind: ExprKind::Unary { op: UnaryOp::BitNot, expr: Box::new(expr) }, span })
        } else if self.match_token(&TokenKind::Star)? {
            let expr = self.parse_unary()?;
            Ok(Expr { kind: ExprKind::Deref(Box::new(expr)), span })
        } else if self.match_token(&TokenKind::BitAnd)? {
            let name = self.expect_ident("a variable name after &")?;
            Ok(Expr { kind: ExprKind::AddrOf(name), span })
        } else {
            self.parse_postfix()
        }
    }

    fn parse_postfix(&mut self) -> Result<Expr, String> {
        let mut expr = self.parse_primary()?;
        while self.match_op(&TokenKind::Period)? {
            let span = self.previous.span.clone();
            let field = self.expect_ident("field name")?;
            expr = Expr { kind: ExprKind::FieldAccess { base: Box::new(expr), field }, span };
        }
        Ok(expr)
    }

    fn parse_primary(&mut self) -> Result<Expr, String> {
        let span = self.current.span.clone();
        match self.current.kind.clone() {
            TokenKind::Number(val) => {
                self.advance()?;
                Ok(Expr { kind: ExprKind::Number(val), span })
            }
            TokenKind::Str(s) => {
                self.advance()?;
                Ok(Expr { kind: ExprKind::Str(s.into_bytes()), span })
            }
            TokenKind::CharLit(b) => {
                self.advance()?;
                Ok(Expr { kind: ExprKind::CharLit(b), span })
            }
            TokenKind::Ident(name) => {
                self.advance()?;
                if let Some(v) = self.consts.get(&name) {
                    return Ok(Expr { kind: ExprKind::Number(*v), span });
                }
                // name(args): a call or an array element -- the parser
                // cannot tell them apart, and does not need to.
                if self.check(&TokenKind::LParen) && !self.current.bol {
                    self.advance()?;
                    let mut args = Vec::new();
                    if !self.check(&TokenKind::RParen) {
                        loop {
                            args.push(self.parse_expr()?);
                            if !self.match_token(&TokenKind::Comma)? {
                                break;
                            }
                        }
                    }
                    self.expect(&TokenKind::RParen, ")")?;
                    Ok(Expr { kind: ExprKind::Call { name, args }, span })
                } else {
                    Ok(Expr { kind: ExprKind::Variable(name), span })
                }
            }
            TokenKind::LParen => {
                self.advance()?;
                let expr = self.parse_expr()?;
                self.expect(&TokenKind::RParen, ")")?;
                Ok(expr)
            }
            other => Err(err_at(&span, &format!("unexpected {:?} in an expression", other))),
        }
    }

    /// Fold an expression of literals to a number, or None.
    pub fn const_value(&self, e: &Expr) -> Option<i64> {
        Some(match &e.kind {
            ExprKind::Number(v) => *v,
            ExprKind::CharLit(c) => *c as i64,
            ExprKind::Unary { op: UnaryOp::Neg, expr } => -self.const_value(expr)?,
            ExprKind::Unary { op: UnaryOp::BitNot, expr } => !self.const_value(expr)?,
            ExprKind::Binary { op, left, right } => {
                let a = self.const_value(left)?;
                let b = self.const_value(right)?;
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
}
