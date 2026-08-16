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
//     F1          warm restart — the scancodes for the machine's
//                 Ctrl+Esc, which Windows keeps for the Start menu
//     F10         cold restart — Ctrl+Shift+Esc, likewise claimed by
//                 the host for its task manager
//     F11         the break button, SW[0] — an NMI, as the board's is
//     Ctrl+Pause  the same; SDL reports the chord as Cancel and both
//                 spellings are handled
//     F12         write the screen to a PNG in the cwd
//     Alt+Enter   fullscreen, SDL's own desktop mode
//     right click paste the clipboard, typed through the keymap
//
// F1 and F10 send the chord's raw scancodes rather than doing the
// restart themselves, so what the machine sees is a keyboard and the
// path under test is the real one.

use crate::machine::Machine;
use crate::render::{Renderer, H_VIS, V_VIS};
use crate::Args;
use sdl2::audio::{AudioCallback, AudioSpecDesired};
use sdl2::event::Event;
use sdl2::keyboard::{Keycode, Mod, Scancode};
use sdl2::mouse::MouseButton;
use sdl2::video::{FullscreenType, GLProfile};
use glow::HasContext;
use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::Instant;

const SND_HZ: f64 = 8_375_000.0 / 256.0;
/// The machine's own frame rate: 266 cycles a line, 525 lines a frame.
const FRAME_HZ: f64 = 8_375_000.0 / (266.0 * 525.0);

fn die(msg: String) -> ! {
    eprintln!("{}", msg);
    std::process::exit(1);
}

/// Phosphor's Private Use Area, which is where its icons live.
static ICON_RANGE: [u32; 3] = [0xE000, 0xF8FF, 0];

/// The text face and the icon face, merged into one atlas.
///
/// **Merging is the toolkit's job and it is done by asking**: two
/// sources in one `add_font` call, and an icon is then simply a
/// character in a string — no second draw path, no atlas packing here.
/// Phosphor regular is MIT and vendored at `assets/icons/`.
fn fonts(ctx: &mut imgui::Context) {
    const ICONS: &[u8] =
        include_bytes!("../../assets/icons/Phosphor.ttf");
    ctx.fonts().add_font(&[
        imgui::FontSource::DefaultFontData { config: None },
        imgui::FontSource::TtfData {
            data: ICONS,
            size_pixels: 15.0,
            config: Some(imgui::FontConfig {
                glyph_ranges:
                    imgui::FontGlyphRanges::from_slice(&ICON_RANGE),
                // The icons sit a shade low against the text baseline.
                glyph_offset: [0.0, 3.0],
                ..Default::default()
            }),
        },
    ]);
}

/// Where the machine's picture goes: centred above the bar, whole
/// pixels, aspect kept.
///
/// This is what `set_logical_size` used to do. It is done here now
/// because the bar owns the bottom of the window and SDL's scaler has
/// no idea it exists.
fn picture_rect(vp: [f32; 2], bar: f32) -> ([f32; 2], [f32; 2]) {
    let avail_h = (vp[1] - bar).max(1.0);
    let scale = (vp[0] / H_VIS as f32).min(avail_h / V_VIS as f32);
    let (w, h) = (H_VIS as f32 * scale, V_VIS as f32 * scale);
    let x = (vp[0] - w) * 0.5;
    let y = (avail_h - h) * 0.5;
    ([x, y], [x + w, y + h])
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
    // **A GL context, because the taskbar is drawn by a toolkit.**
    // SDL2 keeps every job it had -- window, speaker, clipboard,
    // scancodes -- and makes the context itself; only the blit moves,
    // from SDL_Renderer's scaler to a textured quad ImGui draws. The
    // picture is letterboxed by hand now (`picture_rect`), which is
    // what `set_logical_size` used to do.
    {
        let a = video.gl_attr();
        a.set_context_profile(GLProfile::Core);
        a.set_context_version(3, 3);
    }
    let mut window = video
        .window("COOL8", (H_VIS * 2) as u32, (V_VIS * 2) as u32 + 68)
        .position_centered()
        .resizable()
        .opengl()
        .build()
        .unwrap_or_else(|e| die(e.to_string()));
    let _gl_ctx = window
        .gl_create_context()
        .unwrap_or_else(|e| die(e.to_string()));
    window.subsystem().gl_set_swap_interval(1).ok();
    let gl = unsafe {
        glow::Context::from_loader_function(|s| {
            video.gl_get_proc_address(s) as *const _
        })
    };

    let mut imgui = imgui::Context::create();
    imgui.set_ini_filename(None);      // no stray .ini beside the binary
    imgui.io_mut().config_flags |=
        imgui::ConfigFlags::NAV_ENABLE_KEYBOARD;
    fonts(&mut imgui);
    let mut platform = imgui_sdl2_support::SdlPlatform::new(&mut imgui);
    // **`output_srgb` is false, and that is the whole point.**
    // `AutoRenderer` passes true, whose shader applies a linear->sRGB
    // curve on the way out. SDL's framebuffer does no conversion of its
    // own, so the curve lands once too often and every colour is
    // lighter than the machine made it -- which is exactly how this
    // window differed from a frame grabbed out of memory. Holding the
    // texture map ourselves is the price of being able to say false.
    let mut tex_map = imgui_glow_renderer::SimpleTextureMap::default();
    let mut ui_renderer = imgui_glow_renderer::Renderer::new(
        &gl, &mut imgui, &mut tex_map, false)
        .unwrap_or_else(|e| die(e.to_string()));

    // The machine's picture, as one texture ImGui is handed each frame.
    let screen = unsafe {
        let g = &gl;
        let t = g.create_texture().unwrap_or_else(|e| die(e));
        g.bind_texture(glow::TEXTURE_2D, Some(t));
        // NEAREST: this is a machine with square pixels and no opinion
        // about how a filter would like them blended.
        g.tex_parameter_i32(glow::TEXTURE_2D, glow::TEXTURE_MIN_FILTER,
                            glow::NEAREST as i32);
        g.tex_parameter_i32(glow::TEXTURE_2D, glow::TEXTURE_MAG_FILTER,
                            glow::NEAREST as i32);
        g.tex_parameter_i32(glow::TEXTURE_2D, glow::TEXTURE_WRAP_S,
                            glow::CLAMP_TO_EDGE as i32);
        g.tex_parameter_i32(glow::TEXTURE_2D, glow::TEXTURE_WRAP_T,
                            glow::CLAMP_TO_EDGE as i32);
        g.tex_image_2d(glow::TEXTURE_2D, 0, glow::RGB8 as i32,
                       H_VIS as i32, V_VIS as i32, 0, glow::RGB,
                       glow::UNSIGNED_BYTE, None);
        t
    };
    // `AutoRenderer` carries a `SimpleTextureMap`, where the id a draw
    // list wants *is* the GL texture name -- there is nothing to
    // register, which is why this is a cast and not a lookup.
    let screen_id = imgui::TextureId::new(screen.0.get() as usize);

    let discs = args.discs.as_ref()
        .map(|p| crate::bar::load_catalogue(p))
        .unwrap_or_default();
    let mut disc_sel: usize = 0;
    // **Waiting on the machine, not on a stopwatch.** `+idle=` carries
    // the three symbols `Machine::is_idle` wants -- the keyboard wait's
    // address and the input ring's head and tail -- so the launcher can
    // be told a demo the instant BASIC is listening, rather than after
    // a guessed number of frames that is either wrong or slow. Same
    // predicate the `settle` command uses for the suites.
    let idle: Option<(u16, usize, usize)> = args.idle.as_ref()
        .and_then(|s| {
            let n: Vec<usize> = s.split(',')
                .filter_map(|f| f.trim().parse().ok()).collect();
            (n.len() == 3).then(|| (n[0] as u16, n[1], n[2]))
        });
    let mut launch: Option<crate::bar::Entry> = None;
    let mut booted = false;

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

    // The machine runs at its own 59.97 Hz against the wall clock;
    // vsync only decides how often the picture is *shown*. Pacing by
    // presented frames ran the whole machine — cursor blink included —
    // at whatever the monitor refreshes at, which on a 144 Hz panel
    // was a very nervous cursor.
    let started = Instant::now();
    let mut machine_frames: u64 = 0;

    'main: loop {
        for ev in events.poll_iter() {
            // **The toolkit sees every event, and may claim it.** A
            // click on a button or a typed character in the combo box
            // must not also reach the machine, or naming a disc types
            // its name into BASIC.
            platform.handle_event(&mut imgui, &ev);
            let ui_keys = imgui.io().want_capture_keyboard;
            match ev {
                Event::Quit { .. } => break 'main,

                Event::KeyDown { keycode, scancode, keymod, repeat, .. } => {
                    if ui_keys { continue; }
                    let alt = keymod
                        .intersects(Mod::LALTMOD | Mod::RALTMOD);
                    let ctrl = keymod
                        .intersects(Mod::LCTRLMOD | Mod::RCTRLMOD);
                    match (keycode, scancode) {
                        (Some(Keycode::Return), _) if alt => {
                            if !repeat {
                                let fs = window.fullscreen_state();
                                let to = if fs == FullscreenType::Off {
                                    FullscreenType::Desktop
                                } else {
                                    FullscreenType::Off
                                };
                                window.set_fullscreen(to).ok();
                            }
                        }
                        (Some(Keycode::F11), _) if !repeat => {
                            m.cpu.pulse_nmi();
                        }
                        // **The restart chords, on keys the host will
                        // let us have.** The machine's own chords are
                        // Ctrl+Esc and Ctrl+Shift+Esc (D54), decoded in
                        // cool8_ps2 before software sees anything --
                        // which is exactly right on the board, where no
                        // operating system stands between the keyboard
                        // and the machine, and impossible here, because
                        // Windows claims both for the Start menu and
                        // the task manager and never delivers them.
                        //
                        // So the scancodes are injected instead of the
                        // chord being changed: the machine receives the
                        // same bytes a real keyboard would send and
                        // cannot tell the difference, and the hardware
                        // keeps a convention chosen for the hardware
                        // rather than one bent around a host.
                        (Some(Keycode::F1), _) if !repeat => {
                            m.bus.kbd.feed(&[0x14, 0x76, 0xF0, 0x76,
                                             0xF0, 0x14]);
                        }
                        (Some(Keycode::F10), _) if !repeat => {
                            m.bus.kbd.feed(&[0x14, 0x12, 0x76, 0xF0, 0x76,
                                             0xF0, 0x12, 0xF0, 0x14]);
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
                    if ui_keys { continue; }
                    if keys_mode != "raw" && is_char_key(sc) {
                        continue;
                    }
                    // The keys this front end keeps for itself never
                    // reached the machine as a make, so they must not
                    // arrive as a break either -- an unpaired release
                    // is a key the decoder never saw go down.
                    if matches!(sc, Scancode::F1 | Scancode::F10
                                  | Scancode::F11 | Scancode::F12) {
                        continue;
                    }
                    if let Some((code, ext)) = set2(sc) {
                        send_key(&mut m, code, ext, false);
                    }
                }

                Event::TextInput { text, .. } => {
                    if ui_keys { continue; }
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

        let due = (started.elapsed().as_secs_f64() * FRAME_HZ) as u64;
        if due > machine_frames + 8 {
            // A stall (window drag, a debugger): skip, don't sprint.
            machine_frames = due.saturating_sub(1);
        }
        while machine_frames < due {
            let target = m.frames + 1;
            while m.frames < target {
                m.tick();
                // The PC only rests at the idle label; sampling once a
                // frame would miss it, so the test rides the tick loop
                // exactly as `settle` does. It costs one compare, and
                // only while a launch is actually pending.
                if launch.is_some() && !booted {
                    if let Some((pc, h, t)) = idle {
                        if m.is_idle(pc, h, t) {
                            booted = true;
                        }
                    }
                }
            }
            machine_frames += 1;
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

        // **The launch, once the restarted machine has a prompt.** A
        // cold restart is the whole boot -- RAM wipe, fonts into VRAM,
        // banner -- so the typing waits for it in machine frames, which
        // is the clock that actually governs it. Then it goes through
        // the same queue a paste does, so the machine is typed at and
        // knows nothing about any of this.
        if booted {
            if let Some(e) = launch.take() {
                for ch in format!("DRIVE {}\rLOAD \"{}\"\rRUN\r",
                                  e.drive, crate::bar::stem(&e.name))
                    .bytes()
                {
                    typed.push_back(ch);
                }
            }
            booted = false;
        }

        let fb = &m.renderer.as_ref().unwrap().fb;
        for (dst, &px) in rgb.chunks_exact_mut(3).zip(fb.iter()) {
            dst[0] = ((px >> 8) & 0xF) as u8 * 17;
            dst[1] = ((px >> 4) & 0xF) as u8 * 17;
            dst[2] = (px & 0xF) as u8 * 17;
        }
        unsafe {
            let g = &gl;
            g.bind_texture(glow::TEXTURE_2D, Some(screen));
            g.tex_sub_image_2d(glow::TEXTURE_2D, 0, 0, 0, H_VIS as i32,
                               V_VIS as i32, glow::RGB,
                               glow::UNSIGNED_BYTE,
                               glow::PixelUnpackData::Slice(&rgb));
        }

        platform.prepare_frame(&mut imgui, &window, &events);
        let full = window.fullscreen_state() != FullscreenType::Off;
        let bar_h = if full { 0.0 } else { crate::bar::BAR_H };
        let ui = imgui.new_frame();
        let (p0, p1) = picture_rect(ui.io().display_size, bar_h);
        // The picture is the backdrop, not a window: it sits under
        // everything and cannot be dragged, focused or scrolled.
        ui.get_background_draw_list()
            .add_image(screen_id, p0, p1)
            .build();
        // **No bar in fullscreen**, which is what fullscreen is for.
        let act = if full {
            crate::bar::Act::None
        } else {
            crate::bar::draw(ui, &discs, &mut disc_sel, full)
        };
        match act {
            crate::bar::Act::Warm => crate::bar::warm(&mut m),
            crate::bar::Act::Cold => crate::bar::cold(&mut m),
            crate::bar::Act::Break => m.cpu.pulse_nmi(),
            crate::bar::Act::Shot => {
                shot += 1;
                let p = format!("cool8-shot-{}.png", shot);
                save_png(&p, &m.renderer.as_ref().unwrap().fb);
            }
            crate::bar::Act::Fullscreen => {
                window.set_fullscreen(FullscreenType::Desktop).ok();
            }
            crate::bar::Act::Launch(e) => {
                crate::bar::cold(&mut m);
                typed.clear();
                booted = false;
                // Without the symbols there is nothing to wait for, so
                // say so rather than typing into a booting machine and
                // leaving the user to wonder where the keystrokes went.
                if idle.is_some() {
                    launch = Some(e);
                } else {
                    eprintln!("no +idle= symbols: cannot tell when the \
                               machine is ready, so not launching");
                }
            }
            crate::bar::Act::None => {}
        }

        let draw_data = imgui.render();
        unsafe {
            gl.clear_color(0.0, 0.0, 0.0, 1.0);
            gl.clear(glow::COLOR_BUFFER_BIT);
        }
        ui_renderer.render(&gl, &tex_map, draw_data)
            .unwrap_or_else(|e| die(e.to_string()));
        window.gl_swap_window();
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
