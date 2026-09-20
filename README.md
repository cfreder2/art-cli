# art-cli

Sprites and concept art for games: plan a sheet, generate it, key it, cut it,
measure it, pack it.

**Status: the command surface is designed, nothing is built.** Read
[DESIGN.md](DESIGN.md) first — it is the spec, and it is what to argue with.

The first job is [AXI](../../axi), whose every sprite is currently drawn larger
than it was painted. `docs/ASSET_SPEC.md` in that repo says what the sizes
should be; this tool is how they get enforced instead of remembered.

```sh
art audit                 # what is undersized, and by how much, per device
art plan masie            # what to ask the generator for
art prompt masie-move     # the prompt, with the sheet rules baked in
art cut masie-move --from ~/Downloads/masie.png
art check masie-move      # nonzero if it broke a rule
art pack                  # atlas.webp + atlas.json
```

Built against [`DnD-CLI`](../../DND/DnD-CLI), which solved the profile, the
chroma pipeline and the measure-then-correct loop already.
