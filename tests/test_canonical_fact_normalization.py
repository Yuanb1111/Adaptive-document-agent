"""Regression tests for PPT19 issues and canonical fact normalization."""

import pytest

from adaptive_document_agent.document_model.period_semantic_validator import (
    classify_period,
    format_period_label,
)
from adaptive_document_agent.extraction.normalizer import (
    infer_unit_defaults,
    normalize_financial_fact,
)
from adaptive_document_agent.extraction.numeric_parser import parse_number
from adaptive_document_agent.models import CanonicalFact, Observation, SourceEvidence
from adaptive_document_agent.services.financial_formatter import (
    format_compact_currency,
    format_financial_movement,
)
from adaptive_document_agent.services.pptx_export import (
    _appendix_display_unit,
    _appendix_display_value,
)


def test_regression_negative_92m_not_92bn():
    """Regression test: -92,237 RMB'000 must normalize to -92.237m and display as -RMB 92.2m, NEVER -RMB 92.2bn."""
    norm_val, norm_unit, disp_val, disp_unit, curr = normalize_financial_fact(
        "-92,237",
        raw_unit="RMB '000",
    )
    assert norm_val == -92_237_000.0
    assert norm_unit == "currency"
    assert curr == "CNY"
    # Compact currency display must be -RMB 92.2m, NEVER -RMB 92.2bn
    assert disp_val == "-RMB 92.2m"
    assert "bn" not in disp_val

    # Also test format_compact_currency directly with base value
    direct_disp = format_compact_currency(-92_237_000.0, raw_unit="RMB '000", is_base_value=True)
    assert direct_disp == "-RMB 92.2m"
    assert "bn" not in direct_disp

    # Also test format_financial_movement with base values
    movement = format_financial_movement(
        "Operating Loss",
        start_val=-150_000_000.0,
        end_val=-92_237_000.0,
        currency="RMB",
    )
    assert "Loss narrowed" in movement
    assert "bn" not in movement
    assert "57.8m" in movement or "92.2m" in movement


def test_regression_256m_not_256k_million():
    """Regression test: 256,548 RMB'000 must be 256.5m, NEVER 256,548 RMB million in appendix."""
    norm_val, norm_unit, disp_val, disp_unit, curr = normalize_financial_fact(
        "256,548",
        raw_unit="RMB '000",
    )
    assert norm_val == 256_548_000.0
    assert norm_unit == "currency"
    assert curr == "CNY"
    assert disp_val == "RMB 256.5m"

    # Appendix rendering: value divided by 1,000,000 to display under RMB million
    ev = SourceEvidence(page=1, text="256,548", extraction_method="digital_table", confidence=0.9)
    obs = Observation(
        id="obs_rev",
        metric_original="Revenue",
        value=256_548_000.0,
        raw_value="256,548",
        unit="currency",
        raw_unit="RMB '000",
        unit_scale=1000.0,
        currency="CNY",
        period="FY2024",
        evidence=[ev],
        confidence=0.9,
    )
    from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric
    sem = classify_metric("Revenue", value=obs.value, raw_unit=obs.raw_unit, unit=obs.unit)

    unit_header = _appendix_display_unit(obs, sem)
    val_cell = _appendix_display_value(obs, sem)

    assert unit_header == "RMB million"
    # Value cell is in millions (e.g. 257 or 256.5), NEVER raw 256,548 under RMB million!
    assert val_cell in {"256.5", "257", "256.55"}
    assert "256,548" not in val_cell
    assert "256548" not in val_cell


def test_regression_point_in_time_not_fy():
    """Regression test: 'As at 30 Apr 2025' is a point-in-time date, NEVER automatically FY2025."""
    sem_pit = classify_period("As at 30 Apr 2025", is_balance_sheet=False)
    assert sem_pit.period_type == "point_in_time"
    assert sem_pit.clean_label == "30 Apr 2025"
    assert sem_pit.as_of_date == "2025-04-30"
    assert "FY" not in sem_pit.clean_label

    sem_bs = classify_period("As at 30 Apr 2025", is_balance_sheet=True)
    assert sem_bs.period_type == "balance_sheet_date"
    assert "30 Apr 2025" in sem_bs.clean_label
    assert "FY" not in sem_bs.clean_label

    # Also test "30 April 2025"
    sem_text = classify_period("30 April 2025")
    assert sem_text.period_type == "point_in_time"
    assert sem_text.clean_label == "30 Apr 2025"
    assert "FY" not in sem_text.clean_label


def test_unit_conversion_suite():
    """Test deterministic conversion for thousand, million, billion, %, pp, bps, x."""
    # 1. Thousand
    p_k = parse_number("500 thousand")
    assert p_k.value == 500_000.0
    assert p_k.scale == 1_000.0

    # 2. Million
    p_m = parse_number("12.5 million")
    assert p_m.value == 12_500_000.0
    assert p_m.scale == 1_000_000.0

    # 3. Billion
    p_b = parse_number("3.2 billion")
    assert p_b.value == 3_200_000_000.0
    assert p_b.scale == 1_000_000_000.0

    # 4. Percentage
    p_pct = parse_number("15.8%")
    assert p_pct.value == 15.8
    assert p_pct.unit == "percent"

    # 5. Percentage Points (pp)
    p_pp = parse_number("+3.2 pp")
    assert p_pp.value == 3.2
    assert p_pp.unit == "percentage_points"
    assert p_pp.raw_unit == "pp"

    # 6. Basis Points (bps)
    p_bps = parse_number("125 bps")
    assert p_bps.value == 125.0
    assert p_bps.unit == "basis_points"
    assert p_bps.raw_unit == "bps"

    # 7. Multiple (x)
    p_x = parse_number("2.5x")
    assert p_x.value == 2.5
    assert p_x.unit == "multiple"
    assert p_x.raw_unit == "x"


def test_canonical_fact_creation_from_observation():
    """Test creating a CanonicalFact from an Observation."""
    ev = SourceEvidence(page=18, text="RMB 92,237", extraction_method="digital_table", confidence=0.95)
    obs = Observation(
        id="fact_test_1",
        metric_original="Selling and distribution expenses",
        metric_canonical="Selling Expenses",
        value=92_237_000.0,
        raw_value="92,237",
        unit="currency",
        raw_unit="RMB '000",
        unit_scale=1000.0,
        currency="CNY",
        period="FY2024",
        presentation_label="Selling & Distribution",
        display_value="RMB 92.2m",
        display_unit="RMB million",
        normalized_value=92_237_000.0,
        normalized_unit="currency",
        period_type="fiscal_year",
        evidence=[ev],
        confidence=0.95,
        validation_status="valid",
    )
    fact = CanonicalFact.from_observation(obs)
    assert fact.id == "fact_test_1"
    assert fact.raw_metric_name == "Selling and distribution expenses"
    assert fact.canonical_metric_name == "Selling Expenses"
    assert fact.presentation_label == "Selling & Distribution"
    assert fact.raw_value == "92,237"
    assert fact.raw_unit == "RMB '000"
    assert fact.normalized_value == 92_237_000.0
    assert fact.normalized_unit == "currency"
    assert fact.display_value == "RMB 92.2m"
    assert fact.currency == "CNY"
    assert fact.source_page == 18
    assert fact.source_excerpt == "RMB 92,237"
    assert fact.period_type == "fiscal_year"
