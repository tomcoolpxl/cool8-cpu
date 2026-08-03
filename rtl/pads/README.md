# rtl/pads

ASIC pad wrapper: the three-phase bus multiplexer that maps the
core's memory interface onto TinyTapeout's 24 pins.

See docs/03-microarchitecture.md section 5. `tt_um_cool8.v` is the
TinyTapeout submission top level.

Verified at instruction level against a behavioural 74HC573 pair and an
asynchronous SRAM — `python sim/cosim.py bus`. The end-to-end bus-grant
load path, where an external agent drives the merged strobes, is M8.
