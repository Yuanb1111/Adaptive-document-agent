"""Start independent copy once after strict topic corrections, before visuals."""
from concurrent.futures import CancelledError
from contextlib import ExitStack
from threading import Event, get_ident

import pytest

from adaptive_document_agent.agent import presentation_visual_enrichment
from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from adaptive_document_agent.agent.prepared_executive_brief import (
    current_executive_brief, prepare_executive_brief,
)
from adaptive_document_agent.agent.presentation_planner import PresentationPlanner
from adaptive_document_agent.agent.topic_takeaway_repair import TakeawayCorrection
from adaptive_document_agent.models import DocumentPage
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from tests.test_executive_brief import payload
from tests.test_topic_scope_recovery_regressions import _synthetic_result


def test_real_topic_repair_precedes_single_brief_and_overlaps_visuals(monkeypatch):
    result = _synthetic_result('metric_alias')
    text = 'Units were 22 in FY2025.'
    result.document.pages = [DocumentPage(page_number=8, text=text)]
    source = result.model_dump(include={'document', 'observations', 'charts'})
    entered, visual_done = Event(), Event()
    calls, hook_threads, timings = [], [], {}
    brief = ExecutiveBrief.model_validate(payload(text, page=8))

    class Gateway:
        discovery_workers = 2

        def generate_structured(self, messages, response_model, **kwargs):
            assert response_model is TakeawayCorrection
            assert not entered.is_set(), 'No stale briefing may start before topic correction'
            calls.append('repair')
            return TakeawayCorrection(title='Reported loss amounts and percentages', takeaway=
                'Loss for the year amounted to USD 140 in FY2023 and USD 230 in FY2025.')

    def generate(self, snapshot, *, cancelled):
        assert calls == ['repair']
        assert snapshot.presentation_topics.topics[0].takeaway == (
            'Loss for the year amounted to USD 140 in FY2023 and USD 230 in FY2025.')
        calls.append('brief')
        entered.set()
        assert visual_done.wait(5)
        return brief

    def visuals(gateway, current, plan):
        assert entered.wait(5), 'Brief and visual work must overlap'
        assert not ClaimValidator().validate_plan(plan, current.observations, current.charts)
        visual_done.set()
        return plan

    monkeypatch.setattr(ExecutiveBriefWriter, 'generate', generate)
    monkeypatch.setattr(presentation_visual_enrichment, 'enrich_selected_plan', visuals)
    gateway = Gateway()
    with ExitStack() as resources:
        prepared = []

        def ready(current, compiled):
            hook_threads.append(get_ident())
            seed = current.model_copy(deep=True)
            seed.presentation_plan = compiled.model_copy(deep=True)
            prepared.append(resources.enter_context(
                prepare_executive_brief(gateway, seed, timings=timings)))

        result.presentation_plan = PresentationPlanner(gateway, on_topics_ready=ready).plan(result)
        assert len(prepared) == 1
        assert current_executive_brief(gateway, result, prepared[0]) == brief
    assert hook_threads == [get_ident()]
    assert calls == ['repair', 'brief']
    assert result.model_dump(include={'document', 'observations', 'charts'}) == source
    assert not any(issue.code == 'executive_brief_snapshot_refreshed' for issue in result.validation_warnings)
    assert 'executive_brief_duration' in timings


@pytest.mark.parametrize('failed_stage', ['compile', 'repair'])
def test_failed_topic_boundary_never_starts_an_editorial_worker(monkeypatch, failed_stage):
    from adaptive_document_agent.agent import topic_plan_compiler, topic_takeaway_repair
    result = _synthetic_result('metric_alias')
    callbacks = []

    def fail(*args):
        raise ValueError('Rejected stable topic boundary')

    if failed_stage == 'compile':
        monkeypatch.setattr(topic_plan_compiler, 'compile_topic_plan', fail)
    else:
        monkeypatch.setattr(topic_takeaway_repair, 'repair_withheld_takeaways', fail)
    monkeypatch.setattr(presentation_visual_enrichment, 'enrich_selected_plan', lambda *args:
        pytest.fail('Rejected topics cannot reach visuals'))
    with pytest.raises(ValueError, match='Rejected stable topic boundary'):
        PresentationPlanner(object(), on_topics_ready=lambda *args: callbacks.append(args)).plan(result)
    assert not callbacks


def test_visual_failure_cancels_started_brief_without_masking_primary_error(monkeypatch):
    result = _synthetic_result('metric_alias')
    entered = Event()

    class Gateway:
        discovery_workers = 2

        def generate_structured(self, messages, response_model, **kwargs):
            return TakeawayCorrection(takeaway=
                'Loss for the year amounted to USD 140 in FY2023 and USD 230 in FY2025.')

    def generate(self, snapshot, *, cancelled):
        entered.set()
        assert cancelled.wait(5)
        raise CancelledError()

    def visuals(*args):
        assert entered.wait(5)
        raise RuntimeError('Primary visual failure')

    monkeypatch.setattr(ExecutiveBriefWriter, 'generate', generate)
    monkeypatch.setattr(presentation_visual_enrichment, 'enrich_selected_plan', visuals)
    gateway = Gateway()
    prepared = []
    with pytest.raises(RuntimeError, match='Primary visual failure'):
        with ExitStack() as resources:
            def ready(current, compiled):
                prepared.append(resources.enter_context(
                    prepare_executive_brief(gateway, current, timings={})))
            PresentationPlanner(gateway, on_topics_ready=ready).plan(result)
    assert prepared[0]._cancelled.is_set()
    assert prepared[0]._pool._shutdown
