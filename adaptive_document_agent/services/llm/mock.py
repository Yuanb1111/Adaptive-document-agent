"""Deterministic model client for unit and integration tests."""

import json
from collections import deque
from typing import Any

from pydantic import BaseModel

from .base import LLMClient, LLMResponse
from .capabilities import ModelCapabilities
from .exceptions import LLMResponseError, LLMStructuredOutputError
from .structured import validate_structured_text
from .usage import LLMUsage


class MockLLMClient(LLMClient):
    def __init__(self, responses: list[str | dict[str, Any]] | None = None, *, capabilities: ModelCapabilities | None = None) -> None:
        self.responses = deque(responses or [])
        self.calls: list[list[dict[str, Any]]] = []
        self._capabilities = capabilities or ModelCapabilities(structured_output=True, json_mode=True)

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._capabilities

    def supports(self, capability: str) -> bool:
        return bool(getattr(self.capabilities, capability, False))

    def _next(self) -> str:
        if not self.responses:
            raise LLMResponseError("Mock response queue is empty.")
        value = self.responses.popleft()
        return json.dumps(value) if isinstance(value, dict) else value

    def generate_text(self, messages: list[dict[str, Any]], *, temperature: float = 0, max_tokens: int | None = None, model: str | None = None) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(text=self._next(), usage=LLMUsage(provider="mock", model=model or "mock"))

    def generate_structured(self, messages: list[dict[str, Any]], response_model: type[BaseModel], *, temperature: float = 0, model: str | None = None) -> tuple[BaseModel, LLMResponse]:
        response = self.generate_text(messages, temperature=temperature, model=model)
        try:
            return validate_structured_text(response.text, response_model), response
        except Exception as exc:
            raise LLMStructuredOutputError("Mock structured response is invalid.", response=response) from exc
