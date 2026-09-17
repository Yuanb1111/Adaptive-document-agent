"""Privacy-enforcing, structured-output-aware LLM gateway."""

import json
from typing import Any, TypeVar

from pydantic import BaseModel

from .base import LLMClient, LLMResponse
from .config import LLMSettings, PrivacyMode
from .exceptions import LLMResponseError, PrivacyViolationError
from .structured import validate_structured_text

T = TypeVar("T", bound=BaseModel)


class LLMGateway:
    def __init__(self, client: LLMClient, settings: LLMSettings) -> None:
        self.client = client
        self.settings = settings
        self.usage: list[dict[str, object]] = []
        if settings.privacy_mode == PrivacyMode.LOCAL_ONLY and not settings.is_local:
            raise PrivacyViolationError("Local Only mode forbids cloud LLM providers.")

    def generate_text(self, messages: list[dict[str, Any]], *, stage: str, max_tokens: int | None = None) -> str:
        response = self.client.generate_text(
            messages,
            temperature=self.settings.temperature,
            max_tokens=max_tokens,
            model=self.settings.model_for(stage),
        )
        self._record(response)
        return response.text

    def generate_structured(
        self,
        messages: list[dict[str, Any]],
        response_model: type[T],
        *,
        stage: str,
        allow_repair: bool = True,
    ) -> T:
        model_name = self.settings.model_for(stage)
        try:
            value, response = self.client.generate_structured(
                messages,
                response_model,
                temperature=self.settings.temperature,
                model=model_name,
            )
            self._record(response)
            return value  # type: ignore[return-value]
        except LLMResponseError:
            if not allow_repair:
                raise
            return self._repair_structured(messages, response_model, stage=stage)

    def _repair_structured(self, messages: list[dict[str, Any]], response_model: type[T], *, stage: str) -> T:
        schema = json.dumps(response_model.model_json_schema(), separators=(",", ":"))
        repair_messages = [
            *messages,
            {
                "role": "system",
                "content": (
                    "The prior answer was invalid. Return one complete JSON value only. "
                    "Match the schema exactly, use only supplied IDs and facts, and do not wrap JSON in markdown. Schema: "
                    + schema
                ),
            },
        ]
        try:
            response = self.client.generate_text(
                repair_messages,
                temperature=0,
                max_tokens=8_000 if stage == "presentation" else None,
                model=self.settings.model_for(stage),
            )
            self._record(response)
            return validate_structured_text(response.text, response_model)
        except (LLMResponseError, ValueError, TypeError) as exc:
            detail = type(exc).__name__
            raise LLMResponseError(
                f"Structured response for stage '{stage}' remained invalid after one repair attempt ({detail})."
            ) from exc

    def _record(self, response: LLMResponse) -> None:
        if response.usage:
            self.usage.append(response.usage.model_dump())
