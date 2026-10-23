"""Audit source navigation has an isolated configured selector policy identity."""
import json
from unittest.mock import Mock

import pytest

from adaptive_document_agent.agent.executive_brief import BriefSourcePages
from adaptive_document_agent.agent.report_audit_scope import AuditScopeDraft, AuditScopeReview
from adaptive_document_agent.agent.report_audit_source_discovery import AuditSourceDiscovery
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
from adaptive_document_agent.services.llm import reasoning_policy
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.utils.caching import DiskCache
from tests.test_llm_reasoning_policy import fake_litellm, raw_response


def policy(settings, *, stage='report', operation='AuditSourceDiscovery'):
    return reasoning_policy.request_reasoning_policy(settings, stage=stage, operation=operation,
                                                     model=settings.model)


@pytest.mark.parametrize('setting', ['reduced', 'provider_default'])
def test_navigation_uses_configured_simple_policy_and_optout_without_changing_output_limits(monkeypatch, setting):
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash', simple_task_reasoning=setting)
    provider = LiteLLMProvider(settings)
    complete = Mock(return_value=raw_response('{"ranges":[],"rationale":"No unread counterpart identified."}'))
    monkeypatch.setattr(provider, '_completion', complete)
    gateway = LLMGateway(provider, settings)
    gateway.generate_structured([], AuditSourceDiscovery, stage='report', allow_repair=False, max_tokens=8192)
    assert ('extra_body' in complete.call_args.kwargs) is (setting == 'reduced')
    assert complete.call_args.kwargs['max_tokens'] == 8192
    assert gateway.usage[-1]['reasoning_policy']['intent'] == ('reduce' if setting == 'reduced' else 'preserve')


@pytest.mark.parametrize('provider,endpoint,model', [
    (ProviderName.DEEPSEEK, 'https://unverified.example/v1', 'deepseek-flash'),
    (ProviderName.DEEPSEEK, 'https://api.deepseek.com/custom', 'deepseek-flash'),
    (ProviderName.DEEPSEEK, 'https://api.deepseek.com/v1?different=1', 'deepseek-flash'),
    (ProviderName.DEEPSEEK, None, 'deepseek-future'),
    (ProviderName.OPENAI_COMPATIBLE, 'http://127.0.0.1:8000/v1', 'deepseek-flash'),
    (ProviderName.OPENAI_COMPATIBLE, 'https://api.deepseek.com/v1', 'deepseek-flash'),
])
def test_navigation_cannot_infer_capabilities_on_custom_local_or_unknown_routes(provider, endpoint, model):
    value = policy(LLMSettings(provider=provider, base_url=endpoint, model=model))
    assert value['status'] == 'unsupported' and value['options'] == {}


@pytest.mark.parametrize('capable', [False, True])
def test_navigation_still_requires_positive_loaded_capability_metadata(monkeypatch, capable):
    fake_litellm(monkeypatch, capable=capable)
    settings = LLMSettings(provider=ProviderName.OPENAI, model='capable-model')
    assert policy(settings)['options'] == ({'reasoning_effort': 'low'} if capable else {})
    settings.base_url = 'https://proxy.example/v1'
    assert policy(settings)['options'] == {}


def test_complex_analysis_and_wrong_stage_keep_provider_default():
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash')
    for stage, operation in [('semantic', 'SemanticResolution'), ('planner', 'AnalysisPlan'),
                             ('presentation', 'AuditSourceDiscovery')]:
        value = policy(settings, stage=stage, operation=operation)
        assert value['intent'] == 'preserve' and value['options'] == {}
    assert policy(settings)['options'] == policy(settings, operation='BriefSourcePages')['options']


def test_only_new_navigation_identity_changes_preserving_policy_version_and_audit_caches(monkeypatch, tmp_path):
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash')
    provider = LiteLLMProvider(settings)
    values = {
        'AuditSourceDiscovery': dict(ranges=[], rationale='No additional counterpart identified.'),
        'AuditScopeDraft': dict(bindings=[], unresolved_observation_ids=[], unresolved_reason=''),
        'AuditScopeReview': dict(verdicts=[], unresolved_accepted=True, unresolved_reason='No targets.'),
        'BriefSourcePages': dict(pages=[1]),
    }
    def reply(messages, **kwargs):
        schema = json.loads(messages[0]['content'].split('schema: ', 1)[1])
        return raw_response(json.dumps(values[schema['title']]))
    complete = Mock(side_effect=reply)
    monkeypatch.setattr(provider, '_completion', complete)
    gateway = LLMGateway(provider, settings, cache=DiskCache(tmp_path))
    current = reasoning_policy._SIMPLE_OPERATIONS
    schemas = (AuditSourceDiscovery, AuditScopeDraft, AuditScopeReview, BriefSourcePages)
    monkeypatch.setattr(reasoning_policy, '_SIMPLE_OPERATIONS', current - {('report', 'AuditSourceDiscovery')})
    before = {schema.__name__: policy(settings, operation=schema.__name__) for schema in schemas}
    for schema in schemas:
        gateway.generate_structured([], schema, stage='report', allow_repair=False, max_tokens=8192)
    assert complete.call_count == 4
    monkeypatch.setattr(reasoning_policy, '_SIMPLE_OPERATIONS', current)
    assert reasoning_policy.REASONING_POLICY_VERSION == 'operation-reasoning-v9'
    for schema in schemas:
        assert (before[schema.__name__] != policy(settings, operation=schema.__name__)) is (schema is AuditSourceDiscovery)
        gateway.generate_structured([], schema, stage='report', allow_repair=False, max_tokens=8192)
    assert complete.call_count == 5
    assert complete.call_args.kwargs['extra_body'] == {'thinking': {'type': 'disabled'}}
