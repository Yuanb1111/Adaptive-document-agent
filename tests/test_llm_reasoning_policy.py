"""Offline operation-level reasoning, routing, cache and concurrent-scope tests."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from threading import Barrier
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, SecretStr

from adaptive_document_agent.agent.company_introduction import IntroductionDraft, IntroductionPages
from adaptive_document_agent.agent.executive_brief import BriefSourcePages
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, PrivacyMode, ProviderName
from adaptive_document_agent.services.llm.exceptions import LLMResponseError, LLMTransportError
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.services.llm.reasoning_policy import request_reasoning_policy
from adaptive_document_agent.utils.caching import DiskCache


class Answer(BaseModel):
    value: int


class UnsupportedParamsError(Exception):
    pass


def raw_response(text='{"pages":[1,3]}'):
    return SimpleNamespace(model="resolved-test-model", choices=[SimpleNamespace(
        message=SimpleNamespace(content=text), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10))


def fake_litellm(monkeypatch, *, provider="openai", model="capable-model", capable=True, supported=True):
    module = ModuleType("litellm")
    module.model_cost = {f"{provider}/{model}": {
        "litellm_provider": provider, "supports_reasoning": capable,
        "supports_low_reasoning_effort": True, "default_reasoning_effort": "medium",
        "supported_openai_params": ["reasoning_effort"] if supported else [],
    }}
    module.get_supported_openai_params = Mock(return_value=["reasoning_effort"] if supported else [])
    module.completion = Mock(return_value=raw_response())
    monkeypatch.setitem(sys.modules, "litellm", module)
    return module


@pytest.mark.parametrize("model", ["deepseek-flash", "deepseek/deepseek-flash", "deepseek-v4-pro"])
@pytest.mark.parametrize("stage,schema", [("presentation", IntroductionPages), ("report", BriefSourcePages)])
def test_verified_direct_deepseek_selectors_disable_thinking(monkeypatch, model, stage, schema):
    settings = LLMSettings(model="unchanged-default", stage_models={stage: model})
    provider = LiteLLMProvider(settings)
    complete = Mock(return_value=raw_response())
    monkeypatch.setattr(provider, "_completion", complete)
    gateway = LLMGateway(provider, settings)
    result = gateway.generate_structured([], schema, stage=stage)
    assert result.pages == [1, 3]
    assert complete.call_args.kwargs["model"] == model
    assert complete.call_args.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert gateway.usage[0]["thinking_mode"] == "disabled"
    policy = gateway.usage[0]["reasoning_policy"]
    assert policy["operation"] == schema.__name__
    assert policy["requested"] == policy["applied"] == {"thinking": {"type": "disabled"}}
    assert settings.model == "unchanged-default"


@pytest.mark.parametrize("stage,operation", [
    ("semantic", "SemanticMappings"), ("planner", "AnalysisPlan"), ("insight", "InsightBatch"),
    ("report", "ExecutiveBrief"), ("presentation", "IntroductionDraft"),
    ("presentation", "PresentationPlan"), ("report", "text"),
    ("presentation", "UnknownPages"), ("planner", "IntroductionPages"),
])
def test_complex_unknown_and_wrong_stage_operations_keep_defaults(stage, operation):
    policy = request_reasoning_policy(LLMSettings(), stage=stage, operation=operation, model="deepseek-flash")
    assert policy["options"] == {} and policy["intent"] == "preserve"


@pytest.mark.parametrize("provider,model", [
    (ProviderName.OPENAI, "capable-model"), (ProviderName.GEMINI, "capable-model"),
    (ProviderName.OPENROUTER, "deepseek/capable-model"),
])
def test_capable_cloud_routes_get_only_supported_low_effort(monkeypatch, provider, model):
    module = fake_litellm(monkeypatch, provider=provider.value, model=model)
    settings = LLMSettings(provider=provider, model="default-model", api_key=SecretStr("dummy-test-key"),
                           stage_models={"report": model})
    client = LiteLLMProvider(settings)
    monkeypatch.setattr(client, "_request_client", lambda: nullcontext({}))
    gateway = LLMGateway(client, settings)
    gateway.generate_structured([], BriefSourcePages, stage="report")
    call = module.completion.call_args.kwargs
    assert call["model"] == f"{provider.value}/{model}"
    assert call["custom_llm_provider"] == provider.value
    assert call["reasoning_effort"] == "low" and "extra_body" not in call
    module.get_supported_openai_params.assert_not_called()
    policy = gateway.usage[0]["reasoning_policy"]
    assert policy["requested"] == policy["applied"] == {"reasoning_effort": "low"}
    assert gateway.usage[0]["attempts"][0]["reasoning_parameters"] == {"reasoning_effort": "low"}


@pytest.mark.parametrize("case", ["unknown", "not_reasoning", "unsupported_param", "wrong_provider", "no_low", "high_only", "pro_legacy", "batch_pro_legacy", "low_unverified", "missing_params", "invalid_params", "catalog_error"])
def test_capability_unknown_or_unsupported_keeps_provider_default(monkeypatch, case):
    model = "gpt-5-pro" if case == "pro_legacy" else "gpt-5-pro:batch" if case == "batch_pro_legacy" else "capable-model"
    module = fake_litellm(monkeypatch, model=model)
    entry = module.model_cost[f"openai/{model}"]
    if case == "unknown": module.model_cost.clear()
    if case == "not_reasoning": entry["supports_reasoning"] = False
    if case == "unsupported_param": entry["supported_openai_params"] = []
    if case == "wrong_provider": entry["litellm_provider"] = "openrouter"
    if case == "no_low": entry["supports_low_reasoning_effort"] = False
    if case == "high_only": entry["reasoning_effort_levels"] = ["high", "max"]
    if case in {"pro_legacy", "batch_pro_legacy", "low_unverified"}: entry.pop("supports_low_reasoning_effort")
    if case == "missing_params": entry.pop("supported_openai_params")
    if case == "invalid_params": entry["supported_openai_params"] = "reasoning_effort"
    if case == "catalog_error": module.model_cost = None
    policy = request_reasoning_policy(LLMSettings(provider=ProviderName.OPENAI),
        stage="report", operation="BriefSourcePages", model=model)
    assert policy["options"] == {} and policy["status"] == "unsupported"


@pytest.mark.parametrize("settings", [
    LLMSettings(model="deepseek-reasoner"),
    LLMSettings(base_url="https://proxy.example.com/v1"),
    LLMSettings(provider=ProviderName.OPENAI, model="capable-model", base_url="http://127.0.0.1:9000/v1"),
    LLMSettings(provider=ProviderName.OPENAI_COMPATIBLE, model="capable-model", base_url="http://localhost:8080/v1", privacy_mode=PrivacyMode.LOCAL_ONLY),
    LLMSettings(provider=ProviderName.OLLAMA, model="capable-model", privacy_mode=PrivacyMode.LOCAL_ONLY),
    LLMSettings(provider=ProviderName.MOCK, model="mock"),
])
def test_unsupported_custom_and_local_routes_do_not_borrow_cloud_options(monkeypatch, settings):
    module = fake_litellm(monkeypatch)
    client = LiteLLMProvider(settings)
    complete = Mock(return_value=raw_response())
    monkeypatch.setattr(client, "_completion", complete)
    LLMGateway(client, settings).generate_structured([], IntroductionPages, stage="presentation")
    assert "reasoning_effort" not in complete.call_args.kwargs
    assert "extra_body" not in complete.call_args.kwargs
    module.get_supported_openai_params.assert_not_called()


def test_exact_stage_model_capability_does_not_inherit_default_model(monkeypatch):
    module = fake_litellm(monkeypatch, model="capable-model")
    settings = LLMSettings(provider=ProviderName.OPENAI, model="capable-model", stage_models={"report": "unknown-routed"})
    client = LiteLLMProvider(settings)
    complete = Mock(return_value=raw_response())
    monkeypatch.setattr(client, "_completion", complete)
    LLMGateway(client, settings).generate_structured([], BriefSourcePages, stage="report")
    assert complete.call_args.kwargs["model"] == "unknown-routed"
    assert "reasoning_effort" not in complete.call_args.kwargs
    module.get_supported_openai_params.assert_not_called()


@pytest.mark.parametrize("succeeds", [True, False])
def test_format_repair_reduces_only_repair_then_restores_synthesis(monkeypatch, succeeds):
    settings = LLMSettings()
    provider = LiteLLMProvider(settings)
    complete = Mock(side_effect=[raw_response("bad JSON"), raw_response('{"value":7}' if succeeds else "bad again"), raw_response("{}")])
    monkeypatch.setattr(provider, "_completion", complete)
    gateway = LLMGateway(provider, settings)
    if succeeds:
        assert gateway.generate_structured([], Answer, stage="planner").value == 7
    else:
        with pytest.raises(LLMResponseError):
            gateway.generate_structured([], Answer, stage="planner")
    gateway.generate_structured([], IntroductionDraft, stage="presentation")
    assert ["extra_body" in call.kwargs for call in complete.call_args_list] == [False, True, False]
    assert gateway.usage[1]["reasoning_policy"]["operation"] == "format_repair"
    assert gateway.usage[1]["status"] == "format_repair"
    assert gateway.usage[-1]["reasoning_policy"]["intent"] == "preserve"


def test_nested_policy_contexts_restore_on_exception(monkeypatch):
    client = LiteLLMProvider(LLMSettings())
    complete = Mock(return_value=raw_response())
    monkeypatch.setattr(client, "_completion", complete)
    with client.request_context(stage="presentation"), client.operation_context(operation="IntroductionPages"):
        with pytest.raises(RuntimeError):
            with client.request_context(stage="planner"), client.operation_context(operation="AnalysisPlan"):
                client.generate_text([])
                raise RuntimeError("stop")
        client.generate_text([])
    client.generate_text([])
    assert ["extra_body" in call.kwargs for call in complete.call_args_list] == [False, True, False]


def test_concurrent_operations_do_not_leak_context_or_attempts(monkeypatch):
    module = fake_litellm(monkeypatch, provider="deepseek", model="deepseek-flash")
    barrier = Barrier(2)
    def completion(**kwargs):
        barrier.wait(timeout=5)
        content = kwargs["messages"][-1]["content"]
        if content == "selector":
            assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
            return raw_response()
        assert "extra_body" not in kwargs
        return raw_response("{}")
    module.completion.side_effect = completion
    settings = LLMSettings(api_key=SecretStr("dummy-test-key"))
    client = LiteLLMProvider(settings)
    gateway = LLMGateway(client, settings)
    def call(schema, content):
        return gateway.generate_structured([{"role": "user", "content": content}], schema, stage="presentation")
    with ThreadPoolExecutor(max_workers=2) as pool:
        simple = pool.submit(call, IntroductionPages, "selector")
        complex_call = pool.submit(call, IntroductionDraft, "synthesis")
        assert simple.result().pages == [1, 3]
        assert isinstance(complex_call.result(), IntroductionDraft)
    rows = {row["operation"]: row for row in gateway.usage}
    assert len(rows["IntroductionPages"]["attempts"]) == len(rows["IntroductionDraft"]["attempts"]) == 1
    assert rows["IntroductionPages"]["thinking_mode"] == "disabled"
    assert rows["IntroductionDraft"]["thinking_mode"] is None


@pytest.mark.parametrize("provider,parameter", [(ProviderName.OPENAI, "reasoning_effort"), (ProviderName.DEEPSEEK, "thinking")])
def test_compatibility_downgrade_is_bounded_and_honestly_audited(monkeypatch, provider, parameter):
    model = "deepseek-flash" if provider == ProviderName.DEEPSEEK else "capable-model"
    module = fake_litellm(monkeypatch, provider=provider.value, model=model)
    module.completion.side_effect = [UnsupportedParamsError(f"unsupported {parameter}"), raw_response()]
    settings = LLMSettings(provider=provider, model=model, api_key=SecretStr("dummy-test-key"))
    gateway = LLMGateway(LiteLLMProvider(settings), settings)
    gateway.generate_structured([], IntroductionPages, stage="presentation")
    assert module.completion.call_count == 2
    first, second = [call.kwargs for call in module.completion.call_args_list]
    assert first["model"] == second["model"] and first["api_base"] == second["api_base"]
    assert "reasoning_effort" not in second and "extra_body" not in second
    row = gateway.usage[0]
    assert row["reasoning_policy"]["status"] == "compatibility_downgrade"
    assert row["reasoning_policy"]["requested"] and row["reasoning_policy"]["applied"] == {}
    assert row["thinking_mode"] is None
    assert row["attempts"][0]["compatibility_downgrade"] == [parameter]
    assert row["attempts"][1]["reasoning_parameters"] == {}
    assert "dummy-test-key" not in json.dumps(gateway.usage)


def test_compatibility_failure_does_not_retry_forever_or_leak_scope(monkeypatch):
    module = fake_litellm(monkeypatch, provider="deepseek", model="deepseek-flash")
    module.completion.side_effect = [UnsupportedParamsError("unsupported thinking"), UnsupportedParamsError("unsupported request"), raw_response("{}")] 
    settings = LLMSettings(api_key=SecretStr("dummy-test-key"))
    gateway = LLMGateway(LiteLLMProvider(settings), settings)
    with pytest.raises(LLMTransportError):
        gateway.generate_structured([], IntroductionPages, stage="presentation")
    assert module.completion.call_count == 2
    assert len(gateway.usage[0]["attempts"]) == 2
    gateway.generate_structured([], IntroductionDraft, stage="presentation")
    assert "extra_body" not in module.completion.call_args.kwargs


def test_operation_and_repair_policy_settings_invalidate_cache(monkeypatch, tmp_path):
    settings = LLMSettings()
    client = LiteLLMProvider(settings)
    complete = Mock(return_value=raw_response())
    monkeypatch.setattr(client, "_completion", complete)
    gateway = LLMGateway(client, settings, cache=DiskCache(tmp_path))
    gateway.generate_structured([], IntroductionPages, stage="presentation")
    gateway.generate_structured([], IntroductionPages, stage="presentation")
    assert complete.call_count == 1
    settings.simple_task_reasoning = "provider_default"
    gateway.generate_structured([], IntroductionPages, stage="presentation")
    assert complete.call_count == 2 and "extra_body" not in complete.call_args.kwargs
    # A complex operation can also be supplied by repair, so its repair policy
    # belongs in the cache identity even though synthesis itself is unchanged.
    complete.return_value = raw_response("{}")
    gateway.generate_structured([], IntroductionDraft, stage="presentation")
    settings.simple_task_reasoning = "reduced"
    gateway.generate_structured([], IntroductionDraft, stage="presentation")
    assert complete.call_count == 4


def test_model_capability_change_invalidates_cached_selector(monkeypatch, tmp_path):
    module = fake_litellm(monkeypatch, capable=False)
    settings = LLMSettings(provider=ProviderName.OPENAI, model="capable-model")
    client = LiteLLMProvider(settings)
    complete = Mock(return_value=raw_response())
    monkeypatch.setattr(client, "_completion", complete)
    gateway = LLMGateway(client, settings, cache=DiskCache(tmp_path))
    gateway.generate_structured([], BriefSourcePages, stage="report")
    module.model_cost["openai/capable-model"]["supports_reasoning"] = True
    gateway.generate_structured([], BriefSourcePages, stage="report")
    assert complete.call_count == 2 and complete.call_args.kwargs["reasoning_effort"] == "low"


def test_legacy_stage_only_custom_client_keeps_compatible_signature():
    class StageOnlyClient(MockLLMClient):
        @contextmanager
        def request_context(self, *, stage):
            assert stage == "report"
            yield
    client = StageOnlyClient([{"pages": [2]}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))
    assert gateway.generate_structured([], BriefSourcePages, stage="report").pages == [2]


def test_simple_policy_environment_setting_is_validated(monkeypatch):
    monkeypatch.setenv("LLM_SIMPLE_TASK_REASONING", "provider_default")
    assert LLMSettings.from_env().simple_task_reasoning == "provider_default"
    with pytest.raises(ValueError):
        LLMSettings(simple_task_reasoning="high")


@pytest.mark.parametrize("endpoint", [
    "https://api.deepseek.com:443", "https://api.deepseek.com:9000/v1",
    "https://user@api.deepseek.com/v1", "https://api.deepseek.com/custom",
    "https://api.deepseek.com/v1?route=proxy", "https://api.deepseek.com/v1#fragment",
    "http://api.deepseek.com/v1", "https://api.deepseek.com.evil.example/v1",
])
def test_new_deepseek_policy_rejects_custom_endpoint_variants(endpoint):
    policy = request_reasoning_policy(LLMSettings(base_url=endpoint),
        stage="presentation", operation="IntroductionPages", model="deepseek-flash")
    assert policy["options"] == {} and policy["status"] == "unsupported"


@pytest.mark.parametrize("endpoint", [None, "https://api.deepseek.com", "https://api.deepseek.com/",
    "https://api.deepseek.com/v1", "https://api.deepseek.com/v1/", "https://api.deepseek.com/beta"])
def test_new_deepseek_policy_accepts_only_documented_endpoint_variants(endpoint):
    policy = request_reasoning_policy(LLMSettings(base_url=endpoint),
        stage="presentation", operation="IntroductionPages", model="deepseek-flash")
    assert policy["options"] == {"extra_body": {"thinking": {"type": "disabled"}}}


@pytest.mark.parametrize("provider", ["openai", "gemini", "openrouter"])
@pytest.mark.parametrize("default", ["none", "disabled", "minimal", "low", None, "unknown"])
def test_reduction_never_increases_a_low_disabled_or_unknown_default(monkeypatch, provider, default):
    module = fake_litellm(monkeypatch, provider=provider)
    module.model_cost[f"{provider}/capable-model"]["default_reasoning_effort"] = default
    policy = request_reasoning_policy(LLMSettings(provider=ProviderName(provider)),
        stage="report", operation="BriefSourcePages", model="capable-model")
    assert policy["options"] == {}


def test_positive_effort_levels_support_is_enough_without_flag(monkeypatch):
    module = fake_litellm(monkeypatch)
    entry = module.model_cost["openai/capable-model"]
    entry.pop("supports_low_reasoning_effort")
    entry["reasoning_effort_levels"] = ["low", "medium", "high"]
    policy = request_reasoning_policy(LLMSettings(provider=ProviderName.OPENAI),
        stage="report", operation="BriefSourcePages", model="capable-model")
    assert policy["options"] == {"reasoning_effort": "low"}


@pytest.mark.parametrize("model", ["deepseek-v4.1-flash", "deepseek-flash-new", "deepseek-v5-pro",
                                  "openrouter/deepseek/deepseek-flash"])
def test_unknown_new_deepseek_models_and_aliases_keep_defaults(model):
    policy = request_reasoning_policy(LLMSettings(),
        stage="presentation", operation="IntroductionPages", model=model)
    assert policy["options"] == {} and policy["status"] == "unsupported"


def test_simple_deepseek_capability_does_not_depend_on_price_card(monkeypatch):
    from adaptive_document_agent.services.llm import costs
    monkeypatch.setattr(costs, "DEEPSEEK_RATES", {})
    policy = request_reasoning_policy(LLMSettings(),
        stage="presentation", operation="IntroductionPages", model="deepseek-flash")
    assert policy["options"] == {"extra_body": {"thinking": {"type": "disabled"}}}


class BadRequestError(Exception):
    def __init__(self, body=None, *, status_code=400, response=None, code=None, param=None):
        # A misleading string must never authorize the native-server fallback.
        super().__init__("unsupported thinking reasoning_effort")
        self.status_code = status_code
        self.body = body
        self.response = response
        self.code = code
        self.param = param


@pytest.mark.parametrize("parameter,provider", [("reasoning_effort", ProviderName.OPENAI),
    ("thinking", ProviderName.DEEPSEEK), ("thinking.type", ProviderName.DEEPSEEK)])
@pytest.mark.parametrize("code", ["unsupported_parameter", "unknown_parameter"])
@pytest.mark.parametrize("source", ["body", "nested_body", "response", "fields"])
def test_explicit_native_reasoning_rejection_retries_once_and_audits(monkeypatch, parameter, provider, code, source):
    model = "deepseek-flash" if provider == ProviderName.DEEPSEEK else "capable-model"
    module = fake_litellm(monkeypatch, provider=provider.value, model=model)
    details = {"code": code, "param": parameter}
    if source == "body":
        error = BadRequestError(details)
    elif source == "nested_body":
        error = BadRequestError({"error": details})
    elif source == "response":
        error = BadRequestError(response=SimpleNamespace(status_code=400, json=lambda: {"error": details}))
    else:
        error = BadRequestError(code=code, param=parameter)
    module.completion.side_effect = [error, raw_response()]
    settings = LLMSettings(provider=provider, model=model, api_key=SecretStr("dummy-test-key"))
    gateway = LLMGateway(LiteLLMProvider(settings), settings)
    assert gateway.generate_structured([], IntroductionPages, stage="presentation").pages == [1, 3]
    assert module.completion.call_count == 2
    first, second = [call.kwargs for call in module.completion.call_args_list]
    for name in ["model", "api_base", "api_key", "custom_llm_provider", "messages"]:
        assert first[name] == second[name]
    assert "extra_body" not in second and "reasoning_effort" not in second
    assert second["temperature"] == first["temperature"]
    row = gateway.usage[0]
    assert row["reasoning_policy"]["status"] == "compatibility_downgrade"
    assert row["reasoning_policy"]["requested"] and row["reasoning_policy"]["applied"] == {}
    assert row["attempts"][0]["compatibility_downgrade"] == ["reasoning_effort" if parameter == "reasoning_effort" else "thinking"]
    assert row["attempts"][1]["reasoning_parameters"] == {}


@pytest.mark.parametrize("error", [
    BadRequestError(),  # misleading text without structured fields
    BadRequestError('{"code":"unsupported_parameter","param":"thinking"}'),
    BadRequestError({"error": "unsupported thinking"}),
    BadRequestError({"code": "invalid_request_error", "param": "thinking"}),
    BadRequestError({"code": ["unsupported_parameter"], "param": "thinking"}),
    BadRequestError({"code": "content_policy_violation", "param": "thinking"}),
    BadRequestError({"code": "invalid_api_key", "param": "thinking"}),
    BadRequestError({"code": "unsupported_value", "param": "thinking"}),
    BadRequestError({"code": "unsupported_parameter", "param": "temperature"}),
    BadRequestError({"code": "unsupported_parameter", "param": "messages"}),
    BadRequestError({"code": "unsupported_parameter", "param": "extra_body"}),
    BadRequestError({"code": "unsupported_parameter", "param": "thinking.budget"}),
    BadRequestError({"code": "unsupported_parameter", "param": "extra_body.thinking"}),
    BadRequestError({"code": "unsupported_parameter", "param": "not_thinking.type"}),
    BadRequestError({"code": "unsupported_parameter", "param": ["thinking"]}),
    BadRequestError({"code": "unsupported_parameter", "param": "thinking"}, status_code=401),
    BadRequestError({"code": "unsupported_parameter", "param": "thinking"},
                    response=SimpleNamespace(status_code=403)),
    BadRequestError(response=SimpleNamespace(status_code=400, json=lambda: "unsupported thinking")),
])
def test_native_bad_requests_never_downgrade_without_precise_structured_evidence(monkeypatch, error):
    module = fake_litellm(monkeypatch, provider="deepseek", model="deepseek-flash")
    module.completion.side_effect = error
    settings = LLMSettings(api_key=SecretStr("dummy-test-key"))
    gateway = LLMGateway(LiteLLMProvider(settings), settings)
    with pytest.raises(LLMTransportError):
        gateway.generate_structured([], IntroductionPages, stage="presentation")
    assert module.completion.call_count == 1
    assert "compatibility_downgrade" not in gateway.usage[0]["attempts"][0]


def test_native_retry_requires_exact_error_type_and_present_optional_control():
    payload = {"code": "unsupported_parameter", "param": "reasoning_effort"}
    class AuthenticationError(BadRequestError):
        pass
    assert LiteLLMProvider._rejected_optional_params(AuthenticationError(payload), {"reasoning_effort": "low"}) == set()
    assert LiteLLMProvider._rejected_optional_params(BadRequestError(payload), {"temperature": 0}) == set()
    malformed = BadRequestError(response=SimpleNamespace(status_code=400, json=Mock(side_effect=ValueError())))
    assert LiteLLMProvider._rejected_optional_params(malformed, {"reasoning_effort": "low"}) == set()


def test_native_compatibility_retry_is_shared_with_existing_retry_budget(monkeypatch):
    module = fake_litellm(monkeypatch, provider="deepseek", model="deepseek-flash")
    module.completion.side_effect = [UnsupportedParamsError("unsupported temperature"),
        BadRequestError({"code": "unsupported_parameter", "param": "thinking"})]
    settings = LLMSettings(api_key=SecretStr("dummy-test-key"))
    gateway = LLMGateway(LiteLLMProvider(settings), settings)
    with pytest.raises(LLMTransportError):
        gateway.generate_structured([], IntroductionPages, stage="presentation")
    assert module.completion.call_count == 2
    assert len(gateway.usage[0]["attempts"]) == 2


def test_native_thinking_downgrade_preserves_other_extra_body_options(monkeypatch):
    module = fake_litellm(monkeypatch, provider="deepseek", model="deepseek-flash")
    module.completion.side_effect = [BadRequestError({"error": {"code": "unknown_parameter", "param": "thinking.type"}}), raw_response()]
    client = LiteLLMProvider(LLMSettings(api_key=SecretStr("dummy-test-key")))
    original = {"thinking": {"type": "disabled"}, "unrelated_option": True}
    client._completion([], extra_body=original)
    assert module.completion.call_args.kwargs["extra_body"] == {"unrelated_option": True}
    assert original == {"thinking": {"type": "disabled"}, "unrelated_option": True}



def test_native_openai_sdk_error_body_shape_is_supported_offline():
    import httpx
    from openai import BadRequestError as SDKBadRequestError

    body = {"code": "unsupported_parameter", "param": "thinking.type"}
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
                              json={"error": body})
    error = SDKBadRequestError("native structured rejection", response=response, body=body)
    assert LiteLLMProvider._rejected_optional_params(error,
        {"extra_body": {"thinking": {"type": "disabled"}}}) == {"thinking"}



@pytest.mark.parametrize("provider", ["openai", "gemini", "openrouter"])
def test_capability_policy_never_calls_dynamic_sdk_helpers(monkeypatch, provider):
    module = fake_litellm(monkeypatch, provider=provider)
    module.get_supported_openai_params.side_effect = AssertionError("must not perform dynamic lookup")
    module.supports_reasoning = Mock(side_effect=AssertionError("must not query provider metadata"))
    module.get_model_info = Mock(side_effect=AssertionError("must not fetch catalog"))
    policy = request_reasoning_policy(LLMSettings(provider=ProviderName(provider)),
        stage="report", operation="BriefSourcePages", model="capable-model")
    assert policy["options"] == {"reasoning_effort": "low"}
    module.get_supported_openai_params.assert_not_called()
    module.supports_reasoning.assert_not_called()
    module.get_model_info.assert_not_called()


def test_capability_policy_does_not_initialize_sdk_to_load_metadata(monkeypatch):
    import builtins
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        assert name != "litellm", "policy must not initialize a network-capable SDK"
        return original_import(name, *args, **kwargs)
    monkeypatch.delitem(sys.modules, "litellm", raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    policy = request_reasoning_policy(LLMSettings(provider=ProviderName.OPENAI),
        stage="report", operation="BriefSourcePages", model="capable-model")
    assert policy["options"] == {} and policy["status"] == "unsupported"


@pytest.mark.parametrize("initially_loaded", [False, True])
def test_initial_request_uses_exact_pre_hash_policy_when_sdk_state_changes(monkeypatch, tmp_path, initially_loaded):
    from adaptive_document_agent.services.llm import gateway as gateway_module
    module = fake_litellm(monkeypatch)
    if not initially_loaded:
        monkeypatch.delitem(sys.modules, "litellm")
    identities = []
    original_hash = gateway_module.sha256_bytes
    def hash_then_change_sdk(data):
        identities.append(json.loads(data))
        if initially_loaded:
            monkeypatch.delitem(sys.modules, "litellm", raising=False)
        else:
            monkeypatch.setitem(sys.modules, "litellm", module)
        return original_hash(data)
    monkeypatch.setattr(gateway_module, "sha256_bytes", hash_then_change_sdk)
    settings = LLMSettings(provider=ProviderName.OPENAI, model="capable-model")
    client = LiteLLMProvider(settings)
    complete = Mock(return_value=raw_response())
    monkeypatch.setattr(client, "_completion", complete)
    gateway = LLMGateway(client, settings, cache=DiskCache(tmp_path))
    gateway.generate_structured([], BriefSourcePages, stage="report")
    expected = {"reasoning_effort": "low"} if initially_loaded else {}
    assert identities[0]["request_policy"]["requested"] == expected
    assert gateway.usage[0]["reasoning_policy"]["requested"] == expected
    assert gateway.usage[0]["reasoning_policy"]["applied"] == expected
    assert complete.call_args.kwargs.get("reasoning_effort") == expected.get("reasoning_effort")
    assert identities[0]["request_policy"]["options"] == expected  # snapshot not mutated
    module.get_supported_openai_params.assert_not_called()


@pytest.mark.parametrize("initially_loaded", [False, True])
def test_repair_request_uses_pre_hash_policy_when_initial_call_changes_sdk(monkeypatch, tmp_path, initially_loaded):
    from adaptive_document_agent.services.llm import gateway as gateway_module
    module = fake_litellm(monkeypatch)
    if not initially_loaded:
        monkeypatch.delitem(sys.modules, "litellm")
    identities = []
    original_hash = gateway_module.sha256_bytes
    def capture_hash(data):
        identities.append(json.loads(data))
        return original_hash(data)
    monkeypatch.setattr(gateway_module, "sha256_bytes", capture_hash)
    calls = []
    def complete(messages, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            if initially_loaded:
                monkeypatch.delitem(sys.modules, "litellm", raising=False)
            else:
                monkeypatch.setitem(sys.modules, "litellm", module)
            return raw_response("bad JSON")
        return raw_response('{"value":7}')
    settings = LLMSettings(provider=ProviderName.OPENAI, model="capable-model")
    client = LiteLLMProvider(settings)
    monkeypatch.setattr(client, "_completion", complete)
    gateway = LLMGateway(client, settings, cache=DiskCache(tmp_path))
    assert gateway.generate_structured([], Answer, stage="report").value == 7
    expected = {"reasoning_effort": "low"} if initially_loaded else {}
    assert identities[0]["request_policy"]["requested"] == {}
    assert gateway.usage[0]["reasoning_policy"]["requested"] == {}
    assert identities[0]["repair_policy"]["requested"] == expected
    assert gateway.usage[1]["reasoning_policy"]["requested"] == expected
    assert gateway.usage[1]["reasoning_policy"]["applied"] == expected
    assert calls[1].get("reasoning_effort") == expected.get("reasoning_effort")
    assert identities[0]["repair_policy"]["options"] == expected
    module.get_supported_openai_params.assert_not_called()


def test_frozen_policy_is_copied_exactly_scoped_and_restored_after_error(monkeypatch):
    from adaptive_document_agent.services.llm import litellm_provider as provider_module
    provider = LiteLLMProvider(LLMSettings())
    other = LiteLLMProvider(LLMSettings())
    fallback = Mock(return_value={"outside": True})
    monkeypatch.setattr(provider_module, "request_reasoning_policy", fallback)
    route = {"stage": "report", "operation": "BriefSourcePages", "model": "deepseek-flash"}
    policy = {"options": {"reasoning_effort": "low"}}
    with provider.policy_context(**route, policy=policy):
        policy["options"]["reasoning_effort"] = "high"
        returned = provider.request_policy(**route)
        assert returned == {"options": {"reasoning_effort": "low"}}
        returned["options"]["reasoning_effort"] = "max"
        assert provider.request_policy(**route) == {"options": {"reasoning_effort": "low"}}
        assert other.request_policy(**route) == {"outside": True}
        for field in ("stage", "operation", "model"):
            assert provider.request_policy(**{**route, field: "other"}) == {"outside": True}
        with pytest.raises(RuntimeError):
            with provider.policy_context(**route, policy={"inner": True}):
                assert provider.request_policy(**route) == {"inner": True}
                raise RuntimeError("restore outer snapshot")
        assert provider.request_policy(**route) == {"options": {"reasoning_effort": "low"}}
    assert provider.request_policy(**route) == {"outside": True}


def test_frozen_policy_isolation_for_same_model_concurrent_requests(monkeypatch):
    from adaptive_document_agent.services.llm import litellm_provider as provider_module
    provider = LiteLLMProvider(LLMSettings())
    fallback = Mock(side_effect=AssertionError("frozen requests must never recompute policy"))
    monkeypatch.setattr(provider_module, "request_reasoning_policy", fallback)
    route = {"stage": "report", "operation": "BriefSourcePages", "model": "deepseek-flash"}
    barrier = Barrier(2)
    def read_policy(value):
        with provider.policy_context(**route, policy={"thread": value}):
            barrier.wait(timeout=5)
            return provider.request_policy(**route)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(read_policy, value) for value in (1, 2)]
        assert [future.result() for future in futures] == [{"thread": 1}, {"thread": 2}]
    fallback.assert_not_called()
