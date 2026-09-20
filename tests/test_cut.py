"""Frame detection: gaps are the delimiter, and alpha is never binary."""

import numpy as np

from art.cut import (MIN_GAP_PX, alpha_from_colour, find_rows, hex_to_rgb,
                     keyed, unspill)

MAGENTA = hex_to_rgb("#FC309B")


def sheet(rows=2, cols=3, cell=40, blob=20, gap=30):
    """A sheet of dark blobs on a flat magenta backdrop."""
    h = rows * (cell + gap) + gap
    w = cols * (cell + gap) + gap
    a = np.zeros((h, w, 3), dtype=np.uint8)
    a[:, :] = MAGENTA
    for r in range(rows):
        for c in range(cols):
            y = gap + r * (cell + gap)
            x = gap + c * (cell + gap)
            a[y:y + blob, x:x + blob] = (20, 30, 25)
    return a


def test_rows_and_frames_are_found_by_their_gaps():
    rows = find_rows(alpha_from_colour(sheet(rows=3, cols=4), MAGENTA))
    assert len(rows) == 3
    assert all(len(r.boxes) == 4 for r in rows)


def test_touching_frames_merge_rather_than_split_wrongly():
    """Section 7.6 is a rule because this is what happens without it: the
    detector cannot invent a boundary that the art does not leave."""
    a = sheet(rows=1, cols=2, gap=30)
    a[30:50, 30:110] = (20, 30, 25)      # bridge the two blobs together
    rows = find_rows(alpha_from_colour(a, MAGENTA))
    assert len(rows[0].boxes) == 1


def test_alpha_is_a_ramp_not_a_threshold():
    """A binary mask is what the white halo and the magenta rind both are: a
    pixel where the drawing faded into the backdrop is PARTLY transparent,
    because that is what it actually is."""
    # ~104 away from the key, which lands inside the ramp band (60..130).
    edge = np.array([[[192, 108, 95]]], dtype=np.uint8)
    a = float(alpha_from_colour(edge, MAGENTA)[0, 0])
    assert 0.0 < a < 1.0


def test_backdrop_is_fully_transparent_and_art_fully_opaque():
    alpha = alpha_from_colour(sheet(), MAGENTA)
    assert alpha.min() == 0.0 and alpha.max() == 1.0


def test_lift_is_measured_against_the_rows_lowest_pixel():
    a = sheet(rows=1, cols=2, gap=30)
    a[30:50, 30:50] = MAGENTA           # clear the first blob
    a[40:60, 30:50] = (20, 30, 25)      # redraw it 10px lower
    rows = find_rows(alpha_from_colour(a, MAGENTA))
    lifts = sorted(b.lift for b in rows[0].boxes)
    assert lifts == [0, 10]


def test_unspill_pulls_key_dominant_pixels_back():
    pink = np.array([[[250, 120, 170]]], dtype=np.uint8)
    assert unspill(pink, MAGENTA)[0, 0, 0] < 250


def test_a_gap_smaller_than_the_minimum_does_not_split():
    # blob == cell, so the space between the two blobs really is `gap`.
    a = sheet(rows=1, cols=2, cell=20, blob=20, gap=MIN_GAP_PX - 2)
    assert len(find_rows(alpha_from_colour(a, MAGENTA))[0].boxes) == 1


def test_a_known_column_count_rescues_frames_the_generator_crowded():
    """The first generated sheet left 5px between two frames of a hop, below
    the 24px the rules ask for, and they merged into one box twice the width of
    its neighbours. Relaxing the gap only until the KNOWN count is reached
    cannot over-split, because the count is the thing being satisfied."""
    a = np.zeros((80, 180, 3), dtype=np.uint8)
    a[:, :] = MAGENTA
    # Three frames; the last two only 3px apart, under MIN_GAP_PX.
    for x0 in (30, 80, 103):
        a[30:50, x0:x0 + 20] = (20, 30, 25)

    # Without a count to aim at, the crowded pair merges into one box.
    merged = find_rows(alpha_from_colour(a, MAGENTA))[0]
    assert len(merged.boxes) == 2

    row = find_rows(alpha_from_colour(a, MAGENTA), expect=3)[0]
    assert len(row.boxes) == 3
    assert row.gap_used < MIN_GAP_PX
    assert row.complete


def test_a_row_that_cannot_reach_the_count_is_marked_not_forced():
    a = sheet(rows=1, cols=2, cell=20, blob=20, gap=30)
    row = find_rows(alpha_from_colour(a, MAGENTA), expect=5)[0]
    assert len(row.boxes) == 2 and not row.complete


def test_a_row_that_matches_is_complete():
    row = find_rows(alpha_from_colour(sheet(rows=1, cols=4), MAGENTA), expect=4)[0]
    assert row.complete


def test_keyed_removes_the_backdrop_and_leaves_no_rind():
    """Handing on the raw sheet is what left every frame sitting in a rectangle
    of magenta in the preview."""
    out = keyed(sheet(rows=1, cols=2), MAGENTA)
    assert out.shape[2] == 4
    assert out[0, 0, 3] == 0                       # backdrop is transparent
    assert out[..., 3].max() == 255                # art is opaque
    visible = out[..., 3] > 40
    r, g, b = out[..., 0].astype(int), out[..., 1].astype(int), out[..., 2].astype(int)
    assert not (visible & (r > 170) & (g < 130) & (b > 110)).any()
