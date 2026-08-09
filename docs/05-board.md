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

### Trap 0 — the flash comes out of configuration asleep, and the CPU must wake it

**Resolved on the bench: autoboot boots BASIC from flash on the board.**
The iCE40 leaves the SPI flash in deep power-down when it finishes
configuring, and a sleeping W25Q64 ignores every command except `$AB`.
`cool8_flash.v` now opens with the same two frames picosoc's
`spimemio.v` sends on every reset (states 0–3): **`$FF`** (exit
continuous-read mode, in case a previous master left the part there)
and **`$AB`** (release from power-down), each under its own chip
select, then ~490 µs of settling for tRES1 before anything else may
run. `sim/tb/cool8_flash_tb.v`'s model now **starts asleep** and
refuses everything but that wake-up, so a controller without it fails
in simulation instead of on a bench.

The investigation record below is kept because every wrong turn in it
cost a session, and each is the kind that gets repeated.

**Measured on the bench, not inferred.** The FPGA's user logic cannot
talk to the configuration flash at all — not reads, not writes:

| | result |
|---|---|
| `icesprog` reads offset 0 and `$100000` | correct data, both |
| The FPGA's *configuration* engine reads the flash | works — the design runs |
| `sim/test_flash.py`, `sim/test_monitor.py`'s "L then D" | pass |
| Monitor `L 4000 20` (read `$100000`) | **`FF FF FF …`** |
| Monitor `L 4100 20 0` (read `$000000`) | **`FF FF FF …`** |
| Monitor `W 4000 8 7000` (write `$700000`), read back with `icesprog` | **nothing arrived** |

Both those addresses hold known non-`$FF` data, so it is not a blank
region and not an addressing mistake. A write that leaves no trace rules
out MISO alone: **the FPGA is not driving CS, SCK or MOSI to the chip.**

Ruled out, each with evidence rather than argument:

- **The pin constraints.** `flash_cs 16`, `flash_sck 15`, `flash_mosi 17`,
  `flash_miso 14` are byte-identical to a working UP5K flash example
  ([damdoy/ice40_ultraplus_examples](https://github.com/damdoy/ice40_ultraplus_examples)
  `common/io.pcf`).
- **The read opcode.** `$03` with no dummy cycles, which a W25Q64
  supports.
- **The boot ROM.** A bitstream built from a commit predating the
  keyboard work behaves identically. The two bitstreams differ only in
  bytes `0x15A4C-0x19696`, which is EBR initialisation — every byte of
  logic and routing is the same.
- **The flash being left in a mode by `icesprog`** (deep power-down and
  the like): a power cycle does not change the behaviour.

**The board is not at fault, and this is proven rather than argued.**
Muse Lab's own `demo/picorv32.bin` — a 1 MB image, bitstream at 0 and
firmware padded out to `$100000` — was programmed onto this board with
the same `icesprog`, in the same jumper position, and it **runs**:

```
  ____  _          ____         ____
 |  _ \(_) ___ ___/ ___|  ___  / ___|
 | |_) | |/ __/ _ \___ \ / _ \| |
 |  __/| | (_| (_) |__) | (_) | |___
 |_|   |_|\___\___/____/ \___/ \____|
```

PicoSoC executes its firmware *out of the SPI flash*. So user logic can
reach this chip on this board, and what is broken is ours.

Also ruled out along the way, each on the bench:

- **The jumper.** Closed is the working position — the silkscreen reads
  `0 Prog Flash` / `1 Prog iCE`, and with it open the FPGA does not
  configure at all, even from a freshly written flash. It gates
  configuration, not runtime access.
- **`icesprog` versus drag-and-drop.** PicoSoC was programmed with
  `icesprog` and works, so the programming route is not the difference.
- **The pin assignment.** `icicle` in the vendor's own repo constrains
  `flash_io0` to 14 as an output and `flash_io1` to 17 as an input,
  which says our `flash_mosi 17` / `flash_miso 14` is backwards.
  Swapping them changed nothing — still `$FF` at every address — so it
  is not that either, and they were put back.

### What has been tried, and what it cost

**Still unsolved.** Recorded so the same ground is not covered twice.

| tried | result |
|---|---|
| `flash_mosi`/`flash_miso` swapped to 14/17 | no change |
| `SB_IO` pads with explicit enables, as picosoc | no change |
| `/WP` and `/HOLD` constrained and driven high | no change |
| A minimal top: damdoy's `spi_master.v`, an LED, nothing else | flash silent |
| The same, with `SB_IO` and the pin fix as well | flash silent |
| **A minimal top around picosoc's `spimemio.v`** | **reads the flash** |
| picosoc's `$FF`+`$AB` wake-up added to `cool8_flash.v` | **BASIC boots from flash** |

**That last row localises the fault.** `spimemio.v` unmodified, its
`SB_IO` instantiation copied from `icesugar.v`, all four io lines, `csb`
and `clk` as plain outputs, one word read from `$100000` — and the LED
goes solid. So the pads, the constraints, the pin numbers, the clock and
the board are all fine, and **what is wrong is inside
`rtl/soc/cool8_flash.v`**: the command sequence it puts on the wire.

Do not build another bring-up test on `damdoy/ice40_ultraplus_examples`.
It targets the Lattice breakout board, needs jumpers this board does not
have, and its `spi_master.v` never drives `SPI_SS` at all — yosys
reports the port as undriven. Two rounds went into it. picosoc is the
only design confirmed to read this flash on this board, so it is the
reference.

**`$AB` was the answer, and it was nearly thrown away.** damdoy's
example carries the wake-up as dead code — its comment says "not needed
when only reading", which is true only on a board where nothing put the
part to sleep — and a test built on that example produced a false
negative that discredited the right theory for a round. picosoc sends
`$FF` then `$AB` on every reset and demonstrably works here. The
lesson, worth the price paid for it: **when one demo works and another
does not, diff the working one.** The wrong example cost two bench
rounds; reading `spimemio.v`'s state machine end to end found the fix
in one.

### Two facts about this board that cost time to learn

**`icesprog` writing flash *does* reconfigure the FPGA.** No replug is
needed; the new bitstream is running by the time the write returns. The
opposite was assumed for most of a session and every test was preceded
by an unnecessary power cycle.

**The RGB LED is the design's.** A blink seen right after programming is
the bitstream that was just written, not the debugger — which follows
from the line above, and was briefly and wrongly written down here as
the opposite. The two facts are one fact: `icesprog` reconfigures, so
what the LED does after a write is *always* the new design.

### The gap that let this through

`sim/tb`'s flash model answered a bare `$03` immediately, because a
model only refuses what it was written to refuse — and the reader had
never been run against real silicon: [06-roadmap.md](06-roadmap.md)'s
bring-up table has no flash read in it, and the reader is ticked off
with LUT counts, which is synthesis. **Closed**: the model now powers up
asleep, ignores everything but `$AB`, and the testbench waits out the
controller's wake-up before its first request — 65 checks, and a
controller that skips the wake-up fails the first one.

Of the changes shotgunned before the cause was found, the honest
accounting: the **pin swap was a real second bug** — `flash_mosi 17` /
`flash_miso 14` was backwards against both vendor designs, and with the
pins crossed no wake-up could ever have helped. The `SB_IO` pads and
`/WP`/`/HOLD` driven high match picosoc and stay, though neither was
proven individually necessary. The four-clocks-per-bit shifter stays for
margin; it halves SCK to 2.09 MHz, so a 64 KB load is ~250 ms instead
of ~125.

Until it is, treat the flash as **write-only from the host**: `icesprog`
puts data there and the FPGA's configuration engine reads the bitstream,
but nothing the CPU runs can see it. Autoboot therefore cannot work on
this board — it walks 256 directory entries of `$FF`, finds no
`BOOT.BIN`, and falls through to the monitor, which is exactly what it
is specified to do when the flash is blank.

> **This was never verified on hardware before.** [06-roadmap.md](06-roadmap.md)'s
> bring-up table checks `--ping`, `SYSSTAT`, `UART_DIV`, `CPUDIV` and
> `LED` — no flash read among them — and lists the flash *write* path as
> not yet exercised. The reader is ticked off with LUT counts, which is
> synthesis and simulation. `sim/test_autoboot.py` passes on the
> emulator. None of that is a board.

### Not a trap — the SPI flash pins are free after configuration

Pins 14–17 go to the 8 MB configuration flash and are not on any header,
but the iCE40 releases them to user logic once `CDONE` goes high. That
makes the flash usable as mass storage at runtime at no cost to the PMOD
budget — see [04-system.md §4.8](04-system.md#48-spi-flash--fe88).

The design must not drive them during configuration; `nextpnr` and
`icepack` handle that, since user logic only comes alive after `CDONE`.

### Trap 2 — PMOD4 is the four tactile switches

`P4_1…P4_4` are pins 21, 20, 19, 18, which are `SW[3]…SW[0]`. Fine as
buttons, unavailable as a PMOD. **`SW[0]` is spoken for** as the NMI
break button, and it needs `set_io -pullup yes` — see above.

### The result

The 12-bit VGA PMOD takes all of PMOD2 plus six of the eight PMOD3
signals. What's left is exactly enough, and no more:

| Signal | FPGA pin | Where |
|---|---|---|
| `PS2_CLK` | 27 | `P3_3` |
| `PS2_DAT` | 25 | `P3_4` |
| `audio` | 3 | `P1_3` — one pin, mono, 1-bit sigma-delta |
| spare | 48, 47, 2 | `P1_4`, `P1_9`, `P1_10` |

**Sound is one pin, not two.** [D41](01-decisions.md#d41--the-sound-engine-is-one-datapath-walked-eight-times-not-four-dividers)'s
engine mixes its eight voices to a single signed sample, so a stereo pair
would mean two mixers rather than two pins. `P1_4` is free again.

**`SW[0]` is an input now, with a pull-up.** Pin 18, `P4_4`, the break
button of [§6](04-system.md). The pull-up is in the `.pcf` and is not
optional — nothing on the board holds that pin, a floating iCE40 input
oscillates, and the first version of this produced a machine taking NMIs
continuously. See [D40](01-decisions.md#d40--the-hardware-loader-is-a-build-option-and-it-is-off).

---

## 3. Full pin assignment

The live constraint file is [`board/icesugar.pcf`](../board/icesugar.pcf)
and it carries only the pins `cool8_top` currently has a port for —
`nextpnr` rejects a constraint for a port that does not exist, so audio
and the buttons are added to it as their milestones arrive. Everything
else below is now in it. What follows is the whole map, which is the
thing to check against when adding one.

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

# audio — one pin, mono, sigma-delta via the RC filter of section 4.2
set_io audio       3     # P1_3

# SW[0] — the break button, NMI. The pull-up is not optional; see 4.3
set_io -pullup yes sw0 18

# iCELink USB serial console — also carries the hardware loader
set_io uart_rx     4
set_io uart_tx     6

# SPI configuration flash, reused as storage after CDONE
set_io flash_cs   16
set_io flash_sck  15
set_io flash_mosi 17
set_io flash_miso 14

# buttons and LED
# SW[1..3] are unassigned; cool8_top has no port for them and nextpnr
# rejects a constraint for a port that does not exist.
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

  The test is free, because the boot code writes `$01` on its way into
  the monitor:

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

### 4.2 Audio output filter — and it is the whole DAC

**There is no DAC on the board and none to buy.** The FPGA pin does what
every FPGA pin does: 0 V or 3.3 V, nothing between. `cool8_snd`'s
first-order sigma-delta modulator runs at the full 8.375 MHz and puts the
carry of an 8-bit accumulator on the pin, so the *average* of that pin
over any short window is the sample. The resistors and capacitors below
take that average. **They are the digital-to-analogue conversion**, and
until they are built the pin is a square wave carrying no audible signal.

One pin, mono — the engine mixes its eight voices to a single signed
sample, so a second channel would be a second mixer rather than a second
pin ([D41](01-decisions.md#d41--the-sound-engine-is-one-datapath-walked-eight-times-not-four-dividers)).
`P1_4` is free.

```
   P1_3 ──┬── 1k ──┬── 1k ──┬── 10µF ──┬──── tip (line out)
          │        │        │          │
        10nF     10nF      ---        10k
          │        │                   │
         GND      GND                 GND
```

Two RC stages at 1 kΩ / 10 nF — `fc = 1/(2πRC) ≈ 16 kHz` each — which is
above anything the machine can play and two and a half decades below the
switching rate, so the carrier is gone and the treble is not.

**The coupling capacitor is not optional.** The modulator cannot emit a
negative voltage, so the sample is offset to the middle of the range and
**silence sits at 1.65 V**, not at zero. The series capacitor is what
turns that into 0 V at the far end, which is what a line input expects.
The 10 kΩ drains it when nothing is plugged in.

**Do not** connect headphones or a speaker directly to an FPGA pin —
that is a short across an output driver. For a speaker, feed the filter
into a PAM8302 module with its own supply and decoupling.

If it sounds thin, raise the capacitors to 22 nF and lose a little top
end for more carrier rejection. If it hisses, the corner is too high or
the ground return is poor.

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
| R5, R6 | 1 kΩ | 2 | Audio filter — **this is the DAC**, see §4.2 |
| R7 | 10 kΩ | 1 | Audio bias drain |
| C1, C2 | 10 nF ceramic | 2 | Audio filter |
| C3 | 10 µF electrolytic | 1 | Audio coupling — watch polarity |
| J1 | PS/2 mini-DIN 6 socket | 1 | |
| J2 | 3.5 mm jack | 1 | Mono; the engine has one channel |
| — | PAM8302 module | 1 | Optional, for a speaker |

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
| Logic cells | 5022 / 5280 — 95 % |
| EBR | 28 / 30 — boot ROM, font, palette, line buffers, sprites, sound, two FIFOs |
| SPRAM | 4 / 4 — 64 KB main RAM and 64 KB video RAM |
| DSP | 1 / 8 — `y × stride` for the pixel port |
| PLL | 1 / 1 |
| I/O | 28 / 39 — `audio` and `sw0` are the two M7 added |
| Timing | closes at 8.375 MHz, `sclk` Fmax 11.2 |
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

**`icesprog` ships inside the OSS CAD Suite**, at `bin/icesprog` beside
`yosys` and `iverilog` — not in a separate install of its own, and not
only in the board's repository. So it is found the same way every other
tool here is: `OSS_CAD_SUITE` pointing at the suite root, or the suite's
`bin` on `PATH`. `tools/flash.py` resolves it through `sim/cosim.py`'s
`_tool`, which also puts `bin` and `lib` on `PATH` so the DLLs beside
the executable load.

> A bare `which icesprog` in a shell that has not set that up answers
> "no", and **"not on `PATH`" is not "not installed"**. Say which one
> you actually checked.

It is the only way to reach a flash *offset*; the drive takes the
bitstream and nothing else. That is why writing BASIC to volume 0 needs
it and programming the FPGA does not.

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
