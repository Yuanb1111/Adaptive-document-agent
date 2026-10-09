"""Stable topics permit overlapping copy without shared mutations or orphan calls."""
from concurrent.futures import CancelledError
from threading import Event
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.executive_brief import _selected_topic_pages
from adaptive_document_agent.agent.prepared_executive_brief import prepare_executive_brief
from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from tests.test_executive_brief import result_for, payload
from tests.test_topic_summary_coverage import _topic_result


def test_stable_topics_supply_same_pages_before_and_after_slide_layout():
    result = _topic_result(count=3)
    expected = _selected_topic_pages(result, set(range(1, 101)))
    assert len(expected) == 3
    result.presentation_plan = None
    assert _selected_topic_pages(result, set(range(1, 101))) == expected


@pytest.mark.parametrize('changed', [None, 'document', 'presentation_topics'])
def test_editorial_snapshot_is_isolated_and_revalidated(monkeypatch, changed):
    from adaptive_document_agent.agent import prepared_executive_brief as module
    text = 'Revenue was USD 12 million in 2025.'
    source = result_for([text])
    original = source.model_copy(deep=True)
    entered, release = Event(), Event()
    brief = ExecutiveBrief.model_validate(payload(text))
    def generate(self, snapshot, *, cancelled):
        entered.set()
        assert release.wait(5)
        assert not cancelled.is_set()
        snapshot.validation_warnings.append(ValidationIssue(code='executive_brief_repair_audit',
            stage='report', severity='info', message='Verified local audit'))
        return brief
    monkeypatch.setattr(module.ExecutiveBriefWriter, 'generate', generate)
    timings = {}
    with prepare_executive_brief(SimpleNamespace(discovery_workers=2), source, timings=timings) as prepared:
        assert entered.wait(5)
        # The caller is free to plan slides while the writer is blocked.
        final = source.model_copy(deep=True)
        if changed == 'document':
            final.document.pages[0].text = 'Changed source'
        elif changed:
            from adaptive_document_agent.models import PresentationTopicSelection
            final.presentation_topics = PresentationTopicSelection()
        release.set()
        if changed:
            with pytest.raises(ValueError, match='inputs changed'):
                prepared.result(final)
        else:
            assert prepared.result(final) == brief
        assert final.validation_warnings[-1].code == 'executive_brief_repair_audit'
    assert source == original
    assert 'executive_brief_duration' in timings


def test_worker_error_keeps_audit_and_drains(monkeypatch):
    from adaptive_document_agent.agent import prepared_executive_brief as module
    source = result_for(['Verified source'])
    def generate(self, snapshot, *, cancelled):
        snapshot.validation_warnings.append(ValidationIssue(code='executive_brief_repair_audit',
            stage='report', severity='warning', message='Rejected original and patch'))
        raise ValueError('Invalid copy')
    monkeypatch.setattr(module.ExecutiveBriefWriter, 'generate', generate)
    with prepare_executive_brief(SimpleNamespace(discovery_workers=2), source, timings={}) as prepared:
        with pytest.raises(ValueError, match='Invalid copy'):
            prepared.result(source)
        assert source.validation_warnings[-1].message == 'Rejected original and patch'
    assert prepared._pool._shutdown


def test_cancellation_stops_next_paid_request(monkeypatch):
    from adaptive_document_agent.agent import prepared_executive_brief as module
    from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
    entered, stopped = Event(), Event()
    def generate(self, snapshot, *, cancelled):
        entered.set()
        assert cancelled.wait(5)
        stopped.set()
        raise CancelledError()
    monkeypatch.setattr(ExecutiveBriefWriter, 'generate', generate)
    with pytest.raises(RuntimeError, match='primary failure'):
        with prepare_executive_brief(SimpleNamespace(discovery_workers=2), result_for(['source']), timings={}) as prepared:
            assert entered.wait(5)
            raise RuntimeError('primary failure')
    assert stopped.is_set() and prepared._pool._shutdown


def test_local_and_stateful_gateways_cannot_start_parallel_copy():
    with pytest.raises(ValueError, match='concurrent cloud'):
        with prepare_executive_brief(SimpleNamespace(discovery_workers=1), result_for(['source']), timings={}):
            pytest.fail('Must remain serial')


@pytest.mark.parametrize('mode', ['cloud', 'local', 'stateful'])
def test_actual_orchestrator_overlaps_only_stable_cloud_editorial_work(monkeypatch, mode):
    from adaptive_document_agent.agent import orchestrator
    from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
    from adaptive_document_agent.models import PipelineResult, PresentationTopic, PresentationTopicSelection
    from tests.test_early_company_introduction import configure_pipeline
    harness = configure_pipeline(monkeypatch, local=mode == 'local', concurrent=mode != 'stateful')
    entered, layout = Event(), Event()
    # The harness replaces extraction/selection with a fixed scheduling fixture;
    # this test exercises the real resource-owning orchestrator, not semantics.
    topics = PresentationTopicSelection(topics=[PresentationTopic(id='fixed', title='Activity',
        question='What activity is described?', rationale='Source narrative is available.',
        series_ids=['fixed-selected-series'])])
    def report(self, document, profile, *args):
        return PipelineResult(document=document, profile=profile, presentation_topics=topics,
                              report_markdown='Evidence report')
    monkeypatch.setattr(orchestrator.DocumentOrchestrator, '_generate_report', report)
    plan = orchestrator.PresentationPlanner.plan
    def planning(self, snapshot):
        if mode == 'cloud':
            assert entered.wait(5), 'Brief must start before slide layout finishes'
        else:
            assert not entered.is_set(), 'Local and stateful requests must retain order'
        layout.set()
        return plan(self, snapshot)
    monkeypatch.setattr(orchestrator.PresentationPlanner, 'plan', planning)
    text = 'We operate a business software platform.'
    brief = ExecutiveBrief.model_validate(payload(text, page=5))
    def generate(self, snapshot, **kwargs):
        entered.set()
        assert layout.wait(5)
        return brief
    monkeypatch.setattr(ExecutiveBriefWriter, 'generate', generate)
    from threading import get_ident
    caller = get_ident()
    callbacks = []
    result = harness.run(progress=lambda message: callbacks.append(get_ident()))
    assert result.executive_brief == brief
    assert set(callbacks) == {caller}
    assert ('executive_brief_duration' in result.stage_details_ms) == (mode == 'cloud')
    assert not any(issue.code == 'executive_brief_unavailable' for issue in result.validation_warnings)
