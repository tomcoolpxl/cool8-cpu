# 04 — The Cool8 machine

Everything outside the CPU core. FPGA-only; none of this goes to the
ASIC.

---

## 1. Block diagram

```
        12 MHz ──▶ PLL ──▶ 25.125 MHz ──▶ everything
                                │
   ┌────────────┐   clock       │
   │ COOL8 core │◀── enable ────┤   (programmable divider, D13)
   └─────┬──────┘   (÷1…÷32)    │
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
      Prompt on screen and on the USB serial port. Accepts a program
      over serial, loads it, runs it.
```

Programs are loaded over the iCELink USB CDC serial port in v1. The
board's 8 MB SPI flash has plenty of unused space above the bitstream
and is an obvious later addition.

---

## 4. I/O page

Base `$FE00`. Unlisted addresses read as `$FF` and ignore writes.

### 4.1 System — `$FE00`

| Addr | Name | Access | Bits |
|---|---|---|---|
| `$FE00` | `SYSCTRL` | R/W | `0`: `ROMEN` (1 = boot ROM overlay on). `1`: reserved. |
| `$FE01` | `CPUDIV` | R/W | `2:0`: CPU clock enable divider — 0=÷1 (25.1 MHz) … 5=÷32 (~785 kHz). |
| `$FE02` | `SYSSTAT` | R | Build/version identification. |
| `$FE03` | `LED` | R/W | `2:0` = R, G, B on the board LED. |

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

**Frequency.** Reference clock is 25.125 MHz ÷ 64 ≈ 392.6 kHz.

```
f_out = 392578 / (2 × divider)
```

| Divider | Frequency |
|---|---|
| 4095 | 48 Hz |
| 892 | 220 Hz (A3) |
| 446 | 440 Hz (A4) |
| 223 | 880 Hz (A5) |
| 4 | 49 kHz |

A 12-bit divider at this reference reaches down to 48 Hz — considerably
better bass than the real SN76489 managed with 10 bits, and the same
coarsening at high frequencies, which is part of the sound.

**Output chain.** Four channels, each a signed ±volume square, summed
into an 8-bit signed sample, then a first-order sigma-delta modulator
running at the full 25.125 MHz clock drives one FPGA pin. External RC
low-pass and coupling capacitor produce line level. See
[05-board.md](05-board.md).

### 4.5 Timer — `$FE60`

| Addr | Name | Description |
|---|---|---|
| `$FE60` | `TMR_RELOAD_L` | 16-bit reload value, low |
| `$FE61` | `TMR_RELOAD_H` | high |
| `$FE62` | `TMR_CTRL` | `0` enable, `1` auto-reload, `4` interrupt enable |
| `$FE63` | `TMR_STAT` | `0` expired (write 1 to clear) |

Counts down at 25.125 MHz ÷ 256 ≈ 98.1 kHz.

### 4.6 Serial — `$FE70`

Connected to the iCELink USB CDC port. 115200 8N1.

| Addr | Name | Description |
|---|---|---|
| `$FE70` | `UART_STAT` | `0` RX data available, `1` TX ready, `2` RX overrun |
| `$FE71` | `UART_DATA` | Read pops RX, write pushes TX |

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

```
mode 4, the worst case:
  logical pixel rate  = 25.125 MHz / 2          = 12.56 M px/s
  4 bpp, 16-bit SPRAM = 4 pixels per access
  video accesses      = 12.56 / 4               = 3.14 M/s
  available           =                           25.125 M/s
  video share         = 3.14 / 25.125           = 12.5 %
```

**The video engine steals one memory cycle in eight.** Text modes are
the same or better. A round-robin arbiter with video priority is
sufficient; the CPU sees an occasional `mem_ready` low and does not care.

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
| *(none yet)* | NMI | Reserved — a reset button, probably |

All IRQ sources OR together into the core's single `irq` input. The
handler reads the per-peripheral status registers to find the cause.
This is the smallest arrangement and it is what an 8-bit machine should
do; a priority encoder can come later if the handler's dispatch cost
ever matters.
