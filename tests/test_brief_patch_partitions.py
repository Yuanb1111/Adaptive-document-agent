"""Concurrent patch partitions still pass through gateway and full brief validation."""
import json
from threading import Barrier

import pytest
from pydantic import ConfigDict, create_model

from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem
from adaptive_document_agent.services.llm.usage import LLMUsage
from tests.brief_review_client import BriefReviewClient
from tests.test_executive_brief import result_for


def test_independent_item_patches_rejoin_before_source_and_meaning_gates():
    source = 'Revenue was 12. Costs were 8. Cash was 4.'
    originals = [dict(label=label, text=f'{label} was 99.', evidence=[dict(ref='p1_b1')])
                 for label in ('Revenue', 'Costs', 'Cash')]
    replacements = ['Revenue was 12.', 'Costs were 8.', 'Cash was 4.']

    class Client(BriefReviewClient):
        supports_concurrent_requests = True

        def patch(self, messages, keys):
            self.calls.append(messages)
            assert len(keys) == 1 and keys[0].startswith('item_')
            context = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert set(context['invalid_items']) == set(keys)
            assert len(context['parallel_sibling_drafts']) == 2
            assert context['evidence_blocks']['p1_b1']['text'] == source
            index = int(keys[0][5:])
            return {keys[0]: dict(label=originals[index]['label'],
                text=replacements[index], evidence=[dict(ref='p1_b1')])}

        def generate_text(self, messages, **kwargs):
            prefix = 'Return only JSON matching this schema: '
            if messages[0]['content'].startswith(prefix):
                schema = json.loads(messages[0]['content'][len(prefix):])
                if schema['title'] == 'ExecutiveBriefPatch':
                    value = self.patch(messages, list(schema['properties']))
                    return LLMResponse(text=json.dumps(value), usage=LLMUsage(provider='mock', model='mock'))
            return super().generate_text(messages, **kwargs)

    client = Client([dict(title='Summary', items=originals)])
    # Use a cloud routing policy with an entirely in-memory client. No provider
    # transport is constructed, and the real gateway still bounds concurrency.
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.OPENAI))
    assert gateway.discovery_workers == 4
    result = result_for([source])
    brief = ExecutiveBriefWriter(gateway).generate(result)
    assert [item.text for item in brief.items] == replacements
    assert not validate_executive_brief(brief, result)
    assert len(client.editorial_calls) == 4
    audit = json.loads(next(w.message for w in result.validation_warnings
                           if w.code == 'executive_brief_repair_audit'))
    assert [row['requested_fields'] for row in audit['patch_partitions']] == [[f'item_{i}'] for i in range(3)]
    assert audit['outcome'] == 'repaired'


def test_partition_failure_waits_for_all_requests_and_never_returns_partial_success():
    from adaptive_document_agent.agent.brief_patch_partitions import generate_patch
    from adaptive_document_agent.services.llm.exceptions import LLMTransportError
    schema = create_model('ExecutiveBriefPatch', __config__=ConfigDict(extra='forbid'),
                          **{f'item_{i}': (str, ...) for i in range(3)})
    barrier, completed, audit = Barrier(3), set(), {}
    class Gateway:
        discovery_workers = 3
        def generate_structured(self, messages, response_model, **kwargs):
            key = next(iter(response_model.model_fields))
            barrier.wait(timeout=5)
            try:
                if key == 'item_1':
                    raise LLMTransportError('offline test failure')
                return response_model.model_validate({key: 'Unverified candidate'})
            finally:
                completed.add(key)
    with pytest.raises(LLMTransportError, match='offline test failure'):
        generate_patch(Gateway(), [dict(role='system', content='Use source.'),
            dict(role='user', content='Untrusted context')], schema, {}, audit)
    assert completed == set(schema.model_fields)
    assert len(audit['patch_partitions']) == 3


def test_schema_failure_retains_complete_successful_siblings_only_as_unverified_candidates():
    from adaptive_document_agent.agent.brief_patch_partitions import generate_patch
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    schema = create_model('ExecutiveBriefPatch', __config__=ConfigDict(extra='forbid'),
                          **{f'item_{i}': (ExecutiveBriefItem, ...) for i in range(3)})
    audit, corrections = {}, []
    class Gateway:
        discovery_workers = 3
        def generate_structured(self, messages, response_model, **kwargs):
            if response_model.__name__ == 'BriefPatchCapacityCorrection':
                corrections.append(1)
                raise LLMStructuredOutputError('Still overlong', response=LLMResponse(text='{}'))
            key = next(iter(response_model.model_fields))
            value = {key: dict(label=key, text=('Overlong copy. ' * 50 if key == 'item_0' else 'A finding.'),
                               evidence=[dict(page=1, text='Literal source passage.')])}
            if key == 'item_0':
                raise LLMStructuredOutputError('Overlong', response=LLMResponse(text=json.dumps(value)))
            return response_model.model_validate(value)
    with pytest.raises(LLMStructuredOutputError) as failed:
        generate_patch(Gateway(), [], schema, {}, audit)
    retained = json.loads(failed.value.response.text)
    assert set(retained) == set(schema.model_fields) and len(corrections) == 1
    assert retained['item_1']['text'] == retained['item_2']['text'] == 'A finding.'
    assert len(retained['item_0']['text']) > 550
    assert all('response' in audit['patch_partitions'][i] for i in (1, 2))
