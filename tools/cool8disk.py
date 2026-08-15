#!/usr/bin/env python3
"""COOL8 disk volumes, from the PC side.

    python tools/cool8disk.py format  disk.img 0 --label GAMES
    python tools/cool8disk.py add     disk.img 0 hello.bin
    python tools/cool8disk.py dir     disk.img 0
    python tools/cool8disk.py get     disk.img 0 HELLO.BIN out.bin
    python tools/cool8disk.py del     disk.img 0 HELLO.BIN
    python tools/cool8disk.py compact disk.img 0

`disk.img` is an image of the machine's 8 MB flash. Write it to a board
with `icesprog -w disk.img`, or hand it to `tools/cool8run.py --flash
disk.img` and the emulated machine sees the same files.

## The format, and why it is this one

Sixteen volumes of 448 KB, mounted by number, filling the 7 MB above the
`$100000` hardware floor exactly. Each is one 4 KB directory sector, then
110 sectors of data, then one 4 KB sector the machine keeps for itself.

**That last sector is what makes COMPACT possible on a machine with no
spare RAM.** Compaction has to erase a 4 KB sector before rewriting it,
which destroys anything else living there, so the contents have to be
somewhere else first -- and "somewhere else" cannot be main RAM, which
holds the user's program, nor video RAM, which holds their sprites and
the compiler image. So it is on the disk: gather a sector's worth into
the scratch, erase the destination, copy back. Slow, and it costs 4 KB
of every volume.

**It is built around what NOR flash can actually do**, which is: erase a
4 KB sector to all-ones, and thereafter only ever clear bits.

  - **Creating a file** writes an entry that is still `$FF`. No erase, no
    read-modify-write, and **no 4 KB RAM buffer anywhere** — which is the
    whole reason this is not FAT.
  - **Deleting one** clears its status byte to `$00`. One byte
    programmed, nothing erased.
  - **Free space is the tail.** Files are appended; there is no
    allocation bitmap and no free list.
  - **The free pointer is not stored**, because a value that only
    increases cannot be rewritten in place. It is derived at mount by
    scanning the directory for `max(start + length)`.
  - **An erased volume is an empty volume.** Format is erase, and there
    is no superblock to be missing or wrong.

Compaction is the only operation that erases, and it is explicit.

## The entry

| Bytes | Field |
|---|---|
| 0–10 | name, 8.3, space padded, upper case |
| 11 | status: `$FF` free, `$00` deleted, `$80` volume label, else type |
| 12–13 | start, in 256-byte pages from the volume base |
| 14–15 | length in bytes |

Sixteen bytes, 256 entries, one sector. A file is at most 64 KB, which
is the machine's whole address space.
"""

import argparse
import os
import sys

FLOOR = 0x100000
VOL_SIZE = 0x70000              # 448 KB
N_VOLS = 16
IMG_SIZE = 8 << 20
DIR_SIZE = 4096
ENTRY = 16
N_ENTRIES = DIR_SIZE // ENTRY
DATA_START = DIR_SIZE           # page 16
SECTOR = 4096
DATA_END = VOL_SIZE - SECTOR    # the last sector is COMPACT's scratch

ST_FREE = 0xFF
ST_DELETED = 0x00
ST_LABEL = 0x80
ST_FILE = 0x01

assert FLOOR + N_VOLS * VOL_SIZE == IMG_SIZE


def vol_base(n):
    if not 0 <= n < N_VOLS:
        sys.exit(f"drive {n}: there are {N_VOLS}, numbered 0 to {N_VOLS-1}")
    return FLOOR + n * VOL_SIZE


def pad_name(s):
    """'hello.bin' -> b'HELLO   BIN'. The 8.3 the era used."""
    s = os.path.basename(s).upper()
    stem, _, ext = s.partition('.')
    if len(stem) > 8 or len(ext) > 3:
        sys.exit(f"{s}: names are 8.3")
    return (stem.ljust(8) + ext.ljust(3)).encode('ascii')


def show_name(b):
    return (b[:8].decode('ascii').rstrip() + '.' +
            b[8:11].decode('ascii').rstrip()).rstrip('.')


class Image:
    def __init__(self, path, create=False):
        self.path = path
        if os.path.exists(path):
            with open(path, 'rb') as fh:
                self.data = bytearray(fh.read())
            if len(self.data) < IMG_SIZE:
                self.data += b'\xFF' * (IMG_SIZE - len(self.data))
        elif create:
            self.data = bytearray(b'\xFF' * IMG_SIZE)
        else:
            sys.exit(f"{path}: not found (use `format` to make one)")

    def save(self):
        with open(self.path, 'wb') as fh:
            fh.write(self.data)

    # ---- the flash's own rules, enforced here so the tool cannot do
    #      anything the machine could not do to the same image
    def program(self, addr, blob):
        if addr < FLOOR:
            sys.exit(f"refused: ${addr:06X} is below the ${FLOOR:06X} floor")
        for i, b in enumerate(blob):
            self.data[addr + i] &= b        # a program can only clear bits

    def erase(self, addr):
        if addr < FLOOR:
            sys.exit(f"refused: ${addr:06X} is below the ${FLOOR:06X} floor")
        base = addr & ~(SECTOR - 1)
        self.data[base:base + SECTOR] = b'\xFF' * SECTOR


class Volume:
    def __init__(self, img, n):
        self.img = img
        self.n = n
        self.base = vol_base(n)

    def entry(self, i):
        a = self.base + i * ENTRY
        e = self.img.data[a:a + ENTRY]
        return {'i': i, 'name': bytes(e[0:11]), 'status': e[11],
                'page': e[12] | (e[13] << 8),
                'length': e[14] | (e[15] << 8)}

    def entries(self):
        return [self.entry(i) for i in range(N_ENTRIES)]

    def files(self):
        return [e for e in self.entries()
                if e['status'] not in (ST_FREE, ST_DELETED, ST_LABEL)]

    def label(self):
        e = self.entry(0)
        return show_name(e['name']) if e['status'] == ST_LABEL else ''

    def free_offset(self):
        """Derived, never stored — the same scan the machine does."""
        top = DATA_START
        for e in self.entries():
            if e['status'] in (ST_FREE, ST_DELETED, ST_LABEL):
                continue
            end = e['page'] * 256 + e['length']
            top = max(top, end)
        return (top + 255) & ~255           # files start on a page

    def free_entry(self):
        for e in self.entries():
            if e['status'] == ST_FREE:
                return e['i']
        return None

    def find(self, name):
        want = pad_name(name)
        for e in self.files():
            if e['name'] == want:
                return e
        return None

    # ------------------------------------------------------ operations

    def format(self, label=None):
        for off in range(0, VOL_SIZE, SECTOR):
            self.img.erase(self.base + off)
        if label:
            e = bytearray(b'\xFF' * ENTRY)
            e[0:11] = pad_name(label if '.' in label else label + '.')
            e[11] = ST_LABEL
            e[12:16] = b'\x00\x00\x00\x00'
            self.img.program(self.base, bytes(e))

    def add(self, path, name=None, type_=ST_FILE):
        with open(path, 'rb') as fh:
            blob = fh.read()
        if len(blob) > 0xFFFF:
            sys.exit(f"{path}: {len(blob)} bytes, the limit is 65535")
        name = pad_name(name or path)
        if self.find(show_name(name)):
            sys.exit(f"{show_name(name)}: already on drive {self.n}")
        i = self.free_entry()
        if i is None:
            sys.exit(f"drive {self.n}: all {N_ENTRIES} entries used")
        off = self.free_offset()
        if off + len(blob) > DATA_END:
            sys.exit(f"drive {self.n}: {DATA_END - off} bytes free, "
                     f"{len(blob)} wanted")
        self.img.program(self.base + off, blob)
        e = bytearray(name)
        e.append(type_)
        e += bytes((off // 256 & 0xFF, (off // 256) >> 8,
                    len(blob) & 0xFF, len(blob) >> 8))
        self.img.program(self.base + i * ENTRY, bytes(e))
        return show_name(name), off, len(blob)

    def get(self, name):
        e = self.find(name)
        if not e:
            sys.exit(f"{name}: not on drive {self.n}")
        a = self.base + e['page'] * 256
        return bytes(self.img.data[a:a + e['length']])

    def delete(self, name):
        e = self.find(name)
        if not e:
            sys.exit(f"{name}: not on drive {self.n}")
        # A program can only clear bits, so $FF -> $00 needs no erase.
        self.img.program(self.base + e['i'] * ENTRY + 11, b'\x00')
        return e

    def compact(self):
        """The only operation that erases. Rewrites the volume with the
        deleted files gone."""
        live = [(e, self.get(show_name(e['name']))) for e in self.files()]
        lab = self.label()
        self.format(lab or None)
        off = DATA_START
        for i, (e, blob) in enumerate(live):
            self.img.program(self.base + off, blob)
            ent = bytearray(e['name'])
            ent.append(e['status'])
            ent += bytes((off // 256 & 0xFF, (off // 256) >> 8,
                          len(blob) & 0xFF, len(blob) >> 8))
            self.img.program(self.base + (i + 1) * ENTRY, bytes(ent))
            off = (off + len(blob) + 255) & ~255
        return len(live)


# ---------------------------------------------------------------- layout
#
# **Which volume is what, in one place.** The boot ROM walks volume 0 for
# BOOT.BIN and cannot be told otherwise, so 0 is the system's; BASIC
# comes up on 1 (`fsc_init`) so an unqualified SAVE never lands beside
# the file the machine boots from; 13 is the demo disc
# ([docs/14-demos.md](../docs/14-demos.md)).
#
# It lives here because two builders need it -- `tools/flash.py` for the
# board's disk and `tools/mkdemos.py` for the demo disc -- and a layout
# copied into both is a layout that drifts. `poe disk` used to format
# volume 0 alone, which was invisible until BASIC started on 1 and found
# nothing there.

BOOT_VOL = 0                    # the ROM's; BOOT.BIN lives here
USER_VOL = 1                    # where a cold machine comes up
DEMO_VOL = 13                   # the demo disc


def labels():
    """The label for every volume, by number."""
    return {n: "SYSTEM" if n == BOOT_VOL else
               "DEMOS" if n == DEMO_VOL else "COOL8"
            for n in range(N_VOLS)}


def make_image(path, bootbin=None):
    """A fresh image with **every** volume formatted, BOOT.BIN on 0.

    Every volume, because BASIC mounts USER_VOL at startup and an
    unformatted one has no directory to read.
    """
    if os.path.exists(path):
        os.remove(path)
    img = Image(path, create=True)
    for n, label in labels().items():
        Volume(img, n).format(label)
    if bootbin:
        Volume(img, BOOT_VOL).add(bootbin, "BOOT.BIN")
    img.save()
    return img


def cmd_format(a):
    img = Image(a.image, create=True)
    Volume(img, a.drive).format(a.label)
    img.save()
    print(f"drive {a.drive}: formatted, {DATA_END - DATA_START:,} bytes free"
          + (f", labelled {a.label.upper()}" if a.label else ""))


def cmd_dir(a):
    v = Volume(Image(a.image), a.drive)
    lab = v.label()
    print(f"drive {a.drive}:{'  ' + lab if lab else ''}")
    n = 0
    for e in v.files():
        print(f"  {show_name(e['name']):<13} {e['length']:6,} bytes   "
              f"@ ${v.base + e['page']*256:06X}")
        n += 1
    free = DATA_END - v.free_offset()
    dead = sum(1 for e in v.entries() if e['status'] == ST_DELETED)
    print(f"  {n} file{'s' if n != 1 else ''}, {free:,} bytes free"
          + (f", {dead} deleted (compact to reclaim)" if dead else ""))


def cmd_add(a):
    img = Image(a.image)
    name, off, n = Volume(img, a.drive).add(a.file, a.name)
    img.save()
    print(f"drive {a.drive}: {name}, {n:,} bytes at +${off:05X}")


def cmd_get(a):
    blob = Volume(Image(a.image), a.drive).get(a.name)
    with open(a.out, 'wb') as fh:
        fh.write(blob)
    print(f"{a.name}: {len(blob):,} bytes -> {a.out}")


def cmd_del(a):
    img = Image(a.image)
    Volume(img, a.drive).delete(a.name)
    img.save()
    print(f"drive {a.drive}: {a.name} deleted (compact to reclaim the space)")


def cmd_compact(a):
    img = Image(a.image)
    before = Volume(img, a.drive).free_offset()
    n = Volume(img, a.drive).compact()
    after = Volume(img, a.drive).free_offset()
    img.save()
    print(f"drive {a.drive}: {n} file{'s' if n != 1 else ''} kept, "
          f"{before - after:,} bytes reclaimed")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)

    def drive(p):
        p.add_argument('image')
        p.add_argument('drive', type=int)
        return p

    p = drive(sub.add_parser('format', help='erase a volume'))
    p.add_argument('--label')
    p.set_defaults(fn=cmd_format)

    drive(sub.add_parser('dir', help='list')).set_defaults(fn=cmd_dir)

    p = drive(sub.add_parser('add', help='put a file in'))
    p.add_argument('file')
    p.add_argument('--name', help='the 8.3 name on the volume')
    p.set_defaults(fn=cmd_add)

    p = drive(sub.add_parser('get', help='take a file out'))
    p.add_argument('name')
    p.add_argument('out')
    p.set_defaults(fn=cmd_get)

    p = drive(sub.add_parser('del', help='mark deleted'))
    p.add_argument('name')
    p.set_defaults(fn=cmd_del)

    drive(sub.add_parser('compact', help='reclaim deleted space')
          ).set_defaults(fn=cmd_compact)

    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
