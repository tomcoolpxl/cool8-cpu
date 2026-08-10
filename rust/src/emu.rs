// The machine in a window — the Rust counterpart of tools/cool8run.py,
// with the scanline renderer of render.rs behind the glass instead of a
// whole-frame snapshot, so raster splits and mid-frame palette work
// look on the monitor the way they look on the board.
//
// Feature-gated (`--features gui`): the parity suite's build stays
// dependency-free, and only this file touches minifb and cpal.
//
// ## Pacing
//
// One machine frame per window update, with the window limited to the
// machine's own 60 Hz. Audio is the drift-taker: the machine produces
// samples at SND_HZ (8.375 MHz / 256 ≈ 32.7 kHz) into a queue the
// audio callback resamples to the device rate; if the queue runs dry
// the callback holds the last level (silence-shaped, inaudible), and
// if it backs up past half a second the excess is dropped.
//
// ## The keyboard
//
// Host keys become Set 2 scancodes — a make on press, a break on
// release, E0-prefixed where the real key is — and go into the same
// PS/2 FIFO the machine's tests feed. The mapping is the physical
// US-layout table a PS/2 keyboard implements; the *machine's* layout
// is sw/keymap.asm's business, exactly as on the bench.

use crate::machine::Machine;
use crate::render::{Renderer, H_VIS, V_VIS};
use crate::Args;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use minifb::{Key, MouseButton, Scale, ScaleMode, Window, WindowOptions};
use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};

const SND_HZ: f64 = 8_375_000.0 / 256.0;

#[cfg(target_os = "windows")]
fn screen_size() -> (usize, usize) {
    #[link(name = "user32")]
    extern "system" {
        fn GetSystemMetrics(n: i32) -> i32;
    }
    unsafe { (GetSystemMetrics(0) as usize, GetSystemMetrics(1) as usize) }
}

#[cfg(not(target_os = "windows"))]
fn screen_size() -> (usize, usize) {
    (1920, 1080) // minifb cannot ask; a common panel, letterboxed anyway
}

/// The buffer is always 640x480; the window scales it with the aspect
/// ratio kept, so "fullscreen" is a borderless window the size of the
/// screen and the toggle is a window swap, not a mode set.
fn make_window(fullscreen: bool) -> Window {
    let (w, h) = if fullscreen {
        screen_size()
    } else {
        (H_VIS * 2, V_VIS * 2)
    };
    let mut win = Window::new(
        "COOL8",
        w,
        h,
        WindowOptions {
            resize: true,
            scale: Scale::X1,
            scale_mode: ScaleMode::AspectRatioStretch,
            borderless: fullscreen,
            ..WindowOptions::default()
        },
    )
    .unwrap_or_else(|e| {
        eprintln!("cannot open a window: {}", e);
        std::process::exit(1);
    });
    if fullscreen {
        win.set_position(0, 0);
    }
    win.set_target_fps(60);
    win
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

/// Set 2 make code for a host key, with its E0 prefix flag.
fn scancode(k: Key) -> Option<(u8, bool)> {
    use Key::*;
    Some(match k {
        A => (0x1C, false), B => (0x32, false), C => (0x21, false),
        D => (0x23, false), E => (0x24, false), F => (0x2B, false),
        G => (0x34, false), H => (0x33, false), I => (0x43, false),
        J => (0x3B, false), K => (0x42, false), L => (0x4B, false),
        M => (0x3A, false), N => (0x31, false), O => (0x44, false),
        P => (0x4D, false), Q => (0x15, false), R => (0x2D, false),
        S => (0x1B, false), T => (0x2C, false), U => (0x3C, false),
        V => (0x2A, false), W => (0x1D, false), X => (0x22, false),
        Y => (0x35, false), Z => (0x1A, false),
        Key0 => (0x45, false), Key1 => (0x16, false), Key2 => (0x1E, false),
        Key3 => (0x26, false), Key4 => (0x25, false), Key5 => (0x2E, false),
        Key6 => (0x36, false), Key7 => (0x3D, false), Key8 => (0x3E, false),
        Key9 => (0x46, false),
        F1 => (0x05, false), F2 => (0x06, false), F3 => (0x04, false),
        F4 => (0x0C, false), F5 => (0x03, false), F6 => (0x0B, false),
        F7 => (0x83, false), F8 => (0x0A, false), F9 => (0x01, false),
        F10 => (0x09, false), F11 => (0x78, false), F12 => (0x07, false),
        Backquote => (0x0E, false), Minus => (0x4E, false),
        Equal => (0x55, false), Backslash => (0x5D, false),
        Backspace => (0x66, false), Space => (0x29, false),
        Tab => (0x0D, false), Enter => (0x5A, false),
        Escape => (0x76, false), CapsLock => (0x58, false),
        LeftBracket => (0x54, false), RightBracket => (0x5B, false),
        Semicolon => (0x4C, false), Apostrophe => (0x52, false),
        Comma => (0x41, false), Period => (0x49, false),
        Slash => (0x4A, false),
        LeftShift => (0x12, false), RightShift => (0x59, false),
        LeftCtrl => (0x14, false), LeftAlt => (0x11, false),
        Up => (0x75, true), Down => (0x72, true),
        Left => (0x6B, true), Right => (0x74, true),
        Home => (0x6C, true), End => (0x69, true),
        PageUp => (0x7D, true), PageDown => (0x7A, true),
        Insert => (0x70, true), Delete => (0x71, true),
        _ => return None,
    })
}

fn feed_key(m: &mut Machine, k: Key, pressed: bool) {
    if let Some((code, ext)) = scancode(k) {
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
}

fn audio_stream(queue: Arc<Mutex<VecDeque<u8>>>) -> Option<cpal::Stream> {
    let device = cpal::default_host().default_output_device()?;
    let config = device.default_output_config().ok()?;
    let rate = config.sample_rate().0 as f64;
    let channels = config.channels() as usize;
    let step = SND_HZ / rate;
    let mut acc = 0.0f64;
    let mut cur = 128u8;
    let stream = device
        .build_output_stream(
            &config.into(),
            move |out: &mut [f32], _: &cpal::OutputCallbackInfo| {
                let mut q = queue.lock().unwrap();
                for frame in out.chunks_mut(channels) {
                    acc += step;
                    while acc >= 1.0 {
                        acc -= 1.0;
                        if let Some(s) = q.pop_front() {
                            cur = s;
                        }
                    }
                    let v = (cur as f32 - 128.0) / 128.0;
                    for c in frame.iter_mut() {
                        *c = v;
                    }
                }
            },
            |e| eprintln!("audio: {}", e),
            None,
        )
        .ok()?;
    stream.play().ok()?;
    Some(stream)
}

pub fn run(args: &Args) {
    let rom = crate::load_rom(args.rom.as_ref().unwrap_or_else(|| {
        eprintln!("+emu needs +rom=");
        std::process::exit(2);
    }));
    let font = crate::load_font(args.font.as_ref().unwrap_or_else(|| {
        eprintln!("+emu needs +font=");
        std::process::exit(2);
    }));
    let flash = args.flash.as_ref().map(|p| std::fs::read(p).unwrap());

    let mut m = Machine::new(rom, flash);
    m.renderer = Some(Renderer::new(font));

    let queue: Arc<Mutex<VecDeque<u8>>> = Arc::new(Mutex::new(VecDeque::new()));
    let _stream = audio_stream(queue.clone());
    if _stream.is_none() {
        eprintln!("no audio device; running silent");
    }

    let keymap = args.keymap.as_ref().map(|p| load_keymap(p))
        .unwrap_or_default();
    let mut clipboard = arboard::Clipboard::new().ok();
    let mut paste: VecDeque<u8> = VecDeque::new();
    let mut right_was_down = false;

    let mut fullscreen = false;
    let mut window = make_window(fullscreen);

    let mut buf = vec![0u32; H_VIS * V_VIS];
    while window.is_open() {
        let alt = window.is_key_down(Key::LeftAlt)
            || window.is_key_down(Key::RightAlt);
        for k in window.get_keys_pressed(minifb::KeyRepeat::No) {
            if alt && k == Key::Enter {
                fullscreen = !fullscreen;
                window = make_window(fullscreen);
            } else {
                feed_key(&mut m, k, true);
            }
        }
        for k in window.get_keys_released() {
            feed_key(&mut m, k, false);
        }

        // Right click pastes the clipboard, as the Python front end
        // does: typed at the machine's keyboard, a character a frame,
        // so the 16-byte FIFO is never overrun.
        let right = window.get_mouse_down(MouseButton::Right);
        if right && !right_was_down {
            if let Some(cb) = clipboard.as_mut() {
                if let Ok(text) = cb.get_text() {
                    for c in text.chars() {
                        let b = if c == '\n' { b'\r' } else { c as u32 as u8 };
                        if (c as u32) < 0x100 {
                            paste.push_back(b);
                        }
                    }
                }
            }
        }
        right_was_down = right;
        if m.bus.kbd.q.len() < 8 {
            if let Some(ch) = paste.pop_front() {
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
            q.extend(m.bus.sound.samples.drain(..));
            let cap = (SND_HZ / 2.0) as usize;
            while q.len() > cap {
                q.pop_front();
            }
        }

        let fb = &m.renderer.as_ref().unwrap().fb;
        for (dst, &px) in buf.iter_mut().zip(fb.iter()) {
            let r = ((px >> 8) & 0xF) as u32 * 17;
            let g = ((px >> 4) & 0xF) as u32 * 17;
            let b = (px & 0xF) as u32 * 17;
            *dst = r << 16 | g << 8 | b;
        }
        window.update_with_buffer(&buf, H_VIS, V_VIS).unwrap();
    }
}
