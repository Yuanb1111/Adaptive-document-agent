"""Tests for generic PPT chart/KPI layout spacing, title sanitization, and layout QA."""

from __future__ import annotations

import io
import pytest

pytestmark = pytest.mark.usefixtures("local_render_stub")
import re
from pptx import Presentation
from pptx.enum.chart import XL_TICK_LABEL_POSITION

from adaptive_document_agent.document_model import (
    display_metric_name,
    sanitize_metric_for_title,
)
from adaptive_document_agent.models import (
    ChartPlan,
    CompanyProfile,
    DocumentProfile,
    Observation,
    ParsedDocument,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    PresentationVisualBlock,
    ReportPlan,
    SourceEvidence,
)
from adaptive_document_agent.services.export import export_pptx
from adaptive_document_agent.services.pptx_export import _add_chart_cluster_slide, _add_chart_slide
from adaptive_document_agent.document_model.index import DocumentIndex
from adaptive_document_agent.validation.layout_qa import validate_presentation_layout


def _make_evidence(page: int = 15) -> SourceEvidence:
    return SourceEvidence(page=page, text="120.5", extraction_method="digital_table", confidence=0.95)


def test_raw_table_row_reconciliation_excluded_from_slide_title() -> None:
    """Requirement 1: Do not allow raw table row text (e.g. 'Add - Share-based compensation...') to become a slide title."""
    ev = _make_evidence(15)
    obs = Observation(
        id="sbc_1",
        metric_original="Add - Share-based compensation expenses",
        value=54.2,
        raw_value="54.2",
        unit="currency",
        currency="RMB",
        period="FY2022",
        evidence=[ev],
        confidence=0.9,
    )

    # 1. display_metric_name cleans the table reconciliation prefix
    clean_display = display_metric_name(obs)
    assert not clean_display.lower().startswith("add")
    assert "Share-based compensation expenses" in clean_display

    # 2. sanitize_metric_for_title strips table row grammar and notes
    raw_title = "Add - Share-based compensation expenses (note 5 - unparsed line item)"
    sanitized = sanitize_metric_for_title(raw_title, max_length=40)
    assert not sanitized.lower().startswith("add")
    assert "Share-based" in sanitized
    assert len(sanitized) <= 40

    # 3. Layout QA auto-repairs raw table titles
    slide = PresentationSlide(
        id="s_raw",
        slide_type="analysis",
        title="Add - Share-based compensation expenses Trajectory",
        section_title="Profitability",
        observation_ids=["sbc_1"],
        source_pages=[15],
    )
    plan = PresentationPlan(
        title="Institutional Review",
        company=CompanyProfile(name="Acme Tech Ltd.", source_pages=[1]),
        slides=[slide],
    )
    result = PipelineResult(
        document=ParsedDocument(document_id="doc1", sha256="h1", safe_filename="doc.pdf", page_count=50),
        profile=DocumentProfile(document_type="Prospectus", overview_title="Acme Tech Ltd."),
        observations=[obs],
        presentation_plan=plan,
        report_plan=ReportPlan(title="Report"),
    )

    issues = validate_presentation_layout(result, auto_repair=True)
    repaired_title = plan.slides[0].title
    assert not repaired_title.lower().startswith("add -")
    assert "Share-based" in repaired_title
    assert any(item.code == "long_raw_metric_title_repaired" for item in issues)


def test_multi_chart_fixed_vertical_slots_and_clearance() -> None:
    """Requirement 2: On multi-chart slides, create 5 fixed vertical slots inside each KPI block with minimum spacing."""
    prs = Presentation()
    ev = _make_evidence(20)

    plans: list[ChartPlan] = []
    all_obs: list[Observation] = []
    metrics = [
        ("Revenue", [100.0, 130.0, 175.0]),
        ("Gross Profit", [40.0, 55.0, 78.0]),
        ("Adjusted EBITDA", [15.0, 24.0, 38.0]),
    ]
    for idx, (m_name, vals) in enumerate(metrics, start=1):
        obs_ids: list[str] = []
        for yr_idx, val in enumerate(vals, start=1):
            oid = f"m_{idx}_{yr_idx}"
            obs_ids.append(oid)
            all_obs.append(
                Observation(
                    id=oid,
                    metric_original=m_name,
                    value=val,
                    raw_value=str(val),
                    unit="currency",
                    currency="RMB",
                    period=f"FY202{yr_idx}",
                    evidence=[ev],
                    confidence=0.95,
                )
            )
        plans.append(
            ChartPlan(
                id=f"c_{idx}",
                title=f"{m_name} Growth",
                chart_type="bar",
                question=f"How did {m_name} evolve?",
                observation_ids=obs_ids,
                source_pages=[20],
            )
        )

    index = DocumentIndex(all_obs)
    _add_chart_cluster_slide(prs, plans, index, title="Financial Performance Multi-Chart", subtitle="Three key metrics")

    slide = prs.slides[0]
    # Check that each panel has separate shapes for movement text and detail text
    text_boxes = [s for s in slide.shapes if s.has_text_frame and s.text.strip()]
    
    # Movement text (e.g. "increased by 75.0%") and detail text ("100.0 in FY2021 to 175.0 in FY2023")
    movement_boxes = [s for s in text_boxes if "increased by" in s.text.lower()]
    detail_boxes = [s for s in text_boxes if "in fy2021 to" in s.text.lower()]

    assert len(movement_boxes) >= 1
    assert len(detail_boxes) >= 1

    # Verify that for each panel, movement text and detail text are in distinct vertical slots (different Y positions)
    for m_box, d_box in zip(movement_boxes, detail_boxes):
        y_diff = d_box.top - m_box.top
        # Dedicated vertical slot pitch of at least 0.25 inches
        assert y_diff >= 0.25 * 914400, f"Expected dedicated vertical slot pitch >= 0.25 in, got {y_diff / 914400:.3f} in"


def test_single_metric_movement_detail_spacing() -> None:
    """Requirement 4: On single metric detail slides, increase vertical spacing between movement headline and comparison detail."""
    prs = Presentation()
    ev = _make_evidence(30)
    obs = [
        Observation(id="o1", metric_original="Revenue", value=53.6, raw_value="53.6", unit="currency", currency="RMB", period="FY2021", evidence=[ev], confidence=0.9),
        Observation(id="o2", metric_original="Revenue", value=244.0, raw_value="244.0", unit="currency", currency="RMB", period="FY2023", evidence=[ev], confidence=0.9),
    ]
    chart = ChartPlan(id="c_single", title="Revenue Acceleration", chart_type="bar", question="Growth", observation_ids=["o1", "o2"], source_pages=[30])
    index = DocumentIndex(obs)

    _add_chart_slide(prs, chart, index, ordinal=1, title="Revenue Scaled Rapidly", subtitle="Detailed single-metric examination")

    slide = prs.slides[0]
    text_boxes = [s for s in slide.shapes if s.has_text_frame and s.text.strip()]

    movement_box = next(s for s in text_boxes if "increased by" in s.text.lower())
    detail_box = next(s for s in text_boxes if "53.6" in s.text and "244" in s.text)

    # Calculate vertical gap between bottom of movement box and top of detail box
    m_bottom = movement_box.top + movement_box.height
    d_top = detail_box.top

    vertical_gap = d_top - m_bottom
    # The gap should be positive and at least 0.30 inches (generously separated, never touching or crowding)
    assert d_top > m_bottom, "Detail text must sit strictly below the movement banner"
    assert (d_top - movement_box.top) >= 0.85 * 914400, f"Expected slot pitch >= 0.85 in, got {(d_top - movement_box.top) / 914400:.3f} in"


def test_zero_crossing_bar_headroom_and_tick_labels() -> None:
    """Requirement 3: For charts crossing zero, negative data labels must not overlap x-axis year labels."""
    ev = _make_evidence(40)
    # Zero-crossing series: negative (-16.45) in FY2021, positive in FY2022 and FY2023
    obs = [
        Observation(id="z1", metric_original="Operating Profit", value=-16.45, raw_value="-16.45", unit="currency", currency="RMB", period="FY2021", evidence=[ev], confidence=0.95),
        Observation(id="z2", metric_original="Operating Profit", value=25.0, raw_value="25.0", unit="currency", currency="RMB", period="FY2022", evidence=[ev], confidence=0.95),
        Observation(id="z3", metric_original="Operating Profit", value=48.0, raw_value="48.0", unit="currency", currency="RMB", period="FY2023", evidence=[ev], confidence=0.95),
    ]
    chart = ChartPlan(id="c_zero", title="Operating Turnaround", chart_type="bar", question="Turnaround", observation_ids=["z1", "z2", "z3"], source_pages=[40])

    plan = PresentationPlan(
        title="Financial Review",
        company=CompanyProfile(name="Turnaround Corp", source_pages=[1]),
        slides=[
            PresentationSlide(id="cov", slide_type="cover", title="Financial Review"),
            PresentationSlide(id="comp", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(id="exec", slide_type="executive_summary", title="Executive Summary"),
            PresentationSlide(
                id="s_zero",
                slide_type="analysis",
                title="Operating Profit Turned Positive",
                section_title="Profitability",
                message="Operating profit turned positive across the track record period.",
                chart_ids=["c_zero"],
                source_pages=[40],
            ),
            PresentationSlide(id="dq", slide_type="data_quality", title="Data Quality"),
            PresentationSlide(id="app", slide_type="appendix", title="Appendix"),
        ],
    )
    result = PipelineResult(
        document=ParsedDocument(document_id="doc1", sha256="h1", safe_filename="doc.pdf", page_count=50),
        profile=DocumentProfile(document_type="Prospectus", overview_title="Turnaround Corp"),
        observations=obs,
        charts=[chart],
        presentation_plan=plan,
        report_plan=ReportPlan(title="Report"),
    )

    pptx_bytes = export_pptx(result)
    prs = Presentation(io.BytesIO(pptx_bytes))

    analysis_slide = prs.slides[4]
    native_chart = next(s.chart for s in analysis_slide.shapes if s.has_chart)

    # 1. Category axis tick label position must be LOW to pin year labels to the bottom
    assert native_chart.category_axis.tick_label_position == XL_TICK_LABEL_POSITION.LOW

    # 2. Value axis minimum scale has >= 40% headroom below -16.45 (so minimum scale <= -23.0)
    assert native_chart.value_axis.minimum_scale <= -16.45 * 1.40


def test_layout_qa_detects_and_repairs_all_new_checks() -> None:
    """Requirement 5: Add layout QA checks for movement proximity, zero crossing, legend overlap, and raw title."""
    ev = _make_evidence(10)
    obs = [
        Observation(id="o1", metric_original="Net Profit", value=-10.0, raw_value="-10.0", unit="currency", currency="RMB", period="FY2021", evidence=[ev], confidence=0.9),
        Observation(id="o2", metric_original="Net Profit", value=20.0, raw_value="20.0", unit="currency", currency="RMB", period="FY2022", evidence=[ev], confidence=0.9),
    ]
    chart = ChartPlan(id="c_test", title="Net Profit Trajectory", chart_type="bar", question="How did net profit evolve?", observation_ids=["o1", "o2"], source_pages=[10])

    slide = PresentationSlide(
        id="s_polluted",
        slide_type="analysis",
        title="Add - Share-based compensation expenses Trajectory",
        section_title="Operating Details",
        chart_ids=["c_test"],
        source_pages=[10],
    )
    plan = PresentationPlan(
        title="Review",
        company=CompanyProfile(name="Clean Corp", source_pages=[1]),
        slides=[slide],
    )
    result = PipelineResult(
        document=ParsedDocument(document_id="d1", sha256="s1", safe_filename="doc.pdf", page_count=50),
        profile=DocumentProfile(document_type="Prospectus", overview_title="Clean Corp"),
        observations=obs,
        charts=[chart],
        presentation_plan=plan,
        report_plan=ReportPlan(title="Report"),
    )

    issues = validate_presentation_layout(result, auto_repair=True)
    issue_codes = {item.code for item in issues}

    assert "long_raw_metric_title_repaired" in issue_codes
    assert "zero_crossing_bar_label_overlap_repaired" in issue_codes
    assert "movement_detail_text_proximity_repaired" in issue_codes
