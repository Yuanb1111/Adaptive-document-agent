"""Evidence defaults, calculation precision, annualization and analysis identity."""

import pytest

from adaptive_document_agent.models import AnalysisCandidate, AnalysisTask, CandidateScore, Observation
from adaptive_document_agent.agent.analysis_planner import AnalysisPlanner
from adaptive_document_agent.agent.candidate_generator import AnalysisCandidateGenerator
from adaptive_document_agent.agent.executor import AnalysisExecutor
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer
from adaptive_document_agent.services.financial_formatter import normalize_raw_unit


def observation(identifier="o", metric="Revenue", value=100.0, **kwargs):
    return Observation(
        id=identifier, metric_original=metric, value=value, raw_value=str(value),
        confidence=0.95, **kwargs,
    )


@pytest.mark.parametrize("metric", ["Revenue", "Employee count"])
def test_missing_currency_and_accounting_basis_stay_unknown(metric):
    item = observation(metric=metric)
    FinancialNormalizer.normalize_observation(item)
    assert item.currency is None
    assert item.ifrs_status == "UNSPECIFIED"
    assert "RMB" not in item.display_unit


@pytest.mark.parametrize("status", ["IFRS", "NON_IFRS", "ADJUSTED"])
def test_existing_source_accounting_basis_is_preserved(status):
    item = observation(ifrs_status=status)
    FinancialNormalizer.normalize_observation(item)
    assert item.ifrs_status == status


@pytest.mark.parametrize("label,status", [
    ("Revenue (IFRS)", "IFRS"),
    ("Adjusted revenue (Non-IFRS)", "ADJUSTED"),
    ("Revenue (US GAAP)", "UNSPECIFIED"),
])
def test_only_explicit_accounting_qualifiers_are_classified(label, status):
    item = observation(metric=label)
    FinancialNormalizer.normalize_observation(item)
    assert item.ifrs_status == status


def test_source_currency_and_raw_unit_are_preserved():
    item = observation(currency="USD", raw_unit="USD in thousands")
    FinancialNormalizer.normalize_observation(item)
    assert item.currency == "US$"
    assert item.raw_unit == "USD in thousands"
    explicit_unit = observation(raw_unit="USD in thousands")
    FinancialNormalizer.normalize_observation(explicit_unit)
    assert explicit_unit.currency == "US$"
    unknown = observation(raw_unit="in thousands")
    FinancialNormalizer.normalize_observation(unknown)
    assert unknown.currency is None
    assert unknown.raw_unit == "in thousands"
    assert "RMB" not in normalize_raw_unit(unknown.raw_unit)


def test_unknown_currency_is_not_invented_by_export_or_movement_formatters():
    from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric, format_metric_display_value
    from adaptive_document_agent.services.financial_formatter import format_compact_currency, format_financial_movement
    from adaptive_document_agent.services.movement_formatter import FinancialMovementFormatter
    from adaptive_document_agent.services.pptx_export import _appendix_display_unit, _display_source_unit, _unit_label

    item = observation()
    FinancialNormalizer.normalize_observation(item)
    semantic = classify_metric(item.metric_original, unit=item.unit)
    displays = [
        _appendix_display_unit(item, semantic), _display_source_unit(item), _unit_label([item], ""),
        _unit_label([item], "millions"), format_compact_currency(100),
        format_compact_currency(100, raw_unit="unaudited in thousands"),
        format_metric_display_value("100", 100, semantic, raw_unit="in thousands"),
        format_financial_movement("Revenue", 100, 120),
        FinancialMovementFormatter.format_movement("Revenue", 100, 120),
    ]
    assert all("RMB" not in value for value in displays)
    assert all("AUD" not in value for value in displays)
    assert _appendix_display_unit(item, semantic) == "million (currency unspecified)"
    movement = FinancialMovementFormatter.format_movement("Loss", -1.57, -.83, scale=1e9)
    assert "0.74bn" in movement and "RMB" not in movement


@pytest.mark.parametrize("value", [4e-7, 1.23456789, 1.230004, 53.60000000000001])
def test_normalization_and_canonical_conversion_keep_calculation_precision(value):
    item = observation(value=value)
    raw = item.raw_value
    FinancialNormalizer.normalize_observation(item)
    FinancialNormalizer.to_canonical_facts([item])
    assert item.value == value
    assert item.raw_value == raw
    assert float(item.display_value.replace(",", "")) != 0


def execute_cagr(periods, values):
    items = [observation(str(i), period=p, value=v) for i, (p, v) in enumerate(zip(periods, values))]
    task = AnalysisTask(
        id="cagr", title="Annual growth", description="", analysis_type="cagr",
        tool_name="cagr", observation_query={"observation_ids": [o.id for o in items]},
        reason="", expected_output="number",
    )
    return AnalysisExecutor().execute([task], DocumentIndex(items))[0]


@pytest.mark.parametrize("periods,values", [
    (["2020", "2022", "2024"], [100, 121, 146.41]),
    (["FY2020", "2024", "FY2022"], [100, 146.41, 121]),
    (["2020", "2024"], [100, 146.41]),
    (["Year ended 31 December 2020", "Year ended 31 December 2024"], [100, 146.41]),
])
def test_cagr_uses_elapsed_years_and_chronological_endpoints(periods, values):
    result = execute_cagr(periods, values)
    assert result.result == pytest.approx(10)
    assert not result.warnings


@pytest.mark.parametrize("periods", [
    ["Q1 2024", "Q2 2024"], ["2020", None], ["2024", "FY2024"],
    ["2020/2021", "2023/2024"], ["previous", "current"],
    ["Year ended 30 June 2020", "Year ended 31 December 2024"],
])
def test_cagr_rejects_ambiguous_or_nonannual_periods(periods):
    result = execute_cagr(periods, [100, 121])
    assert result.result is None
    assert result.warnings


def test_cagr_candidates_require_known_annual_span():
    quarterly = DocumentIndex([observation(str(i), period=p, value=v) for i, (p, v) in enumerate([
        ("Q1 2024", 100), ("Q2 2024", 110), ("Q3 2024", 121),
    ])])
    assert all(c.analysis_type != "cagr" for c in AnalysisCandidateGenerator().generate(quarterly))
    annual = DocumentIndex([observation("a", period="2020"), observation("b", period="2024", value=146.41)])
    assert any(c.analysis_type == "cagr" for c in AnalysisCandidateGenerator().generate(annual))


def test_rankings_for_each_year_survive_planning():
    items = [observation(str(i), period=p, value=v, dimensions={"region": r})
             for i, (p, r, v) in enumerate([
                 ("2024", "East", 100), ("2024", "West", 200),
                 ("2025", "East", 110), ("2025", "West", 220),
             ])]
    index = DocumentIndex(items)
    candidates = [c for c in AnalysisCandidateGenerator().generate(index) if c.analysis_type == "rank_values"]
    tasks = AnalysisPlanner().plan([CandidateScore(candidate=c, score=.9) for c in candidates], index)
    assert len(tasks) == 2
    assert {frozenset(t.observation_query["observation_ids"]) for t in tasks} == {
        frozenset(["0", "1"]), frozenset(["2", "3"]),
    }


def test_distinct_dimensions_and_entities_survive_but_duplicate_evidence_does_not():
    items = [observation(str(i), period="2024", entity=e,
                         dimensions={"product": product, "region": region}, value=value)
             for i, (e, product, region, value) in enumerate([
                 ("A", "P1", "East", 100), ("A", "P2", "West", 200),
                 ("B", "P1", "East", 110), ("B", "P2", "West", 220),
             ])]
    candidates = [AnalysisCandidate(
        id=identifier, title=identifier, analysis_type="rank_values", metric="revenue",
        dimensions=[dim], observation_ids=ids, reason="Compare categories",
    ) for identifier, dim, ids in [
        ("region_a", "region", ["0", "1"]), ("product_a", "product", ["0", "1"]),
        ("region_b", "region", ["2", "3"]), ("duplicate", "region", ["1", "0"]),
    ]]
    index = DocumentIndex(items)
    tasks = AnalysisPlanner().plan([
        CandidateScore(candidate=c, score=.5 if c.id == "duplicate" else .9) for c in candidates
    ], index)
    assert {t.id for t in tasks} == {"region_a", "product_a", "region_b"}
    rankings = {r.task_id: r.result for r in AnalysisExecutor().execute(tasks, index)}
    assert {row["label"] for row in rankings["region_a"]} == {"East", "West"}
    assert {row["label"] for row in rankings["product_a"]} == {"P1", "P2"}
