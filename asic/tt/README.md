# asic/tt

The TinyTapeout submission: what the shuttle needs that the RTL itself
does not carry.

`info.yaml` and `docs/info.md` are the project metadata and datasheet
page. The Verilog is **not** duplicated here — `prepare.py` copies it out
of `rtl/core` and `rtl/pads`, so there is one copy of the CPU in the
project and no chance of the submission drifting from what the
co-simulation actually tested.

## Running LibreLane

```bash
gh repo create cool8-tt --private \
    --template TinyTapeout/ttsky-verilog-template --clone
python asic/tt/prepare.py ../cool8-tt
cd ../cool8-tt && git add -A && git commit -m "COOL8 core" && git push
```

The template's `tt-gds-action` workflow then runs LibreLane and
publishes the GDS, the cell count, the utilisation and the timing report
as build artefacts. That number — not the `yosys` proxy in
`sim/synth.py` — is the one that decides the tile count.

The CI config and cocotb harness are deliberately not copied in here;
they change from shuttle to shuttle and TinyTapeout maintains them.
Taking them from the current template is what keeps the submission valid
as shuttles roll over.

`python asic/tt/prepare.py ../cool8-tt --check` reports drift without
writing anything.

## Why this exists at M3 and not M8

Area is the one risk that could invalidate the architecture, and it is
knowable from the moment the core synthesises — see
[D19](../../docs/01-decisions.md#d19--area-overruns-are-paid-for-in-tiles-not-isa-cuts)
and the M3 entry in [the roadmap](../../docs/06-roadmap.md). Running it
now makes the tile decision years early instead of weeks before a
shuttle deadline.

## Notes

- `tiles: 2x2`. 3084 gate equivalents against roughly 1000 per tile, and
  the shuttle sells 1x1, 1x2, 2x2, 3x2, 4x2, 6x2 and 8x2 — there is no
  three-tile option. See
  [03-microarchitecture.md §5.7](../../docs/03-microarchitecture.md#57-area-estimate).
- The top module is `tt_um_cool8`. TinyTapeout requires top module names
  to be unique across a shuttle and suggests including your GitHub
  username; confirm this one is free before submitting, and rename it in
  `rtl/pads/tt_um_cool8.v` and `info.yaml` together if it is not.
- OpenLane 2 was renamed **LibreLane** in early 2026. The roadmap and
  the microarchitecture document still say OpenLane in places; it is the
  same tool.
