"""One animation laid across a grid, because some characters are wide."""

from art.measure import Anim, Frame, Group
from art.plan import plan_subject
from art.profile import Profile, Subject


def _plan(cols, frames=6, height_tiles=1.15, canvas=1254):
    prof = Profile(path=None, canvas=canvas, tile_px=192)
    sub = Subject("masie", height_tiles=height_tiles,
                  sheets={"masie-run": {"anims": ["run"], "cols": cols}},
                  raw={"sheets": {"masie-run": {"anims": ["run"], "cols": cols}}})
    groups = {"masie": Group("masie", {"run": Anim("run", [Frame(0, 0, 10, 10)] * frames)})}
    return plan_subject(prof, sub, groups)


def test_six_frames_at_three_columns_becomes_two_rows():
    sheet = _plan(3).sheets[0]
    assert (sheet.cols, sheet.rows, sheet.wrapped) == (3, 2, 6)


def test_the_grid_is_still_one_generation():
    assert _plan(3).generations == 1


def test_fewer_columns_buys_wider_cells():
    """Masie is wider than she is tall: six frames in one row would be 209px
    cells for art that has to be 240px tall. Three columns gives her 418."""
    assert _plan(6).sheets[0].cell_w == 209
    assert _plan(3).sheets[0].cell_w == 418


def test_an_uneven_count_still_gets_enough_rows():
    assert _plan(4, frames=6).sheets[0].rows == 2
    assert _plan(4, frames=9).sheets[0].rows == 3


def test_a_plain_list_is_unaffected():
    prof = Profile(path=None, canvas=1254)
    sub = Subject("frog", height_tiles=1.05, sheets={"frog": ["idle", "jump"]},
                  raw={"sheets": {"frog": ["idle", "jump"]}})
    groups = {"frog": Group("frog", {
        "idle": Anim("idle", [Frame(0, 0, 10, 10)] * 6),
        "jump": Anim("jump", [Frame(0, 0, 10, 10)] * 6)})}
    sheet = plan_subject(prof, sub, groups).sheets[0]
    assert sheet.wrapped == 0 and sheet.rows == 2
