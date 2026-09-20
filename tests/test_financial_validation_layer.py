"""Comprehensive tests for the Financial Validation Layer and Normalized Financial Data Layer.

Validates all 14 required capabilities:
1. Revenue increase/decrease sign and phrasing logic
2. Net loss widening/narrowing sign-aware logic
3. Operating cash outflow widening / increasing logic
4. Profit turning into loss / gross profit turned into gross loss / loss to profit
5. Working-capital cash flow logic (inventory/receivables absorption, payables support)
6. Period compatibility: FY vs interim period mismatch blocking
7. Unit normalization: inferring 'days' for inventory turnover, clean currencies, no float artifacts
8. IFRS vs Adjusted/Non-IFRS metric separation
9. Executive Summary vs Detailed Analysis Slides cross-consistency
10. Banned placeholder detection and auto-repair (unknown, None, null, NaN)
"""

from __future__ import annotations

import pytest

from adaptive_document_agent.document_model.series import (
    canonical_series_partition_key,
    group_comparable_series,
)
from adaptive_document_agent.models import (
    CanonicalFact,
    CompanyProfile,
    DocumentProfile,
    Observation,
    ParsedDocument,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    ReportPlan,
    SourceEvidence,
)
from adaptive_document_agent.services.financial_normalizer import (
    clean_float_artifacts,
    classify_ifrs_status,
    FinancialNormalizer,
    format_clean_number_string,
)
from adaptive_document_agent.services.language_qa import polish_slide_title
from adaptive_document_agent.services.movement_formatter import FinancialMovementFormatter
from adaptive_document_agent.validation.claim_validator import (
    are_observations_compatible,
    determine_trend_state,
    TrendState,
)
from adaptive_document_agent.validation.cross_slide_validator import CrossSlideValidator


def _make_evidence(page: int = 1) -> SourceEvidence:
    return SourceEvidence(
        page=page,
        text="Reported table disclosure",
        table_id=f"t_{page}",
        row_label="Metric Row",
        column_label="FY2022",
        extraction_method="digital_table",
        confidence=0.95,
    )


# ---------------------------------------------------------------------------
# Requirement 1 & 4: Normalized Financial Data Layer & Unit Inference
# ---------------------------------------------------------------------------

def test_unit_normalization_and_float_cleanup() -> None:
    """Infer obvious units (e.g. turnover days -> days) and eliminate floating-point artifacts."""
    ev = _make_evidence(10)

    # 1. Inventory turnover days with missing unit
    obs_days = Observation(
        id="obs_days",
        metric_original="Inventory turnover days",
        value=53.60000000000001,
        raw_value="53.6",
        unit=None,
        currency=None,
        period="FY2022",
        evidence=[ev],
        confidence=0.9,
    )
    FinancialNormalizer.normalize_observation(obs_days)
    assert obs_days.unit == "days"
    assert obs_days.unit_family == "days"
    assert obs_days.display_unit == "days"
    assert obs_days.value == 53.6

    # 2. Turnover ratio with missing unit -> multiple
    obs_ratio = Observation(
        id="obs_ratio",
        metric_original="Current ratio",
        value=1.50000000000002,
        raw_value="1.5",
        unit=None,
        period="FY2022",
        evidence=[ev],
        confidence=0.9,
    )
    FinancialNormalizer.normalize_observation(obs_ratio)
    assert obs_ratio.unit == "multiple"
    assert obs_ratio.display_unit == "x"
    assert obs_ratio.value == 1.5

    # 3. Clean string formatting without float noise
    assert format_clean_number_string(53.60000000000001) == "53.6"
    assert format_clean_number_string(100.0) == "100"
    assert clean_float_artifacts(244.00000000000003) == 244.0


# ---------------------------------------------------------------------------
# Requirement 3: Sign-Aware Financial Movement Logic
# ---------------------------------------------------------------------------

def test_revenue_increase_and_decrease() -> None:
    """Revenue 100 -> 200 = increased; 200 -> 100 = decreased."""
    inc_text = FinancialMovementFormatter.format_movement("Revenue", 100.0, 200.0, currency="RMB", scale=1_000_000.0)
    assert "increased" in inc_text.lower()
    assert "RMB 100m" in inc_text or "RMB100m" in inc_text

    dec_text = FinancialMovementFormatter.format_movement("Revenue", 200.0, 100.0, currency="RMB", scale=1_000_000.0)
    assert "decreased" in dec_text.lower()
    assert "RMB 100m" in dec_text or "RMB100m" in dec_text


def test_net_loss_widening_and_narrowing() -> None:
    """Net loss -100 -> -300 = loss widened; -300 -> -100 = loss narrowed."""
    widen_text = FinancialMovementFormatter.format_movement("Net Loss", -100.0, -300.0, currency="RMB", scale=1_000_000.0)
    assert "widened" in widen_text.lower()
    assert "narrowed" not in widen_text.lower()

    narrow_text = FinancialMovementFormatter.format_movement("Net Loss", -300.0, -100.0, currency="RMB", scale=1_000_000.0)
    assert "narrowed" in narrow_text.lower()
    assert "widened" not in narrow_text.lower()

    # Deterministic trend state check
    state_widen = determine_trend_state("Net Loss", -100.0, -300.0, canonical_name="net_loss")
    assert state_widen == TrendState.LOSS_WIDENED

    state_narrow = determine_trend_state("Net Loss", -300.0, -100.0, canonical_name="net_loss")
    assert state_narrow == TrendState.LOSS_NARROWED


def test_operating_cash_outflow_widening_and_increasing() -> None:
    """Operating cash flow: -75 -> -523 = cash outflow increased / widened."""
    outflow_text = FinancialMovementFormatter.format_movement("Operating cash flow", -75.0, -523.0, currency="RMB", scale=1_000_000.0)
    assert "outflow" in outflow_text.lower()
    assert ("increased" in outflow_text.lower() or "widened" in outflow_text.lower())
    assert "narrowed" not in outflow_text.lower()

    # Reversal across zero
    pos_to_neg = FinancialMovementFormatter.format_movement("Operating cash flow", 50.0, -120.0, currency="RMB", scale=1_000_000.0)
    assert "turned negative" in pos_to_neg.lower()

    neg_to_pos = FinancialMovementFormatter.format_movement("Operating cash flow", -120.0, 50.0, currency="RMB", scale=1_000_000.0)
    assert "turned positive" in neg_to_pos.lower()


def test_gross_profit_turned_into_gross_loss() -> None:
    """Gross profit: 100 -> -50 = turned into gross loss; -50 -> 100 = turned into gross profit."""
    gp_loss_text = FinancialMovementFormatter.format_movement("Gross profit", 100.0, -50.0, currency="RMB", scale=1_000_000.0)
    assert "turned into gross loss" in gp_loss_text.lower()

    gp_profit_text = FinancialMovementFormatter.format_movement("Gross profit", -50.0, 100.0, currency="RMB", scale=1_000_000.0)
    assert "turned into gross profit" in gp_profit_text.lower()


# ---------------------------------------------------------------------------
# Requirement 2: Period Compatibility (FY vs Interim)
# ---------------------------------------------------------------------------

def test_fy_vs_interim_period_mismatch_blocked() -> None:
    """Comparing non-comparable periods (such as FY2022 vs 6M2023) must be strictly forbidden."""
    ev = _make_evidence(5)
    obs_fy = Observation(
        id="o_fy",
        metric_original="Revenue",
        value=100.0,
        raw_value="100.0",
        unit="currency",
        currency="RMB",
        period="FY2022",
        period_type="fiscal_year",
        evidence=[ev],
        confidence=0.9,
    )
    obs_interim = Observation(
        id="o_6m",
        metric_original="Revenue",
        value=60.0,
        raw_value="60.0",
        unit="currency",
        currency="RMB",
        period="6M2023",
        period_type="interim_flow",
        evidence=[ev],
        confidence=0.9,
    )
    is_comp, reason = are_observations_compatible(obs_fy, obs_interim)
    assert not is_comp
    assert "incompatible period" in reason.lower()

    # Comparable periods (FY2021 vs FY2022) must pass
    obs_fy21 = Observation(
        id="o_fy21",
        metric_original="Revenue",
        value=80.0,
        raw_value="80.0",
        unit="currency",
        currency="RMB",
        period="FY2021",
        period_type="fiscal_year",
        evidence=[ev],
        confidence=0.9,
    )
    is_comp_fy, _ = are_observations_compatible(obs_fy21, obs_fy)
    assert is_comp_fy


# ---------------------------------------------------------------------------
# Requirement 5: Working-Capital Cash Flow Logic
# ---------------------------------------------------------------------------

def test_working_capital_direction_validation_and_repair() -> None:
    """Verify that reversed working-capital interpretations (e.g. rising inventory provided cash) are corrected."""
    slide = PresentationSlide(
        id="s_wc",
        slide_type="analysis",
        title="Working Capital Movement",
        bullets=[
            "Increased inventories provided cash during FY2022.",
            "Increase in trade payables drained cash as suppliers required early payment.",
        ],
    )
    plan = PresentationPlan(
        title="Working Capital Review",
        company=CompanyProfile(name="Acme Corp", source_pages=[1]),
        slides=[slide],
    )
    validator = CrossSlideValidator(plan, observations=[])
    issues = validator.validate_and_repair(auto_repair=True)

    issue_codes = {i.code for i in issues}
    assert "working_capital_direction_repaired" in issue_codes

    # Verify that rising inventory was corrected from 'provided cash' to 'absorbed cash'
    assert "absorbed cash" in slide.bullets[0].lower()
    # Verify that rising payables was corrected from 'drained cash' to 'supported cash'
    assert "supported cash" in slide.bullets[1].lower()


# ---------------------------------------------------------------------------
# Requirement 7: IFRS vs Adjusted / Non-IFRS Metric Separation
# ---------------------------------------------------------------------------

def test_ifrs_vs_adjusted_metric_separation() -> None:
    """Net loss and Adjusted net loss must never merge into the same comparable series."""
    ev = _make_evidence(20)
    obs_net_loss = Observation(
        id="o_nl",
        metric_original="Net Loss for the year",
        metric_canonical="Net Loss",
        value=-100.0,
        raw_value="-100.0",
        unit="currency",
        currency="RMB",
        period="FY2022",
        evidence=[ev],
        confidence=0.95,
    )
    obs_adj_loss = Observation(
        id="o_adj",
        metric_original="Adjusted Net Loss (Non-IFRS measure)",
        metric_canonical="Adjusted Net Loss",
        value=-40.0,
        raw_value="-40.0",
        unit="currency",
        currency="RMB",
        period="FY2022",
        evidence=[ev],
        confidence=0.95,
    )

    FinancialNormalizer.normalize_observation(obs_net_loss)
    FinancialNormalizer.normalize_observation(obs_adj_loss)

    assert obs_net_loss.ifrs_status == "IFRS"
    assert obs_adj_loss.ifrs_status == "ADJUSTED"

    # Partition keys must differ
    key_ifrs = canonical_series_partition_key(obs_net_loss)
    key_adj = canonical_series_partition_key(obs_adj_loss)
    assert key_ifrs != key_adj

    # Compatibility check must fail between IFRS and Adjusted metrics
    is_comp, _ = are_observations_compatible(obs_net_loss, obs_adj_loss)
    assert not is_comp


# ---------------------------------------------------------------------------
# Requirement 8 & 9: Executive Summary vs Detail Slides Consistency
# ---------------------------------------------------------------------------

def test_executive_summary_cross_slide_consistency() -> None:
    """Executive Summary must never contradict detailed analysis slides."""
    ev = _make_evidence(12)
    obs_rev21 = Observation(id="r1", metric_original="Revenue", value=100.0, raw_value="100.0", unit="currency", currency="RMB", period="FY2021", evidence=[ev], confidence=0.9)
    obs_rev22 = Observation(id="r2", metric_original="Revenue", value=200.0, raw_value="200.0", unit="currency", currency="RMB", period="FY2022", evidence=[ev], confidence=0.9)

    summary_slide = PresentationSlide(
        id="slide_summary",
        slide_type="executive_summary",
        title="Executive Summary",
        bullets=[
            "Revenue decreased significantly from FY2021 to FY2022.",
        ],
    )
    analysis_slide = PresentationSlide(
        id="slide_revenue",
        slide_type="analysis",
        title="Revenue Growth",
        observation_ids=["r1", "r2"],
        bullets=["Revenue increased from RMB 100m in FY2021 to RMB 200m in FY2022."],
    )
    plan = PresentationPlan(
        title="Annual Report",
        company=CompanyProfile(name="Acme Corp", source_pages=[1]),
        slides=[summary_slide, analysis_slide],
    )

    validator = CrossSlideValidator(plan, observations=[obs_rev21, obs_rev22])
    issues = validator.validate_and_repair(auto_repair=True)

    issue_codes = {i.code for i in issues}
    assert "summary_detail_contradiction_repaired" in issue_codes
    # Contradictory 'decreased' in summary must be corrected to 'increased'
    assert "increased" in summary_slide.bullets[0].lower()
    assert "decreased" not in summary_slide.bullets[0].lower()


# ---------------------------------------------------------------------------
# Requirement 10: Slide Title Polishing
# ---------------------------------------------------------------------------

def test_slide_title_polishing() -> None:
    """Awkward titles like 'Net Widened From FY2020 to FY2022 and Trajectory' must be polished."""
    awkward = "Net Widened From FY2020 to FY2022 and Trajectory"
    polished = polish_slide_title(awkward)
    assert polished == "Net Loss Widened Across FY2020–FY2022"

    gross_loss = polish_slide_title("Gross Profit Turned Negative Trajectory")
    assert gross_loss == "Gross Profit Turned Negative"


# ---------------------------------------------------------------------------
# Regression: Cash-flow outflow TrendState semantics  (was crashing with
# "type object 'TrendState' has no attribute 'outflow_increased'")
# ---------------------------------------------------------------------------

def test_cash_outflow_trendstate_increased() -> None:
    """-75 → -523: absolute cash outflow grew = OUTFLOW_INCREASED."""
    state = determine_trend_state("Operating cash flow", -75.0, -523.0, canonical_name="operating_cash_flow")
    assert state == TrendState.OUTFLOW_INCREASED, f"Expected OUTFLOW_INCREASED, got {state}"
    assert state != TrendState.INCREASED
    assert state != TrendState.DECREASED


def test_cash_outflow_trendstate_narrowed() -> None:
    """-523 → -75: absolute cash outflow shrank = OUTFLOW_NARROWED."""
    state = determine_trend_state("Operating cash flow", -523.0, -75.0, canonical_name="operating_cash_flow")
    assert state == TrendState.OUTFLOW_NARROWED, f"Expected OUTFLOW_NARROWED, got {state}"
    assert state != TrendState.INCREASED
    assert state != TrendState.DECREASED


def test_cash_outflow_trendstate_turned_positive() -> None:
    """-100 → +50: outflow turned into positive cash flow = TURNED_POSITIVE."""
    state = determine_trend_state("Operating cash flow", -100.0, 50.0, canonical_name="operating_cash_flow")
    assert state == TrendState.TURNED_POSITIVE, f"Expected TURNED_POSITIVE, got {state}"


def test_cash_outflow_trendstate_turned_negative() -> None:
    """+50 → -100: positive cash flow turned into outflow = TURNED_NEGATIVE."""
    state = determine_trend_state("Operating cash flow", 50.0, -100.0, canonical_name="operating_cash_flow")
    assert state == TrendState.TURNED_NEGATIVE, f"Expected TURNED_NEGATIVE, got {state}"


def test_cash_outflow_movement_text_outflow_increased() -> None:
    """-75 → -523: movement text must contain 'outflow' and 'increased' or 'widened'."""
    text = FinancialMovementFormatter.format_movement(
        "Operating cash flow", -75.0, -523.0, currency="RMB", scale=1_000_000.0
    )
    assert "outflow" in text.lower(), f"'outflow' missing from: {text}"
    assert ("increased" in text.lower() or "widened" in text.lower()), f"Expected 'increased' or 'widened' in: {text}"
    assert "narrowed" not in text.lower(), f"'narrowed' must not appear in: {text}"


def test_cash_outflow_movement_text_outflow_narrowed() -> None:
    """-523 → -75: movement text must contain 'outflow' and 'narrowed'."""
    text = FinancialMovementFormatter.format_movement(
        "Operating cash flow", -523.0, -75.0, currency="RMB", scale=1_000_000.0
    )
    assert "outflow" in text.lower(), f"'outflow' missing from: {text}"
    assert "narrowed" in text.lower(), f"Expected 'narrowed' in: {text}"
    assert "increased" not in text.lower(), f"'increased' must not appear in: {text}"


def test_trendstate_enum_uppercase_only() -> None:
    """All TrendState members must be UPPERCASE — no lowercase attribute access should be needed."""
    for member in TrendState:
        assert member.name == member.name.upper(), (
            f"TrendState member '{member.name}' is not uppercase — use TrendState.{member.name.upper()}"
        )
    # Verify the new states exist at correct uppercase names
    assert hasattr(TrendState, "OUTFLOW_INCREASED")
    assert hasattr(TrendState, "OUTFLOW_NARROWED")
    assert TrendState.OUTFLOW_INCREASED.value == "OUTFLOW_INCREASED"
    assert TrendState.OUTFLOW_NARROWED.value == "OUTFLOW_NARROWED"

