"""Selected summary findings remain visible, ordered and readable on every page."""

from copy import deepcopy

import pytest

from adaptive_document_agent.services.presentation_brief import BriefItem
from adaptive_document_agent.services.presentation_summary import render_complete_summary
from tests.test_presentation_brief import blank_deck, visible


def _bodies(slides):
    return [shape for slide in slides for shape in slide.shapes if shape.name == "brief:body"]


def _assert_readable_geometry(deck, slides):
    for slide in slides:
        content = [shape for shape in slide.shapes if shape.name in {"brief:body", "brief:heading"}]
        for shape in content:
            assert shape.top.inches + shape.height.inches <= deck.slide_height.inches - 1.02 + .001
            expected = 16 if shape.name == "brief:body" else 18
            assert all(p.font.size.pt == expected for p in shape.text_frame.paragraphs)
            assert all(p.font.name == "Arial" for p in shape.text_frame.paragraphs)
        for i, left in enumerate(content):
            for right in content[i + 1:]:
                overlap_x = min(left.left + left.width, right.left + right.width) - max(left.left, right.left)
                overlap_y = min(left.top + left.height, right.top + right.height) - max(left.top, right.top)
                assert overlap_x <= 0 or overlap_y <= 0


def test_five_complete_findings_share_one_page_with_the_final_item_visible():
    deck = blank_deck()
    items = [BriefItem(f"Finding {i}",
                      f"Measure {i} moved between the three reported annual periods. "
                      "The comparison retains its source boundary and does not estimate missing observations.",
                      [i + 1]) for i in range(5)]
    before = deepcopy(items)

    slides = render_complete_summary(deck, "Selected findings", items, notes="Original scope remains unchanged.")

    assert len(slides) == 1
    assert [shape.text for shape in _bodies(slides)] == [item.text for item in items]
    assert items == before
    assert _bodies(slides)[-1].width.inches > 10
    assert "Original scope remains unchanged." in slides[0].notes_slide.notes_text_frame.text
    assert all(item.title in visible(slides[0]) for item in items)
    _assert_readable_geometry(deck, slides)


def test_three_long_editorial_findings_use_one_complete_readable_page():
    deck = blank_deck()
    items = [BriefItem(f"Finding {i}",
                      "The source reports a measured change for the stated population and reporting period. " * 5,
                      [i + 1]) for i in range(3)]
    slides = render_complete_summary(deck, "Executive Summary", items, single_column=True)
    assert len(slides) == 1
    assert [shape.text for shape in _bodies(slides)] == [item.text for item in items]
    assert all(shape.text_frame.paragraphs[0].font.size.pt == 14 for shape in _bodies(slides))
    assert all(shape.top.inches + shape.height.inches <= deck.slide_height.inches - 1.02
               for shape in _bodies(slides))


@pytest.mark.parametrize("count", [1, 3, 4, 6, 7, 9, 17])
def test_all_selected_findings_are_displayed_in_model_order(count):
    deck = blank_deck()
    items = [BriefItem(f"Observation {i}", f"Complete finding {i}; its comparison excludes unreported units.", [i + 2])
             for i in range(count)]
    slides = render_complete_summary(deck, "Summary", items)

    assert [body.text for body in _bodies(slides)] == [item.text for item in items]
    assert all("Selected points; full context" not in visible(slide) for slide in slides)
    if count > 8:
        assert len(slides) > 1
        assert "(continued)" in visible(slides[1])
    for item in items:
        assert any(item.text in visible(slide) and f"p. {item.pages[0]}" in slide.notes_slide.notes_text_frame.text
                   for slide in slides)
    _assert_readable_geometry(deck, slides)


@pytest.mark.parametrize("copy", [
    "Reported coverage includes only the measured population; missing participants are excluded. " * 70,
    "仅包括已披露样本，不补充缺失数据。结论必须保留原始期间、单位和证据。" * 90,
    "UNSPACED_IDENTIFIER_WITH_QUALIFIERS_" * 200,
])
def test_oversized_finding_continues_without_losing_any_copy(copy):
    deck = blank_deck()
    items = [BriefItem("Evidence scope", copy, [47]), BriefItem("Next finding", "The next finding remains visible.", [48])]
    slides = render_complete_summary(deck, "Scope and findings", items)

    assert len(slides) > 1
    assert "".join(shape.text for shape in _bodies(slides)) == copy + items[1].text
    assert all(copy in slide.notes_slide.notes_text_frame.text for slide in slides)
    assert "The next finding remains visible." in visible(slides[-1])
    _assert_readable_geometry(deck, slides)


def test_wrapped_continuation_titles_do_not_overlap_summary_copy():
    deck = blank_deck()
    items = [BriefItem("Study result", "Source limits remain part of the finding. " * 55, [8])]
    slides = render_complete_summary(deck, "Detailed findings across the reported populations and observation periods", items)
    assert len(slides) > 1
    for slide in slides:
        header_bottom = max(shape.top.inches + shape.height.inches for shape in slide.placeholders
                            if shape.placeholder_format.idx in (14, 15))
        assert all(shape.top.inches >= header_bottom + .12 - .001
                   for shape in slide.shapes if shape.name in {"brief:body", "brief:heading"})
    _assert_readable_geometry(deck, slides)


def test_empty_summary_retains_notes_without_creating_a_continuation_loop():
    deck = blank_deck()
    slides = render_complete_summary(deck, "Summary", [], notes="No supported findings were selected.")
    assert len(slides) == 1
    assert "No supported findings" in slides[0].notes_slide.notes_text_frame.text


@pytest.mark.parametrize("short_title", ["", "Measured population", "Unusable long alternate heading " * 130],
                         ids=["no-short-title", "readable-short-title", "oversized-short-title"])
@pytest.mark.parametrize("heading", [
    "A fully qualified finding covering only the disclosed population and observation periods. " * 90,
    "本项结论仅适用于已披露的样本和期间，原始限定条件必须完整保留。" * 120,
], ids=["latin-heading", "cjk-heading"])
def test_extremely_long_item_heading_moves_into_paginated_body_without_blocking(heading, short_title):
    deck = blank_deck()
    text = "The original body retains this separate evidence qualification."
    item = BriefItem(heading, text, [53, 57], short_title)
    before = deepcopy(item)

    slides = render_complete_summary(deck, "Summary", [item], notes="Original reported value: (1,250).")

    assert len(slides) > 1
    # python-pptx exposes a paragraph's visible soft line break as vertical tab.
    assert "".join(shape.text.replace("\v", "\n") for shape in _bodies(slides)) == heading + "\n" + text
    headings = [shape.text for slide in slides for shape in slide.shapes if shape.name == "brief:heading"]
    assert headings == ([short_title] * len(slides) if short_title == "Measured population" else [])
    assert all("p. 53, 57" in visible(slide) for slide in slides)
    assert all(heading in slide.notes_slide.notes_text_frame.text for slide in slides)
    assert all("Original reported value: (1,250)." in slide.notes_slide.notes_text_frame.text for slide in slides)
    assert item == before
    _assert_readable_geometry(deck, slides)


def _planned_result(narratives, *, origin="model", use_bullets=False):
    from adaptive_document_agent.models import (
        DocumentProfile, Insight, ParsedDocument, PipelineResult,
        PresentationPlan, PresentationSlide, SourceEvidence,
    )

    insights = [Insight(id=f"finding_{i}", title=f"Finding {i + 1}", narrative=text,
                        kind="reported_fact", evidence=[SourceEvidence(
                            page=i + 1, text=text, extraction_method="digital_text", confidence=.99)])
                for i, text in enumerate(narratives)]
    summary = PresentationSlide(id="summary", slide_type="executive_summary", title="Selected findings",
                                insight_ids=[] if use_bullets else [item.id for item in insights],
                                bullets=list(narratives) if use_bullets else [],
                                source_pages=list(range(1, len(narratives) + 1)))
    result = PipelineResult(
        document=ParsedDocument(document_id="summary-source", sha256="local", safe_filename="source.pdf",
                                page_count=max(1, len(narratives))),
        profile=DocumentProfile(), insights=insights,
        presentation_plan=PresentationPlan(title="Selected findings", planning_origin=origin, slides=[summary]),
    )
    return result, summary


@pytest.mark.parametrize("origin,use_bullets", [("model", False), ("topic_recovery", True)])
def test_planned_summary_export_shows_all_five_selected_findings(origin, use_bullets):
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.services.pptx_export import _add_planned_summary

    narratives = [
        "The first result covers the disclosed population and retains its original scope.",
        "The second result concerns the measured annual periods only.",
        "The third result retains the reported category and does not combine incompatible units.",
        "The fourth result is limited to observations with direct source evidence.",
        "The fifth result is equally visible, including this qualification at the end.",
    ]
    result, summary = _planned_result(narratives, origin=origin, use_bullets=use_bullets)
    before = result.model_dump_json()
    deck = blank_deck()

    _add_planned_summary(deck, result, summary, DocumentIndex(result.observations))

    assert [body.text for body in _bodies(deck.slides)] == narratives
    assert len(deck.slides) == 1
    assert result.model_dump_json() == before
    _assert_readable_geometry(deck, deck.slides)


def test_planned_summary_preserves_similar_findings_with_different_signs_and_caveats():
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.services.pptx_export import _add_planned_summary

    narratives = [
        "Response changed by +5.0%; only the first cohort is included.",
        "Response changed by -5.0%; only the first cohort is included.",
        "Response changed by +5.0%; only the second cohort is included.",
        "Response changed by +0.5%; only the first cohort is included.",
        "Response changed by +5.0 days; only the first cohort is included.",
    ]
    result, summary = _planned_result(narratives)
    for insight in result.insights:
        insight.title = "Response comparison"
    deck = blank_deck()

    _add_planned_summary(deck, result, summary, DocumentIndex([]))

    assert [body.text for body in _bodies(deck.slides)] == narratives


@pytest.mark.parametrize("equivalent_case", [False, True])
def test_planned_summary_merges_repeated_copy_without_losing_either_source_page(equivalent_case):
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.services.pptx_export import _add_planned_summary

    text = "The finding applies only to the disclosed population."
    result, summary = _planned_result([text, text])
    result.insights[0].title = "Study finding"
    result.insights[1].title = "Study finding"
    result.insights[1].evidence[0].page = 7
    if equivalent_case:
        result.insights[1].title = "study finding"
        result.insights[1].narrative = text.upper().replace(" ", "  ")
    before = result.model_dump_json()
    deck = blank_deck()

    _add_planned_summary(deck, result, summary, DocumentIndex([]))

    assert len(_bodies(deck.slides)) == 1
    assert "p. 1, 7" in visible(deck.slides[0])
    assert "p. 1, 7" in deck.slides[0].notes_slide.notes_text_frame.text
    assert result.model_dump_json() == before
