"""Interrupted or overlapping Streamlit runs must not repeat paid analysis."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from adaptive_document_agent.ui import app


class ScriptInterrupted(BaseException):
    """Match Streamlit's BaseException-based stop/rerun control flow."""


@pytest.fixture
def flow(monkeypatch):
    st = Mock()
    st.session_state = {}
    gateway = SimpleNamespace(usage=[])
    cache_values = {}
    cache = SimpleNamespace(
        get_model=lambda key, model: cache_values.get(key),
        set_model=lambda key, value: cache_values.__setitem__(key, value),
    )
    orchestrator = Mock()
    result = object()
    orchestrator.analyse_pdf.return_value = result
    monkeypatch.setattr(app, "DocumentOrchestrator", Mock(return_value=orchestrator))
    monkeypatch.setattr(app, "create_llm_client", Mock(return_value="client"))
    gateways = Mock(return_value=gateway)
    monkeypatch.setattr(app, "LLMGateway", gateways)
    progress = Mock()
    kwargs = dict(scope_key="same-scope", analysis_focus="", settings=SimpleNamespace(model="test"),
                  cache=cache, progress=progress)
    # Cost rendering is covered separately; do not require UI layout here.
    from adaptive_document_agent.ui import llm_costs
    monkeypatch.setattr(llm_costs, "render", Mock())
    return SimpleNamespace(st=st, gateway=gateway, gateways=gateways, cache_values=cache_values,
                           orchestrator=orchestrator, result=result, progress=progress, kwargs=kwargs)


def run(flow, **overrides):
    return app._analyse_upload(flow.st, b"%PDF", **(flow.kwargs | overrides))


@pytest.mark.parametrize("point", ["progress", "status", "stage", "pipeline"])
def test_interruption_propagates_and_waits_for_explicit_retry(flow, point):
    interrupted = ScriptInterrupted()
    usage = {"stage": "discovery", "output_tokens": 7}

    def cancel(*args, **kwargs):
        assert flow.st.session_state["analysis_attempts"]["same-scope"]["state"] == "running"
        raise interrupted

    if point == "progress":
        flow.progress.reset.side_effect = cancel
    elif point == "status":
        flow.st.status.side_effect = cancel
    else:
        def analyse(*args, progress, **kwargs):
            flow.gateway.usage.append(usage)
            if point == "stage":
                progress("Planning presentation narrative")
            raise interrupted
        flow.orchestrator.analyse_pdf.side_effect = analyse
        if point == "stage":
            flow.st.status.return_value.write.side_effect = cancel

    with pytest.raises(ScriptInterrupted) as caught:
        run(flow)
    assert caught.value is interrupted
    attempt = flow.st.session_state["analysis_attempts"]["same-scope"]
    assert attempt["state"] == "interrupted"
    assert attempt["failure"]["usage"] == ([usage] if point in {"stage", "pipeline"} else [])
    if point == "stage":
        assert attempt["stage"] == "Planning presentation narrative"
    starts = flow.orchestrator.analyse_pdf.call_count
    assert run(flow) is None
    assert flow.orchestrator.analyse_pdf.call_count == starts
    assert "interrupted" in flow.st.error.call_args.args[0]

    flow.progress.reset.side_effect = None
    flow.st.status.side_effect = None
    flow.st.status.return_value.write.side_effect = None
    flow.orchestrator.analyse_pdf.side_effect = None
    assert run(flow, retry=True) is flow.result
    assert flow.gateways.call_args.kwargs["cache_enabled"] is True
    assert run(flow) is flow.result
    assert flow.orchestrator.analyse_pdf.call_count == starts + 1


@pytest.mark.parametrize("override", [{}, {"force": True}, {"retry": True}])
def test_running_attempt_blocks_overlapping_analysis_even_explicit_retry(flow, override):
    entered, release = Event(), Event()

    def analyse(*args, progress, **kwargs):
        progress("Planning presentation narrative")
        entered.set()
        assert release.wait(5)
        return flow.result

    flow.orchestrator.analyse_pdf.side_effect = analyse
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(run, flow)
        try:
            assert entered.wait(5)
            assert run(flow, **override) is None
            assert flow.orchestrator.analyse_pdf.call_count == 1
            assert flow.progress.reset.call_count == 1
            assert flow.progress.update.call_args.args[0] == "Planning presentation narrative"
            flow.st.info.assert_called_once()
        finally:
            release.set()
        assert first.result(5) is flow.result


def test_failure_is_saved_before_status_update_can_interrupt(flow):
    flow.orchestrator.analyse_pdf.side_effect = ValueError("bad evidence")
    flow.gateway.usage.append({"stage": "planning", "output_tokens": 8})
    flow.st.status.return_value.update.side_effect = ScriptInterrupted()
    with pytest.raises(ScriptInterrupted):
        run(flow)
    failure = app._analysis_failure(flow.st, "same-scope")
    assert "bad evidence" in failure["message"]
    assert failure["usage"] == flow.gateway.usage
    assert flow.st.session_state['presentation_notification_outcomes'][0]['outcome'] == 'analysis_failed'
    assert flow.st.session_state["failed_llm_usage"] == flow.gateway.usage
    flow.st.status.return_value.update.side_effect = None
    assert run(flow) is None
    assert flow.orchestrator.analyse_pdf.call_count == 1


def test_interruption_after_success_keeps_completed_result(flow):
    flow.st.status.return_value.update.side_effect = ScriptInterrupted()
    with pytest.raises(ScriptInterrupted):
        run(flow)
    assert app._analysis_failure(flow.st, "same-scope") is None
    assert flow.cache_values["analysis-result-same-scope"] is flow.result
    assert run(flow) is flow.result
    assert flow.orchestrator.analyse_pdf.call_count == 1


def test_interrupted_scope_does_not_block_another_document(flow):
    flow.orchestrator.analyse_pdf.side_effect = ScriptInterrupted()
    with pytest.raises(ScriptInterrupted):
        run(flow)
    flow.orchestrator.analyse_pdf.side_effect = None
    assert run(flow, scope_key="different-scope") is flow.result
    assert app._analysis_failure(flow.st, "same-scope")["message"].startswith("Analysis was interrupted")
    assert app._analysis_failure(flow.st, "different-scope") is None


@pytest.mark.parametrize("outcome", ["complete", "interrupted"])
def test_attempt_finishing_during_cache_lookup_does_not_start_again(flow, outcome):
    def lookup(*args):
        if outcome == "complete":
            flow.st.session_state.update(analysis_result_key="same-scope", analysis_result=flow.result)
        else:
            flow.st.session_state["analysis_attempts"]["same-scope"] = {
                "state": "interrupted", "failure": {
                    "scope_key": "same-scope", "scope": None,
                    "message": "Analysis was interrupted", "usage": [],
                },
            }
        return None

    flow.kwargs["cache"].get_model = lookup
    assert run(flow) is (flow.result if outcome == "complete" else None)
    flow.orchestrator.analyse_pdf.assert_not_called()


def test_completion_identity_changes_only_for_actual_new_analysis_attempts(flow, monkeypatch):
    from adaptive_document_agent.ui import completion_notification

    events = []
    monkeypatch.setattr(completion_notification, "_component", lambda: lambda **kw:
        events.append(kw["data"]) if kw["data"].get('outcome') == 'ready' else None)
    verified = SimpleNamespace(payload=b"identical-presentation", report=SimpleNamespace(status="passed"))
    assert run(flow) is flow.result
    completion_notification.notify_export_ready(flow.st, verified)
    assert run(flow) is flow.result  # Widget rerun reuses the result and attempt.
    completion_notification.notify_export_ready(flow.st, verified)
    assert events[1] == events[0]
    assert run(flow, force=True) is flow.result
    completion_notification.notify_export_ready(flow.st, verified)
    assert events[2]["event_id"] == events[0]["event_id"]
    assert events[2]["run_id"] != events[0]["run_id"]
    flow.orchestrator.analyse_pdf.side_effect = ValueError("failed new attempt")
    assert run(flow, force=True) is None
    flow.orchestrator.analyse_pdf.side_effect = None
    assert run(flow, retry=True) is flow.result
    completion_notification.notify_export_ready(flow.st, verified)
    assert events[3]["run_id"] not in {events[0]["run_id"], events[2]["run_id"]}
    # A new server session may restore only the disk-cached result. The browser
    # recovers the last run for this event_id, without a made-up new attempt.
    flow.st.session_state.clear()
    starts = flow.orchestrator.analyse_pdf.call_count
    assert run(flow) is flow.result
    completion_notification.notify_export_ready(flow.st, verified)
    assert events[4]["run_id"] is None
    assert events[4]["event_id"] == events[3]["event_id"]
    assert flow.orchestrator.analyse_pdf.call_count == starts
