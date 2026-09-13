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

## The backdrops

Each level has a horizon along the bottom of the field, cut from
published pixel art -- the arcade has none. Downloaded from
OpenGameArt on 13 September 2026, with the owner's consent:

| file | work | author | licence |
|---|---|---|---|
| `backdrops/chikyuu_16_edge_0.png` | [Planet Orbit Background](https://opengameart.org/content/planet-orbit-background) | ArthCarvalho | [OGA-BY 3.0](https://opengameart.org/content/oga-by-30-faq) |
| `backdrops/green_nebula_arne16_-_512x512_0.png` | [Nebula Arne16](https://opengameart.org/content/nebula-arne16), an Arne16 edit of Screaming Brain Studios' Green Nebula 4 | zwonky | CC0 |
| `backdrops/rocky-far-mountains_0.png` | [Rocky desert landscape (layered, looping)](https://opengameart.org/content/rocky-desert-landscape-layered-looping), from Quantiset's [Mars background](https://opengameart.org/content/mars-background-pixel-art) (CC0) | Emcee Flesher | CC0 |
| `backdrops/stars-and-planet-alt2_0.png`, `backdrops/planet-only-alt2-alpha.png` | [Space Junkyard Environment](https://opengameart.org/content/super-dead-space-gunner-merc-redux-space-junkyard-environment) | Emcee Flesher; the planet an enhanced image by Gabriel Fiset (CC-BY) based on images courtesy of NASA/JPL-Caltech/SwRI/MSSS; the nebula after Daniel Cook (CC-BY) | [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

The credits the two attribution licences ask for are shown in the game
and in [docs/14-demos.md](../../docs/14-demos.md).
