from __future__ import annotations

import io
from pptx import Presentation
import pytest

from adaptive_document_agent.models import (
    ChartPlan,
    CompanyFact,
    CompanyProfile,
    DocumentProfile,
    Observation,
    ParsedDocument,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    SourceEvidence,
)
from adaptive_document_agent.services.export import export_pptx
from adaptive_document_agent.services.presentation_layout_qa import PresentationLayoutQA
from adaptive_document_agent.services.pptx_export import (
    _add_planned_contents,
    _add_planned_data_slide,
    _base_slide,
)


def _sample_doc() -> ParsedDocument:
    return ParsedDocument(
        document_id="test-doc",
        sha256="0" * 64,
        safe_filename="test.pdf",
        page_count=20,
        text_by_page={1: "Annual Report 2024"},
    )


def test_multi_period_renders_comparison_table_not_8_cards() -> None:
    """Requirement 7: Multi-period series should render a structured table instead of 8 repeated KPI cards."""
    prs = Presentation()
    prs.slide_width = Presentation().slide_width  # standard widescreen
    ev = SourceEvidence(page=10, text="12.5%", extraction_method="digital_table", confidence=0.95)

    # Multi-period observation series (e.g. 3 years for 2 metrics)
    obs = [
        Observation(id="rd_22", metric_original="R&D / Revenue", value=12.0, raw_value="12.0%", period="FY2022", unit="percent", evidence=[ev], confidence=0.9),
        Observation(id="rd_23", metric_original="R&D / Revenue", value=13.5, raw_value="13.5%", period="FY2023", unit="percent", evidence=[ev], confidence=0.9),
        Observation(id="rd_24", metric_original="R&D / Revenue", value=14.2, raw_value="14.2%", period="FY2024", unit="percent", evidence=[ev], confidence=0.9),
        Observation(id="sm_22", metric_original="Selling & Distribution / Revenue", value=20.0, raw_value="20.0%", period="FY2022", unit="percent", evidence=[ev], confidence=0.9),
        Observation(id="sm_23", metric_original="Selling & Distribution / Revenue", value=22.0, raw_value="22.0%", period="FY2023", unit="percent", evidence=[ev], confidence=0.9),
        Observation(id="sm_24", metric_original="Selling & Distribution / Revenue", value=23.1, raw_value="23.1%", period="FY2024", unit="percent", evidence=[ev], confidence=0.9),
    ]

    slide_plan = PresentationSlide(
        id="data_slide",
        slide_type="analysis",
        title="Expense Ratios Overview",
        message="Stable operating cost efficiency across three fiscal years.",
        observation_ids=[o.id for o in obs],
    )

    _add_planned_data_slide(prs, slide_plan, obs)

    slide = prs.slides[0]
    # Check that a table was created on the slide
    tables = [s.table for s in slide.shapes if s.has_table]
    assert len(tables) == 1, "Expected a comparison table instead of KPI cards"
    tbl = tables[0]
    assert len(tbl.columns) == 4  # Metric, FY2022, FY2023, FY2024
    assert tbl.cell(0, 0).text == "Metric"


def test_contents_page_only_lists_actual_sections() -> None:
    """Requirement 9: Contents page should only list sections that actually exist, never phantom ones."""
    prs = Presentation()
    # Plan with only cover, executive_summary, and analysis (no company_overview, no appendix)
    slides = [
        PresentationSlide(id="cov", slide_type="cover", title="Cover"),
        PresentationSlide(id="exec", slide_type="executive_summary", title="Executive Summary"),
        PresentationSlide(id="ana1", slide_type="analysis", title="Revenue Growth", section_title="Financial Performance"),
    ]

    _add_planned_contents(prs, slides)
    slide = prs.slides[0]
    text = " ".join(s.text for s in slide.shapes if s.has_text_frame)

    assert "Financial Performance" in text
    assert "Executive Summary" in text
    assert "Company Overview" not in text  # No phantom company overview
    assert "Appendix" not in text          # No phantom appendix


def test_presentation_layout_qa_detects_issues() -> None:
    """Requirement 6: Presentation layout QA should detect mechanical ellipsis and tiny fonts."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    txBox = slide.shapes.add_textbox(0, 0, 1000000, 1000000)
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = "Research and development expenses: share of revenue..."

    qa = PresentationLayoutQA(prs)
    issues = qa.validate()

    assert any(i.issue_type == "mechanical_ellipsis" for i in issues)


def test_appendix_deduplicates_period_columns() -> None:
    """Requirement 8: Appendix must deduplicate period columns and never produce FY2022 | FY2022."""
    from adaptive_document_agent.services.pptx_export import _add_evidence_table_slides

    ev = SourceEvidence(page=50, text="100", extraction_method="digital_table", confidence=0.95)
    # Observations where periods differ in raw format but represent the same period
    obs = [
        Observation(id="o1", metric_original="Revenue", value=100.0, raw_value="100", period="FY2022", currency="RMB", unit="currency", evidence=[ev], confidence=0.9),
        Observation(id="o2", metric_original="Revenue", value=100.0, raw_value="100", period="2022", currency="RMB", unit="currency", evidence=[ev], confidence=0.9),
        Observation(id="o3", metric_original="Revenue", value=150.0, raw_value="150", period="FY2023", currency="RMB", unit="currency", evidence=[ev], confidence=0.9),
    ]

    c1 = ChartPlan(id="c1", title="Revenue", question="What was revenue?", chart_type="bar", observation_ids=["o1", "o2", "o3"], source_pages=[50])
    result = PipelineResult(
        document=_sample_doc(),
        profile=DocumentProfile(overview_title="Alpha Corp"),
        observations=obs,
        charts=[c1],
    )

    prs = Presentation()
    _add_evidence_table_slides(prs, result, [c1], title="Appendix")

    app_slide = prs.slides[0]
    table = next(s.table for s in app_slide.shapes if s.has_table)
    headers = [table.cell(0, col).text for col in range(len(table.columns))]

    # Header columns should contain unique FY2022 without duplication
    assert headers.count("FY2022") == 1
    assert "FY2023" in headers
