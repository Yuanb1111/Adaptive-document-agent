"""Ratio denominator binding is source structural, not document specific."""

import copy

from adaptive_document_agent.models import DocumentPage, PresentationPlan, PresentationSlide, PresentationTheme
from adaptive_document_agent.services.presentation_ratio_definitions import (
    prepare_presentation_ratio_definitions, ratio_definitions,
)
from tests.test_presentation_claim_evidence import _observation
from tests.test_pptx_export import _result


def _sample():
    result = _result()
    ratio = [_observation("Service utilisation ratio", y, v) for y, v in ((2022, 34.3), (2023, 28.1))]
    result.observations = ratio + [_observation("Available hours", 2022, 100, share=False)]
    result.document.pages = [DocumentPage(page_number=2, text=(
        "(1) A different note before this table.\nService utilisation\nratio(1) 34.3% 28.1%\n"
        "Total utilisation ratio(2) 29.3%\n"
        "(1) Calculated by dividing occupied hours by total scheduled hours.\n"
        "(2) Calculated by dividing occupied rooms by total rooms."))]
    result.charts = []
    title = "Service utilisation ratio to available hours declined."
    result.presentation_plan = PresentationPlan(title="Capacity", themes=[PresentationTheme(
        id="use", title="Utilisation", question="What changed?", rationale="Model choice",
        caveats=["The ratio is presented as a percentage of available hours and is not a share of scheduled hours."])],
        slides=[PresentationSlide(id="summary", slide_type="executive_summary", title="Findings", bullets=[title]),
                PresentationSlide(id="use", slide_type="analysis", theme_id="use", title=title,
                                  message="How did available hours intensity change?",
                                  observation_ids=[o.id for o in ratio])])
    return result


def test_explicit_ratio_footnote_binds_wrapped_row_and_ignores_other_notes():
    definitions = ratio_definitions(_sample())
    assert len(definitions) == 1
    assert definitions[0]["numerator"] == "occupied hours"
    assert definitions[0]["denominator"] == "total scheduled hours"
    assert definitions[0]["page"] == 2
    assert len(definitions[0]["observation_ids"]) == 2


def test_correction_preserves_raw_and_original_copy_with_literal_source_audit():
    result = _sample()
    raw = copy.deepcopy(result.observations)
    prepare_presentation_ratio_definitions(result)
    plan = result.presentation_plan
    assert plan.slides[-1].title == "Service utilisation ratio to total scheduled hours declined."
    assert plan.slides[0].bullets == [plan.slides[-1].title]
    assert "Ratio denominator: total scheduled hours" in plan.slides[-1].message
    assert "not a share" not in plan.themes[0].caveats[0]
    audit = next(w for w in result.validation_warnings if w.code == "presentation_ratio_definition")
    assert "available hours declined" in audit.message
    assert audit.evidence[0].text.startswith("(1) Calculated by dividing occupied hours")
    assert result.observations == raw
    snapshot = result.model_dump()
    prepare_presentation_ratio_definitions(result)
    assert result.model_dump() == snapshot


def test_no_footnote_or_ambiguous_marker_does_not_infer_denominator():
    for suffix in ("", "\n(1) Calculated by dividing occupied hours by available hours."):
        result = _sample()
        if not suffix:
            result.document.pages[0].text = "Service utilisation ratio 34.3% 28.1%"
        else:
            result.document.pages[0].text += suffix
        assert ratio_definitions(result) == []
        original = result.model_dump()
        assert prepare_presentation_ratio_definitions(result) == []
        assert result.model_dump() == original


def test_unrelated_page_definition_cannot_bind_to_selected_ratio():
    result = _sample()
    result.document.pages[0].page_number = 3
    assert ratio_definitions(result) == []


def test_existing_topic_request_receives_source_definition():
    from adaptive_document_agent.agent.presentation_topic_selector import series_directory
    directory, _ = series_directory(_sample())
    ratio_rows = [row for row in directory if row["ratio_definitions"]]
    assert ratio_rows
    assert ratio_rows[0]["ratio_definitions"][0]["denominator"] == "total scheduled hours"


def test_second_unbound_ratio_cannot_borrow_the_first_ratio_definition():
    result = _sample()
    unrelated = _observation("Other ratio", 2023, 42)
    result.observations.append(unrelated)
    result.presentation_plan.slides[-1].observation_ids.append(unrelated.id)
    original = result.model_dump()
    assert prepare_presentation_ratio_definitions(result) == []
    assert result.model_dump() == original


def test_other_named_subject_and_modal_or_negated_suffix_are_not_rewritten():
    from adaptive_document_agent.services.presentation_ratio_definitions import _rewrite
    definition = ratio_definitions(_sample())[0]
    for text in (
        "Debt ratio to available hours increased.",
        "Service utilisation ratio to available hours did not decrease.",
        "Service utilisation ratio to available hours may increase.",
    ):
        assert _rewrite(text, definition, {"Available hours"}) == text


def test_generic_source_initialism_and_its_subject_bind_without_metric_alias_list():
    from adaptive_document_agent.services.presentation_ratio_definitions import _rewrite
    definition = {"metric": "Annual alpha and beta utilisation ratio",
                  "numerator": "annual alpha and beta utilisation", "denominator": "scheduled capacity", "page": 2}
    assert _rewrite("A&B utilisation rose while its ratio to available capacity declined.",
                    definition, {"Available capacity"}) == (
        "A&B utilisation rose while its ratio to scheduled capacity declined.")
    assert _rewrite("The A&B ratio is presented as a percentage of available capacity and not of scheduled capacity.",
                    definition, {"Available capacity"}) == "Ratio denominator: scheduled capacity (see source pages)."
