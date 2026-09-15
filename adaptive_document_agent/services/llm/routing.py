"""Provider construction kept outside agent business logic."""

from .base import LLMClient
from .config import LLMSettings, ProviderName
from .litellm_provider import LiteLLMProvider
from .mock import MockLLMClient


def create_llm_client(settings: LLMSettings) -> LLMClient:
    if settings.provider == ProviderName.MOCK:
        return MockLLMClient()
    return LiteLLMProvider(settings)

