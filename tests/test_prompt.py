"""The constraint block: every line is a failure that already happened."""

from art.plan import SheetPlan
from art.profile import Profile, Subject
from art.prompt import SHEET_RULES, build


def _sheet(**kw):
    base = dict(name="s", anims=["run"], cols=3, rows=2, cell_w=418, cell_h=627,
                min_drawn=240, facings=1, wrapped=6)
    base.update(kw)
    return SheetPlan(**base)


def _text(subject=None, **profile_kw):
    prof = Profile(path=None, canvas=1254, backdrop="#00FF00", **profile_kw)
    sub = subject or Subject("masie", height_tiles=1.15, raw={})
    return build(prof, sub, _sheet(), None, [], "")


def test_every_limb_appears_in_every_frame():
    """A side-view quadruped loses its far legs where they overlap the body.
    Two separate Masie candidates came back with three legs in half the frames."""
    text = _text()
    assert "FOUR legs in all of them" in text
    assert "slightly DARKER shade" in text


def test_the_groundline_rule_does_not_contradict_itself():
    """`no groundline` and `sits on the same groundline` were both in here."""
    text = _text()
    assert "Do not DRAW a groundline" in text
    assert "same invisible one" in text


def test_a_wrapped_sheet_explains_the_reading_order():
    text = _text()
    assert "left to right" in text and "frame 4 sits below frame 1" in text


def test_the_backdrop_named_is_the_subjects_own():
    sub = Subject("masie", height_tiles=1.15, raw={"backdrop": "#00FF00"})
    assert "FLAT #00FF00" in _text(sub)


def test_a_subject_can_override_the_project_style():
    sub = Subject("masie", height_tiles=1.15, raw={"style": "soft and cute"})
    assert "Style: soft and cute" in _text(sub, style="bold and flat")


def test_the_minimum_height_is_stated_as_the_point():
    assert "AT LEAST 240px tall" in _text()


def test_every_rule_is_a_single_instruction():
    assert len(SHEET_RULES) >= 8
    assert all(r.strip() and not r.startswith("-") for r in SHEET_RULES)
