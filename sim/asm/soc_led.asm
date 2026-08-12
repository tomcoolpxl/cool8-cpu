; soc_led.asm -- the shortest program that proves the CPU reaches the
; I/O page: write the LED register and stop. cool8_soc_tb loads this
; over the wire, sends GO, and watches the `led` pins.
;
; Assembled by sim/test_soc.py rather than checked in as bytes, so the
; program the CPU runs is the program in this file.

        .org  $0400

; The register addresses come from sw/io.asm, which tools/ioregs.py
; generates from the Verilog that decodes them. This file used to carry
; `LED = $FE03`, which is exactly the literal that goes on addressing
; the old page after the page moves ([D67]).
        .include "io.asm"

        MOV   R0,#$06           ; bit 2 red + bit 1 green; the ROM uses $01, blue
        ST    [LED],R0
        HALT
