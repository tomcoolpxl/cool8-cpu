# Phosphor Icons

`Phosphor.ttf` — the regular weight of [Phosphor
Icons](https://phosphoricons.com/), vendored here and compiled into the
emulator window (`rust/src/emu.rs` merges it into Dear ImGui's font
atlas beside the text face).

**MIT licence**, © Phosphor Icons. Fetched from
`unpkg.com/@phosphor-icons/web@2.1.1/src/regular/Phosphor.ttf`.

## Why a font and not drawings

The taskbar's icons are characters. Merging a second face into the
atlas is one call, and after it an icon is a string like any other — no
bitmap format, no second draw path, no artwork to maintain. The
codepoints are Phosphor's own Private Use Area assignments, read out of
its stylesheet rather than guessed, and named in
[`rust/src/bar.rs`](../../rust/src/bar.rs).

Only the regular weight is here. The bold weight was fetched too and
deleted: one weight is what a monochrome bar needs, and 488 KB is
already the largest asset in this repository.
