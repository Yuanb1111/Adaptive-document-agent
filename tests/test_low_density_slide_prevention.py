"""Tests for low-density analysis slide prevention, neighbouring merge, and layout QA."""

from __future__ import annotations

import pytest

from adaptive_document_agent.agent.presentation_plan_repairer import PresentationPlanRepairer
from adaptive_document_agent.document_model import DocumentModelBuilder
from adaptive_document_agent.models import (
    ChartPlan,
    DocumentPage,
    DocumentProfile,
    Insight,
    Observation,
    ParsedDocument,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    ReportPlan,
    SourceEvidence,
)
from adaptive_document_agent.validation.layout_qa import validate_presentation_layout
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator


def _build_test_result() -> PipelineResult:
    obs = [
        Observation(
            id="rev_2023",
            metric_original="Revenue",
            value=100_000.0,
            raw_value="100,000",
            unit="currency",
            currency="USD",
            period="2023",
            confidence=0.9,
            evidence=[SourceEvidence(page=1, text="Revenue 2023 = 100,000", extraction_method="digital_text", confidence=0.9)],
        ),
        Observation(
            id="rev_2024",
            metric_original="Revenue",
            value=150_000.0,
            raw_value="150,000",
            unit="currency",
            currency="USD",
            period="2024",
            confidence=0.9,
            evidence=[SourceEvidence(page=1, text="Revenue 2024 = 150,000", extraction_method="digital_text", confidence=0.9)],
        ),
        Observation(
            id="gp_2023",
            metric_original="Gross profit",
            value=40_000.0,
            raw_value="40,000",
            unit="currency",
            currency="USD",
            period="2023",
            confidence=0.9,
            evidence=[SourceEvidence(page=1, text="Gross profit 2023 = 40,000", extraction_method="digital_text", confidence=0.9)],
        ),
        Observation(
            id="gp_2024",
            metric_original="Gross profit",
            value=70_000.0,
            raw_value="70,000",
            unit="currency",
            currency="USD",
            period="2024",
            confidence=0.9,
            evidence=[SourceEvidence(page=1, text="Gross profit 2024 = 70,000", extraction_method="digital_text", confidence=0.9)],
        ),
    ]

    chart = ChartPlan(
        id="chart_rev",
        title="Revenue Trajectory",
        chart_type="line",
        question="How did revenue grow?",
        observation_ids=["rev_2023", "rev_2024"],
        source_pages=[1],
        x_metric="Revenue",
    )

    insights = [
        Insight(
            id="ins_rev",
            title="Revenue Scaled Rapidly",
            narrative="Revenue expanded from 100k to 150k.",
            kind="reported_fact",
            metric="Revenue",
            evidence=[SourceEvidence(page=1, text="Revenue expanded", extraction_method="digital_text", confidence=0.9)],
        ),
        Insight(
            id="ins_margin",
            title="Gross Margin Expanded",
            narrative="Product margin expanded due to economies of scale.",
            kind="reported_fact",
            metric="Gross profit",
            evidence=[SourceEvidence(page=1, text="Margin expanded", extraction_method="digital_text", confidence=0.9)],
        ),
        Insight(
            id="ins_isolated",
            title="Regulatory Headwinds",
            narrative="Company navigated shifting regulatory frameworks.",
            kind="interpretation",
            evidence=[SourceEvidence(page=1, text="Regulatory frameworks", extraction_method="digital_text", confidence=0.8)],
        ),
    ]

    doc = ParsedDocument(
        document_id="doc_density",
        sha256="sha_density",
        safe_filename="annual_report.pdf",
        page_count=2,
        pages=[DocumentPage(page_number=1, text="Financial Information", tables=[])],
    )

    return PipelineResult(
        document=doc,
        profile=DocumentProfile(overview_title="Acme Corp"),
        observations=obs,
        charts=[chart],
        insights=insights,
        report_plan=ReportPlan(title="Acme Corp Annual Review"),
    )


def test_validator_rejects_insight_only_analysis_slide() -> None:
    """Requirement: An insight_id alone cannot justify an analysis slide."""
    result = _build_test_result()
    plan = PresentationPlan(
        title="Test Deck",
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Review"),
            PresentationSlide(id="overview", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(id="summary", slide_type="executive_summary", title="Executive Summary"),
            PresentationSlide(
                id="empty_margin_slide",
                slide_type="analysis",
                title="Product Margin Expanded",
                section_title="Profitability",
                message="Product margin expanded across periods.",
                insight_ids=["ins_margin"],  # Only insight, no chart, table, or observations
                source_pages=[1],
            ),
            PresentationSlide(id="quality", slide_type="data_quality", title="Data Quality"),
            PresentationSlide(id="appendix", slide_type="appendix", title="Appendix"),
        ],
    )

    with pytest.raises(ValueError, match="insufficient data density"):
        PresentationPlanValidator().validate(plan, result)


def test_repairer_merges_insight_into_neighbouring_analysis_slide() -> None:
    """Requirement: If an insight lacks visual data, merge into the most relevant neighbouring analysis slide."""
    result = _build_test_result()
    plan = PresentationPlan(
        title="Test Deck",
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Review"),
            PresentationSlide(id="overview", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(id="summary", slide_type="executive_summary", title="Executive Summary"),
            PresentationSlide(
                id="slide_revenue",
                slide_type="analysis",
                title="Revenue Trajectory",
                section_id="fin_perf",
                section_title="Financial Performance",
                message="Revenue expanded rapidly across periods.",
                chart_ids=["chart_rev"],
                source_pages=[1],
            ),
            PresentationSlide(
                id="slide_isolated_note",
                slide_type="analysis",
                title="Regulatory Environment",
                section_id="fin_perf",
                section_title="Financial Performance",
                message="Navigated shifting regulatory frameworks.",
                insight_ids=["ins_isolated"],  # No observations exist for this topic
                source_pages=[1],
            ),
            PresentationSlide(id="quality", slide_type="data_quality", title="Data Quality"),
            PresentationSlide(id="appendix", slide_type="appendix", title="Appendix"),
        ],
    )

    repaired = PresentationPlanRepairer().repair(plan, result)
    # Validate repaired plan
    assert PresentationPlanValidator().validate(repaired, result) is repaired

    # slide_isolated_note should have been merged into slide_revenue
    analysis_slides = [s for s in repaired.slides if s.slide_type == "analysis"]
    assert len(analysis_slides) == 1
    target = analysis_slides[0]
    assert target.id == "slide_revenue"
    assert "ins_isolated" in target.insight_ids
    assert any("regulatory" in b.casefold() for b in target.bullets)


def test_repairer_generates_table_when_matching_observations_exist() -> None:
    """Requirement: Generate a small evidence table if sufficient structured observations exist."""
    result = _build_test_result()
    plan = PresentationPlan(
        title="Test Deck",
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Review"),
            PresentationSlide(id="overview", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(id="summary", slide_type="executive_summary", title="Executive Summary"),
            PresentationSlide(
                id="slide_gp",
                slide_type="analysis",
                title="Gross Profit Growth",
                section_id="sec_gp",
                section_title="Gross Profit",
                message="Gross profit increased from 40k to 70k.",
                insight_ids=["ins_margin"],  # ins_margin has metric="Gross profit", observations exist!
                source_pages=[1],
            ),
            PresentationSlide(id="quality", slide_type="data_quality", title="Data Quality"),
            PresentationSlide(id="appendix", slide_type="appendix", title="Appendix"),
        ],
    )

    repaired = PresentationPlanRepairer().repair(plan, result)
    assert PresentationPlanValidator().validate(repaired, result) is repaired

    analysis_slides = [s for s in repaired.slides if s.slide_type == "analysis"]
    assert len(analysis_slides) >= 1
    gp_slide = next(s for s in analysis_slides if s.id == "slide_gp")
    # Must now contain at least 2 observations and table layout
    assert len(gp_slide.observation_ids) >= 2
    assert "gp_2023" in gp_slide.observation_ids
    assert "gp_2024" in gp_slide.observation_ids
    assert gp_slide.layout == "data_overview"


def test_layout_qa_flags_and_repairs_low_density_analysis_slide() -> None:
    """Requirement: QA check flags and auto-repairs low-density analysis slides."""
    result = _build_test_result()
    plan = PresentationPlan(
        title="Test Deck",
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Review"),
            PresentationSlide(id="overview", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(id="summary", slide_type="executive_summary", title="Executive Summary"),
            PresentationSlide(
                id="slide_rev",
                slide_type="analysis",
                title="Revenue Trajectory",
                section_id="sec_rev",
                section_title="Revenue",
                message="Revenue expanded rapidly.",
                chart_ids=["chart_rev"],
                source_pages=[1],
            ),
            PresentationSlide(
                id="slide_sparse",
                slide_type="analysis",
                title="Sparse Narrative",
                section_id="sec_rev",
                section_title="Revenue",
                message="One short sentence.",
                insight_ids=["ins_isolated"],
                source_pages=[1],
            ),
            PresentationSlide(id="quality", slide_type="data_quality", title="Data Quality"),
            PresentationSlide(id="appendix", slide_type="appendix", title="Appendix"),
        ],
    )
    result.presentation_plan = plan

    # 1. Without auto_repair: flags WARNING
    issues_no_repair = validate_presentation_layout(result, auto_repair=False)
    assert any(i.code == "low_density_analysis_slide" and i.severity == "WARNING" for i in issues_no_repair)

    # 2. With auto_repair: merges into neighbouring slide
    issues_repaired = validate_presentation_layout(result, auto_repair=True)
    assert any(i.code == "low_density_analysis_slide_repaired" for i in issues_repaired)
    repaired_analysis = [s for s in result.presentation_plan.slides if s.slide_type == "analysis"]
    assert len(repaired_analysis) == 1
    assert repaired_analysis[0].id == "slide_rev"
    assert "ins_isolated" in repaired_analysis[0].insight_ids
