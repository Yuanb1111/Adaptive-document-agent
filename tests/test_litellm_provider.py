"""Regression tests for LiteLLM request compatibility."""

import sys
from types import ModuleType
from typing import Any

import pytest

from adaptive_document_agent.services.llm import LLMSettings, ProviderName
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider


class UnsupportedParamsError(Exception):
    pass


def _provider() -> LiteLLMProvider:
    return LiteLLMProvider(LLMSettings(provider=ProviderName.OPENAI, model="gpt-5.6-sol"))


def test_completion_omits_none_request_values(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    litellm = ModuleType("litellm")

    def completion(**kwargs: Any) -> object:
        calls.append(kwargs)
        return object()

    litellm.completion = completion  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", litellm)

    _provider()._completion([], temperature=0, max_tokens=None, model=None)

    assert calls[0]["temperature"] == 0
    assert "max_tokens" not in calls[0]


def test_completion_retries_without_explicitly_rejected_param(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    litellm = ModuleType("litellm")

    def completion(**kwargs: Any) -> object:
        calls.append(kwargs)
        if len(calls) == 1:
            raise UnsupportedParamsError("gpt-5.6-sol doesn't support temperature=0 while reasoning is active")
        return object()

    litellm.completion = completion  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", litellm)

    _provider()._completion([], temperature=0, max_tokens=None, model=None)

    assert len(calls) == 2
    assert calls[0]["temperature"] == 0
    assert "temperature" not in calls[1]


def test_completion_does_not_hide_unidentified_unsupported_param(monkeypatch: pytest.MonkeyPatch) -> None:
    litellm = ModuleType("litellm")

    def completion(**kwargs: Any) -> object:
        raise UnsupportedParamsError("unsupported request configuration")

    litellm.completion = completion  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", litellm)

    with pytest.raises(UnsupportedParamsError):
        _provider()._completion([], temperature=0, model=None)
