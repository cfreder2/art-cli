"""The constraint block: every line is a failure that already happened."""

import re

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


def _water():
    """One sheet, two tiles, two ways of repeating -- AXI's pond."""
    return Subject("terrain_water", kind="tile", raw={
        "anims": {"water_surface": {"summary": "the waterline"},
                  "water_body": {"summary": "the water under it"}},
        "seamless": {"water_surface": "horizontal", "water_body": "both"},
        "joins": {"water_surface": "water_body"},
    })


def _gallery():
    return _sheet(anims=["water_surface", "water_body"], cols=2, rows=1,
                  cell_w=627, cell_h=1254, min_drawn=200, wrapped=0,
                  gallery=True)


def test_the_callers_note_survives_the_per_cell_direction():
    """`--note` and the frames `issues` flagged arrive in `note`. Reading each
    cell's own direction into that same name dropped them, and printed the last
    animation's raw dict at the foot of the prompt instead."""
    prof = Profile(path=None, canvas=1254, backdrop="#00FF00")
    text = build(prof, _water(), _gallery(), None, [], "draw the foam softer")

    assert "Also: draw the foam softer" in text
    assert "'summary'" not in text, "a raw dict reached the generator"


def test_a_sheet_whose_tiles_repeat_differently_says_so_per_tile():
    """Stating one rule for the sheet is a lie about whichever tile it does not
    describe: `both` rolls the crest out of the surface, `horizontal` leaves the
    body with the vertical seam that is the whole bug."""
    prof = Profile(path=None, canvas=1254, backdrop="#00FF00")
    text = build(prof, _water(), _gallery(), None, [], "")

    assert "water_surface: It TILES SIDE BY SIDE" in text
    assert "water_body: It TILES IN BOTH DIRECTIONS" in text
    assert "water_surface is drawn directly ON TOP OF water_body" in text


def _prop_sheet(**kw):
    base = dict(name="decor", anims=["log", "cattail"], cols=2, rows=1,
                cell_w=627, cell_h=627, min_drawn=240, facings=1, gallery=True)
    base.update(kw)
    return SheetPlan(**base)


def _prop_text():
    prof = Profile(path=None, canvas=1254, backdrop="#00FF00")
    sub = Subject("decor", raw={
        "kind": "prop",
        "anims": {
            "log": {"summary": "a fallen mossy log", "width_tiles": 1.6,
                    "height_tiles": 0.5},
            "cattail": {"summary": "tall reeds", "width_tiles": 1.5,
                        "height_tiles": 3.2},
        },
    })
    sub.kind = "prop"
    return build(prof, sub, _prop_sheet(), None, [], "")


def test_a_prop_is_not_prompted_as_a_character():
    """Props went through SHEET_RULES, whose size line says the subject must be
    AT LEAST Npx tall and must fill its cell. Told that, the generator drew
    every prop to one height: eleven of AXI's fifteen changed shape at once."""
    text = _prop_text()
    assert "must be AT LEAST" not in text
    assert "FOUR legs in all of them" not in text
    assert "faces the SAME direction" not in text


def test_each_prop_carries_its_own_size():
    """A shared size is the defect. The log is long and low, the reed tall and
    thin, and each has to be told so in its own cell."""
    text = _prop_text()
    sizes = dict(zip(["log", "cattail"], [None, None]))
    for name, want in (("log", 1.6 / 0.5), ("cattail", 1.5 / 3.2)):
        m = re.search(rf"Cell \d: {name} .*?\[draw this one (\d+)x(\d+)px", text)
        assert m, f"{name} carries no size"
        w, h = int(m.group(1)), int(m.group(2))
        sizes[name] = (w, h)
        # The SHAPE is the load-bearing part -- the game takes a prop's height
        # from its source aspect alone -- so that is what is asserted.
        assert abs((w / h) / want - 1) < 0.02, f"{name} drawn {w}x{h}, want {want:.2f}:1"
    assert sizes["log"][0] > 400, "the log should grow to fill its cell's width"
    assert "long and low" in text
    assert "clearly taller than it is wide" in text
    assert "do NOT stretch an item to reach the sides of its cell" in text
