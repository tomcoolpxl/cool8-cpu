# 07 — Loader wire protocol

The protocol spoken over the USB serial port to the hardware loader
described in [04-system.md §4.7](04-system.md#47-loader--fe80).

Deliberately trivial. It runs over USB CDC, which already does CRC and
retransmission at the USB layer, so this does not need to be a robust
link protocol — it needs to be small enough to implement in ~60 LUTs
and simple enough to drive from a shell script.

---

## 1. Framing

The loader watches every byte arriving on the UART. Bytes that are not
part of a frame are passed through to the CPU's `UART_DATA` FIFO
unchanged, so a running program can use the serial port and still be
interrupted and reloaded.

A frame starts with the two-byte magic:

```
$C8 $8C
```

`$C8` is not valid ASCII and `$8C` is its bit-reverse; the pair is
vanishingly unlikely in text or in a program's own serial output. If the
sniffer sees `$C8` not followed by `$8C`, it forwards both bytes to the
CPU and resumes watching.

Full frame:

```
 ┌──────┬──────┬─────┬───────────┬──────────┬─────────┬──────┐
 │ $C8  │ $8C  │ cmd │ addr16    │ len16    │ data…   │ csum │
 │      │      │  1B │ lo, hi    │ lo, hi   │ len B   │  1B  │
 └──────┴──────┴─────┴───────────┴──────────┴─────────┴──────┘
```

- All multi-byte fields are little-endian, matching the CPU.
- `addr16` and `len16` are present on every command; unused fields are
  sent as zero.
- `csum` is the 8-bit sum of every byte from `cmd` through the last
  data byte, modulo 256.
- The loader replies with exactly one byte.

| Reply | Meaning |
|---|---|
| `$4B` `'K'` | Accepted |
| `$21` `'!'` | Checksum mismatch or unknown command; frame discarded |

A `READ` reply is the data bytes followed by their checksum, with no
leading `'K'`.

---

## 2. Commands

| cmd | Name | addr16 | len16 | Data | Reply |
|---|---|---|---|---|---|
| `$01` | `WRITE` | destination | byte count | `len` bytes | `'K'` / `'!'` |
| `$02` | `READ` | source | byte count | — | `len` bytes + csum |
| `$03` | `GO` | entry point | 0 | — | `'K'` |
| `$04` | `HALT` | 0 | 0 | — | `'K'` |
| `$05` | `RUN` | 0 | 0 | — | `'K'` |
| `$06` | `RESET` | 0 | 0 | — | `'K'` |
| `$07` | `PING` | 0 | 0 | — | version byte |

### `$01 WRITE`

Requests the bus, writes `len` bytes starting at `addr`, releases the
bus. The CPU keeps running between frames unless it has been halted
first — for loading a program you almost always want `HALT`, then one or
more `WRITE`s, then `GO`.

`len` may be zero; the frame is then just a bus-grant round trip and a
useful liveness check.

### `$02 READ`

The debugger primitive. Reads `len` bytes from `addr` and streams them
back. Because a bus grant preserves all architectural state, a running
program cannot detect this — halt, dump all 64 KB, resume, and it never
knows.

### `$03 GO`

The one that actually starts things:

```
1.  Hold the CPU in reset.
2.  Write addr16 to $FFF8/$FFF9 in RAM   (the RESET vector).
3.  Set LDR_CTRL.BOOTRAM so the boot ROM overlay stays suppressed.
4.  Release reset.
```

The CPU comes up at `addr` with the full 64 KB of RAM visible and the
boot ROM out of the map entirely.

### `$04 HALT` / `$05 RUN`

Assert and release `busrq` persistently. Between them the CPU is frozen
at an instruction boundary with every register intact, and the loader
owns memory.

### `$06 RESET`

Clears `BOOTRAM` and pulses CPU reset, so the machine boots normally
from the boot ROM. The way back to a known-good state.

### `$07 PING`

Returns one byte: the loader version, currently `$01`. Confirms the
right board is on the right COM port before you send it anything.

---

## 3. Host side

The reference host tool is `tools/cool8load.py`. Typical use:

```bash
# load and run
python tools/cool8load.py --port COM3 --load game.bin --at 0x4000 --go 0x4000

# dump memory
python tools/cool8load.py --port COM3 --dump 0x0000 --len 256

# freeze, poke, thaw
python tools/cool8load.py --port COM3 --halt
python tools/cool8load.py --port COM3 --write 0xFE12 --bytes 07
python tools/cool8load.py --port COM3 --run
```

Large `WRITE`s should be split into chunks of a few hundred bytes so a
corrupted frame costs a retry rather than the whole image.

---

## 4. On the ASIC

There is no UART and no loader block on the TinyTapeout part — the SoC
does not exist there, only the core. The equivalent is a microcontroller
on the test board driving `nBUSRQ` and the strobe pass-through pins
directly, as described in
[03-microarchitecture.md §5.3](03-microarchitecture.md#53-strobe-pass-through-during-bus-grant).

The commands above map one-for-one onto what that microcontroller does,
so the same host tool can drive either target with a different transport
underneath. Worth keeping the layering clean in `cool8load.py` for
exactly that reason.
