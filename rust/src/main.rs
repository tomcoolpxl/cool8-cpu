// cool8rs — the COOL8 fast runner. See RUST_PORT.md.
//
// Two modes, chosen by the arguments:
//
// CPU mode (+hex=…): FlatBus, the RTL testbench's plusarg vocabulary,
// so sim/rustsim.py can drive this exactly the way sim/cosim.py drives
// vvp: +hex=, +trace=, +memdump=, +maxinstr=, +irqafter=, +irqat=,
// +nmiafter=. Interrupts are injected by retired-instruction count,
// never by cycle, for the reason the verification contract gives: the
// models cannot agree on a cycle, and do not need to.
//
// Machine mode (+rom=…): the whole machine of machine.rs, driven by a
// stimulus script that sim/rustsim.py executes identically against
// cool8vm.Machine. `+trace=-` streams the state lines to stdout so the
// Python side can compare in lockstep without a quarter-gigabyte file.

mod cpu;
#[cfg(feature = "gui")]
mod emu;
mod machine;
mod optab;
mod render;

use cpu::Bus as _;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::process::exit;

// Plusargs that only mean something to a hardware simulation. Accepted
// and ignored so a cosim call site can be reused verbatim; anything
// else unknown is an error, so a typo'd +irqafter cannot silently
// become a run with no interrupt in it.
const IGNORED: [&str; 6] = ["+ws=", "+wsrnd=", "+maxcycles=", "+busrqat=",
                            "+busrqlen=", "+busrqafter="];

#[derive(Default)]
pub struct Args {
    hex: Option<String>,
    pub rom: Option<String>,
    pub flash: Option<String>,
    script: Option<String>,
    said: Option<String>,
    vramdump: Option<String>,
    trace: Option<String>,
    memdump: Option<String>,
    maxinstr: u64,
    irq_at: Option<u64>,
    nmi_at: Option<u64>,
    mem: Option<String>,
    outmem: Option<String>,
    pc: Option<u16>,
    sp: Option<u16>,
    romen: bool,
    budget: u64,
    pub font: Option<String>,
    pub keymap: Option<String>,
    fbdump: Option<String>,
    emu: bool,
}

fn parse_args() -> Args {
    let mut a = Args::default();
    a.romen = true;
    a.budget = 200_000_000;
    for arg in std::env::args().skip(1) {
        let num = |s: &str| -> u64 {
            s.parse().unwrap_or_else(|_| {
                eprintln!("bad number in {}", arg);
                exit(2);
            })
        };
        if let Some(v) = arg.strip_prefix("+hex=") {
            a.hex = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+rom=") {
            a.rom = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+flash=") {
            a.flash = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+script=") {
            a.script = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+said=") {
            a.said = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+vramdump=") {
            a.vramdump = Some(v.to_string());
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
        } else if let Some(v) = arg.strip_prefix("+mem=") {
            a.mem = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+outmem=") {
            a.outmem = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+pc=") {
            a.pc = Some(num(v) as u16);
        } else if let Some(v) = arg.strip_prefix("+sp=") {
            a.sp = Some(num(v) as u16);
        } else if let Some(v) = arg.strip_prefix("+romen=") {
            a.romen = num(v) != 0;
        } else if let Some(v) = arg.strip_prefix("+budget=") {
            a.budget = num(v);
        } else if let Some(v) = arg.strip_prefix("+font=") {
            a.font = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+keymap=") {
            a.keymap = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+fbdump=") {
            a.fbdump = Some(v.to_string());
        } else if arg == "+emu" {
            a.emu = true;
        } else if IGNORED.iter().any(|p| arg.starts_with(p)) {
            // a hardware-only knob; nothing to do in software
        } else {
            eprintln!("unknown argument: {}", arg);
            exit(2);
        }
    }
    if a.hex.is_none() && a.rom.is_none() && a.mem.is_none() {
        eprintln!(
            "usage: cool8rs +hex=image.hex [+trace=f] [+memdump=f] \
             [+maxinstr=n] [+irqafter=n] [+nmiafter=n]\n\
             \x20      cool8rs +rom=rom.bin +script=s [+flash=img] \
             [+trace=f|-] [+memdump=f] [+vramdump=f] [+said=f]\n\
             \x20      cool8rs +mem=in.bin +outmem=out.bin [+pc=n] [+sp=n] \
             [+romen=0|1] [+budget=n]"
        );
        exit(2);
    }
    a
}

fn die(msg: String) -> ! {
    eprintln!("{}", msg);
    exit(2);
}

fn read_file(path: &str) -> Vec<u8> {
    std::fs::read(path)
        .unwrap_or_else(|e| die(format!("cannot read {}: {}", path, e)))
}

fn load_hex(path: &str, mem: &mut [u8; 0x10000]) {
    let text = std::fs::read_to_string(path)
        .unwrap_or_else(|e| die(format!("cannot read {}: {}", path, e)));
    let mut i = 0;
    for line in text.split_ascii_whitespace() {
        if i >= mem.len() {
            break;
        }
        mem[i] = u8::from_str_radix(line, 16)
            .unwrap_or_else(|_| die(format!("bad hex byte {:?} in {}",
                                            line, path)));
        i += 1;
    }
}

fn create(path: &str) -> BufWriter<File> {
    BufWriter::new(File::create(path)
        .unwrap_or_else(|e| die(format!("cannot write {}: {}", path, e))))
}

fn dump_bytes(path: &str, bytes: &[u8]) {
    let mut out = create(path);
    for b in bytes {
        writeln!(out, "{:02x}", b).unwrap();
    }
    out.flush().unwrap();
}

/// One state line per retired instruction — cosim's format exactly.
enum Trace {
    Off,
    Stdout(BufWriter<std::io::Stdout>),
    File(BufWriter<File>),
}

impl Trace {
    fn open(spec: &Option<String>) -> Trace {
        match spec.as_deref() {
            None => Trace::Off,
            Some("-") => Trace::Stdout(BufWriter::new(std::io::stdout())),
            Some(p) => Trace::File(create(p)),
        }
    }

    fn line(&mut self, cpu: &cpu::Cpu) {
        let w: &mut dyn Write = match self {
            Trace::Off => return,
            Trace::Stdout(w) => w,
            Trace::File(w) => w,
        };
        writeln!(
            w,
            "{:04x} {:02x}{:02x}{:02x}{:02x} {:04x} {:04x} {:04x} {:02x}",
            cpu.pc, cpu.r[0], cpu.r[1], cpu.r[2], cpu.r[3],
            cpu.x, cpu.y, cpu.sp, cpu.f()
        )
        .unwrap();
    }

    fn flush(&mut self) {
        match self {
            Trace::Off => {}
            Trace::Stdout(w) => w.flush().unwrap(),
            Trace::File(w) => w.flush().unwrap(),
        }
    }
}

// ----------------------------------------------------------- CPU mode

fn run_cpu(args: &Args) {
    let mut bus = cpu::FlatBus::new();
    load_hex(args.hex.as_ref().unwrap(), &mut bus.mem);
    let mut c = cpu::Cpu::new();
    c.reset(&mut bus);

    let mut trace = Trace::open(&args.trace);

    // Event order per retired instruction matches cosim.emu_trace:
    // retire, apply any event, write the state line, then the halt
    // check — so an event aimed at a halted machine still fires.
    let mut n: u64 = 0;
    if args.irq_at == Some(0) {
        c.irq_line = true;
    }
    if args.nmi_at == Some(0) {
        c.pulse_nmi();
    }
    let started = std::time::Instant::now();
    loop {
        let before = c.instructions;
        c.step(&mut bus);
        if c.instructions != before {
            n += 1;
            if args.irq_at == Some(n) {
                c.irq_line = true;
            }
            if args.nmi_at == Some(n) {
                c.pulse_nmi();
            }
            trace.line(&c);
            if args.maxinstr != 0 && n >= args.maxinstr {
                break;
            }
        }
        if c.halted && !(c.nmi_edge || (c.irq_line && c.i)) {
            break;
        }
        if n > 20_000_000 {
            eprintln!("runaway: 20M instructions without halting");
            exit(1);
        }
    }
    trace.flush();

    if let Some(p) = args.memdump.as_ref() {
        dump_bytes(p, bus.mem.as_ref());
    }

    // Stepping time alone, not process start-up or the hex parse —
    // sim/rustsim.py reads this line for the speed report.
    let secs = started.elapsed().as_secs_f64();
    println!("-- {} instructions, {} cycles, {:.6}s", n, c.cycles, secs);
}

// ------------------------------------------------------- machine mode

enum Op {
    Type(Vec<u8>),
    Scan(Vec<u8>),
    Frames(u64),
    Poke(u16, Vec<u8>),
}

/// One op per line: `type <hex bytes>`, `scan <hex bytes>`, `frames N`,
/// `poke <hex addr> <hex bytes>` — every byte written to that one
/// address through the bus, which is what makes the auto-incrementing
/// data ports (VRAM, palette, sprites, sound) scriptable.
/// Blank lines and `#` comments are skipped. sim/rustsim.py writes and
/// executes the very same file against the Python machine.
fn load_script(path: &str) -> Vec<Op> {
    let text = std::fs::read_to_string(path)
        .unwrap_or_else(|e| die(format!("cannot read {}: {}", path, e)));
    let mut ops = Vec::new();
    for (ln, line) in text.lines().enumerate() {
        let line = line.split('#').next().unwrap().trim();
        if line.is_empty() {
            continue;
        }
        let bad = || -> ! {
            die(format!("{}:{}: bad script line {:?}", path, ln + 1, line))
        };
        let mut it = line.split_ascii_whitespace();
        let word = it.next().unwrap();
        match word {
            "frames" => {
                let n = it.next().unwrap_or_else(|| bad());
                ops.push(Op::Frames(n.parse().unwrap_or_else(|_| bad())));
            }
            "type" | "scan" => {
                let bytes: Vec<u8> = it
                    .map(|w| u8::from_str_radix(w, 16)
                        .unwrap_or_else(|_| bad()))
                    .collect();
                ops.push(if word == "type" { Op::Type(bytes) }
                         else { Op::Scan(bytes) });
            }
            "poke" => {
                let addr = it.next().unwrap_or_else(|| bad());
                let addr = u16::from_str_radix(addr, 16)
                    .unwrap_or_else(|_| bad());
                let bytes: Vec<u8> = it
                    .map(|w| u8::from_str_radix(w, 16)
                        .unwrap_or_else(|_| bad()))
                    .collect();
                ops.push(Op::Poke(addr, bytes));
            }
            _ => bad(),
        }
    }
    ops
}

pub fn load_rom(path: &str) -> [u8; 4096] {
    let rom_bytes = read_file(path);
    if rom_bytes.len() > 4096 {
        die(format!("ROM is {} bytes; the window is 4096", rom_bytes.len()));
    }
    let mut rom = [0u8; 4096];
    rom[..rom_bytes.len()].copy_from_slice(&rom_bytes);
    rom
}

pub fn load_font(path: &str) -> [u8; 4096] {
    let b = read_file(path);
    if b.len() > 4096 {
        die(format!("font is {} bytes; the ROM is 4096", b.len()));
    }
    let mut font = [0u8; 4096];
    font[..b.len()].copy_from_slice(&b);
    font
}

fn run_machine(args: &Args) {
    let rom = load_rom(args.rom.as_ref().unwrap());
    let flash = args.flash.as_ref().map(|p| read_file(p));
    let mut m = machine::Machine::new(rom, flash);
    if args.fbdump.is_some() {
        let font = args.font.as_ref().unwrap_or_else(|| {
            die("+fbdump needs +font=".to_string())
        });
        m.renderer = Some(render::Renderer::new(load_font(font)));
    }

    let script = args.script.as_ref()
        .map(|p| load_script(p))
        .unwrap_or_default();

    let mut trace = Trace::open(&args.trace);
    let mut n: u64 = 0;
    let started = std::time::Instant::now();

    for op in &script {
        match op {
            Op::Type(b) => m.bus.uart.feed(b),
            Op::Scan(b) => m.bus.kbd.feed(b),
            Op::Poke(a, b) => {
                for &v in b {
                    m.bus.write(*a, v);
                }
            }
            Op::Frames(k) => {
                let target = m.frames + k;
                while m.frames < target {
                    let before = m.cpu.instructions;
                    m.tick();
                    if m.cpu.instructions != before {
                        n += 1;
                        trace.line(&m.cpu);
                    }
                }
            }
        }
    }
    trace.flush();

    if let Some(p) = args.memdump.as_ref() {
        dump_bytes(p, m.bus.mem.as_ref());
    }
    if let Some(p) = args.vramdump.as_ref() {
        dump_bytes(p, m.bus.video.vram.as_ref());
    }
    if let Some(p) = args.said.as_ref() {
        let mut out = create(p);
        out.write_all(&m.bus.uart.tx).unwrap();
        out.flush().unwrap();
    }
    if let Some(p) = args.fbdump.as_ref() {
        // 640x480 of 12-bit palette colours, u16 little-endian.
        let r = m.renderer.as_ref().unwrap();
        let mut out = create(p);
        for px in r.fb.iter() {
            out.write_all(&px.to_le_bytes()).unwrap();
        }
        out.flush().unwrap();
    }

    // To stderr: in machine mode stdout may be carrying the trace.
    let secs = started.elapsed().as_secs_f64();
    eprintln!("-- {} instructions, {} cycles, {} frames, {:.6}s",
              n, m.cpu.cycles, m.frames, secs);
}

// --------------------------------------------------------- batch mode

/// The core of a batch run for tools/cool8rsvm.py: a memory image in,
/// the machine run to a halt or a budget, the memory image out. The
/// loop is cool8vm.Machine.run's own — the halt test (a PC that does
/// not move) before the tick, the budget counted in ticks — so a test
/// that moves from one machine to the other keeps its stopping
/// behaviour exactly.
fn batch_run(image: &[u8], pc: Option<u16>, sp: Option<u16>, romen: bool,
             budget: u64) -> (&'static str, machine::Machine) {
    let mut m = machine::Machine::new([0u8; 4096], None);
    if image.len() != 0x10000 {
        die(format!("memory image is {} bytes, want 65536", image.len()));
    }
    m.bus.mem.copy_from_slice(image);
    m.bus.romen = romen;
    if let Some(pc) = pc {
        m.cpu.pc = pc;
    }
    if let Some(sp) = sp {
        m.cpu.sp = sp;
    }

    let mut last: i32 = -1;
    let mut reason = "budget";
    for _ in 0..budget {
        if m.cpu.pc as i32 == last {
            reason = "halt";
            break;
        }
        last = m.cpu.pc as i32;
        m.tick();
    }
    (reason, m)
}

fn run_batch(args: &Args) {
    let image = read_file(args.mem.as_ref().unwrap());
    let (reason, m) = batch_run(&image, args.pc, args.sp, args.romen,
                                args.budget);
    if let Some(p) = args.outmem.as_ref() {
        std::fs::write(p, m.bus.mem.as_ref())
            .unwrap_or_else(|e| die(format!("cannot write {}: {}", p, e)));
    }
    println!("-- reason={} instructions={} cycles={}",
             reason, m.cpu.instructions, m.cpu.cycles);
}

/// `+serve`: batch runs over stdin, one per line, so a suite of a
/// hundred cases pays for one process rather than a hundred. The
/// fields are tab-separated because they carry paths:
///
///     run \t mem.bin \t out.bin \t pc \t sp \t romen \t budget
///
/// answered, after out.bin is written, with
///
///     ok <reason> <instructions> <cycles>
///
/// Every run is a fresh machine — state does not carry over, which is
/// also cool8vm's shape: one Machine per test case.
fn run_serve() {
    use std::io::BufRead;
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = line.unwrap_or_default();
        let f: Vec<&str> = line.split('\t').collect();
        if line.is_empty() || f[0] == "quit" {
            break;
        }
        if f[0] != "run" || f.len() != 7 {
            writeln!(out, "err bad command").unwrap();
            out.flush().unwrap();
            continue;
        }
        let num = |s: &str| s.parse::<u64>()
            .unwrap_or_else(|_| die(format!("bad number {:?}", s)));
        let image = read_file(f[1]);
        let (reason, m) = batch_run(&image, Some(num(f[3]) as u16),
                                    Some(num(f[4]) as u16),
                                    num(f[5]) != 0, num(f[6]));
        std::fs::write(f[2], m.bus.mem.as_ref())
            .unwrap_or_else(|e| die(format!("cannot write {}: {}", f[2], e)));
        writeln!(out, "ok {} {} {}",
                 reason, m.cpu.instructions, m.cpu.cycles).unwrap();
        out.flush().unwrap();
    }
}

fn main() {
    if std::env::args().any(|a| a == "+serve") {
        run_serve();
        return;
    }
    let args = parse_args();
    if args.emu {
        #[cfg(feature = "gui")]
        {
            emu::run(&args);
            return;
        }
        #[cfg(not(feature = "gui"))]
        die("this build has no window: rebuild with \
             `cargo build --release --features gui`".to_string());
    }
    if args.mem.is_some() {
        run_batch(&args);
    } else if args.rom.is_some() {
        run_machine(&args);
    } else {
        run_cpu(&args);
    }
}
