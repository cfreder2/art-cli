"""Each rule is a failure that has actually happened to this art."""

import numpy as np
import pytest

from art import rules
from art.cut import Box, hex_to_rgb

GREEN = hex_to_rgb("#00FF00")


def box(w=100, h=100, lift=0):
    b = Box(0, 0, w, h); b.lift = lift; return b


def test_a_character_shorter_than_its_minimum_is_caught():
    """Mr Frog came back 199px against a 220px minimum, which is the six
    columns of a 1254 canvas capping him -- and it shipped unnoticed."""
    found = rules.undersized([box(h=199)], "character", 220, 192, "frog/idle")
    assert len(found) == 1 and "199px" in found[0].detail and found[0].fatal


def test_a_character_that_clears_its_minimum_is_not():
    assert rules.undersized([box(h=246)], "character", 240, 192, "masie/run") == []


def test_terrain_must_be_exactly_one_tile():
    assert rules.undersized([box(192, 192)], "tile", None, 192, "ground") == []
    assert len(rules.undersized([box(190, 192)], "tile", None, 192, "ground")) == 1


def test_frames_that_merged_are_reported_with_both_counts():
    found = rules.merged_frames(5, 6, "frog/jump")
    assert "found 5" in found[0].detail and "expected 6" in found[0].detail


def test_a_row_that_matches_is_silent():
    assert rules.merged_frames(6, 6, "frog/jump") == []


def test_backdrop_left_inside_the_art_is_a_halo():
    rgb = np.zeros((40, 40, 3), np.uint8); rgb[:] = (200, 120, 140)
    alpha = np.ones((40, 40), float)
    assert rules.halo(rgb, alpha, GREEN, "x") == []
    rgb[10:30, 10:30] = GREEN
    assert len(rules.halo(rgb, alpha, GREEN, "x")) == 1


def test_an_outline_eaten_by_the_key_is_caught():
    """It happened to Sir Croaks on the navy sheet, in every frame."""
    alpha = np.zeros((40, 40), float); alpha[5:35, 5:35] = 1.0
    flat = np.full((40, 40, 3), 200, np.uint8)
    assert len(rules.outline(flat, alpha, "x")) == 1       # no outline at all
    outlined = flat.copy()
    edge = rules._silhouette_edge(alpha)
    outlined[edge] = 40
    assert rules.outline(outlined, alpha, "x") == []


def test_a_terrain_margin_is_a_seam():
    alpha = np.zeros((40, 40), float); alpha[4:36, 4:36] = 1.0
    found = rules.tile_margin(alpha, "ground")
    assert len(found) == 1 and "4px" in found[0].detail
    full = np.ones((40, 40), float)
    assert rules.tile_margin(full, "ground") == []


def test_baseline_spread_warns_but_does_not_fail():
    """A hop SHOULD leave the ground -- lift is what preserves the bounce --
    so only a person can say which rows are meant to be planted."""
    found = rules.baseline_spread([box(h=100, lift=0), box(h=100, lift=60)], "frog/jump")
    assert len(found) == 1 and not found[0].fatal


def test_a_planted_row_is_silent():
    assert rules.baseline_spread([box(h=100, lift=0), box(h=100, lift=3)], "x") == []
