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
    textdump: Option<String>,
    pub keys: Option<String>,
    pub wav: Option<String>,
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
        } else if let Some(v) = arg.strip_prefix("+textdump=") {
            a.textdump = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+keys=") {
            a.keys = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("+wav=") {
            a.wav = Some(v.to_string());
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
    Lines(u64),
    Nmi,
    Poke(u16, Vec<u8>),
}

/// One op per line: `type <hex bytes>`, `scan <hex bytes>`, `frames N`,
/// `lines N` (scanlines rather than frames, which is what a raster
/// split needs), `nmi` (the break button), and `poke <hex addr>
/// <hex bytes>` — every byte written to that one address through the
/// bus, which is what makes the auto-incrementing data ports (VRAM,
/// palette, sprites, sound) scriptable.
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
            "lines" => {
                let n = it.next().unwrap_or_else(|| bad());
                ops.push(Op::Lines(n.parse().unwrap_or_else(|_| bad())));
            }
            "nmi" => ops.push(Op::Nmi),
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
            Op::Nmi => m.cpu.pulse_nmi(),
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
            Op::Lines(k) => {
                let mut done = 0;
                let mut prev = m.line;
                while done < *k {
                    let before = m.cpu.instructions;
                    m.tick();
                    if m.cpu.instructions != before {
                        n += 1;
                        trace.line(&m.cpu);
                    }
                    if m.line != prev {
                        prev = m.line;
                        done += 1;
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
    if let Some(p) = args.textdump.as_ref() {
        // The text screen through the machine's own VID_BASE, wrap
        // included — what m.text() reads on the Python side.
        let v = &m.bus.video;
        let wrap = ((v.stride << 5) as u16).wrapping_sub(1);
        let mut out = create(p);
        for r in 0..30u16 {
            let ra = (v.base & !wrap)
                | (v.base.wrapping_add(r.wrapping_mul(v.stride)) & wrap);
            let mut row = [b' '; 80];
            for (c, slot) in row.iter_mut().enumerate() {
                let b = m.bus.mem[ra.wrapping_add(2 * c as u16) as usize];
                if (0x20..0x7F).contains(&b) {
                    *slot = b;
                }
            }
            out.write_all(&row).unwrap();
            out.write_all(b"\n").unwrap();
        }
        out.flush().unwrap();
    }

    // To stderr: in machine mode stdout may be carrying the trace.
    let secs = started.elapsed().as_secs_f64();
    eprintln!("-- {} instructions, {} cycles, {} frames, {:.6}s",
              n, m.cpu.cycles, m.frames, secs);
}

// --------------------------------------------------------- batch mode

/// The registers a batch run carries in and out, so tools/cool8rsvm.py
/// can poke a machine, run it, inspect it, and run it again — the
/// shape every vm.Machine test already has. Peripheral state does not
/// round-trip; the batch machine is for CPU-and-RAM workloads and its
/// docstring says so.
#[derive(Default)]
struct Regs {
    pc: u16,
    sp: u16,
    r: [u8; 4],
    x: u16,
    y: u16,
    f: u8,
    cycles: u64,
    instructions: u64,
    halted: bool,
}

impl Regs {
    fn parse(csv: &str) -> Option<Regs> {
        let v: Vec<u64> = csv.split(',')
            .map(|s| s.parse().ok())
            .collect::<Option<Vec<u64>>>()?;
        if v.len() != 12 {
            return None;
        }
        Some(Regs {
            pc: v[0] as u16,
            sp: v[1] as u16,
            r: [v[2] as u8, v[3] as u8, v[4] as u8, v[5] as u8],
            x: v[6] as u16,
            y: v[7] as u16,
            f: v[8] as u8,
            cycles: v[9],
            instructions: v[10],
            halted: v[11] != 0,
        })
    }

    fn of(m: &machine::Machine) -> Regs {
        let c = &m.cpu;
        Regs {
            pc: c.pc, sp: c.sp, r: c.r, x: c.x, y: c.y, f: c.f(),
            cycles: c.cycles, instructions: c.instructions,
            halted: c.halted,
        }
    }

    fn csv(&self) -> String {
        format!("{},{},{},{},{},{},{},{},{},{},{},{}",
                self.pc, self.sp, self.r[0], self.r[1], self.r[2],
                self.r[3], self.x, self.y, self.f, self.cycles,
                self.instructions, self.halted as u8)
    }
}

fn parse_pcs(csv: &str) -> Vec<u16> {
    if csv == "-" {
        return Vec::new();
    }
    csv.split(',')
        .map(|s| s.parse().unwrap_or_else(|_| die(format!(
            "bad pc list {:?}", csv))))
        .collect()
}

/// The run loop itself, in place on any machine. It is
/// cool8vm.Machine.run's own, tests in its order — until, breakpoint,
/// cycles, halt, tick — so a test that moves from one machine to the
/// other keeps its stopping behaviour exactly.
fn run_loop(m: &mut machine::Machine, budget: u64, until: &[u16],
            brk: &[u16], cycles: Option<u64>) -> &'static str {
    let start = m.cpu.cycles;
    let mut last: i32 = -1;
    for _ in 0..budget {
        if until.contains(&m.cpu.pc) {
            return "until";
        }
        if !brk.is_empty() && brk.contains(&m.cpu.pc) {
            return "breakpoint";
        }
        if let Some(cl) = cycles {
            if m.cpu.cycles - start >= cl {
                return "cycles";
            }
        }
        if m.cpu.pc as i32 == last {
            return "halt";
        }
        last = m.cpu.pc as i32;
        m.tick();
    }
    "budget"
}

/// The core of a batch run: a memory image and the registers in, the
/// machine run to a stop, both out.
fn batch_run(image: &[u8], romen: bool, budget: u64, regs: Option<&Regs>,
             until: &[u16], brk: &[u16], cycles: Option<u64>)
             -> (&'static str, machine::Machine) {
    let mut m = machine::Machine::new([0u8; 4096], None);
    if image.len() != 0x10000 {
        die(format!("memory image is {} bytes, want 65536", image.len()));
    }
    m.bus.mem.copy_from_slice(image);
    m.bus.romen = romen;
    if let Some(rg) = regs {
        let c = &mut m.cpu;
        c.pc = rg.pc;
        c.sp = rg.sp;
        c.r = rg.r;
        c.x = rg.x;
        c.y = rg.y;
        c.set_f(rg.f);
        c.cycles = rg.cycles;
        c.instructions = rg.instructions;
        c.halted = rg.halted;
    }
    let reason = run_loop(&mut m, budget, until, brk, cycles);
    (reason, m)
}

fn run_batch(args: &Args) {
    let image = read_file(args.mem.as_ref().unwrap());
    let mut regs = Regs { sp: 0xFFF8, ..Regs::default() };
    if let Some(pc) = args.pc {
        regs.pc = pc;
    }
    if let Some(sp) = args.sp {
        regs.sp = sp;
    }
    let (reason, m) = batch_run(&image, args.romen, args.budget,
                                Some(&regs), &[], &[], None);
    if let Some(p) = args.outmem.as_ref() {
        std::fs::write(p, m.bus.mem.as_ref())
            .unwrap_or_else(|e| die(format!("cannot write {}: {}", p, e)));
    }
    println!("-- reason={} instructions={} cycles={}",
             reason, m.cpu.instructions, m.cpu.cycles);
}

fn hex_of(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{:02x}", b));
    }
    if s.is_empty() {
        s.push('-');
    }
    s
}

fn bytes_of(hex: &str) -> Vec<u8> {
    if hex == "-" {
        return Vec::new();
    }
    (0..hex.len() / 2)
        .map(|i| u8::from_str_radix(&hex[2 * i..2 * i + 2], 16)
            .unwrap_or_else(|_| die(format!("bad hex {:?}", hex))))
        .collect()
}

/// The raw character bytes of the visible text screen, through the
/// machine's own VID_BASE and the circular wrap — the address math
/// m.row() uses on the Python side, which does the string munging.
fn text_bytes(m: &machine::Machine) -> Vec<u8> {
    let v = &m.bus.video;
    let wrap = ((v.stride << 5) as u16).wrapping_sub(1);
    let mut out = Vec::with_capacity(30 * 80);
    for r in 0..30u16 {
        let ra = (v.base & !wrap)
            | (v.base.wrapping_add(r.wrapping_mul(v.stride)) & wrap);
        for c in 0..80u16 {
            out.push(m.bus.mem[ra.wrapping_add(2 * c) as usize]);
        }
    }
    out
}

/// `+serve`: one machine service per line over stdin, so a suite of a
/// hundred cases pays for one process rather than a hundred. Fields
/// are tab-separated because some carry paths; numbers are decimal,
/// payloads are hex with `-` for empty.
///
/// The stateless form carries a whole machine per call:
///
///     run \t mem.bin \t out.bin \t budget \t romen \t regs \t until \t brk \t cycles
///     -> ok <reason> <regs>          (after out.bin is written)
///
/// Registers round-trip; peripheral state does not — every `run` is a
/// fresh machine around the carried CPU and memory.
///
/// The session form holds ONE persistent machine — peripherals, flash
/// and all — which is what lets the interactive suites move here. One
/// session per process: a client that needs two machines starts two
/// servers. The commands mirror cool8vm.Machine's API, at the
/// machine-API granularity RUST_PORT.md requires the boundary to keep:
///
///     new \t rom|- \t flash|- [\t font|0|-]   fresh machine (paths; - for
///                                      none; the 4th field attaches the
///                                      scanline renderer, 0 = blank font)
///     sregs \t regs \t romen           set the register file
///     gregs                            -> ok <regs> <romen>
///     srun \t budget \t until \t brk \t cycles   -> ok <reason> <regs>
///     ticks \t n                       n tick()s -> ok <regs>
///     frames \t n                      n frames of tick() -> ok <regs>
///     settle \t idle \t irhead \t irtail \t budget
///                                      -> ok settled|budget <regs>
///     type|scan \t hex                 UART / PS/2 bytes in
///     nmi                              the break button
///     said                             -> ok <hex>, draining the UART
///     stat                             -> ok <rx> <q> <uart_ov> <kbd_ov>
///     rd \t addr \t len                -> ok <hex>   (RAM, no side effects)
///     wr \t addr \t hex                RAM in, no side effects
///     busrd \t addr                    -> ok <val>   (through the bus)
///     buswr \t addr \t hex             every byte through the bus — the
///                                      auto-increment data-port idiom
///     text                             -> ok <hex of 30x80 char bytes>
///     fb                               -> ok <hex of 640x480 u16 LE pixels>
///     profon                           start (or restart) the cycle profile
///     profdump                         -> ok pc:cycles ... (nonzero only)
///     spmin / spclr                    the SP low-water mark; reset it
///     flush                            flash image written back to its path
///
/// `settle` is test_basic's idle test, server-side because it polls
/// per instruction: UART FIFO empty, PS/2 FIFO empty, the input ring
/// drained (mem[irhead] == mem[irtail]) and the PC at the idle label.
/// The session: the machine plus the observation the suites need and a
/// per-instruction Python loop cannot afford over a pipe — a cycle
/// profile by PC, and the stack's low-water mark. Both ride the tick
/// wrapper, so every stepping command feeds them.
struct Sess {
    m: machine::Machine,
    flash_path: Option<String>,
    prof: Option<Box<[u64; 0x10000]>>,
    spmin: u16,
}

impl Sess {
    fn tick(&mut self) {
        let pc = self.m.cpu.pc as usize;
        let c0 = self.m.cpu.cycles;
        self.m.tick();
        if let Some(p) = self.prof.as_mut() {
            p[pc] += self.m.cpu.cycles - c0;
        }
        if self.m.cpu.sp < self.spmin {
            self.spmin = self.m.cpu.sp;
        }
    }

    /// cool8vm.Machine.run's loop, tests in its order, on the wrapper.
    fn run(&mut self, budget: u64, until: &[u16], brk: &[u16],
           cycles: Option<u64>) -> &'static str {
        let start = self.m.cpu.cycles;
        let mut last: i32 = -1;
        for _ in 0..budget {
            if until.contains(&self.m.cpu.pc) {
                return "until";
            }
            if !brk.is_empty() && brk.contains(&self.m.cpu.pc) {
                return "breakpoint";
            }
            if let Some(cl) = cycles {
                if self.m.cpu.cycles - start >= cl {
                    return "cycles";
                }
            }
            if self.m.cpu.pc as i32 == last {
                return "halt";
            }
            last = self.m.cpu.pc as i32;
            self.tick();
        }
        "budget"
    }
}

fn run_serve() {
    use std::io::BufRead;
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    let mut sess: Option<Sess> = None;
    for line in stdin.lock().lines() {
        let line = line.unwrap_or_default();
        let f: Vec<&str> = line.split('\t').collect();
        if line.is_empty() || f[0] == "quit" {
            break;
        }
        let num = |s: &str| s.parse::<u64>()
            .unwrap_or_else(|_| die(format!("bad number {:?}", s)));
        let opt = |s: &str| if s == "-" { None } else { Some(num(s)) };

        // ---- the stateless batch form
        if f[0] == "run" && f.len() == 9 {
            let image = read_file(f[1]);
            let regs = Regs::parse(f[5])
                .unwrap_or_else(|| die(format!("bad regs {:?}", f[5])));
            let until = parse_pcs(f[6]);
            let brk = parse_pcs(f[7]);
            let (reason, m) = batch_run(&image, num(f[4]) != 0, num(f[3]),
                                        Some(&regs), &until, &brk, opt(f[8]));
            std::fs::write(f[2], m.bus.mem.as_ref()).unwrap_or_else(
                |e| die(format!("cannot write {}: {}", f[2], e)));
            writeln!(out, "ok {} {}", reason, Regs::of(&m).csv()).unwrap();
            out.flush().unwrap();
            continue;
        }

        // ---- the session form. `new` takes rom|-, flash|-, and an
        // optional renderer field: `-` none, `0` a zero font (sprites
        // and bitmaps need no glyphs), else a font path.
        if f[0] == "new" && (f.len() == 3 || f.len() == 4) {
            let rom = if f[1] == "-" { [0u8; 4096] } else { load_rom(f[1]) };
            let flash = if f[2] == "-" { None }
                        else { Some(read_file(f[2])) };
            let mut m = machine::Machine::new(rom, flash);
            if f.len() == 4 && f[3] != "-" {
                let font = if f[3] == "0" { [0u8; 4096] }
                           else { load_font(f[3]) };
                m.renderer = Some(render::Renderer::new(font));
            }
            sess = Some(Sess {
                m,
                flash_path: if f[2] == "-" { None }
                            else { Some(f[2].to_string()) },
                prof: None,
                spmin: 0xFFFF,
            });
            writeln!(out, "ok").unwrap();
            out.flush().unwrap();
            continue;
        }
        let s = match sess.as_mut() {
            Some(s) => s,
            None => {
                writeln!(out, "err no machine").unwrap();
                out.flush().unwrap();
                continue;
            }
        };
        let reply = match f[0] {
            "sregs" if f.len() == 3 => {
                let rg = Regs::parse(f[1])
                    .unwrap_or_else(|| die(format!("bad regs {:?}", f[1])));
                let c = &mut s.m.cpu;
                c.pc = rg.pc;
                c.sp = rg.sp;
                c.r = rg.r;
                c.x = rg.x;
                c.y = rg.y;
                c.set_f(rg.f);
                c.cycles = rg.cycles;
                c.instructions = rg.instructions;
                c.halted = rg.halted;
                s.m.bus.romen = num(f[2]) != 0;
                "ok".to_string()
            }
            "gregs" => format!("ok {} {}", Regs::of(&s.m).csv(),
                               s.m.bus.romen as u8),
            "srun" if f.len() == 5 => {
                let until = parse_pcs(f[2]);
                let brk = parse_pcs(f[3]);
                let reason = s.run(num(f[1]), &until, &brk, opt(f[4]));
                format!("ok {} {} {}", reason, Regs::of(&s.m).csv(),
                        s.m.bus.romen as u8)
            }
            "ticks" if f.len() == 2 => {
                for _ in 0..num(f[1]) {
                    s.tick();
                }
                format!("ok {} {}", Regs::of(&s.m).csv(),
                        s.m.bus.romen as u8)
            }
            "frames" if f.len() == 2 => {
                let target = s.m.frames + num(f[1]);
                while s.m.frames < target {
                    s.tick();
                }
                format!("ok {} {}", Regs::of(&s.m).csv(),
                        s.m.bus.romen as u8)
            }
            "settle" if f.len() == 5 => {
                let idle = num(f[1]) as u16;
                let (irh, irt) = (num(f[2]) as usize, num(f[3]) as usize);
                let mut reason = "budget";
                for _ in 0..num(f[4]) {
                    if s.m.bus.uart.rx.is_empty()
                        && s.m.bus.kbd.q.is_empty()
                        && s.m.bus.mem[irh] == s.m.bus.mem[irt]
                        && s.m.cpu.pc == idle {
                        reason = "settled";
                        break;
                    }
                    s.tick();
                }
                format!("ok {} {} {}", reason, Regs::of(&s.m).csv(),
                        s.m.bus.romen as u8)
            }
            "type" if f.len() == 2 => {
                s.m.bus.uart.feed(&bytes_of(f[1]));
                "ok".to_string()
            }
            "scan" if f.len() == 2 => {
                s.m.bus.kbd.feed(&bytes_of(f[1]));
                "ok".to_string()
            }
            "nmi" => {
                s.m.cpu.pulse_nmi();
                "ok".to_string()
            }
            "said" => {
                let r = format!("ok {}", hex_of(&s.m.bus.uart.tx));
                s.m.bus.uart.tx.clear();
                r
            }
            "stat" => format!("ok {} {} {} {} {} {}",
                              s.m.bus.uart.rx.len(), s.m.bus.kbd.q.len(),
                              s.m.bus.uart.overrun as u8,
                              s.m.bus.kbd.overrun as u8,
                              s.m.bus.kbd.irq_en as u8,
                              s.m.frames),
            // The programmed peripheral state, for a harness comparing
            // two programs' setup: the palette as committed entries
            // (u16 LE), the sprite descriptor bytes, the sound voices.
            "pald" => {
                let mut bytes = Vec::with_capacity(512);
                for e in s.m.bus.video.pal.iter() {
                    bytes.extend_from_slice(&e.to_le_bytes());
                }
                format!("ok {}", hex_of(&bytes))
            }
            "sprd" => format!("ok {}", hex_of(&s.m.bus.video.spr)),
            "sndd" => format!("ok {}", hex_of(&s.m.bus.sound.dump())),
            // The level stream the engine has produced since the last
            // ask, at SND_HZ — what test_vm holds against the RTL's own
            // dump of the running engine.
            "snds" => {
                let r = format!("ok {}", hex_of(&s.m.bus.sound.samples));
                s.m.bus.sound.samples.clear();
                r
            }
            "vrd" if f.len() == 3 => {
                let a = num(f[1]) as usize;
                let n = num(f[2]) as usize;
                let bytes: Vec<u8> = (0..n)
                    .map(|i| s.m.bus.video.vram[(a + i) & 0xFFFF])
                    .collect();
                format!("ok {}", hex_of(&bytes))
            }
            "vwr" if f.len() == 3 => {
                let a = num(f[1]) as usize;
                for (i, b) in bytes_of(f[2]).iter().enumerate() {
                    s.m.bus.video.vram[(a + i) & 0xFFFF] = *b;
                }
                "ok".to_string()
            }
            "rd" if f.len() == 3 => {
                let a = num(f[1]) as usize;
                let n = num(f[2]) as usize;
                let bytes: Vec<u8> = (0..n)
                    .map(|i| s.m.bus.mem[(a + i) & 0xFFFF])
                    .collect();
                format!("ok {}", hex_of(&bytes))
            }
            "wr" if f.len() == 3 => {
                let a = num(f[1]) as usize;
                for (i, b) in bytes_of(f[2]).iter().enumerate() {
                    s.m.bus.mem[(a + i) & 0xFFFF] = *b;
                }
                "ok".to_string()
            }
            "busrd" if f.len() == 2 => {
                use cpu::Bus as _;
                format!("ok {}", s.m.bus.read(num(f[1]) as u16))
            }
            "buswr" if f.len() == 3 => {
                use cpu::Bus as _;
                let a = num(f[1]) as u16;
                for b in bytes_of(f[2]) {
                    s.m.bus.write(a, b);
                }
                "ok".to_string()
            }
            "text" => format!("ok {}", hex_of(&text_bytes(&s.m))),
            // The frame the renderer has drawn: 640x480 of 12-bit
            // palette colours, two hex bytes per pixel, little-endian.
            "fb" => match s.m.renderer.as_ref() {
                Some(r) => {
                    let mut bytes = Vec::with_capacity(r.fb.len() * 2);
                    for px in r.fb.iter() {
                        bytes.extend_from_slice(&px.to_le_bytes());
                    }
                    format!("ok {}", hex_of(&bytes))
                }
                None => "err no renderer".to_string(),
            },
            // The profiler: cycles by the PC that spent them, exactly
            // what cool8vm.Machine.profile counted — server-side,
            // because it looks at every instruction.
            "profon" => {
                s.prof = Some(vec![0u64; 0x10000].into_boxed_slice()
                    .try_into().unwrap());
                "ok".to_string()
            }
            "profdump" => {
                let mut r = String::from("ok");
                if let Some(p) = s.prof.as_ref() {
                    for (pc, &c) in p.iter().enumerate() {
                        if c != 0 {
                            r.push_str(&format!(" {}:{}", pc, c));
                        }
                    }
                }
                r
            }
            // The stack's low-water mark since `spclr` (or the
            // session's start) — the SP-after-every-instruction look a
            // pipe cannot afford.
            "spmin" => format!("ok {}", s.spmin),
            "spclr" => {
                s.spmin = 0xFFFF;
                "ok".to_string()
            }
            "flush" => match s.flash_path.as_ref() {
                Some(p) => {
                    std::fs::write(p, &s.m.bus.flash.mem).unwrap_or_else(
                        |e| die(format!("cannot write {}: {}", p, e)));
                    "ok".to_string()
                }
                None => "err no flash".to_string(),
            },
            _ => "err bad command".to_string(),
        };
        writeln!(out, "{}", reply).unwrap();
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
