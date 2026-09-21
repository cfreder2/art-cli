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
GUTTER = 24

# ...and widening the gutter alone does not fix it, because the gutter is
# TRANSPARENT BLACK. AXI's water tiles arrived wrapping at 1.1 levels and came
# out of the atlas at 17, and the damage was one column deep: the left edge of
# water_body averaged 26 levels of red darker than the column beside it, which
# is the empty canvas bleeding in. Distance does not help when the thing
# bleeding in is black; what helps is the edge not being a cliff. Widening the
# gutter to 48 only moved which tile it ruined.
#
# So every frame is pasted with its own edge pixels extruded into the gutter
# around it. Whatever the encoder averages across the boundary is then the
# frame's own colour, and the recorded rect still points at the frame itself.
# It is the standard atlas bleed, arrived at from compression rather than from
# bilinear sampling.
BLEED = 8

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


def _extruded(img: Image.Image, b: int) -> Image.Image:
    """`img` with its own edge pixels repeated `b` deep on all four sides.

    Clamp, not wrap. A seamless tile's two edges already agree, so repeating
    either one is right there; a character frame's do not, and wrapping one
    would paste its tail beside its nose for the encoder to average in.
    """
    return Image.fromarray(
        np.pad(np.asarray(img), ((b, b), (b, b), (0, 0)), mode="edge"))


def _written_flat(entry) -> bool:
    """Is this atlas entry one frame written flat, rather than a list of them?"""
    return bool(isinstance(entry, list) and entry
                and isinstance(entry[0], (int, float)))


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


def uniform_scale_for(new_boxes: list[cut_mod.Box],
                      ref_boxes: list[cut_mod.Box], ref_mul: float) -> float:
    """What to multiply this row by so it READS the same size as the reference.

    `scale_for` preserves each row's size relative to the art it replaces,
    which is right when that art was consistent and wrong when it was not.
    AXI's was not: her original jump measured 0.96x her idle and her landing
    0.90x, so a faithful redraw reproduced a character who shrank 4% every
    time she left the ground and 10% when she touched down. Nobody had ever
    named it, but it was visible.

    This ignores what the row used to be and matches apparent size across the
    whole subject instead. A pose still changes SHAPE -- a jump is long and
    low, a landing is folded -- it just stops changing how much of her there
    is. Opt in per subject with `uniform_scale: true`, because a subject whose
    rows are meant to differ in size (a boss that swells) must not have that
    flattened.
    """
    if not new_boxes or not ref_boxes:
        return ref_mul
    here = _median([_apparent(b.w, b.h) for b in new_boxes])
    there = _median([_apparent(b.w, b.h) for b in ref_boxes])
    if not here or not there:
        return ref_mul
    return round(ref_mul * there / here, 5)


def inset_of(img: Image.Image, solid: float = 0.9) -> float:
    """How far down a tile its art becomes SOLID, as a fraction of its height.

    A terrain entry is written flat -- `[x, y, w, h, inset]` -- and the fifth
    number is this, not the `lift` an animation frame carries there. The game
    stands things on it: `grassSink` sinks a prop by the inset of the tile it
    is standing on, and `padDepth` raises a pond to meet a lily pad's leaf.

    Writing `lift` into that slot instead fed a PIXEL count to something that
    multiplies by a tile size and expects a fraction. A lily pad with lift 109
    was drawn 109 tiles below the pond and vanished; trees floated off the
    ground by the same mistake.

    "Solid" is the first row that is covered nearly all the way across, which
    is what standing on it means: a rock's dome only reaches that halfway down
    (0.54), a log spans it at once (0.0), a lily pad a quarter of the way in.
    """
    a = np.asarray(img.convert("RGBA"))[..., 3]
    if not a.size or not a.shape[0]:
        return 0.0
    covered = (a > 127).mean(axis=1)
    rows = np.nonzero(covered >= solid)[0]
    if not rows.size:
        return 0.0
    return round(float(rows[0]) / a.shape[0], 4)


def original_row(data: dict, group: str, key: str) -> list[list[int]]:
    """What this row looked like before the tool first redrew it.

    `scale_for` needs the size the row USED to be. Reading that out of the
    atlas reads the last pack's output -- which is the redraw it is meant to
    be measuring -- so old == new and every multiplier rounds to exactly 1.0.
    `base_rows` is the snapshot taken the first time each row was replaced;
    falling back to the live row is right only before that first pack.
    """
    row = (data.get("base_rows") or {}).get(f"{group}/{key}")
    if row is None:
        row = (data.get(group) or {}).get(key)
    if not row:
        return []
    # A terrain entry is ONE frame written flat; wrap it so either shape
    # iterates as frames.
    return [row] if not isinstance(row[0], list) else row


def merge(atlas_png: Path, atlas_json: Path, replacements: list[Replacement],
          out_png: Path, out_json: Path, quality: int = 90) -> PackResult:
    """Append the new frames below the existing atlas and repoint the rows."""
    base = Image.open(atlas_png).convert("RGBA")
    data = json.loads(atlas_json.read_text())

    # "The existing atlas" means the art this tool did not draw -- not whatever
    # the last pack happened to leave behind. Every accepted sheet is re-cut on
    # every run, so the region a previous pack appended is superseded in full,
    # and appending below it instead of over it grows the file by the whole
    # redraw each time. AXI's reached 4103x14503 and stopped packing at all:
    # WebP cannot encode a side past 16383. So the untouched base is measured
    # once, recorded, and cropped back to on every pack after the first.
    base_w = int(data.get("base_w") or base.width)
    base_h = int(data.get("base_h") or base.height)
    if (base_w, base_h) != base.size:
        base = base.crop((0, 0, base_w, base_h))

    # How wide to make the new region. Appending everything below in the old
    # atlas's 1024px column made a strip 20,000px tall, which WebP cannot
    # encode at all -- so the canvas widens toward square instead of growing
    # only downward.
    new = [img for rep in replacements for img in rep.images]
    area = sum(img.width * img.height for img in new)
    widest = max((img.width for img in new), default=1)
    width = max(base.width, widest + GUTTER + 2 * BLEED,
                int((area * 1.25) ** 0.5))
    width = min(width, MAX_SIDE)

    # Every frame is inset by BLEED so its extruded edge has somewhere to go
    # that is neither off the canvas nor on top of the atlas being kept whole.
    shelves: list[list[tuple[Replacement, int, Image.Image]]] = []
    x, shelf = BLEED, []
    for rep in replacements:
        for i, img in enumerate(rep.images):
            if x > BLEED and x + img.width + BLEED > width:
                shelves.append(shelf); shelf = []; x = BLEED
            shelf.append((rep, i, img))
            x += img.width + GUTTER
    if shelf:
        shelves.append(shelf)

    added = 2 * BLEED + sum(max(img.height for _, _, img in s) + GUTTER
                            for s in shelves)
    height = base.height + added
    if height > MAX_SIDE or width > MAX_SIDE:
        raise ValueError(
            f"atlas would be {width}x{height}, past WebP's {MAX_SIDE}px limit. "
            "Fewer frames, smaller sheets, or a second atlas."
        )
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(base, (0, 0))

    placed: dict[tuple[str, str], list[list[int]]] = {}
    y = base.height + BLEED
    for s in shelves:
        x = BLEED
        for rep, i, img in s:
            # The extruded copy is pasted, not the frame: it carries the frame
            # in its middle and BLEED pixels of its own edge all round.
            canvas.paste(_extruded(img, BLEED), (x - BLEED, y - BLEED))
            box = rep.frames[i]
            placed.setdefault((rep.group, rep.anim), []).append(
                [x, y, img.width, img.height, box.lift, box.anchor])
            x += img.width + GUTTER
        y += max(img.height for _, _, img in s) + GUTTER

    # The same argument as base_w/base_h, for the rows rather than the image.
    # `scale_for` asks how big this row USED to look, and answering from
    # `data` answers with the last pack's output -- which is the redraw it is
    # supposed to be measuring. old == new, every scale collapses to exactly
    # 1.0, and the correction silently does nothing: AXI packed 39 rows of
    # 1.0 while her jump, climb, swim and defeat drifted 21-32% oversized.
    # So each row is snapshotted the first time it is replaced, and never
    # again -- the pristine art stays the reference however often we repack.
    base_rows = dict(data.get("base_rows") or {})
    for rep in replacements:
        key = f"{rep.group}/{rep.anim}"
        if key not in base_rows:
            was0 = (data.get(rep.group) or {}).get(rep.anim)
            if was0:
                base_rows[key] = was0

    for rep in replacements:
        frames = placed[(rep.group, rep.anim)]
        # A terrain entry is ONE frame written flat -- `tiles.tree` is
        # [x, y, w, h, inset], not a list of frames -- and the game indexes it
        # directly. Match whatever the atlas already does for that key rather
        # than deciding: it is the only thing that knows.
        was = (data.get(rep.group) or {}).get(rep.anim)
        if was is not None:
            flat = _written_flat(was)
        else:
            # ...and a key the atlas has never held knows nothing, so the GROUP
            # it is joining decides. Defaulting to a list of frames wrote AXI's
            # two new water tiles as [[x, y, w, h, ...]] among thirty flat
            # siblings, and `tiles.water_body[0]` came back an array where the
            # game wanted an x.
            siblings = [v for v in (data.get(rep.group) or {}).values() if v]
            flat = bool(siblings) and (
                sum(_written_flat(v) for v in siblings) * 2 > len(siblings))
        if flat:
            # Five numbers, and the fifth is the inset fraction -- NOT the
            # lift an animation frame carries in that slot. See inset_of.
            x, y, w, h = frames[0][:4]
            data.setdefault(rep.group, {})[rep.anim] = [
                x, y, w, h, inset_of(rep.images[0])]
        else:
            data.setdefault(rep.group, {})[rep.anim] = frames

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
    data["base_w"], data["base_h"] = base_w, base_h
    if base_rows:
        data["base_rows"] = base_rows

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
