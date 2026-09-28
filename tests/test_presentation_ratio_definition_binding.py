"""A source ratio footnote may not rewrite another metric or numerator."""

from adaptive_document_agent.models import (
    ChartPlan, DocumentPage, Observation, PresentationPlan, PresentationSlide, SourceEvidence,
)
from adaptive_document_agent.services.presentation_ratio_definitions import (
    prepare_presentation_ratio_definitions, ratio_definitions,
)
from tests.test_pptx_export import _result


def _ratio_result(title):
    result = _result()
    result.document.pages = [DocumentPage(page_number=1, text=(
        "Expense ratio (1) 25.0 30.0\n"
        "(1) Calculated by dividing operating expenses by total expenses."
    ))]
    result.observations = [Observation(
        id="ratio", metric_original="Expense ratio", value=25, raw_value="25", unit="percent",
        period="FY2024", table_id="ratio-table", confidence=.9,
        evidence=[SourceEvidence(page=1, table_id="ratio-table", row_label="Expense ratio", text="25",
                                 extraction_method="digital_table", confidence=.9)],
    )]
    result.charts = [ChartPlan(id="ratio-chart", title="Expense ratio", chart_type="bar",
                               question="What changed?", observation_ids=["ratio"])]
    result.presentation_plan = PresentationPlan(title="Review", slides=[
        PresentationSlide(id="ratio-slide", slide_type="analysis", title=title, chart_ids=["ratio-chart"])
    ])
    return result


def test_ratio_definition_never_changes_another_ratios_denominator():
    result = _ratio_result("Expense ratio to revenue decreased; debt ratio to assets increased.")
    prepare_presentation_ratio_definitions(result)
    assert "debt ratio to assets increased" in result.presentation_plan.slides[0].title
    assert "debt ratio to total expenses" not in result.presentation_plan.slides[0].title


def test_ratio_of_numerator_to_denominator_keeps_the_numerator():
    result = _ratio_result("Ratio of operating expenses to revenue decreased.")
    prepare_presentation_ratio_definitions(result)
    assert "operating expenses" in result.presentation_plan.slides[0].title
    assert result.presentation_plan.slides[0].title != "Ratio of total expenses decreased."


def test_reused_footnote_marker_after_a_different_row_cannot_be_borrowed():
    result = _ratio_result("Expense ratio to revenue decreased.")
    result.document.pages[0].text = (
        "Expense ratio (1) 25.0 30.0\n\nUNRELATED TABLE\n"
        "Liquidity ratio (1) 80.0 90.0\n"
        "(1) Calculated by dividing current assets by current liabilities."
    )
    assert ratio_definitions(result) == []
