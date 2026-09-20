"""The tiling check, and the axis distinction the real art forced."""

import numpy as np

from art.seams import axes_for, score, transparent_margin


def _gradient(w=64, h=64, wrap=True):
    """A tile whose colour ramps left to right. With `wrap`, it ramps back so
    the last column continues into the first."""
    x = np.linspace(0, 1, w)
    ramp = np.sin(x * 2 * np.pi) if wrap else x
    return np.repeat((ramp * 120 + 120)[None, :, None], h, axis=0).repeat(3, axis=2).astype(np.uint8)


def test_a_wrapping_gradient_reads_as_seamless():
    h = {s.axis: s for s in score(_gradient(wrap=True))}["horizontal"]
    assert h.seamless


def test_a_hard_step_reads_as_a_seam():
    h = {s.axis: s for s in score(_gradient(wrap=False))}["horizontal"]
    assert not h.seamless


def test_ground_is_horizontal_only():
    """Ground has grass on top and dirt below. Scoring its vertical wrap would
    report correct art as a bug -- which is what the first version did."""
    assert axes_for("horizontal") == ("horizontal",)
    assert axes_for("both") == ("horizontal", "vertical")
    assert axes_for(True) == ("horizontal", "vertical")
    assert len(score(_gradient(), axes=("horizontal",))) == 1


def test_a_transparent_margin_is_measured():
    alpha = np.zeros((32, 32), dtype=np.uint8)
    alpha[4:28, 6:30] = 255
    assert transparent_margin(alpha) == {"left": 6, "right": 2, "top": 4, "bottom": 4}


def test_a_tiny_step_on_a_smooth_tile_is_not_a_seam():
    """Still water varies by about one level internally, so a two-level wrap --
    invisible out of 255 -- divides into a ratio that looks alarming."""
    from art.seams import SeamScore
    assert SeamScore("vertical", ratio=2.2, wrap_diff=2.3, typical=1.03).seamless


def test_a_large_step_is_a_seam_however_noisy_the_tile():
    from art.seams import SeamScore
    assert not SeamScore("horizontal", ratio=2.5, wrap_diff=10.2, typical=4.05).seamless
