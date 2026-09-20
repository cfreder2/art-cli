"""Making a generated tile tile, since a generator will not."""

import numpy as np
import pytest

from art.seamless import make_seamless, wrap_step
from art.seams import score


def noisy(w=96, h=96, seed=0):
    """A SMOOTH texture that does not wrap -- which is what a generated tile is.

    Pure noise is the wrong fixture: its internal step is so large that a hard
    edge at the wrap does not stand out against it, and the seam score is
    already near 1 before anything is fixed. A real tile is smooth ground with
    one discontinuity where its edges meet.
    """
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    base = (np.sin(x / 11.0) + np.cos(y / 9.0) + np.sin((x + y) / 17.0))
    base = (base - base.min()) / (base.max() - base.min())
    # A ramp across the width guarantees the left and right edges disagree.
    base = base * 0.55 + (x / w) * 0.45
    a = np.clip(base * 210 + 25 + rng.normal(0, 3, (h, w)), 0, 255)
    rgb = np.dstack([a, a * 0.9, a * 0.8]).astype(np.uint8)
    return np.dstack([rgb, np.full((h, w), 255, np.uint8)])


@pytest.mark.parametrize("axis", ["horizontal", "vertical", "both"])
def test_the_wrap_becomes_continuous(axis):
    a = noisy()
    if axis == "vertical":
        a = np.transpose(a, (1, 0, 2)).copy()
    before = score(a[..., :3], a[..., 3], (axis,) if axis != "both" else ("horizontal",))[0]
    fixed = make_seamless(a, axis)
    after = score(fixed[..., :3], fixed[..., 3],
                  (axis,) if axis != "both" else ("horizontal",))[0]
    assert after.ratio < before.ratio
    assert after.seamless, f"{after.ratio:.1f}x after"


def test_horizontal_only_leaves_the_vertical_wrap_alone():
    """Ground has grass on top and dirt below: it repeats sideways and is never
    stacked, so healing its vertical wrap would blend the sky into the soil."""
    a = noisy()
    fixed = make_seamless(a, "horizontal")
    wrap_v_before, _ = wrap_step(a, "vertical")
    wrap_v_after, _ = wrap_step(fixed, "vertical")
    assert wrap_v_after == pytest.approx(wrap_v_before, rel=0.5)


def test_it_still_looks_like_the_tile():
    """The blend softens detail; it must not flatten it."""
    a = noisy()
    fixed = make_seamless(a, "horizontal")
    spread = fixed[..., :3].std()
    assert spread > a[..., :3].std() * 0.4


def test_alpha_survives():
    a = noisy()
    a[..., 3] = 128
    assert make_seamless(a, "both")[..., 3].mean() == pytest.approx(128, abs=2)


def test_the_atlas_cannot_grow_past_what_webp_can_encode():
    """Appending everything below the old atlas made a 20,000px strip, and
    WebP refuses either dimension past 16383."""
    from art.pack import MAX_SIDE
    assert MAX_SIDE == 16383


def test_a_narrow_feather_ghosts_far_less():
    """A strip with transparent sides cannot blend across a third of itself:
    the half-rolled copy shows through the gaps as a second, pale object.

    The stem has to WANDER for this to bite. A perfectly straight one lands on
    top of itself when rolled and cannot ghost at all, which is what the first
    version of this test measured.
    """
    h, w = 240, 48
    a = np.zeros((h, w, 4), np.uint8)
    a[..., :3] = 120
    for y in range(h):
        cx = int(w / 2 + (w / 3) * np.sin(y / 19.0))
        a[y, max(0, cx - 5):cx + 5, 3] = 255

    def ghost(f):
        out = make_seamless(a, "vertical", feather=f)
        return float(((out[..., 3] > 40) & (a[..., 3] <= 40)).mean())

    wide, narrow = ghost(0.35), ghost(0.04)
    assert wide > 0.002, f"fixture does not ghost at all ({wide:.4f})"
    assert narrow < wide / 2, (narrow, wide)
