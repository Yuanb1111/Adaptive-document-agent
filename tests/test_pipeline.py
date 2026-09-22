import pymupdf
import pytest

from adaptive_document_agent.agent.executor import AnalysisExecutor
from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.agent.presentation_planner import PresentationPlanner
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import AnalysisTask, Observation
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName


def synthetic_time_series_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Revenue 2023 = 100\nRevenue 2024 = 120\nRevenue 2025 = 150")
    value = document.tobytes()
    document.close()
    return value


def test_complete_mock_free_pipeline_uses_python_for_calculations() -> None:
    result = DocumentOrchestrator().analyse_pdf(synthetic_time_series_pdf())
    assert result.document.page_count == 1
    assert len(result.observations) == 3
    assert any(task.analysis_type == "percentage_change" for task in result.analysis_plan)
    growth = next(item for item in result.analysis_results if item.task_id == next(task.id for task in result.analysis_plan if task.analysis_type == "percentage_change"))
    assert growth.result == 50
    assert growth.result_type == "calculated_result"
    assert growth.evidence
    assert "Calculated Result" in result.report_markdown


def test_scope_preview_selects_complete_small_document_without_deep_analysis() -> None:
    preview = DocumentOrchestrator().preview_scope(synthetic_time_series_pdf())
    assert preview.page_count == 1
    assert preview.selected_page_count == 1
    assert [(item.start_page, item.end_page) for item in preview.page_ranges] == [(1, 1)]


def test_monetary_share_pipeline_skips_old_table_cache_and_reuses_new_cache(monkeypatch):
    from adaptive_document_agent.agent import orchestrator
    from adaptive_document_agent.models.table import ExtractedTable, TableRow

    class MemoryCache:
        def __init__(self):
            self.values = {}
            self.requested = []

        def get_model(self, key, model):
            self.requested.append(key)
            assert not key.startswith(("tables-v9-", "tables-v10-")), "Old inferred roles and mixed periods must not be reused"
            value = self.values.get(key)
            return value.model_copy(deep=True) if value is not None else None

        def set_model(self, key, value):
            self.values[key] = value.model_copy(deep=True)

    calls = []

    def extract_tables(self, raw, *, page_numbers=None):
        calls.append(page_numbers)
        return {1: [ExtractedTable(
            table_id="share_amount", page=1, headers=["Metric", "2023", "2024"],
            column_periods=[None, "2023", "2024"], column_types=["label", "amount", "amount"],
            default_unit="currency", default_currency="USD", default_raw_unit="USD '000",
            default_unit_scale=1000,
            rows=[TableRow(cells=["Share of profit of an associate", "100", "125"], page=1)],
        )]}

    monkeypatch.setattr(orchestrator.TableExtractor, "extract", extract_tables)
    cache = MemoryCache()
    raw = synthetic_time_series_pdf()
    for _ in range(2):
        result = DocumentOrchestrator(cache=cache).analyse_pdf(raw)
        observations = [o for o in result.observations if o.metric_original == "Share of profit of an associate"]
        assert [o.value for o in observations] == [100000, 125000]
        assert all(o.unit_family == "currency" and o.unit_scale == 1000 for o in observations)
    assert len(calls) == 1
    assert any(key.startswith("tables-v11-") for key in cache.values)


def test_targeted_observations_extend_instead_of_replace_fact_base() -> None:
    broad = [Observation(id="broad", metric_original="Revenue", value=100, raw_value="100", confidence=0.9)]
    targeted = [
        Observation(id="broad", metric_original="Revenue", value=100, raw_value="100", confidence=0.9),
        Observation(id="new", metric_original="Margin", value=20, raw_value="20", unit="percent", confidence=0.9),
    ]
    merged = DocumentOrchestrator._merge_observations(broad, targeted)
    assert {item.id for item in merged} == {"broad", "new"}


def test_conflicting_same_context_values_block_calculation() -> None:
    observations = [
        Observation(id="a", metric_original="Measure", value=100, raw_value="100", period="2024", confidence=0.9),
        Observation(id="b", metric_original="Measure", value=120, raw_value="120", period="2024", confidence=0.9),
        Observation(id="c", metric_original="Measure", value=140, raw_value="140", period="2025", confidence=0.9),
    ]
    task = AnalysisTask(
        id="task_conflict",
        title="Measure change",
        description="Compare periods",
        analysis_type="absolute_change",
        tool_name="absolute_change",
        required_metrics=["measure"],
        observation_query={"observation_ids": [item.id for item in observations]},
        reason="Multiple periods exist",
        expected_output="number",
    )
    result = AnalysisExecutor().execute([task], DocumentIndex(observations))[0]
    assert result.result is None
    assert "conflict" in result.warnings[0].casefold()


def test_complete_pipeline_with_mock_llm_controls_semantic_selection() -> None:
    pdf = synthetic_time_series_pdf()
    baseline = DocumentOrchestrator().analyse_pdf(pdf)
    candidate_ids = [item.id for item in baseline.candidates]
    task = baseline.analysis_plan[0]
    responses = [
        {"summary": "Three-year revenue series", "metrics": ["Revenue"], "time_periods": ["2023", "2024", "2025"]},
        {
            "document_type": "Revenue performance report",
            "document_purpose": "Review revenue changes",
            "overview_title": "Revenue overview",
            "document_summary": "The document reports a three-year revenue series.",
            "document_summary_pages": [1],
            "metrics": ["Revenue"],
            "detected_time_periods": ["2023", "2024", "2025"],
        },
        {"mappings": [{"original_name": "Revenue", "canonical_name": "revenue", "confidence": 0.95, "reason": "Explicit context"}]},
        {"selected_candidate_ids": candidate_ids, "rationale": ["Revenue change is central to the document purpose."]},
        {"scores": [{"candidate_id": identifier, "score": 0.9, "reasons": ["Relevant and complete"], "rejected": False} for identifier in candidate_ids]},
        {"insights": [{"id": "insight_mock", "title": task.title, "narrative": "The validated series changed over the reported period.", "kind": "calculated_result", "confidence": 0.9, "result_ids": [task.id]}]},
        {"title": "Revenue Performance Analysis", "sections": [{"title": "Revenue Performance", "purpose": "Explain the validated change.", "insight_ids": ["insight_mock"]}]},
        {
            "title": "Revenue Performance Review",
            "report_type": "Performance analysis",
            "themes": [{"id": "revenue", "title": "Revenue movement", "question": "How did revenue change?",
                        "rationale": "The document contains one comparable series.",
                        "chart_ids": ["chart_eb76411966450f2e"], "insight_ids": ["insight_mock"], "source_pages": [1]}],
            "company": {
                "name": "Revenue document",
                "one_line_description": "A source document reporting a three-year revenue series.",
                "document_type": "Revenue performance report",
                "source_pages": [1],
            },
            "slides": [
                {"id": "cover", "slide_type": "cover", "title": "Revenue Performance Review", "message": "Three-year evidence review"},
                {"id": "overview", "slide_type": "company_overview", "title": "Document at a Glance", "source_pages": [1]},
                {"id": "summary", "slide_type": "executive_summary", "title": "Revenue changed across the reported period", "insight_ids": ["insight_mock"], "source_pages": [1]},
                {"id": "analysis", "slide_type": "analysis", "title": "Revenue rose across all reported years", "section_title": "Financial Performance", "message": "The reported series shows sustained growth.", "chart_ids": ["chart_eb76411966450f2e"], "insight_ids": ["insight_mock"], "source_pages": [1], "theme_id": "revenue", "analytical_question": "How did revenue change?", "selection_reason": "Revenue is the only comparable series in this document."},
                {"id": "quality", "slide_type": "data_quality", "title": "Data quality and methodology"},
                {"id": "appendix", "slide_type": "appendix", "title": "Source data"},
            ],
        },
    ]
    client = MockLLMClient(responses)
    settings = LLMSettings(provider=ProviderName.MOCK, model="mock")
    result = DocumentOrchestrator(LLMGateway(client, settings)).analyse_pdf(pdf)
    assert result.profile.document_type == "Revenue performance report"
    assert result.analysis_plan
    assert result.insights[0].evidence
    assert result.report_plan.sections[0].title == "Revenue Performance"
    assert result.presentation_plan is not None
    assert result.presentation_plan.slides[1].title == "Document at a Glance"
    assert "## Revenue overview" in result.report_markdown
    assert len(client.calls) == 8


def test_presentation_plan_failure_does_not_discard_completed_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = synthetic_time_series_pdf()
    baseline = DocumentOrchestrator().analyse_pdf(pdf)
    candidate_ids = [item.id for item in baseline.candidates]
    task = baseline.analysis_plan[0]
    responses = [
        {"summary": "Three-year revenue series", "metrics": ["Revenue"], "time_periods": ["2023", "2024", "2025"]},
        {
            "document_type": "Revenue performance report",
            "document_purpose": "Review revenue changes",
            "overview_title": "Revenue overview",
            "document_summary": "The document reports a three-year revenue series.",
            "document_summary_pages": [1],
            "metrics": ["Revenue"],
            "detected_time_periods": ["2023", "2024", "2025"],
        },
        {"mappings": [{"original_name": "Revenue", "canonical_name": "revenue", "confidence": 0.95, "reason": "Explicit context"}]},
        {"selected_candidate_ids": candidate_ids, "rationale": ["Revenue change is central."]},
        {"scores": [{"candidate_id": identifier, "score": 0.9, "reasons": ["Supported"], "rejected": False} for identifier in candidate_ids]},
        {"insights": [{"id": "insight_mock", "title": task.title, "narrative": "Revenue changed across the period.", "kind": "calculated_result", "confidence": 0.9, "result_ids": [task.id]}]},
        {"title": "Revenue Analysis", "sections": [{"title": "Revenue", "purpose": "Explain the change.", "insight_ids": ["insight_mock"]}]},
    ]
    client = MockLLMClient(responses)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))

    def fail_plan(self: PresentationPlanner, result: object) -> None:
        raise ValueError("invalid presentation plan")

    monkeypatch.setattr(PresentationPlanner, "plan", fail_plan)
    result = DocumentOrchestrator(gateway).analyse_pdf(pdf)

    assert result.presentation_plan is not None
    assert result.report_markdown
    assert any(issue.code == "presentation_plan_failed" for issue in result.validation_warnings)
    assert any(issue.code == "presentation_plan_fallback" for issue in result.validation_warnings)
