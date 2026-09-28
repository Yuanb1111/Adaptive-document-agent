"""Long cover context must not block an otherwise supported presentation."""
import json

import pytest

from adaptive_document_agent.services.pptx_export import _add_cover
from tests.test_presentation_identity_contents import _deck, _resolved_result


PURPOSE = ("Review the reported operations, regional activity and performance across the disclosed periods. " * 6
           + "The comparison excludes overseas entities and unaudited interim periods.")


def _subtitle(slide):
    return next(p for p in slide.placeholders if p.placeholder_format.idx == 15)


@pytest.mark.parametrize("document_type,expected", [
    ("Service operations report", "Service operations report"),
    ("员工调查报告", "员工调查报告"),
    ("Long qualified document classification " * 12, "Document analysis"),
    ("报告范围及比较口径的完整说明" * 30, "Document analysis"),
    ("", "Document analysis"),
])
def test_long_purpose_uses_complete_context_label_and_preserves_full_qualifiers(document_type, expected):
    result = _resolved_result()
    result.profile.document_type = document_type
    title = result.presentation_plan.company.name + " Operations Review"
    before = result.model_dump()
    deck = _deck()
    _add_cover(deck, result, title=title, purpose=PURPOSE)
    slide = deck.slides[0]
    subtitle = _subtitle(slide)
    assert subtitle.text == expected
    assert subtitle.text_frame.paragraphs[0].font.size.pt == 26
    assert subtitle.top.inches + subtitle.height.inches <= 6.15
    heading = next(p for p in slide.placeholders if p.placeholder_format.idx == 16)
    assert heading.text == title
    assert heading.text_frame.paragraphs[0].font.size.pt == 36
    notes = json.loads(slide.notes_slide.notes_text_frame.text)
    assert notes["document_purpose"] == PURPOSE
    assert notes["deferred_cover_subtitle"] == PURPOSE
    assert notes["displayed_subtitle"] == expected
    assert result.model_dump() == before


def test_long_title_promoted_to_subtitle_is_retained_in_full():
    result = _resolved_result()
    result.profile.document_type = "Annual operational review"
    title = "Regional operations and reported capacity review " * 8 + "excluding unreported subsidiaries"
    deck = _deck()
    _add_cover(deck, result, title=title, purpose="Review published evidence.")
    slide = deck.slides[0]
    assert _subtitle(slide).text == "Annual operational review"
    notes = json.loads(slide.notes_slide.notes_text_frame.text)
    assert notes["planned_title"] == title
    assert notes["deferred_cover_subtitle"] == title
    assert notes["document_purpose"] == "Review published evidence."


def test_unresolved_identity_and_duplicate_type_use_neutral_subtitle():
    result = _resolved_result()
    result.presentation_plan.company.identity_state = "UNRESOLVED"
    result.profile.document_type = "Employee survey"
    deck = _deck()
    _add_cover(deck, result, title="Employee survey", purpose=PURPOSE)
    assert _subtitle(deck.slides[0]).text == "Document analysis"
    assert result.presentation_plan.company.name not in " ".join(
        s.text for s in deck.slides[0].shapes if s.has_text_frame)


def test_fitting_qualified_subtitle_is_unchanged():
    result = _resolved_result()
    purpose = "Scope excludes overseas entities."
    deck = _deck()
    _add_cover(deck, result, title=result.presentation_plan.company.name, purpose=purpose)
    assert _subtitle(deck.slides[0]).text == purpose
    assert "deferred_cover_subtitle" not in json.loads(deck.slides[0].notes_slide.notes_text_frame.text)
