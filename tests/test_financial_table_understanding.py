"""Comprehensive regression tests for financial table understanding and evidence pipeline.

Addresses requirements from Sections 33 to 39:
- Amount vs percentage column isolation (never 8,212%)
- Same label, different tables isolation (e.g. 'Others' in revenue vs expenses)
- Same metric, different categories (e.g. 'Gross profit' Mainland vs Overseas)
- Point-in-time balance sheet period semantics (2026-02-28 is not FY2026)
- Duplicate metric collision detection
- Chartability scoring and plausibility validation
- Category candidate single-period scoping
"""

from __future__ import annotations

import pytest

from adaptive_document_agent.agent.candidate_generator import AnalysisCandidateGenerator
from adaptive_document_agent.document_model import (
    DocumentIndex,
    best_period_series,
    metric_identity_key,
    metric_key,
    score_chartability,
)
from adaptive_document_agent.document_model.period_semantic_validator import (
    classify_period,
    format_period_label,
)
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.models import Observation, SourceEvidence
from adaptive_document_agent.models.table import ExtractedTable, TableRow


def test_amount_vs_percentage_column_isolation() -> None:
    """Section 34: Alternating amount and percentage columns must remain isolated."""
    # A financial breakdown table with alternating Amount (RMB'000) and % columns
    headers = ["Segment", "2023 Amount", "2023 %", "2024 Amount", "2024 %"]
    col_types = ["label", "amount", "percentage", "amount", "percentage"]
    col_currencies = [None, "RMB", None, "RMB", None]
    col_scales = [None, 1000.0, 1.0, 1000.0, 1.0]

    rows = [
        TableRow(cells=["Flexible robots", "8,212", "12.7", "16,064", "42.1"], page=45),
        TableRow(cells=["Sensors", "28,991", "22.2", "65,837", "46.4"], page=45),
    ]

    table = ExtractedTable(
        table_id="tbl_breakdown",
        page=45,
        headers=headers,
        column_periods=[None, "2023", "2023", "2024", "2024"],
        column_types=col_types,
        column_currencies=col_currencies,
        column_scales=col_scales,
        rows=rows,
        raw_cells=[[c for c in r.cells] for r in rows],
        default_unit="currency",
        default_currency="RMB",
        default_unit_scale=1000.0,
        default_raw_unit="RMB '000",
        confidence=0.9,
    )

    extractor = ObservationExtractor()
    obs = extractor._table_observations(table)

    # Verify that amount cells remain monetary and percentage cells remain percentages
    amount_obs = [o for o in obs if o.period == "2023" and "Flexible robots" in o.metric_original and o.unit_family == "currency"]
    pct_obs = [o for o in obs if o.period == "2023" and "Flexible robots" in o.metric_original and o.unit_family == "percentage"]

    assert len(amount_obs) == 1
    assert len(pct_obs) == 1

    # 8,212 must be scaled monetary amount, NEVER 8,212%
    rob_amount = amount_obs[0]
    assert rob_amount.value == 8_212_000.0
    assert rob_amount.unit == "currency"
    assert rob_amount.unit_family == "currency"
    assert rob_amount.currency == "RMB"
    assert rob_amount.validation_status == "valid"

    # 12.7 must be percentage, not scaled
    rob_pct = pct_obs[0]
    assert rob_pct.value == 12.7
    assert rob_pct.unit == "percent"
    assert rob_pct.unit_family == "percentage"
    assert rob_pct.currency is None
    assert rob_pct.validation_status == "valid"


def test_same_label_different_tables_isolation() -> None:
    """Section 35: Generic labels (e.g. 'Others') from different tables/sections must not merge."""
    obs_revenue_others = Observation(
        id="rev_others_23",
        metric_original="Others",
        value=6206.0,
        raw_value="6,206",
        period="FY2023",
        unit="currency",
        currency="RMB",
        unit_family="currency",
        parent_section="Revenue by Product",
        source_table="tbl_revenue",
        table_id="tbl_revenue",
        evidence=[SourceEvidence(page=101, text="6,206", table_id="tbl_revenue", extraction_method="digital_table", confidence=0.9)],
        confidence=0.9,
    )

    obs_expense_others = Observation(
        id="exp_others_23",
        metric_original="Others",
        value=95.0,
        raw_value="95",
        period="FY2023",
        unit="currency",
        currency="RMB",
        unit_family="currency",
        parent_section="Operating Expenses Breakdown",
        source_table="tbl_expenses",
        table_id="tbl_expenses",
        evidence=[SourceEvidence(page=150, text="95", table_id="tbl_expenses", extraction_method="digital_table", confidence=0.9)],
        confidence=0.9,
    )

    # Keys must be distinct because they belong to different sections/tables
    key_rev = metric_identity_key(obs_revenue_others)
    key_exp = metric_identity_key(obs_expense_others)
    assert key_rev != key_exp

    metric_name_rev = metric_key(obs_revenue_others)
    metric_name_exp = metric_key(obs_expense_others)
    assert metric_name_rev != metric_name_exp
    assert "revenue" in metric_name_rev
    assert "expenses" in metric_name_exp

    # best_period_series must NOT merge them into one 2-point series
    combined_series = best_period_series([obs_revenue_others, obs_expense_others], minimum_periods=2)
    assert len(combined_series) == 0


def test_same_metric_different_categories() -> None:
    """Section 36: Gross profit with different categories must retain metric and separate dimensions."""
    obs_mainland = Observation(
        id="gp_mainland_23",
        metric_original="Gross profit",
        value=28991.0,
        raw_value="28,991",
        period="FY2023",
        unit="currency",
        currency="RMB",
        unit_family="currency",
        category_dimensions={"geography": "Mainland"},
        dimensions={"geography": "Mainland"},
        evidence=[SourceEvidence(page=110, text="28,991", extraction_method="digital_table", confidence=0.9)],
        confidence=0.9,
    )

    obs_overseas = Observation(
        id="gp_overseas_23",
        metric_original="Gross profit",
        value=16064.0,
        raw_value="16,064",
        period="FY2023",
        unit="currency",
        currency="RMB",
        unit_family="currency",
        category_dimensions={"geography": "Overseas market"},
        dimensions={"geography": "Overseas market"},
        evidence=[SourceEvidence(page=110, text="16,064", extraction_method="digital_table", confidence=0.9)],
        confidence=0.9,
    )

    # Both must have the same metric
    assert obs_mainland.metric_original == "Gross profit"
    assert obs_overseas.metric_original == "Gross profit"

    # But different category dimensions
    assert obs_mainland.category_dimensions["geography"] == "Mainland"
    assert obs_overseas.category_dimensions["geography"] == "Overseas market"

    # Identities must differ due to category dimensions
    assert metric_identity_key(obs_mainland) != metric_identity_key(obs_overseas)


def test_point_in_time_balance_sheet_period() -> None:
    """Section 37: 2026-02-28 point-in-time date must not become FY2026."""
    sem = classify_period("2026-02-28", is_balance_sheet=True)
    assert sem.period_type == "balance_sheet_date"
    assert sem.as_of_date == "2026-02-28"
    assert sem.clean_label == "28 Feb 2026*"
    assert "FY2026" not in sem.clean_label
    assert format_period_label("2026-02-28", is_balance_sheet=True) == "28 Feb 2026*"

    # Explicit CJK date
    sem_cjk = classify_period("2026年2月28日", is_balance_sheet=True)
    assert sem_cjk.period_type == "balance_sheet_date"
    assert sem_cjk.as_of_date == "2026-02-28"
    assert sem_cjk.clean_label == "28 Feb 2026*"


def test_chartability_scoring() -> None:
    """Section 18 & 19: Comprehensive chartability evaluation."""
    ev = SourceEvidence(page=50, text="val", extraction_method="digital_table", confidence=0.9)

    # Valid coherent 3-year series
    valid_series = [
        Observation(id=f"rev_{yr}", metric_original="Revenue", value=float(yr * 10), raw_value=str(yr * 10), period=f"FY{yr}", unit="currency", unit_family="currency", currency="RMB", evidence=[ev], confidence=0.9)
        for yr in (2022, 2023, 2024)
    ]
    res_valid = score_chartability(valid_series)
    assert res_valid.is_chartable is True
    assert res_valid.status in ("HIGH", "MEDIUM")

    # Incoherent mixed unit series: currency + percent
    mixed_series = [
        Observation(id="o1", metric_original="Metric", value=100.0, raw_value="100", period="FY2022", unit="currency", unit_family="currency", evidence=[ev], confidence=0.9),
        Observation(id="o2", metric_original="Metric", value=20.0, raw_value="20%", period="FY2023", unit="percent", unit_family="percentage", evidence=[ev], confidence=0.9),
    ]
    res_mixed = score_chartability(mixed_series)
    assert res_mixed.is_chartable is False
    assert res_mixed.status == "INVALID"
    assert any("Mixed unit families" in r for r in res_mixed.reasons)

    # Implausible percentage value (e.g. 8212%)
    implausible_pct_series = [
        Observation(id="p1", metric_original="Margin", value=12.5, raw_value="12.5%", period="FY2022", unit="percent", unit_family="percentage", evidence=[ev], confidence=0.9),
        Observation(id="p2", metric_original="Margin", value=8212.0, raw_value="8212%", period="FY2023", unit="percent", unit_family="percentage", evidence=[ev], confidence=0.9),
    ]
    res_implausible = score_chartability(implausible_pct_series)
    assert res_implausible.is_chartable is False
    assert res_implausible.status == "INVALID"


def test_category_candidates_single_period_scope() -> None:
    """Section 21 & 22: Category ranking must scope strictly to a single period."""
    obs = [
        Observation(id="m_23", metric_original="Revenue", value=100.0, raw_value="100", period="FY2023", unit="currency", dimensions={"geography": "Mainland"}, confidence=0.9),
        Observation(id="o_23", metric_original="Revenue", value=50.0, raw_value="50", period="FY2023", unit="currency", dimensions={"geography": "Overseas"}, confidence=0.9),
        Observation(id="m_24", metric_original="Revenue", value=120.0, raw_value="120", period="FY2024", unit="currency", dimensions={"geography": "Mainland"}, confidence=0.9),
        Observation(id="o_24", metric_original="Revenue", value=70.0, raw_value="70", period="FY2024", unit="currency", dimensions={"geography": "Overseas"}, confidence=0.9),
    ]

    gen = AnalysisCandidateGenerator()
    candidates = gen._category_candidates("Revenue", "geography", obs)

    # Candidate titles must explicitly mention the single period and not mix periods
    titles = [c.title for c in candidates]
    assert any("(FY2023)" in t for t in titles)
    assert any("(FY2024)" in t for t in titles)

    # For any single candidate, its observation IDs must only span ONE period
    for cand in candidates:
        cand_obs = [o for o in obs if o.id in cand.observation_ids]
        periods_in_cand = {o.period for o in cand_obs}
        assert len(periods_in_cand) == 1, f"Candidate {cand.title} mixes periods: {periods_in_cand}"
