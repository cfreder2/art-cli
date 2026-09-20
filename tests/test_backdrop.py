"""Choosing a backdrop is a measurement, not a project-wide guess."""

import numpy as np

from art.cut import PALETTE, best_backdrop, hex_to_rgb, spill_conflict

MAGENTA, GREEN = hex_to_rgb(PALETTE["magenta"]), hex_to_rgb(PALETTE["green"])


def patch(rgb, size=32):
    return np.tile(np.array(rgb, dtype=np.uint8), (size, size, 1))


def test_a_pink_character_is_destroyed_by_a_magenta_backdrop():
    """Masie is pink, magenta's dominant channel is red, and so is hers -- so
    despill reads her own colour as spill. Measured at 78% of her pixels."""
    assert spill_conflict(patch((235, 150, 175)), MAGENTA) > 0.9


def test_the_same_character_is_untouched_by_green():
    assert spill_conflict(patch((235, 150, 175)), GREEN) == 0.0


def test_a_green_character_is_destroyed_by_a_green_backdrop():
    """And the frog is the mirror image: green despills 64% of him."""
    assert spill_conflict(patch((90, 200, 70)), GREEN) > 0.9


def test_the_ranking_puts_the_safe_backdrop_first():
    ranked = best_backdrop(patch((235, 150, 175)))
    assert ranked[0][0] == "green" and ranked[0][2] == 0.0
    assert ranked[-1][2] > 0.5


def test_only_the_art_is_measured_not_the_whole_image():
    """The backdrop already in an image would otherwise dominate the score."""
    img = patch((235, 150, 175), 32).copy()
    img[:16] = GREEN
    art = np.zeros(img.shape[:2], dtype=bool)
    art[16:] = True
    assert spill_conflict(img, GREEN, art) == 0.0
