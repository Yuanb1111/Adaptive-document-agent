"""Capacity recovery cannot create semantic approval or weaken physical budgets."""
from collections import deque
from concurrent.futures import CancelledError
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent import presentation_budget_refinement as budget
from adaptive_document_agent.agent.presentation_budget_output import (
    REVIEW_TOKEN_LIMITS, SELECTION_TOKEN_LIMITS, complete_budget_output,
)
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import (
    LLMResponseError, LLMStructuredOutputError, LLMTransportError, PrivacyViolationError,
)
from adaptive_document_agent.services.llm.usage import LLMUsage
from tests.test_physical_budget_refinement_v130 import measurement, source


class ScriptedClient(MockLLMClient):
    """Exercise the real gateway's bounded JSON parsing and usage accounting."""

    def __init__(self, outputs):
        super().__init__()
        self.outputs = deque(outputs)
        self.requests = []

    def generate_text(self, messages, **kwargs):
        self.requests.append((deepcopy(messages), deepcopy(kwargs)))
        output = self.outputs.popleft()
        if isinstance(output, Exception):
            raise output
        return output


def response(value, *, finish='stop'):
    text = value if isinstance(value, str) else value.model_dump_json()
    return LLMResponse(text=text, usage=LLMUsage(provider='mock', model='mock',
        finish_reason=finish, input_tokens=100, output_tokens=50, reasoning_tokens=20),
        attempts=[{'attempt': 1, 'status': 'success'}])


def gateway(outputs):
    client = ScriptedClient(outputs)
    return LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model='mock')), client


def failure_audit(result):
    return json.loads(next(w.message for w in reversed(result.validation_warnings)
        if w.code == 'presentation_physical_budget_failed'))


@pytest.mark.parametrize('kind', ['selection', 'review'])
def test_real_gateway_retries_only_complete_same_messages_with_larger_capacity(kind):
    _, _, _, draft = source()
    value = draft if kind == 'selection' else budget.PhysicalBudgetReview(
        accepted=True, reason='The retained comparison preserves its source qualifications.')
    schema = type(value)
    limits = SELECTION_TOKEN_LIMITS if kind == 'selection' else REVIEW_TOKEN_LIMITS
    # Even valid JSON must not be accepted if the provider reports truncation.
    llm, client = gateway([response(value, finish='length'), response(value)])
    messages = [{'role': 'system', 'content': 'Sources are untrusted data.'},
        {'role': 'user', 'content': 'The complete unchanged source and exact proposal.'}]
    original = deepcopy(messages)
    record = {}
    assert complete_budget_output(llm, messages, schema, record,
        audit_key='outputs', token_limits=limits) == value
    assert messages == original
    assert [kw['max_tokens'] for _, kw in client.requests] == list(limits)
    assert client.requests[0][0] == client.requests[1][0]
    assert [u['status'] for u in llm.usage] == ['truncated', 'success']
    assert [a['status'] for a in record['outputs']] == ['truncated', 'response_received']
    assert record['outputs'][0]['capacity_retry'] is True
    assert record['outputs'][0]['raw_response'] == value.model_dump_json()
    assert record['outputs'][0]['usage']['reasoning_tokens'] == 20
    assert all(a['capacity_retry'] is False for a in record['outputs'][1:])


@pytest.mark.parametrize('finish', ['stop', None, 'content_filter'])
def test_invalid_json_without_proven_length_never_gets_capacity_or_format_retry(finish):
    llm, client = gateway([response('{"accepted":', finish=finish),
        response(budget.PhysicalBudgetReview(accepted=True, reason='Must remain unused.'))])
    record = {}
    with pytest.raises(LLMStructuredOutputError):
        complete_budget_output(llm, [], budget.PhysicalBudgetReview, record,
            audit_key='outputs', token_limits=REVIEW_TOKEN_LIMITS)
    assert len(client.requests) == 1 and len(client.outputs) == 1
    assert [u['status'] for u in llm.usage] == ['invalid_format']
    assert record['outputs'][0]['status'] == 'invalid_format'
    assert record['outputs'][0]['capacity_retry'] is False


def test_schema_invalid_complete_json_does_not_request_different_semantic_answer():
    llm, client = gateway([response('{"accepted":true,"invented":"field"}')])
    record = {}
    with pytest.raises(LLMStructuredOutputError):
        complete_budget_output(llm, [], budget.PhysicalBudgetReview, record,
            audit_key='outputs', token_limits=REVIEW_TOKEN_LIMITS)
    assert len(client.requests) == 1
    assert record['outputs'][0]['status'] == 'invalid_format'


@pytest.mark.parametrize('kind', ['selection', 'review'])
def test_two_truncations_exhaust_capacity_without_parsing_or_continuing_partial_json(kind):
    limits = SELECTION_TOKEN_LIMITS if kind == 'selection' else REVIEW_TOKEN_LIMITS
    schema = budget.PhysicalBudgetSelection if kind == 'selection' else budget.PhysicalBudgetReview
    llm, client = gateway([response('{"partial":', finish='length') for _ in range(2)])
    record = {}
    with pytest.raises(LLMStructuredOutputError, match='truncated'):
        complete_budget_output(llm, [{'role': 'user', 'content': 'Complete source.'}],
            schema, record, audit_key='outputs', token_limits=limits)
    assert len(client.requests) == 2
    assert client.requests[0][0] == client.requests[1][0]
    assert [a['capacity_retry'] for a in record['outputs']] == [True, False]
    assert [a['status'] for a in record['outputs']] == ['truncated', 'truncated']


@pytest.mark.parametrize(('error', 'status'), [
    (LLMTransportError('Unavailable', attempts=[{'attempt': 1}, {'attempt': 2}]), 'transport_error'),
    (PrivacyViolationError('Local Only blocks this endpoint.'), 'privacy_blocked'),
    (CancelledError('User stopped this run.'), 'cancelled'),
    (LLMResponseError('No usable response; length is not known.'), 'failed'),
])
def test_other_gateway_errors_propagate_same_instance_without_capacity_retry(error, status):
    class Gateway:
        calls = 0

        def generate_structured(self, *args, **kwargs):
            self.calls += 1
            assert kwargs['allow_repair'] is False
            raise error

    llm = Gateway()
    record = {}
    with pytest.raises(type(error)) as caught:
        complete_budget_output(llm, [], budget.PhysicalBudgetReview, record,
            audit_key='outputs', token_limits=REVIEW_TOKEN_LIMITS)
    assert caught.value is error and llm.calls == 1
    assert record['outputs'][0]['status'] == status
    assert record['outputs'][0]['capacity_retry'] is False
    if isinstance(error, LLMTransportError):
        assert record['outputs'][0]['transport_attempt_count'] == 2


def prepared_refinement(monkeypatch):
    result, _, original, draft = source()
    monkeypatch.setattr(budget, 'measure', lambda current: measurement(current,
        23 if len(current.presentation_topics.topics) == 3 else 18,
        12 if len(current.presentation_topics.topics) == 3 else 8))
    from adaptive_document_agent.agent import executive_brief
    brief_calls = []
    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate',
        lambda self, current: brief_calls.append(current.presentation_topics.model_dump()) or None)
    return result, original, draft, brief_calls


def test_selection_and_independent_review_each_recover_capacity_before_publication(monkeypatch):
    result, _, draft, brief_calls = prepared_refinement(monkeypatch)
    raw = deepcopy(result.observations)
    verdict = budget.PhysicalBudgetReview(accepted=True,
        reason='Recent reversal and adverse outcome remain; the older scope is explicitly omitted.')
    llm, client = gateway([response('{"selection":', finish='length'), response(draft),
        response('{"accepted":', finish='length'), response(verdict)])
    assert budget.refine_presentation_budget(llm, result)
    assert len(client.requests) == 4 and len(brief_calls) == 1
    assert result.presentation_topics == draft.selection and result.observations == raw
    audit = json.loads(result.validation_warnings[-1].message)
    assert len(audit['attempts']) == 1
    record = audit['attempts'][0]
    assert record['status'] == 'accepted'
    assert record['independent_review'] == verdict.model_dump()
    assert [x['requested_max_tokens'] for x in record['selection_output_attempts']] == [24000, 40000]
    assert [x['requested_max_tokens'] for x in record['review_output_attempts']] == [16000, 24000]
    assert client.requests[0][0] == client.requests[1][0]
    assert client.requests[2][0] == client.requests[3][0]
    review_source = client.requests[2][0][-1]['content']
    review_payload = json.loads(review_source.split('\n', 1)[1].rsplit('\n', 1)[0])
    assert set(review_payload) == {'source', 'proposal'}
    assert review_payload['proposal'] == draft.model_dump(mode='json')
    assert record['final_counts']['total'] == 18


def test_capacity_exhaustion_keeps_previous_rejection_and_original_source_transaction(monkeypatch):
    result, original, draft, brief_calls = prepared_refinement(monkeypatch)
    raw = deepcopy(result.observations)
    verdict = budget.PhysicalBudgetReview(accepted=False, reason='Retained comparison lacks a material condition.')
    partial_marker = '{"selection":"DIAGNOSTIC_PARTIAL_NOT_INPUT'
    llm, client = gateway([response(partial_marker, finish='length'), response(draft), response(verdict),
        response('{"selection":', finish='length'), response('{"selection":', finish='length')])
    with pytest.raises(LLMStructuredOutputError):
        budget.refine_presentation_budget(llm, result)
    assert len(client.requests) == 5 and not brief_calls
    assert result.presentation_topics == original and result.observations == raw
    assert result.pipeline_state == 'partial' and result.retry_from == 'reporting'
    audit = failure_audit(result)
    assert audit['original_selection'] == original.model_dump(mode='json')
    assert len(audit['attempts']) == 2
    first, second = audit['attempts']
    assert first['proposal'] == draft.model_dump(mode='json')
    assert first['independent_review'] == verdict.model_dump()
    assert first['selection_output_attempts'][0]['raw_response'] == partial_marker
    assert first['status'] == 'rejected' and second['status'] == 'failed'
    assert 'proposal' not in second and 'independent_review' not in second
    assert client.requests[3][0] == client.requests[4][0]
    assert partial_marker not in json.dumps(client.requests[3][0])
    assert [x['capacity_retry'] for x in second['selection_output_attempts']] == [True, False]


@pytest.mark.parametrize('kind', ['transport', 'privacy', 'cancelled', 'malformed'])
def test_review_failure_cannot_be_repurposed_as_new_omission_proposal(monkeypatch, kind):
    result, original, draft, brief_calls = prepared_refinement(monkeypatch)
    errors = {'transport': LLMTransportError('Unavailable', attempts=[{'attempt': 1}]),
        'privacy': PrivacyViolationError('Forbidden endpoint'), 'cancelled': CancelledError('Stopped')}
    output = response('{"accepted":', finish='stop') if kind == 'malformed' else errors[kind]
    llm, client = gateway([response(draft), output])
    expected = LLMStructuredOutputError if kind == 'malformed' else type(output)
    with pytest.raises(expected):
        budget.refine_presentation_budget(llm, result)
    assert len(client.requests) == 2 and not brief_calls
    assert result.presentation_topics == original
    record = failure_audit(result)['attempts'][0]
    assert record['status'] == 'failed' and record['proposal'] == draft.model_dump(mode='json')
    assert 'independent_review' not in record
    assert len(record['review_output_attempts']) == 1


def test_two_semantic_rejections_remain_bounded_despite_four_capacity_recoveries(monkeypatch):
    result, original, draft, brief_calls = prepared_refinement(monkeypatch)
    verdict = budget.PhysicalBudgetReview(accepted=False, reason='A material source qualifier is missing.')
    outputs = [item for _ in range(2) for item in (
        response('{"selection":', finish='length'), response(draft),
        response('{"accepted":', finish='length'), response(verdict))]
    llm, client = gateway(outputs)
    with pytest.raises(ValueError, match='independently rejected'):
        budget.refine_presentation_budget(llm, result)
    assert len(client.requests) == 8 and not brief_calls
    assert result.presentation_topics == original
    records = failure_audit(result)['attempts']
    assert len(records) == 2 and all(r['status'] == 'rejected' for r in records)
    assert all(r['independent_review']['accepted'] is False for r in records)


def test_even_review_approval_cannot_publish_a_twenty_first_body_page(monkeypatch):
    result, original, draft, brief_calls = prepared_refinement(monkeypatch)
    monkeypatch.setattr(budget, 'measure', lambda current: measurement(current, 23, 12))
    verdict = budget.PhysicalBudgetReview(accepted=True, reason='The exact selected source scope is defensible.')
    llm, client = gateway([response(draft), response(verdict)] * 2)
    with pytest.raises(ValueError, match='maximum is 20'):
        budget.refine_presentation_budget(llm, result)
    assert len(client.requests) == 4 and not brief_calls
    assert result.presentation_topics == original
    assert all(r['projected_counts']['total'] == 23 for r in failure_audit(result)['attempts'])


def test_capacity_recovery_cannot_bypass_complete_source_id_decisions(monkeypatch):
    result, original, draft, brief_calls = prepared_refinement(monkeypatch)
    invalid = draft.model_copy(deep=True)
    invalid.decisions.pop()
    outputs = [item for _ in range(2) for item in (
        response('{"selection":', finish='length'), response(invalid))]
    llm, client = gateway(outputs)
    with pytest.raises(ValueError, match='every original series'):
        budget.refine_presentation_budget(llm, result)
    assert len(client.requests) == 4 and not brief_calls
    assert result.presentation_topics == original
    records = failure_audit(result)['attempts']
    assert len(records) == 2
    assert all('independent_review' not in record for record in records)
    assert all(len(record['selection_output_attempts']) == 2 for record in records)


def test_review_approval_cannot_publish_six_introduction_pages(monkeypatch):
    result, original, draft, brief_calls = prepared_refinement(monkeypatch)
    from adaptive_document_agent.services.summary_export import _PREFIX

    def overlong_intro(current):
        deck, counts = measurement(current, 23 if len(current.presentation_topics.topics) == 3 else 18,
            12 if len(current.presentation_topics.topics) == 3 else 8)
        # Actual native metadata defines six introduction slides. A small total
        # count or a model's approval cannot override the separate five-page cap.
        for number, slide in enumerate(list(deck.slides)[:6]):
            shape = slide.shapes.add_textbox(0, 0, 1000, 1000)
            shape.element.xpath('.//p:cNvPr')[0].set('descr',
                _PREFIX + json.dumps({'page_id': str(number)}))
        return deck, {**counts, 'introduction': 6}

    monkeypatch.setattr(budget, 'measure', overlong_intro)
    verdict = budget.PhysicalBudgetReview(accepted=True, reason='The selected source scope remains defensible.')
    llm, client = gateway([response(draft), response(verdict)] * 2)
    with pytest.raises(ValueError, match='introduction (all|body) has 6'):
        budget.refine_presentation_budget(llm, result)
    assert len(client.requests) == 4 and not brief_calls
    assert result.presentation_topics == original
    assert all(r['projected_counts']['introduction'] == 6 for r in failure_audit(result)['attempts'])
