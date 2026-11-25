import json

import pytest

from adaptive_document_agent.agent.retained_description_revision import revise_descriptions
from adaptive_document_agent.agent.retained_description_sentence_repair import quoted_description_sentences
from adaptive_document_agent.agent.retained_page_sources import authored_visible_copy
from tests.test_retained_analysis_v216 import gateway
from tests.test_retained_description_revision import source_page


REASON = 'In context-0, “earlier orders” leaves timing unclear. In context-1, "the exposure" needs attribution.'


@pytest.mark.parametrize('issue,applies', [
    (REASON, True),
    ("Clarify 'earlier orders' and ‘the exposure’ where they occur.", True),
    ('Clarify both points without any literal quoted fragments.', False),
    ('In context-0 “EARLIER ORDERS” needs clarification; in context-1 “the exposure” needs attribution.', False),
    ('In context-0 “the exposure” is wrong; in context-1 “earlier orders” is wrong.', False),
    ('In context-0 “earlier orders” and “Reports” are unclear; in context-1 “the exposure” is unclear.', False),
    ('In context-0 “orders. The group” is unclear; in context-1 “the exposure” needs attribution.', False),
    ('In context-0 “orders” is unclear; in context-1 “the exposure” needs attribution.', False),
])
def test_only_unique_current_sentence_anchors_can_select_the_sentence_editor(issue, applies):
    addressed = {'context-0': {'current_description': 'Reports earlier orders. The group tracked all orders.'},
                 'context-1': {'current_description': 'Describes the exposure.'}}
    targets = quoted_description_sentences(addressed, issue)
    assert bool(targets) is applies
    if applies:
        assert targets['context-0']['current_sentence'] == 'Reports earlier orders.'
        assert targets['context-1']['current_sentence'] == 'Describes the exposure.'
        for slot, target in targets.items():
            assert addressed[slot]['current_description'][target['start']:target['end']] == target['current_sentence']


@pytest.mark.parametrize('mode', ['success', 'unbound', 'unchanged', 'old_sparse'])
def test_targeted_sentence_repair_keeps_frozen_context_and_validates_the_entire_page(mode):
    page, evidence = source_page()
    page.source_context[0].description += ' The group tracked all orders.'
    original = page.model_dump()
    limit = len(authored_visible_copy(page, [])) + 10
    chosen = {'context-0': 'Reports early orders.', 'context-1': 'Cites limited exposure.'}
    response = {slot: dict(concise=text, shorter=text) for slot, text in chosen.items()}
    purposes = {'context-0': 'Describe the timing.', 'context-1': 'Explain the assessment.'}
    if mode == 'unbound':
        response['context-0'] = dict(concise='Reports early orders above 40%.', shorter='Reports early orders above 40%.')
    elif mode == 'unchanged':
        response['context-1'] = dict(concise='Describes the exposure.', shorter='Describes the exposure.')
    elif mode == 'old_sparse':
        response = {slot: dict(concise=[edit], shorter=[edit]) for slot, edit in {
            'context-0': dict(before='earlier', after='early'),
            'context-1': dict(before='Describes the', after='Cites limited')}.items()}
    fallback = {**chosen, 'context-0': chosen['context-0']+' The group tracked all orders.'}
    mock = gateway([response, fallback] if mode in ('unbound', 'unchanged') else [response])
    revised = revise_descriptions(mock, page, purposes, source_pages=evidence, periods=[], limit=limit,
                                  owner_issue=REASON, prefer_quoted_sentences=mode != 'old_sparse')
    assert revised.source_context[0].description == fallback['context-0']
    assert revised.source_context[1].description == fallback['context-1']
    assert revised.source_context[2] == page.source_context[2]
    assert revised.all_context_evidence == page.all_context_evidence and len(authored_visible_copy(revised, [])) <= limit
    assert page.model_dump() == original
    calls = [u['operation'] for u in mock.usage]
    if mode == 'old_sparse':
        assert calls == ['RetainedDescriptionSpanRepair']
    else:
        assert calls == ['RetainedDescriptionSentenceRepair'] + (['RetainedDescriptionRevision'] if mode != 'success' else [])
        data = json.loads(mock.client.calls[0][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        assert set(data['addressed_sentences']) == set(purposes) and data['owner_review_issue'] == REASON
        assert data['addressed_sentences']['context-0']['current_sentence'] == 'Reports earlier orders.'
        assert 'The group tracked all orders.' not in str(data)
        assert data['addressed_sentences']['context-0']['literal_proof'] == [evidence[0]]
