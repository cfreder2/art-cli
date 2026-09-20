"""The spec's published numbers, locked down.

AXI's docs/ASSET_SPEC.md states these. If a change here makes one of them move,
the change is wrong or the spec needs rewriting first -- not the other way
round.
"""

import pytest

from art.spec import DEVICES, min_drawn_px, upscale

PUBLISHED_PX_PER_TILE = {
    "iPhone SE": 83, "iPhone 15/16": 131, "1080p monitor": 120,
    "iPad": 182, "MacBook": 200, "4K monitor": 240, "5K iMac": 320,
}

# who, height in tiles, the spec's minimum drawn height
PUBLISHED_MINIMUMS = [("Masie", 1.15, 240), ("enemy", 0.95, 200),
                      ("friend", 1.05, 220), ("boss", 2.50, 500)]


@pytest.mark.parametrize("device", DEVICES, ids=lambda d: d.name)
def test_px_per_tile_matches_spec(device):
    assert device.px_per_tile == PUBLISHED_PX_PER_TILE[device.name]


@pytest.mark.parametrize("who,tiles,expected", PUBLISHED_MINIMUMS)
def test_minimum_drawn_height_matches_spec(who, tiles, expected):
    assert min_drawn_px(tiles) == expected


def test_minimum_always_leaves_headroom():
    """A height that lands exactly on the boundary still gets its margin --
    a boss at 2.50 tiles is 480 px of art and 500 px of cell."""
    assert min_drawn_px(2.50) == 500
    assert min_drawn_px(2.50) > 2.50 * 192


@pytest.mark.parametrize("src,tiles,device,expected", [
    (90, 1.15, "MacBook", 2.6),    # Masie
    (45, 1.05, "MacBook", 4.7),    # Mr Frog, the worst in the game
    (45, 1.05, "iPhone 15/16", 3.1),
    (147, 2.50, "MacBook", 3.4),   # Sir Croaks
])
def test_upscale_reproduces_the_published_table(src, tiles, device, expected):
    px = PUBLISHED_PX_PER_TILE[device]
    assert round(upscale(src, tiles * px), 1) == expected
