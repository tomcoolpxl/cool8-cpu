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
 │ 64 KB   │◀──┤  $FF00    │   │ EBR 4 KB  │  │ engine │
 │ 2 blocks│   └───────────┘   └───────────┘  └───┬────┘
 └────▲────┘                                      │
      └──────────── arbiter, video priority ──────┘
                                                   │
        ┌──────────┬──────────┬───────────────┼──────────┐
     ┌──▼───┐  ┌───▼────┐ ┌───▼─────┐   ┌─────▼───┐  ┌───▼───┐
     │ PS/2 │  │ SPI    │ │  sound  │   │   VGA   │  │ UART  │
     │ kbd  │  │ flash  │ │ 8 voice │   └─────────┘  └───────┘
     └──────┘  └────────┘ └─────────┘
```

---

## 2. Memory map

**This section is normative for what the hardware decodes.
[`tools/memmap.py`](../tools/memmap.py) is the machine-readable copy and
follows it**, the same arrangement `tools/opcodes.py` has for the
encoding: Python imports addresses from there rather than writing one
down twice, and `poe check` fails on drift. The *software* allocation of
page 0 belongs to [`sw/lowram.asm`](../sw/lowram.asm), which is what the
assembler reads, and `memmap.py` verifies itself against those equates.

| Range | Size | Contents |
|---|---|---|
| `$0000–$FEFF` | 65280 B | RAM |
| `$FF00–$FFF7` | 248 B | I/O page — **always decoded, always wins** |
| `$FFF8–$FFFF` | 8 B | RAM — the vectors (§2.1) |

Plus a reset-time overlay:

| Range | While `ROMEN=1` |
|---|---|
| `$F000–$FEFF`, `$FFF8–$FFFF` | Boot ROM (EBR) on **reads** |

**The page is at the top, and it stops eight bytes short of it.** It was
at `$FE00` until
[D67](01-decisions.md#d67--one-system-storage-region-derived-from-the-claims-and-page-0-stops-being-special),
which cost two things that both look small and were not: the system
image could not pass `$FDFF`, and `$FF00–$FFF7` was a stranded 248-byte
RAM island above the page — outside the boot ROM's `$0000–$EFFF` clear,
which is why BASIC had to zero it by hand and why the interpreter's
workspace ended up allocated there rather than anywhere sensible.

Moving the page to `$FF00` makes RAM contiguous to `$FEFF` and hands
**256 bytes to the system image and 256 contiguous bytes to the ROM**.
The eight-byte notch is what makes it cheap: the CPU fetches its vectors
from `$FFF8–$FFFF`, so leaving those as RAM means `rtl/core/` is not
involved at all — the whole change is `io_sel` in
[`cool8_soc.v`](../rtl/soc/cool8_soc.v) and the ROM window in
[`cool8_mem.v`](../rtl/soc/cool8_mem.v).

**No software writes the base down.** `tools/ioregs.py` holds it, reads
every register's offset out of the Verilog localparams that decode it,
and generates `sw/io.asm` and `sw/io.bas`; `poe check` fails on a bare
`$FFxx` anywhere in `sw/`. Before that it was sixty hand-written equates
across five files, and moving the page would have meant editing them all
and hoping.

**Nothing decodes into page 0**, and page 0 has no addressing advantage
either — [D6](01-decisions.md) dropped the zero page and the direct-page
register both, so `$0040` costs exactly what `$7E40` costs. It is
ordinary RAM, and [D67](01-decisions.md) is where it stopped being
treated as scarce: system storage is one packed region, and
`tools/memmap.py --check` refuses a byte with two owners.

**What the software puts where** is not decoded by anything — the
hardware sees 64 KB of flat RAM and the table above is all of it — but
it is the map that matters when reading `sw/`, so:

| Range | Size | Contents |
|---|---|---|
| `$0000–$00FF` | 256 | free. Formerly "page 0", special to nothing now |
| `$0100–$01FF` | 256 | the CPU stack, growing down from `$0200` |
| `$0200–$97FF` | **38,400** | **the user's**: program up, heap down, and the name table, call stack and save stack above the program ([D73]) |
| `$9800–$ABFF` | 5,120 | the text map — 80×32 cells, stride 160 |
| `$AC00–$AF69` | 874 | system storage and the string accumulator |
| `$AF6A–$B21C` | 691 | slack: the image's room to grow |
| `$B21D–$FEFF` | 19,683 | the system image — BASIC, editor, floats |

**The map moved down 1 KB in [D82]**, with the user's agreement, to make
room for the read stream — `FREE` went 39,424 to 38,400 and it is
[standing rule 5](../AGENTS.md) that it does not move again without one.
The four rows above it are derived and move whenever BASIC's size does;
`python tools/memmap.py` prints them from the built image, which is the
copy to trust.

**Do not move the map to make room. Ask first** — it is a
[standing rule](../AGENTS.md), because every byte the map moves down
comes off `FREE` one for one and that is the user's memory. D80 needed
eleven bytes and took them out of a dead 32-byte reservation instead.

Two things to know if it ever genuinely has to move. **The map and
system storage are one block and slide together**: moving the map alone
opens a hole nothing can reach — the user's region ends at the map and
the image stops at the claims — which is what `memmap.check()` says, in
those words. **And the origin is not free.** It reaches the hardware as
four constants in `cool8_vregs.v`, and folding them through the video
address adder costs a different number of logic cells for each value:
`$9C00` is 5,121, while `$9400` — the arithmetically obvious 2 KB down —
is 5,172, the worst of five candidates measured. D80 has the table.
Pick an origin by building it, not by subtracting.

Every boundary in it is derived rather than written down: the image's
origin is `$FF00 − size`, system storage's floor is its lowest `;:`
claim, and the user's ceiling is the map. `python tools/memmap.py`
prints it from the built image, which is the copy to trust — the two
floating rows move whenever BASIC's size changes, and the slack row is
what absorbs that. See
[D70](01-decisions.md#d70--the-user-area-is-one-region-of-40448-bytes).

**Writes always go to RAM**, even where the ROM overlay is active. That
is what lets the boot code install the interrupt vectors at
`$FFF8–$FFFF` before it switches the overlay off.

The I/O page punches a 248-byte hole in the ROM image at ROM offset
`$0F00–$0FF7`. Don't put code there — but note it is now at the *end* of
the image rather than in the middle of it, so ROM code runs contiguously
from `$F000` to `$FEFF` and only the vectors sit above the hole. The
`.org $FF00` that used to exile `sw/keymap.asm` to the island below the
vectors is gone with it ([D67](01-decisions.md)).

There is no banking, and there will not be. The two remaining SPRAM
blocks are **video RAM** — a separate 64 KB address space reached
through an indirect port, not through the CPU's map. See
[D28](01-decisions.md#d28--video-memory-is-split-the-text-map-in-main-ram-everything-else-in-dedicated-vram)
and §5.2.

That leaves sampled audio with nowhere to live, which is correct: the
sound engine is phase accumulators and an LFSR
([D41](01-decisions.md#d41--the-sound-engine-is-one-datapath-walked-eight-times-not-four-dividers))
and its voice state fits in one block RAM.

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

5.  ROM: jump to the monitor
      It is in the ROM alongside this and runs where it stands.
      ROMEN stays set.

6.  Monitor
      Prompt on screen and on the USB serial port.
```

**All of it exists**, in [`sw/boot.asm`](../sw/boot.asm) and the
[`monitor.asm`](../sw/monitor.asm) and [`disasm.asm`](../sw/disasm.asm)
it includes, built into the EBR image by `tools/mkrom.py`. Reset to the
handover at step 5 is **366,091 clocks — 43.7 ms at 8.375 MHz**, nearly
all of it clearing RAM; the monitor's first prompt reaches the far end
of the serial line at **387,675 clocks, 46 ms**, the difference being
the banner going out a byte at a time at 115200.

**Step 5 used to be two steps**: copy the monitor into RAM, then drop
the overlay and jump. It does neither, and
[D36](01-decisions.md#d36--the-monitor-runs-in-place-from-rom-the-overlay-is-not-dropped)
is the argument — a monitor in RAM is overwritten by exactly the program
you most want to examine. The monitor's variables live at `$EF00`, just
below the window and inside the region step 2 has already cleared.

Step 4 is the one worth looking at twice: the vectors live at
`$FFF8-$FFFF`, which is inside the ROM's own read window. The write goes
to RAM and a read of the same address still returns the ROM byte. That
asymmetry is the whole reason the overlay is read-only, and without it
there would be no way to install a vector the machine could use after
the ROM went away.

### 3.1 …or not, if the loader says otherwise

**The loader is a build option now and the shipping image does not carry
it** ([D40](01-decisions.md#d40--the-hardware-loader-is-a-build-option-and-it-is-off)).
What follows describes a bitstream built with `LOADER(1)`.

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
| SPI flash (§4.8) | **The usual way.** `icesprog -o 0x100000 -w prog.bin`, then the monitor's `L` — or as a named file on a volume (§8) | 7.9 MB above the bitstream, ~125 ms to load 64 KB |
| The machine's own flash writes (§4.8) | Anything it made itself | `FLS_WDATA`/`FLS_WCTRL`, above the `$100000` floor |
| Hardware loader over USB serial | Only in a `LOADER(1)` build | No bitstream rebuild, no working ROM required |
| Baked into the boot ROM image | Bring-up only | The ROM is 4 KB and the monitor is 3029 bytes of it |

---

## 4. I/O page

Base `$FF00`. Unlisted addresses read as `$FF` and ignore writes — `$FF`
rather than `$00`, so a register that is not there reads like a bus
nobody is driving instead of like a register holding zero.

The page is decoded on the **bus**, in
[`rtl/soc/cool8_soc.v`](../rtl/soc/cool8_soc.v), ahead of the memory and
whoever the master is. Two consequences worth knowing:

- **The loader reaches it.** A `WRITE` frame to `$FF03` lights the LED
  with no CPU, no program and no working boot ROM. That is deliberate,
  and it is the first useful thing to do to a board that has just come
  up. The other end of it is that a `WRITE` to `$FF80` is the loader
  writing its own control register mid-frame.
- **A read costs the same one wait state a RAM read does.** Answering in
  the address cycle would make the read data a combinational function of
  the address, and the core's address is a combinational function of the
  byte it is fetching — the two close a loop through the bus. So the I/O
  page is read on the launch cycle and answers on the next one, exactly
  as the SPRAM and the boot ROM do.

### 4.1 System — `$FF00`

| Addr | Name | Access | Bits |
|---|---|---|---|
| `$FF00` | `SYSCTRL` | R/W | `0`: `ROMEN` (1 = boot ROM overlay on). Reloads from `~BOOTRAM` on every CPU reset, not from a constant — see §4.7. `7:1` read 0. |
| `$FF01` | `CPUDIV` | — | CPU clock enable divider. **Not implemented**; reads `$FF`. It existed to divide a 25.125 MHz system clock down to something an 8-bit machine plausibly ran at, and [D32](01-decisions.md#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock) divides it by three in the clock tree instead. Nothing needs it until there is a reason to run slower than that. |
| `$FF02` | `SYSSTAT` | R | Build identification: a constant carried as a parameter on `cool8_soc`, `$05` at M6. It answers "which bitstream is this board actually running", which is a question that gets asked during bring-up and has no other way to be answered. |
| `$FF03` | `LED` | R/W | `2:0` = R, G, B on the board LED, active high here. The board's own polarity is [cool8_top](../rtl/soc/) and the `.pcf`'s problem, not software's. |

### 4.2 Video — `$FF10`

Registers with more than a handful of fields sit behind an **indexed
port with auto-increment** — palette, sprite descriptors, blitter
command block, VRAM. That is one idiom, used four times, and it is what
lets a 256-entry palette and a twelve-register blitter share a 48-byte
allocation. It is also the fastest shape for an 8-bit CPU: setup becomes
a straight run of stores with no address recomputation between them.

| Addr | Name | Access | Description |
|---|---|---|---|
| `$FF10` | `VID_MODE` | R/W | `3:0` preset number (§5.3) — writing it loads the registers below. `7` = display enable. Presets 7–15 are **undefined**: no bounds check, freedom and consequences. |
| `$FF11` | `VID_CTRL` | R/W | `1:0` engine (0 text, 1 tile, 2 bitmap). `3:2` bpp (0=1, 1=2, 2=4, 3=8). `4` horizontal doubling. `5` vertical doubling. |
| `$FF12` | `VID_BASE_L` | R/W | Display base address, low byte |
| `$FF13` | `VID_BASE_H` | R/W | high byte |
| `$FF14` | `VID_STRIDE_L` | R/W | Row pitch in bytes, low. Text map stride, tile map width, or bitmap row pitch — see [D30](01-decisions.md#d30--the-text-map-stride-is-a-register-and-the-canonical-map-is-12832) |
| `$FF15` | `VID_STRIDE_H` | R/W | high |
| `$FF16` | `VID_SCRL_X_L` | R/W | Horizontal scroll, low |
| `$FF17` | `VID_SCRL_X_H` | R/W | `1:0` high. 0–1023 |
| `$FF18` | `VID_SCRL_Y_L` | R/W | Vertical scroll, low |
| `$FF19` | `VID_SCRL_Y_H` | R/W | `1:0` high |
| `$FF1A` | `VID_BORDER` | R/W | Border colour, a full 8-bit palette index — so the border and the background can be exactly the same colour |
| `$FF1B` | `VID_RASTER` | R | Current scanline, bits 7:0 |
| `$FF1C` | `VID_RCMP` | R/W | Raster compare value |
| `$FF1D` | `VID_IRQ` | R/W | `0` raster hit (write 1 to clear), `1` vblank. `5:4` enables |
| `$FF1E` | `PAL_IDX` | R/W | Palette **entry** index, 0–255. The half within an entry is implicit and is reset by writing this register |
| `$FF1F` | `PAL_DATA` | W | First write `0000RRRR`, second `GGGGBBBB`; the pair commits together and **the second advances `PAL_IDX`**. Matches the 12-bit VGA PMOD exactly. Write-only — a read port on the palette is the one the raster uses, and reading back what software wrote is not worth a second block RAM |
| `$FF20` | `PAT_BASE_L` | R/W | Glyph/tile pattern base in VRAM. Repointing this swaps a whole tile set in one write |
| `$FF21` | `PAT_BASE_H` | R/W | |
| `$FF22` | `CUR_X` | R/W | Text cursor column. The displayed position is latched at the start of vertical blanking, as `VID_BASE` is, so a mid-frame move cannot split the block; reads return the written value at once |
| `$FF23` | `CUR_Y` | R/W | Text cursor row, latched likewise. Five bits, and it is the console's row unchanged — a console row is 16 display lines in every mode, so there is nothing to convert ([D81]) |
| `$FF24` | `CUR_CTRL` | R/W | `0` enable, `4:3` blink rate, `2:1` unused. Writing `CUR_X` or `CUR_Y` resets the blink phase, effective at the same frame edge |

**The style field is gone**, and with it `CUR_LINES`: the cursor inverts
its whole cell, in every mode, which is the only style the editor ever
asked for and the one a C64 draws. That removed the software cursor the
console kept for the five modes the hardware did not cover — and with it
the second place that remembered where the cursor was, which is what
made it blink in a stale spot after a mode change.

**The blink rate selects a bit of a frame counter**, so each rung is
twice the last:

| `4:3` | frames a phase | full cycle at 60 Hz |
|---|---|---|
| 0 | 8 | 3.75 Hz |
| 1 | 16 | 1.88 Hz |
| **2** | **32** | **0.94 Hz** — what `sw/console.asm` and the boot ROM write |
| 3 | — | solid, no blink |

Rate 2 is not a taste. The software cursor counted 32 frames a phase in
`in_get` before the hardware took the job over, so it is what this
machine's cursor has always done. Both writers said `$01` — rate 0 —
for one release, and a cursor blinking four times faster than it ever
had was the first thing anyone sitting in front of it noticed. `$11` is
enabled at rate 2. Measured off the rendered picture, not the register:
32 frames a phase.
| `$FF25` | `CUR_LINES` | R/W | `3:0` first scanline, `7:4` last — an arbitrary slice of the 16-line cell |
| `$FF26` | `VRAM_ADDR_L` | R/W | VRAM address, low |
| `$FF27` | `VRAM_ADDR_H` | R/W | high |
| `$FF28` | `VRAM_STEP` | R/W | `2:0` amount: 0, 1, 2, 4, 8, 16, 256, `VID_STRIDE`. `3` = decrement. Resets to +1 |
| `$FF29` | `VRAM_DATA` | R/W | **Auto-increments `VRAM_ADDR`. Read has a side effect.** Also aliased at `$FFC0–$FFFF` — see §5.8 |
| `$FF2A` | `SPR_IDX` | R/W | Sprite descriptor byte index, 0–255 |
| `$FF2B` | `SPR_DATA` | W | **Auto-increments `SPR_IDX`.** Eight bytes per descriptor (§5.6), written as pairs from an even index. Write-only, for the same reason `PAL_DATA` is |
| `$FF2C` | `SPR_CTRL` | R/W | `0` sprite engine enable, `1` overrun occurred this frame (write 1 to clear), `7:4` the palette bank **every** sprite uses — see §5.6 |
| `$FF30–$FF33` | — | — | **Reserved for a blitter, which is not built.** Reads `$FF`. See [D34](01-decisions.md#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter) and §5.11 |
| `$FF34` | `PIX_X_L` | R/W | Pixel port X, low |
| `$FF35` | `PIX_X_H` | R/W | `2:0` high |
| `$FF36` | `PIX_Y_L` | R/W | Pixel port Y, low |
| `$FF37` | `PIX_Y_H` | R/W | `2:0` high |
| `$FF38` | `PIX_DATA` | W | Write one pixel at (X, Y) of the surface `VID_BASE`/`VID_STRIDE` describes, in the current bpp, with sub-byte masking done in hardware. **Auto-increments X**, so a horizontal span is one store per pixel. **Write-only** — reads `$FF`; see §5.7 |
| `$FF39` | `PIX_DATA_Y` | W | The same store **auto-incrementing Y** instead, so a vertical run is also one store per pixel. The store address picks the direction — no mode bit (D91). **Write-only** — reads `$FF`; see §5.7 |

`$FF39–$FF3F` are spare, as is `$FF2D–$FF2F`.

`$FF29` and `$FF38` have read side effects, and `$FF1E` and `$FF2A` are
readable so an interrupt handler can save and restore the index it
interrupted. The three `_DATA` ports are write-only and read `$FF`.

### 4.3 Keyboard — `$FF40`

| Addr | Name | Access | Description |
|---|---|---|---|
| `$FF40` | `KBD_STAT` | R | `0` data available, `1` FIFO overflow, `2` parity error, `3` transmit busy, `4` transmit failed |
| `$FF41` | `KBD_DATA` | R | Pop one raw scancode byte from the FIFO. **Read has a side effect.** |
| `$FF42` | `KBD_CTRL` | R/W | `0` FIFO clear, `4` interrupt enable |
| `$FF43` | `KBD_TX` | W | Byte to send to the keyboard (LED/typematic commands) |
| `$FF44` | `KBD_MOD` | R/W | `0` Shift held, `1` Ctrl held, `2` Alt held, `3` the Ctrl+Esc chord fired (write 1 to clear) |

**Ctrl+Shift+Esc resets the machine and Ctrl+Esc raises `NMI`**, both
decoded in `cool8_ps2` from the arriving bytes ([D54](01-decisions.md)).
The reset is the only way back from a program that has taken the
vectors and stopped reading the FIFO — the board has no reset pin — and
being in hardware it cannot be masked, intercepted or ignored. The warm
chord is an NMI plus bit 3, so the break button and the restart share
one unmaskable path and are told apart by asking.

**Bits `2:0` say "now"; the FIFO says "earlier".** A byte is read out of
the queue long after it arrived, so a shift read from here may already
have been released — these bits are for chords and for asking what is
held this instant, never for translating a queued character. That stays
with the in-stream state `sw/kbd.asm` keeps.

Bits 1, 2 and 4 of `KBD_STAT` are sticky and are cleared by writing a 1
to the bit's own position, the same shape `UART_STAT` and `VID_IRQ` use.

Bit 4 is not in the original register map and was added with the
hardware. **A transmission the device never acknowledges has to end**,
or a monitor setting the caps-lock LED hangs for ever on a socket with
nothing plugged into it. The receiver gives up after the 15 ms the
protocol allows a device to start clocking, and after a byte the device
clocked in but did not acknowledge, and says which happened only in the
sense that both raise this bit.

The hardware delivers **raw Set 2 scancodes**, including `$E0` prefixes
and `$F0` break codes. Translation to ASCII is software's job — it
belongs in the decoder, not in gates, and
[`sw/kbd.asm`](../sw/kbd.asm) does it in a 128-byte table plus a
21-entry list of the keys shift does something to that is not a case
change. That file is `.include`d by both the boot ROM and BASIC, which
cannot share it at run time: `basic.bin` runs past `$F000` and would be
hidden under its own ROM window ([D50](01-decisions.md)).

**Bit 4 of `KBD_CTRL` is used.** BASIC sets it, so a keypress raises IRQ
rather than waiting up to a frame for the vertical blank, and the same
handler drains both this and the UART into one ring. The UART is not on
that line and cannot be (§6), which is why the vblank still ticks.

#### Scancodes a program reaches for

`KEY(c)` takes a raw Set 2 code, because it asks about a key and not
about a character ([D51](01-decisions.md)). The common ones:

| key | code | key | code | key | code |
|---|---|---|---|---|---|
| `A`–`Z` | see the keymap | up | `$75` | space | `$29` |
| `1` | `$16` | down | `$72` | enter | `$5A` |
| `Z` | `$1A` | left | `$6B` | escape | `$76` |
| `X` | `$22` | right | `$74` | left shift | `$12` |
| `.` | `$49` | home | `$6C` | ctrl | `$14` |

The cursor keys share their codes with the numeric keypad and are told
apart by the `$E0` prefix. There is no keypad on this machine, so only
one of each pair can ever be pressed and `KEY($75)` is unambiguous.

**Ctrl+Pause is Break.** It arrives as `$E0 $7E` and the decoder returns
`$03` — the byte the serial console's Ctrl-C already sends — so a
running program is stopped the same way whichever keyboard is attached.

**Read `KBD_STAT` bit 0 before `KBD_DATA`.** The FIFO is a block RAM and
its read register is a cycle behind, so a read taken in the cycle a byte
lands in an empty FIFO would see the previous one. Availability is
suppressed for that cycle instead — which makes "bit 0 is set" the
condition under which the data register is meaningful, and a read taken
without checking is not. `sim/test_ps2.py` sweeps a blind read across
the whole arrival window to prove nothing is ever lost or duplicated by
one that does not check.

A parity or framing error **drops the byte** rather than queueing it and
raising a flag beside it. A scancode nobody can trust is worse than a
missing one, because it desynchronises the make/break pairing that
follows.

FIFO depth 16 bytes. The overflow is the *newest* byte, so a burst that
outruns software loses the end of it and not the beginning.

### 4.4 Sound — `$FF50`

**Eight voices, one datapath.** Square waves and noise, 4-bit volume
each, mixed into a 1-bit sigma-delta output on one pin. 141 LUT4, 131
flip-flops and one block RAM — see
[D41](01-decisions.md#d41--the-sound-engine-is-one-datapath-walked-eight-times-not-four-dividers)
for why that is smaller than the four dividers it replaced.

| Addr | Name | Access | Description |
|---|---|---|---|
| `$FF50` | `SND_IDX` | W | Which byte of the voice array. Auto-increments on every write of `SND_DATA` |
| `$FF51` | `SND_DATA` | W | ...and it |

Two addresses rather than twenty-four, the idiom `PAL_IDX`/`PAL_DATA` and
`SPR_IDX`/`SPR_DATA` already use. Both are write-only: the array's read
port belongs to the engine.

**Six bytes to a voice**, and a 16-bit word commits on its odd byte
because this configuration of block RAM has no byte enables — the same
arrangement `PAL_DATA` uses.

| Byte | Contents |
|---|---|
| 8v+0, 8v+1 | Phase increment `[15:0]` — the pitch |
| 8v+2, 8v+3 | The engine's phase accumulator. Software leaves it alone |
| 8v+4 | `3:0` volume |
| 8v+5 | `7` noise, `6` enable |

**Frequency.** The phase accumulator is 16 bits and a sample is taken
every 256 system clocks:

```
f_out = increment × 8375000 / 256 / 65536 = increment × 0.4993 Hz
```

| Increment | Frequency |
|---|---|
| 1 | 0.5 Hz |
| 441 | 220.2 Hz (A3) |
| 881 | 439.9 Hz (A4) |
| 1763 | 880.3 Hz (A5) |

**0.5 Hz resolution everywhere**, where the 12-bit divider this replaced
gave 46 Hz at the bottom of its range and 12 kHz steps at the top. Twelve
bits of divider could not reach both ends; sixteen bits of increment
reach the whole range at one resolution.

**Noise** is a 16-bit LFSR shared by every voice that asks for it,
advanced when that voice's phase wraps — so a noise voice's pitch
register sets the noise rate exactly as it sets a square's frequency,
rather than choosing between three fixed rates.

**Output.** The eight voices sum into a signed 8-bit sample, and a
first-order sigma-delta modulator running at the full 8.375 MHz drives
one pin. 256 carries per sample is eight bits of resolution, which is all
an eight-bit machine's music needs. **An external RC low-pass and a
coupling capacitor are the DAC** — see [05-board.md](05-board.md).

**No envelopes, no sweep, no filter.** A vblank handler doing envelopes
is about twenty instructions and can make shapes no hardware ADSR offers.
A voice is silenced by clearing its enable bit or its volume.

### 4.5 Timer — `$FF60`

| Addr | Name | Description |
|---|---|---|
| `$FF60` | `TMR_RELOAD_L` | 16-bit reload value, low |
| `$FF61` | `TMR_RELOAD_H` | high |
| `$FF62` | `TMR_CTRL` | `0` enable, `1` auto-reload, `4` interrupt enable |
| `$FF63` | `TMR_STAT` | `0` expired (write 1 to clear) |

Counts down at 8.375 MHz ÷ 256 = 32.7 kHz — a 30.6 µs tick, and up to
2.00 s from a 16-bit reload.

Here the ÷256 is kept and the rate simply follows the clock, which is
the opposite of the choice §4.4 makes. Nothing has to land on a specific
frequency: a timer needs enough resolution and enough range, and a
slower clock improves the range and leaves the resolution far finer than
any 8-bit machine can act on.

### 4.6 Serial — `$FF70`

Connected to the iCELink USB CDC port. 115200 8N1.

| Addr | Name | Access | Description |
|---|---|---|---|
| `$FF70` | `UART_STAT` | R/W | `0` RX data available, `1` TX has room, `2` RX overrun — **write 1 to bit 2 to acknowledge the overrun**, the same shape `VID_IRQ` and `TMR_STAT` use |
| `$FF71` | `UART_DATA` | R/W | Read pops RX, write pushes TX. **Read has a side effect.** |
| `$FF72` | `UART_DIV_L` | R/W | Baud divider, low byte |
| `$FF73` | `UART_DIV_H` | R/W | Baud divider, high byte |

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

### 4.7 Loader — `$FF80`

**This block is a build option and the shipping bitstream does not have
it** — `cool8_soc #(.LOADER(0))`, which is the default. Both addresses
read `$FF` without it, as an address nobody claims does. See
[D40](01-decisions.md#d40--the-hardware-loader-is-a-build-option-and-it-is-off)
for what it cost and what replaced it; build with `LOADER(1)` when a
board will not boot and you need the bus-master read-back.

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
| `$FF80` | `LDR_CTRL` | R/W | `0` sniffer enable (resets to 1; reads 1 and is not yet implemented — the sniffer is always on). `4` CPU requests a bus grant for itself. `5` `BOOTRAM` — see below. |
| `$FF81` | `LDR_STAT` | R | `0` loader currently owns the bus, `1` last frame had a checksum error, `2` a frame has been received since reset |

`BOOTRAM` is the piece that makes the `GO` command work. Concretely, it
is **`ROMEN`'s reset value**: every CPU reset reloads `ROMEN` from
`~BOOTRAM` rather than from a constant, so with the bit set the machine
wakes with the overlay already gone and fetches its reset vector from
`$FFF8` in RAM — which the loader has just written. Software can still
set `ROMEN` back afterwards; `BOOTRAM` decides again at the next reset.
The bit is owned by the loader and survives a CPU reset; only a full
board reset clears it.

Wire protocol: [07-loader.md](07-loader.md).

### 4.8 SPI flash — `$FF88`

The board's 8 MB configuration flash doubles as mass storage. The iCE40
releases pins 14–17 to user logic once `CDONE` goes high, so a small SPI
master can read the flash at runtime. This is the machine's cartridge
slot and its disk. This section is the raw device; the filesystem
`SAVE` and `LOAD` put on top of it is §8.

| Addr | Name | Access | Description |
|---|---|---|---|
| `$FF88` | `FLS_ADDR_L` | R/W | Flash address bits 7:0 |
| `$FF89` | `FLS_ADDR_M` | R/W | bits 15:8 |
| `$FF8A` | `FLS_ADDR_H` | R/W | bits 23:16 |
| `$FF8B` | `FLS_DATA` | R | Read one byte and advance the address. **Read has a side effect.** |
| `$FF8C` | `FLS_CTRL` | R/W | `0` stream open — write 1 to issue a read at `FLS_ADDR` and hold chip-select low; write 0 to close |
| `$FF8D` | `FLS_STAT` | R | `0` busy, `1` stream open, `2` a write is running |
| `$FF8E` | `FLS_WDATA` | W | The byte a program will write |
| `$FF8F` | `FLS_WCTRL` | R/W | Write `1` to program `FLS_WDATA` at `FLS_ADDR`, `2` to erase its 4 KB sector, `4` to acknowledge a refusal. Reads `0` write running, `2` the last request was refused |

**A read of `FLS_DATA` stalls until the byte is there.** A byte off the
wire is sixteen system clocks and the CPU can ask for one in two, so
something has to give, and it is the same choice `VRAM_DATA` makes for
the same reason ([§5.8](#58-reaching-vram-from-the-cpu-and-from-the-debugger)):
the copy loop below has no status poll in it because it does not need
one. `FLS_STAT` is still worth having — it is how a program asks whether
the stream is open without touching a register that has a side effect,
and reading it never stalls.

`FLS_ADDR` follows the stream as it advances, so it always says where
the next byte will come from. **Writes to it are ignored while the
stream is open**: the flash is counting on its own and only a close and
a re-open moves it, so a write that appeared to work and did not would
be worse than one that visibly does nothing.

Typical use — copy 8 KB from flash offset `$100000` to `$4000`:

```asm
        MOV  R0,#$00
        ST   [$FF88],R0        ; addr = $100000
        ST   [$FF89],R0
        MOV  R0,#$10
        ST   [$FF8A],R0
        MOV  R0,#$01
        ST   [$FF8C],R0        ; open the stream
        ; X = $4000, R2:R3 = 8192
.copy:  LD   R1,[$FF8B]        ; byte, address auto-advances
        ST   [X],R1
        INCW X
        ...
        SUB  R0,R0
        ST   [$FF8C],R0        ; close
```

SPI mode 0, and the clock is the system clock divided by two — **4.19 MHz
at [D32](01-decisions.md#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock)'s
8.375**, which is about 500 KB/s and 64 KB in 125 ms. This section used
to say 12.5 MHz and 40 ms, from before the system clock was known.
Opcode `$03` is specified to 50 MHz on these parts, so the limit here is
the system clock and not the flash; a double-rate shifter would buy
back the factor of two and nothing in the plan is waiting on it.

**Writes, above a floor that is checked in gates.** The machine can
program a byte and erase a 4 KB sector, which is what makes it a computer
that can save rather than only load — see
[D42](01-decisions.md#d42--the-machine-can-write-its-own-flash-above-a-hardware-floor).

**Nothing below `$100000` can be touched.** The comparison happens on the
cycle the request arrives, *before an opcode has been chosen*: a request
below the floor sets `FLS_WCTRL` bit 2 and does nothing else — no
write-enable, no command, no chip select. There is no path in the gates
from a bad request to a shifted opcode, so the bitstream at offset 0 is
unreachable by construction rather than by discipline. The bitstream is
about 104 KB against a 1 MB floor: an order of magnitude of margin.

The master has five opcodes and no others — `$03` READ, `$06` WREN,
`$02` PP, `$20` SE, `$05` RDSR. `sim/test_flash.py`'s device model
**fails the run** on any opcode outside that set, on any program or erase
below the floor, and on either without a preceding write-enable.
`sim/mutate.py` carries the mutation that deletes the floor check and it
is caught, which is what turns the promise into a test rather than a
comment.

A program or an erase is three SPI transactions — enable, command, then
poll the status register until the part reports it has finished — and the
poll is in gates because software would otherwise have to name the RDSR
opcode, which is precisely what it must not be able to do. `FLS_STAT`
bit 2 and `FLS_WCTRL` bit 0 say when it is running.

**The upgrade is untested on hardware.** Back up the bitstream and try a
high address first.

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
      │   $FF10-3F   │   engine   │   (EBR, dual clock)   ▲
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

All modes use the 256-entry, 12-bit palette.

**The bitstream carries a default and nothing writes one at boot**
([D77]). The palette RAM used to come up zeroed -- 256 entries of black,
border included -- so the ROM, the flash stub and the console each wrote
part of one. `rtl/soc/cool8_pal.v` reads `pal.hex` at elaboration now,
the way `cool8_rom.v` reads the boot image, and it is **76 logic cells
cheaper** than the software it replaced. `tools/palette.py` owns the
colours and generates the emulator's copy from the same table.

256 entries is **sixteen banks of sixteen**, because a tile attribute's
low nibble selects a bank. Modes 0, 1, 4 and 5 read bank 0; mode 3
reaches only entries 0 and 1; mode 6 sees all 256.

**Bank 0's slots are load-bearing; banks 1-15 are designed palettes**
([D79]). A text attribute is `bg[7:4] fg[3:0]`, so bank 0 keeps CGA's
slot meanings — entry 4 is red because a program writing 4 means red.
Nothing indexes the other banks by meaning, so each is a published
sixteen chosen for how it looks:

| bank | palette | author | source |
|---|---|---|---|
| 0 | Softened CGA | COOL8 | the boot ROM's, values eased |
| 1 | PICO-8 | Lexaloffle | [lospec](https://lospec.com/palette-list/pico-8) |
| 2 | DawnBringer 16 | DawnBringer | [lospec](https://lospec.com/palette-list/dawnbringer-16) |
| 3 | Sweetie 16 | GrafxKid | [lospec](https://lospec.com/palette-list/sweetie-16) |
| 4 | Endesga 16 | Endesga | [lospec](https://lospec.com/palette-list/endesga-16) |
| 5 | AAP-16 | Adigun A. Polack | [lospec](https://lospec.com/palette-list/aap-16) |
| 6 | Arne 16 | Arne Niklas Jansson | [lospec](https://lospec.com/palette-list/arne-16) |
| 7 | Steam Lords | Slynyrd | [lospec](https://lospec.com/palette-list/steam-lords) |
| 8 | Island Joy 16 | Kerrie Lake | [lospec](https://lospec.com/palette-list/island-joy-16) |
| 9 | Bubblegum 16 | PineappleOnPizza | [lospec](https://lospec.com/palette-list/bubblegum-16) |
| 10 | Commodore 64 | Commodore | [lospec](https://lospec.com/palette-list/commodore64) |
| 11 | NA16 | Nauris | [lospec](https://lospec.com/palette-list/na16) |
| 12 | ZX Spectrum | Sinclair | [lospec](https://lospec.com/palette-list/zx-spectrum) |
| 13 | MSX | Texas Instruments | [lospec](https://lospec.com/palette-list/msx) |
| 14 | CGA | IBM | the hard 0/A/5/F levels bank 0 softens |
| 15 | Greyscale | COOL8 | a linear ramp, for dithering and masks |

`python tools/palette.py --show` prints them with their sources. The
24-bit originals live there and one function quantises them, so the only
thing this machine changes about a published palette is its depth. Logical pixels are doubled
where the resolution is below 640×480.

| # | Engine | Memory | Displayed | Format | Bytes | Stride |
|---|---|---|---|---|---|---|
| 0 | text | main | 80×30 cells, 8×16 glyphs | char + attr | 5120 | 160 |
| 1 | text | main | 40×30 cells, 16×16 | char + attr | 5120 | 160 |
| 2 | tile | VRAM | 40×30 tiles of 8×8 → 320×240 | 2 B/entry, 4 bpp patterns | 4096 + patterns | 128 |
| 3 | bitmap | VRAM | 640×480, native | 1 bpp | 38,400 | 80 |
| 4 | bitmap | VRAM | 320×240 → doubled to full screen | 4 bpp | 38,400 | 160 |
| 5 | bitmap | VRAM | 256×192 → doubled, bordered | 4 bpp | 24,576 | 128 |
| 6 | bitmap | VRAM | 256×240 → doubled, side borders | 8 bpp | 61,440 | 256 |

**A bitmap row is at most 255 words**, so `VID_STRIDE` above 510 in a
bitmap mode silently loses the end of every row. That is the line
buffer's bank — 256 words — rather than an arbitrary limit, and the
widest mode in the set is mode 6 at 256 bytes, so there is a factor of
two of headroom before anyone meets it. It matters only to software
building a mode by hand.

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

**The canonical text map is 80×32 cells with 80×30 displayed**, stride
160, 5,120 bytes, at `$9C00`. The two spare rows off the bottom are what
the circular scroll rotates through, so a scroll is one register write
and moves no memory.

Row addressing costs no `MUL` and no spill of X, which is what
[D30](01-decisions.md#d30--the-text-map-stride-is-a-register-and-the-canonical-map-is-12832)
originally bought with a 256-byte stride and 8,192 bytes: 160 is 5·32,
so row *r* is at `(5r) << 5`, `5r` fits in a byte for all 32 rows, and
the address's high byte is `5r >> 3` with low byte `(5r AND 7) << 5`.
Three adds and six shifts, all eight-bit. `con_row` in `sw/console.asm`
is the routine; `con_cell` caches its result in `CROWA`, so a run of
characters on one row pays it once.

**Neither the stride nor the base is constrained by the hardware.** The
fetch engine has an explicit map-origin register
([D69](01-decisions.md#d69--the-map-is-derived-end-to-end)), so the
circular wrap is computed against the map's origin rather than against
`VID_BASE`, which is what a scroll moves. Any stride, any address. The
5,120-byte map is what let the screen be packed against system storage
and the user's memory become one region
([D70](01-decisions.md#d70--the-user-area-is-one-region-of-40448-bytes)).
`con_row` still wants the base page-aligned — that is software's own
constraint, worth one add.

Mode 1 is the same 8×16 glyphs **doubled horizontally only**, giving
16×16 cells and the same 30 rows. It uses the real character set; there
is no half-height font.

**Changing the tile set**, in increasing order of speed:

| | Cost |
|---|---|
| Write patterns through `VRAM_DATA` | ~70 cycles for one 8×8 4 bpp tile; ~2 ms for 256 — and `STW` into the `$FFC0` alias block moves two bytes per instruction (§5.8) |
| Repoint `PAT_BASE` | **one register write, instant** |
| `[5:4]` pattern bank in the attribute | four sets live at once, per cell, no writes at all |

(An earlier revision listed a `COPY_RECT` here. There is no blitter —
§5.11 and [D34](01-decisions.md#d34--the-video-engine-ships-with-sprites-and-a-pixel-port-and-no-blitter)
— and the port's prefetch makes interleaved VRAM-to-VRAM copying its
worst case; redraw from source data instead.)

Animating eight tiles per frame costs about 800 cycles out of ~200,000.
Loading a set from SPI flash is `LD R0,[$FF8B] ; ST [$FF29],R0` at
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
  within `stride × 32` in hardware, against a map origin of its own, so
  **any stride works**; text's own 160 is not a power of two.
  `VID_SCRL_Y` gives fine vertical motion within a character cell.

  > **Software must wrap `VID_BASE` itself**, and this is the part that
  > was missing for a milestone. The hardware wraps *its own row pointer*,
  > against the map's origin — `map_org` is a register of its own, loaded
  > from `VID_BASE` on a mode change and never after — so the origin says
  > where the map is and `VID_BASE` says which of its rows is displayed
  > first. A base allowed to walk past the end of the map takes the whole
  > window with it and the map appears to relocate. The idiom is a
  > compare and subtract:
  >
  > ```
  > base = base + stride
  > if base >= map_org + stride × 32 then base = base − stride × 32
  > ```
  >
  > **It is not a mask, and the map does not have to be aligned to its own
  > size.** It was both, once: `VID_BASE` carried the address in its high
  > bits and the scroll offset in its low ones, which is where the "8 KB
  > map on an 8 KB boundary" rule and the power-of-two stride ([D30]) came
  > from. Separating the origin ended both restrictions — **any stride,
  > any address** — and mode 0's stride of **160** is the proof, since the
  > mask could not have scrolled it at all.
  >
  > `sw/monitor.asm`'s `scroll` is the worked example.
  > `VID_BASE` must also stay a whole number of rows: it is not
  > masked in hardware, and a base off a row boundary shifts every row on
  > the screen by the remainder.
  >
  > [`sw/monitor.asm`](../sw/monitor.asm) copied 4640 bytes per scrolled
  > line — about 46,000 cycles, 5.5 ms — until this was written down, and
  > `sim/test_monitor.py` now checks the origin moved rather than trusting
  > that it did.
- **Tile.** The map row wraps the same way. `VID_SCRL_X/Y` give the
  pixel motion inside a tile and `VID_BASE` gives the tile motion.
- **Bitmap.** `VID_BASE` plus `VID_STRIDE`. A framebuffer wider than the
  viewport scrolls by moving the base, so software redraws only newly
  exposed rows or columns.

`VID_BASE` is latched at the start of vertical blanking, so a page flip
never tears.

**The tile row offset is latched with it, and the text one is not.** In
tile mode `VID_SCRL_Y`'s low three bits are sampled once at frame start
(`trow <= scrl_y[2:0]`); in text mode the fetch adds `scrl_y[3:0]` to
the source line as it goes. So a tile-mode fine scroll changes on a
frame boundary and a text-mode one changes wherever the raster happens
to be — which is a raster effect if you want one and a tear if you do
not.

**And `VID_IRQ`'s vblank flag sets at that same instant, which decides
how a scroll must be written.** By the time software sees the flag the
latch has already happened, so *everything written after it lands on the
next frame* — base and tile offset alike. A smooth scroll therefore
writes, into one gap, the pair of values that belong to one frame: the
coarse step goes with **fine step 0**, not with fine step 7. Pair the
base with 7 and one frame shows a row and seven pixels at once and the
next comes back, which reads as a shudder with an odd frame in it.

**A fine scroll makes the window touch 31 rows, not 30.** Thirty rows
of 16 are the whole 480 lines, so any non-zero `VID_SCRL_Y` shows the
bottom of row `B` and the top of row `B+30`. Of a 32-row ring that
leaves exactly **one** row off screen, `B+31`, and it is the only one
software may draw into. Filling 31 rows before scrolling puts the draw
one row early — into `B+30`, the part-shown one — and every new row is
then built in full view along the bottom edge. Fill 32.

**The cursor is not gated by engine.** `cur_cell` XORs the finished
palette index, so it is visible in text, tile and bitmap alike, and a
graphics program that never asked for a cursor gets one blinking
wherever `CUR_X`/`CUR_Y` were left. `CUR_CTRL` bit 0 turns it off in the
chip — `POKE $FF24,0` — rather than anything having to paint over it.

`VID_BASE` is also two byte-writes, and a frame start between them
latches an address that was never meant to exist: going from `$0980` to
`$0A00`, a low byte written first gives `$0900` — a row *backwards*.
Write both immediately after seeing the vblank flag, where a whole frame
of margin stands between them and the next latch.

### 5.5a The frame counter

**`TMR_L`/`TMR_M`/`TMR_H` are 24 bits of frames since reset**, free
running, incremented on the same `frame_start` the vblank flag and the
cursor blink already use. At 59.97 Hz it wraps in **77 hours**.

**Every machine of the period counted time by counting the vertical
blank, and every one of them counted it in software** — the C64's `TI`,
the Spectrum's `FRAMES`, the Atari's `RTCLOK`, all incremented by an
interrupt handler. That is why `TI` stops on a C64 during tape and disk
work: no interrupt, no time. (The C64 also carried a real time-of-day
clock in the CIA, in BCD, with an alarm — the expensive answer.)

Counting it in hardware costs 24 flip-flops and **cannot be missed**:
there is no handler to run, nothing to disable, and no drift under load.
It is not a programmable timer — no reload, no compare, no interrupt of
its own. `VID_RCMP` already does raster interrupts and `VID_IRQ` bit 1
already does the frame tick, so a timer's usual jobs have owners.

**Three plain bytes and no latch**, because this bus has no read strobe
and the tear it would guard is a frame boundary landing between two
reads microseconds apart. Read high, low, high again and retry if the
high byte moved — the idiom the machines with the same problem used.

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
| 7 | `3:0` palette bank — **ignored**, see below |

**All sprites share one palette bank**, `SPR_CTRL[7:4]`. Byte 7's
per-sprite field is still in the layout and is not read by the hardware.

The reason is the line buffer, and it is the largest single claim on
block RAM in the machine. It is 2048 entries, and an iCE40 block RAM
2048 deep is **two bits wide**, so it costs `ceil(bits/2)` blocks and
nothing else about it matters. Carrying a 4-bit bank on every pixel made
the entry fourteen bits and the buffer seven blocks; without it the entry
is `{tag[3:0], behind, pix[3:0]}` — nine bits, **five blocks**.

The generation tag lost a bit with it, and that needed checking rather
than assuming: an *n*-bit tag separates 2ⁿ⁻¹ fills of one bank, because
the banks alternate every line, and the sweep bounds how long an entry
can survive at ten fills. Four bits separate sixteen, which is enough.
Three would separate eight, which is not — and that is why this stops at
nine bits and not eight, even though eight would have saved another
block. Getting there needs the sweep to cover a bank in five passes of
128 instead of ten of 64, and the sweep blocks rendering, which would
take the practical limit from about six sprites a line to about four.

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

**Eight per line is a real limit, and it is now a real eight.** It was
five: a 16x16 sprite cost 38 of the 266 system clocks a scanline has, so
the sixth onwards were cut off by the next line and vanished without
saying anything. Pipelining the pattern fetch and halving the buffer
sweep took a sprite to 25 clocks, and eight of them to 237 with 29 to
spare —
[D43](01-decisions.md#d43--the-sprite-engine-renders-eight-16x16-sprites-and-did-not-before)
has the measurements.

Sprite 9 on a line is dropped and `SPR_CTRL` bit 1 records that it
happened, **and so is a render the next line aborts** — that used to be
silent and is the reason the limit went unnoticed for two milestones. Multiplexing more than eight is done with
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
[`cool8_pixport.v`](../rtl/soc/cool8_pixport.v) and one `SB_MAC16`.

Write `PIX_X`, write `PIX_Y`, write `PIX_DATA`, and the pixel appears in
the surface `VID_BASE` and `VID_STRIDE` describe. X then advances on its
own, so a horizontal span is one store per pixel.

**`PIX_DATA_Y` is the same store advancing Y instead** ([D91]), so a
vertical run is also one store per pixel. The store address picks the
direction and there is deliberately no mode register: a Bresenham inner
loop mixes the two stores freely, nothing to set, save or restore, and
an interrupt cannot land between a mode write and the store it was
meant for. +1 is the only direction either port steps, because any line
can be drawn from its lesser-Y endpoint. Measured cost of the register:
**+47 LUT4, +1 FF** on the SoC (3,972 → 4,019, same synthesis).

**`PIX_DATA` is write-only.** It was readable, and reading it cost two
more variable shifters — one to bring the pixel down out of its byte and
one to mask it — plus a stall path, a state and a holding register,
because the byte has to be fetched before the answer exists. Nothing
wanted it: this is an output device, and the one use for reading a pixel
back is collision detection, which §5.11 already answers with software
bounding-box tests. Software that genuinely needs to read a surface has
`VRAM_ADDR`/`VRAM_DATA`. A read of `$FF38` returns `$FF`, and the pixel
port no longer holds the bus at all.

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

**`VRAM_DATA` is also aliased across `$FFC0–$FFFF`.** Every address in
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

## 7. The monitor

[`sw/monitor.asm`](../sw/monitor.asm) and the disassembler it includes,
[`sw/disasm.asm`](../sw/disasm.asm). It is in the ROM image, it runs
where it stands ([D36](01-decisions.md#d36--the-monitor-runs-in-place-from-rom-the-overlay-is-not-dropped)),
and the machine is in it whenever nothing else is running.

**Both consoles are peers.** Input is taken from the serial port and the
PS/2 keyboard, whichever has a byte; output goes to the serial port and
the screen together. That is what makes the machine usable over a wire
before the keyboard is built and after it is, and it is why the M6 gate
can drive it from a testbench.

| Command | |
|---|---|
| `D [addr]` | Dump. Eight lines of sixteen bytes, hex and text. Carries on from the last dump if no address is given |
| `E addr bb bb ...` | Enter bytes |
| `U [addr]` | Unassemble sixteen instructions |
| `G addr` | Go. There is no coming back |
| `L dest len [flsH]` | Copy `len` bytes from the SPI flash to `dest`. `flsH` is the top sixteen bits of the flash address and defaults to `$1000`, which is offset `$100000` |
| `?` | The list |

Numbers are hexadecimal and unprefixed. A command letter is folded to
upper case; a blank line is not an error.

**`D` over `$FF00-$FFFF` really reads the I/O page**, and half of it has
side effects — a dump across `UART_DATA` pops the receive FIFO, one
across `PAL_DATA` advances the palette index. That is not a bug to fix.
It is the thing a monitor is for, and it is worth knowing before you
type the address.

### 7.1 The disassembler

There is **no 256-entry opcode table** in it and there must not be: the
primary page is `1 ooo dd ss` and `01 gg t dd b` all the way down, so
reading the fields costs a few hundred bytes where indexing every opcode
would cost more ROM than exists. The only tables are the mnemonics.

They are NUL-terminated strings rather than fixed-width slots, because
`PUSHW` is five characters and `MOV` is three and a slot wide enough for
the first wastes it on all the others. Where a whole operand is a
constant — `JMP [X]`, `MOVW SP,Y` — it lives in the string too and the
decode for that case disappears.

A branch prints its **target**, not its displacement. The displacement
is the one thing you can always work out for yourself and never want to.

It does not check that an encoding is legal. Page 2 has 22 reserved
second bytes which trap on the real machine; here they print as `???`
with the byte. A disassembler that refused to show you the byte you are
looking at would be worse than one that guessed, because the reason you
are looking is usually that something has already gone wrong.

### 7.2 Scancodes

Set 2 arrives raw — `$E0` prefixes, `$F0` break codes and all — because
that is what §4.3's hardware promised and because a table in ROM is
cheaper than a state machine in gates. The translation is a 128-byte
map indexed by the make code, plus a 21-entry list of the keys shift
does something to that is not a case change. Letters are handled by
clearing bit 5, which is 42 bytes saved against a second full map.

Break codes are swallowed except for the two shifts, which is what makes
auto-repeat work with no effort at all.

---

## 6. Interrupt sources

| Source | Vector | Notes |
|---|---|---|
| Raster compare | IRQ | `VID_RCMP` match |
| Vertical blank | IRQ | Start of vblank |
| Keyboard data available | IRQ | `KBD_CTRL` bit 4 enables it. **BASIC uses this** |
| Break button, `SW[0]` | NMI | Debounced, edge-triggered |

`SW[0]` is wired to `NMI` as a **break button**. Under the boot ROM a
hung program lands in the monitor with all of its state intact; under
BASIC — whose relocation turns the overlay off, taking the ROM's
handler with it — BASIC installs its own NMI handler, which sets the
break flag the interpreter polls, so the button is the same break as
Ctrl+Pause and the serial Ctrl-C. An NMI
pushes `PC` and `F` and changes nothing else. It is the escape hatch that
makes a machine with no other input device debuggable, and it matters
more since [D40](01-decisions.md#d40--the-hardware-loader-is-a-build-option-and-it-is-off)
made the loader's `HALT` a build option.

**It needs the line low for two continuous milliseconds, and the pin
needs a pull-up** — both, and for the same reason. Nothing on the board
holds pin 18, a floating iCE40 input oscillates, and a button that fires
on the first low sample turns that into a continuous NMI. The counter
resets on any high sample so noise never accumulates, and saturates so
one press gives one interrupt. This was found on the board and could not
have been found anywhere else.

**The timer and the UART do not raise interrupts.** This table listed
both for a long time and the hardware never agreed: `cool8_soc.v:468`
drives the core with `irq | vid_irq | ps2_irq`, and the machine
mirrors it. `TMR_CTRL` bit 4 and the UART's status bits exist, but
nothing carries either to the core, and `irq` is an external SoC input
that nothing on the board drives. **The keyboard is not in that
position** — `ps2_irq` is right there in the same expression — which is
why BASIC's handler is entered on a keypress but still has to drain the
UART on the vblank tick. Software wanting either must poll it
**from** another interrupt — which is what `sw/basic.bas` does, taking
the vertical blank as its tick the way the C64 takes the 60 Hz jiffy
IRQ and the BBC its 100 Hz one.

All IRQ sources OR together into the core's single `irq` input. The
handler reads the per-peripheral status registers to find the cause.
This is the smallest arrangement and it is what an 8-bit machine should
do; a priority encoder can come later if the handler's dispatch cost
ever matters.

---

## 8. Mass storage: the filesystem

What `SAVE`, `LOAD`, `DIR`, `ERA`, `COMPACT` and `DRIVE` talk to. The
7 MB of flash above the `$100000` hardware floor (§4.8) is **sixteen
volumes of 448 KB, mounted one at a time by number** — `DRIVE n` in
BASIC. Sixteen drives with a disk in each, or one drive and a box of
sixteen disks: at one mounted volume the two readings are the same
code, and
[D54](01-decisions.md#d54--storage-stays-sixteen-mounted-volumes-the-disk-box-was-considered-and-declined)
records why the machine does not have to choose.

Two things sit **below** this layer and read the flash raw: the
monitor's `L` command, which copies bytes from any offset, and the boot
ROM's autoboot, which walks volume 0's directory looking for `BOOT.BIN`
with its own few lines of code ([`sw/boot.asm`](../sw/boot.asm)) rather
than linking the filesystem into a 4 KB ROM. Autoboot reads, only —
mounting, allocating and writing all live in the OS.

**The format is written twice, on purpose.**
[`sw/fs.asm`](../sw/fs.asm) is the machine side;
[`tools/cool8disk.py`](../tools/cool8disk.py) is the same filesystem
implemented independently on the PC, enforcing the same only-clear-bits
flash rules so the tool cannot produce an image the machine could not
have. `sim/test_fs.py` is the gate that makes the two agree — change
either and it says so. This section is the human-readable copy; where
prose and gate disagree, the gate decides.

### 8.1 Geometry

A volume is 448 KB = 7 × 64 KB, so **every volume base is 64 KB
aligned**: `base = ($10 + drive × 7) << 16`, low sixteen bits zero. A
file starts on a 256-byte page, so the flash address of a file is

```
low = 0,  mid = start page low,  high = base high + start page high
```

— one 8-bit add, and 448 KB was chosen partly for it.

Inside a volume:

| Offset | | |
|---|---|---|
| `+$00000` | directory | one 4 KB sector: 256 entries of 16 bytes |
| `+$01000` | data | 110 sectors, 440 KB — files appended on 256-byte page boundaries |
| `+$6F000` | scratch | one 4 KB sector, `COMPACT`'s — see §8.2 |

A directory entry:

| Bytes | Field |
|---|---|
| 0–10 | name — 8.3, space padded, upper case |
| 11 | status: `$FF` free, `$00` deleted, `$80` volume label, else type |
| 12–13 | start, in 256-byte pages from the volume base |
| 14–15 | length in bytes — so a file is at most 64 KB, the whole address space |

### 8.2 Built around what NOR flash can do

Erase sets a 4 KB sector to `$FF`; programming can only clear bits
(§4.8). Everything about the format follows:

- **Creating a file** programs an entry that is still `$FF` — no erase,
  no read-modify-write, and **no 4 KB RAM buffer anywhere**, which is
  the whole reason this is not FAT.
- **Deleting one** clears its status byte to `$00`. One byte
  programmed, nothing erased.
- **Free space is the tail.** Files are appended; there is no
  allocation bitmap and no free list.
- **The free pointer is not stored** — a value that only increases
  cannot be rewritten in place — so `fs_mount` derives it by scanning
  the directory for the highest `start + length`. One sector read,
  always right, where a stored counter can drift.
- **An erased volume is an empty volume.** Format is erase, and there
  is no superblock to be missing or wrong.

`COMPACT` is the only operation that erases, and it is explicit. It has
to put a sector's contents somewhere before erasing underneath them,
and "somewhere" cannot be main RAM (the user's program) or VRAM (their
sprites), so it is the volume's own last sector: gather, erase, copy
back. Slow, and 4 KB of every volume — and the reason a deleted file
costs nothing until the space is asked for back.

### 8.3 The host side

`icesprog -w disk.img` writes a whole 8 MB image to the board;
[`tools/cool8disk.py`](../tools/cool8disk.py) builds and reads one on
the PC — `format`, `add`, `get`, `del`, `dir`, `compact`, one volume at
a time. `tools/cool8run.py --flash disk.img` hands the same image to
the emulated machine, so a disk prepared on the PC is tested without a
board. What the tool does not yet have is volume-to-volume copy or
import/export of a single 448 KB volume image; both are additive if
they are ever wanted.
