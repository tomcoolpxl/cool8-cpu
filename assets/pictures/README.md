# The picture drive's originals

`demos/slides.act` (SLIDES, on the CoolAction menu) shows every `.PIC`
on drive 10, the picture drive. The pictures are the classic
image-processing test set, and **this directory holds them only on a
machine that has fetched them** -- `.gitignore` keeps everything here
but this file out of the repository.

```bash
python tools/mkpics.py --fetch
python tools/mkdemos.py --no-shots
```

The first downloads whichever originals are missing, checks each against
the SHA-256 in `tools/mkpics.py`, and writes a `.pic` beside it: 256 of
the palette's 4,096 colours, mode 6's own bytes. The second builds the
disc with them on drive 10. Without them SLIDES still runs, and says on
the screen that the drive is empty.

| On the disc | Original | From | Rights |
|---|---|---|---|
| `MANDRILL.PIC` | `4.2.03.tiff`, 512 × 512 | [USC-SIPI](https://sipi.usc.edu/database/database.php?volume=misc) | unknown |
| `PEPPERS.PIC` | `4.2.07.tiff`, 512 × 512 | [USC-SIPI](https://sipi.usc.edu/database/database.php?volume=misc) | unknown |
| `PARROTS.PIC` | `kodim23.png`, 768 × 512 | [Kodak Photo CD set](https://r0k.us/graphics/kodak/) | reported released for unrestricted use |
| `PAINTED.PIC` | `kodim15.png`, 768 × 512 | [Kodak Photo CD set](https://r0k.us/graphics/kodak/) | reported released for unrestricted use |

**Why they are not committed.** The USC-SIPI database
[says](https://sipi.usc.edu/database/copyright.php) it does not hold the
copyright on most of its images and cannot grant permission for them,
and for the miscellaneous volume that the Mandrill and the Peppers come
from, it says the sources and the copyright status are unknown. This
repository is public. The Kodak pictures are safer, but one rule for the
whole drive is simpler than two, and the build does not need them.

**What is deliberately not here: Lena** (USC-SIPI 4.2.04). Its subject
asked for it to be retired, USC-SIPI has removed it, and IEEE stopped
accepting papers that use it in 2024.

[D103](../../docs/01-decisions.md) has the argument for the file
format and the drive; [14-demos.md](../../docs/14-demos.md) describes SLIDES.
