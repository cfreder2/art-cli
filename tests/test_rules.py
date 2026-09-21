"""Each rule is a failure that has actually happened to this art."""

import numpy as np
import pytest

from art import rules
from art.cut import Box, hex_to_rgb

GREEN = hex_to_rgb("#00FF00")

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


def test_an_outline_the_key_would_eat_is_caught():
    """It happened to Sir Croaks on the navy sheet, in every frame: the outline
    sat close enough to the backdrop that keying took it too."""
    alpha = np.zeros((40, 40), float); alpha[5:35, 5:35] = 1.0
    art = np.full((40, 40, 3), 200, np.uint8)
    edge = rules._silhouette_edge(alpha)

    at_risk = art.copy(); at_risk[edge] = GREEN            # edge IS the backdrop
    assert len(rules.outline(at_risk, alpha, GREEN, "x")) == 1

    safe = art.copy(); safe[edge] = (40, 20, 30)           # a dark outline
    assert rules.outline(safe, alpha, GREEN, "x") == []


def test_a_bright_edge_is_not_a_missing_outline():
    """A ground tile is bright grass over dark earth, and a glassy gem has a
    bright rim. Testing "darker than the fill" failed both."""
    alpha = np.ones((40, 40), float)
    art = np.full((40, 40, 3), 60, np.uint8)
    art[rules._silhouette_edge(alpha)] = (240, 250, 235)
    assert rules.outline(art, alpha, GREEN, "x") == []


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


def test_a_soft_edge_is_not_an_eaten_outline():
    """A cloud and a mossy log both have a band of semi-transparent pixels
    leaning toward the backdrop. That is what a soft edge is, and both composite
    cleanly on white and on dark."""
    alpha = np.zeros((60, 60), float)
    alpha[10:50, 10:50] = 1.0
    # a two-pixel fringe of half-transparent, backdrop-tinted pixels
    alpha[8:10, 8:52] = alpha[50:52, 8:52] = 0.45
    alpha[8:52, 8:10] = alpha[8:52, 50:52] = 0.45
    art = np.full((60, 60, 3), 210, np.uint8)
    art[alpha == 0.45] = GREEN
    art[rules._silhouette_edge(alpha, threshold=0.85)] = (30, 25, 40)
    assert rules.outline(art, alpha, GREEN, "cloud") == []


def test_a_prop_that_changes_shape_is_caught():
    """Eleven of AXI's fifteen props came back a different shape and nothing
    failed: every rule measured height, squareness or seams, none measured
    shape. The flower went 1.78:1 -> 0.76:1, the log 3.15:1 -> 1.59:1."""
    from art import rules
    from art.cut import Box

    # A flower declared low and wide (192x110) that came back upright.
    assert rules.prop_shape(Box(0, 0, 150, 197), (192, 110), "decor/flower")
    # The same flower drawn correctly, just twice as large -- which is the
    # whole point of the resolution work and must not be a finding.
    assert not rules.prop_shape(Box(0, 0, 384, 220), (192, 110), "decor/flower")
    # A prop that declares no height cannot be judged.
    assert not rules.prop_shape(Box(0, 0, 150, 197), None, "decor/flower")
