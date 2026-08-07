' The Byte sieve. 1899 primes below 8190.
CONST SIZE = 8190
DIM flags(SIZE) AS BYTE

c = 0
i = 0
DO
  flags(i) = 1
  i = i + 1
LOOP WHILE i < SIZE + 1

i = 0
DO
  IF flags(i) <> 0 THEN
    p = i + i + 3
    j = i + p
    DO WHILE j < SIZE + 1
      flags(j) = 0
      j = j + p
    LOOP
    c = c + 1
  END IF
  i = i + 1
LOOP WHILE i < SIZE + 1
END
