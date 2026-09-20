# art — the command surface

Sprites and concept art for games. Built against `DnD-CLI`, which already
solved most of this once: a profile that holds the style, one rule that decides
how a thing is drawn, a chroma pipeline that runs locally, and `--dry-run` on
everything that writes.

The first job is AXI, whose `docs/ASSET_SPEC.md` is the spec this implements.
Nothing below is invented — every number comes from that document, and every
rule in §7 of it is a bug that already happened.

## The job, in one line

Get from "Masie needs a swim animation" to a packed atlas the game can draw,
without anyone measuring anything by hand.

## The surface

```
art init                      write art.yaml for this project

art audit [subject…]          measure what exists against the spec
art plan   <subject>          what to ask the generator for
art prompt <subject>          the prompt text, the rules baked in
art draw   <subject>          generate the sheet
art cut    <subject>          key, unspill, split into frames
art check  <subject>          verify the rules; nonzero exit on a violation
art pack                      atlas.webp + atlas.json

art concept new <description> exploratory art — not measured, not cut, not packed
art concept list
```

Flat, because the pipeline *is* the mental model: each verb is one stage, and
you run them left to right. `DnD-CLI` moved away from a flat surface, but it had
grown two jobs (rules engine, campaign authoring) sharing one list. This has
one job. `concept` is a group because it is the one thing that skips the
pipeline entirely — it is never cut and never packed.

### Global

`--project/-p <dir>` the directory holding `art.yaml`; defaults to the nearest
one above `$PWD`. `--json` on every reader, so `audit` and `check` can drive
CI. `--dry-run` on every writer, showing the prompt and the numbers and writing
nothing.

### The stages

| Command | Reads | Writes | Key options |
| --- | --- | --- | --- |
| `audit` | the atlas + the sheets | nothing | `--at-tile-px 192`, `--device macbook` |
| `plan` | art.yaml | nothing | `--canvas 2048`, `--tile-px` |
| `prompt` | art.yaml | nothing | `--note`, `--reference/-i` |
| `draw` | art.yaml | `sheets/<id>.png` | `--from <file>`, `--retry`, `--dry-run` |
| `cut` | `sheets/<id>.png` | `frames/<id>/*.png` | `--from`, `--key`, `--rows`, `--open` |
| `check` | frames + art.yaml | nothing | `--strict` |
| `pack` | frames | `atlas.webp`, `atlas.json` | `--format`, `--quality 90` |

`--from` on both `draw` and `cut` is the escape hatch that matters: art made by
hand in ChatGPT or Midjourney drops straight into the pipeline, and no
generator needs to be configured for the tool to be useful. `DnD-CLI` has the
same flag on `mini`, `portrait` and `topdown` for the same reason.

## What makes the numbers agree: one rule, one place

`DnD-CLI` has `art_class_for(actor)` — the single rule deciding whether a thing
is a mini or a top-down rotation, written once so four commands cannot
disagree. The same shape applies here. `kind_for(subject)` returns one of three,
and it decides sizing, cell layout and the check that runs afterwards:

| kind | sized by | cell rule |
| --- | --- | --- |
| `character` | height in tiles → minimum drawn px | grid cell with 20% headroom both ways |
| `tile` | exact | 192 × 192, edge to edge, **no margin** — a margin is a seam |
| `prop` | width in tiles | height follows its own aspect ratio |

At 192 px per tile that gives Masie 240 px, an enemy 200, a friend 220, a boss
500, a tree 580 × 790. `plan`, `prompt`, `cut` and `check` all read those from
the same function, so a sheet cannot be planned at one size and checked at
another.

## art.yaml — the single source of truth

This replaces the constants currently hardcoded across `pack_atlas.py`:
`NPC_PANELS` pixel boxes, `AXI_ROWS`, `ENEMY_ROWS`, the per-sheet tolerances.
Those are data, and they are wrong to compile in.

```yaml
tile_px: 192            # the target. everything else derives from it
camera_tiles: 9         # the camera shows 9 tiles of height, always
canvas: 2048            # what the generator can actually output
backdrop: "#FC309B"     # flat magenta, keyed by colour alone

style: >
  Painterly storybook, soft light, visible brush texture, heavy dark outline.

subjects:
  masie:
    kind: character
    height_tiles: 1.15
    # Which animations share a sheet is art direction, not arithmetic: one
    # sheet is one costume and one lighting setup. Nine animations do not fit
    # 6x4, so they are grouped here rather than split by the tool.
    sheets:
      masie-move:  [idle, run, climb]
      masie-air:   [jump, fall, land]
      masie-react: [hurt, defeat, swim]

  mr-frog:
    kind: character
    height_tiles: 1.05
    sheets:
      mr-frog: [idle, walk, run, jump, hurt, sit]

  sir-croaks:
    kind: character
    height_tiles: 2.50          # boss: 3x3 at 2048, 500 px minimum
    sheets: {sir-croaks: [idle, talk, cast]}

  tree:
    kind: prop
    width_tiles: 3
```

`art init` writes this by reading what a project already has, so AXI's first
`art.yaml` is generated from its current sheets rather than typed.

## The keyer, and the halo

The white halo on Mr Frog and the magenta rind on the King are the same bug:
**a binary mask.** A flood fill that returns in-or-out leaves every pixel where
the drawing faded into the paper fully opaque and fully pale.

So the design separates finding the background from removing it. Three ways to
find it —

- **colour** — distance from the key colour (magenta, green)
- **flood** — flooded in from the border, for sheets drawn on paper or white
- **alpha** — already transparent

— and exactly one way to remove it, applied to all three: a **soft alpha ramp**
across a band of distance, then an **unspill** pulling key-dominant pixels back
toward the other channels, then trim, then measure. There is no binary mask
anywhere in this pipeline. That is the whole point of writing it down.

`--open` (erode then dilate, which drops a line that has no core but keeps an
axolotl) stays, as a **rescue for sheets that already exist**. New art never
needs it, because §7.3 says nothing is in the frame but the character.

## Measuring, which is the actual product

`cut` records, per frame: the content box, the baseline, and the drawn height in
px and in tiles. `check` then fails on the things that have already gone wrong:

1. a frame smaller than its kind's minimum → the pixelation, caught at source
2. baselines in one row differing by more than a few px → the bob when animated
3. any pixel of backdrop left inside a frame → the halo
4. an outline too close to the backdrop colour → Sir Croaks' lost outline
5. a frame touching its neighbour, or a label touching art → merged frames
6. a terrain tile with a transparent margin → the seam
7. more than one subject on a sheet → **the rule that matters most**

`audit` is the same measurement pointed at what already ships, and it prints
§2's table: source size, drawn size, upscale factor per device. Fixing AXI
starts and ends with that command reading clean.

## WebP

`pack` defaults to WebP at quality 90. The atlas today is 5.6 MB of PNG for 2.4
megapixels — 2.3 bytes per pixel, because PNG is built for flat colour and this
art is painterly. WebP at q90 runs 4–6× smaller, which is what makes 6× the
pixel area affordable at all, and it needs no new art. `--format png` stays for
debugging. The game hands the file to `drawImage`, which does not care what
decoded it.

## Deliberately not in scope

- **Level data.** The log hanging above the ledge in 1-1 and the high stump
  near x=60 are placement bugs in AXI's level builder, not art. The assert that
  catches them — every standing prop's footprint touches the ground under it —
  belongs in `build_1-*.py`, where the level data is.
- **Running in AXI's CI.** `web/atlas.png` and `web/atlas.json` are committed,
  and the Pages workflow only runs `build_web.py`. So `art` is a tool a person
  runs, and the atlas stays committed. AXI's build keeps its dependency-free
  property; this tool is free to use Pillow, numpy and click the way `DnD-CLI`
  does.
