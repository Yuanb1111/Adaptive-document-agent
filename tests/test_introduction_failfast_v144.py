"""A failed required introduction blocks new dependent calls, never evidence."""
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from threading import Event

import pytest
from pydantic import BaseModel

from adaptive_document_agent.agent import company_introduction as introduction, orchestrator
from adaptive_document_agent.agent.introduction_checkpoint import (
    IntroductionGuardedGateway, IntroductionVerificationFailed,
)
from adaptive_document_agent.models import AnalysisResult, PipelineResult, ValidationIssue
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
from adaptive_document_agent.utils.caching import DiskCache
from tests.test_early_company_introduction import configure_pipeline, source_only


class Answer(BaseModel):
    value: str


def guarded(responses=(), *, cache=None):
    client = MockLLMClient(list(responses))
    gateway = LLMGateway(client, LLMSettings(), cache=cache)
    source, _ = source_only()
    prepared = introduction.PreparedCompanyIntroduction(gateway, source)
    assert prepared._future is None  # Deferred generation must remain deferred.
    prepared._future = Future()
    return IntroductionGuardedGateway(gateway, prepared), prepared, client


@pytest.mark.parametrize('error', [ValueError('Rejected source meaning'),
                                  PrivacyViolationError('Local Only'), CancelledError('Stopped')])
def test_completed_failure_preserves_exception_boundary_and_starts_no_call(error):
    guard, prepared, client = guarded()
    prepared._future.set_exception(error)
    expected = IntroductionVerificationFailed if isinstance(error, ValueError) else type(error)
    with pytest.raises(expected):
        guard.generate_structured([], Answer, stage='report')
    assert not client.calls and not guard.gateway.usage


def test_cache_hit_cannot_authorize_work_after_prerequisite_failure(tmp_path):
    guard, prepared, client = guarded([{'value': 'Source-bound response'}], cache=DiskCache(tmp_path))
    assert guard.generate_structured([], Answer, stage='report').value == 'Source-bound response'
    assert len(client.calls) == 1
    prepared._future.set_exception(ValueError('Review failed after previous request'))
    with pytest.raises(IntroductionVerificationFailed):
        guard.generate_structured([], Answer, stage='report')
    assert len(client.calls) == 1


def test_queued_request_rechecks_failure_after_gateway_admission():
    guard, prepared, client = guarded()
    checked = Event()
    original_check = guard.check
    def check():
        original_check()
        checked.set()
    guard.check = check
    guard.gateway._request_slots.acquire()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(guard.generate_structured, [], Answer, stage='report')
        assert checked.wait(3)
        prepared._future.set_exception(ValueError('Failed while queued'))
        guard.gateway._request_slots.release()
        with pytest.raises(IntroductionVerificationFailed, match='while queued'):
            future.result(timeout=3)
    assert not client.calls


def test_existing_cancellation_wins_at_admission_and_other_gateway_is_unchanged():
    guard, prepared, client = guarded([{'value': 'Independent invocation'}])
    # The first check is healthy; failure/cancellation happen while queued.
    checked, cancelled = Event(), Event()
    original_check = guard.check
    def check():
        original_check()
        checked.set()
    guard.check = check
    guard.gateway._request_slots.acquire()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(guard.generate_structured, [], Answer, stage='report', cancelled=cancelled)
        assert checked.wait(3)
        cancelled.set()
        prepared._future.set_exception(ValueError('Introduction failed'))
        guard.gateway._request_slots.release()
        with pytest.raises(CancelledError):
            future.result(timeout=3)
    # A view never mutates the gateway used by the introduction or another run.
    assert guard.gateway.generate_structured([], Answer, stage='report').value == 'Independent invocation'
    assert len(client.calls) == 1


def test_already_cancelled_caller_wins_over_already_failed_introduction():
    guard, prepared, client = guarded()
    prepared._future.set_exception(ValueError('Introduction failed'))
    cancelled = Event()
    cancelled.set()
    with pytest.raises(CancelledError):
        guard.generate_structured([], Answer, stage='report', cancelled=cancelled)
    assert not client.calls


def test_no_failure_check_starts_local_deferred_introduction():
    source, _ = source_only()
    gateway = LLMGateway(MockLLMClient(), LLMSettings())
    prepared = introduction.PreparedCompanyIntroduction(gateway, source)
    guard = IntroductionGuardedGateway(gateway, prepared)
    guard.check()
    assert prepared._future is None and not gateway.client.calls


def test_format_repair_admission_stops_when_initial_response_outlives_intro(monkeypatch):
    guard, prepared, client = guarded(['invalid JSON', {'value': 'Must not be consumed'}])
    generate = client.generate_text
    def text(*args, **kwargs):
        response = generate(*args, **kwargs)
        prepared._future.set_exception(ValueError('Introduction failed during initial response'))
        return response
    monkeypatch.setattr(client, 'generate_text', text)
    with pytest.raises(IntroductionVerificationFailed):
        guard.generate_structured([], Answer, stage='report')
    assert len(client.calls) == 1 and len(client.responses) == 1
    assert guard.gateway.usage[0]['status'] == 'invalid_format'


@pytest.mark.parametrize('mode', ['background', 'deferred'])
def test_late_known_failure_skips_brief_and_retains_completed_diagnostics(monkeypatch, mode):
    entered, release, finished = Event(), Event(), Event()
    def fail(gateway, source, draft, **kwargs):
        entered.set()
        if mode == 'background':
            assert release.wait(3)
        source.validation_warnings.append(ValidationIssue(code='company_introduction_summary_audit',
            message='Rejected source with all evidence retained', severity='info', stage='presentation'))
        finished.set()
        raise ValueError('Required six-axis meaning still missing')
    monkeypatch.setattr(introduction, 'ensure_company_introduction', fail)
    harness = configure_pipeline(monkeypatch, concurrent=mode == 'background')
    actual_plan = orchestrator.PresentationPlanner.plan
    def plan(self, result):
        if mode == 'background':
            assert entered.wait(3)
            release.set()
            with pytest.raises(ValueError, match='six-axis'):
                self.gateway.prepared._future.result(timeout=3)
        return actual_plan(self, result)
    monkeypatch.setattr(orchestrator.PresentationPlanner, 'plan', plan)
    brief_calls = []
    monkeypatch.setattr('adaptive_document_agent.agent.executive_brief.ExecutiveBriefWriter.generate',
                        lambda *a, **kw: brief_calls.append(True))
    result = harness.run()
    assert result.pipeline_state == 'partial' and result.retry_from == 'reporting'
    assert not brief_calls and result.executive_brief is None
    assert result.presentation_plan is not None  # Completed body plan remains diagnostic.
    assert result.document == harness.source.document
    codes = {w.code for w in result.validation_warnings}
    assert {'company_introduction_summary_audit', 'company_introduction_unavailable',
            'editorial_stages_skipped'} <= codes
    assert 'presentation_planning' in result.timings_ms


def test_reporting_next_request_stops_after_background_failure_and_keeps_completed_data(monkeypatch):
    entered, release, finished = Event(), Event(), Event()
    def fail(gateway, source, draft, **kwargs):
        entered.set()
        assert release.wait(3)
        source.validation_warnings.append(ValidationIssue(code='company_introduction_summary_audit',
            message='Background rejection', severity='info', stage='presentation'))
        finished.set()
        raise ValueError('Mandatory introduction rejected')
    monkeypatch.setattr(introduction, 'ensure_company_introduction', fail)
    harness = configure_pipeline(monkeypatch)
    completed = AnalysisResult(task_id='completed-calculation', title='Retained calculation', result={'sum': 12})
    def report(self, document, profile, *args, gateway, output):
        assert entered.wait(3)
        output.analysis_results.append(completed)
        output.report_markdown = 'Completed report context'
        output.validation_warnings.append(ValidationIssue(code='retained_report_audit', stage='report', message='Kept'))
        release.set()
        with pytest.raises(ValueError, match='Mandatory'):
            gateway.prepared._future.result(timeout=3)
        # Models never receive this request: the guard sees the completed failure.
        gateway.generate_structured([], Answer, stage='presentation')
        pytest.fail('A new topic request was allowed after introduction failure')
    monkeypatch.setattr(orchestrator.DocumentOrchestrator, '_generate_report', report)
    result = harness.run()
    assert result.analysis_results == [completed] and result.report_markdown == 'Completed report context'
    assert result.pipeline_state == 'partial' and result.retry_from == 'reporting'
    assert not harness.client.operations
    assert not {'slide_plan'} & {row['name'] for row in harness.intervals}
    assert {'retained_report_audit', 'company_introduction_summary_audit', 'editorial_stages_skipped'} <= {
        w.code for w in result.validation_warnings}
