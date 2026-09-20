"""The sizing rules, in one place.

Everything here is derived from AXI's `docs/ASSET_SPEC.md` and checked against
the numbers written there. Nothing in this module reads a file or touches an
image: it is arithmetic about tiles, and every other module asks it rather than
rounding on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

# The camera shows this many tiles of height, whatever the screen. It is the
# one assumption the whole spec rests on.
CAMERA_TILES = 9

# The target. A tile is drawn at this many device pixels.
TARGET_TILE_PX = 192

# Device pixel ratio is capped before it multiplies anything.
DPR_CAP = 3


@dataclass(frozen=True)
class Device:
    name: str
    css_w: int
    css_h: int
    dpr: int

    @property
    def px_per_tile(self) -> int:
        """Device pixels per tile: the viewport's height over nine, times dpr."""
        return round(self.css_h / CAMERA_TILES * min(self.dpr, DPR_CAP))


# Landscape is the reference, so css_h is the short side.
DEVICES = (
    Device("iPhone SE", 667, 375, 2),
    Device("iPhone 15/16", 852, 393, 3),
    Device("1080p monitor", 1920, 1080, 1),
    Device("iPad", 1180, 820, 2),
    Device("MacBook", 1440, 900, 2),
    Device("4K monitor", 3840, 2160, 1),
    Device("5K iMac", 2560, 1440, 2),
)

DEVICE_BY_KEY = {d.name.lower().split("/")[0].replace(" ", "-"): d for d in DEVICES}

# The three kinds. Closed on purpose: each one is a different piece of
# arithmetic, and a fourth would mean `plan` and `check` could disagree about a
# size. Adding one is a change to this file.
KINDS = ("character", "tile", "prop")


def min_drawn_px(height_tiles: float, tile_px: int = TARGET_TILE_PX) -> int:
    """The minimum height a character may be drawn at, in pixels.

    The spec's four characters round to 240, 200, 220 and 500 px at 192 px per
    tile. That is the height in tiles times the tile size, taken up to the next
    multiple of twenty — strictly next, so a value already on the boundary still
    gets its headroom. Masie at 1.15 tiles is 220.8 px of art and 240 px of cell.

        >>> [min_drawn_px(h) for h in (1.15, 0.95, 1.05, 2.50)]
        [240, 200, 220, 500]
    """
    exact = height_tiles * tile_px
    return (int(exact // 20) + 1) * 20


def tile_size_px(tile_px: int = TARGET_TILE_PX) -> tuple[int, int]:
    """Terrain tiles are exact and fill the cell. A margin here becomes a seam."""
    return (tile_px, tile_px)


def prop_width_px(width_tiles: float, tile_px: int = TARGET_TILE_PX) -> int:
    """A prop is drawn a fixed number of tiles wide; its height follows its art.

    The spec's prop table is hand-rounded (a 2-tile shrine is 390, not 400), and
    those are art-direction numbers rather than a formula. So this returns the
    exact width and the table lives in `art.yaml`, where a per-prop override
    belongs.
    """
    return round(width_tiles * tile_px)


def upscale(source_px: float, drawn_px: float) -> float:
    """How far the source is stretched to reach the size it is drawn at."""
    if source_px <= 0:
        return float("inf")
    return drawn_px / source_px
