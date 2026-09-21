"""Source-based units must survive multi-year tables and legacy inferred roles."""

import pytest

from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor
from adaptive_document_agent.models.table import ExtractedTable, TableRow


def make_table(raw):
    headers, periods, rows, roles, currencies, scales = TableReconstructor.reconstruct_multi_tier_headers(
        raw, default_unit="currency", default_currency="USD", default_scale=1000,
    )
    return ExtractedTable(
        table_id="generic", page=3, headers=headers, column_periods=periods,
        column_types=roles, column_currencies=currencies, column_scales=scales,
        rows=[TableRow(cells=row, page=3) for row in rows], raw_cells=raw,
        default_unit="currency", default_currency="USD", default_unit_scale=1000, confidence=0.95,
    )


@pytest.mark.parametrize("metric", ["Revenue", "Profit", "Income tax expense", "Cost of sales", "Assets", "Liabilities", "Operating cash flow"])
def test_monetary_year_columns_never_alternate_into_percentages(metric):
    table = make_table([["Metric", "2022", "2023", "2024"], [metric, "800", "731,876", "10,350,986"]])
    assert table.column_types == ["label", "amount", "amount", "amount"]
    obs = ObservationExtractor()._table_observations(table)
    assert len(obs) == 3
    assert all(o.metric_original == metric and o.unit_family == "currency" for o in obs)
    assert [o.value for o in obs] == [800_000, 731_876_000, 10_350_986_000]
    assert obs[-1].raw_value == "10,350,986"
    assert obs[-1].evidence[0].page == 3


def test_stale_synthetic_percentage_header_is_re_evaluated_from_raw_grid():
    table = make_table([["Metric", "2023", "2024"], ["Revenue", "9000000", "10350986"]])
    table.headers[-1] = "2024 %"
    table.column_types[-1] = "percentage"
    table.column_scales[-1] = 1
    table.column_currencies[-1] = None
    repaired = TableReconstructor().reconstruct(table)
    assert repaired.column_types[-1] == "amount"
    assert repaired.warnings
    observations = ObservationExtractor()._table_observations(table)
    assert all(o.metric_original == "Revenue" and o.unit_family == "currency" for o in observations)


def test_role_without_percentage_evidence_does_not_rename_revenue():
    table = make_table([["Metric", "2023", "2024"], ["Revenue", "80", "90"]])
    table.raw_cells = []
    table.column_types[-1] = "percentage"
    table.column_scales[-1] = 1
    observations = ObservationExtractor()._table_observations(table)
    assert all(o.metric_original == "Revenue" and o.unit_family == "currency" for o in observations)
    assert observations[-1].value == 90_000


def test_explicit_amount_percentage_structure_and_expense_ratios_survive():
    table = make_table([
        ["Metric", "2023", None, "2024", None],
        [None, "Amount", "%", "Amount", "%"],
        ["Revenue", "1000", "100", "1200", "100"],
        ["Income tax expense", "80", "8", "72", "6"],
    ])
    obs = ObservationExtractor()._table_observations(table)
    assert [o.value for o in obs if o.metric_original == "Revenue %"] == [100, 100]
    assert [o.value for o in obs if o.metric_original == "Income tax expense %"] == [8, 6]
    assert all(o.currency is None and o.unit_scale == 1 for o in obs if o.unit_family == "percentage")
    ratios = make_table([
        ["Metric", "2023", "2024"],
        ["Selling expense ratio", "12.0", "10.0"],
        ["Gross profit margin", "30.0", "35.0"],
        ["Market share", "5.0", "6.0"],
    ])
    assert all(o.unit_family == "percentage" for o in ObservationExtractor()._table_observations(ratios))


def test_explicit_raw_percent_wins_over_amount_default():
    table = make_table([["Metric", "2023", "2024"], ["Revenue", "100%", "100%"]])
    assert all(o.unit_family == "percentage" for o in ObservationExtractor()._table_observations(table))


def test_column_roles_require_actual_percentage_words():
    roles, _, _ = TableExtractor()._classify_column_roles(
        ["Metric", "2023 Share capital", "2024 Corporate assets"], [None, "2023", "2024"],
        [["Total", "100000", "200000"]], "currency", "USD", 1,
    )
    assert roles == ["label", "amount", "amount"]


def test_mixed_ratio_rows_do_not_turn_monetary_rows_into_percentages():
    table = make_table([
        ["Metric", "2023", "2024"],
        ["Revenue", "9000000", "10350986"],
        ["Gross profit margin", "20%", "22%"],
        ["Selling expense ratio", "10%", "9%"],
    ])
    obs = ObservationExtractor()._table_observations(table)
    assert table.column_types == ["label", "amount", "amount"]
    assert all(o.unit_family == "currency" for o in obs if o.metric_original == "Revenue")
    assert sum(o.unit_family == "percentage" for o in obs) == 4


def test_implausible_source_percent_is_flagged_not_silently_rewritten():
    table = make_table([["Metric", "2023", "2024"], ["Revenue", "9000000%", "10350986%"]])
    obs = ObservationExtractor()._table_observations(table)
    assert all(o.unit_family == "percentage" and o.validation_status == "suspicious_alignment" for o in obs)
    assert obs[-1].raw_value == "10350986%"
    assert all(o.anomaly_notes for o in obs)


def test_percentage_re_evaluation_preserves_continuation_rows_and_page_evidence():
    raw = [
        ["Metric", "2023", None, "2024", None],
        [None, "Amount", "%", "Amount", "%"],
        ["Revenue", "1000", "100", "1200", "100"],
    ]
    first = make_table(raw)
    second = make_table(raw[:2] + [["Income tax expense", "80", "8", "72", "6"]])
    second.table_id = "continuation"
    second.page = 4
    for row in second.rows:
        row.page = 4
    combined = TableReconstructor().combine_continuations([first, second])
    assert len(combined) == 1
    observations = ObservationExtractor()._table_observations(combined[0])
    assert len(observations) == 8
    assert {o.evidence[0].page for o in observations} == {3, 4}
    assert sum(o.unit_family == "percentage" for o in observations) == 4
