"""Lazy LiteLLM adapter; no analysis module imports LiteLLM directly."""

import json
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from .base import LLMClient, LLMResponse
from .capabilities import ModelCapabilities
from .config import LLMSettings
from .exceptions import LLMConfigurationError, LLMResponseError
from .usage import LLMUsage


class LiteLLMProvider(LLMClient):
    def __init__(self, settings: LLMSettings, capabilities: ModelCapabilities | None = None) -> None:
        self.settings = settings
        self._capabilities = capabilities or ModelCapabilities(json_mode=True)

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._capabilities

    def supports(self, capability: str) -> bool:
        return bool(getattr(self.capabilities, capability, False))

    def _completion(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        try:
            from litellm import completion
        except ImportError as exc:
            raise LLMConfigurationError("LiteLLM is not installed. Install requirements.txt.") from exc
        key = self.settings.api_key.get_secret_value() if self.settings.api_key else None
        model = self._litellm_model(kwargs.pop("model") or self.settings.model)
        if not model:
            raise LLMConfigurationError("No LLM model is configured.")
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return completion(
                    model=model,
                    messages=messages,
                    api_key=key,
                    api_base=self.settings.base_url,
                    timeout=self.settings.timeout_seconds,
                    num_retries=0,
                    **kwargs,
                )
            except Exception as exc:
                last_error = exc
                transient = any(marker in type(exc).__name__.casefold() for marker in ("timeout", "rate", "connection", "serviceunavailable"))
                if not transient or attempt == 1:
                    raise
                time.sleep(0.25)
        raise last_error or RuntimeError("Unknown model error")

    def _litellm_model(self, model: str) -> str:
        if "/" in model or self.settings.provider.value == "openai":
            return model
        prefix = {
            "deepseek": "deepseek",
            "gemini": "gemini",
            "openrouter": "openrouter",
            "ollama": "ollama",
            "openai_compatible": "openai",
        }.get(self.settings.provider.value)
        return f"{prefix}/{model}" if prefix else model

    def generate_text(self, messages: list[dict[str, Any]], *, temperature: float = 0, max_tokens: int | None = None, model: str | None = None) -> LLMResponse:
        started = time.perf_counter()
        try:
            raw = self._completion(messages, temperature=temperature, max_tokens=max_tokens, model=model)
            text = raw.choices[0].message.content or ""
            usage_raw = getattr(raw, "usage", None)
            usage = LLMUsage(
                provider=self.settings.provider.value,
                model=model or self.settings.model,
                input_tokens=getattr(usage_raw, "prompt_tokens", None),
                output_tokens=getattr(usage_raw, "completion_tokens", None),
                latency_ms=int((time.perf_counter() - started) * 1000),
                estimated_cost=None,
            )
            return LLMResponse(text=text, usage=usage, raw=raw)
        except LLMConfigurationError:
            raise
        except Exception as exc:
            raise LLMResponseError(f"Model request failed: {type(exc).__name__}") from exc

    def generate_structured(self, messages: list[dict[str, Any]], response_model: type[BaseModel], *, temperature: float = 0, model: str | None = None) -> tuple[BaseModel, LLMResponse]:
        schema_instruction = {
            "role": "system",
            "content": "Return only valid JSON matching this schema: " + json.dumps(response_model.model_json_schema()),
        }
        response = self.generate_text([schema_instruction, *messages], temperature=temperature, model=model)
        try:
            return response_model.model_validate_json(response.text), response
        except ValidationError as exc:
            raise LLMResponseError("Structured response failed schema validation.") from exc
