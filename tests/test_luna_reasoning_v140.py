"""Offline regression for documented Luna effort support on its exact route."""

import builtins
import json
import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from adaptive_document_agent.agent.company_introduction import IntroductionPages
from adaptive_document_agent.agent.topic_coverage_review import TopicCoverageReview
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.services.llm.reasoning_policy import request_reasoning_policy
from adaptive_document_agent.utils.caching import DiskCache


def _settings(**changes):
    return LLMSettings(provider=ProviderName.OPENAI, model='gpt-6-luna', **changes)


def _policy(settings=None, *, model='gpt-6-luna', stage='presentation', operation='TopicCoverageReview'):
    return request_reasoning_policy(settings or _settings(), model=model, stage=stage, operation=operation)


def _sdk(monkeypatch, catalog=None, text='{"pages":[2]}', finish_reason='stop'):
    module = ModuleType('litellm')
    module.model_cost = catalog
    module.completion = Mock(return_value=SimpleNamespace(
        model='gpt-6-luna', choices=[SimpleNamespace(
            message=SimpleNamespace(content=text), finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10)))
    module.get_model_info = Mock(side_effect=AssertionError('must not fetch model metadata'))
    module.get_supported_openai_params = Mock(side_effect=AssertionError('must not query SDK capabilities'))
    module.supports_reasoning = Mock(side_effect=AssertionError('must not query SDK capabilities'))
    monkeypatch.setitem(sys.modules, 'litellm', module)
    return module


@pytest.mark.parametrize('catalog', [None, {}, {'gpt-6-luna': {}},
    {'openai/gpt-6-luna': {'litellm_provider': 'openai', 'supports_reasoning': True}},
    {'openai/gpt-6-luna': {'litellm_provider': 'openai', 'supports_reasoning': False,
        'supports_low_reasoning_effort': False, 'reasoning_effort_levels': ['high'],
        'default_reasoning_effort': 'unknown', 'supported_openai_params': []}},
])
def test_documented_exact_luna_support_does_not_depend_on_incomplete_or_stale_sdk(monkeypatch, catalog):
    module = _sdk(monkeypatch, catalog)
    policy = _policy()
    assert policy['options'] == policy['requested'] == {'reasoning_effort': 'low'}
    assert policy['intent'] == 'reduce' and policy['status'] == 'requested'
    module.get_model_info.assert_not_called()
    module.get_supported_openai_params.assert_not_called()
    module.supports_reasoning.assert_not_called()


def test_documented_luna_policy_never_initializes_sdk(monkeypatch):
    monkeypatch.delitem(sys.modules, 'litellm', raising=False)
    original_import = builtins.__import__
    def guard(name, *args, **kwargs):
        assert name != 'litellm', 'policy lookup must not initialize an SDK'
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guard)
    assert _policy()['options'] == {'reasoning_effort': 'low'}


@pytest.mark.parametrize('model', ['gpt-6-luna', 'openai/gpt-6-luna'])
@pytest.mark.parametrize('endpoint', [None, 'https://api.openai.com/v1', 'https://api.openai.com/v1/'])
def test_luna_declaration_applies_only_to_exact_documented_model_and_official_route(monkeypatch, model, endpoint):
    monkeypatch.delitem(sys.modules, 'litellm', raising=False)
    assert _policy(_settings(base_url=endpoint), model=model)['options'] == {'reasoning_effort': 'low'}


@pytest.mark.parametrize('model', ['gpt-6-luna-new', 'gpt-6-luna:batch', 'gpt-6-luna-2026-10-15',
    'gpt-6-luna-pro', 'gpt-6-Luna', 'openai/openai/gpt-6-luna', 'openrouter/openai/gpt-6-luna',
    'gpt-6-astra', 'gpt-6.1-sol'])
def test_luna_static_declaration_does_not_grant_capabilities_to_unverified_ids(monkeypatch, model):
    _sdk(monkeypatch, {})
    assert _policy(model=model)['options'] == {}


@pytest.mark.parametrize('endpoint', [
    'http://api.openai.com/v1', 'https://api.openai.com:443/v1', 'https://api.openai.com:9000/v1',
    'https://user@api.openai.com/v1', 'https://api.openai.com.evil.example/v1',
    'https://api.openai.com/custom', 'https://api.openai.com/v1/extra',
    'https://api.openai.com/v1?route=proxy', 'https://api.openai.com/v1#fragment',
    'https://proxy.example.com/v1', 'http://127.0.0.1:8000/v1',
])
def test_official_luna_capability_cannot_be_borrowed_by_custom_endpoints(monkeypatch, endpoint):
    _sdk(monkeypatch, {})
    policy = _policy(_settings(base_url=endpoint))
    assert policy['options'] == {} and policy['status'] == 'unsupported'


@pytest.mark.parametrize('provider', [ProviderName.OPENROUTER, ProviderName.GEMINI,
    ProviderName.OPENAI_COMPATIBLE, ProviderName.OLLAMA, ProviderName.DEEPSEEK, ProviderName.MOCK])
def test_other_providers_cannot_borrow_static_openai_capability(monkeypatch, provider):
    _sdk(monkeypatch, {})
    assert _policy(LLMSettings(provider=provider, model='gpt-6-luna'))['options'] == {}


@pytest.mark.parametrize('stage,operation', [
    ('semantic', 'SemanticResolution'), ('planner', 'AnalysisPlan'), ('insight', 'InsightList'),
    ('presentation', 'PresentationTopicSelection'), ('presentation', 'IntroductionDraft'),
    ('presentation', 'PresentationPlan'), ('presentation', 'UnknownOperation'),
    ('planner', 'IntroductionPages'), ('report', 'text'),
])
def test_luna_analytical_and_unknown_operations_preserve_defaults(monkeypatch, stage, operation):
    monkeypatch.delitem(sys.modules, 'litellm', raising=False)
    policy = _policy(stage=stage, operation=operation)
    assert policy['options'] == {} and policy['intent'] == 'preserve'


@pytest.mark.parametrize('stage,operation', [('presentation', 'TopicCoverageReview'),
    ('presentation', 'IntroductionPages'), ('report', 'BriefSourcePages'), ('report', 'format_repair')])
def test_luna_existing_reasoning_opt_out_remains_effective(monkeypatch, stage, operation):
    monkeypatch.delitem(sys.modules, 'litellm', raising=False)
    policy = _policy(_settings(simple_task_reasoning='provider_default'), stage=stage, operation=operation)
    assert policy['options'] == {} and policy['requested'] == {}
    assert policy['intent'] == 'preserve' and policy['status'] == 'provider_default'


def test_bounded_coverage_sends_low_to_completion_and_records_actual_attempt(monkeypatch):
    module = _sdk(monkeypatch, {}, '{"topics":[],"omissions":[],"coverage_decisions":[]}')
    settings = _settings(api_key=SecretStr('synthetic-test-key'))
    client = LiteLLMProvider(settings)
    monkeypatch.setattr(client, '_request_client', lambda: nullcontext({}))
    gateway = LLMGateway(client, settings)
    gateway.generate_structured([], TopicCoverageReview, stage='presentation', allow_repair=False, max_tokens=8192)
    request = module.completion.call_args.kwargs
    assert request['model'] == 'openai/gpt-6-luna' and request['custom_llm_provider'] == 'openai'
    assert request['api_base'] == 'https://api.openai.com/v1'
    assert request['reasoning_effort'] == 'low' and request['max_tokens'] == 8192
    row = gateway.usage[0]
    assert row['reasoning_policy']['requested'] == row['reasoning_policy']['applied'] == {'reasoning_effort': 'low'}
    assert row['attempts'][0]['reasoning_parameters'] == {'reasoning_effort': 'low'}
    assert 'synthetic-test-key' not in json.dumps(gateway.usage)


def test_real_sdk_temperature_rejection_preserves_luna_low_effort_and_its_audit(monkeypatch):
    class UnsupportedParamsError(Exception):
        pass
    module = _sdk(monkeypatch, {}, '{"topics":[],"omissions":[],"coverage_decisions":[]}')
    success = module.completion.return_value
    # Exact message emitted by the installed LiteLLM GPT adapter. The effort
    # name is explanatory advice, not a rejection of the requested low effort.
    error = UnsupportedParamsError(
        "gpt-6-luna doesn't support temperature=0.0 while reasoning is "
        "active. Only temperature=1 is supported unless reasoning_effort resolves to "
        "'none', either set explicitly on the request or declared as the model's "
        "default_reasoning_effort. "
        "To drop unsupported params set `litellm.drop_params = True`"
    )
    module.completion.side_effect = [error, success]
    settings = _settings(api_key=SecretStr('synthetic-test-key'))
    client = LiteLLMProvider(settings)
    monkeypatch.setattr(client, '_request_client', lambda: nullcontext({}))
    gateway = LLMGateway(client, settings)
    gateway.generate_structured([], TopicCoverageReview, stage='presentation', allow_repair=False, max_tokens=8192)
    assert module.completion.call_count == 2
    first, second = [call.kwargs for call in module.completion.call_args_list]
    assert first['temperature'] == 0 and 'temperature' not in second
    assert first['reasoning_effort'] == second['reasoning_effort'] == 'low'
    assert first['max_tokens'] == second['max_tokens'] == 8192
    for field in ('model', 'api_base', 'api_key', 'messages'):
        assert first[field] == second[field]
    row = gateway.usage[0]
    assert row['reasoning_policy']['requested'] == row['reasoning_policy']['applied'] == {'reasoning_effort': 'low'}
    assert row['reasoning_policy']['status'] == 'requested'
    assert row['attempts'][0]['compatibility_downgrade'] == ['temperature']
    assert row['attempts'][1]['reasoning_parameters'] == {'reasoning_effort': 'low'}


@pytest.mark.parametrize('message,rejected', [
    ("model doesn't support temperature=0 while reasoning is active unless reasoning_effort is none", {'temperature'}),
    ("model does not support temperature=0 when reasoning_effort=low", {'temperature'}),
    ("model only supports top_p, top_logprobs when reasoning_effort resolves to 'none'", {'top_p', 'top_logprobs'}),
    ("reasoning_effort=low is not supported for this model", {'reasoning_effort'}),
    ('unsupported request configuration', set()),
])
def test_sdk_rejection_clause_does_not_treat_control_advice_as_rejected_parameters(message, rejected):
    class UnsupportedParamsError(Exception):
        pass
    options = {'temperature': 0, 'reasoning_effort': 'low', 'top_p': 1, 'top_logprobs': 2}
    assert LiteLLMProvider._rejected_optional_params(UnsupportedParamsError(message), options) == rejected


def test_luna_reduction_and_opt_out_have_distinct_cache_identities(monkeypatch, tmp_path):
    from adaptive_document_agent.services.llm import gateway as gateway_module
    module = _sdk(monkeypatch, {})
    identities = []
    original_hash = gateway_module.sha256_bytes
    def capture(data):
        identities.append(json.loads(data))
        return original_hash(data)
    monkeypatch.setattr(gateway_module, 'sha256_bytes', capture)
    settings = _settings(api_key=SecretStr('synthetic-test-key'))
    client = LiteLLMProvider(settings)
    monkeypatch.setattr(client, '_request_client', lambda: nullcontext({}))
    gateway = LLMGateway(client, settings, cache=DiskCache(tmp_path))
    gateway.generate_structured([], IntroductionPages, stage='presentation', allow_repair=False)
    settings.simple_task_reasoning = 'provider_default'
    gateway.generate_structured([], IntroductionPages, stage='presentation', allow_repair=False)
    settings.simple_task_reasoning = 'reduced'
    gateway.generate_structured([], IntroductionPages, stage='presentation', allow_repair=False)
    assert module.completion.call_count == 2 and gateway.usage[-1]['status'] == 'app_cache_hit'
    assert identities[0]['request_policy']['options'] == {'reasoning_effort': 'low'}
    assert identities[1]['request_policy']['options'] == {}
    assert identities[2]['request_policy'] == identities[0]['request_policy']


def test_luna_explicit_unsupported_control_keeps_single_bounded_compatibility_retry(monkeypatch):
    class UnsupportedParamsError(Exception):
        pass
    module = _sdk(monkeypatch, {})
    success = module.completion.return_value
    module.completion.side_effect = [UnsupportedParamsError('unsupported reasoning_effort'), success]
    client = LiteLLMProvider(_settings(api_key=SecretStr('synthetic-test-key')))
    monkeypatch.setattr(client, '_request_client', lambda: nullcontext({}))
    gateway = LLMGateway(client, client.settings)
    gateway.generate_structured([], IntroductionPages, stage='presentation', allow_repair=False)
    assert module.completion.call_count == 2
    first, second = [call.kwargs for call in module.completion.call_args_list]
    assert first['reasoning_effort'] == 'low' and 'reasoning_effort' not in second
    for field in ('model', 'api_base', 'api_key', 'messages'):
        assert first[field] == second[field]
    row = gateway.usage[0]
    assert row['reasoning_policy']['status'] == 'compatibility_downgrade'
    assert row['reasoning_policy']['requested'] == {'reasoning_effort': 'low'}
    assert row['reasoning_policy']['applied'] == {}
    assert row['attempts'][0]['compatibility_downgrade'] == ['reasoning_effort']


@pytest.mark.parametrize('text,finish_reason', [('not JSON', 'stop'), ('', 'length')])
def test_luna_low_effort_never_relaxes_response_or_truncation_validation(monkeypatch, text, finish_reason):
    module = _sdk(monkeypatch, {}, text=text, finish_reason=finish_reason)
    client = LiteLLMProvider(_settings(api_key=SecretStr('synthetic-test-key')))
    monkeypatch.setattr(client, '_request_client', lambda: nullcontext({}))
    gateway = LLMGateway(client, client.settings)
    with pytest.raises(LLMResponseError):
        gateway.generate_structured([], IntroductionPages, stage='presentation', allow_repair=False)
    assert module.completion.call_count == 1
    assert module.completion.call_args.kwargs['reasoning_effort'] == 'low'
    assert gateway.usage[0]['status'] == ('truncated' if finish_reason == 'length' else 'invalid_format')
