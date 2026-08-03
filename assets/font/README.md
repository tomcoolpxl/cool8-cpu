# assets/font

**Spleen 8x16**, by Frédéric Cambus — <https://github.com/fcambus/spleen>,
BSD 2-clause, `LICENSE.spleen` alongside it.

Vendored rather than downloaded at build time, so a checkout builds
without a network. `tools/mkfont.py` turns the BDF into the 4 KB image
`cool8_rom` loads into eight EBR blocks: 256 glyphs of 8x16, one byte a
row, glyph *n* at offset *n* × 16.

The character set is **CP437**, mapped through Python's own codec.
Spleen covers 224 of the 256 codes; the 32 it does not are `$00-$1F`,
CP437's decorative smilies and card suits, which come out blank. If
those matter, any BDF of the same cell size drops in — `mkfont.py`
parses the bounding boxes rather than assuming them, and the font is one
argument.

```bash
python tools/mkfont.py assets/font/spleen-8x16.bdf -o sim/build/font.hex
```
