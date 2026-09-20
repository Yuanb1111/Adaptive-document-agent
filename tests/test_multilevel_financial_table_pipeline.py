"""Regression tests for multi-level financial table header reconstruction,
observation extraction, Amount vs Percentage separation, and chart planning.
"""

from __future__ import annotations

import pytest

from adaptive_document_agent.agent.chart_planner import ChartPlanner
from adaptive_document_agent.document_model import (
    DocumentIndex,
    DocumentModelBuilder,
    best_period_series,
    group_comparable_series,
    metric_key,
    score_chartability,
)
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor
from adaptive_document_agent.models import (
    AnalysisResult,
    AnalysisTask,
    DocumentProfile,
    Insight,
    Observation,
    ParsedDocument,
    PipelineResult,
    SourceEvidence,
)
from adaptive_document_agent.models.document import DocumentPage
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer


def _create_generic_3yr_raw_table() -> list[list[str | None]]:
    return [
        ["", "2023", "", "2024", "", "2025", ""],
        ["", "Amount", "%", "Amount", "%", "Amount", "%"],
        ["Revenue", "100,000", "100.0", "150,000", "100.0", "220,000", "100.0"],
        ["Cost of sales", "-60,000", "-60.0", "-80,000", "-53.3", "-110,000", "-50.0"],
        ["Gross profit", "40,000", "40.0", "70,000", "46.7", "110,000", "50.0"],
        ["Net loss", "-20,000", "-20.0", "-15,000", "-10.0", "-5,000", "-2.3"],
        ["Operating cash flow", "-75,000", "-75.0", "-523,000", "-348.7", "120,000", "54.5"],
    ]


def test_multilevel_financial_table_header_reconstruction() -> None:
    """Requirement 1, 2: Multi-level financial table headers reconstructed with correct periods and roles."""
    raw = _create_generic_3yr_raw_table()
    headers, periods, data_rows, col_types, col_currs, col_scales = (
        TableReconstructor.reconstruct_multi_tier_headers(
            raw,
            default_unit="currency",
            default_currency="USD",
            default_scale=1000.0,
            context="Year ended December 31",
        )
    )

    # 1. Periods correctly propagated to both Amount and % columns
    assert periods == [None, "2023", "2023", "2024", "2024", "2025", "2025"]

    # 2. Column types correctly separate Amount and Percentage
    assert col_types == ["label", "amount", "percentage", "amount", "percentage", "amount", "percentage"]

    # 3. Currencies set for amount columns, None for percentages
    assert col_currs == [None, "USD", None, "USD", None, "USD", None]

    # 4. Scales set for amount columns, 1.0 for percentages
    assert col_scales == [None, 1000.0, 1.0, 1000.0, 1.0, 1000.0, 1.0]

    # 5. Data rows contain the 5 metric rows
    assert len(data_rows) == 5
    assert data_rows[0][0] == "Revenue"
    assert data_rows[4][0] == "Operating cash flow"


def test_multilevel_table_observations_amount_vs_percentage_separation() -> None:
    """Requirement 2, 3: Amount and percentage columns produce isolated, typed observations."""
    raw = _create_generic_3yr_raw_table()
    reconstructor = TableReconstructor()
    headers, periods, data_rows, col_types, col_currs, col_scales = (
        reconstructor.reconstruct_multi_tier_headers(
            raw,
            default_unit="currency",
            default_currency="USD",
            default_scale=1000.0,
            context="Consolidated Statement of Profit or Loss",
        )
    )

    table = ExtractedTable(
        table_id="tbl_fin_3yr",
        page=12,
        headers=headers,
        column_periods=periods,
        column_types=col_types,
        column_currencies=col_currs,
        column_scales=col_scales,
        rows=[TableRow(cells=r, page=12, column_periods=periods) for r in data_rows],
        raw_cells=raw,
        default_unit="currency",
        default_currency="USD",
        default_unit_scale=1000.0,
        confidence=0.92,
        context_label="Statement of Profit or Loss and Cash Flows",
    )

    extractor = ObservationExtractor()
    obs = extractor._table_observations(table)
    obs = FinancialNormalizer.normalize_observations(obs, default_currency="USD")

    # Group by metric
    by_metric: dict[str, list[Observation]] = {}
    for item in obs:
        by_metric.setdefault(item.metric_original, []).append(item)

    # 1. Revenue Amount: 3 points, currency, scaled 100,000 * 1000 = 100,000,000
    assert "Revenue" in by_metric
    rev_amounts = sorted(by_metric["Revenue"], key=lambda o: o.period or "")
    assert len(rev_amounts) == 3
    assert [o.period for o in rev_amounts] == ["2023", "2024", "2025"]
    assert [o.value for o in rev_amounts] == [100_000_000.0, 150_000_000.0, 220_000_000.0]
    assert all(o.unit_family == "currency" for o in rev_amounts)
    assert all(o.currency in {"USD", "US$"} for o in rev_amounts)

    # 2. Revenue %: separate metric name, 3 points, unscaled 100.0%, currency is None
    assert "Revenue %" in by_metric
    rev_pcts = sorted(by_metric["Revenue %"], key=lambda o: o.period or "")
    assert len(rev_pcts) == 3
    assert [o.value for o in rev_pcts] == [100.0, 100.0, 100.0]
    assert all(o.unit_family == "percentage" for o in rev_pcts)
    assert all(o.currency is None for o in rev_pcts)

    # 3. Gross profit Amount: 3 points, currency
    assert "Gross profit" in by_metric
    gp_amounts = sorted(by_metric["Gross profit"], key=lambda o: o.period or "")
    assert len(gp_amounts) == 3
    assert [o.value for o in gp_amounts] == [40_000_000.0, 70_000_000.0, 110_000_000.0]
    assert all(o.unit_family == "currency" for o in gp_amounts)

    # 4. Gross profit margin: separate metric name, 3 points, percentages
    assert "Gross profit margin" in by_metric
    gp_margins = sorted(by_metric["Gross profit margin"], key=lambda o: o.period or "")
    assert len(gp_margins) == 3
    assert [o.value for o in gp_margins] == [40.0, 46.7, 50.0]
    assert all(o.unit_family == "percentage" for o in gp_margins)
    assert all(o.currency is None for o in gp_margins)

    # 5. Net loss Amount: negative amounts, currency
    assert "Net loss" in by_metric
    loss_amounts = sorted(by_metric["Net loss"], key=lambda o: o.period or "")
    assert len(loss_amounts) == 3
    assert [o.value for o in loss_amounts] == [-20_000_000.0, -15_000_000.0, -5_000_000.0]

    # 6. Operating cash flow: cash flow amounts, currency
    assert "Operating cash flow" in by_metric
    cf_amounts = sorted(by_metric["Operating cash flow"], key=lambda o: o.period or "")
    assert len(cf_amounts) == 3
    assert [o.value for o in cf_amounts] == [-75_000_000.0, -523_000_000.0, 120_000_000.0]


def test_multilevel_financial_series_grouping_and_chartability() -> None:
    """Requirement 4, 6, 8: Verified metrics pass strict chartability without weakening checks."""
    raw = _create_generic_3yr_raw_table()
    headers, periods, data_rows, col_types, col_currs, col_scales = (
        TableReconstructor.reconstruct_multi_tier_headers(
            raw,
            default_unit="currency",
            default_currency="USD",
            default_scale=1000.0,
        )
    )
    table = ExtractedTable(
        table_id="tbl_fin_3yr",
        page=12,
        headers=headers,
        column_periods=periods,
        column_types=col_types,
        column_currencies=col_currs,
        column_scales=col_scales,
        rows=[TableRow(cells=r, page=12, column_periods=periods) for r in data_rows],
        raw_cells=raw,
        default_unit="currency",
        default_currency="USD",
        default_unit_scale=1000.0,
        confidence=0.92,
    )
    obs = ObservationExtractor()._table_observations(table)
    obs = FinancialNormalizer.normalize_observations(obs, default_currency="USD")
    index = DocumentModelBuilder().build(obs)

    # Test each key financial metric series
    for metric_name in ["revenue", "gross profit", "gross profit margin", "net loss", "operating cash flow"]:
        metric_obs = index.for_metric(metric_name)
        assert len(metric_obs) == 3, f"Expected 3 observations for {metric_name}, got {len(metric_obs)}"

        series = best_period_series(metric_obs, minimum_periods=3)
        assert len(series) == 3, f"Expected best_period_series to retain 3 periods for {metric_name}"

        # Strict chartability evaluation must succeed with HIGH status
        res = score_chartability(series)
        assert res.is_chartable is True, f"Series for {metric_name} failed chartability: {res.reasons}"
        assert res.status == "HIGH", f"Expected HIGH chartability status for {metric_name}, got {res.status}"


def test_multilevel_financial_table_chart_planner_generates_charts() -> None:
    """Requirement 8: ChartPlanner generates multi-period charts for Revenue, Gross Profit, Net Loss, Cash Flow."""
    raw = _create_generic_3yr_raw_table()
    headers, periods, data_rows, col_types, col_currs, col_scales = (
        TableReconstructor.reconstruct_multi_tier_headers(
            raw,
            default_unit="currency",
            default_currency="USD",
            default_scale=1000.0,
        )
    )
    table = ExtractedTable(
        table_id="tbl_fin_3yr",
        page=12,
        headers=headers,
        column_periods=periods,
        column_types=col_types,
        column_currencies=col_currs,
        column_scales=col_scales,
        rows=[TableRow(cells=r, page=12, column_periods=periods) for r in data_rows],
        raw_cells=raw,
        default_unit="currency",
        default_currency="USD",
        default_unit_scale=1000.0,
        confidence=0.92,
    )
    obs = ObservationExtractor()._table_observations(table)
    obs = FinancialNormalizer.normalize_observations(obs, default_currency="USD")
    index = DocumentModelBuilder().build(obs)

    planner = ChartPlanner()
    charts = planner.plan([], [], index, preferred_metrics=["Revenue", "Gross profit", "Net loss", "Operating cash flow"])

    # Must produce multiple chart-grade plans
    assert len(charts) >= 4, f"Expected at least 4 charts, got {len(charts)}"

    chart_metrics = {c.x_metric.casefold() for c in charts if c.x_metric}
    assert "revenue" in chart_metrics
    assert "gross profit" in chart_metrics
    assert "net loss" in chart_metrics
    assert "operating cash flow" in chart_metrics


def test_multilevel_table_with_none_cells_and_super_header() -> None:
    """Requirement 1, 4: Table with None merged cells and a super-header row reconstructs cleanly."""
    raw_with_nones = [
        ["For the year ended December 31,", None, None, None, None, None, None],
        [None, "2023", None, "2024", None, "2025", None],
        [None, "Amount", "%", "Amount", "%", "Amount", "%"],
        ["Revenue", "100,000", "100.0", "150,000", "100.0", "220,000", "100.0"],
        ["Gross profit", "40,000", "40.0", "70,000", "46.7", "110,000", "50.0"],
    ]

    reconstructor = TableReconstructor()
    headers, periods, data_rows, col_types, col_currs, col_scales = (
        reconstructor.reconstruct_multi_tier_headers(
            raw_with_nones,
            default_unit="currency",
            default_currency="EUR",
            default_scale=1.0,
            context="Income statement",
        )
    )

    assert periods == [None, "2023", "2023", "2024", "2024", "2025", "2025"]
    assert col_types == ["label", "amount", "percentage", "amount", "percentage", "amount", "percentage"]
    assert len(data_rows) == 2
    assert data_rows[0][0] == "Revenue"
    assert data_rows[1][0] == "Gross profit"


def test_table_reconstructor_reconstruct_repairs_unaligned_table() -> None:
    """Requirement 4: TableReconstructor.reconstruct repairs tables with missing periods and unknown types."""
    raw = _create_generic_3yr_raw_table()
    # Construct table with missing column_periods and empty column_types
    broken_table = ExtractedTable(
        table_id="tbl_broken",
        page=5,
        headers=["label", "col2", "col3", "col4", "col5", "col6", "col7"],
        column_periods=[None, "2023", None, "2024", None, "2025", None],
        column_types=[],
        rows=[
            TableRow(cells=raw[1], page=5),
            TableRow(cells=raw[2], page=5),
            TableRow(cells=raw[3], page=5),
            TableRow(cells=raw[4], page=5),
            TableRow(cells=raw[5], page=5),
            TableRow(cells=raw[6], page=5),
        ],
        raw_cells=raw,
        default_unit="currency",
        default_currency="USD",
        default_unit_scale=1000.0,
    )

    reconstructor = TableReconstructor()
    repaired = reconstructor.reconstruct(broken_table)

    # Must be repaired with complete periods and column types
    assert repaired.column_periods == [None, "2023", "2023", "2024", "2024", "2025", "2025"]
    assert repaired.column_types == ["label", "amount", "percentage", "amount", "percentage", "amount", "percentage"]
    assert len(repaired.rows) == 5  # Sub-header trimmed from data rows
    assert repaired.rows[0].cells[0] == "Revenue"


def test_financial_table_recovery_pass_when_charts_zero() -> None:
    """Requirement 5: Trigger financial-table recovery pass when narrative claims exist but charts == 0."""
    raw = _create_generic_3yr_raw_table()
    # Simulate an initially un-reconstructed table where column_periods were missing
    unreconstructed_table = ExtractedTable(
        table_id="tbl_initially_sparse",
        page=1,
        headers=["label", "col2", "col3", "col4", "col5", "col6", "col7"],
        column_periods=[None, "2023", None, "2024", None, "2025", None],
        column_types=[],
        rows=[TableRow(cells=r, page=1) for r in raw[1:]],
        raw_cells=raw,
        default_unit="currency",
        default_currency="USD",
        default_unit_scale=1000.0,
    )
    doc = ParsedDocument(
        document_id="doc_test",
        sha256="sha_test",
        safe_filename="prospectus.pdf",
        page_count=1,
        pages=[
            DocumentPage(
                page_number=1,
                text="Revenue expanded to 220 million in 2025. Operating cash flow turned positive to 120 million.",
                tables=[unreconstructed_table],
            )
        ],
    )

    # Narrative has quantitative claims
    insights = [
        Insight(
            id="ins_1",
            title="Revenue Scaled Across Periods",
            narrative="Revenue expanded from 100 million in 2023 to 220 million in 2025.",
            kind="reported_fact",
            importance=0.9,
        ),
        Insight(
            id="ins_2",
            title="Operating Cash Flow Turned Positive",
            narrative="Operating cash flow improved from negative 523 million to positive 120 million in 2025.",
            kind="reported_fact",
            importance=0.85,
        ),
    ]
    quantitative_claims = sum(
        len(__import__("re").findall(r"\b\d+(?:\.\d+)?%?\b", f"{i.title} {i.narrative}"))
        for i in insights
    )
    assert quantitative_claims >= 3

    # Initial state: 0 charts planned because initial table had broken column periods
    charts: list = []
    assert len(charts) == 0

    # Trigger recovery pass logic
    if not charts and quantitative_claims >= 2:
        reconstructor = TableReconstructor()
        for p in doc.pages:
            p.tables = [reconstructor.reconstruct(t) for t in p.tables]

        extractor = ObservationExtractor()
        recovered = extractor.extract(doc)
        recovered = FinancialNormalizer.normalize_observations(recovered, default_currency="USD")
        index = DocumentModelBuilder().build(recovered)

        recovered_charts = ChartPlanner().plan(
            [],
            [],
            index,
            preferred_metrics=["Revenue", "Gross profit", "Net loss", "Operating cash flow"],
            insights=insights,
        )

        # Successfully recovered charts!
        assert len(recovered_charts) >= 4
        chart_metrics = {c.x_metric.casefold() for c in recovered_charts if c.x_metric}
        assert "revenue" in chart_metrics
        assert "operating cash flow" in chart_metrics
