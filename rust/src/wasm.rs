use crate::machine::Machine;
use crate::render::{Renderer, H_VIS, V_VIS};
use std::collections::{HashMap, VecDeque};

pub struct WasmState {
    pub machine: Machine,
    pub rgba: Vec<u8>,
    pub audio: Vec<u8>,
    pub typed_queue: VecDeque<u8>,
    pub keymap: HashMap<u8, (u8, bool)>,
}

#[no_mangle]
pub extern "C" fn cool8_alloc(size: usize) -> *mut u8 {
    let mut buf = Vec::with_capacity(size);
    let ptr = buf.as_mut_ptr();
    std::mem::forget(buf);
    ptr
}

#[no_mangle]
pub extern "C" fn cool8_free(ptr: *mut u8, size: usize) {
    if !ptr.is_null() {
        unsafe {
            let _ = Vec::from_raw_parts(ptr, 0, size);
        }
    }
}

#[no_mangle]
pub extern "C" fn cool8_create(
    rom_ptr: *const u8,
    rom_len: usize,
    font_ptr: *const u8,
    font_len: usize,
    flash_ptr: *const u8,
    flash_len: usize,
) -> *mut WasmState {
    let mut rom = [0u8; 4096];
    if !rom_ptr.is_null() && rom_len > 0 {
        let slice = unsafe { std::slice::from_raw_parts(rom_ptr, rom_len.min(4096)) };
        rom[..slice.len()].copy_from_slice(slice);
    }

    let mut font = [0u8; 4096];
    if !font_ptr.is_null() && font_len > 0 {
        let slice = unsafe { std::slice::from_raw_parts(font_ptr, font_len.min(4096)) };
        font[..slice.len()].copy_from_slice(slice);
    }

    let flash = if !flash_ptr.is_null() && flash_len > 0 {
        let slice = unsafe { std::slice::from_raw_parts(flash_ptr, flash_len) };
        Some(slice.to_vec())
    } else {
        None
    };

    let mut machine = Machine::new(rom, flash);
    machine.renderer = Some(Renderer::new(font));

    let state = Box::new(WasmState {
        machine,
        rgba: vec![0u8; H_VIS * V_VIS * 4],
        audio: Vec::with_capacity(4096),
        typed_queue: VecDeque::new(),
        keymap: HashMap::new(),
    });

    Box::into_raw(state)
}

#[no_mangle]
pub extern "C" fn cool8_destroy(state: *mut WasmState) {
    if !state.is_null() {
        unsafe {
            let _ = Box::from_raw(state);
        }
    }
}

#[no_mangle]
pub extern "C" fn cool8_load_keymap(
    state: *mut WasmState,
    keymap_ptr: *const u8,
    keymap_len: usize,
) {
    if state.is_null() || keymap_ptr.is_null() || keymap_len == 0 {
        return;
    }
    let st = unsafe { &mut *state };
    let slice = unsafe { std::slice::from_raw_parts(keymap_ptr, keymap_len) };
    if let Ok(text) = std::str::from_utf8(slice) {
        for line in text.lines() {
            let f: Vec<&str> = line.split_whitespace().collect();
            if f.len() == 3 {
                if let (Ok(ch), Ok(code)) = (
                    u8::from_str_radix(f[0], 16),
                    u8::from_str_radix(f[1], 16),
                ) {
                    st.keymap.insert(ch, (code, f[2] == "1"));
                }
            }
        }
    }
}

#[no_mangle]
pub extern "C" fn cool8_step_frame(state: *mut WasmState) -> u32 {
    if state.is_null() {
        return 0;
    }
    let st = unsafe { &mut *state };

    // Service typed characters sharing the PS/2 queue (up to 1 char per frame)
    if st.machine.bus.kbd.q.len() < 8 {
        if let Some(ch) = st.typed_queue.pop_front() {
            if let Some(&(code, shifted)) = st.keymap.get(&ch) {
                let mut b = Vec::new();
                if shifted {
                    b.push(0x12);
                }
                b.extend([code, 0xF0, code]);
                if shifted {
                    b.extend([0xF0, 0x12]);
                }
                st.machine.bus.kbd.feed(&b);
            }
        }
    }

    let target = st.machine.frames + 1;
    while st.machine.frames < target {
        st.machine.tick();
    }

    // Drain audio
    st.audio.extend(st.machine.bus.sound.samples.drain(..));

    // Convert 12-bit RGB framebuffer to RGBA8888
    if let Some(r) = st.machine.renderer.as_ref() {
        for (dst, &px) in st.rgba.chunks_exact_mut(4).zip(r.fb.iter()) {
            dst[0] = (((px >> 8) & 0xF) as u8) * 17;
            dst[1] = (((px >> 4) & 0xF) as u8) * 17;
            dst[2] = ((px & 0xF) as u8) * 17;
            dst[3] = 255;
        }
    }

    st.machine.frames as u32
}

#[no_mangle]
pub extern "C" fn cool8_get_rgba_ptr(state: *mut WasmState) -> *const u8 {
    if state.is_null() {
        std::ptr::null()
    } else {
        let st = unsafe { &*state };
        st.rgba.as_ptr()
    }
}

#[no_mangle]
pub extern "C" fn cool8_get_audio_ptr(state: *mut WasmState) -> *const u8 {
    if state.is_null() {
        std::ptr::null()
    } else {
        let st = unsafe { &*state };
        st.audio.as_ptr()
    }
}

#[no_mangle]
pub extern "C" fn cool8_get_audio_len(state: *mut WasmState) -> usize {
    if state.is_null() {
        0
    } else {
        let st = unsafe { &*state };
        st.audio.len()
    }
}

#[no_mangle]
pub extern "C" fn cool8_clear_audio(state: *mut WasmState) {
    if !state.is_null() {
        let st = unsafe { &mut *state };
        st.audio.clear();
    }
}

#[no_mangle]
pub extern "C" fn cool8_send_key(
    state: *mut WasmState,
    code: u8,
    ext: bool,
    pressed: bool,
) {
    if state.is_null() {
        return;
    }
    let st = unsafe { &mut *state };
    let mut b = Vec::with_capacity(3);
    if ext {
        b.push(0xE0);
    }
    if !pressed {
        b.push(0xF0);
    }
    b.push(code);
    st.machine.bus.kbd.feed(&b);
}

#[no_mangle]
pub extern "C" fn cool8_type_char(state: *mut WasmState, ch: u8) {
    if state.is_null() {
        return;
    }
    let st = unsafe { &mut *state };
    st.typed_queue.push_back(ch);
}

#[no_mangle]
pub extern "C" fn cool8_type_str(
    state: *mut WasmState,
    str_ptr: *const u8,
    str_len: usize,
) {
    if state.is_null() || str_ptr.is_null() || str_len == 0 {
        return;
    }
    let st = unsafe { &mut *state };
    let slice = unsafe { std::slice::from_raw_parts(str_ptr, str_len) };
    for &b in slice {
        st.typed_queue.push_back(b);
    }
}

#[no_mangle]
pub extern "C" fn cool8_pulse_nmi(state: *mut WasmState) {
    if !state.is_null() {
        let st = unsafe { &mut *state };
        st.machine.cpu.pulse_nmi();
    }
}

#[no_mangle]
pub extern "C" fn cool8_warm_reset(state: *mut WasmState) {
    if !state.is_null() {
        let st = unsafe { &mut *state };
        st.machine.bus.kbd.feed(&[0x14, 0x76, 0xF0, 0x76, 0xF0, 0x14]);
    }
}

#[no_mangle]
pub extern "C" fn cool8_cold_reset(state: *mut WasmState) {
    if !state.is_null() {
        let st = unsafe { &mut *state };
        st.typed_queue.clear();
        st.machine.bus.kbd.feed(&[0x14, 0x12, 0x76, 0xF0, 0x76, 0xF0, 0x12, 0xF0, 0x14]);
    }
}

#[no_mangle]
pub extern "C" fn cool8_is_idle(
    state: *mut WasmState,
    idle_pc: u16,
    irhead: usize,
    irtail: usize,
) -> bool {
    if state.is_null() {
        false
    } else {
        let st = unsafe { &*state };
        st.typed_queue.is_empty() && st.machine.is_idle(idle_pc, irhead, irtail)
    }
}

#[no_mangle]
pub extern "C" fn cool8_is_flash_dirty(state: *mut WasmState) -> bool {
    if state.is_null() {
        false
    } else {
        let st = unsafe { &*state };
        st.machine.bus.flash.dirty
    }
}

#[no_mangle]
pub extern "C" fn cool8_clear_flash_dirty(state: *mut WasmState) {
    if !state.is_null() {
        let st = unsafe { &mut *state };
        st.machine.bus.flash.dirty = false;
    }
}

#[no_mangle]
pub extern "C" fn cool8_get_flash_ptr(state: *mut WasmState) -> *const u8 {
    if state.is_null() {
        std::ptr::null()
    } else {
        let st = unsafe { &*state };
        st.machine.bus.flash.mem.as_ptr()
    }
}

#[no_mangle]
pub extern "C" fn cool8_get_flash_len(state: *mut WasmState) -> usize {
    if state.is_null() {
        0
    } else {
        let st = unsafe { &*state };
        st.machine.bus.flash.mem.len()
    }
}

#[no_mangle]
pub extern "C" fn cool8_get_led(state: *mut WasmState) -> u8 {
    if state.is_null() {
        0
    } else {
        let st = unsafe { &*state };
        st.machine.bus.led
    }
}

/// Compile CoolAction! source text to PRG binary in WebAssembly.
/// Returns pointer to PRG bytes and writes byte length to `out_len`.
/// On error, returns null and sets out_len to 0.
#[no_mangle]
pub extern "C" fn cool8_compile_action(
    src_ptr: *const u8,
    src_len: usize,
    org: u16,
    out_len: *mut usize,
) -> *mut u8 {
    if src_ptr.is_null() || src_len == 0 {
        if !out_len.is_null() {
            unsafe { *out_len = 0; }
        }
        return std::ptr::null_mut();
    }

    let src_slice = unsafe { std::slice::from_raw_parts(src_ptr, src_len) };
    let src_str = match std::str::from_utf8(src_slice) {
        Ok(s) => s,
        Err(_) => {
            if !out_len.is_null() {
                unsafe { *out_len = 0; }
            }
            return std::ptr::null_mut();
        }
    };

    match crate::action::compile(src_str, org) {
        Ok(res) => {
            let mut prg = res.prg;
            let len = prg.len();
            let ptr = prg.as_mut_ptr();
            std::mem::forget(prg);
            if !out_len.is_null() {
                unsafe { *out_len = len; }
            }
            ptr
        }
        Err(_) => {
            if !out_len.is_null() {
                unsafe { *out_len = 0; }
            }
            std::ptr::null_mut()
        }
    }
}
