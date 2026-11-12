"""Local rechecks retain source context without retransmitting unrelated series."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from adaptive_document_agent.agent.retained_copy_review import copy_review_payload
from adaptive_document_agent.utils.record_encoding import decode_records


def packet():
    return dict(copy_review_ids=['edited'], findings=[
        dict(insight=dict(id=iid, result_ids=[task]), observation_ids=[oid], selectable=True)
        for iid, task, oid in [('edited', 'task-1', 'primary'), ('other', 'task-2', 'unrelated')]],
        proposed_selection=dict(decisions=[dict(insight_id=iid, decision='include')
            for iid in ['edited', 'other']], ordered_insight_ids=['edited', 'other']),
        planned_source_citations=[dict(insight_id='edited', observation_ids=['primary', 'companion'])],
        source_rows=[dict(id=oid, table_id=table) for oid, table in [
            ('primary', 'table-1'), ('companion', 'table-1'), ('extra-period', 'table-1'),
            ('unrelated', 'table-2'), ('unbound', None)]],
        observations=[dict(id=oid, raw_value='(1,234)', evidence=[dict(page=2, text='Literal source')])
            for oid in ['primary', 'companion', 'extra-period', 'unrelated']],
        calculations=[dict(task_id=task, input_observation_ids=[oid], result=1)
            for task, oid in [('task-1', 'primary'), ('task-2', 'unrelated')]],
        analysis_plan=[dict(id=task) for task in ['task-1', 'task-2']],
        unavailable_findings=[dict(insight=dict(id='unavailable'))],
        source_row_assurance={'primary': 'unaudited', 'unrelated': 'audited'},
        verified_column_assurance={'primary': dict(status='unaudited'), 'unrelated': dict(status='audited')},
        source_pages=[dict(page=2, text='Complete source', layout_lines=[['Header', 10, 20, 30]]),
            dict(page=3, text='A related measure supplies a material qualification.')],
        profile=dict(analysis_focus='User priority'), report_outline=dict(title='Entire outline'),
        reviewed_priorities=['edited', 'other'])


def test_copy_packet_keeps_all_eligible_companions_and_original_pages_without_mutation():
    original = packet()
    before = deepcopy(original)
    scoped = copy_review_payload(original)
    assert original == before
    assert scoped['settled_selection_ids'] == ['edited', 'other']
    assert scoped['proposed_selection']['ordered_insight_ids'] == ['edited']
    assert [f['insight']['id'] for f in scoped['findings']] == ['edited']
    assert [r['id'] for r in scoped['source_rows']] == ['primary', 'companion', 'extra-period']
    assert scoped['observations'] == original['observations'][:3]
    assert scoped['calculations'] == original['calculations'][:1]
    assert scoped['analysis_plan'] == original['analysis_plan'][:1]
    assert scoped['source_pages'] == original['source_pages']
    assert scoped['profile'] == original['profile'] and scoped['report_outline'] == original['report_outline']
    assert scoped['source_row_assurance'] == {'primary': 'unaudited'}
    assert scoped['verified_column_assurance'] == {'primary': dict(status='unaudited')}


def test_full_coverage_packet_remains_complete():
    full = packet()
    full['copy_review_ids'] = []
    assert copy_review_payload(full) is full


@pytest.mark.parametrize('target', ['unknown', 'omitted'])
def test_scoping_cannot_authorize_an_unknown_or_omitted_page(target):
    full = packet()
    if target == 'omitted':
        full['proposed_selection']['decisions'][0]['decision'] = 'omit'
    else:
        full['copy_review_ids'] = [target]
    with pytest.raises(ValueError, match='Copy review'):
        copy_review_payload(full)


def saved_timeout():
    from adaptive_document_agent.models import PipelineResult
    from adaptive_document_agent.agent import retained_analysis as retained
    from tests.test_retained_brief_reporting_resume import checkpoint
    from tests.test_retained_analysis_v216 import gateway

    saved, _, _ = checkpoint()
    company = saved.presentation_plan.company.model_copy(deep=True)
    saved.document.pages[0].text_blocks = [dict(lines=[dict(text='Original source table')])]
    iid = saved.insights[0].id
    page = dict(title='Revenue', message='The company reported revenue.', companion_ids=[])
    selection = dict(decisions=[dict(insight_id=iid, decision='include', reason='Revenue trend.', page=page)],
                     ordered_insight_ids=[iid])
    accepted = dict(accepted=True, reason='Synthetic source protocol check.')
    retained.select_retained_analysis(gateway([selection, accepted]), saved)
    saved.presentation_plan = retained.compile_retained_analysis(saved)
    saved.presentation_plan.company = company
    issue = next(w for w in reversed(saved.validation_warnings) if w.code == retained.SELECTION_CODE)
    record = json.loads(issue.message)
    invalid = 'Revenue was RMB987,654,321 in FY2025.'
    record['selection']['decisions'][0]['page']['message'] = invalid
    issue.message = json.dumps(record)
    slide = next(s for s in saved.presentation_plan.slides if s.slide_type == 'analysis')
    slide.message, slide.bullets = invalid, [invalid]
    saved.failed_stage = 'analysis_time_limit'
    saved.failure_details = dict(component='AnalysisTimeLimit')
    current = PipelineResult(document=saved.document.model_copy(deep=True),
        profile=saved.profile.model_copy(deep=True), observations=saved.observations,
        analysis_plan=saved.analysis_plan, analysis_results=saved.analysis_results)
    return saved, current, iid, page, invalid, company


@pytest.mark.parametrize('corrected', [True, False])
def test_timeout_with_invalid_saved_copy_keeps_upstream_work_and_requires_fresh_checks(corrected):
    from adaptive_document_agent.agent.brief_reporting_resume import retained_brief_reporting
    from adaptive_document_agent.agent.retained_analysis_review import review_complete
    from tests.test_retained_analysis_v216 import gateway

    saved, current, iid, page, invalid, company = saved_timeout()
    accepted = dict(accepted=True, reason='Synthetic source protocol check.')
    patch = page if corrected else dict(page, message=invalid)
    responses = [accepted, dict(pages={iid: patch}), accepted]
    if not corrected:
        responses.extend([dict(pages={iid: patch}), accepted])
    mock = gateway(responses)
    before = saved.model_dump()
    resumed = retained_brief_reporting(saved, current, mock)
    assert resumed is not None and saved.model_dump() == before
    assert resumed.pipeline_state == ('complete' if corrected else 'partial')
    assert resumed.presentation_plan.company == company
    assert not review_complete(resumed) and resumed.executive_brief is None
    assert 'SourceAuthoredAnalysisSelection' not in [u['operation'] for u in mock.usage]
    if corrected:
        assert next(s for s in resumed.presentation_plan.slides if s.slide_type == 'analysis').message == page['message']
    else:
        assert resumed.failed_stage == 'presentation_selection'


@pytest.mark.parametrize('kind', ['deadline', 'privacy'])
def test_timeout_copy_repair_propagates_deadline_and_privacy_failures(monkeypatch, kind):
    from adaptive_document_agent.agent.brief_reporting_resume import retained_brief_reporting
    from adaptive_document_agent.services.analysis_deadline import AnalysisTimeLimitExceeded
    from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
    from tests.test_retained_analysis_v216 import gateway

    saved, current, *_ = saved_timeout()
    mock = gateway([])
    error = AnalysisTimeLimitExceeded() if kind == 'deadline' else PrivacyViolationError('Local Only')
    calls = []
    def stopped(*args, **kwargs):
        calls.append(1)
        raise error
    monkeypatch.setattr(mock, 'generate_structured', stopped)
    with pytest.raises(type(error)):
        retained_brief_reporting(saved, current, mock)
    assert calls == [1]


def test_private_589_recheck_preserves_sources_and_reduces_request():
    path = os.getenv('TIMEOUT_589_DIAGNOSTIC')
    if not path:
        pytest.skip('Set TIMEOUT_589_DIAGNOSTIC for the private timeout replay.')
    from adaptive_document_agent.models import PipelineResult
    from adaptive_document_agent.agent.retained_analysis import selection_context, selected_record, RetainedAnalysisSelection
    from adaptive_document_agent.agent.retained_selection_coverage import review_selection_coverage
    from tests.test_retained_analysis_v216 import gateway

    result = PipelineResult.model_validate_json(Path(path).read_bytes())
    selection = RetainedAnalysisSelection.model_validate(selected_record(result)['selection'])
    targets = json.loads(next(w.message for w in reversed(result.validation_warnings)
        if w.code == 'retained_selection_coverage'))['copy_review_ids']
    original = result.model_dump(include={'document', 'observations', 'analysis_results', 'insights'})
    context = selection_context(result)
    mock = gateway([dict(accepted=True, reason='Synthetic request protocol check.')]*2)
    review_selection_coverage(mock, context, selection, result)
    review_selection_coverage(mock, {**context, 'copy_review_ids': targets}, selection, result)
    full_wire, scoped_wire = [c[-1]['content'] for c in mock.client.calls]
    scoped = decode_records(json.loads(scoped_wire.split('\n', 1)[1].rsplit('\n', 1)[0]))
    assert scoped['source_pages'] == context['source_pages']
    assert {f['insight']['id'] for f in scoped['findings']} == set(targets)
    assert len(scoped_wire) < .6 * len(full_wire)
    assert result.model_dump(include=set(original)) == original
    assert not any(w.code == 'presentation_retained_analysis_review' for w in result.validation_warnings)
    print(f'Full request: {len(full_wire)} chars; local recheck: {len(scoped_wire)} chars')


@pytest.mark.parametrize('corrected', [True, False])
def test_private_589_timeout_repairs_only_invalid_copy_before_reusing_reporting(corrected):
    path = os.getenv('TIMEOUT_589_DIAGNOSTIC')
    if not path:
        pytest.skip('Set TIMEOUT_589_DIAGNOSTIC for the private timeout replay.')
    from adaptive_document_agent.models import PipelineResult
    from adaptive_document_agent.agent.retained_analysis import selection_context, selected_record, RetainedAnalysisSelection
    from adaptive_document_agent.agent.retained_page_sources import AuthoredPageErrors, validate_authored_pages
    from adaptive_document_agent.agent.brief_reporting_resume import retained_brief_reporting
    from adaptive_document_agent.agent.retained_analysis_review import review_complete
    from tests.test_retained_analysis_v216 import gateway

    saved = PipelineResult.model_validate_json(Path(path).read_bytes())
    context = selection_context(saved)
    selection = RetainedAnalysisSelection.model_validate(selected_record(saved)['selection'])
    # Current main binds the original literal day-count definition. Exercise
    # recovery with an explicitly corrupted copy while retaining real source
    # data and the accepted original copy as the synthetic repair candidate.
    validate_authored_pages(selection, context, saved)
    decision = next(d for d in selection.decisions if d.decision == 'include')
    page = decision.page.model_dump()
    decision.page.message += ' The source reports an unbound amount of RMB987,654,321.'
    warning = next(w for w in reversed(saved.validation_warnings) if w.code == 'presentation_retained_analysis_selection')
    record = json.loads(warning.message)
    record['selection'] = selection.model_dump(mode='json', exclude_none=True)
    warning.message = json.dumps(record)
    slide = next(s for s in saved.presentation_plan.slides if decision.insight_id in s.insight_ids)
    slide.message = decision.page.message
    slide.bullets[0] = slide.message
    with pytest.raises(AuthoredPageErrors) as caught:
        validate_authored_pages(selection, context, saved)
    iid, = caught.value.by_insight
    if not corrected:
        page = decision.page.model_dump()
    accepted = dict(accepted=True, reason='Synthetic copy-check protocol verdict.')
    responses = [accepted, dict(pages={iid: page}), accepted]
    if not corrected:
        responses.extend([dict(pages={iid: page}), accepted])
    mock = gateway(responses)
    current = PipelineResult(document=saved.document.model_copy(deep=True),
        profile=saved.profile.model_copy(deep=True), observations=saved.observations,
        analysis_plan=saved.analysis_plan, analysis_results=saved.analysis_results)
    before = saved.model_dump()
    resumed = retained_brief_reporting(saved, current, mock)
    assert resumed is not None
    assert saved.model_dump() == before
    assert not review_complete(resumed)
    if corrected:
        assert resumed.pipeline_state != 'partial'
        assert resumed.presentation_plan.company == saved.presentation_plan.company
        old = {s.id: s for s in saved.presentation_plan.slides}
        for slide in resumed.presentation_plan.slides:
            if iid not in slide.insight_ids:
                assert slide == old[slide.id]
        assert resumed.executive_brief is None
    else:
        assert resumed.pipeline_state == 'partial' and resumed.failed_stage == 'presentation_selection'
        assert 'outside its bound evidence' in resumed.failure_details['message']
    operations = [u['operation'] for u in mock.usage]
    assert 'SourceAuthoredAnalysisSelection' not in operations
    assert operations[:3] == ['RetainedSelectionCoverage', 'RetainedPageRevisions', 'RetainedSelectionCoverage']
    for call, op in zip(mock.client.calls, operations):
        if op == 'RetainedSelectionCoverage':
            packet = decode_records(json.loads(call[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0]))
            assert packet['copy_review_ids'] == [iid]
            assert packet['source_pages'] == context['source_pages']
