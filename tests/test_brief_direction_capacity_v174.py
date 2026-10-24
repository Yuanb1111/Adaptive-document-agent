"""Truncated source-blind reviews get capacity, never inferred semantic approval."""
from concurrent.futures import CancelledError
import json
from threading import Event

import pytest

from adaptive_document_agent.agent.brief_claim_direction import review_claim_directions
from adaptive_document_agent.agent.presentation_budget_output import complete_budget_output
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
from adaptive_document_agent.services.llm.exceptions import (
    LLMResponseError, LLMStructuredOutputError, LLMTransportError, PrivacyViolationError,
)
from tests.test_brief_direction_v174 import observed_loss
from tests.test_budget_output_v145 import ScriptedClient, gateway, response


def audit(result):
    return json.loads(next(w.message for w in reversed(result.validation_warnings)
                          if w.code == 'executive_brief_direction_audit'))


@pytest.mark.parametrize('wrong_body', [False, True])
def test_real_length_recovery_preserves_complete_blind_request_and_direction_gate(wrong_body):
    brief, result, source, audience = observed_loss(wrong_body=wrong_body)
    # Even a complete valid JSON reply is unusable with finish_reason=length.
    llm, client = gateway([response(audience, finish='length'), response(audience)])
    errors = review_claim_directions(llm, brief=brief, verdicts=source.items, result=result)
    assert bool(errors) is wrong_body
    if wrong_body:
        assert 'decrease, not increase' in str(errors)
    assert [kw['max_tokens'] for _, kw in client.requests] == [8192, 16384]
    assert client.requests[0][0] == client.requests[1][0]
    payload = json.loads(client.requests[0][0][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert set(payload[0]) == {'index', 'label', 'text', 'comparisons'}
    assert all(set(c) == {'comparison_index', 'claim'} for c in payload[0]['comparisons'])
    recorded = audit(result)
    assert len(recorded['attempts']) == 1
    physical = recorded['attempts'][0]['output_attempts']
    assert [row['status'] for row in physical] == ['truncated', 'response_received']
    assert physical[0]['raw_response'] == audience.model_dump_json()
    assert physical[0]['usage']['finish_reason'] == 'length'


def test_final_length_exhaustion_propagates_without_format_prompt_or_partial_acceptance():
    brief, result, source, audience = observed_loss(wrong_body=False)
    llm, client = gateway([response(audience, finish='length'), response(audience, finish='length'),
                           response(audience)])
    with pytest.raises(LLMStructuredOutputError, match='truncated'):
        review_claim_directions(llm, brief=brief, verdicts=source.items, result=result)
    assert len(client.requests) == 2 and len(client.outputs) == 1
    assert client.requests[0][0] == client.requests[1][0]
    recorded = audit(result)
    assert len(recorded['attempts']) == 1 and 'response' not in recorded['attempts'][0]
    assert 'output capacity' in str(recorded['errors'])
    assert [row['capacity_retry'] for row in recorded['attempts'][0]['output_attempts']] == [True, False]


@pytest.mark.parametrize('invalid', ['syntax', 'item_index', 'comparison_index'])
def test_complete_format_or_index_failure_retains_one_separate_correction(invalid):
    brief, result, source, audience = observed_loss(wrong_body=False)
    broken = audience.model_copy(deep=True)
    if invalid == 'item_index':
        broken.items[0].index = 3
    elif invalid == 'comparison_index':
        broken.items[0].comparisons[1].comparison_index = 0
    bad_response = response('{broken', finish='stop') if invalid == 'syntax' else response(broken)
    llm, client = gateway([response('{partial', finish='length'), bad_response, response(audience)])
    assert review_claim_directions(llm, brief=brief, verdicts=source.items, result=result) == {}
    assert [kw['max_tokens'] for _, kw in client.requests] == [8192, 16384, 8192]
    assert client.requests[0][0] == client.requests[1][0]
    assert client.requests[2][0][:-2] == client.requests[0][0]
    feedback = client.requests[2][0][-2]['content']
    assert '<UNTRUSTED_DOCUMENT_CONTENT>' in feedback
    assert 'previous_response' in feedback and 'validation_error' in feedback
    assert 'exact schema/index bindings' in client.requests[2][0][-1]['content']
    assert len(audit(result)['attempts']) == 2


def test_cancellation_between_length_attempts_reaches_real_gateway_admission():
    brief, result, source, audience = observed_loss(wrong_body=False)
    cancelled = Event()

    class CancellingClient(ScriptedClient):
        def generate_text(self, messages, **kwargs):
            output = super().generate_text(messages, **kwargs)
            cancelled.set()
            return output

    client = CancellingClient([response('{partial', finish='length'), response(audience)])
    llm = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model='mock'))
    with pytest.raises(CancelledError):
        review_claim_directions(llm, brief=brief, verdicts=source.items, result=result, cancelled=cancelled)
    assert len(client.requests) == 1 and len(client.outputs) == 1
    assert [row['status'] for row in audit(result)['attempts'][0]['output_attempts']] == ['truncated', 'cancelled']


@pytest.mark.parametrize('error', [LLMTransportError('offline'), PrivacyViolationError('local only'),
                                  CancelledError('stopped'), LLMResponseError('No complete response')])
def test_non_format_failures_do_not_trigger_capacity_or_format_retries(error):
    brief, result, source, audience = observed_loss(wrong_body=False)
    llm, client = gateway([error, response(audience)])
    with pytest.raises(type(error)):
        review_claim_directions(llm, brief=brief, verdicts=source.items, result=result)
    assert len(client.requests) == 1 and len(client.outputs) == 1
    assert len(audit(result)['attempts']) == 1


def test_optional_cancellation_does_not_change_existing_helper_call_signatures():
    class Gateway:
        def generate_structured(self, messages, schema, *, stage, allow_repair, max_tokens):
            assert (stage, allow_repair, max_tokens) == ('report', False, 8192)
            return 'accepted'
    assert complete_budget_output(Gateway(), [], object, {}, audit_key='outputs',
        token_limits=(8192, 16384), stage='report', cancelled=None) == 'accepted'
