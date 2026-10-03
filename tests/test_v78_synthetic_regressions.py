"""Synthetic reproductions for reported v78 review symptoms; no private data."""

from adaptive_document_agent.models import (
    ChartPlan, DocumentPage, DocumentProfile, ExtractedTable, Observation, ParsedDocument,
    PipelineResult, PresentationPlan, PresentationSlide, SourceEvidence, TableRow,
)
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from adaptive_document_agent.services.presentation_scope import scope_items


def _percentage_result() -> PipelineResult:
    source = "Product mix 6M2025 50.5 43.5 RMB in thousands"
    table = ExtractedTable(
        table_id="mix", page=1, headers=["Product", "Share"], column_types=["unknown", "percentage"],
        rows=[TableRow(cells=["Core", "50.5"], page=1), TableRow(cells=["Other", "43.5"], page=1)],
    )
    observations = [
        Observation(id=f"share-{row}", metric_original="Product share", raw_value=value, value=float(value),
                    period="6M2025", unit="percent", unit_family="percentage", confidence=.99,
                    table_id="mix", row_id=row, column_id=1,
                    evidence=[SourceEvidence(page=1, text=value, table_id="mix", extraction_method="synthetic",
                                             confidence=.99)])
        for row, value in enumerate(("50.5", "43.5"))
    ]
    return PipelineResult(
        document=ParsedDocument(document_id="synthetic", sha256="a" * 64, safe_filename="synthetic.pdf",
                                page_count=1, pages=[DocumentPage(page_number=1, text=source, tables=[table])]),
        profile=DocumentProfile(), observations=observations,
    )


def test_table_percentage_context_and_6m_period_are_supported() -> None:
    result = _percentage_result()
    brief = ExecutiveBrief.model_validate({"title": "Findings", "items": [{
        "label": "Product mix", "text": "Product shares were 50.5% and 43.5% in the 6M period.",
        "evidence": [{"page": 1, "text": "Product mix 6M2025 50.5 43.5 RMB in thousands"}],
    }]})
    assert validate_executive_brief(brief, result) == []


def test_real_unsupported_number_and_changed_unit_still_fail() -> None:
    result = _percentage_result()
    brief = ExecutiveBrief.model_validate({"title": "Findings", "items": [{
        "label": "Product mix", "text": "Product share was 61.0% and revenue was USD 43.5 million.",
        "evidence": [{"page": 1, "text": "Product mix 6M2025 50.5 43.5 RMB in thousands"}],
    }]})
    errors = validate_executive_brief(brief, result)
    assert any("unsupported numeric claims" in error for error in errors)
    assert any("currency or magnitude" in error for error in errors)


def test_unit_header_is_repaired_as_label_not_accepted_as_metric() -> None:
    result = _percentage_result()
    brief = ExecutiveBrief.model_validate({"title": "Findings", "items": [{
        "label": "RMB in thousands", "text": "Product mix was 50.5%.",
        "evidence": [{"page": 1, "text": "Product mix 6M2025 50.5 43.5 RMB in thousands"}],
    }]})
    assert any("unit header" in error for error in validate_executive_brief(brief, result))


def test_stale_absence_note_is_removed_only_when_exact_category_is_retained() -> None:
    result = _percentage_result()
    result.observations[1].category_dimensions = {"product": "Others"}
    result.charts = [ChartPlan(id="mix-chart", title="Product mix", question="Composition", chart_type="bar",
                               observation_ids=["share-0", "share-1"])]
    result.presentation_plan = PresentationPlan(title="Review", coverage_notes=[
        "The Others category is not shown in detail.",
        "Supplier-level detail is not shown.",
    ], slides=[PresentationSlide(id="mix", slide_type="analysis", title="Product mix",
                                 chart_ids=["mix-chart"])])
    text = [item.text for item in scope_items(result)]
    assert "The Others category is not shown in detail." not in text
    assert "Supplier-level detail is not shown." in text


def test_absence_note_remains_when_category_was_not_retained() -> None:
    result = _percentage_result()
    result.observations[1].category_dimensions = {"product": "Others"}
    result.presentation_plan = PresentationPlan(title="Review", coverage_notes=[
        "The Others category is not shown in detail.",
    ], slides=[PresentationSlide(id="other", slide_type="analysis", title="Another topic",
                                 observation_ids=["share-0"])])
    assert any("Others" in item.text for item in scope_items(result))
