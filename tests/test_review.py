"""Agentic review: the parsing and the contact sheet, not the model."""

import pytest
from PIL import Image

from art.review import LOOK_FOR, ReviewError, build_prompt, contact_sheet, parse


def test_findings_are_parsed_and_numbered_from_one():
    """The model is shown FRAME 1..n; everything else here is 0-based."""
    notes = parse('{"findings": [{"frame": 4, "issue": "five legs", "severity": "high"}]}')
    assert len(notes) == 1 and notes[0].frame == 3 and notes[0].high


def test_a_sheet_wide_finding_has_no_frame():
    notes = parse('{"findings": [{"frame": null, "issue": "cheek blush", "severity": "low"}]}')
    assert notes[0].frame is None and not notes[0].high


def test_prose_around_the_json_is_tolerated():
    notes = parse('Here is what I found:\n```json\n{"findings": '
                  '[{"frame": 1, "issue": "doubled tail"}]}\n```\nHope that helps.')
    assert len(notes) == 1 and notes[0].issue == "doubled tail"


def test_a_clean_sheet_parses_to_nothing():
    assert parse('{"findings": []}') == []


def test_a_reply_with_no_findings_block_is_an_error_not_a_pass():
    """Silently treating a failed call as "clean" is the worst outcome."""
    with pytest.raises(ReviewError, match="No findings block"):
        parse("I could not open the image.")


def test_empty_issues_are_dropped():
    assert parse('{"findings": [{"frame": 1, "issue": "  "}]}') == []


def test_the_prompt_names_every_check_and_the_character():
    text = build_prompt("a pink axolotl", "run", 10)
    assert "a pink axolotl" in text and '10 poses of "run"' in text
    assert all(c[:24] in text for c in LOOK_FOR)


def test_the_contact_sheet_labels_every_frame(tmp_path):
    frames = [Image.new("RGBA", (40, 30), (255, 0, 0, 255)) for _ in range(7)]
    out = contact_sheet(frames, tmp_path / "c.png", per_row=5, cell=100)
    im = Image.open(out)
    assert im.size == (500, 2 * (100 + 46))     # 7 frames wrap to two rows
