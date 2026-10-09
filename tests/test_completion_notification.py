from types import SimpleNamespace

import pytest

from adaptive_document_agent.ui import completion_notification as notification


def exported(*, payload=b"ppt", status="passed"):
    return SimpleNamespace(payload=payload, report=SimpleNamespace(status=status))


def test_completion_uses_opaque_stable_export_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(notification, "_component", lambda: lambda **kw: calls.append(kw))
    ui = SimpleNamespace(session_state={"ppt_build_cache": {("version", "template", "content"): b"ppt"}})
    notification.notify_export_ready(ui, exported())
    notification.notify_export_ready(ui, exported(payload=b"new ZIP timestamp"))
    assert calls[0]["data"] == calls[1]["data"]
    assert len(calls[0]["data"]["event_id"]) == 64
    assert set(calls[0]["data"]) == {"mode", "event_id", "run_id", "outcome"}
    ui.session_state["ppt_build_cache"] = {("version", "template", "other content"): b"ppt"}
    notification.notify_export_ready(ui, exported())
    assert calls[2]["data"] != calls[0]["data"]


def test_new_attempt_with_same_content_has_new_run_but_reruns_keep_it(monkeypatch):
    calls = []
    monkeypatch.setattr(notification, "_component", lambda: lambda **kw: calls.append(kw))
    ui = SimpleNamespace(session_state={
        "ppt_build_cache": {("version", "template", "content"): b"ppt"},
        "analysis_result_key": "scope",
        "analysis_attempts": {"scope": {"id": "first", "state": "complete"}},
    })
    notification.notify_export_ready(ui, exported())
    notification.notify_export_ready(ui, exported())
    assert calls[0]["data"] == calls[1]["data"]
    ui.session_state["analysis_attempts"]["scope"] = {"id": "second", "state": "complete"}
    notification.notify_export_ready(ui, exported())
    assert calls[2]["data"]["event_id"] == calls[0]["data"]["event_id"]
    assert calls[2]["data"]["run_id"] == "second"
    ui.session_state.pop("analysis_attempts")  # Restored from disk cache after refresh.
    notification.notify_export_ready(ui, exported())
    assert calls[3]["data"]["run_id"] is None
    assert calls[3]["data"]["event_id"] == calls[2]["data"]["event_id"]


@pytest.mark.parametrize("analysis_run", [None, "analysis-first"])
def test_explicit_export_cycles_notify_again_without_repeating_on_refresh(monkeypatch, analysis_run):
    calls = []
    monkeypatch.setattr(notification, "_component", lambda: lambda **kw: calls.append(kw["data"]))
    ui = SimpleNamespace(session_state={
        "analysis_result_key": "scope",
        "analysis_attempts": {"scope": {"id": analysis_run, "state": "complete"}} if analysis_run else {},
        "ppt_build_cache": {("version", "template", "same-content"): b"ppt"},
    })
    notification.notify_export_ready(ui, exported())
    notification.begin_export_run(ui, "scope")
    notification.notify_export_ready(ui, exported())
    notification.notify_export_ready(ui, exported())  # Widget/cache rerun.
    assert calls[1] == calls[2]
    assert calls[1]["run_id"] != calls[0]["run_id"]
    assert calls[1]["event_id"] == calls[0]["event_id"]
    notification.begin_export_run(ui, "scope")
    notification.notify_export_ready(ui, exported(status="failed"))
    assert len(calls) == 3  # Failed export never emits its new cycle.
    notification.notify_export_ready(ui, exported())
    assert calls[3]["run_id"] not in {calls[0]["run_id"], calls[1]["run_id"]}
    ui.session_state["analysis_attempts"]["scope"] = {"id": "analysis-next", "state": "complete"}
    notification.notify_export_ready(ui, exported())
    assert calls[4]["run_id"] == "analysis-next"  # Do not inherit the old export cycle.
    ui.session_state.pop("analysis_attempts")
    ui.session_state.pop("ppt_notification_export_runs")
    notification.notify_export_ready(ui, exported())
    assert calls[5]["run_id"] is None  # Browser restores its latest run for this content.


@pytest.mark.parametrize("payload,status", [(b"", "passed"), (b"ppt", "failed"), (b"ppt", "unavailable")])
def test_unavailable_or_failed_export_cannot_emit(monkeypatch, payload, status):
    calls = []
    monkeypatch.setattr(notification, "_component", lambda: lambda **kw: calls.append(kw))
    notification.notify_export_ready(SimpleNamespace(session_state={}), exported(payload=payload, status=status))
    assert not calls


def test_old_streamlit_degrades_to_on_page_progress(monkeypatch):
    def unavailable():
        raise ImportError("No v2 components")
    monkeypatch.setattr(notification, "_component", unavailable)
    captions = []
    ui = SimpleNamespace(session_state={}, caption=captions.append)
    notification.render_settings(ui)
    notification.notify_export_ready(ui, exported())
    assert "Progress remains available" in captions[0]


@pytest.mark.parametrize('outcome', sorted(notification.OUTCOMES - {'ready'}))
def test_terminal_outcomes_are_private_stable_and_distinct_from_success(monkeypatch, outcome):
    calls = []
    monkeypatch.setattr(notification, '_component', lambda: lambda **kw: calls.append(kw['data']))
    ui = SimpleNamespace(session_state={'analysis_result_key': 'private document name',
        'analysis_attempts': {'private document name': {'id': 'attempt', 'state': 'failed'}}})
    notification.notify_outcome(ui, outcome)
    notification.notify_outcome(ui, outcome)
    assert calls[0] == calls[1]
    assert calls[0]['outcome'] == outcome
    assert 'private document' not in str(calls)
    success = notification.queue_outcome(ui, 'ready')
    assert success['event_id'] != calls[0]['event_id']


def test_interruption_is_replayed_after_script_restart(monkeypatch):
    calls = []
    monkeypatch.setattr(notification, '_component', lambda: lambda **kw: calls.append(kw['data']))
    ui = SimpleNamespace(session_state={'analysis_attempts': {
        'scope': {'id': 'interrupted-attempt', 'state': 'interrupted'}}})
    notification.render_settings(ui)
    notification.render_settings(ui)
    assert len(ui.session_state['presentation_notification_outcomes']) == 1
    assert calls[0]['events'][0]['outcome'] == 'analysis_interrupted'
    assert calls[0]['events'][0]['run_id'] == 'interrupted-attempt'


def test_notification_component_failure_cannot_break_delivery(monkeypatch):
    def failed(): raise RuntimeError('browser component unavailable')
    monkeypatch.setattr(notification, '_component', failed)
    ui = SimpleNamespace(session_state={})
    notification.notify_export_ready(ui, exported(), needs_review=True)
    notification.notify_outcome(ui, 'export_failed')
    assert [e['outcome'] for e in ui.session_state['presentation_notification_outcomes']] == [
        'ready_with_warnings', 'export_failed']
