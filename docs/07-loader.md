# 07 — Loader wire protocol

The protocol spoken over the USB serial port to the hardware loader
described in [04-system.md §4.7](04-system.md#47-loader--fe80).

Deliberately trivial. It runs over USB CDC, which already does CRC and
retransmission at the USB layer, so this does not need to be a robust
link protocol — it needs to be small and simple enough to drive from a
shell script. Built, it is **250 LUT4 and 139 flip-flops**, with the
UART another 141 and 72; the 64 KB address, length and byte counters are
most of it.

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

**Except when the byte that followed was itself `$C8`.** Then only the
first is forwarded and the second stays a candidate, so `$C8 $C8 $8C` is
a data `$C8` followed by a frame, and a run of any length ending `$8C`
is a frame. Forwarding the second `$C8` as well would be a byte the host
never sent, and refusing to reconsider it would swallow a frame the host
is entitled to send; the sniffer must do neither. Simulation found the
RTL doing the first of those two — see
[06-roadmap.md](06-roadmap.md#m4--first-light-on-the-fpga).

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
| `$21` `'!'` | Checksum mismatch or unknown command; the command is not executed (but see `WRITE`) |

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
bus.

**Send `HALT` first.** The grant is per frame, so between one `WRITE`
and the next the CPU resumes — into whatever half of the new program has
landed so far, at whatever PC it was holding. Simulation found this the
first time `cool8_soc_tb` loaded over a program that was still running,
and it produced output from code that was never written as a whole. The
sequence a host sends is `HALT`, then one or more `WRITE`s, then `GO`,
and `GO` releases the halt itself.

`WRITE` reaches the I/O page as well as memory, because the page is
decoded on the bus rather than on the CPU's port. Writing `$FE03` lights
the LED with no CPU and no program at all, which is the first useful
thing to do to a board that has just come up. Writing `$FE80` is the
loader writing its own control register mid-frame; that is allowed and
it is the caller's problem.

`len` may be zero; the frame is then just a bus-grant round trip and a
useful liveness check.

**The payload is written as it arrives**, byte by byte, because the
loader has no frame buffer and is not going to grow one — buffering 64 KB
to make a checksum atomic would cost more than the whole block. So a
`WRITE` that fails its checksum has already modified memory: the `'!'`
means the data was not what was sent, not that nothing happened. The
recovery is to send the same `WRITE` again, which is what a host does
anyway. Nothing else in the protocol touches memory before its checksum
is verified.

### `$02 READ`

The debugger primitive. Reads `len` bytes from `addr` and streams them
back. Because a bus grant preserves all architectural state, a running
program cannot detect this — halt, dump all 64 KB, resume, and it never
knows.

**The address advances between bytes**, so a length-*n* `READ` at an I/O
address reads *n* consecutive registers rather than the same one *n*
times. To pop the receive FIFO repeatedly, send repeated length-1 reads.

### `$03 GO`

The one that actually starts things:

```
1.  Set LDR_CTRL.BOOTRAM so the boot ROM overlay stays suppressed.
2.  Write addr16 to $FFF8/$FFF9 in RAM   (the RESET vector).
3.  Pulse CPU reset, release any standing HALT, release the bus.
```

The CPU is off the bus for all of this because the frame holds the grant,
which is what makes step 2 safe; it does not additionally need to be held
in reset while the vector is written. Reset is one clock wide — the core
resets synchronously — and it lands before the grant is released, so the
CPU's first fetch after it is the vector read. It comes up at `addr` with
the full 64 KB of RAM visible and the boot ROM out of the map entirely.

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
on the test board that asserts `nBUSRQ`, waits for `BUSAK`, then drives
`AD[7:0]` and its own copies of the bus strobes, which are OR/AND-merged
with the CPU's on the board. See
[03-microarchitecture.md §5.3](03-microarchitecture.md#53-merging-a-granted-bus).

The commands above map one-for-one onto what that microcontroller does,
so the same host tool can drive either target with a different transport
underneath. Worth keeping the layering clean in `cool8load.py` for
exactly that reason.
