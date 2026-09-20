"""The checks, one per failure that has actually happened to this art.

Every rule here exists because something shipped wrong once, and every one is
cheap enough to run on every accepted sheet before it is packed. That matters
more than it sounds: AXI has 68 subjects and two of them are done. Everything
found so far was found by a person squinting at a 1254px sheet, which does not
survive the other 66.

A rule returns findings, not booleans, because "this frame is 12px short" is
actionable and "failed" is not.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from art import cut as cut_mod


@dataclass
class Finding:
    rule: str
    where: str
    detail: str
    fatal: bool = True


def _silhouette_edge(alpha: np.ndarray, width: int = 2) -> np.ndarray:
    """The ring of pixels just inside the opaque boundary."""
    solid = alpha > 0.5
    inner = solid.copy()
    for _ in range(width):
        shrunk = inner.copy()
        shrunk[1:, :] &= inner[:-1, :]
        shrunk[:-1, :] &= inner[1:, :]
        shrunk[:, 1:] &= inner[:, :-1]
        shrunk[:, :-1] &= inner[:, 1:]
        inner = shrunk
    return solid & ~inner


def undersized(boxes, kind: str, minimum: int | None, tile_px: int,
               name: str) -> list[Finding]:
    """A frame smaller than its kind allows -- the pixelation, at source."""
    out: list[Finding] = []
    if kind == "tile":
        for i, b in enumerate(boxes):
            if b.w != tile_px or b.h != tile_px:
                out.append(Finding("undersized", f"{name}[{i}]",
                                   f"{b.w}×{b.h}, terrain must be exactly "
                                   f"{tile_px}×{tile_px}"))
        return out
    if not minimum:
        return out
    tallest = max((b.h for b in boxes), default=0)
    if tallest < minimum:
        out.append(Finding("undersized", name,
                           f"tallest frame {tallest}px, needs {minimum}px"))
    return out


def merged_frames(row_count: int, expected: int | None, name: str) -> list[Finding]:
    """Frames that touched and were cut as one -- or never drawn at all."""
    if not expected or row_count == expected:
        return []
    return [Finding("merged", name,
                    f"found {row_count} frames, expected {expected} -- frames "
                    "touching, below the 24px of clear background the rules ask for")]


def halo(rgb: np.ndarray, alpha: np.ndarray, key, name: str,
         tolerance: float = 70.0) -> list[Finding]:
    """Backdrop left inside the art: the rind the despill should have removed."""
    body = alpha > 0.9
    if not body.any():
        return []
    d = cut_mod.key_distance(rgb, key)
    share = float((d[body] < tolerance).mean())
    if share > 0.005:
        return [Finding("halo", name,
                        f"{share * 100:.1f}% of solid pixels still sit on the "
                        "backdrop colour")]
    return []


def outline(rgb: np.ndarray, alpha: np.ndarray, name: str,
            margin: float = 18.0) -> list[Finding]:
    """An outline eaten by the key, which cost Sir Croaks his in every frame.

    The edge ring should be clearly DARKER than the body it surrounds. When the
    outline is close to the backdrop it keys away with it, and the ring comes
    back the same brightness as the fill.
    """
    edge = _silhouette_edge(alpha)
    body = (alpha > 0.9) & ~edge
    if edge.sum() < 40 or body.sum() < 40:
        return []
    lum = rgb.astype(float).mean(axis=-1)
    if lum[edge].mean() > lum[body].mean() - margin:
        return [Finding("outline", name,
                        f"edge is only {lum[body].mean() - lum[edge].mean():.0f} "
                        "levels darker than the fill -- outline may have been "
                        "keyed away")]
    return []


def tile_margin(alpha: np.ndarray, name: str) -> list[Finding]:
    """A terrain tile that does not fill its cell leaves a gap that reads as a
    seam even when the art itself wraps."""
    margins = _margins(alpha)
    worst = max(margins.values())
    if worst > 0:
        return [Finding("tile-margin", name,
                        f"{worst}px of transparent margin ("
                        + ", ".join(f"{k} {v}" for k, v in margins.items() if v)
                        + ") -- terrain must fill its cell edge to edge")]
    return []


def _margins(alpha: np.ndarray, threshold: float = 0.03) -> dict[str, int]:
    opaque = alpha > threshold
    if not opaque.any():
        return {"left": alpha.shape[1], "right": alpha.shape[1],
                "top": alpha.shape[0], "bottom": alpha.shape[0]}
    cols = np.where(opaque.any(axis=0))[0]
    rows = np.where(opaque.any(axis=1))[0]
    return {"left": int(cols[0]), "right": int(alpha.shape[1] - 1 - cols[-1]),
            "top": int(rows[0]), "bottom": int(alpha.shape[0] - 1 - rows[-1])}


def baseline_spread(boxes, name: str, allowed: float = 0.25) -> list[Finding]:
    """Frames in one row not sharing a groundline.

    Reported, not failed. A hop and a run SHOULD leave the ground, and `lift`
    exists to preserve exactly that -- it is what gives a run cycle its bounce.
    A person has to say which rows are meant to be planted.
    """
    if len(boxes) < 2:
        return []
    spread = max(b.lift for b in boxes)
    tallest = max(b.h for b in boxes) or 1
    if spread > tallest * allowed:
        return [Finding("baseline", name,
                        f"frames sit up to {spread}px above the row's "
                        f"groundline ({spread / tallest * 100:.0f}% of height) "
                        "-- intended for an airborne pose, a bob otherwise",
                        fatal=False)]
    return []
