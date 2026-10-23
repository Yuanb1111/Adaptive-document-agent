"""A new classifier shares simple-task policy without invalidating other reviews."""
import json
from unittest.mock import Mock

import pytest

from adaptive_document_agent.agent.brief_claim_direction import BriefClaimDirectionReview
from adaptive_document_agent.agent.report_audit_scope import AuditScopeReview
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.services.llm import reasoning_policy
from adaptive_document_agent.utils.caching import DiskCache
from tests.test_llm_reasoning_policy import fake_litellm, raw_response


def policy(settings, *, stage='report', operation='BriefClaimDirectionReview', model=None):
    return reasoning_policy.request_reasoning_policy(settings, stage=stage, operation=operation,
        model=model or settings.model)


@pytest.mark.parametrize('setting', ['reduced', 'provider_default'])
def test_real_classifier_route_respects_configured_simple_reasoning_and_optout(monkeypatch, setting):
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash', simple_task_reasoning=setting)
    provider = LiteLLMProvider(settings)
    complete = Mock(return_value=raw_response('{"items":[]}'))
    monkeypatch.setattr(provider, '_completion', complete)
    llm = LLMGateway(provider, settings)
    llm.generate_structured([], BriefClaimDirectionReview, stage='report', allow_repair=False, max_tokens=8192)
    assert ('extra_body' in complete.call_args.kwargs) is (setting == 'reduced')
    assert complete.call_args.kwargs['max_tokens'] == 8192
    assert llm.usage[-1]['reasoning_policy']['intent'] == ('reduce' if setting == 'reduced' else 'preserve')


@pytest.mark.parametrize('provider,endpoint,model', [
    (ProviderName.DEEPSEEK, 'https://unverified.example/v1', 'deepseek-flash'),
    (ProviderName.DEEPSEEK, 'https://api.deepseek.com/custom', 'deepseek-flash'),
    (ProviderName.DEEPSEEK, 'https://api.deepseek.com/v1?different=1', 'deepseek-flash'),
    (ProviderName.DEEPSEEK, None, 'deepseek-future'),
    (ProviderName.OPENAI_COMPATIBLE, 'http://127.0.0.1:8000/v1', 'deepseek-flash'),
    (ProviderName.OPENAI_COMPATIBLE, 'https://api.deepseek.com/v1', 'deepseek-flash'),
])
def test_classifier_cannot_borrow_capabilities_from_custom_routes_or_unknown_models(provider, endpoint, model):
    value = policy(LLMSettings(provider=provider, base_url=endpoint, model=model))
    assert value['status'] == 'unsupported' and value['options'] == {}


@pytest.mark.parametrize('capable', [False, True])
def test_other_providers_still_require_positive_loaded_capability_metadata(monkeypatch, capable):
    fake_litellm(monkeypatch, capable=capable)
    settings = LLMSettings(provider=ProviderName.OPENAI, model='capable-model')
    assert policy(settings)['options'] == ({'reasoning_effort': 'low'} if capable else {})
    settings.base_url = 'https://proxy.example/v1'
    assert policy(settings)['options'] == {}


def test_complex_analysis_operations_and_other_stages_keep_prior_reasoning():
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash')
    for stage, operation in [('semantic', 'SemanticResolution'), ('planner', 'AnalysisPlan'),
                             ('presentation', 'BriefClaimDirectionReview'), ('insight', 'Insights')]:
        value = policy(settings, stage=stage, operation=operation)
        assert value['intent'] == 'preserve' and value['options'] == {}
    assert policy(settings)['options'] == policy(settings, operation='BriefMeaningReview')['options']


def test_only_new_operation_cache_identity_changes_without_global_policy_bump(monkeypatch, tmp_path):
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash')
    provider = LiteLLMProvider(settings)
    def reply(messages, **kwargs):
        schema = json.loads(messages[0]['content'].split('schema: ', 1)[1])
        value = {'items': []} if schema['title'] == 'BriefClaimDirectionReview' else {
            'verdicts': [], 'unresolved_accepted': True, 'unresolved_reason': 'No unresolved targets.'}
        return raw_response(json.dumps(value))
    complete = Mock(side_effect=reply)
    monkeypatch.setattr(provider, '_completion', complete)
    llm = LLMGateway(provider, settings, cache=DiskCache(tmp_path))
    current = reasoning_policy._SIMPLE_OPERATIONS
    monkeypatch.setattr(reasoning_policy, '_SIMPLE_OPERATIONS',
        current - {('report', 'BriefClaimDirectionReview')})
    old_classifier, old_audit = policy(settings), policy(settings, operation='AuditScopeReview')
    for schema in (BriefClaimDirectionReview, AuditScopeReview):
        llm.generate_structured([], schema, stage='report', allow_repair=False, max_tokens=8192)
    assert complete.call_count == 2
    monkeypatch.setattr(reasoning_policy, '_SIMPLE_OPERATIONS', current)
    assert reasoning_policy.REASONING_POLICY_VERSION == 'operation-reasoning-v9'
    assert old_classifier != policy(settings)
    assert old_audit == policy(settings, operation='AuditScopeReview')
    for schema in (BriefClaimDirectionReview, AuditScopeReview):
        llm.generate_structured([], schema, stage='report', allow_repair=False, max_tokens=8192)
    # The new classifier gets a new request; the unchanged audit operation is a hit.
    assert complete.call_count == 3
    assert complete.call_args.kwargs['extra_body'] == {'thinking': {'type': 'disabled'}}
