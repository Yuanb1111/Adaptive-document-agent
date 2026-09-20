"""Regression tests for presentation logic, financial semantics, consistency, units, and titles."""

import pytest

from adaptive_document_agent.document_model.metric_semantic_classifier import (
    classify_metric,
    is_days_metric,
    is_margin_metric,
)
from adaptive_document_agent.models import (
    DocumentProfile,
    Observation,
    ParsedDocument,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    SourceEvidence,
)
from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer
from adaptive_document_agent.services.language_qa import polish_slide_title
from adaptive_document_agent.services.movement_formatter import FinancialMovementFormatter
from adaptive_document_agent.services.pptx_export import _unit_label, _display_source_unit
from adaptive_document_agent.tools.comparison import percentage_change
from adaptive_document_agent.tools.growth import cagr, growth_rate
from adaptive_document_agent.validation.claim_validator import (
    ClaimValidator,
    DirectionalClaimIssue,
    MetricSemanticFamily,
    TrendState,
    classify_metric_semantic_family,
    determine_trend_state,
    is_expense_metric,
    repair_presentation_plan,
)
from adaptive_document_agent.validation.cross_slide_validator import CrossSlideValidator


def _ev(page: int = 1, text: str = "") -> SourceEvidence:
    return SourceEvidence(
        page=page,
        text=text or "table cell",
        extraction_method="digital_table",
        confidence=0.95,
    )


def _obs(
    id: str,
    metric_original: str,
    value: float,
    period: str,
    *,
    metric_canonical: str | None = None,
    currency: str | None = "RMB",
    unit: str | None = "currency",
    display_unit: str = "",
    page: int = 1,
) -> Observation:
    return Observation(
        id=id,
        metric_original=metric_original,
        metric_canonical=metric_canonical or metric_original.lower().replace(" ", "_"),
        period=period,
        value=value,
        raw_value=str(value),
        currency=currency,
        unit=unit,
        display_unit=display_unit,
        evidence=[_ev(page, str(value))],
        confidence=0.9,
    )


# ==============================================================================
# 1. Signed Expense Semantics
# ==============================================================================
def test_signed_expense_semantics_trend_state():
    """Expenses stored as negative accounting figures must interpret magnitude correctly."""
    assert is_expense_metric("R&D expenses")
    assert is_expense_metric("Selling and Marketing Expenses")
    assert is_expense_metric("Administrative expenses")
    assert is_expense_metric("Cost of sales")

    # -95.9 -> -121.1 means magnitude grew (spending increased)
    trend = determine_trend_state("R&D expenses", -95.9, -121.1)
    assert trend == TrendState.INCREASED

    # -121.1 -> -95.9 means magnitude shrank (spending decreased)
    trend_down = determine_trend_state("R&D expenses", -121.1, -95.9)
    assert trend_down == TrendState.DECREASED

    # Cost of sales stored as negative
    trend_cos = determine_trend_state("Cost of sales", -500.0, -750.0)
    assert trend_cos == TrendState.INCREASED


def test_signed_expense_movement_formatter():
    """Movement formatter describes negative expenses by magnitude change."""
    text_increase = FinancialMovementFormatter.format_movement(
        "R&D expenses",
        -95.9,
        -121.1,
        currency="RMB",
        scale=1_000_000.0,
    )
    assert "increased by" in text_increase
    assert "RMB25.2m" in text_increase
    assert "decreased" not in text_increase

    text_decrease = FinancialMovementFormatter.format_movement(
        "Selling and Marketing Expenses",
        -150.0,
        -100.0,
        currency="RMB",
        scale=1_000_000.0,
    )
    assert "decreased by" in text_decrease
    assert "increased" not in text_decrease


def test_signed_expense_claim_validator_flags_and_repairs():
    """Claim validator detects and fixes 'decreased' when negative expense magnitude increased."""
    obs = [
        _obs("rd_2022", "R&D expenses", -95.9, "2022", metric_canonical="research_and_development_expenses", page=10),
        _obs("rd_2023", "R&D expenses", -121.1, "2023", metric_canonical="research_and_development_expenses", page=10),
    ]

    slide = PresentationSlide(
        id="s_rd",
        slide_type="analysis",
        title="R&D Expenses",
        message="R&D expenses decreased over the period.",
        bullets=["R&D expenses decreased significantly from 2022 to 2023."],
        observation_ids=["rd_2022", "rd_2023"],
        source_pages=[10],
    )

    plan = PresentationPlan(title="Deck", slides=[slide])
    validator = ClaimValidator()
    issues = validator.validate_plan(plan, obs)

    contradictions = [i for i in issues if isinstance(i, DirectionalClaimIssue)]
    assert len(contradictions) >= 1
    assert contradictions[0].expected_direction == "INCREASED"
    assert "decreased" in contradictions[0].offending_direction

    repaired_plan, repairs = repair_presentation_plan(plan, obs)
    assert len(repairs) >= 1
    assert "increased" in repaired_plan.slides[0].message
    assert "decreased" not in repaired_plan.slides[0].message


# ==============================================================================
# 2. Executive Summary Consistency
# ==============================================================================
def test_executive_summary_consistency_validation_and_repair():
    """Executive Summary must never contradict underlying structured observations (e.g. Gross profit 71.1 -> 191.9)."""
    obs = [
        _obs("gp_2022", "Gross profit", 71.1, "2022", metric_canonical="gross_profit", page=5),
        _obs("gp_2023", "Gross profit", 91.3, "2023", metric_canonical="gross_profit", page=5),
        _obs("gp_2024", "Gross profit", 191.9, "2024", metric_canonical="gross_profit", page=5),
    ]

    exec_summary = PresentationSlide(
        id="s_exec",
        slide_type="executive_summary",
        title="Executive Summary",
        message="Gross profit decreased over the track record period.",
        bullets=["Gross profit decreased from RMB 71.1m in 2022 to RMB 191.9m in 2024."],
        source_pages=[5],
    )

    analysis_slide = PresentationSlide(
        id="s_gp",
        slide_type="analysis",
        title="Gross Profit Expansion",
        message="Gross profit expanded strongly.",
        bullets=["Gross profit grew from 71.1 to 191.9."],
        observation_ids=["gp_2022", "gp_2023", "gp_2024"],
        source_pages=[5],
    )

    plan = PresentationPlan(title="Deck", slides=[exec_summary, analysis_slide])

    # 1. ClaimValidator directly validates executive summary against document observations
    validator = ClaimValidator()
    issues = validator.validate_plan(plan, obs)
    exec_issues = [i for i in issues if getattr(i, "slide_id", "") == "s_exec"]
    assert len(exec_issues) >= 1

    repaired_plan, repairs = repair_presentation_plan(plan, obs)
    assert "increased" in repaired_plan.slides[0].message
    assert "decreased" not in repaired_plan.slides[0].message

    # 2. CrossSlideValidator also repairs contradictory Executive Summary statements on an un-repaired plan
    unrepaired_exec = PresentationSlide(
        id="s_exec2",
        slide_type="executive_summary",
        title="Executive Summary",
        message="Gross profit decreased over the period.",
        bullets=["Gross profit decreased significantly."],
        source_pages=[5],
    )
    plan2 = PresentationPlan(title="Deck 2", slides=[unrepaired_exec, analysis_slide])
    cross_val = CrossSlideValidator(plan2, obs)
    qa_issues = cross_val.validate_and_repair(auto_repair=True)
    assert any("Gross profit" in i.message or "gross_profit" in i.message for i in qa_issues)
    assert "increased" in plan2.slides[0].message
    assert "decreased" not in plan2.slides[0].message


# ==============================================================================
# 3. Percentage / Ratio Direction (Rebound Series)
# ==============================================================================
def test_ratio_rebound_direction_validation_and_repair():
    """Series 14.8% -> 7.9% -> 9.3% must not be described as 'increased overall'."""
    obs = [
        _obs("gm_2022", "Gross margin", 14.8, "2022", metric_canonical="gross_margin", unit="percent", currency=None, page=8),
        _obs("gm_2023", "Gross margin", 7.9, "2023", metric_canonical="gross_margin", unit="percent", currency=None, page=8),
        _obs("gm_2024", "Gross margin", 9.3, "2024", metric_canonical="gross_margin", unit="percent", currency=None, page=8),
    ]

    # Net change is 14.8 -> 9.3 (decline)
    trend = determine_trend_state("Gross margin", 14.8, 9.3)
    assert trend == TrendState.DECREASED

    slide = PresentationSlide(
        id="s_gm",
        slide_type="analysis",
        title="Gross Margin Performance",
        message="Gross margin increased overall across the period.",
        bullets=["Gross margin increased from 14.8% to 9.3%."],
        observation_ids=["gm_2022", "gm_2023", "gm_2024"],
        source_pages=[8],
    )

    plan = PresentationPlan(title="Deck", slides=[slide])
    validator = ClaimValidator()
    issues = validator.validate_plan(plan, obs)
    assert any(isinstance(i, DirectionalClaimIssue) and i.expected_direction == "DECREASED" for i in issues)

    repaired_plan, repairs = repair_presentation_plan(plan, obs)
    repaired_text = repaired_plan.slides[0].message
    assert "declined overall, with a partial rebound" in repaired_text or "decreased" in repaired_text
    assert "increased" not in repaired_text

    # Formatter test
    formatted = FinancialMovementFormatter.format_movement(
        "Gross margin",
        14.8,
        9.3,
        values=[14.8, 7.9, 9.3],
        unit="percent",
    )
    assert "contracted overall by 5.5 pp, with a partial rebound" in formatted


# ==============================================================================
# 4. Margin Unit Classification
# ==============================================================================
def test_margin_metric_classification_and_normalization():
    """Gross margin, product gross margin, and margin ratios must use %, never currency or RMB."""
    assert is_margin_metric("Gross margin")
    assert is_margin_metric("Product-Line Gross Margins")
    assert is_margin_metric("Operating margin")

    sem = classify_metric("Product-Line Gross Margins", value=18.5)
    assert sem.is_percentage is True
    assert sem.is_currency is False
    assert sem.display_unit == "%"

    # Raw observation with erroneous currency unit from table header
    obs = _obs(
        "pm_1",
        "Product-Line Gross Margins",
        18.5,
        "2023",
        unit="currency",
        currency="RMB",
        display_unit="RMB",
    )
    normalized = FinancialNormalizer.normalize_observation(obs)
    assert normalized.unit == "percent"
    assert normalized.unit_family == "percentage"
    assert normalized.display_unit == "%"
    assert normalized.currency is None


# ==============================================================================
# 5. Known Operational Units
# ==============================================================================
def test_known_operational_units():
    """Turnover days -> 'days', multiples -> 'x', never 'unknown'."""
    assert is_days_metric("Inventory turnover days")
    assert is_days_metric("Trade receivables turnover days")

    obs_days = _obs(
        "dio_1",
        "Inventory turnover days",
        66.0,
        "2023",
        unit="unknown",
        currency=None,
    )
    normalized_days = FinancialNormalizer.normalize_observation(obs_days)
    assert normalized_days.unit == "days"
    assert normalized_days.display_unit == "days"

    unit_lbl = _unit_label([normalized_days], "")
    assert unit_lbl == "days"
    assert "unknown" not in unit_lbl

    disp_source = _display_source_unit(normalized_days)
    assert disp_source == "days"
    assert "unknown" not in disp_source

    # Multiple metric
    obs_ratio = _obs(
        "cr_1",
        "Current ratio",
        1.5,
        "2023",
        unit="multiple",
        currency=None,
    )
    normalized_ratio = FinancialNormalizer.normalize_observation(obs_ratio)
    assert normalized_ratio.unit == "multiple"
    assert normalized_ratio.display_unit == "x"
    assert _unit_label([normalized_ratio], "") == "x"


# ==============================================================================
# 6. Growth Calculations for Negative Expenses
# ==============================================================================
def test_negative_expense_growth_rate_and_cagr():
    """Growth calculations for expenses use absolute magnitude to avoid inverting financial meaning."""
    # R&D expenses: -95.9 -> -121.1 is an increase in spending
    pct = percentage_change(-95.9, -121.1, is_expense=True)
    assert pct == pytest.approx(26.277, rel=1e-3)
    assert pct > 0

    # Decrease in spending: -121.1 -> -95.9
    pct_dec = percentage_change(-121.1, -95.9, is_expense=True)
    assert pct_dec == pytest.approx(-20.809, rel=1e-3)
    assert pct_dec < 0

    # growth_rate wrapper
    gr = growth_rate(-95.9, -121.1, is_expense=True)
    assert gr == pytest.approx(26.277, rel=1e-3)

    # CAGR on expense magnitude
    cagr_val = cagr(-95.9, -121.1, 2, is_expense=True)
    assert cagr_val > 0
    assert cagr_val == pytest.approx(12.37, rel=1e-2)


# ==============================================================================
# 7. Title Generation and Polishing
# ==============================================================================
def test_title_polishing_eliminates_awkward_trajectory():
    """Slide titles must avoid awkward appending of 'Trajectory' and trailing prepositions."""
    t1 = polish_slide_title("R&D Expenses Held Broadly Flat Before Rising in Trajectory")
    assert t1 == "R&D Expenses Held Broadly Flat Before Rising"
    assert "Trajectory" not in t1

    t2 = polish_slide_title("Selling and Marketing Expenses Rose, With Trajectory")
    assert t2 == "Selling and Marketing Expenses Rose"
    assert "Trajectory" not in t2
    assert not t2.endswith(",")

    t3 = polish_slide_title("Robot Lawn Mowers Became a Material Revenue Trajectory")
    assert t3 == "Robot Lawn Mowers Became a Material Revenue Driver"

    # Natural concise title under 15 words
    long_t = "A Very Comprehensive Analysis of Operational Metrics and Customer Acquisitions Across Fiscal Years 2021 to 2024 with Further Context"
    polished_long = polish_slide_title(long_t)
    assert len(polished_long.split()) <= 15


# ==============================================================================
# 8. Appendix Title Alignment
# ==============================================================================
def test_appendix_title_realignment_when_no_offering_data():
    """Appendix titles must not mention Offering / Proceeds when no offering data exists."""
    obs = [
        _obs("rev_1", "Revenue", 100.0, "2023", page=1)
    ]

    from adaptive_document_agent.agent.presentation_plan_repairer import PresentationPlanRepairer

    plan = PresentationPlan(
        title="Test",
        slides=[
            PresentationSlide(
                id="app_1",
                slide_type="appendix",
                title="Offering and Use of Proceeds Detail",
                section_title="Offering and Use of Proceeds",
                observation_ids=["rev_1"],
                source_pages=[1],
            )
        ],
    )

    result = PipelineResult(
        document=ParsedDocument(
            document_id="doc_test",
            filename="test.pdf",
            safe_filename="test.pdf",
            sha256="abc12345",
            page_count=1,
        ),
        profile=DocumentProfile(
            document_id="doc_test",
            primary_language="en",
            page_count=1,
        ),
        observations=obs,
    )

    repaired = PresentationPlanRepairer().repair(plan, result)
    app_slide = repaired.slides[0]
    assert "Offering" not in app_slide.title
    assert "Proceeds" not in app_slide.title
    assert "Offering" not in app_slide.section_title
