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


def test_structured_output_repairs_once_when_the_first_response_is_invalid() -> None:
    client = MockLLMClient(["not-json", {"value": 7}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))
    assert gateway.generate_structured([], Answer, stage="discovery").value == 7
    assert len(client.calls) == 2


def test_structured_output_accepts_fenced_json_without_a_repair() -> None:
    client = MockLLMClient(['Here is the result:\n```json\n{"value": 9}\n```'])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))

    assert gateway.generate_structured([], Answer, stage="discovery").value == 9
    assert len(client.calls) == 1


def test_malformed_json_fails_after_one_repair_and_names_the_stage() -> None:
    client = MockLLMClient(["bad", "still bad"])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))
    with pytest.raises(LLMResponseError, match="stage 'discovery'.*one repair attempt"):
        gateway.generate_structured([], Answer, stage="discovery")
    assert len(client.calls) == 2


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
