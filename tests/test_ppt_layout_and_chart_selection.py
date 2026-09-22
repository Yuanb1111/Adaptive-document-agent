"""Comprehensive tests for PPT layout and chart-selection generic fixes.

Tests:
1. Company Overview structured extraction & fixed 4-card snapshot layout (cards/bullets).
   Ensures unresolved issuer name renders as a small note only, never a long narrative block.
2. Scatter chart selection safeguards:
   Rejects arbitrary numeric categories (70.901, 131.843), requires meaningful numeric variables,
   explicit axis labels, explained relationship; falls back to line, bar, or table.
3. Multi-chart slide safe areas:
   3-chart panels keep legends at TOP, never overlapping black explanatory text;
   auto-splits into two slides when cramped.
4. Source / page labels:
   Strict non-overlapping safe placement.
5. Layout QA & auto-repair:
   Detects and auto-repairs unreadable scatter, cramped 3-chart panels, and narrative overflow.
"""

from __future__ import annotations

import io
from pptx import Presentation

from adaptive_document_agent.agent.chart_planner import ChartPlanner, is_valid_scatter_candidate
from adaptive_document_agent.models import (
    AnalysisTask,
    ChartPlan,
    CompanyFact,
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
from adaptive_document_agent.services.company_extractor import extract_structured_company_fields
from adaptive_document_agent.services.export import export_pptx
from adaptive_document_agent.services.pptx_export import build_presentation
from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa
from adaptive_document_agent.validation.layout_qa import validate_presentation_layout


def _make_evidence(page: int = 12) -> SourceEvidence:
    return SourceEvidence(page=page, text="123.4", extraction_method="digital_table", confidence=0.95)


def _base_result() -> PipelineResult:
    evidence = _make_evidence(10)
    observations = [
        Observation(
            id=f"rev-{yr}",
            metric_original="Revenue",
            canonical_name="revenue",
            value=val,
            raw_value=str(val),
            unit="currency",
            currency="USD",
            period=f"FY{yr}",
            dimensions={"period_basis": "FY"},
            evidence=[evidence],
            confidence=0.9,
        )
        for yr, val in [(2021, 100.0), (2022, 130.0), (2023, 175.0)]
    ]
    return PipelineResult(
        document=ParsedDocument(document_id="doc1", sha256="hash1", safe_filename="doc.pdf", page_count=50),
        profile=DocumentProfile(
            document_type="Prospectus",
            overview_title="Company overview",
            document_summary=(
                "The group operates in the Industrial Automation industry, specializing in robotic arms "
                "and sensor control systems. It operates a B2B direct sales and subscription service model. "
                "Main markets include Mainland China, Europe, and North America. Ranked No. 1 in domestic market share with 28.5%. "
                "Stock code: 01234.HK, listing on HKEX Main Board via Global Offering for the track record period FY2021-FY2023."
            ),
            document_purpose="Evaluate commercial and financial track record.",
        ),
        observations=observations,
        report_plan=ReportPlan(title="Executive Investment Deck"),
    )


def _make_valid_plan(
    analysis_slides: list[PresentationSlide],
    company: CompanyProfile | None = None,
    result: PipelineResult | None = None,
) -> PresentationPlan:
    obs_pages: list[int] = []
    first_obs_id: list[str] = []
    if result and result.observations:
        first_obs = result.observations[0]
        first_obs_id = [first_obs.id]
        obs_pages = sorted({source.page for source in first_obs.evidence})
    if not obs_pages:
        obs_pages = [10]

    if company is None:
        company = CompanyProfile(name="Test Issuer", source_pages=obs_pages)
    elif not company.source_pages:
        company = company.model_copy(update={"source_pages": obs_pages})

    slides = [
        PresentationSlide(id="cover", slide_type="cover", title="Cover", message="Document Analysis"),
        PresentationSlide(id="co", slide_type="company_overview", title="Company at a Glance"),
        PresentationSlide(
            id="exec",
            slide_type="executive_summary",
            title="Executive Summary",
            message="Executive summary overview",
            source_pages=obs_pages,
            observation_ids=first_obs_id,
        ),
        *analysis_slides,
        PresentationSlide(
            id="dq",
            slide_type="data_quality",
            title="Data Quality & Integrity",
            section_title="Data Quality",
        ),
        PresentationSlide(
            id="app",
            slide_type="appendix",
            title="Appendix",
            section_title="Appendix",
        ),
    ]
    return PresentationPlan(
        title="Investment Deck",
        company=company,
        slides=slides,
    )


# ==============================================================================
# 1. Company Overview Template & Structured Fields Extraction
# ==============================================================================

def test_company_overview_structured_extraction():
    """Verify that structured fields are extracted from unstructured text before slide generation."""
    result = _base_result()
    company = CompanyProfile(
        name="Automation Dynamics Ltd.",
        one_line_description=result.profile.document_summary,
    )
    enriched = extract_structured_company_fields(company, result)

    assert enriched.industry == "Industrial Automation"
    assert any("robotic" in p.casefold() or "sensor" in p.casefold() for p in enriched.products)
    assert "B2B" in enriched.business_model or "direct sales" in enriched.business_model.casefold()
    assert any("China" in g or "Europe" in g for g in enriched.geographies)
    assert "Ranked No. 1" in enriched.market_position or "28.5%" in enriched.market_position
    assert "01234.HK" in enriched.stock_code or any("01234.HK" in f for f in enriched.listing_facts)
    assert "HKEX" in enriched.listing_market or "MAIN BOARD" in enriched.listing_market


def test_company_overview_unresolved_name_snapshot_layout():
    """Unresolved identity remains explicit in a flat, readable three-part brief."""
    result = _base_result()
    company = CompanyProfile(
        name="",  # Unresolved
        one_line_description=(
            "A provider in the Biotechnology sector focusing on mRNA vaccines. "
            "Operates direct sales model across Mainland China and North America."
        ),
    )
    slide = PresentationSlide(
        id="slide_company_overview",
        slide_type="company_overview",
        title="Document at a Glance",
    )
    analysis_slide = PresentationSlide(
        id="anal",
        slide_type="analysis",
        title="Revenue Performance",
        message="Revenue grew consistently over the period",
        section_title="Financials",
        source_pages=[10],
        observation_ids=["rev-2021", "rev-2022", "rev-2023"],
    )
    result.presentation_plan = _make_valid_plan([analysis_slide], company=company, result=result)

    pptx_bytes = build_presentation(result)
    prs = Presentation(io.BytesIO(pptx_bytes))
    company_slide = prs.slides[2]  # slide 0 is cover, slide 1 is contents, slide 2 is company overview

    slide_text = " ".join(
        p.text for s in company_slide.shapes if s.has_text_frame for p in s.text_frame.paragraphs
    )

    # Must contain the unresolved issuer note
    assert "Issuer name not identified in supplied pages" in slide_text

    assert "Document overview" in slide_text
    assert "Business and products" in slide_text
    profile_slides = [s for s in prs.slides if any(sh.has_text_frame and sh.text.startswith("Document at a Glance") for sh in s.shapes)]
    all_profile_text = " ".join(sh.text for sl in profile_slides for sh in sl.shapes if sh.has_text_frame)
    assert "Markets and listing" in all_profile_text
    bodies = [shape for sl in profile_slides for shape in sl.shapes if shape.name == "brief:body"]
    assert len(bodies) >= 3
    assert all(p.font.size.pt == 18 for s in bodies for p in s.text_frame.paragraphs)
    assert company_slide.notes_slide.notes_text_frame.text
    assert "ISSUER PROFILE & IDENTITY" not in slide_text


def test_company_overview_resolved_name_snapshot_layout():
    """When company name is resolved, slide shows company name and 4 structured cards with clean bullets."""
    result = _base_result()
    company = CompanyProfile(
        name="Apex Robotics Inc.",
        industry="Industrial Automation",
        business_model="B2B direct manufacturing and SaaS maintenance",
        products=["Industrial Robocells", "Vision Inspection Sensors"],
        geographies=["Mainland China", "North America"],
        market_position="Ranked #1 with 28.5% market share",
        stock_code="09988.HK",
        identity_state="RESOLVED",
    )
    analysis_slide = PresentationSlide(
        id="anal",
        slide_type="analysis",
        title="Revenue Performance",
        message="Revenue grew consistently over the period",
        section_title="Financials",
        source_pages=[10],
        observation_ids=["rev-2021", "rev-2022", "rev-2023"],
    )
    result.presentation_plan = _make_valid_plan([analysis_slide], company=company, result=result)

    pptx_bytes = build_presentation(result)
    prs = Presentation(io.BytesIO(pptx_bytes))
    company_slide = prs.slides[2]
    slide_text = " ".join(
        p.text for s in company_slide.shapes if s.has_text_frame for p in s.text_frame.paragraphs
    )

    assert "Apex Robotics Inc." in slide_text
    assert "Issuer name not identified" not in slide_text
    assert "Industrial Robocells" in slide_text
    assert "Ranked #1 with 28.5% market share" in slide_text


# ==============================================================================
# 2. Scatter Chart Selection Safeguards
# ==============================================================================

def test_scatter_chart_rejects_arbitrary_numeric_categories():
    """Arbitrary numeric categories (e.g. 70.901, 131.843) must be rejected for scatter charts."""
    ev = _make_evidence()
    # Mock observations where metrics or categories are arbitrary decimal numbers
    obs = [
        Observation(
            id=f"obs-{i}",
            metric_original="70.901",
            canonical_name="70.901",
            value=float(val),
            raw_value=str(val),
            dimensions={"category": f"ratio_{val}"},
            evidence=[ev],
            confidence=0.9,
        )
        for i, val in enumerate([70.901, 131.843, 45.210, 89.100, 112.450])
    ]
    task = AnalysisTask(
        id="task_corr",
        title="Correlation",
        description="Correlation between categories",
        analysis_type="pearson_correlation",
        required_metrics=["70.901", "131.843"],
        reason="Check relationship",
        expected_output="Correlation coefficient",
    )

    # Check is_valid_scatter_candidate
    assert not is_valid_scatter_candidate(task, obs, "70.901", "131.843")

    # In ChartPlanner, fallback must NOT select scatter
    planner = ChartPlanner()
    selected = planner._select_chart_type(task, obs, {})
    assert selected != "scatter"
    assert selected in {"bar", "line", "horizontal_bar", "table"}

    # Available types must not offer scatter
    avail = planner._available_types(task, obs)
    assert "scatter" not in avail


def test_scatter_chart_requires_continuous_variance_and_explained_relationship():
    """Scatter requires meaningful named variables, explicit labels, continuous variance, and explanation."""
    ev = _make_evidence()
    # Valid continuous paired variables
    obs = []
    for i in range(8):
        obs.append(
            Observation(
                id=f"rd-{i}",
                metric_original="R&D Expense",
                canonical_name="rd_expense",
                value=float(10 + i * 5),
                raw_value=str(10 + i * 5),
                period=f"Period {i}",
                dimensions={"index": str(i)},
                evidence=[ev],
                confidence=0.9,
            )
        )
        obs.append(
            Observation(
                id=f"rev-{i}",
                metric_original="Revenue",
                canonical_name="revenue",
                value=float(50 + i * 25),
                raw_value=str(50 + i * 25),
                period=f"Period {i}",
                dimensions={"index": str(i)},
                evidence=[ev],
                confidence=0.9,
            )
        )

    valid_task = AnalysisTask(
        id="task_valid",
        title="R&D Correlation",
        description="Examine the correlation relationship between R&D Expense and Revenue growth.",
        analysis_type="pearson_correlation",
        required_metrics=["R&D Expense", "Revenue"],
        reason="Verify if higher R&D expense yields increased top-line revenue.",
        expected_output="Correlation analysis",
    )
    assert is_valid_scatter_candidate(valid_task, obs, "R&D Expense", "Revenue")

    # Missing explanation must fail
    unexplained_task = AnalysisTask(
        id="task_no_exp",
        title="Unexplained",
        description="",
        analysis_type="pearson_correlation",
        required_metrics=["R&D Expense", "Revenue"],
        reason="",
        expected_output="Output",
    )
    assert not is_valid_scatter_candidate(unexplained_task, obs, "R&D Expense", "Revenue")


# ==============================================================================
# 3. Multi-Chart Slide Safe Areas & Splitting
# ==============================================================================

def test_multi_chart_3_panels_legend_at_top_no_footer_overlap():
    """For slides with 3 charts, legends must be positioned at TOP so colored legends never overlap black footer text."""
    result = _base_result()
    ev = _make_evidence()

    # Create 3 charts with multi-series data
    charts = []
    all_obs = []
    for c_idx in range(3):
        c_obs = [
            Observation(
                id=f"c{c_idx}-s1-2021",
                metric_original=f"Metric {c_idx + 1}",
                value=100.0 + c_idx * 10,
                raw_value="100",
                period="FY2021",
                dimensions={"series": "Product A", "period_basis": "FY"},
                evidence=[ev],
                confidence=0.9,
            ),
            Observation(
                id=f"c{c_idx}-s1-2022",
                metric_original=f"Metric {c_idx + 1}",
                value=130.0 + c_idx * 10,
                raw_value="130",
                period="FY2022",
                dimensions={"series": "Product A", "period_basis": "FY"},
                evidence=[ev],
                confidence=0.9,
            ),
            Observation(
                id=f"c{c_idx}-s2-2021",
                metric_original=f"Metric {c_idx + 1}",
                value=50.0 + c_idx * 5,
                raw_value="50",
                period="FY2021",
                dimensions={"series": "Product B", "period_basis": "FY"},
                evidence=[ev],
                confidence=0.9,
            ),
            Observation(
                id=f"c{c_idx}-s2-2022",
                metric_original=f"Metric {c_idx + 1}",
                value=70.0 + c_idx * 5,
                raw_value="70",
                period="FY2022",
                dimensions={"series": "Product B", "period_basis": "FY"},
                evidence=[ev],
                confidence=0.9,
            ),
        ]
        all_obs.extend(c_obs)
        charts.append(
            ChartPlan(
                id=f"chart_{c_idx + 1}",
                title=f"Segment Performance {c_idx + 1}",
                chart_type="bar",
                question=f"How did segment {c_idx + 1} perform?",
                observation_ids=[o.id for o in c_obs],
                source_pages=[10 + c_idx],
            )
        )

    result.observations = all_obs
    result.charts = charts

    # Create 3-up slide
    slide = PresentationSlide(
        id="slide_cluster",
        slide_type="analysis",
        title="Three Chart Cluster",
        message="Coordinated view across operational metrics",
        section_title="Operations",
        source_pages=[10, 11, 12],
        chart_ids=[c.id for c in charts],
        layout="three_up",
    )
    result.presentation_plan = _make_valid_plan([slide], company=CompanyProfile(name="Test Co"), result=result)

    # Build presentation
    pptx_bytes = build_presentation(result)
    prs = Presentation(io.BytesIO(pptx_bytes))

    # Check chart legends in generated slide
    # Either slide was auto-split into two slides (2-up and 1-up), or generated with top legends
    analysis_slides = [s for s in prs.slides if s != prs.slides[0] and s != prs.slides[1] and s != prs.slides[2]]
    assert len(analysis_slides) >= 1

    for a_slide in analysis_slides:
        for shape in a_slide.shapes:
            if shape.has_chart and shape.chart.has_legend:
                # Legend must be at TOP (0 in python-pptx XL_LEGEND_POSITION.TOP)
                from pptx.enum.chart import XL_LEGEND_POSITION
                assert shape.chart.legend.position == XL_LEGEND_POSITION.TOP


# ==============================================================================
# 4. Source / Page Labels Safe Placement
# ==============================================================================

def test_source_page_labels_no_overlap():
    """Source page references must sit safely below each chart or in a slide-level footer without collision."""
    result = _base_result()
    ev = _make_evidence(25)
    obs = [
        Observation(
            id=f"rev-{y}",
            metric_original="Revenue",
            value=float(y * 10),
            raw_value=str(y * 10),
            period=f"FY{y}",
            dimensions={"period_basis": "FY"},
            evidence=[ev],
            confidence=0.9,
        )
        for y in [2021, 2022, 2023]
    ]
    chart = ChartPlan(
        id="chart_rev",
        title="Revenue Trajectory",
        chart_type="line",
        question="What is the historical revenue trend?",
        observation_ids=[o.id for o in obs],
        source_pages=[25, 26],
    )
    result.observations = obs
    result.charts = [chart]

    slide = PresentationSlide(
        id="slide_single_chart",
        slide_type="analysis",
        title="Revenue Analysis",
        message="Revenue grew year-over-year",
        section_title="Financials",
        chart_ids=[chart.id],
        source_pages=[25, 26],
    )
    result.presentation_plan = _make_valid_plan([slide], company=CompanyProfile(name="Acme Corp"), result=result)

    pptx_bytes = build_presentation(result)
    prs = Presentation(io.BytesIO(pptx_bytes))
    target_slide = prs.slides[4]  # slide 0: cover, 1: contents, 2: co, 3: exec, 4: analysis

    # Verify source text is present and placed in lower safe zone (top > 5.0in)
    source_boxes = [
        s for s in target_slide.shapes
        if s.has_text_frame and any("p. " in p.text or "Source" in p.text for p in s.text_frame.paragraphs)
    ]
    assert len(source_boxes) >= 1
    for s_box in source_boxes:
        assert s_box.top.inches > 5.0, f"Source box top ({s_box.top.inches}in) was placed too high!"


# ==============================================================================
# 5. Layout QA Validator & Auto-Repair
# ==============================================================================

def test_layout_qa_detects_and_repairs_all_classes():
    """validate_presentation_layout detects unreadable scatter, splits cramped 3-chart slides, and structures overview."""
    result = _base_result()
    ev = _make_evidence()

    # 1. Unreadable scatter chart
    scatter_chart = ChartPlan(
        id="chart_scatter_bad",
        title="Unreadable Scatter",
        chart_type="scatter",
        question="What is the correlation?",
        x_metric="70.901",  # numeric category
        y_metric="131.843",
        observation_ids=["rev-2021", "rev-2022", "rev-2023"],
    )

    # 2. Cramped 3-chart slide with long titles and multi-series
    chart1 = ChartPlan(id="c1", title="Very Detailed Segment Operating Metric", chart_type="bar", question="Q1", observation_ids=["rev-2021", "rev-2022"])
    chart2 = ChartPlan(id="c2", title="Second Operating Metric Trajectory", chart_type="line", question="Q2", observation_ids=["rev-2022", "rev-2023"])
    chart3 = ChartPlan(id="c3", title="Third Long Metric With Detailed Disclosures", chart_type="bar", question="Q3", observation_ids=["rev-2021", "rev-2023"])
    result.charts = [scatter_chart, chart1, chart2, chart3]

    slide_cramped = PresentationSlide(
        id="slide_cramped_3",
        slide_type="analysis",
        title="Operating Dynamics Summary",
        message="Dense multi-metric operational overview across segments",
        section_title="Operations",
        source_pages=[10],
        chart_ids=["c1", "c2", "c3"],
        visual_blocks=[
            PresentationVisualBlock(role="hero", chart_ids=["c1"]),
            PresentationVisualBlock(role="supporting", chart_ids=["c2"]),
            PresentationVisualBlock(role="supporting", chart_ids=["c3"]),
        ],
        layout="three_up",
    )

    # 3. Company Overview with narrative overflow
    company = CompanyProfile(
        name="",
        one_line_description=(
            "The company is an enterprise software provider operating in the Cloud Computing space. "
            "It delivers SaaS subscription solutions to Fortune 500 customers across North America, Europe, and Asia. "
            "The company holds a 35% market share in enterprise cloud management tools. "
            "Track record period covers FY2021 through FY2023 with steady operational expansion and high customer retention."
        ),
        source_pages=[10],
    )

    result.presentation_plan = _make_valid_plan([slide_cramped], company=company, result=result)

    # Run layout QA with auto_repair=True
    issues = validate_presentation_layout(result, auto_repair=True)

    issue_codes = {i.code for i in issues}
    assert "company_overview_structured_repaired" in issue_codes
    assert "unreadable_scatter_chart_repaired" in issue_codes
    assert "cramped_multi_chart_split" in issue_codes

    # Scatter chart must have been converted to line or bar
    assert scatter_chart.chart_type in {"line", "bar"}

    # Cramped slide must have been split into two slides
    slide_ids = [s.id for s in result.presentation_plan.slides]
    assert "slide_cramped_3" in slide_ids
    assert "slide_cramped_3_part2" in slide_ids

    # Company overview must have structured fields populated
    assert result.presentation_plan.company.industry == "Cloud Computing" or "Software" in result.presentation_plan.company.industry
    assert "35%" in result.presentation_plan.company.market_position or "enterprise" in result.presentation_plan.company.market_position.casefold()


def test_run_comprehensive_qa_includes_layout_qa():
    """run_comprehensive_qa invokes layout QA and logs auto-repairs into QAReport."""
    result = _base_result()
    scatter_chart = ChartPlan(
        id="chart_scatter_num",
        title="Scatter",
        chart_type="scatter",
        question="What is the numeric category scatter?",
        x_metric="45.10",
        y_metric="92.30",
        observation_ids=["rev-2021", "rev-2022"],
    )
    result.charts = [scatter_chart]
    anal_slide = PresentationSlide(
        id="anal",
        slide_type="analysis",
        title="Scatter Analysis",
        message="Analysis of metrics",
        section_title="Analysis",
        source_pages=[10],
        chart_ids=[scatter_chart.id],
    )
    result.presentation_plan = _make_valid_plan([anal_slide], company=CompanyProfile(name="Issuer"), result=result)

    report = run_comprehensive_qa(result, auto_repair=True)
    info_codes = {item.code for item in report.info}
    assert "unreadable_scatter_chart_repaired" in info_codes
    assert scatter_chart.chart_type != "scatter"
