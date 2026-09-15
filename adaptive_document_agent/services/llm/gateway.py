"""Privacy-enforcing, structured-output-aware LLM gateway."""

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .base import LLMClient, LLMResponse
from .config import LLMSettings, PrivacyMode
from .exceptions import LLMResponseError, PrivacyViolationError

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

    def generate_structured(self, messages: list[dict[str, Any]], response_model: type[T], *, stage: str) -> T:
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
            return self._repair_once(messages, response_model, stage=stage)

    def _repair_once(self, messages: list[dict[str, Any]], response_model: type[T], *, stage: str) -> T:
        repair_messages = [
            *messages,
            {
                "role": "system",
                "content": "The prior answer was invalid. Return JSON only, matching this schema exactly. Do not add or invent facts: "
                + json.dumps(response_model.model_json_schema()),
            },
        ]
        response = self.client.generate_text(
            repair_messages,
            temperature=0,
            model=self.settings.model_for(stage),
        )
        self._record(response)
        try:
            return response_model.model_validate_json(response.text)
        except ValidationError as exc:
            raise LLMResponseError("Structured response remained invalid after one repair attempt.") from exc

    def _record(self, response: LLMResponse) -> None:
        if response.usage:
            self.usage.append(response.usage.model_dump())

