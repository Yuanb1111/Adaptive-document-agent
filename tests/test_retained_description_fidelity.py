import json

import pytest

from adaptive_document_agent.agent.retained_description_fidelity import review_description_fidelity
from adaptive_document_agent.agent.retained_page_sources import RetainedPage
from adaptive_document_agent.agent.retained_selection_coverage import SelectionCoverageError, review_selection_coverage
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_retained_analysis_v216 import gateway
from tests.test_retained_source_citations import fixture


def page():
    return RetainedPage(title='Service stability', message='The operator assessed the service.',
        source_context=[dict(scope='the review period', description='Reports that stability was insignificant.',
            quote=dict(page=1, text='The operator reviewed the service.'),
            continuation_quotes=[dict(page=2, text='The operator found no significant problem with\nstability.')]),
            dict(scope='management oversight', description='Describes how the operator monitors service.',
                 quote=dict(page=3, text='The service is monitored continuously.'))])


FINDING = dict(description_excerpt='stability was insignificant',
               source_excerpt='no significant problem with stability',
               description_meaning='The operator judges the stability insignificant.',
               source_meaning='The operator judges problems affecting stability insignificant.',
               verdict='contradiction', correction='The judgment concerns a problem with stability.')


def accounts(current, **overrides):
    # Echo a supported literal comparison to exercise the protocol using a mock.
    items = {f'context-{i}': dict(description_excerpt=item.description[:240], source_excerpt=item.quote.text[:240],
                                 description_meaning=item.description[:240], source_meaning=item.quote.text[:240],
                                 verdict='faithful', correction=None)
             for i, item in enumerate(current.source_context)}
    return dict(accounts={**items, **overrides})


def test_no_descriptions_needs_no_model_and_completed_accounts_accept():
    current = page()
    current.source_context[0].description = 'Reports the operator found no significant problem with stability.'
    mock = gateway([accounts(current)])
    assert review_description_fidelity(mock, current.model_copy(update={'source_context': []}), 'owner') is None
    assert mock.client.calls == []
    assert review_description_fidelity(mock, current, 'owner') is None
    assert [u['operation'] for u in mock.usage] == ['RetainedDescriptionFidelity']
    payload = json.loads(mock.client.calls[0][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert set(payload) == {'context-0', 'context-1'}
    for index, item in enumerate(current.source_context):
        assert payload[f'context-{index}'] == dict(scope=item.scope, description=item.description,
            literal_proofs=[q.model_dump(mode='json') for q in item.proof_quotes])


@pytest.mark.parametrize('classification', ['contradiction', 'materially_ambiguous'])
def test_substantiated_discrepancy_is_addressed_to_its_proven_description_and_does_not_change_copy(classification):
    current = page()
    before = current.model_dump()
    response = accounts(current, **{'context-0': {**FINDING, 'verdict': classification}})
    with pytest.raises(SelectionCoverageError) as caught:
        review_description_fidelity(gateway([response]), current, 'owner')
    assert caught.value.priority_ids == []
    issue, = caught.value.page_issues
    assert issue.insight_id == 'owner' and list(issue.description_edits) == ['context-0']
    for key in ('correction', 'source_excerpt', 'description_excerpt'):
        assert FINDING[key] in issue.description_edits['context-0']
    assert current.model_dump() == before


@pytest.mark.parametrize('response', [
    {}, {'accounts': {}}, {'accounts': {'context-0': FINDING}},
    accounts(page(), **{'context-2': FINDING}),
    accounts(page(), **{'context-0': {**FINDING, 'source_excerpt': 'The service is monitored continuously.'}}),
    accounts(page(), **{'context-0': {**FINDING, 'description_excerpt': 'The reader inferred'}}),
    accounts(page(), **{'context-0': {**FINDING, 'description_meaning': '  '}}),
    accounts(page(), **{'context-0': {**FINDING, 'correction': ' '}}),
    accounts(page(), **{'context-0': {**FINDING, 'verdict': 'faithful'}}),
])
def test_malformed_or_unsubstantiated_result_never_supplies_an_authoring_correction(response):
    mock = gateway([response])
    with pytest.raises((ValueError, LLMStructuredOutputError)) as caught:
        review_description_fidelity(mock, page(), 'owner')
    assert not isinstance(caught.value, SelectionCoverageError)
    assert len(mock.client.calls) == 1


@pytest.mark.parametrize('outcome', ['accept', 'reject', 'invalid'])
def test_full_owner_verdict_requires_completed_fidelity_check_before_recording_acceptance(outcome):
    result, context, selection = fixture()
    owner, = selection.ordered_insight_ids
    current = selection.decisions[0].page
    current.source_context = page().source_context
    # Rebind these passages to the existing fixture's physical source page.
    physical_page = result.document.pages[0]
    for item in current.source_context:
        for quote in item.proof_quotes:
            quote.page = physical_page.page_number
            physical_page.text += '\n' + quote.text
    from adaptive_document_agent.agent.retained_analysis import selection_context
    context = {**selection_context(result, source_authoring=True), 'copy_review_ids': [owner]}
    full = dict(accepted=True, reason='The broad review accepted the page.')
    verdict = accounts(current, **({'context-0': FINDING} if outcome == 'reject' else {}))
    mock = gateway([full, {} if outcome == 'invalid' else verdict])
    if outcome == 'invalid':
        with pytest.raises(LLMStructuredOutputError):
            review_selection_coverage(mock, context, selection, result)
        assert not any(w.code == 'retained_selection_coverage' for w in result.validation_warnings)
        return
    if outcome == 'reject':
        with pytest.raises(SelectionCoverageError) as caught:
            review_selection_coverage(mock, context, selection, result)
        assert list(caught.value.page_issues[0].description_edits) == ['context-0']
    else:
        review_selection_coverage(mock, context, selection, result)
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['review']['accepted']
    assert audit['description_fidelity'] == dict(**verdict, accepted=outcome == 'accept', slots_checked=2)
    assert audit['effective_review']['accepted'] == (outcome == 'accept')
