"""Costs use reported counters; no paid requests or guessed missing metadata."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName, MockLLMClient
from adaptive_document_agent.services.llm.costs import estimate_cost, summarize_usage
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.services.llm.usage import LLMUsage
from adaptive_document_agent.services.llm.usage_parser import usage_counters
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError


class Answer(BaseModel):
    value: int


def usage(**kwargs):
    return LLMUsage(provider="deepseek", model="deepseek-flash", input_tokens=1000,
                    output_tokens=200, cached_input_tokens=800, reasoning_tokens=150, **kwargs)


@pytest.mark.parametrize("band,factor", [("off_peak", 1), ("peak", 2)])
def test_input_cache_output_and_reasoning_are_charged_once(band, factor):
    record = usage()
    estimate_cost(record, LLMSettings(deepseek_price_band=band))
    assert record.estimated_cost == pytest.approx((800 * .02 + 200 + 200 * 4) * factor / 1_000_000)
    assert record.cost_details["output_cost_min"] == pytest.approx(200 * 4 * factor / 1_000_000)
    assert record.cost_currency == "CNY"


def test_unknown_band_or_cache_counts_are_ranges_not_invented_exact_costs():
    record = usage()
    estimate_cost(record, LLMSettings())
    assert record.estimated_cost is None
    assert record.cost_details["estimated_cost_max"] == 2 * record.cost_details["estimated_cost_min"]
    record.cached_input_tokens = None
    estimate_cost(record, LLMSettings())
    assert not record.cost_details["cache_split_known"]
    assert record.cost_details["input_cost_min"] == pytest.approx(1000 * .02 / 1_000_000)
    assert record.cost_details["input_cost_max"] == pytest.approx(1000 * 2 / 1_000_000)


@pytest.mark.parametrize("settings", [
    LLMSettings(provider=ProviderName.OPENROUTER),
    LLMSettings(base_url="https://third-party.example/v1"),
    LLMSettings(provider=ProviderName.OPENAI_COMPATIBLE, base_url="http://localhost:8080/v1"),
])
def test_unknown_or_proxy_prices_stay_unknown(settings):
    record = usage()
    estimate_cost(record, settings)
    assert record.estimated_cost is None and record.cost_details["status"] == "unknown"


def test_bad_or_missing_usage_is_not_zero_cost():
    record = usage()
    record.uncached_input_tokens = 500
    estimate_cost(record, LLMSettings())
    assert record.cost_details["status"] == "unknown"
    record.input_tokens = None
    estimate_cost(record, LLMSettings())
    assert record.cost_details["status"] == "unknown"


@pytest.mark.parametrize("factory", [lambda x: x, lambda x: SimpleNamespace(**x)])
def test_provider_usage_dict_and_objects_preserve_cache_and_reasoning(factory):
    raw = factory({"usage": factory({"prompt_tokens": 100, "completion_tokens": 50,
        "prompt_tokens_details": factory({"cached_tokens": 70}),
        "completion_tokens_details": factory({"reasoning_tokens": 40}), "total_tokens": 150})})
    counters = usage_counters(raw)
    assert counters == dict(input_tokens=100, output_tokens=50, cached_input_tokens=70,
                            uncached_input_tokens=30, reasoning_tokens=40, total_tokens=150)
    assert all(v is None for v in usage_counters(factory({})).values())


def test_native_cache_counts_take_precedence_and_zero_is_preserved():
    counters = usage_counters({"usage": {"prompt_tokens": 90, "prompt_cache_hit_tokens": 0,
                              "prompt_cache_miss_tokens": 90, "prompt_tokens_details": {"cached_tokens": 80}}})
    assert counters["cached_input_tokens"] == 0 and counters["uncached_input_tokens"] == 90


def test_summary_keeps_unknown_legacy_failed_retry_and_currency_separate():
    record = usage()
    estimate_cost(record, LLMSettings())
    rows = [{**record.model_dump(), "stage": "discovery", "attempts": [{"status": "failed"}, {"status": "success"}]},
            {"stage": "discovery", "input_tokens": 10, "output_tokens": 5},
            {"stage": "semantic", "cache_hit": True}]
    result = summarize_usage(rows)
    cny = next(x for x in result["by_currency"] if x["currency"] == "CNY")
    assert cny["known_cost_min"] > 0 and cny["estimated_total_min"] is None
    assert cny["unmetered_attempts"] == 1
    unknown = next(x for x in result["by_currency"] if x["currency"] == "unknown")
    assert unknown["unknown_cost_calls"] == 1 and unknown["app_cache_hits"] == 1
    assert unknown["calls"] == 1 and unknown["estimated_total_max"] is None


def raw_response(text='{"value":1}', finish="stop"):
    return SimpleNamespace(model="resolved-version", choices=[SimpleNamespace(
        message=SimpleNamespace(content=text), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50,
                              prompt_cache_hit_tokens=60, prompt_cache_miss_tokens=40))


def test_discovery_thinking_policy_is_scoped_and_usage_keeps_actual_model(monkeypatch):
    settings = LLMSettings()
    provider = LiteLLMProvider(settings)
    complete = Mock(return_value=raw_response())
    monkeypatch.setattr(provider, "_completion", complete)
    gateway = LLMGateway(provider, settings)
    gateway.generate_structured([], Answer, stage="discovery")
    gateway.generate_structured([], Answer, stage="planner")
    assert complete.call_args_list[0].kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "extra_body" not in complete.call_args_list[1].kwargs
    assert gateway.usage[0]["resolved_model"] == "resolved-version"
    assert gateway.usage[0]["started_at"] and gateway.usage[0]["completed_at"]
    assert gateway.usage[0]["operation"] == "Answer"


@pytest.mark.parametrize("settings", [LLMSettings(discovery_thinking="provider_default"),
    LLMSettings(provider=ProviderName.OPENAI), LLMSettings(model="deepseek-reasoner"),
    LLMSettings(base_url="http://127.0.0.1:9000/v1")])
def test_policy_does_not_send_unsupported_thinking_options(settings, monkeypatch):
    provider = LiteLLMProvider(settings)
    complete = Mock(return_value=raw_response())
    monkeypatch.setattr(provider, "_completion", complete)
    LLMGateway(provider, settings).generate_structured([], Answer, stage="discovery")
    assert "extra_body" not in complete.call_args.kwargs


@pytest.mark.parametrize("output_tokens", [50, 8192, None])
def test_truncated_even_valid_json_is_metered_but_never_repaired_or_cached(monkeypatch, tmp_path, output_tokens):
    from adaptive_document_agent.utils.caching import DiskCache
    settings = LLMSettings()
    provider = LiteLLMProvider(settings)
    response = raw_response(finish="length")
    response.usage.completion_tokens = output_tokens
    complete = Mock(return_value=response)
    monkeypatch.setattr(provider, "_completion", complete)
    gateway = LLMGateway(provider, settings, cache=DiskCache(tmp_path))
    with pytest.raises(LLMStructuredOutputError, match="truncated") as failure:
        gateway.generate_structured([], Answer, stage="discovery")
    assert complete.call_count == 1 and not list(tmp_path.glob("*.json"))
    assert len(gateway.usage) == 1
    assert gateway.usage[0]["status"] == "truncated" and gateway.usage[0]["output_tokens"] == output_tokens
    assert "stage 'discovery'" in str(failure.value) and "operation 'Answer'" in str(failure.value)
    assert "model 'deepseek-flash'" in str(failure.value)
    token_detail = "unknown" if output_tokens is None else str(output_tokens)
    assert f"output tokens: {token_detail}" in str(failure.value)
    assert failure.value.response.usage.output_tokens == output_tokens
    assert failure.value.response.text not in str(failure.value)


def test_request_without_usage_is_recorded_as_unknown():
    from adaptive_document_agent.services.llm.base import LLMResponse
    gateway = LLMGateway(MockLLMClient(), LLMSettings(provider=ProviderName.MOCK))
    gateway._record(LLMResponse(text="hello"), stage="discovery")
    assert len(gateway.usage) == 1
    assert summarize_usage(gateway.usage)["by_stage"][0]["unknown_cost_calls"] == 1
