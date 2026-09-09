// CoolAction! Compiler CLI for COOL8

use cool8rs::action;
use std::env;
use std::fs;
use std::process::exit;

fn print_usage() {
    eprintln!(
        "Usage: coolaction [options] <input.act>\n\
         \x20      coolaction --assemble <input.asm> -o <image.bin>\n\
         Options:\n\
         \x20 -o <output.bin>   Output PRG binary (default: input with .bin)\n\
         \x20 --org <hex/dec>   Origin address in RAM (default: $0200 for ~63.25 KB standalone RAM)\n\
         \x20 --asm <out.asm>   Emit generated COOL8 assembly\n\
         \x20 --sym <out.sym>   Emit symbol table\n\
         \x20 --assemble        Assemble COOL8 assembly text instead; the output is the raw image"
    );
}

/// The compiler's assembler on its own, so sim/test_action.py can hold
/// it to tools/cool8asm.py on every encoding the ISA has.
fn assemble_only(input: &str, output: Option<String>) -> ! {
    let source = match fs::read_to_string(input) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Cannot read '{}': {}", input, e);
            exit(1);
        }
    };
    let mut a = action::asm::Assembler::new();
    let (org, image, _) = match a.assemble(&source) {
        Ok(r) => r,
        Err(e) => {
            eprintln!("Assembly error:\n{}", e);
            exit(1);
        }
    };
    let out = output.unwrap_or_else(|| {
        let stem = std::path::Path::new(input).file_stem().unwrap_or_default().to_string_lossy();
        format!("{}.bin", stem)
    });
    if let Err(e) = fs::write(&out, &image) {
        eprintln!("Cannot write '{}': {}", out, e);
        exit(1);
    }
    println!(
        "coolaction: assembled {} bytes at ${:04X}, {} branches relaxed -> {}",
        image.len(),
        org,
        a.relaxed,
        out
    );
    exit(0)
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.is_empty() {
        print_usage();
        exit(1);
    }

    let mut inputs: Vec<String> = Vec::new();
    let mut output_file: Option<String> = None;
    let mut asm_file: Option<String> = None;
    let mut sym_file: Option<String> = None;
    let mut org: u16 = 0x0200; // Standalone by default ($0200)
    let mut assemble = false;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--assemble" => assemble = true,
            "-o" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Missing argument for -o");
                    exit(1);
                }
                output_file = Some(args[i].clone());
            }
            "--org" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Missing argument for --org");
                    exit(1);
                }
                let s = &args[i];
                let val = if s.starts_with('$') {
                    u16::from_str_radix(&s[1..], 16)
                } else if s.starts_with("0x") {
                    u16::from_str_radix(&s[2..], 16)
                } else {
                    s.parse::<u16>()
                };
                match val {
                    Ok(addr) => org = addr,
                    Err(e) => {
                        eprintln!("Bad origin address '{}': {}", s, e);
                        exit(1);
                    }
                }
            }
            "--asm" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Missing argument for --asm");
                    exit(1);
                }
                asm_file = Some(args[i].clone());
            }
            "--sym" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Missing argument for --sym");
                    exit(1);
                }
                sym_file = Some(args[i].clone());
            }
            "-h" | "--help" => {
                print_usage();
                exit(0);
            }
            other => {
                if other.starts_with('-') {
                    eprintln!("Unknown option '{}'", other);
                    exit(1);
                }
                inputs.push(other.to_string());
            }
        }
        i += 1;
    }

    if inputs.is_empty() {
        eprintln!("No input file specified");
        print_usage();
        exit(1);
    }
    let input_path = inputs[0].clone();

    if assemble {
        assemble_only(&input_path, output_file);
    }

    // Several files compile as one, in order: there is no INCLUDE, so
    // the library goes first on the command line.
    let mut source = String::new();
    for p in &inputs {
        match fs::read_to_string(p) {
            Ok(s) => {
                source.push_str(&s);
                source.push('\n');
            }
            Err(e) => {
                eprintln!("Cannot read '{}': {}", p, e);
                exit(1);
            }
        }
    }

    let result = match action::compile(&source, org) {
        Ok(r) => r,
        Err(e) => {
            eprintln!("Compilation error:\n{}", e);
            exit(1);
        }
    };

    let out_path = output_file.unwrap_or_else(|| {
        let stem = std::path::Path::new(&input_path)
            .file_stem()
            .unwrap_or_default()
            .to_string_lossy();
        format!("{}.bin", stem)
    });

    if let Err(e) = fs::write(&out_path, &result.prg) {
        eprintln!("Cannot write output '{}': {}", out_path, e);
        exit(1);
    }

    if let Some(p) = asm_file {
        if let Err(e) = fs::write(&p, &result.asm_text) {
            eprintln!("Cannot write assembly to '{}': {}", p, e);
        }
    }

    if let Some(p) = sym_file {
        let mut sym_lines = Vec::new();
        for (name, addr) in &result.symbols {
            sym_lines.push(format!("{:04X} {}", addr, name));
        }
        sym_lines.sort();
        if let Err(e) = fs::write(&p, sym_lines.join("\n")) {
            eprintln!("Cannot write symbols to '{}': {}", p, e);
        }
    }

    println!(
        "CoolAction!: {} -> {}: {} bytes at ${:04X}, {} branches relaxed",
        input_path,
        out_path,
        result.binary.len(),
        org,
        result.relaxed
    );
}
