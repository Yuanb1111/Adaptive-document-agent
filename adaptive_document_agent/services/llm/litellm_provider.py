"""Lazy LiteLLM adapter; no analysis module imports LiteLLM directly."""

import json
import re
import time
from contextvars import ContextVar
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from .base import LLMClient, LLMResponse
from .capabilities import ModelCapabilities
from .config import LLMSettings, ProviderName
from .credentials import provider_endpoint
from .exceptions import LLMConfigurationError, LLMTransportError, LLMStructuredOutputError
from .structured import validate_structured_text
from .usage import LLMUsage
from .usage_parser import get_field, usage_counters
from .costs import estimate_cost
from .reasoning_policy import reasoning_parameters, request_reasoning_policy

_attempts: ContextVar[list | None] = ContextVar("llm_attempts", default=None)
_stage: ContextVar[str | None] = ContextVar("llm_stage", default=None)
_operation: ContextVar[str] = ContextVar("llm_operation", default="text")
_frozen_policy: ContextVar[tuple[object, str, str, str, dict[str, Any]] | None] = ContextVar("llm_frozen_policy", default=None)


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

    @contextmanager
    def request_context(self, *, stage: str):
        token = _stage.set(stage)
        try:
            yield
        finally:
            _stage.reset(token)

    @contextmanager
    def operation_context(self, *, operation: str):
        token = _operation.set(operation)
        try:
            yield
        finally:
            _operation.reset(token)

    @contextmanager
    def policy_context(self, *, stage: str, operation: str, model: str, policy: dict[str, Any]):
        token = _frozen_policy.set((self, stage, operation, model, deepcopy(policy)))
        try:
            yield
        finally:
            _frozen_policy.reset(token)

    def request_policy(self, *, stage: str, operation: str, model: str) -> dict[str, Any]:
        frozen = _frozen_policy.get()
        if frozen is not None and frozen[0] is self and frozen[1:4] == (stage, operation, model):
            return deepcopy(frozen[4])
        return request_reasoning_policy(self.settings, stage=stage, operation=operation, model=model)

    def _completion(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        try:
            from litellm import completion
        except ImportError as exc:
            raise LLMConfigurationError("LiteLLM is not installed. Install requirements.txt.") from exc
        key = self.settings.api_key.get_secret_value() if self.settings.api_key else None
        if not key:
            if self.settings.provider not in {ProviderName.OLLAMA, ProviderName.OPENAI_COMPATIBLE}:
                raise LLMConfigurationError("An API key is required for the selected provider.")
            # Explicit non-secret value prevents LiteLLM/OpenAI SDKs from using
            # another provider's environment or process-global credentials.
            key = "no-api-key"
        base_url = provider_endpoint(self.settings.provider, self.settings.base_url)
        if not base_url:
            raise LLMConfigurationError("A base URL is required for the selected provider.")
        selected_model = kwargs.pop("model", None) or self.settings.model
        if not selected_model:
            raise LLMConfigurationError("No LLM model is configured.")
        model = self._litellm_model(selected_model)
        if self.settings.provider == ProviderName.GEMINI and not self.settings.base_url:
            # LiteLLM expects a versioned Gemini api_base. Keep its default
            # chat API versions while excluding ambient endpoint overrides.
            version = "v1alpha" if "gemini-3" in selected_model else "v1beta"
            base_url = f"{base_url}/{version}"
        request_kwargs = {name: value for name, value in kwargs.items() if value is not None}
        transient_retries = 0
        compatibility_retry_used = False
        while True:
            started = time.perf_counter()
            event = {"attempt": transient_retries + int(compatibility_retry_used) + 1,
                     "started_at": datetime.now(timezone.utc).isoformat(),
                     "kind": "compatibility_retry" if compatibility_retry_used else "network_retry" if transient_retries else "initial"}
            event["reasoning_parameters"] = reasoning_parameters(request_kwargs)
            try:
                with self._request_client() as client_options:
                    result = completion(
                        model=model,
                        messages=messages,
                        api_key=key,
                        api_base=base_url,
                        custom_llm_provider=self._provider_route,
                        timeout=self.settings.timeout_seconds,
                        num_retries=0,
                        **client_options,
                        **request_kwargs,
                    )
                event["status"] = "success"
                return result
            except Exception as exc:
                event.update(status="failed", error_type=type(exc).__name__)
                rejected_params = self._rejected_optional_params(exc, request_kwargs)
                if rejected_params and not compatibility_retry_used:
                    event["compatibility_downgrade"] = sorted(rejected_params)
                    for param in rejected_params:
                        if param == "thinking":
                            body = dict(request_kwargs.get("extra_body", {}))
                            body.pop("thinking", None)
                            if body:
                                request_kwargs["extra_body"] = body
                            else:
                                request_kwargs.pop("extra_body", None)
                        else:
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
                event["completed_at"] = datetime.now(timezone.utc).isoformat()
                if _attempts.get() is not None:
                    _attempts.get().append(event)

    @contextmanager
    def _request_client(self):
        if self.settings.provider != ProviderName.GEMINI:
            yield {}
            return
        from litellm.llms.custom_httpx.http_handler import HTTPHandler

        # HTTPX strips Authorization across origins, but not x-goog-api-key.
        # Use a request-owned client so concurrent sessions and retries cannot
        # forward Gemini credentials via redirects or mutate global SDK state.
        client = HTTPHandler(timeout=self.settings.timeout_seconds)
        client.client.follow_redirects = False
        try:
            yield {"client": client}
        finally:
            client.close()

    @classmethod
    def _rejected_optional_params(cls, exc: Exception, request_kwargs: dict[str, Any]) -> set[str]:
        if type(exc).__name__ == "BadRequestError":
            return cls._server_rejected_reasoning_param(exc, request_kwargs)
        if type(exc).__name__ != "UnsupportedParamsError":
            return set()
        message = str(exc).casefold()
        candidates = request_kwargs.keys() & cls._OPTIONAL_GENERATION_PARAMS
        if "thinking" in request_kwargs.get("extra_body", {}):
            candidates.add("thinking")
        return {
            param
            for param in candidates
            if re.search(rf"(?<![a-z0-9_]){re.escape(param)}(?![a-z0-9_])", message)
        }

    @staticmethod
    def _server_rejected_reasoning_param(exc: Exception, request_kwargs: dict[str, Any]) -> set[str]:
        """Only explicit structured 400 parameter rejections permit downgrade.

        No message matching: authentication, content-policy and generic invalid
        requests must fail unchanged. Native SDKs expose body/code/param; LiteLLM
        can instead retain the original HTTP response with the same JSON fields.
        """
        if getattr(exc, "status_code", None) != 400:
            return set()
        response = getattr(exc, "response", None)
        if response is not None and getattr(response, "status_code", None) != 400:
            return set()
        body = getattr(exc, "body", None)
        if body is None and response is not None:
            try:
                body = response.json()
            except (ValueError, TypeError, AttributeError):
                return set()
        if body is None:
            body = {"code": getattr(exc, "code", None), "param": getattr(exc, "param", None)}
        if not isinstance(body, dict):
            return set()
        error = body.get("error", body)
        if not isinstance(error, dict):
            return set()
        code = error.get("code")
        if not isinstance(code, str) or code not in {"unsupported_parameter", "unknown_parameter"}:
            return set()
        param = error.get("param")
        if param == "reasoning_effort" and "reasoning_effort" in request_kwargs:
            return {"reasoning_effort"}
        # extra_body is a client wrapper; the actual outgoing JSON field is
        # thinking with its type child. Do not match arbitrary dotted prefixes.
        if param in ("thinking", "thinking.type") and "thinking" in request_kwargs.get("extra_body", {}):
            return {"thinking"}
        return set()

    @property
    def _provider_route(self) -> str:
        return "openai" if self.settings.provider == ProviderName.OPENAI_COMPATIBLE else self.settings.provider.value

    def _litellm_model(self, model: str) -> str:
        # Model IDs (including stage overrides and OpenRouter's provider/model
        # IDs) cannot change the selected credential's transport provider.
        prefix = self._provider_route + "/"
        return model if model.startswith(prefix) else prefix + model

    def generate_text(self, messages: list[dict[str, Any]], *, temperature: float = 0, max_tokens: int | None = None, model: str | None = None) -> LLMResponse:
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        attempt_log = []
        token = _attempts.set(attempt_log)
        try:
            policy = self.request_policy(stage=_stage.get(), operation=_operation.get(), model=model or self.settings.model)
            options = policy.pop("options")
            raw = self._completion(messages, temperature=temperature, max_tokens=max_tokens, model=model, **options)
            # "applied" records controls on the successful LiteLLM call; actual
            # reasoning consumption is separately reported by provider token usage.
            policy["applied"] = (attempt_log[-1]["reasoning_parameters"] if attempt_log else dict(policy["requested"]))
            if policy["applied"] != policy["requested"]:
                policy["status"] = "compatibility_downgrade"
            thinking = policy["applied"].get("thinking", {}).get("type")
            text = raw.choices[0].message.content or ""
            usage = LLMUsage(
                provider=self.settings.provider.value,
                model=model or self.settings.model,
                **usage_counters(raw),
                resolved_model=get_field(raw, "model"),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                finish_reason=get_field(raw.choices[0], "finish_reason"),
                thinking_mode=thinking,
                reasoning_policy=policy,
                request_chars=len(json.dumps(messages, ensure_ascii=False, separators=(",", ":"))),
                response_chars=len(text),
                latency_ms=int((time.perf_counter() - started) * 1000),
                estimated_cost=None,
            )
            estimate_cost(usage, self.settings)
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
            "content": "Return only valid JSON matching this schema: " + json.dumps(response_model.model_json_schema(), ensure_ascii=False, separators=(",", ":")),
        }
        response = self.generate_text([schema_instruction, *messages], temperature=temperature, model=model)
        if response.usage and response.usage.finish_reason == "length":
            raise LLMStructuredOutputError("Structured response was truncated by the model output limit.", response=response)
        try:
            return validate_structured_text(response.text, response_model), response
        except (ValueError, TypeError) as exc:
            raise LLMStructuredOutputError("Structured response failed schema validation.", response=response) from exc
