"""Share wording alone must not turn reported monetary amounts into percentages."""

import pytest

from adaptive_document_agent.extraction.column_roles import explicit_percentage, percentage_column
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.models import DocumentProfile, ParsedDocument, PipelineResult
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer
from adaptive_document_agent.validation.presentation_data_qa import validate_presentation_data


def amount_table(metric, raw="125", column_type="amount"):
    return ExtractedTable(
        table_id="synthetic_share_amount", page=3,
        headers=["Metric", "2024", "", "2023"],
        column_periods=[None, "2024", None, "2023"],
        column_types=["label", column_type, "unknown", column_type],
        default_unit="currency", default_currency="USD",
        default_raw_unit="USD '000", default_unit_scale=1000,
        rows=[TableRow(cells=[metric, raw, None, "100"], page=3)],
    )


def result_for(observations):
    return PipelineResult(
        document=ParsedDocument(document_id="synthetic", sha256="a" * 64,
                                safe_filename="synthetic.pdf", page_count=3),
        profile=DocumentProfile(), observations=observations,
    )


@pytest.mark.parametrize("metric", [
    "Share of profit of an associate", "Share of loss of joint ventures",
    "Share of net assets of associates",
])
@pytest.mark.parametrize("column_type", ["amount", "unknown"])
@pytest.mark.parametrize("raw,expected", [("125", 125000), ("(25)", -25000), ("0", 0)])
def test_share_amount_preserves_source_currency_scale_and_evidence(metric, column_type, raw, expected):
    table = amount_table(metric, raw, column_type)
    observations = ObservationExtractor()._table_observations(table)
    assert [o.column_id for o in observations] == [1, 3]
    assert [o.value for o in observations] == [expected, 100000]
    for obs in observations:
        assert obs.currency == "USD"
        FinancialNormalizer.normalize_observation(obs)
        assert obs.unit == "currency"
        assert obs.unit_family == "currency"
        assert obs.currency == "US$"
        assert obs.unit_scale == 1000
        assert "%" not in obs.display_value
        assert obs.evidence[0].page == 3
        assert obs.evidence[0].row_label == metric
        assert obs.evidence[0].table_id == table.table_id
    assert observations[0].raw_value == raw
    assert observations[0].value == expected
    assert not validate_presentation_data(result_for(observations))


@pytest.mark.parametrize("header", [
    "Share of profit of an associate", "Share of loss of joint ventures",
    "Share of net assets of associates",
])
def test_monetary_share_header_is_not_percentage_evidence(header):
    assert not explicit_percentage(header)
    assert not percentage_column(header, ["125", "100"])


@pytest.mark.parametrize("header", ["Share", "Share of revenue", "Market share", "2024 %"])
def test_actual_share_column_still_provides_percentage_evidence(header):
    assert explicit_percentage(header)
    assert percentage_column(header, ["25", "75"])


@pytest.mark.parametrize("metric", ["Market share", "Cost of sales: share of revenue", "Gross profit margin"])
def test_intrinsic_ratios_remain_percentages(metric):
    observations = ObservationExtractor()._table_observations(amount_table(metric, "25"))
    assert observations[0].unit == "percent"
    assert observations[0].unit_scale == 1
    assert observations[0].currency is None
    assert observations[0].value == 25


@pytest.mark.parametrize("marked_cell", [False, True])
def test_source_marked_percentage_remains_valid_for_monetary_row(marked_cell):
    table = amount_table("Share of profit of an associate", "25%" if marked_cell else "25")
    if not marked_cell:
        table.headers[1] = "2024 %"
    obs = ObservationExtractor()._table_observations(table)[0]
    FinancialNormalizer.normalize_observation(obs)
    assert obs.unit == "percent"
    assert obs.value == 25
    assert obs.unit_scale == 1
    assert not validate_presentation_data(result_for([obs]))


def test_stale_bad_percentage_is_still_blocked_by_export_gate():
    obs = ObservationExtractor()._table_observations(amount_table("Share of profit of an associate"))[0]
    obs.unit = "percent"
    obs.unit_family = "percentage"
    obs.display_value = "125%"
    issues = validate_presentation_data(result_for([obs]))
    assert any(i.code == "monetary_percentage_mismatch" and i.severity == "CRITICAL" for i in issues)


def test_monetary_share_as_column_metric_preserves_amounts():
    table = amount_table("Division A")
    table.headers = ["Division", "Share of profit of an associate", "", "Revenue"]
    observations = ObservationExtractor()._table_observations(table)
    assert observations[0].metric_original == table.headers[1]
    assert observations[0].value == 125000
    assert observations[0].unit == "currency"
    assert observations[0].currency == "USD"
    assert observations[0].evidence[0].column_label == table.headers[1]


def test_mixed_amount_and_share_columns_remain_distinct():
    table = amount_table("Share of profit of an associate")
    table.headers = ["Metric", "2024 Amount", "2024 %", "2023 Amount"]
    table.column_periods[2] = "2024"
    table.column_types[2] = "percentage"
    table.rows[0].cells[2] = "12.5"
    observations = ObservationExtractor()._table_observations(table)
    assert [o.unit_family for o in observations] == ["currency", "percentage", "currency"]
    assert [o.value for o in observations] == [125000, 12.5, 100000]
    assert not validate_presentation_data(result_for(observations))
