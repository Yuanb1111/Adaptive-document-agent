"""Template typography remains readable without losing profile source copy."""

import pytest

from adaptive_document_agent.services.presentation_brief import (
    BriefItem, render_brief, render_profile, render_summary,
)
from tests.test_presentation_brief import blank_deck, visible


def _assert_template_type(slide):
    bodies = [shape for shape in slide.shapes if shape.name == "brief:body"]
    assert bodies
    for shape in bodies:
        for paragraph in shape.text_frame.paragraphs:
            assert paragraph.font.name == "Arial"
            assert paragraph.font.size.pt == 16
    for shape in slide.shapes:
        if shape.name == "brief:heading":
            assert all(paragraph.font.size.pt == 18 for paragraph in shape.text_frame.paragraphs)


@pytest.mark.parametrize("count", [3, 4])
def test_company_snapshot_grid_uses_template_type_with_all_evidence(count):
    deck = blank_deck()
    items = [BriefItem(f"Scope {index}", "Reported activities include manufacturing and service.", [index + 1])
             for index in range(count)]
    slides = render_profile(deck, "Company at a Glance", items, notes="Full source inventory.")
    assert len(slides) == 1
    _assert_template_type(slides[0])
    assert all(item.text in visible(slides[0]) for item in items)
    assert "Full source inventory." in slides[0].notes_slide.notes_text_frame.text
    for item in items:
        assert f"p. {item.pages[0]}" in slides[0].notes_slide.notes_text_frame.text


@pytest.mark.parametrize("count", [2, 4])
def test_summary_and_brief_use_consistent_body_and_heading_sizes(count):
    deck = blank_deck()
    items = [BriefItem(f"Finding {index}", "The reported scope excludes overseas operations.", [index + 1])
             for index in range(count)]
    render_summary(deck, "Selected findings", items)
    _assert_template_type(deck.slides[0])
    assert all(item.text in visible(deck.slides[0]) for item in items)


def test_long_profile_accounts_for_wrapped_continuation_header_without_losing_copy():
    deck = blank_deck()
    detail = "The reported business includes regional production and service activities. " * 80
    pages = render_profile(
        deck, "Operations and distribution across the reported business activities",
        [BriefItem("Business activities", detail, [7])], notes="Original source qualifiers.",
    )
    assert len(pages) > 1
    bodies = [shape for slide in pages for shape in slide.shapes if shape.name == "brief:body"]
    assert "".join(shape.text for shape in bodies) == detail
    for slide in pages:
        _assert_template_type(slide)
        title_bottom = max(shape.top.inches + shape.height.inches for shape in slide.placeholders
                           if shape.placeholder_format.idx in (14, 15))
        for shape in slide.shapes:
            if shape.name in ("brief:heading", "brief:body"):
                assert shape.top.inches >= title_bottom + .12
                assert shape.top.inches + shape.height.inches <= deck.slide_height.inches - 1.28
        assert "p. 7" in visible(slide)
        assert "Original source qualifiers." in slide.notes_slide.notes_text_frame.text


def test_brief_keeps_complete_caveat_and_raw_source_note():
    deck = blank_deck()
    text = "The result is limited to the disclosed operations; no estimate is made for missing entities."
    notes = "Source: original value (1,250); original unit unchanged."
    render_brief(deck, "Scope", [BriefItem("Boundary", text, [9])], notes=notes)
    _assert_template_type(deck.slides[0])
    assert text in visible(deck.slides[0])
    assert notes in deck.slides[0].notes_slide.notes_text_frame.text
