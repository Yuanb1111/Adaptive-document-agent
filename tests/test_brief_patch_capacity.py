"""Overlong model copy gets one bounded source reading, never silent truncation."""
import json

import pytest
from pydantic import ConfigDict, create_model

from adaptive_document_agent.agent.brief_patch_capacity import compact_overlong_patch
from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from adaptive_document_agent.services.llm.usage import LLMUsage


def case():
    schema = create_model('ExecutiveBriefPatch', __config__=ConfigDict(extra='forbid'),
                          item_0=(ExecutiveBriefItem, ...))
    value = dict(item_0=dict(label='A qualified finding', text='Long source discussion. ' * 30,
        evidence=[dict(page=1, text='The estimate remains conditional.')],
        quantity_representations=[], comparison_table=None))
    error = LLMStructuredOutputError('Overlong body', response=LLMResponse(text=json.dumps(value)))
    return schema, value, error


def test_one_source_bound_text_compression_preserves_every_other_field():
    schema, original, error = case()
    calls, record = [], {}
    class Gateway:
        def generate_structured(self, messages, response_model, **kwargs):
            calls.append(messages)
            assert messages[0]['content'] == 'Current literal source and constraints'
            assert kwargs['allow_repair'] is False
            assert set(response_model.model_fields) == {'item_0'}
            return response_model(item_0={'text': 'The estimate remains conditional.'})
    value = compact_overlong_patch(Gateway(), [dict(role='system',
        content='Current literal source and constraints')], schema, error, record)
    assert len(calls) == 1
    assert value.item_0.model_dump(exclude={'text'}) == {
        k: v for k, v in original['item_0'].items() if k != 'text'}
    assert value.item_0.text == 'The estimate remains conditional.'
    assert original['item_0']['text'] == 'Long source discussion. ' * 30
    assert record['raw_response'] == error.response.text


@pytest.mark.parametrize('overlong_fields', [{'label'}, {'label', 'text'}])
def test_copy_compression_edits_only_the_overlong_fields(overlong_fields):
    schema, original, error = case()
    original['item_0']['label'] = 'Qualified source finding ' * 4
    if 'text' not in overlong_fields:
        original['item_0']['text'] = 'The estimate remains conditional.'
    error.response.text = json.dumps(original)
    record = {}
    class Gateway:
        def generate_structured(self, messages, response_model, **kwargs):
            item_schema = response_model.model_fields['item_0'].annotation
            assert set(item_schema.model_fields) == overlong_fields
            replacement = dict(label='A qualified finding', text='The estimate remains conditional.')
            return response_model.model_validate({'item_0': {
                key: replacement[key] for key in overlong_fields}})
    value = compact_overlong_patch(Gateway(), [], schema, error, record)
    assert value.item_0.label == 'A qualified finding'
    assert value.item_0.text == 'The estimate remains conditional.'
    assert value.item_0.model_dump(exclude=overlong_fields) == {
        k: v for k, v in original['item_0'].items() if k not in overlong_fields}
    assert original['item_0']['label'] == 'Qualified source finding ' * 4


@pytest.mark.parametrize('accept_final', [True, False])
def test_label_capacity_failure_can_reach_its_remaining_independent_meaning_correction(accept_final):
    from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
    from tests.test_brief_item_repair import audited, item
    from tests.test_brief_targeted_contract_v147 import Replies
    from tests.test_executive_brief import result_for

    source = 'Revenue was 12. Cash was 4.'
    result = result_for([source])
    original = dict(title='Summary', items=[item('Revenue was 12.', label='Revenue'),
                                          item('Cash was 4.', label='Cash')])
    patch = {**original['items'][0], 'text': 'Reported revenue was 12.',
             'label': 'The source provides a detailed revenue qualification that must survive'}
    error = LLMStructuredOutputError('Overlong label',
        response=LLMResponse(text=json.dumps({'item_0': patch})))
    replies = Replies([original, error, {'item_0': {'label': 'Revenue context'}},
                       {'item_0': {'text': 'The source reports revenue of 12.'}}])
    reviewed = []
    def review(brief):
        reviewed.append(brief.model_dump())
        if not accept_final or brief.items[0].text != 'The source reports revenue of 12.':
            return {0: ['Preserve the source attribution.']}
        return {}
    def run():
        return generate_with_item_repair(replies, [dict(role='system', content='Use only the literal source.')],
            result=result, excerpts={1: source}, topics=[], source_context={}, semantic_validator=review)
    if accept_final:
        final = run()
        assert final.items[0].text == 'The source reports revenue of 12.'
        assert final.items[1].model_dump() == original['items'][1]
        assert audited(result)['post_source_meaning_correction']['status'] == 'accepted'
    else:
        with pytest.raises(ValueError, match='source attribution'):
            run()
    assert len(replies.calls) == 4
    assert replies.calls[2][1] == {'item_0'}
    assert any(row['items'][0]['label'] == 'Revenue context' for row in reviewed)


@pytest.mark.parametrize('mutation', ['truncated', 'wrong_key', 'unknown_field', 'quote_limit'])
def test_copy_correction_does_not_repair_other_schema_or_transport_failures(mutation):
    schema, value, error = case()
    if mutation == 'truncated':
        error.response.usage = LLMUsage(provider='mock', model='mock', finish_reason='length')
    elif mutation == 'wrong_key':
        value['other'] = value.pop('item_0')
    elif mutation == 'unknown_field':
        value['item_0']['unknown'] = 'Untrusted'
    else:
        value['item_0']['evidence'] *= 7
    error.response.text = json.dumps(value)
    class Gateway:
        def generate_structured(self, *args, **kwargs):
            pytest.fail('Non-copy failures must not request a compression')
    with pytest.raises(LLMStructuredOutputError):
        compact_overlong_patch(Gateway(), [], schema, error, {})


def test_a_failed_compression_keeps_original_diagnostics_without_a_second_retry():
    schema, _, error = case()
    calls, record = [], {}
    class Gateway:
        def generate_structured(self, *args, **kwargs):
            calls.append(1)
            raise LLMStructuredOutputError('Still overlong', response=LLMResponse(text='{}'))
    with pytest.raises(LLMStructuredOutputError) as failed:
        compact_overlong_patch(Gateway(), [], schema, error, record)
    assert failed.value is error and len(calls) == 1
    assert record['capacity_correction']['raw_response'] == '{}'
def test_copy_size_feedback_counts_characters_without_accepting_draft_content():
    from adaptive_document_agent.agent.brief_patch_capacity import copy_character_counts
    raw = '{"item_2":{"text":"' + 'A' * 583 + '","label":"范围","evidence":[]}}'
    sizes = copy_character_counts(raw)
    assert sizes['item_2']['text'] == dict(characters=583, target=400, characters_to_remove=183)
    assert sizes['item_2']['label']['characters'] == 2
    assert sizes['item_2']['label']['target'] == 40
    assert 'evidence' not in sizes['item_2']
    assert copy_character_counts('{"item_2":') == {}
