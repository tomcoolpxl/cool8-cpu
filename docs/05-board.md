# 05 — Board, pinout and external hardware

Target board: **iCESugar v1.5** (MuseLab), Lattice **iCE40UP5K-SG48**.

Pin numbers below are taken from the board's own constraint files
(`wuxx/icesugar`, `src/common/io.pcf` and `src/basic/verilog/vga_pong/pong.pcf`).

---

## 1. Board resources

| | |
|---|---|
| FPGA | iCE40UP5K-SG48, 5280 LUT4 |
| Block RAM (EBR) | ~120 Kbit (~15 KB), bitstream-initialisable |
| SPRAM | 4 × 256 Kbit = 128 KB, **not** bitstream-initialisable |
| PLL | 1 |
| Clock | 12 MHz on pin 35, supplied by the on-board iCELink debugger |
| Flash | 8 MB SPI |
| Debugger | iCELink (ARM Mbed DAPLink) — drag-and-drop bitstream, USB CDC serial, JTAG |
| Connectors | PMOD1, PMOD2, PMOD3 (8 signals each), PMOD4 (4 pins) |
| I/O voltage | 3.3 V LVCMOS. **Not 5 V tolerant.** |

---

## 2. The pin budget, and its two traps

### Trap 1 — PMOD1 overlaps the USB and serial pins

| PMOD1 pin | FPGA pin | Also is |
|---|---|---|
| `P1_1` | 10 | `USB_DP` |
| `P1_2` | 6 | `TX` (iCELink serial) |
| `P1_11` | 4 | `RX` (iCELink serial) |
| `P1_12` | 9 | `USB_DN` |
| `P1_3` | 3 | — free |
| `P1_4` | 48 | — free |
| `P1_9` | 47 | — free |
| `P1_10` | 2 | — free |

Using PMOD1 as a whole PMOD costs you the USB serial console, which is
how programs get loaded. **Only the four free pins get used.**

### Not a trap — the SPI flash pins are free after configuration

Pins 14–17 go to the 8 MB configuration flash and are not on any header,
but the iCE40 releases them to user logic once `CDONE` goes high. That
makes the flash usable as mass storage at runtime at no cost to the PMOD
budget — see [04-system.md §4.8](04-system.md#48-spi-flash--fe88).

The design must not drive them during configuration; `nextpnr` and
`icepack` handle that, since user logic only comes alive after `CDONE`.

### Trap 2 — PMOD4 is the four tactile switches

`P4_1…P4_4` are pins 21, 20, 19, 18, which are `SW[3]…SW[0]`. Fine as
buttons, unavailable as a PMOD.

### The result

The 12-bit VGA PMOD takes all of PMOD2 plus six of the eight PMOD3
signals. What's left is exactly enough, and no more:

| Signal | FPGA pin | Where |
|---|---|---|
| `PS2_CLK` | 27 | `P3_3` |
| `PS2_DAT` | 25 | `P3_4` |
| `AUDIO_L` | 3 | `P1_3` |
| `AUDIO_R` | 48 | `P1_4` |
| spare | 47, 2 | `P1_9`, `P1_10` |

---

## 3. Full pin assignment

The live constraint file is [`board/icesugar.pcf`](../board/icesugar.pcf)
and it carries only the pins `cool8_top` currently has a port for —
`nextpnr` rejects a constraint for a port that does not exist, so VGA,
PS/2, audio and the buttons are added to it as their milestones arrive.
What follows is the whole map, which is the thing to check against when
adding one.

```
# clock
set_io clk        35

# VGA — MuseLab PMOD-VGA on PMOD2 + PMOD3
set_io vga_r[3]   36     # P2_9
set_io vga_r[2]   38     # P2_10
set_io vga_r[1]   43     # P2_11
set_io vga_r[0]   45     # P2_12
set_io vga_g[3]   23     # P3_9
set_io vga_g[2]   26     # P3_10
set_io vga_g[1]   28     # P3_11
set_io vga_g[0]   32     # P3_12
set_io vga_b[3]   37     # P2_4
set_io vga_b[2]   42     # P2_3
set_io vga_b[1]   44     # P2_2
set_io vga_b[0]   46     # P2_1
set_io vga_hs     34     # P3_1
set_io vga_vs     31     # P3_2

# PS/2 keyboard — via level shifter
set_io ps2_clk    27     # P3_3
set_io ps2_dat    25     # P3_4

# audio — sigma-delta, via RC filter
set_io audio_l     3     # P1_3
set_io audio_r    48     # P1_4

# iCELink USB serial console — also carries the hardware loader
set_io uart_rx     4
set_io uart_tx     6

# SPI configuration flash, reused as storage after CDONE
set_io flash_cs   16
set_io flash_sck  15
set_io flash_mosi 17
set_io flash_miso 14

# buttons and LED
set_io sw[0]      18     # NMI break button — debounced, edge-triggered
set_io sw[1]      19
set_io sw[2]      20
set_io sw[3]      21
set_io led_r      40
set_io led_g      41
set_io led_b      39
```

**To verify before trusting the colour ordering:** the official demo
names the red signals `vga_R`, `vga_R1`, `vga_R2`, `vga_R3` on pins
45, 43, 38, 36, without stating which is the most significant bit. The
assignment above assumes 45 is bit 0. Check against the PMOD-VGA
schematic, or just display a horizontal ramp and look at the monitor —
if the ramp is scrambled, reverse the order.

### 3.1 The two facts a first bitstream guessed at

- **Which of pins 4 and 6 the FPGA transmits on — settled, correct.**
  The board's own file calls 6 `TX` and `board/icesugar.pcf` reads that
  as the FPGA's transmit. A `PING` on the real board answers, which it
  could not do if they were swapped.
- **LED polarity — still a guess.** `cool8_top` drives the pins low to
  light them, assuming the common-anode wiring these boards normally
  use. **This is not readable over the wire**: `$FE03` reads back what
  was written to it whichever way the pins go, so the only instrument
  that can settle it is an eye on the board.

  The test is free, because the boot ROM ends by writing `$01`:

  | What you see after a reset | Verdict |
  |---|---|
  | Blue | `LED_ACTIVE_LOW = 1` is right |
  | Yellow (red + green) | It is backwards — flip it and rebuild |

  Blue against yellow rather than lit against dark, because "dark" is
  also what a board that never ran looks like.

### 3.2 No reset button

There is no reset pin and none of `SW[0..3]` is wired to one.
`cool8_top` makes its own reset from a counter that stops at all-ones —
iCE40 flip-flops leave configuration at zero, so it holds the machine
down for 4096 clocks, 341 µs, and then never moves again.

A button would be nicer and is deliberately not there yet: one whose
polarity is guessed wrong holds the machine in reset forever and is
indistinguishable from a dead board. It costs nothing to add once there
is a board known to work.

---

## 4. External circuits to build

Two small circuits, five components each. Neither needs a PCB; a scrap
of stripboard is fine.

### 4.1 PS/2 level shifter

**This is not optional.** PS/2 clock and data are open-collector with
the pull-ups **inside the keyboard, tied to its own +5 V**. When the
keyboard is not driving, the line idles at 5 V. Connecting that to an
iCE40 pin means conducting through the ESD clamp diode every idle
period.

The standard bidirectional MOSFET shifter, one per line:

```
        +3.3V                              +5V
          │                                  │
         10k                                10k
          │            BSS138                │
   FPGA ──┼──────────────┐ D                 │
                         │                   │
                    G ───┴───────────────────┤   (gate to +3.3V)
                         │
                       S ┴──────────────────────── keyboard line
```

Gate to +3.3 V, source to the 5 V (keyboard) side, drain to the 3.3 V
(FPGA) side, 10 kΩ pull-up on each side to its own rail. Two of these,
one for `PS2_CLK` and one for `PS2_DAT`.

**The keyboard also needs 5 V at up to ~300 mA, and the PMOD `VCC` pins
on this board are 3.3 V.** Take 5 V from the board's USB VBUS or from a
separate supply, with grounds tied together.

PS/2 mini-DIN female, looking into the socket:

| Pin | Signal |
|---|---|
| 1 | DATA |
| 2 | *(not connected)* |
| 3 | GND |
| 4 | +5 V |
| 5 | CLK |
| 6 | *(not connected)* |

### 4.2 Audio output filter

One-bit sigma-delta straight off an FPGA pin, per channel:

```
   FPGA ──┬── 1k ──┬── 1k ──┬── 10µF ──┬──── tip (line out)
          │        │        │           │
          │      10nF     10nF        10k
          │        │        │           │
         GND      GND      GND         GND
```

Two RC stages at 1 kΩ / 10 nF (`fc = 1/(2πRC) ≈ 15.9 kHz` each), then a
coupling capacitor to strip the DC bias and a 10 kΩ drain resistor. The
sigma-delta noise sits up at 25 MHz, so this is more filtering than
strictly necessary and it keeps the treble.

Duplicate for the second channel. **Do not** connect headphones or a
speaker directly to an FPGA pin. For a speaker, feed this into a
PAM8302 (mono) or PAM8403 (stereo) module with its own supply and
decoupling.

---

## 5. Bill of materials

| Ref | Part | Qty | Notes |
|---|---|---|---|
| — | iCESugar v1.5 | 1 | Have it |
| — | MuseLab PMOD-VGA (12-bit) | 1 | Buy. Sold alongside the board. |
| — | VGA cable + monitor | 1 | Have it |
| — | PS/2 keyboard | 1 | Have it |
| Q1, Q2 | BSS138 (or a 2-channel BSS138 level-shifter breakout) | 2 | |
| R1–R4 | 10 kΩ | 4 | Level shifter pull-ups |
| R5–R8 | 1 kΩ | 4 | Audio filter, 2 per channel |
| R9, R10 | 10 kΩ | 2 | Audio bias drain |
| C1–C4 | 10 nF ceramic | 4 | Audio filter |
| C5, C6 | 10 µF electrolytic | 2 | Audio coupling — watch polarity |
| J1 | PS/2 mini-DIN 6 socket | 1 | |
| J2 | 3.5 mm stereo jack | 1 | |
| — | PAM8302 or PAM8403 module | 1 | Optional, for a speaker |

Everything except the VGA PMOD is a few euro of passives.

---

## 6. Toolchain

Fully open source, and wrapped in one script:

```bash
python tools/mkbit.py                    # yosys, nextpnr, icepack
```

It assembles the boot ROM and converts the font first — both are read
at elaboration, so `yosys` runs with `build/` as its working directory —
and constrains the design to 8.375 MHz, which `nextpnr` enforces rather
than reports.

**Measured, the whole machine placed and routed:**

| | |
|---|---|
| Logic cells | 4877 / 5280 — 92 % |
| EBR | 27 / 30 — boot ROM, font, palette, line buffers, sprites |
| SPRAM | 4 / 4 — 64 KB main RAM and 64 KB video RAM |
| DSP | 1 / 8 — `y × stride` for the pixel port |
| PLL | 1 / 1 |
| I/O | 20 / 39 |
| Timing | closes at 8.375 MHz, `sclk` Fmax 10.65 |
| Bitstream | 104 KB |

**The clock is 8.375 MHz and not 12, and the part decided that.** The
single PLL's reference is a pad, and on the SG48 that pad is pin 35 —
the one the board's 12 MHz arrives on. `nextpnr` will not place a PLL
whose pin is also an input, so the system clock has to be a division of
the 25.125 MHz the raster needs. Half of it does not close: 11.0 to 11.6
MHz across six placer seeds. A third of it does, with 33 % to spare. The
whole argument is
[D32](01-decisions.md#d32--the-system-clock-is-8375-mhz-a-third-of-the-pixel-clock).

The critical path is what
[D26](01-decisions.md#d26--the-system-clock-is-12-mhz-the-pixel-clock-is-decoupled)
said it would be: SPRAM read data, through the read mux and the
instruction decode, to the next state. D26's own 16.9 MHz figure was
measured on the core and two SPRAM alone; the assembled machine adds the
boot ROM's block mux and the I/O page's, and `nextpnr`'s result moves by
about 6 % across placer seeds.

**M5 did not leave it intact.** With the video engine in it is 37 levels
of logic and 87 ns, and it is the reason the machine runs at 8.375 rather
than 12.5625. It is logic depth rather than congestion — the seed spread
is under 6 % — and it is
[D23](01-decisions.md#d23--no-memory-address-register) showing up: the
core reads the opcode straight off the bus, so the byte and the decision
it drives share a cycle. Pipelining it is the open question in
[01-decisions.md](01-decisions.md).

Programming is drag-and-drop: the iCELink debugger enumerates as a mass
storage device, so copying `build/cool8.bin` onto it flashes the board.
The `icesprog` utility in the board's repository does the same from a
script, and there is a prebuilt `icesprog.win.exe` for Windows.

> **Do not use `icesprog -e`.** Whole-chip erase, not sector erase — it
> takes the bitstream with it. Also in
> [04-system.md §4.8](04-system.md#48-spi-flash--fe88), because that is
> where you would go looking for the flash commands.

Simulation: `iverilog` + `gtkwave`, or `verilator` for the
co-simulation against the reference emulator.

---

## 7. Sources

- [wuxx/icesugar](https://github.com/wuxx/icesugar) — board repository,
  `src/common/io.pcf` for the pin map
- [iCESugar README](https://github.com/wuxx/icesugar/blob/master/README_en.md)
- [MuseLab on Tindie](https://www.tindie.com/products/johnnywu/icesugar-fpga-development-board/)
- Lattice `FPGA-TN-02022` — iCE40 SPRAM usage guide
- Lattice `FPGA-TN-02052` — sysCLOCK PLL design usage guide

Both Lattice technical notes are mirrored in `doc/LatticeSemi/` in the
board repository.
