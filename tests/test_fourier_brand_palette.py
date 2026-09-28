"""Regression coverage for approved colours and consistent deck assignments."""

import pytest

from adaptive_document_agent.services.fourier_brand import (
    ALL_CHART_COLORS, AMBER, APPROVED_COLORS, CHART_COLORS, CYAN, LIGHT_PURPLE, PRIMARY,
    TEXT, WHITE, label_color, normalize_brand_color, relative_luminance,
)
from adaptive_document_agent.services.presentation_style import (
    PALETTE, chart_color, deck_color_map, normalize_chart_color_map,
)


def test_deck_assignments_survive_ordering_and_equivalent_spellings():
    keys = ["West", "East", "Digital", " east  ", "EAST"]
    mapping = deck_color_map(keys)
    assert mapping == deck_color_map(list(reversed(keys)))
    assert mapping["East"] == mapping[" east  "] == mapping["EAST"]
    assert len({mapping[key] for key in ("West", "East", "Digital")}) == 3
    assert PRIMARY in mapping.values()
    assert chart_color("West", mapping) == mapping["West"]


def test_complete_palette_has_distinct_approved_colors():
    assert PALETTE is CHART_COLORS
    assert len(set(CHART_COLORS)) == 8
    assert set(CHART_COLORS) <= APPROVED_COLORS
    assert set(deck_color_map([str(index) for index in range(8)]).values()) == set(CHART_COLORS)
    assert set(deck_color_map([str(index) for index in range(40)]).values()) <= set(CHART_COLORS)


def test_cooccurrence_groups_keep_independent_metrics_purple_and_series_distinct():
    independent = deck_color_map(["Revenue", "Volume"], groups=[["Revenue"], ["Volume"]])
    assert set(independent.values()) == {PRIMARY}
    groups = [["East", "West"], ["West", "Central"], ["Revenue"]]
    mapping = deck_color_map([], groups=groups)
    assert mapping == deck_color_map([], groups=[list(reversed(group)) for group in reversed(groups)])
    assert mapping["East"] != mapping["West"]
    assert mapping["West"] != mapping["Central"]
    assert mapping["East"] == mapping["Central"]
    assert mapping["Revenue"] == PRIMARY


def test_dense_groups_use_only_additional_vi_colors_then_fail_explicitly():
    keys = [str(index) for index in range(len(ALL_CHART_COLORS))]
    mapping = deck_color_map(keys, groups=[keys])
    assert set(mapping.values()) == set(ALL_CHART_COLORS)
    assert all(chart_color(key, mapping) == color for key, color in mapping.items())
    keys.append("overflow")
    with pytest.raises(ValueError, match="palette capacity"):
        deck_color_map(keys, groups=[keys])


def test_migrating_a_legacy_deck_map_resolves_alias_collisions_once():
    original = {"East": "5B21B6", "West": "5B21B6", "Small": "5B21B6"}
    mapping = normalize_chart_color_map(original)
    assert len(set(mapping.values())) == 3
    assert mapping == normalize_chart_color_map(dict(reversed(list(original.items()))))
    assert original["East"] == "5B21B6"


@pytest.mark.parametrize(("legacy", "expected"), [
    ("5B21B6", PRIMARY), ("#ab74ff", LIGHT_PURPLE),
    ("F4B923", AMBER), ("20ECF1", CYAN),
])
def test_legacy_generated_chart_maps_cannot_reintroduce_wrong_colors(legacy, expected):
    assert chart_color("Metric", {"Metric": legacy}) == expected


def test_unknown_color_and_neutral_chart_assignment_use_approved_palette():
    for color in ("123456", "not a colour", TEXT, WHITE):
        assert chart_color("Metric", {"Metric": color}) in CHART_COLORS
    assert normalize_brand_color("123456") == PRIMARY
    with pytest.raises(ValueError):
        normalize_brand_color(PRIMARY, fallback="123456")


@pytest.mark.parametrize("background", sorted(APPROVED_COLORS))
def test_labels_have_accessible_contrast_against_every_approved_fill(background):
    foreground = label_color(background)
    assert foreground in (TEXT, WHITE)
    luminances = sorted((relative_luminance(background), relative_luminance(foreground)))
    assert (luminances[1] + 0.05) / (luminances[0] + 0.05) >= 4.5


def test_bright_auxiliary_colors_use_black_labels():
    assert label_color(AMBER) == TEXT
    assert label_color(CYAN) == TEXT
    assert label_color(PRIMARY) == WHITE
