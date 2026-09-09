#!/usr/bin/env python3
"""tools/ucsd_disk.py -- UCSD Pascal Disk Volume & Text File Utility.

Handles:
1. Encoding text into UCSD Pascal .TEXT format (1024-byte header, DLE compression, 1024-byte pages).
2. Adding/listing/extracting files on UCSD Pascal disk images (.vol).
"""

import os
import struct
import sys

KIND_UNTYPED = 0
KIND_XDATA = 1
KIND_CODE = 2
KIND_TEXT = 3
KIND_INFO = 4
KIND_DATA = 5
KIND_GRAF = 6
KIND_FOTO = 7
KIND_SECURED = 8


def encode_ucsd_text(text: str) -> bytes:
    """Encode standard text into UCSD Pascal .TEXT format."""
    # 1. Two 512-byte blocks (1024 bytes) header
    header = bytearray(1024)
    # Header format: editor environment. Mostly zeros or spaces.

    pages = bytearray()
    cur_page = bytearray()

    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    # If trailing empty line, remove it
    if lines and lines[-1] == '':
        lines.pop()

    for line in lines:
        # Calculate leading spaces
        stripped = line.lstrip(' ')
        num_spaces = len(line) - len(stripped)

        line_bytes = bytearray()
        if num_spaces > 0:
            line_bytes.append(0x10)  # DLE
            line_bytes.append(32 + num_spaces)
        line_bytes.extend(stripped.encode('ascii', errors='replace'))
        line_bytes.append(0x0D)  # CR

        # Check if line fits in current 1024-byte page
        if len(cur_page) + len(line_bytes) > 1024:
            # Pad current page to 1024 with NULs
            cur_page.extend(b'\x00' * (1024 - len(cur_page)))
            pages.extend(cur_page)
            cur_page = bytearray()

        cur_page.extend(line_bytes)

    if len(cur_page) > 0:
        cur_page.extend(b'\x00' * (1024 - len(cur_page)))
        pages.extend(cur_page)

    return bytes(header + pages)


class UCSDVolume:
    def __init__(self, data: bytearray):
        self.data = data
        self.read_dir()

    @classmethod
    def load(cls, path: str):
        with open(path, 'rb') as f:
            return cls(bytearray(f.read()))

    def save(self, path: str):
        with open(path, 'wb') as f:
            f.write(self.data)

    def read_dir(self):
        dir_bytes = self.data[512 * 2 : 512 * 6]
        self.first_block = struct.unpack_from('<H', dir_bytes, 0)[0]
        self.next_block = struct.unpack_from('<H', dir_bytes, 2)[0]
        self.vol_name_len = dir_bytes[6]
        self.vol_name = dir_bytes[7 : 7 + self.vol_name_len].decode('ascii', errors='ignore')
        self.nblocks = struct.unpack_from('<H', dir_bytes, 14)[0]
        self.nfiles = struct.unpack_from('<H', dir_bytes, 16)[0]

        self.files = []
        for i in range(1, self.nfiles + 1):
            entry = dir_bytes[i * 26 : (i + 1) * 26]
            fb, nb, kind = struct.unpack_from('<HHH', entry, 0)
            namelen = entry[6]
            name = entry[7 : 7 + namelen].decode('ascii', errors='ignore')
            last_byte, date = struct.unpack_from('<HH', entry, 22)
            self.files.append({
                'index': i,
                'first_block': fb,
                'next_block': nb,
                'kind': kind,
                'name': name,
                'last_byte': last_byte,
                'date': date,
                'data': self.data[fb * 512 : nb * 512]
            })

    def write_dir(self):
        # Update directory header and entries
        dir_offset = 512 * 2
        struct.pack_into('<HH', self.data, dir_offset, self.first_block, self.next_block)
        self.data[dir_offset + 4] = 0  # kind
        self.data[dir_offset + 5] = 0
        self.data[dir_offset + 6] = len(self.vol_name)
        for i, c in enumerate(self.vol_name[:7]):
            self.data[dir_offset + 7 + i] = ord(c)
        for i in range(len(self.vol_name), 7):
            self.data[dir_offset + 7 + i] = 0

        struct.pack_into('<HH', self.data, dir_offset + 14, self.nblocks, len(self.files))

        for i, f in enumerate(self.files):
            entry_off = dir_offset + (i + 1) * 26
            struct.pack_into('<HHH', self.data, entry_off, f['first_block'], f['next_block'], f['kind'])
            fname = f['name'][:15]
            self.data[entry_off + 6] = len(fname)
            for k, c in enumerate(fname):
                self.data[entry_off + 7 + k] = ord(c)
            for k in range(len(fname), 15):
                self.data[entry_off + 7 + k] = 0
            struct.pack_into('<HH', self.data, entry_off + 22, f['last_byte'], f.get('date', 0))

    def add_file(self, name: str, file_bytes: bytes, kind: int = KIND_TEXT):
        """Add a file to the volume in the free space at the end."""
        # Find highest used block
        last_block = 6
        for f in self.files:
            if f['next_block'] > last_block:
                last_block = f['next_block']

        num_blocks = (len(file_bytes) + 511) // 512
        if last_block + num_blocks > self.nblocks:
            raise ValueError(f"Not enough space on volume for {name} ({num_blocks} blocks needed, {self.nblocks - last_block} free)")

        # Pad file_bytes to 512-byte block boundary
        padded = file_bytes + b'\x00' * (num_blocks * 512 - len(file_bytes))
        fb = last_block
        nb = last_block + num_blocks

        # Write data to volume
        self.data[fb * 512 : nb * 512] = padded

        # Add entry
        self.files.append({
            'index': len(self.files) + 1,
            'first_block': fb,
            'next_block': nb,
            'kind': kind,
            'name': name.upper(),
            'last_byte': 512 if len(file_bytes) % 512 == 0 else len(file_bytes) % 512,
            'date': 0,
            'data': padded
        })
        self.write_dir()
        print(f"Added {name.upper()} ({kind}) to volume {self.vol_name}: blocks {fb}..{nb} ({num_blocks} blocks)")
