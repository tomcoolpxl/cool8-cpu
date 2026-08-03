; soc_led.asm -- the shortest program that proves the CPU reaches the
; I/O page: write the LED register and stop. cool8_soc_tb loads this
; over the wire, sends GO, and watches the `led` pins.
;
; Assembled by sim/test_soc.py rather than checked in as bytes, so the
; program the CPU runs is the program in this file.

        .org  $0400

LED     = $FE03

        MOV   R0,#$06           ; green + blue
        ST    [LED],R0
        HALT
