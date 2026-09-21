"""Reference resolution: the rules that stop a redraw coming back wrong."""

from pathlib import Path

import pytest

from art.profile import Profile, Subject
from art.refs import prompt_block, resolve


@pytest.fixture
def game(tmp_path):
    for n in ("style.png", "croaks.png", "frog.png"):
        (tmp_path / n).write_bytes(b"x")
    return tmp_path


def _profile(root, **raw):
    return Profile(path=root / "art.yaml", raw=raw)


def test_a_legacy_subject_attaches_its_own_old_sheet(game):
    """Forgetting it is how a redraw comes back a different frog."""
    prof = _profile(game)
    frog = Subject("frog", state="legacy", raw={"source": {"sheet": "frog.png"}})
    assert [(r.role, r.path.name) for r in resolve(prof, frog)] == [("identity", "frog.png")]


def test_the_specific_role_wins_when_one_file_serves_two(game):
    """Sir Croaks' sheet is a style benchmark AND the statement of who he is.
    Letting `style` win would tell the model to ignore the subject it is drawing."""
    prof = _profile(game, style_ref=["style.png", "croaks.png"])
    croaks = Subject("croaks", state="legacy", raw={"source": {"sheet": "croaks.png"}})
    got = {r.path.name: r.role for r in resolve(prof, croaks)}
    assert got == {"style.png": "style", "croaks.png": "identity"}


def test_a_file_is_never_attached_twice(game):
    prof = _profile(game, style_ref=["croaks.png"])
    croaks = Subject("croaks", state="legacy", raw={"source": {"sheet": "croaks.png"}})
    refs = resolve(prof, croaks)
    assert len(refs) == 1 and refs[0].role == "identity"


def test_identity_overrides_nothing_it_should_not(game):
    """Mr Frog is 45x45 -- that is the bug, not the target -- and Masie's sheet
    shows her floating when the whole point is to make her walk. So identity
    means WHO, never how big and never which pose."""
    prof = _profile(game)
    frog = Subject("frog", state="legacy", raw={"source": {"sheet": "frog.png"}})
    block = prompt_block(resolve(prof, frog))
    assert "Image 1" in block
    assert "Do NOT copy its poses" in block and "resolution" in block
    assert "the description wins" in block


def test_a_subject_is_never_its_own_style_reference(game):
    """The style instruction says "do not copy its subject", which is nonsense
    pointed at the character being drawn."""
    prof = _profile(game, style_ref=["style.png", "croaks.png"])
    croaks = Subject("croaks", state="legacy", raw={"source": {"sheet": "croaks.png"}})
    roles = {r.path.name: r.role for r in resolve(prof, croaks)}
    assert roles == {"style.png": "style", "croaks.png": "identity"}


def test_missing_files_are_skipped_rather_than_promised(game):
    prof = _profile(game, style_ref=["gone.png"])
    assert resolve(prof, Subject("x", raw={})) == []


def test_a_subject_can_replace_the_project_style_anchors(game):
    """Masie's own art is softer than the game's bolder characters. Anchoring
    her to Sir Croaks pulled her toward a harder, flatter look than she has."""
    prof = _profile(game, style_ref=["croaks.png"])
    masie = Subject("masie", raw={"style_ref": ["style.png"]})
    assert [(r.role, r.path.name) for r in resolve(prof, masie)] == [("style", "style.png")]


def test_a_subject_can_drop_the_style_anchors_entirely(game):
    prof = _profile(game, style_ref=["croaks.png"])
    masie = Subject("masie", state="legacy",
                    raw={"style_ref": [], "source": {"sheet": "frog.png"}})
    assert [r.role for r in resolve(prof, masie)] == ["identity"]


def test_identity_carries_the_rendering_when_it_is_the_only_anchor(game):
    prof = _profile(game)
    masie = Subject("masie", state="legacy", raw={"source": {"sheet": "frog.png"}})
    block = prompt_block(resolve(prof, masie))
    assert "how they are drawn" in block and "line weight" in block


def test_pose_takes_nothing_but_the_posing(game):
    """The pose reference is a previous candidate: it has the right gait and
    the wrong face, so it must not contribute anything else."""
    prof = _profile(game)
    masie = Subject("masie", raw={"reference": {"pose": "style.png"}})
    block = prompt_block(resolve(prof, masie))
    assert "LAYOUT and POSING only" in block
    assert "not the facial features" in block
