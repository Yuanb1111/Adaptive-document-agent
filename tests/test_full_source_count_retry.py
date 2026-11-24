import json

import pytest

from adaptive_document_agent.agent.compact_publication_copy import compact_publication_copy
from adaptive_document_agent.agent.retained_page_revision_parallel import complete_owned_copy_revisions, revise_owned_pages
from adaptive_document_agent.agent.retained_page_sources import AuthoredPageErrors
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_compact_publication_copy import base_gateway, payload


def surplus_response():
    source = payload()
    page = source['source_pages'][0]
    items = []
    for topic in ('delivery', 'returns', 'deposits', 'receipts', 'inventory', 'sales', 'costs', 'orders', 'payables'):
        text = f'The source discusses its {topic} policy.'
        page['text'] += '\n\n' + text
        items.append(dict(scope='the reporting period', description=f'Describes the {topic} policy.',
                          quote=dict(page=page['page'], text=text)))
    return source, dict(message=None, source_context=items)


def stopped_gateway(monkeypatch, responses, second_finish='stop'):
    gateway = base_gateway(responses)
    generate = gateway.client.generate_text

    def respond(*args, **kwargs):
        response = generate(*args, **kwargs)
        response.usage.finish_reason = second_finish if len(gateway.client.calls) == 2 else 'stop'
        return response

    monkeypatch.setattr(gateway.client, 'generate_text', respond)
    return gateway


@pytest.mark.parametrize('rounds', [1, 2])
def test_complete_surplus_source_list_is_only_an_owner_retry(monkeypatch, rounds):
    source, response = surplus_response()
    gateway = stopped_gateway(monkeypatch, [response, response, dict(message=None, source_context=[])])
    runs = []

    def revise(pending, attempts):
        runs.append(set(pending))
        if len(runs) == 2:
            assert any('9 entries; the page limit is 8' in error for error in pending['owned'])
        assert not any(attempts.values())
        return revise_owned_pages(pending, lambda own: compact_publication_copy(
            gateway, 'owned', source, 1800, lambda _: {}) if 'owned' in own else {'sibling': 'Unapproved copy'})

    issues = {'owned': ['Preserve each source qualification'], 'sibling': []}
    if rounds == 1:
        with pytest.raises(AuthoredPageErrors, match='9 entries'):
            complete_owned_copy_revisions(issues, rounds, revise)
        assert runs == [set(issues)] and len(gateway.usage) == 2
    else:
        pages, remaining = complete_owned_copy_revisions(issues, rounds, revise)
        assert remaining == 0 and runs == [set(issues), {'owned'}]
        assert pages['sibling'] == 'Unapproved copy' and not pages['owned'].source_context
        assert len(gateway.usage) == 3


@pytest.mark.parametrize('defect', ['truncated', 'refusal', 'trailing', 'duplicate', 'hidden_field',
                                    'unknown_root', 'unbound_quote', 'unknown_ref', 'mixed_edits',
                                    'unknown_continuation', 'unbound_standalone', 'combined_proof_limit'])
def test_other_defects_are_not_treated_as_an_owner_count_retry(monkeypatch, defect):
    source, original = surplus_response()
    candidate = json.loads(json.dumps(original))
    last = candidate['source_context'][-1]
    if defect == 'hidden_field':
        last['unknown'] = 'unexpected'
    elif defect == 'unknown_root':
        candidate['unknown'] = True
    elif defect == 'unbound_quote':
        last['quote']['text'] = 'Absent from the physical source page.'
    elif defect == 'unknown_ref':
        last['quote'] = {'passage_id': 'p999_s0_e10'}
    elif defect == 'mixed_edits':
        candidate['source_context_additions'] = [last]
    elif defect == 'unknown_continuation':
        last['continuation_quotes'] = [dict(page=999, text='Missing cited physical page.')]
    elif defect == 'unbound_standalone':
        candidate['context_evidence'] = [dict(page=2, text='Unsupported standalone proof.')]
    elif defect == 'combined_proof_limit':
        for index, item in enumerate(candidate['source_context']):
            text = f'An additional source qualification for the item numbered {index}.'
            source['source_pages'][0]['text'] += '\n' + text
            item['continuation_quotes'] = [dict(page=2, text=text)]
    second = json.dumps(candidate)
    if defect == 'duplicate':
        second = second.replace('"scope":', '"scope":"ambiguous", "scope":', 1)
    if defect == 'trailing':
        second += ' trailing content'
    gateway = stopped_gateway(monkeypatch, [original, second], {'refusal': 'content_filter', 'truncated': 'length'}.get(defect, 'stop'))
    with pytest.raises(LLMStructuredOutputError):
        complete_owned_copy_revisions({'owned': ['Preserve material scope']}, 2, lambda issues, attempts:
            compact_publication_copy(gateway, 'owned', source, 1800, lambda _: {}))
    assert len(gateway.usage) == 2
