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

There is no banking, and there will not be. The two remaining SPRAM
blocks are **video RAM** — a separate 64 KB address space reached
through an indirect port, not through the CPU's map. See
[D28](01-decisions.md#d28--video-memory-is-split-the-text-map-in-main-ram-everything-else-in-dedicated-vram)
and §5.2.

That leaves sampled audio with nowhere to live, which is correct: the
audio engine is dividers and an LFSR
([D12](01-decisions.md#d12--audio-sn76489-style-not-sid-style)) and has
no use for memory.

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

Registers with more than a handful of fields sit behind an **indexed
port with auto-increment** — palette, sprite descriptors, blitter
command block, VRAM. That is one idiom, used four times, and it is what
lets a 256-entry palette and a twelve-register blitter share a 48-byte
allocation. It is also the fastest shape for an 8-bit CPU: setup becomes
a straight run of stores with no address recomputation between them.

| Addr | Name | Access | Description |
|---|---|---|---|
| `$FE10` | `VID_MODE` | R/W | `3:0` preset number (§5.3) — writing it loads the registers below. `7` = display enable. |
| `$FE11` | `VID_CTRL` | R/W | `1:0` engine (0 text, 1 tile, 2 bitmap). `3:2` bpp (0=1, 1=2, 2=4, 3=8). `4` horizontal doubling. `5` vertical doubling. |
| `$FE12` | `VID_BASE_L` | R/W | Display base address, low byte |
| `$FE13` | `VID_BASE_H` | R/W | high byte |
| `$FE14` | `VID_STRIDE_L` | R/W | Row pitch in bytes, low. Text map stride, tile map width, or bitmap row pitch — see [D30](01-decisions.md#d30--the-text-map-stride-is-a-register-and-the-canonical-map-is-128x32) |
| `$FE15` | `VID_STRIDE_H` | R/W | high |
| `$FE16` | `VID_SCRL_X_L` | R/W | Horizontal scroll, low |
| `$FE17` | `VID_SCRL_X_H` | R/W | `1:0` high. 0–1023 |
| `$FE18` | `VID_SCRL_Y_L` | R/W | Vertical scroll, low |
| `$FE19` | `VID_SCRL_Y_H` | R/W | `1:0` high |
| `$FE1A` | `VID_BORDER` | R/W | Border colour, a full 8-bit palette index — so the border and the background can be exactly the same colour |
| `$FE1B` | `VID_RASTER` | R | Current scanline, bits 7:0 |
| `$FE1C` | `VID_RCMP` | R/W | Raster compare value |
| `$FE1D` | `VID_IRQ` | R/W | `0` raster hit (write 1 to clear), `1` vblank. `5:4` enables |
| `$FE1E` | `PAL_IDX` | R/W | Palette byte index, 0–511. Two bytes per entry |
| `$FE1F` | `PAL_DATA` | R/W | Even byte `0000RRRR`, odd byte `GGGGBBBB`. **Auto-increments `PAL_IDX`.** Matches the 12-bit VGA PMOD exactly |
| `$FE20` | `PAT_BASE_L` | R/W | Glyph/tile pattern base in VRAM. Repointing this swaps a whole tile set in one write |
| `$FE21` | `PAT_BASE_H` | R/W | |
| `$FE22` | `CUR_X` | R/W | Text cursor column |
| `$FE23` | `CUR_Y` | R/W | Text cursor row |
| `$FE24` | `CUR_CTRL` | R/W | `0` enable, `2:1` style (block/underline/bar/inverse), `4:3` blink rate. Writing `CUR_X` or `CUR_Y` resets the blink phase |
| `$FE25` | `CUR_LINES` | R/W | `3:0` first scanline, `7:4` last — an arbitrary slice of the 16-line cell |
| `$FE26` | `VRAM_ADDR_L` | R/W | VRAM address, low |
| `$FE27` | `VRAM_ADDR_H` | R/W | high |
| `$FE28` | `VRAM_STEP` | R/W | `2:0` increment (0, ±1, ±2, ±`VID_STRIDE`, ±256), `3` decrement |
| `$FE29` | `VRAM_DATA` | R/W | **Auto-increments `VRAM_ADDR`. Read has a side effect.** Also aliased at `$FEC0–$FEFF` — see §5.8 |
| `$FE2A` | `SPR_IDX` | R/W | Sprite descriptor byte index, 0–255 |
| `$FE2B` | `SPR_DATA` | R/W | **Auto-increments `SPR_IDX`.** Eight bytes per descriptor (§5.6) |
| `$FE2C` | `SPR_CTRL` | R/W | `0` sprite engine enable, `1` overrun occurred this frame (write 1 to clear) |
| `$FE30` | `BLT_IDX` | R/W | Blitter command-block byte index, 0–31 |
| `$FE31` | `BLT_DATA` | R/W | **Auto-increments `BLT_IDX`.** The command block is §5.7 |
| `$FE32` | `BLT_CTRL` | W | Writing starts an operation: `2:0` op, `4:3` logic op, `5` transparent, `6` reverse direction |
| `$FE33` | `BLT_STAT` | R | `0` busy, `1` clipped-away (the operation produced no pixels) |
| `$FE34` | `PIX_X_L` | R/W | Pixel port X, low |
| `$FE35` | `PIX_X_H` | R/W | `1:0` high |
| `$FE36` | `PIX_Y_L` | R/W | Pixel port Y, low |
| `$FE37` | `PIX_Y_H` | R/W | `0` high |
| `$FE38` | `PIX_DATA` | R/W | Read or write one pixel at (X, Y) in the current bpp, sub-byte masking done in hardware. **Auto-increments X**, so a horizontal span is one store per pixel |

`$FE39–$FE3F` are spare.

`$FE1F`, `$FE29`, `$FE2B`, `$FE31` and `$FE38` all have read side
effects, and `$FE1E`, `$FE2A` and `$FE30` are readable so an interrupt
handler can save and restore the index it interrupted.

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

[`rtl/soc/cool8_vga.v`](../rtl/soc/cool8_vga.v) generates it, in **51
LUT4 and 46 flip-flops**, and every number in that table is checked
against a golden model on every pixel clock of two frames by
`sim/test_video.py`. It runs in the *pixel* domain: the system clock is
12 MHz and these two are decoupled through a scanline buffer, which is
what [D26](01-decisions.md#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled)
settled. `o_prefetch` fires once a line at the start of the front porch,
naming the line about to be displayed, so the buffer has the whole
horizontal blank — 160 pixel clocks, 6.4 µs — to fill.

### 5.2 Two memories, one clock

**Text modes read main RAM. Every other mode reads a dedicated 64 KB
VRAM** built from the two remaining SPRAM blocks. The blitter and the
sprite pattern fetch operate in VRAM only, so neither can ever stall the
CPU. Which memory the display fetch reads is decided by the mode decode,
not by a register — there is no setting that puts a blitter destination
in main RAM. Full argument in
[D28](01-decisions.md#d28--video-memory-is-split-the-text-map-in-main-ram-everything-else-in-dedicated-vram).

```
12 MHz                                                     25.125 MHz
──────────────────────────────────────────────────────    ───────────
CPU ──┬── arbiter ── SPRAM x2, 64 KB main RAM
      │                    ▲
      │                    │ text map only
      │              ┌─────┴──────┐
      ├── I/O page ──┤   fetch    ├── line buffer ──▶ palette ──▶ VGA
      │   $FE10-3F   │   engine   │   (EBR, dual clock)   ▲
      │              └─────┬──────┘                       │
      │                    │                        sprite line buffer
      │                    ▼                              ▲
      └── VRAM port ── arbiter ── SPRAM x2, 64 KB VRAM ────┘
                          ▲   ▲
                 blitter ─┘   └─ sprite engine
```

The fetch engine, both arbiters, the sprite engine, the blitter and the
CPU's port all run at **12 MHz**. Only
[`cool8_vga`](../rtl/soc/cool8_vga.v) and the pixel output stage run at
25.125. **The dual-clock line buffer is the only clock crossing in the
machine** — see [D29](01-decisions.md#d29--the-video-subsystem-runs-at-12-mhz-only-the-raster-is-at-25125).

### 5.3 Modes

The fetch engine is parameterised by `VID_CTRL`, `VID_BASE`,
`VID_STRIDE` and the scroll registers. **The modes below are presets
over that one engine, not separate hardware**; `VID_MODE` loads the
registers and software may override any of them afterwards.

All modes use the 256-entry, 12-bit palette. Logical pixels are doubled
where the resolution is below 640×480.

| # | Engine | Memory | Displayed | Format | Bytes | Stride |
|---|---|---|---|---|---|---|
| 0 | text | main | 80×30 cells, 8×16 glyphs | char + attr | 8192 | 256 |
| 1 | text | main | 40×30 cells, 16×16 | char + attr | 8192 | 256 |
| 2 | tile | VRAM | 40×30 tiles of 8×8 → 320×240 | 2 B/entry, 4 bpp patterns | 4096 + patterns | 128 |
| 3 | bitmap | VRAM | 640×480, native | 1 bpp | 38,400 | 80 |
| 4 | bitmap | VRAM | 320×240 → doubled to full screen | 4 bpp | 38,400 | 160 |
| 5 | bitmap | VRAM | 256×192 → doubled, bordered | 4 bpp | 24,576 | 128 |
| 6 | bitmap | VRAM | 256×240 → doubled, side borders | 8 bpp | 61,440 | 256 |

**Mode 4 is the general graphics mode** and leaves 25 KB of VRAM for
patterns, sprites and off-screen work. **Mode 5 is the one that
double-buffers** — two buffers is 49,152 bytes, leaving 16 KB. Mode 4
cannot double-buffer; 76,800 bytes does not fit in 64 KB, and the answer
to wanting it is usually mode 2.

**Mode 2 is what a game should use.** A tile map needs no double
buffering because nothing is redrawn: scrolling is a register write and
only the edges of the map are touched. Map 4 KB + 256 tiles 8 KB +
sprite patterns 8 KB is 20 KB, leaving 44 KB free. This is why the NES
and the Master System had no framebuffer.

**Mode 6 fills VRAM.** 61,440 of 65,536 leaves 4 KB — about 32 sprite
patterns and nothing else. It is the mode that coexists with nothing,
and that is a property of 8 bpp rather than a flaw in the layout.

### 5.4 The character and tile engine

Text and tiles are one engine. A cell is a 16-bit word — index in the
low byte, attribute in the high byte — so one access fetches a complete
cell.

| Format | Cell | Attribute byte |
|---|---|---|
| Text | 8×16, 1 bpp glyph | `bg[7:4] fg[3:0]`, indices into a 16-entry palette bank |
| Tile | 8×8, 4 bpp | `[7:6]` V/H flip, `[5:4]` pattern bank, `[3:0]` palette bank |

**The canonical text map is 128×32 cells with 80×30 displayed**, stride
256. That makes the address of row *r* one add on `XH` and the circular
scroll wrap an `AND R0,#31`, where a 160-byte stride needs a `MUL` that
clobbers X — the exact spill pattern
[D21](01-decisions.md#d21--four-general-registers-is-enough-confirmed-question-closed)
measured. `VID_STRIDE` is a register, so software that would rather have
the 4800-byte screen back writes 160 and pays the multiply. Reasoning in
[D30](01-decisions.md#d30--the-text-map-stride-is-a-register-and-the-canonical-map-is-128x32).

Mode 1 is the same 8×16 glyphs **doubled horizontally only**, giving
16×16 cells and the same 30 rows. It uses the real character set; there
is no half-height font.

**Changing the tile set**, in increasing order of speed:

| | Cost |
|---|---|
| Write patterns through `VRAM_DATA` | ~70 cycles for one 8×8 4 bpp tile; ~2 ms for 256 |
| `COPY_RECT` between VRAM regions | ~0.7 ms for an 8 KB set, CPU free |
| Repoint `PAT_BASE` | **one register write, instant** |
| `[5:4]` pattern bank in the attribute | four sets live at once, per cell, no writes at all |

Animating eight tiles per frame costs about 800 cycles out of ~200,000.
Loading a set from SPI flash is `LD R0,[$FE8B] ; ST [$FE29],R0` at
~6 cycles a byte — an 8 KB set in 4 ms, no DMA engine needed.

**The font is 256 glyphs of 8×16 in EBR (4 KB) on its own port**, so
glyph fetches in text mode cost no memory bandwidth at all and a boot
message needs nothing loaded. The character set is **CP437**, the font
is Spleen 8×16 (BSD 2-clause), vendored in
[`assets/font/`](../assets/font) and converted by `tools/mkfont.py`.
Codes `$00-$1F` are blank — CP437's decorative glyphs, which Spleen does
not carry.

Mode 0 is built: [`rtl/soc/cool8_text.v`](../rtl/soc/cool8_text.v),
**266 LUT4, 212 flip-flops and 9 EBR** — eight the font, one the
dual-clock line buffer.

### 5.5 Scrolling

The engine changes where it reads from; nothing moves in memory.

- **Text.** The map is a circular buffer 32 rows tall with 30 displayed.
  Scrolling a terminal is: increment the origin row, clear the newly
  exposed row, move the cursor. No bulk copy. `VID_SCRL_Y` gives fine
  vertical motion within that.
- **Tile.** `VID_SCRL_X/Y` are 10-bit, covering whole-tile and fine
  pixel motion in one register pair. The map wraps at its power-of-two
  width and height, which is what the spare rows and columns are for.
- **Bitmap.** `VID_BASE` plus `VID_STRIDE`. A framebuffer wider than the
  viewport scrolls by moving the base, so software redraws only newly
  exposed rows or columns.

`VID_BASE` is latched at the start of vertical blanking, so a page flip
never tears.

### 5.6 Sprites

Independent of the background mode — a separate line buffer merged at
the pixel stage — so sprites work over text, tiles and bitmaps alike.

```
32 descriptors, 8 bytes each, in dual-port EBR
8 sprites per scanline
8x8 and 16x16, 4 bpp: 15 colours plus transparency
```

The CPU writes descriptors through `SPR_IDX`/`SPR_DATA` on one port
while the scan engine reads the other, so **descriptor scanning costs no
VRAM bandwidth at all**.

| Byte | Contents |
|---|---|
| 0 | Pattern address `12:5` (32-byte granularity) |
| 1 | Pattern address `15:13`, enable |
| 2–3 | X, 10 bits — final VGA coordinates, 0–639 |
| 4–5 | Y, 9 bits — 0–479 |
| 6 | H-flip, V-flip, priority (2 bits) |
| 7 | Size, palette bank (4 bits) |

Positions are in **final raster coordinates**, so a sprite over a
320×240 background positions twice as finely as the background it sits
on, and reaches the border without tricks.

**Priority is descriptor order, implemented as first-writer-wins** into
the line buffer: a pixel is written only if the buffer entry is still
transparent. That is the cheapest correct scheme and it needs no
comparator. Pixel value 0 is transparent. Two priority levels place a
sprite in front of or behind the background.

**Eight per line is a real limit.** Sprite 9 on a line is dropped and
`SPR_CTRL` bit 1 records that it happened, so software can detect the
condition rather than wonder. Multiplexing more than eight is done with
the raster interrupt (§5.9), which is deliberate hardware rather than a
reproduction of the VIC-II's DMA timing — see
[00-goals.md](00-goals.md) non-goals.

### 5.7 The blitter

Operates in VRAM only, and therefore **never stalls the CPU**. The
command block is written through `BLT_IDX`/`BLT_DATA` as a run of
stores and started by writing `BLT_CTRL`.

| Op | |
|---|---|
| `FILL_RECT` | solid colour, in the current bpp |
| `COPY_RECT` | VRAM→VRAM, reverse-direction bit for overlapping regions |
| `COPY_RECT_TRANSPARENT` | colour 0 skipped — software sprites, UI icons, glyph blitting |
| `DRAW_LINE` | Bresenham |
| `CLEAR` | `FILL_RECT` over the whole destination |

Logic ops: replace, XOR, OR, AND. **XOR is what gives you rubber-band
selection, non-destructive cursors and sprite masking** without reading
the background back.

Every operation respects a programmable clipping rectangle. `BLT_STAT`
bit 1 reports an operation that clipped away entirely, so software need
not pre-check.

Command block: `SRC`, `DST`, `SRC_STRIDE`, `DST_STRIDE`, `WIDTH`,
`HEIGHT`, `COLOUR`, `CLIP_X0/X1/Y0/Y1`. `DRAW_LINE` reuses `SRC` and
`DST` as the two endpoints.

**Measured against the CPU doing the same work:** clearing a 320×240
4 bpp screen is ~3.4 ms with the CPU untouched, against ~9.6 ms with the
CPU fully occupied. Line drawing is 10–20× and free.

`PIX_DATA` (§4.2) is the small end of the same machinery: write X, write
Y, write colour, and the engine does the address arithmetic and the
sub-byte masking on the blitter's own adders. For 1, 2 and 4 bpp that is
**faster than direct addressing would have been**, which is why losing
`ST` access to the framebuffer costs nothing.

### 5.8 Reaching VRAM from the CPU, and from the debugger

`VRAM_ADDR`/`VRAM_DATA` with a programmable step (±1, ±2, ±stride,
±256). One port, not two — the second was traded away in the fit budget;
bulk copies are the blitter's job anyway.

**`VRAM_DATA` is also aliased across `$FEC0–$FEFF`.** Every address in
that block hits the same auto-incrementing port, so one loader `READ`
frame pulls 64 consecutive VRAM bytes instead of re-reading one
register. Without it VRAM would be invisible to
[`tools/cool8screen.py`](../tools/cool8screen.py) and to the loader's
memory read-back, which are the two tools that made M4 tractable. It
costs *fewer* gates than decoding the address precisely.

### 5.9 Raster effects

`VID_RASTER`, `VID_RCMP` and `VID_IRQ` (§4.2) give split screens,
per-region scroll values, mid-frame palette changes, status bars and
sprite multiplexing. Register writes take effect immediately; there is
no shadowing and no next-line/next-frame queue — one policy, one bank of
flip-flops. The exception is `VID_BASE`, latched at vblank so page flips
do not tear.

### 5.10 Bandwidth

Per scanline, because that is the unit a line buffer works in. A line is
31.8 µs, and at 12 MHz that is **381 memory accesses**.

**Main RAM**, shared with the CPU:

```
mode 0, text: 80 cells of one word, per 16 scanlines
              = 5 accesses per line                    1.3 %
every other mode                                       0 %
```

**VRAM**, shared between the display fetch, the sprite engine and the
blitter — and with nothing the CPU is doing:

| Load | Accesses/line | |
|---|---|---|
| mode 3, 1 bpp 640-wide | 40 | 10 % |
| mode 4, 4 bpp 320-wide | 80 | 21 % |
| mode 2, tile map + patterns | 85 | 22 % |
| mode 6, 8 bpp 256-wide | 128 | 34 % |
| 8 sprites × 16 px at 4 bpp | 32 | 8 % |
| **worst case: mode 6 + sprites** | **160** | **42 %** |
| **left for the blitter** | **221** | **58 %** |

That is 211 KB per frame of blitter throughput. Nothing in the mode set
is bandwidth-starved at 12 MHz, which is why
[D29](01-decisions.md#d29--the-video-subsystem-runs-at-12-mhz-only-the-raster-is-at-25125)
did not put VRAM in the pixel domain.

The pixel clock is still 25.125 MHz and unaffected — it has to be, since
a monitor is counting.

### 5.11 Not in v1

| | Why, and what it would cost |
|---|---|
| Second background layer | ~250–400 LUT4 for a duplicate fetch path and a priority mux. Sprites plus a raster split cover most of the same ground |
| 64 descriptors / 16 sprites per line | Bandwidth-feasible at 12 MHz (128 accesses/line); it is LUT4 that stops it, ~250 more |
| Sprite ×2 doubling, 32 px sprites, 8 bpp sprites | Descriptor bits are reserved |
| Sprite-to-sprite collision | Software bounding-box tests are a few instructions per pair and tell you *what* hit |
| Programmable viewport and calibration mode | Traded away in the fit budget. `VID_BORDER` remains; a calibration screen is a few blitter rectangles |
| Second indirect VRAM port | Traded away. Costs CPU-driven VRAM copies about half their speed |
| Palette cycling sequencer | A vblank handler rotating entries is ~20 instructions and more flexible |
| Command queue, display list, banked CPU window | Not needed at these speeds, and each is a new failure mode |

**And one that will not arrive: sampled audio from VRAM.** VRAM is the
video engine's, and the audio engine is dividers and an LFSR
([D12](01-decisions.md#d12--audio-sn76489-style-not-sid-style)) with no
use for memory.

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
