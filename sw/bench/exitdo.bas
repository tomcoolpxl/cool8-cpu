' EXIT DO leaves the innermost loop only.
a = 0
b = 0
DO
  b = b + 1
  DO
    a = a + 1
    IF a > 20 THEN EXIT DO
  LOOP WHILE a < 100
  IF b > 2 THEN EXIT DO
LOOP WHILE b < 100
END
