#!/usr/bin/env python3
"""The video engine's picture, from the registers a program set.

    from cool8vid import render, save_png
    save_png(render(machine), 'screen.png')

## Where this model comes from

**Not from `rtl/soc/cool8_pixel.v`.** It is a port of the golden model in
`sim/tb/cool8_video_tb.v`, which was itself written from
docs/04-system.md section 5 rather than from the RTL — and which compares
against the hardware on all 307,200 pixels of every mode, twice a frame.

That lineage is the point. Two derivations that agree are evidence; a
model copied from the thing it checks is decoration. So this multiplies
where the RTL accumulates, renumbers a flipped tile's pixels where the
RTL reverses nibbles and swaps words, and finds the winning sprite by
looking through the list where the RTL renders backwards and lets the
last write stand.

## Whole frames, not scanlines

`cool8vm` runs the CPU a scanline at a time so raster splits behave, but
the picture is drawn here in one go from the registers as they stand.
**A mid-frame register change is therefore not visible in a rendered
frame**, which is the one place this is less faithful than the hardware.
Call `render()` per scanline if you need that; the arithmetic is
per-pixel and does not care.
"""

import os
import struct
import sys
import zlib

H_VIS, V_VIS = 640, 480


def _row_addr(vid, r):
    """A text or tile map row, wrapped inside `stride * 32`.

    The wrap is a mask, so it is correct only for a power-of-two stride —
    which is the argument D30 made for one. Software that sets 160 to get
    the 4800-byte screen back gets no wrap with it.
    """
    m = ((vid.stride << 5) - 1) & 0xFFFF
    return (vid.base & ~m) | ((vid.base + r * vid.stride) & m)


def _word(buf, byte_addr):
    """A little-endian 16-bit word out of a byte array."""
    a = byte_addr & 0xFFFF
    return buf[a] | (buf[(a + 1) & 0xFFFF] << 8)


def _sprites(vid, gx, gy, bg_index):
    """The sprite that wins at (gx, gy), or None.

    Section 5.6's rule stated directly: among the first eight descriptors
    that touch this line, in index order, the lowest-numbered one whose
    pixel is not colour zero. A sprite is in the list for two lines past
    its bottom edge — where the hardware writes the zeros that tidy its
    span away — and those trailing rows take slots like anything else.
    """
    n = 0
    for si in range(32):
        d = vid.spr[si * 8:si * 8 + 8]
        enable = bool(d[1] & 0x40)
        big = bool(d[1] & 0x80)
        sy = ((d[1] & 0x01) << 8) | d[0]
        sh = 16 if big else 8
        sdy = (gy - sy) & 0x3FF
        if not (enable and sdy < sh + 2 and n < 8):
            continue
        n += 1
        sx = ((d[3] & 0x03) << 8) | d[2]
        sdx = (gx - sx) & 0x3FF
        if sdy >= sh or sdx >= sh:
            continue                      # a trailing row draws nothing
        vflip, hflip, behind = bool(d[6] & 0x80), bool(d[6] & 0x40), bool(d[6] & 0x20)
        row = (sh - 1 - sdy) if vflip else sdy
        col = (sh - 1 - sdx) if hflip else sdx
        pat = (((d[5] & 0x07) << 8) | d[4]) << 5
        w = _word(vid.vram, pat + row * (sh >> 1) + ((col >> 2) << 1))
        ps = ((w & 0xFF) << 8) | (w >> 8)
        px = (ps >> (12 - (col & 3) * 4)) & 0x0F
        if px == 0:
            continue                      # colour zero is transparent
        if behind and bg_index != 0:
            return None
        return (vid.spr_bank << 4) | px
    return None


def pixel(vid, gx, gy):
    """The palette index at (gx, gy), border and sprites included."""
    xl = (gx >> 1) if vid.hdouble else gx
    rel = (xl - vid.hstart) & 0x7FF
    vrel = (gy - vid.vstart) & 0x3FF
    vlog = (vrel >> 1) if vid.vdouble else vrel

    if (not (vid.mode & 0x80) or xl < vid.hstart or rel >= vid.hactive
            or gy < vid.vstart or vrel >= vid.vactive):
        return vid.border

    eng = vid.engine
    if eng == 0:                                  # ---- text
        vsrc = vrel + (vid.scrl_y & 15)
        grow = vsrc & 15
        ra = _row_addr(vid, vsrc >> 4)
        cw = _word(vid.ram, ra + (rel >> 3) * 2)
        attr = cw >> 8
        fb = vid.font[((cw & 0xFF) << 4) | grow]
        lit = bool(fb & (1 << (7 - (rel & 7))))
        if (vid.cur_on and (rel >> 3) == vid.cur_x
                and (vsrc >> 4) == vid.cur_y):
            style = (vid.cur_ctrl >> 1) & 3
            if style == 0:
                lit = True
            elif style == 1:
                if (vid.cur_lines & 15) <= grow <= (vid.cur_lines >> 4):
                    lit = True
            elif style == 2:
                if (rel & 7) < 2:
                    lit = True
            else:
                lit = not lit
        idx = (attr & 0x0F) if lit else (attr >> 4)

    elif eng == 1:                                # ---- tile
        vsrc = vlog + (vid.scrl_y & 7)
        ra = _row_addr(vid, vsrc >> 3)
        sx = rel + (vid.scrl_x & 7)
        ent = _word(vid.vram, ra + (sx >> 3) * 2)
        attr = ent >> 8
        sub = sx & 7
        p = (7 - sub) if (attr & 0x40) else sub
        trow = (7 - (vsrc & 7)) if (attr & 0x80) else (vsrc & 7)
        pa = (vid.pat_base + ((attr & 0x30) << 9) + ((ent & 0xFF) << 5)
              + (trow << 2))
        w = _word(vid.vram, pa + ((p >> 2) << 1))
        ps = ((w & 0xFF) << 8) | (w >> 8)
        idx = ((attr & 0x0F) << 4) | ((ps >> (12 - (p & 3) * 4)) & 0x0F)

    else:                                         # ---- bitmap
        bpp = 1 << vid.bpp_log
        ppw = 16 // bpp
        ra = vid.base + vlog * vid.stride
        sx = rel + vid.scrl_x
        w = _word(vid.vram, ra + (sx // ppw) * 2)
        ps = ((w & 0xFF) << 8) | (w >> 8)
        k = sx % ppw
        idx = (ps >> (16 - bpp - k * bpp)) & ((1 << bpp) - 1)

    if vid.spr_en:
        s = _sprites(vid, gx, gy, idx)
        if s is not None:
            idx = s
    return idx & 0xFF


def render(machine):
    """A whole frame as 12-bit palette colours, row-major."""
    vid = machine.video
    vid.ram = machine.bus.mem            # text maps live in main RAM (D28)
    return [vid.pal[pixel(vid, x, y)] for y in range(V_VIS)
            for x in range(H_VIS)]


# ===================================================== the same, quickly
#
# `pixel()` above is the definition and `render()` is it written out; at
# 0.88 s a frame it is also twelve times the cost of emulating the
# machine that produced it, which makes an interactive front end
# impossible. What follows is the same arithmetic done to whole arrays
# at once — about a hundred times faster, and the only reason
# tools/cool8run.py can run at speed.
#
# **It is not checked against `pixel()`.** Both are checked against the
# same thing: sim/test_vm.py compares each of them to build/text.hex and
# build/tiles.hex, which are the RTL's own output. A fast path validated
# against the slow one would only prove they share a misunderstanding.

def _np():
    import numpy                          # noqa: E402  (optional)
    return numpy


def _row_addr_v(vid, r):
    m = ((vid.stride << 5) - 1) & 0xFFFF
    return (vid.base & (0xFFFF ^ m)) | ((vid.base + r * vid.stride) & m)


def _words_v(buf, addr):
    np = _np()
    a = addr & 0xFFFF
    b = np.frombuffer(bytes(buf), dtype=np.uint8).astype(np.int64)
    return b[a] | (b[(a + 1) & 0xFFFF] << 8)


def _bswap(w):
    return ((w & 0xFF) << 8) | ((w >> 8) & 0xFF)


def _sprites_v(vid, idx, np):
    """Every sprite in the frame at once, in descriptor order.

    The scalar version answers one pixel by walking the list; this walks
    the list once and paints. The order is the same and so is the
    eight-per-line cut: a sprite's place in the list is decided per
    scanline, before anything is drawn, and a sprite two lines past its
    bottom edge still takes a slot.
    """
    gy = np.arange(V_VIS)[:, None]
    gx = np.arange(H_VIS)[None, :]

    d = np.frombuffer(bytes(vid.spr), dtype=np.uint8).astype(np.int64)
    out = idx
    written = np.zeros((V_VIS, H_VIS), dtype=bool)
    used = np.zeros((V_VIS, 1), dtype=np.int64)     # slots taken per line

    for si in range(32):
        b = d[si * 8:si * 8 + 8]
        if not (b[1] & 0x40):
            continue                                # disabled: no slot
        big = bool(b[1] & 0x80)
        sh = 16 if big else 8
        sy = ((b[1] & 0x01) << 8) | b[0]
        sdy = (gy - sy) & 0x3FF
        on_line = (sdy < sh + 2) & (used < 8)
        used = used + on_line.astype(np.int64)
        if not on_line.any():
            continue

        sx = ((b[3] & 0x03) << 8) | b[2]
        sdx = (gx - sx) & 0x3FF
        cover = on_line & (sdy < sh) & (sdx < sh)
        if not cover.any():
            continue

        vflip, hflip, behind = b[6] & 0x80, b[6] & 0x40, b[6] & 0x20
        row = (sh - 1 - sdy) if vflip else sdy
        col = (sh - 1 - sdx) if hflip else sdx
        pat = (((b[5] & 0x07) << 8) | b[4]) << 5
        row = np.clip(row, 0, sh - 1)
        col = np.clip(col, 0, sh - 1)
        w = _words_v(vid.vram, pat + row * (sh >> 1) + ((col >> 2) << 1))
        ps = _bswap(w)
        px = (ps >> (12 - (col & 3) * 4)) & 0x0F

        take = (~written) & cover & (px != 0)
        if behind:
            # Behind the background: where the background is not colour
            # zero the sprite loses — and the search stops there, so no
            # lower sprite gets a look either.
            win = take & (out == 0)
        else:
            win = take
        out = np.where(win, (vid.spr_bank << 4) | px, out)
        written = written | take

    return out


def render_np(machine):
    """The frame as a 480x640 numpy array of 12-bit palette colours."""
    np = _np()
    vid = machine.video
    vid.ram = machine.bus.mem

    gy = np.arange(V_VIS)
    gx = np.arange(H_VIS)
    xl = (gx >> 1) if vid.hdouble else gx
    rel = (xl - vid.hstart) & 0x7FF
    vrel = (gy - vid.vstart) & 0x3FF
    vlog = (vrel >> 1) if vid.vdouble else vrel

    vis = (bool(vid.mode & 0x80) & (xl >= vid.hstart)[None, :] &
           (rel < vid.hactive)[None, :] & (gy >= vid.vstart)[:, None] &
           (vrel < vid.vactive)[:, None])

    eng = vid.engine
    if eng == 0:
        vsrc = vrel + (vid.scrl_y & 15)
        grow = vsrc & 15
        ra = _row_addr_v(vid, vsrc >> 4)
        cw = _words_v(vid.ram, ra[:, None] + (rel >> 3)[None, :] * 2)
        attr = cw >> 8
        f = np.frombuffer(bytes(vid.font), dtype=np.uint8).astype(np.int64)
        fb = f[((cw & 0xFF) << 4) | grow[:, None]]
        lit = ((fb >> (7 - (rel & 7))[None, :]) & 1).astype(bool)

        if vid.cur_on:
            here = (((rel >> 3) == vid.cur_x)[None, :] &
                    ((vsrc >> 4) == vid.cur_y)[:, None])
            style = (vid.cur_ctrl >> 1) & 3
            if style == 0:
                lit = np.where(here, True, lit)
            elif style == 1:
                band = (((vid.cur_lines & 15) <= grow) &
                        (grow <= (vid.cur_lines >> 4)))[:, None]
                lit = np.where(here & band, True, lit)
            elif style == 2:
                lit = np.where(here & ((rel & 7) < 2)[None, :], True, lit)
            else:
                lit = np.where(here, ~lit, lit)
        idx = np.where(lit, attr & 0x0F, attr >> 4)

    elif eng == 1:
        vsrc = vlog + (vid.scrl_y & 7)
        ra = _row_addr_v(vid, vsrc >> 3)
        sx = rel + (vid.scrl_x & 7)
        ent = _words_v(vid.vram, ra[:, None] + (sx >> 3)[None, :] * 2)
        attr = ent >> 8
        sub = (sx & 7)[None, :]
        p = np.where(attr & 0x40, 7 - sub, sub)
        tr = (vsrc & 7)[:, None]
        trow = np.where(attr & 0x80, 7 - tr, tr)
        pa = (vid.pat_base + ((attr & 0x30) << 9) + ((ent & 0xFF) << 5) +
              (trow << 2))
        ps = _bswap(_words_v(vid.vram, pa + ((p >> 2) << 1)))
        idx = ((attr & 0x0F) << 4) | ((ps >> (12 - (p & 3) * 4)) & 0x0F)

    else:
        bpp = 1 << vid.bpp_log
        ppw = 16 // bpp
        ra = vid.base + vlog * vid.stride
        sx = rel + vid.scrl_x
        ps = _bswap(_words_v(vid.vram,
                             ra[:, None] + (sx // ppw)[None, :] * 2))
        k = (sx % ppw)[None, :]
        idx = (ps >> (16 - bpp - k * bpp)) & ((1 << bpp) - 1)

    idx = np.broadcast_to(idx, (V_VIS, H_VIS)).copy()
    if vid.spr_en:
        idx = _sprites_v(vid, idx, np)

    pal = np.array(vid.pal, dtype=np.int64)
    return np.where(vis, pal[idx & 0xFF], vid.pal[vid.border])


def render_fast(machine):
    """`render()`'s answer, as a flat list, without the twenty minutes."""
    return render_np(machine).reshape(-1).tolist()


def save_png(frame, path):
    """A minimal truecolour PNG, the same way sim/test_video.py writes one."""
    raw = bytearray()
    for row in range(V_VIS):
        raw.append(0)
        for v in frame[row * H_VIS:(row + 1) * H_VIS]:
            raw += bytes((((v >> 8) & 0xF) * 17, ((v >> 4) & 0xF) * 17,
                          (v & 0xF) * 17))

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, 'wb') as fh:
        fh.write(b'\x89PNG\r\n\x1a\n')
        fh.write(chunk(b'IHDR', struct.pack('>IIBBBBB', H_VIS, V_VIS,
                                            8, 2, 0, 0, 0)))
        fh.write(chunk(b'IDAT', zlib.compress(bytes(raw), 9)))
        fh.write(chunk(b'IEND', b''))
    return path


def as_text(machine, cols=80, rows=30):
    """The text screen as characters, for a terminal or a test.

    Reads the map the way the fetch engine does, wrap included, so it
    follows VID_BASE when software scrolls by moving the origin.
    """
    vid = machine.video
    out = []
    for r in range(rows):
        ra = _row_addr(vid, r)
        line = ''.join(chr(machine.bus.mem[(ra + c * 2) & 0xFFFF])
                       for c in range(cols))
        out.append(line.rstrip())
    return out


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cool8vm

    m = cool8vm.boot()
    cool8vm.converse(m)
    for line in as_text(m):
        print(line)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '..', 'build', 'vm-screen.png')
    print('\n' + save_png(render(m), os.path.normpath(out)))
