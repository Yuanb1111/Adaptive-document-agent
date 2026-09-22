"""Regression tests for generic Adaptive Document Agent improvements based on PPT23.

Validates:
1. Company Identity: resolved company identity eliminates "issuer unnamed" contradictions.
2. Period Semantics: interim flow dates (e.g. six months ended 30 Jun 2021 -> 6M2021) and as at dates.
3. Liability Wording: standard liabilities use increase/decrease; only deficit/net liabilities use widened/narrowed.
4. Unit Inference: financial statement items inherit table currency/scale, never generic "units".
5. Slide Evidence Matching: slides about R&D do not group or show Gross Profit.
6. Period Comparability: rejects comparing FY2020 directly with 6M2021 as an annual trend.
"""

from __future__ import annotations

import pytest

from adaptive_document_agent.document_model.metric_semantic_classifier import (
    classify_metric,
    is_financial_statement_metric,
)
from adaptive_document_agent.document_model.period_semantic_validator import (
    are_periods_comparable,
    classify_period,
    extract_period_basis,
    format_period_label,
)
from adaptive_document_agent.document_model import DocumentIndex, best_period_series
from adaptive_document_agent.agent.executor import AnalysisExecutor
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.models import (
    AnalysisTask,
    ChartPlan,
    CompanyProfile,
    DocumentProfile,
    Observation,
    ParsedDocument,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    ReportPlan,
    SourceEvidence,
    ValidationIssue,
)
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.services.movement_formatter import FinancialMovementFormatter
from adaptive_document_agent.services.pptx_export import (
    _change_summary,
    _charts_belong_together,
    _display_source_unit,
    _filter_observations_by_slide_topic,
    _metrics_match_topic,
    _unit_label,
)
from adaptive_document_agent.services.qa_reporter import (
    sanitize_company_identity_contradictions,
)
from adaptive_document_agent.validation.claim_validator import (
    TrendState,
    are_observations_compatible,
    determine_trend_state,
)


def _obs(metric: str, value: float, period: str, *, canonical: str | None = None, unit: str = "currency", currency: str = "RMB", period_type: str = "generic") -> Observation:
    return Observation(
        id=f"obs_{metric}_{period}",
        metric_original=metric,
        metric_canonical=canonical or metric,
        raw_value=str(value),
        value=value,
        period=period,
        unit=unit,
        currency=currency,
        period_type=period_type,
        confidence=0.9,
        evidence=[SourceEvidence(page=10, text=f"{metric} {value}", extraction_method="test", confidence=0.9)],
    )


# ---------------------------------------------------------------------------
# 1. Company Identity Reconciliation
# ---------------------------------------------------------------------------
def test_company_identity_no_unnamed_contradiction():
    company = CompanyProfile(
        name="MicroPort Scientific Corporation",
        identity_state="RESOLVED",
        one_line_description="A medical technology company (prospectus for an unnamed issuer).",
    )
    slides = [
        PresentationSlide(
            id="slide_1",
            slide_type="analysis",
            title="Revenue Overview",
            message="Results for the issuer unnamed indicate steady expansion.",
            bullets=["The issuer name is not stated in section 3.", "Gross margin was stable."],
        ),
        PresentationSlide(
            id="slide_2",
            slide_type="executive_summary",
            title="Executive Summary",
            message="Analysis for the unidentified issuer.",
            bullets=["Issuer unknown at initial glance."],
        ),
    ]
    plan = PresentationPlan(
        title="Analysis Plan",
        slides=slides,
        company=company,
        sections=[],
    )
    profile = DocumentProfile(
        data_quality_notes=["The company name is not stated on page 4.", "Data quality note on scale."],
    )
    result = PipelineResult(
        document=ParsedDocument(
            document_id="doc_test_123",
            sha256="abc123def4567890",
            safe_filename="test_doc.pdf",
            page_count=20,
            pages=[],
        ),
        profile=profile,
        observations=[],
        insights=[],
        analysis_plan=[],
        analysis_results=[],
        charts=[],
        presentation_plan=plan,
        report_plan=ReportPlan(title="Report", sections=[]),
        validation_warnings=[
            ValidationIssue(code="unnamed_warning", message="Document is for an unnamed issuer.", stage="profile"),
            ValidationIssue(code="other_warning", message="Missing footnote.", stage="profile"),
        ],
    )

    fixes = sanitize_company_identity_contradictions(result)
    assert len(fixes) > 0

    # Contradictory unnamed phrases removed
    assert "unnamed issuer" not in company.one_line_description.casefold()
    assert "MicroPort Scientific Corporation" in company.one_line_description

    slide1 = result.presentation_plan.slides[0]
    assert "issuer unnamed" not in slide1.message.casefold()
    assert "MicroPort Scientific Corporation" in slide1.message
    assert len(slide1.bullets) == 1
    assert "Gross margin was stable." in slide1.bullets[0]

    slide2 = result.presentation_plan.slides[1]
    assert "unidentified issuer" not in slide2.message.casefold()
    assert len(slide2.bullets) == 0

    # Profile notes and validation warnings sanitized
    assert not any("company name is not stated" in n.casefold() for n in result.profile.data_quality_notes)
    assert not any("unnamed issuer" in w.message.casefold() for w in result.validation_warnings)

    # Titles use the same canonical identity state as the company overview.
    result.presentation_plan.title = "Prospectus for an unnamed issuer"
    slide1.title = "Unnamed issuer — Revenue Overview"
    sanitize_company_identity_contradictions(result)
    assert "unnamed" not in result.presentation_plan.title.casefold()
    assert "unnamed" not in slide1.title.casefold()


# ---------------------------------------------------------------------------
# 2. Period Semantics: Interim Flow & Balance Sheet Dates
# ---------------------------------------------------------------------------
def test_period_semantics_interim_and_balance_sheet():
    # Interim month flow statements
    assert format_period_label("six months ended 30 Jun 2021") == "6M2021"
    assert format_period_label("Six months ended June 30, 2021") == "6M2021"
    assert format_period_label("for the six months ended 30 June 2021") == "6M2021"
    assert format_period_label("6 months ended 30 Jun 2021") == "6M2021"
    assert format_period_label("three months ended 31 March 2021") == "3M2021"
    assert format_period_label("four months ended 30 April 2025") == "4M2025"
    assert format_period_label("截至2021年6月30日止六个月") == "6M2021"

    # Point-in-time balance sheet dates
    assert format_period_label("as at 31 Aug 2021", is_balance_sheet=True) == "31 Aug 2021"
    assert format_period_label("as of 31 August 2021", is_balance_sheet=True) == "31 Aug 2021"
    assert format_period_label("at 31 August 2021*", is_balance_sheet=True) == "31 Aug 2021*"
    assert format_period_label("30 April 2025", is_balance_sheet=True) == "30 Apr 2025"
    assert format_period_label("as at 31 Aug 2021", is_balance_sheet=False) == "31 Aug 2021"

    # Annual fiscal years remain FY
    assert format_period_label("FY2020") == "FY2020"
    assert format_period_label("2020") == "FY2020"

    # Basis classification
    assert extract_period_basis("6M2021") == "6M"
    assert extract_period_basis("six months ended 30 Jun 2021") == "6M"
    assert extract_period_basis("FY2020") == "FY"
    assert extract_period_basis("31 Aug 2021*") == "point_in_time"
    assert extract_period_basis("as at 31 Aug 2021") == "point_in_time"
    assert classify_period("six months ended 30 Jun 2021").period_type == "interim_flow"
    assert classify_period("six months ended 30 Jun 2021").as_of_date is None
    assert BorderlessTableExtractor._period_from_line("As at 31 August 2021") == "31 Aug 2021"


# ---------------------------------------------------------------------------
# 3. Liability Wording: Standard vs Deficit / Net Liabilities
# ---------------------------------------------------------------------------
def test_liability_wording_standard_vs_deficit():
    # Standard liabilities: 35.7 -> 121.2 must be "increased", NOT "widened"
    headline_inc = FinancialMovementFormatter.format_movement_headline("Current liabilities", 35.7, 121.2)
    assert "increased by" in headline_inc
    assert "widened" not in headline_inc

    headline_dec = FinancialMovementFormatter.format_movement_headline("Current liabilities", 121.2, 35.7)
    assert "decreased by" in headline_dec
    assert "narrowed" not in headline_dec

    headline_borrowings = FinancialMovementFormatter.format_movement_headline("Borrowings", 100.0, 250.0)
    assert "increased by" in headline_borrowings

    # Deficit / Net liabilities: magnitude semantics (widened / narrowed)
    headline_net_liab = FinancialMovementFormatter.format_movement_headline("Net current liabilities", -4.47, -6.62)
    assert "widened by" in headline_net_liab.casefold()
    assert "decreased" not in headline_net_liab.casefold()

    headline_net_liab_imp = FinancialMovementFormatter.format_movement_headline("Net current liabilities", -6.62, -4.47)
    assert "narrowed by" in headline_net_liab_imp.casefold()
    assert "increased" not in headline_net_liab_imp.casefold()

    headline_deficit = FinancialMovementFormatter.format_movement_headline("Shareholders' deficit", -100.0, -150.0)
    assert "widened by" in headline_deficit.casefold()

    # ClaimValidator trend states
    state_curr_liab = determine_trend_state("Current liabilities", 35.7, 121.2)
    assert state_curr_liab == TrendState.INCREASED

    state_net_curr = determine_trend_state("Net current liabilities", -4.47, -6.62)
    assert state_net_curr == TrendState.DEFICIT_WIDENED


# ---------------------------------------------------------------------------
# 4. Unit Inference for Financial Statement Line Items
# ---------------------------------------------------------------------------
def test_unit_inference_financial_statement_items():
    items = [
        "Trade and other receivables",
        "Non-current liabilities",
        "Total assets",
        "Cash and bank balances",
        "Share capital",
        "Current liabilities",
        "Selling and distribution expenses",
        "Trade payables",
    ]
    for item in items:
        assert is_financial_statement_metric(item) is True
        sem = classify_metric(item)
        assert sem.is_currency is True
        assert sem.unit_family == "currency"

    # Ratios and percentages should not be financial statement currency items
    assert is_financial_statement_metric("Gross profit margin") is False
    assert is_financial_statement_metric("R&D expense ratio") is False
    assert is_financial_statement_metric("Gearing ratio") is False

    # Formatting unit labels
    obs_fin = _obs("Trade and other receivables", 1500.0, "FY2020", currency="USD")
    assert _unit_label([obs_fin], "millions") == "US$ millions"

    obs_unknown = _obs("Other non-current assets", 10.0, "FY2020", unit="unknown", currency="")
    assert _unit_label([obs_unknown], "unknown") == "unknown"

    # Financial statement items should never display generic "units"
    assert _display_source_unit(obs_fin) != "units"

    # The extraction path inherits an explicitly stated table currency/scale,
    # even when the source column was generically classified as a count.
    table = ExtractedTable(
        table_id="statement_position",
        page=8,
        headers=["Item", "FY2020"],
        column_periods=[None, "FY2020"],
        column_types=["unknown", "count"],
        column_currencies=[None, "USD"],
        column_scales=[None, 1_000_000.0],
        default_unit="currency",
        default_raw_unit="USD in millions",
        default_unit_scale=1_000_000.0,
        default_currency="USD",
        rows=[TableRow(cells=["Trade and other receivables", "1.5"], page=8)],
        confidence=0.95,
    )
    extracted = ObservationExtractor()._table_observations(table)
    assert len(extracted) == 1
    assert extracted[0].unit == "currency"
    assert extracted[0].currency == "USD"
    assert extracted[0].unit_scale == 1_000_000.0
    assert extracted[0].value == 1_500_000.0
    assert extracted[0].display_unit != "units"


# ---------------------------------------------------------------------------
# 5. Slide Evidence Matching & Strict Chart Cohesion
# ---------------------------------------------------------------------------
def test_slide_evidence_matching_no_unrelated_rows():
    obs_rd = _obs("Research and development expenses", 282.0, "FY2020", canonical="R&D Expenses")
    obs_gp = _obs("Gross profit", 950.0, "FY2020", canonical="Gross Profit")

    # Metrics match topic
    assert _metrics_match_topic(obs_rd, "r&d expenses", "R&D Expense Trajectory") is True
    assert _metrics_match_topic(obs_gp, "r&d expenses", "R&D Expense Trajectory") is False

    # Slide topic filtering
    filtered = _filter_observations_by_slide_topic([obs_rd, obs_gp], "R&D Expense Trajectory")
    assert len(filtered) == 1
    assert filtered[0].metric_original == "Research and development expenses"

    # Validation of chart metrics against slide topic
    assert _metrics_match_topic(obs_rd, "r&d expenses", "R&D Expenses") is True
    assert _metrics_match_topic(obs_gp, "r&d expenses", "R&D Expenses") is False


def test_slide_topic_mismatch_remains_an_export_blocker():
    obs_rd = _obs("Research and development expenses", 282.0, "FY2020", canonical="R&D Expenses")
    obs_gp = _obs("Gross profit", 950.0, "FY2020", canonical="Gross Profit")
    chart = ChartPlan(
        id="chart_rd",
        title="R&D Expenses",
        chart_type="bar",
        question="How did R&D expenses change?",
        observation_ids=[obs_rd.id, obs_gp.id],
    )
    plan = PresentationPlan(
        title="Analysis",
        company=CompanyProfile(),
        slides=[PresentationSlide(
            id="slide_rd",
            slide_type="analysis",
            title="R&D Expense Trajectory",
            chart_ids=[chart.id],
            observation_ids=[obs_rd.id, obs_gp.id],
        )],
    )
    result = PipelineResult(
        document=ParsedDocument(document_id="doc", sha256="abc123def4567890", safe_filename="test.pdf", page_count=10, pages=[]),
        profile=DocumentProfile(), observations=[obs_rd, obs_gp], insights=[], analysis_plan=[],
        analysis_results=[], charts=[chart], presentation_plan=plan,
        report_plan=ReportPlan(title="Report", sections=[]), validation_warnings=[],
    )
    from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa

    qa = run_comprehensive_qa(result)
    assert qa.is_export_blocked is True
    assert {item.code for item in qa.critical_errors} >= {"slide_topic_mismatch", "chart_topic_mismatch"}


# ---------------------------------------------------------------------------
# 6. Period Comparability: Reject Comparing FY with 6M
# ---------------------------------------------------------------------------
def test_period_comparability_rejects_fy_vs_6m():
    # Basis comparability
    comp, reason = are_periods_comparable("FY2020", "6M2021")
    assert comp is False
    assert "Incompatible period basis" in reason

    assert are_periods_comparable("6M2020", "6M2021")[0] is True
    assert are_periods_comparable("FY2019", "FY2020")[0] is True

    # ClaimValidator rejects comparing FY2020 with 6M2021
    obs_fy = _obs("Revenue", 1000.0, "FY2020", canonical="Revenue")
    obs_6m = _obs("Revenue", 600.0, "6M2021", canonical="Revenue")
    is_compat, msg = are_observations_compatible(obs_fy, obs_6m)
    assert is_compat is False
    assert "Incompatible period basis" in msg

    # Compatible 6M vs 6M passes
    obs_6m_prior = _obs("Revenue", 500.0, "6M2020", canonical="Revenue")
    is_compat_6m, _ = are_observations_compatible(obs_6m_prior, obs_6m)
    assert is_compat_6m is True

    # Change summary on mixed periods: only compares compatible periods
    obs_2018 = _obs("Revenue", 800.0, "FY2018", canonical="Revenue")
    obs_2019 = _obs("Revenue", 900.0, "FY2019", canonical="Revenue")
    obs_2020 = _obs("Revenue", 1000.0, "FY2020", canonical="Revenue")
    obs_2021_6m = _obs("Revenue", 600.0, "6M2021", canonical="Revenue")

    summary = _change_summary([obs_2018, obs_2019, obs_2020, obs_2021_6m], 1.0)
    assert summary is not None
    headline, detail = summary
    # Must compare FY2018 to FY2020, NOT FY2018 to 6M2021!
    assert "FY2018" in detail
    assert "FY2020" in detail
    assert "6M2021" not in detail
    assert "increased by" in headline

    # Generic/legacy period_type values must still be split by duration.
    compatible_series = best_period_series([obs_2018, obs_2019, obs_2020, obs_2021_6m])
    assert [item.period for item in compatible_series] == ["FY2018", "FY2019", "FY2020"]

    # The deterministic executor also blocks a hand-built invalid task, so an
    # LLM or imported plan cannot bypass period compatibility.
    task = AnalysisTask(
        id="mixed_period_growth",
        title="Revenue growth",
        description="Compare revenue periods",
        analysis_type="percentage_change",
        required_metrics=["Revenue"],
        observation_query={"observation_ids": [obs_fy.id, obs_6m.id]},
        reason="Two reported periods are present.",
        expected_output="percentage",
    )
    executed = AnalysisExecutor().execute([task], DocumentIndex([obs_fy, obs_6m]))[0]
    assert executed.result is None
    assert any("incompatible periods" in warning for warning in executed.warnings)
