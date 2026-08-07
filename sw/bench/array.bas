' BM7 -- an array element in the inner loop
DIM m(16)
k = 0
DO
  k = k + 1
  l = 0
  DO
    l = l + 1
    m(l) = k
  LOOP WHILE l < 5
LOOP WHILE k < 1000
a = m(5)
END
