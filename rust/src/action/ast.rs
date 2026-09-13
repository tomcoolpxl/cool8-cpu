// CoolAction! Abstract Syntax Tree (AST)

use super::token::Span;

#[derive(Debug, Clone, PartialEq)]
pub enum TypeKind {
    Byte,
    Char,
    Int,
    Card,
    Pointer(Box<TypeKind>),
    Array(Box<TypeKind>, usize),
    UserDefined(String),
}

impl TypeKind {
    /// Storage size of a variable of this type. A record's is resolved
    /// by the code generator, which has the declarations.
    pub fn size_bytes(&self) -> usize {
        match self {
            TypeKind::Byte | TypeKind::Char => 1,
            TypeKind::Int | TypeKind::Card | TypeKind::Pointer(_) => 2,
            TypeKind::Array(elem, len) => elem.size_bytes() * len,
            TypeKind::UserDefined(_) => 0,
        }
    }

    /// Width of the type as a value in registers: one byte, or two.
    /// An array or a record is its address, so two.
    pub fn width(&self) -> usize {
        match self {
            TypeKind::Byte | TypeKind::Char => 1,
            _ => 2,
        }
    }

    pub fn is_byte(&self) -> bool {
        matches!(self, TypeKind::Byte | TypeKind::Char)
    }

    pub fn is_signed(&self) -> bool {
        matches!(self, TypeKind::Int)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum UnaryOp {
    Neg,        // -
    BitNot,     // ~
    LogicalNot, // NOT / !
}

#[derive(Debug, Clone, PartialEq)]
pub enum BinaryOp {
    Add, Sub, Mul, Div, Mod,
    BitAnd, BitOr, BitXor,
    Shl, Shr,
    Eq, Ne, Lt, Le, Gt, Ge,
    LogicalAnd, LogicalOr,
}

#[derive(Debug, Clone, PartialEq)]
pub enum AssignOp {
    Assign,      // =
    PlusAssign,  // +=
    MinusAssign, // -=
    MulAssign,   // *=
    DivAssign,   // /=
    ModAssign,   // %=
    AndAssign,   // &=
    OrAssign,    // |=
    XorAssign,   // ^=
    ShlAssign,   // <<=
    ShrAssign,   // >>=
}

impl AssignOp {
    pub fn binary(&self) -> Option<BinaryOp> {
        Some(match self {
            AssignOp::Assign => return None,
            AssignOp::PlusAssign => BinaryOp::Add,
            AssignOp::MinusAssign => BinaryOp::Sub,
            AssignOp::MulAssign => BinaryOp::Mul,
            AssignOp::DivAssign => BinaryOp::Div,
            AssignOp::ModAssign => BinaryOp::Mod,
            AssignOp::AndAssign => BinaryOp::BitAnd,
            AssignOp::OrAssign => BinaryOp::BitOr,
            AssignOp::XorAssign => BinaryOp::BitXor,
            AssignOp::ShlAssign => BinaryOp::Shl,
            AssignOp::ShrAssign => BinaryOp::Shr,
        })
    }
}

#[derive(Debug, Clone)]
pub struct Expr {
    pub kind: ExprKind,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub enum ExprKind {
    Number(i64),
    Str(Vec<u8>),
    CharLit(u8),
    Variable(String),
    FieldAccess {
        base: Box<Expr>,
        field: String,
    },
    Deref(Box<Expr>),
    AddrOf(String),
    /// `name(args)`: a routine call, or an array element when `name`
    /// is an array -- the parser cannot tell, the code generator can.
    Call {
        name: String,
        args: Vec<Expr>,
    },
    Unary {
        op: UnaryOp,
        expr: Box<Expr>,
    },
    Binary {
        op: BinaryOp,
        left: Box<Expr>,
        right: Box<Expr>,
    },
}

#[derive(Debug, Clone)]
pub struct Stmt {
    pub kind: StmtKind,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub enum StmtKind {
    Assign {
        target: Expr,
        op: AssignOp,
        value: Expr,
    },
    Call {
        name: String,
        args: Vec<Expr>,
    },
    If {
        cond: Expr,
        then_branch: Vec<Stmt>,
        else_ifs: Vec<(Expr, Vec<Stmt>)>,
        else_branch: Option<Vec<Stmt>>,
    },
    While {
        cond: Expr,
        body: Vec<Stmt>,
    },
    DoLoop {
        body: Vec<Stmt>,
        until_cond: Option<Expr>,
    },
    For {
        var: String,
        start: Expr,
        to: Expr,
        step: Option<Expr>,
        body: Vec<Stmt>,
    },
    Return(Option<Expr>),
    Exit,
    Asm(String),
    Assert {
        cond: Expr,
        msg: Option<Vec<u8>>,
    },
    Break,
}

/// What a declaration starts its storage with.
#[derive(Debug, Clone, PartialEq)]
pub enum Init {
    None,
    /// `=[1 2 3]` -- one value per element, or one for a scalar.
    Values(Vec<i64>),
    /// `="text"` -- a length byte and the characters.
    Str(Vec<u8>),
}

#[derive(Debug, Clone)]
pub struct VarDecl {
    pub name: String,
    pub type_kind: TypeKind,
    pub init: Init,
    /// `BYTE vid_mode = $FF10`: the variable *is* that address.
    pub hw_address: Option<u16>,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub struct FieldDecl {
    pub name: String,
    pub type_kind: TypeKind,
    pub offset: usize,
}

#[derive(Debug, Clone)]
pub struct RecordDecl {
    pub name: String,
    pub fields: Vec<FieldDecl>,
    pub size_bytes: usize,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub struct ParamDecl {
    pub name: String,
    pub type_kind: TypeKind,
}

#[derive(Debug, Clone)]
pub struct RoutineDecl {
    pub name: String,
    pub is_func: bool,
    pub return_type: Option<TypeKind>,
    pub params: Vec<ParamDecl>,
    pub locals: Vec<VarDecl>,
    pub body: Vec<Stmt>,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub enum Item {
    GlobalVar(VarDecl),
    Const(String, i64),
    Record(RecordDecl),
    Routine(RoutineDecl),
}

#[derive(Debug, Clone)]
pub struct Program {
    pub items: Vec<Item>,
    /// the `#"text"` strings in number order, for `strings_file`
    pub disc_strings: Vec<Vec<u8>>,
}
