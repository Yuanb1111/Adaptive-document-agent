"""Synthetic reproductions for reported v78 review symptoms; no private data."""

from adaptive_document_agent.models import (
    ChartPlan, DocumentPage, DocumentProfile, ExtractedTable, Observation, ParsedDocument,
    PipelineResult, PresentationPlan, PresentationSlide, SourceEvidence, TableRow,
)
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from adaptive_document_agent.services.presentation_scope import scope_items
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator


def _percentage_result() -> PipelineResult:
    source = "Product mix 6M2025: Core 50.5; Others 43.5. RMB in thousands"
    table = ExtractedTable(
        table_id="mix", page=1, headers=["Product", "Share"], column_types=["unknown", "percentage"],
        rows=[TableRow(cells=["Core", "50.5"], page=1), TableRow(cells=["Other", "43.5"], page=1)],
    )
    observations = [
        Observation(id=f"share-{row}", metric_original="Product share", raw_value=value, value=float(value),
                    period="6M2025", unit="percent", unit_family="percentage", confidence=.99,
                    table_id="mix", row_id=row, column_id=1,
                    evidence=[SourceEvidence(page=1, text=value, table_id="mix",
                                             row_label=("Core", "Others")[row], column_label="Share",
                                             extraction_method="synthetic", confidence=.99)])
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
        "evidence": [{"page": 1, "text": "Product mix 6M2025: Core 50.5; Others 43.5. RMB in thousands"}],
    }]})
    assert validate_executive_brief(brief, result) == []


def test_compact_unsupported_amount_is_not_mistaken_for_period_marker() -> None:
    result = PipelineResult(
        document=ParsedDocument(document_id="amount", sha256="b" * 64, safe_filename="synthetic.pdf",
                                page_count=1, pages=[DocumentPage(
                                    page_number=1, text="Revenue was USD 4.6 billion in 2025.")]),
        profile=DocumentProfile(),
    )
    brief = ExecutiveBrief.model_validate({"title": "Findings", "items": [{
        "label": "Revenue", "text": "Revenue was USD99M.",
        "evidence": [{"page": 1, "text": "Revenue was USD 4.6 billion in 2025."}],
    }]})
    errors = validate_executive_brief(brief, result)
    assert any("unsupported numeric claims" in error for error in errors)
    assert any("currency or magnitude" in error for error in errors)


def test_compact_decimal_amount_cannot_change_magnitude() -> None:
    result = PipelineResult(
        document=ParsedDocument(document_id="amount", sha256="b" * 64, safe_filename="synthetic.pdf",
                                page_count=1, pages=[DocumentPage(page_number=1, text="Revenue was RMB43.5m.")]),
        profile=DocumentProfile(),
    )
    brief = ExecutiveBrief.model_validate({"title": "Findings", "items": [{
        "label": "Revenue", "text": "Revenue was RMB43.5b.",
        "evidence": [{"page": 1, "text": "Revenue was RMB43.5m."}],
    }]})
    errors = validate_executive_brief(brief, result)
    assert not any("unsupported numeric claims" in error for error in errors)
    assert any("currency or magnitude" in error for error in errors)


def test_period_markers_and_compact_amounts_are_distinguished() -> None:
    numbers = PresentationPlanValidator._numbers
    assert numbers("6M") == set()
    assert numbers("9M period") == set()
    assert numbers("6M2025") == {"2025"}
    assert numbers("USD99M") == {"99"}
    assert numbers("RMB43.5m") == {"43.5"}


def test_real_unsupported_number_and_changed_unit_still_fail() -> None:
    result = _percentage_result()
    brief = ExecutiveBrief.model_validate({"title": "Findings", "items": [{
        "label": "Product mix", "text": "Product share was 61.0% and revenue was USD 43.5 million.",
        "evidence": [{"page": 1, "text": "Product mix 6M2025: Core 50.5; Others 43.5. RMB in thousands"}],
    }]})
    errors = validate_executive_brief(brief, result)
    assert any("unsupported numeric claims" in error for error in errors)
    assert any("currency or magnitude" in error for error in errors)


def test_unit_header_is_repaired_as_label_not_accepted_as_metric() -> None:
    result = _percentage_result()
    brief = ExecutiveBrief.model_validate({"title": "Findings", "items": [{
        "label": "RMB in thousands", "text": "Product mix was 50.5%.",
        "evidence": [{"page": 1, "text": "Product mix 6M2025: Core 50.5; Others 43.5. RMB in thousands"}],
    }]})
    assert any("unit header" in error for error in validate_executive_brief(brief, result))


def test_stale_absence_note_is_removed_only_when_exact_category_is_retained() -> None:
    result = _percentage_result()
    result.observations[1].category_dimensions = {"product": "Others"}
    result.charts = [ChartPlan(id="mix-chart", title="Product mix", question="Composition", chart_type="bar",
                               observation_ids=["share-0", "share-1"])]
    result.presentation_plan = PresentationPlan(title="Review", coverage_notes=[
        "The Others category is not shown.",
        "Supplier-level detail is not shown.",
    ], slides=[PresentationSlide(id="mix", slide_type="analysis", title="Product mix",
                                 chart_ids=["mix-chart"])])
    text = [item.text for item in scope_items(result)]
    assert "The Others category is not shown." not in text
    assert "Supplier-level detail is not shown." in text


def test_absence_note_remains_when_category_was_not_retained() -> None:
    result = _percentage_result()
    result.observations[1].category_dimensions = {"product": "Others"}
    result.presentation_plan = PresentationPlan(title="Review", coverage_notes=[
        "The Others category is not shown in detail.",
    ], slides=[PresentationSlide(id="other", slide_type="analysis", title="Another topic",
                                 observation_ids=["share-0"])])
    assert any("Others" in item.text for item in scope_items(result))


def test_same_page_equal_value_cannot_borrow_another_metrics_percentage_cell() -> None:
    result = _percentage_result()
    result.document.pages[0].text = "Revenue 50.5. Gross margin 50.5."
    result.document.pages[0].tables = [ExtractedTable(
        table_id="mixed", page=1, headers=["Metric", "Amount", "Percentage"],
        column_types=["unknown", "amount", "percentage"],
        rows=[TableRow(cells=["Revenue", "50.5", None], page=1),
              TableRow(cells=["Gross margin", None, "50.5"], page=1)],
    )]
    result.observations = [Observation(
        id="margin", metric_original="Gross margin", raw_value="50.5", value=50.5,
        unit="percent", unit_family="percentage", confidence=.99,
        table_id="mixed", row_id=1, column_id=2,
        evidence=[SourceEvidence(page=1, text="50.5", table_id="mixed", row_label="Gross margin",
                                 column_label="Percentage", extraction_method="synthetic", confidence=.99)],
    )]
    brief = ExecutiveBrief.model_validate({"title": "Findings", "items": [{
        "label": "Revenue", "text": "Revenue was 50.5%.",
        "evidence": [{"page": 1, "text": "Revenue 50.5"}],
    }]})
    assert any("unsupported numeric claims" in error for error in validate_executive_brief(brief, result))


def test_mixed_columns_bind_percentage_only_to_quoted_row_and_cell() -> None:
    result = _percentage_result()
    result.document.pages[0].text = "Revenue 50.5. Gross margin 50.5."
    result.document.pages[0].tables = [ExtractedTable(
        table_id="mixed", page=1, headers=["Metric", "Amount", "Percentage"],
        column_types=["unknown", "amount", "percentage"],
        rows=[TableRow(cells=["Revenue", "50.5", None], page=1),
              TableRow(cells=["Gross margin", None, "50.5"], page=1)],
    )]
    result.observations = [Observation(
        id="margin", metric_original="Gross margin", raw_value="50.5", value=50.5,
        unit="percent", unit_family="percentage", confidence=.99,
        table_id="mixed", row_id=1, column_id=2,
        evidence=[SourceEvidence(page=1, text="50.5", table_id="mixed", row_label="Gross margin",
                                 column_label="Percentage", extraction_method="synthetic", confidence=.99)],
    )]
    brief = ExecutiveBrief.model_validate({"title": "Findings", "items": [{
        "label": "Gross margin", "text": "Gross margin was 50.5%.",
        "evidence": [{"page": 1, "text": "Gross margin 50.5"}],
    }]})
    assert validate_executive_brief(brief, result) == []


def test_retained_total_does_not_erase_detail_or_supplier_limitations() -> None:
    result = _percentage_result()
    result.observations[1].category_dimensions = {"product": "Others"}
    result.charts = [ChartPlan(id="mix-chart", title="Product mix", question="Composition", chart_type="bar",
                               observation_ids=["share-1"])]
    result.presentation_plan = PresentationPlan(title="Review", coverage_notes=[
        "Supplier-level breakdown of Others is not shown.",
        "Others is shown; supplier-level detail is not shown.",
        "The Others category is not shown for FY2024.",
    ], slides=[PresentationSlide(id="mix", slide_type="analysis", title="Product mix",
                                 chart_ids=["mix-chart"])])
    text = [item.text for item in scope_items(result)]
    assert "Supplier-level breakdown of Others is not shown." in text
    assert "Others is shown; supplier-level detail is not shown." in text
    assert "The Others category is not shown for FY2024." in text
