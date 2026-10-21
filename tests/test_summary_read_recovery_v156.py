"""A semantic correction may need its own format repair, without losing evidence."""
import json
from threading import Event

import pytest

from adaptive_document_agent.agent.prompting import untrusted_document_message
from adaptive_document_agent.agent.summary_reader import SummaryReadBatch, _read_batch, read_summary
from adaptive_document_agent.models.summary import SummaryReview
from adaptive_document_agent.services.llm import LLMGateway, MockLLMClient
from adaptive_document_agent.services.llm.structured import preserves_json_content
from adaptive_document_agent.services.summary_source import source_blocks
from adaptive_document_agent.utils.caching import DiskCache
from tests.test_complete_summary_reading import SummaryClient, gateway, source


def reading(result, blocks):
    messages = [untrusted_document_message(json.dumps([
        {'block_id': b.id, 'page': b.page, 'lines': list(enumerate(b.text.splitlines(keepends=True), 1))}
        for b in blocks]))]
    return SummaryClient().generate_structured(messages, SummaryReadBatch)[0]


def setup(*, cache=None, pages=1):
    result = source(pages)
    blocks = source_blocks(result, list(range(1, pages + 1)))
    valid = reading(result, blocks)
    initial = valid.model_copy(deep=True)
    initial.parts.append(initial.parts[1].model_copy(deep=True))
    malformed = valid.model_dump_json().replace('"quote_start_line":', 'quote_start_line":', 1)
    client = MockLLMClient([initial.model_dump(), malformed, valid.model_dump_json()])
    real = LLMGateway(client, gateway(local=True).settings, cache=cache)
    return result, blocks, valid, client, real


def test_semantic_retry_has_independent_format_repair_and_all_validators_still_run():
    result, blocks, valid, client, real = setup()
    outcome = _read_batch(real, result, blocks, Event())
    assert outcome.error is None
    assert len(client.calls) == 3
    assert len(outcome.audit['attempts']) == 2
    assert outcome.audit['attempts'][0]['errors']
    repair = outcome.audit['attempts'][1]['format_repair']
    assert repair['status'] == 'repaired' and 'raw_response' in repair
    assert outcome.audit['attempts'][1]['errors'] == []
    assert [r['status'] for r in real.usage] == ['success', 'invalid_format', 'format_repair']
    assert all(r['source_page_start'] == 1 and r['source_page_end'] == 1 for r in real.usage)
    assert all(f.source_quote in p.source_text for p in outcome.parts for f in p.facts)


@pytest.mark.parametrize('change', ['number', 'claim', 'structure', 'invalid'])
def test_format_repair_cannot_invent_facts_or_loop(change):
    result, blocks, valid, client, real = setup()
    repaired = valid.model_dump_json()
    if change == 'number': repaired = repaired.replace('Cedar provides', 'Cedar provides 999')
    elif change == 'claim': repaired = repaired.replace('manufacturing', 'medical')
    elif change == 'structure':
        altered = valid.model_copy(deep=True)
        altered.parts.pop()
        repaired = altered.model_dump_json()
    else: repaired = '{broken'
    client.responses[-1] = repaired
    outcome = _read_batch(real, result, blocks, Event())
    assert outcome.error is not None and outcome.parts == []
    assert len(client.calls) == 3
    assert outcome.audit['failure_kind'] == 'format'
    assert outcome.audit['attempts'][1]['format_repair']['status'] == 'failed'
    assert outcome.audit['attempts'][1]['format_repair']['repair_validation_detail']


def test_format_repair_does_not_spend_the_semantic_retry_on_the_initial_request():
    result, blocks, valid, client, real = setup()
    initial = client.responses[0]
    initial_text = json.dumps(initial)
    client.responses.clear()
    client.responses.extend([initial_text.replace('"quote_start_line":', 'quote_start_line":', 1),
                             initial_text, valid.model_dump_json()])
    outcome = _read_batch(real, result, blocks, Event())
    assert outcome.error is None and len(client.calls) == 3
    assert outcome.audit['attempts'][0]['format_repair']['status'] == 'repaired'
    assert outcome.audit['attempts'][0]['errors']
    assert outcome.audit['attempts'][1]['errors'] == []


def test_successful_batches_survive_another_batch_failure_and_are_revalidated(tmp_path, monkeypatch):
    import adaptive_document_agent.agent.summary_reader as reader
    result = source(2)
    blocks = source_blocks(result, [1, 2])
    monkeypatch.setattr(reader, 'reading_batches', lambda supplied: [[b] for b in supplied])
    first, second = [reading(result, [b]) for b in blocks]
    malformed = second.model_dump_json().replace('"quote_start_line":', 'quote_start_line":', 1)
    client = MockLLMClient([first.model_dump_json(), malformed, '{invalid'])
    real = LLMGateway(client, gateway(local=True).settings, cache=DiskCache(tmp_path))
    def review():
        return SummaryReview(document_id=result.document.document_id, document_sha256=result.document.sha256,
                             source_pages=[1, 2], source_blocks=blocks)
    rejected = review()
    with pytest.raises(Exception): read_summary(real, result, rejected)
    assert len(rejected.parts) == len(first.parts)
    client.responses.append(second.model_dump_json())
    resumed = review()
    read_summary(real, result, resumed)
    assert resumed.read_audits[0]['validated_batch_cache'] is True
    assert len(client.calls) == 4  # Only the previously failed batch needs a new request.
    assert len(resumed.parts) == len(first.parts) + len(second.parts)
    # Same SHA is insufficient: current source evidence is always rechecked.
    result.document.pages[0].text = result.document.pages[0].text.replace('Cedar', 'Other')
    from adaptive_document_agent.agent.summary_read_cache import cached_reading, reading_cache_key
    key = reading_cache_key(real, result, [blocks[0]], reader._RULES)
    assert cached_reading(real, key, result, [blocks[0]]) is None


def test_format_fingerprint_preserves_string_punctuation_and_scalar_types():
    assert preserves_json_content('{value":1}', '{"value":1}')
    assert not preserves_json_content('{"value":true}', '{"value":1}')
    assert not preserves_json_content('{text":"a,b"}', '{"text":"ab"}')
    assert not preserves_json_content('{value":1}', '{"value":2}')


def test_truncated_reading_does_not_attempt_format_repair():
    from adaptive_document_agent.services.llm.base import LLMResponse
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    from adaptive_document_agent.services.llm.usage import LLMUsage
    result, blocks, valid, client, real = setup()
    class Truncated(MockLLMClient):
        def generate_structured(self, messages, schema, **kwargs):
            self.calls.append(messages)
            raise LLMStructuredOutputError('Truncated', response=LLMResponse(text='{"parts":[',
                usage=LLMUsage(provider='mock', model='fixture', finish_reason='length')))
    client = Truncated()
    real = LLMGateway(client, real.settings)
    outcome = _read_batch(real, result, blocks, Event())
    assert outcome.error is not None and len(client.calls) == 1
    assert outcome.audit['failure_kind'] == 'truncated'


def test_format_repair_checks_cancellation_before_admission():
    from concurrent.futures import CancelledError
    from adaptive_document_agent.services.llm.base import LLMResponse
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    result, blocks, valid, client, real = setup()
    signal = Event()
    signal.set()
    with pytest.raises(CancelledError):
        real.repair_structured_output(LLMStructuredOutputError('Invalid',
            response=LLMResponse(text='{parts":[]}')), SummaryReadBatch, stage='presentation', cancelled=signal)
    assert client.calls == []


def test_batch_cache_identity_respects_model_privacy_endpoint_and_source(tmp_path):
    from adaptive_document_agent.agent.summary_read_cache import reading_cache_key
    from adaptive_document_agent.agent.summary_reader import _RULES
    result, blocks, valid, client, real = setup(cache=DiskCache(tmp_path))
    original = reading_cache_key(real, result, blocks, _RULES)
    for field, value in [('model', 'other'), ('base_url', 'http://127.0.0.1:9999/v1')]:
        settings = real.settings.model_copy(update={field: value})
        other = LLMGateway(MockLLMClient(), settings, cache=real.cache)
        assert reading_cache_key(other, result, blocks, _RULES) != original
    from adaptive_document_agent.services.llm import PrivacyMode
    settings = real.settings.model_copy(update={'privacy_mode': PrivacyMode.CLOUD})
    other = LLMGateway(MockLLMClient(), settings, cache=real.cache)
    assert reading_cache_key(other, result, blocks, _RULES) != original
    changed = blocks[0].model_copy(update={'text': blocks[0].text + ' More evidence.'})
    assert reading_cache_key(real, result, [changed], _RULES) != original
    real.cache_enabled = False
    assert reading_cache_key(real, result, blocks, _RULES) is None
