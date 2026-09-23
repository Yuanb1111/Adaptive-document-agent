"""No paid model calls: regression checks for bounded, evidence-preserving speedups."""

from contextlib import nullcontext
from threading import Barrier, Lock, get_ident
from types import SimpleNamespace
from unittest.mock import Mock
import time

import pytest

from adaptive_document_agent.agent.document_discovery import ChunkDiscovery, DocumentDiscovery
from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from adaptive_document_agent.utils.caching import DiskCache
from adaptive_document_agent.utils.chunking import DocumentChunk
from adaptive_document_agent.services import export
from adaptive_document_agent.services.presentation_visual_qa import VisualQAError
from adaptive_document_agent.services.qa_reporter import CriticalQAError, QAItem, QAReport
from adaptive_document_agent.ui import exports
from tests.test_pipeline import synthetic_time_series_pdf
from tests.test_pdf_fonts import report
from tests.test_p2_visual_qa import deck_bytes
from tests.ppt_render_stub import LocalRenderStub


def chunks(count=6):
    return [DocumentChunk(chunk_id=f"chunk-{i}", start_page=i, end_page=i,
                          estimated_tokens=10, text=f"[PAGE {i}]\nEvidence {i}") for i in range(1, count + 1)]


def test_concurrent_discovery_is_bounded_ordered_and_progress_stays_on_ui_thread(monkeypatch):
    discovery = DocumentDiscovery(SimpleNamespace(discovery_workers=3))
    barrier, lock = Barrier(3), Lock()
    active = peak = 0
    completed = []
    main_thread = get_ident()
    notifications = []

    def work(chunk):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=5)
        time.sleep((3 - (chunk.start_page - 1) % 3) * .01)
        with lock:
            completed.append(chunk.start_page)
            active -= 1
        return ChunkDiscovery(summary=str(chunk.start_page))

    monkeypatch.setattr(discovery, "_discover_chunk", work)
    output = discovery._discover_chunks(chunks(), lambda text: notifications.append((get_ident(), text)))
    assert [item.summary for item in output] == list(map(str, range(1, 7)))
    assert peak == 3 and completed != list(range(1, 7))
    assert all(thread_id == main_thread for thread_id, _ in notifications)
    assert "6/6" in notifications[-1][1]


def test_failed_chunk_does_not_produce_partial_discovery(monkeypatch):
    discovery = DocumentDiscovery(SimpleNamespace(discovery_workers=3))
    monkeypatch.setattr(discovery, "_discover_chunk", Mock(side_effect=LLMResponseError("failed")))
    with pytest.raises(LLMResponseError):
        discovery._discover_chunks(chunks(), lambda _: None)


@pytest.mark.parametrize("provider,url,opt_in,expected", [
    (ProviderName.OPENAI, None, True, 4),
    (ProviderName.OPENAI, None, False, 1),
    (ProviderName.OLLAMA, None, True, 1),
    (ProviderName.OPENAI_COMPATIBLE, "http://127.0.0.1:8000/v1", True, 1),
])
def test_worker_count_respects_local_and_stateful_clients(provider, url, opt_in, expected):
    client = MockLLMClient()
    client.supports_concurrent_requests = opt_in
    gateway = LLMGateway(client, LLMSettings(provider=provider, base_url=url))
    assert gateway.discovery_workers == expected


def test_discovery_workers_config_is_bounded(monkeypatch):
    monkeypatch.setenv("LLM_DISCOVERY_WORKERS", "1")
    assert LLMSettings.from_env().discovery_workers == 1
    with pytest.raises(ValueError):
        LLMSettings(discovery_workers=100)


def test_successful_chunk_checkpoint_survives_retry_without_new_model_calls(tmp_path):
    cache = DiskCache(tmp_path)
    settings = LLMSettings(provider=ProviderName.MOCK, model="mock")
    client = MockLLMClient([{"summary": "Grounded page 1"}])
    first = DocumentDiscovery(LLMGateway(client, settings), cache=cache)._discover_chunk(chunks(1)[0])
    first.summary = "mutated caller value"
    retry_client = MockLLMClient([])
    retry = DocumentDiscovery(LLMGateway(retry_client, settings), cache=cache)._discover_chunk(chunks(1)[0])
    assert retry.summary == "Grounded page 1"
    assert not retry_client.calls


@pytest.mark.parametrize("change", ["content", "model", "endpoint", "privacy", "temperature", "prompt"])
def test_chunk_checkpoint_invalidates_when_request_changes(tmp_path, monkeypatch, change):
    cache = DiskCache(tmp_path)
    settings = LLMSettings(provider=ProviderName.MOCK, model="mock")
    client = MockLLMClient([{"summary": "first"}, {"summary": "second"}])
    gateway = LLMGateway(client, settings)
    discovery = DocumentDiscovery(gateway, cache=cache)
    chunk = chunks(1)[0]
    discovery._discover_chunk(chunk)
    if change == "content":
        chunk.text += " changed evidence"
    elif change == "model":
        settings.stage_models["discovery"] = "different-model"
    elif change == "endpoint":
        settings.base_url = "http://localhost:8001"
    elif change == "privacy":
        from adaptive_document_agent.services.llm.config import PrivacyMode
        settings.privacy_mode = PrivacyMode.LOCAL_ONLY
    elif change == "temperature":
        settings.temperature = .5
    else:
        monkeypatch.setattr("adaptive_document_agent.agent.document_discovery.load_prompt", lambda _: "Changed rules")
    assert discovery._discover_chunk(chunk).summary == "second"
    assert len(client.calls) == 2


def test_failed_discovery_is_not_checkpointed(tmp_path):
    client = MockLLMClient(["invalid", "invalid"])
    discovery = DocumentDiscovery(LLMGateway(client, LLMSettings(provider=ProviderName.MOCK)), cache=DiskCache(tmp_path))
    with pytest.raises(LLMResponseError):
        discovery._discover_chunk(chunks(1)[0])
    assert not list(tmp_path.glob("*.json"))


def test_targeted_analysis_reuses_broad_extraction_and_preserves_evidence(monkeypatch):
    original = ObservationExtractor.extract
    calls = []

    def tracking(self, document, **kwargs):
        calls.append(kwargs)
        return original(self, document, **kwargs)

    monkeypatch.setattr(ObservationExtractor, "extract", tracking)
    result = DocumentOrchestrator().analyse_pdf(synthetic_time_series_pdf())
    # This sparse synthetic fixture still needs its legitimate recovery pass.
    assert len(calls) == 2
    assert all("required_metrics" not in call for call in calls)
    assert result.analysis_results and result.observations
    assert all(obs.raw_value and obs.evidence for obs in result.observations)


def export_setup(monkeypatch, tmp_path):
    template = tmp_path / "template.pptx"
    template.write_bytes(b"template-v1")
    monkeypatch.setattr("adaptive_document_agent.services.pptx_export._resolve_template_path", lambda _: template)
    builder = Mock(return_value=deck_bytes())
    monkeypatch.setattr(export, "build_presentation", builder)
    qa = Mock(return_value=QAReport(document_title="Report"))
    monkeypatch.setattr("adaptive_document_agent.services.qa_reporter.run_comprehensive_qa", qa)
    return builder, qa, template


def test_ppt_build_reuse_keeps_financial_qa_and_content_renderer_validation(monkeypatch, tmp_path):
    builder, financial_qa, _ = export_setup(monkeypatch, tmp_path)
    result, build_cache, visual_cache = report("# Report"), {}, {}
    renderer = LocalRenderStub()
    first = export.export_pptx_with_report(result, renderer=renderer, build_cache=build_cache, visual_cache=visual_cache)
    second = export.export_pptx_with_report(result, renderer=renderer, build_cache=build_cache, visual_cache=visual_cache)
    assert first.payload == second.payload
    assert second.build_cache_hit and second.report.cache_hit
    assert builder.call_count == renderer.calls == 1
    assert financial_qa.call_count == 2
    assert "rendered_qa" in second.timings_ms


@pytest.mark.parametrize("change", ["content", "template"])
def test_ppt_build_cache_invalidates(monkeypatch, tmp_path, change):
    builder, _, template = export_setup(monkeypatch, tmp_path)
    result, cache = report("# Report"), {}
    export.export_pptx_with_report(result, renderer=LocalRenderStub(), build_cache=cache)
    if change == "content":
        result.report_markdown += "\nNew evidence"
    else:
        template.write_bytes(b"template-v2")
    export.export_pptx_with_report(result, renderer=LocalRenderStub(), build_cache=cache)
    assert builder.call_count == 2
    assert len(cache) == 1


def test_ppt_build_cache_never_bypasses_new_critical_qa(monkeypatch, tmp_path):
    _, financial_qa, _ = export_setup(monkeypatch, tmp_path)
    result, cache = report("# Report"), {}
    export.export_pptx_with_report(result, renderer=LocalRenderStub(), build_cache=cache)
    financial_qa.return_value = QAReport(document_title="Report", critical_errors=[
        QAItem(code="ambiguous", severity="CRITICAL", message="Ambiguous data")])
    with pytest.raises(CriticalQAError):
        export.export_pptx_with_report(result, renderer=LocalRenderStub(), build_cache=cache)


def test_failed_render_is_not_cached_as_success(monkeypatch, tmp_path):
    builder, _, _ = export_setup(monkeypatch, tmp_path)
    builder.return_value = deck_bytes(x=40)
    cache = {}
    with pytest.raises(VisualQAError):
        export.export_pptx_with_report(report("# Report"), renderer=LocalRenderStub(), build_cache=cache)
    assert cache == {}


def test_renderer_change_still_renders_with_reused_native_build(monkeypatch, tmp_path):
    builder, _, _ = export_setup(monkeypatch, tmp_path)
    result, build_cache, visual_cache = report("# Report"), {}, {}
    export.export_pptx_with_report(result, renderer=LocalRenderStub(), build_cache=build_cache, visual_cache=visual_cache)

    class ChangedRenderer(LocalRenderStub):
        identity = "different-renderer-version"

    renderer = ChangedRenderer()
    exported = export.export_pptx_with_report(result, renderer=renderer, build_cache=build_cache, visual_cache=visual_cache)
    assert exported.build_cache_hit and not exported.report.cache_hit
    assert builder.call_count == 1 and renderer.calls == 1


def test_pdf_is_lazy_cached_and_invalidated_by_report_content(monkeypatch):
    pdf = Mock(return_value=b"%PDF valid")
    monkeypatch.setattr(exports, "export_pdf", pdf)
    st, cache, result = Mock(), {}, report("# Report")
    columns = tuple(nullcontext() for _ in range(3))
    st.button.return_value = False
    exports.render_report_downloads(st, result, columns, pdf_cache=cache)
    assert pdf.call_count == 0
    st.button.return_value = True
    exports.render_report_downloads(st, result, columns, pdf_cache=cache)
    exports.render_report_downloads(st, result, columns, pdf_cache=cache)
    assert pdf.call_count == 1
    result.report_markdown = "# Changed"
    st.button.return_value = False
    exports.render_report_downloads(st, result, columns, pdf_cache=cache)
    assert pdf.call_count == 1 and cache == {}
