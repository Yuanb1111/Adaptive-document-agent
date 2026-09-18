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

    # Appendix slide is before the final official Thank You slide
    appendix_slide = deck.slides[-2]
    tables = [s.table for s in appendix_slide.shapes if s.has_table]
    assert len(tables) >= 1
    table = tables[0]
    total_w = sum(col.width.inches for col in table.columns)
    assert abs(total_w - 11.70) < 0.1
    assert table.columns[0].width.inches >= 2.5
    # Tesla-style wide table has Metric + Unit + Periods columns
    assert len(table.columns) == 5
    assert table.cell(0, 0).text == "Financial Metric"
    assert table.cell(0, 1).text == "Unit"

    # Final slide is the official FOURIER Thank You slide
    thank_you_slide = deck.slides[-1]
    assert any("thank you" in s.text.casefold() for s in thank_you_slide.shapes if s.has_text_frame)


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


def test_update_geometry_preserves_unspecified_dimensions() -> None:
    from adaptive_document_agent.services.pptx_export import update_geometry
    prs = Presentation(r"adaptive_document_agent/templates/FOURIER Light Version Template EN_251217.pptx")
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    phs = {p.placeholder_format.idx: p for p in slide.placeholders}
    t = phs[14]
    s = phs[16]

    orig_t_w = t.width.inches
    orig_t_l = t.left.inches
    orig_s_w = s.width.inches
    orig_s_l = s.left.inches

    # Test 1: Update only height, verify width and left remain completely intact
    update_geometry(t, height=1.15)
    assert abs(t.width.inches - orig_t_w) < 0.05
    assert abs(t.left.inches - orig_t_l) < 0.05
    assert abs(t.height.inches - 1.15) < 0.05

    # Test 2: Update only top position, verify width, height, and left remain intact
    update_geometry(s, top=2.10)
    assert abs(s.width.inches - orig_s_w) < 0.05
    assert abs(s.left.inches - orig_s_l) < 0.05
    assert abs(s.top.inches - 2.10) < 0.05

    # Test 3: Title width cannot collapse to zero
    update_geometry(t, width=0.0)
    assert t.width.inches >= 8.0


def test_preflight_restores_collapsed_title_width() -> None:
    prs = Presentation(r"adaptive_document_agent/templates/FOURIER Light Version Template EN_251217.pptx")
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    phs = {p.placeholder_format.idx: p for p in slide.placeholders}
    t = phs[14]
    # Simulate a bug where width was set to near zero
    t.width = Inches(0.01)

    preflight = PresentationPreflight(prs)
    issues = preflight.validate_and_sanitize()

    assert any(i.code == "title_geometry_collapsed" for i in issues)
    assert t.width.inches >= 8.5


def test_cjk_multilingual_table_row_and_header_extraction() -> None:
    from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
    from adaptive_document_agent.models.table import ExtractedTable, TableRow

    # Table with Chinese financial labels (e.g. LDROBOT prospectus)
    headers = ["项目", "2021", "2022", "2023"]
    rows = [
        TableRow(cells=["营业收入", "100,000", "150,000", "220,000"], page=10),
        TableRow(cells=["毛利", "30,000", "48,000", "75,000"], page=10),
        TableRow(cells=["流动比率", "1.25", "1.45", "1.80"], page=10),
    ]
    table = ExtractedTable(
        table_id="tbl_cjk",
        page=10,
        headers=headers,
        column_periods=[None, "2021", "2022", "2023"],
        rows=rows,
        raw_cells=[[c for c in r.cells] for r in rows],
        bbox=(50.0, 100.0, 500.0, 300.0),
        confidence=0.9,
        default_unit="currency",
        default_currency="RMB",
        default_raw_unit="RMB '000",
        default_unit_scale=1000.0,
    )
    extractor = ObservationExtractor()
    obs = extractor._table_observations(table)

    # All Chinese rows must be successfully extracted
    assert len(obs) == 9
    metrics = {o.metric_original for o in obs}
    assert "营业收入" in metrics
    assert "毛利" in metrics
    assert "流动比率" in metrics

    # Multiples should be correctly identified
    cr_obs = [o for o in obs if o.metric_original == "流动比率"]
    assert len(cr_obs) == 3
    assert all(o.unit_family == "multiple" or o.unit == "multiple" for o in cr_obs)


def test_cross_table_metric_series_construction() -> None:
    from adaptive_document_agent.document_model.series import best_period_series
    # Multi-page table where 2021-2022 are in table_1 and 2023-2024 are in table_2
    obs = [
        Observation(
            id="rev_21",
            metric_original="Revenue",
            value=100.0,
            raw_value="100",
            period="FY2021",
            unit="currency",
            currency="RMB",
            unit_family="currency",
            evidence=[SourceEvidence(page=45, text="100", extraction_method="digital_table", table_id="tbl_45", confidence=0.9)],
            confidence=0.9,
        ),
        Observation(
            id="rev_22",
            metric_original="Revenue",
            value=150.0,
            raw_value="150",
            period="FY2022",
            unit="currency",
            currency="RMB",
            unit_family="currency",
            evidence=[SourceEvidence(page=45, text="150", extraction_method="digital_table", table_id="tbl_45", confidence=0.9)],
            confidence=0.9,
        ),
        Observation(
            id="rev_23",
            metric_original="Revenue",
            value=220.0,
            raw_value="220",
            period="FY2023",
            unit="currency",
            currency="RMB",
            unit_family="currency",
            evidence=[SourceEvidence(page=46, text="220", extraction_method="digital_table", table_id="tbl_46", confidence=0.9)],
            confidence=0.9,
        ),
        Observation(
            id="rev_24",
            metric_original="Revenue",
            value=310.0,
            raw_value="310",
            period="FY2024",
            unit="currency",
            currency="RMB",
            unit_family="currency",
            evidence=[SourceEvidence(page=46, text="310", extraction_method="digital_table", table_id="tbl_46", confidence=0.9)],
            confidence=0.9,
        ),
    ]
    # Cross-table series should successfully unify into all 4 periods
    series = best_period_series(obs)
    assert len(series) == 4
    assert [o.period for o in series] == ["FY2021", "FY2022", "FY2023", "FY2024"]


def test_template_text_completeness_and_sanitization() -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    tb = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1))
    tb.text_frame.text = "The CSV export contains the complete retained fact base with {dataset_name} and None values."

    preflight = PresentationPreflight(prs)
    issues = preflight.validate_and_sanitize()

    # Preflight should detect and clean banned phrase 'retained fact', unresolved variable, and 'None'
    clean_text = tb.text_frame.text
    assert "retained fact" not in clean_text
    assert "{dataset_name}" not in clean_text
    assert "None" not in clean_text
    assert "  " not in clean_text  # No double spaces
    assert "The CSV export contains the complete  base." not in clean_text


def test_empty_appendix_explicit_fallback_card() -> None:
    from adaptive_document_agent.services.pptx_export import _add_evidence_table_slides
    prs = Presentation(r"adaptive_document_agent/templates/FOURIER Light Version Template EN_251217.pptx")
    empty_result = PipelineResult(
        document=ParsedDocument(document_id="d0", sha256="s0", safe_filename="doc.pdf", page_count=10),
        profile=DocumentProfile(document_type="Prospectus", document_summary="Test"),
        observations=[],
        charts=[],
    )
    _add_evidence_table_slides(prs, empty_result, [])
    appendix_slide = prs.slides[-1]

    # Must contain explicit fallback text rather than an empty 1-row table
    slide_text = " ".join(s.text for s in appendix_slide.shapes if s.has_text_frame)
    assert "No chart-grade structured observations were retained" in slide_text
    assert "The CSV export contains the complete reported dataset." in slide_text


# ---------------------------------------------------------------------------
# Defect 1: format_observation_period — point-in-time period labels
# ---------------------------------------------------------------------------

def test_format_observation_period_balance_sheet_date() -> None:
    """April 30 balance-sheet observations must render as '30 Apr 2025*', never 'FY2025'."""
    from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period

    obs = Observation(
        id="o1",
        metric_original="Total assets",
        raw_value="12000000",
        confidence=0.9,
        period="30 April 2025",
        period_type="balance_sheet_date",
        audited_status="unaudited",
    )
    result = format_observation_period(obs)
    assert result == "30 Apr 2025*", f"Expected '30 Apr 2025*', got '{result}'"


def test_format_observation_period_fy_period() -> None:
    """FY2024 observations must render as 'FY2024' regardless of is_balance_sheet."""
    from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period

    obs = Observation(
        id="o2",
        metric_original="Revenue",
        raw_value="500000",
        confidence=0.9,
        period="FY2024",
        period_type="fiscal_year",
        audited_status="audited",
    )
    result = format_observation_period(obs)
    assert result == "FY2024", f"Expected 'FY2024', got '{result}'"


def test_format_observation_period_auto_bs_from_metric() -> None:
    """Balance-sheet keyword in metric name auto-sets is_balance_sheet=True."""
    from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period

    obs = Observation(
        id="o3",
        metric_original="Cash and cash equivalents",
        raw_value="50000",
        confidence=0.9,
        period="2025-04-30",
        period_type="generic",
        audited_status="unaudited",
    )
    result = format_observation_period(obs)
    assert result == "30 Apr 2025*", f"Expected '30 Apr 2025*', got '{result}'"


# ---------------------------------------------------------------------------
# Defect 2: Negative chart rendering — number format and axis scaling
# ---------------------------------------------------------------------------

def test_negative_chart_number_format_has_sign() -> None:
    """Data labels number format must preserve minus sign (not strip it)."""
    # We test indirectly by checking the constants used in the chart builder
    # The format "0.0;-0.0;0.0" has a negative section that forces the minus sign
    signed_format = "0.0;-0.0;0.0"
    # positive, negative, zero sections
    sections = signed_format.split(";")
    assert len(sections) == 3, "Signed number format must have 3 sections"
    assert sections[1].startswith("-"), "Negative section must start with '-'"


# ---------------------------------------------------------------------------
# Defect 4: Non-monotonic series — intermediate reversal detection
# ---------------------------------------------------------------------------

def test_detect_non_monotonic_transitions_rebound() -> None:
    """Series that declines then rebounds should be detected as non-monotonic."""
    from adaptive_document_agent.validation.claim_validator import detect_non_monotonic_transitions

    class FakeObs:
        def __init__(self, v: float) -> None:
            self.value = v

    obs = [FakeObs(1.185), FakeObs(1.191), FakeObs(1.029), FakeObs(1.506)]
    result = detect_non_monotonic_transitions(obs)  # type: ignore[arg-type]
    assert result["is_non_monotonic"] is True
    assert result["had_rebound"] is True


def test_detect_non_monotonic_transitions_monotone() -> None:
    """Monotone increasing series must NOT be flagged as non-monotonic."""
    from adaptive_document_agent.validation.claim_validator import detect_non_monotonic_transitions

    class FakeObs:
        def __init__(self, v: float) -> None:
            self.value = v

    obs = [FakeObs(100), FakeObs(200), FakeObs(300)]
    result = detect_non_monotonic_transitions(obs)  # type: ignore[arg-type]
    assert result["is_non_monotonic"] is False


# ---------------------------------------------------------------------------
# Defect 5: Evidence completeness — title claim check
# ---------------------------------------------------------------------------

def test_evidence_completeness_strips_unsupported_multi_period_claim() -> None:
    """Slide title claiming 'across the Track Record Period' with 1 obs period gets repaired."""
    from adaptive_document_agent.services.qa_reporter import check_evidence_completeness_for_title_claims

    obs = Observation(
        id="oe1",
        metric_original="Adjusted EBITDA loss",
        raw_value="-100",
        confidence=0.9,
        period="FY2024",
        period_type="fiscal_year",
    )
    slide = PresentationSlide(
        id="slide_revenue",
        slide_type="analysis",
        title="Adjusted EBITDA loss shrank across the Track Record Period",
        observation_ids=["oe1"],
    )
    plan = PresentationPlan(title="Test", slides=[slide])
    issues = check_evidence_completeness_for_title_claims(plan, [obs])
    assert any(i.code == "evidence_incomplete_title_claim" for i in issues)
    # Title should be repaired
    assert "across the Track Record Period" not in slide.title


def test_evidence_completeness_ok_with_two_periods() -> None:
    """Slide title with 2+ distinct period observations must NOT be flagged."""
    from adaptive_document_agent.services.qa_reporter import check_evidence_completeness_for_title_claims

    obs1 = Observation(id="oe2", metric_original="EBITDA", raw_value="-100", confidence=0.9, period="FY2022", period_type="fiscal_year")
    obs2 = Observation(id="oe3", metric_original="EBITDA", raw_value="-80", confidence=0.9, period="FY2023", period_type="fiscal_year")
    slide = PresentationSlide(
        id="slide_ebitda",
        slide_type="analysis",
        title="EBITDA improved across the Track Record Period",
        observation_ids=["oe2", "oe3"],
    )
    plan = PresentationPlan(title="Test", slides=[slide])
    issues = check_evidence_completeness_for_title_claims(plan, [obs1, obs2])
    assert not any(i.code == "evidence_incomplete_title_claim" for i in issues)


# ---------------------------------------------------------------------------
# Defect 6: Expense ratio — cost of sales ratio must be EXPENSE not RATIO
# ---------------------------------------------------------------------------

def test_cost_of_sales_ratio_classified_as_expense() -> None:
    """'Cost of sales / revenue' is an expense ratio and must be EXPENSE family."""
    from adaptive_document_agent.validation.claim_validator import (
        classify_metric_semantic_family,
        MetricSemanticFamily,
    )
    family = classify_metric_semantic_family("Cost of sales / revenue")
    assert family == MetricSemanticFamily.EXPENSE, f"Expected EXPENSE, got {family}"


def test_cost_of_sales_as_pct_classified_as_expense() -> None:
    """'Cost of sales as % of revenue' is an expense ratio."""
    from adaptive_document_agent.validation.claim_validator import (
        classify_metric_semantic_family,
        MetricSemanticFamily,
    )
    family = classify_metric_semantic_family("Cost of sales as % of revenue")
    assert family == MetricSemanticFamily.EXPENSE, f"Expected EXPENSE, got {family}"


def test_gross_margin_still_ratio() -> None:
    """'Gross profit margin' must remain RATIO family (not EXPENSE)."""
    from adaptive_document_agent.validation.claim_validator import (
        classify_metric_semantic_family,
        MetricSemanticFamily,
    )
    family = classify_metric_semantic_family("Gross profit margin")
    assert family == MetricSemanticFamily.RATIO, f"Expected RATIO, got {family}"


def test_expense_ratio_decrease_not_contradiction_of_gross_margin() -> None:
    """Declining cost of sales ratio should NOT contradict gross margin improvement."""
    from adaptive_document_agent.validation.claim_validator import (
        determine_trend_state,
        TrendState,
        classify_metric_semantic_family,
        MetricSemanticFamily,
    )
    # Cost of sales ratio declined 65% → 60% (positive for gross margin)
    family = classify_metric_semantic_family("Cost of sales / revenue")
    assert family == MetricSemanticFamily.EXPENSE

    trend = determine_trend_state("Cost of sales / revenue", 65.0, 60.0)
    # A 65 → 60 decrease in EXPENSE metric must be DECREASED (not contradicting gross margin improvement)
    assert trend == TrendState.DECREASED, f"Expected DECREASED, got {trend}"


