"""galaga_sound.py -- Galaga (Namco, 1981) sound CPU (Z80 #3) music/SFX data
and a tick-accurate re-implementation of its driver.

Sources
  * neiderm/arcade galag/galagao_ASxxx/rom0/gg1-7.s (commented reassemblable
    disassembly of gg1-7.2c, MAME set `galagao`); hackbar/galaga rom0/gg1-7.s is
    byte-for-byte the same file.
  * computerarcheology.com Arcade/Galaga/CPU3 listing.  Its hex column rebuilds
    to a 4096-byte image with CRC32 b07f0aa4 / SHA1 7528644a8480d0be2d0d37069515ed319e94778f,
    i.e. MAME's `3700g.bin` (Midway sets galagamw/galagamf).  Every table below
    was generated from those verified bytes; the data region is identical to
    neiderm's gg1-7 source apart from a constant +0x27 address shift and the
    ROM checksum byte.
  * MAME src/devices/sound/namco.cpp (namco_wsg_device::pacman_sound_w,
    clock handling) and src/mame/namco/galaga.cpp (NAMCO_WSG clock
    MASTER_CLOCK/6/32 = 96 kHz, cpu3_interrupt_callback NMI at scanlines 64 and 192,
    screen 18.432 MHz/3, 384 x 264 -> 60.606 Hz).

Driver model (see sound_spec.md for the prose):
  * one tick = one NMI = 2 per video frame = 121.2121 Hz;
  * every tick all 16 WSG frequency/volume shadow bytes are cleared, then every
    active sound rewrites its voice(s) in a fixed order (later wins);
  * a note lasts (TEMPO[id] * dur) & 0xFF ticks (0 -> 256);
  * WSG frequency register = (NOTE_BASE[lo] >> hi) << 4, Hz = reg * 96000 / 2**20.

Public API
  SOUNDS                    per-id description (name, kind, tempo, voices with header/notes)
  render(sound_id, ...)     per voice list of (frame, hz_or_None, volume) at 60 Hz
  render_ticks(sound_id, ...) the same at driver-tick resolution, with WSG register values
  note_hz(note_byte)        Hz of a note byte (None for rest)
  target_increment(hz)      increment for the target machine (Hz = inc * 0.4993)
  Driver                    the emulated driver itself, for combinations of sounds
"""

import math
import zlib

# ---- data section: generated from bytes 0x06D0-0x0F54 of 3700g.bin (== gg1-7.2c 0x06A9-0x0F2D) ----
DATA_REGION_CRC32_3700G = 0x251F8461   # crc32 of that region, pointers in 3700g addressing

# d_06A9: 13 words, indexed by low nibble of the note byte (0x0C -> 0x0000 = rest)
NOTE_BASE = (0x8150, 0x8900, 0x9126, 0x99C8, 0xA2EC, 0xAC9D, 0xB6E0, 0xC1C0, 0xCD45, 0xD97A, 0xE669, 0xF41C, 0x0000)

# d_06C3: formation-pulse tables, 32 words:
#   [0:8] expanding increments, [8:16] contracting increments,
#   [16:24] expanding start values, [24:32] contracting start values
FORMATION_WORDS = (
    0x0130, 0x0168, 0x0136, 0x01A8, 0x0168, 0x0200, 0x01AC, 0x0208,
    0xFE00, 0xFE58, 0xFE08, 0xFE98, 0xFE58, 0xFED0, 0xFE98, 0xFED6,
    0x5B00, 0x6C00, 0x5B00, 0x7E00, 0x6C00, 0x9700, 0x8100, 0x9900,
    0xD900, 0xB600, 0xD900, 0x9700, 0xB600, 0x7E00, 0x9900, 0x8100,
)

# d_0703: per sound id -> (first stream index, number of voices, first voice)
SND_PARMS = (
    (0x00, 1, 0),  # 00
    (0x01, 1, 1),  # 01
    (0x02, 1, 1),  # 02
    (0x03, 1, 1),  # 03
    (0x04, 1, 1),  # 04
    (0x05, 1, 0),  # 05
    (0x06, 1, 0),  # 06
    (0x20, 3, 0),  # 07
    (0x0A, 3, 0),  # 08
    (0x0D, 3, 0),  # 09
    (0x07, 3, 0),  # 0A
    (0x13, 3, 0),  # 0B
    (0x16, 3, 0),  # 0C
    (0x19, 3, 0),  # 0D
    (0x1C, 3, 0),  # 0E
    (0x1F, 1, 2),  # 0F
    (0x2C, 3, 0),  # 10
    (0x10, 3, 0),  # 11
    (0x23, 1, 0),  # 12
    (0x24, 1, 0),  # 13
    (0x25, 3, 0),  # 14
    (0x28, 1, 0),  # 15
    (0x29, 3, 0),  # 16
)

# d_0748: 47 stream pointers (gg1-7 addresses; add 0x27 for 3700g/Midway)
STREAM_PTR = (
    0x07BD, 0x0814, 0x07F2, 0x07BE, 0x085E, 0x0878, 0x088C, 0x09D2,
    0x09E2, 0x09F2, 0x099C, 0x09AE, 0x09C0, 0x0A02, 0x0A46, 0x0A8A,
    0x0AB6, 0x0AFA, 0x0B3E, 0x08A0, 0x08EC, 0x0936, 0x0C5C, 0x0CEA,
    0x0D38, 0x0966, 0x0978, 0x098A, 0x08A0, 0x08A0, 0x08A0, 0x0C08,
    0x0B6A, 0x0BA0, 0x0BD6, 0x0BF4, 0x0C08, 0x0D6C, 0x0DE0, 0x0E5C,
    0x0D5E, 0x0CE0, 0x0D2E, 0x0D54, 0x0E9E, 0x0EDA, 0x0F16,
)

# d_07A6: tempo multiplier per sound id (ticks per duration unit)
TEMPO = (0x04, 0x02, 0x02, 0x02, 0x02, 0x04, 0x04, 0x0A, 0x07, 0x0C, 0x0B, 0x04, 0x0A, 0x0D, 0x04, 0x01, 0x04, 0x0C, 0x02, 0x06, 0x05, 0x02, 0x0A)

# Note streams keyed by gg1-7 address: (header=(env, decay, wave), ((note, dur), ...)).
# Each is terminated by 0xFF in ROM (not stored). d_07BD is a bare 0xFF (unused stream 0).
STREAMS = {
    0x07BD: None,
    0x07BE: ((0x00, 0x00, 0x06), (
        (0x71, 1), (0x72, 1), (0x73, 1), (0x75, 1), (0x74, 1), (0x73, 1), (0x72, 1), (0x71, 1),
        (0x70, 1), (0x8B, 1), (0x8A, 1), (0x0C, 4), (0x86, 1), (0x87, 1), (0x88, 1), (0x89, 1),
        (0x8A, 1), (0x89, 1), (0x88, 1), (0x87, 1), (0x86, 1), (0x85, 1), (0x84, 1), (0x83, 1),
    )),
    0x07F2: ((0x00, 0x00, 0x04), (
        (0x88, 1), (0x8A, 1), (0x70, 1), (0x71, 1), (0x73, 1), (0x75, 1), (0x77, 1), (0x78, 1),
        (0x0C, 6), (0x74, 1), (0x73, 1), (0x72, 1), (0x71, 1), (0x70, 1), (0x8B, 1),
    )),
    0x0814: ((0x00, 0x00, 0x07), (
        (0x89, 1), (0x8A, 1), (0x8B, 1), (0x0C, 1), (0x70, 1), (0x71, 1), (0x72, 1), (0x0C, 1),
        (0x73, 1), (0x74, 1), (0x75, 1), (0x0C, 3), (0x8B, 1), (0x70, 1), (0x71, 1), (0x0C, 1),
        (0x72, 1), (0x73, 1), (0x74, 1), (0x0C, 1), (0x75, 1), (0x76, 1), (0x77, 1), (0x0C, 3),
        (0x71, 1), (0x72, 1), (0x73, 1), (0x0C, 1), (0x74, 1), (0x75, 1), (0x76, 1), (0x0C, 1),
        (0x77, 1), (0x78, 1), (0x79, 1),
    )),
    0x085E: ((0x00, 0x00, 0x05), (
        (0x71, 1), (0x72, 1), (0x73, 1), (0x0C, 1), (0x74, 1), (0x75, 1), (0x76, 1), (0x0C, 1),
        (0x77, 1), (0x78, 1), (0x79, 1),
    )),
    0x0878: ((0x00, 0x00, 0x04), (
        (0x61, 1), (0x7A, 1), (0x60, 1), (0x78, 1), (0x7A, 1), (0x76, 1), (0x78, 1), (0x75, 1),
    )),
    0x088C: ((0x00, 0x00, 0x00), (
        (0x76, 1), (0x79, 1), (0x60, 1), (0x63, 1), (0x66, 1), (0x63, 1), (0x60, 1), (0x79, 1),
    )),
    0x08A0: ((0x00, 0x00, 0x07), (
        (0x81, 8), (0x81, 1), (0x86, 3), (0x88, 9), (0x8B, 3), (0x8A, 9), (0x86, 3), (0x88, 9),
        (0x73, 3), (0x71, 9), (0x86, 3), (0x88, 9), (0x8B, 3), (0x8A, 9), (0x86, 3), (0x71, 9),
        (0x75, 3), (0x76, 9), (0x74, 3), (0x72, 9), (0x71, 3), (0x8B, 9), (0x89, 3), (0x88, 9),
        (0x84, 3), (0x74, 9), (0x76, 3), (0x74, 9), (0x71, 3), (0x73, 4), (0x8B, 4), (0x88, 4),
        (0x71, 4), (0x8A, 4), (0x88, 4), (0x0C, 16),
    )),
    0x08EC: ((0x00, 0x00, 0x06), (
        (0x8A, 9), (0x81, 3), (0x88, 9), (0x83, 3), (0x86, 9), (0x81, 3), (0x83, 9), (0x85, 3),
        (0x8A, 9), (0x81, 3), (0x88, 9), (0x83, 3), (0x86, 9), (0x81, 3), (0x88, 9), (0x71, 3),
        (0x72, 9), (0x71, 3), (0x8B, 9), (0x89, 3), (0x88, 9), (0x86, 3), (0x84, 9), (0x88, 3),
        (0x89, 9), (0x8B, 3), (0x89, 9), (0x86, 3), (0x8B, 4), (0x88, 4), (0x83, 4), (0x88, 4),
        (0x85, 4), (0x83, 4), (0x0C, 16),
    )),
    0x0936: ((0x00, 0x00, 0x07), (
        (0x81, 12), (0x83, 9), (0x86, 3), (0x85, 12), (0x81, 12), (0x86, 12), (0x88, 9), (0x8B, 3),
        (0x8A, 12), (0x88, 12), (0x89, 12), (0x88, 9), (0x86, 3), (0x84, 12), (0x89, 12), (0x74, 12),
        (0x71, 9), (0x89, 3), (0x88, 12), (0x71, 9), (0x8A, 3), (0x0C, 16),
    )),
    0x0966: ((0x02, 0x00, 0x03), (
        (0x78, 2), (0x0C, 1), (0x78, 1), (0x79, 1), (0x7B, 1), (0x61, 3), (0x0C, 3),
    )),
    0x0978: ((0x02, 0x00, 0x03), (
        (0x73, 2), (0x0C, 1), (0x73, 1), (0x74, 1), (0x76, 1), (0x78, 3), (0x0C, 2),
    )),
    0x098A: ((0x02, 0x00, 0x03), (
        (0x70, 2), (0x0C, 1), (0x70, 1), (0x71, 1), (0x73, 1), (0x75, 3), (0x0C, 2),
    )),
    0x099C: ((0x01, 0x00, 0x04), (
        (0x78, 1), (0x7A, 1), (0x63, 1), (0x78, 1), (0x7A, 1), (0x63, 1), (0x65, 3),
    )),
    0x09AE: ((0x01, 0x00, 0x05), (
        (0x73, 1), (0x78, 1), (0x7A, 1), (0x73, 1), (0x78, 1), (0x7A, 1), (0x60, 3),
    )),
    0x09C0: ((0x01, 0x00, 0x07), (
        (0x8A, 1), (0x73, 1), (0x78, 1), (0x8A, 1), (0x73, 1), (0x78, 1), (0x7A, 3),
    )),
    0x09D2: ((0x01, 0x06, 0x04), (
        (0x7A, 1), (0x78, 1), (0x7A, 1), (0x61, 1), (0x65, 1), (0x68, 3),
    )),
    0x09E2: ((0x01, 0x06, 0x04), (
        (0x78, 1), (0x75, 1), (0x78, 1), (0x7A, 1), (0x61, 1), (0x65, 3),
    )),
    0x09F2: ((0x01, 0x06, 0x04), (
        (0x75, 1), (0x71, 1), (0x75, 1), (0x78, 1), (0x7A, 1), (0x60, 3),
    )),
    0x0A02: ((0x02, 0x04, 0x03), (
        (0x7A, 1), (0x76, 1), (0x78, 1), (0x75, 1), (0x76, 1), (0x73, 1), (0x75, 1), (0x72, 1),
        (0x73, 1), (0x8A, 1), (0x8B, 1), (0x88, 1), (0x86, 1), (0x85, 1), (0x83, 1), (0x82, 1),
        (0x83, 1), (0x86, 1), (0x85, 1), (0x88, 1), (0x86, 1), (0x8A, 1), (0x88, 1), (0x8B, 1),
        (0x8A, 1), (0x73, 1), (0x72, 1), (0x73, 1), (0x75, 1), (0x8A, 1), (0x70, 1), (0x72, 1),
    )),
    0x0A46: ((0x02, 0x04, 0x03), (
        (0x76, 1), (0x73, 1), (0x75, 1), (0x72, 1), (0x73, 1), (0x70, 1), (0x72, 1), (0x8A, 1),
        (0x8B, 1), (0x86, 1), (0x88, 1), (0x85, 1), (0x83, 1), (0x82, 1), (0x80, 1), (0x9A, 1),
        (0x9A, 1), (0x83, 1), (0x82, 1), (0x85, 1), (0x83, 1), (0x86, 1), (0x85, 1), (0x88, 1),
        (0x86, 1), (0x8A, 1), (0x88, 1), (0x8B, 1), (0x8A, 1), (0x88, 1), (0x86, 1), (0x85, 1),
    )),
    0x0A8A: ((0x02, 0x10, 0x03), (
        (0x93, 2), (0x9A, 2), (0x83, 3), (0x9A, 1), (0x98, 1), (0x96, 1), (0x95, 1), (0x93, 2),
        (0x95, 3), (0x96, 2), (0x98, 2), (0x9A, 2), (0x9B, 2), (0x9A, 2), (0x98, 1), (0x96, 1),
        (0x95, 1), (0x92, 1), (0x93, 1), (0x95, 1),
    )),
    0x0AB6: ((0x02, 0x04, 0x03), (
        (0x7A, 1), (0x77, 1), (0x78, 1), (0x75, 1), (0x77, 1), (0x73, 1), (0x75, 1), (0x72, 1),
        (0x73, 1), (0x8A, 1), (0x80, 1), (0x88, 1), (0x87, 1), (0x85, 1), (0x83, 1), (0x82, 1),
        (0x83, 1), (0x87, 1), (0x85, 1), (0x88, 1), (0x87, 1), (0x8A, 1), (0x88, 1), (0x80, 1),
        (0x8A, 1), (0x73, 1), (0x72, 1), (0x73, 1), (0x75, 1), (0x8A, 1), (0x70, 1), (0x72, 1),
    )),
    0x0AFA: ((0x02, 0x04, 0x03), (
        (0x77, 1), (0x73, 1), (0x75, 1), (0x72, 1), (0x73, 1), (0x70, 1), (0x72, 1), (0x8A, 1),
        (0x80, 1), (0x87, 1), (0x88, 1), (0x85, 1), (0x83, 1), (0x82, 1), (0x80, 1), (0x9A, 1),
        (0x9A, 1), (0x83, 1), (0x82, 1), (0x85, 1), (0x83, 1), (0x87, 1), (0x85, 1), (0x88, 1),
        (0x87, 1), (0x8A, 1), (0x88, 1), (0x80, 1), (0x8A, 1), (0x88, 1), (0x87, 1), (0x85, 1),
    )),
    0x0B3E: ((0x02, 0x10, 0x03), (
        (0x93, 2), (0x9A, 2), (0x83, 3), (0x9A, 1), (0x98, 1), (0x97, 1), (0x95, 1), (0x93, 2),
        (0x95, 3), (0x97, 2), (0x98, 2), (0x9A, 2), (0x90, 2), (0x9A, 2), (0x98, 1), (0x97, 1),
        (0x95, 1), (0x92, 1), (0x93, 1), (0x95, 1),
    )),
    0x0B6A: ((0x02, 0x04, 0x03), (
        (0x7A, 1), (0x76, 1), (0x78, 1), (0x75, 1), (0x76, 1), (0x73, 1), (0x75, 1), (0x72, 1),
        (0x73, 1), (0x8A, 1), (0x8A, 1), (0x88, 1), (0x86, 1), (0x85, 1), (0x83, 1), (0x82, 1),
        (0x83, 1), (0x85, 1), (0x86, 1), (0x88, 1), (0x86, 1), (0x8A, 1), (0x70, 1), (0x72, 1),
        (0x73, 4),
    )),
    0x0BA0: ((0x02, 0x04, 0x03), (
        (0x76, 1), (0x73, 1), (0x75, 1), (0x72, 1), (0x73, 1), (0x70, 1), (0x72, 1), (0x8A, 1),
        (0x8A, 1), (0x86, 1), (0x86, 1), (0x85, 1), (0x83, 1), (0x82, 1), (0x80, 1), (0x9A, 1),
        (0x9A, 1), (0x8B, 1), (0x80, 1), (0x82, 1), (0x83, 1), (0x85, 1), (0x86, 1), (0x88, 1),
        (0x8A, 4),
    )),
    0x0BD6: ((0x02, 0x10, 0x03), (
        (0x73, 2), (0x75, 2), (0x76, 2), (0x75, 2), (0x73, 2), (0x72, 2), (0x70, 2), (0x72, 2),
        (0x73, 2), (0x8B, 2), (0x8A, 2), (0x86, 2), (0x83, 4),
    )),
    0x0BF4: ((0x00, 0x00, 0x04), (
        (0x71, 4), (0x73, 4), (0x71, 4), (0x73, 4), (0x76, 4), (0x78, 4), (0x76, 4), (0x78, 4),
    )),
    0x0C08: ((0x00, 0x00, 0x06), (
        (0x56, 1), (0x55, 1), (0x54, 1), (0x53, 1), (0x52, 1), (0x51, 1), (0x50, 1), (0x6B, 1),
        (0x6A, 1), (0x69, 1), (0x68, 1), (0x67, 1), (0x66, 1), (0x65, 1), (0x64, 1), (0x63, 1),
        (0x62, 1), (0x61, 1), (0x60, 1), (0x7B, 1), (0x7A, 1), (0x79, 1), (0x78, 1), (0x77, 1),
        (0x76, 1), (0x75, 1), (0x74, 1), (0x73, 1), (0x72, 1), (0x71, 1), (0x70, 1), (0x8B, 1),
        (0x8A, 1), (0x89, 1), (0x88, 1), (0x87, 1), (0x86, 1), (0x85, 1), (0x84, 1), (0x83, 1),
    )),
    0x0C5C: ((0x02, 0x04, 0x05), (
        (0x60, 1), (0x78, 1), (0x75, 1), (0x71, 1), (0x60, 1), (0x78, 1), (0x75, 1), (0x71, 1),
        (0x60, 1), (0x78, 1), (0x75, 1), (0x71, 1), (0x60, 1), (0x78, 1), (0x75, 1), (0x71, 1),
        (0x60, 1), (0x78, 1), (0x75, 1), (0x71, 1), (0x60, 1), (0x78, 1), (0x75, 1), (0x71, 1),
        (0x60, 1), (0x0C, 1), (0x78, 1), (0x7A, 1), (0x75, 1), (0x78, 1), (0x73, 1), (0x75, 1),
        (0x61, 1), (0x7A, 1), (0x76, 1), (0x73, 1), (0x61, 1), (0x7A, 1), (0x76, 1), (0x73, 1),
        (0x61, 1), (0x7A, 1), (0x76, 1), (0x73, 1), (0x61, 1), (0x7A, 1), (0x76, 1), (0x73, 1),
        (0x61, 1), (0x79, 1), (0x76, 1), (0x73, 1), (0x61, 1), (0x79, 1), (0x76, 1), (0x73, 1),
        (0x61, 1), (0x0C, 1), (0x79, 1), (0x61, 1), (0x78, 1), (0x79, 1), (0x75, 1), (0x78, 1),
    )),
    0x0CE0: ((0x02, 0x02, 0x05), (
        (0x60, 1), (0x60, 1), (0x60, 1),
    )),
    0x0CEA: ((0x02, 0x04, 0x05), (
        (0x61, 2), (0x78, 2), (0x78, 2), (0x61, 2), (0x78, 2), (0x78, 2), (0x61, 2), (0x78, 2),
        (0x78, 2), (0x61, 2), (0x78, 2), (0x78, 2), (0x61, 2), (0x78, 2), (0x7A, 2), (0x75, 2),
        (0x63, 2), (0x7A, 2), (0x7A, 2), (0x63, 2), (0x7A, 2), (0x7A, 2), (0x63, 2), (0x7A, 2),
        (0x79, 2), (0x63, 2), (0x79, 2), (0x79, 2), (0x63, 2), (0x79, 2), (0x76, 2), (0x73, 2),
    )),
    0x0D2E: ((0x02, 0x02, 0x05), (
        (0x78, 1), (0x78, 1), (0x78, 1),
    )),
    0x0D38: ((0x02, 0x10, 0x05), (
        (0x85, 6), (0x85, 6), (0x85, 6), (0x85, 6), (0x85, 4), (0x85, 4), (0x86, 6), (0x86, 6),
        (0x86, 6), (0x86, 6), (0x86, 4), (0x86, 4),
    )),
    0x0D54: ((0x02, 0x04, 0x05), (
        (0x81, 1), (0x81, 1), (0x81, 1),
    )),
    0x0D5E: ((0x02, 0x00, 0x07), (
        (0x65, 1), (0x0C, 1), (0x61, 1), (0x0C, 1), (0x63, 1),
    )),
    0x0D6C: ((0x02, 0x00, 0x05), (
        (0x7A, 5), (0x0C, 1), (0x7A, 1), (0x0C, 1), (0x7A, 3), (0x0C, 1), (0x78, 7), (0x0C, 1),
        (0x78, 7), (0x0C, 1), (0x78, 3), (0x0C, 1), (0x7B, 5), (0x0C, 1), (0x7B, 1), (0x0C, 1),
        (0x7B, 3), (0x0C, 1), (0x7A, 7), (0x0C, 1), (0x7A, 7), (0x0C, 1), (0x7A, 3), (0x0C, 1),
        (0x7B, 1), (0x0C, 1), (0x7B, 1), (0x0C, 3), (0x7B, 1), (0x0C, 1), (0x7B, 3), (0x0C, 1),
        (0x61, 1), (0x0C, 1), (0x61, 1), (0x0C, 3), (0x61, 1), (0x0C, 1), (0x61, 3), (0x0C, 1),
        (0x61, 3), (0x0C, 1), (0x61, 3), (0x0C, 1), (0x63, 1), (0x0C, 1), (0x63, 1), (0x0C, 3),
        (0x63, 1), (0x0C, 1), (0x63, 3), (0x0C, 1), (0x63, 3), (0x0C, 1), (0x63, 3), (0x0C, 1),
    )),
    0x0DE0: ((0x02, 0x00, 0x03), (
        (0x86, 2), (0x8A, 2), (0x71, 2), (0x76, 2), (0x86, 2), (0x8A, 2), (0x71, 2), (0x76, 2),
        (0x86, 2), (0x8A, 2), (0x71, 2), (0x76, 2), (0x86, 2), (0x8A, 2), (0x71, 2), (0x76, 2),
        (0x86, 2), (0x8A, 2), (0x71, 2), (0x76, 2), (0x86, 2), (0x8A, 2), (0x71, 2), (0x76, 2),
        (0x86, 2), (0x8A, 2), (0x71, 2), (0x76, 2), (0x86, 2), (0x8A, 2), (0x71, 2), (0x76, 2),
        (0x77, 1), (0x0C, 1), (0x77, 1), (0x0C, 3), (0x77, 1), (0x0C, 1), (0x77, 3), (0x0C, 1),
        (0x69, 1), (0x0C, 1), (0x69, 1), (0x0C, 3), (0x69, 1), (0x0C, 1), (0x69, 3), (0x0C, 1),
        (0x69, 3), (0x0C, 1), (0x69, 3), (0x0C, 1), (0x8B, 2), (0x73, 2), (0x76, 2), (0x7B, 2),
        (0x7B, 2), (0x76, 2), (0x73, 2), (0x8B, 2),
    )),
    0x0E5C: ((0x00, 0x00, 0x02), (
        (0x86, 8), (0x81, 8), (0x86, 8), (0x81, 8), (0x86, 8), (0x81, 8), (0x86, 8), (0x81, 8),
        (0x82, 1), (0x0C, 1), (0x82, 1), (0x0C, 3), (0x82, 1), (0x0C, 1), (0x82, 3), (0x0C, 1),
        (0x84, 1), (0x0C, 1), (0x84, 1), (0x0C, 3), (0x84, 1), (0x0C, 1), (0x84, 3), (0x0C, 1),
        (0x84, 3), (0x0C, 1), (0x84, 3), (0x0C, 1), (0x7B, 8), (0x76, 4), (0x8B, 4),
    )),
    0x0E9E: ((0x00, 0x0C, 0x05), (
        (0x75, 12), (0x71, 12), (0x8A, 12), (0x86, 12), (0x0C, 9), (0x75, 3), (0x71, 9), (0x8A, 3),
        (0x86, 4), (0x8A, 4), (0x71, 4), (0x89, 4), (0x70, 4), (0x73, 4), (0x8B, 12), (0x73, 12),
        (0x76, 12), (0x78, 12), (0x0C, 9), (0x79, 3), (0x76, 9), (0x72, 3), (0x8B, 4), (0x89, 4),
        (0x86, 4), (0x72, 4), (0x89, 4), (0x76, 4),
    )),
    0x0EDA: ((0x00, 0x0C, 0x05), (
        (0x71, 12), (0x8A, 12), (0x86, 12), (0x85, 12), (0x0C, 9), (0x81, 3), (0x8A, 9), (0x86, 3),
        (0x85, 4), (0x86, 4), (0x8A, 4), (0x86, 4), (0x89, 4), (0x8B, 4), (0x88, 12), (0x8B, 12),
        (0x73, 12), (0x76, 12), (0x0C, 9), (0x76, 3), (0x72, 9), (0x8B, 3), (0x8A, 4), (0x86, 4),
        (0x82, 4), (0x8B, 4), (0x89, 4), (0x82, 4),
    )),
    0x0F16: ((0x00, 0x00, 0x03), (
        (0x75, 24), (0x75, 24), (0x75, 24), (0x71, 12), (0x75, 12), (0x73, 24), (0x73, 24), (0x72, 24),
        (0x76, 12), (0x78, 12),
    )),
}

# ---------------------------------------------------------------------------
# Rebuilt ROM image of the data region (gg1-7 addressing) and self-check
# ---------------------------------------------------------------------------

REGION_START = 0x06A9
REGION_END = 0x0F2E          # exclusive; ROM checksum byte follows (0xFA gg1-7, 0xFB 3700g)
PTR_SHIFT_3700G = 0x27


def _build_region(ptr_shift=0):
    out = bytearray()
    for v in NOTE_BASE:
        out += bytes((v & 0xFF, v >> 8))
    for v in FORMATION_WORDS:
        out += bytes((v & 0xFF, v >> 8))
    for t in SND_PARMS:
        out += bytes(t)
    for p in STREAM_PTR:
        p += ptr_shift
        out += bytes((p & 0xFF, p >> 8))
    out += bytes(TEMPO)
    for addr in sorted(STREAMS):
        s = STREAMS[addr]
        assert REGION_START + len(out) == addr, hex(addr)
        if s is None:
            out.append(0xFF)
            continue
        out += bytes(s[0])
        for n, d in s[1]:
            out += bytes((n, d))
        out.append(0xFF)
    assert REGION_START + len(out) == REGION_END
    return bytes(out)


_REGION = _build_region()
assert zlib.crc32(_build_region(PTR_SHIFT_3700G)) == DATA_REGION_CRC32_3700G, \
    "transcription does not match the 3700g.bin dump"


def rom_byte(addr):
    return _REGION[addr - REGION_START]


def rom_word(addr):
    return rom_byte(addr) | (rom_byte(addr + 1) << 8)


# ---------------------------------------------------------------------------
# Timing and frequency constants
# ---------------------------------------------------------------------------

MASTER_CLOCK = 18432000
FRAME_HZ = MASTER_CLOCK / 3 / 384 / 264          # 60.6060... Hz
TICK_HZ = 2 * FRAME_HZ                           # 121.2121... Hz (NMI rate)
NMI_LINES = (64, 192)                            # of 264 lines per frame
WSG_CLOCK = MASTER_CLOCK / 6 / 32                # 96000 Hz
WSG_HZ_PER_UNIT = WSG_CLOCK / (1 << 20)          # 0.091552734375 Hz per unit of the 20-bit register
TARGET_HZ_PER_INC = 0.4993
TARGET_FRAME_HZ = 60.0


def wsg_reg_hz(reg20):
    return reg20 * WSG_HZ_PER_UNIT


def note_reg(note_byte):
    """20-bit WSG frequency register for a note byte (0 for rest 0x0C)."""
    lo, hi = note_byte & 0x0F, note_byte >> 4
    base = rom_word(0x06A9 + 2 * lo)
    return ((base >> hi) & 0xFFFF) << 4


def note_hz(note_byte):
    if note_byte == 0x0C:
        return None
    r = note_reg(note_byte)
    return wsg_reg_hz(r) if r else None


def target_increment(hz):
    return None if hz is None else int(round(hz / TARGET_HZ_PER_INC))


_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')


def hz_name(hz, cents=False):
    if hz is None:
        return '--'
    m = 69 + 12 * math.log2(hz / 440.0)
    n = int(round(m))
    s = '%s%d' % (_NAMES[n % 12], n // 12 - 1)
    if cents:
        s += '%+dc' % int(round((m - n) * 100))
    return s


def note_name(note_byte, cents=False):
    return hz_name(note_hz(note_byte), cents)


# ---------------------------------------------------------------------------
# Sound catalogue
# ---------------------------------------------------------------------------

# kind: 'pulse'   formation pulse, special code (not a note stream)
#       'retrig'  c_03F4/c_044A: count register is a trigger, cleared by the driver; retrigger restarts
#       'oneshot' c_04A2: plays while count register != 0; driver clears it at the end
#                  (08 decrements -> repeats; 0C decrements and chains 16; 14 chains 13)
#       'loop'    c_0375: plays and restarts while count register != 0 (main CPU stops it)
SOUND_INFO = {
    0x00: ('formation pulse (breathing formation, voice 0 sweeps)', 'pulse'),
    0x01: ('boss Galaga destroyed (blue boss, colour map 1)', 'retrig'),
    0x02: ('enemy hit, colour map 2 (butterfly/red per disassembly comment)', 'retrig'),
    0x03: ('enemy hit, colour map 3 (bee/yellow per disassembly comment)', 'retrig'),
    0x04: ('boss Galaga first hit (green boss, not destroyed)', 'retrig'),
    0x05: ('tractor beam, boss lowering beam', 'loop'),
    0x06: ('tractor beam, fighter being captured', 'loop'),
    0x07: ('captured (red) fighter shot by the player', 'oneshot'),
    0x08: ('coin / credit', 'oneshot'),
    0x09: ('fighter captured music', 'loop'),
    0x0A: ('extra fighter awarded', 'oneshot'),
    0x0B: ('game start theme', 'oneshot'),
    0x0C: ('high score 1st place (name entry) tune; chains 16', 'oneshot'),
    0x0D: ('challenging stage start', 'oneshot'),
    0x0E: ('challenging stage results (not perfect): start theme as 3-voice echo', 'oneshot'),
    0x0F: ('fighter shot', 'retrig'),
    0x10: ('high score 2nd-5th place (name entry) tune', 'loop'),
    0x11: ('rescued fighter music', 'loop'),
    0x12: ('enemy transform ("bonus bee")', 'oneshot'),
    0x13: ('enemy dive', 'retrig'),
    0x14: ('challenging stage PERFECT; chains 13', 'oneshot'),
    0x15: ('stage badge click', 'oneshot'),
    0x16: ('tail chord for 0C', 'oneshot'),
}


def _stream_index_list(sid):
    idx, n, v = SND_PARMS[sid]
    return [(idx + k, v + k) for k in range(n)]


def _describe():
    d = {}
    for sid in range(0x17):
        name, kind = SOUND_INFO[sid]
        voices = []
        if kind != 'pulse':
            for idx, voice in _stream_index_list(sid):
                addr = STREAM_PTR[idx]
                hdr, notes = STREAMS[addr]
                voices.append(dict(stream_index=idx, addr=addr, voice=voice,
                                   header=hdr, notes=notes))
        d[sid] = dict(name=name, kind=kind, tempo=TEMPO[sid], voices=voices)
    return d


SOUNDS = _describe()


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------

def _rrca4(x):
    x &= 0xFF
    return ((x >> 4) | (x << 4)) & 0xFF


_FREQ_BASE = (0x01, 0x06, 0x0B)     # b_9A60 offsets of each voice's 4 frequency nibbles
_VOL = (0x05, 0x0A, 0x0F)


class Driver:
    """RAM-level model of the sound CPU's NMI routine (c_nmi_proc and callees).

    revision '3700g' (Midway, CRC-verified) or 'gg1-7' (Namco original,
    neiderm source). They differ only in how 07 interacts with other sounds
    and in the 0E volume override on its final tick.
    """

    def __init__(self, revision='3700g'):
        assert revision in ('3700g', 'gg1-7')
        self.rev = revision
        self.st = [0] * 0x30          # b_9A00: ticks into current note, per stream index
        self.di = [0] * 0x30          # b_9A30: data offset (even), per stream index
        self.sh = [0] * 16            # b_9A60: WSG freq/vol shadow (6810-681F)
        self.wave = [0, 0, 0]         # b_9A70[0..2]
        self.m70 = [0] * 16           # b_9A70[0x0C..0x0F] beam counters live here
        self.fm_sign = 0              # b_9A80[0]
        self.fm_step = 0              # b_9A80[1]
        self.fm_ptr = 0               # b_9A80[2..3]
        self.fm_inc = 0               # b_9A80[4..5]
        self.fm_acc = 0               # b_9A80[6..7]
        self.fx = [0] * 0x20          # b_9AA0: count/enable registers (written by main CPU)
        self.act = [0] * 0x20         # b_9AC0: active flags
        self.signage = 1              # ds_9200_glbls[0x11] (main CPU): 1 expanding, 0xFF contracting
        self.credits_in = 0           # b_9A70[9] (main CPU)
        self.onset = [False, False, False]
        self._finished = 0            # b_9A70[8]

    # -- c_0550: one voice of one sound --------------------------------------
    def _voice(self, sid, idx, voice):
        st, di, sh = self.st, self.di, self.sh
        st[idx] = (st[idx] + 1) & 0xFF
        ptr = rom_word(0x0748 + 2 * idx)
        h0, h1, h2 = rom_byte(ptr), rom_byte(ptr + 1), rom_byte(ptr + 2)
        p = ptr + 3 + di[idx]
        nb = rom_byte(p)
        if nb == 0xFF:                                   # j_068B: close voice
            sh[_VOL[voice]] = 0
            self._finished = 1
            return
        f = (rom_word(0x06A9 + 2 * (nb & 0x0F)) >> (nb >> 4)) & 0xFFFF
        c, b = f & 0xFF, f >> 8
        fb = _FREQ_BASE[voice]
        sh[fb], sh[fb + 1], sh[fb + 2], sh[fb + 3] = c, _rrca4(c), b, _rrca4(b)
        s = st[idx]
        if nb == 0x0C:
            vol = 0
        else:
            vol = None
            if h0 == 1 and s < 6:
                vol = (s + s) & 0xFF                     # attack 2,4,6,8,10
            elif h0 >= 2 and s < 6:
                vol = (~s) & 0xFF                        # low nibble 15-s: 14,13,12,11,10
            if vol is None:
                if h1 == 0 or s < h1:
                    vol = 0x0A
                elif s - h1 >= 10:
                    vol = 0
                else:
                    vol = 10 - (s - h1)
        sh[_VOL[voice]] = vol
        self.wave[voice] = h2
        self.onset[voice] = (s == 1)
        length = (rom_byte(0x07A6 + sid) * rom_byte(p + 1)) & 0xFF
        if s == length:
            di[idx] = (di[idx] + 2) & 0xFF
            st[idx] = 0

    def _parms(self, sid):
        a = 0x0703 + 3 * sid
        idx, cnt, v = rom_byte(a), rom_byte(a + 1), rom_byte(a + 2)
        if sid == 0x0E:                                  # staggered echo entry
            x = self.di[0x1C]
            if x == 0:
                cnt = 1
            elif x == 1 or self.di[0x1D] == 0:
                cnt = 2
        return idx, cnt, v

    def _reset_streams(self, idx, cnt):
        for k in range(cnt):
            self.di[(idx + k) & 0xFF] = 0
            self.st[(idx + k) & 0xFF] = 0

    def _run(self, sid, idx, cnt, v):
        while True:
            self._voice(sid, idx, min(v, 2))
            cnt = (cnt - 1) & 0xFF
            if cnt == 0:
                break
            idx += 1
            v += 1
        if self._finished:
            self._finished = 0
            self.act[sid] = 0
            return True
        return False

    def _c0375(self, sid):                               # looping sounds
        idx, cnt, v = self._parms(sid)
        if self.act[sid] == 0:
            self.act[sid] = 1
            self._reset_streams(idx, cnt)
        self._run(sid, idx, cnt, v)

    def _c03f4(self, sid):                               # retriggerable start
        self.act[sid] = (self.act[sid] + 1) & 0xFF
        idx, cnt, v = self._parms(sid)
        self._reset_streams(idx, cnt)
        self._run(sid, idx, cnt, v)

    def _c044a(self, sid):                               # retriggerable continue
        idx, cnt, v = self._parms(sid)
        self._run(sid, idx, cnt, v)

    def _c04a2(self, sid):                               # one-shot
        idx, cnt, v = self._parms(sid)
        if self.act[sid] == 0:
            self.act[sid] = 1
            self._reset_streams(idx, cnt)
        if not self._run(sid, idx, cnt, v):
            return
        fx = self.fx
        if sid == 0x08:
            fx[8] = (fx[8] - 1) & 0xFF
        elif sid == 0x0C:
            fx[0x0C] = (fx[0x0C] - 1) & 0xFF
            if fx[0x0C] == 0 or (fx[0x0C] & 1):
                fx[0x16] = 1
        elif sid == 0x14:
            fx[0x14] = 0
            fx[0x13] = 1
        elif sid == 0x07 and self.rev == '3700g':
            for k in list(range(0, 8)) + [9] + list(range(0x0B, 0x17)):
                fx[k] = 0
                self.act[k] = 0
        else:
            fx[sid] = 0

    def _retrig(self, sid):
        if self.fx[sid]:
            self.fx[sid] = 0
            self._c03f4(sid)
        elif self.act[sid]:
            self._c044a(sid)

    def _loop(self, sid):
        if self.fx[sid]:
            self._c0375(sid)
        else:
            self.act[sid] = 0

    def _oneshot(self, sid):
        if self.fx[sid]:
            self._c04a2(sid)

    def _formation_load(self):
        hl = self.fm_ptr + 2 * self.fm_step
        self.fm_inc = rom_word(hl)
        self.fm_acc = rom_word(hl + 0x20)

    def _formation(self):
        if not self.fx[0]:
            return
        a = self.signage & 0xFF
        if a != self.fm_sign:
            self.fm_sign = a
            self.fm_ptr = 0x06C3 if ((a + 1) & 0xFF) else 0x06D3
            self.st[0] = 0
            self.fm_step = 0
            self._formation_load()
        else:
            self.st[0] = (self.st[0] + 1) & 0xFF
            if self.st[0] == 0x22:
                self.st[0] = 0
                self.fm_step = (self.fm_step + 1) & 0xFF
                self._formation_load()
        self.fm_acc = (self.fm_acc + self.fm_inc) & 0xFFFF
        h = self.fm_acc >> 8
        self.sh[1], self.sh[2] = h, _rrca4(h)
        self.sh[5] = 0x0A
        self.wave[0] = 0

    def tick(self):
        """One NMI. Returns ((reg20, vol, wave, onset) for voices 0, 1, 2)."""
        fx, act, sh = self.fx, self.act, self.sh
        self.onset = [False, False, False]
        if fx[0x18]:                                     # l_067A (never used by the game)
            self.__init__(self.rev)
            return self._outputs()
        for k in range(16):
            sh[k] = 0
        if fx[0x17]:                                     # sound off / reset
            for k in range(0x16):
                fx[k] = 0
            for k in range(0x17):
                act[k] = 0
            return self._outputs()
        if self.credits_in:
            fx[8] = (fx[8] + self.credits_in) & 0xFF
            self.credits_in = 0
        self._formation()
        for sid in (0x13, 0x0F, 0x03, 0x02, 0x04, 0x01):
            self._retrig(sid)
        self._oneshot(0x12)
        # 05: beam part 1, plus a volume ramp written to voice 2
        if fx[5]:
            self._c0375(5)
            m = self.m70
            m[0x0E] = (m[0x0E] + 1) & 0xFF
            if m[0x0E] >= 6:
                m[0x0E] = 0
                m[0x0C] = 0x0C if m[0x0C] < 4 else m[0x0C] - 1
            sh[0x0F] = m[0x0C]
        else:
            act[5] = 0
        # 06: beam part 2, plus a waveform counter written to voice 2
        if fx[6]:
            self._c0375(6)
            m = self.m70
            m[0x0F] = (m[0x0F] + 1) & 0xFF
            if m[0x0F] == 0x1C:
                m[0x0F] = 0
                m[0x0D] = (m[0x0D] + 1) & 0xFF
            self.wave[2] = m[0x0D]
        else:
            act[6] = 0
        self._loop(0x09)
        skip_to_coin = False
        if fx[7]:
            self._c04a2(7)
            skip_to_coin = (self.rev == '3700g')
        if not skip_to_coin:
            self._loop(0x11)
            self._oneshot(0x0D)
            if fx[0x0E]:
                self._c04a2(0x0E)
                if self.rev == '3700g' or fx[0x0E]:
                    sh[0x0A], sh[0x0F] = 9, 6
            self._oneshot(0x14)
            self._oneshot(0x15)
            self._oneshot(0x0A)
            self._oneshot(0x0B)
            self._loop(0x10)
            self._oneshot(0x0C)
            self._oneshot(0x16)
        self._oneshot(0x08)
        return self._outputs()

    def _outputs(self):
        sh = self.sh
        out = []
        for v in range(3):
            fb = _FREQ_BASE[v]
            reg = (sh[0] & 0xF) if v == 0 else 0
            for k in range(4):
                reg += (sh[fb + k] & 0xF) << (4 * (k + 1))
            out.append((reg, sh[_VOL[v]] & 0xF, self.wave[v] & 7, self.onset[v]))
        return tuple(out)

    def idle(self):
        return not any(self.fx[:0x17]) and not any(self.act[:0x17])


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

LOOP_IDS = (0x05, 0x06, 0x09, 0x10, 0x11)


def render_ticks(sound_id, count=None, revision='3700g', chain=True,
                 pulse_half_period_ticks=256, pulse_half_cycles=2, max_ticks=20000):
    """Run the driver for one sound in isolation.

    Returns a list of ticks; each tick is a tuple of 3 voices
    (wsg_reg20, volume, wave, onset).
      * one-shot/retrig sounds: until the driver is idle again (chains such as
        0C->16 and 14->13 are followed when chain=True);
      * loop sounds (05 06 09 10 11): exactly one cycle;
      * 00: `pulse_half_cycles` formation half-cycles of `pulse_half_period_ticks`
        (256 ticks = 32 formation steps x 4 frames x 2 NMIs, from main CPU f_1DE6).
    """
    d = Driver(revision)
    ticks = []
    if sound_id == 0x00:
        d.fx[0] = 1
        for hc in range(pulse_half_cycles):
            d.signage = 1 if hc % 2 == 0 else 0xFF
            for _ in range(pulse_half_period_ticks):
                ticks.append(d.tick())
        return ticks
    d.fx[sound_id] = 1 if count is None else count
    for _ in range(max_ticks):
        was_active = d.act[sound_id]
        ticks.append(d.tick())
        if sound_id in LOOP_IDS:
            if was_active and not d.act[sound_id]:
                break
        else:
            if not chain and not d.fx[sound_id] and not d.act[sound_id]:
                break
            if d.idle():
                break
    return ticks


def _tick_times(n):
    t = []
    for k in range(n):
        frame, half = divmod(k, 2)
        line = NMI_LINES[half] - NMI_LINES[0]
        t.append((frame + line / 264.0) / FRAME_HZ)
    return t


def quantise(ticks, realtime=True):
    """Tick list -> per voice [(frame, hz_or_None, vol)] at 60 Hz, one entry per frame.

    realtime=True maps real arcade time (121.21 ticks/s) onto 60 Hz frames;
    realtime=False maps exactly 2 ticks to 1 frame (1% slower).
    Within a frame the tick used per voice is the latest one that starts a note
    (so notes of >= 2 ticks are never dropped), else the first tick of the frame.
    """
    if not ticks:
        return [[], [], []]
    if realtime:
        times = _tick_times(len(ticks))
        fidx = [int(math.floor(t * TARGET_FRAME_HZ + 1e-9)) for t in times]
    else:
        fidx = [k // 2 for k in range(len(ticks))]
    nframes = fidx[-1] + 1
    buckets = [[] for _ in range(nframes)]
    for k, f in enumerate(fidx):
        buckets[f].append(k)
    voices = [[], [], []]
    for v in range(3):
        last = None
        for f, ks in enumerate(buckets):
            if not ks:
                k = last
            else:
                ons = [k for k in ks if ticks[k][v][3]]
                k = ons[-1] if ons else ks[0]
            last = k
            reg, vol = ticks[k][v][0], ticks[k][v][1]
            if reg == 0 or vol == 0:
                voices[v].append((f, None, 0))
            else:
                voices[v].append((f, wsg_reg_hz(reg), vol))
    return voices


def render(sound_id, count=None, realtime=True, revision='3700g', chain=True, **kw):
    """Per voice (0, 1, 2) list of (frame, frequency_hz or None, volume 0-15) at 60 Hz."""
    return quantise(render_ticks(sound_id, count, revision, chain, **kw), realtime)


def to_changes(voice_events):
    """Collapse a dense per-frame list to change events only."""
    out, prev = [], object()
    for f, hz, vol in voice_events:
        key = (hz, vol)
        if key != prev:
            out.append((f, hz, vol))
            prev = key
    return out


def wave_per_voice(sound_id, **kw):
    """Waveform numbers (0-7, into prom-1.1d) used per voice over the render."""
    ticks = render_ticks(sound_id, **kw)
    return [sorted({t[v][2] for t in ticks if t[v][1] and t[v][0]}) for v in range(3)]


def stream_ticks(sound_id, voice_k):
    """Total ticks of the k-th voice's note stream (before its 0xFF)."""
    t = TEMPO[sound_id]
    hdr, notes = STREAMS[STREAM_PTR[SND_PARMS[sound_id][0] + voice_k]]
    return sum(((t * d) & 0xFF) or 256 for _, d in notes)


# ---------------------------------------------------------------------------

MUSICAL = (0x0B, 0x0D, 0x0E, 0x14, 0x11, 0x0A, 0x09, 0x07, 0x10, 0x0C, 0x16)


def _main():
    print('Galaga sound driver: tick %.4f Hz, WSG %.9f Hz/unit, target inc = Hz/%.4f'
          % (TICK_HZ, WSG_HZ_PER_UNIT, TARGET_HZ_PER_INC))
    print()
    for sid in MUSICAL:
        s = SOUNDS[sid]
        ticks = render_ticks(sid)
        frames = render(sid)
        kind = s['kind']
        extra = ' (one loop cycle)' if kind == 'loop' else ''
        print('%02X  %s  [%s, tempo %d]' % (sid, s['name'], kind, s['tempo']))
        print('    duration %.3f s = %d ticks = %d frames%s'
              % (len(ticks) / TICK_HZ, len(ticks), len(frames[0]), extra))
        for k, vc in enumerate(s['voices']):
            names = []
            for n, dur in vc['notes'][:16]:
                ln = (s['tempo'] * dur) & 0xFF or 256
                names.append('%s/%d' % (note_name(n), ln))
            print('    voice %d hdr %02X %02X %02X  stream %.2fs: %s'
                  % (vc['voice'], *vc['header'], stream_ticks(sid, k) / TICK_HZ, ' '.join(names)))
        print()
    print('note/ticks per entry; "--" = rest. Pitch names are nearest equal-tempered (A4=440);')
    print('the Galaga table sits about +37 cents above them (see sound_spec.md).')


if __name__ == '__main__':
    _main()
