"""Bounded editorial scheduling retains the native budget and source gates."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent import brief_budget_schedule as schedule
from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.services.llm import LLMSettings, ProviderName
from adaptive_document_agent.services.llm.reasoning_policy import request_reasoning_policy
from adaptive_document_agent.validation.scoped_narrative_values import scoped_value_errors
from tests.test_physical_budget_refinement_v130 import source
from tests.test_p0_composition import observation


EDITORIAL_OPERATIONS = [
    ('presentation', name) for name in (
        'TopicCoverageDelta', 'SummarySynthesisDraft',
        'IntroductionAudienceSelection', 'IntroductionMeaningRevision',
        'IntroductionMeaningResolution', 'SummaryCoverageReview',
        'PhysicalBudgetReview', 'IntroductionAudienceReview',
        'SummaryLayoutPages', 'PhysicalBudgetSelection')
] + [('report', 'BriefMeaningReview')]


@pytest.mark.parametrize('stage,operation', EDITORIAL_OPERATIONS)
def test_new_editorial_reduction_is_route_stage_and_optout_bound(stage, operation):
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash')
    def policy(**kwargs):
        return request_reasoning_policy(settings, stage=kwargs.get('stage', stage),
            operation=operation, model='deepseek-flash')
    assert policy()['options'] == {'extra_body': {'thinking': {'type': 'disabled'}}}
    assert policy(stage='insight')['options'] == {}
    settings.simple_task_reasoning = 'provider_default'
    assert policy()['options'] == {}
    settings.simple_task_reasoning = 'reduced'
    settings.base_url = 'https://unverified.example/v1'
    assert policy()['status'] == 'unsupported' and policy()['options'] == {}


def test_budget_selection_and_review_use_configured_editorial_reasoning():
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash')
    selection = request_reasoning_policy(settings, stage='presentation',
        operation='PhysicalBudgetSelection', model='deepseek-flash')
    assert selection['intent'] == 'reduce' and selection['status'] == 'requested'
    assert selection['options'] == {'extra_body': {'thinking': {'type': 'disabled'}}}
    review = request_reasoning_policy(settings, stage='presentation',
        operation='PhysicalBudgetReview', model='deepseek-flash')
    assert review['options'] == {'extra_body': {'thinking': {'type': 'disabled'}}}


def test_only_known_oversized_drafts_defer_briefing():
    result, _, _, _ = source()
    assert not schedule.briefing_waits_for_budget(result, result.presentation_plan)
    original = result.presentation_plan.model_copy(deep=True)
    analysis = next(s for s in original.slides if s.slide_type == 'analysis')
    result.presentation_plan.slides = [analysis.model_copy(update={'id': str(i)}) for i in range(11)]
    assert schedule.briefing_waits_for_budget(result, result.presentation_plan)
    result.presentation_plan.slides = [analysis.model_copy(update={'id': str(i), 'slide_type': 'conclusion'})
                                       for i in range(21)]
    assert schedule.briefing_waits_for_budget(result, result.presentation_plan)
    result.presentation_topics = None
    assert not schedule.briefing_waits_for_budget(result, result.presentation_plan)
    assert not schedule.briefing_waits_for_budget(result, None)


def test_deferred_brief_is_written_once_and_still_checks_native_budget(monkeypatch):
    from adaptive_document_agent.agent import executive_brief, presentation_budget_refinement
    from adaptive_document_agent.services import slide_budgets
    result, _, _, _ = source()
    result.executive_brief = None
    calls = []
    sentinel = SimpleNamespace(title='Independent source-checked brief')
    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate',
        lambda self, current: calls.append('write') or sentinel)
    monkeypatch.setattr(presentation_budget_refinement, 'measure',
        lambda current: (calls.append('measure') or 'native-deck', {}))
    monkeypatch.setattr(slide_budgets, 'require_exported_budgets',
        lambda deck, current: calls.append(('gate', deck)))
    schedule.complete_deferred_brief(None, result)
    schedule.complete_deferred_brief(None, result)
    assert calls == ['write', 'measure', ('gate', 'native-deck')]
    assert result.executive_brief is sentinel


def _attached_introduction(result):
    from adaptive_document_agent.models.summary import SummaryReview, SummarySlidePage, SummarySlideItem
    result.presentation_plan.company.summary_review = SummaryReview(
        document_id=result.document.document_id, document_sha256=result.document.sha256,
        source_pages=[1], status='complete')
    result.presentation_plan.company.summary_pages = [SummarySlidePage(
        id='intro', title='Source topic', source_section='Source section', items=[SummarySlideItem(
            label='Statement', text='Source statement.', source_quote='Source statement.',
            source_pages=[1], part_ids=['part'])])]


@pytest.mark.parametrize('physical_count,deferred', [(18, False), (21, True)])
def test_attached_native_projection_detects_spill_before_disposable_brief(monkeypatch, physical_count, deferred):
    from adaptive_document_agent.agent import presentation_budget_refinement
    from tests.test_physical_budget_refinement_v130 import measurement
    result, _, _, _ = source()
    _attached_introduction(result)
    original = result.model_dump_json()
    snapshots = []
    def measured(snapshot):
        snapshots.append(snapshot)
        return measurement(snapshot, physical_count, 8)
    monkeypatch.setattr(presentation_budget_refinement, 'measure', measured)
    assert not schedule.briefing_waits_for_budget(result, result.presentation_plan)
    assert schedule.native_briefing_waits_for_budget(result, result.presentation_plan) is deferred
    assert len(snapshots) == 1 and snapshots[0] is not result
    assert result.model_dump_json() == original


def test_unmeasurable_preliminary_layout_cannot_create_a_budget_verdict(monkeypatch):
    from adaptive_document_agent.agent import presentation_budget_refinement
    result, _, _, _ = source()
    _attached_introduction(result)
    calls = []
    def unavailable(snapshot):
        calls.append('projection')
        raise ValueError('Pre-visual composition is not ready')
    monkeypatch.setattr(presentation_budget_refinement, 'measure', unavailable)
    assert not schedule.native_briefing_waits_for_budget(result, result.presentation_plan)
    assert calls == ['projection']
    result.presentation_plan.company.summary_review.status = 'incomplete'
    assert not schedule.native_briefing_waits_for_budget(result, result.presentation_plan)
    assert calls == ['projection']


def test_deferred_brief_cannot_hide_an_export_budget_failure(monkeypatch):
    from adaptive_document_agent.agent import executive_brief, presentation_budget_refinement
    from adaptive_document_agent.services import slide_budgets
    result, _, _, _ = source()
    result.executive_brief = None
    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate', lambda *args: None)
    monkeypatch.setattr(presentation_budget_refinement, 'measure', lambda current: ('native', {}))
    def fail(*args):
        raise ValueError('Actual native page count exceeds the configured budget')
    monkeypatch.setattr(slide_budgets, 'require_exported_budgets', fail)
    with pytest.raises(ValueError, match='Actual native'):
        schedule.complete_deferred_brief(None, result)


def test_cached_label_parsing_never_reuses_a_numeric_or_selection_verdict():
    own, other = observation('own', 'Service hours', 100), observation('other', 'Staff hours', 200)
    slide = PresentationSlide(id='s', slide_type='analysis', title='Review',
        message='Service hours rose to 100.')
    assert not scoped_value_errors(slide, [own, other])
    own.value, own.raw_value = 200, '200'
    other.value, other.raw_value = 100, '100'
    assert scoped_value_errors(slide, [own, other])
    own.category_dimensions = {'region': 'North'}
    slide.message = 'Service hours for North rose to 200.'
    assert not scoped_value_errors(slide, [own, other])
    other.value, other.raw_value = 200, '200'
    assert scoped_value_errors(slide, [other], [own, other])


def test_geometry_cache_is_fresh_for_each_validation_pass(monkeypatch):
    from adaptive_document_agent.services import summary_layout_evidence as evidence
    from adaptive_document_agent.services.summary_validation import reading_errors
    from adaptive_document_agent.models.summary import SummaryReview
    from adaptive_document_agent.services.summary_source import source_blocks
    from tests.test_summary_layout_recovery_v146 import rotated_source
    from tests.test_summary_line_recovery_v114 import Responses
    from adaptive_document_agent.agent.summary_reader import _read_batch
    from threading import Event
    result = rotated_source()
    blocks = source_blocks(result, [1])
    rows = [dict(block_id=blocks[0].id, start_line=n, end_line=n,
                 role='layout' if n > 1 else 'content', title='Source passage',
                 reading_note='Read source.', facts=[]) for n in range(1, 4)]
    outcome = _read_batch(Responses([rows, rows]), result, blocks, Event())
    assert outcome.error is None
    review = SummaryReview(document_id=result.document.document_id,
        document_sha256=result.document.sha256, source_pages=[1], source_blocks=blocks,
        parts=outcome.parts, scope_ranges=[dict(start_page=1, end_page=1, reason='The assigned source page.')])
    original = evidence._geometry_rows
    misses = []
    def counted(page, cache=None):
        if cache is None or id(page) not in cache:
            misses.append(page.page_number)
        return original(page, cache)
    monkeypatch.setattr(evidence, '_geometry_rows', counted)
    assert not reading_errors(review, result)
    assert len(misses) == len(set(misses))
    before = deepcopy(result.document.pages[0].text_blocks)
    result.document.pages[0].text_blocks[0]['lines'].append(
        {'text': 'OPERATING MODEL', 'bbox': [40, 300, 400, 312]})
    assert reading_errors(review, result)
    result.document.pages[0].text_blocks = before
    assert not reading_errors(review, result)


def test_partial_budget_failure_reports_time_spent_in_the_final_stage(monkeypatch):
    import time
    from adaptive_document_agent.agent import presentation_budget_refinement
    from tests.test_reporting_checkpoint_v144 import (
        _coverage_fixture, _run_coverage_fixture, SyntheticCoverageFlowClient)
    result, raw = _coverage_fixture()
    client = SyntheticCoverageFlowClient(result)
    clock = [0.0]
    # Orchestration reads its clock at invocation time. No sleep or timing
    # threshold is needed to prove the formerly omitted late-stage interval.
    monkeypatch.setattr(time, 'perf_counter', lambda: clock[0])
    def failed(*args, **kwargs):
        clock[0] += 30.0
        raise ValueError('Final source gate rejected the proposed briefing')
    monkeypatch.setattr(presentation_budget_refinement, 'refine_presentation_budget', failed)
    completed = _run_coverage_fixture(monkeypatch, result, raw, client)
    assert completed.pipeline_state == 'partial' and completed.retry_from == 'reporting'
    assert completed.failed_stage == 'presentation_budget'
    assert completed.failure_details == dict(component='PresentationBudget',
        error_type='ValueError', message='Final source gate rejected the proposed briefing')
    assert completed.pipeline_total_ms == 30000
    assert any('Final source gate' in warning.message for warning in completed.validation_warnings)
