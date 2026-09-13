#!/usr/bin/env python3
"""MOTT's art: DawnLike's tiles cut into the machine's pattern banks, a
file of them for each theme of the dungeon, and the table that names them.

    python tools/mkmott.py           write assets/mott/ -- the .act, the theme files, a preview
    python tools/mkmott.py --check   everything there is what the sheets make
    python tools/mkmott.py --font    render the SDS 8x8 font into assets/mott/sds8x8.png

**The pictures are DawnLike's**, DragonDePlatino's 16 x 16 tileset drawn
for NetHack, on DawnBringer's sixteen-colour palette -- CC-BY 4.0, in
assets/dawnlike/ with its credits. Nothing is redrawn: every cell of the
dungeon is cut from those sheets, and the only change is the one the
machine makes, the palette's 24-bit colours to 12.

**A cell is 16 x 16, four of mode 2's tiles**, and mode 2's tiles have no
transparency. So a creature or an item cannot be laid over the floor on
the screen; it is laid over the floor *here*, and every theme -- a band of
the dungeon's depth, its floor, its walls, its stairs -- is a file of its
own: 32,768 bytes, the four pattern banks the attribute byte reaches.
The game streams the one for the level into VRAM on the stairs.

    bank 0   the font (ASCII 32-126), then the terrain: sixteen wall
             pieces by their neighbours, floor, corridor, the doors, stairs
    bank 1   the things, each on the floor, one picture an appearance
    bank 2   the creatures on the floor, frame 0
    bank 3   the same creatures, frame 1 -- DawnLike animates every one

**Colour is a bank of the palette**: DawnBringer's sixteen as they are
for what is in view, the same sixteen dimmed for what is remembered, and
the text in its own inks.

**The font is DawnLike's SDS 8x8**, a TrueType font whose glyphs are
drawn on an 8 x 8 grid: rendered at its own size every pixel is fully on
or off. It is rendered once, by --font, into sds8x8.png, and the build
reads that picture -- so a different FreeType cannot make the check fail.
"""

import io
import os
import sys
import warnings

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL = os.path.join(ROOT, "assets", "dawnlike")
OUT_DIR = os.path.join(ROOT, "assets", "mott")
OUT = os.path.join(OUT_DIR, "mott_art.act")
FONT_PNG = os.path.join(OUT_DIR, "sds8x8.png")
PREVIEW = os.path.join(OUT_DIR, "preview.png")

# DawnBringer's 16, as lospec publishes them. DawnLike's sheets carry
# them a unit or two off here and there; a pixel is its nearest.
DB16 = [0x140C1C, 0x442434, 0x30346D, 0x4E4A4E, 0x854C30, 0x346524, 0xD04648, 0x757161,
        0x597DCE, 0xD27D2C, 0x8595A1, 0x6DAA2C, 0xD2AA99, 0x6DC2CA, 0xDAD45E, 0xDEEED6]

# ------------------------------------------------------------ the themes
# A theme is a band of the dungeon: its floor, its walls, its stairs.
# Coordinates are (column, row) in 16-pixel cells of a sheet. A floor or
# a wall set is DawnLike's 7 x 3 autotile block; the floor is its middle,
# the wall pieces are read from the block by the legend in WALL_PIECE.
THEMES = [
    dict(name="halls", file="MTHEME0", depths="1-4",
         floor=(1, 7), wall=(0, 9), up=(0, 1), down=(1, 1)),
    dict(name="caverns", file="MTHEME1", depths="5-8",
         floor=(1, 22), wall=(0, 21), up=(4, 1), down=(5, 1)),
    dict(name="depths", file="MTHEME2", depths="9-12",
         floor=(1, 25), wall=(14, 48), up=(2, 1), down=(3, 1)),
]

# which piece of a wall block for a wall cell whose neighbours north,
# south, west and east are wall: the block's legend, rows 0-2 of
# Objects/Wall.png. A lone run end takes the straight piece.
WALL_PIECE = {
    (0, 0, 0, 0): (3, 0), (0, 0, 0, 1): (1, 0), (0, 0, 1, 0): (1, 0), (0, 0, 1, 1): (1, 0),
    (0, 1, 0, 0): (0, 1), (0, 1, 0, 1): (0, 0), (0, 1, 1, 0): (2, 0), (0, 1, 1, 1): (4, 0),
    (1, 0, 0, 0): (0, 1), (1, 0, 0, 1): (0, 2), (1, 0, 1, 0): (2, 2), (1, 0, 1, 1): (4, 2),
    (1, 1, 0, 0): (0, 1), (1, 1, 0, 1): (3, 1), (1, 1, 1, 0): (5, 1), (1, 1, 1, 1): (4, 1),
}

# doors: closed and open, in a wall running across and in one running down
DOORS = dict(closed_h=("Objects/Door0.png", 0, 0), open_h=("Objects/Door1.png", 0, 0),
             closed_v=("Objects/Door0.png", 1, 0), open_v=("Objects/Door1.png", 1, 0))

# the heroes: frame 0 and frame 1 are the same cell of Player0 and Player1.
# The names of DawnLike's cells are tommyettinger's DawnLikeAtlas
# (image_names.tsv): the human valkyrie, wizard and -- for the Rogue --
# bandit, row 0 of the sheet
ROLES = [("VALK", "Valkyrie", 4, 0), ("WIZ", "Wizard", 6, 0), ("ROGUE", "Rogue", 3, 0)]

# ---------------------------------------------------------- the creatures
# Every creature but the heroes: its sheet and cell (named by DawnLikeAtlas),
# and its numbers from NetHack 3.6's src/monst.c -- level, speed, armour
# class, generation frequency and difficulty, and up to three attacks as
# (kind, effect, dice, sides). NetHack's own, so the dungeon's ladder of
# danger is the one players know; an effect the game does not have does
# its dice and nothing more.
A_BITE, A_CLAW, A_WEAP, A_STNG, A_TUCH, A_BUTT, A_HUGS, A_PASV, A_KICK = range(1, 10)
E_PHYS, E_POIS, E_PLYS, E_ACID, E_SLEE, E_DRLI, E_STUN, E_SGLD, E_SITM = range(9)
NOHANDS, FLY, REGEN, SGROUP, LGROUP, NOGEN, PET, PEACE = 1, 2, 4, 8, 16, 32, 64, 128

CREATURES = [
    # key, name, sheet, col, row, lvl, spd, ac, freq, diff, flags, attacks
    ("KITTEN", "kitten", "Cat", 0, 3, 2, 18, 6, 0, 3, NOHANDS | PET | NOGEN, [(A_BITE, E_PHYS, 1, 6)]),
    ("HOUSECAT", "housecat", "Cat", 1, 3, 4, 16, 5, 0, 5, NOHANDS | PET | NOGEN, [(A_BITE, E_PHYS, 1, 6)]),
    ("LARGECAT", "large cat", "Cat", 2, 3, 6, 15, 4, 0, 7, NOHANDS | PET | NOGEN, [(A_BITE, E_PHYS, 2, 4)]),
    ("LITTLEDOG", "little dog", "Dog", 0, 4, 2, 18, 6, 0, 3, NOHANDS | PET | NOGEN, [(A_BITE, E_PHYS, 1, 6)]),
    ("DOG", "dog", "Dog", 1, 4, 4, 16, 5, 0, 5, NOHANDS | PET | NOGEN, [(A_BITE, E_PHYS, 1, 6)]),
    ("LARGEDOG", "large dog", "Dog", 2, 4, 6, 15, 4, 0, 7, NOHANDS | PET | NOGEN, [(A_BITE, E_PHYS, 2, 4)]),
    ("NEWT", "newt", "Reptile", 3, 10, 0, 6, 8, 5, 1, NOHANDS, [(A_BITE, E_PHYS, 1, 2)]),
    ("JACKAL", "jackal", "Dog", 0, 0, 0, 12, 7, 3, 1, NOHANDS | SGROUP, [(A_BITE, E_PHYS, 1, 2)]),
    ("SEWERRAT", "sewer rat", "Rodent", 0, 1, 0, 12, 7, 1, 1, NOHANDS | SGROUP, [(A_BITE, E_PHYS, 1, 3)]),
    ("LICHEN", "lichen", "Slime", 0, 0, 0, 1, 9, 4, 1, NOHANDS, [(A_TUCH, E_PHYS, 0, 0)]),
    ("KOBOLD", "kobold", "Misc", 0, 2, 0, 6, 10, 1, 1, 0, [(A_WEAP, E_PHYS, 1, 4)]),
    ("FOX", "fox", "Dog", 1, 0, 0, 15, 7, 1, 1, NOHANDS, [(A_BITE, E_PHYS, 1, 3)]),
    ("GIANTRAT", "giant rat", "Rodent", 1, 1, 1, 10, 7, 2, 2, NOHANDS | SGROUP, [(A_BITE, E_PHYS, 1, 3)]),
    ("GECKO", "gecko", "Reptile", 0, 10, 1, 6, 8, 5, 2, NOHANDS, [(A_BITE, E_PHYS, 1, 3)]),
    ("ACIDBLOB", "acid blob", "Slime", 0, 2, 1, 3, 8, 2, 2, NOHANDS, [(A_PASV, E_ACID, 1, 8)]),
    ("YELLOWMOLD", "yellow mold", "Slime", 2, 0, 1, 0, 9, 2, 2, NOHANDS, [(A_PASV, E_STUN, 0, 4)]),
    ("LARGEKOBOLD", "large kobold", "Misc", 1, 2, 1, 6, 10, 1, 2, 0, [(A_WEAP, E_PHYS, 1, 6)]),
    ("HOBBIT", "hobbit", "Humanoid", 0, 10, 1, 9, 10, 2, 2, 0, [(A_WEAP, E_PHYS, 1, 6)]),
    ("CAVESPIDER", "cave spider", "Pest", 0, 2, 1, 12, 3, 2, 3, NOHANDS | SGROUP, [(A_BITE, E_PHYS, 1, 2)]),
    ("GIANTBAT", "giant bat", "Avian", 1, 11, 2, 22, 7, 2, 3, NOHANDS | FLY, [(A_BITE, E_PHYS, 1, 6)]),
    ("GNOME", "gnome", "Humanoid", 0, 8, 1, 6, 10, 1, 3, SGROUP, [(A_WEAP, E_PHYS, 1, 6)]),
    ("HOMUNCULUS", "homunculus", "Demon", 0, 4, 2, 12, 6, 2, 3, FLY, [(A_BITE, E_SLEE, 1, 3)]),
    ("FLOATINGEYE", "floating eye", "Elemental", 0, 5, 2, 1, 9, 5, 3, NOHANDS | FLY, [(A_PASV, E_PLYS, 0, 70)]),
    ("DWARF", "dwarf", "Humanoid", 1, 10, 2, 6, 10, 3, 4, 0, [(A_WEAP, E_PHYS, 1, 8)]),
    ("HILLORC", "hill orc", "Humanoid", 1, 4, 2, 9, 10, 2, 4, LGROUP, [(A_WEAP, E_PHYS, 1, 6)]),
    ("IGUANA", "iguana", "Reptile", 1, 8, 2, 6, 7, 5, 3, NOHANDS, [(A_BITE, E_PHYS, 1, 4)]),
    ("KILLERBEE", "killer bee", "Pest", 5, 1, 1, 18, -1, 2, 5, NOHANDS | FLY | LGROUP, [(A_STNG, E_POIS, 1, 3)]),
    ("GNOMELORD", "gnome lord", "Humanoid", 1, 8, 3, 8, 10, 2, 4, 0, [(A_WEAP, E_PHYS, 1, 8)]),
    ("GIANTANT", "giant ant", "Pest", 0, 4, 2, 18, 3, 3, 4, NOHANDS | SGROUP, [(A_BITE, E_PHYS, 1, 4)]),
    ("IMP", "imp", "Demon", 0, 5, 3, 12, 2, 1, 4, REGEN, [(A_CLAW, E_PHYS, 1, 4)]),
    ("SOLDIERANT", "soldier ant", "Pest", 1, 4, 3, 18, 3, 2, 6, NOHANDS | SGROUP,
     [(A_BITE, E_PHYS, 2, 4), (A_STNG, E_POIS, 3, 4)]),
    ("DINGO", "dingo", "Dog", 2, 0, 4, 16, 5, 1, 5, NOHANDS, [(A_BITE, E_PHYS, 1, 6)]),
    ("DWARFLORD", "dwarf lord", "Humanoid", 2, 10, 4, 6, 10, 2, 6, 0, [(A_WEAP, E_PHYS, 2, 4), (A_WEAP, E_PHYS, 2, 4)]),
    ("SNAKE", "snake", "Reptile", 1, 4, 4, 15, 3, 2, 6, NOHANDS, [(A_BITE, E_POIS, 1, 6)]),
    ("HUMANZOMBIE", "human zombie", "Undead", 5, 0, 4, 6, 8, 1, 5, SGROUP, [(A_CLAW, E_PHYS, 1, 8)]),
    ("WOLF", "wolf", "Dog", 0, 1, 5, 12, 4, 2, 6, NOHANDS | SGROUP, [(A_BITE, E_PHYS, 2, 4)]),
    ("LEPRECHAUN", "leprechaun", "Humanoid", 4, 8, 5, 15, 8, 4, 4, 0, [(A_CLAW, E_SGLD, 1, 2)]),
    ("GIANTBEETLE", "giant beetle", "Pest", 3, 0, 5, 6, 4, 3, 6, NOHANDS, [(A_BITE, E_PHYS, 3, 6)]),
    ("OWLBEAR", "owlbear", "Misc", 3, 0, 5, 12, 5, 3, 7, 0,
     [(A_CLAW, E_PHYS, 1, 6), (A_CLAW, E_PHYS, 1, 6), (A_HUGS, E_PHYS, 2, 8)]),
    ("OGRE", "ogre", "Humanoid", 0, 14, 5, 10, 5, 1, 7, SGROUP, [(A_WEAP, E_PHYS, 2, 5)]),
    ("GIANTSPIDER", "giant spider", "Pest", 1, 2, 5, 15, 4, 1, 7, NOHANDS, [(A_BITE, E_POIS, 2, 4)]),
    ("VAMPIREBAT", "vampire bat", "Avian", 2, 11, 5, 20, 6, 2, 7, NOHANDS | FLY | REGEN,
     [(A_BITE, E_PHYS, 1, 6), (A_BITE, E_POIS, 0, 0)]),
    ("HUMANMUMMY", "human mummy", "Undead", 5, 1, 6, 12, 4, 1, 7, 0, [(A_CLAW, E_PHYS, 2, 4), (A_CLAW, E_PHYS, 2, 4)]),
    ("WRAITH", "wraith", "Undead", 0, 6, 6, 12, 4, 2, 8, FLY, [(A_TUCH, E_DRLI, 1, 6)]),
    ("SOLDIER", "soldier", "Humanoid", 0, 5, 6, 10, 10, 1, 8, SGROUP, [(A_WEAP, E_PHYS, 1, 8)]),
    ("CROCODILE", "crocodile", "Reptile", 1, 9, 6, 9, 5, 1, 7, NOHANDS, [(A_BITE, E_PHYS, 4, 2), (A_CLAW, E_PHYS, 1, 12)]),
    ("FORESTCENTAUR", "forest centaur", "Humanoid", 2, 13, 5, 18, 3, 1, 8, 0, [(A_WEAP, E_PHYS, 1, 8), (A_KICK, E_PHYS, 1, 6)]),
    ("TROLL", "troll", "Humanoid", 0, 7, 7, 12, 4, 2, 9, REGEN,
     [(A_WEAP, E_PHYS, 4, 2), (A_CLAW, E_PHYS, 4, 2), (A_BITE, E_PHYS, 2, 6)]),
    ("HILLGIANT", "hill giant", "Humanoid", 2, 0, 8, 10, 6, 1, 10, SGROUP, [(A_WEAP, E_PHYS, 2, 8)]),
    ("VAMPIRE", "vampire", "Undead", 0, 3, 10, 12, 1, 1, 12, FLY | REGEN, [(A_CLAW, E_PHYS, 1, 6), (A_BITE, E_DRLI, 1, 6)]),
    ("BLACKPUDDING", "black pudding", "Slime", 2, 1, 10, 6, 6, 1, 12, NOHANDS, [(A_BITE, E_PHYS, 3, 8)]),
    ("ETTIN", "ettin", "Humanoid", 6, 0, 10, 12, 3, 1, 13, 0, [(A_WEAP, E_PHYS, 2, 8), (A_WEAP, E_PHYS, 3, 6)]),
    ("VAMPIRELORD", "vampire lord", "Undead", 1, 3, 12, 14, 0, 1, 14, FLY | REGEN,
     [(A_CLAW, E_PHYS, 1, 8), (A_BITE, E_DRLI, 1, 8)]),
    # the fountain's two, the nymph generated as NetHack generates her; the
    # humans that do not respect Elbereth come after them, from here on
    ("WATERNYMPH", "water nymph", "Humanoid", 1, 11, 3, 12, 9, 2, 5, 0, [(A_CLAW, E_SITM, 0, 0)]),
    ("WATERDEMON", "water demon", "Demon", 6, 1, 8, 12, -4, 0, 11, NOGEN,
     [(A_WEAP, E_PHYS, 1, 3), (A_CLAW, E_PHYS, 1, 3), (A_BITE, E_PHYS, 1, 3)]),
    ("SHOPKEEPER", "shopkeeper", "Humanoid", 4, 2, 12, 18, 0, 0, 15, NOGEN | PEACE,
     [(A_WEAP, E_PHYS, 4, 4), (A_WEAP, E_PHYS, 4, 4)]),
    ("ORACLE", "Oracle", "Humanoid", 0, 22, 12, 0, 0, 0, 13, NOGEN | PEACE, [(A_PASV, E_PHYS, 0, 4)]),
    ("WATCHMAN", "watchman", "Humanoid", 4, 5, 6, 10, 10, 0, 8, NOGEN | PEACE, [(A_WEAP, E_PHYS, 1, 8)]),
    ("PRIEST", "aligned priest", "Humanoid", 0, 23, 12, 12, 10, 0, 15, NOGEN | PEACE,
     [(A_WEAP, E_PHYS, 4, 10), (A_KICK, E_PHYS, 1, 4)]),
    ("WIZARDOFMOTT", "Wizard of Mott", "Undead", 1, 7, 30, 12, -8, 0, 34, NOGEN, [(A_WEAP, E_PHYS, 2, 12)]),
]
# DawnLike's easter egg, which its author asks be hidden in the game
PLATINO = ("Reptile", 3, 12)

# ------------------------------------------------------------- the items
# NetHack 3.6's objects (src/objects.c) the game has: a class, the base
# number -- a weapon's small-monster die, an armour's AC -- the armour
# slot, a wand's direction, the generation probability within the class,
# the base cost for the shops, and the DawnLike cell. The classes whose
# identity is hidden have one picture per *appearance*, and each game
# shuffles which appearance a kind of item wears, as NetHack does: the
# appearance's name is NetHack's description, and DawnLike's picture of
# that name is its picture.
C_WEAPON, C_ARMOR, C_POTION, C_SCROLL, C_WAND, C_RING, C_AMULET, C_GOLD = range(8)
SLOT_BODY, SLOT_SHIELD, SLOT_HELM, SLOT_GLOVES, SLOT_BOOTS, SLOT_CLOAK = range(1, 7)
D_NODIR, D_IMMEDIATE, D_RAY = range(3)

ITEMS = [
    # key, name, class, arg, slot or direction, prob, cost, (sheet, col, row) -- None for a shuffled class
    ("DAGGER", "dagger", C_WEAPON, 4, 0, 30, 4, ("ShortWep", 0, 0)),
    ("SHORTSWORD", "short sword", C_WEAPON, 6, 0, 8, 10, ("MedWep", 0, 0)),
    ("LONGSWORD", "long sword", C_WEAPON, 8, 0, 50, 15, ("LongWep", 2, 1)),
    ("QUARTERSTAFF", "quarterstaff", C_WEAPON, 6, 0, 11, 5, ("LongWep", 2, 4)),
    ("MACE", "mace", C_WEAPON, 6, 0, 40, 5, ("LongWep", 4, 4)),
    ("AXE", "axe", C_WEAPON, 6, 0, 40, 8, ("MedWep", 0, 1)),
    ("TWOHANDED", "two-handed sword", C_WEAPON, 12, 0, 22, 50, ("LongWep", 3, 1)),
    ("LEATHERARMOR", "leather armor", C_ARMOR, 2, SLOT_BODY, 82, 5, ("Armor", 6, 8)),
    ("RINGMAIL", "ring mail", C_ARMOR, 3, SLOT_BODY, 72, 100, ("Armor", 1, 6)),
    ("CHAINMAIL", "chain mail", C_ARMOR, 5, SLOT_BODY, 72, 75, ("Armor", 3, 7)),
    ("PLATEMAIL", "plate mail", C_ARMOR, 7, SLOT_BODY, 44, 600, ("Armor", 6, 6)),
    ("SMALLSHIELD", "small shield", C_ARMOR, 1, SLOT_SHIELD, 6, 3, ("Shield", 0, 0)),
    ("ORCISHHELM", "orcish helm", C_ARMOR, 1, SLOT_HELM, 6, 10, ("Hat", 1, 0)),
    ("GLOVES", "leather gloves", C_ARMOR, 1, SLOT_GLOVES, 16, 8, ("Glove", 1, 0)),
    ("LOWBOOTS", "low boots", C_ARMOR, 1, SLOT_BOOTS, 25, 8, ("Boot", 2, 0)),
    ("CLOAK", "leather cloak", C_ARMOR, 1, SLOT_CLOAK, 8, 40, ("Armor", 0, 4)),
    ("HEALING", "healing", C_POTION, 0, 0, 57, 100, None),
    ("EXTRAHEALING", "extra healing", C_POTION, 0, 0, 47, 100, None),
    ("GAINLEVEL", "gain level", C_POTION, 0, 0, 20, 300, None),
    ("GAINENERGY", "gain energy", C_POTION, 0, 0, 42, 150, None),
    ("SLEEPING", "sleeping", C_POTION, 0, 0, 42, 100, None),
    ("SICKNESS", "sickness", C_POTION, 0, 0, 42, 50, None),
    ("FRUITJUICE", "fruit juice", C_POTION, 0, 0, 42, 50, None),
    ("WATER", "water", C_POTION, 0, 0, 92, 100, None),
    ("IDENTIFY", "identify", C_SCROLL, 0, 0, 180, 20, None),
    ("ENCHANTWEAPON", "enchant weapon", C_SCROLL, 0, 0, 80, 60, None),
    ("ENCHANTARMOR", "enchant armor", C_SCROLL, 0, 0, 63, 80, None),
    ("REMOVECURSE", "remove curse", C_SCROLL, 0, 0, 65, 80, None),
    ("TELEPORT", "teleportation", C_SCROLL, 0, 0, 55, 100, None),
    ("MAGICMAPPING", "magic mapping", C_SCROLL, 0, 0, 45, 100, None),
    ("LIGHT", "light", C_SCROLL, 0, 0, 90, 50, None),
    ("FIRE", "fire", C_SCROLL, 0, 0, 30, 100, None),
    ("WLIGHT", "light", C_WAND, 0, D_NODIR, 95, 100, None),
    ("WCREATE", "create monster", C_WAND, 0, D_NODIR, 45, 200, None),
    ("WSTRIKING", "striking", C_WAND, 0, D_IMMEDIATE, 75, 150, None),
    ("WDIGGING", "digging", C_WAND, 0, D_RAY, 55, 150, None),
    ("WMISSILE", "magic missile", C_WAND, 0, D_RAY, 50, 150, None),
    ("WSLEEP", "sleep", C_WAND, 0, D_RAY, 50, 175, None),
    ("RPROTECTION", "protection", C_RING, 0, 0, 1, 100, None),
    ("RREGEN", "regeneration", C_RING, 0, 0, 1, 200, None),
    ("RFREEACTION", "free action", C_RING, 0, 0, 1, 200, None),
    ("RPOISONRES", "poison resistance", C_RING, 0, 0, 1, 150, None),
    ("RDAMAGE", "increase damage", C_RING, 0, 0, 1, 150, None),
    ("RTELEPORT", "teleportation", C_RING, 0, 0, 1, 200, None),
    ("LIFESAVING", "life saving", C_AMULET, 0, 0, 75, 150, ("Amulet", 5, 0)),
    ("MOTT", "Amulet of Mott", C_AMULET, 0, 0, 0, 30000, ("Amulet", 1, 2)),
    ("FAKEMOTT", "cheap plastic imitation", C_AMULET, 0, 0, 0, 0, ("Amulet", 0, 2)),
    ("GOLD", "gold piece", C_GOLD, 0, 0, 0, 1, ("Money", 0, 1)),
]
# the appearances of the shuffled classes: NetHack's descriptions, and
# DawnLike's picture of each; water is always clear, and a scroll's
# picture goes with its label
APPEARANCES = {
    C_POTION: [("ruby", 0, 0), ("pink", 1, 0), ("orange", 2, 0), ("emerald", 4, 0), ("sky blue", 7, 0),
               ("milky", 4, 1), ("bubbly", 6, 1), ("clear", 5, 4)],
    C_SCROLL: [("ZELGO MER", 0, 0), ("JUYED AWK YACC", 2, 1), ("NR 9", 3, 1), ("PRATYAVAYAH", 4, 1),
               ("DAIYEN FOOELS", 6, 1), ("VERR YED HORRE", 0, 2), ("KERNOD WEL", 1, 2), ("ELAM EBOW", 2, 2)],
    C_WAND: [("glass", 0, 0), ("balsa", 1, 0), ("maple", 3, 0), ("oak", 5, 0), ("ebony", 6, 0), ("iron", 1, 2)],
    C_RING: [("wooden", 0, 0), ("granite", 1, 0), ("black onyx", 0, 1), ("moonstone", 1, 1), ("jade", 3, 1), ("ruby", 0, 2)],
}
APPEAR_SHEET = {C_POTION: "Potion", C_SCROLL: "Scroll", C_WAND: "Wand", C_RING: "Ring"}


def item_pictures():
    """Bank 1, in order: every item with a fixed picture, then each shuffled
    class's appearances; and for each item kind its first picture."""
    pics, base = [], []
    for it in ITEMS:
        if it[7] is not None:
            base.append(len(pics))
            pics.append(it[7])
        else:
            base.append(None)
    cls_base = {}
    for c in (C_POTION, C_SCROLL, C_WAND, C_RING):
        cls_base[c] = len(pics)
        pics += [(APPEAR_SHEET[c], col, row) for _, col, row in APPEARANCES[c]]
    base = [b if b is not None else cls_base[it[2]] for b, it in zip(base, ITEMS)]
    assert len(pics) <= 64, len(pics)
    return pics, base


def experience(lvl, spd, ac, attacks):
    """NetHack's experience() for a kill, cut to what these creatures use:
    the square of the level, more for a low armour class and for speed, a
    little for a special attack, and fifty past level eight."""
    xp = 1 + lvl * lvl
    if ac < 3:
        xp += (7 - ac) * (2 if ac < 0 else 1)
    if spd >= 18:
        xp += 5
    elif spd > 12:
        xp += 3
    xp += sum(1 for _, e, _, _ in attacks if e != E_PHYS)
    if lvl > 8:
        xp += 50
    return xp

FONT_FIRST, FONT_LAST = 32, 126


# ---------------------------------------------------------- the pictures
_sheets = {}


def sheet(rel):
    from PIL import Image
    if rel not in _sheets:
        _sheets[rel] = Image.open(os.path.join(DL, rel)).convert("RGBA")
    return _sheets[rel]


def cut(rel, col, row):
    return sheet(rel).crop((col * 16, row * 16, col * 16 + 16, row * 16 + 16))


def over(bg, fg):
    out = bg.copy()
    out.alpha_composite(fg)
    return out


_near = {}


def indices(im):
    """A 16 x 16 picture as DB16 indices; a transparent pixel is 0, the void."""
    out = []
    for y in range(16):
        row = []
        for x in range(16):
            r, g, b, a = im.getpixel((x, y))
            if a < 128:
                row.append(0)
                continue
            v = (r << 16) | (g << 8) | b
            if v not in _near:
                _near[v] = min(range(16), key=lambda i: sum(
                    (((DB16[i] >> s) & 255) - ((v >> s) & 255)) ** 2 for s in (16, 8, 0)))
            row.append(_near[v])
        out.append(row)
    return out


def pack(rows):
    out = []
    for r in rows:
        for i in range(0, len(r), 2):
            out.append((r[i] << 4) | r[i + 1])
    return out


def quarters(px):
    """A 16 x 16 picture as its four 8 x 8 tiles, top left to bottom right."""
    return [pack([r[ox:ox + 8] for r in px[oy:oy + 8]]) for oy in (0, 8) for ox in (0, 8)]


def rgb12(c):
    return (round(((c >> 16) & 255) / 17) << 8) | (round(((c >> 8) & 255) / 17) << 4) | round((c & 255) / 17)


def mix(a, b, t):
    return sum(round(((a >> s) & 255) * (1 - t) + ((b >> s) & 255) * t) << s for s in (16, 8, 0))


# -------------------------------------------------------------- the font
def render_font():
    """SDS 8x8 at its own size, ASCII 32-126 in a row of 8 x 8 cells."""
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(os.path.join(DL, "GUI", "SDS_8x8.ttf"), 8)
    n = FONT_LAST - FONT_FIRST + 1
    im = Image.new("L", (8 * n, 8), 0)
    d = ImageDraw.Draw(im)
    for i in range(n):
        d.text((i * 8, 0), chr(FONT_FIRST + i), fill=255, font=f)
    assert set(im.getdata()) <= {0, 255}, "the font rendered with grey in it"
    im.point(lambda v: 255 if v else 0).convert("1").save(FONT_PNG)


def font_tiles():
    from PIL import Image
    im = Image.open(FONT_PNG).convert("L")
    out = []
    for i in range(FONT_LAST - FONT_FIRST + 1):
        rows = [[15 if im.getpixel((i * 8 + x, y)) else 0 for x in range(8)] for y in range(8)]
        out.append(pack(rows))
    return out


# ------------------------------------------------------- a theme's banks
def terrain_images(t):
    """(name, 16 x 16 indices) for bank 0's terrain, in the game's order."""
    floor = cut("Objects/Floor.png", *t["floor"])
    wx, wy = t["wall"]
    imgs = []
    for mask in range(16):
        key = ((mask >> 3) & 1, (mask >> 2) & 1, (mask >> 1) & 1, mask & 1)
        c, r = WALL_PIECE[key]
        imgs.append(("WALL" if mask == 0 else "", indices(over(floor, cut("Objects/Wall.png", wx + c, wy + r)))))
    imgs.append(("FLOOR", indices(floor)))
    for k in ("closed_h", "open_h", "closed_v", "open_v"):
        imgs.append(("DOOR_" + k.upper(), indices(over(floor, cut(*DOORS[k])))))
    imgs.append(("UP", indices(over(floor, cut("Objects/Tile.png", *t["up"])))))
    imgs.append(("DOWN", indices(over(floor, cut("Objects/Tile.png", *t["down"])))))
    imgs.append(("GRAVE", indices(over(floor, cut("Objects/Decor0.png", 0, 17)))))
    imgs.append(("FOUNTAIN", indices(over(floor, cut("Objects/Decor0.png", 1, 21)))))
    imgs.append(("ALTAR", indices(over(floor, cut("Objects/Decor0.png", 0, 20)))))
    for i, (key, _name, c, r, _lvl) in enumerate(TRAPS):
        imgs.append(("TRAP" if i == 0 else "", indices(over(floor, cut("Objects/Trap0.png", c, r)))))
    assert 96 + 4 * len(imgs) <= 256, len(imgs)
    return imgs


def creature_images(t, frame):
    """Bank 2 or 3: the heroes, the creatures in CREATURES' order, Platino."""
    floor = cut("Objects/Floor.png", *t["floor"])
    out = [indices(over(floor, cut("Characters/Player%d.png" % frame, c, r))) for _, _, c, r in ROLES]
    for _key, _name, sh, c, r, *_ in CREATURES:
        out.append(indices(over(floor, cut("Characters/%s%d.png" % (sh, frame), c, r))))
    out.append(indices(over(floor, cut("Characters/%s%d.png" % (PLATINO[0], frame), PLATINO[1], PLATINO[2]))))
    assert len(out) <= 64, len(out)
    return out


def creature_table():
    """The creatures' numbers as the game reads them: a type is an index
    into these arrays, and its picture is tile (3 + type) * 4 of banks 2-3."""
    n = len(CREATURES)
    col = lambda k: " ".join(str(v) for v in k)   # noqa: E731
    out = ["", "; the creatures: NetHack 3.6's numbers (src/monst.c) for DawnLike's pictures",
           "CONST N_MON = %d" % n]
    out += ["CONST M_%s = %d" % (cr[0], i) for i, cr in enumerate(CREATURES)]
    out += ["CONST %s = %d" % kv for kv in (
        ("MF_NOHANDS", NOHANDS), ("MF_FLY", FLY), ("MF_REGEN", REGEN), ("MF_SGROUP", SGROUP),
        ("MF_LGROUP", LGROUP), ("MF_NOGEN", NOGEN), ("MF_PET", PET), ("MF_PEACE", PEACE),
        ("A_BITE", A_BITE), ("A_CLAW", A_CLAW), ("A_WEAP", A_WEAP), ("A_STNG", A_STNG), ("A_TUCH", A_TUCH),
        ("A_BUTT", A_BUTT), ("A_HUGS", A_HUGS), ("A_PASV", A_PASV), ("A_KICK", A_KICK),
        ("E_POIS", E_POIS), ("E_PLYS", E_PLYS), ("E_ACID", E_ACID), ("E_SLEE", E_SLEE),
        ("E_DRLI", E_DRLI), ("E_STUN", E_STUN), ("E_SGLD", E_SGLD), ("E_SITM", E_SITM))]
    out.append("BYTE ARRAY m_lvl(%d) = [%s]" % (n, col(c[5] for c in CREATURES)))
    out.append("BYTE ARRAY m_spd(%d) = [%s]" % (n, col(c[6] for c in CREATURES)))
    out.append("; armour class plus ten, so a byte holds it")
    out.append("BYTE ARRAY m_ac(%d) = [%s]" % (n, col(c[7] + 10 for c in CREATURES)))
    out.append("BYTE ARRAY m_freq(%d) = [%s]" % (n, col(c[8] for c in CREATURES)))
    out.append("BYTE ARRAY m_diff(%d) = [%s]" % (n, col(c[9] for c in CREATURES)))
    out.append("BYTE ARRAY m_flag(%d) = [%s]" % (n, col(c[10] for c in CREATURES)))
    out.append("CARD ARRAY m_xp(%d) = [%s]" % (n, col(experience(c[5], c[6], c[7], c[11]) for c in CREATURES)))
    out.append("; three attacks a creature, three bytes each: kind * 16 + effect, dice, sides")
    att = []
    for c in CREATURES:
        a = (list(c[11]) + [(0, 0, 0, 0)] * 3)[:3]
        att += [x for k, e, d, s in a for x in ((k << 4) | e, d, s)]
    out.append("BYTE ARRAY m_att(%d) = [" % (9 * n))
    out += ["  " + col(att[i:i + 27]) for i in range(0, len(att), 27)]
    out.append("]")
    return out


def theme_bytes(t, font):
    """The 32,768 bytes of a theme's four pattern banks."""
    bank0 = [b for g in font for b in g]
    bank0 += [0] * (32 * 96 - len(bank0))            # the terrain starts at tile 96
    for _, px in terrain_images(t):
        bank0 += [b for q in quarters(px) for b in q]
    floor = cut("Objects/Floor.png", *t["floor"])
    bank1 = []
    for sh, c, r in item_pictures()[0]:
        bank1 += [b for q in quarters(indices(over(floor, cut("Items/%s.png" % sh, c, r)))) for b in q]
    banks = [bank0, bank1]
    for frame in (0, 1):
        banks.append([b for px in creature_images(t, frame) for q in quarters(px) for b in q])
    out = bytearray()
    for b in banks:
        assert len(b) <= 8192, len(b)
        out += bytes(b) + bytes(8192 - len(b))
    return bytes(out)


# ------------------------------------------------------------- the file
def palette():
    """The banks: 0 DawnBringer's 16, 1 the same remembered -- dimmed
    towards the void -- then the inks of the text, entry 15 of each."""
    db = [rgb12(c) for c in DB16]
    dim = [rgb12(mix(c, 0x140C1C, 0.58)) for c in DB16]
    inks = [0xDEEED6, 0xDAD45E, 0xD04648, 0x6DAA2C, 0x8595A1, 0x6DC2CA]
    banks = [db, dim] + [[db[0]] * 15 + [rgb12(c)] for c in inks]
    return banks


def act(font):
    lines = [
        "; MOTT's art table, written by tools/mkmott.py from DawnLike's sheets --",
        "; run it, do not edit this. Tiles, patterns and the palette are DawnLike's,",
        "; by DragonDePlatino, on DawnBringer's palette (CC-BY 4.0).",
        "",
        "; bank 0: tile FONT_FIRST.. is ASCII from 32; a terrain picture is four",
        "; tiles from its T_ number, and T_WALL + 4 * mask is the wall piece whose",
        "; neighbours are walls by mask: 8 north, 4 south, 2 west, 1 east",
        "CONST FONT_FIRST = %d" % FONT_FIRST,
    ]
    n = 96
    for name, _ in terrain_images(THEMES[0]):
        if name:
            lines.append("CONST T_%s = %d" % (name, n))
        n += 4
    lines.append("; a corridor and an empty doorway are the floor's picture")
    lines.append("CONST T_CORR = T_FLOOR")
    lines.append("CONST T_DOORWAY = T_FLOOR")
    lines += trap_table()
    lines.append("; banks 2 and 3: the creatures, a picture four tiles, frame 0 and frame 1")
    for i, (key, _, _, _) in enumerate(ROLES):
        lines.append("CONST C_%s = %d" % (key, i * 4))
    lines.append("CONST C_PLATINO = %d" % ((len(ROLES) + len(CREATURES)) * 4))
    lines += creature_table()
    lines += item_table()
    lines += names_table()
    lines.append("CONST N_THEMES = %d" % len(THEMES))
    lines.append("; a theme's file on MOTT's drive, eleven characters each")
    lines.append('BYTE ARRAY theme_names = "%s"' % "".join(t["file"].ljust(8) + "DAT" for t in THEMES))
    pal = palette()
    lines.append("CONST N_PAL = %d" % len(pal))
    lines.append("; the palette: 0 in view, 1 remembered, 2.. the inks of the text")
    lines.append("CARD ARRAY mott_pal(%d) = [" % (16 * len(pal)))
    for b in pal:
        lines.append("  " + " ".join("$%03X" % c for c in b))
    lines.append("]")
    return "\n".join(lines) + "\n"


def byte_rows(name, data, per=24):
    out = ["BYTE ARRAY %s(%d) = [" % (name, len(data))]
    out += ["  " + " ".join(str(v) for v in data[i:i + per]) for i in range(0, len(data), per)]
    out.append("]")
    return out


def item_table():
    """The items' numbers: a kind is an index into these arrays; its picture
    is bank 1's o_pic, plus the kind's appearance for a shuffled class."""
    n = len(ITEMS)
    _, base = item_pictures()
    col = lambda k: " ".join(str(v) for v in k)   # noqa: E731
    out = ["", "; the items: NetHack 3.6's (src/objects.c) the game has",
           "CONST N_OBJ = %d" % n]
    out += ["CONST O_%s = %d" % (it[0], i) for i, it in enumerate(ITEMS)]
    out += ["CONST %s = %d" % kv for kv in (
        ("C_WEAPON", C_WEAPON), ("C_ARMOR", C_ARMOR), ("C_POTION", C_POTION), ("C_SCROLL", C_SCROLL),
        ("C_WAND", C_WAND), ("C_RING", C_RING), ("C_AMULET", C_AMULET), ("C_GOLD", C_GOLD),
        ("SLOT_BODY", SLOT_BODY), ("SLOT_SHIELD", SLOT_SHIELD), ("SLOT_HELM", SLOT_HELM),
        ("SLOT_GLOVES", SLOT_GLOVES), ("SLOT_BOOTS", SLOT_BOOTS), ("SLOT_CLOAK", SLOT_CLOAK),
        ("D_NODIR", D_NODIR), ("D_IMMEDIATE", D_IMMEDIATE), ("D_RAY", D_RAY))]
    out.append("BYTE ARRAY o_class(%d) = [%s]" % (n, col(it[2] for it in ITEMS)))
    out.append("; a weapon's die, an armour's AC")
    out.append("BYTE ARRAY o_arg(%d) = [%s]" % (n, col(it[3] for it in ITEMS)))
    out.append("; an armour's slot, a wand's direction")
    out.append("BYTE ARRAY o_slot(%d) = [%s]" % (n, col(it[4] for it in ITEMS)))
    out.append("BYTE ARRAY o_prob(%d) = [%s]" % (n, col(min(255, it[5]) for it in ITEMS)))
    out.append("CARD ARRAY o_cost(%d) = [%s]" % (n, col(it[6] for it in ITEMS)))
    out.append("BYTE ARRAY o_pic(%d) = [%s]" % (n, col(base)))
    return out


# the names' file: a record of NAME_REC bytes for each name, a length byte
# and the letters, so the game finds one by multiplying and keeps no table
NAMES_FILE = "MNAMES"
NAME_REC = 48

# NetHack's traps the game has, in the order of their pictures from T_TRAP:
# the key, defsyms' name, DawnLike's Trap0 cell, and mktrap()'s least
# difficulty for it
TRAPS = [
    ("ARROW", "arrow trap", 0, 0, 1), ("DART", "dart trap", 1, 0, 1),
    ("ROCK", "falling rock trap", 2, 0, 1), ("SQUEAKY", "squeaky board", 3, 0, 1),
    ("BEAR", "bear trap", 4, 0, 1), ("SLEEPGAS", "sleeping gas trap", 7, 0, 2),
    ("PIT", "pit", 2, 2, 1), ("SPIKEDPIT", "spiked pit", 3, 2, 5),
    ("TRAPDOOR", "trap door", 5, 2, 1), ("TELEPORT", "teleportation trap", 2, 1, 1),
    ("LEVELTELE", "level teleporter", 3, 1, 5),
]

# the gods of each role -- lawful, neutral, chaotic -- as role.c has them
GODS = ["Tyr", "Odin", "Loki", "Ptah", "Thoth", "Anhur", "Issek", "Mog", "Kos"]

# the shops the game has, shknam.c's names and probabilities, and the first
# eight of each one's keepers
SHOPS = [
    ("GENERAL", "general store", 42,
     ["Hebiwerie", "Possogroenoe", "Asidonhopo", "Manlobbi", "Adjama", "Pakka Pakka", "Kabalebo", "Wonotobo"]),
    ("ARMOR", "used armor dealership", 14,
     ["Demirci", "Kalecik", "Boyabai", "Yildizeli", "Gaziantep", "Siirt", "Akhalataki", "Tirebolu"]),
    ("SCROLL", "second-hand bookstore", 10,
     ["Skibbereen", "Kanturk", "Rath Luirc", "Ennistymon", "Lahinch", "Kinnegad", "Lugnaquillia", "Enniscorthy"]),
    ("POTION", "liquor emporium", 10,
     ["Njezjin", "Tsjernigof", "Ossipewsk", "Gorlowka", "Gomel", "Konosja", "Weliki Oestjoeg", "Syktywkar"]),
    ("WEAPON", "antique weapons outlet", 5,
     ["Voulgezac", "Rouffiac", "Lerignac", "Touverac", "Guizengeard", "Melac", "Neuvicq", "Vanzac"]),
    ("RING", "jewelers", 3,
     ["Feyfer", "Flugi", "Gheel", "Havic", "Haynin", "Hoboken", "Imbyze", "Juyn"]),
    ("WAND", "quality apparel and accessories", 3,
     ["Yr Wyddgrug", "Trallwng", "Mallwyd", "Pontarfynach", "Rhaeader", "Llandrindod", "Llanfair-ym-muallt",
      "Y-Fenni"]),
]

# what the gravestone says of a death that is not a monster's
DEATHS = [
    ("ARROW", "killed by an arrow"), ("DART", "killed by a little dart"),
    ("DARTPOIS", "poisoned by a little dart"), ("ROCK", "killed by a falling rock"),
    ("BEAR", "killed by a bear trap"), ("PIT", "fell into a pit"),
    ("SPIKES", "fell into a pit of iron spikes"), ("SPIKEHP", "killed by a fall onto poison spikes"),
    ("SPIKEPOIS", "poisoned by a fall onto poison spikes"), ("WATER", "killed by contaminated water"),
    ("JUICE", "killed by an unrefrigerated sip of juice"), ("WRATH", "killed by the wrath of"),
]
KD_FIRST = 200

# the ? page: the keys, a line a row of the window
HELP_FILE = "MHELP"
HELP = [
    "Move: the arrows, the keypad, or",
    "      h j k l y u b n; two arrows held",
    "      together go diagonally. Into a",
    "      monster attacks it, into the pet",
    "      swaps places, into a door opens it",
    "",
    "> <  down, up the stairs   Enter: either",
    ".    rest a turn    s  search a turn",
    ",    pick up        d  drop",
    "i    the pack       :  look here",
    "w    wield          t  throw",
    "f    fire daggers   z  zap a wand",
    "W T  wear, take off armour",
    "P R  put on, remove a ring or amulet",
    "q    drink -- from a fountain too",
    "r    read           Z  cast a spell",
    "p    pay the shopkeeper",
    "E    write in the dust",
    "#    a long command: #pray",
    "\\    what you have discovered",
    "",
    "Ctrl+R  draw the screen again",
    "Esc     quit        ?  this page",
]


def trap_table():
    out = ["; the traps: a trap's picture is T_TRAP + 4 * its TR_ number"]
    out += ["CONST TR_%s = %d" % (t[0], i) for i, t in enumerate(TRAPS)]
    out.append("CONST N_TRAP = %d" % len(TRAPS))
    out.append("BYTE ARRAY tr_min(%d) = [%s]" % (len(TRAPS), " ".join(str(t[4]) for t in TRAPS)))
    out.append("; the shops: SH_ numbers, and each one's chance in %d" % sum(s[2] for s in SHOPS))
    out += ["CONST SH_%s = %d" % (s[0], i) for i, s in enumerate(SHOPS)]
    out.append("CONST N_SHOP = %d" % len(SHOPS))
    out.append("CONST SHOP_ODDS = %d" % sum(s[2] for s in SHOPS))
    out.append("BYTE ARRAY sh_prob(%d) = [%s]" % (len(SHOPS), " ".join(str(s[2]) for s in SHOPS)))
    out.append("; a death that is not a monster's: killer KD_FIRST + its number")
    out.append("CONST KD_FIRST = %d" % KD_FIRST)
    out += ["CONST KD_%s = %d" % (d[0], KD_FIRST + i) for i, d in enumerate(DEATHS)]
    return out


def help_bytes():
    out = bytearray()
    for line in HELP:
        assert len(line) <= 40, line
        out += line.ljust(40).encode("ascii")
    return bytes(out)


def name_groups():
    """The names in the file's order, as (constant, first record, words)."""
    groups = [("NAME_MON", [c[1] for c in CREATURES]), ("NAME_OBJ", [it[1] for it in ITEMS])]
    groups += [("NAME_" + key, [w for w, _, _ in APPEARANCES[c]])
               for c, key in ((C_POTION, "POTION"), (C_SCROLL, "SCROLL"), (C_WAND, "WAND"), (C_RING, "RING"))]
    groups += [("NAME_TRAP", [t[1] for t in TRAPS]), ("NAME_GOD", GODS),
               ("NAME_SHOP", [s[1] for s in SHOPS]), ("NAME_SHK", [k for s in SHOPS for k in s[3]]),
               ("NAME_DEATH", [d[1] for d in DEATHS])]
    out, k = [], 0
    for const, words in groups:
        out.append((const, k, words))
        k += len(words)
    return out


def names_bytes():
    out = bytearray()
    for _, _, words in name_groups():
        for w in words:
            assert len(w) < NAME_REC, w
            out += (chr(len(w)) + w).encode("ascii").ljust(NAME_REC, b"\0")
    return bytes(out)


def names_table():
    out = ["", "; the names are in %s.DAT on MOTT's drive, NAME_REC bytes a name: a" % NAMES_FILE,
           "; length byte and the letters. The creatures' from NAME_MON by type, the",
           "; kinds' from NAME_OBJ, each shuffled class's appearances from its own",
           "CONST NAME_REC = %d" % NAME_REC]
    out += ["CONST %s = %d" % (const, k) for const, k, _ in name_groups()]
    out.append('BYTE ARRAY names_file = "%s"' % (NAMES_FILE.ljust(8) + "DAT"))
    out.append("; the ? page: %d lines of forty characters in %s.DAT" % (len(HELP), HELP_FILE))
    out.append("CONST N_HELP = %d" % len(HELP))
    out.append('BYTE ARRAY help_file = "%s"' % (HELP_FILE.ljust(8) + "DAT"))
    return out


def outputs():
    font = font_tiles()
    files = {OUT: act(font).encode("utf-8")}
    for t in THEMES:
        files[os.path.join(OUT_DIR, t["file"] + ".DAT")] = theme_bytes(t, font)
    files[os.path.join(OUT_DIR, NAMES_FILE + ".DAT")] = names_bytes()
    files[os.path.join(OUT_DIR, HELP_FILE + ".DAT")] = help_bytes()
    return files


def preview(files):
    """Each theme's terrain and heroes as the machine would show them, from
    the bytes of its file and the palette -- a room, a door, the stairs."""
    from PIL import Image
    pal = palette()
    S = 2
    room = [
        "###########",
        "#.........#",
        "#..V......+",
        "#....W....#",
        "#.R.....>.#",
        "#####+#####",
    ]
    W, H = len(room[0]), len(room)
    im = Image.new("RGB", ((W * 16 + 8) * S * len(THEMES), (H * 16 + 8) * S), (20, 12, 28))
    rgb = lambda v: (((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17)   # noqa: E731
    for k, t in enumerate(THEMES):
        dat = files[os.path.join(OUT_DIR, t["file"] + ".DAT")]

        def put(tile, pbank, ox, oy, bank=0):
            base = pbank * 8192 + tile * 32
            for y in range(8):
                for x in range(8):
                    v = dat[base + y * 4 + x // 2]
                    ix = (v >> 4) if x % 2 == 0 else v & 15
                    c = rgb(pal[bank][ix])
                    for dy in range(S):
                        for dx in range(S):
                            im.putpixel((ox + x * S + dx, oy + y * S + dy), c)
        names = {}
        n = 96
        for name, _ in terrain_images(t):
            if name:
                names[name] = n
            n += 4
        X0 = k * (W * 16 + 8) * S + 4 * S
        for y, row in enumerate(room):
            for x, ch in enumerate(row):
                pb = 0
                if ch == "#":
                    wall = lambda dx, dy: 1 if 0 <= y + dy < H and 0 <= x + dx < W and room[y + dy][x + dx] in "#+" else 0  # noqa: E731
                    t0 = names["WALL"] + 4 * (8 * wall(0, -1) + 4 * wall(0, 1) + 2 * wall(-1, 0) + wall(1, 0))
                elif ch == "+":
                    t0 = names["DOOR_CLOSED_H"] if y in (0, H - 1) else names["DOOR_CLOSED_V"]
                elif ch == ">":
                    t0 = names["DOWN"]
                elif ch in "VWR":
                    t0, pb = "VWR".index(ch) * 4, 2
                else:
                    t0 = names["FLOOR"]
                for q in range(4):
                    put(t0 + q, pb, X0 + (x * 16 + 8 * (q & 1)) * S, 4 * S + (y * 16 + 8 * (q >> 1)) * S,
                        1 if (ch == "." and x > 7) else 0)
    im.save(PREVIEW)


def main():
    if "--font" in sys.argv:
        os.makedirs(OUT_DIR, exist_ok=True)
        render_font()
        print("  wrote %s" % os.path.relpath(FONT_PNG, ROOT))
        return 0
    files = outputs()
    if "--check" in sys.argv:
        stale = [p for p, b in files.items() if not os.path.exists(p) or open(p, "rb").read() != b]
        if stale:
            print("  stale: %s -- run python tools/mkmott.py" % ", ".join(os.path.relpath(p, ROOT) for p in stale))
            return 1
        print("ok -- the art table, the %d theme files and the names are current" % len(THEMES))
        return 0
    os.makedirs(OUT_DIR, exist_ok=True)
    for p, b in files.items():
        with open(p, "wb") as fh:
            fh.write(b)
    preview(files)
    print("  %d themes, %d bytes each, and %d names; wrote %s" % (len(THEMES), 32768, len(names_bytes()) // NAME_REC, ", ".join(
        os.path.relpath(p, ROOT) for p in files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
