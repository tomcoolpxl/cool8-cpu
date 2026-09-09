#!/usr/bin/env python3
"""tools/build_pascal_examples.py -- Create and add UCSD Pascal example programs.

Adds:
- HELLO.TEXT: Interactive greeting and welcome
- SIEVE.TEXT: Byte Sieve of Eratosthenes benchmark
- HANOI.TEXT: Recursive Towers of Hanoi
- MANDEL.TEXT: Fixed-point Mandelbrot set rendering
- GUESS.TEXT: Interactive number guessing game
- FACT.TEXT: Factorial and Fibonacci calculation
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "sim"))

import cool8disk as disk
import harness as H
from ucsd_disk import UCSDVolume, encode_ucsd_text, KIND_TEXT

EXAMPLES = {
    "HELLO.TEXT": """\
PROGRAM HELLO;
VAR
  NAME: STRING;
BEGIN
  WRITELN('*** Welcome to UCSD Pascal on COOL8 ***');
  WRITELN;
  WRITE('What is your name? ');
  READLN(NAME);
  WRITELN;
  WRITELN('Hello, ', NAME, '! Enjoy Pascal on the 8-bit COOL8 CPU!');
END.
""",

    "SIEVE.TEXT": """\
PROGRAM SIEVE;
CONST
  SIZE = 1000;
VAR
  FLAGS: ARRAY [0..SIZE] OF BOOLEAN;
  I, PRIME, K, COUNT, ITER: INTEGER;
BEGIN
  WRITELN('10 iterations of Sieve of Eratosthenes (size ', SIZE, '):');
  FOR ITER := 1 TO 10 DO
  BEGIN
    COUNT := 0;
    FOR I := 0 TO SIZE DO FLAGS[I] := TRUE;
    FOR I := 0 TO SIZE DO
      IF FLAGS[I] THEN
      BEGIN
        PRIME := I + I + 3;
        K := I + PRIME;
        WHILE K <= SIZE DO
        BEGIN
          FLAGS[K] := FALSE;
          K := K + PRIME;
        END;
        COUNT := COUNT + 1;
      END;
  END;
  WRITELN(COUNT, ' primes found.');
END.
""",

    "HANOI.TEXT": """\
PROGRAM HANOI;
VAR
  DISKS, MOVES: INTEGER;

PROCEDURE MOVETOWER(N, FROMPEG, TOPEG, USINGPEG: INTEGER);
BEGIN
  IF N > 0 THEN
  BEGIN
    MOVETOWER(N - 1, FROMPEG, USINGPEG, TOPEG);
    WRITELN('Move disk ', N, ' from peg ', FROMPEG, ' to peg ', TOPEG);
    MOVES := MOVES + 1;
    MOVETOWER(N - 1, USINGPEG, TOPEG, FROMPEG);
  END;
END;

BEGIN
  WRITELN('--- Towers of Hanoi ---');
  WRITE('Number of disks (1..6): ');
  READLN(DISKS);
  MOVES := 0;
  WRITELN;
  MOVETOWER(DISKS, 1, 3, 2);
  WRITELN;
  WRITELN('Completed in ', MOVES, ' moves.');
END.
""",

    "MANDEL.TEXT": """\
PROGRAM MANDEL;
CONST
  MAXITER = 30;
VAR
  X, Y, ITER, CX, CY, ZX, ZY, ZX2, ZY2, TEMP: INTEGER;
BEGIN
  WRITELN('--- Mandelbrot Set (COOL8 Pascal) ---');
  FOR Y := -12 TO 12 DO
  BEGIN
    CY := Y * 5;
    FOR X := -25 TO 14 DO
    BEGIN
      CX := (X * 7) DIV 2;
      ZX := 0;
      ZY := 0;
      ITER := 0;
      REPEAT
        ZX2 := (ZX * ZX) DIV 64;
        ZY2 := (ZY * ZY) DIV 64;
        TEMP := ZX2 - ZY2 + CX;
        ZY := (ZX * ZY) DIV 32 + CY;
        ZX := TEMP;
        ITER := ITER + 1;
      UNTIL (ZX2 + ZY2 > 256) OR (ITER = MAXITER);

      IF ITER = MAXITER THEN
        WRITE('*')
      ELSE IF ITER > 15 THEN
        WRITE('+')
      ELSE IF ITER > 8 THEN
        WRITE('.')
      ELSE
        WRITE(' ');
    END;
    WRITELN;
  END;
END.
""",

    "GUESS.TEXT": """\
PROGRAM GUESS;
VAR
  SECRET, GUESSVAL, TRIES: INTEGER;
BEGIN
  WRITELN('=== Number Guessing Game ===');
  SECRET := 42;
  TRIES := 0;
  REPEAT
    WRITE('Enter guess (1..100): ');
    READLN(GUESSVAL);
    TRIES := TRIES + 1;
    IF GUESSVAL < SECRET THEN
      WRITELN('Too low! Try higher.')
    ELSE IF GUESSVAL > SECRET THEN
      WRITELN('Too high! Try lower.');
  UNTIL GUESSVAL = SECRET;
  WRITELN('Congratulations! You found it in ', TRIES, ' tries!');
END.
""",

    "FACT.TEXT": """\
PROGRAM FACT;
VAR
  N, I: INTEGER;

FUNCTION FACTORIAL(N: INTEGER): INTEGER;
BEGIN
  IF N <= 1 THEN
    FACTORIAL := 1
  ELSE
    FACTORIAL := N * FACTORIAL(N - 1);
END;

FUNCTION FIB(N: INTEGER): INTEGER;
BEGIN
  IF N <= 1 THEN
    FIB := N
  ELSE
    FIB := FIB(N - 1) + FIB(N - 2);
END;

BEGIN
  WRITELN('--- Factorials and Fibonacci ---');
  WRITELN(' N    Factorial    Fibonacci');
  WRITELN('----------------------------');
  FOR I := 1 TO 7 DO
    WRITELN(I:2, FACTORIAL(I):12, FIB(I):12);
END.
"""
}


def build():
    vol_path = os.path.join(ROOT, "tools", "ucsd-psystem-vm", "disk-images", "system.vol")
    vol = UCSDVolume.load(vol_path)

    # Check which files already exist on system.vol
    existing_names = [f["name"] for f in vol.files]
    print(f"Initial files on system.vol: {existing_names}")

    # Overwrite existing example files or add new ones
    for fname, src in EXAMPLES.items():
        text_bytes = encode_ucsd_text(src)
        matched = False
        for f in vol.files:
            if f["name"].upper() == fname.upper():
                fb = f["first_block"]
                nb = f["next_block"]
                max_len = (nb - fb) * 512
                padded = text_bytes + b"\x00" * (max_len - len(text_bytes))
                vol.data[fb * 512 : nb * 512] = padded
                f["data"] = padded
                f["last_byte"] = 512 if len(text_bytes) % 512 == 0 else len(text_bytes) % 512
                matched = True
                break
        if not matched:
            vol.add_file(fname, text_bytes, KIND_TEXT)

    vol.save(vol_path)
    print(f"Updated system.vol with {len(vol.files)} total files.")

    # Now run mkpascal.py to package into demos.img
    import subprocess
    cmd = [sys.executable, os.path.join(ROOT, "tools", "mkpascal.py")]
    subprocess.run(cmd, check=True)
    print("Demos disk image updated with Pascal system & examples.")


if __name__ == "__main__":
    build()
