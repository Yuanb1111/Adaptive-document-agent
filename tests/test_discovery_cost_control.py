"""Generic discovery compression must retain inventories, evidence and privacy."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

from adaptive_document_agent.agent.document_discovery import ChunkDiscovery, DiscoveryOverview, DocumentDiscovery
from adaptive_document_agent.agent.semantic_resolver import SemanticResolution, SemanticResolver
from adaptive_document_agent.models import DocumentPage, ParsedDocument
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.services.llm.usage_export import export_usage_csv
from adaptive_document_agent.utils.caching import DiskCache
from tests.test_llm_costs import Answer, raw_response
from tests.test_performance import chunks


def test_overview_excludes_repeated_inventory_but_profile_preserves_all_terms_and_pages():
    metrics = [f"Water category {i}" for i in range(400)] + ["Gross sales", "Net sales"]
    chunk = ChunkDiscovery(summary="Water survey [page 1]", metrics=metrics,
        units=["litres", "%"], time_periods=["H1 2025", "FY2025"], currencies=["USD", "EUR"],
        entities=["Site A", "Site B"], dimensions=["Region"], data_quality_notes=["Conflicting totals on page 1"])
    client = MockLLMClient([chunk.model_dump(), {"document_summary": "Water survey", "document_summary_pages": [1, 999]}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))
    document = ParsedDocument(document_id="sample", sha256="sample", safe_filename="sample.pdf", page_count=1,
                              pages=[DocumentPage(page_number=1, text="Raw (1,250) litres and 12.5%")])
    before = document.model_dump()
    profile = DocumentDiscovery(gateway).discover(document)
    assert profile.metrics == metrics
    assert profile.detected_units == chunk.units and profile.detected_time_periods == chunk.time_periods
    assert profile.detected_currencies == chunk.currencies and profile.entities == chunk.entities
    assert profile.dimensions == chunk.dimensions and profile.data_quality_notes == chunk.data_quality_notes
    assert profile.document_summary_pages == [1] and document.model_dump() == before
    assert "metrics" not in DiscoveryOverview.model_json_schema()["properties"]
    assert all(name in client.calls[-1][-1]["content"] for name in metrics)


def test_thinking_policy_change_invalidates_both_chunk_and_gateway_caches(tmp_path):
    settings = LLMSettings(provider=ProviderName.MOCK)
    client = MockLLMClient([{"summary": "first"}, {"summary": "second"}])
    cache = DiskCache(tmp_path)
    gateway = LLMGateway(client, settings, cache=cache)
    discovery = DocumentDiscovery(gateway, cache=cache)
    chunk = chunks(1)[0]
    assert discovery._discover_chunk(chunk).summary == "first"
    assert discovery._discover_chunk(chunk).summary == "first"
    assert gateway.usage[-1]["cache_hit"] and gateway.usage[-1]["estimated_cost"] == 0
    settings.discovery_thinking = "enabled"
    assert discovery._discover_chunk(chunk).summary == "second"
    assert len(client.calls) == 2


def test_parallel_stage_policy_never_leaks_into_analysis_calls(monkeypatch):
    settings = LLMSettings()
    provider = LiteLLMProvider(settings)
    barrier = Barrier(2)
    received = {}
    def complete(messages, **kwargs):
        barrier.wait(timeout=5)
        received[messages[-1]["content"]] = kwargs
        return raw_response()
    monkeypatch.setattr(provider, "_completion", complete)
    gateway = LLMGateway(provider, settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda stage: gateway.generate_structured(
            [{"role": "user", "content": stage}], Answer, stage=stage), ["discovery", "planner"]))
    assert len(results) == 2
    assert received["discovery"]["extra_body"]["thinking"]["type"] == "disabled"
    assert "extra_body" not in received["planner"]


def test_larger_batches_reduce_repeated_context_and_keep_complete_vocabulary():
    names = [f"Metric {i}" for i in range(480)]
    captured = []
    def generate(messages, *args, **kwargs):
        captured.append(messages[-1]["content"])
        return SemanticResolution()
    gateway = SimpleNamespace(discovery_workers=4, generate_structured=generate)
    mappings = SemanticResolver(gateway).resolve_metrics(names, context="shared evidence " * 500)
    assert len(captured) == 5  # Previously 10 batches of 48.
    assert [mapping.original_name for mapping in mappings] == names
    prefixes = {text.split("\nMetric names:\n")[0] for text in captured}
    assert len(prefixes) == 1 and all(name in next(iter(prefixes)) for name in names)
    assert all(mapping.canonical_name is None and mapping.confidence == 0 for mapping in mappings)


def test_cost_export_keeps_unknown_cells_and_json_evidence():
    import csv
    import io
    from adaptive_document_agent.models import PipelineResult, ReportPlan, DocumentProfile
    from adaptive_document_agent.services.export import export_json
    record = {"stage": "discovery", "input_tokens": 20, "output_tokens": 4, "model": "=unsafe"}
    rows = list(csv.DictReader(io.StringIO(export_usage_csv([record]).decode("utf-8-sig"))))
    assert rows[0]["estimated_cost_min"] == "" and rows[0]["reasoning_tokens"] == ""
    assert rows[0]["model"] == "'=unsafe"
    result = PipelineResult(document=ParsedDocument(document_id="x", sha256="x", safe_filename="x.pdf", page_count=0),
                            profile=DocumentProfile(), report_plan=ReportPlan(title="x"), llm_usage=[record])
    exported = json.loads(export_json(result))
    assert exported["llm_usage"] == [record]
    assert exported["llm_cost_summary"]["by_stage"][0]["estimated_total_min"] is None


def test_cost_ui_exposes_partial_coverage_and_csv():
    from unittest.mock import Mock
    from contextlib import nullcontext
    from adaptive_document_agent.ui.llm_costs import render
    st = Mock()
    st.expander.return_value = nullcontext()
    render(st, [{"stage": "discovery", "input_tokens": 20, "output_tokens": 4}])
    assert "incomplete" in st.caption.call_args_list[0].args[0]
    assert st.dataframe.call_count == 2
    assert st.download_button.call_args.args[2] == "llm_cost_details.csv"


def test_scope_preview_costs_enter_confirmed_analysis_once(monkeypatch):
    from adaptive_document_agent.ui import app
    from tests.test_streamlit_auto_flow import _Streamlit
    st = _Streamlit()
    preview_record = {"stage": "discovery", "operation": "DocumentRoute", "input_tokens": 100}
    st.session_state["analysis_scope_usage_pending"] = {"key": "one", "records": [preview_record]}
    ledgers = []
    class Orchestrator:
        def __init__(self, gateway, **kwargs):
            self.gateway = gateway
        def analyse_pdf(self, *args, **kwargs):
            ledgers.append(list(self.gateway.usage))
            return object()
    monkeypatch.setattr(app, "DocumentOrchestrator", Orchestrator)
    monkeypatch.setattr(app, "create_llm_client", lambda settings: MockLLMClient())
    settings = LLMSettings(provider=ProviderName.MOCK)
    for _ in range(2):
        assert app._analyse_upload(st, b"fake", scope_key="one", analysis_focus="", settings=settings,
                                   cache=None, scope=object(), force=True) is not None
    assert ledgers == [[preview_record], []]


def test_failed_analysis_preserves_paid_calls_for_download(monkeypatch):
    from adaptive_document_agent.ui import app, llm_costs
    from tests.test_streamlit_auto_flow import _Streamlit
    st = _Streamlit()
    records = [{"stage": "discovery", "output_tokens": 200}]
    class Orchestrator:
        def __init__(self, gateway, **kwargs):
            self.gateway = gateway
        def analyse_pdf(self, *args, **kwargs):
            self.gateway.usage.extend(records)
            raise ValueError("failed after discovery")
    captured = []
    monkeypatch.setattr(app, "DocumentOrchestrator", Orchestrator)
    monkeypatch.setattr(app, "create_llm_client", lambda settings: MockLLMClient())
    monkeypatch.setattr(llm_costs, "render", lambda st, rows: captured.extend(rows))
    result = app._analyse_upload(st, b"fake", scope_key="one", analysis_focus="",
                                 settings=LLMSettings(provider=ProviderName.MOCK), cache=None)
    assert result is None and st.session_state["failed_llm_usage"] == records and captured == records
