"""Source missing cells and compound units must retain their own meaning."""

import pytest

from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric
from adaptive_document_agent.extraction.normalizer import (
    UnitSignature, compatible_units, infer_unit_defaults, normalize_financial_fact,
)
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.models import Observation
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer


def source_table(rows, **kwargs):
    return ExtractedTable(
        table_id="generic-source", page=8, headers=["label", "FY2022", "FY2023"],
        column_periods=[None, "FY2022", "FY2023"],
        column_types=["label", "amount", "amount"], confidence=.9,
        rows=[TableRow(cells=row, page=8) for row in rows], **kwargs,
    )


@pytest.mark.parametrize("missing", ["—", "–", "-", "N/A", "nil", "not reported"])
def test_missing_value_data_row_never_becomes_a_parent_heading(missing):
    table = source_table([
        ["Service incidents", None, None],
        ["Network failure", "4", "5"],
        ["Unavailable sample", missing, missing],
        ["Equipment failure", "2", "3"],
    ])
    table.rows[0].is_section_header = True
    original = table.model_dump()
    values = ObservationExtractor()._table_observations(table)
    assert len(values) == 4
    assert {o.parent_section for o in values} == {"Service incidents"}
    assert not any("Unavailable sample" in o.metric_original for o in values)
    assert table.model_dump() == original


def test_named_total_retains_identity_after_empty_heading_and_all_dash_row():
    table = source_table([
        ["Funding attributable to operating units", None, None],
        ["Capital allocation", "400", "450"],
        ["Unassigned funding", "—", "—"],
        ["Total funding", "400", "450"],
    ], default_unit="currency", default_currency="EUR", default_unit_scale=1000,
       default_raw_unit="EUR thousands")
    table.rows[0].is_section_header = True
    table.rows[-1].is_subtotal = True
    values = ObservationExtractor()._table_observations(table)
    totals = [o for o in values if o.evidence[0].row_label == "Total funding"]
    assert [o.metric_original for o in totals] == ["Total funding", "Total funding"]
    assert all(o.parent_section is None and not o.category_dimensions for o in totals)
    assert [o.value for o in totals] == [400_000, 450_000]


@pytest.mark.parametrize("unit, expected_unit, factor", [
    ("m3/Revenue RMB’ million", "compound:m3/CNY", 1e-6),
    ("MWh/Revenue RMB’ million", "compound:MWh/CNY", 1e-6),
    ("kg per USD thousand", "compound:kg/USD", 1e-3),
    ("million units/EUR thousand", "compound:units/EUR", 1e3),
    ("thousand kg/million units", "compound:kg/units", 1e-3),
    ("MWh/tonnes", "compound:MWh/tonnes", 1),
])
def test_compound_unit_normalizes_both_sides_without_currency_amount(unit, expected_unit, factor):
    defaults = infer_unit_defaults(f"Resource intensity ({unit})")
    assert (defaults.unit, defaults.currency, defaults.raw_unit) == ("compound", None, unit)
    assert defaults.normalized_unit == expected_unit
    assert defaults.scale == pytest.approx(factor)
    table = source_table([[f"Resource intensity ({unit})", "43.60", "34.55"]],
                         default_currency="USD", default_unit_scale=1e6, default_unit="currency")
    before = table.model_dump()
    obs = ObservationExtractor()._table_observations(table)[0]
    assert obs.value == pytest.approx(43.6 * factor)
    assert (obs.unit, obs.normalized_unit, obs.unit_family, obs.semantic_type, obs.currency) == (
        expected_unit, expected_unit, "compound", "compound_ratio", None,
    )
    assert (obs.raw_unit, obs.raw_value) == (unit, "43.60")
    assert obs.unit_scale == pytest.approx(factor)
    assert obs.display_value == f"43.60  {unit}"
    assert obs.evidence[0].page == 8
    for _ in range(2):
        FinancialNormalizer.normalize_observation(obs, default_currency="USD")
        assert obs.value == pytest.approx(43.6 * factor)
        assert obs.currency is None and obs.display_value == f"43.60  {unit}"
    assert table.model_dump() == before
    semantic = classify_metric("Resource revenue intensity", unit=obs.unit, raw_unit=obs.raw_unit)
    assert semantic.unit_family == "compound" and not semantic.is_currency
    value, normalized, display, display_unit, currency = normalize_financial_fact(
        "43.60", unit, default_currency="USD",
    )
    assert value == pytest.approx(43.6 * factor)
    assert (normalized, display, display_unit, currency) == (expected_unit, "43.60", unit, None)


def test_unknown_compound_unit_is_retained_without_inferred_conversion():
    obs = ObservationExtractor()._table_observations(source_table([
        ["Light intensity (lumens/USD million)", "12", "14"],
    ]))[0]
    assert (obs.value, obs.raw_value, obs.raw_unit, obs.currency) == (None, "12", "lumens/USD million", None)
    assert obs.normalized_value is None and obs.unit_scale is None
    assert obs.display_value == "12  lumens/USD million"
    assert obs.semantic_type == "compound_ratio" and obs.validation_status == "ambiguous"
    assert not compatible_units(UnitSignature(obs.unit), UnitSignature("currency", "USD"))
    for _ in range(2):
        FinancialNormalizer.normalize_observation(obs)
        assert obs.value is None and obs.normalized_value is None
        assert obs.raw_value == "12" and obs.display_value == "12  lumens/USD million"
    assert normalize_financial_fact("12", "lumens/USD million")[0] is None


def test_unsupported_compound_values_do_not_enter_mean_calculation():
    from adaptive_document_agent.agent.candidate_generator import AnalysisCandidateGenerator
    from adaptive_document_agent.agent.executor import AnalysisExecutor
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.models import AnalysisTask

    observations = ObservationExtractor()._table_observations(source_table([
        ["Light intensity (lumens/USD million)", "12", "14"],
    ]))
    assert AnalysisCandidateGenerator().generate(DocumentIndex(observations)) == []
    task = AnalysisTask(id="mean", title="Mean intensity", description="Mean reported intensity",
        analysis_type="mean", observation_query={"observation_ids": [o.id for o in observations]},
        reason="Comparable source coefficients", expected_output="Mean")
    result = AnalysisExecutor().execute([task], DocumentIndex(observations))[0]
    assert result.result is None and result.warnings
    assert result.input_observation_ids == []


def test_repair_stale_currency_interpretation_from_retained_source_label():
    obs = Observation(
        id="stale", metric_original="Resource intensity (m3/Revenue RMB’ million)",
        value=43_600_000, raw_value="43.60", raw_unit="RMB", unit="currency",
        currency="CNY", unit_scale=1e6, confidence=.8,
    )
    FinancialNormalizer.normalize_observation(obs)
    assert obs.value == pytest.approx(43.6 / 1e6)
    assert obs.raw_unit == "m3/Revenue RMB’ million"
    assert obs.currency is None and obs.normalized_unit == "compound:m3/CNY"
    assert obs.period is None


def test_compound_unit_dimensions_do_not_make_different_measurements_compatible():
    water = infer_unit_defaults("m3/Revenue RMB’ million")
    energy = infer_unit_defaults("MWh/Revenue RMB’ million")
    assert not compatible_units(UnitSignature(water.normalized_unit), UnitSignature(energy.normalized_unit))


def test_compound_column_header_and_unknown_period_remain_source_bound():
    table = source_table([["Site A", "1.2", "2.4"]])
    table.headers = ["Site", "kg/USD million", "kg/USD million"]
    table.column_periods = [None, None, None]
    obs = ObservationExtractor()._table_observations(table)[0]
    assert obs.period is None
    assert (obs.raw_unit, obs.unit, obs.currency) == ("kg/USD million", "compound:kg/USD", None)
    assert obs.value == pytest.approx(1.2e-6)


def test_standalone_compound_unit_scopes_following_rows_without_becoming_parent():
    table = source_table([
        ["(kg/USD million)", None, None],
        ["Reported intensity", "1.2", "2.4"],
    ])
    obs = ObservationExtractor()._table_observations(table)[0]
    assert obs.metric_original == "Reported intensity" and obs.parent_section is None
    assert (obs.raw_unit, obs.unit, obs.currency) == ("kg/USD million", "compound:kg/USD", None)
    assert obs.value == pytest.approx(1.2e-6)


def test_cached_compound_table_unit_recovers_dimension_before_cached_currency():
    table = source_table([["Reported intensity", "1.2", "2.4"]],
                         default_unit="currency", default_currency="USD", default_unit_scale=1e6,
                         default_raw_unit="kg/USD million")
    obs = ObservationExtractor()._table_observations(table)[0]
    assert obs.unit == "compound:kg/USD" and obs.currency is None
    assert obs.value == pytest.approx(1.2e-6)
