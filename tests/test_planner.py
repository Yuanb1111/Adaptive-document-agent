from adaptive_document_agent.agent import AnalysisCandidateGenerator, AnalysisPlanner, AnalysisValueScorer
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import DocumentProfile, Observation
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName


def make_observation(identifier: str, period: str, value: float) -> Observation:
    return Observation(id=identifier, metric_original="Revenue", value=value, raw_value=str(value), period=period, confidence=0.9)


def test_time_series_generates_growth_and_trend_but_no_correlation() -> None:
    index = DocumentIndex([make_observation("a", "2023", 100), make_observation("b", "2024", 120), make_observation("c", "2025", 150)])
    candidates = AnalysisCandidateGenerator().generate(index)
    kinds = {candidate.analysis_type for candidate in candidates}
    assert {"absolute_change", "percentage_change", "linear_trend", "cagr"} <= kinds
    assert "pearson_correlation" not in kinds
    scores = AnalysisValueScorer().score(candidates, index, DocumentProfile(document_purpose="Revenue performance", metrics=["Revenue"]))
    tasks = AnalysisPlanner().plan(scores, index)
    assert tasks
    assert all(task.required_metrics == ["revenue"] for task in tasks)


def test_single_value_does_not_generate_growth() -> None:
    index = DocumentIndex([make_observation("a", "2025", 130)])
    assert AnalysisCandidateGenerator().generate(index) == []


def test_generic_page_metric_is_not_an_analysis_candidate() -> None:
    values = [
        Observation(id=f"p{year}", metric_original="Page", value=float(year), raw_value=str(year), period=str(year), confidence=0.9)
        for year in (2023, 2024, 2025)
    ]
    assert AnalysisCandidateGenerator().generate(DocumentIndex(values)) == []


def test_empty_llm_selection_falls_back_to_bounded_supported_candidates() -> None:
    observations = [
        Observation(
            id=f"{metric}-{year}",
            metric_original=metric,
            value=float(year),
            raw_value=str(year),
            period=str(year),
            confidence=0.9,
        )
        for metric_index in range(60)
        for metric in [f"Metric {metric_index}"]
        for year in (2023, 2024, 2025)
    ]
    client = MockLLMClient([{"selected_candidate_ids": [], "rationale": []}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))
    candidates = AnalysisCandidateGenerator(gateway).generate(DocumentIndex(observations), DocumentProfile())
    assert 0 < len(candidates) <= 160
    assert "data_supported_candidates" in client.calls[0][1]["content"]


def test_period_analysis_uses_one_comparable_dimension_series() -> None:
    values = [
        Observation(
            id=f"{region}-{year}",
            metric_original="Revenue",
            value=value,
            raw_value=str(value),
            period=str(year),
            dimensions={"region": region},
            confidence=0.9,
        )
        for region, amounts in (("East", (100, 120)), ("West", (80, 90)))
        for year, value in zip((2024, 2025), amounts, strict=True)
    ]
    candidates = AnalysisCandidateGenerator().generate(DocumentIndex(values))
    assert candidates
    for candidate in candidates:
        if candidate.analysis_type not in {"absolute_change", "percentage_change", "linear_trend", "cagr"}:
            continue
        regions = {next(item for item in values if item.id == identifier).dimensions["region"] for identifier in candidate.observation_ids}
        assert len(regions) == 1


def test_period_analysis_uses_one_source_consistent_sign_convention() -> None:
    from adaptive_document_agent.models import SourceEvidence

    observations = []
    for year, amount in ((2023, 100.0), (2024, 120.0), (2025, 140.0)):
        observations.extend(
            [
                Observation(
                    id=f"statement-{year}",
                    metric_original="Expense",
                    value=-amount,
                    raw_value=f"({int(amount)})",
                    period=f"FY{year}",
                    unit="currency",
                    currency="CNY",
                    evidence=[SourceEvidence(page=1, text=str(amount), table_id="statement", extraction_method="digital_table", confidence=0.9)],
                    confidence=0.9,
                ),
                Observation(
                    id=f"analysis-{year}",
                    metric_original="Expense",
                    value=amount,
                    raw_value=str(int(amount)),
                    period=f"FY{year}",
                    unit="currency",
                    currency="CNY",
                    evidence=[SourceEvidence(page=2, text=str(amount), table_id="analysis", extraction_method="digital_table", confidence=0.8)],
                    confidence=0.8,
                ),
            ]
        )
    candidates = AnalysisCandidateGenerator().generate(DocumentIndex(observations))
    period_candidates = [candidate for candidate in candidates if candidate.analysis_type == "linear_trend"]
    assert len(period_candidates) == 1
    assert set(period_candidates[0].observation_ids) == {"statement-2023", "statement-2024", "statement-2025"}


def test_cagr_is_not_proposed_for_nonpositive_start_value() -> None:
    values = [
        Observation(id=f"x{year}", metric_original="Profit", value=value, raw_value=str(value), period=str(year), confidence=0.9)
        for year, value in ((2023, -10.0), (2024, 5.0), (2025, 20.0))
    ]
    kinds = {candidate.analysis_type for candidate in AnalysisCandidateGenerator().generate(DocumentIndex(values))}
    assert "cagr" not in kinds


def test_internal_period_basis_does_not_become_a_category_analysis() -> None:
    values = [
        Observation(
            id=f"{basis}-{year}",
            metric_original="Revenue",
            value=value,
            raw_value=str(value),
            period=f"{basis}{year}",
            dimensions={"period_basis": basis},
            confidence=0.9,
        )
        for basis, years in (("FY", ((2023, 100.0), (2024, 120.0))), ("6M", ((2023, 50.0), (2024, 60.0))))
        for year, value in years
    ]
    candidates = AnalysisCandidateGenerator().generate(DocumentIndex(values))
    assert all("period_basis" not in candidate.dimensions for candidate in candidates)


def test_correlation_requires_five_actual_context_matched_pairs() -> None:
    observations = [
        Observation(id=f"left-{year}", metric_original="Left", value=float(year), raw_value=str(year), period=str(year), confidence=0.9)
        for year in range(2020, 2025)
    ] + [
        Observation(id=f"right-{year}", metric_original="Right", value=float(year * 2), raw_value=str(year * 2), period=str(year), confidence=0.9)
        for year in range(2021, 2026)
    ]
    candidates = AnalysisCandidateGenerator().generate(DocumentIndex(observations))
    assert all(candidate.analysis_type != "pearson_correlation" for candidate in candidates)
