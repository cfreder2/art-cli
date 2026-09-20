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

# Gap between packed frames. Two pixels is enough to stop a rounding error in a
# draw call sampling a neighbour -- and not nearly enough under lossy
# compression, which works in 16px blocks and will happily average a tile's
# edge together with whatever was packed beside it. A seamless tile is exactly
# where that hurts: its two edges have to match each other, and the neighbours
# bleeding in are different on each side. Measured on water_col, the wrap went
# from 2.4x compressed alone to 10.0x compressed in the atlas.
GUTTER = 18

# WebP cannot encode either dimension past this. PNG can, but an atlas that
# only WebP cannot hold is an atlas that cannot ship.
MAX_SIDE = 16383


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
              cols: int | None, wrapped: int, gallery: bool = False
              ) -> tuple[Image.Image, dict[str, list[cut_mod.Box]]]:
    """Key a sheet and return its frames, by animation name."""
    rgb = np.asarray(Image.open(path).convert("RGB"))
    key = cut_mod.hex_to_rgb(backdrop)
    _, rows = cut_mod.detect(rgb, key, expect=cols)
    keyed = Image.fromarray(cut_mod.keyed(rgb, key))

    if gallery:
        # One cell per entry, row-major. Mapping rows to names positionally --
        # which is right for a sheet of animations -- gave a six-entry terrain
        # sheet in two rows only two of its six entries, and left the other
        # four as the art they were meant to replace.
        boxes = [b for r in rows for b in r.boxes]
        return keyed, {n: [b] for n, b in zip(names, boxes)}

    if wrapped:
        boxes = [b for r in rows for b in r.boxes]
        return keyed, {(names[0] if names else "frames"): boxes}

    out: dict[str, list[cut_mod.Box]] = {}
    for i, row in enumerate(rows):
        if i >= len(names):
            break                    # rows the profile does not claim
        out[names[i]] = row.boxes
    return keyed, out


def _apparent(w: float, h: float) -> float:
    """How big a frame LOOKS, independent of how it is posed.

    Frame height is not it. A character stretched into a leap is short and wide
    and exactly as big as before; a character curled up is tall and narrow and
    also exactly as big. The geometric mean of the two holds steady through
    both, which frame height does not.
    """
    return (w * h) ** 0.5


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return 0.0
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def scale_for(new_boxes: list[cut_mod.Box], old: list[list[int]],
              ref_old: float, ref_new: float) -> float:
    """What to multiply the character's base scale by for this row.

    The game derives ONE scale per character from a reference frame -- AXI uses
    `1.15 / atlas.axi.idle[0][3]` -- and applies it to every row. Preserving how
    big she LOOKS in a row means preserving that row's apparent size relative to
    the reference, so the multiplier cancels whatever the redraw changed.

    Measured on the tallest frame first, which was wrong: the redrawn poses vary
    far more in height than the old ones did, so matching their ceilings left
    the shortest frame of `fall` drawn at 85px where it used to be 127. She
    visibly shrank mid-jump. The median of the geometric mean is steady through
    a stretch, and it is a median so one extreme pose cannot drag it.
    """
    if not old or not new_boxes or not ref_old or not ref_new:
        return 1.0
    old_size = _median([_apparent(f[2], f[3]) for f in old])
    new_size = _median([_apparent(b.w, b.h) for b in new_boxes])
    if not new_size or not old_size:
        return 1.0
    # Relative to the reference frame, which moves when that row is redrawn too.
    return round((old_size / ref_old) / (new_size / ref_new), 5)


def merge(atlas_png: Path, atlas_json: Path, replacements: list[Replacement],
          out_png: Path, out_json: Path, quality: int = 90) -> PackResult:
    """Append the new frames below the existing atlas and repoint the rows."""
    base = Image.open(atlas_png).convert("RGBA")
    data = json.loads(atlas_json.read_text())

    # How wide to make the new region. Appending everything below in the old
    # atlas's 1024px column made a strip 20,000px tall, which WebP cannot
    # encode at all -- so the canvas widens toward square instead of growing
    # only downward.
    new = [img for rep in replacements for img in rep.images]
    area = sum(img.width * img.height for img in new)
    widest = max((img.width for img in new), default=1)
    width = max(base.width, widest + GUTTER, int((area * 1.25) ** 0.5))
    width = min(width, MAX_SIDE)

    shelves: list[list[tuple[Replacement, int, Image.Image]]] = []
    x, shelf = 0, []
    for rep in replacements:
        for i, img in enumerate(rep.images):
            if x and x + img.width + GUTTER > width:
                shelves.append(shelf); shelf = []; x = 0
            shelf.append((rep, i, img))
            x += img.width + GUTTER
    if shelf:
        shelves.append(shelf)

    added = sum(max(img.height for _, _, img in s) + GUTTER for s in shelves)
    height = base.height + added
    if height > MAX_SIDE or width > MAX_SIDE:
        raise ValueError(
            f"atlas would be {width}x{height}, past WebP's {MAX_SIDE}px limit. "
            "Fewer frames, smaller sheets, or a second atlas."
        )
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
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
        frames = placed[(rep.group, rep.anim)]
        # A terrain entry is ONE frame written flat -- `tiles.tree` is
        # [x, y, w, h, inset], not a list of frames -- and the game indexes it
        # directly. Match whatever the atlas already does for that key rather
        # than deciding: it is the only thing that knows.
        was = (data.get(rep.group) or {}).get(rep.anim)
        flat = isinstance(was, list) and was and isinstance(was[0], (int, float))
        data.setdefault(rep.group, {})[rep.anim] = frames[0] if flat else frames

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
