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


@pytest.mark.parametrize('wrapper', ['{}', 'Result: {}', '```json\n{}\n```'])
def test_invalid_outer_response_cannot_be_replaced_by_a_valid_nested_answer(wrapper):
    from adaptive_document_agent.services.llm.structured import validate_structured_text
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match='value'):
        validate_structured_text(wrapper.format('{"unexpected": {"value": 9}}'), Answer)


def test_repairs_receive_the_outer_schema_error_instead_of_nested_missing_fields():
    from pydantic import Field, ValidationError
    from adaptive_document_agent.services.llm.structured import validate_structured_text
    class Part(BaseModel):
        text: str = Field(max_length=4)
    class Reading(BaseModel):
        parts: list[Part]
    with pytest.raises(ValidationError) as caught:
        validate_structured_text('{"parts":[{"text":"too long"}]}', Reading)
    assert caught.value.errors()[0]['loc'] == ('parts', 0, 'text')
    assert caught.value.errors()[0]['type'] == 'string_too_long'


@pytest.mark.parametrize('prefix', ['', 'Here is the result: '])
def test_malformed_outer_json_does_not_expose_an_inner_answer(prefix):
    from adaptive_document_agent.services.llm.structured import validate_structured_text
    with pytest.raises(ValueError):
        validate_structured_text(prefix + '{"broken": {"value": 9}', Answer)


def test_exact_json_takes_precedence_over_markdown_inside_source_strings():
    import json
    from adaptive_document_agent.services.llm.structured import validate_structured_text
    class Quote(BaseModel):
        text: str
    text = 'Source contains ```json\n{"value": 999}\n``` as untrusted text.'
    assert validate_structured_text(json.dumps({'text': text}), Quote).text == text


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
