import fitz

from adaptive_document_agent.agent.executor import AnalysisExecutor
from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import AnalysisTask, Observation
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName


def synthetic_time_series_pdf() -> bytes:
    document = fitz.open()
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
    ]
    client = MockLLMClient(responses)
    settings = LLMSettings(provider=ProviderName.MOCK, model="mock")
    result = DocumentOrchestrator(LLMGateway(client, settings)).analyse_pdf(pdf)
    assert result.profile.document_type == "Revenue performance report"
    assert result.analysis_plan
    assert result.insights[0].evidence
    assert result.report_plan.sections[0].title == "Revenue Performance"
    assert "## Revenue overview" in result.report_markdown
    assert len(client.calls) == 7
