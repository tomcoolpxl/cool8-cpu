/**
 * COOL8 WebAssembly Emulator Frontend
 */

const SND_HZ = 8375000.0 / 256.0; // ~32714.84 Hz
const FRAME_HZ = 8375000.0 / (266.0 * 525.0); // ~59.9706 Hz
const H_VIS = 640;
const V_VIS = 480;

// Set 2 PS/2 Scancodes for DOM KeyboardEvent.code
const SET2_MAP = {
  KeyA: [0x1C, false], KeyB: [0x32, false], KeyC: [0x21, false], KeyD: [0x23, false],
  KeyE: [0x24, false], KeyF: [0x2B, false], KeyG: [0x34, false], KeyH: [0x33, false],
  KeyI: [0x43, false], KeyJ: [0x3B, false], KeyK: [0x42, false], KeyL: [0x4B, false],
  KeyM: [0x3A, false], KeyN: [0x31, false], KeyO: [0x44, false], KeyP: [0x4D, false],
  KeyQ: [0x15, false], KeyR: [0x2D, false], KeyS: [0x1B, false], KeyT: [0x2C, false],
  KeyU: [0x3C, false], KeyV: [0x2A, false], KeyW: [0x1D, false], KeyX: [0x22, false],
  KeyY: [0x35, false], KeyZ: [0x1A, false],
  Digit0: [0x45, false], Digit1: [0x16, false], Digit2: [0x1E, false], Digit3: [0x26, false],
  Digit4: [0x25, false], Digit5: [0x2E, false], Digit6: [0x36, false], Digit7: [0x3D, false],
  Digit8: [0x3E, false], Digit9: [0x46, false],
  Backquote: [0x0E, false], Minus: [0x4E, false], Equal: [0x55, false], Backslash: [0x5D, false],
  Backspace: [0x66, false], Space: [0x29, false], Tab: [0x0D, false], Enter: [0x5A, false],
  Escape: [0x76, false], CapsLock: [0x58, false],
  BracketLeft: [0x54, false], BracketRight: [0x5B, false],
  Semicolon: [0x4C, false], Quote: [0x52, false],
  Comma: [0x41, false], Period: [0x49, false], Slash: [0x4A, false],
  ShiftLeft: [0x12, false], ShiftRight: [0x59, false],
  ControlLeft: [0x14, false], ControlRight: [0x14, true],
  AltLeft: [0x11, false], AltRight: [0x11, true],
  ArrowUp: [0x75, true], ArrowDown: [0x72, true],
  ArrowLeft: [0x6B, true], ArrowRight: [0x74, true],
  Home: [0x6C, true], End: [0x69, true],
  PageUp: [0x7D, true], PageDown: [0x7A, true],
  Insert: [0x70, true], Delete: [0x71, true],
  F1: [0x05, false], F2: [0x06, false], F3: [0x04, false], F4: [0x0C, false],
  F5: [0x03, false], F6: [0x0B, false], F7: [0x83, false], F8: [0x0A, false],
  F9: [0x01, false], F10: [0x09, false]
};

class Cool8Emulator {
  constructor() {
    this.canvas = document.getElementById("screen");
    this.ctx = this.canvas.getContext("2d", { alpha: false });
    this.imgData = this.ctx.createImageData(H_VIS, V_VIS);

    this.wasm = null;
    this.state = 0;
    this.started = false;
    this.audioCtx = null;
    this.audioNode = null;
    this.audioQueue = [];
    this.audioVolume = 0.7;
    this.audioMuted = false;

    this.config = { idle_pc: 0xB632, irhead: 0x0280, irtail: 0x0281 };
    this.discs = [];
    this.pendingLaunch = null;
    this.launchBooted = false;

    this.lastFrameTime = performance.now();
    this.machineFrames = 0;
    this.fpsFrames = 0;
    this.fpsLastCheck = performance.now();

    this.initUI();
  }

  async load() {
    this.setStatus("Fetching WebAssembly module and assets...");
    try {
      // 1. Fetch assets in parallel
      const [wasmResp, romResp, fontResp, diskResp, discsResp, keymapResp, cfgResp] =
        await Promise.all([
          fetch("cool8.wasm"),
          fetch("boot.bin"),
          fetch("font.bin"),
          fetch("cool8.img"),
          fetch("discs.json").catch(() => null),
          fetch("keymap.json").catch(() => null),
          fetch("config.json").catch(() => null)
        ]);

      if (!wasmResp.ok) throw new Error("Failed to load cool8.wasm");
      if (!romResp.ok) throw new Error("Failed to load boot.bin");
      if (!fontResp.ok) throw new Error("Failed to load font.bin");
      if (!diskResp.ok) throw new Error("Failed to load cool8.img");

      const [wasmBuffer, romBytes, fontBytes, diskBytes] = await Promise.all([
        wasmResp.arrayBuffer(),
        romResp.arrayBuffer().then(b => new Uint8Array(b)),
        fontResp.arrayBuffer().then(b => new Uint8Array(b)),
        diskResp.arrayBuffer().then(b => new Uint8Array(b))
      ]);

      this.romBytes = romBytes;
      this.fontBytes = fontBytes;

      if (discsResp && discsResp.ok) {
        this.discs = await discsResp.json();
        this.populateMenus(this.discs);
      }
      if (cfgResp && cfgResp.ok) {
        this.config = await cfgResp.json();
      }

      // 2. Instantiate WebAssembly
      const wasmModule = await WebAssembly.instantiate(wasmBuffer, {
        env: {
          abort: () => console.error("Wasm aborted")
        }
      });
      this.wasm = wasmModule.instance.exports;

      // 3. Allocate buffers in Wasm memory
      const romPtr = this.allocCopy(romBytes);
      const fontPtr = this.allocCopy(fontBytes);
      const diskPtr = this.allocCopy(diskBytes);

      // 4. Create machine instance
      this.state = this.wasm.cool8_create(
        romPtr, romBytes.length,
        fontPtr, fontBytes.length,
        diskPtr, diskBytes.length
      );

      // 5. Load keymap text into wasm if available
      if (keymapResp && keymapResp.ok) {
        const kmJson = await keymapResp.json();
        let kmLines = "";
        for (const [ch, info] of Object.entries(kmJson)) {
          const chCode = ch.charCodeAt(0);
          kmLines += `${chCode.toString(16)} ${info.scancode.toString(16)} ${info.shifted ? 1 : 0}\n`;
        }
        const kmBytes = new TextEncoder().encode(kmLines);
        const kmPtr = this.allocCopy(kmBytes);
        this.wasm.cool8_load_keymap(this.state, kmPtr, kmBytes.length);
        this.wasm.cool8_free(kmPtr, kmBytes.length);
      }

      this.setStatus("COOL8 ready. Click screen or press any key to start.");
    } catch (err) {
      console.error(err);
      this.setStatus("Load error: " + err.message);
    }
  }

  allocCopy(uint8Array) {
    const ptr = this.wasm.cool8_alloc(uint8Array.length);
    const mem = new Uint8Array(this.wasm.memory.buffer, ptr, uint8Array.length);
    mem.set(uint8Array);
    return ptr;
  }

  initAudio() {
    if (this.audioCtx) return;
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      this.audioCtx = new AudioContext({ sampleRate: 44100 });

      // Resampling buffer queue via ScriptProcessorNode
      const bufferSize = 2048;
      this.audioNode = this.audioCtx.createScriptProcessor(bufferSize, 1, 1);

      let acc = 0.0;
      let curSample = 128;
      const step = SND_HZ / this.audioCtx.sampleRate;

      this.audioNode.onaudioprocess = (e) => {
        const output = e.outputBuffer.getChannelData(0);
        const vol = this.audioMuted ? 0 : this.audioVolume;

        for (let i = 0; i < output.length; i++) {
          acc += step;
          while (acc >= 1.0) {
            acc -= 1.0;
            if (this.audioQueue.length > 0) {
              curSample = this.audioQueue.shift();
            }
          }
          output[i] = ((curSample - 128) / 128.0) * vol;
        }

        // Cap queue to avoid high latency lag
        const maxLag = Math.floor(SND_HZ * 0.25);
        if (this.audioQueue.length > maxLag) {
          this.audioQueue.splice(0, this.audioQueue.length - maxLag);
        }
      };

      this.audioNode.connect(this.audioCtx.destination);
    } catch (e) {
      console.warn("Web Audio API not supported:", e);
    }
  }

  start() {
    if (this.started || !this.state) return;
    this.started = true;
    this.initAudio();
    if (this.audioCtx && this.audioCtx.state === "suspended") {
      this.audioCtx.resume();
    }

    document.getElementById("click-to-start").classList.add("hidden");
    this.canvas.focus();
    this.setStatus("Running");

    this.lastFrameTime = performance.now();
    this.machineFrames = 0;
    requestAnimationFrame((t) => this.loop(t));
  }

  loop(now) {
    if (!this.started || !this.state) return;

    // Time-based frame pacing: 59.9706 Hz
    const elapsedSecs = (now - this.lastFrameTime) / 1000.0;
    const due = Math.floor(elapsedSecs * FRAME_HZ);

    if (due > this.machineFrames + 8) {
      // Lag spike / tab background recovery
      this.machineFrames = Math.max(0, due - 1);
    }

    while (this.machineFrames < due) {
      this.wasm.cool8_step_frame(this.state);

      // Handle demo auto-launch typing
      if (this.pendingLaunch && !this.launchBooted) {
        if (this.wasm.cool8_is_idle(this.state, this.config.idle_pc, this.config.irhead, this.config.irtail)) {
          this.launchBooted = true;
          this.typeString(this.launchText(this.pendingLaunch));
          this.setStatus(`Launched ${this.pendingLaunch.stem}`);
          this.pendingLaunch = null;
        }
      }

      this.machineFrames++;
    }

    // 1. Render Video Frame
    const rgbaPtr = this.wasm.cool8_get_rgba_ptr(this.state);
    if (rgbaPtr) {
      const rgba = new Uint8ClampedArray(this.wasm.memory.buffer, rgbaPtr, H_VIS * V_VIS * 4);
      this.imgData.data.set(rgba);
      this.ctx.putImageData(this.imgData, 0, 0);
    }

    // 2. Queue Audio Samples
    const audioLen = this.wasm.cool8_get_audio_len(this.state);
    if (audioLen > 0) {
      const audioPtr = this.wasm.cool8_get_audio_ptr(this.state);
      const samples = new Uint8Array(this.wasm.memory.buffer, audioPtr, audioLen);
      for (let i = 0; i < samples.length; i++) {
        this.audioQueue.push(samples[i]);
      }
      this.wasm.cool8_clear_audio(this.state);
    }

    // 3. Update LED state
    const led = this.wasm.cool8_get_led(this.state);
    const ledEl = document.getElementById("led-indicator");
    if (led & 1) ledEl.classList.add("active");
    else ledEl.classList.remove("active");

    // 4. Update FPS Counter
    this.fpsFrames++;
    if (now - this.fpsLastCheck >= 1000) {
      const fps = (this.fpsFrames * 1000.0) / (now - this.fpsLastCheck);
      document.getElementById("fps-counter").innerText = `${fps.toFixed(1)} FPS`;
      this.fpsFrames = 0;
      this.fpsLastCheck = now;
    }

    requestAnimationFrame((t) => this.loop(t));
  }

  typeString(str) {
    if (!this.state) return;
    const bytes = new TextEncoder().encode(str);
    const ptr = this.allocCopy(bytes);
    this.wasm.cool8_type_str(this.state, ptr, bytes.length);
    this.wasm.cool8_free(ptr, bytes.length);
  }

  sendKey(code, ext, pressed) {
    if (!this.state) return;
    this.wasm.cool8_send_key(this.state, code, ext, pressed);
  }

  warmReset() {
    if (!this.state) return;
    this.wasm.cool8_warm_reset(this.state);
    this.setStatus("Warm restart (Ctrl+Esc)");
  }

  coldReset() {
    if (!this.state) return;
    this.wasm.cool8_cold_reset(this.state);
    this.setStatus("Cold restart");
  }

  pulseBreak() {
    if (!this.state) return;
    this.wasm.cool8_pulse_nmi(this.state);
    this.setStatus("Break (NMI) triggered");
  }

  saveScreenshot() {
    const link = document.createElement("a");
    link.download = `cool8-shot-${Date.now()}.png`;
    link.href = this.canvas.toDataURL("image/png");
    link.click();
    this.setStatus("Screenshot saved");
  }

  toggleFullscreen() {
    const wrapper = document.getElementById("screen-wrapper");
    if (!document.fullscreenElement) {
      wrapper.requestFullscreen().catch(err => console.warn(err));
    } else {
      document.exitFullscreen().catch(err => console.warn(err));
    }
  }

  // **A menu is a drive.** discs.json carries the menus in order, each
  // a drive and a title from tools/cool8disk.py's MENUS, and every
  // program with the drive it is on; the page groups by drive and
  // never names a program or a disc format itself.
  populateMenus(discs) {
    const host = document.getElementById("menus");
    host.innerHTML = "";
    for (const menu of discs.menus) {
      const label = document.createElement("span");
      label.className = "group-label";
      label.textContent = `\u{1F4BE} ${menu.title}:`;
      const select = document.createElement("select");
      select.className = "select-demo";
      select.title = `Select a program from drive ${menu.drive}`;
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = `(${menu.title}...)`;
      select.appendChild(blank);
      for (const d of discs.programs) {
        if (d.drive !== menu.drive) continue;
        const opt = document.createElement("option");
        opt.value = JSON.stringify(d);
        opt.textContent = d.stem;
        select.appendChild(opt);
      }
      const run = document.createElement("button");
      run.className = "btn-primary";
      run.title = `Restart, then start the selected ${menu.title} program`;
      run.innerHTML = "&#9654; Run";
      run.addEventListener("click", () => this.runSelected(select));
      host.append(label, select, run);
    }
  }

  // How a program is started is the catalogue's `kind`: a `.BAS` by
  // LOAD and RUN, a `.BIN` -- a PRG carrying its own address (D87) --
  // by SYS. The same two strings rust/src/bar.rs types.
  launchText(p) {
    if (p.kind === "bin") {
      return `DRIVE ${p.drive}\rSYS "${p.name}"\r`;
    }
    return `DRIVE ${p.drive}\rLOAD "${p.stem}"\rRUN\r`;
  }

  runSelected(select) {
    if (!select.value) return;
    const prog = JSON.parse(select.value);

    this.coldReset();
    this.pendingLaunch = prog;
    this.launchBooted = false;
    this.setStatus(`Rebooting to launch ${prog.stem}...`);
  }

  setStatus(text) {
    document.getElementById("status-text").innerText = text;
  }

  initUI() {
    // Start Overlay Click
    document.getElementById("click-to-start").addEventListener("click", () => this.start());

    // Toolbar Buttons
    document.getElementById("btn-warm").addEventListener("click", () => this.warmReset());
    document.getElementById("btn-cold").addEventListener("click", () => this.coldReset());
    document.getElementById("btn-break").addEventListener("click", () => this.pulseBreak());
    document.getElementById("btn-shot").addEventListener("click", () => this.saveScreenshot());
    document.getElementById("btn-full").addEventListener("click", () => this.toggleFullscreen());

    // Audio Controls
    const btnAudio = document.getElementById("btn-audio");
    const volSlider = document.getElementById("audio-volume");

    btnAudio.addEventListener("click", () => {
      this.audioMuted = !this.audioMuted;
      btnAudio.innerHTML = this.audioMuted ? "&#128263;" : "&#128266;";
    });

    volSlider.addEventListener("input", (e) => {
      this.audioVolume = e.target.value / 100.0;
      if (this.audioMuted && this.audioVolume > 0) {
        this.audioMuted = false;
        btnAudio.innerHTML = "&#128266;";
      }
    });

    // Help Modal
    const modal = document.getElementById("help-modal");
    document.getElementById("btn-help").addEventListener("click", () => modal.classList.remove("hidden"));
    document.getElementById("btn-close-help").addEventListener("click", () => modal.classList.add("hidden"));
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.classList.add("hidden");
    });

    // Keyboard Handling
    window.addEventListener("keydown", (e) => {
      if (!this.started) {
        this.start();
      }

      // Allow modal Esc
      if (e.key === "Escape" && !modal.classList.contains("hidden")) {
        modal.classList.add("hidden");
        return;
      }

      // Check emulator shortcuts
      if (e.code === "F1") { e.preventDefault(); this.warmReset(); return; }
      if (e.code === "F10") { e.preventDefault(); this.coldReset(); return; }
      if (e.code === "F11") { e.preventDefault(); this.pulseBreak(); return; }
      if (e.code === "F12") { e.preventDefault(); this.saveScreenshot(); return; }
      if (e.code === "Enter" && e.altKey) { e.preventDefault(); this.toggleFullscreen(); return; }

      // Map physical keys to PS/2 Set 2 make scancodes
      if (SET2_MAP[e.code]) {
        const [sc, ext] = SET2_MAP[e.code];
        this.sendKey(sc, ext, true);

        // Prevent browser scrolling on navigation keys
        if (["Space", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Tab"].includes(e.code)) {
          e.preventDefault();
        }
      }
    });

    window.addEventListener("keyup", (e) => {
      if (SET2_MAP[e.code]) {
        const [sc, ext] = SET2_MAP[e.code];
        this.sendKey(sc, ext, false);
      }
    });

    // Paste handling
    window.addEventListener("paste", (e) => {
      const text = (e.clipboardData || window.clipboardData).getData("text");
      if (text) {
        e.preventDefault();
        const formatted = text.replace(/\r?\n/g, "\r");
        this.typeString(formatted);
        this.setStatus(`Pasted ${text.length} characters`);
      }
    });

    // Drag & Drop .img or .bas files
    const dropOverlay = document.getElementById("drop-overlay");
    const frame = document.querySelector(".emulator-frame");

    window.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropOverlay.classList.remove("hidden");
    });
    window.addEventListener("dragleave", (e) => {
      if (e.relatedTarget === null) dropOverlay.classList.add("hidden");
    });
    window.addEventListener("drop", async (e) => {
      e.preventDefault();
      dropOverlay.classList.add("hidden");
      const files = e.dataTransfer.files;
      if (!files || files.length === 0) return;

      const file = files[0];
      const buf = new Uint8Array(await file.arrayBuffer());

      if (file.name.toLowerCase().endsWith(".img")) {
        // Recreate machine with new flash image
        this.setStatus(`Loading flash disk image: ${file.name}...`);
        const diskPtr = this.allocCopy(buf);
        // Destroy old machine and create new
        const romPtr = this.allocCopy(this.romBytes);
        const fontPtr = this.allocCopy(this.fontBytes);
        this.wasm.cool8_destroy(this.state);
        this.state = this.wasm.cool8_create(romPtr, this.romBytes.length, fontPtr, this.fontBytes.length, diskPtr, buf.length);
        this.setStatus(`Booted custom disk: ${file.name}`);
      } else if (file.name.toLowerCase().endsWith(".bas")) {
        // Type BASIC file content directly
        const text = new TextDecoder().decode(buf);
        this.typeString("NEW\r" + text.replace(/\r?\n/g, "\r") + "\r");
        this.setStatus(`Injected BASIC file: ${file.name}`);
      }
    });
  }
}

window.addEventListener("DOMContentLoaded", () => {
  const emu = new Cool8Emulator();
  // Reachable from the console as `cool8`, so the machine can be driven
  // and inspected by hand -- a hidden tab gets no animation frames, and
  // a launch can still be stepped through from the devtools.
  window.cool8 = emu;
  emu.load();
});
