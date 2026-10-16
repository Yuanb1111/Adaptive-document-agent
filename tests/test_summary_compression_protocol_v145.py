"""Independent boundary checks for compression, format and privacy budgets."""
from concurrent.futures import CancelledError
from threading import Event

import pytest

from adaptive_document_agent.agent.summary_draft_protocol import SummaryDraftProtocolError
from adaptive_document_agent.services.llm import (
    LLMGateway, LLMSettings, MockLLMClient, PrivacyMode, ProviderName)
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import (
    LLMStructuredOutputError, LLMTransportError, PrivacyViolationError)
from tests.test_summary_compression_v145 import compression_fixture, paginate


class FormatSequence:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append((messages, kwargs))
        value = self.responses.pop(0)
        if value == 'invalid':
            raise LLMStructuredOutputError('Malformed response', response=LLMResponse(text='{}'))
        return schema.model_validate(value.model_dump(mode='json'))


def test_each_geometry_correction_keeps_its_own_single_format_repair_bound():
    _, review, catalog, original, packed = compression_fixture()
    client, audit = FormatSequence(['invalid', original, 'invalid', packed]), {}
    current, pages = paginate(client, original, catalog, review, audit)
    assert current == packed and len(pages) == 1
    assert len(client.calls) == 4
    assert [row['status'] for row in audit['layout_attempts']] == ['overflow', 'overflow', 'success']
    assert [[attempt['status'] for attempt in row['draft_format_attempts']]
            for row in audit['layout_attempts'][:2]] == [
        ['invalid_format', 'success'], ['invalid_format', 'success']]
    assert all(kwargs['allow_repair'] is False for _, kwargs in client.calls)


def test_format_exhaustion_cannot_start_another_geometry_correction():
    _, review, catalog, original, packed = compression_fixture()
    client, audit = FormatSequence(['invalid', 'invalid', packed]), {}
    with pytest.raises(SummaryDraftProtocolError, match='format repair exhausted'):
        paginate(client, original, catalog, review, audit)
    assert len(client.calls) == 2 and len(client.responses) == 1
    assert len(audit['layout_attempts']) == 1


@pytest.mark.parametrize('error_type', [PrivacyViolationError, LLMTransportError, CancelledError])
def test_nonformat_compression_failure_propagates_without_a_repair_or_fallback(error_type):
    _, review, catalog, original, _ = compression_fixture()
    failure = error_type('Boundary failure')
    class Client:
        calls = 0
        def generate_structured(self, *args, **kwargs):
            self.calls += 1
            raise failure
    client, audit = Client(), {}
    with pytest.raises(error_type) as caught:
        paginate(client, original, catalog, review, audit)
    assert caught.value is failure
    assert client.calls == 1 and len(audit['layout_attempts']) == 1


def test_cancelled_before_compression_never_admits_an_author_request():
    _, review, catalog, original, _ = compression_fixture()
    cancelled = Event()
    cancelled.set()
    client, audit = FormatSequence([]), {}
    with pytest.raises(CancelledError):
        paginate(client, original, catalog, review, audit, cancelled=cancelled)
    assert not client.calls


def test_cancellation_after_first_compression_blocks_the_second_request():
    _, review, catalog, original, packed = compression_fixture()
    cancelled = Event()
    class Client(FormatSequence):
        def generate_structured(self, messages, schema, **kwargs):
            value = super().generate_structured(messages, schema, **kwargs)
            cancelled.set()
            return value
    client, audit = Client([original, packed]), {}
    with pytest.raises(CancelledError):
        paginate(client, original, catalog, review, audit, cancelled=cancelled)
    assert len(client.calls) == 1 and len(client.responses) == 1


def test_two_compressions_keep_the_same_loopback_only_gateway():
    _, review, catalog, original, packed = compression_fixture()
    client = MockLLMClient([original.model_dump(mode='json'), packed.model_dump(mode='json')])
    settings = LLMSettings(provider=ProviderName.OPENAI_COMPATIBLE, model='local-author',
        base_url='http://127.0.0.1:8000/v1', privacy_mode=PrivacyMode.LOCAL_ONLY)
    gateway = LLMGateway(client, settings, cache_enabled=False)
    current, pages = paginate(gateway, original, catalog, review, {})
    assert current == packed and len(pages) == 1 and len(client.calls) == 2
    assert gateway.settings is settings and gateway.settings.is_local
    assert gateway.settings.privacy_mode is PrivacyMode.LOCAL_ONLY
    assert gateway.client is client
    assert [row['operation'] for row in gateway.usage] == ['CompactSummaryDraft', 'CompactSummaryDraft']


def test_loopback_transport_failure_does_not_launch_another_model():
    _, review, catalog, original, _ = compression_fixture()
    class FailingLocalClient(MockLLMClient):
        admissions = 0
        def generate_structured(self, *args, **kwargs):
            self.admissions += 1
            raise LLMTransportError('Loopback unavailable')
    client = FailingLocalClient()
    settings = LLMSettings(provider=ProviderName.OPENAI_COMPATIBLE, model='local-author',
        base_url='http://127.0.0.1:8000/v1', privacy_mode=PrivacyMode.LOCAL_ONLY)
    gateway = LLMGateway(client, settings, cache_enabled=False)
    with pytest.raises(LLMTransportError, match='Loopback unavailable'):
        paginate(gateway, original, catalog, review, {})
    assert client.admissions == 1 and gateway.client is client
    assert gateway.settings is settings and gateway.settings.is_local
