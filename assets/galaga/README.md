# GALAGA's art

## The arcade's sprites and text

Ripped from arcade Galaga (Namco, 1981). The owner's hobby port, with no
users; the sheets are in the repository by the owner's decision, as
Ms. Cool-Man's and Arkanoid's are. Fetched on 13 September 2026 from the
GitHub copies of The Spriters Resource's two arcade Galaga sheets,
because the site itself stands behind a bot check:

| file | sheet | from |
|---|---|---|
| `arcade_general_sprites.png` | "General Sprites", the expanded version, ripped by 125scratch, xdonthave1xx and Goemar | [BlazorGuy/BlazorGalaga](https://github.com/BlazorGuy/BlazorGalaga) `BlazorGalaga/wwwroot/Assets/spritesheet.png` |
| `arcade_general_sprites_old.png` | "General Sprites", the older version (The Spriters Resource asset 26482), by xdonthave1xx | [rokcoder-qb64/galaga](https://github.com/rokcoder-qb64/galaga) `resources/26482.png` |
| `arcade_rotations.png` | the same art repacked, with the fighter's full rotation | rokcoder-qb64/galaga `resources/Galaga.png` |
| `arcade_screens_text.png` | "Screens and Text", ripped by 125scratch | rokcoder-qb64/galaga `assets/text.png` |

`tools/mkgalaga.py` cuts everything the game draws from these; the only
change it makes to a pixel is the machine's, 24-bit colour to 12.

## The backdrops, which are gone

Each level once had a horizon along the bottom of the field, cut from
published pixel art. The arcade has none, and at the owner's word they
were taken out again (D120): the field is the arcade's black with its
stars. The pictures were deleted with them, and nothing here needs a
credit any more.
