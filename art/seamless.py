"""Making a generated tile actually tile.

An image generator cannot produce a seamless tile from a description. Asked
plainly and in detail, AXI's ground family came back at 13.1x, 9.8x and 5.7x
the tile's own internal step across the wrap -- a line ruled across the world
every screen width. Rewording does not fix it, because the model has no way to
reason about what its right edge will sit next to.

It is an image-processing problem, so it is solved here instead.

The method is the old one: blend the tile with a copy of itself rolled by half,
weighted so the weight is zero at both edges and one in the middle. At the left
edge the result is entirely the rolled copy, which there is the tile's own
middle; at the right edge it is the column beside that middle. Two columns that
were adjacent in the original end up as the wrap, so the wrap is continuous by
construction rather than by luck.

The cost is honest: the middle of the tile is a blend of two parts of itself, so
fine detail softens. For ground, moss, water and stone -- which is what tiles
are -- that is invisible. For a tile with a distinct object in it, it is not,
and `check --seams` still reports what it actually got.
"""

from __future__ import annotations

import numpy as np


def _ramp(n: int, feather: float) -> np.ndarray:
    """Zero at both ends, one across the middle, smooth in between."""
    x = np.linspace(0.0, 1.0, n, dtype=np.float32)
    band = max(feather, 1e-3)
    w = np.clip(np.minimum(x, 1.0 - x) / band, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * w)          # ease, so no visible ridge


def make_seamless(rgba: np.ndarray, axis: str = "both",
                  feather: float = 0.35) -> np.ndarray:
    """Return the tile made periodic on the requested axis.

    `feather` is how much of the tile the blend spans, as a fraction. Larger is
    smoother and softer; smaller keeps more detail and risks a ridge.
    """
    out = rgba.astype(np.float32)
    h, w = out.shape[:2]

    if axis in ("horizontal", "both"):
        rolled = np.roll(out, w // 2, axis=1)
        weight = _ramp(w, feather)[None, :, None]
        out = out * weight + rolled * (1.0 - weight)

    if axis in ("vertical", "both"):
        rolled = np.roll(out, h // 2, axis=0)
        weight = _ramp(h, feather)[:, None, None]
        out = out * weight + rolled * (1.0 - weight)

    return np.clip(out, 0, 255).astype(np.uint8)


def wrap_step(rgba: np.ndarray, axis: str) -> tuple[float, float]:
    """(step across the wrap, the tile's own median step) on that axis.

    The same quantity `seams.py` scores, exposed so a caller can measure before
    and after rather than trust that the blend worked.
    """
    a = rgba.astype(np.float32)
    if axis == "vertical":
        a = np.transpose(a, (1, 0, 2))
    internal = np.abs(a[:, 1:, :] - a[:, :-1, :]).mean(axis=(0, 2))
    wrap = float(np.abs(a[:, 0, :] - a[:, -1, :]).mean())
    return wrap, float(np.median(internal))
