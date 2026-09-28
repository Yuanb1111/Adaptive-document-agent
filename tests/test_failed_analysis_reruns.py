"""A failed upload waits for explicit retry instead of charging on widget reruns."""

from collections import deque
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from adaptive_document_agent.models import DocumentProfile, ParsedDocument, PipelineResult
from adaptive_document_agent.services.llm import LLMSettings, MockLLMClient, PrivacyMode, ProviderName
from adaptive_document_agent.ui import app, llm_costs


RETRY = "Retry analysis (reuse successful cache)"


class MemoryCache:
    def __init__(self):
        self.values = {}

    def get_model(self, key, model):
        return self.values.get(key)

    def set_model(self, key, value):
        self.values[key] = value


@pytest.fixture
def flow(monkeypatch):
    st = Mock()
    st.session_state = {}
    st.expander.side_effect = lambda *args, **kwargs: nullcontext()
    st.tabs.side_effect = lambda labels: [nullcontext() for _ in labels]
    st.text_area.return_value = ""
    st.toggle.return_value = False
    st.file_uploader.return_value = SimpleNamespace(getvalue=lambda: b"first-pdf")
    st.checkbox.return_value = True
    pressed = set()
    st.button.side_effect = lambda label, **kwargs: label in pressed
    settings = LLMSettings(provider=ProviderName.MOCK, model="offline-test", privacy_mode=PrivacyMode.LOCAL_ONLY)
    cache = MemoryCache()
    result = PipelineResult(
        document=ParsedDocument(document_id="test", sha256="test", safe_filename="source.pdf", page_count=1),
        profile=DocumentProfile(),
    )
    outcomes = deque([ValueError("Synthetic ChunkDiscovery truncation"), result])
    attempts = []
    preview = SimpleNamespace(page_ranges=[], selected_page_count=1, page_count=1)

    class Orchestrator:
        def __init__(self, gateway, **kwargs):
            self.gateway = gateway

        def analyse_pdf(self, raw_pdf, *, scope, **kwargs):
            attempts.append({"raw_pdf": raw_pdf, "scope": scope, "gateway": self.gateway})
            self.gateway.usage.append({"stage": "discovery", "operation": "ChunkDiscovery",
                                       "output_tokens": len(attempts), "estimated_cost": .01})
            outcome = outcomes.popleft()
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def preview_scope(self, *args, **kwargs):
            return preview

    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.setattr(app, "render_sidebar", lambda *args, **kwargs: settings)
    monkeypatch.setattr(app, "is_public_deployment", lambda: False)
    monkeypatch.setattr(app, "cache_for_session", lambda *args, **kwargs: cache)
    monkeypatch.setattr(app, "create_llm_client", lambda settings: MockLLMClient())
    monkeypatch.setattr(app, "DocumentOrchestrator", Orchestrator)
    from adaptive_document_agent.services import export_readiness
    from adaptive_document_agent.ui import processing_progress
    from adaptive_document_agent.utils import timing
    monkeypatch.setattr(export_readiness, "check_export_readiness", lambda *args: {"ready": True, "backend": "offline"})
    monkeypatch.setattr(processing_progress, "ProcessingProgress", Mock())
    monkeypatch.setattr(timing, "configure_timing_logging", lambda: None)
    for module in (app.deliverables, app.overview, app.analysis, app.data, app.sources, app.quality, app.technical):
        monkeypatch.setattr(module, "render", Mock())
    return SimpleNamespace(st=st, settings=settings, cache=cache, result=result, outcomes=outcomes,
                           attempts=attempts, pressed=pressed, preview=preview)


def test_failed_upload_widget_reruns_preserve_error_and_costs_without_new_analysis(flow):
    app.run_app()
    first_failure = flow.st.session_state["analysis_failure"]
    assert len(flow.attempts) == 1
    assert any(call.args[0] == RETRY for call in flow.st.button.call_args_list)
    for _ in range(3):
        app.run_app()
    assert len(flow.attempts) == 1
    assert flow.st.session_state["analysis_failure"] == first_failure
    assert flow.st.session_state["failed_llm_usage"] == first_failure["usage"]
    assert len(first_failure["usage"]) == 1
    assert all(call.args[0] == first_failure["message"] for call in flow.st.error.call_args_list)
    assert flow.st.download_button.call_count == 4
    assert all(call.kwargs["on_click"] == "ignore" for call in flow.st.download_button.call_args_list)


def test_explicit_retry_uses_model_cache_then_successful_reruns_reuse_result(flow):
    app.run_app()
    failure_usage = list(flow.st.session_state["failed_llm_usage"])
    flow.pressed.add(RETRY)
    app.run_app()
    assert len(flow.attempts) == 2
    assert flow.attempts[-1]["gateway"].cache_enabled
    assert flow.attempts[-1]["gateway"].settings.privacy_mode == PrivacyMode.LOCAL_ONLY
    assert len(flow.attempts[-1]["gateway"].usage) == 1
    assert "analysis_failure" not in flow.st.session_state
    assert flow.st.session_state["failed_llm_usage"] == failure_usage
    flow.pressed.clear()
    app.run_app()
    assert len(flow.attempts) == 2
    assert flow.st.session_state["analysis_result_reused"] is True


@pytest.mark.parametrize("change", ["document", "focus", "model"])
def test_new_scope_automatically_runs_without_showing_old_failure(flow, change):
    app.run_app()
    flow.st.error.reset_mock()
    if change == "document":
        flow.st.file_uploader.return_value = SimpleNamespace(getvalue=lambda: b"second-pdf")
    elif change == "focus":
        flow.st.text_area.return_value = "A different supported question"
    else:
        flow.settings.model = "another-offline-model"
    app.run_app()
    assert len(flow.attempts) == 2
    flow.st.error.assert_not_called()
    assert app._analysis_failure(flow.st, flow.st.session_state["analysis_result_key"]) is None


def test_second_failed_attempt_replaces_ledger_without_accumulating_prior_costs(flow):
    flow.outcomes.clear()
    flow.outcomes.extend([ValueError("First synthetic failure"), ValueError("Second synthetic failure")])
    app.run_app()
    first = flow.st.session_state["failed_llm_usage"]
    flow.pressed.add(RETRY)
    app.run_app()
    current = flow.st.session_state["failed_llm_usage"]
    assert len(current) == 1 and current[0]["output_tokens"] == 2
    assert first[0]["output_tokens"] == 1
    assert flow.st.session_state["analysis_failure"]["usage"] == current
    assert "Second synthetic failure" in flow.st.session_state["analysis_failure"]["message"]


def test_reviewed_scope_retry_keeps_confirmed_ranges_and_success_cache(flow):
    flow.st.toggle.return_value = True
    app.run_app()
    assert not flow.attempts
    key = app._analysis_scope_key(b"first-pdf", "", flow.settings)
    flow.st.session_state.update(analysis_scope=flow.preview, analysis_scope_key=key)
    flow.pressed.add("Analyse selected pages")
    app.run_app()
    assert flow.attempts[0]["scope"] is flow.preview
    assert not flow.attempts[0]["gateway"].cache_enabled
    flow.pressed.clear()
    app.run_app()
    assert len(flow.attempts) == 1
    flow.pressed.add(RETRY)
    app.run_app()
    assert flow.attempts[1]["scope"] is flow.preview
    assert flow.attempts[1]["gateway"].cache_enabled


def test_ignore_model_cache_reanalysis_remains_explicit_and_bypasses_cache(flow):
    flow.outcomes.popleft()
    app.run_app()
    flow.outcomes.append(flow.result)
    flow.pressed.add("Reanalyse PDF (ignore model cache)")
    app.run_app()
    assert len(flow.attempts) == 2
    assert not flow.attempts[-1]["gateway"].cache_enabled


def test_explicit_retry_does_not_silently_return_an_older_success(flow):
    app.run_app()
    key = flow.st.session_state["analysis_failure"]["scope_key"]
    older_result = flow.result.model_copy(update={"pipeline_version": "old-success"})
    flow.st.session_state.update(analysis_result=older_result, analysis_result_key=key)
    flow.cache.set_model(f"analysis-result-{key}", older_result)
    app.run_app()
    assert len(flow.attempts) == 1
    flow.pressed.add(RETRY)
    app.run_app()
    assert len(flow.attempts) == 2
    assert flow.st.session_state["analysis_result"] is flow.result


def test_cost_csv_download_does_not_rerun_the_app():
    st = Mock()
    st.expander.return_value = nullcontext()
    llm_costs.render(st, [{"stage": "discovery", "output_tokens": 8192}])
    assert st.download_button.call_args.kwargs["on_click"] == "ignore"
