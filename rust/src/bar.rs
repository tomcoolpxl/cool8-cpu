// bar.rs -- the window's taskbar: the keys this front end keeps, as
// buttons, and the discs in the flash image, as a menu.
//
// ## Nothing here draws a widget
//
// Dear ImGui draws the buttons, the hover tooltips, the combo box and
// the text; `imgui-sdl2-support` turns SDL events into its input and
// `imgui-glow-renderer` puts it on the screen. This file decides what
// the bar contains and what each control does to the machine, and that
// is all it decides.
//
// **Dear ImGui and not egui because that set composes at current
// versions**: egui is 0.36, `egui_sdl2_gl` pins egui ~0.33 and
// `egui-phosphor` wants ^0.35, so an egui bar could only be had by
// holding egui back. The three imgui crates ship together and the SDL2
// one asks for sdl2 ^0.37, which is the version this crate already had.
//
// ## The icons are a font, not artwork
//
// Phosphor regular (MIT), vendored at `assets/icons/Phosphor.ttf` and
// merged into ImGui's atlas beside the text face, so an icon is a
// character in a string and the toolkit does the rest. The codepoints
// below are Phosphor's own, taken from its stylesheet rather than
// guessed -- they are Private Use Area, so nothing else can be meant.
//
// ## What the bar does not do
//
// **It never reads the flash image.** The disc catalogue arrives as a
// file the launcher wrote with `tools/cool8disk.py` (`+discs=`), the
// same arrangement the keymap has, because the directory format is that
// tool's and a second walk written here would drift from it.

use crate::machine::Machine;

/// Phosphor's own codepoints, from its stylesheet.
pub const IC_WARM: &str = "\u{e038}"; // arrow-counter-clockwise
pub const IC_COLD: &str = "\u{e3da}"; // power
pub const IC_BREAK: &str = "\u{e57e}"; // hand-palm
pub const IC_SHOT: &str = "\u{e10e}"; // camera
pub const IC_FULL: &str = "\u{e1d0}"; // corners-out
pub const IC_PLAY: &str = "\u{e3d0}"; // play
pub const IC_DISC: &str = "\u{e564}"; // disc

/// The height of the bar in logical points.
pub const BAR_H: f32 = 34.0;

/// One program on one disc, as the launcher reported it.
#[derive(Clone)]
pub struct Entry {
    pub drive: u8,
    pub label: String,
    pub name: String,
}

/// `drive<TAB>label<TAB>name` a line — written by tools/cool8rsrun.py.
pub fn load_catalogue(path: &str) -> Vec<Entry> {
    let mut out = Vec::new();
    let text = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("no disc catalogue at {}: {}", path, e);
            return out;
        }
    };
    for line in text.lines() {
        let mut f = line.split('\t');
        if let (Some(d), Some(l), Some(n)) = (f.next(), f.next(), f.next()) {
            if let Ok(drive) = d.parse::<u8>() {
                out.push(Entry {
                    drive,
                    label: l.to_string(),
                    name: n.to_string(),
                });
            }
        }
    }
    out
}

/// What a click asked for. The window owns the machine, so the bar
/// reports rather than acts — except where acting is one call on a
/// machine it was handed.
pub enum Act {
    None,
    Warm,
    Cold,
    Break,
    Shot,
    Fullscreen,
    Launch(Entry),
}

/// The scancodes for the machine's own restart chords ([D54]).
///
/// **Injected rather than the chord being changed.** Ctrl+Esc and
/// Ctrl+Shift+Esc are decoded in `cool8_ps2` before software sees
/// anything, which is right on a board where no operating system stands
/// between the keyboard and the machine, and impossible on a host that
/// keeps both for itself. The machine receives the bytes a real
/// keyboard would send and cannot tell a button from a key.
pub fn warm(m: &mut Machine) {
    m.bus.kbd.feed(&[0x14, 0x76, 0xF0, 0x76, 0xF0, 0x14]);
}

pub fn cold(m: &mut Machine) {
    m.bus.kbd.feed(&[0x14, 0x12, 0x76, 0xF0, 0x76, 0xF0, 0x12, 0xF0, 0x14]);
}

/// Draw the bar and say what was clicked.
///
/// `sel` is the combo's current index and is written back, so the menu
/// keeps its place across frames the way an immediate-mode menu must.
pub fn draw(ui: &imgui::Ui, discs: &[Entry], sel: &mut usize,
            fullscreen: bool) -> Act {
    let mut act = Act::None;
    let vp = ui.io().display_size;

    let _pad = ui.push_style_var(
        imgui::StyleVar::WindowPadding([8.0, 5.0]));
    let _round = ui.push_style_var(imgui::StyleVar::FrameRounding(3.0));

    ui.window("##bar")
        .position([0.0, vp[1] - BAR_H], imgui::Condition::Always)
        .size([vp[0], BAR_H], imgui::Condition::Always)
        .flags(imgui::WindowFlags::NO_DECORATION
               | imgui::WindowFlags::NO_MOVE
               | imgui::WindowFlags::NO_SAVED_SETTINGS
               | imgui::WindowFlags::NO_BRING_TO_FRONT_ON_FOCUS
               | imgui::WindowFlags::NO_NAV_FOCUS
               | imgui::WindowFlags::NO_SCROLLBAR)
        .build(|| {
            // A button, its shortcut and one line of what it does. The
            // tooltip is the toolkit's; the words are the only part
            // worth writing.
            let button = |icon: &str, key: &str, what: &str| -> bool {
                let hit = ui.button(icon);
                if ui.is_item_hovered() {
                    ui.tooltip(|| {
                        ui.text(format!("{}   {}", key, what));
                    });
                }
                ui.same_line();
                hit
            };

            if button(IC_WARM, "F1", "Warm restart") {
                act = Act::Warm;
            }
            if button(IC_COLD, "F10", "Cold restart") {
                act = Act::Cold;
            }
            if button(IC_BREAK, "F11", "Break — stop a running program") {
                act = Act::Break;
            }
            if button(IC_SHOT, "F12", "Screenshot to a PNG") {
                act = Act::Shot;
            }
            let fs_what = if fullscreen { "Leave fullscreen" }
                          else { "Fullscreen" };
            if button(IC_FULL, "Alt+Enter", fs_what) {
                act = Act::Fullscreen;
            }

            if discs.is_empty() {
                ui.text_disabled("no discs");
                return;
            }

            ui.text(IC_DISC);
            ui.same_line();
            ui.set_next_item_width(230.0);
            let names: Vec<String> = discs.iter()
                .map(|e| format!("{}  {}", e.label, stem(&e.name)))
                .collect();
            let refs: Vec<&String> = names.iter().collect();
            ui.combo_simple_string("##disc", sel, &refs);
            if ui.is_item_hovered() {
                ui.tooltip(|| {
                    ui.text("Every program on every disc");
                });
            }
            ui.same_line();
            if ui.button(IC_PLAY) {
                if let Some(e) = discs.get(*sel) {
                    act = Act::Launch(e.clone());
                }
            }
            if ui.is_item_hovered() {
                ui.tooltip(|| {
                    ui.text("Restart, then DRIVE / LOAD / RUN it");
                });
            }
        });
    act
}

/// `10PRINT.BAS` -> `10PRINT`, which is what LOAD wants.
pub fn stem(name: &str) -> &str {
    match name.rfind('.') {
        Some(i) => &name[..i],
        None => name,
    }
}
