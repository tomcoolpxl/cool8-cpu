// CoolAction! Token definitions

#[derive(Debug, Clone, PartialEq)]
pub struct Span {
    pub line: usize,
    pub col: usize,
}

#[derive(Debug, Clone, PartialEq)]
pub enum TokenKind {
    // Keywords - Declarations
    Byte,
    Char,
    Int,
    Card,
    Pointer,
    Array,
    Type,
    Proc,
    Func,
    Return,
    Asm,
    EndAsm,
    Module,
    Const,

    // Keywords - Control Flow
    If,
    Then,
    ElseIf,
    Else,
    Fi,
    Do,
    Od,
    While,
    Until,
    For,
    To,
    Step,
    Exit,

    // Debugging built-in keywords
    Assert,
    Break,

    // Literals
    Number(i64),
    Str(String),
    /// `#"text"`: a string kept out of the image, which is its number
    DiscStr(String),
    CharLit(u8),
    Ident(String),

    // Delimiters & Punctuation
    LParen,   // (
    RParen,   // )
    LBracket, // [
    RBracket, // ]
    Comma,    // ,
    Colon,    // :
    Semicolon,// ; (or comment end)
    Period,   // .

    // Operators
    Assign,       // =
    PlusAssign,   // +=
    MinusAssign,  // -=
    MulAssign,    // *=
    DivAssign,    // /=
    ModAssign,    // %=
    AndAssign,    // &=
    OrAssign,     // |=
    XorAssign,    // ^=
    ShlAssign,    // <<=
    ShrAssign,    // >>=

    Equal,        // ==
    NotEqual,     // != or <>
    Less,         // <
    LessEqual,    // <=
    Greater,      // >
    GreaterEqual, // >=

    Plus,         // +
    Minus,        // -
    Star,         // *
    Slash,        // /
    Percent,      // % (mod)

    BitAnd,       // & or AND
    Pipe,         // | or OR (bitwise OR)
    Tilde,        // ~ (bitwise NOT)
    BitXor,       // XOR keyword or ^
    Shl,          // << or LSH
    Shr,          // >> or RSH

    LogicalAnd,   // && or AND
    LogicalOr,    // || or OR
    LogicalNot,   // NOT

    // Special
    Eof,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Token {
    pub kind: TokenKind,
    pub span: Span,
    /// First token on its line. A binary operator that starts a line
    /// ends the expression before it, which is what keeps `x = y` on
    /// one line and `*p = 1` on the next from parsing as `x = y * p`.
    pub bol: bool,
}
