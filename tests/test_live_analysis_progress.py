"""Real worker transitions: polling never creates another paid attempt."""

from threading import Event, get_ident

import pytest

from adaptive_document_agent.ui import app
from adaptive_document_agent.ui.analysis_job import start_worker
from tests.test_interrupted_analysis_reruns import flow, run, ScriptInterrupted


@pytest.fixture
def workers(monkeypatch):
    active = []
    def start(target):
        worker = start_worker(target)
        active.append(worker)
        return worker
    monkeypatch.setattr(app, '_start_analysis_worker', start)
    yield active
    for worker in active:
        worker.join(5)
        assert not worker.is_alive()


@pytest.mark.parametrize('outcome', ['complete', 'failed', 'partial'])
def test_live_polling_observes_stage_and_terminal_state_without_restarting(flow, workers, outcome):
    entered, advance, second, finish = (Event() for _ in range(4))
    ui_thread = get_ident()
    def analyse(*args, progress, **kwargs):
        assert get_ident() != ui_thread
        progress('Understanding document')
        entered.set()
        assert advance.wait(5)
        progress('Selecting presentation questions before chart generation')
        second.set()
        assert finish.wait(5)
        flow.gateway.usage.append({'output_tokens': 7})
        if outcome == 'failed':
            raise ValueError('Synthetic model timeout')
        if outcome == 'partial':
            flow.result.pipeline_state = 'partial'
        return flow.result
    flow.orchestrator.analyse_pdf.side_effect = analyse
    try:
        assert run(flow) is None  # Returns immediately while the model is busy.
        assert entered.wait(5)
        assert len(workers) == 1
        attempt = flow.st.session_state['analysis_attempts']['same-scope']
        app._poll_active_attempt(flow.st, attempt, flow.progress)
        assert flow.progress.restore.call_args.args[0]['label'] == 'Understanding document'
        advance.set()
        assert second.wait(5)
        app._poll_active_attempt(flow.st, attempt, flow.progress)
        snapshot = flow.progress.restore.call_args.args[0]
        assert snapshot['label'] == 'Selecting presentation questions before chart generation'
        assert snapshot['percent'] == 80
        for options in ({}, {'retry': True}, {'force': True}):
            assert run(flow, **options) is None
        assert len(workers) == flow.orchestrator.analyse_pdf.call_count == 1
        flow.st.rerun.assert_not_called()
    finally:
        advance.set()
        finish.set()
        for worker in workers:
            worker.join(5)
    app._poll_active_attempt(flow.st, attempt, flow.progress)
    flow.st.rerun.assert_called_once_with()
    assert run(flow) is (None if outcome == 'failed' else flow.result)
    assert attempt['state'] == outcome
    assert run(flow) is (None if outcome == 'failed' else flow.result)
    assert len(workers) == 1
    if outcome == 'complete':
        assert flow.cache_values['analysis-result-same-scope'] is flow.result
    else:
        assert 'analysis-result-same-scope' not in flow.cache_values
        assert flow.st.session_state['failed_llm_usage'] == [{'output_tokens': 7}]
        assert flow.progress.restore.call_args.args[0]['stopped_at'] is not None


def test_widget_script_interruption_does_not_interrupt_the_worker(flow, workers):
    entered, finish = Event(), Event()
    def analyse(*args, progress, **kwargs):
        progress('Understanding document')
        entered.set()
        assert finish.wait(5)
        return flow.result
    flow.orchestrator.analyse_pdf.side_effect = analyse
    flow.progress.restore.side_effect = ScriptInterrupted()
    try:
        with pytest.raises(ScriptInterrupted):
            run(flow)
        assert entered.wait(5)
        attempt = flow.st.session_state['analysis_attempts']['same-scope']
        assert attempt['state'] == 'running'
    finally:
        finish.set()
        for worker in workers:
            worker.join(5)
    flow.progress.restore.side_effect = None
    assert run(flow) is flow.result
    assert len(workers) == flow.orchestrator.analyse_pdf.call_count == 1


def test_worker_settings_cannot_change_when_sidebar_is_edited(flow, workers):
    entered, finish = Event(), Event()
    def analyse(*args, **kwargs):
        entered.set()
        assert finish.wait(5)
        return flow.result
    flow.orchestrator.analyse_pdf.side_effect = analyse
    try:
        assert run(flow) is None
        assert entered.wait(5)
        flow.kwargs['settings'].model = 'edited-model'
        assert flow.gateways.call_args.args[1].model == 'test'
    finally:
        finish.set()


@pytest.mark.parametrize('failed', [False, True])
def test_streamlit_fragment_updates_in_place_then_automatically_shows_terminal_state(monkeypatch, failed):
    """Exercise actual Streamlit fragments/components, including full-app rerun."""
    from dataclasses import replace
    from types import SimpleNamespace
    from streamlit.testing.v1 import AppTest
    from streamlit.runtime.scriptrunner_utils.script_requests import ScriptRequests
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import ThreadState
    except ImportError:
        ThreadState = None
    from tests.test_fourier_ui import sample_result

    entered, finish = Event(), Event()
    calls, active, fragment_ids = [], [], []
    def analyse(*args, progress, **kwargs):
        calls.append(1)
        progress('Selecting presentation questions before chart generation')
        entered.set()
        assert finish.wait(10)
        if failed:
            raise ValueError('Synthetic timeout')
        return sample_result()
    monkeypatch.setattr(app, 'DocumentOrchestrator', lambda *a, **k: SimpleNamespace(analyse_pdf=analyse))
    monkeypatch.setattr(app, 'create_llm_client', lambda settings: None)
    monkeypatch.setattr(app, 'LLMGateway', lambda *a, **k: SimpleNamespace(usage=[]))
    def start(target):
        worker = start_worker(target)
        active.append(worker)
        return worker
    monkeypatch.setattr(app, '_start_analysis_worker', start)
    poll = app._poll_active_attempt
    def track(*args):
        fragment_ids.append(ThreadState.get().fragment_id if ThreadState is not None
                            else get_script_run_ctx().current_fragment_id)
        poll(*args)
    monkeypatch.setattr(app, '_poll_active_attempt', track)
    page = AppTest.from_string('''import streamlit as st
from adaptive_document_agent.ui import app
from adaptive_document_agent.ui.processing_progress import ProcessingProgress
from adaptive_document_agent.services.llm import LLMSettings, ProviderName, PrivacyMode
st.session_state.shell_runs = st.session_state.get('shell_runs', 0) + 1
progress = ProcessingProgress(st.empty(), timer=st.empty())
result = app._analyse_upload(st, b'fake', scope_key='live-widget-test', analysis_focus='',
    settings=LLMSettings(provider=ProviderName.MOCK, model='offline', privacy_mode=PrivacyMode.LOCAL_ONLY),
    cache=None, progress=progress)
if result is not None:
    st.success('Analysis result ready')
''', default_timeout=15)
    original_request = ScriptRequests.request_rerun
    test_thread = get_ident()
    def tick():
        def fragment_request(runner, data):
            if get_ident() == test_thread:
                data = replace(data, fragment_id_queue=[fragment_ids[0]])
            return original_request(runner, data)
        with monkeypatch.context() as patch:
            patch.setattr(ScriptRequests, 'request_rerun', fragment_request)
            page.run()
        assert not page.exception, page.exception
    try:
        page.run()
        assert not page.exception, page.exception
        assert entered.wait(5)
        assert fragment_ids[0]
        tick()
        assert page.session_state['shell_runs'] == 1
        assert any('Selecting presentation questions' in item.value for item in page.markdown)
    finally:
        finish.set()
        for worker in active:
            worker.join(5)
    tick()
    assert page.session_state['shell_runs'] == 2
    assert calls == [1]
    if failed:
        assert any('Synthetic timeout' in item.value for item in page.error)
        assert not page.success
    else:
        assert any('Analysis result ready' in item.value for item in page.success)
