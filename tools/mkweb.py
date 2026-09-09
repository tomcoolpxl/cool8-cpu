#!/usr/bin/env python3
"""Build and package the COOL8 WebAssembly static web emulator.

    python tools/mkweb.py          # build wasm binary and assets into web/
    python tools/mkweb.py --serve  # build and serve on http://localhost:8000
    (or: poe web-build, poe web)
"""

import argparse
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "web")
BUILD = os.path.join(ROOT, "sim", "build")
RUST_DIR = os.path.join(ROOT, "rust")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "sim"))


def build_wasm():
    os.makedirs(WEB, exist_ok=True)
    print("  building WebAssembly binary (wasm32-unknown-unknown)...", flush=True)
    r = subprocess.run(
        ["cargo", "build", "--release", "--target", "wasm32-unknown-unknown", "--lib"],
        cwd=RUST_DIR,
    )
    if r.returncode != 0:
        sys.exit(f"error: cargo build failed with exit code {r.returncode}")

    src_wasm = os.path.join(
        RUST_DIR, "target", "wasm32-unknown-unknown", "release", "cool8rs.wasm"
    )
    if not os.path.exists(src_wasm):
        sys.exit(f"error: compiled wasm binary not found at {src_wasm}")

    dst_wasm = os.path.join(WEB, "cool8.wasm")
    shutil.copyfile(src_wasm, dst_wasm)
    size_kb = os.path.getsize(dst_wasm) / 1024.0
    print(f"  wasm binary copied to web/cool8.wasm ({size_kb:.1f} KB)")


def build_assets():
    os.makedirs(WEB, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)

    import cool8disk as disk
    import cool8kbd
    import cool8rsvm as vm
    import flash
    import test_basic as B

    # 1. ROM and Font
    print("  building boot ROM and font...", flush=True)
    rom, font = vm.build_rom()
    rom_p = os.path.join(WEB, "boot.bin")
    font_p = os.path.join(WEB, "font.bin")
    with open(rom_p, "wb") as f:
        f.write(rom)
    with open(font_p, "wb") as f:
        f.write(font)
    print(f"  wrote {rom_p} ({len(rom)} bytes) and {font_p} ({len(font)} bytes)")

    # 2. Flash Disk Image (with BASIC and demo programs)
    disk_p = os.path.join(ROOT, "build", "cool8.img")
    print("  building flash disk image with demos...", flush=True)
    subprocess.run([sys.executable, os.path.join(HERE, "mkdemos.py"), "--img", disk_p, "--no-shots"],
                   cwd=ROOT, check=True)

    dst_disk = os.path.join(WEB, "cool8.img")
    shutil.copyfile(disk_p, dst_disk)
    print(f"  copied disk image to web/cool8.img ({os.path.getsize(dst_disk) / (1024 * 1024):.1f} MB)")

    # 3. Disc catalogue metadata. **The menus and the programs, both
    # from tools/cool8disk.py**: a menu is a drive (`MENUS`), and a
    # program carries the drive it is on and how it is started (`kind`),
    # so the page groups and launches without knowing a disc format or
    # a program name.
    rows = disk.catalogue(disk_p)
    discs = {
        "menus": [{"drive": d, "title": t} for d, t in disk.menus()],
        "programs": [{"drive": drive, "label": label, "name": name,
                      "stem": disk.stem(name), "kind": kind}
                     for drive, label, name, kind in rows],
    }
    discs_p = os.path.join(WEB, "discs.json")
    with open(discs_p, "w", encoding="utf-8") as f:
        json.dump(discs, f, indent=2)
    print(f"  wrote {len(rows)} catalogue entries in {len(discs['menus'])} menus to web/discs.json")

    # 4. Keyboard mapping table
    chars, named = cool8kbd.kbd_tables()
    keymap = {}
    for ch, (sc, shifted) in chars.items():
        keymap[ch] = {"scancode": sc, "shifted": shifted}
    keymap_p = os.path.join(WEB, "keymap.json")
    with open(keymap_p, "w", encoding="utf-8") as f:
        json.dump(keymap, f, indent=2)
    print(f"  wrote keymap table to web/keymap.json")

    # 5. Idle symbols & configuration
    code, syms = B.build()
    config = {
        "idle_pc": syms.get("in_raw.rk0", 0),
        "irhead": syms.get("irhead", 0),
        "irtail": syms.get("irtail", 0),
    }
    config_p = os.path.join(WEB, "config.json")
    with open(config_p, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"  wrote machine config to web/config.json (idle PC: ${config['idle_pc']:04X})")


class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Set proper MIME types and caching headers for local development
        if self.path.endswith(".wasm"):
            self.send_header("Content-Type", "application/wasm")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def guess_type(self, path):
        if path.endswith(".wasm"):
            return "application/wasm"
        return super().guess_type(path)


def serve(port=8000):
    os.chdir(WEB)
    handler = CustomHTTPRequestHandler
    # Allow address reuse to prevent "address already in use" on fast restarts
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        url = f"http://localhost:{port}/"
        print(f"\n  Serving COOL8 web emulator at {url}")
        print("  Press Ctrl+C to stop the server.\n")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")


def main():
    ap = argparse.ArgumentParser(description="COOL8 WebAssembly builder & local server")
    ap.add_argument("--serve", action="store_true", help="start local dev server after build")
    ap.add_argument("--port", type=int, default=8000, help="port for dev server (default: 8000)")
    args = ap.parse_args()

    print("=== COOL8 WebAssembly Build ===")
    build_wasm()
    build_assets()
    print("=== Build Complete ===")

    if args.serve:
        serve(args.port)


if __name__ == "__main__":
    main()
