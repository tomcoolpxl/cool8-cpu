// The machine in a window — the Rust counterpart of tools/cool8run.py,
// with the scanline renderer of render.rs behind the glass instead of a
// whole-frame snapshot, so raster splits and mid-frame palette work
// look on the monitor the way they look on the board.
//
// The window is SDL2 — the same library the Python front end uses
// through pygame, and the established wheel for exactly this job:
// `set_logical_size(640, 480)` makes the GPU scale the picture with the
// aspect ratio kept and letterboxes the rest, Alt+Enter toggles a real
// desktop fullscreen, key events arrive with system chords intact, and
// text input, the clipboard and the audio callback are all SDL's.
// Nothing here scales, letterboxes or polls a keyboard by hand.
//
// Feature-gated (`--features gui`): the parity suite's build stays
// dependency-free, and only this file touches SDL.
//
// ## Pacing
//
// One machine frame per presented frame, vsync-paced. Audio is the
// drift-taker: the machine produces samples at SND_HZ (8.375 MHz / 256
// ≈ 32.7 kHz) into a queue the audio callback resamples to the device
// rate; if the queue runs dry the callback holds the last level, and
// past half a second of backlog the excess is dropped.
//
// ## The keyboard, in cool8run.py's three modes (+keys=text|raw|both)
//
// `text`, the default: printable characters arrive as SDL text input —
// the user's layout applies, so a Belgian keyboard's quote is a quote —
// and are typed through the machine's own keymap, derived from
// sw/keymap.asm by the launcher. The keys that produce no character
// (cursors, Home and friends, the F-keys, the modifiers, and
// Return/Backspace/Tab/Escape, kept physical so they cannot depend on
// what a platform calls a character) go as physical Set 2 make/break,
// with SDL's own key repeat re-sending the make. `raw` sends
// everything as physical US-positional scancodes. `both` is text with
// every character echoed to the UART, for a machine that has no
// keyboard driver yet.
//
// ## The emulator's own keys
//
//     F11         the break button, SW[0] — an NMI, as the board's is
//     Ctrl+Pause  the same; SDL reports the chord as Cancel and both
//                 spellings are handled
//     F12         write the screen to a PNG in the cwd
//     Alt+Enter   fullscreen, SDL's own desktop mode
//     right click paste the clipboard, typed through the keymap

use crate::machine::Machine;
use crate::render::{Renderer, H_VIS, V_VIS};
use crate::Args;
use sdl2::audio::{AudioCallback, AudioSpecDesired};
use sdl2::event::Event;
use sdl2::keyboard::{Keycode, Mod, Scancode};
use sdl2::mouse::MouseButton;
use sdl2::pixels::PixelFormatEnum;
use sdl2::video::FullscreenType;
use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};

const SND_HZ: f64 = 8_375_000.0 / 256.0;

fn die(msg: String) -> ! {
    eprintln!("{}", msg);
    std::process::exit(1);
}

/// The machine's own layout, derived from sw/keymap.asm by the
/// launcher — never a second copy of the table. One line per typeable
/// character: `<char hex> <scancode hex> <shifted 0|1>`.
fn load_keymap(path: &str) -> HashMap<u8, (u8, bool)> {
    let mut map = HashMap::new();
    if let Ok(text) = std::fs::read_to_string(path) {
        for line in text.lines() {
            let f: Vec<&str> = line.split_whitespace().collect();
            if f.len() == 3 {
                if let (Ok(ch), Ok(code)) = (
                    u8::from_str_radix(f[0], 16),
                    u8::from_str_radix(f[1], 16),
                ) {
                    map.insert(ch, (code, f[2] == "1"));
                }
            }
        }
    }
    map
}

/// Set 2 make code for an SDL scancode (USB-HID positional), with its
/// E0 prefix flag — what a PS/2 keyboard sends from that key position.
/// The machine's layout is sw/keymap.asm's business, as on the bench.
fn set2(sc: Scancode) -> Option<(u8, bool)> {
    use Scancode::*;
    Some(match sc {
        A => (0x1C, false), B => (0x32, false), C => (0x21, false),
        D => (0x23, false), E => (0x24, false), F => (0x2B, false),
        G => (0x34, false), H => (0x33, false), I => (0x43, false),
        J => (0x3B, false), K => (0x42, false), L => (0x4B, false),
        M => (0x3A, false), N => (0x31, false), O => (0x44, false),
        P => (0x4D, false), Q => (0x15, false), R => (0x2D, false),
        S => (0x1B, false), T => (0x2C, false), U => (0x3C, false),
        V => (0x2A, false), W => (0x1D, false), X => (0x22, false),
        Y => (0x35, false), Z => (0x1A, false),
        Num0 => (0x45, false), Num1 => (0x16, false),
        Num2 => (0x1E, false), Num3 => (0x26, false),
        Num4 => (0x25, false), Num5 => (0x2E, false),
        Num6 => (0x36, false), Num7 => (0x3D, false),
        Num8 => (0x3E, false), Num9 => (0x46, false),
        F1 => (0x05, false), F2 => (0x06, false), F3 => (0x04, false),
        F4 => (0x0C, false), F5 => (0x03, false), F6 => (0x0B, false),
        F7 => (0x83, false), F8 => (0x0A, false), F9 => (0x01, false),
        F10 => (0x09, false),
        Grave => (0x0E, false), Minus => (0x4E, false),
        Equals => (0x55, false), Backslash => (0x5D, false),
        Backspace => (0x66, false), Space => (0x29, false),
        Tab => (0x0D, false), Return => (0x5A, false),
        Escape => (0x76, false), CapsLock => (0x58, false),
        LeftBracket => (0x54, false), RightBracket => (0x5B, false),
        Semicolon => (0x4C, false), Apostrophe => (0x52, false),
        Comma => (0x41, false), Period => (0x49, false),
        Slash => (0x4A, false),
        LShift => (0x12, false), RShift => (0x59, false),
        LCtrl => (0x14, false), LAlt => (0x11, false),
        Up => (0x75, true), Down => (0x72, true),
        Left => (0x6B, true), Right => (0x74, true),
        Home => (0x6C, true), End => (0x69, true),
        PageUp => (0x7D, true), PageDown => (0x7A, true),
        Insert => (0x70, true), Delete => (0x71, true),
        _ => return None,
    })
}

/// In text mode these keys' characters arrive as SDL text input with
/// the user's layout applied — so the physical path must not also fire
/// for them, or every key would type twice.
fn is_char_key(sc: Scancode) -> bool {
    use Scancode::*;
    matches!(sc,
        A | B | C | D | E | F | G | H | I | J | K | L | M | N | O | P
        | Q | R | S | T | U | V | W | X | Y | Z
        | Num0 | Num1 | Num2 | Num3 | Num4 | Num5 | Num6 | Num7 | Num8
        | Num9 | Space | Grave | Minus | Equals | Backslash
        | LeftBracket | RightBracket | Semicolon | Apostrophe | Comma
        | Period | Slash)
}

fn send_key(m: &mut Machine, code: u8, ext: bool, pressed: bool) {
    let mut b = Vec::with_capacity(3);
    if ext {
        b.push(0xE0);
    }
    if !pressed {
        b.push(0xF0);
    }
    b.push(code);
    m.bus.kbd.feed(&b);
}

// ------------------------------------------------------------- audio

struct Speaker {
    queue: Arc<Mutex<VecDeque<u8>>>,
    step: f64,
    acc: f64,
    cur: u8,
}

impl AudioCallback for Speaker {
    type Channel = f32;

    fn callback(&mut self, out: &mut [f32]) {
        let mut q = self.queue.lock().unwrap();
        for v in out.iter_mut() {
            self.acc += self.step;
            while self.acc >= 1.0 {
                self.acc -= 1.0;
                if let Some(s) = q.pop_front() {
                    self.cur = s;
                }
            }
            *v = (self.cur as f32 - 128.0) / 128.0;
        }
    }
}

/// Unsigned 8-bit mono at the machine's own sample rate — what the
/// speaker heard, byte for byte, through the hound crate.
fn save_wav(path: &str, samples: &[u8]) {
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate: SND_HZ.round() as u32,
        bits_per_sample: 8,
        sample_format: hound::SampleFormat::Int,
    };
    let write = || -> Result<(), hound::Error> {
        let mut w = hound::WavWriter::create(path, spec)?;
        for &s in samples {
            w.write_sample((s as i16 - 128) as i8)?;
        }
        w.finalize()
    };
    match write() {
        Ok(()) => eprintln!("wrote {}", path),
        Err(e) => eprintln!("cannot write {}: {}", path, e),
    }
}

/// The frame as a truecolour PNG, through the png crate.
fn save_png(path: &str, fb: &[u16]) {
    let mut rgb = Vec::with_capacity(H_VIS * V_VIS * 3);
    for &px in fb {
        rgb.push(((px >> 8) & 0xF) as u8 * 17);
        rgb.push(((px >> 4) & 0xF) as u8 * 17);
        rgb.push((px & 0xF) as u8 * 17);
    }
    let write = || -> Result<(), png::EncodingError> {
        let file = std::fs::File::create(path)
            .map_err(png::EncodingError::IoError)?;
        let mut enc = png::Encoder::new(std::io::BufWriter::new(file),
                                        H_VIS as u32, V_VIS as u32);
        enc.set_color(png::ColorType::Rgb);
        enc.set_depth(png::BitDepth::Eight);
        enc.write_header()?.write_image_data(&rgb)
    };
    match write() {
        Ok(()) => eprintln!("wrote {}", path),
        Err(e) => eprintln!("cannot write {}: {}", path, e),
    }
}

// -------------------------------------------------------------- run

pub fn run(args: &Args) {
    let rom = crate::load_rom(args.rom.as_ref().unwrap_or_else(|| {
        die("+emu needs +rom=".into())
    }));
    let font = crate::load_font(args.font.as_ref().unwrap_or_else(|| {
        die("+emu needs +font=".into())
    }));
    let flash = args.flash.as_ref().map(|p| std::fs::read(p).unwrap());
    let keys_mode = args.keys.as_deref().unwrap_or("text");
    if !["text", "raw", "both"].contains(&keys_mode) {
        die("+keys= takes text, raw or both".into());
    }

    let mut m = Machine::new(rom, flash);
    m.renderer = Some(Renderer::new(font));
    let keymap = args.keymap.as_ref().map(|p| load_keymap(p))
        .unwrap_or_default();

    // ---- SDL: window, renderer, audio, events
    let sdl = sdl2::init().unwrap_or_else(|e| die(e));
    let video = sdl.video().unwrap_or_else(|e| die(e));
    let window = video
        .window("COOL8", (H_VIS * 2) as u32, (V_VIS * 2) as u32)
        .position_centered()
        .resizable()
        .build()
        .unwrap_or_else(|e| die(e.to_string()));
    let mut canvas = window
        .into_canvas()
        .accelerated()
        .present_vsync()
        .build()
        .unwrap_or_else(|e| die(e.to_string()));
    canvas
        .set_logical_size(H_VIS as u32, V_VIS as u32)
        .unwrap_or_else(|e| die(e.to_string()));
    let creator = canvas.texture_creator();
    let mut tex = creator
        .create_texture_streaming(PixelFormatEnum::RGB24, H_VIS as u32,
                                  V_VIS as u32)
        .unwrap_or_else(|e| die(e.to_string()));

    let queue: Arc<Mutex<VecDeque<u8>>> = Arc::default();
    let audio = sdl.audio().ok();
    let device = audio.as_ref().and_then(|a| {
        let want = AudioSpecDesired {
            freq: Some(SND_HZ.round() as i32),
            channels: Some(1),
            samples: None,
        };
        a.open_playback(None, &want, |spec| Speaker {
            queue: queue.clone(),
            step: SND_HZ / spec.freq as f64,
            acc: 0.0,
            cur: 128,
        })
        .ok()
    });
    match &device {
        Some(d) => d.resume(),
        None => eprintln!("no audio device; running silent"),
    }

    if keys_mode == "raw" {
        video.text_input().stop();
    } else {
        video.text_input().start();
    }

    let mut events = sdl.event_pump().unwrap_or_else(|e| die(e));
    let mut typed: VecDeque<u8> = VecDeque::new();
    let mut wav: Vec<u8> = Vec::new();
    let mut rgb = vec![0u8; H_VIS * V_VIS * 3];
    let mut shot = 0;

    'main: loop {
        for ev in events.poll_iter() {
            match ev {
                Event::Quit { .. } => break 'main,

                Event::KeyDown { keycode, scancode, keymod, repeat, .. } => {
                    let alt = keymod
                        .intersects(Mod::LALTMOD | Mod::RALTMOD);
                    let ctrl = keymod
                        .intersects(Mod::LCTRLMOD | Mod::RCTRLMOD);
                    match (keycode, scancode) {
                        (Some(Keycode::Return), _) if alt => {
                            if !repeat {
                                let fs = canvas.window().fullscreen_state();
                                let to = if fs == FullscreenType::Off {
                                    FullscreenType::Desktop
                                } else {
                                    FullscreenType::Off
                                };
                                canvas.window_mut().set_fullscreen(to).ok();
                            }
                        }
                        (Some(Keycode::F11), _) if !repeat => {
                            m.cpu.pulse_nmi();
                        }
                        (Some(Keycode::F12), _) if !repeat => {
                            shot += 1;
                            let p = format!("cool8-shot-{}.png", shot);
                            save_png(&p, &m.renderer.as_ref().unwrap().fb);
                        }
                        // Ctrl+Pause is the break chord; Windows and
                        // SDL spell it Cancel, other platforms Pause.
                        (Some(Keycode::Cancel), _) |
                        (Some(Keycode::Pause), _) if !repeat => {
                            if ctrl || keycode == Some(Keycode::Cancel) {
                                m.cpu.pulse_nmi();
                            }
                        }
                        (_, Some(sc)) => {
                            if keys_mode != "raw" && is_char_key(sc) {
                                continue; // arrives as text input
                            }
                            if let Some((code, ext)) = set2(sc) {
                                // SDL's own key repeat: a held key
                                // re-sends its make, no break between,
                                // which is the PS/2 typematic.
                                send_key(&mut m, code, ext, true);
                            }
                        }
                        _ => {}
                    }
                }

                Event::KeyUp { scancode: Some(sc), .. } => {
                    if keys_mode != "raw" && is_char_key(sc) {
                        continue;
                    }
                    if let Some((code, ext)) = set2(sc) {
                        send_key(&mut m, code, ext, false);
                    }
                }

                Event::TextInput { text, .. } => {
                    for c in text.chars() {
                        if (c as u32) < 0x100 {
                            typed.push_back(c as u32 as u8);
                        }
                    }
                }

                Event::MouseButtonDown {
                    mouse_btn: MouseButton::Right, ..
                } => {
                    if let Ok(text) = video.clipboard().clipboard_text() {
                        for c in text.chars() {
                            let b = if c == '\n' { b'\r' }
                                    else { c as u32 as u8 };
                            if (c as u32) < 0x100 {
                                typed.push_back(b);
                            }
                        }
                    }
                }

                _ => {}
            }
        }

        // Typed and pasted characters share one queue, fed a character
        // a frame through the machine's keymap so the 16-byte PS/2
        // FIFO cannot overrun.
        if m.bus.kbd.q.len() < 8 {
            if let Some(ch) = typed.pop_front() {
                if keys_mode == "both" {
                    m.bus.uart.feed(&[ch]);
                }
                if let Some(&(code, shifted)) = keymap.get(&ch) {
                    let mut b = Vec::new();
                    if shifted {
                        b.push(0x12);
                    }
                    b.extend([code, 0xF0, code]);
                    if shifted {
                        b.extend([0xF0, 0x12]);
                    }
                    m.bus.kbd.feed(&b);
                }
            }
        }

        let target = m.frames + 1;
        while m.frames < target {
            m.tick();
        }

        {
            let mut q = queue.lock().unwrap();
            if args.wav.is_some() {
                wav.extend(m.bus.sound.samples.iter());
            }
            q.extend(m.bus.sound.samples.drain(..));
            let cap = (SND_HZ / 2.0) as usize;
            while q.len() > cap {
                q.pop_front();
            }
        }

        let fb = &m.renderer.as_ref().unwrap().fb;
        for (dst, &px) in rgb.chunks_exact_mut(3).zip(fb.iter()) {
            dst[0] = ((px >> 8) & 0xF) as u8 * 17;
            dst[1] = ((px >> 4) & 0xF) as u8 * 17;
            dst[2] = (px & 0xF) as u8 * 17;
        }
        tex.update(None, &rgb, H_VIS * 3)
            .unwrap_or_else(|e| die(e.to_string()));
        canvas.clear();
        canvas.copy(&tex, None, None)
            .unwrap_or_else(|e| die(e.to_string()));
        canvas.present();
    }

    // SAVE survives the window closing: a dirtied flash goes back to
    // its image, as cool8run.py's flush does.
    if m.bus.flash.dirty {
        if let Some(p) = args.flash.as_ref() {
            match std::fs::write(p, &m.bus.flash.mem) {
                Ok(()) => eprintln!("flash written back to {}", p),
                Err(e) => eprintln!("cannot write {}: {}", p, e),
            }
        }
    }
    if let Some(p) = args.wav.as_ref() {
        save_wav(p, &wav);
    }
}
