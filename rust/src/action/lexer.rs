// CoolAction! Lexer / Tokenizer

use super::token::{Span, Token, TokenKind};

pub struct Lexer<'a> {
    chars: Vec<char>,
    pos: usize,
    line: usize,
    col: usize,
    bol: bool,
    _src: std::marker::PhantomData<&'a str>,
}

impl<'a> Lexer<'a> {
    pub fn new(src: &'a str) -> Self {
        Self {
            chars: src.chars().collect(),
            pos: 0,
            line: 1,
            col: 1,
            bol: true,
            _src: std::marker::PhantomData,
        }
    }

    fn peek(&self) -> Option<char> {
        if self.pos < self.chars.len() {
            Some(self.chars[self.pos])
        } else {
            None
        }
    }

    fn peek_next(&self) -> Option<char> {
        if self.pos + 1 < self.chars.len() {
            Some(self.chars[self.pos + 1])
        } else {
            None
        }
    }

    fn advance(&mut self) -> Option<char> {
        if self.pos < self.chars.len() {
            let ch = self.chars[self.pos];
            self.pos += 1;
            if ch == '\n' {
                self.line += 1;
                self.col = 1;
            } else {
                self.col += 1;
            }
            Some(ch)
        } else {
            None
        }
    }

    fn current_span(&self) -> Span {
        Span {
            line: self.line,
            col: self.col,
        }
    }

    pub fn next_token(&mut self) -> Result<Token, String> {
        let mut tok = self.next_token_inner()?;
        tok.bol = self.bol;
        Ok(tok)
    }

    fn next_token_inner(&mut self) -> Result<Token, String> {
        self.bol = self.pos == 0;
        loop {
            // Skip whitespace
            while let Some(ch) = self.peek() {
                if ch.is_whitespace() {
                    if ch == '\n' {
                        self.bol = true;
                    }
                    self.advance();
                } else {
                    break;
                }
            }

            let span = self.current_span();
            let ch = match self.peek() {
                Some(c) => c,
                None => return Ok(Token { kind: TokenKind::Eof, span, bol: true }),
            };

            // Comments start with ';' or '//'
            if ch == ';' || (ch == '/' && self.peek_next() == Some('/')) {
                // Skip to end of line
                while let Some(c) = self.advance() {
                    if c == '\n' {
                        self.bol = true;
                        break;
                    }
                }
                continue;
            }

            // Identifiers / Keywords
            if ch.is_alphabetic() || ch == '_' {
                return Ok(self.lex_ident_or_keyword(span));
            }

            // Numbers: $hex, 0x hex, 0b binary, or decimal. `%` is modulo.
            if ch == '$' || ch.is_ascii_digit() {
                return self.lex_number(span);
            }

            // String literals
            if ch == '"' {
                return self.lex_string(span);
            }
            // `#"text"`: its number, and the text for the strings file
            if ch == '#' && self.peek_next() == Some('"') {
                self.advance();
                let tok = self.lex_string(span)?;
                if let TokenKind::Str(s) = tok.kind {
                    return Ok(Token { kind: TokenKind::DiscStr(s), span: tok.span, bol: tok.bol });
                }
                return Ok(tok);
            }

            // Char literals
            if ch == '\'' {
                return self.lex_char(span);
            }

            // Operators and punctuation
            self.advance();
            let kind = match ch {
                '(' => TokenKind::LParen,
                ')' => TokenKind::RParen,
                '[' => TokenKind::LBracket,
                ']' => TokenKind::RBracket,
                ',' => TokenKind::Comma,
                ':' => TokenKind::Colon,
                '.' => TokenKind::Period,
                '^' => {
                    if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::XorAssign
                    } else {
                        TokenKind::BitXor
                    }
                }
                '~' => TokenKind::Tilde,
                '+' => {
                    if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::PlusAssign
                    } else {
                        TokenKind::Plus
                    }
                }
                '-' => {
                    if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::MinusAssign
                    } else {
                        TokenKind::Minus
                    }
                }
                '*' => {
                    if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::MulAssign
                    } else {
                        TokenKind::Star
                    }
                }
                '/' => {
                    if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::DivAssign
                    } else {
                        TokenKind::Slash
                    }
                }
                '%' => {
                    if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::ModAssign
                    } else {
                        TokenKind::Percent
                    }
                }
                '=' => {
                    if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::Equal
                    } else {
                        TokenKind::Assign
                    }
                }
                '!' => {
                    if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::NotEqual
                    } else {
                        TokenKind::LogicalNot
                    }
                }
                '<' => {
                    if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::LessEqual
                    } else if self.peek() == Some('>') {
                        self.advance();
                        TokenKind::NotEqual
                    } else if self.peek() == Some('<') {
                        self.advance();
                        if self.peek() == Some('=') {
                            self.advance();
                            TokenKind::ShlAssign
                        } else {
                            TokenKind::Shl
                        }
                    } else {
                        TokenKind::Less
                    }
                }
                '>' => {
                    if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::GreaterEqual
                    } else if self.peek() == Some('>') {
                        self.advance();
                        if self.peek() == Some('=') {
                            self.advance();
                            TokenKind::ShrAssign
                        } else {
                            TokenKind::Shr
                        }
                    } else {
                        TokenKind::Greater
                    }
                }
                '&' => {
                    if self.peek() == Some('&') {
                        self.advance();
                        TokenKind::LogicalAnd
                    } else if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::AndAssign
                    } else {
                        TokenKind::BitAnd
                    }
                }
                '|' => {
                    if self.peek() == Some('|') {
                        self.advance();
                        TokenKind::LogicalOr
                    } else if self.peek() == Some('=') {
                        self.advance();
                        TokenKind::OrAssign
                    } else {
                        TokenKind::Pipe
                    }
                }
                _ => return Err(format!("Unexpected character '{}' at line {}, col {}", ch, span.line, span.col)),
            };

            return Ok(Token { kind, span, bol: false });
        }
    }

    fn lex_ident_or_keyword(&mut self, span: Span) -> Token {
        let mut s = String::new();
        while let Some(ch) = self.peek() {
            if ch.is_alphanumeric() || ch == '_' {
                s.push(ch);
                self.advance();
            } else {
                break;
            }
        }

        let upper = s.to_uppercase();
        let kind = match upper.as_str() {
            "BYTE" => TokenKind::Byte,
            "CHAR" => TokenKind::Char,
            "INT" => TokenKind::Int,
            "CARD" => TokenKind::Card,
            "POINTER" => TokenKind::Pointer,
            "ARRAY" => TokenKind::Array,
            "TYPE" => TokenKind::Type,
            "PROC" => TokenKind::Proc,
            "FUNC" => TokenKind::Func,
            "RETURN" => TokenKind::Return,
            "ASM" => TokenKind::Asm,
            "ENDASM" => TokenKind::EndAsm,

            "IF" => TokenKind::If,
            "THEN" => TokenKind::Then,
            "ELSEIF" => TokenKind::ElseIf,
            "ELSE" => TokenKind::Else,
            "FI" => TokenKind::Fi,
            "DO" => TokenKind::Do,
            "OD" => TokenKind::Od,
            "WHILE" => TokenKind::While,
            "UNTIL" => TokenKind::Until,
            "FOR" => TokenKind::For,
            "TO" => TokenKind::To,
            "STEP" => TokenKind::Step,
            "EXIT" => TokenKind::Exit,

            "MODULE" => TokenKind::Module,
            "CONST" => TokenKind::Const,

            "ASSERT" => TokenKind::Assert,
            "BREAK" => TokenKind::Break,

            "AND" => TokenKind::LogicalAnd,
            "OR" => TokenKind::LogicalOr,
            "XOR" => TokenKind::BitXor,
            "NOT" => TokenKind::LogicalNot,
            "LSH" => TokenKind::Shl,
            "RSH" => TokenKind::Shr,

            _ => TokenKind::Ident(s),
        };

        Token { kind, span, bol: false }
    }

    fn lex_number(&mut self, span: Span) -> Result<Token, String> {
        let first = self.advance().unwrap();
        let mut num_str = String::new();
        let radix = if first == '$' {
            16
        } else if first == '0' && matches!(self.peek(), Some('x') | Some('X')) {
            self.advance();
            16
        } else if first == '0' && matches!(self.peek(), Some('b') | Some('B')) {
            self.advance();
            2
        } else {
            num_str.push(first);
            10
        };
        while let Some(ch) = self.peek() {
            let ok = match radix {
                16 => ch.is_ascii_hexdigit(),
                2 => ch == '0' || ch == '1',
                _ => ch.is_ascii_digit(),
            };
            if ok {
                num_str.push(ch);
                self.advance();
            } else if ch == '_' {
                self.advance();
            } else {
                break;
            }
        }
        if num_str.is_empty() {
            return Err(format!("Invalid numeric literal at line {}, col {}", span.line, span.col));
        }
        let val = i64::from_str_radix(&num_str, radix)
            .map_err(|e| format!("Bad number '{num_str}' at line {}, col {}: {}", span.line, span.col, e))?;
        Ok(Token {
            kind: TokenKind::Number(val),
            span,
            bol: false,
        })
    }

    fn lex_string(&mut self, span: Span) -> Result<Token, String> {
        self.advance(); // consume opening quote '"'
        let mut s = String::new();
        while let Some(ch) = self.advance() {
            if ch == '"' {
                return Ok(Token {
                    kind: TokenKind::Str(s),
                    span,
                    bol: false,
                });
            } else if ch == '\\' {
                let esc = match self.advance() {
                    Some('n') => '\n',
                    Some('r') => '\r',
                    Some('t') => '\t',
                    Some('\\') => '\\',
                    Some('"') => '"',
                    Some('0') => '\0',
                    Some(c) => c,
                    None => return Err(format!("Unterminated escape at line {}, col {}", span.line, span.col)),
                };
                s.push(esc);
            } else {
                s.push(ch);
            }
        }
        Err(format!("Unterminated string literal at line {}, col {}", span.line, span.col))
    }

    fn lex_char(&mut self, span: Span) -> Result<Token, String> {
        self.advance(); // consume opening quote '\''
        let ch = match self.advance() {
            Some('\\') => match self.advance() {
                Some('n') => b'\n',
                Some('r') => b'\r',
                Some('t') => b'\t',
                Some('\\') => b'\\',
                Some('\'') => b'\'',
                Some('0') => 0,
                Some(c) => c as u8,
                None => return Err(format!("Unterminated char escape at line {}, col {}", span.line, span.col)),
            },
            Some('\'') => return Err(format!("Empty char literal at line {}, col {}", span.line, span.col)),
            Some(c) => c as u8,
            None => return Err(format!("Unterminated char literal at line {}, col {}", span.line, span.col)),
        };

        if self.advance() != Some('\'') {
            return Err(format!("Unclosed char literal at line {}, col {}", span.line, span.col));
        }

        Ok(Token {
            kind: TokenKind::CharLit(ch),
            span,
            bol: false,
        })
    }

    pub fn tokenize(&mut self) -> Result<Vec<Token>, String> {
        let mut tokens = Vec::new();
        loop {
            let tok = self.next_token()?;
            let is_eof = tok.kind == TokenKind::Eof;
            tokens.push(tok);
            if is_eof {
                break;
            }
        }
        Ok(tokens)
    }

    /// Read raw text until next ENDASM keyword
    pub fn read_until_endasm(&mut self) -> Result<(String, Span), String> {
        let span = self.current_span();
        let mut text = String::new();
        loop {
            // Check if upcoming word is ENDASM
            let remaining = &self.chars[self.pos..];
            let check_word: String = remaining.iter().take(6).collect();
            if check_word.to_uppercase() == "ENDASM" {
                // Check word boundary
                let boundary = remaining.get(6).map_or(true, |c| !c.is_alphanumeric() && *c != '_');
                if boundary {
                    for _ in 0..6 {
                        self.advance();
                    }
                    break;
                }
            }
            if let Some(c) = self.advance() {
                text.push(c);
            } else {
                return Err(format!("Unterminated ASM block at line {}, col {}", span.line, span.col));
            }
        }
        Ok((text, span))
    }
}
