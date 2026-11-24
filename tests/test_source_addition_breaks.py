"""Only the writer chooses an exact source-addition break; review still judges the result."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.source_integration_copy import shorten_additions
from adaptive_document_agent.agent.source_integration_review import (
    SourceIntegrationDraft, resolved_source_check_ids, review_supplementary_sources,
)
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_budget_output_v145 import gateway, response
from tests.test_source_completion_capacity_v173 import _audit, _outputs, wire_response
from tests.test_source_integration_v166 import fixture


def complete_sentences():
    first = ('Under the agreement the manufacturer keeps separate records for goods supplied under '
             'each contract and must make these available to the buyer on reasonable notice, subject '
             'to a confidentiality undertaking that applies only where confidential information '
             'would otherwise have to be disclosed.')
    second = ('Under a separate provision the buyer may cancel an unperformed order in writing '
              'only after the manufacturer fails to remedy the specified breach within the period '
              'set out in the order, while completed deliveries remain subject to the agreed payment '
              'terms and their associated exceptions.')
    assert 550 < len(first + ' ' + second)
    return first, second


def copy_request(raw, value, original_count=3):
    llm, client = gateway([response(json.dumps({'addition_0_text': value}))])
    detail = dict(loc=['additions', 0, 'text'], ctx=dict(max_length=550))
    entry = {}
    repaired = shorten_additions(llm, [], SourceIntegrationDraft, (raw, [detail]), entry, original_count)
    return repaired, entry, client


def test_model_selected_break_copies_exact_words_and_remaps_only_owners():
    first, second = complete_sentences()
    draft, _ = _outputs('The manufacturer must retain the contractual records.')
    raw = draft.model_dump(mode='json')
    raw['additions'][0]['text'] = first + ' ' + second
    sibling = deepcopy(raw['additions'][0])
    sibling.update(label='Unaffected finding', text='Repairs are billed under a separate service agreement.')
    raw['additions'].append(sibling)
    raw['decisions'][0]['brief_item_indexes'] = [3]
    raw['decisions'] += [{**deepcopy(raw['decisions'][0]), 'section_id': 'shared'},
                         {**deepcopy(raw['decisions'][0]), 'section_id': 'separate', 'brief_item_indexes': [4]}]
    value = dict(split_at='break_1', labels=['Records', 'Cancellation'])
    repaired, entry, client = copy_request(raw, value)

    assert [i.text for i in repaired.additions] == [first + ' ', sibling['text'], second]
    assert repaired.additions[0].text + repaired.additions[2].text == first + ' ' + second
    assert repaired.additions[1].model_dump(mode='json') == sibling
    assert [i.label for i in (repaired.additions[0], repaired.additions[2])] == value['labels']
    assert repaired.additions[0].evidence == repaired.additions[2].evidence == draft.additions[0].evidence
    assert [d.brief_item_indexes for d in repaired.decisions] == [[3, 5], [3, 5], [4]]
    assert entry['exact_copy_breaks'] == {'addition_0_text': value}
    assert len(client.requests) == 1 and 'review' not in entry


@pytest.mark.parametrize('choice', [
    dict(split_at='break_2', labels=['Records', 'Orders']),
    dict(split_at='break_1', labels=['Records']),
    dict(split_at='break_1', labels=['Records', 'Orders', 'Other']),
    dict(split_at='break_1', labels=['Records', 'Orders'], text='Unrelated replacement.'),
])
def test_malformed_break_cannot_change_text_or_bindings(choice):
    raw = _outputs('The written agreement governs cancellation.')[0].model_dump(mode='json')
    raw['additions'][0]['text'] = ' '.join(complete_sentences())
    original = deepcopy(raw)
    with pytest.raises(LLMStructuredOutputError):
        copy_request(raw, choice, original_count=1)
    assert raw == original


@pytest.mark.parametrize('constraint', ['no_capacity', 'unsplittable', 'table', 'quantity', 'not_owner'])
def test_exact_selector_requires_capacity_ownership_and_suitable_body(constraint):
    raw = _outputs('The written agreement governs cancellation.')[0].model_dump(mode='json')
    item = raw['additions'][0]
    item['text'] = ' '.join(complete_sentences())
    if constraint == 'unsplittable':
        item['text'] = 'X' * 551
    if constraint == 'table':
        item['comparison_table'] = dict(headers=['Terms', 'Status'], rows=[['Agreement', 'Active']])
    if constraint == 'quantity':
        item['quantity_representations'] = [
            dict(quantity_text='12 kg', source_value='-12', representation='absolute_magnitude')]
    count = 6 if constraint == 'no_capacity' else 1
    raw['decisions'][0]['brief_item_indexes'] = [0] if constraint == 'not_owner' else [count]
    with pytest.raises(LLMStructuredOutputError):
        copy_request(raw, dict(split_at='break_1', labels=['Records', 'Orders']), count)


@pytest.mark.parametrize('accepted', [True, False])
def test_copied_sentences_still_require_fresh_review_of_the_whole_source(accepted):
    result, constraint = fixture()
    draft, review = _outputs(constraint)
    raw = draft.model_dump(mode='json')
    first, second = complete_sentences()
    body = first + ' ' + second
    raw['additions'][0]['text'] = body
    page = next(p for p in result.document.pages if p.page_number == 12)
    page.text = body + ' ' + page.text
    original = result.executive_brief.model_copy(deep=True)
    review.verdicts[0].accepted = accepted
    patch = response(json.dumps({'addition_0_text': dict(split_at='break_1', labels=['Records', 'Orders'])}))
    outputs = [wire_response(raw), patch, response(review)]
    if not accepted:
        outputs.extend([wire_response(draft), response(review)])
    llm, client = gateway(outputs)
    merged = review_supplementary_sources(llm, result, original)
    attempt = next(a for a in _audit(result)[1]['attempts'] if 'exact_copy_breaks' in a)
    assert attempt['review']['verdicts'][0]['accepted'] is accepted
    assert [u['operation'] for u in llm.usage][:3] == [
        'SourceIntegrationDraft', 'SourceAdditionCopy', 'SourceIntegrationReview']
    assert any(body in m['content'] for m in client.requests[2][0])
    if accepted:
        assert [i.text for i in merged.items[len(original.items):]] == [first + ' ', second]
        assert resolved_source_check_ids(result, merged) == {'contracts'}
    else:
        assert merged == original and not resolved_source_check_ids(result, merged)
