import json
import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_selection_feedback import retain_selection_feedback, selection_retry_feedback
from tests.test_retained_analysis_v216 import _linked_result, gateway


def fixture():
    result = _linked_result()
    result.document.pages[0].text_blocks = [dict(lines=[dict(text='Source table')])]
    iid = result.insights[0].id
    response = dict(decisions=[dict(insight_id=iid, decision='include', reason='Synthetic priority.',
        page=dict(title='Revenue', message='Revenue was USD999 million.', companion_ids=[]))],
        ordered_insight_ids=[iid])
    accepted = dict(accepted=True, missing_insight_ids=[], reason='Synthetic coverage only.')
    with pytest.raises(ValueError):
        retained.select_retained_analysis(gateway([response, accepted] * 2), result)
    result.failed_stage = 'presentation_selection'
    result.failure_details = dict(component='RetainedAnalysisSelection')
    result.validation_warnings.append(retain_selection_feedback(result))
    return result, response, accepted


def test_rejected_feedback_is_rechecked_and_cannot_approve_or_become_stale():
    result, _, _ = fixture()
    context = retained.selection_context(result, source_authoring=True)
    feedback = selection_retry_feedback(result, context)
    assert feedback and not feedback['final_approval']
    assert 'USD999 million' in feedback['current_binding_errors'][0]
    assert retained.selected_record(result) is None
    result.observations[0].raw_value = '888888'
    assert selection_retry_feedback(result, retained.selection_context(result, source_authoring=True)) is None


def test_retry_repairs_rejected_page_without_regenerating_valid_selection():
    result, response, accepted = fixture()
    response['decisions'][0]['page']['message'] = 'Reported revenue.'
    iid = response['ordered_insight_ids'][0]
    mock = gateway([accepted, dict(pages={iid: response['decisions'][0]['page']}), accepted])
    retained.select_retained_analysis(mock, result)
    messages = json.dumps(mock.client.calls[1])
    assert 'pages_to_correct' in messages and 'USD999 million' in messages
    assert [u['operation'] for u in mock.usage] == [
        'RetainedSelectionCoverage', 'RetainedPageRevisions', 'RetainedSelectionCoverage']
    assert retained.selected_record(result)
    assert not any(w.code=='presentation_retained_analysis_review' for w in result.validation_warnings)


def test_other_failure_stage_cannot_inject_selection_feedback():
    result, _, _ = fixture()
    result.failed_stage = 'presentation_coverage'
    assert retain_selection_feedback(result) is None


def test_now_valid_retained_copy_still_requires_independent_coverage():
    result, _, accepted = fixture()
    issue = result.validation_warnings[-1]
    record = json.loads(issue.message)
    record['rejected']['rejected_draft']['decisions'][0]['page']['message'] = 'Reported revenue.'
    issue.message = json.dumps(record)
    mock = gateway([accepted])
    retained.select_retained_analysis(mock, result)
    assert len(mock.client.calls) == 1
    assert 'RetainedSelectionCoverage' in json.dumps(mock.client.calls)
    assert retained.selected_record(result)
    assert not any(w.code == 'presentation_retained_analysis_review' for w in result.validation_warnings)


@pytest.mark.parametrize('resume', [False, True])
def test_shortened_omission_id_is_recovered_before_fresh_coverage_review(resume):
    from adaptive_document_agent.models import ValidationIssue
    from tests.test_retained_source_citations import fixture as source_fixture

    result, _, proposal = source_fixture()
    task_id = 'task_other'
    alias = f'insight_{task_id}'
    finding_id = alias + '_full'
    result.analysis_results.append(result.analysis_results[0].model_copy(update={'task_id': task_id}))
    result.insights.append(result.insights[0].model_copy(update={'id': finding_id, 'result_ids': [task_id]}))
    draft = proposal.model_dump(exclude_none=True)
    draft['decisions'].append(dict(insight_id=alias, decision='omit', reason='Repeats the selected series.'))
    approved = dict(accepted=True, reason='Synthetic independent coverage review.')
    if resume:
        result.failed_stage = 'presentation_selection'
        result.failure_details = dict(component='RetainedAnalysisSelection')
        result.validation_warnings.append(ValidationIssue(code='retained_page_draft_rejected',
            stage='presentation', message=json.dumps(dict(rejected_draft=draft, row_ids={},
                diagnostic=f'Unknown finding {alias}'))))
        result.validation_warnings.append(retain_selection_feedback(result))
    mock = gateway([approved] if resume else [draft, approved])
    retained.select_retained_analysis(mock, result)
    selected = retained.selected_record(result)['selection']
    assert selected['ordered_insight_ids'] == draft['ordered_insight_ids']
    assert selected['decisions'] == [draft['decisions'][0], {**draft['decisions'][1], 'insight_id': finding_id}]
    assert [u['operation'] for u in mock.usage] == (
        ['RetainedSelectionCoverage'] if resume else ['SourceAuthoredAnalysisSelection', 'RetainedSelectionCoverage'])
    assert not any(w.code == 'presentation_retained_analysis_review' for w in result.validation_warnings)


@pytest.mark.parametrize('case', ['ambiguous', 'included', 'duplicate', 'not_provenanced'])
def test_omission_id_recovery_does_not_guess_or_rebind_selected_findings(case):
    alias = 'insight_task_other'
    finding_id = alias + '_full'
    insight = dict(id=finding_id, result_ids=['task_other'] if case != 'not_provenanced' else ['task_different'])
    context = dict(findings=[dict(insight=insight, selectable=True)], unavailable_findings=[])
    if case == 'ambiguous':
        context['unavailable_findings'].append(dict(insight={**insight, 'id': alias + '_another'}))
    decisions = [dict(insight_id=alias, decision='include' if case == 'included' else 'omit', reason='Test decision.')]
    if case == 'duplicate':
        decisions.append(dict(insight_id=finding_id, decision='omit', reason='Already decided.'))
    proposal = retained.RetainedAnalysisSelection(decisions=decisions, ordered_insight_ids=['other'])
    assert not retained.repair_omission_ids(proposal, context)
    with pytest.raises(ValueError, match='unknown finding'):
        retained._validate_selection(proposal, context)


def test_final_source_rejection_gets_one_bounded_selection_repair_not_an_approval():
    from adaptive_document_agent.models import ValidationIssue
    from adaptive_document_agent.agent.retained_analysis_review import needs_catalog_retry
    from adaptive_document_agent.agent.retained_selection_feedback import can_retry_source_review
    result, response, accepted = fixture()
    response['decisions'][0]['page']['message'] = 'Reported revenue.'
    iid = response['ordered_insight_ids'][0]
    retained.select_retained_analysis(gateway([
        accepted, dict(pages={iid: response['decisions'][0]['page']}), accepted]), result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    result.pipeline_state = 'partial'
    result.failed_stage = 'presentation_coverage'
    result.failure_details = dict(component='PresentationCoverage',message='A material trajectory was omitted.')
    from adaptive_document_agent.agent.retained_analysis_review import review_context
    slide = next(s for s in result.presentation_plan.slides if s.slide_type=='analysis')
    result.validation_warnings.append(ValidationIssue(code='presentation_retained_analysis_review',
        stage='presentation',message=json.dumps(dict(contract=1,fingerprint=retained.fingerprint(review_context(result)),review=dict(
            verdicts=[dict(slide_id=slide.id,accepted=True,reason='Copy correct')],
            omissions_accepted=False,omission_reason='Material trajectory omitted.')))))
    assert can_retry_source_review(result) and not needs_catalog_retry(result)
    from adaptive_document_agent.agent.brief_reporting_resume import _final_source_retry
    assert not _final_source_retry(result), 'A fresh source rejection must reach bounded page correction'
    result.validation_warnings.append(retain_selection_feedback(result))
    feedback = selection_retry_feedback(result,retained.selection_context(result))
    assert feedback['source_review'] and not feedback['final_approval']
    result.report_plan.title = 'A regenerated provisional report title'
    assert selection_retry_feedback(result,retained.selection_context(result))['preserved_pages']
    changed = result.model_copy(deep=True)
    changed.profile.analysis_focus = 'A different user request'
    assert selection_retry_feedback(changed,retained.selection_context(changed)) is None
    response['decisions'][0]['page']['message'] = 'Unrequested rewrite with unsupported RMB999 billion.'
    mock = gateway([response,accepted])
    retained.select_retained_analysis(mock,result)
    assert len(mock.client.calls)==2  # Source rejection forces rewriting, even if numeric bindings pass.
    assert retained.selected_record(result)['selection']['decisions'][0]['page']['message']=='Reported revenue.'
    assert not can_retry_source_review(result) and needs_catalog_retry(result)


@pytest.mark.parametrize('legacy', [True, False])
@pytest.mark.parametrize('obeys', [True, False])
def test_resume_keeps_structured_priority_verdict_and_requires_corrected_selection(legacy, obeys):
    from adaptive_document_agent.models import ValidationIssue
    from tests.test_retained_source_citations import fixture as source_fixture

    result, _, proposal = source_fixture()
    original = proposal.ordered_insight_ids[0]
    result.insights.append(result.insights[0].model_copy(update={'id': 'required'}))
    draft = proposal.model_dump(exclude_none=True)
    draft['decisions'].append(dict(insight_id='required', decision='omit', reason='Lower priority.'))
    from adaptive_document_agent.agent.retained_page_sources import writer_context
    context = retained.selection_context(result, source_authoring=True)
    _, aliases = writer_context(context)
    review = dict(accepted=False, missing_insight_ids=['required'], prioritized_insight_ids=['required'],
                  page_issues=[], reason='Material omission.')
    rejected = dict(rejected_draft=draft, row_ids=aliases, diagnostic='Material omission.')
    if not legacy:
        rejected['reviewed_priorities'] = ['required']
    result.validation_warnings.extend([
        ValidationIssue(code='retained_selection_coverage', stage='presentation', message=json.dumps(dict(review=review))),
        ValidationIssue(code='retained_page_draft_rejected', stage='presentation', message=json.dumps(rejected)),
    ])
    result.failed_stage = 'presentation_selection'
    result.failure_details = dict(component='RetainedAnalysisSelection')
    result.validation_warnings.append(retain_selection_feedback(result))
    feedback = selection_retry_feedback(result, context)
    assert feedback['reviewed_priorities'] == ['required']
    assert feedback['current_binding_errors'] and not feedback['final_approval']
    corrected = (dict(decisions=[
        dict(insight_id=original, decision='omit', reason='Reviewed lower priority.'),
        dict(insight_id='required', decision='include', reason='Reviewed priority.', page=draft['decisions'][0]['page'])],
        ordered_insight_ids=['required']) if obeys else draft)
    mock = gateway([corrected, dict(accepted=True, reason='Synthetic independent review.')]
                   if obeys else [corrected, corrected])
    if obeys:
        retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result)['selection'] == corrected
        assert len(mock.client.calls) == 2
    else:
        with pytest.raises(ValueError, match='independently chosen priorities'):
            retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result) is None
