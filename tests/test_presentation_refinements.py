"""Unit tests for presentation refinements, metric semantics, period formatting, and preflight."""

import io
from pptx import Presentation
from pptx.util import Inches

from adaptive_document_agent.document_model.metric_semantic_classifier import (
    classify_metric,
    is_currency_metric,
    is_percentage_metric,
)
from adaptive_document_agent.document_model.period_semantic_validator import (
    format_period_label,
    is_interim_date,
    period_sort_key_extended,
)
from adaptive_document_agent.models import (
    ChartPlan,
    DocumentProfile,
    Observation,
    ParsedDocument,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    CompanyProfile,
    SourceEvidence,
)
from adaptive_document_agent.services.export import export_pptx
from adaptive_document_agent.services.ppt_preflight import PresentationPreflight


def test_metric_semantic_classifier() -> None:
    sem_gp = classify_metric("Gross profit", value=256548.0, raw_unit="RMB '000", unit="currency")
    assert sem_gp.metric_type == "currency"
    assert sem_gp.is_currency is True
    assert sem_gp.is_percentage is False
    assert is_currency_metric("Gross profit") is True

    sem_gm = classify_metric("Gross margin", value=31.7, raw_unit="%", unit="percent")
    assert sem_gm.metric_type == "percentage"
    assert sem_gm.is_percentage is True
    assert sem_gm.is_currency is False
    assert is_percentage_metric("Gross margin") is True

    sem_cleaned = classify_metric("Revenue % of RMB", value=521747.0, raw_unit="RMB in thousands")
    assert "of RMB" not in sem_cleaned.clean_name
    assert sem_cleaned.clean_name == "Revenue"

    sem_seg = classify_metric("Geek+ EMEA % of total revenue", value=42.5)
    assert "share of revenue" in sem_seg.clean_name

    sem_rd = classify_metric("Research and development expenses as % of revenue", value=14.2)
    assert sem_rd.clean_name == "R&D / revenue"


def test_period_semantic_validator() -> None:
    assert format_period_label("2025-04-30", is_balance_sheet=True) == "30 Apr 2025*"
    assert format_period_label("As of April 30, 2025", is_balance_sheet=True) == "30 Apr 2025*"
    assert format_period_label("4M2025", is_balance_sheet=True) == "30 Apr 2025*"
    assert is_interim_date("2025-04-30") is True

    assert format_period_label("4M2025", is_balance_sheet=False) == "4M2025"
    assert format_period_label("FY2024", is_balance_sheet=False) == "FY2024"

    assert period_sort_key_extended("FY2023") < period_sort_key_extended("FY2024")
    assert period_sort_key_extended("FY2024") < period_sort_key_extended("4M2025")


def test_presentation_preflight_disables_gridlines_and_cleans_phrases() -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    tb = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
    tb.text_frame.text = "This is a calculated result based on extracted observations."

    preflight = PresentationPreflight(prs)
    issues = preflight.validate_and_sanitize()

    assert "calculated result" not in tb.text_frame.text
    assert "based on extracted observations" not in tb.text_frame.text
    assert any(i.code == "banned_phrase" for i in issues)


def test_pptx_export_structure_ordering_and_gridlines() -> None:
    evidence = SourceEvidence(page=100, text="1000", extraction_method="digital_table", confidence=0.9)
    obs = [
        Observation(
            id=f"rev_{yr}",
            metric_original="Revenue",
            value=v,
            raw_value=str(v),
            currency="RMB",
            unit="currency",
            period=f"FY{yr}",
            evidence=[evidence],
            confidence=0.9,
        )
        for yr, v in ((2022, 100), (2023, 200), (2024, 300))
    ]
    chart = ChartPlan(
        id="c1",
        title="Revenue Growth",
        chart_type="bar",
        question="How did revenue grow?",
        observation_ids=[o.id for o in obs],
        source_pages=[100],
    )
    plan = PresentationPlan(
        title="Institutional Review",
        company=CompanyProfile(name="Test Corp", one_line_description="A test tech firm.", source_pages=[1]),
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Institutional Review"),
            PresentationSlide(id="overview", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(id="summary", slide_type="executive_summary", title="Executive Summary", bullets=["Consistent growth across periods"]),
            PresentationSlide(
                id="analysis",
                slide_type="analysis",
                title="Revenue Acceleration",
                section_title="Financials",
                message="Reported revenue increased across the historical years.",
                chart_ids=["c1"],
                source_pages=[100],
            ),
            PresentationSlide(id="quality", slide_type="data_quality", title="Data Quality"),
            PresentationSlide(id="appendix", slide_type="appendix", title="Source Data"),
        ],
    )
    result = PipelineResult(
        document=ParsedDocument(document_id="d1", sha256="s1", safe_filename="doc.pdf", page_count=200),
        profile=DocumentProfile(document_type="Prospectus", document_summary="Tech firm overview"),
        observations=obs,
        charts=[chart],
        presentation_plan=plan,
    )

    pptx_bytes = export_pptx(result)
    deck = Presentation(io.BytesIO(pptx_bytes))

    slide_titles = [
        next((s.text.strip() for s in slide.shapes if s.has_text_frame and s.text.strip()), "")
        for slide in deck.slides
    ]
    assert slide_titles[0] == "Institutional Review"
    assert slide_titles[1] == "Contents"
    assert slide_titles[2] == "Company at a Glance"
    assert slide_titles[3] == "Executive Summary"
    assert slide_titles[4] == "Revenue Acceleration"

    analysis_slide = deck.slides[4]
    charts = [s.chart for s in analysis_slide.shapes if s.has_chart]
    assert len(charts) == 1
    ch = charts[0]
    if hasattr(ch, "value_axis") and ch.value_axis:
        assert ch.value_axis.has_major_gridlines is False
        assert ch.value_axis.has_minor_gridlines is False
    if hasattr(ch, "category_axis") and ch.category_axis:
        assert ch.category_axis.has_major_gridlines is False
        assert ch.category_axis.has_minor_gridlines is False

    appendix_slide = deck.slides[-1]
    tables = [s.table for s in appendix_slide.shapes if s.has_table]
    assert len(tables) >= 1
    table = tables[0]
    assert len(table.columns) == 5
    total_w = sum(col.width.inches for col in table.columns)
    assert abs(total_w - 11.70) < 0.1
    assert table.columns[4].width.inches < 1.2
    assert table.columns[0].width.inches > 3.8


def test_multiple_ratio_semantics_and_formatting() -> None:
    from adaptive_document_agent.document_model.metric_semantic_classifier import (
        format_metric_change,
        format_metric_display_value,
        is_multiple_metric,
    )
    from adaptive_document_agent.models import FinancialObservation

    cr_sem = classify_metric("Current ratio", value=1.45, raw_unit="", unit="multiple")
    assert cr_sem.is_multiple is True
    assert cr_sem.is_percentage is False
    assert cr_sem.is_currency is False
    assert cr_sem.unit_family == "multiple"
    assert is_multiple_metric("Current ratio") is True

    # Multiples must format change as '+0.20x', NEVER 'pp' or '%'
    change_str = format_metric_change(1.10, 1.30, 1.0, cr_sem)
    assert change_str == "+0.20x"
    assert "pp" not in change_str

    # Multiples must display as '1.45x', NEVER '1.45%'
    disp_str = format_metric_display_value("1.45", 1.45, cr_sem)
    assert disp_str == "1.45x"
    assert "%" not in disp_str

    qr_sem = classify_metric("Quick ratio", value=0.98)
    assert qr_sem.is_multiple is True
    assert is_multiple_metric("Quick ratio") is True

    # FinancialObservation model and typed properties
    obs = FinancialObservation(
        id="cr_1",
        metric_original="Current ratio",
        value=1.45,
        raw_value="1.45",
        unit="multiple",
        semantic_type="multiple",
        unit_family="multiple",
        display_unit="x",
        period_type="instant",
        as_of_date="2024-12-31",
        confidence=0.95,
    )
    assert obs.numeric_value == 1.45
    assert obs.source_label == "Current ratio"
    assert obs.unit_family == "multiple"
    assert obs.period_type == "instant"


def test_currency_vs_share_of_revenue_semantics() -> None:
    from adaptive_document_agent.document_model.metric_semantic_classifier import (
        format_metric_change,
        format_metric_display_value,
    )

    # Monetary loss metric
    sem_loss = classify_metric("Loss from operations", value=-145200.0, raw_unit="RMB '000", unit="currency")
    assert sem_loss.is_currency is True
    assert sem_loss.is_percentage is False
    assert sem_loss.unit_family == "currency"

    loss_disp = format_metric_display_value("-145,200", -145200.0, sem_loss, raw_unit="RMB '000", currency="RMB")
    assert "RMB '000" in loss_disp
    assert "%" not in loss_disp

    # Loss narrowing explanation
    loss_change = format_metric_change(-200.0, -150.0, 1.0, sem_loss)
    assert "Loss narrowed by 50.0" in loss_change

    # Share of revenue metric
    sem_share = classify_metric("Loss from operations: share of revenue", value=22.4, raw_unit="%")
    assert sem_share.is_percentage is True
    assert sem_share.is_currency is False
    assert sem_share.unit_family == "percentage"

    share_disp = format_metric_display_value("22.4", 22.4, sem_share)
    assert share_disp == "22.4%"


def test_long_title_dynamic_layout_and_preflight() -> None:
    long_title = "Rapid expansion across European fulfillment networks accelerated revenue growth while operating leverage supported margin trajectory"
    assert len(long_title) > 80

    evidence = SourceEvidence(page=50, text="120", extraction_method="digital_table", confidence=0.9)
    obs = [
        Observation(
            id=f"metric_{i}",
            metric_original="Gross profit",
            value=float(100 + i * 50),
            raw_value=str(100 + i * 50),
            unit="currency",
            currency="RMB",
            period=f"FY202{i}",
            evidence=[evidence],
            confidence=0.9,
        )
        for i in range(1, 4)
    ]
    chart = ChartPlan(
        id="c_long",
        title="Gross Profit Trajectory",
        chart_type="bar",
        question="How did gross profit evolve?",
        observation_ids=[o.id for o in obs],
        source_pages=[50],
    )
    plan = PresentationPlan(
        title="Institutional Review",
        company=CompanyProfile(name="Scale Tech Inc.", one_line_description="Global automation leader", source_pages=[1]),
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Institutional Review"),
            PresentationSlide(id="overview", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(id="summary", slide_type="executive_summary", title="Executive Summary", bullets=["Consistent growth across periods"]),
            PresentationSlide(
                id="long_analysis",
                slide_type="analysis",
                title=long_title,
                section_title="Financial Performance",
                message="Substantial improvements observed throughout the track record period.",
                chart_ids=["c_long"],
                source_pages=[50],
            ),
            PresentationSlide(id="quality", slide_type="data_quality", title="Data Quality"),
            PresentationSlide(id="appendix", slide_type="appendix", title="Source Data"),
        ],
    )
    result = PipelineResult(
        document=ParsedDocument(document_id="d_long", sha256="s_long", safe_filename="doc.pdf", page_count=100),
        profile=DocumentProfile(document_type="Prospectus", document_summary="Automation company"),
        observations=obs,
        charts=[chart],
        presentation_plan=plan,
    )

    pptx_bytes = export_pptx(result)
    deck = Presentation(io.BytesIO(pptx_bytes))
    # In exported deck: 0=Cover, 1=Contents, 2=Overview, 3=Summary, 4=Analysis
    slide = deck.slides[4]

    # Check title and subtitle placeholder spacing
    phs = {p.placeholder_format.idx: p for p in slide.placeholders}
    title_ph = phs.get(14) or phs.get(15)
    sub_ph = phs.get(16)

    assert title_ph is not None
    assert sub_ph is not None
    # Subtitle must start strictly below title bottom
    assert sub_ph.top.inches >= title_ph.top.inches + title_ph.height.inches - 0.01

    # Check that preflight detects zero fatal collisions
    preflight = PresentationPreflight(deck)
    issues = preflight.validate_and_sanitize()
    severe_collisions = [i for i in issues if i.code in ("title_subtitle_collision", "title_collision")]
    assert len(severe_collisions) == 0


def test_preflight_ratio_sanitization() -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    tb = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1))
    tb.text_frame.text = "Current ratio: 1.45% and Quick ratio increased by +0.20 pp in the period"

    preflight = PresentationPreflight(prs)
    issues = preflight.validate_and_sanitize()

    # Preflight should detect and fix invalid ratio unit (%) and invalid ratio change (pp)
    assert any(i.code == "invalid_ratio_unit" for i in issues)
    assert any(i.code == "invalid_ratio_change" for i in issues)
    assert "1.45x" in tb.text_frame.text
    assert "+0.20x" in tb.text_frame.text
    assert "1.45%" not in tb.text_frame.text
    assert "pp" not in tb.text_frame.text

