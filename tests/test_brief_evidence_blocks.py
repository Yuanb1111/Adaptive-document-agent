import json
import pytest

from adaptive_document_agent.agent.brief_evidence_blocks import evidence_blocks, expand_item
from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from tests.test_executive_brief import gateway, result_for


def test_generated_evidence_schema_has_no_literal_quote_rewrite_route():
    from pydantic import ValidationError
    from adaptive_document_agent.agent.brief_evidence_blocks import ReferencedBriefItem
    from adaptive_document_agent.agent.brief_quantity_references import NativeQuantityBriefItem

    for model in (ReferencedBriefItem, NativeQuantityBriefItem):
        item = {'label': 'Results', 'text': 'Revenue was USD 12 million.',
                'evidence': [{'ref': 'p1_b1'}]}
        assert model.model_validate(item).evidence[0].ref == 'p1_b1'
        item['evidence'] = [{'page': 1, 'text': 'Revenue was USD 12 million.'}]
        with pytest.raises(ValidationError):
            model.model_validate(item)


def test_complete_evidence_capacity_keeps_claim_and_quote_limits_strict():
    from pydantic import ValidationError
    from adaptive_document_agent.agent.brief_evidence_blocks import ReferencedBriefItem
    from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem, ExecutiveBrief, BRIEF_EVIDENCE_LIMIT
    from adaptive_document_agent.services.executive_brief import validate_executive_brief
    texts = [f'In {2020 + i}, output was {100 + i} units.' for i in range(BRIEF_EVIDENCE_LIMIT)]
    result = result_for(texts)
    blocks = evidence_blocks({i: text for i, text in enumerate(texts, 1)})
    value = dict(label='Reported snapshots', text=' '.join(texts),
                 evidence=[dict(ref=ref) for ref in blocks])
    wire = ReferencedBriefItem.model_validate(value)
    item = ExecutiveBriefItem.model_validate(expand_item(wire.model_dump(mode='json'), blocks))
    assert len(item.evidence) == BRIEF_EVIDENCE_LIMIT == 6
    assert not validate_executive_brief(ExecutiveBrief(items=[item]), result)
    item.text = item.text.replace('100 units', '9999 units')
    assert validate_executive_brief(ExecutiveBrief(items=[item]), result)
    value['evidence'].append(value['evidence'][0])
    with pytest.raises(ValidationError):
        ReferencedBriefItem.model_validate(value)
    assert ExecutiveBriefItem.model_json_schema()['properties']['text']['maxLength'] == 550
    assert ExecutiveBrief.model_json_schema()['properties']['items']['maxItems'] == 7


def test_reference_transport_restores_exact_quotes_and_rejects_unknown_ids():
    text = 'Revenue was USD 12 million in 2025.'
    draft = {'title': 'Results', 'items': [{'label': 'Revenue', 'text': text,
                                         'evidence': [{'ref': 'p1_b1'}]}]}
    g, client = gateway([draft])
    brief = ExecutiveBriefWriter(g).generate(result_for([text]))
    assert brief.items[0].evidence[0].model_dump() == {'page': 1, 'text': text}
    assert len(client.editorial_calls) == 1
    assert 'evidence_blocks' in client.editorial_calls[0][1]['content']
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
    assert len(client.editorial_calls) == 2
    assert brief.items[0].text == source
    assert brief.items[0].evidence[0].model_dump() == {'page': 1, 'text': source}
    audit = json.loads(next(i.message for i in result.validation_warnings if i.code == 'executive_brief_repair_audit'))
    assert audit['outcome'] == 'repaired'
    assert audit['reference_response']['items'][0]['evidence'] == [{'ref': 'p1_b1'}]
    assert audit['original']['items'][0]['evidence'] == [{'page': 1, 'text': source}]
