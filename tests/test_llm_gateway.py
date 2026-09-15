"""Foundation tests for provider abstraction and privacy."""

import pytest
from pydantic import BaseModel

from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, PrivacyMode, ProviderName
from adaptive_document_agent.services.llm.exceptions import LLMResponseError, PrivacyViolationError


class Answer(BaseModel):
    value: int


def test_mock_structured_output() -> None:
    client = MockLLMClient([{"value": 42}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))
    assert gateway.generate_structured([], Answer, stage="discovery").value == 42
    assert gateway.usage[0]["provider"] == "mock"


def test_one_repair_attempt() -> None:
    client = MockLLMClient(["not-json", {"value": 7}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))
    assert gateway.generate_structured([], Answer, stage="discovery").value == 7
    assert len(client.calls) == 2


def test_malformed_json_fails_after_repair() -> None:
    client = MockLLMClient(["bad", "still bad"])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))
    with pytest.raises(LLMResponseError):
        gateway.generate_structured([], Answer, stage="discovery")


def test_local_only_rejects_cloud_provider() -> None:
    settings = LLMSettings(provider=ProviderName.OPENAI, model="example", privacy_mode=PrivacyMode.LOCAL_ONLY)
    with pytest.raises(PrivacyViolationError):
        LLMGateway(MockLLMClient(), settings)


def test_local_only_accepts_ollama() -> None:
    settings = LLMSettings(provider=ProviderName.OLLAMA, model="local", privacy_mode=PrivacyMode.LOCAL_ONLY)
    LLMGateway(MockLLMClient(), settings)


def test_local_only_rejects_remote_compatible_endpoint() -> None:
    settings = LLMSettings(
        provider=ProviderName.OPENAI_COMPATIBLE,
        model="example",
        base_url="https://models.example.com/v1",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )
    with pytest.raises(PrivacyViolationError):
        LLMGateway(MockLLMClient(), settings)


def test_local_only_accepts_loopback_compatible_endpoint() -> None:
    settings = LLMSettings(
        provider=ProviderName.OPENAI_COMPATIBLE,
        model="example",
        base_url="http://127.0.0.1:8000/v1",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )
    LLMGateway(MockLLMClient(), settings)
