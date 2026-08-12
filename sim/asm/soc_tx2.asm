; soc_tx2.asm -- three bytes into a transmitter with room for two.
;
; What must happen when a program writes UART_DATA with no room left is
; that the *late* byte is dropped and the one already accepted still
; comes out. A transmitter that let a late write displace a byte it had
; already taken would reorder a program's output whenever something else
; was on the wire, which is the kind of fault that only appears under
; load and never in a quiet test.
;
; The two polls are what make that deterministic. UART_STAT bit 1 says
; there is room in the holding register, not that the wire is idle -- and
; when this starts, the wire is still carrying the loader's own reply to
; the GO that launched it. So: wait for room, hand over $A1; wait again,
; which cannot succeed until $A1 has left for the wire; hand over $A2,
; and then write $A3 into a register that is certainly full.
;
; The wire must carry $A1 then $A2, and nothing else.

        .org  $0400

; Register addresses from sw/io.asm, generated from the RTL ([D67]).
        .include "io.asm"
UARTS   = UART_STAT
UARTD   = UART_DATA

w1:     LD    R1,[UARTS]
        AND   R1,#$02
        BEQ   w1
        MOV   R0,#$A1
        ST    [UARTD],R0

w2:     LD    R1,[UARTS]
        AND   R1,#$02
        BEQ   w2
        MOV   R0,#$A2
        ST    [UARTD],R0        ; accepted -- $A1 has gone to the wire
        MOV   R0,#$A3
        ST    [UARTD],R0        ; no room, and the wire is busy: dropped
        HALT
