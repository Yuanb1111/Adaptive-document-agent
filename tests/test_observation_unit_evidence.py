"""Reported units must be resolved per cell, including cached source tables."""

import pytest

from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric, is_explicit_count_metric
from adaptive_document_agent.extraction.normalizer import infer_unit_defaults
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer


def mixed_table(rows, **kwargs):
    return ExtractedTable(
        table_id="mixed-measurements", page=7,
        headers=["label", "FY2022", "FY2023"],
        column_periods=[None, "FY2022", "FY2023"],
        column_types=["label", "amount", "amount"],
        rows=[TableRow(cells=row, page=7) for row in rows],
        confidence=0.95, **kwargs,
    )


def test_mixed_rows_use_count_money_and_percentage_source_evidence():
    table = mixed_table([
        ["Number of customers", "289", "411"],
        ["Average transaction value (RMB in thousands)", "157", "195"],
        ["Customer retention rate", "42.7%", "30.8%"],
    ])
    before = table.model_dump()
    observations = ObservationExtractor()._table_observations(table)
    count, money, ratio = observations[0], observations[2], observations[4]
    assert (count.value, count.unit, count.currency, count.raw_unit) == (289, "count", None, None)
    assert (money.value, money.unit, money.currency, money.raw_unit) == (157_000, "currency", "CNY", "RMB in thousands")
    assert (ratio.value, ratio.unit, ratio.currency, ratio.raw_unit) == (42.7, "percent", None, "%")
    assert count.dimensions["column_role"] == "count"
    assert [o.raw_value for o in observations] == ["289", "411", "157", "195", "42.7%", "30.8%"]
    assert all(o.evidence[0].page == 7 for o in observations)
    assert table.model_dump() == before


@pytest.mark.parametrize("label", [
    "Number of patients", "Number of cash transactions", "Number of shares",
    "Number of revenue-generating customers", "Number of assets",
    "Number of distributors at the end of the year/period",
    "Number of distributors at the beginning of the year / period",
    "Average number of employees", "Sample count", "参与人数",
])
def test_explicit_counts_do_not_inherit_currency_or_scale(label):
    table = mixed_table(
        [[label, "120", "140"]],
        default_unit="currency", default_currency="USD",
        default_unit_scale=1_000_000, default_raw_unit="USD million",
    )
    obs = ObservationExtractor()._table_observations(table)[0]
    assert (obs.value, obs.raw_value, obs.unit, obs.unit_scale, obs.raw_unit, obs.currency) == (120, "120", "count", 1, None, None)
    assert classify_metric(label, unit=obs.unit, raw_unit=obs.raw_unit).unit_family == "count"
    FinancialNormalizer().normalize_observation(obs)
    assert (obs.value, obs.unit, obs.currency, obs.unit_family) == (120, "count", None, "count")


def test_generic_nonfinancial_amount_column_does_not_invent_currency():
    table = mixed_table([["Observed response score", "4.1", "4.5"]])
    obs = ObservationExtractor()._table_observations(table)[0]
    assert obs.value == 4.1
    assert obs.unit == "unknown"
    assert obs.currency is None and obs.raw_unit is None
    assert obs.unit_family == "generic"


def test_mid_table_source_unit_heading_scopes_only_following_rows_and_preserves_scale():
    table = mixed_table([
        ['Number of customers', '254', '324'],
        ['(In millions of RMB)', None, None],
        ['Repeat end customers revenue', '726.83', '1,792.43'],
        ['Average revenue per repeat end customer', '4.49', '6.82'],
    ])
    original = table.model_dump()
    values = ObservationExtractor()._table_observations(table)
    assert (values[0].value, values[0].currency, values[0].unit_scale) == (254, None, 1)
    money = values[2:]
    assert [o.value for o in money] == [726_830_000, 1_792_430_000, 4_490_000, 6_820_000]
    assert all(o.currency == 'CNY' and o.unit_scale == 1_000_000 for o in money)
    assert all(o.raw_unit == 'In millions of RMB' for o in money)
    assert all('(In millions' not in o.metric_original for o in money)
    assert table.model_dump() == original
    from adaptive_document_agent.services.pptx_export import _appendix_display_unit, _appendix_display_value
    semantic = classify_metric(money[0].metric_original, value=money[0].value,
                               raw_unit=money[0].raw_unit, unit=money[0].unit)
    assert _appendix_display_unit(money[0], semantic) == 'RMB million'
    assert _appendix_display_value(money[0], semantic) == '726.83'


def test_body_metric_currency_is_not_a_scope_heading_for_later_rows():
    table = mixed_table([
        ['Average transaction value (USD million)', None, None],
        ['Observed response score', '4.1', '4.5'],
    ])
    value = ObservationExtractor()._table_observations(table)[0]
    assert value.currency is None and value.unit_scale == 1


def test_financial_metric_still_supports_unknown_currency():
    obs = ObservationExtractor()._table_observations(mixed_table([["Revenue", "123", "456"]]))[0]
    assert (obs.value, obs.unit, obs.currency) == (123, "currency", None)


@pytest.mark.parametrize("label", [
    "Number of customers growth rate", "Number of patients (%)",
    "Number of employees as percentage of total",
])
def test_count_wording_does_not_override_explicit_ratios(label):
    obs = ObservationExtractor()._table_observations(mixed_table([[label, "12%", "15%"]]))[0]
    assert (obs.value, obs.unit, obs.currency) == (12, "percent", None)


def test_count_label_with_explicit_currency_is_preserved_and_flagged():
    obs = ObservationExtractor()._table_observations(mixed_table([["Number of samples (USD thousands)", "12", "15"]]))[0]
    assert (obs.value, obs.raw_value, obs.unit, obs.raw_unit) == (12_000, "12", "currency", "USD thousands")
    assert obs.validation_status == "suspicious_alignment"
    assert "conflicts" in obs.anomaly_notes[0]
    assert "units" not in obs.display_value


@pytest.mark.parametrize(("source", "raw_unit", "scale"), [
    ("(RMBinthousands/unitforASP)", "RMB in thousands/unit", 1_000),
    ("RMB in thousands/unit for ASP", "RMB in thousands/unit", 1_000),
    ("USD millions per employee", "USD millions per employee", 1_000_000),
    ("USD per patient", "USD per patient", None),
    ("EUR/kg", "EUR/kg", None),
    ("USD per square meter", "USD per square meter", None),
    ("USD thousands per square meter for ASP", "USD thousands per square meter", 1_000),
    ("(EUR/cubic meter), amounts exclude tax", "EUR/cubic meter", None),
    ("USD per patient visit in FY2023", "USD per patient visit", None),
    ("USD per square meter was reported separately", "USD per square meter", None),
    ("USD per square meter. Revenue rose in FY2023", "USD per square meter", None),
])
def test_source_denominator_is_part_of_raw_unit(source, raw_unit, scale):
    defaults = infer_unit_defaults(source)
    assert defaults.raw_unit == raw_unit
    assert defaults.scale == scale


def test_unrelated_per_phrase_does_not_become_unit_denominator():
    assert infer_unit_defaults("USD million revenue per year").raw_unit == "USD million"


@pytest.mark.parametrize("label", [
    "Number of patients / year", "Number of visits / total visits",
    "Number of responses per period", "Number of samples / square meter",
])
def test_real_count_denominators_are_not_absolute_counts(label):
    assert not is_explicit_count_metric(label)


def test_scoped_header_does_not_leak_through_cached_currency_defaults():
    table = ExtractedTable(
        table_id="scoped-currency", page=8,
        headers=["Product", "Observed response score", "ASP"],
        column_periods=[None, "FY2023", "FY2023"],
        column_types=["label", "amount", "amount"],
        column_currencies=[None, "USD", "USD"],
        column_scales=[None, 1000, 1000],
        rows=[TableRow(cells=["Product A", "4.1", "65.9"], page=8)],
        raw_header_lines=["(USD thousands/unit for ASP)"],
        default_unit="currency", default_currency="USD", default_unit_scale=1000,
        default_raw_unit="USD thousands/unit", confidence=0.95,
    )
    before = table.model_dump()
    score, price = ObservationExtractor()._table_observations(table)
    assert (score.value, score.unit, score.raw_unit, score.currency, score.unit_scale) == (4.1, "unknown", None, None, 1)
    assert (price.value, price.unit, price.raw_unit, price.currency, price.unit_scale) == (65_900, "currency", "USD thousands/unit", "USD", 1000)
    assert table.model_dump() == before


def test_cached_source_header_recovers_per_unit_without_changing_counts_or_values():
    table = ExtractedTable(
        table_id="mixed-columns", page=9,
        headers=["Product", "Sales volume", "ASP", "Sales volume", "ASP"],
        column_periods=[None, "FY2022", "FY2022", "FY2023", "FY2023"],
        column_types=["label", "count", "amount", "count", "amount"],
        column_currencies=[None, None, "CNY", None, "CNY"],
        column_scales=[None, 1, 1000, 1, 1000],
        rows=[TableRow(cells=["Product A", "394", "65.9", "1,707", "61.4"], page=9)],
        raw_header_lines=["volume ASP volume ASP", "(RMBinthousands/unitforASP)"],
        default_unit="currency", default_currency="CNY", default_unit_scale=1000,
        default_raw_unit="RMB in thousands", confidence=0.95,
    )
    before = table.model_dump()
    items = ObservationExtractor()._table_observations(table)
    assert [o.value for o in items] == [394, 65_900, 1707, 61_400]
    assert [o.raw_unit for o in items] == [None, "RMB in thousands/unit", None, "RMB in thousands/unit"]
    assert items[1].raw_value == "65.9"
    assert items[1].evidence[0].column_label == "ASP"
    assert items[1].category_dimensions == {"product": "Product A"}
    assert table.model_dump() == before
    # The name alone must not invent /unit when the source declaration is lost.
    table.raw_header_lines = []
    assert ObservationExtractor()._table_observations(table)[1].raw_unit == "RMB in thousands"


def test_explicit_numeric_suffix_is_scaled_once():
    table = mixed_table(
        [["Revenue", "$1.2m", "$1.5m"]], default_unit="currency",
        default_currency="USD", default_unit_scale=1000, default_raw_unit="USD thousands",
    )
    obs = ObservationExtractor()._table_observations(table)[0]
    assert (obs.value, obs.raw_value, obs.currency, obs.unit_scale) == (1_200_000, "$1.2m", "USD", 1_000_000)


def test_explicit_row_currency_without_scale_does_not_inherit_millions():
    table = mixed_table(
        [["Cost per visit (USD)", "25", "30"]], default_unit="currency",
        default_currency="USD", default_unit_scale=1_000_000, default_raw_unit="USD millions",
    )
    obs = ObservationExtractor()._table_observations(table)[0]
    assert (obs.value, obs.unit_scale, obs.raw_unit) == (25, 1, "USD")
