# 04 — The Cool8 machine

Everything outside the CPU core. FPGA-only; none of this goes to the
ASIC.

---

## 1. Block diagram

```
        12 MHz ──┬──────────────────────▶ everything below
                 │
                 └── PLL ──▶ 25.125 MHz ──▶ VGA pixels only (M5),
                                             across a scanline buffer
   ┌────────────┐
   │ COOL8 core │            D26: no PLL in the CPU path
   └─────┬──────┘
         │ 16-bit addr, 8-bit data
   ┌─────▼───────────────────────────────────────┐
   │              bus / decoder                   │
   └──┬──────────────┬───────────────┬───────────┬┘
      │              │               │           │
 ┌────▼────┐   ┌─────▼─────┐   ┌─────▼─────┐  ┌──▼─────┐
 │ SPRAM   │   │  I/O page │   │ boot ROM  │  │ video  │
 │ 64 KB   │◀──┤  $FE00    │   │ EBR 4 KB  │  │ engine │
 │ 2 blocks│   └───────────┘   └───────────┘  └───┬────┘
 └────▲────┘                                      │
      └──────────── arbiter, video priority ──────┘
                                                   │
                    ┌──────────────┬───────────────┼──────────┐
                 ┌──▼───┐     ┌────▼────┐    ┌─────▼───┐  ┌───▼───┐
                 │ PS/2 │     │  audio  │    │   VGA   │  │ UART  │
                 └──────┘     └─────────┘    └─────────┘  └───────┘
```

---

## 2. Memory map

| Range | Size | Contents |
|---|---|---|
| `$0000–$FDFF` | 65024 B | RAM |
| `$FE00–$FEFF` | 256 B | I/O page — **always decoded, always wins** |
| `$FF00–$FFFF` | 256 B | RAM (or boot ROM while `ROMEN=1`) |

Plus a reset-time overlay:

| Range | While `ROMEN=1` |
|---|---|
| `$F000–$FDFF`, `$FF00–$FFFF` | Boot ROM (EBR) on **reads** |

**Writes always go to RAM**, even where the ROM overlay is active. That
is what lets the boot code install the interrupt vectors at
`$FFF8–$FFFF` before it switches the overlay off.

The I/O page punches a 256-byte hole in the ROM image at ROM offset
`$0E00–$0EFF`. Don't put code there.

There is no banking in v1. The two unused SPRAM blocks (a further 64 KB)
are reserved for a future banked window carrying tile graphics, sprite
patterns and sample data.

### 2.1 Vectors

| Address | Vector |
|---|---|
| `$FFF8` | `RESET` |
| `$FFFA` | `NMI` |
| `$FFFC` | `IRQ` |
| `$FFFE` | `BRK` |

---

## 3. Boot sequence

The problem: **iCE40 SPRAM has no bitstream initialisation.** All 64 KB
of main RAM is undefined at power-on. The boot ROM lives in EBR, which
*is* initialisable, and bootstraps from there.

```
1.  Power-on / reset
      ROMEN ← 1          boot ROM visible at $F000-$FFFF (reads)
      SP    ← $0000
      PC    ← mem16[$FFF8]    ← comes from ROM

2.  ROM: clear RAM
      Zero $0000-$EFFF so nothing reads back garbage.

3.  ROM: bring up video
      Set VID_MODE, VID_BASE, palette, clear the screen buffer.
      A visible screen this early is the single most useful debug tool
      in the project.

4.  ROM: install vectors
      Write RESET/NMI/IRQ/BRK vectors to $FFF8-$FFFF.
      These land in RAM (writes bypass the overlay).

5.  ROM: copy the monitor
      Copy the monitor/loader image from EBR into RAM.

6.  ROM: ROMEN ← 0
      $F000-$FFFF is now RAM. Jump to the monitor.

7.  Monitor
      Prompt on screen and on the USB serial port.
```

**Steps 1, 2 and 4 exist**, in [`sw/boot.asm`](../sw/boot.asm), built
into the EBR image by `tools/mkrom.py`. Reset to the end of step 4 is
365,036 clocks — 30 ms at 12 MHz, nearly all of it clearing RAM. Steps 3,
5 and 6 need video and a monitor and arrive with them at M5 and M6; until
then the ROM lights the LED blue and halts, and software arrives through
the loader.

Step 4 is the one worth looking at twice: the vectors live at
`$FFF8-$FFFF`, which is inside the ROM's own read window. The write goes
to RAM and a read of the same address still returns the ROM byte. That
asymmetry is the whole reason the overlay is read-only, and without it
there would be no way to install a vector the machine could use after
the ROM went away.

### 3.1 …or not, if the loader says otherwise

The hardware loader (§4.7) can bypass all of that. It holds the CPU off
the bus, writes a program and a reset vector directly into RAM, sets
`BOOTRAM` so the ROM overlay stays out of the way, and pulses CPU reset.
Execution starts at the loaded program with the full 64 KB of RAM
visible and the boot ROM never runs at all.

That path needs no working software on the machine, which is exactly
what you want at M4 when there isn't any.

### 3.2 Where software comes from

| Source | When | Notes |
|---|---|---|
| Hardware loader over USB serial | Development, always | No bitstream rebuild, no working ROM required |
| SPI flash (§4.8) | Finished programs | 7.9 MB free above the bitstream, ~40 ms to load 64 KB |
| Baked into the boot ROM image | Bring-up only | EBR is ~15 KB and the font and ROM already claim 8 |

---

## 4. I/O page

Base `$FE00`. Unlisted addresses read as `$FF` and ignore writes — `$FF`
rather than `$00`, so a register that is not there reads like a bus
nobody is driving instead of like a register holding zero.

The page is decoded on the **bus**, in
[`rtl/soc/cool8_soc.v`](../rtl/soc/cool8_soc.v), ahead of the memory and
whoever the master is. Two consequences worth knowing:

- **The loader reaches it.** A `WRITE` frame to `$FE03` lights the LED
  with no CPU, no program and no working boot ROM. That is deliberate,
  and it is the first useful thing to do to a board that has just come
  up. The other end of it is that a `WRITE` to `$FE80` is the loader
  writing its own control register mid-frame.
- **A read costs the same one wait state a RAM read does.** Answering in
  the address cycle would make the read data a combinational function of
  the address, and the core's address is a combinational function of the
  byte it is fetching — the two close a loop through the bus. So the I/O
  page is read on the launch cycle and answers on the next one, exactly
  as the SPRAM and the boot ROM do.

### 4.1 System — `$FE00`

| Addr | Name | Access | Bits |
|---|---|---|---|
| `$FE00` | `SYSCTRL` | R/W | `0`: `ROMEN` (1 = boot ROM overlay on). Reloads from `~BOOTRAM` on every CPU reset, not from a constant — see §4.7. `7:1` read 0. |
| `$FE01` | `CPUDIV` | — | CPU clock enable divider. **Not implemented**; reads `$FF`. It existed to divide a 25.125 MHz system clock down to something an 8-bit machine plausibly ran at, and [D26](01-decisions.md#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled) put the core on the raw 12 MHz instead. Nothing needs it until there is a reason to run slower than that. |
| `$FE02` | `SYSSTAT` | R | Build identification: a constant carried as a parameter on `cool8_soc`, `$04` at M4. It answers "which bitstream is this board actually running", which is a question that gets asked during bring-up and has no other way to be answered. |
| `$FE03` | `LED` | R/W | `2:0` = R, G, B on the board LED, active high here. The board's own polarity is [cool8_top](../rtl/soc/) and the `.pcf`'s problem, not software's. |

### 4.2 Video — `$FE10`

| Addr | Name | Access | Description |
|---|---|---|---|
| `$FE10` | `VID_MODE` | R/W | `2:0` mode number (§5.2). `7` = display enable. |
| `$FE11` | `VID_BASE` | R/W | High byte of the framebuffer base address. Low byte is always 0, so the base has 256-byte granularity. |
| `$FE12` | `VID_BORDER` | R/W | `3:0` palette index for the border. |
| `$FE13` | `VID_SCRL_X` | R/W | Horizontal fine scroll, 0–7 pixels. |
| `$FE14` | `VID_SCRL_Y` | R/W | Vertical fine scroll, 0–7 lines. |
| `$FE15` | `VID_RASTER` | R | Current scanline, bits 7:0. |
| `$FE16` | `VID_RCMP` | R/W | Raster compare value for the raster interrupt. |
| `$FE17` | `VID_IRQ` | R/W | `0` raster hit (write 1 to clear), `1` vblank. Bits `5:4` are the corresponding enables. |
| `$FE20–$FE3F` | `PALETTE` | R/W | 16 entries × 2 bytes. Even byte = `0000RRRR`, odd byte = `GGGGBBBB`. Matches the 12-bit VGA PMOD exactly. |

### 4.3 Keyboard — `$FE40`

| Addr | Name | Access | Description |
|---|---|---|---|
| `$FE40` | `KBD_STAT` | R | `0` data available, `1` FIFO overflow, `2` parity error, `3` transmit busy |
| `$FE41` | `KBD_DATA` | R | Pop one raw scancode byte from the FIFO. **Read has a side effect.** |
| `$FE42` | `KBD_CTRL` | R/W | `0` FIFO clear, `4` interrupt enable |
| `$FE43` | `KBD_TX` | W | Byte to send to the keyboard (LED/typematic commands) |

The hardware delivers **raw Set 2 scancodes**, including `$E0` prefixes
and `$F0` break codes. Translation to ASCII is software's job — it
belongs in the monitor, not in gates.

FIFO depth 16 bytes.

### 4.4 Audio — `$FE50`

Four channels: three tone, one noise. Registers are direct-mapped — the
SN76489's latch/data protocol is a bus-width artefact we have no reason
to reproduce.

| Addr | Name | Description |
|---|---|---|
| `$FE50` | `CH0_FREQ_L` | Divider bits 7:0 |
| `$FE51` | `CH0_FREQ_H` | Divider bits 11:8 (bits 3:0) |
| `$FE52` | `CH0_VOL` | Attenuation, bits 3:0. `$0` = loudest, `$F` = silent |
| `$FE53` | `CH0_CTRL` | `0` enable, `2:1` duty (00 = 50 %) |
| `$FE54–$FE57` | `CH1_*` | Same layout |
| `$FE58–$FE5B` | `CH2_*` | Same layout |
| `$FE5C` | `NSE_CTRL` | `1:0` shift rate, `2` 0 = white / 1 = periodic, `3` track CH2 frequency, `4` enable |
| `$FE5E` | `NSE_VOL` | Attenuation, bits 3:0 |
| `$FE5F` | `AUD_MASTER` | `3:0` master attenuation |

**Frequency.** Reference clock is 12 MHz ÷ 32 = 375 kHz.

```
f_out = 375000 / (2 × divider)
```

| Divider | Frequency |
|---|---|
| 4095 | 45.8 Hz |
| 852 | 220.1 Hz (A3) |
| 426 | 440.1 Hz (A4) |
| 213 | 880.3 Hz (A5) |
| 4 | 46.9 kHz |

A 12-bit divider at this reference reaches down to 45.8 Hz —
considerably better bass than the real SN76489 managed with 10 bits, and
the same coarsening at high frequencies, which is part of the sound.

The divider off the system clock is ÷32 rather than the ÷64 this section
carried when the system clock was going to be 25.125 MHz
([D26](01-decisions.md#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled)).
**What was worth preserving was the reference, not the ratio**: the
table above is a set of notes that have to stay reachable and in tune,
and 375 kHz lands them within 0.05 % while keeping the bass floor where
it was. Halving the reference instead would have doubled every divider,
run out of resolution an octave sooner at the top, and moved the floor
to 22.9 Hz, which is below hearing and buys nothing.

**Output chain.** Four channels, each a signed ±volume square, summed
into an 8-bit signed sample, then a first-order sigma-delta modulator
running at the full 12 MHz system clock drives one FPGA pin. External RC
low-pass and coupling capacitor produce line level. See
[05-board.md](05-board.md).

### 4.5 Timer — `$FE60`

| Addr | Name | Description |
|---|---|---|
| `$FE60` | `TMR_RELOAD_L` | 16-bit reload value, low |
| `$FE61` | `TMR_RELOAD_H` | high |
| `$FE62` | `TMR_CTRL` | `0` enable, `1` auto-reload, `4` interrupt enable |
| `$FE63` | `TMR_STAT` | `0` expired (write 1 to clear) |

Counts down at 12 MHz ÷ 256 = 46.875 kHz — a 21.3 µs tick, and up to
1.40 s from a 16-bit reload.

Here the ÷256 is kept and the rate simply follows the clock, which is
the opposite of the choice §4.4 makes. Nothing has to land on a specific
frequency: a timer needs enough resolution and enough range, and halving
the rate improves the range and leaves the resolution far finer than any
8-bit machine can act on.

### 4.6 Serial — `$FE70`

Connected to the iCELink USB CDC port. 115200 8N1.

| Addr | Name | Access | Description |
|---|---|---|---|
| `$FE70` | `UART_STAT` | R/W | `0` RX data available, `1` TX has room, `2` RX overrun — **write 1 to bit 2 to acknowledge the overrun**, the same shape `VID_IRQ` and `TMR_STAT` use |
| `$FE71` | `UART_DATA` | R/W | Read pops RX, write pushes TX. **Read has a side effect.** |
| `$FE72` | `UART_DIV_L` | R/W | Baud divider, low byte |
| `$FE73` | `UART_DIV_H` | R/W | Baud divider, high byte |

**Receive is 16 bytes deep** and it is not fed from the wire directly —
every byte goes into the loader first and arrives here only if the
sniffer decided it was not part of a frame (§4.7). Bit 0 says there is
at least one byte; bit 2 says at least one was thrown away because there
was no room, and stays set until acknowledged. The byte lost to an
overrun is the *newest*: a receiver that dropped its oldest byte instead
would turn a diagnosable overrun into scrambled input.

**Transmit is one byte deep, and the wire is shared with the loader.**
Bit 1 says the holding register is free, not that the wire is idle.
Writing while it is occupied loses the byte being written — the one
already accepted always wins, so output cannot be reordered by writing
at the wrong moment. The loader has absolute priority for the wire
itself; a program that transmits flat out delays the loader by at most
one byte and cannot lock it out, which is
[D27](01-decisions.md#d27--the-loader-outranks-the-cpu-on-the-shared-transmitter)
and was not true of the first attempt.

The divider is a register rather than a synthesis constant so the rate
can be changed without rebuilding the bitstream. `div = round(f_clk /
baud) − 1`; at the 12 MHz system clock
([D26](01-decisions.md#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled))
115200 baud is `$0067` (103), which lands on 115385 — 0.16 % out, far
inside the ~2 % a UART tolerates. That is the reset value.

**Changing the divider desynchronises the byte after it**, necessarily:
the new rate takes effect the moment the register lands and the host has
not switched yet. Change the rate, switch, and let the receiver re-sync
on the next start bit; do not expect an acknowledgement of the write
that changed it.

The iCELink debugger presents a USB CDC port whose baud rate is chosen
by the host and bridged to FPGA pins 4 and 6. The FPGA end has no way to
learn what the host picked, so both must be set to agree. 115200 is the
safe default; higher rates are worth testing empirically once the link
works.

### 4.7 Loader — `$FE80`

The hardware loader is a bus master that can write RAM while the CPU is
held off the bus. It is what makes software iteration a one-second
`cat` rather than a bitstream rebuild — see
[D15](01-decisions.md#d15--the-loader-is-hardware-not-a-rom-monitor).

It sits on the UART receive stream and watches for a two-byte magic
prefix. Bytes that are not part of a loader frame pass straight through
to the CPU's `UART_DATA` FIFO, so a running program can use the serial
port normally and still be interrupted and reloaded.

| Addr | Name | Access | Description |
|---|---|---|---|
| `$FE80` | `LDR_CTRL` | R/W | `0` sniffer enable (resets to 1; reads 1 and is not yet implemented — the sniffer is always on). `4` CPU requests a bus grant for itself. `5` `BOOTRAM` — see below. |
| `$FE81` | `LDR_STAT` | R | `0` loader currently owns the bus, `1` last frame had a checksum error, `2` a frame has been received since reset |

`BOOTRAM` is the piece that makes the `GO` command work. Concretely, it
is **`ROMEN`'s reset value**: every CPU reset reloads `ROMEN` from
`~BOOTRAM` rather than from a constant, so with the bit set the machine
wakes with the overlay already gone and fetches its reset vector from
`$FFF8` in RAM — which the loader has just written. Software can still
set `ROMEN` back afterwards; `BOOTRAM` decides again at the next reset.
The bit is owned by the loader and survives a CPU reset; only a full
board reset clears it.

Wire protocol: [07-loader.md](07-loader.md).

### 4.8 SPI flash — `$FE88`

The board's 8 MB configuration flash doubles as mass storage. The iCE40
releases pins 14–17 to user logic once `CDONE` goes high, so a small SPI
master can read the flash at runtime. This is the machine's cartridge
slot and its disk.

| Addr | Name | Access | Description |
|---|---|---|---|
| `$FE88` | `FLS_ADDR_L` | R/W | Flash address bits 7:0 |
| `$FE89` | `FLS_ADDR_M` | R/W | bits 15:8 |
| `$FE8A` | `FLS_ADDR_H` | R/W | bits 23:16 |
| `$FE8B` | `FLS_DATA` | R | Read one byte and advance the address. **Read has a side effect.** |
| `$FE8C` | `FLS_CTRL` | R/W | `0` stream open — write 1 to issue a read at `FLS_ADDR` and hold chip-select low; write 0 to close |
| `$FE8D` | `FLS_STAT` | R | `0` busy, `1` stream open |

Typical use — copy 8 KB from flash offset `$100000` to `$4000`:

```asm
        MOV  R0,#$00
        ST   [$FE88],R0        ; addr = $100000
        ST   [$FE89],R0
        MOV  R0,#$10
        ST   [$FE8A],R0
        MOV  R0,#$01
        ST   [$FE8C],R0        ; open the stream
        ; X = $4000, R2:R3 = 8192
.copy:  LD   R1,[$FE8B]        ; byte, address auto-advances
        ST   [X],R1
        INCW X
        ...
        SUB  R0,R0
        ST   [$FE8C],R0        ; close
```

At a 12.5 MHz SPI clock that is roughly 1.5 MB/s — 64 KB in about 40 ms.

**Reads only.** The SPI master issues opcode `$03` (READ) and nothing
else. It has no write-enable, page-program or erase path *in hardware*,
so no amount of software error can corrupt the bitstream living at
offset 0. See
[D16](01-decisions.md#d16--flash-access-is-read-only-in-hardware).

Writing the flash is a host-side operation:

```bash
icesprog -o 0x100000 -w mygame.bin
```

`icesprog` writes in 4096-byte sectors at any offset. The UP5K bitstream
is about 104 KB, so anything at or above `$100000` (1 MB) has enormous
margin.

> **Do not use `icesprog -e`.** It is a whole-chip erase, not a sector
> erase, and it will take your bitstream with it. Sector writes at an
> offset never need it.

---

## 5. Video

### 5.1 VGA timing

640×480 @ ~60 Hz, both syncs active low.

| | Visible | Front porch | Sync | Back porch | Total |
|---|---|---|---|---|---|
| Horizontal | 640 | 16 | 96 | 48 | 800 |
| Vertical | 480 | 10 | 2 | 33 | 525 |

```
pixel clock  = 25.125 MHz          (PLL from 12 MHz; nominal is 25.175)
frame rate   = 25.125e6 / (800 × 525) = 59.82 Hz
```

0.2 % below nominal. Every VGA monitor accepts this.

### 5.2 Modes

All modes use the 16-entry, 12-bit palette. Logical pixels are doubled
horizontally and vertically where the resolution is below 640×480.

| Mode | Type | Resolution | Colours | Bytes | Notes |
|---|---|---|---|---|---|
| 0 | Text | 80 × 30 chars, 8×16 glyphs | 16 fg / 16 bg per cell | 4800 | Native 640×480, no doubling |
| 1 | Text | 40 × 25 chars, 8×8 glyphs | 16 fg / 16 bg per cell | 2000 | Doubled to 640×400 |
| 2 | Bitmap | 320 × 200 | 4 (palette 0–3) | 16000 | Doubled |
| 3 | Bitmap | 160 × 200 | 16 | 16000 | Doubled ×4 horizontally |
| 4 | Bitmap | 320 × 200 | 16 | 32000 | Doubled. Eats half of RAM. |

Text modes pack each cell as a 16-bit word — character code in the low
byte, attribute (`bg[7:4] fg[3:0]`) in the high byte — so one SPRAM
access fetches a complete cell.

The font is 256 glyphs of 8×16 in EBR (4 KB), on its own port, so glyph
fetches cost no main-memory bandwidth at all. Mode 1 uses the top or
bottom half of each glyph cell.

### 5.3 Bandwidth

The reason there is no banking, no separate video RAM and no display
list:

Counted per scanline, because that is the unit a scanline buffer works
in and [D26](01-decisions.md#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled)
made the buffer the thing that joins the two clock domains:

```
mode 4, the worst case:
  logical pixels per line = 320 at 4 bpp        = 80 SPRAM words
  vertical doubling: one fetch feeds two lines  = 40 words per line
  a line is 31.8 us, and at 12 MHz that is        381 memory cycles
  video share             = 40 / 381            = 10.5 %

mode 0, text:
  80 cells of one 16-bit word, per 16 scanlines = 5 words per line
  video share             = 5 / 381             = 1.3 %
```

**The video engine steals about one memory cycle in ten**, worst case,
and one in eighty in text. A round-robin arbiter with video priority is
sufficient; the CPU sees an occasional `mem_ready` low and does not care.

The pixel clock is still 25.125 MHz and unaffected by any of this — it
has to be, since a monitor is counting. What changed at D26 is that the
*memory* runs at 12 MHz and the two are decoupled, so the fetch rate is
set by how much a scanline needs rather than by the pixel rate.

### 5.4 Not in v1

Sprites, tile layers and raster command lists. The register map leaves
room and the two spare SPRAM blocks exist for exactly this, but the
first target is a text prompt on a real monitor.

When sprites do arrive, the plan is deliberate hardware — a scanline
renderer with a sprite descriptor table, X/Y expansion, priority and
collision — **not** a reproduction of the VIC-II's internal DMA
timing. C64-style multiplexing and raster splits work because we
implement raster interrupts and register writes during active display,
not because we reproduce someone else's chip bugs. See
[00-goals.md](00-goals.md) non-goals.

---

## 6. Interrupt sources

| Source | Vector | Notes |
|---|---|---|
| Raster compare | IRQ | `VID_RCMP` match |
| Vertical blank | IRQ | Start of vblank |
| Timer expiry | IRQ | |
| Keyboard data available | IRQ | |
| UART RX | IRQ | |
| Break button, `SW[0]` | NMI | Debounced, edge-triggered |

`SW[0]` is wired to `NMI` as a **break button**: press it and a hung
program lands in the monitor with all of its state intact, since an NMI
pushes `PC` and `F` and changes nothing else. It is the escape hatch
that makes a machine with no other input device debuggable, and it costs
a debounce counter and an edge detector.

All IRQ sources OR together into the core's single `irq` input. The
handler reads the per-peripheral status registers to find the cause.
This is the smallest arrangement and it is what an 8-bit machine should
do; a priority encoder can come later if the handler's dispatch cost
ever matters.
