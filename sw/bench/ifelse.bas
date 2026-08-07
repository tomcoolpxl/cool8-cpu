' IF / ELSEIF / ELSE. 4 small, 3 middling, 3 large.
a = 0
FOR i = 1 TO 10
  IF i < 5 THEN
    a = a + 1
  ELSEIF i < 8 THEN
    a = a + 10
  ELSE
    a = a + 100
  END IF
NEXT i
END
