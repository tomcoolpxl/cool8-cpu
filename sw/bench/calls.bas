' BM6 -- nested loop and a call
SUB Nothing
END SUB

k = 0
DO
  k = k + 1
  l = 0
  DO
    l = l + 1
    Nothing
  LOOP WHILE l < 5
LOOP WHILE k < 1000
END
