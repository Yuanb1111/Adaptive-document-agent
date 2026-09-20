"""Tests for multi-strategy table extraction, candidate selection, text fallback, and zero-chart diagnostics."""

from __future__ import annotations

from adaptive_document_agent.agent.chart_planner import ChartPlanner
from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.document_model import DocumentModelBuilder
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.extraction.table_candidate_selector import TableCandidateSelector
from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor
from adaptive_document_agent.models import (
    DocumentPage,
    DocumentProfile,
    ExtractedTable,
    Insight,
    ParsedDocument,
    TableRow,
)
from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer


def _create_malformed_table() -> ExtractedTable:
    """A non-empty table returned by a flawed table frame extraction (no periods, garbled cells)."""
    return ExtractedTable(
        table_id="tbl_malformed_frame",
        page=1,
        headers=["Item", "Value"],
        column_periods=[None, None],
        column_types=["label", "generic"],
        rows=[
            TableRow(cells=["Financial highlights", None], page=1),
            TableRow(cells=["Refer to notes on page 100", None], page=1),
        ],
        raw_cells=[["Item", "Value"], ["Financial highlights", None]],
        confidence=0.4,
    )


def _create_valid_borderless_table() -> ExtractedTable:
    """A valid table extracted via borderless pattern with 3 years of data."""
    raw = [
        ["Financial Summary", "2023", "2024", "2025"],
        ["Revenue", "100,000", "150,000", "220,000"],
        ["Gross profit", "40,000", "70,000", "110,000"],
        ["Net loss", "(20,000)", "(10,000)", "(5,000)"],
    ]
    return ExtractedTable(
        table_id="tbl_borderless_clean",
        page=1,
        headers=["Financial Summary", "2023", "2024", "2025"],
        column_periods=[None, "2023", "2024", "2025"],
        column_types=["label", "amount", "amount", "amount"],
        rows=[
            TableRow(cells=raw[1], page=1),
            TableRow(cells=raw[2], page=1),
            TableRow(cells=raw[3], page=1),
        ],
        raw_cells=raw,
        default_unit="currency",
        default_currency="USD",
        default_unit_scale=1000.0,
        confidence=0.85,
    )


def test_table_candidate_selector_prefers_borderless_over_malformed_pdfplumber() -> None:
    """Requirement 2, 3: Candidate selector chooses the table yielding higher valid financial series."""
    malformed = _create_malformed_table()
    borderless = _create_valid_borderless_table()

    malformed_score, malformed_series, _ = TableCandidateSelector.score_table(malformed)
    borderless_score, borderless_series, _ = TableCandidateSelector.score_table(borderless)

    assert malformed_series == 0
    assert malformed_score == 0.0

    assert borderless_series == 3
    assert borderless_score > 300.0

    # merge_or_replace_tables must replace the malformed table with the valid borderless table
    chosen = TableCandidateSelector.merge_or_replace_tables([malformed], [borderless])
    assert len(chosen) == 1
    assert chosen[0].table_id == "tbl_borderless_clean"


def test_deterministic_vertical_text_series_fallback() -> None:
    """Requirement 4: Deterministic financial text fallback extracts vertical multi-period series."""
    text = """
    Business Review
    
    Revenue (USD in thousands)
    2023  100,000
    2024  150,000
    2025  220,000

    Gross profit (USD in thousands)
    2023: 40,000
    2024: 70,000
    2025: 110,000

    Net loss (USD in thousands)
    2023  (20,000)
    2024  (10,000)
    2025  (5,000)
    """

    extractor = ObservationExtractor()
    observations = extractor._text_observations(page=1, text=text)

    # Must find Revenue, Gross profit, Net loss across 2023, 2024, 2025
    assert len(observations) == 9

    rev_obs = [o for o in observations if o.metric_original == "Revenue"]
    assert len(rev_obs) == 3
    assert [o.period for o in rev_obs] == ["2023", "2024", "2025"]
    assert [o.value for o in rev_obs] == [100_000_000, 150_000_000, 220_000_000]
    assert rev_obs[0].currency == "USD"
    assert rev_obs[0].evidence[0].page == 1

    gp_obs = [o for o in observations if o.metric_original == "Gross profit"]
    assert len(gp_obs) == 3
    assert [o.value for o in gp_obs] == [40_000_000, 70_000_000, 110_000_000]

    loss_obs = [o for o in observations if o.metric_original == "Net loss"]
    assert len(loss_obs) == 3
    assert [o.value for o in loss_obs] == [-20_000_000, -10_000_000, -5_000_000]


def test_integration_malformed_primary_table_recovered_to_produce_charts() -> None:
    """Requirement 8: Integration test where primary table extractor returns a malformed table,
    but fallback/recovery extracts valid 3-year Revenue, Gross Profit, and Net Loss series,
    producing valid charts without weakening chart validation."""
    malformed = _create_malformed_table()

    page_text = """
    FINANCIAL INFORMATION
    
    Revenue (USD in thousands)
    2023  100,000
    2024  150,000
    2025  220,000

    Gross profit (USD in thousands)
    2023  40,000
    2024  70,000
    2025  110,000

    Net loss (USD in thousands)
    2023  (20,000)
    2024  (10,000)
    2025  (5,000)
    """

    doc = ParsedDocument(
        document_id="doc_integration_test",
        sha256="sha_int_test",
        safe_filename="company_prospectus.pdf",
        page_count=1,
        pages=[
            DocumentPage(
                page_number=1,
                text=page_text,
                tables=[malformed],  # Primary extractor only found malformed table
            )
        ],
    )

    # Initial extraction from malformed table gives 0 chartable series
    initial_table_obs = ObservationExtractor()._table_observations(malformed)
    assert len(initial_table_obs) == 0

    # With the multi-strategy text fallback, ObservationExtractor extracts the 3-year series
    extractor = ObservationExtractor()
    extracted_obs = extractor.extract(doc)
    extracted_obs = FinancialNormalizer.normalize_observations(extracted_obs, default_currency="USD")

    assert len(extracted_obs) == 9
    index = DocumentModelBuilder().build(extracted_obs)

    # Plan charts
    planner = ChartPlanner()
    charts = planner.plan(
        [],
        [],
        index,
        preferred_metrics=["Revenue", "Gross profit", "Net loss"],
    )

    # Must produce valid chart plans for all three key metrics
    assert len(charts) >= 3
    chart_metrics = {c.x_metric.casefold() for c in charts if c.x_metric}
    assert "revenue" in chart_metrics
    assert "gross profit" in chart_metrics
    assert "net loss" in chart_metrics


def test_zero_charts_diagnostics_generation() -> None:
    """Requirement 6: Diagnostics when charts == 0 accurately detail why candidate series failed."""
    doc = ParsedDocument(
        document_id="doc_diag_test",
        sha256="sha_diag_test",
        safe_filename="empty.pdf",
        page_count=1,
        pages=[DocumentPage(page_number=1, text="No financial tables here.", tables=[])],
    )

    # Observation with only 1 period (cannot form a time series)
    from adaptive_document_agent.models.evidence import SourceEvidence
    from adaptive_document_agent.models.observation import Observation

    sparse_obs = [
        Observation(
            id="obs_single",
            metric_original="Revenue",
            value=100.0,
            raw_value="100",
            unit="currency",
            currency="USD",
            period="2023",
            confidence=0.8,
            evidence=[SourceEvidence(page=1, text="Revenue 2023 = 100", extraction_method="digital_text", confidence=0.8)],
        )
    ]
    index = DocumentModelBuilder().build(sparse_obs)

    summary, failure_reasons = DocumentOrchestrator._diagnose_zero_charts(doc, sparse_obs, index)

    assert "[DIAGNOSTIC: charts == 0]" in summary
    assert "Tables detected across document: 0" in summary
    assert "Observations extracted: 1" in summary
    assert "Observations retained in model index: 1" in summary
    lower_failures = {k.casefold(): v for k, v in failure_reasons.items()}
    assert "revenue" in lower_failures
    assert any("Fewer than 2 distinct periods" in r for r in lower_failures["revenue"])
