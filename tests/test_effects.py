"""Effects are metadata, and the set of them is closed."""

import pytest

from art.effects import EFFECTS, EffectError, catalogue, for_anim, normalise


def test_defaults_are_filled_in():
    got = normalise({"idle": {"breathe": {}}})["idle"]["breathe"]
    assert got == {**EFFECTS["breathe"].defaults(), "phase": "none", "anchor": "feet"}


def test_default_falls_through_and_the_animation_wins():
    n = normalise({"default": {"breathe": {"amount": 0.02}},
                   "sit": {"breathe": {"hz": 0.3}}})
    assert for_anim(n, "sit")["breathe"]["hz"] == 0.3
    assert for_anim(n, "idle")["breathe"]["hz"] == EFFECTS["breathe"].defaults()["hz"]


def test_an_unknown_effect_is_refused():
    """The set is closed because whatever draws the sprite has to implement it:
    an invented name would move in the preview and not in the game."""
    with pytest.raises(EffectError, match="unknown effect"):
        normalise({"idle": {"wobble": {}}})


def test_an_unknown_parameter_is_refused():
    with pytest.raises(EffectError, match="no parameter"):
        normalise({"idle": {"breathe": {"speed": 2}}})


@pytest.mark.parametrize("value", [-0.1, 9.0])
def test_a_value_out_of_range_is_refused(value):
    with pytest.raises(EffectError, match="outside"):
        normalise({"idle": {"breathe": {"amount": value}}})


def test_phase_is_restricted_to_known_sources():
    normalise({"idle": {"sway": {"phase": "x"}}})
    with pytest.raises(EffectError, match="phase"):
        normalise({"idle": {"sway": {"phase": "vibes"}}})


def test_standing_things_are_anchored_at_the_feet():
    """A sprite that scales about its centre lifts off the ground, and a
    cattail that rotates about its middle detaches from the soil."""
    assert EFFECTS["breathe"].anchor == "feet"
    assert EFFECTS["sway"].anchor == "feet"
    assert EFFECTS["bob"].anchor == "free"


def test_the_catalogue_describes_every_effect_for_the_preview():
    names = {e["name"] for e in catalogue()}
    assert names == set(EFFECTS)
    assert all(e["params"] and e["help"] for e in catalogue())
