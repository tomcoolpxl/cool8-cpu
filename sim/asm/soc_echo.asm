; soc_echo.asm -- read a byte from the serial port and send it back.
;
; The point of it is that every byte makes the whole round trip: the
; loader's sniffer decides it is not part of a frame and forwards it, it
; lands in the receive FIFO, the CPU polls UART_STAT and pops UART_DATA
; through the I/O page, and pushes it back out through a transmitter it
; shares with the loader. Nothing in that chain is stubbed in
; cool8_soc_tb, and a byte that comes back is a byte that survived it.

        .org  $0400

; Register addresses from sw/io.asm, generated from the RTL ([D67]).
        .include "io.asm"
UARTS   = UART_STAT                 ; 0 rx available, 1 tx ready
UARTD   = UART_DATA

rx:     LD    R0,[UARTS]
        AND   R0,#$01
        BEQ   rx
        LD    R0,[UARTD]

tx:     LD    R1,[UARTS]
        AND   R1,#$02
        BEQ   tx
        ST    [UARTD],R0
        BRA   rx
