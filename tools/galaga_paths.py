"""Galaga's (Namco, 1981) flight paths: the arcade's data and a reference interpreter.

    python tools/galaga_paths.py      stage 1's waves, a dive and challenging stage 3, as
                                      sim/build/paths_*.png plots and a printed summary

**The reference GALAGA's motion is held to**, as sim/test_action.py holds
the game's flying objects to `fly()` frame by frame. tools/mkgalaga.py
takes the path bytes, the starts and the stage tables from here into
assets/galaga/galaga_art.act; the specification this implements, with
line references, is what docs/14-demos.md's GALAGA section and D114
summarise.

Source of truth: the commented Z80 disassembly at https://github.com/hackbar/galaga
(rom0/gg1-5.s = sub CPU, rom0/gg1-3.s / gg1-2*.s / new_stage.s / task_man.s = main CPU),
which the project states re-assembles to the exact ROM images.  All tables below were
extracted mechanically from those .s files (see line references) and every label whose
name encodes an address (db_flv_0067, p_flv_0502, db_0454 ...) was checked against the
address computed by re-assembling the data sequentially -- no mismatches.

Coordinates
-----------
"sprite X"  = 8-bit sprite register (ds_sprite_posn[n].b0).
"sprite Y"  = 9-bit sprite register (posn[n].b1 | ctrl[n].b1 bit0 << 8).
MAME galaga_v.cpp + ROT90: on the 224x288 portrait screen a 16x16 sprite has
    left = spriteX - 17,   top = spriteY - 40.
Motion-queue (sub CPU, 20-byte struct, IX) fixed point:
    X16 = (b03<<8)|b02  = spriteX * 128 + fraction        (b03 = X>>1, unit 2 px)
    Y16 = (b01<<8)|b00  = Yint * 128 + fraction,  Yint grows UPWARD,
    spriteY = (0x161 - Yint) & 0x1FF   (non-flipped screen)
Angle: 10-bit (b05 bits1:0, b04), 0 = right, 256 = up, 512 = left, 768 = down
(counter-clockwise, 1024 units per turn).

"""
import random

# ============================================================================
# DATA (extracted mechanically from the disassembly's .s files; line references beside each)
# ============================================================================
# (label, address, [bytes; a str item is a 2-byte little-endian .dw pointer to that label]), gg1-5.s line
PATH_TABLES = [
    ('db_flv_001d', 0x001D, [0x23, 0x06, 0x16, 0x23, 0x00, 0x19, 0xF7, 'p_flv_004b', 0x23, 0xF0, 0x02, 0xF0, 'p_flv_005e', 0x23, 0xF0, 0x24, 0xFB, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:82
    ('p_flv_004b', 0x004B, [0x23, 0xF0, 0x26, 0x23, 0x14, 0x13, 0xFE, 0x0D, 0x0B, 0x0A, 0x08, 0x06, 0x04, 0x03, 0x01, 0x23, 0xFF, 0xFF, 0xFF]),  # gg1-5.s:136
    ('p_flv_005e', 0x005E, [0x44, 0xE4, 0x18, 0xFB, 0x44, 0x00, 0xFF, 0xFF, 0xC9]),  # gg1-5.s:140
    ('db_flv_0067', 0x0067, [0x23, 0x08, 0x08, 0x23, 0x03, 0x1B, 0x23, 0x08, 0x0F, 0x23, 0x16, 0x15, 0xF7, 'p_flv_0084', 0x23, 0x16, 0x03, 0xF0, 'p_flv_0097', 0x23, 0x16, 0x19, 0xFB, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:144
    ('p_flv_0084', 0x0084, [0x23, 0x16, 0x01, 0xFE, 0x0D, 0x0C, 0x0A, 0x08, 0x06, 0x04, 0x03, 0x01, 0x23, 0xFC, 0x30, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:150
    ('p_flv_0097', 0x0097, [0x44, 0x27, 0x0E, 0xFB, 0x44, 0x00, 0xFF, 0xFF]),  # gg1-5.s:155
    ('db_flv_009f', 0x009F, [0x33, 0x06, 0x18, 0x23, 0x00, 0x18, 0xF7, 'p_flv_00b6', 0x23, 0xF0, 0x08, 0xF0, 'p_flv_00cc', 0x23, 0xF0, 0x20, 0xFB, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:158
    ('p_flv_00b6', 0x00B6, [0x23, 0xF0, 0x20, 0x23, 0x10, 0x0D, 0xFE, 0x1A, 0x18, 0x15, 0x10, 0x0C, 0x08, 0x05, 0x03, 0x23, 0xFE, 0x30, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:164
    ('p_flv_00cc', 0x00CC, [0x33, 0xE0, 0x10, 0xFB, 0x44, 0x00, 0xFF, 0xFF]),  # gg1-5.s:169
    ('db_flv_00d4', 0x00D4, [0x23, 0x03, 0x18, 0x33, 0x04, 0x10, 0x23, 0x08, 0x0A, 0x44, 0x16, 0x12, 0xF7, 'p_flv_0160', 0x44, 0x16, 0x03, 0xF0, 'p_flv_0173', 0x44, 0x16, 0x1D, 0xFB, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:172
    ('db_flv_00f1', 0x00F1, [0x12, 0x18, 0x17, 0x12, 0x00, 0x80, 0xFF]),  # gg1-5.s:179
    ('sprt_fmtn_hpos', 0x0100, [0x14, 0x06, 0x14, 0x0C, 0x14, 0x08, 0x14, 0x0A, 0x1C, 0x00, 0x1C, 0x12, 0x1E, 0x00, 0x1E, 0x12, 0x1C, 0x02, 0x1C, 0x10, 0x1E, 0x02, 0x1E, 0x10, 0x1C, 0x04, 0x1C, 0x0E, 0x1E, 0x04, 0x1E, 0x0E, 0x1C, 0x06, 0x1C, 0x0C, 0x1E, 0x06, 0x1E, 0x0C, 0x1C, 0x08, 0x1C, 0x0A, 0x1E, 0x08, 0x1E, 0x0A, 0x16, 0x06, 0x16, 0x0C, 0x16, 0x08, 0x16, 0x0A, 0x18, 0x00, 0x18, 0x12, 0x1A, 0x00, 0x1A, 0x12, 0x18, 0x02, 0x18, 0x10, 0x1A, 0x02, 0x1A, 0x10, 0x18, 0x04, 0x18, 0x0E, 0x1A, 0x04, 0x1A, 0x0E, 0x18, 0x06, 0x18, 0x0C, 0x1A, 0x06, 0x1A, 0x0C, 0x18, 0x08, 0x18, 0x0A, 0x1A, 0x08, 0x1A, 0x0A]),  # gg1-5.s:185
    ('p_flv_0160', 0x0160, [0x44, 0x16, 0x06, 0xFE, 0x0C, 0x0B, 0x0A, 0x08, 0x06, 0x04, 0x02, 0x01, 0x23, 0xFE, 0x30, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:193
    ('p_flv_0173', 0x0173, [0x66, 0x20, 0x14, 0xFB, 0x44, 0x00, 0xFF, 0xFF]),  # gg1-5.s:198
    ('db_flv_017b', 0x017B, [0x23, 0x06, 0x18, 0x23, 0x00, 0x18, 0xF7, 'p_flv_0192', 0x44, 0xF0, 0x08, 0xF0, 'p_flv_01a8', 0x44, 0xF0, 0x20, 0xFB, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:201
    ('p_flv_0192', 0x0192, [0x44, 0xF0, 0x26, 0x23, 0x10, 0x0B, 0xFE, 0x22, 0x20, 0x1E, 0x1B, 0x18, 0x15, 0x12, 0x10, 0x23, 0xFE, 0x30, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:207
    ('p_flv_01a8', 0x01A8, [0x66, 0xE0, 0x10, 0xFB, 0x44, 0x00, 0xFF, 0xFF]),  # gg1-5.s:212
    ('db_flv_01b0', 0x01B0, [0x23, 0x03, 0x20, 0x23, 0x08, 0x0F, 0x23, 0x16, 0x12, 0xF7, 'p_flv_01ca', 0x23, 0x16, 0x03, 0xF0, 'p_flv_01e0', 0x23, 0x16, 0x1D, 0xFB, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:215
    ('p_flv_01ca', 0x01CA, [0x23, 0x16, 0x01, 0xFE, 0x0D, 0x0C, 0x0B, 0x09, 0x07, 0x05, 0x03, 0x02, 0x23, 0x02, 0x20, 0x23, 0xFC, 0x12, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:221
    ('p_flv_01e0', 0x01E0, [0x44, 0x20, 0x14, 0xFB, 0x44, 0x00, 0xFF, 0xFF]),  # gg1-5.s:226
    ('db_flv_01e8', 0x01E8, [0x23, 0x00, 0x10, 0x23, 0x01, 0x40, 0x22, 0x0C, 0x37, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:229
    ('db_flv_01f5', 0x01F5, [0x23, 0x02, 0x3A, 0x23, 0x10, 0x09, 0x23, 0x00, 0x18, 0x23, 0x20, 0x10, 0x23, 0x00, 0x18, 0x23, 0x20, 0x0D, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:232
    ('db_flv_020b', 0x020B, [0x23, 0x00, 0x10, 0x23, 0x01, 0x30, 0x00, 0x40, 0x08, 0x23, 0xFF, 0x30, 0x23, 0x00, 0xFF, 0xFF]),  # gg1-5.s:236
    ('db_flv_021b', 0x021B, [0x23, 0x00, 0x30, 0x23, 0x05, 0x80, 0x23, 0x05, 0x4C, 0x23, 0x04, 0x01, 0x23, 0x00, 0x50, 0xFF]),  # gg1-5.s:239
    ('db_flv_022b', 0x022B, [0x23, 0x00, 0x28, 0x23, 0x06, 0x1D, 0x23, 0x00, 0x11, 0x00, 0x40, 0x08, 0x23, 0x00, 0x11, 0x23, 0xFA, 0x1D, 0x23, 0x00, 0x50, 0xFF]),  # gg1-5.s:242
    ('db_flv_0241', 0x0241, [0x23, 0x00, 0x21, 0x00, 0x20, 0x10, 0x23, 0xF8, 0x20, 0x23, 0xFF, 0x20, 0x23, 0xF8, 0x1B, 0x23, 0xE8, 0x0B, 0x23, 0x00, 0x21, 0x00, 0x20, 0x08, 0x23, 0x00, 0x42, 0xFF]),  # gg1-5.s:246
    ('db_flv_025d', 0x025D, [0x23, 0x00, 0x08, 0x00, 0x20, 0x08, 0x23, 0xF0, 0x20, 0x23, 0x10, 0x20, 0x23, 0xF0, 0x40, 0x23, 0x10, 0x20, 0x23, 0xF0, 0x20, 0x00, 0x20, 0x08, 0x23, 0x00, 0x30, 0xFF]),  # gg1-5.s:250
    ('db_flv_0279', 0x0279, [0x23, 0x10, 0x0C, 0x23, 0x00, 0x20, 0x23, 0xE8, 0x10, 0x23, 0xF4, 0x10, 0x23, 0xE8, 0x10, 0x23, 0xF4, 0x32, 0x23, 0xE8, 0x10, 0x23, 0xF4, 0x32, 0x23, 0xE8, 0x10, 0x23, 0xF4, 0x10, 0x23, 0xE8, 0x0E, 0x23, 0x02, 0x30, 0xFF]),  # gg1-5.s:254
    ('db_flv_029e', 0x029E, [0x23, 0xF1, 0x08, 0x23, 0x00, 0x10, 0x23, 0x05, 0x3C, 0x23, 0x07, 0x42, 0x23, 0x0A, 0x40, 0x23, 0x10, 0x2D, 0x23, 0x20, 0x19, 0x00, 0xFC, 0x14, 0x23, 0x02, 0x4A, 0xFF]),  # gg1-5.s:259
    ('db_flv_02ba', 0x02BA, [0x23, 0x04, 0x20, 0x23, 0x00, 0x16, 0x23, 0xF0, 0x30, 0x23, 0x00, 0x12, 0x23, 0x10, 0x30, 0x23, 0x00, 0x12, 0x23, 0x10, 0x30, 0x23, 0x00, 0x16, 0x23, 0x04, 0x20, 0x23, 0x00, 0x10, 0xFF]),  # gg1-5.s:263
    ('db_flv_02d9', 0x02D9, [0x23, 0x00, 0x15, 0x00, 0x20, 0x08, 0x23, 0x00, 0x11, 0x00, 0xE0, 0x08, 0x23, 0x00, 0x18, 0x00, 0x20, 0x08, 0x23, 0x00, 0x13, 0x00, 0xE0, 0x08, 0x23, 0x00, 0x1F, 0x00, 0x20, 0x08, 0x23, 0x00, 0x30, 0xFF]),  # gg1-5.s:267
    ('db_flv_02fb', 0x02FB, [0x23, 0x02, 0x0E, 0x23, 0x00, 0x34, 0x23, 0x12, 0x19, 0x23, 0x00, 0x20, 0x23, 0xE0, 0x0E, 0x23, 0x00, 0x12, 0x23, 0x20, 0x0E, 0x23, 0x00, 0x0C, 0x23, 0xE0, 0x0E, 0x23, 0x1B, 0x08, 0x23, 0x00, 0x10, 0xFF]),  # gg1-5.s:272
    ('db_flv_031d', 0x031D, [0x23, 0x00, 0x0D, 0x00, 0xC0, 0x04, 0x23, 0x00, 0x21, 0x00, 0x40, 0x06, 0x23, 0x00, 0x51, 0x00, 0xC0, 0x06, 0x23, 0x00, 0x73, 0xFF]),  # gg1-5.s:277
    ('db_flv_0333', 0x0333, [0x23, 0x08, 0x20, 0x23, 0x00, 0x16, 0x23, 0xE0, 0x0C, 0x23, 0x02, 0x0B, 0x23, 0x11, 0x0C, 0x23, 0x02, 0x0B, 0x23, 0xE0, 0x0C, 0x23, 0x00, 0x16, 0x23, 0x08, 0x20, 0xFF]),  # gg1-5.s:281
    ('db_flv_atk_yllw', 0x034F, [0x12, 0x18, 0x1E]),  # gg1-5.s:285
    ('p_flv_0352', 0x0352, [0x12, 0x00, 0x34, 0x12, 0xFB, 0x26]),  # gg1-5.s:287
    ('p_flv_0358', 0x0358, [0x12, 0x00, 0x02, 0xFC, 0x2E, 0x12, 0xFA, 0x3C, 0xFA, 'p_flv_039e']),  # gg1-5.s:289
    ('p_flv_0363', 0x0363, [0x12, 0xF8, 0x10, 0x12, 0xFA, 0x5C, 0x12, 0x00, 0x23]),  # gg1-5.s:293
    ('p_flv_036c', 0x036C, [0xF8, 0xF9, 0xEF, 'p_flv_037c', 0xF6, 0xAB, 0x12, 0x01, 0x28, 0x12, 0x0A, 0x18, 0xFD, 'p_flv_0352']),  # gg1-5.s:295
    ('p_flv_037c', 0x037C, [0xF6, 0xB0, 0x23, 0x08, 0x1E, 0x23, 0x00, 0x19, 0x23, 0xF8, 0x16, 0x23, 0x00, 0x02, 0xFC, 0x30, 0x23, 0xF7, 0x26, 0xFA, 'p_flv_039e', 0x23, 0xF0, 0x0A, 0x23, 0xF5, 0x31, 0x23, 0x00, 0x10, 0xFD, 'p_flv_036c']),  # gg1-5.s:301
    ('p_flv_039e', 0x039E, [0x12, 0xF8, 0x10, 0x12, 0x00, 0x40, 0xFB, 0x12, 0x00, 0xFF, 0xFF]),  # gg1-5.s:308
    ('db_flv_atk_red', 0x03A9, [0x12, 0x18, 0x1D]),  # gg1-5.s:311
    ('p_flv_03ac', 0x03AC, [0x12, 0x00, 0x28, 0x12, 0xFA, 0x02, 0xF3, 0x3F, 0x3B, 0x36, 0x32, 0x28, 0x26, 0x24, 0x22, 0x12, 0x04, 0x30, 0x12, 0xFC, 0x30, 0x12, 0x00, 0x18, 0xF8, 0xF9, 0xFA, 'p_flv_040c', 0xEF, 'p_flv_03d7']),  # gg1-5.s:313
    ('p_flv_03cc', 0x03CC, [0xF6, 0xB0, 0x12, 0x01, 0x28, 0x12, 0x0A, 0x15, 0xFD, 'p_flv_03ac']),  # gg1-5.s:322
    ('p_flv_03d7', 0x03D7, [0xF6, 0xC0, 0x23, 0x08, 0x10, 0x23, 0x00, 0x23, 0x23, 0xF8, 0x0F, 0x23, 0x00, 0x48, 0xF8, 0xF9, 0xFA, 'p_flv_040c', 0xF6, 0xB0, 0x23, 0x08, 0x20, 0x23, 0x00, 0x08, 0x23, 0xF8, 0x02, 0xF3, 0x34, 0x31, 0x2D, 0x29, 0x22, 0x26, 0x1F, 0x18, 0x23, 0x08, 0x18, 0x23, 0xF8, 0x18, 0x23, 0x00, 0x10, 0xF8, 0xF9, 0xFD, 'p_flv_03cc']),  # gg1-5.s:326
    ('p_flv_040c', 0x040C, [0xFB, 0x12, 0x00, 0xFF, 0xFF]),  # gg1-5.s:335
    ('db_flv_0411', 0x0411, [0x12, 0x18, 0x14]),  # gg1-5.s:338
    ('p_flv_0414', 0x0414, [0x12, 0x03, 0x2A, 0x12, 0x10, 0x40, 0x12, 0x01, 0x20, 0x12, 0xFE, 0x71]),  # gg1-5.s:340
    ('p_flv_0420', 0x0420, [0xF9, 0xF1, 0xFA, 'p_flv_040c']),  # gg1-5.s:342
    ('p_flv_0425', 0x0425, [0xEF, 'p_flv_0430', 0xF6, 0xAB, 0x12, 0x02, 0x20, 0xFD, 'p_flv_0414']),  # gg1-5.s:345
    ('p_flv_0430', 0x0430, [0xF6, 0xB0, 0x23, 0x04, 0x1A, 0x23, 0x03, 0x1D, 0x23, 0x1A, 0x25, 0x23, 0x03, 0x10, 0x23, 0xFD, 0x48, 0xFD, 'p_flv_0420']),  # gg1-5.s:351
    ('db_fltv_rogefgter', 0x0444, [0x12, 0x18, 0x14, 0x12, 0x03, 0x2A, 0x12, 0x10, 0x40, 0x12, 0x01, 0x20, 0x12, 0xFE, 0x78, 0xFF]),  # gg1-5.s:356
    ('db_0454', 0x0454, [0x12, 0x18, 0x14, 0xF4, 0x12, 0x00, 0x04, 0xFC, 0x48, 0x00, 0xFC, 0xFF, 0x23, 0x00, 0x30, 0xF8, 0xF9, 0xFA, 'p_flv_040c', 0xFD, 'p_flv_0425']),  # gg1-5.s:359
    ('db_flv_cboss', 0x046B, [0x12, 0x18, 0x14, 0xFB, 0x12, 0x00, 0xFF, 0xFF]),  # gg1-5.s:367
    ('db_0473', 0x0473, [0x12, 0x18, 0x1E, 0x12, 0x00, 0x08, 0xF2, 'p_flv_0499', 0x00, 0x00, 0x0A, 0xF2, 'p_flv_0499', 0x00, 0x00, 0x0A, 0x12, 0x00, 0x2C, 0x12, 0xFB, 0x26, 0x12, 0x00, 0x02, 0xFC, 0x2E, 0x12, 0xFA, 0x3C, 0xFA, 'p_flv_039e', 0xFD, 'p_flv_0363']),  # gg1-5.s:370
    ('p_flv_0499', 0x0499, [0x12, 0x00, 0x2C, 0x12, 0xFB, 0x26, 0x12, 0x00, 0x02, 0xFC, 0x2E, 0x12, 0xFA, 0x18, 0x12, 0x00, 0x10, 0xFF]),  # gg1-5.s:382
    ('db_04AB', 0x04AB, [0x12, 0x18, 0x13, 0xF2, 'p_flv_04c6', 0x00, 0x00, 0x08, 0xF2, 'p_flv_04cf', 0x00, 0x00, 0x08, 0x12, 0x18, 0x0B, 0x12, 0x00, 0x34, 0x12, 0xFB, 0x26, 0xFD, 'p_flv_0358']),  # gg1-5.s:386
    ('db_flv_04c6', 0x04C6, [0x12, 0x00, 0x10, 0x12, 0x18, 0x0B, 0xFD, 'p_flv_04d8']),  # gg1-5.s:394  alias p_flv_04c6
    ('db_flv_04cf', 0x04CF, [0x12, 0x00, 0x08, 0x12, 0x18, 0x0B, 0x12, 0x00, 0x06]),  # gg1-5.s:399  alias p_flv_04cf
    ('db_flv_04d8', 0x04D8, [0x12, 0x00, 0x22, 0x12, 0xFB, 0x26, 0x12, 0x00, 0x02, 0xFC, 0x2E, 0x12, 0xFA, 0x18, 0x12, 0x00, 0x20, 0xFF]),  # gg1-5.s:403  alias p_flv_04d8
    ('db_04EA', 0x04EA, [0x12, 0x18, 0x1E, 0x12, 0x00, 0x14, 0xF2, 'p_flv_0502', 0x12, 0x00, 0x08, 0xF2, 'p_flv_0502', 0x12, 0x00, 0x18, 0x12, 0xFB, 0x26, 0xFD, 'p_flv_0358']),  # gg1-5.s:408
    ('db_flv_0502', 0x0502, [0x12, 0xE2, 0x01, 0xF3, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01, 0xF5, 0x23, 0x00, 0x48, 0xFF]),  # gg1-5.s:416  alias p_flv_0502
    ('db_flv_0fda', 0x0FDA, [0x23, 0x00, 0x1B, 0x23, 0xF0, 0x40, 0x23, 0x00, 0x09, 0x23, 0x05, 0x11, 0x23, 0x00, 0x10, 0x23, 0x10, 0x40, 0x23, 0x04, 0x30, 0xFF]),  # gg1-5.s:2893
    ('db_flv_0ff0', 0x0FF0, [0x23, 0x02, 0x35, 0x23, 0x08, 0x10, 0x23, 0x10, 0x3C, 0x23, 0x00, 0xFF, 0xFF, 0x32]),  # gg1-5.s:2896
]

# gg1-3.s:1438-1441  d_combat_stg_dat_idx
D_COMBAT_STG_DAT_IDX = [
    0x00, 0x12, 0x24, 0x36, 0x00, 0x48, 0x6C, 0x5A, 0x48, 0x6C, 0x00, 0x7E, 0xA2, 0x90, 0xB4, 0xD8, 0xC6,  # line 1438
    0x00, 0x12, 0x48, 0x6C, 0x5A, 0x7E, 0xA2, 0x00, 0x7E, 0xD8, 0xC6, 0xB4, 0xD8, 0xC6, 0xB4, 0xD8, 0xC6,  # line 1439
    0x00, 0x12, 0x7E, 0xA2, 0x90, 0x7E, 0xD8, 0xC6, 0xB4, 0xD8, 0xC6, 0xB4, 0xD8, 0xC6, 0xB4, 0xD8, 0xC6,  # line 1440
    0x00, 0x12, 0x48, 0x36, 0x24, 0x48, 0x6C, 0x00, 0x7E, 0xA2, 0x90, 0xB4, 0xD8, 0x00, 0xB4, 0xD8, 0xC6,  # line 1441
]

# gg1-3.s:1445-1445  d_challg_stg_data_idx
D_CHALLG_STG_DATA_IDX = [
    0x00, 0x12, 0x24, 0x36, 0x48, 0x5A, 0x6C, 0x7E,  # line 1445
]

# gg1-3.s:1462-1474  d_combat_stg_dat
D_COMBAT_STG_DAT = [
    0x14, 0x00, 0x00, 0x00, 0xC0, 0x00, 0x01, 0x01, 0x00, 0x41, 0x41, 0x00, 0x40, 0x40, 0x00, 0x00, 0x00, 0xFF,  # line 1462
    0x14, 0x01, 0x00, 0x42, 0x82, 0x00, 0x03, 0x85, 0x00, 0x43, 0xC5, 0x00, 0x42, 0xC4, 0x00, 0x02, 0x84, 0xFF,  # line 1463
    0x14, 0x01, 0x82, 0x00, 0xC0, 0x00, 0x01, 0x01, 0x00, 0x41, 0x41, 0x02, 0x40, 0x40, 0x02, 0x00, 0x00, 0xFF,  # line 1464
    0x14, 0x01, 0x82, 0x02, 0xC2, 0x00, 0x03, 0x85, 0x00, 0x43, 0xC5, 0x02, 0x42, 0xC4, 0x02, 0x02, 0x84, 0xFF,  # line 1465
    0x14, 0x01, 0x82, 0x00, 0xC0, 0x00, 0x01, 0xC1, 0x00, 0x41, 0x81, 0x02, 0x40, 0x80, 0x02, 0x40, 0x80, 0xFF,  # line 1466
    0x14, 0x01, 0x82, 0x00, 0xC0, 0x42, 0x01, 0x01, 0xF2, 0x41, 0x41, 0x02, 0x40, 0x40, 0x02, 0x00, 0x00, 0xFF,  # line 1467
    0x14, 0x01, 0xA4, 0x02, 0xC2, 0x52, 0x03, 0x85, 0xF2, 0x43, 0xC5, 0x02, 0x42, 0xC4, 0x02, 0x02, 0x84, 0xFF,  # line 1468
    0x14, 0x01, 0x82, 0x00, 0xC0, 0x52, 0x01, 0xC1, 0xF2, 0x41, 0x81, 0x02, 0x40, 0x80, 0x02, 0x40, 0x80, 0xFF,  # line 1469
    0x14, 0x01, 0xA4, 0x00, 0xC0, 0x42, 0x01, 0x01, 0xF4, 0x41, 0x41, 0x04, 0x40, 0x40, 0x04, 0x00, 0x00, 0xFF,  # line 1470
    0x14, 0x01, 0xA4, 0x02, 0xC2, 0x52, 0x03, 0x85, 0xF4, 0x43, 0xC5, 0x04, 0x42, 0xC4, 0x04, 0x02, 0x84, 0xFF,  # line 1471
    0x14, 0x03, 0xA4, 0x00, 0xC0, 0x54, 0x01, 0xC1, 0xF4, 0x41, 0x81, 0x04, 0x40, 0x80, 0x04, 0x40, 0x80, 0xFF,  # line 1472
    0x14, 0x03, 0xA4, 0x00, 0xC0, 0x54, 0x01, 0x01, 0xF4, 0x41, 0x41, 0x04, 0x40, 0x40, 0x04, 0x00, 0x00, 0xFF,  # line 1473
    0x14, 0x03, 0xA4, 0x02, 0xC2, 0x54, 0x03, 0x85, 0xF4, 0x43, 0xC5, 0x04, 0x42, 0xC4, 0x04, 0x02, 0x84, 0xFF,  # line 1474
]

# gg1-3.s:1478-1485  d_challg_stg_dat
D_CHALLG_STG_DAT = [
    0xFF, 0x00, 0x00, 0x06, 0xC6, 0x00, 0x07, 0x07, 0x00, 0x47, 0x47, 0x00, 0x46, 0x46, 0x00, 0x06, 0x06, 0xFF,  # line 1478
    0xFF, 0x00, 0x00, 0x08, 0xC8, 0x00, 0x09, 0xC9, 0x00, 0x09, 0xC9, 0x00, 0x48, 0x48, 0x00, 0x08, 0x08, 0xFF,  # line 1479
    0xFF, 0x00, 0x00, 0x0A, 0x4A, 0x00, 0x0B, 0xCB, 0x00, 0x0B, 0xCB, 0x00, 0x0A, 0x4A, 0x00, 0x16, 0x56, 0xFF,  # line 1480
    0xFF, 0x00, 0x00, 0x0C, 0xCC, 0x00, 0x0D, 0x0D, 0x00, 0x4D, 0x4D, 0x00, 0x0C, 0xCC, 0x00, 0x17, 0xD7, 0xFF,  # line 1481
    0xFF, 0x00, 0x00, 0x0E, 0x0E, 0x00, 0x0F, 0x0F, 0x00, 0x4F, 0x4F, 0x00, 0x0E, 0x0E, 0x00, 0x4E, 0x4E, 0xFF,  # line 1482
    0xFF, 0x00, 0x00, 0x10, 0x10, 0x00, 0x11, 0xD1, 0x00, 0x11, 0xD1, 0x00, 0x50, 0x50, 0x00, 0x10, 0x10, 0xFF,  # line 1483
    0xFF, 0x00, 0x00, 0x12, 0x12, 0x00, 0x13, 0x13, 0x00, 0x53, 0x53, 0x00, 0x52, 0x52, 0x00, 0x12, 0x12, 0xFF,  # line 1484
    0xFF, 0x00, 0x00, 0x14, 0xD4, 0x00, 0x15, 0x15, 0x00, 0x55, 0x55, 0x00, 0x14, 0xD4, 0x00, 0x14, 0xD4, 0xFF,  # line 1485
]

# gg1-3.s:1490-1494  db_attk_wav_IDs
DB_ATTK_WAV_IDS = [
    0x58, 0x5A, 0x5C, 0x5E, 0x28, 0x2A, 0x2C, 0x2E,  # line 1490
    0x30, 0x34, 0x36, 0x32, 0x50, 0x52, 0x54, 0x56,  # line 1491
    0x42, 0x46, 0x40, 0x44, 0x4A, 0x4E, 0x48, 0x4C,  # line 1492
    0x1A, 0x1E, 0x20, 0x24, 0x22, 0x26, 0x18, 0x1C,  # line 1493
    0x08, 0x0C, 0x12, 0x16, 0x10, 0x14, 0x0A, 0x0E,  # line 1494
]

# gg1-3.s:1930-1941  db_2A6C
DB_2A6C = [
    0x9B, 0x34, 0x03,  # line 1930
    0x9B, 0x44, 0x03,  # line 1931
    0x23, 0x00, 0x00,  # line 1932
    0x23, 0x78, 0x02,  # line 1933
    0x9B, 0x2C, 0x03,  # line 1934
    0x9B, 0x4C, 0x03,  # line 1935
    0x2B, 0x00, 0x00,  # line 1936
    0x2B, 0x78, 0x02,  # line 1937
    0x9B, 0x34, 0x03,  # line 1938
    0x9B, 0x34, 0x03,  # line 1939
    0x9B, 0x44, 0x03,  # line 1940
    0x9B, 0x44, 0x03,  # line 1941
]

# gg1-3.s:1634-1637  d_stage_chllg_rnd_attrib
D_STAGE_CHLLG_RND_ATTRIB = [
    0x0A, 0xB8,  # line 1634
    0x0F, 0xB9,  # line 1635
    0x14, 0xBC,  # line 1636
    0x1E, 0xBD,  # line 1637
]

# gg1-3.s:1640-1640  d_2908
D_2908 = [
    0xA5, 0x5A, 0xA9, 0x0F, 0x0A, 0x50,  # line 1640
]

# gg1-3.s:1642-1642  d_290E
D_290E = [
    0x36, 0x24, 0xD4, 0xBA, 0xE4, 0xCC, 0xA8, 0xF4,  # line 1642
]

# gg1-2.s:949-949  db_fmtn_hpos_orig
DB_FMTN_HPOS_ORIG = [
    0x31, 0x41, 0x51, 0x61, 0x71, 0x81, 0x91, 0xA1, 0xB1, 0xC1, 0x92, 0x8A, 0x82, 0x7C, 0x76, 0x70,  # line 949
]

# task_man.s:133-138  db_obj_home_posn_rc
DB_OBJ_HOME_POSN_RC = [
    0x14, 0x06, 0x14, 0x0C, 0x14, 0x08, 0x14, 0x0A, 0x1C, 0x00, 0x1C, 0x12, 0x1E, 0x00, 0x1E, 0x12,  # line 133
    0x1C, 0x02, 0x1C, 0x10, 0x1E, 0x02, 0x1E, 0x10, 0x1C, 0x04, 0x1C, 0x0E, 0x1E, 0x04, 0x1E, 0x0E,  # line 134
    0x1C, 0x06, 0x1C, 0x0C, 0x1E, 0x06, 0x1E, 0x0C, 0x1C, 0x08, 0x1C, 0x0A, 0x1E, 0x08, 0x1E, 0x0A,  # line 135
    0x16, 0x06, 0x16, 0x0C, 0x16, 0x08, 0x16, 0x0A, 0x18, 0x00, 0x18, 0x12, 0x1A, 0x00, 0x1A, 0x12,  # line 136
    0x18, 0x02, 0x18, 0x10, 0x1A, 0x02, 0x1A, 0x10, 0x18, 0x04, 0x18, 0x0E, 0x1A, 0x04, 0x1A, 0x0E,  # line 137
    0x18, 0x06, 0x18, 0x0C, 0x1A, 0x06, 0x1A, 0x0C, 0x18, 0x08, 0x18, 0x0A, 0x1A, 0x08, 0x1A, 0x0A,  # line 138
]

# gg1-2_fx.s:1723-1726  d_1E64_bitmap_tables
D_1E64_BITMAP_TABLES = [
    0xFF, 0x77, 0x55, 0x14, 0x10, 0x10, 0x14, 0x55, 0x77, 0xFF, 0x00, 0x10, 0x14, 0x55, 0x77, 0xFF,  # line 1723
    0xFF, 0x77, 0x55, 0x51, 0x10, 0x10, 0x51, 0x55, 0x77, 0xFF, 0x00, 0x10, 0x51, 0x55, 0x77, 0xFF,  # line 1724
    0xFF, 0x77, 0x57, 0x15, 0x10, 0x10, 0x15, 0x57, 0x77, 0xFF, 0x00, 0x10, 0x15, 0x57, 0x77, 0xFF,  # line 1725
    0xFF, 0xF7, 0xD5, 0x91, 0x10, 0x10, 0x91, 0xD5, 0xF7, 0xFF, 0x00, 0x10, 0x91, 0xD5, 0xF7, 0xFF,  # line 1726
]

# gg1-2_fx.s:1333-1333  d_1D2C_wingmen
D_1D2C_WINGMEN = [
    0x4A, 0x52, 0x5A, 0x58, 0x50, 0x48,  # line 1333
]

# new_stage.s:144-198  bmbr_stg_cfg_dat
BMBR_STG_CFG_DAT = [
    0x00, 0x00, 0x22, 0xC6, 0x00, 0x00, 0x11, 0x23, 0xC7, 0x00,  # line 144
    0x00, 0x00, 0x00, 0xC0, 0x00, 0x11, 0x12, 0x23, 0x97, 0x00,  # line 145
    0x11, 0x23, 0x23, 0x98, 0x00, 0x21, 0x24, 0x33, 0x98, 0x00,  # line 146
    0x00, 0x00, 0x00, 0x90, 0x00, 0x22, 0x25, 0x33, 0x99, 0x10,  # line 147
    0x22, 0x36, 0x34, 0x69, 0x10, 0x10, 0x11, 0x23, 0x97, 0x00,  # line 148
    0x00, 0x00, 0x00, 0x60, 0x00, 0x32, 0x46, 0x34, 0x67, 0x11,  # line 149
    0x32, 0x67, 0x44, 0x68, 0x11, 0x32, 0x67, 0x45, 0x68, 0x11,  # line 150
    0x00, 0x00, 0x00, 0x60, 0x00, 0x42, 0x78, 0x45, 0x69, 0x11,  # line 151
    0x42, 0x78, 0x45, 0x69, 0x11, 0x11, 0x22, 0x23, 0x97, 0x11,  # line 152
    0x00, 0x00, 0x00, 0x60, 0x00, 0x52, 0x88, 0x46, 0x3A, 0x11,  # line 153
    0x52, 0x88, 0x56, 0x3A, 0x11, 0x52, 0x88, 0x56, 0x3C, 0x11,  # line 154
    0x00, 0x00, 0x00, 0x30, 0x00, 0x62, 0x89, 0x57, 0x3C, 0x11,  # line 155
    0x62, 0x99, 0x57, 0x3C, 0x11, 0x62, 0x99, 0x57, 0x3C, 0x11,  # line 156
    0x00, 0x00, 0x12, 0xC6, 0x00, 0x00, 0x11, 0x22, 0xC6, 0x00,  # line 158
    0x00, 0x00, 0x00, 0xC0, 0x00, 0x11, 0x12, 0x23, 0x97, 0x00,  # line 159
    0x11, 0x12, 0x23, 0x97, 0x00, 0x00, 0x11, 0x23, 0xC7, 0x00,  # line 160
    0x00, 0x00, 0x00, 0x90, 0x00, 0x21, 0x23, 0x33, 0x98, 0x10,  # line 161
    0x21, 0x24, 0x33, 0x98, 0x10, 0x21, 0x25, 0x34, 0x98, 0x10,  # line 162
    0x00, 0x00, 0x00, 0x60, 0x00, 0x22, 0x25, 0x34, 0x68, 0x11,  # line 163
    0x32, 0x36, 0x44, 0x68, 0x11, 0x11, 0x11, 0x23, 0x67, 0x01,  # line 164
    0x00, 0x00, 0x00, 0x60, 0x00, 0x32, 0x36, 0x45, 0x68, 0x11,  # line 165
    0x32, 0x46, 0x45, 0x69, 0x11, 0x32, 0x67, 0x45, 0x69, 0x11,  # line 166
    0x00, 0x00, 0x00, 0x60, 0x00, 0x42, 0x67, 0x46, 0x3A, 0x11,  # line 167
    0x42, 0x78, 0x56, 0x3A, 0x11, 0x52, 0x78, 0x56, 0x3A, 0x11,  # line 168
    0x00, 0x00, 0x00, 0x30, 0x00, 0x52, 0x88, 0x56, 0x3C, 0x11,  # line 169
    0x62, 0x99, 0x57, 0x3C, 0x11, 0x62, 0x99, 0x57, 0x3C, 0x11,  # line 170
    0x00, 0x00, 0x23, 0xC6, 0x00, 0x10, 0x11, 0x23, 0x97, 0x00,  # line 172
    0x00, 0x00, 0x00, 0xC0, 0x00, 0x11, 0x12, 0x33, 0x98, 0x00,  # line 173
    0x21, 0x23, 0x34, 0x68, 0x00, 0x21, 0x24, 0x34, 0x68, 0x00,  # line 174
    0x00, 0x00, 0x00, 0x90, 0x00, 0x32, 0x36, 0x34, 0x67, 0x10,  # line 175
    0x32, 0x46, 0x44, 0x68, 0x10, 0x11, 0x11, 0x23, 0x97, 0x10,  # line 176
    0x00, 0x00, 0x00, 0x60, 0x00, 0x42, 0x67, 0x45, 0x68, 0x11,  # line 177
    0x42, 0x67, 0x45, 0x69, 0x11, 0x42, 0x78, 0x46, 0x69, 0x11,  # line 178
    0x00, 0x00, 0x00, 0x60, 0x00, 0x52, 0x78, 0x46, 0x3A, 0x11,  # line 179
    0x52, 0x88, 0x56, 0x3A, 0x11, 0x52, 0x88, 0x56, 0x3A, 0x11,  # line 180
    0x00, 0x00, 0x00, 0x60, 0x00, 0x62, 0x88, 0x56, 0x3C, 0x11,  # line 181
    0x62, 0x89, 0x57, 0x3C, 0x11, 0x62, 0x89, 0x57, 0x3E, 0x11,  # line 182
    0x00, 0x00, 0x00, 0x30, 0x00, 0x72, 0x99, 0x57, 0x3E, 0x11,  # line 183
    0x72, 0x99, 0x68, 0x3E, 0x11, 0x72, 0x99, 0x68, 0x3E, 0x11,  # line 184
    0x00, 0x00, 0x23, 0xC6, 0x00, 0x10, 0x11, 0x23, 0x97, 0x00,  # line 186
    0x00, 0x00, 0x00, 0xC0, 0x00, 0x11, 0x12, 0x34, 0x98, 0x00,  # line 187
    0x21, 0x23, 0x34, 0x68, 0x00, 0x21, 0x24, 0x34, 0x68, 0x00,  # line 188
    0x00, 0x00, 0x00, 0x90, 0x00, 0x32, 0x36, 0x45, 0x67, 0x11,  # line 189
    0x32, 0x46, 0x46, 0x68, 0x11, 0x32, 0x56, 0x46, 0x69, 0x11,  # line 190
    0x00, 0x00, 0x00, 0x60, 0x00, 0x42, 0x67, 0x56, 0x6A, 0x11,  # line 191
    0x42, 0x67, 0x56, 0x6A, 0x11, 0x42, 0x78, 0x57, 0x6A, 0x11,  # line 192
    0x00, 0x00, 0x00, 0x60, 0x00, 0x52, 0x78, 0x57, 0x3A, 0x11,  # line 193
    0x52, 0x88, 0x57, 0x3A, 0x11, 0x52, 0x88, 0x68, 0x3C, 0x11,  # line 194
    0x00, 0x00, 0x00, 0x60, 0x00, 0x62, 0x88, 0x68, 0x3C, 0x11,  # line 195
    0x62, 0x89, 0x68, 0x3C, 0x11, 0x62, 0x89, 0x68, 0x3E, 0x11,  # line 196
    0x00, 0x00, 0x00, 0x30, 0x00, 0x72, 0x99, 0x68, 0x3E, 0x11,  # line 197
    0x72, 0x99, 0x68, 0x3E, 0x11, 0x72, 0x99, 0x68, 0x3E, 0x11,  # line 198
]

# gg1-3.s:1919-1924  db_2A3C: (path label, bits13:15 select into db_2A6C)
DB_2A3C = [
    ('db_flv_001d', 0),  # line 1919  (.dw db_flv_001d + 0x0000)
    ('db_flv_0067', 1),  # line 1919  (.dw db_flv_0067 + 0x2000)
    ('db_flv_009f', 2),  # line 1919  (.dw db_flv_009f + 0x4000)
    ('db_flv_00d4', 1),  # line 1919  (.dw db_flv_00d4 + 0x2000)
    ('db_flv_017b', 0),  # line 1920  (.dw db_flv_017b + 0x0000)
    ('db_flv_01b0', 3),  # line 1920  (.dw db_flv_01b0 + 0x6000)
    ('db_flv_01e8', 0),  # line 1920  (.dw db_flv_01e8 + 0x0000)
    ('db_flv_01f5', 1),  # line 1920  (.dw db_flv_01f5 + 0x2000)
    ('db_flv_020b', 0),  # line 1921  (.dw db_flv_020b + 0x0000)
    ('db_flv_021b', 1),  # line 1921  (.dw db_flv_021b + 0x2000)
    ('db_flv_022b', 4),  # line 1921  (.dw db_flv_022b + 0x8000)
    ('db_flv_0241', 1),  # line 1921  (.dw db_flv_0241 + 0x2000)
    ('db_flv_025d', 4),  # line 1922  (.dw db_flv_025d + 0x8000)
    ('db_flv_0279', 1),  # line 1922  (.dw db_flv_0279 + 0x2000)
    ('db_flv_029e', 0),  # line 1922  (.dw db_flv_029e + 0x0000)
    ('db_flv_02ba', 1),  # line 1922  (.dw db_flv_02ba + 0x2000)
    ('db_flv_02d9', 0),  # line 1923  (.dw db_flv_02d9 + 0x0000)
    ('db_flv_02fb', 1),  # line 1923  (.dw db_flv_02fb + 0x2000)
    ('db_flv_031d', 0),  # line 1923  (.dw db_flv_031d + 0x0000)
    ('db_flv_0333', 1),  # line 1923  (.dw db_flv_0333 + 0x2000)
    ('db_flv_0fda', 0),  # line 1924  (.dw db_flv_0fda + 0x0000)
    ('db_flv_0ff0', 1),  # line 1924  (.dw db_flv_0ff0 + 0x2000)
    ('db_flv_022b', 5),  # line 1924  (.dw db_flv_022b + 0xA000)
    ('db_flv_025d', 5),  # line 1924  (.dw db_flv_025d + 0xA000)
]



# ============================================================================
# Sub-CPU ROM image (only the path-data regions are populated)
# ============================================================================
SUB_ROM = bytearray([0xFF]) * 0x1000
LABEL_ADDR = {}
ADDR_LABEL = {}
for _name, _addr, _items in PATH_TABLES:
    LABEL_ADDR[_name] = _addr
    ADDR_LABEL.setdefault(_addr, _name)
LABEL_ADDR.update({'p_flv_04c6': 0x04C6, 'p_flv_04cf': 0x04CF, 'p_flv_04d8': 0x04D8,
                   'p_flv_0502': 0x0502})
for _name, _addr, _items in PATH_TABLES:
    _a = _addr
    for _it in _items:
        if isinstance(_it, str):
            _w = LABEL_ADDR[_it]
            SUB_ROM[_a] = _w & 0xFF
            SUB_ROM[_a + 1] = _w >> 8
            _a += 2
        else:
            SUB_ROM[_a] = _it
            _a += 1
# sanity: the sub-CPU copy of the home-position table equals the main-CPU one
assert list(SUB_ROM[0x100:0x160]) == DB_OBJ_HOME_POSN_RC

HPOS = SUB_ROM[0x100:0x160]          # sprt_fmtn_hpos / db_obj_home_posn_rc


def rom(a):
    return SUB_ROM[a] if 0 <= a < 0x1000 else 0xFF


def word(a):
    return rom(a) | (rom(a + 1) << 8)


def addr_of(label_or_addr):
    return LABEL_ADDR[label_or_addr] if isinstance(label_or_addr, str) else label_or_addr


def name_of(addr):
    return ADDR_LABEL.get(addr, '0x%04X' % addr)


TOKEN_NAMES = {
    0xFF: 'END (make inactive)', 0xFE: 'TABLE8 frames by fighter X (case_0B16)',
    0xFD: 'JUMP', 0xFC: 'UNTIL_Y', 0xFB: 'HOME', 0xFA: 'JUMP unless cont.bombing',
    0xF9: 'SET_X home column', 0xF8: 'SET_Y top (0x9C)', 0xF7: 'JUMP if transient',
    0xF6: 'SET_ANGLE', 0xF5: 'STATE=3', 0xF4: 'AIM capture point',
    0xF3: 'TABLE8 frames by dX to fighter (case_0A01)', 0xF2: 'CLONE',
    0xF1: 'SET_Y row+0x20', 0xF0: 'JUMP if stage_parm[8] (consumes frame)',
    0xEF: 'JUMP if stage_parm[9] (consumes frame)',
}


def disasm(label, max_items=200):
    """Token listing of one path table starting at label (does not follow jumps)."""
    a = addr_of(label)
    out = []
    for _ in range(max_items):
        t = rom(a)
        lab = ADDR_LABEL.get(a)
        pre = ('%s:' % lab) if lab and a != addr_of(label) else ''
        if t < 0xEF:
            out.append('%s  %04X  seg speed=%X/%X(odd/even frames) dAngle=%+d frames=%d   [%02X %02X %02X]' % (
                pre, a, t & 15, t >> 4, (rom(a + 1) ^ 0x80) - 0x80, rom(a + 2) or 256,
                t, rom(a + 1), rom(a + 2)))
            a += 3
            continue
        if t in (0xFD, 0xFA, 0xF7, 0xF2, 0xF0, 0xEF):
            out.append('%s  %04X  %02X %s -> %s' % (pre, a, t, TOKEN_NAMES[t], name_of(word(a + 1))))
            if t == 0xFD:
                break
            a += 3
        elif t in (0xFE, 0xF3):
            out.append('%s  %04X  %02X %s  table=%s' % (pre, a, t, TOKEN_NAMES[t],
                                                       ' '.join('%02X' % rom(a + 1 + i) for i in range(8))))
            a += 9
        elif t in (0xFC, 0xF6):
            out.append('%s  %04X  %02X %s %02X' % (pre, a, t, TOKEN_NAMES[t], rom(a + 1)))
            a += 2
        else:
            out.append('%s  %04X  %02X %s' % (pre, a, t, TOKEN_NAMES[t]))
            a += 1
            if t == 0xFF:
                break
    return out


# ============================================================================
# Z80 arithmetic helpers (bit-exact)
# ============================================================================
def c_0EAA(hl, a):
    """HL = HL / A (gg1-5.s c_0EAA), returns (quotient16, remainder8)."""
    c = a & 0xFF
    acc = 0
    cy = 0
    for _ in range(17):
        acc = (acc << 1) | cy
        if acc > 0xFF:                      # jr c,l_0EBD: sub c; scf
            acc = (acc - c) & 0xFF
            cy = 1
        elif acc < c:                       # cp c -> C ; ccf -> NC
            cy = 0
        else:                               # sub c -> NC ; ccf -> C
            acc = (acc - c) & 0xFF
            cy = 1
        hl = (hl << 1) | cy
        cy = hl >> 16
        hl &= 0xFFFF
    return hl, acc


def c_0E5B(d, e, h, l):
    """Rotation angle from (H=y, L=x) to (D=y, E=x); all in 2-px units.
    Returns 11-bit HL; callers store HL>>1 as the 10-bit angle."""
    a = e - l
    b = 0
    if a < 0:
        b = 1
        a = -a
    c = a & 0xFF
    a = d - h
    if a < 0:
        b = (b ^ 1) | 2
        a = -a
    a &= 0xFF
    cy1 = 1 if a < c else 0                 # cp c
    t = ((a << 1) | cy1) & 0xFF             # rla
    t ^= b                                  # xor b
    cy = (t & 1) ^ 1                        # rra ; ccf
    b = ((b << 1) | cy) & 0xFF              # rl b
    if cy1:                                 # |dy| < |dx| : swap so c=smaller, a=larger
        c, a = a, c
    hl, _ = c_0EAA(c << 8, a)
    hh, ll = hl >> 8, hl & 0xFF
    if (hh ^ b) & 1:
        ll = (~ll) & 0xFF
    return (b << 8) | ll


def angle_to(ty2, tx2, y2, x2):
    """10-bit angle as stored by FB/F4 (srl h; rr l)."""
    return c_0E5B(ty2, tx2, y2, x2) >> 1


def s8(v):
    return v - 256 if v & 0x80 else v


# ============================================================================
# Formation (home positions) -- main CPU c_12C3, f_2A90 (sway), f_1DE6 (breathing)
# ============================================================================
class Formation:
    def __init__(self, flip=0):
        self.flip = flip
        self.loc_t = [0] * 0x20        # even: offset, odd: origin (ds_hpos_loc_t)
        self.spcoords = [0] * 0x20     # ds_hpos_spcoords (sprite coordinates)
        self.nest_dir = flip           # ds_9200_glbls[0x0F]
        self.bitmap = [0] * 16         # ds10_9920
        self.nestlr_inh = 0
        self.sway_active = False
        self.breathe_active = False
        self.c_12C3(0)

    def c_12C3(self, ofs):
        for i in range(16):
            self.loc_t[2 * i] = 0
            self.loc_t[2 * i + 1] = DB_FMTN_HPOS_ORIG[i]
        for i in range(10):
            a = DB_FMTN_HPOS_ORIG[i]
            if self.flip:
                a = (~(a + 0x0D)) & 0xFF
            self.spcoords[2 * i] = a
            self.spcoords[2 * i + 1] = 0
        for i in range(6):
            a = (DB_FMTN_HPOS_ORIG[10 + i] + ofs) & 0xFF
            if not self.flip:
                a = (~(a + 0x4F)) & 0xFF
            self.spcoords[20 + 2 * i] = (a << 1) & 0xFF
            self.spcoords[21 + 2 * i] = a >> 7
        self.nest_dir = self.flip

    def slot_xy(self, obj):
        """Current sprite (X, Y9) of an object's home slot."""
        row, col = HPOS[obj], HPOS[obj + 1]
        return self.spcoords[col], self.spcoords[row] | (self.spcoords[row + 1] << 8)

    def origin_xy(self, obj):
        row, col = HPOS[obj], HPOS[obj + 1]
        r = self.loc_t[row + 1]
        return self.loc_t[col + 1], ((~(r + 0x4F)) & 0xFF) << 1

    def _add(self, n, inc):
        self.loc_t[2 * n] = (self.loc_t[2 * n] + inc) & 0xFF
        v = self.spcoords[2 * n] + inc
        if v > 0xFF or v < 0:
            self.spcoords[2 * n + 1] ^= 1
        self.spcoords[2 * n] = v & 0xFF

    def f_2A90(self, frame, any_active, f2916_active):
        """Left/right sway during entry waves (gg1-3.s f_2A90)."""
        if not self.sway_active or ((frame - 1) & 3):
            return
        if not any_active and not f2916_active:
            self.sway_active = False
            return
        c = 1 if self.nest_dir == 0 else 0xFF
        for i in range(10):
            self.loc_t[2 * i] = (self.loc_t[2 * i] + c) & 0xFF
            self.spcoords[2 * i] = (self.spcoords[2 * i] + c) & 0xFF   # LSB only
        o0 = self.loc_t[0]
        if self.nestlr_inh and o0 == 0:
            self.nest_dir = 0
            self.sway_active = False
            self.breathe_active = True
            return
        if o0 == 32:
            self.nest_dir = 1
        elif o0 == 0xE0:
            self.nest_dir = 0

    def f_1DE6(self, frame):
        """Expand/contract 'breathing' (gg1-2_fx.s f_1DE6 / c_1E43)."""
        if not self.breathe_active or (frame & 3):
            return
        e = self.nest_dir
        if e & 0x80:
            cnt = (e - 1) & 0xFF
        else:
            cnt = (e + 1) & 0xFF
        if e == 0x1F:
            cnt |= 0x80
        if e == 0x81:
            cnt &= 0x7F
        self.nest_dir = cnt
        if (e & 7) == 0:
            r = (cnt & 0x18) >> 3
            self.bitmap = list(D_1E64_BITMAP_TABLES[16 * r:16 * r + 16])
        if ((e >> 7) ^ self.flip) & 1:
            binc, cinc = 1, -1
        else:
            binc, cinc = -1, 1
        for n in range(16):
            bit = self.bitmap[n] & 1
            self.bitmap[n] = (self.bitmap[n] >> 1) | (bit << 7)
            if bit:
                self._add(n, binc if n < 5 else cinc)


# ============================================================================
# The machine: motion queue (sub CPU f_08D3) + the main-CPU pieces that touch it
# ============================================================================
class Slot:
    __slots__ = ('b', 'idx')

    def __init__(self, idx):
        self.b = [0] * 0x14
        self.idx = idx


class Machine:
    """Frame order per tick (assumption, see spec): frame_cts[0]++ ; main-CPU tasks
    (f_2916, f_1DE6, f_2A90, c_23E0, f_1DD2, hooks) ; sub-CPU f_08D3 over the 12 slots."""

    def __init__(self, frame0=0, fighter_x=0x7A, parm8=0, parm9=0, cont_bomb=0, task1D=0,
                 flip=0, formation=None):
        self.frame = frame0 & 0xFF
        self.cts2 = 0                   # ds3_92A0_frame_cts[2]
        self.slots = [Slot(i) for i in range(12)]
        self.state = [0x80] * 0x80      # b_8800 even bytes
        self.obj_slot = [0] * 0x80      # b_8800 odd bytes (slot index)
        self.spr_x = [0] * 0x80
        self.spr_y = [0] * 0x80
        self.spr_code = [0] * 0x80
        self.spr_ctrl = [0] * 0x80
        self.fighter_x = fighter_x
        self.parm8, self.parm9 = parm8, parm9
        self.cont_bomb, self.task1D = cont_bomb, task1D
        self.flip = flip
        self.form = formation or Formation(flip)
        self.flying_cnt = 0
        self.flying_nbr = 0
        self.captr0 = 0
        self.tick = 0
        self.tracks = {}                # obj -> list of dicts
        self.hooks = []                 # callables(machine) run in the main-CPU phase
        self.enemy_enable = 3

    # ---------------------------------------------------------------- recording
    def _rec(self, obj, moved, ev):
        s = self.slots[self.obj_slot[obj]]
        self.tracks.setdefault(obj, []).append(dict(
            tick=self.tick, frame=self.frame, x=self.spr_x[obj], y=self.spr_y[obj],
            angle=((s.b[5] & 3) << 8) | s.b[4], code=self.spr_code[obj], ctrl=self.spr_ctrl[obj],
            moved=moved, event=','.join(ev) if ev else None))

    # ---------------------------------------------------------------- launches
    def launch_entry(self, slot, obj, token, transient_kind=None):
        """f_2916 l_2974.. l_2A05: token = the byte from d_*_stg_dat (bit7 = no delay,
        bit6 = mirror + 2nd start set, bits5:0 = db_2A3C index, bit0 = side-entry bomb timer)."""
        s = self.slots[slot]
        b = s.b
        b[0x10] = obj
        self.state[obj] = 7
        self.obj_slot[obj] = slot
        d = (token << 1) & 0xFF
        cidx = d & 0x7F
        b[0x0E] = 0x44 if cidx & 2 else 0x08
        label, sel = DB_2A3C[cidx >> 1]
        w = LABEL_ADDR[label]
        b[0x08], b[0x09] = w & 0xFF, w >> 8
        i = sel * 6 + (3 if d & 0x80 else 0)
        b[0x01], b[0x03], b[0x05] = DB_2A6C[i], DB_2A6C[i + 1], DB_2A6C[i + 2]
        b[0x00] = b[0x02] = b[0x04] = 0
        b[0x0D] = 1
        b[0x13] = (1 | d) & 0x81
        return s

    def launch_dive(self, obj, path, mirror=None, boss_flag=None):
        """gg1-2.s c_1083 / c_1079 / j_108A: dive from the object's current sprite position.
        mirror default = bit1 of the object id (right half of the formation)."""
        for s in self.slots:
            if not s.b[0x13] & 1:
                break
        else:
            return None
        if mirror is None:
            mirror = (obj >> 1) & 1
        b = s.b
        w = addr_of(path)
        b[0x08], b[0x09] = w & 0xFF, w >> 8
        b[0x0D] = 1
        b[0x04], b[0x05] = 0x00, 0x01            # angle 0x100 (up)
        b[0x10] = obj
        self.state[obj] = 9
        self.obj_slot[obj] = s.idx
        x, y9 = self.spr_x[obj], self.spr_y[obj]
        yb = y9 >> 1
        cy = y9 & 1
        if not self.flip:
            yb = (-(yb + 0x50)) & 0xFF
            cy ^= 1
        b[0x01] = yb
        b[0x00] = cy << 7
        if self.flip:
            x = (~(x + 0x0D)) & 0xFF
        b[0x03] = x >> 1
        b[0x02] = (x & 1) << 7
        b[0x13] = (0x80 if mirror else 0) | 1
        b[0x0E] = 0x1E
        return s

    # ---------------------------------------------------------------- f_08D3
    def run_motion(self):
        self.flying_nbr = self.flying_cnt
        self.flying_cnt = 0
        for s in self.slots:
            if s.b[0x13] & 1:
                self._motion_slot(s)

    def _inactive(self, s, obj, ev):
        self.state[obj] = 0x80
        self.spr_x[obj] = 0
        s.b[0x13] = 0
        ev.append('END')
        self._rec(obj, False, ev)

    def _motion_slot(self, s):
        b = s.b
        self.flying_cnt += 1
        obj = b[0x10]
        ev = []
        if self.state[obj] not in (3, 7, 9):
            self._inactive(s, obj, ev)
            return
        b[0x0D] = (b[0x0D] - 1) & 0xFF
        if b[0x0D] == 0:
            hl = b[0x08] | (b[0x09] << 8)
            consume = False
            while True:
                t = rom(hl)
                if t < 0xEF:                                     # l_0BDC_flite_pth_load
                    b[0x0A] = t & 0x0F
                    b[0x0B] = t >> 4
                    dl = rom(hl + 1)
                    if b[0x13] & 0x80:
                        dl = (-dl) & 0xFF
                    b[0x0C] = dl
                    b[0x0D] = rom(hl + 2)
                    ev.append('%04X:seg %02X %02X %02X' % (hl, t, rom(hl + 1), rom(hl + 2)))
                    hl += 3
                    break
                ev.append('%04X:%02X' % (hl, t))
                if t == 0xFF:                                    # case_0E49
                    self._inactive(s, obj, ev)
                    return
                elif t == 0xFE:                                  # case_0B16
                    cy = (self.flip ^ (b[0x13] >> 7)) & 1
                    a = self.fighter_x or 0x80
                    if not cy:
                        a = (-a + 0xF2) & 0xFF
                    a = (a + 0x0E) & 0xFF
                    idx = a // 0x1E
                    b[0x0D] = rom(hl + idx)
                    hl += 9
                    break
                elif t == 0xFD:                                  # case_0B46
                    hl = word(hl + 1)
                elif t == 0xFC:                                  # case_0B4E
                    b[0x06] = rom(hl + 1)
                    b[0x07] = 0
                    b[0x13] |= 0x20
                    hl += 2
                    break
                elif t == 0xFB:                                  # case_0AA0
                    self.state[obj] = 9
                    row, col = HPOS[obj], HPOS[obj + 1]
                    lt = self.form.loc_t
                    bo, e = lt[col], lt[col + 1] >> 1
                    co, d = lt[row], lt[row + 1]
                    b[0x11], b[0x12] = bo, co
                    if self.flip:
                        bo, co = (-bo) & 0xFF, (-co) & 0xFF
                    y16 = ((b[1] << 8) | b[0]) + ((s8(co) * 128) & 0xFFFF)
                    y16 &= 0xFFFF
                    b[0], b[1] = y16 & 0xFF, y16 >> 8
                    x16 = (((b[3] << 8) | b[2]) - s8(bo) * 128) & 0xFFFF
                    b[2], b[3] = x16 & 0xFF, x16 >> 8
                    ang = angle_to(d, e, b[1], b[3])
                    b[4], b[5] = ang & 0xFF, ang >> 8
                    b[6], b[7] = d, e
                    b[0x13] |= 0x40
                    hl += 1
                elif t == 0xFA:                                  # case_0BD1
                    a = ((self.task1D - 1) & 0xFF) & (self.cont_bomb & 0xFF)
                    hl = word(hl + 1) if a == 0 else hl + 3
                elif t == 0xF9:                                  # case_0B5F
                    a = self.form.spcoords[HPOS[obj + 1]]
                    if self.flip:
                        a = (-(a + 0x0E)) & 0xFF
                    b[0x03] = a >> 1
                    hl += 1
                    consume = True
                    break
                elif t == 0xF8:                                  # case_0B87
                    b[0x01] = 0x9C
                    hl += 1
                    consume = True
                    break
                elif t == 0xF7:                                  # case_0B98
                    hl = word(hl + 1) if (obj & 0x38) == 0x38 else hl + 3
                elif t == 0xF6:                                  # case_0BA8
                    a = rom(hl + 1)
                    if b[0x13] & 0x80:
                        a = (-(a + 0x80)) & 0xFF
                    b[0x04] = (a << 2) & 0xFF
                    b[0x05] = a >> 6
                    b[0x0E] = 0x1E
                    hl += 2
                    consume = True
                    break
                elif t == 0xF5:                                  # case_0942
                    self.state[obj] = 3
                    hl += 1
                elif t == 0xF4:                                  # case_0A53
                    a = (((self.fighter_x + 3) & 0xF8) + 1) & 0xFF
                    if a < 0x29:
                        a = 0x29
                    if a >= 0xCA:
                        a = 0xC9
                    if self.flip:
                        a = (~(a + 13)) & 0xFF
                    self.captr0 = a
                    ang = angle_to(0x48, a >> 1, b[1], b[3])
                    b[4], b[5] = ang & 0xFF, ang >> 8
                    hl += 1
                elif t == 0xF3:                                  # case_0A01
                    a = self.fighter_x
                    a = max(0x1E, min(0xD1, a))
                    if self.flip:
                        a = (-(a + 0x0E)) & 0xFF
                    a >>= 1
                    r = a - b[0x03]
                    borrow = 1 if r < 0 else 0
                    a = ((borrow << 7) | ((r & 0xFF) >> 1)) & 0xFF
                    if b[0x13] & 0x80:
                        a = (-a) & 0xFF
                    a = (a + 0x18) & 0xFF
                    if a & 0x80:
                        a = 0
                    if a >= 0x30:
                        a = 0x2F
                    b[0x0D] = rom(hl + a // 6 + 1)
                    hl += 9
                    break
                elif t == 0xF2:                                  # case_097B
                    hl = self._clone(s, obj, hl)
                elif t == 0xF1:                                  # case_0968
                    b[0x01] = (self.form.loc_t[HPOS[obj] + 1] + 0x20) & 0xFF
                    hl += 1
                    consume = True
                    break
                elif t in (0xF0, 0xEF):                          # case_0955 / case_094E
                    flag = self.parm8 if t == 0xF0 else self.parm9
                    hl = word(hl + 1) if flag else hl + 3
                    consume = True
                    break
            b[0x08], b[0x09] = hl & 0xFF, (hl >> 8) & 0xFF
            if consume:                                          # l_0B8B / l_0B8C
                b[0x0D] = (b[0x0D] + 1) & 0xFF
                self._rec(obj, False, ev)
                return
        # ------------------------------------------------ l_0C05_flite_pth_cont
        if b[0x13] & 0x40:
            if _near(b[1], b[6]) and _near(b[3], b[7]):
                b[0x13] &= ~1                                    # l_0E08_imhome
                b[0] = b[2] = 0
                self.state[obj] = 2
                b[1], b[3] = b[6], b[7]
                ev.append('HOME')
                self._posn_set(s, obj)
                self._rec(obj, True, ev)
                return
        if b[0x13] & 0x20:                                       # l_0C2D
            a = (b[1] - b[6]) & 0xFF
            if a == 0 or a == 0xFF:
                b[0x0D] = 1
                b[0x13] &= ~0x20
                ev.append('Y-reached')
        # angle update (l_0C46)
        dl = b[0x0C]
        e_old, d_old = b[4], b[5]
        ssum = e_old + dl
        b[4] = ssum & 0xFF
        if ((ssum >> 8) ^ (dl >> 7)) & 1:
            b[5] = (d_old + (1 if dl < 0x80 else 0xFF)) & 0xFF
        # sprite tile + flips from the OLD angle
        a = e_old
        if d_old & 1:
            a = (~a) & 0xFF
        if a + 21 > 0xFF:
            tile = 6
        else:
            v = a + 21
            tile = (((v >> 1) + (v >> 2)) >> 5) & 7
        self.spr_code[obj] = (self.spr_code[obj] & 0xF8) | tile
        q1, q0 = (d_old >> 1) & 1, d_old & 1
        self.spr_ctrl[obj] = (((q0 ^ q1) ^ 1) << 1) | q1
        # displacement: nibble selected by frame parity
        v = b[0x0A] if (self.frame & 1) else b[0x0B]
        if v:
            q = d_old & 3
            e7 = e_old >> 7
            oct_ = ((q << 1) | e7) & 0xFF
            prim = 0 if ((q ^ oct_) & 1) else 2                 # 0 -> Y (b00/b01), 2 -> X (b02/b03)
            a = v
            if (oct_ + 1) & 4:
                a = (-v) & 0xFF
            c = s8(a) >> 1 & 0xFF
            lo, hi = b[prim], b[prim + 1]
            carry = 0
            if a & 1:
                lo += 0x80
                carry = lo >> 8
                lo &= 0xFF
            hi = (hi + c + carry) & 0xFF
            b[prim], b[prim + 1] = lo, hi
            sec = prim ^ 2
            L = e_old & 0x7F
            if e7:
                L ^= 0x7F
            prod = L * v
            if (((oct_ ^ 2) - 1) & 0xFF) & 4:
                prod = (-prod) & 0xFFFF
            val = (((b[sec + 1] << 8) | b[sec]) + prod) & 0xFFFF
            b[sec], b[sec + 1] = val & 0xFF, val >> 8
        self._posn_set(s, obj)
        self._rec(obj, True, ev)

    def _posn_set(self, s, obj):                                 # l_0D03_flite_pth_posn_set
        b = s.b
        x = ((b[3] << 1) | (1 if b[2] > 0x7F else 0)) & 0xFF
        if self.flip:
            x = (~(x + 0x0D)) & 0xFF
        if b[0x13] & 0x40:
            x = (x + b[0x11]) & 0xFF
        self.spr_x[obj] = x
        c = 1 if b[0] > 0x7F else 0
        a = b[1]
        if not self.flip:
            a = (~(a + 0x4F)) & 0xFF
            c ^= 1
        y9 = ((a << 1) | c) & 0x1FF
        if b[0x13] & 0x40:
            y9 = (y9 + s8(b[0x12])) & 0x1FF
        self.spr_y[obj] = y9

    def _clone(self, s, obj, hl):                                # case_097B
        for new in (0x38, 0x3A, 0x3C, 0x3E):
            if self.state[new] & 0x80:
                break
        else:
            return hl + 3
        self.spr_code[new] = self.spr_code[obj]
        for t in reversed(self.slots):
            if not t.b[0x13] & 1:
                break
        else:
            return hl + 3
        for i in range(6):
            t.b[i] = s.b[i]
        # NOTE: the listing reads 'ex de,hl / add hl,de / ex de,hl' before copying 4 more
        # bytes; the evident intent (dst += 6) is modelled here: copy b0C..b0F.  Either
        # way b0A..b0D are reloaded from the clone's own path on its next step, so the
        # trajectory is unaffected.
        for i in range(0x0C, 0x10):
            t.b[i] = s.b[i]
        t.b[0x13] = s.b[0x13]
        w = word(hl + 1)
        t.b[0x08], t.b[0x09] = w & 0xFF, w >> 8
        t.b[0x0A], t.b[0x0B], t.b[0x0D] = 1, 2, 1
        t.b[0x10] = new
        self.state[new] = 9
        self.obj_slot[new] = t.idx
        return hl + 3

    # ---------------------------------------------------------------- c_23E0 (subset)
    def c_23E0(self):
        fc = self.frame
        if not fc & 1:
            return
        for obj in range(fc & 2, 0x80, 4):
            st = self.state[obj]
            if st & 0x80:
                continue
            if st == 9:
                row, col = HPOS[obj], HPOS[obj + 1] if obj < 0x60 else (0, 0)
                if obj < 0x60:
                    sl = self.slots[self.obj_slot[obj]]
                    sl.b[0x11] = self.form.loc_t[col]
                    sl.b[0x12] = self.form.loc_t[row]
            elif st == 7:
                self.state[obj] = 3
            elif st == 3:
                x, y9 = self.spr_x[obj], self.spr_y[obj]
                if x >= 0xF4 or (y9 >> 1) < 0x0B or (y9 >> 1) >= 0xA5:
                    self.slots[self.obj_slot[obj]].b[0x13] = 0
                    self.state[obj] = 0x80
                    self.spr_x[obj] = 0
                    self.tracks.setdefault(obj, []).append(dict(
                        tick=self.tick, frame=self.frame, x=x, y=y9, angle=None, code=None,
                        ctrl=None, moved=False, event='CULLED off-screen (c_23E0 state 3)'))
            elif st == 2 and obj < 0x60:
                if self.spr_ctrl[obj] & 1:
                    if (self.spr_code[obj] & 7) == 0:
                        self.spr_ctrl[obj] &= ~1
                    else:
                        self.spr_code[obj] -= 1
                elif (self.spr_code[obj] & 7) == 6:
                    self.state[obj] = 1
                else:
                    self.spr_code[obj] += 1
                self.spr_x[obj], self.spr_y[obj] = self.form.slot_xy(obj)
            elif st == 1 and obj < 0x60 and self.enemy_enable:
                self.spr_x[obj], self.spr_y[obj] = self.form.slot_xy(obj)

    # ---------------------------------------------------------------- tick
    def step(self):
        self.tick += 1
        self.frame = (self.frame + 1) & 0xFF
        # frame_cts[2] exactly as jp_0513_rst38
        m = self.frame & 0x1F
        if m == 1:
            self.cts2 = (self.cts2 + 1) & 0xFF
        elif m == 0:
            self.cts2 = ((self.cts2 | 1) + 1) & 0xFF
        for h in self.hooks:
            h(self)
        self.form.f_1DE6(self.frame)
        self.form.f_2A90(self.frame, any(st != 0x80 for st in self.state[:0x60]),
                         getattr(self, 'f2916_active', False))
        self.c_23E0()
        self.run_motion()


def _ended(rec):
    ev = (rec['event'] or '').split(',')
    return 'HOME' in ev or 'END' in ev or (rec['event'] or '').startswith('CULLED')


def _near(a, b):
    d = (a - b) & 0xFF
    if d == 0:
        return True
    if d & 0x80:
        d = (-d) & 0xFF
    return d == 1


# ============================================================================
# Reference interpreter entry point
# ============================================================================
def fly(path_label, x, y, angle, mirror, home=(0x71, 92), frames=600, obj=None,
        fighter_x=0x7A, frame0=0, parm8=0, parm9=0, cont_bomb=0, task1D=0,
        transient=False, home_offset=None, state=9):
    """Fly one object along a path.

    x, y      : start in sprite-register coordinates (spriteX, 9-bit spriteY)
    angle     : 10-bit start angle (0=right, 256=up, 512=left, 768=down)
    mirror    : True negates every angle delta (bit7 of b13) and mirrors F6/F3/FE
    home      : (spriteX, spriteY) of the home slot at zero formation offset; must be one
                of the 10 columns 0x31..0xC1 x 6 rows 60,76,92,104,116,128 unless obj given
    obj       : object id (overrides home); transient=True uses 0x38 (F7 jumps taken)
    home_offset: optional callable(frame_index) -> (dx, dy) formation offset
    Returns [(x, y, angle, event), ...] one entry per frame (spriteX, spriteY9).
    """
    m = Machine(frame0=frame0, fighter_x=fighter_x, parm8=parm8, parm9=parm9,
                cont_bomb=cont_bomb, task1D=task1D)
    if transient:
        obj = 0x38
    if obj is None:
        hx, hy = home
        for o in range(0, 0x60, 2):
            if m.form.origin_xy(o) == (hx, hy):
                obj = o
                break
        else:
            raise ValueError('home %r is not a formation slot' % (home,))
    s = m.slots[0]
    b = s.b
    yint = (0x161 - y) & 0x1FF
    b[1], b[0] = yint >> 1, (yint & 1) << 7
    b[3], b[2] = x >> 1, (x & 1) << 7
    b[4], b[5] = angle & 0xFF, (angle >> 8) & 3
    w = addr_of(path_label)
    b[8], b[9] = w & 0xFF, w >> 8
    b[0x0D] = 1
    b[0x10] = obj
    b[0x13] = 1 | (0x80 if mirror else 0)
    m.state[obj] = state
    m.obj_slot[obj] = 0
    out = []
    for i in range(frames):
        if home_offset:
            dx, dy = home_offset(i)
            for c in range(10):
                m.form.loc_t[2 * c] = dx & 0xFF
                m.form.spcoords[2 * c] = (m.form.loc_t[2 * c + 1] + dx) & 0xFF
        m.step()
        tr = m.tracks.get(obj, [])
        if not tr:
            continue
        r = tr[-1]
        out.append((r['x'], r['y'], r['angle'], r['event']))
        if _ended(r):
            break
    return out


# ============================================================================
# Stage / wave construction (gg1-3.s c_25A2, f_2916)
# ============================================================================
def stage_row(stage, rank=3):
    """Return (kind, row_offset, row_bytes) selected by c_25A2 for a 1-based stage."""
    a = stage & 0xFF
    while a >= 0x17:
        a -= 4
    if (a + 1) & 3:
        idx = a - (a >> 2) - 1
        off = D_COMBAT_STG_DAT_IDX[rank * 17 + idx]
        return 'combat', off, D_COMBAT_STG_DAT[off:off + 18]
    off = D_CHALLG_STG_DATA_IDX[(stage >> 2) & 7]
    return 'challenge', off, D_CHALLG_STG_DAT[off:off + 18]


def stage_parms(stage, rank=3):
    """new_stage.s c_2C00: 10 nibbles [0..9] + [10]."""
    a = stage
    while a >= 0x1B:
        a -= 4
    e = (a - 1) * 5
    base = [0x82, 0x82 * 2, 0x82 * 3, 0][rank]
    by = BMBR_STG_CFG_DAT[base + e: base + e + 5]
    p = []
    for v in by:
        p += [v >> 4, v & 15]
    p.append(0 if stage < 3 else (0 if (stage | 0xFC) == 0xFF else 0x0A))
    return p


def build_wave_table(stage, rank=3, rng=None):
    """c_25A2: returns (hdr0, hdr1, table) where table is the ds_8920 byte stream."""
    rng = rng or random.Random(0)
    kind, off, row = stage_row(stage, rank)
    hdr0, hdr1 = row[0], row[1]
    p = 2
    table = [0x7E]
    ids = 0
    while row[p] != 0xFF:
        c = row[p]
        p += 1
        tmp = [0xFF] * 16
        n = c & 0x0F
        if n:
            e = (n >> 1) + 4
            bb = n
            while bb:
                while True:
                    slot = rng.randrange(256) % e          # c_1000 (R register) -> modelled RNG
                    if bb & 1:
                        slot |= 8
                    if tmp[slot] == 0xFF:
                        break
                cy = c >> 7
                c = ((c << 1) | cy) & 0xFF
                tmp[slot] = ((bb << 1) & 0xFF) | (0x40 if cy else 0) | 0x38
                bb -= 1
        i = 0
        for k in range(8, 0, -1):
            while tmp[i] != 0xFF:
                i += 1
            tmp[i] = DB_ATTK_WAV_IDS[ids]
            ids += 1
            i += 1
            if k == 5:
                i = 8
        lb, rb = row[p], row[p + 1]
        p += 2
        i = 0
        while tmp[i] != 0xFF:
            table += [lb, tmp[i], rb, tmp[i + 8]]
            i += 1
        table.append(0x7E)
    table[-1] = 0x7F
    return hdr0, hdr1, table


def describe_stage(stage, rank=3):
    kind, off, row = stage_row(stage, rank)
    lines = ['stage %d (rank %s): %s row 0x%02X  header %02X %02X' % (
        stage, 'BCDA'[rank], kind, off, row[0], row[1])]
    for w in range(5):
        t0, t1, t2 = row[2 + 3 * w: 5 + 3 * w]
        ids = DB_ATTK_WAV_IDS[8 * w: 8 * w + 8]
        def tok(t):
            lab, sel = DB_2A3C[t & 0x3F]
            st = DB_2A6C[sel * 6 + (3 if t & 0x40 else 0): sel * 6 + (6 if t & 0x40 else 3)]
            return 'path%02X=%s%s start(b01=%02X,b03=%02X,b05=%02X)->spr(%d,%d) ang=%d' % (
                t & 0x3F, lab, ' MIRROR' if t & 0x40 else '', st[0], st[1], st[2],
                2 * st[1], 0x161 - 2 * st[0], st[2] << 8)
        n = t0 & 15
        trans = ''
        if n:
            kinds = []
            cc = t0
            for k in range(n):
                cy = cc >> 7
                cc = ((cc << 1) | cy) & 0xFF
                kinds.append('moth' if cy else ('boss' if w == 1 else 'bee'))
            trans = ' transients=%d %s' % (n, kinds)
        lines.append('  wave %d: byte0=%02X%s  %s' % (w + 1, t0, trans,
                     'side-by-side (1 frame apart)' if t2 & 0x80 else 'trailing (every 8 frames)'))
        lines.append('     lefty  %s  ids %s' % (tok(t1), ' '.join('%02X' % i for i in ids[:4])))
        lines.append('     righty %s  ids %s' % (tok(t2), ' '.join('%02X' % i for i in ids[4:])))
    return '\n'.join(lines)


def simulate_stage(stage=1, rank=3, frames=3000, frame0=0, rng_seed=0, fighter_x=0x7A):
    """Entry waves of a stage: f_2916 launcher + f_2A90 sway + c_23E0 + f_08D3."""
    kind, _, _ = stage_row(stage, rank)
    parms = stage_parms(stage, rank)
    m = Machine(frame0=frame0, fighter_x=fighter_x, parm8=parms[8], parm9=parms[9])
    m.form.sway_active = True
    hdr0, hdr1, table = build_wave_table(stage, rank, random.Random(rng_seed))
    st = dict(ptr=0, wave=0, tmr0=2, launches=[])
    m.f2916_active = True
    challenge = kind == 'challenge'
    code_for = {}

    def f_2916(mm):
        if not mm.f2916_active:
            return
        if mm.frame & 0x1F == 0 and st['tmr0']:      # f_1DD2 (cts2 even only on this frame)
            st['tmr0'] -= 1
        tok = table[st['ptr']]
        if tok == 0x7F:
            if mm.flying_nbr == 0:
                mm.f2916_active = False
                mm.form.nestlr_inh = 1
            return
        if tok == 0x7E:
            if mm.flying_nbr:
                st['tmr0'] = 2
                return
            if challenge:
                if st['tmr0'] == 1 or st['tmr0']:
                    return
            st['ptr'] += 1
            st['wave'] += 1
            return
        if not (tok & 0x80) and (mm.frame & 7):
            return
        for sl in mm.slots:
            if not sl.b[0x13] & 1:
                break
        else:
            return
        raw = table[st['ptr'] + 1]
        obj = raw & ~0x40 if (raw & 0x78) == 0x78 else raw
        st['ptr'] += 2
        mm.launch_entry(sl.idx, obj, tok)
        st['launches'].append(dict(tick=mm.tick, frame=mm.frame, wave=st['wave'], obj=obj,
                                   raw=raw, token=tok, slot=sl.idx,
                                   path=DB_2A3C[tok & 0x3F][0], mirror=bool(tok & 0x40)))
    m.hooks.append(f_2916)
    for _ in range(frames):
        m.step()
        if not m.f2916_active and not m.form.sway_active:
            break
    return m, st['launches'], table


def capture_boss_hook(obj, beam_frames=328):
    """Approximation of the main-CPU side of a capture dive (gg1-3.s f_21CB + f_2222):
    once the boss has loaded the '00 FC FF' segment (b0A == 0) f_21CB forces the angle
    delta to +12 or -12 (-12 if b05 bit0) until ((b05&1)<<7 | b04>>1) - 0x78 < 0x10,
    then zeroes it; f_2222 sets b0D=0xFF while the beam runs and b0D=1 when it ends.
    beam_frames (extend 11 steps + 64-frame hold + retract 11 steps at the stage's
    capture-step period, ~12 frames) is NOT cycle-exact."""
    st = dict(phase=0, t=0)

    def hook(m):
        if m.state[obj] != 9:
            return
        s = m.slots[m.obj_slot[obj]]
        b = s.b
        if st['phase'] == 0:
            if b[0x0A] != 0:
                return
            b[0x0C] = 0xF4 if b[5] & 1 else 0x0C
            a = ((((b[5] & 1) << 7) | (b[4] >> 1)) - 0x78) & 0xFF
            if a < 0x10:
                b[0x0C] = 0
                st['phase'] = 1
        elif st['phase'] == 1:
            b[0x0D] = 0xFF
            st['t'] += 1
            if st['t'] >= beam_frames:
                b[0x0D] = 1
                st['phase'] = 2
    return hook


def simulate_dive(obj, path=None, frames=900, fighter_x=0x7A, breathe=True, frame0=0,
                  settle=0, parm9=0, cont_bomb=0, hooks=()):
    """One diving attack from the formation (all other enemies resting).  The formation
    'breathes' (f_1DE6) from nest counter 0 if breathe=True; `settle` frames run first."""
    if path is None:
        path = ('db_flv_atk_yllw' if obj < 0x30 else 'db_flv_0411' if obj < 0x38
                else 'db_flv_atk_red')
    m = Machine(frame0=frame0, fighter_x=fighter_x, parm9=parm9, cont_bomb=cont_bomb)
    m.form.breathe_active = breathe
    m.hooks.extend(hooks)
    for o in range(0, 0x60, 2):
        if 0x08 <= o < 0x38 or o >= 0x40:
            m.state[o] = 1
            m.spr_code[o] = 6
            m.spr_x[o], m.spr_y[o] = m.form.slot_xy(o)
    for _ in range(settle):
        m.step()
    m.launch_dive(obj, path)
    for _ in range(frames):
        m.step()
        tr = m.tracks.get(obj)
        if tr and _ended(tr[-1]):
            break
    return m


# ============================================================================
# Demo
# ============================================================================
WAVE_COLOURS = [(255, 80, 80), (80, 200, 255), (120, 255, 120), (255, 220, 60), (230, 120, 255)]


def _screen(x, y):
    """Sprite registers -> centre pixel on the 224x288 portrait screen."""
    return x - 17 + 8, y - 40 + 8


def _summ(track):
    pts = [r for r in track if r['angle'] is not None]
    xs = [r['x'] for r in pts]
    ys = [r['y'] for r in pts]
    home = next((r['tick'] for r in track if 'HOME' in (r['event'] or '').split(',')), None)
    return xs, ys, home, (track[-1]['event'] or '')


def _plot(filename, series, title, form=None):
    from PIL import Image, ImageDraw
    S = 2
    img = Image.new('RGB', (224 * S, 288 * S), (8, 8, 20))
    dr = ImageDraw.Draw(img)
    form = form or Formation()
    for o in range(0, 0x60, 2):
        if 0x08 <= o < 0x38 or o >= 0x40:
            x, y = form.origin_xy(o)
            cx, cy = _screen(x, y)
            dr.rectangle([(cx - 7) * S, (cy - 7) * S, (cx + 7) * S, (cy + 7) * S], outline=(60, 60, 90))
    for label, pts, col in series:
        sp = [(_screen(x, y)[0] * S, _screen(x, y)[1] * S) for x, y in pts]
        run = sp[:1]
        for p in sp[1:]:                       # break the polyline at teleports (F8/F9/F1)
            if abs(p[0] - run[-1][0]) + abs(p[1] - run[-1][1]) > 24 * S:
                if len(run) > 1:
                    dr.line(run, fill=col, width=1)
                run = [p]
            else:
                run.append(p)
        if len(run) > 1:
            dr.line(run, fill=col, width=1)
        for i, p in enumerate(sp):
            if i % 30 == 0:
                dr.ellipse([p[0] - 2, p[1] - 2, p[0] + 2, p[1] + 2], fill=col)
        if sp:
            dr.rectangle([sp[0][0] - 3, sp[0][1] - 3, sp[0][0] + 3, sp[0][1] + 3], outline=col)
    dr.text((4, 4), title, fill=(220, 220, 220))
    dr.text((4, 288 * S - 14), 'centre = (sprX-9, sprY-32); dots every 30 frames; box = start', fill=(150, 150, 150))
    img.save(filename)


def main():
    import os
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'sim', 'build')
    print(describe_stage(1))
    m, launches, table = simulate_stage(1)
    print('\nstage 1 wave table (ds_8920):', ' '.join('%02X' % v for v in table))
    series = []
    print('\n%-5s %-4s %-3s %-12s %-6s %6s %6s %7s %7s  %s' % (
        'wave', 'obj', 'mir', 'path', 'launch', 'frames', 'home@', 'x-range', 'y-range', 'end'))
    for L in launches:
        tr = m.tracks[L['obj']]
        xs, ys, home, end = _summ(tr)
        series.append(('w%d %02X' % (L['wave'], L['obj']), [(r['x'], r['y']) for r in tr if r['angle'] is not None],
                       WAVE_COLOURS[(L['wave'] - 1) % 5]))
        print('%-5d %02X   %-3s %-12s %6d %6d %6s %3d-%3d %3d-%3d  %s' % (
            L['wave'], L['obj'], 'M' if L['mirror'] else '', L['path'], L['tick'],
            (home - L['tick']) if home else len(tr), home, min(xs), max(xs), min(ys), max(ys), end))
    # a bee dive: obj 0x24 = bottom bee row (0x1E), column 3 (left half); 0x26 = its mirror (column 6)
    for obj in (0x24, 0x26):
        md = simulate_dive(obj)
        tr = md.tracks[obj]
        xs, ys, home, end = _summ(tr)
        print('\nbee dive obj %02X (slot row %02X col %02X, mirror=%d): %d frames to HOME, '
              'spriteX %d..%d spriteY %d..%d  end=%s' % (
                  obj, HPOS[obj], HPOS[obj + 1], (obj >> 1) & 1, len(tr), min(xs), max(xs),
                  min(ys), max(ys), end))
        series.append(('dive %02X' % obj, [(r['x'], r['y']) for r in tr if r['angle'] is not None],
                       (255, 255, 255)))
    _plot(os.path.join(here, 'paths_stage1.png'), series,
          'Galaga stage 1 entry waves (rank A, fighter X=0x7A) + bee dives 24/26 (white)')
    # extra: dives of each class
    ds = []
    for obj, col in ((0x58, (255, 90, 90)), (0x5A, (255, 160, 160)), (0x30, (90, 255, 90)),
                     (0x08, (255, 230, 80)), (0x0A, (255, 255, 180))):
        md = simulate_dive(obj)
        tr = md.tracks[obj]
        xs, ys, home, end = _summ(tr)
        print('dive obj %02X: %d frames, spriteX %d..%d spriteY %d..%d end=%s' % (
            obj, len(tr), min(xs), max(xs), min(ys), max(ys), end))
        ds.append(('', [(r['x'], r['y']) for r in tr if r['angle'] is not None], col))
    mc = simulate_dive(0x34, 'db_0454', hooks=[capture_boss_hook(0x34)])
    tr = mc.tracks[0x34]
    xs, ys, home, end = _summ(tr)
    print('capture boss 34 (db_0454, beam modelled approx): %d frames, spriteX %d..%d spriteY %d..%d end=%s' % (
        len(tr), min(xs), max(xs), min(ys), max(ys), end))
    ds.append(('', [(r['x'], r['y']) for r in tr if r['angle'] is not None], (120, 255, 255)))
    _plot(os.path.join(here, 'paths_dives.png'), ds,
          'dives: red 58/5A, boss 30 (0411), bees 08/0A, capture boss 34 (cyan); fighter X=0x7A')

    # reference interpreter call: bee dive from its home slot (col 0x61, row Y 128 = obj 0x24)
    tr = fly('db_flv_atk_yllw', 0x61, 128, 256, False, home=(0x61, 128), frames=900)
    xs = [p[0] for p in tr]
    ys = [p[1] for p in tr]
    print('\nfly(db_flv_atk_yllw from (0x61,128), static formation): %d frames, X %d..%d Y %d..%d, last=%s'
          % (len(tr), min(xs), max(xs), min(ys), max(ys), tr[-1]))
    # challenging stage 3
    mc, lc, tc = simulate_stage(3)
    print('\n' + describe_stage(3))
    cs = []
    for L in lc:
        trc = mc.tracks[L['obj']]
        pts = [(r['x'], r['y']) for r in trc if r['angle'] is not None]
        cs.append(('', pts, WAVE_COLOURS[(L['wave'] - 1) % 5]))
        print('  wave %d obj %02X %-12s %s launch %4d  %3d frames  end=%s' % (
            L['wave'], L['obj'], L['path'], 'M' if L['mirror'] else ' ', L['tick'], len(trc),
            trc[-1]['event']))
    _plot(os.path.join(here, 'paths_challenge3.png'), cs, 'Challenging stage (stage 3) waves 1-5')


if __name__ == '__main__':
    main()
