' An address is sixteen bits even when the expression that builds it
' would fit in eight.
'
' width() calls a literal one byte wide when it is under 256, so
' `PEEK(BASE + k)` with BASE below 256 took the byte path: R1 was never
' loaded with the address's high byte and XH carried whatever the
' previous statement happened to leave there. It read the right offset
' of the wrong page. POKE had the same fault and *wrote* there.
'
' Both hid for as long as every small constant in the system was an I/O
' register used bare -- `PEEK($FE70)` is a literal and takes the
' one-instruction path. It surfaced the moment a base below 256 was
' added to an index, when the filesystem's variables moved from $0100
' to $0074.
'
' The `x = big` lines are load-bearing: they leave a non-zero high byte
' in R1, which is what makes a wrong XH visible rather than accidentally
' correct.

CONST BASE = $007B

DIM k AS BYTE
DIM big AS CARD
DIM a AS INT
DIM b AS INT

big = $3412

' Write four bytes through a computed small address.
k = 0
DO WHILE k < 4
  a = big
  POKE BASE + k, 65 + k
  k = k + 1
LOOP

' Read them back the same way.
k = 0
a = 0
DO WHILE k < 4
  b = big
  a = a + PEEK(BASE + k)
  k = k + 1
LOOP

' And again through literal addresses, which have always been correct.
' The two must agree: if POKE wrote to the wrong page b stays 0, and if
' PEEK read from the wrong page a does.
b = PEEK($007B) + PEEK($007C) + PEEK($007D) + PEEK($007E)

END
