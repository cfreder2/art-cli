"""Frame detection: gaps are the delimiter, and alpha is never binary."""

import numpy as np

from art.cut import MIN_GAP_PX, alpha_from_colour, find_rows, hex_to_rgb, unspill

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
