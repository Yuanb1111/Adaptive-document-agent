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
            return response_model(item_0='The estimate remains conditional.')
    value = compact_overlong_patch(Gateway(), [dict(role='system',
        content='Current literal source and constraints')], schema, error, record)
    assert len(calls) == 1
    assert value.item_0.model_dump(exclude={'text'}) == {
        k: v for k, v in original['item_0'].items() if k != 'text'}
    assert value.item_0.text == 'The estimate remains conditional.'
    assert original['item_0']['text'] == 'Long source discussion. ' * 30
    assert record['raw_response'] == error.response.text


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
