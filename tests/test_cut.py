import pytest
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


def test_packing_twice_does_not_grow_the_atlas(tmp_path):
    """Every accepted sheet is re-cut on every pack, so what a previous pack
    appended is superseded in full. Appending below it instead grew AXI's atlas
    by the whole redraw each time, until it passed the side WebP can encode and
    packing stopped working."""
    import json
    import numpy as np
    from PIL import Image
    from art import cut as cut_mod, pack as pack_mod

    png, js = tmp_path / "atlas.png", tmp_path / "atlas.json"
    Image.new("RGBA", (64, 64), (10, 20, 30, 255)).save(png)
    js.write_text(json.dumps({"image": "atlas.png", "w": 64, "h": 64,
                              "tiles": {"rock": [0, 0, 32, 32, 0, 16]}}))

    def pack_once():
        art = Image.fromarray(np.full((48, 48, 4), 200, np.uint8))
        rep = pack_mod.Replacement(
            group="tiles", anim="rock", frames=[cut_mod.Box(0, 0, 48, 48)],
            images=[art], old_frames=1)
        return pack_mod.merge(png, js, [rep], png, js)

    first = pack_once()
    second = pack_once()
    assert (second.width, second.height) == (first.width, first.height)

    # ...and the legacy art it was told to keep is still where it was.
    kept = np.asarray(Image.open(png).convert("RGBA"))[:64, :64]
    assert kept[..., 3].all(), "the base was cropped away, not just reused"


def test_packing_twice_still_remembers_the_original_size(tmp_path):
    """`scale_for` asks how big a row USED to look. Reading that from the
    current atlas reads the LAST pack's output, so old == new, every scale
    rounds to exactly 1.0, and the correction quietly stops correcting. AXI
    shipped 39 rows of 1.0 while her jump, climb, swim and defeat sat 21-32%
    oversized against an original that had held within 11%."""
    import json
    import numpy as np
    from PIL import Image
    from art import cut as cut_mod, pack as pack_mod

    png, js = tmp_path / "atlas.png", tmp_path / "atlas.json"
    Image.new("RGBA", (64, 64), (10, 20, 30, 255)).save(png)
    # Two rows the same size, and `idle` is the one the game measures by.
    js.write_text(json.dumps({
        "image": "atlas.png", "w": 64, "h": 64,
        "axi": {"idle": [[0, 0, 32, 32, 0, 16]],
                "jump": [[0, 0, 32, 32, 0, 16]]}}))

    # The redraw is 3x, but `jump` came back half again as big on top of that
    # -- exactly the drift the multiplier exists to undo.
    redrawn = {"idle": cut_mod.Box(0, 0, 96, 96), "jump": cut_mod.Box(0, 0, 144, 144)}

    def pack_once():
        reps = []
        for anim, box in redrawn.items():
            art = Image.fromarray(np.full((box.h, box.w, 4), 200, np.uint8))
            reps.append(pack_mod.Replacement(
                group="axi", anim=anim, frames=[box], images=[art], old_frames=1,
                scale=pack_mod.scale_for(
                    [box],
                    pack_mod.original_row(json.loads(js.read_text()), "axi", anim),
                    [redrawn["idle"]],
                    pack_mod.original_row(json.loads(js.read_text()), "axi", "idle"))))
        return pack_mod.merge(png, js, reps, png, js)

    pack_once()
    after_first = json.loads(js.read_text())["scales"]["axi/jump"]
    pack_once()
    after_second = json.loads(js.read_text())["scales"]["axi/jump"]

    assert after_first == pytest.approx(1 / 1.5, rel=1e-3), \
        "the first pack should have undone the 1.5x drift"
    assert after_second == after_first, (
        f"the correction decayed to {after_second} on the second pack; "
        "the original size was overwritten by the redraw")


def test_the_reference_row_is_never_rescaled(tmp_path):
    """The game sizes a character BY the reference row, read out of the atlas
    it is drawing from -- `1.15 / atlas.axi.idle[0][3]`. That measurement
    already accounts for however the row was redrawn, so a multiplier on top
    of it corrects the same thing twice.

    It did. `scale_for` divided apparent size by frame-0 HEIGHT, two different
    measures, so the reference did not cancel: Masie packed at 0.85134 and
    drew at 0.979 tiles where the game asks for 1.15. Every row of her was 15%
    small at once, which is exactly the way a bug like this hides -- nothing
    looked inconsistent, she was just smaller than she was meant to be."""
    from art import pack as pack_mod
    from art.cut import Box

    was = [[0, 0, 32, 40, 0, 16]]
    # Redrawn bigger, and reshaped: longer and lower, so frame height alone
    # says something different from apparent size. This is the case that broke.
    now = [Box(0, 0, 140, 96)]
    assert pack_mod.scale_for(now, was, now, was) == 1.0

    # And a row that came back the same size as the reference reads the same
    # size as the reference, whatever either of them used to be.
    assert pack_mod.scale_for(now, was, now, was) == \
        pack_mod.uniform_scale_for(now, now, 1.0)


def test_uniform_scale_makes_every_row_read_the_same_size():
    """AXI's original art had jump at 0.96x her idle and landing at 0.90x, so
    preserving each row's old size preserved a character who shrank 4% when
    she left the ground. Uniform scale matches apparent size across the
    subject instead, and leaves the reference row alone."""
    from art import pack as pack_mod
    from art.cut import Box

    ref = [Box(0, 0, 100, 100)]           # apparent 100
    tall = [Box(0, 0, 50, 128)]           # apparent 80 -- reads 20% small
    wide = [Box(0, 0, 200, 72)]           # apparent 120 -- reads 20% big

    assert pack_mod.uniform_scale_for(ref, ref, 0.85) == 0.85, \
        "the reference row must keep the multiplier it was given"
    assert pack_mod.uniform_scale_for(tall, ref, 1.0) == pytest.approx(1.25, rel=1e-3)
    assert pack_mod.uniform_scale_for(wide, ref, 1.0) == pytest.approx(0.8333, rel=1e-3)

    # Scale-free: the same shapes drawn twice as large need the same correction.
    big_tall = [Box(0, 0, 100, 256)]
    assert (pack_mod.uniform_scale_for(big_tall, [Box(0, 0, 200, 200)], 1.0)
            == pytest.approx(1.25, rel=1e-3))


def test_redrawing_the_reference_row_carries_its_untouched_siblings(tmp_path):
    """A game sizes a whole group off one row -- `1.05 / frog_idle[0][3]` --
    so redrawing that row alone resizes every row beside it, including the
    ones this pack never looked at.

    AXI's frog came back at 339px against an original of 90-odd, and his four
    untouched rows went on being drawn at their own 45px through a scale meant
    for 339: a seventh of a tile, a speck. Nothing drew those rows any more so
    nobody saw it -- but Sir Croaks is eight rows of one group, and redrawing
    only his idle would have done the same to the other seven."""
    import json
    import numpy as np
    from PIL import Image
    from art import cut as cut_mod, pack as pack_mod

    png, js = tmp_path / "atlas.png", tmp_path / "atlas.json"
    Image.new("RGBA", (64, 64), (10, 20, 30, 255)).save(png)
    js.write_text(json.dumps({
        "image": "atlas.png", "w": 64, "h": 64,
        "frog": {"idle": [[0, 0, 40, 40, 0, 20]],      # the reference
                 "sit":  [[0, 0, 40, 40, 0, 20]]}}))   # never redrawn

    art = Image.fromarray(np.full((160, 160, 4), 200, np.uint8))
    pack_mod.merge(png, js, [pack_mod.Replacement(
        group="frog", anim="idle", frames=[cut_mod.Box(0, 0, 160, 160)],
        images=[art], old_frames=1, scale=1.0, ref="idle")], png, js)

    out = json.loads(js.read_text())
    assert out["scales"]["frog/idle"] == 1.0, "the reference is never rescaled"
    # The reference grew 4x, so the game's scale for the group is 4x smaller
    # and the row that did not move needs 4x to stay where it was.
    assert out["scales"]["frog/sit"] == pytest.approx(4.0, rel=1e-3)

    # Which is the whole point: `sit` still draws the size it always did.
    base_before = 1.05 / 40
    base_after = 1.05 / out["frog"]["idle"][0][3]
    assert (out["frog"]["sit"][0][3] * base_after * out["scales"]["frog/sit"]
            == pytest.approx(40 * base_before, rel=1e-3))
