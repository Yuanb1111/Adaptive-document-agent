"""Substantive audit operations retain provider reasoning and unrelated caches."""
import json
from unittest.mock import Mock

import pytest

from adaptive_document_agent.agent.brief_claim_direction import BriefClaimDirectionReview
from adaptive_document_agent.agent.executive_brief import BriefSourcePages
from adaptive_document_agent.agent.report_audit_scope import AuditScopeDraft, AuditScopeReview
from adaptive_document_agent.agent.report_audit_source_discovery import AuditSourceDiscovery
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
from adaptive_document_agent.services.llm import reasoning_policy
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.utils.caching import DiskCache
from tests.test_llm_reasoning_policy import fake_litellm, raw_response


AUDIT_SCHEMAS = (AuditScopeDraft, AuditScopeReview)
RESPONSES = {
    'AuditScopeDraft': dict(bindings=[], unresolved_observation_ids=[], unresolved_reason=''),
    'AuditScopeReview': dict(verdicts=[], unresolved_accepted=True, unresolved_reason='No targets.'),
    'AuditSourceDiscovery': dict(ranges=[], rationale='No additional counterpart identified.'),
    'BriefSourcePages': dict(pages=[1]),
    'BriefClaimDirectionReview': dict(items=[]),
}


def policy(settings, schema, *, stage='report'):
    return reasoning_policy.request_reasoning_policy(settings, stage=stage,
        operation=schema.__name__, model=settings.model)


@pytest.mark.parametrize('schema', AUDIT_SCHEMAS)
@pytest.mark.parametrize('setting', ['reduced', 'provider_default'])
def test_each_audit_operation_preserves_reasoning_and_unchanged_token_limit(monkeypatch, schema, setting):
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash', simple_task_reasoning=setting)
    provider = LiteLLMProvider(settings)
    complete = Mock(return_value=raw_response(json.dumps(RESPONSES[schema.__name__])))
    monkeypatch.setattr(provider, '_completion', complete)
    gateway = LLMGateway(provider, settings)
    gateway.generate_structured([], schema, stage='report', allow_repair=False, max_tokens=12000)
    assert complete.call_args.kwargs.get('extra_body') is None
    assert complete.call_args.kwargs['max_tokens'] == 12000
    assert gateway.usage[-1]['reasoning_policy']['intent'] == 'preserve'


@pytest.mark.parametrize('schema', AUDIT_SCHEMAS)
@pytest.mark.parametrize('provider,endpoint,model', [
    (ProviderName.DEEPSEEK, 'https://unverified.example/v1', 'deepseek-flash'),
    (ProviderName.DEEPSEEK, 'https://api.deepseek.com/custom', 'deepseek-flash'),
    (ProviderName.DEEPSEEK, 'https://api.deepseek.com/v1?different=1', 'deepseek-flash'),
    (ProviderName.DEEPSEEK, None, 'deepseek-future'),
    (ProviderName.OPENAI_COMPATIBLE, 'http://127.0.0.1:8000/v1', 'deepseek-flash'),
    (ProviderName.OPENAI_COMPATIBLE, 'https://api.deepseek.com/v1', 'deepseek-flash'),
])
def test_each_audit_operation_preserves_unsupported_custom_local_and_unknown_routes(schema, provider, endpoint, model):
    value = policy(LLMSettings(provider=provider, base_url=endpoint, model=model), schema)
    assert value['status'] == 'provider_default'
    assert value['intent'] == 'preserve'
    assert value['options'] == {}


@pytest.mark.parametrize('schema', AUDIT_SCHEMAS)
@pytest.mark.parametrize('capable', [False, True])
def test_each_audit_operation_preserves_reasoning_regardless_of_capabilities(monkeypatch, schema, capable):
    fake_litellm(monkeypatch, capable=capable)
    settings = LLMSettings(provider=ProviderName.OPENAI, model='capable-model')
    assert policy(settings, schema)['options'] == {}
    assert policy(settings, schema)['intent'] == 'preserve'
    settings.base_url = 'https://proxy.example/v1'
    assert policy(settings, schema)['options'] == {}


@pytest.mark.parametrize('schema', AUDIT_SCHEMAS)
def test_audit_operation_also_preserves_reasoning_in_other_stages(schema):
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash')
    assert policy(settings, schema, stage='presentation')['options'] == {}
    assert policy(settings, schema, stage='presentation')['intent'] == 'preserve'


def test_restored_draft_reasoning_invalidates_only_its_old_reduced_cache(monkeypatch, tmp_path):
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash')
    provider = LiteLLMProvider(settings)
    def reply(messages, **kwargs):
        schema = json.loads(messages[0]['content'].split('schema: ', 1)[1])
        return raw_response(json.dumps(RESPONSES[schema['title']]))
    complete = Mock(side_effect=reply)
    monkeypatch.setattr(provider, '_completion', complete)
    gateway = LLMGateway(provider, settings, cache=DiskCache(tmp_path))
    current = reasoning_policy._SIMPLE_OPERATIONS
    assert ('report', 'AuditScopeDraft') not in current
    assert ('report', 'AuditScopeReview') not in current
    schemas = (*AUDIT_SCHEMAS, AuditSourceDiscovery, BriefSourcePages, BriefClaimDirectionReview)
    monkeypatch.setattr(reasoning_policy, '_SIMPLE_OPERATIONS',
                        current | {('report', 'AuditScopeDraft')})
    before = {schema.__name__: policy(settings, schema) for schema in schemas}
    assert before['AuditScopeDraft']['intent'] == 'reduce'
    assert before['AuditScopeReview']['intent'] == 'preserve'
    assert before['AuditSourceDiscovery']['intent'] == 'reduce'
    for schema in schemas:
        gateway.generate_structured([], schema, stage='report', allow_repair=False, max_tokens=12000)
    assert complete.call_count == 5
    monkeypatch.setattr(reasoning_policy, '_SIMPLE_OPERATIONS', current)
    assert reasoning_policy.REASONING_POLICY_VERSION == 'operation-reasoning-v9'
    for schema in schemas:
        assert (before[schema.__name__] != policy(settings, schema)) is (schema is AuditScopeDraft)
        gateway.generate_structured([], schema, stage='report', allow_repair=False, max_tokens=12000)
    assert complete.call_count == 6
    assert policy(settings, AuditScopeDraft)['intent'] == 'preserve'
    assert complete.call_args.kwargs.get('extra_body') is None
    gateway.generate_structured([], AuditScopeDraft, stage='report', allow_repair=False, max_tokens=12000)
    assert complete.call_count == 6
