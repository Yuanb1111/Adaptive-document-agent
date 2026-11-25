"""Fast processing must be opt-in on the wire and traceable in the usage ledger."""

import json
import socket

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
from adaptive_document_agent.services.llm.exceptions import LLMTransportError
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.services.llm.usage_export import usage_rows
from adaptive_document_agent.utils.caching import DiskCache


class Answer(BaseModel):
    value: int


@pytest.fixture
def wire(monkeypatch):
    requests = []
    response = {"service_tier": "priority"}
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")

    def send(client, request, **kwargs):
        payload = json.loads(request.content)
        requests.append(payload)
        if "error" in response:
            return httpx.Response(400, request=request, json=response)
        return httpx.Response(200, request=request, json={
            "id": "test", "object": "chat.completion", "created": 1, "model": payload["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": '{"value": 42}'}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}, **response,
        })

    def block(*args, **kwargs):
        raise AssertionError("Unmocked HTTP access during a Fast mode test")

    monkeypatch.setattr(socket.socket, "connect", block)
    monkeypatch.setattr(httpx.Client, "send", send)
    return requests, response


def settings(**overrides):
    return LLMSettings(**{"provider": ProviderName.OPENAI, "model": "gpt-6-luna",
                          "api_key": SecretStr("offline-test"), **overrides})


@pytest.mark.parametrize(("provider", "base_url", "stage_model", "enabled", "expected"), [
    (ProviderName.OPENAI, None, "gpt-6-luna", False, None),
    (ProviderName.OPENAI, "https://api.openai.com/v1/", "openai/gpt-6-luna", True, "fast"),
    (ProviderName.OPENAI, None, "gpt-6-luna-2026-09-22", True, "fast"),
    (ProviderName.OPENAI, None, "gpt-6.2-sol", True, None),
    (ProviderName.OPENAI, "https://proxy.invalid/v1", "gpt-6-luna", True, None),
    (ProviderName.OPENAI_COMPATIBLE, "https://proxy.invalid/v1", "gpt-6-luna", True, None),
])
def test_serialized_stage_requests(wire, provider, base_url, stage_model, enabled, expected):
    calls, _ = wire
    config = settings(provider=provider, base_url=base_url, openai_fast_mode=enabled,
                      stage_models={"report": stage_model})
    gateway = LLMGateway(LiteLLMProvider(config), config)
    assert gateway.generate_structured([], Answer, stage="report").value == 42
    assert len(calls) == 1 and calls[0].get("service_tier") == expected
    assert ("service_tier" in calls[0]) == bool(expected)
    row = usage_rows(gateway.usage)[0]
    assert row["requested_service_tier"] == expected
    assert row["service_tier"] == "priority"
    assert row["estimated_cost"] is None


@pytest.mark.parametrize("flag, expected", [("true", True), ("false", False)])
def test_fast_setting_from_environment(monkeypatch, flag, expected):
    monkeypatch.setenv("OPENAI_FAST_MODE", flag)
    assert LLMSettings.from_env().openai_fast_mode is expected


@pytest.mark.parametrize("returned_tier", ["default", None])
def test_record_returned_tier_without_inventing_or_rebilling(wire, tmp_path, returned_tier):
    calls, response = wire
    response.clear()
    if returned_tier is not None:
        response["service_tier"] = returned_tier
    config = settings(openai_fast_mode=True)
    cache = DiskCache(tmp_path)
    gateway = LLMGateway(LiteLLMProvider(config), config, cache=cache)
    assert gateway.generate_structured([], Answer, stage="report").value == 42
    actual = gateway.usage[0]
    assert actual["requested_service_tier"] == "fast" and actual["service_tier"] == returned_tier
    assert actual["attempts"][0]["requested_service_tier"] == "fast"
    assert actual["attempts"][0].get("service_tier") == returned_tier

    standard = settings()
    cached = LLMGateway(LiteLLMProvider(standard), standard, cache=cache)
    assert cached.generate_structured([], Answer, stage="report").value == 42
    assert len(calls) == 1
    ledger = usage_rows(cached.usage)[0]
    assert ledger["cache_hit"] and ledger["estimated_cost"] == 0
    assert ledger["requested_service_tier"] is None and ledger["service_tier"] is None


def test_rejected_fast_tier_is_not_retried_as_standard(wire):
    calls, response = wire
    response.clear()
    response["error"] = {"code": "unsupported_parameter", "type": "invalid_request_error",
                         "param": "service_tier", "message": "Unsupported service_tier."}
    config = settings(openai_fast_mode=True)
    gateway = LLMGateway(LiteLLMProvider(config), config)
    with pytest.raises(LLMTransportError):
        gateway.generate_structured([], Answer, stage="report")
    assert [c.get("service_tier") for c in calls] == ["fast"]
    ledger = usage_rows(gateway.usage)[0]
    assert ledger["requested_service_tier"] == "fast" and ledger["service_tier"] is None
    attempt = gateway.usage[0]["attempts"][0]
    assert attempt["status"] == "failed" and attempt["requested_service_tier"] == "fast"
