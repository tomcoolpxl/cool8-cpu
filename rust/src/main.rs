// cool8rs — the COOL8 fast runner. See RUST_PORT.md.
//
// The command line is the RTL testbench's plusarg vocabulary, so
// sim/rustsim.py can drive this exactly the way sim/cosim.py drives
// vvp: +hex=, +trace=, +memdump=, +maxinstr=, +irqafter=, +irqat=,
// +nmiafter=. Interrupts are injected by retired-instruction count,
// never by cycle, for the reason the verification contract gives: the
// models cannot agree on a cycle, and do not need to.

mod cpu;
mod optab;

use std::fs::File;
use std::io::{BufWriter, Write};
use std::process::exit;

// Plusargs that only mean something to a hardware simulation. Accepted
// and ignored so a cosim call site can be reused verbatim; anything
// else unknown is an error, so a typo'd +irqafter cannot silently
// become a run with no interrupt in it.
const IGNORED: [&str; 6] = ["+ws=", "+wsrnd=", "+maxcycles=", "+busrqat=",
                            "+busrqlen=", "+busrqafter="];

struct Args {
    hex: String,
    trace: Option<String>,
    memdump: Option<String>,
    maxinstr: u64,
    irq_at: Option<u64>,
    nmi_at: Option<u64>,
}

fn parse_args() -> Args {
    let mut a = Args {
        hex: String::new(),
        trace: None,
        memdump: None,
        maxinstr: 0,
        irq_at: None,
        nmi_at: None,
    };
    for arg in std::env::args().skip(1) {
        let num = |s: &str| -> u64 {
            s.parse().unwrap_or_else(|_| {
                eprintln!("bad number in {}", arg);
                exit(2);
            })
        };
        if let Some(v) = arg.strip_prefix("+hex=") {
            a.hex = v.to_string();
        } else if let Some(v) = arg.strip_prefix("+trace=") {
            a.trace = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+memdump=") {
            a.memdump = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+maxinstr=") {
            a.maxinstr = num(v);
        } else if let Some(v) = arg.strip_prefix("+irqafter=") {
            a.irq_at = Some(num(v));
        } else if let Some(v) = arg.strip_prefix("+irqat=") {
            a.irq_at = Some(num(v));
        } else if let Some(v) = arg.strip_prefix("+nmiafter=") {
            a.nmi_at = Some(num(v));
        } else if IGNORED.iter().any(|p| arg.starts_with(p)) {
            // a hardware-only knob; nothing to do in software
        } else {
            eprintln!("unknown argument: {}", arg);
            exit(2);
        }
    }
    if a.hex.is_empty() {
        eprintln!("usage: cool8rs +hex=image.hex [+trace=f] [+memdump=f] \
                   [+maxinstr=n] [+irqafter=n] [+nmiafter=n]");
        exit(2);
    }
    a
}

fn load_hex(path: &str, mem: &mut [u8; 0x10000]) {
    let text = std::fs::read_to_string(path).unwrap_or_else(|e| {
        eprintln!("cannot read {}: {}", path, e);
        exit(2);
    });
    let mut i = 0;
    for line in text.split_ascii_whitespace() {
        if i >= mem.len() {
            break;
        }
        mem[i] = u8::from_str_radix(line, 16).unwrap_or_else(|_| {
            eprintln!("bad hex byte {:?} in {}", line, path);
            exit(2);
        });
        i += 1;
    }
}

fn main() {
    let args = parse_args();
    let mut cpu = cpu::Cpu::new();
    load_hex(&args.hex, &mut cpu.mem);
    cpu.reset();

    let mut trace = args.trace.as_ref().map(|p| {
        BufWriter::new(File::create(p).unwrap_or_else(|e| {
            eprintln!("cannot write {}: {}", p, e);
            exit(2);
        }))
    });

    // Event order per retired instruction matches cosim.emu_trace:
    // retire, apply any event, write the state line, then the halt
    // check — so an event aimed at a halted machine still fires.
    let mut n: u64 = 0;
    if args.irq_at == Some(0) {
        cpu.irq_line = true;
    }
    if args.nmi_at == Some(0) {
        cpu.pulse_nmi();
    }
    let started = std::time::Instant::now();
    loop {
        let before = cpu.instructions;
        cpu.step();
        if cpu.instructions != before {
            n += 1;
            if args.irq_at == Some(n) {
                cpu.irq_line = true;
            }
            if args.nmi_at == Some(n) {
                cpu.pulse_nmi();
            }
            if let Some(t) = trace.as_mut() {
                writeln!(
                    t,
                    "{:04x} {:02x}{:02x}{:02x}{:02x} {:04x} {:04x} {:04x} {:02x}",
                    cpu.pc, cpu.r[0], cpu.r[1], cpu.r[2], cpu.r[3],
                    cpu.x, cpu.y, cpu.sp, cpu.f()
                )
                .unwrap();
            }
            if args.maxinstr != 0 && n >= args.maxinstr {
                break;
            }
        }
        if cpu.halted && !(cpu.nmi_edge || (cpu.irq_line && cpu.i)) {
            break;
        }
        if n > 20_000_000 {
            eprintln!("runaway: 20M instructions without halting");
            exit(1);
        }
    }

    if let Some(t) = trace.as_mut() {
        t.flush().unwrap();
    }
    if let Some(p) = args.memdump.as_ref() {
        let mut out = BufWriter::new(File::create(p).unwrap_or_else(|e| {
            eprintln!("cannot write {}: {}", p, e);
            exit(2);
        }));
        for b in cpu.mem.iter() {
            writeln!(out, "{:02x}", b).unwrap();
        }
        out.flush().unwrap();
    }

    // Stepping time alone, not process start-up or the hex parse —
    // sim/rustsim.py reads this line for the speed report.
    let secs = started.elapsed().as_secs_f64();
    println!("-- {} instructions, {} cycles, {:.6}s", n, cpu.cycles, secs);
}
