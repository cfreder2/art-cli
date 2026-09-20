# art-cli

Sprites and concept art for games: plan a sheet, generate it, key it, cut it,
measure it, pack it.

**Status:** `init`, `audit`, `status`, `plan`, `prompt`, `draw`, `check --seams`,
`view`, `issues` and `effects` are built and tested. `accept`, `cut`, `pack` and
`runtime` are designed but not written. Read [DESIGN.md](DESIGN.md) — it is the spec.

```sh
uv tool install --editable .    # `art` on PATH, tracking this working tree
```

Installed editable on purpose: edits here take effect on the next `art` run,
with no reinstall step to forget.

The first job is [AXI](../../axi), whose every sprite is currently drawn larger
than it was painted. `docs/ASSET_SPEC.md` in that repo says what the sizes
should be; this tool is how they get enforced instead of remembered.

```sh
cd ../../axi
art status                       # the board: 68 subjects, all legacy
art audit --all                  # what is undersized, by how much, per device
art plan frog                    # sheets, cells, references, generations
art plan --all --budget          # what the whole redraw costs to generate
art check --all                  # which terrain tiles seam when repeated
art prompt frog                  # the exact text a generation would be sent
art draw frog                    # the only verb that spends anything
art view frog                    # play it in a browser, today beside the candidate
art issues frog                  # frames flagged as wrong, from the preview
art effects frog                 # breathe, sway, bob, throb — motion without frames
```

Built against [`DnD-CLI`](../../DND/DnD-CLI), which solved the profile, the
chroma pipeline and the measure-then-correct loop already.
