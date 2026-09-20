"""Finding the frames on a sheet.

Two jobs that used to be one: deciding which pixels are background, and
deciding where the frames are. `pack_atlas.py` fuses them per sheet with
hand-measured boxes; separating them is what makes this work on a sheet nobody
has measured.

Background is found three ways -- by colour, by flooding in from the border,
or from existing alpha -- and all three produce the same thing: a soft ramp,
never a binary mask. The white halo on Mr Frog and the magenta rind on the King
are both what a binary mask looks like when the drawing fades into the paper.

Frames are found by gaps. Rows first (bands of content separated by empty
scanlines), then frames within each row. That is why the sheet rules demand 24px
of clear background between frames and more between rows than within them: the
gap IS the delimiter, and a frame touching its neighbour merges with it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Gaps smaller than this are treated as part of the same frame. The sheet rules
# ask for 24px; this is deliberately below that so a sheet that only just obeys
# still cuts, while a frame pair that actually touches still merges (and is
# reported, rather than silently cut in a wrong place).
MIN_GAP_PX = 6


# The share of a frame's height, measured from the bottom, that counts as its
# footprint. The contact patch, not the whole silhouette.
FOOTPRINT = 0.18

# How a frame's standing point is found. This is the registration point of
# traditional animation -- the peg hole every drawing lines up on -- and
# choosing it badly is visible as jitter in whatever it is NOT tracking.
#
#   centroid   the horizontal centre of mass. What a rigged character's root
#              is: the hips travel smoothly and the limbs move relative to
#              them. The default, because it is the smoothest thing on the
#              character by definition.
#   footprint  the middle of the contact patch. Correct for a standing pose,
#              wrong for a run: the feet are the part that moves MOST, so
#              holding them still swings the body and the head. Measured on
#              Masie's run it moved her head 35px a cycle against the
#              centroid's 12px.
#   leading    the front edge. For something led by its nose.
#   box        the middle of the bounding box: what a sheet of equal-width
#              frames implicitly used.
ANCHOR_MODES = ("centroid", "footprint", "leading", "box")


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int
    lift: int = 0      # how far this frame rides above its row's baseline
    anchor: int = 0    # where the character stands, measured from the left edge

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h, self.lift, self.anchor]


@dataclass
class Row:
    index: int
    boxes: list[Box]
    gap_used: int = MIN_GAP_PX
    expected: int | None = None

    @property
    def baseline_spread(self) -> int:
        return max((b.lift for b in self.boxes), default=0)

    @property
    def complete(self) -> bool:
        return self.expected is None or len(self.boxes) == self.expected


def key_distance(rgb: np.ndarray, key: tuple[int, int, int]) -> np.ndarray:
    """Euclidean distance from the key colour, per pixel."""
    k = np.array(key, dtype=np.float32)
    return np.sqrt(((rgb.astype(np.float32) - k) ** 2).sum(axis=-1))


def alpha_from_colour(
    rgb: np.ndarray,
    key: tuple[int, int, int],
    soft: float = 60.0,
    full: float = 130.0,
) -> np.ndarray:
    """Alpha as a ramp across distance from the key colour, not a threshold.

    Below `soft` is background, above `full` is art, and between them alpha
    rises smoothly. That band is the whole difference between a clean edge and
    a halo: a pixel where the drawing faded into the backdrop is partly
    transparent, which is what it actually is.
    """
    d = key_distance(rgb, key)
    a = (d - soft) / max(full - soft, 1e-6)
    return np.clip(a, 0.0, 1.0)


def unspill(rgb: np.ndarray, key: tuple[int, int, int]) -> np.ndarray:
    """Pull key-dominant pixels back toward the channels the key does not use.

    Magenta spill leaves a pink rind, green leaves a yellow-green one. The fix
    is the same: where a pixel leans toward the key beyond what the other
    channels support, bring it back.
    """
    out = rgb.astype(np.float32).copy()
    k = np.argsort(key)[::-1]          # the key's dominant channels, high to low
    hi, lo = k[0], k[-1]
    over = out[..., hi] - np.maximum(out[..., lo], out[..., k[1]])
    mask = over > 0
    out[..., hi] = np.where(mask, out[..., hi] - over, out[..., hi])
    return np.clip(out, 0, 255).astype(np.uint8)


def _runs(present: np.ndarray, min_gap: int = MIN_GAP_PX) -> list[tuple[int, int]]:
    """Contiguous runs of True, merging runs separated by less than `min_gap`."""
    idx = np.where(present)[0]
    if idx.size == 0:
        return []
    runs, start, prev = [], int(idx[0]), int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - prev > min_gap:
            runs.append((start, prev))
            start = i
        prev = i
    runs.append((start, prev))
    return runs


def _columns_in_band(present: np.ndarray, min_gap: int,
                     expect: int | None) -> tuple[list[tuple[int, int]], int]:
    """Column runs for one row, relaxing the gap until the count is right.

    A generator does not always leave the 24px the sheet rules ask for. The
    first real sheet left 5px between two frames of a hop, which merged them
    into one 421px box beside neighbours half that width. Relaxing the gap
    blindly would split a frame whose own limbs are separated; relaxing it only
    until the KNOWN column count is reached cannot, because the count is the
    thing being satisfied.
    """
    runs = _runs(present, min_gap)
    if expect is None or len(runs) == expect:
        return runs, min_gap
    for gap in range(min_gap - 1, 1, -1):
        tighter = _runs(present, gap)
        if len(tighter) == expect:
            return tighter, gap
        if len(tighter) > expect:
            break
    return runs, min_gap


def find_rows(alpha: np.ndarray, threshold: float = 0.35,
              min_gap: int = MIN_GAP_PX,
              expect: int | None = None,
              anchor: str = "centroid") -> list[Row]:
    """Rows of frames, and the frames in each, from an alpha channel.

    `expect` is how many frames each row should hold, which the plan knows. A
    row that cannot reach it is returned short and marked incomplete rather
    than being forced.
    """
    solid = alpha > threshold
    rows: list[Row] = []
    for n, (y0, y1) in enumerate(_runs(solid.any(axis=1), min_gap)):
        band = solid[y0:y1 + 1]
        boxes: list[Box] = []
        cols, gap_used = _columns_in_band(band.any(axis=0), min_gap, expect)
        for x0, x1 in cols:
            cell = band[:, x0:x1 + 1]
            ys = np.where(cell.any(axis=1))[0]
            if ys.size == 0:
                continue
            top, bottom = int(ys[0]), int(ys[-1])
            boxes.append(Box(x0, y0 + top, x1 - x0 + 1, bottom - top + 1))
        if not boxes:
            continue
        # Lift is measured against the row's lowest pixel, so a frame that sits
        # higher than its neighbours keeps that difference instead of being
        # flattened onto a shared bottom edge. It is what gives a run cycle its
        # bounce back after trimming.
        floor = max(b.y + b.h for b in boxes)
        for b in boxes:
            b.lift = floor - (b.y + b.h)
            b.anchor = anchor_of(solid, b, anchor)
        rows.append(Row(n, boxes, gap_used, expect))
    return rows


def anchor_of(solid: np.ndarray, b: Box, mode: str = "centroid") -> int:
    """Where the character registers, horizontally, within its own frame.

    `lift` says where the ground is vertically; this is the horizontal half,
    and getting it wrong is what a viewer sees as the head jerking back and
    forth. See ANCHOR_MODES for why the default is the centre of mass.
    """
    patch = solid[b.y:b.y + b.h, b.x:b.x + b.w]
    if patch.size == 0 or not patch.any():
        return b.w // 2
    if mode == "box":
        return b.w // 2
    if mode == "leading":
        return int(np.where(patch.any(axis=0))[0][-1])
    if mode == "footprint":
        cut = max(1, int(patch.shape[0] * (1 - FOOTPRINT)))
        xs = np.where(patch[cut:].any(axis=0))[0]
        if xs.size == 0:
            xs = np.where(patch.any(axis=0))[0]
        return int((xs[0] + xs[-1]) // 2)
    return int(round(np.argwhere(patch)[:, 1].mean()))


def already_keyed(image) -> bool:
    """Does this image carry a real alpha channel rather than a flat backdrop?

    A generator asked for a flat green plate sometimes returns a transparent
    PNG instead -- it has done the keying itself. Colour-keying that against
    green finds nothing, because there is no green: the whole sheet reads as
    one object and cuts into a single 1254px "frame".
    """
    from PIL import Image as _Image

    if not isinstance(image, _Image.Image) or image.mode not in ("RGBA", "LA"):
        return False
    a = np.asarray(image.convert("RGBA"))[..., 3]
    return bool((a < 8).mean() > 0.25)


def alpha_of(image) -> np.ndarray:
    """The image's own alpha, as the 0..1 ramp the rest of this module wants."""
    return np.asarray(image.convert("RGBA"))[..., 3].astype(np.float32) / 255.0


def detect(rgb: np.ndarray, key: tuple[int, int, int],
           expect: int | None = None,
           anchor: str = "centroid",
           alpha: np.ndarray | None = None
           ) -> tuple[np.ndarray, list[Row]]:
    """(alpha, rows) for a sheet, keyed by colour unless one is supplied."""
    if alpha is None:
        alpha = alpha_from_colour(rgb, key)
    return alpha, find_rows(alpha, expect=expect, anchor=anchor)


def read(path, key: tuple[int, int, int], expect: int | None = None,
         anchor: str = "centroid"):
    """Open a sheet and key it whichever way it needs.

    Returns (rgba_image, rows). The one place that decides between "flat
    backdrop" and "already transparent", so nothing downstream has to.
    """
    from PIL import Image

    img = Image.open(path)
    if already_keyed(img):
        img = img.convert("RGBA")
        a = alpha_of(img)
        return img, find_rows(a, expect=expect, anchor=anchor)
    rgb = np.asarray(img.convert("RGB"))
    a, rows = detect(rgb, key, expect=expect, anchor=anchor)
    return Image.fromarray(keyed(rgb, key)), rows


def apply_nudges(boxes: list[Box], nudges: dict) -> None:
    """Shift individual frames' registration by hand.

    An automatic anchor gets a cycle most of the way -- the centre of mass took
    Masie's head jitter from 35px to 12px -- and the last of it is per-frame,
    because one drawing is simply further forward than its neighbours. That is
    not something a rule can find; it is the judgement a traditional animator
    made at the peg bar, sliding a drawing until its arc ran smooth.
    """
    for i, b in enumerate(boxes):
        n = nudges.get(i) or nudges.get(str(i))
        if not n:
            continue
        dx, dy = (list(n) + [0, 0])[:2]
        b.anchor += int(dx)
        b.lift += int(dy)


def keyed(rgb: np.ndarray, key: tuple[int, int, int]) -> np.ndarray:
    """The sheet as RGBA: backdrop removed, spill pulled back, edges ramped.

    This is what anything downstream should draw. Handing on the raw sheet
    leaves every frame sitting in a rectangle of backdrop -- which is exactly
    what the preview did before this existed.
    """
    a = alpha_from_colour(rgb, key)
    out = np.dstack([unspill(rgb, key), (a * 255).astype(np.uint8)])
    return out


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


# Backdrops worth offering, and what each one is safe against. The rule they
# serve is the spec's first: a backdrop must be a colour the artwork never
# uses, so it can be keyed by colour alone.
PALETTE = {
    "magenta": "#FC309B",
    "green": "#00FF00",
    "blue": "#0033FF",
    "orange": "#FF7A00",
}


def spill_conflict(rgb: np.ndarray, key: tuple[int, int, int],
                   art: np.ndarray | None = None) -> float:
    """How much of this artwork the despill would damage, 0..1.

    Despill pulls a pixel's key-dominant channel back toward the channels the
    key does not use. That is right for a green rind on a pink axolotl and
    catastrophic for the axolotl: magenta's dominant channel is red, and so is
    hers, so her own colour reads as spill.

    Measured rather than assumed, because "is this character too close to the
    backdrop" is exactly the judgement that gets made wrong by eye.
    """
    if art is None:
        art = np.ones(rgb.shape[:2], dtype=bool)
    if not art.any():
        return 0.0
    changed = np.abs(unspill(rgb, key).astype(int) - rgb.astype(int)).max(axis=-1)
    return float((changed[art] > 10).mean())


def best_backdrop(rgb: np.ndarray, art: np.ndarray | None = None
                  ) -> list[tuple[str, str, float]]:
    """Every offered backdrop, ranked by how little of this art it would harm."""
    scored = [(name, value, spill_conflict(rgb, hex_to_rgb(value), art))
              for name, value in PALETTE.items()]
    return sorted(scored, key=lambda row: row[2])
