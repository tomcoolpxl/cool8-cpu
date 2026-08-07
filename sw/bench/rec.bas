' Recursion through stack parameters. 1+2+...+10 = 55.
total = 0

SUB Down(n AS INT)
  total = total + n
  IF n > 1 THEN
    Down(n - 1)
  END IF
END SUB

Down(10)
END
