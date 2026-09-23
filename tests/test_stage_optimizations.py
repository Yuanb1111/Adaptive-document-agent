"""Regression tests for generic speedups; no paid providers or real documents."""

import json
from contextlib import nullcontext
from threading import Barrier, get_ident
from types import SimpleNamespace, ModuleType
import sys

import pytest
from pydantic import BaseModel

from adaptive_document_agent.agent.discovery_compaction import compact_discoveries
from adaptive_document_agent.agent.document_discovery import ChunkDiscovery, DocumentDiscovery
from adaptive_document_agent.agent import output_planning
from adaptive_document_agent.agent.candidate_generator import AnalysisCandidateGenerator
from adaptive_document_agent.agent.value_scorer import AnalysisValueScorer
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import DocumentProfile
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.exceptions import LLMTransportError
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.utils.caching import DiskCache
from tests.test_performance import chunks
from tests.test_planner import make_observation


class Answer(BaseModel):
    value: int


def test_combined_candidate_decisions_keep_rejection_and_missing_reasons():
    index = DocumentIndex([make_observation(str(y), str(y), v) for y, v in [(2023, 100), (2024, 120), (2025, 150)]])
    candidates = AnalysisCandidateGenerator().generate(index)
    client = MockLLMClient([{"scores": [
        {"candidate_id": candidates[0].id, "score": .9, "rejected": False, "reasons": ["central"]},
        {"candidate_id": candidates[1].id, "score": .2, "rejected": True, "reasons": ["redundant"]},
        {"candidate_id": "invented", "score": 1, "rejected": False},
    ]}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))
    scores = AnalysisValueScorer(gateway).score(candidates, index, DocumentProfile())
    assert len(client.calls) == 1
    assert len(scores) == len(candidates)
    assert sum(not item.rejected for item in scores) == 1
    assert any("redundant" in item.reasons for item in scores)
    assert any("model omitted candidate decision" in item.reasons for item in scores)


def test_compact_catalog_preserves_all_terms_conflicts_and_pages():
    values = [ChunkDiscovery(summary=f"Section {i}", metrics=["Revenue", "Gross revenue", f"unique{i}"],
                             data_quality_notes=[f"conflict{i}"]) for i in range(40)]
    payload = json.loads(compact_discoveries(chunks(40), values))
    assert len(payload["catalog"]["metrics"]) == 42
    assert payload["catalog"]["metrics"]["Revenue"] == list(range(40))
    assert payload["chunks"][39]["pages"] == [40, 40]
    assert "conflict39" in payload["catalog"]["data_quality_notes"]


@pytest.mark.parametrize("stage", ["discovery", "semantic", "insight", "report", "presentation"])
def test_stage_checkpoint_reuses_success_and_respects_model(stage, tmp_path):
    client = MockLLMClient([{"value": 1}, {"value": 2}])
    settings = LLMSettings(provider=ProviderName.MOCK, model="a")
    gateway = LLMGateway(client, settings, cache=DiskCache(tmp_path))
    first = gateway.generate_structured([], Answer, stage=stage)
    first.value = 99
    assert gateway.generate_structured([], Answer, stage=stage).value == 1
    settings.stage_models[stage] = "b"
    assert gateway.generate_structured([], Answer, stage=stage).value == 2
    assert len(client.calls) == 2
    assert gateway.usage[1]["cache_hit"]


def test_format_repair_uses_bad_output_not_original_document():
    client = MockLLMClient(['{"value":7,}', {"value": 7}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))
    assert gateway.generate_structured([{"role": "user", "content": "large-secret-document"}], Answer, stage="insight").value == 7
    repair = str(client.calls[1])
    assert "large-secret-document" not in repair
    assert '"value":7' in repair and "FORMAT ONLY" in repair
    assert [row["status"] for row in gateway.usage] == ["invalid_format", "format_repair"]


def test_transport_failure_has_two_attempts_not_a_third_format_request(monkeypatch):
    calls = []
    module = ModuleType("litellm")
    def completion(**kwargs):
        calls.append(kwargs)
        raise TimeoutError("no response")
    module.completion = completion
    monkeypatch.setitem(sys.modules, "litellm", module)
    settings = LLMSettings(provider=ProviderName.OPENAI, model="test")
    gateway = LLMGateway(LiteLLMProvider(settings), settings)
    with pytest.raises(LLMTransportError):
        gateway.generate_structured([], Answer, stage="report")
    assert len(calls) == 2
    assert len(gateway.usage[0]["attempts"]) == 2
    assert gateway.usage[0]["stage"] == "report"


def test_output_planners_overlap_without_report_dependency(monkeypatch):
    barrier = Barrier(2)
    threads = []
    def report(*args):
        threads.append(get_ident())
        barrier.wait(timeout=3)
        return "report"
    def topics(result):
        assert not hasattr(result, "report_plan")
        threads.append(get_ident())
        barrier.wait(timeout=3)
        return "topics"
    monkeypatch.setattr(output_planning, "DynamicReportPlanner", lambda g: SimpleNamespace(plan=report))
    monkeypatch.setattr(output_planning, "PresentationTopicSelector", lambda g: SimpleNamespace(select=topics))
    assert output_planning.plan_outputs(SimpleNamespace(discovery_workers=4), SimpleNamespace(profile=None, insights=[])) == ("report", "topics", None)
    assert len(set(threads)) == 2


def test_force_bypasses_chunk_and_gateway_model_caches(tmp_path):
    cache = DiskCache(tmp_path)
    client = MockLLMClient([{"summary": "first"}, {"summary": "fresh"}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK), cache=cache)
    discovery = DocumentDiscovery(gateway, cache=cache)
    assert discovery._discover_chunk(chunks(1)[0]).summary == "first"
    gateway.cache_enabled = False
    assert discovery._discover_chunk(chunks(1)[0]).summary == "fresh"


def test_sidebar_connects_stage_models_and_does_not_carry_to_other_provider(monkeypatch):
    from adaptive_document_agent.ui.sidebar import render_sidebar
    defaults = LLMSettings(provider=ProviderName.OPENAI, model="main", stage_models={"discovery": "fast"})
    monkeypatch.setattr(LLMSettings, "from_env", lambda: defaults)
    class UI:
        sidebar = nullcontext()
        provider = "OpenAI"
        def selectbox(self, label, options, **kwargs):
            return self.provider if label == "Provider" else "Auto"
        def text_input(self, label, value="", **kwargs):
            return value
        def expander(self, *args):
            return nullcontext()
        def __getattr__(self, name):
            return lambda *args, **kwargs: None
    ui = UI()
    assert render_sidebar(ui, public_deployment=False).stage_models == {"discovery": "fast"}
    ui.provider = "DeepSeek"
    assert render_sidebar(ui, public_deployment=False).stage_models == {}


@pytest.mark.parametrize("provider,endpoint,prefix", [
    (ProviderName.OLLAMA, None, "ollama/"),
    (ProviderName.OPENAI_COMPATIBLE, "http://localhost:8000/v1", "openai/"),
])
def test_local_stage_names_cannot_switch_provider(provider, endpoint, prefix):
    from adaptive_document_agent.services.llm import PrivacyMode
    settings = LLMSettings(provider=provider, base_url=endpoint,
                           privacy_mode=PrivacyMode.LOCAL_ONLY,
                           stage_models={"discovery": "anthropic/some-model"})
    client = LiteLLMProvider(settings)
    assert client._litellm_model(settings.model_for("discovery")) == prefix + "anthropic/some-model"


@pytest.mark.parametrize("change", ["prompt", "schema", "endpoint", "privacy", "temperature", "stage"])
def test_gateway_cache_invalidates_changed_request(tmp_path, change):
    class OtherAnswer(BaseModel):
        value: int
        reason: str = ""
    from adaptive_document_agent.services.llm import PrivacyMode
    settings = LLMSettings(provider=ProviderName.MOCK, model="test")
    client = MockLLMClient([{"value": 1}, {"value": 2}])
    gateway = LLMGateway(client, settings, cache=DiskCache(tmp_path))
    gateway.generate_structured([], Answer, stage="discovery")
    messages, schema, stage = [], Answer, "discovery"
    if change == "prompt":
        messages = [{"role": "user", "content": "new"}]
    elif change == "schema":
        schema = OtherAnswer
    elif change == "endpoint":
        settings.base_url = "http://localhost:8000"
    elif change == "privacy":
        settings.privacy_mode = PrivacyMode.LOCAL_ONLY
    elif change == "temperature":
        settings.temperature = .5
    else:
        stage = "semantic"
    assert gateway.generate_structured(messages, schema, stage=stage).value == 2
    assert len(client.calls) == 2


def test_failed_structured_output_not_checkpointed_and_sessions_isolated(tmp_path):
    from adaptive_document_agent.services.llm.exceptions import LLMResponseError
    from adaptive_document_agent.ui.deployment import cache_for_session
    # Keep temporary-directory owners alive for the complete check.
    first_session, second_session = {}, {}
    first_cache = cache_for_session(first_session, public_deployment=True, temporary_root=tmp_path)
    second_cache = cache_for_session(second_session, public_deployment=True, temporary_root=tmp_path)
    settings = LLMSettings(provider=ProviderName.MOCK)
    bad = LLMGateway(MockLLMClient(["bad", "still bad"]), settings, cache=first_cache)
    with pytest.raises(LLMResponseError):
        bad.generate_structured([], Answer, stage="discovery")
    assert not list(first_cache.root.glob("*.json"))
    LLMGateway(MockLLMClient([{"value": 1}]), settings, cache=first_cache).generate_structured([], Answer, stage="discovery")
    second = MockLLMClient([{"value": 2}])
    assert LLMGateway(second, settings, cache=second_cache).generate_structured([], Answer, stage="discovery").value == 2
    assert len(second.calls) == 1


def test_completed_analysis_checkpoint_reloads_without_model_and_force_replaces_it(tmp_path, monkeypatch):
    from adaptive_document_agent.ui import app
    from adaptive_document_agent.models import PipelineResult, ParsedDocument
    from tests.test_streamlit_auto_flow import _Streamlit
    result = PipelineResult(document=ParsedDocument(document_id="doc", sha256="hash", safe_filename="input.pdf", page_count=1), profile=DocumentProfile())
    cache = DiskCache(tmp_path)
    cache.set_model("analysis-result-key", result)
    st = _Streamlit()
    kwargs = dict(scope_key="key", analysis_focus="", settings=LLMSettings(provider=ProviderName.MOCK, model="test"), cache=cache)
    monkeypatch.setattr(app, "create_llm_client", lambda settings: (_ for _ in ()).throw(AssertionError("cache must not call a model")))
    assert app._analyse_upload(st, b"pdf", **kwargs) == result
    assert not st.statuses
    calls = []
    monkeypatch.setattr(app, "create_llm_client", lambda settings: MockLLMClient())
    def orchestrator(gateway, **unused):
        assert not gateway.cache_enabled
        def analyse(*args, **kwargs):
            calls.append(True)
            return result
        return SimpleNamespace(analyse_pdf=analyse)
    monkeypatch.setattr(app, "DocumentOrchestrator", orchestrator)
    assert app._analyse_upload(st, b"pdf", **kwargs, force=True) == result
    assert calls == [True]
