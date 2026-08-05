# 04 — The Cool8 machine

Everything outside the CPU core. FPGA-only; none of this goes to the
ASIC.

---

## 1. Block diagram

```
   12 MHz ──▶ PLL ──┬──▶ 25.125 MHz ──▶ VGA pixels, across a line buffer
    (pin 35)         │
                     └── ÷3 ──▶ 8.375 MHz ──▶ everything below
   ┌────────────┐
   │ COOL8 core │            D32: both clocks from one PLL
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
365,036 clocks — 43.6 ms at 8.375 MHz, nearly all of it clearing RAM. Steps 3,
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
| `$FE01` | `CPUDIV` | — | CPU clock enable divider. **Not implemented**; reads `$FF`. It existed to divide a 25.125 MHz system clock down to something an 8-bit machine plausibly ran at, and [D32](01-decisions.md#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock) divides it by three in the clock tree instead. Nothing needs it until there is a reason to run slower than that. |
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
| `$FE1E` | `PAL_IDX` | R/W | Palette **entry** index, 0–255. The half within an entry is implicit and is reset by writing this register |
| `$FE1F` | `PAL_DATA` | W | First write `0000RRRR`, second `GGGGBBBB`; the pair commits together and **the second advances `PAL_IDX`**. Matches the 12-bit VGA PMOD exactly. Write-only — a read port on the palette is the one the raster uses, and reading back what software wrote is not worth a second block RAM |
| `$FE20` | `PAT_BASE_L` | R/W | Glyph/tile pattern base in VRAM. Repointing this swaps a whole tile set in one write |
| `$FE21` | `PAT_BASE_H` | R/W | |
| `$FE22` | `CUR_X` | R/W | Text cursor column |
| `$FE23` | `CUR_Y` | R/W | Text cursor row |
| `$FE24` | `CUR_CTRL` | R/W | `0` enable, `2:1` style (block/underline/bar/inverse), `4:3` blink rate. Writing `CUR_X` or `CUR_Y` resets the blink phase |
| `$FE25` | `CUR_LINES` | R/W | `3:0` first scanline, `7:4` last — an arbitrary slice of the 16-line cell |
| `$FE26` | `VRAM_ADDR_L` | R/W | VRAM address, low |
| `$FE27` | `VRAM_ADDR_H` | R/W | high |
| `$FE28` | `VRAM_STEP` | R/W | `2:0` amount: 0, 1, 2, 4, 8, 16, 256, `VID_STRIDE`. `3` = decrement. Resets to +1 |
| `$FE29` | `VRAM_DATA` | R/W | **Auto-increments `VRAM_ADDR`. Read has a side effect.** Also aliased at `$FEC0–$FEFF` — see §5.8 |
| `$FE2A` | `SPR_IDX` | R/W | Sprite descriptor byte index, 0–255 |
| `$FE2B` | `SPR_DATA` | W | **Auto-increments `SPR_IDX`.** Eight bytes per descriptor (§5.6), written as pairs from an even index. Write-only, for the same reason `PAL_DATA` is |
| `$FE2C` | `SPR_CTRL` | R/W | `0` sprite engine enable, `1` overrun occurred this frame (write 1 to clear) |
| `$FE30–$FE33` | — | — | **Reserved for a blitter, which is not built.** Reads `$FF`. See [D34](01-decisions.md#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter) and §5.11 |
| `$FE34` | `PIX_X_L` | R/W | Pixel port X, low |
| `$FE35` | `PIX_X_H` | R/W | `2:0` high |
| `$FE36` | `PIX_Y_L` | R/W | Pixel port Y, low |
| `$FE37` | `PIX_Y_H` | R/W | `2:0` high |
| `$FE38` | `PIX_DATA` | R/W | Read or write one pixel at (X, Y) of the surface `VID_BASE`/`VID_STRIDE` describes, in the current bpp, with sub-byte masking done in hardware. **Auto-increments X**, so a horizontal span is one store per pixel. **Read has a side effect** and holds the bus until the memory answers |

`$FE39–$FE3F` are spare, as is `$FE2D–$FE2F`.

`$FE29` and `$FE38` have read side effects, and `$FE1E` and `$FE2A` are
readable so an interrupt handler can save and restore the index it
interrupted. The three `_DATA` ports are write-only and read `$FF`.

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

**Frequency.** Reference clock is 8.375 MHz ÷ 22 = 380.7 kHz.

```
f_out = 380682 / (2 × divider)
```

| Divider | Frequency |
|---|---|
| 4095 | 46.5 Hz |
| 865 | 220.0 Hz (A3) |
| 433 | 439.6 Hz (A4) |
| 216 | 881.2 Hz (A5) |
| 4 | 47.6 kHz |

A 12-bit divider at this reference reaches down to 46.5 Hz —
considerably better bass than the real SN76489 managed with 10 bits, and
the same coarsening at high frequencies, which is part of the sound.

**The divider off the system clock has now been changed twice, and each
time the reference was what was preserved.** It was ÷64 of 25.125 MHz,
then ÷32 of 12 MHz, and it is ÷22 of 8.375
([D32](01-decisions.md#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock)).
The table above is a set of notes that have to stay reachable and in
tune, and ~380 kHz lands them within 0.15 % while keeping the bass floor
where it was. A round ÷32 would give 261.7 kHz, which is in tune too —
the divider table is recomputed either way — but it is coarser at the
top, where an 8-bit machine's music actually lives.

An awkward divisor costs a comparator rather than a shift, which is the
whole of the difference, and this engine is M7 and not built yet.

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

Counts down at 8.375 MHz ÷ 256 = 32.7 kHz — a 30.6 µs tick, and up to
2.00 s from a 16-bit reload.

Here the ÷256 is kept and the rate simply follows the clock, which is
the opposite of the choice §4.4 makes. Nothing has to land on a specific
frequency: a timer needs enough resolution and enough range, and a
slower clock improves the range and leaves the resolution far finer than
any 8-bit machine can act on.

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
baud) − 1`; at the 8.375 MHz system clock
([D32](01-decisions.md#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock))
115200 baud is `$0048` (72), which lands on 114726 — 0.41 % out, well
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
8.375 MHz — a third of this one, because the part's single PLL owns the
pin the 12 MHz arrives on
([D32](01-decisions.md#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock))
— and the two are decoupled through a line buffer. `o_prefetch` fires once a line at the start of the front porch,
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
8.375 MHz                                                  25.125 MHz
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
      ├── VRAM port ── arbiter ── SPRAM x2, 64 KB VRAM ────┘
      │                   ▲   ▲
      └── pixel port ─────┘   └─ sprite engine
```

The fetch engine, both arbiters, the sprite engine, the pixel port and
the CPU's VRAM port all run at **8.375 MHz**. Only
[`cool8_vga`](../rtl/soc/cool8_vga.v) and the pixel output stage run at
25.125. **The crossings are the line buffer and the palette, and both
are inside dual-clock block RAMs** — see
[D29](01-decisions.md#d29--the-video-subsystem-runs-at-12-mhz-only-the-raster-is-at-25125).

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

All three engines are one block:
[`cool8_fetch.v`](../rtl/soc/cool8_fetch.v) fills the line buffer and
[`cool8_pixel.v`](../rtl/soc/cool8_pixel.v) turns it into pixels.
`cool8_text.v`, the special-purpose mode-0 block that came first, is
gone — and the proof that nothing was lost with it is that
`docs/img/text-mode-0.png`, the screen it produced, comes back
byte-identical from the general engine.

### 5.5 Scrolling

The engine changes where it reads from; nothing moves in memory.

**`VID_SCRL_X` and `VID_SCRL_Y` are fine scroll**: the low four bits in
text, the low three in tiles. The coarse part is a move of `VID_BASE` —
one 16-bit add in software per row or per tile column — because doing it
in hardware means multiplying the origin by the stride, and the
alternatives were a DSP block the pixel port has a better claim on or an
accumulator that has to be re-run whenever the register moves. See
[D35](01-decisions.md#d35--the-scroll-registers-are-fine-scroll-the-coarse-part-is-a-move-of-vid_base).
A bitmap gets the full ten bits for nothing, because its whole row is in
the line buffer already.

- **Text.** The map is a circular buffer 32 rows tall with 30 displayed.
  Scrolling a terminal is: add the stride to `VID_BASE`, clear the newly
  exposed row, move the cursor. No bulk copy — the row pointer wraps
  within `stride × 32` in hardware, and that wrap is a mask, so it is
  correct only for a power-of-two stride. `VID_SCRL_Y` gives fine
  vertical motion within a character cell.
- **Tile.** The map row wraps the same way. `VID_SCRL_X/Y` give the
  pixel motion inside a tile and `VID_BASE` gives the tile motion.
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

**The layout is packed for the scan.** A scanline is 266 system clocks
and all 32 descriptors have to be asked "are you on this line" inside
it; at four byte-reads each that is 128 clocks before a single pattern
is fetched. So the descriptor RAM is sixteen bits wide and the whole
test — enable, size and all nine bits of Y — is in the first word. The
scan is then one read per descriptor, 33 clocks, and the other three
words are read only for the eight that matter.

| Byte | Contents |
|---|---|
| 0 | Y `7:0` |
| 1 | `7` size (0 = 8×8, 1 = 16×16), `6` enable, `0` Y `8` |
| 2 | X `7:0` |
| 3 | `1:0` X `9:8` |
| 4 | Pattern address `12:5` (32-byte granularity) |
| 5 | `2:0` pattern address `15:13` |
| 6 | `7` V-flip, `6` H-flip, `5` behind the background |
| 7 | `3:0` palette bank |

A descriptor is written as byte **pairs** from an even index: the even
byte is held and the odd byte commits both, because a block RAM in this
configuration has no byte enables. `PAL_DATA` does the same thing for
the same reason.

Positions are in **final raster coordinates**, so a sprite over a
320×240 background positions twice as finely as the background it sits
on, and reaches the border without tricks.

**Priority is descriptor order, implemented backwards.** First-writer-
wins would need the line buffer read back before every write, and an
iCE40 block RAM has one read port and one write port — and the read port
belongs to the raster. So the eight sprites of a line are rendered in
reverse, seven first and zero last, and last-writer-wins gives exactly
the same picture with no reads at all. Pixel value 0 is transparent and
simply skips its write. Two priority levels place a sprite in front of
or behind the background; *behind* shows the sprite only where the
background is itself colour 0.

**Nothing clears the line buffer; every sprite cleans up after itself.**
Clearing 640 entries would take 640 of the 266 clocks a line has, so
instead **a sprite is rendered for two lines past its bottom edge,
writing zeros** over the span it used. Two lines is exactly enough and
one is not: the banks alternate every line, so a span sits in both of
them and both have to be wiped.

Those trailing rows go down *before* the real sprites of the line,
whatever their descriptor index — otherwise a low-numbered sprite's
clear would land on a high-numbered sprite's pixels, which is the
opposite of the priority rule. They also occupy slots in the
eight-per-line budget like anything else, so a sprite that ends exactly
where eight others begin can leave a ghost, and sets the overrun flag
while it does.

An entry also carries bit 1 of the line number it was written for, and a
generation that does not match reads as transparent. **That bit was the
first attempt at this and does not work on its own** — it distinguishes
a line from the one two lines earlier and not from the one four lines
earlier, so a sprite's last row came back four lines under it in a band
that repeated. It is kept because it is free in an entry that is already
ten bits wide, and because it covers the lines immediately after reset,
before any sprite has had the chance to tidy.

This is the one place in the design that depends on block RAM coming up
zeroed, which it does: EBR is initialised from the bitstream, unlike
SPRAM.

**Eight per line is a real limit.** Sprite 9 on a line is dropped and
`SPR_CTRL` bit 1 records that it happened, so software can detect the
condition rather than wonder. Multiplexing more than eight is done with
the raster interrupt (§5.9), which is deliberate hardware rather than a
reproduction of the VIC-II's DMA timing — see
[00-goals.md](00-goals.md) non-goals.

### 5.7 Reaching a pixel by coordinate

**There is no blitter.** It did not fit — the machine came to 5438 logic
cells against the 5280 the part has — and the sprite engine was kept
instead, because §5.3's own argument says a tile map redraws nothing and
therefore needs no accelerator. The full reasoning, the measurements and
what it would take to bring one back are in
[D34](01-decisions.md#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter)
and §5.11.

What is built is the small end of the same machinery, and it is the part
an 8-bit CPU is genuinely bad at:
[`cool8_pixport.v`](../rtl/soc/cool8_pixport.v), **199 LUT4 and one
`SB_MAC16`**.

Write `PIX_X`, write `PIX_Y`, write `PIX_DATA`, and the pixel appears in
the surface `VID_BASE` and `VID_STRIDE` describe. X then advances on its
own, so a horizontal span is one store per pixel.

| | |
|---|---|
| `y × stride` | one of the eight DSP blocks the design had never used |
| 4 and 8 bpp | one write, no read — a pixel is a whole number of nibbles and `MASKWREN` writes nibbles |
| 1 and 2 bpp | read, merge, write |
| the same pixel by hand through `VRAM_DATA` | a sequenced multiply, an address, a read, a mask and a write — about twenty cycles |

The merge happens in eight bits and the result goes into *both* halves
of the 16-bit word with `MASKWREN` choosing which lands, the same trick
`cool8_spram` uses for the CPU's byte port. Doing it in sixteen is what
made the blitter twice the size it should have been.

### 5.8 Reaching VRAM from the CPU, and from the debugger

`VRAM_ADDR`/`VRAM_DATA` with a programmable step. One port, not two —
the second was traded away in the fit budget.

**Seven of the eight step codes are powers of two and the eighth follows
`VID_STRIDE`.** That is why there is no fixed table of awkward row
pitches: the register holding the current mode's row pitch already
exists, so `±stride` covers 80, 128, 160, 256 and anything else a mode
needs. VERA spends a sixteen-entry increment field on the same problem.

**A read of `VRAM_DATA` returns a byte fetched in advance.** The I/O page
answers in a fixed two cycles and a VRAM read cannot — it has to win the
arbiter and then wait for `DATAOUT` — so the port keeps the byte at the
current address in a register and re-arms after every read. This is the
arrangement every VDP with a data port has used, and the reason those
chips want a dummy read after the address is set. Here the address
registers arm it themselves, so the dummy read is not needed.

**A prefetch follows a read and an address write, never a write of
data.** Writing is the bulk direction and fetching after each write would
double the port's VRAM traffic for a read that is not coming; the cost is
one stall on the first read after a burst. When the byte is not ready the
port holds `mem_ready` low, which the core tolerates and `sim/cosim.py`
already proves against randomised wait states.

**The stall is not asserted on the launch cycle**, only from the data
cycle onwards. A read's launch cycle already has `mem_ready` low from the
memory, so the term would be redundant — and leaving it out keeps the
I/O address decode off the machine's critical path, which
[D32](01-decisions.md#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock)
measured at 37 levels of logic before anything was added to it.

Implemented in [`cool8_vport.v`](../rtl/soc/cool8_vport.v), **170 LUT4
and 59 flip-flops**.

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
31.8 µs, and at 8.375 MHz that is **266 system cycles**.

**Main RAM**, shared with the CPU:

```
mode 0, text: 80 cells of two bytes, two cycles each,
              per 16 scanlines = 20 cycles per line          7.5 %
every other mode                                               0 %
```

Text costs more than the 1.3 % this section used to claim, and the
reason is that the display fetch reads main RAM a *byte* at a time
through the same port the CPU uses — `cool8_spram` presents a byte
because the core has an 8-bit bus — and a read there is two cycles.
That is the price of D28's split, and it is still small.

**VRAM**, shared between the display fetch, the sprite engine and the
CPU's indirect and pixel ports:

| Load | Cycles/line | |
|---|---|---|
| mode 3, 1 bpp 640-wide | 40 | 15 % |
| mode 4, 4 bpp 320-wide, lines doubled | 40 | 15 % |
| mode 5, 4 bpp 256-wide, lines doubled | 32 | 12 % |
| mode 6, 8 bpp 256-wide, lines doubled | 64 | 24 % |
| mode 2, tile map and patterns | 123 | 46 % |
| 8 sprites × 16 px at 4 bpp | 64 | 24 % |
| **worst case: mode 2 + sprites** | **187** | **70 %** |
| **left for the CPU's two ports** | **79** | **30 %** |

**The tile engine is now the heaviest, not mode 6**, and the reason is
sequencing rather than data: a tile costs three dependent accesses — the
map entry, then the two pattern words the entry names — and the fetch
engine runs them one at a time, so each is two cycles rather than one.
A bitmap has no dependency and its requests are pipelined, which is why
mode 6 moves twice the data for half the cycles.

30 % of a line is 79 accesses, and the CPU cannot use more than one per
store. Nothing in the mode set is bandwidth-starved.

The pixel clock is still 25.125 MHz and unaffected — it has to be, since
a monitor is counting.

### 5.11 Not in v1

| | Why, and what it would cost |
|---|---|
| **A blitter** | ~500–700 LUT4 written tightly, and the part has about 500 logic cells left. It is the first thing to build if the CPU's fetch path is ever pipelined and the design gets smaller or the clock gets faster — [D34](01-decisions.md#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter) |
| `DRAW_LINE`, Bresenham | ~200 LUT4, and it went before the blitter did. About six cycles a pixel through `PIX_DATA` in software |
| Second background layer | ~250–400 LUT4 for a duplicate fetch path and a priority mux. Sprites plus a raster split cover most of the same ground |
| 64 descriptors / 16 sprites per line | Bandwidth-feasible at 12 MHz (128 accesses/line); it is LUT4 that stops it, ~250 more |
| Sprite ×2 doubling, 32 px sprites, 8 bpp sprites | Descriptor bits are reserved |
| Sprite-to-sprite collision | Software bounding-box tests are a few instructions per pair and tell you *what* hit |
| Programmable viewport and calibration mode | Traded away in the fit budget. `VID_BORDER` remains; a calibration screen is a few blitter rectangles |
| Second indirect VRAM port | Traded away. Costs CPU-driven VRAM copies about half their speed |
| Whole-tile and whole-cell scroll registers | Fine scroll is in hardware; the coarse part is one add on `VID_BASE` ([D35](01-decisions.md#d35--the-scroll-registers-are-fine-scroll-the-coarse-part-is-a-move-of-vid_base)) |
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
