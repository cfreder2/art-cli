"""Merging redrawn sheets into the atlas a game already ships.

A redraw happens one character at a time, so packing cannot mean "rebuild
everything from the new art" -- most of the art is still the old art, and the
old packer is the only thing that knows how to cut it. So this MERGES: the
existing atlas is kept whole, the new frames are appended below it, and only
the animations that were redrawn are repointed.

Two things have to be recorded for that to be drawable.

**Scale.** A game derives one scale per character from its idle frame --
`1.15 / atlas.axi.idle[0][3]` in AXI -- and applies it to every row. Replacing
one row with art three times the resolution would draw it three times the size.
So each replaced animation carries a multiplier that cancels its own
resolution, and the row lands at exactly the size it had before, just sharper.
An animation with no entry is drawn as it always was.

**Anchor.** Trimmed frames of differing widths cannot be placed by centring
their boxes. The sixth number in a frame is where the character stands.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from art import cut as cut_mod

# Gap between packed frames, so a rounding error in a draw call cannot bleed a
# neighbouring frame's pixels into one being drawn.
GUTTER = 2


@dataclass
class Replacement:
    group: str
    anim: str                       # the atlas key, prefix included
    frames: list[cut_mod.Box]
    images: list[Image.Image]
    scale: float = 1.0
    old_frames: int = 0
    meta: dict = field(default_factory=dict)   # fps, loop, effects


@dataclass
class PackResult:
    image: Path
    data: Path
    replaced: list[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    added_px: int = 0


def cut_sheet(path: Path, backdrop: str, names: list[str],
              cols: int | None, wrapped: int
              ) -> tuple[Image.Image, dict[str, list[cut_mod.Box]]]:
    """Key a sheet and return its frames, by animation name."""
    rgb = np.asarray(Image.open(path).convert("RGB"))
    key = cut_mod.hex_to_rgb(backdrop)
    _, rows = cut_mod.detect(rgb, key, expect=cols)
    keyed = Image.fromarray(cut_mod.keyed(rgb, key))

    if wrapped:
        boxes = [b for r in rows for b in r.boxes]
        return keyed, {(names[0] if names else "frames"): boxes}

    out: dict[str, list[cut_mod.Box]] = {}
    for i, row in enumerate(rows):
        if i >= len(names):
            break                    # rows the profile does not claim
        out[names[i]] = row.boxes
    return keyed, out


def scale_for(new_boxes: list[cut_mod.Box], old: list[list[int]],
              ref_old: float, ref_new: float) -> float:
    """What to multiply the character's base scale by for this row.

    The game derives ONE scale per character from a reference frame -- AXI uses
    `1.15 / atlas.axi.idle[0][3]` -- so a row's drawn size is its own height
    over that reference. Preserving the drawn size means preserving that ratio.

    Which is why the answer is not simply "old height over new height". When the
    reference row is itself redrawn, the base scale moves with it and the
    multiplier is 1: the frog's idle IS his reference, so replacing it corrects
    itself. Masie's idle is untouched while her run tripled in resolution, so
    her run needs the full correction.
    """
    if not old or not new_boxes or not ref_old or not ref_new:
        return 1.0
    old_top = max(f[3] for f in old)
    new_top = max(b.h for b in new_boxes)
    if not new_top:
        return 1.0
    return round((old_top / ref_old) / (new_top / ref_new), 5)


def merge(atlas_png: Path, atlas_json: Path, replacements: list[Replacement],
          out_png: Path, out_json: Path, quality: int = 90) -> PackResult:
    """Append the new frames below the existing atlas and repoint the rows."""
    base = Image.open(atlas_png).convert("RGBA")
    data = json.loads(atlas_json.read_text())

    # Shelf-pack the new frames into rows no wider than the atlas.
    shelves: list[list[tuple[Replacement, int, Image.Image]]] = []
    x, row_h, shelf = 0, 0, []
    for rep in replacements:
        for i, (box, img) in enumerate(zip(rep.frames, rep.images)):
            if x and x + img.width + GUTTER > base.width:
                shelves.append(shelf); shelf = []; x = 0
            shelf.append((rep, i, img))
            x += img.width + GUTTER
            row_h = max(row_h, img.height)
    if shelf:
        shelves.append(shelf)

    added = sum(max(img.height for _, _, img in s) + GUTTER for s in shelves)
    canvas = Image.new("RGBA", (base.width, base.height + added), (0, 0, 0, 0))
    canvas.paste(base, (0, 0))

    placed: dict[tuple[str, str], list[list[int]]] = {}
    y = base.height
    for s in shelves:
        x = 0
        for rep, i, img in s:
            canvas.paste(img, (x, y))
            box = rep.frames[i]
            placed.setdefault((rep.group, rep.anim), []).append(
                [x, y, img.width, img.height, box.lift, box.anchor])
            x += img.width + GUTTER
        y += max(img.height for _, _, img in s) + GUTTER

    for rep in replacements:
        data.setdefault(rep.group, {})[rep.anim] = placed[(rep.group, rep.anim)]

    scales = dict(data.get("scales") or {})
    anims = dict(data.get("anims") or {})
    for rep in replacements:
        key = f"{rep.group}/{rep.anim}"
        scales[key] = rep.scale
        if rep.meta:
            anims[key] = rep.meta
    data["scales"] = scales
    if anims:
        data["anims"] = anims
    data["image"] = out_png.name
    data["w"], data["h"] = canvas.width, canvas.height

    out_png.parent.mkdir(parents=True, exist_ok=True)
    if out_png.suffix.lower() == ".webp":
        # Lossy WebP keeps alpha, and at q90 the difference is invisible on art
        # this painterly while costing a fraction of PNG, which is built for
        # flat colour.
        canvas.save(out_png, "WEBP", quality=quality, method=6)
    else:
        canvas.save(out_png)
    out_json.write_text(json.dumps(data, separators=(",", ":")))
    return PackResult(out_png, out_json,
                      [f"{r.group}/{r.anim}" for r in replacements],
                      canvas.width, canvas.height, added)
