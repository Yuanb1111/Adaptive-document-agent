"""Month-flow scope must survive raw headers, normalization and calculation guards."""

from itertools import combinations

import pymupdf
import pytest

from adaptive_document_agent.agent.executor import AnalysisExecutor
from adaptive_document_agent.document_model import DocumentIndex, group_comparable_series, score_chartability
from adaptive_document_agent.document_model.period_semantic_validator import (
    are_periods_comparable,
    classify_period,
    extract_period_basis,
    format_period_label,
)
from adaptive_document_agent.models import AnalysisTask, Observation, SourceEvidence
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.extraction.pdf_parser import PDFParser
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer
from adaptive_document_agent.validation.claim_validator import are_observations_compatible


@pytest.mark.parametrize("count,word", [(3, "Three"), (6, "Six"), (9, "Nine")])
@pytest.mark.parametrize("ending", ["", " 30 June 2025", " June 30, 2025", " 2025-06-30", " 31 December 2025"])
def test_numeric_and_written_month_durations_agree(count, word, ending):
    for token in (str(count), word):
        label = f"{token} months ended{ending}"
        semantic = classify_period(label)
        assert extract_period_basis(label) == f"{count}M"
        assert semantic.period_type == "interim_flow"
        assert semantic.as_of_date is None
        assert semantic.is_interim is True
        assert semantic.clean_label == (f"{count}M2025" if ending else label)
        assert extract_period_basis(semantic.clean_label) == extract_period_basis(label)


@pytest.mark.parametrize("ending", ["", " 30 June 2025", " June 30, 2025", " 2025-06-30"])
def test_different_month_durations_are_not_comparable(ending):
    for left, right in combinations((3, 6, 9), 2):
        comparable, reason = are_periods_comparable(
            f"{left} months ended{ending}", f"{right} months ended{ending}",
        )
        assert comparable is False
        assert f"'{left}M'" in reason and f"'{right}M'" in reason


def _observation(identifier, period, value):
    return Observation(
        id=identifier, metric_original="Revenue", raw_value=str(value), value=value,
        period=period, unit="currency", unit_family="currency", currency="USD", confidence=0.9,
        evidence=[SourceEvidence(page=1, text=f"Revenue {value}", column_label=period,
                                 extraction_method="test", confidence=0.9)],
    )


def _execute(observations, operation="percentage_change"):
    task = AnalysisTask(
        id="month_comparison", title="Revenue comparison", description="Compare disclosed periods",
        analysis_type=operation, tool_name=operation, required_metrics=["Revenue"],
        observation_query={"observation_ids": [o.id for o in observations]},
        reason="Check period scope", expected_output="Validated comparison",
    )
    return AnalysisExecutor().execute([task], DocumentIndex(observations))[0]


@pytest.mark.parametrize("operation", ["absolute_change", "percentage_change", "growth_rate", "compare_periods", "linear_trend", "moving_average"])
def test_executor_blocks_cross_duration_calculations(operation):
    observations = [
        _observation("quarter", "3 months ended 30 June 2025", 100),
        _observation("half", "6 months ended 30 June 2025", 200),
        _observation("nine_month", "9 months ended 30 June 2025", 300),
    ]
    result = _execute(observations, operation)
    assert result.result is None
    assert result.confidence == 0
    assert any("incompatible periods" in warning for warning in result.warnings)
    assert result.input_observation_ids == [o.id for o in observations]
    assert len(result.evidence) == 3


def test_series_chart_and_claim_guards_share_raw_month_scope():
    observations = [
        _observation(f"{count}_{year}", f"{count} months ended 30 June {year}", count * year)
        for count in (3, 6, 9) for year in (2024, 2025)
    ]
    groups = group_comparable_series(observations)
    assert len(groups) == 3
    assert sorted(len(group) for group in groups) == [2, 2, 2]
    assert {extract_period_basis(group[0].period) for group in groups} == {"3M", "6M", "9M"}
    assert not score_chartability(observations).is_chartable
    assert all(score_chartability(group).is_chartable for group in groups)
    assert not are_observations_compatible(observations[0], observations[2])[0]


def test_same_duration_comparison_still_calculates():
    observations = [
        _observation("prior", "3 months ended 30 June 2024", 100),
        _observation("current", "3 months ended 30 June 2025", 120),
    ]
    assert _execute(observations).result == pytest.approx(20)
    assert are_periods_comparable(observations[0].period, "Three months ended 30 June 2025")[0]


@pytest.mark.parametrize("label,expected", [
    ("As at 30 June 2025", "2025-06-30"),
    ("June 30, 2025", "2025-06-30"),
    ("2025-06-30", "2025-06-30"),
    ("2025年6月30日", "2025-06-30"),
])
def test_exact_dates_keep_point_in_time_semantics(label, expected):
    assert classify_period(label).period_type == "point_in_time"
    semantic = classify_period(label, is_balance_sheet=True)
    assert semantic.period_type == "balance_sheet_date"
    assert semantic.as_of_date == expected
    assert semantic.clean_label == "30 Jun 2025"


@pytest.mark.parametrize("label", ["2025", "FY2025", "1999", "FY1999"])
def test_fiscal_year_classification_is_unchanged(label):
    assert classify_period(label).period_type == "fiscal_year"
    assert extract_period_basis(label) == "FY"


@pytest.mark.parametrize("label,basis", [
    ("3M2025", "3M"), ("6M2025", "6M"), ("9M2025", "9M"),
    ("Q12025", "3M"), ("H12025", "6M"), ("YTD 2025", "YTD"),
    ("截至2025年6月30日止六个月", "6M"),
])
def test_existing_duration_aliases_are_unchanged(label, basis):
    assert extract_period_basis(label) == basis


def test_missing_year_is_not_invented_and_audit_marker_is_preserved():
    assert format_period_label("3 months ended") == "3 months ended"
    assert format_period_label("3 months ended 30 June 2025", is_unaudited=True) == "3M2025*"
    assert classify_period("3 months ended 30 June 2025*").is_unaudited


@pytest.mark.parametrize("count,word", list(enumerate(
    ("One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"),
    start=1,
)))
def test_month_recognizer_is_not_limited_to_requested_examples(count, word):
    for token in (str(count), word, f"{count:02d}"):
        label = f"For the {token}\nMONTHS\tENDED 30 June 2025"
        assert extract_period_basis(label) == f"{count}M"
        assert format_period_label(label) == f"{count}M2025"


@pytest.mark.parametrize("label", ["months ended", "months ended 3", "someone months ended", "123 months ended", "0 months ended"])
def test_incomplete_or_non_token_month_counts_are_not_guessed(label):
    assert extract_period_basis(label) == "generic"
    assert format_period_label(label) == label


@pytest.mark.parametrize("numeric_variant", [False, True])
def test_public_header_transcription_preserves_duration_from_pdf_text(numeric_variant):
    """Minimal public header excerpt, with an explicitly synthetic numeric variant.

    Source: Apple FY25 Q3 statements, p. 1 (June 28, 2025 column).
    https://www.apple.com/newsroom/pdfs/fy2025-q3/FY25_Q3_Consolidated_Financial_Statements.pdf
    This tests PDF text ingestion and period semantics, not table geometry.
    """
    labels = ["Three Months Ended June 28, 2025", "Nine Months Ended June 28, 2025"]
    if numeric_variant:
        labels = [labels[0].replace("Three", "3"), labels[1].replace("Nine", "9")]
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "\n".join(labels))
        document = PDFParser().parse(pdf.tobytes(), extract_tables=False)
    retained = [line.strip() for line in document.pages[0].text.splitlines() if line.strip()]
    assert retained == labels
    assert [extract_period_basis(label) for label in retained] == ["3M", "9M"]
    assert not are_periods_comparable(*retained)[0]


def test_table_observation_normalization_retains_disclosed_month_scope():
    """Synthetic table uses resolved column periods, without assuming a fiscal calendar."""
    periods = [f"{count} months ended 30 June {year}" for count in (3, 6, 9) for year in (2024, 2025)]
    raw_values = ["100", "120", "200", "240", "300", "360"]
    table = ExtractedTable(
        table_id="disclosed_duration", page=2,
        headers=["Metric", *periods], column_periods=[None, *periods],
        column_types=["label", *(["amount"] * len(periods))],
        rows=[TableRow(cells=["Revenue", *raw_values], page=2)],
        default_unit="currency", default_currency="USD", default_unit_scale=1,
        confidence=0.95,
    )
    observations = ObservationExtractor()._table_observations(table)
    observations = FinancialNormalizer.normalize_observations(observations)
    assert len(observations) == 6
    assert [o.raw_value for o in observations] == raw_values
    assert [o.period for o in observations] == periods
    assert [o.period_basis for o in observations] == ["3M", "3M", "6M", "6M", "9M", "9M"]
    assert all(o.period_type == "interim_flow" and o.as_of_date is None for o in observations)
    assert all(o.evidence[0].page == 2 and o.evidence[0].column_label == o.period for o in observations)
    assert len(group_comparable_series(observations)) == 3
    assert _execute(observations).result is None
    assert _execute(observations[:2]).result == pytest.approx(20)
