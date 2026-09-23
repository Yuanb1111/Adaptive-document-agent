"""Lazy LiteLLM adapter; no analysis module imports LiteLLM directly."""

import json
import re
import time
from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel

from .base import LLMClient, LLMResponse
from .capabilities import ModelCapabilities
from .config import LLMSettings
from .exceptions import LLMConfigurationError, LLMTransportError, LLMStructuredOutputError
from .structured import validate_structured_text
from .usage import LLMUsage

_attempts: ContextVar[list | None] = ContextVar("llm_attempts", default=None)


class LiteLLMProvider(LLMClient):
    supports_concurrent_requests = True

    _OPTIONAL_GENERATION_PARAMS = {
        "frequency_penalty",
        "logprobs",
        "max_tokens",
        "presence_penalty",
        "reasoning_effort",
        "seed",
        "stop",
        "temperature",
        "top_logprobs",
        "top_p",
    }

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
        request_kwargs = {name: value for name, value in kwargs.items() if value is not None}
        transient_retries = 0
        compatibility_retry_used = False
        while True:
            started = time.perf_counter()
            event = {"attempt": transient_retries + int(compatibility_retry_used) + 1,
                     "kind": "compatibility_retry" if compatibility_retry_used else "network_retry" if transient_retries else "initial"}
            try:
                result = completion(
                    model=model,
                    messages=messages,
                    api_key=key,
                    api_base=self.settings.base_url,
                    timeout=self.settings.timeout_seconds,
                    num_retries=0,
                    **request_kwargs,
                )
                event["status"] = "success"
                return result
            except Exception as exc:
                event.update(status="failed", error_type=type(exc).__name__)
                rejected_params = self._rejected_optional_params(exc, request_kwargs)
                if rejected_params and not compatibility_retry_used:
                    for param in rejected_params:
                        request_kwargs.pop(param, None)
                    compatibility_retry_used = True
                    continue
                transient = any(marker in type(exc).__name__.casefold() for marker in ("timeout", "rate", "connection", "serviceunavailable"))
                if not transient or transient_retries == 1:
                    raise
                transient_retries += 1
                time.sleep(0.25)
            finally:
                event["latency_ms"] = int((time.perf_counter() - started) * 1000)
                if _attempts.get() is not None:
                    _attempts.get().append(event)

    @classmethod
    def _rejected_optional_params(cls, exc: Exception, request_kwargs: dict[str, Any]) -> set[str]:
        if type(exc).__name__ != "UnsupportedParamsError":
            return set()
        message = str(exc).casefold()
        return {
            param
            for param in request_kwargs.keys() & cls._OPTIONAL_GENERATION_PARAMS
            if re.search(rf"(?<![a-z0-9_]){re.escape(param)}(?![a-z0-9_])", message)
        }

    def _litellm_model(self, model: str) -> str:
        if self.settings.is_local:
            # A stage override is a model name, not permission to reroute to a
            # cloud provider (including when an Ollama name contains a slash).
            prefix = "ollama/" if self.settings.provider.value == "ollama" else "openai/"
            return model if model.startswith(prefix) else prefix + model
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
        attempt_log = []
        token = _attempts.set(attempt_log)
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
            return LLMResponse(text=text, usage=usage, raw=raw, attempts=attempt_log)
        except LLMConfigurationError:
            raise
        except Exception as exc:
            raise LLMTransportError(f"Model request failed: {type(exc).__name__}", attempts=attempt_log) from exc
        finally:
            _attempts.reset(token)

    def generate_structured(self, messages: list[dict[str, Any]], response_model: type[BaseModel], *, temperature: float = 0, model: str | None = None) -> tuple[BaseModel, LLMResponse]:
        schema_instruction = {
            "role": "system",
            "content": "Return only valid JSON matching this schema: " + json.dumps(response_model.model_json_schema()),
        }
        response = self.generate_text([schema_instruction, *messages], temperature=temperature, model=model)
        try:
            return validate_structured_text(response.text, response_model), response
        except (ValueError, TypeError) as exc:
            raise LLMStructuredOutputError("Structured response failed schema validation.", response=response) from exc
