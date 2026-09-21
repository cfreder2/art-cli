"""Does this tile repeat without a visible seam?

A terrain tile is drawn edge to edge and then tiled, so the right column has to
continue into the left column of the next copy. If it does not, the grid shows
up as a line across the ground -- the most visible art bug there is, because it
is regular.

Testing it by comparing the two edge columns for equality is wrong: painterly
art is never equal anywhere, and a tile that wrapped perfectly would fail. What
matters is whether the jump *at the wrap* is bigger than the jumps the image
makes everywhere else. So the wrap difference is measured against the image's
own median column-to-column difference, and the ratio is the score.

A score near 1 means the wrap looks like any other step across the image, which
is what seamless means. Large means a line.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SeamScore:
    axis: str          # "horizontal" (left/right wrap) or "vertical"
    ratio: float       # wrap difference over typical internal difference
    wrap_diff: float
    typical: float

    @property
    def seamless(self) -> bool:
        return self.ratio <= SEAMLESS_RATIO or self.wrap_diff < SEAMLESS_LEVELS

    def verdict(self) -> str:
        if self.seamless:
            return "seamless"
        if self.ratio <= SEAMLESS_RATIO * 2 and self.wrap_diff < SEAMLESS_LEVELS * 2:
            return "soft seam"
        return "SEAM"


# How much bigger the wrap step may be than a typical internal step. Painterly
# art varies, so this is deliberately loose: it is meant to catch a line, not
# to enforce a tiling pattern.
SEAMLESS_RATIO = 2.0

# ...and below this many levels out of 255 the step cannot be seen whatever the
# ratio says. A very smooth tile -- still water, open sky -- has an internal
# step near zero, so dividing by it turns an invisible two-level difference
# into a large number. Water measured 2.3 levels at a 2.2x ratio while a noisy
# dirt measured 10 levels at 2.5x; only one of those is a line on screen.
SEAMLESS_LEVELS = 4.0


def _edge_scores(a: np.ndarray) -> tuple[float, float]:
    """(difference across the wrap, median difference between neighbours).

    `a` is (rows, cols, channels) as float. Columns are compared, so pass the
    transposed array to test the vertical wrap.
    """
    if a.shape[1] < 3:
        return (0.0, 1.0)
    # Every neighbouring column pair, and then the wrap pair: last -> first.
    internal = np.abs(a[:, 1:, :] - a[:, :-1, :]).mean(axis=(0, 2))
    wrap = float(np.abs(a[:, 0, :] - a[:, -1, :]).mean())
    typical = float(np.median(internal))
    return (wrap, typical)


# Which wraps a tile is actually required to make. A ground tile has grass on
# top and dirt underneath: it repeats left to right and is never stacked, so
# scoring its vertical wrap reports the art as a bug. Only `both` means both.
AXES = {"horizontal": ("horizontal",), "vertical": ("vertical",),
        "both": ("horizontal", "vertical"), True: ("horizontal", "vertical")}


def axes_for(declared) -> tuple[str, ...]:
    """The wraps to test, from one tile's resolved axis."""
    if isinstance(declared, (str, bool)) and declared in AXES:
        return AXES[declared]
    return AXES["both"]


def axis_for(declared, anim: str | None = None):
    """One tile's axis, from a subject's `seamless:` value.

    A string is the whole sheet. A map is per tile, because a sheet can carry
    tiles that repeat differently: a water surface has a crest along its top
    and only ever repeats sideways, while the water under it is stacked too.
    One value on the subject cannot say both, and saying either one wrecks the
    other tile.
    """
    if isinstance(declared, dict):
        return declared.get(anim)
    return declared


def junction(upper: np.ndarray, lower: np.ndarray) -> SeamScore:
    """Score the seam where one tile is STACKED on another.

    `score` only ever compares a tile with itself, so two tiles that each wrap
    perfectly both pass while the line between them is the one on screen. Same
    metric, different pair of edges.
    """
    from art.seamless import junction_step
    step, typical = junction_step(upper, lower)
    ratio = step / typical if typical > 1e-6 else (0.0 if step < 1e-6 else 999.0)
    return SeamScore("joint", ratio, step, typical)


def score(rgb: np.ndarray, alpha: np.ndarray | None = None,
          axes: tuple[str, ...] = ("horizontal", "vertical")) -> list[SeamScore]:
    """Score the required wraps for one tile.

    Fully transparent pixels carry no colour worth comparing, so they are
    folded out by weighting: a tile with a transparent margin is a seam by
    definition and `check` reports that separately.
    """
    a = rgb.astype(np.float32)
    if alpha is not None:
        a = a * (alpha.astype(np.float32)[..., None] / 255.0)

    out: list[SeamScore] = []
    for axis, arr in (("horizontal", a), ("vertical", np.transpose(a, (1, 0, 2)))):
        if axis not in axes:
            continue
        wrap, typical = _edge_scores(arr)
        ratio = wrap / typical if typical > 1e-6 else (0.0 if wrap < 1e-6 else 999.0)
        out.append(SeamScore(axis, ratio, wrap, typical))
    return out


def transparent_margin(alpha: np.ndarray, threshold: int = 8) -> dict[str, int]:
    """How many fully-transparent rows/columns sit on each edge.

    A terrain tile must fill its cell: any margin here becomes a gap between
    tiles, which reads as a seam even when the art itself wraps.
    """
    opaque = alpha > threshold
    if not opaque.any():
        return {"left": alpha.shape[1], "right": alpha.shape[1],
                "top": alpha.shape[0], "bottom": alpha.shape[0]}
    cols = np.where(opaque.any(axis=0))[0]
    rows = np.where(opaque.any(axis=1))[0]
    return {
        "left": int(cols[0]),
        "right": int(alpha.shape[1] - 1 - cols[-1]),
        "top": int(rows[0]),
        "bottom": int(alpha.shape[0] - 1 - rows[-1]),
    }
