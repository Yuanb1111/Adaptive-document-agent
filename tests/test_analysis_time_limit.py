"""Fake-clock spending limits; all clients are mocks and no models are called."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, SecretStr

from adaptive_document_agent.services.analysis_deadline import (
    AnalysisDeadline, AnalysisTimeLimitExceeded, request_deadline, request_timeout)
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName


class Answer(BaseModel):
    value: int


@pytest.fixture
def budget():
    clock = SimpleNamespace(now=0.0)
    return clock, AnalysisDeadline(clock=lambda: clock.now)


def gateway(client=None):
    return LLMGateway(client or MockLLMClient(['ok']), LLMSettings(provider=ProviderName.MOCK, model='mock'))


def test_timeout_uses_remaining_budget_and_context_is_isolated(budget):
    clock, deadline = budget
    clock.now = 890
    with request_deadline(deadline):
        assert request_timeout(300) == 10
        assert request_timeout(3) == 3
        with request_deadline(None):
            assert request_timeout(300) == 300
        clock.now = 900
        with pytest.raises(AnalysisTimeLimitExceeded):
            request_timeout(300)
    assert request_timeout(300) == 300


@pytest.mark.parametrize('structured', [False, True])
def test_expired_request_never_reaches_provider_or_charges_fake_usage(budget, structured):
    clock, deadline = budget
    gate = gateway()
    gate.run_deadline = deadline
    clock.now = 900
    with pytest.raises(AnalysisTimeLimitExceeded):
        if structured:
            gate.generate_structured([], Answer, stage='presentation')
        else:
            gate.generate_text([], stage='presentation')
    assert gate.client.calls == gate.usage == []


def test_format_repair_cannot_restart_budget_and_original_usage_is_retained(budget):
    clock, deadline = budget
    client = MockLLMClient(['not json', {'value': 9}])
    original = client.generate_text
    def late_response(*args, **kwargs):
        response = original(*args, **kwargs)
        clock.now = 901
        return response
    client.generate_text = late_response
    gate = gateway(client)
    gate.run_deadline = deadline
    with pytest.raises(AnalysisTimeLimitExceeded):
        gate.generate_structured([], Answer, stage='presentation')
    assert len(client.calls) == len(gate.usage) == 1
    assert gate.usage[0]['status'] == 'invalid_format'


def test_queued_worker_shares_deadline_and_does_not_take_a_slot(budget):
    clock, deadline = budget
    gate = gateway()
    gate.run_deadline = deadline
    gate._request_slots.acquire()
    try:
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(gate.generate_text, [], stage='presentation')
            clock.now = 901
            with pytest.raises(AnalysisTimeLimitExceeded):
                pending.result(3)
    finally:
        gate._request_slots.release()
    assert not gate.client.calls
    gate.run_deadline = AnalysisDeadline()
    assert gate.generate_text([], stage='presentation') == 'ok'


@pytest.mark.parametrize('error_kind', ['network', 'compatibility'])
def test_provider_retry_stops_and_keeps_attempt_diagnostics(budget, monkeypatch, error_kind):
    import litellm
    from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
    clock, deadline = budget
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-chat', api_key=SecretStr('test-key'))
    calls = []
    def completion(**kwargs):
        calls.append(kwargs)
        clock.now = 900
        if error_kind == 'compatibility':
            error = type('UnsupportedParamsError', (Exception,), {})
            raise error("doesn't support temperature")
        raise TimeoutError('synthetic timeout')
    monkeypatch.setattr(litellm, 'completion', completion)
    monkeypatch.setattr('adaptive_document_agent.services.llm.litellm_provider.time.sleep', lambda _: None)
    gate = LLMGateway(LiteLLMProvider(settings), settings)
    gate.run_deadline = deadline
    clock.now = 895
    with pytest.raises(AnalysisTimeLimitExceeded):
        gate.generate_text([], stage='presentation')
    assert len(calls) == 1
    assert calls[0]['timeout'] == 5
    assert calls[0]['num_retries'] == 0
    assert len(gate.usage) == 1
    assert gate.usage[0]['output_tokens'] is None  # Unknown billing is never reported as zero.
    assert len(gate.usage[0]['attempts']) == 1


def test_late_success_is_metered_but_next_call_is_blocked(budget):
    clock, deadline = budget
    client = MockLLMClient(['finished', 'must not run'])
    original = client.generate_text
    def response(*args, **kwargs):
        value = original(*args, **kwargs)
        clock.now = 901
        return value
    client.generate_text = response
    gate = gateway(client)
    gate.run_deadline = deadline
    assert gate.generate_text([], stage='presentation') == 'finished'
    with pytest.raises(AnalysisTimeLimitExceeded):
        gate.generate_text([], stage='presentation')
    assert len(gate.usage) == len(client.calls) == 1


@pytest.mark.parametrize('reporting_ready', [False, True])
def test_orchestrator_returns_partial_evidence_with_usage_on_deadline(budget, monkeypatch, reporting_ready):
    from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
    from adaptive_document_agent.models import PipelineResult, ParsedDocument, DocumentProfile
    clock, deadline = budget
    gate = gateway()
    gate.run_deadline = deadline
    result = PipelineResult(document=ParsedDocument(document_id='test', sha256='hash',
        safe_filename='test.pdf', page_count=1), profile=DocumentProfile())
    def analyse(*args, run_state, progress, **kwargs):
        run_state.update(result=result, reporting_ready=reporting_ready)
        progress('Writing briefing')
        gate.generate_text([], stage='presentation')
        clock.now = 901
        gate.generate_text([], stage='presentation')
    orchestrator = DocumentOrchestrator(gate)
    monkeypatch.setattr(orchestrator, '_analyse_pdf', analyse)
    stopped = orchestrator.analyse_pdf(b'%PDF')
    assert stopped is result
    assert stopped.pipeline_state == 'partial'
    assert stopped.retry_from == ('reporting' if reporting_ready else None)
    assert stopped.failed_stage == 'analysis_time_limit'
    assert stopped.failure_details['stopped_stage'] == 'Writing briefing'
    assert len(stopped.llm_usage) == len(gate.client.calls) == 1
    assert stopped.pipeline_total_ms == 901000


def test_ui_waits_for_worker_then_requires_explicit_retry(flow):
    from adaptive_document_agent.ui.analysis_job import snapshot
    from tests.test_interrupted_analysis_reruns import run
    def late(*args, **kwargs):
        attempt = flow.st.session_state['analysis_attempts']['same-scope']
        attempt['deadline'].expires_at = attempt['deadline'].clock() - 1
        state = snapshot(attempt)
        assert state['state'] == 'running'  # No overlapping replacement while draining.
        assert '15-minute' in state['progress']['label']
        flow.gateway.usage.append({'output_tokens': 7})
        return flow.result
    flow.orchestrator.analyse_pdf.side_effect = late
    assert run(flow) is flow.result
    assert flow.result.failed_stage == 'analysis_time_limit'
    assert 'analysis-result-same-scope' not in flow.cache_values
    assert run(flow) is flow.result
    assert flow.orchestrator.analyse_pdf.call_count == 1
    flow.orchestrator.analyse_pdf.side_effect = None
    run(flow, retry=True)
    assert flow.orchestrator.analyse_pdf.call_count == 2
    assert flow.gateway.run_deadline.remaining > 899


def test_deadline_is_checked_after_background_cleanup(budget, monkeypatch):
    from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
    from adaptive_document_agent.models import PipelineResult, ParsedDocument, DocumentProfile
    clock, deadline = budget
    gate = gateway()
    gate.run_deadline = deadline
    result = PipelineResult(document=ParsedDocument(document_id='test', sha256='hash',
        safe_filename='test.pdf', page_count=1), profile=DocumentProfile())
    def analyse(*args, resources, **kwargs):
        resources.callback(lambda: setattr(clock, 'now', 901))
        return result
    orchestrator = DocumentOrchestrator(gate)
    monkeypatch.setattr(orchestrator, '_analyse_pdf', analyse)
    assert orchestrator.analyse_pdf(b'%PDF').failed_stage == 'analysis_time_limit'
    assert result.pipeline_state == 'partial'


from tests.test_interrupted_analysis_reruns import flow  # Shared Streamlit harness.
