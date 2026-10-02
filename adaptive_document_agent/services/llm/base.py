"""Abstract interface implemented by all model providers."""

from abc import ABC, abstractmethod
from contextlib import nullcontext
from typing import Any

from pydantic import BaseModel, Field

from .capabilities import ModelCapabilities
from .usage import LLMUsage


class LLMResponse(BaseModel):
    text: str
    usage: LLMUsage | None = None
    raw: Any = None
    attempts: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class LLMClient(ABC):
    # Stateful/custom adapters remain serial unless they explicitly opt in.
    supports_concurrent_requests: bool = False

    def request_context(self, *, stage: str):
        """Optional per-call policy scope; custom adapters retain their API."""
        return nullcontext()

    def operation_context(self, *, operation: str):
        """Optional operation policy scope, independent of legacy stage hooks."""
        return nullcontext()

    def policy_context(self, *, stage: str, operation: str, model: str, policy: dict[str, Any]):
        """Optional frozen cache-policy scope; existing custom clients are unchanged."""
        return nullcontext()

    def request_policy(self, *, stage: str, operation: str, model: str) -> dict[str, Any]:
        """Non-secret request policy identity for structured-response caching."""
        return {}

    @abstractmethod
    def generate_text(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """Generate text without assuming provider-specific features."""

    @abstractmethod
    def generate_structured(
        self,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
        *,
        temperature: float = 0,
        model: str | None = None,
    ) -> tuple[BaseModel, LLMResponse]:
        """Generate a validated structured response."""

    @abstractmethod
    def supports(self, capability: str) -> bool:
        """Return whether a declared capability is supported."""

    @property
    @abstractmethod
    def capabilities(self) -> ModelCapabilities:
        """Return the model's declared capabilities."""
