// CoolAction!: source text to a COOL8 PRG, entirely in Rust so the
// browser build can carry it. docs/15-action.md is the reference.

pub mod asm;
pub mod ast;
pub mod codegen;
pub mod lexer;
pub mod parser;
pub mod token;

use std::collections::HashMap;

pub struct CompileResult {
    /// The generated assembly, which tools/cool8asm.py also accepts.
    pub asm_text: String,
    /// The image, starting at `org`.
    pub binary: Vec<u8>,
    /// The image behind its two-byte load address (D87).
    pub prg: Vec<u8>,
    pub symbols: HashMap<String, u16>,
    /// Branches the assembler had to grow (docs/08-assembler.md).
    pub relaxed: usize,
}

/// Compile CoolAction! source. `org` is where the program loads; the
/// PRG header carries it, so `SYS "NAME.BIN"` needs no number.
pub fn compile(source: &str, org: u16) -> Result<CompileResult, String> {
    let mut parser = parser::Parser::new(source)?;
    let program = parser.parse_program()?;

    let mut cg = codegen::Codegen::new(org);
    let asm_text = cg.generate(&program)?;

    let mut assembler = asm::Assembler::new();
    let (image_org, binary, symbols) = assembler
        .assemble(&asm_text)
        .map_err(|e| format!("in the generated assembly:\n{}", e))?;
    if image_org != org {
        return Err(format!("image starts at ${:04X}, not ${:04X}", image_org, org));
    }

    let mut prg = Vec::with_capacity(binary.len() + 2);
    prg.push((org & 0xFF) as u8);
    prg.push((org >> 8) as u8);
    prg.extend_from_slice(&binary);

    Ok(CompileResult {
        asm_text,
        binary,
        prg,
        symbols,
        relaxed: assembler.relaxed,
    })
}
