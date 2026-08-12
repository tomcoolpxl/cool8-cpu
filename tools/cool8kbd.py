#!/usr/bin/env python3
"""The machine's keymap, read out of sw/keymap.asm, and the encoder
that turns text into the make and break codes a keyboard sends.

**Read, not restated.** The machine decodes with that table; a copy
here would only ever agree with itself, and the one thing this is for
is catching the day they disagree. sim/test_lex.py reads sw/toktab.asm
for the same reason.

Lifted out of the Python machine when it retired (D57): the keymap
is single-sourced for every client — the session machine's `key()`,
the emulator launcher's layout file — and none of them should carry a
machine to get it.
"""

import os
import re


def _operands(line):
    """The values on one `.byte` line, honouring quotes.

    One pass, because both the separator and the comment marker occur as
    characters in the table itself: `.byte 0,',','k'` rules out
    `split(",")` and `.byte 0,'.','/','l',';','p'` rules out cutting the
    comment off first.
    """
    line = line.strip()[len(".byte"):]
    out, cur, q = [], "", False
    for c in line:
        if c == "'":
            q = not q
            cur += c
        elif q:
            cur += c
        elif c == ";":
            break
        elif c == ",":
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        out.append(cur.strip())
    return out


def _value(tok):
    if tok.startswith("'"):
        return ord(tok[1])
    if tok.startswith("$"):
        return int(tok[1:], 16)
    return int(tok, 0)


def _table(text, label):
    """Every `.byte` value under `label`, up to the blank line after it."""
    body = text.split(label + ":", 1)[1]
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith(".byte"):
            if line.startswith(";") or not line:
                continue
            break
        out += [_value(t) for t in _operands(line)]
    return out


def kbd_tables(_cache={}):
    """keymap, shiftmap and extmap, read out of sw/keymap.asm.

    Returns character -> (scancode, shifted) and name -> scancode, the
    K_* names coming from sw/basic.bas so even the ordering is the
    machine's rather than a guess about it.
    """
    if _cache:
        return _cache["chars"], _cache["named"]

    here = os.path.dirname(os.path.abspath(__file__))
    sw = os.path.join(os.path.dirname(here), "sw")
    with open(os.path.join(sw, "keymap.asm"), encoding="utf-8") as fh:
        text = fh.read()

    keymap = _table(text, "keymap")
    shiftmap = _table(text, "shiftmap")
    extmap = _table(text, "extmap")

    # Ascending, so the main row wins over the keypad: '1' is $16 before
    # it is $69, and a test that meant to press the 1 key means that one.
    chars = {}
    for code, ch in enumerate(keymap):
        if ch:
            chars.setdefault(chr(ch), (code, False))
    for i in range(0, len(shiftmap) - 1, 2):
        plain, shifted = chr(shiftmap[i]), chr(shiftmap[i + 1])
        if plain in chars:
            chars.setdefault(shifted, (chars[plain][0], True))
    for ch in "abcdefghijklmnopqrstuvwxyz":
        if ch in chars:
            chars.setdefault(ch.upper(), (chars[ch][0], True))
    if "\r" in chars:
        chars.setdefault("\n", chars["\r"])

    # The K_* constants, so `K_UP` here is the K_UP the editor compares
    # against rather than a number that happens to match today.
    #
    # **They are equates in sw/*.asm now**, not `CONST`s in sw/basic.bas,
    # which [D68] deleted along with the compiled editor. Only the named
    # keys are wanted -- they live above the byte range at 256 and up, so
    # the value is the filter and no list of names has to be kept here.
    # `K_UPK` and friends carry a trailing K in sw/main.asm to stay clear
    # of the token equates; both spellings are registered, since a
    # caller naturally writes `K_UP`.
    consts = {}
    for base_name in ("input.asm", "main.asm"):
        path = os.path.join(sw, base_name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for n, v in re.findall(r"^(K_\w+)\s*=\s*(\d+)", fh.read(), re.M):
                if int(v) < 256 or n == "K_NAMED":
                    continue
                consts.setdefault(n, v)
                if n.endswith("K"):
                    consts.setdefault(n[:-1], v)
    base = min(int(v) for v in consts.values()) if consts else 256
    named = {}
    for name, v in consts.items():
        want = 0x80 + (int(v) - base)
        for i in range(0, len(extmap) - 1, 2):
            if extmap[i + 1] == want:
                named[name] = extmap[i]
    _cache["chars"], _cache["named"] = chars, named
    return chars, named


def encode_keys(text):
    """Characters and K_* names to the make and break codes a keyboard
    sends."""
    chars, named = kbd_tables()
    if isinstance(text, str):
        text = list(text)
    out = bytearray()
    for item in text:
        if item in named:
            out += bytes((0xE0, named[item], 0xE0, 0xF0, named[item]))
            continue
        if item not in chars:
            raise KeyError("no key on this keyboard sends %r" % (item,))
        code, shifted = chars[item]
        if shifted:
            out += bytes((0x12,))
        out += bytes((code, 0xF0, code))
        if shifted:
            out += bytes((0xF0, 0x12))
    return bytes(out)
