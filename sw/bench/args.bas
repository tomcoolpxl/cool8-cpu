' Several parameters, and a call in an expression position.
r = 0

SUB Add3(x AS INT, y AS INT, z AS INT)
  r = r + x * 100 + y * 10 + z
END SUB

Add3(1, 2, 3)
Add3(4, 5, 6)
END
