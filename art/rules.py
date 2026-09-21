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


def _silhouette_edge(alpha: np.ndarray, width: int = 2,
                     threshold: float = 0.5) -> np.ndarray:
    """The ring of pixels just inside the opaque boundary."""
    solid = alpha > threshold
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
               name: str, square: bool = True) -> list[Finding]:
    """A frame smaller than its kind allows -- the pixelation, at source.

    192x192 in the spec is the size a tile is DRAWN at, not the size it must be
    stored at. A larger source is not a defect, it is headroom: a tile drawn at
    192 on a laptop is drawn at 320 on a 5K display. So the rule is square and
    at least a tile, never exactly a tile.

    `square` is off for the entries the game stretches into a rectangle rather
    than repeating in a cell -- `water_col` is a whole column from surface to
    floor, and `vine` is drawn 0.64 tiles wide by one tall.
    """
    out: list[Finding] = []
    if kind == "tile":
        for i, b in enumerate(boxes):
            if square and abs(b.w - b.h) > max(b.w, b.h) * 0.08:
                out.append(Finding("not-square", f"{name}[{i}]",
                                   f"{b.w}×{b.h}; a repeating tile must be square"))
            side = min(b.w, b.h) if square else max(b.w, b.h)
            if side < tile_px:
                out.append(Finding("undersized", f"{name}[{i}]",
                                   f"{b.w}×{b.h}, under the {tile_px}px a tile "
                                   f"is drawn at"))
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


# How close to the backdrop an edge may sit before the key would eat it. The
# keyer ramps alpha to zero below 60 and to one above 130, so an edge inside
# that band is already partly transparent.
OUTLINE_AT_RISK = 130.0


def outline(rgb: np.ndarray, alpha: np.ndarray, key, name: str) -> list[Finding]:
    """An outline the key would eat, which cost Sir Croaks his in every frame.

    The rule is about DISTANCE FROM THE BACKDROP, not darkness. An earlier
    version tested whether the edge was darker than the fill, which fails a
    ground tile -- bright grass on top of dark earth reads as an edge 30 levels
    BRIGHTER -- and fails a glassy gem for having a bright rim. Neither is a
    defect; both would have been drawn exactly that way on purpose.

    What actually went wrong on the navy sheet was an outline so close to the
    backdrop that keying it out took the outline with it. So that is what is
    measured.
    """
    # Measure the SOLID edge, not the antialiasing fringe. A soft-edged thing
    # -- a cloud, a mossy log -- has a band of genuinely semi-transparent
    # pixels whose colour still leans toward the backdrop, and that is what a
    # soft edge IS, not an outline being eaten. Both came back clean on white
    # and on dark while failing a rule that counted their fringe.
    edge = _silhouette_edge(alpha, threshold=0.85)
    if edge.sum() < 40:
        return []
    d = cut_mod.key_distance(rgb, tuple(key))
    at_risk = float((d[edge] < OUTLINE_AT_RISK).mean())
    if at_risk > 0.12:
        return [Finding("outline", name,
                        f"{at_risk * 100:.0f}% of the edge sits within the key's "
                        "ramp -- the outline will be partly keyed away")]
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


def prop_shape(box, want: tuple[int, int] | None, name: str,
               allowed: float = 0.25) -> list[Finding]:
    """A prop drawn at a different proportion from the one it declares.

    `width_tiles` fixes how wide a prop is drawn and lets its height follow the
    art, so a prop that comes back a different SHAPE is silently resized by the
    game rather than caught. Eleven of AXI's fifteen props drifted that way at
    once -- the flower from 1.78:1 to 0.76:1, the log from 3.15:1 to 1.59:1,
    the hill from 3.95:1 to 6.82:1 -- and nothing failed, because every rule
    there was measured height, squareness or seams, and none measured shape.

    Compared as a ratio of ratios, so it is scale-free: drawing the right prop
    twice as large is fine and is what the resolution work was for.
    """
    if not want or not box or not box.h:
        return []
    want_w, want_h = want
    if not want_h:
        return []
    got, expected = box.w / box.h, want_w / want_h
    drift = got / expected
    if 1 - allowed <= drift <= 1 + allowed:
        return []
    return [Finding("prop-shape", name,
                    f"drawn {got:.2f}:1, declared {expected:.2f}:1 "
                    f"({drift:.2f}x) -- {'wider' if drift > 1 else 'taller'} "
                    "than the shape the game reserves for it")]
