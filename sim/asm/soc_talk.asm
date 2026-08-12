; soc_talk.asm -- transmit $80, $81 ... $FF and round again, as fast as
; the wire will take it.
;
; This exists to put the shared transmitter under contention: while it
; runs, cool8_soc_tb sends a frame and requires the loader's reply to get
; out without one of these bytes being lost or corrupted. Every value has
; bit 7 set, so a reply is unmistakable in the stream and a dropped byte
; shows up as a gap in a sequence rather than as a byte that is merely
; unexpected.

        .org  $0400

; Register addresses from sw/io.asm, generated from the RTL ([D67]).
        .include "io.asm"
UARTS   = UART_STAT
UARTD   = UART_DATA

        MOV   R2,#$80

tx:     LD    R1,[UARTS]
        AND   R1,#$02
        BEQ   tx
        ST    [UARTD],R2
        ADD   R2,#$01
        OR    R2,#$80           ; $FF wraps to $80, not to $00
        BRA   tx
