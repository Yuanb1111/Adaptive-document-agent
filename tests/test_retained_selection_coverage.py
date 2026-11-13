import json
import pytest

from adaptive_document_agent.agent.retained_analysis import RetainedAnalysisSelection
from adaptive_document_agent.agent.retained_selection_coverage import review_selection_coverage
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_retained_analysis_v216 import _linked_result, gateway


@pytest.mark.parametrize('accepted,missing,raises', [
    (True, [], False), (False, ['omitted'], True),
    (True, ['omitted'], True), (False, [], True),
    (False, ['included'], True), (False, ['unknown'], True),
    (False, ['omitted', 'omitted'], True),
])
def test_early_coverage_verdict_is_bound_and_never_approves_final_presentation(accepted, missing, raises):
    result = _linked_result()
    context = dict(findings=[dict(insight=dict(id=k), selectable=True)
                            for k in ('included', 'omitted')])
    selection = RetainedAnalysisSelection(decisions=[], ordered_insight_ids=['included'])
    mock = gateway([dict(accepted=accepted, missing_insight_ids=missing,
                         reason='A distinct material trend is missing.' if missing else 'Coverage is sufficient.')])
    if raises:
        with pytest.raises(ValueError):
            review_selection_coverage(mock, context, selection, result)
    else:
        review_selection_coverage(mock, context, selection, result)
    records = [json.loads(w.message) for w in result.validation_warnings if w.code=='retained_selection_coverage']
    assert all(not r['final_presentation_approval'] for r in records)
    assert not any(w.code=='presentation_retained_analysis_review' for w in result.validation_warnings)


@pytest.mark.parametrize('accepted,page_ids,valid', [
    (False, ['included'], True), (True, ['included'], False),
    (False, ['omitted'], False), (False, ['unknown'], False),
    (False, ['included', 'included'], False),
])
def test_copy_feedback_must_reference_an_included_page(accepted, page_ids, valid):
    result = _linked_result()
    context = dict(findings=[dict(insight=dict(id=k), selectable=True) for k in ('included','omitted')])
    selection = RetainedAnalysisSelection(decisions=[], ordered_insight_ids=['included'])
    mock = gateway([dict(accepted=accepted, missing_insight_ids=[], reason='Copy is incomplete.',
                        page_issues=[dict(insight_id=k, reason='The latest source composition is missing.')
                                     for k in page_ids])])
    with pytest.raises(ValueError, match='Page corrections' if valid else 'exact omitted'):
        review_selection_coverage(mock, context, selection, result)


@pytest.mark.parametrize('second_finish', ['stop', 'length'])
def test_length_recovery_reuses_complete_review_packet_and_preserves_draft(monkeypatch, second_finish):
    from adaptive_document_agent.agent import retained_analysis as retained
    from adaptive_document_agent.agent.retained_selection_feedback import retain_selection_feedback
    from tests.test_retained_source_citations import fixture

    result, _, proposal = fixture()
    accepted = dict(accepted=True, reason='Synthetic complete coverage verdict.')
    mock = gateway([proposal.model_dump(), accepted, accepted])
    generate_text = mock.client.generate_text
    caps = []

    def with_finish_reason(messages, **kwargs):
        response = generate_text(messages, **kwargs)
        if 'RetainedSelectionCoverage' in messages[0]['content']:
            caps.append(kwargs['max_tokens'])
            response.usage.finish_reason = 'length' if len(caps) == 1 else second_finish
        return response

    monkeypatch.setattr(mock.client, 'generate_text', with_finish_reason)
    if second_finish == 'length':
        with pytest.raises(LLMStructuredOutputError, match='truncated'):
            retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result) is None
        assert not any(w.code == 'retained_selection_coverage' for w in result.validation_warnings)
        result.failed_stage = 'presentation_selection'
        result.failure_details = dict(component='RetainedAnalysisSelection')
        result.validation_warnings.append(retain_selection_feedback(result))
        resume = gateway([accepted])
        retained.select_retained_analysis(resume, result)
        assert len(resume.client.calls) == 1  # Recheck the retained draft without rewriting it.
    else:
        retained.select_retained_analysis(mock, result)
    assert caps == [12000, 20000]
    assert mock.client.calls[1] == mock.client.calls[2]
    assert [u['status'] for u in mock.usage if u['operation'] == 'RetainedSelectionCoverage'] == [
        'truncated', 'truncated' if second_finish == 'length' else 'success']
    assert retained.selected_record(result)['selection'] == proposal.model_dump(exclude_none=True)
    assert not any(w.code == 'presentation_retained_analysis_review' for w in result.validation_warnings)


def test_copy_and_coverage_errors_reach_the_same_bounded_correction(monkeypatch):
    from adaptive_document_agent.agent import retained_analysis as retained, retained_page_sources as sources
    from tests.test_retained_analysis_v216 import selection as base_selection
    result = _linked_result()
    result.document.pages[0].text_blocks = [dict(lines=[dict(text='Original source')])]
    draft = base_selection(result)
    iid = draft['ordered_insight_ids'][0]
    draft['decisions'][0]['page'] = dict(title='Revenue', message='Source-backed levels.', companion_ids=[])
    calls = []
    def check(*args):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError('A comparison endpoint is missing')
    monkeypatch.setattr(sources, 'validate_authored_pages', check)
    mock = gateway([draft, dict(accepted=False, missing_insight_ids=[], reason='Source qualification omitted.',
                        page_issues=[dict(insight_id=iid, reason='Retain the unaudited qualifier.')]),
                    draft, dict(accepted=True, missing_insight_ids=[], reason='Synthetic acceptance.')])
    retained.select_retained_analysis(mock, result)
    record = json.loads(next(w.message for w in result.validation_warnings if w.code=='retained_page_draft_rejected'))
    assert 'endpoint is missing' in record['diagnostic'] and 'unaudited qualifier' in record['diagnostic']
    assert len(mock.client.calls) == 4


@pytest.mark.parametrize('outcome', ['accepted', 'unchanged', 'wrong_id', 'material_omission'])
def test_final_copy_revision_preserves_selection_and_requires_fresh_validation(outcome):
    from copy import deepcopy
    from adaptive_document_agent.agent import retained_analysis as retained
    from adaptive_document_agent.utils.record_encoding import decode_records
    from tests.test_retained_source_citations import fixture

    result, _, proposal = fixture()
    iid = proposal.ordered_insight_ids[0]
    result.insights.extend(result.insights[0].model_copy(update={'id': other})
                           for other in ('other-page', 'omitted'))
    good = proposal.model_dump(exclude_none=True)
    good['decisions'].extend([
        dict(insight_id='other-page', decision='include', reason='Other finding.',
             page=dict(title='Revenue context', message='Revenue is reported.', companion_ids=[], context_evidence=[])),
        dict(insight_id='omitted', decision='omit', reason='Lower priority.'),
    ])
    good['ordered_insight_ids'].append('other-page')
    bad = deepcopy(good)
    bad['decisions'][0]['page']['message'] = 'Revenue was RMB 987,654,321.'
    issue = dict(accepted=False, reason='Copy needs source correction.',
                 page_issues=[dict(insight_id=iid, reason='Remove the unbound amount.')])
    accepted = dict(accepted=True, reason='Synthetic complete coverage verdict.')
    responses = [bad, issue]
    if outcome == 'material_omission':
        responses[-1] = dict(issue, missing_insight_ids=['omitted'], prioritized_insight_ids=[iid, 'omitted'])
        # Copy transport cannot substitute its old page set for the reviewer's fixed priorities.
        responses.append(dict(reasons={iid:'Still selected.'},pages={iid:bad['decisions'][0]['page']}))
    else:
        page = (bad if outcome == 'unchanged' else good)['decisions'][0]['page']
        responses.append(dict(pages={'other-page' if outcome == 'wrong_id' else iid: page}))
        if outcome != 'wrong_id':
            responses.append(accepted)
        if outcome == 'unchanged':
            responses.extend([dict(pages={iid: page}), accepted])
    mock = gateway(responses)

    if outcome == 'accepted':
        retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result)['selection'] == good
        assert mock.usage[-1]['operation'] == 'RetainedSelectionCoverage'
    else:
        error = {'unchanged': 'outside its bound evidence', 'wrong_id': 'exactly the flagged insight IDs',
                 'material_omission': 'invalid after one repair'}[outcome]
        from adaptive_document_agent.services.llm.exceptions import LLMResponseError
        with pytest.raises((ValueError,LLMResponseError), match=error):
            retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result) is None

    revision_calls = [i for i, usage in enumerate(mock.usage) if usage['operation'] == 'RetainedPageRevisions']
    assert revision_calls == {'material_omission': [], 'unchanged': [2, 4]}.get(outcome, [2])
    if revision_calls:
        wire = mock.client.calls[revision_calls[0]][-1]['content']
        payload = decode_records(json.loads(wire.split('\n', 1)[1].rsplit('\n', 1)[0]))
        assert set(payload['pages_to_correct']) == {iid}
        assert payload['pages_to_correct'][iid]['source_page_numbers'] == [234]
        errors = payload['pages_to_correct'][iid]['errors']
        assert any('outside its bound evidence' in error for error in errors)
        assert 'Remove the unbound amount.' in errors


@pytest.mark.parametrize('resolved', [True, False])
def test_valid_checkpoint_gets_copy_revision_without_regenerating_selection(resolved):
    from adaptive_document_agent.agent import retained_analysis as retained
    from adaptive_document_agent.agent.retained_page_sources import writer_context
    from adaptive_document_agent.agent.retained_selection_feedback import retain_selection_feedback
    from adaptive_document_agent.models import ValidationIssue
    from tests.test_retained_source_citations import fixture

    result, context, proposal = fixture()
    _, aliases = writer_context(context)
    iid = proposal.ordered_insight_ids[0]
    draft = proposal.model_dump(exclude_none=True)
    result.failed_stage = 'presentation_selection'
    result.failure_details = dict(component='RetainedAnalysisSelection')
    result.validation_warnings.append(ValidationIssue(code='retained_page_draft_rejected', stage='presentation',
        message=json.dumps(dict(rejected_draft=draft, row_ids=aliases, diagnostic='Copy requires clarification.'))))
    result.validation_warnings.append(retain_selection_feedback(result))
    page = dict(draft['decisions'][0]['page'], message='The company reported revenue.')
    rejected = dict(accepted=False, reason='A page needs clarification.',
                    page_issues=[dict(insight_id=iid, reason='Clarify the reporting attribution.')])
    revision = dict(pages={iid: page})
    if resolved:
        mock = gateway([rejected, revision, dict(accepted=True, reason='The correction retains source meaning.')])
        retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result)['selection']['decisions'][0]['page'] == page
        count = 1
    else:
        mock = gateway([rejected, revision, rejected, revision, rejected])
        with pytest.raises(ValueError, match='Clarify the reporting attribution'):
            retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result) is None
        count = 2
    assert [u['operation'] for u in mock.usage] == ['RetainedSelectionCoverage'] + [
        'RetainedPageRevisions', 'RetainedSelectionCoverage'] * count


def test_copy_review_cannot_reopen_selection_but_retains_remaining_copy_error():
    from copy import deepcopy
    from adaptive_document_agent.agent import retained_analysis as retained
    from adaptive_document_agent.agent.retained_analysis_review import review_context, review_complete
    from tests.test_retained_source_citations import fixture

    result, _, proposal = fixture()
    iid = proposal.ordered_insight_ids[0]
    result.insights.extend(result.insights[0].model_copy(update={'id': key}) for key in ('unchanged', 'omitted'))
    draft = proposal.model_dump(exclude_none=True)
    draft['ordered_insight_ids'].append('unchanged')
    draft['decisions'].extend([
        dict(insight_id='unchanged', decision='include', reason='Included.',
             page=dict(title='Revenue context', message='Revenue is reported.', companion_ids=[], context_evidence=[])),
        dict(insight_id='omitted', decision='omit', reason='Lower priority.'),
    ])
    corrected = dict(draft['decisions'][0]['page'], message='The company reported revenue.')
    copy_issue = dict(insight_id=iid, reason='Clarify the attributed claim.')
    needs_copy = dict(accepted=False, reason='The selection is sound; revise this page.', page_issues=[copy_issue])
    conflicting = dict(accepted=False, reason='Replace a topic and correct two pages.',
        missing_insight_ids=['omitted'], prioritized_insight_ids=[iid, 'omitted'],
        page_issues=[copy_issue, dict(insight_id='unchanged', reason='Review an untouched page.')])
    accepted = dict(accepted=True, reason='The revised page is source-faithful.')
    mock = gateway([draft, needs_copy,
                    dict(pages={iid: draft['decisions'][0]['page']}), conflicting,
                    dict(pages={iid: corrected}), accepted])

    retained.select_retained_analysis(mock, result)
    selection = retained.selected_record(result)['selection']
    assert selection['ordered_insight_ids'] == draft['ordered_insight_ids']
    assert selection['decisions'][0]['page'] == corrected
    assert selection['decisions'][1:] == draft['decisions'][1:]
    result.presentation_plan = retained.compile_retained_analysis(result)
    deferred, = review_context(result)['deferred_copy_review_objections']
    assert deferred['missing_insight_ids'] == ['omitted']
    assert deferred['page_issues'] == conflicting['page_issues'][1:]
    assert not review_complete(result)


@pytest.mark.parametrize('priorities,valid', [
    (['omitted'], True), (['included', 'omitted'], False),
    ([], False), (['unknown'], False), (['omitted', 'omitted'], False),
])
def test_priority_revision_must_be_feasible_and_bound_to_missing_findings(priorities, valid):
    result = _linked_result()
    context = dict(selection_capacity=1, findings=[dict(insight=dict(id=k), selectable=True)
                                                  for k in ('included', 'omitted')])
    proposal = RetainedAnalysisSelection(decisions=[], ordered_insight_ids=['included'])
    mock = gateway([dict(accepted=False, missing_insight_ids=['omitted'],
                        prioritized_insight_ids=priorities, reason='The omitted finding has higher priority.')])
    with pytest.raises(ValueError, match='Complete feasible' if valid else 'exact omitted') as failure:
        review_selection_coverage(mock, context, proposal, result)
    if valid:
        assert failure.value.priority_ids == ['omitted']


@pytest.mark.parametrize('obeys', [True, False])
def test_writer_cannot_drop_independently_reviewed_priorities(obeys):
    from copy import deepcopy
    from adaptive_document_agent.agent import retained_analysis as retained
    result = _linked_result()
    result.document.pages[0].text_blocks = [dict(lines=[dict(text='Original source')])]
    original = result.insights[0].id
    result.insights.append(result.insights[0].model_copy(update={'id': 'required'}))
    page = dict(title='Revenue', message='Source-backed levels.', companion_ids=[])
    initial = dict(decisions=[dict(insight_id=original, decision='include', reason='Initial priority.', page=page),
                              dict(insight_id='required', decision='omit', reason='Initial omission.')],
                   ordered_insight_ids=[original])
    corrected = deepcopy(initial)
    if obeys:
        corrected['decisions'] = [dict(insight_id=original, decision='omit', reason='Reviewed lower priority.'),
                                 dict(insight_id='required', decision='include', reason='Reviewed priority.', page=page)]
        corrected['ordered_insight_ids'] = ['required']
    patch=dict(reasons={original:'Reviewed lower priority.','required':'Reviewed priority.'},
               pages={'required':page} if obeys else {original:page})
    mock = gateway([initial, dict(accepted=False, missing_insight_ids=['required'],
                        prioritized_insight_ids=['required'], reason='This is the material priority.'),
                    patch, dict(accepted=True, missing_insight_ids=[], reason='The correction preserves priorities.')])
    if obeys:
        retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result)['selection']['ordered_insight_ids'] == ['required']
    else:
        from adaptive_document_agent.services.llm.exceptions import LLMResponseError
        with pytest.raises(LLMResponseError, match='invalid after one repair'):
            retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result) is None


@pytest.mark.parametrize('settles', [True, False])
def test_late_priority_change_gets_one_independent_correction_after_proposal_retry(settles):
    from copy import deepcopy
    from adaptive_document_agent.agent import retained_analysis as retained
    from tests.test_retained_source_citations import fixture

    result, _, proposal = fixture()
    original = proposal.ordered_insight_ids[0]
    result.insights.append(result.insights[0].model_copy(update={'id': 'required'}))
    initial = proposal.model_dump(exclude_none=True)
    initial['decisions'].append(dict(insight_id='required', decision='omit', reason='Lower priority.'))
    # A non-localizable proposal failure still permits a complete correction.
    # Addressed copy issues now repair locally and defer out-of-scope ranking
    # objections to the mandatory final review instead of reopening priorities.
    proposal_issue = dict(accepted=False, reason='The complete selection needs correction.')
    corrected = deepcopy(initial)
    corrected['decisions'][0]['page']['message'] = 'The company reported revenue.'
    replacement = dict(decisions=[
        dict(insight_id=original, decision='omit', reason='Reviewed lower priority.'),
        dict(insight_id='required', decision='include', reason='Independent priority.',
             page=corrected['decisions'][0]['page'])], ordered_insight_ids=['required'])
    priority_issue = dict(accepted=False, missing_insight_ids=['required'],
                         prioritized_insight_ids=['required'], reason='Material omitted trajectory.')
    final_review = (dict(accepted=True, reason='Source-backed corrected selection.') if settles else
                    dict(accepted=False, missing_insight_ids=[original],
                         prioritized_insight_ids=[original], reason='Another priority reversal.'))
    patch=dict(reasons={original:'Reviewed lower priority.','required':'Independent priority.'},
               pages={'required':corrected['decisions'][0]['page']})
    mock = gateway([initial, proposal_issue, corrected, priority_issue, patch, final_review])
    if settles:
        retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result)['selection'] == replacement
        assert not any(w.code == 'presentation_retained_analysis_review' for w in result.validation_warnings)
    else:
        with pytest.raises(ValueError, match='omits material findings'):
            retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result) is None
    assert [u['operation'] for u in mock.usage] == [
        'SourceAuthoredAnalysisSelection', 'RetainedSelectionCoverage'] * 2 + [
        'PriorityPagePatch','RetainedSelectionCoverage']
