#!/usr/bin/env python3
"""COOL8 in a window: the screen, the keyboard and the speaker.

    python tools/cool8run.py                     # boot the ROM and type at it
    python tools/cool8run.py --scale 1
    python tools/cool8run.py --load prog.bin --at 0x0200
    python tools/cool8run.py --flash disk.bin    # a disk that survives
    python tools/cool8run.py --wav out.wav       # record what it plays
    python tools/cool8run.py --headless --frames 600 --shot screen.png

This is `tools/cool8vm.py` with a display attached. The machine, the
memory map, the register semantics and the sound engine are all there;
what is here is a window, a keyboard, a mixer and a frame loop.

## The keyboard is a keyboard, not a text field

Keys become **raw Set 2 scancodes** — make codes, `$F0` break codes,
`$E0` prefixes, both shifts — because that is what the PS/2 port
delivers on the board (docs section 4.3) and translating to ASCII here
would let software work in the emulator and fail on hardware. The boot
monitor's own table turns them into characters, and an operating system
will need one too.

Two keys are the emulator's rather than the machine's, and are not
passed through:

    F11   the break button, SW[0] — an NMI, exactly as the board's is
    F12   write the screen to a PNG

Everything typed also reaches the UART with `--keys both`, which is
useful before an OS has a keyboard driver.

## It does not run at 60 fps, and says so

The CPU costs about 75 ms of Python per emulated frame and the display
about 13, so the machine runs at roughly a sixth of real time on a
desktop. The title bar shows the ratio. **Sound is generated at the
right rate and consumed at the rate it is produced**, so it plays
correctly pitched but gappy; `--wav` records the true stream with no
gaps at all, which is what a music routine should be judged on.

## What draws the picture

`cool8vid.render_np`, which is checked pixel for pixel against the RTL's
own frames by `sim/test_vm.py` — including sprites. Nothing about the
picture is approximated here.
"""

import argparse
import os
import sys
import time
import wave
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import cool8vm as vm                                 # noqa: E402
import cool8vid as vid                               # noqa: E402


# ------------------------------------------------------ the keyboard
#
# Set 2 make codes. The extended ones carry their $E0 in the value and
# the break sequence puts it back in the right place: $E0 $F0 $xx, not
# $F0 $E0 $xx, which is the mistake that makes cursor keys stick down.

SET2 = {
    'a': 0x1C, 'b': 0x32, 'c': 0x21, 'd': 0x23, 'e': 0x24, 'f': 0x2B,
    'g': 0x34, 'h': 0x33, 'i': 0x43, 'j': 0x3B, 'k': 0x42, 'l': 0x4B,
    'm': 0x3A, 'n': 0x31, 'o': 0x44, 'p': 0x4D, 'q': 0x15, 'r': 0x2D,
    's': 0x1B, 't': 0x2C, 'u': 0x3C, 'v': 0x2A, 'w': 0x1D, 'x': 0x22,
    'y': 0x35, 'z': 0x1A,
    '0': 0x45, '1': 0x16, '2': 0x1E, '3': 0x26, '4': 0x25, '5': 0x2E,
    '6': 0x36, '7': 0x3D, '8': 0x3E, '9': 0x46,
    '`': 0x0E, '-': 0x4E, '=': 0x55, '\\': 0x5D, '[': 0x54, ']': 0x5B,
    ';': 0x4C, "'": 0x52, ',': 0x41, '.': 0x49, '/': 0x4A,
    'space': 0x29, 'tab': 0x0D, 'return': 0x5A, 'backspace': 0x66,
    'escape': 0x76, 'capslock': 0x58,
    'left shift': 0x12, 'right shift': 0x59, 'left ctrl': 0x14,
    'left alt': 0x11,
    'f1': 0x05, 'f2': 0x06, 'f3': 0x04, 'f4': 0x0C, 'f5': 0x03,
    'f6': 0x0B, 'f7': 0x83, 'f8': 0x0A, 'f9': 0x01, 'f10': 0x09,
    'right ctrl': 0xE014, 'right alt': 0xE011,
    'insert': 0xE070, 'home': 0xE06C, 'page up': 0xE07D,
    'delete': 0xE071, 'end': 0xE069, 'page down': 0xE07A,
    'up': 0xE075, 'left': 0xE06B, 'down': 0xE072, 'right': 0xE074,
}


def make_code(code):
    return [code >> 8, code & 0xFF] if code > 0xFF else [code]


def break_code(code):
    if code > 0xFF:
        return [code >> 8, 0xF0, code & 0xFF]
    return [0xF0, code]


# ASCII for the UART path, so a machine with no keyboard driver is still
# usable. Shift is applied here because the UART carries characters.
SHIFTED = {'1': '!', '2': '@', '3': '#', '4': '$', '5': '%', '6': '^',
           '7': '&', '8': '*', '9': '(', '0': ')', '-': '_', '=': '+',
           '[': '{', ']': '}', '\\': '|', ';': ':', "'": '"', ',': '<',
           '.': '>', '/': '?', '`': '~'}


def ascii_for(name, shift):
    if name == 'space':
        return ' '
    if name == 'return':
        return '\r'
    if name == 'backspace':
        return '\x08'
    if name == 'tab':
        return '\t'
    if name == 'escape':
        return '\x1b'
    if len(name) == 1:
        if shift:
            return SHIFTED.get(name, name.upper())
        return name
    return None


# ------------------------------------------------------------ the pixels

def rgb_array(frame12, np):
    """12-bit palette colours to 8-bit RGB, the way the PMOD's resistors
    do it: each nibble repeated, so $F is 255 and $0 is 0."""
    r = ((frame12 >> 8) & 0xF) * 17
    g = ((frame12 >> 4) & 0xF) * 17
    b = (frame12 & 0xF) * 17
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def save_shot(machine, path):
    vid.save_png(vid.render_fast(machine), path)
    return path


# ------------------------------------------------------------ the loop

def make_machine(args):
    m = vm.boot(flash_path=args.flash)
    if args.load:
        with open(args.load, 'rb') as fh:
            data = fh.read()
        at = int(args.at, 0)
        m.bus.mem[at:at + len(data)] = data
        m.cpu.pc = at
        m.romen = False
        print(f"loaded {len(data)} bytes at ${at:04X}")
    return m


def open_wav(args):
    if not args.wav:
        return None
    wav = wave.open(args.wav, 'wb')
    wav.setnchannels(1)
    wav.setsampwidth(1)
    wav.setframerate(vm.SND_HZ)
    return wav


def run_headless(args):
    """No window, no pygame, nothing to install — the same machine."""
    m = make_machine(args)
    wav = open_wav(args)
    for _ in range(args.frames or 120):
        m.run_frame()
        if wav:
            wav.writeframes(m.sound.take())
    if args.shot:
        print(save_shot(m, args.shot))
    out = m.uart.take()
    if out:
        sys.stdout.write(out.decode('latin-1'))
    if wav:
        wav.close()
    if args.flash:
        m.flash.flush()
    return 0


def run(args):
    import numpy as np
    import pygame

    m = make_machine(args)
    wav = open_wav(args)

    audio = not args.no_audio
    mix_ch = 1
    if audio:
        try:
            pygame.mixer.pre_init(vm.SND_HZ, -16, 1, 2048)
            pygame.mixer.init()
            # Asking for mono does not guarantee mono — a device that
            # only does stereo gets opened stereo and then rejects a
            # one-dimensional array. Take what it actually gave.
            got = pygame.mixer.get_init()
            mix_ch = got[2] if got else 1
            if got and got[0] != vm.SND_HZ:
                print(f"mixer opened at {got[0]} Hz, not {vm.SND_HZ}; "
                      f"the pitch will be off by "
                      f"{got[0] / vm.SND_HZ:.2f}x")
        except pygame.error as e:
            print(f"no audio device ({e}); continuing without")
            audio = False

    pygame.init()
    w, h = vid.H_VIS * args.scale, vid.V_VIS * args.scale
    screen = pygame.display.set_mode((w, h))
    pygame.display.set_caption("COOL8")
    surf = pygame.Surface((vid.H_VIS, vid.V_VIS))
    channel = pygame.mixer.Channel(0) if audio else None
    clock = pygame.time.Clock()

    pressed = set()
    running = True
    t0 = time.time()
    shown = 0

    # ------------------------------------------------ typed characters
    #
    # In `text` mode every printable character -- typed or pasted --
    # goes through one queue and out via Machine.key(), which builds
    # the make, the break and any shift from sw/keymap.asm itself. The
    # OS has already applied the user's layout, so a Belgian keyboard's
    # quote arrives as a quote instead of whatever sits on that key in
    # the US table below. One character leaves per frame, and only when
    # the PS/2 FIFO is empty, so nothing can overrun -- a paste is just
    # a long queue.
    #
    # The keys that produce no text -- Return, Backspace, Escape, the
    # cursors, Home and friends -- still go as physical make/break.
    typing = deque()
    pause_down = False
    # pygame ships with key repeat OFF: a held Backspace deletes one
    # character, a held cursor key moves one cell, and it feels dead.
    # PC-keyboard rates; the raw ps2 mode is immune, its handler
    # ignores repeat KEYDOWNs via the `pressed` set.
    pygame.key.set_repeat(400, 40)
    TEXT_SPECIALS = {
        'return', 'backspace', 'tab', 'escape', 'up', 'down', 'left',
        'right', 'home', 'end', 'delete', 'insert', 'page up',
        'page down', 'pause', 'break',
    }

    def clipboard():
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            text = root.clipboard_get()
            root.destroy()
            return text
        except Exception:
            return ""

    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3
                    and args.keys == 'text'):
                # Right click pastes: the clipboard joins the same queue
                # typing uses, so pacing and layout are already solved.
                for ch in clipboard().replace('\r\n', '\r') \
                                     .replace('\n', '\r'):
                    typing.append(ch)
            elif ev.type == pygame.TEXTINPUT and args.keys == 'text':
                for ch in ev.text:
                    typing.append(ch)
            elif ev.type in (pygame.KEYDOWN, pygame.KEYUP):
                name = pygame.key.name(ev.key)
                down = ev.type == pygame.KEYDOWN
                if args.debug_keys:
                    print("%s name=%r key=%d scancode=%d mod=%04x"
                          % ('DOWN' if down else 'UP  ', name, ev.key,
                             getattr(ev, 'scancode', -1), ev.mod),
                          flush=True)
                if name == 'f11':
                    if down:
                        m.press_break()
                    continue
                if name == 'f12':
                    if down:
                        print(save_shot(m, args.shot or 'build/cool8.png'))
                    continue
                if args.keys == 'text':
                    # Break is Ctrl+Pause -- the SAME chord as the real
                    # board's keyboard. Windows reports that chord as
                    # VK_CANCEL ('break'), not 'pause', and some SDL
                    # builds deliver the Pause key only on RELEASE -- so
                    # the match is by name, keycode and HID scancode,
                    # and fires on the release too if the press never
                    # arrived. It goes straight into the port, ahead of
                    # any queued typing. Ctrl+C is the serial spelling.
                    # Measured on the bench, not assumed: Windows
                    # delivers plain Pause as name 'break'/scancode 72,
                    # and Ctrl+Pause as name 'scroll lock'/scancode 71
                    # -- a different key entirely. Both identities are
                    # matched; the ctrl test below keeps plain Pause
                    # (and real Scroll Lock, unchorded) inert.
                    is_pause = (name in ('pause', 'break', 'cancel',
                                         'scroll lock')
                                or ev.key in (pygame.K_PAUSE,
                                              pygame.K_BREAK,
                                              pygame.K_SCROLLLOCK)
                                or getattr(ev, 'scancode', 0) in (71, 72))
                    if is_pause and (ev.mod & pygame.KMOD_CTRL):
                        if down or not pause_down:
                            m.scancode([0xE0, 0x7E, 0xE0, 0xF0, 0x7E])
                        pause_down = down
                        continue
                    if down and name == 'c' and (ev.mod & pygame.KMOD_CTRL):
                        m.uart.feed(b'\x03')
                        continue
                    # Printables arrive as TEXTINPUT above; feeding them
                    # here as well would double every keystroke.
                    if name in TEXT_SPECIALS and down:
                        typing.append({'return': '\r', 'backspace': '\x08',
                                       'tab': '\t', 'escape': '\x1b',
                                       'up': 'K_UP', 'down': 'K_DOWN',
                                       'left': 'K_LEFT', 'right': 'K_RIGHT',
                                       'home': 'K_HOME', 'end': 'K_END',
                                       'delete': 'K_DEL', 'insert': 'K_INS',
                                       }.get(name, ''))
                    continue
                code = SET2.get(name)
                if code is not None and args.keys in ('ps2', 'both'):
                    # A held key does not repeat on this machine: the
                    # port delivers what the keyboard sends and a typematic
                    # repeat is the keyboard's own, which nothing here has.
                    if down and name not in pressed:
                        m.kbd.feed(make_code(code))
                        pressed.add(name)
                    elif not down:
                        m.kbd.feed(break_code(code))
                        pressed.discard(name)
                if down and args.keys in ('uart', 'both'):
                    ch = ascii_for(name, ev.mod & pygame.KMOD_SHIFT)
                    if ch:
                        m.uart.feed(ch.encode('latin-1'))

        # One queued character per frame, and only into an empty FIFO:
        # a paste of a whole program cannot overrun anything, it just
        # types fast.
        if typing and not m.kbd.q:
            item = typing.popleft()
            if item:
                try:
                    m.key([item])
                except KeyError:
                    pass                # no such key on this machine

        m.run_frame()

        out = m.uart.take()
        if out:
            sys.stdout.write(out.decode('latin-1'))
            sys.stdout.flush()

        samples = m.sound.take()
        if wav:
            wav.writeframes(samples)
        if channel is not None and samples:
            # Unsigned 8-bit level to signed 16-bit, which is what the
            # mixer was opened for. Silence is $80 and becomes zero.
            pcm = (np.frombuffer(samples, dtype=np.uint8).astype(np.int16)
                   - 128) * 256
            if mix_ch > 1:
                pcm = np.repeat(pcm[:, None], mix_ch, axis=1)
            snd = pygame.sndarray.make_sound(np.ascontiguousarray(pcm))
            if channel.get_queue() is None:
                channel.queue(snd)

        frame = vid.render_np(m)
        pygame.surfarray.blit_array(surf, rgb_array(frame, np).swapaxes(0, 1))
        if args.scale == 1:
            screen.blit(surf, (0, 0))
        else:
            pygame.transform.scale(surf, (w, h), screen)
        pygame.display.flip()

        shown += 1
        if args.frames and shown >= args.frames:
            running = False
        if shown % 10 == 0:
            real = shown / 60.0
            wall = time.time() - t0
            pygame.display.set_caption(
                f"COOL8 — {real / wall * 100:.0f}% of real time, "
                f"{shown / wall:.1f} fps")
        clock.tick(60)

    if wav:
        wav.close()
    if args.flash:
        m.flash.flush()
    pygame.quit()
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="COOL8 with a screen, a keyboard and a speaker")
    ap.add_argument("--scale", type=int, default=2, choices=(1, 2, 3),
                    help="window size; the machine is always 640x480")
    ap.add_argument("--load", help="a binary to place in RAM and run")
    ap.add_argument("--at", default="0x0200", help="where to place it")
    ap.add_argument("--flash", help="a file used as the 8 MB flash")
    ap.add_argument("--wav", help="record the sound engine's output")
    ap.add_argument("--shot", help="where F12 writes, or the headless shot")
    ap.add_argument("--keys", default="text",
                    choices=("text", "ps2", "uart", "both"),
                    help="text (default): what you type is what arrives, "
                         "on any keyboard layout -- printable characters "
                         "come from the OS as text and are encoded with "
                         "the machine's own keymap; specials go physical. "
                         "ps2 is the raw US-position path games may want "
                         "for held keys; uart/both are the serial console")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--debug-keys", action="store_true",
                    help="print every key event: name, keycode, "
                         "scancode, modifiers")
    ap.add_argument("--headless", action="store_true",
                    help="no window: run, then dump the screen and console")
    ap.add_argument("--frames", type=int, default=0,
                    help="stop after this many frames (headless: 120)")
    args = ap.parse_args()

    if args.headless:
        return run_headless(args)
    try:
        import pygame                            # noqa: F401
    except ImportError:
        sys.exit("pygame is needed for the window.\n"
                 "    pip install pygame\n"
                 "or run with --headless, which needs nothing.")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
