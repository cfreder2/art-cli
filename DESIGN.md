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
art status                    the board: every subject, its state, what is stale

art audit  [selector]         measure what exists against the spec
art plan   [selector]         what to ask the generator for
art prompt [selector]         the prompt text, the rules baked in
art draw   [selector]         generate candidates for a sheet
art accept <sheet> [n]        keep candidate n as the sheet
art cut    [selector]         key, unspill, split into frames
art check  [selector]         verify the rules; nonzero exit on a violation
art pack                      atlas.webp + atlas.json
art view   [selector]         preview in the browser (also bare `art`)
art runtime                   emit the reader for the format it writes

art concept new <description> exploratory art — not measured, not cut, not packed
art concept list
```

A **selector** is `<name>… | --all | --stale | --tag <t>`, on every stage. That
is not a convenience: fixing AXI is nineteen sheets, and a surface that only
addresses one at a time is a surface you drive with a shell loop.

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
- **Running in AXI's CI.** `build_web.py:28` calls `pack_atlas.py`, so the atlas
  is rebuilt on every deploy — which is why `tools/_png.py` is a hand-written
  PNG writer: GitHub Actions installs nothing, and the whole toolchain is
  stdlib on purpose. `art` cannot take that slot without adding a `pip install`
  of a **private** repo to CI, with the token that implies.

  So `art` is run by a person, `web/atlas.webp` and `web/atlas.json` are
  committed as the real artifacts, and `build_web.py` stops calling the packer.
  AXI keeps its dependency-free build; this tool stays free to use Pillow,
  numpy and click the way `DnD-CLI` does. That is a one-line deletion in
  `build_web.py` and it is a prerequisite, not a side effect.

- **Editing the game.** `art` writes the atlas and vends the reader. Rewriting
  `Sprites` in `game.js` to use them is hand work in AXI, and should be — a
  tool that edits its consumer's source is a tool you cannot trust.

---

# The artifact, the runtime, and the preview

## Generated files are never hand-edited

One rule underneath all of this: `art.yaml` is source, `atlas.json` is build
output. Tuning a walk cycle in the preview writes **back to `art.yaml`**, and
`pack` emits it forward into `atlas.json`. Nothing is typed into a generated
file, because `pack` overwrites it.

That is the answer to "store the timing in JSON?" — it ends up in JSON, but it
is never authored there.

## The atlas format

Today AXI's atlas is `{image, w, h, <sheet>: {<anim>: [[x, y, w, h, lift], …]}}`,
where `lift` is how far the frame rides above its row's baseline. That fifth
number is the good idea in the current pipeline and it survives: it is what
gives the run cycle its bounce back after trimming.

Two things get fixed.

**The scale constants stop being duplicated.** `game.js` currently computes
`axiScale = 1.15 / atlas.axi.idle[0][3]` — the height in tiles is a literal in
the JS, and the divisor is whatever height the first idle frame happened to
come out. Redraw the idle and every sprite in the game silently changes size.
`height_tiles` already lives in `art.yaml`, so `pack` emits it, and the runtime
reads it. One number, one place.

**The shape follows Aseprite's.** Frame rects, per-frame duration, and named
animation ranges are a solved problem with a de facto standard, and engines
have importers for it. Matching that shape costs nothing now and is what makes
a sheet portable to MANTIS, or to Godot, without writing an importer. The
things only this pipeline knows — `lift`, `height_tiles`, the content box, the
tile unit — go in a namespaced block rather than bent into fields that already
mean something else. *(Worth verifying the exact dialect against a real
importer before this is locked.)*

```jsonc
{
  "format": 1,
  "image": "atlas.webp",
  "size": {"w": 2048, "h": 2377},
  "tile_px": 192,                      // what the art was drawn for
  "subjects": {
    "masie": {
      "kind": "character",
      "height_tiles": 1.15,            // was a literal in game.js
      "anims": {
        "run": {
          "fps": 14,                   // a default, not a decision
          "loop": "forward",           // forward | pingpong | once
          "frames": [
            {"x": 791, "y": 1753, "w": 110, "h": 79, "lift": 3}
            // "ms": 220 on a frame overrides fps, for a hold on a landing
          ]
        }
      }
    }
  }
}
```

## The runtime: the tool vends the reader

`art runtime --emit web/sprite.js` writes the loader for the format the tool
writes. Not a package to install and keep in step — the generator ships its own
reader, so the two cannot drift, and each game vendors a copy it can edit.

```js
const sheet = await Sprite.load('atlas.json');     // reads atlas.webp too
const masie = sheet.actor('masie');                // knows height_tiles
masie.play('run');                                 // fps from the file
masie.play('run', {fps: 22});                      // the game overrides
masie.draw(ctx, x, y, {tile_px: view.tile});       // scales itself, lift applied
```

The file carries **defaults**; the call site wins. Anything the tool can
measure belongs in the JSON; anything the game decides at runtime — current
speed, whether it loops right now, tint, flip — never does.

## `art view` — and bare `art`

`art` with no subcommand runs `art view`, the way `dnd` with no subcommand
starts a session. Run it in a game folder and it finds the nearest `art.yaml`
above you, builds if the atlas is stale, serves a page and opens it.

The preview is not a zoom slider. It shows the art at **real device pixels per
tile**, from the same table the spec is built on:

| | iPhone SE | iPhone 15 | 1080p | target | 5K iMac |
| --- | --- | --- | --- | --- | --- |
| px/tile | 83 | 131 | 120 | **192** | 320 |

with the upscale factor printed live beside each one — `1.7× up`, the same
number `audit` reports. "Is this pixelated?" is only answerable at a real device
size, so the preview and the audit are the same measurement, shown two ways.

Also on the page: a speed slider per animation, a **baseline overlay** (the
row's ground line, so a bobbing frame is visible rather than inferred), onion
skin, and a file watcher that re-cuts and reloads when a sheet changes on disk.
Changes made in the page are written back to `art.yaml` on save.

## Extensible without being limiting

The line is: **close what has to agree, open everything else.**

Closed, because the tool does arithmetic with it — `kind` is
`character | tile | prop`, and `format` is an integer. A fourth kind would mean
`plan` and `check` disagree about a size, which is the exact failure this whole
design exists to prevent. A new kind is a change to the tool, on purpose.

Open, and passed through untouched:

- `meta:` on any subject in `art.yaml` lands in `atlas.json` verbatim. Hitboxes,
  damage frames, sound cues, whatever the next game needs. The tool never reads
  it and never drops it.
- `tags:` for selection — `art cut --tag boss`, `art audit --tag world1`.
- unknown keys are **preserved on write**, the way `artsource.py` puts back only
  the art keys it owns so that round-tripping cannot silently delete a campaign.
- `--from` at every stage, so a sheet made by hand anywhere still flows through.
- `art pack --emit <plugin>` for a project that needs a different atlas dialect,
  rather than teaching the core about every engine.

The version field is what makes this safe: a runtime that reads `format: 1` can
refuse `format: 2` loudly instead of drawing garbage.

---

# Fixing AXI, in the verbs

This is the design's test. If the surface cannot express this job, the surface
is wrong.

## The size of the job, measured

203 frames ship today across 6 sheets — 142 of character animation, plus 61
terrain and decor entries of one frame each. At one character per sheet and a
2048² canvas, the same content wants about **nineteen**:

| | today | frames | sheets at 2048² |
| --- | --- | --- | --- |
| Masie | 1 shared sheet | 47 in 9 anims | **3** (6×4, 4 anims of 6) |
| Mudbug, Glowgrub, Dragonfly, Nibbler | 1 shared sheet | 27 | **4** — one each |
| Mr Frog | ⅓ of a shared sheet | 36 in 6 anims | **2** |
| Sir Croaks | 1 sheet (already right) | 32 in 8 anims | **4** (3×3) |
| terrain + decor | 2 tilesets | 61 entries | **~6** (8×8 grid, 3×2 decor) |

Nineteen generations is the real cost of this, and no tool removes it. What the
tool removes is everything around it.

## The sequence

```sh
cd axi

art init                 # art.yaml from the sheets and atlas already here
art audit                # §2's table: what is undersized, per device
art status               # nineteen sheets, all `todo`

art plan masie-move      # 2048², 6×4, 341×512 cells, 240 px minimum
art prompt masie-move    # the prompt, §7's rules as Constraints
art draw masie-move      # → candidates, or skip and use --from
art view masie-move      # at 83 / 131 / 192 / 320 px per tile, against the old
art accept masie-move 2  # keep candidate 2
art cut masie-move       # magenta key, soft ramp, unspill, split, measure
art check masie-move     # the seven rules; nonzero if it broke one

art status               # 1 of 19 done — repeat 18 times

art pack                 # atlas.webp + atlas.json
art runtime --emit web/sprite.js
```

Then, by hand in AXI, because a tool should not edit its consumer:

- `Sprites` in `game.js` reads `sprite.js` instead of indexing raw arrays, and
  drops the hardcoded `1.15 / atlas.axi.idle[0][3]` scale constants;
- `game.js:2865` loads `atlas.webp`;
- `build_web.py:28` stops calling `pack_atlas.py`;
- `pack_atlas.py` and `build_atlas.py` are deleted, their algorithms having moved.

## The part the first draft got wrong: this is not one change

Nineteen sheets cannot land at once, so **the atlas has to hold old and new art
at the same time** — Masie at 240 px beside a 45 px Mr Frog — for as long as the
job takes. That makes state a first-class field, not a nicety:

```yaml
subjects:
  masie:   {state: accepted, …}   # redrawn at 192, checked, packed
  mr-frog: {state: legacy,   …}   # still the old art; audit counts it, check spares it
```

`check --all` fails on an `accepted` subject that breaks a rule and stays quiet
about a `legacy` one, so the build can be green throughout a migration that
takes weeks. `audit` ignores the distinction entirely — it always reports the
truth, which is the number that should be embarrassing until it is zero.

`status` is the hub that makes nineteen tractable: what is `todo`, what is
`drawn` and waiting on a decision, what is `accepted`, and what is `stale`
because its sheet changed on disk after it was cut.

## Where the tool genuinely does not help

- It does not draw. Nineteen 2048² generations is human and generator time.
- It does not pick. `accept` records a judgement; it cannot make one.
- It does not rewrite `game.js`, and should not.
- One character per sheet means **more files, not fewer** — 19 sources instead
  of 6. That is the trade the spec already made, and the tool's job is to make
  19 cheaper to manage than 6 are today, not to pretend they are the same.

---

# One facing, and showing the model what it should look like

## One facing

A 2D game mirrors a sprite horizontally at draw time — AXI does it at
`game.js:727` with `ctx.scale(-1, 1)`. So a sheet drawn facing right already
covers left, and asking a generator for a turnaround doubles the bill for
nothing. `mirror: true` is the default and `plan` counts one facing.

The exception is asymmetry, and it is a real one: mirroring flips *everything*.
An eye patch changes eyes, a sash swaps shoulders, a held tool moves hand. A
subject like that sets `mirror: false`, genuinely needs both facings, and the
budget doubles because the art requires it rather than because a generator
volunteered it.

Worth being precise about what is *not* wasted today: AXI's `AXI_LEFT` and
`AXI_RIGHT` are the left and right **halves of the sheet** (x 0–800 and
800–1536), holding different animations. They are not facings. The current
sheets already store one direction.

## How many sheets, and the trade `--tight` makes

Rows are animations, columns are frames — an animation per row is what lets a
row share one ground line, which is what the cutter measures against.

The spec puts **four animations on a character sheet**. That is a flat choice,
not arithmetic: 6×4 for Masie, 7×4 for an enemy and 6×4 for a friend are all
"four animations". Packing more rows technically clears the minimum height —
seven rows of Masie fit at 2048, giving 292px cells against her 240px minimum —
while leaving almost nothing for a jump pose that is taller than an idle. That
is the failure the spec warns about: *fewer frames per image, not smaller
frames.*

So the spec layout is the default, `--tight` opts into the trade knowingly, and
`plan` prints what each costs. For AXI: **12 generations** at the spec layout,
10 at `--tight`.

## References: four roles, not "inspiration"

`codex exec -i/--image FILE` attaches images, and they arrive numbered, so a
prompt can say "Image 1" and mean it. That numbering only works if each image
has a stated job, so a reference is always one of four:

| role | what the prompt says about it |
| --- | --- |
| `style` | match brushwork, palette, line weight, outline — not subject or composition |
| `identity` | this is the character; keep markings, colours, silhouette, costume |
| `revise` | the sheet being changed; keep every row not named identical |
| `pose` | follow this layout and posing |

`identity` is the one that matters for AXI, and it carries a warning the others
do not need: **ignore the resolution.** Mr Frog is 45×45 today — that is the
bug — but that sheet is still the only statement of what Mr Frog looks like.
Attaching it without saying so invites a redraw that faithfully reproduces 45
pixels.

Because forgetting it is how a redraw comes back as a *different* frog, a
subject still on its old art attaches its own sheet automatically:

```yaml
style_ref: art/refs/axi-style.png       # every prompt carries this

subjects:
  frog:
    state: legacy
    source: {group: npc, sheet: assets/sprites/npc_sheet.png}
    # → references: identity=npc_sheet.png, with no flag typed
```

Adding an animation to a character already redrawn is the same mechanism with a
different role: the accepted sheet goes in as `revise`, the prompt names only
the new row, and everything else is told to stay identical. That is how twelve
separate generations stay one character — and `plan` prints a warning when a
subject would be generated with nothing attached at all.

---

# Seamless edges, and what the real art said about them

Terrain is drawn edge to edge and then repeated, so the right column has to
continue into the left column of the next copy. A seam is the most visible art
bug there is, because it is *regular* — it draws a grid across the ground.

Testing it by comparing the two edge columns for equality is wrong: painterly
art is never equal anywhere, so a tile that wrapped perfectly would fail. What
matters is whether the step **at the wrap** is bigger than the steps the image
makes everywhere else. So the wrap difference is scored against the tile's own
median column-to-column difference. About 1× reads as continuous; large is a
line.

## The axis, which the data forced

The first version scored both wraps for every tile, and AXI's ground came back
as a catastrophic failure — 11× on the vertical. It was right about the pixels
and wrong about the art: a ground tile has grass on top and dirt underneath. It
repeats sideways and is never stacked, so its vertical "seam" is the drawing
working correctly.

So `seamless` takes an axis, and only `both` means both:

```yaml
ground: {seamless: horizontal}   # repeats sideways, never stacked
water:  {seamless: both}         # stacked in columns as well
tree:   {}                       # decor does not tile at all
```

Pointed at what AXI ships today, with the axes set:

| tile | h-wrap | v-wrap | |
| --- | --- | --- | --- |
| grass | 0.4× | — | seamless |
| ground | 2.8× | — | soft seam |
| ground_alt | 5.4× | — | **SEAM** |
| ground_wide | 6.3× | — | **SEAM** |
| water | 1.0× | 14.8× | **SEAM** (it is stacked in columns) |

A transparent margin is reported separately, because a tile that does not fill
its cell leaves a gap that reads as a seam even when the art itself wraps.

## Style benchmarks

`style_ref` is project-level and every prompt carries it. For AXI it is Masie's
sheet, Sir Croaks' and Mr Frog's — the three the author names as the look.

That created the first bug the tool found in itself. `npc_sheet.png` is both a
style benchmark *and* the only statement of who Mr Frog is, and de-duplicating
by path silently dropped the second role: the frog's redraw would have gone out
with no identity reference at all. Roles now have precedence — `revise` over
`identity` over `pose` over `style` — because telling a model to ignore the
subject of the very image it is drawing from is worse than attaching nothing.

---

# What the first real generation taught

One sheet, Mr Frog, three rows, three references. It came back usable, and it
came back wrong in a way worth writing down.

## The canvas is 1254, not 2048

The prompt asked for 2048×2048. `gpt-image` returned **1254×1254**, which is
the same size `DnD-CLI` records for its actor plates. The requested canvas is
not a request the media service honours.

Everything in the spec's §5 sheet-layout table is built on 2048, so those grids
describe a canvas this generator does not produce. `canvas:` is now a measured
number with a default of 1254, and it is per-project because another backend
will answer differently.

## Columns are what cap sprite size

At 1254 square with six columns, a cell is 209px wide. The frog came back
**189–207px tall** against a 220px minimum — not because the model drew small,
but because it could not draw bigger without frames colliding.

`plan` had the check for this all along, and it fires the moment the canvas is
honest:

```
· `frog`: 6 columns leaves 209px of width for 220px art
  -- split the longest animation or raise the canvas
```

So the spec's advice generalises with a sharper edge: *fewer frames per image*
means **fewer columns**. Four columns of the same canvas gives 313px cells and
clears the minimum with room. Six does not, at any row count.

## It still fixed the problem

Mr Frog ships today at **45×45**. The candidate is **~195px tall** — 4.3× the
linear size and about nineteen times the pixel area. Against the 192px-per-tile
target he goes from 4.7× upscaled on a MacBook to 1.13×. Short of spec, and
unrecognisably better.

## What the sheet got right, and what it did not

Right, and all of it is a rule from §7 that held: flat magenta backdrop, every
frame facing right with no turnaround, no labels copied from the three
reference sheets, nothing in frame but the character, one consistent character
across eighteen frames, and a hop arc in row 2 that reads in order.

Wrong: two frames in the hop row touch and merge — §7.6, found by measurement
rather than by eye. And `idle` and `sit` came back nearly indistinguishable,
which is a prompt problem rather than a drawing problem: for a frog those
poses genuinely are similar, and the row descriptions have to say what
separates them.

## Reading the game first is worth a generation

`game.js:2502` only ever draws three of Mr Frog's six rows. `walk`, `run` and
`hurt` are in the shipped atlas and unreachable -- frogs hop, which is the
whole of their movement model, and he is a friend who never takes damage.
Planning from what the code draws rather than from what the old sheet holds cut
him from two sheets to one before anything was spent.

---

# `art view`

A terminal cannot answer the question this tool exists to answer. So the
preview serves a page and opens it, and the page draws to a canvas **exactly
the way the game does**: one scale for the whole set derived from the reference
frame, `lift` applied per frame. If it looks wrong here it looks wrong in the
game.

It shows **what ships today beside the candidate**, because the useful question
is never "is this good" but "is this better, and by how much". Both are scaled
by their own reference frame, so the comparison is the one a player would see.

The resolution picker is the device table, not a zoom slider — 83, 131, 192,
320 — with the upscale factor printed live under each variant in the same
green/red `audit` uses. Also on the page: a speed slider, a **baseline overlay**
so a bobbing frame is visible rather than inferred, and a frame box.

Rows that have a candidate sort first. The ones that do not are still listed,
which is how Mr Frog's preview shows `hurt`, `run` and `walk` as `today` only —
a standing reminder that three of his six animations are art nobody can reach.

The detector behind it is `cut.py`, and it is the same code the `cut` verb will
use: background found by colour distance as a **ramp, never a threshold**, then
frames found by gaps — rows first, then frames within a row. That is why the
sheet rules demand 24px of clear background: the gap *is* the delimiter. When
two frames touch, the detector merges them rather than inventing a boundary the
art does not contain, which is exactly what it did to the hop row of the first
generated sheet.

## Two things the first preview got wrong

Looking at it on screen found both immediately, which is the argument for the
preview existing.

**Every candidate frame sat in a rectangle of magenta.** The page was handed the
raw sheet. The alpha was being computed and then thrown away -- detection used
it, drawing did not. `cut.keyed()` now returns the sheet as RGBA, backdrop
ramped out and spill pulled back, and that is what is served. Anything
downstream draws the keyed image; nothing draws the plate.

**The hop row showed two frogs in one frame.** The generator left **5px**
between two frames where the rules ask for 24, so they merged into a 421px box
beside neighbours half that width.

Lowering the gap threshold globally would be the wrong fix: a frame whose own
limbs are separated would start splitting in half. The right fix is that the
plan already knows how many columns a row should have. `find_rows(expect=n)`
relaxes the gap only until that count is reached, which cannot over-split
because the count is the thing being satisfied. At `expect=6` the hop row
splits at a 4px gap and every row comes back complete.

A row that still cannot reach its count is returned short and marked
`complete = False` rather than forced, and the preview prints which rows those
are. Silently cutting a frame in a place the art does not contain would be
worse than reporting that the sheet broke a rule.

---

# Frames you can step, flag, and animate procedurally

## Stepping and numbers

Rows have different frame counts, so "frame 3" only means something inside one
row — transport is per row, not global. Each row gets a scrub slider, step
buttons, and its number printed under **both** variants, so "frame 4 of jump"
names the same thing in the preview, in `art issues` and in the prompt.

Arrow keys step every row at once; space toggles play. Touching a scrub pauses,
because you reached for it to look at something.

## Flagging a bad frame

The page is where a bad frame is actually noticed, so it is where the note is
written. A flag POSTs to the preview's own server and lands in **art.yaml** —
source, not build output, so it survives:

```yaml
frog:
  issues:
    - {anim: jump, frame: 4, note: back foot clipped at the ankle}
```

`art issues` lists them, `art issues frog --clear jump:4` drops one, and the
next `art draw` folds them into the prompt as *"Fix these specifically and keep
everything else identical — in the jump row, frame 4 (counting from 0): back
foot clipped at the ankle."* A note written while looking at the frame reaches
the generator without being retyped, and a flagged frame is outlined in the
preview so it is findable again.

## Retired animations

`game.js:2502` can only ever select `sit`, `jump` or `idle` for Mr Frog. The
other three are art nobody can reach:

```yaml
frog:
  retired: [hurt, run, walk]
```

Retired rows are not previewed, not planned, and will not be packed. The pixels
leave the atlas when `art pack` takes over — the current packer asserts that its
row names match the rows it detects on the sheet, so it cannot simply be told to
emit fewer.

## Effects: motion without frames

An effect is **metadata, not pixels**. A breathing idle costs one drawn frame
and a line of YAML instead of six drawn frames, which matters when every frame
comes out of a finite generation allowance — and a sine has no seam when it
loops.

AXI already does this by hand. The Frog King breathes at `game.js:2470`: *"he
breathes rather than floats: the sprite is anchored at his feet, so a small
pulse in scale swells him upwards and leaves him planted."* That comment is the
design, and **anchoring is the whole of it** — a sprite that scales about its
centre lifts off the ground, and a cattail that rotates about its middle
detaches from the soil.

| effect | anchor | for |
| --- | --- | --- |
| `breathe` | feet | a scale pulse; anything alive standing still |
| `sway` | feet | rotation about the base; wind in a cattail, reed, tree |
| `bob` | free | vertical float; a lily pad, a hovering enemy |
| `throb` | free | opacity pulse; glow, an aura, something charging |

The set is **closed**, like `kind`, because whatever draws the sprite has to
implement it: an invented name would move in the preview and not in the game.
Parameters are range-checked, so `amount: 9` is refused rather than producing a
frog that inflates to fill the screen.

`phase` keeps identical props out of lockstep — a row of cattails seeded from
its x position reads as wind; the same row in unison reads as a texture.

They are tuned **in the preview**, with a slider per parameter and a Save that
writes back to art.yaml. That is the loop the whole tool is shaped around:
generated art is expensive and slow, and everything that can be adjusted
without regenerating should be adjustable while looking at it.


---

# Consolidating `sit` into `idle`

Mr Frog had two resting rows. In the code they meant different things: `sit`
is terminal, set once at `game.js:1788` when he reaches his lily pad and
finishes speaking -- *"he lives here now"* -- and `idle` is everything else
on the ground.

In the art they meant nothing. Measured off the generated sheet, `idle[0]` and
`sit[0]` overlap **95.7%** by silhouette, at the same heights, with the same
three beats. The original 45px sheet has the same problem, so the generator
faithfully reproduced an ambiguity that was already in the reference -- which
is what an `identity` reference is supposed to do.

Two identical rows is a row of every sheet spent on nothing, and at six
columns per row that is a sixth of the character's pixels. So they are one row
now, and `idle` is the survivor: it plays for essentially the whole level,
while `sit` is a single moment at the end.

The `game.js` change is three lines to one:

```js
const row = f.vy !== 0 ? 'jump' : 'idle';
```

`friendSettled` keeps its other two jobs -- it is what stops him moving and
turns him around -- so that he has arrived is still told, by where he is
standing and which way he faces, rather than by a second drawing of the same
pose.

Retiring a row the game still asks for would have been worse than leaving it:
`drawFriend` returns early when `S.row()` comes back empty, so the frog would
have vanished the moment he settled. Consolidation is a change to both the
profile and the code, never to the profile alone.

A sheet drawn before an animation list changed still carries the extra row.
The preview names it `unassigned row N` rather than `row3`, and says why:
hiding it behind a positional name is how a stale row gets packed.

---

# Masie, and the backdrop rule the spec already had

## The walk was never a walk

Her `run` row, laid on a shared baseline, is a **float**: body horizontal,
limbs tucked, nothing touching the ground. Every ground pose on her sheet is
drawn the same way — she is a swimming axolotl in all of them. "Her feet do not
stay on the baseline" was not a rigging bug; the feet were never down.

So the row description does the work: a diagonal gait, front-left with
back-right, legs under the body rather than splayed, belly clear of the ground,
lifted feet staying low. Stated as anatomy, because "make her walk properly" is
not a thing a generator can act on.

## One animation across a grid

Masie is **wider than she is tall** — her frames run about 1.4:1. Six frames in
one row of a 1254px canvas is a 209px cell for art that has to be 240px tall,
so the frames get clipped rather than small. Three columns of two rows gives
her 418px.

`sheets: {masie-run: {anims: [run], cols: 3}}` lays one animation across the
whole grid. The cutter reads rows top to bottom and frames left to right, so
concatenating restores the order — which only holds because the sheet carries a
single animation, and is why `wrapped` is recorded rather than inferred.

## The backdrop is a fact about the character

The spec's first rule is that a backdrop must be **a colour the artwork never
uses**. The project set magenta once and every subject inherited it. Masie is
pink.

Despill pulls a pixel's key-dominant channel back toward the channels the key
does not use. Magenta's dominant channel is red. So is hers. Measured on her
own sheet:

| backdrop | of Masie's pixels damaged | of Mr Frog's |
| --- | --- | --- |
| green | **0.0%** | 63.9% |
| blue | 6.7% | **0.6%** |
| magenta | **78.5%** | 17.1% |

The first generation came back a **grey** axolotl, and it was not only the
model: the keyer was pulling her red channel down by 21 on 70% of her pixels.
Her own colour read as spill.

So `backdrop` is per subject, and `plan` measures the chosen one against the
identity reference and refuses to stay quiet:

```
backdrop: #FC309B would despill 78% of this character's own pixels
  -- its dominant channel is the character's too. Try green (#00FF00).
```

On green: despill damage 1.5%, and she is pink again. The check now runs before
a generation is spent, which is where it belongs — this one cost an image to
learn.

## Two contradictions the prompt was carrying

Reading the assembled prompt before spending caught both:

- *"No groundline"* fought *"every frame sits on the same groundline"*. It now
  says do not **draw** one, but align every frame as though standing on the
  same invisible one.
- `identity` said *"keep the silhouette exactly"* while the entire job was to
  change her silhouette from floating to walking. It now says identity means
  **who**, never which pose, and that where the reference and the description
  disagree the description wins.

A subject's own sheet is also no longer attached as its own `style` reference,
since that instruction says "do not copy its subject" — nonsense aimed at the
character being drawn.

## Result

288–302px tall against a 240px minimum, every frame's lowest point within 3px
of the shared baseline, four legs under her, belly off the ground, and pink.

## Getting a character back after a redraw drifts

The walk was right and the character was not: a pronounced muzzle where there
had been a flat round snout, blue migrated from the tail fin onto the gills,
and four outlined toes where there had been soft rounded stubs.

Three changes fixed it, and only the first is about the description.

**Say the features, not the species.** "A young axolotl" leaves the face to the
generator. The description now pins the snout shape, states that the nose is a
dot, names the gill colours and says **NO BLUE ON THEM AT ALL -- blue appears
only on her tail fin**, and asks for feet "like little mittens", explicitly
without separated toes or claws. A negative is worth stating when the drift has
already happened once.

**A subject can replace or drop the project's style anchors.** Masie was pointed
at Sir Croaks, who is bold flat cartoon with a heavy black outline. Her own art
is soft, airbrushed and thinly outlined. The style anchor was pulling her away
from herself, so `style_ref: []` plus a per-subject `style` string lets her own
identity reference carry the rendering -- and the `identity` instruction now
says it covers **how she is drawn**, not only who she is.

**`pose` is how a good result survives a bad one.** The second candidate had the
gait right and the face wrong. Passing it as `pose` keeps the walk while
identity and the description rebuild the character, so the fix does not cost
the thing that already worked. That only holds because the role instruction is
specific: *layout and posing only -- not the colours, not the facial features,
not the proportions.* A reference with no stated job would have carried the
mistakes straight back in.

## Limbs vanish, and the fix is a shading convention

Two separate Masie candidates came back with **three legs** in half their
frames. A side-view quadruped occludes its far limbs, and the generator
resolves the overlap by dropping them -- which, animated, is a leg that
flickers in and out six times a second.

It is not a reference problem: candidate 2 and candidate 3 had different
references and the same failure. So it is a sheet rule now, stated the way a
2D artist would state it:

> EVERY limb the character has appears in EVERY frame. Never drop, merge or
> hide a limb behind the body because it overlaps -- draw the far-side limbs in
> a slightly **darker shade** of the same colour so they read as being behind,
> and keep their outline.

That is the standard convention and it worked first try: four legs in all six
frames, the far pair legible as a deeper pink.

## Silhouette aspect catches what "the tail looks short" is really about

The tail was reported short. It was not, after the description asked for one
reaching back as far as her body -- but the impression survived, and measuring
the silhouette says why:

| | width / height |
| --- | --- |
| original Masie | **1.61** |
| candidate | **1.29** |

She is standing *taller and narrower* than she used to be, because the walk
direction told her to stand up on four legs with her belly clear of the
ground. A tail of the same length reads shorter against a taller body.

The lesson is that a proportion note belongs beside a posture note: telling a
character to stand up will make it taller unless the description also says how
long and how low it is. Aspect ratio is cheap to measure off the identity
reference and is the number that catches it.

---

# Animating a character that is not a mammal

Masie's run took seven generations. Most of them failed for reasons worth
writing down, because none of them were about image quality.

## Name the animal, then check the gait against it

"A four-legged walk cycle" produced a mammal. Salamanders do not move like
mammals, and the differences are all things a description can state:

- **Limbs SPRAWL.** The upper leg comes out sideways and bends down at elbow
  and knee. Not tucked vertically underneath like a dog's — which is what
  "legs underneath her carrying her weight" asked for, and got.
- **No flight phase.** Salamanders never bound and never have all four feet off
  the ground. An early attempt asked for an airborne frame; that is a gallop,
  and gallops belong to animals with a flexible spine in the vertical plane.
- **The body does the work.** A travelling wave of lateral undulation, short
  limbs, short stride. The tail counterbalances the trunk's bend.

## The trap: a real gait can be invisible

A salamander trots — diagonal pairs, so the second half of the cycle is the
mirror of the first. **A mirrored pose looks identical from the side.** Half of
a correctly-specified trot is visually redundant in a side-scroller, which is
exactly why the accurate version read as a shuffle.

Worse, the characteristic salamander motion is *lateral*, and lateral motion
does not exist in a side view at all.

So biomechanical accuracy and side-view readability pull against each other,
and the resolution is to keep the anatomy and restructure the cycle around the
one thing a side view can show: **body length**. One continuous wave from most
bunched to fully stretched and back, every frame a different length, explicitly
*not* two mirrored halves.

Stated that way, frame widths went from 390, 390, 391, 394, 390, 387 — six
drawings of one pose — to **304, 381, 473, 375, 353, 330**.

## Per-frame poses

A general description of a cycle produces a general cycle. `anims` takes a
`summary` plus a `frames` list, and each frame is named for what it *is* —
GATHER, UNCOILING, FULLY STRETCHED — with the closing instruction that if two
frames could be swapped without anyone noticing, the cycle is wrong.

This is the only lever that reliably changed the result. Everything else —
references, style, constraints — held the character steady; only naming the
poses made it move.

## A constraint can flatten the thing it protects

"All four legs in every frame" was added to stop limbs vanishing. It worked,
and it also halved the motion: the model satisfied it by drawing the legs in
the same place every time. The rule now says so explicitly — *this is about
never LOSING a limb; it is not a reason to draw them in the same place. Each
frame's pose governs where they go.*

## Known: a wrapped grid can drift between rows

Laying one animation across a grid risks the second row being treated as a
separate drawing. Masie's frames 4–6 came back slightly chunkier, with a
different tail treatment, than 1–3. Worth watching; a single row would not have
this problem, and cannot fit her.

---

# Two things trimmed frames cannot carry, and a template that fixes one

## A frame needs a horizontal anchor, not just a vertical one

`lift` says where the ground is. Nothing said where the character *stood*, so
the game placed each frame by centring its bounding box -- `-w / 2` at
`game.js:728`. That is correct only while every frame is the same width.

AXI's current run frames are 110, 114, 113, 114, 109, 109 -- a 5px spread, so
centring has never caused trouble. Masie's redrawn run stretches from 304px to
473px as her tail streams out behind her, and centring those boxes would swing
her body **59px back and forth every cycle**. She would slide as she ran.

So a frame carries an anchor: the middle of its **footprint**, the lowest
slice where it touches the ground, rather than the middle of a box a tail can
lengthen. `[x, y, w, h, lift]` becomes `[x, y, w, h, lift, anchor]`, and the
game draws the anchor at the character's x instead of the box's middle. A
legacy frame has no sixth number and falls back to centring, which is what it
was drawn for.

This is a `game.js` change when `pack` lands: `-w / 2` becomes `-anchor`.

## A template makes the anchor known instead of inferred

The footprint heuristic works, but it is a guess about where a character
stands. Giving the generator a guide sheet to draw **into** makes it a fact.

`art template <sheet>` writes the canvas at its real size with cell borders, a
groundline in each cell, and a vertical mark where the character stands. The
brief then says: one pose per cell, feet on the line, body straddling the mark.

The risk was that a generator redraws its reference and bakes the guides into
the art. Measured on the first attempt: **0.02%** of the output sat on the
guide colour. It drew into the template rather than copying it. The guides are
a single flat grey nothing else uses precisely so that failure is measurable
rather than something to squint for -- `guide_remnants()` reports it.

What the template bought beyond placement: the two grid rows came back
consistent with each other, which the previous wrapped-grid attempt did not
manage, and the frames no longer crowd their neighbours.

## Anatomy has to be described as shape, not as name

"A broad flat tail fin" produced a thin tube with a fan on the end for three
generations. An axolotl's tail is a laterally flattened paddle with the fin
running its whole length from the hips. Saying that -- *"think of a broad leaf
or an oar blade lying on its side"*, plus explicitly what it is **not** --
fixed it in one.

The same shape applies to limbs: "four legs" is satisfied by a stretched pose
with an extra stray stub. "EXACTLY FOUR, never more... no extra limb or stray
stub anywhere -- a stretched pose must still have four" is the version that
survives an extreme frame.

## Editing a frame instead of regenerating a sheet

Regenerating a sheet to remove one stray stub costs an image **and rerolls five
frames that were already right**. That trade is bad often enough that the frame
is editable where it is looked at: click it in the preview and it opens at its
native resolution on a checkerboard, with an eraser, a size slider, undo and
reset.

A saved edit goes to `art/edits/<subject>/<anim>-<frame>.png` — **beside** the
candidate, never inside it, so the generated sheet stays the untouched record of
what actually came back. The preview prefers an edit where one exists and
outlines that frame in green; reopening the preview picks up edits already on
disk.

The eraser alone covers most of what goes wrong at this stage, because the
defects are additive: a leftover limb, a stray stub, a doubled tail. Removing is
usually enough; drawing is not usually needed.

## Flags had no way out, and no sign they were used

Both reported, both true. A flag could be added from the preview and only
removed from the CLI, and nothing on the page said what a flag was for. Each
issue now carries a **remove** button, and the row prints how many flags it holds
and that they will be sent as art direction on the next `art draw`.

They were being used — `draw` folds them into the prompt as *"Fix these
specifically and keep everything else identical"* — but a feature that gives no
sign it is working is one nobody trusts, which is the same as not having it.

---

# Accepting, comparing, and what more frames cost

## `accept`

A generator produces variations and picking one is a judgement, so `accept`
**records** it rather than makes it. The chosen file is copied to
`art/sheets/<sheet>.png` and every candidate stays where it is — the point of
accepting is to have something the next `art draw` cannot lose. It also sets the
subject to `state: accepted`, which is what makes `check` start holding it to
the rules.

## Comparison is open-ended

Which two versions matter is not knowable when the page is built, and
relaunching to see a third loses whatever was set up on the page. So the preview
takes `--candidate` repeatedly, shows the accepted sheet automatically beside
`today`, and carries a **compare another version…** control that cuts any sheet
in the project on demand and adds a column to every row.

Each version is normalised to the same apparent size, so a three-way comparison
is about the art rather than about scale. Hand edits apply to the newest version
only; the earlier ones are there to judge against.

## The pose list is the authority on frame count

The atlas says how many frames the **old** animation had, which is exactly what
is being changed when someone writes ten poses for a six-frame cycle. So a
written `frames` list sets the count, and the grid follows from it.

## Ten frames cost resolution, and the trade is worth stating

At a fixed 1254px canvas, frames and pixels-per-frame trade directly:

| | grid | cell | drawn height |
| --- | --- | --- | --- |
| 6 frames | 3×2 | 418×627 | 186–257px |
| 10 frames | 3×4 | 418×313 | **149–201px** |

About 20% smaller, for a cycle that reads as continuous instead of stepped.
Widths arc 292 → 409 → 319 and heights mirror them, which is the smooth wave
that six frames could only approximate.

Whether that trade is right depends on the animation: a run that plays at 14fps
and fills the screen for the whole level is a different question from a hurt
flash that plays five frames once. It is not a decision the tool should make,
so it makes both easy to look at instead.

## Comparing versions that have different frame counts

Six drawn frames and ten drawn frames are the **same action**, so the transport
cannot be a frame index. It was one, taken from the first version on the row,
which meant a ten-frame cycle shown beside a six-frame one only ever displayed
its first six frames — the other four were unreachable and invisible.

The transport is the cycle's **phase** instead, and each version maps that phase
onto its own frames. At 40% through the cycle a ten-frame version is on frame 5
and a six-frame version is on frame 3. The scrub's granularity is the *longest*
version on the row, so every frame of every version can be stepped to, and each
caption reads `frame 5/10` rather than a shared number that means different
things in different columns.

Speed then splits into two honest questions, so there is a **Sync speed** toggle:

- **On** (default): every version completes its loop in the same time, so the
  comparison is about the motion — is ten frames actually smoother than six?
- **Off**: every version advances one frame per tick at the chosen fps, which is
  what a game with a fixed `ANIM.fps` would do — so a ten-frame cycle takes
  longer and runs slower. That is the question of whether the *game* needs
  retiming, which is separate.

Flags and hand edits resolve against the version being worked on, not the row,
since a frame number only means something inside one version.

## The preview page is code, so it is parsed before it ships

A syntax error anywhere in a `<script>` block kills the **whole** block. The
symptom is a page that renders its static HTML and nothing else: the title, the
toolbar and the buttons all present, and no device buttons, no rows, no
animations — and no error unless someone opens a console.

That happened, to a `let syncSpeed` that was first written as `let sync` beside
an existing `function sync()`. Two correct-looking edits, one dead page.

So the page's script is extracted and run through `node --check` in the tests,
skipped when node is not installed, plus a check that nothing is declared twice
at the top level. Shipping a page that renders blank is worse than shipping one
that is ugly, because blank looks like the tool is broken rather than the page.

## The upscale number is about sharpness, and the caption has to say so

Every version on a row is normalised to the same apparent size, so the `×`
beside it is **not** a scale — it is how far that version's source pixels are
stretched to reach that size. Two versions of the same action showing `0.33×`
and `0.43×` is not an inconsistency: the second genuinely has fewer pixels per
frame, which is the thing being compared.

The caption now prints the tallest source frame beside the factor
(`257px src · 0.33×`), because a bare number invites reading it as a size.

Normalisation is on the **tallest** frame of each version rather than the mean.
A cycle's mean height depends on how many stretched poses it happens to
contain, so a ten-frame version with more low frames would report as smaller
than a six-frame one drawn at the same scale. The tallest frame is the most
upright pose in the set, which is the nearest thing to the idle frame a game
would really scale by.

## Exaggeration has an upper bound, and it is a shape

"Build the cycle on body length" fixed a static run and then overshot: her torso
swung 40% across the cycle and she read as a stretching weasel rather than a
chubby axolotl.

The fix was to name the limit and move the motion: *the change in her body
length is SLIGHT -- about one part in eight, a springy gather and release, not a
stretch. Her legs and her tail do the moving; her torso barely changes.* Plus
the shape it must keep -- small, round, chubby, never long and thin.

Swing went 40% → **10%**, and she came back **taller** as a side effect: 246px
against 201px, because a body that does not stretch sideways fits more of the
cell vertically. Less exaggeration bought both a better silhouette and better
resolution.

---

# `pack`: merging a redraw into an atlas that already ships

A redraw happens one character at a time, so packing cannot mean "rebuild
everything from the new art" — most of the art is still the old art, and the old
packer is the only thing that knows how to cut it. So `pack` **merges**: the
existing atlas is kept whole, new frames are appended below it, and only the
animations that were redrawn are repointed.

Two things have to be recorded for mixed-resolution art to be drawable.

## Scale, and the trap in computing it

A game derives ONE scale per character from a reference frame — AXI uses
`1.15 / atlas.axi.idle[0][3]` — and applies it to every row. Masie's run came
back at 246px against an idle still drawn at 90px, so dropped in untouched it
would have rendered **three times too big**.

So each replaced row carries a multiplier. The obvious formula, old height over
new height, is wrong: when the reference row is **itself** redrawn the base
scale moves with it and no correction is needed at all. The frog's `idle` is his
own reference, so replacing it self-corrects at ×1.0; Masie's idle is untouched,
so her run needs the full ×0.329.

The right quantity is the row's height *relative to its reference*, preserved:

```
multiplier = (old_row_top / old_ref) / (new_row_top / new_ref)
```

Verified on the packed atlas at 131px per tile — drawn sizes before and after:

| row | drawn before | drawn after | source pixels |
| --- | --- | --- | --- |
| axi/run | 132px | 133px | 81 → 246 (**3.0×**) |
| npc/frog_idle | 138px | 138px | 45 → 199 (**4.4×**) |
| axi/idle | 151px | 151px | unchanged |

Same size on screen, three to four times the pixels. That is what a resolution
fix should look like from the game's side: nothing moves.

## The two changes the game needs

```js
const mul = (this.a.scales && this.a.scales[group + '/' + name]) || 1;
scale *= mul;
const anchor = (f.length > 5 ? f[5] : f[2] / 2) * scale * ts;
```

Both degrade correctly: a row with no `scales` entry and frames with no sixth
number are drawn exactly as before, which is most of the atlas.

## And the prerequisite that finally came due

`build_web.py:28` called `pack_atlas.py` on every build, which would have
regenerated the atlas from the old concept sheets and thrown away the redraw.
That call is commented out, with the reason, and the committed atlas is the
artifact now — as designed several turns ago, when it was still theoretical.

---

# Registration, and the head jerking back and forth

A sprite's anchor is the **registration point** of traditional animation: the
peg hole every drawing lines up on. Choose it badly and the error shows up as
jitter in whatever it is *not* tracking.

`cut` anchored on the **footprint** — the middle of the contact patch — which is
correct for a standing pose and wrong for a run, because **the feet are the part
that moves most.** Holding them still swings everything else. Measured on
Masie's ten-frame run, her head travelled **35px** per cycle relative to the
anchor, on a character drawn 246px tall. That is the whiplash.

## What a rigged character does, and why the centre of mass wins

In rigged animation the root is the **hips**, not the feet: the pelvis travels
smoothly and the limbs are solved relative to it. Feet plant and lift *against*
the root; they never define it. A sprite's anchor is the same decision, so the
default is now the horizontal **centre of mass**, which is the smoothest thing
on a character by definition.

Measured across the same cycle, head travel relative to each candidate:

| anchor | head swing |
| --- | --- |
| footprint | 35.1px |
| box centre | 38.0px |
| leading edge | 25.0px |
| **centroid** | **11.9px** |

`anchor: centroid | footprint | leading | box` is per subject, because which
landmark is stable is a fact about the character.

## The last of it is per-frame, and always was

A rule gets a cycle most of the way. The remaining 12px was almost entirely
**one frame** sitting further forward than its neighbours — not something a
formula can find, and exactly the judgement an animator made at the peg bar,
sliding a drawing until its arc ran smooth.

So a frame carries a nudge, stored in `art.yaml` and applied by `pack`:

```yaml
masie:
  anchor: centroid
  nudge: {run: {0: [2, 0], 3: [-5, 0], 4: [3, 0], …}}
```

The sheet is never rewritten. The drawing was right; it was hung a few pixels
off. `art view` has an **Align** mode beside the eraser — drag sideways and the
registration line moves with a ghost of where it started.

## Smooth the arc, do not flatten it

The temptation is to pin the head still. That is wrong: a real run has a small
head bob, and removing it entirely reads as rigid. Animators talk about every
part travelling a **smooth arc** — jitter is a point leaving its arc, not a
point moving.

So the nudges were computed against a *smoothed* version of the head's own
path, not a constant. Total swing 35.1 → 11.8 → **5.7px**, and the largest jump
between neighbouring frames — which is what "whiplash" actually is — is
**2.9px**, about 1% of her height.

---

# `review`: the verification a formula cannot do

`rules.py` catches what a formula can catch. Every defect that actually cost a
generation on this project was outside that set:

> a stub protruding from the base of her tail · two frogs in one frame · a
> doubled tail · five legs · gills that drifted blue · a nose that stopped being
> her nose

A person found every one of those by squinting at a 1254px sheet, and that does
not survive sixty-six more subjects.

So `art review` lays the cut frames out as a **numbered contact sheet** and hands
it to a model with the specific list of things that have gone wrong here — not
"look for problems", which gets a general answer, but *count the legs in every
frame*, *any body part drawn twice*, *a stray stub where the body meets the
tail*.

Numbered, because a finding has to be addressable. "Frame 4" is actionable;
"one of the frames" is not. And a numbered finding drops straight into the same
`issues` block the preview writes, so `--flag` turns a review into art direction
for the next `art draw`.

The labels sit in a margin **above** each frame rather than on it, for the same
reason the sheet rules forbid labels in generated art: a label touching the art
is read as part of the character.

## What it found, and what it got wrong

Run against Masie's accepted sheet it reported the tail narrowing at its base
and reading as a terminal fan rather than a full-length paddle — **independently
finding the thing that had already been reported by eye**, and which was only
partly fixed. It also caught a back leg overlapping the tail-base region across
four frames, against a description that explicitly forbids it.

It also claimed a pink cheek spot in every frame. Zoomed in, that is the
specified nose dot. A false positive — and it marked that one `low` while the
others were `high`, which is the right instinct.

So: a strong first pass with some noise. That is why `--flag` is opt-in, why a
failed call raises rather than returning "clean", and why the closing line of a
clean review says *worth a look anyway — it is a second opinion, not a
replacement for one.*

## Effects reach the game

They were previewable and then lost: `pack` did not emit them. It does now, into
`anims["<group>/<row>"].effects`, and `Sprites.draw` applies them anchored at the
feet the way the Frog King already breathed by hand.

One bug worth recording. `phase` names how an offset is *chosen* — `none`, `x`,
`random` — not the offset itself. Adding the string to the wave makes the whole
expression `NaN` and the effect vanishes silently, which is the worst kind of
failure: no error, no motion, nothing to notice.

---

# Finishing a character: what nine sheets taught

Masie's other eight animations and the frog's two, generated in one batch.
Everything below is a failure the batch produced, not a hypothetical.

## The identity reference becomes the character's own accepted sheet

Drawing the remaining eight from the original 45px sheet would have
reintroduced every drift already corrected — the muzzle, the blue gills, the
toes. Pointing `identity` at her **accepted run sheet** instead held one
character across nine sheets. This was the cross-sheet consistency risk flagged
several turns earlier as unproven; it works.

## A wide character needs fewer columns than the arithmetic suggests

Three columns gives 418px cells, and she came back up to **444px wide** in the
stretched poses — so neighbouring frames touched and cut as one. Three sheets
failed that way. Two columns gives 627px of width, and the shorter cells (418)
still leave her well clear of the 240px minimum.

The lesson is that the binding constraint for a wide character is **width per
column**, and it has to be checked against the widest pose, not the standing
one.

## A generator sometimes keys the sheet for you

`masie-defeat` came back as a **transparent PNG** rather than art on a green
plate. Colour-keying that against green finds nothing, the whole sheet reads as
one object, and it cuts into a single 1254px "frame". `cut.read()` now decides
between "flat backdrop" and "already transparent" in one place, which is the
third background mode the design named and never built.

## Described motion gets amplified

Asked for a breath, the idle came back swinging **21.8%** in height — 28% for
the frog — where the old art swung 2.2%. That is not breathing, it is
inflation. The same overshoot took the run's body stretch to 40% when a quarter
was asked for.

So the idles are drawn **static** — *"her body stays exactly the same size in
every frame; the breathing is added by the game, so drawing it here would
double it"* — and the motion comes from the `breathe` effect. The frog's
redrawn idle swings 3%, so his breath is procedural. Masie's still swings 11%,
so **hers is drawn and the effect is removed**: use whichever carries it, never
both, because they add.

## The scale reference moved to its own sheet

With one animation per sheet, the row a character's scale is measured from is
no longer on the sheet being packed. Looking for it there finds nothing and
falls back to the old height, which scaled the frog's jump to **a seventh** of
its size. `pack` now cuts every accepted sheet first, resolves each character's
reference frame across all of them, and only then computes corrections. The
reference row itself takes ×1.0, since the base scale moves with it.

Verified across all eleven rows: every one lands within 0.98–1.00× of the size
it drew before, on 2.7× to 7.6× the source pixels.

## The preview sized its canvas to the wrong thing

`view` derived each canvas from `height_tiles × device px`, which is the
character's **standing** height. A climb is vertical — Masie is two and a half
times taller in it than in her idle — so she was drawn past the bottom of the
box and cut off at the knees.

The canvas now follows the tallest frame the row actually draws, across every
version on it, so the versions still line up.

## "Seen from the side" is not enough for a rotated pose

Her first climb came back **facing the viewer**: three-quarter head, both eyes,
limbs splayed forward. Every other row is a strict profile, and the description
said "seen from the side" — but for a pose rotated a quarter turn, that reads as
a new composition rather than the same one turned.

What worked was saying it as a rotation of the drawing she already is: *strict
side view exactly as in every other row, one eye visible, far-side legs behind
the near ones, the same drawing rotated a quarter turn, nose up, tail hanging
straight down.*

The limb cycle is still subtler than asked for. A climb has no ground contact
and no travel, so the only cue is the limbs passing each other — naming four
feet at four different heights got a profile that reads as climbing, but not yet
a ladder.

## Archiving broke candidate numbering

`archive` empties the live directory, and the next generation numbered from one
again — producing a second `masie-climb-1.png`. `accept` searches both
directories, so it then saw two different sheets claiming the same number.
Numbering counts the archive now.

## An identity reference propagates defects as faithfully as virtues

Masie's other eight sheets were drawn with her **accepted run sheet** as
`identity`, which held one character across nine sheets — and carried its flaws
across them too. `review` reports the same two findings on `idle` that it found
on `run`: the tail narrows at the hips before widening into a fan rather than
being broadest at its base, and the rear legs join at the tail base with no
smooth body between.

Both were already described against, in words, three times. Neither was fixed
before the reference was reused, so all nine sheets inherited them.

The order matters: **fix the reference sheet, then draw from it.** A defect in
the reference is not one sheet's problem, it is every later sheet's problem, and
the cost of noticing late is nine regenerations instead of one.

## A review harness can report itself

The first clean run of `review` reported *"the frame labels, dark header strip
and contact-sheet grid borders remain visible in the artwork"* — describing the
numbering `review` itself draws. A model shown a composite will critique the
composite.

The prompt now says which furniture belongs to the review sheet and that it is
never a defect. Worth remembering for any agentic check that builds its own
input: say what you added, or it will be reported back to you.

---

# Terrain: what the game actually draws

Before asking for a single tile, the same question the frog's six rows raised,
at scale: **which of the 61 terrain and decor entries does the game reference?**

**Twenty-seven.** The other **thirty-four** appear nowhere in `game.js` —
`reed`, `mushroom`, `bridge`, `slope`, `water`, `grass`, the whole `plank`
family, six of the seven lily-pad variants. They are in the atlas, they are
downloaded by every player, and nothing can ever select them.

The scan is safe because every name is a literal: `grassTileAt` returns
`'ground_flower'`, `'ground_alt'` or `'ground_grass'` by name, and the item art
is a ternary of two strings. Nothing is assembled from fragments.

They are `state: retired` now — a subject state, not just an animation one —
so they are planned, audited, checked and packed by nothing, and kept on the
books with the reason.

## The game's sizes disagree with the spec, and the game wins

`ASSET_SPEC.md` says a tree is drawn 3 tiles wide. `game.js` draws it at
**3.6**. A cattail is 1 in the spec and **1.5** in the code. Those numbers come
from `blitStanding(ctx, name, cx, baseY, ts * size)` at each call site, which is
what actually reaches the screen.

So `width_tiles` is read from the code, not the document. The spec is the
intent; the call site is the fact.

## Three kinds of terrain, not one

`init` drafted all 61 as `kind: tile`, which is right for about ten of them.

- **Stretched tiles** — `blit()` fills a cell, so they are exactly one tile and
  must wrap on the axis they repeat: `dirt` and `ruins` both ways, the `ground`
  family horizontally (grass on top, dirt below, never stacked), `water_col` and
  `vine` vertically because they hang in columns.
- **Standing props** — `blitStanding()` draws them a number of tiles **wide**
  with the height following their own aspect: tree 3.6, shrine 3, bank 2.9,
  burrow 2.2, cattail 1.5, pad 1.1, flower and rock 0.8.
- **Parallax bands** — `hill` at 3.4 tiles tall and the clouds at 1.05, each
  repeated across the sky, so they must wrap **horizontally** or the horizon
  shows a seam every screen width.

That third kind did not exist in the design. A band is sized by its height and
tiled by its width, which is neither of the other two.

---

# Tiles: three things the generator cannot do, and one the atlas undid

## A generator cannot draw a seamless tile

Asked plainly, in detail, with the wrap named in its own sentence, AXI's ground
family came back at **13.1x, 9.8x, 5.7x and 4.1x** the tile's own internal step
across the wrap. Rewording will not fix it: the model has no way to reason about
what its right edge will sit next to.

So `seamless.py` does it. Blend the tile with a copy of itself rolled by half,
weighted zero at both edges and one in the middle. At the left edge the result
is entirely the rolled copy -- which there is the tile's own middle -- and at
the right edge it is the column beside that middle. Two columns that were
adjacent in the original become the wrap, so the wrap is continuous **by
construction**. Every tile went to ~1.0x.

The cost is honest: the middle blends with itself, so fine detail softens. For
ground, moss, water and stone that is invisible.

## One axis per SUBJECT was one too few

`seamless:` was written on the subject, and a subject is a whole sheet. AXI's
water is one sheet with two tiles on it and they do not repeat the same way:
the surface carries a crest and only ever repeats sideways, while every tile
below it is stacked as well. One value cannot say both. `both` rolls the crest
into the middle of the surface tile and there is no waterline left; `horizontal`
leaves the body -- the tile the entire pond is made of -- with the 21.8x
vertical seam it started with.

Ground had the same problem and nobody had noticed. `dirt` is described in
art.yaml as "the fill below the surface", the game draws it under every grass
tile, and it was declared `horizontal` along with the grass it shares a sheet
with.

So `seamless:` takes a map as well as a string:

```yaml
terrain_ground: {seamless: horizontal}   # every tile on the sheet
terrain_water:
  seamless:
    water_surface: horizontal            # a crest: never stacked
    water_body: both                     # the pond is made of it
```

A bare string still means every tile on the sheet. Most sheets want that, and
rewriting them would be noise.

## A stack has junctions, not only wraps

Two tiles that are each perfectly seamless still show a line where one sits on
the other, and `check --seams` could not see it: it scores a tile against
itself, and both of them pass. The seam is *between* them and nothing was
measuring it.

It is the wrap problem with the roll left out, so it is solved the same way. A
tile names what it sits on:

```yaml
joins: {water_surface: water_body}   # my bottom edge continues into its top
```

and the bottom band of the surface is blended toward the body, weighted one
above the band and zero at the last row. The surface's last row is then the
body's last row -- and the body's last row already continues into the body's
first, which is what `both` bought. So surface-on-body is the same junction as
body-on-body, by construction rather than by luck.

`check --seams` scores it too, in a `joint` column, so a join that was declared
and never built shows up instead of being assumed. The order matters and is
enforced by doing it in two passes: every tile is made seamless first, then the
joins are blended, because a join to a tile that has not been healed yet copies
the unhealed edge.

## Lossy compression undoes it, and the gutter is why

Packed, `water_col` measured **10.0x** again -- from 1.1x. Compressed on its own
it measured 2.4x, so the compression was not the whole story: **its neighbours
in the atlas were bleeding across its edges.** WebP works in 16px blocks and
will average a tile's edge together with whatever was packed beside it, and a
seamless tile is exactly where that hurts, because its two edges have to match
each other while the neighbours bleeding in differ on each side.

`GUTTER` was 2px -- enough to stop a draw call sampling a neighbour, nowhere
near a compression block. At **18px**: water_col 10.0x -> 2.2x, vine 4.6x ->
1.6x, for 0.1MB.

## The seam metric needed an absolute floor

Still water varies about **one level** internally, so a two-level wrap -- which
cannot be seen out of 255 -- divides into a ratio of 2.2 and reads as a failure,
while a noisy dirt with a **ten-level** wrap reads as 2.5. Only one of those is a
line on screen. A wrap is seamless now if the ratio is low **or** the absolute
step is under four levels.

## Rules written for characters are wrong for tiles

Three of them, each caught by the gate refusing a sheet:

- **Outline.** The character rule demands one. A tile must NOT have one -- an
  outline becomes a line ruled across the world every time it repeats -- so
  checking for it is backwards.
- **Exact size.** 192x192 is the size a tile is DRAWN at, not stored at. A
  larger source is headroom, not a defect: 192 on a laptop is 320 on a 5K
  display. Square and at least a tile.
- **What "outline" even means.** The rule tested whether the edge was darker
  than the fill, which fails a ground tile -- bright grass over dark earth reads
  as an edge 30 levels *brighter* -- and fails a glassy gem for having a bright
  rim. What actually went wrong on the navy sheet was an outline close enough to
  the backdrop that keying took it too, so that is what is measured now. And it
  measures the KEYED art, not the plate, where every antialiased edge is a blend
  with the backdrop by definition.

---

# `scene`: previewing a landscape as a landscape

`view` is built for animation — rows of frames playing at device sizes — and
none of the questions you ask about terrain fit that shape:

| | its one frame tells you nothing about | so `scene` shows |
| --- | --- | --- |
| a tile | what happens when it **repeats** | a 3-row field of it, with the tile edges toggleable |
| a prop | how big it is **beside the character** | it standing on real ground at its width in tiles, Masie ghosted in at 1.15 |
| a band | whether it seams across a **screen** | it repeated across a screen width, drifting at its parallax speed |

A seam is invisible in one tile and obvious in a field, which is the whole
point: the check reports `ground_alt` at 2.5x and this is where you decide
whether 2.5x is a line you can see.

It reads the **packed atlas**, not the sheets. What ships is what matters, and
the packer is where tiles are made seamless and where compression can undo it —
previewing the sheets would show a seam that the atlas does not have, or hide
one it does.

## Size is a fact about an entry, not a group

Grouping terrain by material — so a dirt matches its own ground — put a width
on the group, and every prop came back 1.0 tiles wide while the sky bands
vanished entirely. A group shares a material, a palette and a light direction.
It does not share a size: a tree is 3.6 tiles across and a gem is 0.6.

So `width_tiles` and `tiles_tall` live on the entry, beside its description,
and `scene` falls back to the group only when an entry does not say.

## Two bugs the sky band surfaced

**A double image.** `cloud` and `cloud_face` were drawn at the same height, at
the same speed, laid edge to edge — so the two layers sat on top of each other
and every cloud in the preview had a face. The game does none of that: it
spaces each layer `w × 3.4 × mul` apart, at `0.5 + 0.7 × mul` tiles down, and
drifts it at `0.15 × mul`. A preview of parallax that does not use the game's
own parallax numbers is not previewing the game.

**Shimmer at low resolution, and why it was only visible there.** Destination
coordinates were fractional, so the browser resampled every frame against a
slightly different pixel grid. At 320px per tile that is invisible; at 83 it
reads as flashing. Positions and sizes are rounded now.

That second one is a genuine trade rather than a fix: whole pixels shimmer less
and judder more, because a band drifting at 0.15 moves in one-pixel steps
instead of continuously. For slow parallax at a low tile size, crisp wins.

Worth noting the game draws its clouds at fractional coordinates too, at
`game.js:2288`. It has always done so, and on a phone it will have the same
shimmer — a real finding from previewing the art rather than the code.

## Higher resolution art can look worse, and the filter is why

Masie looked soft in the scene preview beside props that looked crisp. She is
not lower quality: she was drawn at **0.38x** of her source and they at
0.45-0.50x, and Canvas defaults `imageSmoothingQuality` to `'low'` -- a cheap
filter that aliases below about half scale. She alone was under the line.

The important part is what that means for the game, which sets
`imageSmoothingEnabled` and never sets the quality:

| | idle source | drawn on an iPhone SE | |
| --- | --- | --- | --- |
| before the redraw | 90px | 95px | 1.06x **up** |
| after | 248px | 95px | **0.38x down** |

Every redraw in this project moves a sprite from being upscaled to being
downscaled. That is the whole point -- but it also moves it across the line
where the default filter stops coping, so on a phone the sharper art could
have looked **worse** than the art it replaced, purely on the resampling.

One line in each: `ctx.imageSmoothingQuality = 'high'`.

It is worth stating plainly because it inverts the usual intuition. Adding
pixels is not automatically an improvement; it changes which resampling path
the art takes, and the path it lands on has to be chosen.

---

# Integration: four failures, none of them in the art

Everything below came from running the game rather than looking at sheets.

## A stale build is indistinguishable from broken art

`dist/atlas.json` held the previous pack's `scales` beside the current
`atlas.webp`. Same geometry, same image, wrong multipliers -- so every sprite
drew at the wrong size and it read as "all manner of visual artifacts". The
atlas itself was sound: 207 frame rects, zero overlaps, zero out of bounds.

Worth checking the served build against the packed one before believing
anything about the art.

## Frame height is not how big a character looks

`scale_for` matched each row's TALLEST frame to the old row's tallest. The
redrawn poses vary far more in height than the old ones did -- a leap is short
and wide, a crouch is tall and narrow -- so matching ceilings left the shortest
frame of `fall` drawn at 85px where it used to be 127. She visibly shrank
mid-jump.

The geometric mean of a frame's dimensions holds steady through a stretch,
where height does not. Taking the **median** of that across a row, so one
extreme pose cannot drag it:

| apparent size | before | after (tallest) | after (median √area) |
| --- | --- | --- | --- |
| idle | 153–160 | 180–189 | **153–161** |
| fall | 148–162 | 114–136 | **147–175** |
| swing across all nine | 1.47× | 1.50× | **1.39×** |

## The reference row needs correcting too

Leaving it at ×1.0 assumes the redraw preserved the relationship between the
reference frame's HEIGHT and how big the character looks. Masie's did not: she
is a longer, lower salamander now, so the same frame height carries a visibly
bigger animal. Uncorrected she was 18% larger standing still than in any other
state, and shrank the moment she moved.

## A rule can be followed exactly and still be wrong

The vine came back as a solid rectangle of foliage, 100% opaque, because it was
classified `kind: tile` and the tile rule says *"fills its square completely,
corner to corner, the artwork runs off all four edges."* It did exactly that.

A vine is a **strip**: a tile on one axis and an object on the others, drawn
0.64 tiles wide with open air either side. `STRIP_RULES` says so -- full height,
background on both sides, running off top and bottom, about a fifth as wide as
tall.

Strips also need a much narrower seamless blend. Rolling a vine by half and
blending paints a pale ghost vine through its own gaps: 8.3% of it at the
default feather, 1.6% at 0.04, and the wrap closes either way.
