#!/usr/bin/env python3
"""Bad Apple for COOL8 -- encoder, decoder, stub, and the disc plan.

    python tools/mkbadapple.py badapple.mp4      # the real thing
    python tools/mkbadapple.py --selftest 96     # a synthetic clip

**The shape of the port.** Every 8-bit Bad Apple is a fight against
storage; COOL8's is not -- flash is 8 MB and `FLS_DATA` auto-advances,
so streaming is built into the hardware and plain delta-RLE at 256x192
is comfortable where the C64 needed vector quantisation. The fight
here is only decode speed, and 8.375 MHz against the C64's 1 settles
it. Chosen: **256x192, 15 fps, silent** (the soundtrack is a later,
separate step).

**The stream.** Video frames become mode 5 byte planes (4 bpp, two
pixels a byte, values $00/$0F/$F0/$FF), each frame delta-encoded
against the frame *two* back -- because pages alternate under the D92
double buffer, so a page's previous content is two frames old. Tokens,
decoder-simple on purpose:

    $00       end of frame: flip VID_DBASE_H to the page just written
    $01-$7F   run: next byte is the value, written n times through
              VRAM_DATA's auto-increment
    $80-$FF   skip: advance VRAM_ADDR by (token - 127)

Frames 0 and 1 are encoded full (no skips), so no clear is needed.

**The disc plan: dedicated drives, 12 downward.** A file is at most
65,535 bytes (the catalogue's 16-bit length), so the stream ships as
BA###.DAT chunks split at frame boundaries, packed onto drives 12, 11,
10... in order. Files in a volume are contiguous from a deterministic
offset, so this tool *predicts* each chunk's absolute flash address
and bakes the table into the stub; `tools/mkdemos.py` re-adds the
chunks on every disc build and asserts the prediction held. The
decoder itself is ~70 bytes of machine code, assembled here through
the harness with register addresses stamped from `tools/ioregs.py`
(a literal in a generator is the D67 trap), POKEd to $9000 by the
stub, and driven one frame per `SYS` from a VSYNC loop -- BASIC keeps
the tempo and the exit key, the machine code moves the bytes.
"""
import io
import json
import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cool8disk as disk                                   # noqa: E402
import ioregs                                              # noqa: E402

W, H = 256, 192
PLANE = W // 2 * H            # 24,576 bytes, one mode 5 page
FPS = 15
ORG = 0x9000                  # the decoder, inside user RAM
CHUNK_MAX = 0xFFFF            # the catalogue's 16-bit file length
DRIVES = list(range(12, 0, -1))   # dedicated drives, 12 downward
OUT = os.path.join(ROOT, "demos", "bapple")


def _adr(name):
    return ioregs.addr_of(name)


def decoder_asm():
    """The frame decoder, register addresses stamped from the RTL."""
    return """        .org  ${org:04X}
; Bad Apple -- decode one delta-RLE frame per SYS call. Tokens from
; FLS_DATA (auto-advancing): $00 end of frame, $01-$7F a run of the
; next byte, $80-$FF a skip of (token - 127) positions. The frame
; lands on the hidden page; the flip is VID_DBASE_H (D92).
badapple:
        MOV  R1,#0
        ST   [${val:04X}],R1
        LD   R0,[page]
        ST   [${vah:04X}],R0
.tok:   LD   R0,[${fls:04X}]
        OR   R0,R0
        BEQ  .fin
        CMP  R0,#$80
        BHS  .skip
        LD   R1,[${fls:04X}]
.run:   ST   [${vda:04X}],R1
        SUB  R0,#1
        BNE  .run
        BRA  .tok
.skip:  SUB  R0,#127
        LD   R2,[${val:04X}]
        ADD  R2,R0
        ST   [${val:04X}],R2
        BLO  .tok
        LD   R2,[${vah:04X}]
        ADD  R2,#1
        ST   [${vah:04X}],R2
        BRA  .tok
.fin:   LD   R0,[page]
        ST   [${dbh:04X}],R0
        XOR  R0,#$60
        ST   [page],R0
        RET
page:   .byte $00
""".replace("{org:04X}", "%04X" % ORG) \
   .replace("{val:04X}", "%04X" % _adr("VRAM_ADDR_L")) \
   .replace("{vah:04X}", "%04X" % _adr("VRAM_ADDR_H")) \
   .replace("{vda:04X}", "%04X" % _adr("VRAM_DATA")) \
   .replace("{fls:04X}", "%04X" % _adr("FLS_DATA")) \
   .replace("{dbh:04X}", "%04X" % _adr("VID_DBASE_H"))


def build_decoder():
    import harness as HN
    code, syms = HN.assemble_text(decoder_asm(), name="bapple_ml")
    assert syms["badapple"] == ORG
    assert len(code) < 128, len(code)
    return bytes(code)


# ------------------------------------------------------------- frames

def plane(bits):
    """256x192 truthy rows -> one mode 5 byte plane, white on black."""
    out = bytearray(PLANE)
    i = 0
    for y in range(H):
        row = bits[y]
        for x in range(0, W, 2):
            out[i] = ((0xF0 if row[x] else 0)
                      | (0x0F if row[x + 1] else 0))
            i += 1
    return bytes(out)


def encode(planes):
    """Per-frame token blobs: delta against two frames back."""
    blobs = []
    for i, cur in enumerate(planes):
        prev = planes[i - 2] if i >= 2 else None
        t = bytearray()
        j = 0
        while j < PLANE:
            if prev is not None and cur[j] == prev[j]:
                n = 0
                while (j < PLANE and n < 128
                       and cur[j] == prev[j]):
                    j += 1
                    n += 1
                t.append(0x80 + n - 1)
            else:
                v = cur[j]
                n = 0
                while (j < PLANE and n < 127 and cur[j] == v
                       and (prev is None or cur[j] != prev[j]
                            or n == 0)):
                    j += 1
                    n += 1
                t.append(n)
                t.append(v)
        t.append(0)
        blobs.append(bytes(t))
    return blobs


def decode(stream, nframes):
    """The reference decoder, for the gate: yields both pages after
    each frame, exactly as the machine code leaves them."""
    pages = [bytearray(PLANE), bytearray(PLANE)]
    it = iter(stream)
    out = []
    for f in range(nframes):
        pg, a = pages[f & 1], 0
        while True:
            tok = next(it)
            if tok == 0:
                break
            if tok >= 0x80:
                a += tok - 127
            else:
                v = next(it)
                for _ in range(tok):
                    pg[a] = v
                    a += 1
        out.append((bytes(pages[0]), bytes(pages[1])))
    return out


def synth_frames(n):
    """A bouncing filled square -- enough motion to exercise runs,
    skips, page parity and the flip."""
    frames = []
    x, y, dx, dy, s = 10, 10, 3, 2, 48
    for _ in range(n):
        rows = [[False] * W for _ in range(H)]
        for yy in range(y, y + s):
            r = rows[yy]
            for xx in range(x, x + s):
                r[xx] = True
        frames.append(rows)
        x += dx
        y += dy
        if x < 0 or x + s >= W:
            dx = -dx
            x += 2 * dx
        if y < 0 or y + s >= H:
            dy = -dy
            y += 2 * dy
    return frames


def mp4_frames(path):
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not on PATH; it does the frame extraction")
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path,
         "-vf", "fps=%d,scale=%d:%d" % (FPS, W, H),
         "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE, check=True)
    raw = p.stdout
    n = len(raw) // (W * H)
    frames = []
    for f in range(n):
        base = f * W * H
        frames.append([[raw[base + y * W + x] >= 128 for x in range(W)]
                       for y in range(H)])
    return frames


# ---------------------------------------------------------- the plan

def chunk(blobs):
    """Chunks of whole frames, each within the catalogue's 16 bits."""
    chunks, cur, frames = [], bytearray(), 0
    for b in blobs:
        assert len(b) <= CHUNK_MAX, "one frame larger than a file"
        if len(cur) + len(b) > CHUNK_MAX:
            chunks.append((bytes(cur), frames))
            cur, frames = bytearray(), 0
        cur += b
        frames += 1
    if cur:
        chunks.append((bytes(cur), frames))
    return chunks


def plan(chunks):
    """Chunks onto the dedicated drives, addresses predicted the way
    Volume.add lays files out: contiguous from DATA_START."""
    cap = disk.DATA_END - disk.DATA_START
    man, di, off = [], 0, disk.DATA_START
    for k, (blob, frames) in enumerate(chunks):
        if off + len(blob) > disk.DATA_END:
            di += 1
            off = disk.DATA_START
        if di >= len(DRIVES):
            sys.exit("the stream outgrew the dedicated drives")
        drive = DRIVES[di]
        addr = disk.vol_base(drive) + off
        man.append({"drive": drive, "name": "BA%03d.DAT" % k,
                    "addr": addr, "frames": frames, "size": len(blob)})
        off += len(blob)
    assert cap > 0
    return man


def emit(outdir, chunks, man, ml):
    os.makedirs(outdir, exist_ok=True)
    for m, (blob, _) in zip(man, chunks):
        with open(os.path.join(outdir, m["name"]), "wb") as fh:
            fh.write(blob)
    with open(os.path.join(outdir, "manifest.json"), "w") as fh:
        json.dump(man, fh, indent=1)

    def data(vals, start):
        lines, n, i = [], start, 0
        while i < len(vals):
            ch = vals[i:i + 14]
            while len(("%d DATA " % n) + ",".join(map(str, ch))) > 79:
                ch = ch[:-1]
            lines.append("%d DATA %s" % (n, ",".join(map(str, ch))))
            i += len(ch)
            n += 1
        return lines

    table = []
    for m in man:
        a = m["addr"]
        table += [a & 0xFF, (a >> 8) & 0xFF, a >> 16, m["frames"]]
    body = """1 GOTO 100
10 FOR C=1 TO %d
11 READ D,E,G,N
12 POKE $FF8C,0:POKE $FF88,D:POKE $FF89,E:POKE $FF8A,G:POKE $FF8C,1
13 FOR F=1 TO N
14 VSYNC:VSYNC:VSYNC:VSYNC
15 SYS %d
16 T=INKEY:IF T>0 THEN GOTO 20
17 NEXT F
18 NEXT C
20 POKE $FF8C,0
21 MODE 0
22 CURSOR 1:END
100 MODE 5
101 CURSOR 0
102 POKE $FF11,$7A:POKE $FF30,$60
103 POKE $FF28,1
104 FOR I=0 TO %d
105 READ N:POKE %d+I,N
106 NEXT I
107 GOTO 10
""" % (len(man), ORG, len(ml) - 1, ORG)
    src = body + "\n".join(data(list(ml), 200) + data(table, 250)) + "\n"
    stub = os.path.join(outdir, "bapple.bas")
    with io.open(stub, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    lines = [l for l in src.split("\n") if l.strip()]
    ns = [int(l.split()[0]) for l in lines]
    assert ns == sorted(ns)
    assert not [n for n, l in zip(ns, lines) if len(l) > 79]
    return stub


def build(frames, outdir=OUT):
    ml = build_decoder()
    planes = [plane(f) for f in frames]
    blobs = encode(planes)
    chunks = chunk(blobs)
    man = plan(chunks)
    stub = emit(outdir, chunks, man, ml)
    total = sum(m["size"] for m in man)
    drives = sorted({m["drive"] for m in man}, reverse=True)
    print("  %d frames -> %s bytes in %d chunks on drives %s"
          % (len(frames), "{:,}".format(total), len(man), drives))
    print("  decoder %d bytes at $%04X; stub %s"
          % (len(ml), ORG, stub))
    return man


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        build(synth_frames(int(sys.argv[2])),
              outdir=sys.argv[3] if len(sys.argv) > 3 else OUT)
    elif len(sys.argv) == 2:
        build(mp4_frames(sys.argv[1]))
    else:
        sys.exit(__doc__.split("\n\n")[0])


if __name__ == "__main__":
    main()
