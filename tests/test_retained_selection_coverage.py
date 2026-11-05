import json
import pytest

from adaptive_document_agent.agent.retained_analysis import RetainedAnalysisSelection
from adaptive_document_agent.agent.retained_selection_coverage import review_selection_coverage
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
    mock = gateway([initial, dict(accepted=False, missing_insight_ids=['required'],
                        prioritized_insight_ids=['required'], reason='This is the material priority.'),
                    corrected, dict(accepted=True, missing_insight_ids=[], reason='The correction preserves priorities.')])
    if obeys:
        retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result)['selection']['ordered_insight_ids'] == ['required']
    else:
        with pytest.raises(ValueError, match='independently chosen priorities'):
            retained.select_retained_analysis(mock, result)
        assert retained.selected_record(result) is None
