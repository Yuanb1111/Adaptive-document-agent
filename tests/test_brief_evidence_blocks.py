import json
import pytest

from adaptive_document_agent.agent.brief_evidence_blocks import evidence_blocks, expand_item
from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from tests.test_executive_brief import gateway, result_for


def test_reference_transport_restores_exact_quotes_and_rejects_unknown_ids():
    text = 'Revenue was USD 12 million in 2025.'
    draft = {'title': 'Results', 'items': [{'label': 'Revenue', 'text': text,
                                         'evidence': [{'ref': 'p1_b1'}]}]}
    g, client = gateway([draft])
    brief = ExecutiveBriefWriter(g).generate(result_for([text]))
    assert brief.items[0].evidence[0].model_dump() == {'page': 1, 'text': text}
    assert len(client.calls) == 1
    assert 'evidence_blocks' in client.calls[0][1]['content']
    draft['items'][0]['evidence'][0]['ref'] = 'not-supplied'
    g, _ = gateway([draft, {'item_0': draft['items'][0]}])
    with pytest.raises(ValueError):
        ExecutiveBriefWriter(g).generate(result_for([text]))


def test_partition_keeps_full_source_in_order_including_conditions_and_headers():
    text = '2023 2024\nUSD thousands per unit\n\n' + ('The full source condition remains unchanged. ' * 110)
    blocks = evidence_blocks({9: text})
    assert ' '.join(' '.join(v['text'].split()) for v in blocks.values()) == ' '.join(text.split())
    assert all(v['page'] == 9 and len(v['text']) <= 1800 for v in blocks.values())
    for key, value in blocks.items():
        assert value['text'] in text
        assert expand_item({'evidence': [{'ref': key}]}, blocks)['evidence'] == [value]


def test_reference_patch_restores_exact_evidence_and_uses_one_bounded_repair():
    source = 'Revenue was USD 12 million in 2025.'
    draft = {'title': 'Results', 'items': [{'label': 'Revenue',
        'text': 'Revenue was USD 99 million in 2025.', 'evidence': [{'ref': 'p1_b1'}]}]}
    corrected = {**draft['items'][0], 'text': source}
    g, client = gateway([draft, {'item_0': corrected}])
    result = result_for([source])
    brief = ExecutiveBriefWriter(g).generate(result)
    assert len(client.calls) == 2
    assert brief.items[0].text == source
    assert brief.items[0].evidence[0].model_dump() == {'page': 1, 'text': source}
    audit = json.loads(next(i.message for i in result.validation_warnings if i.code == 'executive_brief_repair_audit'))
    assert audit['outcome'] == 'repaired'
    assert audit['reference_response']['items'][0]['evidence'] == [{'ref': 'p1_b1'}]
    assert audit['original']['items'][0]['evidence'] == [{'page': 1, 'text': source}]
